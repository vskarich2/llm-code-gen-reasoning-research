# Inline Oracle Integration Plan v2 — Full Revision

**Date:** 2026-04-03
**Supersedes:** inline_oracle_integration_plan_v1.md
**Status:** PLAN ONLY

---

## 1. Executive Summary

The oracle reasoning evaluator does not run inline during ablations. Per-attempt WAL records lack ground-truth reasoning labels. This plan fixes it by running the oracle inline after reasoning extraction, logging results per-attempt in the trajectory, and guaranteeing atomic WAL events that contain all four measurement axes.

**Critical v2 additions:** per-attempt alignment in retry chains, schema versioning, structural no-leakage enforcement, trace identifiers, classifier-oracle disagreement tracking, coverage accounting, atomicity guarantees.

---

## 2. The Question: Is Oracle Part of the Experimental Unit?

**Answer: Yes. Oracle evaluation is part of the experimental unit, not an auxiliary measurement.**

Justification:
- The project's core claim decomposes failures into reasoning × structure × execution
- This decomposition requires per-attempt alignment of all three signals
- If oracle is auxiliary (offline-only), the decomposition is a post-hoc join, not a measurement
- If oracle is part of the experimental unit, every attempt has a complete 4-axis record
- The oracle's cost (~$0.001/attempt, ~3s latency) is negligible relative to generation (~$0.01/attempt, ~5-30s)

**Consequence:** Oracle runs on EVERY attempt, including retry iterations. Results are logged in the same WAL event. No offline joining is needed for new runs.

---

## 3. Per-Attempt Alignment

### Current retry trajectory structure (from `retry_v2.py` line 508)

Each retry attempt appends to `payload.trajectory`:
```json
{
    "attempt": 0,
    "pass": true,
    "score": 1.0,
    "parse_valid": true,
    "code_length": 450,
    "retry_mode": "retry_bare_retry_v2",
    "had_test_feedback": true,
    "mismatch_critique": "..."
}
```

### Required: oracle per attempt

Each trajectory entry MUST also include:
```json
{
    "attempt": 0,
    "pass": true,
    "oracle": {
        "status": "SUCCESS",
        "reasoning_truth": "CORRECT",
        "justification": "...",
        "error": null,
        "latency_ms": 340
    },
    "...existing fields..."
}
```

### Implementation in retry_v2.py

Inside the retry loop (before line 508), after artifact normalization for each attempt:

```python
# After: artifact = normalize_generation_v2(parsed_gen, case, condition)
# Before: trajectory.append({...})

oracle_result = _run_oracle_evaluation(artifact, case, config)

trajectory.append({
    "attempt": k,
    "pass": passed,
    "oracle": oracle_result,       # ← NEW: per-attempt oracle
    "score": exec_result.get("score", 0),
    ...
})
```

### For baseline (single-shot) path

In `execution_v2.py`, oracle result is logged in `payload.oracle` (the top-level oracle, since there's only one attempt):

```json
{
    "payload": {
        "oracle": { "status": "SUCCESS", "reasoning_truth": "CORRECT", ... },
        "...other fields..."
    }
}
```

### Dashboard expansion

The `leg_scanner.py` trajectory expansion (line 198-234) must extract oracle from each trajectory entry:

```python
# Inside the trajectory expansion loop (line 206-234):
row["oracle_status"] = t_entry.get("oracle", {}).get("status", "NOT_PRESENT")
row["oracle_verdict"] = t_entry.get("oracle", {}).get("reasoning_truth", "UNASSESSED")
```

### Alignment guarantee

Every attempt row in the dashboard DataFrame will have:

| Field | Source | Per-attempt? |
|-------|--------|-------------|
| `exec_pass` | trajectory[k].pass | YES |
| `oracle_verdict` | trajectory[k].oracle.reasoning_truth | YES |
| `mechanism_dim` | final attempt only (classifier) | NO (final only) |
| `ast_status` | final attempt only (AST eval) | NO (final only) |

**Note:** Classifier and AST run only on the final attempt (current behavior). Oracle runs on EVERY attempt because reasoning text changes between retries. This is the correct design — oracle tracks whether reasoning IMPROVES across retries.

---

## 4. Schema Versioning

### New field: `payload._schema_version`

```json
{
    "payload": {
        "_schema_version": "v3.1",
        "...all other fields..."
    }
}
```

### Version history

| Version | Description | Breaking? |
|---------|-------------|-----------|
| v2 (implicit) | Original v2 WAL format. No evaluation/ast_eval/oracle sections. | — |
| v3.0 | Added payload.evaluation, payload.ast_eval, payload.classification, payload.reconstruction | Non-breaking (additive) |
| **v3.1** | **Added payload.oracle, trajectory[].oracle, payload._schema_version** | **Non-breaking (additive)** |

### Versioning policy

- Non-breaking changes (new fields): increment minor version (v3.0 → v3.1)
- Breaking changes (renamed/removed fields): increment major version (v3 → v4)
- `_schema_version` absent = legacy v2 format
- Readers must handle missing fields gracefully (use `.get()` with defaults)

### `payload.oracle.version`

```json
{
    "payload": {
        "oracle": {
            "version": "inline_v1",
            "status": "SUCCESS",
            "reasoning_truth": "CORRECT",
            "..."
        }
    }
}
```

`version` tracks the oracle evaluator implementation. Changes to the oracle prompt, model, or logic increment this version. This allows analysis scripts to filter by oracle version for consistency.

---

## 5. No-Leakage Enforcement

### Structural enforcement

The `_run_oracle_evaluation()` function takes EXACTLY these parameters:

```python
def _run_oracle_evaluation(
    root_cause: str,
    fix_strategy: str,
    case: dict,
    config: ExperimentConfig,
) -> dict:
```

It does NOT take:
- `exec_result` (execution outcome)
- `classifier_result` (classifier judgment)
- `code` (reconstructed/generated code)
- `recon` (reconstruction result)
- `ast_result` (AST evaluation)

**Enforcement:** The function signature excludes execution and classifier data. It is called BEFORE those stages. Even if a developer adds parameters later, the call site cannot pass what doesn't exist yet.

### Call site enforcement

In `execution_v2.py`, the call order ensures no-leakage:

```python
artifact = normalize_generation_v2(...)          # step 5: reasoning available
oracle_result = _run_oracle_evaluation(          # step 5a: oracle runs HERE
    root_cause=artifact.raw_root_cause,
    fix_strategy=artifact.raw_fix_strategy,
    case=case,
    config=config,
)
recon, code, exec_result = _reconstruct_and_execute(...)  # step 6: execution
classifier_result = _classify_reasoning(...)               # step 7: classifier
```

Oracle is called at step 5a. `exec_result` doesn't exist until step 6. `classifier_result` doesn't exist until step 7. Leakage is impossible by construction.

### Documenting the contract

The function docstring MUST state:

```python
"""Run oracle reasoning evaluation.

NO LEAKAGE CONTRACT: This function must NEVER receive or access:
- execution results
- classifier results
- reconstructed/generated code
- AST evaluation results
It evaluates ONLY the model's stated reasoning against ground truth.
"""
```

---

## 6. Trace Identifiers

### Existing identifiers in WAL events

| Field | Example | Scope |
|-------|---------|-------|
| `work_id` | `gpt-4.1-nano__baseline_v2__trial_001__alias_config_a` | One case × model × condition × trial |
| `instance_id` | `...alias_config_a__attempt_001` | One work_id + attempt number |
| `trace_id` | `9f553534bd2c41ef9151eb12a0c9b5e6` | UUID for the trace chain |
| `event_id` | `...attempt_001__000006` | Unique per event within trace |
| `trial` | `1` | Trial index |
| `attempt` | `1` | Attempt index (always 1 for baseline) |

### What's already sufficient

The existing identifiers are adequate for per-attempt alignment:
- `work_id` identifies the case × model × condition × trial
- `attempt` (or trajectory index) identifies the attempt within a retry chain
- `trace_id` links all events in a trace

### No new identifiers needed

The plan does NOT introduce new identifier fields. The existing `work_id + attempt` tuple uniquely identifies every attempt. The trajectory array index serves as the retry iteration ID.

### For dashboard joins

```python
# Per-attempt join key:
join_key = (case_id, model, condition, trial_idx, attempt_idx)
```

---

## 7. Classifier-Oracle Disagreement Tracking

### Derived field: `reasoning_disagreement`

Computed during event assembly (NOT by oracle or classifier — by the metrics layer):

```python
def _compute_reasoning_disagreement(classifier_result, oracle_result):
    """Compare classifier and oracle reasoning judgments."""
    cls_correct = classifier_result.mechanism_identified == "CORRECT"
    
    oracle_truth = oracle_result.get("reasoning_truth", "UNASSESSED")
    if oracle_truth == "UNASSESSED":
        return {"disagreement": None, "type": "oracle_not_available"}
    
    oracle_correct = oracle_truth in ("CORRECT", "PARTIAL")
    
    if cls_correct == oracle_correct:
        return {"disagreement": False, "type": "agreement"}
    elif cls_correct and not oracle_correct:
        return {"disagreement": True, "type": "classifier_overcall"}
    else:
        return {"disagreement": True, "type": "classifier_undercall"}
```

### WAL field

```json
{
    "payload": {
        "reasoning_disagreement": {
            "disagreement": true,
            "type": "classifier_overcall"
        }
    }
}
```

### Handling edge cases

| Classifier | Oracle | Disagreement type |
|-----------|--------|------------------|
| CORRECT | CORRECT | agreement |
| CORRECT | PARTIAL | agreement (PARTIAL counted as correct) |
| CORRECT | WRONG | classifier_overcall |
| CORRECT | UNJUDGABLE | oracle_not_available |
| CORRECT | UNASSESSED | oracle_not_available |
| WRONG | CORRECT | classifier_undercall |
| WRONG | WRONG | agreement |
| N/A | any | classifier_not_available |

### Dashboard exposure

The Three-Axis Evaluation tab gains a "Classifier-Oracle Disagreement" section:
- Overall disagreement rate
- Disagreement rate by model
- Disagreement rate by family
- Overcall vs undercall split

---

## 8. Oracle Coverage Accounting

### `oracle_coverage_status` field

Derived from `payload.oracle.status`:

| WAL status | Coverage status | Meaning |
|-----------|----------------|---------|
| `SUCCESS` | `evaluated` | Oracle ran and produced a label |
| `SKIPPED` | `skipped_no_reasoning` | Reasoning text too short/missing |
| `FAILURE` | `oracle_failed` | LLM call failed |
| `PARSE_ERROR` | `oracle_parse_error` | LLM returned unparseable response |
| `DISABLED` | `oracle_disabled` | Intentionally turned off via config |
| (field absent) | `not_present_legacy` | Old WAL format, no oracle field |

### How this affects metrics

```python
# Analysis must compute metrics only on oracle-evaluated events:
oracle_evaluated = df[df["oracle_coverage_status"] == "evaluated"]

# Report coverage prominently:
coverage_rate = len(oracle_evaluated) / len(df)
# If coverage < 90%, analysis should warn about potential bias
```

### Bias avoidance

Oracle is SKIPPED when reasoning text is too short (<20 chars). This means SKIPPED events are disproportionately parse failures and malformed responses. Analyses conditioned on oracle must report the skip rate and acknowledge that skipped events are systematically different from evaluated events.

---

## 9. WAL Atomicity Guarantee

### The guarantee

Every `case.end` WAL event MUST contain ALL of:
- `payload.oracle` (or explicit status explaining absence)
- `payload.classification` (classifier results)
- `payload.evaluation` (3-axis taxonomy)
- `payload.ast_eval` (AST verification)
- `payload.execution_category` (execution result)

### Implementation

All results are computed BEFORE the event dict is assembled. The `_assemble_result()` function (line 705) receives all results as parameters and constructs the event dict in memory. The `logger.end_case()` call (line 797) writes the complete dict atomically.

**No partial writes possible:** The event dict is built entirely in memory, then written as one JSON line to the WAL. If any upstream computation fails (oracle timeout, classifier crash), the event is still emitted with explicit failure status fields — never omitted.

### Failure handling in assembly

```python
def _assemble_result(..., oracle_result, ...):
    ev = assemble_v2_result(...)
    
    # Oracle: always present, even on failure
    ev["oracle"] = oracle_result  # has status=FAILURE/SKIPPED if not SUCCESS
    
    # Classifier: always present, even on failure
    ev["classification"] = { ... }  # has classifier_ran=False if skipped
    
    # Evaluation: always present
    ev["evaluation"] = evaluation
    
    # AST: always present
    ev["ast_eval"] = ast_result.to_dict()
    
    return ev
```

### What if oracle times out?

The oracle LLM call has a 30-second timeout. If it times out:
```json
{"oracle": {"status": "FAILURE", "reasoning_truth": "UNASSESSED", "error": "timeout after 30s"}}
```

The event is still emitted with all other fields intact. The oracle section explicitly records the failure.

---

## 10. Exact WAL Schema (v3.1)

```json
{
    "_schema_version": "v3.1",
    
    "payload": {
        "...existing v3 fields...",
        
        "oracle": {
            "version": "inline_v1",
            "status": "SUCCESS|FAILURE|SKIPPED|PARSE_ERROR|DISABLED",
            "reasoning_truth": "CORRECT|PARTIAL|WRONG|UNJUDGABLE|UNASSESSED",
            "justification": "string",
            "error": "string|null",
            "latency_ms": 340
        },
        
        "reasoning_disagreement": {
            "disagreement": true,
            "type": "classifier_overcall|classifier_undercall|agreement|oracle_not_available|classifier_not_available"
        },
        
        "trajectory": [
            {
                "attempt": 0,
                "pass": true,
                "oracle": {
                    "version": "inline_v1",
                    "status": "SUCCESS",
                    "reasoning_truth": "CORRECT",
                    "justification": "...",
                    "error": null,
                    "latency_ms": 310
                },
                "...existing trajectory fields..."
            }
        ]
    }
}
```

### Field semantics (complete)

| Field | Type | Nullable | Allowed values | Semantics |
|-------|------|----------|---------------|-----------|
| `_schema_version` | str | No | "v3.1" | WAL schema version |
| `oracle.version` | str | No | "inline_v1" | Oracle evaluator version |
| `oracle.status` | str | No | SUCCESS, FAILURE, SKIPPED, PARSE_ERROR, DISABLED | Whether oracle completed |
| `oracle.reasoning_truth` | str | No | CORRECT, PARTIAL, WRONG, UNJUDGABLE, UNASSESSED | Oracle label. UNASSESSED = not evaluated |
| `oracle.justification` | str | No | free text (empty OK) | Oracle's reasoning |
| `oracle.error` | str | Yes | error description | null = no error |
| `oracle.latency_ms` | int | No | ≥ 0 | LLM call time |
| `reasoning_disagreement.disagreement` | bool | Yes | true, false, null | null = one signal unavailable |
| `reasoning_disagreement.type` | str | No | see table above | Disagreement classification |

---

## 11. Backward Compatibility

### Old WAL records (v2, v3.0)

| Missing field | Default behavior |
|--------------|-----------------|
| `_schema_version` absent | Treat as "v2" |
| `payload.oracle` absent | `oracle_coverage_status = "not_present_legacy"` |
| `trajectory[].oracle` absent | Per-attempt oracle = UNASSESSED |
| `reasoning_disagreement` absent | Compute from available fields or null |

### Dashboard fallback chain

```python
# 1. Inline oracle (v3.1+)
oracle_truth = payload.get("oracle", {}).get("reasoning_truth")

# 2. Sidebar-loaded oracle labels (legacy)
if oracle_truth is None or oracle_truth == "UNASSESSED":
    oracle_truth = sidebar_oracle_labels.get(join_key)

# 3. Not available
if oracle_truth is None:
    oracle_truth = "UNASSESSED"
```

### No migration needed

Old WAL files are never rewritten. The schema addition is purely additive.

---

## 12. Dashboard and Analysis Implications

### Oracle tab behavior

1. If `payload.oracle.reasoning_truth` exists and is not UNASSESSED → display inline oracle data
2. If absent → check sidebar oracle labels → display if available
3. If neither → show classifier reasoning with note: "No oracle evaluation available. Showing classifier-based reasoning."
4. Display source indicator: "Source: inline oracle v1" or "Source: offline oracle labels" or "Source: classifier (no oracle)"

### Disagreement section (NEW)

When inline oracle is available, the Oracle tab gains:
- Overall classifier-oracle agreement rate
- Overcall vs undercall breakdown
- Disagreement rate by model, condition, family
- Example events where they disagree

### Analysis script preference

```python
# New runs: use inline oracle directly
# Old runs: join with offline oracle artifacts
# Mixed: use inline where available, fall back to offline
```

---

## 13. Validation Plan

### A. Classifier vs Oracle disagreement analysis

After first run with inline oracle:
1. Compute overall disagreement rate (expected: ~7-10% based on prior 92-93% agreement)
2. Stratify by case family — identify families where classifier overcalls most
3. Compare with offline oracle results to verify consistency

### B. Coverage validation

1. Compute `oracle_coverage_status` distribution across a full ablation
2. Expected: ~95% evaluated, ~5% skipped (parse failures)
3. If >10% skipped → investigate whether reasoning extraction is broken

### C. Retry consistency

1. For retry chains, check: does oracle verdict improve across attempts?
2. Expected: reasoning_truth should become more CORRECT in later attempts (if critique helps reasoning)
3. If oracle is inconsistent across attempts with identical reasoning → oracle is noisy

### D. Inline vs offline comparison

1. Run offline oracle on 200 events from a v3.1 run
2. Compare with inline oracle labels
3. Expected: >99% agreement (any disagreement = LLM non-determinism)
4. If <95% agreement → implementation bug

### E. Atomicity check

1. Grep WAL for events where `oracle.status` is missing (should be 0 in v3.1)
2. Verify every `case.end` event has all 4 sections present

---

## 14. Rollout Plan

### Phase 0: Audit (0.5 day)
**Goal:** Confirm integration points, verify oracle import paths.
**Files:** Read `execution_v2.py`, `retry_v2.py`, `reasoning_truth.py`
**Exit criteria:** Integration point confirmed at line 133 of execution_v2.py

### Phase 1: Schema + config (0.5 day)
**Goal:** Add `_schema_version`, oracle config key, dashboard schema fields.
**Files:** `dashboard/schema.py`, config YAMLs, `dashboard/data/evaluation_fields.py`
**Exit criteria:** Dashboard reads (empty) oracle fields without crash.

### Phase 2: Inline oracle in baseline path (1 day)
**Goal:** `_run_oracle_evaluation()` in `execution_v2.py`, `payload.oracle` in event.
**Files:** `core/pipeline/orchestration/execution_v2.py`
**Exit criteria:** WAL events from baseline run contain `payload.oracle` with valid labels.

### Phase 3: Inline oracle in retry path (0.5 day)
**Goal:** Oracle per attempt in `retry_v2.py` trajectory entries.
**Files:** `core/pipeline/orchestration/retry_v2.py`
**Exit criteria:** Trajectory entries contain per-attempt oracle results.

### Phase 4: Disagreement tracking + dashboard (1 day)
**Goal:** Compute `reasoning_disagreement`, update dashboard Oracle tab.
**Files:** `execution_v2.py`, `dashboard/views/oracle.py`, `dashboard/data/evaluation_fields.py`, `dashboard/leg_scanner.py`
**Exit criteria:** Dashboard shows inline oracle + disagreement analysis without sidebar checkbox.

### Phase 5: Validation (0.5 day)
**Goal:** Run all validation checks from Section 13.
**Exit criteria:** All checks pass. Inline oracle matches offline oracle >99%.

### Phase 6: Documentation + legacy handling (0.5 day)
**Goal:** Update CLAUDE_RULES docs, mark offline script as legacy.
**Files:** `CLAUDE_RULES/`, `CLAUDE.md`, `scripts/run_oracle_eval.py` (deprecation notice)
**Exit criteria:** New runs never need offline oracle. Old runs still work.

**Total: ~4.5 days**

---

## 15. Concrete Next-Step Checklist

- [ ] Add `oracle.inline_enabled` and `oracle.model` to default.yaml
- [ ] Add `_schema_version: "v3.1"` to event assembly
- [ ] Implement `_run_oracle_evaluation()` in execution_v2.py with no-leakage signature
- [ ] Call it after line 133 (artifact normalization), before line 134 (execution)
- [ ] Add `oracle_result` parameter to `_assemble_result()`
- [ ] Include `payload.oracle` in assembled event
- [ ] Add oracle per-attempt in retry_v2.py trajectory dict (line 508)
- [ ] Implement `_compute_reasoning_disagreement()` in execution_v2.py
- [ ] Include `payload.reasoning_disagreement` in assembled event
- [ ] Add oracle + disagreement fields to `dashboard/schema.py`
- [ ] Update `dashboard/leg_scanner.py` trajectory expansion to extract oracle
- [ ] Update `dashboard/data/evaluation_fields.py` to read inline oracle
- [ ] Update `dashboard/views/oracle.py` to display inline oracle and disagreement
- [ ] Run end-to-end test: baseline with oracle enabled
- [ ] Run end-to-end test: retry with oracle enabled
- [ ] Run 200-event inline vs offline comparison
- [ ] Verify backward compat on old v2 WAL
