# Forensic Audit: Parsing/Recovery Layer and Retry Mechanics Interaction

**Date:** 2026-04-03
**Scope:** Signal flow from parser_v2 through retry_v2, into dashboard attempt table and metrics.
**Verdict:** Multiple measurement integrity violations found. Retry retries unconditionally regardless of parse state. Per-attempt parse/routing metadata is not recorded in trajectory entries and is therefore lost across attempts in retry chains.

---

## 1. CURRENT STATE MAP -- Every Field, Where Produced, Where Consumed

### 1.1 Parser Fields (ParsedGenerationV2) -- `core/pipeline/parsing/parser_v2.py`

| Field | Type | Set By | Meaning |
|-------|------|--------|---------|
| `parse_status` | str | `_validate_and_build()` L257 / `_fail()` L242 | "success", "partial", "invalid", "failed" |
| `parse_valid` | bool | `_validate_and_build()` L273 (always True on non-fail) / default False | Whether a JSON dict was extracted at all |
| `schema_valid` | bool | `_validate_and_build()` L256 | Whether extracted dict passes schema validation |
| `parser_tier` | str | Each tier function | "execution", "format", "recovery" |
| `full_json` | dict/None | `_validate_and_build()` L267 | The extracted JSON dict |
| `files_dict` | dict/None | `_validate_and_build()` L252 | The `files` sub-dict if present |
| `parse_error` | str/None | `_validate_and_build()` L270 / `_fail()` L244 | Error description on failure |
| `recovery_type` | str/None | Recovery parser phases | "raw_block_extraction", "triple_quote_fix", etc. |
| `recovery_steps` | list[str] | Recovery parser | Phase-by-phase trace |
| `execution_equivalent` | bool | Set externally in execution_v2 L402-406 / retry_v2 L567-569 | Whether recovery produced same JSON as strict |
| `schema_normalization_applied` | bool | `_maybe_normalize_schema()` L525 | Whether code->files rename was applied |
| `possible_mis_extraction` | bool | `_validate_and_build()` L265 | Heuristic: many required keys missing |
| `format_valid` | bool | Format parser only | Whether output followed exact format rules |
| `format_error` | str/None | Format parser only | Specific format violation type |

**Critical observation:** `parse_valid=True` means a JSON dict was successfully extracted (L273 in `_validate_and_build`). It does NOT mean schema validation passed. A parse can be `parse_valid=True` but `schema_valid=False`.

### 1.2 Routing Fields (RoutingDecision) -- `core/pipeline/orchestration/execution_v2.py`

| Field | Type | Set At | Meaning |
|-------|------|--------|---------|
| `selected_source` | str | `_select_artifact()` L249-291 | "strict", "recovery", "none" |
| `strict_parse_valid` | bool | L261 | Whether execution parser extracted a dict |
| `recovery_parse_valid` | bool | L262 | Whether recovery parser extracted a dict |
| `strict_structurally_valid` | bool | L261 | Whether strict output has correct file structure |
| `recovery_structurally_valid` | bool | L262 | Whether recovery output has correct file structure |
| `recovery_used` | bool | L277 | True only when recovery was selected for execution |
| `divergence_detected` | bool | L264-268 | Both parsed but produced different JSON |
| `structural_errors` | list[str] | L290 | Combined error list |

### 1.3 Reconstruction Fields (ReconstructionResult) -- `core/pipeline/reconstructor.py`

| Field | Type | Set At | Meaning |
|-------|------|--------|---------|
| `status` | str | Various gates L111 | SUCCESS, RECON_MISSING_FILES, RECON_EMPTY_FILE, RECON_SENTINEL_MISMATCH, RECON_INVALID_CODE, RECON_SENTINEL_MIXED |
| `recovery_applied` | bool | L431/L451 | Whether content normalization was applied |
| `recovery_types` | list[str] | L414 | "fence_stripped", "newlines_unescaped", "file_value_prefix_stripped", etc. |
| `content_normalized` | bool | L413 | Same as recovery_applied |

### 1.4 Where Fields Are Logged (execution_v2 vs retry_v2)

**execution_v2.py** (`_build_reconstruction_section()` L834-866):
- Logs ALL routing and reconstruction fields into `ev["reconstruction"]`
- Logs ALL parse tier diagnostics into `ev["v2_parse_tiers"]` (L959-974)
- Dashboard schema.py maps these to columns (L213-299)

**retry_v2.py** -- DOES NOT LOG THESE FIELDS:
- No `ev["reconstruction"]` section (grep confirmed: zero matches)
- No `ev["v2_parse_tiers"]` section
- Trajectory entries (L654-672) store only:
  - `parse_valid` (L665) -- a SINGLE boolean, NOT the decomposed strict/recovery pair
  - `code_length` (L666)
  - No `selected_source`, no `recovery_used`, no `strict_parse_valid`, no `recovery_parse_valid`
  - No `recon.status`, no `recovery_types`, no `content_normalized`

### 1.5 Dashboard Schema Extraction (`dashboard/schema.py` L213-299)

The schema defines these columns which ONLY exist in `extra.reconstruction.*`:
- `parsing_mode` (source: `extra.reconstruction.parsing_mode`)
- `strict_parse_valid` (source: `extra.reconstruction.strict_parse_valid`)
- `recovery_parse_valid` (source: `extra.reconstruction.recovery_parse_valid`)
- `recovery_used` (source: `extra.reconstruction.recovery_used`)
- `execution_eligible` (source: `extra.reconstruction.execution_eligible`)

For retry events, `ev["reconstruction"]` is never set. Therefore:
- **All these fields will be None for every attempt row in a retry chain.**
- The dashboard cannot distinguish strict from recovered parsing in retry data.

---

## 2. RETRY ELIGIBILITY LOGIC -- Exact Code Paths

### 2.1 Retry Loop Structure (`retry_v2.py` L541-727)

```
for k in range(max_iterations):        # L541
    if elapsed > max_total_seconds:     # L543 -- timeout guard
        break
    try:
        prompt = ...                    # L548
        raw_response = call_model(...)  # L554
        parse → route → oracle → normalize → reconstruct → classify → AST → execute
        trajectory.append(entry)        # L654
    except Exception:
        trajectory.append(INCOMPLETE)   # L676
        passed = False

    if not passed and k < max_iterations - 1:    # L688
        # Build hints for next iteration
        test_feedback = ...
        critique = ...

    prev_code = code                    # L721
    prev_raw = raw_response             # L722

    if passed:                          # L724
        break
```

### 2.2 Retry Decision Logic

**The retry decision is made at L688 and L724:**
- Line 688: `if not passed and k < max_iterations - 1:` -- prepare hints for next attempt
- Line 724: `if passed: break` -- stop only on execution pass

**There is NO check of parse state before retrying.** The loop structure is:

1. Loop runs unconditionally from `k=0` to `k=max_iterations-1`
2. Only `break` conditions: timeout (L544) or `passed=True` (L725)
3. Between attempts, only execution pass/fail determines behavior
4. Parse state is checked ONLY for classifier hint generation (L693): `if use_classifier_hint and parsed_gen.parse_status == "success"`

### 2.3 What Happens When Both Strict and Recovery Fail

If attempt 0 produces `strict_parse_valid=False AND recovery_parse_valid=False`:

1. `routing.selected_source = "none"` (execution_v2.py L278-279)
2. `parsed_gen = parse_exec` (the strict/failed one, since selected_source != "recovery", L571)
3. `parsed_gen.parse_valid = False`, `parsed_gen.files_dict = None`
4. Reconstruction is skipped (L600: `if parsed_gen.files_dict:` is False)
5. `recon = ReconstructionResult(status="RECON_MISSING_FILES", files={})`
6. `code = ""` (no full_code_parts)
7. Classifier is skipped (L615: `parsed_gen.parse_status != "success"`)
8. Execution runs anyway via `exec_canonical` (L634) with no code -> fails
9. `passed = False`
10. **Loop continues to attempt 1** (L688: `not passed and k < max_iterations - 1`)
11. Retry prompt is built with `prev_raw` = the unparseable raw response
12. **The model is re-prompted with the same schema instruction**

**VERDICT: Retry ALWAYS retries regardless of parse state. There is no parse-state gate.**

### 2.4 Is There ANY Code That Says "Don't Retry if Parse Failed"?

**No.** Exhaustive search of retry_v2.py:
- `parse_valid` appears at L568, L665, L480 -- never in a retry-decision conditional
- `parse_status` appears at L615, L621, L693 -- only for classifier skipping and hint generation
- `selected_source` appears at L571 -- only for routing, not retry gating
- The word "retry" combined with "parse" never appears in a conditional guard

---

## 3. SIGNAL COLLAPSE FINDINGS -- Where Strict/Recovered Are Merged

### 3.1 Collapse Point 1: Trajectory Entry (retry_v2.py L665)

The trajectory entry stores:
```python
"parse_valid": parsed_gen.parse_valid,    # L665
```

This is the parse_valid of the SELECTED artifact (strict or recovery). The following are lost:
- Which parser produced it (`selected_source`)
- Whether recovery was used (`recovery_used`)
- Whether strict failed but recovery succeeded
- Recovery type and steps
- Execution equivalence

**Impact:** When the dashboard reads trajectory entries, it cannot distinguish:
- "Strict parsed successfully" from "Recovery saved it"
- "Both failed" from "Strict failed, recovery not attempted"

### 3.2 Collapse Point 2: Final Event Assembly (retry_v2.py L758-782)

The final event for a retry chain reconstructs evaluation from `trajectory[best_idx]`:
```python
routing_valid = best.get("parse_valid", False)          # L411
reconstruction_success = routing_valid and best.get("code_length", 0) > 0  # L412
```

This derives `routing_valid` from the collapsed `parse_valid` boolean. The real routing decision (which might have been "recovery") is lost. The `reconstruction_success` is approximated from `code_length > 0` rather than from the actual `recon.status`.

### 3.3 Collapse Point 3: Dashboard Attempt Table (leg_scanner.py L229-286)

For retry chains, the scanner extracts per-attempt data from trajectory entries:
```python
row["exec_pass"] = t_exec.get("pass", False)     # L241
row["code_length"] = t_entry.get("code_length")   # L284
```

It does NOT extract:
- `parse_valid` from trajectory entries (though it's available)
- Any routing/reconstruction metadata (not available in trajectory)

The base_row inherits `parse_status`, `recon_status`, `parsing_mode`, `strict_parse_valid`, `recovery_parse_valid`, `recovery_used` from the top-level event fields. But for retry events, these top-level fields come from the FINAL/BEST attempt only. All non-final attempts inherit the final attempt's parse metadata.

**Impact:** In a 3-attempt retry chain where attempt 0 had parse failure but attempt 2 had strict success, ALL three rows will show the same `parse_status`/`recovery_used` values from the best attempt's top-level event.

### 3.4 Collapse Point 4: Evaluation Fields (evaluation_fields.py L70-80)

The V2 fallback path derives `serialization_success`:
```python
parse_ok = _safe_str_col(out, "parse_status").eq("success")
recon_ok = ~_safe_str_col(out, "reconstruction_status").str.contains("fail|invalid|error")
eligible = _safe_bool_col(out, "execution_eligible", default=True)
out["serialization_success"] = parse_ok & recon_ok & recon_v2 & eligible
```

For retry events where these columns are None (because `ev["reconstruction"]` is never set), the defaults produce:
- `parse_status` = whatever was extracted from `payload.v2_artifact.parse_status` (may be None for retries)
- `execution_eligible` defaults to True
- This means serialization_success may be incorrectly True for retry attempts that had parse failures

### 3.5 Collapse Point 5: Transforms (transforms.py L8-17)

```python
out["parse_failure"] = (
    ~out.get("execution_eligible", pd.Series(False, ...)).fillna(False)
    & out.get("parse_status", ...).fillna("").str.contains("parse", ...)
)
```

The `parse_failure` derived column depends on `execution_eligible` which is:
- Correctly set for execution_v2 events (from `extra.reconstruction.execution_eligible`)
- Always None for retry events (no reconstruction section) -> `fillna(False)` -> `~False = True`
- Combined with `parse_status` containing "parse" -> this partially works but the `execution_eligible` leg is always wrong for retries

### 3.6 Collapse Point 6: Metrics Registry (metrics_registry.py)

All retry metrics operate on `exec_pass` only:

- `_retry_recovery_rate` (L45-60): Compares `first_pass` vs `final_pass` using `exec_pass`. No conditioning on parse state.
- `_pct_improved_by_retry` (L72-83): Same -- `exec_pass` only.
- `_pct_degraded_by_retry` (L86-98): Same -- `exec_pass` only.
- `_trajectory_distribution` (L101-107): Uses `trajectory_type` which is derived from `exec_pass` sequence.

**None of these metrics condition on parse state, recovery_used, or parsing_mode.**

A chain where attempt 0 had parse failure (no code ran) and attempt 1 succeeded is counted as "improved" -- identical to a chain where attempt 0 had valid code that simply failed tests.

---

## 4. CHAIN-LEVEL SIGNAL LOSS -- What's Lost Across Attempts

### 4.1 Fields Present in Trajectory Entry

Per attempt (retry_v2.py L654-672):
- `attempt`, `status`, `execution` (pass/score/category), `oracle`, `classifier`, `ast`, `reasoning_disagreement`
- `parse_valid` (single collapsed boolean)
- `code_length`
- `retry_mode`, `had_test_feedback`, `had_classifier_hint`
- `mismatch_critique`, `mismatch_variant`

### 4.2 Fields Computed Per Attempt But NOT Stored

| Field | Computed At | Why It's Lost |
|-------|------------|---------------|
| `routing.selected_source` | L570 | Not added to trajectory entry |
| `routing.strict_parse_valid` | L570 (via _select_artifact) | Not added |
| `routing.recovery_parse_valid` | L570 | Not added |
| `routing.recovery_used` | L570 | Not added |
| `routing.divergence_detected` | L570 | Not added |
| `parse_exec.parse_status` | L565 | Not added |
| `parse_exec.parse_error` | L565 | Not added |
| `parse_rec.recovery_type` | L566 | Not added |
| `parse_rec.recovery_steps` | L566 | Not added |
| `parse_rec.execution_equivalent` | L567-569 | Not added |
| `recon.status` | L599-601 | Not added |
| `recon.recovery_applied` | L601 | Not added |
| `recon.recovery_types` | L601 | Not added |
| `recon.syntax_errors` | L601 | Not added |
| `recon.content_normalized` | L601 | Not added |

### 4.3 Fields Lost At Dashboard Level

For single-shot (execution_v2) events, the scanner uses base_row from event-level fields. These are correctly populated because execution_v2 writes `ev["reconstruction"]` and `ev["v2_parse_tiers"]`.

For retry events:
- `base_row` is populated from event-level fields
- But retry_v2 does NOT write `ev["reconstruction"]` or `ev["v2_parse_tiers"]`
- Therefore `parsing_mode`, `strict_parse_valid`, `recovery_parse_valid`, `recovery_used`, `execution_eligible`, `recon_status` are all None
- These None values are inherited by ALL attempt rows in the chain
- Per-attempt overrides (L239-285) do NOT override any of these fields

---

## 5. CRITICAL BUGS

### BUG 1: Retry Retries Unrecoverable Parse Failures (Severity: MEASUREMENT)

**File:** `retry_v2.py` L541-725
**Evidence:** No parse-state conditional anywhere in the retry loop.

When the LLM produces output that neither the strict nor recovery parser can handle (e.g., no JSON at all, or malformed beyond repair), the retry loop:
1. Wastes an API call re-prompting with the same schema
2. Records the attempt as a legitimate retry
3. Inflates `n_attempts` and `avg_attempts` metrics
4. Conflates "parse failure retries" with "code-quality retries" in all downstream analysis

This violates measurement integrity because retry metrics cannot distinguish "the model produced parseable but wrong code" from "the model produced garbage that couldn't be parsed."

### BUG 2: Retry Events Missing Reconstruction Section (Severity: DATA LOSS)

**File:** `retry_v2.py` L758-782 (event assembly)
**Evidence:** `ev["reconstruction"]` is never set. Grep returns zero matches.

The dashboard schema expects `extra.reconstruction.*` fields. For retry events, these are all None. This means:
- `parsing_mode` is None for all retry data
- `recovery_used` is None for all retry data
- `execution_eligible` is None for all retry data
- The dashboard cannot accurately compute `serialization_success` for retry events

### BUG 3: Per-Attempt Parse/Routing Metadata Not in Trajectory (Severity: DATA LOSS)

**File:** `retry_v2.py` L654-672 (trajectory entry construction)
**Evidence:** Trajectory entry contains `parse_valid` (L665) but NOT `selected_source`, `recovery_used`, `strict_parse_valid`, `recovery_parse_valid`, `recon_status`.

Consequence: The dashboard cannot know, for any given retry attempt, whether:
- The output was parsed strictly or via recovery
- The reconstruction succeeded or failed
- Content normalization was applied

### BUG 4: Reconstruction Success Approximated from code_length (Severity: MEASUREMENT)

**File:** `retry_v2.py` L412
```python
reconstruction_success = routing_valid and best.get("code_length", 0) > 0
```

`code_length > 0` is a proxy for `recon.status == "SUCCESS"`. But reconstruction can produce files (`code_length > 0`) with status `RECON_INVALID_CODE` (syntax errors in files). This approximation silently classifies some reconstruction failures as successes.

### BUG 5: Dashboard Inherits Best-Attempt Parse State for All Attempts (Severity: MEASUREMENT)

**File:** `leg_scanner.py` L237-286
**Evidence:** `base_row` is populated from event-level fields. Per-attempt overrides do not include `parse_status`, `recon_status`, `parsing_mode`, or any reconstruction field. But `parse_valid` IS in the trajectory entry and IS extracted... wait, let me re-check.

Actually, re-examining: `parse_valid` from the trajectory entry is NOT extracted into the row. The trajectory loop (L239-285) sets `exec_pass`, `score`, `exec_category`, oracle fields, classifier fields, ast fields, disagreement, but NOT `parse_valid`. The `parse_valid` field that exists in the trajectory entry is silently dropped.

This means `parse_status` and `parse_valid` for all rows in a retry chain come from the base_row (event-level), which reflects either the best attempt's state or a default value. Non-final attempts that had different parse outcomes are misrepresented.

---

## 6. REQUIRED FIXES (Minimal Changes)

### Fix 1: Add Parse/Routing Metadata to Trajectory Entries

**File:** `retry_v2.py` around L654-672

Add to the trajectory entry dict:
```python
"selected_source": routing.selected_source,
"strict_parse_valid": routing.strict_parse_valid,
"recovery_parse_valid": routing.recovery_parse_valid,
"recovery_used": routing.recovery_used,
"parse_status": parsed_gen.parse_status,
"parse_error": parsed_gen.parse_error,
"recovery_type": parse_rec.recovery_type,
"recon_status": recon.status,
"recon_recovery_applied": recon.recovery_applied,
"recon_recovery_types": recon.recovery_types,
```

### Fix 2: Add Reconstruction Section to Retry Final Event

**File:** `retry_v2.py` around L766-782

After `ev["evaluation"] = ...`, add:
```python
# Build reconstruction section from best attempt's trajectory data
# (requires Fix 1 to be in place)
ev["reconstruction"] = _build_retry_reconstruction_section(best)
```

Alternatively, compute and store the routing/recon for the best attempt separately.

### Fix 3: Extract Per-Attempt Parse Fields in Dashboard Scanner

**File:** `leg_scanner.py` around L239-285

Add per-attempt overrides:
```python
row["parse_valid"] = t_entry.get("parse_valid")  # already in trajectory
row["selected_source"] = t_entry.get("selected_source")  # after Fix 1
row["recovery_used"] = t_entry.get("recovery_used")
row["recon_status"] = t_entry.get("recon_status")
row["parse_status_attempt"] = t_entry.get("parse_status")  # per-attempt
```

### Fix 4: Add Parse-State Guard to Retry Loop (Design Decision Required)

**File:** `retry_v2.py` around L688

Option A (conservative): Log parse failures but still retry (the model might do better on retry):
```python
if not passed and k < max_iterations - 1:
    if not parsed_gen.parse_valid:
        _log.warning("RETRY_PARSE_FAIL %s attempt %d: retrying despite parse failure", cid, k)
```

Option B (strict): Don't retry unrecoverable parse failures:
```python
if not passed and k < max_iterations - 1:
    if routing.selected_source == "none":
        _log.warning("RETRY_ABORT %s: unrecoverable parse failure at attempt %d", cid, k)
        break
```

**Recommendation:** Option A initially (don't change behavior, just observe), then evaluate data to decide if Option B improves signal quality.

### Fix 5: Condition Retry Metrics on Parse State

**File:** `metrics_registry.py`

Add new metrics:
```python
"retry_recovery_rate_parseable": {
    "compute": _retry_recovery_rate_parseable,
    "description": "Recovery rate excluding chains with parse failures",
}
```

Where `_retry_recovery_rate_parseable` filters out chains where the first attempt had `parse_valid=False`.

---

## 7. DASHBOARD DESIGN -- New Tables/Views Needed

### 7.1 Per-Attempt Parse State Table

A new view showing, for each attempt in a retry chain:
| chain_id | attempt | selected_source | strict_valid | recovery_valid | recovery_used | recon_status | exec_pass |

This requires Fix 1 and Fix 3.

### 7.2 Parse-Aware Retry Metrics Panel

| Metric | Current | Needed |
|--------|---------|--------|
| retry_recovery_rate | All chains | Split by: parseable_first_attempt / unparseable_first_attempt |
| pct_improved | All chains | Same split |
| pct_degraded | All chains | Same split |
| avg_attempts | All chains | Same split |

### 7.3 Recovery Usage View

A summary table showing:
- How many attempts used strict vs recovery vs none
- Recovery type breakdown (raw_block_extraction, triple_quote_fix, etc.)
- Whether recovery diverged from strict
- Whether content normalization was applied at reconstruction level

### 7.4 Parse Failure Retry Analysis

For chains where attempt 0 had parse failure:
- Did subsequent attempts also fail to parse? (stagnation vs recovery)
- What was the parse error type?
- Did the retry prompt change anything about the output format?

### 7.5 Signal Flow Integrity Dashboard

A diagnostic view that for each chain verifies:
- Per-attempt `parse_valid` matches expected from `selected_source`
- `reconstruction_success` matches `recon_status == "SUCCESS"`
- No attempts with `exec_pass=True` but `parse_valid=False`

---

## APPENDIX: Line Number Reference

| File | Key Line | What |
|------|----------|------|
| `parser_v2.py` L29-57 | `ParsedGenerationV2` dataclass definition |
| `parser_v2.py` L273 | `parse_valid=True` always set in `_validate_and_build` |
| `parser_v2.py` L283-321 | `parse_v2_execution` -- strict parser |
| `parser_v2.py` L389-503 | `parse_v2_recovery` -- recovery parser |
| `execution_v2.py` L58-68 | `RoutingDecision` dataclass |
| `execution_v2.py` L249-291 | `_select_artifact` -- routing logic |
| `execution_v2.py` L834-866 | `_build_reconstruction_section` -- logged for single-shot |
| `execution_v2.py` L959-974 | `v2_parse_tiers` -- logged for single-shot |
| `retry_v2.py` L541 | Retry loop start |
| `retry_v2.py` L565-571 | Per-attempt parse + route |
| `retry_v2.py` L654-672 | Trajectory entry construction (missing routing fields) |
| `retry_v2.py` L688 | Retry decision (no parse check) |
| `retry_v2.py` L724 | Break on pass (only exit besides timeout) |
| `retry_v2.py` L766-782 | Final event assembly (no reconstruction section) |
| `retry_v2.py` L411-412 | reconstruction_success approximated from code_length |
| `leg_scanner.py` L229-286 | Trajectory entry extraction (missing parse_valid) |
| `evaluation_fields.py` L70-80 | V2 fallback serialization_success derivation |
| `metrics_registry.py` L45-60 | retry_recovery_rate (no parse conditioning) |
| `metrics_registry.py` L72-83 | pct_improved (no parse conditioning) |
| `metrics_registry.py` L86-98 | pct_degraded (no parse conditioning) |

---

## SUMMARY OF FINDINGS

1. **Retry is parse-blind.** The retry loop (`retry_v2.py` L541-725) retries unconditionally. There is zero code checking parse state before deciding to retry. Line 688 checks only `not passed`.

2. **Per-attempt parse/routing metadata is lost.** Trajectory entries store a single `parse_valid` boolean (L665) but not `selected_source`, `recovery_used`, `strict_parse_valid`, `recovery_parse_valid`, `recon_status`, or any recovery diagnostics.

3. **Retry events have no reconstruction section.** Unlike execution_v2 which writes `ev["reconstruction"]` (L899) and `ev["v2_parse_tiers"]` (L959), retry_v2 writes neither. Dashboard columns sourced from `extra.reconstruction.*` are all None for retry data.

4. **Dashboard inherits best-attempt metadata for all attempts.** The scanner (leg_scanner.py L237) uses `base_row` from event-level fields for all rows in a chain. Per-attempt parse_valid from trajectory entries is not extracted.

5. **All retry metrics are parse-agnostic.** `retry_recovery_rate`, `pct_improved`, `pct_degraded` compare only `exec_pass` across attempts, with no conditioning on whether the output was parseable, recovered, or unrecoverable.

6. **reconstruction_success is approximated.** In `_compute_evaluation_from_trajectory` (L412), reconstruction success is derived from `code_length > 0`, which conflates syntax-error reconstructions with actual successes.
