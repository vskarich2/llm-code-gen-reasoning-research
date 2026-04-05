# AttemptState Refactor — Plan v1

## Problem

The pipeline has no shared state container. Each stage produces output as local variables, passes them through function arguments, and the final event assembly gathers everything ad-hoc. This causes:

1. **retry_v2 reimplements the pipeline** (lines 562-672) because it can't get intermediate state from run_v2. run_v2 returns only `(cid, condition, ev_dict)` — all intermediate state (routing, recon, classifier, oracle, AST) is lost.

2. **Data loss in retry events** — retry_v2's event assembly (L758-782) drops 15+ fields that execution_v2 writes, because it assembled them differently. `ev["reconstruction"]`, `ev["v2_parse_tiers"]` are never set.

3. **Per-attempt metadata discarded** — trajectory entries store a collapsed `parse_valid` boolean but not `selected_source`, `recovery_used`, `recon_status`, or any reconstruction diagnostics.

4. **Fragile assembly** — `_assemble_result()` takes 17 positional arguments. Adding a new pipeline stage means threading a new variable through every function signature in both files.

5. **Duplicate code** — retry_v2 lines 562-672 are a near-copy of run_v2 lines 129-165, with subtle differences that cause bugs.

## Solution

Introduce `AttemptState` — a typed dataclass that accumulates all pipeline state for one attempt. Refactor run_v2's stages into functions that read/write AttemptState. Make retry_v2 call the same stage functions per attempt.

## Design

### The AttemptState dataclass

```python
# core/pipeline/orchestration/attempt_state.py (NEW FILE)

@dataclass
class AttemptState:
    """All pipeline state for one attempt. Populated stage by stage."""
    
    # Identity
    case_id: str = ""
    condition: str = ""
    model: str = ""
    attempt_idx: int = 0
    
    # Stage 1: Generation
    prompt: str = ""
    prompt_meta: dict = field(default_factory=dict)
    raw_response: str = ""
    gen_event_id: str | int = 0
    
    # Stage 2: Parsing
    strict_parse: ParsedGenerationV2 | None = None
    recovery_parse: ParsedGenerationV2 | None = None
    format_parse: ParsedGenerationV2 | None = None
    routing: RoutingDecision | None = None
    parsed_gen: ParsedGenerationV2 | None = None  # the selected one
    
    # Stage 3: Oracle (runs on raw fields, before normalize)
    oracle_result: dict = field(default_factory=dict)
    
    # Stage 4: Normalize
    artifact: NormalizedReasoningArtifactV2 | None = None
    
    # Stage 5: Reconstruction
    recon: ReconstructionResult | None = None
    code: str = ""  # full materialized code for classifier
    artifact_id: str = ""
    
    # Stage 6: Classification (before execution — blindness)
    classifier_result: ClassifierResultV2 | None = None
    classify_event_id: str | int = 0
    
    # Stage 7: AST verification (before execution — blindness)
    ast_result: dict = field(default_factory=dict)
    
    # Stage 8: Execution
    exec_result: dict = field(default_factory=dict)
    passed: bool = False
    
    # Stage 9: Derived metrics
    disagreement: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    evaluation: dict = field(default_factory=dict)
    
    # Timing
    start_time: float = 0.0
    elapsed: float = 0.0
```

### Stage functions

Each stage becomes a function that takes AttemptState + config/case/logger and modifies state in place. These live in `execution_v2.py` (or a new `stages.py`) and are called by both run_v2 and retry_v2.

```python
def stage_generate(state: AttemptState, case, config, logger) -> None:
    """Stage 1: Render prompt, call generation model."""
    state.prompt, state.prompt_meta = _render_generation_prompt(case, state.condition, config)
    state.raw_response, state.gen_event_id = _call_generation_model(
        state.prompt, state.model, state.case_id, state.condition,
        state.prompt_meta, logger, ...)

def stage_parse(state: AttemptState, case) -> None:
    """Stage 2: Parse raw response, route to strict/recovery."""
    state.strict_parse, state.recovery_parse, state.format_parse = (
        _parse_outputs(state.raw_response, state.condition))
    state.routing = _select_artifact(state.strict_parse, state.recovery_parse, case)
    state.parsed_gen = (state.recovery_parse 
                        if state.routing.selected_source == "recovery" 
                        else state.strict_parse)

def stage_oracle(state: AttemptState, case, config, logger) -> None:
    """Stage 3: Oracle evaluation on raw reasoning fields."""
    fj = state.parsed_gen.full_json or {}
    state.oracle_result = run_oracle_evaluation(
        fj.get("root_cause"), fj.get("fix_strategy"), case, config,
        logger=logger, ...)

def stage_normalize(state: AttemptState, case) -> None:
    """Stage 4: Normalize generation artifact."""
    state.artifact = normalize_generation_v2(state.parsed_gen, case, state.condition)

def stage_reconstruct(state: AttemptState, case, config) -> None:
    """Stage 5: Reconstruct code files from parsed output."""
    state.recon, state.code = _reconstruct(state.parsed_gen, case, config)
    state.artifact_id = _compute_artifact_id(state.recon)

def stage_classify(state: AttemptState, case, config, logger) -> None:
    """Stage 6: Run classifier (before execution)."""
    state.classifier_result, state.classify_event_id = _classify_reasoning(
        state.artifact, case, state.code, config, logger,
        state.case_id, state.condition, state.parsed_gen, state.gen_event_id)

def stage_ast(state: AttemptState, case) -> None:
    """Stage 7: AST structural verification (before execution)."""
    state.ast_result = _run_ast_verification(state.recon, case, state.artifact_id)

def stage_execute(state: AttemptState, case, config, logger) -> None:
    """Stage 8: Execute code against test suite."""
    state.exec_result = _execute(case, state.parsed_gen, state.recon, config, logger)
    state.passed = state.exec_result.get("pass", False)

def stage_derive_metrics(state: AttemptState, config) -> None:
    """Stage 9: Compute disagreement, signals, evaluation."""
    state.disagreement = compute_disagreement(
        state.classifier_result, state.oracle_result, config)
    state.signals = _derive_metrics(
        state.classifier_result, state.artifact, state.exec_result, state.parsed_gen)
    state.evaluation = _compute_evaluation(
        state.routing, state.recon, state.exec_result,
        state.classifier_result, state.oracle_result, state.artifact_id)
```

### run_v2 becomes thin

```python
def run_v2(case, model, condition, logger, case_start_eid=0):
    state = AttemptState(case_id=case["id"], condition=condition, model=model)
    
    stage_generate(state, case, config, logger)
    stage_parse(state, case)
    stage_oracle(state, case, config, logger)
    stage_normalize(state, case)
    stage_reconstruct(state, case, config)
    stage_classify(state, case, config, logger)
    stage_ast(state, case)
    stage_execute(state, case, config, logger)
    stage_derive_metrics(state, config)
    
    ev = assemble_event_from_state(state, case, ...)
    _log_result(logger, ...)
    return cid, condition, ev
```

### retry_v2 calls the same stages

```python
def run_retry_v2(case, model, condition, logger, ...):
    trajectory: list[AttemptState] = []
    
    for k in range(max_iterations):
        state = AttemptState(
            case_id=cid, condition=condition, model=model, attempt_idx=k)
        
        # Stage 1: Generate (with retry prompt for k>0)
        if k == 0:
            stage_generate(state, case, config, logger)
        else:
            state.prompt = _build_retry_prompt(k, trajectory[k-1], ...)
            state.raw_response, state.gen_event_id = _call_generation_model(
                state.prompt, model, ...)
        
        # Stages 2-8: identical to single-shot
        stage_parse(state, case)
        stage_oracle(state, case, config, logger)
        stage_normalize(state, case)
        stage_reconstruct(state, case, config)
        stage_classify(state, case, config, logger)
        stage_ast(state, case)
        stage_execute(state, case, config, logger)
        stage_derive_metrics(state, config)
        
        trajectory.append(state)
        
        if state.passed:
            break
    
    # Assemble final event from trajectory of AttemptState objects
    ev = assemble_retry_event_from_trajectory(trajectory, case, ...)
    return cid, condition, ev
```

### Event assembly reads from state

`assemble_event_from_state(state)` replaces the 17-argument `_assemble_result()`. It reads all fields from the typed state object. No positional args to get wrong.

For retry, `assemble_retry_event_from_trajectory(trajectory)` has full access to every attempt's complete state — routing, recon, recovery_types, parse diagnostics. Nothing is lost because nothing was discarded.

### Trajectory entries become AttemptState objects

Instead of building a lossy dict at L654-672, the trajectory IS a list of AttemptState. The event assembly serializes what it needs from each state. The dashboard scanner can extract per-attempt parse/routing/recon fields because they're all on the state object.

## Files changed

| File | Change | Risk |
|------|--------|------|
| `core/pipeline/orchestration/attempt_state.py` | **NEW** — AttemptState dataclass | None (new file) |
| `core/pipeline/orchestration/execution_v2.py` | Extract stage functions from run_v2, rewrite run_v2 to use them | Medium — core pipeline, but logic unchanged |
| `core/pipeline/orchestration/retry_v2.py` | Delete duplicated pipeline code (L562-672), call stage functions instead | Medium — removes ~110 lines of duplication |
| `core/pipeline/checks.py` | Move checks to operate on AttemptState fields | Low |
| `dashboard/leg_scanner.py` | Update trajectory extraction for new format | Low — additive |

## Files NOT changed

- `parser_v2.py` — stage functions call it the same way
- `reconstructor.py` — same
- `evaluator_v2.py` — same
- `exec_canonical.py` — same
- `logging_core.py` — same (event assembly just produces the same dict)
- No config changes
- No prompt changes

## What this fixes

1. **Retry data loss** — trajectory is `list[AttemptState]`, every field survives
2. **Reconstruction section missing** — `assemble_retry_event_from_trajectory` reads `state.routing`, `state.recon` etc. and builds the same `ev["reconstruction"]` section as single-shot
3. **Per-attempt metadata** — each AttemptState has `routing.selected_source`, `routing.recovery_used`, `recon.status`, `recon.recovery_types` etc.
4. **Fragile assembly** — `assemble_event_from_state(state)` reads typed fields, no positional args
5. **Duplicate code** — retry_v2 calls the same stage functions as run_v2
6. **Empty classifier code** — `check_reconstruction_produced_code` runs inside `stage_reconstruct` on `state.code`
7. **reconstruction_success approximation** — reads `state.recon.status` directly, not `code_length > 0`

## What this does NOT do

- Does NOT change pipeline logic (same stages in same order)
- Does NOT change event schema (same fields in same places in the dict)
- Does NOT change prompts, parsers, reconstructor, classifier, executor
- Does NOT require config changes
- Does NOT affect dashboard (event dict format is unchanged)

## Migration strategy

1. Create `attempt_state.py` with the dataclass
2. Extract stage functions from execution_v2.py (pure refactor — logic identical)
3. Rewrite run_v2 to use stage functions + AttemptState (behavioral equivalence test: produce same event dict)
4. Rewrite retry_v2 to use stage functions + AttemptState (gains: reconstruction section, per-attempt metadata)
5. Update event assembly to read from state
6. Run existing tests to verify behavioral equivalence
7. Update dashboard scanner to extract new per-attempt fields (additive, backward compat)

## Risks

- **Behavioral drift during refactor** — mitigated by running existing tests after each step
- **State object becomes a god object** — mitigated by keeping it as pure data (no methods, no logic, just fields). Stage functions own the logic.
- **Import cycles** — AttemptState needs to reference ParsedGenerationV2, RoutingDecision, ReconstructionResult, ClassifierResultV2. These are in different modules. Use `from __future__ import annotations` and import at use site to avoid cycles.

## Invariants

After refactor:
- `run_v2(case, model, condition, logger)` produces the EXACT same event dict as before
- Retry events gain `ev["reconstruction"]` and `ev["v2_parse_tiers"]` sections (currently missing)
- Per-attempt trajectory entries contain full routing/recon metadata (currently missing)
- All existing dashboard functionality works unchanged (event dict format preserved)
- All existing tests pass

## Size estimate

- `attempt_state.py`: ~60 lines (dataclass only)
- Stage function extraction from execution_v2: ~200 lines moved, ~30 lines of new wrapper code
- run_v2 rewrite: ~20 lines (becomes thin orchestrator)
- retry_v2 rewrite: ~110 lines deleted (duplicated pipeline), ~40 lines added (call stage functions)
- Event assembly: ~50 lines refactored (read from state instead of positional args)
- Total: net reduction of ~50-80 lines, plus the new 60-line dataclass
