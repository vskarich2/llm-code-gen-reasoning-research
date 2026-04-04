# Addendum to fix_parser_evaluation_separation_v2.md

## Revised Sections: Fallback Policy, Extraction Selection, Invariants

**Date:** 2026-03-26
**Applies to:** fix_parser_evaluation_separation_v2.md
**Replaces:** Sections E.1, E.3, E.5, and Invariant F.6
**All other v2 sections remain unchanged.**

---

## E.1 (REVISED) — LEG-Reduction: Restricted Fallback

### Current Rule (v2): No fallback. REJECTED — too strict.

The v2 rule discards valid solutions when JSON is malformed but code exists in the raw output. The forensic analysis found 2/11 failures (18%) are Category B: the model produced correct code but the JSON structure was broken (e.g., brace nesting lost after a long code string). Under v2's no-fallback rule, this code is lost.

### New Rule: Restricted fallback for LEG, gated by JSON extraction failure

**Primary path**: Extract code from JSON `code` field via `parse_leg_reduction_output()`. If JSON parses and `code` field exists and is a non-empty string, this extraction is FINAL. No fallback runs.

**Restricted fallback ONLY IF**:
- JSON extraction fails entirely (`_extract_json()` returns None), OR
- JSON parses but `code` field is absent, OR
- JSON parses but `code` field is empty or not a string

**Fallback procedure** (when triggered):
1. Run `parse_model_response(raw_output)` — the standard 7-tier parser.
2. If it extracts non-empty code: use that code.
3. Mark the result:
   - `extraction_source = "fallback"`
   - `schema_compliant = False`
   - `parse_error = None` (code WAS extracted — this is not a code extraction failure)
   - `schema_violations` includes "LEG JSON extraction failed; code recovered via fallback"
4. If fallback also finds no code: hard failure (`code_extracted = False`, `parse_error` set).

**Fallback MUST NOT**:
- Run when JSON extraction succeeded and produced non-empty code (primary path takes precedence)
- Silently override a valid JSON extraction
- Produce a result without `extraction_source` being set

**Rationale**: The LEG prompt instructs the model to return JSON, but Category B failures show models sometimes break the JSON structure while still emitting valid Python code. The code is present in the raw output — `parse_model_response()` can find it via code block or substring extraction. Discarding it is a measurement error.

---

## E.3 (REVISED) — Retry Harness: Candidate Selection with Validation

### Current Rule (v2): Strict parser wins if it finds code. REJECTED — assumes strict extraction is always correct.

The strict parser (`parse_structured_output`) extracts code from the JSON `code` field. But JSON extraction can produce WRONG code in edge cases:
- Model put code in a markdown block INSIDE a JSON string (escaped newlines, truncated)
- JSON `code` field contains a partial snippet, while a ```python block in the same response contains the full fix
- JSON `code` field is a placeholder ("your code here") while real code is elsewhere

Blindly preferring strict JSON extraction over fallback extraction is not safe.

### New Rule: Extract BOTH candidates, select the best via validation

**Step 1 — Extract both candidates**:
```
strict_parsed = parse_structured_output(raw)
strict_code = strict_parsed["code"]      # from JSON "code" field

fallback_parsed = parse_model_response(raw)
fallback_code = fallback_parsed.get("code") or ""  # from 7-tier fallback
```

Both extractions ALWAYS run. This is a change from the current system where fallback only runs on strict failure.

**Step 2 — Build candidate set**:
```
candidates = []
if strict_code.strip():
    candidates.append(("strict", strict_code))
if fallback_code.strip() and fallback_code != strict_code:
    candidates.append(("fallback", fallback_code))
```

If both produce the same string, there is only one candidate (no conflict).

**Step 3 — Select best candidate via validation criteria**:

If only one candidate: use it.

If two candidates exist (strict and fallback produced DIFFERENT non-empty code):

| Criterion | Check | Eliminates |
|---|---|---|
| **C1: Syntax validity** | `ast.parse(candidate)` succeeds | Eliminates candidates that are not valid Python |
| **C2: Non-trivial content** | `len(candidate.strip()) >= 50` AND contains at least one `def ` or `class ` | Eliminates placeholders, stubs, and non-code text |
| **C3: Longer is better** (tiebreaker) | `len(candidate)` | Between two syntactically valid, non-trivial candidates, prefer the longer one (more likely to be the complete fix) |

**Selection algorithm**:
```
def select_best(candidates: list[tuple[str, str]]) -> tuple[str, str]:
    """Select best (source, code) from candidates.

    Returns (source_label, code_string).
    """
    if len(candidates) == 1:
        return candidates[0]

    # C1: Filter to syntax-valid candidates
    valid = []
    for source, code in candidates:
        try:
            ast.parse(code)
            valid.append((source, code))
        except SyntaxError:
            pass

    if len(valid) == 0:
        # Neither is valid Python — prefer strict (came from structured JSON)
        return candidates[0]
    if len(valid) == 1:
        return valid[0]

    # C2: Filter to non-trivial candidates
    nontrivial = []
    for source, code in valid:
        has_def = 'def ' in code or 'class ' in code
        long_enough = len(code.strip()) >= 50
        if has_def and long_enough:
            nontrivial.append((source, code))

    if len(nontrivial) == 0:
        # Both valid but trivial — prefer strict
        return valid[0]
    if len(nontrivial) == 1:
        return nontrivial[0]

    # C3: Tiebreaker — longer code
    return max(nontrivial, key=lambda x: len(x[1]))
```

**Step 4 — Record selection metadata**:
```
code_k = selected_code
extraction_source = selected_source     # "strict" or "fallback"
extraction_conflict = len(candidates) > 1  # True if both produced different code
extraction_candidates = {
    source: len(code) for source, code in candidates
}
```

All selection metadata is logged in the audit record. If `extraction_conflict=True`, the case is flagged for manual review.

### Why This Is Safe

1. **Both extractions run independently** — no information is lost.
2. **Syntax check (C1)** ensures we never prefer garbage over valid Python.
3. **Non-trivial check (C2)** ensures we never prefer a placeholder over real code.
4. **Length tiebreaker (C3)** is a weak heuristic but only fires when BOTH candidates are syntactically valid and non-trivial — in that case, the longer code is more likely to be the complete fix.
5. **Conflict is logged** — every case where the two extractors disagree is flagged for review.

### What This Changes vs Current System

| Scenario | Current Behavior | New Behavior |
|---|---|---|
| Strict finds code, fallback would find same code | Strict used (fallback never runs) | Both run, same result, no conflict |
| Strict finds code, fallback finds different (better) code | Strict used (fallback never runs) | Both run, selection picks best via C1-C3 |
| Strict fails, fallback finds code | Fallback used | Same — fallback used |
| Both fail | No code extracted | Same — no code extracted |
| Strict finds placeholder, fallback finds real code | Strict placeholder used (BUG) | Fallback real code selected via C2 |

---

## E.5 (REVISED) — Fallback Prohibitions

| Prohibition | Rationale |
|---|---|
| LEG fallback MUST NOT run when JSON extraction produced non-empty code | Primary path takes precedence. Fallback only on JSON failure. |
| LEG fallback MUST set `extraction_source="fallback"` and `schema_compliant=False` | Downstream systems must know code came from fallback, not structured JSON. |
| Salvage reconstruction MUST NOT be used for primary metrics | Produces hybrid programs. |
| Raw fallback (tier 4) MUST be flagged with `_raw_fallback=True` | Entire raw text is not structured code. |
| Retry harness: fallback extraction MUST NOT silently replace strict extraction | Both run; selection is explicit via C1-C3 criteria. No silent override. |
| Retry harness: if `extraction_conflict=True`, the case MUST be logged | Conflicts indicate ambiguous extraction — must be reviewable. |

---

## F.6 (REVISED) — Invariant: Best-Available Extraction

**Old invariant (v2)**: "If a higher-priority parser tier successfully extracts code, no lower-priority tier may replace that extraction."

**New invariant**: "The executed code is the BEST candidate from all available extraction sources, selected via the deterministic criteria C1 (syntax validity), C2 (non-trivial content), C3 (length tiebreaker). Selection metadata is always logged."

This replaces the "first wins" rule with a "best wins" rule. The selection criteria are deterministic and verifiable — given the same input, the same candidate is always selected.

---

## F.8 (NEW) — Invariant: Extraction Source Traceability

Every case MUST record `extraction_source` in its result:
- `"strict"` — code from JSON field (LEG or retry harness strict parser)
- `"fallback"` — code from `parse_model_response()` fallback
- `"file_dict"` — code from V2 file-dict reconstruction
- `"direct"` — code from `parse_model_response()` primary tier (standard conditions)

If `extraction_source` is missing from any result, the result is INVALID.

---

## F.9 (NEW) — Invariant: Extraction Conflict Logging

If two extraction sources produce DIFFERENT non-empty code for the same case, `extraction_conflict=True` MUST be set and `extraction_candidates` MUST record the source and length of each candidate.

If `extraction_conflict=True` and `extraction_candidates` is missing, the result is INVALID.

---

## Updated Validation Tests

### Test 13: Extraction Selection — Strict Wins When Both Valid

**Input**: A retry harness response where JSON `code` field contains valid Python (200 chars, has `def`), and a ```python block contains the same code.

**Expected**: `extraction_source="strict"`, `extraction_conflict=False` (same code, no conflict).

### Test 14: Extraction Selection — Fallback Wins When Strict Is Placeholder

**Input**: A retry harness response where JSON `code` field contains `"# your code here"` (placeholder, fails C2), and a ```python block contains a valid 300-char fix with `def`.

**Expected**: `extraction_source="fallback"`, `extraction_conflict=True`, selected code is the 300-char fix.

### Test 15: Extraction Selection — Strict Wins When Fallback Is Garbage

**Input**: A retry harness response where JSON `code` field contains valid Python, and `parse_model_response()` raw_fallback tier returns the entire response as "code" (fails C1 — not valid Python by itself).

**Expected**: `extraction_source="strict"`, selected code is the JSON extraction.

### Test 16: LEG Restricted Fallback — Code Recovered from Broken JSON

**Input**: A LEG response where JSON is malformed (Category B from forensic analysis — brace nesting lost), but the raw output contains a ```python block with the correct fix.

**Expected**: `extraction_source="fallback"`, `schema_compliant=False`, `code_extracted=True`, `parse_error=None`.

### Test 17: LEG Restricted Fallback — Does NOT Override Valid JSON

**Input**: A LEG response where JSON parses correctly and `code` field is non-empty.

**Expected**: `extraction_source="strict"`. Fallback does NOT run.

### Test 18: Extraction Conflict Logging

**Input**: A retry harness response where strict and fallback produce DIFFERENT non-empty code.

**Expected**: `extraction_conflict=True`, `extraction_candidates` has two entries with source labels and lengths.
