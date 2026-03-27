# ExecutionStrategy Spec: Graph + Policy Runtime

**Version:** 1.0
**Date:** 2026-03-27
**Status:** Design specification. Not yet implemented.

---

## 1. EXECUTION MODEL

### 1.1 Core Principle

Execution is a controlled traversal of a directed graph where:
- **Nodes** are typed processing stages with input/output contracts
- **Edges** are guarded transitions with typed predicates over accumulated state
- **Policy** is a pure function that selects among valid transitions
- **State** is an append-only log of all stage outputs and transition decisions

The graph defines what transitions are structurally possible.
The policy decides which transition to take at runtime.
These are separate concerns. The graph never calls the policy. The policy never modifies the graph.

### 1.2 Formal Definitions

```
ExecutionGraph = (Stages, Transitions, EntryStage, TerminalStages)

Stages         : dict[StageID, StageSpec]
Transitions    : list[TransitionSpec]
EntryStage     : StageID
TerminalStages : set[StageID]

StageID        : str   # unique identifier, e.g., "generate", "parse", "exec_eval"
```

### 1.3 Invariants of the Execution Model

- **INV-G1:** Every graph has exactly one `EntryStage`.
- **INV-G2:** Every non-terminal stage has at least one outgoing transition.
- **INV-G3:** Every terminal stage has zero outgoing transitions.
- **INV-G4:** Every stage is reachable from `EntryStage` (no orphaned nodes).
- **INV-G5:** Every cycle in the graph passes through at least one transition with a `budget_field` guard (no unbounded loops).
- **INV-G6:** The graph is static after construction. No runtime modification.

---

## 2. STAGE SPECIFICATION

### 2.1 StageSpec

```python
@dataclass(frozen=True)
class StageSpec:
    stage_id: StageID
    family: StageFamily              # taxonomy classification
    input_contract: InputContract     # required fields in state
    output_fields: list[str]          # fields this stage writes to state
    prompt_spec: PromptSpecRef | None # reference to prompt template (NOT the prompt itself)
    timeout_seconds: int | None       # hard timeout for this stage
    idempotent: bool                  # safe to re-execute with same inputs?
```

### 2.2 StageFamily Taxonomy

| Family | Description | Performs network I/O? | Mutates external state? |
|--------|------------|----------------------|------------------------|
| `GENERATION` | LLM call to produce candidate code | Yes (LLM API) | No |
| `PARSE` | Extract structured data from raw LLM response | No | No |
| `RECONSTRUCT` | Map parsed output to file-level program structure | No | No |
| `EXEC_EVAL` | Run candidate code against behavioral tests | No (subprocess) | No |
| `CLASSIFY` | LLM call to classify failure type or reasoning correctness | Yes (LLM API) | No |
| `CRITIQUE` | LLM call to analyze failure and suggest correction | Yes (LLM API) | No |
| `INTERVENTION_SELECT` | Policy-driven selection of next intervention strategy | No | No |
| `RETRY_GENERATION` | LLM call with augmented context (feedback, contract, hints) | Yes (LLM API) | No |
| `TERMINAL` | Final state. No processing. Records outcome. | No | No |

### 2.3 InputContract

```python
@dataclass(frozen=True)
class InputContract:
    required_fields: list[str]      # must exist in state and be non-None
    optional_fields: list[str]      # may exist; absence is not an error
```

A stage may only execute if all `required_fields` are present and non-None in the current `ExecutionState`. If any required field is missing, the runtime raises `ContractViolation` — this is a graph construction bug, not a runtime error.

### 2.4 Stage Definitions (Canonical Set)

**`generate`**
- Family: `GENERATION`
- Input: `prompt: str`, `model: str`, `file_paths: list[str]`
- Output: `raw_response: str`, `generation_elapsed: float`
- Prompt: references a PromptSpec by ID (e.g., `"baseline"`, `"diagnostic"`)
- Timeout: from config (`models.generation.timeout` or 120s default)

**`parse`**
- Family: `PARSE`
- Input: `raw_response: str`
- Output: `parsed: ParsedResponse` (reasoning, code, files, response_format, parse_error)
- Prompt: None (pure computation)
- Timeout: None

**`reconstruct`**
- Family: `RECONSTRUCT`
- Input: `parsed: ParsedResponse`, `manifest_files: dict[str, str]`
- Output: `reconstruction: ReconstructionResult`
- Prompt: None
- Timeout: None

**`exec_eval`**
- Family: `EXEC_EVAL`
- Input: `code: str`, `case: dict`
- Output: `exec_result: dict` (pass, score, reasons, execution metadata)
- Prompt: None
- Timeout: from config (`evaluation.subprocess_timeout`)

**`classify_reasoning`**
- Family: `CLASSIFY`
- Input: `case: dict`, `code: str`, `reasoning: str`
- Output: `classification: dict` (reasoning_correct, failure_type)
- Prompt: references `"reasoning_classifier"` PromptSpec
- Timeout: 120s

**`compute_alignment`**
- Family: `INTERVENTION_SELECT` (pure computation, no LLM)
- Input: `exec_result: dict`, `classification: dict`
- Output: `alignment: dict` (category, leg_true, lucky_fix, etc.)
- Prompt: None
- Timeout: None

**`log_terminal`**
- Family: `TERMINAL`
- Input: all accumulated state
- Output: (none — writes to log, emits event, records terminal state)
- Prompt: None
- Timeout: None

**`critique`**
- Family: `CRITIQUE`
- Input: `case: dict`, `code: str`, `exec_result: dict`, `classification: dict`
- Output: `critique_text: str`, `suggested_fix: str`
- Prompt: references `"critique"` PromptSpec
- Timeout: 120s

**`select_intervention`**
- Family: `INTERVENTION_SELECT`
- Input: `exec_result: dict`, `classification: dict`, `iteration: int`, `trajectory: list[dict]`
- Output: `intervention: InterventionDecision`
- Prompt: None (policy-driven pure computation)
- Timeout: None

**`retry_generate`**
- Family: `RETRY_GENERATION`
- Input: `prompt: str`, `feedback: str`, `model: str`, `file_paths: list[str]`
- Output: `raw_response: str`, `generation_elapsed: float`
- Prompt: references augmented PromptSpec (base + feedback)
- Timeout: from config

---

## 3. ARCHITECTURAL SEPARATION: PROMPTS vs EXECUTION

### 3.1 Principle

The prompt system and the execution system are strictly separate layers.

```
Execution layer: WHAT happens and in WHAT ORDER
Prompt layer:    WHAT TEXT is sent to the model
```

### 3.2 Boundaries

| Concern | Owner | May NOT |
|---------|-------|---------|
| Which stage runs next | ExecutionGraph + Policy | Reference prompt content |
| What text goes to the model | PromptSpec + PromptBuilder | Modify execution flow |
| What model to call | Config + Stage params | Be decided by prompt content |
| How to interpret the response | ParseStage | Depend on which prompt was used |

### 3.3 PromptSpec

```python
@dataclass(frozen=True)
class PromptSpecRef:
    template_id: str            # e.g., "baseline", "diagnostic", "critique"
    # The actual prompt content is resolved at runtime by the PromptBuilder,
    # which reads the template and fills in case data, code files, etc.
    # The execution layer never sees prompt text directly.
```

A `StageSpec` holds a `PromptSpecRef`, not a prompt string. The execution runtime calls `PromptBuilder.build(spec_ref, state)` to produce the actual prompt text immediately before the LLM call. This ensures:
- Graph structure does not depend on prompt content
- Prompts can be changed without modifying the graph
- Policy decisions never inspect prompt text

### 3.4 Forbidden

- Policy reading prompt text to make decisions
- Transition guards inspecting prompt content
- Stages modifying prompt templates at runtime
- Graph edges conditioned on prompt wording

---

## 4. TRANSITION SYSTEM

### 4.1 TransitionSpec

```python
@dataclass(frozen=True)
class TransitionSpec:
    source: StageID
    target: StageID
    label: TransitionLabel          # semantic label
    guard: Guard                    # predicate over ExecutionState
    priority: int                   # lower number = higher priority (for disambiguation)
    side_effects: list[SideEffect]  # e.g., increment iteration counter
```

### 4.2 TransitionLabel (Enum)

```python
class TransitionLabel(Enum):
    PASS = "pass"                        # stage succeeded, proceed forward
    FAIL_LOGIC = "fail_logic"            # behavioral test failed
    FAIL_PARSE = "fail_parse"            # response could not be parsed
    FAIL_RECONSTRUCT = "fail_reconstruct"  # reconstruction failed
    FAIL_TIMEOUT = "fail_timeout"        # stage timed out
    RETRY = "retry"                      # policy decided to retry
    ESCALATE = "escalate"                # policy decided to escalate intervention
    TERMINATE_SUCCESS = "terminate_success"
    TERMINATE_FAILURE = "terminate_failure"
    TERMINATE_BUDGET = "terminate_budget"  # retry budget exhausted
```

### 4.3 Guard

```python
@dataclass(frozen=True)
class Guard:
    predicate: str    # human-readable description
    evaluate: Callable[[ExecutionState], bool]
```

Guards are pure functions over `ExecutionState`. They may inspect any field but must not mutate state.

Examples:
- `"exec_result.pass == True"` → forward to terminal success
- `"exec_result.pass == False AND iteration < max_attempts"` → forward to retry
- `"exec_result.pass == False AND iteration >= max_attempts"` → forward to terminal failure
- `"reconstruction.status != SUCCESS"` → forward to terminal with reconstruction failure

### 4.4 Disambiguation

When multiple transitions from the same source have guards that evaluate to `True`:
1. Select the transition with the lowest `priority` value.
2. If priorities are equal, this is a graph construction error. The runtime raises `AmbiguousTransition`.

There is no "default" transition. Every possible state must be covered by at least one guard from each non-terminal stage, or the runtime raises `DeadEndState`.

### 4.5 Side Effects

```python
class SideEffect(Enum):
    INCREMENT_ITERATION = "increment_iteration"
    RECORD_TRAJECTORY_POINT = "record_trajectory_point"
    LOG_TRANSITION = "log_transition"
```

Side effects are declarative. The runtime executes them after the transition is selected but before the target stage runs. Side effects are append-only operations on `ExecutionState`.

---

## 5. POLICY LAYER

### 5.1 Policy Interface

```python
class Policy:
    def select_intervention(self, state: ExecutionState) -> InterventionDecision:
        """Given accumulated state, decide what to do next.

        Inputs (read from state):
            exec_result: latest execution outcome
            classification: failure type + reasoning correctness
            iteration: current attempt count
            trajectory: list of (pass, score, category) per attempt
            trajectory_signals: stagnation, divergence, oscillation flags
            contract_violations: list of violated contract clauses (if any)
            budget_remaining: max_attempts - iteration

        Output:
            InterventionDecision specifying next action
        """
```

### 5.2 InterventionDecision

```python
@dataclass(frozen=True)
class InterventionDecision:
    action: InterventionAction
    level: int                  # escalation level (0 = none, 1 = hint, 2 = critique, 3 = contract)
    feedback_text: str | None   # text to include in retry prompt (if action is RETRY)
    termination_reason: str | None  # reason if action is TERMINATE
```

### 5.3 InterventionAction (Enum)

```python
class InterventionAction(Enum):
    CONTINUE = "continue"         # proceed to next stage (no intervention)
    RETRY_PLAIN = "retry_plain"   # retry with test output feedback only
    RETRY_HINT = "retry_hint"     # retry with failure-type-specific hint
    RETRY_CRITIQUE = "retry_critique"  # retry with LLM-generated critique
    RETRY_CONTRACT = "retry_contract"  # retry with contract constraints
    TERMINATE = "terminate"       # stop execution, record outcome
```

### 5.4 Intervention Ladder

The policy implements a multi-level escalation strategy. The level increases with each failed attempt:

```
Level 0: No intervention (first attempt)
Level 1: Plain retry with test output
Level 2: Failure-type-specific hint (adaptive)
Level 3: LLM-generated critique feedback
Level 4: Contract-gated retry
Level 5: Terminate (budget exhausted)
```

The mapping from signals to actions:

| Signal | Condition | Action |
|--------|-----------|--------|
| First attempt | `iteration == 0` | `CONTINUE` (no retry) |
| Pass | `exec_result.pass == True` | `TERMINATE` (success) |
| Fail, budget remaining, no stagnation | `iteration < max AND NOT stagnant` | Escalate to next level |
| Fail, stagnating | `consecutive_same_failure >= 2` | Skip to level 3 or 4 |
| Fail, diverging | `score decreasing` | `TERMINATE` (divergence) |
| Budget exhausted | `iteration >= max_attempts` | `TERMINATE` (budget) |

### 5.5 Policy is Pluggable

Different experimental conditions use different policy implementations:
- `BaselinePolicy`: no retry, always terminate after first attempt
- `RetryPlainPolicy`: retry with test output, no escalation
- `RetryAdaptivePolicy`: full escalation ladder
- `RetryContractPolicy`: contract-gated from first retry
- `RetryAlignmentPolicy`: critique + alignment verification

The condition name in the config maps to a policy class. The graph structure may be shared; the policy determines behavior.

---

## 6. GRAPH TEMPLATES

### 6.1 Single-Shot (baseline, diagnostic, guardrail, etc.)

```
[generate] → [parse] → [reconstruct] → [exec_eval] → [classify_reasoning] → [compute_alignment] → [log_terminal]
```

No loops. No retry. One attempt. Policy is `BaselinePolicy` (always proceeds forward, terminates after eval).

### 6.2 Retry Loop (retry_no_contract, retry_adaptive)

```
[generate] → [parse] → [reconstruct] → [exec_eval] → [classify_reasoning] → [compute_alignment]
     ↑                                                                              ↓
     └──────── [select_intervention] ← [critique (optional)] ←─────────────────────┘
                        ↓
                  [log_terminal] (if TERMINATE)
```

Loop bounded by `max_attempts` from config. Policy selects intervention level per iteration.

### 6.3 Contract-Gated (contract_gated)

```
[elicit_contract] → [generate_with_contract] → [parse] → [reconstruct] → [diff_gate_validate]
                                                                                    ↓
                          ┌─────── GATE PASS ────── [exec_eval] → [classify] → [log_terminal]
                          │
                   GATE FAIL → [retry_generate_with_violations] → [parse] → [reconstruct] → [diff_gate_validate]
                                                                                                      ↓
                                                                                              [exec_eval] → [log_terminal]
```

Contract is elicited once. Gate validation may trigger one retry. Budget = 2 attempts max.

### 6.4 LEG-Reduction (leg_reduction)

```
[generate_structured] → [parse_structured] → [exec_eval] → [classify_reasoning] → [compute_alignment] → [log_terminal]
```

Single-shot but with a specialized prompt that instructs plan→verify→revise within one LLM call. No external retry loop.

### 6.5 Audit-Heavy Loop (future, not yet implemented)

```
[generate] → [parse] → [reconstruct] → [exec_eval] → [classify] → [alignment]
     ↑                                                                    ↓
     │                                                          [audit_reasoning]
     │                                                                    ↓
     └──────── [select_intervention] ← [generate_targeted_critique] ←────┘
                        ↓
                  [log_terminal]
```

Adds explicit reasoning audit before intervention selection. For research into reasoning-execution gap diagnosis.

---

## 7. EXECUTION STATE

### 7.1 Definition

```python
@dataclass
class ExecutionState:
    # Identity
    run_id: str
    case_id: str
    condition: str
    model: str
    trial: int

    # Append-only history
    stage_outputs: list[StageOutput]     # ordered list of all stage results
    transitions: list[TransitionRecord]  # ordered list of all transitions taken
    interventions: list[InterventionDecision]  # ordered list of all policy decisions

    # Current counters (derived from history, cached for convenience)
    iteration: int = 0
    budget_remaining: int = 0

    # Terminal state (set exactly once)
    terminal: TerminalRecord | None = None
```

### 7.2 StageOutput

```python
@dataclass(frozen=True)
class StageOutput:
    stage_id: StageID
    iteration: int
    timestamp: str
    elapsed_seconds: float
    output: dict          # stage-specific output fields
    error: str | None     # None if stage succeeded
```

### 7.3 TransitionRecord

```python
@dataclass(frozen=True)
class TransitionRecord:
    source: StageID
    target: StageID
    label: TransitionLabel
    guard_description: str
    timestamp: str
```

### 7.4 TerminalRecord

```python
@dataclass(frozen=True)
class TerminalRecord:
    outcome: str           # "success", "failure", "timeout", "budget_exhausted", "parse_failure"
    pass_result: bool
    score: float
    reasons: list[str]
    alignment: dict        # category, leg_true, lucky_fix, etc.
    total_iterations: int
    total_llm_calls: int
    total_elapsed: float
```

### 7.5 Immutability Guarantee

`stage_outputs`, `transitions`, and `interventions` are append-only lists. No element is ever modified or removed after insertion. This guarantees:
- Full replay from initial state
- Deterministic reconstruction of execution trace
- No hidden state mutation between stages

The `iteration` and `budget_remaining` counters are derived values that MUST equal:
```
iteration == len([t for t in transitions if t.label == RETRY])
budget_remaining == max_attempts - iteration
```

If these ever diverge, the runtime raises `StateCorruption`.

---

## 8. VALIDATION AND INVARIANTS

### 8.1 Graph Construction Invariants (checked once at build time)

```
GV-01: Exactly one EntryStage
GV-02: All non-terminal stages have at least one outgoing transition
GV-03: All terminal stages have zero outgoing transitions
GV-04: All stages reachable from EntryStage (BFS/DFS check)
GV-05: Every cycle passes through a transition with budget guard
GV-06: No two transitions from the same source have equal priority and overlapping guards
GV-07: Every stage's input_contract is satisfiable (all required fields are produced by some upstream stage)
```

### 8.2 Runtime Invariants (checked on every transition)

```
RV-01: Current stage's input_contract is satisfied before execution
RV-02: Exactly one transition guard evaluates to True (or disambiguation by priority succeeds)
RV-03: iteration <= max_attempts at all times
RV-04: State is append-only (no field overwritten, no list element modified)
RV-05: Terminal state is set exactly once
RV-06: Every stage that performs network I/O has a timeout
RV-07: Every LLM call is logged (call_logger receives the call before response is processed)
```

### 8.3 Termination Guarantee

Every graph must terminate. This is guaranteed by:
- Every cycle includes a `budget_remaining > 0` guard on its back-edge
- `budget_remaining` strictly decreases on every retry transition (via `INCREMENT_ITERATION` side effect)
- When `budget_remaining == 0`, the only valid transition is to a terminal stage

Maximum execution time per case: `max_attempts * timeout_per_stage`. With `max_attempts=5` and `timeout=120s`, worst case is 10 minutes per case.

---

## 9. LOGGING AND OBSERVABILITY

### 9.1 Per-Stage Log

Emitted by the runtime after every stage execution:

```json
{
    "event": "stage_complete",
    "run_id": "...",
    "case_id": "...",
    "condition": "...",
    "stage_id": "exec_eval",
    "iteration": 2,
    "elapsed_seconds": 3.4,
    "output_summary": {"pass": false, "score": 0.2},
    "error": null,
    "timestamp": "..."
}
```

### 9.2 Per-Transition Log

```json
{
    "event": "transition",
    "run_id": "...",
    "case_id": "...",
    "source": "compute_alignment",
    "target": "select_intervention",
    "label": "fail_logic",
    "guard": "exec_result.pass == False AND iteration < 5",
    "timestamp": "..."
}
```

### 9.3 Policy Decision Log

```json
{
    "event": "policy_decision",
    "run_id": "...",
    "case_id": "...",
    "iteration": 2,
    "action": "retry_hint",
    "level": 2,
    "signals": {
        "pass": false,
        "failure_type": "HIDDEN_DEPENDENCY",
        "stagnation": false,
        "score_trend": "flat"
    },
    "feedback_text_length": 142,
    "timestamp": "..."
}
```

### 9.4 Terminal Log

```json
{
    "event": "terminal",
    "run_id": "...",
    "case_id": "...",
    "condition": "retry_adaptive",
    "outcome": "failure",
    "pass": false,
    "score": 0.2,
    "category": "leg",
    "total_iterations": 5,
    "total_llm_calls": 12,
    "total_elapsed": 47.3,
    "timestamp": "..."
}
```

All logs go through the existing `call_logger` (for LLM calls) and `RunLogger` (for evaluation records) systems. The execution runtime adds structured stage/transition/policy logs as a new log stream that is append-only to the run directory.

---

## 10. MAPPING TO CURRENT SYSTEM

### 10.1 Current Pipeline → Graph Nodes

| Current function | Graph stage | Notes |
|-----------------|------------|-------|
| `execution.build_prompt()` | Part of `generate` stage setup | Prompt construction is not a separate stage; it's the `generate` stage's preparation step |
| `llm.call_model()` | `generate` stage execution | Network I/O happens here |
| `parse.parse_model_response()` | `parse` stage | Pure computation |
| `reconstructor.reconstruct_strict()` | `reconstruct` stage | Pure computation |
| `exec_eval.exec_evaluate()` | `exec_eval` stage | Subprocess or in-process |
| `evaluator.llm_classify()` | `classify_reasoning` stage | Network I/O (evaluator LLM call) |
| `evaluator.compute_alignment()` | `compute_alignment` stage | Pure computation |
| `execution.write_log()` + `_emit_metrics_event()` | `log_terminal` stage | I/O (file + optional Redis) |

### 10.2 Current Conditions → Graph Templates

| Condition | Graph template | Policy |
|-----------|---------------|--------|
| `baseline` | Single-shot (6.1) | `BaselinePolicy` |
| `diagnostic` | Single-shot (6.1) | `BaselinePolicy` (different PromptSpec) |
| `guardrail` | Single-shot (6.1) | `BaselinePolicy` (different PromptSpec) |
| `guardrail_strict` | Single-shot (6.1) | `BaselinePolicy` (different PromptSpec) |
| `repair_loop` | Retry loop (6.2) | `RetryPlainPolicy(max_attempts=2)` |
| `retry_no_contract` | Retry loop (6.2) | `RetryPlainPolicy(max_attempts=5)` |
| `retry_adaptive` | Retry loop (6.2) | `RetryAdaptivePolicy(max_attempts=5)` |
| `retry_alignment` | Retry loop (6.2) | `RetryAlignmentPolicy(max_attempts=5)` |
| `contract_gated` | Contract-gated (6.3) | `ContractPolicy(max_attempts=2)` |
| `leg_reduction` | LEG-reduction (6.4) | `BaselinePolicy` (specialized PromptSpec) |

### 10.3 Key Insight

The current system already implements these graph templates — but as ad-hoc `if/elif` chains in `execution.py` (`run_single`, `run_repair_loop`, `run_contract_gated`, `run_leg_reduction`). Each function is a hardcoded graph traversal. The spec formalizes these into declarative graph definitions, making the execution logic:
- Auditable (the graph IS the documentation)
- Testable (validate graph invariants at construction time)
- Extensible (add a new condition = define a new graph + policy, not a new function)

---

## 11. IMPLEMENTATION PLAN

### Phase 1: Constrained State Machine (no full DAG)

**Goal:** Replace the `if/elif` dispatch in `_run_one_inner()` with a data-driven state machine where each condition maps to a sequence of stages.

**Scope:**
- Define `StageSpec`, `TransitionSpec`, `ExecutionState` as Python dataclasses
- Define `SingleShotGraph` and `RetryLoopGraph` as the two graph templates
- Implement `GraphRunner.execute(graph, state)` that traverses the graph sequentially
- Map `baseline` and `retry_no_contract` conditions to the new runner
- Keep all other conditions on the existing path during migration

**Constraint:** The `GraphRunner` is the ONLY new execution path. It calls the same underlying functions (`call_model`, `parse_model_response`, `exec_evaluate`, `llm_classify`). It does NOT duplicate their logic.

**Deliverable:** `baseline` condition produces identical results through GraphRunner as through `run_single`.

### Phase 2: Graph Generalization

**Goal:** Migrate all conditions to graph-based execution. Remove `run_repair_loop`, `run_contract_gated`, `run_leg_reduction` as separate functions.

**Scope:**
- Define `ContractGatedGraph` and `LEGReductionGraph` templates
- Implement `Policy` interface with `BaselinePolicy`, `RetryPlainPolicy`, `RetryAdaptivePolicy`
- Wire `select_intervention` stage to policy lookup
- Remove all condition-specific execution functions from `execution.py`
- `_run_one_inner()` becomes: `graph = build_graph(condition, config); result = GraphRunner.execute(graph, state)`

**Constraint:** Single execution path. All conditions go through `GraphRunner`. No fallback to old functions.

**Deliverable:** All 16 conditions produce identical results through GraphRunner.

### Phase 3: Policy Modularization

**Goal:** Make policies first-class configurable objects defined in YAML.

**Scope:**
- Define policy parameters in config (`conditions.retry_adaptive.policy.escalation_levels`, etc.)
- Implement `PolicyFactory.from_config(condition_config)` that returns a `Policy` instance
- Enable new experimental conditions by adding config entries — no code changes required
- Add policy decision logging (section 9.3)
- Add graph validation at construction time (section 8.1)

**Constraint:** Adding a new experimental condition must require ZERO code changes — only a new config entry (graph template ID + policy parameters + PromptSpec references).

**Deliverable:** New condition `retry_escalation_v2` added by creating a config entry only. No Python code modified.
