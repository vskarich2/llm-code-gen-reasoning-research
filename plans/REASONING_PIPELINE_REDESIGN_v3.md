# Reasoning Pipeline Redesign v3 — Implementation Plan

**Date:** 2026-03-28
**Status:** PLAN ONLY — awaiting approval
**Supersedes:** v1, v2

---

## CHANGES FROM V2

All 10 remaining issues addressed. This is the final pre-implementation revision.

---

## FIX 1: Semantic Grounding (not just syntactic)

v2 required function/variable names. v3 requires causal explanation.

**Prompt addition (all generation conditions):**

```
GROUNDING RULES:
- "root_cause" MUST name the specific function and variable AND explain the causal relationship
  (e.g., "create_config() returns DEFAULTS directly, creating a shared reference instead of a copy").
- "failure_mechanism" MUST describe a cause → effect chain with concrete data flow or state transitions.
  It MUST contain at least one causal statement using language like "because", "which causes", "leads to", "so that", "as a result".
  Example: "Because create_config() returns the same dict object, any mutation by caller A propagates to caller B's config, because both hold references to the same object."
- "broken_invariant" MUST be a falsifiable statement about expected program behavior.
  Example: "Each call to create_config() must return an independent dict that does not share state."
- "fix_strategy" MUST reference the specific code change AND explain why it breaks the failure chain.
  Example: "Changed return DEFAULTS to return dict(DEFAULTS), which creates a new dict object on each call, so mutations to one config cannot propagate to others."
- Generic statements without causal explanation will be treated as missing reasoning.
```

**Parse-time semantic validation (updated):**

```python
CAUSAL_MARKERS = {"because", "causes", "leads to", "so that", "as a result",
                  "which means", "therefore", "consequently", "propagates",
                  "since", "due to", "results in"}

def validate_failure_mechanism(text):
    """Check for causal language, not just identifier presence."""
    text_lower = text.lower()
    has_causal = any(marker in text_lower for marker in CAUSAL_MARKERS)
    has_scenario = any(w in text_lower for w in ("if", "when", "calling", "after", "returns"))
    if not has_causal:
        return "no_causal_explanation"
    if not has_scenario:
        return "no_concrete_scenario"
    return None  # valid
```

---

## FIX 2: Hard Validation Policy

v2 annotated but allowed everything through. v3 enforces metric separation.

**Policy decision: Option A + B hybrid.**

Hard rule: if `reasoning_quality == "missing"` (any required field is empty or below minimum length), the case is:
- Excluded from reasoning metrics (LEG rate, mechanism_identification_rate)
- Included in pass/fail metrics (code correctness is independent of reasoning quality)
- Logged with `reasoning_excluded: true` in events.jsonl

For `reasoning_quality == "degraded"`:
- Included in all metrics BUT separately tracked
- Analysis scripts report: "N cases excluded for missing reasoning, M cases with degraded reasoning"
- Aggregate metrics always reported both with and without degraded cases

```python
def should_classify_reasoning(reasoning_validation):
    """Determine if reasoning is worth classifying."""
    if reasoning_validation["reasoning_quality"] == "missing":
        return False  # skip classifier, set reasoning_correct = None
    return True  # classify even degraded — but log the quality level
```

**Events.jsonl fields:**
```json
{
  "reasoning_quality": "valid",
  "reasoning_excluded": false,
  "reasoning_field_scores": {"root_cause": 1, "failure_mechanism": 1, "broken_invariant": 1, "fix_strategy": 1}
}
```

---

## FIX 3: Bidirectional Reasoning-Code Consistency

v2 had a trivial check. v3 adds structural bidirectional checks.

```python
def check_reasoning_code_consistency(reasoning_obj, parsed, ev):
    """Bidirectional consistency between reasoning claims and code behavior."""
    issues = []
    code = parsed.get("code", "")

    # Direction 1: reasoning → code
    # If reasoning names specific functions to change, check they appear in the diff
    fix_strategy = reasoning_obj.get("fix_strategy", "")
    # Extract function names from fix_strategy
    import re
    mentioned_funcs = set(re.findall(r'[a-z_][a-z0-9_]*\(', fix_strategy.lower()))

    # Direction 2: code → reasoning
    # If code modifies functions, reasoning should mention them
    # (This requires comparing original vs modified code — available from reconstruction)
    changed_files = parsed.get("_reconstruction", None)
    if changed_files and hasattr(changed_files, "changed_files"):
        for fname in changed_files.changed_files:
            fname_base = fname.split("/")[-1].replace(".py", "")
            if fname_base not in fix_strategy.lower() and fname not in fix_strategy:
                issues.append(f"code_changes_{fname}_not_mentioned_in_reasoning")

    # Direction 3: reasoning claims fix → execution result
    if reasoning_obj.get("fix_strategy") and not ev.get("pass"):
        issues.append("fix_claimed_but_tests_fail")

    # Direction 4: execution passes but reasoning is empty/missing
    if ev.get("pass") and not reasoning_obj.get("root_cause", "").strip():
        issues.append("tests_pass_but_no_reasoning")

    return {
        "consistent": len(issues) == 0,
        "issues": issues,
        "directions_checked": 4,
    }
```

---

## FIX 4: Classifier Calibration via Grounded Mode

v2 mentioned grounded mode but didn't specify it. v3 makes it a concrete, operational mode.

**Grounded mode classifier prompt addition:**

```
# Ground Truth (provided for calibration — NOT available in blind mode)

## Known Bug Type
{{ ground_truth_failure_mode }}

## Known Bug Location
{{ ground_truth_trap }}

## Known Invariant
{{ ground_truth_invariant }}

When evaluating, compare the developer's reasoning against this ground truth.
- mechanism_identified: does the developer's root_cause match the known bug type and location?
- invariant_identified: does the developer's broken_invariant match the known invariant?
```

**Config:**
```yaml
evaluation:
  classifier_mode: "blind"     # "blind" or "grounded"
```

**Calibration protocol:**
1. Run the same cases in both blind and grounded mode
2. Compare classifier verdicts
3. Where they disagree: grounded mode is correct (by definition — it has ground truth)
4. Measure: blind-mode accuracy = agreement rate with grounded mode
5. This gives a calibration number for the classifier itself

**Ground truth source:** `case["failure_mode"]` and `case["trap"]` from `cases_v2.json`. For `ground_truth_invariant`, add a new field to case metadata (initially populated for the cases that have SCM data, null for others).

---

## FIX 5: Invariant Alignment — Replace Token Overlap

v2 used token overlap. v3 replaces it with classifier-based alignment.

**Remove `invariant_alignment_score` (token overlap).**

**Replace with:** The grounded-mode classifier already compares `broken_invariant` against ground truth. The `invariant_identified` dimension IS the invariant alignment metric when run in grounded mode.

For blind mode: no invariant alignment score is computed (because we have no ground truth to compare against). This is honest — we don't pretend to measure alignment when we can't.

**New metric:** `grounded_invariant_match` — only populated in grounded mode:
```json
{
  "grounded_invariant_match": "YES",  // from grounded classifier
  "grounded_mechanism_match": "YES",  // from grounded classifier
}
```

---

## FIX 6: Explicit Regime Classification + Validation

The 4 regimes must be explicitly tested:

| Regime | reasoning_correct | code_correct | Category |
|--------|------------------|--------------|----------|
| True success | true | true | `true_success` |
| LEG | true | false | `leg` |
| Lucky fix | false | true | `lucky_fix` |
| True failure | false | false | `true_failure` |

**Test suite:**

```python
class TestRegimeClassification:
    """Verify all 4 regimes are correctly detected from classifier + execution."""

    def test_true_success_regime(self):
        """Correct reasoning + correct code → true_success."""
        dims = {"mechanism_identified": "YES", "invariant_identified": "YES",
                "fix_alignment": "YES", "reasoning_code_alignment": "YES"}
        rc = compute_reasoning_correct(dims, mode="strict")
        assert rc == True
        cat = compute_category(code_correct=True, reasoning_correct=rc)
        assert cat == "true_success"

    def test_leg_regime(self):
        """Correct reasoning + incorrect code → leg."""
        dims = {"mechanism_identified": "YES", "invariant_identified": "YES",
                "fix_alignment": "YES", "reasoning_code_alignment": "NO"}
        rc = compute_reasoning_correct(dims, mode="strict")
        assert rc == True  # reasoning itself is correct even if code doesn't match
        cat = compute_category(code_correct=False, reasoning_correct=rc)
        assert cat == "leg"

    def test_lucky_fix_regime(self):
        """Incorrect reasoning + correct code → lucky_fix."""
        dims = {"mechanism_identified": "NO", "invariant_identified": "NO",
                "fix_alignment": "NO", "reasoning_code_alignment": "PARTIAL"}
        rc = compute_reasoning_correct(dims, mode="strict")
        assert rc == False
        cat = compute_category(code_correct=True, reasoning_correct=rc)
        assert cat == "lucky_fix"

    def test_true_failure_regime(self):
        """Incorrect reasoning + incorrect code → true_failure."""
        dims = {"mechanism_identified": "NO", "invariant_identified": "NO",
                "fix_alignment": "NO", "reasoning_code_alignment": "NO"}
        rc = compute_reasoning_correct(dims, mode="strict")
        assert rc == False
        cat = compute_category(code_correct=False, reasoning_correct=rc)
        assert cat == "true_failure"

    def test_partial_reasoning_regimes(self):
        """PARTIAL dimensions produce correct regime assignment."""
        # Mechanism PARTIAL + invariant YES → reasoning_correct depends on mode
        dims = {"mechanism_identified": "PARTIAL", "invariant_identified": "YES",
                "fix_alignment": "YES", "reasoning_code_alignment": "YES"}
        strict = compute_reasoning_correct(dims, mode="strict")
        lenient = compute_reasoning_correct(dims, mode="lenient")
        assert strict == False  # strict requires mechanism == YES
        assert lenient == True   # lenient allows PARTIAL
```

---

## FIX 7: Adversarial Case — Correct Invariant, Wrong Mechanism

Added to adversarial test suite:

```python
def test_correct_invariant_wrong_mechanism(self):
    """Model identifies correct invariant but wrong mechanism.
    This is the hardest adversarial case — the reasoning SOUNDS correct
    but the causal chain is wrong."""
    reasoning_obj = {
        "root_cause": "create_config() has a concurrency issue",  # WRONG — it's aliasing
        "failure_mechanism": "Multiple threads calling create_config() simultaneously cause a race condition",  # WRONG mechanism
        "broken_invariant": "Each call must return an independent config",  # CORRECT invariant
        "fix_strategy": "Added a lock around the dict creation",  # WRONG fix
    }
    # Classifier should return: NO (mechanism wrong); YES (invariant correct)
    # reasoning_correct should be False — wrong mechanism despite correct invariant
```

```python
def test_correct_mechanism_wrong_invariant(self):
    """Model identifies correct mechanism but states wrong invariant."""
    reasoning_obj = {
        "root_cause": "create_config() returns DEFAULTS directly (shared reference)",  # CORRECT
        "failure_mechanism": "Mutations propagate because both callers hold the same dict",  # CORRECT
        "broken_invariant": "Functions must be pure and have no side effects",  # WRONG — too broad
        "fix_strategy": "Return dict(DEFAULTS) to create a copy",  # CORRECT
    }
    # mechanism_identified: YES, invariant_identified: PARTIAL (related but imprecise)
```

---

## FIX 8: Runtime Schema Version Enforcement

v2 had analysis-time enforcement only. v3 enforces at runtime.

```python
# In execution.py, at run start:
def validate_reasoning_schema_version(config, existing_events_path):
    """Refuse to write to a run directory with mismatched schema version."""
    if not existing_events_path.exists():
        return  # new run, no conflict

    # Read first event
    first_line = open(existing_events_path).readline().strip()
    if not first_line:
        return

    import json
    first_event = json.loads(first_line)
    existing_version = first_event.get("reasoning_schema_version", 1)
    current_version = config.evaluation.reasoning_schema_version

    if existing_version != current_version:
        raise RuntimeError(
            f"SCHEMA VERSION MISMATCH: existing events use reasoning_schema_version={existing_version}, "
            f"but current config uses version={current_version}. "
            f"Cannot mix versions in the same run directory. Use a new run_dir."
        )
```

Called at the start of `run_ablation_mode()`, before any evaluations.

---

## FIX 9: Hard Enforcement of Reasoning Presence

v2 allowed missing fields through. v3 makes the policy explicit per condition.

**Conditions that REQUIRE reasoning (classifier runs):**
- baseline, diagnostic, guardrail, guardrail_strict, all reasoning conditions, SCM conditions, repair_loop

**Conditions where reasoning is OPTIONAL (classifier may skip):**
- contract_gated (multi-step, reasoning in contract not in final code response)
- leg_reduction (has its own reasoning schema — required there)

**For required conditions:** If ALL 4 reasoning fields are empty after parsing:
- `reasoning_quality = "missing"`
- Classifier is SKIPPED (`reasoning_correct = None`)
- Case is EXCLUDED from reasoning metrics
- Case is INCLUDED in code correctness metrics
- `reasoning_excluded = true` in events.jsonl

This is a hard behavioral change. Models that produce no reasoning get no reasoning score. They don't get a free pass.

---

## FIX 10: Mandatory Classifier Explanation

v2 made explanation optional. v3 makes it required.

**Updated classifier output format:**

```
Return EXACTLY two lines:

Line 1: <mechanism>;<invariant>;<fix_align>;<code_align>;<failure_type>
Line 2: <one-sentence explanation of your judgment>

Example:
YES;YES;YES;YES;HIDDEN_DEPENDENCY
Reasoning correctly identifies shared reference aliasing in create_config and fix breaks the sharing via dict copy.

Return ONLY these two lines.
```

**Parser update:**
```python
def parse_classify_output(raw):
    lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
    # Line 1: dimensions
    dims_line = lines[0] if lines else ""
    # Line 2: explanation
    explanation = lines[1] if len(lines) > 1 else ""

    parts = dims_line.split(";")
    # ... parse dimensions ...

    result["explanation"] = explanation
    return result
```

Logged in `audit.classifier_explanation` in run.jsonl. This is mandatory — if the classifier doesn't provide an explanation, `classifier_explanation = ""` is logged (not null), and a warning is emitted.

---

## IMPLEMENTATION PHASES

Same as v2: R1 (templates) → R2 (parser) → R3 (classifier) → R4 (logging) → R5 (tests)

Plus:
- R0: Add `ground_truth_invariant` field to cases_v2.json for cases with SCM data
- R6: Adversarial test suite
- R7: Regime classification tests

---

*End of v3 plan. Awaiting approval.*
