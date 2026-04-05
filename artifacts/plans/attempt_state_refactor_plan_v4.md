# AttemptState Refactor — Plan v4 (final refinement of v3)

## Changes from v3

Four targeted fixes. No architectural or scope changes.

---

## 1. execution_source assignment (FIXED)

v3 derived `execution_source` from `parse_mode`. Wrong — it must reflect what was actually executed, which is `routing.selected_source`.

```python
# In stage_parse, AFTER routing decision:
state.execution_source = state.routing.selected_source  # "strict" | "recovery" | "none"
```

This is correct when both strict and recovery are valid but routing picks strict — `execution_source` will be `"strict"` even though `recovery_parse_valid` is also True. The provenance tracks what ran, not what could have run.

---

## 2. retry_eligible comment (CLARIFIED)

```python
# retry_eligible = at least one executable artifact exists.
# If neither parser produced a structurally valid, schema-valid
# output that the reconstructor can consume, there is nothing
# to execute and retrying would waste an API call on the same
# format failure.
state.retry_eligible = (
    state.strict_parse_valid or state.recovery_parse_valid
)
```

No logic change. Comment added.

---

## 3. Parsing signal preservation note

`parse_mode` is a derived summary for display convenience. It is NOT the primary analysis signal. Dashboard analysis MUST use the two independent booleans:

- `strict_parse_valid` — did the strict parser produce a structurally valid artifact?
- `recovery_parse_valid` — did the recovery parser produce a structurally valid artifact?

These are independent. All four combinations are meaningful:

| strict | recovery | meaning |
|:---:|:---:|---|
| T | T | both valid (normal case, strict used) |
| T | F | strict valid, recovery failed (recovery parser bug or edge case) |
| F | T | strict failed, recovery saved it (the recovery value-add) |
| F | F | unrecoverable (nothing executable) |

`parse_mode` collapses the first two rows into "strict" and cannot distinguish them. Use the booleans.

---

## 4. Final attempt semantics (CONFIRMED)

Final attempt = last attempt in trajectory (index -1). This is the attempt that terminated the retry loop, whether by passing, hitting the retry eligibility gate, or exhausting max iterations.

There is no best-attempt selection. There is no re-scoring. The trajectory is an ordered list and the last entry is the final state.
