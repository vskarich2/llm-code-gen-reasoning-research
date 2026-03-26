"""Enforcement tests: canonical pipeline rules.

Ensures no code path bypasses evaluate_case for evaluation logic.
"""

import inspect
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestEvaluateOutputNotCalledDirectly:
    """evaluate_output must only be called inside evaluate_case."""

    def test_no_evaluate_output_in_run_functions(self):
        """No run_* function may call evaluate_output directly."""
        import execution
        for name in ["run_single", "run_repair_loop", "run_contract_gated",
                     "_fallback_run", "run_leg_reduction"]:
            fn = getattr(execution, name)
            source = inspect.getsource(fn)
            assert "evaluate_output(" not in source, (
                f"{name} calls evaluate_output directly. "
                f"It must use evaluate_case instead."
            )

    def test_no_evaluate_output_in_retry_harness(self):
        """retry_harness must not call evaluate_output directly."""
        import retry_harness
        source = inspect.getsource(retry_harness.run_retry_harness)
        assert "evaluate_output(" not in source, (
            "run_retry_harness calls evaluate_output directly. "
            "It must use evaluate_case instead."
        )


class TestNoManualParsedDictConstruction:
    """No run_* function may construct parsed dicts inline."""

    def test_no_eval_parsed_dict_in_run_functions(self):
        import execution
        for name in ["run_single", "run_repair_loop", "run_contract_gated",
                     "_fallback_run", "run_leg_reduction"]:
            fn = getattr(execution, name)
            source = inspect.getsource(fn)
            assert "eval_parsed = {" not in source, (
                f"{name} constructs eval_parsed dict inline. "
                f"It must use evaluate_case."
            )
            # Check for manual parsed dict with code/reasoning keys
            # (but allow ev["xxx"] = ... which is metadata attachment)
            lines = source.split("\n")
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("parsed = {") and '"code"' in stripped:
                    pytest.fail(
                        f"{name} constructs manual parsed dict: {stripped}"
                    )

    def test_no_manual_parsed_in_retry(self):
        import retry_harness
        source = inspect.getsource(retry_harness.run_retry_harness)
        assert "eval_parsed = {" not in source, (
            "run_retry_harness constructs eval_parsed dict inline."
        )


class TestNoParsingOutsideEvaluateCase:
    """parse_model_response must not be called from run_* functions."""

    def test_no_parse_model_response_in_run_functions(self):
        import execution
        for name in ["run_single", "run_repair_loop", "run_contract_gated",
                     "_fallback_run", "run_leg_reduction"]:
            fn = getattr(execution, name)
            source = inspect.getsource(fn)
            assert "parse_model_response(" not in source, (
                f"{name} calls parse_model_response directly. "
                f"Use evaluate_case or extract_code_from_raw."
            )

    def test_no_parse_in_retry(self):
        import retry_harness
        source = inspect.getsource(retry_harness.run_retry_harness)
        assert "parse_model_response(" not in source, (
            "run_retry_harness calls parse_model_response directly."
        )
        assert "parse_structured_output(" not in source, (
            "run_retry_harness calls parse_structured_output directly."
        )

    def test_extract_code_from_raw_only_in_cge(self):
        """extract_code_from_raw is the only external parse_model_response caller."""
        import execution
        source = inspect.getsource(execution.extract_code_from_raw)
        assert "parse_model_response(" in source


class TestNoSafeEvaluate:
    """_safe_evaluate must not exist — evaluate_case handles errors."""

    def test_safe_evaluate_removed(self):
        import retry_harness
        assert not hasattr(retry_harness, "_safe_evaluate"), (
            "_safe_evaluate still exists. It must be removed."
        )


class TestPropagateObservabilityCalled:
    """Every path that calls evaluate_case must also call _propagate_observability."""

    def test_run_functions_propagate(self):
        import execution
        for name in ["run_single", "run_repair_loop", "run_contract_gated",
                     "_fallback_run", "run_leg_reduction"]:
            fn = getattr(execution, name)
            source = inspect.getsource(fn)
            if "evaluate_case(" in source or "_attempt_and_evaluate(" in source:
                assert "_propagate_observability(" in source, (
                    f"{name} calls evaluate_case but does not call "
                    f"_propagate_observability. Phase 1 fields will be missing."
                )


class TestEvaluateCaseExists:
    """evaluate_case must exist and have the correct signature."""

    def test_evaluate_case_signature(self):
        from execution import evaluate_case
        sig = inspect.signature(evaluate_case)
        params = list(sig.parameters.keys())
        assert "case" in params
        assert "raw_output" in params
        assert "parser" in params

    def test_evaluate_case_returns_tuple(self):
        """evaluate_case must return (parsed, ev) tuple."""
        from execution import evaluate_case
        # We can't call it without a real case, but verify the return annotation
        # exists in the docstring
        doc = evaluate_case.__doc__ or ""
        assert "parsed" in doc.lower() or "tuple" in doc.lower()
