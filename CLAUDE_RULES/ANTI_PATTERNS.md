# ANTI_PATTERNS.md — HARD REJECTION RULES

Purpose:
Immediate rejection filter for known LLM failure modes.

If ANY pattern is present:
→ output is INVALID
→ must be regenerated or fixed

---

# AP-01 — Silent Failure

- `except:`
- `except Exception: pass`
- swallowing errors without re-raise
- returning default values on failure

---

# AP-02 — Hidden or Implicit State

- `global` keyword
- module-level mutable state
- hidden caches
- implicit shared mutation

---

# AP-03 — Unauthorized Caching

Forbidden unless explicitly requested:

- adding cache dictionaries
- memoization layers
- LRU caches
- storing computed results across calls

Rationale:
→ introduces hidden state and invalidates evaluation assumptions

---

# AP-04 — Unauthorized Concurrency

Forbidden unless explicitly requested:

- threading
- ThreadPoolExecutor
- async/await for parallelism

Rationale:
→ breaks determinism and execution model

---

# AP-05 — Mutable Default Arguments

- `def f(x=[])`
- `def f(x={})`

---

# AP-06 — Implicit or Fallback Behavior

- returning `None` without contract
- partial success returns
- fallback logic without explicit signaling

---

# AP-07 — Unvalidated External Input

- assuming structure of LLM output
- accessing dict fields without checks
- missing validation at boundaries

---

# AP-08 — Hidden Side Effects

- mutating inputs without documentation
- modifying shared objects implicitly

---

# USAGE

This file is a rejection filter.

Do NOT rationalize violations.
Do NOT “fix later.”

If triggered:
→ reject immediately