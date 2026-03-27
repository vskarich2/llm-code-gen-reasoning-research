"""Tier 1 (T1.4): Parse logic — JSON parsing, code extraction, import stripping."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parse import parse_model_response
from exec_eval import extract_code, _strip_local_imports


def test_parse_json_valid():
    raw = '{"reasoning": "looks good", "code": "def f(): return 1"}'
    r = parse_model_response(raw)
    assert r["code"] == "def f(): return 1"
    assert r["reasoning"] == "looks good"
    assert r["parse_error"] is None


def test_parse_json_wrapped():
    raw = 'Here is the fix:\n{"reasoning": "x", "code": "def f(): pass"}\nDone.'
    r = parse_model_response(raw)
    assert r["code"] == "def f(): pass"
    assert r["parse_error"] is None


def test_parse_code_block_fallback():
    raw = "Explanation here.\n```python\ndef f():\n    return 42\n```\nEnd."
    r = parse_model_response(raw)
    assert "return 42" in r["code"]
    assert r["parse_error"] is not None  # not JSON


def test_parse_raw_fallback():
    raw = "def f(): return 1"
    r = parse_model_response(raw)
    assert "def f()" in r["code"]
    assert r["parse_error"] is not None


def test_parse_malformed_json():
    raw = '{"reasoning": "x", "code":'
    r = parse_model_response(raw)
    assert r["parse_error"] is not None
    # Must not crash


def test_strip_imports_multiline():
    code = (
        "from cache_writer import (\n"
        "    cache_put,\n"
        "    cache_delete,\n"
        ")\n"
        "import json\n"
        "import random\n"
        "from state import make_state\n"
        "x = 1\n"
    )
    cleaned = _strip_local_imports(code)
    assert "import json" in cleaned
    assert "import random" in cleaned
    assert "from cache_writer" not in cleaned
    assert "from state import" not in cleaned
    assert "x = 1" in cleaned


def test_multiple_code_blocks_selects_last():
    raw = (
        "First attempt:\n```python\ndef f(): return 1\n```\n"
        "Actually, better:\n```python\ndef f(): return 2\n```\n"
    )
    code = extract_code(raw)
    assert "return 2" in code
    assert "return 1" not in code


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  PASS  {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
