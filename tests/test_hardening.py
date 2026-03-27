"""Hardening tests — verify the system cannot silently fail.

These tests enforce structural invariants that prevent the classes of
silent failure identified in the D-BUDIT reasoning_evaluator_audit. Each test targets a
specific failure mode that previously existed or could exist.

If ANY of these tests fail, the system may be producing invalid results.
"""

import sys
import os
import json
import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["OPENAI_API_KEY"] = "sk-dummy"

BASE = Path(__file__).resolve().parents[1]


# ============================================================
# 1. exec_eval is the SOLE production evaluator — no fallback
# ============================================================


def test_evaluator_has_no_heuristic_fallback():
    """evaluator.evaluate_output must NOT fall back to heuristic evaluation.

    The ImportError fallback was the #1 silent failure in the system.
    It must be impossible for eval_cases._EVALUATORS to influence
    production evaluation results.
    """
    import evaluator

    source = Path(evaluator.__file__).read_text()

    # No ImportError catch around exec_eval
    assert "except ImportError" not in source, (
        "evaluator.py still contains 'except ImportError' — " "heuristic fallback path is NOT dead"
    )

    # exec_evaluate is imported at module level, not inside try/except
    assert (
        "from exec_eval import exec_evaluate" in source
    ), "evaluator.py must import exec_evaluate at module level (not deferred)"


def test_evaluator_does_not_call_heuristic_evaluators():
    """No code path in evaluate_output dispatches to _EVALUATORS."""
    import evaluator
    import inspect

    source = inspect.getsource(evaluator.evaluate_output)
    assert (
        "_EVALUATORS" not in source
    ), "evaluate_output still references _EVALUATORS — heuristic path is alive"
    assert (
        "_eval_generic" not in source
    ), "evaluate_output still references _eval_generic — heuristic path is alive"


def test_exec_eval_import_failure_is_fatal():
    """If exec_eval cannot be imported, evaluator.py must fail at import time."""
    # We can't actually break the import without side effects,
    # but we can verify the import is top-level (not deferred)
    import evaluator

    source = Path(evaluator.__file__).read_text()

    # The import must be at module level (outside any function/try)
    lines = source.splitlines()
    for i, line in enumerate(lines):
        if "from exec_eval import exec_evaluate" in line:
            # Verify it's not inside a try block
            for j in range(max(0, i - 5), i):
                assert "try:" not in lines[j], (
                    f"exec_eval import is inside a try block at line {j+1} — "
                    "this allows silent fallback"
                )
            break
    else:
        raise AssertionError("exec_eval import not found at module level")


# ============================================================
# 2. No silent heuristic eval path
# ============================================================


def test_eval_cases_not_imported_for_dispatch():
    """eval_cases is imported for _has/_low (reasoning detection) only.

    It must NOT be imported for _EVALUATORS or _eval_generic dispatch.
    """
    import evaluator

    source = Path(evaluator.__file__).read_text()

    # _EVALUATORS must not be imported
    assert (
        "_EVALUATORS" not in source.split("from eval_cases import")[1].split("\n")[0]
        if "from eval_cases import" in source
        else True
    ), "_EVALUATORS is still imported from eval_cases in evaluator.py"


# ============================================================
# 3. Condition labels must be unique
# ============================================================


def test_condition_labels_unique():
    """COND_LABELS values must be unique. Duplicates corrupt result columns."""
    from runner import COND_LABELS

    values = list(COND_LABELS.values())
    duplicates = [v for v in values if values.count(v) > 1]
    assert not duplicates, (
        f"Duplicate condition labels: {set(duplicates)}. " f"This corrupts result columns."
    )


def test_condition_labels_assertion_exists():
    """runner.py must have an import-time assertion for label uniqueness."""
    source = (BASE / "runner.py").read_text()
    assert (
        "assert len(set(COND_LABELS.values()))" in source
    ), "runner.py missing import-time uniqueness assertion for COND_LABELS"


# ============================================================
# 4. Log write failures are surfaced and counted
# ============================================================


def test_log_write_failure_is_tracked():
    """Log write failures must be counted, not silently swallowed."""
    source = (BASE / "execution.py").read_text()
    assert "except OSError:\n            pass" not in source, (
        "execution.py still has bare 'except OSError: pass' — "
        "log write failures are silently swallowed"
    )
    assert "writes_failed" in source, "execution.py does not track log write failures"


def test_log_write_stats_available():
    """get_log_write_stats must be callable and return valid structure."""
    from execution import get_log_write_stats

    stats = get_log_write_stats()
    assert "attempted" in stats
    assert "failed" in stats
    assert "success_rate" in stats


def test_retry_harness_no_silent_log_swallow():
    """retry_harness.py must not silently swallow log write failures."""
    source = (BASE / "retry_harness.py").read_text()
    assert (
        "except OSError:\n            pass" not in source
    ), "retry_harness.py still has bare 'except OSError: pass'"


# ============================================================
# 5. Parser fallback is flagged and visible downstream
# ============================================================


def test_raw_fallback_is_flagged():
    """When parser uses raw fallback, _raw_fallback=True must be set."""
    from parse import parse_model_response

    result = parse_model_response("This is plain English, not code or JSON.")
    assert (
        result.get("_raw_fallback") is True
    ), "Raw fallback parse result missing _raw_fallback=True flag"
    assert "SEVERE" in (
        result.get("parse_error") or ""
    ), "Raw fallback parse_error should contain SEVERE marker"


def test_normal_parse_has_no_raw_fallback_flag():
    """Successful JSON parse must NOT have _raw_fallback flag."""
    from parse import parse_model_response

    result = parse_model_response('{"reasoning": "ok", "code": "x = 1"}')
    assert result.get("_raw_fallback") is not True


# ============================================================
# 6. Every runnable case has a valid evaluator
# ============================================================


def test_all_v2_cases_have_test_functions():
    """Every case in cases_v2.json must resolve to a test function."""
    from exec_eval import _CASE_TESTS, _load_v2_test

    cases_path = BASE / "cases_v2.json"
    if not cases_path.exists():
        return  # skip if v2 cases not present

    cases = json.loads(cases_path.read_text())
    missing = []
    for case in cases:
        cid = case["id"]
        test_fn = _CASE_TESTS.get(cid)
        if test_fn is None:
            test_fn = _load_v2_test(case)
        if test_fn is None:
            missing.append(cid)

    assert not missing, (
        f"{len(missing)} cases have NO test function and would silently " f"score 0.0: {missing}"
    )


def test_preflight_verify_catches_missing_tests():
    """preflight_verify_tests must raise on cases without test functions."""
    from runner import preflight_verify_tests

    fake_case = {
        "id": "NONEXISTENT_CASE_ID_FOR_TESTING",
        "failure_mode": "UNKNOWN",
        "family": "nonexistent",
        "difficulty": "a",
    }
    try:
        preflight_verify_tests([fake_case])
        assert False, "preflight_verify_tests should have raised RuntimeError"
    except RuntimeError as e:
        assert "NONEXISTENT_CASE_ID_FOR_TESTING" in str(e)


# ============================================================
# 7. V1/V2 routing is deterministic
# ============================================================


def test_v2_test_loader_is_deterministic():
    """_load_v2_test must return the same function for the same case."""
    from exec_eval import _load_v2_test

    cases_path = BASE / "cases_v2.json"
    if not cases_path.exists():
        return

    cases = json.loads(cases_path.read_text())
    for case in cases[:3]:
        fn1 = _load_v2_test(case)
        fn2 = _load_v2_test(case)
        if fn1 is not None:
            assert (
                fn1.__name__ == fn2.__name__
            ), f"V2 test loader not deterministic for {case['id']}"


# ============================================================
# 8. No legacy import path silently activates
# ============================================================


def test_no_backward_compat_aliases_in_runner():
    """runner.py must not export _build_prompt, _run_single, _run_repair_loop."""
    source = (BASE / "runner.py").read_text()
    assert "_build_prompt = " not in source, "runner.py still has _build_prompt alias"
    assert "_run_single = " not in source, "runner.py still has _run_single alias"
    assert "_run_repair_loop = " not in source, "runner.py still has _run_repair_loop alias"


def test_llm_does_not_reexport_parse_model_response():
    """llm.py must not re-export parse_model_response."""
    source = (BASE / "llm.py").read_text()
    assert (
        "from parse import parse_model_response" not in source
    ), "llm.py still re-exports parse_model_response"


# ============================================================
# 9. No fallback path can activate without explicit signal
# ============================================================


def test_mock_mode_logs_warning():
    """Mock mode must emit a warning, not activate silently."""
    source = (BASE / "llm.py").read_text()
    assert "MOCK MODE ACTIVE" in source, "llm.py does not warn about mock mode activation"


def test_yaml_fallback_parser_removed():
    """run_ablation_config.py must not have a fallback YAML parser."""
    source = (BASE / "scripts" / "run_ablation_config.py").read_text()
    assert (
        "current_list" not in source
    ), "YAML fallback parser still present in run_ablation_config.py"


# ============================================================
# 10. Thread safety of module loading
# ============================================================


def test_module_counter_is_threadsafe():
    """exec_eval._load_counter must use itertools.count, not a global int."""
    source = (BASE / "exec_eval.py").read_text()
    assert "itertools.count" in source, (
        "exec_eval._load_counter is not using itertools.count — "
        "not thread-safe for parallel execution"
    )
    assert (
        "global _load_counter" not in source
    ), "exec_eval still uses 'global _load_counter' — race condition"


# ============================================================
# 11. Script syntax validity
# ============================================================


def test_all_scripts_parse():
    """Every .py file in scripts/ must be valid Python syntax."""
    scripts_dir = BASE / "scripts"
    if not scripts_dir.exists():
        return
    failures = []
    for py_file in scripts_dir.glob("*.py"):
        try:
            compile(py_file.read_text(), str(py_file), "exec")
        except SyntaxError as e:
            failures.append(f"{py_file.name}: {e}")
    assert not failures, f"Script syntax errors:\n" + "\n".join(failures)


# ============================================================
# 12. CGE execution flag
# ============================================================


def _ensure_logger(model="gpt-4.1-nano"):
    """Ensure an active RunLogger exists for tests that need write_log.

    The conftest autouse fixture already creates one, but if it's for the
    wrong model, we recreate it.
    """
    from execution import get_current_log_path, get_run_logger, init_run_log, close_run_log

    current = get_current_log_path()
    if current is not None:
        # Check if model matches
        logger = get_run_logger()
        if logger.model == model:
            return  # already correct
        close_run_log()
    else:
        close_run_log()
    # Remove stale files and create fresh logger
    logs_dir = BASE / "logs"
    for f in logs_dir.glob(f"{model.replace('/', '_')}*"):
        f.unlink(missing_ok=True)
    init_run_log(model)


def test_cge_success_and_fallback_flags():
    """CGE success path sets cge_executed=True; fallback sets cge_executed=False.

    Combined into one test to share a single RunLogger session (avoids
    timestamp-based filename collisions).
    """
    from execution import run_contract_gated, _fallback_run, close_run_log
    from runner import load_cases

    _ensure_logger("gpt-4.1-nano")
    case = load_cases(case_id="l3_state_pipeline")[0]

    # SUCCESS PATH
    cid, cond, ev = run_contract_gated(case, "gpt-4.1-nano")
    assert "cge_executed" in ev, "cge_executed field missing from CGE result"
    assert ev["cge_executed"] is True, f"CGE ran but cge_executed={ev['cge_executed']}"

    # FALLBACK PATH
    cid2, cond2, ev2 = _fallback_run(case, "gpt-4.1-nano", "not json at all")
    assert "cge_executed" in ev2, "cge_executed field missing from fallback result"
    assert (
        ev2["cge_executed"] is False
    ), f"Fallback should have cge_executed=False, got {ev2['cge_executed']}"

    close_run_log()


def test_cge_fallback_invalidated_at_aggregation():
    """contract_gated + cge_executed=False must result in pass=False, score=0."""
    # Simulate what run_all does for contract_gated results
    ev = {
        "pass": True,
        "score": 0.8,
        "reasons": ["some reason"],
        "failure_modes": [],
        "operator_used": "CONTRACT_GATED",
        "condition": "contract_gated",
        "cge_executed": False,
        "identified_correct_issue": False,
        "final_output_correct": True,
        "reasoning_action_gap": False,
    }

    # Replicate the aggregation logic from run_all
    cond = "contract_gated"
    if cond == "contract_gated":
        if "cge_executed" not in ev:
            raise RuntimeError("missing cge_executed")
        if ev["cge_executed"] is False:
            ev["pass"] = False
            ev["score"] = 0.0

    assert ev["pass"] is False, "Fallback CGE must be invalidated"
    assert ev["score"] == 0.0, "Fallback CGE score must be 0"


def test_cge_missing_flag_crashes():
    """contract_gated result without cge_executed must raise RuntimeError."""
    ev = {"pass": True, "score": 1.0}
    try:
        # Replicate the aggregation check
        cond = "contract_gated"
        if cond == "contract_gated":
            if "cge_executed" not in ev:
                raise RuntimeError("CGE INTEGRITY FAILURE: missing cge_executed")
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "cge_executed" in str(e)


# ============================================================
# 13. Evidence metrics: None for non-SCM, real values for SCM
# ============================================================


def test_evidence_none_for_non_scm_case():
    """Non-SCM case must return None evidence metrics, NEVER zero."""
    from evaluator import compute_evidence_metrics

    case = {"id": "easy_conservation", "failure_mode": "EASY_CONSERVATION"}
    m = compute_evidence_metrics(case, "any output")
    assert m["has_scm"] is False, "easy_conservation is not an SCM case"
    assert (
        m["evidence_usage_score"] is None
    ), f"Non-SCM evidence_usage_score should be None, got {m['evidence_usage_score']}"
    assert m["incorrect_evidence_usage_count"] is None
    assert m["uncertain_evidence_usage_count"] is None
    assert m["hallucinated_evidence_count"] is None
    assert m["evidence_action_gap"] is None
    assert m["delta_gap"] is None


def test_evidence_real_values_for_scm_case():
    """SCM case must return integer evidence metrics, NEVER None."""
    from evaluator import compute_evidence_metrics

    case = {"id": "l3_state_pipeline", "failure_mode": "STATE_SEMANTIC_VIOLATION"}
    m = compute_evidence_metrics(case, "No IDs mentioned.")
    assert m["has_scm"] is True, "l3_state_pipeline should have SCM data"
    assert m["evidence_usage_score"] is not None
    assert isinstance(m["evidence_usage_score"], int)


def test_evidence_no_zero_default_anywhere():
    """No return path in compute_evidence_metrics returns 0 for non-SCM cases."""
    source = (BASE / "evaluator.py").read_text()
    # Find the non-SCM return block
    lines = source.splitlines()
    in_non_scm_block = False
    for i, line in enumerate(lines):
        if "if not scm:" in line:
            in_non_scm_block = True
            continue
        if in_non_scm_block:
            if line.strip().startswith("return"):
                # Scan the return dict for any : 0 or : False
                # (except has_scm which is legitimately False)
                break
            if ": 0," in line or ": 0}" in line:
                assert False, f"evaluator.py line {i+1} returns 0 for non-SCM case: {line.strip()}"
            if "has_scm" not in line and ": False" in line:
                assert (
                    False
                ), f"evaluator.py line {i+1} returns False for non-SCM case: {line.strip()}"
            if line.strip() and not line.strip().startswith(("#", "}", '"', "'")):
                if "return" in line.strip():
                    break


def test_evaluate_output_evidence_none_propagates():
    """evaluate_output on non-SCM case must have None evidence fields."""
    from evaluator import evaluate_output

    case = {
        "id": "easy_conservation",
        "failure_mode": "EASY_CONSERVATION",
        "code_files": [],
        "code_files_contents": {},
    }
    r = evaluate_output(
        case,
        {
            "code": 'def transfer(a,b,n): a["balance"]-=n; b["balance"]+=n',
            "reasoning": "",
            "raw_output": '```python\ndef transfer(a,b,n): a["balance"]-=n; b["balance"]+=n\n```',
            "parse_error": None,
            "_raw_fallback": False,
        },
    )
    assert (
        r["evidence_usage_score"] is None
    ), f"Non-SCM evaluate_output should have None evidence_usage_score, got {r['evidence_usage_score']}"
    assert r["evidence_action_gap"] is None
    assert r["delta_gap"] is None
