# Concurrency Cases — Full Specification

**Date:** 2026-03-24
**Scope:** Cases 5–8 of the Benchmark Extension Plan v3
**Design principle:** All concurrency is simulated via deterministic interleaving — no threads, no async, no randomness.

---

## Shared Infrastructure: The Stepper Model

All four cases use the same concurrency simulation pattern: operations are split into **steps** (plain functions), and a **runner** executes them in a controlled order.

```python
def run_steps(step_sequence):
    """Execute a list of (function, args) tuples in order.

    Each step is a regular function call. The step_sequence
    controls interleaving — no threads involved.
    """
    results = []
    for fn, args in step_sequence:
        results.append(fn(*args))
    return results
```

A "concurrent" scenario is just two operations whose steps are interleaved:

```python
# Sequential: A completes, then B completes
sequential = [(a_read, ()), (a_write, ()), (b_read, ()), (b_write, ())]

# Interleaved: A reads, B reads, A writes, B writes
interleaved = [(a_read, ()), (b_read, ()), (a_write, ()), (b_write, ())]
```

This makes every test deterministic and reproducible.

---

## Case 5: lost_update

**Category:** Concurrency | **Level:** L2 | **Pattern:** race_condition (read-modify-write)

### Code

```python
# counter.py
_value = 0

def reset():
    global _value
    _value = 0

def get():
    return _value

def read_then_increment():
    """Non-atomic read-modify-write. Returns (read_value, written_value)."""
    global _value
    current = _value       # READ
    new_val = current + 1  # MODIFY
    _value = new_val       # WRITE
    return (current, new_val)

def atomic_increment():
    """Atomic increment — correct implementation for reference."""
    global _value
    _value += 1
    return _value

# runner.py
def run_steps(steps):
    results = []
    for fn, args in steps:
        results.append(fn(*args))
    return results

def make_increment_steps():
    """Split read_then_increment into separate read and write steps."""
    captured = {}

    def step_read():
        captured["current"] = get()
        return ("read", captured["current"])

    def step_write():
        global _value
        import counter
        counter._value = captured["current"] + 1
        return ("write", captured["current"] + 1)

    return step_read, step_write

def sequential_double_increment():
    """Two increments, sequential: expect value=2."""
    reset()
    read_a, write_a = make_increment_steps()
    read_b, write_b = make_increment_steps()
    run_steps([(read_a, ()), (write_a, ()), (read_b, ()), (write_b, ())])
    return get()

def interleaved_double_increment():
    """Two increments, interleaved: BUG — both read 0, both write 1, value=1."""
    reset()
    read_a, write_a = make_increment_steps()
    read_b, write_b = make_increment_steps()
    run_steps([(read_a, ()), (read_b, ()), (write_a, ()), (write_b, ())])
    return get()
```

### Task

"Two concurrent increments of a counter produce value=1 instead of value=2 under interleaved execution. The sequential version works correctly. Fix `read_then_increment` (or the stepping model) so that the counter is correct under any interleaving."

### Deterministic Interleaving Model

```
Sequential:  A_read → A_write → B_read → B_write   → value=2 ✓
Interleaved: A_read → B_read  → A_write → B_write   → value=1 ✗
```

Both read `_value=0`. Both write `0+1=1`. The second write overwrites the first — a lost update.

### Hidden Causal Trap

The read and write are separate steps. Under interleaving, B's read happens before A's write, so B sees stale state. The fix must make read+write atomic (single step), not just "add a lock around write."

### Gold Reasoning

"Both operations read `_value=0` before either writes. B's write overwrites A's result. Fix: make the read-modify-write a single atomic step so that B reads AFTER A has written."

### EXPECTED_REASONING_HOOKS

- Must mention: both reads happen before either write (stale read)
- Must mention: the read and write must be atomic / combined into one step
- Must NOT propose: locking only the write (read still stale)

### EXPECTED_CAUSAL_RELATIONS

```
step_read() → captures _value into local state
step_write() → writes captured+1 to _value
interleaving → B's step_read() executes before A's step_write()
stale read → B's captured value is outdated → B's write overwrites A's
INVARIANT: after N increments, _value == N
```

### EXPECTED_CODE_ALIGNMENT

- `make_increment_steps()` or `read_then_increment()` must be changed so read+write is a single step
- OR: a guard/compare-and-swap mechanism prevents stale writes
- The step_read/step_write split must be eliminated or guarded

### TRACE_OUTPUT_FAILURE_CONDITION

- Reasoning says "make atomic" but code only locks the write step → **LEG_coupling** (correct reasoning, wrong fix scope)
- Reasoning says "stale read" but code adds a retry loop without atomicity → **LEG_execution** (retry doesn't fix the root cause)
- Reasoning says "add a check after write" → **false_fix** (detects but doesn't prevent)

### Tests

```python
def test(mod):
    # Test 1: sequential must produce 2
    seq_result = mod.sequential_double_increment()
    if seq_result != 2:
        return False, [f"sequential: expected 2, got {seq_result}"]

    # Test 2: interleaved must ALSO produce 2 (after fix)
    int_result = mod.interleaved_double_increment()
    if int_result != 2:
        return False, [f"interleaved: expected 2, got {int_result}"]

    return True, ["both sequential and interleaved produce correct count"]
```

---

## Case 6: check_then_act

**Category:** Concurrency | **Level:** L2 | **Pattern:** check_then_act

### Code

```python
# bank.py
_accounts = {}

def reset():
    _accounts.clear()

def create_account(name, balance):
    _accounts[name] = balance

def get_balance(name):
    return _accounts.get(name, 0)

def check_balance(name, amount):
    """CHECK: is balance sufficient? Returns True/False."""
    return _accounts.get(name, 0) >= amount

def do_withdraw(name, amount):
    """ACT: decrement balance. No check — assumes caller verified."""
    _accounts[name] = _accounts.get(name, 0) - amount

def safe_withdraw(name, amount):
    """Check-then-act (NOT atomic). Returns True if successful."""
    if check_balance(name, amount):  # CHECK
        do_withdraw(name, amount)     # ACT
        return True
    return False

# runner.py
def run_steps(steps):
    results = []
    for fn, args in steps:
        results.append(fn(*args))
    return results

def make_withdraw_steps(name, amount):
    """Split safe_withdraw into check and act steps."""
    result = {"approved": False}

    def step_check():
        result["approved"] = check_balance(name, amount)
        return ("check", result["approved"])

    def step_act():
        if result["approved"]:
            do_withdraw(name, amount)
        return ("act", result["approved"])

    return step_check, step_act

def sequential_withdrawals():
    """Two withdrawals of 80 from balance=100. Sequential: second denied."""
    reset()
    create_account("alice", 100)
    check_a, act_a = make_withdraw_steps("alice", 80)
    check_b, act_b = make_withdraw_steps("alice", 80)
    run_steps([(check_a, ()), (act_a, ()), (check_b, ()), (act_b, ())])
    return get_balance("alice")

def interleaved_withdrawals():
    """Two withdrawals of 80 from balance=100. Interleaved: both approved, overdraft."""
    reset()
    create_account("alice", 100)
    check_a, act_a = make_withdraw_steps("alice", 80)
    check_b, act_b = make_withdraw_steps("alice", 80)
    run_steps([(check_a, ()), (check_b, ()), (act_a, ()), (act_b, ())])
    return get_balance("alice")
```

### Task

"Under interleaved execution, two withdrawals of 80 from a balance of 100 both succeed, leaving balance at -60. The sequential version correctly denies the second withdrawal. Fix the withdrawal logic so balance never goes negative under any interleaving."

### Deterministic Interleaving Model

```
Sequential:  A_check(100≥80→T) → A_act(100-80=20) → B_check(20≥80→F) → B_act(skip)  → balance=20 ✓
Interleaved: A_check(100≥80→T) → B_check(100≥80→T) → A_act(100-80=20) → B_act(20-80=-60) → balance=-60 ✗
```

### Hidden Causal Trap

The check and act are separate steps. Both checks pass because neither withdrawal has occurred yet. The fix must make check+act atomic. Locking only the check doesn't help — both checks still pass sequentially, then both acts execute.

### Gold Reasoning

"Both withdrawals check balance=100 before either debits. Both pass. Both debit. Fix: the check and debit must be in the same atomic step. A check separated from its corresponding debit is vulnerable to interleaving."

### EXPECTED_REASONING_HOOKS

- Must mention: both checks see balance=100 because neither has debited yet
- Must mention: check and act must be atomic / combined into one step
- Must NOT propose: locking only the check step

### EXPECTED_CAUSAL_RELATIONS

```
check_balance() → reads _accounts[name] (point-in-time snapshot)
do_withdraw() → decrements _accounts[name]
interleaving → B's check reads balance BEFORE A's withdraw executes
stale check → B approved on outdated balance → overdraft
INVARIANT: _accounts[name] >= 0 at all times
```

### EXPECTED_CODE_ALIGNMENT

- `make_withdraw_steps` or `safe_withdraw` must combine check+act into a single step
- The act step must re-verify balance before decrementing
- OR: the step model must prevent interleaving between a check and its corresponding act

### TRACE_OUTPUT_FAILURE_CONDITION

- Reasoning says "make check+act atomic" but code locks only the check → **LEG_coupling**
- Reasoning correct, code re-checks balance in act step but with wrong comparison (`>` vs `>=`) → **LEG_execution**
- Reasoning says "add a balance floor in do_withdraw" → **false_fix** (prevents negative but allows silent failure — withdrawn amount is wrong)

### Tests

```python
def test(mod):
    # Test 1: sequential — second withdrawal denied, balance=20
    seq_balance = mod.sequential_withdrawals()
    if seq_balance != 20:
        return False, [f"sequential: expected balance=20, got {seq_balance}"]

    # Test 2: interleaved — must also prevent overdraft
    int_balance = mod.interleaved_withdrawals()
    if int_balance < 0:
        return False, [f"interleaved: balance went negative ({int_balance})"]
    # Exactly one withdrawal should succeed: balance should be 20
    if int_balance != 20:
        return False, [f"interleaved: expected balance=20, got {int_balance}"]

    return True, ["balance never goes negative under any interleaving"]
```

---

## Case 7: ordering_dependency

**Category:** Concurrency | **Level:** L2 | **Pattern:** ordering_dependency

### Code

```python
# pipeline.py
_log = []
_initialized = False

def reset():
    global _initialized
    _log.clear()
    _initialized = False

def init():
    global _initialized
    _initialized = True
    _log.append("init")

def process(item):
    """Must run AFTER init. Appends processed result."""
    if not _initialized:
        _log.append(f"error:not_init:{item}")
        return False
    _log.append(f"processed:{item}")
    return True

def shutdown():
    _log.append("shutdown")
    return list(_log)

def get_log():
    return list(_log)

# runner.py
def run_steps(steps):
    results = []
    for fn, args in steps:
        results.append(fn(*args))
    return results

def correct_order():
    """init → process(a) → process(b) → shutdown. Correct."""
    reset()
    run_steps([
        (init, ()),
        (process, ("a",)),
        (process, ("b",)),
        (shutdown, ()),
    ])
    return get_log()

def broken_order():
    """process(a) runs BEFORE init. Bug: ordering not enforced."""
    reset()
    run_steps([
        (process, ("a",)),  # runs before init — should fail or be deferred
        (init, ()),
        (process, ("b",)),
        (shutdown, ()),
    ])
    return get_log()
```

### Task

"Under certain execution orderings, `process()` runs before `init()` and fails. The current code logs an error but continues. Fix the pipeline so that processing is correct regardless of the order that `init` and `process` steps arrive — either by enforcing ordering or by deferring early process calls until after init."

### Deterministic Interleaving Model

```
Correct:  init → process(a) → process(b) → shutdown  → log: [init, processed:a, processed:b, shutdown] ✓
Broken:   process(a) → init → process(b) → shutdown   → log: [error:not_init:a, init, processed:b, shutdown] ✗
```

### Hidden Causal Trap

Models often "fix" this by adding a lock or mutex. But locks provide mutual exclusion, NOT ordering. Two operations can both acquire the same lock — they just can't hold it simultaneously. The actual fix requires either:
1. A barrier/gate: `process` waits until `init` has run
2. A queue: early `process` calls are buffered and replayed after `init`
3. Automatic init: `process` calls `init` if not yet initialized

### Gold Reasoning

"process() has an ordering dependency on init(). The `_initialized` flag detects violations but doesn't prevent or recover from them. Fix: either buffer early process calls and replay after init, or have process auto-initialize if needed."

### EXPECTED_REASONING_HOOKS

- Must mention: `process` depends on `init` having run first
- Must mention: the current code detects the violation but doesn't fix it
- Must mention: the fix must handle the case where process arrives before init
- Must NOT propose: adding a lock (locks don't enforce ordering)

### EXPECTED_CAUSAL_RELATIONS

```
init() → sets _initialized = True
process(item) → reads _initialized, requires True
ordering constraint: init must happen-before any process call
current code: detects violation (logs error) but does not defer or retry
INVARIANT: all items passed to process() must appear as "processed:{item}" in the log
```

### EXPECTED_CODE_ALIGNMENT

- `process()` must be modified to handle pre-init calls (buffer, auto-init, or block)
- OR: a new coordination mechanism (queue, gate) must be added
- The `_initialized` check must change from "log error and skip" to "defer and succeed"

### TRACE_OUTPUT_FAILURE_CONDITION

- Reasoning says "add ordering" but code adds a lock → **LEG_coupling** (locks ≠ ordering)
- Reasoning says "buffer early calls" but implementation has a bug (buffer never drained) → **LEG_execution**
- Reasoning says "call init() inside process()" — correct simple fix but may have re-entrancy issues → depends on implementation quality

### Tests

```python
def test(mod):
    # Test 1: correct order must work
    log_ok = mod.correct_order()
    if "error" in str(log_ok):
        return False, [f"correct order produced errors: {log_ok}"]
    if log_ok != ["init", "processed:a", "processed:b", "shutdown"]:
        return False, [f"correct order wrong log: {log_ok}"]

    # Test 2: broken order must ALSO produce correct results
    log_fix = mod.broken_order()
    processed = [e for e in log_fix if e.startswith("processed:")]
    if len(processed) != 2:
        return False, [f"broken order: expected 2 processed items, got {len(processed)}"]
    if "error" in str(log_fix):
        return False, [f"broken order still has errors: {log_fix}"]

    return True, ["pipeline handles out-of-order execution"]
```

---

## Case 8: false_fix_deadlock

**Category:** Concurrency | **Level:** L2 (deep) | **Pattern:** deadlock (lock ordering)

### Code

```python
# resources.py
_locks = {}
_state = {"A": 100, "B": 100}

def reset():
    _locks.clear()
    _state["A"] = 100
    _state["B"] = 100

def acquire(resource):
    """Simulate lock acquisition. Raises if already held."""
    if _locks.get(resource):
        raise RuntimeError(f"deadlock: {resource} already locked")
    _locks[resource] = True

def release(resource):
    _locks[resource] = False

def get_state():
    return dict(_state)

# transfers.py
def transfer_a_to_b(amount):
    """Lock A then B, transfer."""
    acquire("A")
    acquire("B")
    _state["A"] -= amount
    _state["B"] += amount
    release("B")
    release("A")
    return True

def transfer_b_to_a(amount):
    """BUG: Lock B then A — opposite order from transfer_a_to_b."""
    acquire("B")
    acquire("A")
    _state["B"] -= amount
    _state["A"] += amount
    release("A")
    release("B")
    return True

# runner.py
def run_steps(steps):
    results = []
    for fn, args in steps:
        results.append(fn(*args))
    return results

def make_transfer_steps(transfer_fn, amount):
    """Split a transfer into lock-acquire steps for interleaving."""
    state = {"phase": 0}

    def step_lock_first():
        # Acquire first lock
        if transfer_fn == transfer_a_to_b:
            acquire("A")
        else:
            acquire("B")
        state["phase"] = 1
        return "locked_first"

    def step_lock_second_and_transfer():
        # Acquire second lock + do transfer
        if transfer_fn == transfer_a_to_b:
            acquire("B")
            _state["A"] -= amount
            _state["B"] += amount
            release("B")
            release("A")
        else:
            acquire("A")
            _state["B"] -= amount
            _state["A"] += amount
            release("A")
            release("B")
        return "transferred"

    return step_lock_first, step_lock_second_and_transfer

def sequential_transfers():
    """A→B then B→A. Sequential: works fine."""
    reset()
    transfer_a_to_b(10)
    transfer_b_to_a(10)
    return get_state()

def interleaved_transfers():
    """A→B and B→A interleaved: deadlock."""
    reset()
    lock_ab, do_ab = make_transfer_steps(transfer_a_to_b, 10)
    lock_ba, do_ba = make_transfer_steps(transfer_b_to_a, 10)
    try:
        run_steps([
            (lock_ab, ()),   # A→B locks A
            (lock_ba, ()),   # B→A locks B
            (do_ab, ()),     # A→B tries to lock B — DEADLOCK (B held by B→A)
            (do_ba, ()),     # never reached
        ])
        return get_state()
    except RuntimeError as e:
        return {"error": str(e)}
```

### Task

"Concurrent transfers between accounts A and B deadlock when interleaved. `transfer_a_to_b` locks A then B; `transfer_b_to_a` locks B then A. Under interleaving, each holds one lock and waits for the other. Fix the transfer functions so they never deadlock under any interleaving."

### Deterministic Interleaving Model

```
Sequential:  lock_A → lock_B → transfer → unlock_B → unlock_A → lock_B → lock_A → transfer → unlock → balance correct ✓
Interleaved: A→B_locks_A → B→A_locks_B → A→B_tries_B(HELD!) → DEADLOCK ✗
```

### Hidden Causal Trap

The model must recognize that the deadlock is caused by **inconsistent lock ordering**: `transfer_a_to_b` acquires A then B, while `transfer_b_to_a` acquires B then A. The fix is to make BOTH functions acquire locks in the same order (always A before B, or always B before A).

Common wrong fixes:
- Remove all locking (introduces race conditions)
- Add a timeout (hides the deadlock, doesn't fix it)
- Use a single global lock (correct but over-serializes — loses all concurrency)

### Gold Reasoning

"Deadlock occurs because the two transfers acquire locks in opposite order, creating a circular wait. Fix: both functions must acquire locks in the same canonical order (e.g., always A before B). Change `transfer_b_to_a` to acquire A first, then B."

### EXPECTED_REASONING_HOOKS

- Must mention: opposite lock ordering as the cause of deadlock
- Must mention: consistent/canonical lock ordering as the fix
- Must NOT propose: removing locks (introduces races)
- Must NOT propose: timeout-based detection (hides bug)

### EXPECTED_CAUSAL_RELATIONS

```
transfer_a_to_b() → acquires A then B
transfer_b_to_a() → acquires B then A (OPPOSITE ORDER — CAUSE)
interleaving → each holds one lock, waits for the other → circular wait
INVARIANT: no circular lock dependency → no deadlock
FIX: both functions acquire in same order (A then B)
```

### EXPECTED_CODE_ALIGNMENT

- `transfer_b_to_a()` must change lock order from B→A to A→B
- `transfer_a_to_b()` should remain unchanged (it already uses the canonical order)
- The transfer logic inside `transfer_b_to_a` must still correctly move funds B→A despite acquiring A first

### TRACE_OUTPUT_FAILURE_CONDITION

- Reasoning says "fix lock ordering" but code removes locks entirely → **LEG_coupling** (correct diagnosis, wrong fix)
- Reasoning says "fix lock ordering" but code changes BOTH functions to B→A (still consistent, just different canonical order) → **correct** (either consistent order works)
- Reasoning says "add timeout" → **false_fix** (hides deadlock without fixing circular dependency)
- Reasoning says "use one global lock" → **over_serialization** (correct but loses concurrency granularity)

### Tests

```python
def test(mod):
    # Test 1: sequential transfers must work and conserve balance
    seq_state = mod.sequential_transfers()
    if "error" in seq_state:
        return False, [f"sequential deadlocked: {seq_state}"]
    total = seq_state.get("A", 0) + seq_state.get("B", 0)
    if total != 200:
        return False, [f"sequential: total={total}, expected 200"]

    # Test 2: interleaved transfers must NOT deadlock
    int_state = mod.interleaved_transfers()
    if "error" in int_state:
        return False, [f"interleaved deadlocked: {int_state['error']}"]
    total = int_state.get("A", 0) + int_state.get("B", 0)
    if total != 200:
        return False, [f"interleaved: total={total}, expected 200"]

    return True, ["no deadlock, balance conserved"]
```
