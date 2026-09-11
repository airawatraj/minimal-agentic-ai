import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, Optional
from openai import OpenAI
from pydantic import BaseModel

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
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))
            break

_load_env()

client = OpenAI(
    base_url=os.getenv("COGNI_BASE_URL", "http://localhost:8000/v1"),
    api_key=os.getenv("COGNI_API_KEY", "none"),
)
MODEL_NAME = os.getenv("COGNI_MODEL", "Cogni-Brain")



STATE_FILE = Path("agent_checkpoint.json")

# --- 1. Typed State Container with Suspension ---
class GraphState(BaseModel):
    task: str
    code_draft: Optional[str] = None
    execution_output: Optional[str] = None
    execution_error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2
    status: Literal["RUNNING", "SUSPENDED_AWAITING_APPROVAL", "PASSED", "FAILED", "ABORTED"] = "RUNNING"


# --- 2. Node A: Generator (LLM) ---
def generator_node(state: GraphState) -> GraphState:
    print(f"\n[Node: Generator] Attempt #{state.retry_count + 1}")

    prompt = f"Task:\n{state.task}\n"
    if state.execution_error:
        prompt += f"\nYour previous code failed tests with this error:\n{state.execution_error}\nFix the bug."

    prompt += "\nOutput ONLY valid Python code inside a single ```python ... ``` block."

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    content = response.choices[0].message.content or ""
    if "```python" in content:
        code = content.split("```python")[1].split("```")[0].strip()
    elif "```" in content:
        code = content.split("```")[1].split("```")[0].strip()
    else:
        code = content.strip()

    state.code_draft = code
    return state


# --- 3. Node B: Non-Blocking State Suspension (Production HITL) ---
def suspend_for_approval_node(state: GraphState) -> GraphState:
    """Instead of freezing the process with input(), save state and exit gracefully."""
    print("\n[Node: State Suspension] Sensitive operation detected. Suspending execution...")
    state.status = "SUSPENDED_AWAITING_APPROVAL"
    STATE_FILE.write_text(state.model_dump_json(indent=2))
    print(f"  >>> State persisted to {STATE_FILE.name}. Safe to shut down or reload.")
    return state


# --- 4. Node C: Verifier (Subprocess Test Runner) ---
def verifier_node(state: GraphState) -> GraphState:
    print("[Node: Verifier] Executing code against hidden assertions...")

    test_harness = """
assert remove_vowels("Hello World") == "Hll Wrld", "Failed standard test"
assert remove_vowels("AEIOU") == "", "Failed uppercase test"
assert remove_vowels("") == "", "Failed empty test"
print("ALL_TESTS_PASSED")
"""
    full_script = (state.code_draft or "") + "\n" + test_harness

    try:
        run_res = subprocess.run(
            [sys.executable, "-c", full_script],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if run_res.returncode != 0:
            state.execution_output = None
            state.execution_error = f"Test Failure:\n{run_res.stderr.strip()}"
            state.retry_count += 1
            print(f"  >>> Verification Failed:\n{state.execution_error}")
            return state

        output = run_res.stdout.strip()
        if "ALL_TESTS_PASSED" in output:
            state.execution_output = "All assertions passed successfully."
            state.execution_error = None
            state.status = "PASSED"
            print("  >>> Verification Passed!")
        else:
            state.execution_error = f"Unexpected output: {output}"
            state.retry_count += 1

    except Exception as exc:
        state.execution_error = str(exc)
        state.retry_count += 1

    return state


# --- 5. Deterministic Router ---
def route_after_verifier(state: GraphState) -> Literal["generator", "end"]:
    if state.status == "PASSED":
        return "end"
    if state.retry_count >= state.max_retries:
        print("\n[Router] Max retries exhausted. Halting.")
        state.status = "FAILED"
        return "end"

    print("\n[Router] Verification failed. Routing back to Generator for self-correction...")
    return "generator"


# --- 6. The Execution Runner (Supports Resuming from Disk) ---
def run_graph(initial_task: str, approval_override: Optional[bool] = None) -> GraphState:
    # Resume from checkpoint if it exists and approval is granted
    if STATE_FILE.exists() and approval_override is not None:
        print(f"Loading checkpoint from {STATE_FILE.name}...")
        state = GraphState.model_validate_json(STATE_FILE.read_text())
        if approval_override is True:
            print(">> Human approval granted. Resuming execution.")
            state.status = "RUNNING"
            current_node = "verifier"
            STATE_FILE.unlink(missing_ok=True)
        else:
            print(">> Human rejected execution.")
            state.status = "ABORTED"
            STATE_FILE.unlink(missing_ok=True)
            return state
    else:
        state = GraphState(task=initial_task)
        current_node = "generator"

    while current_node != "end":
        if current_node == "generator":
            state = generator_node(state)
            current_node = "approval"

        elif current_node == "approval":
            state = suspend_for_approval_node(state)
            # Clean exit: Process shuts down here and waits for external event
            return state

        elif current_node == "verifier":
            state = verifier_node(state)
            current_node = route_after_verifier(state)

    print(f"\n=== Graph Status: {state.status} ===")
    if state.status == "PASSED":
        print(f"Final Output: {state.execution_output}")
    return state


if __name__ == "__main__":
    task_input = (
        "Write a Python function named `remove_vowels(s: str) -> str` "
        "that removes vowels (a, e, i, o, u) from a string."
    )

    # Clean any stale checkpoint
    STATE_FILE.unlink(missing_ok=True)

    # Run 1: Generates code, dumps checkpoint, and exits cleanly
    print("--- Phase A: Initial Generation & State Suspension ---")
    run_graph(task_input)

    # Run 2: Simulating resuming execution after human verifies the JSON file
    print("\n--- Phase B: Resuming from Disk with Approval ---")
    run_graph(task_input, approval_override=True)
