"""Integration tests for the evaluation pipeline.

Tests that EVERY case:
1. Has a resolvable test in the production eval path
2. Correctly fails on buggy code
3. Correctly passes on reference fix code
4. Never silently returns score=0.5 (no-test sentinel)
5. Handles simulated correct and incorrect agent outputs

Run: .venv/bin/python -m pytest tests/test_eval_integration.py -v
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "sk-dummy")

from exec_eval import (
    _CASE_TESTS,
    _load_v2_test,
    load_module_from_code,
    exec_evaluate,
)

BASE = Path(__file__).resolve().parents[1]

_STDLIB = {
    "os", "sys", "json", "re", "math", "copy", "collections", "functools",
    "itertools", "typing", "pathlib", "datetime", "abc", "dataclasses",
    "enum", "logging", "hashlib", "random", "io", "string", "textwrap",
}


def _strip_local_imports(code: str) -> str:
    lines = []
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("from ") and " import " in s:
            mod = s.split()[1].split(".")[0]
            if mod not in _STDLIB:
                continue
        lines.append(line)
    return "\n".join(lines)


def _load_buggy_code(case: dict) -> str:
    parts = []
    for rel in case["code_files"]:
        parts.append((BASE / rel).read_text(encoding="utf-8"))
    return _strip_local_imports("\n\n".join(parts))


def _load_reference_code(case: dict) -> str:
    ref_path = BASE / "reference_fixes" / f"{case['id']}.py"
    ref_code = ref_path.read_text(encoding="utf-8")
    bug_file = case.get("reference_fix", {}).get("file", "")
    other_parts = []
    for rel in case["code_files"]:
        if rel != bug_file:
            path = BASE / rel
            if path.exists():
                other_parts.append(path.read_text(encoding="utf-8"))
    if other_parts:
        return _strip_local_imports("\n\n".join(other_parts) + "\n\n" + ref_code)
    return _strip_local_imports(ref_code)


# Load all cases once
_ALL_CASES = json.loads((BASE / "cases_v2.json").read_text())
_CASE_IDS = [c["id"] for c in _ALL_CASES]


# ============================================================
# TEST 1: Every case has a resolvable test function
# ============================================================

class TestEveryTestResolves:
    """No case should silently lack a test in the production eval path."""

    @pytest.mark.parametrize("case_id", _CASE_IDS)
    def test_resolves(self, case_id):
        case = next(c for c in _ALL_CASES if c["id"] == case_id)
        test_fn = _CASE_TESTS.get(case_id) or _load_v2_test(case)
        assert test_fn is not None, (
            f"Case {case_id} has NO test function. "
            f"family={case.get('family')}, difficulty={case.get('difficulty')}. "
            f"Neither _CASE_TESTS['{case_id}'] nor _load_v2_test resolved."
        )


# ============================================================
# TEST 2: Every test correctly FAILS on buggy code
# ============================================================

class TestBuggyCodeFails:
    """The buggy code shipped with each case must fail its test."""

    @pytest.mark.parametrize("case_id", _CASE_IDS)
    def test_fails_on_buggy(self, case_id):
        case = next(c for c in _ALL_CASES if c["id"] == case_id)
        test_fn = _CASE_TESTS.get(case_id) or _load_v2_test(case)
        assert test_fn is not None, f"No test for {case_id}"

        code = _load_buggy_code(case)
        mod = load_module_from_code(code, f"buggy_{case_id}")
        passed, reasons = test_fn(mod)
        assert not passed, (
            f"Test PASSES on buggy code for {case_id}. "
            f"Bug is not real or test is too permissive. Reasons: {reasons}"
        )


# ============================================================
# TEST 3: Every test correctly PASSES on reference fix
# ============================================================

_CASES_WITH_REFFIX = [
    c["id"] for c in _ALL_CASES
    if (BASE / "reference_fixes" / f"{c['id']}.py").exists()
]


class TestReferenceFixPasses:
    """The reference fix for each case must pass its test."""

    @pytest.mark.parametrize("case_id", _CASES_WITH_REFFIX)
    def test_passes_on_fix(self, case_id):
        case = next(c for c in _ALL_CASES if c["id"] == case_id)
        test_fn = _CASE_TESTS.get(case_id) or _load_v2_test(case)
        assert test_fn is not None, f"No test for {case_id}"

        code = _load_reference_code(case)
        mod = load_module_from_code(code, f"fixed_{case_id}")
        passed, reasons = test_fn(mod)
        assert passed, (
            f"Test FAILS on reference fix for {case_id}. "
            f"Reference fix is wrong or test is too strict. Reasons: {reasons}"
        )


# ============================================================
# TEST 4: Score=0.5 sentinel never appears on valid cases
# ============================================================

class TestNoSilentHalfScore:
    """The production eval path must never return score=0.5
    (the old 'no test found' sentinel) for any case in the benchmark."""

    @pytest.mark.parametrize("case_id", _CASE_IDS)
    def test_no_05_sentinel(self, case_id):
        case = next(c for c in _ALL_CASES if c["id"] == case_id)
        code = _load_buggy_code(case)

        # Populate code_files_contents (required by evaluate_output)
        case_with_contents = dict(case)
        case_with_contents["code_files_contents"] = {}
        for rel in case["code_files"]:
            case_with_contents["code_files_contents"][rel] = (BASE / rel).read_text()

        # exec_evaluate now expects bare code, not a JSON-wrapped response
        result = exec_evaluate(case_with_contents, code)
        assert result["score"] != 0.5 or result.get("execution", {}).get("runtime_error") != "no_test_found", (
            f"Case {case_id} returned score=0.5 with no_test_found — "
            f"test function did not resolve in production eval path"
        )


# ============================================================
# TEST 5: Tests are idempotent (same result 3 times)
# ============================================================

class TestIdempotency:
    """Running a test 3 times on the same module must produce identical results."""

    @pytest.mark.parametrize("case_id", _CASE_IDS)
    def test_idempotent(self, case_id):
        case = next(c for c in _ALL_CASES if c["id"] == case_id)
        test_fn = _CASE_TESTS.get(case_id) or _load_v2_test(case)
        assert test_fn is not None

        code = _load_buggy_code(case)
        results = []
        for i in range(3):
            mod = load_module_from_code(code, f"idemp_{case_id}_{i}")
            passed, reasons = test_fn(mod)
            results.append((passed, tuple(reasons)))

        assert len(set(results)) == 1, (
            f"Test for {case_id} is NOT idempotent. "
            f"3 runs produced {len(set(results))} distinct results: {results}"
        )


# ============================================================
# TEST 6: Simulated agent outputs — correct fixes pass, wrong fixes fail
# ============================================================

# Define simulated outputs for a representative sample of cases.
# Each entry: (case_id, description, code_transform, should_pass)
# code_transform is a function that takes the buggy code and returns modified code.

_SIMULATED_OUTPUTS = [
    # alias_config_a: correct fix (.copy)
    ("alias_config_a", "correct: add .copy()",
     lambda code: code.replace("config = DEFAULTS", "config = DEFAULTS.copy()"),
     True),

    # alias_config_a: wrong fix (does nothing)
    ("alias_config_a", "wrong: no change",
     lambda code: code,
     False),

    # alias_config_a: wrong fix (copies overrides instead of DEFAULTS)
    ("alias_config_a", "wrong: copy overrides not defaults",
     lambda code: code.replace("config.update(overrides)", "config.update(dict(overrides))"),
     False),

    # partial_rollback_a: correct fix (add release in except)
    ("partial_rollback_a", "correct: add release on failure",
     lambda code: code.replace(
         "except ValueError:\n        raise",
         "except ValueError:\n        inventory.release(qty)\n        raise"
     ),
     True),

    # partial_rollback_a: wrong fix (no change)
    ("partial_rollback_a", "wrong: no change",
     lambda code: code,
     False),

    # stale_cache_a: correct fix (invalidate after write)
    ("stale_cache_a", "correct: add cache invalidation",
     lambda code: code.replace(
         "    _db[product_id].update(fields)",
         "    _db[product_id].update(fields)\n    _cache.pop(product_id, None)"
     ).replace("    # BUG: cache not invalidated \u2014 get_product returns stale data", ""),
     True),

    # mutable_default_a: correct fix (None default)
    ("mutable_default_a", "correct: None default pattern",
     lambda code: code.replace(
         "def enqueue(task, queue=[]):",
         "def enqueue(task, queue=None):"
     ).replace(
         "    queue.append(task)",
         "    if queue is None:\n        queue = []\n    queue.append(task)"
     ),
     True),

    # mutable_default_a: wrong fix (return copy - actually fixes the symptom)
    ("mutable_default_a", "wrong: return copy but default still shared",
     lambda code: code.replace(
         "    return queue",
         "    result = list(queue)\n    return result"
     ),
     False),

    # missing_branch_a: correct fix (add moderator with read+write+delete)
    ("missing_branch_a", "correct: add moderator branch",
     lambda code: code.replace(
         '"user": {"read", "write"},',
         '"user": {"read", "write"},\n    "moderator": {"read", "write", "delete"},'
     ),
     True),

    # missing_branch_a: wrong fix (no change)
    ("missing_branch_a", "wrong: no change",
     lambda code: code,
     False),

    # wrong_condition_a: correct fix (>= instead of >)
    ("wrong_condition_a", "correct: fix comparison operator",
     lambda code: code.replace("> max_requests", ">= max_requests")
     if "> max_requests" in code else code.replace(
         "count > limit", "count >= limit"
     ),
     True),

    # config_shadowing: correct fix (fix default)
    ("config_shadowing", "correct: fix default timeout",
     lambda code: code.replace('"timeout": 5', '"timeout": 30'),
     True),

    # config_shadowing: wrong fix (no change)
    ("config_shadowing", "wrong: no change",
     lambda code: code,
     False),
]


class TestSimulatedAgentOutputs:
    """Test the evaluation pipeline with known correct and incorrect agent outputs."""

    @pytest.mark.parametrize(
        "case_id,description,transform,should_pass",
        _SIMULATED_OUTPUTS,
        ids=[f"{cid}:{desc}" for cid, desc, _, _ in _SIMULATED_OUTPUTS]
    )
    def test_simulated(self, case_id, description, transform, should_pass):
        case = next(c for c in _ALL_CASES if c["id"] == case_id)
        test_fn = _CASE_TESTS.get(case_id) or _load_v2_test(case)
        assert test_fn is not None, f"No test for {case_id}"

        code = _load_buggy_code(case)
        modified = transform(code)
        mod = load_module_from_code(modified, f"sim_{case_id}")
        passed, reasons = test_fn(mod)

        if should_pass:
            assert passed, (
                f"[{case_id}] '{description}' should PASS but FAILED. "
                f"Reasons: {reasons}"
            )
        else:
            assert not passed, (
                f"[{case_id}] '{description}' should FAIL but PASSED. "
                f"Reasons: {reasons}"
            )


# ============================================================
# TEST 7: No case returns score=0.0 with reason "no_test_found"
# ============================================================

class TestNoTestFoundCrashes:
    """Missing tests must raise RuntimeError — never silently return a score."""

    def test_missing_test_raises(self):
        """A fake case with no matching test must crash, not return 0.5."""
        fake_case = {
            "id": "fake_nonexistent_case_xyz",
            "family": "fake_nonexistent_family_xyz",
            "difficulty": "A",
            "failure_mode": "TEST",
            "code_files": [],
        }
        fake_case["code_files_contents"] = {}

        fake_code = "def fake_function():\n    return 42\n"

        # exec_evaluate now expects bare code, not a JSON-wrapped response
        with pytest.raises(RuntimeError, match="NO TEST for case"):
            exec_evaluate(fake_case, fake_code)
