# Pipeline Refactor Plan v2

**Date:** 2026-04-03
**Status:** PLAN — awaiting approval
**Supersedes:** pipeline_refactor_plan_v1.md

---

## Structure

This plan is organized into seven sequential phases with explicit dependency boundaries. Each phase is a shippable unit with its own validation gate. No phase may begin until its predecessor's validation gate passes.

- **Phase A** — Path centralization and dependency cleanup
- **Phase B** — Parsing/reconstruction pipeline cleanup
- **Phase C** — Classification pipeline unification
- **Phase D** — Prompt/schema contract changes (baseline commitments)
- **Phase E** — AST verification integration
- **Phase F** — Invariant/test audit
- **Phase G** — Analysis and backward-compat migration

---

## Non-Goals / Explicitly Rejected Approaches

- Scattering path constants across multiple modules. One module owns all canonical paths.
- Replacing hardcoded paths with env vars only. Env vars are an override mechanism, not the primary definition.
- Adding a parallel schema reader. One event schema, one reader contract.
- Duplicating classifier logic in retry and execution. One canonical classifier entrypoint.
- Introducing silent fallback behavior without explicit event fields. Every fallback must be observable.
- Burying migration complexity under "analysis can handle it." Analysis code gets explicit migration in Phase G.
- Mixing architecture cleanup with behavior changes in the same PR unless the behavioral change is mechanically coupled to the architectural change.

---

## Phase A — Path Centralization and Dependency Cleanup

### Objective

Eliminate all hardcoded filesystem paths from the critical execution path. Establish a single authoritative path module that all pipeline code imports from.

### Design: `core/config/paths.py`

This file already exists and defines `PROJECT_ROOT`. Expand it to be the single source of truth for all repo-relative paths:

```python
from pathlib import Path

# ── Repo root (computed once) ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Static repo locations ──
CASE_DATA_DIR     = PROJECT_ROOT / "case_data"
CASES_V2_PATH     = CASE_DATA_DIR / "cases_v2.json"
TESTS_V2_DIR      = CASE_DATA_DIR / "tests_v2"
CODE_SNIPPETS_DIR = CASE_DATA_DIR / "code_snippets_v2"
REFERENCE_FIXES_DIR = CASE_DATA_DIR / "reference_fixes"
AST_SPECS_PATH    = CASE_DATA_DIR / "ast_specs.json"
VALIDATION_DIR    = CASE_DATA_DIR / "validation"

PROMPTS_DIR       = PROJECT_ROOT / "core" / "prompts"
COMPONENTS_DIR    = PROMPTS_DIR / "components"
PROMPT_MANIFEST   = PROMPTS_DIR / "prompt_manifest.yaml"
COMPONENT_META    = PROMPTS_DIR / "component_metadata.yaml"

HARNESS_SCRIPT    = PROJECT_ROOT / "core" / "harness" / "run_case.py"

LOGS_DIR          = PROJECT_ROOT / "logs"

# ── Runtime output locations (overridable) ──
def get_run_dir(run_dir_str: str) -> Path:
    """Resolve a run directory. If relative, resolve against PROJECT_ROOT."""
    p = Path(run_dir_str)
    return p if p.is_absolute() else PROJECT_ROOT / p

# ── Output filenames (canonical, not paths) ──
MANIFEST_FILENAME       = "manifest.json"
EVENTS_FILENAME         = "events.jsonl"
MERGED_EVENTS_FILENAME  = "merged_events.jsonl"
CONFIG_SNAPSHOT_FILENAME = "config.snapshot.yaml"
LOCK_FILENAME           = "orchestrator.lock"
HEARTBEAT_FILENAME      = "heartbeat.json"
```

### Rules (Enforced from this phase forward)

1. No new hardcoded relative paths in production code under `core/`.
2. No string-literal path concatenation in execution-critical modules. Use `pathlib.Path` operators.
3. No module in the critical path may reference repo layout except through `core/config/paths.py`.
4. Analysis scripts under `scripts/` may use hardcoded paths temporarily; migration deferred to Phase G.
5. Tests must fail if required canonical paths are missing at startup (preflight check).

### Migration Strategy

1. Replace each hardcoded path with the corresponding `paths.py` constant.
2. For the prompt registry in `execution_v2.py` and `retry_v2.py`: replace inline `Path("core/prompts/...")` with `COMPONENTS_DIR`, `COMPONENT_META`, `PROMPT_MANIFEST`.
3. For `exec_canonical.py` line 109: replace `Path(project_root) / "core" / "harness" / "run_case.py"` with `HARNESS_SCRIPT`.
4. For `test_loader.py` line 64: replace `_PROJECT_ROOT / "case_data" / "tests_v2"` with `TESTS_V2_DIR`.
5. For `validate_cases_v2.py` line 53: replace `BASE / "tests_v2"` with `TESTS_V2_DIR`.
6. For `run_case.py` lines 41, 50, 158: these run inside a temp directory and are CWD-relative by design. Document this as an exception. Do not migrate.
7. Output filenames (manifest.json, events.jsonl, etc.) in `orchestrate.py`: replace string literals with `paths.MANIFEST_FILENAME` etc. These are filename constants, not full paths — the directory part comes from config.

### Validation Gate

- `grep -rn '"core/' core/pipeline/ core/evaluation/ core/config/experiment_config.py` returns zero matches (excluding paths.py itself and comments)
- `grep -rn '"case_data/' core/pipeline/ core/evaluation/` returns zero matches
- `grep -rn '"tests_v2' core/pipeline/` returns zero matches
- Pipeline smoke test passes: one case, one model, one condition, full execution
- Renaming `case_data/tests_v2/` to `case_data/tests_v2_RENAMED/` and updating `TESTS_V2_DIR` in `paths.py` causes all test loads to use the new directory (proof that centralization works)

### PR: PR1

- **Files touched:** `core/config/paths.py`, `core/pipeline/orchestration/execution_v2.py`, `core/pipeline/orchestration/retry_v2.py`, `core/pipeline/execution/exec_canonical.py`, `core/pipeline/execution/test_loader.py`, `core/pipeline/orchestration/validate_cases_v2.py`, `core/pipeline/orchestration/orchestrate.py`
- **Behavior change:** None. Paths resolve to identical locations.
- **Rollback:** Revert single PR. No data migration.
- **Blocking dependencies:** None.
- **Required tests:** grep audit + smoke test.

---

## Phase B — Parsing/Reconstruction Pipeline Cleanup

### Objective

Make the lenient parsing fallback a first-class execution path. Promote reconstruction/parsing metadata from buried `extra` dicts to a dedicated event section. Eliminate post-hoc reanalysis for recoverable outputs.

### B.1 — Lenient Parsing Fallback

In `execution_v2.py` STAGE 3, replace:

```python
parsed_gen = parse_exec  # ONLY execution enters pipeline
```

With:

```python
if parse_exec.parse_valid:
    parsed_gen = parse_exec
    parsing_mode = "strict"
elif parse_rec.parse_valid:
    parsed_gen = parse_rec
    parsing_mode = "recovery"
else:
    parsed_gen = parse_exec  # failed — keep for error reporting
    parsing_mode = "failed"
```

### Parsing Mode Decision Matrix

| Strict | Recovery | Action | `parsing_mode` | `recovery_used` |
|---|---|---|---|---|
| valid | valid, equivalent | Use strict | `strict` | `false` |
| valid | valid, different | Use strict; flag divergence | `strict` | `false` |
| valid | invalid | Use strict | `strict` | `false` |
| invalid | valid | Use recovery | `recovery` | `true` |
| invalid | invalid | Mark failed | `failed` | `false` |
| valid | not run | Use strict | `strict` | `false` |

When strict succeeds and recovery also succeeds but produces different code: log `strict_recovery_divergent: true`. Use strict for execution. The divergence is a diagnostic signal, not an error.

When recovery is used: all downstream stages (normalize, reconstruct, execute, classify) operate on the recovery output. The event records `recovery_used: true`.

### B.2 — First-Class Reconstruction Section

Add a `reconstruction` section to the event, alongside `execution`, `reasoning`, and (new in Phase C) `classification`:

```python
ev["reconstruction"] = {
    "parsing_mode": "strict" | "recovery" | "failed",
    "strict_valid": bool,
    "recovery_valid": bool,
    "recovery_used": bool,
    "execution_equivalent": bool,
    "strict_recovery_divergent": bool,
    "recon_status": str,            # SUCCESS | RECON_MISSING_FILES | ...
    "files_changed": list[str],
    "files_total": int,
}
```

### Schema Versioning

This is a **backward-compatible extension** (new section, no existing fields removed or renamed). Classify as **schema minor version bump: v7 → v7.1**.

Downstream reader contract:
- Readers MUST tolerate missing `reconstruction` section (old events).
- Readers MUST NOT assume `reconstruction` is present without checking.
- Fallback: `event.get("reconstruction") or {}`.
- Compatibility window: indefinite. Old events will never be backfilled.

### Validation Gate

- Run 10 trials × 2 models × 1 condition on 3 cases.
- Verify: events with `parsing_mode=strict` have identical execution results to pre-refactor.
- Verify: at least 1 event has `parsing_mode=recovery` (pick a model/case known to produce recovery-only parses).
- Verify: `reconstruction` section present in all new events.
- Verify: old event reader code still works (doesn't crash on missing `reconstruction`).

### PR: PR2 (reconstruction fields) + PR3 (recovery fallback activation)

PR2 is structure-only (adds fields, no behavior change). PR3 activates the fallback.

- **PR2 files:** `core/pipeline/orchestration/execution_v2.py` (field population), `core/logging_/logging_core.py` (consumed keys update)
- **PR2 behavior change:** No. Fields populated but fallback not yet active.
- **PR3 files:** `core/pipeline/orchestration/execution_v2.py` (STAGE 3 logic change)
- **PR3 behavior change:** Yes. Recoverable outputs now execute.
- **Rollback:** PR3 revert restores strict-only behavior. PR2 revert removes fields (harmless).
- **Blocking dependencies:** PR1 (paths cleanup).

---

## Phase C — Classification Pipeline Unification

### Objective

One canonical classifier entrypoint. Zero duplicated prompt-building logic between execution_v2.py and retry_v2.py.

### Design

Extract from `core/evaluation/evaluator_v2.py`:

```python
def classify_case(
    artifact: NormalizedArtifact,
    case: dict,
    code: str,
    config,
    logger,
    parent_event_id,
    condition: str,
) -> ClassifierResultV2:
    """Canonical classifier. Called by execution_v2 and retry_v2."""
```

This function:
1. Calls `build_classifier_v2_vars()` to build prompt variables
2. Compiles the `classify_reasoning_v2` prompt
3. Calls the evaluator model
4. Parses the output via `parse_classifier_v2_output()`
5. Returns `ClassifierResultV2`

Both `execution_v2.py` STAGE 6 and `retry_v2.py`'s final-attempt classification call this function. No duplicated prompt building.

### Retry Classification Contract

- Per-attempt classification: runs after each retry attempt. Uses the same `classify_case()` function.
- Final-attempt classification: the last attempt's classification is the case-level classification.
- No separate "final classification" step — the last call to `classify_case()` IS the final classification.

### New Event Section

```python
ev["classification"] = {
    "mechanism_identified": str | None,
    "commitments_extracted": str | None,
    "commitments_satisfied": str | None,
    "reasoning_code_alignment": str | None,
    "classifier_ran": bool,
    "classifier_skipped_reason": str | None,
    "commitment_source": str,       # "explicit" | "inferred" | "none"
}
```

Schema: **v7.1 → v7.2** (additive, backward-compatible).

### Validation Gate

- Run one baseline_v2 case and one retry_leg_critique_strict_v2 case.
- Verify: both produce identical `classification` section structure.
- Verify: `evaluator_v2.py` no longer contains prompt compilation logic (moved to `classify_case()`).
- Verify: `retry_v2.py` imports and calls `classify_case()`, does not build classifier prompts inline.

### PR: PR4

- **Files:** `core/evaluation/evaluator_v2.py` (extract function), `core/pipeline/orchestration/execution_v2.py` (call extracted function), `core/pipeline/orchestration/retry_v2.py` (call extracted function), `core/logging_/logging_core.py` (add `classification` to consumed keys)
- **Behavior change:** Classification results move from `extra` to `classification` section. Classification now runs identically in both paths.
- **Rollback:** Revert PR. Old inline classification code restored.
- **Blocking dependencies:** PR1, PR3 (recovery fallback).

---

## Phase D — Baseline Commitments Contract Migration

### Objective

Add `code_commitments` to the baseline_v2 generation prompt output schema. Eliminate evaluator guessing.

### This Is a Contract Migration

Affected contracts:
1. `core/prompts/components/output_instruction_v3.j2` — prompt template
2. `core/contracts/contracts_v2.py` — schema definition for baseline_v2
3. `core/pipeline/orchestration/execution_v2.py` — schema_line construction
4. `core/evaluation/evaluator_v2.py` — commitment extraction logic
5. `core/pipeline/parsing/parser_v2.py` — schema validation for baseline_v2

### Rollout Order

1. Update `output_instruction_v3.j2` to request `code_commitments`.
2. Update `contracts_v2.py` baseline_v2 schema to include `code_commitments` as optional field.
3. Update `execution_v2.py` schema_line to include `code_commitments`.
4. Update `parser_v2.py` to accept `code_commitments` in baseline_v2 output (optional, not required for parse success).
5. Update `evaluator_v2.py`: if `code_commitments` present, use them. If absent, fall back to inference from `fix_strategy` (backward compat for old data).

### Backward Compatibility

- Old baseline runs: no `code_commitments` field. Evaluator falls back to inference. Behavior unchanged.
- New baseline runs: `code_commitments` field present. Evaluator uses explicit commitments.
- Cross-era comparisons: valid with caveat. Old runs have inferred commitments (noisier), new runs have explicit commitments (cleaner). Analysis must note the era boundary.
- Comparisons within era: fully valid.

### Validation

- Run 5 trials × 2 models on 3 baseline_v2 cases.
- Verify: models produce `code_commitments` in ≥80% of responses.
- Verify: evaluator uses explicit commitments when present.
- Verify: evaluator falls back to inference when `code_commitments` is absent (test with a manually constructed response missing the field).
- If models produce commitments <50% of the time: the prompt change is insufficient. Revise before shipping.

### PR: PR5

- **Files:** `core/prompts/components/output_instruction_v3.j2`, `core/contracts/contracts_v2.py`, `core/pipeline/orchestration/execution_v2.py`, `core/pipeline/parsing/parser_v2.py`, `core/evaluation/evaluator_v2.py`
- **Behavior change:** Yes. New generation outputs include commitments. Evaluator behavior changes for new runs.
- **Rollback:** Revert prompt template change. New runs revert to old behavior. Old data unaffected.
- **Blocking dependencies:** PR4 (classifier unification, so commitment handling is in one place).

---

## Phase E — AST Verification Integration

### Objective

Add deterministic structural verification of generated code as a pipeline stage.

### Architectural Decision: AST Is Best-Effort Analysis Metadata

AST evaluation is NOT part of the canonical event contract (not in `execution` or `classification`). It lives in the `extra` section as enrichment metadata. Rationale:
- AST specs don't exist for all cases (coverage is partial).
- False negatives are expected for novel correct fixes.
- It is an analytical signal, not a pipeline gate.

If AST measurement proves highly reliable after Phase E, it can be promoted to a first-class section in a future schema bump.

### Design

Create `core/evaluation/ast_eval.py`:

```python
def check_ast_patterns(
    reconstructed_files: dict[str, str],
    case_id: str,
) -> ASTResult:
```

- Loads specs from `paths.AST_SPECS_PATH` (centralized, per Phase A).
- Returns `ASTResult(measurable, ast_correct, ast_score, patterns_matched, patterns_missing)`.
- If no spec exists for the case: returns `ASTResult(measurable=False, reason="no_spec")`.
- If code has syntax errors: returns `ASTResult(measurable=False, reason="syntax_error")`.

### Detector Registration

Detectors are registered in `ast_eval.py` as a dict:

```python
DETECTORS = {
    "copy_call_on_assignment": _detect_copy_call,
    "cache_invalidation_call": _detect_cache_invalidation,
    "none_guard_for_default": _detect_none_guard,
    "statement_in_loop": _detect_statement_in_loop,
    "break_after_success": _detect_break_after,
}
```

Spec lookup and detector dispatch are cleanly separated. Adding a detector does not require modifying spec loading.

### Phase 1 Scope

- 5 detectors (listed above).
- Specs for ~15 single-file cases (alias_config, stale_cache, mutable_default, effect_order, retry_dup families).
- Measurable false-negative risk: alternative correct fixes (e.g., `dict(DEFAULTS)` vs `.copy()`) not in initial spec. Mitigated by `alternative_patterns` in specs. Expected FN rate: ~10% based on model output diversity.
- Measurable false-positive risk: pattern present in wrong function. Mitigated by function-scoping in specs. Expected FP rate: <5%.

### Integration Point

In `execution_v2.py`, after STAGE 5 (execute) and before STAGE 8 (derive metrics):

```python
# STAGE 7: AST Verify
from core.evaluation.ast_eval import check_ast_patterns
ast_result = check_ast_patterns(recon.files if recon.status == "SUCCESS" else {}, case["id"])
ev["ast_eval"] = ast_result.to_dict()
```

### Validation Gate

- Automated: reference fix passes AST check for all spec'd cases. Buggy code fails.
- Manual: hand-review 10 model outputs per case (5 AST-correct, 5 AST-incorrect). Compute FP/FN rates.
- If FP > 10% or FN > 20%: revise specs before shipping.

### PR: PR6

- **Files:** NEW `core/evaluation/ast_eval.py`, NEW `case_data/ast_specs.json`, `core/pipeline/orchestration/execution_v2.py` (add STAGE 7), `core/pipeline/orchestration/retry_v2.py` (add AST after final attempt)
- **Behavior change:** New `ast_eval` field in event `extra`. No execution behavior change.
- **Rollback:** Revert PR. Events stop containing `ast_eval`. No data corruption.
- **Blocking dependencies:** PR1 (paths), PR3 (recovery fallback, so AST runs on recovered code too).

---

## Phase F — Invariant/Test Audit

### Objective

Strengthen test invariants for the 13 single-test families. Target: ≥30 of 58 cases have ≥3 distinct invariant checks.

### Audit Table

| Family | Cases | Current Checks | LEG Rate | Missing Invariants | Priority |
|---|---|---|---|---|---|
| overdetermination | 1 | 1 | 25% | trap-catching, generalization, causal-location | HIGH |
| invariant_partial_fail | 1 | 2 | 93% | generalization, causal-location | HIGH |
| config_shadowing | 1 | 3 | 64% | trap-catching, generalization | HIGH |
| l3_state_pipeline | 1 | 3 | 62% | generalization | HIGH |
| hidden_dep_multihop | 1 | 4 | 60% | generalization | MEDIUM |
| lost_update | 1 | 4 | 57% | generalization | MEDIUM |
| cache_invalidation_order | 1 | 4 | 52% | generalization | MEDIUM |
| check_then_act | 1 | 5 | 43% | causal-location | MEDIUM |
| feature_flag_drift | 1 | 5 | 67% | causal-location | MEDIUM |
| commit_gate | 1 | 5 | 14% | generalization | LOW |
| false_fix_deadlock | 1 | 8 | 77% | (audit for gaps) | LOW |
| async_race_lock | 1 | 4 | 98% | (special: 0% pass, may need redesign) | DEFER |
| ordering_dependency | 1 | 4 | 18% | generalization | LOW |

### Rules for New Invariants

No new invariant may be added unless it demonstrably:
1. Fails on the buggy code
2. Passes on the reference fix
3. Fails on at least one plausible trap fix (when applicable — trap fixes must be identified during audit)

Validation command per family:
```bash
.venv/bin/python scripts/test_case.py <case_id>         # buggy fails
.venv/bin/python scripts/test_case.py <case_id> --ref    # reference passes
```

### Proposed New Assertions (First Batch — HIGH Priority)

**overdetermination:** Currently 1 check. Add: (1) second input configuration with different product mix, (2) verify both write paths produce consistent state.

**invariant_partial_fail:** Currently 2 checks. Add: (1) verify sender balance is restored on failure (generalization with different failure point), (2) verify ledger records are consistent with final balances (causal-location).

**config_shadowing:** Currently 3 checks. Add: (1) verify background job path reads correct config (trap-catching for different code path), (2) second config value test (generalization).

**l3_state_pipeline:** Currently 3 checks. Add: (1) verify incremental pipeline produces same result as batch (generalization).

### PR: PR7

- **Files:** `case_data/tests_v2/test_overdetermination.py`, `test_invariant_partial_fail.py`, `test_config_shadowing.py`, `test_l3_state_pipeline.py`, `test_hidden_dep_multihop.py`, `test_lost_update.py`, `test_cache_invalidation_order.py`
- **Behavior change:** Tests are stricter. Cases that previously passed with partial fixes may now fail.
- **Rollback:** Revert test changes. Old test behavior restored.
- **Blocking dependencies:** None. Can run in parallel with Phases A-E.
- **Required validation:** Each new assertion verified against buggy/reference/trap-fix.

---

## Phase G — Analysis and Backward-Compat Migration

### Objective

Update analysis scripts to consume the new event structure. Migrate remaining hardcoded paths in non-critical scripts.

### Tasks

1. Update `scripts/global_cal_analysis.py`, `scripts/per_case_analysis.py`, `scripts/per_triple_analysis.py` to read from `event.reconstruction` and `event.classification` when present.
2. Add fallback logic: if `reconstruction` section missing, fall back to `event.extra.v2_parse_tiers`.
3. Migrate path references in analysis scripts from inline strings to `core.config.paths` imports.
4. Add `parsing_mode` as a first-class analysis dimension (filter by strict/recovery/failed).
5. Add `ast_correct` as an analysis dimension where available.

### PR: PR8

- **Files:** `scripts/*.py` (analysis scripts only)
- **Behavior change:** Analysis uses new event fields when present. Falls back gracefully.
- **Rollback:** Revert script changes. Old analysis behavior restored.
- **Blocking dependencies:** PR2, PR4, PR6 (needs the new event sections to exist).

---

## PR Summary

| PR | Phase | Behavior Change | Files | Dependencies | Rollback |
|---|---|---|---|---|---|
| PR1 | A | No | 7 core modules | None | Revert |
| PR2 | B.2 | No (fields only) | 2 modules | PR1 | Revert |
| PR3 | B.1 | Yes (recovery fallback) | 1 module | PR1, PR2 | Revert |
| PR4 | C | Yes (unified classifier) | 4 modules | PR1, PR3 | Revert |
| PR5 | D | Yes (baseline commitments) | 5 files | PR4 | Revert prompt |
| PR6 | E | No (extra field only) | 4 files | PR1, PR3 | Revert |
| PR7 | F | Yes (stricter tests) | 7 test files | None | Revert tests |
| PR8 | G | No (analysis only) | ~5 scripts | PR2, PR4, PR6 | Revert scripts |

---

## Acceptance Criteria

1. **Path centralization:** `grep -rn '"core/' core/pipeline/ core/evaluation/` returns zero matches outside `paths.py`. Changing one path in `paths.py` reroutes all dependent loads.
2. **Parsing observability:** every new event contains `reconstruction.parsing_mode` ∈ {strict, recovery, failed}. Recovery-parsed outputs are executed and scored.
3. **Classifier unification:** `execution_v2.py` and `retry_v2.py` both call `classify_case()` from `evaluator_v2.py`. No duplicated prompt-building logic exists.
4. **Baseline commitments:** new baseline runs emit `code_commitments`. Evaluator uses explicit commitments when present, falls back to inference for old data.
5. **AST integration:** `ast_eval` field present in events for spec'd cases. Spec loading uses `paths.AST_SPECS_PATH`. Reference fixes pass, buggy code fails, for all spec'd cases.
6. **Invariant strength:** ≥30 of 58 cases have ≥3 distinct invariant checks. All new assertions validated against buggy/reference.
7. **Backward compat:** old events (pre-refactor) still readable by all analysis scripts without errors.

---

## Appendix: Hardcoded Path Inventory

| Location | Hardcoded String | Module | Critical Path? | Replacement | PR |
|---|---|---|---|---|---|
| execution_v2.py:38 | `Path("core/prompts/components")` | orchestration | YES | `paths.COMPONENTS_DIR` | PR1 |
| execution_v2.py:39 | `Path("core/prompts/component_metadata.yaml")` | orchestration | YES | `paths.COMPONENT_META` | PR1 |
| execution_v2.py:40 | `Path("core/prompts/prompt_manifest.yaml")` | orchestration | YES | `paths.PROMPT_MANIFEST` | PR1 |
| retry_v2.py:46 | `Path("core/prompts/components")` | orchestration | YES | `paths.COMPONENTS_DIR` | PR1 |
| retry_v2.py:47 | `Path("core/prompts/component_metadata.yaml")` | orchestration | YES | `paths.COMPONENT_META` | PR1 |
| retry_v2.py:48 | `Path("core/prompts/prompt_manifest.yaml")` | orchestration | YES | `paths.PROMPT_MANIFEST` | PR1 |
| exec_canonical.py:109 | `Path(project_root) / "core" / "harness" / "run_case.py"` | execution | YES | `paths.HARNESS_SCRIPT` | PR1 |
| test_loader.py:64 | `_PROJECT_ROOT / "case_data" / "tests_v2"` | execution | YES | `paths.TESTS_V2_DIR` | PR1 |
| validate_cases_v2.py:53 | `BASE / "tests_v2"` | validation | YES | `paths.TESTS_V2_DIR` | PR1 |
| orchestrate.py:377,432,441 | `"orchestrator.lock"` | orchestration | YES | `paths.LOCK_FILENAME` | PR1 |
| orchestrate.py:737 | `"merged_events.jsonl"` | orchestration | YES | `paths.MERGED_EVENTS_FILENAME` | PR1 |
| orchestrate.py:979+ | `"manifest.json"` | orchestration | YES | `paths.MANIFEST_FILENAME` | PR1 |
| orchestrate.py:1076 | `"config.snapshot.yaml"` | orchestration | YES | `paths.CONFIG_SNAPSHOT_FILENAME` | PR1 |
| orchestrate.py:888 | `"trial_config.yaml"` | orchestration | YES | constant in paths.py | PR1 |
| orchestrate.py:892 | `"stdout.log"` | orchestration | NO (worker) | constant in paths.py | PR1 |
| orchestrate.py:893 | `"stderr.log"` | orchestration | NO (worker) | constant in paths.py | PR1 |
| orchestrate.py:573+ | `"events.jsonl"` | orchestration | YES | `paths.EVENTS_FILENAME` | PR1 |
| orchestrate.py:781 | `"heartbeat.json"` | orchestration | NO | `paths.HEARTBEAT_FILENAME` | PR1 |
| orchestrate.py:805 | `f"/proc/{pid}/cmdline"` | orchestration | NO (Linux) | Leave as-is (system path) | — |
| run_case.py:41 | `"case_meta.json"` | harness | NO (CWD) | Leave as-is (runs in temp dir) | — |
| run_case.py:50 | `"pkg"` | harness | NO (CWD) | Leave as-is | — |
| run_case.py:158 | `"tests_v2.test_{family}"` | harness | NO (module import) | Leave as-is (import path) | — |
| runner.py:240 | `"heartbeat.json"` | orchestration | NO | `paths.HEARTBEAT_FILENAME` | PR1 |
