"""Three-axis evaluation derived fields + AST fields.

Computes the 5-class outcome taxonomy and AST structural signals
from WAL-derived attempt table columns. No recomputation of
classification logic — only reads logged fields.
"""

from __future__ import annotations

import pandas as pd


def _safe_bool_col(df: pd.DataFrame, col: str, default: bool = False) -> pd.Series:
    """Extract a boolean column, filling missing with default."""
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=bool)
    return df[col].fillna(default).astype(bool)


def _safe_str_col(df: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    """Extract a string column, filling missing with default."""
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype=object)
    return df[col].fillna(default).astype(str)


# =====================================================================
# THREE-AXIS EVALUATION (5-class taxonomy)
# =====================================================================

def add_three_axis_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Add the 3-axis evaluation fields to the attempt table.

    If v3 pipeline fields exist (payload.evaluation.*), use them directly.
    Otherwise, derive from v2 payload fields.
    """
    out = df.copy()

    # ── V3 path: fields already computed by pipeline ──
    if "outcome_class" in out.columns and out["outcome_class"].notna().any():
        # Use LEG_field from schema extraction if LEG not already set
        if "LEG" not in out.columns and "LEG_field" in out.columns:
            out["LEG"] = out["LEG_field"].fillna(False).astype(bool)
        # Ensure all expected fields exist
        for col, default in [
            ("serialization_success", False),
            ("execution_success", False),
            ("mechanism_correct", False),
            ("commitments_valid", False),
            ("alignment_positive", False),
            ("reasoning_sufficient", False),
            ("LEG", False),
            ("LEG_subtype", ""),
            ("serialization_failure_type", ""),
        ]:
            if col not in out.columns:
                out[col] = default
            elif out[col].dtype == object and default is False:
                out[col] = out[col].fillna(False).astype(bool)
        return out

    # ── V2 path: derive from raw classifier dimensions ──

    # ── Axis 1: Serialization (S) ──
    # Parse succeeded AND reconstruction succeeded
    parse_ok = _safe_str_col(out, "parse_status").eq("success")
    recon_ok = ~_safe_str_col(out, "reconstruction_status").str.contains(
        "fail|invalid|error", case=False, na=False
    )
    recon_v2 = ~_safe_str_col(out, "recon_status").str.contains(
        "fail|invalid|error", case=False, na=False
    )
    eligible = _safe_bool_col(out, "execution_eligible", default=True)

    out["serialization_success"] = parse_ok & recon_ok & recon_v2 & eligible

    # Serialization failure type
    s_fail = pd.Series("", index=out.index, dtype=object)
    s_fail = s_fail.mask(~parse_ok, "parse_failure")
    s_fail = s_fail.mask(parse_ok & ~(recon_ok & recon_v2), "reconstruction_failure")
    s_fail = s_fail.mask(parse_ok & recon_ok & recon_v2 & ~eligible, "not_eligible")
    out["serialization_failure_type"] = s_fail

    # ── Axis 2: Execution (E) ──
    out["execution_success"] = _safe_bool_col(out, "exec_pass")

    # ── Axis 3: Reasoning (R = M ∧ C) ──
    out["mechanism_correct"] = _safe_str_col(out, "mechanism_dim").eq("CORRECT")
    out["commitments_valid"] = _safe_str_col(out, "satisfied_dim").isin(["CORRECT", "PARTIAL"])
    out["alignment_positive"] = _safe_str_col(out, "alignment_dim").eq("CORRECT")
    out["reasoning_sufficient"] = out["mechanism_correct"] & out["commitments_valid"]

    # ── 5-class outcome ──
    S = out["serialization_success"]
    E = out["execution_success"]
    R = out["reasoning_sufficient"]

    outcome = pd.Series("unknown", index=out.index, dtype=object)
    outcome = outcome.mask(~S, "serialization_failure")
    outcome = outcome.mask(S & E & R, "interpretable_success")
    outcome = outcome.mask(S & E & ~R, "unsupported_success")
    outcome = outcome.mask(S & ~E & R, "LEG")
    outcome = outcome.mask(S & ~E & ~R, "reasoning_failure")
    out["outcome_class"] = outcome

    # ── LEG fields ──
    out["LEG"] = (outcome == "LEG")
    out["LEG_subtype"] = pd.Series("", index=out.index, dtype=object)
    out.loc[out["LEG"], "LEG_subtype"] = out.loc[out["LEG"], "alignment_positive"].map(
        {True: "congruent", False: "incongruent"}
    )

    return out


# =====================================================================
# AST FIELDS
# =====================================================================

def add_ast_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Add AST structural verification fields.

    Runs the AST checkers inline on _extracted_code for each row.
    This matches the offline analysis scripts but runs live on dashboard data.
    """
    import ast as ast_mod
    import logging

    log = logging.getLogger(__name__)
    out = df.copy()

    # If ast_status already present from schema extraction (v3 pipeline), use it
    if "ast_status" in out.columns and out["ast_status"].notna().any():
        # Normalize status values: measured_correct → correct, measured_incorrect → incorrect
        out["ast_status"] = out["ast_status"].map({
            "measured_correct": "correct",
            "measured_incorrect": "incorrect",
            "no_spec": "not_measurable",
            "not_measurable": "not_measurable",
            "correct": "correct",
            "incorrect": "incorrect",
        }).fillna("not_available")
        if "ast_score" not in out.columns:
            out["ast_score"] = out["ast_status"].map({"correct": 1.0, "incorrect": 0.0})
        return out

    # Otherwise, compute AST evaluation from _extracted_code
    try:
        import sys
        from pathlib import Path
        ast_phase1_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts" / "ast_phase1")
        if ast_phase1_dir not in sys.path:
            sys.path.insert(0, ast_phase1_dir)
        from checkers import CASE_RULES, find_function
        from checker_fixes import (
            CASE_RULES_OVERRIDES, MODULE_LEVEL_CASES, NOT_AST_MEASURABLE,
        )
        from checker_fixes_v2 import CHECKER_V2_OVERRIDES
        checkers_available = True
    except ImportError as e:
        log.warning("AST checkers not importable (%s) — AST fields will be not_available", e)
        checkers_available = False

    if not checkers_available:
        out["ast_status"] = "not_available"
        out["ast_score"] = None
        return out

    # L3 anti-pattern override
    from checkers import _has_call
    def _l3_anti(fn):
        return _has_call(fn, {"commit"}) and not _has_call(fn, {"freeze_view"})

    L3_OVERRIDE = {
        "l3_state_pipeline": ("process_batch",
            lambda fn: _has_call(fn, {"commit"}) and _has_call(fn, {"freeze_view"}),
            lambda fn: _has_call(fn, {"commit"}) and _has_call(fn, {"freeze_view"}),
            _l3_anti,
            lambda fn: _has_call(fn, {"commit"}) or _has_call(fn, {"freeze_view"}),
        ),
        "commit_gate": ("process_batch",
            lambda fn: _has_call(fn, {"commit"}) and _has_call(fn, {"freeze_view"}),
            lambda fn: _has_call(fn, {"commit"}) and _has_call(fn, {"freeze_view"}),
            _l3_anti,
            lambda fn: _has_call(fn, {"commit"}) or _has_call(fn, {"freeze_view"}),
        ),
    }

    def _get_rules(cid):
        if cid in NOT_AST_MEASURABLE: return None, False
        if cid in L3_OVERRIDE: return L3_OVERRIDE[cid], False
        if cid in CHECKER_V2_OVERRIDES: return CHECKER_V2_OVERRIDES[cid], False
        if cid in CASE_RULES_OVERRIDES: return CASE_RULES_OVERRIDES[cid], False
        if cid in MODULE_LEVEL_CASES: return MODULE_LEVEL_CASES[cid], True
        if cid in CASE_RULES: return CASE_RULES[cid], False
        return None, False

    def _addl_relaxed(cid, fn):
        if cid.startswith('mutable_default_a'):
            ps = [a.arg for a in fn.args.args]
            return 'queue' not in ps and any(isinstance(s, ast_mod.Assign) and any(isinstance(t, ast_mod.Name) and t.id == 'queue' for t in s.targets) for s in fn.body)
        elif cid.startswith('mutable_default_b'):
            ps = [a.arg for a in fn.args.args]
            return 'seen' not in ps and any(isinstance(s, ast_mod.Assign) and any(isinstance(t, ast_mod.Name) and t.id == 'seen' for t in s.targets) for s in fn.body)
        elif cid.startswith('mutable_default_c'):
            return any(isinstance(n, ast_mod.Call) and isinstance(n.func, ast_mod.Name) and n.func.id == 'hasattr' for n in ast_mod.walk(fn))
        elif cid.startswith('stale_cache_a') or cid.startswith('stale_cache_b'):
            from checkers import _call_name
            sw = False
            for stmt in fn.body:
                for n in ast_mod.walk(stmt):
                    if isinstance(n, ast_mod.Call) and isinstance(n.func, ast_mod.Attribute) and n.func.attr == 'update': sw = True
                    if isinstance(n, ast_mod.Assign):
                        for t in n.targets:
                            if isinstance(t, ast_mod.Subscript) and isinstance(t.value, ast_mod.Name) and 'db' in t.value.id.lower(): sw = True
                if sw:
                    for n in ast_mod.walk(stmt):
                        if isinstance(n, ast_mod.Assign):
                            for t in n.targets:
                                if isinstance(t, ast_mod.Subscript) and isinstance(t.value, ast_mod.Name) and 'cache' in t.value.id.lower(): return True
        return False

    import json
    from pathlib import Path
    cases_path = Path("case_data/cases_v2.json")
    if cases_path.exists():
        cases_data = {c['id']: c for c in json.loads(cases_path.read_text())}
    else:
        cases_data = {}
    multi_file = {cid for cid, c in cases_data.items() if len(c.get('code_files', [])) > 1}

    statuses = []
    for idx, row in out.iterrows():
        cid = row.get("case_id", "")
        code = row.get("_extracted_code", "")
        recon = str(row.get("reconstruction_status", ""))

        rules, is_mod = _get_rules(cid)
        if rules is None:
            statuses.append("not_measurable")
            continue
        if "SUCCESS" not in recon.upper() or not code or not str(code).strip():
            statuses.append("not_available")
            continue

        func_name = rules[0]
        code_str = str(code)

        if f'def {func_name}' not in code_str and cid in multi_file:
            statuses.append("not_available")
            continue

        try:
            tree = ast_mod.parse(code_str)
        except SyntaxError:
            statuses.append("not_available")
            continue

        if is_mod:
            _, sf, rf, af, pf = rules
            ro = rf(tree) if rf else False
            anti = af(tree) if af else False
        else:
            fn = find_function(tree, func_name)
            if fn is None:
                statuses.append("not_available")
                continue
            _, sf, rf, af, pf = rules
            ro = rf(fn) if rf else False
            anti = af(fn) if af else False
            if not ro:
                ro = _addl_relaxed(cid, fn)

        ast_relaxed = ro and not anti
        target_modified = f'def {func_name}' in code_str

        if ast_relaxed:
            statuses.append("correct")
        elif anti:
            statuses.append("incorrect")
        elif not ro and not anti and target_modified:
            statuses.append("unknown")
        else:
            statuses.append("incorrect")

    out["ast_status"] = statuses
    out["ast_score"] = out["ast_status"].map({"correct": 1.0, "incorrect": 0.0}).fillna(None)

    return out


# =====================================================================
# APPLY ALL
# =====================================================================

def apply_evaluation_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all evaluation-derived fields."""
    df = add_three_axis_fields(df)
    df = add_ast_fields(df)
    return df
