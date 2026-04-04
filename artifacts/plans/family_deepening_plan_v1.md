# Family Deepening Plan v1 — Theory-Driven Case Expansion

**Date:** 2026-04-01
**Status:** PLAN ONLY — NO IMPLEMENTATION
**Scope:** 14 new cases across 5 priority families + 1 upgraded family
**Purpose:** Deepen existing families with strongest theory value for reasoning-vs-execution analysis

---

## 1. Executive Summary

### Why these families

The benchmark currently has 58 cases across 28 families, but its theory-discriminative power is diluted because the strongest families for reasoning/execution separation are under-represented. Three of the five most theory-relevant families (`hidden_dep_multihop`, `invariant_partial_fail`, `cache_invalidation_order`) are singletons with no difficulty ladder, making it impossible to measure within-family difficulty scaling, family-level LEG heterogeneity, or critique-gain gradients.

These five families were selected because they satisfy all six family-selection criteria simultaneously:

1. **Reasoning and execution genuinely separate.** In each family, a model can produce a correct verbal description of the problem mechanism while generating a patch that fails to implement that understanding. This is not true of mechanical families like `wrong_condition` (where the reasoning IS the fix — flip `>` to `>=`) or `mutable_default` (where the fix pattern is a single well-known idiom).

2. **Critique can detect reasoning/code mismatch.** In `invariant_partial_fail`, a critique model can compare "your reasoning says balance must be conserved" against "your patch doesn't add rollback." In `hidden_dep_multihop`, a critique can compare "you identified that these functions have different cache-write semantics" against "your consolidated code uses only one semantic." Mechanical families like `index_misalign` don't offer this — the mismatch is in array operations, not in verbally articulable reasoning.

3. **Multiple plausible wrong fixes exist.** Each family supports 2-4 distinct wrong-fix attractors (not just "forgot to fix" or "fixed wrong line"), creating a richer failure taxonomy than families where there's basically one wrong fix and one right fix.

4. **Difficulty ladders are meaningful.** Adding B and D levels to these families creates genuine causal-depth variation: more hops, more files, more state to track. Unlike `early_return` or `silent_default` where difficulty mainly means "more files to read," these families' difficulty genuinely increases the reasoning load.

5. **Model stratification is expected.** These families target the capability boundary between models: the reasoning is hard enough that weaker models fail entirely, but structured enough that stronger models can partially succeed — creating measurable variation rather than ceiling/floor effects.

### Why deepening is better than broadening

Broadening (adding many unrelated families) produces an uninterpretable benchmark: each family contributes 1-2 data points, making it impossible to distinguish family-level effects from case-level noise. Deepening produces families with 3-4 cases at varying difficulty, enabling:

- **Within-family difficulty gradients**: Does LEG increase from B to D within a family? If so, the family isolates a real scaling phenomenon.
- **Family-level critique sensitivity**: Does critique help consistently within a family, or only at certain difficulty levels? This distinguishes "critique helps with this mechanism" from "critique helps with easy cases."
- **Controlled comparison**: Cases within a family share the same bug mechanism, so performance differences across difficulty levels are attributable to causal depth, not mechanism novelty.

### What hypotheses these families test

The central question is: **When does structured reasoning scaffolding convert correct diagnosis into correct execution, and when does it lock in wrong diagnosis?**

These families test this by creating scenarios where:
- The correct diagnosis is articulable in natural language (testable via reasoning extraction)
- The correct fix requires multi-step implementation that can diverge from the diagnosis (testable via code evaluation)
- Critique has the information needed to detect divergence (testable via critique ablation)
- Wrong diagnoses are plausible enough to attract models (testable via failure-mode classification)

---

## 2. Family Ranking with Justification

### Rank 1: hidden_dep_multihop

**Reasoning phenomenon isolated:** The model must trace a dependency chain through multiple modules to discover that two apparently-identical functions have different semantics, and that consolidating them destroys a critical semantic distinction. The reasoning (identifying the semantic difference) is separable from the execution (preserving it in the refactored code).

**LEG/critique usefulness:** This is the highest-LEG-potential family in the benchmark. The diagnosis ("these two functions use different cache-write strategies") can be stated in one sentence, but implementing the fix requires correctly assigning the right strategy to every call site. A model that articulates the distinction but consolidates anyway exhibits textbook LEG. Critique is highly effective here because the mismatch between reasoning ("they have different semantics") and code ("I merged them into one") is visible in prose.

**Reasoning-right/execution-wrong prediction:** HIGH. The multi-hop dependency chain (service → writer → low-level operation) means a model can follow one hop and correctly identify the semantic distinction but fail to trace all callers to determine which semantics each needs. This is exactly the reasoning/execution gap the thesis targets.

**Critique prediction:** HELPS STRONGLY. The mismatch is articulable: "Your reasoning identifies that `cache_put` always overwrites while `cache_put_if_absent` is conditional, but your refactored code uses only the conditional version for all callers." This is a clean, detectable inconsistency.

**Likely wrong fixes:**
1. Consolidate using the "safer-looking" option (current case's attractor)
2. Consolidate using the simpler option (loses safety guarantees)
3. Consolidate correctly but miss one caller that needed the other semantic
4. Add a parameter to toggle behavior but wire it wrong at some call sites

**Model stratification expected:** HIGH. Nano will consolidate without tracing. 4o-mini will trace one hop but not all callers. 5-mini may trace correctly but implement the parameter-toggle wrong. Strong models will preserve the semantic distinction.

**Current state:** 1 case (C-level singleton). Needs B and D levels for a complete difficulty ladder.

---

### Rank 2: invariant_partial_fail

**Reasoning phenomenon isolated:** The model must discover a latent invariant violation in code that the task frames as correct-but-messy. The task asks for refactoring, not bug-fixing. The model must reason about failure-path semantics (what happens when an exception occurs between two mutations?) independently of the task framing.

**LEG/critique usefulness:** Very high critique potential. The invariant (e.g., "balance must be conserved") is easy to state and easy to check against a patch. A critique model can ask: "Does the refactored code maintain balance conservation on all paths, including the exception path?" If the model's reasoning acknowledges the invariant but the code doesn't enforce it, the mismatch is unambiguous.

**Reasoning-right/execution-wrong prediction:** HIGH. Models frequently identify partial-failure risks in their reasoning ("what if step 2 fails after step 1 commits?") but then produce code that doesn't add compensation. The refactoring framing actively suppresses the "add rollback" instinct because the task says "simplify," not "fix."

**Critique prediction:** HELPS STRONGLY for models that identify the invariant in reasoning. DOES NOT HELP for models that never consider the failure path — critique can only detect a gap between stated reasoning and code, not supply missing reasoning.

**Likely wrong fixes:**
1. Clean refactoring that faithfully preserves the existing bug (most common)
2. Adding logging/observability without adding rollback (the task-framing trap)
3. Adding rollback for one resource but not all (partial fix, common at C+ difficulty)
4. Wrapping in try/except that catches and re-raises but doesn't compensate

**Model stratification expected:** HIGH. This family discriminates between models that treat refactoring as purely structural vs. those that reason about behavioral preservation during refactoring.

**Current state:** 1 case (C-level singleton). Needs B and D levels.

---

### Rank 3: retry_state_temporal (new sub-family) + retry_dup extension

**Reasoning phenomenon isolated:** Temporal reasoning about state that persists or accumulates across retry attempts. The model must reason about what state exists at retry-attempt-N given that attempts 1 through N-1 have already partially executed. This is fundamentally different from the existing `retry_dup` family (which targets duplicate side effects from missing break/idempotence) — `retry_state_temporal` targets state contamination.

**LEG/critique usefulness:** LEG is expected to increase with temporal depth. A model can describe the failure mode ("state from attempt 1 leaks into attempt 2") but fail to implement the reset/rollback needed between attempts. Critique effectiveness is MIXED: some state contamination is visible in prose ("you said state must be reset between attempts but your code doesn't reset it") while other contamination depends on execution order that prose can't capture.

**Reasoning-right/execution-wrong prediction:** HIGH at C+ difficulty. Temporal reasoning about "what state exists at this point in execution" is one of the hardest reasoning-to-execution translation tasks because it requires mental simulation of multiple execution paths.

**Critique prediction:** MIXED. Critique helps when the state-reset requirement is explicit in the model's reasoning. Critique is useless when the model's reasoning doesn't mention state persistence across attempts.

**Likely wrong fixes:**
1. Adding retry without clearing accumulated state
2. Clearing some state but not all (e.g., resetting a counter but not a partial-result buffer)
3. Adding idempotence checks that mask the contamination rather than preventing it
4. Moving the retry boundary to the wrong level (retrying too much or too little)

**Model stratification expected:** VERY HIGH. Temporal reasoning is a sharp discriminator across model tiers.

**Current state:** `retry_dup` has A/B/C. No cases target state contamination across retries. Adding `retry_dup_d` (exponential complexity) and a new `retry_state_temporal` sub-family (B/C/D) gives comprehensive temporal coverage.

---

### Rank 4: cache_invalidation_order

**Reasoning phenomenon isolated:** Ordering dependencies in cache operations where the "obviously redundant" step is actually load-bearing. The model must reason about why a seemingly wasteful invalidate-then-set sequence is correct: the invalidation bumps a version counter that the subsequent conditional set depends on. Removing the "redundant" invalidation breaks the version check.

**LEG/critique usefulness:** Moderate. The ordering dependency is articulable ("invalidation must happen before set to bump the version"), but whether the model actually generates correct ordering in code depends on implementation details that are hard to verify in prose. Critique helps when the model's reasoning mentions version semantics but the code removes the version bump. Critique fails when the ordering bug is only detectable by execution trace.

**Reasoning-right/execution-wrong prediction:** MODERATE. The ordering reasoning is subtle but, once identified, the fix is usually straightforward (don't remove the invalidation). The harder cases involve two-stage invalidation or layered caches where the ordering is less obvious.

**Critique prediction:** MIXED. Some ordering bugs are critique-visible ("you said version tracking depends on invalidation but your code removes it"). Others are execution-only ("the L2 cache gets re-populated from L1 before L1 is invalidated, but this is only visible in the execution order of cache reads").

**Likely wrong fixes:**
1. Remove the "redundant" invalidation (current case's attractor)
2. Reorder operations to look cleaner but break the version dependency
3. Add a cache refresh after set (masks the bug but adds latency and fragility)
4. Replace conditional set with unconditional set (loses the version-based conflict detection)

**Model stratification expected:** MODERATE. This family discriminates less sharply than hidden_dep or invariant_partial because the fix, once identified, is simple. The discrimination is in whether the model identifies the ordering constraint at all.

**Current state:** 1 case (C-level singleton). Needs B and D levels.

---

### Rank 5: control_flow_path (upgraded missing_branch)

**Reasoning phenomenon isolated:** Path interaction bugs where one execution path mutates state that another path depends on, or where guard evaluation order determines correctness. This is NOT the same as "missing branch" (which is a simple case-enumeration omission). Path-interaction requires reasoning about the combinatorial space of execution paths and their state effects.

**LEG/critique usefulness:** Moderate to low. Path-interaction bugs are hard to articulate in prose — the model needs to reason about "if path A runs before path B, then X happens, but if B runs first, then Y happens." Critique can detect obvious mismatches ("your reasoning says cleanup must run on all paths but your code skips it on early return") but cannot easily detect subtle ordering effects.

**Reasoning-right/execution-wrong prediction:** MODERATE. The reasoning challenge is identifying which paths interact. The execution challenge is implementing guards or cleanup that covers all interaction cases. The gap between these is real but smaller than in hidden_dep or invariant_partial.

**Critique prediction:** HELPS ON CLEANUP CASES. Cases where the model identifies "cleanup must happen on all exit paths" but generates code that misses one path are critique-visible. Cases involving guard ordering or state-mutation interaction are execution-only.

**Likely wrong fixes:**
1. Adding the missing guard but at the wrong priority level
2. Adding cleanup to the explicit return paths but missing exception paths
3. Fixing one path interaction but creating a new one
4. Adding a blanket guard that's too restrictive (breaks valid paths)

**Model stratification expected:** MODERATE. This family is included conditionally — only if the cases can be designed to involve genuine path interaction rather than simple branch completion.

**Current state:** `missing_branch` has A/B/C but all are simple case-enumeration bugs. New `control_flow_path` cases must demonstrate path INTERACTION, not missing enumeration. The existing missing_branch_c (middleware/auth pipeline) is at the boundary — it involves multi-file tracing but the fix is still "add a branch."

---

## 3. Hypotheses per Family

### hidden_dep_multihop

**H1-base:** Baseline pass rates will be LOW across all models (< 30% for nano, < 40% for 4o-mini, < 50% for 5-mini) because the task actively encourages the wrong consolidation.

**H1-leg:** Baseline LEG rates will be HIGH (> 40% across models) because the semantic distinction between the two functions is easy to articulate but hard to preserve in code. Models will identify the distinction in their reasoning trace but consolidate anyway.

**H1-critique-help:** Critique will reduce LEG by 15-25 percentage points for models that identify the semantic distinction in their initial reasoning, because the mismatch between "these functions have different semantics" and "I merged them into one" is clearly detectable by a critique model.

**H1-critique-hurt:** Critique will NOT help (and may hurt by 5-10pp) for models that never identify the semantic distinction. In these cases, critique reinforces the wrong consolidation approach by making it more systematic.

**H1-difficulty:** LEG rate will increase from B to D because the number of callers to correctly assign increases, while the articulable reasoning ("they're different") stays the same length. The reasoning/execution gap widens with implementation complexity.

**H1-falsification:** If LEG rates are LOW (< 20%) in this family, it means models either (a) don't identify the semantic distinction at all (reasoning and execution are both wrong — the family is too hard) or (b) reliably translate the distinction into correct code (the family is too easy). Either would make the family non-discriminative for reasoning/execution separation.

---

### invariant_partial_fail

**H2-base:** Baseline pass rates will be VERY LOW (< 15% for nano, < 25% for 4o-mini, < 35% for 5-mini) because the task frames the code as correct-but-messy. Models must independently discover the invariant violation.

**H2-leg:** LEG rates will be MODERATE (20-35%) because some models will mention failure-path risks in reasoning but still produce a "clean" refactoring that preserves the bug. The refactoring framing suppresses the fix instinct.

**H2-critique-help:** Critique will show STRONG gains (20-40pp) specifically for models whose reasoning mentions the invariant ("balance must be conserved" or "what if step 2 fails?"). The critique prompt "does your refactored code maintain this invariant on all paths?" is highly effective.

**H2-critique-hurt:** Critique will have NO EFFECT on models that never reason about the failure path. You can't detect a reasoning/code mismatch when there's no relevant reasoning.

**H2-difficulty:** Pass rates will drop sharply from B (one resource to rollback) to D (3+ resources across 4+ files). LEG rate may actually DECREASE at D because the reasoning itself becomes wrong (models can't even articulate all the resources that need compensation).

**H2-falsification:** If critique shows zero gain across all model tiers, it means either (a) models that identify the invariant also fix it (no gap to bridge) or (b) no models identify the invariant (no reasoning for critique to leverage). Both would challenge the theory.

---

### retry_state_temporal + retry_dup

**H3-base:** Baseline pass rates for retry_state_temporal will be MODERATE (30-50% for 5-mini) because temporal state reasoning is partially within capability but error-prone.

**H3-leg:** LEG rates will INCREASE with temporal depth. At B-level (2 retries, 1 state variable), LEG will be 15-25%. At D-level (nested retry with multiple state accumulators), LEG will be 35-50%. The reasoning ("state must be reset between attempts") stays simple while the implementation complexity scales.

**H3-critique-mixed:** Critique effectiveness will split by visibility: cases where the state-reset is explicitly in the model's reasoning will show critique gains. Cases where the contamination is implicit (the model didn't mention state persistence) will show no critique effect. Across the family, aggregate critique gain will be 10-20pp.

**H3-retry-dup-d:** The retry_dup_d case (exponential nested retry) will show the highest LEG in the benchmark because the model can trivially describe "don't retry if already succeeded" but implementing break/return at the correct nesting level across multiple retry boundaries is genuinely hard.

**H3-falsification:** If LEG does NOT increase with temporal depth, it means either temporal reasoning difficulty doesn't separate from execution difficulty (they fail together) or the difficulty ladder is poorly calibrated.

---

### cache_invalidation_order

**H4-base:** Baseline pass rates will be LOW-MODERATE (20-35% for 5-mini) because the "redundant operation" framing is a strong attractor toward removal.

**H4-leg:** LEG rates will be MODERATE (15-30%). The ordering constraint is articulable but the connection between "version tracking" and "conditional set" requires multi-step reasoning that may not fully appear in the reasoning trace.

**H4-critique-mixed:** Critique will help on B-level cases (where the version dependency is explicit and single-hop) but not on D-level cases (where the ordering dependency spans layers with intermediate buffering). Aggregate critique gain: 5-15pp.

**H4-difficulty:** Performance will drop more steeply from B to D than in other families because cache ordering bugs become genuinely hard to reason about at higher complexity.

**H4-falsification:** If critique helps uniformly across B/C/D, it means the ordering reasoning is more prose-visible than expected, which would upgrade this family's theory value.

---

### control_flow_path

**H5-base:** Baseline pass rates will depend heavily on case design. If cases involve genuine path interaction (one path's side effect affects another path's correctness), pass rates should be 20-40% for 5-mini.

**H5-leg:** LEG rates will be LOW-MODERATE (10-25%) because path-interaction reasoning is hard to articulate precisely. Models that reason about it will tend to get the code right; models that don't will fail at both.

**H5-critique-help:** Critique will help on cleanup-on-exit cases ("your reasoning says cleanup must run on all paths but your code has an early return that skips it") but not on guard-ordering cases (execution-order dependent).

**H5-conditional:** This family is ONLY worth the investment if cases can be designed where the path interaction is articulable in prose. If all path-interaction bugs are execution-only, the family should be deprioritized in favor of more hidden_dep_multihop or invariant_partial_fail variants.

**H5-falsification:** If this family shows no model stratification (all models fail equally), the cases are too hard or too execution-dependent for the reasoning/execution thesis.

---

## 4. Case-Expansion Strategy Inside Each Family

### hidden_dep_multihop: Add B and D to existing C

**What stays constant (family-defining):**
- Two or more functions that look interchangeable at the call site
- They differ in a semantic property hidden behind at least one hop of indirection
- The task encourages consolidation/simplification
- The bug from incorrect consolidation is SILENT (no exception, wrong behavior)
- The correct fix requires preserving the semantic distinction across all callers

**What varies (case-distinguishing):**
- The domain (cache operations, event dispatch, data transforms, serialization — each case uses a different domain)
- The number of hops in the dependency chain (B=2 hops, C=3 hops already, D=4+ hops)
- The number of files (B=2, C=4 already, D=5+)
- The specific semantic distinction (overwrite-vs-conditional, sync-vs-async, encoding-vs-raw, etc.)
- The number of callers that need correct assignment (B=2, C=3-4, D=5+)
- The trap mechanism (B: "simpler is better", C: "safer is better" already, D: "consistent is better")

**Family-preserving variation:** Changing the domain, the specific semantic distinction, and the trap mechanism while keeping the core structure (two similar-looking functions, hidden semantic difference, consolidation task).

**Family-breaking variation (DO NOT DO):** Cases where the functions are obviously different at the call site. Cases where the consolidation would cause an immediate error rather than silent wrong behavior. Cases where there's only one caller (no multi-site assignment problem).

**Difficulty progression:**
| Level | Hops | Files | Callers | Semantic distinction |
|-------|------|-------|---------|---------------------|
| B | 2 | 2 | 2 | Visible with 1 hop of tracing |
| C | 3 | 4 | 3-4 | Requires tracing through intermediate module (existing) |
| D | 4+ | 5+ | 5+ | Requires tracing through 2+ intermediate modules with one red herring module |

---

### invariant_partial_fail: Add B and D to existing C

**What stays constant (family-defining):**
- The task asks for refactoring or simplification, NOT bug-fixing
- The code contains a latent invariant violation on a failure/exception path
- The invariant is a conservation law or consistency constraint (not just "correct output")
- A correct response must both complete the refactoring AND add failure compensation
- The invariant violation is pre-existing, not introduced by the refactoring

**What varies (case-distinguishing):**
- The domain (financial transfer, resource allocation, session management, data migration)
- The number of resources that need compensation (B=1, C=2 already, D=3+)
- The number of files involved (B=2, C=4 already, D=5+)
- The specific invariant type (balance conservation, resource cleanup, referential integrity)
- The task-framing trap (B: "simplify", C: "extract helper" already, D: "optimize performance")
- The failure trigger mechanism (B: explicit error, C: random failure already, D: conditional timeout)

**Family-preserving variation:** Different domains, different invariants, different numbers of resources — but always a refactoring task that hides a latent invariant violation.

**Family-breaking variation (DO NOT DO):** Cases where the task mentions the bug or failure path. Cases where the invariant violation is introduced by the refactoring (that's a different bug class). Cases where there's no failure path (the invariant is always maintained).

**Difficulty progression:**
| Level | Resources to rollback | Files | Invariant complexity | Task misdirection strength |
|-------|----------------------|-------|---------------------|---------------------------|
| B | 1 | 2 | Single conservation law | "Clean up this module" |
| C | 2 | 4 | Dual conservation (existing) | "Extract helper, move logging" |
| D | 3+ | 5+ | Coupled invariants (A's rollback depends on B's state) | "Optimize this critical path" |

---

### cache_invalidation_order: Add B and D to existing C

**What stays constant (family-defining):**
- Cache operations where the ORDER of invalidation/set/version-bump matters
- A step that looks redundant is actually load-bearing for correctness
- The task encourages removing the "redundant" step
- The bug manifests as stale reads or lost updates, not crashes

**What varies (case-distinguishing):**
- The cache architecture (single-layer, two-layer, versioned, TTL-based)
- The specific ordering dependency (invalidate-before-set, flush-before-update, lock-before-read)
- The number of interacting operations (B=2 operations, C=3 already, D=4+ with dependent ordering)
- The trap type (B: "remove redundant call", C: "simplify redundant invalidation" already, D: "consolidate cache layers")

**Family-preserving variation:** Different cache architectures and ordering dependencies, but always a "remove the redundant operation" task that breaks correctness.

**Family-breaking variation (DO NOT DO):** Cases where the ordering doesn't matter (generic stale-cache bugs). Cases where removal causes an immediate error. Cases that are really about cache consistency without ordering (those belong in `stale_cache`).

**Distinguishing from stale_cache family:** The `stale_cache` family (which already has A/B/C) is about MISSING invalidation. `cache_invalidation_order` is about ORDERING of existing operations. The mechanism is different: stale_cache bugs are fixed by adding an invalidation call; cache_invalidation_order bugs are fixed by NOT REMOVING an existing call or by restoring correct operation order.

---

### retry_state_temporal: New sub-family (B, C, D)

**What stays constant (family-defining):**
- A retry loop where state from failed attempts persists into subsequent attempts
- The persistence is the bug — state should be reset or isolated between attempts
- The correct fix involves either resetting state before retry or scoping state per attempt
- The symptom is corrupted output, not duplicate operations (that's `retry_dup`)

**What varies (case-distinguishing):**
- The kind of state that persists (partial results, accumulators, flags, buffers)
- The number of state variables that need reset (B=1, C=2, D=3+ with dependencies)
- The retry topology (B: simple loop, C: nested retry with different state, D: saga-style with compensating actions)
- The visibility of state persistence (B: obvious accumulator, C: hidden in closure, D: spread across modules)

**Distinguishing from retry_dup:** `retry_dup` is about DUPLICATE SIDE EFFECTS (sending a message twice). `retry_state_temporal` is about STATE CONTAMINATION (attempt 2 sees partial results from attempt 1). The fix patterns are different: retry_dup fixes involve break/return/idempotence; retry_state_temporal fixes involve state reset/isolation.

---

### retry_dup: Add D to existing A/B/C

**What stays constant:** Same as existing family — duplicate side effects from retry logic.

**What varies for D:** Exponential duplication from nested retry boundaries spanning multiple modules. The D-level case should involve 3+ levels of retry nesting where each level has its own break/continue semantics and the correct fix requires changes at exactly 2 of the 3 levels.

---

### control_flow_path: New sub-family (C, D) upgrading missing_branch

**What stays constant (family-defining):**
- Multiple execution paths through a function or pipeline
- One path's side effects interact with another path's assumptions
- The bug is NOT a missing branch — all branches exist but interact incorrectly
- The fix requires reasoning about the combinatorial space of path orderings or path interactions

**What varies (case-distinguishing):**
- The kind of interaction (state mutation, resource acquisition, guard evaluation order)
- The number of interacting paths (C=2 paths, D=3+ paths)
- Whether the interaction is sequential (path A runs then path B) or conditional (path A or path B depending on input, but both modify shared state)

**NOT the same as missing_branch:** The existing missing_branch family has cases where a branch is simply missing from a conditional. control_flow_path cases have all branches present but their interactions are buggy. This is a fundamentally different reasoning demand.

---

## 5. Proposed New-Case Templates

### hidden_dep_multihop_b — "Formatter Encoding Consolidation"

- **Candidate case name:** `hidden_dep_multihop_b`
- **Difficulty target:** B (2 files, 2 hops, 2 callers)
- **Short scenario:** A text processing module has two formatting functions: `format_for_display(text)` (applies HTML entity encoding) and `format_for_storage(text)` (stores raw text). Both take a string and return a string. A utility module calls `format_for_display` for web output and `format_for_storage` for database persistence. The task asks to "consolidate these redundant formatters into a single `format_text` function."
- **Root cause:** The two functions differ in whether they HTML-encode special characters. Consolidating into the encoding version corrupts stored data with entities. Consolidating into the raw version creates XSS-vulnerable display output.
- **Likely symptom:** After consolidation, either stored data contains `&amp;` entities (if encoding version chosen) or displayed text renders raw `<script>` tags (if raw version chosen). No exception either way.
- **Plausible wrong fixes:** (1) Use encoding version everywhere — stored data is corrupted. (2) Use raw version everywhere — display is unsafe. (3) Add a parameter but default it to the wrong behavior for one caller.
- **Why critique might help:** Critique can see "your reasoning says these functions have different encoding behavior but your merged function uses only one behavior."
- **Why this fits hidden_dep_multihop:** Two functions with identical signatures and apparent purpose differ in a hidden semantic property (encoding). The task encourages harmful consolidation. The bug is silent.
- **Correctness invariant:** `format_for_display` output must have HTML entities escaped; `format_for_storage` output must be raw.

---

### hidden_dep_multihop_d — "Event Dispatch Pipeline Consolidation"

- **Candidate case name:** `hidden_dep_multihop_d`
- **Difficulty target:** D (5 files, 4+ hops, 5+ callers)
- **Short scenario:** An event processing system has `dispatch_immediate(event)` (synchronous, returns acknowledgment, used by transaction pipeline) and `dispatch_buffered(event)` (adds to batch queue, returns immediately, used by analytics pipeline). Both go through a shared `event_router` module that calls either `transport.send_sync()` or `transport.enqueue()`. A `metrics` module and a `compliance` module also call these dispatchers. The task asks to "simplify the event dispatch — there are too many similar dispatch paths doing the same thing."
- **Root cause:** `dispatch_immediate` guarantees delivery acknowledgment before the caller proceeds, which is required for transactional consistency in the order pipeline. `dispatch_buffered` batches for throughput, which is correct for analytics but would break transaction ordering if used for orders. Five callers across 3 modules need correct dispatch assignment.
- **Likely symptom:** After consolidation to buffered dispatch, the order pipeline returns "confirmed" before the event is actually delivered. Under load, events are reordered or dropped from the batch. No immediate error.
- **Plausible wrong fixes:** (1) Merge into buffered (faster, looks like an optimization). (2) Merge into immediate (slower, works but the task asked to simplify — and one caller has a good reason to batch). (3) Add a `mode` parameter but wire it wrong for the compliance module. (4) Correctly preserve both paths but miss the metrics module's requirement.
- **Why critique might help:** Critique can see "you identified that immediate dispatch provides ordering guarantees but your consolidated function doesn't preserve them for the order pipeline."
- **Why this fits hidden_dep_multihop:** Same family mechanism at higher complexity — more hops, more callers, more files. The semantic distinction (sync-vs-buffered) is different from the C-level case (put-vs-put_if_absent) to avoid benchmark contamination.
- **Correctness invariant:** `process_order` must receive acknowledgment before returning; `track_analytics` must batch for throughput; `log_compliance` must use immediate for audit trail.

---

### invariant_partial_fail_b — "Session Cleanup on Failure"

- **Candidate case name:** `invariant_partial_fail_b`
- **Difficulty target:** B (2 files, 1 resource to rollback)
- **Short scenario:** A session management module has `start_session(user_id)` that allocates a session slot (incrementing `_active_count` and adding to `_sessions` dict) and then calls `load_user_preferences(user_id)` which may fail if the user's preference file is missing. The task asks to "clean up the session module — the start_session function is too verbose with all the logging."
- **Root cause:** When `load_user_preferences` raises (missing preference file for new users), `start_session` propagates the exception without decrementing `_active_count` or removing the session from `_sessions`. The session slot is leaked.
- **Likely symptom:** After N failures, `_active_count` reaches the limit and no new sessions can be created despite no active users.
- **Plausible wrong fixes:** (1) Clean refactoring that preserves the existing leak. (2) Add a try/except that catches and logs but doesn't clean up. (3) Make `load_user_preferences` never fail (mask the bug with a default).
- **Why critique might help:** "Your reasoning says active_count must match the number of live sessions, but your refactored code doesn't decrement on failure."
- **Why this fits invariant_partial_fail:** Refactoring task that hides a latent invariant violation (active_count conservation).
- **Correctness invariant:** `_active_count == len(_sessions)` at all times.

---

### invariant_partial_fail_d — "Data Migration Pipeline Atomicity"

- **Candidate case name:** `invariant_partial_fail_d`
- **Difficulty target:** D (5 files, 3+ resources, coupled invariants)
- **Short scenario:** A data migration pipeline has 4 phases: (1) `lock_source_table()` acquires an advisory lock, (2) `copy_records(src, dst)` copies rows to the new table, (3) `update_foreign_keys(dst)` rewrites foreign key references in dependent tables, (4) `swap_table_alias(src, dst)` atomically switches the table alias. The task asks to "optimize the migration pipeline — the locking is too aggressive and the copy phase should be parallelizable."
- **Root cause:** If phase 3 fails (a dependent table has a constraint violation), the lock from phase 1 is never released, the partial copy from phase 2 leaves the destination table in an inconsistent state, and the foreign keys that WERE updated in phase 3 now point to the wrong table. Three resources need compensation: lock release, destination table cleanup, and foreign key revert.
- **Likely symptom:** After a failed migration attempt, the source table is locked forever, the destination has partial data, and some foreign keys point to the destination while others still point to the source.
- **Plausible wrong fixes:** (1) Optimize the copy phase without adding rollback (task framing). (2) Add rollback for the lock but not the partial copy or foreign keys. (3) Add rollback for lock and copy but not foreign keys (most common partial fix). (4) Retry the failed phase instead of rolling back (makes it worse — re-copies into partially copied table).
- **Why critique might help:** Critique can enumerate: "Your reasoning identifies three resources (lock, copy, foreign keys) that need compensation, but your code only rolls back two of them."
- **Why this fits invariant_partial_fail:** Multi-resource invariant violation behind a performance-optimization task. The coupling between invariants (foreign key rollback depends on knowing which keys were already updated) makes this genuinely D-level.
- **Correctness invariant:** After failed migration: source table unlocked, destination table empty or dropped, all foreign keys point to source table.

---

### cache_invalidation_order_b — "TTL Refresh Ordering"

- **Candidate case name:** `cache_invalidation_order_b`
- **Difficulty target:** B (2 files, 2 operations, single ordering dependency)
- **Short scenario:** A cache module has `refresh_entry(key)` that (1) extends the TTL and then (2) fetches fresh data from the database. The code also has a `read_entry(key)` that returns cached data if TTL is valid, otherwise returns None. A cleanup job runs periodically and evicts expired entries. The task asks to "simplify refresh_entry — the TTL extension before the fetch looks redundant since the fetch will set a new TTL anyway."
- **Root cause:** The TTL extension BEFORE the fetch prevents the cleanup job from evicting the entry while the (slow) database fetch is in progress. Removing the pre-fetch TTL extension creates a race: cleanup runs during the fetch, evicts the entry, and the fetched data is written to a key that cleanup immediately re-evicts on its next pass because the write's TTL was calculated relative to the evicted timestamp.
- **Likely symptom:** Under load, cache entries disappear immediately after refresh. No error, just cache misses.
- **Plausible wrong fixes:** (1) Remove the pre-fetch TTL extension (the attractor). (2) Remove the cleanup job (masks the bug but allows unbounded cache growth).
- **Why critique might help:** "Your reasoning says the TTL extension prevents eviction during fetch, but your simplified code removes it."
- **Correctness invariant:** After `refresh_entry(key)`, `read_entry(key)` must return the fresh value for at least `TTL_SECONDS`.

---

### cache_invalidation_order_d — "Layered Cache Version Propagation"

- **Candidate case name:** `cache_invalidation_order_d`
- **Difficulty target:** D (5 files, 4+ operations, cross-layer ordering)
- **Short scenario:** A three-layer cache system (L1 in-process, L2 shared, L3 persistent) where updates must propagate in a specific order: invalidate L1, then write L3, then set L2 (which triggers L1 re-population from L2 on next read). The system has a `version_oracle` that tracks the latest version per key. The task asks to "consolidate the cache layers — L1 and L2 do almost the same thing, and the invalidation ordering looks over-engineered."
- **Root cause:** The invalidation order (L1 first, then L3 write, then L2 set) ensures that when L1 is re-populated from L2, L2 already has the new value. Reversing to the "intuitive" order (write L3, set L2, invalidate L1) creates a window where L1 reads the OLD L2 value before L2 is updated. The version_oracle detects this and permanently marks the key as "conflicted," breaking all future reads.
- **Likely symptom:** After the "optimized" ordering, some keys permanently return None due to version conflict status. No error during the update operation itself.
- **Plausible wrong fixes:** (1) Write in "intuitive" order L3→L2→L1 (breaks version ordering). (2) Merge L1 and L2 into one layer (loses the re-population semantics). (3) Remove version_oracle (loses conflict detection entirely). (4) Add version checks at each layer (adds complexity without fixing ordering).
- **Why critique might help:** Critique can trace: "Your reasoning says L1 must be invalidated before L2 is set, but your consolidated code writes L2 before invalidating L1."
- **Correctness invariant:** After `update(key, value)`, all three layers must converge to the new value with no version conflict.

---

### retry_state_temporal_b — "Accumulator Leak Across Retries"

- **Candidate case name:** `retry_state_temporal_b`
- **Difficulty target:** B (2 files, 1 state variable, simple loop)
- **Short scenario:** A data processing function `aggregate_batch(items)` accumulates a running total in a local variable. On transient failure (network timeout fetching item details), the function retries from the beginning of the batch. But the running total is not reset, so retry-attempt-2 starts with the partial total from attempt-1 and double-counts the items that were successfully processed before the failure.
- **Root cause:** The accumulator variable is declared outside the retry loop. Each retry iteration adds to the existing total instead of starting fresh.
- **Likely symptom:** Batch totals are inflated. The inflation amount depends on where in the batch the failure occurred.
- **Plausible wrong fixes:** (1) Move the retry to individual items (changes semantics — batch must be atomic). (2) Add a deduplication check on items (doesn't help — same items, legitimately reprocessed). (3) Subtract the known-good items from the total (fragile, doesn't handle nested structures).
- **Why critique might help:** "Your reasoning says the accumulator must reflect only the current attempt's items, but your code doesn't reset it between retries."
- **Correctness invariant:** `aggregate_batch(items)` returns the same total regardless of how many retry attempts occur.

---

### retry_state_temporal_c — "Pipeline Stage State Bleed"

- **Candidate case name:** `retry_state_temporal_c`
- **Difficulty target:** C (3 files, 2 state variables, nested retry)
- **Short scenario:** A three-stage pipeline (validate → transform → persist) where each stage has its own retry logic. The `transform` stage modifies records in-place and appends transformation metadata to a shared `_audit` list. When `persist` fails and retries, it re-invokes `transform`, which re-appends audit entries and re-applies transformations to already-transformed records (double-encoding, duplicate audit entries).
- **Root cause:** Two state contamination bugs: (1) records are mutated in-place by transform, so re-transform applies encoding twice; (2) the audit list accumulates entries across retries without deduplication.
- **Likely symptom:** After a persist retry, records contain double-encoded fields and the audit log has duplicate entries with slightly different timestamps.
- **Plausible wrong fixes:** (1) Add deduplication to audit (fixes audit but not double-encoding). (2) Make transform idempotent with a "transformed" flag (works for transform but doesn't address audit). (3) Clone records before transform (fixes encoding but not audit).
- **Why critique might help:** Critique can identify: "Your reasoning mentions both double-encoding and audit duplication, but your fix only addresses one."
- **Correctness invariant:** After pipeline completion: each record transformed exactly once; audit has exactly one entry per record.

---

### retry_state_temporal_d — "Saga Compensation State Corruption"

- **Candidate case name:** `retry_state_temporal_d`
- **Difficulty target:** D (5 files, 3+ state variables, saga pattern with compensation)
- **Short scenario:** A saga-style orchestrator runs 4 steps across 4 services: (1) reserve inventory, (2) create shipment, (3) charge payment, (4) confirm order. On failure at any step, it runs compensating actions in reverse order. The orchestrator tracks compensation state in a `_compensation_log`. When step 3 (payment) fails and triggers compensation, it correctly reverses steps 2 and 1. But if the compensation for step 2 (cancel shipment) itself fails, the orchestrator retries the ENTIRE saga from step 1 — without clearing the compensation log. The second saga attempt accumulates a new compensation log on top of the first attempt's partial log.
- **Root cause:** The compensation log is not reset between saga attempts. On the second attempt, if step 3 fails again, the compensator tries to reverse entries from BOTH attempts, causing double-reversal of step 1 (inventory released twice — negative inventory) and attempting to cancel a shipment that was already cancelled.
- **Likely symptom:** Negative inventory quantities and "shipment not found" errors from the shipping service.
- **Plausible wrong fixes:** (1) Add idempotence to each compensation action (doesn't fix double-release of inventory — idempotent release still releases once, but the saga log has two entries for the same reservation, causing it to call release twice with different reservation IDs if each attempt gets a different reservation). (2) Clear the log between attempts (loses the record of what was compensated in the first attempt — needed for audit). (3) Add a "compensated" flag per log entry (fixes double-compensation but the saga still re-reserves inventory from attempt 2 without cleaning up the new reservation on failure). (4) Reset only the compensation_status but not the actions (partial fix).
- **Why critique might help:** Limited. The state interactions are complex enough that critique would need to trace 4-step execution paths across retry boundaries. This is near the limit of prose-based mismatch detection.
- **Correctness invariant:** After any number of saga attempts: inventory quantities >= 0; no orphaned shipments; no orphaned charges; compensation log is consistent with actual system state.

---

### retry_dup_d — "Triple-Nested Retry Exponential Duplication"

- **Candidate case name:** `retry_dup_d`
- **Difficulty target:** D (4 files, 3 retry boundaries, exponential duplication)
- **Short scenario:** A message processing pipeline has three levels of retry: (1) `ingestion_gateway` retries on HTTP failure (max 2), (2) `message_router` retries on routing failure (max 2), (3) `delivery_agent` retries on delivery failure (max 2). Each level wraps the next. A transient failure at the delivery level causes the router to retry delivery (2 sends), then the gateway sees the router "fail" and retries the whole router (now 4 sends), and the gateway's own retry produces 8 sends total. The message store receives 8 copies.
- **Root cause:** None of the three retry levels has a break/return after success, and the inner levels' success is not properly signaled to outer levels. The fix requires adding break at exactly the router and gateway levels (not the delivery level, which already has correct break logic — a trap).
- **Likely symptom:** Message appears 8 times in the store. Message count grows exponentially with retry depth.
- **Plausible wrong fixes:** (1) Add break to all three levels (changes delivery semantics — delivery level's retry is intentionally exhaustive). (2) Add break only to gateway (reduces from 8 to 4, not 1). (3) Add deduplication at the store level (masks the bug — still wastes resources on 8 network calls). (4) Reduce retry counts (reduces severity but doesn't fix the mechanism).
- **Why critique might help:** "Your reasoning identifies that gateway and router lack break-on-success, but your fix adds break to all three levels, including delivery which intentionally retries."
- **Correctness invariant:** Each message appears exactly once in the store regardless of transient failures.

---

### control_flow_path_c — "Guard-Order State Mutation"

- **Candidate case name:** `control_flow_path_c`
- **Difficulty target:** C (3 files, 2 interacting paths)
- **Short scenario:** A request handler has two guards: `rate_limit_check(request)` and `auth_check(request)`. Both guards have side effects: rate_limit_check increments a counter for the user's IP, and auth_check logs the authentication attempt. The guards are evaluated in order: rate_limit → auth. The bug is that rate_limit_check runs and increments the counter BEFORE auth_check runs. For unauthenticated requests, the rate limit counter is incremented even though the request will be rejected by auth. An attacker can exhaust a legitimate user's rate limit by sending unauthenticated requests with the user's IP.
- **Root cause:** Guard evaluation order: rate-limiting before authentication means unauthenticated requests consume rate-limit quota.
- **Likely symptom:** Legitimate users get rate-limited after an attacker sends many unauthenticated requests from the same IP range.
- **Plausible wrong fixes:** (1) Add rate-limit exemption for unauthenticated requests (defeats purpose of rate limiting). (2) Move rate limiting into the auth handler (couples concerns incorrectly). (3) Add a "rollback" to decrement on auth failure (works but fragile — races, and any new guard between them breaks it). (4) Correct fix: swap guard order (auth first, rate-limit only for authenticated requests).
- **Why critique might help:** "Your reasoning says rate limiting should only apply to authenticated requests, but your code still evaluates rate_limit_check before auth_check."
- **Correctness invariant:** Unauthenticated requests must NOT increment rate-limit counters for any user.

---

### control_flow_path_d — "Cleanup-on-Exit with Exception Interaction"

- **Candidate case name:** `control_flow_path_d`
- **Difficulty target:** D (4 files, 3+ interacting paths, exception-path interaction)
- **Short scenario:** A resource-management pipeline acquires three resources in sequence: (1) database connection, (2) file lock, (3) remote API session. The pipeline has three exit paths: normal completion (releases all three in reverse order), early return on validation failure (should release only the resources acquired so far), and exception during processing (should release all acquired resources via finally). The task asks to "simplify the resource management — there's too much repetitive cleanup code."
- **Root cause:** The "simplified" version uses a single finally block that unconditionally releases all three resources. But when validation fails after acquiring only the DB connection (step 1), the finally block tries to release the file lock (step 2) and API session (step 3) that were never acquired, causing secondary exceptions that swallow the original validation error.
- **Likely symptom:** Validation failures produce "NoneType has no attribute 'release'" errors instead of the original validation error. The original error is lost.
- **Plausible wrong fixes:** (1) Add None checks to the finally block (works but violates the "simplify" goal — now there's MORE code). (2) Use a blanket try/except in finally that catches release errors (swallows secondary errors but loses diagnostic info). (3) Use context managers (correct approach but requires understanding which resources are conditionally acquired). (4) Move all acquisition to the top (changes semantics — acquires resources that may not be needed).
- **Why critique might help:** "Your reasoning says cleanup must be conditional on what was acquired, but your simplified code unconditionally releases all resources."
- **Correctness invariant:** (1) No resource leak on any exit path. (2) Original exception is propagated on error paths, not swallowed by cleanup exceptions. (3) Release is only called for resources that were successfully acquired.

---

## 6. Similar-But-Not-Too-Similar Design Rules

### Code-level reuse rules

1. **Zero code-level reuse across cases within a family.** Each case must use a completely different domain (cache operations, event dispatch, text formatting, resource management, etc.). No shared variable names, no shared function names, no shared module names.
2. **No shared domains across priority families.** If hidden_dep_multihop_b uses text formatting, no other family's cases may use text formatting as their domain.
3. **Code structure may be analogous but not isomorphic.** Two cases may both have "module A calls module B calls module C" structure, but the internal logic of each module must be domain-specific, not a find-and-replace transformation of another case.

### Bug-mechanism reuse rules

4. **The family-level mechanism MUST be reused — that's what defines the family.** For hidden_dep_multihop, every case must involve consolidation of semantically-different functions. For invariant_partial_fail, every case must involve a latent invariant violation hidden by a refactoring task.
5. **The specific instantiation of the mechanism must differ.** If case C uses "overwrite vs. conditional write" as the semantic distinction, case B must use a different distinction (e.g., "encoding vs. raw"). The MODEL should not be able to learn "in hidden_dep problems, always check for put vs. put_if_absent."
6. **At most two cases in a family may share the same trap type.** If case B's trap is "pick the simpler option," case D's trap must NOT also be "pick the simpler option."

### Symptom variation rules

7. **Each case in a family must have a different symptom.** For hidden_dep_multihop: stale data (existing C), corrupted encoding (proposed B), lost ordering guarantees (proposed D). No two cases may manifest as the same observable failure.
8. **Symptoms must be at different observability levels.** At least one case per family should have an easy-to-observe symptom (wrong output) and at least one should have a hard-to-observe symptom (subtle data corruption or race condition).

### Trap variation rules

9. **Traps must pull toward different wrong fixes.** If case B's trap makes the model choose the "safer" option, case D's trap must make the model choose the "more consistent" or "more efficient" option.
10. **The plausible wrong fix set must be disjoint across cases.** If case B's wrong fixes are {encode-everything, raw-everything, wrong-default}, case D's wrong fixes must not include any of these.

### Anti-contamination rules

11. **No case's correct fix should transfer to another case in the same family.** If learning "always use cache_put, not cache_put_if_absent" would fix case C, no other case in the family should be fixable by the same rule. Each case must require family-mechanism reasoning, not pattern matching.
12. **The test-discoverable information must differ.** If a model reads the test for case B and discovers the invariant, that knowledge must not help with case D's invariant. Tests must be case-specific, not family-generic.
13. **Anti-memorization rule:** No case's code should be derivable from another case's code by mechanical substitution (e.g., replacing "cache" with "event" and "put" with "dispatch"). The code structures, control flows, and module interaction patterns must be structurally different even if the family mechanism is the same.

---

## 7. Critique-Visibility Analysis

### hidden_dep_multihop — CRITIQUE HIGHLY VISIBLE

**Can critique detect the mismatch?** YES, strongly. The reasoning almost always articulates the semantic distinction ("function A always overwrites, function B is conditional") and the code almost always violates it ("I merged them into one"). This is a textbook reasoning/code mismatch.

**Visibility mechanism:** The mismatch is between a stated PROPERTY ("these functions have different semantics") and a code DECISION ("I used only one semantic"). This is visible in prose without execution.

**Effective critique prompt:** "Your reasoning identifies that [function X] and [function Y] have different behavior regarding [specific property]. Does your refactored code preserve both behaviors for all callers? For each caller, state which behavior it requires and verify your code provides it."

**Useless critique:** Generic "is your code correct?" prompts that don't reference the specific semantic distinction identified in the reasoning.

**Critique ceiling:** ~80% of LEG cases should be detectable by critique in this family. The remaining ~20% are cases where the model's reasoning doesn't articulate the distinction clearly enough for critique to detect the mismatch.

---

### invariant_partial_fail — CRITIQUE HIGHLY VISIBLE (conditional)

**Can critique detect the mismatch?** YES, but ONLY when the model's reasoning mentions the invariant or failure path. If the model's reasoning says "I'll extract a clean helper that does debit then credit," a critique can ask "does your helper maintain the invariant when credit fails?" If the model's reasoning never considers failure, critique has nothing to work with.

**Visibility mechanism:** The mismatch is between a stated INVARIANT ("balance must be conserved") and a code OMISSION (no rollback on the exception path). Conservation laws are easy to check in prose: "if A decreases, B must increase by the same amount."

**Effective critique prompt:** "Your reasoning mentions [invariant]. Trace the exception path through your refactored code. At each point where an exception could occur, verify that all previously-committed mutations are compensated."

**Useless critique:** "Does your refactoring preserve behavior?" — too vague to trigger failure-path analysis. "Is your code clean?" — reinforces the refactoring frame that caused the bug.

**Critique ceiling:** ~60% of LEG cases (conditioned on the model having mentioned the failure path in reasoning). For models that never mention the failure path, critique ceiling is ~10% (unlikely to introduce the concept from scratch).

---

### retry_state_temporal — CRITIQUE PARTIALLY VISIBLE

**Can critique detect the mismatch?** SOMETIMES. Cases where the model explicitly states "state must be reset between retries" but generates code without a reset are critique-visible. Cases where state contamination is implicit (closure captures, module-level variables) are harder for critique to detect without execution.

**Visibility mechanism:** When visible, the mismatch is between a stated REQUIREMENT ("clean state per attempt") and code STRUCTURE (variable declared outside the retry loop). When invisible, the contamination is an execution-order effect that critique can't trace.

**Effective critique prompt:** "For each variable that accumulates state across the retry loop, verify that it is reset at the start of each retry iteration. List every variable modified inside the retry body and check whether its initial value is correct on retry attempt N > 1."

**Useless critique:** "Is your retry logic correct?" — too vague. "Will this handle transient failures?" — focuses on the retry mechanism, not on state across retries.

**Critique ceiling:** ~50% of LEG cases at B difficulty, ~30% at D difficulty (state interactions become too complex for prose analysis).

---

### cache_invalidation_order — CRITIQUE PARTIALLY VISIBLE

**Can critique detect the mismatch?** SOMETIMES. The version dependency ("invalidation bumps the version that conditional set checks") is articulable, and if the model's reasoning mentions it, critique can verify the code preserves it. But ordering effects between cache layers are hard to reason about in prose.

**Visibility mechanism:** When visible, the mismatch is between a stated ORDERING CONSTRAINT ("invalidation must happen before set") and code ORDER (set happens before or instead of invalidation). When invisible, the effect is an interleaving of operations that prose can't capture.

**Effective critique prompt:** "Your reasoning says [operation A] must happen before [operation B] because [dependency]. Verify that your code preserves this ordering. Trace what happens if the operations execute in the opposite order."

**Useless critique:** "Is the cache consistent?" — doesn't pinpoint the ordering dependency. "Will stale data be served?" — too generic to identify the specific ordering bug.

**Critique ceiling:** ~55% at B difficulty (single ordering dependency), ~25% at D difficulty (cross-layer ordering with intermediate buffering).

---

### control_flow_path — CRITIQUE MIXED

**Can critique detect the mismatch?** DEPENDS ON THE CASE. Cleanup-on-exit cases are critique-visible: "your reasoning says cleanup must run on all paths but your code has an early return that skips it." Guard-ordering cases are execution-only: "the rate limiter fires before auth" is an ordering effect that requires execution trace analysis.

**Visibility mechanism:** For cleanup cases: the mismatch is between a stated GUARANTEE ("all resources are released") and a code PATH (early return that doesn't release). For guard cases: the mismatch is between an ASSUMED ORDERING ("auth first, then rate limit") and actual code ordering.

**Effective critique prompt (cleanup cases):** "For each resource acquired in your code, trace every possible exit path (normal return, early return, exception) and verify the resource is released on every path."

**Effective critique prompt (guard cases):** "List the side effects of each guard in your handler. For the case where a later guard rejects the request, verify that earlier guards' side effects are appropriate."

**Useless critique:** "Is your error handling complete?" — doesn't differentiate between paths.

**Critique ceiling:** ~60% for cleanup cases (path enumeration is prose-tractable). ~20% for guard-ordering cases (ordering is execution-dependent).

---

## 8. Expansion Constraints

### Mandatory constraints for all new cases

**EC-1: Plausible wrong fix.** Every new case must have at least one plausible wrong fix that a model would reasonably produce. The wrong fix must be MORE obvious than the correct fix (fewer hops, simpler change, or matches the task framing).

**EC-2: Distractor at B+.** Every B-level or higher case must include at least one distractor: a code element that looks like the bug location but isn't (e.g., a function that touches the same state but isn't the root cause).

**EC-3: Multi-hop or cross-file at C+.** Every C-level or higher case must involve either multi-hop reasoning (3+ hops from symptom to root cause), cross-file dependency (root cause in different file from symptom), or temporal/state interaction (bug depends on execution order).

**EC-4: Distinguishing invariant.** Every case must have a testable invariant that distinguishes the root fix from symptom patches. The invariant must be checkable in a test without execution-order dependence (no flaky invariants).

**EC-5: Critique plausibility for Rank 1-2 families.** Every case in hidden_dep_multihop and invariant_partial_fail must be designed so that critique has at least a 40% chance of detecting a reasoning/code mismatch (assuming the model's reasoning contains the relevant information). This means the mismatch must be articulable in prose.

**EC-6: Silent failure.** For hidden_dep_multihop and cache_invalidation_order cases, the bug must produce no exception or error message. The failure must be behavioral (wrong output, stale data, corrupted state) and discoverable only by checking the invariant.

**EC-7: Task-framing misdirection.** For invariant_partial_fail cases, the task prompt must NOT mention the bug, the invariant, or the failure path. The task must frame the code as correct-but-messy and ask for structural improvement.

**EC-8: State-reset testability.** For retry_state_temporal cases, the test must be deterministic: it must be possible to trigger the exact failure pattern (which attempt fails, when it fails) using injectable failure triggers, not random failure.

### Additional constraints

**EC-9: No trivial fixes.** No case should be fixable by a single-token change (flipping an operator, adding a `not`, etc.). The minimum fix complexity is 2+ lines or 1 line with non-trivial content.

**EC-10: Family-unique domain.** No two cases within the same family may share the same application domain. If case B uses text formatting, case D must use something entirely different.

**EC-11: Anti-transfer.** No case's correct fix pattern should be mechanically transferable to another case in the same family. The fix must require case-specific reasoning, not family-level pattern matching.

**EC-12: Difficulty monotonicity.** Within each family, pass rates must be expected to decrease monotonically from B to D. If a proposed D-level case is expected to be easier than the existing C-level case, it should be re-designed or re-classified.

---

## 9. What NOT to Expand

### wrong_condition (A/B/C) — DO NOT EXPAND

**Why not:** The bug mechanism (wrong boolean operator, wrong comparison, wrong precedence) is fully mechanical. The reasoning IS the fix — identifying `>` should be `>=` is the entire challenge. There is no reasoning/execution gap: a model that identifies the wrong condition will flip it correctly, and a model that doesn't identify it cannot be helped by critique. This family produces ceiling/floor effects, not gradients.

**Theory weakness:** Critique has nothing to detect. The mismatch between "your reasoning says >= is needed" and "your code uses >" is too trivial to be informative. No model produces an elaborate wrong-condition analysis and then implements the wrong condition.

### index_misalign (A/B/C) — DO NOT EXPAND

**Why not:** Parallel-array alignment bugs are purely structural. The fix is always "update the other array(s) when you update one." There are no multiple plausible wrong fixes (you either update all arrays or you don't). Critique cannot detect anything beyond what the model already sees. No reasoning/execution separation.

### mutable_default (A/B/C) — DO NOT EXPAND

**Why not:** This is a Python-specific idiom bug. Models either know the mutable-default-argument pattern or they don't. There is no causal reasoning involved — it's pattern recognition. Adding more cases of `def f(x=[])` in different contexts doesn't test reasoning, it tests memorization.

### silent_default (A/B/C) — DO NOT EXPAND

**Why not:** The bug mechanism (key mismatch in dict/config lookup falling to default) is mechanical and deterministic. The reasoning is straightforward: trace the key name through the lookup chain. No reasoning/execution gap — models that trace the key correctly will fix it; models that don't won't be helped by critique.

### early_return (A/B/C) — DO NOT EXPAND

**Why not:** While early-return bugs can involve cross-file reasoning (C-level), the fix pattern is always the same: move the audit/logging call before the early return, or add it to the early-return path. This is a single-pattern family with low variation potential. Critique adds nothing because the mismatch ("should log on all paths" → "code doesn't log on early return") is too simple.

### use_before_set (A/B/C) — DO NOT EXPAND

**Why not:** Uninitialized variable bugs are detectable by static analysis. The reasoning challenge is low (identify which path doesn't set the variable). No meaningful reasoning/execution separation. Models that see the bug fix it trivially.

### partial_update (A/B/C) — DO NOT EXPAND (with reservation)

**Why not:** Partial-update bugs ("update field A but not derived field B") are mechanical checklist bugs. The reasoning is "enumerate all dependent fields." While this COULD be deepened (more fields, more dependencies), the reasoning challenge doesn't scale well — it's always "check more fields," not "reason more deeply."

**Reservation:** If partial_update cases were combined with hidden dependencies (the dependent field is in another module, connected by a non-obvious chain), they would become theory-useful. But that's really a hidden_dep case, not a partial_update case.

### alias_config (A/B/C) — DO NOT EXPAND

**Why not:** Shared-reference aliasing is a Python-specific pattern. The fix is always `.copy()` or `deepcopy()`. Single-pattern family with no variation in fix strategy.

### effect_order (A/B/C) — DO NOT EXPAND

**Why not:** While effect ordering is related to temporal reasoning, the existing cases are about "batch vs. per-item" side effects, which is a mechanical pattern. The fix is always "move the side effect inside the loop." This doesn't test the kind of complex temporal reasoning that retry_state_temporal targets.

### temporal_drift (A/B/C) — DEPRIORITIZE (overlap with cache_invalidation_order)

**Why not now:** Temporal drift (computing statistics on post-transformed data) overlaps with cache_invalidation_order's ordering concern. Expanding cache_invalidation_order covers the ordering-reasoning space more cleanly.

---

## 10. Experimental Payoff

### What this plan enables

If executed well, these 14 new cases (plus 44 existing family-level cases, plus the 13 existing singletons) would produce a benchmark of 71 total cases where the 5 priority families contribute 16 theory-critical cases with full difficulty ladders.

### LEG measurement

The priority families are specifically designed to produce LEG. A model that articulates "these functions have different semantics" (correct reasoning) but generates code that uses only one semantic (wrong execution) is a textbook LEG case. With 3-4 cases per family across B/C/D difficulty, we can measure:

1. **LEG rate per family:** Which mechanisms produce the most reasoning/execution separation?
2. **LEG rate vs. difficulty:** Does LEG increase with causal depth within a family?
3. **LEG rate vs. model tier:** Which model tiers show the most LEG? (Hypothesis: mid-tier models show the most LEG because weak models fail at reasoning AND execution, while strong models succeed at both.)

### Critique usefulness

The critique-visibility analysis (Section 7) predicts that critique will be highly effective for hidden_dep_multihop and invariant_partial_fail, moderately effective for retry_state_temporal and cache_invalidation_order, and mixed for control_flow_path. This prediction is directly testable:

1. **Critique gain per family:** Does critique improve pass rates more in high-visibility families?
2. **Critique gain vs. difficulty:** Does critique effectiveness decay at higher difficulty (D-level)?
3. **Critique gain vs. model tier:** Is critique more useful for mid-tier models (where it can bridge a reasoning/execution gap) than for weak models (where there's no correct reasoning to leverage)?

If critique gain correlates with the predicted visibility scores, the theory is supported. If not, the visibility analysis needs revision.

### Family-level heterogeneity

With 3-4 cases per priority family, we can compute meaningful per-family statistics:

1. **Family-specific critique sensitivity:** Some families should show strong critique gains while others show weak or negative gains. This is a testable prediction, not just aggregation noise.
2. **Family-specific difficulty gradients:** The slope of pass-rate-vs-difficulty should differ across families. Steep slopes indicate the family tests a genuine scaling phenomenon. Flat slopes indicate the family's difficulty variation is noise.
3. **Family-specific model stratification:** Some families should stratify models sharply while others show ceiling or floor effects. The Rank 1-2 families should show the strongest stratification.

### Model-level heterogeneity

Across the 5 model tiers (nano, 4o-mini, 5-mini, 5.4-mini, GPT-5), the expanded benchmark should reveal:

1. **Tier-specific LEG profiles:** Do weaker models show LEG on easier cases while stronger models show LEG on harder cases? Or do weaker models simply fail at both reasoning and execution?
2. **Tier-specific critique sensitivity:** Do mid-tier models benefit most from critique (they have correct reasoning that needs execution assistance)?
3. **Capability thresholds:** At what difficulty level does each model tier transition from "reasoning-right/execution-wrong" (LEG) to "reasoning-wrong/execution-wrong" (complete failure)?

### Paper-quality claims

With this expanded benchmark, the paper can make the following claims:

1. **"Structured reasoning scaffolding helps when models already identify the correct bug mechanism."** Supported by: critique gain in families where the model's reasoning contains the correct diagnosis (hidden_dep_multihop, invariant_partial_fail).

2. **"Structured reasoning scaffolding hurts or is neutral when the model's reasoning is wrong."** Supported by: critique having no effect (or negative effect) on models that don't identify the correct mechanism, even in high-visibility families.

3. **"LEG increases with causal depth within families that separate reasoning from execution."** Supported by: B-to-D LEG gradients in hidden_dep_multihop and retry_state_temporal.

4. **"Not all bug families are equally theory-informative."** Supported by: mechanical families (wrong_condition, index_misalign, mutable_default) showing no LEG or critique effect, while reasoning-heavy families show both.

5. **"Family-level analysis is necessary; aggregate benchmark scores obscure the mechanism."** Supported by: different families showing qualitatively different critique sensitivity patterns, which would wash out in an aggregate score.

These claims are specific, falsifiable, and directly enabled by the family-deepening strategy proposed in this plan. A broadening strategy (many unrelated cases) would not support claims 3, 4, or 5.

---

## Appendix A: Complete Case Allocation Summary

| Family | Existing Cases | New Cases | Post-expansion |
|--------|---------------|-----------|----------------|
| hidden_dep_multihop | 1 (C) | +2 (B, D) | B/C/D |
| invariant_partial_fail | 1 (C) | +2 (B, D) | B/C/D |
| cache_invalidation_order | 1 (C) | +2 (B, D) | B/C/D |
| retry_state_temporal | 0 | +3 (B, C, D) | B/C/D (new sub-family) |
| retry_dup | 3 (A/B/C) | +1 (D) | A/B/C/D |
| control_flow_path | 0 (missing_branch A/B/C is related but different) | +2 (C, D) | C/D (new sub-family) |
| **TOTAL** | 6 | **+12** | 18 |

**Net new cases: 12** (within the 12-16 target range)

If additional cases are desired, the next-highest-value additions would be:
- invariant_partial_fail_a (A-level, to complete A/B/C/D ladder) — +1
- hidden_dep_multihop_a (A-level, same reason) — +1
- retry_state_temporal_a (A-level, same reason) — +1

These would bring the total to 15, but A-level cases in these families risk being too easy to produce useful theory signal.

---

## Appendix B: Implementation Priority Order

If cases must be implemented incrementally, the priority order is:

1. **hidden_dep_multihop_b** — Highest-value single case (fills the B-level gap in the #1-ranked family)
2. **invariant_partial_fail_b** — Same rationale for #2-ranked family
3. **retry_state_temporal_c** — Introduces the new sub-family at its most theory-useful difficulty level
4. **hidden_dep_multihop_d** — Completes the #1-ranked family's difficulty ladder
5. **invariant_partial_fail_d** — Completes the #2-ranked family's difficulty ladder
6. **retry_dup_d** — Extends an existing well-understood family
7. **cache_invalidation_order_b** — Fills the B-level gap in #4-ranked family
8. **retry_state_temporal_b** — Easier entry point for the new sub-family
9. **retry_state_temporal_d** — Hardest temporal case
10. **cache_invalidation_order_d** — Completes #4-ranked family
11. **control_flow_path_c** — Introduces upgraded family at C-level
12. **control_flow_path_d** — Hardest path-interaction case
