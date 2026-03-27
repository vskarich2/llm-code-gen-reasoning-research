"""Core nudge operators — generic reasoning interventions.

Each operator targets a failure CLASS, not a specific case.
Diagnostic operators guide reasoning. Guardrail operators constrain actions.
"""

from nudges.operators import NudgeOperator, register

# ═══════════════════════════════════════════════════════════════
# DIAGNOSTIC OPERATORS (reasoning guidance)
# ═══════════════════════════════════════════════════════════════


def _dependency_check_diagnostic(base: str) -> str:
    return base + """

Before finalizing your answer, perform a dependency reasoning_evaluator_audit:

1. For every function you plan to modify, list ALL its side effects
   (writes to shared state, caches, databases, module-level dicts).
2. For each side effect, trace which other functions READ that state —
   search ALL files, not just the one you are editing.
3. If two functions have similar names, check whether they have
   IDENTICAL semantics. Similar names often hide different behavior
   (e.g., always-write vs write-if-absent, overwrite vs merge).
4. For each change you propose, ask: "does any downstream reader
   still get the same value at the same time?"

Only make changes that preserve all cross-file behavioral contracts.
Explain which dependencies you traced and what you preserved.
"""


register(
    NudgeOperator(
        name="DEPENDENCY_CHECK",
        kind="diagnostic",
        description="Forces tracing of downstream consumers and side-effect dependencies.",
        build_prompt=_dependency_check_diagnostic,
    )
)


def _invariant_guard_diagnostic(base: str) -> str:
    return base + """

Before finalizing your answer, reason about failure invariants:

1. Identify the key correctness invariant (e.g., conservation of value,
   consistency of paired operations, atomicity of multi-step mutations).
2. Identify the FAILURE WINDOW: the point between two related operations
   where an exception would leave the system in an inconsistent state.
3. Distinguish between OBSERVABILITY helpers (logging, auditing, alerting,
   telemetry) and CORRECTNESS mechanisms (rollback, atomic assignment,
   compensation). Only correctness mechanisms fix invariant violations.
4. Ask: "if an exception occurs at every possible point in my refactored
   code, does the invariant still hold?"

Do not confuse visibility with consistency.
Explain what invariant you are protecting and how.
"""


register(
    NudgeOperator(
        name="INVARIANT_GUARD",
        kind="diagnostic",
        description="Forces reasoning about invariants, failure windows, and atomicity.",
        build_prompt=_invariant_guard_diagnostic,
    )
)


def _temporal_robustness_diagnostic(base: str) -> str:
    return base + """

Before finalizing your answer, trace the data flow step by step:

1. Identify which values are computed from ORIGINAL (pre-transform) data
   and which are computed from TRANSFORMED (post-transform) data.
   These are semantically different — do not conflate them.
2. For each consumer of pipeline output, check: does it expect raw
   values or processed values? What breaks if you swap them?
3. If two functions compute similar statistics (averages, maximums),
   check whether they use the same keys, the same rounding, and the
   same input data. Similar output shape does NOT mean interchangeable.
4. For any reordering you propose, verify: does every intermediate
   variable still hold the same value as before?

Preserve the semantic contract between pipeline stages and their consumers.
Explain which ordering constraints you identified.
"""


register(
    NudgeOperator(
        name="TEMPORAL_ROBUSTNESS",
        kind="diagnostic",
        description="Forces tracing of data flow ordering and semantic stage boundaries.",
        build_prompt=_temporal_robustness_diagnostic,
    )
)


def _state_lifecycle_diagnostic(base: str) -> str:
    return base + """

Before finalizing your answer, trace the state lifecycle:

1. Identify all distinct state representations (e.g., raw, pending,
   stable, view, committed). Each may serve a different purpose.
2. For each state transition (staging, committing, freezing, projecting),
   determine what fields change and what flags are set.
3. Trace which downstream selectors/consumers read each representation.
   A selector that checks a flag before reading means that flag is
   load-bearing — removing the step that sets it breaks the selector.
4. Check whether any API function intentionally skips a transition
   (e.g., preview without commit). If so, merging those transitions
   would break that API function.

Do not remove or merge state transitions unless you can prove all
downstream readers still get the same values.
Explain which state distinction you preserved and why.
"""


register(
    NudgeOperator(
        name="STATE_LIFECYCLE",
        kind="diagnostic",
        description="Forces tracing of staged state transitions and selector dependencies.",
        build_prompt=_state_lifecycle_diagnostic,
    )
)


# ═══════════════════════════════════════════════════════════════
# GUARDRAIL OPERATORS (action constraints)
# ═══════════════════════════════════════════════════════════════


def _dependency_check_guardrail(base: str) -> str:
    return base + """

MANDATORY CONSTRAINTS — you must follow ALL of these:

1. You may NOT remove or replace any function call that writes to shared
   state unless you can prove that every downstream reader still receives
   the SAME data at the SAME time.

2. You may NOT substitute one write function for a similarly-named one
   unless you have verified they have IDENTICAL semantics (same write
   policy, same overwrite behavior, same key format).

3. You may NOT remove cache/state write operations to "reduce coupling"
   unless you provide an equivalent write path that preserves all
   downstream read contracts.

4. For ANY change to a write path, you MUST name every function that
   reads from the same shared state and confirm it still works.

If you cannot prove semantic equivalence, keep the original code.
"""


register(
    NudgeOperator(
        name="DEPENDENCY_CHECK_GUARDRAIL",
        kind="guardrail",
        description="Constrains actions: forbids removing write-path operations without equivalence proof.",
        build_prompt=_dependency_check_guardrail,
    )
)


def _invariant_guard_guardrail(base: str) -> str:
    return base + """

MANDATORY CONSTRAINTS — you must follow ALL of these:

1. You may NOT separate a debit/decrement from its paired credit/increment
   without adding explicit rollback or atomic assignment.

2. If any operation between the debit and credit can raise an exception,
   the except path MUST restore the original value.

3. You may NOT add retries as a substitute for rollback. A retry that
   fails still leaves the invariant violated.

4. You may NOT rely on logging, auditing, alerting, or telemetry calls
   as correctness mechanisms. They are observability, not consistency.

5. The ONLY acceptable patterns are:
   a) try/except where except restores the debited value
   b) compute both new values first, then assign both atomically
   c) explicit compensation on every exception path

If your refactor does not include rollback or atomic assignment, it is wrong.
"""


register(
    NudgeOperator(
        name="INVARIANT_GUARD_GUARDRAIL",
        kind="guardrail",
        description="Constrains actions: requires rollback/atomicity, forbids observability-only fixes.",
        build_prompt=_invariant_guard_guardrail,
    )
)


def _temporal_robustness_guardrail(base: str) -> str:
    return base + """

MANDATORY CONSTRAINTS — you must follow ALL of these:

1. You may NOT move any statistics computation to run on transformed
   data if it was originally computed on raw data. The output keys
   and values must reflect the original input, not a normalized or
   clipped version.

2. You may NOT replace one metrics function with a similarly-named one
   unless they produce IDENTICAL keys and values. Different key names
   or different rounding means they are NOT interchangeable.

3. You may NOT merge pre-transform and post-transform computations
   into a single pass. They operate on different representations
   and serve different consumers.

4. You may reorder transform steps ONLY IF the final output is
   byte-identical to the original.

If you cannot prove that every consumer still receives the same
semantic values, keep the original pipeline structure.
"""


register(
    NudgeOperator(
        name="TEMPORAL_ROBUSTNESS_GUARDRAIL",
        kind="guardrail",
        description="Constrains actions: forbids reordering stats computation or swapping metrics functions.",
        build_prompt=_temporal_robustness_guardrail,
    )
)


def _state_lifecycle_guardrail(base: str) -> str:
    return base + """

MANDATORY CONSTRAINTS — you must follow ALL of these:

1. You may NOT remove any state transition step (stage, commit,
   freeze, etc.) unless you can prove that every selector and API
   function that reads state still returns the SAME value.

2. You may NOT merge two state transitions into one if ANY caller
   uses them independently (e.g., preview calling stage without commit).

3. You may NOT remove a step that sets a flag (e.g., frozen=True)
   if any downstream selector checks that flag before reading state.

4. You may NOT route selector-facing data through a display/projection
   helper in place of the committed/stable state path.

5. For ANY step you propose to remove, you MUST name every function
   that reads its output and prove they still return the same values.

If you cannot prove equivalence for ALL consumers, keep the original
multi-step sequence.
"""


register(
    NudgeOperator(
        name="STATE_LIFECYCLE_GUARDRAIL",
        kind="guardrail",
        description="Constrains actions: forbids removing state transitions without consumer equivalence proof.",
        build_prompt=_state_lifecycle_guardrail,
    )
)


# ═══════════════════════════════════════════════════════════════
# STRICT GUARDRAIL OPERATORS (hard prohibitions from case metadata)
# ═══════════════════════════════════════════════════════════════


def build_strict_guardrail(base: str, hard_constraints: list[str]) -> str:
    """Build a strict guardrail prompt from case-level hard_constraints."""
    if not hard_constraints:
        return base
    bullets = "\n".join(f"  * {c}" for c in hard_constraints)
    return base + f"""

HARD CONSTRAINTS — your solution MUST obey ALL of the following.
Any violation makes your solution INCORRECT. Do NOT proceed with
a solution that violates any of these:

{bullets}

If your solution violates ANY of these constraints, it is wrong.
You must find an alternative approach that satisfies all of them.
"""


# ═══════════════════════════════════════════════════════════════
# COUNTERFACTUAL SIMULATION OPERATOR
# ═══════════════════════════════════════════════════════════════


def _counterfactual_generic(base: str) -> str:
    return base + """

Before finalizing your solution, you MUST perform this counterfactual check:

1. Pick the most important state transition in the code (e.g., staging,
   committing, writing to shared state, mutating balances).

2. Consider a scenario where:
   - a downstream consumer reads state BETWEEN two of your changes
   - OR an exception occurs midway through your refactored sequence

3. In that scenario, will the consumer see DIFFERENT data than it would
   have seen with the original code?

4. If YES: your solution changes observable behavior — it is INCORRECT.
   You must revert that specific change.

5. If NO for ALL consumers: your solution is valid.

Explicitly reason through at least one concrete scenario before
giving your final answer.
"""


register(
    NudgeOperator(
        name="COUNTERFACTUAL",
        kind="counterfactual",
        description="Forces explicit counterfactual simulation of intermediate-state observers.",
        build_prompt=_counterfactual_generic,
    )
)


# ═══════════════════════════════════════════════════════════════
# REASON-THEN-ACT OPERATOR
# ═══════════════════════════════════════════════════════════════


def _reason_then_act_generic(base: str) -> str:
    return base + """

You MUST complete both steps IN ORDER. Do not skip Step 1.

STEP 1 — REASONING (required before any code)

Answer ALL of the following:

a) What distinct state representations exist in this code?
   (e.g., raw, pending, committed, cached, projected, displayed)

b) For each representation, which functions READ it and which WRITE it?

c) What invariants must hold? (e.g., conservation, ordering, visibility gates)

d) Which of the proposed simplifications would break an invariant or
   change what a reader sees?

STEP 2 — CODE

Based ONLY on your Step 1 analysis, produce the refactored code.
If Step 1 reveals that a simplification is unsafe, do NOT make it.
"""


register(
    NudgeOperator(
        name="REASON_THEN_ACT",
        kind="reason_then_act",
        description="Forces explicit reasoning about state/invariants before code generation.",
        build_prompt=_reason_then_act_generic,
    )
)


# ═══════════════════════════════════════════════════════════════
# SELF-CHECK OPERATOR (post-generation verification)
# ═══════════════════════════════════════════════════════════════


def _self_check_generic(base: str) -> str:
    return base + """

After producing your solution, you MUST perform a verification step
BEFORE outputting your final answer:

1. Re-read your proposed code changes and check:
   - Did you remove or merge any function that has downstream readers
     in OTHER files?
   - Did you change when data becomes visible to other components?
   - Did you break any flag, gate, or guard that a consumer checks?

2. For each function you changed, trace ONE concrete scenario:
   - Call the public API with sample data
   - Walk through your new code step by step
   - Verify the return value is identical to the original

3. If you find ANY inconsistency:
   - Revert that specific change
   - Explain what you reverted and why

4. Only output the FINAL code after completing this check.
   If you cannot verify correctness, keep the original code unchanged.
"""


register(
    NudgeOperator(
        name="SELF_CHECK",
        kind="self_check",
        description="Post-generation verification: forces model to trace a concrete scenario through its own output.",
        build_prompt=_self_check_generic,
    )
)


# ═══════════════════════════════════════════════════════════════
# COUNTERFACTUAL CHECK OPERATOR
# ═══════════════════════════════════════════════════════════════


def _counterfactual_check_generic(base: str) -> str:
    return base + """

Before submitting your solution, you MUST perform a counterfactual failure analysis:

1. Identify at least two realistic ways your implementation could fail:
   a) A runtime scenario where your code produces wrong output
   b) An edge case where an invariant is violated

2. For each failure mode:
   - Describe the concrete input or sequence of calls
   - Explain what goes wrong and why
   - Show how your implementation handles (or fails to handle) it

3. If either failure mode is NOT handled:
   - Fix your implementation before returning it
   - Explain what you changed

Only return code that survives both counterfactual scenarios.
"""


register(
    NudgeOperator(
        name="COUNTERFACTUAL_CHECK",
        kind="counterfactual_check",
        description="Forces model to enumerate concrete failure scenarios before finalizing code.",
        build_prompt=_counterfactual_check_generic,
    )
)


# ═══════════════════════════════════════════════════════════════
# TEST-DRIVEN OPERATOR
# ═══════════════════════════════════════════════════════════════


def _test_driven_generic(base: str) -> str:
    return base + """

Your implementation MUST satisfy the following behavioral requirements:

1. All public functions preserve their input/output contract:
   - Same inputs produce same outputs as the original code
   - Side effects (state mutations, writes) occur in the same order

2. All invariants hold under repeated and concurrent calls:
   - No state is lost between sequential operations
   - No partial updates are visible to downstream consumers

3. Error paths preserve consistency:
   - If an exception occurs mid-operation, system state is not corrupted
   - Partial work is rolled back or never committed

Write your code so that these requirements are testable via simple assertions.
If a requirement cannot be met, keep the original implementation unchanged.
"""


register(
    NudgeOperator(
        name="TEST_DRIVEN",
        kind="test_driven",
        description="Injects testable behavioral invariants the model must satisfy.",
        build_prompt=_test_driven_generic,
    )
)
