# Architectural Path Audit: Logic Duplication and Path Divergence

**Date:** 2026-03-26
**Status:** PLAN ONLY. No implementation.

---

## 1. EXECUTION PATH MAP

### 1.1 Entry Point: `_run_one_inner` (runner.py:195)

All model evaluation flows through this single dispatcher:

```
_run_one_inner(case, model, condition)
  │
  ├─ condition == "repair_loop"     → run_repair_loop(case, model)
  ├─ condition == "contract_gated"  → run_contract_gated(case, model)
  ├─ condition in RETRY_CONDITIONS  → run_retry_harness(case, model, ...)
  ├─ condition == "leg_reduction"   → run_leg_reduction(case, model)
  └─ all others                     → run_single(case, model, condition)
```

### 1.2 Per-Path Call Chains

**Path A: run_single (25 standard conditions)**
```
run_single
  → _attempt_and_evaluate                    ← CANONICAL PIPELINE
    → call_model
    → parse_model_response → _build_parsed_response
    → reconstruct_strict (if file_dict)
    → [Phase 1 observability computation]     ← PRESENT
    → evaluate_output → exec_evaluate
    → [failure_source attribution]            ← PRESENT
  → write_log
  → _emit_metrics_event
```

**Path B: run_repair_loop (1 condition)**
```
run_repair_loop
  → _attempt_and_evaluate  [attempt 1]       ← CANONICAL PIPELINE (Phase 1 PRESENT)
  → _attempt_and_evaluate  [attempt 2]       ← CANONICAL PIPELINE (Phase 1 PRESENT)
  → write_log
  → _emit_metrics_event
```

**Path C: run_contract_gated (1 condition)**
```
run_contract_gated
  → call_model [contract elicitation]
  → parse_contract
  → call_model [code generation]
  → parse_model_response                      ← DIRECT CALL, not through _attempt_and_evaluate
  → call_model [retry, if gate fails]
  → parse_model_response                      ← DIRECT CALL
  → _build_parsed_response + evaluate_output  ← DIRECT CALL, BYPASSES _attempt_and_evaluate
  → write_log                                  Phase 1 fields: NOT SET
  → _emit_metrics_event                        Phase 1 fields: NOT SET
```

**Path D: _fallback_run (contract_gated fallback)**
```
_fallback_run
  → _build_parsed_response + evaluate_output  ← DIRECT CALL, BYPASSES _attempt_and_evaluate
  → write_log                                  Phase 1 fields: NOT SET
  → _emit_metrics_event                        Phase 1 fields: NOT SET
```

**Path E: run_leg_reduction (1 condition)**
```
run_leg_reduction
  → call_model(raw=True)
  → parse_leg_reduction_output                 ← DIFFERENT PARSER (not parse_model_response)
  → manually build parsed dict                 ← MANUAL CONSTRUCTION
  → evaluate_output                            ← DIRECT CALL, BYPASSES _attempt_and_evaluate
  → write_log                                  Phase 1 fields: NOT SET
  → _emit_metrics_event                        Phase 1 fields: NOT SET
```

**Path F: run_retry_harness (4 conditions)**
```
run_retry_harness
  → call_model [per iteration]
  → parse_structured_output + parse_model_response  ← DUAL PARSER
  → _select_best_code                               ← CUSTOM EXTRACTION
  → manually build eval_parsed dict                  ← MANUAL CONSTRUCTION
  → _safe_evaluate (wraps evaluate_output)           ← BYPASSES _attempt_and_evaluate
  → [own logging: _write_retry_summary]              ← SEPARATE LOGGING PATH
  → return ev (no write_log, no _emit_metrics_event) ← CALLER DOES LOGGING
```

---

## 2. DUPLICATION TABLE

| Logical Step | Path A (single) | Path B (repair) | Path C (CGE) | Path D (CGE fallback) | Path E (LEG) | Path F (retry) |
|---|---|---|---|---|---|---|
| **Model call** | call_model | call_model | call_model x3 | N/A | call_model(raw) | call_model |
| **Parsing** | parse_model_response | parse_model_response | parse_model_response x3 | parse_model_response | parse_leg_reduction_output | parse_structured_output + parse_model_response |
| **_build_parsed_response** | YES (via _attempt) | YES (via _attempt) | YES (direct call) | YES (direct call) | MANUAL DICT | MANUAL DICT |
| **Reconstruction** | YES (via _attempt) | YES (via _attempt) | NO | NO | NO | NO |
| **Phase 1 observability** | YES | YES | **NO** | **NO** | **NO** | **NO** |
| **evaluate_output** | YES (via _attempt) | YES (via _attempt) | YES (direct) | YES (direct) | YES (direct) | YES (via _safe_evaluate) |
| **failure_source** | YES | YES | **NO** | **NO** | **NO** | **NO** |
| **case_validity** | YES | YES | **NO** | **NO** | **NO** | **NO** |
| **data_lineage** | YES | YES | **NO** | **NO** | **NO** | **NO** |
| **write_log** | YES | YES | YES | YES | YES | **NO** (own _write_retry_summary) |
| **_emit_metrics_event** | YES | YES | YES (without Phase 1 fields) | YES (without Phase 1 fields) | YES (without Phase 1 fields) | **NO** (caller does it) |

---

## 3. DIVERGENCE ANALYSIS

### 3.1 Path C (run_contract_gated) — 7 Divergences

1. **parse_model_response called 3x directly** (lines 565, 580, 589, 607) without going through _attempt_and_evaluate. No reconstruction runs. File-dict responses from CGE code generation are NOT reconstructed.
2. **_build_parsed_response called directly** (line 589) — gets code=None normalization but NO Phase 1 fields.
3. **evaluate_output called directly** (line 590) — no reconstruction, no Phase 1 observability.
4. **Phase 1 fields missing**: code_present, code_empty_reason, code_source, case_validity, failure_source, failure_source_detail, recovery_applied, recovery_types, content_normalized, data_lineage — ALL absent from ev.
5. **parse_model_response called TWICE** on final_code_raw (lines 589 and 607) — once for evaluation, once for write_log. This is wasteful and potentially inconsistent if the parser has side effects.
6. **No reconstruction**: if the CGE code generation step returns file_dict format, reconstruction never runs. Code may be None.
7. **Events emitted without Phase 1 fields** (line 609) — events.jsonl has "unknown" for all observability fields.

### 3.2 Path D (_fallback_run) — 5 Divergences

Same as Path C but simpler: one parse, one eval, no reconstruction, no Phase 1.

### 3.3 Path E (run_leg_reduction) — 6 Divergences

1. **Different parser**: uses parse_leg_reduction_output instead of parse_model_response. This is INTENTIONAL — LEG schema is different. But it means the standard reconstruction path never runs.
2. **Manual parsed dict** (lines 659-665): builds `{"code": ..., "reasoning": ..., ...}` by hand. Missing: code_present, code_empty_reason, parse_tier, parse_repaired, data_lineage.
3. **No reconstruction**: LEG uses raw=True, gets code from JSON "code" field directly. No file-dict format. No reconstruction needed. This is correct.
4. **evaluate_output called directly** (line 668): no Phase 1 computation.
5. **Phase 1 fields missing from ev**: all observability fields absent.
6. **write_log receives different parsed dict** (lines 699-702): `log_parsed` is a THIRD dict, different from both `parsed` and the one evaluate_output saw. This means the logged "reasoning" and "code" might not match what was actually evaluated.

### 3.4 Path F (run_retry_harness) — 8 Divergences

1. **Dual parser**: parse_structured_output + parse_model_response both run. _select_best_code chooses. This is INTENTIONAL but creates a third parser path.
2. **Manual eval_parsed dict** (lines 1151-1157): built inline. Missing all Phase 1 fields.
3. **_safe_evaluate wraps evaluate_output** in try/except. On crash: returns synthetic ev with pass=False. This is a FOURTH evaluation path (the others are direct evaluate_output calls).
4. **No _emit_metrics_event inside retry harness**. The CALLER (runner.py:_run_one_inner → _run_one → run_all) does logging. But run_all only writes events through its own path — and the retry harness return value does NOT include Phase 1 fields.
5. **Own logging**: _write_retry_summary writes to a SEPARATE log path. Not through RunLogger.write().
6. **Per-iteration eval**: evaluate_output runs once per iteration (up to 5 times). Only the FINAL iteration's ev is returned. Earlier iterations' evaluations are in the trajectory but not in events.jsonl.
7. **compute_alignment called AGAIN** at line 1587-1590 with DIFFERENT arguments than evaluate_output uses. evaluate_output uses (exec_pass, reasoning_correct). Retry harness uses (identified_correct_issue, execution.status). These can disagree.
8. **Phase 1 fields missing from final ev**: returned to _run_one_inner without code_present, case_validity, failure_source, data_lineage.

---

## 4. VIOLATION LIST

| # | Violation | Location | Impact |
|---|---|---|---|
| V1 | Manual parsed dict construction (LEG) | execution.py:659-665 | Phase 1 fields missing. Inconsistent with _build_parsed_response output. |
| V2 | Manual eval_parsed dict construction (retry) | retry_harness.py:1151-1157 | Phase 1 fields missing. |
| V3 | Direct evaluate_output call (CGE) | execution.py:590 | Bypasses reconstruction + Phase 1. |
| V4 | Direct evaluate_output call (CGE fallback) | execution.py:616 | Bypasses reconstruction + Phase 1. |
| V5 | Direct evaluate_output call (LEG) | execution.py:668 | Bypasses Phase 1. |
| V6 | Direct evaluate_output call (retry) | retry_harness.py:1158 via _safe_evaluate | Bypasses Phase 1. |
| V7 | Double parse_model_response on same raw (CGE) | execution.py:589, 607 | Wasteful, potentially inconsistent. |
| V8 | Separate write_log dict (LEG) | execution.py:699-702 | Logged data may differ from evaluated data. |
| V9 | compute_alignment re-called with different args (retry) | retry_harness.py:1587-1590 | Alignment can disagree with evaluate_output's alignment. |
| V10 | No _emit_metrics_event in retry harness | retry_harness.py (absent) | Events emitted by caller without Phase 1 fields. |
| V11 | _safe_evaluate swallows crashes | retry_harness.py:843-850 | Synthetic ev dict may lack required fields. |
| V12 | No reconstruction in CGE code gen | execution.py:565, 580 | File-dict responses are not reconstructed. |

---

## 5. CANONICAL PIPELINE DESIGN

### 5.1 The Single Canonical Function

All evaluation MUST flow through a single function that performs:

```python
def evaluate_case(case: dict, raw_output: str, model: str,
                  condition: str, parser: str = "standard") -> tuple[dict, dict]:
    """Canonical pipeline: parse → reconstruct → observe → evaluate → classify.

    Args:
        case: benchmark case dict
        raw_output: raw model response string
        model: model name
        condition: experimental condition
        parser: "standard" (parse_model_response) or "leg" (parse_leg_reduction_output)

    Returns:
        (parsed, ev) — the parsed dict and evaluation result.
        Both contain ALL Phase 1 observability fields.
    """
    # 1. Parse
    if parser == "leg":
        lr_parsed = parse_leg_reduction_output(raw_output)
        parsed = _build_parsed_response_from_leg(lr_parsed, raw_output)
    else:
        parsed = _build_parsed_response(parse_model_response(raw_output), raw_output)

    # 2. Reconstruct (if applicable)
    _do_reconstruction(case, parsed)

    # 3. Phase 1 observability
    _compute_observability(case, parsed)

    # 4. Evaluate
    ev = evaluate_output(case, parsed)

    # 5. Failure classification
    _compute_failure_source(parsed, ev)

    return parsed, ev
```

### 5.2 What Each Caller Does

**run_single**: Call `evaluate_case(case, raw_output, model, condition)`. Add condition-specific ev fields. Call write_log + _emit_metrics_event.

**run_repair_loop**: Call `evaluate_case` for attempt 1. If fail, call `evaluate_case` for attempt 2. Add repair-loop metadata. Write/emit.

**run_contract_gated**: Call `call_model` for each step. For the FINAL step's output, call `evaluate_case(case, final_code_raw, model, "contract_gated")`. Add CGE metadata. Write/emit.

**run_leg_reduction**: Call `call_model(raw=True)`. Call `evaluate_case(case, raw_output, model, "leg_reduction", parser="leg")`. Add LEG metadata. Write/emit.

**run_retry_harness**: Per iteration, call `evaluate_case(case, raw, model, condition)`. Accumulate trajectory. Return final ev. Caller does write/emit.

### 5.3 What Changes

The critical functions extracted from `_attempt_and_evaluate` into reusable components:

```
_build_parsed_response(parse_result, raw_output)     # Already exists
_build_parsed_response_from_leg(lr_parsed, raw_output) # NEW: maps LEG fields to standard dict
_do_reconstruction(case, parsed)                       # EXTRACT from _attempt_and_evaluate
_compute_observability(case, parsed)                   # EXTRACT from _attempt_and_evaluate
_compute_failure_source(parsed, ev)                    # EXTRACT from _attempt_and_evaluate
```

---

## 6. CONSOLIDATION PLAN

### Phase 1: Extract (Minimal, No Behavior Change)

Extract three functions from `_attempt_and_evaluate`:

**Step 1**: Extract `_do_reconstruction(case, parsed)` — lines 244-280 of current execution.py. Takes `case` and `parsed` dict, mutates `parsed` in place (sets _reconstruction_*, code).

**Step 2**: Extract `_compute_observability(parsed)` — lines 282-380. Takes `parsed` dict, sets code_present, code_empty_reason, code_source, recovery_applied, recovery_types, case_validity, data_lineage.

**Step 3**: Extract `_compute_failure_source(parsed, ev)` — lines 382-418. Takes `parsed` and `ev`, sets failure_source and failure_source_detail on `ev`.

**Step 4**: Rewrite `_attempt_and_evaluate` to call these three functions. Verify identical behavior.

### Phase 2: Wire Into Bypass Paths

**Step 5**: In `run_leg_reduction` (after building parsed dict and calling evaluate_output): call `_compute_observability(parsed)` and `_compute_failure_source(parsed, ev)`.

**Step 6**: In `run_contract_gated` (after calling evaluate_output at line 590): call `_compute_observability(final_parsed)` and `_compute_failure_source(final_parsed, ev)`.

**Step 7**: In `_fallback_run` (after calling evaluate_output at line 616): call `_compute_observability(parsed)` and `_compute_failure_source(parsed, ev)`.

**Step 8**: In retry harness (after `_safe_evaluate` at line 1158): call `_compute_observability(eval_parsed)` and `_compute_failure_source(eval_parsed, ev)`. Also ensure the final ev returned to _run_one_inner has all Phase 1 fields.

### Phase 3: Wire Into Logging/Events

**Step 9**: In `_run_one_inner` or `run_all`, after receiving ev from ANY path: ensure Phase 1 fields are propagated to _emit_metrics_event. Currently run_single does this explicitly. The other paths need it too — either by adding propagation or by having each run_* function do it.

**Step 10**: Fix V7 (double parse in CGE) and V8 (separate log_parsed dict in LEG) as cleanup.

### Validation

After each step: run all existing tests + canary validation. ALL 10 Phase 1 fields must be present for ALL conditions.

### Risk Assessment

- Steps 1-4: ZERO behavior change (extract + call). Tests prove equivalence.
- Steps 5-8: Add Phase 1 fields to bypass paths. Events change (gain fields). No execution logic change.
- Steps 9-10: Logging cleanup. No execution logic change.

Total: ~60 lines of extraction + ~20 lines of wiring per bypass path. No new abstractions. No architecture change.
