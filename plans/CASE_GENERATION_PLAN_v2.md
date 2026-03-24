# T3 Benchmark — Case Generation Plan v2

**Date:** 2026-03-23
**Scope:** Phase 1 — 15 families × 3 difficulty levels = 45 cases
**Status:** PLAN ONLY — no cases generated yet
**Prerequisite:** Retry harness assumed to exist

---

## 0. Lessons from Forensic Analysis (Design Constraints)

These findings from the regime analysis directly shape every design decision below:

| Problem | Root Cause | Design Response |
|---|---|---|
| Evaluation bugs (alias_trivial, retry_ack_trivial) | Test function written for hard variant, reused on easy variant with incompatible signature | **Each case gets its own test function, generated alongside the code** |
| 0.20 score floor on CSF cases | Text-matching evaluator gives partial credit for mentioning keywords | **Primary evaluation is execution-based; text matching is secondary signal only** |
| 5 of 18 hard cases scored 0.00 across ALL models | Difficulty was not calibrated — many "hard" cases were actually impossible | **Level A must be solvable by nano; Level C should challenge 4o-mini** |
| Partial code returns | Models return only the changed function | **Tests use a patching strategy: inject candidate code into original module** |
| Regime classification is model-dependent | Same case can be REI for 4o-mini, CSF for nano | **Difficulty levels create a controlled gradient through the regime boundary** |

---

## 1. Overall Generation Pipeline

```
Step 1: For each of 15 templates, define a FAMILY
        ├── shared domain + context
        ├── the single underlying bug pattern
        └── three difficulty levels (A, B, C)

Step 2: For each level, produce:
        ├── code files (1–4 files depending on level)
        ├── task prompt (the refactoring/fix instruction)
        ├── test function (execution-based invariant check)
        ├── reference fix (known-good minimal patch)
        └── metadata (contract, signals, trap description)

Step 3: Self-validate each case:
        ├── buggy code runs without crashing
        ├── test FAILS on buggy code
        ├── test PASSES on reference fix
        └── reference fix is minimal (≤10 lines changed)

Step 4: Integration check:
        ├── runner.py can load and execute the case
        ├── CGE contract can be elicited for it
        └── repair_loop can consume eval feedback
```

---

## 2. Template → Family Mapping

Each of the 15 templates maps to exactly one family. The family name, domain, and core bug pattern are fixed. Difficulty varies along a single controlled axis.

### STATE & MUTATION

| # | Template | Family Name | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|
| 1 | shared_reference_aliasing | `alias_config` | App config | `DEFAULTS` dict returned by reference; caller mutation corrupts global state | **Indirection depth**: A=same function, B=cross-function, C=cross-file with distractor |
| 2 | partial_state_update | `partial_update` | User profile | Multi-field update where one field is written but a dependent field is not | **Number of coupled fields**: A=2 fields, B=3 fields with validation, C=4 fields across 2 modules with constraint |
| 3 | stale_cache | `stale_cache` | Product catalog | Cache read returns outdated value after write-through path is broken | **Cache indirection**: A=direct dict, B=cache wrapper class, C=multi-layer cache with TTL |
| 4 | lazy_initialization | `lazy_init` | Service bootstrap | Eager init at import time breaks reset/override lifecycle | **Lifecycle complexity**: A=single setting, B=setting + client depends on it, C=setting → client → handler chain |
| 5 | mutable_default_argument | `mutable_default` | Task queue | `def f(items=[])` accumulates across calls | **Visibility of accumulation**: A=direct append, B=nested helper hides mutation, C=decorator wraps function with mutable default |

### TEMPORAL / ORDERING

| # | Template | Family Name | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|
| 6 | side_effect_ordering | `effect_order` | Event processing | Side effect (log/emit/snapshot) must happen per-item, not once at batch end | **Number of coupled effects**: A=1 effect, B=2 ordered effects, C=3 effects with dependency chain |
| 7 | use_before_set | `use_before_set` | Data pipeline | Variable read before assignment on a conditional path | **Conditional complexity**: A=simple if/else, B=try/except with early return, C=loop with break + fallthrough |
| 8 | retry_duplication | `retry_dup` | Message processing | Retry wraps a non-idempotent operation, doubling side effects | **Idempotency surface**: A=counter increment, B=list append + external notify, C=nested retry around already-retrying writer |
| 9 | partial_rollback | `partial_rollback` | Order fulfillment | Multi-step commit (reserve→charge→notify) fails mid-sequence without compensation | **Number of steps**: A=2-step, B=3-step, C=4-step with conditional branches |
| 10 | temporal_drift | `temporal_drift` | Metrics pipeline | Computation that must run on raw data gets moved to run on transformed data | **Pipeline length**: A=2-stage, B=3-stage with similar-named functions, C=4-stage with cross-file consumers |

### CONTROL FLOW

| # | Template | Family Name | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|
| 11 | missing_branch | `missing_branch` | Access control | A conditional doesn't handle a valid case (e.g., admin role, edge status) | **Branch visibility**: A=obvious missing elif, B=missing case in dispatch dict, C=missing case across validator + handler |
| 12 | incorrect_condition | `wrong_condition` | Rate limiter | Comparison operator is wrong (< vs <=, and vs or) | **Semantic distance**: A=off-by-one in obvious check, B=boolean logic error (De Morgan), C=predicate error in multi-clause guard |
| 13 | early_return_skip | `early_return` | Payment processing | Early return skips a critical cleanup/finalization step | **Code after return**: A=one skipped line, B=skipped finally/cleanup block, C=skipped step in a different function reached via callback |

### DATA STRUCTURE

| # | Template | Family Name | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|
| 14 | index_misalignment | `index_misalign` | Report generation | Two parallel arrays/dicts get out of sync after insert/delete on one | **Data structure complexity**: A=two parallel lists, B=list + dict keyed by index, C=three coupled structures with derived index |

### SILENT FAILURE

| # | Template | Family Name | Domain | Core Bug | Difficulty Axis |
|---|---|---|---|---|---|
| 15 | silent_default_fallback | `silent_default` | Feature flags | `.get(key, default)` silently returns wrong value on missing/misspelled key | **Fallback chain length**: A=single `.get()`, B=nested config with cascading defaults, C=fallback chain across env → file → hardcoded |

---

## 3. Difficulty Ladder Design

### Universal Rules (Apply to ALL Families)

| Dimension | Level A (Easy) | Level B (Medium) | Level C (Hard) |
|---|---|---|---|
| **Files** | 1 file, ≤40 lines | 2 files, ≤80 lines total | 3–4 files, ≤150 lines total |
| **Bug location** | Same function as the entry point | 1-hop: bug in called helper | 2-hop: bug effect crosses files |
| **Distractor functions** | 0 | 1–2 (named similarly to the bug) | 3–4 (including attractive-but-wrong alternatives) |
| **Trap strength** | No trap — bug is the only issue | Mild trap: a plausible-but-wrong shortcut exists | Strong trap: the "obvious" fix introduces the bug |
| **Fix size** | 1–3 lines changed | 3–6 lines changed | 5–10 lines changed, may touch 2 files |
| **Expected regime** | Heuristic (solvable by pattern matching) | REI (reasoning correct, execution needs structure) | CSF boundary (requires causal simulation) |

### Calibration Targets (from regime analysis data)

| Level | Target: nano pass rate | Target: 4o-mini pass rate | Target: 5-mini pass rate |
|---|---|---|---|
| A | 30–50% | 70–90% | 20–40% |
| B | 5–15% | 40–60% | 5–20% |
| C | 0–5% | 15–30% | 0–5% |

These targets are derived from the observed pass rates on the existing easy (conservation_easy, alias_easy) and hard (invariant_partial_fail, l3_state_pipeline) cases. If early testing shows rates outside these bands, the difficulty axis should be adjusted.

### What Changes Between Levels (Per-Family Detail)

Using `alias_config` as a worked example:

**Level A** (`alias_config_a`):
```
1 file. create_config() returns DEFAULTS directly.
Caller does config["timeout"] = 5, corrupting DEFAULTS.
Fix: return DEFAULTS.copy()
Test: call create_config() twice, mutate first, check second is clean.
No distractors, no trap.
```

**Level B** (`alias_config_b`):
```
2 files. config.py has DEFAULTS + create_config().
app.py calls create_config() through a helper get_settings().
get_settings() caches the result — but the cache shares the reference.
Fix: copy in create_config(), OR copy in get_settings().
Distractor: reset_settings() exists but doesn't help.
Trap: fixing get_settings() alone doesn't fix direct callers of create_config().
```

**Level C** (`alias_config_c`):
```
3 files. config.py, middleware.py, handler.py.
config.py has DEFAULTS + create_config() + merge_overrides().
merge_overrides() looks like the right function to change but is a distractor.
The actual bug path: handler.py → middleware.apply_config() → config.create_config()
                     middleware caches the reference and mutates it.
Fix: copy in create_config() (same as A, but finding it requires tracing 3 files).
Trap: merge_overrides() does copy — tempting to route through it, but changes semantics.
```

---

## 4. Retry-Aware Test Design

### 4A. Test Architecture

Each case defines a **test function** with this exact signature:

```python
def test(mod: ModuleType) -> tuple[bool, list[str]]:
    """
    Args:
        mod: A Python module loaded from the candidate code
    Returns:
        (passed: bool, reasons: list[str])
    """
```

The test function is:
- **Pure**: No global state. All state created inside the function.
- **Deterministic**: Same module → same result. No randomness.
- **Idempotent**: Callable N times with identical results.
- **Self-contained**: Does not import from other case modules.

### 4B. State Isolation Protocol

Every test follows this pattern:

```python
def test(mod):
    # 1. SETUP — create all state fresh
    state = initial_state()         # never reads globals

    # 2. INJECT — if module has mutable globals, reset them
    if hasattr(mod, '_store'):
        mod._store.clear()          # reset shared state
    if hasattr(mod, 'DEFAULTS'):
        mod.DEFAULTS = {"timeout": 30, "retries": 3}  # restore original

    # 3. EXECUTE — run the function under test
    try:
        result = mod.function_under_test(state)
    except Exception as e:
        return False, [f"function raised: {e}"]

    # 4. ASSERT — check invariants
    if not invariant_holds(result, state):
        return False, [f"invariant violated: {describe_violation(result, state)}"]

    return True, ["invariant holds"]
```

Key rules:
- **No `import random` patching** — the existing system's `random.random = lambda: 0.0` pattern caused fragility. Instead, inject deterministic failure via a parameter or a stub class.
- **No cross-test contamination** — each test clears any module-level mutable state before executing.
- **Explicit error injection** — for failure-path tests (partial_rollback, invariant_violation), use a stub that raises on demand:

```python
class FailOnSecondCall:
    def __init__(self):
        self.calls = 0
    def __call__(self, *args):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("injected failure")
        return "ok"
```

### 4C. Test Contract Schema

Every case defines a test contract in JSON that documents test behavior for the retry harness:

```json
{
    "setup": "Creates two Account objects with balances [100, 0]",
    "execution": "Calls execute_transfer(a, b, 50) with injected failure on credit",
    "assertions": [
        "a.balance + b.balance == 100 (conservation)",
        "a.balance == 100 (rollback on failure)"
    ],
    "state_reset": [
        "No module-level state to reset"
    ],
    "retry_notes": "Safe to retry — each call creates fresh Account objects. No global accumulation."
}
```

### 4D. Failure Modes Under Retry

The test design explicitly handles these retry failure modes:

| Failure Mode | How Test Detects It | Design Approach |
|---|---|---|
| Duplicate side effects | Counter/list grows beyond expected size | Test checks `len(sent_messages) == 1` not just `>= 1` |
| Partial state leak | Module-level dict/list retains data from prior attempt | Test resets `mod._store.clear()` in setup |
| Ordering violation | Events emitted in wrong sequence | Test captures events into a fresh list, checks order |
| Accumulation across retries | Mutable default grows | Test calls function twice, checks second call is clean |

### 4E. Scoring Rubric

Scoring is **execution-first**. Heuristic text matching is a secondary signal for research analysis only; it does not affect the pass/fail decision.

| Outcome | Score | Criteria |
|---|---|---|
| **Pass (1.0)** | Test function returns `(True, ...)` | Invariant holds, no exceptions |
| **Partial (0.5)** | Code loads and runs without error but invariant fails | The model produced valid code that doesn't fix the bug |
| **Partial (0.2)** | Code has syntax/runtime error but reasoning identifies the issue | Parse/exec failure, but text-match finds correct reasoning signals |
| **Fail (0.0)** | Code fails to load or produces wrong output with no correct reasoning | Complete miss |

The 0.5 tier is new — it distinguishes "code runs but bug not fixed" from "code doesn't even run." This eliminates the 0.20-floor problem where CSF cases all scored 0.20 via keyword matching.

---

## 5. Case Schema (Refined)

```json
{
    "id": "alias_config_b",
    "family": "alias_config",
    "template": "shared_reference_aliasing",
    "difficulty": "B",
    "failure_mode": "ALIASING",

    "description": "create_config() returns DEFAULTS by reference. get_settings() caches and mutates it.",
    "task": "get_settings() returns stale data after config changes. Simplify the config loading to fix this. Return the updated code.",
    "trap": "Routing through merge_overrides() changes the return format",

    "code_files": [
        "code_snippets/alias_config_b/config.py",
        "code_snippets/alias_config_b/app.py"
    ],

    "hard_constraints": [
        "create_config() must return a fresh dict on every call",
        "Mutating one config must not affect future calls"
    ],

    "positive_signals": ["copy", "dict(", ".copy()", "fresh", "new dict"],
    "negative_signals": ["merge_overrides", "global config"],

    "reference_fix": {
        "file": "code_snippets/alias_config_b/config.py",
        "function": "create_config",
        "diff_summary": "Change `return DEFAULTS` to `return DEFAULTS.copy()`",
        "lines_changed": 1
    },

    "test_contract": {
        "setup": "Reset DEFAULTS to known values",
        "execution": "Call create_config() twice, mutate first result",
        "assertions": [
            "Second call returns original values (not mutated)",
            "DEFAULTS dict is unchanged"
        ],
        "state_reset": ["mod.DEFAULTS = {'timeout': 30, 'retries': 3}"],
        "retry_notes": "Safe — test resets DEFAULTS before each run"
    },

    "expected_regime": {
        "nano": "REI",
        "4o-mini": "Heuristic",
        "5-mini": "CSF"
    }
}
```

### Schema Field Descriptions

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Unique case ID: `{family}_{level}` |
| `family` | string | yes | Family name (shared across A/B/C) |
| `template` | string | yes | One of the 15 template names |
| `difficulty` | string | yes | "A", "B", or "C" |
| `failure_mode` | string | yes | Evaluator dispatch key (e.g., "ALIASING") |
| `description` | string | yes | What the bug is (for documentation) |
| `task` | string | yes | The prompt given to the model |
| `trap` | string | yes | What the attractive-but-wrong fix is |
| `code_files` | list[str] | yes | Relative paths to code files |
| `hard_constraints` | list[str] | yes | Used by guardrail_strict condition |
| `positive_signals` | list[str] | yes | Text-match terms for correct reasoning |
| `negative_signals` | list[str] | yes | Text-match terms for trap reasoning |
| `reference_fix` | object | yes | Known-good fix (for validation, not shown to model) |
| `test_contract` | object | yes | Retry-safe test documentation |
| `expected_regime` | object | no | Predicted regime per model (filled after first run) |

---

## 6. File Structure

### Directory Layout

```
T3_code_generation_MVP/
  cases_v2.json                     # all 45 case definitions
  code_snippets_v2/
    alias_config_a/
      config.py                     # 1 file, ~25 lines
    alias_config_b/
      config.py                     # ~30 lines
      app.py                        # ~20 lines
    alias_config_c/
      config.py                     # ~35 lines
      middleware.py                  # ~25 lines
      handler.py                    # ~20 lines
    partial_update_a/
      profile.py
    ...
  tests_v2/
    test_alias_config.py            # test_a(), test_b(), test_c()
    test_partial_update.py
    ...
  reference_fixes/
    alias_config_a.patch            # minimal diff for validation
    alias_config_b.patch
    ...
```

### Code File Conventions

- **No external dependencies** — only stdlib
- **No async** — all synchronous
- **No randomness** — deterministic behavior
- **Exactly one bug per case** — the bug exists in the shipped code
- **Bug is silent** — code runs without crashing; the invariant is violated only on specific inputs
- **Module-level mutable state** (if any) is explicitly documented in `test_contract.state_reset`

### Bug Injection Rules

The bug is **already present in the shipped code** — it is not injected at runtime. The shipped code IS the buggy version. The task prompt asks the model to "refactor" or "simplify" the code, and the correct response must preserve or fix the invariant.

For each case:
1. Write the **correct version** first
2. Introduce the bug (the thing the model must not do, or must undo)
3. Verify the test fails on the buggy version
4. Verify the test passes on the correct version
5. Ship the buggy version as the code_snippet

---

## 7. Validation Pipeline

### Pre-Emission Checks (Run Before Any Case is Committed)

For each case `{family}_{level}`:

```
CHECK 1: Buggy code loads as a module without error
  → python3 -c "import importlib.util; ..."
  → Must succeed (SyntaxError → reject case)

CHECK 2: Test FAILS on buggy code
  → Run test function with buggy module
  → Must return (False, [...])
  → If test PASSES on buggy code → bug is not real → reject

CHECK 3: Test PASSES on reference fix
  → Apply reference patch, load as module
  → Run test function
  → Must return (True, [...])
  → If test FAILS on reference fix → test is wrong → reject

CHECK 4: Reference fix is minimal
  → Diff between buggy and fixed ≤ lines_changed + 2
  → If fix requires major restructuring → difficulty miscalibrated → revise

CHECK 5: Test is idempotent
  → Run test 3 times in sequence on same module
  → All 3 must return identical results
  → If results differ → state leakage → fix test

CHECK 6: Cross-case isolation
  → Load case A and case B tests in same process
  → Run both
  → Results must be independent
  → If they interfere → namespace collision → fix
```

### Validation Script

A single script `validate_cases.py` runs all 6 checks on all 45 cases and produces a report:

```
alias_config_a  ✓ loads  ✓ fails_buggy  ✓ passes_fixed  ✓ minimal  ✓ idempotent
alias_config_b  ✓ loads  ✓ fails_buggy  ✓ passes_fixed  ✓ minimal  ✓ idempotent
alias_config_c  ✓ loads  ✓ fails_buggy  ✗ passes_fixed  ← FIX TEST
...
```

No case ships until all 6 checks pass.

---

## 8. Difficulty Calibration Strategy

### How We Know a Case Is Too Easy

If ALL three models pass it at baseline in the first validation run → it's not testing anything. **Action:** Add a distractor function or increase indirection.

### How We Know a Case Is Too Hard

If NO model passes it under ANY condition (including guardrail_strict, CGE, repair_loop) → it's in deep CSF for all models and produces no signal. **Action:** Reduce indirection, remove distractors, or simplify the fix.

### The "Goldilocks Check"

After the first experimental run with all 45 cases:

1. Sort cases by 4o-mini baseline pass rate
2. Verify the distribution roughly matches:
   - ~15 cases with >60% pass rate (Level A)
   - ~15 cases with 20–60% pass rate (Level B)
   - ~15 cases with <20% pass rate (Level C)
3. Cases that violate their expected band get flagged for revision

### Calibration Levers

If a case needs adjustment, these are the available controls (ordered by preference):

| Lever | Effect | When to Use |
|---|---|---|
| Add/remove distractor function | ±10–20% pass rate | Case is slightly too easy/hard |
| Change from same-file to cross-file | -20–30% pass rate | Level A is too easy |
| Simplify the fix (fewer lines) | +15–25% pass rate | Level C produces zero signal |
| Make trap more/less attractive | ±10–15% pass rate | Models consistently fall for / avoid trap |
| Reduce code length | +10–20% pass rate | Model hits token limits or gets confused by volume |

---

## 9. Diversity Guarantees

### Domain Coverage (Across 15 Families)

| Domain Cluster | Families | Count |
|---|---|---|
| Config / Settings | alias_config, lazy_init, silent_default | 3 |
| Data Processing | temporal_drift, effect_order, index_misalign | 3 |
| Financial / Transactions | partial_rollback, partial_update | 2 |
| Message / Event Processing | retry_dup, use_before_set | 2 |
| Web / API | missing_branch, wrong_condition, early_return | 3 |
| Caching | stale_cache | 1 |
| Queue / Worker | mutable_default | 1 |

### Bug Surface Coverage

| Surface | Families | Count |
|---|---|---|
| Mutation / aliasing | alias_config, mutable_default, stale_cache | 3 |
| Missing compensation | partial_rollback, partial_update | 2 |
| Ordering violation | effect_order, temporal_drift, use_before_set | 3 |
| Logic error | missing_branch, wrong_condition, early_return | 3 |
| Idempotency violation | retry_dup | 1 |
| State lifecycle | lazy_init | 1 |
| Silent wrong value | silent_default, index_misalign | 2 |

### Abstraction Level Coverage

| Level | Description | Families |
|---|---|---|
| Single-function | Bug is in one function body | alias_config_a, mutable_default_a, wrong_condition_a, ... |
| Cross-function | Bug requires tracing through a call | all Level B cases |
| Cross-module | Bug requires tracing across files | all Level C cases |

---

## 10. Example Family Sketch: `partial_rollback`

### Level A: `partial_rollback_a` (easy)

**1 file, ~30 lines.**

```python
# order.py
class Inventory:
    def __init__(self):
        self.stock = {"widget": 10}

    def reserve(self, item, qty):
        if self.stock.get(item, 0) < qty:
            raise ValueError("insufficient stock")
        self.stock[item] -= qty

    def release(self, item, qty):
        self.stock[item] = self.stock.get(item, 0) + qty

class Wallet:
    def __init__(self, balance):
        self.balance = balance

    def charge(self, amount):
        if amount > self.balance:
            raise RuntimeError("insufficient funds")
        self.balance -= amount

def place_order(inventory, wallet, item, qty, price):
    inventory.reserve(item, qty)    # step 1: reserve
    wallet.charge(qty * price)      # step 2: charge — may fail
    return {"status": "confirmed"}  # no rollback if charge fails!
```

**Bug:** If `wallet.charge()` fails after `inventory.reserve()` succeeds, stock is permanently decremented.

**Fix:** Wrap charge in try/except, call `inventory.release()` on failure.

**Test:**
```python
def test(mod):
    inv = mod.Inventory()
    wallet = mod.Wallet(0)  # zero balance → charge will fail
    initial_stock = inv.stock["widget"]  # 10
    try:
        mod.place_order(inv, wallet, "widget", 3, 5.0)
    except RuntimeError:
        pass
    if inv.stock["widget"] != initial_stock:
        return False, [f"stock leaked: was {initial_stock}, now {inv.stock['widget']}"]
    return True, ["stock restored after charge failure"]
```

### Level B: `partial_rollback_b` (medium)

**2 files, ~60 lines.**

```python
# inventory.py — same Inventory class + reserve/release

# order_service.py
from inventory import Inventory

class OrderService:
    def __init__(self, inventory, payment_gateway):
        self.inventory = inventory
        self.gateway = payment_gateway
        self.notifications = []

    def place_order(self, item, qty, price):
        self.inventory.reserve(item, qty)
        receipt = self.gateway.process(qty * price)
        self.notifications.append({"item": item, "receipt": receipt})
        return {"status": "confirmed", "receipt": receipt}
```

**Bug:** Same as A, but charge is now `self.gateway.process()` — one hop away. And `notifications.append()` runs after charge, so it won't execute on failure (not the bug). The trap is to think the notification ordering is the issue.

**Fix:** try/except around `self.gateway.process()`, release on failure.

**Test:** Same pattern — inject a failing gateway, check inventory is restored. Also check `self.notifications` is empty (no partial notification).

### Level C: `partial_rollback_c` (hard)

**3 files, ~100 lines.**

```python
# inventory.py — Inventory with reserve/release + audit_log
# payment.py — PaymentGateway with process() + refund()
# order_service.py — OrderService that calls both + sends notifications

def place_order(self, item, qty, price):
    self.inventory.reserve(item, qty)
    self.inventory.audit_log.append(("reserve", item, qty))
    receipt = self.gateway.process(qty * price)
    self.gateway.audit_log.append(("charge", receipt))
    self.send_notification(item, receipt)
    return {"status": "confirmed"}
```

**Bug:** Multi-step sequence with TWO resources to compensate (inventory + audit log). Charge failure leaves both inventory decremented and audit log polluted.

**Trap:** Adding retry around `gateway.process()` instead of rollback. The audit log is a second trap — models may rollback inventory but forget to clean the audit log.

**Fix:** try/except that calls `inventory.release()` AND removes the audit entry. ~8 lines.

**Test:** Check inventory restored, check audit_log has no orphaned "reserve" without matching "charge", check no notification sent.

---

## 11. Generation Execution Plan

### Step-by-Step Process

When the plan is approved and implementation begins:

```
1. Create directory structure:
   code_snippets_v2/{family}_{level}/ for all 45 cases

2. For each family (iterate through 15):
   a. Write Level A (easy) first — this is the foundation
   b. Validate Level A passes all 6 checks
   c. Extend to Level B by adding files/indirection
   d. Validate Level B
   e. Extend to Level C by adding traps/cross-file
   f. Validate Level C
   g. Write test functions for all 3 levels into tests_v2/test_{family}.py
   h. Write reference patches

3. Build cases_v2.json from all 45 case definitions

4. Run validate_cases.py on all 45

5. Run a single baseline experiment:
   runner.py --cases cases_v2.json --model gpt-4.1-nano --conditions baseline
   runner.py --cases cases_v2.json --model gpt-4o-mini --conditions baseline

6. Check calibration: do pass rates match expected bands?
   If not → adjust specific cases using calibration levers

7. Ship for full multi-condition + CGE experiment
```

### Estimated Output Size

- 45 case definitions in `cases_v2.json`
- ~90 code files (avg 2 per case) in `code_snippets_v2/`
- 15 test files in `tests_v2/`
- 45 reference patches in `reference_fixes/`
- 1 validation script
- ~3,000 lines of code total

---

## 12. Open Questions (To Resolve Before Implementation)

1. **Task prompt style**: Should all tasks use "Refactor for clarity" framing (like the existing cases), or should some use "Fix the bug" framing? The refactoring framing is a stronger test of causal reasoning but may be unfair for Level A.

2. **Reference fix format**: Should reference fixes be stored as `.patch` files (git-format-patch) or as separate Python files (the fixed version)?

3. **Integration with existing runner**: Should the new cases extend `cases.json` or use a separate `cases_v2.json`? Separate is cleaner but means updating runner.py to accept a `--cases` argument.

4. **Failure mode naming**: The existing system uses specific names like `HIDDEN_DEPENDENCY`. Should new families reuse these where applicable, or define a new taxonomy aligned with the 15 templates?

5. **How many distractors at Level C**: The existing hard cases have 3–4 distractor functions. Should this be standardized to exactly 3, or vary per family?
