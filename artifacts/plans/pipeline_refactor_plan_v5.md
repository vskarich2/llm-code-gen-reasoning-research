# Pipeline Refactor Plan v5

**Date:** 2026-04-03
**Status:** PLAN — awaiting approval
**Supersedes:** pipeline_refactor_plan_v4.md

---

## Structure

Eight phases. Each is a shippable unit with a validation gate. No phase begins until its predecessor's gate passes, except Phase G (invariant audit) which has no upstream dependency.

- **Phase A** — Path centralization, enforcement, preflight
- **Phase B** — Critical-path readability refactor
- **Phase C** — Full-fidelity prompt/response logging
- **Phase D** — Parsing, structural validation, and recovery routing
- **Phase E** — Classification unification
- **Phase F** — AST verification integration
- **Phase G** — Invariant/test audit (parallel)
- **Phase H** — Baseline commitments, analysis migration

---

## Non-Goals / Explicitly Rejected Approaches

- Scattering path constants across multiple modules.
- Building a path-abstraction framework. The path module is small and practical.
- Replacing hardcoded paths with env vars only.
- Adding a parallel schema reader.
- Duplicating classifier logic. One canonical entrypoint. No temporary duplication without same-phase removal.
- Silent fallback behavior without explicit event fields.
- Burying migration complexity under "analysis can handle it."
- Mixing architecture cleanup with behavior changes in the same PR unless mechanically coupled.
- Judging path centralization complete because a constants file exists.
- Judging commitments migration successful because the field appears.
- Judging recovery fallback successful because parse-valid counts rise.
- Judging AST rollout successful because fields are populated.
- Judging test strengthening successful because assertion count increases.
- Allowing arbitrary-path helper functions in critical-path modules beyond `resolve_run_dir`.
- Letting structural validation be "best effort" before execution.
- Letting classifier lifecycle differ between execution and retry paths.
- Truncating prompts or responses in canonical research storage.
- Max-char clipping, prompt-preview-only storage, or response-preview-only storage.
- Storing only parsed JSON while dropping the raw model text.
- Distributing the critical-path control flow across multiple peer modules with no single readable entrypoint.
- Allowing any LLM call in the critical path to bypass the canonical call-artifact logger.
- Burying full-fidelity logging after behavior-changing pipeline work in the PR sequence.

---

## Phase A — Path Centralization, Enforcement, Preflight

### Objective

Stop hardcoding paths everywhere. Centralize in one small module. Enforce. Preflight.

### A.1 — Central Path Module: `core/config/paths.py`

```python
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Case data
CASE_DATA_DIR       = PROJECT_ROOT / "case_data"
CASES_V2_PATH       = CASE_DATA_DIR / "cases_v2.json"
TESTS_V2_DIR        = CASE_DATA_DIR / "tests_v2"
CODE_SNIPPETS_DIR   = CASE_DATA_DIR / "code_snippets_v2"
REFERENCE_FIXES_DIR = CASE_DATA_DIR / "reference_fixes"
AST_SPECS_PATH      = CASE_DATA_DIR / "ast_specs.json"

# Prompts
PROMPTS_DIR         = PROJECT_ROOT / "core" / "prompts"
COMPONENTS_DIR      = PROMPTS_DIR / "components"
PROMPT_MANIFEST     = PROMPTS_DIR / "prompt_manifest.yaml"
COMPONENT_META      = PROMPTS_DIR / "component_metadata.yaml"

# Harness
HARNESS_SCRIPT      = PROJECT_ROOT / "core" / "harness" / "run_case.py"

# Default output root
DEFAULT_LOGS_DIR    = PROJECT_ROOT / "logs"

# Canonical output filenames
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
    """Resolve configured output directory root. Only run/output roots may use this.
    Repo asset paths must never pass through this function."""
    p = Path(run_dir_str)
    p = (p if p.is_absolute() else PROJECT_ROOT / p).resolve()
    if not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    return p

def resolve_test_path(family: str) -> Path:
    return TESTS_V2_DIR / f"test_{family}.py"
```

**Boundary rules:**
- Only run/output roots may come from config or arbitrary string resolution.
- Repo asset paths (cases, tests, prompts, harness, AST specs) must never come from config or arbitrary strings. They are defined only in `paths.py`.
- `resolve_run_dir()` exists only for the configured output directory root. No additional generic path resolvers are allowed in critical-path modules.

### A.2 — Enforcement

`scripts/check_forbidden_paths.py` scans `core/` (excluding `paths.py`, `run_case.py`, test files, comments). Detects forbidden patterns: `"core/"`, `"case_data/"`, `"tests_v2"`, `"code_snippets"`, `"prompts/"`, `"components/"`, `"reference_fixes"`, `"ast_specs"` in Path constructors or path-like string literals. Exits non-zero on match.

**Documented exceptions:** `paths.py` itself, `run_case.py` (CWD-relative temp dir), `/proc/{pid}/cmdline` (system path).

Run as mandatory pre-merge check on PRs touching `core/`.

### A.3 — Preflight

`core/config/preflight.py`:

```python
def validate_startup(config=None) -> None:
    """Fails fast with RuntimeError if canonical assets are missing or output roots are invalid."""
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
        if not run_dir.parent.exists():
            missing.append(f"run_dir parent: {run_dir.parent}")
    if missing:
        raise RuntimeError("Preflight failed:\n" + "\n".join(missing))
```

Called at runner startup and orchestrator startup, before workers launch.

### A.4 — Validation Gate

1. Enforcement script exits 0.
2. Preflight passes.
3. Smoke test: 1 case × 1 model × baseline_v2.
4. Rename proof: rename `case_data/tests_v2/` → update `TESTS_V2_DIR` → verify pipeline uses renamed directory → revert.

### PR: PR1

- **Files:** `core/config/paths.py`, NEW `core/config/preflight.py`, NEW `scripts/check_forbidden_paths.py`, + 8 core modules (see Appendix)
- **Behavior change:** None.
- **Rollback:** Revert.

---

## Phase B — Critical-Path Readability Refactor

### Objective

One readable top-level orchestration function. Hard architectural constraint.

### B.1 — Top-Level Function

`execution_v2.py` must expose one canonical function for the single-shot execution path. This function is the authoritative tree root. It must remain ≤60 lines. All major stages appear in sequence. Detailed logic is delegated to helpers.

No peer orchestration function may duplicate this flow.

```python
def run_v2(case, model, condition, logger, case_start_eid=0):
    """Canonical critical path. ≤60 lines. Shows all stages."""
    config = _get_config()
    ctx = _build_context(case, model, condition, config, logger, case_start_eid)

    # 1. Render prompt
    prompt, prompt_meta = _render_generation_prompt(ctx)

    # 2. Call model (canonical logged call — full prompt/response persisted)
    raw_response, gen_eid = _call_generation_model(ctx, prompt, prompt_meta)

    # 3. Parse strict + recovery
    strict_parse, recovery_parse = _parse_outputs(raw_response, condition)

    # 4. Validate structure + select artifact
    routing = _select_artifact(strict_parse, recovery_parse, case)

    # 5. Reconstruct
    recon = _reconstruct(ctx, routing)

    # 6. Determine execution eligibility
    eligibility = _check_execution_eligibility(routing, recon)

    # 7. Execute (if eligible)
    exec_result = _execute(ctx, recon, eligibility)

    # 8. Classify reasoning (if eligible, regardless of execution outcome)
    classification = _classify(ctx, routing, case, exec_result, gen_eid)

    # 9. AST verification
    ast_result = _run_ast(recon, case)

    # 10. Derive metrics + assemble event
    ev = _assemble_event(ctx, exec_result, routing, recon, eligibility,
                         classification, ast_result)

    # 11. Emit
    _emit_event(ctx, ev, gen_eid)

    return case["id"], condition, ev
```

### B.2 — Retry Integration

`retry_v2.py` is a thin loop over the same helpers. Retry-specific logic decides *when* to call helpers (loop control, critique generation) but does NOT reimplement *how* parse/structure/execute/classify/AST/logging work. Generation, critique, classification, AST, and event assembly logic must not fork into separate implementations.

### B.3 — Validation Gate

1. `run_v2()` is ≤60 lines.
2. Smoke test: identical results to pre-refactor for 3 cases × 2 models.
3. No behavior change.
4. The function is the only human-facing root for the single-shot path. No peer function duplicates the flow.

### PR: PR2

- **Files:** `execution_v2.py` (refactor), `retry_v2.py` (call shared helpers)
- **Behavior change:** None.
- **Dependencies:** PR1.

---

## Phase C — Full-Fidelity Prompt and Response Logging

### Objective

Guarantee that every LLM call in the critical path persists full prompt text and full raw response. No truncation. This lands BEFORE any behavior-changing pipeline work so the refactor itself is auditable.

### C.1 — Universal Call Logging Architecture

**Invariant:** No LLM call in the critical path may bypass the canonical call-artifact logger.

This includes: generation calls, classifier calls, retry critique calls, retry generation calls, and any future evaluator/judge/repair calls.

**Implementation:** Persistence responsibility lives in one canonical function, called by the LLM interface layer, not sprinkled across orchestration helpers.

```python
# In core/pipeline/llm.py (or equivalent single layer):

def logged_llm_call(prompt: str, *, model: str, logger, ctx: CallContext, **kwargs) -> LLMResponse:
    """Every critical-path LLM call goes through here. Full prompt/response persisted."""
    response = _provider_call(prompt, model=model, **kwargs)
    _persist_full_call_artifact(ctx, prompt, response)
    return response
```

All orchestration code (`execution_v2.py`, `retry_v2.py`) calls `logged_llm_call` instead of a raw provider call. No orchestration module persists call artifacts itself.

### C.2 — Canonical Storage

**Per-call artifact files** in `{worker_dir}/calls/`:

```json
{
    "call_id": 1,
    "call_type": "generation" | "classification" | "critique" | "retry_generation",
    "model": "gpt-5-mini",
    "provider": "openai",
    "temperature": 0.0,
    "timestamp": "2026-04-03T10:00:00Z",
    "case_id": "alias_config_a",
    "condition": "baseline_v2",
    "attempt": 0,
    "prompt_text": "<FULL PROMPT — NO TRUNCATION>",
    "response_text": "<FULL RAW RESPONSE — NO TRUNCATION>",
    "latency_ms": 1234,
    "tokens_input_estimate": 500,
    "tokens_output_estimate": 800,
    "event_id": "ref_to_parent_event"
}
```

`calls_flat/*.txt` is optional human-readable convenience. Event logs store references and metadata, not full text.

### C.3 — No Truncation Rules

- `calls/*.json` is the canonical full-fidelity record. Authoritative.
- No max-char clipping.
- No prompt-preview-only storage.
- No response-preview-only storage.
- No storing only parsed JSON while dropping raw model text.
- Any preview/snippet field in events or dashboards must be clearly marked non-canonical.
- No code path may overwrite canonical full prompt/response with a shortened form.

**Required audit:** Before shipping PR3, audit `pipeline/llm.py`, `logging_core.py`, `call_logger.py`, and any dashboard/export helper for truncation logic. Remove or bypass any truncation in the canonical storage path.

### C.4 — Reconstruction Invariant

A run is not research-complete unless, for every LLM call in the critical path, the full prompt text and full raw response are recoverable from `calls/*.json`.

### C.5 — Validation Gate

1. Run 1 case × 1 model × baseline_v2 (generation + classification = 2 LLM calls).
2. `calls/000001.json` contains non-empty `prompt_text` (full generation prompt).
3. `calls/000001.json` contains non-empty `response_text` (full raw response).
4. `calls/000002.json` contains full classifier prompt and response.
5. Run 1 case × 1 model × retry condition (generation + critique + retry_generation + classification = 4 LLM calls). Verify all 4 have full artifacts.
6. Deliberately long prompt/response test: no truncation.
7. Every event that references a call artifact (`llm_call.request_path`) points to an existing file with non-empty `prompt_text` and `response_text`.
8. Full run reconstruction: from `events.jsonl + calls/*.json` only, reconstruct every prompt and response without needing ephemeral in-memory state.

### PR: PR3

- **Files:** `core/pipeline/llm.py` (canonical logged call), `core/logging_/call_logger.py` (ensure completeness + no truncation), `execution_v2.py` (use `logged_llm_call`), `retry_v2.py` (same)
- **Behavior change:** Call artifacts now guaranteed complete. May slightly increase disk usage.
- **Rollback:** Revert.
- **Dependencies:** PR2.

---

## Phase D — Parsing, Structural Validation, and Recovery Routing

### Objective

First-class lenient parsing fallback with structural validation gating execution eligibility.

### D.1 — Separated Stages

Four objects, cleanly separated. None jammed together.

**Structural Validation** (runs on parsed output, before reconstruction):

```python
@dataclass
class StructuralValidationResult:
    structurally_valid: bool
    errors: list[str]
    warnings: list[str]
    expected_files: list[str]
    observed_files: list[str]
```

Checks: required file coverage, no duplicate file keys, no empty changed-file payloads, valid changed/unchanged semantics (not all UNCHANGED), file basename consistency, no structurally degenerate output.

**Routing Decision** (selects which parsed artifact to use):

```python
@dataclass
class RoutingDecision:
    selected_source: str              # "strict" | "recovery" | "none"
    strict_parse_valid: bool
    recovery_parse_valid: bool
    strict_structurally_valid: bool
    recovery_structurally_valid: bool
    recovery_used: bool
    divergence_detected: bool
```

**Execution Preparation** (after reconstruction):

```python
@dataclass
class ExecutionPreparation:
    execution_eligible: bool
    recon_status: str
    recon_errors: list[str]
```

`execution_eligible` is true only when: routing selected an artifact + structural validation passed + reconstruction succeeded enough for execution.

**Execution Result** (after execution harness):

```python
executed: bool  # True if code was submitted to harness
```

### D.2 — Routing Policy

1. Attempt strict parse.
2. Attempt recovery parse.
3. Validate structure for each successful parse.
4. Prefer strict if strict parse-valid AND structurally valid.
5. Use recovery only if strict is unusable AND recovery is parse-valid AND structurally valid.
6. If both unusable, mark failed.
7. If both valid + structurally valid but divergent: execute strict, record divergence, keep recovery as diagnostic.

### D.3 — Complete Routing Table

| # | Strict PV | Strict SV | Recovery PV | Recovery SV | Equiv/Div | Selected | `parsing_mode` | `recovery_used` | `divergence` | Exec Eligible (if recon OK) | Classified | `classifier_skipped_reason` | Event Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | T | T | T | T | equiv | strict | strict | F | F | T | T | — | executable |
| 2 | T | T | T | T | div | strict | strict | F | T | T | T | — | executable |
| 3 | T | T | T | F | — | strict | strict | F | F | T | T | — | executable |
| 4 | T | T | F | — | — | strict | strict | F | F | T | T | — | executable |
| 5 | T | T | absent | — | — | strict | strict | F | F | T | T | — | executable |
| 6 | T | F | T | T | — | recovery | recovery | T | F | T | T | — | executable |
| 7 | T | F | T | F | — | none | failed | F | F | F | F | struct_invalid | failed |
| 8 | T | F | F | — | — | none | failed | F | F | F | F | struct_invalid | failed |
| 9 | T | F | absent | — | — | none | failed | F | F | F | F | struct_invalid | failed |
| 10 | F | — | T | T | — | recovery | recovery | T | F | T | T | — | executable |
| 11 | F | — | T | F | — | none | failed | F | F | F | F | struct_invalid | failed |
| 12 | F | — | F | — | — | none | failed | F | F | F | F | parse_failed | failed |
| 13 | F | — | absent | — | — | none | failed | F | F | F | F | parse_failed | failed |
| 14 | any | any | any | any | — | selected | any | any | any | recon fails | F | recon_failed | diagnosable |

Row 14: selected artifact passed parse + structural validation, but reconstruction itself failed. `execution_eligible = false`. Event status = diagnosable (metadata preserved, execution did not run).

### D.4 — Reconstruction Event Section

```python
ev["reconstruction"] = {
    "parsing_mode": "strict" | "recovery" | "failed",
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
}
```

**Schema:** v7 → v7.1 (additive backward-compatible). Old readers tolerate missing section. New readers check presence. Coexistence indefinite.

### D.5 — Staged Rollout

**PR4a — Instrumentation only:** Populate `reconstruction` section. Run structural validation. Log everything. Recovery remains diagnostic-only. No behavior change.

**PR4b — Recovery behind disabled flag:** `_ENABLE_RECOVERY_EXECUTION = False`. Routing logic wired but gated. When off: identical to PR4a.

**PR4c — Activate recovery:** Set flag True. Controlled bake-in first:

**Bake-in validation (3 cohorts):**

1. **Strict-stable cohort:** Cases where strict parse + strict structural validation succeed under both flag-off and flag-on. Requirement: outputs and metrics match exactly.

2. **Recovery-eligible cohort:** Cases where strict is unusable but recovery is valid + structurally valid. Requirement: inspect recovery-executed outcomes directly. Report pass rate, failure categories, reconstruction categories, classification coverage. No comparison to nonexistent strict-execution baseline.

3. **Divergent dual-valid cohort:** Both strict and recovery valid but divergent. Requirement: strict remains selected. Divergence count reported.

Run bake-in on 3 cases × 2 models × 10 trials. If strict-stable exact match passes and recovery-eligible cohort produces non-degenerate results, proceed to full activation.

### D.6 — Validation Gate

1. PR4a: `reconstruction` present in all new events. No execution behavior change.
2. PR4b: flag-off path matches strict-only baseline exactly.
3. PR4c: all three bake-in cohorts validated. No event has `executed=true AND execution_eligible=false`.

---

## Phase E — Classification Unification

### Objective

One canonical classifier entrypoint. One lifecycle. Zero duplication.

### E.1 — Canonical Classifier

```python
def classify_case(artifact, case, code, config, logger, parent_event_id, condition) -> ClassifierResultV2:
    """Canonical classifier. Called by execution_v2 and retry_v2. No other module builds classifier prompts."""
```

Owns: variable assembly, prompt compilation, model call (via `logged_llm_call`), output parsing.

### E.2 — When Classification Runs

Classification runs whenever the selected artifact is parse-valid, structurally valid, and execution-eligible, **regardless of whether execution later succeeds or fails.**

Classification is skipped only when parse or structural validation fails, or when reconstruction fails (row 14).

Execution failure diagnostics are NOT part of classifier input. The classifier evaluates the code artifact and reasoning, not the runtime behavior.

### E.3 — Lifecycle

| Context | Parse Valid | Struct Valid | Exec Eligible | Executed | Classified | Stored Where |
|---|---|---|---|---|---|---|
| Single-shot: eligible, exec success | T | T | T | T | T | `ev["classification"]` |
| Single-shot: eligible, exec fail | T | T | T | T | T | `ev["classification"]` |
| Single-shot: struct fail | T | F | F | F | F | `classifier_skipped_reason` |
| Single-shot: parse fail | F | — | F | F | F | `classifier_skipped_reason` |
| Retry attempt N (not final): eligible | T | T | T | T | T | `trajectory[N].classification` |
| Retry attempt N: struct fail | T | F | F | F | F | `trajectory[N].classifier_skipped_reason` |
| Retry final attempt: eligible | T | T | T | T | T | `ev["classification"]` (case-level) |
| Retry final attempt: not eligible | T/F | F | F | F | F | `ev["classification"].classifier_skipped_reason` |

Case-level classification = final attempt's classification, copied directly. No rollup.

If earlier attempts classified but final did not: case-level `classifier_ran = false`, `classifier_skipped_reason` explains why. Earlier attempt classifications remain in trajectory.

### E.4 — Classification Event Section

```python
ev["classification"] = {
    "mechanism_identified": str | None,
    "commitments_extracted": str | None,
    "commitments_satisfied": str | None,
    "reasoning_code_alignment": str | None,
    "classifier_ran": bool,
    "classifier_skipped_reason": str | None,
    "commitment_state": "missing" | "explicit_valid" | "explicit_low_quality" |
                        "explicit_malformed" | "inferred",
}
```

**Schema:** v7.1 → v7.2. Additive backward-compatible.

**Explicit prohibitions:** No duplicated classifier variable assembly, prompt compilation, or output parsing between `execution_v2.py` and `retry_v2.py`.

### E.5 — Validation Gate

1. Run baseline_v2 and retry condition on 1 case each. Both produce `classification` with identical structure.
2. `grep -rn "build_classifier_v2_vars" core/pipeline/orchestration/` shows calls to `classify_case()` only.
3. `retry_v2.py` does not contain `build_classifier_v2_vars` or `parse_classifier_v2_output`.

### PR: PR5

- **Files:** `evaluator_v2.py` (extract), `execution_v2.py` (call), `retry_v2.py` (call), `logging_core.py` (consumed keys)
- **Behavior change:** Classification results move from `extra` to `classification`. Runs identically in both paths.
- **Dependencies:** PR2, PR4a.

---

## Phase F — AST Verification Integration

### Objective

Deterministic structural verification that executes automatically whenever a case has AST coverage. Non-gating. Explicitly records unavailability.

### F.1 — Role

AST is a non-gating analytical stage. It does not block execution. It does not invalidate results. It executes every time a spec exists. Missing spec is explicitly recorded, not silently omitted.

### F.2 — Status States

Every evaluation emits one of four AST states:

| Status | Meaning |
|---|---|
| `no_spec` | No AST spec for this case |
| `not_measurable` | Spec exists but code not parseable or reconstruction failed |
| `measured_correct` | Spec exists, code parseable, all required patterns matched |
| `measured_incorrect` | Spec exists, code parseable, ≥1 required pattern missing |

### F.3 — Event Contract

Every new event MUST contain:

```python
ev["ast_eval"] = {
    "status": "no_spec" | "not_measurable" | "measured_correct" | "measured_incorrect",
    "ast_correct": bool | None,      # True/False for measured_*, None otherwise
    "ast_score": float | None,       # fraction of patterns matched, None if not measurable
    "patterns_matched": list[str],   # empty if not measured
    "patterns_missing": list[str],   # empty if not measured
    "reason": str | None,            # populated for not_measurable (e.g., "syntax_error")
}
```

`ast_eval` must never be absent from new events. `no_spec` and `not_measurable` are valid, explicit states.

### F.4 — Design

`core/evaluation/ast_eval.py`:
- Loads specs from `paths.AST_SPECS_PATH`.
- Detector registry and spec lookup are separate.
- Phase 1: 5 detectors, 15 single-file cases.

### F.5 — Validation Gate

1. Covered case with reference fix → `measured_correct`.
2. Covered case with buggy code → `measured_incorrect`.
3. Uncovered case → `no_spec` (explicitly present in event).
4. Syntax-broken case → `not_measurable` with `reason="syntax_error"`.
5. FP < 10%, FN < 20% on manual review of 10 model outputs per case.

### PR: PR7

- **Files:** NEW `core/evaluation/ast_eval.py`, NEW `case_data/ast_specs.json`, `execution_v2.py` (add stage), `retry_v2.py` (add after final attempt)
- **Behavior change:** New `ast_eval` field in all events.
- **Dependencies:** PR1, PR4c.

---

## Phase G — Invariant/Test Audit (Parallel)

### Objective

Strengthen invariants for the 13 single-test families. Target: ≥30 of 58 cases with ≥3 distinct checks.

### G.1 — Prioritization

Score = `LEG% × 0.25 + (1 - pass%) × 0.20 + (1/checks) × 0.15 + trap_density × 0.15 + centrality × 0.15 + invariant_softness × 0.10`

Where:
- `trap_density` ∈ {0, 0.5, 1}: known plausible trap fixes
- `centrality` ∈ {0, 0.5, 1}: core to paper claims (high-LEG, intervention-responsive)
- `invariant_softness` ∈ {0, 0.5, 1}: evidence current tests admit false positives (trap fixes pass)

| Rank | Family | LEG% | Pass% | Checks | Traps | Central | Soft | Score |
|---|---|---|---|---|---|---|---|---|
| 1 | invariant_partial_fail | 93 | 6 | 2 | 1.0 | 1.0 | 1.0 | 0.82 |
| 2 | config_shadowing | 64 | 30 | 3 | 1.0 | 1.0 | 0.5 | 0.62 |
| 3 | feature_flag_drift | 67 | 31 | 5 | 1.0 | 1.0 | 0.5 | 0.56 |
| 4 | l3_state_pipeline | 62 | 34 | 3 | 0.5 | 1.0 | 0.5 | 0.56 |
| 5 | hidden_dep_multihop | 60 | 40 | 4 | 1.0 | 1.0 | 0.5 | 0.53 |
| 6 | false_fix_deadlock | 77 | 20 | 8 | 0.5 | 0.5 | 0.0 | 0.39 |
| 7 | lost_update | 57 | 34 | 4 | 0.5 | 0.5 | 0.5 | 0.42 |
| 8 | overdetermination | 25 | 70 | 1 | 0.5 | 0.5 | 1.0 | 0.44 |
| 9 | cache_invalidation_order | 52 | 48 | 4 | 0.5 | 0.5 | 0.5 | 0.37 |

### G.2 — Per-Family Audit

For each of the top 9: current assertions, plausible trap fixes, missing invariant classes, proposed new assertions, validation against buggy/reference/trap-fix.

### G.3 — Rules

1. No new invariant without buggy-fails + reference-passes.
2. Trap-fix validation required when a trap fix is identified.
3. No decorative assertions.

### PR: PR8

- **Files:** 9 test files in `case_data/tests_v2/`
- **Behavior change:** Tests are stricter.
- **Dependencies:** None (parallel).

---

## Phase H — Baseline Commitments and Analysis Migration

### H.1 — Baseline Commitments Contract Migration

Add `code_commitments` to baseline_v2 output schema.

**Commitment State Model:**

| State | Condition | Evaluator Behavior |
|---|---|---|
| `missing` | Field absent | Fall back to inferred from `fix_strategy` |
| `explicit_valid` | Present, ≥1 references concrete code entity with specific behavioral property | Use explicit commitments |
| `explicit_low_quality` | Present, all generic ("fix the bug", "handle correctly") | Record low-quality; fall back to inferred |
| `explicit_malformed` | Present, not parseable as list of strings | Record malformed; fall back to inferred |
| `inferred` | Actual mode used when fallback inference performed | Used for scoring |

**Examples — acceptable:** `"create_config must return a copy of DEFAULTS"`, `"cache invalidation must occur after db write"`, `"rollback path must restore sender balance on failure"`

**Examples — unacceptable:** `"fix the bug"`, `"handle correctly"`, `"ensure proper behavior"`

**Logged as:** `ev["classification"]["commitment_state"]` — one of `missing`, `explicit_valid`, `explicit_low_quality`, `explicit_malformed`, `inferred`.

**Backward compat:** Old runs have no `code_commitments`. Evaluator infers. No behavior change.

**Validation:** 10 trials × 2 models × 3 cases. Presence ≥80%. Valid quality ≥60%. If presence <50% or quality <40%: revise prompt before shipping.

### H.2 — Analysis Migration

Update scripts to consume `reconstruction`, `classification`, `ast_eval`. Add fallback for old events.

### PRs

- **PR6:** Baseline commitments (prompt + schema + parser + evaluator)
- **PR9:** Analysis migration (scripts only)

---

## Critical-Path Readability and Function Boundaries

**Hard architectural constraint:**

- One canonical top-level orchestration function for single-shot execution (`run_v2`)
- ≤60 lines
- All stages visible in sequence
- Helper functions with narrow responsibilities
- No giant orchestration blob
- No peer function duplicating the same flow
- Retry orchestration is a thin loop over the same helpers
- Reading `run_v2()` plus helper names is sufficient to understand execution flow

---

## Hidden Assumptions and Failure Modes

| Assumption | Risk | Detection | Contingency |
|---|---|---|---|
| Recovery outputs are often structurally salvageable | Most recoveries structurally degenerate | `structurally_valid=false` rate in PR4a | If >80% invalid, skip PR4c |
| Classifier produces useful signal on execution-failed code | Noise when code deeply broken | Agreement rate with execution outcomes | Restrict to exec-success-only |
| CWD-relative harness paths survive centralization | `run_case.py` breaks | Documented exception + smoke test | Exclude from scope |
| Models produce usable commitments under baseline prompt | Generic/empty commitments | Quality rate ≥60% | Defer migration |
| AST specs achieve acceptable noise | FP/FN exceed thresholds | Manual review | Narrow to highest-confidence |
| Invariant strengthening targets realistic traps | Traps don't match model behavior | Trap-fix validation | Flag as generalization-only |
| Call artifact disk usage is acceptable | Disk fills | Monitor in bake-in | Compress old runs |
| Logged_llm_call integration does not add latency | Sync I/O slows pipeline | Benchmark before/after | Buffer writes |

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
| PR6 | H.1 | YES (baseline commitments) | PR5 |
| PR7 | F | No (ast_eval field) | PR1, PR4c |
| PR8 | G | YES (stricter tests) | None (parallel) |
| PR9 | H.2 | No (analysis) | PR4a, PR5, PR7 |

---

## Acceptance Criteria

### Critical Path
- One readable top-level orchestration function ≤60 lines
- All stages visible in sequence
- No peer function duplicates the flow
- Retry uses same helper tree

### Paths
- Zero critical-path repo-layout literals outside `paths.py` and documented exceptions
- Enforcement script active and required for merges
- Preflight catches missing assets before workers launch
- Only run/output roots come from config; repo asset paths never pass through `resolve_run_dir`

### Logging
- Every critical-path LLM call routes through `logged_llm_call` (one canonical function)
- Every event referencing a call artifact points to an existing file with non-empty `prompt_text` and `response_text`
- At least one deliberately long prompt/response test proves no truncation
- Full run reconstructable from `events.jsonl + calls/*.json` without ephemeral state
- Generation, classifier, critique, and retry generation calls all persisted

### Parsing/Recovery
- `parse_valid`, `structurally_valid`, `execution_eligible`, `executed` are all distinct and logged
- Recovery routing follows the specified policy
- Flag-off path matches strict-only baseline (strict-stable cohort exact match)
- Recovery-eligible and divergent cohorts reported before broader rollout
- No event has `executed=true AND execution_eligible=false`
- Rollback by flag flip works

### Classification
- One canonical classifier entrypoint
- Classification runs on execution failure when eligibility conditions met
- Per-attempt and case-level storage match lifecycle table
- No duplicated prompt-building or output-parsing

### Commitments
- Presence ≥80%, valid quality ≥60% in new baseline runs
- `commitment_state` records exact state
- Low-quality/malformed fall back to inferred deterministically
- Old runs analyzable with no behavior change

### AST
- Every new event contains `ast_eval` with explicit `status`
- `no_spec`, `not_measurable`, `measured_correct`, `measured_incorrect` all tested explicitly
- Spec loading uses `paths.AST_SPECS_PATH`
- Phase-1 reference/buggy validation passes

### Invariants
- ≥30 of 58 cases have ≥3 checks
- Prioritization follows scoring rubric
- Each new assertion validated against buggy/reference/trap-fix

### Backward Compatibility
- Old events readable without errors
- Missing `reconstruction`, `classification`, `ast_eval` handled with explicit fallback

---

## Appendix: Hardcoded Path Inventory

| Location | Hardcoded String | Critical? | Replacement | PR |
|---|---|---|---|---|
| execution_v2.py:38-40 | `Path("core/prompts/...")` × 3 | YES | `paths.COMPONENTS_DIR/META/MANIFEST` | PR1 |
| retry_v2.py:46-48 | Same × 3 | YES | Same | PR1 |
| exec_canonical.py:109 | `Path(...) / "core" / "harness" / "run_case.py"` | YES | `paths.HARNESS_SCRIPT` | PR1 |
| test_loader.py:64 | `_PROJECT_ROOT / "case_data" / "tests_v2"` | YES | `paths.TESTS_V2_DIR` | PR1 |
| validate_cases_v2.py:53 | `BASE / "tests_v2"` | YES | `paths.TESTS_V2_DIR` | PR1 |
| orchestrate.py (multiple) | `"manifest.json"`, `"events.jsonl"`, etc. | YES | `paths.*_FILENAME` | PR1 |
| runner.py:240 | `"heartbeat.json"` | NO | `paths.HEARTBEAT_FILENAME` | PR1 |
| orchestrate.py:805 | `/proc/{pid}/cmdline` | NO | Leave (system) | — |
| run_case.py:41,50,158 | CWD-relative | NO | Leave (documented) | — |
