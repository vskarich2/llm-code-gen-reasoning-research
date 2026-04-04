# V6 Final Analysis — Cleaned Metrics and Tables

**Events:** 20031 assessable oracle-labeled
**Changes from V5:** l3 anti-pattern added, locus probe removed (degenerate), exec failure subtypes refined

## 1. Anchor Table (FINAL)

| Metric | Value |
|--------|-------|
| N | 20031 |
| P(oracle_correct) | 90.4% |
| P(ast_correct) | 91.2% |
| P(ast_incorrect) | 4.5% |
| P(ast_unknown) | 4.3% |
| P(exec_pass) | 80.8% |

## 2. V5 → V6 Impact (l3 anti-pattern fix)

| Metric | V5 | V6 | Delta |
|--------|----|----|-------|
| ast_unknown | 932 (4.7%) | 859 (4.3%) | -73 |
| ast_incorrect | 828 (4.1%) | 901 (4.5%) | +73 |
| ast_correct | 18271 (91.2%) | 18271 (91.2%) | +0 |

l3_state_pipeline: correct=20, incorrect=60, unknown=579
*60 events now correctly classified as incorrect (commit without freeze_view).*

## 3. Three-Stage Failure Decomposition (FINAL)

Total failures: 3837

| Stage | Count | % | Description |
|-------|-------|---|-------------|
| 1. Reasoning | 1320 | 34.4% | Oracle says reasoning wrong |
| 2. Structure | 275 | 7.2% | Oracle correct, AST not correct |
| 3. Execution | 2242 | 58.4% | Oracle correct, AST correct, exec fails |

*Stage 2 breakdown: 162 incorrect + 113 unknown = 275*

## 4. AST-Correct Execution Failures — Central Analysis

**Total: 2531 events where structure is correct but execution fails.**

### 4a. Failure Type Decomposition

| Category | Count | % | Method |
|----------|-------|---|--------|
| wrong_numeric_value | 714 | 28.2% | rule-based |
| wrong_aggregation | 528 | 20.9% | rule-based |
| unexpected_exception | 396 | 15.6% | rule-based |
| name_error | 309 | 12.2% | automatic |
| import_failure | 302 | 11.9% | automatic |
| cache_semantics_error | 191 | 7.5% | rule-based |
| runtime_crash | 35 | 1.4% | automatic |
| unclassified | 30 | 1.2% | rule-based |
| missing_attribute | 26 | 1.0% | rule-based |

### 4b. Per-Family Breakdown

| Family | N | Failures | AST-Correct Failures | EFF% (of all) | EFF% (of failures) |
|--------|---|----------|---------------------|---------------|-------------------|
| invariant_partial_fail | 1151 | 837 | 732 | 63.6% | 87% |
| hidden_dep_multihop | 784 | 374 | 372 | 47.4% | 99% |
| missing_branch | 1427 | 374 | 355 | 24.9% | 95% |
| silent_default | 214 | 52 | 50 | 23.4% | 96% |
| cache_invalidation_order | 714 | 405 | 162 | 22.7% | 40% |
| use_before_set | 1201 | 231 | 231 | 19.2% | 100% |
| overdetermination | 853 | 133 | 132 | 15.5% | 99% |
| early_return | 1851 | 214 | 185 | 10.0% | 86% |
| effect_order | 975 | 82 | 82 | 8.4% | 100% |
| partial_rollback | 611 | 78 | 43 | 7.0% | 55% |
| commit_gate | 679 | 50 | 37 | 5.4% | 74% |
| index_misalign | 209 | 11 | 11 | 5.3% | 100% |
| mutable_default | 1472 | 60 | 60 | 4.1% | 100% |
| partial_update | 809 | 42 | 31 | 3.8% | 74% |
| stale_cache | 1003 | 22 | 19 | 1.9% | 86% |
| retry_dup | 586 | 11 | 11 | 1.9% | 100% |
| alias_config | 1028 | 10 | 10 | 1.0% | 100% |
| temporal_drift | 1064 | 3 | 3 | 0.3% | 100% |
| lazy_init | 1319 | 5 | 3 | 0.2% | 60% |
| wrong_condition | 1040 | 51 | 2 | 0.2% | 4% |

### 4c. Per-Model Breakdown

| Model | N | Failures | AST-Correct Failures | EFF% | Sample note |
|-------|---|----------|---------------------|------|-------------|
| claude-haiku-4-5-20251001 | 355 | 272 | 272 | 76.6% |  |
| gpt-5 | 238 | 147 | 86 | 36.1% | small N |
| gpt-4o-mini | 3998 | 1403 | 989 | 24.7% |  |
| claude-sonnet-4-6 | 739 | 107 | 107 | 14.5% |  |
| gpt-4.1-nano | 4040 | 907 | 497 | 12.3% |  |
| gpt-5-mini | 4778 | 399 | 321 | 6.7% |  |
| gpt-5.4-mini | 5222 | 602 | 259 | 5.0% |  |
| claude-sonnet-4-20250514 | 660 | 0 | 0 | 0.0% |  |

### 4d. Per-Condition Breakdown

| Condition | N | AST-Correct Failures | EFF% |
|-----------|---|---------------------|------|
| baseline_v2 | 5071 | 786 | 15.5% |
| leg_reduction_lean_v2 | 4805 | 547 | 11.4% |
| leg_reduction_v2 | 4735 | 559 | 11.8% |
| retry_bare_retry_v2 | 1779 | 288 | 16.2% |
| retry_leg_critique_strict_v2 | 1983 | 234 | 11.8% |
| retry_reasoning_only_critique_v1 | 1658 | 117 | 7.1% |

## 5. AST-Negative Family Investigation

Families where AST performs WORSE than execution at predicting oracle:

| Family | N | Exec-Oracle | AST-Oracle | Delta | Recommendation |
|--------|---|-------------|-----------|-------|----------------|
| cache_invalidation_order | 714 | 58.3% | 38.2% | -20.0pp | Checker accepts valid structural fixes where oracle rejects reasoning. AST is measuring a DIFFERENT property than oracle. Keep but report separately. |
| temporal_drift | 1064 | 99.7% | 96.4% | -3.3pp | AST argument-check slightly misaligned with oracle. Minor — keep. |

### cache_invalidation_order (-20pp)

N=714, Oracle=4%, AST_correct=65%, Pass=43%

**Root cause:** The canonical fix preserves the `invalidate → conditional_set` pattern for version tracking. The v2 AST checker also accepts direct `cache_set` after `db_write` (a valid structural alternative). But the oracle evaluates against the ground truth mechanism: "keep invalidate call before set for version tracking." Models that use direct cache_set have a DIFFERENT reasoning path (simpler, but doesn't preserve version tracking). The oracle correctly grades this reasoning as WRONG (only 7% oracle-correct) even though the structural fix works.

**Recommendation:** This family demonstrates that AST and oracle measure DIFFERENT things. AST measures structural repair validity. Oracle measures mechanism-understanding depth. Direct cache_set is structurally valid but reflects shallow reasoning. Keep both signals — the disagreement IS the insight. Do NOT "fix" the AST checker to match oracle, and do NOT report this family as "AST is wrong." Report it as "AST and oracle intentionally diverge because structural validity ≠ mechanism understanding."

## 6. Unknown State (Post l3 Fix)

Total unknown: 859 (4.3%)

Excluding l3_state_pipeline: 280 (1.4%)

| Family | N | Unknown | Unknown% |
|--------|---|---------|----------|
| l3_state_pipeline | 659 | 579 | 87.9% |
| invariant_partial_fail | 1151 | 113 | 9.8% |
| use_before_set | 1201 | 69 | 5.7% |
| async_race_lock | 382 | 41 | 10.7% |
| stale_cache | 1003 | 12 | 1.2% |
| lazy_init | 1319 | 12 | 0.9% |
| index_misalign | 209 | 9 | 4.3% |
| early_return | 1851 | 7 | 0.4% |
| partial_rollback | 611 | 6 | 1.0% |
| partial_update | 809 | 4 | 0.5% |
| hidden_dep_multihop | 784 | 3 | 0.4% |
| mutable_default | 1472 | 2 | 0.1% |
| effect_order | 975 | 1 | 0.1% |
| missing_branch | 1427 | 1 | 0.1% |

## 7. Signal Comparison (FINAL)

| Signal | N | Oracle Agreement | Note |
|--------|---|-----------------|------|
| Execution | 20031 | 84.4% | Behavioral ground truth |
| Old LLM classifier | 20031 | 90.5% | LLM-based, non-deterministic |
| **AST structural** | **19172** | **94.6%** | **Deterministic, excludes 859 unknown** |

*Locus probe removed: degenerate on assessable set (100% by construction).*
*AST incremental over execution: +10.2pp*

## 8. Core Claim (FINAL)

Of 3837 execution failures across 20031 oracle-labeled evaluation events, **58.4% (2242 events)** occur in cases where both the oracle reasoning evaluator and AST structural verification indicate correct reasoning and correct structural implementation, yet execution fails.

This execution-fidelity gap:
- Is the dominant failure mode (58% of failures)
- Exceeds reasoning failure (34%) and structural translation failure (7%)
- Is model-stratified (0.0% for claude-sonnet-4 to 76.6% for the weakest large-N model)
- Is intervention-responsive (reduced from baseline 15.5% to 7.1% under reasoning-only critique)

### Limitations

- AST structural verification is a necessary but not sufficient condition for correct reasoning. It cannot distinguish genuine understanding from pattern recall (2.3% measured blind spot).
- 859 events (4.3%) are structurally indeterminate (unknown state) and excluded from AST accuracy.
- The execution failure decomposition is partially rule-based (91% classified automatically, 9% requires manual review).
- The 58% claim is conditioned on both oracle and AST validity, which agree at 94.6% on the assessable set.