"""Targeted fixes for broken checkers + NOT_AST_MEASURABLE exclusion set.

Imported by retro_eval.py to override specific CASE_RULES entries.
"""

# Cases that cannot be reliably distinguished by AST between buggy and fixed
NOT_AST_MEASURABLE = {
    # Runtime semantics only
    "false_fix_deadlock", "lost_update", "check_then_act", "ordering_dependency",
    "config_shadowing", "feature_flag_drift",
    # Buggy/fixed structure too similar for AST to distinguish
    "index_misalign_b", "index_misalign_c",
    "silent_default_a", "silent_default_c",
    "partial_update_b",
}

import ast
from checkers import find_function, _call_name, _calls_in, _has_call


# =====================================================================
# FIX 1: retry_dup_a — uses if/break pattern, not try/break
# =====================================================================

def retry_a_strict(fn):
    """retry_dup_a: for loop with 'if result: break' pattern."""
    for node in ast.walk(fn):
        if isinstance(node, ast.For):
            for child in ast.walk(node):
                if isinstance(child, ast.If):
                    for s in child.body:
                        if isinstance(s, ast.Break): return True
                if isinstance(child, ast.Break): return True
                if isinstance(child, ast.Return): return True
    return False

def retry_a_relaxed(fn):
    return retry_a_strict(fn)

def retry_a_anti(fn):
    """Anti: for loop with NO break or return anywhere inside."""
    for node in ast.walk(fn):
        if isinstance(node, ast.For):
            for child in ast.walk(node):
                if isinstance(child, (ast.Break, ast.Return)): return False
            return True  # loop found with no break/return
    return False


# =====================================================================
# FIX 2: temporal_drift — check ordering with actual call names
# =====================================================================

def td_strict(fn):
    """Check compute_raw_stats called BEFORE normalize/clean/transform."""
    raw_pos = 999; transform_pos = -1
    for i, s in enumerate(fn.body):
        for n in ast.walk(s):
            if isinstance(n, ast.Call):
                nm = _call_name(n)
                if nm in ("compute_raw_stats","raw_stats","compute_raw"):
                    raw_pos = min(raw_pos, i)
                if nm in ("normalize","clean","transform","clip","apply_transform"):
                    transform_pos = max(transform_pos, i)
    return raw_pos < transform_pos and raw_pos < 999

def td_relaxed(fn):
    if td_strict(fn): return True
    # Accept: raw_stats computed at all (even if argument is wrong)
    return _has_call(fn, {"compute_raw_stats","raw_stats","compute_raw"})

def td_anti(fn):
    """Anti: raw_stats called AFTER first transform call."""
    raw_pos = -1; transform_pos = 999
    for i, s in enumerate(fn.body):
        for n in ast.walk(s):
            if isinstance(n, ast.Call):
                nm = _call_name(n)
                if nm in ("compute_raw_stats","raw_stats","compute_raw"):
                    raw_pos = max(raw_pos, i)
                if nm in ("normalize","clean","transform"):
                    transform_pos = min(transform_pos, i)
    return raw_pos > transform_pos and raw_pos >= 0

def td_partial(fn):
    return _has_call(fn, {"compute_raw_stats","raw_stats","compute_raw"})


# =====================================================================
# FIX 3: early_return — audit call must be on the EARLY RETURN path
# =====================================================================

def er_strict(fn):
    """Check: in the if-branch that returns early, there is an audit/ledger call."""
    for s in fn.body:
        if isinstance(s, ast.If):
            has_return = any(isinstance(c, ast.Return) for c in ast.walk(s))
            if has_return:
                # Check if there's an audit call BEFORE the return in this branch
                audit_names = {"append","record","log","log_charge","log_attempt","ledger"}
                for stmt in s.body:
                    if _has_call(stmt, audit_names): return True
                # Also check: call in finally block
    for n in ast.walk(fn):
        if isinstance(n, ast.Try) and n.finalbody:
            if _has_call(ast.Module(body=n.finalbody, type_ignores=[]),
                        {"append","record","log","log_charge","log_attempt","ledger"}):
                return True
    return False

def er_relaxed(fn):
    if er_strict(fn): return True
    # Accept: audit call at start of function (before any if)
    audit_names = {"append","record","log","log_charge","log_attempt","ledger"}
    for s in fn.body:
        if isinstance(s, ast.If): break  # stop at first if
        if _has_call(s, audit_names): return True
    return False

def er_anti(fn):
    """Anti: early return branch has NO audit call."""
    for s in fn.body:
        if isinstance(s, ast.If):
            has_return = any(isinstance(c, ast.Return) for c in s.body)
            if has_return:
                audit_names = {"append","record","log","log_charge","log_attempt","ledger"}
                has_audit = _has_call(ast.Module(body=s.body, type_ignores=[]), audit_names)
                if not has_audit: return True  # early return without audit = bug
    return False

def er_partial(fn):
    """Partial: audit call exists somewhere in function."""
    return _has_call(fn, {"append","record","log","log_charge","log_attempt","ledger"})


# =====================================================================
# FIX 4: partial_rollback — compensation CALL in handler, not bare raise
# =====================================================================

def pr_strict(fn):
    """Strict: except handler has a compensation call + raise."""
    comp_names = {"release","remove_audit_entry","rollback","undo","revert","restore"}
    for n in ast.walk(fn):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                has_comp = any(_call_name(c) in comp_names for c in _calls_in(h))
                has_raise = any(isinstance(c, ast.Raise) for c in ast.walk(h))
                if has_comp and has_raise: return True
    return False

def pr_relaxed(fn):
    """Relaxed: except handler has ANY call before raise."""
    if pr_strict(fn): return True
    for n in ast.walk(fn):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                calls = list(_calls_in(h))
                has_raise = any(isinstance(c, ast.Raise) for c in ast.walk(h))
                if calls and has_raise: return True
    return False

def pr_anti(fn):
    """Anti: try/except with ONLY bare raise (the bug pattern)."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                if len(h.body) == 1 and isinstance(h.body[0], ast.Raise):
                    return True
    return False

def pr_partial(fn):
    """Partial: try/except with handler that has more than just raise."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                if len(h.body) > 1: return True
    return False


# =====================================================================
# FIX 5: partial_update — check for DEPENDENT field assignments
# =====================================================================

def pu_strict(fn):
    """Check that dependent fields are assigned in EVERY branch that changes primary.
    For partial_update_b: full_name must be updated in BOTH first_name and last_name branches."""
    # Find all if/elif branches that assign to user dict
    branches_with_dep = 0
    branches_with_primary = 0
    for n in ast.walk(fn):
        if isinstance(n, ast.If):
            # Check this branch
            branch_targets = set()
            for c in ast.walk(n):
                if isinstance(c, ast.Assign):
                    for t in c.targets:
                        if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str):
                            branch_targets.add(t.slice.value)
            primary = {"name","first_name","last_name","email"}
            dep = {"display_name","full_name","verified","display"}
            if branch_targets & primary:
                branches_with_primary += 1
                if branch_targets & dep:
                    branches_with_dep += 1
    # All primary-modifying branches must also modify dependent
    return branches_with_primary > 0 and branches_with_dep >= branches_with_primary

def pu_relaxed(fn):
    if pu_strict(fn): return True
    # Accept: multiple different subscript assignments to user dict
    targets = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant):
                    targets.add(str(t.slice.value))
    # Buggy has only 1-2 distinct targets; fixed has 3+
    return len(targets) >= 3

def pu_anti(fn):
    """Anti: only primary field is assigned, no dependent fields."""
    targets = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant):
                    if isinstance(t.slice.value, str):
                        targets.add(t.slice.value)
    dep_fields = {"display_name","full_name","verified","display"}
    return not bool(targets & dep_fields)

def pu_partial(fn):
    return pu_relaxed(fn)


# =====================================================================
# FIX 6: missing_branch — MODULE-LEVEL dict key count or function elif
# =====================================================================

def mb_a_strict(tree_not_fn):
    """missing_branch_a: ROLE_PERMISSIONS dict must have moderator key.
    NOTE: This takes the TREE, not the function node."""
    for n in ast.walk(tree_not_fn):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and k.value == "moderator": return True
    return False

def mb_b_strict(tree_not_fn):
    """missing_branch_b: dispatch dict must have guest key."""
    for n in ast.walk(tree_not_fn):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and k.value == "guest": return True
    return False

def mb_c_strict(fn):
    """missing_branch_c: authorize() must have service_account branch."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Compare):
            for comp in n.comparators:
                if isinstance(comp, ast.Constant) and comp.value == "service_account": return True
    return False

def mb_c_anti(fn):
    """Anti: no service_account check in authorize()."""
    return not mb_c_strict(fn)

def mb_a_relaxed(tree_not_fn):
    """Relaxed: dict has moderator or 3+ role keys."""
    if mb_a_strict(tree_not_fn): return True
    for n in ast.walk(tree_not_fn):
        if isinstance(n, ast.Dict) and len(n.keys) >= 3:
            str_keys = [k.value for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if "admin" in str_keys and "user" in str_keys and len(str_keys) >= 3:
                return True
    return False

def mb_b_relaxed(tree_not_fn):
    """Relaxed: dispatch dict has guest or 5+ entries."""
    if mb_b_strict(tree_not_fn): return True
    for n in ast.walk(tree_not_fn):
        if isinstance(n, ast.Dict) and len(n.keys) >= 5: return True
    return False

def mb_c_relaxed(fn):
    """Relaxed: authorize has 5+ branches or mentions service_account."""
    if mb_c_strict(fn): return True
    count = sum(1 for n in ast.walk(fn) if isinstance(n, ast.If))
    return count >= 5

def mb_partial(fn_or_tree):
    return True


# =====================================================================
# FIX 7: silent_default — string literal correction
# =====================================================================

def sd_a_strict(fn):
    """silent_default_a: must use "enable_debug" not "enableDebug"."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if "enable_debug" in n.value: return True
    return False

def sd_a_anti(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if "enableDebug" in n.value: return True
    return False

def sd_b_strict(fn):
    """silent_default_b: must use "feature.analytics" not "features.analytics"."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if "feature.analytics" in n.value and "features.analytics" not in n.value: return True
    return False

def sd_b_anti(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if "features.analytics" in n.value: return True
    return False

def sd_c_strict(fn):
    """silent_default_c: correct env var key."""
    # Generic: function uses get_flag or os.environ with a string
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if "ENABLE_DEBUG" in n.value or "enable_debug" in n.value: return True
    return False

def sd_a_relaxed(fn):
    """Accept: any snake_case flag name in function."""
    if sd_a_strict(fn): return True
    # Accept if there are NO camelCase flag references
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if any(c.isupper() for c in n.value) and "_" not in n.value:
                return False  # camelCase still present
    return True  # no camelCase = probably fixed

def sd_c_relaxed(fn):
    """Accept: function uses correct env key mapping."""
    if sd_c_strict(fn): return True
    # Check that function has some string-based lookup
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and _call_name(n) in ("get_flag","get","getenv","get_env_bool","get_config_bool"):
            return True
    return False

def sd_partial(fn):
    return sd_relaxed(fn)


# =====================================================================
# FIX 8: index_misalign — consistent parallel operations
# =====================================================================

def im_a_strict(fn):
    """Both labels and values use insert."""
    insert_count = sum(1 for n in ast.walk(fn)
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr == "insert")
    return insert_count >= 2

def im_bc_strict(fn):
    """index_misalign_b: fix adds row deletion. Check for del on rows inside delete_column."""
    # Check: both headers and rows are modified
    has_header_del = False
    has_row_del = False
    for n in ast.walk(fn):
        if isinstance(n, ast.Delete):
            for t in n.targets:
                if isinstance(t, ast.Subscript):
                    if isinstance(t.value, ast.Attribute) and "header" in t.value.attr.lower():
                        has_header_del = True
                    if isinstance(t.value, ast.Name) and "header" in t.value.id.lower():
                        has_header_del = True
        # Check for row modification (for loop deleting from rows)
        if isinstance(n, ast.For):
            for c in ast.walk(n):
                if isinstance(c, ast.Delete) or (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in ("pop","del","remove")):
                    has_row_del = True
                if isinstance(c, ast.Expr) and isinstance(c.value, ast.Call):
                    if _call_name(c.value) in ("pop","del"): has_row_del = True
    # Also check for list comprehension or slice deletion on rows
    for n in ast.walk(fn):
        if isinstance(n, ast.ListComp): has_row_del = True
        if isinstance(n, ast.Call) and _call_name(n) == "pop": has_row_del = True
    return has_header_del and has_row_del

def im_bc_relaxed(fn):
    if im_bc_strict(fn): return True
    # Accept: any modification that touches both headers and rows
    touches_header = False
    touches_row = False
    for n in ast.walk(fn):
        src = ast.dump(n)
        if "header" in src.lower(): touches_header = True
        if "row" in src.lower(): touches_row = True
    return touches_header and touches_row

def im_partial(fn):
    return True  # any modification = partial


# =====================================================================
# FIX 9: lazy_init_a — MODULE-LEVEL eager capture removal
# =====================================================================

def li_a_strict(tree_not_fn):
    """lazy_init_a: _default_host must NOT be assigned at module level."""
    for n in ast.iter_child_nodes(tree_not_fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "_default_host": return False
    return True  # absence of eager capture = correct

def li_a_anti(tree_not_fn):
    """Anti: _default_host IS assigned at module level."""
    for n in ast.iter_child_nodes(tree_not_fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "_default_host": return True
    return False

def li_a_relaxed(tree_not_fn):
    return li_a_strict(tree_not_fn)


# =====================================================================
# FIX 10: wrong_condition_c — parenthesized precedence
# =====================================================================

def wc_c_strict(fn):
    """Check: And node contains an Or node as a value (explicit parenthesization).
    Correct: not expired and (under_limit or exempt)
    → BoolOp(And, [UnaryOp(Not, expired), BoolOp(Or, [under_limit, exempt])])
    Buggy: not expired and under_limit or exempt
    → BoolOp(Or, [BoolOp(And, [UnaryOp(Not, expired), under_limit]), exempt])
    """
    for n in ast.walk(fn):
        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.And):
            # Check if any value is an Or BoolOp (= parenthesized Or inside And)
            for v in n.values:
                if isinstance(v, ast.BoolOp) and isinstance(v.op, ast.Or):
                    return True
    return False

def wc_c_anti(fn):
    """Anti: top-level Or with And inside (wrong precedence)."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.BoolOp):
            if isinstance(n.value.op, ast.Or):
                # Top-level Or = buggy precedence
                return True
    return False

def wc_c_relaxed(fn):
    if wc_c_strict(fn): return True
    # Accept: no top-level Or in return statement
    return not wc_c_anti(fn)


# =====================================================================
# MODULE-LEVEL CHECK FLAG
# Cases where the check must operate on the tree, not a function
# =====================================================================

MODULE_LEVEL_CASES = {
    "missing_branch_a": ("get_permissions", mb_a_strict, mb_a_relaxed, None, mb_partial),
    "missing_branch_b": ("get_access", mb_b_strict, mb_b_relaxed, None, mb_partial),
    "lazy_init_a": ("get_host", li_a_strict, li_a_relaxed, li_a_anti, None),
}

# =====================================================================
# CASE_RULES OVERRIDES (function-level, replacing broken entries)
# =====================================================================

CASE_RULES_OVERRIDES = {
    "retry_dup_a": ("retry_send", retry_a_strict, retry_a_relaxed, retry_a_anti, None),

    "temporal_drift_a": ("pipeline", td_strict, td_relaxed, td_anti, td_partial),
    "temporal_drift_b": ("pipeline", td_strict, td_relaxed, td_anti, td_partial),
    "temporal_drift_c": ("pipeline", td_strict, td_relaxed, td_anti, td_partial),

    "early_return_a": ("process_payment", er_strict, er_relaxed, er_anti, er_partial),
    "early_return_b": ("process_payment", er_strict, er_relaxed, er_anti, er_partial),
    "early_return_c": ("charge", er_strict, er_relaxed, er_anti, er_partial),

    "partial_rollback_a": ("place_order", pr_strict, pr_relaxed, pr_anti, pr_partial),
    "partial_rollback_b": ("place_order", pr_strict, pr_relaxed, pr_anti, pr_partial),
    "partial_rollback_c": ("place_order", pr_strict, pr_relaxed, pr_anti, pr_partial),

    "partial_update_a": ("update_profile", pu_strict, pu_relaxed, pu_anti, pu_partial),
    # partial_update_b: NOT AST-MEASURABLE — buggy code already has full_name assignment
    # in the last_name branch. The bug is that the first_name branch DOESN'T update full_name.
    # Detecting "assignment missing in ONE specific branch" requires branch-specific analysis
    # that our AST framework doesn't support cleanly.
    "partial_update_c": ("update_profile", pu_strict, pu_relaxed, pu_anti, pu_partial),

    "missing_branch_c": ("authorize", mb_c_strict, mb_c_relaxed, mb_c_anti, mb_partial),

    # silent_default_a/c: NOT AST-MEASURABLE — fix is caller-side key name, not function structure
    # The function itself is identical in buggy and fixed; the bug is in the CALLER's argument
    "silent_default_b": ("is_analytics_enabled", sd_b_strict, sd_b_strict, sd_b_anti, sd_partial),
    # silent_default_c: same as silent_default_a — caller-side key mismatch

    "index_misalign_a": ("add_entry", im_a_strict, im_a_strict, None, im_partial),
    # index_misalign_b/c: NOT AST-MEASURABLE — buggy and fixed have too-similar structure
    # The fix is adding row deletion inside delete_column, but the function structure
    # is identical (del + loop) — requires semantic analysis of WHICH structures are modified

    "wrong_condition_c": ("should_allow", wc_c_strict, wc_c_relaxed, wc_c_anti, None),
}
