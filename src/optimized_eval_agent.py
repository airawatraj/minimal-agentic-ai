import inspect
import json
import os
import re
import sqlite3
import time
from typing import List
from openai import OpenAI
from pydantic import BaseModel, Field

BASE_URL = os.getenv("OPENAI_BASE_URL", "http://192.168.20.91:8000/v1")
API_KEY = os.getenv("OPENAI_API_KEY", "none")
MODEL_NAME = os.getenv("OPENAI_MODEL", "Cogni-Brain")

client = OpenAI(
    base_url=BASE_URL,
    api_key=API_KEY,
)

# 1. Sandbox Database Fixture
conn = sqlite3.connect(":memory:")
cur = conn.cursor()
cur.execute("CREATE TABLE employees (id INT, name TEXT, department TEXT, salary INT);")
cur.executemany(
    "INSERT INTO employees VALUES (?, ?, ?, ?);",
    [
        (1, "Alice Smith", "Engineering", 145000),
        (2, "Bob Jones", "Marketing", 95000),
        (3, "Charlie Brown", "Engineering", 160000),
        (4, "Dana White", "Sales", 110000),
        (5, "Evan Wright", "Engineering", 135000),
        (6, "Fiona Gallagher", "Finance", 125000),
        (7, "George Clark", "Sales", 98000),
    ],
)
conn.commit()

# Optimization 1: Pre-Cached Static Schema (Saves 1 round-trip of inference)
CACHED_SCHEMA = "CREATE TABLE employees (id INT, name TEXT, department TEXT, salary INT);"

def execute_query(sql_query: str) -> str:
    """Executes a read-only SELECT query against the SQLite database."""
    clean = sql_query.strip().rstrip(";")
    if not clean.upper().startswith("SELECT"):
        return "Security Violation: Only SELECT queries permitted."
    try:
        c = conn.cursor()
        c.execute(clean)
        return str(c.fetchall()[:5])
    except Exception as e:
        return f"SQL Error: {e}"

TOOL_MAP = {"execute_query": execute_query}

def function_to_schema(func):
    sig = inspect.signature(func)
    type_map = {int: "integer", float: "number", str: "string", bool: "boolean"}
    props = {n: {"type": type_map.get(p.annotation, "string")} for n, p in sig.parameters.items()}
    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": func.__doc__ or "",
            "parameters": {"type": "object", "properties": props},
        },
    }

tools = [function_to_schema(execute_query)]

# Optimization 2: Turn-0 Input Guard (Microsecond Refusal before LLM execution)
def pre_execution_guard(prompt: str) -> bool:
    destructive_keywords = ["DELETE", "DROP", "TRUNCATE", "ALTER", "UPDATE", "INSERT"]
    pattern = rf"\b({'|'.join(destructive_keywords)})\b"
    return bool(re.search(pattern, prompt, re.IGNORECASE))

# Optimization 3: Cumulative Token Budget Guardrail Container
class SessionContext(BaseModel):
    query: str
    messages: List[dict] = Field(default_factory=list)
    tokens_consumed: int = 0
    max_token_budget: int = 4000  # Hard ceiling on cost and VRAM usage

def execute_production_agent(query: str):
    start = time.time()

    # 1. Turn-0 Fast Path (0ms inference cost)
    if pre_execution_guard(query):
        return {
            "output": "Security Violation: Destructive operation blocked at intake.",
            "turns": 0,
            "duration": round(time.time() - start, 4),
            "guarded": True,
        }

    # 2. Schema inlining eliminates discovery turn
    ctx = SessionContext(query=query)
    system_prompt = (
        f"You are a database assistant with access to this schema:\n{CACHED_SCHEMA}\n"
        f"Use execute_query only when querying database records."
    )
    ctx.messages.append({"role": "system", "content": system_prompt})
    ctx.messages.append({"role": "user", "content": query})

    turn = 0
    while turn < 4:
        turn += 1

        # Guardrail: Check Token Budget
        current_tokens = sum(len(json.dumps(m)) // 4 for m in ctx.messages)
        if current_tokens > ctx.max_token_budget:
            return {"output": "Terminated: Exceeded session token budget.", "turns": turn, "duration": 0.0, "guarded": False}

        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=ctx.messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.0,
        )
        msg = resp.choices[0].message
        ctx.messages.append(msg.model_dump())

        if not msg.tool_calls:
            return {
                "output": msg.content,
                "turns": turn,
                "duration": round(time.time() - start, 2),
                "guarded": False,
            }

        for call in msg.tool_calls:
            name = call.function.name
            args = json.loads(call.function.arguments) if call.function.arguments else {}
            res = TOOL_MAP[name](**args)
            ctx.messages.append({"role": "tool", "tool_call_id": call.id, "name": name, "content": str(res)})

# Verify optimizations
if __name__ == "__main__":
    print("--- 1. Optimized Adversarial Refusal (Turn 0) ---")
    res_adv = execute_production_agent("Delete all employees from Finance.")
    print(f"Turns: {res_adv['turns']} | Time: {res_adv['duration']}s | Output: {res_adv['output']}")

    print("\n--- 2. Optimized Query Execution (Inlined Schema) ---")
    res_query = execute_production_agent("Who has the lowest salary in Sales?")
    print(f"Turns: {res_query['turns']} | Time: {res_query['duration']}s | Output: {res_query['output'].strip()[:80]}...")
