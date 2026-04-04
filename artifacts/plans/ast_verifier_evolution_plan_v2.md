# AST Verifier Evolution Plan v2 — Scientific Instrument Revisions

**Date:** 2026-04-03
**Supersedes:** Sections added to ast_verifier_evolution_plan_v1.md
**Scope:** 8 critical gap fixes. Only new/revised sections below.

---

## 1. Validation of AST as a Reasoning Signal

### The question

Can AST structural verification reliably distinguish "model understood the bug" from "model did not understand the bug"?

### The honest answer

**Partially.** AST measures structural repair fidelity — whether the code contains the fix pattern. This correlates with reasoning but is not the same thing. Three failure modes break the correlation:

1. **Correct reasoning, wrong structure:** Model describes the fix correctly in prose but generates code that doesn't implement it. Oracle=correct, AST=incorrect. This is the translation gap — AST correctly identifies it.

2. **Wrong reasoning, correct structure:** Model pattern-matches the fix from training data without understanding why. Oracle=wrong, AST=correct. AST CANNOT detect this — it's a blind spot.

3. **Correct reasoning, correct structure, wrong semantics:** Model understands the bug and produces the right shape but gets a value wrong. Oracle=correct, AST=correct, exec=fail. AST correctly classifies the structure; execution catches the semantic error. Not a failure of AST — it measures what it claims to.

### What AST can reliably measure

| Signal | Reliable? | Why |
|--------|-----------|-----|
| "Model produced the canonical fix structure" | YES | Direct pattern matching |
| "Model produced ANY valid fix structure" | YES (with alternatives) | Relaxed equivalence classes |
| "Model understood the bug mechanism" | NO — can only infer | Structure is necessary but not sufficient for understanding |
| "Model changed the right location" | YES | Locus verification |
| "Model's code matches its stated commitments" | PARTIALLY | Claim verification, limited by claim vagueness |

### Measurement plan

**AST vs Oracle agreement:**
- Already measured: 92.2% on 20,031 events
- Re-measure after each phase to detect drift
- Target: >90% agreement. If it drops below 85%, the verifier is mis-scoped.

**AST false positive rate (AST=correct when structure is actually wrong):**
- Method: Sample 200 events where AST=correct AND exec=fail. Manual inspection.
- Already done: estimated 10% FP rate (from instrument validation audit)
- Target: <15% on the exec-failing subset. Above 15% means checkers are too loose.

**AST false negative rate (AST=incorrect when structure is actually correct):**
- Method: Sample 200 events where AST=incorrect AND exec=pass (LUCKY_FIX bucket)
- Already done: LUCKY_FIX = 2.0% overall
- Target: <5% overall. Each LUCKY_FIX event is either a missing alternative or a genuine false negative.

**AST blind spots (correct structure from wrong reasoning):**
- Method: Sample events where Oracle=wrong AND AST=correct AND exec=pass (LUCKY_REASONING category)
- Currently: 458 events (2.3% of oracle-labeled)
- This is structurally undetectable by AST. Report it honestly. Do not claim AST catches it.

### Per-family reliability

| Family | AST reliable for reasoning? | Why |
|--------|---------------------------|-----|
| Aliasing (alias_config) | HIGH — .copy() is a strong signal of understanding | Pattern is unique to the fix |
| Retry (retry_dup) | HIGH — break in loop is unambiguous | No alternative interpretation |
| Rollback (partial_rollback) | MEDIUM — try/except structure present but compensation may be wrong | 10-15% semantic FP |
| Hidden dep (hidden_dep_multihop) | MEDIUM — correct function name but could be pattern-matched | Training data contamination risk |
| Deep chain | UNKNOWN — untested | Must validate empirically |
| Atomicity (lost_update) | NONE — fundamentally uncheckable | Runtime semantics only |

### What the paper should claim

SAFE: "AST provides a deterministic structural proxy for reasoning correctness that agrees with the oracle evaluator 92% of the time."

UNSAFE: "AST measures reasoning correctness." (It measures structural repair fidelity, which correlates with but is not identical to reasoning.)

---

## 2. Formal Claim Schema

### What a valid claim looks like

Model commitments arrive as strings: `"<scope> must <action>"`.

Formal schema:

```
Claim := {
  raw_text: str,                           # "create_config must return a copy of DEFAULTS"
  scope: str | None,                       # "create_config" (extracted function/variable name)
  action: str | None,                      # "return a copy of DEFAULTS" (extracted predicate)
  scope_resolved: bool,                    # was scope successfully extracted?
  action_resolved: bool,                   # was action successfully mapped to AST property?
  claim_checkability: CheckableLevel,      # checkable | partially_checkable | uncheckable
  claim_confidence: float,                 # 0.0-1.0 — how confidently we can verify this claim
}
```

### Normalization pipeline

```
Raw commitment string
  → split on " must " or " should " or " needs to "
  → left half = scope (function/variable name extraction via regex)
  → right half = action (keyword matching to AST property types)
  → classify checkability
```

### Checkability classification

| Pattern in action | AST property | Checkable? |
|-------------------|-------------|------------|
| "return a copy" / "return independent" | method_call_present (.copy/dict) | YES |
| "not mutate" / "not modify" | absence of mutation pattern | PARTIALLY — hard to prove absence |
| "handle empty input" / "handle edge case" | branch coverage | YES — else branch or init |
| "add rollback" / "compensate" | try/except with compensation | YES |
| "break after success" / "stop retrying" | break in loop | YES |
| "invalidate cache" | call present after write | YES |
| "use correct lock order" | UNCHECKABLE — runtime semantics | NO |
| "ensure atomicity" | UNCHECKABLE — runtime semantics | NO |
| vague: "fix the bug" / "clean up" | no specific AST mapping | UNCHECKABLE — too vague |

### Mapping from claim → AST check

```python
CLAIM_ACTION_MAP = {
    # Keywords in action → AST property to check
    "copy": ("method_call_present", {"methods": ["copy"]}),
    "independent": ("method_call_present", {"methods": ["copy"]}),
    "break": ("break_in_loop", {}),
    "rollback": ("try_except_with_compensation", {}),
    "invalidate": ("call_present_after_write", {"call_names": INVALIDATE_NAMES}),
    "initialize": ("assign_before_conditional", {}),
    "handle empty": ("branch_coverage", {}),
    "handle edge": ("branch_coverage", {}),
}
```

For each claim, attempt to match the action text against this map. If no match: `claim_checkability = "uncheckable"`.

### Ambiguity handling

| Situation | Behavior | Output |
|-----------|----------|--------|
| Vague claim ("fix the issue") | Skip — no AST mapping possible | `claim_checkability: "uncheckable"`, `claim_confidence: 0.0` |
| Incomplete claim ("update config") | Attempt partial match | `claim_checkability: "partially_checkable"`, `claim_confidence: 0.3` |
| Incorrect but plausible claim ("fix middleware") | Check whether patch matches the claim, NOT whether claim is correct | `claim_alignment: "aligned"` if model did what it said, even if that's wrong |
| Multiple claims, some checkable | Check each independently, report per-claim results | `claims_checked: N`, `claims_matched: M` |
| No claims (baseline condition) | Skip claim verification entirely | `claim_alignment: "no_claims"` |

---

## 3. Property-Based Specs (Not Solution Matching)

### The problem with v1

V1's `required_changes` encodes the solution:
```json
{"type": "method_call_present", "params": {"object": "DEFAULTS", "methods": ["copy"]}}
```

This says "check for .copy()" — it's checking for the canonical solution, not the invariant property.

### The fix: property-level specs

Each case gets TWO layers:

**Layer 1 — Invariant property (what must be true):**
```json
{
  "invariant_property": "no_aliasing",
  "description": "Return value must be independent of module-level DEFAULTS",
  "structural_requirement": "value_independence",
  "target_object": "DEFAULTS"
}
```

**Layer 2 — Known detection patterns (how we currently check it):**
```json
{
  "known_patterns": [
    {"type": "method_call", "method": "copy", "object": "DEFAULTS"},
    {"type": "builtin_call", "func": "dict", "arg": "DEFAULTS"},
    {"type": "dict_unpacking", "source": "DEFAULTS"},
    {"type": "comprehension", "over": "DEFAULTS"}
  ],
  "anti_patterns": [
    {"type": "bare_name_assign", "name": "DEFAULTS"}
  ]
}
```

The invariant property is the TRUTH. The known patterns are HEURISTICS that detect it. If a model produces a novel pattern not in the list that satisfies the invariant, the verifier returns `ast_truth_alignment: "uncheckable_novel"` rather than `incorrect`.

### Revised structural_spec schema

```json
"structural_spec": {
  "checkability": "fully_checkable",
  "target": {"file": "config.py", "function": "create_config"},
  "invariant_property": {
    "type": "no_aliasing",
    "description": "Return value must not alias module-level mutable state",
    "target_object": "DEFAULTS"
  },
  "known_correct_patterns": [...],
  "known_anti_patterns": [...],
  "novel_repair_policy": "flag_as_unknown",
  "checker_family": "aliasing"
}
```

`novel_repair_policy` determines behavior when no known pattern matches but no anti-pattern is found either:
- `"flag_as_unknown"` — return `ast_truth_alignment: "unknown"` (honest)
- `"assume_incorrect"` — return `incorrect` (conservative, current behavior)
- `"assume_correct"` — return `correct` (dangerous, never use)

Default: `"flag_as_unknown"`. This prevents the verifier from asserting wrongness when it simply doesn't recognize the approach.

---

## 4. Alternative Valid Repair Framework

### How alternatives are represented

Two mechanisms:

**Mechanism 1: Enumerated alternatives** — known valid patterns listed in `known_correct_patterns`. Currently ~3-5 per case. These are patterns we've seen in actual model outputs and verified as correct.

**Mechanism 2: Negative-space detection** — if no anti-pattern is present AND the model made changes to the target function, the repair MIGHT be valid but novel. The verifier returns `ast_truth_alignment: "unknown"` rather than `incorrect`.

### How to avoid penalizing novel fixes

```python
def classify_truth_alignment(check_passed, anti_found, changes_detected):
    if check_passed and not anti_found:
        return "correct"
    if anti_found:
        return "incorrect"      # bug pattern still present = definitely wrong
    if not check_passed and not anti_found and changes_detected:
        return "unknown"        # changed something, but we don't recognize it
    if not check_passed and not anti_found and not changes_detected:
        return "incorrect"      # didn't change the target at all
```

The key insight: `unknown` is NOT `incorrect`. A model that produces a genuinely novel correct fix gets `unknown`, not `false negative`. The LUCKY_FIX analysis then determines how many `unknown` cases are actually valid alternatives that should be added to `known_correct_patterns`.

### `ast_alternative_valid` determination

```python
ast_alternative_valid = (
    ast_truth_alignment == "unknown"  # novel pattern
    AND exec_pass == True              # but execution passes
)
```

This is computed post-hoc by joining AST and execution results. It identifies cases where the verifier should expand its equivalence classes.

### NOT done: enumerate every possible fix

We explicitly do NOT attempt to enumerate all valid repairs. Instead:
1. Start with canonical + 3-5 known alternatives
2. Run on data
3. Events with `ast_alternative_valid = True` are candidates for expansion
4. Manual review determines which to add
5. Repeat

---

## 5. Deep Dependency Chain Checking — Formalized

### Formal definitions

**Corruption site:** The function where the bug was introduced. In the CaseSpec, this is `nodes.corruption_introduced_at_node`. The validator enforces `corruption_site == required_fix_node`.

**Symptom site:** The first function where the corruption manifests as incorrect behavior. In the CaseSpec, this is `nodes.first_symptom_observed_at_node`. This is downstream of the corruption site in the chain.

**Band-aid:** A fix applied at or downstream of the symptom site that makes the primary test pass but fails at least one of the 5 invariants (generalization, cross_path, chain_integrity, trap_catching, causal_location). The CaseSpec defines these explicitly as `TrapSpec` objects.

**Mixed repair:** A patch that modifies both the corruption site AND a downstream node. The corruption-site fix may be correct, but the downstream changes may be unnecessary or harmful.

### Detection rules

**Rule 1: Corruption-site edit detection**
```
Parse the file containing the corruption-site function.
Check: does the function contain structural changes consistent with
the invariant_property? (Same as single-function checking.)
```

**Rule 2: Downstream-only fix detection**
```
For each file in the chain AFTER the corruption site:
  Parse the file.
  Check: does it contain structural changes?
  If yes AND corruption site is unchanged:
    → downstream_only_fix = True (likely band-aid)
```

**Rule 3: Cross-path correctness**
```
The bypass_consumer reads a field that should be fixed.
Check: does the fix also affect the bypass consumer's input path?
If the fix is at the corruption site: usually yes (field fixed at source).
If the fix is downstream: usually no (bypass consumer still reads corrupt data).
```

**Rule 4: Band-aid pattern matching**
```
For each defined trap in the CaseSpec:
  Check: does the model's patch resemble the trap's structural signature?
  Each trap has a trap_type (endpoint_compensation, validation_masking, etc.)
  Each trap type has a known structural pattern.
```

### Detection output

```python
@dataclass
class ChainVerificationResult:
    corruption_site_modified: bool     # did model change the right function?
    corruption_site_fix_valid: bool    # does the change match the property?
    downstream_modifications: list[str] # which downstream files were changed?
    band_aid_detected: bool            # does the downstream change match a known trap?
    band_aid_type: str | None          # which trap type?
    cross_path_risk: bool              # bypass consumer not covered?
    chain_repair_classification: str   # root_fix | band_aid | mixed | unknown
```

### What cannot be verified structurally

- Whether the corruption-site fix is semantically correct (values, not just pattern)
- Whether the fix handles ALL inputs correctly (generalization — runtime only)
- Whether a novel downstream fix is actually correct (could be a valid alternative repair strategy)
- Chain integrity across more than the immediate nodes (requires execution)

---

## 6. Failure Modes of AST Verification

### Structural false positive

**Definition:** AST says "correct" but the code does not actually satisfy the invariant.

**Cause:** The structural pattern is present but semantically wrong. Example: `try: ... except: sender.balance += wrong_variable; raise` — has the right shape but compensates the wrong thing.

**Measured rate:** ~10% of AST-correct execution failures (from instrument validation audit).

**Mitigation:** Symbol tracking (Phase 3) can verify compensation targets the correct variable. Reduces to ~5% estimated.

### Structural false negative

**Definition:** AST says "incorrect" but the code does satisfy the invariant.

**Cause:** Novel valid repair not in the equivalence classes. Example: model uses `json.loads(json.dumps(DEFAULTS))` for deep copy — correct but not in the pattern list.

**Measured rate:** LUCKY_FIX = 2.0% overall. After `novel_repair_policy: "flag_as_unknown"`, these become `unknown` instead of `incorrect`.

**Mitigation:** Phase 3 `unknown` + exec_pass → `ast_alternative_valid` feedback loop.

### Underconstrained pass

**Definition:** AST says "correct" because the checker is too loose, not because the fix is right.

**Cause:** Relaxed equivalence class accepts too many patterns. Example: any function call with "cache" in the name accepted as cache invalidation, including `cache_stats()`.

**Mitigation:** Anti-patterns as negative gates. If the anti-pattern (bug signature) is still present, `incorrect` regardless of relaxed check.

### Alternative repair miss

**Definition:** Model produces a structurally valid alternative that the verifier doesn't recognize, resulting in `incorrect` (or `unknown` with v2 policy).

**Mitigation:** `novel_repair_policy: "flag_as_unknown"` converts these from false negatives to honest uncertainty. Manual review pipeline promotes confirmed alternatives to `known_correct_patterns`.

### Checkability misclassification

**Definition:** A case is labeled `uncheckable_runtime` when it could actually be partially checked with a better checker.

**Measured:** 5 of 11 NOT_AST_MEASURABLE cases are `not_yet_implemented`, not `fundamentally_uncheckable`.

**Mitigation:** CheckabilityLevel taxonomy separates these explicitly. Phase 3 implements checkers for the 5 `not_yet_implemented` cases.

### Claim verification noise

**Definition:** claim_alignment says "aligned" or "misaligned" but the claim was too vague to check meaningfully.

**Mitigation:** `claim_checkability` and `claim_confidence` fields. Analysis should filter to `claim_confidence >= 0.5` for claim-conditioned metrics.

---

## 7. Joint Signal Analysis Plan

### The 2×2×2 decomposition

Three binary signals: Oracle (O), AST (A), Execution (E).

| O | A | E | Category | N (measured) | % | Insight |
|---|---|---|----------|------|---|---------|
| T | T | T | **Full success** | 15,282 | 76.3% | Everything aligned |
| T | T | F | **Execution gap** | 2,242 | 11.2% | Correct reasoning + structure, runtime failure |
| T | F | T | **Lucky fix** | 300 | 1.5% | Correct reasoning, wrong/unknown structure, passes anyway |
| T | F | F | **Structural failure** | 275 | 1.4% | Correct reasoning but can't translate to code |
| F | T | T | **Lucky reasoning** | 458 | 2.3% | Wrong reasoning but correct structure + execution (AST blind spot) |
| F | T | F | **AST-ok reasoning-wrong** | 289 | 1.4% | Structure correct but reasoning wrong — pattern matching? |
| F | F | T | **Double lucky** | 154 | 0.8% | Everything wrong but passes |
| F | F | F | **Full failure** | 1,031 | 5.1% | Nothing works |

### Key disagreement patterns and what they teach us

**O=T, A=T, E=F (Execution gap, 11.2%):**
The paper's core finding. Correct understanding + correct structure → runtime failure. Proves execution fidelity is a distinct capability.

**O=T, A=F, E=F (Structural failure, 1.4%):**
Model understands the bug but can't translate understanding into code structure. This is the TRANSLATION gap — where claim-aware verification adds most value. If `claim_alignment=aligned` here, the model SAID the right thing AND the oracle agrees, but the code doesn't match. Pure implementation failure.

**F=T, A=T, E=T (Lucky reasoning, 2.3%):**
AST blind spot. Model has wrong reasoning but correct structure and execution. Could be: training data pattern matching, or oracle is wrong about the reasoning. Manual audit needed to determine proportion.

**O=F, A=T, E=F (AST-ok reasoning-wrong, 1.4%):**
Structural fix present but reasoning is wrong. The structure is correct BY ACCIDENT — the model applied a known pattern without understanding why. AST cannot distinguish this from genuine understanding. This is the fundamental limit.

### Paper contribution from joint analysis

The 2×2×2 table enables three claims no single signal can make:

1. **Execution fidelity is a distinct capability** — the O=T,A=T,E=F cell proves it
2. **Structural translation is a distinct capability** — the O=T,A=F cells prove it  
3. **AST has a measurable blind spot** — the O=F,A=T cells quantify it

Without AST, we can only say "reasoning correct but execution fails" (2-way). With AST, we can localize WHERE the failure occurs: reasoning→structure or structure→execution.

### Condition-specific joint analysis

The most publishable finding:

| Condition | O=T,A=T,E=F (execution gap) |
|-----------|----|
| baseline | 52.9% |
| lean | 34.6% |
| retry_bare | 15.2% |
| retry_critique | 10.8% |
| **retry_reasoning_only** | **6.7%** |

Reasoning-only critique closes the execution gap most effectively. The 2×2×2 shows this is because it simultaneously improves O, A, AND E — not just one axis.

---

## 8. Minimal Viable Verifier

### If we only implement 30%: what do we build?

**Build exactly these 3 things:**

**MVV-1: Consolidate scripts/ → core/ (2 days)**
Fixes the INV-02 violation. Zero scientific risk. Pure cleanup.

**MVV-2: Add CheckabilityLevel taxonomy + `unknown` alignment state (1 day)**
Replace the flat NOT_AST_MEASURABLE set with the typed enum. Add `novel_repair_policy: "flag_as_unknown"` so the verifier stops asserting wrongness on unrecognized but potentially valid repairs. This immediately improves honesty.

**MVV-3: Add locus verification (2 days)**
Check: did the model modify the file/function specified in `reference_fix.file` / `reference_fix.function`? This already exists as data in cases_v2.json — just needs a checker. Adds `ast_location_match` to every event.

**Total: 5 days. Still yields publishable insight because:**
- Locus verification enables the "wrong location" failure mode (currently invisible)
- CheckabilityLevel enables honest reporting of what AST can and cannot measure
- `unknown` alignment prevents false confidence on novel repairs
- Consolidation prevents future divergence

### What we skip in the MVV

- Claim-aware verification (needs normalization pipeline — Phase 2)
- Symbol tracking / dataflow (Phase 3 — nice but not critical for core claim)
- Deep dependency chain (Phase 4 — separate benchmark expansion)
- Property-based specs in case metadata (Phase 2 — current hardcoded patterns are working)

### What still yields publishable insight with MVV only

The existing 3-way decomposition (oracle × AST × execution) is already publishable. The MVV adds:
1. Honest `unknown` state instead of false `incorrect` on novel repairs
2. Location-match signal showing whether models fix the right place
3. Typed uncheckability instead of a flat exclusion set

These are precision improvements, not new capabilities. But they make the existing claims more defensible.

### What should absolutely NOT be in the MVV

- Full claim verification (too complex for the marginal value in the first iteration)
- Cross-file call resolution (only needed for a few multi-file cases)
- Generic AST similarity / tree edit distance (wrong abstraction entirely)
- Any gating behavior (violates the independence invariant)
