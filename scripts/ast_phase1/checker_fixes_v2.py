"""V2 checker fixes: targeted repairs for the 6 high-LUCKY_FIX families.

Each fix is invariant-justified. Imported by retro_eval_full.py.
"""

import ast
from checkers import find_function, _call_name, _calls_in, _has_call

# =====================================================================
# FIX 1: early_return — INVARIANT: ledger must have entry for every call
#
# OLD RULE: audit call exists in the if-branch before return
# DEFECT: Models restructure to single append() for all paths. The checker
#   only looks inside the if-branch, missing the restructured pattern.
# NEW RULE: _ledger.append() (or equivalent) is called on ALL control paths,
#   including the early-return path. Accept: append in if-body before return,
#   append before the if, append in both branches, append after if with no
#   early return, or finally block.
# COUNTEREXAMPLE REJECTED: append only in the non-zero path (the bug pattern)
# =====================================================================

def er_relaxed_v2(fn):
    """Relaxed: ledger is written on all paths including early return.

    Invariant: every call to this function must produce a ledger entry.
    Accept any structure where the audit call is guaranteed to execute
    on all control flow paths through the function.
    """
    audit_names = {"append", "record", "log", "log_charge", "log_attempt", "ledger"}

    # Pattern 1: audit call inside if-branch before return
    for s in fn.body:
        if isinstance(s, ast.If):
            has_return = any(isinstance(c, ast.Return) for c in ast.walk(s))
            if has_return and _has_call(s, audit_names):
                return True

    # Pattern 2: audit call BEFORE any if that contains a return (covers all paths)
    # Scan all statements before the first if-with-return
    for s in fn.body:
        if isinstance(s, ast.If):
            has_return = any(isinstance(c, ast.Return) for c in ast.walk(s))
            if has_return:
                break  # hit the branching point — stop scanning
        if _has_call(s, audit_names):
            return True  # audit happens unconditionally before any branching

    # Pattern 3: no early return at all (model restructured to avoid it)
    has_early_return = False
    for s in fn.body:
        if isinstance(s, ast.If):
            for child in s.body:
                if isinstance(child, ast.Return):
                    has_early_return = True
    if not has_early_return:
        if _has_call(fn, audit_names):
            return True

    # Pattern 4: finally block
    for n in ast.walk(fn):
        if isinstance(n, ast.Try) and n.finalbody:
            if _has_call(ast.Module(body=n.finalbody, type_ignores=[]), audit_names):
                return True

    # Pattern 5: both if and else branches have audit call
    for s in fn.body:
        if isinstance(s, ast.If) and s.orelse:
            if_has = _has_call(ast.Module(body=s.body, type_ignores=[]), audit_names)
            else_has = _has_call(ast.Module(body=s.orelse, type_ignores=[]), audit_names)
            if if_has and else_has:
                return True

    # Pattern 6: audit call after all ifs (no early return prevents reaching it)
    # If there IS an early return but append is after the if block,
    # the early-return path ALSO has an append before it (Pattern 2 catches this).
    # This catches: if/else with returns in both branches, append after.
    # Not valid — the returns prevent reaching the append. Skip.

    return False

def er_anti_v2(fn):
    """Anti: early return path has NO audit call AND no audit before the if.

    The bug pattern is: if amount==0: return (skipping ledger).
    This is NOT the bug if audit happens BEFORE the if (covers all paths).
    """
    audit_names = {"append", "record", "log", "log_charge", "log_attempt", "ledger"}

    # First: check if there's an audit call BEFORE any if-with-return
    # If so, the early return is safe — not the bug pattern
    audit_before_if = False
    for s in fn.body:
        if isinstance(s, ast.If):
            has_return = any(isinstance(c, ast.Return) for c in ast.walk(s))
            if has_return:
                break  # hit the branching point
        if _has_call(s, audit_names):
            audit_before_if = True

    if audit_before_if:
        return False  # audit happens before the branch — not the bug

    # Also check: no early return at all = not the bug
    has_early_return = False
    for s in fn.body:
        if isinstance(s, ast.If):
            for child in s.body:
                if isinstance(child, ast.Return):
                    has_early_return = True
    if not has_early_return:
        return False

    # Check: if-branch with return but no audit inside it
    for s in fn.body:
        if isinstance(s, ast.If):
            has_return = any(isinstance(c, ast.Return) for c in s.body)
            if has_return:
                has_audit_in_branch = _has_call(
                    ast.Module(body=s.body, type_ignores=[]), audit_names)
                if not has_audit_in_branch:
                    return True  # early return without audit AND no pre-if audit = bug
    return False


# =====================================================================
# FIX 2: temporal_drift — INVARIANT: raw_stats must reflect original case_data
#
# OLD RULE: compute_raw_stats must be called BEFORE normalize
# DEFECT: The actual invariant is about the ARGUMENT, not the ordering.
#   Models correctly pass `case_data` (original) to compute_raw_stats even when
#   it's called after normalize. The checker tests ordering when it should
#   test the argument.
# NEW RULE: compute_raw_stats must be called with the ORIGINAL case_data parameter
#   (the function's input parameter), not with cleaned/normalized/clipped output.
# COUNTEREXAMPLE REJECTED: compute_raw_stats(cleaned) or compute_raw_stats(normalized)
# =====================================================================

def td_relaxed_v2(fn):
    """Relaxed: compute_raw_stats called with the original case_data param (not cleaned)."""
    # Find the function's first parameter name (the original case_data)
    if not fn.args.args:
        return False
    original_param = fn.args.args[0].arg  # typically "case_data"

    raw_stats_names = {"compute_raw_stats", "raw_stats", "compute_raw"}

    for call in _calls_in(fn):
        name = _call_name(call)
        if name in raw_stats_names and call.args:
            arg = call.args[0]
            if isinstance(arg, ast.Name) and arg.id == original_param:
                return True  # called with original case_data parameter
    return False

def td_anti_v2(fn):
    """Anti: compute_raw_stats called with transformed case_data (not original)."""
    if not fn.args.args:
        return False
    original_param = fn.args.args[0].arg

    raw_stats_names = {"compute_raw_stats", "raw_stats", "compute_raw"}

    for call in _calls_in(fn):
        name = _call_name(call)
        if name in raw_stats_names and call.args:
            arg = call.args[0]
            if isinstance(arg, ast.Name) and arg.id != original_param:
                return True  # called with wrong argument
    return False


# =====================================================================
# FIX 3: cache_invalidation_order — INVARIANT: read_record returns latest after update
#
# OLD RULE: invalidate call before conditional_set
# DEFECT: Models use direct cache_set after db_write instead of the
#   invalidate→conditional_set pattern. This is a valid alternative that
#   satisfies the invariant (the cache gets the new value directly).
# NEW RULE: after db_write, either (a) invalidate + conditional_set, OR
#   (b) direct cache_set with the new value.
# COUNTEREXAMPLE REJECTED: db_write with NO cache operation at all
# =====================================================================

def cio_relaxed_v2(fn):
    """Relaxed: after db_write, cache is updated or invalidated."""
    seen_write = False
    for s in fn.body:
        if _has_call(s, {"db_write"}):
            seen_write = True
        if seen_write:
            # Accept: invalidate, or cache_set, or cache_conditional_set
            if _has_call(s, {"cache_invalidate", "invalidate", "cache_set",
                            "cache_conditional_set", "set"}):
                return True
    return False

def cio_anti_v2(fn):
    """Anti: db_write with no cache operation after it."""
    seen_write = False
    has_cache_op = False
    for s in fn.body:
        if _has_call(s, {"db_write"}):
            seen_write = True
        if seen_write and _has_call(s, {"cache_invalidate", "invalidate", "cache_set",
                                        "cache_conditional_set"}):
            has_cache_op = True
    return seen_write and not has_cache_op


# =====================================================================
# FIX 4: hidden_dep_multihop — INVARIANT: save_user must use always-overwrite cache
#
# OLD RULE: save_user calls sync_user_to_cache or cache_put
# DEFECT: Models create new unified functions (update_user_cache,
#   cache_write, etc.) with overwrite semantics. The checker only
#   matches specific function names.
# NEW RULE: save_user calls a cache-write function that is NOT
#   refresh_user_snapshot or cache_put_if_absent (the conditional ones).
#   Accept any call that writes to cache, as long as it's not the
#   conditional-only function.
# COUNTEREXAMPLE REJECTED: refresh_user_snapshot (conditional write)
# =====================================================================

def hdm_relaxed_v2(fn):
    """Relaxed: save_user calls any cache write function except the conditional one."""
    forbidden = {"refresh_user_snapshot", "cache_put_if_absent"}
    cache_write_indicators = {"sync_user_to_cache", "cache_put", "update_user_cache",
                              "cache_write", "write_cache", "update_cache", "set_cache",
                              "cache_set"}

    for call in _calls_in(fn):
        name = _call_name(call)
        if name in cache_write_indicators:
            return True
        # Accept any call with "cache" in name that isn't the forbidden one
        if "cache" in name.lower() and name not in forbidden:
            return True
        # Accept cache_put explicitly
        if name == "cache_put":
            return True
    return False

def hdm_anti_v2(fn):
    """Anti: save_user uses refresh_user_snapshot (conditional write)."""
    for call in _calls_in(fn):
        name = _call_name(call)
        if name in ("refresh_user_snapshot", "cache_put_if_absent"):
            return True
    return False


# =====================================================================
# FIX 5: l3_state_pipeline — INVARIANT: commit + freeze_view both required
#
# NO CHANGE to the checker rule. The current checker correctly requires
# both commit() and freeze_view(). The 230 LF events have commit() but
# NOT freeze_view(). These pass execution because the test primarily
# checks commit's effects (frozen gate). These are GENUINE PARTIAL FIXES
# that happen to pass the test — not checker errors.
#
# However: we should reclassify them as ast_partial, not ast_wrong.
# The current checker marks them as wrong because relaxed requires both.
# We keep relaxed requiring both, but partial should catch commit-only.
# =====================================================================

# (No new functions needed — partial detector already catches this)


# =====================================================================
# FIX 6: invariant_partial_fail — INVARIANT: balance conservation
#
# OLD RULE: try/except with AugAssign in handler
# DEFECT: Models extract core transfer into a helper function and add
#   try/except around the helper call. The checker can't see through
#   the indirection.
# NEW RULE: either (a) try/except with compensation in handler (direct),
#   OR (b) helper function call inside try/except (indirect — the model
#   extracted the mutation into a helper and the try/except catches failure).
# COUNTEREXAMPLE REJECTED: try/except with only raise (no compensation)
# =====================================================================

def ipf_relaxed_v2(fn):
    """Relaxed: balance conservation via any mechanism.

    Invariant: sender.balance + receiver.balance must be conserved.
    Accept any structure that prevents partial mutation:
    1. try/except with compensation + re-raise
    2. pre-saved balance + try/except restoring it
    3. failure check BEFORE any mutation (no partial state possible)
    4. helper function with try/except wrapping it
    """
    # Pattern 1: try/except with compensation
    for n in ast.walk(fn):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                has_comp = False
                for c in ast.walk(h):
                    if isinstance(c, ast.AugAssign): has_comp = True
                    if isinstance(c, ast.Assign):
                        for t in c.targets:
                            if isinstance(t, ast.Attribute) and 'balance' in ast.dump(t):
                                has_comp = True
                    if isinstance(c, ast.Call): has_comp = True
                has_raise = any(isinstance(c, ast.Raise) for c in ast.walk(h))
                if has_comp and has_raise: return True

    # Pattern 2: pre-saved balance + try/except
    has_pre_save = False
    for s in fn.body:
        if isinstance(s, ast.Assign):
            src = ast.dump(s)
            if 'balance' in src.lower() or 'pre_' in src.lower() or 'original' in src.lower():
                has_pre_save = True
    if has_pre_save:
        for n in ast.walk(fn):
            if isinstance(n, ast.Try): return True

    # Pattern 3: failure check BEFORE any mutation
    # If the failure (random.random() / raise) happens before any balance change,
    # the invariant is trivially satisfied — no partial state can exist.
    # Detect: the if-with-raise comes before any balance mutation or helper call.
    helper_names = {"_perform_transfer", "_core_transfer", "_do_transfer",
                    "transfer_core", "_transfer", "_execute"}
    raise_pos = -1
    mutation_pos = 999

    for i, s in enumerate(fn.body):
        # Check for the failure/raise block
        if isinstance(s, ast.If):
            has_raise = any(isinstance(c, ast.Raise) for c in ast.walk(s))
            if has_raise and raise_pos < 0:
                raise_pos = i

        # Check for balance mutation
        for n in ast.walk(s):
            if isinstance(n, ast.AugAssign):
                if isinstance(n.target, ast.Attribute) and 'balance' in ast.dump(n.target):
                    mutation_pos = min(mutation_pos, i)
            if isinstance(n, ast.Call):
                nm = _call_name(n)
                if nm in helper_names:
                    mutation_pos = min(mutation_pos, i)

    if raise_pos >= 0 and raise_pos < mutation_pos:
        return True  # failure happens before any mutation — invariant trivially satisfied

    return False


# =====================================================================
# OVERRIDE TABLE — replaces entries in CASE_RULES_OVERRIDES
# =====================================================================

CHECKER_V2_OVERRIDES = {
    # early_return: all 3 cases
    "early_return_a": ("process_payment", None, er_relaxed_v2, er_anti_v2, None),
    "early_return_b": ("process_payment", None, er_relaxed_v2, er_anti_v2, None),
    "early_return_c": ("charge", None, er_relaxed_v2, er_anti_v2, None),

    # temporal_drift: all 3 cases
    "temporal_drift_a": ("pipeline", None, td_relaxed_v2, td_anti_v2, None),
    "temporal_drift_b": ("pipeline", None, td_relaxed_v2, td_anti_v2, None),
    "temporal_drift_c": ("pipeline", None, td_relaxed_v2, td_anti_v2, None),

    # cache_invalidation_order
    "cache_invalidation_order": ("update_record", None, cio_relaxed_v2, cio_anti_v2, None),

    # hidden_dep_multihop
    "hidden_dep_multihop": ("save_user", None, hdm_relaxed_v2, hdm_anti_v2, None),

    # invariant_partial_fail
    "invariant_partial_fail": ("execute_transfer", None, ipf_relaxed_v2, None, None),
}
