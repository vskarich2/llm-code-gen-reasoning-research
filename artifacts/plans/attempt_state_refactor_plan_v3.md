# AttemptState Refactor — Plan v3 (refinement of v2)

## Changes from v2

Five targeted corrections. No architectural changes.

---

## 1. AttemptState field updates

```python
@dataclass
class AttemptState:
    # ... all v2 fields ...

    # ── Parsing semantics (CORRECTED) ──
    strict_parse_valid: bool = False
    recovery_parse_valid: bool = False     # was lenient_parse_valid
    parse_mode: str = "failed"             # "strict" | "recovered" | "failed"
    recovery_used: bool = False
    retry_eligible: bool = False

    # ── Execution provenance (NEW) ──
    execution_source: str = ""             # "strict" | "recovered"

    # ── Retry signal (NEW) ──
    retry_triggered: bool = False          # True when attempt_idx > 0
```

`lenient_parse_valid` is removed. The two independent signals are `strict_parse_valid` and `recovery_parse_valid`. No collapsing.

---

## 2. Updated stage_parse

```python
def stage_parse(state: AttemptState, case) -> None:
    state.strict_parse, state.recovery_parse, state.format_parse = (
        _parse_outputs(state.raw_response, state.condition))
    state.routing = _select_artifact(
        state.strict_parse, state.recovery_parse, case)
    state.parsed_gen = (
        state.recovery_parse
        if state.routing.selected_source == "recovery"
        else state.strict_parse)

    # ── Independent parse signals ──
    state.strict_parse_valid = (
        state.strict_parse.parse_valid
        and _validate_structure(state.strict_parse, case).structurally_valid
    )
    state.recovery_parse_valid = (
        state.recovery_parse.parse_valid
        and _validate_structure(state.recovery_parse, case).structurally_valid
    )

    # ── Derived ──
    if state.strict_parse_valid:
        state.parse_mode = "strict"
        state.execution_source = "strict"
    elif state.recovery_parse_valid:
        state.parse_mode = "recovered"
        state.execution_source = "recovered"
    else:
        state.parse_mode = "failed"
        state.execution_source = ""

    state.recovery_used = (state.routing.selected_source == "recovery")
    state.retry_eligible = (
        state.strict_parse_valid or state.recovery_parse_valid
    )
    state.retry_triggered = (state.attempt_idx > 0)
```

### Invariants

- `strict_parse_valid` and `recovery_parse_valid` are independent booleans — never collapsed
- `parse_mode == "strict"` iff `strict_parse_valid == True`
- `parse_mode == "recovered"` iff `strict_parse_valid == False AND recovery_parse_valid == True`
- `parse_mode == "failed"` iff both are False
- `execution_source` matches `parse_mode` (empty when failed — no execution runs)
- `retry_eligible` = either parser produced a usable artifact
- `retry_triggered` = this is not the first attempt

---

## 3. Updated retry loop

```python
for k in range(max_iterations):
    state = AttemptState(case_id=cid, condition=condition,
                         model=model, attempt_idx=k)

    # ... stages 1-8 ...

    trajectory.append(state)

    if state.passed:
        break

    # ── Retry eligibility gate ──
    if not state.retry_eligible:
        _log.warning(
            "RETRY_ABORT %s attempt %d: parse_mode=%s — "
            "not retryable", cid, k, state.parse_mode)
        break
```

`retry_triggered` is set by `stage_parse` from `attempt_idx > 0`. It doesn't gate anything — it's a signal for downstream analysis.

---

## 4. Updated event assembly

### New fields in `ev["reconstruction"]`

```python
"parse_mode": state.parse_mode,
"strict_parse_valid": state.strict_parse_valid,
"recovery_parse_valid": state.recovery_parse_valid,
"recovery_used": state.recovery_used,
"retry_eligible": state.retry_eligible,
"execution_source": state.execution_source,
"retry_triggered": state.retry_triggered,
```

7 fields added to existing reconstruction section. Nothing restructured.

### Per-attempt trajectory entries

Each entry includes all 7 fields from that attempt's state. Final attempt = last in trajectory, not best.

---

## 5. What the corrected signals enable

### Parsing matrix

| strict_valid | recovery_valid | parse_mode | count | exec_pass_rate |
|:---:|:---:|---|---:|---:|
| T | T | strict | 1100 | 86% |
| T | F | strict | 100 | 82% |
| F | T | recovered | 180 | 61% |
| F | F | failed | 60 | 0% |

Keeping strict and recovery as independent booleans shows whether recovery agrees with strict (row 1 vs row 2) and how much signal recovery alone contributes (row 3).

### Parsing × retry analysis

| parse_mode | execution_source | retry_triggered | count | pass_rate | improvement_rate |
|---|---|:---:|---:|---:|---:|
| strict | strict | no | 800 | 85% | — |
| strict | strict | yes | 400 | 72% | 31% |
| recovered | recovered | no | 60 | 61% | — |
| recovered | recovered | yes | 120 | 48% | 19% |
| failed | — | no | 60 | 0% | — |

`execution_source` confirms what artifact was actually executed, not just what was parsed. `retry_triggered` splits first attempts from retries without requiring chain-level joins.

### Retry conditional metrics

```
P(pass | execution_source=strict, retry_triggered)     = 72%
P(pass | execution_source=recovered, retry_triggered)  = 48%
degradation_rate(strict)                               = 2.1%
degradation_rate(recovered)                            = 5.4%
```

Answers: retry helps more on strict outputs; recovered outputs degrade more under retry.
