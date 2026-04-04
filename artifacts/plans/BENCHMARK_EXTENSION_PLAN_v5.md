# Benchmark Extension Plan v5 — Case-Authoring + Measurement Protocol

**Date:** 2026-04-01
**Status:** PLAN ONLY
**Supersedes:** BENCHMARK_EXTENSION_PLAN_v4.md

---

## Revision History

| Version | Changes |
|---|---|
| v1 | 13 cases: LEG (4), concurrency (4), pressure (2), write-from-scratch (3) |
| v2 | +3 cases: false competence (2), L3 concurrency (1). Trace-output hooks. Replay tests. Self-contradiction protocol. |
| v3 | +2 LEG cases (17-18). Causal relation hooks on all LEG cases. false_competence_rate metric. |
| v4 | Structural overhaul. Family discriminator rules. Two-pass construction/annotation separation. Stage-gated flow. Stress-test case policy. |
| **v5** | Added observed-behavior validation layer (Stage 2). Trap activation requirement. Intervention probes mandatory. Benchmark-level completion criteria. Forced disambiguation rule for family assignment. Operationalized all vague criteria. Gold-standard family spec + example case. |

---

## 1. Executive Summary

This plan defines the full protocol for extending the CS372 benchmark with new cases that measure causal reasoning failures in LLM code generation.

It covers two distinct protocols:

1. **Case Design Protocol** — how to construct a structurally valid case (mechanism, traps, invariants, validation matrix).
2. **Observed Behavior Validation Protocol** — how to verify that models actually exhibit the intended failure pattern during calibration, and that the case is sensitive to at least one intervention.

A case is **not benchmark-valid** merely because:
- the reference fix passes
- trap fixes fail
- invariants discriminate

A case is benchmark-valid only when:
- it passes the full design validation (Stage 1)
- models actually exhibit the intended family failure pattern during calibration (Stage 2)
- at least one defined trap is chosen by ≥20% of failed model attempts (Stage 2)
- the case's intervention sensitivity is measured and classified (Stage 2)

The primary unit of analysis is the **case**. All design decisions prioritize case quality and diagnostic sharpness over family balance.

---

## 2. Core Design Principles

**P1. Case quality over coverage balance.**
No case may be kept merely to satisfy a distribution quota.

**P2. Cases measure reasoning failure, not bug difficulty.**
Extension cases classify by the type of reasoning-to-code failure, not the type of bug.

**P3. Traps must be structurally plausible.**
Every wrong fix must be something a competent developer could plausibly write given partial understanding. A trap that no model ever chooses is not a real trap.

**P4. Construction precedes annotation.**
Case authors build the mechanism, trap, and invariants first. Intervention hypotheses are assigned only after the case is finalized.

**P5. Validation requires observed behavior.**
No case enters the benchmark without both (a) a completed validation matrix and (b) calibration data showing models actually exhibit the intended failure pattern.

**P6. Invariants must discriminate.**
Every case must have at least one invariant that separates the true fix from every plausible trap fix. If no such invariant exists, the case is invalid.

**P7. Intervention sensitivity must be measured.**
Every case must have calibration data for baseline, critique, and reasoning-only conditions. Cases without measured intervention sensitivity are labeled `intervention-insensitive` in benchmark metadata.

---

## 3. Case Authoring Protocol

Every step must be completed in order.

### Step 1: Mechanism Selection

- Choose one failure family from Section 4.
- Read the family discriminator (inclusion rule, exclusion rule, adjacent-family boundary).
- State in writing:
  - Which family this case belongs to
  - Why it satisfies the inclusion rule
  - Why it does not belong in the most similar adjacent family

**Forced disambiguation rule:** If a case admits two or more comparably plausible causal hypotheses that require cross-function or cross-module evidence to disambiguate, it MUST be classified as `misinferred_dependency`. Classification as `false_fix_attractor` is permitted ONLY when there is exactly one dominant wrong target that is visibly more attractive than all alternatives due to symptom proximity or structural simplicity.

If the case spans two families and cannot be cleanly classified, it is a stress-test case (Section 6).

### Step 2: Causal Graph Sketch

Define the following nodes and edges in writing:

- **Symptom node**: the observable failure
- **True root cause**: the actual source of the failure
- **Plausible wrong cause(s)**: at least one alternative explanation that is structurally plausible (not merely possible)
- **Intervention points**: where in the code a fix could be applied
- **Trap path**: the reasoning path from symptom → wrong cause → wrong fix
- **Why the trap is plausible**: what local evidence supports the wrong cause

### Step 3: Trap Design

For each wrong fix:
- Define the concrete code change
- State why the fix is structurally plausible (what evidence supports it)
- State why the fix fails globally (what invariant or test it violates)
- Verify the fix addresses the symptom at least partially (a trap that obviously does nothing is not a trap)

Minimum trap count:
- A-level cases: at least 2 trap fixes
- B-level and C-level cases: at least 3 trap fixes

### Step 4: Invariant Design

Define three classes of invariants:

1. **Trap-catching invariant**: at least one assertion that fails for every defined trap fix.
2. **Generalization invariant**: at least one assertion that catches hardcoded or input-specific fixes. Must use at least two distinct input configurations.
3. **Causal-location invariant** (where applicable): an assertion that fails when the fix is applied at the wrong layer, function, or scope, even if the primary symptom is repaired.

### Step 5: Reference Fix

- Define the unique correct intervention.
- Explain why each trap fix does not satisfy all invariants.
- If multiple semantically distinct fixes could pass all invariants, either:
  - Redesign the invariants to discriminate, or
  - Document the accepted equivalence class and state why all members reflect correct causal understanding.

### Step 6: Validation Matrix

Produce a concrete table:

| Variant | Trap-catching | Generalization | Causal-location | Overall |
|---|---|---|---|---|
| No-op (original bug) | FAIL | FAIL | N/A | FAIL |
| Reference fix | PASS | PASS | PASS | PASS |
| Trap fix 1 | PASS | FAIL | PASS | FAIL |
| Trap fix 2 | FAIL | PASS | FAIL | FAIL |
| Trap fix 3 | PASS | PASS | FAIL | FAIL |

Every row must be verified by running actual code, not predicted.

### Step 7: Difficulty Assignment

Assign A, B, or C using structural properties only:

| Property | A | B | C |
|---|---|---|---|
| Files involved | 1 | 1-2 | 2-3 |
| Causal hops to root cause | 1 | 2 | 3+ |
| Distractor functions | 0 | 1-2 | 3+ |
| Competing plausible causes | 1 | 2 | 3+ |
| Cross-boundary reasoning | No | Partial | Required |

Difficulty is a structural property of the case, not an empirical observation.

### Step 8: Post Hoc Hypothesis Annotation (SEPARATE PASS)

Only after Steps 1-7 are complete and the case passes Stage 1 validation:

- Expected regime hypothesis (which quadrant: correct/correct, correct/incorrect, incorrect/correct, incorrect/incorrect)
- LEG susceptibility: none / low / medium / high (defined as: what fraction of failed attempts are expected to have correct mechanism identification)
- Intervention hypothesis: critique-sensitive / reasoning-only-sensitive / retry-sensitive / intervention-insensitive
- Expected reconstruction burden: low / medium / high

**Hard rule:** The person constructing the case must not use intervention expectations as a guide for shaping the trap or invariants. Hypothesis annotation is descriptive, not prescriptive.

---

## 4. Failure Family Definitions

Each family classifies a distinct type of reasoning-to-code failure.

Every family includes these mandatory subsections:

1. Failure Mechanism
2. Inclusion Rule
3. Exclusion Rule
4. Adjacent-Family Boundary
5. Structural Difficulty Ladder
6. Observed Failure Pattern to Validate
7. Intervention Probe Hypotheses
8. Calibration Criteria
9. Minimum Trap Activation Pattern

---

### 4.1 false_fix_attractor

**Failure Mechanism:** The model identifies the correct symptom but is drawn to a plausible wrong fix that addresses the visible manifestation rather than the underlying cause. The wrong fix is attractive because it is symptom-proximal and structurally simpler than the true fix.

**Inclusion Rule:** The primary failure is that the model applies a fix to the wrong target (wrong function, wrong variable, wrong layer) because that target is closer to the symptom than the true root cause. There is exactly one dominant wrong target that is visibly more attractive than alternatives.

**Exclusion Rule:** If the model's reasoning correctly identifies the root cause AND the root cause location but the implementation is merely buggy (off-by-one, wrong operator, incomplete), that belongs in intervention_boundary. If multiple comparably plausible wrong targets exist, it belongs in misinferred_dependency. The distinguishing feature of false_fix_attractor is exactly one dominant wrong *target*, not wrong *implementation* and not multiple competing hypotheses.

**Adjacent-Family Boundaries:**

- vs `control_flow_trap`: false_fix_attractor patches the wrong target. control_flow_trap patches the wrong branch. If the error is "which function to fix," it's false_fix_attractor. If the error is "which execution path is taken," it's control_flow_trap.
- vs `misinferred_dependency`: false_fix_attractor has one dominant wrong target that is attractive due to proximity. misinferred_dependency has two or more competing plausible causes that require disambiguation. Operational test: if a reviewer can identify a second comparably plausible cause that implies a different fix, the case is misinferred_dependency.

**Structural Difficulty Ladder:**
- A: wrong target in same file, single-hop misdirection
- B: wrong target across functions, distractor function present
- C: wrong target across files, attractor competes with root cause for salience

**Observed Failure Pattern to Validate:**
In Stage 2, classify each failed model output into:
- **Attractor chosen:** model's code change targets the attractor (symptom-proximal wrong target)
- **True-fix direction:** model targets the correct root cause but implementation is wrong
- **Unrelated failure:** model produces an unrelated fix (wrong function, parse error, etc.)

Validation threshold: ≥50% of failures must be "attractor chosen." Otherwise the case does not function as intended for this family.

**Intervention Probe Hypotheses:**
- Critique may help if it redirects attention from symptom to root cause
- Reasoning-only may help if re-prompting triggers deeper causal analysis
- Empirical finding from current benchmark: critique and reasoning-only are statistically indistinguishable on average. Case-level variation may differ.

**Calibration Criteria:**
- Baseline pass rate must be between 10% and 90% (not floor, not ceiling)
- At least one intervention delta ≥10pp, OR explicitly labeled intervention-insensitive

**Minimum Trap Activation Pattern:**
In Stage 2, the primary attractor trap must be chosen by ≥20% of failed model attempts across the calibration model set. If no trap reaches 20%, the attractor is too weak — redesign or drop.

---

### 4.2 control_flow_trap

**Failure Mechanism:** The model misunderstands which execution path is taken at runtime and fixes the wrong branch, handler, or dispatch target.

**Inclusion Rule:** The root cause is misrouting — execution enters the wrong branch, case, or handler. The model fixes logic within a handler rather than fixing the routing itself.

**Exclusion Rule:** If the code takes the correct path but produces the wrong result due to a logic error within that path, this is not a control_flow_trap. The model must be misled about *which path* executes, not merely about *what the path does*.

**Adjacent-Family Boundaries:**
- vs `false_fix_attractor`: control_flow_trap is about routing error (which path runs). false_fix_attractor is about target error (which entity to fix).
- vs `spec_misinterpretation`: control_flow_trap involves misunderstanding runtime execution flow. spec_misinterpretation involves misunderstanding intended behavior.

**Structural Difficulty Ladder:**
- A: single branch, wrong case in a simple if/else
- B: dispatch table or multi-branch switch with distractors
- C: cross-file dispatch with callback indirection

**Observed Failure Pattern to Validate:**
Classify each failed model output into:
- **Handler fix:** model edits the handler/endpoint of the wrongly-taken path
- **Guard fix:** model edits the routing guard/condition (correct direction)
- **Unrelated failure:** neither

Validation threshold: ≥50% of failures must be "handler fix."

**Intervention Probe Hypotheses:**
- Critique may help if it asks about control flow explicitly
- Likely neutral otherwise — control flow tracing is a reasoning task, not a commitment task

**Calibration Criteria:**
- Baseline pass rate between 10% and 90%
- At least one intervention delta ≥10pp, OR labeled intervention-insensitive

**Minimum Trap Activation Pattern:**
≥20% of failed attempts must edit the wrong handler/path rather than the routing guard.

---

### 4.3 spec_misinterpretation

**Failure Mechanism:** The model is misled by semantic signals (variable names, comments, docstrings, task description) into adopting the wrong intended behavior.

This family serves as a **non-LEG contrast class**. In spec_misinterpretation cases, reasoning and code are wrong together — the model misreads what the code is supposed to do, and both its explanation and its fix reflect that misreading. This means:
- LEG rate should be low (reasoning and code fail together, not separately)
- Critique may be harmful if it reinforces the misleading spec
- Commitment-style prompting may hurt if it locks in the wrong interpretation

This family is important specifically because it provides cases where interventions designed for LEG (critique, reasoning-only) should NOT help, preventing the benchmark from overfitting to LEG-only cases.

**Inclusion Rule:** The primary failure is that the model misreads what the code is *supposed to do*, not how it does it. Semantic cues conflict with actual expected behavior.

**Exclusion Rule:** If the model correctly understands intended behavior but picks the wrong causal mechanism or fix location, it belongs in another family.

**Adjacent-Family Boundaries:**
- vs `test_impl_mismatch`: spec_misinterpretation is about misleading semantic context. test_impl_mismatch is about competing authority sources (test vs code).

**Structural Difficulty Ladder:**
- A: misleading variable name in single function
- B: misleading comments or docstrings that contradict actual behavior, with supporting context
- C: task description that implies wrong goal, with misleading expert-like hints

**Observed Failure Pattern to Validate:**
Classify each failed model output into:
- **Spec-aligned failure:** model's fix aligns with the misleading spec (wrong intended behavior)
- **True-spec aligned:** model targets the correct intended behavior but implementation is wrong
- **Unrelated failure:** neither

Validation threshold: ≥50% of failures must be "spec-aligned failure."

**Intervention Probe Hypotheses:**
- Hypothesis: critique HURTS (reinforces misleading spec)
- Hypothesis: reasoning-only is neutral-to-harmful (re-prompting re-exposes misleading cues)
- This is a critical family for testing the limits of interventions

**Calibration Criteria:**
- Baseline pass rate between 10% and 90%
- LEG rate should be ≤30% (reasoning and code fail together). If LEG rate >30%, reclassify the case.
- Intervention sensitivity is expected to be low or negative. Label as intervention-insensitive if no delta ≥10pp.

**Minimum Trap Activation Pattern:**
≥20% of failed attempts must produce fixes aligned with the misleading spec.

---

### 4.4 test_impl_mismatch

**Failure Mechanism:** The case presents a conflict between what the test expects and what the code implementation does. The model must determine which artifact is authoritative. The model either defers to the wrong authority or tries to reconcile them incorrectly.

**Inclusion Rule:** There is an explicit or implicit conflict between the test contract and the implementation behavior. The root cause is in one artifact but the model fixes the other.

**Exclusion Rule:** If both test and implementation agree on behavior but the implementation has a bug, this is not test_impl_mismatch.

**Adjacent-Family Boundaries:**
- vs `spec_misinterpretation`: test_impl_mismatch involves competing authority sources (test says X, code says Y). spec_misinterpretation involves semantic cues misleading about intended behavior. Operational test: if removing the test would eliminate the ambiguity, it's test_impl_mismatch.

**Structural Difficulty Ladder:**
- A: test and code disagree on a single return value; one is clearly correct from context
- B: test and code disagree on invariant; both are locally defensible
- C: test and code disagree on behavior across multiple functions; resolution requires understanding design intent

**Observed Failure Pattern to Validate:**
Classify each failed model output into:
- **Wrong authority:** model defers to the incorrect artifact (e.g., changes test to match buggy code, or changes code to match wrong test)
- **Correct authority, wrong fix:** model identifies the right artifact to fix but implementation is wrong
- **Unrelated failure:** neither

Validation threshold: ≥50% of failures must be "wrong authority."

**Intervention Probe Hypotheses:**
- Models likely default to trusting tests (RLHF prior: "make the test pass")
- LEG susceptibility: low (reasoning and code usually agree)
- Critique may hurt if commitment locks in the wrong authority

**Calibration Criteria:**
- Baseline pass rate between 10% and 90%
- At least one intervention delta ≥10pp, OR labeled intervention-insensitive

**Minimum Trap Activation Pattern:**
≥20% of failed attempts must defer to the wrong authority artifact.

---

### 4.5 misinferred_dependency

**Failure Mechanism:** The symptom has multiple plausible causal explanations, and only deeper inspection or counterfactual reasoning disambiguates them. The model selects the wrong cause — not because it's drawn to a visible symptom-proximal target (that's false_fix_attractor) but because it incorrectly evaluates competing causal hypotheses.

**Inclusion Rule:** The case presents at least two comparably plausible candidate causes for the observed symptom. Each candidate cause implies a distinct fix. Only one cause is correct. Disambiguation requires evidence beyond local function scope (cross-function data flow, invariant analysis, or counterfactual reasoning).

**Mandatory assignment rule:** If a case admits multiple comparably plausible causal hypotheses that require cross-function or cross-module disambiguation, it MUST be classified as misinferred_dependency, even if one hypothesis involves a symptom-proximal target. The operational test: if a reviewer can construct a second comparably plausible causal narrative that implies a different fix, the case is misinferred_dependency.

**Exclusion Rule:** If only one plausible cause exists and the model simply misses it or is drawn to a nearby target, it belongs in false_fix_attractor.

**Adjacent-Family Boundaries:**
- vs `false_fix_attractor`: false_fix_attractor has one obvious wrong target near the symptom; alternative explanations are not comparably plausible. misinferred_dependency has two or more non-obvious candidates requiring disambiguation.
- vs `intervention_boundary`: misinferred_dependency is about *which cause* is correct. intervention_boundary is about *where to intervene* given a correctly identified cause.
- vs `abstraction_leak`: abstraction_leak is about fixing at the wrong abstraction level within the correct causal chain. misinferred_dependency is about following the wrong causal chain entirely.

**Required Case Structure:**
Every case must define:
1. Symptom with at least 2 plausible candidate causes
2. Why each wrong cause is believable from local evidence
3. What evidence disambiguates the candidates
4. What wrong fix each cause induces
5. What invariant separates the true cause from the wrong cause

**Structural Difficulty Ladder:**
- A: two candidate causes, one in same file, disambiguation from function signatures
- B: two candidate causes across files, disambiguation requires tracing data flow
- C: three+ candidate causes, disambiguation requires counterfactual reasoning across module boundary

**Observed Failure Pattern to Validate:**
Classify each failed model output into:
- **Wrong cause chosen:** model's fix targets the wrong candidate cause (identify which candidate)
- **Right cause, wrong fix:** model identifies correct cause but implementation is wrong
- **Unrelated failure:** neither

Validation threshold: ≥50% of failures must be "wrong cause chosen."

**Intervention Probe Hypotheses:**
- High LEG susceptibility: models may reason about the right cause but implement the fix for the more accessible wrong cause
- Critique may help if it challenges the causal hypothesis directly
- Reasoning-only may help if re-prompting triggers deeper disambiguation

**Calibration Criteria:**
- Baseline pass rate between 10% and 90%
- At least one intervention delta ≥10pp, OR labeled intervention-insensitive

**Minimum Trap Activation Pattern:**
≥20% of failed attempts must choose the wrong candidate cause (not just produce unrelated failures).

---

### 4.6 abstraction_leak

**Failure Mechanism:** The model correctly identifies the root cause but applies the fix at the wrong abstraction level — patching a downstream consumer instead of fixing the upstream producer, or compensating at the caller instead of correcting the callee.

**Inclusion Rule:** The model's reasoning identifies the correct root cause. The model's code applies the fix at a different abstraction layer (caller vs callee, producer vs consumer, interface vs implementation) than the structurally correct location.

**Exclusion Rule:** If the model identifies the wrong root cause entirely, it belongs in misinferred_dependency or false_fix_attractor.

**Adjacent-Family Boundaries:**
- vs `intervention_boundary`: Both involve correct reasoning with wrong fix location. abstraction_leak is about wrong *abstraction layer* (upstream/downstream). intervention_boundary is about wrong *point within the same layer*.
- vs `false_fix_attractor`: false_fix_attractor involves wrong causal target. abstraction_leak involves correct causal target but wrong layer.

**Structural Difficulty Ladder:**
- A: caller/callee in same file, clear producer-consumer relationship
- B: producer/consumer across files, with wrapper or adapter pattern
- C: three-layer stack (interface → adapter → implementation), fix must be at correct layer

**Observed Failure Pattern to Validate:**
Classify each failed model output into:
- **Wrong-layer fix:** model patches downstream consumer/defaulting instead of upstream producer (or vice versa)
- **Right-layer, wrong implementation:** model fixes at the correct layer but implementation is wrong
- **Unrelated failure:** neither

Validation threshold: ≥50% of failures must be "wrong-layer fix."

**Intervention Probe Hypotheses:**
- High LEG susceptibility: correct reasoning, wrong code placement
- Commitment mechanisms that force layer-specific intervention planning may help
- Critique may help if it asks "where should the fix be applied?"

**Calibration Criteria:**
- Baseline pass rate between 10% and 90%
- At least one intervention delta ≥10pp, OR labeled intervention-insensitive

**Minimum Trap Activation Pattern:**
≥20% of failed attempts must apply the fix at the wrong abstraction layer.

---

### 4.7 intervention_boundary

**Failure Mechanism:** The model identifies the correct root cause and the correct abstraction layer but applies the fix at the wrong point in the causal chain within that layer. The fix addresses one effect of the root cause but misses co-required effects, or repairs the right state but breaks an adjacent invariant.

**Inclusion Rule:** The model's reasoning correctly identifies root cause AND the correct abstraction layer. The code change is at the right target but is incomplete, over-broad, or misscoped within that target.

**Exclusion Rule:** If the model targets the wrong function or wrong layer entirely, it belongs in false_fix_attractor or abstraction_leak.

**Adjacent-Family Boundaries:**
- vs `abstraction_leak`: abstraction_leak fixes at the wrong layer. intervention_boundary fixes at the right layer but the wrong point or scope.
- vs `false_fix_attractor`: false_fix_attractor targets the wrong entity. intervention_boundary targets the right entity but applies the fix incompletely.

**Structural Difficulty Ladder:**
- A: single missing co-effect in same function
- B: missing co-effects across functions, or fix that breaks adjacent guard
- C: coordinated changes at multiple points within the correct layer, with ordering constraints

**Observed Failure Pattern to Validate:**
Classify each failed model output into:
- **Incomplete/misscoped fix:** model targets correct entity but fix is incomplete, over-broad, or breaks adjacent invariant
- **Wrong target entirely:** model targets wrong entity (reclassify to another family)
- **Unrelated failure:** neither

Validation threshold: ≥50% of failures must be "incomplete/misscoped fix."

**Intervention Probe Hypotheses:**
- High LEG susceptibility: this is the most "almost right" family
- Commitment mechanisms that force enumeration of all required state changes may help
- Critique is hypothesized neutral (reasoning is already correct; failure is in translation)
- Empirical finding from current benchmark: reasoning-only is statistically indistinguishable from critique on average

**Calibration Criteria:**
- Baseline pass rate between 10% and 90%
- At least one intervention delta ≥10pp, OR labeled intervention-insensitive

**Minimum Trap Activation Pattern:**
≥20% of failed attempts must produce incomplete/misscoped fixes at the correct target.

---

## 5. Gold-Standard Family Specification: false_fix_attractor

This section serves as the concrete template for all family specs. Implementation teams should imitate this level of detail.

### 5.A. Sharpened Definition

false_fix_attractor measures whether models gravitate to a symptom-proximal wrong target when a more distal root cause exists. The attractor is dominant: it is the single most obvious wrong fix, and no other wrong fix is comparably plausible. If a second wrong fix IS comparably plausible, the case is misinferred_dependency.

### 5.B. Formal Discriminator

A case belongs to false_fix_attractor if and only if ALL of the following hold:

1. There exists exactly one dominant wrong target W (function, variable, or code location)
2. W is closer to the symptom than the true root cause R in the dependency graph (measured by call-chain hops or data-flow distance)
3. A fix applied to W partially addresses the symptom (at least one failing test starts passing)
4. A fix applied to W fails at least one generalization or causal-location invariant
5. No second wrong target W' exists such that W' is comparably plausible (a reviewer presented with the case independently identifies W as THE obvious wrong fix)

If condition 5 fails, the case belongs in misinferred_dependency.

### 5.C. What Counts / What Does Not Count

**Counts as false_fix_attractor:**
- Function `process()` crashes because `validate()` silently returns None on error. Model patches `process()` to handle None instead of fixing `validate()`. `validate()` is the root cause; `process()` is the attractor because it's where the crash manifests.
- Test fails because `format_output()` produces wrong string. Root cause is `parse_input()` returns wrong data. Model patches `format_output()` to compensate. `format_output()` is the attractor; `parse_input()` is the root cause.

**Does NOT count as false_fix_attractor:**
- Two functions both contain bugs that could independently cause the symptom. This is misinferred_dependency.
- Model targets the correct root cause function but writes the fix wrong (off-by-one). This is intervention_boundary.
- Model patches the right function at the wrong abstraction layer (caller instead of callee). This is abstraction_leak.

### 5.D. Expected Model Behavior

If the family is real and the case is well-designed:
- ≥50% of failed model outputs should target the attractor W
- The attractor fix should partially pass (some tests pass) but fail generalization invariants
- Stronger models should show lower attractor rates (deeper causal analysis)
- Weaker models should show higher attractor rates (default to symptom-proximal fixes)

### 5.E. Stage 2 Output Classification

For each failed model output, the classifier asks:
1. Did the model's code change target function/location W (the attractor)? → "attractor chosen"
2. Did the model's code change target function/location R (the root cause) but implement incorrectly? → "true-fix direction"
3. Neither? → "unrelated failure"

This classification can be automated by checking which functions were modified in the model's output and comparing against the attractor function list and root cause function list.

### 5.F. Diagnostic Intervention Pattern

Based on current benchmark data (33,569 events, 8 models, 58 cases):
- Critique (strict): +8.2pp over baseline (p<0.0001) — significant
- Reasoning-only: +7.6pp over baseline (p<0.0001) — significant
- Critique vs reasoning-only: +0.4pp (p=0.54) — NOT significant

Hypothesis for false_fix_attractor specifically: critique may have a larger edge in this family than globally, because the code-mismatch feedback can redirect attention from attractor to root cause. This is testable.

What would be diagnostic:
- If critique > reasoning-only on false_fix_attractor cases but not on other families, the code-mismatch feedback adds family-specific value.
- If critique ≈ reasoning-only even on false_fix_attractor, the attractor is defeated by re-prompting alone, not by specific feedback.

### 5.G. Falsification Conditions

The family design is falsified if:
- <30% of failures target the attractor (the trap is not attractive)
- Attractor rates are identical across model capability tiers (no difficulty gradient)
- All cases classified as false_fix_attractor show identical intervention profiles to misinferred_dependency cases (the families are not empirically distinguishable)

---

## 6. Gold-Standard Example Case: `cache_bypass_attractor`

This is a fully worked example case under `false_fix_attractor`. Implementation teams should use this as a calibration target for authoring quality.

### 6.1 Case Title

`cache_bypass_attractor`

### 6.2 Scenario

A web application has a `CacheManager` that wraps a `DataStore`. The `CacheManager.get()` method should check the cache first and only call `DataStore.fetch()` on a miss. The bug: `DataStore.fetch()` has a side effect — it increments an access counter. When `CacheManager.get()` is called repeatedly with the same key, the access counter increments every time instead of only on the first call, because the `CacheManager` is not storing results back to the cache after a fetch.

The symptom manifests in `ReportGenerator.build_report()`, which calls `CacheManager.get()` and then checks the access counter for rate-limiting. The report is rejected because the counter is too high.

### 6.3 File Layout

```
cache_manager.py    — CacheManager class with get(), invalidate()
data_store.py       — DataStore class with fetch(), access_count
report_generator.py — ReportGenerator that uses CacheManager
test_report.py      — Tests that exercise the full flow
```

### 6.4 Buggy Behavior

`CacheManager.get()` calls `DataStore.fetch()` on every cache miss but never writes the result back to the internal cache dict. So every call is a miss, fetch runs every time, and the access counter increments on every call.

### 6.5 True Root Cause

`CacheManager.get()` is missing `self._cache[key] = result` after the `DataStore.fetch()` call. The fix is in `cache_manager.py`.

### 6.6 Dominant Attractor Fix

Modify `ReportGenerator.build_report()` to reset or ignore the access counter before checking the rate limit. This is the attractor because:
- The symptom (report rejected) manifests in `report_generator.py`
- The access counter check is the immediate cause of the rejection
- The fix is simpler (one line: `store.reset_counter()` or skip the check)
- A developer seeing "counter too high → report rejected" would naturally look at the counter check first

This fix partially works: the report is no longer rejected. But it breaks the invariant that the access counter should accurately reflect actual data store hits.

### 6.7 Additional Trap Fixes

**Trap fix 2:** Modify `DataStore.fetch()` to not increment the counter. Plausible because the counter seems to be causing the problem. Fails invariant: other callers of DataStore depend on accurate access counting for monitoring.

**Trap fix 3:** Add a `max_retries` parameter to `ReportGenerator.build_report()` and cap counter-based rejection. Plausible defensive coding. Fails generalization: with a different cache key set, the counter will still be wrong and other rate-limiting consumers will malfunction.

### 6.8 Reference Fix

In `cache_manager.py`, `CacheManager.get()`:
```python
def get(self, key):
    if key in self._cache:
        return self._cache[key]
    result = self._store.fetch(key)
    self._cache[key] = result     # <-- THIS LINE IS THE FIX
    return result
```

### 6.9 Trap-Catching Invariant

```python
def test_cache_hit_does_not_fetch():
    """After first get(), subsequent get() with same key must not call fetch()."""
    store = DataStore()
    cache = CacheManager(store)
    cache.get("key_a")
    count_after_first = store.access_count
    cache.get("key_a")  # should be cached
    assert store.access_count == count_after_first, "Cache miss on repeated key"
```

This invariant catches:
- Trap fix 1 (attractor): counter is reset/ignored but fetch still runs → count increments
- Trap fix 2: counter doesn't increment but fetch still runs → test structure can be adapted to check fetch call count
- Trap fix 3: cap doesn't prevent extra fetches

### 6.10 Generalization Invariant

```python
def test_multiple_keys_cache_correctly():
    """Cache must work across multiple distinct keys."""
    store = DataStore()
    cache = CacheManager(store)
    for key in ["a", "b", "c"]:
        cache.get(key)
    initial_count = store.access_count  # should be 3
    for key in ["a", "b", "c"]:
        cache.get(key)  # all cached
    assert store.access_count == initial_count, "Cache not working across keys"
```

### 6.11 Causal-Location Invariant

```python
def test_fix_is_in_cache_manager():
    """DataStore and ReportGenerator must be unmodified from original."""
    # Verify DataStore.fetch still increments counter (it's supposed to)
    store = DataStore()
    store.fetch("x")
    assert store.access_count == 1
    store.fetch("x")
    assert store.access_count == 2  # fetch SHOULD count

    # Verify ReportGenerator still checks counter (it's supposed to)
    # ... (rate limit check is by design, not a bug)
```

### 6.12 Validation Matrix

| Variant | Trap-catching | Generalization | Causal-location | Overall |
|---|---|---|---|---|
| No-op (original bug) | FAIL | FAIL | PASS | FAIL |
| Reference fix (cache write-back) | PASS | PASS | PASS | PASS |
| Trap 1: reset counter in report_generator | FAIL | FAIL | FAIL | FAIL |
| Trap 2: remove counter increment in data_store | FAIL | FAIL | FAIL | FAIL |
| Trap 3: cap rejection in report_generator | FAIL | FAIL | FAIL | FAIL |

### 6.13 Why false_fix_attractor, Not misinferred_dependency

There is exactly one dominant wrong target: `ReportGenerator.build_report()` (or `DataStore.fetch()`'s counter). The root cause (`CacheManager.get()` not caching) is not comparably plausible from a surface reading — a developer must trace the data flow from ReportGenerator → CacheManager → DataStore to discover that the cache write-back is missing. The attractor is the counter/report check because that's where the symptom manifests. No second wrong target is comparably plausible.

### 6.14 Expected Stage 2 Observations

If the case functions as intended:
- ≥50% of failures should target report_generator.py or data_store.py (attractor zone)
- <30% of failures should target cache_manager.py with a wrong implementation (true-fix direction)
- Stronger models should show higher rates of targeting cache_manager.py
- Critique should help if feedback says "the cache is not being populated" (redirects from symptom to cause)
- Reasoning-only should partially help (re-prompting may trigger deeper trace)
- If critique >> reasoning-only on this case, it supports the hypothesis that code-mismatch feedback adds attractor-specific value

### 6.15 Redesign Triggers

This case must be redesigned if:
- <20% of failures target the attractor (trap too weak)
- >90% of models pass at baseline (case too easy — ceiling)
- <10% of models pass at baseline (case too hard — floor)
- The attractor fix passes all invariants (invariants need redesign)
- Critique and reasoning-only both show zero delta (case is intervention-insensitive AND was predicted to be sensitive — hypothesis failed)

---

## 7. Case Validation Protocol

### 7.1 Design Validation (Stage 1 gate)

For every case, the author must produce:

1. **No-op baseline:** Original broken code. Document which assertions fail and which pass.
2. **Reference fix:** True correct fix. Must pass ALL assertions. Must be minimum change.
3. **Trap fix set:** Minimum 2 (A-level) or 3 (B/C-level) concrete code changes. Each must be structurally plausible. Each must fail at least one invariant.
4. **Validation matrix:** Concrete PASS/FAIL per invariant per variant. Verified by running code.
5. **Uniqueness justification:** Why the reference fix is uniquely correct under defined invariants.
6. **Generalization probe:** At least two distinct input configurations exercising the fix.
7. **Causal-location check:** Where applicable, confirm wrong-layer fixes fail.

**Blocking rule:** A case missing any of artifacts 1-6 is not eligible for Stage 2.

### 7.2 Observed Behavior Validation (Stage 2 gate)

Stage 2 runs after Stage 1 passes. It requires actual model outputs.

**7.2.1 Calibration Run**

Run low-N trials on the case:
- Models: at least 2 models from different capability tiers (e.g., one strong, one weak)
- Trials: at least 10 per model per condition
- Conditions (mandatory):
  - baseline
  - critique (strict)
  - reasoning-only
- Conditions (optional):
  - bare retry (if wired)

**7.2.2 Observed Failure Pattern Check**

For each failed model output, classify into the family-specific failure categories (defined in Section 4 under "Observed Failure Pattern to Validate").

**Hard rule:** At least 50% of failures must match the intended family failure pattern. If <50%, the case must be reclassified to a different family, redesigned to strengthen the trap, or dropped.

**7.2.3 Trap Activation Check**

**Hard rule:** At least one defined trap fix must be chosen by ≥20% of failed model attempts across the calibration model set. "Chosen" means the model's output modifies the same target function/location as the trap fix. If no trap reaches 20%, the trap is too weak — redesign or drop.

**7.2.4 Intervention Probe**

Compute from calibration data:
- `pass_rate_baseline`
- `pass_rate_critique`
- `pass_rate_reasoning_only`
- `delta_critique = pass_rate_critique - pass_rate_baseline`
- `delta_reasoning_only = pass_rate_reasoning_only - pass_rate_baseline`

**Hard rule:** If `max(delta_critique, delta_reasoning_only) >= 10 percentage points`, the case is classified as **intervention-sensitive**. Otherwise, classify as **intervention-insensitive**. This label is preserved in benchmark metadata.

A case is NOT invalid for being intervention-insensitive. But it must be explicitly labeled, and the benchmark must contain at least one intervention-insensitive case (see Section 10).

**7.2.5 Floor/Ceiling Check**

- If baseline pass rate ≥90% across all calibration models: case is too easy. Redesign to increase difficulty or drop.
- If baseline pass rate = 0% across all calibration models: case is too hard. Redesign to reduce difficulty or drop.
- If baseline pass rate is between 1% and 10% across all models: flag as near-floor. Acceptable but note in metadata.

**7.2.6 Stage 2 Gate**

A case advances to Stage 3 only if ALL of the following pass:
- Observed failure pattern check: ≥50% match
- Trap activation check: ≥20% activation
- Floor/ceiling check: not at 0% or ≥90% baseline across all models
- Intervention probe: completed (sensitivity labeled)

---

## 8. Stress-Test Case Policy

### 8.1 Definition

A stress-test case is one that:
- Combines multiple failure families
- Has elevated distractor density (5+ distractor functions)
- Has unusually high ambiguity or layered traps

### 8.2 Rules

- Must still pass the full validation protocol (Stages 1 and 2)
- Results must not be pooled with standard cases for family-level statistics
- Tagged `stress_test: true` and reported separately

### 8.3 When to Use

A case qualifies as stress-test when it genuinely spans two or more families and cannot be cleanly classified into one.

---

## 9. Stage-Gated Implementation Plan

### Stage 0 — Design Review

For each proposed case:
- Family assignment with written justification (Step 1)
- Causal graph sketch (Step 2)
- Trap design with plausibility justification (Step 3)
- Invariant design (Step 4)
- Orthogonality check: case does not duplicate an existing case's mechanism

**Gate:** Design review approved by at least one team member who did not author the case.

### Stage 1 — Local Validation

- No-op fails expected assertions
- Reference fix passes ALL assertions
- Every trap fix fails at least one invariant
- Validation matrix complete and verified by running code
- Generalization probe passes (2+ input configurations)
- Causal-location invariant verified (where applicable)

**Gate:** All artifacts from Section 7.1 present and verified. No case advances to Stage 2 without a complete validation matrix.

### Stage 2 — Calibration

- Low-N multi-model run (≥2 models, ≥10 trials, 3 conditions)
- Observed failure pattern validation: ≥50% of failures match intended family pattern
- Trap activation check: ≥20% of failures choose a defined trap
- Intervention probe completed: baseline, critique, reasoning-only deltas computed
- Floor/ceiling check: not at 0% or ≥90% baseline

**Gate:** All checks from Section 7.2 pass. Cases that fail are redesigned or dropped. Do NOT carry forward cases that fail Stage 2 on the assumption they "might work later."

### Stage 3 — Promotion and Family Ablation

- Only cases that pass Stage 2 are promoted
- Family-level ablation: for each family with ≥2 promoted cases, run full ablation (N≥30 trials, all models) to compute family-level statistics
- Compute family-level intervention deltas and regime distributions
- Identify families that produce diagnostic signal (intervention-sensitive cases with heterogeneous model behavior)

**Gate:** At least 3 families have ≥1 promoted case.

### Stage 4 — Benchmark Completion Review

- Evaluate completion criteria (Section 10)
- Apply portfolio balancing rules (secondary, post-validation)
- Fill gaps in diagnostic families if needed
- Finalize benchmark extension

---

## 10. Benchmark Completion Criteria

The benchmark extension is complete when ALL of the following hold:

### 10.1 Family Coverage

- At least 3 families have ≥2 validated cases that passed Stage 2
- At least 5 total families have ≥1 validated case

### 10.2 Intervention Coverage

- At least 1 family where `mean(delta_critique) > mean(delta_reasoning_only) + 5pp` across its cases (critique adds value beyond re-prompting)
- At least 1 family where `mean(delta_reasoning_only) >= mean(delta_critique)` (re-prompting suffices; critique overhead unjustified)
- At least 1 validated case classified as intervention-insensitive (baseline pass rate in 10-90% range but no intervention delta ≥10pp)

### 10.3 LEG Diversity

- At least 1 family with mean baseline LEG rate >30% across its cases (high-LEG family)
- At least 1 family with mean baseline LEG rate ≤15% across its cases (low-LEG / non-LEG contrast family, e.g., spec_misinterpretation)

### 10.4 Model Heterogeneity

- Regime distributions must differ across at least 2 model capability tiers (e.g., weak models show more attractor failures, strong models show more intervention-boundary failures)
- At least 1 case where model-tier ordering of pass rates reverses under an intervention condition (an intervention helps weak models more than strong models, or vice versa)

### 10.5 Minimum Scale

- At least 12 total validated cases (excluding stress-tests)
- At least 2 stress-test cases

### 10.6 Failure Conditions

If after reasonable effort (Stage 3 completed for ≥4 families), ANY of the following hold:
- Fewer than 3 families produce intervention-sensitive cases → the extension is measuring bug difficulty, not reasoning-to-code failure. Redesign families.
- All families show identical intervention profiles → the families are not empirically distinguishable. Merge or redesign.
- LEG rate ≤5% across all extension cases → the extension is not measuring LEG. Either accept that or redesign.

These failure conditions do not kill the project. They trigger mandatory redesign of the failing component.

---

## 11. Two-Pass Review Protocol

### Pass 1: Construction (Steps 1-7)
- Author builds mechanism, trap, invariants, reference fix, validation matrix
- Author assigns difficulty using structural properties only
- No reference to expected model behavior, LEG predictions, or intervention effects

### Pass 2: Annotation (Step 8)
- After case is finalized and passes Stage 1
- Separate reviewer (or same author in a distinct pass) annotates:
  - Expected regime hypothesis
  - LEG susceptibility
  - Intervention hypothesis
- Annotations are hypotheses, not design constraints
- Annotations must not retroactively modify case design

---

## 12. Existing Case Inventory

Cases from v3 carried forward. Each must pass the full validation protocol (Stages 1-2) before benchmark inclusion.

### 12.1 LEG-Targeted (6 cases)

| Case | Family | Level |
|---|---|---|
| leg_wrong_target | false_fix_attractor | L2 |
| leg_incomplete_propagation | abstraction_leak | L2 |
| leg_invariant_break | intervention_boundary | L2 |
| leg_scope_error | control_flow_trap | L2 |
| leg_false_mechanism | misinferred_dependency | L2 |
| leg_overgeneralization | intervention_boundary | L2 |

### 12.2 Concurrency (4 cases)

| Case | Level |
|---|---|
| lost_update | L2 |
| check_then_act | L2 |
| ordering_dependency | L2 |
| false_fix_deadlock | L2 |

### 12.3 Pressure/Sycophancy (2 cases)

| Case | Family | Level |
|---|---|---|
| misleading_hint_aliasing | spec_misinterpretation | L2 |
| misleading_hint_ordering | spec_misinterpretation | L2 |

### 12.4 Write-from-Scratch (3 cases)

| Case | Level |
|---|---|
| idempotent_processor | L2 |
| transactional_update | L2 |
| ordered_message_handler | L2 |

### 12.5 False Competence (2 cases)

| Case | Level |
|---|---|
| false_competence_aliasing | L2 |
| false_competence_ordering | L2 |

### 12.6 L3 Concurrency (1 case)

| Case | Level |
|---|---|
| counterfactual_interleaving | L3 |

May be reclassified as stress-test if it spans multiple families.

---

## 13. Coverage Gap: test_impl_mismatch

test_impl_mismatch has no cases from v3. Cases should be authored during Stage 3 if pilot calibration confirms that reasoning-failure families produce diagnostic signal. A missing family is preferable to a family populated with weak cases.

---

## 14. Evaluation Metrics

### 14.1 Primary Metrics

```
pass_rate              = (# passed) / total
LEG_rate               = (# mechanism_correct AND NOT passed) / total_failed
false_competence_rate  = (# passed AND NOT mechanism_correct) / total
```

### 14.2 Per-Family Metrics (computed in Stage 3)

```
family_pass_rate       = mean pass rate across family cases
family_LEG_rate        = mean LEG rate across family cases
family_delta_critique  = mean(pass_rate_critique - pass_rate_baseline) across family cases
family_delta_ro        = mean(pass_rate_reasoning_only - pass_rate_baseline) across family cases
family_trap_activation = mean(% of failures choosing defined trap) across family cases
```

### 14.3 Failure Classification

| Label | Definition |
|---|---|
| LEG_coupling | Correct reasoning, code edits wrong target/scope |
| LEG_execution | Correct reasoning, correct target, implementation error |
| FALSE_COMPETENCE | Code passes but reasoning incorrect |
| FAMILY_MATCH | Failed output matches intended family failure pattern |
| FAMILY_MISMATCH | Failed output does not match intended family failure pattern |
