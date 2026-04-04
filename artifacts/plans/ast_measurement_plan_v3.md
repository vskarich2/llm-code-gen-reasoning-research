# AST-Based Structural Measurement — Plan v3 (Data-Driven)

**Date:** 2026-04-03
**Status:** PLAN ONLY
**Supersedes:** v1 (pipeline-first, rejected), v2 (concept-driven, rejected)
**Core revision:** Every AST rule is DERIVED FROM `cases_v2.json` fields. No hand-waving.

---

## Changes from v2

| v2 Flaw | v3 Fix |
|---------|--------|
| AST rules were informally described per-family | AST rules are mechanically derived from `ground_truth_bug.fix_pattern` + `reference_fix.file` + `reference_fix.function` |
| No spec registry; rules scattered in prose | Spec registry: `fix_pattern` string → AST rule callable. Declarative, no if/else spaghetti. |
| Multi-file handling was vague | Target is ONLY `reference_fix.file::reference_fix.function`. Nothing else scored. |
| Partial fixes not defined | Explicit: correct pattern at correct location = 1; correct pattern wrong location = 0; partial pattern = fractional |
| Invariants not connected to AST rules | Each AST rule is justified by its invariant from `ground_truth_bug.invariant` |
| Validation was abstract | Validation is: run AST rule on reference fix (must pass) AND on buggy code (must fail), for every case |

---

## 1. AST Specification Derived from cases_v2.json

### Ground truth fields used

Every case in `data/cases_v2.json` provides:

```json
{
  "ground_truth_bug": {
    "type": "shared_reference_mutation",
    "location": "config.py::create_config",
    "invariant": "create_config must return a dict independent of DEFAULTS",
    "fix_pattern": "DEFAULTS.copy()"
  },
  "reference_fix": {
    "file": "code_snippets_v2/alias_config_a/config.py",
    "function": "create_config",
    "diff_summary": "Apply DEFAULTS.copy()",
    "lines_changed": 1
  }
}
```

**These four fields fully specify the AST check:**
- `reference_fix.file` → which file to parse
- `reference_fix.function` → which function to scope the check to
- `fix_pattern` → what structural change to detect
- `invariant` → why this structural change is the correct one

### The mapping

```
AST_spec(case_id) = {
    target_file:     cases_v2[case_id].reference_fix.file  (filename only, strip path)
    target_function: cases_v2[case_id].reference_fix.function
    ast_rule:        FIX_PATTERN_RULES[cases_v2[case_id].ground_truth_bug.fix_pattern]
    invariant:       cases_v2[case_id].ground_truth_bug.invariant
}
```

`FIX_PATTERN_RULES` is the spec registry (Section 2). It maps `fix_pattern` strings to AST rule callables.

---

## 2. Fix-Pattern → AST Rule Registry

There are **33 distinct `fix_pattern` values** across 73 cases. They group into **16 AST rule types**. Each rule type covers 1-6 fix patterns.

### The registry

```python
# ast_spec_registry.py — Declarative mapping from fix_pattern to AST rule

FIX_PATTERN_RULES = {

    # ── TYPE 1: Copy-on-return ──────────────────────────────────────
    # Invariant: must return independent dict, not alias
    # AST: Call to .copy() or dict() on the return/assign value
    "DEFAULTS.copy()": Rule(
        checker=check_copy_or_dict_call,
        params={"object_name": "DEFAULTS"},
        anti_checker=check_bare_name_assign,
        anti_params={"name": "DEFAULTS"},
    ),

    # ── TYPE 2: None-default with guard ─────────────────────────────
    # Invariant: each call starts with fresh container
    # AST: default is None + if-None guard in body
    "None default + create inside function": Rule(
        checker=check_none_default_with_guard,
        params={},  # param name extracted from reference fix
        anti_checker=check_mutable_default_arg,
        anti_params={},
    ),

    # ── TYPE 3: Break-on-success in retry loop ──────────────────────
    # Invariant: each message exactly once
    # AST: break statement after success call inside for>try
    "break on success / idempotency guard": Rule(
        checker=check_break_after_success_in_loop,
        params={},
        anti_checker=check_loop_without_break,
        anti_params={},
    ),

    # ── TYPE 4: Cache invalidation after write ──────────────────────
    # Invariant: get must return current case_data after update
    # AST: invalidation call present in function, after the write
    "invalidate cache after write": Rule(
        checker=check_invalidation_call_after_write,
        params={"invalidation_names": ["pop", "invalidate", "invalidate_local",
                                        "invalidate_shared", "clear", "__delitem__"]},
        anti_checker=None,  # absence of call = bug; no separate anti-pattern
        anti_params={},
    ),

    # ── TYPE 5: Side-effect relocation into loop ────────────────────
    # Invariant: one side effect per item processed
    # AST: target call is inside For.body, not a sibling of For
    "move effect inside loop": Rule(
        checker=check_call_inside_for_body,
        params={"call_names": ["snapshot", "emit_event", "audit_log"]},
        anti_checker=check_call_outside_for,
        anti_params={"call_names": ["snapshot", "emit_event", "audit_log"]},
    ),

    # ── TYPE 6: Variable init before conditional ────────────────────
    # Invariant: handle empty input without NameError
    # AST: assignment to result var before the if/for that uses it
    "initialize variable before conditional": Rule(
        checker=check_init_before_conditional,
        params={},  # variable name from reference fix diff
        anti_checker=None,
        anti_params={},
    ),

    # ── TYPE 7: Try/except with rollback ────────────────────────────
    # Invariant: failed operation must not leave partial state
    # AST: Try node wrapping critical section + compensation call in except
    "try/except with rollback": Rule(
        checker=check_try_except_with_compensation,
        params={},  # compensation calls from reference fix
        anti_checker=check_bare_raise_without_compensation,
        anti_params={},
    ),
    "try/except around credit with sender.balance += amount in except block": Rule(
        checker=check_try_except_with_compensation,
        params={"compensation_pattern": "sender.balance"},
        anti_checker=check_bare_raise_without_compensation,
        anti_params={},
    ),

    # ── TYPE 8: Ordering constraint (compute before transform) ──────
    # Invariant: raw_stats must reflect untransformed case_data
    # AST: call to raw_stats before call to transform in function body
    "compute raw_stats before transform": Rule(
        checker=check_call_ordering,
        params={"before_call": "raw_stats", "after_call": "transform"},
        anti_checker=check_call_ordering,
        anti_params={"before_call": "transform", "after_call": "raw_stats"},
    ),

    # ── TYPE 9: Missing branch addition ─────────────────────────────
    # Invariant: all valid roles must receive correct permissions
    # AST: if/elif chain or dict has entry for the missing case
    "add missing branch/case": Rule(
        checker=check_branch_count_increased,
        params={},  # expected count derived from reference fix
        anti_checker=None,
        anti_params={},
    ),

    # ── TYPE 10: Operator correction ────────────────────────────────
    # Invariant: boundary condition handled correctly
    # AST: correct operator type in the comparison
    "correct comparison operator": Rule(
        checker=check_comparison_operator,
        params={},  # expected op from reference fix
        anti_checker=None,
        anti_params={},
    ),

    # ── TYPE 11: Record before early return ─────────────────────────
    # Invariant: ledger/audit must have entry for every call
    # AST: audit call before Return inside if-branch, or in finally
    "record before early return or in finally": Rule(
        checker=check_call_before_return_in_branch,
        params={"call_names": ["record", "ledger", "log_charge",
                                "audit", "append"]},
        anti_checker=None,
        anti_params={},
    ),

    # ── TYPE 12: Function call substitution ─────────────────────────
    # Invariant: save_user must use cache_put (overwrite) semantics
    # AST: expected call name present, forbidden call name absent
    "keep sync_user_to_cache (uses cache_put) in save_user, do not replace with refresh_user_snapshot": Rule(
        checker=check_call_name_present,
        params={"expected_call": "sync_user_to_cache"},
        anti_checker=check_call_name_present,
        anti_params={"expected_call": "refresh_user_snapshot"},
    ),

    # ── TYPE 13: Parallel structure consistency ─────────────────────
    # Invariant: parallel arrays must stay aligned
    # AST: same operation type on all parallel structures
    "update all parallel structures consistently": Rule(
        checker=check_parallel_operations_consistent,
        params={},
        anti_checker=None,
        anti_params={},
    ),

    # ── TYPE 14: Dependent field sync ───────────────────────────────
    # Invariant: all dependent fields updated when primary changes
    # AST: multiple assignment targets in same function
    "update display_name/full_name/verified when source changes": Rule(
        checker=check_dependent_field_assignments,
        params={},  # field names from reference fix
        anti_checker=None,
        anti_params={},
    ),

    # ── TYPE 15: Key name correction ────────────────────────────────
    # Invariant: flag lookup returns configured value
    # AST: string literal in subscript/dict access matches expected key
    "fix key name to match dict": Rule(
        checker=check_key_literal_matches,
        params={},  # expected key from reference fix
        anti_checker=None,
        anti_params={},
    ),

    # ── TYPE 16: Lazy access instead of eager capture ───────────────
    # Invariant: reset must affect subsequent calls
    # AST: module-level assignment removed; function body has inline call
    "lazy access instead of eager capture": Rule(
        checker=check_lazy_not_eager,
        params={},
        anti_checker=check_module_level_eager_capture,
        anti_params={},
    ),

    # ── TYPE 17: Keep ordering dependency ───────────────────────────
    # Invariant: read_record returns latest value after update
    # AST: invalidation call before set call in function
    "keep invalidate call before set in update_record": Rule(
        checker=check_call_ordering,
        params={"before_call": "cache_invalidate", "after_call": "cache_conditional_set"},
        anti_checker=None,
        anti_params={},
    ),

    # ── TYPE 18: Restore removed function calls ─────────────────────
    # Invariant: commit and freeze_view both required
    # AST: both calls present in function body
    "restore commit(st) and freeze_view(st) in process_batch": Rule(
        checker=check_calls_all_present,
        params={"required_calls": ["commit", "freeze_view"]},
        anti_checker=None,
        anti_params={},
    ),

    # ── TYPE 19: Keep locking structure ─────────────────────────────
    # Invariant: requires atomic read-increment-read
    # AST: try_lock/unlock calls present
    "keep process_item with try_lock/unlock, do not replace with quick_increment": Rule(
        checker=check_calls_all_present,
        params={"required_calls": ["try_lock", "unlock"]},
        anti_checker=check_call_name_present,
        anti_params={"expected_call": "quick_increment"},
    ),

    # ── TYPE 20: Cache writeback ────────────────────────────────────
    # Invariant: subsequent get must not refetch
    # AST: cache assignment after fetch
    "_cache[key] = result after fetch()": Rule(
        checker=check_cache_assignment_present,
        params={},
        anti_checker=None,
        anti_params={},
    ),

    # ── NOT AST-MEASURABLE (runtime semantics only) ─────────────────

    "canonical lock order: always A before B": None,  # lock ordering is semantic
    "combine read+write into single atomic step": None,  # atomicity is runtime
    "combine check+act into single atomic step": None,  # atomicity is runtime
    "buffer early items, drain on init": None,  # complex control flow
    "timeout: 5 -> timeout: 30 in DEFAULTS": None,  # literal value check is fragile
    "enable/disable global flag around create_invoice call, or propagate param through billing to pricing": None,  # multi-path propagation
    "remove write_cached call from update_product": Rule(  # removing a call IS measurable
        checker=check_call_name_absent,
        params={"absent_call": "write_cached"},
        anti_checker=check_call_name_present,
        anti_params={"expected_call": "write_cached"},
    ),
    # Singletons with unique patterns:
    "_config.clear() then _config.update(new_values)": Rule(
        checker=check_calls_all_present,
        params={"required_calls": ["clear", "update"]},
        anti_checker=None,
        anti_params={},
    ),
    "%H:%M:%S instead of %Y-%m-%d": None,  # literal string check
    "offset + limit instead of offset + limit - 1": None,  # arithmetic expression check
    "reverse=True in sorted()": Rule(
        checker=check_keyword_arg_present,
        params={"func_name": "sorted", "kwarg": "reverse", "expected_value": True},
        anti_checker=None,
        anti_params={},
    ),
    "parts[i].strip() in parse()": Rule(
        checker=check_method_call_on_subscript,
        params={"method": "strip"},
        anti_checker=None,
        anti_params={},
    ),
    "raise NotFoundError instead of return None": Rule(
        checker=check_raise_present,
        params={"exception_name": "NotFoundError"},
        anti_checker=None,
        anti_params={},
    ),
    "register(admin_login, on_admin_login)": Rule(
        checker=check_call_with_args,
        params={"func_name": "register", "expected_args": ["admin_login", "on_admin_login"]},
        anti_checker=None,
        anti_params={},
    ),
    'Change _dispatch_table["priority"] to handle_priority': Rule(
        checker=check_dict_value_is_name,
        params={"dict_name": "_dispatch_table", "key": "priority", "expected_value": "handle_priority"},
        anti_checker=None,
        anti_params={},
    ),
    "Change REQUIRED to INVALID_FORMAT for email format check": Rule(
        checker=check_string_literal_in_function,
        params={"expected": "INVALID_FORMAT"},
        anti_checker=check_string_literal_in_function,
        anti_params={"expected": "REQUIRED"},
    ),
    "Add modified_at = time.time() AND reindex(user_id, new_name)": Rule(
        checker=check_calls_all_present,
        params={"required_calls": ["time", "reindex"]},
        anti_checker=None,
        anti_params={},
    ),
    "Add row backfill and version bump": Rule(
        checker=check_assignments_present,
        params={"targets": ["role", "version"]},
        anti_checker=None,
        anti_params={},
    ),
    "Move reset() before loop, not inside loop": Rule(
        checker=check_call_before_for,
        params={"call_name": "reset"},
        anti_checker=check_call_inside_for_body,
        anti_params={"call_names": ["reset"]},
    ),
    "update(overrides) then update(base)": Rule(
        checker=check_call_ordering,
        params={"before_call": "update", "after_call": "update"},
        anti_checker=None,
        anti_params={},
        # Note: checks that two update calls exist; order is base second
    ),
}
```

### AST-measurability classification

**AST-measurable (67 of 73 cases):** All cases whose `fix_pattern` maps to a non-None Rule.

**NOT AST-measurable (6 cases):**

| Case | fix_pattern | Why |
|------|-----------|-----|
| false_fix_deadlock | "canonical lock order: always A before B" | Lock ordering = semantic variable identity, not structural |
| lost_update | "combine read+write into single atomic step" | Atomicity = runtime synchronization property |
| check_then_act | "combine check+act into single atomic step" | Same as lost_update |
| ordering_dependency | "buffer early items, drain on init" | Complex stateful control flow with many valid structures |
| config_shadowing | "timeout: 5 -> timeout: 30 in DEFAULTS" | Literal value check; model might use a valid different value |
| feature_flag_drift | "enable/disable global flag..." | Multi-path parameter propagation too structurally diverse |

**For the primary 13-case dataset** (v2_targeted_50trial): **10 of 13 measurable** (lost_update, commit_gate, config_shadowing are excluded). Covers 5,925 of 7,695 events.

---

## 3. AST Rule Implementations — Exact Specifications

Each rule takes `(tree: ast.Module, function_name: str, params: dict)` and returns `bool`. The function_name comes from `reference_fix.function`. The tree comes from parsing the model's code for `reference_fix.file`.

### Rule: `check_copy_or_dict_call`
**Derived from invariant:** "must return a dict independent of DEFAULTS"
```
Walk target function. Return True if ANY of:
  1. ast.Call where func is ast.Attribute(attr="copy") 
     and func.value is ast.Name(id=params["object_name"])
  2. ast.Call where func is ast.Name(id="dict") 
     and first arg is ast.Name(id=params["object_name"])
  3. ast.Dict containing ast.Starred(value=ast.Name(id=params["object_name"]))
```

### Rule: `check_bare_name_assign` (anti-check)
```
Walk target function. Return True if:
  ast.Assign where value is bare ast.Name(id=params["name"]) 
  AND that assignment's target is later returned
  (i.e., the function returns the raw reference without copying)
```

### Rule: `check_none_default_with_guard`
**Derived from invariant:** "each call must start with empty container"
```
In target function's arguments:
  Find the parameter that had a mutable default in the buggy version
  (identified by diffing buggy vs model output defaults)
  Check: default is ast.Constant(value=None)
In target function's body:
  Check: ast.If where test contains ast.Is + ast.Constant(None)
  for the same parameter name
Both must be True.
```

### Rule: `check_mutable_default_arg` (anti-check)
```
In target function's arguments:
  Return True if any default is ast.List or ast.Set or ast.Dict (mutable literal)
```

### Rule: `check_break_after_success_in_loop`
**Derived from invariant:** "each message appears exactly once"
```
Walk target function. Find ast.For node.
Within For.body, find ast.Try node.
Within Try.body, check for ast.Break.
  OR: after the Try node (still inside For.body), check for ast.Break.
  OR: within Try.body, check for ast.Return (also terminates the loop).
Return True if any found.
```

### Rule: `check_loop_without_break` (anti-check)
```
Walk target function. Find ast.For containing ast.Try.
Return True if there is NO ast.Break anywhere inside the For body
AND no ast.Return inside Try.body after the success call.
```

### Rule: `check_invalidation_call_after_write`
**Derived from invariant:** "get must return current data after update"
```
Walk target function body statements in order.
Track: has_write = False
For each statement:
  If statement contains a call matching a write pattern 
  (e.g., .update(), assignment to _db[key], db_write()):
    has_write = True
  If has_write AND statement contains a call matching any of 
  params["invalidation_names"]:
    return True
Return False.
```

**This is ordering-sensitive.** The invalidation must come AFTER the write. A model that invalidates before writing would pass a naive "call present" check but fail this one.

### Rule: `check_call_inside_for_body`
**Derived from invariant:** "one side effect per item processed"
```
Walk target function. Find ast.For node.
Within For.body (recursively), check for ast.Call 
where func matches any of params["call_names"].
Return True if found.
```

### Rule: `check_call_outside_for` (anti-check)
```
Walk target function body at top level (not inside For).
Check for ast.Call matching params["call_names"].
Return True if found at function body level (outside any For).
```

### Rule: `check_init_before_conditional`
**Derived from invariant:** "handle empty input without NameError"
```
Walk target function body statements in order.
Identify the variable that is set inside a conditional in the buggy code.
(Derived from reference fix diff: the added assignment's target name.)
Check: an ast.Assign with that target name appears BEFORE the ast.If/ast.For
that uses it.
Return True if found.
```

### Rule: `check_try_except_with_compensation`
**Derived from invariant:** "failed operation must not leave partial state" / "balance conserved"
```
Walk target function. Find ast.Try node.
Check: ast.Try has at least one ExceptHandler.
In the ExceptHandler body:
  Check: contains at least one ast.Call (the compensation call)
  If params has "compensation_pattern":
    Check: compensation call/assignment references that pattern
  Check: handler body contains ast.Raise (re-raise)
All must be True.
```

### Rule: `check_bare_raise_without_compensation` (anti-check)
```
Walk target function. Find ast.Try with ExceptHandler.
Return True if handler body contains ONLY ast.Raise (no calls before it).
```

### Rule: `check_call_ordering`
**Derived from invariant:** "raw_stats must reflect untransformed data" / "invalidate before set"
```
Walk target function body statements in order.
Record position (index) of first call matching params["before_call"].
Record position of first call matching params["after_call"].
Return True if before_position < after_position.
```

### Rule: `check_call_name_present`
**Derived from invariant:** "must use specific function"
```
Walk target function. 
Return True if ast.Call where func.id == params["expected_call"]
or func.attr == params["expected_call"].
```

### Rule: `check_call_name_absent`
```
Inverse of check_call_name_present. Return True if NO such call exists.
```

### Rule: `check_calls_all_present`
```
For each name in params["required_calls"]:
  Walk target function looking for call to that name.
Return True only if ALL required calls found.
```

### Rule: `check_branch_count_increased`
```
Parse buggy code for same function. Count if/elif branches.
Parse model code for same function. Count if/elif branches.
Return True if model count > buggy count.
```

### Rule: `check_comparison_operator`
```
Walk target function. Find the ast.Compare node at the known location
(matched by surrounding context from reference fix).
Check that ops[0] matches the expected operator type 
(derived from reference fix: GtE, LtE, And, Or, etc.)
```

### Rule: `check_call_before_return_in_branch`
```
Walk target function. Find ast.If that contains ast.Return.
Check: before the Return in the If body, there is a call matching
params["call_names"].
OR: the function uses ast.Try with ast.Finally containing the call.
```

### Remaining rules follow the same structure. Each is 10-25 lines of AST walking.

---

## 4. Target Scoping: reference_fix.file and reference_fix.function ONLY

**Rule:** AST evaluation checks ONLY the file and function specified in the case's `reference_fix` fields. Nothing else.

**Why:** The dataset explicitly tells us where the fix is. Scoring other files introduces noise. A model that correctly fixes `config.py::create_config` but adds unnecessary changes to `middleware.py` should score `ast_correct = True`.

**Implementation:**
```python
def evaluate_case(model_code: str, case: dict) -> ASTResult:
    ref = case["reference_fix"]
    target_file = os.path.basename(ref["file"])  # e.g., "config.py"
    target_func = ref["function"]                 # e.g., "create_config"
    
    tree = ast.parse(model_code)
    func_node = find_function_in_tree(tree, target_func)
    if func_node is None:
        return ASTResult(assessable=True, correct=False, 
                         reason="target function not found")
    
    rule = get_rule_for_case(case)
    if rule is None:
        return ASTResult(assessable=False, reason="not ast-measurable")
    
    check_passed = rule.checker(tree, target_func, rule.params)
    anti_passed = True
    if rule.anti_checker:
        anti_found = rule.anti_checker(tree, target_func, rule.anti_params)
        anti_passed = not anti_found  # anti-pattern must be ABSENT
    
    return ASTResult(
        assessable=True,
        correct=check_passed and anti_passed,
        check_passed=check_passed,
        anti_passed=anti_passed,
    )
```

**Multi-file cases:** The model outputs multiple files. We extract only the one matching `reference_fix.file` (by filename). For the 13-case primary dataset:

| Case | Target file | Target function |
|------|------------|----------------|
| alias_config_c | config.py | create_config |
| stale_cache_a | catalog.py | update_product |
| mutable_default_b | queue.py | process_batch |
| mutable_default_c | queue.py | with_history |
| hidden_dep_multihop | user_service.py | save_user |
| invariant_partial_fail | transfer_service.py | execute_transfer |
| cache_invalidation_order | service.py | update_record |
| wrong_condition_b | limiter.py | is_allowed |
| lazy_init_b | client.py | get_db_url |
| early_return_a | payment.py | process_payment |
| lost_update | (NOT AST-MEASURABLE) | — |
| commit_gate | pipeline.py | process_batch |
| config_shadowing | (NOT AST-MEASURABLE) | — |

---

## 5. Partial Fix Detection

### Categories

| Outcome | Definition | AST Signal |
|---------|-----------|------------|
| **ast_correct** | Required pattern present at target function + anti-pattern absent | checker=True, anti_checker≠found |
| **ast_partial** | Required pattern present but anti-pattern also present | checker=True, anti_checker=found |
| **ast_wrong_location** | Required pattern exists somewhere in the file but NOT in the target function | file-level match but func-level miss |
| **ast_incorrect** | Required pattern absent | checker=False |

### How to detect wrong-location

```python
# After check_passed fails on target function:
# Search the entire file
for func_node in get_all_functions(tree):
    if rule.checker(tree, func_node.name, rule.params):
        return ASTResult(correct=False, partial="wrong_location",
                         found_in=func_node.name)
```

This distinguishes "model applied .copy() but in the wrong function" from "model didn't add .copy() at all."

### Scoring

For multi-pattern cases (e.g., partial_rollback with try/except + compensation + re-raise):
```
ast_score = patterns_matched / patterns_required
```
This gives 0.0, 0.33, 0.67, or 1.0 for a 3-pattern case.

---

## 6. Invariant-Justified AST Rules

Every AST rule MUST trace to the case's invariant. This is not optional — it's what distinguishes "checking the right structural property" from "arbitrary pattern matching."

| fix_pattern | invariant | AST rule | justification |
|------------|-----------|----------|--------------|
| DEFAULTS.copy() | "must return dict independent of DEFAULTS" | check_copy_or_dict_call | .copy()/dict() creates independent dict → invariant satisfied |
| None default + create inside | "each call must start with empty container" | check_none_default_with_guard | None default + guard prevents accumulation → invariant satisfied |
| break on success | "each message exactly once" | check_break_in_loop | break prevents re-execution → invariant satisfied |
| invalidate cache after write | "get must return current data after update" | check_invalidation_call_after_write | invalidation removes stale entry → invariant satisfied |
| move effect inside loop | "one side effect per item" | check_call_inside_for_body | call inside loop = per-item execution → invariant satisfied |
| initialize before conditional | "handle empty input without NameError" | check_init_before_conditional | pre-init ensures variable always defined → invariant satisfied |
| try/except with rollback | "failed operation must not leave partial state" | check_try_except_with_compensation | compensation undoes partial mutation → invariant satisfied |
| compute before transform | "raw_stats must reflect untransformed data" | check_call_ordering | ordering ensures correct input data → invariant satisfied |
| keep sync_user_to_cache | "must use cache_put (overwrite)" | check_call_name_present | correct function uses overwrite semantics → invariant satisfied |

If an AST rule cannot be justified by the invariant, it is WRONG and must be redesigned.

---

## 7. Retrospective Evaluation Pipeline

### Data flow (concrete)

```python
# scripts/ast_retro_eval.py

import ast, json, os

def main(events_path, cases_path, snippets_dir):
    cases = load_cases(cases_path)  # case_data/cases_v2.json
    results = []

    for event in load_case_end_events(events_path):
        case_id = event["case_id"]
        case = cases[case_id]
        
        # Step 1: Extract reconstructed code
        recon_status = event["payload"].get("reconstruction_status")
        if recon_status != "SUCCESS":
            results.append(make_row(event, assessable=False, reason="recon_failed"))
            continue
        
        code = event["payload"].get("_extracted_code", "")
        if not code.strip():
            results.append(make_row(event, assessable=False, reason="empty_code"))
            continue
        
        # Step 2: Parse AST
        try:
            tree = ast.parse(code)
        except SyntaxError:
            results.append(make_row(event, assessable=False, reason="syntax_error"))
            continue
        
        # Step 3: Lookup AST spec from case metadata
        rule = get_rule_for_case(case)
        if rule is None:
            results.append(make_row(event, assessable=False, reason="not_measurable"))
            continue
        
        target_func = case["reference_fix"]["function"]
        
        # Step 4: Run rule
        check = rule.checker(tree, target_func, rule.params)
        anti = True
        if rule.anti_checker:
            anti = not rule.anti_checker(tree, target_func, rule.anti_params)
        
        ast_correct = check and anti
        
        # Step 5: Join with existing labels
        exec_pass = event["payload"].get("pass", False)
        v2_cat = event["payload"].get("v2_category", "")
        mech_correct = event["payload"].get("mechanism_correct", False)
        
        # Step 6: Derive combined categories
        if ast_correct and exec_pass:
            ast_category = "TRUE_SUCCESS"
        elif ast_correct and not exec_pass:
            ast_category = "AST_CORRECT_FAILURE"  # ← cleanest LEG proxy
        elif not ast_correct and exec_pass:
            ast_category = "LUCKY_FIX_AST"
        else:
            ast_category = "FULL_FAILURE"
        
        results.append(make_row(
            event, assessable=True, ast_correct=ast_correct,
            check_passed=check, anti_passed=anti,
            ast_category=ast_category, exec_pass=exec_pass,
            v2_category=v2_cat, mechanism_correct=mech_correct,
        ))
    
    write_csv(results, "analysis/ast_retro_results.csv")
```

### Output schema (CSV)

```
case_id, model, condition, trial,
reconstruction_success, ast_assessable, ast_correct, check_passed, anti_passed,
ast_category, exec_pass, v2_category, mechanism_correct,
LEG_ast, LEG_text, lucky_fix_ast
```

Where:
- `LEG_ast = ast_correct AND NOT exec_pass`
- `LEG_text = (v2_category == "LEG_v2")`
- `lucky_fix_ast = NOT ast_correct AND exec_pass`

---

## 8. Mandatory Strict vs Recon-Only Split

Every metric is computed twice:

**Strict mode:** Denominator = all case.end events for the case.
- Events with `reconstruction_status != "SUCCESS"` contribute to the denominator but not to ast_correct count.
- `ast_correct_rate_strict = count(ast_correct=True) / count(all events for case)`

**Recon-only mode:** Denominator = events with successful reconstruction only.
- `ast_correct_rate_recon = count(ast_correct=True) / count(recon_success events)`

**Why both:** The LEG report showed that 4 of 10 "LEG hurts" were reconstruction artifacts. If `ast_correct_rate_strict` and `ast_correct_rate_recon` diverge, it means reconstruction failures (not structural incorrectness) are driving the metric.

---

## 9. Connection to Core Thesis

### What AST replaces

The current LEG definition depends on the LLM classifier's `mechanism_correct` signal. AST replaces this with an objective structural check for the specific dimension that `mechanism_correct` is trying to capture: "did the model produce the right fix?"

**Current:** LEG_v2 = mechanism_correct (LLM judge) AND NOT alignment_positive (LLM judge) AND NOT exec_pass

**Proposed:** LEG_ast = ast_correct (deterministic) AND NOT exec_pass

The LLM judge is noisy, subjective, and susceptible to sycophancy (documented in RAUDIT/RCA papers). AST is deterministic and auditable.

### What AST does NOT replace

- The LLM evaluator's `mechanism_identified` dimension (whether the model articulated the bug mechanism in prose). AST cannot assess verbal reasoning.
- Execution evaluation. Execution remains the behavioral ground truth.

### The decomposition AST enables (without LLM evaluator)

```
ALL FAILURES decompose into:
  
  STRUCTURAL FAILURE (ast_incorrect AND exec_fail)
    → Model did not produce the correct fix pattern
    → This is a CODE GENERATION failure
  
  RUNTIME FAILURE (ast_correct AND exec_fail)  
    → Model produced correct fix pattern but execution still fails
    → This is the purest LEG signal: structure was right, something else broke
    → Could be: reconstruction artifact, import error, test contract mismatch,
      semantic error within structurally correct pattern
  
  RECONSTRUCTION FAILURE (recon_failed)
    → Cannot assess structure at all
    → Separate bucket
```

**This decomposition does not require an LLM evaluator.** It is entirely deterministic.

### Specific questions this answers

1. **Do LEG-labeled cases actually have correct structural fixes?**
   Compute: `P(ast_correct | v2_category == "LEG_v2")`.
   If high → the LLM evaluator's LEG judgment is validated by objective structure.
   If low → the LLM evaluator was calling things "mechanism correct" when the structure was wrong.

2. **Does lean scaffolding improve STRUCTURAL correctness (not just pass rate)?**
   Compare `ast_correct_rate` between baseline and lean conditions.
   This removes execution-layer noise.

3. **Are reconstruction artifacts still contaminating?**
   Compare `ast_correct_rate_strict` vs `ast_correct_rate_recon`.
   If they diverge on the same cases the LEG report flagged → same artifact, confirmed by AST.

4. **How reliable is the LLM reasoning evaluator?**
   Compute agreement rate between `mechanism_correct` (LLM) and `ast_correct` (AST).
   Disagreements measure evaluator error rate.

---

## 10. Validation on Real Cases

### Step 1: Validate spec on reference fixes (MUST all pass)

```python
for case_id, case in cases.items():
    rule = get_rule_for_case(case)
    if rule is None:
        continue
    ref_fix_path = case["reference_fix"]["file"]
    ref_code = read_file(ref_fix_path.replace("code_snippets_v2", "case_data/reference_fixes"))
    tree = ast.parse(ref_code)
    target_func = case["reference_fix"]["function"]
    
    assert rule.checker(tree, target_func, rule.params), \
        f"FAIL: reference fix for {case_id} does not pass AST check"
    if rule.anti_checker:
        assert not rule.anti_checker(tree, target_func, rule.anti_params), \
            f"FAIL: reference fix for {case_id} triggers anti-check"
```

### Step 2: Validate spec on buggy code (MUST all fail)

```python
for case_id, case in cases.items():
    rule = get_rule_for_case(case)
    if rule is None:
        continue
    buggy_path = case["reference_fix"]["file"]  # same path but in code_snippets_v2
    buggy_code = read_file(buggy_path)
    tree = ast.parse(buggy_code)
    target_func = case["reference_fix"]["function"]
    
    # The check should FAIL on buggy code (pattern not present)
    assert not rule.checker(tree, target_func, rule.params), \
        f"FAIL: buggy code for {case_id} passes AST check (false positive)"
```

If any assertion fails, the AST rule is wrong. Fix the rule before analyzing model outputs.

### Step 3: Validate on known experimental outcomes

From the primary dataset (7,695 events):
- Events where `exec_pass=True AND v2_category="interpretable_success"` should have a HIGH `ast_correct` rate (>85%). If not, specs are too strict or alternatives are missing.
- Events where `exec_pass=False AND v2_category="full_failure_v2"` should have a HIGH `ast_incorrect` rate (>80%). If not, specs are too loose.
- The 13 `lucky_fix_v2` events should have LOW `ast_correct` rate. If high → the LLM evaluator was wrong about mechanism.

---

## 11. Phased Plan (Validation-First)

### Phase 1 — Prototype on 10 cases (3-4 days)

**Goal:** Working AST evaluator on the 10 measurable cases in the primary dataset. Produce the 2×2 matrix.

**Tasks:**
1. Implement `scripts/ast_pattern_matchers.py` — 10 checker functions covering 7 rule types
2. Implement `scripts/ast_spec_registry.py` — declarative dict mapping fix_pattern → Rule
3. Implement `scripts/ast_validate_specs.py` — validate all specs on ref fixes (pass) and buggy code (fail)
4. Run validation. Fix any failing specs.
5. Implement `scripts/ast_retro_eval.py` — load events, run matchers, output CSV
6. Run on `v2_targeted_50trial_canonical/merged_events.jsonl`
7. Compute: 2×2 matrix (strict and recon-only), LEG_ast vs LEG_text, ast_text_agreement

**Exit criterion:** AST_CORRECT_FAILURE rate > 2% of assessable events. If not, stop.

### Phase 2 — Full log analysis (1-2 days)

**Goal:** Run on all log files. Expand to ~50 AST-measurable cases.

**Tasks:**
1. Add pattern matchers for remaining rule types
2. Run on all `merged_events.jsonl` files
3. Generate per-family, per-model, per-condition breakdowns
4. Identify LUCKY_FIX_AST events; review manually; expand alternatives if needed

**Exit criterion:** Metrics are stable and interpretable.

### Phase 3 — Paper integration (1-2 days)

**Goal:** Draft paper content.

**Tasks:**
1. Write `analysis/run_ast_analysis.py` with tables and figures
2. Draft methodology section
3. Decide LEG definition revision

### Phase 4 — Pipeline integration (ONLY IF JUSTIFIED)

**Goal:** Optional. Only after Phases 1-3 prove value.

---

## 12. Hard Constraints

- NO new LLM calls in Phases 1-3
- AST rules MUST be derived from cases_v2.json fix_pattern + invariant
- AST evaluation MUST target reference_fix.file::reference_fix.function ONLY
- Every metric MUST be computed in both strict and recon-only modes
- Every spec MUST pass validation on reference fix AND fail on buggy code
- Cases marked NOT AST-MEASURABLE MUST be excluded from all AST metrics
- NO pipeline changes until Phase 4

---

## 13. Next Steps

- [ ] Implement `scripts/ast_pattern_matchers.py` (10 checker functions)
- [ ] Implement `scripts/ast_spec_registry.py` (fix_pattern → Rule mapping)
- [ ] Implement `scripts/ast_validate_specs.py`
- [ ] Run validation on 10 pilot cases: ref fix passes, buggy code fails
- [ ] Implement `scripts/ast_retro_eval.py`
- [ ] Run on v2_targeted_50trial_canonical (7,695 events)
- [ ] Compute 2×2 matrix (strict + recon-only)
- [ ] Compute LEG_ast rate; compare to LEG_text rate
- [ ] Compute ast-text agreement (ast_correct vs mechanism_correct)
- [ ] Decision: is AST_CORRECT_FAILURE > 2%? If yes → Phase 2. If no → stop.
