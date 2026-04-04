# Project Overview: Measuring and Reducing the Latent Execution Gap in LLM Code Generation

## 1. What This Project Is

### Background: From Portfolio Allocation to Code Generation

This project is a continuation of work begun as the CS372 final project (Winter 2026), where we studied the gap between LLM reasoning quality and task performance in a multi-agent debate system for stock portfolio allocation. That project applied RAudit-style blind auditing and RCA-style trace-output consistency checking to measure whether agents that produced high-quality causal reasoning actually made better investment decisions. The central finding was that they did not — CRIT reasoning scores showed no meaningful correlation with financial returns (r = +0.07, p = 0.29 across 210 runs). Structured debate raised reasoning quality by 17.7% without improving outcomes. The reasoning was better, but the decisions were not.

That result raised a deeper question: is the disconnect between reasoning and performance a general property of LLMs, or was it specific to the noisy, feedback-delayed domain of financial markets? Portfolio allocation is a hard test bed — the ground truth is ambiguous, the feedback loop is long, and "correct reasoning" is difficult to define independently of outcomes. We needed a domain where we could measure the gap more precisely.

Code generation is that domain. It offers three properties that portfolio allocation lacks. First, **deterministic ground truth**: code either passes its test suite or it doesn't — no noise, no ambiguity, no market randomness. Second, **inspectable reasoning**: we can read the model's stated root cause and fix strategy and compare it structurally against what the code actually does, rather than relying on post-hoc financial evaluation. Third, **mechanistic decomposition**: when code fails, we can distinguish between "the model didn't understand the bug" and "the model understood the bug but produced broken code" — a distinction that was impossible to make cleanly in the trading domain.

This project takes the same core question — does better reasoning produce better performance? — and moves it to a setting where we can actually answer it. The Latent Execution Gap (LEG) is the code-generation-specific version of the reasoning-performance disconnect we observed in portfolio allocation: models that demonstrably understand a bug mechanism but cannot translate that understanding into working code.

### This Project

This is a research benchmark system for studying a specific phenomenon in LLM code generation: the **Latent Execution Gap (LEG)** — cases where a model demonstrates correct reasoning about a software bug but produces code that fails tests.

The system generates buggy code repair tasks, sends them to LLMs under various experimental conditions, evaluates both the model's reasoning and its code output independently, and measures whether structured reasoning interventions can close the gap between understanding and execution.

The core question: **When a model knows what's wrong, why does it still produce broken code — and can we make it stop?**

### Scale

The full dataset spans **42,188 evaluations** across **8 models**, **6 experimental conditions**, **58 benchmark cases** organized into **28 bug families**, with up to **50 trials per (case, model, condition)** triple for statistical power.

### Models Tested

| Model | Provider | Evaluations |
|---|---|---|
| gpt-4o-mini | OpenAI | 10,535 |
| gpt-5.4-mini | OpenAI | 10,505 |
| gpt-5-mini | OpenAI | 8,463 |
| gpt-4.1-nano | OpenAI | 7,854 |
| claude-sonnet-4-6 | Anthropic | 2,418 |
| claude-haiku-4-5 | Anthropic | 1,262 |
| gpt-5 | OpenAI | 980 |
| claude-sonnet-4 | Anthropic | 171 |

---

## 2. The Benchmark Cases

### Case Structure

Each case is a **realistic software bug** embedded in Python code. Cases are not toy examples — they involve real patterns like shared mutable references, stale caches, partial state updates, race conditions, and hidden cross-module dependencies. The model receives the buggy code and a refactoring task (the task does NOT say "fix the bug" — the model must discover the bug through reasoning).

**58 cases** organized into **28 families** at **3 difficulty levels** (A/B/C) plus 2 L3-depth cases:

| Difficulty | Cases | Description |
|---|---|---|
| A | 15 | Single-file, single-function bugs. Correct fix is typically 1-3 lines. |
| B | 15 | Single-file but requires understanding cross-function interactions. |
| C | 26 | Multi-file, cross-boundary bugs. Requires tracing dependencies across modules. |
| L3 | 2 | Deep causal chains (3+ hops) requiring multi-step pipeline reasoning. |

### Bug Families and Failure Modes

Each case has a classified `failure_mode` (22 distinct types) and a higher-level `bug_pattern_class` (7 types):

**Bug pattern classes:**
- `hidden_dependency` (14 cases) — bugs where the root cause is in a different module than the symptom
- `partial_state_update` (13) — updating some fields but not dependent ones
- `edge_case_omission` (10) — missing branches or unhandled input cases
- `implicit_schema` (6) — unstated contracts between components
- `retry_state_accumulation` (6) — state that persists incorrectly across retries
- `execution_model_mismatch` (5) — wrong assumptions about execution order
- `silent_failure` (4) — failures that don't raise but produce wrong results

### What a Case Looks Like

**Simple case (alias_config_a, difficulty A):**
```python
# config.py — 16 lines
DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}

def create_config(overrides=None):
    config = DEFAULTS           # BUG: returns reference, not copy
    if overrides:
        config.update(overrides)
    return config
```
The model receives: "Refactor this configuration module for clarity. Return the updated code."

The bug: `create_config` returns `DEFAULTS` directly. Calling `create_config({"timeout": 5})` mutates the global `DEFAULTS`, so the next call to `create_config()` returns `{"timeout": 5}` instead of `{"timeout": 30}`. Fix: `config = DEFAULTS.copy()`.

**Complex case (hidden_dep_multihop, difficulty C, 4 files):**
Files: `cache_reader.py`, `cache_writer.py`, `user_repo.py`, `user_service.py`.
Bug: `save_user()` calls `refresh_user_snapshot()` which uses `cache_put_if_absent()` (won't overwrite), but the write-through cache requires `cache_put()` (always overwrites). After renaming a user, `get_display_name()` returns the stale cached name. Fix requires tracing a 3-hop dependency chain.

### How Cases Are Validated

Each case has an **invariant test** in `tests_v2/test_{family}.py`. Tests follow a uniform contract:

```python
def test_a(mod):
    """Accept the merged module namespace, exercise the function, check the invariant."""
    # Reset state
    mod.reset_defaults()
    # Exercise
    c1 = mod.create_config({"timeout": 5})
    c2 = mod.create_config()
    # Invariant
    if c2["timeout"] != 30:
        return False, ["create_config() returned timeout=5, expected 30 — shared reference not copied"]
    return True, []
```

Returns `(passed: bool, reasons: list[str])`. The test must **fail on buggy code** and **pass on correct code**. This is verified by preflight checks before every experiment run.

### Case Metadata

Each case carries rich metadata for analysis:
- `failure_mode`: specific bug type (ALIASING, STALE_CACHE, etc.)
- `bug_pattern_class`: higher-level grouping
- `boundary_type`: local, cross_function, or cross_boundary
- `causal_depth`: L1 (direct), L2 (one hop), L3 (multi-hop)
- `temporal_depth`: single_step or multi_step
- `ground_truth_bug`: authoritative bug description with type, location, invariant, fix_pattern
- `trap`: description of the plausible-but-wrong fix (if any)
- `expected_regime_hypothesis`: per-model predictions of behavior

---

## 3. Experimental Conditions

The system tests 6 primary experimental conditions — 3 single-shot and 3 retry-based:

### Single-Shot Conditions

**baseline_v2**: The model receives the task description, the buggy code, and a JSON output instruction. It must produce `root_cause`, `fix_strategy`, and `files` (the repaired code). No structured reasoning scaffolding.

**leg_reduction_v2 (Full LEG)**: The model follows a 5-step structured reasoning process before writing code:
1. Diagnose the mechanism (name the specific function/variable, explain the causal chain)
2. State explicit fix commitments in `<scope> must <action>` form (1-3 commitments)
3. Plan the fix (name the file/function, describe the exact change)
4. Risk check (what could still go wrong? revise if needed)
5. Return fixed code as JSON

This forces the model to articulate its reasoning before producing code, testing whether making reasoning explicit reduces the execution gap.

**leg_reduction_lean_v2 (Lean LEG)**: Same structure as full LEG but with compressed instructions (~60 lines vs ~110 lines). Fewer examples, shorter step descriptions. Tests whether the reasoning benefit comes from the structure itself or from the verbosity of instruction.

### Retry Conditions

**retry_bare_retry_v2**: Pure control. On failure, the model receives its previous response and the same prompt. No feedback, no critique. Tests whether simple re-rolling helps.

**retry_leg_critique_strict_v2**: On failure, a separate LLM call generates a one-sentence mismatch critique comparing the model's stated reasoning to its code. The critique is fed back with the previous response for revision. The critique is deliberately non-prescriptive — it describes the mismatch but does not suggest a fix.

**retry_reasoning_only_critique_v1**: On failure, a separate LLM call identifies the weakest claim in the model's reasoning (without seeing the code). Tests whether reasoning-level feedback is sufficient without code-level feedback.

All retry conditions run up to 3 attempts with a 300-second timeout.

---

## 4. The Evaluation Pipeline

### End-to-End Flow

```
Case + Condition → Prompt Assembly → LLM Call → Response Parsing →
File Reconstruction → Subprocess Execution → LLM Classification →
Metric Derivation → Logging
```

### 4.1 Prompt Assembly

Prompts are constructed through a strict compiler system (`pipeline/prompting/compiler.py`). Each prompt is assembled from typed components loaded from `prompts/components/*.j2` with metadata-defined contracts (`prompts/component_metadata.yaml`). The compiler validates inputs, tracks variable access at runtime, and produces a `CompiledPrompt` artifact with full provenance (component hashes, accessed/unused inputs, composition hash).

The prompt manifest (`prompts/prompt_manifest.yaml`) maps each condition to its component list. Section markers in templates enable structural validation — the compiler verifies that declared sections match rendered sections.

### 4.2 Response Parsing (Three-Tier Architecture)

The model's raw text response goes through three independent parsers:

**Execution parser** (drives the pipeline): Extracts the first balanced JSON object from the response. Tolerates markdown fences and surrounding text. Rejects empty responses, multiple JSON objects, and non-dict results. Does NOT repair broken JSON. If this parser fails, the case is marked `parser_failure_v2` and no further evaluation occurs.

**Format parser** (diagnostic only): Checks whether the model followed output instructions exactly — no fences, no extra text, only the JSON block. Records `format_valid` for analysis but does not affect the pipeline.

**Recovery parser** (diagnostic only): Attempts controlled repairs through 6 phases: fence stripping, triple-quote repair, invalid escape fixing, `code`→`files` key rename. Records what could have been recovered but does not feed into the pipeline. This measures the upper bound of what better parsing could rescue.

### 4.3 File Reconstruction (5-Gate Validation)

The parsed JSON's `files` dict maps file paths to either `"UNCHANGED"` or the complete repaired file contents. The reconstructor validates each file through 5 gates:

1. **Exact UNCHANGED check** — use original file content
2. **Empty/whitespace rejection** — blocks execution
3. **No-change phrase detection** — catches 30 common sentinel phrases like "same as original", "keep as is" — blocks execution
4. **AST parse validation** — `ast.parse()` on every file; syntax errors block execution
5. **Semantic structure check** — compares function/class definitions against original (diagnostic only, never blocks)

Only `status == "SUCCESS"` proceeds to execution. Any gate failure produces a specific category (`RECON_EMPTY_FILE`, `RECON_SENTINEL_MISMATCH`, `RECON_INVALID_CODE`) and the case is scored 0.

### 4.4 Subprocess Execution

Code is executed in an isolated subprocess via `exec_canonical`:

1. **Materialize**: Write reconstructed files to a temp directory as a Python package
2. **Spawn subprocess**: Run `harness/run_case.py` with `PYTHONPATH` set to the package + project root
3. **The harness**: Imports all modules, builds a merged namespace with conflict detection, discovers the test function from `tests_v2/`, runs it, emits structured JSON to stdout
4. **Classify result**: Map subprocess output to one of 13 categories with scores from 0.0 (crash/syntax/import failure) to 0.2 (invariant failure) to 1.0 (execution success)

The subprocess has a configurable timeout (default 30s). Timeout, crash, or unparseable output all score 0. The harness includes call tracing — it records which functions the test actually invoked, which is useful for diagnosing why code that "looks right" still fails.

### 4.5 LLM-Based Reasoning Classification

After execution, a separate LLM call (the "evaluator model", typically gpt-5-mini) classifies the generator model's reasoning quality. The classifier receives the model's `root_cause`, `fix_strategy`, `risk_check` (if present), the task description, and the generated code. It does NOT receive execution results — it evaluates reasoning-code consistency, not correctness.

The classifier scores 4 dimensions:

| Dimension | What it measures |
|---|---|
| `mechanism_identified` | Did the model correctly identify the bug mechanism with a concrete code anchor? |
| `commitments_extracted` | Did the model articulate valid, checkable fix commitments that map to canonical patterns? |
| `commitments_satisfied` | Does the code implement the stated commitments? |
| `reasoning_code_alignment` | Does the code match the stated fix strategy? |

Each dimension is scored `CORRECT`, `PARTIAL`, or `WRONG`. The classifier also assigns a `failure_type` from a closed vocabulary of 9 types (ALIASING, STALE_CACHE, HIDDEN_DEPENDENCY, etc.).

**Canonical commitment patterns**: The classifier prompt includes 30 canonical commitment patterns across 10 bug families. These serve as a reference for the evaluator to check the model's commitments against — e.g., for ALIASING bugs, canonical commitments include "returned objects must not share mutable references with global defaults." This constrains the evaluator's judgment space but also means the evaluator is not truly blind to the answer space.

**Grounded vs blind mode**: In `grounded` mode, the classifier additionally receives ground truth (bug type, location, invariant). In `blind` mode (the default for most experiments), it does not. The classifier evaluates reasoning quality, not correctness — it checks whether the code implements the stated reasoning, regardless of whether that reasoning is right.

### 4.6 Metric Derivation

From execution results (pass/fail) and classifier dimensions, the system derives categorical labels:

| Category | Definition |
|---|---|
| `interpretable_success` | Code passes AND mechanism correct AND commitments valid AND alignment positive |
| `LEG_v2` | Code fails AND mechanism correct AND commitments valid AND alignment NOT positive |
| `lucky_fix_v2` | Code passes AND mechanism NOT correct (or commitments not valid) |
| `full_failure_v2` | Code fails AND mechanism NOT correct |
| `alignment_failure_pass` | Code passes AND mechanism correct AND commitments valid AND alignment NOT positive |
| `uninterpretable_success` | Code passes AND no commitments source AND commitments not valid |
| `classifier_failure_v2` | Any classifier dimension is None (parse failure) |

The key metric is `LEG_v2` — the subset of failures where the model demonstrably understood the bug but couldn't translate that understanding into working code.

Three primary boolean signals are tracked separately (not collapsed):
- `mechanism_correct` = mechanism_identified is CORRECT
- `commitments_valid` = commitments_extracted is CORRECT or PARTIAL
- `alignment_positive` = reasoning_code_alignment is CORRECT

A backward-compatible `reasoning_correct` rollup exists (`mechanism_correct AND commitments_valid AND alignment_positive`) but is explicitly labeled as "NOT primary scientific measure" in the code.

---

## 5. What We Measure

### Primary Metrics

**Pass rate**: Fraction of trials where generated code passes the invariant test. This is the ground truth metric — deterministic, trustworthy, not dependent on LLM judgment.

**LEG rate**: Fraction of trials classified as `LEG_v2` — correct reasoning, failed code. This depends on the LLM classifier, which introduces noise, but the 2x2 matrix of (reasoning correct/wrong) x (code passes/fails) is the core analytical framework.

**Intervention effect (delta-pass)**: Per-(case, model) paired difference in pass rate between a treatment condition and baseline. Positive delta means the intervention helped.

### Derived Metrics

**Help rate**: Fraction of (case, model) pairs where delta-pass > 10pp.
**Harm rate**: Fraction where delta-pass < -10pp.
**Help/harm ratio**: Help rate / harm rate. A ratio > 1 means the intervention helps more often than it hurts.

**LEG conversion rate**: Among (case, model) pairs with baseline LEG rate >= 40%, what fraction see LEG rate drop AND pass rate increase under the intervention?

**Reconstruction-conditioned metrics**: All metrics recomputed on only the trials where code extraction succeeded. This separates genuine reasoning effects from parsing/reconstruction artifacts.

### What We Do NOT Trust

The LLM classifier's accuracy has been flagged as unreliable in the system design docs — the system design document notes "DISQUALIFIED due to brevity bias and 33% accuracy on known-good reasoning." The primary scientific claims rest on pass rate (deterministic) and intervention deltas (paired within-subject), not on the absolute LEG rate. The classifier is useful for decomposing failures into categories but its individual judgments are noisy.

---

## 6. Preliminary Results

### Headline Finding: Retry Dominates Single-Shot

| Intervention | Mean delta-pass | Help/Harm Ratio |
|---|---|---|
| Lean LEG (single-shot) | -0.001 | 0.97 |
| Full LEG (single-shot) | -0.003 | 1.10 |
| Bare retry (no feedback) | +0.053 | 4.63 |
| Retry + strict critique | +0.079 | 5.21 |
| Retry + reasoning critique | +0.075 | **9.64** |

Single-shot LEG interventions (both full and lean) are approximately **neutral on average** across the full 58-case benchmark. They help and hurt at roughly equal rates (~15% each). Their value is case-specific, concentrated in cross-boundary cases with high baseline LEG rates.

Retry-based interventions dominate. Retry + reasoning-only critique has the best help/harm ratio at 9.64:1 — it helps 21% of (case, model) pairs by more than 10pp and hurts only 2.2%.

### Where LEG Scaffolding Helps

From the 7,800-evaluation canonical analysis (4 models, 13 targeted cases, 50 trials each):

- **19 genuine LEG-helps** across 7 cases — all cross-boundary or multi-step reasoning bugs
- LEG never harms LEG-suffering models: of 17 (case, model) pairs with baseline LEG rate >= 40%, LEG intervention helps 35%, is neutral 65%, and harms **0%**
- Best case: `commit_gate/nano/lean` — 100% LEG conversion rate (34pp LEG reduction maps directly to 34pp pass rate increase)
- Lean outperforms full LEG in 6 of 8 direct comparisons, often by 3-3.75x margin

### Where LEG Scaffolding Hurts

- **6 genuine LEG-hurts** across 3 cases — all high-baseline-pass cases where the model already succeeds
- `alias_config_c` (a trivial 1-word fix): nano drops from 100% to 8% under LEG — the serialization overhead of structured output destroys a fix the model produces easily at baseline
- `config_shadowing/5.4-mini`: 5.4-mini is the only model that fixes the structural root cause at baseline; LEG derails it to a surface-level fix

### Cross-Provider Findings

Anthropic models show different failure patterns:
- **Haiku**: 78% reconstruction failure rate due to triple-quoted Python strings in JSON. The model often produces correct code but in an unparseable format. Under LEG, reconstruction improves dramatically (0% strict pass -> 100% recovered), suggesting the structured format helps Haiku produce parseable output.
- **Sonnet-4**: Zero reconstruction failures but 92% LEG rate on `lost_update` with 0% pass across all conditions. Sonnet-4 correctly identifies the non-atomic read-modify-write bug every time but cannot serialize the step-function simulation code correctly.

### Model Capability Is the Dominant Factor

Mixed-effects models show model capability is the primary driver of pass rate:
- 5.4-mini is +32.6pp above nano (p < 0.001)
- 5-mini is +22.6pp above nano (p < 0.001)
- LEG's marginal effect is small and often non-significant after controlling for model

---

## 7. System Architecture

### Execution Path (V2 Production)

```
runner.py
  ├── Load config YAML
  ├── Load cases from cases_v2.json
  ├── Preflight: verify every case has a test function
  │
  ├── For each (case, condition) pair:
  │   │
  │   ├── baseline/leg/lean → execution_v2.run_v2()
  │   │     ├── Compile prompt (pipeline/prompting/compiler.py)
  │   │     ├── Call generator model (pipeline/llm.py)
  │   │     ├── Parse response (parser_v2.py, three-tier)
  │   │     ├── Normalize reasoning (reasoning_v2.py)
  │   │     ├── Reconstruct files (reconstructor.py, 5-gate)
  │   │     ├── Execute in subprocess (exec_canonical.py)
  │   │     ├── Classify reasoning (evaluator_v2.py → LLM call)
  │   │     ├── Derive metrics (metrics_v2.py)
  │   │     └── Log (logging_core.py)
  │   │
  │   └── retry_* → retry_v2.run_retry_v2()
  │         ├── Same pipeline per attempt (up to 3)
  │         ├── On failure: generate critique (compiled .j2 template)
  │         ├── Build retry prompt with critique
  │         └── Classify best result after loop
  │
  └── Emit run metrics
```

### Module Organization

| Layer | Modules | Purpose |
|---|---|---|
| **Entry** | `runner.py`, `experiment_config.py` | Config loading, dispatch, preflight |
| **Prompting** | `pipeline/prompting/` (13 modules) | Strict prompt compilation with contracts |
| **LLM** | `pipeline/llm.py` | OpenAI/Anthropic API calls with logging |
| **Parsing** | `pipeline/parsing/parser_v2.py` | Three-tier JSON extraction |
| **Reconstruction** | `pipeline/reconstructor.py` | 5-gate file reconstruction |
| **Execution** | `pipeline/execution/exec_canonical.py`, `harness/run_case.py` | Subprocess-isolated test execution |
| **Evaluation** | `evaluation/evaluator_v2.py`, `evaluation/metrics_v2.py` | LLM classifier + metric derivation |
| **Reasoning** | `evaluation/reasoning_v2.py` | Commitment normalization |
| **Logging** | `logging_core.py`, `call_logger.py` | Canonical event schema, per-call artifacts |
| **Legacy** | `legacy/` (14 modules with shims) | V1 pipeline, preserved but isolated |

### Key Design Constraints

From `CLAUDE.md` (project rules):
- ONE execution path. No parallel pipelines. Config-parameterized variation only.
- No duplicate logic across files.
- No silent failures. Log or raise every exception.
- All experimental parameters from YAML config. Zero hardcoded values.
- No threads. Single-process serial execution.
- Max 50 lines per function. Max 300 lines per file.
- Evaluation must be independent of generation (no measurement-intervention blur).

---

## 8. Risks and Uncertainties

### Measurement Risks

**Classifier reliability**: The LLM classifier that scores reasoning dimensions has been flagged as potentially unreliable (33% accuracy on known-good reasoning, brevity bias). All LEG rate numbers depend on this classifier. The pass rate is trustworthy (deterministic test oracle), but the decomposition into "correct reasoning + wrong code" vs "wrong reasoning + wrong code" carries classifier noise.

**Canonical commitment patterns as answer leakage**: The classifier prompt includes 30 canonical commitment patterns that effectively give the evaluator a reference table of correct fixes. This means the classifier is not evaluating reasoning quality in a vacuum — it's pattern-matching against known-correct answers. This inflates apparent "mechanism_correct" rates and may undercount genuinely novel correct reasoning that doesn't match canonical patterns.

**Reconstruction confounds**: 6 of the 25 apparent LEG effects in the canonical analysis were reconstruction artifacts — the LEG format produced more parseable output, not better reasoning. The reconstruction-conditioned analysis separates these, but headline numbers without this conditioning are misleading.

### Benchmark Risks

**Case coverage**: 58 cases across 28 families is a meaningful benchmark but not exhaustive. Results may not generalize to bug types not represented (e.g., concurrency bugs, security vulnerabilities, performance issues).

**Task framing**: Cases use refactoring tasks ("Refactor this module for clarity") rather than explicit bug-fix tasks. This is by design (it tests whether the model discovers the bug), but means results may differ under explicit bug-fix framing.

**Difficulty skew**: 26 of 58 cases are difficulty C (cross-boundary). This weights the benchmark toward harder cases where LEG effects are most likely, potentially overstating LEG prevalence relative to real-world bug distributions.

### System Risks

**Three LEG formulas**: The codebase has three different LEG computations that can disagree: `LEG_v2` (4-dimension gate), legacy `leg` (collapsed boolean), and `leg_candidate` (2-factor). Care is needed to ensure analysis uses the correct formula.

**Blind evaluator is not fully blind**: The "blind" evaluator in `leg_evaluator.py` receives execution error details (error category, message, failed assertions). It's blind to the failure type classification but not to execution outcomes. The v2 classifier is blind to execution results but has canonical patterns.

**Parser-evaluator coupling**: The prompt tells the model what JSON format to produce, and the parser expects that format. If prompt and parser drift independently, reconstruction artifacts contaminate downstream results. This was the root cause of a historical 0% pass rate bug.

---

## 9. Key Takeaways

1. **LEG is real but case-specific.** Models do demonstrate correct reasoning that fails to translate into correct code, but this happens primarily on cross-boundary, multi-step bugs — not uniformly.

2. **Structured reasoning scaffolding has a narrow win condition.** LEG interventions help when the model already understands the bug (high baseline LEG rate) AND has sufficient serialization capability to benefit from structured output. They harm when applied to cases the model already solves easily (serialization overhead destroys simple fixes).

3. **Lean beats full.** The minimal scaffolding (lean LEG) outperforms the verbose version in most head-to-head comparisons. The reasoning benefit comes from the structure, not the verbosity.

4. **Retry dominates single-shot.** Even bare retry (no feedback) substantially outperforms single-shot LEG. Retry with reasoning-only critique has a 9.64:1 help/harm ratio — the best intervention in the benchmark.

5. **Model capability is the primary factor.** After controlling for model, intervention effects are small. The gap between gpt-4.1-nano and gpt-5.4-mini (+32.6pp) dwarfs any intervention effect.

6. **Reconstruction artifacts are a real confound.** Apparent intervention effects can be parsing artifacts. Reconstruction-conditioned analysis is essential for valid conclusions.

7. **Cross-provider effects differ qualitatively.** The same intervention works for OpenAI models but fails for Anthropic models on the same case, suggesting the gap is not a universal reasoning-to-code translation problem but depends on model-specific serialization behaviors.
