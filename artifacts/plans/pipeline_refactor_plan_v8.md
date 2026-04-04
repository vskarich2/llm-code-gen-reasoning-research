# Pipeline Refactor Plan v8

**Date:** 2026-04-03
**Status:** PLAN — awaiting approval
**Supersedes:** pipeline_refactor_plan_v7.md

---

## Structure

Nine phases. Unchanged from v7. This revision tightens invariants, fixes correctness bugs, and eliminates None-leakage paths. No new systems. No scope expansion.

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

Unchanged from v7. Additionally:

- Relying on boolean algebra with None values. All evaluation variables must be explicitly typed before use.
- Deriving serialization status from execution results. Serialization status comes from routing + reconstruction only.
- Allowing classifier output fields to be None when `classifier_ran == True`.
- Running AST verification on artifacts that failed reconstruction.

---

## Phase A — Path Centralization, Enforcement, Preflight

Unchanged from v7.

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

    artifact_id = _compute_artifact_id(recon)

    exec_result = _execute(ctx, recon, eligibility)

    if eligibility.execution_eligible:
        classification = _classify(ctx, routing, case, exec_result, gen_eid, artifact_id)
    else:
        classification = _classification_skipped(eligibility)

    if recon.status == "success":
        ast_result = _run_ast(recon, case, artifact_id)
    else:
        ast_result = _ast_not_measurable("reconstruction_failed")

    evaluation = _compute_evaluation(routing, recon, exec_result, classification, artifact_id)

    _assert_event_consistency(routing, recon, eligibility, classification, ast_result, evaluation, artifact_id)

    ev = _assemble_event(ctx, exec_result, routing, recon, eligibility,
                         classification, ast_result, evaluation, artifact_id)
    _emit_event(ctx, ev, gen_eid)

    return case["id"], condition, ev
```

**Changes from v7:**
- Classification guarded by `eligibility.execution_eligible` at call site, not inside helper.
- AST guarded by `recon.status == "success"` at call site.
- `_compute_evaluation` receives `routing` and `recon` directly, not `exec_result` for serialization.
- Explicit `_assert_event_consistency` before assembly.
- `_compute_artifact_id` receives only `recon`, not `routing`.

### B.2 — Artifact ID Computation (Fixed)

```python
def _compute_artifact_id(recon) -> str:
    import hashlib, json
    if recon.status != "success" or not recon.files:
        return "no_artifact"
    content = json.dumps(recon.files, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

Uses `json.dumps` with deterministic serialization. No string concatenation collisions.

### B.3 — Consistency Assertion

```python
def _assert_event_consistency(routing, recon, eligibility, classification, ast_result, evaluation, artifact_id):
    # Serialization consistency
    if evaluation["serialization_success"]:
        assert recon.status == "success", "S=True but recon failed"
        assert eligibility.execution_eligible, "S=True but not execution_eligible"
        assert artifact_id != "no_artifact", "S=True but no artifact"

    # Artifact congruence
    if classification.classifier_ran:
        assert classification.artifact_id == artifact_id, "classification artifact mismatch"
    if ast_result.status in ("measured_correct", "measured_incorrect"):
        assert ast_result.artifact_id == artifact_id, "AST artifact mismatch"
    if evaluation["artifact_id"] != artifact_id:
        raise RuntimeError(f"evaluation artifact mismatch: {evaluation['artifact_id']} != {artifact_id}")
```

### B.4 — Retry Integration

Unchanged from v7. `retry_v2.py` calls shared helpers only. Classification and AST guarding follow the same pattern as `run_v2`.

### B.5 — Validation Gate

Unchanged from v7.

### PR: PR2

---

## Phase C — Full-Fidelity Prompt/Response Logging with Enforcement

### C.1-C.3 — Unchanged from v7.

### C.4 — Call Sequence Index

`sequence_index` is **global per case evaluation, across all attempts**. It is strictly increasing. It does not reset between retry attempts.

Rationale: preserves total ordering across retries for replay.

```json
{
    "call_id": 3,
    "sequence_index": 3,
    "attempt": 1,
    "step": "retry_generation",
    "parent_call_id": 2
}
```

Attempt 0 calls get sequence_index 1, 2. Attempt 1 calls continue at 3, 4, etc.

### C.5 — Event-Call Linkage Integrity

**Invariant:** Every call_id referenced by any event must resolve to exactly one call artifact. Every call artifact must be referenced by at least one event.

**Validation (added to gate):**
- `count(call_artifacts) == count(unique call_ids in events)`
- No dangling call artifacts (artifact exists but no event references it)
- No orphan event references (event references a call_id with no artifact)
- No duplicate call_ids
- No gaps in sequence_index

### C.6 — Validation Gate

Items 1-8 from v7, plus:

9. `count(call_artifacts) == count(unique call_ids referenced in events.jsonl)`
10. No orphan references or dangling artifacts.

### PR: PR3

---

## Phase D — Parsing, Structural Validation, Recovery Routing

Unchanged from v7.

---

## Phase E — Classification Unification

### E.1-E.4 — Unchanged from v7.

### E.5 — Classifier Output Completeness Invariant

**When `classifier_ran == True`:**

```python
assert classification.mechanism_identified in ("CORRECT", "INCORRECT")
assert classification.commitments_satisfied in ("CORRECT", "INCORRECT")
assert classification.reasoning_code_alignment in ("CORRECT", "INCORRECT")
```

No None values permitted when classifier ran successfully.

**When `classifier_ran == False`:**

```python
assert classification.mechanism_identified is None
assert classification.commitments_satisfied is None
assert classification.reasoning_code_alignment is None
```

All dimension fields must be None.

This invariant is enforced in `parse_classifier_v2_output()`. If the classifier produces an unparseable or partial result, `classifier_ran` must be set to `False` and all fields set to `None`. A partially-parsed classifier result (e.g., mechanism_identified present but commitments_satisfied missing) is treated as a classifier failure, not a partial success.

### E.6 — Classification Event Section (Updated)

```python
ev["classification"] = {
    "mechanism_identified": "CORRECT" | "INCORRECT" | None,
    "commitments_extracted": "CORRECT" | "INCORRECT" | None,
    "commitments_satisfied": "CORRECT" | "INCORRECT" | None,
    "reasoning_code_alignment": "CORRECT" | "INCORRECT" | None,
    "classifier_ran": bool,
    "classifier_skipped_reason": str | None,
    "commitment_state": str,
    "artifact_id": str,
}
```

`None` is valid ONLY when `classifier_ran == False`.

### E.7 — Validation Gate

Items 1-3 from v7, plus:

4. For events where `classifier_ran == True`: all four dimension fields are non-None and ∈ {"CORRECT", "INCORRECT"}.
5. For events where `classifier_ran == False`: all four dimension fields are None.

### PR: PR5

---

## Phase F — Formal Evaluation Model and Outcome Classification

### F.1 — Three Evaluation Axes (Corrected)

**Axis 1: Serialization (S)**

```python
S = (routing.selected_source != "none") and (recon.status == "success")
```

Derived from routing + reconstruction. NOT from exec_result.

`_compute_evaluation` receives `routing` and `recon` as explicit arguments. It does not read serialization status from `exec_result`.

**Axis 2: Oracle Execution (E)**

```python
E = (exec_result.get("execution_category") == "EXECUTION_SUCCESS")
```

`execution_success` is a pure function of `execution_category`. It is not stored independently. It is not computed from a separate boolean like `exec_result.get("pass")`.

**Invariant:** `execution_success` must equal `(execution_category == "EXECUTION_SUCCESS")`. No other derivation is allowed.

**Axis 3: Blind Process Evaluation (R)**

```python
if classification.classifier_ran:
    M = (classification.mechanism_identified == "CORRECT")    # bool
    C = (classification.commitments_satisfied == "CORRECT")   # bool
    A = (classification.reasoning_code_alignment == "CORRECT") # bool
    R = M and C                                                # bool
else:
    M = None
    C = None
    A = None
    R = None
```

**Invariant:** When `classifier_ran == True`, M, C, A are guaranteed bool (not None) by Phase E invariant. When `classifier_ran == False`, all are None.

**Invariant:** `R is None` when `classifier_ran == False`. `R in (True, False)` when `classifier_ran == True`.

### F.2 — Outcome Classes (Corrected)

```
serialization_failure   := ¬S
interpretable_success   := S ∧ E ∧ R
unsupported_success     := S ∧ E ∧ ¬R
LEG                     := S ∧ ¬E ∧ R
reasoning_failure       := S ∧ ¬E ∧ ¬R
```

Complete partition. One class per attempt.

### F.3 — Implementation (Corrected)

```python
def _compute_evaluation(routing, recon, exec_result, classification, artifact_id):
    # Axis 1: Serialization — from routing + recon, NOT exec_result
    S = (routing.selected_source != "none") and (recon.status == "success")

    # Axis 2: Execution — from execution_category only
    E = (exec_result.get("execution_category") == "EXECUTION_SUCCESS")

    # Axis 3: Reasoning — from classifier, with None safety
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

    # Pre-partition safety: R must be bool when S is True
    if S:
        assert R in (True, False), f"R must be bool when S=True, got R={R} (classifier_ran={classification.classifier_ran})"

    # Outcome classification
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
    else:  # not E and not R
        outcome = "reasoning_failure"
        s_fail_type = None

    # Partition assertion (no None in boolean algebra)
    if S:
        classes = [
            S and E and R,
            S and E and (not R),
            S and (not E) and R,
            S and (not E) and (not R),
        ]
        assert sum(classes) == 1, f"Partition violated: S={S} E={E} R={R}"

    # LEG subtyping
    leg_subtype = None
    if outcome == "LEG":
        leg_subtype = "congruent" if A else "incongruent"

    return {
        "serialization_success": S,
        "serialization_failure_type": s_fail_type,
        "execution_success": E,
        "execution_category": exec_result.get("execution_category"),
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

**Key changes from v7:**
1. `S` derived from `routing` + `recon`, not `exec_result`.
2. `E` derived from `execution_category`, not `exec_result.get("pass")`.
3. `R` is explicitly None when classifier did not run. Pre-partition assertion ensures `R` is bool when `S` is True.
4. Partition assertion uses only bool values (no None in boolean algebra).
5. `_derive_serialization_failure_type` receives `routing` + `recon`, not `exec_result`.

### F.4 — Serialization Failure Type Derivation

```python
def _derive_serialization_failure_type(routing, recon):
    if routing.selected_source == "none":
        if not routing.strict_parse_valid and not routing.recovery_parse_valid:
            return "parser_failure"
        if not routing.strict_structurally_valid and not routing.recovery_structurally_valid:
            return "structural_invalid"
        return "unknown"
    # routing selected an artifact but recon failed
    if recon.status == "syntax_error":
        return "syntax_error"
    if recon.status == "missing_file":
        return "missing_file"
    if recon.status == "empty_file":
        return "empty_file"
    return "recon_failure"
```

### F.5 — Pre-Partition Guarantee: Classification Must Run When S Is True

When `S == True`, classification MUST have run (because `execution_eligible == True` when `S == True`, and classification runs when `execution_eligible == True`).

**Global invariant:**

```
S == True  →  classification.classifier_ran == True  →  R ∈ {True, False}
```

This chain is guaranteed by:
1. Phase D: `execution_eligible = (recon.status == "success")`
2. Phase B: classification guarded by `eligibility.execution_eligible`
3. Phase E: `classifier_ran == True` → all dimensions non-None → R is bool

If for any reason `S == True` but `classifier_ran == False`, the pre-partition assertion fires and the pipeline halts with a `RuntimeError`. This should never happen if Phases B/D/E are implemented correctly.

### F.6 — Evaluation Event Section

Unchanged from v7.

### F.7 — Validation Gate

Items 1-5 from v7, plus:

6. For events where `serialization_success == True`: `reconstruction.recon_status == "success"` AND `reconstruction.execution_eligible == True` AND `reconstruction.artifact_id != "no_artifact"`.
7. For events where `serialization_success == True`: `classification.classifier_ran == True`.
8. `evaluation.execution_success == (evaluation.execution_category == "EXECUTION_SUCCESS")` for all events.

### PR: PR6

---

## Phase G — AST Verification Integration

### G.1 — Role

Unchanged from v7: non-gating, automatic when spec exists, explicit status when unavailable.

### G.2 — AST Must Not Run on Failed Reconstruction

AST runs on the SAME reconstructed artifact used for execution. AST must NOT run on raw parsed output or on artifacts that failed reconstruction.

In `run_v2`:

```python
if recon.status == "success":
    ast_result = _run_ast(recon, case, artifact_id)
else:
    ast_result = _ast_not_measurable("reconstruction_failed")
```

When a spec exists but reconstruction failed: `status = "not_measurable"`, `reason = "reconstruction_failed"`.

When no spec exists: `status = "no_spec"`.

### G.3-G.5 — Unchanged from v7.

### PR: PR7

---

## Phase H — Invariant/Test Audit

Unchanged from v7.

### PR: PR8

---

## Phase I — Baseline Commitments, Metric Materialization, Analysis Migration

Unchanged from v7.

### PRs: PR9, PR10

---

## Hidden Assumptions and Failure Modes

Unchanged from v7, plus:

| Assumption | Risk | Detection | Contingency |
|---|---|---|---|
| Classifier always runs when S=True | Classifier call could fail (network, parse error) | Pre-partition assertion fires | Set `classifier_ran=False`, which sets `R=None`, which violates `R must be bool when S=True` → pipeline halts. Investigate classifier failure. |
| `execution_category` is always set by execution harness | Execution stage could crash without setting it | Null-check before evaluation | Default to `"EXECUTION_UNKNOWN"` and mark outcome as `"reasoning_failure"` (conservative) |

---

## PR Summary

Unchanged from v7.

---

## Acceptance Criteria

All items from v7, plus:

### Evaluation Model Correctness
- `S` derived from `routing.selected_source` + `recon.status`, never from `exec_result`
- `E` derived from `execution_category` only, never from `exec_result.get("pass")`
- When `classifier_ran == True`: all four dimension fields are non-None and ∈ {"CORRECT", "INCORRECT"}
- When `classifier_ran == False`: all four dimension fields are None
- When `serialization_success == True`: `classifier_ran == True` AND `R ∈ {True, False}`
- Partition assertion passes for all events: exactly one outcome class
- `evaluation.execution_success == (evaluation.execution_category == "EXECUTION_SUCCESS")`
- When `serialization_success == True`: `recon_status == "success"` AND `execution_eligible == True` AND `artifact_id != "no_artifact"`

### Call Linkage
- `count(call_artifacts) == count(unique call_ids in events)`
- No orphan references or dangling artifacts
- `sequence_index` is global per case, strictly increasing, no gaps

### AST
- AST never runs on `artifact_id == "no_artifact"`
- AST uses `not_measurable` when recon failed, not silent absence

### Artifact Congruence
- `evaluation.artifact_id == classification.artifact_id == reconstruction.artifact_id == ast_eval.artifact_id` for all events where those stages ran

---

## Appendix: Hardcoded Path Inventory

Unchanged from v7.
