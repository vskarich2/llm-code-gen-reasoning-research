# AST-Based Structural Measurement — Revised Plan v2

**Date:** 2026-04-03
**Status:** PLAN ONLY — NO IMPLEMENTATION
**Supersedes:** ast_measurement_plan_v1.md
**Core revision:** Retrospective-first design. Validate offline on existing logs before any pipeline integration.

---

## Changes from v1

| v1 Flaw | Fix in v2 |
|---------|-----------|
| Pipeline integration first | Retrospective analysis first. Pipeline integration is Phase 4, not Phase 1. |
| Assumed AST is useful before proving it | Phases 1-2 are validation-only. If the signal is garbage, we stop. |
| Vague about data sources | Specifies exact log paths, event fields, and raw response structure. |
| Ignored reconstruction confound | Explicit strict / recon-only split at every stage. |
| Over-designed spec format before testing | Starts with 10 cases, hardcoded patterns, no JSON spec file. |
| Drifted into "AST analysis tool" | Tied every metric to the core thesis: decomposing reasoning vs structural vs runtime failure. |

---

## 1. Retrospective AST Evaluation System (MANDATORY FIRST PHASE)

### Architecture

This is an **offline analysis pass over existing logs**. Zero new LLM calls. Zero pipeline changes.

```
┌─────────────────────────────────────┐
│  EXISTING LOGS (already on disk)    │
│                                     │
│  merged_events.jsonl (case.end)     │
│  ├─ payload._extracted_code         │
│  ├─ payload.pass                    │
│  ├─ payload.v2_category             │
│  ├─ payload.reconstruction_status   │
│  ├─ payload.mechanism_correct       │
│  └─ context.condition               │
│                                     │
│  calls/{N}.json (raw responses)     │
│  └─ response_raw → JSON → files{}  │
│     (per-file code for multi-file)  │
│                                     │
│  data/reference_fixes/{case}.py     │
│  code_snippets_v2/{case}/*.py       │
│  data/cases_v2.json                 │
└──────────┬──────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  RETROSPECTIVE AST EVALUATOR         │
│  (new script, runs offline)          │
│                                      │
│  For each case.end event:            │
│  1. Extract reconstructed code       │
│  2. Parse AST (ast.parse)            │
│  3. Match against fix patterns       │
│  4. Emit: ast_correct, ast_score     │
│                                      │
│  Join with existing labels:          │
│  - exec_pass                         │
│  - v2_category (LEG, lucky, etc)     │
│  - mechanism_correct                 │
│  - reconstruction_status             │
└──────────┬──────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  ANALYSIS OUTPUT                     │
│                                      │
│  AST × Exec confusion matrix        │
│  AST × LEG_text comparison          │
│  Strict vs recon-only split          │
│  Per-case / family / model / cond    │
└──────────────────────────────────────┘
```

### Data sources used

**1. `logs/v2_targeted_50trial_canonical/merged_events.jsonl`** — Primary dataset. 7,695 case.end events, 13 cases, 4 models × 3 conditions × ~50 trials. 6,937 with successful reconstruction. 1,282 LEG_v2 events.

**2. `logs/v2_full_ablation/*/merged_events.jsonl`** — Full 58-case single-trial ablation across 3 models. 174 events each. Used for breadth validation.

**3. `data/reference_fixes/{case_id}.py`** — 74 canonical fix files. The AST supervision signal.

**4. `code_snippets_v2/{case_id}/*.py`** — Buggy code. Needed to compute structural diff.

**5. `data/cases_v2.json`** — `ground_truth_bug.fix_pattern`, `reference_fix.file`, `reference_fix.function`, case metadata.

### Where the code is in the logs

| Need | Location |
|------|----------|
| Primary target file (reconstructed) | `event.payload._extracted_code` (string) |
| All files (multi-file cases) | Raw call JSON: `calls/{N}.json` → `response_raw` → parse JSON → `files` dict |
| Execution pass/fail | `event.payload.pass` (bool) |
| LEG category | `event.payload.v2_category` (string, e.g., "LEG_v2") |
| Mechanism correct | `event.payload.mechanism_correct` (bool) |
| Reconstruction status | `event.payload.reconstruction_status` ("SUCCESS" or null/other) |
| Model | `event.model` |
| Condition | `event.context.condition` |
| Case ID | `event.case_id` |

---

## 2. What AST Correctness Means — Precisely

### Definition

**AST correctness = the model's generated code contains the structural fix pattern that distinguishes the reference fix from the buggy code.**

This is NOT:
- Exact AST equality with the reference fix
- Full semantic equivalence
- Code string equality
- "Good code"

It IS:
- Presence of the specific structural change that constitutes the fix
- Absence of the specific structural signature of the bug
- Measurable by walking the AST and checking node types, positions, and relationships

### Binary + graded

- **`ast_correct`** (bool): ALL critical patterns matched AND no critical forbidden patterns found
- **`ast_score`** (float, 0.0–1.0): fraction of critical patterns matched. For single-pattern cases, this is binary. For multi-pattern cases (e.g., partial_rollback needs try/except + release call), this provides partial credit.

---

## 3. Pattern Detection Rules for Real Case Families

For each family, the detection rule is derived from the structural diff between the buggy code and reference fix. These are the 10 pilot cases.

### alias_config (a, b, c) — `.copy()` addition

**Buggy AST:** `create_config` returns `DEFAULTS` (bare `ast.Name` on RHS of assignment or return)

**Fixed AST:** `create_config` returns `DEFAULTS.copy()` (`ast.Call` with `func=ast.Attribute(attr='copy')`)

**Detection:**
```
In function "create_config":
  REQUIRED: an ast.Call where func.attr == "copy" AND func.value refers to DEFAULTS
  OR: ast.Call where func.id == "dict" with DEFAULTS as arg
  OR: ast.Dict with **DEFAULTS unpacking
  FORBIDDEN: ast.Assign or ast.Return with bare ast.Name("DEFAULTS") as the value
             (without wrapping .copy() / dict() / unpacking)
```

**Alternatives accepted:** `DEFAULTS.copy()`, `dict(DEFAULTS)`, `{**DEFAULTS}`, `copy.deepcopy(DEFAULTS)`

**False positive risk:** LOW. `.copy()` on a different dict in the same function. Mitigated by checking the object is `DEFAULTS`.

**False negative risk:** LOW. Model renames `DEFAULTS`. Unlikely given the code structure.

**AST-measurable confidence:** VERY HIGH.

---

### mutable_default (a, b, c) — None default + guard

**Buggy AST:** Function default argument is `ast.List([])` or `ast.Set()` or `ast.Dict()`

**Fixed AST:** Default is `ast.Constant(None)` + body contains `if param is None: param = []`

**Detection:**
```
In target function:
  REQUIRED: default for target param is ast.Constant(value=None)
  REQUIRED: function body contains ast.If where:
    test is ast.Compare with ast.Is and ast.Constant(None)
    body contains ast.Assign to the same param
  FORBIDDEN: default for target param is ast.List or ast.Set or ast.Dict
```

**Target functions per case:**
- mutable_default_a: `enqueue`, param `queue`
- mutable_default_b: `process_batch`, param `seen`
- mutable_default_c: `with_history` decorator's inner default

**AST-measurable confidence:** VERY HIGH.

---

### retry_dup (a, b, c) — Break after success in retry loop

**Buggy AST:** `for` loop with `try/except` in body; no `break` after the success call

**Fixed AST:** `break` statement after the success call inside `try.body`

**Detection:**
```
In target function:
  REQUIRED: inside ast.For → ast.Try.body, an ast.Break node exists
            after the success call (send / send_with_retry)
  FORBIDDEN: for loop with try body that has no break and no return after success
```

**Target functions:**
- retry_dup_a: `retry_send`
- retry_dup_b: `send_with_retry`
- retry_dup_c: `ingest` in `pipeline.py`

**Note on retry_dup_c:** The break is needed in the OUTER loop (`ingest`), not the inner retry. The model must add break in `pipeline.py`, not `sender.py`. sender.py's `send_with_retry` already has break.

**AST-measurable confidence:** VERY HIGH.

---

### stale_cache (a, b, c) — Cache invalidation after write

**Buggy AST:** `update_product` has DB write but no cache invalidation call

**Fixed AST:** Cache invalidation call added after DB write

**Detection:**
```
In function "update_product":
  REQUIRED: ast.Call to invalidation function AFTER the db write call
  
  Case-specific invalidation functions:
  - stale_cache_a: _cache.pop(product_id, None)
  - stale_cache_b: cache.invalidate(product_id)
  - stale_cache_c: invalidate_local(product_id)  [invalidate_shared already present]
```

**Alternative accepted:** Any call that removes/clears the cache entry (`.pop()`, `del _cache[key]`, `.invalidate()`, `.clear()`)

**AST-measurable confidence:** HIGH.

---

### effect_order_a — Statement relocation into loop

**Buggy AST:** `snapshot()` call is a sibling of the `for` loop (same indent level, after loop)

**Fixed AST:** `snapshot()` call is inside `ast.For.body`

**Detection:**
```
In function "process_batch":
  REQUIRED: ast.Call to snapshot() is a child of ast.For.body
  FORBIDDEN: ast.Call to snapshot() is a sibling of ast.For (at function body level)
```

**AST-measurable confidence:** HIGH. The structural question — inside or outside the loop — maps directly to AST parent-child relationships.

---

### use_before_set_a — Return path fix

**Buggy AST:** Single `return _last_result` at function end, reached on both truthy and falsy data

**Fixed AST:** `return result` inside `if data:` block + `return []` for falsy path

**Detection:**
```
In function "transform":
  REQUIRED: ast.Return inside ast.If.body (the truthy branch returns directly)
  REQUIRED: ast.Return at function level that returns empty list (not _last_result)
  FORBIDDEN: single ast.Return of ast.Name("_last_result") as only return
```

**AST-measurable confidence:** MEDIUM. The model might fix this differently (e.g., `result = []` before the if, return result at end). Alternative pattern needed.

---

### invariant_partial_fail — Try/except with rollback

**Buggy AST:** Sequential mutations with no exception handling around the failure-prone section

**Fixed AST:** `ast.Try` wrapping the credit phase, `ast.ExceptHandler` with `sender.balance += amount` and `raise`

**Detection:**
```
In function "execute_transfer":
  REQUIRED: ast.Try node present that wraps the credit phase
  REQUIRED: ast.ExceptHandler body contains:
    - ast.AugAssign with target "sender.balance" and op ast.Add
    - ast.Raise (bare raise to re-raise)
  FORBIDDEN: sequential debit→credit with no Try wrapping
```

**AST-measurable confidence:** HIGH. The try/except + rollback + re-raise is a distinctive structural pattern.

---

### partial_rollback_b — Compensation call in except handler

**Buggy AST:** `except ValueError: raise` (bare re-raise, no compensation)

**Fixed AST:** `except ValueError: release(product_id, qty); raise`

**Detection:**
```
In function "place_order":
  REQUIRED: ast.ExceptHandler body contains ast.Call to "release"
  REQUIRED: ast.Raise in same handler (re-raise after compensation)
  FORBIDDEN: ast.ExceptHandler with only ast.Raise (no compensation call)
```

**AST-measurable confidence:** HIGH.

---

### hidden_dep_multihop — Function call name substitution

**Buggy AST:** `save_user` calls `refresh_user_snapshot(user)`

**Fixed AST:** `save_user` calls `sync_user_to_cache(user)`

**Detection:**
```
In function "save_user":
  REQUIRED: ast.Call where func.id == "sync_user_to_cache"
  FORBIDDEN: ast.Call where func.id == "refresh_user_snapshot"
```

**AST-measurable confidence:** VERY HIGH. Literal function name comparison.

---

### wrong_condition_b — Operator correction

**Buggy AST:** `ast.BoolOp(op=ast.Or())` combining two conditions

**Fixed AST:** `ast.BoolOp(op=ast.And())`

**Detection:**
```
In target function:
  REQUIRED: ast.BoolOp with op=ast.And in the rate-limit check
  FORBIDDEN: ast.BoolOp with op=ast.Or in same location
```

**AST-measurable confidence:** VERY HIGH.

---

## 4. Cases That Are NOT Reliably AST-Measurable

These cases should be excluded from AST-conditioned analysis:

| Case | Why NOT measurable |
|------|--------------------|
| false_fix_deadlock | Lock ordering is semantic (which variable is locked first), not structural |
| lost_update | "Atomic" is a runtime property; many valid structural implementations |
| check_then_act | Same as lost_update |
| async_race_lock | Lock presence vs absence is AST-detectable, but correctness depends on runtime semantics |
| ordering_dependency | Buffering strategy is structurally diverse |
| config_shadowing | Fix is changing a literal value (5 → 30); AST can see the Constant node but verifying the VALUE is fragile |
| commit_gate | Fix requires restoring two function calls that look like many other calls |

For the 13 cases in the primary dataset (v2_targeted_50trial):
- **AST-measurable:** alias_config_c, cache_invalidation_order, hidden_dep_multihop, invariant_partial_fail, lazy_init_b, mutable_default_b, mutable_default_c, stale_cache_a, wrong_condition_b, early_return_a (10 of 13)
- **NOT AST-measurable:** lost_update, commit_gate, config_shadowing (3 of 13)

This means **77% of the primary dataset is AST-assessable**, covering 5,925 of 7,695 events.

---

## 5. Multi-File Handling

### The problem

For single-file cases (alias_config_a, mutable_default_a, etc.), `payload._extracted_code` contains the target file's code directly. For multi-file cases (partial_rollback_b, stale_cache_c, etc.), we need per-file code.

### Data access strategy

**Primary:** `payload._extracted_code` — the reconstructed target file. Sufficient for all cases where the fix is in a single file (the one specified in `reference_fix.file`).

**Fallback for multi-file cases:** Parse the raw model response from `calls/{N}.json` → `response_raw` → JSON → `files` dict. This gives per-file code. Multi-file cases where the fix spans multiple files (e.g., partial_rollback_c: fix in `order_service.py`, affects `inventory.py` and `payment.py`) typically only require AST checking on the primary target file — the test validates the cross-file behavior.

### Aggregation rule

For the retrospective analysis (Phases 1-2), **check only the primary target file** specified in `cases_v2.json` → `reference_fix.file`. This is where the structural fix lives.

Rationale: In all 73 cases, the `reference_fix.file` field identifies THE file that changes. Supporting files (inventory.py, cache.py, etc.) are not modified in the fix. The model might modify them, but we don't penalize or reward that — we only check whether the target file contains the fix pattern.

If Phase 3 reveals cases where this is insufficient, we extend to multi-file checking at that point.

---

## 6. The Reconstruction Confound — Mandatory Split

### Why this matters

The LEG report found that 4 of 10 "LEG hurts" results were 100% reconstruction artifacts. Models generated correct code that was unparseable as JSON. If we compute AST metrics on all events, we'll miss events where reconstruction failed but the code was actually structurally correct.

### Required split

Every AST metric MUST be computed in two modes:

**1. Strict (all case.end events):**
- If `reconstruction_status != "SUCCESS"`: `ast_correct = None` (not assessable)
- If `reconstruction_status == "SUCCESS"`: run AST pattern matching
- Report: "Of N events with successful reconstruction, X% were ast_correct"

**2. Recon-only (events where reconstruction succeeded):**
- Same as strict, but denominators only count events where reconstruction succeeded
- This matches the LEG report's methodology

**3. Recovery mode (stretch goal):**
- For events where reconstruction failed, attempt to parse code from the raw response `calls/{N}.json`
- If parseable, run AST matching
- This reveals the "code was right but JSON was wrong" artifact

### Implementation

```python
for event in events:
    recon_status = event['payload'].get('reconstruction_status')
    if recon_status == 'SUCCESS':
        code = event['payload']['_extracted_code']
        ast_result = match_patterns(code, case_spec)
        # → assessable, ast_correct, ast_score
    else:
        ast_result = {'assessable': False, 'reason': 'reconstruction_failed'}
```

---

## 7. New Metrics — The Whole Point

### Core decomposition (2×2 matrix)

For each event where AST is assessable:

```
                     exec_pass=T          exec_pass=F
ast_correct=T    TRUE_SUCCESS          AST_CORRECT_FAILURE
ast_correct=F    LUCKY_FIX_AST         FULL_FAILURE
```

### Category definitions

| Category | Definition | What it tells us |
|----------|-----------|-----------------|
| **TRUE_SUCCESS** | ast_correct AND exec_pass | Model got structure right AND execution confirms it |
| **AST_CORRECT_FAILURE** | ast_correct AND NOT exec_pass | **Cleanest LEG proxy.** Correct structural fix, but something else fails (runtime error, test contract mismatch, import issue, reconstruction artifact) |
| **LUCKY_FIX_AST** | NOT ast_correct AND exec_pass | Model passed tests without the canonical fix pattern. Either: alternative fix, weak test, or coincidence |
| **FULL_FAILURE** | NOT ast_correct AND NOT exec_pass | Wrong structure, wrong execution |
| **RECON_FAIL** | reconstruction failed | Not assessable by AST or execution |

### Derived metrics

| Metric | Formula | Purpose |
|--------|---------|---------|
| `ast_correct_rate` | mean(ast_correct) where assessable | Structural fix success rate |
| `ast_pass_agreement` | mean(ast_correct == exec_pass) where assessable | How often structural and behavioral verdicts agree |
| `LEG_ast_rate` | mean(ast_correct AND NOT exec_pass) where assessable | Objective LEG measurement |
| `LEG_text_rate` | mean(v2_category == "LEG_v2") | Existing LLM-based LEG measurement |
| `lucky_fix_ast_rate` | mean(NOT ast_correct AND exec_pass) where assessable | Alternative fix or weak test rate |
| `ast_text_agreement` | mean(ast_correct == mechanism_correct) where both assessable | How well the LLM evaluator agrees with AST |

### Connection to core thesis

The project's thesis: **models exhibit a gap between correct reasoning and correct execution.** Currently, "correct reasoning" is measured by an LLM evaluator. AST provides a non-LLM measurement of a closely related property: "correct structural transformation."

The specific questions AST answers:

| Question | How AST answers it |
|----------|-------------------|
| Do "LEG cases" actually show correct structural fixes? | Compute ast_correct for events where v2_category == "LEG_v2". If high → LEG is validated structurally. If low → the LLM evaluator was wrong about mechanism correctness. |
| How often does the LLM evaluator disagree with AST? | Compare mechanism_correct vs ast_correct. Disagreements reveal evaluator noise. |
| Does LEG scaffolding improve structural correctness? | Compare ast_correct_rate across conditions (baseline vs lean vs LEG). Independent of execution. |
| Are LEG improvements structural or just formatting? | Compare ast_correct_rate strict vs recon-only. If they diverge → formatting effect, not structural. |
| What fraction of failures are structural vs runtime? | ast_correct AND exec_fail → runtime failure. NOT ast_correct AND exec_fail → structural failure. |

### The key decomposition AST enables

Without AST, failure = undifferentiated blob. With AST:

```
FAILURE = 
  STRUCTURAL_FAILURE (wrong fix pattern)
  + RUNTIME_FAILURE (right fix pattern, execution still fails)
  + RECON_FAILURE (code might be right but couldn't parse it)
```

This is a massive upgrade. "LEG" becomes testable: does the model produce the right structure? If yes, the gap is between structure and runtime. If no, the gap is between reasoning and structure.

---

## 8. Phased Implementation Plan

### Phase 1 — Retrospective AST Prototype (3-4 days)

**Goal:** Run AST evaluation on existing logs for 10 pilot cases. Produce the 2×2 matrix. Determine if the signal is real.

**Tasks:**
1. Write `scripts/ast_retro_eval.py` — standalone script, no pipeline changes
2. Implement 7 pattern matchers covering the 10 pilot cases:
   - `check_copy_call(tree, func_name, object_name)` — alias_config
   - `check_none_default_with_guard(tree, func_name, param_name)` — mutable_default
   - `check_break_in_retry(tree, func_name)` — retry_dup
   - `check_call_added(tree, func_name, call_name)` — stale_cache, partial_rollback
   - `check_call_inside_loop(tree, func_name, call_name)` — effect_order
   - `check_try_except_with_compensation(tree, func_name)` — invariant_partial_fail
   - `check_call_name_substitution(tree, func_name, expected, forbidden)` — hidden_dep_multihop
3. Hardcode pattern specs per case (dict in the script, not a separate file)
4. Load `merged_events.jsonl` from `v2_targeted_50trial_canonical/`
5. For each `case.end` event with `reconstruction_status == "SUCCESS"`:
   - Extract `_extracted_code`
   - Parse AST
   - Run case-specific pattern matcher
   - Record: `(case_id, model, condition, trial, ast_correct, exec_pass, v2_category, mechanism_correct)`
6. Output CSV with all results
7. Compute:
   - 2×2 confusion matrix (AST × exec) per case
   - LEG_ast rate per (case, model, condition)
   - Comparison: LEG_ast vs LEG_text (v2_category == "LEG_v2")
   - Strict vs recon-only split

**Validation criteria:**
- Reference fix → ast_correct = True for all 10 cases
- Buggy code → ast_correct = False for all 10 cases
- At least 3 fabricated wrong fixes per case → ast_correct = False

**Exit criteria:**
- The 2×2 matrix shows non-trivial AST_CORRECT_FAILURE count (>2% of assessable events)
- If ast_correct ≈ exec_pass for all cases (agreement > 95%), AST adds minimal information and Phases 3-4 should be deprioritized

---

### Phase 2 — Scale to Full Logs (1-2 days)

**Goal:** Run AST evaluation across ALL available log files. Generate publication-quality tables.

**Tasks:**
1. Extend pattern matchers to cover all AST-measurable cases (up to ~50)
2. Run on all `merged_events.jsonl` files (multiple experiments)
3. Generate:
   - AST × exec confusion matrix by model
   - AST × exec confusion matrix by family
   - AST correct rate by condition (baseline vs lean vs LEG)
   - AST-correct failure rate vs LEG_text rate comparison
   - Strict vs recon-only decomposition of AST metrics
4. Run on v2_full_ablation logs (all 58 cases, lower trial count) for breadth check
5. Identify cases where lucky_fix_ast rate is high → spec may need alternative patterns

**Exit criteria:**
- All target metrics computed
- Results are interpretable and tell a coherent story
- Lucky_fix_ast rate < 5% for well-specified cases (if higher, review specs)

---

### Phase 3 — Paper Integration (1-2 days)

**Goal:** Draft paper text and determine how AST metrics change the story.

**Tasks:**
1. Write analysis summary comparing AST-based LEG with LLM-based LEG
2. Generate figures: scatter (ast_correct_rate vs pass_rate per case), confusion matrix heatmaps
3. Determine: does AST validate or challenge the existing LEG findings?
4. Draft methodology section for AST evaluation
5. Decision: should LEG_ast replace LEG_text as primary metric, supplement it, or be a validation only?

**Exit criteria:**
- Paper text drafted
- Decision made on LEG metric role

---

### Phase 4 — Pipeline Integration (ONLY AFTER PHASES 1-3)

**Goal:** If AST measurement proves valuable, integrate into the live pipeline.

**Tasks:**
1. Extract pattern matchers into `evaluation/ast_eval.py`
2. Add `ast_evaluate()` call to `execution_v2.run_v2()` after reconstruction
3. Add AST fields to event dict
4. Update `derive_v2_signals()` to include AST-based categories
5. Update analysis scripts to consume AST fields

**This phase is optional.** If retrospective analysis in Phases 1-3 produces all needed results, pipeline integration can be deferred.

---

## 9. Concrete Implementation Spec for Phase 1

### Script: `scripts/ast_retro_eval.py`

```
Input:  merged_events.jsonl path(s)
        data/reference_fixes/ directory
        code_snippets_v2/ directory
        
Output: ast_retro_results.csv with columns:
        case_id, model, condition, trial, 
        reconstruction_success, ast_assessable, ast_correct, ast_score,
        exec_pass, v2_category, mechanism_correct, LEG_text, LEG_ast,
        lucky_fix_ast, true_success_ast
```

### Pattern spec (hardcoded dict in script for Phase 1)

```python
CASE_PATTERNS = {
    "alias_config_c": {
        "target_file_suffix": "config.py",
        "checks": [
            {"type": "copy_call", "function": "create_config", "object": "DEFAULTS"},
        ],
        "anti_checks": [
            {"type": "bare_name_return", "function": "create_config", "name": "DEFAULTS"},
        ],
    },
    "mutable_default_b": {
        "target_file_suffix": "queue.py",
        "checks": [
            {"type": "none_default", "function": "process_batch", "param": "seen"},
        ],
        "anti_checks": [
            {"type": "mutable_default", "function": "process_batch", "param": "seen"},
        ],
    },
    "stale_cache_a": {
        "target_file_suffix": "catalog.py",
        "checks": [
            {"type": "call_present", "function": "update_product", 
             "call_names": ["pop", "invalidate", "clear", "__delitem__"]},
        ],
    },
    "invariant_partial_fail": {
        "target_file_suffix": "transfer_service.py",
        "checks": [
            {"type": "try_except_present", "function": "execute_transfer"},
            {"type": "compensation_in_except", "function": "execute_transfer",
             "pattern": "sender.balance"},
        ],
    },
    "hidden_dep_multihop": {
        "target_file_suffix": "user_service.py",
        "checks": [
            {"type": "call_name", "function": "save_user", 
             "expected": "sync_user_to_cache"},
        ],
        "anti_checks": [
            {"type": "call_name", "function": "save_user",
             "expected": "refresh_user_snapshot"},
        ],
    },
    # ... remaining 5 cases
}
```

### Pattern matcher implementations (7 functions)

Each takes an `ast.Module` tree and check parameters, returns bool.

```python
def check_copy_call(tree: ast.Module, func_name: str, object_name: str) -> bool:
    """Check that func_name's body contains object_name.copy() or dict(object_name)."""
    func = find_function(tree, func_name)
    if func is None:
        return False
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            # .copy() pattern
            if (isinstance(node.func, ast.Attribute) 
                and node.func.attr == "copy"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == object_name):
                return True
            # dict() pattern
            if (isinstance(node.func, ast.Name) 
                and node.func.id == "dict"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == object_name):
                return True
    return False
```

The other 6 follow the same structure. Each is 15-30 lines of AST walking. No magic.

### Validation step (MUST RUN BEFORE ANALYZING LOGS)

```python
# For each case in CASE_PATTERNS:
#   1. Parse reference fix → ast_correct MUST be True
#   2. Parse buggy code → ast_correct MUST be False
# If any fail, the pattern spec is wrong. Fix it before proceeding.
```

---

## 10. Expected Outcomes and Decision Points

### If the pilot succeeds (likely scenario)

The 2×2 matrix shows:
- TRUE_SUCCESS ≈ 60-70% (matches current ~63% pass rate on these cases)
- AST_CORRECT_FAILURE ≈ 5-15% (the LEG signal)
- LUCKY_FIX_AST ≈ 1-3% (very few, consistent with existing lucky_fix_v2 count of 13)
- FULL_FAILURE ≈ 20-30%

If AST_CORRECT_FAILURE is non-trivial, then:
- "LEG exists" is now backed by a deterministic structural signal
- We can compare LEG_ast with LEG_text to measure evaluator reliability
- The paper gains a section on "Objective Structural Evaluation"
- Proceed to Phase 2

### If AST is uninformative (possible scenario)

The 2×2 matrix shows:
- ast_correct ≈ exec_pass for >95% of events
- AST_CORRECT_FAILURE ≈ 0-1%

This means the structural fix is nearly always sufficient for execution success. The gap between reasoning and execution is NOT a structural translation gap — it's something else (e.g., import errors, argument mismatches, test-contract issues).

If this happens:
- AST is validated as a CONFIRMATION tool (it confirms execution verdicts) but not a DISCRIMINATION tool (it doesn't reveal new categories)
- Do NOT proceed to Phase 4 (pipeline integration)
- Possibly include as a brief validation paragraph in the paper

### If LUCKY_FIX_AST is high (unlikely but important)

If >10% of exec-passing events are NOT ast_correct:
- Either the AST specs are too strict (missing alternative patterns)
- Or the tests are too weak (passing code that doesn't actually fix the bug)
- Manual review of these events will reveal which
- Update specs with missing alternatives; re-run

---

## 11. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| AST specs too strict → high false-negative rate | Medium | Validate on reference fixes first; add alternatives when back-test reveals them |
| AST specs too loose → false-positive rate | Low | Anti-checks (forbidden patterns) catch the buggy pattern |
| `_extracted_code` is sometimes empty or partial | Low | Check `reconstruction_status == "SUCCESS"` before parsing |
| Multi-file cases have fix in non-primary file | Low | For Phase 1, target file only; extend in Phase 2 if needed |
| Reconstruction artifacts inflate AST_CORRECT_FAILURE | Medium | Mandatory strict/recon-only split; recovery mode as stretch goal |
| Model uses a valid fix not in the spec | Medium | LUCKY_FIX_AST > 5% triggers manual review and spec expansion |
| Pattern matching is brittle for complex fixes | Low for pilot cases | Pilot cases chosen for high AST confidence; complex cases excluded |

---

## 12. Hard Constraints

- **NO new LLM calls.** This is purely offline analysis.
- **MUST operate on existing logs.** No new experiment runs needed for Phases 1-3.
- **MUST separate strict vs recon-only.** Every metric computed both ways.
- **MUST use cases_v2.json ground_truth_bug as supervision.** Pattern specs derive from fix_pattern + reference fixes.
- **MUST produce quantitative outputs comparable to LEG report.** Same granularity: per-case × per-model × per-condition.
- **MUST validate on real cases.** Pattern specs tested on reference fixes AND buggy code before analyzing model outputs.
- **NO pipeline changes in Phases 1-3.** Scripts only.
- **NO spec file format before prototype works.** Hardcoded dict in Phase 1. Extract to JSON only if Phase 2 proceeds.

---

## 13. Recommended File Layout

### Phase 1 (minimal)

```
scripts/
  ast_retro_eval.py          # Standalone retrospective evaluator
  ast_pattern_matchers.py    # 7 pattern matcher functions
  ast_validate_specs.py      # Validate specs against ref fixes + buggy code

analysis/
  ast_retro_results.csv      # Output of ast_retro_eval.py
  run_ast_analysis.py        # Analysis script consuming the CSV
```

### Phase 4 (if reached)

```
evaluation/
  ast_eval.py                # Pipeline-integrated version
  ast_patterns.py            # Extracted from scripts/ast_pattern_matchers.py

data/
  ast_specs.json             # Formalized specs (only after validation)
```

---

## 14. Concrete Next-Step Checklist

- [ ] Write `scripts/ast_pattern_matchers.py` with 7 matchers
- [ ] Write `scripts/ast_validate_specs.py` — validate each matcher on reference fix (True) and buggy code (False)
- [ ] Run validation: all 10 pilot cases must pass
- [ ] Write `scripts/ast_retro_eval.py` — load events, run matchers, output CSV
- [ ] Run on `v2_targeted_50trial_canonical/merged_events.jsonl` (7,695 events)
- [ ] Compute 2×2 matrix: AST × exec (strict mode)
- [ ] Compute 2×2 matrix: AST × exec (recon-only mode)
- [ ] Compute LEG_ast rate and compare to LEG_text rate per (case, model, condition)
- [ ] Compute ast_text_agreement (AST vs mechanism_correct)
- [ ] Review LUCKY_FIX_AST events manually — are specs too strict?
- [ ] Decision: is AST_CORRECT_FAILURE > 2%? If yes → Phase 2. If no → stop.
- [ ] If proceeding: extend to full ablation logs + more cases
- [ ] Draft paper methodology section
