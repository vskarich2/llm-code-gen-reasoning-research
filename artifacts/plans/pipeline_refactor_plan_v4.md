# Pipeline Refactor Plan v4

**Date:** 2026-04-03
**Status:** PLAN — awaiting approval
**Supersedes:** pipeline_refactor_plan_v3.md

---

## Structure

Seven phases. Each is a shippable unit with a validation gate. No phase begins until its predecessor's gate passes, except Phase F (invariant audit) which has no upstream dependency.

- **Phase A** — Path centralization, enforcement, preflight
- **Phase B** — Critical-path readability refactor
- **Phase C** — Parsing, structural validation, and recovery routing
- **Phase D** — Full-fidelity prompt/response logging
- **Phase E** — Classification unification
- **Phase F** — Invariant/test audit (parallel)
- **Phase G** — Baseline commitments, AST integration, analysis migration

---

## Non-Goals / Explicitly Rejected Approaches

- Scattering path constants across multiple modules. One module owns all canonical paths.
- Building an elaborate path-abstraction framework. The path module is small and practical.
- Replacing hardcoded paths with env vars only. Env vars are overrides, not primary definitions.
- Adding a parallel schema reader. One event schema, one reader contract.
- Duplicating classifier logic. One canonical classifier entrypoint. No temporary duplication without a same-phase removal step.
- Introducing silent fallback behavior without explicit event fields. Every fallback is observable.
- Burying migration complexity under "analysis can handle it."
- Mixing architecture cleanup with behavior changes in the same PR unless mechanically coupled.
- Judging path centralization complete because a constants file exists. Enforcement must be active.
- Judging commitments migration successful because the field appears. Quality and specificity rates must meet thresholds.
- Judging recovery fallback successful because parse-valid counts rise. Structural validation must gate execution eligibility.
- Judging AST migration successful because fields are populated. FP/FN rates must be within bounds.
- Judging test strengthening successful because assertion count increases. Each assertion must be validated against buggy/reference/trap-fix.
- Allowing arbitrary-path helper functions in critical-path modules.
- Letting structural validation be "best effort" before execution.
- Letting classifier lifecycle differ between execution and retry paths.
- Truncating prompts or responses in canonical research storage.
- Distributing the critical-path control flow across multiple peer modules with no single readable entrypoint.

---

## Phase A — Path Centralization, Enforcement, Preflight

### Objective

Stop hardcoding paths everywhere. Centralize the important paths in one small module. Enforce it. Add preflight.

### A.1 — Central Path Module: `core/config/paths.py`

One small module. Not a framework. Defines:

```python
from pathlib import Path

# Repo root
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

# Default output roots
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

# Small helpers where useful
def resolve_run_dir(run_dir_str: str) -> Path:
    """Resolve run directory from config. Relative paths resolve against PROJECT_ROOT."""
    p = Path(run_dir_str)
    return (p if p.is_absolute() else PROJECT_ROOT / p).resolve()

def resolve_test_path(family: str) -> Path:
    return TESTS_V2_DIR / f"test_{family}.py"
```

That is the entire module. No framework. No elaborate abstractions.

### A.2 — Enforcement

**Script:** `scripts/check_forbidden_paths.py`

Scans all `.py` files under `core/` (excluding `core/config/paths.py`, `core/harness/run_case.py`, test files, and comments). Detects forbidden patterns:
- `"core/"` in Path constructors or string literals used as path components
- `"case_data/"` as a path fragment
- `"tests_v2"` as a path fragment (excluding module import strings)
- `"code_snippets"` as a path fragment
- `"prompts/"` or `"components/"` in Path constructors
- `"reference_fixes"` as a path fragment
- `"ast_specs"` as a path fragment

Exits non-zero on any match. Reports file, line, and matched string.

Run as a mandatory pre-merge check on any PR touching `core/`.

**Documented exceptions:**
- `core/config/paths.py` (defines the paths)
- `core/harness/run_case.py` (CWD-relative temp directory by design: `"case_meta.json"`, `"pkg"`, `"tests_v2.test_{family}"` as module imports)
- `/proc/{pid}/cmdline` in orchestrate.py (system path)

### A.3 — Preflight

**Module:** `core/config/preflight.py`

```python
def validate_startup() -> None:
    """Fails fast with RuntimeError if any canonical asset is missing."""
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
    if missing:
        raise RuntimeError(f"Preflight failed — missing assets:\n" + "\n".join(missing))
```

**Called at:**
- Runner startup (before any case execution)
- Orchestrator startup (before spawning workers)

Failures are loud and immediate. No silent degradation.

### A.4 — Migration

Replace every hardcoded path in the inventory (see Appendix) with the corresponding `paths.py` constant. One PR. No behavior change.

### A.5 — Validation Gate

1. `scripts/check_forbidden_paths.py` exits 0.
2. `core/config/preflight.validate_startup()` passes.
3. Smoke test: 1 case × 1 model × baseline_v2, full execution.
4. Rename proof: rename `case_data/tests_v2/` → `case_data/tests_v2_TMP/`, update `TESTS_V2_DIR`, verify pipeline uses the renamed directory. Then revert.

### PR: PR1

- **Files:** `core/config/paths.py`, NEW `core/config/preflight.py`, NEW `scripts/check_forbidden_paths.py`, + 8 core modules (see Appendix)
- **Behavior change:** None.
- **Rollback:** Revert.

---

## Phase B — Critical-Path Readability Refactor

### Objective

Establish one readable top-level orchestration function that shows the entire pipeline flow. Extract subordinate logic into focused helper functions.

### B.1 — The Critical-Path Function

In `core/pipeline/orchestration/execution_v2.py`, the existing `run_v2()` function is currently ~250 lines with 9 inline stages. Refactor into:

```python
def run_v2(case, model, condition, logger, case_start_eid=0):
    """Top-level critical path. ~50 lines. Shows all stages in order."""
    config = _get_config()
    ctx = _build_context(case, model, condition, config, logger, case_start_eid)

    # 1. Render prompt
    prompt, prompt_meta = _render_generation_prompt(ctx)

    # 2. Call model
    raw_response, gen_eid = _call_generation_model(ctx, prompt, prompt_meta)

    # 3. Persist full prompt + response
    _persist_call_artifacts(ctx, "generation", prompt, raw_response, gen_eid)

    # 4. Parse strict + recovery
    strict_parse, recovery_parse = _parse_outputs(raw_response, condition)

    # 5. Validate structure + select execution artifact
    selected, routing = _select_execution_artifact(strict_parse, recovery_parse, case)

    # 6. Reconstruct + execute
    recon, exec_result = _reconstruct_and_execute(ctx, selected, routing)

    # 7. Classify reasoning
    classification = _classify_reasoning(ctx, selected, case, exec_result, gen_eid)

    # 8. AST verification
    ast_result = _run_ast_verification(recon, case)

    # 9. Derive metrics + assemble event
    ev = _assemble_event(ctx, exec_result, selected, routing, recon,
                         classification, ast_result)

    # 10. Log
    _emit_event(ctx, ev, prompt, raw_response, gen_eid)

    return case["id"], condition, ev
```

Each helper is a focused function of 20-40 lines. The top-level function is ~50 lines and is the single place a human reads to understand pipeline flow.

### B.2 — Helper Boundaries

| Helper | Responsibility | Approximate Size |
|---|---|---|
| `_build_context` | Bundle case/model/config/logger into context object | 10 lines |
| `_render_generation_prompt` | Compile prompt from components + variables | 30 lines |
| `_call_generation_model` | Call LLM, return raw response + event ID | 15 lines |
| `_persist_call_artifacts` | Write full prompt + response to disk (Phase D) | 20 lines |
| `_parse_outputs` | Run strict + recovery parsers | 15 lines |
| `_select_execution_artifact` | Structural validation + routing decision | 30 lines |
| `_reconstruct_and_execute` | Reconstruction + canonical execution | 25 lines |
| `_classify_reasoning` | Canonical classifier call (Phase E) | 20 lines |
| `_run_ast_verification` | AST spec check if available (Phase G) | 15 lines |
| `_assemble_event` | Build complete event dict | 40 lines |
| `_emit_event` | Log event + run record | 15 lines |

### B.3 — Retry Path

`retry_v2.py` calls the same helpers. Per-attempt logic wraps `_parse_outputs` through `_classify_reasoning` in a loop. The retry-specific orchestration function is also kept to ~60 lines, calling shared helpers.

### B.4 — Validation Gate

1. `run_v2()` is ≤60 lines.
2. Each helper function has a single clear responsibility.
3. Smoke test: identical results to pre-refactor for 3 cases × 2 models.
4. No functional behavior change in this PR.

### PR: PR2

- **Files:** `core/pipeline/orchestration/execution_v2.py` (refactor), `core/pipeline/orchestration/retry_v2.py` (call shared helpers)
- **Behavior change:** None. Internal restructuring only.
- **Rollback:** Revert.
- **Dependencies:** PR1.

---

## Phase C — Parsing, Structural Validation, and Recovery Routing

### Objective

Make lenient parsing fallback a first-class execution path with structural validation gating.

### C.1 — Four Execution States

Every evaluation produces these four distinct booleans:

| State | Meaning |
|---|---|
| `parse_valid` | Parser extracted a structured result from raw model output |
| `structurally_valid` | Parsed result passes integrity checks for this case |
| `execution_eligible` | Parsed + structurally valid + reconstruction succeeded |
| `executed` | Code was submitted to the execution harness |

These are never conflated.

### C.2 — Structural Validation

```python
@dataclass
class StructuralValidationResult:
    structurally_valid: bool
    execution_eligible: bool  # structurally_valid AND recon prerequisites met
    errors: list[str]
    warnings: list[str]
    expected_files: list[str]
    observed_files: list[str]
```

**Checks (minimum):**
1. All files in `case["code_files"]` present or marked UNCHANGED
2. No duplicate file keys
3. No empty/null payloads for changed files
4. Valid changed/unchanged semantics (not all UNCHANGED = no change)
5. File basenames match expected module names
6. No structurally degenerate output that would poison execution

**Location:** `_select_execution_artifact()` helper in `execution_v2.py` (Phase B).

### C.3 — Routing Policy

This is the chosen policy:

1. Attempt strict parse.
2. Attempt recovery parse.
3. Validate structure for each successful parse.
4. **Prefer strict** if strict is parse-valid AND structurally valid.
5. **Use recovery** only if strict is unusable AND recovery is parse-valid AND structurally valid.
6. If both unusable, mark failed.
7. If both valid + structurally valid but materially divergent: execute strict, record divergence as diagnostic, keep recovery metadata.

### C.4 — Complete Routing Table

| # | Strict Parse | Strict Struct | Recovery Parse | Recovery Struct | Selected | `parsing_mode` | `recovery_used` | Exec Eligible | Executed | Classified |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | valid | valid | valid, equiv | valid | strict | `strict` | false | yes | yes | yes |
| 2 | valid | valid | valid, divergent | valid | strict | `strict` | false | yes | yes | yes |
| 3 | valid | valid | invalid | — | strict | `strict` | false | yes | yes | yes |
| 4 | valid | valid | not run | — | strict | `strict` | false | yes | yes | yes |
| 5 | valid | **invalid** | valid | valid | recovery | `recovery` | true | yes | yes | yes |
| 6 | valid | **invalid** | valid | **invalid** | none | `failed` | false | no | no | no |
| 7 | valid | **invalid** | invalid | — | none | `failed` | false | no | no | no |
| 8 | **invalid** | — | valid | valid | recovery | `recovery` | true | yes | yes | yes |
| 9 | **invalid** | — | valid | **invalid** | none | `failed` | false | no | no | no |
| 10 | **invalid** | — | invalid | — | none | `failed` | false | no | no | no |

"Classified" = yes whenever execution_eligible is true (see Phase E). "Classified" = no otherwise; `classifier_skipped_reason` populated.

### C.5 — Reconstruction Event Section

```python
ev["reconstruction"] = {
    "parsing_mode": "strict" | "recovery" | "failed",
    "strict_parse_valid": bool,
    "recovery_parse_valid": bool,
    "strict_structurally_valid": bool,
    "recovery_structurally_valid": bool,
    "structural_errors": list[str],
    "recovery_used": bool,
    "execution_eligible": bool,
    "executed": bool,
    "execution_equivalent": bool,
    "strict_recovery_divergent": bool,
    "recon_status": str,
    "files_changed": list[str],
    "files_total": int,
}
```

**Schema:** v7 → v7.1 (additive, backward-compatible).

**Consumer contract:**
- Old readers MUST tolerate missing `reconstruction`. Fallback: `event.get("reconstruction") or {}`.
- New readers MAY rely on `reconstruction` when present.
- Coexistence: indefinite. Old events never backfilled.

### C.6 — Staged Rollout

**PR3a — Instrumentation only:** Populate `reconstruction` section. Run structural validation. Log everything. Recovery remains diagnostic-only. No behavior change.

**PR3b — Recovery behind disabled flag:** Add `_ENABLE_RECOVERY_EXECUTION = False`. Wire routing logic gated by flag. When off: identical to PR3a.

**PR3c — Activate recovery:** Set flag True. Recovery-parsed, structurally-valid outputs now execute. Rollback: set flag False.

**Controlled bake-in:** Activate on a known subset (3 cases × 2 models × 10 trials) first. Compare strict-only baseline to flag-on results. If recovery-used events produce reasonable results (pass rates within 10pp of strict-only), proceed to full activation.

### C.7 — Validation Gate

1. PR3a: `reconstruction` present in all new events. No execution behavior change.
2. PR3b: flag-off path matches strict-only baseline exactly.
3. PR3c: ≥1 event has `recovery_used=true`. All `recovery_used=true` events have `structurally_valid=true`. No event has `executed=true AND execution_eligible=false`.

---

## Phase D — Full-Fidelity Prompt and Response Logging

### Objective

Persist the complete prompt text and complete raw response for every LLM call in the critical path. No truncation.

### D.1 — Scope

Every LLM call type in the critical path:
- Generation calls (model produces code)
- Classifier calls (evaluator classifies reasoning)
- Retry critique calls (evaluator produces critique for retry)
- Any future LLM call added to the pipeline

### D.2 — Canonical Storage Design

**Per-call artifact files** stored alongside the worker's event log:

```
{worker_dir}/
├── events.jsonl           # event stream (references call artifacts)
├── calls/
│   ├── 000001.json        # full call record: prompt, response, metadata
│   ├── 000002.json
│   └── ...
└── calls_flat/
    ├── 000001_generation.txt    # human-readable prompt+response (optional)
    └── 000002_classification.txt
```

**Call record structure (`calls/NNNNNN.json`):**

```json
{
    "call_id": 1,
    "call_type": "generation",
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

**Event log references calls but does NOT duplicate full text:**

```json
{
    "event_type": "call.generate",
    "llm_call": {
        "call_id": 1,
        "request_path": "calls/000001.json",
        "response_path": "calls/000001.json",
        "flat_path": "calls_flat/000001_generation.txt"
    }
}
```

This design already exists partially in the codebase (the `call_logger.py` module writes to `calls/` and `calls_flat/`). Phase D ensures it is complete, mandatory, and never truncated.

### D.3 — No Truncation Policy

- No truncation in `calls/*.json` (canonical research storage).
- No truncation in `calls_flat/*.txt`.
- Event log `llm_call` section stores metadata and file references, not full text. No truncation concern.
- Dashboard previews or summary fields may truncate for display. These are NOT canonical storage.

### D.4 — Reconstruction Invariant

A run is not research-complete unless, for every LLM call in the critical path, the full prompt text and full raw response are recoverable from the `calls/` directory.

### D.5 — Validation Gate

1. Run 1 case × 1 model × baseline_v2 (generation + classification = 2 LLM calls).
2. Verify: `calls/000001.json` contains full prompt text (not truncated).
3. Verify: `calls/000001.json` contains full response text (not truncated).
4. Verify: `calls/000002.json` (classifier) contains full prompt and response.
5. End-to-end reconstruction test: from a completed run, reconstruct the exact prompt and response for every LLM call by reading `calls/*.json` only.

### PR: PR5

- **Files:** `core/logging_/call_logger.py` (ensure completeness), `core/pipeline/orchestration/execution_v2.py` (call `_persist_call_artifacts`), `core/pipeline/orchestration/retry_v2.py` (same)
- **Behavior change:** Call artifacts now guaranteed complete. May slightly increase disk usage.
- **Rollback:** Revert.
- **Dependencies:** PR2 (critical-path refactor).

---

## Phase E — Classification Unification

### Objective

One canonical classifier entrypoint. One lifecycle. Zero duplication.

### E.1 — Canonical Classifier

Extract to `core/evaluation/evaluator_v2.py`:

```python
def classify_case(
    artifact: NormalizedArtifact,
    case: dict,
    code: str,
    config,
    logger,
    parent_event_id: str | int,
    condition: str,
) -> ClassifierResultV2:
    """Canonical classifier. Called by execution_v2 and retry_v2."""
```

Owns: variable assembly, prompt compilation, model call, output parsing. No other module does any of these.

### E.2 — When Classification Runs

Classification runs whenever the selected artifact is parse-valid, structurally valid, and execution-eligible, **regardless of whether execution later succeeds or fails.**

Rationale: LEG is defined as correct reasoning + failed execution. Classification must run on execution failures to compute LEG.

Classification is skipped only when parse or structural validation fails. `classifier_skipped_reason` is populated with the specific failure.

### E.3 — Lifecycle (Attempt-Level vs Case-Level)

| Context | Classified? | Stored Where |
|---|---|---|
| Baseline execution | Yes (if eligible) | `ev["classification"]` |
| Retry attempt N (not final) | Yes (if eligible) | `ev["trajectory"][N]["classification"]` |
| Retry final attempt | Yes (if eligible) | `ev["classification"]` (case-level) |
| Any attempt: parse/struct fails | No | `ev["classification"]["classifier_skipped_reason"]` |

Case-level classification = the final attempt's classification, copied directly. No rollup or transformation.

If earlier attempts were classifiable but the final attempt is not: case-level classification is `classifier_ran: false` with `classifier_skipped_reason` explaining why the final attempt was not classifiable. Earlier attempt classifications remain in the trajectory.

### E.4 — Classification Event Section

```python
ev["classification"] = {
    "mechanism_identified": str | None,
    "commitments_extracted": str | None,
    "commitments_satisfied": str | None,
    "reasoning_code_alignment": str | None,
    "classifier_ran": bool,
    "classifier_skipped_reason": str | None,
    "commitment_source": str,  # "explicit_valid" | "explicit_low_quality" | "inferred" | "none"
}
```

**Schema:** v7.1 → v7.2 (additive, backward-compatible). Same consumer contract as `reconstruction`.

### E.5 — Validation Gate

1. Run baseline_v2 and retry_leg_critique_strict_v2 on 1 case each.
2. Both produce `classification` with identical structure.
3. `grep -rn "build_classifier_v2_vars" core/pipeline/orchestration/` shows calls to `classify_case()` only.
4. `retry_v2.py` does not contain `build_classifier_v2_vars` or `parse_classifier_v2_output`.

### PR: PR4

- **Files:** `core/evaluation/evaluator_v2.py` (extract), `execution_v2.py` (call), `retry_v2.py` (call), `logging_core.py` (consumed keys)
- **Behavior change:** Classification results move from `extra` to `classification`. Classification runs identically in both paths.
- **Rollback:** Revert.
- **Dependencies:** PR2, PR3a.

---

## Phase F — Invariant/Test Audit (Parallel)

### Objective

Strengthen invariants for the 13 single-test families. Target: ≥30 of 58 cases with ≥3 distinct invariant checks.

### F.1 — Prioritization

Score = `LEG_rate × 0.3 + (1 - pass_rate) × 0.2 + (1 / current_checks) × 0.2 + trap_plausibility × 0.15 + benchmark_centrality × 0.15`

Where:
- `trap_plausibility` ∈ {0, 0.5, 1}: 0 = no known trap fix, 0.5 = one plausible trap, 1 = multiple plausible traps
- `benchmark_centrality` ∈ {0, 0.5, 1}: 0 = peripheral case, 0.5 = standard, 1 = core to paper claims (high-LEG cluster, intervention-responsive)

| Rank | Family | LEG% | Pass% | Checks | Trap | Central | Score | Action |
|---|---|---|---|---|---|---|---|---|
| 1 | invariant_partial_fail | 93 | 6 | 2 | 1.0 | 1.0 | 0.81 | Audit |
| 2 | config_shadowing | 64 | 30 | 3 | 1.0 | 1.0 | 0.65 | Audit |
| 3 | l3_state_pipeline | 62 | 34 | 3 | 0.5 | 1.0 | 0.59 | Audit |
| 4 | feature_flag_drift | 67 | 31 | 5 | 1.0 | 1.0 | 0.57 | Audit |
| 5 | hidden_dep_multihop | 60 | 40 | 4 | 1.0 | 1.0 | 0.54 | Audit |
| 6 | false_fix_deadlock | 77 | 20 | 8 | 0.5 | 0.5 | 0.44 | Audit |
| 7 | lost_update | 57 | 34 | 4 | 0.5 | 0.5 | 0.43 | Audit |
| 8 | overdetermination | 25 | 70 | 1 | 0.5 | 0.5 | 0.42 | Audit |
| 9 | cache_invalidation_order | 52 | 48 | 4 | 0.5 | 0.5 | 0.38 | Audit |
| 10 | check_then_act | 43 | 47 | 5 | 0.5 | 0.5 | 0.33 | Defer |
| 11 | commit_gate | 14 | 86 | 5 | 0.5 | 0.0 | 0.16 | Defer |
| 12 | ordering_dependency | 18 | 81 | 4 | 0.0 | 0.0 | 0.16 | Defer |
| 13 | async_race_lock | 98 | 0 | 4 | 0.5 | 0.5 | 0.56 | Defer (0% pass) |

### F.2 — Per-Family Audit (Top 9)

For each:
- Current assertions (list each check)
- Known/plausible trap fixes (≥1 concrete wrong fix)
- Missing invariant classes (trap-catching, generalization, causal-location)
- Proposed new assertions (concrete descriptions)
- Validation: buggy fails, reference passes, trap-fix fails (for ≥1 trap)

### F.3 — Rules

1. No new invariant without buggy-fails + reference-passes.
2. Trap-fix validation required when a plausible trap fix is identified.
3. No decorative assertions.
4. Each new assertion targets a specific invariant class.

### PR: PR8

- **Files:** 9 test files in `case_data/tests_v2/`
- **Behavior change:** Tests are stricter.
- **Rollback:** Revert test files.
- **Dependencies:** None. Parallel with all other phases.

---

## Phase G — Baseline Commitments, AST Integration, Analysis Migration

### G.1 — Baseline Commitments Contract Migration

**Objective:** Add `code_commitments` to baseline_v2 output schema.

**Commitment Quality State Model:**

| State | Condition | Evaluator Behavior |
|---|---|---|
| `missing` | Field absent from response | Fall back to inferred commitments from `fix_strategy` |
| `explicit_valid` | Present, ≥1 commitment references a concrete code entity with a specific behavioral property | Use explicit commitments |
| `explicit_low_quality` | Present, but all commitments are generic (e.g., "fix the bug") | Record as low-quality; fall back to inferred commitments |
| `explicit_malformed` | Present but not parseable as a list of strings | Record as malformed; fall back to inferred commitments |

**Examples — acceptable:**
- `"create_config must return a copy of DEFAULTS"`
- `"cache invalidation must occur after db write"`
- `"rollback path must restore sender balance on failure"`

**Examples — unacceptable (low quality):**
- `"fix the bug"`
- `"handle correctly"`
- `"ensure proper behavior"`

**Logged in event:** `classification.commitment_source` = one of `explicit_valid`, `explicit_low_quality`, `explicit_malformed`, `inferred`, `none`.

**Backward compatibility:** Old runs have no `code_commitments`. Evaluator infers. No behavior change.

**Validation:** 10 trials × 2 models × 3 cases. Presence ≥80%. Valid quality ≥60%. If presence <50% or quality <40%: revise prompt before shipping.

**Schema:** No new event section. `commitment_source` lives in `classification` (Phase E).

### G.2 — AST Verification Integration

**Objective:** Add deterministic structural verification that runs automatically whenever a case has AST coverage.

**Role:** Non-gating analytical stage. Executes every time a spec exists. Does not block execution. Does not invalidate results.

**AST Status States:**

| Status | Meaning |
|---|---|
| `no_spec` | No AST spec exists for this case. Explicitly recorded. |
| `not_measurable` | Spec exists but code could not be parsed (syntax error) or reconstruction failed. |
| `measured_correct` | Spec exists, code parseable, all required patterns matched. |
| `measured_incorrect` | Spec exists, code parseable, ≥1 required pattern missing. |

Every evaluation emits one of these four states. No silent omission.

**Module:** `core/evaluation/ast_eval.py`

```python
def check_ast_patterns(reconstructed_files: dict[str, str], case_id: str) -> ASTResult:
```

- Loads specs from `paths.AST_SPECS_PATH`.
- Detector registry and spec lookup are separate.
- If no spec: returns `ASTResult(status="no_spec")`.
- If syntax error: returns `ASTResult(status="not_measurable", reason="syntax_error")`.

**Phase 1 scope:** 5 detectors, 15 single-file cases.

**Logged as:** `ev["ast_eval"] = {"status": "...", "ast_correct": bool|None, "ast_score": float|None, ...}`

**Validation:** Reference fixes pass, buggy code fails, for all 15 spec'd cases. FP < 10%, FN < 20%.

### G.3 — Analysis Migration

Update analysis scripts to consume `reconstruction`, `classification`, `ast_eval`. Add fallback for old events.

### PRs

- **PR6:** Baseline commitments (prompt + schema + parser + evaluator)
- **PR7:** AST integration (ast_eval.py + ast_specs.json + pipeline integration)
- **PR9:** Analysis migration (scripts only)

---

## PR Summary

| PR | Phase | Behavior Change | Dependencies | Key Files |
|---|---|---|---|---|
| PR1 | A | No | None | paths.py + 8 modules |
| PR2 | B | No (refactor) | PR1 | execution_v2.py, retry_v2.py |
| PR3a | C (instrumentation) | No | PR2 | execution_v2.py, logging_core.py |
| PR3b | C (flag-off routing) | No | PR3a | execution_v2.py |
| PR3c | C (activate recovery) | YES | PR3b | execution_v2.py (flag flip) |
| PR4 | E | YES (unified classifier) | PR2, PR3a | evaluator_v2.py + orchestration |
| PR5 | D | No (logging completeness) | PR2 | call_logger.py + orchestration |
| PR6 | G.1 | YES (baseline commitments) | PR4 | prompt + schema + evaluator |
| PR7 | G.2 | No (extra field) | PR1, PR3c | ast_eval.py + ast_specs.json |
| PR8 | F | YES (stricter tests) | None (parallel) | 9 test files |
| PR9 | G.3 | No (analysis) | PR3a, PR4, PR7 | scripts/ |

---

## Hidden Assumptions and Failure Modes

| Assumption | What Could Fail | Detection | Contingency |
|---|---|---|---|
| Recovery outputs are often structurally salvageable | Most recovery outputs may be structurally degenerate | `structurally_valid=false` rate in PR3a instrumentation | If >80% of recoveries are structurally invalid, the fallback adds no value. Skip PR3c. |
| Classifier produces useful signal on execution-failed code | Classifier may return noise when code is deeply broken | Monitor classifier dimension agreement with execution outcomes | If agreement drops below existing baseline, restrict to execution-success-only |
| CWD-relative harness paths survive path centralization | `run_case.py` uses CWD paths in temp dirs | Documented exception; smoke test exercises harness | If broken, exclude run_case.py from scope |
| Models produce usable commitments under baseline prompt | Commitments may be generic/empty | Quality rate check (≥60% valid) | If quality <40%, defer migration |
| AST specs achieve acceptable noise | FP/FN may exceed thresholds | Manual review (FP<10%, FN<20%) | Narrow to highest-confidence cases |
| Invariant strengthening targets realistic traps | Traps may not match actual model behavior | Trap-fix validation required per new invariant | If no plausible trap identified, flag as generalization-only |
| Call artifacts directory has sufficient disk | Full prompt/response storage increases disk use | Monitor worker disk usage in controlled bake-in | Compress old runs or increase allocation |

---

## Acceptance Criteria

### Critical Path
- One readable top-level orchestration function exists (≤60 lines)
- It clearly shows 10+ stages in order
- Helper functions have narrow responsibilities

### Paths
- Zero critical-path repo-layout string literals outside `paths.py` and documented exceptions
- Enforcement script active and required for merges
- Preflight catches missing assets before workers launch

### Logging
- Every critical-path LLM call persists full prompt text and full raw response in `calls/*.json`
- No truncation in canonical stored artifacts
- End-to-end reconstruction proven for one complete run

### Parsing/Recovery
- `parse_valid`, `structurally_valid`, `execution_eligible`, `executed` are all distinct and logged
- Recovery routing follows the specified policy (strict preferred, recovery if strict unusable)
- Flag-off path matches strict-only baseline
- No event has `executed=true AND execution_eligible=false`
- Rollback by flag flip works

### Classification
- One canonical classifier entrypoint (`classify_case()`)
- Classification runs on execution failure when eligibility conditions are met
- Per-attempt and case-level storage semantics match the lifecycle table
- No duplicated prompt-building or output-parsing logic

### Commitments
- Presence ≥80%, valid quality ≥60% in new baseline runs
- `commitment_source` explicitly records state (`explicit_valid`, `explicit_low_quality`, `explicit_malformed`, `inferred`, `none`)
- Low-quality/malformed fall back to inferred deterministically
- Old runs analyzable with no behavior change

### AST
- AST runs whenever a case has a spec; `no_spec` explicitly recorded otherwise
- `not_measurable` explicitly recorded when code cannot be parsed
- Spec loading uses `paths.AST_SPECS_PATH`
- Phase-1 reference/buggy validation passes (15 cases)

### Invariants
- ≥30 of 58 cases have ≥3 invariant checks
- Prioritization follows the scoring rubric
- Each new assertion validated against buggy/reference/trap-fix

### Backward Compatibility
- Old events readable by all analysis scripts without errors
- Missing `reconstruction`, `classification`, `ast_eval` handled with explicit fallback
- No analysis script crashes on pre-refactor data

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
| run_case.py:41,50,158 | CWD-relative | NO | Leave (documented exception) | — |
