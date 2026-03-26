# D-BUDIT: Deep Bug / Silent Failure Audit
## T3 Code Generation MVP — Full System Reliability Audit
**Date:** 2026-03-24
**Auditor:** Claude Opus 4.6 (adversarial reliability audit)

---

## A. EXECUTIVE SUMMARY

### Top Silent Failure Risks (P0)

1. **EVAL-01: `evaluator.py:238` — `except ImportError` silently falls back to heuristic evaluators when `exec_eval` fails to import.** The heuristic evaluators (`eval_cases.py`) are text-matching pattern matchers that can produce wildly different results from execution-based evaluation. If `exec_eval.py` has a transient import issue (e.g., `parse.py` has a bug), the ENTIRE experiment silently switches to unreliable heuristic scoring. The user sees no warning that execution-based evaluation didn't happen.

2. **LOG-01: `execution.py:376` / `retry_harness.py:956` — `except OSError: pass` silently swallows ALL log write failures.** If the disk is full, permissions are wrong, or the path doesn't exist, every single data point is silently lost. The experiment continues and prints results to console, but no artifact is persisted. The experimenter sees "Log written: ..." at the end but the file may be empty or incomplete.

3. **PARSE-01: `parse.py:198-209` — raw fallback treats entire LLM output as code.** When no JSON or code blocks are found, the parser returns the entire raw response as the "code" field. This means the model's natural language reasoning gets `exec()`'d as Python code. It will fail — but with misleading error messages (SyntaxError on English text), and the eval_cases heuristic evaluator may still score it based on text patterns in the "code" (which is actually the full response).

4. **COND-01: `runner.py:51` — COND_LABELS has duplicate key "RA" for both `reason_then_act` and `retry_adaptive`.** This means printed results conflate these two conditions. Any analysis using the label column will merge data from two completely different conditions.

5. **DRIFT-01: `evaluator.py:233-241` — `evaluate_output` uses `exec_eval` for execution evaluation but falls back to `eval_cases` heuristic on ImportError.** The heuristic evaluator `_eval_generic` and case-specific evaluators in `eval_cases.py` use completely different scoring scales and criteria than exec_eval. Results are not comparable. A run that uses exec_eval and one that silently fell back to heuristics produce numbers that look identical but measure different things.

### Top Stale/Duplicate Path Risks

6. **LEGACY-01: `eval_cases.py` (entire file, 720+ lines) — Legacy heuristic evaluators that should never run in production but ARE still reachable via the ImportError fallback.** These pattern-matching evaluators were the v0 approach. They can produce false positives (text patterns match but code is wrong) and false negatives (correct code doesn't mention expected keywords).

7. **LEGACY-02: `runner.py:85-87` — backward-compat aliases `_build_prompt`, `_run_single`, `_run_repair_loop` re-export from execution.py.** These create an ambiguous import surface where tests may import from either location.

### Top Test Coverage Risks

8. **TEST-01: No test exercises the `except ImportError` fallback path in `evaluator.py:238`.** The most dangerous code path in the system has zero test coverage.

9. **TEST-02: No integration test verifies that log files contain the expected data after a run.** All tests mock `write_log` or ignore it. Log integrity — the primary reproducibility artifact — is untested.

10. **TEST-03: No test verifies that `cases_v2.json` and `_CASE_TESTS`/`_load_v2_test` are in sync.** A case could exist in the JSON but have no test function, causing SEVERE silent failure at runtime.

---

## B. SYSTEM MAP

### Architecture Overview

```
runner.py (CLI entrypoint)
  ├── load_cases() → cases.json / cases_v2.json
  ├── run_all() → parallel/serial execution
  │   └── _run_one() → dispatch by condition:
  │       ├── run_single()  → [execution.py]
  │       │   ├── build_prompt() → [execution.py] → nudges/router.py, prompts.py, scm_prompts.py, reasoning_prompts.py
  │       │   ├── call_model() → [llm.py] → OpenAI API or llm_mock.py
  │       │   ├── parse_model_response() → [parse.py]
  │       │   ├── evaluate_output() → [evaluator.py]
  │       │   │   ├── exec_evaluate() → [exec_eval.py] (PRIMARY)
  │       │   │   │   ├── parse → extract code → load module → run invariant test → run mutation test
  │       │   │   │   ├── _CASE_TESTS dispatch table (V1 cases)
  │       │   │   │   └── _load_v2_test() dynamic loader (V2 cases → tests_v2/)
  │       │   │   ├── FALLBACK: _EVALUATORS dispatch → [eval_cases.py] (heuristic, SHOULD NOT RUN)
  │       │   │   ├── _detected_correct_reasoning() → reasoning signal detection
  │       │   │   └── compute_evidence_metrics() → SCM evidence scoring
  │       │   └── write_log() → [execution.py] → 3 JSONL files
  │       │
  │       ├── run_repair_loop() → [execution.py]
  │       │   └── 2-attempt loop with error feedback
  │       │
  │       ├── run_contract_gated() → [execution.py]
  │       │   ├── contract.py (parse_contract, build_contract_prompt)
  │       │   ├── diff_gate.py (validate: 6 structural checks)
  │       │   └── fallback: _fallback_run() on contract parse failure
  │       │
  │       └── run_retry_harness() → [retry_harness.py]
  │           ├── multi-iteration retry loop (max 5)
  │           ├── parse_structured_output() (strict JSON) + fallback to parse_model_response()
  │           ├── _safe_evaluate() → evaluate_output() wrapped in try/except
  │           ├── _call_critique() → LLM diagnosis of failure
  │           ├── failure_classifier.py → heuristic failure classification
  │           ├── leg_evaluator.py → LEG evaluation (post-hoc, gated)
  │           ├── trajectory analysis (dynamics, regime, metrics)
  │           └── _write_iteration_log() + _write_retry_summary()
  │
  └── print_results() → console output

ANALYSIS PIPELINE (post-hoc):
  scripts/leg_regime_analysis.py → reads JSONL logs, produces CSVs
  scripts/leg_ablation_analysis.py → reads CSVs, produces plots
  scripts/shadow_analysis.py → reads JSONL, comparison tables
  scripts/extract_metadata.py → log extraction
  scripts/extract_responses.py → response extraction

VALIDATION:
  preflight_check.py → pre-experiment case validation
  validate_cases_v2.py → v2 case validation pipeline

NUDGE SYSTEM:
  nudges/operators.py → NudgeOperator registry
  nudges/core.py → 13 operators (4 diagnostic, 4 guardrail, counterfactual, reason_then_act, self_check, counterfactual_check, test_driven)
  nudges/mapping.py → case→operator dispatch (14 cases mapped)
  nudges/router.py → condition→operator application
```

### Source Files (core orchestration)

| File | LOC | Role | Inputs | Outputs | Side Effects |
|------|-----|------|--------|---------|--------------|
| `runner.py` | 291 | CLI entrypoint, run orchestration | CLI args, cases JSON | Console output, return results | Calls init_run_log |
| `execution.py` | 378 | Single-run logic, prompt building, logging | Case dict, model, condition | (case_id, condition, eval) tuple | Writes 3 JSONL files |
| `retry_harness.py` | ~1400 | Retry loop with trajectory analysis | Case, model, config flags | (case_id, condition, eval) tuple | Writes JSONL logs, LLM calls |
| `evaluator.py` | 265 | Evaluation dispatcher | Case dict, raw output | Eval result dict | None |
| `exec_eval.py` | 758 | Execution-based evaluator | Case dict, raw output | Eval result dict | Module loading (sys.modules pollution) |
| `parse.py` | 428 | Response parsing | Raw LLM string | Parsed dict {reasoning, code, ...} | Logging warnings |
| `llm.py` | 68 | LLM call wrapper | Prompt, model name | Raw string response | API call |
| `contract.py` | 216 | CGE contract schema/parsing | Raw contract string | Contract dict | None |
| `diff_gate.py` | 520 | Contract validation | Contract, code, reference | Validation result | None |
| `failure_classifier.py` | 126 | Heuristic failure classification | Error obj, critique | Classification dict | None |
| `leg_evaluator.py` | 259 | LEG evaluation | Model, reasoning, code, error | LEG result dict | LLM call |
| `eval_cases.py` | 720+ | LEGACY heuristic evaluators | Case dict, raw output | Eval result dict | None |
| `prompts.py` | 230 | Base prompt construction | Task, code files | Prompt string | None |
| `scm_prompts.py` | 219 | SCM prompt builders | Base prompt, case_id | Prompt string | None |
| `scm_data.py` | 258 | SCM data registry | Case ID | SCM dict | None |
| `reasoning_prompts.py` | 53 | Reasoning prompt variants | Base prompt | Prompt string | None |

### Data Files

| File | Format | Role |
|------|--------|------|
| `cases.json` | JSON array | V1 benchmark cases (original) |
| `cases_v2.json` | JSON array | V2 benchmark cases (expanded) |
| `ablation_config.yaml` | YAML | Experiment configuration |
| `run_log.jsonl` | JSONL | Default log fallback |
| `run_prompts.jsonl` | JSONL | Default prompt log fallback |
| `run_responses.jsonl` | JSONL | Default response log fallback |

---

## C. SILENT FAILURE FINDINGS

### EVAL-01: ImportError Fallback Silently Switches Evaluation Strategy
- **Category:** CRITICAL silent fallback / masked evaluation change
- **Location:** `evaluator.py:235-241`
- **Expected behavior:** `exec_evaluate()` always runs; execution truth determines pass/fail
- **Actual risk:** If `exec_eval` import fails (even transiently — e.g., `parse.py` has a bug during import), the system silently falls back to `_EVALUATORS` text-matching heuristics from `eval_cases.py`. These produce completely different scores. A model that writes correct code but doesn't mention keywords may fail heuristically. A model that mentions correct keywords but writes wrong code may pass heuristically.
- **Why this is dangerous:** Entire experimental conclusions could be based on heuristic scores that don't measure what the experimenter thinks they measure. The paper says "execution-based evaluation" but the system silently ran text-matching.
- **Concrete trigger scenario:** Someone adds a bad import to `parse.py` during development. All evaluations silently switch to heuristic mode. Tests pass because they use mocks. Ablation runs on real data produce numbers that look normal but are from a completely different evaluation pipeline.
- **Detection rule:** `WARNING: exec_eval import failed — falling back to heuristic evaluation. THIS CHANGES THE EVALUATION METHOD.`
- **Required runtime action:** HARD FAIL. This should raise an exception, not fall back silently. If exec_eval can't import, the experiment CANNOT produce valid results.
- **Keep or Remove:** **REMOVE the fallback.** The `except ImportError` should be `except ImportError as e: raise RuntimeError(f"exec_eval import failed: {e}. Cannot run experiment without execution-based evaluation.") from e`
- **Proposed fix:** Replace lines 238-241 with a hard failure
- **Required tests:** Test that `evaluate_output` raises when `exec_eval` is not importable; test that it never silently uses heuristic evaluators

---

### LOG-01: Silent Log Write Failure
- **Category:** CRITICAL silent data loss
- **Location:** `execution.py:373-377`, `retry_harness.py:953-957`, `retry_harness.py:966-969`
- **Expected behavior:** If log writing fails, the experiment should know about it
- **Actual risk:** `except OSError: pass` silently swallows ALL log write failures. The experiment runs to completion, prints results to console, says "Log written: <path>" but the file may be empty, partial, or absent.
- **Why this is dangerous:** The ONLY reproducibility artifact is the log file. If it's silently not written, the experiment is unreproducible and the data is lost. The console output is insufficient for analysis.
- **Concrete trigger scenario:** Disk full. Permissions wrong. NFS mount dropped. Path doesn't exist after cleanup.
- **Detection rule:** Count log writes attempted vs succeeded. At end of run, verify file exists and has expected number of entries.
- **Required runtime action:** First failure: WARNING + continue. Track failure count. At end: if any failures, print PROMINENT warning with count. Consider buffering and retrying.
- **Keep or Remove:** **KEEP the try/except** (don't crash the experiment) but **ADD tracking and warning**
- **Proposed fix:** Add `_log_write_failures` counter; print summary at end of run
- **Required tests:** Test that log write failure is tracked and reported

---

### PARSE-01: Raw Fallback Treats Full Response as Code
- **Category:** Silent semantic corruption
- **Location:** `parse.py:198-209`
- **Expected behavior:** When parsing fails completely, the system should flag the response as unusable
- **Actual risk:** The entire raw LLM response (including English reasoning) becomes the "code" field. `exec_eval` then tries to `exec()` this, gets a SyntaxError on English text, and reports a "syntax error." The experimenter sees "syntax error" and thinks the model wrote bad Python, when actually the model may have written perfect code wrapped in explanation that the parser couldn't extract.
- **Why this is dangerous:** Misattributes parsing failures as model code quality failures. Inflates syntax error rates. May cause false negatives in research conclusions.
- **Concrete trigger scenario:** Model returns perfectly correct code but wraps it in `Here is the fixed code:` before and `This fixes the issue by...` after, with no markdown code blocks. Parser can't extract it. Entire text becomes "code." SyntaxError. Scored 0.0.
- **Detection rule:** Check if "code" field contains common natural language indicators (multiple sentences, no `def`/`class` keywords, high ratio of spaces to code characters)
- **Required runtime action:** Warning already exists. But the downstream eval should check `parse_error` and mark the result as `degraded` when raw fallback was used.
- **Keep or Remove:** **KEEP** the raw fallback (it's the last resort) but **ADD** a degraded-result flag
- **Proposed fix:** Add `"_raw_fallback": True` to the result; exec_eval should check this flag
- **Required tests:** Test that raw fallback result is flagged; test that downstream eval acknowledges it

---

### COND-01: Duplicate Condition Label
- **Category:** Data corruption / silent conflation
- **Location:** `runner.py:44,51`
- **Expected behavior:** Each condition has a unique label
- **Actual risk:** `COND_LABELS` maps both `reason_then_act` and `retry_adaptive` to `"RA"`. In `print_results`, column headers use these labels, so the two conditions share a column header. Any CSV/analysis that uses labels to identify conditions will conflate them.
- **Why this is dangerous:** Research conclusions may attribute retry_adaptive results to reason_then_act or vice versa
- **Concrete trigger scenario:** Run both conditions simultaneously. Results table has two "RA" columns. Analysis code groups by label, merging the data.
- **Detection rule:** `assert len(set(COND_LABELS.values())) == len(COND_LABELS)` at import time
- **Required runtime action:** Fix the label. `retry_adaptive` should be `"RD"` or `"AD"`
- **Keep or Remove:** **FIX** — change the duplicate label
- **Proposed fix:** Change `runner.py:51` `"retry_adaptive": "RA"` to `"retry_adaptive": "AD"`
- **Required tests:** Add assertion that labels are unique

---

### EVAL-02: Heuristic Evaluator Can Score on Raw Fallback Code
- **Category:** Metric computed on invalid input
- **Location:** `eval_cases.py` (all evaluators), `evaluator.py:240-241`
- **Expected behavior:** Heuristic evaluators score model output text
- **Actual risk:** If exec_eval import fails AND parser used raw fallback, the heuristic evaluator receives the full response text as "output." Since heuristic evaluators look for keyword patterns, they may find positive signals in the model's reasoning text and produce a passing score — even though the code was never extracted or evaluated.
- **Why this is dangerous:** False positive: model "passes" because its English explanation mentions the right keywords, not because it wrote correct code
- **Concrete trigger scenario:** Model writes correct reasoning but wrong code. Heuristic evaluator sees keywords in reasoning. Reports PASS. exec_eval would have caught the bug via execution.
- **Detection rule:** If evaluation path was heuristic (not exec_eval), flag result as `evaluation_method: "heuristic"` and warn
- **Required runtime action:** Hard fail (see EVAL-01)
- **Keep or Remove:** **REMOVE** the fallback entirely
- **Proposed fix:** Same as EVAL-01
- **Required tests:** Same as EVAL-01

---

### RETRY-01: _safe_evaluate Masks Evaluator Crashes
- **Category:** Error swallowing / masked failure
- **Location:** `retry_harness.py:774-796`
- **Expected behavior:** `evaluate_output` should always produce a valid result for valid input
- **Actual risk:** `_safe_evaluate` catches ALL exceptions from `evaluate_output` and returns a synthetic failure result. The trajectory records this as a normal failure (score 0.0, "evaluator_error") which is indistinguishable from a genuine model failure. The model gets penalized for an evaluator bug.
- **Why this is dangerous:** Evaluator bugs become invisible. The model appears to produce wrong code when actually the evaluator crashed. Trajectory analysis treats this as a real failure pattern.
- **Concrete trigger scenario:** `exec_eval.py` has a bug in one specific test function. That case always gets `score: 0.0` in retry trajectory. Looks like a hard case. Actually it's a test bug.
- **Detection rule:** If `_safe_evaluate` catches, the trajectory entry should have `"_evaluator_crash": True` and the reason should be prominently prefixed with `EVALUATOR_ERROR:`
- **Required runtime action:** Log at ERROR level (already done). But also mark the entry distinctly. Analysis code should filter these.
- **Keep or Remove:** **KEEP** (don't crash the retry loop) but **HARDEN** the entry marking
- **Proposed fix:** Add `"_evaluator_crash": True` field; analysis scripts filter on it
- **Required tests:** Test that evaluator crash is distinguishable from model failure

---

### RETRY-02: Critique Parse Failure Returns Plausible-Looking Dict
- **Category:** Silent schema forgery
- **Location:** `retry_harness.py:832-837`
- **Expected behavior:** When critique JSON parsing fails, the system knows the critique is invalid
- **Actual risk:** On parse failure, `_call_critique` returns `{"failure_type": "unknown", "root_cause": "unparseable", ..., "_valid": False}`. The `_valid: False` field exists, but downstream code checks `critique.get("_valid", True)` with a default of `True`. In `failure_classifier.py:65`: `if critique and critique.get("_valid", True) and critique.get("_valid") is not False:` — this complex condition is correct but fragile. Any caller that checks `critique.get("_valid")` without the `is not False` guard gets `False` (truthy check on False = falsy, correct). But the returned dict has real-looking data ("unknown", "unparseable") that could be used if `_valid` is not checked.
- **Why this is dangerous:** If a new code path accesses `critique["root_cause"]` without checking `_valid`, it gets "unparseable" as if it were a real root cause analysis.
- **Concrete trigger scenario:** New analysis code reads critiques from logs, doesn't filter on `_valid`, counts "unparseable" as a frequent root cause.
- **Detection rule:** All code paths that access critique fields should first check `_valid`. Enforcement: grep for `critique.get("root_cause")` without nearby `_valid` check.
- **Required runtime action:** The dict should be clearly marked. Consider returning `None` instead and having callers handle None.
- **Keep or Remove:** **KEEP** but **HARDEN** — consider `_valid` as a top-level filter before any field access
- **Proposed fix:** Document contract; add assertion helper `ensure_valid_critique(c)`
- **Required tests:** Test that invalid critique data is never used in classification or analysis

---

### NUDGE-01: Missing Case in Nudge Mapping Falls Back Silently to Base Prompt
- **Category:** Silent no-op / missing intervention
- **Location:** `nudges/router.py:14-68` (all `apply_*` functions)
- **Expected behavior:** Every case that runs under a nudge condition gets the appropriate nudge applied
- **Actual risk:** If a case_id is not in `CASE_TO_OPERATORS` (mapping.py:23-61), `get_operators_for_case()` returns `None`, and the router function returns the base prompt unmodified (for diagnostic/guardrail) or applies the generic operator (for counterfactual etc). The case runs as if it were baseline, but the condition is logged as "diagnostic" or "guardrail." The experimenter thinks the nudge was applied.
- **Why this is dangerous:** V2 cases (29+ case IDs like `alias_config_a`, `early_return_b`, etc.) are NOT in the mapping. They will silently get baseline treatment under nudge conditions. This means experimental results for nudge conditions on V2 cases are actually baseline results.
- **Concrete trigger scenario:** Run `--conditions diagnostic --cases cases_v2.json`. All V2 cases get baseline prompt. Results show "diagnostic has no effect on V2 cases." True, because it was never applied.
- **Detection rule:** At case load time, verify every case_id is in CASE_TO_OPERATORS for the requested conditions. If not, warn: `WARNING: case {id} has no operator mapping for {condition} — using base prompt`
- **Required runtime action:** WARNING for each unmapped case. Mark result as `"operator_applied": False` vs `"operator_applied": True`
- **Keep or Remove:** **KEEP** the fallback behavior (it's correct for generic operators) but **ADD WARNING** when diagnostic/guardrail fall through
- **Proposed fix:** Add logging in router.py when assignment is None for case-specific conditions
- **Required tests:** Test that unmapped case produces warning and marks operator_applied=False

---

### CASE-01: V1/V2 Case Test Resolution is Fragile
- **Category:** Silent test absence / false failure
- **Location:** `exec_eval.py:680-697`
- **Expected behavior:** Every case has exactly one test function that is found reliably
- **Actual risk:** Test resolution: first checks `_CASE_TESTS` dict, then `_load_v2_test()`. V2 loader requires `case["family"]` and `case["difficulty"]` fields. If either is missing, returns `None`. If the test file exists but the function name doesn't match (e.g., `test_a` vs `test_easy`), returns `None`. The case then gets logged as SEVERE and scored 0.0 — attributed to model failure but it's actually a pipeline bug.
- **Why this is dangerous:** The SEVERE log exists but is at ERROR level which may not be visible in a noisy parallel run. The case appears as a hard failure. If the experimenter doesn't check logs, they may draw wrong conclusions about model capability.
- **Concrete trigger scenario:** Add a new V2 case, forget to add the difficulty field. Case loads fine from JSON. Prompt goes out. Model responds. Eval scores 0.0. Looks like the model failed. Actually no test was run.
- **Detection rule:** Preflight check (preflight_check.py) DOES check this. But it only checks the cases file, not the runtime dispatch path. And it's optional — not enforced before experiments.
- **Required runtime action:** The SEVERE log is good. But also: add a summary at end of run showing any cases with "no_test_found" failures.
- **Keep or Remove:** **KEEP** but **INTEGRATE preflight check as mandatory** before any experiment run
- **Proposed fix:** runner.py should call preflight_check before starting experiment
- **Required tests:** Test that missing family/difficulty fields cause clear failure

---

### LOG-02: Log Fallback to Default Files Without Warning
- **Category:** Silent data clobbering
- **Location:** `execution.py:364-366`, `retry_harness.py:947-949`
- **Expected behavior:** Logs go to per-run timestamped files
- **Actual risk:** If `init_run_log()` was never called (e.g., in tests or when imported by scripts), `_current_log_path` is `None`, and logs silently fall back to `run_log.jsonl`, `run_prompts.jsonl`, `run_responses.jsonl` in the project root. These files accumulate data from multiple runs without timestamps, making data attribution impossible.
- **Why this is dangerous:** Data from different experiments gets mixed. No way to tell which entries came from which run.
- **Concrete trigger scenario:** Script imports `execution.py` and calls `run_single()` without calling `init_run_log()` first. Results go to the default files, mixed with whatever was already there.
- **Detection rule:** If `_current_log_path is None` when `write_log` is called, warn: `WARNING: write_log called without init_run_log — writing to default fallback`
- **Required runtime action:** WARNING on first fallback write. Add run_id to fallback records.
- **Keep or Remove:** **KEEP** fallback (for tests) but **ADD WARNING**
- **Proposed fix:** Add logging when fallback is used; add `"_fallback_log": True` field
- **Required tests:** Test that fallback logging produces a warning

---

### PARSE-02: Lenient JSON Parser Silently Extracts from Malformed JSON
- **Category:** Silent data corruption risk
- **Location:** `parse.py:78-118`
- **Expected behavior:** JSON parsing is strict; malformed JSON is rejected
- **Actual risk:** `_try_json_lenient` uses regex to extract code from malformed JSON. It handles unescaped newlines but could extract partial code if the regex greedily matches. The regex `"code"\s*:\s*"(.*)"` with `re.DOTALL` may capture content across field boundaries.
- **Why this is dangerous:** Could extract truncated code or code with artifacts from other JSON fields
- **Concrete trigger scenario:** Model returns `{"reasoning": "fix by...", "code": "def f():\n    pass", "confidence": 0.9}` — the regex may or may not correctly delimit the code field depending on quote escaping
- **Detection rule:** When lenient parser is used, compare extracted code length vs expected. The warning at line 106-109 exists but doesn't validate content.
- **Required runtime action:** Existing warning is adequate. Add `parse_tier: "lenient"` to parsed result.
- **Keep or Remove:** **KEEP** (it recovers valid data in many cases) but mark tier
- **Proposed fix:** Add `"parse_tier"` field to all parse results
- **Required tests:** Test lenient parser with adversarial inputs (nested quotes, multi-field JSON)

---

### CONTRACT-01: Contract Parse Failure Triggers Fallback Run
- **Category:** Silent degradation of experimental condition
- **Location:** `execution.py:184-188`
- **Expected behavior:** `contract_gated` condition uses contract→generate→gate→eval flow
- **Actual risk:** If `parse_contract()` returns `None`, `_fallback_run()` is called which does a STANDARD single-shot evaluation against the contract elicitation prompt output (not even a code generation prompt). The result is logged as condition="contract_gated" but the CGE pipeline never ran.
- **Why this is dangerous:** Results for "contract_gated" include both real CGE runs and fallback single-shot runs. Average scores mix the two. The experimenter thinks all cases went through CGE.
- **Concrete trigger scenario:** Model outputs contract as prose instead of JSON. parse_contract returns None. Fallback evaluates the prose as code. Gets 0.0. Looks like CGE failed. Actually CGE never happened.
- **Detection rule:** `ev["contract"] is None` and `ev["contract_parse_error"]` already distinguish this. But no warning is printed.
- **Required runtime action:** WARNING at the log message. Mark result clearly as `"cge_executed": False`
- **Keep or Remove:** **KEEP** the fallback (graceful degradation) but **ADD explicit marking**
- **Proposed fix:** Add `"cge_executed"` boolean field; warn prominently
- **Required tests:** Test that contract parse failure produces cge_executed=False

---

### GATE-01: Diff Gate Skips Unresolvable Orderings Silently
- **Category:** Silent validation weakening
- **Location:** `diff_gate.py:296-297`
- **Expected behavior:** If an ordering constraint can't be checked, the validation result should reflect this
- **Actual risk:** When anchor lines are not found (`if not anchor_lines: continue`), the ordering check is silently skipped. The contract may declare "effect A must happen after B" but if B is not found in code, the check passes. The validation result shows `valid: True` even though a key constraint was not verified.
- **Why this is dangerous:** The gate may report "all checks passed" when critical constraints were actually unresolvable
- **Concrete trigger scenario:** Model renames a function. Contract references old name. Gate can't find anchor. Skips check. Reports valid.
- **Detection rule:** Track `unresolvable_checks` count in validation result
- **Required runtime action:** Add `"unresolvable_checks"` field to validation result; if > 0, mark as `"partial_validation"`
- **Keep or Remove:** **KEEP** (can't validate what can't be found) but **ADD tracking**
- **Proposed fix:** Add counter for skipped checks in validate()
- **Required tests:** Test that unresolvable checks are counted

---

### EVAL-03: Evidence Metrics Return Zeros for Non-SCM Cases
- **Category:** Schema padding / misleading defaults
- **Location:** `evaluator.py:96-103`
- **Expected behavior:** Non-SCM cases have no evidence metrics
- **Actual risk:** `compute_evidence_metrics()` returns a full dict of zeros for non-SCM cases. These zeros are indistinguishable from "SCM case with zero evidence usage." Analysis code that computes averages across all cases will include these zeros, diluting real SCM metrics.
- **Why this is dangerous:** Average evidence_usage_score will be lower than actual because non-SCM cases contribute zeros
- **Concrete trigger scenario:** Analysis computes mean evidence_usage_score across all 30+ cases. 25 non-SCM cases contribute 0. Mean is pulled toward 0.
- **Detection rule:** Analysis code must filter on `case in SCM_CASES` before computing evidence metrics
- **Required runtime action:** Return `None` values instead of zeros, or add `"has_scm": False` flag
- **Keep or Remove:** **KEEP** but **CHANGE defaults to None** so analysis code must handle them explicitly
- **Proposed fix:** Change default returns to `None` instead of `0`
- **Required tests:** Test that non-SCM case evidence metrics are distinguishable from SCM case with zero usage

---

### RETRY-03: LEG Evaluation Gated by use_llm_eval=False Default
- **Category:** Feature silently disabled
- **Location:** `retry_harness.py:978,1284-1285`
- **Expected behavior:** LEG evaluation runs during retry harness execution
- **Actual risk:** `use_llm_eval` defaults to `False`. Runner.py calls `run_retry_harness()` without passing `use_llm_eval=True`. So LEG evaluation NEVER runs in the standard experiment flow. All LEG-related fields in trajectory entries are set to `None`/`False`. Any analysis that examines LEG metrics from standard ablation runs will find all zeros.
- **Why this is dangerous:** The LEG evaluator exists, has tests, but is never activated. Researcher may expect LEG data from runs and find none. Or analysis code may compute LEG rates from all-False data and report 0%.
- **Concrete trigger scenario:** Run ablation with `retry_with_contract`. Check LEG metrics. All zeros. Think LEG is 0%. Actually LEG was never computed.
- **Detection rule:** Log at start of retry harness: `"LEG evaluation: {'ENABLED' if use_llm_eval else 'DISABLED (pass use_llm_eval=True to enable)'}"`
- **Required runtime action:** INFO log stating whether LEG is active
- **Keep or Remove:** **KEEP** the default (LEG requires extra API calls, expensive) but **WARN** when LEG data fields are present but empty
- **Proposed fix:** Add info log at retry harness start; add `"leg_evaluation_active"` boolean to summary
- **Required tests:** Test that LEG fields are populated when use_llm_eval=True and empty when False

---

### SCHEMA-01: Runner Result Assembly Uses .get() with Defaults Everywhere
- **Category:** Default values masking missing fields
- **Location:** `runner.py:170-181`
- **Expected behavior:** All eval result fields are populated by evaluate_output
- **Actual risk:** Every field in the result assembly uses `.get(field, default)`. If `evaluate_output` fails to populate a field (e.g., `identified_correct_issue` is missing because reasoning detection didn't run), the default `False` is silently used. This masks the difference between "checked and found false" vs "never checked."
- **Why this is dangerous:** Analysis code can't distinguish "model didn't identify the issue" from "reasoning analysis was never performed"
- **Concrete trigger scenario:** Bug in `_detected_correct_reasoning` causes it to not run for certain failure_modes. Result silently defaults to `False`. Looks like models never identify those issues. Actually the check was broken.
- **Detection rule:** Assert that all expected fields are present after evaluate_output
- **Required runtime action:** Add validation: if any expected field is missing, warn
- **Keep or Remove:** **KEEP** the .get() pattern (for robustness) but **ADD** explicit field presence validation
- **Proposed fix:** Add `_validate_eval_result(ev)` function that checks required fields
- **Required tests:** Test that missing eval fields produce warnings

---

### CONFIG-01: YAML Parser Fallback in run_ablation_config.py
- **Category:** Silent behavior change based on environment
- **Location:** `scripts/run_ablation_config.py:13-41`
- **Expected behavior:** YAML config is parsed correctly
- **Actual risk:** If `pyyaml` is not installed, `yaml = None` and a hand-rolled line parser is used. This fallback parser uses fragile string splitting (`line.split(":")[1]`) that will break on values containing colons, and it doesn't handle nested keys, indentation, or multi-line values.
- **Why this is dangerous:** Experiment config may be silently wrong. Different environments (local vs CI) may produce different behavior.
- **Concrete trigger scenario:** Config value contains a colon (e.g., `name: "retry:v2"`). Fallback parser splits on first colon, gets `"retry` as value. Experiment runs with wrong name.
- **Detection rule:** If yaml is None, print WARNING and suggest `pip install pyyaml`
- **Required runtime action:** WARNING on fallback parser use
- **Keep or Remove:** **REMOVE** the fallback parser. Require pyyaml.
- **Proposed fix:** `if yaml is None: raise ImportError("pyyaml required: pip install pyyaml")`
- **Required tests:** Test that import error is raised when yaml is not available

---

### SHADOW-01: shadow_analysis.py Has Syntax Error
- **Category:** Dead code / broken script
- **Location:** `scripts/shadow_analysis.py:13`
- **Expected behavior:** Script is runnable
- **Actual risk:** Line 13: `import from collections import Counter, defaultdict` — this is a syntax error. The script cannot be imported or executed.
- **Why this is dangerous:** Analysis capability is silently broken. Anyone trying to run shadow analysis gets an import error.
- **Concrete trigger scenario:** `python scripts/shadow_analysis.py logs/...` → SyntaxError
- **Detection rule:** Import test / syntax check on all scripts
- **Required runtime action:** Fix the syntax error
- **Keep or Remove:** **FIX** if used, **REMOVE** if not
- **Proposed fix:** Change to `from collections import Counter, defaultdict`
- **Required tests:** Add import test for all scripts

---

### EXEC-01: sys.modules Pollution from Module Loading
- **Category:** Potential cross-contamination
- **Location:** `exec_eval.py:51`
- **Expected behavior:** Each module load is isolated
- **Actual risk:** `sys.modules[mod_name] = mod` adds every loaded candidate module to `sys.modules`. With unique names (`_t3_exec_{name}_{counter}`), this is mostly safe. But if two evaluations of the same case_id run in parallel (ThreadPoolExecutor in runner.py), the counter is not thread-safe (`global _load_counter` with `_load_counter += 1` is a race condition).
- **Why this is dangerous:** In parallel execution, two threads could get the same counter value, producing the same module name, and one module could overwrite another in `sys.modules`.
- **Concrete trigger scenario:** `--parallel 8` with many cases. Two threads increment `_load_counter` simultaneously. Same mod_name. One thread's module overwrites the other's in sys.modules.
- **Detection rule:** Use `threading.Lock` or `itertools.count()` (atomic on CPython)
- **Required runtime action:** Make counter thread-safe
- **Keep or Remove:** **FIX**
- **Proposed fix:** Replace `_load_counter` with `itertools.count()` or add a lock
- **Required tests:** Test parallel module loading doesn't produce name collisions

---

### VALIDATE-01: validate_cases_v2.py Dead Code Branch
- **Category:** Dead code
- **Location:** `validate_cases_v2.py:45`
- **Expected behavior:** N/A
- **Actual risk:** Line 45: `elif stripped.startswith("import ") and not stripped.startswith("import "):` — this condition is always False (both operands are the same). The `pass` on line 46 never executes. This is a no-op dead branch.
- **Why this is dangerous:** Not directly dangerous, but indicates a copy-paste error. The intent was probably to handle bare `import X` statements differently from `from X import Y`. As written, all bare imports are passed through unfiltered.
- **Concrete trigger scenario:** Case code has `import some_local_module`. This import is NOT stripped. Module loading fails because `some_local_module` doesn't exist.
- **Detection rule:** Static analysis / linting
- **Required runtime action:** Fix or remove the dead branch
- **Keep or Remove:** **FIX** the condition
- **Proposed fix:** Remove the dead `elif` or fix to `elif stripped.startswith("import ") and not any(stripped.startswith(f"import {m}") for m in _STDLIB):`
- **Required tests:** Test that bare local imports are stripped

---

### EVAL-04: Compute Alignment Uses Nested .get() on Potentially Missing Execution Dict
- **Category:** Default value masking missing execution data
- **Location:** `execution.py:111-113`
- **Expected behavior:** Alignment uses real execution status
- **Actual risk:** `ev.get("execution", {}).get("status", "failed")` — if `execution` key is missing entirely, defaults to empty dict, then status defaults to "failed". This means alignment computation silently uses `"failed"` even when execution was never attempted. The alignment_type will be "aligned_failure" or "reasoning_correct_execution_failed" even though no execution happened.
- **Why this is dangerous:** Alignment metrics are corrupted by never-executed cases
- **Concrete trigger scenario:** Edge case where evaluate_output returns a result without "execution" key (e.g., from a code path that was added but forgot the execution field)
- **Detection rule:** Validate that ev["execution"]["status"] is always present after evaluation
- **Required runtime action:** Warning if execution is missing
- **Keep or Remove:** **KEEP** with validation
- **Proposed fix:** Add assertion/warning when execution key is missing
- **Required tests:** Test that missing execution key is detected

---

### MOCK-01: Mock Fallback Activates Without Warning
- **Category:** Silent mode switch
- **Location:** `llm.py:43-45`
- **Expected behavior:** When API key is present, real API is used; when missing, mock is used with CLEAR indication
- **Actual risk:** If `OPENAI_API_KEY` is unset or is `"sk-dummy"`, `mock_call` is used silently. The experiment runs with fake model outputs. Results look real.
- **Why this is dangerous:** If someone accidentally unsets their API key and runs an experiment, they get mock results that look like real model outputs. They may publish these.
- **Concrete trigger scenario:** CI/CD environment doesn't have API key set. Ablation runs. All cases get mock responses. Results written to logs. Look normal.
- **Detection rule:** `init_run_log` should record `"api_mode": "mock"` or `"api_mode": "live"` in the log. Console should print prominently: `WARNING: Running with MOCK model (no API key). Results are NOT from a real model.`
- **Required runtime action:** PROMINENT console warning + log field
- **Keep or Remove:** **KEEP** (needed for tests) but **ADD WARNING** in non-test contexts
- **Proposed fix:** Print warning when mock mode is activated in runner.py
- **Required tests:** Test that mock mode produces warning

---

### LLM-01: API Response Structure Not Validated
- **Category:** Contract drift with external API
- **Location:** `llm.py:66-67`
- **Expected behavior:** `response.output_text` always returns a string
- **Actual risk:** Uses OpenAI's `client.responses.create()` API. If the API changes (field renamed, structure changed, None returned), the code will crash or silently produce empty strings. No validation on `response.output_text` type or content.
- **Why this is dangerous:** API changes could silently corrupt all experiment outputs
- **Concrete trigger scenario:** OpenAI deprecates `output_text` field. Returns `None`. `call_model` returns `None`. `parse_model_response(None)` → empty response → raw fallback → everything scores 0.
- **Detection rule:** Validate that `response.output_text` is a non-empty string
- **Required runtime action:** Raise ValueError if response is empty or not a string
- **Keep or Remove:** **ADD** validation
- **Proposed fix:** Add `if not isinstance(result, str) or not result.strip(): raise ValueError(...)`
- **Required tests:** Test that empty API response raises ValueError

---

## D. WARNING / ASSERTION HARDENING PLAN

### Severity Levels

| Level | Meaning | Action |
|-------|---------|--------|
| **FATAL** | Experiment cannot produce valid results | Raise exception. Stop run. |
| **SEVERE** | Data for this case/condition is invalid | Mark result as invalid. Continue run. Print at end. |
| **WARNING** | Data may be degraded | Log prominently. Continue run. |
| **INFO** | Notable but not concerning | Log at debug level. |

### Warning Strategy

#### FATAL Warnings (must raise)

| ID | Condition | Message | Location |
|----|-----------|---------|----------|
| W-FATAL-01 | exec_eval import fails | `FATAL: exec_eval import failed: {e}. Cannot run experiment without execution-based evaluation.` | evaluator.py:238 |
| W-FATAL-02 | No test found for case | Already exists as SEVERE log. Promote to FATAL. | exec_eval.py:686-697 |
| W-FATAL-03 | YAML parser unavailable | `FATAL: pyyaml not installed. Cannot parse config.` | scripts/run_ablation_config.py |

#### SEVERE Warnings (mark result invalid)

| ID | Condition | Message | Action |
|----|-----------|---------|--------|
| W-SEV-01 | Raw fallback used in parse | `SEVERE: parser used raw fallback for {case_id}/{condition}. Code may include non-code text.` | Mark `_parse_degraded: True` |
| W-SEV-02 | Contract parse failed in CGE | `SEVERE: contract parse failed for {case_id}. CGE not executed.` | Mark `cge_executed: False` |
| W-SEV-03 | Evaluator crashed in retry | `SEVERE: evaluator crashed for {case_id} iter {k}: {e}` | Mark `_evaluator_crash: True` |
| W-SEV-04 | Parse divergence detected | Already exists. | Already logged. |

#### WARNING Warnings (data may be degraded)

| ID | Condition | Message | Action |
|----|-----------|---------|--------|
| W-WARN-01 | Log write failed | `WARNING: failed to write log entry for {case_id}/{condition}: {e}` | Track count, report at end |
| W-WARN-02 | Case has no nudge mapping | `WARNING: case {id} has no operator mapping for condition {cond} — using base prompt` | Mark `operator_applied: False` |
| W-WARN-03 | Mock mode active | `WARNING: Running with MOCK model (no API key). Results are NOT from a real model.` | Print once at start |
| W-WARN-04 | LEG evaluation disabled | `WARNING: LEG evaluation disabled (use_llm_eval=False). LEG metrics will be empty.` | Print at retry start |
| W-WARN-05 | Gate validation partial | `WARNING: {n} ordering constraints unresolvable for {case_id}` | Mark `partial_validation: True` |
| W-WARN-06 | Fallback log path used | `WARNING: write_log called without init_run_log — using fallback path` | Log once |
| W-WARN-07 | Critique parse failed | `WARNING: critique parse failed for {case_id} iter {k} — using invalid marker` | Already handled via _valid |

---

## E. KEEP / REMOVE CLASSIFICATION

### REMOVE

| Item | Location | Reason |
|------|----------|--------|
| `except ImportError` fallback to heuristics | evaluator.py:238-241 | Creates invisible evaluation method switch. exec_eval must be required. |
| YAML fallback parser | scripts/run_ablation_config.py:22-41 | Fragile, incomplete. Require pyyaml. |
| Dead `elif` branch | validate_cases_v2.py:45-46 | Always-false condition, copy-paste error |
| Broken shadow_analysis.py | scripts/shadow_analysis.py:13 | Syntax error makes script unusable. Fix or remove. |
| `except OSError: pass` (bare) | execution.py:376-377, retry_harness.py:956-957 | REPLACE with tracking, not remove entirely |

### KEEP (with hardening)

| Item | Location | Reason |
|------|----------|--------|
| Raw fallback in parse.py | parse.py:198-209 | Last resort needed, but must flag result |
| _safe_evaluate wrapper | retry_harness.py:774-796 | Don't crash retry loop, but mark crashes distinctly |
| Contract parse fallback | execution.py:184-188 | Graceful degradation, but must mark clearly |
| eval_cases.py heuristic evaluators | eval_cases.py | After removing the ImportError fallback, these become unreachable from production. KEEP for reference/testing but ensure they are NEVER called in production eval. |
| Log fallback paths | execution.py:364-366 | Needed for tests, but warn in production |
| Mock LLM fallback | llm.py:43-45 | Needed for tests, but warn in production runner |
| Nudge router fallback to base prompt | nudges/router.py | Correct for generic operators, but warn for case-specific ones |
| Backward-compat aliases in runner.py | runner.py:85-87 | Harmless, used by tests |
| Evidence metrics zeros for non-SCM | evaluator.py:96-103 | Change to None values |

### PROVISIONALLY REMOVE

| Item | Condition |
|------|-----------|
| eval_cases.py | Remove if confirmed that no analysis script or notebook imports from it directly. Check: `grep -r "from eval_cases import\|import eval_cases" --include="*.py"` |

---

## F. TEST COVERAGE GAP AUDIT

### Current Test Coverage Map

| Test File | What It Tests | Coverage Level |
|-----------|--------------|----------------|
| test_parse.py | parse_model_response: 3 tiers + empty + SEVERE | Good for happy path, weak on adversarial |
| test_nudges.py | Operator registration, apply functions, mapping | Comprehensive for nudge system |
| test_conditions_exist.py | All 22+ conditions produce non-empty prompts | Structural only — doesn't verify prompt content |
| test_prompt_modification.py | Diagnostic/guardrail modify base prompt | Shallow — checks length only |
| test_execution_runs.py | Module loading, exec_evaluate | Basic coverage |
| test_repair_loop.py | 2-attempt repair loop | Happy path only |
| test_backward_compatibility.py | Legacy imports still work | Structural |
| test_result_structure.py | Eval result has required fields | Good structural test |
| test_integration.py | Full pipeline: prompt → eval for all conditions | Good but uses mocks |
| test_scm.py | SCM prompts, evidence scoring | Comprehensive |
| test_easy_cases.py | Easy calibration cases pass/fail correctly | Comprehensive |
| test_contract_gated.py | CGE: contract parse, gate, retry, full flow | Comprehensive |
| test_retry_harness.py | Retry: convergence, stagnation, trajectory | Very comprehensive |
| test_eval_integration.py | exec_eval for each case type | Good case-by-case coverage |
| test_all_conditions.py | Each condition+case doesn't crash | Smoke test only |
| test_failure_classifier.py | Classification rules, priority ordering | Good |
| test_failure_suite.py | Systematic failure scenarios for each case | Comprehensive |
| test_invariants.py | Invariant tests pass on reference, fail on buggy | Good |
| test_leg_evaluator.py | LEG parser, evaluator, bias, LEG_true | Good |
| test_v2_bridge.py | V2 case loading, test dispatch | Moderate |

### CRITICAL GAPS

#### GAP-P0-01: No test for evaluator.py ImportError fallback
- **Subsystem:** evaluator.py
- **Missing behavior:** What happens when exec_eval can't be imported
- **Failure mode caught:** Silent switch to heuristic evaluation
- **Why untested:** Probably considered an edge case
- **Recommended test:** Integration test that patches `exec_eval` import to fail and verifies RuntimeError is raised (after fix)
- **Priority:** P0

#### GAP-P0-02: No test for log write failure handling
- **Subsystem:** execution.py, retry_harness.py
- **Missing behavior:** What happens when log file can't be written
- **Failure mode caught:** Silent data loss
- **Why untested:** OSError is hard to simulate in tests
- **Recommended test:** Mock open() to raise OSError; verify warning is logged and failure is tracked
- **Priority:** P0

#### GAP-P0-03: No test for parallel execution race conditions
- **Subsystem:** exec_eval.py (_load_counter), runner.py (ThreadPoolExecutor)
- **Missing behavior:** Thread safety of module loading
- **Failure mode caught:** Module name collision in sys.modules
- **Why untested:** Race conditions hard to test deterministically
- **Recommended test:** Property test: run 100 parallel module loads, assert all unique names
- **Priority:** P0

#### GAP-P0-04: No test for case-test-mapping completeness
- **Subsystem:** exec_eval.py (_CASE_TESTS + _load_v2_test), cases_v2.json
- **Missing behavior:** Every case in the JSON file resolves to a test function
- **Failure mode caught:** Case scored 0.0 due to missing test (not model failure)
- **Why untested:** Dynamic, would need to load all cases and resolve tests
- **Recommended test:** Load cases_v2.json, for each case, verify _CASE_TESTS or _load_v2_test returns non-None
- **Priority:** P0

#### GAP-P1-01: No test for mock mode detection/warning
- **Subsystem:** llm.py
- **Missing behavior:** Warning when mock mode activates in production context
- **Failure mode caught:** Experiment runs with mock data unknowingly
- **Recommended test:** Set OPENAI_API_KEY="" and verify warning is produced
- **Priority:** P1

#### GAP-P1-02: No test for nudge operator mapping completeness
- **Subsystem:** nudges/mapping.py
- **Missing behavior:** V2 cases with no mapping get base prompt under nudge conditions
- **Failure mode caught:** Silent no-op nudge application
- **Recommended test:** For each case in cases_v2.json, check if in CASE_TO_OPERATORS; log uncovered cases
- **Priority:** P1

#### GAP-P1-03: No malformed JSON adversarial tests for parse.py
- **Subsystem:** parse.py
- **Missing behavior:** Parser behavior on adversarial inputs (deeply nested JSON, unicode escapes, null bytes, very large responses)
- **Failure mode caught:** Parser crash or incorrect extraction
- **Recommended test:** Fixture-based test with 20+ adversarial parse inputs
- **Priority:** P1

#### GAP-P1-04: No test for diff_gate unresolvable constraints
- **Subsystem:** diff_gate.py
- **Missing behavior:** What happens when contract references functions not in code
- **Failure mode caught:** Silent skipping of validation checks
- **Recommended test:** Contract with must_change pointing to nonexistent function; verify unresolvable check count
- **Priority:** P1

#### GAP-P1-05: No test for retry harness timeout behavior
- **Subsystem:** retry_harness.py
- **Missing behavior:** What happens when MAX_TOTAL_SECONDS is exceeded
- **Failure mode caught:** Loop exits with ev=None, synthetic error result
- **Recommended test:** Mock time.monotonic to simulate timeout; verify graceful handling
- **Priority:** P1

#### GAP-P1-06: No test for evidence metrics with non-SCM cases
- **Subsystem:** evaluator.py
- **Missing behavior:** Verify evidence metrics don't pollute analysis for non-SCM cases
- **Failure mode caught:** Zero-diluted averages
- **Recommended test:** Call compute_evidence_metrics on non-SCM case; verify result can be filtered
- **Priority:** P1

#### GAP-P2-01: No golden trace / replay tests
- **Subsystem:** Full pipeline
- **Missing behavior:** Given specific LLM output, verify exact evaluation result
- **Failure mode caught:** Evaluation regression
- **Recommended test:** Golden trace file with (input, expected_output) pairs
- **Priority:** P2

#### GAP-P2-02: No test for COND_LABELS uniqueness
- **Subsystem:** runner.py
- **Missing behavior:** Labels should be unique
- **Failure mode caught:** Column conflation in results
- **Recommended test:** Assert len(set(COND_LABELS.values())) == len(COND_LABELS)
- **Priority:** P2

#### GAP-P2-03: No test for script syntax validity
- **Subsystem:** scripts/
- **Missing behavior:** All scripts at least import without errors
- **Failure mode caught:** Dead scripts (like shadow_analysis.py)
- **Recommended test:** `import` test for each script
- **Priority:** P2

---

## G. IMMEDIATE ACTION PLAN

### P0 — Do Now (blocks experiment validity)

1. **EVAL-01: Remove ImportError fallback in evaluator.py:238** — Replace with hard failure. This is a 3-line change.

2. **COND-01: Fix duplicate label in runner.py:51** — Change `"retry_adaptive": "RA"` to `"retry_adaptive": "AD"`. 1-line change.

3. **LOG-01: Add log write failure tracking** — Replace `except OSError: pass` with tracked counter and end-of-run summary. ~10-line change per location.

4. **GAP-P0-04: Add case-test completeness check** — Either integrate preflight_check into runner.py startup, or add assertion test. ~20-line change.

5. **EXEC-01: Thread-safe module counter** — Replace `_load_counter` with `itertools.count()`. 2-line change.

### P1 — Do Next (affects data interpretation)

6. **MOCK-01: Add mock mode warning** — Print prominent warning when mock mode is active. ~5-line change.

7. **NUDGE-01: Add nudge mapping warnings** — Log when case has no operator mapping for diagnostic/guardrail conditions. ~5-line change per function.

8. **CONTRACT-01: Add cge_executed field** — Mark fallback runs clearly. ~3-line change.

9. **PARSE-01: Add _raw_fallback flag** — Mark raw fallback parse results. 1-line change.

10. **SHADOW-01: Fix shadow_analysis.py syntax error** — Fix line 13. 1-line change.

11. **VALIDATE-01: Fix dead branch** — Fix or remove validate_cases_v2.py:45. 1-line change.

### P2 — Do When Convenient (improves robustness)

12. **RETRY-01: Add _evaluator_crash flag to trajectory entries**
13. **GATE-01: Track unresolvable checks in diff_gate validation**
14. **EVAL-03: Change evidence metric defaults to None**
15. **RETRY-03: Add LEG evaluation active/inactive logging**
16. **LLM-01: Add API response validation**
17. **CONFIG-01: Remove YAML fallback parser, require pyyaml**
18. **LOG-02: Add warning when fallback log path is used**

---

## H. OPTIONAL IMPLEMENTATION PATCH PLAN

### Patch 1: Critical Silent Failure Fixes (P0)

**Files modified:** evaluator.py, runner.py, execution.py, retry_harness.py, exec_eval.py

**Changes:**
1. `evaluator.py:238` — Replace `except ImportError` fallback with hard error
2. `runner.py:51` — Fix duplicate "RA" label
3. `execution.py:373-377` — Add log write failure counter and warning
4. `retry_harness.py:953-957,966-969` — Same log write failure handling
5. `exec_eval.py:28-29` — Replace `_load_counter` with `itertools.count()`

**Risk:** Low. These are all detection/warning changes except the evaluator.py change which removes a fallback. The fallback should never activate in a working installation, so removing it has no effect on correct systems and loudly surfaces broken ones.

### Patch 2: Marking/Flagging Fixes (P1)

**Files modified:** execution.py, parse.py, nudges/router.py, scripts/shadow_analysis.py, validate_cases_v2.py

**Changes:**
1. `execution.py:184-188` — Add `cge_executed` field
2. `parse.py:204` — Add `_raw_fallback: True` to raw fallback result
3. `nudges/router.py` — Add WARNING log when diagnostic/guardrail falls through for unmapped case
4. `scripts/shadow_analysis.py:13` — Fix syntax error
5. `validate_cases_v2.py:45` — Fix dead branch

### Patch 3: Test Coverage (all priorities)

**New files:** tests/test_silent_failures.py

**Tests to add:**
1. Test evaluator raises on exec_eval import failure
2. Test log write failure is tracked
3. Test case-test mapping completeness
4. Test COND_LABELS uniqueness
5. Test parallel module loading safety
6. Test mock mode warning
7. Test script import validity

---

*End of D-BUDIT Audit Report v1*
