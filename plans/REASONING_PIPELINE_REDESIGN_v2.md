# Reasoning Pipeline Redesign v2 — Implementation Plan

**Date:** 2026-03-28
**Status:** PLAN ONLY — awaiting approval
**Supersedes:** REASONING_PIPELINE_REDESIGN.md (v1)

---

## CHANGES FROM V1

All 10 critical issues addressed. Numbered to match the critique.

---

## FIX 1: Grounding Constraints in Generation Prompt

The generation prompt must force the model to reference actual code, not make abstract claims.

**Added to output instruction (both V1 and V2):**

```
GROUNDING RULES:
- "root_cause" MUST name the specific function and variable where the bug lives.
- "failure_mechanism" MUST describe a concrete scenario with specific inputs/outputs or state transitions.
  Example: "If create_config() is called twice, the second caller sees mutations from the first because both hold references to the same DEFAULTS dict."
- "broken_invariant" MUST be a specific, testable statement about expected behavior.
  Example: "Each call to create_config() must return an independent dict."
- "fix_strategy" MUST reference the actual code change you made.
  Example: "Changed line 4 to return dict(DEFAULTS) instead of DEFAULTS, creating a shallow copy."
- Do NOT write generic statements like "the function does not behave correctly" or "fixed the bug."
- Do NOT restate the task description as reasoning.
```

**Added to LEG prompt (same grounding rules, plus):**

```
- "self_check" MUST reference specific lines or functions in your code, not abstract claims.
  Example: "In my fixed create_config(), line 4 now returns dict(DEFAULTS). If DEFAULTS is later mutated, this copy is unaffected because dict() creates a new object."
```

---

## FIX 2: Semantic Validation at Parse Time

The parser validates reasoning fields after extraction. Invalid reasoning is flagged, not silently accepted.

**Validation rules:**

| Field | Minimum Length | Must Contain | Reject If |
|-------|--------------|--------------|-----------|
| `root_cause` | 20 chars | at least one identifier (function/variable name matching `[a-z_][a-z0-9_]*\(` or `[a-z_][a-z0-9_]*`) | Generic filler: "the bug is in the code", "there is an issue" |
| `failure_mechanism` | 30 chars | conditional language ("if", "when", "because", "causes", "returns") suggesting a concrete scenario | Task restatement (>80% overlap with task text) |
| `broken_invariant` | 10 chars | assertion-like structure ("must", "should", "never", "always", "each", "every") | Empty or single word |
| `fix_strategy` | 15 chars | reference to code change ("changed", "replaced", "added", "removed", "return", "copy") | Generic: "fixed the bug", "corrected the issue" |

**Validation outcome:**
- All fields present and valid → `reasoning_quality: "valid"`
- Some fields weak → `reasoning_quality: "degraded"` (logged, not blocked)
- Fields missing or empty → `reasoning_quality: "missing"` (classifier receives what exists)

`reasoning_quality` is logged in events.jsonl and run.jsonl. Analysis can filter by quality level.

**Important:** Validation does NOT block execution. It annotates. The classifier still runs on whatever the model produced — but we know whether the input was well-formed.

---

## FIX 3: Post-Execution Reasoning-Code Consistency

After execution tests run, the system checks whether the reasoning is consistent with what actually happened.

**New field in evaluation result: `reasoning_execution_consistent`**

Computed as:
```python
def check_reasoning_execution_consistency(reasoning_obj, ev):
    """Check if reasoning claims are consistent with execution outcomes."""
    issues = []

    # If model claims a fix but code fails
    if reasoning_obj.get("fix_strategy") and not ev.get("pass"):
        issues.append("fix_claimed_but_tests_fail")

    # If model claims an invariant but execution shows no code ran
    if reasoning_obj.get("broken_invariant") and not ev.get("execution", {}).get("ran"):
        issues.append("invariant_claimed_but_no_execution")

    return {
        "consistent": len(issues) == 0,
        "issues": issues,
    }
```

This is a lightweight structural check, not a semantic one. The semantic check is the classifier's job. This catches gross inconsistencies (claiming a fix when tests fail).

Logged in events.jsonl as `reasoning_execution_consistent: true/false`.

---

## FIX 4: Classifier Decision Criteria + Few-Shot Examples

**Explicit decision criteria per dimension:**

```
# Decision Criteria (added to classifier prompt)

## mechanism_identified
- YES: Reasoning names the specific function/variable where the bug lives AND explains the concrete runtime behavior that causes failure. Must match the actual bug.
- PARTIAL: Reasoning identifies the general area (correct file/module) but is vague about the specific mechanism, OR identifies a related but not primary mechanism.
- NO: Reasoning is wrong, identifies a different bug, or only restates the task.

## invariant_identified
- YES: States a specific, testable property that the bug violates. The property must be about program behavior, not about code style.
- PARTIAL: States a general correctness property but not the specific one violated by this bug.
- NO: No invariant stated, or states something irrelevant.

## fix_alignment
- YES: The stated fix strategy directly addresses the identified mechanism. If mechanism is "shared reference," fix must address reference sharing.
- PARTIAL: Fix is in the right area but does not fully address the mechanism (e.g., identifies aliasing but fix only adds a comment).
- NO: Fix does not address the identified mechanism, or fix strategy contradicts the reasoning.

## reasoning_code_alignment
- YES: The generated code implements exactly what the reasoning describes. If reasoning says "return a copy," code returns a copy.
- PARTIAL: Code partially implements the reasoning, or implements it plus unrelated changes.
- NO: Code contradicts the reasoning, or code is unchanged despite reasoning claiming a fix.
```

**Few-shot examples (added to classifier prompt):**

```
# Examples

Example 1 (all YES):
Root cause: "create_config() on line 4 returns DEFAULTS directly instead of a copy"
Mechanism: "If caller A gets config and sets config['debug']=True, caller B's config also has debug=True because both reference the same dict"
Invariant: "Each create_config() call must return an independent dict"
Fix: "Changed return DEFAULTS to return dict(DEFAULTS)"
Code: shows dict(DEFAULTS) on the return line
→ YES;YES;YES;YES;HIDDEN_DEPENDENCY

Example 2 (mechanism wrong):
Root cause: "The function has a typo in the variable name"
Mechanism: "The typo causes a NameError"
Invariant: "Variables must be spelled correctly"
Fix: "Fixed the typo"
Code: actually fixes an aliasing bug, not a typo
→ NO;NO;NO;PARTIAL;UNKNOWN

Example 3 (reasoning correct, code wrong):
Root cause: "create_config() returns a reference to DEFAULTS"
Mechanism: "Mutations to the returned config propagate to DEFAULTS"
Invariant: "Configs must be independent"
Fix: "Return a deep copy using copy.deepcopy()"
Code: still returns DEFAULTS (no change made)
→ YES;YES;YES;NO;HIDDEN_DEPENDENCY
```

**PARTIAL usage policy:**
- PARTIAL is allowed when reasoning shows partial understanding
- PARTIAL counts as a "soft yes" for `mechanism_identified` and `invariant_identified`
- PARTIAL counts as "no" for `fix_alignment` and `reasoning_code_alignment` (these should be binary: either the fix matches or it doesn't)
- This is documented in the derivation rule (Fix 5)

---

## FIX 5: Transparent, Configurable `reasoning_correct` Derivation

**v1 had an arbitrary rule. v2 makes it explicit and configurable.**

**Default derivation (strict mode):**
```python
def compute_reasoning_correct(dims, mode="strict"):
    m = dims["mechanism_identified"]
    i = dims["invariant_identified"]
    f = dims["fix_alignment"]
    c = dims["reasoning_code_alignment"]

    if mode == "strict":
        # Reasoning is correct only if mechanism AND invariant are right
        # AND the fix logically follows from the reasoning
        return m == "YES" and i in ("YES", "PARTIAL") and f in ("YES", "PARTIAL")

    elif mode == "lenient":
        # Reasoning is correct if mechanism is at least partially right
        return m in ("YES", "PARTIAL") and i in ("YES", "PARTIAL")

    elif mode == "raw":
        # Don't derive — return None, let analysis decide
        return None
```

**Config:**
```yaml
evaluation:
  reasoning_correct_mode: "strict"  # "strict", "lenient", or "raw"
```

**In "raw" mode**, `reasoning_correct` is null in events.jsonl. The 4 raw dimensions are always logged regardless of mode. Analysis scripts can compute any derivation they want.

**Justification for strict default:** The purpose of the T3 benchmark is to measure whether models understand bugs, not whether they vaguely gesture at the right area. "YES" on mechanism + invariant (with partial tolerance on invariant) is the minimum for "understood the bug." Requiring fix_alignment ensures the reasoning is coherent, not just a correct diagnosis followed by an unrelated fix.

---

## FIX 6: Adversarial Reasoning Test Cases

**Added to test suite:**

```python
class TestAdversarialReasoning:
    """Test that the system handles deceptive reasoning correctly."""

    def test_incorrect_code_correct_reasoning(self):
        """Model reasons correctly but produces wrong code (LEG case)."""
        # reasoning_obj has correct root_cause/mechanism
        # code does NOT implement the fix
        # classifier should return: YES;YES;YES;NO

    def test_correct_code_incorrect_reasoning(self):
        """Model produces correct code but reasoning is wrong (lucky fix)."""
        # code is correct
        # reasoning describes a different bug entirely
        # classifier should return: NO;NO;NO;YES (or PARTIAL)

    def test_generic_template_reasoning(self):
        """Model writes plausible but generic reasoning."""
        # root_cause: "The function has a bug that causes incorrect behavior"
        # failure_mechanism: "When the function is called, it does not work correctly"
        # Validation should flag as reasoning_quality: "degraded"

    def test_task_restatement_as_reasoning(self):
        """Model restates the task description as reasoning."""
        # root_cause text has >80% overlap with task text
        # Validation should flag

    def test_reasoning_invariant_matches_case(self):
        """Verify reasoning invariant aligns with case ground truth."""
        # Compare reasoning_obj.broken_invariant with case metadata
        # Not a pass/fail — log the alignment score
```

---

## FIX 7: LEG Trace Preservation

v1 removed too much structure. v2 keeps minimal trajectory:

**LEG schema (revised):**

```json
{
  "root_cause": "...",
  "failure_mechanism": "...",
  "broken_invariant": "...",
  "fix_strategy": "...",
  "self_check": "...",
  "revision_note": "...",
  "attempt_number": 0,
  "previous_attempt_summary": null,
  "files": { ... }
}
```

**Fields:**
- `attempt_number`: 0 for initial, 1+ for revisions (integer)
- `previous_attempt_summary`: null for first attempt. For revisions: one-sentence summary of what the previous attempt got wrong.

This preserves trajectory analysis (how reasoning evolves across revisions) without the giant arrays. The retry harness can accumulate `previous_attempt_summary` from prior iterations.

For single-call LEG (no retry): `attempt_number: 0`, `previous_attempt_summary: null`.

---

## FIX 8: Schema Versioning

**Explicit version field in every event:**

```json
{
  "reasoning_schema_version": 2,
  ...
}
```

**Version semantics:**
- Version 1 (old runs): `reasoning` is a flat string. `reasoning_obj` does not exist. Classifier received flat string.
- Version 2 (new runs): `reasoning_obj` is a structured dict. Classifier receives 4 fields. 4-dimension output.

**Migration policy:**
- Old runs (version 1) are NEVER silently mixed with new runs (version 2) in analysis
- Analysis scripts check `reasoning_schema_version` and refuse to compare across versions
- No silent fallback. If version is missing, assume version 1.

**Config:**
```yaml
evaluation:
  reasoning_schema_version: 2
```

---

## FIX 9: Parse-Time Validation (detailed)

Added to parser output:

```python
reasoning_validation = {
    "reasoning_quality": "valid" | "degraded" | "missing",
    "field_issues": {
        "root_cause": null | "too_short" | "no_code_reference" | "generic_filler",
        "failure_mechanism": null | "too_short" | "no_scenario" | "task_restatement",
        "broken_invariant": null | "too_short" | "not_testable",
        "fix_strategy": null | "too_short" | "no_code_reference" | "generic_filler",
    },
    "overall_score": 4,  # count of fields with no issues (0-4)
}
```

This is computed in the parser, stored in `parsed["reasoning_validation"]`, and logged in run.jsonl. It does NOT block execution or classification.

---

## FIX 10: Reasoning ↔ Execution ↔ Invariant Consistency

**Three-way consistency check (post-evaluation):**

```python
def compute_reasoning_invariant_alignment(reasoning_obj, case):
    """Compare reasoning's stated invariant with case ground truth."""
    stated = reasoning_obj.get("broken_invariant", "")
    ground_truth_mode = case.get("failure_mode", "")
    ground_truth_trap = case.get("trap", "")

    # Keyword overlap between stated invariant and case metadata
    stated_tokens = set(stated.lower().split())
    gt_tokens = set(f"{ground_truth_mode} {ground_truth_trap}".lower().split())

    overlap = len(stated_tokens & gt_tokens)
    score = overlap / max(len(gt_tokens), 1)

    return {
        "invariant_alignment_score": round(score, 3),
        "stated_invariant": stated,
        "ground_truth_mode": ground_truth_mode,
    }
```

This is a SOFT metric — logged for analysis, not used for pass/fail. It measures whether the model's stated invariant is in the same semantic neighborhood as the case's known failure mode.

Logged in events.jsonl as `invariant_alignment_score: 0.0-1.0`.

---

## SECONDARY ISSUES ADDRESSED

**Overhead:** The new reasoning schema adds ~200-400 chars to the response (4 short fields). This is less than the old LEG schema removed (~2000+ chars of arrays). Net token savings for LEG.

**Failure logging:** The classifier prompt now includes `explanation` as an optional field. If the classifier provides one, it's logged in `audit.classifier_explanation`.

**Confidence:** Not added as a required field (adds complexity without proven value). The 4 dimensions serve as a more informative signal than a single confidence float.

---

## IMPLEMENTATION PHASES (unchanged from v1)

R1: Templates → R2: Parser → R3: Classifier → R4: Logging → R5: Tests

Each phase has byte-level verification where applicable.

---

*End of v2 plan. Awaiting approval.*
