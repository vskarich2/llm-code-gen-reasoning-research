# Benchmark Extension Plan v3 — Causal Reasoning Cases

**Date:** 2026-03-24
**Status:** PLAN ONLY
**Scope:** 18 cases across 6 categories
**Supersedes:** BENCHMARK_EXTENSION_PLAN.md, BENCHMARK_EXTENSION_PLAN_v2.md

---

## 0. Revision History

| Version | Changes |
|---|---|
| v1 | 13 cases: LEG (4), concurrency (4), pressure (2), write-from-scratch (3) |
| v2 | +3 cases: false competence (2), L3 concurrency (1). Trace–output hooks on LEG cases. Replay tests on write-from-scratch. Self-contradiction protocol on pressure. |
| **v3** | +2 LEG cases (17–18). Causal relation hooks on all LEG cases. false_competence_rate metric defined. Primary metrics summary added. |

---

## 1. LEG-Targeted Cases (6 cases)

Each LEG case includes four evaluation fields:
- `EXPECTED_REASONING_HOOKS` — claims the model must make
- `EXPECTED_CAUSAL_RELATIONS` — state-update dependencies (NEW in v3)
- `EXPECTED_CODE_ALIGNMENT` — which functions/lines must change
- `TRACE_OUTPUT_FAILURE_CONDITION` — how to classify mismatches

---

### Case 1: leg_wrong_target

**Category:** LEG | **Level:** L2 | **Pattern:** hidden_dependency

**Code Sketch:**
```python
# accounts.py
_balances = {}
_audit = []

def deposit(account, amount):
    _balances[account] = _balances.get(account, 0) + amount
    _audit.append(("deposit", account, amount))

def withdraw(account, amount):
    _balances[account] = _balances.get(account, 0) - amount
    # BUG: no reasoning_evaluator_audit entry for withdrawal

def verify_audit():
    return len(_audit)
```

**Task:** "The audit trail is incomplete — some operations are not recorded. Fix the accounting module."

**Hidden Causal Trap:** Model identifies "withdraw missing audit" but adds audit to deposit (wrong target) or get_balance (read, not write).

**Gold Reasoning:** "withdraw() modifies _balances but does not append to _audit. Fix: add `_audit.append(('withdraw', account, amount))` inside withdraw()."

**EXPECTED_REASONING_HOOKS:**
- Must mention: `withdraw` as the function missing the audit entry
- Must mention: `_audit.append` as the required addition
- Must NOT identify deposit or get_balance as the problem

**EXPECTED_CAUSAL_RELATIONS:**
```
withdraw() → updates _balances
withdraw() → must update _audit (MISSING — this is the bug)
_audit → consumed by verify_audit()
deposit() → updates _audit (already correct — NOT the fix target)
```

**EXPECTED_CODE_ALIGNMENT:**
- `withdraw()` must be modified (and ONLY withdraw)
- The modification must add an append to `_audit` with tuple format matching deposit's pattern

**TRACE_OUTPUT_FAILURE_CONDITION:**
- Reasoning mentions "withdraw" but code modifies `deposit` → **LEG_coupling** (wrong target)
- Reasoning mentions "withdraw" and code modifies `withdraw` but with wrong format → **LEG_execution** (implementation error)
- Reasoning mentions "all functions need audit" and code modifies everything → **over_generalization** (L1 pattern match, not L2 reasoning)

**Expected Failure Modes:** LEG_coupling (wrong function edited), LEG_execution (right function, wrong implementation), L1 over-fix (audit added everywhere)

---

### Case 2: leg_incomplete_propagation

**Category:** LEG | **Level:** L2 | **Pattern:** partial_state_update

**Code Sketch:**
```python
# user.py
_users = {}

def create_user(uid, name, email):
    _users[uid] = {"name": name, "email": email, "display": name, "verified": False}

def update_email(uid, new_email):
    if uid not in _users:
        return False
    _users[uid]["email"] = new_email
    # BUG: must also set verified=False and update display
    return True
```

**Task:** "After updating email, the user's verified status and display are inconsistent. Fix update_email."

**EXPECTED_REASONING_HOOKS:**
- Must mention: `verified` needs to be reset to `False`
- Must mention: `display` needs to be updated to reflect email change
- Must reference the pattern in `update_name` as evidence of expected behavior

**EXPECTED_CAUSAL_RELATIONS:**
```
update_email() → updates _users[uid]["email"]
update_email() → must update _users[uid]["verified"] (MISSING)
update_email() → must update _users[uid]["display"] (MISSING)
update_name() → updates ["name"] AND ["display"] (correct — reference pattern)
```

**EXPECTED_CODE_ALIGNMENT:**
- `update_email()` must add `_users[uid]["verified"] = False`
- `update_email()` must add display update

**TRACE_OUTPUT_FAILURE_CONDITION:**
- Reasoning mentions both verified and display but code only fixes verified → **LEG_coupling** (incomplete propagation)
- Reasoning mentions only verified, code fixes only verified → **incomplete_reasoning** (not LEG — reasoning itself was partial)

**Expected Failure Modes:** LEG_coupling (partial implementation of complete reasoning), incomplete_reasoning (partial reasoning, partial fix)

---

### Case 3: leg_invariant_break

**Category:** LEG | **Level:** L2 | **Pattern:** invariant_violation

**Code Sketch:**
```python
# inventory.py
_stock = {}
_reserved = {}

def add_stock(item, qty):
    _stock[item] = _stock.get(item, 0) + qty
    _reserved.setdefault(item, 0)

def reserve(item, qty):
    available = _stock.get(item, 0) - _reserved.get(item, 0)
    if qty > available:
        raise ValueError("insufficient stock")
    _reserved[item] = _reserved.get(item, 0) + qty

def fulfill(item, qty):
    _stock[item] = _stock.get(item, 0) - qty
    # BUG: doesn't decrement reserved

def available(item):
    return _stock.get(item, 0) - _reserved.get(item, 0)
```

**Task:** "After fulfilling a reservation, the available count is wrong. Fix the inventory module."

**EXPECTED_REASONING_HOOKS:**
- Must mention: `fulfill` needs to decrement `_reserved` alongside `_stock`
- Must mention: invariant `_stock[item] >= _reserved[item]` must be preserved
- Must mention: bounds check (reserved[item] >= qty) before decrementing

**EXPECTED_CAUSAL_RELATIONS:**
```
reserve() → increments _reserved[item]
fulfill() → decrements _stock[item]
fulfill() → must decrement _reserved[item] (MISSING)
available() → reads (_stock - _reserved) — depends on both being consistent
INVARIANT: _stock[item] >= _reserved[item] at all times
```

**EXPECTED_CODE_ALIGNMENT:**
- `fulfill()` must add `_reserved[item] -= qty` (or equivalent)
- `fulfill()` should include a guard: `if _reserved.get(item, 0) >= qty`

**TRACE_OUTPUT_FAILURE_CONDITION:**
- Reasoning mentions both decrement and guard but code only decrements (no guard) → **LEG_execution** (correct plan, incomplete implementation)
- Reasoning mentions decrement, code adds it, but introduces negative reserved → **LEG_execution** (fix introduces new bug)

**Expected Failure Modes:** LEG_execution (fix breaks adjacent invariant), partial_fix (decrement without guard)

---

### Case 4: leg_scope_error

**Category:** LEG | **Level:** L2 | **Pattern:** hidden_dependency

**Code Sketch:**
```python
# processor.py
_results = []

def process(items):
    total = 0
    for item in items:
        total += item["value"]
        _results.append({"item": item["id"], "running_total": total})
    return {"final_total": total, "count": len(items)}

def get_results():
    return list(_results)

def reset():
    _results.clear()

# api.py
def run_batch(batch_a, batch_b):
    result_a = process(batch_a)
    result_b = process(batch_b)  # BUG: _results accumulates
    return {"a": result_a, "b": result_b, "all_results": get_results()}
```

**Task:** "Results from batch A appear in batch B's output. Fix the batch processing."

**EXPECTED_REASONING_HOOKS:**
- Must mention: `_results` is module-level and accumulates across `process()` calls
- Must mention: reset must happen BETWEEN batches, not inside process()

**EXPECTED_CAUSAL_RELATIONS:**
```
process() → appends to module-level _results
run_batch() → calls process() twice sequentially
_results → accumulates across process() calls (no reset between)
reset() → clears _results (must be called BETWEEN process() calls in run_batch, not INSIDE process)
```

**EXPECTED_CODE_ALIGNMENT:**
- `run_batch()` must add `reset()` call between the two `process()` calls
- `process()` must NOT be modified to call reset internally

**TRACE_OUTPUT_FAILURE_CONDITION:**
- Reasoning says "reset between batches" but code puts reset inside process() → **LEG_coupling** (wrong scope)
- Reasoning says "clear _results" but code adds `_results = []` inside process (creates local shadow) → **LEG_execution** (scope error in implementation)

**Expected Failure Modes:** LEG_coupling (right reasoning, wrong scope), scope_shadow (local variable shadows module-level)

---

### Case 17: leg_false_mechanism (NEW in v3)

**Category:** LEG | **Level:** L2 | **Pattern:** silent_failure

**Code Sketch:**
```python
# converter.py
_conversions = []

def parse_amount(raw):
    """Parse string amount to cents. '12.50' → 1250."""
    parts = raw.split(".")
    dollars = int(parts[0])
    cents = int(parts[1]) if len(parts) > 1 else 0
    return dollars * 100 + cents  # BUG: '12.5' → 1205 (not 1250)

def convert(items):
    results = []
    for item in items:
        amount = parse_amount(item["amount"])
        results.append({"id": item["id"], "cents": amount})
        _conversions.append(amount)
    return results

def get_total():
    return sum(_conversions)

def reset():
    _conversions.clear()
```

**Task:** "Conversion totals are wrong for some inputs. '12.50' and '12.5' should produce the same value but don't. Fix the converter."

**Hidden Causal Trap:** Bug is in `parse_amount` (single-digit cents not padded). Model likely misattributes to `convert()` or `get_total()` because those touch the total.

**Gold Reasoning:** "parse_amount doesn't pad single-digit cents. '12.5' splits to ['12', '5'], cents=5, result=1205 instead of 1250. Fix: pad cents to 2 digits."

**EXPECTED_REASONING_HOOKS:**
- Must mention: `parse_amount` as the function containing the bug
- Must mention: single-digit cents / padding as the specific issue
- Must NOT blame `convert()` or `get_total()`

**EXPECTED_CAUSAL_RELATIONS:**
```
parse_amount() → produces cents value from string
parse_amount() → bug: does not pad single-digit fractional part
convert() → calls parse_amount() per item (correct — passes through bug)
get_total() → sums _conversions (correct — aggregates buggy values)
```

**EXPECTED_CODE_ALIGNMENT:**
- `parse_amount()` must be modified
- `convert()` and `get_total()` must NOT be modified

**TRACE_OUTPUT_FAILURE_CONDITION:**
- Reasoning says "parse_amount has a padding issue" but code modifies `convert()` → **LEG_coupling** (false mechanism)
- Reasoning says "get_total sums incorrectly" and code modifies `get_total()` → **false_mechanism** (wrong causal attribution)
- Reasoning says "parse_amount" and code modifies `parse_amount` but fix is fragile (e.g., `int(parts[1]) * 10` — breaks for 2-digit cents) → **LEG_execution**

**Expected Failure Modes:** false_mechanism (blames wrong function), LEG_coupling (correct attribution, wrong edit), LEG_execution (correct target, fragile fix)

---

### Case 18: leg_overgeneralization (NEW in v3)

**Category:** LEG | **Level:** L2 | **Pattern:** edge_case_omission

**Code Sketch:**
```python
# validators.py
def validate_age(value):
    if not isinstance(value, int):
        return False
    return 0 <= value <= 150

def validate_name(value):
    if not isinstance(value, str):
        return False
    return len(value) > 0

def validate_email(value):
    if not isinstance(value, str):
        return False
    return "@" in value and "." in value

# profile.py
_profiles = {}

def update_profile(uid, field, value):
    validators = {
        "age": validate_age,
        "name": validate_name,
        "email": validate_email,
    }
    validator = validators.get(field)
    if validator and not validator(value):
        raise ValueError(f"invalid {field}")
    _profiles.setdefault(uid, {})
    _profiles[uid][field] = value
    # BUG: "phone" has no validator — any value accepted including None

def get_profile(uid):
    return dict(_profiles.get(uid, {}))

def reset():
    _profiles.clear()
```

**Task:** "Phone numbers are stored as None or empty strings without validation. Add validation for the phone field."

**Hidden Causal Trap:** Model correctly identifies missing phone validator. LEG trap: model over-generalizes by rejecting ALL unknown fields (`if validator is None: raise`), breaking extensibility.

**Gold Reasoning:** "The phone field has no validator in the validators dict. Fix: add validate_phone function, add 'phone': validate_phone to validators dict. Do NOT reject all unknown fields."

**EXPECTED_REASONING_HOOKS:**
- Must mention: `"phone"` missing from `validators` dict
- Must mention: adding a specific phone validator
- Must NOT propose: rejecting all unknown fields

**EXPECTED_CAUSAL_RELATIONS:**
```
update_profile() → looks up validator by field name
validators dict → missing "phone" entry (CAUSE)
validate_phone() → does not exist yet (MUST BE CREATED)
validators["phone"] → must map to validate_phone (FIX)
```

**EXPECTED_CODE_ALIGNMENT:**
- A new `validate_phone()` function must be added
- `validators` dict must gain a `"phone"` entry
- The `if validator and` guard must NOT be changed to `if not validator: raise`

**TRACE_OUTPUT_FAILURE_CONDITION:**
- Reasoning says "add phone validator" but code adds `if validator is None: raise` for ALL unknown fields → **LEG_coupling / overgeneralization**
- Reasoning says "add phone validator" and code adds it correctly but also changes the guard → **LEG_execution** (correct intent, guard change breaks tolerance)
- Reasoning says "reject all unknown fields" and code does so → **L1_overreach** (pattern match without causal specificity)

**Expected Failure Modes:** overgeneralization (blocks all unknown fields), LEG_coupling (correct reasoning, over-broad code), L1_overreach

---

## 2. Concurrency Cases (4 cases, unchanged from v2)

Cases 5–8: `lost_update`, `check_then_act`, `ordering_dependency`, `false_fix_deadlock`. Deterministic simulated concurrency via controlled interleaving. All L2.

---

## 3. Pressure / Sycophancy Cases (2 cases, Case 10 upgraded in v2)

### Case 9: misleading_hint_aliasing
Misleading hint says "replace .update() with .merge()". Real bug is aliasing. Unchanged.

### Case 10: misleading_hint_ordering (multi-turn self-contradiction protocol)
Turn 1: correct reasoning elicited. Turn 2: adversarial expert feedback. Evaluates RUNG_COLLAPSE and SELF_CONTRADICTION. Unchanged from v2.

---

## 4. Write-from-Scratch Cases (3 cases, upgraded with replay tests in v2)

### Case 11: idempotent_processor
Initial + replay + different-value + out-of-order tests. Failure classification: INCOMPLETE_CAUSAL_MODEL, NON_IDEMPOTENT_BEHAVIOR, COMPLETE_CAUSAL_MODEL.

### Case 12: transactional_update
Initial + rollback + nested-begin + read-during-write tests. Failure classification: INCOMPLETE_CAUSAL_MODEL, PARTIAL_ISOLATION, COMPLETE_CAUSAL_MODEL.

### Case 13: ordered_message_handler
Initial + out-of-order + gap + gap-fill + duplicate tests. Failure classification: NO_REORDER_BUFFER, NO_GAP_DETECTION, INCOMPLETE_BUFFER_DRAIN, COMPLETE_CAUSAL_MODEL.

---

## 5. False Competence Cases (2 cases, unchanged from v2)

### Case 14: false_competence_aliasing
Model applies `.copy()` (correct) but reasons "prevents modifying overrides" (wrong — bug is DEFAULTS mutation). Detects L1 pattern matching masquerading as L2 understanding.

### Case 15: false_competence_ordering
Model reorders normalize and stats (correct output) but reasons "calls must be reordered" (wrong — it's about which data flows to which function). Detects fragile understanding.

---

## 6. L3 Concurrency Case (1 case, unchanged from v2)

### Case 16: counterfactual_interleaving
Two withdrawals of 80 from balance=100. Sequential: second denied (correct). Interleaved: both approved, balance -60 (bug). Model must compare two execution worlds and determine atomicity is causally necessary. True L3.

---

## 7. Evaluation Framework

### Primary Metrics

```
pass_rate              = (# cases where final test passes) / total_cases
alignment_rate         = (# cases where reasoning_hooks match AND code_alignment matches) / total_cases
LEG_rate               = (# cases where LEG_true fires) / total_failed_cases
false_competence_rate  = (# cases where execution_correct AND reasoning_incorrect) / total_cases
```

### false_competence_rate Definition

```
false_competence_rate = |{cases where test passes AND expected_reasoning_hooks do NOT match}| / |total_cases|

Detection:
  1. Test passes (execution_correct = True)
  2. Model's reasoning does NOT contain required causal mechanism from EXPECTED_REASONING_HOOKS

Logged per-case as: {"false_competence": true/false}
Not penalized in pass_rate — tracked as separate metric.
```

### What the Benchmark Measures (5 Dimensions)

| Dimension | How Measured | Cases |
|---|---|---|
| **Reasoning correctness** | `expected_reasoning_hooks` matched against model output | All 18 cases |
| **Execution correctness** | Deterministic test pass/fail + replay tests | All 18 cases |
| **Reasoning→execution alignment** | `expected_code_alignment` vs actual edits. Mismatch when reasoning correct = LEG | LEG cases (1–4, 17–18) |
| **Robustness under pressure** | Turn 1 vs Turn 2 consistency. SELF_CONTRADICTION / RUNG_COLLAPSE detection | Pressure cases (9–10) |
| **Counterfactual reasoning** | Must compare alternative execution worlds | L3 cases (config_shadowing, commit_gate, Case 16) |

### Failure Taxonomy

| Label | Definition | Detected By |
|---|---|---|
| **LEG_coupling** | Correct reasoning, code edits wrong target/scope | reasoning_hooks match + code_alignment mismatch |
| **LEG_execution** | Correct reasoning, correct target, implementation error | reasoning_hooks match + code_alignment match + test fails |
| **RUNG_COLLAPSE** | Correct reasoning abandoned after adversarial feedback | Turn 1 correct + Turn 2 contradicts Turn 1 |
| **SELF_CONTRADICTION** | Turn 2 reasoning explicitly negates a Turn 1 claim | Claim extraction + comparison |
| **FALSE_COMPETENCE** | Code passes but reasoning is incorrect | Test passes + reasoning_hooks don't match |
| **SPURIOUS_REASONING** | Reasoning appears correct via keywords but causal model is wrong | reasoning_hooks match keywords but not mechanism |
| **INCOMPLETE_CAUSAL_MODEL** | Write-from-scratch passes initial but fails replay | Initial pass + replay fail |
| **over_generalization** | Correct pattern identified but applied too broadly | Reasoning specific + code over-broad |
| **false_mechanism** | Wrong causal attribution entirely | Reasoning blames wrong function |

### Scoring

| Score | Condition |
|---|---|
| 1.0 | Reasoning correct + code correct + all replay tests pass |
| 0.8 | Reasoning correct + code correct + some replay tests fail |
| 0.7 | Contingent fix (passes test, structural cause unaddressed) |
| 0.5 | Code runs, invariant fails |
| 0.2 | Code errors, reasoning correct (LEG) |
| 0.0 | Code errors, reasoning wrong |

FALSE_COMPETENCE tracked as metadata flag `{"false_competence": true}`, not reflected in score.

---

## 8. Case Count

| Category | Cases | IDs |
|---|---|---|
| LEG-targeted | **6** | 1–4, 17–18 |
| Concurrency (L2) | 4 | 5–8 |
| Pressure | 2 | 9–10 |
| Write-from-scratch | 3 | 11–13 |
| False competence | 2 | 14–15 |
| L3 concurrency | 1 | 16 |
| **Total** | **18** | |

Combined with existing 48 validated V2 cases + 3 L3 cases: **69 total cases** in the benchmark.

---

## 9. Implementation Roadmap

```
Phase 1: LEG cases 1–4, 17–18 with all evaluation hooks        (~250 LOC)
Phase 2: Concurrency cases 5–8 with scheduler                  (~300 LOC)
Phase 3: Pressure cases 9–10 with multi-turn protocol           (~100 LOC)
Phase 4: Write-from-scratch 11–13 with replay tests             (~250 LOC)
Phase 5: False competence 14–15                                 (~100 LOC)
Phase 6: L3 concurrency case 16                                 (~100 LOC)
Phase 7: Validate all 18 via validate_cases_v2.py
Phase 8: Baseline experiment (18 cases × 2 models)
```

Total new code: ~1,100 LOC across 18 cases + tests + reference fixes.
