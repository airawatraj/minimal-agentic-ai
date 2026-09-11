"""
Self-contained verification suite auditing:
1. is_mock_evaluation_enabled() boolean parsing and truthiness safety.
2. _load_env() parsing, precedence, and edge cases.
3. Code parity between src/*.py and docs/index.html code snippets.
"""

import os
import sys
import tempfile
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def test_mock_eval_truthiness():
    print("\n[Test 1] Auditing is_mock_evaluation_enabled() truthiness safety...")
    from src.eval_agent import is_mock_evaluation_enabled

    truthy_cases = ["1", "true", "TRUE", "True", "yes", "YES", "on", "ON", "  true  "]
    falsy_cases = ["0", "false", "FALSE", "False", "no", "NO", "off", "OFF", "", "   ", "random", "none"]

    for val in truthy_cases:
        os.environ["MOCK_EVAL"] = val
        assert is_mock_evaluation_enabled() is True, f"Expected True for MOCK_EVAL={repr(val)}"
        print(f"  ✓ Truthy correctly parsed: MOCK_EVAL={repr(val)} -> True")

    for val in falsy_cases:
        os.environ["MOCK_EVAL"] = val
        assert is_mock_evaluation_enabled() is False, f"Expected False for MOCK_EVAL={repr(val)}"
        print(f"  ✓ Falsy correctly parsed: MOCK_EVAL={repr(val)} -> False")

    # Unset case
    os.environ.pop("MOCK_EVAL", None)
    assert is_mock_evaluation_enabled() is False, "Expected False when MOCK_EVAL is unset"
    print("  ✓ Unset correctly parsed: MOCK_EVAL=None -> False")

    # Truthiness trap demonstration
    assert bool("0") is True, "Sanity check: standard python bool('0') is True"
    assert is_mock_evaluation_enabled() is False, "Verified: is_mock_evaluation_enabled() avoids bool('0') trap"
    print("  ✓ Confirmed: Truthiness trap averted (string '0' does not trigger mock mode)")


def test_load_env_logic():
    print("\n[Test 2] Auditing _load_env() loading and precedence...")
    from src.agent import _load_env

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        env_file = tmp_path / ".env"

        env_content = """
# Sample comment line
   # Indented comment line

TEST_SIMPLE=simple_value
TEST_DOUBLE_QUOTES="double quoted value"
TEST_SINGLE_QUOTES='single quoted value'
TEST_WITH_SPACES = spaced value  
TEST_EMPTY_VALUE=""
TEST_INLINE_UNQUOTED=inline_val # this is an inline comment
TEST_INLINE_QUOTED="quoted_val" # inline comment after quote
TEST_HASH_IN_QUOTES="http://example.com/api#fragment"
TEST_HASH_IN_SINGLE='single#fragment'
TEST_PREEXISTING=from_dot_env
"""
        env_file.write_text(env_content, encoding="utf-8")

        # Set up a preexisting environment variable to test precedence
        os.environ["TEST_PREEXISTING"] = "from_shell"

        # Change cwd to tmpdir to test loading
        orig_cwd = os.getcwd()
        test_keys = [
            "TEST_SIMPLE",
            "TEST_DOUBLE_QUOTES",
            "TEST_SINGLE_QUOTES",
            "TEST_WITH_SPACES",
            "TEST_EMPTY_VALUE",
            "TEST_INLINE_UNQUOTED",
            "TEST_INLINE_QUOTED",
            "TEST_HASH_IN_QUOTES",
            "TEST_HASH_IN_SINGLE",
            "TEST_PREEXISTING",
        ]
        try:
            os.chdir(tmpdir)
            _load_env()

            assert os.environ.get("TEST_SIMPLE") == "simple_value", "Failed TEST_SIMPLE"
            print("  ✓ Injected simple variable: TEST_SIMPLE='simple_value'")

            assert os.environ.get("TEST_DOUBLE_QUOTES") == "double quoted value", "Failed TEST_DOUBLE_QUOTES"
            print("  ✓ Stripped double quotes: TEST_DOUBLE_QUOTES='double quoted value'")

            assert os.environ.get("TEST_SINGLE_QUOTES") == "single quoted value", "Failed TEST_SINGLE_QUOTES"
            print("  ✓ Stripped single quotes: TEST_SINGLE_QUOTES='single quoted value'")

            assert os.environ.get("TEST_WITH_SPACES") == "spaced value", "Failed TEST_WITH_SPACES"
            print("  ✓ Trimmed whitespace: TEST_WITH_SPACES='spaced value'")

            assert os.environ.get("TEST_EMPTY_VALUE") == "", "Failed TEST_EMPTY_VALUE"
            print("  ✓ Empty value handled: TEST_EMPTY_VALUE=''")

            assert os.environ.get("TEST_INLINE_UNQUOTED") == "inline_val", f"Failed TEST_INLINE_UNQUOTED: got {repr(os.environ.get('TEST_INLINE_UNQUOTED'))}"
            print("  ✓ Inline comment stripped from unquoted value: TEST_INLINE_UNQUOTED='inline_val'")

            assert os.environ.get("TEST_INLINE_QUOTED") == "quoted_val", f"Failed TEST_INLINE_QUOTED: got {repr(os.environ.get('TEST_INLINE_QUOTED'))}"
            print("  ✓ Inline comment stripped after quoted value: TEST_INLINE_QUOTED='quoted_val'")

            assert os.environ.get("TEST_HASH_IN_QUOTES") == "http://example.com/api#fragment", f"Failed TEST_HASH_IN_QUOTES: got {repr(os.environ.get('TEST_HASH_IN_QUOTES'))}"
            print("  ✓ Preserved '#' inside double quotes: TEST_HASH_IN_QUOTES='http://example.com/api#fragment'")

            assert os.environ.get("TEST_HASH_IN_SINGLE") == "single#fragment", f"Failed TEST_HASH_IN_SINGLE: got {repr(os.environ.get('TEST_HASH_IN_SINGLE'))}"
            print("  ✓ Preserved '#' inside single quotes: TEST_HASH_IN_SINGLE='single#fragment'")

            assert os.environ.get("TEST_PREEXISTING") == "from_shell", "Precedence failed: shell var was overwritten!"
            print("  ✓ Shell precedence respected: TEST_PREEXISTING remains 'from_shell' (not overwritten)")

        finally:
            os.chdir(orig_cwd)
            for k in test_keys:
                os.environ.pop(k, None)


def test_code_parity():
    print("\n[Test 3] Auditing code parity across src/ and docs/index.html...")

    src_files = [
        "src/agent.py",
        "src/graph_agent.py",
        "src/sqlite_agent.py",
        "src/eval_agent.py",
        "src/optimized_eval_agent.py",
    ]

    # Verify each src file contains _load_env logic
    for path_str in src_files:
        content = (PROJECT_ROOT / path_str).read_text(encoding="utf-8")
        assert "def _load_env():" in content, f"Missing _load_env() in {path_str}"
        assert "_load_env()" in content, f"Missing _load_env() invocation in {path_str}"
        print(f"  ✓ {path_str} contains _load_env() definition and invocation")

    # Check docs/index.html snippets
    html_path = PROJECT_ROOT / "docs" / "index.html"
    assert html_path.exists(), "docs/index.html missing!"
    html_content = html_path.read_text(encoding="utf-8")

    mapping = [
        ("code-1", "src/agent.py"),
        ("code-2", "src/graph_agent.py"),
        ("code-3", "src/sqlite_agent.py"),
        ("code-4", "src/eval_agent.py"),
        ("code-5", "src/optimized_eval_agent.py"),
    ]

    discrepancies = []
    for code_id, src_rel in mapping:
        pattern = rf"<code[^>]*id=\"{code_id}\"[^>]*>(.*?)</code>"
        match = re.search(pattern, html_content, re.DOTALL)
        assert match, f"Code element with id='{code_id}' not found in docs/index.html"

        html_snippet = match.group(1).strip()
        src_code = (PROJECT_ROOT / src_rel).read_text(encoding="utf-8").strip()

        if html_snippet != src_code:
            discrepancies.append((code_id, src_rel, len(html_snippet.splitlines()), len(src_code.splitlines())))
            print(f"  ✗ Parity mismatch for {code_id} ({src_rel}): HTML has {len(html_snippet.splitlines())} lines, src has {len(src_code.splitlines())} lines")
        else:
            print(f"  ✓ Exact parity for {code_id} <-> {src_rel}")

    assert len(discrepancies) == 0, f"Found {len(discrepancies)} code parity mismatches between docs/index.html and src/!"


if __name__ == "__main__":
    print("=" * 60)
    print("STARTING REPOSITORY CONFIGURATION & CODE PARITY AUDIT")
    print("=" * 60)

    try:
        test_mock_eval_truthiness()
        test_load_env_logic()
        test_code_parity()
        print("\n" + "=" * 60)
        print("ALL AUDIT TESTS PASSED (100% PARITY & CONFIG INTEGRITY)")
        print("=" * 60)
        sys.exit(0)
    except AssertionError as e:
        print(f"\n[AUDIT FAILURE]: {e}")
        sys.exit(1)
