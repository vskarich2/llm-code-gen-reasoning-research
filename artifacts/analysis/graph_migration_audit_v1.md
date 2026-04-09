Date: 2026-04-09
Time: 14:30

# FORENSIC ARCHITECTURE AUDIT + GRAPH MIGRATION ANALYSIS

---

# PART 1 — CURRENT SYSTEM (GROUND TRUTH)

## 1. EXECUTION ENTRYPOINT

**File:** `core/pipeline/orchestration/runner.py`
**Function:** `main()` (line 684)

### Full Call Chain

```
runner.py:main()
  ├── load_config(args.config)                          # config/experiment_config.py
  ├── if trials > 1 or workers > 1:
  │     └── run_experiment(config, args)                # orchestrate.py:1211
  │           └── _run_experiment_inner(config, args, run_dir)  # orchestrate.py:1236
  │                 ├── resolve_case_ids(config)
  │                 ├── generate_work_items(config, case_ids)
  │                 ├── initialize_manifest()
  │                 └── [loop] launch_worker(item, config, run_dir)  # subprocess → runner.py
  └── else:
        └── run_ablation_mode(args)                     # runner.py:502
              ├── load_cases(case_id, cases_file)       # shared.py:69
              ├── preflight_verify_tests(cases)         # shared.py:106
              ├── RunLogger(run_dir, ...)               # logging_core.py
              └── run_all(cases, model, conditions, logger)  # runner.py:187
                    └── [loop] _run_one(case, model, condition, logger)  # runner.py:130
                          └── _run_one_inner(case, model, condition, logger, eid)  # runner.py:161
                                ├── baseline/leg conditions → run_v2()        # execution_v2.py:110
                                └── retry/critique conditions → run_retry_v2() # retry_v2.py:530
```

**Canonical entrypoint for a single case:** `execution_v2.py:run_v2()`
**Retry variant:** `retry_v2.py:run_retry_v2()`

**Dispatch logic** in `_run_one_inner()` (runner.py:164-184):
- Hard guard: validates condition is in `V2_CONDITIONS`
- Routes baseline/leg/lean conditions to `run_v2()`
- Routes retry/critique conditions to `run_retry_v2()`

---

## 2. FULL PIPELINE TRACE

### Canonical Pipeline (10 stages)

Each stage is a function in `core/pipeline/orchestration/stages.py` that mutates an `AttemptState` dataclass.

| Stage | Function | File:Line | Calls | Writes to State |
|-------|----------|-----------|-------|-----------------|
| 1. Generate | `stage_generate()` | stages.py:18 | `_render_generation_prompt()`, `_call_generation_model()` | prompt, raw_response, gen_event_id |
| 2. Parse | `stage_parse()` | stages.py:31 | `_parse_outputs()`, `_select_artifact()`, `_validate_structure()` | strict_parse, recovery_parse, parsed_gen, routing, parse_mode |
| 3. Oracle | `stage_oracle()` | stages.py:71 | `oracle_inline.py:run_oracle_evaluation()` | oracle_result |
| 4. Normalize | `stage_normalize()` | stages.py:81 | `reasoning_v2.py:normalize_generation_v2()` | artifact (NormalizedReasoningArtifactV2) |
| 5. Reconstruct | `stage_reconstruct()` | stages.py:88 | `_reconstruct()`, `_compute_artifact_id()` | recon, code, artifact_id |
| 6. Classify | `stage_classify()` | stages.py:98 | `evaluator_v2.py:classify_case()` | classifier_result, classify_event_id |
| 7. AST | `stage_ast()` | stages.py:111 | `_run_ast_verification()` | ast_result |
| 8. Execute | `stage_execute()` | stages.py:166 | `exec_canonical.py:exec_canonical()` | exec_result, passed |
| 8b. Spec Oracle | `stage_spec_oracle()` | stages.py:183 | `spec_oracle.py:run_spec_oracle()` | spec_oracle_result |
| 9. Derive Metrics | `stage_derive_metrics()` | stages.py:189 | `compute_disagreement()`, `_derive_metrics()`, `_compute_evaluation()` | disagreement, signals, evaluation |

**Post-pipeline:**
- `_assemble_result_from_state()` (execution_v2.py:163) — builds final event dict
- `_log_result()` (execution_v2.py:998) — emits case.end event

### Stage Detail: Prompt Construction

```
stage_generate() [stages.py:18]
  └── _render_generation_prompt(case, condition, config) [execution_v2.py:313]
        └── _prompt_compile(PromptProgram, variables, mode, registry)
              └── compiler.py:compile() — 6-stage pipeline:
                    1. Input normalization
                    2. Component resolution from PromptRegistry
                    3. Static validation (order, collisions)
                    4. Input validation (required fields)
                    5. Jinja2 render (env.from_string → template.render)
                    6. Post-compile validation (section parsing, marker stripping)
              └── Returns: CompiledPrompt(final_prompt, composition_hash, final_prompt_hash)
```

**Template files:** `core/prompts/components/*.j2`
**Registry:** `core/pipeline/prompting/registry.py:PromptRegistry`

### Stage Detail: LLM Call

```
_call_generation_model(prompt, model, ...) [execution_v2.py:390]
  └── llm.py:call_model(prompt, model, ...)
        ├── _is_anthropic_model(model) → route
        ├── _anthropic_call(prompt, model, api_key)
        │     └── anthropic.Anthropic().messages.create(model, messages, max_tokens, temperature)
        └── _openai_call(prompt, model, api_key)
              └── OpenAI().responses.create(model, input, temperature)
  └── Returns: ModelCallResult(response, event_id)
```

### Stage Detail: Parsing (3-tier)

```
_parse_outputs(raw_response, condition) [execution_v2.py:411]
  ├── parser_v2.py:parse_v2_execution(raw, condition)   # Tier 1: tolerant
  │     └── _strip_fences() → _find_json_block() → json.loads() → _validate_and_build()
  ├── parser_v2.py:parse_v2_recovery(raw, condition)    # Tier 2: repair
  └── parser_v2.py:parse_v2_format(raw, condition)      # Tier 3: strict
```

**Routing:** `_select_artifact(strict, recovery, case)` → selects best parse via validity cascade

### Stage Detail: Reconstruction

```
_reconstruct(parsed_gen, case, config) [execution_v2.py:447]
  └── reconstructor.py:reconstruct_strict(manifest_paths, manifest_files, model_files)
        5-gate validation:
        1. Exact UNCHANGED check → accept original
        2. Empty/whitespace check → RECON_EMPTY_FILE (blocks)
        3. No-change phrase detection → RECON_SENTINEL_MISMATCH (blocks)
        4. ast.parse() validation → RECON_INVALID_CODE (blocks)
        5. Semantic structure check → diagnostic only
```

### Stage Detail: Oracle

```
stage_oracle() [stages.py:71]
  └── oracle_inline.py:run_oracle_evaluation(root_cause, fix_strategy, case, ...)
        ├── oracle_eval/reasoning_truth.py:build_oracle_spec()    # extract ground truth
        ├── oracle_eval/reasoning_truth.py:load_buggy_code()      # read case files
        ├── oracle_eval/reasoning_truth.py:render_prompt()        # compile oracle prompt
        ├── llm.py:call_model()                                    # evaluator model call
        └── oracle_eval/reasoning_truth.py:parse_response()       # CORRECT|PARTIAL|WRONG|UNJUDGABLE
```

### Stage Detail: Classifier

```
stage_classify() [stages.py:98]
  └── execution_v2.py:_classify_reasoning()
        └── evaluator_v2.py:classify_case()
              ├── build_classifier_v2_vars()       # root_cause, fix_strategy, code, commitments, task
              ├── _compile_prompt_from_components() # compile classifier prompt
              ├── llm.py:call_model()               # evaluator model call
              └── parse_classifier_v3_output() or parse_classifier_v2_output()
```

**Output:** ClassifierResultV2 with 4 dimensions (reasoning_internal_consistency, commitments_internal_consistency, commitments_code_consistency, reasoning_code_alignment)

### Stage Detail: Execution

```
stage_execute() [stages.py:166]
  ├── SWE-bench cases: _swebench_exec_result(case) — uses pre-computed Docker results
  └── Benchmark cases: _execute(case, parsed_gen, recon, config, logger)
        └── exec_canonical.py:exec_canonical(case, parsed_gen, recon, config, logger, attempt)
```

### Stage Detail: Spec Oracle (DDC only)

```
stage_spec_oracle() [stages.py:183]
  └── spec_oracle.py:run_spec_oracle(case, exec_result)
        ├── _load_spec()           # load case spec module
        ├── build_patch_profiles() # run invariants for root_fix + traps
        └── classify_llm_depth()   # match LLM result to known depth profile
```

### Stage Detail: Metrics Derivation

```
stage_derive_metrics() [stages.py:189]
  ├── oracle_inline.py:compute_disagreement(classifier_result, oracle_result, config)
  ├── execution_v2.py:_derive_metrics(classifier_result, artifact, exec_result, parsed_gen)
  │     └── metrics_v2.py:derive_v2_signals() → V2Signals dataclass
  └── execution_v2.py:_compute_evaluation(routing, recon, exec_result, classification, oracle_result, artifact_id)
        → outcome_class, LEG, LEG_subtype, quadrant_RT, quadrant_RE
```

---

## 3. RETRY + CONTROL FLOW

**File:** `core/pipeline/orchestration/retry_v2.py`
**Function:** `run_retry_v2()` (line 530)

### Retry Loop Structure

```
run_retry_v2(case, model, condition, logger, case_start_eid)
  ├── max_attempts from config.conditions[condition].retry.max_attempts
  ├── attempt 0: run full pipeline (stages 1-9, same as run_v2)
  ├── if passed → return immediately
  ├── for k in 1..max_attempts:
  │     ├── _build_retry_prompt_for_attempt() — includes critique + hint text
  │     ├── _generate_critique() — runs critique variant (strict/moderate/aggressive/reasoning_only)
  │     ├── run full pipeline (stages 1-9 with new prompt)
  │     ├── store in trajectory list
  │     └── if passed → break
  ├── select_best_attempt() — first passing, or last
  └── _compute_evaluation_from_trajectory() → final evaluation dict
```

### Where Retry Decisions Occur

| Decision | Location | Mechanism |
|----------|----------|-----------|
| Retry eligibility | `stage_parse()` → `state.retry_eligible` | At least one executable parse exists |
| Retry trigger | `run_retry_v2()` loop condition | `k < max_iterations` AND `elapsed < max_total_seconds` |
| Critique generation | `_generate_critique()` in retry_v2.py | Calls evaluator model with critique prompt |
| Best attempt selection | `select_best_attempt()` in retry_v2.py | First passing attempt, or last |
| Oracle sampling | `parse_sampling_strategy()` + `should_run_oracle()` | Determines which attempts get full oracle eval |

### Failure Context Propagation

Failure context flows through the `AttemptState` dataclass. On retry:
1. Previous attempt's `exec_result`, `classifier_result`, `oracle_result` are available
2. Critique prompt is built from previous attempt's reasoning + execution feedback
3. New `AttemptState` is created for each retry attempt
4. All attempts stored in trajectory list for final selection

---

## 4. DATA FLOW

### Complete Data Flow Trace

```
task input (case dict from cases_v2.json)
  ↓ load_cases() [shared.py:69] — enriches with code_files, logical_file_keys
prompt (compiled template string)
  ↓ _render_generation_prompt() → compiler.py:compile()
model output (raw text string)
  ↓ llm.py:call_model() → anthropic/openai API
parsed structure (ParsedGenerationV2)
  ↓ parser_v2.py:parse_v2_execution/recovery/format()
  ↓ _select_artifact() → RoutingDecision
reconstructed files (ReconstructionResult)
  ↓ reconstructor.py:reconstruct_strict() — 5-gate validation
  ↓ materialized as code string with file markers
execution result (dict: pass, score, execution_category)
  ↓ exec_canonical.py:exec_canonical()
oracle result (dict: reasoning_truth, oracle_correct, justification)
  ↓ oracle_inline.py:run_oracle_evaluation()
classifier result (ClassifierResultV2: 4 dimensions + justifications)
  ↓ evaluator_v2.py:classify_case()
spec oracle result (dict: llm_depth, patch_profiles) [DDC only]
  ↓ spec_oracle.py:run_spec_oracle()
evaluation (dict: outcome_class, LEG, quadrants, signals)
  ↓ _compute_evaluation() + _derive_metrics()
metrics/logs (events.jsonl, calls/*.json, calls_flat.txt)
  ↓ logger.end_case() → emit_event("execution_eval")
```

### State Container

**File:** `core/pipeline/orchestration/attempt_state.py`
**Class:** `AttemptState` — mutable dataclass populated stage-by-stage

Fields populated per stage:
- Generation: `prompt`, `prompt_meta`, `raw_response`, `gen_event_id`
- Parsing: `strict_parse`, `recovery_parse`, `parsed_gen`, `routing`, `parse_mode`, `retry_eligible`
- Oracle: `oracle_result`
- Normalize: `artifact`
- Reconstruct: `recon`, `code`, `artifact_id`
- Classify: `classifier_result`, `classify_event_id`
- AST: `ast_result`
- Execute: `exec_result`, `passed`
- Spec Oracle: `spec_oracle_result`
- Metrics: `disagreement`, `signals`, `evaluation`

---

## 5. MODULE RESPONSIBILITY MAP

| Module | Responsibility | Calls | Called By | Violations |
|--------|---------------|-------|-----------|------------|
| `runner.py` | CLI entry, dispatch, case loading | orchestrate.py, execution_v2.py, retry_v2.py, shared.py | CLI/subprocess | Contains condition routing logic that duplicates knowledge of condition semantics |
| `orchestrate.py` | Multi-worker orchestration, manifest management | runner.py (via subprocess), manifest I/O | runner.py:main() | None identified |
| `execution_v2.py` | Single-case pipeline execution, helper functions | stages.py, parser_v2.py, reconstructor.py, evaluator_v2.py, llm.py, oracle_inline.py | runner.py:_run_one_inner() | Contains ~20 private helper functions that should be in their respective modules |
| `stages.py` | Stage function definitions (thin wrappers) | execution_v2.py helpers | execution_v2.py:run_v2(), retry_v2.py:run_retry_v2() | None — clean delegation |
| `retry_v2.py` | Retry loop orchestration, critique generation | stages.py (all stages), llm.py | runner.py:_run_one_inner() | Duplicates stage orchestration from run_v2() |
| `attempt_state.py` | Pipeline state container | None | stages.py, execution_v2.py, retry_v2.py | None |
| `parser_v2.py` | Response parsing (3-tier) | contracts_v2.py | execution_v2.py:_parse_outputs() | None |
| `reconstructor.py` | Code reconstruction from parsed files | ast module | execution_v2.py:_reconstruct() | None |
| `code_assembly.py` | Content normalization, assembly | None | reconstructor.py (indirectly) | Has both old CodeAssembler class and new reconstruct_strict path |
| `evaluator_v2.py` | Classifier prompt + parse | compiler.py, llm.py, contracts_v2.py | execution_v2.py:_classify_reasoning() | None |
| `oracle_inline.py` | Oracle evaluation orchestration | oracle_eval/reasoning_truth.py, llm.py | stages.py:stage_oracle() | None |
| `spec_oracle.py` | DDC depth classification | Case spec modules (dynamic import) | stages.py:stage_spec_oracle() | None |
| `metrics_v2.py` | Signal derivation, category computation | None | execution_v2.py:_derive_metrics() | None |
| `llm.py` | LLM API calls (Anthropic + OpenAI) | anthropic, openai SDKs | execution_v2.py, evaluator_v2.py, oracle_inline.py | None |
| `compiler.py` | Prompt template compilation | registry.py, jinja2 | execution_v2.py | None |
| `logging_core.py` | WAL event system, call logging | filesystem (atomic writes) | runner.py, execution_v2.py, retry_v2.py | Global singleton pattern for config |
| `experiment_config.py` | Config loading, validation | yaml | runner.py:main() | Global `_config` singleton accessed via get_config() everywhere |

---

## 6. V2 vs LEGACY COMPARISON

### execution_v2.py vs legacy

| Aspect | Current (v2) | Legacy | Status |
|--------|-------------|--------|--------|
| Entry | `run_v2()` | UNKNOWN — no legacy entrypoint found in current code | v2 is the only active path |
| Parsing | 3-tier: execution, recovery, format | UNKNOWN | v2 only |
| Reconstruction | `reconstruct_strict()` — 5-gate | `CodeAssembler.assemble()` in code_assembly.py | **BOTH exist** — CodeAssembler appears unused by the main pipeline |
| State | `AttemptState` dataclass | No equivalent | v2 only |

### parser_v2.py vs legacy

`parser_v2.py` is the only parser. No legacy parser file found. The 3-tier architecture (execution/recovery/format) is the current canonical implementation.

### evaluator_v2.py vs legacy

`evaluator_v2.py` is the only classifier. It supports both v2 and v3 output schemas via `classifier_schema_variant` config. No legacy evaluator found.

### Dead Code Identified

| File/Class | Evidence | Recommendation |
|------------|----------|----------------|
| `code_assembly.py:CodeAssembler` class | Not called by any stage; `reconstruct_strict()` in reconstructor.py is the active path | Dead code — verify and remove |
| `code_assembly.py:assemble()` module function | Wrapper for CodeAssembler | Dead code |

---

## 7. DUPLICATION + VIOLATIONS

### Duplicate Logic

| Duplication | Location 1 | Location 2 | Severity |
|-------------|-----------|-----------|----------|
| Stage orchestration | `execution_v2.py:run_v2()` calls stages 1-9 sequentially | `retry_v2.py:run_retry_v2()` calls same stages 1-9 in a loop | MEDIUM — same stage ordering duplicated |
| Evaluation assembly | `_compute_evaluation()` in execution_v2.py | `_compute_evaluation_from_trajectory()` in retry_v2.py | MEDIUM — parallel evaluation logic |
| Condition routing | `_run_one_inner()` in runner.py | Condition semantics also encoded in config parsing | LOW |

### Pipeline Bypasses

None identified. All execution flows through `_run_one_inner()` → `run_v2()` or `run_retry_v2()`.

### Mixed Responsibilities

| Issue | Location | Description |
|-------|----------|-------------|
| execution_v2.py is a monolith | execution_v2.py (~1000 lines) | Contains ~20 private helpers for prompt rendering, parsing dispatch, reconstruction, classification, metrics, assembly — these belong in their respective modules |
| Config as global singleton | experiment_config.py:get_config() | Called throughout pipeline instead of being passed as argument |

### Hidden State

| Issue | Location | Description |
|-------|----------|-------------|
| Global config singleton | experiment_config.py:_config | Set once, accessed everywhere via get_config() |
| Call logger globals | call_logger.py:_run_dir, _call_counter, _enabled | Global mutable state for call logging |
| AttemptState mutation | attempt_state.py | Stages mutate shared state object — no immutability guarantees |

---

# PART 2 — GRAPH RUNNER ANALYSIS

**Location:** `side_projects/graph_runner/`

## 1. GRAPH MODEL

### What a "Node" Represents

A node is a `StageSpec` (stage_spec.py):
```python
@dataclass
class StageSpec:
    name: str                                          # stage identifier
    input_keys: List[str]                              # expected artifact names
    output_keys: List[str]                             # declared output artifact names
    executor: Callable[[ExecutionState], StageResult]   # execution function
    guard: Optional[Callable[[ExecutionState], bool]]   # optional precondition
```

Each node declares its data dependencies (input_keys), outputs (output_keys), an executor function, and an optional guard predicate.

### How Transitions Are Defined

Transitions are implicit — the graph is a **linear sequence**. `GraphRunner.run()` iterates through `stages: List[StageSpec]` in order. Guard functions (transitions.py) control whether a stage executes:

- `has_prompt(state)` — checks `state.has("prompt")`
- `has_raw_response(state)` — checks `state.has("raw_response")`
- `can_execute(state)` — checks `state.has("parsed_response")` AND NOT `state.has("parse_error")`

### How Execution Proceeds

```python
# graph_runner.py:GraphRunner.run()
for stage in self.stages:
    if stage.should_run(state):       # evaluate guard
        stage.validate_inputs(state)  # check input_keys present
        result = stage.executor(state)
        state = result.state
return state
```

Strictly linear. No branching, no parallelism, no backtracking.

## 2. STATE MODEL

### Data Structure

**File:** `state.py`

```python
@dataclass(frozen=True)
class Artifact:
    id: str         # UUID
    type: str       # semantic label
    value: Any      # payload
    metadata: Dict[str, Any]

class ExecutionState:
    artifacts: Dict[str, Artifact]  # id → Artifact
    index: Dict[str, str]           # name → latest artifact id
```

**Two-layer lookup:** logical name → artifact UUID → Artifact object.

### Data Flow Between Stages

Stages read from state via `state.get("name")` and write via `state.add_artifact("name", artifact)`. All communication is through string-keyed artifacts in the shared `ExecutionState`.

### Mutability

`ExecutionState` is **mutable**. `Artifact` is frozen (immutable once created). Index overwrites previous entries for the same name but old artifacts are retained in the artifacts dict.

## 3. EXECUTION MODEL

### Stage Execution

Each stage's executor receives the full `ExecutionState`, reads its inputs, performs work, writes outputs, and returns a `StageResult(state, outcome)`.

### Failure Handling

Executors catch their own errors and return `StageResult(state, outcome="error")` with error artifacts. No global error recovery. No backtracking.

### Retries

**Not implemented.** `executors/retry.py` is empty. The `GraphRunner` has no retry loop.

## 4. MISSING PIECES

### Completely Stubbed (empty files)

| File | Intended Purpose |
|------|-----------------|
| `policy.py` | Retry/decision policies |
| `shadow_runner.py` | Shadow execution comparison |
| `executors/retry.py` | Retry logic |
| `executors/classify.py` | Reasoning classifier |
| `executors/critique.py` | Critique generation |
| `executors/diff_gate.py` | Diff-based gating |
| `executors/apply_nudge.py` | Hint/nudge application |
| `contracts/input_contract.py` | Input validation |

### Implemented But Incomplete

| Component | Issue |
|-----------|-------|
| `build_prompt_executor` | Minimal string formatting — no template system, no component compilation |
| `generate_executor` | Default mode returns hardcoded fake response; real LLM mode has no retry/error recovery |
| `GraphRunner` | Linear only — no DAG support, no branching, no conditional paths |
| `StageSpec.output_keys` | Declared but not enforced — executor can write anything |

### Architectural Gaps

- No oracle evaluation stage
- No spec oracle stage
- No normalization stage
- No AST verification stage
- No metrics derivation stage
- No logging/WAL integration
- No config system integration
- No multi-worker orchestration
- No artifact versioning/history

---

# PART 3 — MAPPING CURRENT SYSTEM → GRAPH

## 1. Pipeline Stage Mapping

| Current Stage | File:Function | Graph Node | Type | Notes |
|---------------|--------------|------------|------|-------|
| Prompt build | execution_v2.py:_render_generation_prompt() → compiler.py:compile() | `PromptBuildNode` | Pure transformation | Reads case + config, produces prompt string. No side effects. |
| LLM call | execution_v2.py:_call_generation_model() → llm.py:call_model() | `GenerateNode` | Side-effect boundary | External API call. Must handle timeouts, retries, logging. |
| Parse | execution_v2.py:_parse_outputs() → parser_v2.py:parse_v2_* | `ParseNode` | Pure transformation | 3-tier parsing, deterministic. |
| Route/select | execution_v2.py:_select_artifact() | `RouteNode` | Pure transformation | Selects best parse result. |
| Oracle eval | oracle_inline.py:run_oracle_evaluation() | `OracleNode` | Side-effect boundary | LLM call to evaluator model. |
| Normalize | reasoning_v2.py:normalize_generation_v2() | `NormalizeNode` | Pure transformation | Text normalization, commitment extraction. |
| Reconstruct | reconstructor.py:reconstruct_strict() | `ReconstructNode` | Pure transformation | 5-gate validation, deterministic. |
| Classify | evaluator_v2.py:classify_case() | `ClassifyNode` | Side-effect boundary | LLM call to evaluator model. MUST run before Execute. |
| AST verify | execution_v2.py:_run_ast_verification() | `ASTNode` | Pure transformation | ast.parse() check, deterministic. |
| Execute | exec_canonical.py:exec_canonical() | `ExecuteNode` | Side-effect boundary | Runs generated code in subprocess. |
| Spec Oracle | spec_oracle.py:run_spec_oracle() | `SpecOracleNode` | Pure transformation | Matches against known profiles, deterministic. DDC only. |
| Derive metrics | execution_v2.py:_compute_evaluation() + _derive_metrics() | `MetricsNode` | Pure transformation | Combines all signals into final evaluation. |
| Assemble result | execution_v2.py:_assemble_result_from_state() | `AssembleNode` | Pure transformation | Builds final event dict. |
| Log result | execution_v2.py:_log_result() → logger.end_case() | `LogNode` | Side-effect boundary | Writes to WAL (events.jsonl). |

### Classification Summary

| Type | Count | Stages |
|------|-------|--------|
| Pure transformation | 9 | PromptBuild, Parse, Route, Normalize, Reconstruct, AST, SpecOracle, Metrics, Assemble |
| Side-effect boundary | 5 | Generate (LLM), Oracle (LLM), Classify (LLM), Execute (subprocess), Log (filesystem) |

## 2. ORDERING CONSTRAINTS

```
PromptBuild → Generate → Parse → Route
                                    ↓
                              ┌─────┴─────┐
                              ↓           ↓
                           Oracle    Normalize
                              ↓           ↓
                              │     Reconstruct
                              │           ↓
                              │     ┌─────┴─────┐
                              │     ↓           ↓
                              │  Classify     AST
                              │     ↓           ↓
                              │     └─────┬─────┘
                              │           ↓
                              │       Execute
                              │           ↓
                              │     SpecOracle (DDC only)
                              │           ↓
                              └─────→ Metrics
                                        ↓
                                     Assemble
                                        ↓
                                       Log
```

**Critical ordering constraint:** Classify MUST run BEFORE Execute (preserves blindness — classifier does not see execution results).

**Parallelizable:**
- Oracle and Normalize can run in parallel (both depend only on parsed output)
- Classify and AST can run in parallel (both depend on reconstructed code)

## 3. STATE TRANSFORMATION

### Unified State Dict (inferred from AttemptState)

```python
state = {
    # Identity
    "case": dict,               # enriched case from load_cases()
    "condition": str,           # e.g., "baseline_v3"
    "model": str,               # e.g., "gpt-4o-mini"
    "config": ExperimentConfig, # frozen config

    # Stage 1: PromptBuild
    "prompt": str,              # compiled prompt string
    "prompt_meta": dict,        # prompt_family, prompt_hash, template_stack, variables_hash

    # Stage 2: Generate
    "raw_response": str,        # raw LLM output text
    "gen_event_id": int|str,    # logged event ID

    # Stage 3: Parse
    "strict_parse": ParsedGenerationV2,
    "recovery_parse": ParsedGenerationV2,
    "format_parse": ParsedGenerationV2,

    # Stage 4: Route
    "parsed_gen": ParsedGenerationV2,  # selected parse
    "routing": RoutingDecision,        # which parser was selected
    "parse_mode": str,                 # "strict"|"recovered"|"failed"
    "retry_eligible": bool,

    # Stage 5: Oracle
    "oracle_result": dict,      # reasoning_truth, oracle_correct, justification

    # Stage 6: Normalize
    "artifact": NormalizedReasoningArtifactV2,

    # Stage 7: Reconstruct
    "recon": ReconstructionResult,
    "code": str,                # materialized code with file markers
    "artifact_id": str,         # SHA256 hash

    # Stage 8: Classify
    "classifier_result": ClassifierResultV2,
    "classify_event_id": int|str,

    # Stage 9: AST
    "ast_result": dict,         # status, ast_correct, ast_score

    # Stage 10: Execute
    "exec_result": dict,        # pass, score, execution_category, reasons
    "passed": bool,

    # Stage 10b: Spec Oracle
    "spec_oracle_result": dict|None,

    # Stage 11: Metrics
    "disagreement": dict,
    "signals": V2Signals,
    "evaluation": dict,         # outcome_class, LEG, LEG_subtype, quadrants
}
```

---

# PART 4 — MIGRATION ANALYSIS

## 1. DIFFICULTY ASSESSMENT

| Subsystem | Current Location | Difficulty | Reason |
|-----------|-----------------|------------|--------|
| Prompt building | execution_v2.py:_render_generation_prompt() + compiler.py | **EASY** | Already pure: case + config → prompt string. No side effects. Direct lift into graph node. |
| Parsing | parser_v2.py:parse_v2_* + execution_v2.py:_select_artifact() | **EASY** | Pure functions: raw_response → ParsedGenerationV2. Deterministic. |
| Reconstruction | reconstructor.py:reconstruct_strict() | **EASY** | Pure function: parsed_files + manifest → ReconstructionResult. Deterministic. |
| Oracle evaluation | oracle_inline.py:run_oracle_evaluation() | **MEDIUM** | Requires LLM call (side effect). Self-contained but needs config, logger, case ground truth. Moderate coupling. |
| Classifier evaluation | evaluator_v2.py:classify_case() | **MEDIUM** | Requires LLM call (side effect). Needs config for template selection, logger for call logging. |
| Execution | exec_canonical.py:exec_canonical() | **MEDIUM** | Subprocess side effect. Needs case, recon, config. Self-contained but relies on test loader and materialization. |
| Spec Oracle | spec_oracle.py:run_spec_oracle() | **EASY** | Deterministic: exec_result + case spec → depth classification. No external calls. |
| Metrics derivation | metrics_v2.py:derive_v2_signals() + execution_v2.py:_compute_evaluation() | **EASY** | Pure computation. All inputs available in state. |
| Retry logic | retry_v2.py:run_retry_v2() | **HARD** | Tightly coupled to stage orchestration. Duplicates the entire pipeline loop. Critique generation requires previous attempt state. Must be redesigned as a graph-level control policy. |
| Logging | logging_core.py:RunLogger | **HARD** | Global singleton pattern. Called from multiple stages. WAL writes are side effects interleaved throughout pipeline. Must be redesigned as either: (a) a cross-cutting concern injected into each node, or (b) an event bus that nodes emit to. |
| Config | experiment_config.py:get_config() | **MEDIUM** | Global singleton accessed everywhere. Must be passed through state or injected as node context. |

## 2. BLOCKERS

### Hidden State

| Issue | Location | Impact on Migration |
|-------|----------|-------------------|
| Config singleton | experiment_config.py:_config | Every module calls get_config(). Must refactor to explicit parameter passing or state injection. |
| Call logger globals | call_logger.py:_run_dir, _call_counter | Stateful module-level variables. Must be replaced with logger instance in state. |
| RunLogger singleton | Created in runner.py, passed everywhere | Must become part of graph execution context. |

### Implicit Dependencies

| Stage | Declared Inputs | Actual Hidden Dependencies |
|-------|----------------|---------------------------|
| Oracle | root_cause, fix_strategy, case | config (oracle prompt template, partial_mode), logger, evaluator model name |
| Classify | artifact, case, code | config (classifier template, schema variant), logger, evaluator model name |
| Execute | parsed_gen, recon | config (execution settings), logger, test functions (loaded from case spec) |
| All LLM stages | prompt | API keys from environment, timeout from config |

### Tightly Coupled Logic

| Component | Coupling | Description |
|-----------|---------|-------------|
| execution_v2.py:_assemble_result() | Knows about ALL stages | Builds final event dict from all stage outputs. Must know the schema of every stage's output. |
| retry_v2.py:run_retry_v2() | Duplicates stage orchestration | Re-implements the same stage sequence as run_v2() with a loop wrapper. |
| runner.py:_run_one_inner() | Knows condition semantics | Routes conditions to run_v2() or run_retry_v2() based on condition name patterns. |

### Non-Composable Functions

| Function | Issue |
|----------|-------|
| `execution_v2.py:_render_generation_prompt()` | Reads from global config via get_config(). Should accept config as parameter. |
| `execution_v2.py:_call_generation_model()` | Couples LLM call + logging + event ID tracking. Should be split: call + log. |
| `execution_v2.py:_assemble_result()` | ~100 lines that know every stage's output schema. Should be auto-assembled from state. |

## 3. REQUIRED REFACTORING

### Functions to Split

| Current Function | Split Into | Reason |
|-----------------|-----------|--------|
| `_call_generation_model()` | `call_llm(prompt, model, config)` + `log_llm_call(result, logger)` | Separate side effect (API call) from logging |
| `_classify_reasoning()` | Already delegates to `classify_case()` — just remove wrapper | Thin wrapper adds no value |
| `run_retry_v2()` | Extract stage loop into reusable `run_pipeline_stages(state, stages)`, then wrap with retry policy | Eliminate duplicate stage orchestration |

### State to Centralize

| Current | Target |
|---------|--------|
| `AttemptState` (mutable dataclass) | Immutable state dict passed through graph. Each node returns new state. |
| Global config via `get_config()` | Config injected into graph execution context, accessible to all nodes without global state. |
| Logger passed as function parameter | Logger injected into graph execution context. |

### Side Effects to Isolate

| Side Effect | Current Location | Target |
|-------------|-----------------|--------|
| LLM API call | Embedded in `_call_generation_model()`, `classify_case()`, `run_oracle_evaluation()` | Dedicated `LLMCallNode` type with explicit timeout, retry, logging hooks |
| Subprocess execution | Embedded in `exec_canonical()` | Dedicated `SubprocessNode` with resource limits |
| WAL writes | `logger.emit_event()` called from multiple locations | Event bus pattern — nodes emit events, bus handles persistence |
| File I/O (prompt/call storage) | `call_logger.emit_call()`, `prompt_store.write_prompt()` | Artifact storage layer in graph framework |

### Modules to Decouple

| Module | From | How |
|--------|------|-----|
| execution_v2.py | stages.py, retry_v2.py | Extract ~20 helper functions into their respective domain modules (parser, reconstructor, evaluator, metrics) |
| experiment_config.py | All modules via get_config() | Pass config explicitly or inject into graph context |
| logging_core.py | All pipeline modules | Replace direct logger calls with event emission pattern |

## 4. TARGET DAG STRUCTURE

### Single-Shot DAG

```
                    TaskInput
                       ↓
                  PromptBuild         ← pure: case + config → prompt
                       ↓
                    Generate           ← side-effect: LLM API call
                       ↓
                     Parse             ← pure: raw_response → 3 parse results
                       ↓
                     Route             ← pure: select best parse
                       ↓
               ┌───────┴───────┐
               ↓               ↓
            Oracle          Normalize   ← parallel: both depend only on parsed output
               ↓               ↓
               │          Reconstruct   ← pure: parsed files → validated code
               │               ↓
               │         ┌─────┴─────┐
               │         ↓           ↓
               │      Classify      AST  ← parallel: both depend on reconstructed code
               │         ↓           ↓   ← Classify MUST complete before Execute
               │         └─────┬─────┘
               │               ↓
               │           Execute      ← side-effect: subprocess
               │               ↓
               │         SpecOracle     ← pure: exec_result → depth (DDC only, conditional)
               │               ↓
               └───────→ Metrics        ← pure: all signals → evaluation
                           ↓
                        Assemble        ← pure: state → result dict
                           ↓
                          Log           ← side-effect: WAL write
```

### Retry DAG (extends single-shot)

```
TaskInput → [Single-Shot DAG] → CheckPass
                                    ↓
                              ┌─ PASS ──→ FinalLog
                              │
                              └─ FAIL ──→ BuildCritique
                                              ↓
                                         [Single-Shot DAG with critique prompt]
                                              ↓
                                          CheckPass (loop up to max_attempts)
```

The retry loop is a **graph-level control policy**, not a stage. The `GraphRunner` must support conditional back-edges or a policy layer that re-enters the DAG with modified inputs.

### Required Graph Runner Extensions

| Feature | Current graph_runner | Required |
|---------|---------------------|----------|
| Linear execution | YES | YES (baseline) |
| Parallel stages | NO | YES (Oracle ‖ Normalize, Classify ‖ AST) |
| Conditional stages | Guard-based only | YES (SpecOracle only for DDC cases) |
| Retry/looping | NO | YES (retry policy as control layer) |
| Side-effect isolation | NO | YES (LLM calls, subprocess, file I/O) |
| Event bus / logging | NO | YES (WAL integration) |
| Config injection | NO | YES (replace global singleton) |
| Immutable state | Partial (Artifact frozen, State mutable) | YES (full immutability for reproducibility) |

---

# APPENDIX A — FILE INDEX

| Component | File Path |
|-----------|-----------|
| CLI Entry | core/pipeline/orchestration/runner.py |
| Orchestrator | core/pipeline/orchestration/orchestrate.py |
| V2 Pipeline | core/pipeline/orchestration/execution_v2.py |
| Pipeline Stages | core/pipeline/orchestration/stages.py |
| Retry Harness | core/pipeline/orchestration/retry_v2.py |
| State Container | core/pipeline/orchestration/attempt_state.py |
| Shared Utilities | core/pipeline/orchestration/shared.py |
| Prompt Compiler | core/pipeline/prompting/compiler.py |
| Prompt Registry | core/pipeline/prompting/registry.py |
| Prompt Templates | core/prompts/components/*.j2 |
| LLM Calls | core/pipeline/llm.py |
| Parser (v2) | core/pipeline/parsing/parser_v2.py |
| Reconstructor | core/pipeline/reconstructor.py |
| Code Assembly | core/pipeline/code_assembly.py |
| Execution | core/pipeline/execution/exec_canonical.py |
| Evaluator (Classifier) | core/evaluation/evaluator_v2.py |
| Oracle (Inline) | core/evaluation/oracle_inline.py |
| Oracle (Truth) | core/evaluation/oracle_eval/reasoning_truth.py |
| Spec Oracle | core/evaluation/spec_oracle.py |
| Metrics | core/evaluation/metrics_v2.py |
| Score Execution | core/evaluation/score_execution.py |
| Materialize | core/evaluation/materialize.py |
| Contracts | core/contracts/contracts_v2.py |
| Config | core/config/experiment_config.py |
| Logging Core | core/logging_/logging_core.py |
| Call Logger | core/logging_/call_logger.py |
| Prompt Store | core/logging_/prompt_store.py |
| V2 Metrics | core/logging_/v2_metrics.py |
| V2 Dashboard | core/logging_/v2_dashboard.py |
| Live Metrics | core/logging_/live_metrics.py |
| Graph Runner | side_projects/graph_runner/graph_runner.py |
| Graph Factory | side_projects/graph_runner/graph_factory.py |
| Stage Spec | side_projects/graph_runner/stage_spec.py |
| Graph State | side_projects/graph_runner/state.py |
| Transitions | side_projects/graph_runner/transitions.py |
| Exec Eval (Graph) | side_projects/graph_runner/executors/exec_eval.py |
| Generate (Graph) | side_projects/graph_runner/executors/generate.py |
| Build Prompt (Graph) | side_projects/graph_runner/executors/build_prompt.py |
| Parse (Graph) | side_projects/graph_runner/executors/reconstruct.py |
| Response Contract | side_projects/graph_runner/contracts/response_contract.py |
| Execution Contract | side_projects/graph_runner/contracts/execution_contract.py |
| Legacy Adapter | side_projects/graph_runner/adapters/legacy_adapter.py |
