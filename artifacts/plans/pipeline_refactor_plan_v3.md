# Pipeline Refactor Plan v3

**Date:** 2026-04-03
**Status:** PLAN — awaiting approval
**Supersedes:** pipeline_refactor_plan_v2.md

---

## Structure

Seven phases. Each is a shippable unit with a validation gate. Phases are split into PRs that isolate behavior changes from structural changes. No phase may begin until its predecessor's gate passes, except Phase F (invariant audit) which has no upstream dependency.

- **Phase A** — Path centralization, enforcement, and preflight
- **Phase B** — Parsing/reconstruction pipeline cleanup
- **Phase C** — Classification pipeline unification
- **Phase D** — Baseline commitments contract migration
- **Phase E** — AST verification integration
- **Phase F** — Invariant/test audit
- **Phase G** — Analysis and backward-compat migration

---

## Non-Goals / Explicitly Rejected Approaches

- Scattering path constants across multiple modules. One module owns all canonical paths.
- Replacing hardcoded paths with env vars only. Env vars are override mechanisms, not primary definitions.
- Adding a parallel schema reader. One event schema, one reader contract.
- Duplicating classifier logic. One canonical classifier entrypoint. "Temporary" duplication is prohibited unless a scheduled same-phase removal step exists.
- Introducing silent fallback behavior without explicit event fields. Every fallback is observable.
- Burying migration complexity under "analysis can handle it." Analysis gets explicit migration.
- Mixing architecture cleanup with behavior changes in the same PR unless mechanically coupled.
- Judging path centralization complete because a constants file exists. Enforcement must be active.
- Judging commitments rollout successful because the field appears. Quality/specificity rate must meet thresholds.
- Judging recovery fallback successful because parse-valid counts rise. Structural validation must gate execution eligibility.
- Judging AST rollout successful because fields are populated. FP/FN rates must be within bounds.
- Judging test strengthening successful because assertion count increases. Each assertion must be validated against buggy/reference/trap-fix.

---

## Phase A — Path Centralization, Enforcement, and Preflight

### Objective

Eliminate all hardcoded filesystem paths from the critical execution path. Establish enforcement that prevents regressions. Add preflight validation that catches missing canonical assets early.

### A.1 — Central Path Module: `core/config/paths.py`

This file already defines `PROJECT_ROOT`. Expand it to be the single authority for all repo-relative paths.

#### Path Categories

**Category 1: Canonical Static Paths (repo layout)**

These are derived from `PROJECT_ROOT` and represent fixed repo structure:

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
VALIDATION_DIR      = CASE_DATA_DIR / "validation"

# Prompts
PROMPTS_DIR         = PROJECT_ROOT / "core" / "prompts"
COMPONENTS_DIR      = PROMPTS_DIR / "components"
PROMPT_MANIFEST     = PROMPTS_DIR / "prompt_manifest.yaml"
COMPONENT_META      = PROMPTS_DIR / "component_metadata.yaml"

# Harness
HARNESS_SCRIPT      = PROJECT_ROOT / "core" / "harness" / "run_case.py"

# Default logs root
DEFAULT_LOGS_DIR    = PROJECT_ROOT / "logs"
```

No module outside `paths.py` may construct these paths from string literals.

**Category 2: Canonical Derived Paths (intent-based helpers)**

These accept typed arguments and return validated `Path` objects:

```python
def resolve_run_dir(run_dir_config: str) -> Path:
    """Resolve a run directory from config. Validates existence of parent."""
    p = Path(run_dir_config)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    p = p.resolve()
    if not p.parent.exists():
        raise FileNotFoundError(f"Run directory parent does not exist: {p.parent}")
    return p

def resolve_test_module(family: str) -> Path:
    """Resolve test file path for a case family."""
    path = TESTS_V2_DIR / f"test_{family}.py"
    if not path.exists():
        raise FileNotFoundError(f"Test file not found: {path}")
    return path

def resolve_case_dir(case_id: str) -> Path:
    """Resolve code snippet directory for a case."""
    return CODE_SNIPPETS_DIR / case_id
```

**Category 3: Canonical Output Filenames (constants, not paths)**

```python
MANIFEST_FILENAME       = "manifest.json"
EVENTS_FILENAME         = "events.jsonl"
MERGED_EVENTS_FILENAME  = "merged_events.jsonl"
CONFIG_SNAPSHOT_FILENAME = "config.snapshot.yaml"
LOCK_FILENAME           = "orchestrator.lock"
HEARTBEAT_FILENAME      = "heartbeat.json"
TRIAL_CONFIG_FILENAME   = "trial_config.yaml"
STDOUT_LOG_FILENAME     = "stdout.log"
STDERR_LOG_FILENAME     = "stderr.log"
```

**Category 4: Config-Supplied Override Roots**

Only `resolve_run_dir()` accepts arbitrary paths (from experiment config). All other user-supplied paths are prohibited in critical-path code.

Override roots are validated:
- Must resolve to an absolute path
- Parent directory must exist
- Must not escape PROJECT_ROOT unless explicitly absolute
- Normalized via `.resolve()` before use

### A.2 — Forbidden Pattern Enforcement

#### Enforcement Script: `scripts/check_forbidden_paths.py`

A standalone script that:
1. Scans all `.py` files under `core/` (excluding `core/config/paths.py` and test files)
2. Detects forbidden string literals:
   - `"core/"` as a path component
   - `"case_data/"` as a path component
   - `"tests_v2"` as a path fragment (excluding module import strings like `"tests_v2.test_"`)
   - `"code_snippets"` as a path fragment
   - `"prompts/"` or `"components/"` as a path fragment (in Path constructors)
   - `"reference_fixes"` as a path fragment
   - `"ast_specs"` as a path fragment
3. Exits non-zero if any forbidden pattern found
4. Reports file, line number, and matched string for each violation

#### Allowed Exceptions (documented in the script)

- `core/config/paths.py` itself (defines the canonical paths)
- `core/harness/run_case.py` (runs in CWD-relative temp directory by design; uses `"case_meta.json"`, `"pkg"`, and `"tests_v2.test_{family}"` as module imports)
- `f"/proc/{pid}/cmdline"` in `orchestrate.py` (system path, not repo layout)
- String literals in comments and docstrings

#### Integration

- Run as a pre-commit hook or mandatory CI check
- Run before every PR merge that touches `core/`
- Run as part of the Phase A validation gate

#### Regression Prevention Rule

No future PR may introduce new critical-path repo-layout string literals outside `core/config/paths.py` and the documented exceptions. The enforcement script blocks this.

### A.3 — Preflight Validation

Add `core/config/preflight.py`:

```python
def validate_repo_structure() -> list[str]:
    """Check that all canonical paths exist. Returns list of errors."""
    errors = []
    for name, path in [
        ("CASE_DATA_DIR", CASE_DATA_DIR),
        ("CASES_V2_PATH", CASES_V2_PATH),
        ("TESTS_V2_DIR", TESTS_V2_DIR),
        ("COMPONENTS_DIR", COMPONENTS_DIR),
        ("PROMPT_MANIFEST", PROMPT_MANIFEST),
        ("HARNESS_SCRIPT", HARNESS_SCRIPT),
    ]:
        if not path.exists():
            errors.append(f"{name} not found: {path}")
    return errors
```

Called at:
- Runner startup (before any case execution)
- Orchestrator startup (before spawning workers)
- Test suite initialization

Failures are loud and immediate: `RuntimeError` with the missing path list.

### A.4 — Migration

| Location | Current | Replacement | PR |
|---|---|---|---|
| execution_v2.py:38-40 | `Path("core/prompts/...")` × 3 | `paths.COMPONENTS_DIR`, `paths.COMPONENT_META`, `paths.PROMPT_MANIFEST` | PR1 |
| retry_v2.py:46-48 | Same as above | Same replacements | PR1 |
| exec_canonical.py:109 | `Path(project_root) / "core" / "harness" / "run_case.py"` | `paths.HARNESS_SCRIPT` | PR1 |
| test_loader.py:64 | `_PROJECT_ROOT / "case_data" / "tests_v2"` | `paths.TESTS_V2_DIR` | PR1 |
| validate_cases_v2.py:53 | `BASE / "tests_v2"` | `paths.TESTS_V2_DIR` | PR1 |
| orchestrate.py (multiple) | `"manifest.json"`, `"events.jsonl"`, etc. | `paths.MANIFEST_FILENAME`, etc. | PR1 |
| runner.py:240 | `"heartbeat.json"` | `paths.HEARTBEAT_FILENAME` | PR1 |
| run_case.py:41,50,158 | CWD-relative | Leave as-is (documented exception) | — |
| orchestrate.py:805 | `/proc/{pid}/cmdline` | Leave as-is (system path) | — |

### A.5 — Validation Gate

1. `scripts/check_forbidden_paths.py` exits 0 (zero violations in `core/`)
2. `core/config/preflight.validate_repo_structure()` returns empty list
3. Pipeline smoke test: 1 case × 1 model × baseline_v2, full execution, passes
4. Rename proof: temporarily rename `case_data/tests_v2/` → `case_data/tests_v2_TMP/`, update `TESTS_V2_DIR` in `paths.py`, verify pipeline loads tests from renamed directory, then revert

### PR: PR1

- **Files:** `core/config/paths.py` (expand), NEW `core/config/preflight.py`, NEW `scripts/check_forbidden_paths.py`, `core/pipeline/orchestration/execution_v2.py`, `core/pipeline/orchestration/retry_v2.py`, `core/pipeline/execution/exec_canonical.py`, `core/pipeline/execution/test_loader.py`, `core/pipeline/orchestration/validate_cases_v2.py`, `core/pipeline/orchestration/orchestrate.py`, `core/pipeline/orchestration/runner.py`
- **Behavior change:** None. Paths resolve to identical locations.
- **Rollback:** Revert PR. No data migration needed.
- **Dependencies:** None.
- **Tests:** Enforcement script + smoke test + rename proof.

---

## Phase B — Parsing/Reconstruction Pipeline Cleanup

### Objective

Make lenient parsing fallback a first-class execution path with structural validation. Promote reconstruction metadata to a dedicated event section.

### B.1 — Three-Level Parse Validity

The pipeline must distinguish:

1. **Parse validity:** Did the parser extract a structured result from the raw model output?
2. **Structural validity:** Does the parsed result contain the required files, meet schema expectations, and pass integrity checks for this case?
3. **Execution eligibility:** Is the parsed + structurally-valid result safe to execute?

Recovery parse success is NOT sufficient for execution. A structurally invalid recovery result must not enter downstream stages.

#### Structural Validation Checks

After any successful parse (strict or recovery), before execution:

1. Required file set: all files in `case["code_files"]` must be present or marked UNCHANGED
2. No duplicate filenames
3. No empty file contents for changed files
4. File-to-module consistency: file names must match expected module names
5. No structurally degenerate output (e.g., all files marked UNCHANGED = no change)

Implement as `validate_parsed_structure(parsed_gen, case) -> (bool, list[str])` in a new function in `execution_v2.py` or a shared utility.

### B.2 — Parsing Decision Matrix

| Strict Parse | Recovery Parse | Structural Valid | Action | `parsing_mode` | `recovery_used` | `structurally_valid` | Executes? | Classified? |
|---|---|---|---|---|---|---|---|---|
| valid | valid, equivalent | yes | Use strict | `strict` | false | true | YES | YES |
| valid | valid, different | yes | Use strict; flag divergence | `strict` | false | true | YES | YES |
| valid | valid | no (strict fails struct) | Try recovery; if struct-valid, use it | `recovery` | true | true | YES | YES |
| valid | invalid | yes | Use strict | `strict` | false | true | YES | YES |
| valid | any | no (both fail struct) | Log failure | `failed` | false | false | NO | NO |
| invalid | valid | yes | Use recovery | `recovery` | true | true | YES | YES |
| invalid | valid | no | Log failure | `failed` | false | false | NO | NO |
| invalid | invalid | — | Log failure | `failed` | false | false | NO | NO |

Key rule: `structurally_valid` must be true for execution to proceed, regardless of which parser produced the output.

### B.3 — Reconstruction Event Section

```python
ev["reconstruction"] = {
    "parsing_mode": "strict" | "recovery" | "failed",
    "strict_parse_valid": bool,
    "recovery_parse_valid": bool,
    "recovery_used": bool,
    "structurally_valid": bool,
    "structural_errors": list[str],    # empty if valid
    "execution_equivalent": bool,       # strict ≡ recovery when both valid
    "strict_recovery_divergent": bool,
    "recon_status": str,               # SUCCESS | RECON_MISSING_FILES | ...
    "files_changed": list[str],
    "files_total": int,
    "executed": bool,                  # did this output enter execution?
}
```

#### Schema Change Classification

**Type:** Additive backward-compatible extension. New top-level section.
**Version:** v7 → v7.1.

**Consumer contract:**
- Old readers: MUST tolerate missing `reconstruction`. Fallback: `event.get("reconstruction") or {}`.
- New readers: MAY rely on `reconstruction` when present. MUST check presence before access.
- Coexistence: indefinite. Old events are never backfilled.
- Analysis code during migration window: check for `reconstruction` first, fall back to `event.extra.v2_parse_tiers` for old events.

### B.4 — Recovery Fallback Rollout (Staged)

Split into three PRs for safe activation:

**PR2a — Instrumentation only:**
- Populate `reconstruction` section in all events
- Run structural validation on all parsed outputs
- Log results but do NOT use recovery output for execution
- Recovery outputs remain diagnostic-only
- Behavior change: none (new fields only)

**PR2b — Recovery behind disabled flag:**
- Add `ENABLE_RECOVERY_EXECUTION = False` constant in `execution_v2.py`
- Wire the fallback logic gated by this flag
- When disabled: behavior identical to PR2a
- Behavior change: none (flag off)

**PR2c — Activate recovery execution:**
- Set `ENABLE_RECOVERY_EXECUTION = True`
- Recovery-parsed, structurally-valid outputs now enter execution
- Behavior change: YES — recoverable outputs get executed and scored
- Rollback: set flag to False (PR2b revert unnecessary)

### B.5 — Validation Gate

1. PR2a: events contain `reconstruction` section. Smoke test passes. No execution behavior change.
2. PR2b: flag-off behavior identical to PR2a. One test verifying flag-off path.
3. PR2c: run 10 trials × 2 models × 1 condition on 3 cases. Verify: ≥1 event has `recovery_used=true`. Verify: all `recovery_used=true` events also have `structurally_valid=true`. Verify: `parsing_mode=strict` events produce identical results to pre-refactor baseline.

---

## Phase C — Classification Pipeline Unification

### Objective

One canonical classifier entrypoint. One normalization layer. Zero duplication.

### C.1 — Canonical Classifier Entrypoint

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
```

This function owns:
1. Variable assembly (`build_classifier_v2_vars`)
2. Prompt compilation (`classify_reasoning_v2`)
3. Model call (evaluator model)
4. Output parsing (`parse_classifier_v2_output`)

No other module may build classifier prompts or parse classifier outputs.

### C.2 — Classification Lifecycle

| Context | Parsed? | Structurally valid? | Executed? | Classified? | Event target |
|---|---|---|---|---|---|
| baseline_v2 success | yes | yes | yes (pass) | YES | `classification` section |
| baseline_v2 exec fail | yes | yes | yes (fail) | YES | `classification` section |
| baseline_v2 struct fail | yes | no | no | NO | `classification.classifier_skipped_reason` |
| baseline_v2 parse fail | no | no | no | NO | `classification.classifier_skipped_reason` |
| retry attempt N | yes | yes | yes | YES (per-attempt) | `trajectory[N].classification` |
| retry final attempt | yes | yes | yes | YES | `classification` section (case-level) |
| retry parse fail | no | — | no | NO | `classification.classifier_skipped_reason` |

#### Classification on Execution Failure: Policy Decision

**Chosen policy: Option A — classify whenever parsing + structural validation succeed, regardless of execution outcome.**

Rationale:
- The classifier evaluates reasoning-to-code alignment, which is meaningful even when execution fails
- LEG is defined as correct reasoning + failed execution; classification is required to compute it
- Execution failure reason is NOT part of classifier input (classifier evaluates the code artifact, not the runtime behavior)
- This maximizes data density for reasoning-vs-execution decomposition

`classifier_skipped_reason` is populated only when parse or structural validation fails. Execution failure never causes classification to be skipped.

### C.3 — Classification Event Section

```python
ev["classification"] = {
    "mechanism_identified": str | None,
    "commitments_extracted": str | None,
    "commitments_satisfied": str | None,
    "reasoning_code_alignment": str | None,
    "classifier_ran": bool,
    "classifier_skipped_reason": str | None,
    "commitment_source": str,           # "explicit" | "inferred" | "none"
}
```

**Schema change:** v7.1 → v7.2. Additive backward-compatible.

**Consumer contract:**
- Old readers: MUST tolerate missing `classification`. Fallback: read from `event.extra` (legacy location).
- New readers: check `classification` first, fall back to `extra` for old events.
- Coexistence: indefinite.

### C.4 — Validation Gate

1. Run baseline_v2 and retry_leg_critique_strict_v2 on 1 case each.
2. Both produce `classification` section with identical structure.
3. `grep -rn "build_classifier_v2_vars\|_compile_prompt.*classify" core/pipeline/orchestration/` returns calls to `classify_case()` only, no inline implementations.
4. `retry_v2.py` imports `classify_case`, does not contain `build_classifier_v2_vars` or `parse_classifier_v2_output`.

### PR: PR3

- **Files:** `core/evaluation/evaluator_v2.py` (extract), `core/pipeline/orchestration/execution_v2.py` (call), `core/pipeline/orchestration/retry_v2.py` (call), `core/logging_/logging_core.py` (consumed keys)
- **Behavior change:** Classification results move from `extra` to `classification`. Classification runs on same-code for both execution paths.
- **Rollback:** Revert PR.
- **Dependencies:** PR1, PR2c.

---

## Phase D — Baseline Commitments Contract Migration

### Objective

Add `code_commitments` to baseline_v2 output schema. Validate quality, not mere presence.

### D.1 — Contract Changes

| Component | Change | File |
|---|---|---|
| Prompt template | Add `code_commitments` instruction | `output_instruction_v3.j2` |
| Schema definition | Add `code_commitments` as optional | `contracts_v2.py` |
| Schema line | Include `code_commitments` in example | `execution_v2.py` |
| Parser | Accept `code_commitments` (optional, not required for parse success) | `parser_v2.py` |
| Evaluator | Use explicit when present, infer when absent | `evaluator_v2.py` |

### D.2 — Commitment Quality Validation

Commitments are not only present but usable. Quality criteria:

**Acceptable commitment:**
- References a concrete code entity (function name, variable, module)
- Specifies a concrete behavioral property (`must return a copy`, `must invalidate cache`)
- Parseable as `<scope> must <action>` or close equivalent

**Unacceptable commitment:**
- Empty string or empty list
- `"fix the bug"`, `"handle correctly"`, `"ensure proper behavior"`
- No reference to any code entity
- Verbatim copy of the task prompt

**Quality classification per response:**

| Commitments field | Quality | Evaluator behavior |
|---|---|---|
| Present, ≥1 meets quality criteria | `explicit` | Use explicit commitments |
| Present, all fail quality criteria | `explicit-low-quality` | Use explicit but flag; evaluator treats as inferred-equivalent |
| Absent | `inferred` | Infer from fix_strategy (legacy behavior) |

### D.3 — Backward Compatibility

- Old baseline runs (no `code_commitments`): evaluator infers. No behavior change.
- New baseline runs: evaluator uses explicit commitments when quality passes.
- Cross-era comparison: valid with documented caveat (noisy inferred vs clean explicit).
- Within-era: fully valid.

### D.4 — Validation

1. Run 10 trials × 2 models (nano, 5mini) × 3 baseline_v2 cases.
2. **Presence rate:** `code_commitments` present in ≥80% of responses.
3. **Quality rate:** ≥60% of present commitments meet quality criteria.
4. If presence <50%: prompt insufficient, revise before shipping.
5. If quality <40%: commitments not useful, defer migration.
6. Verify backward compat: manually constructed response without `code_commitments` → evaluator falls back to inference.

### PR: PR4

- **Files:** `output_instruction_v3.j2`, `contracts_v2.py`, `execution_v2.py`, `parser_v2.py`, `evaluator_v2.py`
- **Behavior change:** Yes. New outputs include commitments. Evaluator changes for new runs.
- **Rollback:** Revert prompt template. New runs revert to old behavior.
- **Dependencies:** PR3 (classifier unified, commitment handling in one place).

---

## Phase E — AST Verification Integration

### Objective

Add deterministic structural verification as a pipeline enrichment stage.

### E.1 — Architectural Role: Semi-Structured Analytical Signal

AST verification is a **semi-structured analytical signal with quality targets but no pipeline guarantees.**

Concretely:
- It is NOT a pipeline gate. AST failure does not invalidate execution results.
- It is NOT a first-class event section. It lives in `extra` as enrichment.
- Coverage is partial. Not all cases have specs. Absence is normal.
- FN/FP rates are expected and bounded by spec quality.
- Consumers interpret: `measurable=false` (no spec or syntax error), `ast_correct=true/false` (spec exists, result determined), absent (pre-Phase-E event).

**Promotion path:** If FP < 5% and FN < 15% after Phase E validation, AST can be promoted to a first-class section (v7.3) in a future PR. That decision is deferred.

### E.2 — Design

Create `core/evaluation/ast_eval.py`:

```python
from core.config.paths import AST_SPECS_PATH

def check_ast_patterns(
    reconstructed_files: dict[str, str],
    case_id: str,
) -> ASTResult:
```

- Loads specs from `paths.AST_SPECS_PATH` (Phase A centralized path).
- Spec lookup and detector dispatch are separate layers.
- Adding a detector does not require modifying spec loading.

### E.3 — Phase 1 Scope

- 5 detectors: `copy_call_on_assignment`, `cache_invalidation_call`, `none_guard_for_default`, `statement_in_loop`, `break_after_success`
- Specs for 15 single-file cases (alias_config ×3, stale_cache ×3, mutable_default ×3, effect_order ×3, retry_dup ×3)
- Expected FN: ~10% (alternative correct patterns not in spec). Mitigated by `alternative_patterns`.
- Expected FP: <5% (pattern in wrong function). Mitigated by function-scoping.

### E.4 — Validation Gate

1. Automated: reference fix passes AST check for all 15 spec'd cases. Buggy code fails for all 15.
2. Manual: hand-review 10 model outputs per case (5 AST-correct, 5 AST-incorrect). Compute FP/FN.
3. If FP > 10% or FN > 20%: revise specs before shipping.

### PR: PR5

- **Files:** NEW `core/evaluation/ast_eval.py`, NEW `case_data/ast_specs.json`, `core/pipeline/orchestration/execution_v2.py` (add stage), `core/pipeline/orchestration/retry_v2.py` (add after final attempt)
- **Behavior change:** New `ast_eval` field in event `extra`. No execution behavior change.
- **Rollback:** Revert PR.
- **Dependencies:** PR1 (paths), PR2c (recovery, so AST runs on recovered code).

---

## Phase F — Invariant/Test Audit

### Objective

Strengthen invariants for the 13 single-test families. Target: ≥30 of 58 cases with ≥3 distinct invariant checks.

### F.1 — Prioritization Score

Priority = `LEG_rate × 0.4 + (1 - pass_rate) × 0.3 + (1 / current_checks) × 0.3`

Higher score = higher priority. This weights: high LEG (reasoning-execution gap worth measuring), low pass rate (room for discrimination), few current checks (most to gain).

| Family | LEG% | Pass% | Checks | Score | Priority |
|---|---|---|---|---|---|
| invariant_partial_fail | 93 | 6 | 2 | 0.80 | 1 |
| overdetermination | 25 | 70 | 1 | 0.49 | 2 |
| config_shadowing | 64 | 30 | 3 | 0.57 | 3 |
| l3_state_pipeline | 62 | 34 | 3 | 0.55 | 4 |
| feature_flag_drift | 67 | 31 | 5 | 0.48 | 5 |
| hidden_dep_multihop | 60 | 40 | 4 | 0.44 | 6 |
| lost_update | 57 | 34 | 4 | 0.44 | 7 |
| false_fix_deadlock | 77 | 20 | 8 | 0.39 | 8 |
| cache_invalidation_order | 52 | 48 | 4 | 0.38 | 9 |
| check_then_act | 43 | 47 | 5 | 0.31 | 10 |
| async_race_lock | 98 | 0 | 4 | 0.54 | DEFER (0% pass) |
| commit_gate | 14 | 86 | 5 | 0.16 | 11 |
| ordering_dependency | 18 | 81 | 4 | 0.16 | 12 |

### F.2 — Per-Family Audit Template

For each audited family (top 7 by priority):

| Property | Required |
|---|---|
| Current assertions | List each check |
| Known/plausible trap fixes | ≥1 concrete wrong fix that passes current tests |
| Missing invariant classes | trap-catching, generalization, causal-location |
| Proposed new assertions | Concrete check descriptions |
| Validation: buggy fails | Confirmed |
| Validation: reference passes | Confirmed |
| Validation: trap-fix fails | Confirmed for ≥1 trap |

### F.3 — Rules

1. No new invariant without buggy-fails + reference-passes validation.
2. Trap-fix validation required when a plausible trap fix is identified.
3. No decorative assertions (checks that pass for both buggy and reference are useless).
4. Each new assertion must target a specific invariant class (trap-catching, generalization, or causal-location).

### PR: PR6

- **Files:** 7 test files in `case_data/tests_v2/`
- **Behavior change:** Tests are stricter.
- **Rollback:** Revert test files.
- **Dependencies:** None. Runs in parallel with Phases A-E.

---

## Phase G — Analysis and Backward-Compat Migration

### Objective

Update analysis scripts for new event structure. Migrate remaining hardcoded paths in scripts.

### Tasks

1. Update `scripts/global_cal_analysis.py`, `per_case_analysis.py`, `per_triple_analysis.py`:
   - Read `event.reconstruction` when present; fall back to `event.extra.v2_parse_tiers`.
   - Read `event.classification` when present; fall back to `event.extra`.
   - Read `event.extra.ast_eval` when present.
2. Add `parsing_mode` as analysis dimension.
3. Add `ast_correct` as analysis dimension where available.
4. Migrate path references in scripts to `core.config.paths` imports.

### PR: PR7

- **Files:** analysis scripts under `scripts/`
- **Behavior change:** None (analysis only).
- **Rollback:** Revert scripts.
- **Dependencies:** PR2a, PR3, PR5 (needs new event sections to exist).

---

## PR Summary

| PR | Phase | Behavior Change | Key Files | Dependencies | Rollback |
|---|---|---|---|---|---|
| PR1 | A | No | paths.py + 8 core modules | None | Revert |
| PR2a | B (instrumentation) | No | execution_v2.py, logging_core.py | PR1 | Revert |
| PR2b | B (flag-off fallback) | No | execution_v2.py | PR2a | Revert |
| PR2c | B (activate recovery) | YES | execution_v2.py (flag flip) | PR2b | Set flag=False |
| PR3 | C | YES (classifier unified) | evaluator_v2.py + execution + retry | PR1, PR2c | Revert |
| PR4 | D | YES (baseline commitments) | prompt + schema + parser + evaluator | PR3 | Revert prompt |
| PR5 | E | No (extra field) | ast_eval.py + ast_specs.json + execution | PR1, PR2c | Revert |
| PR6 | F | YES (stricter tests) | 7 test files | None (parallel) | Revert tests |
| PR7 | G | No (analysis) | scripts/ | PR2a, PR3, PR5 | Revert |

---

## Hidden Assumptions and Failure Modes

| Assumption | What Could Fail | Detection | Contingency |
|---|---|---|---|
| Recovery parser outputs are often structurally salvageable | Recovery outputs may be structurally degenerate (all UNCHANGED, missing files) | Structural validation in B.1 catches this; `structurally_valid=false` logged | Recovery output rejected; treated as parse failure |
| Classifier can operate meaningfully on artifacts when execution fails | Classifier may not produce useful signal when code is deeply broken | Monitor classifier-skipped rate and agreement with execution outcomes | If classifier-on-failure adds noise, restrict to execution-success-only in a follow-up |
| Path centralization does not break CWD-relative harness behavior | `run_case.py` uses CWD-relative paths in temp directories | Documented exception; smoke test covers harness execution | If broken, exclude run_case.py from migration |
| Baseline commitments can be elicited with adequate specificity | Models produce generic/useless commitments | Quality rate check in D.4 (≥60% must meet quality criteria) | If quality too low, defer migration or strengthen prompt examples |
| AST specs achieve acceptable noise rates for initial subset | FP/FN rates exceed thresholds | Manual review in E.4 (FP<10%, FN<20%) | Revise specs; narrow to highest-confidence cases only |
| Invariant strengthening targets realistic trap fixes | Proposed traps may not match actual model behavior | Trap-fix validation required for each new invariant | If no plausible trap fix identified, flag the invariant as "generalization-only" |

---

## Acceptance Criteria

### Path Centralization
- Zero critical-path repo-layout string literals outside `paths.py` and documented exceptions
- Enforcement script (`check_forbidden_paths.py`) exits 0 and runs before PRs
- Preflight (`validate_repo_structure()`) runs at startup and catches missing assets within 1 second
- Changing one path in `paths.py` reroutes all dependent loads (rename proof passes)

### Parsing/Recovery
- Every new event contains `reconstruction` section with `parsing_mode`, `structurally_valid`, `executed` fields
- Recovery outputs entering execution are structurally validated (not just parse-valid)
- Recovery activation is independently toggleable (flag-based rollback)
- No event has `executed=true` AND `structurally_valid=false`

### Classification
- One canonical classifier implementation (`classify_case()` in `evaluator_v2.py`)
- `execution_v2.py` and `retry_v2.py` both call it; neither contains inline prompt-building
- Classification runs whenever parse + structural validation succeed, including on execution failures
- `classification` section present in all new events

### Commitments
- Presence rate ≥80% in new baseline runs
- Quality/specificity rate ≥60% of present commitments
- Evaluator uses explicit when present, infers when absent, with no silent degradation

### AST
- Role explicitly defined as semi-structured analytical signal (not pipeline gate)
- Spec loading uses `paths.AST_SPECS_PATH`
- Reference fixes pass, buggy code fails, for all 15 spec'd cases
- FP < 10%, FN < 20% on manual review

### Invariants
- ≥30 of 58 cases have ≥3 distinct invariant checks
- Every new assertion validated against buggy (fails) and reference (passes)
- ≥70% of new assertions validated against a plausible trap fix

### Backward Compatibility
- Old events readable by all analysis scripts without errors
- Missing `reconstruction`, `classification`, `ast_eval` sections handled with explicit fallback logic
- No analysis script crashes on pre-refactor event data

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
| exec_canonical.py:109 | `Path(...) / "core" / "harness" / "run_case.py"` | execution | YES | `paths.HARNESS_SCRIPT` | PR1 |
| test_loader.py:64 | `_PROJECT_ROOT / "case_data" / "tests_v2"` | execution | YES | `paths.TESTS_V2_DIR` | PR1 |
| validate_cases_v2.py:53 | `BASE / "tests_v2"` | validation | YES | `paths.TESTS_V2_DIR` | PR1 |
| orchestrate.py:377+ | `"orchestrator.lock"` | orchestration | YES | `paths.LOCK_FILENAME` | PR1 |
| orchestrate.py:737 | `"merged_events.jsonl"` | orchestration | YES | `paths.MERGED_EVENTS_FILENAME` | PR1 |
| orchestrate.py:979+ | `"manifest.json"` | orchestration | YES | `paths.MANIFEST_FILENAME` | PR1 |
| orchestrate.py:1076 | `"config.snapshot.yaml"` | orchestration | YES | `paths.CONFIG_SNAPSHOT_FILENAME` | PR1 |
| orchestrate.py:888 | `"trial_config.yaml"` | orchestration | YES | `paths.TRIAL_CONFIG_FILENAME` | PR1 |
| orchestrate.py:892-893 | `"stdout.log"`, `"stderr.log"` | orchestration | NO | `paths.STDOUT_LOG_FILENAME`, etc. | PR1 |
| orchestrate.py:573+ | `"events.jsonl"` | orchestration | YES | `paths.EVENTS_FILENAME` | PR1 |
| orchestrate.py:781 | `"heartbeat.json"` | orchestration | NO | `paths.HEARTBEAT_FILENAME` | PR1 |
| runner.py:240 | `"heartbeat.json"` | orchestration | NO | `paths.HEARTBEAT_FILENAME` | PR1 |
| orchestrate.py:805 | `/proc/{pid}/cmdline` | orchestration | NO | Leave (system) | — |
| run_case.py:41,50,158 | CWD-relative | harness | NO | Leave (documented) | — |
