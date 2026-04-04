# Forensic Data Integrity Audit

**Date**: 2026-03-31
**Scope**: Full V2 code generation + evaluation pipeline
**Auditor**: Claude (adversarial mode)
**Trigger**: Discovery of silent classifier truncation (max_code_chars=2000) corrupting all prior v2 ablation runs
**Escalation**: Discovery that exec_canonical (subprocess isolation) NEVER EXECUTED in any production run

---

## 1. EXECUTIVE SUMMARY

**Is the system trustworthy? NO.**

The execution pass/fail scores are produced by the concat path (`exec_evaluate`), which flattens all multi-file code into a single `exec()` namespace. The canonical execution system (`exec_canonical`) — designed for subprocess isolation, per-file module loading, cross-file import validation, and structured execution diagnostics — has **never executed in any production run**. Every v2 ablation used the concat path due to a config/code vocabulary mismatch: configs set `execution_mode: "in_process"`, but the code checks `config.execution.mode == "canonical"`. These are different config paths. The value `"in_process"` is never read by any code. The `execution.mode` field defaults to `"legacy"` and no config ever sets it to `"canonical"`.

Beyond this catastrophic execution path failure, the reasoning classification layer has multiple additional data corruption vectors. The system has no data integrity invariants, no checksums, no end-to-end verification that what enters the pipeline exits unchanged. Silent defaults, cascading fallbacks, and swallowed exceptions create at least **7 critical** and **6 high-risk** failure modes in the active v2 code path where data is silently lost, modified, or fabricated without any detection mechanism.

---

## 1.1 CATASTROPHIC FINDING: exec_canonical NEVER EXECUTED

**The entire canonical execution system is dead code.**

`exec_canonical.py` implements disk-backed subprocess execution with:
- Per-file module materialization on disk
- Proper Python import resolution between case files
- Subprocess sandboxing (fresh Python process per evaluation)
- Merged namespace with conflict detection and call-level tracing
- Structured JSON output with modules_loaded, functions_called, execution_trace
- 13-category execution classification (SYNTAX_FAILURE, IMPORT_FAILURE, NAME_ERROR, etc.)

**None of this ever ran.** Every production run used `exec_evaluate()` (the concat path) which:
- Concatenates all model code into a single string
- Calls `exec()` in a shared in-process namespace
- Erases all cross-file import semantics
- Has sys.modules pollution between evaluations
- Uses CodeAssembler import rewriting that silently changes code semantics
- Makes a model that dumps everything into one flat file score identically to one that maintains file boundaries

### Root Cause

The config system and the execution dispatch use **different vocabulary for the same concept**:

```
Config YAML:     evaluation.execution_mode: "in_process"     <- what configs set
Config class:    EvaluationConfig.execution_mode: str         <- where it's stored
Code check:      config.execution.mode == "canonical"         <- what execution_v2.py reads
Config class:    ExecutionConfig.mode: str = "legacy"         <- what that field actually is
```

These are **two different config fields on two different dataclasses**:
- `config.evaluation.execution_mode` = "in_process" (set by YAML, never read by execution_v2.py)
- `config.execution.mode` = "legacy" (never set by any YAML, defaults to "legacy")

The dispatch at `execution_v2.py:127` checks `config.execution.mode == "canonical"`. Since `config.execution.mode` is always `"legacy"` (the default), the `else` branch always wins, and `exec_evaluate()` always runs.

The value `"in_process"` set in every config YAML is stored in `config.evaluation.execution_mode` and **never read by any code in the system**. It is a completely dead config value.

### Impact on Results

1. **All 38 multi-file cases**: Cross-file import behavior was never tested. A model that collapses 3 files into 1 flat namespace scores identically to a model that maintains file boundaries. Every cross-boundary claim in the benchmark is based on an execution model that doesn't test cross-boundary behavior.

2. **Module isolation**: The concat path calls `exec()` in-process. Module-level state from one case can leak into the next via `sys.modules`. The canonical path uses fresh subprocess per case, preventing this.

3. **Import error detection**: The concat path strips imports via CodeAssembler and resolves names in a flat namespace. Real `ImportError` and `ModuleNotFoundError` that would occur with actual cross-file imports are never triggered. The canonical path preserves import statements and lets Python's import system validate them.

4. **Execution classification**: The canonical path classifies results into 13 categories (SYNTAX_FAILURE, IMPORT_FAILURE, NAME_ERROR, INVARIANT_CRASH, etc.). The concat path has coarser classification. The detailed categories in `exec_canonical.ALL_CATEGORIES` are never populated.

5. **Execution trace**: The canonical path logs `modules_loaded`, `functions_detected`, `functions_called`, `merge_conflicts`, `execution_trace`. The concat path does not produce these. All these fields in logged results are empty/default.

### Required Action

1. **Wire exec_canonical into the v2 path as the SOLE execution mode**. Remove the concat fallback entirely from `execution_v2.py`.
2. **Fix the config vocabulary**: Either remove `evaluation.execution_mode` (dead field) or make `execution_v2.py` read from the correct config path.
3. **Revalidate all reference fixes pass under exec_canonical** before trusting any results from the new path.
4. **Document in every prior result**: "Execution used concat-mode (flat namespace). Cross-file import behavior was not tested."

---

## 1.5 LEGACY MODE: DEACTIVATE IMMEDIATELY

**DIRECTIVE: The legacy (v1) execution path MUST be deactivated completely.**

The v1 path (`execution.py:evaluate_case` -> `evaluator.py:evaluate_output`) has its own set of critical data corruption issues (P1-1, P1-3, P1-4, P1-5, P1-6, P1-8, P2-5, P2-6) that are SEPARATE from the v2 issues. Maintaining two parallel execution paths:

1. **Doubles the attack surface** for data corruption
2. **Creates confusion** about which path produced which results
3. **Makes auditing impossible** -- any given result could have taken either path
4. **Adds 7 additional high-risk findings** that only exist in legacy code

The legacy path is not used by any v2 condition (baseline_v2, leg_reduction_v2, leg_reduction_lean_v2). It exists only for obsolete v1 conditions (baseline, diagnostic, guardrail, etc.) that are not part of current experiments.

**Action required**:
- Remove all v1 conditions from `constants.py:ALL_CONDITIONS` and `VALID_CONDITIONS`
- Remove v1 dispatch in `runner.py` (the `run_single`, `run_repair_loop`, `run_leg_reduction` branches)
- Remove or gate `evaluator.py:evaluate_output` so it cannot be called from production paths
- Keep `exec_eval.py:exec_evaluate` alive (the v2 path uses it for concat-mode execution), but ensure it is ONLY called from `execution_v2.py`
- Add a hard assertion in `runner.py` that the condition is in `V2_CONDITIONS`

**Until deactivated**: Any result from a v1 condition is subject to findings P1-1, P1-3, P1-4, P1-5, P1-6, P1-8, P2-5, P2-6 IN ADDITION to the v2 findings. These results are unreliable and should not be reported.

---

## 2. V2 CODE PATH: WHAT IS ACTIVE

The v2 code path for our experiments is:

```
runner.py -> execution_v2.py:run_v2()
  -> parser_v2.py (parse_v2_execution, parse_v2_format, parse_v2_recovery)
  -> reconstructor.py:reconstruct_strict()
  -> exec_eval.py:exec_evaluate()          [config.execution.mode != "canonical"]
  -> evaluator_v2.py:build_classifier_v2_vars() + parse_classifier_v2_output()
  -> llm.py:call_model() [generation + classification]
  -> metrics_v2.py:derive_v2_signals()
  -> score_execution.py:score_execution()
  -> logging_core.py:RunLogger
  -> parallel_runner.py [when num_workers > 1]
  -> merge_run.py [post-run aggregation]
```

All our v2 configs use `execution_mode: "in_process"` which maps to `config.execution.mode = "legacy"` (NOT "canonical"). This means `exec_evaluate()` (concat path) is used, NOT `exec_canonical()` (subprocess path).

---

## 3. FINDINGS ACTIVE IN V2 PATH -- FIX NOW

### FIX-NOW-1 (P0-5): V2 Invariant Violation Logged but Ignored

**Location**: `execution_v2.py:104-110`
**What happens**: When the execution parser succeeds but the recovery parser fails, an ERROR is logged but execution continues with potentially inconsistent parse state.
**Why critical**: This is a self-diagnosed invariant violation that the system explicitly detects and then ignores. The result dict has no flag indicating the violation occurred.
**Fix**: Add `ev["parse_invariant_violation"] = True` to the result when this fires. Consider halting execution and classifying as PARSE_FAILURE.

### FIX-NOW-2 (P1-2): "[COULD NOT EXTRACT]" Placeholders in Classifier Prompt

**Location**: `evaluator_v2.py:83-85` (via `_field_or_missing()`)
**What happens**: Missing reasoning fields (root_cause, fix_strategy, risk_check) are replaced with the literal string `"[COULD NOT EXTRACT]"` before being sent to the classifier LLM.
**Why critical**: The classifier LLM interprets this placeholder as content. It may judge "reasoning partially correct" because it sees text that looks like a diagnostic message. The classifier prompt is fabricated input.
**Fix**: When any field is `[COULD NOT EXTRACT]`, skip classification entirely and return a result with `classify_parse_error = "reasoning_fields_missing"`. Do not send fabricated input to the classifier.

### FIX-NOW-3 (P1-7): Failure Type Silently Coerced to "UNKNOWN"

**Location**: `evaluator_v2.py:156-159`
**What happens**: If the classifier LLM returns a failure_type not in the allowed set, it's silently replaced with `"UNKNOWN"`. No `parse_error` is set. The `failure_type_raw` preserves the original but `failure_type` is corrupted.
**Why critical**: Novel failure types that the model correctly identified are erased. Analysis using `failure_type` sees "UNKNOWN" and cannot recover the original. This directly corrupts failure-mode analysis.
**Fix**: Set `parse_error = f"unknown_failure_type:{ft_raw}"` when coercion occurs, so downstream analysis can detect it. Or expand the allowed set.

### FIX-NOW-4 (P1-11): Classifier Parser Drops Lines Before First Section Prefix

**Location**: `evaluator_v2.py:179-196`
**What happens**: The multiline classifier parser looks for section prefixes ("Counterfactual:", "Evidence:", "Judgment:"). Lines BEFORE the first prefix are dropped because `current_section` is None.
**Why critical**: If the classifier LLM outputs preamble text (e.g., "Based on my analysis...") before "Counterfactual:", that text is lost. The parsed judgment is incomplete.
**Fix**: Assign initial lines to a "preamble" section, or to the first dimension section. Log dropped lines.

### FIX-NOW-5 (P2-10 upgraded): None mechanism_correct Treated as False

**Location**: `score_execution.py:43-44`
**What happens**: `mechanism_correct is True` evaluates to False when `mechanism_correct` is None. This means cases where the classifier didn't run (None) are counted the same as cases where the classifier said "mechanism wrong" (False).
**Why critical**: LEG candidate detection (`mechanism_correct is True and not execution_pass`) and lucky fix detection (`execution_pass and mechanism_correct is False`) both produce wrong results when mechanism_correct is None. None should mean "unknown", not "wrong".
**Fix**: Guard with `if mechanism_correct is not None:` before computing leg_candidate and lucky_fix_candidate. When None, set both to None (unknown), not False.

### FIX-NOW-6 (P0-1): Parser Raw Fallback Produces Garbage Code

**Location**: `parse.py:482-506`
**What happens**: When all 7 parse tiers fail, the entire raw LLM response (including reasoning text, error messages, and non-code content) is used as "code" and passed to `exec()`.
**Why critical**: The "code" executed may contain arbitrary text that happens to not throw SyntaxError. The test result is meaningless. The `_raw_fallback=True` flag is set but no hard gate prevents execution.
**Fix**: Add a hard gate in `exec_eval.py:exec_evaluate()`: if `_raw_fallback` is True in the parsed result, return FAIL with `failure_source=PARSE_FAILURE` immediately. Do not execute raw-fallback code.

---

## 4. FINDINGS ACTIVE IN V2 PATH -- FIX BEFORE NEXT ABLATION

### FIX-NEXT-1 (P0-2): Parallel Runner Truncates Events on First Parse Error

**Location**: `parallel_runner.py:145-151`
**What happens**: `_read_events_prefix()` breaks on the first JSONDecodeError. All subsequent events in that chunk file are silently dropped.
**Why it matters**: A single corrupt JSON line (partial write during process kill) causes loss of all remaining events. The merge step has no way to detect the truncation.
**Fix**: Replace `break` with `continue` -- skip corrupt lines, don't stop reading. Log each skipped line. After reading, emit a warning if any lines were skipped.

### FIX-NEXT-2 (P0-3): Logging Fabricates Empty Evaluation Records

**Location**: `logging_core.py:454-463`
**What happens**: When `raw_ev` is None, the event record is filled with `ran: None, passed: None, score: None`. This looks like a real record with None results.
**Why it matters**: Analysis code that reads events.jsonl cannot distinguish "evaluation crashed before producing results" from "evaluation produced None". Averages and counts are corrupted.
**Fix**: When `raw_ev` is None, set `execution.status = "not_evaluated"` explicitly. Add an `evaluation_missing = True` flag. Do not fill passed/score with None -- omit them entirely.

### FIX-NEXT-3 (P0-4): Consumed Keys Silently Drop Fields

**Location**: `logging_core.py:601`
**What happens**: Keys "condition", "operator_used", "num_attempts", "alignment" are consumed (excluded from extra_section) but never written to any canonical section. Data under these keys vanishes.
**Why it matters**: The v2 path sets `ev["condition"]` and `ev["operator_used"]` in execution_v2.py. These are consumed by logging_core and dropped. They don't appear in events.jsonl canonical sections or extra_section.
**Fix**: Either read these keys into canonical sections, or remove them from consumed_keys so they flow to extra_section.

### FIX-NEXT-4 (P0-6): Merge Validates After Committing

**Location**: `parallel_runner.py:217`
**What happens**: Duplicate terminal events are detected after the merged file is written.
**Why it matters**: A brief window exists where the merged file contains duplicates. Any concurrent reader sees corrupted data.
**Fix**: Validate BEFORE writing. Compute duplicate check on in-memory data, only write if clean.

### FIX-NEXT-5 (P1-9): Resume Logic Inconsistent State

**Location**: `parallel_runner.py:283-285`
**What happens**: expected_pairs is computed after resume filtering, but skip pairs are loaded from merged events which may be incomplete.
**Why it matters**: Missing pair detection becomes inaccurate during resume. Completed work may be rerun.
**Fix**: Load skip pairs from ALL chunk events, not just the merged file.

### FIX-NEXT-6 (P1-10): Merge Deduplication Loses Metadata

**Location**: `merge_run.py:162-190`
**What happens**: When two rows have the same primary key and identical evaluation dicts, the first row wins. Non-evaluation fields from the second row are lost.
**Why it matters**: Metadata like assembly_sources, reconstruction details, timing data from the second row disappears.
**Fix**: Merge non-evaluation fields from both rows, preferring the more complete one.

---

## 5. FINDINGS ACTIVE IN V2 PATH -- MEDIUM RISK (monitor)

| ID | Location | Issue | Impact |
|---|---|---|---|
| P2-1 | `execution.py:603-614` | Token estimation char/4 fallback when tiktoken unavailable | Token budget checks inaccurate |
| P2-2 | `llm.py:34-51` | Temperature/top_p silent defaults on config failure | Wrong model params used silently |
| P2-3 | `llm.py:143-144` | Logger swallows logging failures | LLM call data lost to structured log |
| P2-4 | `llm.py:136` | case_id defaults to "unknown" | Lost case attribution |
| P2-7 | `reasoning.py:91-97` | Reasoning fields <10 chars marked "not present" | Short valid reasoning ignored |
| P2-8 | `experiment_config.py:430-432` | int() truncates floats in config | trial=1.5 becomes trial=1 |
| P2-9 | `runner.py:82-85` | Assertions used for validation (python -O disables) | Empty files proceed silently |
| P2-11 | `runner.py:129-132` | Syntax errors skipped in preflight import check | Invalid cases pass preflight |
| P2-12 | `merge_run.py:57-58, 78-80` | Corrupt JSON lines and missing-field records silently skipped | Unknown data loss in merge |

---

## 6. FINDINGS NOT ACTIVE IN V2 PATH (legacy only)

These affect ONLY the v1 execution path (`execution.py:evaluate_case` -> `evaluator.py:evaluate_output`). They are one more reason to deactivate legacy mode.

| ID | Location | Issue | Why v1 only |
|---|---|---|---|
| P1-1 | `evaluator.py:94-104` | Classifier skipped when reasoning_present=False | V2 uses parse_status gate instead |
| P1-3 | `evaluator.py:245` | Error reasons truncated to 2 items | V2 evaluator doesn't truncate reasons |
| P1-4 | `execution.py:290-311` | Reconstruction partial recovery (franken-code) | V2 path uses only SUCCESS+changed_files |
| P1-5 | `execution.py:327` | Code presence requires 10 characters | V2 has own observability in parser_v2 |
| P1-6 | `reasoning.py:230-234` | LEG dimension override inflates scores | V2 computes reasoning_correct differently via metrics_v2 |
| P1-8 | `execution.py:174-177` | None code normalized to empty string | V2 builds own parsed_gen via parser_v2 |
| P1-12 | `execution.py:732-735` | CGE fallback mislabels condition | CGE not a v2 condition |
| P2-5 | `execution.py:405-450` | 9-way cascading failure attribution | V2 has own failure source logic |
| P2-6 | `execution.py:496-517` | 14 observability fields with .get() defaults | V2 builds own observability |

**Total legacy-only issues: 9.** Every one of these is eliminated by deactivating the legacy path.

---

## 7. SYSTEMIC WEAKNESSES

### SW-1: No End-to-End Data Integrity Verification

There is no checksum, hash, or content verification between pipeline stages. The system cannot detect if data was modified between:
- LLM response receipt and parsing
- Parsing and reconstruction
- Reconstruction and execution
- Execution and evaluation
- Evaluation and logging

### SW-2: Silent Fallback as Design Pattern

The system uses a pervasive pattern of try/except with fallback values. At least 40 locations use `.get(key, default)` where the default is indistinguishable from a legitimate value. This makes it impossible to determine post-hoc whether a field's value was measured or fabricated.

### SW-3: No Schema Contract Between Pipeline Stages

Each stage expects certain fields from the previous stage but does not validate them. An empty dict `{}` passes all presence checks.

### SW-4: Parallel Execution Without Atomic Guarantees

The parallel runner writes events.jsonl from multiple workers. The merge step reads all files sequentially with no lock. If a worker is still writing when the merge begins, the merge reads a partial file.

### SW-5: Conditional Prompt Sections Without Audit Trail

Jinja2 templates conditionally include/exclude sections (self_check, risk_check, ground_truth, SCM data) based on variable truthiness. There is no log of which sections were included in the final prompt.

---

## 8. DATA INTEGRITY MAP

```
RAW LLM RESPONSE
  |
  | Transformations: None (stored as-is in calls/*.json)
  | Risk: NONE -- raw response preserved
  v
PARSER (parse.py / parser_v2.py)
  |
  | Transformations: 7-tier fallback, type coercion, None->""
  | Risk: HIGH -- tier 4 uses raw text as code (P0-1)
  | Guarantee: parse_tier field records which tier was used
  | Gap: no hash of input vs output to verify no mutation
  v
RECONSTRUCTOR (reconstructor.py)
  |
  | Transformations: file-dict -> merged code
  | Risk: MEDIUM in v2 (only uses SUCCESS+changed_files)
  | Guarantee: _reconstruction_status field records outcome
  | Gap: no log of which files were changed vs unchanged
  v
CODE ASSEMBLER (code_assembly.py) [concat path only]
  |
  | Transformations: import stripping, duplicate resolution
  | Risk: MEDIUM -- import rewrites change code semantics
  | Guarantee: assembly_used, assembly_risky flags
  | Gap: assembled code may differ from logged extracted code
  v
EXECUTION (exec_eval.py)
  |
  | Transformations: exec() in namespace
  | Risk: LOW -- code executed is the assembled code
  | Guarantee: ran flag, invariant_pass, mutation_pass
  | Gap: sys.modules pollution in concat path
  v
CLASSIFIER (evaluator_v2.py)
  |
  | Transformations: [COULD NOT EXTRACT] substitution (FIX-NOW-2),
  |                  failure_type -> UNKNOWN coercion (FIX-NOW-3),
  |                  preamble lines dropped (FIX-NOW-4)
  | Risk: HIGH -- classifier sees fabricated/incomplete input
  | Guarantee: classify_raw preserves raw classifier output
  | Gap: no hash verification that classifier input matches execution input
  v
SCORING (score_execution.py / metrics_v2.py)
  |
  | Transformations: None -> False conflation (FIX-NOW-5)
  | Risk: MEDIUM -- LEG/lucky detection wrong when classifier didn't run
  | Guarantee: none
  | Gap: no distinction between "not evaluated" and "evaluated as wrong"
  v
LOGGING (logging_core.py)
  |
  | Transformations: consumed key removal (FIX-NEXT-3),
  |                  None-filling for missing sections (FIX-NEXT-2)
  | Risk: HIGH -- fields silently dropped, empty records look real
  | Guarantee: event_id monotonic, trace_id linkage
  | Gap: no content hash to verify logged == runtime
```

---

## 9. VERIFICATION GAPS

Places where corruption could happen AND would NOT be detected:

1. **Parser tier selection**: If tier 1c (lenient JSON) activates when tier 1b (strict JSON) should have worked, the regex-based reconstruction may produce subtly different code. No comparison between tiers.

2. **Assembled code vs logged code**: `_extracted_code` and `_assembled_code` are separate fields but no verification they're consistent.

3. **Classifier input vs execution input**: No hash verification that the code string sent to the classifier matches what was executed.

4. **Event field migration**: Any field NOT in consumed_keys goes to extra_section. New fields silently migrate without anyone knowing.

5. **Parallel merge completeness**: No mechanism to verify that merged_events.jsonl contains ALL events from ALL chunks. A chunk with a corrupt first line produces 0 events.

6. **V2 invariant violation**: execution_v2.py:104-110 detects parse inconsistency and ignores it. The result has no flag.

---

## 10. REQUIRED INVARIANTS (MANDATORY)

### INV-DATA-1: Raw LLM Output Preservation
The raw LLM response string MUST be stored exactly as received, with no modification, truncation, or encoding change.

### INV-DATA-2: No Silent Truncation
No data field in the pipeline may be truncated. All prior truncation has been removed. Any future truncation MUST be blocked by CI checks.

### INV-DATA-3: Executed Code Must Match Logged Code
A SHA-256 hash of the code string passed to `exec()` MUST be stored in the evaluation result and match `_assembled_code` in the logged event.

### INV-DATA-4: Classifier Input Must Match Execution Input
The code string sent to the classifier MUST be identical to the code string that was executed. A hash comparison MUST be performed.

### INV-DATA-5: No Default-Filling of Measurement Fields
Fields that represent measurement outcomes (pass, score, reasoning_correct, mechanism_identified, failure_type) MUST NOT have default values. If a measurement was not performed, the field MUST be absent, not set to None/False/0/"UNKNOWN".

### INV-DATA-6: Parallel Merge Completeness Verification
After merging chunk event files, the merge MUST verify that the total number of case.end events matches the expected count. Any shortfall MUST halt the merge.

### INV-DATA-7: Legacy Path Deactivation
The v1 execution path MUST be deactivated. Only v2 conditions may execute. A hard assertion in runner.py MUST enforce this.

### INV-DATA-8: No Fabricated Classifier Input
If reasoning fields cannot be extracted, the classifier MUST NOT be called with placeholder strings. Classification MUST be skipped and the result MUST indicate `classify_skipped_reason`.

### INV-DATA-9: Canonical Execution is the SOLE Execution Path
All production evaluation MUST use `exec_canonical` (subprocess isolation with per-file module loading). The concat path (`exec_evaluate` via `exec()`) MUST NOT be used for any reported results. A hard assertion MUST enforce that `config.execution.mode == "canonical"` before any evaluation begins. The config field `evaluation.execution_mode` MUST be removed (it is dead code that creates a false sense of configuration).

### INV-DATA-10: Config Field Liveness Verification
Every config field defined in the schema MUST be read by at least one code path. Dead config fields (defined but never read) MUST be removed. A CI check MUST verify that every field in `ExperimentConfig` and its sub-dataclasses has at least one read site in production code.

---

## 11. PRIORITY SUMMARY

### Fix RIGHT NOW (before any new ablation)

| Priority | ID | Location | Issue | Impact on Results |
|---|---|---|---|---|
| **0** | **P0-7** | **`execution_v2.py:127`** | **exec_canonical never runs — concat path used for all evals** | **All cross-file claims invalid. Module isolation never tested. 38 multi-file cases evaluated in flat namespace.** |
| 1 | FIX-NOW-5 | `score_execution.py:43-44` | None mechanism_correct = False | LEG/lucky counts wrong |
| 2 | FIX-NOW-2 | `evaluator_v2.py:83-85` | Fabricated classifier input | Classifier judgments on fake data |
| 3 | FIX-NOW-3 | `evaluator_v2.py:156-159` | Failure type -> UNKNOWN | Failure analysis corrupted |
| 4 | FIX-NOW-4 | `evaluator_v2.py:179-196` | Preamble lines dropped | Classifier parse incomplete |
| 5 | FIX-NOW-1 | `execution_v2.py:104-110` | Invariant violation ignored | Unknown impact on affected cases |
| 6 | FIX-NOW-6 | `parse.py:482-506` | Raw fallback executed | Garbage code scored as real |
| 7 | LEGACY | `runner.py` + `execution.py` | v1 path still callable | 9 additional corruption vectors |

### Fix before next ablation

| Priority | ID | Location | Issue |
|---|---|---|---|
| 8 | FIX-NEXT-1 | `parallel_runner.py:145-151` | Event truncation on parse error |
| 9 | FIX-NEXT-2 | `logging_core.py:454-463` | Fabricated empty eval records |
| 10 | FIX-NEXT-3 | `logging_core.py:601` | Consumed keys drop data |
| 11 | FIX-NEXT-4 | `parallel_runner.py:217` | Validate after commit |
| 12 | FIX-NEXT-5 | `parallel_runner.py:283-285` | Resume state inconsistency |
| 13 | FIX-NEXT-6 | `merge_run.py:162-190` | Dedup loses metadata |

### Monitor (medium risk, not actively corrupting current results)

P2-1 through P2-12 as listed in Section 5.
