# Reasoning Evaluator System Audit

**Date**: 2026-04-02
**Auditor**: Claude Opus 4.6 (automated, code-verified)
**Repo**: `cs372research_2/t3_code_generation`
**Commit**: `cc9d1cf2` (working tree, uncommitted changes present)

---

## 1. Executive Summary

This repo implements a **reasoning evaluation pipeline** for measuring the Latent Execution Gap (LEG) — the phenomenon where an LLM demonstrates correct reasoning about a bug but produces code that fails tests. The system has **two generations** of evaluator infrastructure: a legacy v1 path (`evaluator.py`, `reasoning.py`) and a production v2 path (`evaluator_v2.py`, `metrics_v2.py`, `execution_v2.py`). Both are live in the codebase.

The evaluator system is **not** a single module. It is a distributed pipeline spanning prompt assembly, LLM-based classification, deterministic execution, metric derivation, and logging. The "evaluator" is really three things:

1. **Deterministic execution oracle** — subprocess-based test execution (`exec_canonical.py`) that produces pass/fail ground truth.
2. **LLM-based reasoning classifier** — a second LLM call (the "evaluator model") that scores the generator model's reasoning along 4-5 dimensions.
3. **Metric derivation layer** — pure functions that combine execution results and classifier dimensions into categories (LEG, lucky_fix, true_success, true_failure).

Additionally, there is a **LEG evaluator** (`leg_evaluator.py`) implementing blind/conditioned CRIT-lite evaluation, and an **oracle reasoning evaluator** (`evaluators/reasoning_truth.py`) that uses ground truth for validation. These are analysis-only — they never feed back into the retry loop.

Key findings:
- The v2 classifier is **not blind** in the RAudit sense. It receives the model's code and reasoning simultaneously.
- The blind/conditioned evaluator in `leg_evaluator.py` is **genuinely blind** but is only used in the legacy retry harness, not in the v2 production path.
- There are **three different LEG formulas** in the codebase that can produce different results.
- A **NameError bug** in `evaluator.py:172` would crash the v1 classifier on every successful classification.
- The v2 classifier prompt contains **canonical commitment patterns per bug family**, which effectively leaks the answer space to the evaluator.

---

## 2. Scope and System Boundary

### What counts as the "reasoning evaluator system"

The system boundary encompasses everything between "model raw response received" and "final labeled result dict emitted." Specifically:

| Inside the boundary | Outside the boundary |
|---|---|
| Response parsing (`parser_v2.py`, `parse.py`) | Prompt generation for the *generator* model |
| File reconstruction (`reconstructor.py`) | The generator LLM call itself |
| Deterministic execution (`exec_canonical.py`, `exec_eval.py`) | Config loading and case selection |
| Reasoning normalization (`reasoning_v2.py`) | Run orchestration (`runner.py`) |
| Classifier prompt assembly (`classify_reasoning_v2.j2`, `classify_reasoning.j2`) | Retry loop control logic |
| Classifier LLM call (via `llm.py`) | Nudge/intervention prompt construction |
| Classifier output parsing (`evaluator_v2.py`, `reasoning.py`) | Live dashboard rendering |
| Metric derivation (`metrics_v2.py`, `reasoning.py`) | |
| LEG/blind evaluator (`leg_evaluator.py`) | |
| Oracle evaluator (`evaluators/reasoning_truth.py`) | |
| Failure classifier heuristic (`failure_classifier.py`) | |

### Measurement vs intervention

- **Measurement only**: The classifier, LEG evaluator, oracle evaluator, and metric derivation are purely observational. They score what the generator produced but never feed information back to the generator.
- **Intervention**: The critique mismatch evaluator (`critique_mismatch_v2.j2`) and retry feedback in `retry_v2.py` DO feed back into generation. These are inside the retry loop and influence subsequent attempts.

**Verified**: In `execution_v2.py`, the classifier runs at Stage 6 *after* execution at Stage 5. There is no path from classifier output back to the generator. In `retry_v2.py`, mismatch critiques are generated via separate prompts (not the classifier) and fed into retry attempts — the classifier runs only once on the final best result.

---

## 3. File Map

### A. Core Evaluator Implementation

| File | Purpose | Lines |
|---|---|---|
| `evaluator.py` | V1 evaluation dispatcher: execution + LLM classification + category + SCM evidence | 646 |
| `evaluator_v2.py` | V2 classifier invocation, output parsing, result assembly | 319 |
| `leg_evaluator.py` | CRIT-lite blind/conditioned evaluator (analysis-only) | 197 |
| `evaluators/reasoning_truth.py` | Oracle ground-truth reasoning validator | 98 |
| `disagreement_classifier.py` | Deterministic dual-execution disagreement classifier | 339 |
| `failure_classifier.py` | Heuristic failure type classifier (no LLM) | 157 |

### B. Prompt Assembly

| File | Purpose |
|---|---|
| `assembly_engine.py` | Single prompt construction path, enforcement invariant |
| `prompt_registry.py` | Loads .j2 templates and nudge text, computes content hashes |
| `prompts/prompt_manifest.yaml` | Maps condition -> component list + nudge resolution |
| `prompts/components/classify_reasoning_v2.j2` | V2 classifier prompt (4 dimensions + failure type) |
| `prompts/components/classify_reasoning.j2` | V1 classifier prompt (5 dimensions + failure type) |
| `prompts/components/evaluate_reasoning_blind.j2` | LEG blind evaluator prompt |
| `prompts/components/evaluate_reasoning_conditioned.j2` | LEG conditioned evaluator prompt |
| `prompts/components/critique_mismatch_v2.j2` | Mismatch critique prompt (retry feedback) |
| `evaluators/reasoning_truth_prompt.j2` | Oracle reasoning evaluator prompt |

### C. Orchestration

| File | Purpose |
|---|---|
| `runner.py` | Entry point, dispatches to v2 or retry paths |
| `execution_v2.py` | V2 9-stage pipeline (production path) |
| `execution.py` | V1 execution + evaluation pipeline |
| `retry_v2.py` | V2 retry harness with multi-attempt execution |
| `retry_harness.py` | Legacy retry harness (1706 lines) |

### D. Parsing / Contracts

| File | Purpose |
|---|---|
| `parser_v2.py` | Three-tier v2 parser (execution/format/recovery) |
| `parse.py` | V1 eight-tier cascade parser |
| `contracts_v2.py` | V2 field schemas and validation |
| `contract.py` | CGE contract schema parsing |
| `reconstructor.py` | File-level reconstruction with 5-gate validation |
| `reasoning.py` | V1 reasoning extraction, validation, classifier output parsing |
| `reasoning_v2.py` | V2 reasoning normalization and artifact construction |

### E. Logging / Artifacts

| File | Purpose |
|---|---|
| `logging_core.py` | Centralized logging with canonical event schema v7 |
| `call_logger.py` | Per-LLM-call logging (prompt + response + metadata) |
| `load_logs.py` | Event log loading and LEG rate computation |

### F. Analysis / Metrics

| File | Purpose |
|---|---|
| `metrics_v2.py` | V2 signal derivation (mechanism_correct, commitments_valid, alignment_positive) |
| `v2_metrics.py` | V2 aggregation dashboard |
| `aggregate.py` | Cross-run aggregation |
| `join_reasoning_execution.py` | Joins reasoning signals with execution results |
| `score_execution.py` | Adds leg_candidate and lucky_fix_candidate flags |
| `live_metrics.py` | Real-time dashboard with LEG adjustment |
| `leg_reduction.py` | LEG intervention response parsing |

---

## 4. End-to-End Execution Paths

### 4.1 V2 Baseline Path (Production)

**Verified** from `execution_v2.py:26-242`.

```
runner.main()
  → runner.run_ablation_mode()
    → runner.run_all()
      → runner._run_one()
        → runner._run_one_inner()
          → execution_v2.run_v2(case, model, condition="baseline_v2", logger, eid)
```

Inside `run_v2()`, 9 stages:

```
STAGE 1: Build prompt
  assembly_engine.build(["task_and_code", "output_instruction_v3"], variables)
  → Renders task description + code files + JSON output schema instruction
  → Returns prompt string

STAGE 2: Call generator model
  llm.call_model(prompt, model=model, raw=True, logger=logger, ...)
  → Returns ModelCallResult(response=str, event_id=int)

STAGE 3: Parse (three-tier)
  parser_v2.parse_v2_execution(raw_response, condition)  ← drives pipeline
  parser_v2.parse_v2_format(raw_response, condition)     ← diagnostic only
  parser_v2.parse_v2_recovery(raw_response, condition)   ← diagnostic only
  → Returns ParsedGenerationV2 with full_json, files_dict, parse_status

STAGE 4: Normalize reasoning
  reasoning_v2.normalize_generation_v2(parsed_gen, case, condition)
  → Returns NormalizedReasoningArtifactV2 with raw/normalized root_cause,
    fix_strategy, risk_check, code_commitments, commitments_source

STAGE 5: Reconstruct + Execute
  reconstructor.reconstruct_strict(manifest_paths, manifest_files, parsed_gen.files_dict)
  exec_canonical.exec_canonical(case, parsed_gen, recon, config, logger, attempt=0)
  → Subprocess execution: writes files to temp dir, runs test harness
  → Returns dict with pass, score, category (12 possible)

STAGE 6: Classify reasoning (LLM evaluator call)
  evaluator_v2.build_classifier_v2_vars(artifact, case, code, config)
  assembly_engine.build(["classify_reasoning_v2"], classifier_vars)
  llm.call_model(classify_prompt, model=config.models.evaluator.name, ...)
  evaluator_v2.parse_classifier_v2_output(classify_result.response)
  → Returns ClassifierResultV2 with 4 dimension scores + failure_type

STAGE 7: Derive metrics
  metrics_v2.derive_v2_signals(classifier_dims, code_correct, commitments_source)
  → Returns V2Signals with mechanism_correct, commitments_valid,
    alignment_positive, v2_category, legacy_compat_category

STAGE 8: Assemble result
  evaluator_v2.assemble_v2_result(exec_result, artifact, classifier, signals, ...)
  → Returns final ev dict with 40+ fields

STAGE 9: Log
  logger.end_case(cid, condition, raw_ev=ev, ...)
  logger.log_run(cid, condition, prompt, raw_response, parsed_compat, ...)
```

### 4.2 V2 Retry Path

**Verified** from `retry_v2.py:283-616`.

```
runner._run_one_inner()
  → retry_v2.run_retry_v2(case, model, condition="retry_leg_critique_strict_v2", logger, eid)
```

Inside `run_retry_v2()`:

```
ITERATION LOOP (max 3 attempts, 300s timeout):
  Attempt 0: Same as baseline (prompt + call + parse + reconstruct + execute)
  
  If failed:
    Generate mismatch critique via separate LLM call:
      assembly_engine.build(["critique_mismatch_v2"], {root_cause, fix_strategy, code, task})
      llm.call_model(critique_prompt, model=model, ...)
      → Returns one-sentence mismatch description
      → Truncated to one sentence via _truncate_to_one_sentence()
      → Checked for prescriptive content via _check_prescriptive()
    
    Build retry prompt: previous raw response + critique + schema
    
  Attempt 1+: retry prompt + call + parse + reconstruct + execute
  
AFTER LOOP:
  Classify BEST result (highest score, latest on tie) via same Stage 6-7 as baseline
  Assemble and log
```

**Key distinction**: The critique is a *separate* prompt (`critique_mismatch_v2.j2`) that compares stated reasoning to code. It is NOT the classifier. The classifier runs once, after the loop, on the best attempt only.

### 4.3 Legacy Blind/Conditioned LEG Evaluation

**Verified** from `leg_evaluator.py:90-140` and `retry_harness.py:1420-1465`.

This path exists ONLY in the legacy retry harness (`retry_harness.py`), not in the v2 pipeline.

```
retry_harness.run_retry_harness()
  → After retry loop completes (line ~1420):
    If config.leg_enabled and case failed at least once:
      
      BLIND evaluation:
        leg_evaluator.evaluate_reasoning(
            model, reasoning_text, code_k, error_obj,
            classifier_type=None, blind=True, eval_model=eval_model
        )
        → Renders evaluate_reasoning_blind.j2 with code, error, reasoning
        → LLM call → parse_evaluator_output() → verdict (YES/NO), inferred_type
      
      CONDITIONED evaluation:
        leg_evaluator.evaluate_reasoning(
            model, reasoning_text, code_k, error_obj,
            classifier_type=failure_type, blind=False, eval_model=eval_model
        )
        → Renders evaluate_reasoning_conditioned.j2 (same + classifier_type field)
        → LLM call → parse_evaluator_output() → verdict (YES/NO), inferred_type
      
      Derived signals:
        compute_leg_true(entry):
          pass=False AND blind_verdict=YES AND blind_type == classifier_type
        compute_reasoning_matches_truth(entry):
          blind_type == classifier_type
        compute_evaluator_bias(trajectory):
          blind_yes_count vs conditioned_yes_count
```

**Status**: This blind/conditioned evaluator is the closest thing to RAudit's blindness constraint in the codebase, but it is **not used** in the v2 production path.

---

## 5. Evaluator Variants

### Table 1 — Evaluator Variants

| Variant | File / function | Trigger point | Inputs | Outputs | Blind? | Notes |
|---|---|---|---|---|---|---|
| **V2 Classifier** | `evaluator_v2.py:build_classifier_v2_vars()` + `parse_classifier_v2_output()` | `execution_v2.py:148` (Stage 6) | root_cause, fix_strategy, risk_check, code_commitments, task, code, canonical_family, optional ground_truth | 4 dimensions (CORRECT/PARTIAL/WRONG), failure_type, confidence, counterfactual, evidence, judgment | **No** — sees both reasoning and code | Production path. Uses `classify_reasoning_v2.j2` |
| **V1 Classifier** | `evaluator.py:llm_classify()` | `evaluator.py:303` (inside evaluate_output) | root_cause, failure_mechanism, broken_invariant, fix_strategy, self_check, risk_check, task, code, optional ground_truth | 5 dimensions + failure_type, confidence, counterfactual, evidence, judgment | **No** — sees reasoning and code | Legacy path. Uses `classify_reasoning.j2`. Has NameError bug on line 172. |
| **CRIT-lite Blind** | `leg_evaluator.py:evaluate_reasoning()` with `blind=True` | `retry_harness.py:1440` | code (failed), error_category, error_message, test_reasons, reasoning | YES/NO verdict + inferred failure type | **Yes** — no classifier_type, no ground truth, no execution result | Analysis-only, legacy path only |
| **CRIT-lite Conditioned** | `leg_evaluator.py:evaluate_reasoning()` with `blind=False` | `retry_harness.py:1453` | Same as blind + classifier_type | YES/NO verdict + inferred failure type | **No** — given system-detected failure type | Analysis-only, legacy path only |
| **Oracle (Reasoning Truth)** | `evaluators/reasoning_truth.py:render_prompt()` + `parse_response()` | Not wired into any execution path (standalone module) | task, buggy_code, oracle ground truth (bug_type, bug_location, invariant, fix_pattern, mechanism), developer's root_cause + fix_strategy | CORRECT/PARTIAL/WRONG/UNJUDGABLE + justification | **No** — given full ground truth | Not integrated into pipeline. Requires manual invocation. |
| **Heuristic Failure Classifier** | `failure_classifier.py:classify_failure()` | `evaluator.py` (via evaluate_output -> _compute_failure_source) | error_obj, critique text | failure_type + confidence + rule_path | N/A (no LLM) | Deterministic keyword matching. 4 priority rules. |
| **Disagreement Classifier** | `disagreement_classifier.py:classify_disagreement()` | `evaluator.py:229-300` (dual execution side-channel) | concat_result, module_result | DisagreementResult (type, subtype, confidence, assembly_confirmed) | N/A (no LLM) | Deterministic. Compares two execution modes. Side-channel only. |
| **Mismatch Critique** | `critique_mismatch_v2.j2` via `retry_v2.py:189` | `retry_v2.py` retry loop | root_cause, fix_strategy, code, task | One-sentence mismatch description or "NO MISMATCH" | Partially blind — no execution results | **Intervention**, not measurement. Feeds back into retry. |

---

## 6. Prompt Assembly and Inputs

### 6.1 Prompt Construction Path

All prompts are assembled through a single enforced path: **`assembly_engine.build(component_list, variables)`** (`assembly_engine.py`).

The flow:

```
assembly_engine.build(["classify_reasoning_v2"], vars)
  → prompt_registry.get(component_name) for each component
    → Loads prompts/components/{name}.j2
    → Renders Jinja2 template with provided variables
  → Concatenates rendered components
  → Returns RenderedPrompt(final_prompt, metadata)
```

`prompt_manifest.yaml` maps conditions to component lists, but the **classifier prompts are not condition-driven** — they are invoked directly by name in `execution_v2.py:159` and `evaluator.py:144`.

### 6.2 V2 Classifier Prompt Structure (`classify_reasoning_v2.j2`)

**Verified**: 316 lines. The prompt has this structure:

```
[Role statement: "STRICT reasoning-code alignment auditor"]
[Scope declaration: NOT evaluating code correctness or test results]

INPUTS:
  - Root Cause: {{ root_cause }}
  - Fix Strategy: {{ fix_strategy }}
  - Risk Check: {{ risk_check }}  (conditional, if present)
  - Task: {{ task }}
  - Code Produced: {{ code }}
  
  IF grounded mode:
    - Ground Truth: {{ ground_truth_failure_mode }}, {{ ground_truth_trap }}, {{ ground_truth_invariant }}

EVALUATION STEPS:
  Step 1: Extract mechanism from reasoning only
  Step 2: Extract commitments (explicit if present, else from reasoning)
  Step 2.5: Normalize commitments to "<scope> must <action>" form
  Step 2.6: CANONICAL COMMITMENT MATCHING — compare against hardcoded per-family patterns
  Step 3: Check commitment satisfaction against code
  Step 4: Rate 4 dimensions (CORRECT/PARTIAL/WRONG)
  
CANONICAL PATTERNS:
  10 bug families with 3 canonical commitments each (30 total patterns hardcoded)

OUTPUT FORMAT:
  Line 1: mechanism_identified;commitments_extracted;commitments_satisfied;reasoning_code_alignment;failure_type
  Line 2: confidence (HIGH/MEDIUM/LOW)
  Line 3: Counterfactual: <sentence>
  Line 4: Evidence: <bullets>
  Line 5: Judgment: <sentences>
  Optional: ---DEBUG--- section
```

### 6.3 V1 Classifier Prompt Structure (`classify_reasoning.j2`)

**Verified**: 131 lines. 5 dimensions instead of 4:

```
INPUTS:
  - Root Cause, Failure Mechanism, Broken Invariant, Fix Strategy, Self-Check, Risk Check
  - Task, Code
  - IF grounded: Ground Truth

DIMENSIONS:
  1. mechanism_identified
  2. invariant_identified     ← V2 drops this
  3. causal_chain_complete    ← V2 drops this
  4. fix_alignment            ← V2 drops this
  5. reasoning_code_alignment ← V2 keeps this

OUTPUT: 6 semicolons on line 1 (5 dims + failure_type)
```

### 6.4 Blind Evaluator Prompt (`evaluate_reasoning_blind.j2`)

**Verified**: 62 lines. Simpler than the classifiers:

```
INPUTS:
  - Code (FAILED): {{ code }}
  - Test Failure: {{ error_category }}, {{ error_message }}, {{ test_reasons }}
  - Developer's Reasoning: {{ reasoning }}

NO ground truth. NO classifier type. NO execution result.

OUTPUT: Single line "VERDICT ; FAILURE_TYPE"
  e.g., "YES ; TEMPORAL_ORDERING"
```

### 6.5 Conditioned Evaluator Prompt (`evaluate_reasoning_conditioned.j2`)

**Verified**: 65 lines. Identical to blind except adds one section:

```
  ## System-Detected Failure Type
  {{ classifier_type }}
```

### Table 2 — Evaluator Input Fields

| Field | Source | Passed to which evaluator(s) | Transformation | Leakage risk | Notes |
|---|---|---|---|---|---|
| `root_cause` | Model's JSON response, extracted by parser_v2 | V2 Classifier, Mismatch Critique | `.strip()` or `"[EMPTY]"` via reasoning_v2 | None | |
| `fix_strategy` | Model's JSON response | V2 Classifier, V1 Classifier, Mismatch Critique | Same normalization | None | |
| `risk_check` | Model's JSON response (LEG conditions only) | V2 Classifier (conditional) | Conditional inclusion `{% if risk_check %}` | None | |
| `code_commitments` | Model's JSON response (LEG conditions only) | V2 Classifier (via commitments_source) | Normalized via `normalize_commitments()` | None | Not directly in prompt; affects `commitments_source` label |
| `code` | Reconstructed code from model's files dict | V2 Classifier, V1 Classifier, Mismatch Critique, Blind/Conditioned | Joined from changed files after reconstruction | **Medium** — code quality indirectly reveals execution likelihood | |
| `task` | `case["task"]` from cases JSON | All evaluators | None | None | |
| `error_category` | From `exec_eval` / `exec_canonical` result | Blind/Conditioned evaluator ONLY | None | **This is execution result leakage into blind evaluator** | See Section 10 |
| `error_message` | From execution result | Blind/Conditioned evaluator ONLY | None | Same | |
| `test_reasons` | From execution result | Blind/Conditioned evaluator ONLY | None | Same | |
| `classifier_type` | From `failure_classifier.classify_failure()` | Conditioned evaluator ONLY | None | **Intentional** — this is the conditioned variable | |
| `ground_truth_failure_mode` | `case["failure_mode"]` | V2 Classifier (grounded mode), Oracle | None | **High** — directly reveals answer | Only in grounded mode |
| `ground_truth_trap` | `case["ground_truth_bug"]["trap"]` | V2 Classifier (grounded mode), Oracle | None | High | |
| `ground_truth_invariant` | `case["ground_truth_bug"]["invariant"]` | V2 Classifier (grounded mode), Oracle | None | High | |
| `canonical_family` | Derived from `mapping_v2.get_canonical_family()` | V2 Classifier (via `failure_types` list) | None | **Medium** — constrains failure type to known set | |
| `failure_types` | Joined list of valid types from `reasoning.VALID_FAILURE_TYPES` | V1 Classifier, V2 Classifier | Template variable | Low | |
| `reasoning` (raw text) | Concatenated reasoning fields | Blind/Conditioned evaluator | Stringified | None | |

---

## 7. How Reasoning Correctness Is Determined

There are **four distinct mechanisms** for determining reasoning correctness, used in different contexts:

### 7.1 V2 Primary: Separated Dimensions (Production)

**Location**: `metrics_v2.py:31-85`

The v2 system does NOT produce a single "reasoning_correct" boolean as its primary output. Instead it produces three separated signals:

```python
mechanism_correct = (mechanism_identified == "CORRECT")         # line 57
commitments_valid = (commitments_extracted in ("CORRECT", "PARTIAL"))  # line 58
alignment_positive = (reasoning_code_alignment == "CORRECT")    # line 59
```

These are the **primary scientific measures**. The code comments explicitly state this (`metrics_v2.py:4-5`):

> "These are NOT collapsed into one boolean for primary scientific analysis."

A **compatibility rollup** exists for backward-compatible reporting:

```python
reasoning_correct_compat = mechanism_correct and commitments_valid and alignment_positive  # line 63
```

**Verified**: This rollup is labeled as "NOT primary scientific measure" in the dataclass docstring.

### 7.2 V1: Five-Dimension Collapse (Legacy)

**Location**: `reasoning.py:196-256`

The v1 system produces 5 dimension scores and collapses them to a single boolean:

```python
# strict mode (default):
reasoning_correct = (
    m == "CORRECT" and
    i in ("CORRECT", "PARTIAL") and
    c in ("CORRECT", "PARTIAL") and
    f in ("CORRECT", "PARTIAL")
)
# reasoning_code_alignment not checked in strict mode!
```

**Finding**: In v1 strict mode, `reasoning_code_alignment` (dimension 5) is NOT used in the `reasoning_correct` computation. This means a model can have `reasoning_code_alignment = WRONG` and still be marked `reasoning_correct = True`. This is a **conceptual mismatch** with the stated goal of measuring reasoning-code consistency.

**Special case for LEG schema** (`reasoning.py:230-234`): When `schema_matched == "leg"`, dimensions `invariant_identified` and `causal_chain_complete` are forced to `"CORRECT"` (since the LEG prompt doesn't ask for them), and PARTIAL `mechanism_identified` is promoted to CORRECT. This silently changes the bar for reasoning correctness based on which prompt condition was used.

### 7.3 CRIT-lite: Binary Verdict (Legacy Analysis)

**Location**: `leg_evaluator.py:90-140`

The blind/conditioned evaluator produces a binary YES/NO verdict. There is no dimensional breakdown. The evaluator LLM makes a single judgment: "did the reasoning correctly identify the failure type AND mechanism AND connect to the error?"

### 7.4 Oracle: Ground-Truth Comparison (Standalone)

**Location**: `evaluators/reasoning_truth.py`

Uses ground truth (bug_type, bug_location, invariant, fix_pattern, mechanism_description) to judge reasoning as CORRECT/PARTIAL/WRONG/UNJUDGABLE. Not integrated into any pipeline.

### 7.5 How these interact

In the v2 production path, **only mechanism 7.1** is active. The classifier LLM produces 4 dimension scores, which are split into 3 boolean signals. The `reasoning_correct_compat` rollup exists for backward-compatible tables but is explicitly marked as non-primary.

The CRIT-lite blind/conditioned evaluator (7.3) is **completely separate** from the v2 classifier. It runs in the legacy retry harness only.

---

## 8. How Reasoning-Code Alignment / Inconsistency Is Determined

### 8.1 Explicit alignment dimension

The v2 classifier has an explicit `reasoning_code_alignment` dimension (dimension 4 of 4). The prompt defines it as:

> **Required**: code matches fix strategy, correct location modified, no contradiction.

This is a **prompt-based, LLM-judged** assessment. There is no programmatic comparison of reasoning text to code AST.

The dimension produces CORRECT/PARTIAL/WRONG, which maps to:

```python
alignment_positive = (rca == "CORRECT")  # metrics_v2.py:59
```

### 8.2 Commitment satisfaction as alignment proxy

The v2 system has a second alignment signal: `commitments_satisfied`. This checks whether the model's stated code_commitments (e.g., "create_config must return a copy of DEFAULTS") are implemented in the code. This is also LLM-judged via the same classifier prompt.

### 8.3 Mismatch critique as intervention signal

The `critique_mismatch_v2.j2` template directly compares reasoning to code:

> "In ONE sentence, state the specific mismatch between the developer's stated fix strategy and what their code actually does."

This is used in the retry loop to generate feedback, not as a measurement. It produces a natural language critique, not a structured score.

### 8.4 What does NOT exist

- **No AST-level comparison**: There is no code that programmatically compares the reasoning text to code structure.
- **No embedding similarity**: No vector similarity between reasoning and code.
- **No RCA-style trace-output consistency check**: The RCA paper describes checking whether derivation steps support conclusions. This is not implemented in the code generation arm — the v2 classifier's `reasoning_code_alignment` dimension is the closest analog, but it's a single LLM judgment, not a structured trace analysis.
- **No direct reasoning-vs-code diff**: The system does not identify cases where "reasoning mentions correct fix but code implements different fix" at a structural level. This is left entirely to the classifier LLM's judgment.

### 8.5 Derived alignment categories

The system infers alignment from the combination of reasoning correctness and execution results:

```python
# join_reasoning_execution.py:54-63
"aligned"     = mechanism_correct AND exec_pass
"misaligned"  = mechanism_correct AND NOT exec_pass    # THIS IS LEG
"lucky"       = NOT mechanism_correct AND exec_pass
"both_wrong"  = NOT mechanism_correct AND NOT exec_pass
```

This is a **2x2 matrix** inference, not a direct measurement of whether reasoning matches code. A model can have `reasoning_code_alignment = CORRECT` (classifier says code matches reasoning) but `misaligned` (code fails tests) — meaning the reasoning was wrong AND the code faithfully implemented that wrong reasoning.

---

## 9. LEG, Lucky Fix, and Related Metrics

### Table 3 — Derived Metrics

| Metric | Definition as implemented | Upstream dependencies | Code location | Main confounds |
|---|---|---|---|---|
| **LEG_v2** | `code_correct=False AND mechanism_correct=True AND commitments_valid=True AND alignment_positive=False` | V2 classifier dims, exec result | `metrics_v2.py:110-111` | Classifier accuracy; commitment matching quality |
| **leg** (legacy compat) | `reasoning_correct_compat=True AND code_correct=False` | Collapsed reasoning_correct, exec result | `metrics_v2.py:125` | Conflates mechanism + commitment + alignment into one bool |
| **leg_true** (from load_logs) | `reasoning_correct=1 AND pass=0` | Whatever reasoning_correct was at log time | `load_logs.py:234` | Depends on which classifier path produced reasoning_correct |
| **leg_candidate** | `mechanism_correct=True AND NOT execution_pass` | mechanism_correct only, exec result | `score_execution.py:49` | Ignores commitments and alignment |
| **lucky_fix_v2** | `code_correct=True AND (NOT mechanism_correct OR (mechanism_correct AND NOT commitments_valid))` | V2 classifier dims, exec result | `metrics_v2.py:103-107` | |
| **lucky_fix** (legacy) | `NOT reasoning_correct_compat AND code_correct` | Collapsed reasoning_correct, exec result | `metrics_v2.py:127` | |
| **interpretable_success** | `code_correct AND mechanism_correct AND commitments_valid AND alignment_positive` | All 3 primary signals + exec | `metrics_v2.py:98-99` | Highest bar category |
| **true_failure** (legacy) | `NOT reasoning_correct_compat AND NOT code_correct` | Collapsed reasoning_correct, exec | `metrics_v2.py:128` | |
| **full_failure_v2** | `NOT mechanism_correct AND NOT code_correct` (or mechanism correct but commitments not valid) | V2 dims + exec | `metrics_v2.py:113-115` | |
| **LEG_adjusted_conservative** | LEG_raw minus assembly_confirmed infrastructure failures | LEG + dual execution disagreement | `live_metrics.py:606-620` | Only available when dual execution runs |
| **reasoning_execution_alignment** | 5-way: aligned/misaligned/lucky/both_wrong/unknown | mechanism_correct + exec_pass | `join_reasoning_execution.py:54-63` | Binary mechanism_correct only |

### 9.1 Three LEG formulas

There are **three distinct LEG computations** that can disagree:

1. **LEG_v2** (4-way gate): Requires mechanism correct AND commitments valid AND alignment NOT positive AND code fails. This is the strictest definition.

2. **leg (compat)** (2-way): Requires the collapsed `reasoning_correct_compat` (which is mechanism AND commitments AND alignment) AND code fails. But note: if alignment is CORRECT, the compat reasoning_correct is True, but LEG_v2 requires alignment to be NOT positive. **These formulas are contradictory**: `leg_compat` requires alignment positive (through the rollup), while `LEG_v2` requires alignment NOT positive. They measure different things.

3. **leg_candidate** (simplest): Only requires mechanism_correct AND code fails. Ignores commitments and alignment entirely.

**Finding**: The `leg` (legacy compat) and `LEG_v2` categories are **mutually exclusive** by construction. If `alignment_positive = True`, the compat path marks it as `leg` (reasoning_correct_compat = True, code fails). But LEG_v2 requires `alignment_positive = False`. This means:
- `LEG_v2` captures cases where reasoning is correct but code doesn't implement it.
- `leg` (compat) captures cases where reasoning is correct AND code implements it but still fails.

These measure fundamentally different phenomena. The naming similarity is misleading.

### 9.2 Stubbornness / Sycophancy

**Verified** in `retry_harness.py:765-850`:

- **Stubborn trajectory** (`retry_harness.py:809`): Classified via `_classify_regime()` based on failure type persistence and score oscillation. Uses `_compute_failure_persistence()` (line 520) to track whether the same failure type recurs.
- **Sycophantic behavior**: Not explicitly classified in the code. The word "sycophant" appears in research docs but not as a computed metric.
- **Stagnation detection** (`retry_harness.py:221`): `_is_stagnated()` checks code similarity (keyword overlap > 0.8) and score non-improvement.

---

## 10. Blindness / Leakage Audit

### 10.1 V2 Classifier: NOT blind

**Verdict: Not blind.**

The v2 classifier (`classify_reasoning_v2.j2`) receives:

1. The model's `root_cause` and `fix_strategy` (reasoning)
2. The model's generated `code`
3. The `task` description

It does NOT receive:
- Execution results (pass/fail)
- Test output
- Error messages
- Prior attempt history

However, it DOES receive:
- **Canonical commitment patterns per bug family** (hardcoded in the prompt, lines 132-191). These list 30 patterns across 10 bug families (ALIASING, PARTIAL_STATE_UPDATE, STALE_CACHE, etc.) that are "NECESSARY conditions for a correct fix." This effectively gives the evaluator a **lookup table of correct answers**, constrained by the bug families in the benchmark. The evaluator doesn't need to independently assess reasoning quality — it can pattern-match against the provided canonical patterns.

**In grounded mode** (`classifier_mode = "grounded"`):
- The prompt additionally receives `ground_truth_failure_mode`, `ground_truth_trap`, and `ground_truth_invariant`. This is fully non-blind.

**Risk assessment**: The canonical commitment patterns are a form of **indirect ground truth leakage**. While the evaluator doesn't see execution results, it has a reference table that tells it what correct reasoning looks like for each bug family. This is by design (the prompts call it "calibration"), but it means the classifier is not evaluating reasoning quality in a vacuum — it is comparing against known-correct patterns.

### 10.2 CRIT-lite Blind Evaluator: Mostly blind but leaky

**Verdict: Mostly blind but with execution result leakage.**

The blind evaluator (`evaluate_reasoning_blind.j2`) receives:

1. `code` — the **failed** code (header says "Code (FAILED)")
2. `error_category`, `error_message`, `test_reasons` — **execution results**
3. `reasoning` — the model's reasoning text

**Critical finding**: The blind evaluator receives test failure details. The prompt header literally says "Code (FAILED)" and shows the error category, error message, and failed assertions. This means the evaluator knows:
- That the code failed (not blind to execution outcome)
- Why it failed (error details)
- Which tests failed (assertions)

The "blindness" is only with respect to the **failure type classification** (TEMPORAL_ORDERING, HIDDEN_DEPENDENCY, etc.). The evaluator must infer the failure type without being told it. But it IS told that the code failed and how.

This is blind in the RAudit sense (no access to correct answer / ground truth), but it is NOT blind to execution results. The RAudit paper's blindness constraint says the auditor should evaluate "only whether derivation steps support conclusions." Here, the evaluator sees the execution failure, which is outcome information.

### 10.3 Conditioned Evaluator: Explicitly not blind

**Verdict: Not blind (by design).**

Identical to blind evaluator plus `classifier_type` — the heuristic failure classification. This is the experimental control arm.

### 10.4 Summary of blindness

| Evaluator | Blind to ground truth? | Blind to execution results? | Blind to failure type? | Blind to code? | Overall |
|---|---|---|---|---|---|
| V2 Classifier | Yes (blind mode) / No (grounded) | **Yes** | Partially (has canonical patterns) | **No** | Not blind |
| CRIT-lite Blind | Yes | **No** (sees errors) | Yes | No | Mostly blind, execution-leaky |
| CRIT-lite Conditioned | Yes | No | **No** | No | Not blind |
| Oracle | **No** | N/A | No | N/A (sees buggy code) | Not blind |

---

## 11. Contracts, Parsing, and Structured Output Fragility

### 11.1 V2 Classifier Output Schema

**Defined in**: `evaluator_v2.py:123-237` (`parse_classifier_v2_output`)

Expected format:
```
CORRECT;PARTIAL;WRONG;CORRECT;ALIASING
HIGH
Counterfactual: <sentence>
Evidence: <bullets>
Judgment: <sentences>
```

**Parsing logic**:
1. Strip everything after `---DEBUG---`
2. Split into non-empty lines
3. Line 1: split on `;`, expect exactly 5 fields (4 dims + failure_type)
4. Each dim validated against `V2_VALID_DIMENSION_VALUES` = {CORRECT, PARTIAL, WRONG}
5. Line 2: confidence validated against `V2_VALID_CONFIDENCE` = {HIGH, MEDIUM, LOW}
6. Lines 3+: section detection by prefix ("Counterfactual:", "Evidence:", "Judgment:")
7. Multiline sections: handled by detecting section prefixes and accumulating

**Failure modes**:
- If line 1 has wrong number of semicolons → parse_error, all dims = None
- If a dimension value is not in {CORRECT, PARTIAL, WRONG} → parse_error
- If failure_type is unknown → `parse_error` set but result still usable (dims preserved)
- If confidence is invalid → parse_error

**Downstream impact of parse failure**: When any dim is None, `derive_v2_signals()` returns `v2_category = "classifier_failure_v2"`. The case gets excluded from LEG/lucky_fix categorization. This means **parser fragility directly inflates the "classifier_failure" category** and deflates all others.

### 11.2 V1 Classifier Output Schema

**Defined in**: `reasoning.py:128-195` (`parse_classify_output`)

Expected: exactly 5 non-empty lines, line 1 has 6 semicolons (5 dims + failure_type).

**Fragility**: V1 requires **exactly 5 non-empty lines**. Any extra blank line or preamble text causes parse failure. V2 improved this by allowing multiline sections and preamble tolerance.

### 11.3 Blind Evaluator Output Schema

**Defined in**: `leg_evaluator.py:36-88` (`parse_evaluator_output`)

Expected: exactly one non-empty line with exactly one semicolon. Left = YES/NO, right = failure type.

**Very strict**: Any extra line, missing semicolon, or unknown failure type → parse failure. This is intentionally strict to avoid ambiguity.

### 11.4 Generation Output Parsing

**Defined in**: `parser_v2.py` (three-tier architecture)

The generator model's response is parsed through:
1. **Execution parser** (line 283): Extracts JSON. Tolerates surrounding text/fences. Rejects multiple JSON objects.
2. **Format parser** (line 329): Checks exact format compliance (no fences, no extra text).
3. **Recovery parser** (line 389): Multi-phase repair (fence stripping, escape fixing, triple-quote repair, code→files rename).

Only the execution parser drives the pipeline. Format and recovery are diagnostic.

**Confound risk**: If a model's JSON output fails parsing but contains correct reasoning, the case is categorized as `parser_failure_v2` and excluded from all reasoning analysis. The `leg_effect_canonical_report.md` explicitly addresses this by computing "reconstruction-conditioned" metrics that filter to successfully parsed trials. This is methodologically sound but means the headline numbers include parsing artifacts.

### 11.5 Reconstruction

**Defined in**: `reconstructor.py:168-327` (`reconstruct_strict`)

5-gate validation:
1. Exact "UNCHANGED" → use original
2. Empty/whitespace → blocks (RECON_EMPTY_FILE)
3. No-change phrase detection → blocks (RECON_SENTINEL_MISMATCH)
4. `ast.parse()` → blocks if syntax invalid (RECON_INVALID_CODE)
5. Semantic structure check → diagnostic only

**Confound**: Reconstruction failures prevent execution, which prevents LEG/lucky_fix categorization. A model that produces correct reasoning but syntactically invalid code gets `RECONSTRUCTION_FAILURE` → no execution → no classification. This inflates the appearance of "failure" beyond reasoning quality.

---

## 12. Logging, Artifacts, and Reproducibility

### 12.1 What is preserved

**Per LLM call** (via `call_logger.py`):
- Raw prompt text
- Raw response text
- Model name, elapsed time, error
- Prompt assembly metadata (component names, hashes, variables, condition)
- Stored as individual JSON files in `{run_dir}/calls/{call_id}.json`

**Per case** (via `logging_core.py`):
- Canonical event with 14 sections (schema v7)
- `execution`: ran, passed, score, tests_run, tests_passed, runtime_ms, error
- `reasoning`: evaluated, reasoning_correct, failure_type, confidence
- `extra`: all non-canonical fields (including all v2 classifier dimensions, parse tiers, artifact details)
- Stored in `{run_dir}/events.jsonl`

**Per run** (via `logging_core.py:1036`):
- `metrics.json` with pass_rate, total_cases, total_pass
- Finalized event file

### 12.2 What is NOT preserved

- **Classifier prompt text**: The actual prompt sent to the evaluator LLM is logged via `call_logger` (as a raw LLM call), so it IS recoverable. **Verified**: `execution_v2.py:162-169` passes `logger` to `call_model` for the classifier call.
- **Parsed classifier dimensions**: Stored in the `extra` section of events, with `_dim` suffix.
- **Raw classifier response**: Stored as `classify_v2_raw` in the event dict.

### 12.3 Can a third party reconstruct evaluator decisions?

**Yes, with caveats.**

From logs alone, a third party can:
1. Read the raw generator response (from `calls/` files)
2. Read the raw classifier response (from `calls/` files, identified by `phase="classification"`)
3. Read the parsed classifier dimensions (from `events.jsonl`, in the `extra` section)
4. Read the execution results (from `events.jsonl`, in the `execution` section)
5. Derive the category from dimensions + execution results (using `metrics_v2.py` logic)

**Missing for full reconstruction**:
- The exact classifier prompt is logged as raw text but the template variables are only partially reconstructable (the prompt assembly metadata has component names and hashes but not all variable values).
- The evaluator model name is in the config but not always in the event itself. **Verified**: The `reasoning` section has `evaluated` boolean but not `evaluator_model`. The LLM call log has the model name.

### 12.4 Reproducibility

- **Config-driven**: All experimental parameters come from YAML config. Seeds are not used for LLM calls (non-deterministic by nature), but case order and condition assignment are deterministic.
- **Schema versioning**: `REASONING_SCHEMA_VERSION = 3` enforced at log load time (`reasoning.py:318`).
- **Run ID**: Each run gets a unique ID in the logger.
- **Trial indexing**: Events include trial number.

---

## 13. Confirmed Findings, Weak Points, and Open Questions

### Table 4 — Confirmed Risks

| Risk | Severity | Evidence | Why it matters | Suggested fix |
|---|---|---|---|---|
| **NameError bug in v1 classifier** | P0 (if v1 path used) | `evaluator.py:172` references undefined `raw` variable | Crashes every v1 classification call | Fix: capture `call_model().response` into `raw` before use |
| **Canonical patterns leak answer space** | P1 | `classify_reasoning_v2.j2:132-191` hardcodes 30 correct-fix patterns | Evaluator has a lookup table instead of independently judging reasoning | By design, but limits claim of "blind" evaluation |
| **Three contradictory LEG formulas** | P1 | `metrics_v2.py:111` vs `:125` vs `score_execution.py:49` | Readers may conflate LEG_v2 with legacy leg; they measure different things | Document explicitly; consider renaming |
| **LEG_v2 vs leg compat are mutually exclusive** | P1 | LEG_v2 requires alignment_positive=False; leg compat requires it True (via rollup) | These literally cannot co-occur for the same trial | This is correct by design but naming is misleading |
| **Blind evaluator sees execution results** | P1 | `evaluate_reasoning_blind.j2:8-16` receives error_category, error_message, test_reasons | "Blind" evaluator is not blind to execution outcome | Rename to "ungrounded" or "type-blind" |
| **V1 reasoning_correct ignores reasoning_code_alignment** | P2 | `reasoning.py:215-225` strict mode doesn't check dim 5 | Model can have WRONG alignment and still be reasoning_correct | Fixed in v2 (alignment is a separate signal) |
| **LEG schema promotes PARTIAL mechanism to CORRECT** | P2 | `reasoning.py:230-234` | Lowers the bar for reasoning correctness in LEG conditions | Intentional design choice but creates condition-dependent threshold |
| **Dual execution side-channel complexity** | P2 | `evaluator.py:229-300` with 70+ lines of try/except | Complex logic that never affects canonical pipeline but adds code surface | Consider extracting to separate module |
| **Parser failure inflates classifier_failure category** | P2 | `metrics_v2.py:49-54` returns classifier_failure_v2 on any None dim | Parsing noise affects category distribution | Already mitigated by reconstruction-conditioned analysis |
| **V1 classifier has stale code paths** | P3 | `evaluator.py:389-510` deprecated functions, backward compat re-exports | Dead code increases cognitive load | Remove deprecated functions |
| **No evaluator model name in canonical event schema** | P3 | `logging_core.py:592-648` reasoning section has no evaluator_model field | Harder to audit which model evaluated which trial | Add `evaluator_model` to reasoning section |

### 13.1 Conceptual mismatches between papers and code

| Paper concept | Implementation status |
|---|---|
| RAudit blindness constraint (no outcome access) | **Partially implemented**. The blind evaluator sees execution errors. The v2 classifier doesn't see execution results but has canonical patterns. |
| RCA trace-output consistency checking | **Not implemented** in code generation arm. The v2 `reasoning_code_alignment` dimension is the closest analog but is a single LLM judgment, not a structured trace analysis. |
| PID control loop for reasoning quality | **Not implemented** in code generation arm. Implemented in the trading/debate arm (separate codebase). |
| CRIT 4-pillar scoring | **Partially mapped**. V2 classifier has 4 dimensions but they are different from CRIT's P1-P4 (Logical Validity, Evidential Support, Alternative Consideration, Causal Alignment). V2 uses mechanism, commitments_extracted, commitments_satisfied, reasoning_code_alignment. |
| Strategy escalation (Direct → CoT → Code) | **Not implemented**. |
| Sycophancy detection and measurement | **Not implemented** as a computed metric in code generation arm. |
| ConsistencyJudge | **Not implemented** in code generation arm. |

### 13.2 Things that are clean

- The v2 pipeline separation (execution_v2.py) is well-structured with clear 9-stage flow.
- The three-tier parser architecture (execution/format/recovery) is sound — keeping diagnostic tiers separate from the pipeline driver.
- The `metrics_v2.py` signal derivation is clean pure-function code with no side effects.
- The `derive_v2_signals()` function explicitly separates primary scientific measures from compatibility rollups.
- Prompt assembly through `assembly_engine.build()` is a genuine single path with enforcement.
- The canonical event schema (v7) is comprehensive and well-documented in code.
- The `leg_effect_canonical_report.md` methodology (reconstruction-conditioned analysis) is rigorous.

---

## 14. Minimal Mental Model

**How to think about this evaluator system in one page.**

The system measures whether LLMs can *think correctly about bugs* and *translate that thinking into working code*. It does this by running a 2x2 experiment:

```
                     Code Passes    Code Fails
                    ┌──────────────┬──────────────┐
Reasoning Correct   │ true_success │    LEG       │
                    ├──────────────┼──────────────┤
Reasoning Wrong     │  lucky_fix   │ true_failure │
                    └──────────────┴──────────────┘
```

**Code correctness** is determined by subprocess execution against invariant tests. This is deterministic and trustworthy.

**Reasoning correctness** is determined by a second LLM call (the "evaluator model") that reads the generator's reasoning and code, and scores it on 4 dimensions. This is non-deterministic and depends on the evaluator LLM's judgment plus the quality of the classifier prompt.

**The key architectural invariant**: Evaluation is AFTER generation. The evaluator never feeds back into the generator (except in retry conditions, where *critiques* — not classifier scores — are fed back).

**The key branches**:
- V2 path (production): `execution_v2.py` → `parser_v2` → `reconstructor` → `exec_canonical` → `evaluator_v2` → `metrics_v2`
- Retry path: same but with a loop and critique-based feedback between attempts
- Legacy path: `execution.py` → `parse.py` → `exec_eval` → `evaluator.py` → `reasoning.py`

**The important invariants**:
1. Only the execution parser drives the pipeline (format and recovery are diagnostic)
2. The classifier runs on the evaluator model, not the generator model
3. Categories are derived from signals, never directly assigned by the LLM
4. All parameters come from YAML config

**The biggest risks**:
1. Classifier accuracy is unvalidated — there is no systematic measurement of evaluator LLM agreement with human judgment on these specific cases
2. The canonical commitment patterns in the classifier prompt constrain the evaluator's judgment space in ways that may inflate apparent "correctness"
3. Three different LEG formulas make it easy to cite the wrong metric

**The most likely cleanup path**:
1. Remove all v1 code paths (they have bugs and are not used in production)
2. Add evaluator model name to canonical event schema
3. Rename "blind" evaluator to "type-blind" or "ungrounded" to avoid confusion with RAudit's stronger blindness concept
4. Add inter-rater reliability measurements for the v2 classifier
5. Consolidate the three LEG formulas with explicit documentation of what each measures

---

## Appendix A. File-by-File Notes

### `evaluator.py` (646 lines)
- **Purpose**: V1 evaluation dispatcher — orchestrates execution, classification, category derivation, and SCM evidence scoring.
- **Key symbols**: `evaluate_output()` (main entry), `llm_classify()` (LLM classifier call), `compute_alignment()` (deprecated), `compute_evidence_metrics()` (SCM scoring), `_detected_correct_reasoning()` (deprecated heuristic).
- **Evaluator role**: Central hub for v1. Calls `exec_evaluate()`, then `llm_classify()`, then `compute_category()`.
- **Suspicious/fragile**: Line 172 NameError (`raw` undefined). Lines 389-510 are deprecated but still importable. Dual execution block (229-300) is 70 lines of try/except that is side-channel only.

### `evaluator_v2.py` (319 lines)
- **Purpose**: V2 classifier invocation, output parsing, and result assembly.
- **Key symbols**: `ClassifierResultV2` (dataclass), `build_classifier_v2_vars()`, `parse_classifier_v2_output()`, `assemble_v2_result()`.
- **Evaluator role**: Builds classifier prompt variables, parses classifier output into structured dimensions, assembles final result dict.
- **Suspicious/fragile**: `_field_or_missing()` returns `None` for blank values (not `"[COULD NOT EXTRACT]"` like v1) — inconsistency between v1 and v2.

### `leg_evaluator.py` (197 lines)
- **Purpose**: CRIT-lite blind/conditioned reasoning evaluator. Analysis only.
- **Key symbols**: `evaluate_reasoning()`, `parse_evaluator_output()`, `compute_leg_true()`, `compute_reasoning_matches_truth()`, `compute_evaluator_bias()`.
- **Evaluator role**: Post-hoc analysis of reasoning correctness with/without failure type hint. Used only in legacy retry harness.
- **Suspicious/fragile**: `evaluate_reasoning()` lazy-imports `assembly_engine.build` inside function body. The "blind" evaluator still sees execution error details.

### `execution_v2.py` (243 lines)
- **Purpose**: V2 9-stage execution pipeline. Single entry point for v2 conditions.
- **Key symbols**: `run_v2()`.
- **Evaluator role**: Orchestrates the full pipeline from prompt build through classification and logging.
- **Clean**: Well-structured, clear stage separation, explicit invariant checks.

### `reasoning.py` (333 lines)
- **Purpose**: V1 reasoning extraction, validation, classifier output parsing, category computation.
- **Key symbols**: `extract_reasoning_obj()`, `validate_reasoning()`, `parse_classify_output()`, `compute_reasoning_correct()`, `compute_category()`.
- **Evaluator role**: Defines the v1 dimensional evaluation framework and category assignment.
- **Suspicious/fragile**: LEG schema forces 2 dimensions to CORRECT and promotes PARTIAL mechanism to CORRECT (lines 230-234). Strict mode ignores reasoning_code_alignment dimension.

### `reasoning_v2.py` (238 lines)
- **Purpose**: V2 reasoning normalization and artifact construction.
- **Key symbols**: `NormalizedReasoningArtifactV2` (dataclass), `normalize_generation_v2()`, `normalize_commitments()`.
- **Evaluator role**: Transforms raw parsed reasoning into normalized form for the classifier.
- **Clean**: Well-documented normalization pipeline with phase annotations.

### `metrics_v2.py` (129 lines)
- **Purpose**: V2 signal derivation — the pure-function core of category computation.
- **Key symbols**: `V2Signals` (dataclass), `derive_v2_signals()`, `_compute_v2_category()`, `_compute_legacy_compat()`.
- **Evaluator role**: Converts classifier dimensions + execution results into categories.
- **Clean**: Explicit separation of primary signals from compatibility rollups. Well-documented.

### `contracts_v2.py` (92 lines)
- **Purpose**: V2 field schemas and validation for generation output.
- **Key symbols**: `V2_BASELINE_REQUIRED`, `V2_LEG_REQUIRED`, `CONDITION_TO_SCHEMA`, `V2_CLASSIFIER_DIMENSIONS`, `validate_generation_fields()`.
- **Evaluator role**: Defines what the generator must produce and what the classifier evaluates.
- **Clean**: Small, focused, no surprises.

### `parser_v2.py` (539 lines)
- **Purpose**: Three-tier v2 generation output parser.
- **Key symbols**: `ParsedGenerationV2` (dataclass), `parse_v2_execution()`, `parse_v2_format()`, `parse_v2_recovery()`.
- **Evaluator role**: Extraction of code and reasoning from generator output. Parse failure → no evaluation.
- **Clean**: Well-separated tiers with clear contracts.

### `reconstructor.py` (383 lines)
- **Purpose**: File-level reconstruction from model's files dict to executable code.
- **Key symbols**: `ReconstructionResult` (dataclass), `reconstruct_strict()`, `reconstruct_salvage()`.
- **Evaluator role**: Converts parsed files dict to reconstructed code for execution. Reconstruction failure → no execution → no classification.
- **Clean**: 5-gate validation with clear pass/fail semantics.

### `exec_canonical.py` (356 lines)
- **Purpose**: Disk-backed subprocess execution — deterministic test oracle.
- **Key symbols**: `exec_canonical()`, `_materialize_package()`, `_run_subprocess()`, `_classify()`.
- **Evaluator role**: Ground truth pass/fail determination. 12 classification categories.
- **Clean**: Subprocess isolation prevents code-under-test from affecting the evaluator process.

### `exec_eval.py` (1060 lines)
- **Purpose**: In-process execution evaluator (legacy). Loads model code via `exec()`.
- **Key symbols**: `exec_evaluate()`, `_CASE_TESTS` (dispatch table), `_load_v2_test()`.
- **Evaluator role**: Legacy ground truth. Still used as fallback in some retry paths.
- **Suspicious/fragile**: In-process `exec()` means test code shares process with evaluator.

### `failure_classifier.py` (157 lines)
- **Purpose**: Heuristic failure type classifier (no LLM).
- **Key symbols**: `classify_failure()`, `FAILURE_TYPES`, `FAILURE_TYPE_SET`.
- **Evaluator role**: Produces failure type for conditioned evaluator and logging.
- **Clean**: Deterministic, well-documented priority rules.

### `logging_core.py` (1144 lines)
- **Purpose**: Centralized logging with canonical event schema v7.
- **Key symbols**: `RunLogger`, `OrchestratorLogger`, event schema definition.
- **Evaluator role**: Persists all evaluator inputs, outputs, and derived labels.
- **Missing**: No `evaluator_model` field in canonical reasoning section.

### `live_metrics.py` (1017 lines)
- **Purpose**: Real-time dashboard with LEG rate computation and dual-execution adjustment.
- **Key symbols**: `LEG_adjusted_conservative`, `LEG_adjusted_broad`, regime distribution, intervention effects.
- **Evaluator role**: Post-hoc aggregation and visualization.
- **Useful**: Contains the only LEG adjustment for assembly infrastructure failures.

---

## Appendix B. Concrete Call Chains

### Chain 1: V2 Baseline (production path)
```
runner.main()
  → runner.run_ablation_mode(args)
    → runner.run_all(cases, model, conditions, logger, ...)
      → runner._run_one(case, model, condition, logger)
        → runner._run_one_inner(case, model, "baseline_v2", logger, eid)
          → execution_v2.run_v2(case, model, "baseline_v2", logger, eid)
            → assembly_engine.build(["task_and_code", "output_instruction_v3"], vars)
            → llm.call_model(prompt, model=model)  [GENERATION]
            → parser_v2.parse_v2_execution(raw_response, "baseline_v2")
            → reasoning_v2.normalize_generation_v2(parsed_gen, case, "baseline_v2")
            → reconstructor.reconstruct_strict(paths, files, parsed.files_dict)
            → exec_canonical.exec_canonical(case, parsed, recon, config, logger)
            → evaluator_v2.build_classifier_v2_vars(artifact, case, code, config)
            → assembly_engine.build(["classify_reasoning_v2"], classifier_vars)
            → llm.call_model(classify_prompt, model=eval_model)  [CLASSIFICATION]
            → evaluator_v2.parse_classifier_v2_output(classify_response)
            → metrics_v2.derive_v2_signals(dims, code_correct, commitments_source)
            → evaluator_v2.assemble_v2_result(exec, artifact, classifier, signals, ...)
            → logger.end_case(cid, condition, raw_ev=ev)
            → logger.log_run(cid, condition, prompt, raw_response, parsed)
```

### Chain 2: V2 Retry with Mismatch Critique
```
runner._run_one_inner(case, model, "retry_leg_critique_strict_v2", logger, eid)
  → retry_v2.run_retry_v2(case, model, condition, logger, eid)
    LOOP (max 3 iterations):
      → assembly_engine.build(components, vars)  [GENERATION PROMPT]
      → llm.call_model(prompt, model=model)
      → parser_v2.parse_v2_execution(raw, condition)
      → reconstructor.reconstruct_strict(...)
      → exec_canonical.exec_canonical(...) OR exec_eval.exec_evaluate(...)
      IF failed AND not last:
        → retry_v2._generate_critique(variant, root_cause, fix_strategy, code, ...)
          → assembly_engine.build(["critique_mismatch_v2"], critique_vars)
          → llm.call_model(critique_prompt, model=model)  [CRITIQUE]
          → retry_v2._truncate_to_one_sentence(critique)
        → retry_v2._build_critique_retry_prompt(prev_raw, critique, schema)
    END LOOP
    
    → evaluator_v2.build_classifier_v2_vars(best_artifact, case, code, config)
    → assembly_engine.build(["classify_reasoning_v2"], classifier_vars)
    → llm.call_model(classify_prompt, model=eval_model)  [CLASSIFICATION]
    → evaluator_v2.parse_classifier_v2_output(response)
    → metrics_v2.derive_v2_signals(dims, code_correct, commitments_source)
    → evaluator_v2.assemble_v2_result(...)
    → logger.end_case(...)
```

### Chain 3: Legacy Blind/Conditioned LEG Evaluation
```
retry_harness.run_retry_harness(case, model, condition, logger, ...)
  RETRY LOOP:
    → execution.build_prompt(case, condition)
    → llm.call_model(prompt, model)
    → execution.evaluate_case(case, raw_output)
      → parse.parse_model_response(raw_output)
      → exec_eval.exec_evaluate(case, code)
      → evaluator.evaluate_output(case, parsed)
        → evaluator.llm_classify(case, code, reasoning, validation)  [V1 CLASSIFIER]
        → reasoning.compute_reasoning_correct(dims, mode)
        → reasoning.compute_category(code_correct, reasoning_correct, ...)
  END LOOP
  
  POST-LOOP ANALYSIS:
    → leg_evaluator.evaluate_reasoning(model, reasoning, code, error, blind=True)  [BLIND]
      → assembly_engine.build(["evaluate_reasoning_blind"], vars)
      → llm.call_model(prompt, model=eval_model)
      → leg_evaluator.parse_evaluator_output(response)
    → leg_evaluator.evaluate_reasoning(model, reasoning, code, error, blind=False)  [CONDITIONED]
      → assembly_engine.build(["evaluate_reasoning_conditioned"], vars)
      → llm.call_model(prompt, model=eval_model)
      → leg_evaluator.parse_evaluator_output(response)
    → leg_evaluator.compute_leg_true(entry)
    → leg_evaluator.compute_evaluator_bias(trajectory)
```

---

## Appendix C. Suggested Cleanup / Refactor Priorities

### P0 — Correctness / Leakage

1. **Fix NameError in `evaluator.py:172`**: The `raw` variable is never defined. Store `call_model().response` in a variable before passing to parser. (Only matters if v1 path is ever invoked.)

2. **Document canonical pattern leakage**: The v2 classifier prompt includes 30 canonical commitment patterns that effectively give the evaluator a lookup table. This should be documented as a design decision, not hidden. Consider measuring classifier accuracy with and without the canonical patterns.

3. **Clarify "blind" terminology**: The blind evaluator receives execution error details. Rename to "type-blind" or "failure-class-blind" to avoid confusion with RAudit's stronger blindness concept.

### P1 — Observability / Reproducibility

4. **Add evaluator_model to canonical event schema**: Currently the evaluator model name is only in the LLM call log, not in the canonical event. Add it to the `reasoning` section of the event schema.

5. **Consolidate LEG formula documentation**: Create a single reference document explaining the three LEG formulas, what each measures, and when each should be used. Consider renaming `leg` (compat) to `leg_aligned_fail` to distinguish from `LEG_v2`.

6. **Log classifier prompt variables**: The call_logger records the raw prompt but not the structured variables that were passed to the template. Add variable logging for classifier calls.

### P2 — Architecture Simplification

7. **Remove deprecated v1 functions**: `evaluator.py` has 5+ deprecated functions (`compute_alignment`, `_detected_correct_reasoning`, `classify_parse_category`) that are unused or backward-compat-only. Remove them.

8. **Extract dual execution to separate module**: The 70-line try/except block in `evaluator.py:229-300` is a side-channel that clutters the main evaluation flow.

9. **Unify parser missing-value sentinel**: V1 uses `"[COULD NOT EXTRACT]"`, v2 uses `None`. Pick one.

### P3 — Naming / Hygiene

10. **Rename `reasoning_correct_compat`**: The name suggests it IS reasoning_correct. Call it `legacy_reasoning_correct_rollup` or similar.

11. **Remove LEG schema dimension forcing**: `reasoning.py:230-234` forces two dimensions to CORRECT for LEG schema. This changes the evaluation bar silently. If LEG schema doesn't ask for these dimensions, set them to None and adjust `compute_reasoning_correct` to handle missing dimensions.

12. **Standardize failure type sets**: `failure_classifier.FAILURE_TYPES` and `reasoning.VALID_FAILURE_TYPES` are defined separately with the same values. Share a single constant.
