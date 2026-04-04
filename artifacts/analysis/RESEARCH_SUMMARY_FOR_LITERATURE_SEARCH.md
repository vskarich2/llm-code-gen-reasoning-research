# Research Summary: Diagnosing and Intervening on LLM Code Generation Failures

**Purpose:** This document summarizes what we are doing, what we have found, and what appears novel — to guide a literature search for related prior work.

---

## 1. What We Are Studying

We study **why LLMs fail at code generation tasks that require causal reasoning about program state**, and whether **targeted interventions** can selectively fix specific failure types.

The domain is **refactoring tasks with hidden invariants**: the LLM is asked to simplify or consolidate code, and the correct answer requires preserving a causal dependency that is not obvious from the prompt. The task is adversarial by design — the "obvious" simplification breaks something.

We test on small, deterministic Python programs (1–4 files, 20–150 lines) where the bug is silent (code runs without crashing but violates a testable invariant). We evaluate with execution-based tests, not text matching.

---

## 2. The Core Finding: Three Failure Regimes

We empirically identified three distinct failure regimes in LLM code generation. These are not hypothetical categories — they were discovered through controlled experiments (324 variance-controlled API calls across 3 models × 18 cases × 3 replications).

### REI (Reasoning–Execution Inconsistency)

- The model's reasoning trace **correctly identifies** the bug and the invariant to preserve
- The generated code **does not implement** the identified fix
- Small structural interventions (contracts, retry with feedback) **reliably fix** these cases
- Retry converges within 1–2 iterations
- **Empirical signature:** reasoning_valid=True, pass=False, convergence_slope > 0, error_stable=True

### Heuristic Competence

- The model succeeds via **pattern matching** from training data, not causal simulation
- The model passes without deep reasoning (e.g., `.copy()` for aliasing bugs, `try/except` for rollback)
- Adding scaffolding (contracts, causal models) **actively hurts** performance by disrupting the working heuristic
- **Empirical signature:** pass_first_try=True at baseline, CGE delta negative, retry may degrade

### CSF (Causal Simulation Failure)

- The model **cannot simulate** multi-step state evolution required by the task
- Fails even with contracts, causal graphs, retry, and all scaffolding
- Retry does not converge — errors persist or mutate across iterations
- **Empirical signature:** pass=False across all conditions, error_entropy high, convergence_slope ≈ 0, reasoning may or may not be valid

### Key Property: Regimes Are Model-Relative

The same case can be REI for a capable model (4o-mini) and CSF for a weaker one (nano). The regime describes the **gap between task difficulty and model capability**, not an intrinsic case property. This means interventions must be targeted per-model, not per-case.

---

## 3. The Intervention Framework

### 3A. Contract-Gated Execution (CGE)

Before generating code, the model emits a **structured execution contract** declaring:
- What it will change (`must_change`) and what it must preserve (`must_not_change`)
- Behavioral commitments from a closed vocabulary (e.g., `add_rollback_on_failure`, `prevent_duplicate_effect`, `preserve_effect_order`)
- Ordering constraints on side effects
- Invariants to maintain

A **deterministic diff gate** (rule-based, not neural) then validates the generated code against this contract. If violations are found, the model retries with specific violation feedback.

**CGE results (controlled experiment, 3 replications):**
- On REI cases: CGE PASS 3/3 where baseline FAIL 3/3 (e.g., retry_causality on 4o-mini)
- On Heuristic cases: CGE FAIL 3/3 where baseline PASS 3/3 (e.g., easy_aliasing on 4o-mini)
- On CSF cases: CGE has zero effect (0% change across 54 controlled run-pairs)

### 3B. Structural Causal Model (SCM) Prompting

We experimented with providing LLMs an explicit causal graph of the code:
- Functions and variables as nodes
- Data-flow edges between them
- Constraints and invariants labeled
- Critical evidence sets identified

**SCM results:** Mixed. The most informative SCM condition (full graph + constraints + evidence) did not significantly outperform a **length-matched control** (same token count of meaningless filler). This suggests prompt length, not causal structure, may drive improvement for some models — a confound that challenges purely structural explanations of why scaffolding helps.

### 3C. Retry with Trajectory Logging

A scientific retry harness that runs up to K iterations with:
- Structured error feedback after each failure
- Optional LLM-generated critique (separate model call analyzing the failure)
- Full trajectory logging (code, reasoning, error, diff, critique per iteration)
- Post-hoc computation of: convergence slope, error entropy, edit dispersion, critique accuracy, trajectory type classification

**Retry serves as a diagnostic instrument, not just an optimization strategy.** The convergence dynamics themselves classify the failure regime.

### 3D. Adaptive Retry (Planned)

A failure classifier (heuristic, not LLM-based) categorizes the error type at each iteration and selects a regime-appropriate hint. Confidence-gated: only applies the hint when classifier confidence exceeds a threshold; otherwise uses a generic default.

---

## 4. The Benchmark

### V1: 37 cases (18 original hard + 19 difficulty variants)
- Tested with gpt-4.1-nano, gpt-4o-mini, gpt-5-mini
- 19 experimental conditions × 3 models = 1,000+ API calls
- Baseline pass rates: nano 0–5%, 4o-mini 19–28%, 5-mini 3–8%

### V2: 45 cases (15 families × 3 difficulty levels)
- 15 bug pattern families spanning 7 failure classes
- Each family has Level A (easy, 1 file, L1 causal depth), Level B (medium, 2 files, L2), Level C (hard, 3+ files, L3)
- Execution-based tests with deterministic invariant checking
- Ground truth bug metadata per case (type, location, invariant, fix pattern)
- Validated: 45/45 pass all 4 critical checks (loads, fails on buggy code, passes on fixed code, idempotent tests)

### Bug Pattern Taxonomy (grounded in real codebase forensic audit)

| Pattern | Definition | Example |
|---|---|---|
| implicit_schema | Producer/consumer disagree on data shape | Dict returned by reference; consumer assumes fresh copy |
| partial_state_update | Multi-resource update not atomic | Reserve inventory, charge fails, no rollback |
| hidden_dependency | Function depends on invisible behavior of another | Cache write-through path broken by refactor |
| silent_failure | Error produces valid-looking but wrong output | `.get(key, default)` with mismatched key name |
| retry_state_accumulation | Retry/re-execution grows state or duplicates effects | Mutable default argument, nested retry |
| execution_model_mismatch | Code for one execution model used in another | Eager init when lazy is required |
| edge_case_omission | Valid input not handled | Missing branch, off-by-one, uninitialized variable |

---

## 5. Key Quantitative Results

| Finding | Data |
|---|---|
| CGE helps REI, hurts Heuristic, no effect on CSF | Controlled: 324 calls, 3 replications, 3 models |
| 5 cases form "hard CSF core" — nothing helps them | 0% pass across ALL models × ALL 19 conditions |
| Reasoning-execution gap affects 44–67% of failures | 3 models, 18 cases, measured via keyword + trajectory signals |
| Length-matched control ties best SCM condition | 4o-mini: 8/18 for both length_matched_control and scm_descriptive |
| Retry convergence is regime-diagnostic | REI: 60% converge, Heuristic: 57%, CSF: 0% |
| More reasoning scaffolding increases REI rate | Diagnostic condition: 71% REI rate (highest of all conditions) |
| 4o-mini baseline variance: std=1.53 across 3 runs | Single-run CGE claims are unreliable |
| REI is compliance failure, not reasoning failure | 38% of REI instances: model echoes correct analysis, then follows the (wrong) prompt instruction anyway |

---

## 6. Research Questions

### Primary

**RQ1:** Do LLM code generation failures exhibit distinct failure regimes with different correction dynamics?

**RQ2:** Can interventions (contracts, retry, causal scaffolding) be targeted to specific regimes, and does targeting outperform uniform application?

**RQ3:** How does the failure regime boundary shift across models of different capability?

### Secondary

**RQ4:** Is the reasoning-execution gap a reasoning failure or an execution failure? (Our evidence: it's execution — the model reasons correctly but doesn't follow its own reasoning in code generation.)

**RQ5:** Does providing explicit causal structure (SCM graphs) improve code generation beyond the effect of prompt length?

**RQ6:** Can retry convergence dynamics serve as a post-hoc classifier of failure regimes?

**RQ7:** What bug patterns are most resistant to all interventions (the "CSF core")?

---

## 7. What Appears Novel

### 7A. The 3-Regime Framework Itself

We are not aware of prior work that classifies LLM code generation failures into distinct regimes (REI/Heuristic/CSF) with **different intervention prescriptions per regime**. Most LLM evaluation work treats failure as monolithic: either the model passes or it doesn't. We show that the failure type determines which intervention works, and applying the wrong intervention (CGE on Heuristic cases) actively degrades performance.

### 7B. Model-Relative Regime Classification

The regime is not a case property — it's a property of the (model, case) pair. This is a stronger claim than "some cases are harder than others." It means the optimal intervention strategy must be conditioned on model capability, not just task difficulty.

### 7C. Contracts as Regime-Specific Intervention

Contract-Gated Execution is not new (it resembles design-by-contract and specification-first programming). What's new is the empirical demonstration that it is **regime-specific**: it helps REI, hurts Heuristic, and does nothing for CSF. This reframes CGE from "a general code quality technique" to "a precision tool for a specific failure mode."

### 7D. Retry Dynamics as Diagnostic Signal

Using the shape of the retry trajectory (convergence slope, error entropy, edit dispersion) to classify the failure mechanism is, to our knowledge, novel. Most retry/self-repair work focuses on whether retry succeeds or fails. We use HOW it fails to diagnose WHY.

### 7E. Adversarial Refactoring as Evaluation

The benchmark uses refactoring prompts where the "obvious" simplification introduces a bug. This is different from typical code generation benchmarks (HumanEval, MBPP, SWE-bench) that test whether the model can write correct code from scratch. Our benchmark tests whether the model can **preserve causal invariants under transformation** — a qualitatively different capability.

### 7F. Length-Matched Control Confound

The finding that a length-matched control (meaningless filler text of the same token count as the SCM prompt) performs equally well raises questions about whether structured prompting improvements are attributable to the structure or to prompt length/attention effects. This is a methodological contribution applicable beyond our specific framework.

### 7G. REI as Compliance Failure

Our deep analysis of REI instances found that 38% involve the model correctly identifying the bug in its reasoning trace, then complying with the (adversarial) task prompt instruction anyway. This reframes REI from "the model can't execute its reasoning" to "the model's code generation is dominated by instruction-following over self-generated reasoning" — a finding about the architecture of LLM code generation, not just its performance.

---

## 8. Related Work Areas to Search

The following areas are most likely to contain prior work that overlaps with ours:

### 8A. LLM Code Generation Evaluation & Benchmarks
- HumanEval, MBPP, SWE-bench, CodeContests, ClassEval
- Multi-file code generation benchmarks
- Execution-based evaluation vs. match-based
- Difficulty laddering in benchmarks

### 8B. Self-Repair / Self-Debugging / Iterative Refinement
- Self-repair in code generation (Chen et al., Olausson et al., Zhang et al.)
- Self-debugging (Chen et al. 2023)
- Reflexion (Shinn et al.)
- Test-driven code generation with feedback loops
- Convergence analysis of iterative refinement

### 8C. Reasoning-Execution Gap / Faithfulness
- Chain-of-thought faithfulness in code generation
- Planning vs. execution in LLMs
- "Knowing vs. Doing" in language models
- Instruction following vs. self-reasoning conflicts

### 8D. Contract / Specification-Guided Code Generation
- Design by contract for LLMs
- Specification-first programming
- Formal verification integration with LLMs
- Pre-commitment strategies in generation

### 8E. Causal Reasoning in LLMs
- Causal inference capabilities of LLMs
- Structural causal models + LLMs
- Program dependency analysis by LLMs
- State tracking in language models

### 8F. Failure Mode Analysis / Error Taxonomy
- Taxonomy of LLM coding errors
- Root cause analysis of code generation failures
- Bug pattern classification in AI-generated code
- Silent failures / semantic bugs vs. crash bugs

### 8G. Prompt Engineering / Scaffolding for Code
- Chain-of-thought for code generation
- Tree-of-thought / branching reasoning
- Structured output formats
- Prompt length effects on performance

### 8H. Adaptive Intervention / Meta-Learning
- Dynamic strategy selection for LLMs
- Confidence-based intervention gating
- Meta-cognitive scaffolding
- When to intervene vs. when to leave alone

### 8I. Multi-Step Code Editing / Refactoring
- Code refactoring with LLMs
- Invariant preservation in code transformation
- Program repair
- Mutation testing and bug seeding

### 8J. Capability Boundaries / Scaling
- Model capability analysis across scales
- Capability thresholds and phase transitions
- Task difficulty vs. model size interactions
- When do larger models fail?

---

## 9. Terminology for Search

Key terms that a literature search agent should query:

- "LLM code generation failure modes"
- "reasoning execution gap code generation"
- "self-repair code generation convergence"
- "contract-gated code generation"
- "causal reasoning LLM code"
- "code generation retry dynamics"
- "specification-guided code generation"
- "LLM refactoring invariant preservation"
- "failure regime classification LLM"
- "adaptive intervention code generation"
- "prompt scaffolding code generation"
- "self-debugging convergence analysis"
- "design by contract neural code generation"
- "silent bugs LLM code generation"
- "chain of thought faithfulness code"
- "execution-based evaluation code generation"
- "SWE-bench failure analysis"
- "multi-file code generation benchmark"
- "causal simulation failure language models"
- "heuristic pattern matching vs reasoning LLM"
