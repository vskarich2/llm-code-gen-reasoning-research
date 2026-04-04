# T3 Code Generation Benchmark — Full System Audit

**Date**: 2026-03-25
**Scope**: Every .py file in the project root, nudges/, scripts/, templates/
**Method**: Line-by-line source reading, execution path tracing

---

## 1. SYSTEM OVERVIEW

T3 is a research benchmark that measures how LLMs (primarily OpenAI models) handle causal invariant bugs in multi-file Python codebases. It presents buggy code to a model, collects the model's fix + reasoning, executes the fix against behavioral invariant tests, and classifies the result along two independent axes: **code correctness** (did the fix pass tests?) and **reasoning correctness** (did the model identify the true failure mechanism?). The cross of these axes yields four categories: true_success, LEG (Latent Execution Gap — correct reasoning but broken code), lucky_fix (wrong reasoning but passing code), and true_failure.

The system runs 25 experimental conditions that vary the prompt (nudges, guardrails, SCM annotations, reasoning scaffolds, contract-gated execution, retry loops, LEG-reduction) across 58 benchmark cases (v2), with multiple trials per model for statistical power.

### Core Pipeline (step-by-step)

```
1. load_cases()         — read cases_v2.json, load code files, validate imports
2. preflight_verify_tests() — verify every case has a test function
3. validate_run()       — check (case, condition) compatibility
4. For each (case, condition):
   a. build_prompt()    — select condition branch, apply nudge/SCM/reasoning scaffold
   b. call_model()      — OpenAI API (or mock), append JSON output instruction
   c. parse_model_response() — 7-tier parser (file_dict → code_dict → JSON → code block → raw)
   d. reconstruct_strict()   — (V2) map file-dict output back to case files
   e. exec_evaluate()   — assemble multi-file program, load module, run invariant test
   f. llm_classify()    — LLM judge: reasoning_correct + failure_type
   g. compute_alignment() — derive category: true_success/leg/lucky_fix/true_failure
   h. write_log()       — append to run.jsonl, run_prompts.jsonl, run_responses.jsonl
   i. emit_event()      — append to events.jsonl for live dashboard
5. print_results()      — summary table
6. verify_integrity()   — check all log writes succeeded
```

### Key Abstractions

| Abstraction | What It Is |
|---|---|
| **Case** | A dict from cases_v2.json: id, task, code_files, failure_mode, difficulty |
| **Condition** | One of 25 experimental treatments (baseline, diagnostic, guardrail, retry_*, etc.) |
| **Nudge** | A prompt modifier: diagnostic (reasoning scaffold) or guardrail (action constraint) |
| **Evaluator** | Two sources: exec_evaluate (behavioral, authoritative) and llm_classify (reasoning) |
| **Alignment** | The 2x2 matrix of code_correct x reasoning_correct |
| **RunLogger** | Thread-safe JSONL writer with integrity verification |
| **Trajectory** | Sequence of (prompt, response, eval) steps in a retry harness run |

---

## 2. GLOBAL CONTROL FLOW

### Entry Points

1. **`runner.py main()`** — primary CLI. Two modes:
   - **Legacy mode**: `python runner.py --model gpt-4o-mini --conditions baseline,diagnostic`
   - **Ablation mode**: `python runner.py --model gpt-4o-mini --run-dir ablation_runs/... --trial 1 --run-id abc`
2. **`scripts/run_ablation_v2.sh`** — shell script that invokes runner.py in ablation mode for each (model, trial)
3. **`scripts/update_dashboards.py`** — standalone dashboard aggregator (runs on cron/loop)
4. **`preflight_check.py`** — standalone validation script

### Detailed Execution Flow (Ablation Mode)

```
main()
  ├─ parse CLI args
  ├─ if --run-dir: _run_ablation_mode(args)
  │    ├─ load_cases(cases_file=args.cases)
  │    │    ├─ json.loads(cases_v2.json)
  │    │    ├─ for each case: read code files, validate import consistency
  │    │    └─ return list[dict]
  │    ├─ preflight_verify_tests(cases)
  │    │    └─ for each case: verify _CASE_TESTS[case_id] or _load_v2_test(case) exists
  │    ├─ validate_run(cases, conditions)  [condition_registry.py]
  │    │    └─ for each (case, condition): check_compatibility()
  │    ├─ _validate_experiment_config(cases, conditions, model)
  │    ├─ mkdir(run_dir), write metadata.json, touch events.jsonl
  │    ├─ set_ablation_context(events_path, trial, run_id)
  │    ├─ init_run_log(model, log_dir=run_dir)
  │    ├─ run_all(cases, model, conditions, max_workers=1)
  │    │    ├─ for each (case, condition):
  │    │    │    ├─ _run_one(case, model, condition)
  │    │    │    │    └─ _run_one_inner(case, model, condition)
  │    │    │    │         ├─ if "repair_loop":     run_repair_loop()
  │    │    │    │         ├─ if "contract_gated":   run_contract_gated()
  │    │    │    │         ├─ if in RETRY_CONDITIONS: run_retry_harness()
  │    │    │    │         ├─ if "leg_reduction":    run_leg_reduction()
  │    │    │    │         └─ else:                  run_single()
  │    │    │    └─ store result in raw dict
  │    │    └─ return results
  │    ├─ print_results(results, conditions, model)
  │    ├─ _validate_execution_sanity(results, conditions)
  │    ├─ verify_integrity() on RunLogger
  │    ├─ close_run_log()
  │    └─ write completion to metadata.json
  └─ else: legacy mode (same flow, different log paths)
```

### Branching by Condition

```
_run_one_inner(case, model, condition)
  │
  ├─ condition == "repair_loop"
  │    └─ run_repair_loop(): attempt 1 with diagnostic, if fail → attempt 2 with error feedback
  │
  ├─ condition == "contract_gated"
  │    └─ run_contract_gated(): elicit contract → generate code → diff gate → retry → eval
  │
  ├─ condition in RETRY_CONDITIONS (retry_no_contract, retry_with_contract, retry_adaptive, retry_alignment)
  │    └─ run_retry_harness(): up to 5 iterations with failure classification + adaptive hints
  │
  ├─ condition == "leg_reduction"
  │    └─ run_leg_reduction(): single call with self-correction schema
  │
  └─ all others (baseline, diagnostic, guardrail, SCM, reasoning, etc.)
       └─ run_single(): build_prompt() → call_model() → parse → evaluate → log
```

### Failure Paths

- **Empty API key** → mock mode (llm_mock.py returns deterministic responses)
- **Parse failure** → raw fallback (entire response used as code, _raw_fallback=True)
- **Syntax error in generated code** → SyntaxError caught, score=0.0
- **Runtime error during test** → caught, score=0.0
- **Contract parse failure** → fallback to standard code gen (_fallback_run)
- **Log write failure** → counted in writes_failed, run marked INVALID at end
- **Preflight failure** → RuntimeError, experiment blocked

---

## 3. FILE-BY-FILE BREAKDOWN

### File: `runner.py`

**Purpose**: CLI entry point and experiment orchestrator. Loads cases, validates, dispatches to execution functions, collects results.

**Key Functions**:

#### `main()`
- Inputs: CLI args (--model, --case-id, --cases, --conditions, --parallel, --run-dir, --trial, --run-id)
- Outputs: Printed results, log files
- Side effects: Creates log files, run directories
- Routes to `_run_ablation_mode()` if --run-dir, else legacy mode

#### `load_cases(case_id, cases_file) -> list[dict]`
- Inputs: Optional case_id filter, path to cases JSON
- Outputs: List of case dicts with `code_files_contents` populated
- Side effects: Reads files from disk, validates import consistency
- Calls `_validate_import_consistency()` per case

#### `_run_one_inner(case, model, condition) -> (case_id, condition, eval_dict)`
- Inputs: Case dict, model name, condition string
- Outputs: Tuple of (case_id, condition_name, evaluation_result)
- The dispatch hub: routes to run_single, run_repair_loop, run_contract_gated, run_retry_harness, or run_leg_reduction

#### `run_all(cases, model, conditions, max_workers, quiet) -> list[dict]`
- Serial (max_workers=1) or parallel (ThreadPoolExecutor) execution
- Catches exceptions from parallel workers, logs them, continues
- Post-processes CGE results (enforces cge_executed invariant)

#### `_run_ablation_mode(args)`
- Full ablation run lifecycle: preflight → metadata → set context → init log → run → verify → close

#### `_validate_execution_sanity(results, conditions)`
- Post-run guard: rejects runs with <50% execution rate, 0% pass rate, zero variance, or >95% LEG rate

**Dependencies**: execution.py (build_prompt, run_single, run_repair_loop, etc.), constants.py, condition_registry.py, retry_harness.py
**Called by**: CLI (python runner.py)
**Importance**: CRITICAL

---

### File: `execution.py`

**Purpose**: Core execution logic. Prompt building, single runs, repair loops, contract-gated execution, LEG-reduction, logging.

**Key Functions**:

#### `build_prompt(case, condition) -> (prompt, operator_used)`
- 25-branch if/elif chain dispatching to nudge router, SCM builders, reasoning builders
- Returns (full_prompt_text, operator_name_string)
- For contract_gated and leg_reduction: returns base prompt (multi-step flow is inside their run functions)

#### `run_single(case, model, condition) -> (case_id, condition, eval)`
- Single LLM call pipeline: build_prompt → call_model → parse → evaluate → log → emit event
- Handles V2 file-dict format via reconstructor
- Adds token instrumentation (prompt_tokens, budget check)

#### `_attempt_and_evaluate(case, model, prompt, file_paths) -> (raw_output, parsed, eval)`
- One LLM call + parse + optional reconstruction + evaluate
- Reconstruction: if file_dict format, calls reconstruct_strict(), wires changed files into parsed["code"]

#### `run_repair_loop(case, model) -> (case_id, "repair_loop", eval)`
- Attempt 1: diagnostic prompt. If pass → done.
- Attempt 2: append error feedback to prompt. Evaluate.

#### `run_contract_gated(case, model) -> (case_id, "contract_gated", eval)`
- Step 1: Elicit contract (raw=True)
- Step 2: Generate code conditioned on contract
- Step 3: Diff gate validation
- Step 4: If gate fails, retry with violations
- Step 5: Evaluate final code

#### `run_leg_reduction(case, model) -> (case_id, "leg_reduction", eval)`
- Single LLM call with revision trace schema
- Parses structured output (bug_diagnosis, plan_steps, revision_history, verification, code)

#### `class RunLogger`
- Thread-safe JSONL writer with lock
- Writes to three files: run.jsonl, run_prompts.jsonl, run_responses.jsonl
- Invariant checks: no writes after close, no model mismatch
- verify_integrity(): returns (valid, reason) based on writes_failed count

#### `set_ablation_context(events_path, trial, run_id)`
- Sets module-level globals for event emission routing

#### `_emit_metrics_event(case, model, condition, ev, elapsed_seconds)`
- Ablation mode: validates + writes to per-run events.jsonl via live_metrics.emit_event
- Legacy mode: writes to shared events.jsonl without strict validation

**Dependencies**: llm.py, parse.py, evaluator.py, prompts.py, nudges/router.py, contract.py, diff_gate.py, leg_reduction.py, reconstructor.py, live_metrics.py
**Called by**: runner.py
**Importance**: CRITICAL

---

### File: `evaluator.py`

**Purpose**: Evaluation dispatcher. Routes to exec_evaluate for behavioral testing, llm_classify for reasoning assessment, computes alignment categories.

**Key Functions**:

#### `evaluate_output(case, parsed, eval_model) -> dict`
- Step 1: `exec_evaluate(case, parsed["code"])` → behavioral pass/fail (SOLE authority for code_correct)
- Step 2: `llm_classify(case, code, reasoning)` → reasoning_correct, failure_type
- Step 3: `compute_alignment(exec_pass, reasoning_correct)` → category
- Step 4: `compute_evidence_metrics(case, raw_output)` → SCM evidence usage
- Step 5: Propagate parse_error, _raw_fallback

#### `llm_classify(case, code, reasoning, eval_model) -> dict`
- Builds classifier prompt from _CLASSIFY_PROMPT template
- Calls LLM (default gpt-4.1-nano), parses "YES/NO ; FAILURE_TYPE" response
- Returns reasoning_correct (bool|None), failure_type (str|None)

#### `compute_category(code_correct, reasoning_correct) -> str`
- Pure function: true_success, leg, lucky_fix, true_failure, unclassified

#### `compute_evidence_metrics(case, output) -> dict`
- SCM evidence usage scoring (0-3 scale)
- Scans for evidence IDs (F*, V*, E*, I*, C*) in output

**Dependencies**: exec_eval.py (exec_evaluate), llm.py (call_model), failure_classifier.py (FAILURE_TYPE_SET), eval_cases.py (_has, _low — deprecated), scm_data.py
**Called by**: execution.py (run_single, run_repair_loop, etc.)
**Importance**: CRITICAL

---

### File: `exec_eval.py`

**Purpose**: Execution-based evaluator. Loads model-generated code as a Python module, runs case-specific invariant tests.

**Key Functions**:

#### `exec_evaluate(case, code) -> dict`
- Checks code non-empty
- Calls `_assemble_program(code, case)` for multi-file assembly
- Loads assembled code via `load_module_from_code()`
- Runs case-specific test from `_CASE_TESTS` or `_load_v2_test()`
- Runs mutation tests
- Returns structured result with execution info

#### `load_module_from_code(code, name) -> ModuleType`
- Strips local imports (sibling module references)
- exec() compiled code into new module
- Thread-safe via itertools.count()

#### `_assemble_program(model_code, case) -> dict`
- Multi-file assembly: prepends ALL original case files, appends model code
- Later definitions override earlier ones (Python semantics)
- Detects rename errors (model didn't override expected function)

#### `_load_v2_test(case) -> callable | None`
- Dynamically loads test from `tests_v2/test_{family}.py`
- Tries test_{difficulty}, then test(), then test_a

#### Case-specific tests (16+)
- `_test_temporal`, `_test_idempotency`, `_test_partial_rollback`, etc.
- Each tests a specific causal invariant (e.g., "raw_stats on original data", "retrying doesn't double delta")
- Return (passed: bool, reasons: list[str])

**Dependencies**: parse.py (extract_code, strip_local_imports, STDLIB_MODULES)
**Called by**: evaluator.py
**Importance**: CRITICAL

---

### File: `llm.py`

**Purpose**: OpenAI API wrapper with mock fallback.

**Key Functions**:

#### `call_model(prompt, model, raw, file_paths) -> str`
- If `raw=False`: appends JSON output instruction (V1 or V2 depending on file_paths)
- If no OPENAI_API_KEY: routes to `llm_mock.mock_call()`
- Else: `_openai_call()` via OpenAI SDK
- Deterministic: temperature=0.0, top_p=1.0 (except o1/o3/o4/gpt-5 which don't support temperature)

#### `_openai_call(prompt, model, api_key) -> str`
- `client.responses.create(model=model, input=prompt, store=False)`
- Returns `response.output_text`

**V2 output instruction**: If `file_paths` provided and `USE_V2_OUTPUT_FORMAT=True`, instructs model to return `{"reasoning": "...", "files": {"path": "content or UNCHANGED"}}` format.

**Dependencies**: openai SDK, llm_mock.py
**Called by**: execution.py, evaluator.py
**Importance**: CRITICAL

---

### File: `parse.py`

**Purpose**: Multi-tier response parser. Extracts code, reasoning, and files from model output.

**Key Functions**:

#### `parse_model_response(raw) -> dict`
- 7-tier fallback chain:
  1. `_try_file_dict()` — JSON with "files" key (V2 multi-file)
  2. `_try_code_dict()` — JSON with "code" as dict
  3. `_try_json_direct()` — standard JSON with "code" as string
  4. `_try_json_lenient()` — JSON with unescaped newlines
  5. `_try_json_substring()` — JSON embedded in text
  6. `_try_code_block()` — ```python blocks
  7. Raw fallback — entire response as code (_raw_fallback=True)

#### `parse_structured_output(raw) -> dict`
- Strict JSON parser for retry harness
- Requires reasoning, plan, code keys
- No fallback — returns parse_error on any issue

#### `strip_local_imports(code) -> str`
- Removes import statements referencing sibling modules
- Preserves stdlib imports (from _stdlib.STDLIB_MODULES)

**Dependencies**: _stdlib.py
**Called by**: execution.py, retry_harness.py
**Importance**: CRITICAL

---

### File: `prompts.py`

**Purpose**: Base prompt construction and nudge libraries (DIAGNOSTIC_NUDGES, GUARDRAIL_NUDGES).

**Key Functions**:

#### `build_base_prompt(task, code_files) -> str`
- Terse format: task text + formatted code files

#### `_format_code_files(code_files) -> str`
- V2 format: `### FILE 1/N: path ###` with ```python blocks

#### `DIAGNOSTIC_NUDGES` (dict)
- HIDDEN_DEPENDENCY, TEMPORAL_CAUSAL_ERROR, INVARIANT_VIOLATION, STATE_SEMANTIC_VIOLATION
- Each is a multi-paragraph reasoning guide

#### `GUARDRAIL_NUDGES` (dict)
- Same four keys, each is a set of mandatory constraints

**Called by**: execution.py (build_prompt), nudges/core.py
**Importance**: CRITICAL

---

### File: `retry_harness.py`

**Purpose**: Scientific trajectory probe. Runs up to 5 iterations per case with failure classification, adaptive hints, and trajectory analysis. Measurement instrument, NOT production retry.

**Key Functions**:

#### `run_retry_harness(case, model, condition, eval_model) -> (case_id, condition, result_dict)`
- Main entry: for step in range(max_steps):
  - Build prompt (initial or retry with feedback)
  - call_model → parse_structured_output → evaluate
  - Classify failure type
  - Compute trajectory analytics (diffs, stagnation, convergence)
  - If pass: break
- Returns comprehensive result with trajectory, dynamics, failure persistence

#### Trajectory Analysis Functions (post-hoc only)
- `_classify_trajectory_dynamics()` → MONOTONIC_FIX, OSCILLATION, STAGNATION, etc.
- `_compute_convergence_depth()` → how deep before success
- `_trajectory_stability_score()` → consistency of failure types
- `_oscillation_rate()` → fraction of score reversals
- `_compute_failure_persistence()` → model stuck-ness metrics

#### Helper Functions
- `_build_error_object(ev)` → structured error from eval result
- `_format_test_output(ev)` → human-readable failure for retry prompt
- `classify_failure(error_obj, critique)` → failure type classification
- `_estimate_reasoning_validity()` → signal fusion (heuristic + trajectory)

**Constants**: MAX_ITERATION_SECONDS=60, MAX_TOTAL_SECONDS=360, 5 iterations max

**Dependencies**: parse.py, evaluator.py, llm.py, failure_classifier.py, leg_evaluator.py
**Called by**: runner.py (_run_one_inner)
**Importance**: CRITICAL

---

### File: `live_metrics.py`

**Purpose**: Process-based live metrics. Workers write events, separate dashboard process aggregates.

**Key Functions**:

#### `emit_event(event, events_path)`
- Validates schema (model, trial, run_id, case_id, condition, timestamp)
- Atomic write: `os.open() + os.write() + os.fsync() + os.close()`

#### `compute_metrics(events, total_jobs) -> dict`
- Pure function: per-condition pass_rate, LEG rate, lucky_fix rate, exec|reasoning
- Deltas (leg_reduction - baseline), regime classification, case stability

#### `write_dashboard(metrics, dashboard_path)`
- Atomic file write (temp + fsync + os.replace)
- Human-readable text dashboard

**Called by**: execution.py (emit_event), scripts/update_dashboards.py (compute + write)
**Importance**: Supporting

---

### File: `failure_classifier.py`

**Purpose**: Heuristic failure type classifier. No ground truth access.

**Key Functions**:

#### `classify_failure(error_obj, critique) -> dict`
- 4 priority rules:
  1. Critique keyword match (confidence 0.8)
  2. Error category mapping (0.5)
  3. Keyword scan on error reasons (0.3)
  4. Fallback → UNKNOWN (0.0)

**FAILURE_TYPES**: TEMPORAL_ORDERING, HIDDEN_DEPENDENCY, PARTIAL_STATE_UPDATE, INVARIANT_VIOLATION, RETRY_LOGIC_BUG, LOGGING_INCONSISTENCY, CONFOUNDING_LOGIC, EDGE_CASE_MISSED, UNKNOWN

**Called by**: retry_harness.py
**Importance**: Supporting

---

### File: `condition_registry.py`

**Purpose**: Compatibility registry. Prevents running conditions on cases that lack required data.

**Key Functions**:

#### `check_compatibility(case, condition) -> (bool, reason)`
- Universal conditions: always OK
- Nudge conditions: require entry in CASE_TO_OPERATORS
- SCM conditions: require entry in scm_data
- Hard constraint conditions: require case["hard_constraints"] non-empty

#### `validate_run(cases, conditions)`
- Checks ALL (case, condition) pairs. Raises RuntimeError on any incompatibility.

**Called by**: runner.py (preflight)
**Importance**: CRITICAL

---

### File: `contract.py`

**Purpose**: Contract-Gated Execution contract schema, parsing, and prompt builders.

**Key Functions**:
- `parse_contract(raw) -> dict | None` — extract JSON contract from model output
- `build_contract_prompt(task, code_files) -> str` — prompt for contract elicitation
- `build_code_from_contract_prompt(task, code_files, contract) -> str` — code gen conditioned on contract
- `build_retry_prompt(task, code_files, contract, violations) -> str` — retry with violation feedback

**Called by**: execution.py (run_contract_gated)
**Importance**: Supporting

---

### File: `diff_gate.py`

**Purpose**: Validates candidate code against an Execution Contract. 6 check categories.

**Key Functions**:
- `validate(contract, code, reference_code) -> dict` — runs all checks, returns {valid, violations, checks_run, checks_passed}
- Checks: must_change, must_not_change, required_effects, ordering, retry_safety, rollback

**Called by**: execution.py (run_contract_gated)
**Importance**: Supporting

---

### File: `leg_reduction.py`

**Purpose**: LEG-reduction prompt builder and output parser.

**Key Functions**:
- `build_leg_reduction_prompt(task, code_files) -> str` — prompt with revision trace schema
- `parse_leg_reduction_output(raw) -> dict` — strict parser for revision_history, verification, code

**Called by**: execution.py (run_leg_reduction)
**Importance**: Supporting

---

### File: `leg_evaluator.py`

**Purpose**: LEG metric evaluator. Analysis only (not in control loops).

**Key Functions**:
- `evaluate_reasoning(model, reasoning_text, code_k, error_obj, ...) -> dict` — LLM judge for reasoning
- `compute_leg_true(entry) -> bool` — primary LEG metric
- `compute_evaluator_bias(trajectory) -> dict` — confirmation bias measurement

**Called by**: retry_harness.py (post-hoc analysis)
**Importance**: Supporting

---

### File: `reconstructor.py`

**Purpose**: Maps LLM file-dict output back to case files.

**Key Functions**:
- `reconstruct_strict(manifest_paths, manifest_files, model_files) -> ReconstructionResult` — primary path, fails on missing files
- `reconstruct_salvage(...)  -> ReconstructionResult` — fills missing with originals

**Called by**: execution.py (_attempt_and_evaluate)
**Importance**: Supporting

---

### File: `constants.py`

**Purpose**: Shared constants. Sole source of truth for condition names, labels, and categories.

**Key Data**:
- `VALID_CONDITIONS` (frozenset, 25 conditions)
- `COND_LABELS` (dict, 2-char labels)
- `RETRY_CONDITIONS`, `MULTISTEP_CONDITIONS`, `SIMPLE_CONDITIONS` (structural category sets)
- `CURRENT_CONFIG_VERSION = 1`

**Called by**: runner.py, config.py
**Importance**: CRITICAL

---

### File: `config.py`

**Purpose**: YAML config loader with strict validation and frozen dataclasses.

**Key Functions**:
- `load_config(path) -> ExperimentConfig` — load, validate, freeze
- `_validate_and_build(raw) -> ExperimentConfig` — full validation (version, types, unknown keys, structural invariants)
- `get_template_for_condition(config, condition, phase) -> str` — template lookup
- `log_resolved_config(config, run_dir) -> Path` — serialize config to disk

**Key Dataclasses**: ExperimentConfig, ConditionConfig, RetryConfig, ExecutionConfig, LoggingConfig (all frozen)

**Called by**: Not yet integrated into runner.py production path (Phase 1: use_templates=False)
**Importance**: CRITICAL (new system)

---

### File: `templates.py`

**Purpose**: Jinja2 template registry with StrictUndefined, strict variable validation, one-shot hashing.

**Key Functions**:
- `render(template_name, variables) -> str` — registry lookup + var validation + Jinja2 render
- `render_with_metadata(template_name, variables) -> (str, dict)` — render + provenance metadata
- `init_template_hashes() -> dict` — compute SHA-256 of all templates via Jinja2 loader source (once, immutable)
- `preflight_validate_templates(config)` — startup validation (files exist, no forbidden logic, dry-render)

**Registered Templates**: base, retry, repair_feedback, contract_elicit, contract_code, contract_retry, classify

**Called by**: Not yet integrated into production path (Phase 1: use_templates=False)
**Importance**: CRITICAL (new system)

---

### File: `nudges/router.py`

**Purpose**: Strict router for nudge operator dispatch. Enforces identity-transform prohibition.

**Key Functions**:
- `apply_diagnostic(case_id, base_prompt) -> str` — looks up operator, applies, asserts output differs
- `apply_guardrail(case_id, base_prompt) -> str`
- `apply_guardrail_strict(case_id, base_prompt, hard_constraints) -> str`
- `apply_counterfactual/reason_then_act/self_check/counterfactual_check/test_driven(case_id, base_prompt) -> str`

**Called by**: execution.py (build_prompt)
**Importance**: Supporting

---

### File: `nudges/operators.py`

**Purpose**: Global operator registry. NudgeOperator = (name, kind, description, build_prompt).

**Key Functions**: `register()`, `get()`, `list_operators()`, `list_by_kind()`

**Called by**: nudges/core.py (registration), nudges/router.py (retrieval)
**Importance**: Supporting

---

### File: `nudges/mapping.py`

**Purpose**: Maps case_id to NudgeAssignment (which operators to apply). Hardcoded for ~15 cases.

**Key Functions**: `get_operators_for_case(case_id) -> NudgeAssignment | None`

**Called by**: nudges/router.py, condition_registry.py
**Importance**: Supporting

---

### File: `nudges/core.py`

**Purpose**: Concrete nudge operator definitions. All self-register on module import.

Defines 13 operators: 4 diagnostic, 4 guardrail, 5 generic (counterfactual, reason_then_act, self_check, counterfactual_check, test_driven).

**Called by**: nudges/operators.py (via registry)
**Importance**: Supporting

---

### File: `reasoning_prompts.py`

**Purpose**: Three reasoning interface builders.

**Functions**: `build_structured_reasoning()`, `build_free_form_reasoning()`, `build_branching_reasoning()`

**Called by**: execution.py (build_prompt)
**Importance**: Supporting

---

### File: `scm_prompts.py`

**Purpose**: SCM prompt builders for 6 experimental conditions.

**Functions**: `build_scm_descriptive()`, `build_scm_constrained()`, `build_scm_constrained_evidence()`, `build_scm_constrained_evidence_minimal()`, `build_evidence_only()`, `build_length_matched_control()`

**Called by**: execution.py (build_prompt)
**Importance**: Supporting

---

### File: `scm_data.py`

**Purpose**: SCM evidence registry. Hardcoded data for ~5 cases.

**Functions**: `get_scm(case_id) -> dict | None`

**Called by**: scm_prompts.py, evaluator.py, condition_registry.py
**Importance**: Supporting

---

### File: `eval_cases.py`

**Purpose**: Heuristic text-matching evaluators (deprecated, retained for backward compat).

**Functions**: `_eval_hidden_dep()`, `_eval_temporal()`, `_eval_invariant()`, etc. (16 evaluators)

**Called by**: evaluator.py (legacy _has, _low imports only)
**Importance**: Utility (deprecated)

---

### File: `llm_mock.py`

**Purpose**: Deterministic mock LLM. Returns condition-appropriate responses when no API key.

**Functions**: `mock_call(prompt) -> str` with dispatch table for different case types.

**Called by**: llm.py (when OPENAI_API_KEY absent)
**Importance**: Utility (testing only)

---

### File: `_stdlib.py`

**Purpose**: Canonical stdlib module list (28 modules).

**Data**: `STDLIB_MODULES` frozenset

**Called by**: parse.py, validate_cases_v2.py
**Importance**: Utility

---

### File: `main.py`

**Purpose**: Stub entry point. Prints welcome message only.

**Importance**: Utility (unused)

---

### File: `preflight_check.py`

**Purpose**: Pre-ablation validation script. Runs 7 checks per case.

**Checks**: Test resolves, code files exist, buggy code loads, test runs, test fails on buggy code, reference fix exists, test passes on reference fix.

**Importance**: Supporting

---

### File: `validate_cases_v2.py`

**Purpose**: Case validation pipeline for v2 benchmark. 5 checks per case.

**Checks**: Code loads, test fails on buggy, test passes on fixed, minimal diff, idempotent test.

**Importance**: Supporting

---

### File: `experiment.yaml`

**Purpose**: YAML config for the new config system. Defines models, conditions (with template mappings), retry settings, execution params, logging.

**Importance**: CRITICAL (new system)

---

### Files: `templates/*.jinja2` (7 files)

**Purpose**: Jinja2 prompt templates for the new template system.

**Templates**: base, retry, repair_feedback, contract_elicit, contract_code, contract_retry, classify

**Importance**: CRITICAL (new system)

---

### Script Files: `scripts/`

| Script | Purpose |
|---|---|
| `run_ablation.sh` | Shell runner for ablation experiments (v1 cases) |
| `run_ablation_v2.sh` | Shell runner for v2 ablation experiments |
| `run_ablation_leg_8t.sh` | LEG ablation with 8 threads |
| `run_tests.sh` | Test runner |
| `update_dashboards.py` | Dashboard aggregator (polls run dirs, writes dashboards) |
| `run_ablation_config.py` | Config-driven ablation runner |
| `paper_analysis.py` | Paper statistics and visualization |
| `leg_ablation_analysis.py` | LEG ablation study analysis |
| `leg_regime_analysis.py` | LEG regime analysis |
| `merge_and_validate.py` | Result merging and validation |
| `shadow_analysis.py` | Shadow analysis for failure types |
| `extract_metadata.py` | Metadata extraction from results |
| `extract_responses.py` | Response extraction utility |
| `validate_smoke.py` | Smoke test validator |
| `test_invariant.py` | Invariant testing utility |

---

## 4. CORE COMPONENTS (DEEP DIVE)

### 4.1 Case Loading

**Files**: runner.py:load_cases, cases_v2.json, code_snippets_v2/

**How it works**:
1. `json.loads(cases_v2.json)` → 58 case dicts
2. For each case, read each file in `case["code_files"]` from disk
3. Store in `case["code_files_contents"]` (dict: path → content)
4. Validate import consistency: all files same directory, no duplicate basenames, no relative/qualified imports

**Case structure**:
```json
{
  "id": "alias_config_a",
  "family": "alias_config",
  "difficulty": "A",
  "failure_mode": "ALIASING",
  "task": "Refactor this configuration module...",
  "code_files": ["code_snippets_v2/alias_config_a/config.py"],
  "hard_constraints": []
}
```

### 4.2 Prompt Construction

**Files**: execution.py:build_prompt, prompts.py, nudges/, scm_prompts.py, reasoning_prompts.py

**Flow**:
1. `build_base_prompt(task, code_files)` → terse prompt with numbered FILE delimiters
2. Condition branch selects augmentation:
   - baseline: base only
   - diagnostic/guardrail: nudge router selects operator from mapping, appends to base
   - SCM: scm_prompts builds graph/evidence/constraint sections
   - reasoning: appends step-by-step/free-form/branching scaffold
   - contract_gated/leg_reduction: base returned (multi-step flow handles its own prompts)
3. llm.py appends JSON output instruction (V1 or V2)

### 4.3 Model API Calls

**Files**: llm.py, llm_mock.py

**How it works**:
1. `call_model(prompt, model, raw, file_paths)`
2. If raw=False: append output instruction (V1 or V2 depending on file_paths)
3. If no API key: `mock_call(prompt)` returns deterministic response
4. Else: `OpenAI().responses.create(model=model, input=full_prompt, store=False, temperature=0.0)`
5. Return response.output_text as string

### 4.4 Evaluation Logic

**Files**: evaluator.py, exec_eval.py

**Two sources of truth**:
1. **exec_evaluate** (behavioral): load code as module → run invariant test → pass/fail
2. **llm_classify** (reasoning): LLM judges if reasoning identifies correct mechanism

**Alignment matrix**:
| | Code Correct | Code Wrong |
|---|---|---|
| **Reasoning Correct** | true_success | LEG |
| **Reasoning Wrong** | lucky_fix | true_failure |

### 4.5 Retry / Trajectory System

**File**: retry_harness.py

**How it works**:
1. For step 0..4:
   - Step 0: base prompt
   - Step 1+: retry prompt with test output, error feedback, adaptive hints
   - call_model → parse_structured_output → evaluate
   - If pass: break
   - Classify failure, compute diff, check stagnation
2. Post-hoc analysis: trajectory dynamics, convergence, persistence, oscillation
3. All metrics logged but NOT used for control decisions (scientific instrument)

### 4.6 Logging System

**Files**: execution.py (RunLogger), live_metrics.py

**RunLogger**: Thread-safe JSONL writer. Three files per run: run.jsonl (metadata), run_prompts.jsonl (prompts), run_responses.jsonl (raw responses). Integrity verification at end.

**Live metrics**: emit_event() with schema validation and fsync. Dashboard process aggregates across run directories.

---

## 5. PROMPT + TEMPLATE SYSTEM

### Current System (f-string based)

**Templates stored in**: prompts.py (DIAGNOSTIC_NUDGES, GUARDRAIL_NUDGES), nudges/core.py (operator functions), scm_prompts.py, reasoning_prompts.py, contract.py, leg_reduction.py

**How rendered**: String concatenation. `build_base_prompt()` creates base, condition-specific functions append nudge/scaffold text.

**Variables injected**: task (case["task"]), code_files (formatted file blocks), failure_mode (for nudge lookup), hard_constraints (for strict guardrail)

**Prompt variant selection**: 25-branch if/elif in execution.py:build_prompt()

### New System (Jinja2 based — implemented but not yet wired in)

**Templates stored in**: templates/*.jinja2 (7 files)

**How rendered**: templates.py:render() with StrictUndefined + pre-render var set validation

**Variables injected**: declared per-template in TemplateSpec.required_vars

**Selection**: config.conditions[condition_name].template (from experiment.yaml)

### Example Flow (new system)

```
experiment.yaml: conditions.baseline.template = "base"
  → TEMPLATE_REGISTRY["base"]
  → TemplateSpec(path="templates/base.jinja2", required_vars={"task", "code_files_block"})
  → validate: provided == required
  → Jinja2 render: "{{ task }}\n\n{{ code_files_block }}"
  → rendered prompt logged with template_hash to run_prompts.jsonl
```

---

## 6. CONFIG SYSTEM

### Legacy Config

**File**: ablation_config.yaml (minimal, read by shell scripts only)

### New Config System (implemented, not yet integrated into runner.py production path)

**Files**: config.py, experiment.yaml, constants.py

**Schema**: experiment (version, name, models), conditions (per-condition template mapping), retry (enabled, max_steps, strategy), execution (parallel, cases_file, timeouts), logging (run_dir_pattern, log_resolved_config)

**Validation**: 9-step chain — file exists, YAML parse, top-level keys, version check, section validation, condition structural invariants (SIMPLE/RETRY/MULTISTEP), template registry references, file existence, freeze into frozen dataclasses.

**Structural invariants**: Simple conditions MUST NOT have retry_template. Retry conditions MUST have retry_template. Multistep conditions MUST have both retry_template and next_template.

---

## 7. MODEL INTERACTION LAYER

**Where API calls happen**: llm.py:_openai_call()

**Request construction**:
1. Prompt text (from build_prompt or condition-specific builder)
2. JSON output instruction appended (unless raw=True)
3. `client.responses.create(model=model, input=full_prompt, store=False, temperature=0.0)`

**Response parsing**: parse.py:parse_model_response() — 7-tier chain

**Error handling**:
- No retry on API errors (single call, fail fast)
- Mock fallback if no API key
- Parse fallback to raw text if no JSON/code blocks found
- SEVERE warnings logged for type mismatches and empty fields

---

## 8. DATA FLOW (END-TO-END)

Tracing case "alias_config_a" through baseline condition:

```
1. load_cases("cases_v2.json")
   → case = {id: "alias_config_a", task: "Refactor this configuration module...",
              code_files: ["code_snippets_v2/alias_config_a/config.py"],
              code_files_contents: {"code_snippets_v2/alias_config_a/config.py": "DEFAULTS = {...}\ndef create_config()..."}}

2. build_prompt(case, "baseline")
   → build_base_prompt(case["task"], case["code_files_contents"])
   → prompt = "Refactor this configuration module...\n\n## Codebase (1 file)\n### FILE 1/1: code_snippets_v2/alias_config_a/config.py ###\n```python\n...\n```"
   → operator_used = None

3. call_model(prompt + JSON_OUTPUT_INSTRUCTION_V2, model="gpt-4o-mini", file_paths=["code_snippets_v2/..."])
   → OpenAI API call
   → raw_output = '{"reasoning": "create_config returns DEFAULTS by reference...", "files": {"code_snippets_v2/alias_config_a/config.py": "DEFAULTS = {...}\ndef create_config():\n    return dict(DEFAULTS)"}}'

4. parse_model_response(raw_output)
   → _try_file_dict succeeds
   → parsed = {reasoning: "...", code: None, files: {"code_snippets_v2/.../config.py": "..."}, response_format: "file_dict"}

5. reconstruct_strict(manifest_paths, manifest_files, parsed["files"])
   → ReconstructionResult(status="SUCCESS", files={...}, changed_files=["code_snippets_v2/.../config.py"])
   → parsed["code"] = reconstructed changed files joined

6. evaluate_output(case, parsed)
   6a. exec_evaluate(case, parsed["code"])
       → _assemble_program(code, case) → assembled code string
       → load_module_from_code(assembled) → module
       → _load_v2_test(case) → test_a from tests_v2/test_alias_config.py
       → test_a(module) → (True, ["DEFAULTS not mutated"])
       → result = {pass: True, score: 1.0, ...}

   6b. llm_classify(case, code, reasoning)
       → classifier prompt with failure_types, task, code, reasoning
       → call_model → "YES ; ALIASING"
       → {reasoning_correct: True, failure_type: "ALIASING"}

   6c. compute_alignment(True, True)
       → {category: "true_success", ...}

   6d. compute_evidence_metrics(case, raw_output)
       → {has_scm: False, ...} (no SCM for this case)

   → final result = {pass: True, score: 1.0, code_correct: True, reasoning_correct: True,
                      alignment: {category: "true_success"}, ...}

7. write_log(case_id, "baseline", model, prompt, raw_output, parsed, ev)
   → RunLogger.write() → appends to run.jsonl, run_prompts.jsonl, run_responses.jsonl

8. _emit_metrics_event(case, model, "baseline", ev)
   → emit_event() → appends to events.jsonl with fsync
```

---

## 9. FAILURE POINTS / RISKS

### Silent Failures

1. **Legacy event emission** (execution.py:172): Entire `_emit_metrics_event` legacy path is wrapped in `try/except` that catches all exceptions and only logs a warning. Events can be silently lost.

2. **eval_cases.py heuristic evaluators** are still importable and technically accessible. If anyone calls `_eval_hidden_dep()` directly instead of `exec_evaluate()`, they get deprecated heuristic results without execution-based testing.

3. **_REASONING_SIGNALS** in evaluator.py is retained "for backward compat" but not used for decisions. Dead code that could confuse maintainers.

### Missing Error Handling

4. **`_openai_call`** has no retry logic, no rate limiting, no timeout. A hung API call blocks the entire run indefinitely (though MAX_ITERATION_SECONDS protects the retry harness).

5. **`load_module_from_code`** uses `exec()` on model-generated code with full `__builtins__`. Malicious model output could execute arbitrary code. (Acceptable for research but risky.)

### Fragile Parsing

6. **7-tier parse fallback**: The raw_fallback tier treats the entire response as code. If a model returns explanatory text, it becomes "code" that fails with cryptic SyntaxError rather than a clear parse error.

7. **`_try_json_lenient`**: Regex-based JSON extraction can silently truncate code if the model output contains a closing `"` followed by `}` inside a string literal.

### Concurrency Issues

8. **Module-level globals in execution.py**: `_ablation_events_path`, `_ablation_trial`, `_ablation_run_id` are set via `set_ablation_context()`. In parallel mode (max_workers > 1), all threads share these globals. This is safe in ablation mode (max_workers=1) but would corrupt events if parallel were enabled.

9. **sys.modules pollution**: `load_module_from_code` registers each module in `sys.modules`. Thousands of unique module names accumulate over a run. No cleanup.

### API Cost Risks

10. **No cost tracking**: Every `call_model()` is a paid API call. No budget limits, no cost estimation, no abort-on-budget. A misconfigured run with 58 cases x 25 conditions x 5 retry steps = 7,250+ API calls.

11. **Two LLM calls per eval**: Every evaluation calls both the generation model AND the classifier model (gpt-4.1-nano). Classifier calls are hidden inside `evaluate_output()`.

### Data Integrity

12. **No run-level deduplication**: If a run is interrupted and restarted with the same run_dir, events.jsonl gets duplicate entries. No mechanism to detect or deduplicate.

---

## 10. MOST IMPORTANT FUNCTIONS (TOP 10)

| Rank | Function | File | Why It Matters |
|---|---|---|---|
| 1 | `exec_evaluate()` | exec_eval.py | Sole authority for code correctness. If this is wrong, every metric is wrong. |
| 2 | `evaluate_output()` | evaluator.py | Orchestrates both eval axes (exec + LLM classify) and derives alignment. |
| 3 | `call_model()` | llm.py | Every interaction with the model flows through here. Mock/real routing. |
| 4 | `parse_model_response()` | parse.py | Extracts code from model output. Parse failures cascade to wrong evaluations. |
| 5 | `build_prompt()` | execution.py | 25-condition dispatch. Wrong prompt = wrong experiment. |
| 6 | `run_all()` | runner.py | Execution loop. Handles parallel/serial, exception recovery, result assembly. |
| 7 | `_assemble_program()` | exec_eval.py | Multi-file assembly. If originals and model code mix wrong, tests fail spuriously. |
| 8 | `emit_event()` | live_metrics.py | Durable event writing with fsync. Lost events = incomplete data. |
| 9 | `validate_run()` | condition_registry.py | Prevents invalid (case, condition) pairs. Without this, experiments waste API calls. |
| 10 | `RunLogger.write()` | execution.py | Thread-safe log writing with integrity tracking. Corrupted logs = invalid run. |

---

## 11. OPEN QUESTIONS / CONFUSIONS

1. **UNCLEAR**: `eval_cases.py` contains 16+ heuristic evaluators that appear to be fully deprecated (evaluator.py imports only `_has` and `_low` for backward compat). Why is this file still in the project? Could be deleted entirely unless retry_harness still uses `_detected_correct_reasoning()`.

2. **UNCLEAR**: `main.py` is a stub that prints "Hello from t3-code-generation!". It appears to serve no purpose. The actual entry point is `runner.py`.

3. **INCONSISTENCY**: `runner.py` has two modes (legacy and ablation) with significant code duplication. Both follow the same load → preflight → run → verify flow but with different setup and teardown.

4. **SUSPICIOUS**: The `USE_V2_OUTPUT_FORMAT = True` flag in llm.py is a module-level boolean that controls output instruction format globally. There's no way to run V1 and V2 format cases in the same experiment.

5. **INCONSISTENCY**: `execution.py:build_prompt()` returns `(base, "CONTRACT_GATED")` for contract_gated condition, but the actual prompt used in `run_contract_gated()` is built by `contract.py:build_contract_prompt()`, NOT by `build_prompt()`. The return value from `build_prompt()` is unused for this condition.

6. **RISK**: The new config/template system (config.py, templates.py, experiment.yaml) is fully implemented and tested but NOT wired into the production runner.py path. The `use_templates` flag mentioned in the plan doesn't exist yet. There's a gap between "implemented" and "integrated."

7. **UNCLEAR**: `retry_harness.py` signature was updated to accept `condition` as a parameter per the v3 plan, but the actual `run_retry_harness` function body in the codebase may still reference the old boolean flags internally. The runner.py dispatch was updated but the harness internals may not match.

8. **SUSPICIOUS**: `reconstructor.py` is not explicitly imported at the top of execution.py — it's imported inline inside `_attempt_and_evaluate()`. This is intentional (avoid import at module load) but means import errors would only surface at runtime during V2 file-dict responses.
