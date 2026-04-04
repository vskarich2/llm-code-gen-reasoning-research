# V5 Analysis Results

**Events:** 20031 assessable + oracle-labeled

## 1. Anchor Table

| Metric | Value |
|--------|-------|
| N (assessable + oracle) | 20031 |
| P(oracle_correct) | 90.4% |
| P(ast_correct) | 91.2% |
| P(ast_incorrect) | 4.1% |
| P(ast_unknown) | 4.7% (estimate) |
| P(exec_pass) | 80.8% |
| P(locus_match) | 100.0% (of assessable) |

## 2. Three-Stage Failure Decomposition

Total failures: 3837

| Stage | Count | % | Description |
|-------|-------|---|-------------|
| 1. Reasoning | 1320 | 34.4% | Oracle says reasoning wrong |
| 2. Structure | 275 | 7.2% | Oracle correct, AST not correct |
| 3. Execution | 2242 | 58.4% | Oracle correct, AST correct, exec fails |

*Note: Stage 2 includes 126 events classified as AST "unknown" (structurally indeterminate).*

## 3. Execution Failure Decomposition (AST-correct failures)

Total AST-correct execution failures: 2531

| Category | Count | % | Classification |
|----------|-------|---|---------------|
| wrong_value_literal | 1242 | 49.1% | rule-based |
| unexpected_exception | 378 | 14.9% | rule-based |
| name_error | 309 | 12.2% | automatic |
| import_failure | 302 | 11.9% | automatic |
| unclassified_invariant | 239 | 9.4% | manual review needed |
| runtime_crash | 35 | 1.4% | automatic |
| missing_attribute | 26 | 1.0% | rule-based |

## 4. Unknown State Analysis

Total unknown: 932 (4.7%) — estimate, pending rule validation

| Unknown × Exec | Count | Interpretation |
|----------------|-------|----------------|
| unknown + exec_pass | 355 | Alternative repair candidate |
| unknown + exec_fail | 577 | Structurally indeterminate failure |

### Per-family unknown rate

| Family | N | Unknown | Unknown% |
|--------|---|---------|----------|
| l3_state_pipeline | 659 | 639 | 97.0% |
| async_race_lock | 382 | 41 | 10.7% |
| invariant_partial_fail | 1151 | 113 | 9.8% |
| use_before_set | 1201 | 69 | 5.7% |
| index_misalign | 209 | 9 | 4.3% |
| commit_gate | 679 | 13 | 1.9% |
| stale_cache | 1003 | 12 | 1.2% |
| partial_rollback | 611 | 6 | 1.0% |
| lazy_init | 1319 | 12 | 0.9% |
| partial_update | 809 | 4 | 0.5% |
| hidden_dep_multihop | 784 | 3 | 0.4% |
| early_return | 1851 | 7 | 0.4% |
| mutable_default | 1472 | 2 | 0.1% |
| effect_order | 975 | 1 | 0.1% |
| missing_branch | 1427 | 1 | 0.1% |

## 5. Locus Verification

Assessable for locus: 20031
Locus match: 20031 (100.0%)
Locus mismatch: 0 (0.0%)

Locus mismatch + exec_pass: 0 (cross-layer or wrong-file fix that passes)
Locus mismatch + exec_fail: 0 (wrong location + failure)

## 6. Baseline Comparison: Locus Probe vs Full AST

Oracle agreement rates (measured):

| Signal | N | Oracle Agreement | Status |
|--------|---|-----------------|--------|
| Execution only | 20031 | 84.4% | Measured |
| Old LLM classifier | 20031 | 90.5% | Measured |
| Locus probe | 20031 | 90.4% | Measured |
| Full AST (excl. unknown) | 19099 | 94.8% | Measured |

AST incremental over execution: +10.4pp
AST incremental over locus probe: +4.5pp
Locus incremental over execution: +6.0pp

## 7. By Condition

| Condition | N | Oracle% | AST_correct% | Unknown% | Pass% | ExecFidelityFail% |
|-----------|---|---------|-------------|---------|-------|-------------------|
| baseline_v2 | 5071 | 90.7% | 91.1% | 4.6% | 77.3% | 14.2% |
| leg_reduction_lean_v2 | 4805 | 89.9% | 91.5% | 4.3% | 81.9% | 9.8% |
| leg_reduction_v2 | 4735 | 91.1% | 91.8% | 4.9% | 82.3% | 9.8% |
| retry_bare_retry_v2 | 1779 | 87.6% | 88.2% | 5.6% | 74.5% | 15.1% |
| retry_leg_critique_strict_v2 | 1983 | 88.6% | 90.2% | 4.8% | 81.5% | 10.6% |
| retry_reasoning_only_critique_v1 | 1658 | 93.7% | 93.5% | 4.0% | 90.3% | 6.7% |

## 8. By Model

| Model | N | Oracle% | AST_correct% | Unknown% | Pass% | ExecFidelityFail% |
|-------|---|---------|-------------|---------|-------|-------------------|
| claude-haiku-4-5-20251001 | 355 | 90.7% | 99.2% | 0.8% | 23.4% | 68.5% |
| claude-sonnet-4-20250514 | 660 | 100.0% | 100.0% | 0.0% | 100.0% | 0.0% |
| claude-sonnet-4-6 | 739 | 97.0% | 100.0% | 0.0% | 85.5% | 12.2% |
| gpt-4.1-nano | 4040 | 87.1% | 88.9% | 5.6% | 77.5% | 9.3% |
| gpt-4o-mini | 3998 | 88.0% | 89.2% | 6.8% | 64.9% | 22.2% |
| gpt-5 | 238 | 73.1% | 74.4% | 1.3% | 38.2% | 34.0% |
| gpt-5-mini | 4778 | 93.8% | 92.7% | 4.6% | 91.6% | 6.5% |
| gpt-5.4-mini | 5222 | 90.1% | 91.0% | 4.0% | 88.5% | 4.8% |

## 9. Core Claim (Precise)

Of 3837 execution failures across 20031 oracle-labeled evaluation events, 58.4% (2242 events) occur in cases where both the oracle reasoning evaluator and AST structural verification indicate correct reasoning and correct structural implementation, yet execution fails. This execution-fidelity gap is the dominant failure mode, exceeding reasoning failure (34.4%) and structural translation failure (7.2%).