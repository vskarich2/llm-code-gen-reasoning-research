from __future__ import annotations

from graph_runner.state import Artifact, ExecutionState
from graph_runner.stage_spec import StageResult
from graph_runner.contracts.execution_contract import (
    ExecutionContract,
    ExecutionContractError,
)


# ============================================================
# INVARIANT TEST IMPLEMENTATIONS
# ============================================================

def _run_independence_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Successive calls return independent objects. Mutation of one must not affect others."""
    try:
        cfg1 = fn()
    except Exception as e:
        return False, f"{type(e).__name__}: {e} (calling function)"
    if not isinstance(cfg1, dict):
        return False, f"returned object is {type(cfg1).__name__}, not dict"
    try:
        cfg2 = fn()
    except Exception as e:
        return False, f"{type(e).__name__}: {e} (second call)"
    mutation = test.get("mutation", {})
    for k, v in mutation.items():
        cfg1[k] = v
    for k, v in mutation.items():
        if cfg2.get(k) == v:
            return False, f"independence violated: mutation leaked (key='{k}', value={v})"
    return True, None


def _run_idempotence_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Multiple calls with same inputs produce equivalent results."""
    try:
        result1 = fn()
        result2 = fn()
    except Exception as e:
        return False, f"idempotence failed: {type(e).__name__}: {e}"
    if result1 != result2:
        return False, f"idempotence violated: results differ ({result1} != {result2})"
    return True, None


def _run_consistency_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Output satisfies a relation between fields or derived values."""
    try:
        result = fn()
    except Exception as e:
        return False, f"consistency failed: {type(e).__name__}: {e}"
    check_expr = test.get("check")
    if not check_expr:
        return False, "consistency test missing 'check' expression"
    try:
        check_fn = eval(check_expr)
    except Exception as e:
        return False, f"consistency failed: invalid check expression: {e}"
    try:
        passed = check_fn(result)
    except Exception as e:
        return False, f"consistency failed: check execution error: {e}"
    if not passed:
        return False, "consistency violated: check returned False"
    return True, None


def _run_field_sync_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Modifying a primary field must update dependent fields."""
    try:
        obj = fn()
    except Exception as e:
        return False, f"field_sync failed: {type(e).__name__}: {e}"
    if not isinstance(obj, dict):
        return False, f"field_sync: returned {type(obj).__name__}, not dict"
    primary = test.get("primary_field")
    dependent = test.get("dependent_field")
    if not primary or not dependent:
        return False, "field_sync test missing primary_field or dependent_field"
    mutation_value = test.get("mutation_value", "CHANGED")
    obj[primary] = mutation_value
    try:
        obj2 = fn()
    except Exception as e:
        return False, f"field_sync: second call failed: {type(e).__name__}: {e}"
    if not isinstance(obj2, dict):
        return False, f"field_sync: second call returned {type(obj2).__name__}"
    if obj2.get(dependent) == obj2.get(primary):
        return True, None
    return False, f"field_sync violated: {primary} changed but {dependent} not synced"


def _run_lifecycle_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """After reset, function must reflect clean state."""
    try:
        result1 = fn()
    except Exception as e:
        return False, f"lifecycle: initial call failed: {type(e).__name__}: {e}"
    reset_fn_name = test.get("reset_fn")
    exec_globals = test.get("_exec_globals", {})
    reset_fn = exec_globals.get(reset_fn_name) if reset_fn_name else None
    if reset_fn and callable(reset_fn):
        try:
            reset_fn()
        except Exception as e:
            return False, f"lifecycle: reset failed: {type(e).__name__}: {e}"
    try:
        result2 = fn()
    except Exception as e:
        return False, f"lifecycle: post-reset call failed: {type(e).__name__}: {e}"
    if result1 != result2:
        return False, f"lifecycle violated: post-reset result differs ({result1} != {result2})"
    return True, None


def _run_side_effect_count_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Function must produce expected number of side effects."""
    collector = []
    exec_globals = test.get("_exec_globals", {})
    exec_globals["_side_effect_log"] = collector
    try:
        result = fn()
    except Exception as e:
        return False, f"side_effect_count: {type(e).__name__}: {e}"
    expected = test.get("expected_count")
    if expected is not None and len(collector) != expected:
        return False, f"side_effect_count violated: expected {expected}, got {len(collector)}"
    if result is not None and isinstance(result, (list, tuple)):
        actual_count = len(result)
        if expected is not None and actual_count != expected:
            return False, f"side_effect_count violated: result length {actual_count}, expected {expected}"
    return True, None


def _run_no_exception_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Function must not raise on edge inputs."""
    args = test.get("args", [])
    kwargs = test.get("kwargs", {})
    try:
        fn(*args, **kwargs)
    except Exception as e:
        return False, f"no_exception violated: {type(e).__name__}: {e}"
    return True, None


def _run_branch_coverage_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Function must handle all valid inputs without returning None."""
    inputs = test.get("inputs", [([], {})])
    for i, inp in enumerate(inputs):
        args = inp if isinstance(inp, (list, tuple)) else [inp]
        try:
            result = fn(*args)
        except Exception as e:
            return False, f"branch_coverage: input {i} raised {type(e).__name__}: {e}"
        if result is None:
            return False, f"branch_coverage violated: input {i} returned None"
    return True, None


def _run_boundary_condition_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Function must produce correct results at boundary values."""
    boundary_cases = test.get("boundary_cases", [])
    if not boundary_cases:
        return False, "boundary_condition test missing boundary_cases"
    for i, bc in enumerate(boundary_cases):
        args = bc.get("args", [])
        expected = bc.get("expected")
        try:
            result = fn(*args)
        except Exception as e:
            return False, f"boundary_condition: case {i} raised {type(e).__name__}: {e}"
        if expected is not None and result != expected:
            return False, f"boundary_condition violated: case {i} got {result}, expected {expected}"
    return True, None


def _run_state_conservation_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Total state must be conserved across operations, including failure paths."""
    snapshot_fn_name = test.get("snapshot_fn")
    exec_globals = test.get("_exec_globals", {})
    snapshot_fn = exec_globals.get(snapshot_fn_name) if snapshot_fn_name else None
    if snapshot_fn and callable(snapshot_fn):
        try:
            before = snapshot_fn()
        except Exception as e:
            return False, f"state_conservation: snapshot before failed: {type(e).__name__}: {e}"
        try:
            fn()
        except Exception:
            pass  # failure path is expected
        try:
            after = snapshot_fn()
        except Exception as e:
            return False, f"state_conservation: snapshot after failed: {type(e).__name__}: {e}"
        if before != after:
            return False, f"state_conservation violated: state changed ({before} -> {after})"
        return True, None
    # Fallback: call twice, check no drift
    try:
        r1 = fn()
        r2 = fn()
    except Exception as e:
        return False, f"state_conservation: {type(e).__name__}: {e}"
    if r1 != r2:
        return False, f"state_conservation violated: successive calls differ ({r1} != {r2})"
    return True, None


def _run_ordering_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Execution order must produce correct final state."""
    steps = test.get("steps", [])
    exec_globals = test.get("_exec_globals", {})
    if not steps:
        # Default: call function, verify no exception
        try:
            fn()
        except Exception as e:
            return False, f"ordering: {type(e).__name__}: {e}"
        return True, None
    for i, step_name in enumerate(steps):
        step_fn = exec_globals.get(step_name)
        if step_fn is None or not callable(step_fn):
            return False, f"ordering: step '{step_name}' not found"
        try:
            step_fn()
        except Exception as e:
            return False, f"ordering: step {i} ('{step_name}') raised {type(e).__name__}: {e}"
    check_expr = test.get("check")
    if check_expr:
        try:
            check_fn = eval(check_expr)
            if not check_fn(exec_globals):
                return False, "ordering violated: final state check failed"
        except Exception as e:
            return False, f"ordering: check failed: {e}"
    return True, None


def _run_atomicity_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Operation must be atomic — partial execution must not corrupt state."""
    exec_globals = test.get("_exec_globals", {})
    setup_fn_name = test.get("setup_fn")
    check_expr = test.get("check")
    if setup_fn_name:
        setup_fn = exec_globals.get(setup_fn_name)
        if setup_fn and callable(setup_fn):
            try:
                setup_fn()
            except Exception as e:
                return False, f"atomicity: setup failed: {type(e).__name__}: {e}"
    try:
        fn()
    except Exception:
        pass  # failure is expected in atomicity tests
    if check_expr:
        try:
            check_fn = eval(check_expr)
            if not check_fn(exec_globals):
                return False, "atomicity violated: invariant broken after execution"
        except Exception as e:
            return False, f"atomicity: check failed: {e}"
        return True, None
    return True, None


def _run_structure_alignment_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Parallel structures must have same length and aligned indices."""
    try:
        result = fn()
    except Exception as e:
        return False, f"structure_alignment: {type(e).__name__}: {e}"
    if not isinstance(result, dict):
        return False, f"structure_alignment: returned {type(result).__name__}, not dict"
    fields = test.get("aligned_fields", [])
    if len(fields) < 2:
        return False, "structure_alignment: need at least 2 aligned_fields"
    lengths = []
    for field in fields:
        val = result.get(field)
        if val is None:
            return False, f"structure_alignment: field '{field}' is None"
        if not hasattr(val, "__len__"):
            return False, f"structure_alignment: field '{field}' has no length"
        lengths.append(len(val))
    if len(set(lengths)) > 1:
        return False, f"structure_alignment violated: lengths differ {dict(zip(fields, lengths))}"
    return True, None


def _run_no_silent_fallback_test(fn: object, test: dict) -> tuple[bool, str | None]:
    """Function must not return a default/fallback value when given valid input."""
    forbidden_values = test.get("forbidden_values", [None])
    try:
        result = fn()
    except Exception as e:
        return False, f"no_silent_fallback: {type(e).__name__}: {e}"
    for fv in forbidden_values:
        if result == fv:
            return False, f"no_silent_fallback violated: returned forbidden value {result!r}"
    return True, None


# ============================================================
# INVARIANT TYPE REGISTRY
# ============================================================

INVARIANT_TYPE_REGISTRY = {
    "independence": _run_independence_test,
    "idempotence": _run_idempotence_test,
    "consistency": _run_consistency_test,
    "field_sync": _run_field_sync_test,
    "lifecycle": _run_lifecycle_test,
    "side_effect_count": _run_side_effect_count_test,
    "no_exception": _run_no_exception_test,
    "branch_coverage": _run_branch_coverage_test,
    "boundary_condition": _run_boundary_condition_test,
    "state_conservation": _run_state_conservation_test,
    "ordering": _run_ordering_test,
    "atomicity": _run_atomicity_test,
    "structure_alignment": _run_structure_alignment_test,
    "no_silent_fallback": _run_no_silent_fallback_test,
}

# Backward compat alias
_TEST_DISPATCHERS = INVARIANT_TYPE_REGISTRY


# ============================================================
# FAMILY → INVARIANT TYPE MAPPING
# ============================================================

_FAMILY_TO_INVARIANT = {
    "alias_config": "independence",
    "mutable_default": "idempotence",
    "retry_dup": "idempotence",
    "stale_cache": "consistency",
    "temporal_drift": "consistency",
    "feature_flag_drift": "consistency",
    "hidden_dep_multihop": "consistency",
    "overdetermination": "consistency",
    "config_shadowing": "consistency",
    "partial_update": "field_sync",
    "lazy_init": "lifecycle",
    "effect_order": "side_effect_count",
    "early_return": "side_effect_count",
    "use_before_set": "no_exception",
    "missing_branch": "branch_coverage",
    "wrong_condition": "boundary_condition",
    "partial_rollback": "state_conservation",
    "invariant_partial_fail": "state_conservation",
    "ordering_dependency": "ordering",
    "cache_invalidation_order": "ordering",
    "l3_state_pipeline": "ordering",
    "commit_gate": "ordering",
    "lost_update": "atomicity",
    "check_then_act": "atomicity",
    "async_race_lock": "atomicity",
    "false_fix_deadlock": "atomicity",
    "index_misalign": "structure_alignment",
    "silent_default": "no_silent_fallback",
}


def infer_invariant_type(case: dict) -> str:
    """Map a case to its canonical invariant type using family.

    Uses only case["family"]. No case_id branching.
    Raises ValueError if family is unmapped.
    """
    family = case.get("family", "")
    inv_type = _FAMILY_TO_INVARIANT.get(family)
    if inv_type is None:
        raise ValueError(
            f"No invariant type mapped for family '{family}' "
            f"(case_id={case.get('id', '?')}). Add mapping to _FAMILY_TO_INVARIANT."
        )
    if inv_type not in INVARIANT_TYPE_REGISTRY:
        raise ValueError(
            f"Invariant type '{inv_type}' for family '{family}' "
            f"not found in INVARIANT_TYPE_REGISTRY."
        )
    return inv_type


# ============================================================
# CONTRACT-DRIVEN EVALUATION
# ============================================================

def _run_contract_tests(exec_globals: dict, contract: dict) -> dict:
    """Execute test_contract against loaded code. Returns result dict."""
    fn_name = contract.get("function")
    if not fn_name:
        return {
            "success": False,
            "error": "test_contract missing 'function' field",
            "tests_run": 0,
            "tests_passed": 0,
        }

    if fn_name not in exec_globals:
        return {
            "success": False,
            "error": f"{fn_name} not found",
            "tests_run": 1,
            "tests_passed": 0,
        }

    fn = exec_globals[fn_name]
    tests = contract.get("tests", [])

    if not tests:
        return {
            "success": False,
            "error": "test_contract has no tests defined",
            "tests_run": 0,
            "tests_passed": 0,
        }

    tests_run = 0
    tests_passed = 0
    errors = []

    for test in tests:
        test_type = test.get("type")
        dispatcher = INVARIANT_TYPE_REGISTRY.get(test_type)

        if dispatcher is None:
            tests_run += 1
            errors.append(f"unknown test type: '{test_type}'")
            continue

        # Inject exec_globals for tests that need sibling functions
        test_with_globals = dict(test)
        test_with_globals["_exec_globals"] = exec_globals

        tests_run += 1
        passed, error = dispatcher(fn, test_with_globals)

        if passed:
            tests_passed += 1
        else:
            errors.append(error)

    success = tests_passed == tests_run
    error = "; ".join(errors) if errors else None

    return {
        "success": success,
        "error": error,
        "tests_run": tests_run,
        "tests_passed": tests_passed,
    }


# ============================================================
# GENERIC FALLBACK (no contract)
# ============================================================

def _run_generic_fallback(exec_globals: dict) -> dict:
    """Fallback for cases without test_contract: find callable, call it."""
    for name, obj in exec_globals.items():
        if name.startswith("__"):
            continue
        if callable(obj):
            try:
                obj()
                return {
                    "success": True,
                    "error": None,
                    "tests_run": 1,
                    "tests_passed": 1,
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"{type(e).__name__}: {e} (in {name})",
                    "tests_run": 1,
                    "tests_passed": 0,
                }

    return {
        "success": False,
        "error": "No callable function found in executed code",
        "tests_run": 1,
        "tests_passed": 0,
    }


# ============================================================
# MAIN EXECUTOR
# ============================================================

def exec_eval_executor(state: ExecutionState) -> StageResult:
    # Step 1 — Preconditions
    if not state.has("parsed_response"):
        artifact = Artifact.create(
            type="exec_result",
            value={
                "success": False,
                "error": "Execution skipped: no parsed_response",
                "tests_run": 0,
                "tests_passed": 0,
            },
        )
        state.add_artifact("exec_result", artifact)
        return StageResult(state=state, outcome="skipped")

    # Step 2 — Load and execute code
    parsed = state.get("parsed_response").value
    code = parsed["code"]

    try:
        exec_globals: dict = {}
        exec(code, exec_globals)
    except Exception as e:
        result = {
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "tests_run": 1,
            "tests_passed": 0,
        }
        return _emit_result(state, result)

    # Step 3 — Load contract (if available)
    contract = None
    if state.has("case"):
        case = state.get("case").value
        contract = case.get("test_contract")

    # Step 4 — Evaluate
    if contract and "function" in contract and "tests" in contract:
        result = _run_contract_tests(exec_globals, contract)
    else:
        result = _run_generic_fallback(exec_globals)

    return _emit_result(state, result)


def _emit_result(state: ExecutionState, result: dict) -> StageResult:
    """Validate result against ExecutionContract and emit artifact."""
    try:
        validated = ExecutionContract.validate(result)
    except ExecutionContractError as e:
        artifact = Artifact.create(
            type="exec_contract_error",
            value=str(e),
        )
        state.add_artifact("exec_contract_error", artifact)
        return StageResult(state=state, outcome="error")

    artifact = Artifact.create(
        type="exec_result",
        value=validated,
    )
    state.add_artifact("exec_result", artifact)

    outcome = "success" if validated["success"] else "error"
    return StageResult(state=state, outcome=outcome)
