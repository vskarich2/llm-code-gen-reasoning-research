# Invariant Test System Overhaul -- Plan v1

**Task type**: FEATURE (new testing architecture)
**Date**: 2026-03-30
**Status**: AWAITING APPROVAL

---

## 1. DIAGNOSIS: Root Causes of Current System Failure

The current `tests_v2/` system has 6 structural root causes that produce unreliable evaluation signals. These are not bugs to patch -- they are architectural deficiencies that require a redesign.

### ROOT CAUSE 1: Tests encode expected outputs, not invariants

Every current test function follows the pattern:
```
call function -> check return value -> pass/fail
```

This is outcome testing, not invariant testing. An invariant is a property that must hold across ALL valid states of the system, not a specific output for a specific input. The tests check "did the output match?" rather than "does the required property hold?"

**Evidence**: `test_wrong_condition.py:test_a` checks `is_rate_limited(5, 5) == True` but never checks `is_rate_limited(4, 5) == False`. The invariant "requests at or above the limit are blocked; requests below are allowed" is not tested. Only one half of the predicate is verified. Result: `def is_rate_limited(c, l): return True` passes.

**Evidence**: `test_partial_rollback.py:test_a` checks `inv.available() == 10` after a failed order. But it never verifies that a successful order DOES reduce inventory. Result: `def place_order(*a): pass` passes.

**Evidence**: `test_temporal_drift.py:test_a` checks `raw_stats["raw_max"] == 80` but never checks that normalization still produces correct output. Result: removing the normalization step entirely passes.

**Structural pattern**: 15 of 28 test families check only one direction of a two-directional invariant (the failure/boundary case without the success case, or vice versa).

### ROOT CAUSE 2: No state transition verification

Tests check final state but never verify:
- What the state was BEFORE the operation
- That the state CHANGED in the expected way (not just that it has the expected final value)
- That intermediate states were valid
- That hidden state (module globals, caches, captured closures) was properly affected

**Evidence**: `test_alias_config.py:test_a` checks `cfg2.get("timeout") == 30` but never checks `cfg1.get("timeout") == 5`. It cannot distinguish "overrides work and don't leak" from "overrides are ignored."

**Evidence**: `test_lazy_init.py:test_a` resets `mod._default_host = "localhost"` (an implementation detail), then calls configure and checks the result. It never verifies the initial state was actually the default, so a model that ignores configure() but starts with the right value would pass.

**Evidence**: `test_invariant_partial_fail.py:test` checks `sender.balance + receiver.balance == 100` after a forced failure. But `sender.balance = 100, receiver.balance = 0` (the INITIAL state, unchanged) satisfies this. The test cannot distinguish "rolled back correctly" from "never started."

### ROOT CAUSE 3: No adversarial coverage

Current tests use a single input, call the function once (or twice), and check one assertion. None of the 28 test families include:
- Repeated calls with accumulation detection
- Input permutations testing commutativity/associativity
- Edge inputs (empty, None, boundary values)
- Cross-call contamination probes
- Anti-hardcoding checks (only `lost_update` and `check_then_act` do this)

**Evidence**: `test_stale_cache.py:test_a` calls add->read->update->read and checks the final read. It never calls update->update->read (multiple updates) or read->read (cache consistency) or add->update->add->read (key reuse).

**Evidence**: `test_mutable_default.py:test_a` calls enqueue twice and checks the second queue has length 1. It never calls enqueue 5 times to detect progressive accumulation. It never calls with empty/None tasks to test boundary behavior.

### ROOT CAUSE 4: Execution model erases cross-file semantics

Both execution paths (concat via `exec_eval.py` and disk-backed via `harness/run_case.py`) flatten all files into a single merged namespace. This means:

- `from cache import cache_get` is never tested -- `cache_get` is already in the flat namespace
- Module-scoped state (`_db = {}` in db.py, `_data = {}` in cache.py) becomes shared globals
- Import-time side effects are not exercised
- A model that dumps everything into one file produces identical test results to one that maintains file boundaries

**Evidence**: `harness/run_case.py:98-148` builds `merged = types.ModuleType("_t3_merged")` and copies all names from all imported modules into it. Name conflicts are logged but the last writer wins.

**Evidence**: `exec_eval.py:33-50` does `exec(compile(code, ...), mod.__dict__)` on concatenated code, creating identical flat-namespace semantics.

**Impact**: 38 of 51 cases are multi-file. Their cross-file invariants (cache invalidation, hidden dependencies, config shadowing) are not actually tested as cross-file interactions.

### ROOT CAUSE 5: No mechanism to detect partial fixes or lucky fixes

The current system has a binary pass/fail signal from execution tests. There is no way to detect:
- A fix that satisfies the tested assertion but violates the stated invariant
- A fix that works for the tested input but fails for other valid inputs
- A fix that works by accident (e.g., removing code that happens to eliminate the symptom without addressing the cause)
- A partial fix that addresses one of two required changes (e.g., commit_gate: restoring commit() but not freeze_view())

**Evidence**: `test_config_shadowing.py:test` checks both timeouts equal 30. The reference fix changes DEFAULTS. But a contingent fix -- changing `run_background_job()` to call `get_config()` instead of `get_defaults()` -- also passes the test. The metadata explicitly calls this out as the "trap" fix, but the test cannot distinguish them.

**Evidence**: `test_feature_flag_drift.py:test` checks `total == 900`. A model that bypasses the flag system entirely and computes `base * qty * 0.9` directly from the parameter would pass. The test cannot distinguish "flag propagated correctly" from "hardcoded the right formula."

### ROOT CAUSE 6: No state isolation enforcement

Tests rely on ad-hoc state reset via direct variable assignment:
```python
if hasattr(mod, "_counter"):
    mod._counter = 0
```

This has three failure modes:
1. Model renames the variable -> reset doesn't happen -> stale state contaminates test
2. Model adds new state variables -> test doesn't know to reset them -> leakage
3. Module-level `exec()` means state from one test persists for the next test using the same module

**Evidence**: `test_effect_order.py` resets `mod._counter`, `mod._snapshots`, `mod._events` by direct assignment. If a model renames `_counter` to `_total`, the reset is silently skipped. The test then runs against whatever value `_total` had after module initialization.

---

## 2. TARGET TEST ARCHITECTURE

### 2.1 Components

```
cases_v2.json
    |
    v
INVARIANT_SPECS/                    <-- NEW: formal invariant definitions
    invariant_{family}.yaml         one per family (28 files)
    |
    v
TEST_GENERATOR                      <-- NEW: compiles specs into test functions
    |
    +-- normal_tests                (happy path, basic invariant)
    +-- adversarial_tests           (boundary, contamination, degenerate)
    +-- stateful_tests              (multi-call, accumulation, lifecycle)
    +-- cross_boundary_tests        (import resolution, module scoping)
    +-- anti_cheat_tests            (varying inputs, anti-hardcoding)
    |
    v
tests_v2/
    test_{family}.py                GENERATED or HAND-WRITTEN from specs
    |
    v
TEST_HARNESS                        <-- REDESIGNED
    |
    +-- IsolationEngine             (fresh module per test, no shared state)
    +-- StateTracker                (captures before/after state snapshots)
    +-- InvariantRunner             (executes tests, collects structured verdicts)
    +-- CoverageAnalyzer            (measures invariant/failure-mode coverage)
    |
    v
STRUCTURED_VERDICT                  <-- NEW: replaces (bool, list[str])
    {
      "invariant_id": "alias_config.no_mutation",
      "satisfied": false,
      "phase_results": [...],       (per-phase pass/fail with evidence)
      "false_positive_checks": [...],
      "state_snapshots": {...},
      "anti_cheat_passed": true/false
    }
```

### 2.2 Responsibilities

| Component | Current Owner | Target Owner | Change |
|-----------|--------------|-------------|--------|
| Invariant definition | Implicit in test code | `INVARIANT_SPECS/*.yaml` | Extract and formalize |
| Test logic | `tests_v2/test_*.py` | Same files, rewritten | Restructure around phases |
| State reset | Ad-hoc `hasattr` checks | `IsolationEngine` | Centralize, make mandatory |
| Module loading | `exec()` / `importlib` | `IsolationEngine` | Fresh module per test invocation |
| Verdict format | `(bool, list[str])` | `StructuredVerdict` | Rich structured signal |
| Coverage tracking | None | `CoverageAnalyzer` | New capability |
| Anti-cheat | 2 of 28 families | Every family | Systematic |

### 2.3 Data Flow

```
1. Load case from cases_v2.json
2. Load invariant spec from INVARIANT_SPECS/{family}.yaml
3. IsolationEngine creates FRESH module from model code
4. StateTracker snapshots initial state
5. InvariantRunner executes test phases in order:
   Phase 0: PRECONDITION -- verify initial state matches expectations
   Phase 1: HAPPY_PATH -- verify the function works correctly for normal inputs
   Phase 2: INVARIANT -- verify the specific invariant holds
   Phase 3: ADVERSARIAL -- boundary inputs, repeated calls, contamination probes
   Phase 4: ANTI_CHEAT -- varying inputs to detect hardcoded outputs
   Phase 5: NEGATIVE -- verify that known-wrong implementations FAIL
6. StateTracker snapshots final state, computes diff
7. InvariantRunner assembles StructuredVerdict
8. CoverageAnalyzer records which invariant dimensions were exercised
```

---

## 3. INVARIANT SPEC SYSTEM

### 3.1 Schema

Each family gets one YAML file: `INVARIANT_SPECS/invariant_{family}.yaml`

```yaml
family: alias_config
variants: [a, b, c]

invariants:
  - id: alias_config.no_global_mutation
    type: state_preservation
    description: "create_config() must not mutate the module-level DEFAULTS dict"
    formal: "forall calls c to create_config(overrides): DEFAULTS_after(c) == DEFAULTS_before(c)"
    failure_class: shared_reference_mutation
    applies_to: [a, b, c]

  - id: alias_config.call_independence
    type: output_isolation
    description: "Two successive calls to create_config must return independent objects"
    formal: "forall c1,c2: create_config(o1) is not create_config(o2) AND mutating c1 does not affect c2"
    failure_class: shared_reference_mutation
    applies_to: [a, b, c]

  - id: alias_config.override_application
    type: functional_correctness
    description: "Overrides passed to create_config must appear in the returned dict"
    formal: "forall k,v in overrides: create_config({k: v})[k] == v"
    failure_class: functional_regression
    applies_to: [a, b, c]

state_contract:
  module_state:
    - name: DEFAULTS
      type: dict
      reset_strategy: "call reset_defaults() if available, else restore to {timeout: 30, retries: 3, debug: False}"
  hidden_state:
    - name: _cached_settings
      type: "Optional[dict]"
      reset_strategy: "set to None"
      applies_to: [b]

test_phases:
  precondition:
    - "DEFAULTS exists and equals {timeout: 30, retries: 3, debug: False}"
  happy_path:
    - "create_config({timeout: 5}) returns dict with timeout=5"
    - "create_config() returns dict with timeout=30"
  invariant:
    - "After create_config({timeout: 5}), DEFAULTS['timeout'] still == 30"
    - "create_config({x: 1}) is not create_config({y: 2}) (identity check)"
    - "mutating cfg1 = create_config({}) does not affect cfg2 = create_config({})"
  adversarial:
    - "Call create_config 10 times with different overrides; DEFAULTS unchanged after each"
    - "create_config({}) with empty overrides returns fresh copy"
    - "create_config with nested dict overrides does not share nested references"
  anti_cheat:
    - "create_config({timeout: 42}) returns {timeout: 42, ...} (non-default value)"
    - "create_config({new_key: True}) returns dict containing new_key"
  negative:
    - "Buggy code (DEFAULTS reference returned directly) MUST fail no_global_mutation"

false_positive_patterns:
  - pattern: "always_return_hardcoded_defaults"
    description: "create_config ignores overrides, always returns {timeout: 30, ...}"
    detected_by: "happy_path phase (override not applied)"
  - pattern: "new_dict_per_call_but_ignores_overrides"
    description: "Returns fresh dict each time but never applies overrides"
    detected_by: "happy_path phase (override not applied)"

trap_fix_detection:
  - trap: "Copy DEFAULTS but still mutate the copy returned to caller"
    invariant_violated: "alias_config.call_independence"
```

### 3.2 How Invariants Compile Into Tests

Each invariant in the spec produces one or more test assertions within its phase. The mapping is explicit and traceable:

```
invariant_id                    ->  phase      ->  assertion
alias_config.no_global_mutation ->  invariant  ->  assert DEFAULTS == original after call
alias_config.call_independence  ->  invariant  ->  assert cfg1 is not cfg2
alias_config.call_independence  ->  adversarial -> mutate cfg1, assert cfg2 unchanged
alias_config.override_application -> happy_path -> assert cfg1["timeout"] == 5
```

Every test assertion MUST reference back to an `invariant_id`. An assertion without an invariant reference is a specification defect.

### 3.3 Invariant Types

| Type | Meaning | Test Strategy |
|------|---------|---------------|
| `state_preservation` | Some state must not change | Snapshot before, snapshot after, diff must be empty |
| `output_isolation` | Outputs must be independent objects | Identity check, mutation probe |
| `functional_correctness` | Function must produce correct output | Input-output pairs with varying inputs |
| `state_transition` | State must change in specific way | Before != after, after matches expectation |
| `temporal_ordering` | Operations must happen in specific order | Log/trace inspection, interleaving |
| `conservation` | Quantity must be conserved | Sum/count before == sum/count after |
| `atomicity` | Operation must be all-or-nothing | Interrupt at each step, verify rollback |
| `completeness` | All inputs must produce outputs | Enumerate inputs, verify no silent drops |
| `idempotence` | Repeated calls must produce same result | Call N times, compare results |
| `boundary` | Behavior at limits must be correct | Test at exact boundary, +/- 1 |

---

## 4. TEST GENERATION STRATEGY

### 4.1 Normal Tests (Happy Path)

For every case, the test must verify:
1. The primary function exists and is callable
2. For well-formed input, the function produces correct output
3. The output has the expected structure (all required keys present)
4. For the specific scenario the case describes, the correct result is produced

**Concrete example for `partial_rollback_c`:**
```
Phase 1 (happy_path):
  - add_product("W1", 20) -> product exists
  - set_gateway_fail(False) -> gateway will succeed
  - place_order("W1", 5, 10.0) -> completes without exception
  - available("W1") == 15 (20 - 5)
  - get_audit_log() has exactly 1 entry with correct details
```

This is MISSING from the current test. The current test only checks the failure path.

### 4.2 Adversarial Tests

For every case, systematically generate tests from the following dimensions:

**4.2.1 Repeated calls (accumulation detection)**
- Call the primary function N times (N >= 3) with reset between groups
- Verify no cross-group state leakage
- Verify within-group behavior is correct on each call

**4.2.2 Boundary inputs**
- Empty collections: `[]`, `{}`, `set()`, `""`
- None where a value is expected
- Maximum-size inputs (if applicable)
- Exact boundary values (e.g., `count == limit` for rate limiters)

**4.2.3 Cross-call contamination**
- Call with input A, then call with input B, verify B's result is not contaminated by A
- For cache-related cases: populate cache, update underlying data, verify cache reflects update

**4.2.4 Ordering permutations**
- For multi-step operations: permute step order and verify invariant holds or correct error raised
- For temporal cases: reverse the expected order and verify the system handles it

**Concrete example for `wrong_condition_a`:**
```
Phase 3 (adversarial):
  - is_rate_limited(0, 5) == False   (no requests yet)
  - is_rate_limited(4, 5) == False   (under limit)
  - is_rate_limited(5, 5) == True    (at limit - the bug)
  - is_rate_limited(6, 5) == True    (over limit)
  - is_rate_limited(0, 0) == True    (zero limit)
  - is_rate_limited(5, 5) == True    (repeat boundary check)
```

### 4.3 Stateful Tests

For every stateful case (32 of 51 cases have `statefulness: stateful`):

**4.3.1 Lifecycle test**
```
reset -> verify clean state -> operate -> verify dirty state -> reset -> verify clean again
```

**4.3.2 Multi-call accumulation**
```
reset -> call(input_1) -> verify -> call(input_2) -> verify -> call(input_3) -> verify
```
At each step, check both the immediate result AND all accumulated state.

**4.3.3 Reset completeness**
```
operate to dirty state -> reset -> inspect ALL known state variables -> all must be at initial values
```

**Concrete example for `overdetermination`:**
```
Phase stateful:
  - reset()
  - update_product("P1", lambda: 10) -> serve_request("P1")["value"] == 10
  - update_product("P1", lambda: 20) -> serve_request("P1")["value"] == 20
  - update_product("P1", lambda: 30) -> serve_request("P1")["value"] == 30
  - update_product("P2", lambda: 99) -> serve_request("P2")["value"] == 99
  - serve_request("P1")["value"] == 30  (P2 update didn't affect P1)
  - reset() -> serve_request("P1")["value"] == None  (clean after reset)
```

### 4.4 Cross-Boundary Tests

For every multi-file case (38 cases), test that:

1. **Import resolution**: Functions from file A can call functions from file B
2. **Module state scoping**: `_db` in `db.py` and `_cache` in `cache.py` are independent namespaces
3. **Write-through propagation**: Changes in one module's state are visible when read through another module's API

**This requires a new execution mode** (see Section 5). The current merged namespace cannot test these properties.

**Concrete example for `stale_cache_c`:**
```
Phase cross_boundary:
  - Verify: catalog.update_product writes to db._tables (not cache)
  - Verify: catalog.get_product reads from cache._data first, then db._tables
  - Verify: after update, cache._data["p1"] is invalidated (key removed or value updated)
  - Verify: local cache (_local) is ALSO invalidated (the actual bug)
```

### 4.5 Anti-Cheat Tests

For every case, include at least one test with non-standard input values that cannot be predicted by hardcoding:

**Strategy**: Run the same logical test with 2-3 different input sets. If the function works correctly, all must pass. If the function hardcodes the expected output for the standard test input, the non-standard inputs will fail.

**Concrete example for `temporal_drift_a`:**
```
Phase anti_cheat:
  - Standard:  pipeline([10, 50, 30, 80, 20]) -> raw_max=80, raw_min=10
  - Variant 1: pipeline([100, 200, 300])       -> raw_max=300, raw_min=100
  - Variant 2: pipeline([7])                    -> raw_max=7, raw_min=7
  - Variant 3: pipeline([1, 1, 1, 1])           -> raw_max=1, raw_sum=4
```

---

## 5. TEST HARNESS DESIGN

### 5.1 IsolationEngine

**Purpose**: Guarantee that each test invocation runs against a completely fresh module with zero state leakage.

**Design**:

```
class IsolationEngine:
    def create_execution_context(case, model_code) -> ExecutionContext:
        """
        1. Create a temporary directory
        2. Write each code file to its own .py file
        3. Write an __init__.py that exports all public names
        4. Import the package in a fresh sys.modules namespace
        5. Return the ExecutionContext with the loaded modules
        """

    def create_merged_context(case, model_code) -> ExecutionContext:
        """
        Legacy compatibility: flat namespace (current behavior).
        Used for backward-compatible evaluation.
        """

    def create_isolated_context(case, model_code) -> ExecutionContext:
        """
        True module isolation: each file is a separate module
        with proper import resolution.
        Used for cross-boundary testing.
        """
```

**Critical guarantee**: `create_execution_context` must:
- Never reuse a previously loaded module
- Clear all module-level state by loading fresh
- Not add modules to `sys.modules` (use a private loader)
- Kill the context after the test completes

**Implementation note**: The disk-backed subprocess approach in `exec_canonical.py` already achieves some of this. The plan is to make it the ONLY execution path and to run tests within the subprocess, not in the merged namespace.

### 5.2 StateTracker

**Purpose**: Capture module state before and after test execution for transition verification.

**Design**:

```
class StateTracker:
    def snapshot(module) -> StateSnapshot:
        """
        Capture all module-level mutable state:
        - All non-callable, non-dunder attributes
        - All mutable containers (dict, list, set) with deep copy
        - Class instance attributes for known classes
        Returns a frozen snapshot for comparison.
        """

    def diff(before: StateSnapshot, after: StateSnapshot) -> StateDiff:
        """
        Compute what changed between two snapshots.
        Returns: {added: [...], removed: [...], modified: {key: (old, new)}}
        """

    def verify_reset(initial: StateSnapshot, after_reset: StateSnapshot) -> list[str]:
        """
        Verify that reset() restored ALL state to initial values.
        Returns list of violations.
        """
```

### 5.3 InvariantRunner

**Purpose**: Execute test phases in order, collect structured verdicts.

**Design**:

```
class InvariantRunner:
    def run(case, model_code, invariant_spec) -> StructuredVerdict:
        """
        1. Create fresh execution context via IsolationEngine
        2. Run Phase 0 (PRECONDITION): verify initial state
        3. Run Phase 1 (HAPPY_PATH): verify normal operation
        4. Reset state
        5. Run Phase 2 (INVARIANT): verify the specific invariant
        6. Reset state
        7. Run Phase 3 (ADVERSARIAL): boundary/contamination/ordering
        8. Reset state
        9. Run Phase 4 (ANTI_CHEAT): varying inputs
        10. Assemble StructuredVerdict

        CRITICAL: Each phase runs against a FRESH module state.
        Failure in an earlier phase does NOT skip later phases
        (we want the full picture).
        """
```

### 5.4 StructuredVerdict (replaces `(bool, list[str])`)

```python
@dataclass
class PhaseResult:
    phase: str                    # "precondition", "happy_path", etc.
    invariant_id: str             # which invariant this checks
    passed: bool
    assertions_total: int
    assertions_passed: int
    failure_details: list[str]    # specific assertion failures
    state_diff: dict | None       # what state changed during this phase

@dataclass
class StructuredVerdict:
    case_id: str
    variant: str                  # "a", "b", "c", "L3", etc.
    overall_pass: bool            # True only if ALL phases pass
    phases: list[PhaseResult]
    invariants_tested: list[str]  # invariant IDs that were exercised
    false_positive_checks: dict   # {pattern_name: detected_or_not}
    anti_cheat_passed: bool
    state_isolation_verified: bool
    execution_model: str          # "merged" or "isolated"
```

The `overall_pass` field replaces the current boolean. It is True ONLY if every phase passes. This means a function that passes the invariant check but fails the happy-path check (because it's a no-op) will correctly fail.

### 5.5 State Reset Enforcement

Current approach (ad-hoc, fragile):
```python
if hasattr(mod, "_counter"):
    mod._counter = 0
```

New approach (mandatory, verified):

Each invariant spec declares `state_contract.module_state` listing every state variable, its type, and its reset strategy. The IsolationEngine uses this contract to:

1. Before each phase: call the declared reset function (e.g., `mod.reset()`)
2. After reset: snapshot state and verify ALL declared variables are at initial values
3. If any variable is NOT at its initial value after reset: log a state_isolation_violation

If the model renames state variables, the IsolationEngine detects this by comparing the actual module attributes to the declared contract and reports the mismatch as a diagnostic, not a silent failure.

---

## 6. FAILURE CLASS -> TEST PATTERN MAPPING

### 6.1 shared_reference_mutation (alias_config)

**What naive tests miss**: That overrides are actually applied (not just that defaults are preserved).
**What robust tests enforce**:
- BEFORE state captured (DEFAULTS value)
- Override applied -> result has override
- DEFAULTS unchanged after override
- Result is not identity-equal to DEFAULTS
- Mutating result does not affect DEFAULTS
- Mutating result does not affect future calls
- Anti-cheat: non-default override values produce correct output

### 6.2 incomplete_field_sync (partial_update)

**What naive tests miss**: That ALL dependent fields are updated, not just the one checked.
**What robust tests enforce**:
- Primary field updated -> all declared dependent fields updated
- Non-updated fields remain unchanged
- For each dependency pair (source -> derived): changing source changes derived
- If metadata declares N dependent fields, ALL N are checked

### 6.3 cache_invalidation_missing (stale_cache)

**What naive tests miss**: That the cache is actually being USED (model could bypass it entirely).
**What robust tests enforce**:
- Write -> Read (cache miss path works)
- Read -> Read (cache hit path works, returns same result)
- Write -> Read -> Write -> Read (invalidation works)
- Two writes to same key -> final read returns second value
- State inspection: cache contains expected entries after operations

### 6.4 eager_capture_breaks_lifecycle (lazy_init)

**What naive tests miss**: Initial state was correct before configure.
**What robust tests enforce**:
- Initial state verified (get_host() returns default before configure)
- Configure -> get_host() returns new value
- Reset -> configure with different value -> get_host() returns latest
- Multiple configure calls -> last one wins
- State inspection: no eagerly captured closure retaining old value

### 6.5 mutable_default_accumulation (mutable_default)

**What naive tests miss**: Progressive accumulation across many calls.
**What robust tests enforce**:
- N=5 calls, each independently verified
- Different inputs each call, output only reflects current input
- Cross-function contamination check (function A's state doesn't affect function B)
- Anti-cheat: varying input sizes

### 6.6 batch_level_side_effect (effect_order)

**What naive tests miss**: That the effect happened at the wrong granularity but with the right total.
**What robust tests enforce**:
- Count of effects == count of items (not 1)
- Each effect tagged with correct item ID
- Running total/counter values are incrementally correct (not just final total)
- Order of effects matches order of items

### 6.7 conditional_variable_unset (use_before_set)

**What naive tests miss**: That the non-edge-case works correctly.
**What robust tests enforce**:
- FIRST verify the normal case returns correct result (not stale)
- THEN verify the edge case (empty/None input) returns correct default
- Verify the function can alternate between normal and edge inputs

### 6.8 retry_missing_break (retry_dup)

**What naive tests miss**: Behavior when first attempt fails and second succeeds.
**What robust tests enforce**:
- Success on first try -> exactly 1 message
- Fail first, succeed second -> exactly 1 message
- All fail -> 0 messages
- Success, then new message -> 2 messages total (1 each)

### 6.9 partial_compensation_missing (partial_rollback)

**What naive tests miss**: That the function works at all (happy path).
**What robust tests enforce**:
- **Happy path FIRST**: successful order reduces inventory, creates audit entry
- THEN failure path: failed order leaves inventory unchanged, cleans audit
- Verify exception IS raised (not silently swallowed)
- Verify BOTH rollback targets (inventory AND audit in _c variant)

### 6.10 wrong_operator / wrong_precedence (wrong_condition)

**What naive tests miss**: That the function allows legitimate requests.
**What robust tests enforce**:
- Must-allow cases: under limit, valid token, both conditions met
- Must-deny cases: at limit, over limit, expired, one condition failed
- Boundary: exact limit value (the off-by-one)
- Anti-cheat: multiple different limit/count combinations

### 6.11 early_return_skips_side_effect (early_return)

**What naive tests miss**: Content of ledger entries (only count is checked).
**What robust tests enforce**:
- Normal payment: ledger entry with correct amount and type
- Zero-amount payment: ledger entry exists with amount=0
- Duplicate payment: ledger entry exists, marked as duplicate
- Count AND content checked

### 6.12 parallel_array_desync (index_misalign)

**What naive tests miss**: Multiple mutations in sequence.
**What robust tests enforce**:
- Insert -> verify alignment
- Delete -> verify alignment
- Insert then delete -> verify alignment
- Multiple inserts at different positions -> verify alignment
- Render after each mutation (not just final)

### 6.13 silent_key_mismatch (silent_default)

**What naive tests miss**: That truly-disabled flags return False.
**What robust tests enforce**:
- Enabled flag returns True (the bug: returns False due to key mismatch)
- Disabled flag returns False (not accidentally enabled)
- Multiple flags tested, not just the one with the bug
- Anti-cheat: flag state changed at runtime, re-checked

### 6.14 stale_cache_overwrite (overdetermination)

**What naive tests miss**: That a third update also works.
**What robust tests enforce**:
- Update 1 -> read -> correct
- Update 2 (different value) -> read -> correct (current test)
- Update 3 (yet another value) -> read -> correct (accumulation)
- Update different key -> read first key -> unchanged
- Anti-cheat: lambda returning computed value, not constant

### 6.15 non_atomic_read_modify_write (lost_update, check_then_act)

**Current tests are already STRONG.** No changes needed except:
- Add a third anti-hardcoding input set
- Verify step functions still exist (structural check already present)

### 6.16 ordering_violation (ordering_dependency)

**What naive tests miss**: Multiple items before init.
**What robust tests enforce**:
- Correct order: init -> process(a) -> process(b)
- Broken order: process(a) -> init -> process(b) (current)
- Worse order: process(a) -> process(b) -> init (both before init)
- All must produce all items processed, no errors

### 6.17 circular_lock_ordering (false_fix_deadlock)

**Current test is ADEQUATE.** Add:
- Verify specific account values after transfer (not just total)
- Anti-cheat: different transfer amounts

### 6.18 absent_causally_necessary_steps (commit_gate, l3_state_pipeline)

**What naive tests miss**: Incremental updates after initial ingest.
**What robust tests enforce**:
- Initial ingest -> frozen gate set, total correct, view consistent
- Preview -> NOT frozen (current)
- Incremental update -> total reflects new entries
- Anti-cheat: different entry values and counts

### 6.19 structural_default_masked_by_override (config_shadowing)

**What naive tests miss**: That the fix is in the right layer.
**What robust tests enforce**:
- Both request and background timeout == 30 (current)
- Change DEFAULTS to a DIFFERENT value -> both paths reflect the change
  (proves the system reads from DEFAULTS, not hardcoded)
- Anti-cheat: verify retries field also propagates correctly

### 6.20 flag_not_propagated (feature_flag_drift)

**What naive tests miss**: That checkout WITHOUT the flag uses v1 pricing.
**What robust tests enforce**:
- checkout with use_new_pricing=True -> total=900 (current)
- checkout with use_new_pricing=False -> total=1000 (MISSING)
- Flag cleanup after checkout (current)
- Anti-cheat: different quantities, verify discount threshold

### 6.21 balance_not_conserved_on_failure (invariant_partial_fail)

**What naive tests miss**: That transfer works at all (happy path).
**What robust tests enforce**:
- **Happy path FIRST**: random > 0.3, transfer succeeds
  - sender.balance == 50, receiver.balance == 50
- Failure path: random < 0.3, transfer fails
  - Exception raised (VERIFIED, not silently swallowed)
  - sender.balance + receiver.balance == initial total
  - Debit was rolled back (sender.balance == initial, NOT sender.balance == 50)
- Anti-cheat: different amounts

### 6.22 write_through_cache_broken (hidden_dep_multihop)

**What naive tests miss**: rename_user path.
**What robust tests enforce**:
- save_user -> get_display_name (current)
- save_user twice -> get_display_name returns latest (current)
- rename_user -> get_display_name returns new name (MISSING)
- delete_user -> get_display_name returns None (MISSING)

### 6.23 non_atomic_check_then_act (async_race_lock)

**What naive tests miss**: That locking actually provides atomicity.
**What robust tests enforce**:
- run_verified produces correct total (current)
- Results have before/after fields (current)
- Calling run_verified twice produces correct total both times
- After run_verified, counter state reflects expected value

---

## 7. FALSE POSITIVE / FALSE NEGATIVE ANALYSIS

### 7.1 Current False Positive Vectors (wrong code passes)

| Family | False Positive Pattern | Root Cause | New System Prevention |
|--------|----------------------|------------|----------------------|
| wrong_condition (a,b,c) | `return True` / `return False` | No allow-path test | Phase 1 (happy_path) requires both allow AND deny |
| partial_rollback (a,b,c) | No-op `place_order` | No happy-path test | Phase 1 verifies successful order reduces inventory |
| invariant_partial_fail | No-op `execute_transfer` | No happy-path test | Phase 1 verifies successful transfer moves funds |
| temporal_drift (a,b,c) | Remove normalization entirely | Only raw_stats checked | Phase 1 verifies normalized output exists and is correct |
| alias_config (a,b) | Ignore overrides, return defaults | Override result not checked | Phase 1 verifies override appears in result |
| config_shadowing | Hardcode 30 in both paths | Only checks value, not source | Phase 4 uses different config value to detect hardcoding |
| feature_flag_drift | Bypass flag system, compute directly | Only checks total | Phase 1 verifies flag-off path; Phase 4 varies inputs |
| early_return (a,b,c) | Append dummy ledger entries | Only count checked, not content | Phase 2 checks entry content matches operation |
| missing_branch (a,b,c) | Give all roles maximum permissions | Only missing role checked | Phase 3 verifies existing roles have correct (limited) permissions |
| partial_update_c | Fix verified but not cached_greeting | cached_greeting not checked | Phase 2 checks ALL declared dependent fields |

### 7.2 Current False Negative Vectors (correct code fails)

| Family | False Negative Pattern | Root Cause | New System Prevention |
|--------|----------------------|------------|----------------------|
| lazy_init_a | Model uses different variable name for captured state | Test resets `_default_host` directly | IsolationEngine uses fresh module, no manual reset needed |
| effect_order | Model renames `_counter` | Test resets by name | IsolationEngine uses fresh module |
| All multi-file cases | Model maintains file boundaries but merged namespace works differently | Concat/merge erases boundaries | Isolated execution mode tests actual imports |

### 7.3 How New System Prevents Each

**False positives**: Eliminated by Phase 1 (happy_path). Every test must verify the function works correctly before testing the invariant. A no-op function fails Phase 1.

**False positives from hardcoding**: Eliminated by Phase 4 (anti_cheat). Every test uses at least 2 distinct input sets. Hardcoded outputs fail on the non-standard input.

**False negatives from state reset**: Eliminated by IsolationEngine. Fresh module per test invocation means no manual state reset is needed. Module-level state starts at its initialization value every time.

---

## 8. MIGRATION PLAN

### Phase 1: Foundation (no behavior change)

**Goal**: Introduce new infrastructure without breaking existing tests.

1. Create `INVARIANT_SPECS/` directory
2. Write invariant specs for 5 pilot families:
   - `wrong_condition` (MISLEADING -> must be fixed first)
   - `partial_rollback` (MISLEADING -> must be fixed first)
   - `invariant_partial_fail` (MISLEADING -> must be fixed first)
   - `lost_update` (STRONG -> reference implementation)
   - `alias_config` (ADEQUATE -> representative multi-variant)
3. Implement `StructuredVerdict` dataclass
4. Implement `StateTracker` (snapshot/diff only, not wired to tests yet)
5. Implement `IsolationEngine.create_merged_context()` (same as current behavior)

**Verification**: All existing tests still pass. New infrastructure exists but is not yet used for scoring.

### Phase 2: Rewrite pilot families (5 families, 13 cases)

**Goal**: Replace the 5 pilot test families with spec-driven tests.

1. Rewrite `tests_v2/test_wrong_condition.py` with all phases
2. Rewrite `tests_v2/test_partial_rollback.py` with all phases
3. Rewrite `tests_v2/test_invariant_partial_fail.py` with all phases
4. Rewrite `tests_v2/test_lost_update.py` with all phases (should be minimal changes)
5. Rewrite `tests_v2/test_alias_config.py` with all phases

**Verification**:
- Reference fixes pass all phases for all 5 families
- Buggy code fails at least one phase for all 5 families
- Known false-positive patterns (no-op, always-True) now correctly fail
- Existing reference-fix pass rates are unchanged or improved

### Phase 3: Extend to all families (remaining 23 families, 38 cases)

**Goal**: Every family has a formal invariant spec and phase-structured tests.

Order of rewrite (by priority):
1. `temporal_drift` (WEAK, false positive risk)
2. `missing_branch` (WEAK, false positive risk)
3. `feature_flag_drift` (WEAK, false positive risk)
4. `config_shadowing` (WEAK, false positive risk)
5. `partial_update` (metadata mismatch)
6. `cache_invalidation_order` (metadata mismatch)
7. `use_before_set` (WEAK)
8. `lazy_init` (WEAK, fragile reset)
9. `silent_default` (WEAK, fragile reset)
10. `async_race_lock` (WEAK, proxy check)
11. `early_return` (ADEQUATE but content not checked)
12. `stale_cache` (ADEQUATE)
13. `retry_dup` (ADEQUATE)
14. `effect_order` (ADEQUATE)
15. `mutable_default` (STRONG, add anti-cheat)
16. `index_misalign` (ADEQUATE)
17. `hidden_dep_multihop` (ADEQUATE)
18. `overdetermination` (ADEQUATE)
19. `ordering_dependency` (ADEQUATE)
20. `commit_gate` (ADEQUATE)
21. `l3_state_pipeline` (ADEQUATE)
22. `check_then_act` (STRONG, minimal changes)
23. `false_fix_deadlock` (STRONG, minimal changes)

**Verification at each step**: Reference fix passes, buggy code fails, known false-positive patterns fail.

### Phase 4: Harness upgrade

**Goal**: Replace ad-hoc state reset with IsolationEngine.

1. Implement `IsolationEngine.create_isolated_context()` (true module isolation)
2. Wire `InvariantRunner` to use `IsolationEngine` for all test executions
3. Add `StateTracker` verification to each phase boundary
4. Update `harness/run_case.py` to use the new structured verdict format
5. Update `exec_eval.py` to consume `StructuredVerdict` and produce backward-compatible `(pass, score, reasons)` for the existing pipeline

**Verification**: All tests produce identical pass/fail results in both old and new harness. State isolation violations are detected and logged.

### Phase 5: Coverage and meta-testing

**Goal**: Prove the test system is correct.

1. Implement `CoverageAnalyzer` that reports:
   - Which invariant IDs were tested
   - Which failure modes were exercised
   - Which phases ran for each case
2. Write meta-tests (see Section 9)
3. Generate coverage report and identify gaps
4. Remove mutation test inflation for V2 cases

---

## 9. VALIDATION STRATEGY

### 9.1 Meta-Tests for Tests

The following meta-tests prove the test system itself is correct:

**META-1: Reference fix passes all phases**
```
For each case in cases_v2.json:
    Load reference fix code
    Run all test phases
    Assert: overall_pass == True
    Assert: every phase passes
```
If a reference fix fails any phase, the test is wrong.

**META-2: Buggy code fails at least one invariant phase**
```
For each case in cases_v2.json:
    Load buggy code (original code_snippets_v2)
    Run all test phases
    Assert: Phase 2 (INVARIANT) fails
    Assert: Phase 1 (HAPPY_PATH) may pass (buggy code CAN work for normal inputs)
```
If buggy code passes the invariant phase, the test is wrong.

**META-3: Known false-positive patterns fail**
```
For each false_positive_pattern declared in invariant specs:
    Construct the pattern code (e.g., no-op function, always-True predicate)
    Run all test phases
    Assert: at least one phase fails
    Assert: the failure is in the phase declared by "detected_by"
```

**META-4: Trap fixes are detected**
```
For each case with a declared "trap" in cases_v2.json:
    Construct the trap fix code
    Run all test phases
    Assert: at least one phase fails
    Assert: the failure is in the invariant declared by trap_fix_detection
```

**META-5: Invariant spec completeness**
```
For each case in cases_v2.json:
    Assert: INVARIANT_SPECS/{family}.yaml exists
    Assert: spec declares at least 1 invariant
    Assert: spec has all 5 test phases populated
    Assert: spec has at least 1 false_positive_pattern
    Assert: every invariant_id is referenced by at least 1 test assertion
```

**META-6: Anti-cheat coverage**
```
For each case:
    Assert: Phase 4 (ANTI_CHEAT) has at least 2 distinct input sets
    Assert: input sets produce different expected outputs
```

### 9.2 Proving Test Correctness

A test is CORRECT if and only if:
1. The reference fix passes it (META-1)
2. The buggy code fails it (META-2)
3. Known degenerate implementations fail it (META-3)
4. Known trap fixes fail it (META-4)
5. The invariant spec is complete (META-5)
6. Anti-cheat inputs are diverse (META-6)

All 6 meta-tests must pass for every case before the benchmark is considered trustworthy.

---

## FILES THAT WILL BE CREATED

```
INVARIANT_SPECS/                          (28 YAML files, one per family)
    invariant_alias_config.yaml
    invariant_partial_update.yaml
    invariant_stale_cache.yaml
    invariant_lazy_init.yaml
    invariant_mutable_default.yaml
    invariant_effect_order.yaml
    invariant_use_before_set.yaml
    invariant_retry_dup.yaml
    invariant_partial_rollback.yaml
    invariant_temporal_drift.yaml
    invariant_missing_branch.yaml
    invariant_wrong_condition.yaml
    invariant_early_return.yaml
    invariant_index_misalign.yaml
    invariant_silent_default.yaml
    invariant_l3_state_pipeline.yaml
    invariant_cache_invalidation_order.yaml
    invariant_feature_flag_drift.yaml
    invariant_invariant_partial_fail.yaml
    invariant_async_race_lock.yaml
    invariant_hidden_dep_multihop.yaml
    invariant_config_shadowing.yaml
    invariant_commit_gate.yaml
    invariant_overdetermination.yaml
    invariant_lost_update.yaml
    invariant_check_then_act.yaml
    invariant_ordering_dependency.yaml
    invariant_false_fix_deadlock.yaml
```

## FILES THAT WILL BE MODIFIED

```
tests_v2/test_*.py                        (28 files, all rewritten)
harness/run_case.py                       (updated to emit StructuredVerdict)
exec_eval.py                              (consume StructuredVerdict, remove mutation test inflation)
```

## FILES THAT WILL BE CREATED (harness)

```
harness/isolation_engine.py               (IsolationEngine)
harness/state_tracker.py                  (StateTracker)
harness/invariant_runner.py               (InvariantRunner)
harness/structured_verdict.py             (StructuredVerdict dataclass)
harness/coverage_analyzer.py              (CoverageAnalyzer)
tests/test_meta_reference_pass.py         (META-1)
tests/test_meta_buggy_fail.py             (META-2)
tests/test_meta_false_positive.py         (META-3)
tests/test_meta_trap_detection.py         (META-4)
tests/test_meta_spec_completeness.py      (META-5)
tests/test_meta_anti_cheat.py             (META-6)
```

---

## RISKS

1. **Backward compatibility**: Rewriting tests may change pass/fail rates for previously collected data. Mitigation: keep old tests alongside new ones during Phase 2-3; compare results before removing old tests.

2. **Spec maintenance**: 28 YAML specs must be kept in sync with test code. Mitigation: META-5 enforces completeness; any spec-test mismatch is a test failure.

3. **Over-specification**: Specs that are too tight may reject valid alternative fixes. Mitigation: invariants should express WHAT must hold, not HOW it is implemented. Phase 1 (happy_path) tests behavior, not implementation.

4. **Scope creep into implementation**: This plan must not become an implementation task. Each phase has concrete verification criteria that can be checked before proceeding.

5. **False confidence from Phase 4 (anti-cheat)**: Anti-cheat inputs might be too predictable. Mitigation: use computed values (lambdas, arithmetic) rather than literal constants where possible.
