# AST-Based Code Measurement — Design Document v1

**Date:** 2026-04-03
**Status:** PLAN — awaiting approval
**Author:** Design review document for CS372 T3 benchmark

---

## 1. Executive Summary

This document proposes adding AST-based structural measurement of generated code to the T3 evaluation pipeline. The goal: for each model output, determine programmatically whether the model produced the correct structural transformation, independent of whether the code executes successfully.

The project currently measures reasoning correctness via LLM-based evaluation (the LEG evaluator's blind verdict + classifier), and execution correctness via subprocess-based invariant tests. The LEG metric bridges these: mechanism_correct AND NOT passed. The problem is that the "mechanism_correct" signal comes from an LLM judge, which is noisy, expensive, and not reproducible across evaluator models.

AST measurement adds a third signal: did the model's code contain the correct structural pattern? This is deterministic, zero-cost, and reproducible. It does not replace execution evaluation (which remains behavioral ground truth) or reasoning evaluation (which captures intent). It provides an objective middle layer: structural correctness of the code artifact itself.

**Assessment: Is this worth doing?** Yes, but narrowly. AST measurement materially strengthens two specific claims: (1) it provides a cleaner LEG signal by replacing the LLM judge's "mechanism_correct" with a deterministic check, and (2) it enables a new analysis class — cases where the code has the right structure but fails execution due to assembly/reconstruction artifacts versus cases where the structure itself is wrong. The smallest useful implementation covers ~35 of 58 original cases (the single-file, single-function-fix families) and requires roughly 2-3 days of engineering. It does NOT strengthen claims about model reasoning per se — it measures code structure, which is a proxy for reasoning but not reasoning itself.

---

## 2. Current System Audit

### Pipeline Flow (inspected in codebase)

```
Model prompt → LLM generation → parse_model_response() [parse.py]
  → reconstruct_strict() [reconstructor.py] or assemble() [code_assembly.py]
  → exec_canonical() [exec_canonical.py] — subprocess execution + invariant tests
  → evaluate_reasoning() [leg_evaluator.py] — LLM-based blind verdict + classifier
  → logging [logging_core.py] — canonical event schema v7
```

### Key Files Inspected

| File | Role | AST already used? |
|---|---|---|
| `pipeline/parsing/parse.py` | Extract code from model response | No |
| `pipeline/code_assembly.py` | Assemble multi-file code, rewrite imports | **Yes** — `_collect_import_info()`, `_NameRewriter`, `_ImportRemover`, `ast.unparse()` |
| `pipeline/execution/exec_canonical.py` | Subprocess execution + test | No |
| `orchestration/leg_evaluator.py` | LLM reasoning evaluation | No |
| `logging_/logging_core.py` | Event emission (schema v7) | No |
| `scripts/ast_mutator.py` | Case generation via AST mutation | **Yes** — full 3-layer system |
| `core/registry/condition_registry.py` | Condition compatibility | No |

### Current Reasoning Evaluation (from `leg_evaluator.py`)

```python
compute_leg_true(entry) → bool:
    entry["pass"] is False
    AND entry["llm_eval_blind_verdict"] == "YES"
    AND blind-inferred failure type == classifier-detected type
    AND type != "UNKNOWN"
```

This depends on: (1) an LLM evaluator call, (2) a classifier call, (3) agreement between them. The evaluator receives code, error messages, and reasoning text — all potentially truncated (fixed in commit 9175515b). The signal is LLM-dependent, non-reproducible across evaluator model versions, and costs ~$0.01 per evaluation.

### What `ast_mutator.py` Already Provides

The existing AST mutator has a mature 3-layer architecture that is directly invertible for measurement:

- **Layer 1 (SemanticTarget):** Identifies invariant-relevant nodes — `.copy()` calls, method calls, default parameters, branch structures, break statements
- **Layer 2 (Finders):** `find_copy_calls()`, `find_method_calls()`, `find_default_params()`, `find_comparisons()`, etc.
- **Layer 3 (Transformers):** `_RemoveCopy`, `_DeleteStatement`, `_RestoreMutableDefault`, `_RemoveBranch`, etc.

The mutator breaks invariants; AST measurement checks whether they're restored. The finder functions are directly reusable.

### Current Reconstruction/Strict Mode

The V2 pipeline has strict reconstruction (`reconstruct_strict()`) that returns status SUCCESS or various failure codes. When reconstruction fails, `exec_canonical()` returns early with RECONSTRUCTION_FAILURE and score 0.0. The LEG effect report found that **6 of 31 significant deltas were reconstruction artifacts** — apparent effects that disappeared when conditioning on successful code extraction.

AST measurement must handle this: it should operate on the reconstructed code when available, and emit a separate "not measurable" status when reconstruction fails.

---

## 3. Why AST Measurement Is Valuable In This Project

### 3.1 The LEG Evaluator Problem

The current `compute_leg_true()` depends on an LLM judge agreeing with a classifier about mechanism correctness. This has three problems:

1. **Non-reproducible.** Changing the evaluator model (gpt-5-mini → gpt-5) changes the LEG rate. The LEG effect report was run specifically with gpt-5-mini as evaluator; prior runs with different evaluators gave different LEG rates.

2. **Expensive.** Each evaluation requires an LLM call (~$0.01). At 33,000+ events, this is $330+ just for classification.

3. **Noisy.** The report found that the classifier truncation bug (fixed March 29) distorted multi-file LEG rate judgments. Even after the fix, the evaluator operates on extracted text, not code structure.

AST measurement provides a deterministic, zero-cost, reproducible alternative for the "mechanism correct" signal on cases where the fix is structurally characterizable.

### 3.2 Reconstruction Artifact Decomposition

The LEG effect report identified that strict vs. recon-only conditioning changes results dramatically (e.g., `stale_cache_a` with 4o-mini: -48pp strict delta, +0pp recon-only delta). AST measurement enables a finer decomposition:

- **Reconstruction failed:** code not extractable → not measurable
- **Reconstruction succeeded, AST wrong:** code extracted but wrong structure → genuine structural failure
- **Reconstruction succeeded, AST correct, execution failed:** correct structure but runtime failure → assembly/environment artifact
- **Reconstruction succeeded, AST correct, execution passed:** clean success

This is strictly more informative than the current binary (recon ok / not ok) conditioning.

### 3.3 What Claims It Strengthens

1. **LEG as a real phenomenon, not an evaluator artifact.** If AST-measured structural correctness correlates with LLM-evaluated mechanism correctness, it validates the evaluator. If they diverge, it identifies where the evaluator is noisy.

2. **Reconstruction artifact isolation.** Currently the report conditions on recon_ok (a boolean). AST measurement enables conditioning on structural correctness, which is strictly more informative.

3. **Intervention mechanism.** If critique/reasoning-only interventions change AST correctness rates (not just pass rates), that proves the intervention affects code structure, not just surface formatting.

### 3.4 What Claims It Does NOT Strengthen

- **Whether models "reason" correctly internally.** AST measures code output, not internal reasoning. A model could produce correct code through pattern matching without genuine causal understanding.
- **Financial performance correlation.** The final report shows CRIT reasoning metrics don't predict financial returns. AST measurement in the code benchmark is orthogonal to this.
- **Claims about reasoning quality beyond code.** AST is specific to code generation tasks.

---

## 4. What AST Can Reliably Measure

For this benchmark, AST can reliably detect:

| Pattern Class | Example Cases | Detection Method |
|---|---|---|
| **Added method call** | `alias_config_a` (`.copy()`), `stale_cache_a` (`_cache.pop()`) | Check for Call node with specific attribute/function name |
| **Changed default parameter** | `mutable_default_b` (`set()` → `None`) | Compare FunctionDef.args.defaults |
| **Added branch** | `use_before_set_b` (else clause) | Check If.orelse is non-empty |
| **Added statement in loop** | `effect_order_b` (`emit_event` inside for) | Check For.body contains target call |
| **Added break** | `retry_dup_b` (break after send) | Check Try.body contains Break |
| **Added try-except wrapper** | `invariant_partial_fail` | Check target statements are inside Try |
| **Changed function call name** | `hidden_dep_multihop` (`refresh_user_snapshot` → `sync_user_to_cache`) | Check Call.func name |
| **Added None guard** | `mutable_default_*` | Check for `if X is None: X = ...` pattern |
| **Added cache write-back** | `cache_bypass_attractor` | Check for assignment to cache dict after fetch |
| **Changed sort direction** | `test_authority_conflict` | Check for `reverse=True` keyword |

These patterns cover ~40 of 65 active cases. They are the "AST-measurable" subset.

---

## 5. What AST Cannot Reliably Measure

| Limitation | Example | Why |
|---|---|---|
| **Semantic equivalence** | `dict(DEFAULTS)` vs `DEFAULTS.copy()` vs `{**DEFAULTS}` — all correct for alias_config | Different AST structures, same semantics. Requires listing equivalent patterns. |
| **Cross-file invariants** | `hidden_dep_multihop`: fix in user_service.py affects cache_reader.py behavior | AST sees local structure, not runtime data flow. |
| **Runtime ordering** | `false_fix_deadlock`: lock acquisition order matters | AST sees statement sequence, not execution order under concurrency. |
| **Partial correctness gradients** | A fix that adds 2 of 3 required statements | Binary "pattern present / absent" misses partial credit. Addressable with graded scoring. |
| **Intent behind code** | Model adds `.copy()` for the wrong reason | AST confirms structure, not understanding. |
| **Novel correct fixes** | Model uses a contextmanager instead of try-except for `invariant_partial_fail` | Unanticipated patterns require explicit alternatives or give false negatives. |

---

## 6. Proposed Evaluation Model

### Three-Signal Architecture

```
                          ┌─────────────────┐
Model output ──→ Parse ──→│ AST Measurement  │──→ ast_correct: bool
                          │ (deterministic)  │    ast_score: float [0,1]
                          └────────┬────────┘    ast_patterns_matched: list
                                   │
                          ┌────────▼────────┐
                     ──→  │ Execution Eval   │──→ passed: bool
                          │ (subprocess)     │    score: float
                          └────────┬────────┘
                                   │
                          ┌────────▼────────┐
                     ──→  │ Reasoning Eval   │──→ mechanism_correct: bool (LLM)
                          │ (LLM judge)      │    failure_type: str
                          └─────────────────┘
```

All three signals are preserved. AST measurement runs between parsing/reconstruction and execution. It consumes the reconstructed code (same artifact that execution receives). It is fast (milliseconds), deterministic, and logged alongside execution and reasoning results.

### Signal Hierarchy

1. **Execution** (behavioral ground truth) — did the code pass invariant tests?
2. **AST** (structural ground truth) — does the code contain the correct fix pattern?
3. **Reasoning** (intent signal, LLM-based) — did the model articulate correct understanding?

Execution is authoritative. AST is objective but may have false negatives (novel correct fixes). Reasoning is subjective but captures intent.

---

## 7. Revised Definitions of LEG / Lucky Fix / Success / Failure

### Current Definitions

| Metric | Current Definition |
|---|---|
| Success | `passed == True` |
| LEG | `mechanism_correct AND NOT passed` (LLM-based mechanism_correct) |
| Lucky fix | `passed AND NOT mechanism_correct` |
| Failure | `NOT passed AND NOT mechanism_correct` |

### Proposed Additions (NOT replacements)

| Metric | Definition | Signal Source |
|---|---|---|
| `ast_correct` | Code contains required structural fix pattern | AST measurement |
| `ast_score` | Fraction of required patterns matched (0.0 to 1.0) | AST measurement |
| `LEG_ast` | `ast_correct AND NOT passed` | AST + execution |
| `lucky_fix_ast` | `passed AND NOT ast_correct` | AST + execution |
| `LEG_llm` | Original `mechanism_correct AND NOT passed` | LLM + execution (renamed for clarity) |
| `ast_llm_agreement` | `ast_correct == mechanism_correct` | Both |
| `ast_recon_artifact` | `ast_correct AND NOT passed AND recon_ok` | AST + execution + reconstruction |

### Naming Convention

- `LEG_ast` — AST-based LEG (deterministic)
- `LEG_llm` — LLM-based LEG (original metric, renamed)
- `LEG_combined` — `ast_correct AND mechanism_correct AND NOT passed` (both agree)

The paper should report both `LEG_ast` and `LEG_llm` side by side. If they agree on >90% of cases, AST can be promoted to primary. If they disagree substantially, the disagreement itself is an interesting finding.

---

## 8. Canonical AST Target Representation

For each AST-measurable case, define a **fix pattern spec** — a declarative description of what the correct code should structurally contain.

### Schema

```python
@dataclass
class FixPattern:
    """One structural pattern that the correct fix must contain."""
    pattern_type: str       # "added_call", "changed_default", "added_branch", etc.
    target_function: str    # function where pattern should appear
    target_file: str | None # for multi-file cases; None = any file
    required: bool          # True = must be present; False = bonus
    description: str        # human-readable

@dataclass
class ForbiddenPattern:
    """A pattern that must NOT appear in correct code."""
    pattern_type: str
    target_function: str
    target_file: str | None
    description: str

@dataclass
class ASTSpec:
    """Complete AST specification for one case."""
    case_id: str
    ast_measurable: bool            # False = skip AST eval for this case
    required_patterns: list[FixPattern]
    forbidden_patterns: list[ForbiddenPattern]
    alternative_patterns: list[list[FixPattern]]  # OR-groups: any one group suffices
    matching_scope: str             # "function" | "file" | "cross_file"
    notes: str                      # limitations, known false negatives
```

### Example: `alias_config_a`

```python
ASTSpec(
    case_id="alias_config_a",
    ast_measurable=True,
    required_patterns=[
        FixPattern(
            pattern_type="copy_call_on_assignment",
            target_function="create_config",
            target_file=None,
            required=True,
            description="config = DEFAULTS.copy() instead of config = DEFAULTS",
        ),
    ],
    forbidden_patterns=[],
    alternative_patterns=[
        [FixPattern(pattern_type="dict_constructor", target_function="create_config",
                    target_file=None, required=True,
                    description="config = dict(DEFAULTS)")],
        [FixPattern(pattern_type="dict_unpacking", target_function="create_config",
                    target_file=None, required=True,
                    description="config = {**DEFAULTS}")],
    ],
    matching_scope="function",
    notes="Three structurally distinct correct fixes exist. All must be accepted.",
)
```

---

## 9. Case Schema Changes

### Recommendation: Separate File, Not In cases_v2.json

**Rationale:**
- `cases_v2.json` is used by the runner, orchestrator, and multiple analysis scripts. Adding AST specs bloats it and risks breaking consumers.
- AST specs are evaluation metadata, not case definitions. They change independently (as we refine patterns) without requiring re-validation of cases.
- A separate file allows incremental coverage: cases without specs are simply `ast_measurable: false`.

**Proposed file:** `ast_specs.json`

```json
{
  "schema_version": "1.0",
  "specs": {
    "alias_config_a": {
      "ast_measurable": true,
      "matching_scope": "function",
      "required_patterns": [...],
      "forbidden_patterns": [...],
      "alternative_patterns": [...],
      "notes": "..."
    },
    "async_race_lock": {
      "ast_measurable": true,
      "matching_scope": "function",
      "required_patterns": [...],
      ...
    },
    "false_fix_deadlock": {
      "ast_measurable": false,
      "notes": "Fix involves nested function restructuring; too complex for pattern matching"
    }
  }
}
```

**Link to cases_v2.json:** Add one field to each case entry:

```json
"ast_spec": "ast_specs.json"
```

This is a pointer, not the spec itself. Analysis scripts that don't need AST specs ignore it.

---

## 10. AST Pattern Specification Design

### Pattern Types (mapped to project's case families)

| Pattern Type | Detection Logic | Cases |
|---|---|---|
| `copy_call_on_assignment` | Assignment RHS is `X.copy()` or `dict(X)` or `{**X}` | alias_config_a/b/c |
| `cache_invalidation_call` | `_cache.pop(key)` or `del _cache[key]` or `_cache.clear()` after update | stale_cache_a/b/c |
| `none_guard_for_default` | `if X is None: X = <constructor>()` at function start | mutable_default_a/b/c |
| `statement_in_loop` | Specific Call node is child of For/While body, not sibling | effect_order_a/b/c |
| `else_branch_added` | If.orelse is non-empty and contains target assignments | use_before_set_a/b/c |
| `break_after_success` | Break node in Try.body after successful operation | retry_dup_a/b/c |
| `try_except_wrapper` | Target statements wrapped in Try with except handler | invariant_partial_fail |
| `function_call_renamed` | Call to function X replaced with call to function Y | hidden_dep_multihop |
| `added_statement_before_return` | New Expr/Assign statement added before Return in function | stale_cache, partial_update |
| `nested_if_added` | If node added inside existing If branch body | partial_update_c |
| `assignment_in_both_branches` | Target variable assigned in both if-body and else-body | use_before_set |
| `removed_global_assignment` | Module-level assignment removed | lazy_init_b/c |
| `dispatch_table_entry_changed` | Dict literal value changed for specific key | dispatch_handler_trap |
| `raise_instead_of_return_none` | Raise statement replaces `return None` or bare return | caller_null_check |
| `reset_moved_before_loop` | `reset()` call moved from inside for-body to before for | shared_counter_ambiguous |
| `dict_mutate_inplace` | `_config.clear(); _config.update()` instead of `_config = ...` | stale_config_reload |
| `co_effects_present` | Multiple specific statements all present in same function | incomplete_state_sync, partial_migration |

### Matching Policy Per Pattern

Each pattern has:
- **Strictness:** `exact_node` (must match AST node type precisely) vs `semantic_class` (accepts equivalent alternatives)
- **Location sensitivity:** `specific_function` (must be in named function) vs `any_scope` (anywhere in file)
- **Order sensitivity:** `ordered` (must appear in sequence) vs `unordered` (just must all be present)

---

## 11. Matching Strategy: Exact AST vs Pattern-Based Detection

### Why Exact AST Equality Fails

Given buggy `config.py` and reference fix `reference_fixes/alias_config_a.py`, one could diff their ASTs. This fails because:

1. **Multiple valid fixes.** `DEFAULTS.copy()`, `dict(DEFAULTS)`, `{**DEFAULTS}` are all correct but have different ASTs.
2. **Irrelevant differences.** Model may rename variables, add comments, reorder functions, add type hints.
3. **Partial fixes.** Model may fix the target function correctly but also change other functions.

### Recommended Strategy: Pattern-Based Detection

Instead of comparing whole ASTs, check for the presence or absence of specific structural patterns:

```python
def check_pattern(code: str, spec: ASTSpec) -> ASTResult:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ASTResult(measurable=False, reason="syntax_error")

    matched = []
    missing = []

    for pattern in spec.required_patterns:
        if detect_pattern(tree, pattern):
            matched.append(pattern)
        else:
            missing.append(pattern)

    # Check alternatives
    alt_satisfied = False
    if not missing and not spec.alternative_patterns:
        alt_satisfied = True
    for alt_group in spec.alternative_patterns:
        if all(detect_pattern(tree, p) for p in alt_group):
            alt_satisfied = True
            break

    # Check forbidden
    violations = []
    for fp in spec.forbidden_patterns:
        if detect_pattern(tree, fp):
            violations.append(fp)

    ast_correct = (not missing or alt_satisfied) and not violations
    ast_score = len(matched) / max(len(spec.required_patterns), 1)

    return ASTResult(
        measurable=True,
        ast_correct=ast_correct,
        ast_score=ast_score,
        patterns_matched=matched,
        patterns_missing=missing,
        forbidden_violations=violations,
        alt_satisfied=alt_satisfied,
    )
```

### Detection Functions (reuse from ast_mutator.py)

The `find_copy_calls()`, `find_method_calls()`, `find_default_params()`, etc. from `scripts/ast_mutator.py` are directly reusable. The mutator finds these patterns to break them; the measurement finds them to verify they're restored.

---

## 12. Multi-File and Cross-Boundary Cases

### The Problem

9 of 58 original cases are multi-file. The reference fix may involve changing one file while leaving others intact. The model's output may be a single file, multiple files, or a combined code block.

### Strategy

1. **Per-file matching.** Parse each file in the model's output separately. Apply AST specs to the file indicated by `target_file` in the pattern.

2. **File identification.** The reconstruction pipeline (`reconstruct_strict()`) already maps model output to canonical file names. Use the same mapping.

3. **Cross-file aggregation.** If a case's spec has patterns across files, all must match. `ast_correct` is the conjunction.

4. **Single-file model output for multi-file case.** If the model only outputs one file, patterns targeting other files check the original (unmodified) code. Missing modifications in un-output files → those patterns fail.

### Example: `hidden_dep_multihop`

Spec requires:
- In `user_service.py`: call to `sync_user_to_cache` instead of `refresh_user_snapshot` in `save_user()`
- In `user_service.py`: call to `sync_user_to_cache` instead of `refresh_user_snapshot` in `rename_user()`

If model outputs only `user_service.py` with correct changes → ast_correct = True (other files don't need changes).

If model outputs `cache_writer.py` with changes but not `user_service.py` → ast_correct = False (wrong file modified).

### Interaction with Strict vs Recon-Only

AST measurement should run ONLY when reconstruction succeeds. If reconstruction fails, AST measurement emits `measurable: false, reason: "reconstruction_failed"`. This prevents conflating reconstruction failures with structural failures.

---

## 13. Integration Points in the Existing Pipeline

### Where It Runs

```
parse_model_response()
    ↓
reconstruct_strict()  ←── if status != SUCCESS: ast_measurable = false
    ↓
┌────────────────────┐
│  AST MEASUREMENT   │  ←── NEW: runs here, on reconstructed code
│  (ast_eval.py)     │
└────────┬───────────┘
         ↓
exec_canonical()     ←── unchanged
    ↓
evaluate_reasoning() ←── unchanged (but now has ast_result for comparison)
```

### What It Consumes

- Reconstructed code files (from `ReconstructionResult.files` dict)
- AST spec for the case (from `ast_specs.json`)
- Reference fix code (from `reference_fixes/{case_id}.py`)

### What It Emits

```python
@dataclass
class ASTResult:
    measurable: bool
    reason: str | None          # if not measurable: "syntax_error", "no_spec", "reconstruction_failed"
    ast_correct: bool | None    # None if not measurable
    ast_score: float | None     # 0.0 to 1.0, fraction of patterns matched
    patterns_matched: list[str]
    patterns_missing: list[str]
    forbidden_violations: list[str]
    alt_satisfied: bool
```

### How It's Logged

Added to the `raw_ev` dict passed to `emit_event()`:

```python
raw_ev["ast_eval"] = {
    "measurable": True,
    "ast_correct": True,
    "ast_score": 1.0,
    "patterns_matched": ["copy_call_on_assignment"],
    "patterns_missing": [],
    "forbidden_violations": [],
}
```

This appears in the event's `extra` section (since "ast_eval" is not in the consumed-keys set of `logging_core.py`).

### Downstream Analysis

Analysis scripts read `event.extra.ast_eval.ast_correct` from events.jsonl alongside `event.execution.passed` and `event.reasoning.reasoning_correct`.

---

## 14. Logging and Artifact Design

### Event Schema Addition

No changes to the canonical event schema v7. AST results flow through the existing `extra` dict mechanism.

### Stored Artifacts (Optional, Debug Mode)

When `config.logging.store.ast_details: true`:
- `{worker_dir}/ast_diff.json` — per-file AST node differences
- `{worker_dir}/ast_patterns.json` — full pattern match details

### Aggregate Dashboard Addition

Add to `aggregate.py` output:
```json
{
  "ast_correctness_rate": 0.42,
  "ast_measurable_rate": 0.88,
  "leg_ast_rate": 0.15,
  "leg_llm_rate": 0.18,
  "ast_llm_agreement_rate": 0.91
}
```

---

## 15. Analysis Outputs and Metrics

### Core Analyses Enabled

1. **AST correctness rate by case / family / model / condition.** Direct analog of pass rate but for structural correctness.

2. **Confusion matrix: AST × Execution.**
   ```
                   Exec Pass    Exec Fail
   AST Correct    true_success  LEG_ast
   AST Incorrect  lucky_fix     true_failure
   ```

3. **AST correctness vs LLM mechanism_correct.** Agreement rate, per case/model. Where they disagree is the most interesting analysis.

4. **LEG_ast vs LEG_llm.** If AST-based LEG is higher/lower than LLM-based LEG, it indicates where the LLM evaluator is noisy.

5. **Intervention effects on AST correctness.** Does critique/reasoning-only change the rate at which models produce structurally correct code? Currently we only know if it changes pass rates.

6. **Reconstruction artifact decomposition (refined).**
   ```
   recon_failed → not measurable
   recon_ok, ast_wrong → genuine structural failure
   recon_ok, ast_correct, exec_fail → runtime artifact
   recon_ok, ast_correct, exec_pass → clean success
   ```

7. **Per-pattern analysis.** Which specific patterns are hardest? Do models consistently miss `.copy()` but get `break` statements right?

### Paper-Strengthening Analyses

- **Claim: "LEG is a real phenomenon, not an evaluator artifact."** Show AST-based LEG correlates with LLM-based LEG (validates the evaluator) but is deterministic and reproducible.
- **Claim: "Intervention helps structural correctness, not just formatting."** Show critique/ro conditions change AST correctness rates, not just recon success rates.
- **Claim: "Reconstruction artifacts explain X% of apparent intervention effects."** Use the 4-way decomposition above.

---

## 16. Validation Strategy

### Ground Truth Validation

For each AST spec, validate against:

1. **Reference fix must match all required patterns.** If the spec doesn't match the reference fix, the spec is wrong.
2. **Buggy code must NOT match all required patterns.** If it does, the spec is trivial / wrong.
3. **Known trap fixes must NOT match.** Trap fixes are structurally plausible but incorrect; the spec must reject them.
4. **Hand-review 10 model outputs per case.** For each case, manually check 10 model outputs where AST says correct and 10 where AST says incorrect. Compute false positive and false negative rates.

### Automated Regression

```python
def validate_ast_specs():
    for case_id, spec in load_specs():
        ref_code = load_reference_fix(case_id)
        buggy_code = load_buggy_code(case_id)

        assert check_pattern(ref_code, spec).ast_correct, f"{case_id}: ref fix doesn't match spec"
        assert not check_pattern(buggy_code, spec).ast_correct, f"{case_id}: buggy code matches spec"
```

Run this as a pre-flight check before any evaluation run.

---

## 17. Risks, Failure Modes, and Edge Cases

### Risk 1: Multiple Valid Fixes With Different ASTs

**Problem:** `alias_config_a` has ≥3 valid fixes (`.copy()`, `dict()`, `{**X}`). Missing one gives false negatives.

**Mitigation:** `alternative_patterns` in spec. Validation step 4 catches gaps. Start with the most common patterns observed in model outputs, expand as needed.

### Risk 2: AST-Level Correctness But Semantic Wrongness

**Problem:** Model adds `.copy()` in the wrong function. AST says "copy call present," but it's in the wrong place.

**Mitigation:** All patterns are scoped to `target_function`. The pattern specifies where the fix must appear, not just that it exists anywhere.

### Risk 3: Parser Brittleness

**Problem:** `ast.parse()` fails on model output with syntax errors.

**Mitigation:** Return `measurable: false, reason: "syntax_error"`. This is the correct behavior — if the code doesn't parse, we can't measure its structure. Analysis excludes these from AST metrics (same as excluding reconstruction failures).

### Risk 4: Overfitting the Benchmark to Handcrafted Patterns

**Problem:** Each case gets a handcrafted spec. The benchmark "knows" what the fix looks like, creating a teaching-to-the-test risk.

**Mitigation:** AST specs are derived from reference fixes and validated against them. They measure whether the model produced a structurally equivalent transformation. The specs are not exposed to models — they're evaluation-side only. The risk is analogous to having invariant tests (which already "know" what correct behavior looks like).

### Risk 5: Leakage from Canonical Fixes

**Problem:** If AST specs are too tightly coupled to the reference fix, they might reject correct alternatives.

**Mitigation:** `alternative_patterns` and hand-review validation. The spec should be as loose as the invariant test — any code that would pass the invariant test should also pass the AST check. Where they diverge, the spec is too strict.

### Risk 6: Cases Not Naturally AST-Measurable

**Problem:** `false_fix_deadlock` requires restructuring nested functions and lock ordering. This is hard to express as a pattern.

**Mitigation:** `ast_measurable: false`. Not all cases need AST specs. The analysis reports AST metrics only for the measurable subset and clearly states coverage.

### Risk 7: False Confidence from Superficial Pattern Matches

**Problem:** Model adds `.copy()` somewhere in the code but the actual fix requires `.copy()` in a specific location with specific context.

**Mitigation:** Patterns are scoped to function + location. `forbidden_patterns` can reject common false positives (e.g., adding `.copy()` in the wrong function).

### Risk 8: Cross-File Invariants Are Hard to Express

**Problem:** `hidden_dep_multihop` requires understanding that `sync_user_to_cache` uses `cache_put` (overwrites) while `refresh_user_snapshot` uses `cache_put_if_absent` (doesn't overwrite). AST can check the call name but not the semantic difference.

**Mitigation:** For this case, checking the call name IS sufficient (the two functions have different overwrite semantics by construction). But this is case-specific knowledge baked into the spec. Document the limitation.

---

## 18. Phased Implementation Plan

### Phase 0: Audit and Scope (1 day)

**Goal:** Classify all 65 active cases as AST-measurable or not.

**Tasks:**
- For each case, inspect reference fix and determine if the structural change is pattern-expressible
- Draft `ast_specs.json` with `ast_measurable: true/false` for all cases
- Identify the ~10 most straightforward cases for Phase 1

**Validation:** Coverage table reviewed by team.

**Exit criteria:** `ast_specs.json` exists with boolean coverage for all cases.

### Phase 1: Core Measurement Module + 10 Cases (2 days)

**Goal:** Working AST measurement for 10 single-file, single-function-fix cases.

**Tasks:**
- Implement `ast_eval.py` with `check_pattern()` and detection functions
- Port relevant finders from `ast_mutator.py`
- Write specs for: alias_config_a, stale_cache_a, mutable_default_b, effect_order_b, use_before_set_b, retry_dup_b, partial_update_c, lazy_init_b, early_return_b, index_misalign_a
- Implement automated validation (ref fix passes, buggy fails)
- Run on existing event data (offline, not integrated into pipeline)

**Validation:** 10/10 reference fixes pass, 10/10 buggy codes fail, hand-review 5 model outputs per case.

**Exit criteria:** `ast_eval.py` passes validation on 10 cases.

### Phase 2: Validate Against Existing Data (1 day)

**Goal:** Compare AST measurement against existing LLM mechanism_correct on real model outputs.

**Tasks:**
- Extract model code from existing events.jsonl files (the `_extracted_code` field)
- Run AST measurement offline on all extractable outputs for the 10 cases
- Compute agreement rate between `ast_correct` and `mechanism_correct`
- Identify disagreement cases and hand-review

**Validation:** Agreement rate >80% (if lower, investigate).

**Exit criteria:** Agreement analysis complete, disagreements classified.

### Phase 3: Pipeline Integration + Logging (1 day)

**Goal:** AST measurement runs as part of the live pipeline and is logged.

**Tasks:**
- Insert `ast_eval()` call in `execution_v2.py` between reconstruction and execution
- Pass results through `raw_ev` to logging
- Add to aggregate dashboard
- Run smoke test on 1 case × 1 model × 5 trials

**Validation:** Events contain `ast_eval` in extra section.

**Exit criteria:** Smoke test passes, events logged correctly.

### Phase 4: Expand to Full Coverage (2 days)

**Goal:** AST specs for all measurable cases.

**Tasks:**
- Write specs for remaining ~30 measurable cases
- Handle multi-file cases (hidden_dep_multihop, feature_flag_drift, etc.)
- Add `alternative_patterns` where multiple valid fixes exist
- Validate all specs (ref passes, buggy fails)

**Validation:** All specs pass automated validation.

**Exit criteria:** `ast_specs.json` has specs for ≥40 cases.

### Phase 5: Analysis and Comparison (1 day)

**Goal:** Produce paper-ready analyses comparing AST and LLM metrics.

**Tasks:**
- Run full analysis: AST correctness × execution × reasoning for all available data
- Compute confusion matrices, agreement rates, intervention effects
- Generate figures for paper
- Draft methodology paragraph for paper

**Validation:** Analyses are reproducible from scripts.

**Exit criteria:** Analysis notebook/script committed, figures generated.

### Phase 6: Decide on LEG Revision (Team Decision)

**Goal:** Decide whether to revise LEG definitions in the paper.

**Tasks:**
- Present AST vs LLM comparison to team
- If agreement >90%: propose AST as primary LEG signal (cheaper, reproducible)
- If agreement <90%: report both, analyze disagreements as a finding
- Update paper framing accordingly

**Exit criteria:** Team decision documented.

---

## 19. Recommended File/Module Layout

```
t3_code_generation/
├── ast_specs.json                     # Per-case AST pattern specs
├── pipeline/
│   └── ast_eval.py                    # Core measurement module
│       ├── ASTResult (dataclass)
│       ├── check_pattern(code, spec) → ASTResult
│       ├── detect_pattern(tree, pattern) → bool
│       ├── load_specs(path) → dict
│       └── validate_all_specs() → report
├── scripts/
│   ├── ast_mutator.py                 # Existing (unchanged)
│   ├── build_ast_specs.py             # Generate initial specs from reference fixes
│   ├── validate_ast_specs.py          # Automated spec validation
│   └── analyze_ast_metrics.py         # Paper-ready analysis
└── tests/
    └── test_ast_eval.py               # Unit tests for pattern detection
```

---

## 20. Minimal First Milestone

The smallest implementation that yields publishable value:

1. `ast_eval.py` with 5 pattern detectors (copy_call, cache_invalidation, none_guard, statement_in_loop, break_after_success)
2. Specs for 10 cases (the easiest single-file families)
3. Offline analysis on existing event data (no pipeline integration needed)
4. One figure: 2×2 confusion matrix of AST correctness × execution for 10 cases across 4 models
5. One paragraph in the paper: "We validate the LLM-based mechanism classification against deterministic AST analysis on N cases and find X% agreement, confirming that..."

**Estimated effort:** 2 days.

**What it proves:** Whether AST measurement is viable and whether it agrees with the LLM evaluator. If agreement is high, it justifies the evaluator. If agreement is low, the disagreement is a finding. Either way, it's publishable.

---

## 21. Open Design Questions

1. **Should AST measurement run on raw model code or reconstructed code?** Reconstruction applies import rewriting and concatenation. Raw model code is closer to what the model produced; reconstructed code is what actually executes. Recommendation: reconstruct first, measure reconstructed code (same artifact that execution sees).

2. **How to handle partial scores?** A case with 3 required patterns where 2 match: is `ast_score` 0.67? Is `ast_correct` false? Recommendation: `ast_correct` requires all required patterns. `ast_score` is the fraction matched. Both are logged.

3. **Should forbidden patterns be hard or soft?** If a forbidden pattern is detected, should it override a fully-matched required pattern? Recommendation: hard override. If the forbidden pattern is present, `ast_correct = false` regardless of required matches.

4. **How to spec cases with minimal-diff requirement?** Some cases should be a one-line fix. Model adding the correct fix PLUS unnecessary changes is technically correct but not minimal. Should AST penalize extra edits? Recommendation: no. Extra edits don't invalidate the fix. The invariant tests catch harmful extras. AST checks for presence of correct pattern, not absence of extras.

5. **Should the AST spec reference the buggy code or the fixed code?** Recommendation: the spec is defined in terms of what the correct code should contain, not what it should change from. This makes specs independent of the specific buggy variant.

6. **Coverage threshold for paper.** What fraction of cases must be AST-measurable to make claims about the benchmark? Recommendation: ≥60% (≥39 of 65). Below that, AST is a supplementary analysis, not a primary metric.

---

## 22. Concrete Next-Step Checklist

- [ ] Classify all 65 cases as AST-measurable / not (Phase 0)
- [ ] Create `ast_specs.json` skeleton with coverage flags
- [ ] Implement `pipeline/ast_eval.py` with `check_pattern()` and 5 core detectors
- [ ] Port `find_copy_calls()`, `find_method_calls()`, `find_default_params()` from `ast_mutator.py`
- [ ] Write specs for 10 pilot cases
- [ ] Implement `scripts/validate_ast_specs.py` — ref fix passes, buggy fails
- [ ] Run validation, fix any spec errors
- [ ] Extract model code from 100 existing events for the 10 pilot cases
- [ ] Run AST measurement offline, compute agreement with `mechanism_correct`
- [ ] Hand-review 10 disagreement cases
- [ ] Write up results: agreement rate, confusion matrix, figure
- [ ] Team decision: proceed to pipeline integration or stop?
