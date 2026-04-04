# Canonical Pipeline Consolidation Plan

**Date:** 2026-03-26
**Status:** PLAN ONLY. No implementation.
**Supersedes:** ARCHITECTURAL_PATH_AUDIT.md consolidation section

---

## Core Principle

There is ONE canonical function for evaluating model output:

```
evaluate_case(case, raw_output) → (parsed, ev)
```

It performs ALL of: parsing, reconstruction, observability, evaluation, failure classification.

No other code may perform any of these operations. No exceptions.

---

## 1. The Canonical Pipeline Function

```python
def evaluate_case(case: dict, raw_output: str,
                  parser: str = "standard") -> tuple[dict, dict]:
    """THE canonical evaluation pipeline. ALL paths use this.

    1. Parse raw_output → parsed dict
    2. Reconstruct (if file-dict format)
    3. Compute observability (code_present, case_validity, etc.)
    4. Run exec_evaluate + llm_classify via evaluate_output
    5. Compute failure_source attribution

    Args:
        case: benchmark case dict
        raw_output: raw model response string
        parser: "standard" or "leg"

    Returns:
        (parsed, ev) with ALL fields populated. No exceptions.
    """
```

**This function replaces `_attempt_and_evaluate`.** Same logic, but:
- Accepts `raw_output` as input (model call happens OUTSIDE)
- Accepts `parser` to select LEG vs standard parsing
- Does NOT call `call_model` (separation of model calling from evaluation)

### What It Does (in order)

```
Step 1: PARSE (ONE constructor for all paths)
    if parser == "leg":
        lr_parsed = parse_leg_reduction_output(raw_output)
        parse_result = _leg_to_parse_format(lr_parsed)  # format converter → standard schema
    else:
        parse_result = parse_model_response(raw_output)  # standard parser
    parsed = _build_parsed_response(parse_result, raw_output)  # THE ONE CONSTRUCTOR

Step 2: RECONSTRUCT
    if file-dict format and files present:
        run reconstruct_strict
        handle SUCCESS / FAILED_SYNTAX_ERRORS / other failures
        recovery if applicable

Step 3: OBSERVE
    compute code_present, code_empty_reason
    compute code_source
    compute recovery_applied, recovery_types
    compute case_validity
    accumulate data_lineage

Step 4: EVALUATE
    ev = evaluate_output(case, parsed)

Step 5: CLASSIFY
    compute failure_source, failure_source_detail

Step 6: RETURN
    return (parsed, ev)
```

### What It Guarantees

Every (parsed, ev) returned by this function has:
- `parsed["code"]` is str (never None)
- `parsed["code_present"]` is bool
- `parsed["code_empty_reason"]` is set when code_present=False
- `parsed["case_validity"]` is set
- `parsed["data_lineage"]` is non-empty
- `ev["failure_source"]` is set
- `ev["failure_source_detail"]` is set

---

## 2. What Each Caller Becomes

### run_single (baseline, diagnostic, guardrail, SCM, reasoning conditions)

```python
def run_single(case, model, condition):
    prompt, op_used = build_prompt(case, condition)
    raw_output = call_model(prompt, model=model, file_paths=...)

    parsed, ev = evaluate_case(case, raw_output)  # THE ONE CALL

    ev["operator_used"] = op_used
    ev["condition"] = condition
    # ... token instrumentation ...
    write_log(case["id"], condition, model, prompt, raw_output, parsed, ev)
    _emit_metrics_event(case, model, condition, ev, elapsed_seconds=...)
    return case["id"], condition, ev
```

**Deleted:** All inline reconstruction, observability computation, failure_source code in run_single. These now live exclusively in evaluate_case.

### run_repair_loop

```python
def run_repair_loop(case, model):
    prompt, _ = build_prompt(case, "repair_loop")
    raw_1 = call_model(prompt, model=model)

    parsed_1, ev_1 = evaluate_case(case, raw_1)  # THE ONE CALL

    if ev_1["pass"]:
        ev_1["operator_used"] = "REPAIR_LOOP"
        # ... write_log, _emit_metrics_event ...
        return case["id"], "repair_loop", ev_1

    # Attempt 2
    error_reasons = "; ".join(ev_1.get("reasons", [])[:3])
    repair_prompt = prompt + f"\n\nYour previous attempt FAILED with:\n{error_reasons}\n\nFix..."
    raw_2 = call_model(repair_prompt, model=model)

    parsed_2, ev_2 = evaluate_case(case, raw_2)  # THE ONE CALL

    ev_2["operator_used"] = "REPAIR_LOOP"
    # ... write_log, _emit_metrics_event ...
    return case["id"], "repair_loop", ev_2
```

**Change:** Replaces `_attempt_and_evaluate` with `evaluate_case`. `call_model` is separated out. Same behavior.

### run_contract_gated

```python
def run_contract_gated(case, model):
    # Step 1: Elicit contract
    contract_prompt = build_contract_prompt(task, code_files)
    contract_raw = call_model(contract_prompt, model=model, raw=True)
    contract = parse_contract(contract_raw)

    if contract is None:
        return _fallback_run(case, model, contract_raw)

    # Step 2: Generate code
    code_prompt = build_code_from_contract_prompt(task, code_files, contract)
    code_raw = call_model(code_prompt, model=model)

    # Step 3: Gate validation (extraction-only helper, NOT evaluation)
    candidate_code = extract_code_from_raw(code_raw)
    gate_1 = gate_validate(contract, candidate_code, ref_code)
    ...

    # Step 5: Evaluate FINAL output through canonical pipeline
    parsed, ev = evaluate_case(case, final_code_raw)  # THE ONE CALL

    ev["operator_used"] = "CONTRACT_GATED"
    ev["cge_executed"] = True
    ev["contract"] = contract
    # ... gate_results, num_attempts ...
    write_log(cid, "contract_gated", model, code_prompt, final_code_raw, parsed, ev)
    _emit_metrics_event(case, model, "contract_gated", ev)
    return cid, "contract_gated", ev
```

**Deleted:** Direct calls to `_build_parsed_response` and `evaluate_output` at lines 589-590. Double `parse_model_response` at line 607. Manual `parsed_final` construction.

**Kept:** Gate validation needs code from intermediate steps. Uses `extract_code_from_raw(code_raw)` — a dedicated extraction-only helper that returns a bare string, not a parsed dict. This is explicitly NOT an evaluation parse. `extract_code_from_raw` is the ONLY function outside evaluate_case permitted to call `parse_model_response`.

### _fallback_run

```python
def _fallback_run(case, model, contract_raw):
    parsed, ev = evaluate_case(case, contract_raw)  # THE ONE CALL

    ev["operator_used"] = "CONTRACT_GATED"
    ev["cge_executed"] = False
    ev["contract"] = None
    # ...
    write_log(case["id"], "contract_gated", model, "", contract_raw, parsed, ev)
    _emit_metrics_event(case, model, "contract_gated", ev)
    return case["id"], "contract_gated", ev
```

**Deleted:** Direct `_build_parsed_response` + `evaluate_output` call.

### run_leg_reduction

```python
def run_leg_reduction(case, model):
    prompt = build_leg_reduction_prompt(task, code_files)
    raw_output = call_model(prompt, model=model, raw=True)

    parsed, ev = evaluate_case(case, raw_output, parser="leg")  # THE ONE CALL

    ev["operator_used"] = "LEG_REDUCTION"
    ev["condition"] = "leg_reduction"
    # Attach LEG-specific metadata from lr_parsed (stored in parsed["_lr_parsed"])
    lr = parsed.get("_lr_parsed", {})
    ev["leg_reduction"] = {
        "valid_schema": lr.get("valid"),
        "schema_compliant": lr.get("schema_compliant"),
        "bug_diagnosis": lr.get("bug_diagnosis"),
        "plan_steps": lr.get("plan_steps", []),
        # ...
    }
    write_log(cid, "leg_reduction", model, prompt, raw_output, parsed, ev)
    _emit_metrics_event(case, model, "leg_reduction", ev)
    return cid, "leg_reduction", ev
```

**Deleted:** Manual `parsed = {...}` dict at lines 659-665. Direct `evaluate_output` call at line 668. Separate `log_parsed` dict at lines 699-702.

**New:** `_leg_to_parse_format(lr_parsed, raw_output)` inside evaluate_case. This is the ONE place where LEG parser output is converted to the canonical parsed dict. It stores `lr_parsed` in `parsed["_lr_parsed"]` so the caller can access LEG-specific metadata.

### run_retry_harness

```python
def run_retry_harness(case, model, ...):
    for k in range(max_iterations):
        if k == 0:
            prompt = _build_initial_prompt(case, ...)
        else:
            prompt = _build_retry_prompt(case, ...)

        raw = call_model(prompt, model=model)

        parsed, ev = evaluate_case(case, raw)  # THE ONE CALL

        # Build trajectory entry from ev (which now has ALL fields)
        entry = {
            "step": k,
            "pass": ev["pass"],
            "score": ev["score"],
            "code": parsed["code"],
            "reasoning": parsed["reasoning"],
            "failure_source": ev["failure_source"],
            "case_validity": parsed["case_validity"],
            # ... trajectory-specific analysis ...
        }
        trajectory.append(entry)

        if ev["pass"]:
            break

    # Build summary from trajectory
    _write_retry_summary(case, model, condition, summary)

    # CRITICAL FIX: write_log and _emit_metrics_event for the FINAL iteration
    write_log(case["id"], condition, model, prompt, raw, parsed, ev)
    _emit_metrics_event(case, model, condition, ev, elapsed_seconds=...)

    return case["id"], condition, ev
```

**Deleted:**
- `parse_structured_output` + `parse_model_response` dual parsing at lines 1119-1127.
- `_select_best_code` candidate selection (this logic moves INTO the standard parser path or becomes irrelevant since evaluate_case handles extraction).
- Manual `eval_parsed` dict at lines 1151-1157.
- `_safe_evaluate` wrapper (evaluate_case handles errors internally).
- `compute_alignment` re-call at line 1587-1590 (evaluate_case's evaluate_output already computes it correctly).

**Added:**
- `write_log` call (V10 fix — retry harness events now appear in run.jsonl via standard path).
- `_emit_metrics_event` call (V10 fix — retry harness events now appear in events.jsonl).

**Question: what about the retry harness's custom parsing (parse_structured_output + _select_best_code)?**

This is resolved by extending `parse_model_response` to handle the retry schema. The retry harness requests `{"reasoning": ..., "plan": [...], "code": ...}` format. Currently `parse_structured_output` handles this as a separate parser. Under consolidation:

- `parse_model_response` already handles JSON with "code" key via `_try_json_direct` (tier 1b). This extracts code and reasoning.
- The "plan" field is metadata, not needed for execution. It can be extracted post-parsing from `parsed["raw_output"]` or by reading the JSON's plan field from the already-parsed dict.
- `_select_best_code` is defensive extraction logic for when strict and fallback produce different code. This is a parser-level concern. It stays in the parser layer — either as part of `parse_model_response` or as a post-parse normalization step inside `evaluate_case`.

**Concrete approach:** Add a `_try_structured_output` tier to `parse_model_response` that handles the `{reasoning, plan, code}` schema — equivalent to `parse_structured_output` but producing the standard parsed dict format. If it fails, the existing tiers (json_direct, lenient, etc.) handle fallback. `_select_best_code` becomes an internal function of the parser layer, called when multiple extraction methods produce different results. The retry harness NEVER does its own parsing.

---

## 3. Helper Functions Inside evaluate_case

These are PRIVATE to evaluate_case. No external caller may use them.

### 3.1 ONE Parsed Constructor (Constraint 1)

There is exactly ONE function that normalizes parsed dicts: `_build_parsed_response`.

```python
# THE ONE CONSTRUCTOR — normalizes ALL parsed dicts:
def _build_parsed_response(parse_result: dict, raw_output: str) -> dict:
    """Attach raw_output, normalize code=None→"", ensure all defaults.
    EVERY parsed dict passes through this. No exceptions."""

# FORMAT CONVERTER (not a constructor) — translates LEG fields to standard schema:
def _leg_to_parse_format(lr_parsed: dict) -> dict:
    """Convert LEG parser output to parse_model_response-compatible dict.
    Returns a dict that _build_parsed_response can normalize.
    Stores lr_parsed in result["_lr_parsed"] for caller metadata access.

    Mapping:
        lr_parsed["code"] → result["code"]
        lr_parsed["bug_diagnosis"] → result["reasoning"]
        lr_parsed["parse_error"] → result["parse_error"]
        lr_parsed["code_extracted"] → result["code_present"] (preliminary)
        lr_parsed["extraction_source"] → result["code_source"] (preliminary)
        lr_parsed → result["_lr_parsed"] (full LEG metadata)
    """
```

Flow:
```
LEG:      parse_leg_reduction_output → _leg_to_parse_format → _build_parsed_response
Standard: parse_model_response → _build_parsed_response
```

Both paths produce the same normalized dict. No second constructor.

### 3.2 Extraction-Only Helper (Constraint 2)

```python
def extract_code_from_raw(raw: str) -> str:
    """Extract code string from raw output for NON-EVALUATION purposes.

    Used ONLY by CGE gate validation to get candidate code for contract checking.
    Does NOT produce a parsed dict. Does NOT trigger observability.
    This is NOT an evaluation path. Explicitly marked as such.
    """
    result = parse_model_response(raw)
    return result.get("code") or ""
```

This is the ONLY function outside evaluate_case that may call parse_model_response.
It returns a bare string, not a dict. It cannot be confused with an evaluation parse.

### 3.3 Best-Code Selection Inside Pipeline (Constraint 3)

`_select_best_code` is called INSIDE evaluate_case, after parsing and before reconstruction.
It is a post-parse normalization step within the canonical pipeline. No caller ever sees it.

```python
# INSIDE evaluate_case, after parse, before reconstruct:
def _post_parse_code_selection(parsed: dict, raw_output: str) -> None:
    """If the raw output contains code in multiple locations (JSON field + code block),
    select the best candidate via C1-C3. Mutates parsed["code"] in place.
    Only fires when parsed["code"] looks suspicious (too short, no defs)."""
```

This replaces the retry harness's `_select_best_code`. The retry harness no longer
does any extraction or selection — evaluate_case handles it for ALL paths.

### 3.4 Remaining Private Helpers

```python
# Extracted from current _attempt_and_evaluate:
def _do_reconstruction(case: dict, parsed: dict) -> None:
    """Mutates parsed in place: sets _reconstruction_*, code."""

def _compute_observability(parsed: dict) -> None:
    """Mutates parsed in place: sets code_present, code_empty_reason,
    code_source, recovery_applied, recovery_types, case_validity, data_lineage."""

def _compute_failure_source(parsed: dict, ev: dict) -> None:
    """Mutates ev in place: sets failure_source, failure_source_detail."""
```

---

## 4. What Is Deleted

| Location | What | Why |
|---|---|---|
| execution.py:234-418 | `_attempt_and_evaluate` | Replaced by `evaluate_case` |
| execution.py:659-665 | Manual parsed dict in run_leg_reduction | Replaced by `_leg_to_parse_format` inside evaluate_case |
| execution.py:589-590 | Direct `_build_parsed_response` + `evaluate_output` in run_contract_gated | Replaced by `evaluate_case` call |
| execution.py:607 | Double `parse_model_response` in run_contract_gated | Eliminated — evaluate_case parses once |
| execution.py:615-616 | Direct `_build_parsed_response` + `evaluate_output` in _fallback_run | Replaced by `evaluate_case` call |
| execution.py:699-702 | Separate `log_parsed` dict in run_leg_reduction | Eliminated — parsed from evaluate_case is used for logging |
| retry_harness.py:1119-1157 | Dual parsing + manual eval_parsed dict | Replaced by `evaluate_case` call |
| retry_harness.py:835-850 | `_safe_evaluate` wrapper | Eliminated — evaluate_case handles errors |
| retry_harness.py:1587-1590 | Second `compute_alignment` call | Eliminated — evaluate_case's evaluate_output computes alignment correctly |

---

## 5. What Is NOT Changed

| Component | Reason |
|---|---|
| `evaluate_output` in evaluator.py | Stays as-is. evaluate_case calls it. Nobody else does. |
| `exec_evaluate` in exec_eval.py | Stays as-is. evaluate_output calls it. |
| `parse_model_response` in parse.py | Stays as-is (with existing tiers). Gets one new tier for structured output. |
| `parse_leg_reduction_output` in leg_reduction.py | Stays as-is. evaluate_case calls it when parser="leg". |
| `reconstruct_strict` in reconstructor.py | Stays as-is. evaluate_case calls it. |
| `write_log` and `_emit_metrics_event` | Stay as-is. Callers of evaluate_case call these after. |
| `RunLogger` | Stays as-is. |
| All prompt construction | Stays as-is. |
| All model calling | Stays as-is. Separated from evaluate_case. |

---

## 6. Enforcement: How Duplication Is Prevented

### Rule 1: evaluate_output is PRIVATE to evaluate_case

`evaluate_output` must NOT be imported or called from any file except inside `evaluate_case`. If any other function calls it, that is a violation.

**Enforcement:** grep test asserting no `evaluate_output(` call outside evaluate_case.

### Rule 2: ONE parsed constructor

Every parsed dict MUST pass through `_build_parsed_response`. No second constructor. `_leg_to_parse_format` is a format converter that feeds INTO `_build_parsed_response`, not a replacement for it.

**Enforcement:** grep test asserting `_build_parsed_response` is the only function that sets `parsed["raw_output"]` (the signature of the constructor).

### Rule 3: No manual parsed dict construction

No inline `{"code": ..., "reasoning": ...}` construction outside the constructor chain. No `eval_parsed = {`, no `parsed = {` patterns in run_* functions.

**Enforcement:** grep test asserting no dict-literal construction of evaluation dicts outside evaluate_case.

### Rule 4: No parsing outside evaluate_case (one exception)

`parse_model_response` and `parse_leg_reduction_output` MUST NOT be called from run_* functions. The ONLY permitted external caller is `extract_code_from_raw`, which returns a bare string (not a dict) for CGE gate validation.

**Enforcement:** grep test asserting `parse_model_response(` appears ONLY in: (a) evaluate_case, (b) extract_code_from_raw, (c) parse.py itself. Any other call site is a violation.

### Rule 5: All extraction logic in parser tiers or pipeline

`_select_best_code` / `_post_parse_code_selection` lives INSIDE evaluate_case. No caller-side extraction. No dual-parser logic in any run_* function or retry harness.

**Enforcement:** grep test asserting `_select_best_code` is not called from retry_harness.py.

---

## 7. Implementation Order

| Step | What | Risk |
|---|---|---|
| 1 | Create `evaluate_case` by refactoring `_attempt_and_evaluate`: remove `call_model`, add `parser` parameter, add `_leg_to_parse_format`. | LOW — same logic, reorganized |
| 2 | Add `_try_structured_output` tier to parse_model_response for retry harness format. | LOW — new parser tier |
| 3 | Rewrite `run_single` to use `evaluate_case`. | LOW — trivial caller change |
| 4 | Rewrite `run_repair_loop` to use `evaluate_case`. | LOW — already uses _attempt_and_evaluate |
| 5 | Rewrite `run_contract_gated` to use `evaluate_case`. | MEDIUM — multi-step flow with pre-gate parsing |
| 6 | Rewrite `_fallback_run` to use `evaluate_case`. | LOW — simple |
| 7 | Rewrite `run_leg_reduction` to use `evaluate_case(parser="leg")`. | MEDIUM — different parser path |
| 8 | Rewrite `run_retry_harness` to use `evaluate_case` per iteration. Add write_log + _emit_metrics_event. | MEDIUM — largest change, multiple iterations |
| 9 | Delete `_attempt_and_evaluate`. Delete `_safe_evaluate`. Delete dead code. | LOW — cleanup |
| 10 | Add enforcement tests. | LOW |

### Validation at each step:

After steps 1-2: existing tests pass (evaluate_case is a drop-in).
After steps 3-7: canary run, ALL conditions, ALL Phase 1 fields populated.
After step 8: retry conditions appear in events.jsonl for the first time.
After step 9: grep confirms no remaining direct evaluate_output calls outside evaluate_case.
After step 10: enforcement tests prevent future duplication.
