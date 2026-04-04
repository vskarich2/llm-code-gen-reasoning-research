# LEG Benchmark Dashboard — Deep Reference Guide

This document is not just a schema description.
It is the **operational manual** for interpreting the dashboard correctly.

If you forget how something works, this should let you reconstruct:
- what the field means
- how it was computed
- what assumptions it encodes
- how to interpret it without fooling yourself

This is especially important because many fields are:
- derived
- lossy summaries
- dependent on upstream failures

---

# 0. CORE MENTAL MODEL (READ THIS FIRST)

Every row in the dashboard represents:

> ONE ATTEMPT in a generation → evaluation pipeline

NOT:
- a case
- a trial
- a retry chain
- an experiment

This distinction is critical.

---

## The true hierarchy

```
Experiment
  → Model
    → Condition
      → Case
        → Trial
          → Attempt (THIS IS THE ROW)
```

If retry is enabled:
- 1 trial → multiple attempts
- each attempt = separate row

---

## The pipeline being measured

Every attempt flows through:

```
Raw Output
  ↓
Parse
  ↓
Reconstruction
  ↓
Execution
  ↓
Reasoning Evaluation
```

Every metric and field is trying to measure:
**where and why this pipeline failed (or succeeded)**

---

# 1. METRICS — WHAT THEY REALLY MEAN

All metrics come from aggregating attempt-level rows.
Defined in `dashboard/metrics_registry.py`.

---

## 1.1 Pass Rate (`pass_rate`)

```
mean(exec_pass)
```

### What it measures
Whether the model produces working code.

### What it does NOT measure
- reasoning quality
- structural correctness beyond what tests catch

### Interpretation
This is your **ground-truth behavioral success metric**.

If this is low:
- the system is failing somewhere upstream
- but you don't yet know where

---

## 1.2 LEG Rate (`leg_rate`)

```
mean(is_leg)
= mean(reasoning_correct AND NOT exec_pass)
```

### What it measures
The core phenomenon:

> The model *understood the bug* but failed to implement the fix

### Why this matters
This is the **reasoning → execution gap**.

### Interpretation
High LEG means:
- reasoning signal exists
- implementation is the bottleneck

Low LEG with low pass rate means the model doesn't even understand the bugs.

---

## 1.3 Lucky Fix Rate (`lucky_fix_rate`)

```
mean(is_lucky_fix)
= mean(NOT reasoning_correct AND exec_pass)
```

### What it measures
The opposite failure:

> Code works, but reasoning is wrong

### Why this matters
This breaks naive evaluation:
- execution success ≠ reasoning correctness

### Interpretation
High lucky fix rate means:
- the model is exploiting heuristics or pattern-matching
- reasoning is unreliable as a signal
- your test suite may not be discriminating enough for some cases

---

## 1.4 Reasoning Rate (`reasoning_rate`)

```
mean(reasoning_correct)
```

### What it measures
The classifier's judgment of reasoning correctness.

### Important caveat
This is:
- NOT ground truth
- NOT execution
- NOT necessarily reliable

The classifier evaluates whether the model's stated reasoning correctly identifies the bug mechanism. It does not evaluate whether the code implements the fix. It is a measurement layer with its own error rate.

### Interpretation
Use this only in combination with execution. The gap between `reasoning_rate` and `pass_rate` is the execution fidelity gap.

---

## 1.5 Count (`count`)

```
len(group)
```

### What it measures
Number of attempts.

### Why it matters
Many metrics become meaningless at low N. Always check count before reading percentages.

---

## 1.6 Score (`mean_score`)

Average execution score (if partial scoring exists).

### Interpretation
More granular than pass/fail. Useful when you want to see if attempts are getting "closer" to passing even when they don't fully pass.

---

## 1.7 Reconstruction Pass Rate (`recon_pass_rate`)

```
mean(recon_pass)
```

### What it measures
Whether parsed outputs become valid code.

### Interpretation
Separates:
- formatting failures (model produced bad JSON)
- structural failures (model produced bad Python)
- true code failures (model produced valid but wrong code)

If recon_pass_rate is much lower than pass_rate, you have a serialization bottleneck.

---

# 2. RETRY METRICS — CHAIN-LEVEL SIGNALS

These operate at the **chain level**, not attempt level.
A chain = all attempts for one `(model, condition, case_id, trial_idx)`.

---

## 2.1 Retry Recovery Rate (`retry_recovery_rate`)

```
recovered / eligible
```

Where:
- eligible = chains where first attempt failed
- recovered = chains where final attempt passed

### What it measures
Whether retry helps — specifically, whether failed first attempts can be recovered.

---

## 2.2 Avg Attempts (`avg_attempts`)

```
mean(max(attempt_idx) + 1)
```

### What it measures
How many attempts chains actually use. Always 1.0 if retry is disabled.

---

## 2.3 Improved % (`pct_improved`)

Fail → Pass transitions across multi-attempt chains.

### Interpretation
Retry effectiveness. If this is 0%, retry is doing nothing useful.

---

## 2.4 Degraded % (`pct_degraded`)

Pass → Fail transitions across multi-attempt chains.

### Interpretation
Retry harm. If Degr% > Impr%, retries are actively harmful — the model "unlearns" correct fixes.

---

# 3. THE THREE-AXIS MODEL (S × E × R)

This is the conceptual core of the evaluation system.
Implemented in `dashboard/data/evaluation_fields.py:add_three_axis_fields()`.

---

## Axes

### S — Serialization
Did the output become executable code? Combines parse success, reconstruction success, and execution eligibility.

Computed as:
```python
serialization_success = parse_ok & recon_ok & recon_v2 & eligible
```

### E — Execution
Did the code pass tests?
```python
execution_success = exec_pass
```

### R — Reasoning
Did the model correctly identify the bug mechanism?
```python
reasoning_sufficient = mechanism_correct & commitments_valid
```

Where `mechanism_correct = mechanism_dim == "CORRECT"` and `commitments_valid = satisfied_dim IN ("CORRECT", "PARTIAL")`.

---

## 5-class taxonomy

| Class | S | E | R | Meaning |
|-------|---|---|---|---------|
| Interpretable Success | 1 | 1 | 1 | Everything works |
| Unsupported Success | 1 | 1 | 0 | Lucky fix |
| LEG | 1 | 0 | 1 | Reasoning OK, execution fails |
| Reasoning Failure | 1 | 0 | 0 | Both fail |
| Serialization Failure | 0 | - | - | Pipeline never reached execution |

---

## Key insight

This decomposition lets you distinguish:
- formatting failures (S=0)
- reasoning failures (R=0)
- execution-only failures (S=1, R=1, E=0) — this is LEG
- spurious successes (S=1, R=0, E=1) — this is lucky fix

Without this decomposition, all you have is pass/fail.

---

## LEG Subtypes

- **Congruent LEG**: model's fix strategy aligns with the correct approach (alignment_dim = CORRECT), but the implementation diverges. The model "knew what to do" at a high level but the code didn't match.
- **Incongruent LEG**: model's reasoning and code are internally consistent (alignment_dim != CORRECT), but both miss the actual bug mechanism.

---

# 4. FAILURE DECOMPOSITION — WHERE THE SYSTEM BREAKS

Pipeline stages, evaluated in order:

1. **Parse** — can the raw output be parsed into file-dict JSON?
2. **Reconstruction** — does the parsed output pass AST validation, sentinel checks, file count matching?
3. **Execution** — do the reconstructed files pass the test suite?
4. **Reasoning** — does the classifier judge reasoning as correct?

---

## Critical principle

Each attempt is assigned a **terminal stage**:

> The FIRST stage where it fails

This is computed in `dashboard/data/transforms.py:add_failure_stage_columns()`:
```python
stage = "success"
if parse_failure: stage = "parse_failure"
elif reconstruction_failure: stage = "reconstruction_failure"
elif execution_failure: stage = "execution_failure"
```

---

## Why this matters

Without this:
- failures are ambiguous
- metrics mix causes
- you can't tell if the model wrote bad code or if the pipeline couldn't process good code

With this:
- you get causal localization
- you can target fixes at the right stage

---

## Funnel interpretation

```
all_attempts
  → execution_eligible
    → reconstruction_ok
      → execution_pass
        → reasoning_correct
```

Each drop = loss at a stage. A steep drop at reconstruction means serialization is the bottleneck, not model capability.

---

# 5. CASE EXPLORER — TEMPORAL ANALYSIS

This shows **chains over time**.

---

## What to look for

- does retry improve execution?
- does reasoning improve or degrade?
- do they diverge (reasoning improves but code regresses)?
- does the model get lucky on a later attempt?

---

## Key insight

You often see:
- reasoning improves but code regresses
- code improves but reasoning collapses
- first attempt had the best reasoning, last attempt passed for the wrong reason

This is important for diagnosing alignment issues and understanding whether retry is actually helping for the right reasons.

---

# 6. PIPELINE TRACE — FORENSIC VIEW

This is your debugger.

---

## Stages

### Prompt
What the model saw. Inspect this when you suspect prompt issues.

### Raw Response
What the model produced. Compare against the prompt to see if the model followed instructions.

### Parse
Did the response have valid structure? Check `strict_parse_valid`, `recovery_parse_valid`, `strict_structurally_valid`, `recovery_structurally_valid`, `execution_eligible`.

### Reconstruction
Did parsed files become valid code? Check `reconstruction_mode`, `files_changed`/`files_missing`/`files_extra`, `syntax_errors`, `recovery_types`, `normalization_log`.

### Execution
Did tests pass? Check `exec_pass`, `exec_category`, `exec_reasons`, `execution_trace`, `functions_detected`/`functions_called`, `merge_conflicts`.

### Classification
Did reasoning align? Check the parsed classifier response: `mechanism_identified`, `commitments_extracted`/`satisfied`, `reasoning_code_alignment`, `failure_type`, `confidence`, `counterfactual`, `evidence`, `judgment`.

---

## How to use it

When something looks wrong:
**always go here first**

---

# 7. AST / STRUCTURAL SIGNALS

These measure:

> Did the model preserve required structure?

Implemented in `dashboard/data/evaluation_fields.py:add_ast_fields()`.

---

## Status meanings

- **correct** → all required top-level definitions present with correct signatures
- **incorrect** → one or more required definitions missing or structurally wrong
- **unknown** → couldn't determine (function present but rule didn't match cleanly)
- **not_available** → no AST data (reconstruction failed, code empty, or multi-file case with missing target)
- **not_measurable** → case has no AST verification criteria (in `NOT_AST_MEASURABLE` set)

---

## Why this matters

Execution tests don't always detect structural errors. A model can produce code with the wrong function signature that still passes some tests. AST verification catches these structural mismatches independently.

High AST-correct rate in LEG events means the gap is in execution semantics (logic errors), not code structure (missing functions). That's a stronger form of LEG.

---

# 8. FAMILY BREAKDOWN

Groups by bug family.

---

## What to look for

- which bug types are hardest (lowest Pass%)
- where LEG is concentrated (model understands but can't fix)
- whether lucky fixes cluster in specific families (tests aren't discriminating enough there)

---

## Interpretation

High LEG in a family = the model understands that bug type but cannot implement fixes. This is a genuine capability gap worth investigating in Pipeline Trace.

Low LEG + low Pass% = the model doesn't even understand the bugs in this family. Different problem.

---

# 9. MODEL × CONDITION

This is your **ablation core view**.

---

## Use this to answer:

- does a prompt variant help?
- which model is better within a condition?
- is the gap between models consistent across conditions?

---

## Interpretation

Compare conditions within a model to measure prompt effectiveness. Compare models within a condition to measure model capability. If a prompt helps one model but not another, the effect is model-dependent.

---

# 10. RETRY ANALYSIS

Key question:

> does retry help or hurt?

---

## Interpretation patterns

| Pattern | Meaning |
|---------|---------|
| High Recov% + Low Degr% | Retry is clearly helpful |
| High Recov% + High Degr% | Retry is volatile — helps some, hurts others |
| Low Recov% + Low Degr% | Retry is inert — not doing much |
| Low Recov% + High Degr% | Retry is actively harmful |
| High AvgAtt | Chains are long — potential instability |

---

# 11. DIFFICULTY ANALYSIS

---

## Expected behavior

- Pass% ↓ as difficulty ↑
- LEG% may ↑ (models understand but can't execute harder tasks)
- Lucky% may ↓ (harder cases are harder to accidentally pass)

---

## Interpretation

If LEG increases with difficulty: the execution gap widens for harder bugs. Models understand harder bugs but can't implement fixes — this is the core finding.

If R% drops with difficulty: models can't even reason about harder bugs. Different conclusion.

---

# 12. ORACLE

Human-grounded reasoning evaluation.

---

## Important

Oracle ≠ truth.
Oracle = high-quality proxy.

The oracle evaluates whether the model's reasoning correctly identifies the **bug mechanism**, not whether the code is correct. A model can have CORRECT oracle verdict and still fail execution (this is LEG).

---

## Oracle verdicts

- **CORRECT**: human agrees the model correctly identified the bug mechanism
- **INCORRECT**: human disagrees — the model misidentified or missed the mechanism
- **UNJUDGABLE**: human cannot determine (e.g., reasoning is too vague or generic)

---

## Oracle join semantics

Oracle labels are joined at the trial level using `(case_id, model, condition, trial_idx)`, NOT at the attempt level. If a retry chain has 3 attempts, all 3 share the same oracle label. Don't overinterpret oracle values as attempt-specific.

---

# 13. FIELD INTROSPECTION

Schema debugging tool.

---

## What to look for

- **high null%** → field not logged for some events, or conditional (e.g., oracle_verdict only exists for labeled rows)
- **constant columns (unique=1)** → field doesn't vary in loaded data, may be a configuration artifact
- **weird dtype mismatches** → field parsed as wrong type

---

## Why it matters

Bad data → invalid conclusions. Always check field introspection when numbers look suspicious.

---

# 14. IDENTITY AND GROUPING FIELDS

### `_experiment`
The experiment directory name. Preserves provenance when multiple experiments are loaded.

### `model`
The generator model. Primary grouping field. When something is strange, check if it's model-specific first.

### `condition`
The experimental condition (prompt variant, retry config). The other primary grouping field.

### `case_id`
The benchmark case identifier. Links results to a specific bug task.

### `trial_idx`
Repeated sampling number for the same (model, condition, case_id).

### `attempt_idx`
Which retry step. Attempt 0 = initial generation; higher = retries.

### `chain_id`
Retry-chain identifier. Computed as `model|condition|case_id|trial_idx`. This is how the dashboard counts chains (not just attempts).

### `family`
Bug family. Used in family-level breakdowns. Often more informative than case_id for understanding systematic failure modes.

### `difficulty`
Benchmark difficulty bucket.

---

# 15. EXECUTION FIELDS

### `exec_pass`
The most important "hard" outcome field. Boolean pass/fail of test execution. This is your ground truth.

### `exec_category`
Categorical execution outcome. More specific than exec_pass — distinguishes clean test failure from crash, malformed code, invalid reconstruction, etc.

### `exec_reasons`
List of execution or test-failure reasons. Human-readable explanation of what went wrong. Essential for Pipeline Trace debugging.

### `execution_trace`
Trace of execution events. Deeper debugging instrumentation showing function calls and execution progress.

### `functions_detected`
Functions discovered in reconstructed code.

### `functions_called`
Functions actually invoked during execution. Compare with `functions_detected` to check if the test exercised the right code.

### `merge_conflicts`
Conflicts during code artifact merging. Debugging signal when execution results make no sense.

---

# 16. PARSING FIELDS

### `parse_status`
High-level parse outcome string.

### `strict_parse_valid`
Whether the response passed strict parsing (strongest compliance).

### `recovery_parse_valid`
Whether the response could be parsed after recovery logic. Matters because some rows fail strict but are still recoverable.

### `strict_structurally_valid` / `recovery_structurally_valid`
Whether the parsed object is structurally valid under strict/recovery paths.

### `execution_eligible`
Key gate field. If false, the attempt never reached a valid execution-ready artifact. Downstream execution fields become meaningless.

### Interpretation rule
If parsing fails, downstream fields may be placeholders or partial diagnostics. Do not read failed rows as "bad code" when the real issue is "bad output format."

---

# 17. RECONSTRUCTION FIELDS

### `reconstruction_status` / `recon_status`
High-level reconstruction result. Two fields exist because of schema evolution — the dashboard checks both when computing reconstruction failure.

### `reconstruction_mode`
How reconstruction was performed ("strict" or "salvaged").

### `files_changed` / `files_missing` / `files_extra`
File-level reconstruction signals. `files_missing` is a strong structural error signal. `files_extra` may or may not be harmful.

### `syntax_errors`
Per-file syntax errors. Often explain execution failure more directly than `exec_category`.

### `structural_errors`
Higher-level structure problems beyond plain syntax.

### `recovery_types`
List of specific recovery transformations applied. Critical for distinguishing:
- natural model compliance (no recovery needed)
- parser/reconstructor rescue (fence_stripped, file_value_prefix_stripped, leading_whitespace_stripped, missing_files_auto_filled, newlines_unescaped)
- artifact salvage

If a row passed only after recovery, temper how strongly you interpret it as a clean model success.

### `recovery_used` / `recovery_applied`
Whether any recovery logic was used/applied.

### `content_normalized`
Whether normalization steps were applied to the content.

### `divergence_detected`
Whether a divergence between strict and recovery paths was detected.

### `normalization_log`
Record of what normalization steps were applied. More informative than the final status string when debugging reconstruction oddities.

---

# 18. CLASSIFIER / REASONING FIELDS

These fields are **evaluation outputs**, not execution truth.

### `mechanism_dim`
Primary reasoning-mechanism judgment. Conceptually: did the evaluator think the model correctly identified the bug mechanism?

The dashboard derives `reasoning_failure` from this: `mechanism_dim != "CORRECT"` → reasoning_failure = True.

### `commitments_dim` / `satisfied_dim`
Did the model articulate valid commitments, and were they satisfied?

### `alignment_dim`
Did the code appear aligned with stated reasoning?

### `mechanism_label`
Categorical mechanism classification (failure_type).

### `confidence`
Classifier's reported confidence level.

### Parsed classifier subfields (Pipeline Trace only)
`mechanism_identified`, `commitments_extracted`, `commitments_satisfied`, `reasoning_code_alignment`, `failure_type`, `confidence`, `counterfactual`, `evidence`, `judgment`

### Important caution
- Classifier fields are **measurement fields**, not execution truth
- A classifier disagreement with execution does not automatically mean the classifier is wrong
- But it also does not override execution
- Execution is still the hard behavioral outcome

---

# 19. DERIVED FAILURE-STAGE FIELDS

These are NOT loaded from WAL directly. They are added by `add_failure_stage_columns(df)` in `dashboard/data/transforms.py`.

### `parse_failure`
Derived when `execution_eligible` is false AND `parse_status` contains "parse". This is a pragmatic signal that the failure was probably in parsing/output-format.

### `reconstruction_failure`
Derived by inspecting `reconstruction_status` and `recon_status` for failure-like strings (fail, invalid, error). Broad catch-all for "parsed output did not become valid executable artifacts."

### `execution_failure`
Derived as `~exec_pass`. Intentionally blunt — did the attempt fail execution?

### `reasoning_failure`
Derived as `mechanism_dim != "CORRECT"`. The dashboard's standardized notion of reasoning-side failure. Anchored specifically to the mechanism judgment.

### `stage_terminal`
Single categorical summary of where the attempt "ended":
1. default = `success`
2. if parse_failure → `parse_failure`
3. elif reconstruction_failure → `reconstruction_failure`
4. elif execution_failure → `execution_failure`

This powers the terminal-stage views in Failure Decomposition.

### Interpretation caution
`stage_terminal` is a dashboard summary field designed for decomposition and visualization. When a result actually matters, also inspect the underlying raw fields.

---

# 20. OUTCOME-CATEGORY FIELDS

### `is_leg`
```python
reasoning_correct AND NOT exec_pass
```
The model reasoned correctly about the bug but failed to produce working code. This is the core phenomenon the benchmark measures.

### `is_lucky_fix`
```python
NOT reasoning_correct AND exec_pass
```
Code works but reasoning is wrong. Breaks the assumption that correct code implies correct reasoning.

### `outcome_class`
The 5-class S×E×R classification: `interpretable_success`, `unsupported_success`, `LEG`, `reasoning_failure`, `serialization_failure`.

### `LEG_subtype`
`congruent` (alignment OK, implementation diverges) or `incongruent` (reasoning and code are consistent but both miss the actual mechanism).

---

# 21. ARTIFACT-PATH FIELDS

### `prompt_path`
Path to the prompt/response artifact for the generator attempt. The dashboard reads this to show raw prompts and responses in Pipeline Trace.

### `classify_path`
Path to the classifier artifact. Shows classifier prompt, response, and parsed subfields.

### `_extracted_code`
The code extracted from the model response. Shows what the execution system actually saw after extraction. One of the most useful fields in Pipeline Trace.

---

# 22. HOW TO READ THE DASHBOARD WITHOUT FOOLING YOURSELF

### Rule 1: Execution is the hard outcome
If `exec_pass` is false, the attempt did not solve the benchmark, no matter how elegant the reasoning looked.

### Rule 2: Classifier fields explain failures; they do not erase them
If the classifier says the mechanism is correct but execution failed, that is a LEG-style discrepancy, not a success.

### Rule 3: Parse and reconstruction failures are pipeline failures, not necessarily reasoning failures
A model can fail because it emitted malformed JSON or malformed file content. That is different from misunderstanding the bug itself.

### Rule 4: Derived fields are convenience summaries
Fields like `parse_failure`, `reconstruction_failure`, and `stage_terminal` are there to help you navigate. When a result matters, inspect the underlying raw fields too.

### Rule 5: Retry chains should be read longitudinally
Do not only look at the last attempt. Sometimes attempt 0 had the best reasoning, attempt 1 had better structure, and attempt 2 passed for the wrong reason.

### Rule 6: Oracle labels are annotations, not runtime-native facts
They are useful and often important, but they are joined after the fact at the trial level, not the attempt level.

### Rule 7: Recovery-assisted rows are not clean successes
If `recovery_types` is non-empty, the pipeline had to fix the model's output. The model didn't cleanly comply with the output format.

---

# 23. PRACTICAL "WHAT SHOULD I INSPECT FIRST?" GUIDE

### If pass rate is low for a model/condition
1. Go to Failure Decomposition
2. Check `stage_terminal` — is the bottleneck parse, reconstruction, or execution?
3. If parse-heavy: the model can't produce valid JSON
4. If reconstruction-heavy: valid JSON but bad Python (check syntax_errors, recovery_types)
5. If execution-heavy: valid code but wrong logic (this is the interesting case)

### If a row is marked LEG
1. Check `exec_pass` (must be false)
2. Check `mechanism_dim` (must be CORRECT)
3. Read the raw prompt/response in Pipeline Trace
4. Read the extracted code
5. Ask: did the model really know the bug, or did the classifier over-credit it?

### If a row is a lucky fix
1. Check classifier fields — what did the classifier think was wrong?
2. Read the extracted code — is the fix correct but under-explained?
3. Or did the model guess a plausible patch without understanding the causal mechanism?

### If reconstruction looks suspicious
1. Check `reconstruction_status` / `recon_status`
2. Check `recovery_types` — was recovery needed?
3. Check `normalization_log` — what transformations were applied?
4. Check `syntax_errors`
5. Check `files_missing` / `files_extra`

### If the dashboard itself feels inconsistent
1. Go to Field Introspection
2. Check for high null% columns
3. Check for constant columns (unique=1)
4. Check whether your interpretation relies on a derived field rather than a source field

---

# 24. SHORT GLOSSARY OF THE MOST IMPORTANT FIELDS

If you only remember ten things, remember these:

| Field | What it answers |
|-------|----------------|
| `exec_pass` | Did the code actually pass the test? |
| `exec_category` | What kind of execution outcome? |
| `parse_status` | Did the response parse cleanly? |
| `reconstruction_status` / `recon_status` | Did parsed output become valid code? |
| `execution_eligible` | Was the attempt even valid enough to execute? |
| `mechanism_dim` | Did the evaluator think the bug mechanism was correctly identified? |
| `is_leg` | Failed execution despite apparently correct mechanism understanding |
| `is_lucky_fix` | Passed execution without trustworthy reasoning support |
| `stage_terminal` | Where the dashboard thinks the attempt "ended" |
| `prompt_path` / `classify_path` | Where to look when you need raw evidence |

---

# 25. ONE-SENTENCE SUMMARY

The cleanest way to think about the dashboard is:

**It is an attempt-level forensic viewer over a code-generation pipeline, with derived stage-failure summaries layered on top so you can tell whether a result failed because the model reasoned badly, formatted badly, reconstructed badly, or simply wrote code that did not work.**
