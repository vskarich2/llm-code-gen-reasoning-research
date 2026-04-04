# Inline Oracle Integration Plan v3 — Full Revision

**Date:** 2026-04-03
**Supersedes:** inline_oracle_integration_plan_v2.md
**Status:** PLAN ONLY

---

## Changes from v2

1. **Classifier and AST now run per-attempt** (v2 had them final-only). Trajectory entries contain all four axes. This enables causal retry analysis.
2. **Oracle input integrity guarantee** added. Oracle uses raw model fields from `parsed_gen.full_json`, not normalized artifact fields.
3. **PARTIAL handling made configurable** via `oracle.partial_mode` config key. No hardcoded `CORRECT_OR_PARTIAL` rule.
4. **Per-attempt disagreement tracking** added in `trajectory[k].reasoning_disagreement`.
5. **True atomicity guarantee** with explicit failure handling for oracle timeout, exception, and partial pipeline failure. Every trajectory entry always has all four axis objects.
6. **Oracle sampling strategy** added via `oracle.sampling_strategy` config key with four modes.
7. **Formal experimental unit definition** made explicit.
8. **Full updated schema** with trajectory-level classifier, AST, oracle, and disagreement.
9. **Oracle prompt included verbatim** from `reasoning_truth_prompt.j2`.

---

## 1. Formal Experimental Unit Definition

```
experimental_unit = (case_id, model, condition, trial, attempt)
```

Every experimental unit MUST contain aligned signals from all four measurement axes:

| Axis | Signal | Scope |
|------|--------|-------|
| Execution (E) | `exec_pass`, `score`, `execution_category` | per-attempt |
| Oracle (O) | `reasoning_truth`, `justification` | per-attempt |
| Classifier (C) | `mechanism_identified`, `commitments_satisfied`, `reasoning_code_alignment` | per-attempt |
| Structure (AST) | `ast_status`, `ast_correct` | per-attempt |

The join key for any cross-axis analysis is the 5-tuple above. No analysis may mix signals from different attempts within the same retry chain.

---

## 2. Why All Four Axes Must Be Per-Attempt

### v2 design (broken)

In v2, classifier and AST ran only on the **best/final attempt** of a retry chain. This means:

- For attempt 0 that failed: we had execution data but no classifier, AST, or oracle
- For attempt 3 that passed: we had all four axes
- For attempt 1 (intermediate failure): only execution data

This makes retry analysis impossible. You cannot ask "did reasoning improve across retries?" without per-attempt classifier data. You cannot ask "did AST correctness change?" without per-attempt AST data.

### v3 design (fixed)

All four axes run on EVERY attempt. Every `trajectory[k]` entry is a complete experimental unit.

### Computational cost justification

| Axis | Cost per call | Latency | Calls per attempt |
|------|--------------|---------|-------------------|
| Oracle | ~$0.001 | ~3s | 1 LLM call |
| Classifier | ~$0.002 | ~3s | 1 LLM call |
| AST | $0 | <50ms | local computation |
| Execution | ~$0 | ~1-30s | local subprocess |

For a 5-attempt retry chain on 72 cases:
- v2 cost: 72 * (1 classifier + 1 AST) = 72 classifier calls
- v3 cost: 72 * 5 * (1 oracle + 1 classifier + 1 AST) = 360 oracle + 360 classifier calls
- Additional cost: ~$1.08 per ablation (negligible vs generation cost of ~$50-100)
- Additional latency per case: ~30s total (oracle + classifier run sequentially per attempt)

The cost is negligible. The scientific value (complete per-attempt decomposition) is critical.

### Why this is necessary for causal analysis

Without per-attempt alignment:
- Cannot compute P(reasoning_improves | execution_fails) across retries
- Cannot detect cases where AST correctness degrades across retries (regression)
- Cannot measure oracle-classifier disagreement trajectory
- Cannot identify whether critique feedback improves reasoning or just code

With per-attempt alignment:
- Full causal decomposition of retry dynamics
- Disagreement evolution curves
- Per-attempt LEG classification (reasoning correct but execution fails at attempt k)

---

## 3. Oracle Input Integrity

### The guarantee

```
Oracle uses the RAW model reasoning text, NEVER normalized or transformed text.
```

### Source fields

The oracle reads from the **parsed JSON** directly, before normalization:

```python
# In the retry loop, BEFORE normalize_generation_v2():
fj = parsed_gen.full_json or {}
raw_root_cause = fj.get("root_cause", "")
raw_fix_strategy = fj.get("fix_strategy", "")
```

These are the exact strings the model produced in its JSON output. They have been:
- Extracted from the raw LLM response by the JSON parser
- NOT normalized (no trimming, no scope tagging, no dedup)
- NOT transformed (no commitment splitting, no string replacement)
- NOT reconstructed (no code assembly)

### Why `artifact.raw_root_cause` is also acceptable

The `NormalizedReasoningArtifactV2` stores both raw and normalized fields:

```python
# From reasoning_v2.py lines 206-212:
raw_root_cause = fj.get("root_cause", "")     # exact model output
raw_fix_strategy = fj.get("fix_strategy", "")  # exact model output
```

These `raw_*` fields are copied verbatim from `parsed_gen.full_json` without transformation. Using `artifact.raw_root_cause` is equivalent to using `fj.get("root_cause", "")`.

**However, for maximum clarity**, the oracle integration will read from `parsed_gen.full_json` directly, BEFORE `normalize_generation_v2()` is called. This makes it impossible for any future normalization changes to affect oracle inputs.

### Pipeline ordering enforcement

```
parse → extract raw fields → oracle(raw fields) → normalize → reconstruct → execute → classify → AST
```

Oracle runs AFTER parsing (raw fields available) but BEFORE normalization. Even if `normalize_generation_v2` is later modified to mutate the raw fields (which it currently does not), the oracle has already captured its inputs.

### Function signature enforcement

```python
def _run_oracle_evaluation(
    raw_root_cause: str,      # from parsed_gen.full_json["root_cause"]
    raw_fix_strategy: str,    # from parsed_gen.full_json["fix_strategy"]
    case: dict,
    config,
) -> dict:
```

The signature takes raw strings, not the artifact. This prevents any normalization leak.

---

## 4. PARTIAL Handling — Configurable

### Problem with v2

v2 hardcoded:
```python
oracle_correct = reasoning_truth in ("CORRECT", "PARTIAL")
```

This collapses PARTIAL into CORRECT, which is a scientific judgment that should be configurable and versioned.

### v3 design: `oracle.partial_mode`

```yaml
oracle:
  partial_mode: "lenient"  # "strict" | "lenient"
```

| Mode | `oracle_correct` when | Semantics |
|------|----------------------|-----------|
| `strict` | `reasoning_truth == "CORRECT"` | Only fully correct reasoning counts. PARTIAL is treated as incorrect. |
| `lenient` | `reasoning_truth in ("CORRECT", "PARTIAL")` | Partially correct reasoning counts as correct. Matches v2 behavior. |

### Logging

The mode is logged in every oracle result:

```json
{
  "oracle": {
    "partial_mode": "lenient",
    "reasoning_truth": "PARTIAL",
    "oracle_correct": true
  }
}
```

The raw `reasoning_truth` is ALWAYS logged regardless of mode. The derived `oracle_correct` boolean reflects the configured mode. This allows re-analysis under either mode from the same WAL data.

### PARTIAL semantics (formal definition)

From the oracle evaluator rubric:

- **PARTIAL** means the model identified the correct bug class but got the causal chain wrong, OR identified the correct location but wrong mechanism, OR correctly described part of a multi-step mechanism but missed critical steps, OR fell into the known trap.

PARTIAL is NOT "almost correct." It is a distinct category representing incomplete causal understanding. Whether to count it as "correct enough" depends on the research question being asked.

---

## 5. Per-Attempt Disagreement

### v2 design (top-level only)

v2 computed disagreement only at the top level of the event. This loses retry dynamics.

### v3 design: per-attempt disagreement

Every `trajectory[k]` entry includes:

```json
{
  "reasoning_disagreement": {
    "disagreement": true,
    "type": "classifier_overcall",
    "classifier_correct": true,
    "oracle_correct": false
  }
}
```

### Computation

```python
def _compute_per_attempt_disagreement(classifier_result, oracle_result, partial_mode):
    cls_correct = (classifier_result.mechanism_identified == "CORRECT")
    
    oracle_truth = oracle_result.get("reasoning_truth", "UNASSESSED")
    if oracle_truth == "UNASSESSED":
        return {"disagreement": None, "type": "oracle_not_available",
                "classifier_correct": cls_correct, "oracle_correct": None}
    
    if partial_mode == "strict":
        oracle_correct = (oracle_truth == "CORRECT")
    else:
        oracle_correct = oracle_truth in ("CORRECT", "PARTIAL")
    
    if cls_correct == oracle_correct:
        dtype = "agreement"
    elif cls_correct and not oracle_correct:
        dtype = "classifier_overcall"
    else:
        dtype = "classifier_undercall"
    
    return {
        "disagreement": cls_correct != oracle_correct,
        "type": dtype,
        "classifier_correct": cls_correct,
        "oracle_correct": oracle_correct,
    }
```

### What this enables

- **Disagreement evolution**: does classifier-oracle disagreement decrease across retries?
- **Debugging**: which attempts have overcall vs undercall?
- **Retry causal analysis**: does critique feedback help the classifier more than the oracle (or vice versa)?

---

## 6. True Atomicity Guarantee

### The guarantee

Every `trajectory[k]` entry ALWAYS contains ALL of:

```json
{
  "execution": { ... },
  "oracle": { ... },
  "classifier": { ... },
  "ast": { ... },
  "reasoning_disagreement": { ... }
}
```

No field is EVER missing. If a component fails, it emits an explicit failure object.

### Failure handling

| Failure scenario | oracle result | classifier result | ast result |
|-----------------|---------------|-------------------|------------|
| Oracle LLM timeout | `{"status": "FAILURE", "reasoning_truth": "UNASSESSED", "error": "timeout after 30s"}` | runs independently | runs independently |
| Oracle LLM exception | `{"status": "FAILURE", "reasoning_truth": "UNASSESSED", "error": "<exc>"}` | runs independently | runs independently |
| Classifier LLM timeout | oracle runs independently | `{"classifier_ran": false, "error": "timeout"}` | runs independently |
| Parse failure (no JSON) | `{"status": "SKIPPED", "reasoning_truth": "UNASSESSED"}` | `{"classifier_ran": false}` | `{"status": "not_measurable"}` |
| Reconstruction failure | oracle already ran | classifier may or may not run | `{"status": "not_measurable", "reason": "reconstruction_failed"}` |
| Execution crash | oracle already ran | classifier may or may not run | AST already ran |

### Implementation pattern

```python
# Inside retry loop, per attempt k:
# 1. Parse (already exists)
# 2. Extract raw fields for oracle
fj = parsed_gen.full_json or {}
raw_rc = fj.get("root_cause", "")
raw_fs = fj.get("fix_strategy", "")

# 3. Oracle (before normalize, before execute)
oracle_result = _run_oracle_evaluation(raw_rc, raw_fs, case, config)

# 4. Normalize + Reconstruct + Execute (already exists)
artifact = normalize_generation_v2(parsed_gen, case, condition)
recon = reconstruct_strict(...)
exec_result = exec_canonical(...)

# 5. Classifier (per-attempt, NEW)
classifier_result = _classify_per_attempt(artifact, case, code, config, logger, ...)

# 6. AST (per-attempt, NEW)
ast_result = _run_ast_verification(recon, case, artifact_id)

# 7. Disagreement (per-attempt, NEW)
disagreement = _compute_per_attempt_disagreement(
    classifier_result, oracle_result, config.oracle.partial_mode)

# 8. Assemble trajectory entry — ALL fields ALWAYS present
trajectory.append({
    "attempt": k,
    "execution": {
        "pass": passed,
        "score": exec_result.get("score", 0),
        "execution_category": exec_result.get("execution_category"),
    },
    "oracle": oracle_result,
    "classifier": {
        "mechanism_identified": classifier_result.mechanism_identified,
        "commitments_satisfied": classifier_result.commitments_satisfied,
        "reasoning_code_alignment": classifier_result.reasoning_code_alignment,
        "classifier_ran": classifier_result.parse_error is None,
    },
    "ast": ast_result.to_dict(),
    "reasoning_disagreement": disagreement,
    # ... existing fields (parse_valid, code_length, critique, etc.)
})
```

### What if the entire pipeline crashes mid-attempt?

If Python raises an unhandled exception during attempt k, the trajectory entry for attempt k is NOT appended (the code hasn't reached the append). The event is still emitted for the best prior attempt. The `num_attempts` field reflects how many complete trajectory entries exist.

This is acceptable: a mid-attempt crash means we have no valid data for that attempt. Emitting partial data would be worse than omitting it.

---

## 7. Oracle Sampling Strategy

### Config

```yaml
oracle:
  inline_enabled: true
  model: "gpt-5-mini"
  timeout: 30
  partial_mode: "lenient"
  sampling_strategy: "ALWAYS"  # ALWAYS | FINAL_ONLY | FIRST_K(n) | RANDOM_SAMPLE(p)
```

### Strategies

| Strategy | Description | Oracle runs on | Use case |
|----------|-------------|----------------|----------|
| `ALWAYS` | Default. Oracle runs on every attempt. | All attempts | Full per-attempt decomposition |
| `FINAL_ONLY` | Oracle runs only on the final/best attempt | Last attempt | Cost-sensitive runs |
| `FIRST_K(n)` | Oracle runs on first n attempts only | Attempts 0..n-1 | Early retry analysis |
| `RANDOM_SAMPLE(p)` | Oracle runs with probability p per attempt | Random subset | Unbiased cost reduction |

### Parsing the config value

```python
def _parse_sampling_strategy(strategy_str: str) -> tuple[str, dict]:
    """Parse strategy string into (mode, params)."""
    s = strategy_str.strip().upper()
    if s == "ALWAYS":
        return ("ALWAYS", {})
    if s == "FINAL_ONLY":
        return ("FINAL_ONLY", {})
    if s.startswith("FIRST_K(") and s.endswith(")"):
        n = int(s[8:-1])
        return ("FIRST_K", {"n": n})
    if s.startswith("RANDOM_SAMPLE(") and s.endswith(")"):
        p = float(s[14:-1])
        assert 0 < p <= 1, f"RANDOM_SAMPLE probability must be in (0, 1], got {p}"
        return ("RANDOM_SAMPLE", {"p": p})
    raise ValueError(f"Unknown oracle sampling strategy: {strategy_str}")
```

### Skip behavior

When oracle is skipped due to sampling:

```json
{
  "oracle": {
    "status": "SAMPLING_SKIP",
    "reasoning_truth": "UNASSESSED",
    "justification": "",
    "error": null,
    "latency_ms": 0,
    "sampling_strategy": "FIRST_K(3)",
    "sampling_reason": "attempt 4 > k=3"
  }
}
```

### Analysis handling

```python
# Analysis must filter on oracle status:
oracle_evaluated = df[df["oracle_status"] == "SUCCESS"]

# Report coverage:
total = len(df)
evaluated = len(oracle_evaluated)
coverage = evaluated / total if total > 0 else 0

# Warn if coverage is low:
if coverage < 0.9:
    log.warning("Oracle coverage %.1f%% — results may have sampling bias", coverage * 100)
```

### FINAL_ONLY implementation in retry loop

```python
for k in range(max_iterations):
    ...
    if sampling_mode == "ALWAYS":
        oracle_result = _run_oracle_evaluation(raw_rc, raw_fs, case, config)
    elif sampling_mode == "FINAL_ONLY":
        oracle_result = _make_sampling_skip("FINAL_ONLY", f"deferred to final attempt")
    elif sampling_mode == "FIRST_K" and k < sampling_params["n"]:
        oracle_result = _run_oracle_evaluation(raw_rc, raw_fs, case, config)
    elif sampling_mode == "RANDOM_SAMPLE" and random.random() < sampling_params["p"]:
        oracle_result = _run_oracle_evaluation(raw_rc, raw_fs, case, config)
    else:
        oracle_result = _make_sampling_skip(sampling_strategy, f"attempt {k} not sampled")
    ...

# After loop, if FINAL_ONLY: run oracle on best attempt
if sampling_mode == "FINAL_ONLY":
    fj = best_parsed_gen.full_json or {}
    oracle_result = _run_oracle_evaluation(
        fj.get("root_cause", ""), fj.get("fix_strategy", ""), case, config)
    # Patch the final trajectory entry
    trajectory[-1]["oracle"] = oracle_result
    trajectory[-1]["reasoning_disagreement"] = _compute_per_attempt_disagreement(...)
```

---

## 8. Oracle Evaluator Prompt (verbatim)

This is the complete oracle prompt template from `core/evaluation/oracle_eval/reasoning_truth_prompt.j2`:

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

### Oracle prompt variables

| Variable | Source | Type |
|----------|--------|------|
| `task` | `case["task"]` | str |
| `buggy_code` | Loaded from `case["code_files"]` on disk | str |
| `bug_type` | `case["ground_truth_bug"]["type"]` | str |
| `bug_location` | `case["ground_truth_bug"]["location"]` | str |
| `invariant` | `case["ground_truth_bug"]["invariant"]` | str |
| `fix_pattern` | `case["ground_truth_bug"]["fix_pattern"]` | str |
| `mechanism_description` | `case["description"]` | str |
| `trap_description` | `case["trap"]` (may be "No trap") | str |
| `root_cause` | `parsed_gen.full_json["root_cause"]` (RAW) | str |
| `fix_strategy` | `parsed_gen.full_json["fix_strategy"]` (RAW) | str |

Note: `root_cause` and `fix_strategy` come from raw parsed JSON, not from the normalized artifact. See Section 3.

---

## 9. Pipeline Ordering (v3)

### Baseline path (`execution_v2.run_v2`)

```
1.  prompt = _render_generation_prompt(case, condition, config)
2.  raw_response = _call_generation_model(prompt, model, ...)
3.  strict_parse, recovery_parse, fmt_parse = _parse_outputs(raw_response, condition)
4.  routing = _select_artifact(strict_parse, recovery_parse, case)
5.  parsed_gen = strict_parse or recovery_parse (based on routing)

--- NEW: extract raw fields for oracle BEFORE normalization ---
5a. fj = parsed_gen.full_json or {}
5b. raw_rc = fj.get("root_cause", "")
5c. raw_fs = fj.get("fix_strategy", "")
5d. oracle_result = _run_oracle_evaluation(raw_rc, raw_fs, case, config)

6.  artifact = normalize_generation_v2(parsed_gen, case, condition)
7.  recon, code, exec_result = _reconstruct_and_execute(parsed_gen, case, config, logger)
8.  artifact_id = _compute_artifact_id(recon)
9.  classifier_result = _classify_reasoning(artifact, case, code, config, logger, ...)
10. signals = _derive_metrics(classifier_result, artifact, exec_result, parsed_gen)
11. evaluation = _compute_evaluation(routing, recon, exec_result, classifier_result, artifact_id)
12. ast_result = _run_ast_verification(recon, case, artifact_id)

--- NEW: disagreement ---
13. disagreement = _compute_per_attempt_disagreement(classifier_result, oracle_result, config)

14. ev = _assemble_result(..., oracle_result, disagreement)
15. _log_result(logger, ...)
```

### Retry path (`retry_v2.run_retry_v2`)

```
for k in range(max_iterations):
    # 1. Build prompt (already exists)
    # 2. Call model (already exists)
    # 3. Parse (already exists)

    --- NEW: extract raw fields ---
    fj = parsed_gen.full_json or {}
    raw_rc = fj.get("root_cause", "")
    raw_fs = fj.get("fix_strategy", "")

    --- NEW: oracle (before normalize) ---
    oracle_result = _run_oracle_evaluation(raw_rc, raw_fs, case, config)
    # (subject to sampling_strategy)

    # 4. Normalize (NEW — per-attempt)
    artifact = normalize_generation_v2(parsed_gen, case, condition)

    # 5. Reconstruct + Execute (already exists)
    recon = reconstruct_strict(...)
    exec_result = exec_canonical(...)

    --- NEW: classifier per-attempt ---
    classifier_result = _classify_per_attempt(artifact, case, code, config, logger, ...)

    --- NEW: AST per-attempt ---
    artifact_id = _compute_artifact_id(recon)
    ast_result = _run_ast_verification(recon, case, artifact_id)

    --- NEW: disagreement per-attempt ---
    disagreement = _compute_per_attempt_disagreement(
        classifier_result, oracle_result, config)

    # 6. Trajectory entry — ALL axes present
    trajectory.append({
        "attempt": k,
        "execution": { "pass": passed, "score": ..., "execution_category": ... },
        "oracle": oracle_result,
        "classifier": { ... },
        "ast": ast_result.to_dict(),
        "reasoning_disagreement": disagreement,
        "parse_valid": parsed_gen.parse_valid,
        "code_length": len(code),
        "retry_mode": condition,
        # ... existing critique/feedback fields
    })

    # 7. Best-tracking, loop control (already exists)

# After loop: final assembly uses best attempt's axis data
# (already computed and stored in trajectory)
```

### Key change from v2 retry flow

In v2 retry, the classifier ran ONCE after the loop on `best_parsed_gen`:
```python
# v2 (retry_v2.py line 551-559):
artifact = normalize_generation_v2(best_parsed_gen, case, "baseline_v2")
classifier_result, _ = classify_case(artifact, case, best_code, ...)
```

In v3, the classifier runs inside the loop on EACH attempt's artifact. The final event still uses the best attempt's classifier result for top-level fields, but every attempt's classifier result is preserved in the trajectory.

### Per-attempt classifier cost control

Classifier is an LLM call (~$0.002, ~3s). For a 5-attempt chain, this adds ~$0.010 and ~15s per case. This is acceptable because:
1. Generation itself costs ~$0.01-0.05 per attempt
2. Total additional classifier cost across a 72-case ablation: ~$3.60
3. The alternative (final-only) makes retry analysis scientifically invalid

If cost becomes a concern, the classifier can be gated the same way as oracle (via a `classifier.sampling_strategy` config key — but this is NOT implemented in v3; oracle sampling is sufficient for now).

---

## 10. Full WAL Schema (v3.1)

### Top-level event structure

```json
{
    "_schema_version": "v3.1",

    "payload": {
        "pass": true,
        "score": 1.0,
        "_extracted_code": "...",
        "reconstruction_status": "SUCCESS",

        "v2_artifact": {
            "raw_root_cause": "...",
            "raw_fix_strategy": "...",
            "normalized_root_cause": "...",
            "normalized_fix_strategy": "...",
            "schema_variant": "v2",
            "parse_status": "success"
        },

        "oracle": {
            "version": "inline_v1",
            "status": "SUCCESS",
            "reasoning_truth": "CORRECT",
            "oracle_correct": true,
            "partial_mode": "lenient",
            "justification": "The reasoning correctly identifies the stale cache mechanism...",
            "error": null,
            "latency_ms": 340,
            "sampling_strategy": "ALWAYS",
            "sampling_reason": null
        },

        "classification": {
            "mechanism_identified": "CORRECT",
            "commitments_extracted": "CORRECT",
            "commitments_satisfied": "CORRECT",
            "reasoning_code_alignment": "CORRECT",
            "classifier_ran": true,
            "classifier_skipped_reason": null,
            "classifier_mode": "blind",
            "classifier_template": "classify_reasoning_v2",
            "classifier_schema_variant": "v2_semicolon",
            "commitment_state": "explicit_valid",
            "artifact_id": "a1b2c3d4e5f6g7h8"
        },

        "evaluation": {
            "serialization_success": true,
            "serialization_failure_type": null,
            "execution_success": true,
            "execution_category": "EXECUTION_SUCCESS",
            "mechanism_correct": true,
            "commitments_valid": true,
            "alignment_positive": true,
            "reasoning_sufficient": true,
            "LEG": false,
            "LEG_subtype": null,
            "outcome_class": "interpretable_success",
            "artifact_id": "a1b2c3d4e5f6g7h8"
        },

        "ast_eval": {
            "status": "measured_correct",
            "ast_correct": true,
            "ast_score": 1.0,
            "reason": null,
            "artifact_id": "a1b2c3d4e5f6g7h8",
            "case_id": "stale_cache_a"
        },

        "reasoning_disagreement": {
            "disagreement": false,
            "type": "agreement",
            "classifier_correct": true,
            "oracle_correct": true
        },

        "reconstruction": { "...existing fields..." },

        "trajectory": [
            {
                "attempt": 0,
                "execution": {
                    "pass": false,
                    "score": 0.0,
                    "execution_category": "EXECUTION_FAILURE"
                },
                "oracle": {
                    "version": "inline_v1",
                    "status": "SUCCESS",
                    "reasoning_truth": "WRONG",
                    "oracle_correct": false,
                    "partial_mode": "lenient",
                    "justification": "...",
                    "error": null,
                    "latency_ms": 280,
                    "sampling_strategy": "ALWAYS",
                    "sampling_reason": null
                },
                "classifier": {
                    "mechanism_identified": "CORRECT",
                    "commitments_satisfied": "WRONG",
                    "reasoning_code_alignment": "WRONG",
                    "classifier_ran": true,
                    "error": null
                },
                "ast": {
                    "status": "measured_incorrect",
                    "ast_correct": false,
                    "ast_score": 0.0,
                    "reason": null
                },
                "reasoning_disagreement": {
                    "disagreement": true,
                    "type": "classifier_overcall",
                    "classifier_correct": true,
                    "oracle_correct": false
                },
                "parse_valid": true,
                "code_length": 450,
                "retry_mode": "retry_leg_critique_moderate_v2",
                "had_test_feedback": false,
                "had_classifier_hint": false,
                "mismatch_critique": "The code does not invalidate...",
                "mismatch_variant": "moderate",
                "mismatch_no_mismatch": false,
                "mismatch_truncated": false,
                "mismatch_prescriptive": false,
                "critique_skipped_missing_fields": false
            },
            {
                "attempt": 1,
                "execution": {
                    "pass": true,
                    "score": 1.0,
                    "execution_category": "EXECUTION_SUCCESS"
                },
                "oracle": {
                    "version": "inline_v1",
                    "status": "SUCCESS",
                    "reasoning_truth": "CORRECT",
                    "oracle_correct": true,
                    "partial_mode": "lenient",
                    "justification": "...",
                    "error": null,
                    "latency_ms": 310,
                    "sampling_strategy": "ALWAYS",
                    "sampling_reason": null
                },
                "classifier": {
                    "mechanism_identified": "CORRECT",
                    "commitments_satisfied": "CORRECT",
                    "reasoning_code_alignment": "CORRECT",
                    "classifier_ran": true,
                    "error": null
                },
                "ast": {
                    "status": "measured_correct",
                    "ast_correct": true,
                    "ast_score": 1.0,
                    "reason": null
                },
                "reasoning_disagreement": {
                    "disagreement": false,
                    "type": "agreement",
                    "classifier_correct": true,
                    "oracle_correct": true
                },
                "parse_valid": true,
                "code_length": 480,
                "retry_mode": "retry_leg_critique_moderate_v2",
                "had_test_feedback": false,
                "had_classifier_hint": false,
                "mismatch_critique": null,
                "mismatch_variant": "moderate",
                "mismatch_no_mismatch": false,
                "mismatch_truncated": false,
                "mismatch_prescriptive": false,
                "critique_skipped_missing_fields": false
            }
        ],

        "v2_parse_tiers": { "...existing fields..." },

        "num_attempts": 2,
        "retry_passed_at": 1,
        "retry_mode": "retry_leg_critique_moderate_v2"
    }
}
```

### Field semantics (complete)

| Field path | Type | Nullable | Allowed values | Semantics |
|------------|------|----------|---------------|-----------|
| `_schema_version` | str | No | "v3.1" | WAL schema version |
| `oracle.version` | str | No | "inline_v1" | Oracle evaluator implementation version |
| `oracle.status` | str | No | SUCCESS, FAILURE, SKIPPED, PARSE_ERROR, DISABLED, SAMPLING_SKIP | Whether oracle completed |
| `oracle.reasoning_truth` | str | No | CORRECT, PARTIAL, WRONG, UNJUDGABLE, UNASSESSED | Raw oracle label. UNASSESSED = not evaluated |
| `oracle.oracle_correct` | bool | Yes | true, false, null | Derived from reasoning_truth + partial_mode. null when UNASSESSED |
| `oracle.partial_mode` | str | No | "strict", "lenient" | Which mode was used for oracle_correct derivation |
| `oracle.justification` | str | No | free text (empty OK) | Oracle's reasoning |
| `oracle.error` | str | Yes | error description | null = no error |
| `oracle.latency_ms` | int | No | >= 0 | LLM call time |
| `oracle.sampling_strategy` | str | No | "ALWAYS", "FINAL_ONLY", etc. | Active sampling strategy |
| `oracle.sampling_reason` | str | Yes | explanation | null when oracle ran; explanation when skipped |
| `trajectory[k].execution.pass` | bool | No | true, false | Test pass/fail |
| `trajectory[k].execution.score` | float | No | 0.0-1.0 | Test score |
| `trajectory[k].execution.execution_category` | str | No | EXECUTION_SUCCESS, EXECUTION_FAILURE, etc. | Execution outcome |
| `trajectory[k].oracle.*` | dict | No | same as top-level oracle | Per-attempt oracle result |
| `trajectory[k].classifier.mechanism_identified` | str | Yes | CORRECT, PARTIAL, WRONG, null | Per-attempt classifier mechanism |
| `trajectory[k].classifier.commitments_satisfied` | str | Yes | CORRECT, PARTIAL, WRONG, null | Per-attempt classifier commitments |
| `trajectory[k].classifier.reasoning_code_alignment` | str | Yes | CORRECT, PARTIAL, WRONG, null | Per-attempt classifier alignment |
| `trajectory[k].classifier.classifier_ran` | bool | No | true, false | Whether classifier completed |
| `trajectory[k].classifier.error` | str | Yes | error description | null = no error |
| `trajectory[k].ast.status` | str | No | measured_correct, measured_incorrect, not_measurable, no_spec | AST check result |
| `trajectory[k].ast.ast_correct` | bool | Yes | true, false, null | null when not measurable |
| `trajectory[k].ast.ast_score` | float | Yes | 0.0, 1.0, null | null when not measurable |
| `trajectory[k].reasoning_disagreement.disagreement` | bool | Yes | true, false, null | null = one signal unavailable |
| `trajectory[k].reasoning_disagreement.type` | str | No | agreement, classifier_overcall, classifier_undercall, oracle_not_available, classifier_not_available | Disagreement category |
| `trajectory[k].reasoning_disagreement.classifier_correct` | bool | Yes | true, false, null | null when classifier didn't run |
| `trajectory[k].reasoning_disagreement.oracle_correct` | bool | Yes | true, false, null | null when oracle not assessed |

---

## 11. Schema Versioning

### `_schema_version: "v3.1"`

```json
{
    "_schema_version": "v3.1",
    "payload": { ... }
}
```

### Version history

| Version | Description | Breaking? |
|---------|-------------|-----------|
| v2 (implicit) | Original v2 WAL format. No evaluation/ast_eval/oracle sections. | -- |
| v3.0 | Added payload.evaluation, payload.ast_eval, payload.classification, payload.reconstruction | Non-breaking (additive) |
| **v3.1** | **Added payload.oracle, trajectory[].oracle, trajectory[].classifier, trajectory[].ast, trajectory[].reasoning_disagreement, payload.reasoning_disagreement, payload._schema_version** | **Non-breaking (additive)** |

### `oracle.version: "inline_v1"`

Tracks the oracle evaluator implementation version. Changes to the oracle prompt text, model, or parsing logic increment this. Analysis scripts can filter by oracle version for consistency.

---

## 12. Backward Compatibility

### Old WAL records (v2, v3.0)

| Missing field | Default behavior |
|--------------|-----------------|
| `_schema_version` absent | Treat as "v2" |
| `payload.oracle` absent | `oracle_coverage_status = "not_present_legacy"` |
| `trajectory[k].oracle` absent | Per-attempt oracle = UNASSESSED |
| `trajectory[k].classifier` absent | Per-attempt classifier = not available |
| `trajectory[k].ast` absent | Per-attempt AST = not available |
| `trajectory[k].reasoning_disagreement` absent | Per-attempt disagreement = null |
| `reasoning_disagreement` absent | Top-level disagreement = null |

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

### No migration needed

Old WAL files are never rewritten. The schema addition is purely additive.

---

## 13. No-Leakage Enforcement

### Structural enforcement

The `_run_oracle_evaluation()` function signature:

```python
def _run_oracle_evaluation(
    raw_root_cause: str,
    raw_fix_strategy: str,
    case: dict,
    config,
) -> dict:
    """Run oracle reasoning evaluation.

    NO LEAKAGE CONTRACT: This function must NEVER receive or access:
    - execution results (exec_result, passed, score)
    - classifier results (mechanism_identified, etc.)
    - reconstructed/generated code
    - AST evaluation results
    - normalized reasoning text
    It evaluates ONLY the model's RAW stated reasoning against ground truth.
    """
```

### Call site enforcement (baseline path)

```python
# Step 5a: extract raw fields from parsed JSON
fj = parsed_gen.full_json or {}
raw_rc = fj.get("root_cause", "")
raw_fs = fj.get("fix_strategy", "")

# Step 5b: oracle runs HERE — before normalize, execute, classify
oracle_result = _run_oracle_evaluation(raw_rc, raw_fs, case, config)

# Step 6: normalize (oracle already done)
artifact = normalize_generation_v2(parsed_gen, case, condition)

# Step 7: execute (oracle already done)
recon, code, exec_result = _reconstruct_and_execute(...)

# Step 8: classify (oracle already done)
classifier_result = _classify_reasoning(...)
```

Oracle runs at step 5b. `exec_result` doesn't exist until step 7. `classifier_result` doesn't exist until step 8. Leakage is impossible by construction.

### Call site enforcement (retry path)

Same pattern inside the loop: oracle runs after parsing, before normalize/execute/classify.

---

## 14. `_run_oracle_evaluation` Implementation

```python
def _run_oracle_evaluation(raw_root_cause, raw_fix_strategy, case, config):
    """Run oracle reasoning evaluation inline.

    NO LEAKAGE CONTRACT: see docstring above.
    Returns dict with: version, status, reasoning_truth, oracle_correct,
    partial_mode, justification, error, latency_ms, sampling_strategy, sampling_reason.
    """
    from core.evaluation.oracle_eval.reasoning_truth import (
        build_oracle_spec, load_buggy_code, render_prompt,
        parse_response, is_unjudgable,
    )
    from core.pipeline.llm import call_model
    import time

    oracle_cfg = config.oracle if hasattr(config, 'oracle') else None
    partial_mode = getattr(oracle_cfg, 'partial_mode', 'lenient') if oracle_cfg else 'lenient'
    sampling_strategy = getattr(oracle_cfg, 'sampling_strategy', 'ALWAYS') if oracle_cfg else 'ALWAYS'
    timeout = getattr(oracle_cfg, 'timeout', 30) if oracle_cfg else 30

    base = {
        "version": "inline_v1",
        "partial_mode": partial_mode,
        "sampling_strategy": sampling_strategy,
        "sampling_reason": None,
    }

    # Check if oracle is disabled
    if oracle_cfg and not getattr(oracle_cfg, 'inline_enabled', True):
        return {**base, "status": "DISABLED", "reasoning_truth": "UNASSESSED",
                "oracle_correct": None, "justification": "", "error": None, "latency_ms": 0}

    # Pre-filter
    if is_unjudgable(raw_root_cause, raw_fix_strategy):
        return {**base, "status": "SKIPPED", "reasoning_truth": "UNASSESSED",
                "oracle_correct": None, "justification": "", "error": "pre_filter",
                "latency_ms": 0}

    oracle_spec = build_oracle_spec(case)
    buggy_code = load_buggy_code(case, str(Path(__file__).resolve().parent.parent.parent))
    prompt = render_prompt(oracle_spec, raw_root_cause, raw_fix_strategy, buggy_code)

    t0 = time.monotonic()
    try:
        cr = call_model(
            prompt,
            model=getattr(oracle_cfg, 'model', config.models.evaluator.name) if oracle_cfg else config.models.evaluator.name,
            raw=True, logger=None, phase="oracle_eval",
            timeout=timeout,
        )
        raw_resp = cr.response
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        return {**base, "status": "FAILURE", "reasoning_truth": "UNASSESSED",
                "oracle_correct": None, "justification": "", "error": str(e)[:200],
                "latency_ms": elapsed}

    elapsed = int((time.monotonic() - t0) * 1000)
    label, justification, err = parse_response(raw_resp)

    if err is not None:
        return {**base, "status": "PARSE_ERROR", "reasoning_truth": label,
                "oracle_correct": None, "justification": justification,
                "error": err, "latency_ms": elapsed}

    # Derive oracle_correct based on partial_mode
    if partial_mode == "strict":
        oracle_correct = (label == "CORRECT")
    else:
        oracle_correct = label in ("CORRECT", "PARTIAL")

    return {**base, "status": "SUCCESS", "reasoning_truth": label,
            "oracle_correct": oracle_correct, "justification": justification,
            "error": None, "latency_ms": elapsed}
```

---

## 15. Config Schema Extension

```yaml
# Added to default.yaml:

oracle:
  inline_enabled: true
  model: "gpt-5-mini"
  timeout: 30
  partial_mode: "lenient"        # "strict" | "lenient"
  sampling_strategy: "ALWAYS"    # "ALWAYS" | "FINAL_ONLY" | "FIRST_K(n)" | "RANDOM_SAMPLE(p)"
```

---

## 16. Dashboard Schema Extension

New fields in `dashboard/schema.py` FIELD_REGISTRY:

```python
# ── V3.1 ORACLE ──
"oracle_status": {
    "source": "payload.oracle.status",
    "type": "str",
    "required": False,
},
"oracle_reasoning_truth": {
    "source": "payload.oracle.reasoning_truth",
    "type": "str",
    "required": False,
},
"oracle_correct": {
    "source": "payload.oracle.oracle_correct",
    "type": "bool",
    "required": False,
},
"oracle_partial_mode": {
    "source": "payload.oracle.partial_mode",
    "type": "str",
    "required": False,
},
"oracle_justification": {
    "source": "payload.oracle.justification",
    "type": "str",
    "required": False,
},
"oracle_version": {
    "source": "payload.oracle.version",
    "type": "str",
    "required": False,
},
"oracle_latency_ms": {
    "source": "payload.oracle.latency_ms",
    "type": "int",
    "required": False,
},
"oracle_sampling_strategy": {
    "source": "payload.oracle.sampling_strategy",
    "type": "str",
    "required": False,
},

# ── V3.1 DISAGREEMENT ──
"reasoning_disagreement": {
    "source": "payload.reasoning_disagreement.disagreement",
    "type": "bool",
    "required": False,
},
"reasoning_disagreement_type": {
    "source": "payload.reasoning_disagreement.type",
    "type": "str",
    "required": False,
},
```

---

## 17. Dashboard Oracle Tab Behavior

1. If `payload.oracle.reasoning_truth` exists and is not UNASSESSED -> display inline oracle data
2. If absent -> check sidebar oracle labels -> display if available
3. If neither -> show classifier reasoning with note: "No oracle evaluation available. Showing classifier-based reasoning."
4. Display source indicator: "Source: inline oracle v1" or "Source: offline oracle labels" or "Source: classifier (no oracle)"

### New sections when inline oracle is available:

- Oracle verdict distribution (bar chart)
- Oracle accuracy by model, condition, family
- Disagreement rate overall and by model
- Disagreement evolution across retry attempts (line chart: attempt vs disagreement rate)
- Per-attempt oracle trajectory (expandable per-case)

---

## 18. Validation Plan

### A. Per-attempt alignment check

1. For a v3.1 retry run, verify every `trajectory[k]` has all 5 sub-objects: execution, oracle, classifier, ast, reasoning_disagreement
2. Verify no trajectory entry has missing or null top-level keys
3. Check that attempt indices are sequential (0, 1, 2, ...)

### B. Oracle input integrity check

1. For 50 events, compare `payload.oracle` inputs (from WAL logging) against `parsed_gen.full_json["root_cause"]`
2. Verify they are character-for-character identical
3. Verify `normalized_root_cause` differs from `raw_root_cause` in at least some cases (proves normalization is active but oracle doesn't use it)

### C. Classifier-oracle disagreement analysis

1. Compute overall disagreement rate (expected: ~7-10%)
2. Stratify by case family — identify families where classifier overcalls most
3. Compare with offline oracle results for consistency

### D. Coverage validation

1. Compute `oracle.status` distribution across a full ablation
2. Expected: ~95% SUCCESS, ~5% SKIPPED (parse failures)
3. If >10% SKIPPED -> investigate reasoning extraction

### E. Retry consistency

1. For retry chains, check: does oracle verdict improve across attempts?
2. Check: does disagreement rate decrease across attempts?
3. If oracle is inconsistent across attempts with identical reasoning -> oracle is noisy

### F. Inline vs offline comparison

1. Run offline oracle on 200 events from a v3.1 run
2. Compare with inline oracle labels
3. Expected: >99% agreement
4. If <95% -> implementation bug

### G. Atomicity check

1. For every `case.end` event in v3.1 runs, verify `oracle` section exists
2. Verify `classification` section exists
3. Verify `ast_eval` section exists
4. Verify every trajectory entry has all 5 sub-objects
5. Zero missing fields allowed

### H. PARTIAL mode check

1. Run one ablation with `partial_mode: "strict"`, one with `partial_mode: "lenient"`
2. Verify `oracle_correct` differs for PARTIAL cases
3. Verify raw `reasoning_truth` is identical between both runs (same oracle prompt)

### I. Sampling strategy check

1. Run small ablation with `sampling_strategy: "FIRST_K(2)"`
2. Verify attempts 0 and 1 have `oracle.status: "SUCCESS"`
3. Verify attempts 2+ have `oracle.status: "SAMPLING_SKIP"`

---

## 19. Rollout Plan

### Phase 0: Audit (0.5 day)
**Goal:** Confirm integration points, verify oracle import paths, verify `parsed_gen.full_json` availability timing.
**Files:** Read `execution_v2.py`, `retry_v2.py`, `reasoning_truth.py`, `reasoning_v2.py`
**Exit criteria:** Integration points confirmed. Raw field availability verified at step 5a.

### Phase 1: Schema + config (0.5 day)
**Goal:** Add `_schema_version`, oracle config section, dashboard schema fields.
**Files:** `dashboard/schema.py`, `core/config/config_storage/default.yaml`, `dashboard/data/evaluation_fields.py`
**Exit criteria:** Dashboard reads (empty) oracle fields without crash. Config parses oracle section.

### Phase 2: Inline oracle in baseline path (1 day)
**Goal:** `_run_oracle_evaluation()` in `execution_v2.py`, `payload.oracle` + `payload.reasoning_disagreement` in event.
**Files:** `core/pipeline/orchestration/execution_v2.py`
**Exit criteria:** WAL events from baseline run contain `payload.oracle` with valid labels.

### Phase 3: Per-attempt axes in retry path (1.5 days)
**Goal:** Oracle + classifier + AST per-attempt in `retry_v2.py` trajectory entries.
**Files:** `core/pipeline/orchestration/retry_v2.py`
**Key changes:**
- Move `normalize_generation_v2` into the loop (per-attempt)
- Move classifier call into the loop (per-attempt)
- Add oracle call into the loop (per-attempt, before normalize)
- Add AST call into the loop (per-attempt, after reconstruct)
- Add disagreement computation per-attempt
- Restructure trajectory entry to include all 5 sub-objects
**Exit criteria:** Every trajectory entry contains execution, oracle, classifier, ast, reasoning_disagreement.

### Phase 4: Sampling strategy + PARTIAL mode (0.5 day)
**Goal:** Implement `oracle.sampling_strategy` and `oracle.partial_mode` config keys.
**Files:** `execution_v2.py`, `retry_v2.py`, config
**Exit criteria:** FIRST_K and FINAL_ONLY strategies work correctly. Strict vs lenient produce different `oracle_correct` values.

### Phase 5: Dashboard update (1 day)
**Goal:** Oracle tab shows inline oracle + disagreement + per-attempt trajectory.
**Files:** `dashboard/views/oracle.py`, `dashboard/data/evaluation_fields.py`, `dashboard/schema.py`, `dashboard/leg_scanner.py`
**Exit criteria:** Dashboard shows inline oracle data without sidebar checkbox. Disagreement section works.

### Phase 6: Validation (0.5 day)
**Goal:** Run all validation checks from Section 18.
**Exit criteria:** All checks pass.

### Phase 7: Documentation + legacy handling (0.5 day)
**Goal:** Update docs, mark offline script as legacy.
**Files:** `CLAUDE_RULES/`, `CLAUDE.md`, `scripts/run_oracle_eval.py`
**Exit criteria:** New runs never need offline oracle. Old runs still work.

**Total: ~6 days**

---

## 20. Concrete Next-Step Checklist

- [ ] Add `oracle` section to `core/config/config_storage/default.yaml`
- [ ] Add `_schema_version: "v3.1"` to event assembly in `execution_v2.py`
- [ ] Implement `_run_oracle_evaluation()` in `execution_v2.py` with raw-field-only signature
- [ ] Call it at step 5b (after parse, before normalize) in baseline path
- [ ] Add `oracle_result` parameter to `_assemble_result()`
- [ ] Include `payload.oracle` and `payload.reasoning_disagreement` in assembled event
- [ ] Move `normalize_generation_v2()` into retry loop (per-attempt)
- [ ] Move classifier call into retry loop (per-attempt)
- [ ] Add oracle call into retry loop (per-attempt, before normalize)
- [ ] Add AST call into retry loop (per-attempt, after reconstruct)
- [ ] Implement per-attempt disagreement computation
- [ ] Restructure trajectory entries to include all 5 sub-objects
- [ ] Implement `_parse_sampling_strategy()` and sampling skip behavior
- [ ] Implement PARTIAL mode logic in oracle result derivation
- [ ] Add oracle + disagreement fields to `dashboard/schema.py` FIELD_REGISTRY
- [ ] Update `dashboard/leg_scanner.py` trajectory expansion to extract per-attempt axes
- [ ] Update `dashboard/data/evaluation_fields.py` to read inline oracle
- [ ] Update `dashboard/views/oracle.py` to display inline oracle and disagreement
- [ ] Run end-to-end test: baseline with oracle enabled
- [ ] Run end-to-end test: retry with per-attempt oracle + classifier + AST
- [ ] Run 200-event inline vs offline comparison
- [ ] Test PARTIAL mode strict vs lenient
- [ ] Test sampling strategies FIRST_K and FINAL_ONLY
- [ ] Verify backward compat on old v2 WAL
