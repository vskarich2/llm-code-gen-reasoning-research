# AttemptState Refactor — Plan v2

## Changes from v1

v1 defined AttemptState and stage functions but left parsing semantics implicit (buried in RoutingDecision) and did not address retry eligibility. v2 adds:

1. Explicit canonical parsing fields on AttemptState
2. Retry eligibility gating
3. Per-attempt parsing provenance preserved through event assembly
4. Minimal event schema extension (5 fields added, nothing restructured)

Everything else from v1 is unchanged. This document covers ONLY the delta.

---

## 1. Updated AttemptState fields (additions only)

```python
@dataclass
class AttemptState:
    # ... all v1 fields unchanged ...
    
    # ── Canonical parsing semantics (NEW) ──
    strict_parse_valid: bool = False
    lenient_parse_valid: bool = False
    parse_mode: str = "failed"       # "strict" | "recovered" | "failed"
    recovery_used: bool = False
    retry_eligible: bool = False
```

These are NOT aliases for RoutingDecision fields. They are canonical, independently assigned in stage_parse. RoutingDecision still exists for internal routing logic — these fields are the measurement-facing semantics.

Derived (not stored, computed on read):

```python
is_recovered = (parse_mode == "recovered")
is_unrecoverable = (parse_mode == "failed")
```

---

## 2. Updated stage_parse (explicit assignment)

```python
def stage_parse(state: AttemptState, case) -> None:
    """Stage 2: Parse, route, and assign canonical parsing semantics."""
    state.strict_parse, state.recovery_parse, state.format_parse = (
        _parse_outputs(state.raw_response, state.condition))
    state.routing = _select_artifact(
        state.strict_parse, state.recovery_parse, case)
    state.parsed_gen = (
        state.recovery_parse
        if state.routing.selected_source == "recovery"
        else state.strict_parse)

    # ── Canonical parsing fields (explicit, not derived from routing) ──
    state.strict_parse_valid = (
        state.strict_parse.parse_valid
        and _validate_structure(state.strict_parse, case).structurally_valid
    )
    state.lenient_parse_valid = (
        state.strict_parse_valid
        or (
            state.recovery_parse.parse_valid
            and _validate_structure(state.recovery_parse, case).structurally_valid
        )
    )

    if state.strict_parse_valid:
        state.parse_mode = "strict"
    elif state.lenient_parse_valid:
        state.parse_mode = "recovered"
    else:
        state.parse_mode = "failed"

    state.recovery_used = (state.routing.selected_source == "recovery")
    state.retry_eligible = state.lenient_parse_valid
```

### Invariants enforced by this assignment:

- `strict_parse_valid == True` implies `lenient_parse_valid == True` (strict is a subset of lenient)
- `parse_mode == "strict"` implies `strict_parse_valid == True`
- `parse_mode == "recovered"` implies `strict_parse_valid == False AND lenient_parse_valid == True`
- `parse_mode == "failed"` implies `lenient_parse_valid == False`
- `recovery_used == True` implies `parse_mode == "recovered"`
- `retry_eligible == True` iff `lenient_parse_valid == True`

---

## 3. Updated retry loop (eligibility gating)

```python
def run_retry_v2(case, model, condition, logger, ...):
    trajectory: list[AttemptState] = []

    for k in range(max_iterations):
        if elapsed > max_total_seconds:
            break

        state = AttemptState(
            case_id=cid, condition=condition, model=model, attempt_idx=k)

        # Stage 1: Generate
        if k == 0:
            stage_generate(state, case, config, logger)
        else:
            state.prompt = _build_retry_prompt(k, trajectory[k-1], ...)
            state.raw_response, state.gen_event_id = _call_generation_model(...)

        # Stages 2-8
        stage_parse(state, case)
        stage_oracle(state, case, config, logger)
        stage_normalize(state, case)
        stage_reconstruct(state, case, config)
        stage_classify(state, case, config, logger)
        stage_ast(state, case)
        stage_execute(state, case, config, logger)
        stage_derive_metrics(state, config)

        trajectory.append(state)

        if state.passed:
            break

        # ── RETRY ELIGIBILITY GATE (NEW) ──
        if not state.retry_eligible:
            _log.warning(
                "RETRY_ABORT %s attempt %d: parse_mode=%s, "
                "lenient_parse_valid=False — nothing to retry",
                cid, k, state.parse_mode)
            break

    ev = assemble_retry_event_from_trajectory(trajectory, case, ...)
    return cid, condition, ev
```

The gate fires AFTER the attempt completes (so the failed attempt is recorded in the trajectory) but BEFORE the next iteration starts. This means:

- Unrecoverable parse failures are recorded as attempts (for metrics)
- But they don't trigger a wasted API call for the next attempt
- The trajectory faithfully shows what happened, including the stop reason

---

## 4. Updated event assembly (new fields)

### Single-shot event (execution_v2)

In `assemble_event_from_state(state)`, add to the reconstruction section:

```python
ev["reconstruction"]["parse_mode"] = state.parse_mode
ev["reconstruction"]["strict_parse_valid"] = state.strict_parse_valid
ev["reconstruction"]["lenient_parse_valid"] = state.lenient_parse_valid
ev["reconstruction"]["recovery_used"] = state.recovery_used
ev["reconstruction"]["retry_eligible"] = state.retry_eligible
```

These go in the existing `ev["reconstruction"]` dict alongside `parsing_mode`, `execution_eligible`, etc. No new top-level sections.

### Retry event

`assemble_retry_event_from_trajectory(trajectory)` builds `ev["reconstruction"]` from `trajectory[-1]` (the best/final attempt), which is an AttemptState with all fields populated. Same 5 fields are included.

Additionally, each trajectory entry in the event's `payload.trajectory` array includes:

```python
{
    "attempt": state.attempt_idx,
    "parse_mode": state.parse_mode,
    "strict_parse_valid": state.strict_parse_valid,
    "lenient_parse_valid": state.lenient_parse_valid,
    "recovery_used": state.recovery_used,
    "retry_eligible": state.retry_eligible,
    "execution": { ... },
    "oracle": { ... },
    "classifier": { ... },
    ...
}
```

Per-attempt parsing state is preserved because the trajectory IS a list of AttemptState objects.

---

## 5. Dashboard schema additions (5 fields)

In `dashboard/schema.py`, add to FIELD_REGISTRY:

```python
"parse_mode": {
    "source": "extra.reconstruction.parse_mode",
    "type": "str",
    "required": False,
},
"strict_parse_valid": {
    "source": "extra.reconstruction.strict_parse_valid",
    "type": "bool",
    "required": False,
},
"lenient_parse_valid": {
    "source": "extra.reconstruction.lenient_parse_valid",
    "type": "bool",
    "required": False,
},
"recovery_used": {
    "source": "extra.reconstruction.recovery_used",
    "type": "bool",
    "required": False,
},
"retry_eligible": {
    "source": "extra.reconstruction.retry_eligible",
    "type": "bool",
    "required": False,
},
```

These already exist partially (`strict_parse_valid`, `recovery_parse_valid`, `recovery_used` are in the current schema). `parse_mode`, `lenient_parse_valid`, and `retry_eligible` are new. `recovery_parse_valid` becomes `lenient_parse_valid` for clarity (both names kept for backward compat).

---

## 6. Dashboard scanner per-attempt extraction

In `leg_scanner.py`, when extracting per-attempt rows from trajectory entries, add:

```python
row["parse_mode"] = t_entry.get("parse_mode", None)
row["strict_parse_valid"] = t_entry.get("strict_parse_valid", None)
row["lenient_parse_valid"] = t_entry.get("lenient_parse_valid", None)
row["recovery_used"] = t_entry.get("recovery_used", None)
row["retry_eligible"] = t_entry.get("retry_eligible", None)
```

This replaces the current behavior where all attempts inherit the best-attempt's parse state.

---

## 7. What this enables

### Parsing matrix (group by model × condition)

| parse_mode | count | exec_pass_rate | leg_rate |
|------------|-------|----------------|----------|
| strict     | 1200  | 85.2%          | 4.1%     |
| recovered  | 180   | 61.3%          | 8.7%     |
| failed     | 60    | 0.0%           | 0.0%     |

Answers: how much of our pass rate comes from recovered outputs?

### Parsing × retry matrix (group by model × condition)

| parse_mode | retry_eligible | retried | count | pass_rate |
|------------|----------------|---------|-------|-----------|
| strict     | yes            | yes     | 400   | 72.1%     |
| strict     | yes            | no      | 800   | 85.2%     |
| recovered  | yes            | yes     | 120   | 48.3%     |
| recovered  | yes            | no      | 60    | 61.3%     |
| failed     | no             | no      | 60    | 0.0%      |

Answers: is retry effective for recovered outputs? Are we wasting retries on unrecoverable failures?

### Retry conditional analysis

```
P(pass | strict, retried)     = 72.1%
P(pass | recovered, retried)  = 48.3%
improvement_rate(strict)      = 31.2%
improvement_rate(recovered)   = 18.7%
degradation_rate(strict)      = 2.1%
degradation_rate(recovered)   = 5.4%
```

Answers: does retry help more for strict or recovered outputs? Does recovery + retry degrade more often?

### Failure decomposition split

Current "Parse Failure" card becomes three values:
- Strict failures (recovered downstream): X%
- Unrecoverable parse failures: Y%
- Both fail = true pipeline dead-end: Z%

---

## 8. Implementation order

1. Create `attempt_state.py` with AttemptState including the 5 new parsing fields
2. Extract stage functions from execution_v2 (v1 plan, no change)
3. Implement explicit parsing assignment in `stage_parse` (this plan, section 2)
4. Rewrite `run_v2` to use stage functions + AttemptState (v1 plan)
5. Rewrite `retry_v2` to use stage functions + eligibility gate (this plan, section 3)
6. Update event assembly to include new fields (this plan, section 4)
7. Add schema entries (this plan, section 5)
8. Update scanner extraction (this plan, section 6)
9. Tests: verify invariants, verify retry stops on unrecoverable, verify per-attempt fields preserved

---

## 9. What this does NOT do

- Does NOT change parser logic (strict/recovery parsers unchanged)
- Does NOT change reconstructor logic
- Does NOT change classifier or executor
- Does NOT change prompt templates
- Does NOT introduce policy systems or complex retry strategies
- Does NOT restructure existing event fields (only adds 5 new ones)
- Does NOT require dashboard redesign (new fields enable new views but existing views work unchanged)
