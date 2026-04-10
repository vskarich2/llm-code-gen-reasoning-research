Date: 2026-04-09
Time: 16:45

# GRAPH RUNNER MIGRATION PLAN v2

**Changes from v1:**
- Replaced single OracleNode and ClassifyNode with SLOT-BASED architecture
- Added NODE REGISTRY for config-driven node instantiation
- Added AGGREGATION NODES (OracleAggregationNode, ClassifierAggregationNode)
- Replaced state["oracle_result"] with state["oracle_results"] (namespaced dict)
- Replaced state["classifier_result"] with state["classifier_results"] (namespaced dict)
- Rewrote MetricsNode to consume aggregated outputs
- Rewrote graph builder to resolve slots dynamically from config
- Updated validation plan for multi-oracle/classifier scenarios
- Full DAG structure revised

**Why this change was necessary:** v1 assumed single oracle + single classifier, hardcoded in the DAG. This prevents adding new evaluation components without pipeline rewiring. The system must support config-driven activation of multiple oracles and classifiers with zero core changes.

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
| `side_projects/graph_runner/nodes/execute.py` | ExecuteNode (effect) |
| `side_projects/graph_runner/nodes/spec_oracle.py` | SpecOracleNode (conditional, pure) |
| `side_projects/graph_runner/nodes/metrics.py` | MetricsNode (consumes aggregated outputs) |
| `side_projects/graph_runner/nodes/assemble.py` | AssembleNode |
| `side_projects/graph_runner/nodes/log.py` | LogNode (effect) |
| `side_projects/graph_runner/nodes/oracles/__init__.py` | Oracle slot package |
| `side_projects/graph_runner/nodes/oracles/inline_oracle.py` | InlineOracleNode (effect) |
| `side_projects/graph_runner/nodes/oracles/oracle_aggregation.py` | OracleAggregationNode (pure) |
| `side_projects/graph_runner/nodes/classifiers/__init__.py` | Classifier slot package |
| `side_projects/graph_runner/nodes/classifiers/reasoning_classifier.py` | ReasoningClassifierNode (effect) |
| `side_projects/graph_runner/nodes/classifiers/classifier_aggregation.py` | ClassifierAggregationNode (pure) |
| `side_projects/graph_runner/registry.py` | Node registry (string ID → node factory) |
| `side_projects/graph_runner/dag.py` | DAG definition + dynamic construction |
| `side_projects/graph_runner/node_interface.py` | NodeSpec base class + StageResult contract |
| `side_projects/graph_runner/effect_wrapper.py` | Side-effect isolation wrappers |
| `side_projects/graph_runner/validation/diff_runner.py` | Differential testing harness |
| `side_projects/graph_runner/validation/__init__.py` | Validation package init |
| `core/tests/test_graph_runner_diff.py` | Differential test suite |

## Files to Modify

| File | Change |
|------|--------|
| `side_projects/graph_runner/state.py` | Extend ExecutionState with append-only enforcement, namespaced collection support |
| `side_projects/graph_runner/stage_spec.py` | Extend StageSpec with effect/pure classification, slot membership field |
| `side_projects/graph_runner/graph_runner.py` | Extend GraphRunner for DAG execution (topological sort), conditional nodes, slot execution |
| `side_projects/graph_runner/graph_factory.py` | Replace `build_minimal_graph()` with `build_pipeline_dag(config)` using registry + config-driven slot resolution |
| `side_projects/graph_runner/transitions.py` | Add guard functions for all nodes including slot members |

## Files Reused As-Is (NOT Modified)

- `core/pipeline/parsing/parser_v2.py` — parse_v2_execution, parse_v2_recovery, parse_v2_format
- `core/pipeline/reconstructor.py` — reconstruct_strict
- `core/evaluation/metrics_v2.py` — derive_v2_signals
- `core/evaluation/spec_oracle.py` — run_spec_oracle
- `core/evaluation/reasoning_v2.py` — normalize_generation_v2
- `core/pipeline/llm.py` — call_model
- `core/evaluation/evaluator_v2.py` — classify_case, build_classifier_v2_vars, _extract_canonical_dims
- `core/evaluation/oracle_inline.py` — run_oracle_evaluation, compute_disagreement
- `core/pipeline/prompting/compiler.py` — compile
- `core/pipeline/execution/exec_canonical.py` — exec_canonical

## Files NOT Imported (Forbidden)

- `core/pipeline/orchestration/execution_v2.py`
- `core/pipeline/orchestration/retry_v2.py`
- `core/pipeline/orchestration/stages.py`
- `core/pipeline/orchestration/runner.py`

---

# SECTION 2 — NODE IMPLEMENTATION PLAN

## Node Interface (node_interface.py)

All nodes implement a uniform interface:

```
NodeSpec:
    node_id: str               # unique instance ID (e.g., "oracle.inline", "classifier.v3")
    name: str                  # human-readable name
    input_keys: list[str]      # explicit state keys read
    output_keys: list[str]     # explicit state keys written
    node_type: "pure" | "effect"
    slot: str | None           # None for fixed nodes; "oracle" or "classifier" for slot members
    guard: Callable | None     # optional precondition
    execute: Callable          # (state: dict) -> dict
```

Contract:
- `execute(state) -> dict` returns ONLY the new keys (output_keys)
- The runner merges returned keys into state
- Nodes MUST NOT read keys outside their declared input_keys
- Nodes MUST NOT write keys outside their declared output_keys
- Nodes MUST NOT mutate the input state dict

**Slot nodes** have a special output convention:
- Oracle slot nodes write to `state["oracle_results"][node_id]` (not a top-level key)
- Classifier slot nodes write to `state["classifier_results"][node_id]` (not a top-level key)
- The runner handles merging into the namespaced collection (see Section 4)

---

## FIXED PURE NODES (Unchanged from v1)

### Node 1: PromptBuildNode

| Property | Value |
|----------|-------|
| **File** | `nodes/prompt_build.py` |
| **Source** | `core/pipeline/prompting/compiler.py:compile()` |
| **Inputs** | `["case", "condition", "config"]` |
| **Outputs** | `["prompt", "prompt_meta"]` |
| **Side effects** | None |
| **Risk** | PromptRegistry must be pre-initialized. Pass via config context, not global state. |

### Node 2: ParseNode

| Property | Value |
|----------|-------|
| **File** | `nodes/parse.py` |
| **Source** | `parser_v2.py:parse_v2_execution()`, `parse_v2_recovery()`, `parse_v2_format()` |
| **Inputs** | `["raw_response", "condition"]` |
| **Outputs** | `["strict_parse", "recovery_parse", "format_parse"]` |
| **Side effects** | None |
| **Risk** | None. Parsers are pure. |

### Node 3: RouteNode

| Property | Value |
|----------|-------|
| **File** | `nodes/route.py` |
| **Source** | Reimplemented from `_select_artifact()` logic (execution_v2.py:264-310) |
| **Inputs** | `["strict_parse", "recovery_parse", "format_parse", "case"]` |
| **Outputs** | `["parsed_generation", "routing", "parse_mode", "retry_eligible"]` |
| **Side effects** | None |
| **Risk** | MEDIUM. Routing logic reimplemented (~50 lines). Must validate for exact equivalence. |

### Node 4: NormalizeNode

| Property | Value |
|----------|-------|
| **File** | `nodes/normalize.py` |
| **Source** | `reasoning_v2.py:normalize_generation_v2()` |
| **Inputs** | `["parsed_generation", "case", "condition"]` |
| **Outputs** | `["normalized_reasoning"]` |
| **Side effects** | None |
| **Risk** | None. |

### Node 5: ReconstructNode

| Property | Value |
|----------|-------|
| **File** | `nodes/reconstruct.py` |
| **Source** | `reconstructor.py:reconstruct_strict()` |
| **Inputs** | `["parsed_generation", "case", "config"]` |
| **Outputs** | `["recon", "reconstructed_code", "artifact_id"]` |
| **Side effects** | None |
| **Risk** | LOW. Code materialization + SHA256 ID reimplemented (~20 lines). |

### Node 6: ASTNode

| Property | Value |
|----------|-------|
| **File** | `nodes/ast_verify.py` |
| **Source** | Reimplemented from `_run_ast_verification()` (execution_v2.py:821) |
| **Inputs** | `["recon", "case", "artifact_id"]` |
| **Outputs** | `["ast_result"]` |
| **Side effects** | None |
| **Risk** | LOW. Pure ast.parse() check (~30 lines). |

### Node 7: SpecOracleNode (conditional)

| Property | Value |
|----------|-------|
| **File** | `nodes/spec_oracle.py` |
| **Source** | `spec_oracle.py:run_spec_oracle()` |
| **Inputs** | `["execution_result", "case"]` |
| **Outputs** | `["spec_oracle_result"]` |
| **Side effects** | None |
| **Guard** | `case.get("case_family", "") in DDC_FAMILIES` |
| **Risk** | None. |

### Node 8: MetricsNode (REDESIGNED — see Section 8)

| Property | Value |
|----------|-------|
| **File** | `nodes/metrics.py` |
| **Source** | `metrics_v2.py:derive_v2_signals()`, `oracle_inline.py:compute_disagreement()` |
| **Inputs** | `["oracle_summary", "classifier_summary", "execution_result", "normalized_reasoning", "parsed_generation", "artifact_id", "routing", "recon", "config"]` |
| **Outputs** | `["signals", "disagreement", "evaluation"]` |
| **Side effects** | None |
| **Key change from v1** | Reads from `oracle_summary` and `classifier_summary` (aggregated outputs), NOT from raw individual results. |
| **Risk** | MEDIUM. Must produce identical evaluation dict for single-oracle/single-classifier configs. |

### Node 9: AssembleNode

| Property | Value |
|----------|-------|
| **File** | `nodes/assemble.py` |
| **Source** | Reimplemented from `_assemble_result_from_state()` + `_assemble_result()` |
| **Inputs** | ALL state keys |
| **Outputs** | `["final_result"]` |
| **Side effects** | None |
| **Risk** | HIGH. ~100 lines of schema knowledge. Must validate field-by-field. |

---

## FIXED EFFECT NODES (Unchanged from v1)

### Node 10: GenerateNode

| Property | Value |
|----------|-------|
| **File** | `nodes/generate.py` |
| **Source** | `llm.py:call_model()` via effect wrapper |
| **Inputs** | `["prompt", "model", "config"]` |
| **Outputs** | `["raw_response", "gen_event_id"]` |
| **Side effects** | LLM API call |
| **Risk** | LOW. |

### Node 11: ExecuteNode

| Property | Value |
|----------|-------|
| **File** | `nodes/execute.py` |
| **Source** | `exec_canonical.py:exec_canonical()` via effect wrapper |
| **Inputs** | `["recon", "parsed_generation", "case", "config"]` |
| **Outputs** | `["execution_result", "passed"]` |
| **Side effects** | Subprocess execution |
| **CRITICAL CONSTRAINT** | MUST execute AFTER all classifier slot nodes and ClassifierAggregation. DAG structure enforces this. |
| **Risk** | MEDIUM. |

### Node 12: LogNode

| Property | Value |
|----------|-------|
| **File** | `nodes/log.py` |
| **Inputs** | `["final_result"]` |
| **Outputs** | `["log_status"]` |
| **Side effects** | WAL write |
| **Risk** | LOW. |

---

## ORACLE SLOT NODES (NEW in v2)

### Slot Node: InlineOracleNode

| Property | Value |
|----------|-------|
| **File** | `nodes/oracles/inline_oracle.py` |
| **Registry ID** | `"oracle.inline"` |
| **Source** | `oracle_inline.py:run_oracle_evaluation()` via effect wrapper |
| **Inputs** | `["normalized_reasoning", "case", "config"]` |
| **Outputs** | Writes to `oracle_results["oracle.inline"]` |
| **Side effects** | LLM API call to evaluator model |
| **Logic** | Extract raw_root_cause and raw_fix_strategy from normalized_reasoning. Call `run_oracle_evaluation(raw_root_cause, raw_fix_strategy, case, config, logger=None, case_id, condition)`. Return oracle_result dict. |
| **Risk** | MEDIUM. run_oracle_evaluation() accepts logger=None safely (verified: guards with `if logger:`). |

**Adding a new oracle:** Create a new file in `nodes/oracles/`, register it in the registry (e.g., `"oracle.enriched"`), and add it to config. No existing files change.

### Aggregation Node: OracleAggregationNode

| Property | Value |
|----------|-------|
| **File** | `nodes/oracles/oracle_aggregation.py` |
| **Inputs** | `["oracle_results"]` |
| **Outputs** | `["oracle_summary"]` |
| **Side effects** | None |
| **Logic** | Receives `oracle_results: dict[str, dict]` where each value is one oracle's output. Produces `oracle_summary` dict containing: (a) `primary`: the result from the first oracle in config order (backward compat), (b) `all`: the full oracle_results dict, (c) `oracle_correct`: bool from primary oracle, (d) `reasoning_truth`: label from primary oracle. |
| **Backward compatibility** | When config has exactly one oracle (the default), `oracle_summary.primary` is identical to the old `oracle_result`. MetricsNode reads `oracle_summary.primary` for its single-oracle code path. |
| **Risk** | LOW. Pure dict transformation. The "primary" designation is explicit — first oracle in config list. |

---

## CLASSIFIER SLOT NODES (NEW in v2)

### Slot Node: ReasoningClassifierNode

| Property | Value |
|----------|-------|
| **File** | `nodes/classifiers/reasoning_classifier.py` |
| **Registry ID** | `"classifier.reasoning_v3"` (or `"classifier.reasoning_v2"` depending on config) |
| **Source** | `evaluator_v2.py:classify_case()` via effect wrapper |
| **Inputs** | `["normalized_reasoning", "reconstructed_code", "case", "config"]` |
| **Outputs** | Writes to `classifier_results["classifier.reasoning_v3"]` |
| **Side effects** | LLM API call to evaluator model |
| **Logic** | Call `classify_case(artifact=normalized_reasoning, case=case, code=reconstructed_code, config=config, logger=wrapped_logger_or_None, parent_event_id=None, condition=condition, cid=case_id)`. Return (ClassifierResultV2, classify_event_id) stored as dict in classifier_results. |
| **CRITICAL CONSTRAINT** | All classifier slot nodes MUST complete BEFORE ExecuteNode. Enforced by DAG: Execute depends on ClassifierAggregation, which depends on all classifier slot nodes. |
| **Risk** | MEDIUM. Must verify classify_case() is safe with logger=None. If not, provide no-op logger adapter. |

**Adding a new classifier:** Create a new file in `nodes/classifiers/`, register it (e.g., `"classifier.behavioral_v1"`), and add it to config. No existing files change.

### Aggregation Node: ClassifierAggregationNode

| Property | Value |
|----------|-------|
| **File** | `nodes/classifiers/classifier_aggregation.py` |
| **Inputs** | `["classifier_results"]` |
| **Outputs** | `["classifier_summary"]` |
| **Side effects** | None |
| **Logic** | Receives `classifier_results: dict[str, dict]` where each value contains a ClassifierResultV2 (or dict equivalent) and its event_id. Produces `classifier_summary` dict containing: (a) `primary`: the result from the first classifier in config order, (b) `all`: the full classifier_results dict, (c) `canonical_dims`: canonical dimensions from primary classifier via `_extract_canonical_dims()`, (d) `classify_event_id`: from primary classifier. |
| **Backward compatibility** | When config has exactly one classifier, `classifier_summary.primary` is identical to the old `classifier_result`. MetricsNode reads `classifier_summary.primary` for its single-classifier code path. |
| **Risk** | LOW. Uses `_extract_canonical_dims()` from evaluator_v2.py as the single source of truth for dimension mapping. |

---

# SECTION 3 — GRAPH CONSTRUCTION

## Node Registry (registry.py)

**Purpose:** Maps string node IDs to node factory functions. All node instantiation goes through the registry. No inline construction allowed.

**Structure:**

```
REGISTRY: dict[str, Callable[..., NodeSpec]] = {
    # Fixed nodes (always present)
    "prompt_build":             PromptBuildNode,
    "generate":                 GenerateNode,
    "parse":                    ParseNode,
    "route":                    RouteNode,
    "normalize":                NormalizeNode,
    "reconstruct":              ReconstructNode,
    "ast_verify":               ASTNode,
    "execute":                  ExecuteNode,
    "spec_oracle":              SpecOracleNode,
    "metrics":                  MetricsNode,
    "assemble":                 AssembleNode,
    "log":                      LogNode,

    # Oracle slot nodes
    "oracle.inline":            InlineOracleNode,

    # Classifier slot nodes
    "classifier.reasoning_v3":  ReasoningClassifierNode,

    # Aggregation nodes (auto-inserted, not in config)
    "oracle_aggregation":       OracleAggregationNode,
    "classifier_aggregation":   ClassifierAggregationNode,
}
```

**Extension contract:** To add a new oracle or classifier:
1. Create the node file in `nodes/oracles/` or `nodes/classifiers/`
2. Add one entry to REGISTRY
3. Add the string ID to the YAML config

No other files change. No rewiring. No core modifications.

## Config-Driven Node Selection

**Config structure (YAML):**

```yaml
graph_runner:
  oracles:
    - oracle.inline           # the default
  classifiers:
    - classifier.reasoning_v3  # the default
```

**Default config** (when graph_runner section is absent):

```yaml
graph_runner:
  oracles:
    - oracle.inline
  classifiers:
    - classifier.reasoning_v3
```

The builder reads `config.graph_runner.oracles` and `config.graph_runner.classifiers` to determine which slot nodes to instantiate.

## Graph Builder (dag.py)

**Function:** `build_pipeline_dag(config) -> tuple[list[NodeSpec], dict[str, list[str]]]`

Returns: (ordered node list, adjacency list)

**Builder algorithm:**

```
1. Instantiate all FIXED nodes from registry:
   prompt_build, generate, parse, route, normalize, reconstruct,
   ast_verify, execute, spec_oracle, metrics, assemble, log

2. Read config.graph_runner.oracles → list of oracle IDs
   For each oracle_id:
     - Look up in REGISTRY → instantiate node with node_id = oracle_id
     - Set node.slot = "oracle"
     - Add to oracle_slot_nodes list

3. Read config.graph_runner.classifiers → list of classifier IDs
   For each classifier_id:
     - Look up in REGISTRY → instantiate node with node_id = classifier_id
     - Set node.slot = "classifier"
     - Add to classifier_slot_nodes list

4. Instantiate aggregation nodes:
   - OracleAggregationNode (depends on all oracle slot nodes)
   - ClassifierAggregationNode (depends on all classifier slot nodes)

5. Build adjacency list (dependencies):
   FIXED_DEPS = {
     "prompt_build":              [],
     "generate":                  ["prompt_build"],
     "parse":                     ["generate"],
     "route":                     ["parse"],
     "normalize":                 ["route"],
     "reconstruct":               ["normalize"],
     "ast_verify":                ["reconstruct"],
     "execute":                   ["classifier_aggregation", "ast_verify"],
     "spec_oracle":               ["execute"],
     "metrics":                   ["oracle_aggregation", "classifier_aggregation",
                                   "execute", "spec_oracle"],
     "assemble":                  ["metrics"],
     "log":                       ["assemble"],
   }

   SLOT_DEPS:
   - Each oracle slot node depends on: ["route"]
   - oracle_aggregation depends on: [all oracle slot node IDs]
   - Each classifier slot node depends on: ["reconstruct"]
   - classifier_aggregation depends on: [all classifier slot node IDs]

6. Merge FIXED_DEPS + SLOT_DEPS into full adjacency list
7. Topological sort → execution order
8. Return (sorted_nodes, adjacency)
```

**Builder MUST NOT:**
- Contain business logic
- Hardcode node lists (reads from config)
- Assume number of oracle/classifier nodes
- Know the internals of any node

## Dependencies Enforcement

The runner validates before executing each node:
- All `depends_on` nodes have completed
- All `input_keys` are present in state
- For conditional nodes, guard is evaluated first

## Updated DAG Structure

```
                    PromptBuild
                        |
                     Generate
                        |
                      Parse
                        |
                      Route
                        |
         +--------------+---------------+
         |                              |
   [Oracle Slot]                    Normalize
   oracle.inline                        |
   (+ any others)                  Reconstruct
         |                              |
  OracleAggregation         +----------+----------+
         |                  |                      |
         |            [Classifier Slot]          AST
         |          classifier.reasoning_v3        |
         |            (+ any others)               |
         |                  |                      |
         |         ClassifierAggregation           |
         |                  |                      |
         |                  +----------+-----------+
         |                             |
         |                          Execute
         |                             |
         |                        SpecOracle (conditional)
         |                             |
         +-----------------------------+
                        |
                     Metrics
                        |
                     Assemble
                        |
                       Log
```

**Critical ordering guarantee:** Execute depends on ClassifierAggregation. ClassifierAggregation depends on all classifier slot nodes. All classifiers run BEFORE execution. This is structurally enforced by the DAG — not by convention.

**Execution order** (single oracle, single classifier):

```
 1. prompt_build
 2. generate
 3. parse
 4. route
 5. oracle.inline          (parallel-safe with normalize)
 6. normalize
 7. reconstruct
 8. classifier.reasoning_v3 (parallel-safe with ast_verify)
 9. ast_verify
10. oracle_aggregation
11. classifier_aggregation
12. execute                 (after both aggregations + ast)
13. spec_oracle             (conditional)
14. metrics
15. assemble
16. log
```

---

# SECTION 4 — STATE MODEL DESIGN

## Full State Schema

```python
state: dict[str, Any] = {
    # --- Seeded at entry ---
    "case":       dict,
    "condition":  str,
    "model":      str,
    "config":     ExperimentConfig,

    # --- PromptBuildNode ---
    "prompt":      str,
    "prompt_meta": dict,

    # --- GenerateNode ---
    "raw_response":  str,
    "gen_event_id":  int | str,

    # --- ParseNode ---
    "strict_parse":   ParsedGenerationV2,
    "recovery_parse": ParsedGenerationV2,
    "format_parse":   ParsedGenerationV2,

    # --- RouteNode ---
    "parsed_generation": ParsedGenerationV2,
    "routing":           RoutingDecision,
    "parse_mode":        str,
    "retry_eligible":    bool,

    # --- Oracle Slot Nodes → namespaced collection ---
    "oracle_results": {
        "oracle.inline": {
            "reasoning_truth": str,
            "oracle_correct": bool | None,
            "justification": str,
            "status": str,
            "latency_ms": int,
            "prompt_instance_hash": str,
            ...
        },
        # additional oracles would appear here
    },

    # --- OracleAggregationNode ---
    "oracle_summary": {
        "primary": dict,              # result from first oracle in config
        "all": dict[str, dict],       # all oracle results
        "oracle_correct": bool | None, # from primary
        "reasoning_truth": str,        # from primary
    },

    # --- NormalizeNode ---
    "normalized_reasoning": NormalizedReasoningArtifactV2,

    # --- ReconstructNode ---
    "recon":               ReconstructionResult,
    "reconstructed_code":  str,
    "artifact_id":         str,

    # --- Classifier Slot Nodes → namespaced collection ---
    "classifier_results": {
        "classifier.reasoning_v3": {
            "result": ClassifierResultV2,
            "classify_event_id": int | str,
        },
        # additional classifiers would appear here
    },

    # --- ClassifierAggregationNode ---
    "classifier_summary": {
        "primary": ClassifierResultV2,     # result from first classifier in config
        "all": dict[str, dict],            # all classifier results
        "canonical_dims": dict,            # from primary via _extract_canonical_dims()
        "classify_event_id": int | str,    # from primary
    },

    # --- ASTNode ---
    "ast_result": dict,

    # --- ExecuteNode ---
    "execution_result": dict,
    "passed":           bool,

    # --- SpecOracleNode ---
    "spec_oracle_result": dict | None,

    # --- MetricsNode ---
    "signals":       V2Signals,
    "disagreement":  dict,
    "evaluation":    dict,

    # --- AssembleNode ---
    "final_result":  dict,

    # --- LogNode ---
    "log_status":    str,
}
```

## Append-Only Enforcement

Same as v1:
1. Runner creates frozen read-only view for each node (only declared input_keys)
2. Node returns new keys only
3. Runner validates no key conflicts
4. Runner merges into state

**Special handling for slot nodes:**
- Oracle slot nodes return `{"__slot_oracle__": {node_id: result_dict}}`
- Classifier slot nodes return `{"__slot_classifier__": {node_id: result_dict}}`
- The runner intercepts `__slot_*` keys and merges into `oracle_results` / `classifier_results` dicts
- This preserves append-only semantics: each slot node writes to its own namespace within the collection

## Mapping from AttemptState to Dict

| AttemptState Field | State Dict Key | Notes |
|--------------------|---------------|-------|
| oracle_result | oracle_summary.primary | v2 reads oracle_summary, not raw oracle_results |
| classifier_result | classifier_summary.primary | v2 reads classifier_summary, not raw classifier_results |
| All other fields | Same mapping as v1 | Unchanged |

---

# SECTION 5 — EFFECT WRAPPING STRATEGY

## Effect Wrapper (effect_wrapper.py)

Unchanged from v1. All side-effect nodes delegate through a uniform wrapper:

1. **Timeout enforcement** — explicit timeout from config
2. **Error capture** — exceptions wrapped in structured error dict (never silent — INV-03)
3. **Call logging** — each call recorded in effect log (JSON lines)
4. **No global state** — wrapper instantiated per-run

### How llm.py Is Wrapped

GenerateNode, all oracle slot nodes, and all classifier slot nodes call `llm.py:call_model()`.

- Each node receives `call_model` via config/context (not global import)
- Wrapper intercepts: records prompt hash, model, timer
- Delegates to `llm.py:call_model(prompt, model)`
- Records response hash, duration, status
- Mock-injectable for testing

### How Execution Is Wrapped

ExecuteNode calls `exec_canonical.py:exec_canonical()`.

- Wrapper creates temp directory, delegates to exec_canonical, captures result, cleans up
- Records duration, status, errors

### How Logging Is Handled

Graph runner uses its own logging (effect log + LogNode), NOT the V2 RunLogger. Schema-compatible for differential testing.

---

# SECTION 6 — VALIDATION PLAN

## Differential Testing Strategy

### Phase 4a: Deterministic Stages (Pure Nodes Only)

For each test case, run both V2 and graph pipeline. Compare ALL pure node outputs:
- parse results (strict, recovery, format)
- routing decision
- reconstruction result
- artifact_id
- AST result
- spec_oracle_result (DDC cases)

These MUST be byte-identical.

### Phase 4b: Single Oracle/Classifier Equivalence

With config `oracles: [oracle.inline], classifiers: [classifier.reasoning_v3]`:
- `oracle_summary.primary` must match V2's `oracle_result`
- `classifier_summary.primary` must match V2's `classifier_result`
- `evaluation.outcome_class` must match V2's evaluation
- All fields in `final_result` must match V2's case.end event

Seed LLM calls for determinism where API supports it.

### Phase 4c: Multi-Oracle/Classifier Validation

With config `oracles: [oracle.inline, oracle.inline], classifiers: [classifier.reasoning_v3]`:
- Both oracle results should be present in `oracle_results`
- `oracle_summary.primary` should match first oracle
- MetricsNode should produce same evaluation as single-oracle (since primary is same)

This tests the slot infrastructure without changing behavior.

### Phase 4d: Aggregation Correctness

Synthetic test:
- Inject two oracle results with different labels (CORRECT vs WRONG)
- Verify OracleAggregationNode produces correct primary + all dict
- Verify MetricsNode reads from primary only
- Verify AssembleNode includes all results in final_result

### Test Cases

| Category | Cases | Purpose |
|----------|-------|---------|
| DDC always-pass | logging_pipeline_chain, ml_feature_chain | Full success path |
| DDC always-fail | billing_aggregation_chain | Full failure path |
| DDC trap | event_etl_chain_trap_3 | Trap anchoring |
| V2 simple | lazy_init_a | Single-file case |
| V2 complex | versioned_policy_fallback_regression_b | Multi-step |
| Parse failure | synthetic malformed JSON | Parse failure path |
| Recon failure | synthetic empty file | Recon gate |
| Multi-oracle | any case with 2 oracles | Slot infrastructure |

### Mismatch Detection

The diff runner logs:
- Field-level mismatches with expected vs actual values
- Missing fields in either output
- Type mismatches
- Per-oracle/per-classifier result comparison when multiple are active

---

# SECTION 7 — MIGRATION PHASES

## Phase 1: Pure Nodes + Registry

**Scope:** Implement all 7 fixed pure nodes (PromptBuild, Parse, Route, Normalize, Reconstruct, AST, SpecOracle). Implement registry.py with fixed node entries only.

**Deliverables:**
- All pure node files
- registry.py with fixed entries
- node_interface.py
- Updated state.py with append-only enforcement
- Unit tests for each pure node

**Exit criteria:** All pure nodes produce identical outputs to V2 stages for identical inputs.

## Phase 2: Effect Nodes + Effect Wrapper

**Scope:** Implement GenerateNode, ExecuteNode, LogNode + effect_wrapper.py. Mock LLM backend for testing.

**Deliverables:**
- All fixed effect node files
- effect_wrapper.py
- Mock LLM interface

**Exit criteria:** Effect nodes callable with mocks, producing structurally valid outputs.

## Phase 3: Oracle + Classifier Slots

**Scope:** Implement InlineOracleNode, ReasoningClassifierNode, OracleAggregationNode, ClassifierAggregationNode. Add slot entries to registry. Implement config-driven slot resolution in builder.

**Deliverables:**
- Oracle slot node + aggregation node
- Classifier slot node + aggregation node
- Updated registry with slot entries
- Updated dag.py with slot resolution logic
- Updated graph_factory.py with `build_pipeline_dag(config)`

**Exit criteria:** Single-oracle + single-classifier config produces identical pipeline to v1 design.

## Phase 4: Full DAG + Differential Validation

**Scope:** Wire all nodes into DAG. Extend GraphRunner for topological execution. Run differential testing.

**Deliverables:**
- Extended graph_runner.py with DAG support
- Extended transitions.py with all guards
- validation/diff_runner.py
- core/tests/test_graph_runner_diff.py
- Comparison report

**Exit criteria:** Phase 4a (pure identical), Phase 4b (single-oracle/classifier equivalent), Phase 4c (multi-slot infrastructure works), Phase 4d (aggregation correct).

## Phase 5: Retry Integration (Future — NOT in this plan)

Out of scope. Retry is a graph-level control policy requiring: back-edges, state snapshot/restore, critique prompt injection, trajectory tracking.

## Phase 6: Additional Oracles/Classifiers (Future)

Enabled by the slot architecture. Adding a new oracle or classifier requires:
1. Create node file in `nodes/oracles/` or `nodes/classifiers/`
2. Add one line to REGISTRY
3. Add string ID to YAML config

No core files change.

---

# SECTION 8 — METRICS REDESIGN

## Current System Assumptions

`metrics_v2.py:derive_v2_signals()` assumes:
- Single classifier result → reads `classifier_dims` dict directly
- Called with `code_correct` (bool from single execution)
- Called with `commitments_source` (from single normalized artifact)

`oracle_inline.py:compute_disagreement()` assumes:
- Single classifier result → reads `classifier_result` directly
- Single oracle result → reads `oracle_result` directly

`_compute_evaluation()` (execution_v2.py:578) assumes:
- Single oracle: reads `oracle_result.reasoning_truth`, `oracle_result.oracle_correct`
- Single classifier: reads `classification` as single ClassifierResultV2, extracts canonical dims
- Single execution result

## Redesigned MetricsNode

The MetricsNode reads from **aggregated outputs** (`oracle_summary`, `classifier_summary`), not from raw slot results.

**Aggregation contract:**
- `oracle_summary.primary` → dict with `reasoning_truth`, `oracle_correct` (same schema as old oracle_result)
- `classifier_summary.primary` → ClassifierResultV2 (same type as old classifier_result)
- `classifier_summary.canonical_dims` → dict from `_extract_canonical_dims()` (same as old classifier dims)

**MetricsNode logic:**

```
1. Read oracle_summary.primary → oracle_result
2. Read classifier_summary.primary → classifier_result
3. Read classifier_summary.canonical_dims → classifier_dims

4. Call derive_v2_signals(classifier_dims, code_correct, commitments_source)
   → V2Signals (unchanged function, unchanged inputs)

5. Call compute_disagreement(classifier_result, oracle_result, config)
   → disagreement dict (unchanged function, unchanged inputs)

6. Compute evaluation dict:
   - execution_pass from execution_result
   - reconstruction_success from recon.status
   - routing_valid from routing
   - oracle_correct from oracle_summary.primary.oracle_correct
   - classifier_dims from classifier_summary.canonical_dims
   - outcome_class, LEG, LEG_subtype, quadrants
   (reimplemented from _compute_evaluation(), same logic)

7. Return {signals, disagreement, evaluation}
```

**Key insight:** By routing through aggregation nodes that expose a `.primary` field, the MetricsNode code is IDENTICAL to what it would be with a single oracle/classifier. The aggregation layer absorbs the multi-result complexity.

**Multi-result awareness:** MetricsNode reads ONLY from `primary`. Future MetricsNode extensions can read from `oracle_summary.all` and `classifier_summary.all` to compute cross-oracle/cross-classifier metrics — but this is NOT required for v2 equivalence.

## Places Where Metrics Depend on Single Outputs

| Location | Dependency | Resolution |
|----------|-----------|------------|
| `derive_v2_signals(classifier_dims, ...)` | Single classifier_dims dict | Reads from `classifier_summary.canonical_dims` (primary) |
| `compute_disagreement(classifier_result, oracle_result, ...)` | Single of each | Reads from `.primary` of each summary |
| `_compute_evaluation(... classification, oracle_result, ...)` | Single of each | Reads from `.primary` of each summary |
| `assemble_v2_result(... classifier, ...)` | Single ClassifierResultV2 | Reads from `classifier_summary.primary` |

All four are resolved by the aggregation node's `.primary` convention.

---

# SECTION 9 — BACKWARD COMPATIBILITY PLAN

## Default Config

When `graph_runner.oracles` and `graph_runner.classifiers` are not specified in YAML, defaults apply:

```yaml
graph_runner:
  oracles:
    - oracle.inline
  classifiers:
    - classifier.reasoning_v3
```

## Behavioral Equivalence

With default config:
- `oracle_results` contains exactly one entry: `{"oracle.inline": {...}}`
- `oracle_summary.primary` is identical to V2's `oracle_result`
- `classifier_results` contains exactly one entry: `{"classifier.reasoning_v3": {...}}`
- `classifier_summary.primary` is identical to V2's `classifier_result`
- MetricsNode produces identical `evaluation` dict
- AssembleNode produces identical `final_result` dict
- LogNode writes identical event schema

## Validation

Phase 4b differential testing specifically validates this: single-oracle + single-classifier graph output must match V2 output field-by-field (excluding LLM non-determinism).

---

# SECTION 10 — RISKS

## 1. State Explosion (Multi-Results)

**Risk:** With N oracles and M classifiers, state grows by N+M result dicts. For large N/M, state dict becomes unwieldy.

**Mitigation:** Practical configs will have 1-3 oracles and 1-2 classifiers. State is a dict — growth is linear and bounded. Aggregation nodes reduce downstream complexity to O(1) regardless of N/M.

## 2. Aggregation Correctness

**Risk:** OracleAggregation and ClassifierAggregation must correctly select "primary" and preserve all results. If primary selection logic differs from V2's single-oracle behavior, evaluation diverges.

**Mitigation:** Primary = first in config list. With single-oracle config, primary is the only oracle — identical to V2. Differential testing (Phase 4b) validates this.

## 3. Metric Drift

**Risk:** MetricsNode reimplements `_compute_evaluation()` from execution_v2.py (~80 lines). Subtle differences in outcome_class logic would produce different LEG/category labels.

**Mitigation:** The reimplementation is pure and deterministic. Phase 4b validates field-by-field equivalence for all test cases. Any mismatch is a blocking failure.

## 4. Config Misconfiguration

**Risk:** User specifies an oracle/classifier ID not in the registry. Builder fails at runtime.

**Mitigation:** Builder validates all IDs against REGISTRY at construction time. Missing ID raises immediately with: `"Unknown node ID '{id}' in config.graph_runner.oracles. Available: {list(REGISTRY.keys())}"`. Fail-fast, no silent fallback (INV-03).

## 5. Ordering Bugs (Classifier vs Execute)

**Risk:** A DAG construction bug could allow Execute to run before classifiers complete, violating classifier blindness.

**Mitigation:** Structural guarantee: Execute depends on ClassifierAggregation, which depends on ALL classifier slot nodes. The topological sort enforces this. Additionally: a post-construction validation step checks that every classifier node ID appears in Execute's transitive dependency set. If not, construction fails.

## 6. Hidden Dependencies in Reimplemented Functions

**Risk:** RouteNode, MetricsNode, AssembleNode reimplement logic from execution_v2.py. Undocumented edge cases may diverge.

**Mitigation:** Differential testing (Phase 4a, 4b) catches all divergences. Each reimplemented function is tested against V2 output for identical inputs.

## 7. Logger Requirement for Classifier

**Risk:** `classify_case()` may require a non-None logger and crash without one.

**Mitigation:** Must verify during Phase 3 implementation. If classify_case() does not guard logger calls, provide a thin no-op logger adapter that implements the required interface but discards writes. The effect wrapper handles actual logging.

## 8. Registry Key Collisions

**Risk:** Two nodes registered with the same ID would silently overwrite.

**Mitigation:** Registry validates on registration: duplicate IDs raise immediately. REGISTRY is populated at import time — collisions fail at startup, not at runtime.

---

# SECTION 11 — INVARIANT CHECK

## INV-01 — Single Canonical Execution Entry

**SATISFIED.** Graph runner is a parallel system in `side_projects/`. Does not share entrypoints with V2. After validation, V2 path can be deprecated.

## INV-02 — Single Canonical Implementation Per Responsibility

**TEMPORARY VIOLATION (PLANNED).** During Phases 1-4, routing, evaluation computation, and assembly logic exist in both execution_v2.py and graph runner nodes. Validated via differential testing. V2 becomes deprecated copy after Phase 4.

## INV-03 — No Silent Failure

**SATISFIED.** All nodes fail-fast on invalid inputs. Effect wrapper captures all exceptions. Registry raises on unknown IDs. Builder raises on missing nodes. No bare except, no except pass.

## INV-04 — Explicit Contract Boundaries

**SATISFIED.** Each node declares explicit input_keys and output_keys. Slot nodes declare output namespace. Runner validates at execution time.

## INV-07 — Separation of Generation and Evaluation

**SATISFIED.** All classifier slot nodes complete BEFORE ExecuteNode. Enforced by DAG structure: Execute depends on ClassifierAggregation, which depends on all classifier slot nodes.

## INV-11 — Single Source of Truth for State

**SATISFIED.** State dict is the single source. Each key written exactly once (append-only). Slot results namespaced under `oracle_results`/`classifier_results`. Aggregation produces `oracle_summary`/`classifier_summary`. No shadow copies.

## INV-14 — No Duplicate Decision Logic

**SATISFIED.** Primary oracle/classifier selection happens exactly once in the aggregation node. MetricsNode reads from summary, not from raw results. No duplicate classification threshold logic.

## INV-16 — Canonical Pipeline Structure

**SATISFIED.** DAG encodes the full pipeline. Slot nodes are injected by the builder based on config. All stages exist explicitly. Ordering preserved by topological sort.

## INV-17 — No Pipeline Bypass

**SATISFIED.** All execution flows through the DAG. Nodes communicate only via state dict. No cross-node direct calls.

## INV-19 — Configuration Single Source of Truth

**SATISFIED.** Config from YAML. Oracle/classifier selection from config. Node instantiation from config. No hardcoded node lists in the builder.

## No Node Depends on Specific Oracle/Classifier

**SATISFIED.** MetricsNode reads from `oracle_summary` and `classifier_summary` — it does not know which specific oracle or classifier produced the data. AssembleNode reads from the same summaries. No downstream node references a specific oracle/classifier by ID.

## No Global State (AP-02)

**SATISFIED.** No `global` keyword in any graph runner module. No module-level mutable state. Config singleton (pre-existing, read-only) is tolerated.

## No Hidden Side Effects (AP-08, EC-06)

**SATISFIED.** All side effects in effect nodes only. Pure nodes have zero side effects. Effect wrapper makes all effects explicit and logged.

---

# SUMMARY

This plan defines an extensible 14+ node DAG with slot-based oracle and classifier architecture. Oracle and classifier nodes are instantiated from a registry driven by YAML config. Aggregation nodes decouple downstream metrics from specific oracle/classifier implementations. The MetricsNode reads from aggregated summaries, producing identical outputs for single-oracle/single-classifier configs. Adding a new oracle or classifier requires: one new file, one registry entry, one config line — zero core changes.

Changes from v1:
- Single OracleNode → Oracle Slot (N nodes) + OracleAggregationNode
- Single ClassifyNode → Classifier Slot (N nodes) + ClassifierAggregationNode
- state["oracle_result"] → state["oracle_results"] + state["oracle_summary"]
- state["classifier_result"] → state["classifier_results"] + state["classifier_summary"]
- Hardcoded DAG → config-driven builder with registry
- MetricsNode reads from summaries, not raw results
- Validation plan extended for multi-oracle/classifier scenarios

No code. No speculation. No assumptions about specific oracle/classifier count.
