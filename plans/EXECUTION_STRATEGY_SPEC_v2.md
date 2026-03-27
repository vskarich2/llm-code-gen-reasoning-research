# ExecutionStrategy Spec: Graph + Policy Runtime (v2)

**Version:** 2.0
**Date:** 2026-03-27
**Supersedes:** EXECUTION_STRATEGY_SPEC_v1.md
**Status:** Design specification. Not yet implemented.

**v1 → v2 corrections:**
1. Versioned artifact references replace implicit string field overwrites
2. ResponseContract layer reintroduced for all stages that process LLM output
3. Policy no longer generates text — outputs InterventionType enum only
4. StageSpec strengthened with ExecutionContract and failure handling rules
5. GraphRunner explicitly defined with full execution loop
6. Compile-time guard coverage validation added (no runtime DeadEndState)
7. SideEffect changed from enum to structured callable with parameters
8. Prompt identities (PromptConfigIdentity + PromptCallIdentity) added to logging
9. GraphRunner defined as the ONLY execution entry point

---

## 1. EXECUTION MODEL

Unchanged from v1 section 1 (core principle, formal definitions, invariants INV-G1 through INV-G6).

---

## 2. ARTIFACT VERSIONING

### 2.1 Problem

In a retry loop, the same artifact (e.g., `raw_response`, `code`, `exec_result`) is produced multiple times. Using flat field names causes implicit overwrites. Stage N's guard might read iteration 2's result when it should read iteration 3's.

### 2.2 ArtifactRef

Every artifact in ExecutionState is addressed by a versioned reference:

```python
@dataclass(frozen=True)
class ArtifactRef:
    name: str           # e.g., "raw_response", "exec_result", "classification"
    iteration: int      # which iteration produced it (0 = first attempt)
    stage_id: StageID   # which stage produced it
```

### 2.3 Artifact Storage in State

```python
@dataclass
class ExecutionState:
    # ... identity fields unchanged ...

    artifacts: list[Artifact]  # append-only, ordered by production time

@dataclass(frozen=True)
class Artifact:
    ref: ArtifactRef
    value: Any          # the actual data
    timestamp: str
    elapsed_seconds: float
```

### 2.4 Artifact Access

Stages and guards access artifacts through explicit queries:

```python
def latest(state: ExecutionState, name: str) -> Artifact | None:
    """Return the most recent artifact with this name."""
    for a in reversed(state.artifacts):
        if a.ref.name == name:
            return a
    return None

def at_iteration(state: ExecutionState, name: str, iteration: int) -> Artifact | None:
    """Return the artifact with this name from a specific iteration."""
    for a in state.artifacts:
        if a.ref.name == name and a.ref.iteration == iteration:
            return a
    return None

def all_versions(state: ExecutionState, name: str) -> list[Artifact]:
    """Return all versions of this artifact, ordered by iteration."""
    return [a for a in state.artifacts if a.ref.name == name]
```

### 2.5 Invariants

- **ART-01:** No artifact is ever overwritten. `artifacts` is append-only.
- **ART-02:** Every artifact has a unique `(name, iteration, stage_id)` triple.
- **ART-03:** Guards reference artifacts via `latest()` or `at_iteration()`, never by positional index.
- **ART-04:** A stage's `output_artifacts` declaration must list every artifact name it produces. The runtime verifies this after stage execution.

### 2.6 Canonical Artifact Names

| Name | Type | Produced by | Description |
|------|------|------------|-------------|
| `prompt` | `str` | `generate`, `retry_generate` | Rendered prompt text (for logging, not for graph control) |
| `raw_response` | `str` | `generate`, `retry_generate` | Raw LLM output |
| `parsed` | `ParsedResponse` | `parse` | Structured parse result |
| `reconstruction` | `ReconstructionResult` | `reconstruct` | File mapping result |
| `assembled_code` | `str` | `reconstruct` | Final code for execution |
| `exec_result` | `dict` | `exec_eval` | Behavioral test outcome |
| `classification` | `dict` | `classify_reasoning` | Reasoning correctness + failure type |
| `alignment` | `dict` | `compute_alignment` | LEG category |
| `critique` | `str` | `critique` | LLM-generated critique text |
| `intervention` | `InterventionDecision` | `select_intervention` | Policy decision |
| `contract` | `dict` | `elicit_contract` | Elicited behavioral contract |
| `gate_result` | `dict` | `diff_gate_validate` | Contract gate validation |

---

## 3. STAGE SPECIFICATION (REVISED)

### 3.1 StageSpec

```python
@dataclass(frozen=True)
class StageSpec:
    stage_id: StageID
    family: StageFamily
    input_contract: InputContract
    output_artifacts: list[str]           # artifact names this stage MUST produce
    execution_contract: ExecutionContract  # output schema + error schema
    response_contract: ResponseContract | None  # for stages that process LLM output
    prompt_spec: PromptSpecRef | None
    timeout_seconds: int | None
    idempotent: bool
    failure_handling: FailureHandling     # what to do when this stage fails
```

### 3.2 InputContract (revised)

```python
@dataclass(frozen=True)
class InputContract:
    required_artifacts: list[str]   # artifact names that must exist via latest()
    optional_artifacts: list[str]   # may exist; absence is not an error
    required_state: list[str]       # non-artifact state fields (e.g., "iteration", "model")
```

### 3.3 ExecutionContract

Defines the expected output shape and error shape for a stage.

```python
@dataclass(frozen=True)
class ExecutionContract:
    output_schema: dict[str, type]    # artifact_name -> expected type
    error_schema: dict[str, type]     # error fields if stage fails
    must_produce_all: bool            # if True, ALL output_schema fields must be non-None on success
    may_produce_error: bool           # if True, stage may fail without crashing the graph
```

Example for `exec_eval`:
```python
ExecutionContract(
    output_schema={"exec_result": dict},  # must contain: pass, score, reasons
    error_schema={"exec_error": str},
    must_produce_all=True,
    may_produce_error=True,  # timeout or crash is a valid outcome, not a graph error
)
```

### 3.4 FailureHandling

```python
@dataclass(frozen=True)
class FailureHandling:
    on_timeout: FailureAction      # TERMINATE | RECORD_AND_CONTINUE | PROPAGATE
    on_exception: FailureAction
    on_contract_violation: FailureAction  # always PROPAGATE (graph bug)

class FailureAction(Enum):
    TERMINATE = "terminate"              # record terminal failure, end execution
    RECORD_AND_CONTINUE = "record"       # record failure artifact, continue to transition eval
    PROPAGATE = "propagate"              # raise to GraphRunner (graph construction bug)
```

For LLM stages (`GENERATION`, `CLASSIFY`, `CRITIQUE`):
- `on_timeout = RECORD_AND_CONTINUE` — a timeout is a valid outcome, produces a failure artifact, transition guards route to retry or terminal
- `on_exception = RECORD_AND_CONTINUE` — API errors are recoverable
- `on_contract_violation = PROPAGATE` — this is a bug

For pure computation stages (`PARSE`, `RECONSTRUCT`, `COMPUTE`):
- `on_timeout = PROPAGATE` — pure computation should not timeout
- `on_exception = RECORD_AND_CONTINUE` — parse failure is a valid outcome
- `on_contract_violation = PROPAGATE`

---

## 4. RESPONSE CONTRACT LAYER

### 4.1 Purpose

Defines how raw LLM output is processed into validated artifacts. Applied to every stage that receives LLM text.

### 4.2 ResponseContract

```python
@dataclass(frozen=True)
class ResponseContract:
    parse_fn: str           # function reference: "parse.parse_model_response"
    normalize_fn: str | None  # optional: "reconstructor.normalize_file_content"
    validate_fn: str | None   # optional: "reconstructor.validate_syntax"
    reconstruct_fn: str | None  # optional: "reconstructor.reconstruct_strict"

    expected_format: str    # "file_dict" | "code_string" | "json_structured" | "raw_text"
    required_output_fields: list[str]  # fields that must be non-None after parsing
    failure_mode: str       # "parse_error" | "format_violation" | "reconstruction_failure"
```

### 4.3 ResponseContract Bindings

| Stage | Contract | Parse | Normalize | Validate | Reconstruct |
|-------|----------|-------|-----------|----------|-------------|
| `generate` | Yes | `parse_model_response` | `normalize_file_content` | `ast.parse` per file | `reconstruct_strict` |
| `retry_generate` | Yes | `parse_model_response` | `normalize_file_content` | `ast.parse` per file | `reconstruct_strict` |
| `classify_reasoning` | Yes | `parse_classify_output` | None | output format check | None |
| `critique` | Yes | plain text extraction | None | non-empty check | None |
| `elicit_contract` | Yes | `parse_contract` | None | contract field validation | None |
| `parse` | No (this IS the parse stage) | — | — | — | — |
| `reconstruct` | No (this IS the reconstruct stage) | — | — | — | — |
| `exec_eval` | No (no LLM output) | — | — | — | — |

### 4.4 Contract Execution Order

For stages with a ResponseContract, the runtime applies the contract steps IN ORDER after receiving raw output:

```
raw_output → parse_fn → normalize_fn → validate_fn → reconstruct_fn → artifacts
```

Each step produces intermediate artifacts. If any step fails, the failure is recorded as an artifact (not silently dropped) and the stage's `failure_handling` rules determine what happens next.

---

## 5. POLICY LAYER (REVISED)

### 5.1 Policy Interface

```python
class Policy:
    def select_intervention(self, state: ExecutionState) -> InterventionDecision:
        """Pure function. Reads state, returns a decision. No side effects.
        No text generation. No prompt construction."""
```

### 5.2 InterventionDecision (REVISED — no text)

```python
@dataclass(frozen=True)
class InterventionDecision:
    action: InterventionAction
    level: int
    intervention_type: InterventionType  # enum that the prompt layer maps to content
    termination_reason: str | None
```

### 5.3 InterventionType (NEW — replaces feedback_text)

```python
class InterventionType(Enum):
    NONE = "none"                            # no intervention (first attempt or pass)
    TEST_OUTPUT_FEEDBACK = "test_output"      # include test failure output
    FAILURE_TYPE_HINT = "failure_hint"        # failure-type-specific hint
    LLM_CRITIQUE = "llm_critique"            # include critique stage output
    CONTRACT_CONSTRAINT = "contract"          # include behavioral contract
    ALIGNMENT_VERIFICATION = "alignment"      # include plan-code alignment check
```

The prompt system maps `InterventionType` to actual prompt content:

```python
# In prompt_builder.py (NOT in policy):
INTERVENTION_PROMPTS: dict[InterventionType, Callable[[ExecutionState], str]] = {
    InterventionType.TEST_OUTPUT_FEEDBACK: lambda s: format_test_feedback(latest(s, "exec_result")),
    InterventionType.FAILURE_TYPE_HINT: lambda s: get_hint_for_type(latest(s, "classification")),
    InterventionType.LLM_CRITIQUE: lambda s: latest(s, "critique").value,
    # ...
}
```

### 5.4 Separation Enforcement

- Policy outputs `InterventionType` (an enum value).
- Prompt layer maps `InterventionType` → text.
- Policy never sees prompt text. Prompt layer never makes flow decisions.
- If a new intervention type is needed, add it to the enum AND add a mapping in prompt_builder. Two files, explicit contract.

### 5.5 Intervention Ladder, Signal-to-Action Mapping, Pluggable Policies

Unchanged from v1 sections 5.4 and 5.5, except all references to `feedback_text` are replaced with `intervention_type`.

---

## 6. GRAPH RUNNER (NEW SECTION)

### 6.1 GraphRunner Definition

```python
class GraphRunner:
    """The ONLY execution entry point for all evaluation conditions.

    Direct calls to run_single, run_repair_loop, run_contract_gated,
    run_leg_reduction are forbidden after migration. All execution
    enters through GraphRunner.execute().
    """

    def execute(self, graph: ExecutionGraph, state: ExecutionState) -> ExecutionState:
        """Execute the graph to completion. Returns final state with terminal record."""
```

### 6.2 Execution Loop

```python
def execute(self, graph: ExecutionGraph, state: ExecutionState) -> ExecutionState:
    current_stage_id = graph.entry_stage

    while current_stage_id not in graph.terminal_stages:
        stage = graph.stages[current_stage_id]

        # 1. VERIFY INPUT CONTRACT
        self.verify_input_contract(stage, state)

        # 2. EXECUTE STAGE
        stage_output, error = self.execute_stage(stage, state)

        # 3. RECORD ARTIFACTS
        if error is None:
            for artifact_name, value in stage_output.items():
                state.artifacts.append(Artifact(
                    ref=ArtifactRef(name=artifact_name, iteration=state.iteration, stage_id=current_stage_id),
                    value=value,
                    timestamp=now(),
                    elapsed_seconds=elapsed,
                ))
        else:
            self.handle_stage_failure(stage, error, state)

        # 4. VERIFY EXECUTION CONTRACT
        self.verify_execution_contract(stage, state, error)

        # 5. LOG STAGE COMPLETION
        self.log_stage(current_stage_id, state, elapsed, error)

        # 6. EVALUATE TRANSITIONS
        transition = self.select_transition(graph, current_stage_id, state)

        # 7. EXECUTE SIDE EFFECTS
        for effect in transition.side_effects:
            effect.execute(state)

        # 8. LOG TRANSITION
        self.log_transition(transition, state)

        # 9. ADVANCE
        current_stage_id = transition.target

    # TERMINAL: record final state
    state.terminal = self.build_terminal_record(state)
    self.log_terminal(state)
    return state
```

### 6.3 Stage Execution Lifecycle

```python
def execute_stage(self, stage: StageSpec, state: ExecutionState) -> tuple[dict, str | None]:
    """Execute a single stage. Returns (output_dict, error_or_none).

    Lifecycle:
    1. If stage has prompt_spec: resolve prompt via PromptBuilder
    2. If stage has response_contract: prepare contract pipeline
    3. Call stage executor (the actual function: call_model, exec_evaluate, etc.)
    4. If stage has response_contract: apply parse → normalize → validate → reconstruct
    5. If timeout: return error artifact per failure_handling rules
    6. If exception: return error artifact per failure_handling rules
    7. If success: return output artifacts
    """
```

### 6.4 Transition Selection

```python
def select_transition(self, graph: ExecutionGraph, source: StageID, state: ExecutionState) -> TransitionSpec:
    """Select the unique valid transition from source.

    1. Collect all transitions where transition.source == source
    2. Evaluate each guard against current state
    3. Filter to guards that return True
    4. If exactly one: return it
    5. If multiple: select by lowest priority value
    6. If multiple with same priority: raise AmbiguousTransition (graph bug)
    7. If none: raise DeadEndState — but this CANNOT happen if compile-time
       validation passed (see section 8)
    """
```

### 6.5 Error Handling Within Stages

```python
def handle_stage_failure(self, stage: StageSpec, error: Exception, state: ExecutionState):
    """Apply stage's failure_handling rules."""
    fh = stage.failure_handling

    if isinstance(error, TimeoutError):
        action = fh.on_timeout
    elif isinstance(error, ContractViolation):
        action = fh.on_contract_violation
    else:
        action = fh.on_exception

    if action == FailureAction.PROPAGATE:
        raise GraphConstructionError(f"Stage {stage.stage_id} hit {type(error).__name__}: {error}")

    elif action == FailureAction.TERMINATE:
        state.terminal = TerminalRecord(
            outcome="stage_failure",
            pass_result=False,
            # ... fill from current state ...
        )
        # execution loop will see terminal is set and exit

    elif action == FailureAction.RECORD_AND_CONTINUE:
        state.artifacts.append(Artifact(
            ref=ArtifactRef(name=f"{stage.stage_id}_error", iteration=state.iteration, stage_id=stage.stage_id),
            value={"error_type": type(error).__name__, "message": str(error)},
            timestamp=now(),
            elapsed_seconds=0,
        ))
        # transition guards will route based on error artifact
```

### 6.6 Entry Point Enforcement

```python
# In runner.py, the ONLY call site:
def run_one_inner(case, model, condition, config):
    graph = GraphFactory.build(condition, config)
    state = ExecutionState.initialize(case, model, condition, config)
    return GraphRunner().execute(graph, state)
```

Forbidden after migration:
- `execution.run_single()`
- `execution.run_repair_loop()`
- `execution.run_contract_gated()`
- `execution.run_leg_reduction()`
- `retry_harness.run_retry_harness()`

All of these are subsumed by `GraphRunner.execute()` with the appropriate graph template and policy.

---

## 7. TRANSITION SYSTEM (REVISED)

### 7.1 TransitionSpec

Unchanged from v1 except for SideEffect.

### 7.2 Side Effects (REVISED — structured)

```python
@dataclass(frozen=True)
class SideEffect:
    name: str                           # human-readable identifier
    execute: Callable[[ExecutionState], None]  # deterministic function, append-only
    parameters: dict                    # static configuration

    # Pre-declared side effects:
    @staticmethod
    def increment_iteration() -> "SideEffect":
        return SideEffect(
            name="increment_iteration",
            execute=lambda s: setattr(s, 'iteration', s.iteration + 1),
            parameters={},
        )

    @staticmethod
    def record_trajectory_point() -> "SideEffect":
        def _record(state):
            er = latest(state, "exec_result")
            cl = latest(state, "classification")
            state.trajectory.append({
                "iteration": state.iteration,
                "pass": er.value.get("pass") if er else None,
                "score": er.value.get("score") if er else None,
                "category": cl.value.get("category") if cl else None,
            })
        return SideEffect(name="record_trajectory", execute=_record, parameters={})

    @staticmethod
    def decrement_budget() -> "SideEffect":
        return SideEffect(
            name="decrement_budget",
            execute=lambda s: setattr(s, 'budget_remaining', s.budget_remaining - 1),
            parameters={},
        )
```

**Execution order:** Side effects execute in list order (as declared in the TransitionSpec). Each side effect sees the state after all previous side effects have been applied.

**Constraints:**
- Side effects are deterministic (same state → same mutation).
- Side effects are append-only or counter-decrement only.
- Side effects must not read from external resources.
- Side effects must not raise exceptions.

### 7.3 Compile-Time Guard Coverage Validation (NEW)

At graph construction time, the GraphFactory validates:

```python
def validate_guard_coverage(graph: ExecutionGraph):
    """For each non-terminal stage, verify that its outgoing transitions
    cover ALL possible states.

    This is done by:
    1. Enumerate all outgoing transitions for the stage
    2. Verify that the guards form a complete partition:
       - at least one guard must be a "catch-all" (returns True for any state)
       - OR the guards must cover all enum values of the relevant artifact
    3. If coverage cannot be proven statically, require an explicit
       DEFAULT transition with lowest priority
    """
    for stage_id, stage in graph.stages.items():
        if stage_id in graph.terminal_stages:
            continue
        outgoing = [t for t in graph.transitions if t.source == stage_id]
        if not outgoing:
            raise GraphValidationError(f"Stage {stage_id} has no outgoing transitions")

        # Check for catch-all: a transition whose guard always returns True
        has_catchall = any(t.guard.is_catchall for t in outgoing)
        if not has_catchall:
            raise GraphValidationError(
                f"Stage {stage_id} has no catch-all transition. "
                f"Add a DEFAULT transition to prevent DeadEndState at runtime."
            )
```

With this validation, `DeadEndState` is impossible at runtime. The exception class is retained only as a defensive assertion.

---

## 8. EXECUTION STATE (REVISED)

### 8.1 Definition

```python
@dataclass
class ExecutionState:
    # Identity (immutable after construction)
    run_id: str
    case_id: str
    condition: str
    model: str
    trial: int
    max_attempts: int

    # Append-only artifact history
    artifacts: list[Artifact]

    # Append-only transition history
    transitions: list[TransitionRecord]

    # Append-only intervention history
    interventions: list[InterventionDecision]

    # Append-only trajectory
    trajectory: list[dict]

    # Counters (mutated only by SideEffects, verified against history)
    iteration: int = 0
    budget_remaining: int = 0   # initialized to max_attempts

    # Terminal (set exactly once by GraphRunner)
    terminal: TerminalRecord | None = None

    @staticmethod
    def initialize(case, model, condition, config) -> "ExecutionState":
        max_attempts = config.conditions[condition].retry.max_attempts
        return ExecutionState(
            run_id=config.run.run_id,
            case_id=case["id"],
            condition=condition,
            model=model,
            trial=config.run.trial,
            max_attempts=max_attempts,
            artifacts=[],
            transitions=[],
            interventions=[],
            trajectory=[],
            iteration=0,
            budget_remaining=max_attempts,
        )
```

Immutability and derived-value invariants unchanged from v1.

---

## 9. LOGGING AND OBSERVABILITY (REVISED)

### 9.1 Prompt Identity Logging (NEW)

Every LLM stage logs two identity objects:

**PromptConfigIdentity** — what template was used:
```json
{
    "template_id": "baseline",
    "condition": "retry_adaptive",
    "intervention_type": "failure_hint",
    "case_id": "alias_config_b",
    "iteration": 2
}
```

**PromptCallIdentity** — what was actually sent:
```json
{
    "prompt_hash": "sha256:a1b2c3...",
    "prompt_length": 2847,
    "model": "gpt-5.4-mini",
    "temperature": 0.0,
    "file_paths": ["code_snippets_v2/alias_config_b/app.py", "..."],
    "output_format": "v2"
}
```

These are logged as part of the per-stage log (section 9.2) and as part of the call_logger record.

### 9.2 Per-Stage Log (REVISED)

```json
{
    "event": "stage_complete",
    "run_id": "...",
    "case_id": "...",
    "condition": "...",
    "stage_id": "generate",
    "iteration": 2,
    "elapsed_seconds": 4.2,
    "artifacts_produced": ["raw_response"],
    "error": null,
    "prompt_config_identity": {"template_id": "baseline", "intervention_type": "failure_hint"},
    "prompt_call_identity": {"prompt_hash": "sha256:...", "prompt_length": 2847, "model": "gpt-5.4-mini"},
    "timestamp": "..."
}
```

Stages without LLM calls omit the `prompt_config_identity` and `prompt_call_identity` fields.

### 9.3 Per-Transition Log

Unchanged from v1.

### 9.4 Policy Decision Log (REVISED)

```json
{
    "event": "policy_decision",
    "run_id": "...",
    "case_id": "...",
    "iteration": 2,
    "action": "retry_hint",
    "level": 2,
    "intervention_type": "failure_hint",
    "signals": {
        "pass": false,
        "failure_type": "HIDDEN_DEPENDENCY",
        "stagnation": false,
        "score_trend": "flat"
    },
    "timestamp": "..."
}
```

Note: `feedback_text_length` removed (policy no longer produces text). Replaced with `intervention_type` which the prompt layer will resolve.

### 9.5 Terminal Log

Unchanged from v1.

---

## 10. VALIDATION AND INVARIANTS (REVISED)

### 10.1 Graph Construction Invariants

v1 GV-01 through GV-07 unchanged, plus:

```
GV-08: Every non-terminal stage has a catch-all outgoing transition (guarantees no DeadEndState)
GV-09: Every stage's output_artifacts are a subset of the execution_contract.output_schema keys
GV-10: Every stage with a response_contract has family in (GENERATION, CLASSIFY, CRITIQUE, RETRY_GENERATION)
```

### 10.2 Runtime Invariants

v1 RV-01 through RV-07 unchanged, plus:

```
RV-08: Every artifact has a unique (name, iteration, stage_id) triple
RV-09: Stage execution_contract is verified after every stage (all declared outputs produced)
RV-10: Policy.select_intervention is called with immutable state snapshot (no mutation during policy execution)
```

---

## 11. GRAPH TEMPLATES

Unchanged from v1 section 6.

---

## 12. MAPPING TO CURRENT SYSTEM

### 12.1 Current Pipeline → Graph Stages

Unchanged from v1 section 10.1.

### 12.2 Current Conditions → Graph Templates + Policies

Unchanged from v1 section 10.2.

### 12.3 Legacy Function Retirement

| Legacy function | Retired in | Replaced by |
|----------------|-----------|-------------|
| `execution.run_single()` | Phase 1 | `GraphRunner.execute(single_shot_graph, state)` |
| `execution.run_repair_loop()` | Phase 2 | `GraphRunner.execute(retry_graph, state)` with `RetryPlainPolicy(max=2)` |
| `execution.run_contract_gated()` | Phase 2 | `GraphRunner.execute(contract_graph, state)` with `ContractPolicy` |
| `execution.run_leg_reduction()` | Phase 2 | `GraphRunner.execute(leg_reduction_graph, state)` with `BaselinePolicy` |
| `retry_harness.run_retry_harness()` | Phase 2 | `GraphRunner.execute(retry_graph, state)` with appropriate policy |

After Phase 2, none of these functions exist. `GraphRunner.execute()` is the single execution entry point.

---

## 13. IMPLEMENTATION PLAN

### Phase 1: Constrained State Machine

Unchanged from v1, plus:
- Implement `Artifact`, `ArtifactRef`, `ExecutionState` with versioned artifact storage
- Implement `GraphRunner.execute()` with the loop from section 6.2
- Implement `ResponseContract` for `generate` and `classify_reasoning` stages
- Implement compile-time guard coverage validation
- Map `baseline` condition. Verify identical results.

### Phase 2: Graph Generalization

Unchanged from v1, plus:
- Implement all `ResponseContract` bindings from section 4.3
- Implement `InterventionType` enum and prompt layer mapping
- Implement `FailureHandling` for all stage families
- Remove all legacy execution functions
- Enforce: `GraphRunner` is the only entry point

### Phase 3: Policy Modularization

Unchanged from v1, plus:
- Add `PromptConfigIdentity` and `PromptCallIdentity` to all LLM stage logs
- Add structured `SideEffect` with parameter logging
- Policy parameters fully configurable in YAML

---

## APPENDIX A: ARCHITECTURAL SEPARATION SUMMARY

```
POLICY decides WHAT to do        → InterventionType enum
PROMPT LAYER decides WHAT TO SAY → prompt text from template + intervention_type
GRAPH decides WHEN to do it      → stage ordering + transition guards
STAGES do THE WORK               → call_model, parse, exec_evaluate, etc.
STATE records WHAT HAPPENED       → append-only artifacts + transitions
LOGGING records EVERYTHING        → stage logs, transition logs, policy logs, prompt identities
```

No layer reaches into another. All communication is via typed interfaces.
