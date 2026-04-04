# Pipeline Refactor Plan v7

**Date:** 2026-04-03
**Status:** PLAN — awaiting approval
**Supersedes:** pipeline_refactor_plan_v5.md

---

## Structure

Nine phases. Each shippable with a validation gate. No phase begins until predecessor's gate passes, except Phase H (invariant audit) which has no upstream dependency.

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

- Scattering path constants across multiple modules.
- Building a path-abstraction framework.
- Replacing hardcoded paths with env vars only.
- Duplicating classifier logic. One canonical entrypoint.
- Silent fallback behavior without explicit event fields.
- Mixing architecture cleanup with behavior changes in the same PR unless mechanically coupled.
- Judging any migration successful by field presence alone.
- Allowing any LLM call to bypass the canonical logged call path.
- Direct provider calls outside `llm.py`.
- Truncation in canonical stored artifacts.
- Recomputing outcome classes in analysis scripts. Outcome class is computed once and logged.
- Mixing strict/recovery artifacts across stages.
- Classifier seeing execution results, ground truth bugs, or canonical answer patterns.
- Overwriting earlier retry attempts with later ones.

---

## Phase A — Path Centralization, Enforcement, Preflight

### A.1 — Central Path Module: `core/config/paths.py`

```python
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

CASE_DATA_DIR       = PROJECT_ROOT / "case_data"
CASES_V2_PATH       = CASE_DATA_DIR / "cases_v2.json"
TESTS_V2_DIR        = CASE_DATA_DIR / "tests_v2"
CODE_SNIPPETS_DIR   = CASE_DATA_DIR / "code_snippets_v2"
REFERENCE_FIXES_DIR = CASE_DATA_DIR / "reference_fixes"
AST_SPECS_PATH      = CASE_DATA_DIR / "ast_specs.json"

PROMPTS_DIR         = PROJECT_ROOT / "core" / "prompts"
COMPONENTS_DIR      = PROMPTS_DIR / "components"
PROMPT_MANIFEST     = PROMPTS_DIR / "prompt_manifest.yaml"
COMPONENT_META      = PROMPTS_DIR / "component_metadata.yaml"

HARNESS_SCRIPT      = PROJECT_ROOT / "core" / "harness" / "run_case.py"
DEFAULT_LOGS_DIR    = PROJECT_ROOT / "logs"

MANIFEST_FILENAME       = "manifest.json"
EVENTS_FILENAME         = "events.jsonl"
MERGED_EVENTS_FILENAME  = "merged_events.jsonl"
CONFIG_SNAPSHOT_FILENAME = "config.snapshot.yaml"
LOCK_FILENAME           = "orchestrator.lock"
HEARTBEAT_FILENAME      = "heartbeat.json"
TRIAL_CONFIG_FILENAME   = "trial_config.yaml"
STDOUT_LOG_FILENAME     = "stdout.log"
STDERR_LOG_FILENAME     = "stderr.log"

def resolve_run_dir(run_dir_str: str) -> Path:
    p = Path(run_dir_str)
    return (p if p.is_absolute() else PROJECT_ROOT / p).resolve()

def resolve_test_path(family: str) -> Path:
    return TESTS_V2_DIR / f"test_{family}.py"
```

Only run/output roots may come from config. Repo asset paths must never pass through `resolve_run_dir`.

### A.2 — Enforcement

`scripts/check_forbidden_paths.py`: scans `core/` for forbidden path literals. Exits non-zero on match. Mandatory pre-merge.

`scripts/check_direct_provider_calls.py`: scans `core/` for direct provider calls (e.g., `client.chat.completions`, `_provider_call`) outside `llm.py`. Exits non-zero on match. Mandatory pre-merge.

Documented exceptions: `paths.py`, `run_case.py` (CWD-relative), `/proc/{pid}/cmdline`.

### A.3 — Preflight

`core/config/preflight.py`:

```python
def validate_startup(config=None) -> None:
    missing = []
    for name, path in [
        ("CASE_DATA_DIR", CASE_DATA_DIR),
        ("CASES_V2_PATH", CASES_V2_PATH),
        ("TESTS_V2_DIR", TESTS_V2_DIR),
        ("COMPONENTS_DIR", COMPONENTS_DIR),
        ("PROMPT_MANIFEST", PROMPT_MANIFEST),
        ("HARNESS_SCRIPT", HARNESS_SCRIPT),
    ]:
        if not path.exists():
            missing.append(f"{name}: {path}")
    if config and hasattr(config, "run"):
        run_dir = resolve_run_dir(config.run.run_dir)
        # Write permission check
        try:
            probe = run_dir / ".preflight_probe"
            run_dir.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok")
            probe.unlink()
        except OSError as e:
            missing.append(f"run_dir not writable: {run_dir} ({e})")
    if missing:
        raise RuntimeError("Preflight failed:\n" + "\n".join(missing))
```

Called at runner/orchestrator startup before workers launch.

### A.4 — Validation Gate

1. Both enforcement scripts exit 0.
2. Preflight passes (including write-permission check).
3. Smoke test: 1 case × 1 model × baseline_v2.
4. Rename proof for test directory.

### PR: PR1

- **Files:** `paths.py`, NEW `preflight.py`, NEW `check_forbidden_paths.py`, NEW `check_direct_provider_calls.py`, + 8 core modules
- **Behavior change:** None.

---

## Phase B — Critical-Path Readability Refactor

### B.1 — Top-Level Function

`execution_v2.py` exposes one canonical function ≤60 lines:

```python
def run_v2(case, model, condition, logger, case_start_eid=0):
    config = _get_config()
    ctx = _build_context(case, model, condition, config, logger, case_start_eid)

    prompt, prompt_meta = _render_generation_prompt(ctx)
    raw_response, gen_eid = _call_generation_model(ctx, prompt, prompt_meta)

    strict_parse, recovery_parse = _parse_outputs(raw_response, condition)
    routing = _select_artifact(strict_parse, recovery_parse, case)
    recon = _reconstruct(ctx, routing)
    eligibility = _check_execution_eligibility(routing, recon)

    artifact_id = _compute_artifact_id(routing, recon)

    exec_result = _execute(ctx, recon, eligibility)
    classification = _classify(ctx, routing, case, exec_result, gen_eid, artifact_id)
    ast_result = _run_ast(recon, case, artifact_id)

    evaluation = _compute_evaluation(exec_result, classification, routing, artifact_id)
    ev = _assemble_event(ctx, exec_result, routing, recon, eligibility,
                         classification, ast_result, evaluation, artifact_id)
    _emit_event(ctx, ev, gen_eid)

    return case["id"], condition, ev
```

No peer function duplicates this flow.

### B.2 — Retry Integration

`retry_v2.py` is a thin loop over the same helpers. It calls shared helpers for parse, structure, execute, classify, AST, evaluation. It does not import parser, reconstructor, executor, evaluator, or AST evaluator directly — only the shared helper functions.

**Invariant:** `retry_v2.py` may not call parse, reconstruction, execution, classification, evaluation, or AST logic directly. It calls the same helper functions used by `run_v2`.

### B.3 — Artifact Congruence

```python
def _compute_artifact_id(routing: RoutingDecision, recon) -> str:
    """Hash of the reconstructed code that enters execution."""
    import hashlib
    if recon.status != "success" or not recon.files:
        return "no_artifact"
    content = "".join(sorted(f"{k}:{v}" for k, v in recon.files.items()))
    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

**Global invariant:** The SAME selected artifact (identified by `artifact_id`) must be used for reconstruction, execution, classification, and AST analysis. `execution.artifact_id == classification.artifact_id == ast.artifact_id`. Assertion enforced in `_assemble_event`.

### B.4 — Validation Gate

1. `run_v2()` ≤60 lines.
2. Smoke test: identical results to pre-refactor for 3 cases × 2 models.
3. No behavior change.
4. `retry_v2.py` contains no direct calls to parser/reconstructor/executor/evaluator/AST — only shared helpers.

### PR: PR2

- **Files:** `execution_v2.py`, `retry_v2.py`
- **Behavior change:** None.
- **Dependencies:** PR1.

---

## Phase C — Full-Fidelity Prompt/Response Logging with Enforcement

### C.1 — Universal Logged Call

**Hard rule:** Direct provider calls are forbidden outside `llm.py`. Enforced by `check_direct_provider_calls.py`.

```python
# core/pipeline/llm.py

def logged_llm_call(prompt, *, model, logger, ctx, **kwargs):
    """Every critical-path LLM call routes here. No bypass."""
    call_id = ctx.next_call_id()
    response = _provider_call(prompt, model=model, **kwargs)
    _persist_full_call_artifact(ctx, call_id, prompt, response)
    return response, call_id
```

**Runtime assertions inside `logged_llm_call`:**
- `call_id` must be assigned (non-None)
- Artifact file must be written. Failure to persist raises `RuntimeError`, does not warn.
- `prompt_text` and `response_text` in the artifact must be byte-identical to provider input/output. Verified by hash comparison before and after serialization.

### C.2 — Call Artifact Schema

```json
{
    "call_id": 1,
    "parent_call_id": null,
    "call_type": "generation" | "classification" | "critique" | "retry_generation",
    "step": "generation" | "critique" | "retry_generation" | "classification",
    "attempt": 0,
    "sequence_index": 1,
    "model": "gpt-5-mini",
    "provider": "openai",
    "temperature": 0.0,
    "timestamp": "2026-04-03T10:00:00Z",
    "case_id": "alias_config_a",
    "condition": "baseline_v2",
    "prompt_text": "<FULL — NO TRUNCATION>",
    "response_text": "<FULL — NO TRUNCATION>",
    "prompt_hash": "<sha256 of prompt_text>",
    "response_hash": "<sha256 of response_text>",
    "latency_ms": 1234,
    "tokens_input_estimate": 500,
    "tokens_output_estimate": 800,
    "event_id": "ref"
}
```

**Linkage guarantees:**
- `sequence_index` is strictly increasing within a case evaluation.
- Retry attempts increment `attempt`.
- Critique calls set `parent_call_id` to the generation call they critique.
- Events referencing calls must reference only prior or same-index calls.
- Events and calls are append-only and strictly ordered.

### C.3 — No Truncation

- `calls/*.json` is canonical. Authoritative.
- No max-char clipping, preview-only storage, or parsed-JSON-only storage.
- Persistence occurs BEFORE any transformation, parsing, or truncation logic.
- Hash invariant: `sha256(prompt_text_sent_to_provider) == prompt_hash` in the stored artifact.

**Required audit before shipping:** scan `llm.py`, `logging_core.py`, `call_logger.py` for any `[:N]` slicing, `max_chars`, or truncation patterns in the canonical storage path.

### C.4 — Validation Gate

1. Baseline run (generation + classification = 2 calls): both artifacts contain non-empty full text.
2. Retry run (generation + critique + retry_generation + classification = 4 calls): all 4 persisted.
3. Long prompt/response test: no truncation.
4. `count(llm_calls) == count(call_artifacts)`. No duplicate call_ids. No gaps in sequence.
5. Every event referencing a call artifact points to an existing file.
6. Hash verification: `prompt_hash` in stored artifact matches `sha256(prompt_text)`.
7. Full run reconstructable from `events.jsonl + calls/*.json`.

### PR: PR3

- **Files:** `llm.py`, `call_logger.py`, `execution_v2.py`, `retry_v2.py`
- **Behavior change:** Call artifacts guaranteed complete. May increase disk usage.
- **Dependencies:** PR2.

---

## Phase D — Parsing, Structural Validation, Recovery Routing

### D.1 — Separated Stages

```python
@dataclass
class StructuralValidationResult:
    structurally_valid: bool
    errors: list[str]
    warnings: list[str]
    expected_files: list[str]
    observed_files: list[str]

@dataclass
class RoutingDecision:
    selected_source: str              # "strict" | "recovery" | "none"
    strict_parse_valid: bool
    recovery_parse_valid: bool
    strict_structurally_valid: bool
    recovery_structurally_valid: bool
    recovery_used: bool
    divergence_detected: bool

@dataclass
class ExecutionPreparation:
    execution_eligible: bool
    recon_status: str                 # see D.3
    recon_errors: list[str]
```

`execution_eligible = (recon_status == "success")`. No inferred logic.

### D.2 — Routing: `_select_artifact`

```python
def _select_artifact(strict, recovery, case):
    strict_sv = validate_structure(strict, case) if strict.parse_valid else INVALID
    recovery_sv = validate_structure(recovery, case) if recovery.parse_valid else INVALID

    if strict.parse_valid and strict_sv.structurally_valid:
        selected = strict
        mode = "strict"
    elif recovery.parse_valid and recovery_sv.structurally_valid:
        selected = recovery
        mode = "recovery"
    else:
        selected = None
        mode = "failed"

    divergence = (
        strict.parse_valid and recovery.parse_valid
        and strict_sv.structurally_valid and recovery_sv.structurally_valid
        and not equivalent(strict, recovery)
    )

    return RoutingDecision(
        selected_source=mode,
        strict_parse_valid=strict.parse_valid,
        recovery_parse_valid=recovery.parse_valid,
        strict_structurally_valid=strict_sv.structurally_valid,
        recovery_structurally_valid=recovery_sv.structurally_valid,
        recovery_used=(mode == "recovery"),
        divergence_detected=divergence,
    )
```

No ambiguity. No interpretation.

### D.3 — Reconstruction Status Enum

```python
recon_status ∈ {
    "success",
    "syntax_error",
    "missing_file",
    "invalid_structure",
    "empty_file",
    "exception",
    "not_attempted"    # routing failed, no artifact selected
}
```

`execution_eligible = (recon_status == "success")`.

### D.4 — Complete Routing Table

| # | Strict PV | Strict SV | Recovery PV | Recovery SV | Div | Selected | Mode | Recovery Used | Exec Eligible (if recon OK) | Classified | Skip Reason | Event Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | T | T | T | T | eq | strict | strict | F | T | T | — | executable |
| 2 | T | T | T | T | div | strict | strict | F | T | T | — | executable |
| 3 | T | T | T | F | — | strict | strict | F | T | T | — | executable |
| 4 | T | T | F | — | — | strict | strict | F | T | T | — | executable |
| 5 | T | T | absent | — | — | strict | strict | F | T | T | — | executable |
| 6 | T | F | T | T | — | recovery | recovery | T | T | T | — | executable |
| 7 | T | F | T | F | — | none | failed | F | F | F | struct_invalid | failed |
| 8 | T | F | F | — | — | none | failed | F | F | F | struct_invalid | failed |
| 9 | T | F | absent | — | — | none | failed | F | F | F | struct_invalid | failed |
| 10 | F | — | T | T | — | recovery | recovery | T | T | T | — | executable |
| 11 | F | — | T | F | — | none | failed | F | F | F | struct_invalid | failed |
| 12 | F | — | F | — | — | none | failed | F | F | F | parse_failed | failed |
| 13 | F | — | absent | — | — | none | failed | F | F | F | parse_failed | failed |
| 14 | any | any | any | any | — | selected | any | any | recon_fail | F | recon_failed | diagnosable |

### D.5 — Reconstruction Event Section

```python
ev["reconstruction"] = {
    "parsing_mode": str,
    "strict_parse_valid": bool,
    "recovery_parse_valid": bool,
    "strict_structurally_valid": bool,
    "recovery_structurally_valid": bool,
    "structural_errors": list[str],
    "recovery_used": bool,
    "divergence_detected": bool,
    "execution_eligible": bool,
    "executed": bool,
    "recon_status": str,
    "files_changed": list[str],
    "files_total": int,
    "artifact_id": str,
}
```

Schema: v7 → v7.1 (additive).

### D.6 — Staged Rollout

PR4a: instrumentation only. PR4b: recovery behind disabled flag. PR4c: activate recovery.

Bake-in: strict-stable cohort exact match. Recovery-eligible cohort: inspect directly, no comparison to nonexistent strict baseline. Divergent cohort: strict selected, divergence count reported.

### D.7 — Validation Gate

PR4a: `reconstruction` present. No behavior change. PR4b: flag-off matches strict-only exactly. PR4c: three cohorts validated. No `executed=true AND execution_eligible=false`.

### PRs: PR4a, PR4b, PR4c

---

## Phase E — Classification Unification

### E.1 — Canonical Classifier

```python
def classify_case(artifact, case, code, config, logger, parent_event_id,
                  condition, artifact_id) -> ClassifierResultV2:
```

Logs `artifact_id` in classification result. Uses `logged_llm_call`.

### E.2 — When Classification Runs

Classification runs whenever `execution_eligible == True`, regardless of execution outcome. Skipped only on parse/structural/reconstruction failure. Execution failure diagnostics are NOT classifier input.

**Invariant:** Classification input is derived from the SAME artifact selected by routing and passed to reconstruction. `classification.artifact_id == execution.artifact_id`.

### E.3 — Classifier Contract

Classifier evaluates ONLY what the generator produces:
- mechanism correctness (from `root_cause`)
- commitment validity (from `fix_strategy` / `code_commitments`)
- alignment (code vs commitments)

**Forbidden:** Classifier seeing execution results, ground truth bugs, or canonical answer patterns.

### E.4 — Lifecycle

| Context | Eligible | Classified | Stored Where |
|---|---|---|---|
| Single-shot: eligible, exec pass | T | T | `ev["classification"]` |
| Single-shot: eligible, exec fail | T | T | `ev["classification"]` |
| Single-shot: not eligible | F | F | `classifier_skipped_reason` |
| Retry attempt N (not final): eligible | T | T | `trajectory[N].classification` |
| Retry final: eligible | T | T | `ev["classification"]` (case-level) |
| Retry final: not eligible | F | F | `classifier_skipped_reason` |

Case-level = final attempt's classification, copied directly. No rollup. Earlier attempts remain in trajectory.

### E.5 — Classification Event Section

```python
ev["classification"] = {
    "mechanism_identified": str | None,    # "CORRECT" | "INCORRECT" | None
    "commitments_extracted": str | None,
    "commitments_satisfied": str | None,
    "reasoning_code_alignment": str | None,
    "classifier_ran": bool,
    "classifier_skipped_reason": str | None,
    "commitment_state": str,               # see Phase I
    "artifact_id": str,
}
```

Schema: v7.1 → v7.2 (additive).

### E.6 — Validation Gate

1. Both baseline and retry produce `classification` with identical structure.
2. No duplicated classifier logic in `retry_v2.py`.
3. `classification.artifact_id == reconstruction.artifact_id` for all events.

### PR: PR5

---

## Phase F — Formal Evaluation Model and Outcome Classification

### Objective

Establish a first-class 3-axis evaluation model. Compute outcome classes once per attempt and log them. No ad-hoc recomputation in analysis.

### F.1 — Three Evaluation Axes

**Axis 1: Serialization (S)**

```
S := (selected_artifact != None) AND (recon_status == "success")
```

Derived from routing + reconstruction.

**Axis 2: Oracle Execution (E)**

```
E := (execution_category == "EXECUTION_SUCCESS")
```

Derived from execution harness.

**Axis 3: Blind Process Evaluation (R)**

```
M := mechanism_correct       # mechanism_identified == "CORRECT"
C := commitments_valid       # commitments_satisfied == "CORRECT"
A := alignment_positive      # reasoning_code_alignment == "CORRECT"

R := M ∧ C                   # reasoning_sufficient
```

Derived from classifier output.

### F.2 — Outcome Classes (Exact Definitions)

```
serialization_failure   := ¬S
interpretable_success   := S ∧ E ∧ R
unsupported_success     := S ∧ E ∧ ¬R
LEG                     := S ∧ ¬E ∧ R
reasoning_failure       := S ∧ ¬E ∧ ¬R
```

These form a **complete partition**. Every attempt belongs to exactly one class.

**Runtime assertion:**

```python
classes = [serialization_failure, interpretable_success, unsupported_success, LEG, reasoning_failure]
assert sum(classes) == 1, f"Outcome partition violated: {classes}"
```

Violation raises `RuntimeError`. No silent misclassification.

### F.3 — LEG Subtyping

```
LEG_congruent   := LEG ∧ A     # reasoning correct, code aligned, but execution fails
LEG_incongruent := LEG ∧ ¬A    # reasoning correct, code misaligned, execution fails
```

### F.4 — Serialization Failure Typing

```python
serialization_failure_type ∈ {
    "parser_failure",
    "invalid_json",
    "structural_invalid",
    "missing_file",
    "recon_failure",
    "unknown",
    None                        # when S == True
}
```

Populated for ALL attempts. `None` when serialization succeeds.

### F.5 — Evaluation Event Section

Every attempt produces:

```python
ev["evaluation"] = {
    "serialization_success": bool,
    "serialization_failure_type": str | None,
    "execution_success": bool,
    "execution_category": str | None,
    "mechanism_correct": bool | None,
    "commitments_valid": bool | None,
    "alignment_positive": bool | None,
    "reasoning_sufficient": bool | None,    # M ∧ C
    "LEG": bool,
    "LEG_subtype": "congruent" | "incongruent" | None,
    "outcome_class": str,                   # one of the 5 classes
    "artifact_id": str,
}
```

**Schema:** v7.2 → v7.3 (additive).

`outcome_class` is computed ONCE in `_compute_evaluation()` and written to the event. Analysis reads it directly. No recomputation.

### F.6 — Implementation: `_compute_evaluation`

```python
def _compute_evaluation(exec_result, classification, routing, artifact_id):
    S = routing.selected_source != "none" and exec_result.get("reconstruction_status") == "success"
    E = exec_result.get("pass", False)

    M = classification.mechanism_identified == "CORRECT" if classification.classifier_ran else None
    C = classification.commitments_satisfied == "CORRECT" if classification.classifier_ran else None
    A = classification.reasoning_code_alignment == "CORRECT" if classification.classifier_ran else None
    R = (M is True and C is True)

    if not S:
        outcome = "serialization_failure"
        s_fail_type = _derive_serialization_failure_type(routing, exec_result)
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

    leg_subtype = None
    if outcome == "LEG":
        leg_subtype = "congruent" if A else "incongruent"

    # Partition assertion
    classes = [not S, S and E and R, S and E and not R, S and not E and R, S and not E and not R]
    assert sum(classes) == 1, f"Partition violated: S={S} E={E} R={R}"

    return {
        "serialization_success": S,
        "serialization_failure_type": s_fail_type,
        "execution_success": E,
        "execution_category": exec_result.get("execution_category"),
        "mechanism_correct": M,
        "commitments_valid": C,
        "alignment_positive": A,
        "reasoning_sufficient": R,
        "LEG": outcome == "LEG",
        "LEG_subtype": leg_subtype,
        "outcome_class": outcome,
        "artifact_id": artifact_id,
    }
```

### F.7 — Validation Gate

1. Partition completeness: no sample assigned multiple classes.
2. LEG cases satisfy `S ∧ ¬E ∧ M ∧ C`.
3. Serialization failure never overlaps with other classes.
4. `artifact_id` consistent: `evaluation.artifact_id == classification.artifact_id == reconstruction.artifact_id`.
5. Smoke test with known LEG case, known success case, known serialization failure.

### PR: PR6

- **Files:** NEW evaluation computation in execution_v2.py helpers, logging_core.py consumed keys
- **Behavior change:** New `evaluation` section in events. Outcome class computed and logged.
- **Dependencies:** PR5 (classification must exist).

---

## Phase G — AST Verification Integration

### G.1 — Role

Non-gating analytical stage. Executes whenever a spec exists. Missing spec explicitly recorded.

### G.2 — Status States

| Status | Meaning |
|---|---|
| `no_spec` | No AST spec for this case |
| `not_measurable` | Spec exists but code not parseable or recon failed |
| `measured_correct` | All required patterns matched |
| `measured_incorrect` | ≥1 required pattern missing |

### G.3 — Event Contract

Every new event MUST contain `ast_eval`:

```python
ev["ast_eval"] = {
    "status": str,
    "ast_correct": bool | None,
    "ast_score": float | None,
    "patterns_matched": list[str],
    "patterns_missing": list[str],
    "reason": str | None,
    "artifact_id": str,
}
```

**Invariant:** AST runs on the SAME reconstructed artifact used for execution. `ast_eval.artifact_id == reconstruction.artifact_id`. AST must NOT run on raw parsed output.

### G.4 — Validation Gate

1. Covered case + reference fix → `measured_correct`.
2. Covered case + buggy code → `measured_incorrect`.
3. Uncovered case → `no_spec` (explicitly present).
4. Syntax-broken → `not_measurable` with reason.
5. FP < 10%, FN < 20%.
6. `ast_eval.artifact_id == reconstruction.artifact_id`.

### PR: PR7

- **Files:** NEW `ast_eval.py`, NEW `ast_specs.json`, `execution_v2.py`, `retry_v2.py`
- **Dependencies:** PR1, PR4c.

---

## Phase H — Invariant/Test Audit (Parallel)

### H.1 — Prioritization

Score = `LEG% × 0.25 + (1-pass%) × 0.20 + (1/checks) × 0.15 + trap_density × 0.15 + centrality × 0.15 + invariant_softness × 0.10`

Top 9 families audited. Each: current assertions, plausible trap fixes, missing invariant classes, proposed assertions, buggy/reference/trap-fix validation.

### H.2 — Rules

No new invariant without buggy-fails + reference-passes. Trap-fix validation required. No decorative assertions.

### PR: PR8

- **Files:** 9 test files. **Dependencies:** None (parallel).

---

## Phase I — Baseline Commitments, Metric Materialization, Analysis Migration

### I.1 — Baseline Commitments

**Commitment State Model:**

| State | Evaluator Behavior |
|---|---|
| `missing` | Infer from fix_strategy |
| `explicit_valid` | Use explicit |
| `explicit_low_quality` | Record; fall back to inferred |
| `explicit_malformed` | Record; fall back to inferred |
| `inferred` | Mode used when fallback performed |

Logged as `ev["classification"]["commitment_state"]`.

Validation: presence ≥80%, valid quality ≥60%.

### I.2 — Metric Materialization Layer

```python
def build_attempt_table(events_path: Path) -> pd.DataFrame:
    """Canonical analysis input. One row per attempt. No recomputation."""
```

Reads events.jsonl. Produces flat table with columns:

- `case_id`, `model`, `condition`, `trial`, `attempt`
- `serialization_success`, `serialization_failure_type`
- `execution_success`, `execution_category`
- `mechanism_correct`, `commitments_valid`, `alignment_positive`, `reasoning_sufficient`
- `LEG`, `LEG_subtype`, `outcome_class`
- `parsing_mode`, `recovery_used`, `structurally_valid`, `execution_eligible`
- `ast_status`, `ast_correct`, `ast_score`
- `commitment_state`
- `artifact_id`

**Guarantee:** `outcome_class` is read directly from the event. Not recomputed.

### I.3 — Retry Integrity

- Each attempt produces a full evaluation record (serialization, execution, classification, evaluation, AST).
- Attempts linked by `attempt_index` and `parent_attempt_id`.
- Final selected attempt does NOT overwrite earlier attempts. All attempts remain observable in trajectory.

### I.4 — Analysis Migration

Update scripts to consume `reconstruction`, `classification`, `evaluation`, `ast_eval`. Add fallback for old events.

### PRs: PR9 (commitments), PR10 (materialization + analysis)

---

## PR Summary

| PR | Phase | Behavior Change | Dependencies |
|---|---|---|---|
| PR1 | A | No | None |
| PR2 | B | No (refactor) | PR1 |
| PR3 | C | No (logging completeness) | PR2 |
| PR4a | D (instrumentation) | No | PR2 |
| PR4b | D (flag-off routing) | No | PR4a |
| PR4c | D (activate recovery) | YES | PR4b |
| PR5 | E | YES (unified classifier) | PR2, PR4a |
| PR6 | F | YES (evaluation model) | PR5 |
| PR7 | G | No (ast_eval field) | PR1, PR4c |
| PR8 | H | YES (stricter tests) | None (parallel) |
| PR9 | I.1 | YES (commitments) | PR5 |
| PR10 | I.2-I.4 | No (analysis) | PR6, PR7 |

---

## Hidden Assumptions and Failure Modes

| Assumption | Risk | Detection | Contingency |
|---|---|---|---|
| Recovery outputs are often structurally salvageable | Most degenerate | `structurally_valid=false` rate | Skip PR4c if >80% invalid |
| Classifier useful on execution-failed code | Noise | Agreement rate | Restrict to exec-success |
| Models produce usable commitments | Generic | Quality ≥60% | Defer migration |
| AST specs achieve acceptable noise | FP/FN high | Manual review | Narrow scope |
| Call artifact disk acceptable | Disk fills | Monitor | Compress old runs |
| Partition assertion never fires in production | Logic error | Assertion raises | Debug immediately |
| `logged_llm_call` does not add latency | Sync I/O | Benchmark | Buffer writes |

---

## Acceptance Criteria

### Critical Path
- One readable top-level function ≤60 lines. No peer duplicates flow. Retry uses same helpers.

### Paths
- Zero critical-path repo-layout literals outside exceptions. Enforcement active. Preflight catches missing assets + unwritable run dirs.

### Logging
- Every LLM call routes through `logged_llm_call`. No bypass. `count(llm_calls) == count(artifacts)`. No duplicate call_ids. No gaps. Hash verification. No truncation. Full reconstruction proven.

### Parsing/Recovery
- Four states distinct and logged. Recovery routing follows specified policy. Flag rollback works.

### Classification
- One canonical entrypoint. Runs on execution failure. `artifact_id` consistent.

### Evaluation Model
- `outcome_class` computed once, logged, never recomputed. Partition assertion enforced. LEG/LEG_subtype logged. Serialization typed. All axes queryable from flat table.

### AST
- `ast_eval` on every event. Four statuses tested. `artifact_id` consistent. Phase-1 validation passes.

### Invariants
- ≥30 of 58 cases with ≥3 checks. Scoring rubric applied. Validated against buggy/reference/trap-fix.

### Backward Compatibility
- Old events readable. Missing sections handled with fallback. No crashes.

---

## Appendix: Hardcoded Path Inventory

| Location | Hardcoded String | Critical? | Replacement | PR |
|---|---|---|---|---|
| execution_v2.py:38-40 | `Path("core/prompts/...")` × 3 | YES | `paths.*` | PR1 |
| retry_v2.py:46-48 | Same × 3 | YES | Same | PR1 |
| exec_canonical.py:109 | `"core" / "harness" / "run_case.py"` | YES | `paths.HARNESS_SCRIPT` | PR1 |
| test_loader.py:64 | `"case_data" / "tests_v2"` | YES | `paths.TESTS_V2_DIR` | PR1 |
| validate_cases_v2.py:53 | `"tests_v2"` | YES | `paths.TESTS_V2_DIR` | PR1 |
| orchestrate.py (multiple) | filenames | YES | `paths.*_FILENAME` | PR1 |
| runner.py:240 | `"heartbeat.json"` | NO | `paths.HEARTBEAT_FILENAME` | PR1 |
| orchestrate.py:805 | `/proc/{pid}/cmdline` | NO | Leave | — |
| run_case.py:41,50,158 | CWD-relative | NO | Leave | — |
