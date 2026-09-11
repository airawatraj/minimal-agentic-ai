import concurrent.futures
import inspect
import json
import os
from pathlib import Path
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



# --- 1. Tool Registry ---
def add_numbers(a: float, b: float) -> str:
    """Add two numbers together."""
    return str(a + b)

def multiply_numbers(a: float, b: float) -> str:
    """Multiply two numbers together."""
    return str(a * b)

def divide_numbers(a: float, b: float) -> str:
    """Divide a by b. Raises ZeroDivisionError if b is 0."""
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero.")
    return str(a / b)

TOOL_MAP = {
    "add_numbers": add_numbers,
    "multiply_numbers": multiply_numbers,
    "divide_numbers": divide_numbers,
}

# --- 2. Dynamic Schema Generator via inspect ---
def function_to_schema(func):
    sig = inspect.signature(func)
    type_map = {int: "integer", float: "number", str: "string", bool: "boolean"}
    properties = {}
    required = []

    for name, param in sig.parameters.items():
        param_type = type_map.get(param.annotation, "string")
        properties[name] = {"type": param_type}
        if param.default == inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": func.__doc__ or "",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }

tools = [function_to_schema(fn) for fn in TOOL_MAP.values()]

# Helper for executing an individual tool call safely
def execute_single_tool(call) -> dict:
    func_name = call.function.name
    raw_args = call.function.arguments
    print(f"Executing: {func_name}({raw_args})")

    try:
        if func_name in TOOL_MAP:
            args = json.loads(raw_args)
            result = TOOL_MAP[func_name](**args)
        else:
            result = f"Error: Tool '{func_name}' not found."
    except Exception as exc:
        result = f"Runtime Error in {func_name}: {type(exc).__name__} - {str(exc)}"

    return {
        "role": "tool",
        "tool_call_id": call.id,
        "name": func_name,
        "content": str(result),
    }

# --- 3. ReAct Control Loop with Parallel Tool Execution ---
def run_agent(prompt: str):
    messages = [{"role": "user", "content": prompt}]
    max_turns = 5
    turn = 0

    print(f"User Query: {prompt}\n")

    while turn < max_turns:
        turn += 1
        print(f"--- Turn {turn} ---")

        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.0,
        )

        assistant_message = response.choices[0].message
        messages.append(assistant_message)

        if not assistant_message.tool_calls:
            print(f"\nFinal Answer:\n{assistant_message.content}")
            return assistant_message.content

        # Parallel tool dispatch: Execute all returned tool calls concurrently
        with concurrent.futures.ThreadPoolExecutor() as executor:
            observations = list(executor.map(execute_single_tool, assistant_message.tool_calls))

        # Append observations in order
        for obs in observations:
            print(f"Observation Fed Back: {obs['content']}")
            messages.append(obs)
    else:
        print("Guardrail hit: Max turns exhausted.")
        return None

if __name__ == "__main__":
    test_prompt = "Divide 50 by 0. If that fails, divide 50 by 2 instead."
    run_agent(test_prompt)
