# LEG Formulas, Reasoning Classifier, and Metric Derivation

## 1. The Three LEG Formulas

There are three distinct computations in the codebase that measure "LEG" (Latent Execution Gap). They use different inputs, apply different gates, and measure fundamentally different phenomena. The naming similarity is misleading.

### 1.1 LEG_v2 — the strict 4-gate definition

**File:** `evaluation/metrics_v2.py:110-111`
**Used in:** v2 production pipeline (all current experiments)

```
LEG_v2 = (
    code_correct == False
    AND mechanism_correct == True        (classifier dim: mechanism_identified == CORRECT)
    AND commitments_valid == True         (classifier dim: commitments_extracted in {CORRECT, PARTIAL})
    AND alignment_positive == False       (classifier dim: reasoning_code_alignment != CORRECT)
)
```

**What it measures:** The model correctly identified the bug mechanism AND produced valid commitments for fixing it, BUT the code does not implement the stated reasoning. The reasoning is right, the plan is right, the translation to code failed.

**Key property:** Requires `alignment_positive == False`. This means the classifier judged that the code does NOT match the stated fix strategy. This is the strictest form — it says "the model knew what to do and said what it would do, but the code does something different."

### 1.2 leg (legacy compatibility) — the 2-gate definition

**File:** `evaluation/metrics_v2.py:124-125`
**Used in:** backward-compatible reporting, `load_logs.py` analysis

```
leg = (
    reasoning_correct_compat == True     (= mechanism_correct AND commitments_valid AND alignment_positive)
    AND code_correct == False
)
```

**What it measures:** The model's reasoning was judged correct across all three dimensions (mechanism, commitments, AND alignment), but the code still fails tests.

**Key property:** Requires `alignment_positive == True` (through the `reasoning_correct_compat` rollup). This means the classifier judged that the code DOES match the stated reasoning — but the code fails anyway. The reasoning and the code agree, but they're both wrong about what would actually fix the bug.

### 1.3 leg_candidate — the 1-gate definition

**File:** `evaluation/score_execution.py:49`

```
leg_candidate = (
    mechanism_correct == True
    AND execution_pass == False
)
```

**What it measures:** The model identified the right bug mechanism but the code fails. Ignores commitments and alignment entirely. The loosest definition.

### 1.4 How they differ — the critical distinction

LEG_v2 and leg (compat) are **mutually exclusive by construction**:

| Dimension | LEG_v2 requires | leg (compat) requires |
|---|---|---|
| mechanism_correct | True | True |
| commitments_valid | True | True |
| alignment_positive | **False** | **True** |
| code_correct | False | False |

They literally cannot co-occur for the same trial.

- **LEG_v2** = "knew the right fix, but code doesn't implement it" (translation failure)
- **leg (compat)** = "reasoning and code agree, but both are wrong" (reasoning-code aligned failure)
- **leg_candidate** = "identified the right mechanism, code fails" (any mechanism-correct failure)

### 1.5 What the analysis scripts use

`analysis/load_logs.py:234` computes:
```python
leg_true = (reasoning_correct == 1) & (pass == 0)
```

This uses the `reasoning_correct` field from the event log, which is set to `reasoning_correct_compat` by `evaluator_v2.py:311`. So `leg_true` in the analysis scripts corresponds to **leg (compat)** — the 2-gate definition where reasoning and code agree but fail.

---

## 2. What the V2 Reasoning Classifier Is Prompted With

### 2.1 Prompt template

**File:** `prompts/components/classify_reasoning_v2.j2` (316 lines)

The classifier receives a Jinja2-rendered prompt containing:

**Inputs provided:**
- `root_cause` — the generator model's stated root cause (from its JSON output)
- `fix_strategy` — the generator model's stated fix strategy
- `risk_check` — optional, only for LEG conditions
- `task` — the task description from the case definition
- `code` — the generator model's produced code (reconstructed)
- `failure_types` — comma-separated list of valid failure type labels

**In grounded mode (default):**
- `ground_truth_failure_mode` — the case's actual bug type (e.g., "ALIASING")
- `ground_truth_trap` — description of the trap/bug location
- `ground_truth_invariant` — the invariant that must hold

**Inputs NOT provided:**
- Execution results (pass/fail)
- Test output or error messages
- Whether the code ran at all

### 2.2 What the classifier is told to evaluate

The prompt explicitly states:

> You are evaluating **Reasoning → Code Consistency**.
> "Does the code satisfy the obligations implied by the reasoning?"
> NOT: "Is the reasoning correct?"
> NOT: "Does the code work?"

The classifier is instructed to:
1. **Extract the mechanism** from the reasoning text (what the model claims is wrong)
2. **Extract commitments** — specific, checkable obligations implied by the reasoning (e.g., "create_config must return a copy")
3. **Match commitments against canonical patterns** — the prompt contains 30 hardcoded canonical commitment patterns across 10 bug families
4. **Check commitment satisfaction** — does the code actually implement each commitment?
5. **Score 4 dimensions** — each CORRECT, PARTIAL, or WRONG

### 2.3 Canonical commitment patterns in the prompt

The classifier prompt hardcodes canonical patterns for 10 bug families:

| Bug Family | Canonical Commitments |
|---|---|
| ALIASING | returned objects must not share mutable references; functions must return new instances; mutations must not affect source |
| PARTIAL_STATE_UPDATE | all dependent fields must be updated; derived fields must be recomputed; no stale state |
| STALE_CACHE | cache must be invalidated after writes; reads must not return stale values |
| MUTABLE_DEFAULT | default mutable arguments must not be shared across calls; new state per invocation |
| SIDE_EFFECT_ORDER | side effects at correct granularity; updates align with iteration order |
| USE_BEFORE_SET | variables initialized before all reads; all control paths define required variables |
| RETRY_DUPLICATION | retry must not duplicate successful operations; loop must terminate after success |
| PARTIAL_ROLLBACK | failed operations must revert prior state; rollback must restore invariants |
| TEMPORAL_DRIFT | computations must use correct stage of data; transformations must not overwrite needed data |
| MISSING_BRANCH | all valid input cases handled explicitly; dispatch covers all roles/types |

**20 bug families in the benchmark have NO canonical patterns** (e.g., RACE_CONDITION, INVARIANT_VIOLATION, EARLY_RETURN, etc.). For these, the classifier must infer commitments from the model's reasoning alone.

---

## 3. What the Classifier Responds With

### 3.1 Expected output format

```
CORRECT;PARTIAL;WRONG;CORRECT;PARTIAL_STATE_UPDATE
HIGH
Counterfactual: If the function returns a copy instead of the original reference, mutations will not affect global state.
Evidence: - create_config calls dict(DEFAULTS) - returned object is a new dict - mutations to the returned object do not propagate
Judgment: The code implements the stated fix by returning a copy via dict(). This matches the developer's root cause identification of shared reference aliasing.
```

### 3.2 The 4 dimensions

| # | Dimension | What it measures | Scoring |
|---|---|---|---|
| 1 | `mechanism_identified` | Did the reasoning name the correct bug mechanism with a concrete code anchor? | CORRECT = right mechanism + code reference. PARTIAL = vague or generic. WRONG = wrong mechanism. |
| 2 | `commitments_extracted` | Are there valid, checkable commitments implied by the reasoning? | CORRECT = matches canonical pattern. PARTIAL = partially matches. WRONG = no valid commitments. |
| 3 | `commitments_satisfied` | Does the code implement the commitments? | CORRECT = all implemented. PARTIAL = some implemented. WRONG = none or contradicted. |
| 4 | `reasoning_code_alignment` | Does the code match the fix strategy? Correct location modified? No contradiction? | CORRECT = code matches reasoning. PARTIAL = partially matches. WRONG = code contradicts reasoning. |

Plus:
- **failure_type** — one of the valid failure type labels
- **confidence** — HIGH / MEDIUM / LOW
- **counterfactual** — one-sentence "if X then Y" statement
- **evidence** — bullet-point code references
- **judgment** — two-sentence summary

### 3.3 How the output is parsed

**File:** `evaluation/evaluator_v2.py:123-231`

1. Strip everything after `---DEBUG---`
2. Split into non-empty lines
3. Line 1: split on `;`, expect exactly 5 fields → 4 dimensions + failure_type
4. Validate each dimension ∈ {CORRECT, PARTIAL, WRONG}
5. Line 2: confidence ∈ {HIGH, MEDIUM, LOW}
6. Lines 3+: detect section prefixes (`Counterfactual:`, `Evidence:`, `Judgment:`) and accumulate multiline content
7. If any parsing step fails → `parse_error` set, all dimensions = None

**Result:** `ClassifierResultV2` dataclass with all 4 dimension scores, failure_type, confidence, counterfactual, evidence, judgment, and parse_error.

---

## 4. How Parsed Output Becomes Metrics

### 4.1 Signal derivation

**File:** `evaluation/metrics_v2.py:31-85`

The 4 raw classifier dimensions are converted to 3 boolean signals:

```python
mechanism_correct    = (mechanism_identified == "CORRECT")
commitments_valid    = (commitments_extracted in {"CORRECT", "PARTIAL"})
alignment_positive   = (reasoning_code_alignment == "CORRECT")
```

Note: `commitments_satisfied` (dimension 3) produces a supporting signal but is NOT used in the primary LEG/category computation:
```python
commitments_satisfied_positive = (commitments_satisfied in {"CORRECT", "PARTIAL"})
```

A backward-compatible rollup is also computed:
```python
reasoning_correct_compat = mechanism_correct AND commitments_valid AND alignment_positive
```

### 4.2 Category assignment

**File:** `evaluation/metrics_v2.py:88-116`

The 3 boolean signals + `code_correct` (from execution) produce 8 possible categories:

| Category | code_correct | mechanism_correct | commitments_valid | alignment_positive |
|---|---|---|---|---|
| interpretable_success | True | True | True | True |
| uninterpretable_success | True | * | False (no commitments) | * |
| lucky_fix_v2 | True | False | * | * |
| alignment_failure_pass | True | True | True | False |
| **LEG_v2** | **False** | **True** | **True** | **False** |
| full_failure_v2 | False | False | * | * |
| full_failure_v2 | False | True | False | * |
| classifier_failure_v2 | (any dim is None) | | | |

### 4.3 What gets logged

**File:** `evaluation/evaluator_v2.py:238-318`

The final event dict contains:
- `mechanism_correct`, `commitments_valid`, `alignment_positive` — the 3 boolean signals
- `mechanism_identified_dim`, `commitments_extracted_dim`, etc. — raw CORRECT/PARTIAL/WRONG scores
- `v2_category` — the 8-way category (e.g., "LEG_v2")
- `legacy_compat_category` — 4-way mapping for backward compatibility
- `reasoning_correct` — set to `reasoning_correct_compat` (the AND rollup)
- `classify_v2_raw` — the raw classifier response text
- All classifier metadata (counterfactual, evidence, judgment, confidence)

### 4.4 What the analysis scripts consume

`analysis/load_logs.py` reads from `merged_events.jsonl` and extracts:
- `pass` from `payload.pass` (execution truth)
- `reasoning_correct` from `reasoning.reasoning_correct` (the compat rollup)
- Derives `leg_true = (reasoning_correct == 1) & (pass == 0)` — this is the **leg (compat)** formula

This means all the analysis results in `analysis_results.md` use the 2-gate leg definition, not LEG_v2.

---

## 5. The Measurement Gap

The system has a structural blind spot: the classifier evaluates **reasoning→code consistency**, not **reasoning correctness against ground truth**.

When the classifier scores `mechanism_identified = CORRECT`, it means the model stated a specific, code-grounded mechanism. It does NOT mean the mechanism is the actual bug. The classifier prompt says:

> You are NOT evaluating whether the code is correct.

In grounded mode, ground truth is provided "for calibration only." The classifier is free to ignore it. When a bug family has no canonical commitment patterns (20 of 30 families), the classifier has no reference to check against and must rely on internal consistency of the model's reasoning.

This means `reasoning_correct = True` can fire when:
- The model identifies the wrong bug but does so specifically and consistently
- The code faithfully implements the wrong fix
- The classifier scores high on all dimensions because reasoning and code agree

The `leg_true` metric in the analysis scripts inherits this limitation. A case scored as LEG may actually be "consistently wrong" rather than "right reasoning, wrong code."
