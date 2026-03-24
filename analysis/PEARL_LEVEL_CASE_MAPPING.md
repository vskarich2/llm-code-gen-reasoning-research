# Pearl's Causal Hierarchy → Code Generation Case Mapping

**Purpose:** Connect each benchmark case to Pearl's Ladder of Causation and the T3 trap taxonomy. This is the theoretical grounding for our difficulty levels and the causal reasoning sections in case documentation.

---

## 1. Pearl's Ladder Applied to Code

Pearl's three levels describe qualitatively different reasoning tasks. In code generation, they map to qualitatively different kinds of program understanding:

| Pearl Level | Original Domain | Code Generation Analog | Cognitive Task |
|---|---|---|---|
| **L1: Association** | P(Y\|X) — "What do I observe?" | "What does this code do when I run it?" — tracing execution for a specific input. Pure pattern matching from training data. | **Seeing** |
| **L2: Intervention** | P(Y\|do(X)) — "What happens if I change X?" | "If I modify function A, what happens to function B's output?" — requires a causal model of data flow + side effects. The model must reason about the *effect of an edit*, not just the current behavior. | **Doing** |
| **L3: Counterfactual** | P(Y_x\|X',Y') — "What would have happened if X had been different?" | "If the payment had succeeded, would the audit log be correct?" or "If this function were called with empty input, would the invariant hold?" — requires simulating alternative execution paths through multi-module state. | **Imagining** |

### The Critical Boundary in Code Generation

LLMs are trained on code corpora — they are fundamentally **L1 association engines** over code patterns. They excel at:
- "What does this function return?" (pattern matching)
- "How do I write a function that does X?" (template completion)

The failures we study occur at the **L1/L2 boundary** (analogous to T3-L2 in the course framework): tasks that *look* like they only require L1 (reading code) but actually require L2 (reasoning about the causal effects of modifications). This is exactly where T3-L2's trap taxonomy lives — cases where association (pattern matching) produces a plausible but causally wrong answer.

Our hardest cases push into **L3**: the model must imagine alternative execution paths ("what if the payment fails?") and reason about invariants across counterfactual scenarios.

---

## 2. Trap Types from T3-L2 Mapped to Code Cases

The T3-L2 benchmark identifies 6 families of causal reasoning traps. Each maps onto specific code generation failure patterns:

### F1: Selection Effects → Cases Where the "Obvious" Sample is Non-Representative

| T3-L2 Trap | Code Analog | Cases |
|---|---|---|
| **W1: Selection Bias** — Non-representative sample leads to wrong conclusion | Model sees only the happy path in code, misses the failure path. The "sample" of execution paths the model reasons about is biased toward success. | `partial_rollback` (all levels): model sees reserve→charge→notify and reasons about the success path, missing that charge can fail mid-sequence |
| **W2: Survivorship Bias** — Only survivors observed, failures hidden | Model sees functions that exist and work, doesn't notice the *missing* function call. The absence of code is invisible. | `stale_cache` (all levels): the missing `invalidate()` call is the bug — model must notice what ISN'T there, not what is |
| **W3: Healthy User Bias** — Self-selection confounds with treatment effect | Model assumes a function's behavior is representative of all callers, but certain callers have special properties | `alias_config_c`: `merge_overrides()` correctly copies, tempting the model to route through it — but middleware callers have different semantics than admin callers |

### F2: Statistical Artifacts → Cases Where Surface Pattern Misleads

| T3-L2 Trap | Code Analog | Cases |
|---|---|---|
| **W5: Ecological Fallacy** — Aggregate pattern doesn't hold for individuals | Function behavior at batch level doesn't reflect per-item requirements | `effect_order` (all levels): snapshot/emit works at batch level but the invariant requires per-item behavior. The aggregate looks fine, individual items are wrong |
| **Regression to Mean (W4)** | Retry appears to "fix" the problem but the model is just producing different random outputs | Retry dynamics in CSF cases: score oscillates around a mean, looking like progress but actually noise |

### F3: Confounding → Cases Where a Hidden Variable Explains Both

| T3-L2 Trap | Code Analog | Cases |
|---|---|---|
| **W7: Confounding** — Z causes both X and Y, making them correlated without causal link | A shared mutable object (the confound) connects two apparently independent code paths | `alias_config` (all levels): DEFAULTS dict is the confound — `create_config()` and the caller appear independent, but both operate on the same object |
| **W7 variant: Hidden common cause** | Module-level state acts as a hidden variable coupling function calls | `mutable_default` (all levels): the default argument is a hidden variable that persists across calls, coupling call 1 and call 2 through shared state |
| **Simpson's Paradox (W8)** | Aggregated behavior reverses when conditioned on a subgroup | `wrong_condition_c`: the boolean expression `not expired and under_limit or exempt` reads correctly at aggregate level but reverses for the `expired + exempt` subgroup due to operator precedence |

### F4: Direction Errors → Cases Where Cause and Effect Are Confused

| T3-L2 Trap | Code Analog | Cases |
|---|---|---|
| **W9: Reverse Causation** — Direction of causal arrow is wrong | Model assumes the function it's editing is the *cause* of the bug, when the actual cause is upstream | `temporal_drift_c`: model edits `compute_raw_stats()` (the effect site) when the actual cause is in `pipeline()` (wrong argument passed). The causal arrow points from pipeline→metrics, not metrics→self |
| **W10: Post Hoc Fallacy** — Temporal sequence mistaken for causation | Model assumes that because step 2 follows step 1, step 1 caused step 2's problem | `early_return` (all levels): the early return *precedes* the missing ledger entry temporally, so models assume the return itself is the bug. But returns are correct — the bug is the missing side effect |

### F5: Information Bias → Cases Where the Measurement/Observation is Wrong

| T3-L2 Trap | Code Analog | Cases |
|---|---|---|
| **Information bias / Misclassification** — Measurement instrument is miscalibrated | The test/observation mechanism itself is misleading | `silent_default` (all levels): `.get(key, default)` is the measurement — it silently returns a wrong default instead of signaling the key mismatch. The model must recognize the measurement is corrupted, not just that the output is wrong |
| **Observer bias** | Code appears to work (no crash, plausible output) but invariant is silently violated | All "silent failure" cases: the code's observable behavior (no crash) is misleading about its correctness |

### F6: Mechanism Failures → Cases Where the Intervention Doesn't Target the Cause

| T3-L2 Trap | Code Analog | Cases |
|---|---|---|
| **Mechanism mismatch** — Intervention targets the wrong causal pathway | Model's fix addresses a symptom, not the root cause | `retry_dup_c`: adding more retry at the pipeline level (the intuitive "make it robust" intervention) actually *worsens* the duplication. The intervention targets the wrong causal pathway |
| **Goodhart's Law** — When a measure becomes a target, it ceases to be a good measure | Model optimizes for the visible metric (no crash, code runs) rather than the actual invariant | `invariant_partial_fail`: model adds `emit_failure_alert()` (observability) instead of rollback (correctness). It targets the metric "error is handled" instead of the invariant "balance is conserved" |
| **Feedback loop** | Fix introduces a new problem through circular dependency | `lazy_init_c`: model adds `refresh()` to client but handler still captures client's stale copy — the fix creates a longer chain that still doesn't propagate |

---

## 3. Per-Case Pearl Level Classification

### What Determines Pearl Level in Code

| Level | Question the Model Must Answer | Reasoning Type | Number of Causal Hops |
|---|---|---|---|
| **L1** | "What does this function do?" | Association — pattern match from training | 0 (same function) |
| **L2** | "If I change this function, what breaks?" | Intervention — trace the causal graph one hop | 1 (cross-function) |
| **L3** | "If this call had failed, what state would be left?" | Counterfactual — simulate alternative execution across modules | 2+ (cross-module) |

### Level A Cases (Pearl L1 → L2 Boundary)

These cases can be solved by L1 association (pattern matching) on a good day, but the trap exploits the gap between L1 and L2:

| Case | Pearl Reasoning | L2 Trap Analog | Why L1 Suffices for Some Models |
|---|---|---|---|
| `alias_config_a` | "This returns DEFAULTS directly → callers can mutate it" | **Confounding** (shared object) | `.copy()` for mutable defaults is a common pattern in training data |
| `partial_rollback_a` | "reserve() runs before charge() → if charge fails, reserved" | **Selection bias** (happy path only) | try/except + cleanup is a common pattern |
| `mutable_default_a` | "`def f(x=[])` accumulates" | **Confounding** (hidden shared state) | One of the most-documented Python gotchas |
| `missing_branch_a` | "No case for 'moderator'" | **Ecological fallacy** (aggregate covers individuals) | Missing elif is a simple pattern |
| `use_before_set_a` | "result not set when data is empty" | **Information bias** (measurement on wrong path) | Uninitialized variable is a basic pattern |
| `wrong_condition_a` | "`>` instead of `>=`" | **Statistical artifact** (off-by-one) | Off-by-one is highly represented in training |

**Key insight:** Level A cases are at the L1/L2 boundary. Strong models (4o-mini) solve them via L1 pattern matching. Weak models (nano) need L2 intervention reasoning and fail — this is exactly the Heuristic vs. REI regime distinction.

### Level B Cases (Pearl L2: Intervention Reasoning)

These require genuine L2 reasoning — the model must trace the effect of a code change across one function boundary:

| Case | Pearl L2 Reasoning Required | L2 Trap Type | The Intervention Question |
|---|---|---|---|
| `stale_cache_b` | "If update_product changes DB, does get_product still return stale cache?" | **Survivorship** (missing call invisible) | "do(update_product) → what happens to get_product?" |
| `effect_order_b` | "If emit_event is outside the loop, does get_events match items?" | **Ecological** (batch ≠ per-item) | "do(move emit_event) → what happens to event count?" |
| `partial_rollback_b` | "If gateway.process fails, is inventory released?" | **Selection** (failure path) | "do(fail payment) → what happens to reserved inventory?" |
| `silent_default_b` | "If I call get_flag('features.x'), does it find _CONFIG['feature']['x']?" | **Information bias** (silent mismatch) | "do(traverse with 'features') → does it reach the right node?" |
| `lazy_init_b` | "If reset_settings() runs, does client._timeout change?" | **Mechanism** (intervention doesn't reach target) | "do(reset) → does the effect propagate to client?" |
| `temporal_drift_b` | "If raw_stats gets normalized data, does raw_max reflect original?" | **Direction** (wrong data flows to function) | "do(pass normalized) → what does raw_stats report?" |
| `retry_dup_b` | "If send_with_retry retries, does store get duplicates?" | **Mechanism** (intervention worsens) | "do(retry) → does the side effect double?" |

**Key insight:** Level B cases require the model to answer the L2 question "What happens if I do X?" — specifically, what happens at function B when function A is modified. This is the **intervention calculus** applied to code: `P(output_B | do(change_A))`.

### Level C Cases (Pearl L2 → L3 Boundary)

These push toward L3 counterfactual reasoning — the model must simulate alternative execution paths across multiple modules:

| Case | Pearl L3 Reasoning Required | L2 Trap Type | The Counterfactual Question |
|---|---|---|---|
| `alias_config_c` | "If request 1 sets debug=True, would request 2 see debug=False?" | **Confounding** (shared state across requests) | "In the world where request 1 ran, what state does request 2 inherit?" — requires simulating state mutation through 3-file cycle |
| `retry_dup_c` | "If the pipeline retries, how many times does the message appear in store?" | **Mechanism** (nested intervention) | Must mentally execute two nested retry loops across 3 files and count total side effects — abduction + prediction |
| `early_return_c` | "If charge() is called with a cached txn_id, would the audit log be complete?" | **Mechanism** (correct intervention with wrong side effect) | "In the world where the cache hits, which downstream effects still fire?" — requires distinguishing correct omission (ledger) from buggy omission (audit) |
| `temporal_drift_c` | "If pipeline passes normalized data to compute_raw_stats, would raw_max equal the original max?" | **Direction** (wrong stage data) | Must propagate alternative input through a 4-stage pipeline across 3 files to predict the output |
| `partial_rollback_c` | "If payment fails after reserve + audit_log, what state is left?" | **Selection** + **Mechanism** | Must simulate the failure path and identify TWO resources to compensate — partial counterfactual |
| `stale_cache_c` | "If update_product invalidates shared cache but not local, would api.get_product return current data?" | **Survivorship** (one invalidation is invisible) | Two-layer cache — must reason about which layer is stale in the counterfactual world where only one is invalidated |

**Key insight:** Level C cases require the model to perform something close to Pearl's counterfactual procedure:
1. **Abduction**: infer the current state of the system (what's in the cache? what's in the audit log?)
2. **Action**: modify the antecedent (payment fails, request 1 runs)
3. **Prediction**: propagate through the causal structure to predict the outcome under the alternative scenario

This is exactly the L3 procedure: abduction → action → prediction. The model must imagine an execution that didn't happen and reason about its consequences across module boundaries.

---

## 4. Regime Connection

The regime framework (REI / Heuristic / CSF) maps cleanly onto Pearl's levels:

| Regime | Pearl Level | Why |
|---|---|---|
| **Heuristic** | Succeeds at L1 | Pattern matching from training data produces correct code without causal reasoning. The model doesn't need to "do" or "imagine" — it just recognizes the pattern. |
| **REI** | Fails at L1→L2 boundary | Model's L1 association correctly identifies the bug pattern (reasoning is valid), but its code generation doesn't implement the L2 intervention correctly. The gap is between "seeing the problem" and "doing the fix." |
| **CSF** | Fails at L2→L3 | Model cannot perform the counterfactual simulation required. It can't trace multi-step state evolution, can't imagine alternative execution paths, can't propagate changes through module boundaries. The causal model is absent. |

**CGE (Contract-Gated Execution) as an L2 scaffold:** CGE works by forcing the model to make its causal model explicit *before* generating code. This converts an implicit L2 reasoning task into an explicit L1 task (fill in a JSON template with the causal structure). For REI cases — where the model already has a valid causal model but can't execute it — making the model explicit about its understanding via a contract bridges the gap. For CSF cases, the model can't fill in the contract correctly either, so CGE doesn't help.

---

## 5. Summary: Why Each Case Is At Its Level

| Level | Pearl Tier | Cognitive Task | Trap Families Active | Model Behavior |
|---|---|---|---|---|
| **A** | L1/L2 boundary | "See the pattern and apply the fix" | Confounding, selection (simple forms) | Heuristic models pass; weaker models may need L2 and fail |
| **B** | L2 (Intervention) | "Trace the effect of a change across one boundary" | All 6 families (single-hop versions) | Requires genuine causal reasoning about code; CGE helps |
| **C** | L2/L3 boundary | "Simulate alternative execution through multi-module state" | Mechanism failures, compound traps | Requires counterfactual simulation; CGE insufficient for CSF |
