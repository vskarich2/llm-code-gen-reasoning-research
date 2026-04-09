Date: 2026-04-09
Time: 18:30

# STATE MACHINE CONTROLLER DESIGN v2

Outer control layer that orchestrates multiple DAG executions (attempts).
DAG remains acyclic. All iteration logic lives here.

---

## 1. STATE MACHINE DIAGRAM

```
                    ┌──────┐
                    │ INIT │
                    └──┬───┘
                       │ policy = resolve_condition_policy(condition, config, case)
                       │ input = {case, condition, model, config, retry_context: None}
                       ▼
                ┌──────────────┐
         ┌─────│ RUN_ATTEMPT   │◄──────────────────────┐
         │     │ run_attempt()  │                       │
         │     └──────┬────────┘                       │
         │            │ trajectory.append(attempt)      │
         │            ▼                                 │
         │     ┌──────────────┐                        │
         │     │  DECISION     │                       │
         │     │  policy.      │                       │
         │     │  should_      │                       │
         │     │  continue()   │                       │
         │     └──┬────────┬──┘                        │
         │  done  │        │ continue                  │
         │        │        ▼                           │
         │        │  ┌───────────┐                     │
         │        │  │ CRITIQUE  │                     │
         │        │  │ policy.   │                     │
         │        │  │ generate_ │                     │
         │        │  │ critique()│                     │
         │        │  │ policy.   │─────────────────────┘
         │        │  │ build_    │   returns input dict
         │        │  │ next_     │
         │        │  │ input()   │
         │        │  └───────────┘
         ▼        ▼
       ┌──────────────┐
       │     DONE      │
       │ select_best() │
       │ return        │
       │ RunResult     │
       └──────────────┘
```

---

## 2. TYPE DEFINITIONS

### AttemptState

```python
class AttemptState(TypedDict):
    case: dict
    condition: str
    model: str

    prompt: str
    prompt_meta: dict

    raw_response: str

    parsed_generation: Any
    routing: Any
    parse_mode: str

    normalized_reasoning: Any

    reconstructed_code: str
    artifact_id: str

    classifier_summary: dict
    oracle_summary: dict

    ast_result: dict

    execution_result: dict
    passed: bool

    spec_oracle_result: Optional[dict]

    signals: Any
    disagreement: dict
    evaluation: dict
```

AttemptState does NOT contain config. Config is never read from a previous attempt.

### RunResult

```python
class RunResult(TypedDict):
    case_id: str
    condition: str
    trajectory: List[AttemptState]
    final: AttemptState
```

### RetryContext

```python
class RetryContext(TypedDict):
    attempt_index: int          # >= 1
    prev_raw: str               # previous attempt's raw LLM response
    prev_code: str              # previous attempt's reconstructed code
    test_feedback: str          # joined exec failure reasons
    critique_text: str          # LLM-generated mismatch critique (may be "")
    depth_hint: Optional[str]   # static depth hint (overrides critique_text if present)
    classifier_hint: str        # adaptive mode classifier hint (may be "")
```

### DAG Input Schema

```python
class DAGInput(TypedDict):
    case: dict
    condition: str
    model: str
    config: Any
    retry_context: Optional[RetryContext]  # None on attempt 0
```

---

## 3. ConditionPolicy (ALL behavior lives here)

The state machine calls ONLY policy methods. No critique-specific branching
exists in the state machine.

```python
class ConditionPolicy:

    name: str
    max_attempts: int
    stop_on_pass: bool
    critique_type: str          # "none"|"bare_retry"|"strict"|"moderate"|
                                # "aggressive"|"reasoning_only"|"test_feedback"|"adaptive"
    depth_hint_level: str|None  # "gentle"|"directed"|"explicit"|None
    evaluator_model: str        # config.models.evaluator.name
    task: str                   # case["task"] — needed for test_feedback prompts
    schema_line: str            # JSON schema hint for retry prompt
```

### policy.should_continue()

```python
    def should_continue(
        self,
        attempt: AttemptState,
        attempt_index: int,
    ) -> bool:
        """Decide whether to run another attempt.

        Returns False if:
          - passed and stop_on_pass is True
          - attempt_index >= max_attempts - 1
          - parse failed (no executable artifact)
          - critique requires reasoning but reasoning is absent (degenerate case)
        """
        # Passed — done
        if attempt["passed"] and self.stop_on_pass:
            return False

        # Hit attempt limit
        if attempt_index >= self.max_attempts - 1:
            return False

        # Parse failed — nothing executable to critique
        if attempt["parse_mode"] == "failed":
            return False

        # Degenerate retry check:
        # If critique_type requires reasoning fields and they are absent,
        # retrying is pointless — critique will be empty, next attempt
        # will have no useful feedback.
        # Mirrors retry_v2.py _generate_critique lines 244-251.
        if self.critique_type in ("strict", "moderate", "aggressive",
                                   "reasoning_only", "adaptive"):
            parsed = attempt["parsed_generation"]
            full_json = parsed.full_json if parsed else {}
            root_cause = full_json.get("root_cause", "") if full_json else ""
            fix_strategy = full_json.get("fix_strategy", "") if full_json else ""
            if not root_cause or not fix_strategy:
                return False

        return True
```

### policy.generate_critique()

```python
    def generate_critique(
        self,
        attempt: AttemptState,
        call_model_fn: Callable,
    ) -> str:
        """Generate critique text from previous attempt.

        SIDE EFFECT: may call LLM via call_model_fn.
        Returns empty string if no critique applicable.

        call_model_fn signature: (prompt: str, model: str) -> str
        Injected by run_state_machine to avoid config dependency.
        """
        if self.critique_type == "none":
            return ""

        if self.critique_type == "bare_retry":
            return ""

        if self.critique_type == "test_feedback":
            return ""  # test_feedback is in build_next_input, not critique_text

        # Extract reasoning fields from previous attempt
        parsed = attempt["parsed_generation"]
        full_json = parsed.full_json if parsed else {}
        root_cause = full_json.get("root_cause", "") if full_json else ""
        fix_strategy = full_json.get("fix_strategy", "") if full_json else ""
        code = attempt["reconstructed_code"]
        code_commitments = full_json.get("code_commitments", []) if full_json else []
        commitments_str = (
            "; ".join(code_commitments) if isinstance(code_commitments, list)
            else str(code_commitments or "")
        )

        # --- Adaptive mode: classifier hint via critique_mismatch_v2 template ---
        # Mirrors retry_v2.py lines 678-694
        if self.critique_type == "adaptive":
            if root_cause and fix_strategy and code:
                crit_vars = {
                    "root_cause": root_cause,
                    "fix_strategy": fix_strategy,
                    "code": code,
                    "task": self.task,
                }
                prompt = compile_prompt(("critique_mismatch_v2",), crit_vars)
                raw = call_model_fn(prompt, self.evaluator_model)
                text = raw.strip()
                if text and "NO MISMATCH" not in text:
                    return f"\n=== Reasoning-Code Mismatch ===\n{text}"
            return ""

        # --- Critique variants: strict, moderate, aggressive, reasoning_only ---
        # Mirrors retry_v2.py _generate_critique lines 225-301

        # Skip if missing required fields
        if self.critique_type == "reasoning_only":
            if not root_cause or not fix_strategy:
                return ""
        else:
            if not root_cause or not fix_strategy or not code:
                return ""

        # Map to template component
        is_v3 = bool(commitments_str)
        template_map = {
            "strict":         "critique_strict_v3" if is_v3 else "critique_strict",
            "moderate":       "critique_moderate",
            "aggressive":     "critique_aggressive",
            "reasoning_only": "critique_reasoning_only_v3" if is_v3 else "critique_reasoning_only",
        }
        component = template_map.get(self.critique_type)
        if not component:
            return ""

        crit_vars = {"root_cause": root_cause, "fix_strategy": fix_strategy}
        if commitments_str:
            crit_vars["code_commitments"] = commitments_str
        if self.critique_type != "reasoning_only":
            crit_vars["code"] = code

        prompt = compile_prompt((component,), crit_vars)
        raw = call_model_fn(prompt, self.evaluator_model)
        text = raw.strip()

        # Filter no-mismatch signals
        if not text:
            return ""
        if "NO_MISMATCH" in text or "NO MISMATCH" in text:
            return ""
        if "NO_WEAKNESS" in text or "NO WEAKNESS" in text:
            return ""

        # Truncate to one sentence (matches retry_v2.py:296)
        text, _ = truncate_to_one_sentence(text)
        return text
```

### policy.build_next_input()

```python
    def build_next_input(
        self,
        previous_attempt: AttemptState,
        critique_text: str,
        case: dict,
        condition: str,
        model: str,
        config: Any,
    ) -> dict:
        """Build the input dict for the next DAG invocation.

        Config is passed explicitly by run_state_machine.
        Does NOT read config from previous_attempt.

        Returns DAGInput with retry_context populated.
        """
        # Build retry_context — the ONLY channel for cross-attempt data
        retry_ctx = {
            "attempt_index": previous_attempt.get("_attempt_index", 0) + 1,
            "prev_raw": previous_attempt["raw_response"],
            "prev_code": previous_attempt["reconstructed_code"],
            "test_feedback": "",
            "critique_text": critique_text,
            "depth_hint": None,
            "classifier_hint": "",
        }

        # Test feedback from execution reasons
        reasons = previous_attempt["execution_result"].get("reasons", [])
        retry_ctx["test_feedback"] = (
            "\n".join(reasons) if reasons else "Tests failed."
        )

        # Depth hint (PURE — from spec oracle result, overrides critique_text)
        # Mirrors retry_v2.py lines 707-715
        if self.depth_hint_level:
            spec = previous_attempt.get("spec_oracle_result")
            if spec:
                from core.evaluation.depth_hints import generate_depth_hint
                hint = generate_depth_hint(case, spec, self.depth_hint_level)
                if hint:
                    retry_ctx["depth_hint"] = hint

        # For adaptive mode, critique_text already contains the classifier hint
        # No additional processing needed

        # Assemble full DAG input — config from controller, NOT from attempt
        return {
            "case": case,
            "condition": condition,
            "model": model,
            "config": config,
            "retry_context": retry_ctx,
        }
```

---

## 4. run_state_machine

```python
def run_state_machine(
    case: dict,
    model: str,
    condition: str,
    config: Any,
    graph: Any,  # GraphRunner instance
) -> RunResult:

    # ── INIT ──
    policy = resolve_condition_policy(condition, config, case)
    trajectory: list[AttemptState] = []

    # Bind a call_model function for critique generation.
    # Isolates the LLM side effect into a callable the policy can use.
    # No global state — closure captures nothing mutable.
    def call_model_fn(prompt: str, evaluator_model: str) -> str:
        from core.pipeline.llm import call_model
        result = call_model(prompt, model=evaluator_model, raw=True)
        return result.response

    # First attempt: fresh generation, no retry_context
    current_input: dict = {
        "case": case,
        "condition": condition,
        "model": model,
        "config": config,
        "retry_context": None,
    }

    for attempt_index in range(policy.max_attempts):

        # ── RUN_ATTEMPT ──
        attempt = run_attempt(current_input, graph)
        attempt["_attempt_index"] = attempt_index
        trajectory.append(attempt)

        # ── DECISION ──
        if not policy.should_continue(attempt, attempt_index):
            break

        # ── CRITIQUE ──
        critique_text = policy.generate_critique(attempt, call_model_fn)
        current_input = policy.build_next_input(
            previous_attempt=attempt,
            critique_text=critique_text,
            case=case,
            condition=condition,
            model=model,
            config=config,
        )

    # ── DONE ──
    final = select_best(trajectory)

    return RunResult(
        case_id=case["id"],
        condition=condition,
        trajectory=trajectory,
        final=final,
    )
```

The state machine contains zero critique-specific logic. All behavioral variation
is in the policy. The loop body is: RUN → DECIDE → (CRITIQUE via policy →
build input via policy) → RUN.

---

## 5. run_attempt

```python
def run_attempt(
    input_state: dict,
    graph: Any,
) -> AttemptState:
    """Execute one DAG pass. No retry logic. No trajectory access."""

    raw_output = graph.invoke(input_state)

    return AttemptState(
        case=raw_output["case"],
        condition=raw_output["condition"],
        model=raw_output["model"],
        prompt=raw_output["prompt"],
        prompt_meta=raw_output["prompt_meta"],
        raw_response=raw_output["raw_response"],
        parsed_generation=raw_output["parsed_generation"],
        routing=raw_output["routing"],
        parse_mode=raw_output["parse_mode"],
        normalized_reasoning=raw_output["normalized_reasoning"],
        reconstructed_code=raw_output["reconstructed_code"],
        artifact_id=raw_output["artifact_id"],
        classifier_summary=raw_output["classifier_summary"],
        oracle_summary=raw_output["oracle_summary"],
        ast_result=raw_output["ast_result"],
        execution_result=raw_output["execution_result"],
        passed=raw_output["passed"],
        spec_oracle_result=raw_output.get("spec_oracle_result"),
        signals=raw_output["signals"],
        disagreement=raw_output["disagreement"],
        evaluation=raw_output["evaluation"],
    )
```

---

## 6. select_best

```python
def select_best(trajectory: list[AttemptState]) -> AttemptState:
    """Return first passing attempt, or last attempt if none pass.
    Mirrors retry_v2.py select_best_attempt()."""
    for attempt in trajectory:
        if attempt["passed"]:
            return attempt
    return trajectory[-1]
```

---

## 7. resolve_condition_policy

```python
def resolve_condition_policy(
    condition: str,
    config: Any,
    case: dict,
) -> ConditionPolicy:

    cond_config = config.conditions[condition]
    retry_config = cond_config.retry

    # Determine critique type from condition name
    # Mirrors retry_v2.py lines 572-575 + _resolve_critique_variant lines 195-207
    if "bare_retry" in condition:
        critique_type = "bare_retry"
    elif "adaptive" in condition:
        critique_type = "adaptive"
    elif "no_contract" in condition:
        critique_type = "test_feedback"
    elif "reasoning_only" in condition:
        critique_type = "reasoning_only"
    elif "critique_strict" in condition:
        critique_type = "strict"
    elif "critique_moderate" in condition:
        critique_type = "moderate"
    elif "critique_aggressive" in condition:
        critique_type = "aggressive"
    elif "leg_critique" in condition:
        critique_type = "moderate"  # legacy default
    else:
        critique_type = "none"

    depth_hint_level = getattr(config.evaluation, "depth_hint_level", None)

    return ConditionPolicy(
        name=condition,
        max_attempts=retry_config.max_attempts,
        stop_on_pass=True,
        critique_type=critique_type,
        depth_hint_level=depth_hint_level,
        evaluator_model=config.models.evaluator.name,
        task=case["task"],
        schema_line=build_schema_line(case["logical_file_keys"]),
    )
```

---

## 8. PromptBuildNode Input Contract

PromptBuildNode reads from the DAG input state. Its input schema is:

```python
{
    "case": dict,
    "condition": str,
    "model": str,
    "config": ExperimentConfig,
    "retry_context": RetryContext | None
}
```

Where RetryContext is:

```python
{
    "attempt_index": int,           # >= 1
    "prev_raw": str,                # previous attempt's raw LLM response
    "prev_code": str,               # previous attempt's reconstructed code
    "test_feedback": str,           # joined exec failure reasons
    "critique_text": str,           # LLM-generated mismatch critique (may be "")
    "depth_hint": str | None,       # static depth hint (overrides critique_text)
    "classifier_hint": str,         # adaptive mode classifier hint (may be "")
}
```

### PromptBuildNode Logic

```python
def execute(self, state: dict) -> dict:
    case = state["case"]
    condition = state["condition"]
    config = state["config"]
    retry_ctx = state.get("retry_context")

    task = case["task"]
    code_block = format_code_files(case["logical_file_keys"])
    file_keys_example = build_file_keys_example(case["logical_file_keys"])
    schema_line = build_schema_line(case["logical_file_keys"])

    if retry_ctx is None:
        # ── ATTEMPT 0: fresh generation prompt ──
        prompt = compile_prompt(
            ("task_and_code", "output_instruction_v4"),
            {"task": task, "code_files_block": code_block,
             "file_keys_example": file_keys_example,
             "schema_line": schema_line},
        )

    else:
        # ── ATTEMPT 1+: retry prompt with context ──
        # Read ONLY from retry_context, not ad-hoc fields

        # Priority: depth_hint > critique_text > empty
        effective_critique = ""
        if retry_ctx.get("depth_hint"):
            effective_critique = retry_ctx["depth_hint"]
        elif retry_ctx.get("critique_text"):
            effective_critique = retry_ctx["critique_text"]

        # Determine which retry template to use
        # Mirrors _build_retry_prompt_for_attempt in retry_v2.py:320-349
        if "bare_retry" in condition:
            base = compile_prompt(
                ("task_and_code", "output_instruction_v4"),
                {"task": task, "code_files_block": code_block,
                 "file_keys_example": file_keys_example,
                 "schema_line": schema_line},
            )
            prompt = (
                f"Your previous response:\n{retry_ctx['prev_raw']}\n\n"
                + base
            )

        elif effective_critique or "critique" in condition:
            prompt = compile_prompt(
                ("critique_retry",),
                {"prev_raw": retry_ctx["prev_raw"],
                 "mismatch_critique": effective_critique,
                 "schema_line": schema_line},
            )

        elif "no_contract" in condition or "adaptive" in condition:
            prompt = compile_prompt(
                ("test_feedback_retry",),
                {"task": task, "code_files_block": code_block,
                 "prev_code": retry_ctx["prev_code"],
                 "test_feedback": retry_ctx["test_feedback"],
                 "schema_line": schema_line,
                 "classifier_hint": retry_ctx.get("classifier_hint", "")},
            )

        else:
            # Fallback: critique_retry with empty critique
            prompt = compile_prompt(
                ("critique_retry",),
                {"prev_raw": retry_ctx["prev_raw"],
                 "mismatch_critique": "",
                 "schema_line": schema_line},
            )

    prompt_meta = build_prompt_meta(prompt, config)
    return {"prompt": prompt, "prompt_meta": prompt_meta}
```

PromptBuildNode reads `retry_context` as a single structured field. It does NOT
read attempt_index, prev_raw, or critique_text as ad-hoc top-level keys. If
`retry_context is None`, it builds a fresh prompt. If `retry_context` is present,
it reads only the fields within that struct.

---

## 9. DATA FLOW ACROSS ATTEMPTS

### Attempt 0 (fresh generation)

```
current_input = {case, condition, model, config, retry_context: None}
       │
       ▼
   DAG executes all 14 nodes
   PromptBuildNode sees retry_context=None → fresh prompt
       │
       ▼
   AttemptState populated with all fields
       │
       ▼
   trajectory = [attempt_0]
       │
       ▼
   DECISION: policy.should_continue(attempt_0, 0)
   → attempt_0.passed == False
   → attempt_index 0 < max_attempts - 1
   → parse_mode != "failed"
   → reasoning fields present (degenerate check passes)
   → returns True → continue
```

### CRITIQUE (between attempt 0 and attempt 1)

```
   policy.generate_critique(attempt_0, call_model_fn)
       │
       ├── Reads from attempt_0:
       │     root_cause = attempt_0.parsed_generation.full_json["root_cause"]
       │     fix_strategy = attempt_0.parsed_generation.full_json["fix_strategy"]
       │     code = attempt_0.reconstructed_code
       │     code_commitments = attempt_0.parsed_generation.full_json["code_commitments"]
       │
       ├── For critique_type="strict":
       │     Compiles critique_strict.j2 with {root_cause, fix_strategy, code}
       │     Calls evaluator LLM
       │     Returns one-sentence mismatch (or "" if NO_MISMATCH)
       │
       └── For critique_type="adaptive":
             Compiles critique_mismatch_v2.j2 with {root_cause, fix_strategy, code, task}
             Calls evaluator LLM
             Returns classifier hint string (or "")

   policy.build_next_input(
       previous_attempt=attempt_0,
       critique_text="The stated fix targets resolver.py but...",
       case=case,           ← from run_state_machine locals, NOT from attempt
       condition=condition, ← from run_state_machine locals, NOT from attempt
       model=model,         ← from run_state_machine locals, NOT from attempt
       config=config,       ← from run_state_machine locals, NOT from attempt
   )
       │
       └── Returns:
           {
               "case": case,
               "condition": condition,
               "model": model,
               "config": config,
               "retry_context": {
                   "attempt_index": 1,
                   "prev_raw": attempt_0["raw_response"],
                   "prev_code": attempt_0["reconstructed_code"],
                   "test_feedback": "INVARIANT_FAILURE: ...",
                   "critique_text": "The stated fix targets resolver.py but...",
                   "depth_hint": "Trace the data flow backward..." | None,
                   "classifier_hint": "",
               }
           }
```

### Attempt 1 (retry with critique)

```
current_input = {case, condition, model, config, retry_context: {...}}
       │
       ▼
   DAG executes all 14 nodes
   PromptBuildNode sees retry_context is not None:
       → reads retry_context.depth_hint (if present, overrides critique_text)
       → reads retry_context.critique_text
       → builds critique_retry.j2 with prev_raw and effective critique
       │
       ▼
   AttemptState populated with all fields (independent evaluation)
       │
       ▼
   trajectory = [attempt_0, attempt_1]
       │
       ▼
   DECISION: policy.should_continue(attempt_1, 1)
```

---

## 10. EXPLICIT ATTEMPT BOUNDARY DEFINITION

### What crosses the attempt boundary (exhaustive, closed list)

| Field | Source in AttemptState | Destination in RetryContext | Used by |
|-------|----------------------|---------------------------|---------|
| prev_raw | `attempt["raw_response"]` | `retry_context["prev_raw"]` | critique_retry.j2: `{{ prev_raw }}` |
| prev_code | `attempt["reconstructed_code"]` | `retry_context["prev_code"]` | test_feedback_retry.j2: `{{ prev_code }}` |
| test_feedback | `attempt["execution_result"]["reasons"]` | `retry_context["test_feedback"]` | test_feedback_retry.j2: `{{ test_feedback }}` |
| critique_text | `policy.generate_critique()` output | `retry_context["critique_text"]` | critique_retry.j2: `{{ mismatch_critique }}` |
| depth_hint | `generate_depth_hint(case, attempt["spec_oracle_result"], level)` | `retry_context["depth_hint"]` | Overrides critique_text in PromptBuildNode |
| classifier_hint | `policy.generate_critique()` output (adaptive) | `retry_context["classifier_hint"]` | test_feedback_retry.j2: `{{ classifier_hint }}` |

### What does NOT cross the attempt boundary (explicit exclusions)

| Field | Reason |
|-------|--------|
| classifier_summary | Each attempt runs its own classifier independently |
| oracle_summary | Each attempt runs its own oracle independently |
| evaluation | Each attempt is independently evaluated |
| signals | Derived per-attempt, not forwarded |
| disagreement | Derived per-attempt, not forwarded |
| ast_result | Per-attempt structural check, not forwarded |
| spec_oracle_result | Read ONLY by build_next_input to derive depth_hint string. The raw dict is NOT in retry_context. Only the derived hint string crosses. |
| routing | Per-attempt routing decision, not forwarded |
| artifact_id | Per-attempt hash, not forwarded |
| normalized_reasoning | Per-attempt normalization, not forwarded |
| trajectory | Never visible to any node. Only the state machine controller holds the list. |
| config | NOT read from previous attempt. Passed by run_state_machine from its own locals. |
| prompt | Not forwarded. Each attempt builds its own prompt. |
| prompt_meta | Not forwarded. |

---

## 11. PARALLEL SAFETY

Every instance of `run_state_machine` holds:

- Its own `policy` (constructed at INIT, never shared)
- Its own `trajectory` list (local variable)
- Its own `current_input` dict (local variable)
- Its own `call_model_fn` closure (stateless — calls llm.py which creates
  a fresh API client per call)

No global variables. No shared mutable state. No module-level caches.

Multiple `run_state_machine` invocations run in separate processes (current
orchestrator model) or separate threads without interference.

---

## 12. SEMANTIC EQUIVALENCE TO retry_v2.py

| retry_v2.py behavior | State machine equivalent |
|---|---|
| `k == 0`: fresh prompt via `(task_and_code, output_instruction_v4)` | `retry_context is None` → PromptBuildNode builds fresh prompt |
| `k > 0, use_bare_retry`: prepend prev_raw to fresh prompt | `retry_context.prev_raw` + `"bare_retry" in condition` branch in PromptBuildNode |
| `k > 0, critique_variant`: `_generate_critique()` → `_build_critique_retry_prompt(prev_raw, critique)` | `policy.generate_critique()` → `retry_context.critique_text` → PromptBuildNode renders critique_retry.j2 |
| `k > 0, depth_hint_level`: `generate_depth_hint()` overrides critique | `policy.build_next_input()` sets `retry_context.depth_hint` → PromptBuildNode uses depth_hint over critique_text |
| `k > 0, use_test_feedback`: test_feedback_retry.j2 with prev_code + reasons | `retry_context.test_feedback` + `retry_context.prev_code` → PromptBuildNode renders test_feedback_retry.j2 |
| `k > 0, use_classifier_hint (adaptive)`: LLM call → classifier_hint | `policy.generate_critique()` with critique_type="adaptive" returns classifier hint → stored in retry_context |
| `_generate_critique` skips when `not root_cause or not fix_strategy` | `policy.generate_critique()` returns "" on missing fields |
| Loop aborts when `parse_mode == "failed"` | `policy.should_continue()` returns False |
| Loop aborts when reasoning empty + critique requires it | `policy.should_continue()` returns False (degenerate case) |
| `select_best_attempt()`: first passing or last | `select_best(trajectory)`: identical logic |
| Conditions are independent work items | Each `run_state_machine` is self-contained. No cross-condition data. |
| Critique generates its own attempt 0 | First iteration has `retry_context=None`. Fresh prompt. Independent generation. |
| `max_attempts` from config.conditions[condition].retry | `policy.max_attempts` resolved from same config path |
| `max_total_seconds` timeout | Not yet modeled. Future: add wall-clock check at top of loop in run_state_machine. |

### Unmodeled behavior (explicit gaps)

| retry_v2.py feature | Status | Notes |
|---|---|---|
| `max_total_seconds` wall-clock timeout | NOT MODELED | Add elapsed time check at top of loop. Low complexity. |
| Oracle sampling strategy (`FIRST_K`, `RANDOM_SAMPLE`) | NOT MODELED | Currently all attempts run oracle. To add: pass attempt_index to DAG input, OracleNode checks sampling policy. |
| Event ID chaining (`last_parent_eid`) | NOT MODELED | Effect wrapper handles call logging independently. Parent-child event tracing requires logger integration (Phase 5+). |
| Trajectory entry backward-compat format | NOT MODELED | `_trajectory_entry_from_state()` in retry_v2.py builds a specific dict format. RunResult.trajectory uses AttemptState directly. Conversion to legacy format is a separate concern. |
