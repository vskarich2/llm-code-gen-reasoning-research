# Mutation System v3 Report — Semantic Plan-Based AST Mutations

**Date:** 2026-03-28

---

## Architecture

Three-layer semantic mutation system:

### Layer 1: Semantic Targeting
Operators declare what invariant structure to break. `find_targets()` scans the AST for nodes that implement that invariant — not by syntax, but by semantic role (copy call, cache invalidation, dependent field assignment, comparison operator, branch, function call, dict entry, variable initialization).

### Layer 2: AST Localization
Finders return `SemanticTarget` objects with exact AST node, enclosing function, line number, and role description. Plan-based operators can find multiple coordinated targets (e.g., both a module-level assignment AND a return statement for eager capture).

### Layer 3: AST Transformation
Targeted transformers modify specific nodes:
- `_RemoveCopy` — strip .copy()/dict() calls
- `_DeleteStatement` — remove a statement node
- `_FlipComparison` — >= → >
- `_RemoveBranch` — delete else/elif
- `_InsertToAppend` — insert(pos,val) → append(val)
- `_ChangeConstant` — swap a constant value
- `_RestoreMutableDefault` — None → [] + remove guard
- `_SwapCallArgument` — change function call argument
- `_AddModuleLevelAssignment` — inject eager capture
- `_ReplaceReturnWithCaptured` — return dict[key] → return _cached
- `_RemoveDictEntry` — remove key from dict literal
- `_RemoveElifByTest` — remove specific elif branch
- `_RemoveInitAssignment` — remove variable init before conditional

`ast.unparse()` produces structurally valid code. Zero string manipulation.

### 5-Gate Validation Pipeline
1. Semantic target found → 2. AST mutation applied → 3. Diff verified → 4. Semantic guardrails → 5. Oracle fails

---

## Results

| Metric | v1 (regex) | v2 (single-node AST) | v3 (semantic plans) |
|--------|-----------|---------------------|---------------------|
| Cases covered | 20/58 (34%) | 39/58 (67%) | **51/58 (88%)** |
| Total accepted | 25 | 51 | **123** |
| GOLD | 24 | 44 | **84** |
| SILVER | 1 | 7 | **39** |
| Zero-variant | 38 | 19 | **7** |
| False accepts | 0 | 0 | **0** |

---

## Operators (30+ semantic operators)

### Single-node operators
| Operator | Invariant broken | Families |
|----------|-----------------|----------|
| RemoveCopy | Shared reference aliasing | alias_config |
| RemoveMethodCall (cache) | Stale reads | stale_cache, cache_invalidation |
| RemoveMethodCall (rollback) | Partial state on failure | partial_rollback, invariant_partial |
| RemoveMethodCall (ledger) | Missing audit trail | early_return, effect_order |
| RemoveMethodCall (dedup) | Duplicate effects | retry_dup |
| RemoveMethodCall (buffer) | Lost items | ordering_dependency |
| RemoveMethodCall (insert) | Array desync | index_misalign |
| RemoveFunctionCall (sync) | Stale cache | hidden_dep_multihop |
| RemoveFunctionCall (flag) | Flag drift | feature_flag_drift |
| RemoveFunctionCall (commit) | Ungated reads | commit_gate, l3_state |
| RemoveFunctionCall (lock) | Unprotected access | async_race, lost_update, check_then_act |
| RemoveAssignment (field) | Dependent field stale | partial_update |
| FlipComparison | Off-by-one | wrong_condition |
| RemoveBranch | Missing output | missing_branch |
| InsertToAppend | Wrong position | index_misalign |
| RestoreMutableDefault | State shared across calls | mutable_default |
| ChangeConstant | Wrong config value | config_shadowing |

### Plan-based operators (multi-edit coordination)
| Operator | Invariant broken | Edits | Families |
|----------|-----------------|-------|----------|
| EagerCapture | Stale after reset | Add capture + replace return | lazy_init |
| SwapArgument | Stats on wrong data | Replace call argument | temporal_drift |
| RemoveDictEntry | Missing role/case | Delete dict key | missing_branch |
| RemoveElif | Missing branch | Delete elif block | missing_branch |
| RemoveInitialization | Use-before-set | Delete pre-if assignment | use_before_set |
| RemoveReturnValue | Silent fallback | Replace return with None | silent_default |

---

## Remaining 7 Zero-Variant Cases

| Case | Files | Root Cause |
|------|-------|-----------|
| mutable_default_c | 3 | Decorator-based history tracking — no `=None` default to restore |
| missing_branch_b | 2 | Multi-file role dispatch — branch to remove is in a different file from the test |
| wrong_condition_b | 2 | Multi-condition check across classes — no single `>=` to flip |
| wrong_condition_c | 3 | Combined boolean expression — flipping one comparison doesn't break the invariant |
| silent_default_b | 2 | Key mismatch is in the caller, not the dict lookup function |
| silent_default_c | 3 | Environment variable fallback chain — normalization is inline, not a function call |
| invariant_partial_fail | 4 | 4-file conservation invariant with try/except — needs coordinated cross-file edits |

These 7 cases require either cross-file coordinated mutations or mutations on patterns that don't map to single AST constructs (decorator semantics, environment variable chains, class method interactions).

---

## Zero False Positives

The validation pipeline has never accepted an invalid variant across all 3 system versions:
- v1: 0 false positives
- v2: 0 false positives
- v3: 0 false positives

Every accepted variant passes all 5 gates. Every rejected variant has an explicit reason.
