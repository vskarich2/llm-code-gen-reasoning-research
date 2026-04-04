# Plan to Evolve the Current AST System into a Real AST-Based Reasoning Verifier — v1

**Date:** 2026-04-03
**Status:** PLAN ONLY
**Grounded in:** `artifacts/audits/ast_system_audit_20260403.md`, full code inspection of `core/evaluation/ast_eval.py`, `core/evaluation/ast_checker_overrides.py`, `core/pipeline/orchestration/execution_v2.py`, `case_data/deep_dependency_chain_cases/spec_types.py`, `case_data/deep_dependency_chain_cases/validator.py`

---

## 1. Executive Gap Assessment

### Blunt assessment

The current AST system is **roughly 40% of the way to the target verifier design.** The foundation is real and the pipeline integration is correct, but what exists is a pattern matcher, not a reasoning verifier.

**What is genuinely aligned:**
- Non-gating analytical signal, independent of execution — correct architecture
- Per-family checker dispatch via a registry — correct extensibility model
- Strict/relaxed/anti three-tier checking — correct graduated validation
- Pipeline integration in execution_v2.py — wired correctly at line 612
- Event logging and materialization — working end-to-end
- 47/58 case coverage with validated specs — real, tested, not vapor

**What is fundamentally missing:**
- **Claim-aware verification.** The verifier never sees the model's `code_commitments` or `root_cause`. It compares patch-vs-truth only, never patch-vs-claim. The model says "create_config must return a copy of DEFAULTS" — the verifier has no way to check if the patch honors that stated commitment.
- **Structural locus verification.** The verifier checks "does function X contain pattern Y?" but doesn't check "did the model change the RIGHT file/function?" A model that fixes the wrong function gets ast_correct=False but the reason (wrong location) is not surfaced.
- **Lightweight program analysis.** No use-def tracing, no call target resolution, no symbol tracking. Checkers use `ast.walk()` and node-type matching only. This is why 11 cases are NOT_AST_MEASURABLE — some of them could be measurable with even minimal dataflow.
- **Deep dependency chain support.** 8 cases exist with a rich spec type system (CaseSpec, ChainNode, TrapSpec, 5 invariant types) but zero connection to the AST verifier.
- **Uncheckability taxonomy.** The `NOT_AST_MEASURABLE` set is a flat Python set with no typed reasons. "Lock ordering" and "checker not yet written" are lumped together.

**Biggest conceptual gap:** The system measures *structural pattern presence* but not *structural repair fidelity*. It asks "does this code have .copy()?" not "did the model correctly repair the aliasing violation at the reported locus?"

**Biggest engineering gap:** The deep dependency chain cases have a sophisticated validation harness (`validator.py` with 5 invariant types, trap attribution, depth classification) that is architecturally superior to the main benchmark's invariant tests — but completely disconnected.

**Biggest scientific validity risk if nothing changes:** The claim "AST measures structural reasoning correctness" is overstated. AST currently measures structural pattern presence, which is a necessary-but-not-sufficient condition. The 10% AST false-positive rate on execution-failing events (from the instrument validation audit) is the direct consequence: some patterns are present but semantically wrong, and the verifier can't tell.

---

## 2. Current-State vs Target-State Matrix

| Dimension | Current System | Target System | Gap | Priority |
|-----------|---------------|---------------|-----|----------|
| **Purpose of AST signal** | Pattern presence (does code contain .copy()?) | Structural repair fidelity (did model correctly repair the invariant violation?) | Conceptual reframe needed | HIGH |
| **Execution independence** | Fully independent — runs after exec, never gates it | Same | **ALIGNED** | — |
| **Syntax vs structural reasoning** | Structural pattern matching (strict/relaxed/anti) | Property-based structural verification with lightweight program analysis | Needs dataflow/symbol layer | MEDIUM |
| **Family-specific checking** | 21 family-specific checker sets in registry | Same but with richer property specs | **ALIGNED**, needs metadata upgrade | LOW |
| **Case metadata/spec** | Fix pattern + invariant in cases_v2.json, checker rules in Python dicts | Structured `structural_spec` per case with locus, required changes, forbidden patterns, alternatives, checkability level | **MISSING** — specs are in code, not data | HIGH |
| **Patch-vs-truth verification** | Yes (compares against reference fix patterns) | Same but more explicit | **ALIGNED** | LOW |
| **Patch-vs-claim verification** | **MISSING** — verifier never sees model claims | Compare model's code_commitments to patch structure | **FULLY MISSING** | HIGH |
| **Alternative valid repair** | Relaxed equivalence classes with alternatives list | Same but formalized in metadata | **PARTIALLY ALIGNED** — alternatives in code, not data | MEDIUM |
| **Use-def / symbol tracing** | None | Lightweight: variable name tracking, assignment chain following | **MISSING** | MEDIUM |
| **Statement ordering / path sensitivity** | Basic: checks call ordering in function body | Richer: bounded locality, block membership, control flow awareness | **WEAK** — ordering checks are fragile | MEDIUM |
| **Cross-file call target resolution** | None (single-function scoping) | Resolve what function a call actually invokes across files | **MISSING** | LOW (only needed for multi-file cases) |
| **NOT_AST_MEASURABLE handling** | Flat Python set, no reasons | Typed enum with categories: runtime-only, literal-value, underconstrained, not-yet-implemented | **MISSING taxonomy** | HIGH |
| **Deep dependency chain support** | 0% — 8 cases exist but not connected | Corruption-site repair detection, band-aid detection, chain-aware locus verification | **FULLY MISSING** | HIGH |
| **Duplication** | Checkers in both scripts/ast_phase1/ and core/evaluation/ | Single canonical implementation | **INV-02 VIOLATION** — fix immediately | CRITICAL |
| **Event logging** | `ev["ast_eval"]` with status/correct/score | Same + claim alignment + truth alignment + locus match + mechanism match | **NEEDS EXPANSION** | MEDIUM |
| **Derived metrics** | ast_correct, ast_score, LUCKY_FIX, LEG_ast | + ast_claim_alignment, ast_truth_alignment, ast_alternative_valid, translation_failure | **NEEDS EXPANSION** | MEDIUM |

---

## 3. What to Keep, What to Refactor, What to Replace

### Keep (retain as foundation)

| Component | Why keep |
|-----------|---------|
| `core/evaluation/ast_eval.py` main entry point | Correct interface: takes reconstructed files + case_id, returns ASTResult. Pipeline wiring is right. |
| `core/evaluation/ast_checkers.py` checker registry | 21 family checker sets, all validated against ref fixes and buggy code. The pattern matchers are real. |
| `core/evaluation/ast_checker_overrides.py` | Invariant-justified v2 fixes. Each documents its invariant reasoning. |
| Pipeline integration in `execution_v2.py:605-627` | Correct: runs after exec, uses same reconstructed files, always emits result. |
| `core/evaluation/materialize.py` AST extraction | Works. Needs expansion for new fields but the pattern is right. |
| `ASTResult` dataclass | Good skeleton. Needs additional fields for claim/truth/locus. |

### Refactor (useful but mis-scoped or too narrow)

| Component | What to refactor |
|-----------|-----------------|
| Checker rules (Python dicts in code) | Move to structured metadata in cases_v2.json `structural_spec` section. Keep Python dispatchers but drive them from data, not hardcoded dicts. |
| `NOT_AST_MEASURABLE` (flat set in checker_fixes.py) | Replace with typed enum in case metadata. Categories: `runtime_only`, `literal_value`, `underconstrained`, `not_yet_implemented`, `fundamentally_uncheckable`. |
| `find_function()` scoping | Currently finds one function by name. Need: multi-function scoping (check if fix is in the right function), module-level scoping (already partial), and file-level scoping (which file was changed). |
| Relaxed equivalence classes | Currently inline in checker functions. Formalize as lists of alternative patterns in the structural_spec metadata. |

### Replace / Decommission

| Component | Action |
|-----------|--------|
| `scripts/ast_phase1/checkers.py` | **DECOMMISSION.** This is a duplicate of `core/evaluation/ast_checkers.py`. Remove from scripts/, keep only in core/. Any offline tool should import from core/. |
| `scripts/ast_phase1/checker_fixes.py` | **DECOMMISSION.** `NOT_AST_MEASURABLE` and `CASE_RULES_OVERRIDES` are already in core/ equivalents. Remove. |
| `scripts/ast_phase1/checker_fixes_v2.py` | **DECOMMISSION.** `CHECKER_V2_OVERRIDES` already in core/. Remove. |
| `scripts/ast_phase1/retro_eval.py` | **KEEP as offline tool** but make it import from `core.evaluation.ast_eval` instead of local checkers. |
| `scripts/ast_phase1/retro_eval_full.py` | Same — keep but rewrite imports to use canonical core/ modules. |
| `scripts/ast_phase1/validate_specs.py` | Same — keep but rewrite imports. |

---

## 4. Target Architecture

```
core/evaluation/
  ast_verifier/                         [NEW directory]
    __init__.py                         [NEW — public API: verify_structural_repair()]
    result.py                           [REFACTORED from ASTResult — expanded schema]
    registry.py                         [REFACTORED — loads structural_specs from case metadata]
    checkers/                           [REFACTORED — family-specific checkers]
      __init__.py
      aliasing.py                       [MOVED from ast_checkers.py alias section]
      cache.py                          [MOVED from ast_checkers.py stale_cache/invalidation sections]
      mutable_default.py                [MOVED]
      control_flow.py                   [MOVED — effect_order, early_return, use_before_set]
      retry.py                          [MOVED — retry_dup]
      rollback.py                       [MOVED — partial_rollback, invariant_partial_fail]
      branch.py                         [MOVED — missing_branch, wrong_condition]
      dependency.py                     [MOVED — hidden_dep_multihop, lazy_init, temporal_drift]
      state_pipeline.py                 [MOVED — l3_state_pipeline, commit_gate]
      deep_chain.py                     [NEW — deep dependency chain checkers]
    analysis/                           [NEW — lightweight program analysis]
      symbol_tracker.py                 [NEW — variable name extraction, assignment tracking]
      call_resolver.py                  [NEW — call target name resolution within a file]
      ordering.py                       [NEW — statement ordering with locality bounds]
    claim_verifier.py                   [NEW — compares model commitments to patch structure]
    truth_verifier.py                   [REFACTORED — current patch-vs-truth checking, made explicit]
    locus_verifier.py                   [NEW — checks model changed the right file/function]
    uncheckability.py                   [NEW — typed enum and classification for uncheckable cases]

  ast_eval.py                           [KEEP — thin wrapper calling ast_verifier/]
  ast_checkers.py                       [DEPRECATED — replaced by ast_verifier/checkers/]
  ast_checker_overrides.py              [DEPRECATED — overrides folded into family modules]
  materialize.py                        [REFACTORED — expand AST field extraction]
```

| Module | Status | Responsibility |
|--------|--------|---------------|
| `ast_verifier/__init__.py` | NEW | Public API: `verify_structural_repair(files, case_id, model_claims, artifact_id)` |
| `ast_verifier/result.py` | REFACTORED | `VerificationResult` with truth alignment, claim alignment, locus match, mechanism match, alternatives, checkability |
| `ast_verifier/registry.py` | REFACTORED | Load structural_spec from case metadata, dispatch to family checker |
| `ast_verifier/checkers/*.py` | MOVED+SPLIT | One module per family cluster. Each checker function takes `(tree, func_node, spec)` |
| `ast_verifier/analysis/symbol_tracker.py` | NEW | Extract assigned variable names, track name-to-value bindings at function scope |
| `ast_verifier/analysis/call_resolver.py` | NEW | Resolve `foo()` → which function definition `foo` refers to (same-file only) |
| `ast_verifier/analysis/ordering.py` | NEW | Statement ordering with bounded distance and block-membership checks |
| `ast_verifier/claim_verifier.py` | NEW | Parse model `code_commitments`, extract `<scope> must <action>` pairs, check each against AST |
| `ast_verifier/truth_verifier.py` | REFACTORED | Current checker logic, explicitly named as "truth-aware" verification |
| `ast_verifier/locus_verifier.py` | NEW | Check: did model modify the file/function specified in `structural_spec.target`? |
| `ast_verifier/uncheckability.py` | NEW | `CheckabilityLevel` enum, `classify_checkability()` function |
| `ast_verifier/deep_chain.py` | NEW | Corruption-site repair detection, band-aid detection, chain locus verification |

---

## 5. Required Data Model Changes

### New `structural_spec` section in cases_v2.json

Each case gets a `structural_spec` block alongside the existing `ground_truth_bug` and `reference_fix`:

```json
{
  "id": "alias_config_a",
  "structural_spec": {
    "checkability": "fully_checkable",
    "target": {
      "file": "config.py",
      "function": "create_config",
      "scope": "function"
    },
    "required_changes": [
      {
        "id": "copy_on_return",
        "type": "method_call_present",
        "description": "Return value involves defensive copy of DEFAULTS",
        "params": {"object": "DEFAULTS", "methods": ["copy"]},
        "alternatives": [
          {"type": "builtin_call", "func": "dict", "arg": "DEFAULTS"},
          {"type": "dict_unpacking", "source": "DEFAULTS"},
          {"type": "method_call", "object": "copy", "method": "deepcopy"}
        ],
        "severity": "critical"
      }
    ],
    "forbidden_patterns": [
      {
        "id": "bare_reference_return",
        "type": "bare_name_assign_or_return",
        "params": {"name": "DEFAULTS"},
        "description": "Raw DEFAULTS reference without copy"
      }
    ],
    "claim_checkable": true,
    "claim_mapping": {
      "expected_scope": "create_config",
      "expected_action_keywords": ["copy", "independent", "fresh"]
    },
    "checker_family": "aliasing",
    "notes": null
  }
}
```

### Example 2: Hidden dependency case

```json
{
  "id": "hidden_dep_multihop",
  "structural_spec": {
    "checkability": "fully_checkable",
    "target": {
      "file": "user_service.py",
      "function": "save_user",
      "scope": "function"
    },
    "required_changes": [
      {
        "id": "overwrite_cache_call",
        "type": "call_name_present",
        "description": "save_user must call an always-overwrite cache function",
        "params": {"expected_names": ["sync_user_to_cache", "cache_put"]},
        "alternatives": [
          {"type": "call_name_present", "params": {"name_contains": "cache", "name_not_in": ["refresh_user_snapshot", "cache_put_if_absent"]}}
        ],
        "severity": "critical"
      }
    ],
    "forbidden_patterns": [
      {
        "id": "conditional_cache_call",
        "type": "call_name_present",
        "params": {"names": ["refresh_user_snapshot", "cache_put_if_absent"]}
      }
    ],
    "claim_checkable": true,
    "checker_family": "dependency"
  }
}
```

### Example 3: Deep dependency chain case

```json
{
  "id": "ddc_auth_context",
  "structural_spec": {
    "checkability": "chain_checkable",
    "target": {
      "file": "context_normalizer.py",
      "function": "normalize",
      "scope": "function"
    },
    "chain": {
      "corruption_site": "context_normalizer",
      "first_symptom": "resource_gate",
      "bypass_consumer": "audit_logger",
      "chain_length": 4
    },
    "required_changes": [
      {
        "id": "preserve_org_prefix",
        "type": "no_prefix_stripping",
        "description": "normalize() must preserve the ORG- prefix on org_id",
        "params": {"field": "org_id", "prefix": "ORG-"}
      }
    ],
    "forbidden_patterns": [
      {
        "id": "downstream_band_aid",
        "type": "call_in_wrong_module",
        "description": "Fix applied at permission_resolver or resource_gate instead of context_normalizer",
        "params": {"wrong_modules": ["permission_resolver", "resource_gate"]}
      }
    ],
    "trap_detection": {
      "band_aid_indicators": [
        {"trap_type": "endpoint_compensation", "check": "default_tier_grant_in_gate"},
        {"trap_type": "downstream_override", "check": "re_prefix_in_resolver"}
      ]
    },
    "claim_checkable": true,
    "checker_family": "deep_chain",
    "invariant_names": ["trap_catching", "generalization", "causal_location", "cross_path", "chain_integrity"]
  }
}
```

---

## 6. Claim-Aware Verification Plan

### Input representation

The model already produces structured `code_commitments` in LEG/lean conditions:
```json
["create_config must return a copy of DEFAULTS",
 "apply_config must not mutate the cached base configuration"]
```

These are normalized by `reasoning_v2.normalize_generation_v2()` into `normalized_code_commitments` in the artifact. The format is `"<scope> must <action>"`.

### How claim verification works

For each commitment `"<scope> must <action>"`:
1. **Locus check:** Does the patch modify `<scope>` (function name)?
2. **Action check:** Does the patch contain structural evidence of `<action>`?
   - "return a copy" → check for .copy() / dict() / unpacking
   - "not mutate the cached" → check that no mutation of cached object exists
3. **Consistency check:** Is the stated scope the same as the `structural_spec.target.function`?

### Output fields

```python
@dataclass
class VerificationResult:
    # Existing (keep)
    status: str                    # no_spec | not_measurable | measured
    ast_correct: bool | None       # truth-aligned structural correctness

    # New: truth-aware
    ast_truth_alignment: str       # correct | incorrect | partial | uncheckable
    ast_location_match: bool       # did model change the right file/function?
    ast_mechanism_match: bool      # does patch address the right structural property?
    ast_alternative_valid: bool    # is this a non-canonical but valid repair?

    # New: claim-aware
    ast_claim_alignment: str       # aligned | misaligned | no_claims | uncheckable
    claims_checked: int            # how many commitments were verifiable
    claims_matched: int            # how many matched the patch

    # Metadata
    checkability: str              # fully_checkable | partially_checkable | chain_checkable | uncheckable
    checker_family: str
```

### Logging

Both signals logged separately in `ev["ast_eval"]`:
```json
{
  "ast_truth_alignment": "correct",
  "ast_claim_alignment": "aligned",
  "ast_location_match": true,
  "ast_mechanism_match": true,
  "ast_alternative_valid": false,
  "claims_checked": 2,
  "claims_matched": 2,
  "checkability": "fully_checkable"
}
```

---

## 7. Checker Strategy by Bug Family

| Family | Current checker | Sufficient? | What's needed | Dataflow needed? |
|--------|----------------|-------------|---------------|-----------------|
| **Aliasing** (alias_config) | .copy()/dict() detection | YES | Add claim-locus check | No |
| **Partial state update** (partial_update) | Dependent field assignment count | WEAK | Need to check WHICH fields in WHICH branches | Minimal (branch-target tracking) |
| **Hidden dependency** (hidden_dep_multihop) | Call name substitution | YES (v2) | Add cross-file import chain check | Yes (call resolution) |
| **Edge-case omission** (missing_branch) | Branch count / dict key count | MEDIUM | Need module-level dict checking for a/b | No |
| **Retry-state accumulation** (retry_dup) | Break in loop | YES | Adequate | No |
| **Cache invalidation** (stale_cache, cache_inv_order) | Invalidation call after write | YES (v2) | Adequate with ordering | No |
| **Execution model** (mutable_default) | None default + guard | YES | Adequate | No |
| **Silent failure** (early_return) | Audit call on all paths | YES (v2) | Adequate with path coverage | Minimal (path enumeration) |
| **Control flow** (effect_order) | Call inside loop | YES | Adequate | No |
| **Rollback** (partial_rollback, invariant_partial_fail) | Compensation in except | MEDIUM | Need to verify compensation targets correct variable | Yes (symbol tracking) |
| **Temporal ordering** (temporal_drift) | Argument check | YES (v2) | Adequate | No |
| **State pipeline** (l3_state_pipeline, commit_gate) | Both calls present | YES | Adequate (test now fixed) | No |
| **Deep dependency chain** | MISSING | — | Chain-aware locus verification, band-aid detection | Yes (cross-module) |
| **Atomicity** (lost_update, check_then_act) | NOT_AST_MEASURABLE | Correct | Fundamentally uncheckable by AST | — |
| **Lock ordering** (false_fix_deadlock) | NOT_AST_MEASURABLE | Correct | Fundamentally uncheckable by AST | — |

---

## 8. Handling NOT_AST_MEASURABLE Cases

### Proposed taxonomy (typed enum)

```python
class CheckabilityLevel(str, Enum):
    FULLY_CHECKABLE = "fully_checkable"          # single-function structural pattern
    PARTIALLY_CHECKABLE = "partially_checkable"  # some properties checkable, some not
    CHAIN_CHECKABLE = "chain_checkable"          # deep dependency chain: needs chain-aware checker
    UNCHECKABLE_RUNTIME = "uncheckable_runtime"  # atomicity, lock ordering — runtime semantics only
    UNCHECKABLE_LITERAL = "uncheckable_literal"  # fix is a specific literal value (5→30)
    UNCHECKABLE_MULTIPATH = "uncheckable_multipath"  # too many valid structural forms
    NOT_YET_IMPLEMENTED = "not_yet_implemented"  # COULD be checked but checker doesn't exist
```

### Current 11 NOT_AST_MEASURABLE cases reclassified:

| Case | Current | Proposed | Rationale |
|------|---------|----------|-----------|
| false_fix_deadlock | NOT_AST_MEASURABLE | `uncheckable_runtime` | Lock ordering is semantic |
| lost_update | NOT_AST_MEASURABLE | `uncheckable_runtime` | Atomicity is runtime |
| check_then_act | NOT_AST_MEASURABLE | `uncheckable_runtime` | Atomicity is runtime |
| ordering_dependency | NOT_AST_MEASURABLE | `uncheckable_runtime` | Complex buffering |
| config_shadowing | NOT_AST_MEASURABLE | `uncheckable_literal` | Fix is literal 5→30 |
| feature_flag_drift | NOT_AST_MEASURABLE | `uncheckable_multipath` | Too many valid propagation paths |
| index_misalign_b | NOT_AST_MEASURABLE | `not_yet_implemented` | COULD check parallel structure consistency with better checker |
| index_misalign_c | NOT_AST_MEASURABLE | `not_yet_implemented` | Same |
| silent_default_a | NOT_AST_MEASURABLE | `not_yet_implemented` | COULD check string literal with caller-side analysis |
| silent_default_c | NOT_AST_MEASURABLE | `not_yet_implemented` | Same |
| partial_update_b | NOT_AST_MEASURABLE | `not_yet_implemented` | COULD check branch-specific assignment with branch tracking |

**Key insight:** 5 of 11 "unmeasurable" cases are actually `not_yet_implemented` — they could become measurable with the lightweight analysis in Phase 3.

### Encoding in case metadata

```json
"structural_spec": {
  "checkability": "uncheckable_runtime",
  "uncheckable_reason": "Lock ordering correctness depends on runtime variable identity, not AST structure",
  ...
}
```

### Metrics surfacing

In materialized results, report `checkability` alongside `ast_correct`:
- `ast_correct` is `null` for uncheckable cases (not `false`)
- `checkability` is always a string value
- Aggregate metrics exclude uncheckable cases from AST-conditioned analysis
- Dashboard shows checkability distribution

---

## 9. Deep Dependency Chain Integration Plan

### How to bring into main benchmark

1. **Add to cases_v2.json:** Each of the 8 DDC cases gets a full entry with `structural_spec` (checkability="chain_checkable")
2. **Add tests to tests_v2/:** Adapt each case's `run_primary_test` into the standard `test(mod)` format
3. **Add code to code_snippets_v2/:** Each chain node becomes a file in the case directory
4. **Add reference fixes:** The `apply_root_fix` function output becomes the reference fix
5. **Add AST checkers:** New `deep_chain.py` checker module

### What DDC checkers need to detect

1. **Corruption-site repair:** Did the model fix the code at the corruption node (e.g., `context_normalizer.normalize()`)? Check: required change exists at the target function in the target file.

2. **Downstream band-aid detection:** Did the model instead fix a downstream node? Check: forbidden patterns exist in files other than the corruption site (e.g., re-prefix logic in `permission_resolver`).

3. **Mixed repair detection:** Did the model do a partial root fix AND a downstream patch? Check: required change at corruption site + forbidden pattern elsewhere.

4. **Cross-path consistency:** The DDC spec has a `bypass_consumer`. Check: does the fix also work for the bypass path? This is actually an invariant test concern, not AST — but AST can check if the model touched the right place.

### Checker architecture for DDC

```python
def check_deep_chain(files: dict[str, str], spec: dict) -> VerificationResult:
    """Check a deep dependency chain case.
    
    1. Parse all files
    2. Find the corruption site function
    3. Check required_changes at corruption site
    4. Scan OTHER files for forbidden patterns (band-aids)
    5. Classify: root_fix | band_aid | mixed | uncheckable
    """
```

### Timeline

DDC should be **Phase 4** — after the core verifier is mature. Rationale: DDC cases have a fundamentally different checker architecture (multi-file, chain-aware, trap-detecting) that should build on the completed analysis/ layer.

---

## 10. Pipeline Integration Plan

### Inputs to verifier

```python
verify_structural_repair(
    reconstructed_files: dict[str, str],     # from reconstruction
    case_id: str,                             # case identifier
    model_claims: list[str] | None,           # from artifact.normalized_code_commitments
    artifact_id: str,                          # provenance
)
```

**New vs current:** The only new input is `model_claims`. Currently `check_ast_patterns()` receives only `reconstructed_files` and `case_id`.

### When it runs

Same as current: after reconstruction and execution, before final assembly. Line ~612 in execution_v2.py.

```python
# Current (line 612-626):
ast_result = _run_ast_verification(recon, case, artifact_id)

# Target:
ast_result = _run_ast_verification(recon, case, artifact, artifact_id)
#                                                  ^^^^ now includes model claims
```

### What gets logged

Expanded `ev["ast_eval"]` section:

```json
{
  "status": "measured",
  "checkability": "fully_checkable",
  "ast_truth_alignment": "correct",
  "ast_claim_alignment": "aligned",
  "ast_location_match": true,
  "ast_mechanism_match": true,
  "ast_alternative_valid": false,
  "claims_checked": 2,
  "claims_matched": 2,
  "ast_correct": true,
  "ast_score": 1.0,
  "checker_family": "aliasing",
  "artifact_id": "..."
}
```

### What remains non-gating

Everything. The verifier NEVER gates execution, retry, or classification. It is always a post-hoc analytical signal.

### Should retry ever consult AST?

**No.** AST independence from the intervention loop is a design invariant. If retry used AST results, we'd lose the ability to measure AST's correlation with execution independently. The retry system should continue using test feedback and mismatch critique only.

### Changes needed in other modules

| Module | Change |
|--------|--------|
| `execution_v2.py` | Pass `artifact` to `_run_ast_verification()` for claim access |
| `materialize.py` | Extract new fields: truth_alignment, claim_alignment, location_match, mechanism_match, checkability |
| Analysis scripts | Add new derived metrics (Section 11) |
| Event schema | Add new fields to ev["ast_eval"] |

---

## 11. Metric and Outcome Redesign

### Canonical fields (from VerificationResult)

| Field | Type | Meaning |
|-------|------|---------|
| `ast_checkable` | bool | Is this case AST-measurable at all? |
| `ast_truth_alignment` | str | correct / incorrect / partial / uncheckable |
| `ast_claim_alignment` | str | aligned / misaligned / no_claims / uncheckable |
| `ast_location_match` | bool | Did model change the right file/function? |
| `ast_mechanism_match` | bool | Does patch address the right structural property? |
| `ast_alternative_valid` | bool | Non-canonical but valid repair? |
| `checkability` | str | CheckabilityLevel enum value |

### Derived categories

| Category | Definition | What it means |
|----------|-----------|---------------|
| `structural_reasoning_success` | truth=correct AND exec=pass | Full success at all levels |
| `structural_truth_success` | truth=correct AND exec=fail | Correct structure, runtime failure (LEG_ast) |
| `translation_failure` | claim=aligned AND truth=incorrect | Model's reasoning was right but code doesn't implement it |
| `structural_success_runtime_failure` | truth=correct AND exec=fail AND claims=aligned | The purest execution fidelity signal |
| `noncanonical_valid_repair` | truth=incorrect AND alternative=true AND exec=pass | Valid alternative the spec doesn't capture |
| `wrong_locus` | location_match=false | Model fixed the wrong file/function |
| `mechanism_mismatch` | mechanism_match=false AND location_match=true | Right place, wrong fix type |

### Backward compatibility

Keep `ast_correct` and `ast_score` as computed from `ast_truth_alignment` for backward compatibility. All existing analysis scripts continue to work.

---

## 12. Rollout Phases

### Phase 1: Consolidate and Canonicalize (3-5 days)

**Goal:** Fix INV-02 violation, establish single canonical implementation.

**Tasks:**
1. Delete `scripts/ast_phase1/checkers.py`, `checker_fixes.py`, `checker_fixes_v2.py`
2. Update `retro_eval_full.py`, `retro_eval.py`, `validate_specs.py` to import from `core.evaluation.ast_eval`
3. Create `core/evaluation/ast_verifier/` directory structure
4. Move checkers from `ast_checkers.py` into family-specific modules under `ast_verifier/checkers/`
5. Fold overrides from `ast_checker_overrides.py` into family modules
6. Update `ast_eval.py` to delegate to `ast_verifier/`
7. Add `CheckabilityLevel` enum and reclassify 11 NOT_AST_MEASURABLE cases
8. Run full validation suite — all 47 specs must still pass

**Deliverables:** Single canonical AST subsystem in `core/evaluation/ast_verifier/`. Zero script-side duplicates.

**Validation:** `validate_specs.py` passes 47/47. Full retrospective eval produces identical results.

### Phase 2: Metadata + Result Schema + Claim/Truth Split (5-7 days)

**Goal:** Add structured specs to case metadata, implement claim-aware verification.

**Tasks:**
1. Design and populate `structural_spec` in cases_v2.json for all 58 cases
2. Implement `VerificationResult` with new fields (truth_alignment, claim_alignment, location_match, etc.)
3. Implement `locus_verifier.py` — checks file/function match
4. Implement `claim_verifier.py` — parses code_commitments, checks against patch
5. Update `execution_v2.py` to pass model claims to verifier
6. Update `materialize.py` to extract new fields
7. Update event schema documentation

**Deliverables:** Structural specs for all 58 cases. Claim-aware and truth-aware verification running in pipeline.

**Validation:** Rerun on existing oracle-labeled events. Compute claim-vs-truth agreement. Hand-audit 50 claim alignment results.

### Phase 3: Lightweight Program Analysis + Stronger Checkers (5-7 days)

**Goal:** Add symbol tracking, call resolution, and ordering analysis. Upgrade `not_yet_implemented` cases.

**Tasks:**
1. Implement `analysis/symbol_tracker.py` — variable assignment extraction, name binding tracking
2. Implement `analysis/call_resolver.py` — same-file call target resolution
3. Implement `analysis/ordering.py` — statement ordering with locality bounds
4. Upgrade checkers for: partial_update_b, index_misalign_b/c, silent_default_a/c (the 5 `not_yet_implemented` cases)
5. Strengthen rollback checkers to verify compensation targets correct variable
6. Validate new checkers against ref fixes and buggy code

**Deliverables:** 52/58 AST-measurable cases (up from 47). Symbol-aware checking for rollback family.

**Validation:** validate_specs.py passes 52/52. LUCKY_FIX rate drops further.

### Phase 4: Deep Dependency Chain Integration (7-10 days)

**Goal:** Bring 8 DDC cases into the benchmark with chain-aware checkers.

**Tasks:**
1. Add DDC cases to cases_v2.json with structural_specs (checkability="chain_checkable")
2. Create code_snippets_v2/ directories for each DDC case
3. Create reference_fixes/ for each DDC case
4. Adapt DDC primary tests into tests_v2/ format
5. Implement `ast_verifier/checkers/deep_chain.py` — corruption-site repair + band-aid detection
6. Run validation: root fix passes, traps are correctly detected
7. Run first ablation on DDC cases

**Deliverables:** 66 total cases (58 + 8 DDC). Chain-aware AST verification.

**Validation:** DDC self_validate passes for all 8 cases. AST correctly identifies root fixes vs band-aids.

---

## 13. Validation and Audit Plan

### Oracle-vs-AST comparison
After each phase, rerun `retro_eval_full.py` on the oracle-labeled dataset and recompute:
- Oracle-AST agreement rate (currently 92.2%)
- AST false positive rate (currently ~10% of exec-failing events)
- LUCKY_FIX rate (currently 2.0%)

Target: agreement stays >90%, FP rate drops, LUCKY_FIX drops.

### Hand-audited sample
After Phase 2 (claim verification), hand-audit 100 events:
- 50 where claim_alignment=aligned
- 50 where claim_alignment=misaligned
Verify the claim verifier is actually checking the right thing.

### Alternative repair evaluation
After Phase 2, rerun the lucky-fix audit. Events where `ast_alternative_valid=true` should reduce the LUCKY_FIX bucket further.

### Regression tests
Each checker family gets a regression test file:
- Reference fix → must return truth_alignment=correct
- Buggy code → must return truth_alignment=incorrect
- 2-3 known wrong fixes → must return truth_alignment=incorrect
- 1-2 valid alternatives → must return truth_alignment=correct + alternative_valid=true

### Preventing divergence
After Phase 1, there is only ONE implementation. The scripts/ directory imports from core/. No duplication possible.

---

## 14. Repo Integrity and Invariant Compliance

### Current violations

| Invariant | Current violation | Fix in plan |
|-----------|------------------|-------------|
| **INV-02** Single canonical implementation | Checkers in both scripts/ and core/ | **Phase 1:** Delete scripts/ copies |
| **INV-11** Single source of truth | NOT_AST_MEASURABLE is a Python set, not case metadata | **Phase 2:** Move to structural_spec.checkability in cases_v2.json |
| **INV-13** Metric provenance | AST metrics don't declare trust level | **Phase 2:** VerificationResult includes checkability + checker_family |

### How plan maintains invariants

- **INV-01 (single entry):** Verifier is called through one function: `_run_ast_verification()` in execution_v2.py
- **INV-02 (no duplicates):** Phase 1 eliminates all duplication
- **INV-03 (no silent failures):** Every case gets a result with explicit status (never silently omitted)
- **INV-07 (generation/evaluation separation):** Verifier reads reconstructed code and model claims but never modifies them
- **INV-12 (raw preservation):** Raw verification result is logged in ev["ast_eval"] before any metric derivation

---

## 15. Final Recommendation

### Is this migration worth doing?

**Yes, but in phases.** The current system is already useful (the 3-way decomposition finding is real). The migration makes it more precise and more defensible, but the marginal value decreases after Phase 2.

### Highest ROI subset

**Phase 1 + Phase 2 = the critical 20%.** Phase 1 fixes the invariant violation and establishes clean architecture. Phase 2 adds claim-aware verification — the single biggest conceptual upgrade. Together they take ~10 days and deliver the core of the target verifier.

### What should be implemented first

1. **Consolidate scripts/ → core/ (Phase 1, Step 1-2).** This is a pure cleanup with zero scientific risk.
2. **Add CheckabilityLevel taxonomy (Phase 1, Step 7).** Immediately improves reporting honesty.
3. **Add structural_spec to cases_v2.json (Phase 2, Step 1).** Data-driven verification instead of hardcoded dicts.

### What should absolutely NOT be done

- **Do NOT add full dataflow analysis.** Lightweight symbol tracking (Phase 3) is sufficient. SSA, CFG, or abstract interpretation would be massive overengineering for <5% accuracy gain.
- **Do NOT make AST gating.** The non-gating property is a design invariant. Breaking it would contaminate execution independence.
- **Do NOT treat `not_yet_implemented` as `uncheckable`.** 5 of 11 "unmeasurable" cases are just missing checkers. Separating "haven't built it" from "can't build it" is critical for honest reporting.

### What needs immediate correction

1. **The claim that "AST measures structural reasoning correctness" is overstated.** It measures structural pattern presence. The claim-aware and locus-aware additions in Phase 2 are needed to make it a genuine reasoning verifier.
2. **The scripts/core duplication is an active INV-02 violation.** Fix this week regardless of whether the rest of the plan proceeds.
