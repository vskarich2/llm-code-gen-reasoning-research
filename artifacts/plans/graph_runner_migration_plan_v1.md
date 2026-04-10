Date: 2026-04-09
Time: 15:00

# GRAPH RUNNER MIGRATION PLAN v1

---

# SECTION 1 — SCOPE

## Files to Create

| File | Purpose |
|------|---------|
| `side_projects/graph_runner/nodes/__init__.py` | Node package init |
| `side_projects/graph_runner/nodes/prompt_build.py` | PromptBuildNode |
| `side_projects/graph_runner/nodes/generate.py` | GenerateNode (effect) |
| `side_projects/graph_runner/nodes/parse.py` | ParseNode |
| `side_projects/graph_runner/nodes/route.py` | RouteNode |
| `side_projects/graph_runner/nodes/normalize.py` | NormalizeNode |
| `side_projects/graph_runner/nodes/reconstruct.py` | ReconstructNode |
| `side_projects/graph_runner/nodes/ast_verify.py` | ASTNode |
| `side_projects/graph_runner/nodes/classify.py` | ClassifyNode (effect) |
| `side_projects/graph_runner/nodes/oracle.py` | OracleNode (effect) |
| `side_projects/graph_runner/nodes/execute.py` | ExecuteNode (effect) |
| `side_projects/graph_runner/nodes/spec_oracle.py` | SpecOracleNode (conditional) |
| `side_projects/graph_runner/nodes/metrics.py` | MetricsNode |
| `side_projects/graph_runner/nodes/assemble.py` | AssembleNode |
| `side_projects/graph_runner/nodes/log.py` | LogNode (effect) |
| `side_projects/graph_runner/dag.py` | DAG definition + construction |
| `side_projects/graph_runner/node_interface.py` | NodeSpec base class + StageResult contract |
| `side_projects/graph_runner/effect_wrapper.py` | Side-effect isolation wrappers |
| `side_projects/graph_runner/validation/diff_runner.py` | Differential testing harness |
| `side_projects/graph_runner/validation/__init__.py` | Validation package init |
| `core/tests/test_graph_runner_diff.py` | Differential test suite |

## Files to Modify

| File | Change |
|------|--------|
| `side_projects/graph_runner/state.py` | Extend ExecutionState with append-only enforcement and full state schema |
| `side_projects/graph_runner/stage_spec.py` | Extend StageSpec with effect/pure classification field |
| `side_projects/graph_runner/graph_runner.py` | Extend GraphRunner to support DAG execution order (topological sort) and conditional nodes |
| `side_projects/graph_runner/graph_factory.py` | Replace `build_minimal_graph()` with `build_v2_pipeline_graph()` using the 14-node DAG |
| `side_projects/graph_runner/transitions.py` | Add guard functions for all 14 nodes |

## Files NOT Modified

The following are **reused as-is** via import — no modifications:

- `core/pipeline/parsing/parser_v2.py` (parse_v2_execution, parse_v2_recovery, parse_v2_format)
- `core/pipeline/reconstructor.py` (reconstruct_strict)
- `core/evaluation/metrics_v2.py` (derive_v2_signals)
- `core/evaluation/spec_oracle.py` (run_spec_oracle)
- `core/evaluation/reasoning_v2.py` (normalize_generation_v2)
- `core/pipeline/llm.py` (call_model)
- `core/evaluation/evaluator_v2.py` (classify_case, build_classifier_v2_vars)
- `core/evaluation/oracle_inline.py` (run_oracle_evaluation, compute_disagreement)
- `core/pipeline/prompting/compiler.py` (compile)
- `core/pipeline/execution/exec_canonical.py` (exec_canonical)

## Files NOT Imported (Forbidden)

- `core/pipeline/orchestration/execution_v2.py` — orchestration monolith, not imported
- `core/pipeline/orchestration/retry_v2.py` — retry orchestration, not imported
- `core/pipeline/orchestration/stages.py` — V2 stage wrappers, not imported
- `core/pipeline/orchestration/runner.py` — CLI entry, not imported

---

# SECTION 2 — NODE IMPLEMENTATION PLAN

## Node Interface (node_interface.py)

All nodes implement a uniform interface:

```
NodeSpec:
    name: str
    input_keys: list[str]
    output_keys: list[str]
    node_type: "pure" | "effect"
    guard: Optional[Callable[[dict], bool]]
    execute: Callable[[dict], dict]
```

Contract:
- `execute(state) -> dict` returns ONLY the new keys (output_keys)
- The runner merges returned keys into state
- Nodes MUST NOT read keys outside their declared input_keys
- Nodes MUST NOT write keys outside their declared output_keys
- Nodes MUST NOT mutate the input state dict

---

## PURE NODES

### Node 1: PromptBuildNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/prompt_build.py` |
| **Source reused** | `core/pipeline/prompting/compiler.py:compile()`, `core/pipeline/prompting/registry.py:PromptRegistry` |
| **Inputs** | `["case", "condition", "config"]` |
| **Outputs** | `["prompt", "prompt_meta"]` |
| **Side effects** | None |
| **Logic** | Extract task, code_files, logical_file_keys from case. Build PromptProgram from config.conditions[condition].prompt_template. Compile via `compiler.compile(program, variables, mode, registry)`. Return `{"prompt": compiled.final_prompt, "prompt_meta": {prompt_family, prompt_hash, template_stack, variables_hash, composition_hash}}`. |
| **Risk** | PromptRegistry must be initialized before node runs. Registry is currently loaded globally. The node must accept a pre-initialized registry via the config or a context object — NOT via global state. |

### Node 2: ParseNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/parse.py` |
| **Source reused** | `parser_v2.py:parse_v2_execution()`, `parse_v2_recovery()`, `parse_v2_format()` |
| **Inputs** | `["raw_response", "condition"]` |
| **Outputs** | `["strict_parse", "recovery_parse", "format_parse"]` |
| **Side effects** | None |
| **Logic** | Call all three parsers on raw_response with condition. Return the three ParsedGenerationV2 objects. Pure function — parsers are stateless. |
| **Risk** | None. Parser functions are already pure. |

### Node 3: RouteNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/route.py` |
| **Source reused** | Inline reimplementation of `_select_artifact()` logic from execution_v2.py (lines 264-310). Cannot import execution_v2 — must extract the routing logic. |
| **Inputs** | `["strict_parse", "recovery_parse", "format_parse", "case"]` |
| **Outputs** | `["parsed_generation", "routing", "parse_mode", "retry_eligible"]` |
| **Side effects** | None |
| **Logic** | If strict_parse is valid, select it. Else if recovery_parse is valid, select it. Else failed. Build RoutingDecision. Set parse_mode ("strict" / "recovered" / "failed"). Set retry_eligible = at least one executable parse exists. |
| **Risk** | MEDIUM. The routing logic currently lives inside execution_v2.py as a private function. Since we cannot import execution_v2.py, we must reimplement. The logic is ~50 lines and purely conditional — no hidden dependencies. Must be tested for exact behavioral equivalence against `_select_artifact()`. |

### Node 4: NormalizeNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/normalize.py` |
| **Source reused** | `core/evaluation/reasoning_v2.py:normalize_generation_v2()` |
| **Inputs** | `["parsed_generation", "case", "condition"]` |
| **Outputs** | `["normalized_reasoning"]` |
| **Side effects** | None |
| **Logic** | Call `normalize_generation_v2(parsed_gen, case, condition)`. Return the NormalizedReasoningArtifactV2. |
| **Risk** | None. Function is already pure. |

### Node 5: ReconstructNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/reconstruct.py` |
| **Source reused** | `core/pipeline/reconstructor.py:reconstruct_strict()` |
| **Inputs** | `["parsed_generation", "case", "config"]` |
| **Outputs** | `["recon", "reconstructed_code", "artifact_id"]` |
| **Side effects** | None |
| **Logic** | Extract logical_file_keys and code_files from case. Extract files_dict from parsed_generation. Call `reconstruct_strict(manifest_paths, manifest_files, model_files)`. Build full materialized code string (concatenate files with markers). Compute artifact_id as SHA256 of sorted recon.files JSON (first 16 hex chars), or "no_artifact" if files empty. |
| **Risk** | LOW. The code materialization (building the full code string with markers) currently lives in `_reconstruct()` inside execution_v2.py. This is ~15 lines of string formatting that must be extracted. The SHA256 computation is ~5 lines from `_compute_artifact_id()`. Both are trivially reimplementable without importing execution_v2. |

### Node 6: ASTNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/ast_verify.py` |
| **Source reused** | Logic from `_run_ast_verification()` in execution_v2.py (line 821). |
| **Inputs** | `["recon", "case", "artifact_id"]` |
| **Outputs** | `["ast_result"]` |
| **Side effects** | None |
| **Logic** | For each file in recon.files, attempt `ast.parse()`. Report status ("validated" / "error" / "not_measurable"), ast_correct (bool), ast_score (float). |
| **Risk** | LOW. The AST verification is a pure function using only the stdlib `ast` module. Must reimplement ~30 lines. |

### Node 7: SpecOracleNode (conditional)

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/spec_oracle.py` |
| **Source reused** | `core/evaluation/spec_oracle.py:run_spec_oracle()` |
| **Inputs** | `["execution_result", "case"]` |
| **Outputs** | `["spec_oracle_result"]` |
| **Side effects** | None |
| **Logic** | Call `run_spec_oracle(case, exec_result)`. Returns dict or None (None for non-DDC cases). |
| **Guard** | `lambda state: state.get("case", {}).get("case_family", "") in DDC_FAMILIES` — only runs for DDC cases. |
| **Risk** | None. Function is already pure and self-contained. |

### Node 8: MetricsNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/metrics.py` |
| **Source reused** | `metrics_v2.py:derive_v2_signals()`, `oracle_inline.py:compute_disagreement()` |
| **Inputs** | `["classifier_result", "oracle_result", "execution_result", "normalized_reasoning", "parsed_generation", "artifact_id", "routing", "recon", "config"]` |
| **Outputs** | `["signals", "disagreement", "evaluation"]` |
| **Side effects** | None |
| **Logic** | 1. Call `compute_disagreement(classifier_result, oracle_result, config)` → disagreement dict. 2. Extract classifier dimensions from classifier_result. Call `derive_v2_signals(classifier_dims, code_correct, commitments_source)` → V2Signals. 3. Compute evaluation dict: outcome_class, LEG, LEG_subtype, quadrant_RT, quadrant_RE from oracle_correct + classifier_consistent + execution_pass + reconstruction_success + routing_valid + artifact_id. |
| **Risk** | MEDIUM. The `_compute_evaluation()` function (execution_v2.py:578, ~80 lines) encodes the outcome classification logic (interpretable_success, lucky_fix, LEG, coherent_incorrect, etc.). This logic cannot be imported from execution_v2.py and must be reimplemented. It is deterministic and testable — all inputs are booleans/strings. Must be validated for exact equivalence. |

### Node 9: AssembleNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/assemble.py` |
| **Source reused** | Logic from `_assemble_result_from_state()` + `_assemble_result()` in execution_v2.py |
| **Inputs** | ALL state keys (reads the full state to build the final event dict) |
| **Outputs** | `["final_result"]` |
| **Side effects** | None |
| **Logic** | Build the final event dict by reading all prior stage outputs from state. Structure matches the `case.end` event payload schema: root-level pass/fail/score fields, plus nested sections (reconstruction, classification, evaluation, ast_eval, oracle, reasoning_disagreement, spec_oracle). Also calls `assemble_v2_result()` from evaluator_v2.py for v2-specific fields. |
| **Risk** | HIGH. This is the largest reimplementation. `_assemble_result()` is ~100 lines that knows every stage's output schema. It must be reimplemented to produce byte-identical output for differential testing. Must be built incrementally and validated field-by-field. |

---

## EFFECT NODES

### Node 10: GenerateNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/generate.py` |
| **Source reused** | `core/pipeline/llm.py:call_model()` via effect wrapper |
| **Inputs** | `["prompt", "model", "config"]` |
| **Outputs** | `["raw_response", "gen_event_id"]` |
| **Side effects** | LLM API call (OpenAI or Anthropic). Logging via effect wrapper. |
| **Logic** | Call `call_model(prompt, model)` from llm.py. Return raw response text and event_id. The LLM call is wrapped in effect_wrapper.py which handles: timeout enforcement, error capture (never silent), call logging to the effect log. |
| **Risk** | LOW. `call_model()` is already self-contained. The wrapper adds logging context without modifying the call semantics. |

### Node 11: OracleNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/oracle.py` |
| **Source reused** | `core/evaluation/oracle_inline.py:run_oracle_evaluation()` via effect wrapper |
| **Inputs** | `["normalized_reasoning", "case", "config"]` |
| **Outputs** | `["oracle_result"]` |
| **Side effects** | LLM API call to evaluator model. |
| **Logic** | Extract raw_root_cause and raw_fix_strategy from normalized_reasoning artifact. Call `run_oracle_evaluation(raw_root_cause, raw_fix_strategy, case, config, logger=None, case_id, condition, parent_event_id=None)`. Return oracle_result dict. The logger parameter is passed as None — logging is handled by the effect wrapper, not by the oracle function itself. |
| **Risk** | MEDIUM. `run_oracle_evaluation()` currently accepts a logger parameter and uses it to log the LLM call. In the graph system, logging is handled by the effect wrapper. We pass `logger=None` and capture the call via the wrapper. Must verify that `run_oracle_evaluation()` does not crash when logger=None. Inspection of oracle_inline.py confirms it guards with `if logger:` before logging calls — this is safe. |

### Node 12: ClassifyNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/classify.py` |
| **Source reused** | `core/evaluation/evaluator_v2.py:classify_case()` via effect wrapper |
| **Inputs** | `["normalized_reasoning", "reconstructed_code", "case", "config"]` |
| **Outputs** | `["classifier_result", "classify_event_id"]` |
| **Side effects** | LLM API call to evaluator model. |
| **Logic** | Call `classify_case(artifact=normalized_reasoning, case=case, code=reconstructed_code, config=config, logger=wrapped_logger, parent_event_id=None, condition=condition, cid=case_id)`. Return (ClassifierResultV2, classify_event_id). |
| **Risk** | MEDIUM. `classify_case()` requires a logger to log the classifier LLM call. The effect wrapper must provide a minimal logger interface that captures the call metadata without writing to the V2 WAL directly. Alternative: pass `logger=None` if classify_case guards its logging. Must verify. If it does not guard, a thin adapter logger is required. |
| **CRITICAL CONSTRAINT** | ClassifyNode MUST execute BEFORE ExecuteNode. The DAG structure enforces this: Classify is an ancestor of Execute in the dependency graph. This preserves classifier blindness (classifier does not see execution results). |

### Node 13: ExecuteNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/execute.py` |
| **Source reused** | `core/pipeline/execution/exec_canonical.py:exec_canonical()` via effect wrapper |
| **Inputs** | `["recon", "parsed_generation", "case", "config"]` |
| **Outputs** | `["execution_result", "passed"]` |
| **Side effects** | Subprocess execution of generated code. |
| **Logic** | Call `exec_canonical(case, parsed_gen, recon, config, logger=None, attempt=0)`. Extract pass/fail, score, execution_category from result. Return `{"execution_result": exec_result, "passed": exec_result.get("pass", False)}`. |
| **Risk** | MEDIUM. `exec_canonical()` uses file materialization (writes temp files, runs subprocess). This is an inherent side effect. The effect wrapper must handle: temp directory cleanup, subprocess timeout enforcement, error capture. Must verify exec_canonical does not require a non-None logger. |

### Node 14: LogNode

| Property | Value |
|----------|-------|
| **File** | `side_projects/graph_runner/nodes/log.py` |
| **Source reused** | None — new implementation using effect wrapper |
| **Inputs** | `["final_result"]` |
| **Outputs** | `["log_status"]` |
| **Side effects** | WAL write (events.jsonl). |
| **Logic** | Write final_result dict as a JSON line to the graph runner's own events.jsonl output file. Do NOT write to the V2 WAL — the graph runner has its own output path. Return `{"log_status": "written"}`. |
| **Risk** | LOW. Simple append-only file write. Atomic write pattern (temp + fsync + rename) reused from logging_core.py. |

---

# SECTION 3 — GRAPH CONSTRUCTION

## Where the Graph is Defined

**File:** `side_projects/graph_runner/dag.py`

**Function:** `build_v2_pipeline_dag() -> list[NodeSpec]`

This function returns the complete ordered node list with dependency metadata.

## How Nodes Are Wired

The DAG is defined as an **adjacency list of dependencies** per node:

```
PIPELINE_DAG = {
    "prompt_build":  { depends_on: [] },
    "generate":      { depends_on: ["prompt_build"] },
    "parse":         { depends_on: ["generate"] },
    "route":         { depends_on: ["parse"] },
    "oracle":        { depends_on: ["route"] },
    "normalize":     { depends_on: ["route"] },
    "reconstruct":   { depends_on: ["normalize"] },
    "classify":      { depends_on: ["reconstruct"] },
    "ast_verify":    { depends_on: ["reconstruct"] },
    "execute":       { depends_on: ["classify", "ast_verify"] },
    "spec_oracle":   { depends_on: ["execute"] },
    "metrics":       { depends_on: ["oracle", "classify", "execute", "spec_oracle"] },
    "assemble":      { depends_on: ["metrics"] },
    "log":           { depends_on: ["assemble"] },
}
```

## How Dependencies Are Enforced

The `GraphRunner` must be extended to:

1. Accept the DAG adjacency list
2. Compute a topological sort to determine execution order
3. Before executing each node, verify all `depends_on` nodes have completed
4. For conditional nodes (spec_oracle), evaluate the guard before execution; if guard returns False, mark as "skipped" and propagate defaults

**Execution order** (one valid topological sort, respecting the critical Classify-before-Execute constraint):

```
1. prompt_build
2. generate
3. parse
4. route
5. oracle          (parallel-safe with normalize, but serial execution is acceptable)
6. normalize
7. reconstruct
8. classify        (MUST be before execute)
9. ast_verify      (parallel-safe with classify, but serial is acceptable)
10. execute        (depends on classify + ast_verify)
11. spec_oracle    (conditional: DDC only)
12. metrics
13. assemble
14. log
```

**Note on parallelism:** The DAG structure permits oracle || normalize and classify || ast_verify to run in parallel. Phase 1 uses serial execution. Future phases may add parallel dispatch within topological layers. AP-04 (unauthorized concurrency) forbids threading unless explicitly requested, so serial execution is the correct default.

---

# SECTION 4 — STATE MODEL DESIGN

## Full State Schema

```python
state: dict[str, Any] = {
    # --- Seeded at entry (not produced by any node) ---
    "case":       dict,               # enriched case from load_cases()
    "condition":  str,                 # e.g., "baseline_v3"
    "model":      str,                 # e.g., "gpt-4o-mini"
    "config":     ExperimentConfig,    # frozen config object (read-only)

    # --- Node 1: PromptBuildNode ---
    "prompt":      str,               # compiled prompt string
    "prompt_meta": dict,              # {prompt_family, prompt_hash, template_stack, ...}

    # --- Node 2: GenerateNode ---
    "raw_response":  str,             # raw LLM output text
    "gen_event_id":  int | str,       # event ID from call logging

    # --- Node 3: ParseNode ---
    "strict_parse":   ParsedGenerationV2,
    "recovery_parse": ParsedGenerationV2,
    "format_parse":   ParsedGenerationV2,

    # --- Node 4: RouteNode ---
    "parsed_generation": ParsedGenerationV2,  # selected parse
    "routing":           RoutingDecision,      # routing metadata
    "parse_mode":        str,                  # "strict" | "recovered" | "failed"
    "retry_eligible":    bool,

    # --- Node 5: OracleNode ---
    "oracle_result": dict,            # {reasoning_truth, oracle_correct, justification, ...}

    # --- Node 6: NormalizeNode ---
    "normalized_reasoning": NormalizedReasoningArtifactV2,

    # --- Node 7: ReconstructNode ---
    "recon":               ReconstructionResult,
    "reconstructed_code":  str,       # full materialized code with file markers
    "artifact_id":         str,       # SHA256 hash (16 hex chars) or "no_artifact"

    # --- Node 8: ClassifyNode ---
    "classifier_result":   ClassifierResultV2,
    "classify_event_id":   int | str,

    # --- Node 9: ASTNode ---
    "ast_result": dict,               # {status, ast_correct, ast_score}

    # --- Node 10: ExecuteNode ---
    "execution_result": dict,         # {pass, score, execution_category, reasons, ...}
    "passed":           bool,

    # --- Node 11: SpecOracleNode ---
    "spec_oracle_result": dict | None,  # None for non-DDC cases or when guard skips

    # --- Node 12: MetricsNode ---
    "signals":       V2Signals,       # derived signals dataclass
    "disagreement":  dict,            # {type, classifier_consistent, oracle_correct, disagreement}
    "evaluation":    dict,            # {outcome_class, LEG, LEG_subtype, quadrant_RT, quadrant_RE, ...}

    # --- Node 13: AssembleNode ---
    "final_result":  dict,            # complete event dict matching case.end payload schema

    # --- Node 14: LogNode ---
    "log_status":    str,             # "written" | "error"
}
```

## Append-Only Enforcement

The state dict is managed by the `GraphRunner`, not by nodes. Enforcement:

1. Before calling `node.execute(state)`, the runner creates a **frozen read-only view** containing only the keys declared in `node.input_keys`
2. The node returns a dict of new keys (must match `node.output_keys`)
3. The runner validates: (a) returned keys match output_keys exactly, (b) no returned key already exists in state
4. The runner merges the new keys into the state dict
5. If any returned key conflicts with an existing key, the runner raises an error (append-only violation)

This is enforced in the runner, not in individual nodes.

## Mapping from AttemptState to Dict

| AttemptState Field | State Dict Key | Populated By |
|--------------------|---------------|-------------|
| prompt | prompt | PromptBuildNode |
| prompt_meta | prompt_meta | PromptBuildNode |
| raw_response | raw_response | GenerateNode |
| gen_event_id | gen_event_id | GenerateNode |
| strict_parse | strict_parse | ParseNode |
| recovery_parse | recovery_parse | ParseNode |
| parsed_gen | parsed_generation | RouteNode |
| routing | routing | RouteNode |
| parse_mode | parse_mode | RouteNode |
| retry_eligible | retry_eligible | RouteNode |
| oracle_result | oracle_result | OracleNode |
| artifact | normalized_reasoning | NormalizeNode |
| recon | recon | ReconstructNode |
| code | reconstructed_code | ReconstructNode |
| artifact_id | artifact_id | ReconstructNode |
| classifier_result | classifier_result | ClassifyNode |
| classify_event_id | classify_event_id | ClassifyNode |
| ast_result | ast_result | ASTNode |
| exec_result | execution_result | ExecuteNode |
| passed | passed | ExecuteNode |
| spec_oracle_result | spec_oracle_result | SpecOracleNode |
| signals | signals | MetricsNode |
| disagreement | disagreement | MetricsNode |
| evaluation | evaluation | MetricsNode |

---

# SECTION 5 — EFFECT WRAPPING STRATEGY

## Effect Wrapper (effect_wrapper.py)

All side-effect nodes delegate through a uniform effect wrapper that provides:

1. **Timeout enforcement** — every external call has an explicit timeout from config
2. **Error capture** — exceptions are caught, wrapped in a structured error dict, and returned as the node output (never silently swallowed — INV-03)
3. **Call logging** — each effect call is recorded in a separate effect log (JSON lines file) with: timestamp, node_name, duration_ms, status (success/error), error_type if applicable
4. **No global state** — the wrapper is instantiated per-run with an output directory path, not a global singleton

### How llm.py is Wrapped

The GenerateNode, OracleNode, and ClassifyNode all call `llm.py:call_model()`.

Wrapping strategy:
- Each node receives a `call_model` function reference via the config/context (not via global import of execution_v2)
- The effect wrapper intercepts the call: records prompt hash, model name, starts timer
- Delegates to `llm.py:call_model(prompt, model)`
- Records response hash, duration, status
- Returns the result to the node
- The node never directly calls llm.py — it calls the wrapper

This allows: (a) mock injection for testing, (b) call logging without modifying llm.py, (c) timeout enforcement at the wrapper level.

### How Execution is Wrapped

The ExecuteNode calls `exec_canonical.py:exec_canonical()`.

Wrapping strategy:
- The effect wrapper creates a temp directory for materialized files
- Delegates to `exec_canonical(case, parsed_gen, recon, config, logger=None, attempt=0)`
- Captures the result dict
- Cleans up temp directory
- Records duration, status, any subprocess errors

### How Logging is Handled

The V2 system uses RunLogger (global singleton) for WAL writes. The graph runner does NOT use RunLogger.

Instead:
- Each effect node writes to a graph-runner-specific effect log via the effect wrapper
- The LogNode writes the final_result to graph-runner-specific `events.jsonl`
- For differential testing (Phase 4), the graph runner's events.jsonl is compared field-by-field against the V2 events.jsonl
- Future integration: once validated, the graph runner can emit events through a RunLogger adapter — but this is Phase 5+, not in scope

---

# SECTION 6 — VALIDATION PLAN

## Differential Testing Strategy

### Harness: `side_projects/graph_runner/validation/diff_runner.py`

For each test case:

```
1. Load case via shared.py:load_cases()
2. Run V2 pipeline: execution_v2.py:run_v2(case, model, condition, logger, eid)
   → capture (case_id, condition, v2_result)
3. Run graph pipeline: graph_runner with same case, model, condition, config
   → capture graph_result (final_result from state)
4. Compare field-by-field
5. Log all mismatches
```

### Fields Compared

| Field | Source (V2) | Source (Graph) | Comparison |
|-------|------------|----------------|------------|
| pass/fail | v2_result["pass"] | graph_result["pass"] | Exact match |
| score | v2_result["score"] | graph_result["score"] | Exact match |
| execution_category | v2_result["execution"]["execution_category"] | graph_result["execution_result"]["execution_category"] | Exact match |
| oracle_label | v2_result["oracle"]["reasoning_truth"] | graph_result["oracle_result"]["reasoning_truth"] | SKIP — oracle uses LLM, non-deterministic |
| classifier dims | v2_result["classification"] | graph_result["classifier_result"] | SKIP — classifier uses LLM, non-deterministic |
| outcome_class | v2_result["evaluation"]["outcome_class"] | graph_result["evaluation"]["outcome_class"] | Exact match (given same oracle/classifier) |
| recon status | v2_result["reconstruction"]["recon_status"] | graph_result["recon"].status | Exact match |
| artifact_id | v2_result["reconstruction"]["artifact_id"] | graph_result["artifact_id"] | Exact match |
| parse_mode | v2_result["reconstruction"]["parsing_mode"] | graph_result["parse_mode"] | Exact match |
| ast_result | v2_result["ast_eval"] | graph_result["ast_result"] | Exact match |
| spec_oracle depth | v2_result["spec_oracle"]["llm_depth"]["depth"] | graph_result["spec_oracle_result"]["llm_depth"]["depth"] | Exact match (DDC only) |

### Handling Non-Determinism

Oracle and classifier involve LLM calls that are non-deterministic (even at temperature=0, API responses can vary). Strategy:

1. **Phase 4a (deterministic stages only):** Compare ONLY pure stage outputs: parse results, routing, reconstruction, AST, artifact_id. These MUST be identical.
2. **Phase 4b (seeded LLM calls):** Fix the LLM seed (if API supports it) and compare oracle + classifier outputs. Accept small deviations.
3. **Phase 4c (full pipeline):** Run both pipelines end-to-end and compare evaluation/outcome_class. Mismatches are logged but not necessarily failures — they indicate oracle/classifier variance.

### Test Cases

| Category | Cases | Purpose |
|----------|-------|---------|
| DDC baseline (always-pass) | logging_pipeline_chain, ml_feature_chain | Verify full success path |
| DDC baseline (always-fail) | billing_aggregation_chain | Verify full failure path |
| DDC trap variant | event_etl_chain_trap_3 | Verify trap anchoring behavior |
| V2 simple case | lazy_init_a | Verify single-file case |
| V2 complex case | versioned_policy_fallback_regression_b | Verify multi-step reasoning |
| Parse failure case | (synthetic: malformed JSON response) | Verify parse failure path |
| Reconstruction failure | (synthetic: empty file in response) | Verify recon gate behavior |

### Expected Failure Modes

1. **Assembly schema mismatch:** AssembleNode produces a result dict with different field ordering or missing nested fields compared to V2's `_assemble_result()`. Mitigation: field-by-field comparison with explicit expected schema.
2. **Routing divergence:** RouteNode reimplements `_select_artifact()` and may differ on edge cases. Mitigation: test with all three parse tiers (strict-only, recovery-only, both-valid, neither-valid).
3. **Metrics computation drift:** MetricsNode reimplements `_compute_evaluation()` and may differ on edge case category assignments. Mitigation: test with all 8 v2_category values.

---

# SECTION 7 — MIGRATION PHASES

## Phase 1: Pure Nodes Only

**Scope:** Implement and test nodes 1-4, 6-9 (all pure nodes).

**Deliverables:**
- All pure node files in `nodes/`
- Updated `state.py` with append-only enforcement
- Updated `stage_spec.py` with pure/effect classification
- Unit tests for each pure node in isolation

**Validation:** Each node tested with fixture inputs matching V2 stage outputs. Output compared against V2 stage outputs for identical inputs.

**Exit criteria:** All pure nodes produce identical outputs to V2 stages for the same inputs.

## Phase 2: Add Effect Nodes

**Scope:** Implement nodes 10-14 (GenerateNode, OracleNode, ClassifyNode, ExecuteNode, LogNode) + effect_wrapper.py.

**Deliverables:**
- All effect node files in `nodes/`
- `effect_wrapper.py` with timeout, error capture, call logging
- Mock LLM interface for testing

**Validation:** Each effect node tested with mock LLM / mock subprocess. Output structure validated against expected schema.

**Exit criteria:** All effect nodes callable with mock backends and producing structurally valid outputs.

## Phase 3: Full DAG Execution

**Scope:** Wire all 14 nodes into the DAG. Extend `GraphRunner` for topological execution.

**Deliverables:**
- `dag.py` with `build_v2_pipeline_dag()`
- Extended `graph_runner.py` with DAG support
- Extended `transitions.py` with all guard functions
- End-to-end run on a single case with real LLM

**Validation:** Full pipeline run produces a complete state dict with all expected keys populated.

**Exit criteria:** Single case runs end-to-end without errors and produces structurally valid final_result.

## Phase 4: Differential Validation

**Scope:** Run both V2 and graph pipelines on the same cases and compare outputs.

**Deliverables:**
- `validation/diff_runner.py`
- `core/tests/test_graph_runner_diff.py`
- Comparison report for all test cases

**Validation:** Phase 4a (pure stages identical), Phase 4b (seeded LLM comparison), Phase 4c (full pipeline comparison).

**Exit criteria:** All deterministic outputs are identical. LLM-dependent outputs are within expected variance.

## Phase 5: Retry Integration (Future — NOT in this plan)

**Out of scope.** Retry is a graph-level control policy, not a node. Future work will:
- Define a RetryPolicy that wraps the entire DAG
- Re-enter the DAG at PromptBuildNode with modified inputs (critique prompt)
- Track attempt trajectories
- Select best attempt

This requires GraphRunner extensions (back-edges, policy hooks) not yet designed.

---

# SECTION 8 — RISKS

## 1. Hidden Dependencies in Reimplemented Functions

**Risk:** RouteNode, ReconstructNode (code materialization), ASTNode, MetricsNode (evaluation computation), and AssembleNode all reimplement logic currently in execution_v2.py. If execution_v2.py's private functions have undocumented behaviors (edge case handling, special-case branches), the reimplementation may diverge.

**Mitigation:** Differential testing (Phase 4) catches all divergences. Each reimplemented function is tested against V2 output for identical inputs.

## 2. State Mismatch Between AttemptState and Dict

**Risk:** AttemptState is a mutable dataclass with typed fields. The graph state is an untyped dict. Type mismatches (e.g., None vs missing key) could cause downstream nodes to behave differently.

**Mitigation:** The state schema (Section 4) defines explicit types and default values for each key. Nodes validate input types at entry. Missing keys raise immediately (fail-fast, INV-03).

## 3. Retry Complexity (Future)

**Risk:** The V2 retry system (retry_v2.py) tightly couples stage orchestration with retry policy, critique generation, and trajectory management. The graph runner must eventually replicate this as a graph-level policy, which requires: state snapshot/restore, modified prompt injection, trajectory tracking.

**Mitigation:** Phase 5 is explicitly deferred. The Phase 1-4 system runs single-shot only. Retry design will be planned separately after differential validation confirms single-shot equivalence.

## 4. Logging Divergence

**Risk:** The graph runner uses its own logging (effect_wrapper + LogNode) instead of the V2 RunLogger/WAL system. During the migration period, two logging systems coexist. Analysis tools that read events.jsonl may need adaptation.

**Mitigation:** The graph runner's events.jsonl uses the same event schema (case.end payload structure) as V2. The LogNode's output is schema-compatible. Existing analysis scripts can read either source. During Phase 4, both outputs are produced and compared.

## 5. Config Global Singleton

**Risk:** Many reused functions (e.g., classify_case, run_oracle_evaluation) call `get_config()` internally. The graph runner must ensure the config singleton is initialized before any node executes.

**Mitigation:** The graph runner entry point calls `load_config(yaml_path)` before constructing the DAG. Config is also passed through state as `state["config"]` for nodes that need it explicitly. The singleton is a read-only cache — it does not violate AP-02 (hidden state) because it is immutable after initialization.

## 6. Classifier/Oracle Logger Requirement

**Risk:** `classify_case()` and `run_oracle_evaluation()` accept a logger parameter and use it to log LLM calls. Passing `logger=None` may cause crashes if the functions do not guard their logging calls.

**Mitigation:** Verified in oracle_inline.py: `run_oracle_evaluation()` guards with `if logger:`. Must verify the same for `classify_case()` in evaluator_v2.py during Phase 2 implementation. If not guarded, a thin no-op logger adapter is provided.

---

# SECTION 9 — INVARIANT CHECK

## INV-01 — Single Canonical Execution Entry

**Status: SATISFIED.** The graph runner is a parallel system, not a replacement. During migration, two execution paths exist (V2 and graph), but they are explicitly separate — the graph runner is in `side_projects/` and does not share entrypoints with the V2 pipeline. After validation, the V2 path can be deprecated.

## INV-02 — Single Canonical Implementation Per Responsibility

**Status: TEMPORARY VIOLATION (PLANNED).** During Phases 1-4, routing logic (_select_artifact), evaluation computation (_compute_evaluation), and result assembly (_assemble_result) exist in both execution_v2.py and the graph runner's nodes. This is intentional and temporary — the graph runner implementations are validated against V2 via differential testing. After Phase 4 validation, the V2 implementations become the deprecated copies.

## INV-03 — No Silent Failure

**Status: SATISFIED.** All nodes fail-fast on invalid inputs (validate input_keys). Effect wrapper captures all exceptions and returns structured error dicts. No bare except, no except pass, no silent defaults.

## INV-04 — Explicit Contract Boundaries

**Status: SATISFIED.** Each node declares explicit input_keys and output_keys. The runner validates these at execution time. State schema defines types for all keys.

## INV-07 — Separation of Generation and Evaluation

**Status: SATISFIED.** ClassifyNode runs BEFORE ExecuteNode (enforced by DAG dependency: execute depends_on classify). The classifier never sees execution results. This is structurally guaranteed by the DAG, not by convention.

## INV-11 — Single Source of Truth for State

**Status: SATISFIED.** The state dict is the single source of truth. Each key is written exactly once (append-only enforcement). No shadow copies, no recomputation.

## INV-16 — Canonical Pipeline Structure

**Status: SATISFIED.** The DAG encodes the canonical pipeline: prompt → generate → parse → route → (oracle, normalize) → reconstruct → (classify, AST) → execute → spec_oracle → metrics → assemble → log. All stages exist explicitly. Ordering is preserved by topological sort. No stage is skipped (conditional nodes produce defaults when guard is false).

## INV-17 — No Pipeline Bypass

**Status: SATISFIED.** All execution flows through the DAG. Nodes cannot call other nodes directly — they only read from and write to the state dict. The runner is the sole orchestrator.

## INV-19 — Configuration Single Source of Truth

**Status: SATISFIED.** Config originates from YAML, loaded via `load_config()`. Passed through state as `state["config"]`. No shadow config, no Python defaults for required fields.

## No Global State (AP-02)

**Status: SATISFIED within graph_runner.** No `global` keyword, no module-level mutable state in any node. The config singleton (experiment_config.py) is pre-existing and read-only — it is not introduced by this migration.

## No Hidden Side Effects (AP-08, EC-06)

**Status: SATISFIED.** All side effects are isolated in effect nodes (GenerateNode, OracleNode, ClassifyNode, ExecuteNode, LogNode). Pure nodes have no side effects. The effect wrapper makes all side effects explicit and logged.

---

# SUMMARY

This plan defines a 14-node DAG that replicates the V2 pipeline using explicit state flow. 9 nodes are pure transformations. 5 nodes are effect boundaries. The DAG structurally enforces classifier-before-execute ordering. State is append-only. Differential testing validates equivalence. Retry is deferred to Phase 5.

No code. No shortcuts. No guesses.
