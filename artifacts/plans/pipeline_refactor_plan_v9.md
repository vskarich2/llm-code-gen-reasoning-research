# Pipeline Refactor Plan v9

**Date:** 2026-04-03
**Status:** PLAN — awaiting approval
**Supersedes:** pipeline_refactor_plan_v8.md

---

## Structure

Nine phases. Unchanged from v8. This revision tightens edge-condition invariants and eliminates remaining failure-mode ambiguities. No scope expansion.

- **Phase A** — Path centralization, enforcement, preflight
- **Phase B** — Critical-path readability refactor
- **Phase C** — Full-fidelity prompt/response logging with enforcement
- **Phase D** — Parsing, structural validation, and recovery routing
- **Phase E** — Classification unification
- **Phase F** — Formal evaluation model and outcome classification
- **Phase G** — AST verification integration
- **Phase H** — Invariant/test audit (parallel)
- **Phase I** — Baseline commitments, metric materialization, analysis migration

---

## Non-Goals / Explicitly Rejected Approaches

All items from v8, plus:

- Silently coercing missing `execution_category` to a default value. Missing execution_category is a pipeline bug that must raise.
- Relying on downstream assertions to catch upstream invariant violations. Invariants are enforced at the source.
- Allowing classification or AST to operate on any code representation other than the exact `recon.files` object used for execution.
- Collapsing distinct serialization failure modes into ambiguous categories.

---

## Phase A — Path Centralization, Enforcement, Preflight

Unchanged from v8.

---

## Phase B — Critical-Path Readability Refactor

### B.1 — Top-Level Function

```python
def run_v2(case, model, condition, logger, case_start_eid=0):
    """Canonical critical path. ≤60 lines."""
    config = _get_config()
    ctx = _build_context(case, model, condition, config, logger, case_start_eid)

    prompt, prompt_meta = _render_generation_prompt(ctx)
    raw_response, gen_eid = _call_generation_model(ctx, prompt, prompt_meta)

    strict_parse, recovery_parse = _parse_outputs(raw_response, condition)
    routing = _select_artifact(strict_parse, recovery_parse, case)
    recon = _reconstruct(ctx, routing)
    eligibility = _check_execution_eligibility(routing, recon)

    # Source invariant: execution_eligible must be True when recon succeeded
    if routing.selected_source != "none" and recon.status == "success":
        assert eligibility.execution_eligible, \
            "execution_eligible must be True when reconstruction succeeded"

    artifact_id = _compute_artifact_id(recon)
    # The recon.files object is the single code snapshot for all downstream stages
    canonical_code_snapshot = recon.files if recon.status == "success" else None

    exec_result = _execute(ctx, recon, eligibility)

    # execution_category must always be set by execution stage
    assert exec_result.get("execution_category") is not None, \
        "execution_category must be set before evaluation"

    if eligibility.execution_eligible:
        classification = _classify(ctx, routing, case, canonical_code_snapshot,
                                   exec_result, gen_eid, artifact_id)
    else:
        classification = _classification_skipped(eligibility)

    if recon.status == "success":
        ast_result = _run_ast(canonical_code_snapshot, case, artifact_id)
    else:
        ast_result = _ast_not_measurable("reconstruction_failed")

    evaluation = _compute_evaluation(routing, recon, exec_result, classification, artifact_id)

    _assert_event_consistency(routing, recon, eligibility, classification,
                              ast_result, evaluation, artifact_id)

    ev = _assemble_event(ctx, exec_result, routing, recon, eligibility,
                         classification, ast_result, evaluation, artifact_id)
    _emit_event(ctx, ev, gen_eid)

    return case["id"], condition, ev
```

**Changes from v8:**
- `canonical_code_snapshot = recon.files` captured once. Passed to both `_classify` and `_run_ast`. Neither re-loads, re-parses, or re-constructs code.
- `execution_eligible` source invariant enforced immediately after eligibility computation, not downstream.
- `execution_category` assertion enforced immediately after execution, before any evaluation logic.
- `_classify` receives `canonical_code_snapshot` (the exact `recon.files` dict), not a separately-derived code string.
- `_run_ast` receives `canonical_code_snapshot`, not `recon` as a whole.

### B.2 — Artifact ID Computation

Unchanged from v8 (uses `json.dumps` with deterministic serialization).

### B.3 — Canonical Code Snapshot Invariant

**Global invariant:** All stages — reconstruction, execution, classification, and AST — must operate on the SAME artifact identity AND the SAME underlying code snapshot. This is stronger than artifact_id equality. It requires identity of the in-memory object, not just hash equivalence.

**Enforcement:**
- `canonical_code_snapshot` is captured once from `recon.files` at the point of successful reconstruction.
- `_classify` receives `canonical_code_snapshot` directly. It does not read from disk, re-parse, or use pre-reconstruction structures. Inside `_classify`, the code used for classifier variable assembly is exactly `canonical_code_snapshot`.
- `_run_ast` receives `canonical_code_snapshot` directly. It does not re-load or re-construct.
- `_execute` receives `recon` which contains the same `recon.files`. The execution harness materializes code to disk from `recon.files`.
- No stage may use parsed output directly, pre-reconstruction structures, or disk-loaded copies when `canonical_code_snapshot` is available.

### B.4 — Consistency Assertion (Updated)

```python
def _assert_event_consistency(routing, recon, eligibility, classification,
                              ast_result, evaluation, artifact_id):
    # Serialization → recon → eligibility chain
    if evaluation["serialization_success"]:
        assert recon.status == "success", "S=True but recon failed"
        assert eligibility.execution_eligible, "S=True but not execution_eligible"
        assert artifact_id != "no_artifact", "S=True but no artifact"
        assert classification.classifier_ran, "S=True but classifier did not run"

    # Artifact congruence (identity, not just equivalence)
    if classification.classifier_ran:
        assert classification.artifact_id == artifact_id, "classification artifact mismatch"
    if ast_result.status in ("measured_correct", "measured_incorrect"):
        assert ast_result.artifact_id == artifact_id, "AST artifact mismatch"
    assert evaluation["artifact_id"] == artifact_id, "evaluation artifact mismatch"

    # execution_success derivation
    assert evaluation["execution_success"] == \
        (evaluation["execution_category"] == "EXECUTION_SUCCESS"), \
        "execution_success must be derived from execution_category"
```

### B.5 — Retry Integration

Unchanged from v8. `retry_v2.py` calls shared helpers. Per-attempt code follows the same pattern: capture `canonical_code_snapshot` once, pass to classify and AST. The `execution_eligible` source invariant and `execution_category` assertion apply to each attempt.

### B.6 — Validation Gate

Unchanged from v8.

### PR: PR2

---

## Phase C — Full-Fidelity Prompt/Response Logging with Enforcement

Unchanged from v8 (includes sequence_index global per case, event-call linkage integrity).

---

## Phase D — Parsing, Structural Validation, Recovery Routing

Unchanged from v8.

---

## Phase E — Classification Unification

### E.1-E.4 — Unchanged from v8.

### E.5 — Classifier Output Completeness Invariant

Unchanged from v8. When `classifier_ran == True`: all four fields ∈ {"CORRECT", "INCORRECT"}. When `False`: all None.

### E.6 — Classification Code Input Invariant

`_classify` must receive and use the exact `canonical_code_snapshot` (the `recon.files` dict) for building classifier variables. It must not:
- Use parsed output directly
- Use pre-reconstruction structures
- Re-load from disk
- Use any other intermediate representation

```python
def _classify(ctx, routing, case, canonical_code_snapshot, exec_result,
              gen_eid, artifact_id):
    # canonical_code_snapshot IS recon.files — the exact code used for execution
    code_for_classifier = _extract_code_string(canonical_code_snapshot)
    artifact = _normalize_artifact(...)
    result = classify_case(artifact, case, code_for_classifier, ...)
    result.artifact_id = artifact_id
    return result
```

### E.7 — Classification Event Section

Unchanged from v8.

### E.8 — Validation Gate

Items 1-5 from v8, plus:

6. Verify that classifier input code is byte-identical to the code passed to execution (by comparing hashes in a test harness, not in production — production relies on object identity via `canonical_code_snapshot`).

### PR: PR5

---

## Phase F — Formal Evaluation Model and Outcome Classification

### F.1 — Three Evaluation Axes (Final)

**Axis 1: Serialization (S)**

```python
S = (routing.selected_source != "none") and (recon.status == "success")
```

From routing + reconstruction. Never from exec_result.

**Axis 2: Oracle Execution (E)**

```python
E = (exec_result["execution_category"] == "EXECUTION_SUCCESS")
```

`execution_category` must always be set. Missing execution_category is a pipeline bug.

```python
assert exec_result.get("execution_category") is not None, \
    "execution_category must be set before evaluation"
```

No silent coercion. No default value. No "EXECUTION_UNKNOWN" fallback. If the execution stage crashes before setting it, the pipeline halts with an assertion error. This is intentional — a missing execution_category indicates a bug in the execution harness, not a model behavior to classify.

`execution_success` is a pure function of `execution_category`:

```python
execution_success = (execution_category == "EXECUTION_SUCCESS")
```

Not stored independently. Not derived from any other field.

**Axis 3: Blind Process Evaluation (R)**

```python
if classification.classifier_ran:
    M = (classification.mechanism_identified == "CORRECT")
    C = (classification.commitments_satisfied == "CORRECT")
    A = (classification.reasoning_code_alignment == "CORRECT")
    R = M and C
else:
    M = None
    C = None
    A = None
    R = None
```

Guaranteed by Phase E: when `classifier_ran == True`, M/C/A are bool. When False, all None.

### F.2 — Outcome Classes

Unchanged from v8.

### F.3 — Implementation (Final)

```python
def _compute_evaluation(routing, recon, exec_result, classification, artifact_id):
    # Axis 1
    S = (routing.selected_source != "none") and (recon.status == "success")

    # Axis 2 — execution_category must exist
    execution_category = exec_result["execution_category"]
    E = (execution_category == "EXECUTION_SUCCESS")

    # Axis 3
    if classification.classifier_ran:
        M = (classification.mechanism_identified == "CORRECT")
        C = (classification.commitments_satisfied == "CORRECT")
        A = (classification.reasoning_code_alignment == "CORRECT")
        R = M and C
    else:
        M = None
        C = None
        A = None
        R = None

    # Pre-partition: R must be bool when S is True
    if S:
        assert isinstance(R, bool), \
            f"R must be bool when S=True, got R={R} (classifier_ran={classification.classifier_ran})"

    # Outcome
    if not S:
        outcome = "serialization_failure"
        s_fail_type = _derive_serialization_failure_type(routing, recon)
    elif E and R:
        outcome = "interpretable_success"
        s_fail_type = None
    elif E and not R:
        outcome = "unsupported_success"
        s_fail_type = None
    elif not E and R:
        outcome = "LEG"
        s_fail_type = None
    else:
        outcome = "reasoning_failure"
        s_fail_type = None

    # Partition assertion
    if S:
        classes = [S and E and R, S and E and (not R), S and (not E) and R, S and (not E) and (not R)]
        assert sum(classes) == 1, f"Partition violated: S={S} E={E} R={R}"

    leg_subtype = None
    if outcome == "LEG":
        leg_subtype = "congruent" if A else "incongruent"

    return {
        "serialization_success": S,
        "serialization_failure_type": s_fail_type,
        "execution_success": E,
        "execution_category": execution_category,
        "mechanism_correct": M,
        "commitments_valid": C,
        "alignment_positive": A,
        "reasoning_sufficient": R,
        "LEG": (outcome == "LEG"),
        "LEG_subtype": leg_subtype,
        "outcome_class": outcome,
        "artifact_id": artifact_id,
    }
```

### F.4 — Serialization Failure Type Derivation (Corrected)

```python
def _derive_serialization_failure_type(routing, recon):
    if routing.selected_source == "none":
        # No artifact selected — classify why
        if not routing.strict_parse_valid and not routing.recovery_parse_valid:
            return "parser_failure"
        if routing.strict_parse_valid and not routing.strict_structurally_valid:
            if not routing.recovery_parse_valid:
                return "strict_structural_invalid"
            if routing.recovery_parse_valid and not routing.recovery_structurally_valid:
                return "both_structural_invalid"
            # recovery_parse_valid and recovery_structurally_valid should have been selected
            return "unknown"
        if not routing.strict_parse_valid and routing.recovery_parse_valid:
            if not routing.recovery_structurally_valid:
                return "recovery_structural_invalid"
            # recovery was parse+struct valid — should have been selected
            return "unknown"
        return "unknown"
    # Artifact was selected but recon failed
    status = recon.status
    if status == "syntax_error":
        return "syntax_error"
    if status == "missing_file":
        return "missing_file"
    if status == "empty_file":
        return "empty_file"
    if status == "invalid_structure":
        return "invalid_structure"
    return "recon_failure"
```

Distinct failure modes are never collapsed. Each branch produces a unique, specific type.

### F.5-F.7 — Unchanged from v8.

### PR: PR6

---

## Phase G — AST Verification Integration

### G.1 — AST Code Input Invariant

AST runs on the exact same `canonical_code_snapshot` (the `recon.files` dict) passed to classification and used for execution. It does not re-load from disk, re-parse, or use alternate representations.

```python
if recon.status == "success":
    ast_result = _run_ast(canonical_code_snapshot, case, artifact_id)
else:
    ast_result = _ast_not_measurable("reconstruction_failed")
```

Inside `_run_ast`, the code files are taken directly from the passed dict. No re-construction.

### G.2-G.5 — Unchanged from v8.

### PR: PR7

---

## Phase H — Invariant/Test Audit

Unchanged from v8.

### PR: PR8

---

## Phase I — Baseline Commitments, Metric Materialization, Analysis Migration

Unchanged from v8.

### PRs: PR9, PR10

---

## Hidden Assumptions and Failure Modes

All items from v8. The `execution_category` fallback row is removed — missing `execution_category` is now a hard assertion failure, not a recoverable condition.

---

## PR Summary

Unchanged from v8.

---

## Acceptance Criteria

All items from v8, plus:

### Edge-Condition Correctness
- Missing `execution_category` raises `AssertionError`, not silent coercion.
- `execution_eligible` source invariant enforced immediately after eligibility computation, before any downstream use.
- Classification and AST both receive the exact same `canonical_code_snapshot` object (captured once from `recon.files`).
- No stage re-loads, re-parses, or re-constructs code when `canonical_code_snapshot` is available.
- Serialization failure types are exhaustive and never collapse distinct failure modes.
- `S=True → classifier_ran=True` chain enforced by assertion.

---

## Appendix: Hardcoded Path Inventory

Unchanged from v8.
