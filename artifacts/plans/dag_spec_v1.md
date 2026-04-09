Date: 2026-04-09
Time: 22:00

# DAG SPECIFICATION v1 — DESIGN LOCK

This document defines the FINAL DAG structure for Phase 4 implementation.
No code may be written until this spec is approved.

---

# 1. FULL NODE TABLE

14 nodes. 8 pure. 6 effect.

| # | Node ID | Node Class | Type | INPUT_KEYS | OUTPUT_KEYS |
|---|---------|-----------|------|------------|-------------|
| 1 | prompt_build | PromptBuildNode | pure | case, condition, config, retry_context | prompt, prompt_meta |
| 2 | generate | GenerateNode | effect | prompt, model, config | raw_response, gen_event_id |
| 3 | parse | ParseNode | pure | raw_response, condition | strict_parse, recovery_parse, format_parse |
| 4 | route | RouteNode | pure | strict_parse, recovery_parse, format_parse, case | parsed_generation, routing, parse_mode, retry_eligible |
| 5 | oracle.inline | InlineOracleNode | effect | normalized_reasoning, case, config, condition | oracle_results |
| 6 | oracle_aggregation | OracleAggregationNode | pure | oracle_results | oracle_summary |
| 7 | normalize | NormalizeNode | pure | parsed_generation, case, condition | normalized_reasoning |
| 8 | reconstruct | ReconstructNode | pure | parsed_generation, case | recon, reconstructed_code, artifact_id |
| 9 | classifier.reasoning | ReasoningClassifierNode | effect | normalized_reasoning, reconstructed_code, case, config, condition | classifier_results |
| 10 | classifier_aggregation | ClassifierAggregationNode | pure | classifier_results | classifier_summary, classify_event_id |
| 11 | ast_verify | ASTNode | pure | recon, case, artifact_id | ast_result |
| 12 | execute | ExecuteNode | effect | recon, parsed_generation, case, config | execution_result, passed |
| 13 | spec_oracle | SpecOracleNode | pure | execution_result, case | spec_oracle_result |
| 14 | metrics | MetricsNode | pure | oracle_summary, classifier_summary, execution_result, normalized_reasoning, parsed_generation, artifact_id, routing, recon, config | signals, disagreement, evaluation |
| 15 | assemble | AssembleNode | pure | ALL prior outputs | final_result |
| 16 | log | LogNode | effect | final_result | log_status |

Notes:
- Nodes 5-6 are the oracle SLOT (config-driven, currently one oracle)
- Nodes 9-10 are the classifier SLOT (config-driven, currently one classifier)
- Node 13 (spec_oracle) is CONDITIONAL: runs only for DDC cases
- Node 1 (prompt_build) is NOT YET IMPLEMENTED — required for Phase 4
- Node 14 (metrics) is NOT YET IMPLEMENTED — required for Phase 4
- Node 15 (assemble) is NOT YET IMPLEMENTED — required for Phase 4

---

# 2. EDGE LIST

Every edge is explicit. No implicit dependencies.

```
prompt_build          → generate
generate              → parse
parse                 → route
route                 → normalize
route                 → oracle.inline        [parallel group 1]
normalize             → reconstruct
normalize             → oracle.inline        [oracle needs normalized_reasoning]
reconstruct           → classifier.reasoning
reconstruct           → ast_verify           [parallel group 2]
oracle.inline         → oracle_aggregation
classifier.reasoning  → classifier_aggregation
classifier_aggregation→ execute              [CRITICAL: classifier before execute]
ast_verify            → execute
execute               → spec_oracle
oracle_aggregation    → metrics
classifier_aggregation→ metrics
execute               → metrics
spec_oracle           → metrics
metrics               → assemble
assemble              → log
```

Corrected dependency reasoning:
- oracle.inline depends on normalize (needs normalized_reasoning) AND route (needs case already available from seed)
- classifier.reasoning depends on reconstruct (needs reconstructed_code) AND normalize (needs normalized_reasoning)
- execute depends on classifier_aggregation (blindness constraint) AND ast_verify
- metrics depends on oracle_aggregation, classifier_aggregation, execute, spec_oracle (needs all evaluation signals)

---

# 3. FULL DAG DIAGRAM

```
SEED: {case, condition, model, config, retry_context}
                        |
                   PromptBuild
                        |
                    Generate
                        |
                      Parse
                        |
                      Route
                        |
              +---------+---------+
              |                   |
          Normalize          (wait for normalize)
              |                   |
       +------+------+      OracleInline
       |             |           |
  Reconstruct    (feed to     OracleAggregation
       |          oracle)         |
  +----+----+                    |
  |         |                    |
Classify   AST                   |
  |         |                    |
ClassifierAgg                    |
  |         |                    |
  +----+----+                    |
       |                         |
    Execute                      |
       |                         |
   SpecOracle                    |
       |                         |
       +----------+--------------+
                  |
               Metrics
                  |
              Assemble
                  |
                 Log
```

---

# 4. PARALLEL GROUPS

## Group 1: Post-Route Fan-Out

After Route completes, Normalize begins. After Normalize completes:
- OracleInline can begin (needs: normalized_reasoning, case, config, condition)
- Reconstruct can begin (needs: parsed_generation, case)

OracleInline and Reconstruct are parallelizable.

**However:** The current system executes serially (AP-04 forbids unauthorized concurrency). Phase 4 uses serial execution in topological order. Parallel execution is a future optimization.

Serial order within group: Normalize → Reconstruct → OracleInline (or OracleInline → Reconstruct — order does not matter since they have no data dependency on each other).

## Group 2: Post-Reconstruct Fan-Out

After Reconstruct completes:
- ClassifierReasoning can begin (needs: normalized_reasoning, reconstructed_code, case, config, condition)
- ASTNode can begin (needs: recon, case, artifact_id)

ClassifierReasoning and ASTNode are parallelizable.

Serial order within group: ClassifierReasoning → ASTNode (or reverse — no mutual dependency).

---

# 5. CONDITIONAL NODES

## SpecOracleNode

- **Condition:** Case belongs to a DDC family
- **Guard:** `is_ddc_case(state[KEY_CASE])` — checks case ID against DDC_FAMILIES
- **When skipped:** Produces `{spec_oracle_result: None}`
- **Downstream impact:** MetricsNode and AssembleNode must handle `spec_oracle_result = None`

No other nodes are conditional.

---

# 6. TOPOLOGICAL EXECUTION ORDER (Serial)

One valid topological sort respecting all edges:

```
 1. prompt_build
 2. generate
 3. parse
 4. route
 5. normalize
 6. reconstruct
 7. oracle.inline
 8. oracle_aggregation
 9. classifier.reasoning
10. classifier_aggregation
11. ast_verify
12. execute
13. spec_oracle
14. metrics
15. assemble
16. log
```

Critical ordering constraints verified:
- classifier_aggregation (10) before execute (12): YES
- oracle_aggregation (8) before metrics (14): YES
- classifier_aggregation (10) before metrics (14): YES
- execute (12) before spec_oracle (13): YES
- spec_oracle (13) before metrics (14): YES

---

# 7. STATE SCHEMA

## Seed Keys (provided by caller, consumed by nodes)

| Key | Type | Provided By | Consumed By |
|-----|------|-------------|-------------|
| case | dict | Caller | prompt_build, route, normalize, reconstruct, ast_verify, oracle.inline, classifier.reasoning, execute, spec_oracle |
| condition | str | Caller | prompt_build, parse, normalize, oracle.inline, classifier.reasoning |
| model | str | Caller | generate |
| config | ExperimentConfig | Caller | prompt_build, generate, oracle.inline, classifier.reasoning, execute, metrics |
| retry_context | RetryContext or None | Caller | prompt_build |

## Produced Keys (each key produced by exactly one node)

| Key | Type | Produced By | Consumed By |
|-----|------|-------------|-------------|
| prompt | str | prompt_build | generate |
| prompt_meta | dict | prompt_build | assemble |
| raw_response | str | generate | parse |
| gen_event_id | int or str | generate | assemble |
| strict_parse | ParsedGenerationV2 | parse | route |
| recovery_parse | ParsedGenerationV2 | parse | route |
| format_parse | ParsedGenerationV2 | parse | route |
| parsed_generation | ParsedGenerationV2 | route | normalize, reconstruct, execute, metrics |
| routing | RoutingDecision | route | metrics, assemble |
| parse_mode | str | route | assemble |
| retry_eligible | bool | route | assemble |
| normalized_reasoning | NormalizedReasoningArtifactV2 | normalize | oracle.inline, classifier.reasoning, metrics |
| recon | ReconstructionResult | reconstruct | ast_verify, execute, metrics |
| reconstructed_code | str | reconstruct | classifier.reasoning |
| artifact_id | str | reconstruct | ast_verify, metrics |
| oracle_results | dict[str, dict] | oracle.inline | oracle_aggregation |
| oracle_summary | dict | oracle_aggregation | metrics, assemble |
| classifier_results | dict[str, dict] | classifier.reasoning | classifier_aggregation |
| classifier_summary | dict | classifier_aggregation | metrics, assemble |
| classify_event_id | int or str or None | classifier_aggregation | assemble |
| ast_result | ASTResult | ast_verify | assemble |
| execution_result | dict | execute | spec_oracle, metrics, assemble |
| passed | bool | execute | assemble |
| spec_oracle_result | dict or None | spec_oracle | metrics, assemble |
| signals | V2Signals | metrics | assemble |
| disagreement | dict | metrics | assemble |
| evaluation | dict | metrics | assemble |
| final_result | dict | assemble | log |
| log_status | str | log | (terminal) |

## Key Production Rules

- Every key is produced by EXACTLY ONE node
- No key is overwritten after production (append-only)
- Seed keys are never overwritten by any node
- oracle_results and classifier_results are namespaced collections — each slot node merges its entry into the collection

---

# 8. INVARIANTS

## Input Validation (per node)

Every node validates its INPUT_KEYS are present before execution.
Missing inputs raise ValueError immediately (fail-fast).

## Cross-Node Invariants

| Invariant | Description | Enforcement |
|-----------|-------------|-------------|
| INV-BLIND | ClassifierReasoning and ClassifierAggregation MUST complete before Execute | DAG edge: classifier_aggregation → execute |
| INV-ORACLE-BLIND | OracleInline MUST NOT see execution_result | OracleInline INPUT_KEYS does not include execution_result |
| INV-CLASSIFIER-BLIND | ClassifierReasoning MUST NOT see execution_result | ClassifierReasoning INPUT_KEYS does not include execution_result |
| INV-APPEND-ONLY | No state key may be written twice | Runner validates: new output keys do not collide with existing state keys |
| INV-SPEC-CONDITIONAL | SpecOracleNode produces None for non-DDC cases | Guard function in node; downstream nodes handle None |
| INV-SINGLE-PRODUCE | Each output key is produced by exactly one node | Verified by this spec — no two nodes share any output key |
| INV-SEED-IMMUTABLE | Seed keys (case, condition, model, config, retry_context) are never overwritten | No node declares any seed key in OUTPUT_KEYS |

## Post-Node Invariant Checks (from core/graph/invariants.py)

After each node, `validate_pipeline_state()` checks:
- PromptBuildNode: prompt is non-empty
- RouteNode: parsed_generation and routing present when parse_mode != failed
- ReconstructNode: reconstructed_code non-empty, artifact_id non-empty, recon.status consistent
- ClassifierAggregationNode: classifier_summary and classifier_summary.primary present
- ExecuteNode: execution_result present with execution_category and pass fields
- MetricsNode: evaluation, signals, oracle_summary present
- CritiqueNode: (state machine only, not in DAG)

## Forbidden States

| State | Why Forbidden | When Detected |
|-------|--------------|---------------|
| execute runs with classifier_aggregation incomplete | Violates blindness | DAG topology prevents this |
| oracle_results empty at oracle_aggregation | No oracle ran | oracle_aggregation produces empty summary with None fields |
| classifier_results empty at classifier_aggregation | No classifier ran | classifier_aggregation produces empty summary with None fields |
| parse_mode = failed AND execution proceeds | Executing unparseable output | execute receives recon with non-SUCCESS status, returns structural failure |
| spec_oracle_result missing at metrics when case is DDC | Spec oracle skipped for DDC case | spec_oracle guard always runs for DDC — this cannot happen if edges are correct |

---

# 9. NODES NOT YET IMPLEMENTED (Required for Phase 4)

| Node | Status | Blocker |
|------|--------|---------|
| PromptBuildNode | NOT IMPLEMENTED | Requires PromptRegistry wiring + retry_context handling |
| MetricsNode | NOT IMPLEMENTED | Requires reimplementation of _compute_evaluation() from execution_v2.py |
| AssembleNode | NOT IMPLEMENTED | Requires knowledge of full event schema (~100 lines) |

All other 13 nodes are implemented and registered.

---

# 10. DAG INPUT CONTRACT (from state machine controller)

The DAG receives this input dict from `run_state_machine` → `run_attempt`:

```
{
    "case": dict,                    # enriched case from load_cases()
    "condition": str,                # e.g., "baseline_v3"
    "model": str,                    # e.g., "gpt-4o-mini"
    "config": ExperimentConfig,      # frozen config object
    "retry_context": RetryContext | None,  # None on attempt 0
}
```

The DAG returns a fully populated state dict with all 28 produced keys.

---

# 11. DAG OUTPUT CONTRACT (to state machine controller)

The state machine reads these fields from the DAG output to build AttemptState:

| AttemptState Field | State Key |
|--------------------|-----------|
| prompt | prompt |
| prompt_meta | prompt_meta |
| raw_response | raw_response |
| parsed_generation | parsed_generation |
| routing | routing |
| parse_mode | parse_mode |
| normalized_reasoning | normalized_reasoning |
| reconstructed_code | reconstructed_code |
| artifact_id | artifact_id |
| classifier_summary | classifier_summary |
| oracle_summary | oracle_summary |
| ast_result | ast_result |
| execution_result | execution_result |
| passed | passed |
| spec_oracle_result | spec_oracle_result |
| signals | signals |
| disagreement | disagreement |
| evaluation | evaluation |
