````markdown
# CLAUDE-SAFE PYTHON SPEC (v1.0)
# Enforces functional, testable, non-silent, non-stateful code generation

## 0. CORE PRINCIPLE

All code must be:
- Pure by default
- Explicit in state and data flow
- Fail-fast, never silent
- Deterministic and testable

No hidden state. No implicit behavior. No silent fallback.

---

## 1. STATE MANAGEMENT RULES

### 1.1 Forbidden
- Global variables (mutable or immutable)
- Module-level state (except constants)
- Hidden caches
- Mutable default arguments
- Implicit shared references

### 1.2 Required
- All state must be passed explicitly via function arguments
- All mutations must be returned, not performed in-place

BAD:
```python
cache = {}

def get(x):
    return cache.get(x)
````

GOOD:

```python
def get(cache: dict, x: str) -> tuple[dict, Any]:
    return cache, cache.get(x)
```

---

## 2. FUNCTION DESIGN

### 2.1 Constraints

* Max 40 lines per function
* Single responsibility ONLY
* No mixed concerns (I/O + logic + parsing)

### 2.2 Required structure

Each function must:

* Take explicit inputs
* Return explicit outputs
* Avoid side effects

---

## 3. ERROR HANDLING

### 3.1 Forbidden

* `except Exception: pass`
* `except Exception: <log only>`
* Silent fallback values
* Catching broad exceptions without re-raising

### 3.2 Required

* Catch specific exceptions ONLY
* Re-raise with context
* Fail fast on invariant violation

BAD:

```python
try:
    x = risky()
except Exception:
    return None
```

GOOD:

```python
try:
    x = risky()
except ValueError as e:
    raise RuntimeError(f"Invalid input: {e}") from e
```

---

## 4. DATA VALIDATION

### 4.1 Required

* Validate all external inputs
* Validate all LLM outputs
* Assert all invariants

BAD:

```python
return response.output_text
```

GOOD:

```python
if not hasattr(response, "output_text") or response.output_text is None:
    raise ValueError("Missing output_text in response")

return response.output_text
```

---

## 5. IMPORTS

### 5.1 Forbidden

* Imports inside functions
* Dynamic imports

### 5.2 Required

* All imports at top of file
* Dependencies must be explicit

---

## 6. SIDE EFFECTS

### 6.1 Forbidden

* Hidden side effects
* Implicit I/O
* Writing to global state

### 6.2 Required

* All side effects must be isolated
* Side effects must be in dedicated functions

---

## 7. PROMPT + STRING HANDLING

### 7.1 Forbidden

* Raw string concatenation for structured prompts

### 7.2 Required

* Use templates or structured builders
* Explicit delimiters

---

## 8. API CALLS

### 8.1 Required

* Timeout must be specified
* Retry logic must be explicit
* No silent retry

BAD:

```python
client.call(...)
```

GOOD:

```python
def call_with_retry(client, req, retries=2):
    for attempt in range(retries):
        try:
            return client.call(req, timeout=10)
        except TimeoutError:
            if attempt == retries - 1:
                raise
```

---

## 9. LOGGING

### 9.1 Forbidden

* Logging-only error handling
* Debug logs for failures

### 9.2 Required

* Logs must not replace control flow
* Critical failures must raise

---

## 10. DETERMINISM

### 10.1 Required

* No hidden randomness
* Seed must be explicit if used

---

## 11. TESTABILITY

### 11.1 Required

* All functions must be unit-testable
* No hidden dependencies
* No reliance on global environment

---

## 12. ANTI-PATTERN CHECKLIST (AUTO-REJECT)

Reject code if ANY present:

* global keyword
* mutable default args
* except Exception without re-raise
* import inside function
* implicit None returns
* function > 40 lines
* mixed responsibilities
* unvalidated external input
* silent fallback logic

---

## 13. DESIGN TARGET (ALIGNMENT WITH T3)

Code must avoid failure classes:

* hidden_dependency
* implicit_schema
* partial_state_update
* retry_state_accumulation
* silent_failure

These are explicitly represented in benchmark cases  and must be structurally prevented.

---

## 14. SYSTEM CONTEXT REQUIREMENT

This spec exists because the system:

* Separates execution vs reasoning correctness 
* Is vulnerable to silent infrastructure failures
* Requires strict observability and determinism

Therefore:

→ Crashes are preferable to silent degradation
→ Explicitness is mandatory
→ Functional style is enforced to eliminate hidden causal paths

---

## 15. SUMMARY RULE

If a reader cannot trace:

* where data comes from
* how state changes
* why a failure occurs

Then the code is INVALID.

```
