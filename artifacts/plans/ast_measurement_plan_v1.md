# AST-Based Measurement of Generated Code — Implementation Plan v1

**Date:** 2026-04-03
**Status:** PLAN ONLY — NO IMPLEMENTATION
**Scope:** Add objective, programmatic, non-LLM structural measurement to the evaluation pipeline
**Grounded in:** Inspection of the full repository, all 73 cases, 74 reference fixes, pipeline architecture, LEG effect canonical report, and existing AST infrastructure in `scripts/ast_mutator.py`

---

## 1. Executive Summary

This plan adds AST-based structural measurement of model-generated code to the existing evaluation pipeline. The system compares the model's code output against canonical reference fixes using pattern-based AST analysis — not exact tree equality — to determine whether the model produced the correct structural transformation independently of whether execution passes.

**Why this matters for the project:** The current LEG metric (`LEG_v2`) relies on an LLM-based reasoning evaluator to determine "mechanism correctness." This introduces evaluator noise, confirmation bias (documented in the RAUDIT paper), and an irreducible subjectivity layer between the measurement and the claim. AST measurement provides a complementary signal that is:
- Fully deterministic and reproducible
- Zero-cost (no additional API calls)
- Immune to evaluator sycophancy
- Auditable (the pattern match is inspectable)
- Directly anchored to the canonical fix, not to a model's verbal account of its reasoning

The system does NOT replace execution evaluation (behavioral ground truth) or fully replace reasoning evaluation (some dimensions are not AST-measurable). It adds a third evaluation axis: **structural correctness**.

**What it produces:** A per-case boolean + graded score: did the model's code exhibit the required structural fix pattern? This enables a cleaner decomposition of the evaluation space into {AST-correct, AST-incorrect} × {exec-pass, exec-fail} × {reasoning-correct, reasoning-incorrect}, yielding sharper definitions of LEG, lucky fixes, and reasoning-execution alignment.

---

## 2. Current System Audit

### Pipeline architecture (from inspection of `orchestration/execution_v2.py`)

The v2 pipeline has 9 stages:

1. **Prompt assembly** (`assembly_engine.build()`) — renders Jinja2 components
2. **Model call** (`call_model()`) — returns raw text
3. **Parsing** (`parser_v2.parse_v2_execution()`) — extracts JSON from response
4. **Reasoning normalization** (`normalize_generation_v2()`) — extracts root_cause, fix_strategy, code_commitments
5. **Reconstruction + Execution** (`reconstruct_strict()` → `exec_canonical()`) — maps model files to case files, runs invariant tests in subprocess
6. **Classifier** (`build_classifier_v2_vars()` → LLM call → `parse_classifier_v2_output()`) — 5-dimensional LLM judgment
7. **Signal derivation** (`derive_v2_signals()`) — boolean signals from classifier dimensions
8. **Assembly** (`assemble_v2_result()`) — final event dict
9. **Logging** (`logger.end_case()`, `logger.log_run()`)

### Where LEG is currently computed (from `evaluation/metrics_v2.py`)

`LEG_v2` is assigned when:
- `code_correct = False` (execution fails)
- `mechanism_correct = True` (LLM classifier says mechanism_identified == CORRECT)
- `alignment_positive = False` (LLM classifier says reasoning_code_alignment != CORRECT)

This means LEG currently depends entirely on the LLM classifier for the "reasoning was correct" part. There is no objective structural check.

### Existing AST infrastructure (from `scripts/ast_mutator.py`, ~1700 lines)

The project already has substantial AST tooling for **case generation** (mutating clean code into buggy code):
- `find_copy_calls()` — finds `.copy()` / `dict()` calls
- `find_method_calls()` — finds specific method calls by name
- `find_function_calls()` — finds specific function calls by name
- `find_comparisons()` — finds comparison operators
- `find_branches()` — finds if/elif chains
- `find_assignments_to()` — finds assignments to specific variables
- `find_default_params()` — finds `None` defaults in function signatures
- `find_insert_calls()` — finds `.insert()` calls
- ~20 `ast.NodeTransformer` subclasses for specific mutations

**Critical observation:** These finders are the INVERSE of what AST evaluation needs. The mutator finds patterns in clean code and removes/corrupts them to create buggy code. AST evaluation finds patterns in model output to check whether they were restored. The same finder functions can serve both purposes.

### Reference fixes (from `data/reference_fixes/`)

74 canonical fix files exist, one per case. Each contains the complete fixed version of the primary target file. These are the ground truth for what correct code looks like structurally.

### Reconstruction artifact issue (from LEG report)

The LEG report documented that 4 of 10 "LEG hurts" results were 100% reconstruction artifacts — the model's code was structurally correct but wrapped in unparseable JSON. The `strict` vs `recon-only` distinction already exists in the pipeline. AST measurement must respect this: it should operate on successfully reconstructed code only, and the strict/recon-only decomposition must apply to AST metrics too.

---

## 3. Why AST Measurement Is Valuable In This Project

### Problem 1: The LLM reasoning evaluator is noisy

The current `mechanism_correct` signal comes from a 5-dimensional LLM classifier. The RAUDIT and RCA papers (both in `.claude/CS372/`) document that LLM evaluators exhibit:
- **Confirmation bias:** Conditioned evaluators are systematically biased by the context they receive
- **Sycophancy:** Models agree with plausible-sounding but wrong reasoning
- **Inverse scaling on hard tasks:** Stronger evaluator models are sometimes MORE sycophantic on complex causal tasks

The LEG report's own `compute_evaluator_bias()` function (in `orchestration/leg_evaluator.py`) measures this bias. AST measurement is immune to all three: it checks structure, not plausibility.

### Problem 2: "Mechanism correct" is not the same as "code structurally correct"

The classifier's `mechanism_identified` dimension asks: "Did the model correctly identify the bug mechanism?" A model can identify the mechanism in prose (`root_cause: "DEFAULTS is returned by reference"`) but then generate code that doesn't apply `.copy()`. The current system relies on `reasoning_code_alignment` to catch this, but alignment is itself an LLM judgment.

AST measurement directly checks: does the generated code contain `.copy()` on the return value? This is the structural question the alignment dimension is trying to answer, but deterministically.

### Problem 3: LEG's publishable strength depends on measurement objectivity

The paper's central claim — that models exhibit a gap between correct reasoning and correct execution — is only as strong as the reasoning measurement. If "reasoning correct" is itself an LLM judgment, a skeptical reviewer can argue the gap is a measurement artifact. AST measurement converts "reasoning correct" (for the structural dimension) into a programmatic, reproducible check that no reviewer can dispute.

### Problem 4: The project already has the infrastructure

The 74 reference fixes and the 20+ AST finder functions in `ast_mutator.py` mean most of the hard work is done. What's missing is the comparison logic and the integration into the evaluation pipeline.

### What this does NOT fix

- AST cannot measure whether the model *understood* why the fix is correct — only that it produced the correct structural change
- AST cannot distinguish between a model that reasoned its way to the fix and one that pattern-matched from training data
- AST cannot evaluate fix quality beyond structural correctness (performance, style, robustness)
- AST cannot replace execution: a structurally correct fix may still fail execution due to semantic errors, import issues, or test-contract mismatches

---

## 4. What AST Can Reliably Measure

### High-confidence detection (binary, unambiguous)

These patterns have a single canonical AST structure that is either present or absent:

| Pattern | Families | AST Signal | Ambiguity |
|---------|----------|-----------|-----------|
| `.copy()` addition | alias_config | `ast.Call` with `attr='copy'` on return value | None — unique pattern |
| Mutable default → None | mutable_default | `ast.Constant(None)` in `args.defaults` + `is None` guard | None — canonical idiom |
| `break` in retry loop | retry_dup | `ast.Break` inside `ast.For > ast.Try.body` | None — presence/absence |
| Operator correction | wrong_condition | `ast.Compare.ops` type | None — enumerable |
| Variable initialization | use_before_set | `ast.Assign` before `ast.If` | Low — position matters |
| Missing branch addition | missing_branch | Count of `elif` clauses or dict keys | Low — countable |
| Function call substitution | hidden_dep_multihop | `ast.Call.func.id` string value | None — string equality |

### Medium-confidence detection (pattern-based, slight ambiguity)

| Pattern | Families | AST Signal | Ambiguity |
|---------|----------|-----------|-----------|
| Cache invalidation added | stale_cache, cache_invalidation_order | Additional `ast.Call` to invalidation function after write | Medium — call name varies |
| Try/except with rollback | partial_rollback, invariant_partial_fail | `ast.Try` wrapping critical section with compensation in `except` | Medium — compensation varies |
| Statement reordering | temporal_drift, effect_order | Relative position of specific calls in function body | Medium — hard to identify "which" calls |
| Eager→lazy capture | lazy_init | Module-level assignment removed; inline call added | Medium — scope analysis needed |
| Dependent field sync | partial_update | Additional assignment statements for derived fields | Medium — must identify which fields |

### Low-confidence / not reliably AST-measurable

| Pattern | Families | Why AST struggles |
|---------|----------|------------------|
| Lock ordering | false_fix_deadlock | Correct ordering is semantic, not structural — both orders parse identically |
| Atomic read-modify-write | lost_update, check_then_act | "Atomicity" is a runtime property; many structural implementations are valid |
| Event buffering | ordering_dependency | Complex control flow with multiple valid structural approaches |
| Parameter propagation | feature_flag_drift | Must trace parameter threading through multiple functions and files |

---

## 5. What AST Cannot Reliably Measure

### Semantic correctness that requires runtime reasoning

- **Lock ordering** (false_fix_deadlock): Both `lock(A); lock(B)` and `lock(B); lock(A)` have identical AST structure (two `ast.Call` nodes). Correctness depends on which lock object is acquired first, which is a semantic property of the variable bindings.

- **Atomicity** (lost_update, check_then_act): A model might combine read+write in a `with lock:` block, or use a different synchronization primitive, or restructure the computation entirely. All are structurally different but semantically equivalent.

- **Correct value in assignment**: If the fix is changing `timeout: 5` to `timeout: 30` (config_shadowing), AST can detect the assignment exists but checking the literal value is fragile — the model might choose `timeout: 25` or `timeout: 60`, which are structurally identical but semantically wrong or arguable.

### Reasoning quality

AST measures what the model DID, not what it UNDERSTOOD. A model that blindly pattern-matches `.copy()` from training data will score AST-correct on alias_config without any causal understanding. This is a fundamental limitation: AST correctness is a necessary-but-not-sufficient proxy for reasoning correctness in the structural dimension.

### Multi-file interaction semantics

For cross-boundary cases, AST can check whether each file was individually modified correctly, but cannot verify that the modifications interact correctly at runtime. Example: in partial_rollback_c, the model must add `release(product_id, qty)` and `remove_audit_entry(order_id)` in `order_service.py`. AST can detect both calls were added. But if the model added them in the wrong order, or with wrong arguments, AST detects "pattern present" while execution fails. This is a known false-positive risk.

### Cases where the model invents a valid alternative fix

If the canonical fix is `DEFAULTS.copy()` but the model writes `dict(DEFAULTS)` or `{**DEFAULTS}`, these are semantically equivalent but structurally different. The system must handle this. See Section 10 for the multi-pattern spec approach.

---

## 6. Proposed Evaluation Model

### Three orthogonal evaluation axes

```
                    ┌─────────────────────────────────┐
                    │        EXECUTION EVAL            │
                    │   (invariant test pass/fail)     │
                    │   Behavioral ground truth.       │
                    │   Source: exec_canonical()        │
                    └──────────┬──────────────────────┘
                               │
         ┌─────────────────────┼──────────────────────┐
         │                     │                      │
┌────────▼──────────┐ ┌───────▼────────────┐ ┌───────▼────────────┐
│   AST EVAL        │ │ REASONING EVAL     │ │ (future: semantic  │
│ Structural check  │ │ LLM classifier     │ │  equivalence?)     │
│ Pattern matching   │ │ 5 dimensions       │ │                    │
│ Deterministic      │ │ Subjective         │ │                    │
│ New addition       │ │ Existing           │ │                    │
└───────────────────┘ └────────────────────┘ └────────────────────┘
```

**Execution** remains the behavioral ground truth. **AST** is added as the structural ground truth. **Reasoning** (LLM classifier) is retained for dimensions AST cannot measure (mechanism identification from prose, risk awareness, etc.) but is demoted from sole arbiter of "reasoning correct" to one of three signals.

### Evaluation matrix

Each (case, model, condition, trial) now produces a triple:

```
(exec_pass: bool, ast_correct: bool|float, reasoning_correct: bool)
```

The 8 cells of the 2×2×2 cube:

| exec_pass | ast_correct | reasoning_correct | Category | Interpretation |
|-----------|-------------|-------------------|----------|---------------|
| T | T | T | `interpretable_success` | Everything aligned — model understood and executed correctly |
| T | T | F | `ast_lucky_reasoning_miss` | Code correct but evaluator missed the reasoning (evaluator error or partial understanding) |
| T | F | T | `lucky_fix` | Execution passes but fix is structurally wrong — test may be weak or model found an alternative |
| T | F | F | `double_lucky` | Pass with wrong structure AND wrong reasoning — test is almost certainly insufficient |
| F | T | T | **`LEG_ast`** | Core LEG: correct structure + correct reasoning but execution fails — the purest LEG signal |
| F | T | F | `ast_correct_reasoning_miss` | Structure correct but evaluator says wrong — evaluator error or genuine reasoning gap despite correct code |
| F | F | T | `text_LEG_only` | Verbal reasoning correct but code is structurally wrong — this is what text-LEG currently captures |
| F | F | F | `full_failure` | Nothing worked |

---

## 7. Revised Definitions of LEG / Lucky Fix / Success / Failure

### Proposed naming scheme

| Metric | Definition | Signal source |
|--------|-----------|---------------|
| `pass_strict` | Execution passes on strict reconstruction | exec_canonical (existing) |
| `pass_recon` | Execution passes on any successful reconstruction | exec_canonical (existing) |
| `ast_correct` | Model output matches canonical fix AST pattern | AST evaluator (new) |
| `ast_score` | Graded AST correctness [0.0, 1.0] | AST evaluator (new) |
| `mechanism_correct` | LLM classifier says mechanism identified | evaluator_v2 (existing) |
| `alignment_positive` | LLM classifier says reasoning-code alignment correct | evaluator_v2 (existing) |
| **`LEG_ast`** | `NOT pass_strict AND ast_correct` | exec + AST |
| **`LEG_text`** | `NOT pass_strict AND mechanism_correct AND NOT alignment_positive` | exec + classifier (existing LEG_v2) |
| **`LEG_combined`** | `LEG_ast AND LEG_text` | All three — highest confidence LEG |
| **`lucky_fix_ast`** | `pass_strict AND NOT ast_correct` | exec + AST |
| **`lucky_fix_text`** | `pass_strict AND NOT mechanism_correct` | exec + classifier (existing) |
| `ast_exec_agreement` | `ast_correct == pass_strict` | Cross-check |

### Why both LEG definitions should coexist

`LEG_ast` and `LEG_text` measure different things:
- `LEG_ast` says "the model produced the right structural change but something else failed"
- `LEG_text` says "the model articulated the right mechanism but the code doesn't match"

They will often overlap but not always. Cases where they disagree are the most informative:
- `LEG_ast = True, LEG_text = False`: The code is structurally correct, but the reasoning evaluator didn't recognize the mechanism. This suggests evaluator noise.
- `LEG_ast = False, LEG_text = True`: The model described the right mechanism verbally but didn't implement it correctly. This is the "reasoning without execution" gap that the paper claims exists.

Reporting both side by side lets the paper argue: "Even when we remove the LLM evaluator from the loop entirely, the LEG signal persists — X% of structurally correct code still fails execution."

### Partial AST correctness

Many fixes require multiple structural changes (e.g., partial_rollback_c requires BOTH `release()` AND `remove_audit_entry()`). `ast_score` captures partial credit:

```
ast_score = (patterns_matched) / (patterns_required)
```

For cases with a single pattern (alias_config: just `.copy()`), `ast_score` is binary. For cases with 3 required patterns (partial_rollback_c: try/except + release + remove_audit), `ast_score` can be 0.0, 0.33, 0.67, or 1.0.

`ast_correct` is the boolean: `ast_score >= 1.0`.

---

## 8. Canonical AST Target Representation

### Source of truth: reference fixes + buggy code

For each case, the canonical AST target is derived from:
1. The buggy code file(s) in `code_snippets_v2/{case_id}/`
2. The reference fix file in `data/reference_fixes/{case_id}.py`

The AST diff between buggy and fixed code defines "what should change." The AST evaluation checks whether the model's output contains the same structural changes.

### Why not use exact AST equality with the reference fix?

1. **Whitespace, comments, docstrings:** Models add/remove comments freely. `ast.parse` ignores comments, but `ast.dump(tree)` equality fails on trivially equivalent rearrangements.
2. **Variable names:** A model might use `config_copy` instead of `config` for the return value of `.copy()`. Semantically identical, AST-different.
3. **Multiple valid fixes:** `DEFAULTS.copy()`, `dict(DEFAULTS)`, and `{**DEFAULTS}` are all correct for alias_config. Exact equality would reject 2 of 3.
4. **Extra changes:** Models often add logging, docstrings, type hints, or minor refactors alongside the fix. Exact equality would reject all of these.
5. **Reordering:** A model might reorder function definitions or import statements without affecting correctness.

Therefore: **exact AST equality is rejected as the primary measurement.** Pattern-based detection is required.

### What the canonical target looks like conceptually

For `alias_config_a`:
```
canonical_target:
  file: "config.py"
  function: "create_config"
  required_patterns:
    - type: "return_calls_copy"
      description: "Return value involves .copy() or dict() or dict unpacking"
      alternatives:
        - ast.Call with attr='copy' on DEFAULTS
        - ast.Call with func=dict, args=[DEFAULTS]
        - ast.Dict with unpacking of DEFAULTS
  forbidden_patterns:
    - type: "bare_reference_return"
      description: "Return DEFAULTS without copy"
      pattern: ast.Return(value=ast.Name(id='DEFAULTS'))
```

---

## 9. Case Schema Changes

### Recommendation: separate AST spec file, not inline in cases_v2.json

**Rationale:**
- `cases_v2.json` is already large (73 cases × ~50 fields each) and shared by all 6 contributors
- AST specs are implementation-level detail that would bloat the case schema
- AST specs evolve independently (adding alternative patterns, tuning thresholds)
- Not all cases are AST-measurable; a separate file naturally handles this (absent = not measurable)
- The `ground_truth_bug` field already has `fix_pattern` as a human-readable string; the AST spec is the machine-readable equivalent

**Proposed file:** `data/ast_specs.json`

```json
{
  "alias_config_a": {
    "ast_measurable": true,
    "target_files": ["config.py"],
    "target_functions": ["create_config"],
    "match_scope": "function",
    "required_patterns": [
      {
        "id": "copy_on_return",
        "type": "return_value_method_call",
        "method": "copy",
        "object_name": "DEFAULTS",
        "alternatives": [
          {"type": "builtin_call", "func": "dict", "arg_name": "DEFAULTS"},
          {"type": "dict_unpacking", "source": "DEFAULTS"}
        ],
        "severity": "critical"
      }
    ],
    "forbidden_patterns": [
      {
        "id": "bare_reference_return",
        "type": "return_bare_name",
        "name": "DEFAULTS",
        "severity": "critical"
      }
    ],
    "acceptable_extra_edits": true,
    "order_sensitive": false,
    "min_diff_expected": false,
    "notes": "Single-line fix. Very high AST detection confidence."
  },
  "invariant_partial_fail": {
    "ast_measurable": true,
    "target_files": ["transfer_service.py"],
    "target_functions": ["execute_transfer"],
    "match_scope": "function",
    "required_patterns": [
      {
        "id": "try_except_around_credit",
        "type": "try_except_present",
        "must_wrap_calls": ["receiver.balance"],
        "severity": "critical"
      },
      {
        "id": "rollback_in_except",
        "type": "except_contains_compensation",
        "compensation_pattern": "sender.balance += amount",
        "severity": "critical"
      },
      {
        "id": "reraise_after_rollback",
        "type": "except_ends_with_raise",
        "severity": "important"
      }
    ],
    "forbidden_patterns": [],
    "acceptable_extra_edits": true,
    "order_sensitive": true,
    "notes": "Three required patterns. ast_score = matched/3."
  }
}
```

### Case-level AST spec fields

| Field | Type | Description |
|-------|------|-------------|
| `ast_measurable` | bool | Whether this case has an AST spec. ~50 of 73 cases will be `true`. |
| `target_files` | list[str] | Which file(s) must be checked |
| `target_functions` | list[str] or null | If non-null, scope check to these functions |
| `match_scope` | "function" \| "file" \| "module" | Where to look for patterns |
| `required_patterns` | list[PatternSpec] | Patterns that MUST be present in correct fix |
| `forbidden_patterns` | list[PatternSpec] | Patterns that must NOT be present (anti-patterns) |
| `acceptable_extra_edits` | bool | Whether extra changes beyond the fix are OK |
| `order_sensitive` | bool | Whether statement ordering matters |
| `min_diff_expected` | bool | Whether the fix should be minimal (few changes) |
| `notes` | str | Human-readable notes for debugging |

### PatternSpec structure

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Unique identifier within the case |
| `type` | str | Pattern type (see Section 10 for the taxonomy) |
| `severity` | "critical" \| "important" \| "informational" | Weight in ast_score |
| `alternatives` | list[PatternSpec] | OR-alternatives (any one match satisfies) |
| (type-specific fields) | various | Parameters for the specific pattern type |

---

## 10. AST Pattern Specification Design

### Pattern type taxonomy

Based on inspection of all 73 cases' `fix_pattern` fields and reference fixes, these are the distinct pattern types needed:

#### 1. `method_call_present` — Check that a specific method is called

**Covers:** alias_config (.copy()), stale_cache (invalidate()), partial_update (sync calls)

```python
# Pseudocode for the checker
def check_method_call_present(tree, func_name, method_name, object_name=None):
    """Check that <object>.<method>() appears in the function body."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == method_name:
                if object_name is None or _name_matches(node.func.value, object_name):
                    return True
    return False
```

#### 2. `method_call_absent` — Check that a pattern was removed

**Covers:** Cases where the bug IS a call that should be removed (overdetermination: remove write_cached)

#### 3. `default_param_none` — Function default is `None` with guard

**Covers:** mutable_default family (all 3 cases)

```python
def check_default_none_with_guard(tree, func_name, param_name):
    """Default is None + body has 'if param is None: param = []'."""
    func = _find_function(tree, func_name)
    # Check default
    param_idx = _find_param_index(func, param_name)
    default = func.args.defaults[param_idx]
    if not (isinstance(default, ast.Constant) and default.value is None):
        return False
    # Check guard
    for node in ast.walk(func):
        if isinstance(node, ast.If):
            if _is_none_check(node.test, param_name):
                return True
    return False
```

#### 4. `break_in_loop` — Break statement present inside specific loop context

**Covers:** retry_dup family (all 3 cases)

```python
def check_break_in_try_inside_for(tree, func_name):
    """Check for 'break' after success inside for>try>body."""
    func = _find_function(tree, func_name)
    for node in ast.walk(func):
        if isinstance(node, ast.For):
            for child in ast.walk(node):
                if isinstance(child, ast.Try):
                    for stmt in child.body:
                        if isinstance(stmt, ast.Break):
                            return True
                    # Also check: break after the try statement but inside for
                    # (some models put break after the try, not inside it)
    return False  # Simplified — real impl needs parent tracking
```

#### 5. `try_except_with_compensation` — Exception handling with rollback

**Covers:** partial_rollback (all 3), invariant_partial_fail

```python
def check_try_except_compensation(tree, func_name, compensation_calls):
    """Check for try/except with specific compensation calls in handler."""
    func = _find_function(tree, func_name)
    for node in ast.walk(func):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                handler_calls = _extract_call_names(handler.body)
                if all(c in handler_calls for c in compensation_calls):
                    return True
    return False
```

#### 6. `statement_before_target` — A statement appears before another specific statement

**Covers:** temporal_drift (raw_stats before transform), use_before_set (init before conditional), effect_order (side effect inside loop)

```python
def check_statement_order(tree, func_name, before_call, after_call):
    """Check that before_call appears before after_call in function body."""
    func = _find_function(tree, func_name)
    positions = {}
    for i, stmt in enumerate(func.body):
        calls = _extract_calls_from_stmt(stmt)
        for c in calls:
            positions[c] = i
    return positions.get(before_call, 999) < positions.get(after_call, -1)
```

#### 7. `branch_present` — An elif/case exists for a specific condition

**Covers:** missing_branch family

#### 8. `operator_type` — A comparison uses the correct operator

**Covers:** wrong_condition family

#### 9. `call_before_return` — A specific call appears before early return

**Covers:** early_return family (audit/ledger call before return)

#### 10. `module_level_removed` — A module-level statement was deleted

**Covers:** lazy_init family (remove eager capture at module level)

#### 11. `function_call_name` — A specific function is called (not just method)

**Covers:** hidden_dep_multihop (sync_user_to_cache vs refresh_user_snapshot)

#### 12. `parallel_structure_consistent` — Same operation applied to parallel arrays

**Covers:** index_misalign family

#### 13. `key_name_literal` — Correct string key used in dict access

**Covers:** silent_default family

#### 14. `assignment_augmented` — Additional assignments to dependent fields

**Covers:** partial_update family

### Pattern severity and scoring

```
ast_score = (critical_matched / critical_total * 0.8) + (important_matched / important_total * 0.2)
```

If no `important` patterns exist, `ast_score = critical_matched / critical_total`.

`ast_correct = (all critical patterns matched)`.

---

## 11. Matching Strategy: Exact AST vs Pattern-Based Detection

### Rejected: Exact AST tree equality

As argued in Section 8, this is too strict. It fails on:
- Comments/docstrings (mitigated by `ast.parse` but not fully)
- Variable renaming
- Extra imports or helper functions
- Reordering of function definitions
- Multiple valid fix approaches

### Rejected: Full AST diff (tree edit distance)

Tree edit distance algorithms (Zhang-Shasha, APTED) compute the minimum edit operations between two ASTs. Problems:
- Expensive for large files (O(n²) to O(n⁴))
- The edit distance between buggy→model and buggy→canonical can be small even when the model's fix is wrong (if the model made few changes but the wrong ones)
- Edit distance doesn't distinguish between "right change + extra changes" and "wrong change"
- Cannot handle multiple valid fixes naturally

### Chosen: Pattern-based detection with alternative support

Each case specifies required patterns (the structural changes that constitute the fix) and forbidden patterns (the structural signatures of the bug). The matcher checks:

1. Parse model output with `ast.parse()`
2. For each target file, locate the target function(s)
3. For each required pattern, check if it (or any of its alternatives) is present
4. For each forbidden pattern, check that it is absent
5. Compute `ast_score` from the match results

This approach:
- Tolerates extra changes (models that add logging, comments, refactoring alongside the fix)
- Handles multiple valid fixes via `alternatives`
- Provides graded scoring via multiple required patterns
- Is deterministic and inspectable
- Runs in O(n) per file (single AST walk per pattern)
- Leverages existing finder functions from `ast_mutator.py`

### How to handle unknown alternative fixes

If a model produces a fix that is structurally different from all specified alternatives but execution passes, the case should be flagged for manual review and the alternative should be added to the spec. This is a spec-maintenance task, not a system failure.

---

## 12. Multi-File and Cross-Boundary Cases

### Scope of the problem

Of 73 cases:
- ~20 are single-file (A-difficulty, all fix patterns in one file)
- ~25 are two-file (B-difficulty, bug and fix may span two files)
- ~28 are three+ file (C/L3-difficulty, cross-boundary dependencies)

For multi-file cases, the model outputs multiple files. AST evaluation must handle all of them.

### Strategy: per-file evaluation, case-level aggregation

1. **Per-file AST check:** For each target file specified in `ast_specs.json`, parse the model's output for that file and check the patterns.

2. **Case-level aggregation:** A case is `ast_correct` only if ALL target files pass ALL their critical patterns.

```
case_ast_score = min(file_ast_scores)  # weakest link
case_ast_correct = all(file_ast_correct for file in target_files)
```

Using `min` rather than `mean` because a case where one file is perfectly fixed but another is untouched is not correct — it's partial at best.

3. **Per-file reporting:** The event dict includes per-file AST results for analysis:

```json
{
  "ast_eval": {
    "case_ast_correct": false,
    "case_ast_score": 0.5,
    "files": {
      "order_service.py": {
        "ast_correct": true,
        "ast_score": 1.0,
        "patterns_matched": ["release_call", "try_except"],
        "patterns_missed": []
      },
      "payment.py": {
        "ast_correct": false,
        "ast_score": 0.0,
        "patterns_matched": [],
        "patterns_missed": ["remove_audit_entry_call"]
      }
    }
  }
}
```

### Reconstruction interaction

AST evaluation requires parseable Python code. If `reconstruct_strict()` fails for a file:
- That file's AST result is `None` (not False — it's unassessable, not wrong)
- The case-level result is `None` (not assessable) if ANY target file failed reconstruction
- This aligns with the strict/recon-only distinction: AST metrics should be reported for both subsets

If `reconstruct_salvage()` fills a missing file with the original (buggy) code:
- The AST check for that file will correctly report the bug patterns as present → `ast_correct = False`
- This is the right answer: the model didn't fix that file

---

## 13. Integration Points in the Existing Pipeline

### Where AST evaluation runs

AST evaluation should run **after reconstruction and before the LLM classifier** (between current stages 5 and 6):

```
Stage 5: reconstruct_strict() → ReconstructionResult
         exec_canonical() → exec_result
Stage 5.5 [NEW]: ast_evaluate() → ASTResult
Stage 6: build_classifier_v2_vars() → classifier prompt (optionally informed by AST result)
```

**Rationale:**
- Needs reconstructed code (output of stage 5) as input
- Does not need execution results (could run in parallel with exec_canonical, but serial is simpler)
- Should run before the classifier so that AST results can optionally be logged alongside classifier results for cross-comparison
- Does NOT feed into the classifier prompt — AST is an independent signal

### What it consumes

- `ReconstructionResult.files`: dict of {filename: code_string} from successful reconstruction
- Case metadata: `case_id`, `family`, `ground_truth_bug`
- AST spec: loaded from `data/ast_specs.json` for this case_id
- Buggy code files: from `code_snippets_v2/{case_id}/` (for forbidden-pattern checking)

### What it emits

An `ASTEvalResult` dict added to the event:

```python
{
    "ast_eval": {
        "assessable": True,          # False if reconstruction failed for target files
        "case_ast_correct": True,
        "case_ast_score": 1.0,
        "files": { ... },            # per-file details
        "patterns_checked": 3,
        "patterns_matched": 3,
        "patterns_forbidden_found": 0,
        "spec_version": "v1",
    }
}
```

### Where it should live

New module: `evaluation/ast_eval.py`

This follows the existing pattern:
- `evaluation/evaluator_v2.py` — LLM-based evaluation
- `evaluation/metrics_v2.py` — signal derivation
- `evaluation/ast_eval.py` — AST-based evaluation (new)

### How downstream analysis consumes it

The event dict already flows to `merged_events.jsonl`. Analysis scripts in `analysis/` load events via `load_logs.py` → `prepare_df()`. The new `ast_eval.*` fields will be available as DataFrame columns automatically.

A new analysis script `analysis/run_ast_analysis.py` computes the metrics in Section 15.

---

## 14. Logging and Artifact Design

### Event dict additions

The `ast_eval` block (shown above) is added to every event where:
- The case has an AST spec (`ast_measurable: true`)
- At least one target file was successfully reconstructed

For cases without an AST spec, `ast_eval` is absent from the event (not `null` — absent).

### Detailed logging

At INFO level:
```
AST eval: alias_config_a → ast_correct=True (score=1.0, 1/1 patterns)
AST eval: partial_rollback_c → ast_correct=False (score=0.33, 1/3 patterns: try_except✓ release✗ remove_audit✗)
```

At DEBUG level: per-pattern match details including which AST nodes matched.

### Artifact files

For each experiment run, produce:
- `ast_eval_summary.json`: per-case AST correctness rates aggregated across trials
- Included in the existing `merged_events.jsonl` (no separate file needed for per-trial data)

---

## 15. Analysis Outputs and Metrics

### Core metrics (all computable from merged_events.jsonl)

**1. AST correctness rate by case / family / model / condition**

```python
df.groupby(['case_id', 'model', 'condition'])['ast_eval.case_ast_correct'].mean()
```

**2. AST correctness vs pass rate (the key diagnostic)**

For each (case, model, condition):
```
pass_rate:       mean(exec_pass)
ast_correct_rate: mean(ast_correct)
```

Scatter plot: ast_correct_rate vs pass_rate. Cases above the diagonal have structural fixes that don't execute. Cases below have execution passes without the right structure.

**3. 2×2 confusion matrix: AST × Execution**

```
                  exec_pass=T    exec_pass=F
ast_correct=T     success        LEG_ast
ast_correct=F     lucky_fix_ast  full_failure
```

Report these counts per model, per condition, per family.

**4. LEG_ast rate vs LEG_text rate**

Are they correlated? Where do they disagree? Disagreements reveal evaluator noise vs genuine reasoning-execution separation.

**5. AST correctness under intervention conditions**

Does lean/LEG/critique increase ast_correct_rate? This is a cleaner signal than pass_rate because it removes execution-layer failures.

**6. Strict vs recon-only AST conditioned analyses**

Split all AST metrics by reconstruction mode to check for the same artifact patterns the LEG report found.

**7. Family-level AST signal strength**

Which families have high ast_correct but low pass_rate? These are the families where execution evaluation is adding the most value beyond structural correctness. Which families have low ast_correct but high pass_rate? These have alternative valid fixes not in the spec (spec needs updating) or weak tests.

**8. Case families where text reasoning says "correct" but AST says "incorrect"**

These are evaluator false positives. The model describes the right mechanism but generates structurally wrong code, and the LLM evaluator doesn't catch it. Rate of occurrence directly measures evaluator reliability.

**9. Case families where AST says "correct" but execution fails**

These are the purest LEG cases: the model made the right structural change, but something else is wrong (reconstruction artifact, import issue, test-contract mismatch, semantic error within a structurally correct pattern). This number directly measures how much LEG exists beyond the reasoning-measurement-error floor.

### Paper claims strengthened

| Claim | Current evidence | With AST measurement |
|-------|-----------------|---------------------|
| "LEG exists" | LLM evaluator says reasoning correct + execution fails | AST says structure correct + execution fails — objective, reproducible |
| "LEG scaffolding helps when LEG is high" | Compares pass rates under conditions | Can separately measure: does lean increase ast_correct_rate? Does it increase pass_rate given ast_correct? |
| "Reconstruction artifacts distort interpretation" | Strict vs recon-only decomposition | Add AST-conditioned decomposition: among ast_correct cases, what's the strict vs recon pass rate? |
| "Lucky fixes are rare" | LLM evaluator says reasoning wrong + execution passes | AST says structure wrong + execution passes — no evaluator noise |
| "Lean outperforms full LEG" | Pass rate comparison | AST correctness comparison removes execution noise |

---

## 16. Validation Strategy

### Phase 1 validation: Manual audit of AST specs

For the first 15 cases (5 families × 3 difficulties), manually:
1. Write the AST spec
2. Run the matcher on the reference fix — MUST return `ast_correct = True`
3. Run the matcher on the buggy code — MUST return `ast_correct = False`
4. Fabricate 3-5 common wrong fixes per case — MUST return `ast_correct = False`
5. Fabricate 1-2 alternative correct fixes — MUST return `ast_correct = True`

This produces a confusion matrix for the spec itself (TP/TN/FP/FN), not for model outputs.

### Phase 2 validation: Back-test on existing experimental data

The project has ~25,000 experimental events from the LEG ablation runs. For each event where reconstruction succeeded:
1. Run AST evaluation
2. Compare `ast_correct` with `exec_pass` and `mechanism_correct`
3. Check: does `ast_correct AND NOT exec_pass` identify a subset of the cases the LLM evaluator identified as LEG_v2? (Expected: yes, a proper subset)
4. Check: how many `ast_correct AND exec_pass` cases did the LLM evaluator label `lucky_fix_v2`? (Expected: ~0, these should be `interpretable_success`)

### Phase 3 validation: Sensitivity analysis

For each case with an AST spec:
1. What percentage of execution-passing events are ast_correct? (Expected: >80% — if lower, the spec is too strict or alternatives are missing)
2. What percentage of ast_correct events pass execution? (Expected: >50% — if lower, execution barriers beyond structure are significant)
3. Are there cases where ast_correct rate is 0% but pass rate is >0%? (These need spec review — the model found a valid alternative)

---

## 17. Risks, Failure Modes, and Edge Cases

### Risk 1: Multiple semantically valid fixes with different ASTs

**Example:** alias_config admits `.copy()`, `dict()`, `{**DEFAULTS}`, `copy.deepcopy()`, `json.loads(json.dumps())`, etc.

**Mitigation:** The `alternatives` field in pattern specs. Start with 2-3 common alternatives per case. Expand during validation when back-testing reveals new valid patterns.

**Residual risk:** A truly novel valid fix not anticipated in any alternative. Mitigation: flag `ast_correct=False AND exec_pass=True` cases for manual review.

### Risk 2: AST-level correctness but semantic wrongness

**Example:** Model adds `try: ... except: sender.balance += wrong_variable` — the try/except structure matches but the compensation is wrong.

**Mitigation:** Pattern specs can include argument checks (e.g., `compensation_pattern: "sender.balance += amount"`). But this makes specs more brittle. Recommended: keep structural matching loose for the `ast_correct` signal; rely on execution for semantic correctness. Document that `ast_correct` is a structural proxy, not a semantic guarantee.

### Risk 3: Parser brittleness

**Example:** Model output contains syntax errors that prevent `ast.parse()`.

**Mitigation:** Already handled by reconstruction pipeline. If `reconstruct_strict()` fails (which includes `ast.parse()` validation at gate 4), AST eval returns `assessable: False`. This is consistent with the existing strict/recon-only methodology.

### Risk 4: Overfitting the benchmark to handcrafted patterns

**Concern:** If patterns are hand-authored per-case, the benchmark measures "does the model produce the specific code the spec author imagined" rather than "does the model fix the bug."

**Mitigation:**
1. Validate specs against reference fixes (they must pass)
2. Validate against known alternative fixes (they must also pass)
3. Back-test against 25K experimental events — if ast_correct rate is dramatically lower than pass rate, specs are too strict
4. The `alternatives` mechanism is explicit about this: every valid approach that's discovered gets added
5. Execution evaluation remains the behavioral ground truth — AST is supplementary

### Risk 5: Cases that are not naturally AST-measurable

**Estimate:** ~15-20 of 73 cases are poorly suited for AST (lock ordering, atomicity, complex state management). These should have `ast_measurable: false` and be excluded from AST-conditioned analyses.

**Mitigation:** Do NOT force AST specs on these cases. Report AST metrics only for the AST-measurable subset. The paper should state the coverage: "AST evaluation was applicable to N of 73 cases covering M families."

### Risk 6: Accidental leakage from canonical fixes

**Concern:** The AST spec is derived from reference fixes. Could models have seen the reference fixes in training data?

**Mitigation:** Reference fixes are in this repo (not public). The AST spec describes patterns, not exact code. A model cannot memorize "put .copy() on line 6 of config.py" from seeing the pattern spec. The risk is negligible.

### Risk 7: False confidence from superficial pattern matches

**Example:** Model adds `.copy()` on a completely wrong variable. AST says "copy call present" = True.

**Mitigation:** Pattern specs should include scope constraints (`target_function`, `object_name`). A `.copy()` on a random dict in a random function should not match the alias_config spec.

### Risk 8: Difficulty expressing cross-file invariants

**Example:** partial_rollback_c requires changes in `order_service.py` but the invariant (inventory is released) depends on `inventory.py`'s `release()` function.

**Mitigation:** AST evaluation checks that `release()` is called in `order_service.py`. It does not verify that `release()` in `inventory.py` works correctly — that's execution's job. The cross-file AST check is: "did the model add the right calls to the orchestrating file?"

---

## 18. Phased Implementation Plan

### Phase 0: Scope audit and spec authoring (1-2 days)

**Goal:** Determine exactly which cases get AST specs and write the first batch.

**Tasks:**
1. Classify all 73 cases as AST-measurable or not, with justification
2. Write AST specs for the 15 cases in the 5 highest-priority families: alias_config (3), mutable_default (3), retry_dup (3), stale_cache (3), wrong_condition (3)
3. Write AST specs for the 5 singleton LEG-critical cases: hidden_dep_multihop, invariant_partial_fail, cache_invalidation_order, feature_flag_drift, config_shadowing

**Validation:** Each spec must pass on the reference fix and fail on the buggy code.

**Exit criteria:** `data/ast_specs.json` with 20 validated specs.

### Phase 1: Core AST evaluation module (2-3 days)

**Goal:** Working `evaluation/ast_eval.py` that takes reconstructed code + spec and returns an ASTEvalResult.

**Tasks:**
1. Implement pattern matcher for the 8 most common pattern types (method_call_present, default_param_none, break_in_loop, try_except_compensation, statement_order, branch_present, operator_type, function_call_name)
2. Implement spec loader from `data/ast_specs.json`
3. Implement per-file evaluation with function scoping
4. Implement case-level aggregation (min across files)
5. Unit tests: each pattern type tested with positive and negative examples

**Validation:** Run on all 20 Phase-0 specs against reference fixes (all must pass) and buggy code (all must fail).

**Exit criteria:** `ast_eval.py` passes all unit tests and the 20-spec validation suite.

### Phase 2: Pipeline integration (1 day)

**Goal:** AST evaluation runs in the v2 pipeline and results appear in events.

**Tasks:**
1. Add `ast_evaluate()` call to `execution_v2.run_v2()` between stages 5 and 6
2. Add `ast_eval` block to event dict
3. Add AST fields to `derive_v2_signals()` output
4. Update `assemble_v2_result()` to include AST results
5. Integration test: run a single case end-to-end and verify event contains `ast_eval`

**Validation:** Run 3 cases through the full pipeline; verify `ast_eval` fields are present and correct.

**Exit criteria:** Pipeline produces events with AST evaluation for all AST-measurable cases.

### Phase 3: Back-test on existing data (1-2 days)

**Goal:** Run AST evaluation on the ~25,000 existing experimental events to validate metrics.

**Tasks:**
1. Write a batch script that loads events from `merged_events.jsonl`, reconstructs code, runs AST eval, and annotates events
2. Compute the confusion matrix: AST × execution × reasoning
3. Compute LEG_ast rates and compare with LEG_text rates
4. Identify cases where specs need updating (ast_correct=False but exec_pass=True)
5. Update specs as needed

**Validation:** 
- AST_correct AND exec_pass should have >80% overlap with evaluator's `interpretable_success`
- AST_correct AND NOT exec_pass should be a proper subset of evaluator's LEG_v2
- Lucky_fix_ast should be rare (<2%)

**Exit criteria:** Validated confusion matrix with reasonable agreement between AST and existing metrics.

### Phase 4: Expand case coverage (2-3 days)

**Goal:** AST specs for all measurable cases.

**Tasks:**
1. Write specs for remaining A/B/C families: early_return (3), partial_rollback (3), partial_update (3), lazy_init (3), effect_order (3), use_before_set (3), index_misalign (3), missing_branch (3), temporal_drift (3), silent_default (3)
2. Write specs for additional singletons where feasible
3. Validate each spec against reference fix and buggy code
4. Re-run back-test on expanded spec set

**Exit criteria:** ~50-55 cases with validated AST specs.

### Phase 5: Analysis scripts and paper integration (1-2 days)

**Goal:** Analysis outputs ready for the paper.

**Tasks:**
1. Write `analysis/run_ast_analysis.py` producing the metrics in Section 15
2. Generate tables and figures: AST×exec confusion matrix, LEG_ast vs LEG_text, family-level AST signal strength
3. Draft paper language for the AST evaluation methodology section
4. Determine whether to revise LEG definitions based on data

**Exit criteria:** Analysis script produces all required metrics; preliminary paper text drafted.

### Phase 6: Decision on LEG redefinition (deliberation, not code)

**Goal:** Based on Phase 3-5 data, decide whether to:
- Use LEG_ast as the primary LEG metric
- Keep LEG_text as primary and LEG_ast as supplementary
- Report both side by side
- Revise the paper's evaluation framing

This is a judgment call informed by data, not an implementation task.

---

## 19. Recommended File/Module Layout

```
evaluation/
  ast_eval.py              # Core AST evaluation module
  ast_patterns.py          # Pattern matcher implementations (14 pattern types)
  ast_specs_loader.py      # Load and validate ast_specs.json

data/
  ast_specs.json           # Per-case AST pattern specifications
  reference_fixes/         # (existing) Canonical fix code

tests/
  test_ast_eval.py         # Unit tests for ast_eval
  test_ast_patterns.py     # Unit tests for each pattern type
  test_ast_specs.py        # Validation that specs pass on ref fixes, fail on buggy

analysis/
  run_ast_analysis.py      # AST-conditioned analysis script

scripts/
  ast_mutator.py           # (existing) — shared finder utilities used by ast_patterns.py
  backtest_ast_eval.py     # Batch back-testing script for existing events
```

---

## 20. Minimal First Milestone

**The smallest implementation that yields publishable value:**

1. Write AST specs for 10 cases: alias_config_a/b/c, mutable_default_a/b/c, retry_dup_a/b/c, invariant_partial_fail
2. Implement 4 pattern types: method_call_present, default_param_none, break_in_loop, try_except_compensation
3. Run AST evaluation on existing experimental data for these 10 cases
4. Produce one table: the 2×2 confusion matrix (AST × execution) for these 10 cases across all models and conditions
5. Compute LEG_ast rate and compare with LEG_text rate for these cases

**This is achievable in 3-4 focused days.** If the confusion matrix shows meaningful disagreement between AST and execution (i.e., there ARE cases where correct structure + failed execution), the investment in Phases 4-6 is justified. If `ast_correct ≈ exec_pass` for all cases, the entire AST measurement adds no information beyond execution and should be deprioritized.

**The 10-case subset is chosen because:**
- alias_config: highest-confidence AST pattern (single `.copy()` call), the family where LEG harms were documented
- mutable_default: canonical Python idiom fix, unambiguous AST
- retry_dup: single `break` statement, binary presence/absence
- invariant_partial_fail: the paper's strongest finding (lean takes 4%→96%), structurally distinctive (try/except + rollback)

If this 10-case pilot shows that AST-correct-but-execution-failed cases exist at a non-trivial rate, the paper can make the claim: "We validated the LEG finding with a fully deterministic structural analysis that does not rely on any LLM evaluator."

---

## 21. Open Design Questions

### Q1: Should AST evaluation feed into the retry loop?

Currently, retry decisions in `retry_v2.py` use execution pass/fail and optionally mismatch critique. Should a future version use `ast_score` to decide whether to retry? For example: if `ast_correct=True` but `exec_pass=False`, the retry hint could say "your structural fix looks correct; check for import issues or argument errors."

**Recommendation:** Not in MVP. This would couple AST evaluation into the intervention, violating the measurement-intervention separation principle. Explore post-paper.

### Q2: Should the classifier prompt include AST results?

If AST evaluation runs before the classifier (Stage 5.5), the classifier COULD be informed that "the model's code is structurally correct." This might improve classifier accuracy by reducing false negatives.

**Recommendation:** No. AST and classifier should be independent signals for the paper. Coupling them would make it impossible to measure classifier reliability against AST as a reference standard.

### Q3: How should cases with `ast_measurable: false` be handled in aggregate metrics?

If we report "LEG_ast rate = 15%" but this is computed only on AST-measurable cases, and the non-measurable cases have different LEG rates, the number is not directly comparable to "LEG_text rate = 18%" (computed on all cases).

**Recommendation:** Report AST metrics ONLY for the AST-measurable subset. For comparison, also report LEG_text on the same subset. The paper should state clearly: "The following analysis is restricted to the N cases for which deterministic structural evaluation was feasible."

### Q4: How to handle cases where the model restructures the code significantly?

Some models (especially stronger ones) refactor the code beyond the minimal fix — extracting helpers, renaming functions, reorganizing imports. The canonical fix pattern might not be recognizable in the restructured code even though the fix is correct.

**Recommendation:** For the MVP, these cases will be `ast_correct = False` and will show up as `exec_pass AND NOT ast_correct` (lucky_fix_ast) in the confusion matrix. If this rate is high (>10%), it means AST evaluation is too strict and needs a fallback: check whether the reference fix's key statements exist ANYWHERE in the model's output, not just in the expected function.

### Q5: Should pattern specs be auto-generated from reference fix diffs?

The AST diff between buggy code and reference fix could theoretically be computed automatically and converted into a pattern spec.

**Recommendation:** Not for MVP. Auto-generated specs would be too rigid (they'd capture the exact reference fix's structure without alternatives). Manual authoring forces the spec writer to think about what's essential vs incidental. Post-MVP, auto-generation could produce draft specs that are manually reviewed and expanded.

---

## 22. Concrete Next-Step Checklist

- [ ] Classify all 73 cases as AST-measurable or not (spreadsheet or JSON)
- [ ] Write `data/ast_specs.json` with specs for 10 pilot cases
- [ ] Validate each spec: run on reference fix (must pass) and buggy code (must fail)
- [ ] Implement `evaluation/ast_patterns.py` with 4 core pattern types
- [ ] Implement `evaluation/ast_eval.py` with spec loading + per-file evaluation + case aggregation
- [ ] Write `tests/test_ast_patterns.py` with positive/negative tests per pattern type
- [ ] Write `tests/test_ast_eval.py` with end-to-end tests on pilot cases
- [ ] Write `scripts/backtest_ast_eval.py` to run AST eval on existing merged_events.jsonl
- [ ] Run back-test on 10 pilot cases; produce confusion matrix
- [ ] Review confusion matrix: if LEG_ast signal is non-trivial, proceed to Phase 4
- [ ] If proceeding: expand ast_specs.json to ~50 cases
- [ ] Integrate `ast_evaluate()` into `execution_v2.run_v2()` at Stage 5.5
- [ ] Add AST fields to `derive_v2_signals()` and `assemble_v2_result()`
- [ ] Write `analysis/run_ast_analysis.py` for paper metrics
- [ ] Draft paper methodology section for AST evaluation

---

## Appendix A: Concrete Case Examples

### Example 1: alias_config_a — Best case for AST measurement

**Canonical fix:** In `config.py::create_config()`, change `return DEFAULTS` to `return DEFAULTS.copy()`.

**AST spec:**
```json
{
  "required_patterns": [{
    "type": "method_call_present",
    "function": "create_config",
    "method": "copy",
    "object_contains": "DEFAULTS",
    "alternatives": [
      {"type": "builtin_call", "func": "dict", "arg_contains": "DEFAULTS"},
      {"type": "dict_unpacking"}
    ]
  }],
  "forbidden_patterns": [{
    "type": "return_bare_name",
    "function": "create_config",
    "name": "DEFAULTS"
  }]
}
```

**What the matcher checks:**
1. Parse model's `config.py` output
2. Find `create_config` function definition
3. Walk its AST looking for `ast.Call` where `func.attr == 'copy'` and `func.value` resolves to `DEFAULTS`
4. Also check alternatives: `dict(DEFAULTS)`, `{**DEFAULTS}`
5. Check forbidden: `return` of bare `ast.Name(id='DEFAULTS')` without wrapping

**False positives:** Model adds `.copy()` on a different dict in the same function → mitigated by `object_contains: "DEFAULTS"`.

**False negatives:** Model renames `DEFAULTS` to `DEFAULT_CONFIG` → would fail. Mitigation: could add name-insensitive matching, but this case specifically tests whether the model understands DEFAULTS is the module-level dict.

**Assessment:** Excellent case for AST. Binary, unambiguous, high confidence.

### Example 2: invariant_partial_fail — Multi-pattern case

**Canonical fix:** In `transfer_service.py::execute_transfer()`:
1. Wrap credit phase in try/except
2. Add `sender.balance += amount` in except handler (rollback)
3. Re-raise the exception

**AST spec:**
```json
{
  "required_patterns": [
    {"type": "try_except_present", "function": "execute_transfer", "severity": "critical"},
    {"type": "augmented_assign_in_except", "target": "sender.balance", "op": "Add", "severity": "critical"},
    {"type": "raise_in_except", "severity": "important"}
  ]
}
```

**ast_score:** 3 patterns. If model adds try/except (1/3 = 0.33), adds try/except + rollback (2/3 = 0.67), or all three (1.0).

**False positives:** Model adds try/except but with wrong compensation (e.g., `sender.balance -= amount` — subtracting instead of adding). The augmented_assign pattern checks `op=Add`, so subtraction would not match. Good.

**False negatives:** Model uses a different rollback strategy (e.g., save original balance, restore in except). This is semantically correct but AST-different. Mitigation: add alternative pattern `assign_in_except(target="sender.balance", source="original_balance")`.

**Assessment:** Strong case for AST. The try/except + rollback pattern is structurally distinctive. This is the paper's most important finding (lean takes 4%→96%), so AST validation here is particularly valuable.

### Example 3: stale_cache_c — Cross-boundary multi-layer case

**Canonical fix:** In `catalog.py::update_product()`, add `invalidate_local(product_id)` after `invalidate_shared(product_id)`. Two-layer cache: shared was invalidated but local was not.

**AST spec:**
```json
{
  "required_patterns": [{
    "type": "function_call_present",
    "function": "update_product",
    "call_name": "invalidate_local",
    "severity": "critical"
  }]
}
```

**False positives:** Model adds `invalidate_local` somewhere else in the file. Mitigated by `function: "update_product"` scoping.

**False negatives:** Model renames the function or inlines the invalidation logic. Unlikely given the code structure.

**Assessment:** Good case for AST. Single call addition, clear target.

### Example 4: retry_dup_b — Break in retry loop

**Canonical fix:** In `sender.py::send_with_retry()`, add `break` after successful `send()` call inside the for loop.

**AST spec:**
```json
{
  "required_patterns": [{
    "type": "break_in_loop",
    "function": "send_with_retry",
    "context": "for_try_body",
    "severity": "critical"
  }]
}
```

**False positives:** Model adds break in wrong place (after except, not after success). Mitigated by requiring break in `try.body`, not `try.handlers`.

**Assessment:** Excellent case. Binary, unambiguous.

### Example 5: hidden_dep_multihop — Function call substitution (cross-file)

**Canonical fix:** In `user_service.py::save_user()`, change `refresh_user_snapshot(user)` to `sync_user_to_cache(user)`.

**AST spec:**
```json
{
  "target_files": ["user_service.py"],
  "required_patterns": [{
    "type": "function_call_name",
    "function": "save_user",
    "expected_call": "sync_user_to_cache",
    "severity": "critical"
  }],
  "forbidden_patterns": [{
    "type": "function_call_name",
    "function": "save_user",
    "expected_call": "refresh_user_snapshot",
    "severity": "critical"
  }]
}
```

**Assessment:** Excellent. The fix is literally changing one function name to another. AST detects this trivially.

### Example 6: lazy_init_c — Module-level removal + inline call (hard case)

**Canonical fix:** Remove `_client_cfg = get_config()` at module level. In functions that used `_client_cfg`, replace with inline `get_config()` calls.

**AST spec:**
```json
{
  "required_patterns": [
    {"type": "module_level_absent", "assignment_name": "_client_cfg", "severity": "critical"},
    {"type": "inline_call_in_function", "function": "get_endpoint", "call_name": "get_config", "severity": "important"}
  ]
}
```

**Assessment:** Medium difficulty. The first pattern (module-level removal) is clean. The second (inline call) is harder — the model might store the result in a local variable first. This case pushes the limits of AST measurement.

### Example 7: effect_order_a — Statement relocation into loop (LEG-help case)

From the LEG report, effect_order cases showed LEG-help signals for some models under lean.

**Canonical fix:** Move `snapshot()` call from after the for loop to inside the for loop body.

**AST spec:**
```json
{
  "required_patterns": [{
    "type": "call_inside_loop",
    "function": "process_batch",
    "loop_type": "for",
    "call_name": "snapshot",
    "severity": "critical"
  }]
}
```

**Assessment:** Good case. The structural question — is `snapshot()` inside or outside the loop? — is cleanly expressible in AST.

### Example 8: false_fix_deadlock — Poor case for AST

**Canonical fix:** Change lock acquisition order so both functions lock A then B (consistent ordering).

The buggy code has `transfer_a_to_b` locking A then B, and `transfer_b_to_a` locking B then A. The fix requires `transfer_b_to_a` to also lock A then B.

**Why AST struggles:** Both `lock(A); lock(B)` and `lock(B); lock(A)` are structurally identical — two `ast.Call` nodes with different arguments. AST would need to check the argument VALUES, which are variable references whose meaning depends on the calling context.

**Recommendation:** Mark as `ast_measurable: false`. Rely on execution evaluation for this case.

### Example 9: Reconstruction artifact case — alias_config_c with haiku

The LEG report documented that Haiku had 78% reconstruction failure rates due to triple-quoted Python in JSON. For these events:
- Reconstruction fails → `ast_eval.assessable = False`
- No AST signal is produced
- This correctly excludes these events from AST-conditioned metrics
- The strict/recon-only split still applies

---

## Appendix B: Is This Actually Worth Doing?

### Blunt assessment

**Is this likely to materially strengthen the project?**

Yes, conditionally. The project's central claim — that LEG exists and can be mitigated — currently rests on an LLM evaluator's judgment of "mechanism correctness." A skeptical reviewer can attack this: "Your LEG measurement uses one LLM to judge another LLM's reasoning. How do you know the evaluator is reliable?"

AST measurement provides an answer: "For N cases covering M families, we verified the structural fix pattern with a fully deterministic analysis. The LEG signal persists: X% of structurally correct fixes fail execution."

**This converts a soft claim into a hard claim.** That's the publication value.

**What exact claims does it strengthen?**

1. "LEG is real, not a measurement artifact" — strongest improvement
2. "Lean/LEG scaffolding increases structural correctness" — clean new metric
3. "Reconstruction artifacts distort interpretation" — AST adds another decomposition axis
4. "Lucky fixes are rare" — deterministic confirmation

**What claims does it NOT strengthen?**

1. "Models understand bug mechanisms" — AST doesn't measure understanding
2. "Sycophancy is a problem for evaluators" — AST sidesteps evaluators, doesn't measure their bias
3. "Multi-agent debate improves reasoning" — unrelated to AST

**Is it strong enough to justify revising the paper's evaluation framing?**

If the pilot data (10 cases × 25K events) shows a meaningful LEG_ast signal, yes. The paper could add a section: "Objective Structural Evaluation" that presents the confusion matrix alongside the LLM-based evaluation, strengthening the entire results section.

If the pilot data shows `ast_correct ≈ exec_pass` (no structural correctness beyond execution), then AST adds no information and should not be in the paper. This is the honest assessment.

**What is the smallest implementation that still yields publishable value?**

The 10-case pilot described in Section 20: 3-4 days of work, producing one confusion matrix table and one LEG_ast comparison. This is publishable as a methodological contribution even if the main paper doesn't reorganize around it.

**Bottom line:** The expected value is high, the downside risk is 3-4 days of wasted work if the signal doesn't materialize, and the upside is converting the paper's softest claim into its hardest one. That's a good bet.
