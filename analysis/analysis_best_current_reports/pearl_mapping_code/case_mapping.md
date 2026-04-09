# Pearl-Level Remapping Audit for `cases_v2`

## Overview

This document presents a **strict remapping** of all cases in `cases_v2` according to the definition of :contentReference[oaicite:0]{index=0} as operationalized in the *Executable Counterfactuals* paper.

The key takeaway is:

> While the benchmark captures meaningful variation in reasoning depth, **almost all cases fall into Pearl-L1 or Pearl-L2**, and **none qualify as strict Pearl-L3** under the paper’s definition.

---

## Strict Definitions (Paper-Aligned)

### **L1 — Association (Observation Only)**

A task is L1 if:
- The bug can be identified directly from code structure
- No execution reasoning is required
- No causal mechanism simulation is needed

Formally:
- Pattern recognition over syntax is sufficient

---

### **L2 — Intervention (Forward Causal Reasoning)**

A task is L2 if:
- The solver must reason about **what happens when a change occurs**
- Requires understanding **state transitions or propagation**
- Does **not** require reconstructing hidden state from observations

Formally:
- Evaluate: `T(s, f)` and its downstream effects

---

### **L3 — Counterfactual (Abduction + Intervention + Prediction)**

A task is L3 **only if all three are required**:

1. **Abduction** — infer hidden latent state from an observed execution  
2. **Intervention** — modify some input or action  
3. **Prediction** — compute outcome under modified condition while holding latent state fixed  

This is much stricter than “multi-step reasoning.”

---

## Why Most Cases Are Not L3

Your current L3 labeling captures:
- multi-step reasoning
- cross-module dependencies
- temporal state

However, the paper requires something stronger:

> The solver must be forced to **infer hidden state from a concrete observed run**, not just inspect code.

In your benchmark:
- The model can directly read the mechanism from code
- No explicit observed execution trace is required
- No latent variable must be inferred before reasoning

Therefore:
- These tasks are **deep L2 (intervention)**, not true L3

---

## Remapping Table

### L1 Cases

| case_id | current_label | strict_Pearl_label | reason |
|--------|--------------|--------------------|--------|
| alias_config_a | L1 | L1 | local aliasing bug, no hidden state or intervention reasoning |
| partial_update_a | L1 | L1 | local incomplete update, direct observation |
| stale_cache_a | L1 | L1 | stale read visible from local logic |
| lazy_init_a | L1 | L1 | initialization ordering local |
| mutable_default_a | L1 | L1 | classic Python local bug |
| effect_order_a | L1 | L1 | local sequencing error |
| use_before_set_a | L1 | L1 | direct invariant violation |
| retry_dup_a | L1 | L1 | duplicate execution visible locally |
| partial_rollback_a | L1 | L1 | rollback incomplete but local |
| temporal_drift_a | L1 | L1 | drift observable without latent inference |
| missing_branch_a | L1 | L1 | missing conditional branch |
| wrong_condition_a | L1 | L1 | incorrect predicate |
| early_return_a | L1 | L1 | premature return |
| index_misalign_a | L1 | L1 | indexing mismatch local |
| silent_default_a | L1 | L1 | fallback behavior explicit |
| derived_field_stale_a_plus | L1 | L1 | stale derived field local |

---

### L2 Cases (Includes All Deep Cases)

| case_id | current_label | strict_Pearl_label | reason |
|--------|--------------|--------------------|--------|
| alias_config_b | L2 | L2 | cross-call mutation propagation |
| partial_update_b | L2 | L2 | multi-step propagation |
| stale_cache_b | L2 | L2 | cache invalidation reasoning |
| lazy_init_b | L2 | L2 | cross-function dependency |
| mutable_default_b | L2 | L2 | shared state across calls |
| effect_order_b | L2 | L2 | ordering affects downstream |
| use_before_set_b | L2 | L2 | dependency propagation |
| retry_dup_b | L2 | L2 | retry semantics |
| partial_rollback_b | L2 | L2 | rollback interaction |
| temporal_drift_b | L2 | L2 | evolving state |
| missing_branch_b | L2 | L2 | pipeline omission |
| wrong_condition_b | L2 | L2 | incorrect guard |
| early_return_b | L2 | L2 | early exit propagation |
| index_misalign_b | L2 | L2 | propagated misalignment |
| silent_default_b | L2 | L2 | fallback propagation |

---

### Deep Cases (All Collapse to L2)

| case_id | current_label | strict_Pearl_label | reason |
|--------|--------------|--------------------|--------|
| cache_invalidation_order | C | L2 | ordering + dependency |
| feature_flag_drift | C | L2 | flag propagation |
| invariant_partial_fail | C | L2 | multi-step invariant |
| async_race_lock | C | L2 | concurrency ordering |
| hidden_dep_multihop | C | L2 | multi-hop reasoning only |
| overdetermination | C | L2 | multiple causes, no abduction |
| lost_update | C | L2 | race condition |
| check_then_act | C | L2 | TOCTOU |
| ordering_dependency | C | L2 | order-sensitive |
| false_fix_deadlock | C | L2 | intervention failure |
| duplicate_write_deep_dependency_chain_c | C | L2 | deep chain |
| transform_pipeline_unit_drift_c_v3 | C | L2 | representation drift |
| deferred_commit_selector_split_b_plus | B+ | L2 | mismatch reasoning |
| duplicate_write_retry_hidden_b_plus | B+ | L2 | retry interaction |
| duplicate_write_retry_hidden_b_plus_adv | B+ | L2 | adversarial variant |
| derived_field_stale_b_plus | B+ | L2 | stale propagation |
| versioned_policy_fallback_regression_b | B | L2 | fallback behavior |
| versioned_policy_fallback_regression_b_plus | B+ | L2 | complex fallback |
| versioned_policy_fallback_regression_b_plus_adv | B+ | L2 | adversarial |

---

### Former L3 Cases (Downgraded)

| case_id | current_label | strict_Pearl_label | reason |
|--------|--------------|--------------------|--------|
| alias_config_c | L3 | L2 | sequence-dependent only |
| partial_update_c | L3 | L2 | multi-step propagation |
| stale_cache_c | L3 | L2 | cache chain |
| lazy_init_c | L3 | L2 | cross-request state |
| mutable_default_c | L3 | L2 | shared state |
| effect_order_c | L3 | L2 | ordering only |
| use_before_set_c | L3 | L2 | dependency chain |
| retry_dup_c | L3 | L2 | retry effects |
| partial_rollback_c | L3 | L2 | rollback propagation |
| temporal_drift_c | L3 | L2 | temporal evolution |
| missing_branch_c | L3 | L2 | pipeline omission |
| wrong_condition_c | L3 | L2 | branching |
| early_return_c | L3 | L2 | early exit |
| index_misalign_c | L3 | L2 | propagation |
| silent_default_c | L3 | L2 | fallback |

---

### Near-L3 Candidates

| case_id | current_label | strict_Pearl_label | reason |
|--------|--------------|--------------------|--------|
| versioned_policy_fallback_regression_l3 | L3 | L2 (near-L3) | hidden state implied |
| write_through_shadow_cache_l3_gold | L3 | L2 (near-L3) | latent cache state |
| duplicate_write_competing_c_v2 | L3 | L2 (near-L3) | competing writes |

---

## How to Upgrade Cases to True L3

To convert a case into strict Pearl-L3, you must:

### Add an observed execution trace
- Example: “Request A produced output Y”

### Introduce hidden latent state
- Not directly visible in code
- Must be inferred (e.g., cache contents, prior mutation)

### Ask a counterfactual question
- “What would have happened if X were different?”

---

### Example Transformation

Current:
> Fix the bug in a caching system

True L3:
> Given this observed output and logs, what would the output have been if cache invalidation had occurred earlier, assuming the same hidden cache state?

---

## Final Conclusion

- Your benchmark **does capture reasoning depth**
- But it primarily spans:
  - **L1 (pattern recognition)**
  - **L2 (intervention reasoning)**

- What you currently call “L3” is:
  > **deep, stateful, multi-hop intervention reasoning**

- True Pearl-L3 requires:
  > **abduction over hidden state + counterfactual simulation**

---

## Strategic Insight

This is not a weakness—it’s an opportunity.

You are positioned to:

> Introduce the first benchmark that cleanly separates  
> deep interventional reasoning from true counterfactual reasoning in code

That’s a strong, publishable contribution.