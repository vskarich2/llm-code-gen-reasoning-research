# Plan: Inline Oracle Integration into the Ablation Pipeline — v1

**Date:** 2026-04-03
**Status:** PLAN ONLY — NO IMPLEMENTATION
**Priority:** CRITICAL — measurement integrity bug

---

## 1. Executive Summary

The oracle reasoning evaluator (`evaluators/reasoning_truth.py`) does not run inline during ablations. It runs only as an offline post-hoc script (`scripts/run_oracle_eval.py`). This means the per-attempt WAL records contain classifier-based reasoning judgments but NOT ground-truth oracle reasoning labels. The core scientific decomposition — reasoning × structure × execution — cannot be performed from the WAL alone. Instead, it requires offline joining of WAL events with separately-produced oracle artifacts, breaking per-attempt alignment and creating opportunities for misinterpretation.

The fix: run the oracle evaluator inline after reasoning extraction, log both classifier AND oracle results into the same per-attempt WAL event, and make the dashboard read oracle fields directly from the WAL.

Estimated effort: 3-4 days across 6 phases.

---

## 2. Problem Statement

### What currently exists in the WAL

Every `case.end` event contains:
- `payload.mechanism_identified_dim`: classifier judgment (CORRECT/PARTIAL/WRONG)
- `payload.commitments_satisfied_dim`: classifier judgment
- `payload.reasoning_code_alignment_dim`: classifier judgment
- `payload.mechanism_correct`: derived boolean from classifier
- `payload.evaluation.reasoning_sufficient`: derived boolean (M ∧ C)
- `payload.v2_artifact.raw_root_cause`: model's reasoning text
- `payload.v2_artifact.raw_fix_strategy`: model's reasoning text

### What is MISSING from the WAL

- `reasoning_truth`: the oracle evaluator's ground-truth label (CORRECT/PARTIAL/WRONG/UNJUDGABLE)
- Oracle justification
- Oracle evaluation metadata (latency, error status)

### Where oracle labels currently live

Separate files: `artifacts/audits/oracle_intervention/oracle_labels.jsonl` and similar directories. These are produced by `scripts/run_oracle_eval.py`, which:
1. Reads `case.end` events from merged_events.jsonl
2. Extracts `root_cause` and `fix_strategy` from `v2_artifact`
3. Calls the oracle evaluator model (gpt-5-mini)
4. Writes results to a separate JSONL file

### Why this is wrong

- Per-attempt WAL records are incomplete — they lack the ground-truth reasoning signal
- Online analysis requires offline joining, which is fragile and error-prone
- The dashboard Oracle tab cannot display oracle data without sidebar checkbox toggling
- Any analysis that crosses oracle + execution + AST requires multi-file joining
- New runs lose oracle context until the offline script is manually run

---

## 3. Current Pipeline Audit

### Execution flow (from `execution_v2.py` lines 119-151)

```
1. _render_generation_prompt()          → prompt
2. _call_generation_model()             → raw_response
3. _parse_outputs()                     → strict/recovery/fmt parse
4. _select_artifact()                   → routing decision
5. normalize_generation_v2()            → artifact (has root_cause, fix_strategy)  ← ORACLE INPUT READY HERE
6. _reconstruct_and_execute()           → recon, code, exec_result
7. _classify_reasoning()                → classifier_result                        ← CLASSIFIER RUNS HERE
8. _derive_metrics()                    → signals
9. _compute_evaluation()                → 3-axis evaluation
10. _run_ast_verification()             → ast_result
11. _assemble_result()                  → final event dict
12. _log_result()                       → WAL emission
```

The oracle evaluator needs:
- `artifact.raw_root_cause` (available after step 5)
- `artifact.raw_fix_strategy` (available after step 5)
- `case` dict (available from the start)
- Buggy code from disk (loadable from `case["code_files"]`)

**The oracle can run immediately after step 5, in parallel with or before the classifier at step 7.** It does NOT need execution results, reconstructed code, or classifier output.

### Oracle evaluator interface (from `reasoning_truth.py`)

```python
oracle_spec = build_oracle_spec(case)        # from case dict
buggy_code = load_buggy_code(case, root)     # from disk
prompt = render_prompt(oracle_spec, root_cause, fix_strategy, buggy_code)
# → call_model(prompt) → raw_response
label, justification, error = parse_response(raw_response)
```

Returns: `("CORRECT"|"PARTIAL"|"WRONG"|"UNJUDGABLE", justification_text, error_or_none)`

### Pre-filter

`is_unjudgable(root_cause, fix_strategy)` returns True if reasoning text is missing or too short (<20 chars). In this case, oracle eval is skipped and status="SKIPPED".

---

## 4. Why This Is Scientifically Serious

The project's central claim is a 3-way decomposition: reasoning × structure × execution. The "reasoning" axis currently has TWO signals:

1. **Classifier (LLM-based):** mechanism_identified, commitments_satisfied, etc. This is what the WAL contains. It has known problems: 99.7% mechanism_correct vs oracle's 90.4% — massive overcalling.

2. **Oracle (ground-truth-grounded):** reasoning_truth. This is the more accurate signal. But it's offline-only.

Any paper claim about "reasoning failure = 34%" or "execution fidelity = 58%" that uses the oracle signal REQUIRES the oracle to be run. If it's not inline, those numbers are post-hoc artifacts that can't be reproduced from the WAL alone.

---

## 5. Current Data Flow vs Required Data Flow

### Current (broken)

```
Pipeline run → WAL event (classifier reasoning only)
                    ↓
Offline script → oracle_labels.jsonl (separate file)
                    ↓
Analysis script → join WAL + oracle by (case_id, model, condition, trial)
```

### Required (fixed)

```
Pipeline run → WAL event (classifier reasoning + oracle reasoning + execution + AST)
                    ↓
Dashboard / analysis → reads directly from WAL
```

---

## 6. Inline Oracle Integration Design

### Where oracle runs in the pipeline

**After step 5 (artifact normalization), before or in parallel with step 7 (classifier).**

```
5.  artifact = normalize_generation_v2(parsed_gen, case, condition)
5a. oracle_result = _run_oracle_evaluation(artifact, case, config)      ← NEW
6.  recon, code, exec_result = _reconstruct_and_execute(...)
7.  classifier_result = _classify_reasoning(...)
...
11. ev = _assemble_result(..., oracle_result)                           ← PASS THROUGH
```

### Why after step 5, not later

- Oracle needs `artifact.raw_root_cause` and `artifact.raw_fix_strategy`, which are available after step 5
- Oracle MUST NOT see generated code, execution results, or classifier output (per its design contract: "NO LEAKAGE")
- Running before step 6 means oracle doesn't block on execution, which could timeout
- If execution crashes, oracle still has valid reasoning to evaluate

### New function: `_run_oracle_evaluation`

```python
def _run_oracle_evaluation(artifact, case, config) -> dict:
    """Run oracle reasoning evaluation inline.
    
    Returns dict with: status, reasoning_truth, justification, error, latency_ms.
    Must run BEFORE execution and classifier (no leakage).
    """
    from core.evaluation.oracle_eval.reasoning_truth import (
        build_oracle_spec, load_buggy_code, render_prompt,
        parse_response, is_unjudgable,
    )
    
    root_cause = artifact.raw_root_cause or ""
    fix_strategy = artifact.raw_fix_strategy or ""
    
    # Pre-filter
    if is_unjudgable(root_cause, fix_strategy):
        return {"status": "SKIPPED", "reasoning_truth": "UNASSESSED",
                "justification": "", "error": "pre_filter", "latency_ms": 0}
    
    oracle_spec = build_oracle_spec(case)
    buggy_code = load_buggy_code(case, PROJECT_ROOT)
    prompt = render_prompt(oracle_spec, root_cause, fix_strategy, buggy_code)
    
    t0 = time.monotonic()
    try:
        cr = call_model(prompt, model=config.models.evaluator.name,
                        raw=True, logger=None, phase="oracle_eval")
        raw_resp = cr.response
    except Exception as e:
        return {"status": "FAILURE", "reasoning_truth": "UNASSESSED",
                "justification": "", "error": str(e)[:200],
                "latency_ms": int((time.monotonic() - t0) * 1000)}
    
    elapsed = int((time.monotonic() - t0) * 1000)
    label, justification, err = parse_response(raw_resp)
    
    return {
        "status": "SUCCESS" if err is None else "PARSE_ERROR",
        "reasoning_truth": label,
        "justification": justification,
        "error": err,
        "latency_ms": elapsed,
        "source": "inline_oracle_v1",
    }
```

### Should oracle run when parsing fails?

**No.** If `parsed_gen.parse_status != "success"`, the artifact will have empty root_cause/fix_strategy. The pre-filter (`is_unjudgable`) will catch this and return `SKIPPED`. This is correct — if the model didn't produce parseable reasoning, there's nothing for the oracle to evaluate.

### Should oracle run when execution crashes?

**Yes.** Oracle evaluates reasoning text, not code execution. A model can have correct reasoning but code that crashes. Oracle should still assess the reasoning. This is already handled by running oracle BEFORE execution (step 5a vs step 6).

### Retries

For retry conditions, `execution_v2.run_v2()` is called once per case (not per attempt). The inner retry loop is in `retry_v2.py`. Each retry iteration produces a new generation → new artifact → new reasoning text. Oracle should run on EACH attempt's reasoning.

For retry integration: the same `_run_oracle_evaluation()` function is called inside the retry loop, once per attempt, on the attempt's artifact.

### Config gating

Oracle evaluation should be configurable:

```yaml
oracle:
  inline_enabled: true
  model: "gpt-5-mini"
  timeout: 30
```

When `inline_enabled: false`, oracle returns `{"status": "DISABLED", "reasoning_truth": "UNASSESSED", ...}`.

---

## 7. Exact WAL Schema Revision

### New section: `oracle` in the event dict

```json
{
  "payload": {
    "...existing fields...",
    
    "oracle": {
      "status": "SUCCESS|FAILURE|SKIPPED|PARSE_ERROR|DISABLED",
      "reasoning_truth": "CORRECT|PARTIAL|WRONG|UNJUDGABLE|UNASSESSED",
      "justification": "string (oracle's explanation)",
      "error": "string|null",
      "latency_ms": 450,
      "source": "inline_oracle_v1"
    }
  }
}
```

### Field semantics

| Field | Type | Allowed values | Nullable | Semantics |
|-------|------|---------------|----------|-----------|
| `status` | str | SUCCESS, FAILURE, SKIPPED, PARSE_ERROR, DISABLED | No | Whether the oracle call completed |
| `reasoning_truth` | str | CORRECT, PARTIAL, WRONG, UNJUDGABLE, UNASSESSED | No | Oracle's label. UNASSESSED = not evaluated (skipped/failed/disabled) |
| `justification` | str | free text | No (empty string OK) | Oracle's reasoning for the label |
| `error` | str | error description | Yes (null = no error) | Error message if status ≠ SUCCESS |
| `latency_ms` | int | ≥ 0 | No | LLM call latency |
| `source` | str | version identifier | No | "inline_oracle_v1" for this implementation |

### Status semantics

- `SUCCESS`: Oracle call completed, response parsed, label is valid
- `FAILURE`: Oracle LLM call failed (timeout, API error)
- `SKIPPED`: Pre-filter determined reasoning is too short/missing to evaluate
- `PARSE_ERROR`: Oracle LLM returned something unparseable
- `DISABLED`: Oracle evaluation disabled via config

### Nullability rules

- `reasoning_truth` is NEVER null. When not evaluated, value is `UNASSESSED`.
- `status` is NEVER null.
- `error` IS null when no error occurred.
- `justification` is empty string (not null) when not available.

### What this does NOT change

- All existing `payload.mechanism_correct`, `payload.mechanism_identified_dim`, etc. remain untouched
- The `evaluation` section continues to derive from classifier, not oracle
- The `classification` section remains the classifier output
- Oracle and classifier coexist independently

---

## 8. Event Emission Contract

### Single unified event

The oracle result is included in the same `case.end` event, inside `payload.oracle`. No separate event type. No staged partial writes.

### Emission order

```
artifact ready
  → oracle runs (step 5a)
  → execution runs (step 6)
  → classifier runs (step 7)
  → signals derived (step 8)
  → evaluation computed (step 9)
  → AST verified (step 10)
  → ALL results assembled into one event (step 11)
  → ONE case.end event emitted (step 12)
```

### Retry handling

For retry conditions, each attempt within a retry chain gets its own oracle evaluation (on that attempt's artifact). The final `case.end` event contains the results for the LAST attempt. Per-attempt oracle results should also be captured in the trajectory if the retry system logs per-attempt data.

---

## 9. Backward Compatibility Strategy

### Old WAL records (pre-oracle-inline)

Old events will NOT have `payload.oracle`. The dashboard and analysis scripts must handle this:

```python
oracle = payload.get("oracle", {})
reasoning_truth = oracle.get("reasoning_truth", "UNASSESSED")
oracle_status = oracle.get("status", "NOT_PRESENT")
```

`NOT_PRESENT` is not a valid status in the new schema — it's the fallback for old records. Analysis scripts distinguish:
- `NOT_PRESENT`: old run, oracle wasn't available inline
- `DISABLED`: new run, oracle deliberately turned off
- `SKIPPED`: reasoning text too short to evaluate
- `SUCCESS`/`FAILURE`/`PARSE_ERROR`: oracle ran

### No migration needed

Old WAL files are not rewritten. The schema addition is backward-compatible (new field, not renamed field). The offline oracle script (`run_oracle_eval.py`) can still be used for old runs.

### Dashboard behavior

The Oracle tab should:
1. Check for `payload.oracle.reasoning_truth` first (inline oracle)
2. Fall back to joined oracle labels from sidebar (legacy mode)
3. Display which source is active: "Source: inline oracle" or "Source: offline oracle labels"

---

## 10. Dashboard / Analysis Implications

### Oracle tab changes

The tab should show reasoning evaluation by default from inline oracle fields:
- If `oracle.reasoning_truth` is present and not UNASSESSED → show it
- If absent or UNASSESSED → show classifier-based reasoning as fallback with a note: "Oracle not available. Showing classifier reasoning."
- If sidebar oracle labels are also loaded → show comparison view

### Analysis scripts

Existing analysis scripts (e.g., `analysis_v6_final.py`) should prefer inline oracle if present:

```python
# Prefer inline oracle over offline oracle
if 'oracle' in payload and payload['oracle'].get('status') == 'SUCCESS':
    reasoning_truth = payload['oracle']['reasoning_truth']
elif oracle_labels_dict.get(key):
    reasoning_truth = oracle_labels_dict[key]
else:
    reasoning_truth = None
```

### Avoiding classifier/oracle confusion

All downstream code must use explicit field paths:
- Classifier: `payload.mechanism_correct`, `payload.mechanism_identified_dim`
- Oracle: `payload.oracle.reasoning_truth`

Never mix these into a single "reasoning_correct" field.

---

## 11. Failure Modes and Edge Cases

| Scenario | Oracle behavior | WAL record |
|----------|----------------|------------|
| Normal success | Call oracle, get label | `status=SUCCESS, reasoning_truth=CORRECT/PARTIAL/WRONG` |
| Malformed generator response | Artifact has empty root_cause | `status=SKIPPED, reasoning_truth=UNASSESSED` |
| Parser failure (no parse) | No artifact at all | `status=SKIPPED, reasoning_truth=UNASSESSED` |
| Classifier failure | Oracle still runs (independent) | `oracle.status=SUCCESS` even if classifier failed |
| Oracle LLM timeout | Catch exception, log error | `status=FAILURE, reasoning_truth=UNASSESSED, error="timeout"` |
| Oracle LLM returns garbage | Parse error | `status=PARSE_ERROR, reasoning_truth=UNJUDGABLE` |
| Execution crash | Oracle runs before execution | `oracle.status=SUCCESS` regardless of exec |
| Config disables oracle | Skip immediately | `status=DISABLED, reasoning_truth=UNASSESSED` |
| Old run (no oracle field) | N/A | `payload.oracle` absent entirely |
| Retry: multiple attempts | Oracle runs per attempt | Each attempt's oracle result in trajectory |

---

## 12. Validation Plan

### Unit tests

1. `test_oracle_eval_inline_success`: Mock oracle LLM, verify `_run_oracle_evaluation()` returns correct dict
2. `test_oracle_eval_inline_skip`: Empty root_cause → status=SKIPPED
3. `test_oracle_eval_inline_failure`: LLM throws → status=FAILURE, error populated
4. `test_oracle_eval_inline_disabled`: Config disabled → status=DISABLED

### Integration tests

5. Run one case end-to-end with oracle enabled. Verify WAL `case.end` event contains `payload.oracle` with `status=SUCCESS`.
6. Run same case with oracle disabled. Verify `payload.oracle.status=DISABLED`.
7. Run a parse-failure case. Verify `payload.oracle.status=SKIPPED`.

### Golden-run validation

8. Run the oracle on 100 events from `v2_targeted_50trial_canonical` BOTH inline and via the offline script. Compare labels. They should agree >99% (any disagreement is due to LLM non-determinism at temperature=0, which should be rare).

### Dashboard checks

9. Load a v3 experiment with inline oracle. Verify Oracle tab shows data without sidebar checkbox.
10. Load a v2 experiment without inline oracle. Verify Oracle tab shows "Oracle not available" or falls back to sidebar.

### Backward compatibility

11. Load old v2 WAL. Verify no crash. Oracle fields absent, dashboard degrades gracefully.

---

## 13. Rollout Plan

### Phase 0: Audit (0.5 day)
**Goal:** Confirm the integration point is exactly as described in this plan.
**Tasks:** Read execution_v2.py, retry_v2.py, verify artifact availability. Confirm oracle evaluator imports work.
**Exit criteria:** Integration point confirmed, no surprises.

### Phase 1: Schema extension (0.5 day)
**Goal:** Define the `oracle` section in the event schema.
**Tasks:** Add oracle fields to schema.py. Add to dashboard field registry. No pipeline changes.
**Files:** `dashboard/schema.py`, `dashboard/data/evaluation_fields.py`
**Exit criteria:** Dashboard can read (and show empty) oracle fields from v3 events.

### Phase 2: Inline oracle in baseline path (1 day)
**Goal:** Run oracle evaluation inline in `execution_v2.run_v2()`.
**Tasks:**
- Add `_run_oracle_evaluation()` function
- Call it after `normalize_generation_v2()` (line 133)
- Pass result to `_assemble_result()`
- Include `payload.oracle` in the event dict
- Add config gate (`oracle.inline_enabled`)
**Files:** `core/pipeline/orchestration/execution_v2.py`, experiment config YAML
**Risks:** Additional LLM call per attempt (~3s latency, ~$0.001 cost)
**Exit criteria:** WAL events from a new baseline run contain `payload.oracle` with valid labels.

### Phase 3: Inline oracle in retry path (0.5 day)
**Goal:** Run oracle on each retry attempt.
**Tasks:** Add oracle evaluation call inside `retry_v2.py` per-attempt loop, using the same `_run_oracle_evaluation()`.
**Files:** `core/pipeline/orchestration/retry_v2.py`
**Exit criteria:** Retry WAL events contain per-attempt oracle labels.

### Phase 4: Dashboard + analysis updates (1 day)
**Goal:** Dashboard reads inline oracle from WAL without sidebar checkbox.
**Tasks:**
- Update Oracle tab to read from `payload.oracle.reasoning_truth`
- Fall back to sidebar oracle labels for old runs
- Display source indicator
- Update analysis scripts to prefer inline oracle
**Files:** `dashboard/views/oracle.py`, `dashboard/data/evaluation_fields.py`, `dashboard/schema.py`
**Exit criteria:** Oracle tab shows data for v3+ runs without sidebar checkbox.

### Phase 5: Validation (0.5 day)
**Goal:** Verify inline oracle matches offline oracle.
**Tasks:** Run 100-event comparison between inline and offline oracle. Check >99% agreement.
**Exit criteria:** Agreement confirmed. No systematic divergence.

### Phase 6: Deprecate offline-only workflow (optional, 0.5 day)
**Goal:** Mark `scripts/run_oracle_eval.py` as legacy. Update documentation.
**Tasks:** Add deprecation notice. Update CLAUDE.md reference. Keep script for legacy log analysis.
**Exit criteria:** New runs never need the offline script. Old runs still work with it.

---

## 14. Concrete Next-Step Checklist

- [ ] Confirm `core/evaluation/oracle_eval/reasoning_truth.py` imports work from `execution_v2.py`
- [ ] Add `oracle.inline_enabled` config key to default.yaml
- [ ] Implement `_run_oracle_evaluation()` in execution_v2.py
- [ ] Call it after line 133 (artifact normalization)
- [ ] Add `oracle_result` parameter to `_assemble_result()`
- [ ] Include `payload.oracle` in the assembled event dict
- [ ] Add oracle fields to `dashboard/schema.py` FIELD_REGISTRY
- [ ] Update `dashboard/data/evaluation_fields.py` to read inline oracle
- [ ] Update `dashboard/views/oracle.py` to display inline oracle
- [ ] Run one end-to-end test with oracle enabled
- [ ] Run 100-event validation against offline oracle script
- [ ] Update CLAUDE_RULES documentation

---

## Technical Question: Should oracle run before or after classifier?

**Answer: BEFORE the classifier, immediately after artifact normalization (step 5a).**

Justification:
1. Oracle needs only `root_cause` + `fix_strategy` + case metadata — all available at step 5
2. Oracle must NOT see classifier output (independence constraint from the oracle design)
3. Running before execution means oracle doesn't block on slow/crashing execution
4. If execution times out at 30s, oracle has already completed its ~3s LLM call
5. The classifier can optionally see oracle results (for future calibration work), but oracle cannot see classifier results

The pipeline order becomes:

```
1-4. Prompt → Generate → Parse → Route
5.   Normalize artifact (root_cause, fix_strategy available)
5a.  Oracle evaluation (reads reasoning text, writes oracle result)    ← NEW
6.   Reconstruct + Execute
7.   Classifier evaluation (reads artifact + code + execution)
8-10. Derive metrics + Compute evaluation + AST verification
11.  Assemble event (includes oracle + classifier + execution + AST)
12.  Emit WAL event
```
