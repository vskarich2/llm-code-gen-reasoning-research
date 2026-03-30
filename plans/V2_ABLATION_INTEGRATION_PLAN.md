# V2 Ablation Integration Plan

**Date:** 2026-03-29
**Status:** Plan only. No implementation.
**Templates ready:** `leg_reduction_v2.j2`, `leg_reduction_lean_v2.j2`, `classify_reasoning_v2.j2`, `output_instruction_v3.j2`

---

## 1. Executive Summary

Four new prompt templates introduce a commitment-based reasoning framework:
- **baseline_v2**: lightweight baseline with root_cause + fix_strategy + files (no explicit commitments)
- **leg_reduction_v2**: structured treatment with root_cause + code_commitments + fix_strategy + risk_check + files
- **leg_reduction_lean_v2**: same schema as v2 but lighter prompt for weaker models
- **classify_reasoning_v2**: commitment-aware evaluator that extracts/validates commitments against canonical patterns

The integration must create a NEW PARALLEL PATH that:
1. Uses the assembly engine (active system) for prompt rendering
2. Adds new parser helpers for the commitment-aware schema
3. Adds a new classifier invocation path for classify_reasoning_v2
4. Adds new metrics for commitment extraction/satisfaction
5. Touches legacy code ONLY at routing points (condition dispatch)

---

## 2. Current Impact Surface Audit

### 2.1 Prompt Assembly (`assembly_engine.py` + `prompt_registry.py` + `prompt_manifest.yaml`)

**What changes:**
- 4 new `.j2` files already in `prompts/components/` — the registry auto-discovers them at load time
- `prompt_manifest.yaml` needs 3 new condition entries (baseline_v2, leg_reduction_v2, leg_reduction_lean_v2)
- `output_instruction_v3.j2` is a new component that can be appended like v1/v2

**What could break:**
- Nothing — the registry is additive. New components don't affect existing ones.
- Risk: variable name mismatch between manifest and template (caught by StrictUndefined at render time)

**Isolation:** Fully isolated. New manifest entries don't touch existing conditions.

### 2.2 Condition Registry (`constants.py`)

**What changes:**
- Add `baseline_v2`, `leg_reduction_v2`, `leg_reduction_lean_v2` to `ALL_CONDITIONS`
- Add to `SIMPLE_CONDITIONS` (none use retry)
- Add to `COND_LABELS`

**What could break:**
- The exhaustiveness assertion at line 70 will fail if categories don't sum correctly
- `COND_LABELS` uniqueness assertion will fail if labels collide

**Isolation:** Low risk — additive only. Just new entries in existing lists/dicts.

### 2.3 Response Parsing (`parse.py` + `leg_reduction.py`)

**What changes:**
- baseline_v2 returns `{"root_cause": ..., "fix_strategy": ..., "files": {...}}` — this is a SUBSET of the file-dict format. The existing `_try_file_dict()` parser (Tier 0) will match it. No change needed for parsing baseline_v2 generation output.
- leg_v2 and lean_v2 return `{"root_cause": ..., "code_commitments": [...], "fix_strategy": ..., "risk_check": ..., "files": {...}}` — also matches `_try_file_dict()` because it has a `files` key with string values. No parse.py change needed.
- **NEW:** a v2 reasoning extractor is needed to pull `code_commitments` from the parsed JSON and normalize them

**What could break:**
- `_try_file_dict()` will parse the JSON and return it. But `code_commitments` (a list) won't be recognized as a standard field — it'll be in the parsed dict but ignored by downstream code unless explicitly extracted.
- The existing `reasoning.py:extract_reasoning_obj()` won't extract `code_commitments` — it only knows about root_cause, failure_mechanism, broken_invariant, fix_strategy, risk_check.

**Isolation:** Parse itself works. The gap is in reasoning extraction, which needs a NEW function.

### 2.4 Reasoning Extraction (`reasoning.py`)

**What changes:**
- `extract_reasoning_obj()` needs to also extract `code_commitments` from parsed JSON
- `validate_reasoning()` needs to recognize v2 schema: root_cause + fix_strategy + code_commitments as a valid set
- `LEG_REASONING_FIELDS` needs updating or a new `V2_REASONING_FIELDS` constant

**What could break:**
- If `code_commitments` is added to the reasoning_obj but the classifier template doesn't expect it, it'll be silently ignored — safe but useless
- If `validate_reasoning` requires `code_commitments` for ALL conditions, baseline (no commitments) would fail — must be conditional

**Isolation:** New function preferred. See section 3.

### 2.5 Classifier Invocation (`evaluator.py`)

**What changes:**
- `llm_classify()` currently builds variables for `classify_reasoning.j2` (v1). The v2 classifier needs DIFFERENT variables: no `broken_invariant`, no `self_check`, but yes `risk_check`, yes code_commitments (explicit or extracted), yes bug family for canonical matching.
- The v2 classifier prompt template has a DIFFERENT output format: 5 dimensions but with `commitments_extracted` and `commitments_satisfied` instead of `invariant_identified` and `causal_chain_complete`.

**What could break:**
- If we modify `llm_classify()` to support v2, all existing conditions would be affected
- The v2 output parser expects different dimension names → `parse_classify_output()` would break for v1

**Isolation:** MUST use a new function. `llm_classify_v2()` with its own variable builder and output parser. The existing `llm_classify()` stays untouched.

### 2.6 Classifier Output Parsing (`reasoning.py:parse_classify_output`)

**What changes:**
- v2 classifier output has dimensions: `mechanism_identified`, `commitments_extracted`, `commitments_satisfied`, `reasoning_code_alignment`, plus `failure_type`
- This is DIFFERENT from v1: `mechanism_identified`, `invariant_identified`, `causal_chain_complete`, `fix_alignment`, `reasoning_code_alignment`
- 3 of 5 dimensions changed names

**What could break:**
- `parse_classify_output()` hardcodes v1 dimension names at line 152. It will reject v2 output.
- `compute_reasoning_correct()` references v1 dimension names. It will fail on v2 output.

**Isolation:** MUST use a new parser function. `parse_classify_v2_output()`.

### 2.7 Category Computation (`reasoning.py:compute_reasoning_correct`, `compute_category`)

**What changes:**
- `compute_reasoning_correct()` derives a boolean from v1 dimensions. For v2, the derivation is different:
  - mechanism_identified: CORRECT required
  - commitments_extracted: CORRECT or PARTIAL required
  - commitments_satisfied: CORRECT or PARTIAL required
  - reasoning_code_alignment: CORRECT or PARTIAL required
- `compute_category()` itself doesn't change — it takes `(code_correct, reasoning_correct, ...)` booleans

**What could break:**
- If v2 dimensions are passed to the v1 `compute_reasoning_correct()`, it will fail (unknown dimension names)

**Isolation:** New function: `compute_reasoning_correct_v2(dims)`.

### 2.8 Event Schema / Logging

**What changes:**
- New fields in ev dict: `code_commitments`, `commitments_source` (explicit/extracted/none), `commitments_satisfied`, `commitments_extracted`, `schema_variant` (baseline_v2/leg_v2/lean_v2)
- RunLogger now dumps full ev dict (no handpicking) — so new fields automatically flow to logs

**What could break:**
- Downstream analysis scripts that assume fixed field names may not find the new fields — but they won't crash (dict.get with default)

**Isolation:** Additive-only. The full-dict logging change already handles this.

### 2.9 Retry / Contract / Guardrail

**Not affected.** The v2 conditions are all single-shot (no retry, no contract, no guardrail). They follow the same path as `baseline` through `build_prompt` → `run_single`.

### 2.10 Tests and Preflight

**What changes:**
- `preflight_verify_tests()` needs test functions for v2 conditions — but v2 conditions use the SAME test functions as baseline (same cases, same behavioral tests). The only difference is the prompt.
- New tests needed for: v2 parsing, v2 reasoning extraction, v2 classifier parsing, v2 reasoning_correct derivation

**What could break:**
- Nothing in preflight — v2 conditions use existing cases and tests

---

## 3. Proposed Low-Risk Integration Architecture

### 3.1 New Module: `reasoning_v2.py`

**Purpose:** All v2-specific reasoning logic in one isolated file. Zero edits to `reasoning.py`.

**Functions:**

```
extract_reasoning_v2(parsed_json: dict) -> dict
    Input: raw parsed JSON from model response
    Output: {
        "root_cause": str,
        "fix_strategy": str,
        "risk_check": str,         # "" if absent (baseline_v2)
        "code_commitments": list[str],  # [] if absent (baseline_v2)
        "commitments_source": "explicit" | "none",
        "schema_variant": "baseline_v2" | "leg_v2" | "lean_v2",
    }
    Called by: evaluate_case (when condition is a v2 condition)

validate_reasoning_v2(reasoning_obj: dict) -> dict
    Input: output of extract_reasoning_v2
    Output: {
        "reasoning_present": bool,
        "reasoning_attempted": bool,
        "schema_variant": str,
        "commitments_present": bool,
        "reasoning_lengths": dict,
    }
    Called by: evaluate_case

normalize_commitments(raw_commitments: list[str]) -> list[str]
    Input: raw commitment strings from model
    Output: normalized commitments (lowercase, stripped, deduplicated)
    Called by: extract_reasoning_v2 and classifier v2 prompt builder

parse_classify_v2_output(raw: str) -> dict
    Input: raw classifier v2 output (5 lines)
    Output: {
        "mechanism_identified": CORRECT/PARTIAL/WRONG,
        "commitments_extracted": CORRECT/PARTIAL/WRONG,
        "commitments_satisfied": CORRECT/PARTIAL/WRONG,
        "reasoning_code_alignment": CORRECT/PARTIAL/WRONG,
        "failure_type": str,
        "confidence": str,
        "counterfactual": str,
        "evidence": str,
        "judgment": str,
        "parse_error": str | None,
    }
    Called by: llm_classify_v2

compute_reasoning_correct_v2(dims: dict) -> bool | None
    Input: parsed v2 classifier dimensions
    Output: True/False/None
    Logic: mechanism=CORRECT AND commitments_extracted in (CORRECT, PARTIAL)
           AND commitments_satisfied in (CORRECT, PARTIAL)
           AND reasoning_code_alignment in (CORRECT, PARTIAL)
    Called by: evaluate_output (when v2 path)
```

**Where it lives:** `reasoning_v2.py` in project root (alongside `reasoning.py`)

**Who calls it:** `evaluator.py` (via a new `llm_classify_v2` function) and `execution.py` (via `evaluate_case` when condition is v2)

### 3.2 New Function: `llm_classify_v2()` in `evaluator.py`

**Purpose:** Build and invoke the v2 classifier prompt. Separate from `llm_classify()`.

```
llm_classify_v2(
    case: dict,
    code: str,
    reasoning_obj: dict,     # from extract_reasoning_v2
    reasoning_validation: dict,
    eval_model: str | None,
) -> dict
```

**Key differences from v1:**
- Uses `classify_reasoning_v2.j2` template (via assembly engine)
- Passes `code_commitments` to template (explicit if present, extracted marker if not)
- Passes `bug_family` from case for canonical commitment matching
- Parses output with `parse_classify_v2_output()` (different dimensions)
- Derives `reasoning_correct` via `compute_reasoning_correct_v2()`

**Where it lives:** New function appended to `evaluator.py`. Does NOT modify `llm_classify()`.

### 3.3 New Function: `evaluate_output_v2()` in `evaluator.py`

**Purpose:** v2 evaluation pipeline. Parallel to `evaluate_output()`.

```
evaluate_output_v2(case: dict, parsed: dict, eval_model: str | None = None) -> dict
```

**Pipeline:**
1. `exec_evaluate(case, code)` → behavioral pass/fail (SAME as v1)
2. `extract_reasoning_v2(parsed_json)` → structured reasoning with commitments
3. `validate_reasoning_v2(reasoning_obj)` → presence check
4. `llm_classify_v2(case, code, reasoning_obj, validation)` → v2 classification
5. `compute_reasoning_correct_v2(dims)` → boolean
6. `compute_category(code_correct, reasoning_correct, ...)` → category (SAME function as v1)
7. Assemble result dict with v2-specific fields

**Where it lives:** New function in `evaluator.py`. Does NOT modify `evaluate_output()`.

### 3.4 New Run Functions in `execution.py`

Three new thin run functions, one per v2 condition:

```
run_baseline_v2(case, model) -> (case_id, condition, ev)
run_leg_reduction_v2(case, model) -> (case_id, condition, ev)
run_leg_reduction_lean_v2(case, model) -> (case_id, condition, ev)
```

Each follows the same pattern:
1. Build prompt via `_assembly_build(["leg_reduction_v2"], vars)` (or baseline_v2, lean_v2)
2. Call model
3. Parse with standard `parse_model_response()` (file-dict tier matches)
4. Extract v2 reasoning via `extract_reasoning_v2()`
5. Evaluate via `evaluate_output_v2()`
6. Attach v2-specific metadata to ev
7. Write log + emit metrics

**Where they live:** Appended to `execution.py`. Each is ~30 lines. They do NOT modify `run_single()` or `run_leg_reduction()`.

### 3.5 Routing in `runner.py`

**One small edit:** `_run_one_inner()` gets 3 new elif branches:

```python
if condition == "baseline_v2":
    return run_baseline_v2(case, model)
if condition == "leg_reduction_v2":
    return run_leg_reduction_v2(case, model)
if condition == "leg_reduction_lean_v2":
    return run_leg_reduction_lean_v2(case, model)
```

This is the ONLY edit to legacy control flow.

---

## 4. New Data Contracts

### 4.1 Generation Output — baseline_v2

```json
{
    "root_cause": "create_config returns DEFAULTS by reference (str, required)",
    "fix_strategy": "use DEFAULTS.copy() to return independent dict (str, required)",
    "files": {"path": "content or UNCHANGED (dict, required)"}
}
```

No `code_commitments`. No `risk_check`.

### 4.2 Generation Output — leg_reduction_v2 / lean_v2

```json
{
    "root_cause": "str, required",
    "code_commitments": ["<scope> must <action>", "..."],
    "fix_strategy": "str, required",
    "risk_check": "str, required",
    "files": {"path": "content or UNCHANGED"}
}
```

`code_commitments` is a list of 1-3 strings. Each must follow `<scope> must <action>` pattern.

### 4.3 Normalized Internal Reasoning Object

```python
{
    "root_cause": str,           # always present
    "fix_strategy": str,         # always present
    "risk_check": str,           # "" for baseline_v2
    "code_commitments": list[str],  # [] for baseline_v2
    "commitments_source": str,   # "explicit" | "extracted" | "none"
    "schema_variant": str,       # "baseline_v2" | "leg_v2" | "lean_v2"
}
```

This is what `extract_reasoning_v2()` returns. All downstream code uses this normalized form.

### 4.4 Classifier v2 Output

```
Line 1: <mechanism>;<commitments_extracted>;<commitments_satisfied>;<alignment>;<failure_type>
Line 2: <confidence>
Line 3: Counterfactual: <sentence>
Line 4: Evidence: <bullets>
Line 5: Judgment: <sentences>
```

Dimensions: `mechanism_identified`, `commitments_extracted`, `commitments_satisfied`, `reasoning_code_alignment`. Values: CORRECT/PARTIAL/WRONG.

### 4.5 Baseline_v2 Commitment Handling

When baseline_v2 has no explicit `code_commitments`:
- `extract_reasoning_v2()` sets `code_commitments = []`, `commitments_source = "none"`
- The classifier v2 template instructs the evaluator to EXTRACT commitments from reasoning
- The evaluator may produce `commitments_extracted = CORRECT/PARTIAL/WRONG` based on whether it can infer commitments from root_cause + fix_strategy
- `commitments_satisfied` is evaluated against whatever was extracted

This is the key experimental comparison: explicit commitments (leg_v2) vs extracted commitments (baseline_v2).

---

## 5. Parsing Plan

### 5.1 Generation Output Parsing

**No new parser needed.** All v2 generation outputs have a `files` dict with string values. The existing `_try_file_dict()` in `parse.py` (Tier 0) matches this format and returns:

```python
{
    "files": {"path": "content", ...},
    "reasoning": "...",   # from "reasoning" key if present, else ""
    "response_format": "file_dict",
    ...
}
```

The v2-specific fields (`code_commitments`, `risk_check`) are in the raw JSON but NOT extracted by the standard parser. They are extracted by `extract_reasoning_v2()` from the `_raw_json` stashed on the parsed dict.

### 5.2 How `_raw_json` Gets to Reasoning Extraction

The `parse_model_response()` function in `parse.py` already stashes the raw parsed JSON when the file-dict tier matches (it does `json.loads(raw)` and returns the parsed dict). The `_build_parsed_response()` in `execution.py` preserves all keys. So `parsed["_raw_json"]` or the raw JSON fields are accessible.

**However:** there's a gap. `_try_file_dict()` returns `files` but does NOT return the full raw JSON as a separate field. The v2 reasoning extractor needs access to `code_commitments` which is in the raw JSON but not in the standard parsed dict.

**Fix needed:** `extract_reasoning_v2()` should receive the raw response string and do its own `json.loads()` to get the full JSON — same pattern as `parse_leg_output()` in `leg_reduction.py`. This avoids modifying `parse.py`.

### 5.3 Failure Modes

| Failure | Handling |
|---------|----------|
| Malformed JSON | Standard parser fallback tiers handle it (same as baseline) |
| Missing `files` key | `_try_file_dict` fails, falls through to code-string tiers |
| Empty `root_cause` | `validate_reasoning_v2` sets `reasoning_present = False` |
| Vague `fix_strategy` | Not caught by parser — classifier evaluates quality |
| Bad `code_commitments` shape (not a list) | `extract_reasoning_v2` normalizes: if string → wrap in list, if missing → empty list |
| `code_commitments` items not `<scope> must <action>` | Logged as warning, passed to classifier which scores `commitments_extracted` |
| `risk_check` missing in lean variant | `extract_reasoning_v2` sets `risk_check = ""`, validation allows it |
| `UNCHANGED` misuse | Handled by reconstructor (same as baseline) |
| Classifier v2 output mismatch | `parse_classify_v2_output` returns `parse_error`, category becomes `classifier_parse_failed` |

### 5.4 output_instruction_v3 Interaction

`output_instruction_v3.j2` is appended to baseline_v2 prompts. It specifies the schema with `root_cause`, `fix_strategy`, and `files` — no `code_commitments`. This aligns with the baseline_v2 generation contract.

For leg_v2 and lean_v2, the output instruction is embedded in the template itself (the schema is shown in the template's STEP 5). No separate output instruction component is appended — same pattern as the current `leg_reduction.j2` which has `include_output_instruction: false` in the manifest.

---

## 6. Classifier V2 Integration Plan

### 6.1 Prompt Builder Path

New function `llm_classify_v2()` in `evaluator.py`:

```python
def llm_classify_v2(case, code, reasoning_obj, reasoning_validation, eval_model=None):
    # 1. Build variables
    _cls_vars = {
        "task": case["task"][:max_chars],
        "code": code[:max_chars],
        "root_cause": _field_or_missing(reasoning_obj.get("root_cause")),
        "fix_strategy": _field_or_missing(reasoning_obj.get("fix_strategy")),
        "risk_check": _field_or_missing(reasoning_obj.get("risk_check")),
        "failure_types": ", ".join(sorted(VALID_FAILURE_TYPES)),
        "classifier_mode": classifier_mode,
        # v2-specific:
        "ground_truth_failure_mode": case.get("failure_mode", ""),
        "ground_truth_trap": case.get("trap", ""),
        "ground_truth_invariant": case.get("ground_truth_bug", {}).get("invariant", ""),
    }

    # 2. Render via assembly engine
    _rendered = _assembly_build(["classify_reasoning_v2"], _cls_vars)

    # 3. Call model
    raw = call_model(prompt, model=eval_model or _get_eval_model(), raw=True)

    # 4. Parse with v2 parser
    dims = parse_classify_v2_output(raw)

    # 5. Derive reasoning_correct via v2 logic
    reasoning_correct = compute_reasoning_correct_v2(dims)

    # 6. Return
    return {dims..., reasoning_correct, classify_raw, ...}
```

### 6.2 Classifier V2 Output Format

The v2 classifier outputs 5 lines (same structure as v1), but dimensions are:

```
Line 1: <mechanism>;<commitments_extracted>;<commitments_satisfied>;<alignment>;<failure_type>
```

vs v1:
```
Line 1: <mechanism>;<invariant>;<causal_chain>;<fix_align>;<code_align>;<failure_type>
```

Note: v2 has 5 fields on line 1 (4 dimensions + failure_type). v1 has 6 fields (5 dimensions + failure_type). The parser must handle this difference.

### 6.3 Explicit vs Extracted Commitments

The v2 classifier template already handles both cases:
- If explicit commitments are present → use them directly
- If not → extract from reasoning

The classifier makes this decision internally. The prompt passes whatever the model provided. The classifier's `commitments_extracted` dimension reflects whether valid commitments were found (explicit or inferred).

### 6.4 Canonical Commitment Matching

The v2 classifier template includes canonical commitment patterns by bug family (ALIASING, PARTIAL_STATE_UPDATE, STALE_CACHE, etc.). The classifier compares extracted commitments against these patterns.

The `bug_family` is the case's `family` field from `cases_v2.json` (e.g., `alias_config`, `stale_cache`). This maps to the canonical patterns in the template.

**Question:** Should `bug_family` be passed as a template variable, or is it implicitly available via `ground_truth_failure_mode`? The template uses failure_mode categories, not family names. The mapping is: `alias_config` family → `ALIASING` failure pattern. This mapping should be handled in the variable builder, not in the template.

### 6.5 Old Metrics Reinterpretation

| Old dimension | v2 equivalent | Status |
|--------------|---------------|--------|
| `mechanism_identified` | `mechanism_identified` | Same name, same semantics |
| `invariant_identified` | (removed) | Replaced by `commitments_extracted` |
| `causal_chain_complete` | (removed) | Replaced by `commitments_satisfied` |
| `fix_alignment` | (merged into `reasoning_code_alignment`) | Semantically similar |
| `reasoning_code_alignment` | `reasoning_code_alignment` | Same name, refined semantics |

---

## 7. Metrics / Category Plan

### 7.1 Metrics That Remain Valid

- `pass` (code correctness) — unchanged, from exec_evaluate
- `category` — same 8 categories, same `compute_category()` function
- `reasoning_correct` — same boolean, but derived from v2 dimensions via `compute_reasoning_correct_v2()`
- `LEG` = reasoning_correct AND NOT code_correct — unchanged definition
- `lucky_fix` = NOT reasoning_correct AND code_correct — unchanged
- `true_success` = reasoning_correct AND code_correct — unchanged
- `true_failure` = NOT reasoning_correct AND NOT code_correct — unchanged

### 7.2 New Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `schema_variant` | str | "baseline_v2" / "leg_v2" / "lean_v2" |
| `commitments_source` | str | "explicit" / "extracted" / "none" |
| `commitments_present` | bool | were any commitments found? |
| `code_commitments` | list[str] | raw commitment strings |
| `commitments_extracted` | CORRECT/PARTIAL/WRONG | classifier dimension |
| `commitments_satisfied` | CORRECT/PARTIAL/WRONG | classifier dimension |
| `mechanism_identified_v2` | CORRECT/PARTIAL/WRONG | classifier dimension (same name, v2 context) |
| `reasoning_code_alignment_v2` | CORRECT/PARTIAL/WRONG | classifier dimension |

### 7.3 Deprecated Metrics (for v2 conditions only)

These are NOT computed for v2 conditions (they remain valid for v1 conditions):
- `invariant_identified` — replaced by `commitments_extracted`
- `causal_chain_complete` — replaced by `commitments_satisfied`
- `fix_alignment` — merged into `reasoning_code_alignment`

### 7.4 LEG Definition Under V2

LEG = model's reasoning correctly identified the mechanism AND extracted valid commitments, but the code does not satisfy those commitments or does not pass behavioral tests.

Formally: `reasoning_correct_v2 == True AND code_correct == False`

Where `reasoning_correct_v2 = mechanism CORRECT AND commitments_extracted in (CORRECT, PARTIAL) AND commitments_satisfied in (CORRECT, PARTIAL) AND alignment in (CORRECT, PARTIAL)`

### 7.5 "Uninterpretable Success"

New category to consider: code passes but commitments_extracted = WRONG (no valid commitments found in reasoning). The model got the right answer but we can't determine if it reasoned correctly.

This is currently classified as `lucky_fix` (reasoning_correct = False + code_correct = True). That classification is correct — if we can't extract valid commitments, reasoning quality is indeterminate, which maps to "not demonstrated correct" = False.

---

## 8. Required Small Integration Edits

### Edit 1: `constants.py` — add 3 conditions

```python
ALL_CONDITIONS = [
    ...existing...
    "baseline_v2",
    "leg_reduction_v2",
    "leg_reduction_lean_v2",
]

COND_LABELS = {
    ...existing...
    "baseline_v2": "B2",
    "leg_reduction_v2": "L2",
    "leg_reduction_lean_v2": "LL",
}
```

**Risk:** Minimal. Additive. Assertions verify consistency.

### Edit 2: `prompt_manifest.yaml` — add 3 condition specs

```yaml
baseline_v2:
    components: ["task_and_code", "output_instruction_v3"]
    nudge:
      type: "none"
    label: "BASELINE_V2"

leg_reduction_v2:
    components: ["leg_reduction_v2"]
    nudge:
      type: "none"
    include_output_instruction: false
    label: "LEG_V2"

leg_reduction_lean_v2:
    components: ["leg_reduction_lean_v2"]
    nudge:
      type: "none"
    include_output_instruction: false
    label: "LEG_LEAN_V2"
```

**Risk:** Minimal. Additive. Existing conditions untouched.

### Edit 3: `runner.py:_run_one_inner()` — add 3 routing branches

```python
if condition == "baseline_v2":
    return run_baseline_v2(case, model)
if condition == "leg_reduction_v2":
    return run_leg_reduction_v2(case, model)
if condition == "leg_reduction_lean_v2":
    return run_leg_reduction_lean_v2(case, model)
```

**Risk:** Low. New branches only fire for new conditions. Existing conditions take existing paths.

### Edit 4: `execution.py` — add 3 new run functions + import

Add `run_baseline_v2()`, `run_leg_reduction_v2()`, `run_leg_reduction_lean_v2()` as new functions at the end of the file. Each ~30 lines.

**Risk:** Low. New functions, no modification to existing functions.

### Edit 5: `evaluator.py` — add `llm_classify_v2()` and `evaluate_output_v2()`

New functions appended. `evaluate_output()` untouched.

**Risk:** Low. New functions only.

### Edit 6: `experiment_config.py` — recognize v2 conditions in config

The config parser needs to accept the new condition names in YAML. Currently it validates against `VALID_CONDITIONS` — which is updated in Edit 1.

**Risk:** Minimal. The config just passes condition names through.

---

## 9. Test Plan

### Unit Tests (`tests/test_reasoning_v2.py`)

1. `test_extract_reasoning_v2_leg` — leg_v2 JSON with all fields → correct extraction
2. `test_extract_reasoning_v2_baseline` — baseline_v2 JSON without commitments → commitments=[], source="none"
3. `test_extract_reasoning_v2_missing_root_cause` — → reasoning_present=False
4. `test_extract_reasoning_v2_bad_commitments_shape` — string instead of list → normalized to list
5. `test_normalize_commitments` — dedup, lowercase, strip
6. `test_validate_reasoning_v2_leg` — all fields present → reasoning_present=True
7. `test_validate_reasoning_v2_baseline` — no commitments → still reasoning_present=True (baseline doesn't require them)
8. `test_parse_classify_v2_output_valid` — 5-line output → correct dimensions
9. `test_parse_classify_v2_output_wrong_count` — 4 fields on line 1 → parse_error
10. `test_parse_classify_v2_output_bad_dimension` — "MAYBE" → parse_error
11. `test_compute_reasoning_correct_v2_all_correct` — True
12. `test_compute_reasoning_correct_v2_mechanism_wrong` — False
13. `test_compute_reasoning_correct_v2_commitments_wrong` — False

### Integration Tests (`tests/test_v2_integration.py`)

14. `test_baseline_v2_prompt_renders` — assembly engine produces valid prompt
15. `test_leg_v2_prompt_renders` — assembly engine produces valid prompt with file_keys_example
16. `test_lean_v2_prompt_renders` — assembly engine produces valid prompt
17. `test_classify_v2_prompt_renders` — assembly engine produces valid prompt with all variables
18. `test_baseline_v2_end_to_end` — mock model → parse → evaluate_output_v2 → category

### Parser Fairness Tests

19. `test_malformed_baseline_v2_recovers` — same recovery as baseline v1
20. `test_malformed_leg_v2_recovers` — same recovery as baseline v1
21. `test_lean_v2_omits_risk_check` — risk_check="" → still valid

### Edge Cases

22. `test_baseline_v2_no_extractable_commitments` — commitments_source="none", classifier handles extraction
23. `test_leg_v2_explicit_commitments_but_code_ignores` — commitments_satisfied=WRONG, code may still pass → interesting LEG candidate
24. `test_lean_v2_risk_check_is_SAFE` — "SAFE" is valid, treated as risk_check present
25. `test_correct_mechanism_violated_commitments` — LEG candidate
26. `test_wrong_mechanism_passing_code` — lucky_fix
27. `test_vague_fix_strategy_correct_code` — depends on classifier judgment

### Backward Compatibility

28. `test_v1_conditions_unaffected` — run baseline (v1) through evaluate_output (v1) → same result as before
29. `test_v1_classifier_unaffected` — llm_classify (v1) still works with v1 template

---

## 10. Logging / Observability Plan

### New Fields in ev dict (additive-only)

```python
ev["schema_variant"] = "baseline_v2" | "leg_v2" | "lean_v2"
ev["code_commitments"] = ["...", "..."]  # raw from model
ev["commitments_source"] = "explicit" | "extracted" | "none"
ev["commitments_present"] = True | False
# v2 classifier dimensions:
ev["commitments_extracted"] = "CORRECT" | "PARTIAL" | "WRONG"
ev["commitments_satisfied"] = "CORRECT" | "PARTIAL" | "WRONG"
# v2 classifier raw output:
ev["classify_v2_raw"] = "..."
ev["classify_v2_parse_error"] = None | "..."
```

These are set by the v2 run functions in execution.py. Since the RunLogger now dumps full ev dict, they automatically appear in logs.

### Event Schema (events.jsonl)

Add `schema_variant` to events. Additive-only — old events don't have it, new events do. Analysis scripts should check `event.get("schema_variant")` to determine v1 vs v2 path.

---

## 11. Phased Rollout Plan

### Phase 1: Templates + Isolated Code (no conditions enabled)

**Deliverables:**
- `reasoning_v2.py` with all functions
- `llm_classify_v2()` and `evaluate_output_v2()` in evaluator.py
- 3 run functions in execution.py
- Unit tests passing

**Validation:** All 29 unit/integration tests pass. No existing tests broken.

**Rollback:** Delete `reasoning_v2.py` + new functions. Zero impact on existing code.

### Phase 2: Register Conditions + Smoke Test

**Deliverables:**
- Add conditions to `constants.py`, `prompt_manifest.yaml`, `experiment_config.py`
- Add routing in `runner.py:_run_one_inner()`
- Create `configs/v2_smoke.yaml` with 3 cases × 3 v2 conditions

**Validation:** Run smoke config. All 9 evals complete. Pass rate > 0. Logs contain `schema_variant`. No crashes.

**Rollback:** Remove conditions from constants.py + manifest. Routing branches become dead code (never triggered).

### Phase 3: Cost Gate (5 cases × 3 conditions × 1 model)

**Deliverables:**
- Run 5 cases with gpt-4.1-nano
- Verify: pass rate, category distribution, commitment fields in logs, classifier v2 output parseable

**Validation:**
- `commitments_extracted` ≠ all WRONG (classifier is working)
- `schema_variant` present in all events
- No `no_reasoning` from schema gate (reasoning validation accepts v2 schema)
- Existing v1 conditions still produce same results when run alongside

**Rollback:** Don't use v2 conditions in production configs.

### Phase 4: Full Ablation

**Deliverables:**
- Run full 58 cases × 3 v2 conditions × 3 models × N trials
- Compare with existing baseline + leg_reduction data

**Validation:**
- Pass rates comparable to v1 conditions (not wildly different)
- Commitment metrics distributed (not all WRONG or all CORRECT)
- LEG rates interpretable

---

## 12. Risks / Edge Cases / Open Questions

### Risks

1. **Classifier v2 output format divergence:** If gpt-5-mini doesn't follow the 5-line format reliably, `parse_classify_v2_output` will produce many parse errors. Mitigation: test with all 3 eval models before full ablation.

2. **Canonical commitment matching ambiguity:** The classifier template lists canonical patterns by bug family, but the mapping from case `family` (e.g., `alias_config`) to canonical category (e.g., `ALIASING`) is implicit in the template. If the classifier can't determine the bug family from the ground truth fields, canonical matching fails silently.

3. **baseline_v2 commitment extraction quality:** The classifier must extract commitments from unstructured reasoning. This is inherently noisier than explicit commitments. If extraction quality is low, `commitments_extracted = WRONG` for most baseline_v2 cases, making the comparison between baseline_v2 and leg_v2 uninformative.

### Open Questions

1. **Should `output_instruction_v3` include `code_commitments` in its schema for baseline_v2?** Current design says NO (baseline doesn't ask for commitments). But if the model spontaneously includes them, should they be used? Proposal: yes — if present, set `commitments_source = "spontaneous"`.

2. **Should lean_v2 allow `risk_check = "SAFE"`?** The lean template says "Otherwise write: SAFE". This is a valid response. The parser should accept it as present (not missing).

3. **How to handle v2 conditions in the Redis dashboard / redis_live_dashboard.py?** New metrics won't appear in the current dashboard. This is acceptable for now — the dashboard shows pass rate and LEG which are computed the same way.

4. **Should v2 results be stored in a separate log directory?** Proposal: no — same log structure, differentiated by `schema_variant` field. Simpler for analysis.
