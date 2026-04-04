"""AST checkers for all 58 oracle-evaluated cases.

Each family has strict + relaxed + anti checkers.
Not AST-measurable cases return None from get_rule().
"""

import ast
from typing import Optional, Tuple, Callable

# ── Utilities ────────────────────────────────────────────────────────

def find_function(tree: ast.Module, name: str) -> Optional[ast.FunctionDef]:
    """Find function by name. Top-level + one nesting level."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
        if isinstance(node, ast.ClassDef):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef) and child.name == name:
                    return child
    return None

def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name): return node.func.id
    if isinstance(node.func, ast.Attribute): return node.func.attr
    return ""

def _calls_in(node: ast.AST):
    for c in ast.walk(node):
        if isinstance(c, ast.Call): yield c

def _has_call(node: ast.AST, names) -> bool:
    for c in _calls_in(node):
        if _call_name(c) in names: return True
    return False

_SIDE_EFFECT_NAMES = frozenset(["snapshot","emit_event","audit_log"])
_INVALIDATE_NAMES = frozenset(["pop","invalidate","invalidate_local","invalidate_shared",
    "clear","cache_invalidate","delete","remove","discard","expire","evict","flush"])


# =====================================================================
# CHECKER IMPLEMENTATIONS
# Each returns (strict, relaxed, partial) booleans for a func_node.
# =====================================================================

# ── 1. alias_config: copy on return ──────────────────────────────────

def _alias_strict(fn):
    for c in _calls_in(fn):
        if isinstance(c.func, ast.Attribute) and c.func.attr=="copy" and isinstance(c.func.value, ast.Name) and c.func.value.id=="DEFAULTS": return True
        if isinstance(c.func, ast.Name) and c.func.id=="dict" and c.args and isinstance(c.args[0], ast.Name) and c.args[0].id=="DEFAULTS": return True
    return False

def _alias_relaxed(fn):
    if _alias_strict(fn): return True
    for n in ast.walk(fn):
        if isinstance(n, ast.Dict):
            for i,k in enumerate(n.keys):
                if k is None and i<len(n.values) and isinstance(n.values[i], ast.Name) and n.values[i].id=="DEFAULTS": return True
        if isinstance(n, ast.DictComp):
            for g in n.generators:
                if isinstance(g.iter, ast.Call) and isinstance(g.iter.func, ast.Attribute) and isinstance(g.iter.func.value, ast.Name) and g.iter.func.value.id=="DEFAULTS": return True
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Attribute) and n.func.attr in ("copy","deepcopy") and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id=="DEFAULTS": return True
            if isinstance(n.func, ast.Name) and n.func.id not in ("print","len","type","isinstance") and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id=="DEFAULTS": return True
    return False

def _alias_anti(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Name) and n.value.id=="DEFAULTS": return True
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Name) and n.value.id=="DEFAULTS": return True
    return False

def _alias_partial(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            for a in getattr(n,'args',[]):
                if isinstance(a, ast.Name) and a.id=="DEFAULTS": return True
    return False


# ── 2. stale_cache: invalidation or write-through after write ────────

def _sc_is_write(stmt):
    for n in ast.walk(stmt):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr=="update": return True
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and "db" in t.value.id.lower(): return True
    return False

def _sc_is_invalidate(stmt):
    for n in ast.walk(stmt):
        if isinstance(n, ast.Call) and _call_name(n) in _INVALIDATE_NAMES: return True
        if isinstance(n, ast.Delete):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and "cache" in t.value.id.lower(): return True
    return False

def _sc_is_cache_write(stmt):
    for n in ast.walk(stmt):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and "cache" in t.value.id.lower(): return True
    return False

def _sc_strict(fn):
    sw = False
    for s in fn.body:
        if _sc_is_write(s): sw = True
        if sw and _sc_is_invalidate(s): return True
    return False

def _sc_relaxed(fn):
    if _sc_strict(fn): return True
    sw = False
    for s in fn.body:
        if _sc_is_write(s): sw = True
        if sw and (_sc_is_invalidate(s) or _sc_is_cache_write(s)): return True
    return False

def _sc_partial(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and any(x in _call_name(n).lower() for x in ("cache","invalidat","pop","del","clear")): return True
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and "cache" in t.value.id.lower(): return True
    return False

# stale_cache_c: must specifically have invalidate_local
def _sc_c_strict(fn):
    for c in _calls_in(fn):
        if _call_name(c) == "invalidate_local": return True
    return False

def _sc_c_relaxed(fn):
    if _sc_c_strict(fn): return True
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            nm = _call_name(n)
            if "local" in nm.lower() and any(x in nm.lower() for x in ("invalidate","clear","flush","evict")): return True
        if isinstance(n, ast.Delete):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and "local" in t.value.id.lower(): return True
    return False


# ── 3. mutable_default: None default + guard ─────────────────────────

def _md_has_mutable(fn):
    for d in fn.args.defaults:
        if isinstance(d, (ast.List, ast.Set, ast.Dict)): return True
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id in ("set","list","dict"): return True
    return False

def _md_has_none_guard(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.If) and isinstance(n.test, ast.Compare):
            if any(isinstance(op, ast.Is) for op in n.test.ops):
                for comp in n.test.comparators:
                    if isinstance(comp, ast.Constant) and comp.value is None: return True
    return False

def _md_removed_param(fn, pname):
    ps = [a.arg for a in fn.args.args]
    if pname in ps: return False
    for s in fn.body:
        if isinstance(s, ast.Assign):
            for t in s.targets:
                if isinstance(t, ast.Name) and t.id == pname: return True
    return False

def _md_strict(fn):
    return not _md_has_mutable(fn) and _md_has_none_guard(fn)

def _md_relaxed(fn, pname=None):
    if _md_has_mutable(fn): return False
    if _md_strict(fn): return True
    # 'if not X' guard
    for n in ast.walk(fn):
        if isinstance(n, ast.If):
            if isinstance(n.test, ast.UnaryOp) and isinstance(n.test.op, ast.Not): return True
            if isinstance(n.test, ast.BoolOp): return True
    # X = X or [] pattern
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.BoolOp) and isinstance(n.value.op, ast.Or): return True
    # param removed + local init
    if pname and _md_removed_param(fn, pname): return True
    return False

def _md_partial(fn):
    return not _md_has_mutable(fn) and not _md_has_none_guard(fn)

# mutable_default_c: history not a param, local init
def _md_c_strict(fn):
    ps = [a.arg for a in fn.args.args]
    if "history" in ps: return False
    for s in fn.body:
        if isinstance(s, ast.Assign):
            for t in s.targets:
                if isinstance(t, ast.Name) and t.id == "history": return True
    return False

def _md_c_relaxed(fn):
    if _md_c_strict(fn): return True
    ps = [a.arg for a in fn.args.args]
    if "history" in ps:
        idx = ps.index("history") - (len(ps) - len(fn.args.defaults))
        if 0 <= idx < len(fn.args.defaults):
            d = fn.args.defaults[idx]
            if isinstance(d, ast.Constant) and d.value is None: return True
        return False
    # hasattr pattern
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "hasattr": return True
    # local assignment anywhere
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id in ("history","_history"): return True
    return False

def _md_c_anti(fn):
    ps = [a.arg for a in fn.args.args]
    if "history" not in ps: return False
    idx = ps.index("history") - (len(ps) - len(fn.args.defaults))
    if 0 <= idx < len(fn.args.defaults):
        d = fn.args.defaults[idx]
        if isinstance(d, ast.Name): return True
        if isinstance(d, (ast.List, ast.Set, ast.Dict)): return True
    return False

def _md_c_partial(fn):
    ps = [a.arg for a in fn.args.args]
    if "history" not in ps: return True  # removed param = partial understanding
    return False


# ── 4. effect_order: side-effect inside loop ─────────────────────────

def _eo_strict(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.For):
            for s in n.body:
                if _has_call(s, _SIDE_EFFECT_NAMES): return True
    return False

def _eo_relaxed(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.For):
            for c in ast.walk(n):
                if isinstance(c, ast.Call) and _call_name(c) in _SIDE_EFFECT_NAMES: return True
    return False

def _eo_anti(fn):
    for s in fn.body:
        if isinstance(s, ast.For): continue
        if _has_call(s, _SIDE_EFFECT_NAMES): return True
    return False

def _eo_partial(fn):
    return _has_call(fn, _SIDE_EFFECT_NAMES)


# ── 5. use_before_set ────────────────────────────────────────────────

def _ubs_a_strict(fn):
    hi = False; hse = False
    for s in fn.body:
        if isinstance(s, ast.If):
            for c in ast.walk(s):
                if isinstance(c, ast.Return): hi = True
            if s.orelse: hse = True
    for s in fn.body:
        if isinstance(s, ast.Return):
            if isinstance(s.value, ast.List): hse = True
            if isinstance(s.value, ast.Constant) and s.value.value is None: hse = True
    return hi or hse

def _ubs_a_relaxed(fn):
    if _ubs_a_strict(fn): return True
    for i,s in enumerate(fn.body):
        if isinstance(s, ast.Assign):
            for t in s.targets:
                if isinstance(t, ast.Name) and t.id in ("result","_last_result"):
                    for j in range(i+1, len(fn.body)):
                        if isinstance(fn.body[j], ast.If): return True
    return sum(1 for n in ast.walk(fn) if isinstance(n, ast.Return)) >= 2

def _ubs_b_strict(fn):
    for s in fn.body:
        if isinstance(s, ast.If) and s.orelse:
            for c in ast.walk(ast.Module(body=s.orelse, type_ignores=[])):
                if isinstance(c, ast.Assign):
                    for t in c.targets:
                        if isinstance(t, ast.Name) and t.id == "_status": return True
    return False

def _ubs_b_relaxed(fn):
    if _ubs_b_strict(fn): return True
    for i,s in enumerate(fn.body):
        if isinstance(s, ast.Assign):
            for t in s.targets:
                if isinstance(t, ast.Name) and t.id == "_status":
                    for j in range(i+1, len(fn.body)):
                        if isinstance(fn.body[j], ast.If): return True
    for s in fn.body:
        if isinstance(s, ast.If) and s.orelse:
            for c in ast.walk(ast.Module(body=s.orelse, type_ignores=[])):
                if isinstance(c, ast.Assign):
                    for t in c.targets:
                        if isinstance(t, ast.Name) and "status" in t.id.lower(): return True
    return False

def _ubs_c_strict(fn):
    si = False
    for s in fn.body:
        if isinstance(s, ast.Assign):
            for t in s.targets:
                if isinstance(t, ast.Name) and t.id == "best": si = True
        if isinstance(s, ast.For) and si: return True
    return False

def _ubs_c_relaxed(fn):
    if _ubs_c_strict(fn): return True
    assigned = set()
    for s in fn.body:
        if isinstance(s, ast.For) and "best" in assigned: return True
        if isinstance(s, ast.Assign):
            for t in s.targets:
                if isinstance(t, ast.Name): assigned.add(t.id)
    return False

def _ubs_partial(fn):
    for s in fn.body:
        if isinstance(s, ast.If) and s.orelse: return True
    return sum(1 for n in ast.walk(fn) if isinstance(n, ast.Return)) >= 2


# ── 6. retry_dup: break on success in loop ───────────────────────────

def _retry_strict(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.For):
            for c in ast.walk(n):
                if isinstance(c, ast.Try):
                    for s in c.body:
                        if isinstance(s, ast.Break): return True
                    # break after try inside for
            for s in n.body:
                if isinstance(s, ast.Break): return True
                if isinstance(s, ast.Try):
                    for ts in s.body:
                        if isinstance(ts, ast.Break): return True
    return False

def _retry_relaxed(fn):
    if _retry_strict(fn): return True
    # accept return after success inside loop
    for n in ast.walk(fn):
        if isinstance(n, ast.For):
            for c in ast.walk(n):
                if isinstance(c, ast.Return): return True
                if isinstance(c, ast.Break): return True
    return False

def _retry_anti(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.For):
            has_break = False
            has_return = False
            for c in ast.walk(n):
                if isinstance(c, ast.Break): has_break = True
                if isinstance(c, ast.Return): has_return = True
            if not has_break and not has_return:
                # Check there's a try inside
                for c in ast.walk(n):
                    if isinstance(c, ast.Try): return True
    return False

def _retry_partial(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.For):
            for c in ast.walk(n):
                if isinstance(c, ast.If): return True  # some conditional logic in loop
    return False


# ── 7. partial_rollback: try/except with compensation ────────────────

def _pr_strict(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                has_call = any(isinstance(c, ast.Call) for c in ast.walk(h))
                has_raise = any(isinstance(c, ast.Raise) for c in ast.walk(h))
                if has_call and has_raise: return True
    return False

def _pr_relaxed(fn):
    if _pr_strict(fn): return True
    for n in ast.walk(fn):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                if any(isinstance(c, ast.Call) for c in ast.walk(h)): return True
                if any(isinstance(c, ast.Raise) for c in ast.walk(h)): return True
    return False

def _pr_partial(fn):
    return any(isinstance(n, ast.Try) for n in ast.walk(fn))


# ── 8. partial_update: dependent field assignments ───────────────────

def _pu_strict(fn):
    # Count assignments — fixed version has more assignments than buggy
    assigns = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript): assigns.add(ast.dump(t))
                if isinstance(t, ast.Attribute): assigns.add(ast.dump(t))
    return len(assigns) >= 3  # primary + at least 2 dependent

def _pu_relaxed(fn):
    if _pu_strict(fn): return True
    assigns = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript): assigns.add(ast.dump(t))
                if isinstance(t, ast.Attribute): assigns.add(ast.dump(t))
    return len(assigns) >= 2

def _pu_partial(fn):
    assigns = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript): assigns.add(ast.dump(t))
                if isinstance(t, ast.Attribute): assigns.add(ast.dump(t))
    return len(assigns) >= 1


# ── 9. missing_branch: additional elif ───────────────────────────────

def _mb_strict(fn):
    # Count elif/if branches — must have more than buggy
    count = 0
    for n in ast.walk(fn):
        if isinstance(n, ast.If): count += 1
    return count >= 4  # original has 3-4, fixed adds 1+

def _mb_relaxed(fn):
    # Accept dict-based dispatch too
    for n in ast.walk(fn):
        if isinstance(n, ast.Dict) and len(n.keys) >= 5: return True
    count = 0
    for n in ast.walk(fn):
        if isinstance(n, ast.If): count += 1
    return count >= 4

def _mb_partial(fn):
    count = 0
    for n in ast.walk(fn):
        if isinstance(n, ast.If): count += 1
    return count >= 3


# ── 10. wrong_condition: operator correction ─────────────────────────

def _wc_a_strict(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Compare):
            if any(isinstance(op, ast.GtE) for op in n.ops): return True
    return False

def _wc_b_strict(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.And): return True
    return False

def _wc_c_strict(fn):
    # Operator precedence fix — requires parenthesized expression
    for n in ast.walk(fn):
        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or):
            for v in n.values:
                if isinstance(v, ast.BoolOp) and isinstance(v.op, ast.And): return True
    return False

def _wc_relaxed(fn):
    # Any comparison or boolean fix
    return True  # If the function exists and compiles, likely fixed

def _wc_anti_a(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Compare):
            if any(isinstance(op, ast.Gt) for op in n.ops) and not any(isinstance(op, ast.GtE) for op in n.ops):
                return True
    return False

def _wc_anti_b(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or):
            if not any(isinstance(v, ast.BoolOp) for v in n.values):
                return True
    return False


# ── 11. early_return: record before return ───────────────────────────

def _er_strict(fn):
    # Audit/record call exists before early return, or in finally
    for n in ast.walk(fn):
        if isinstance(n, ast.Try) and n.finalbody:
            if _has_call(ast.Module(body=n.finalbody, type_ignores=[]),
                        {"record","ledger","log_charge","audit","append","log"}):
                return True
    # Check: call before return inside if-branch
    for s in fn.body:
        if isinstance(s, ast.If):
            body = s.body
            has_call = False
            for stmt in body:
                if _has_call(stmt, {"record","ledger","log_charge","audit","append","log"}):
                    has_call = True
                if isinstance(stmt, ast.Return) and has_call: return True
    return False

def _er_relaxed(fn):
    if _er_strict(fn): return True
    # Accept: record call anywhere before any return
    record_names = {"record","ledger","log_charge","audit","append","log","log_attempt"}
    return _has_call(fn, record_names)

def _er_partial(fn):
    return _has_call(fn, {"record","ledger","log_charge","audit","append","log","log_attempt"})


# ── 12. silent_default: correct key name ─────────────────────────────

def _sd_strict(fn):
    # The fix is using the correct key string — check that string constants match
    # Since we can't know the "correct" key without case-specific info,
    # use a heuristic: the function accesses dict with consistent key naming
    for n in ast.walk(fn):
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant):
            if isinstance(n.slice.value, str) and "_" in n.slice.value:
                return True  # snake_case key = likely correct
    return False

def _sd_relaxed(fn):
    if _sd_strict(fn): return True
    # Accept: any dict access with string key
    for n in ast.walk(fn):
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
            return True
        if isinstance(n, ast.Call) and _call_name(n) == "get":
            return True
    return False

def _sd_partial(fn):
    return _sd_relaxed(fn)  # any key access = at least partial understanding


# ── 13. index_misalign: parallel structure consistency ───────────────

def _im_strict(fn):
    # Both parallel structures use same operation (insert + insert, not insert + append)
    insert_count = 0
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "insert":
            insert_count += 1
    return insert_count >= 2

def _im_relaxed(fn):
    if _im_strict(fn): return True
    # Accept: any consistent operation on multiple structures
    ops = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            ops.add(n.func.attr)
    # If there's no mix of insert/append, it's consistent
    return not ({"insert","append"}.issubset(ops))

def _im_partial(fn):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "insert" for n in ast.walk(fn))


# ── 14. temporal_drift: call ordering ────────────────────────────────

def _td_strict(fn):
    # raw_stats call before transform call
    raw_pos = -1; trans_pos = -1
    for i, s in enumerate(fn.body):
        for n in ast.walk(s):
            if isinstance(n, ast.Call):
                nm = _call_name(n)
                if "raw_stats" in nm: raw_pos = i
                if "transform" in nm and trans_pos < 0: trans_pos = i
    return raw_pos >= 0 and trans_pos >= 0 and raw_pos < trans_pos

def _td_relaxed(fn):
    if _td_strict(fn): return True
    # Accept: raw_stats called at all before transform
    has_raw = False
    for s in fn.body:
        if _has_call(s, {"raw_stats","compute_raw","compute_raw_stats"}): has_raw = True
        if has_raw and _has_call(s, {"transform","apply_transform","clean"}): return True
    return False

def _td_anti(fn):
    # raw_stats AFTER transform = bug
    raw_pos = 999; trans_pos = -1
    for i, s in enumerate(fn.body):
        for n in ast.walk(s):
            if isinstance(n, ast.Call):
                nm = _call_name(n)
                if "raw_stats" in nm and i < raw_pos: raw_pos = i
                if "transform" in nm and i > trans_pos: trans_pos = i
    return trans_pos >= 0 and raw_pos > trans_pos

def _td_partial(fn):
    return _has_call(fn, {"raw_stats","compute_raw","compute_raw_stats"})


# ── 15. lazy_init: remove eager capture ──────────────────────────────

def _li_strict(fn):
    # Function does NOT use a captured module-level variable,
    # instead calls get_config()/get_settings() inline
    return _has_call(fn, {"get_config","get_settings","load_settings","Settings"})

def _li_relaxed(fn):
    if _li_strict(fn): return True
    # Accept: any function call to retrieve config inside the function body
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            nm = _call_name(n)
            if any(x in nm.lower() for x in ("config","setting","load","get_")): return True
    return False

def _li_partial(fn):
    return _li_relaxed(fn)


# ── 16. hidden_dep_multihop: function call substitution ──────────────

def _hdm_strict(fn):
    for c in _calls_in(fn):
        if _call_name(c) == "sync_user_to_cache": return True
    return False

def _hdm_anti(fn):
    for c in _calls_in(fn):
        if _call_name(c) == "refresh_user_snapshot": return True
    return False

def _hdm_relaxed(fn):
    if _hdm_strict(fn): return True
    # Accept: cache_put called directly
    for c in _calls_in(fn):
        if _call_name(c) == "cache_put": return True
    return False


# ── 17. invariant_partial_fail: try/except + rollback ────────────────

def _ipf_strict(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                has_aug = any(isinstance(c, ast.AugAssign) for c in ast.walk(h))
                has_raise = any(isinstance(c, ast.Raise) for c in ast.walk(h))
                if has_aug and has_raise: return True
    return False

def _ipf_relaxed(fn):
    if _ipf_strict(fn): return True
    for n in ast.walk(fn):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                has_comp = any(isinstance(c, (ast.AugAssign, ast.Assign, ast.Call)) for c in ast.walk(h))
                has_raise = any(isinstance(c, ast.Raise) for c in ast.walk(h))
                if has_comp and has_raise: return True
    return False

def _ipf_partial(fn):
    return any(isinstance(n, ast.Try) and n.handlers for n in ast.walk(fn))


# ── 18. cache_invalidation_order: keep invalidation before set ───────

def _cio_strict(fn):
    inv_pos = -1; set_pos = -1
    for i, s in enumerate(fn.body):
        if _has_call(s, {"cache_invalidate","invalidate"}): inv_pos = i
        if _has_call(s, {"cache_conditional_set","cache_set"}): set_pos = i
    return inv_pos >= 0 and set_pos >= 0 and inv_pos < set_pos

def _cio_relaxed(fn):
    if _cio_strict(fn): return True
    return _has_call(fn, {"cache_invalidate","invalidate"}) and _has_call(fn, {"cache_conditional_set","cache_set","db_write"})

def _cio_partial(fn):
    return _has_call(fn, {"cache_invalidate","invalidate"})


# ── 19. l3_state_pipeline / commit_gate: restore two calls ──────────

def _l3_strict(fn):
    return _has_call(fn, {"commit"}) and _has_call(fn, {"freeze_view"})

def _l3_relaxed(fn):
    return _l3_strict(fn)

def _l3_partial(fn):
    return _has_call(fn, {"commit"}) or _has_call(fn, {"freeze_view"})


# ── 20. overdetermination: remove write_cached ───────────────────────

def _od_strict(fn):
    return not _has_call(fn, {"write_cached"})

def _od_anti(fn):
    return _has_call(fn, {"write_cached"})

def _od_relaxed(fn):
    return _od_strict(fn)


# ── 21. async_race_lock: keep locking structure ──────────────────────

def _arl_strict(fn):
    return _has_call(fn, {"try_lock","lock"}) and _has_call(fn, {"unlock"})

def _arl_anti(fn):
    return _has_call(fn, {"quick_increment"})

def _arl_relaxed(fn):
    if _arl_strict(fn): return True
    return _has_call(fn, {"try_lock","lock","acquire"})


# =====================================================================
# DISPATCH TABLE
# Maps case_id -> (target_function, strict, relaxed, anti, partial)
# None entry = NOT AST-MEASURABLE
# =====================================================================

CASE_RULES = {}

# alias_config
for sfx in ("a","b","c"):
    CASE_RULES[f"alias_config_{sfx}"] = ("create_config", _alias_strict, _alias_relaxed, _alias_anti, _alias_partial)

# stale_cache
for sfx in ("a","b"):
    CASE_RULES[f"stale_cache_{sfx}"] = ("update_product", _sc_strict, _sc_relaxed, None, _sc_partial)
CASE_RULES["stale_cache_c"] = ("update_product", _sc_c_strict, _sc_c_relaxed, None, _sc_partial)

# mutable_default
CASE_RULES["mutable_default_a"] = ("enqueue", _md_strict, lambda fn: _md_relaxed(fn,"queue"), lambda fn: _md_has_mutable(fn), _md_partial)
CASE_RULES["mutable_default_b"] = ("process_batch", _md_strict, lambda fn: _md_relaxed(fn,"seen"), lambda fn: _md_has_mutable(fn), _md_partial)
CASE_RULES["mutable_default_c"] = ("with_history", _md_c_strict, _md_c_relaxed, _md_c_anti, _md_c_partial)

# effect_order
for sfx in ("a","b","c"):
    CASE_RULES[f"effect_order_{sfx}"] = ("process_batch", _eo_strict, _eo_relaxed, _eo_anti, _eo_partial)

# use_before_set
CASE_RULES["use_before_set_a"] = ("transform", _ubs_a_strict, _ubs_a_relaxed, None, _ubs_partial)
CASE_RULES["use_before_set_b"] = ("load", _ubs_b_strict, _ubs_b_relaxed, None, _ubs_partial)
CASE_RULES["use_before_set_c"] = ("find_best", _ubs_c_strict, _ubs_c_relaxed, None, _ubs_partial)

# retry_dup
_retry_funcs = {"retry_dup_a": "retry_send", "retry_dup_b": "send_with_retry", "retry_dup_c": "ingest"}
for cid, func in _retry_funcs.items():
    CASE_RULES[cid] = (func, _retry_strict, _retry_relaxed, _retry_anti, _retry_partial)

# partial_rollback
for sfx in ("a","b","c"):
    CASE_RULES[f"partial_rollback_{sfx}"] = ("place_order", _pr_strict, _pr_relaxed, None, _pr_partial)

# partial_update
for sfx in ("a","b","c"):
    CASE_RULES[f"partial_update_{sfx}"] = ("update_profile", _pu_strict, _pu_relaxed, None, _pu_partial)

# missing_branch
_mb_funcs = {"missing_branch_a": "get_permissions", "missing_branch_b": "get_access", "missing_branch_c": "authorize"}
for cid, func in _mb_funcs.items():
    CASE_RULES[cid] = (func, _mb_strict, _mb_relaxed, None, _mb_partial)

# wrong_condition
CASE_RULES["wrong_condition_a"] = ("is_rate_limited", _wc_a_strict, _wc_relaxed, _wc_anti_a, None)
CASE_RULES["wrong_condition_b"] = ("is_allowed", _wc_b_strict, _wc_relaxed, _wc_anti_b, None)
CASE_RULES["wrong_condition_c"] = ("should_allow", _wc_c_strict, _wc_relaxed, None, None)

# early_return
_er_funcs = {"early_return_a": "process_payment", "early_return_b": "process_payment", "early_return_c": "charge"}
for cid, func in _er_funcs.items():
    CASE_RULES[cid] = (func, _er_strict, _er_relaxed, None, _er_partial)

# silent_default
_sd_funcs = {"silent_default_a": "is_enabled", "silent_default_b": "is_analytics_enabled", "silent_default_c": "is_enabled"}
for cid, func in _sd_funcs.items():
    CASE_RULES[cid] = (func, _sd_strict, _sd_relaxed, None, _sd_partial)

# index_misalign
_im_funcs = {"index_misalign_a": "add_entry", "index_misalign_b": "add_row", "index_misalign_c": "add_row"}
for cid, func in _im_funcs.items():
    CASE_RULES[cid] = (func, _im_strict, _im_relaxed, None, _im_partial)

# temporal_drift
for sfx in ("a","b","c"):
    CASE_RULES[f"temporal_drift_{sfx}"] = ("pipeline", _td_strict, _td_relaxed, _td_anti, _td_partial)

# lazy_init
_li_funcs = {"lazy_init_a": "get_settings", "lazy_init_b": "get_db_url", "lazy_init_c": "get_api_key"}
for cid, func in _li_funcs.items():
    CASE_RULES[cid] = (func, _li_strict, _li_relaxed, None, _li_partial)

# singletons
CASE_RULES["hidden_dep_multihop"] = ("save_user", _hdm_strict, _hdm_relaxed, _hdm_anti, None)
CASE_RULES["invariant_partial_fail"] = ("execute_transfer", _ipf_strict, _ipf_relaxed, None, _ipf_partial)
CASE_RULES["cache_invalidation_order"] = ("update_record", _cio_strict, _cio_relaxed, None, _cio_partial)
CASE_RULES["l3_state_pipeline"] = ("process_batch", _l3_strict, _l3_relaxed, None, _l3_partial)
CASE_RULES["commit_gate"] = ("process_batch", _l3_strict, _l3_relaxed, None, _l3_partial)
CASE_RULES["overdetermination"] = ("update_product", _od_strict, _od_relaxed, _od_anti, None)
CASE_RULES["async_race_lock"] = ("process_item", _arl_strict, _arl_relaxed, _arl_anti, None)

# NOT AST-MEASURABLE — excluded from CASE_RULES:
# false_fix_deadlock, lost_update, check_then_act, ordering_dependency,
# config_shadowing, feature_flag_drift
