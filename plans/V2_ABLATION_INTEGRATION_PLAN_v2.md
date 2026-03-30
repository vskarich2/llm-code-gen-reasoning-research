# V2 Ablation Integration Plan — Revised (v2)

**Date:** 2026-03-29
**Status:** Plan only. No implementation.
**Supersedes:** V2_ABLATION_INTEGRATION_PLAN.md

---

## 1. Executive Summary

This plan integrates 4 new prompt templates (baseline_v2, leg_reduction_v2, leg_reduction_lean_v2, classify_reasoning_v2, output_instruction_v3) as a NEW PARALLEL PATH through the evaluation pipeline.

**Core design principle:** v2 logic lives in DEDICATED MODULES. Legacy code is touched at exactly 3 routing points. All v2 data flows through a single normalized artifact that is the ONLY object downstream v2 code consumes.

**Key architectural decisions made in this plan:**
- `_raw_json` from `parse_model_response()` is the canonical source of truth for v2 fields. No re-parsing.
- Reasoning extraction, validation, classifier invocation, classifier parsing, and metric derivation live in ONE new module: `reasoning_v2.py`.
- Three new thin run functions live in ONE new module: `execution_v2.py`.
- `reasoning_correct` is NOT the primary scientific measure for v2. Three separate booleans are: `mechanism_correct`, `commitments_valid`, `alignment_positive`.
- v1 and v2 category labels are NOT directly comparable. Reports MUST segregate by `schema_variant`.
- "No extractable commitments + pass" is a FIRST-CLASS outcome: `uninterpretable_success`.

---

## 2. Canonical V2 Data Flow

```
raw LLM response (str)
    │
    ▼
parse_model_response()          [parse.py — UNCHANGED, no edits]
    │ returns: {files, _raw_json, response_format, reasoning_obj, reasoning_validation, ...}
    │
    ▼
_raw_json                       [CANONICAL SOURCE for v2 fields]
    │ contains: root_cause, code_commitments, fix_strategy, risk_check, files
    │
    ▼
extract_v2_reasoning()          [reasoning_v2.py — NEW]
    │ input: _raw_json dict
    │ output: V2ReasoningArtifact (full normalized object)
    │
    ▼
validate_v2_reasoning()         [reasoning_v2.py — NEW]
    │ input: V2ReasoningArtifact
    │ output: V2ValidationResult
    │
    ▼
build_v2_classifier_vars()      [reasoning_v2.py — NEW]
    │ input: V2ReasoningArtifact + case
    │ output: dict of template variables for classify_reasoning_v2.j2
    │
    ▼
assembly_engine.build()         [UNCHANGED — just renders a different template]
    │ components: ["classify_reasoning_v2"]
    │
    ▼
call_model()                    [UNCHANGED]
    │
    ▼
parse_v2_classifier_output()    [reasoning_v2.py — NEW]
    │ input: raw classifier response str
    │ output: V2ClassifierResult (4 dimensions + metadata)
    │
    ▼
derive_v2_metrics()             [reasoning_v2.py — NEW]
    │ input: V2ClassifierResult
    │ output: {mechanism_correct, commitments_valid, alignment_positive,
    │          reasoning_correct_compat, category}
    │
    ▼
ev dict                         [populated by execution_v2.py run function]
    │ includes: all v2 fields, schema_variant, full V2ReasoningArtifact
    │
    ▼
RunLogger                       [UNCHANGED — dumps full ev dict]
```

**Authority rule:** `_raw_json` from `parse_model_response()` is the ONE source of truth for v2 reasoning fields. `extract_v2_reasoning()` reads from `_raw_json` ONLY. It does NOT re-parse the raw response string. If `_raw_json` is None (parse failure), the v2 extractor receives an empty dict and produces a failure artifact.

**Example for leg_reduction_v2 response:**

```
Model returns: {"root_cause": "...", "code_commitments": ["..."], "fix_strategy": "...", "risk_check": "...", "files": {"a.py": "..."}}

parse_model_response() returns:
  files: {"a.py": "..."}
  _raw_json: {"root_cause": "...", "code_commitments": ["..."], ...}  ← v2 fields live HERE
  response_format: "file_dict"
  reasoning_obj: {"root_cause": "...", "fix_strategy": "...", ...}    ← v1 extraction (partial, ignores code_commitments)
  reasoning_validation: {reasoning_present: True, schema_matched: "leg"}

extract_v2_reasoning(_raw_json) returns:
  V2ReasoningArtifact with code_commitments populated from _raw_json["code_commitments"]
```

**Example for baseline_v2 response (no commitments):**

```
Model returns: {"root_cause": "...", "fix_strategy": "...", "files": {"a.py": "..."}}

_raw_json: {"root_cause": "...", "fix_strategy": "...", "files": {...}}
  → no "code_commitments" key

extract_v2_reasoning(_raw_json) returns:
  V2ReasoningArtifact with code_commitments=[], commitments_source="none"
```

---

## 3. Current Impact Surface Audit

### 3.1 File Size / Bloat Assessment

| File | Lines | Responsibility | Bloat risk |
|------|-------|---------------|------------|
| `execution.py` | 1272 | Prompt building, run functions, logging, metrics events | **HIGH** — already over 4x the 300-line limit. Adding v2 here worsens it. |
| `parse.py` | 790 | Multi-tier parser + code extraction | **MEDIUM** — large but stable. No v2 edits needed. |
| `runner.py` | 707 | Orchestration, CLI, ablation mode, results printing | **MEDIUM** — 3-line routing edit acceptable. |
| `evaluator.py` | 580 | Classifier invocation, evaluate_output, evidence metrics | **HIGH** — adding v2 classifier here worsens coupling. |
| `reasoning.py` | 333 | V1 reasoning schema, classifier parsing, category computation | **MEDIUM** — v2 should NOT go here (different dimensions, different semantics). |
| `constants.py` | 114 | Condition names, labels | **LOW** — additive edit, self-validating. |
| `assembly_engine.py` | 122 | Prompt rendering | **LOW** — no edits needed. |
| `prompt_registry.py` | 193 | Template loading | **LOW** — auto-discovers new .j2 files. |
| `leg_reduction.py` | 102 | Current LEG parser | **LOW** — v2 does NOT use this file. |

### 3.2 Decision: v2 Logic Gets Dedicated Modules

Given that `execution.py` is already 1272 lines and `evaluator.py` is 580 lines, adding v2 functions to them would worsen the bloat and increase regression risk from accidental edits to surrounding code.

**Decision:** v2 logic lives in TWO new modules:

| New module | Responsibility | Lines (est.) |
|-----------|---------------|-------------|
| `reasoning_v2.py` | V2ReasoningArtifact, extraction, validation, normalization, classifier var builder, classifier output parser, metric derivation | ~250 |
| `execution_v2.py` | `run_baseline_v2()`, `run_leg_v2()`, `run_lean_v2()`, `evaluate_case_v2()` | ~150 |

These modules import FROM existing modules (assembly_engine, llm, parse, exec_eval) but existing modules do NOT import from them. The dependency is one-directional.

**Justification over appending to existing files:**
- `execution.py` has 5 different run functions already. A 6th, 7th, 8th with different evaluation paths would make the file unnavigable.
- `evaluator.py` has tight coupling between `llm_classify` and `evaluate_output`. A v2 variant with different dimensions would require either branching inside those functions (fragile) or duplicating them (drift risk). Dedicated module is cleaner.
- `reasoning.py` defines v1 constants (`CLASSIFIER_DIMENSIONS`, `BASELINE_REASONING_FIELDS`). Putting v2 constants there creates confusion about which version is active.

---

## 4. Dedicated Module Boundary Decision

### 4.1 `reasoning_v2.py` — SINGLE module for all v2 reasoning logic

**Contains:**
- `V2ReasoningArtifact` dataclass (the normalized artifact)
- `V2ValidationResult` dataclass
- `V2ClassifierResult` dataclass
- `V2Metrics` dataclass
- `extract_v2_reasoning(raw_json: dict) -> V2ReasoningArtifact`
- `validate_v2_reasoning(artifact: V2ReasoningArtifact) -> V2ValidationResult`
- `normalize_commitments(raw: list[str]) -> list[str]`
- `build_v2_classifier_vars(artifact: V2ReasoningArtifact, case: dict, code: str, config) -> dict`
- `parse_v2_classifier_output(raw: str) -> V2ClassifierResult`
- `derive_v2_metrics(classifier: V2ClassifierResult) -> V2Metrics`
- `compute_v2_category(code_correct: bool, metrics: V2Metrics) -> str`
- `V2_CLASSIFIER_DIMENSIONS` constant
- `CANONICAL_COMMITMENT_FAMILIES` mapping
- `FAILURE_MODE_TO_COMMITMENT_FAMILY` mapping

**Does NOT contain:**
- LLM call logic (that's in `execution_v2.py`)
- Prompt rendering (that's in `assembly_engine.py`)
- Code execution (that's in `exec_eval.py`)
- Event emission or logging (that's in `execution_v2.py`)

### 4.2 `execution_v2.py` — SINGLE module for v2 run functions

**Contains:**
- `run_baseline_v2(case, model) -> (case_id, condition, ev)`
- `run_leg_v2(case, model) -> (case_id, condition, ev)`
- `run_lean_v2(case, model) -> (case_id, condition, ev)`
- `evaluate_case_v2(case, raw_output, condition) -> (parsed, ev)` — internal helper

**Imports from:**
- `assembly_engine.build` — prompt rendering
- `llm.call_model` — API call
- `parse.parse_model_response` — parsing
- `exec_eval.exec_evaluate` — code execution
- `reasoning_v2.*` — all v2 reasoning logic
- `execution.write_log`, `execution._emit_metrics_event` — logging (reuses existing logging, does NOT create new loggers)

**Does NOT import:**
- `evaluator.evaluate_output` (uses its own v2 evaluation pipeline)
- `evaluator.llm_classify` (uses `reasoning_v2` for classifier invocation)
- `reasoning.py` (does not need v1 logic)

---

## 5. V2 Data Contracts

### 5.1 V2ReasoningArtifact (the FULL normalized object)

```python
@dataclass
class V2ReasoningArtifact:
    # Raw fields (exactly as model produced, before normalization)
    raw_root_cause: str
    raw_fix_strategy: str
    raw_risk_check: str              # "" if not produced (baseline_v2)
    raw_code_commitments: list[str]  # [] if not produced (baseline_v2)

    # Normalized fields
    normalized_root_cause: str       # stripped, non-empty or "[EMPTY]"
    normalized_fix_strategy: str     # stripped, non-empty or "[EMPTY]"
    normalized_risk_check: str       # stripped, "" allowed for baseline_v2
    normalized_code_commitments: list[str]  # normalized per rules in section 7

    # Provenance
    commitment_count: int            # len(normalized_code_commitments)
    commitments_source: str          # "explicit" | "spontaneous" | "none"
    commitment_extractability_status: str  # "present" | "absent" | "malformed"
    schema_variant: str              # "baseline_v2" | "leg_v2" | "lean_v2"

    # Parse provenance
    parse_source: str                # "raw_json" | "fallback" | "none"
    parse_status: str                # "full" | "partial" | "failed"

    # Classifier configuration (set before classifier invocation)
    classifier_prompt_variant: str   # "classify_reasoning_v2"
    classifier_schema_variant: str   # "v2_5line"

    # Validation (set by validate_v2_reasoning)
    validation_result: str           # "valid" | "partial" | "invalid"
    validation_errors: list[str]     # specific errors
```

**Who produces it:** `extract_v2_reasoning(raw_json, schema_variant)`
**Who validates it:** `validate_v2_reasoning(artifact)`
**Who consumes it:** `build_v2_classifier_vars()`, `execution_v2.py` (to populate ev dict), logging

### 5.2 How It Differs by Condition

| Field | baseline_v2 | leg_v2 | lean_v2 |
|-------|------------|--------|---------|
| `raw_risk_check` | `""` | present | present (may be "SAFE") |
| `raw_code_commitments` | `[]` | 1-3 items | 1-2 items |
| `commitments_source` | `"none"` | `"explicit"` | `"explicit"` |
| `commitment_extractability_status` | `"absent"` | `"present"` | `"present"` |

If baseline_v2 model SPONTANEOUSLY includes `code_commitments` (not asked for):
- `commitments_source = "spontaneous"`
- `commitment_extractability_status = "present"`
- These are used by the classifier exactly like explicit commitments

### 5.3 V2ClassifierResult

```python
@dataclass
class V2ClassifierResult:
    # Dimensions (CORRECT / PARTIAL / WRONG / None on parse failure)
    mechanism_identified: str | None
    commitments_extracted: str | None
    commitments_satisfied: str | None
    reasoning_code_alignment: str | None

    # Metadata
    failure_type: str
    failure_type_raw: str
    confidence: str                  # HIGH / MEDIUM / LOW
    counterfactual: str
    evidence: str
    judgment: str

    # Parse status
    parse_error: str | None
    classify_raw: str                # full raw classifier output
```

### 5.4 V2Metrics (derived from classifier)

```python
@dataclass
class V2Metrics:
    # Three SEPARATE booleans — NOT collapsed
    mechanism_correct: bool | None       # mechanism_identified == CORRECT
    commitments_valid: bool | None       # commitments_extracted in (CORRECT, PARTIAL)
                                         # AND commitments_satisfied in (CORRECT, PARTIAL)
    alignment_positive: bool | None      # reasoning_code_alignment in (CORRECT, PARTIAL)

    # Compatibility boolean (NOT the primary scientific measure)
    reasoning_correct_compat: bool | None  # all three above are True
    # This exists ONLY for backward-compat category computation.
    # It MUST NOT be reported as the primary metric.
    # Reports must show mechanism_correct, commitments_valid, alignment_positive separately.
```

---

## 6. Parsing Authority and Strategy

### 6.1 Authority Decision

**`parse_model_response()` is the SOLE JSON deserializer.** It produces `_raw_json` which is the canonical source for all v2 fields.

`extract_v2_reasoning()` reads from `_raw_json`. It does NOT call `json.loads()`. It does NOT access the raw response string. If `_raw_json` is None, it produces a failure artifact.

**This is a hard rule.** No v2 code may re-parse the raw response string. There is ONE parser authority.

### 6.2 What `parse_model_response()` Guarantees for V2

When a v2 response is well-formed JSON with a `files` key:
- `response_format = "file_dict"`
- `files = {"path": "content", ...}` — the file dict
- `_raw_json = {full parsed JSON}` — contains root_cause, code_commitments, fix_strategy, risk_check, files
- `code = None` (file-dict format returns code=None; reconstructor handles files)
- `reasoning_obj` — v1 extraction (may be partial; v2 extractor uses `_raw_json` instead)
- `reasoning_validation` — v1 validation (may match "leg" schema; v2 has its own validation)

When a v2 response is malformed:
- Falls through parser tiers (lenient JSON, code block, raw fallback)
- `_raw_json` may be None or partial
- `extract_v2_reasoning(None)` produces a failure artifact with `parse_status = "failed"`

### 6.3 Schema Drift Detection

Each v2 condition has a REQUIRED FIELD SET:

| Condition | Required in `_raw_json` |
|-----------|------------------------|
| baseline_v2 | `root_cause`, `fix_strategy`, `files` |
| leg_v2 | `root_cause`, `code_commitments`, `fix_strategy`, `risk_check`, `files` |
| lean_v2 | `root_cause`, `code_commitments`, `fix_strategy`, `risk_check`, `files` |

`validate_v2_reasoning()` checks these per `schema_variant`. Missing required fields produce `validation_result = "partial"` or `"invalid"`.

**Test for drift:** A preflight test renders each template, extracts the JSON schema from the template text, and asserts field parity with the validator's required fields. If the template adds a field the validator doesn't know about, or vice versa, the test fails.

---

## 7. Commitment Extraction / Normalization / Provenance Plan

### 7.1 Normalization Rules

`normalize_commitments(raw: list[str]) -> list[str]` applies these rules IN ORDER:

1. **Strip whitespace** from each commitment string
2. **Skip empty** strings after stripping
3. **Atomic splitting:** If a commitment contains " and " or " + " joining two independent clauses, split into separate commitments. Example: `"create_config must return copy and reset_defaults must clear cache"` → two commitments.
4. **Scope preservation:** The `<scope>` portion (before "must") must be preserved exactly. Do NOT add scope to scopeless commitments. If a commitment has no identifiable scope, preserve it as-is and flag as `scopeless`.
5. **Negation normalization:** Convert `"must not X"` and `"should not X"` to canonical form `"<scope> must not <action>"`. Do NOT strengthen `"should not"` to `"must not"` — preserve the original modal.
6. **Deduplication:** Remove exact duplicates (case-insensitive comparison after normalization).
7. **Do NOT strengthen vague commitments.** `"fix shared state"` remains `"fix shared state"` — it is NOT normalized to `"create_config must return copy"`. The classifier evaluates vagueness.
8. **Do NOT add missing information.** If the model said `"must return copy"` without naming a function, the normalized form is `"[unscoped] must return copy"`.

### 7.2 Examples

**Explicit commitment normalization:**
```
Input:  "create_config must return a copy of DEFAULTS  "
Output: "create_config must return a copy of DEFAULTS"
```

**Compound commitment split:**
```
Input:  "create_config must return copy and DEFAULTS must not be mutated"
Output: ["create_config must return copy", "DEFAULTS must not be mutated"]
```

**Vague extracted commitment that must remain vague:**
```
Input:  "fix the aliasing issue"
Output: "fix the aliasing issue"  (NOT strengthened to a specific commitment)
```

**Negative commitment:**
```
Input:  "update_product should not leave stale cache entries"
Output: "update_product should not leave stale cache entries"  (modal preserved)
```

### 7.3 When Normalization Happens

- **Before classifier invocation:** normalized commitments are passed to the classifier template. This ensures the classifier sees clean input.
- **Raw commitments are preserved** in `V2ReasoningArtifact.raw_code_commitments` for debugging/analysis.
- **Extracted commitments from classifier** (when baseline_v2 has no explicit commitments) are NOT normalized by our code — they come from the classifier LLM and are logged as-is.

---

## 8. Canonical Commitment Family Mapping

### 8.1 Primary Mapping Source: `failure_mode` field on the case

The v2 classifier template lists canonical commitment patterns by BUG FAMILY NAME (ALIASING, STALE_CACHE, etc.). These map to the case's `failure_mode` field.

**Full mapping table:**

| Case family | `failure_mode` | Classifier canonical family | Canonical commitments |
|-------------|---------------|---------------------------|----------------------|
| alias_config | ALIASING | ALIASING | returned objects must not share mutable references; functions must return new instance; mutations must not affect original |
| partial_update | PARTIAL_STATE_UPDATE | PARTIAL_STATE_UPDATE | all dependent fields must be updated; derived fields must be recomputed; no stale dependent state |
| stale_cache | STALE_CACHE | STALE_CACHE | cache must be invalidated after writes; reads must not return stale values; cache and source must remain consistent |
| mutable_default | MUTABLE_DEFAULT | MUTABLE_DEFAULT | default mutable arguments must not be shared; new state per invocation; no implicit accumulation |
| effect_order | SIDE_EFFECT_ORDER | SIDE_EFFECT_ORDER | side effects at correct granularity; updates align with iteration; outputs reflect each operation |
| use_before_set | USE_BEFORE_SET | USE_BEFORE_SET | variables initialized before reads; all control paths define required variables |
| retry_dup | RETRY_DUPLICATION | RETRY_DUPLICATION | retry must not duplicate successful operations; loop terminates after success; operations idempotent or guarded |
| partial_rollback | PARTIAL_ROLLBACK | PARTIAL_ROLLBACK | failed operations revert prior state; rollback restores invariants; no partial state persists |
| temporal_drift | TEMPORAL_DRIFT | TEMPORAL_DRIFT | computations use correct stage of data; raw metrics before transformation |
| missing_branch | MISSING_BRANCH | MISSING_BRANCH | all valid input cases handled; no valid case falls through |
| early_return | EARLY_RETURN | (no canonical family in template) | **UNMAPPED** |
| wrong_condition | WRONG_CONDITION | (no canonical family) | **UNMAPPED** |
| lazy_init | INIT_ORDER | (no canonical family) | **UNMAPPED** |
| silent_default | SILENT_DEFAULT | (no canonical family) | **UNMAPPED** |
| index_misalign | INDEX_MISALIGN | (no canonical family) | **UNMAPPED** |
| hidden_dep_multihop | HIDDEN_DEPENDENCY | (no canonical family) | **UNMAPPED** |
| invariant_partial_fail | INVARIANT_VIOLATION | (no canonical family) | **UNMAPPED** |
| l3_state_pipeline | STATE_SEMANTIC_VIOLATION | (no canonical family) | **UNMAPPED** |
| async_race_lock | RACE_CONDITION | (no canonical family) | **UNMAPPED** |
| check_then_act | RACE_CONDITION | (no canonical family) | **UNMAPPED** |
| false_fix_deadlock | RACE_CONDITION | (no canonical family) | **UNMAPPED** |
| lost_update | RACE_CONDITION | (no canonical family) | **UNMAPPED** |
| config_shadowing | PARTIAL_STATE_UPDATE | PARTIAL_STATE_UPDATE | (shares with partial_update) |
| ordering_dependency | TEMPORAL_ORDERING | (no canonical family) | **UNMAPPED** |
| overdetermination | HIDDEN_DEPENDENCY | (no canonical family) | **UNMAPPED** |
| feature_flag_drift | FLAG_DRIFT | (no canonical family) | **UNMAPPED** |
| cache_invalidation_order | CACHE_ORDERING | (no canonical family) | **UNMAPPED** |
| commit_gate | INVARIANT_VIOLATION | (no canonical family) | **UNMAPPED** |

### 8.2 Unmapped Families: Design Decision

**17 of 28 case families have NO canonical commitment pattern** in the v2 classifier template.

**Decision: RESOLVED.** For unmapped families, the classifier operates without canonical matching. It extracts and evaluates commitments based on the model's own stated reasoning, without comparing against a reference pattern. The `commitments_extracted` dimension reflects whether the model produced valid, checkable commitments — not whether they match a canonical pattern.

This means:
- For MAPPED families (11/28): classifier has both model commitments AND canonical reference → stronger signal
- For UNMAPPED families (17/28): classifier has only model commitments → weaker signal, more classifier judgment

This asymmetry MUST be logged as `canonical_family_mapped: true/false` in the V2ReasoningArtifact and reported in analysis.

### 8.3 Mapping Function

```
def get_canonical_family(case: dict) -> str | None:
    """Return canonical commitment family for a case, or None if unmapped."""
    FAILURE_MODE_TO_FAMILY = {
        "ALIASING": "ALIASING",
        "PARTIAL_STATE_UPDATE": "PARTIAL_STATE_UPDATE",
        "STALE_CACHE": "STALE_CACHE",
        "MUTABLE_DEFAULT": "MUTABLE_DEFAULT",
        "SIDE_EFFECT_ORDER": "SIDE_EFFECT_ORDER",
        "USE_BEFORE_SET": "USE_BEFORE_SET",
        "RETRY_DUPLICATION": "RETRY_DUPLICATION",
        "PARTIAL_ROLLBACK": "PARTIAL_ROLLBACK",
        "TEMPORAL_DRIFT": "TEMPORAL_DRIFT",
        "MISSING_BRANCH": "MISSING_BRANCH",
    }
    return FAILURE_MODE_TO_FAMILY.get(case.get("failure_mode"))
```

This function lives in `reasoning_v2.py`. It is the ONLY place that defines this mapping.

---

## 9. Classifier V2 Integration Plan

### 9.1 Classifier V2 Prompt Variables

`build_v2_classifier_vars()` produces:

```python
{
    "root_cause": artifact.normalized_root_cause or "[COULD NOT EXTRACT]",
    "fix_strategy": artifact.normalized_fix_strategy or "[COULD NOT EXTRACT]",
    "risk_check": artifact.normalized_risk_check or "[COULD NOT EXTRACT]",
    "task": case["task"][:max_task_chars],
    "code": code[:max_code_chars],
    "failure_types": ", ".join(sorted(VALID_FAILURE_TYPES)),
    "classifier_mode": classifier_mode,
    # Grounded mode fields:
    "ground_truth_failure_mode": case.get("failure_mode", ""),
    "ground_truth_trap": case.get("trap", ""),
    "ground_truth_invariant": case.get("ground_truth_bug", {}).get("invariant", ""),
}
```

Note: `code_commitments` are NOT passed as a template variable. The classifier template instructs the evaluator to extract commitments from the reasoning fields (root_cause + fix_strategy) or use explicit commitments if they happen to be embedded in the root_cause/fix_strategy text. The template's STEP 2 handles this internally.

**Rationale:** The classifier must determine commitment quality itself. Pre-passing structured commitments would bypass the classifier's extraction evaluation, which is one of the dimensions we're measuring.

### 9.2 Classifier V2 Output Format

```
Line 1: <mechanism>;<commitments_extracted>;<commitments_satisfied>;<alignment>;<failure_type>
Line 2: <confidence>
Line 3: Counterfactual: <sentence>
Line 4: Evidence: <bullets>
Line 5: Judgment: <sentences>
```

**Difference from v1:** Line 1 has 5 semicolon-separated fields (4 dimensions + failure_type). V1 has 6 fields (5 dimensions + failure_type).

### 9.3 V2 Classifier Output Parser

`parse_v2_classifier_output(raw: str) -> V2ClassifierResult`:

```
V2_CLASSIFIER_DIMENSIONS = (
    "mechanism_identified",
    "commitments_extracted",
    "commitments_satisfied",
    "reasoning_code_alignment",
)
```

Parsing logic: same 5-line structure as v1 but with 5 fields on line 1 (4 dims + failure_type) instead of 6.

### 9.4 Grounded vs Blind Mode

**Decision: RESOLVED.** The v2 classifier supports BOTH modes, same as v1. The `classifier_mode` variable controls this. Grounded mode adds ground truth fields. The template has conditional sections for this.

---

## 10. Metric Separation Plan

### 10.1 Three Separate Booleans (NOT Collapsed)

| Metric | Derivation | What it measures |
|--------|-----------|-----------------|
| `mechanism_correct` | `mechanism_identified == "CORRECT"` | Did the model correctly diagnose the bug? |
| `commitments_valid` | `commitments_extracted in (CORRECT, PARTIAL) AND commitments_satisfied in (CORRECT, PARTIAL)` | Did the model produce valid commitments AND did the code satisfy them? |
| `alignment_positive` | `reasoning_code_alignment in (CORRECT, PARTIAL)` | Does the code match the stated reasoning? |

### 10.2 Compatibility Boolean

`reasoning_correct_compat = mechanism_correct AND commitments_valid AND alignment_positive`

**This is NOT the primary scientific measure.** It exists only for:
- backward-compatible category computation (`compute_v2_category`)
- quick filtering in analysis scripts

Reports MUST show the three separate booleans. The collapsed boolean is a convenience, not a truth.

### 10.3 New Metrics (v2-only)

| Metric | Type | Description |
|--------|------|-------------|
| `mechanism_correct` | bool | diagnosis quality |
| `commitments_valid` | bool | extractability + satisfaction |
| `alignment_positive` | bool | code matches reasoning |
| `commitments_source` | str | "explicit" / "spontaneous" / "none" |
| `commitments_count` | int | number of normalized commitments |
| `canonical_family_mapped` | bool | whether case has canonical patterns |
| `commitments_extracted` | str | CORRECT/PARTIAL/WRONG (raw classifier dim) |
| `commitments_satisfied` | str | CORRECT/PARTIAL/WRONG (raw classifier dim) |
| `schema_variant` | str | which v2 condition |

---

## 11. Category Semantics Plan

### 11.1 V2 Categories

`compute_v2_category()` uses `reasoning_correct_compat` (the collapsed boolean) as input to category logic:

| Category | Definition |
|----------|-----------|
| `true_success` | `code_correct AND reasoning_correct_compat` |
| `leg` | `NOT code_correct AND reasoning_correct_compat` |
| `lucky_fix` | `code_correct AND NOT reasoning_correct_compat AND commitments_valid` |
| `uninterpretable_success` | `code_correct AND commitments_source == "none" AND NOT commitments_valid` |
| `true_failure` | `NOT code_correct AND NOT reasoning_correct_compat` |
| `no_reasoning` | `reasoning_present == False` |
| `parse_failed` | raw response could not be parsed |
| `classifier_parse_failed` | classifier output could not be parsed |

### 11.2 V1 vs V2 Comparability

**Decision: RESOLVED.** V1 and V2 category labels are NOT directly comparable.

- v1 `reasoning_correct` is derived from 5 dimensions (mechanism, invariant, causal, fix, alignment)
- v2 `reasoning_correct_compat` is derived from 4 dimensions (mechanism, commitments_extracted, commitments_satisfied, alignment)
- v1 has no `uninterpretable_success` category
- v2 `commitments_valid` combines extractability + satisfaction, which has no v1 equivalent

**Reporting rule:** All reports MUST include `schema_variant` as a grouping variable. v1 and v2 results must NOT be pooled without explicit acknowledgment.

---

## 12. Uninterpretable Success Handling

### 12.1 Definition

A case is `uninterpretable_success` when:
- Code passes (`code_correct == True`)
- Model provided no commitments (`commitments_source == "none"`)
- Classifier could not validate commitments (`commitments_valid == False`)

This is distinct from `lucky_fix` because:
- `lucky_fix` = model tried to reason but got it wrong
- `uninterpretable_success` = model didn't provide enough structure to evaluate reasoning at all

### 12.2 Handling

- Tracked as a FIRST-CLASS category in v2
- Reported separately in all v2 analysis
- Does NOT fold into `lucky_fix` for reporting
- For backward-compat metrics only, MAY be grouped with `lucky_fix` if explicitly labeled

### 12.3 Expected Distribution

- Primarily in `baseline_v2` (which doesn't ask for commitments)
- Occasionally in `lean_v2` if model produces vague commitments the classifier rejects
- Never in `leg_v2` if the model complies with the prompt (explicit commitments required)

---

## 13. Downstream Consumer Audit

| Consumer | Fields consumed | v2 risk | Required action | Severity if ignored |
|----------|----------------|---------|-----------------|-------------------|
| `scripts/paper_analysis.py` | reasoning_correct, alignment, leg_rate, lucky_fix, pass_rate | `reasoning_correct` semantics differ in v2 | Filter by `schema_variant`; do not mix v1/v2 | **HIGH** — silent metric corruption |
| `scripts/leg_ablation_analysis.py` | category, failure_type, leg_true, alignment | category semantics differ; new category `uninterpretable_success` | Branch on `schema_variant` or disable for v2 | **HIGH** — miscounts LEG |
| `scripts/redis_live_dashboard.py` | leg_true, lucky_fix, true_success, pass_rate, failure_type | `leg_true` derivation differs; new categories not displayed | Add `schema_variant` filter; add `uninterpretable_success` to display | **MEDIUM** — misleading dashboard |
| `scripts/monitor_ablation.py` | pass_rate, leg_rate, lucky_fix, true_success | same issues as dashboard | Filter by `schema_variant` | **MEDIUM** |
| `scripts/merge_and_validate.py` | event count validation | new conditions = new expected tuples | Update expected counts when v2 conditions included | **LOW** — validation failure, not silent lie |
| `scripts/canary_run.py` | pass_rate | pass_rate is unaffected by v2 reasoning changes | No change needed | **NONE** |
| `scripts/update_dashboards.py` | (unclear, may be legacy) | unknown | Audit before enabling v2 | **LOW** |

---

## 14. Output Instruction / Schema Authority Plan

### 14.1 Schema Authority Per Condition

| Condition | Schema authority | Parser validator | Drift detection |
|-----------|-----------------|-----------------|-----------------|
| baseline_v2 | `output_instruction_v3.j2` + `V2_BASELINE_REQUIRED = {"root_cause", "fix_strategy", "files"}` | `validate_v2_reasoning()` checks against `V2_BASELINE_REQUIRED` | Preflight test asserts template JSON schema fields == validator required fields |
| leg_v2 | Template-local JSON in `leg_reduction_v2.j2` STEP 5 + `V2_LEG_REQUIRED = {"root_cause", "code_commitments", "fix_strategy", "risk_check", "files"}` | `validate_v2_reasoning()` checks against `V2_LEG_REQUIRED` | Preflight test asserts parity |
| lean_v2 | Template-local JSON in `leg_reduction_lean_v2.j2` section 5 + `V2_LEAN_REQUIRED = {"root_cause", "code_commitments", "fix_strategy", "risk_check", "files"}` | Same as leg_v2 | Same |

### 14.2 Drift Detection Test

For each v2 condition:
1. Render the template with placeholder variables
2. Extract the JSON schema from the rendered text (find `{` ... `}` in the "schema" section)
3. Parse the schema to get field names
4. Assert field names == validator's required fields for that condition
5. If mismatch → test FAILS → template and validator are out of sync

---

## 15. Backward Compatibility Plan

### 15.1 Frozen Fixture Regression Checks

For EACH existing v1 condition (baseline, diagnostic, guardrail, etc.):

1. **Prompt byte check:** Render the prompt for a fixed case. Assert output bytes match a frozen fixture. If any v2 change altered prompt_manifest or assembly_engine behavior, this catches it.

2. **Parser output check:** Feed a frozen v1 response string through `parse_model_response()`. Assert output dict matches a frozen fixture. If parse.py was accidentally changed, this catches it.

3. **Category output check:** Feed frozen v1 classifier dimensions through `compute_reasoning_correct()` and `compute_category()`. Assert output matches frozen fixture. If reasoning.py was accidentally changed, this catches it.

4. **Log shape check:** Produce a log record for a v1 condition. Assert the record's top-level keys match a frozen set. If RunLogger serialization changed, this catches it.

5. **Condition registry check:** Assert `VALID_CONDITIONS` contains all old conditions. Assert `COND_LABELS` maps all old conditions to their previous labels.

### 15.2 What Could Break

| Change | Breakage vector | Check |
|--------|----------------|-------|
| New entries in `constants.py` | Assertion failures if structure changes | Fixture check 5 |
| New entries in `prompt_manifest.yaml` | Could affect YAML loading order | Fixture check 1 |
| New imports in `execution.py` / `evaluator.py` | Import errors, circular deps | Run existing test suite |
| New `.j2` files in `prompts/components/` | Registry auto-loads them; could affect component count assertions | Check test_assembly_engine |

---

## 16. V2 Preflight Plan

Run BEFORE any v2 API calls. All checks must pass. Any failure = hard stop.

1. **Template render check:** All 4 v2 templates render with placeholder variables without Jinja2 errors.
2. **Output instruction v3 schema parity:** baseline_v2 template schema fields match validator required fields.
3. **LEG v2 schema parity:** leg_v2 template schema fields match validator required fields.
4. **Lean v2 schema parity:** lean_v2 template schema fields match validator required fields.
5. **Classifier v2 output shape:** Feed a synthetic 5-line classifier response through `parse_v2_classifier_output()`. Assert it parses without error.
6. **V2 schema variants accepted:** Feed synthetic JSON for each v2 condition through `extract_v2_reasoning()`. Assert no crash. Assert `schema_variant` is correct.
7. **Baseline v2 no-commitments accepted:** Feed baseline_v2 JSON (no `code_commitments` key) through `extract_v2_reasoning()`. Assert `commitments_source = "none"`, `commitment_extractability_status = "absent"`. Assert this is NOT treated as a parse failure.
8. **Canonical mapping coverage:** For every case in the v2 experiment config, call `get_canonical_family(case)`. Assert the result is either a valid family name or `None`. Log which cases are unmapped.
9. **Event schema completeness:** Run one synthetic v2 evaluation. Assert the ev dict contains: `schema_variant`, `commitments_source`, `mechanism_correct`, `commitments_valid`, `alignment_positive`, `commitments_extracted`, `commitments_satisfied`.
10. **V1 regression check:** Run one frozen v1 case through the existing pipeline. Assert identical output to frozen fixture.

---

## 17. Required Small Integration Edits

### Edit 1: `constants.py` — add 3 conditions

Add to `ALL_CONDITIONS`, `SIMPLE_CONDITIONS` (by not adding to RETRY or MULTISTEP), `COND_LABELS`.

**Risk:** Minimal. Self-validating assertions catch errors.
**Regression:** Fixture check 5 (condition registry).

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

**Risk:** Minimal. Additive. Existing conditions untouched.
**Regression:** Fixture check 1 (prompt bytes for v1 conditions).

### Edit 3: `runner.py:_run_one_inner()` — add 3 routing lines

```python
if condition in ("baseline_v2", "leg_reduction_v2", "leg_reduction_lean_v2"):
    from execution_v2 import run_v2_condition
    return run_v2_condition(case, model, condition)
```

ONE branch, not three. The v2 module handles condition dispatch internally.

**Risk:** Low. New branch only fires for new conditions. `run_v2_condition` is in a separate module — import failure would crash only v2 runs.
**Regression:** Run existing v1 test suite to verify no v1 condition is affected.

---

## 18. Test Plan

### Unit Tests (`tests/test_reasoning_v2.py`)

| # | Test | What it validates |
|---|------|------------------|
| 1 | `test_extract_v2_leg_full` | All fields present → correct artifact |
| 2 | `test_extract_v2_baseline_no_commitments` | No commitments → source="none", status="absent" |
| 3 | `test_extract_v2_baseline_spontaneous_commitments` | Unexpected commitments → source="spontaneous" |
| 4 | `test_extract_v2_missing_root_cause` | → validation_result="invalid" |
| 5 | `test_extract_v2_malformed_commitments_string` | String instead of list → normalized to list |
| 6 | `test_extract_v2_empty_raw_json` | None input → parse_status="failed" |
| 7 | `test_normalize_commitments_strip_dedup` | Whitespace, duplicates removed |
| 8 | `test_normalize_commitments_atomic_split` | "X and Y" → two commitments |
| 9 | `test_normalize_commitments_preserve_vague` | Vague commitment stays vague |
| 10 | `test_normalize_commitments_negation` | "must not" preserved |
| 11 | `test_normalize_commitments_scopeless` | No scope → "[unscoped] must ..." |
| 12 | `test_validate_v2_leg_valid` | All required → valid |
| 13 | `test_validate_v2_baseline_valid` | No commitments acceptable for baseline |
| 14 | `test_validate_v2_lean_risk_check_SAFE` | "SAFE" accepted as valid risk_check |
| 15 | `test_parse_v2_classifier_valid` | 5-line output → correct dimensions |
| 16 | `test_parse_v2_classifier_wrong_field_count` | 4 fields on line 1 → parse_error |
| 17 | `test_parse_v2_classifier_bad_dimension` | "MAYBE" → parse_error |
| 18 | `test_derive_v2_metrics_all_correct` | mechanism_correct=True, commitments_valid=True, alignment_positive=True |
| 19 | `test_derive_v2_metrics_mechanism_wrong` | mechanism_correct=False |
| 20 | `test_derive_v2_metrics_commitments_wrong` | commitments_valid=False |
| 21 | `test_compute_v2_category_true_success` | correct code + correct reasoning |
| 22 | `test_compute_v2_category_leg` | wrong code + correct reasoning |
| 23 | `test_compute_v2_category_uninterpretable_success` | correct code + no commitments |
| 24 | `test_compute_v2_category_lucky_fix` | correct code + wrong reasoning + commitments present |
| 25 | `test_canonical_family_mapped` | alias_config → ALIASING |
| 26 | `test_canonical_family_unmapped` | async_race_lock → None |

### Integration Tests (`tests/test_v2_integration.py`)

| # | Test |
|---|------|
| 27 | Baseline_v2 prompt renders via assembly engine |
| 28 | LEG v2 prompt renders with file_keys_example |
| 29 | Lean v2 prompt renders |
| 30 | Classifier v2 prompt renders with all variables |
| 31 | Full pipeline: mock model → parse → extract_v2 → classify_v2 → category |

### Backward Compatibility Tests (`tests/test_v1_frozen_fixtures.py`)

| # | Test |
|---|------|
| 32 | V1 prompt bytes match frozen fixture for baseline condition |
| 33 | V1 parse output matches frozen fixture for a frozen response |
| 34 | V1 category output matches frozen fixture for frozen classifier dims |
| 35 | V1 condition registry unchanged |

### Schema Drift Tests

| # | Test |
|---|------|
| 36 | baseline_v2 template schema fields == V2_BASELINE_REQUIRED |
| 37 | leg_v2 template schema fields == V2_LEG_REQUIRED |
| 38 | lean_v2 template schema fields == V2_LEAN_REQUIRED |

### Edge Case Tests

| # | Test |
|---|------|
| 39 | Malformed v2 JSON recovers same as v1 (parser fairness) |
| 40 | Classifier v2 returns unknown failure type → "UNKNOWN" |
| 41 | Commitments normalize to empty after dedup → commitments_valid=False |
| 42 | Correct mechanism + violated commitments + code passes → lucky_fix |
| 43 | Wrong mechanism + code passes → lucky_fix |
| 44 | baseline_v2 success with no extractable commitments → uninterpretable_success |

---

## 19. Logging / Observability Plan

### 19.1 V2 Fields in ev Dict (additive-only)

```python
ev["schema_variant"] = "baseline_v2" | "leg_v2" | "lean_v2"
ev["v2_artifact"] = {  # full V2ReasoningArtifact as dict
    "raw_root_cause": ...,
    "raw_code_commitments": [...],
    "normalized_code_commitments": [...],
    "commitments_source": ...,
    "commitment_extractability_status": ...,
    "canonical_family_mapped": True | False,
    ...
}
ev["mechanism_correct"] = True | False | None
ev["commitments_valid"] = True | False | None
ev["alignment_positive"] = True | False | None
ev["commitments_extracted"] = "CORRECT" | "PARTIAL" | "WRONG" | None
ev["commitments_satisfied"] = "CORRECT" | "PARTIAL" | "WRONG" | None
ev["classify_v2_raw"] = "..." # full raw classifier output
ev["classify_v2_parse_error"] = None | "..."
```

### 19.2 Event Schema (events.jsonl)

New fields are additive. Old events don't have them. New events do. Analysis scripts check `event.get("schema_variant")` to determine v1 vs v2.

### 19.3 What Must NOT Happen

- `reasoning_correct` for v2 events must NOT be populated from v1 logic (it uses `reasoning_correct_compat` from v2 derivation)
- `category` for v2 events must NOT be computed by v1 `compute_category` (it uses `compute_v2_category`)
- v2 events must NOT flow through `evaluate_output` (they use `evaluate_case_v2` in `execution_v2.py`)

---

## 20. Phased Rollout Plan with Hard Abort Gates

### Phase 1: New Modules + Unit Tests

**Deliverables:**
- `reasoning_v2.py` with all functions and dataclasses
- `execution_v2.py` with 3 run functions + `evaluate_case_v2`
- `tests/test_reasoning_v2.py` (26 tests)
- `tests/test_v1_frozen_fixtures.py` (4 tests)

**Validation:** All tests pass. No existing tests broken.

**Abort gate:** ANY test failure → do not proceed.

**Rollback:** Delete the two new modules. Zero impact.

### Phase 2: Register Conditions + Preflight

**Deliverables:**
- Edit `constants.py` (3 entries)
- Edit `prompt_manifest.yaml` (3 entries)
- Edit `runner.py:_run_one_inner()` (1 branch)
- V2 preflight suite (10 checks)
- Schema drift tests (3 tests)

**Validation:**
- All existing tests pass
- V1 frozen fixture tests pass
- V2 preflight passes
- Schema drift tests pass

**Abort gates:**
- ANY v1 frozen fixture mismatch → halt, investigate
- ANY preflight check failure → halt, fix
- ANY existing test failure → halt, revert

**Rollback:** Remove entries from constants.py + manifest. Remove routing branch. Three files, three reversions.

### Phase 3: Smoke Test (3 cases × 3 v2 conditions × 1 model)

**Deliverables:**
- `configs/v2_smoke.yaml`
- Run 9 evals

**Abort gates (hard thresholds):**
- classifier_v2 parse failure > 33% (3/9) → halt
- `schema_variant` missing from ANY event → halt
- `commitments_source` missing from ANY v2 event → halt
- ANY v1 condition behavior changed (run canary) → halt
- baseline_v2 `reasoning_present < 50%` → halt
- All `commitments_extracted == WRONG` for leg_v2 → halt (classifier not working)

**Rollback:** Don't use v2 conditions.

### Phase 4: Cost Gate (10 cases × 3 conditions × 1 model)

**Abort gates:**
- classifier_v2 parse failure > 20% → halt
- baseline_v2 pass rate differs from baseline v1 by > 25pp → investigate
- `mechanism_correct` rate < 10% across all conditions → classifier calibration issue
- `canonical_family_mapped = False` for ANY exercised case with a mapped family → mapping bug
- v1 canary produces different results than Phase 2 → regression

### Phase 5: Full Ablation

**Abort gates:**
- classifier_v2 parse failure > 15% for any model → halt
- v1 conditions in same run produce different results than standalone v1 runs → contamination
- `uninterpretable_success` > 50% for baseline_v2 → prompt too weak
- `commitments_extracted == WRONG` > 80% for leg_v2 → prompt or classifier broken

---

## 21. Open Questions Classified

### Resolved Design Decisions

1. **Spontaneous commitments in baseline_v2:** If model provides `code_commitments` without being asked, `commitments_source = "spontaneous"`. They are used by the classifier.
2. **"SAFE" in lean_v2:** Accepted as valid `risk_check`. `normalize_risk_check("SAFE") = "SAFE"`.
3. **Bug-family mapping:** Defined in section 8. `get_canonical_family()` in `reasoning_v2.py`.
4. **Separate log directory:** No. Same log structure, differentiated by `schema_variant`. Simpler for analysis.
5. **Dashboard treatment:** Dashboard scripts must filter by `schema_variant`. v2 metrics appear only when filtered. This is Phase 5 work, not blocking for rollout.

### Blocked Pending User Decision

6. **Should unmapped families be excluded from v2 experiments?** Current decision: include them but log `canonical_family_mapped = False`. If the user wants to exclude them, filter in the experiment config's `cases.filters.family` list. Awaiting confirmation.

### Intentionally Deferred

7. **Redis dashboard v2 metrics:** Not blocking. The terminal dashboard is sufficient for debugging. Redis metrics for v2 are deferred until Phase 5.
8. **paper_analysis.py v2 support:** Not blocking for experiment execution. Deferred until results need to be reported.
9. **Merge with templates.py system:** The templates system is more robust but the assembly engine is active. Migration is a separate project. V2 uses the assembly engine (active system) to avoid introducing a second migration simultaneously.

---

## 22. Risks / Edge Cases / Failure Modes

### Top Risks

1. **Classifier v2 format instability:** The 5-line format with 5 fields on line 1 may not be consistently produced by all evaluator models. gpt-5-mini and gpt-5.4-mini may add extra lines or fields. Mitigation: strict parser + preflight + Phase 3 smoke test.

2. **Commitment extraction noise for baseline_v2:** The classifier must extract commitments from unstructured text. If extraction quality is low, most baseline_v2 cases become `uninterpretable_success`, making the comparison uninformative. Mitigation: Phase 4 abort gate (`uninterpretable_success > 50%`).

3. **Semantic drift between v1 and v2 categories:** Researchers may compare v1 LEG rates with v2 LEG rates without accounting for the different `reasoning_correct` derivations. Mitigation: `schema_variant` is ALWAYS present, and analysis scripts MUST segregate.

4. **17/28 unmapped canonical families:** For these cases, `commitments_satisfied` depends entirely on the classifier's judgment without a reference pattern. This may produce noisier results. Mitigation: `canonical_family_mapped` field enables stratified analysis.

### Edge Cases

5. **Model returns code_commitments as a string instead of list:** `extract_v2_reasoning` wraps in a list. Logged as `commitment_extractability_status = "malformed"`.

6. **Model returns 4+ commitments when asked for 1-3:** All are normalized and passed to classifier. Extra commitments are not truncated — the classifier evaluates what it receives.

7. **Empty `files` dict (all UNCHANGED):** Code extraction produces empty string. `exec_evaluate` scores as fail. This is correct (model didn't fix anything).

8. **Classifier v2 produces ---DEBUG--- section:** Stripped by parser (same as v1).
