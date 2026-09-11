import inspect
import json
import os
from pathlib import Path
import sqlite3
from typing import List
from openai import OpenAI

def _load_env():
    """Load local .env file into environment if present."""
    candidates = [Path(".env")]
    if "__file__" in globals():
        candidates.append(Path(__file__).resolve().parent.parent / ".env")
    for path in candidates:
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if v.startswith(('"', "'")):
                        quote = v[0]
                        end_idx = v.find(quote, 1)
                        v = v[1:end_idx] if end_idx != -1 else v.strip(quote)
                    else:
                        for sep in (" #", "\t#"):
                            if sep in v:
                                v = v.split(sep, 1)[0]
                        v = v.strip()
                    os.environ.setdefault(k, v)
            break

_load_env()

client = OpenAI(
    base_url=os.getenv("COGNI_BASE_URL", "http://localhost:8000/v1"),
    api_key=os.getenv("COGNI_API_KEY", "none"),
)
MODEL_NAME = os.getenv("COGNI_MODEL", "Cogni-Brain")



# --- 1. SQLite In-Memory Setup ---
def create_connection():
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
    return conn

conn = create_connection()

# --- 2. Hardened Tools with Payload Ceilings ---
def get_schema() -> str:
    """Returns database table schemas."""
    c = conn.cursor()
    c.execute("SELECT sql FROM sqlite_master WHERE type='table';")
    return "\n".join(r[0] for r in c.fetchall() if r[0])

def execute_query(sql_query: str) -> str:
    """Executes a strictly READ-ONLY SELECT query and formats results as Markdown."""
    clean = sql_query.strip().rstrip(";")
    for bad in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE"]:
        if f" {bad} " in f" {clean.upper()} ":
            return f"Security Violation: '{bad}' statements are forbidden."

    if not clean.upper().startswith("SELECT"):
        return "Security Violation: Only SELECT queries permitted."

    try:
        c = conn.cursor()
        c.execute(clean)
        rows = c.fetchall()
        cols = [d[0] for d in c.description] if c.description else []
        if not rows:
            return "0 rows returned."

        # Compaction: Cap display rows at 5 to defend the context window
        display_rows = rows[:5]
        header = "| " + " | ".join(cols) + " |"
        divider = "| " + " | ".join(["---"] * len(cols)) + " |"
        body = ["| " + " | ".join(str(v) for v in r) + " |" for r in display_rows]

        table = "\n".join([header, divider] + body)
        if len(rows) > 5:
            table += f"\n\n[Truncated: showing 5 of {len(rows)} total rows.]"
        return table
    except Exception as e:
        return f"SQL Error: {e}"

TOOL_MAP = {"get_schema": get_schema, "execute_query": execute_query}

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

tools = [function_to_schema(fn) for fn in TOOL_MAP.values()]

# --- 3. Run Agent with Context Eviction ---
def run_db_agent(query: str):
    messages = [
        {"role": "system", "content": "You are a database assistant. Answer using read-only SQL tools."},
        {"role": "user", "content": query},
    ]

    for turn in range(1, 6):
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.0,
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump())

        if not msg.tool_calls:
            print(f"\nFinal Answer:\n{msg.content}")
            break

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments) if call.function.arguments else {}
            res = TOOL_MAP[call.function.name](**args)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.function.name,
                "content": str(res),
            })

    # Scratchpad Eviction: Discard verbose tool outputs before long-term storage
    evicted_history = [
        m for m in messages
        if m.get("role") in ["system", "user"] or (m.get("role") == "assistant" and not m.get("tool_calls"))
    ]
    print(f"\nContext size before eviction: {sum(len(json.dumps(m))//4 for m in messages)} tokens")
    print(f"Context size after eviction:  {sum(len(json.dumps(m))//4 for m in evicted_history)} tokens")
    return messages, evicted_history

if __name__ == "__main__":
    run_db_agent("Find the highest paid employee in Engineering and their salary.")
