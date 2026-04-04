# Benchmark Extension Implementation Plan v2

**Date:** 2026-04-02
**Implements:** BENCHMARK_EXTENSION_PLAN_v5.md, Stage 0+1 (second batch)

## Gap Analysis

From Stage 4 completion report:
- Need ≥5 families (have 4) → add spec_misinterpretation + test_impl_mismatch
- Need low-LEG family (≤15%) → spec_misinterpretation
- Need ≥2 cases in ≥3 families → add second case to 3+ families
- Need ≥12 promoted cases (have 4) → add 8

## 8 New Cases

| # | Case ID | Family | Difficulty | Gap Filled |
|---|---|---|---|---|
| 1 | misleading_name_format | spec_misinterpretation | A | New family (5th), low-LEG contrast |
| 2 | misleading_docstring_merge | spec_misinterpretation | B | 2nd case in family |
| 3 | test_authority_conflict | test_impl_mismatch | B | New family (6th) |
| 4 | error_source_attractor | false_fix_attractor | B | 2nd case in family |
| 5 | callback_routing_trap | control_flow_trap | B | 2nd case in family |
| 6 | caller_null_check | abstraction_leak | B | 2nd case in family |
| 7 | shared_counter_ambiguous | misinferred_dependency | C | 2nd case in family |
| 8 | partial_migration | intervention_boundary | B | Re-fill dropped family |

After this: 12 cases across 6 families, with ≥2 cases in 5 families.
