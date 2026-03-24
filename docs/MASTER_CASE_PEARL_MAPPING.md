# Master Case-to-Pearl's Ladder Mapping

## T3 Benchmark: Causal Reasoning Levels and Trap Families for 51 Code Generation Cases

**Version:** 4.1
**Date:** 2026-03-24
**Scope:** 45 V2 original + 6 V1 hard + 7 new (L3/concurrency/overdetermination) = 58 cases

---

## 1. Theoretical Framework

### 1.1 Pearl's Ladder of Causation

Judea Pearl's causal hierarchy distinguishes three qualitatively different reasoning tasks. In this benchmark, they correspond to what an LLM must do to correctly identify and fix a bug in source code.

| Level | Name | Formal Query | Cognitive Task | Required Reasoning | Discriminating Test |
|-------|------|-------------|----------------|-------------------|---------------------|
| **L1** | Association | P(Y\|X) | "Seeing" | Pattern recognition. The model recognizes the bug shape from training data (e.g., mutable default argument, missing `.copy()`). No causal model required. | Can the model solve this by recalling a known pattern? |
| **L2** | Intervention | P(Y\|do(X)) | "Doing" | Causal graph reasoning. The model must trace how a proposed change (`do(X)`) propagates effects through the system. Includes: multi-step state propagation, cross-module tracing, branching path analysis, mechanism verification, and evaluation of competing intervention strategies. | Can the model solve this by tracking what happens step-by-step when a change is applied? |
| **L3** | Counterfactual | P(Y_x\|X',Y') | "Imagining" | Causal necessity via but-for reasoning. The model must evaluate alternative execution histories: if a prior cause X were absent, would outcome Y change? Requires constructing competing worlds, establishing but-for dependence, and comparing outcomes to determine whether a specific step is causally necessary for a specific downstream invariant. | Does the model need to determine whether a step is **causally necessary** — i.e., but for that step, would the invariant still hold? |

**The L2/L3 boundary in code reasoning:**

L2 asks: *"What happens if I apply this change?"* — forward simulation of an intervention through the causal graph.

L3 asks: *"Is this step causally necessary? Would the system still work if this step were absent?"* — evaluation of causal necessity by comparing competing execution histories.

The distinction is precise: L2 evaluates the **effect of an action**; L3 evaluates the **necessity of an existing cause**. A case is L3 when the model must apply a but-for test: *if X had not occurred, would Y have changed?* This does not require partial observability — it can arise under full source code visibility whenever the task demands reasoning about causal necessity rather than causal effect.

### 1.2 Trap Families (T3-L2 Framework)

Each case embeds a causal trap — a structural pattern that misleads the model into an incorrect or incomplete fix.

| Family | Name | Core Causal Failure |
|--------|------|---------------------|
| **F1** | Selection Effects | Model observes only a subset of execution paths. Missing paths (failure, edge case, unhandled role) leave no trace in the code. |
| **F2** | Statistical Artifacts | Model reasons at aggregate (batch) level and misapplies the conclusion to individual items. Per-item invariants are violated. |
| **F3** | Confounding | A hidden shared variable (mutable default, global dict, closure) creates spurious coupling between operations that appear independent. |
| **F4** | Direction Errors | Model misidentifies the causal direction. It patches the downstream effect site instead of the upstream cause. |
| **F5** | Information Bias | Silent measurement error — `.get()` with a wrong key, a mismatched variable name — produces a plausible but incorrect value without signaling error. |
| **F6** | Mechanism Failures | Model identifies the correct causal variable but intervenes via a mechanism that is disconnected from the broken pathway. The "fix" exists in the code but does not reach the bug. |

### 1.3 Difficulty-to-Pearl Mapping

| Difficulty | Pearl Level | Expected Regime | Description |
|------------|-------------|-----------------|-------------|
| **Level A** (easy) | L1 / L1-L2 boundary | Heuristic | Solvable by pattern matching. Single file, direct causation. |
| **Level B** (medium) | L2 | REI | Must trace do(change) across one function or file boundary. |
| **Level C** (hard) | L2 (deep) | CSF-L2 | Must trace multi-step causal propagation across multiple modules. Verify mechanism correctness under traps. |
| **V1 hard** | L2 (deep) / L3 | CSF-L2 or CSF-L3 | 3–5 file, multi-hop. Rare cases require but-for causal necessity reasoning (L3). |

### 1.4 Regime Definitions

| Regime | Pearl Transition | Meaning |
|--------|-----------------|---------|
| **Heuristic** | Succeeds at L1 | Pattern matching suffices. The model recognizes the bug from training data. |
| **REI** | Fails at L1→L2 | The model identifies the bug in reasoning but fails to implement the correct intervention in code. |
| **CSF-L2** | Fails within deep L2 | The model cannot propagate multi-module state correctly through mechanism traps. It may fix one layer but miss cascading effects across modules. |
| **CSF-L3** | Fails at L2→L3 | The model cannot evaluate causal necessity — it cannot determine whether a step is required by applying the but-for test across competing execution histories. |

---

## 2. V2 Case Mapping (45 Cases)

### Family 1: alias_config (implicit_schema)

**Bug:** DEFAULTS dict returned by reference. Caller mutation corrupts global state.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `alias_config_A` | A | L1 | F3 | Shared `DEFAULTS` object links callers | do(copy) severs shared reference | Each call gets independent dict | Not L3: pattern match `.copy()` |
| `alias_config_B` | B | L1-L2 | F3 | Reference propagates config→app via `_cached_settings` | do(copy in create_config) | Same | Not L3: deterministic reference tracing across 2 files |
| `alias_config_C` | C | L2 | F3 | 3-file chain: config→middleware→handler. Mutation propagates back to DEFAULTS | do(copy in create_config) | Each request gets independent config | Not L3: multi-hop reference tracing, each step deterministic |

---

### Family 2: partial_update (partial_state_update)

**Bug:** Multi-field update misses a dependent field.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `partial_update_A` | A | L1 | F1 | `name` updated, `display_name` not synced | do(add display_name sync) | Dependent fields consistent | Not L3: spot missing sync |
| `partial_update_B` | B | L2 | F1+F6 | `full_name` not recomputed. Validator distractor | do(recompute full_name) — not do(fix validator) | full_name = first + " " + last | Not L3: forward trace of update path |
| `partial_update_C` | C | L2 (deep) | F6 | Email updated, verified not reset. Validator runs but checks format only | do(add verified=False) — not do(fix validator) | Email change invalidates verification | Not L3: deterministic state tracing under mechanism trap |

---

### Family 3: stale_cache (hidden_dependency)

**Bug:** Cache not invalidated after DB write.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `stale_cache_A` | A | L1 | F1 | DB updated, cache not cleared | do(add invalidate) | get returns current data after update | Not L3: spot missing call |
| `stale_cache_B` | B | L2 | F1 | Missing cross-file invalidation. Distractor: `warm()` | do(call invalidate in update_product) | Same | Not L3: cross-file trace |
| `stale_cache_C` | C | L2 (deep) | F1 | Two-layer cache. Shared invalidated, local not | do(invalidate local layer) | Same | Not L3: trace write→read through both layers |

---

### Family 4: lazy_init (execution_model_mismatch)

**Bug:** Eager capture at import time breaks reset lifecycle.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `lazy_init_A` | A | L1 | F4 | Settings loaded eagerly at module level | do(lazy load) | reset affects subsequent reads | Not L3: direction error, not counterfactual |
| `lazy_init_B` | B | L2 | F6 | Client captures config at import. Reset doesn't propagate | do(lazy access in client) | Same | Not L3: lifecycle tracing |
| `lazy_init_C` | C | L2 (deep) | F6 | Config→client→handler chain. refresh() exists but handler doesn't call it | do(lazy access) or do(call refresh) | Same | Not L3: 3-file lifecycle trace, mechanism disconnected |

---

### Family 5: mutable_default (retry_state_accumulation)

**Bug:** `def f(items=[])` accumulates state across calls.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `mutable_default_A` | A | L1 | F3 | `queue=[]` shared across calls | do(None default + create inside) | Each call starts fresh | Not L3: classic pattern |
| `mutable_default_B` | B | L1-L2 | F3 | `seen=set()` persists across calls in 2 files | Same fix, harder to locate | Each batch independent | Not L3: same antipattern, cross-file |
| `mutable_default_C` | C | L2 | F3 | Decorator default `history=_shared_log` binds at decoration time | do(None default inside decorator) | Each function has independent history | Not L3: multi-hop through decorator mechanism, deterministic |

---

### Family 6: effect_order (hidden_dependency)

**Bug:** Side effect at batch level instead of per-item.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `effect_order_A` | A | L1 | F2 | Snapshot after loop, not inside | do(move inside loop) | One snapshot per item | Not L3: spot loop placement |
| `effect_order_B` | B | L2 | F2 | emit_event outside loop across 2 files | do(move inside loop) | len(events) == len(items) | Not L3: cross-file loop trace |
| `effect_order_C` | C | L2 (deep) | F2+F6 | audit_log at batch level. Distractor: fast_process legitimately batches | do(move audit inside loop) — not do(use fast_process) | Per-item audit entries | Not L3: mechanism trap, forward trace |

---

### Family 7: use_before_set (edge_case_omission)

**Bug:** Variable read before assignment on conditional path.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `use_before_set_A` | A | L1 | F5 | `result` unset when data empty | do(initialize before conditional) | Handles empty input | Not L3: spot uninitialized var |
| `use_before_set_B` | B | L2 | F5 | loader.status unset on empty source | do(set default in loader) | Pipeline reads status safely | Not L3: cross-file edge path |
| `use_before_set_C` | C | L2 (deep) | F5+F6 | best_match set inside loop. Default in wrong scope | do(initialize before loop) — not do(default inside loop) | Handles empty items | Not L3: mechanism trap (wrong scope), forward trace |

---

### Family 8: retry_dup (retry_state_accumulation)

**Bug:** Retry wraps non-idempotent op, doubling side effects.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `retry_dup_A` | A | L1 | F6 | Retry unconditionally re-executes | do(add break on success) | Message stored once | Not L3: retry mechanism is the cause |
| `retry_dup_B` | B | L2 | F6 | Retry wraps store+notify across 2 files | do(add break) | Same | Not L3: cross-file control flow |
| `retry_dup_C` | C | L2 (deep) | F6 | Nested retry across 3 files. Missing break in outer loop | do(add break in outer loop) | Same | Not L3: trace nested loops, count side effects |

---

### Family 9: partial_rollback (partial_state_update)

**Bug:** Multi-step commit without compensation on failure.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `partial_rollback_A` | A | L1 | F1 | Reserve→charge, no rollback | do(add release in except) | Reservation released on failure | Not L3: trace failure path |
| `partial_rollback_B` | B | L2 | F1 | Gateway failure across 2 files. Notification distractor | do(add release before re-raise) | Same | Not L3: cross-file failure path |
| `partial_rollback_C` | C | L2 (deep) | F1+F6 | 3 resources to compensate. Retry mechanism is wrong intervention | do(add release + clean audit) — not do(retry) | Reservation AND audit clean on failure | Not L3: branching path analysis with mechanism trap |

---

### Family 10: temporal_drift (implicit_schema)

**Bug:** Computation on wrong stage of data in pipeline.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `temporal_drift_A` | A | L1 | F4 | raw_stats after transform | do(move before transform) | raw_stats reflects original data | Not L3: fix call order |
| `temporal_drift_B` | B | L2 | F4 | raw_stats on cleaned data. Distractor: summarize_for_display | do(pass original data) | Same | Not L3: cross-file data provenance |
| `temporal_drift_C` | C | L2 (deep) | F4+F6 | 4-stage pipeline across 3 files. Consolidation trap (different key names) | do(pass data not normalized) | Same | Not L3: data provenance tracing |

---

### Family 11: missing_branch (edge_case_omission)

**Bug:** Valid case unhandled in dispatch.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `missing_branch_A` | A | L1 | F1 | No moderator handler | do(add branch) | All valid roles handled | Not L3: spot missing key |
| `missing_branch_B` | B | L2 | F1 | Guest missing from dispatch. Validator distractor | do(add to dispatch) | Same | Not L3: cross-file dispatch trace |
| `missing_branch_C` | C | L2 (deep) | F1 | service_account in middleware but not auth | do(add to auth) | Consistent handling | Not L3: 3-file request path trace |

---

### Family 12: wrong_condition (edge_case_omission)

**Bug:** Wrong comparison operator or logical connective.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `wrong_condition_A` | A | L1 | F2 | `>` vs `>=` | do(change operator) | Boundary handled correctly | Not L3: spot off-by-one |
| `wrong_condition_B` | B | L2 | F3 | `or` vs `and` across 2 files | do(change connective) | Both predicates required | Not L3: trace logic |
| `wrong_condition_C` | C | L2 (deep) | F3 | Operator precedence error across 3 files | do(add parentheses) | Correct for all inputs | Not L3: deterministic operator semantics |

---

### Family 13: early_return (hidden_dependency)

**Bug:** Early return skips required side effect.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `early_return_A` | A | L1 | F4 | Zero-amount skips ledger | do(add ledger before return) | Ledger entry for every call | Not L3: trace return path |
| `early_return_B` | B | L2 | F4 | Duplicate returns cached, skips record | do(add record before return) | Record count matches calls | Not L3: cross-file cached path |
| `early_return_C` | C | L2 (deep) | F4+F6 | Cached charge skips audit. Caching correct, audit omission is bug | do(add log_charge on cached path) | Audit log complete | Not L3: distinguish correct omission from buggy omission |

---

### Family 14: index_misalign (partial_state_update)

**Bug:** Parallel data structures desynchronized.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `index_misalign_A` | A | L1 | F1 | insert vs append | do(insert on both) | Parallel arrays aligned | Not L3: spot mismatch |
| `index_misalign_B` | B | L2 | F1 | delete_column removes header not rows | do(delete from rows too) | Headers and rows aligned | Not L3: cross-file trace |
| `index_misalign_C` | C | L2 (deep) | F1+F6 | insert_column misses widths. recalculate_widths exists but uncalled | do(update widths) or do(call recalculate) | Three structures aligned | Not L3: mechanism disconnected, forward trace |

---

### Family 15: silent_default (silent_failure)

**Bug:** `.get()` with wrong key silently returns default.

| Case | Diff | Pearl | Trap | Mechanism | Intervention | Invariant | L3 Status |
|------|------|-------|------|-----------|-------------|-----------|-----------|
| `silent_default_A` | A | L1 | F5 | camelCase vs snake_case | do(fix key) | Returns configured value | Not L3: spot key mismatch |
| `silent_default_B` | B | L2 | F5 | Wrong intermediate key in nested dict | do(fix key) | Traversal reaches node | Not L3: cross-file key comparison |
| `silent_default_C` | C | L2 (deep) | F5 | Env var key mismatch, 3-file fallback chain | do(fix env key) | Env override reaches system | Not L3: trace fallback chain |

---

## 3. V1 Hard Cases (6 Cases)

These are the original hard cases from V1 that produced the empirical regime data (3 models × 19 conditions each). All are multi-file (3–5 files) with strong mechanism traps.

### L3 Evaluation

For each V1 case, the L3 test is: does the task require establishing **causal necessity** via a but-for test? Specifically: must the model determine whether a step is causally necessary by comparing an execution world where the step is present against a world where it is absent, and showing that the outcome changes?

| Case ID | Pearl | Trap | Mechanism | Intervention Tested | Invariant | L3 Justification |
|---------|-------|------|-----------|---------------------|-----------|-------------------|
| `hidden_dep_multihop` | **L2 (deep)** | F1+F3 | Two cache functions with different overwrite semantics across 4 files | do(consolidate) — verify which semantic is preserved | `get_display_name()` returns current name | **Not L3:** single intervention evaluated by forward tracing of function signatures. No but-for test — the model checks what the consolidated function does, not whether the original function was necessary. |
| `invariant_partial_fail` | **L2 (deep)** | F1+F6 | Debit→potential failure→credit. Logging helpers are mechanism traps (observability, not correctness) | do(extract helper + move logging) — verify balance conservation on failure branch | `sender.balance + receiver.balance` conserved | **Not L3:** failure branch is explicit in code. Model traces success and failure paths of a single proposed refactoring. Competing "fixes" (rollback vs logging vs retry) are alternative interventions evaluated by forward simulation, not alternative execution histories. |
| `l3_state_pipeline` | **L3** | F2+F6 | `stage()→commit()→freeze_view()` across 5 files. `commit()` sets `frozen=True` (gate for selectors). `preview()` calls `stage()` without `commit()` | Task claims commit() and freeze_view() are "redundant" | `get_committed_total()` returns correct value; `preview()` shows uncommitted state | **L3 because the task requires establishing causal necessity via but-for tests.** The model must determine: (1) *Is commit() causally necessary for get_committed_total()?* But-for test: if commit() were absent, `frozen` stays `False`, and `get_committed_total()` returns `None` instead of the sum. The step is necessary. (2) *Is the stage/commit separation causally necessary for preview()?* But-for test: if stage and commit were merged into a single function, `preview()` (which calls stage alone) would set `frozen=True` as a side effect, breaking preview semantics. The separation is necessary. The model must apply two but-for tests against two different downstream invariants and show that the "redundant" steps are each causally necessary for different consumers. This is genuine causal necessity reasoning — not forward simulation of a single change. |
| `async_race_lock` | **L2 (deep)** | F6 | `process_item` uses locking; `quick_increment` skips it. `run_verified` depends on atomicity | do(replace with quick_increment) — verify run_verified breaks | Atomic counter for run_verified | **Not L3:** single intervention, forward trace of which callers depend on atomicity. |
| `cache_invalidation_order` | **L2 (deep)** | F4+F6 | `invalidate→set` ordering intentional. Version numbers in `cache_conditional_set` | do(remove invalidate) — verify version protocol breaks | Version-consistent updates | **Not L3:** single intervention, forward ordering analysis. |
| `feature_flag_drift` | **L2 (deep)** | F3+F6 | `checkout()` accepts flag param but downstream `compute_price()` reads global | do(pass flag) — verify propagation reaches compute_price | Flag reaches all consumers | **Not L3:** single intervention, forward call-chain trace. |

### V1 Summary

| Pearl Level | Count | Cases |
|---|---|---|
| L2 (deep) | 5 | hidden_dep_multihop, invariant_partial_fail, async_race_lock, cache_invalidation_order, feature_flag_drift |
| L3 | 1 | l3_state_pipeline |

---

## 4. Summary Statistics (All 58 Cases)

### Cases by Pearl Level

| Pearl Level | V2 Original | V1 Hard | New (L3/Conc/Overdet) | Total | % |
|---|---|---|---|---|---|
| L1 | 15 | 0 | 0 | 15 | 26% |
| L1-L2 boundary | 2 | 0 | 0 | 2 | 3% |
| L2 | 13 | 0 | 2 | 15 | 26% |
| L2 (deep) | 15 | 5 | 3 | 23 | 40% |
| L3 | 0 | 1 | 2 | 3 | 5% |
| **Total** | **45** | **6** | **7** | **58** | |

> True L3 counterfactual reasoning is present but rare — 3 cases (5%): `l3_state_pipeline`, `config_shadowing`, `commit_gate`. The vast majority of cases (95%) probe L2 reasoning at varying depths. The 4 concurrency cases test a qualitatively different L2 skill: reasoning about interleaving, atomicity, and ordering as causal properties.

### Cases by Trap Family

| Trap Family | Primary | Co-occurring | Total |
|---|---|---|---|
| F1 Selection Effects | 15 | 4 | 19 |
| F2 Statistical Artifacts | 4 | 1 | 5 |
| F3 Confounding | 11 | 2 | 13 |
| F4 Direction Errors | 5 | 1 | 6 |
| F5 Information Bias | 7 | 0 | 7 |
| F6 Mechanism Failures | 7 | 12 | 19 |

F6 (Mechanism Failures) concentrates at Level C, V1 hard, and concurrency cases as a co-occurring trap. The new concurrency cases add F3 (shared state as confound) and F6 (wrong fix mechanism — e.g., lock doesn't fix ordering) to the distribution.

### Key Empirical Insight

A central finding of this benchmark is that **most code reasoning failures occur within L2 (intervention reasoning), not at the L2-L3 boundary (counterfactual reasoning).** Of 51 cases, only 1 (2%) requires true L3 but-for causal necessity reasoning. The remaining 98% are solvable — in principle — by tracing how a proposed change propagates through the system.

This suggests that current LLM limitations in code generation stem primarily from failures in **multi-step causal propagation and mechanism verification** (deep L2), rather than from failures of counterfactual reasoning (L3). Models struggle to track state across module boundaries and to verify that available mechanisms connect to the actual bug — not to reason about alternative worlds.

No clear L3 cases were identified in the V2 benchmark under strict but-for criteria. The single L3 case (`l3_state_pipeline`) comes from V1 and is characterized by requiring two independent but-for tests against two different downstream consumers of the same pipeline step. It is empirically the hardest case in the benchmark: no model passes it under any of the 19 tested conditions.

---

## 5. Regime Prediction

| Regime | Expected Cases | Pearl Level | Failure Mechanism |
|---|---|---|---|
| **Heuristic** | Level A | L1 | Pattern matching from training data suffices |
| **REI** | Level B, esp. with F6 | L2 | Model traces the bug correctly in reasoning but fails to implement the correct intervention in code |
| **CSF-L2** | Level C + most V1 hard | L2 (deep) | Model cannot propagate multi-module state through mechanism traps — fails to verify that the intervention reaches the bug |
| **CSF-L3** | l3_state_pipeline | L3 | Model cannot evaluate causal necessity — cannot determine whether a step is required via but-for reasoning across competing execution histories |

The hardest cases combine **high depth** (3–5 files) with **co-occurring F6 mechanism traps** (existing code that looks like the right fix but is structurally disconnected from the bug). The single L3 case additionally requires but-for reasoning against multiple downstream invariants, and was empirically confirmed as part of the "hard CSF core" — no model passes it under any condition.

---

## 6. Quick-Reference Table (All 51 Cases)

### V2 Cases (45)

| # | Case ID | Family | Diff | Pearl | Primary Trap | Secondary |
|---|---------|--------|------|-------|-------------|-----------|
| 1 | `alias_config_A` | alias_config | A | L1 | F3 | -- |
| 2 | `alias_config_B` | alias_config | B | L1-L2 | F3 | -- |
| 3 | `alias_config_C` | alias_config | C | L2 | F3 | -- |
| 4 | `partial_update_A` | partial_update | A | L1 | F1 | -- |
| 5 | `partial_update_B` | partial_update | B | L2 | F1 | F6 |
| 6 | `partial_update_C` | partial_update | C | L2 (deep) | F6 | -- |
| 7 | `stale_cache_A` | stale_cache | A | L1 | F1 | -- |
| 8 | `stale_cache_B` | stale_cache | B | L2 | F1 | -- |
| 9 | `stale_cache_C` | stale_cache | C | L2 (deep) | F1 | -- |
| 10 | `lazy_init_A` | lazy_init | A | L1 | F4 | -- |
| 11 | `lazy_init_B` | lazy_init | B | L2 | F6 | -- |
| 12 | `lazy_init_C` | lazy_init | C | L2 (deep) | F6 | -- |
| 13 | `mutable_default_A` | mutable_default | A | L1 | F3 | -- |
| 14 | `mutable_default_B` | mutable_default | B | L1-L2 | F3 | -- |
| 15 | `mutable_default_C` | mutable_default | C | L2 | F3 | -- |
| 16 | `effect_order_A` | effect_order | A | L1 | F2 | -- |
| 17 | `effect_order_B` | effect_order | B | L2 | F2 | -- |
| 18 | `effect_order_C` | effect_order | C | L2 (deep) | F2 | F6 |
| 19 | `use_before_set_A` | use_before_set | A | L1 | F5 | -- |
| 20 | `use_before_set_B` | use_before_set | B | L2 | F5 | -- |
| 21 | `use_before_set_C` | use_before_set | C | L2 (deep) | F5 | F6 |
| 22 | `retry_dup_A` | retry_dup | A | L1 | F6 | -- |
| 23 | `retry_dup_B` | retry_dup | B | L2 | F6 | -- |
| 24 | `retry_dup_C` | retry_dup | C | L2 (deep) | F6 | -- |
| 25 | `partial_rollback_A` | partial_rollback | A | L1 | F1 | -- |
| 26 | `partial_rollback_B` | partial_rollback | B | L2 | F1 | -- |
| 27 | `partial_rollback_C` | partial_rollback | C | L2 (deep) | F1 | F6 |
| 28 | `temporal_drift_A` | temporal_drift | A | L1 | F4 | -- |
| 29 | `temporal_drift_B` | temporal_drift | B | L2 | F4 | -- |
| 30 | `temporal_drift_C` | temporal_drift | C | L2 (deep) | F4 | F6 |
| 31 | `missing_branch_A` | missing_branch | A | L1 | F1 | -- |
| 32 | `missing_branch_B` | missing_branch | B | L2 | F1 | -- |
| 33 | `missing_branch_C` | missing_branch | C | L2 (deep) | F1 | -- |
| 34 | `wrong_condition_A` | wrong_condition | A | L1 | F2 | -- |
| 35 | `wrong_condition_B` | wrong_condition | B | L2 | F3 | -- |
| 36 | `wrong_condition_C` | wrong_condition | C | L2 (deep) | F3 | -- |
| 37 | `early_return_A` | early_return | A | L1 | F4 | -- |
| 38 | `early_return_B` | early_return | B | L2 | F4 | -- |
| 39 | `early_return_C` | early_return | C | L2 (deep) | F4 | F6 |
| 40 | `index_misalign_A` | index_misalign | A | L1 | F1 | -- |
| 41 | `index_misalign_B` | index_misalign | B | L2 | F1 | -- |
| 42 | `index_misalign_C` | index_misalign | C | L2 (deep) | F1 | F6 |
| 43 | `silent_default_A` | silent_default | A | L1 | F5 | -- |
| 44 | `silent_default_B` | silent_default | B | L2 | F5 | -- |
| 45 | `silent_default_C` | silent_default | C | L2 (deep) | F5 | -- |

### V1 Hard Cases (6)

| # | Case ID | Pearl | Primary Trap | Secondary |
|---|---------|-------|-------------|-----------|
| 46 | `hidden_dep_multihop` | L2 (deep) | F1 | F3 |
| 47 | `invariant_partial_fail` | L2 (deep) | F1 | F6 |
| 48 | `l3_state_pipeline` | **L3** | F2 | F6 |
| 49 | `async_race_lock` | L2 (deep) | F6 | -- |
| 50 | `cache_invalidation_order` | L2 (deep) | F4 | F6 |
| 51 | `feature_flag_drift` | L2 (deep) | F3 | F6 |

### L3 / Concurrency / Overdetermination Cases (7)

| # | Case ID | Pearl | Primary Trap | Secondary |
|---|---------|-------|-------------|-----------|
| 52 | `config_shadowing` | **L3** | F5 (silent masking) | F3 |
| 53 | `commit_gate` | **L3** | F2 (aggregate vs component) | F6 |
| 54 | `overdetermination` | L2 (deep) | F3 (confounding) | F1 |
| 55 | `lost_update` | L2 | F3 (shared state race) | -- |
| 56 | `check_then_act` | L2 | F1 (check sees stale) | -- |
| 57 | `ordering_dependency` | L2 | F6 (lock ≠ ordering) | -- |
| 58 | `false_fix_deadlock` | L2 (deep) | F6 (wrong fix) | -- |
