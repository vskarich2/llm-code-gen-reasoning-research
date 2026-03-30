# V2 Gold Standard Implementation Plan

**Date:** 2026-03-29
**Status:** Implementation plan. Follows Gold Standard V2 Architecture spec exactly.
**Supersedes:** V2_ABLATION_INTEGRATION_PLAN.md, V2_ABLATION_INTEGRATION_PLAN_v2.md

---

## 1. Module Structure

Six dedicated v2 modules. No substantive v2 logic in legacy files.

```
NEW FILES:
  contracts_v2.py        — schema contracts, required fields, validation rules
  parser_v2.py           — SOLE JSON deserializer for v2 generation outputs
  reasoning_v2.py        — normalization, commitment handling, artifact construction
  evaluator_v2.py        — classifier invocation, classifier output parsing
  metrics_v2.py          — signal derivation, category computation
  mapping_v2.py          — canonical bug-family → commitment-family mapping

LEGACY EDITS (routing only):
  constants.py           — 3 condition entries
  prompt_manifest.yaml   — 3 condition specs
  runner.py              — 1 routing branch to v2 dispatcher
```

---

## 2. Canonical V2 Data Flow (Stage by Stage)

### STAGE 1 — Prompt Rendering

```
build_v2_prompt(case, condition)              [prompt_builders in evaluator_v2.py]
    │ uses assembly_engine.build() with v2 component names
    │ uses prompts._format_code_files() for code block
    │ returns: (prompt_str, prompt_metadata)
    ▼
call_model(prompt_str, model, raw=True)       [llm.py — UNCHANGED]
    │ returns: raw_response_text (str)
```

### STAGE 2 — V2 Parse (SINGLE AUTHORITY)

```
parse_generation_v2(raw_response_text, schema_variant)    [parser_v2.py]
    │
    │ This function is the ONE AND ONLY JSON deserializer for v2.
    │ It calls json.loads() exactly once.
    │ It does NOT delegate to parse_model_response().
    │ It does NOT fall through to v1 parser tiers.
    │
    │ Returns: ParsedGenerationV2
    ▼
```

**Why not reuse parse_model_response()?**

`parse_model_response()` is a multi-tier recovery pipeline designed for v1. It:
- Returns `_raw_json` as a side effect, not a contract
- Strips `code_commitments` from its structured output
- Falls through to lenient/code-block/raw-fallback tiers that are irrelevant for v2
- Runs v1 `reasoning_obj` extraction that overwrites v2 fields

Using it creates split-brain: `parse_model_response` claims authority over the parsed form, but v2 extractors would need to re-read `_raw_json` to get the actual fields. That is two authorities.

Instead, `parser_v2.py` owns deserialization for v2. It is simpler (no multi-tier recovery), stricter (required fields validated), and produces a complete output in one pass.

**What about malformed responses?**

If the model returns non-JSON (prose, markdown), `parse_generation_v2` attempts:
1. Strip markdown fences (```json ... ```)
2. Find first balanced `{...}` via bracket matching
3. `json.loads()` on the extracted block

If all fail: `ParsedGenerationV2` with `parse_status = "failed"`, `full_json = None`. Downstream produces a failure artifact. The response is NOT silently re-routed through v1 parser tiers — that would create semantic ambiguity about which parser produced the result.

### STAGE 3 — Normalization

```
normalize_generation_v2(parsed: ParsedGenerationV2)       [reasoning_v2.py]
    │
    │ Reads from parsed.full_json ONLY (the canonical source).
    │ Produces the SINGLE normalized artifact consumed by all downstream v2 code.
    │
    │ Returns: NormalizedReasoningArtifactV2
    ▼
```

### STAGE 4 — Execution Evaluation

```
exec_evaluate(case, code)                     [exec_eval.py — UNCHANGED]
    │ code extracted from ParsedGenerationV2.files_dict
    │ assembled via reconstructor (same path as v1)
    │
    │ Returns: exec_result dict (pass, score, reasons)
    ▼
```

### STAGE 5 — Classifier V2

```
classify_reasoning_v2(
    artifact: NormalizedReasoningArtifactV2,
    case: dict,
    code: str,
    config
)                                             [evaluator_v2.py]
    │
    │ Builds classifier prompt variables from artifact + case
    │ Renders via assembly_engine.build(["classify_reasoning_v2"], vars)
    │ Calls call_model()
    │ Parses output via parse_classifier_v2_output() [evaluator_v2.py]
    │
    │ Returns: ClassifierResultV2
    ▼
```

### STAGE 6 — Metric Derivation

```
derive_v2_signals(classifier: ClassifierResultV2)         [metrics_v2.py]
    │
    │ Produces three SEPARATE booleans:
    │   mechanism_correct
    │   commitments_valid
    │   alignment_positive
    │ Plus: compatibility rollup, v2 category
    │
    │ Returns: V2Signals
    ▼
```

### STAGE 7 — Result Assembly + Logging

```
assemble_v2_result(
    exec_result, artifact, classifier, signals, case, condition
)                                             [evaluator_v2.py]
    │
    │ Builds the ev dict with ALL v2 fields
    │ Tags schema_variant
    │
    │ Returns: ev dict
    ▼
write_log(...)                                [execution.py — UNCHANGED, reused]
_emit_metrics_event(...)                      [execution.py — UNCHANGED, reused]
```

---

## 3. Data Contracts

### 3.1 ParsedGenerationV2

```
Produced by: parser_v2.parse_generation_v2()
Consumed by: reasoning_v2.normalize_generation_v2()

Fields:
  parse_status: str          "success" | "partial" | "failed"
  schema_variant: str        "baseline_v2" | "leg_v2" | "lean_v2"
  full_json: dict | None     complete parsed JSON object — AUTHORITATIVE
  files_dict: dict | None    {"path": "content|UNCHANGED"} extracted from full_json
  parse_error: str | None    specific error message if parse_status != "success"
  raw_response_text: str     original raw string (for logging only, NOT for re-parsing)
```

### 3.2 NormalizedReasoningArtifactV2

```
Produced by: reasoning_v2.normalize_generation_v2()
Consumed by: evaluator_v2 (classifier var builder), metrics_v2, logging

Fields:
  # Schema identity
  schema_variant: str                     "baseline_v2" | "leg_v2" | "lean_v2"
  parse_status: str                       from ParsedGenerationV2
  validation_status: str                  "valid" | "partial" | "invalid"
  validation_errors: list[str]

  # Raw fields (exactly as model produced)
  raw_root_cause: str
  raw_fix_strategy: str
  raw_risk_check: str                     "" for baseline_v2
  raw_code_commitments: list[str]         [] for baseline_v2

  # Normalized fields
  normalized_root_cause: str              stripped; "[EMPTY]" if blank
  normalized_fix_strategy: str            stripped; "[EMPTY]" if blank
  normalized_risk_check: str              stripped; "" allowed for baseline_v2; "SAFE" valid for lean_v2
  normalized_code_commitments: list[str]  per normalization rules (section 5)
  normalization_notes: list[str]          any normalization actions taken (splits, scope tagging)

  # Commitment provenance
  commitment_count: int
  commitments_source: str                 "explicit" | "spontaneous" | "none"
  commitment_extractability_status: str   "present" | "absent" | "malformed"

  # Files
  files_dict: dict | None
  full_json: dict | None

  # Provenance
  parser_variant: str                     "parser_v2"
  output_contract_variant: str            "baseline_v2_contract" | "leg_v2_contract" | "lean_v2_contract"
  canonical_family: str | None            from mapping_v2
  canonical_family_mapped: bool
```

### 3.3 ClassifierResultV2

```
Produced by: evaluator_v2.parse_classifier_v2_output()
Consumed by: metrics_v2.derive_v2_signals()

Fields:
  # Dimensions (CORRECT | PARTIAL | WRONG | None on parse failure)
  mechanism_identified: str | None
  commitments_extracted: str | None
  commitments_satisfied: str | None
  reasoning_code_alignment: str | None

  # Metadata
  failure_type: str
  failure_type_raw: str
  confidence: str                   HIGH | MEDIUM | LOW
  counterfactual: str
  evidence: str
  judgment: str

  # Parse
  parse_error: str | None
  classify_raw: str
  classifier_schema_variant: str    "v2_5line"
```

### 3.4 V2Signals

```
Produced by: metrics_v2.derive_v2_signals()
Consumed by: evaluator_v2.assemble_v2_result(), logging

Fields:
  # Three SEPARATE booleans — the primary scientific measures
  mechanism_correct: bool | None        mechanism_identified == CORRECT
  commitments_valid: bool | None        commitments_extracted in {CORRECT, PARTIAL}
  alignment_positive: bool | None       commitments_satisfied in {CORRECT, PARTIAL}
                                        AND reasoning_code_alignment in {CORRECT, PARTIAL}

  # Compatibility rollup (NOT primary — exists for category computation only)
  reasoning_correct_compat: bool | None   all three above True

  # Extractability metrics
  commitment_extractability_rate: float | None
  commitment_satisfaction_rate: float | None

  # V2 category
  v2_category: str                       see section 8
```

---

## 4. Contract Validation Rules

### 4.1 contracts_v2.py — Required Fields Per Condition

```python
V2_BASELINE_REQUIRED = frozenset({"root_cause", "fix_strategy", "files"})
V2_LEG_REQUIRED = frozenset({"root_cause", "code_commitments", "fix_strategy", "risk_check", "files"})
V2_LEAN_REQUIRED = frozenset({"root_cause", "code_commitments", "fix_strategy", "risk_check", "files"})

SCHEMA_REQUIRED_FIELDS = {
    "baseline_v2": V2_BASELINE_REQUIRED,
    "leg_v2": V2_LEG_REQUIRED,
    "lean_v2": V2_LEAN_REQUIRED,
}
```

### 4.2 Validation Logic (in reasoning_v2.py)

For each schema_variant:
1. Check all required fields present in `full_json`
2. Check all required fields are non-None
3. Check `root_cause` and `fix_strategy` are non-empty strings with length >= 10
4. For leg_v2 / lean_v2: check `code_commitments` is a list with >= 1 entry
5. For leg_v2 / lean_v2: check `risk_check` is non-empty (or "SAFE" for lean_v2)
6. Check `files` is a dict with at least 1 entry

Validation result: "valid" | "partial" (some optional fields missing) | "invalid" (required fields missing)

### 4.3 Baseline_v2 Spontaneous Commitments

**RESOLVED DESIGN DECISION:**

If baseline_v2 response contains `code_commitments` (not required, but model produced them):
- `commitments_source = "spontaneous"`
- `commitment_extractability_status = "present"`
- Commitments are normalized and passed to classifier
- This is a VALID and interesting outcome, not an error

---

## 5. Commitment Normalization Rules

### 5.1 Three Phases (in reasoning_v2.py)

**Phase A — Shape normalization:**
1. If `code_commitments` is a string, wrap in list: `[string]`
2. Strip whitespace from each entry
3. Remove entries that are empty after stripping
4. Remove exact duplicates (case-insensitive)

**Phase B — Structural normalization:**
5. Split compound commitments on " and " / " + " when BOTH halves contain a verb:
   - `"create_config must copy and DEFAULTS must not be mutated"` → two entries
   - `"create_config must copy DEFAULTS and return it"` → NOT split (second half lacks independent scope)
6. Normalize negation: `"should not"` → preserve as-is (do NOT strengthen to "must not")
7. Preserve explicit scope: the text before "must" or "should" is the scope
8. If no identifiable scope (no "must"/"should" pattern): prefix with `"[unscoped]"`

**Phase C — Semantic preservation:**
9. Do NOT invent missing scope: `"fix shared state"` stays as `"[unscoped] fix shared state"`
10. Do NOT strengthen vague commitments: `"improve correctness"` stays vague
11. Do NOT rephrase in any way that changes meaning

**Output:** `normalized_code_commitments: list[str]`, `normalization_notes: list[str]`

### 5.2 When normalization happens

- ONCE, during `normalize_generation_v2()`
- The normalized commitments are passed to the classifier
- Raw commitments are preserved in the artifact for debugging
- The classifier receives normalized commitments but may re-extract its own from reasoning text (for baseline_v2). The classifier's internal extraction is NOT controlled by our normalization.

---

## 6. Canonical Bug-Family Mapping

### 6.1 mapping_v2.py — Single Authoritative Table

```python
# Primary mapping: failure_mode (from case JSON) → canonical commitment family
# The canonical family matches the section headers in classify_reasoning_v2.j2

FAILURE_MODE_TO_CANONICAL = {
    "ALIASING":              "ALIASING",
    "PARTIAL_STATE_UPDATE":  "PARTIAL_STATE_UPDATE",
    "STALE_CACHE":           "STALE_CACHE",
    "MUTABLE_DEFAULT":       "MUTABLE_DEFAULT",
    "SIDE_EFFECT_ORDER":     "SIDE_EFFECT_ORDER",
    "USE_BEFORE_SET":        "USE_BEFORE_SET",
    "RETRY_DUPLICATION":     "RETRY_DUPLICATION",
    "PARTIAL_ROLLBACK":      "PARTIAL_ROLLBACK",
    "TEMPORAL_DRIFT":        "TEMPORAL_DRIFT",
    "MISSING_BRANCH":        "MISSING_BRANCH",
}

# Unmapped failure modes (no canonical pattern in classifier template):
UNMAPPED_FAILURE_MODES = {
    "EARLY_RETURN", "WRONG_CONDITION", "INIT_ORDER", "SILENT_DEFAULT",
    "INDEX_MISALIGN", "HIDDEN_DEPENDENCY", "INVARIANT_VIOLATION",
    "STATE_SEMANTIC_VIOLATION", "RACE_CONDITION", "TEMPORAL_ORDERING",
    "FLAG_DRIFT", "CACHE_ORDERING",
}

def get_canonical_family(case: dict) -> str | None:
    return FAILURE_MODE_TO_CANONICAL.get(case.get("failure_mode"))
```

### 6.2 Coverage

- **10 mapped families** covering 16 of 28 case families (some share failure_mode)
- **12 unmapped failure modes** covering 12 case families
- For unmapped cases: classifier operates without canonical reference. `canonical_family_mapped = False` is logged.

---

## 7. Classifier V2 Integration

### 7.1 Prompt Variable Builder (in evaluator_v2.py)

```
build_classifier_v2_vars(artifact, case, code, config) -> dict

Inputs:
  artifact: NormalizedReasoningArtifactV2
  case: dict (for task, failure_mode, ground_truth)
  code: str (assembled code for the classifier to inspect)
  config: ExperimentConfig (for model params, truncation limits)

Output dict:
  root_cause:    artifact.normalized_root_cause or "[COULD NOT EXTRACT]"
  fix_strategy:  artifact.normalized_fix_strategy or "[COULD NOT EXTRACT]"
  risk_check:    artifact.normalized_risk_check or "[COULD NOT EXTRACT]"
  task:          case["task"][:max_task_chars]
  code:          code[:max_code_chars]
  failure_types: sorted valid failure types joined
  classifier_mode: "grounded" or "blind"
  # Grounded-mode fields (conditional):
  ground_truth_failure_mode: case.get("failure_mode", "")
  ground_truth_trap: case.get("trap", "")
  ground_truth_invariant: case.get("ground_truth_bug", {}).get("invariant", "")
```

Note: `code_commitments` are NOT passed as a template variable. The classifier template instructs the LLM evaluator to extract commitments from the reasoning fields or use explicit ones if present in the root_cause/fix_strategy text. The classifier's STEP 2 handles this.

### 7.2 Classifier V2 Output Parser (in evaluator_v2.py)

```
V2_CLASSIFIER_DIMENSIONS = (
    "mechanism_identified",
    "commitments_extracted",
    "commitments_satisfied",
    "reasoning_code_alignment",
)

parse_classifier_v2_output(raw: str) -> ClassifierResultV2

Line 1: 5 semicolon-separated fields (4 dimensions + failure_type)
Line 2: confidence
Line 3: Counterfactual: ...
Line 4: Evidence: ...
Line 5: Judgment: ...

Optional ---DEBUG--- section stripped.
```

Difference from v1 parser: 5 fields on line 1 (not 6). Different dimension names. Dedicated parser function — does NOT call v1 `parse_classify_output()`.

---

## 8. V2 Category Semantics

### 8.1 V2 Analytical Categories

```python
def compute_v2_category(
    code_correct: bool,
    mechanism_correct: bool | None,
    commitments_valid: bool | None,
    alignment_positive: bool | None,
    commitments_source: str,
) -> str:

    # Parse/classifier failures
    if mechanism_correct is None:
        return "classifier_unavailable"

    # Success states
    if code_correct:
        if mechanism_correct and commitments_valid and alignment_positive:
            return "interpretable_success"
        if commitments_source == "none" and not commitments_valid:
            return "uninterpretable_success"
        if not mechanism_correct:
            return "lucky_fix_v2"
        if mechanism_correct and commitments_valid and not alignment_positive:
            return "alignment_failure_pass"  # rare: right reasoning, code works but misaligned
        return "lucky_fix_v2"  # fallback for partial mechanism/commitments

    # Failure states
    if mechanism_correct and commitments_valid and alignment_positive:
        return "LEG_v2"  # correct reasoning but code doesn't work
    if mechanism_correct and commitments_valid and not alignment_positive:
        return "alignment_failure_v2"  # reasoning okay but code doesn't match it
    if not mechanism_correct:
        return "full_failure_v2"
    return "full_failure_v2"  # partial mechanism/commitments
```

### 8.2 V1 vs V2 Comparability

**RESOLVED:** NOT directly comparable.

- `interpretable_success` ≈ v1 `true_success` but with commitment validation
- `LEG_v2` ≈ v1 `leg` but with commitment-based definition
- `uninterpretable_success` has NO v1 equivalent
- `alignment_failure_pass` has NO v1 equivalent
- `full_failure_v2` ≈ v1 `true_failure` but different dimensions

**Reporting rule:** All reports MUST include `schema_variant`. v1 and v2 MUST NOT be pooled. Legacy rollup columns may be added for comparison tables but must be labeled `legacy_compat_category`.

---

## 9. Downstream Consumer Audit

| Consumer | Fields read | V2 risk | Action | Severity |
|----------|-----------|---------|--------|----------|
| `paper_analysis.py` | reasoning_correct, alignment, leg_rate, lucky_fix, pass_rate | reasoning_correct semantics differ; new categories not handled | **Disable for v2 data** until upgraded | **SEV-1** silent lie |
| `leg_ablation_analysis.py` | category, failure_type, leg_true, alignment | category labels differ; `leg_true` derivation differs | **Disable for v2** or gate on schema_variant | **SEV-1** |
| `redis_live_dashboard.py` | leg_true, lucky_fix, true_success, pass_rate, failure_type | `pass_rate` is safe; all reasoning metrics differ | **Gate on schema_variant**; show only pass_rate for v2 | **SEV-2** misleading |
| `monitor_ablation.py` | pass_rate, leg_rate, lucky_fix, true_success | same as dashboard | **Gate on schema_variant** | **SEV-2** |
| `merge_and_validate.py` | event count, tuple completeness | new conditions = new expected tuples | **Update expected counts** | **SEV-3** validation error |
| `canary_run.py` | pass_rate only | `pass_rate` is unaffected by v2 reasoning | **No change** | None |
| `update_dashboards.py` | unclear/legacy | unknown | **Audit before enabling** | **SEV-3** |

**Policy:** Consumers that read `reasoning_correct`, `category`, `leg_true`, or classifier dimensions MUST NOT ingest v2 events without a `schema_variant == "v2"` gate. Any consumer that silently mixes v1 and v2 semantics is a SEV-1 incident.

---

## 10. Output Instruction / Schema Authority

| Condition | Generation schema authority | Parser validator | Drift test |
|-----------|---------------------------|-----------------|-----------|
| baseline_v2 | `output_instruction_v3.j2` `{{ schema_line }}` variable + `contracts_v2.V2_BASELINE_REQUIRED` | `parser_v2.parse_generation_v2(schema_variant="baseline_v2")` | Render template with placeholders, extract schema JSON, assert fields == V2_BASELINE_REQUIRED |
| leg_v2 | Template-local JSON in `leg_reduction_v2.j2` STEP 5 + `contracts_v2.V2_LEG_REQUIRED` | `parser_v2.parse_generation_v2(schema_variant="leg_v2")` | Same drift test |
| lean_v2 | Template-local JSON in `leg_reduction_lean_v2.j2` section 5 + `contracts_v2.V2_LEAN_REQUIRED` | `parser_v2.parse_generation_v2(schema_variant="lean_v2")` | Same |

Schema authority chain: template declares expected output → parser_v2 validates against contracts_v2 → drift test asserts parity.

---

## 11. Backward Compatibility

### 11.1 Frozen Fixture Tests

1. **V1 prompt fixture:** Render baseline v1 prompt for case `alias_config_a`. Assert byte-exact match with frozen fixture string.
2. **V1 parse fixture:** Feed frozen v1 response through `parse_model_response()`. Assert output dict matches frozen JSON fixture.
3. **V1 category fixture:** Feed frozen v1 classifier dimensions through `compute_reasoning_correct()` + `compute_category()`. Assert exact category match.
4. **V1 condition registry fixture:** Assert `VALID_CONDITIONS` contains all previous conditions. Assert `COND_LABELS` maps all previous conditions to previous labels.
5. **V1 log shape fixture:** Assert RunLogger output for a v1 condition has the same top-level keys as a frozen fixture.

### 11.2 What MUST NOT Change

- `parse_model_response()` — zero edits
- `reasoning.py` — zero edits
- `evaluator.py:llm_classify()` — zero edits
- `evaluator.py:evaluate_output()` — zero edits
- `execution.py:run_single()` — zero edits
- `execution.py:build_prompt()` — zero edits

---

## 12. V2 Preflight Suite

Run before any v2 API calls. All must pass. Any failure = hard stop.

| # | Check | How |
|---|-------|-----|
| 1 | All 4 v2 templates render | `assembly_engine.build()` with placeholder vars |
| 2 | output_instruction_v3 schema parity | Extract JSON from rendered template, assert fields == V2_BASELINE_REQUIRED |
| 3 | leg_v2 schema parity | Extract JSON from rendered template, assert fields == V2_LEG_REQUIRED |
| 4 | lean_v2 schema parity | Same as above |
| 5 | parser_v2 accepts baseline_v2 output | Feed synthetic JSON through parse_generation_v2("baseline_v2") |
| 6 | parser_v2 accepts leg_v2 output | Same |
| 7 | parser_v2 accepts lean_v2 output | Same |
| 8 | Baseline_v2 with no commitments accepted | Feed baseline JSON (no code_commitments key) → commitments_source="none", NOT a parse error |
| 9 | SAFE accepted as risk_check for lean_v2 | Feed lean JSON with risk_check="SAFE" → validation_status="valid" |
| 10 | Classifier v2 parser accepts valid 5-line output | Feed synthetic classifier output through parse_classifier_v2_output() |
| 11 | schema_variant emitted in synthetic ev | Run one synthetic v2 evaluation, check ev dict |
| 12 | commitments_source emitted in synthetic ev | Same |
| 13 | Canonical mapping for every exercised case | For each case in config, call get_canonical_family(). Log unmapped. |
| 14 | Spontaneous commitments tagged correctly | Feed baseline JSON with unexpected code_commitments → commitments_source="spontaneous" |
| 15 | V1 regression | Run one frozen v1 case, assert identical output to fixture |

---

## 13. Required Small Legacy Edits

### Edit 1: `constants.py` — add 3 conditions

```python
ALL_CONDITIONS = [... "baseline_v2", "leg_reduction_v2", "leg_reduction_lean_v2"]
COND_LABELS = {... "baseline_v2": "B2", "leg_reduction_v2": "L2", "leg_reduction_lean_v2": "LL"}
```

`SIMPLE_CONDITIONS` picks them up automatically (not in RETRY or MULTISTEP).

**Risk:** Minimal. Assertions validate.
**Regression check:** Fixture test 4.

### Edit 2: `prompt_manifest.yaml` — add 3 condition specs

```yaml
baseline_v2:
    components: ["task_and_code", "output_instruction_v3"]
    nudge: { type: "none" }
    label: "BASELINE_V2"

leg_reduction_v2:
    components: ["leg_reduction_v2"]
    nudge: { type: "none" }
    include_output_instruction: false
    label: "LEG_V2"

leg_reduction_lean_v2:
    components: ["leg_reduction_lean_v2"]
    nudge: { type: "none" }
    include_output_instruction: false
    label: "LEG_LEAN_V2"
```

**Risk:** Minimal. Additive.
**Regression check:** Fixture test 1.

### Edit 3: `runner.py:_run_one_inner()` — 1 routing branch

```python
if condition in ("baseline_v2", "leg_reduction_v2", "leg_reduction_lean_v2"):
    from execution_v2 import run_v2
    return run_v2(case, model, condition)
```

One import, one call. `execution_v2.run_v2()` handles internal dispatch.

**Risk:** Low. Only fires for v2 conditions.
**Regression check:** Run existing v1 test suite.

---

## 14. Test Plan

### Unit Tests: `tests/test_contracts_v2.py` (6 tests)
1. V2_BASELINE_REQUIRED matches expected fields
2. V2_LEG_REQUIRED matches expected fields
3. V2_LEAN_REQUIRED matches expected fields
4. Validation accepts valid baseline_v2 JSON
5. Validation rejects baseline_v2 missing root_cause
6. Validation accepts lean_v2 with risk_check="SAFE"

### Unit Tests: `tests/test_parser_v2.py` (8 tests)
7. Valid leg_v2 JSON → parse_status="success", all fields populated
8. Valid baseline_v2 JSON (no commitments) → parse_status="success"
9. Malformed JSON (missing brace) → parse_status="failed"
10. Markdown-fenced JSON → fences stripped, parse succeeds
11. code_commitments as string → shape-normalized to list
12. Empty response → parse_status="failed"
13. JSON with extra unexpected fields → accepted (extra fields preserved in full_json)
14. files dict missing → parse_status="partial"

### Unit Tests: `tests/test_reasoning_v2.py` (12 tests)
15. Normalize: strip + dedup
16. Normalize: compound split on "and"
17. Normalize: preserve vague commitment
18. Normalize: scopeless → "[unscoped]"
19. Normalize: negation preserved
20. Extract leg_v2: all fields present → valid artifact
21. Extract baseline_v2: no commitments → source="none"
22. Extract baseline_v2: spontaneous commitments → source="spontaneous"
23. Extract: empty raw_json → parse_status="failed"
24. Extract: malformed code_commitments (int) → status="malformed"
25. Validate: valid leg_v2 → "valid"
26. Validate: missing root_cause → "invalid"

### Unit Tests: `tests/test_evaluator_v2.py` (6 tests)
27. Valid classifier output parses → 4 dimensions + failure_type
28. Wrong field count on line 1 → parse_error
29. Bad dimension value → parse_error
30. Classifier var builder produces all required template variables
31. Classifier var builder uses "[COULD NOT EXTRACT]" for empty fields
32. Grounded mode adds ground truth fields

### Unit Tests: `tests/test_metrics_v2.py` (8 tests)
33. All CORRECT → mechanism_correct=True, commitments_valid=True, alignment_positive=True
34. mechanism WRONG → mechanism_correct=False
35. commitments_extracted WRONG → commitments_valid=False
36. commitments_satisfied WRONG → alignment_positive=False
37. Category: interpretable_success
38. Category: LEG_v2
39. Category: uninterpretable_success
40. Category: lucky_fix_v2

### Unit Tests: `tests/test_mapping_v2.py` (3 tests)
41. alias_config → ALIASING
42. async_race_lock → None (unmapped)
43. All 10 mapped families produce correct canonical name

### Integration Tests: `tests/test_v2_integration.py` (5 tests)
44. Baseline_v2 prompt renders via assembly engine
45. LEG v2 prompt renders with file_keys_example
46. Lean v2 prompt renders
47. Classifier v2 prompt renders with all variables
48. Full mock pipeline: synthetic response → parse → normalize → classify → metrics → category

### Schema Drift Tests: `tests/test_v2_schema_drift.py` (3 tests)
49. baseline_v2 template fields == V2_BASELINE_REQUIRED
50. leg_v2 template fields == V2_LEG_REQUIRED
51. lean_v2 template fields == V2_LEAN_REQUIRED

### Backward Compat: `tests/test_v1_frozen_fixtures.py` (5 tests)
52-56. As described in section 11.1

### Edge Cases (in test_reasoning_v2.py and test_metrics_v2.py)
57. Correct mechanism + violated commitments + code passes → lucky_fix_v2
58. Correct mechanism + valid commitments + code fails → LEG_v2
59. baseline_v2 + pass + no commitments → uninterpretable_success
60. Classifier returns unknown failure type → "UNKNOWN"
61. Commitments normalize to empty after dedup → commitments_valid=False

---

## 15. Logging / Observability

### 15.1 V2 Fields in ev Dict

All v2 fields are additive. RunLogger dumps full ev dict (no handpicking).

```
ev["schema_variant"] = "baseline_v2" | "leg_v2" | "lean_v2"

ev["v2_artifact"] = {
    raw_root_cause, raw_fix_strategy, raw_risk_check, raw_code_commitments,
    normalized_root_cause, normalized_fix_strategy, normalized_risk_check,
    normalized_code_commitments, normalization_notes,
    commitment_count, commitments_source, commitment_extractability_status,
    canonical_family, canonical_family_mapped,
    validation_status, validation_errors,
    parse_status,
}

ev["mechanism_correct"] = True | False | None
ev["commitments_valid"] = True | False | None
ev["alignment_positive"] = True | False | None
ev["v2_category"] = "interpretable_success" | "LEG_v2" | ...

ev["commitments_extracted_dim"] = "CORRECT" | "PARTIAL" | "WRONG"
ev["commitments_satisfied_dim"] = "CORRECT" | "PARTIAL" | "WRONG"
ev["mechanism_identified_dim"] = "CORRECT" | "PARTIAL" | "WRONG"
ev["reasoning_code_alignment_dim"] = "CORRECT" | "PARTIAL" | "WRONG"

ev["classify_v2_raw"] = "..."
ev["classify_v2_parse_error"] = None | "..."
```

### 15.2 Events.jsonl

New events include `schema_variant`. Analysis scripts MUST check this field before computing metrics.

### 15.3 What Must NOT Happen

- v2 events must NOT flow through `evaluate_output()` (v1 evaluator)
- v2 events must NOT have `reasoning_correct` computed by v1 `compute_reasoning_correct()`
- v2 events must NOT have `category` computed by v1 `compute_category()`
- v2 events must NOT be logged without `schema_variant`

---

## 16. Phased Rollout with Hard Abort Gates

### Phase 1: Modules + Unit Tests (no conditions registered)

**Deliverables:** 6 new modules, 61 tests
**Validation:** All tests pass. No existing tests broken.
**Abort:** ANY test failure.
**Rollback:** Delete 6 files. Zero impact.

### Phase 2: Register + Preflight (conditions exist but not runnable without config)

**Deliverables:** 3 legacy edits, preflight suite, schema drift tests, frozen fixture tests
**Validation:** All 15 preflight checks pass. All frozen fixtures match.
**Abort gates:**
- ANY v1 frozen fixture mismatch → halt
- ANY preflight failure → halt
- ANY existing test failure → halt
**Rollback:** Revert 3 files.

### Phase 3: Smoke (3 cases × 3 conditions × 1 model = 9 evals)

**Abort gates:**
- Classifier v2 parse failure > 33% → halt
- Missing `schema_variant` in ANY event → halt
- Missing `commitments_source` in ANY event → halt
- baseline_v2 `parse_status == "success"` < 67% → halt
- All `commitments_extracted == "WRONG"` for leg_v2 → halt
- v1 canary regression → halt

### Phase 4: Cost Gate (10 cases × 3 conditions × 1 model = 30 evals)

**Abort gates:**
- Classifier v2 parse failure > 20% → halt
- baseline_v2 parse success < 90% → halt
- leg_v2 parse success < 90% → halt
- `mechanism_correct` rate < 10% → halt
- `uninterpretable_success` > 50% for baseline_v2 → halt
- canonical_family_mapped=False for any exercised MAPPED case → mapping bug, halt
- v1 canary regression → halt

### Phase 5: Full Ablation

**Abort gates:**
- Classifier v2 parse failure > 15% for any model → halt
- `commitments_extracted == "WRONG"` > 80% for leg_v2 → halt
- v1 conditions in same run produce different results → contamination, halt

---

## 17. Resolved Design Decisions

1. **Spontaneous commitments in baseline_v2:** RESOLVED. Tagged as `commitments_source="spontaneous"`. Used by classifier.
2. **"SAFE" in lean_v2:** RESOLVED. Valid risk_check value. Not treated as empty or missing.
3. **Bug-family mapping:** RESOLVED. `mapping_v2.py` with explicit table. 10 mapped, 12 unmapped.
4. **Parser authority:** RESOLVED. `parser_v2.py` is the sole JSON deserializer. No delegation to parse_model_response.
5. **Separate log directory:** RESOLVED. No. Same log structure, differentiated by `schema_variant`.
6. **V1/V2 category comparability:** RESOLVED. Not comparable. Reports must segregate.
7. **Primary scientific measure:** RESOLVED. Three separate booleans (mechanism_correct, commitments_valid, alignment_positive). NOT the collapsed reasoning_correct_compat.

### Deferred (Non-Critical)

8. **Redis dashboard v2 metrics:** Deferred. Terminal dashboard sufficient.
9. **paper_analysis.py v2 support:** Deferred until results need reporting.
10. **Templates.py migration:** Deferred. Separate project.

### Blocked Pending User Decision

11. **Should unmapped families be EXCLUDED from v2 experiments?** Currently included with `canonical_family_mapped=False` logging. User may restrict via config filters if desired.
