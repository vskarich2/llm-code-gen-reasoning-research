# AST Verifier Evolution Plan v3 — Scientific Instrument Tightening

**Date:** 2026-04-03
**Supersedes:** v2 sections where specified
**Scope:** 11 revised/new sections addressing overclaiming, arbitrary thresholds, claim feasibility, unknown policy, failure decomposition, signal comparison, and MVP justification

---

## 1. Exactly What AST Can and Cannot Justify

### AST can justify (measured or directly detectable)

1. **Canonical structural pattern is present.** If the code contains `.copy()` on the right object in the right function, that is a fact about the AST. (Measured: 91.2% ast_correct on 20,031 events.)

2. **A known valid alternative structure is present.** If the code uses `dict(DEFAULTS)` instead of `.copy()`, and that's in the equivalence class, the verifier correctly identifies it.

3. **The anti-pattern (bug signature) is still present.** If the code still assigns bare `DEFAULTS` without wrapping, the verifier correctly flags it.

4. **The target locus was or was not modified.** Whether the model changed `config.py::create_config` vs some other file/function is directly checkable.

5. **A structure-to-execution gap exists.** When AST=correct but exec=fail, something broke between structure and runtime. This is a factual observation about the two signals disagreeing, not a claim about why.

### AST cannot justify (inferred, hypothesized, or fundamentally unobservable)

1. **Genuine causal understanding.** A model that pattern-matches `.copy()` from training data produces the same AST as one that reasons through the aliasing mechanism. AST cannot distinguish these. (Measured: 458 events (2.3%) where oracle=wrong but AST=correct — the blind spot.)

2. **Absence of pattern-matching.** There is no structural test for "the model understood why this works." This is a philosophical limit, not an engineering gap.

3. **Semantic correctness within a structurally correct patch.** `try: ... except: sender.balance += wrong_amount; raise` has the right shape but the wrong value. AST sees the shape, not the value. (Measured: ~10% of AST-correct exec failures are this kind.)

4. **Correctness of unrecognized novel repairs.** If the model produces a structurally novel fix that no equivalence class matches, AST returns `unknown`, not `correct`. The verifier CANNOT determine correctness of novel approaches — only execution can.

5. **That a passing test proves the fix is correct.** Execution passes can be false positives (weak test). AST cannot diagnose test quality.

### What the paper should say

**Defensible:** "AST-based structural verification provides a deterministic implementation-level signal that agrees with the oracle reasoning evaluator 93% of the time and identifies 2,531 events where correct structure fails at execution — a signal no other instrument provides."

**Not defensible:** "AST measures reasoning correctness." "AST proves the model understood the bug."

---

## 2. Threshold Justification and Status

| Threshold | Value | Status | Justification |
|-----------|-------|--------|---------------|
| Oracle-AST agreement target | >90% | **Provisional engineering guardrail** | Currently measured at 93.4%. Below 90% would indicate the verifier is checking the wrong structural property. Not a scientific threshold — just an alert level. |
| AST false positive target | <15% of exec-failing events | **Provisional** | Currently measured at ~10%. 15% is a round-number ceiling, not derived from theory. If it exceeds 15%, the relaxed checkers are probably too loose. |
| AST false negative target (LUCKY_FIX) | <5% | **Provisional** | Currently 2.3%. Ceiling above which systematic checker gaps are likely. |
| Claim checkability coverage | not set | — | Cannot set a meaningful target until claim verification is validated. |
| Deep chain checker accuracy | not set | — | No empirical data yet. |

**Policy:** All thresholds are labeled as provisional engineering guardrails in the plan and the paper. None are presented as scientific criteria. They may be revised after Phase 2 validation.

---

## 3. Claim Verification Feasibility: Current Commitments vs Required Commitment Schema

### Empirical assessment of current commitments

From 10,252 sampled commitments in the targeted 50-trial dataset:

| Property | Count | % |
|----------|-------|---|
| Has "must"/"should" split | 10,100 | 99% |
| Has extractable scope (function name) | 10,100 | 99% |
| Has checkable action keywords | 7,126 | 70% |
| Vague (no recognizable action keywords) | 3,126 | 30% |
| Too short (<15 chars) | 0 | 0% |

**Assessment:** The current commitment format is structurally well-formed (99% parseable into scope + action). But 30% of actions are too vague for AST mapping ("must be correct", "must handle properly").

### Option A: Text-heuristic claim parsing

Use keyword matching on the action half of `"<scope> must <action>"`.

**Pros:** Cheap, no prompt changes, works on existing data.
**Cons:** 30% of claims are uncheckable. Keyword matching is brittle — "must not mutate" requires proving absence, which AST does poorly. False alignment rate is unknown and could be high.

**Verdict:** Feasible for the 70% with recognizable keywords. The 30% vague claims must be explicitly classified as `claim_checkability: "uncheckable"` and excluded from claim-conditioned metrics.

### Option B: Constrained claim schema

Require the model to produce typed commitments:
```json
{"scope": "create_config", "property": "independence", "target_object": "DEFAULTS", "constraint": "must_not_alias"}
```

**Pros:** Clean, unambiguous, directly maps to AST properties.
**Cons:** Requires prompt changes → new experiment runs → cannot apply retroactively to existing 20K+ events. Significant engineering and experimental cost.

### Recommendation

**Use Option A for existing data, design Option B for future experiments.**

For v3 of the plan:
- Implement text-heuristic claim parsing (Option A) on existing commitments
- Report `claim_checkability` and exclude uncheckable claims from metrics
- DO NOT report aggregate `claim_alignment` numbers without filtering to `claim_checkability >= "checkable"`
- Design the typed commitment schema (Option B) as a prompt format change for future runs
- Do NOT block the current plan on Option B — it's a separate workstream

**Rollout impact:** Claim-aware verification is **demoted from Phase 2 to Phase 3** because it's lower confidence than originally estimated. Phase 2 should focus on locus verification and property-based specs, which don't depend on claim quality.

---

## 4. Property Spec Design Rules

### Rule 1: Invariant property independent of syntax
The `invariant_property` field must describe WHAT must be true about program behavior, not HOW it is implemented.

**Good:** `"type": "no_aliasing", "description": "Return value must be independent of module-level mutable state"`
**Bad:** `"type": "uses_copy", "description": "Must call .copy()"`

### Rule 2: Known patterns are detectors, not truth
`known_correct_patterns` is a list of heuristic detectors. Matching one is evidence FOR correctness. Not matching any is NOT evidence AGAINST correctness (unless anti-pattern is present).

### Rule 3: Failure to match ≠ incorrectness
If no known pattern matches AND no anti-pattern is present, the result is `"unknown"`, not `"incorrect"`. The verifier does not have enough information to classify.

### Rule 4: Anti-patterns require contradiction justification
Each anti-pattern must document WHY it contradicts the invariant property, not just that it differs from the canonical fix.

**Good:** `"bare_name_assign to DEFAULTS" → "Creates an alias to module-level state, violating independence property"`
**Bad:** `"does not use .copy()" → undefined`

### Rule 5: Detectability classification per spec
Each spec must declare its detection mode:

| Mode | Meaning | Example |
|------|---------|---------|
| `directly_detectable` | Positive pattern match proves correctness | .copy() present → independent dict |
| `negatively_detectable` | Anti-pattern absence is the primary signal | No bare DEFAULTS assignment → likely independent |
| `partially_detectable` | Some aspects checkable, some not | try/except present (checkable) but compensation semantics unknown |
| `not_structurally_decidable` | Invariant requires runtime information | Lock ordering, atomicity |

### Three cases rewritten under these rules

**Case: alias_config_a**
```json
{
  "invariant_property": {
    "type": "value_independence",
    "description": "Return value must be a fresh dict, not an alias to DEFAULTS",
    "detectability": "directly_detectable"
  },
  "known_correct_patterns": [
    {"description": ".copy() on DEFAULTS", "type": "method_call", "method": "copy", "object": "DEFAULTS"},
    {"description": "dict(DEFAULTS)", "type": "builtin_call", "func": "dict", "arg": "DEFAULTS"},
    {"description": "{**DEFAULTS}", "type": "dict_unpacking", "source": "DEFAULTS"}
  ],
  "known_anti_patterns": [
    {"description": "Bare DEFAULTS assignment — creates alias, violates independence",
     "type": "bare_name_assign", "name": "DEFAULTS",
     "contradiction": "Direct name reference creates an alias, not an independent copy"}
  ],
  "novel_repair_policy": "flag_as_unknown"
}
```

**Case: hidden_dep_multihop**
```json
{
  "invariant_property": {
    "type": "cache_write_semantics",
    "description": "save_user must use always-overwrite cache semantics so subsequent reads return the latest value",
    "detectability": "negatively_detectable"
  },
  "known_correct_patterns": [
    {"description": "Calls sync_user_to_cache (uses cache_put)", "type": "call_name", "name": "sync_user_to_cache"},
    {"description": "Calls cache_put directly", "type": "call_name", "name": "cache_put"},
    {"description": "Any cache-write function except conditional", "type": "call_name_contains", "contains": "cache", "not_in": ["refresh_user_snapshot", "cache_put_if_absent"]}
  ],
  "known_anti_patterns": [
    {"description": "Uses refresh_user_snapshot (conditional write) — violates always-overwrite requirement",
     "type": "call_name", "name": "refresh_user_snapshot",
     "contradiction": "cache_put_if_absent does not overwrite existing entries, causing stale reads after rename"}
  ],
  "novel_repair_policy": "flag_as_unknown"
}
```

**Case: use_before_set_b (difficult case)**
```json
{
  "invariant_property": {
    "type": "all_path_coverage",
    "description": "Function must set _status on all control flow paths, including empty/error input",
    "detectability": "partially_detectable"
  },
  "known_correct_patterns": [
    {"description": "Else branch sets _status", "type": "else_branch_assigns", "target": "_status"},
    {"description": "_status set before conditional", "type": "assign_before_conditional", "target": "_status"},
    {"description": "Multiple returns covering all paths", "type": "multi_return_coverage"}
  ],
  "known_anti_patterns": [
    {"description": "_status only set inside truthy branch — empty input leaves stale value",
     "type": "conditional_only_assign", "target": "_status",
     "contradiction": "On empty input, the conditional body is skipped, so _status retains the value from a prior call"}
  ],
  "novel_repair_policy": "flag_as_unknown",
  "notes": "This case has high LUCKY_FIX (2.9%) due to diverse structural alternatives for path coverage. detectability is 'partially' because some valid restructurings are not recognizable without control flow analysis."
}
```

---

## 5. Unknown-State Policy

### When does a case become `unknown`?

`ast_truth_alignment = "unknown"` when ALL of:
1. No known correct pattern matched (relaxed check failed)
2. No anti-pattern found (anti check also failed)
3. The target function/file was modified (model made changes)

If anti-pattern IS found → `incorrect` (strong negative evidence).
If target was NOT modified → `incorrect` (model didn't even attempt the fix).
If no known pattern AND no anti-pattern AND changes made → `unknown` (verifier lacks information).

### Is `unknown` a property of the patch, the checker, or the family?

It is a property of the **interaction between the patch and the checker**. A `unknown` result means the checker does not recognize the approach. It does NOT mean the approach is wrong. It could also mean the checker needs expansion.

### Reporting category

`unknown` is a **third category alongside assessable and unassessable**:

| Label | Meaning | Include in AST accuracy? | Include in family summaries? |
|-------|---------|------------------------|---------------------------|
| `correct` | Known valid pattern present | YES (as positive) | YES |
| `incorrect` | Anti-pattern present OR target unmodified | YES (as negative) | YES |
| `unknown` | No recognized pattern, no anti-pattern, target modified | NO — separate bucket | YES (as separate count) |
| `not_measurable` | Reconstruction failed or case uncheckable | NO — excluded | YES (as coverage note) |

### `unknown` × execution interactions

| AST | Exec | Category | Action |
|-----|------|----------|--------|
| unknown | pass | `ast_alternative_candidate` | Candidate for adding to known patterns. Manual review. |
| unknown | fail | `ast_indeterminate_failure` | Cannot determine if failure is structural or semantic. |

### Impact on metrics

- `ast_correct_rate` is computed over `correct + incorrect` only. `unknown` is excluded from the denominator.
- LUCKY_FIX is computed as `incorrect AND exec_pass`. `unknown AND exec_pass` is NOT a lucky fix — it's an `alternative_candidate`.
- Family summaries report: N_correct, N_incorrect, N_unknown, N_unassessable.
- Paper claims about AST accuracy must state the `unknown` rate. If `unknown` exceeds 10% for a family, AST is not reliable for that family.

---

## 6. Canonical Cross-Signal Taxonomy

### Category names (formal)

| Oracle | AST | Exec | Category | Abbreviation |
|--------|-----|------|----------|-------------|
| correct | correct | pass | **Full convergence** | FC |
| correct | correct | fail | **Execution fidelity failure** | EFF |
| correct | incorrect | pass | **Structural translation bypass** | STB |
| correct | incorrect | fail | **Structural translation failure** | STF |
| wrong | correct | pass | **Oracle-structure disagreement (pass)** | OSD-P |
| wrong | correct | fail | **Oracle-structure disagreement (fail)** | OSD-F |
| wrong | incorrect | pass | **Convergent false positive** | CFP |
| wrong | incorrect | fail | **Full failure** | FF |

When AST = `unknown`, add suffix `-U`:
| Oracle | AST | Exec | Category |
|--------|-----|------|----------|
| correct | unknown | pass | **Structural indeterminacy (pass)** | SI-P |
| correct | unknown | fail | **Structural indeterminacy (fail)** | SI-F |
| wrong | unknown | pass/fail | **Indeterminate failure** | IF |

### Interpretation limits per cell

**FC (76.3%):** All signals agree. Safe to interpret as genuine success.

**EFF (11.2%):** Safe to say structure is correct and execution fails. NOT safe to say the model "understood" the bug — it may have pattern-matched. The structural-to-execution gap is a factual observation about signal disagreement.

**STB (1.5%):** Oracle says reasoning correct, AST doesn't recognize the structure, but execution passes. Most likely: valid alternative repair not in equivalence class. Small risk: oracle is wrong. NOT safe to call this a "lucky fix" — the model may have found a correct novel approach.

**STF (1.4%):** Oracle says reasoning correct but code doesn't implement it. This IS the translation failure — the model can articulate the fix but can't code it. Safe interpretation IF we trust the oracle.

**OSD-P (2.3%):** Oracle says reasoning wrong, AST says structure correct, execution passes. This is the AST blind spot — correct structure from wrong reasoning (likely pattern matching). Safe to identify as an AST limitation.

**OSD-F (1.4%):** Structure correct but reasoning wrong and execution fails. Ambiguous — could be pattern-matched structure with semantic errors, or oracle error. NOT safe to draw strong conclusions.

**FF (5.1%):** Everything wrong. Safe interpretation.

---

## 7. Root Cause Decomposition of AST-Correct but Execution-Failing Events

### This is the core scientific leverage of AST

From 20,031 oracle-labeled events: 2,531 have AST=correct AND exec=fail. These are the events where structure is right but execution breaks. Decomposing WHY they fail is the paper's most defensible claim.

### Taxonomy of execution-failure causes (from prior analysis of 1,046 events)

| Subtype | Count | % | Classification method |
|---------|-------|---|---------------------|
| Other invariant violation | 543 | 51.9% | Rule-based on failure_reasons text |
| Wrong value or literal | 201 | 19.2% | "expected X got Y" pattern in reasons |
| Unexpected exception | 125 | 12.0% | "raised" in reasons |
| Wrong variable binding | 90 | 8.6% | NAME_ERROR execution category |
| Import dependency | 85 | 8.1% | IMPORT_FAILURE execution category |
| Runtime crash | 2 | 0.2% | INVARIANT_CRASH category |

### Problem: "other invariant violation" is too coarse (51.9%)

This is the biggest bucket and it's essentially "test failed for unclassified reason." It needs further decomposition.

### Proposed deeper decomposition

For the 543 "other invariant violation" events:

**Method:** Stratified sample of 200 events. For each, read the failure_reasons text, the generated code, and the test. Classify into:

| Subtype | Definition | Example |
|---------|-----------|---------|
| Wrong constant/string | Correct structure, wrong specific value | `_status = "done"` instead of `"empty"` |
| Incomplete path coverage | Fix covers main path but misses edge case the test checks | Else branch present but doesn't handle None input |
| Wrong argument to correct call | Calls the right function with wrong arguments | `release(wrong_id, qty)` |
| Compensation targets wrong variable | Rollback structure correct but compensates the wrong state | `sender.balance += wrong_var` |
| Helper extraction semantic error | Model extracted logic into helper but helper has a bug | `_perform_transfer()` doesn't properly atomize |
| Test contract mismatch | Code is arguably correct but doesn't match test expectations | Returns dict instead of tuple |

**Assignment method:** Rule-based on failure_reasons text first (keywords: "expected", "got", "raised", "not found", "mismatch"). Manual review for the ~50% that don't match rules.

**Sample size:** 200 events (stratified by case family). Expected to classify ~70% automatically, ~30% manually.

**Output:** Table + figure showing the distribution. This becomes a paper figure: "Among structurally correct execution failures, X% are precision errors (wrong values), Y% are coverage errors (missed paths), Z% are binding errors (wrong variables)."

### Why this matters

This decomposition answers: "Is the execution gap a model capability problem or a test contract problem?"

If most failures are wrong-value/wrong-binding → genuine model precision limitation.
If most are test-contract mismatch → the gap may partly be measurement artifact.

---

## 8. Deep Dependency Chain Checker Inputs and Outputs

### Required metadata from CaseSpec

```python
# From spec_types.py CaseSpec:
required_fields = {
    "nodes.corruption_introduced_at_node": str,   # e.g., "context_normalizer"
    "nodes.required_fix_node": str,                # must equal corruption node
    "nodes.first_symptom_observed_at_node": str,   # downstream symptom
    "canonical.field_names": list[str],             # corrupted field(s)
    "canonical.access_paths": list[str],            # all consumers (including bypass)
    "chain": list[ChainNode],                       # ordered node chain
    "traps": list[TrapSpec],                        # known band-aid patterns
}
```

### Checker inputs

```python
def check_deep_chain(
    files: dict[str, str],          # all reconstructed files
    corruption_site_file: str,      # which file contains the corruption node
    corruption_site_func: str,      # which function to check
    downstream_files: list[str],    # other files in the chain
    trap_specs: list[dict],         # known band-aid patterns
    invariant_property: dict,       # what the corruption-site fix should achieve
) -> ChainVerificationResult
```

### Detection logic

```
1. Parse corruption_site_file
2. Find corruption_site_func
3. Check: does it contain a known_correct_pattern for the invariant_property?
   → corruption_site_fix_present = True/False

4. For each downstream_file:
   Parse and check for modifications (diff from original)
   → downstream_modifications = list of modified functions

5. For each trap in trap_specs:
   Check if any downstream modification matches the trap's structural signature
   → band_aid_detected, band_aid_type

6. Classify:
   if corruption_site_fix_present and no downstream_modifications:
     → "root_fix"
   if corruption_site_fix_present and downstream_modifications:
     → "mixed_repair"
   if not corruption_site_fix_present and downstream_modifications:
     → "band_aid"
   if not corruption_site_fix_present and no downstream_modifications:
     → "no_fix"
```

### What counts as evidence vs proof

| Signal | Evidence or proof? |
|--------|--------------------|
| Corruption-site function modified | Evidence (could be wrong modification) |
| Known correct pattern at corruption site | Strong evidence (same as single-function checking) |
| Anti-pattern absent at corruption site | Evidence (necessary but not sufficient) |
| Downstream-only modifications | Evidence of band-aid (not proof — could be valid refactoring) |
| Trap pattern match in downstream | Strong evidence of specific band-aid type |

### What remains runtime-only

- Whether the corruption-site fix handles ALL inputs (generalization invariant)
- Whether the bypass consumer also gets correct data (cross_path invariant — execution only for novel approaches)
- Whether the full chain is consistent end-to-end (chain_integrity invariant)

### Phase sequencing: why Phase 4, not earlier

DDC integration is Phase 4 because:
1. DDC requires the mature analysis/ layer (symbol tracking, call resolution) from Phase 3
2. DDC cases need new test infrastructure (adapting CaseSpec self_validate into tests_v2/ format)
3. DDC checkers need the `unknown` state and property-based spec design from Phase 2
4. DDC is 8 NEW cases, not improvements to existing 58. The ROI for the paper is lower than improving the existing 20,031-event dataset.

If DDC cases become central to the paper's narrative, move DDC to Phase 3 and defer the 5 not_yet_implemented checker upgrades.

---

## 9. MVP Strategy Comparison and Recommendation

### Strategy A: Architecture cleanup first

| Step | Work | Days | Deliverable |
|------|------|------|------------|
| A1 | Consolidate scripts/→core/ | 2 | INV-02 fixed |
| A2 | CheckabilityLevel taxonomy | 1 | Honest uncheckability reporting |
| A3 | `unknown` state | 1 | Honest novel-repair handling |
| A4 | Locus verification | 2 | `ast_location_match` signal |
| **Total** | | **6** | Clean architecture + 2 new signals |

**Scientific value:** Incremental. The existing 3-way decomposition doesn't change. We get honesty improvements (unknown, checkability) and one new signal (locus).

### Strategy B: Scientific leverage first

| Step | Work | Days | Deliverable |
|------|------|------|------------|
| B1 | `unknown` state | 1 | Stop false negatives on novel repairs |
| B2 | Locus verification | 2 | `ast_location_match` signal |
| B3 | Exec-failure decomposition (Section 7) | 3 | Paper figure: structural-correct failure subtypes |
| B4 | Consolidate scripts/→core/ | 2 | INV-02 fixed |
| **Total** | | **8** | Paper-ready failure decomposition + 2 new signals + cleanup |

**Scientific value:** HIGH. The exec-failure decomposition (B3) is the single most publishable analysis the AST layer enables. It directly answers "why do structurally correct patches fail?" — which is the paper's core question.

### Recommendation: Strategy B

The scientific bottleneck is not architecture hygiene — it's the unexplained exec-failure bucket. The 2,531 AST-correct execution failures are the paper's strongest evidence for the execution-fidelity thesis, but without decomposition they're a black box.

B3 (exec-failure decomposition) should be the FIRST thing implemented, not the last. It doesn't require any architecture changes — it's analysis on existing data. The consolidation (B4) is important but doesn't affect scientific claims.

**Revised priority order:**
1. `unknown` state (1 day) — stops false certainty immediately
2. Exec-failure decomposition (3 days) — produces the paper's key figure
3. Locus verification (2 days) — adds location-match signal
4. Consolidation (2 days) — fixes INV-02

---

## 10. Incremental Value of AST Over Simpler Structural Signals

### Empirical comparison (measured on 20,031 events)

| Signal | Oracle agreement | Unique information |
|--------|-----------------|-------------------|
| Execution pass/fail only | 84.4% | None — execution IS one of the axes |
| Old LLM mechanism_correct | 90.5% | LLM-based, noisy, non-deterministic |
| **AST structural check** | **93.4%** | **Deterministic, reproducible, auditable** |
| AST + execution combined | 93.4% (AST) + 84.4% (exec) | **2,531 events where AST=correct, exec=fail — unique** |

### AST's incremental value over execution alone: +9.0pp oracle agreement

This means AST correctly classifies 9% more events as oracle-aligned than execution alone. Those 9% are the execution-fidelity-failure events — structurally correct but runtime-broken.

### AST's incremental value over old LLM classifier: +2.9pp oracle agreement

Small but important: AST is deterministic and reproducible, while the LLM classifier is not. The 2.9pp comes from cases where the LLM classifier overcalls mechanism_correct (99.7% vs oracle's 90.4%).

### Per-family AST unique signal (AST=correct, exec=fail)

| Family | AST unique signal | Interpretation |
|--------|------------------|----------------|
| invariant_partial_fail | 63.6% | Massive — AST detects correct rollback structure where execution fails on semantics |
| hidden_dep_multihop | 47.4% | Large — correct function substitution but import failures |
| missing_branch | 24.9% | Moderate — correct branch addition but wrong permissions |
| use_before_set | 19.2% | Moderate — correct path coverage but wrong values |
| overdetermination | 15.5% | Moderate — correct call removal but other issues |

Families with <5% AST unique signal (alias_config, mutable_default, stale_cache, lazy_init, retry_dup, temporal_drift, wrong_condition) have AST≈execution — the structural check adds almost no information beyond pass/fail. For these families, AST mainly serves as a deterministic confirmation of execution.

### Would simpler probes suffice?

**Candidate simple probes:**
- "Did the model change the target file?" (1 line of code)
- "Does the target function exist in output?" (ast.parse + find_function)
- "Is the code syntactically valid?" (ast.parse only)

These would catch the gross failures (didn't change anything, syntax errors) but would NOT detect:
- Wrong function call name (hidden_dep_multihop)
- Missing break in retry loop (retry_dup)
- Anti-pattern still present (alias_config)
- Wrong argument to correct call (temporal_drift)

**Verdict:** Simple probes would achieve ~80% of AST's oracle agreement but miss the 12 families where AST provides unique signal. Full AST is worth the complexity for the families where the execution gap is >10%.

---

## 11. Empirical vs Expected Reliability

Every reliability claim is now explicitly labeled.

| Family | AST-Oracle agreement | Signal quality | Source |
|--------|---------------------|---------------|--------|
| alias_config | 100% | Directly detectable | **Measured** (1,295 events) |
| mutable_default | 99.9% | Directly detectable | **Measured** (2,152 events) |
| retry_dup | 100% | Directly detectable | **Measured** (634 events) |
| effect_order | 99.9% | Directly detectable | **Measured** (1,261 events) |
| stale_cache | 99.0% | Directly detectable | **Measured** (1,241 events) |
| early_return | 83% (v2 checkers) | Partially detectable | **Measured** (3,468 events) |
| temporal_drift | 95.4% (v2 arg check) | Directly detectable | **Measured** (1,368 events) |
| use_before_set | 97.1% | Partially detectable | **Measured** (1,695 events) |
| partial_rollback | 88.7% | Partially detectable | **Measured** (645 events) |
| hidden_dep_multihop | 97.9% (v2) | Negatively detectable | **Measured** (1,050 events) |
| invariant_partial_fail | 85.7% (v2) | Partially detectable | **Measured** (1,574 events) |
| missing_branch | 87% | Partially/module-level | **Measured** (2,055 events) |
| partial_update | 78-98% | Partially detectable | **Measured** (1,175 events) |
| deep dependency chain | UNKNOWN | Expected: partially detectable | **Not measured** — no empirical data |
| atomicity cases | N/A | Not structurally decidable | **Measured** (classified as uncheckable) |

All "measured" values come from the 20,031-event oracle-labeled dataset. "Expected" is a hypothesis to be validated in Phase 4. "Unknown" means we have no data and cannot estimate.
