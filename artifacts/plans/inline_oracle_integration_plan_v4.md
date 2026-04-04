# Inline Oracle Integration Plan v4.1 — Implementation-Ready

**Date:** 2026-04-03
**Supersedes:** inline_oracle_integration_plan_v4.md
**Status:** APPROVED FOR IMPLEMENTATION

---

## Changes from v4

1. **Fix: pointer equality → deep equality** in pre-write validation (Section 15). Uses `==` not `is`.
2. **Fix: classifier runs BEFORE execution** in pipeline ordering (Sections 11, 19). Eliminates execution-leakage risk.
3. **Fix: oracle prompt hash split** into `prompt_template_hash` (static) and `prompt_instance_hash` (dynamic) (Section 8).
4. **Fix: disagreement metric expanded** — per-dimension classifier breakdown, not collapsed boolean (Section 13).
5. **Fix: semantic validation** added to pre-write layer — cross-field consistency checks (Section 15).
6. **Note: best_attempt = first_pass** acknowledged as a modeling choice. Documented limitation for future revision.

## Changes from v3

1. **Canonical source of truth per axis** defined. Trajectory is primary; top-level is derived. Invariant enforced in assembly.
2. **Duplication ambiguity eliminated.** `payload.oracle == trajectory[best_idx].oracle`. Enforced, not assumed.
3. **Best attempt selection rigorously defined** with tie-breaking, all-fail, parse-fail, and crash behavior.
4. **AST input validity contract** with explicit status for every failure mode.
5. **Classifier input contract** fully specified: normalized reasoning + reconstructed code. Blind to execution and oracle.
6. **Oracle prompt versioning** via content hash + version string.
7. **Sampling strategy bias analysis** with safe/unsafe designation per claim type.
8. **Failure cascade handling** with exact fallback values for every axis combination.
9. **Trajectory consistency invariants** with enforcement and violation handling.
10. **Metric definitions** (LEG_oracle, LEG_classifier, LEG_ast, lucky_fix, disagreement_rate, structural_failure_rate).
11. **Incomplete attempt handling** — no silent omission, explicit INCOMPLETE status.
12. **Pre-write validation layer** before WAL emission.
13. **Oracle epistemic status** clarified: measurement instrument, not ground truth.

---

## 1. Canonical Source of Truth Per Axis

### Rule

```
trajectory[k] is the PRIMARY source for all per-attempt data.
Top-level payload fields are DERIVED from trajectory[best_idx].
```

### Per-axis canonical sources

| Axis | Canonical source | Top-level payload field | Derivation rule |
|------|-----------------|------------------------|-----------------|
| Execution | `trajectory[k].execution` | `payload.pass`, `payload.score` | Copied from `trajectory[best_idx].execution` |
| Oracle | `trajectory[k].oracle` | `payload.oracle` | Copied from `trajectory[best_idx].oracle` |
| Classifier | `trajectory[k].classifier` | `payload.classification` | Copied from `trajectory[best_idx].classifier` |
| AST | `trajectory[k].ast` | `payload.ast_eval` | Copied from `trajectory[best_idx].ast` |
| Disagreement | `trajectory[k].reasoning_disagreement` | `payload.reasoning_disagreement` | Copied from `trajectory[best_idx].reasoning_disagreement` |

### What if top-level and trajectory diverge?

They cannot. The assembly function copies from trajectory, never computes independently:

```python
import copy

def _assemble_final_from_trajectory(trajectory, best_idx):
    best = trajectory[best_idx]
    return {
        "oracle": copy.deepcopy(best["oracle"]),
        "classification": copy.deepcopy(best["classifier"]),
        "ast_eval": copy.deepcopy(best["ast"]),
        "reasoning_disagreement": copy.deepcopy(best["reasoning_disagreement"]),
        "pass": best["execution"]["pass"],
        "score": best["execution"]["score"],
    }
```

Top-level fields are deep-copied from the trajectory entry. They are VALUE-equal, not pointer-identical (JSON serialization breaks identity). All validation uses `==` (value equality), never `is` (pointer identity).

### Invariant

```
INV-CANONICAL: For every v3.1 event with trajectory:
  payload.oracle == trajectory[best_idx].oracle              (value equality)
  payload.classification == trajectory[best_idx].classifier  (value equality)
  payload.ast_eval == trajectory[best_idx].ast               (value equality)
  payload.reasoning_disagreement == trajectory[best_idx].reasoning_disagreement
  payload.pass == trajectory[best_idx].execution.pass
```

All comparisons use `==` (deep value equality), never `is` (pointer identity). JSON serialization/deserialization breaks object identity. Enforced in the pre-write validation layer (Section 15).

### Baseline path (no trajectory)

For baseline (single-attempt) events, there is no trajectory array. Top-level fields ARE the primary source. There is exactly one attempt so no ambiguity exists.

---

## 2. Best Attempt Selection

### Definition

```
best_idx = index of the first passing attempt.
If no attempt passes: best_idx = index of the last completed attempt.
```

### Formal specification

```python
def select_best_attempt(trajectory: list[dict]) -> int:
    """Select the best attempt index.
    
    Returns the index of the FIRST passing attempt.
    If no attempt passes, returns the index of the LAST attempt.
    """
    for i, entry in enumerate(trajectory):
        if entry["execution"]["pass"]:
            return i
    return len(trajectory) - 1
```

### Tie-breaking

No tie-breaking is needed. Attempts are ordered (0, 1, 2, ...) and the rule is "first passing." If multiple attempts pass, the first one wins. This matches the existing retry behavior: the loop breaks on first pass (`retry_v2.py` line 538).

### Edge cases

| Scenario | `best_idx` | Rationale |
|----------|-----------|-----------|
| Attempt 0 passes | 0 | First pass wins |
| Attempts 0,1 fail; attempt 2 passes | 2 | First pass |
| All 5 attempts fail | 4 | Last attempt (most information) |
| Parse failure on all attempts | last completed | Last attempt with data |
| Only 1 attempt (timeout after attempt 0) | 0 | Only completed attempt |
| Attempt 0 passes, attempt 1 also passes | 0 | First pass wins |

### What "completed attempt" means

An attempt is completed if its trajectory entry was successfully appended. See Section 14 for handling of incomplete attempts.

### Known limitation: first-pass may not be best reasoning

`best = first_pass` assumes earlier passes are preferable. This is NOT always true: attempt 1 may pass with a lucky fix while attempt 3 passes with correct reasoning. The current rule picks attempt 1, losing signal.

This is acceptable for v4.1 because:
1. It matches existing retry loop behavior (break on first pass)
2. Changing to `argmax(score, reasoning_quality)` requires oracle results to inform selection, creating a circularity
3. All per-attempt data is preserved in trajectory regardless — analysis can re-select

**Future revision:** if analysis reveals significant lucky-fix-at-first-pass rates, revisit with a multi-objective selection rule.

---

## 3. Formal Experimental Unit Definition

```
experimental_unit = (case_id, model, condition, trial, attempt)
```

Every experimental unit MUST contain aligned signals from all four measurement axes:

| Axis | Signal | Scope |
|------|--------|-------|
| Execution (E) | `pass`, `score`, `execution_category` | per-attempt |
| Oracle (O) | `reasoning_truth`, `oracle_correct`, `justification` | per-attempt |
| Classifier (C) | `mechanism_identified`, `commitments_satisfied`, `reasoning_code_alignment` | per-attempt |
| Structure (AST) | `status`, `ast_correct`, `ast_score` | per-attempt |

The join key for any cross-axis analysis is the 5-tuple above. No analysis may mix signals from different attempts within the same retry chain.

---

## 4. Oracle Input Integrity

### The guarantee

```
Oracle uses the RAW model reasoning text, NEVER normalized or transformed text.
```

### Source fields

The oracle reads from the **parsed JSON** directly, before normalization:

```python
fj = parsed_gen.full_json or {}
raw_root_cause = fj.get("root_cause", "")
raw_fix_strategy = fj.get("fix_strategy", "")
```

These are the exact strings the model produced. They have been:
- Extracted from the raw LLM response by the JSON parser
- NOT normalized (no trimming, no scope tagging, no dedup)
- NOT transformed (no commitment splitting)
- NOT reconstructed (no code assembly)

### Pipeline ordering enforcement

```
parse → extract raw fields → oracle(raw fields) → normalize → reconstruct → execute → classify → AST
```

Oracle runs AFTER parsing (raw fields available) but BEFORE normalization. The function signature takes raw strings, not the artifact:

```python
def _run_oracle_evaluation(
    raw_root_cause: str,      # from parsed_gen.full_json["root_cause"]
    raw_fix_strategy: str,    # from parsed_gen.full_json["fix_strategy"]
    case: dict,
    config,
) -> dict:
```

---

## 5. Classifier Input Contract

### What the classifier receives

The classifier receives EXACTLY these inputs (from `build_classifier_v2_vars`, evaluator_v2.py line 60):

| Input | Source | Normalized? |
|-------|--------|------------|
| `root_cause` | `artifact.normalized_root_cause` | YES — normalized |
| `fix_strategy` | `artifact.normalized_fix_strategy` | YES — normalized |
| `risk_check` | `artifact.normalized_risk_check` | YES — normalized |
| `code_commitments` | `artifact.normalized_code_commitments` | YES — normalized |
| `code` | reconstructed code string (from `recon.files`) | N/A — code |
| `task` | `case["task"]` | NO — original |
| `canonical_family` | `artifact.canonical_family` | N/A — metadata |

### What the classifier does NOT receive

| Excluded input | Reason |
|---------------|--------|
| Execution results (`pass`, `score`, `reasons`) | Classifier is blind to execution outcome |
| Oracle output (`reasoning_truth`, `justification`) | Classifier is independent of oracle |
| AST results | Classifier is independent of structural analysis |
| Raw (un-normalized) reasoning text | Classifier uses normalized reasoning for consistency |
| Test output / stderr | Blind mode — no execution signal |

### Classifier operating mode

```yaml
evaluation:
  classifier_mode: "blind"  # classifier never sees execution results
```

The classifier evaluates reasoning-code alignment by comparing the model's stated reasoning against the reconstructed code. It judges whether the reasoning is internally consistent with the code, NOT whether the code is correct.

This is deliberate: the classifier measures a DIFFERENT axis than execution. Execution measures behavioral correctness; classifier measures reasoning-code coherence.

### Difference from oracle

| Property | Oracle | Classifier |
|----------|--------|-----------|
| Input: reasoning | RAW (pre-normalization) | NORMALIZED |
| Input: code | NONE (never sees code) | Reconstructed code |
| Input: ground truth | YES (case oracle spec) | NO |
| Judges | Reasoning vs ground-truth mechanism | Reasoning vs generated code |
| Independence | Independent of execution + classifier | Independent of execution + oracle |

---

## 6. AST Input Validity Contract

### What AST receives

```python
def check_ast_patterns(
    reconstructed_files: dict[str, str] | None,
    case_id: str,
    artifact_id: str = "no_artifact",
) -> ASTResult:
```

AST operates on the `reconstructed_files` dict — the same code snapshot used for execution.

### Failure mode status values

| Scenario | `ast.status` | `ast.reason` | `ast_correct` | `ast_score` |
|----------|-------------|-------------|---------------|-------------|
| No checker spec for this case | `no_spec` | null | null | null |
| Reconstruction failed | `not_measurable` | `"reconstruction_failed"` | null | null |
| `reconstructed_files` is None or empty | `not_measurable` | `"no_reconstructed_files"` | null | null |
| Code has syntax errors | `not_measurable` | `"syntax_error: <detail>"` | null | null |
| Target function not found in code | `measured_incorrect` | null | false | 0.0 |
| Multi-file case, target file missing | `not_measurable` | `"target_file_not_in_reconstruction"` | null | null |
| Checker exception | `not_measurable` | `"checker_error: <detail>"` | null | null |
| Relaxed pass, no anti-pattern | `measured_correct` | null | true | 1.0 |
| Anti-pattern detected | `measured_incorrect` | null | false | 0.0 |
| Neither relaxed pass nor anti-pattern, target modified | `measured_incorrect` | `"no_pattern_match"` | false | 0.0 |

### Guarantee

```
ast_result ALWAYS exists in every trajectory entry and top-level event.
ast.status is NEVER null or missing.
```

If AST cannot run for any reason, it returns an explicit `not_measurable` or `no_spec` status with a reason string. Silent omission is not possible.

---

## 7. PARTIAL Handling — Configurable

### Config

```yaml
oracle:
  partial_mode: "lenient"  # "strict" | "lenient"
```

| Mode | `oracle_correct` when | Semantics |
|------|----------------------|-----------|
| `strict` | `reasoning_truth == "CORRECT"` | Only fully correct reasoning counts |
| `lenient` | `reasoning_truth in ("CORRECT", "PARTIAL")` | Partially correct counts as correct |

### PARTIAL semantics (formal definition)

From the oracle evaluator rubric, PARTIAL means:
- Identifies the correct bug class but gets the causal chain wrong
- Identifies the correct location but wrong mechanism at that location
- Correctly describes part of a multi-step mechanism but misses critical steps
- Falls into the known trap — identifying a real but non-root cause
- Identifies the correct mechanism but attributes it to the wrong location

PARTIAL is a distinct epistemic category representing incomplete causal understanding. Whether it counts as "correct enough" depends on the research question.

### Logging

Both raw `reasoning_truth` and derived `oracle_correct` are always logged. Any analysis can re-derive under either mode from the same WAL data.

---

## 8. Oracle Prompt Versioning and Reproducibility

### Version string

```
oracle.version = "inline_v1"
```

Incremented when:
- Prompt template text changes
- Rubric criteria change
- Parsing logic changes

### Content hashes (two distinct hashes)

```python
# STATIC: hash of the prompt template file (same across all events in a run)
template_text = Path("core/evaluation/oracle_eval/reasoning_truth_prompt.j2").read_text()
prompt_template_hash = sha256(template_text.encode()).hexdigest()[:16]

# DYNAMIC: hash of the fully rendered prompt (unique per attempt)
prompt_instance_hash = sha256(rendered_prompt_text.encode()).hexdigest()[:16]
```

Logged per-event:

```json
{
    "oracle": {
        "version": "inline_v1",
        "prompt_template_hash": "a3f2b1c4d5e6f7g8",
        "prompt_instance_hash": "x9y8z7w6v5u4t3s2",
        ...
    }
}
```

- `prompt_template_hash` is stable across attempts and cases within a run. Use it to verify the template hasn't changed between runs.
- `prompt_instance_hash` varies per attempt (because reasoning text differs). Use it for exact reproducibility of a specific oracle call.

### Reproducibility guarantee

Given the same:
- `oracle.version`
- `oracle.model`
- `case` dict (ground truth fields)
- `raw_root_cause` + `raw_fix_strategy` (model reasoning)

The oracle prompt is deterministically reproducible. The `prompt_hash` allows verification.

### What happens when prompt/rubric/model changes

| Change | Action |
|--------|--------|
| Prompt text edited | Increment `oracle.version` to `"inline_v2"` |
| Rubric criteria changed | Increment `oracle.version` |
| Oracle model changed | Logged in `oracle.model` field; same version OK if prompt unchanged |
| Parsing logic changed | Increment `oracle.version` |

Analysis scripts MUST filter by `oracle.version` when comparing across runs. Mixing oracle versions in the same analysis is an error.

---

## 9. Oracle Epistemic Status

### Oracle is a measurement instrument, NOT absolute truth

The oracle evaluator is a ground-truth PROXY. It compares model reasoning against human-authored case metadata (bug type, location, invariant, fix pattern, mechanism description). Its accuracy depends on:

1. **Quality of case metadata**: If `ground_truth_bug` is incomplete or ambiguous, the oracle may misjudge
2. **LLM evaluator fidelity**: The oracle LLM (gpt-5-mini) may misinterpret the rubric or reasoning
3. **Rubric edge cases**: PARTIAL vs WRONG boundary is subjective
4. **Paraphrase sensitivity**: Model may use different terminology than the oracle spec

### Error model

| Error type | Direction | Estimated rate | Mitigation |
|-----------|-----------|---------------|------------|
| False CORRECT (overcall) | Oracle says CORRECT but reasoning is actually wrong | ~2-3% | Rubric requires causal chain, not just symptom |
| False WRONG (undercall) | Oracle says WRONG but reasoning is actually correct (paraphrase miss) | ~3-5% | Rubric allows paraphrases; "may use different words" |
| PARTIAL boundary noise | Oracle assigns PARTIAL vs WRONG inconsistently | ~5-8% on boundary cases | Configurable `partial_mode` allows both interpretations |
| LLM non-determinism | Same inputs produce different labels across calls | <1% at temperature=0 | Reproducibility check: inline vs offline comparison |

### Implications for analysis

1. **Never claim oracle = truth.** Say "oracle-evaluated reasoning correctness" not "reasoning correctness."
2. **Report oracle version and model** in every analysis.
3. **Report coverage** (% of events with oracle status = SUCCESS).
4. **Sensitivity analysis**: report results under both `strict` and `lenient` PARTIAL modes.
5. **Disagreement rate** between oracle and classifier is informative, not diagnostic of "which is right."

---

## 10. Sampling Strategy Bias Analysis

### Strategies and bias properties

| Strategy | Bias | Safe for causal claims? | Safe for descriptive stats? | Notes |
|----------|------|------------------------|----------------------------|-------|
| `ALWAYS` | None | YES | YES | Default. Full coverage. |
| `FINAL_ONLY` | Selection bias: only measures reasoning of best attempt | NO — cannot analyze retry dynamics | YES — for final-attempt metrics only | Cannot compute per-attempt oracle trajectories |
| `FIRST_K(n)` | Right-censoring: later attempts unmeasured | PARTIAL — valid for first n attempts only | PARTIAL — must restrict analysis to sampled attempts | Good for "does reasoning start correct?" |
| `RANDOM_SAMPLE(p)` | No systematic bias if p is fixed | YES — with appropriate confidence intervals | YES — with variance adjustment | Most statistically sound cost reduction |

### Required reporting

Every analysis that uses oracle data MUST report:

```
oracle_coverage = count(oracle.status == "SUCCESS") / count(total_attempts)
oracle_sampling_strategy = <strategy used>
```

If `oracle_coverage < 0.90`, the analysis MUST include a bias warning:
```
WARNING: Oracle coverage is {coverage:.1%}. Results may be affected by 
selection bias from sampling strategy "{strategy}".
```

### Which strategies are safe for which claims

| Claim type | ALWAYS | FINAL_ONLY | FIRST_K | RANDOM_SAMPLE |
|-----------|--------|------------|---------|---------------|
| "X% of attempts have correct reasoning" | VALID | INVALID | VALID (for k) | VALID (with CI) |
| "Reasoning improves across retries" | VALID | INVALID | PARTIAL | VALID (with CI) |
| "Oracle-classifier disagreement = Y%" | VALID | VALID (final only) | VALID (for k) | VALID (with CI) |
| "LEG_oracle rate = Z%" | VALID | VALID (final only) | INVALID | VALID (with CI) |

---

## 11. Failure Cascade Handling

### Cascade rules

When an upstream stage fails, downstream stages receive degraded inputs. The following table defines exact behavior for every cascade:

Pipeline order within each attempt: parse → oracle → normalize → reconstruct → classifier → AST → execute → disagreement.

Classifier runs BEFORE execution. This structurally enforces the blindness contract: execution results do not exist when the classifier runs. AST also runs before execution because it operates on the same reconstructed files.

| Upstream failure | Oracle | Classifier | AST | Execution | Disagreement |
|-----------------|--------|-----------|-----|-----------|-------------|
| Parse fails (no JSON) | `SKIPPED` / `UNASSESSED` | `classifier_ran: false` | `not_measurable` / `"parse_failed"` | Runs on un-parsed code (likely fails) | `type: "oracle_not_available"` |
| Oracle LLM timeout | N/A (this IS the failure) | Runs independently | Runs independently | Runs independently | `type: "oracle_not_available"` |
| Oracle LLM exception | N/A | Runs independently | Runs independently | Runs independently | `type: "oracle_not_available"` |
| Normalize fails | Oracle already ran | `classifier_ran: false`, `error: "normalization_failed"` | Runs on recon (independent) | Runs independently | `type: "classifier_not_available"` |
| Reconstruction fails | Oracle already ran | Classifier runs (has artifact, passes empty code) | `not_measurable` / `"reconstruction_failed"` | `pass: false`, `execution_category: "STRUCTURAL_FAILURE"` | Computed from available signals |
| Classifier LLM timeout | Oracle already ran | N/A | AST runs independently | Execution runs independently | `type: "classifier_not_available"` |
| AST checker exception | Oracle already ran | Classifier already ran | N/A | Execution runs independently | Computed from available signals |
| Execution crashes | Oracle already ran | Classifier already ran | AST already ran | N/A | Computed from available signals |

### Exact fallback values per axis

When an axis cannot produce a result, it emits these exact values:

**Oracle fallback:**
```json
{"status": "FAILURE", "reasoning_truth": "UNASSESSED", "oracle_correct": null,
 "justification": "", "error": "<reason>", "latency_ms": <elapsed>}
```

**Classifier fallback:**
```json
{"mechanism_identified": null, "commitments_satisfied": null,
 "reasoning_code_alignment": null, "classifier_ran": false,
 "error": "<reason>"}
```

**AST fallback:**
```json
{"status": "not_measurable", "ast_correct": null, "ast_score": null,
 "reason": "<reason>"}
```

**Execution fallback (when execution cannot run):**
```json
{"pass": false, "score": 0.0, "execution_category": "NOT_EXECUTED"}
```

**Disagreement fallback (when either signal missing):**
```json
{"disagreement": null, "type": "oracle_not_available",
 "classifier_correct": null, "oracle_correct": null}
```
or:
```json
{"disagreement": null, "type": "classifier_not_available",
 "classifier_correct": null, "oracle_correct": null}
```

### Pipeline ordering within each attempt (precise)

```
1. Parse
2. Extract raw fields (for oracle)
3. Oracle                     ← uses raw fields only; independent of everything below
4. Normalize                  ← transforms reasoning text
5. Reconstruct                ← produces code files
6. Classifier                 ← uses normalized reasoning + reconstructed code (BEFORE execution)
7. AST                        ← uses reconstructed code files (BEFORE execution)
8. Execute                    ← runs tests on reconstructed code (AFTER classifier + AST)
9. Disagreement               ← uses oracle + classifier results
10. Assemble trajectory entry ← all axes guaranteed present
```

**Why classifier and AST before execution (v4.1 fix):**
- Classifier is blind to execution results. Running it before execution makes this structural, not just contractual.
- AST operates on reconstructed files, not execution output. No dependency on execution.
- If execution hangs or times out, classifier and AST data is already captured.
- Eliminates entire class of future leakage bugs from refactors that might accidentally pass exec_result to classifier.

Each stage catches its own exceptions and produces a fallback result. No stage failure prevents subsequent stages from running (except: reconstruction failure means AST gets `not_measurable` and classifier gets empty code).

---

## 12. Trajectory Consistency Invariants

### Hard invariants

```
INV-TRAJ-1: len(trajectory) == num_attempts
INV-TRAJ-2: trajectory[k]["attempt"] == k, for all k in range(num_attempts)
INV-TRAJ-3: Every trajectory[k] contains ALL of: execution, oracle, classifier, ast, reasoning_disagreement
INV-TRAJ-4: No trajectory[k] subfield is missing (may be null/fallback, never absent)
INV-TRAJ-5: trajectory is ordered by attempt index (monotonically increasing)
INV-TRAJ-6: best_idx is a valid index into trajectory
INV-TRAJ-7: payload top-level axes == trajectory[best_idx] axes (Section 1 invariant)
```

### Enforcement

These invariants are checked in the pre-write validation layer (Section 15). If any invariant is violated:

1. Log a structured error: `logger.log_structured_error("case.error.trajectory_invariant", cid, {invariant, details})`
2. Attempt to repair (e.g., fill missing subfields with fallback values)
3. If unrepairable, emit the event with `_trajectory_invariant_violation: true` flag
4. Never silently drop the event

### What if `num_attempts` disagrees with `len(trajectory)`?

`num_attempts` is derived from `len(trajectory)`, never set independently:

```python
ev["num_attempts"] = len(trajectory)  # DERIVED, not independent
```

---

## 13. Metric Definitions

All metrics are defined in terms of schema fields. No ambiguity.

### LEG variants

```
LEG_oracle    = trajectory[k].oracle.oracle_correct == true
                AND trajectory[k].execution.pass == false

LEG_classifier = trajectory[k].classifier.mechanism_identified == "CORRECT"
                 AND trajectory[k].classifier.commitments_satisfied in ("CORRECT", "PARTIAL")
                 AND trajectory[k].execution.pass == false

LEG_ast       = trajectory[k].ast.ast_correct == true
                AND trajectory[k].execution.pass == false

LEG_combined  = LEG_oracle AND LEG_ast
                (strongest signal: both reasoning and structure are correct, execution fails)
```

### Lucky fix

```
lucky_fix     = trajectory[k].execution.pass == true
                AND trajectory[k].oracle.oracle_correct == false

lucky_fix_ast = trajectory[k].execution.pass == true
                AND trajectory[k].ast.ast_correct == false
```

### Disagreement rate (aggregate)

```
disagreement_rate = count(trajectory[k].reasoning_disagreement.disagreement == true)
                    / count(trajectory[k].reasoning_disagreement.disagreement is not null)

overcall_rate     = count(type == "classifier_overcall") / count(disagreement is not null)
undercall_rate    = count(type == "classifier_undercall") / count(disagreement is not null)
```

### Per-dimension disagreement (v4.1 addition)

The aggregate disagreement collapses classifier's multi-dimensional signal to one boolean (`mechanism_identified == "CORRECT"`). This hides whether disagreement is driven by mechanism, commitments, or alignment.

Per-dimension metrics (computed in analysis, not pipeline):

```
mechanism_disagree  = (classifier.mechanism_identified == "CORRECT") != oracle_correct
commitment_disagree = (classifier.commitments_satisfied in ("CORRECT","PARTIAL")) != oracle_correct
alignment_disagree  = (classifier.reasoning_code_alignment == "CORRECT") != oracle_correct
```

Report all three alongside the aggregate. If `mechanism_disagree` is low but `commitment_disagree` is high, the disagreement is driven by commitment evaluation, not mechanism identification. This is a different failure mode requiring different intervention.

**Note:** These per-dimension metrics compare each classifier dimension against the oracle's single `oracle_correct` boolean. This is a simplification — the oracle evaluates mechanism identification, not commitments or alignment separately. The comparison reveals which classifier dimension most frequently diverges from the oracle's mechanism judgment.

### Structural failure rate

```
structural_failure_rate = count(evaluation.outcome_class == "serialization_failure")
                          / count(total_attempts)
```

### 5-class outcome taxonomy (unchanged from v3)

```
serialization_failure  = NOT S
interpretable_success  = S AND E AND R
unsupported_success    = S AND E AND NOT R
LEG                    = S AND NOT E AND R
reasoning_failure      = S AND NOT E AND NOT R
```

Where:
- S = serialization_success (parse + reconstruct succeeded)
- E = execution_success (tests passed)
- R = reasoning_sufficient (mechanism_correct AND commitments_valid, from classifier)

### Oracle-adjusted outcome (new, analysis-only)

```
LEG_oracle_adjusted    = S AND NOT E AND oracle_correct
reasoning_failure_adj  = S AND NOT E AND NOT oracle_correct
```

These are computed in analysis scripts, not in the pipeline. They use oracle instead of classifier for the reasoning axis.

---

## 14. Incomplete Attempt Handling

### The rule

```
No silent omission of attempts. Every started attempt is either
COMPLETED (full trajectory entry) or INCOMPLETE (explicit marker).
```

### Implementation

```python
# At the START of each attempt iteration:
attempt_started = True
incomplete_entry = {
    "attempt": k,
    "status": "INCOMPLETE_ATTEMPT",
    "execution": {"pass": false, "score": 0.0, "execution_category": "ATTEMPT_INCOMPLETE"},
    "oracle": {"status": "FAILURE", "reasoning_truth": "UNASSESSED", "oracle_correct": null,
               "error": "attempt_incomplete", "latency_ms": 0, ...},
    "classifier": {"mechanism_identified": null, "commitments_satisfied": null,
                   "reasoning_code_alignment": null, "classifier_ran": false,
                   "error": "attempt_incomplete"},
    "ast": {"status": "not_measurable", "ast_correct": null, "ast_score": null,
            "reason": "attempt_incomplete"},
    "reasoning_disagreement": {"disagreement": null, "type": "attempt_incomplete",
                               "classifier_correct": null, "oracle_correct": null},
    "parse_valid": false,
    "code_length": 0,
}

try:
    # ... full attempt pipeline ...
    trajectory.append(complete_entry)
except Exception as exc:
    _log.error("Attempt %d crashed for %s: %s", k, cid, exc)
    incomplete_entry["error"] = str(exc)[:500]
    trajectory.append(incomplete_entry)
```

### How analysis handles incomplete attempts

```python
# Filter to completed attempts only:
completed = [t for t in trajectory if t.get("status") != "INCOMPLETE_ATTEMPT"]

# Report incomplete rate:
incomplete_rate = (len(trajectory) - len(completed)) / len(trajectory)
```

Incomplete attempts are NEVER used for metric computation. They exist solely for debugging and completeness accounting.

---

## 15. Pre-Write Validation Layer

### Purpose

Before every WAL event emission, validate schema consistency and invariants. Catch corruption before it reaches disk.

### Implementation

```python
def _validate_event_before_write(ev: dict, trajectory: list, best_idx: int) -> list[str]:
    """Validate event dict before WAL emission.
    
    Returns list of violation descriptions. Empty = valid.
    Uses == (value equality) throughout — never `is` (pointer identity).
    """
    violations = []
    
    # ── 1. Structural presence checks ──
    if ev.get("_schema_version") != "v3.1":
        violations.append(f"missing or wrong _schema_version: {ev.get('_schema_version')}")
    
    if "oracle" not in ev:
        violations.append("missing payload.oracle")
    elif ev["oracle"].get("status") is None:
        violations.append("oracle.status is null")
    elif ev["oracle"].get("reasoning_truth") is None:
        violations.append("oracle.reasoning_truth is null")
    
    if "classification" not in ev:
        violations.append("missing payload.classification")
    
    if "ast_eval" not in ev:
        violations.append("missing payload.ast_eval")
    
    if "evaluation" not in ev:
        violations.append("missing payload.evaluation")
    
    # ── 2. Semantic consistency checks (v4.1 addition) ──
    oracle = ev.get("oracle", {})
    if oracle.get("reasoning_truth") and oracle.get("oracle_correct") is not None:
        rt = oracle["reasoning_truth"]
        oc = oracle["oracle_correct"]
        pm = oracle.get("partial_mode", "lenient")
        if pm == "strict":
            expected = (rt == "CORRECT")
        else:
            expected = rt in ("CORRECT", "PARTIAL")
        if oc != expected:
            violations.append(
                f"oracle_correct={oc} inconsistent with reasoning_truth={rt} "
                f"under partial_mode={pm} (expected {expected})")
    
    ast_eval = ev.get("ast_eval", {})
    ast_status = ast_eval.get("status")
    ast_correct = ast_eval.get("ast_correct")
    if ast_status == "measured_correct" and ast_correct is not True:
        violations.append(f"ast_status=measured_correct but ast_correct={ast_correct}")
    if ast_status == "measured_incorrect" and ast_correct is not False:
        violations.append(f"ast_status=measured_incorrect but ast_correct={ast_correct}")
    if ast_status in ("no_spec", "not_measurable") and ast_correct is not None:
        violations.append(f"ast_status={ast_status} but ast_correct={ast_correct} (expected null)")
    
    # ── 3. Trajectory invariants (retry events only) ──
    if trajectory:
        # INV-TRAJ-1
        if ev.get("num_attempts") != len(trajectory):
            violations.append(
                f"num_attempts={ev.get('num_attempts')} != len(trajectory)={len(trajectory)}")
        
        for k, entry in enumerate(trajectory):
            # INV-TRAJ-2
            if entry.get("attempt") != k:
                violations.append(f"trajectory[{k}].attempt={entry.get('attempt')} != {k}")
            
            # INV-TRAJ-3
            for required in ("execution", "oracle", "classifier", "ast", "reasoning_disagreement"):
                if required not in entry:
                    violations.append(f"trajectory[{k}] missing '{required}'")
        
        # INV-TRAJ-7: canonical source invariant (VALUE equality, not pointer)
        if 0 <= best_idx < len(trajectory):
            best = trajectory[best_idx]
            if ev.get("oracle") != best.get("oracle"):
                violations.append("payload.oracle != trajectory[best_idx].oracle (value mismatch)")
            if ev.get("classification") != best.get("classifier"):
                violations.append("payload.classification != trajectory[best_idx].classifier")
            if ev.get("ast_eval") != best.get("ast"):
                violations.append("payload.ast_eval != trajectory[best_idx].ast")
    
    return violations
```

### Behavior on violation

```python
violations = _validate_event_before_write(ev, trajectory, best_idx)
if violations:
    _log.error("PRE-WRITE VALIDATION FAILED for %s: %s", cid, violations)
    ev["_validation_violations"] = violations
    # Still emit the event — corrupted data with a flag is better than lost data
```

Events with `_validation_violations` present are quarantined in analysis:
```python
valid_events = df[df["_validation_violations"].isna()]
```

---

## 16. Oracle Evaluator Prompt (verbatim)

From `core/evaluation/oracle_eval/reasoning_truth_prompt.j2`:

```
You are an oracle reasoning evaluator. Your job is to determine whether a developer's stated root cause and fix strategy correctly identify the TRUE bug mechanism.

You are given:
1. The task description (what the developer was asked to do)
2. The original buggy code (the code the developer analyzed)
3. The TRUE bug mechanism (oracle ground truth — this is authoritative)
4. The developer's reasoning (their root_cause and fix_strategy)

## CRITICAL RULES

- You must judge ONLY whether the reasoning identifies the TRUE mechanism described in the oracle.
- You must NOT consider whether the developer's proposed fix would actually work in code.
- You must NOT consider any generated or modified code — you are evaluating the REASONING, not the implementation.
- You must NOT use the task description to infer what "good reasoning" would look like — use ONLY the oracle.
- You must evaluate mechanism identification, NOT symptom description. Describing what goes wrong (symptom) is NOT the same as identifying WHY it goes wrong (mechanism).

## TASK DESCRIPTION

{{ task }}

## ORIGINAL BUGGY CODE

```python
{{ buggy_code }}
```

## ORACLE GROUND TRUTH

Bug type: {{ bug_type }}
Bug location: {{ bug_location }}
Invariant violated: {{ invariant }}
Correct fix pattern: {{ fix_pattern }}
Mechanism: {{ mechanism_description }}
{% if trap_description and trap_description != "No trap" %}
Known trap (incorrect fix that may seem plausible): {{ trap_description }}
{% endif %}

## DEVELOPER REASONING

Root cause: {{ root_cause }}
Fix strategy: {{ fix_strategy }}

## EVALUATION RUBRIC

### CORRECT
The reasoning correctly identifies the TRUE causal mechanism:
- Names the correct root cause (may use different words than oracle — paraphrases are acceptable)
- References the correct location (file/function) or the correct code construct
- Captures the causal chain (WHY the bug causes the failure, not just WHAT the failure is)

### PARTIAL
The reasoning is partially correct:
- Identifies the correct bug class but gets the causal chain wrong
- Identifies the correct location but wrong mechanism at that location
- Correctly describes part of a multi-step mechanism but misses critical steps
- Falls into the known trap (if one exists) — identifying a real but non-root cause
- Identifies the correct mechanism but attributes it to the wrong location

### WRONG
The reasoning is incorrect:
- Identifies a different mechanism than the oracle
- Describes only the symptom (what goes wrong) without identifying why
- References the wrong location/function as the bug source
- Proposes a mechanism that is contradicted by the code
- Identifies a completely different bug type

### UNJUDGABLE
- Reasoning is missing, empty, or too vague to evaluate (e.g., "there is a bug")
- Reasoning contains only generic statements with no specific mechanism claim

## OUTPUT FORMAT

You must respond with EXACTLY two lines:

Line 1: CORRECT | PARTIAL | WRONG | UNJUDGABLE
Line 2: <one-sentence justification referencing specific parts of the reasoning and oracle>

Do NOT include any other text.
```

### Prompt variables

| Variable | Source | Mutability |
|----------|--------|-----------|
| `task` | `case["task"]` | Fixed per case |
| `buggy_code` | Loaded from `case["code_files"]` on disk | Fixed per case |
| `bug_type` | `case["ground_truth_bug"]["type"]` | Fixed per case |
| `bug_location` | `case["ground_truth_bug"]["location"]` | Fixed per case |
| `invariant` | `case["ground_truth_bug"]["invariant"]` | Fixed per case |
| `fix_pattern` | `case["ground_truth_bug"]["fix_pattern"]` | Fixed per case |
| `mechanism_description` | `case["description"]` | Fixed per case |
| `trap_description` | `case["trap"]` | Fixed per case |
| `root_cause` | `parsed_gen.full_json["root_cause"]` (RAW) | Varies per attempt |
| `fix_strategy` | `parsed_gen.full_json["fix_strategy"]` (RAW) | Varies per attempt |

---

## 17. Oracle Sampling Strategy

### Config

```yaml
oracle:
  sampling_strategy: "ALWAYS"  # ALWAYS | FINAL_ONLY | FIRST_K(n) | RANDOM_SAMPLE(p)
```

### Strategies

| Strategy | Oracle runs on | Skip status |
|----------|---------------|-------------|
| `ALWAYS` | All attempts | N/A |
| `FINAL_ONLY` | Best attempt only | `SAMPLING_SKIP` for non-best |
| `FIRST_K(n)` | Attempts 0..n-1 | `SAMPLING_SKIP` for attempts >= n |
| `RANDOM_SAMPLE(p)` | Each attempt with probability p | `SAMPLING_SKIP` when not sampled |

### Skip result

```json
{
    "status": "SAMPLING_SKIP",
    "reasoning_truth": "UNASSESSED",
    "oracle_correct": null,
    "justification": "",
    "error": null,
    "latency_ms": 0,
    "sampling_strategy": "FIRST_K(3)",
    "sampling_reason": "attempt 4 > k=3"
}
```

### FINAL_ONLY implementation

```python
# During loop: skip oracle
oracle_result = _make_sampling_skip("FINAL_ONLY", "deferred to best attempt")

# After loop: run oracle on best attempt
best_fj = best_parsed_gen.full_json or {}
oracle_result = _run_oracle_evaluation(
    best_fj.get("root_cause", ""), best_fj.get("fix_strategy", ""), case, config)
trajectory[best_idx]["oracle"] = oracle_result
# Recompute disagreement for best attempt
trajectory[best_idx]["reasoning_disagreement"] = _compute_per_attempt_disagreement(...)
```

---

## 18. Full WAL Schema (v3.1)

### Baseline event (single attempt, no trajectory)

```json
{
    "_schema_version": "v3.1",
    "payload": {
        "pass": true,
        "score": 1.0,
        "_extracted_code": "...",
        "reconstruction_status": "SUCCESS",
        "v2_artifact": { "raw_root_cause": "...", "raw_fix_strategy": "...", ... },
        "oracle": {
            "version": "inline_v1",
            "prompt_template_hash": "a3f2b1c4d5e6f7g8",
            "prompt_instance_hash": "x9y8z7w6v5u4t3s2",
            "status": "SUCCESS",
            "reasoning_truth": "CORRECT",
            "oracle_correct": true,
            "partial_mode": "lenient",
            "justification": "...",
            "error": null,
            "latency_ms": 340,
            "sampling_strategy": "ALWAYS",
            "sampling_reason": null
        },
        "classification": {
            "mechanism_identified": "CORRECT",
            "commitments_satisfied": "CORRECT",
            "reasoning_code_alignment": "CORRECT",
            "classifier_ran": true,
            "error": null,
            "classifier_mode": "blind",
            "artifact_id": "a1b2c3d4"
        },
        "evaluation": {
            "serialization_success": true,
            "execution_success": true,
            "reasoning_sufficient": true,
            "outcome_class": "interpretable_success",
            "LEG": false,
            "LEG_subtype": null,
            "artifact_id": "a1b2c3d4"
        },
        "ast_eval": {
            "status": "measured_correct",
            "ast_correct": true,
            "ast_score": 1.0,
            "reason": null,
            "artifact_id": "a1b2c3d4"
        },
        "reasoning_disagreement": {
            "disagreement": false,
            "type": "agreement",
            "classifier_correct": true,
            "oracle_correct": true
        },
        "reconstruction": { "..." }
    }
}
```

### Retry event (multiple attempts, with trajectory)

```json
{
    "_schema_version": "v3.1",
    "payload": {
        "pass": true,
        "score": 1.0,
        "oracle": { "...copied from trajectory[best_idx].oracle..." },
        "classification": { "...copied from trajectory[best_idx].classifier..." },
        "ast_eval": { "...copied from trajectory[best_idx].ast..." },
        "evaluation": { "...computed from trajectory[best_idx] axes..." },
        "reasoning_disagreement": { "...copied from trajectory[best_idx]..." },
        "num_attempts": 3,
        "best_attempt_idx": 2,
        "retry_passed_at": 2,
        "retry_mode": "retry_leg_critique_moderate_v2",
        "trajectory": [
            {
                "attempt": 0,
                "status": "COMPLETED",
                "execution": {"pass": false, "score": 0.0, "execution_category": "EXECUTION_FAILURE"},
                "oracle": {"version": "inline_v1", "status": "SUCCESS", "reasoning_truth": "WRONG", "oracle_correct": false, "partial_mode": "lenient", "prompt_template_hash": "...", "prompt_instance_hash": "...", "justification": "...", "error": null, "latency_ms": 280, "sampling_strategy": "ALWAYS", "sampling_reason": null},
                "classifier": {"mechanism_identified": "CORRECT", "commitments_satisfied": "WRONG", "reasoning_code_alignment": "WRONG", "classifier_ran": true, "error": null},
                "ast": {"status": "measured_incorrect", "ast_correct": false, "ast_score": 0.0, "reason": null},
                "reasoning_disagreement": {"disagreement": true, "type": "classifier_overcall", "classifier_correct": true, "oracle_correct": false},
                "parse_valid": true, "code_length": 450, "retry_mode": "retry_leg_critique_moderate_v2",
                "had_test_feedback": false, "mismatch_critique": "...", "mismatch_variant": "moderate"
            },
            {
                "attempt": 1,
                "status": "COMPLETED",
                "execution": {"pass": false, "score": 0.0, "execution_category": "EXECUTION_FAILURE"},
                "oracle": {"version": "inline_v1", "status": "SUCCESS", "reasoning_truth": "PARTIAL", "oracle_correct": true, "partial_mode": "lenient", "prompt_template_hash": "...", "prompt_instance_hash": "...", "justification": "...", "error": null, "latency_ms": 310, "sampling_strategy": "ALWAYS", "sampling_reason": null},
                "classifier": {"mechanism_identified": "CORRECT", "commitments_satisfied": "CORRECT", "reasoning_code_alignment": "WRONG", "classifier_ran": true, "error": null},
                "ast": {"status": "measured_incorrect", "ast_correct": false, "ast_score": 0.0, "reason": null},
                "reasoning_disagreement": {"disagreement": false, "type": "agreement", "classifier_correct": true, "oracle_correct": true},
                "parse_valid": true, "code_length": 470, "retry_mode": "retry_leg_critique_moderate_v2",
                "had_test_feedback": false, "mismatch_critique": "...", "mismatch_variant": "moderate"
            },
            {
                "attempt": 2,
                "status": "COMPLETED",
                "execution": {"pass": true, "score": 1.0, "execution_category": "EXECUTION_SUCCESS"},
                "oracle": {"version": "inline_v1", "status": "SUCCESS", "reasoning_truth": "CORRECT", "oracle_correct": true, "partial_mode": "lenient", "prompt_template_hash": "...", "prompt_instance_hash": "...", "justification": "...", "error": null, "latency_ms": 290, "sampling_strategy": "ALWAYS", "sampling_reason": null},
                "classifier": {"mechanism_identified": "CORRECT", "commitments_satisfied": "CORRECT", "reasoning_code_alignment": "CORRECT", "classifier_ran": true, "error": null},
                "ast": {"status": "measured_correct", "ast_correct": true, "ast_score": 1.0, "reason": null},
                "reasoning_disagreement": {"disagreement": false, "type": "agreement", "classifier_correct": true, "oracle_correct": true},
                "parse_valid": true, "code_length": 490, "retry_mode": "retry_leg_critique_moderate_v2",
                "had_test_feedback": false, "mismatch_critique": null, "mismatch_variant": "moderate"
            }
        ]
    }
}
```

---

## 19. Pipeline Ordering (v3.1)

### Baseline path (`execution_v2.run_v2`)

```
1.  prompt = _render_generation_prompt(case, condition, config)
2.  raw_response = _call_generation_model(prompt, model, ...)
3.  strict_parse, recovery_parse, fmt_parse = _parse_outputs(raw_response, condition)
4.  routing = _select_artifact(strict_parse, recovery_parse, case)
5.  parsed_gen = strict_parse or recovery_parse (based on routing)

--- ORACLE (before normalize — uses raw fields) ---
5a. fj = parsed_gen.full_json or {}
5b. raw_rc = fj.get("root_cause", "")
5c. raw_fs = fj.get("fix_strategy", "")
5d. oracle_result = _run_oracle_evaluation(raw_rc, raw_fs, case, config)

--- NORMALIZE ---
6.  artifact = normalize_generation_v2(parsed_gen, case, condition)

--- RECONSTRUCT (code assembly, no execution yet) ---
7.  recon, code = _reconstruct(parsed_gen, case, config)
8.  artifact_id = _compute_artifact_id(recon)

--- CLASSIFIER + AST (before execution — structural blindness) ---
9.  classifier_result = _classify_reasoning(artifact, case, code, config, logger, ...)
10. ast_result = _run_ast_verification(recon, case, artifact_id)

--- EXECUTE (after classifier + AST) ---
11. exec_result = _execute(recon, case, config, logger)

--- DERIVED METRICS ---
12. disagreement = _compute_per_attempt_disagreement(classifier_result, oracle_result, config)
13. signals = _derive_metrics(classifier_result, artifact, exec_result, parsed_gen)
14. evaluation = _compute_evaluation(routing, recon, exec_result, classifier_result, artifact_id)

--- ASSEMBLE + VALIDATE + LOG ---
15. ev = _assemble_result(..., oracle_result, disagreement)
16. violations = _validate_event_before_write(ev, [], -1)
17. _log_result(logger, ...)
```

**Note:** This requires splitting the current `_reconstruct_and_execute()` into separate `_reconstruct()` and `_execute()` functions to place classifier and AST between them. This is a necessary refactor — the current combined function makes it impossible to run classifier before execution.

### Retry path (`retry_v2.run_retry_v2`)

```
for k in range(max_iterations):
    try:
        1. Build prompt
        2. Call model → raw_response
        3. Parse → parsed_gen

        4. Extract raw fields:
           fj = parsed_gen.full_json or {}
           raw_rc = fj.get("root_cause", "")
           raw_fs = fj.get("fix_strategy", "")

        5. Oracle (before normalize):
           oracle_result = _run_oracle_evaluation(raw_rc, raw_fs, case, config)

        6. Normalize:
           artifact = normalize_generation_v2(parsed_gen, case, condition)

        7. Reconstruct (code assembly only):
           recon = reconstruct_strict(...)
           code = assemble_code(recon)
           artifact_id = _compute_artifact_id(recon)

        8. Classifier (per-attempt, BEFORE execution):
           classifier_result = classify_case(artifact, case, code, config, logger, ...)

        9. AST (per-attempt, BEFORE execution):
           ast_result = _run_ast_verification(recon, case, artifact_id)

        10. Execute (AFTER classifier + AST):
            exec_result = exec_canonical(case, parsed_gen, recon, config, logger, attempt=k)

        11. Disagreement:
            disagreement = _compute_per_attempt_disagreement(
                classifier_result, oracle_result, config)

        12. Append COMPLETED trajectory entry

    except Exception as exc:
        Append INCOMPLETE trajectory entry (Section 14)

    13. Best-tracking, loop control, build hints for next iteration

# After loop:
best_idx = select_best_attempt(trajectory)
# Top-level fields derived from trajectory[best_idx] (Section 1)
ev = _assemble_final_from_trajectory(trajectory, best_idx, ...)
violations = _validate_event_before_write(ev, trajectory, best_idx)
_log_result(...)
```

---

## 20. Backward Compatibility

### Old WAL records (v2, v3.0)

| Missing field | Default behavior |
|--------------|-----------------|
| `_schema_version` absent | Treat as "v2" |
| `payload.oracle` absent | `oracle_coverage_status = "not_present_legacy"` |
| `trajectory[k].oracle` absent | Per-attempt oracle = UNASSESSED |
| `trajectory[k].classifier` absent | Per-attempt classifier = not available |
| `trajectory[k].ast` absent | Per-attempt AST = not available |
| `trajectory[k].reasoning_disagreement` absent | null |
| `trajectory[k].status` absent | Treat as "COMPLETED" (old format) |
| `best_attempt_idx` absent | Derive from trajectory (first pass or last) |

### Dashboard fallback chain

```python
# 1. Inline oracle (v3.1+)
oracle_truth = payload.get("oracle", {}).get("reasoning_truth")

# 2. Sidebar-loaded oracle labels (legacy)
if oracle_truth is None or oracle_truth == "UNASSESSED":
    oracle_truth = sidebar_oracle_labels.get(join_key)

# 3. Not available
if oracle_truth is None:
    oracle_truth = "UNASSESSED"
```

---

## 21. Config Schema Extension

```yaml
oracle:
  inline_enabled: true
  model: "gpt-5-mini"
  timeout: 30
  partial_mode: "lenient"        # "strict" | "lenient"
  sampling_strategy: "ALWAYS"    # "ALWAYS" | "FINAL_ONLY" | "FIRST_K(n)" | "RANDOM_SAMPLE(p)"
```

---

## 22. Validation Plan

### A. Per-attempt alignment check
Verify every `trajectory[k]` has all 5 sub-objects. Zero missing fields.

### B. Oracle input integrity check
For 50 events, compare oracle inputs against `parsed_gen.full_json["root_cause"]`. Character-identical.

### C. Canonical source invariant check
For every retry event, verify `payload.oracle == trajectory[best_idx].oracle`.

### D. Best attempt selection check
For 20 retry chains: verify best_idx is first passing attempt (or last if none pass).

### E. Classifier-oracle disagreement analysis
Overall disagreement rate (expected ~7-10%). Stratify by family.

### F. Coverage validation
Oracle status distribution. Expected ~95% SUCCESS, ~5% SKIPPED.

### G. Retry consistency
Does oracle verdict improve across attempts? Does disagreement decrease?

### H. Inline vs offline comparison
200 events. Expected >99% agreement.

### I. Atomicity check
Every v3.1 `case.end` event has oracle, classification, ast_eval, evaluation sections. Zero missing.

### J. PARTIAL mode check
Run strict vs lenient. Verify `oracle_correct` differs for PARTIAL cases. Verify raw `reasoning_truth` identical.

### K. Sampling strategy check
Run FIRST_K(2). Verify attempts 0-1 have SUCCESS, attempts 2+ have SAMPLING_SKIP.

### L. Incomplete attempt check
Inject a crash mid-attempt. Verify trajectory contains INCOMPLETE entry with error string.

### M. Pre-write validation check
Inject a malformed event (missing oracle section). Verify `_validation_violations` is logged.

---

## 23. Rollout Plan

### Phase 0: Audit (0.5 day)
Confirm integration points. Verify `parsed_gen.full_json` availability timing. Verify oracle import paths.

### Phase 1: Schema + config + validation layer (1 day)
Add `_schema_version`, oracle config section, dashboard schema fields. Implement `_validate_event_before_write()`.

### Phase 2: Inline oracle in baseline path (1 day)
`_run_oracle_evaluation()` + disagreement + pre-write validation in `execution_v2.py`.

### Phase 3: Per-attempt axes in retry path (1.5 days)
Oracle + classifier + AST + disagreement per-attempt in retry loop. Incomplete attempt handling. Best attempt selection.

### Phase 4: Sampling strategy + PARTIAL mode (0.5 day)
Implement all 4 sampling strategies. Implement strict/lenient partial mode.

### Phase 5: Dashboard update (1 day)
Oracle tab with inline oracle, disagreement, per-attempt trajectory.

### Phase 6: Validation (1 day)
Run all checks from Section 22 (A through M).

### Phase 7: Documentation (0.5 day)
Update docs. Mark offline oracle as legacy.

**Total: ~7 days**
