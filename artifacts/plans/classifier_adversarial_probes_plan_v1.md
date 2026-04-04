# Classifier Adversarial Probe Design — Plan v1

**Date**: 2026-03-31
**Goal**: Calibrate the classifier's false negative rate by feeding it deliberately wrong reasoning and measuring how often it still returns mechanism_identified=CORRECT.

## Problem Statement

The classifier assigns mc=True to 99.5% of classified evaluations. We cannot distinguish:
- **Hypothesis A**: LLMs genuinely identify the correct mechanism 99.5% of the time
- **Hypothesis B**: The classifier cannot detect wrong mechanisms

Without adversarial calibration, the LEG metric's interpretive power is unknown.

## Design

### Architecture

A script (`scripts/run_classifier_probes.py`) that:
1. Loads real cases from cases_v2.json
2. Reads actual buggy code files
3. Injects **fabricated** root_cause + fix_strategy + code (adversarial inputs)
4. Builds classifier vars via `build_classifier_v2_vars` (or equivalent manual construction)
5. Renders the `classify_reasoning_v2` template via `assembly_engine.build`
6. Calls gpt-5-mini (the classifier model)
7. Parses output via `parse_classifier_v2_output`
8. Reports per-probe dimensions

Each probe runs 5 trials (temperature=0, but provider-side variance exists) to measure consistency.

### Probe Types (5 types, 3 cases each = 15 probes × 5 trials = 75 classifier calls)

#### Type A: WRONG MECHANISM, COHERENT CODE
Fabricate a root cause that is factually wrong about the code but internally consistent. Produce code that implements the wrong fix.

**Expected correct result**: mechanism_identified = WRONG
**What mc=CORRECT here means**: Classifier cannot distinguish wrong-but-coherent reasoning from correct reasoning.

Cases:
- **stale_cache_a**: Real bug = `update_product()` doesn't invalidate `_cache`. Adversarial = "get_product reads from _db instead of _cache when product exists" (wrong direction). Code: add `if pid in _db: return _db[pid]` to get_product.
- **config_shadowing**: Real bug = `run_background_job()` calls `get_defaults()` instead of `get_config()`. Adversarial = "create_config performs a shallow copy instead of deep copy" (wrong function, wrong bug). Code: change `create_config` to use `copy.deepcopy`.
- **invariant_partial_fail**: Real bug = mixing transfer logic with observability. Adversarial = "execute_transfer doesn't validate negative balances before debit" (wrong mechanism). Code: add `if sender.balance < amount: raise ValueError`.

#### Type B: RIGHT KEYWORDS, WRONG CAUSAL CHAIN
Use the correct bug-type label but describe a different causal mechanism.

**Expected correct result**: mechanism_identified = WRONG or PARTIAL
**What mc=CORRECT here means**: Classifier is keyword-matching, not evaluating causal chains.

Cases:
- **stale_cache_a**: Root cause mentions "stale cache" but claims the bug is "`_cache` uses a TTL that's too long" (no TTL exists in the code). Code: add a TTL mechanism.
- **lost_update**: Root cause mentions "shared state" but claims the bug is "the counter's initial value is wrong" (wrong cause for lost update). Code: change initial `_value` from 0 to 1.
- **alias_config_c**: Root cause mentions "aliasing" but claims "DEFAULTS is imported by value, not reference" (wrong; Python dicts are always by reference). Code: wrap DEFAULTS access in `dict()`.

#### Type C: VAGUE MECHANISM (no code anchors)
Describe the bug generically without specific function names, line numbers, or variable references.

**Expected correct result**: mechanism_identified = PARTIAL or WRONG
**What mc=CORRECT here means**: Classifier doesn't enforce the "concrete code anchor" requirement from its own rubric.

Cases:
- **stale_cache_a**: "There is a data consistency issue where stale values are returned after modification." Fix: "Update the data flow to ensure consistency."
- **config_shadowing**: "The configuration system has a bug where some functions read wrong values." Fix: "Fix the functions to read correct values."
- **invariant_partial_fail**: "The transfer has a state management issue." Fix: "Refactor to separate concerns."

Code for all: the original buggy code (no changes).

#### Type D: CORRECT MECHANISM (positive control)
The actual correct root cause, correct fix strategy, and reference fix code. These should get mc=CORRECT.

**Expected correct result**: mechanism_identified = CORRECT
**Purpose**: Confirms the classifier works on correct inputs. If these fail, the classifier is broken in both directions.

Cases:
- **stale_cache_a**: Real root cause + reference fix from case metadata
- **config_shadowing**: Real root cause + reference fix
- **invariant_partial_fail**: Real root cause + reference fix

#### Type E: CORRECT SYMPTOM, WRONG CAUSE
Describe the observable symptom accurately but attribute it to the wrong cause.

**Expected correct result**: mechanism_identified = PARTIAL or WRONG
**What mc=CORRECT here means**: Classifier can't distinguish symptom description from causal explanation.

Cases:
- **stale_cache_a**: "After calling update_product, get_product returns old data" (symptom). Adversarial cause: "because _db.update creates a new dict entry instead of modifying in place" (wrong). Code: change _db update to re-assign.
- **config_shadowing**: "run_background_job uses wrong timeout" (symptom). Adversarial cause: "because the DEFAULTS dict is mutated by create_config" (wrong — create_config doesn't mutate DEFAULTS). Code: add DEFAULTS copy in create_config.
- **lost_update**: "Counter reaches wrong final value after interleaving" (symptom). Adversarial cause: "because apply_steps doesn't lock the counter" (wrong — the bug is in make_increment_steps, not apply_steps). Code: add a lock to apply_steps.

### Scoring

For each probe:
- Record mechanism_identified, all 4 dimensions, confidence
- Record whether the classifier's judgment text correctly identified the fabricated reasoning as wrong

Aggregate:
- **False negative rate** = % of adversarial probes (Types A, B, C, E) that get mechanism_identified=CORRECT
- **True positive rate** = % of control probes (Type D) that get mechanism_identified=CORRECT
- **Sensitivity by probe type** = per-type false negative rate

### Interpretation Guide

| False Negative Rate | Interpretation |
|-------------------|---------------|
| 0-10% | Classifier is calibrated; 99.5% mc=True rate likely reflects genuine LLM capability |
| 10-30% | Classifier has moderate blindness; some mc=True evals have wrong reasoning |
| 30-50% | Classifier is significantly compromised; LEG rate is substantially inflated |
| 50%+ | Classifier has near-zero discriminative power; LEG metric is uninterpretable |

## Files

- **Created**: `scripts/run_classifier_probes.py`
- **Read only**: `evaluator_v2.py`, `metrics_v2.py`, `assembly_engine.py`, `cases_v2.json`, `prompts/components/classify_reasoning_v2.j2`
- **No modifications** to any existing file

## Constraints

- Uses existing `call_model` from `llm.py` for classifier calls
- Uses existing `parse_classifier_v2_output` for parsing
- Uses existing `assembly_engine.build` for template rendering
- Temperature=0, model=gpt-5-mini (same as production)
- Each probe runs 5 trials for consistency measurement
- Total API cost: ~75 calls × ~8K tokens input ≈ ~600K input tokens (~$0.60 at mini pricing)

## Risks

- If the classifier model (gpt-5-mini) is rate-limited, we may need to throttle
- Adversarial probes are hand-crafted, so they may not represent the distribution of actual LLM reasoning errors
- 5 trials per probe may be insufficient for precise rate estimates; consider increasing if initial results are ambiguous
