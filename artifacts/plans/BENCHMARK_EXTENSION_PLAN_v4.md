# Benchmark Extension Plan v4 — Case-Authoring Protocol

**Date:** 2026-04-01
**Status:** PLAN ONLY
**Supersedes:** BENCHMARK_EXTENSION_PLAN_v3.md

---

## Revision History

| Version | Changes |
|---|---|
| v1 | 13 cases: LEG (4), concurrency (4), pressure (2), write-from-scratch (3) |
| v2 | +3 cases: false competence (2), L3 concurrency (1). Trace-output hooks. Replay tests. Self-contradiction protocol. |
| v3 | +2 LEG cases (17-18). Causal relation hooks on all LEG cases. false_competence_rate metric. |
| **v4** | Structural overhaul. Removed numeric model predictions. Added family discriminator rules. Added case authoring and validation protocols. Introduced two-pass construction/annotation separation. Stage-gated implementation. Stress-test case policy. Demoted portfolio balancing to secondary. Strengthened misinferred_dependency as first-class family. |

---

## 1. Executive Summary

This plan defines the protocol for extending the CS372 benchmark with new cases that measure causal reasoning failures in LLM code generation.

The benchmark extension targets a specific research question: under what conditions does correct reasoning fail to produce correct code (LEG), and under what conditions does incorrect reasoning still produce correct code (lucky fix)?

This document is a **case-authoring protocol**, not a strategy memo. It defines:
- How to construct a valid case
- How to classify a case into a failure family
- How to validate a case before benchmark inclusion
- How to separate case construction from hypothesis annotation
- How to gate implementation to prevent benchmark bloat

The primary unit of analysis is the **case**. All design decisions prioritize case quality and diagnostic sharpness over family balance or portfolio coverage.

---

## 2. Core Design Principles

**P1. Case quality over coverage balance.**
No case may be kept merely to satisfy a distribution quota. Case validity and diagnostic sharpness outrank family balance.

**P2. Cases measure reasoning failure, not bug difficulty.**
The existing benchmark classifies by bug type (ALIASING, PARTIAL_STATE_UPDATE, etc.). Extension cases classify by the **type of reasoning-to-code failure** — the mechanism by which correct or incorrect reasoning maps to correct or incorrect code.

**P3. Traps must be locally coherent.**
Every wrong fix in a case must be something a competent developer could plausibly write given partial understanding. Toy distractions are invalid traps.

**P4. Construction precedes annotation.**
Case authors build the mechanism, trap, and invariants first. Expected regime hypotheses (LEG susceptibility, critique sensitivity, etc.) are assigned only after the case is finalized. This separation prevents benchmark leakage.

**P5. Validation is mandatory.**
No case enters the benchmark without a completed validation matrix. Intuition is not evidence.

**P6. Invariants must discriminate.**
Every case must have at least one invariant that separates the true fix from every plausible trap fix. If no such invariant exists, the case is invalid.

---

## 3. Case Authoring Protocol

This section defines the mandatory workflow for producing a valid benchmark case. Every step must be completed in order. Skipping steps is non-compliant.

### Step 1: Mechanism Selection

- Choose one failure family from Section 4.
- Read the family discriminator (inclusion rule, exclusion rule, adjacent-family boundary).
- State in writing:
  - Which family this case belongs to
  - Why it satisfies the inclusion rule
  - Why it does not belong in the most similar adjacent family
- If the case spans two families, it is a stress-test case (Section 6), not a standard case.

### Step 2: Causal Graph Sketch

Define the following nodes and edges in writing:

- **Symptom node**: the observable failure (test failure, wrong output, inconsistent state)
- **True root cause**: the actual source of the failure
- **Plausible wrong cause(s)**: at least one alternative explanation that is locally coherent
- **Intervention points**: where in the code a fix could be applied
- **Trap path**: the reasoning path from symptom → wrong cause → wrong fix
- **Why the trap is plausible**: what local evidence supports the wrong cause

### Step 3: Trap Design

For each wrong fix:
- Define the concrete code change
- State why the fix is locally coherent (what evidence supports it)
- State why the fix fails globally (what invariant or test it violates)
- Verify the fix addresses the symptom at least partially (a trap that obviously does nothing is not a trap)

Minimum trap count:
- A-level cases: at least 2 trap fixes
- B-level and C-level cases: at least 3 trap fixes

### Step 4: Invariant Design

Define three classes of invariants:

1. **Trap-catching invariant**: at least one assertion that fails for every defined trap fix. This is the discriminator between correct and plausible-wrong fixes.
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

| Variant | Invariant 1 | Invariant 2 | Invariant 3 | ... | Overall |
|---|---|---|---|---|---|
| No-op (original bug) | FAIL | FAIL | ... | | FAIL |
| Reference fix | PASS | PASS | ... | | PASS |
| Trap fix 1 | PASS | FAIL | ... | | FAIL |
| Trap fix 2 | FAIL | PASS | ... | | FAIL |
| ... | | | | | |

Every row must be concrete code, not prose descriptions.

### Step 7: Difficulty Assignment

Assign A, B, or C using structural properties only:

| Property | A | B | C |
|---|---|---|---|
| Files involved | 1 | 1-2 | 2-3 |
| Causal hops to root cause | 1 | 2 | 3+ |
| Distractor functions | 0 | 1-2 | 3+ |
| Ambiguity of root cause | Low | Medium | High |
| Cross-boundary reasoning | No | Partial | Required |

Do not assign difficulty based on expected model performance. Difficulty is a structural property of the case, not an empirical observation.

### Step 8: Post Hoc Hypothesis Annotation (SEPARATE PASS)

Only after Steps 1-7 are complete and the case is validated, a separate annotation pass assigns:

- Expected regime hypothesis (which quadrant: correct/correct, correct/incorrect, incorrect/correct, incorrect/incorrect)
- Qualitative LEG susceptibility (low / medium / high)
- Qualitative critique sensitivity (likely helpful / likely neutral / likely harmful)
- Expected reconstruction burden (low / medium / high)

Hard rule: **The person constructing the case must not use intervention expectations as a guide for shaping the trap or invariants.** Hypothesis annotation is descriptive, not prescriptive.

---

## 4. Failure Family Definitions

These families classify the **type of reasoning-to-code failure**, not the type of bug.

Each family has:
- Failure mechanism specification
- Family discriminator (inclusion, exclusion, adjacent-family boundary)
- Structural difficulty ladder
- Qualitative hypothesis notes (no numeric predictions)

---

### 4.1 false_fix_attractor

**Failure Mechanism:** The model identifies the correct symptom but is drawn to a plausible wrong fix that addresses the visible manifestation rather than the underlying cause. The wrong fix may partially work or appear to work on the primary test case but fails under generalization.

**Family Discriminator:**

- **Inclusion rule:** The primary failure mechanism is that the model applies a locally coherent fix to the wrong target (wrong function, wrong variable, wrong layer) because that target is closer to the symptom than the true root cause.
- **Exclusion rule:** If the model's reasoning correctly identifies the root cause AND the root cause location but the implementation is merely buggy (off-by-one, wrong operator, incomplete), that belongs in intervention_boundary, not here. The distinguishing feature of false_fix_attractor is wrong *target*, not wrong *implementation*.
- **Adjacent-family boundary vs control_flow_trap:** false_fix_attractor patches the wrong target for a correctly observed symptom. control_flow_trap patches the wrong branch due to misunderstanding execution routing. If the error is "which function to fix," it's false_fix_attractor. If the error is "which execution path is taken," it's control_flow_trap.
- **Adjacent-family boundary vs misinferred_dependency:** false_fix_attractor is drawn to a visible target near the symptom. misinferred_dependency selects the wrong cause from multiple plausible candidates that require deeper disambiguation. If only one plausible wrong target exists (the obvious nearby one), it's false_fix_attractor. If multiple candidate causes are comparably plausible, it's misinferred_dependency.

**Structural Difficulty Ladder:**
- A: wrong target in same file, single-hop misdirection
- B: wrong target across functions, distractor function present
- C: wrong target across files, multiple attractors competing

**Qualitative Hypothesis Notes:**
- Weaker models likely default to symptom-proximal fixes
- Likely attractor-prone across all model tiers
- Critique interventions may help if they redirect attention to root cause
- LEG susceptibility: medium-high (reasoning may be correct but code targets the attractor)

**v3 Cases in this Family:** Case 1 (leg_wrong_target), Case 17 (leg_false_mechanism)

---

### 4.2 control_flow_trap

**Failure Mechanism:** The model misunderstands which execution path is taken at runtime and fixes the wrong branch, handler, or dispatch target. The root cause is a routing error (wrong branch entered, wrong case matched, wrong callback invoked), but the model treats it as a logic error within the correctly-routed path.

**Family Discriminator:**

- **Inclusion rule:** The root cause is misrouting — execution enters the wrong branch, case, or handler. The model fixes logic within a handler rather than fixing the routing itself.
- **Exclusion rule:** If the code takes the correct path but produces the wrong result due to a logic error within that path, this is not a control_flow_trap. The model must be misled about *which path* executes, not merely about *what the path does*.
- **Adjacent-family boundary vs false_fix_attractor:** control_flow_trap is about routing error (which path runs). false_fix_attractor is about target error (which entity to fix). If the model patches the downstream handler for a misrouted input rather than fixing the routing, it's control_flow_trap. If the model patches a non-routing target because it's near the symptom, it's false_fix_attractor.
- **Adjacent-family boundary vs spec_misinterpretation:** control_flow_trap involves misunderstanding runtime execution flow. spec_misinterpretation involves misunderstanding intended behavior. If the model knows what the code *should* do but traces the wrong path, it's control_flow_trap. If the model disagrees about what the code *should* do, it's spec_misinterpretation.

**Structural Difficulty Ladder:**
- A: single branch, wrong case in a simple if/else
- B: dispatch table or multi-branch switch with distractors
- C: cross-file dispatch with callback indirection

**Qualitative Hypothesis Notes:**
- Models with strong pattern-matching may shortcut past routing analysis
- LEG susceptibility: medium (reasoning may identify the right branch but code edits the wrong handler)
- Likely neutral to critique unless critique explicitly asks about control flow

**v3 Cases in this Family:** Case 4 (leg_scope_error — scope is a routing problem: module-level vs function-level)

---

### 4.3 spec_misinterpretation

**Failure Mechanism:** The model is misled by semantic signals (variable names, comments, docstrings, task description) into adopting the wrong intended behavior. The bug and the fix are clear once the spec is correctly understood, but contextual cues push the model toward a different spec.

**Family Discriminator:**

- **Inclusion rule:** The primary failure is that the model misreads what the code is *supposed to do*, not how it does it. Semantic cues conflict with actual expected behavior.
- **Exclusion rule:** If the model correctly understands intended behavior but picks the wrong causal mechanism or fix location, it belongs in another family. If the primary conflict is between tests and implementation about which is authoritative, it belongs in test_impl_mismatch.
- **Adjacent-family boundary vs test_impl_mismatch:** spec_misinterpretation is about the model being misled by semantic context into the wrong intended behavior. test_impl_mismatch is about the model confusing which artifact (test or code) defines correctness. If the task description or naming conventions mislead the model about behavior, it's spec_misinterpretation. If the model must decide whether to trust the test or the code, it's test_impl_mismatch.

**Structural Difficulty Ladder:**
- A: misleading variable name in single function
- B: misleading comments or docstrings that contradict actual behavior, with supporting context
- C: task description that implies wrong goal, with misleading expert-like hints

**Qualitative Hypothesis Notes:**
- Likely spec-confusion-heavy for models that rely on surface-level context
- Critique may be harmful if it reinforces the misleading spec
- LEG susceptibility: low-medium (if the model misreads the spec, both reasoning and code will be wrong together)

**v3 Cases in this Family:** Case 9 (misleading_hint_aliasing), Case 10 (misleading_hint_ordering)

---

### 4.4 test_impl_mismatch

**Failure Mechanism:** The case presents a conflict between what the test expects and what the code implementation does, where the model must determine which artifact is authoritative. The model either defers to the wrong authority or tries to reconcile them incorrectly.

**Family Discriminator:**

- **Inclusion rule:** There is an explicit or implicit conflict between the test contract and the implementation behavior, and the model must resolve which is correct. The root cause is in one artifact but the model fixes the other.
- **Exclusion rule:** If both test and implementation agree on behavior but the implementation has a bug, this is not a test_impl_mismatch — it's a normal bug fix. The conflict between artifacts must be real, not incidental.
- **Adjacent-family boundary vs spec_misinterpretation:** test_impl_mismatch involves competing authority sources (test says X, code says Y). spec_misinterpretation involves semantic cues misleading about intended behavior. If removing the test would eliminate the ambiguity, it's test_impl_mismatch. If the ambiguity comes from naming, comments, or task framing, it's spec_misinterpretation.

**Structural Difficulty Ladder:**
- A: test and code disagree on a single return value; one is clearly correct from context
- B: test and code disagree on invariant; both are locally defensible
- C: test and code disagree on behavior across multiple functions; resolution requires understanding design intent

**Qualitative Hypothesis Notes:**
- Models likely default to trusting tests (RLHF prior: "make the test pass")
- LEG susceptibility: low (model's reasoning and code will usually agree — the question is whether they agree correctly)
- Likely harmed by forced commitment if the commitment locks in the wrong authority

**v3 Cases in this Family:** None in v3 (new family — cases to be authored)

---

### 4.5 misinferred_dependency

**Failure Mechanism:** The symptom has multiple plausible causal explanations, and only deeper inspection or counterfactual reasoning disambiguates them. The model selects the wrong cause — not because it's drawn to a visible symptom-proximal target (that's false_fix_attractor) but because it incorrectly evaluates competing causal hypotheses.

This is a first-class diagnostic family, not an underspecified placeholder.

**Family Discriminator:**

- **Inclusion rule:** The case presents at least two comparably plausible candidate causes for the observed symptom. Each candidate cause implies a distinct fix. Only one cause is correct. Disambiguation requires evidence beyond local function scope (cross-function data flow, invariant analysis, or counterfactual reasoning).
- **Exclusion rule:** If only one plausible cause exists and the model simply misses it or is drawn to a nearby target, it belongs in false_fix_attractor. The defining feature of misinferred_dependency is *competing plausible hypotheses*, not *single missed cause*.
- **Adjacent-family boundary vs false_fix_attractor:** false_fix_attractor has one obvious wrong target near the symptom. misinferred_dependency has two or more non-obvious candidates requiring disambiguation. If the wrong fix is "the obvious nearby thing," it's false_fix_attractor. If the wrong fix is "the other plausible root cause that requires deeper analysis to rule out," it's misinferred_dependency.
- **Adjacent-family boundary vs intervention_boundary:** misinferred_dependency is about *which cause* is correct. intervention_boundary is about *where to intervene* given a correctly identified cause. If the model knows the cause but fixes the wrong layer, it's intervention_boundary. If the model picks the wrong cause entirely, it's misinferred_dependency.
- **Adjacent-family boundary vs abstraction_leak:** abstraction_leak is about fixing at the wrong abstraction level within the correct causal chain. misinferred_dependency is about following the wrong causal chain entirely.

**Required Case Structure (for all cases in this family):**

Every misinferred_dependency case must define:
1. Symptom with at least 2 plausible candidate causes
2. One proximal cause and one distal cause, OR two comparably plausible causes
3. Why each wrong cause is believable from local evidence
4. What evidence disambiguates the candidates (cross-file data flow, invariant, counterfactual)
5. What wrong fix each cause induces
6. What invariant separates the true cause from the plausible wrong cause

**Structural Difficulty Ladder:**
- A: two candidate causes, one in same file, disambiguation from function signatures
- B: two candidate causes across files, disambiguation requires tracing data flow
- C: three+ candidate causes, disambiguation requires counterfactual reasoning or invariant analysis across module boundary

**Qualitative Hypothesis Notes:**
- High expected LEG susceptibility: models may reason about the right cause but implement the fix for the more accessible wrong cause
- Mid-tier models may partially trace cross-file dependencies but settle on the proximal cause
- Likely helped by root-cause commitment (forcing explicit causal hypothesis before code)
- Critique may help if it challenges the causal hypothesis directly

**v3 Cases in this Family:** Case 17 (leg_false_mechanism — partially; overlaps with false_fix_attractor depending on how the model fails)

---

### 4.6 abstraction_leak

**Failure Mechanism:** The model correctly identifies the root cause but applies the fix at the wrong abstraction level — patching a downstream consumer instead of fixing the upstream producer, or compensating at the caller instead of correcting the callee.

**Family Discriminator:**

- **Inclusion rule:** The model's reasoning identifies the correct root cause. The model's code applies the fix at a different abstraction layer (caller vs callee, producer vs consumer, interface vs implementation) than the structurally correct location.
- **Exclusion rule:** If the model identifies the wrong root cause entirely, it belongs in misinferred_dependency or false_fix_attractor. Abstraction_leak requires correct causal identification coupled with wrong-layer intervention.
- **Adjacent-family boundary vs intervention_boundary:** Both involve correct reasoning with wrong fix location. Abstraction_leak is specifically about fixing at the wrong *abstraction layer* (upstream/downstream confusion). Intervention_boundary is about fixing at the wrong *point in the causal chain* within the same abstraction layer (e.g., fixing effect B instead of effect A when both are at the same level).
- **Adjacent-family boundary vs false_fix_attractor:** false_fix_attractor involves wrong causal target (wrong function/variable). abstraction_leak involves correct causal target but wrong layer of intervention. If the model patches the right root cause function but does so by compensating in the caller instead of fixing the callee, it's abstraction_leak.

**Structural Difficulty Ladder:**
- A: caller/callee in same file, clear producer-consumer relationship
- B: producer/consumer across files, with wrapper or adapter pattern
- C: three-layer stack (interface → adapter → implementation), fix must be at correct layer

**Qualitative Hypothesis Notes:**
- High LEG susceptibility: this family is specifically about correct reasoning with wrong code placement
- Stronger models may identify the right cause in reasoning but still intervene at the wrong layer due to code generation locality bias
- Likely helped by root-cause commitment if it forces layer-specific intervention planning

**v3 Cases in this Family:** Case 2 (leg_incomplete_propagation — correct cause identified, incomplete fix at correct layer), Case 3 (leg_invariant_break — correct cause, fix breaks adjacent invariant at same layer; partial overlap)

---

### 4.7 intervention_boundary

**Failure Mechanism:** The model identifies the correct root cause and the correct abstraction layer but applies the fix at the wrong point in the causal chain within that layer. The fix addresses one effect of the root cause but misses co-required effects, or the fix repairs the right state but breaks an adjacent invariant.

**Family Discriminator:**

- **Inclusion rule:** The model's reasoning correctly identifies root cause AND the correct abstraction layer. The code change is at the right target but is incomplete, over-broad, or misscoped within that target. Examples: fixing one state update but missing a co-required second update; adding the right logic but breaking an adjacent guard; correct fix function but wrong scope (module-level vs local).
- **Exclusion rule:** If the model targets the wrong function or wrong layer entirely, it belongs in false_fix_attractor or abstraction_leak. Intervention_boundary requires the model to be "almost right" — correct cause, correct layer, wrong boundary.
- **Adjacent-family boundary vs abstraction_leak:** abstraction_leak fixes at the wrong layer. intervention_boundary fixes at the right layer but the wrong point or scope within it.
- **Adjacent-family boundary vs false_fix_attractor:** false_fix_attractor targets the wrong entity. intervention_boundary targets the right entity but applies the fix incompletely or over-broadly.

**Structural Difficulty Ladder:**
- A: single missing co-effect in same function
- B: missing co-effects across functions, or fix that breaks adjacent guard
- C: fix requires coordinated changes at multiple points within the correct layer, with ordering constraints

**Qualitative Hypothesis Notes:**
- High LEG susceptibility: this is the most "almost right" family — reasoning is correct, code is close but wrong
- Likely helped by commitment mechanisms that force enumeration of all required state changes
- Likely neutral to critique (the reasoning is already correct; the failure is in translation)

**v3 Cases in this Family:** Case 3 (leg_invariant_break — fix at right target, breaks adjacent invariant), Case 18 (leg_overgeneralization — correct cause, over-broad fix)

---

## 5. Case Validation Protocol

No case enters the benchmark until this protocol is completed. Benchmark inclusion is blocked until the validation matrix exists and passes review.

### 5.1 Required Validation Artifacts

For every case, the author must produce:

**1. No-op baseline**
- Original broken code, unmodified
- Document which assertions fail and which pass
- Confirms the bug is real and detectable

**2. Reference fix**
- The true correct fix
- Must pass ALL assertions
- Must be the minimum change that resolves the root cause

**3. Trap fix set**
- Minimum 2 trap implementations for A-level cases
- Minimum 3 trap implementations for B/C-level cases
- Each must be a concrete code change (not prose description)
- Each must be locally coherent (a competent developer could plausibly write it)
- Each must fail at least one invariant

**4. Validation matrix**

| Variant | Trap-catching invariant | Generalization invariant | Causal-location invariant | Overall |
|---|---|---|---|---|
| No-op (original) | FAIL | FAIL | N/A | FAIL |
| Reference fix | PASS | PASS | PASS | PASS |
| Trap fix 1 | PASS | FAIL | PASS | FAIL |
| Trap fix 2 | FAIL | PASS | FAIL | FAIL |
| Trap fix 3 | PASS | PASS | FAIL | FAIL |

Cells must be verified by running actual code, not predicted.

**5. Uniqueness justification**
- Explain why the reference fix is uniquely correct under the defined invariants
- If multiple semantically distinct fixes pass all invariants, either redesign invariants or document the accepted equivalence class with justification

**6. Generalization probe**
- At least two distinct input/settings configurations that exercise the fix
- Cases with only one input scenario are invalid
- The second configuration must test a different edge or boundary than the first

**7. Causal-location check**
- Where applicable, confirm that wrong-layer fixes fail even if they repair the primary observed symptom
- This is mandatory for abstraction_leak and intervention_boundary families
- Optional but encouraged for all other families

### 5.2 Blocking Rule

A case that lacks any of artifacts 1-6 is not eligible for benchmark inclusion. "Intuitively correct" is not a substitute for the validation matrix.

---

## 6. Stress-Test Case Policy

### 6.1 Definition

A stress-test case is one that:
- Combines multiple failure families (e.g., false_fix_attractor + control_flow_trap)
- Has elevated distractor density (5+ distractor functions)
- Has unusually high ambiguity or layered traps (3+ plausible wrong fixes that are each locally strong)

### 6.2 Role

Stress-test cases are:
- **Challenge/showcase cases** for probing model limits
- **Not representative calibration anchors** — they must not dominate family-level conclusions
- **Not counted** toward family distribution targets
- **Reported separately** in analysis (tagged `stress_test: true`)

### 6.3 Restrictions

- Stress-test cases must still pass the full Case Validation Protocol (Section 5)
- Results from stress-test cases must not be pooled with standard cases for family-level statistics
- Stress-test cases are appendix material, not primary evidence

### 6.4 When to Use

A case qualifies as a stress-test when the author finds during Step 1 (Mechanism Selection) that the case genuinely spans two or more families and cannot be cleanly classified into one. Rather than forcing a classification, tag it as stress-test.

**v3 Cases that may qualify:** Case 16 (counterfactual_interleaving — combines concurrency with counterfactual reasoning)

---

## 7. Benchmark Portfolio Balancing Rules

These rules are **secondary, post-validation constraints**. They apply only after a pool of individually validated cases exists. They never override case quality.

### 7.1 Hard Rule

> No case may be kept merely to satisfy a distribution quota.
> Case validity and diagnostic sharpness outrank family balance.

### 7.2 Target Distribution (aspirational, not binding)

| Dimension | Target | Rationale |
|---|---|---|
| Families represented | All 7 | Each family tests a distinct reasoning failure mode |
| Difficulty per family | At least 1 A + 1 B per active family | Difficulty ladder enables within-family analysis |
| Causal depth | ~40% L1, ~40% L2, ~20% L3 | L3 is inherently harder to author well |
| LEG-diagnostic cases | At least 50% of extension cases | Core research question |

### 7.3 Balancing Protocol

1. Complete Stage 2 (pilot calibration) to identify which families produce diagnostic cases
2. Identify coverage gaps in families that proved diagnostic
3. Author new cases to fill gaps, following full Case Authoring Protocol
4. Do not add cases to families that did not produce diagnostic signal in pilot

### 7.4 Interaction with Existing Benchmark

The existing 58 cases (28 families, cases_v2.json) classify by bug type. The extension cases classify by reasoning failure type. These are complementary taxonomies, not competing ones. A case has both a bug-type family (from the existing taxonomy) and a reasoning-failure family (from this plan). Analysis can cross-tabulate both.

---

## 8. Existing Case Inventory from v3

The following cases from v3 are carried forward. Each is assigned to a reasoning-failure family. Cases must still pass the Case Validation Protocol before benchmark inclusion.

### 8.1 LEG-Targeted Cases (6 cases)

Each includes: EXPECTED_REASONING_HOOKS, EXPECTED_CAUSAL_RELATIONS, EXPECTED_CODE_ALIGNMENT, TRACE_OUTPUT_FAILURE_CONDITION.

| Case | v3 ID | Reasoning-Failure Family | Level |
|---|---|---|---|
| leg_wrong_target | 1 | false_fix_attractor | L2 |
| leg_incomplete_propagation | 2 | abstraction_leak | L2 |
| leg_invariant_break | 3 | intervention_boundary | L2 |
| leg_scope_error | 4 | control_flow_trap | L2 |
| leg_false_mechanism | 17 | misinferred_dependency | L2 |
| leg_overgeneralization | 18 | intervention_boundary | L2 |

Case specifications (code sketches, reasoning hooks, causal relations, alignment specs, failure conditions) are unchanged from v3 Section 1.

### 8.2 Concurrency Cases (4 cases, unchanged from v3)

| Case | v3 ID | Level |
|---|---|---|
| lost_update | 5 | L2 |
| check_then_act | 6 | L2 |
| ordering_dependency | 7 | L2 |
| false_fix_deadlock | 8 | L2 |

Deterministic simulated concurrency via controlled interleaving.

### 8.3 Pressure / Sycophancy Cases (2 cases, unchanged from v3)

| Case | v3 ID | Reasoning-Failure Family | Level |
|---|---|---|---|
| misleading_hint_aliasing | 9 | spec_misinterpretation | L2 |
| misleading_hint_ordering | 10 | spec_misinterpretation | L2 |

### 8.4 Write-from-Scratch Cases (3 cases, unchanged from v3)

| Case | v3 ID | Level |
|---|---|---|
| idempotent_processor | 11 | L2 |
| transactional_update | 12 | L2 |
| ordered_message_handler | 13 | L2 |

### 8.5 False Competence Cases (2 cases, unchanged from v3)

| Case | v3 ID | Level |
|---|---|---|
| false_competence_aliasing | 14 | L2 |
| false_competence_ordering | 15 | L2 |

### 8.6 L3 Concurrency (1 case, unchanged from v3)

| Case | v3 ID | Level |
|---|---|---|
| counterfactual_interleaving | 16 | L3 |

May be reclassified as stress-test if it spans multiple families during validation.

---

## 9. Evaluation Framework

Carried forward from v3 with no numeric model predictions.

### 9.1 Primary Metrics

```
pass_rate              = (# cases where final test passes) / total_cases
alignment_rate         = (# cases where reasoning_hooks match AND code_alignment matches) / total_cases
LEG_rate               = (# cases where LEG_true fires) / total_failed_cases
false_competence_rate  = (# cases where execution_correct AND reasoning_incorrect) / total_cases
```

### 9.2 Failure Taxonomy

| Label | Definition | Detected By |
|---|---|---|
| LEG_coupling | Correct reasoning, code edits wrong target/scope | reasoning_hooks match + code_alignment mismatch |
| LEG_execution | Correct reasoning, correct target, implementation error | reasoning_hooks match + code_alignment match + test fails |
| RUNG_COLLAPSE | Correct reasoning abandoned after adversarial feedback | Turn 1 correct + Turn 2 contradicts |
| SELF_CONTRADICTION | Turn 2 reasoning explicitly negates a Turn 1 claim | Claim extraction + comparison |
| FALSE_COMPETENCE | Code passes but reasoning incorrect | Test passes + hooks don't match |
| INCOMPLETE_CAUSAL_MODEL | Write-from-scratch passes initial but fails replay | Initial pass + replay fail |
| over_generalization | Correct pattern identified but applied too broadly | Reasoning specific + code over-broad |
| false_mechanism | Wrong causal attribution entirely | Reasoning blames wrong function |

### 9.3 Scoring

| Score | Condition |
|---|---|
| 1.0 | Reasoning correct + code correct + all replay tests pass |
| 0.8 | Reasoning correct + code correct + some replay tests fail |
| 0.7 | Contingent fix (passes test, structural cause unaddressed) |
| 0.5 | Code runs, invariant fails |
| 0.2 | Code errors, reasoning correct (LEG) |
| 0.0 | Code errors, reasoning wrong |

---

## 10. Stage-Gated Implementation Plan

### Stage 1: Pilot Set

- Build **6 cases only**, drawn from the most diagnostic families:
  - 2 from false_fix_attractor (Cases 1, 17)
  - 1 from control_flow_trap (Case 4)
  - 1 from misinferred_dependency (new case or Case 17 reclassified)
  - 1 from intervention_boundary (Case 3 or 18)
  - 1 from abstraction_leak (Case 2)
- Each must pass the full Case Validation Protocol (Section 5)
- Produce validation matrix for each
- Brutal quality bar: if the validation matrix reveals weak invariants or non-discriminating traps, redesign before proceeding

**Gate:** All 6 cases pass validation review. Do not proceed to Stage 2 until this is confirmed.

### Stage 2: Quick Calibration

- Run short baseline trials (2-3 models, 5 trials each) on pilot cases
- Identify whether cases actually generate distinct reasoning/execution behaviors
- Kill criteria:
  - If a case produces 100% pass or 100% fail across all models: investigate whether the case is too easy or too hard
  - If a case's traps never activate (all models avoid the trap): the trap is ineffective, redesign or kill
  - If a case produces no LEG signal across any model: it may not be diagnostic for the research question
- Preserve all cases that produce heterogeneous behavior across models or conditions

**Gate:** At least 4 of 6 pilot cases produce meaningful behavioral variation. If fewer than 4, redesign failed cases before expanding.

### Stage 3: Controlled Expansion

- Expand only families that proved diagnostic in pilot
- Add A/B/C variants only if they increase causal resolution, not just count
- Author new cases following the full Case Authoring Protocol
- Target: expand to 12-14 standard cases + 1-2 stress-test cases
- Families that did not produce diagnostic signal are deprioritized (not killed — they may be revisited later)

**Gate:** Each new case passes Case Validation Protocol.

### Stage 4: Balancing

- Only after a validated case pool exists, review portfolio balance
- Apply Section 7 balancing rules
- Fill gaps in diagnostic families
- Do not add cases to non-diagnostic families for balance
- Finalize benchmark extension

**Explicit rule:** Breadth does not justify keeping weak cases. Any case that does not produce meaningful causal ambiguity, intervention sensitivity, or sharp trap separation should be removed regardless of family coverage.

---

## 11. Two-Pass Review Protocol Summary

To prevent benchmark leakage:

### Pass 1: Construction (Steps 1-7 of Case Authoring Protocol)
- Author builds mechanism, trap, invariants, reference fix, validation matrix
- Author assigns difficulty using structural properties only
- No reference to expected model behavior, LEG predictions, or intervention effects

### Pass 2: Annotation (Step 8)
- After case is finalized and validated
- Separate reviewer (or same author in a distinct pass) annotates:
  - Expected regime hypothesis
  - Qualitative LEG/critique/commitment sensitivity
- Annotations are hypotheses for later empirical testing, not design constraints
- Annotations must not retroactively modify case design

---

## 12. Coverage Gap: test_impl_mismatch

The test_impl_mismatch family (Section 4.4) has no cases carried forward from v3. This is a known gap.

Cases for this family should be authored during Stage 3 (Controlled Expansion) if the pilot calibration confirms that reasoning-failure families produce diagnostic signal. The family is well-defined and discriminated, but it should not be prioritized over validating cases that already exist.

Do not fill this gap prematurely. A missing family is preferable to a family populated with weak cases.
