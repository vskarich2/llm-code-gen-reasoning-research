"""V2 metrics computation — pure function from merged_run.jsonl rows.

All metrics are computed over UNIQUE rows only, keyed by
(case_id, condition, trial, model). Duplicates are dropped.

Every metric includes counts alongside rates.
"""

from collections import Counter, defaultdict


def _row_key(row: dict) -> tuple:
    return (
        row.get("case_id"),
        row.get("condition"),
        row.get("trial"),
        row.get("model"),
    )


def _dedup(rows: list[dict]) -> list[dict]:
    """Keep first occurrence of each (case_id, condition, trial, model)."""
    seen = set()
    result = []
    for row in rows:
        key = _row_key(row)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _rate(count: int, total: int) -> dict:
    """Return rate dict with count, total, and pct."""
    return {
        "count": count,
        "total": total,
        "pct": round(count / total, 4) if total else 0,
    }


def compute_v2_metrics(
    rows: list[dict],
    expected_cases: int | None = None,
    expected_conditions: int | None = None,
    expected_trials: int | None = None,
    expected_models: int | None = None,
) -> dict:
    """Compute v2 dashboard metrics from merged_run.jsonl rows.

    All metrics computed over deduplicated rows only.
    Every metric includes counts.
    """
    deduped = _dedup(rows)
    n_dupes = len(rows) - len(deduped)
    n = len(deduped)

    # Progress
    actual_cases = len(set(r.get("case_id") for r in deduped))
    actual_conditions = len(set(r.get("condition") for r in deduped))
    actual_trials = len(set(r.get("trial") for r in deduped))
    actual_models = len(set(r.get("model") for r in deduped))

    nc = expected_cases or actual_cases
    nd = expected_conditions or actual_conditions
    nt = expected_trials or actual_trials
    nm = expected_models or actual_models
    expected_total = nc * nd * nt * nm

    m = {
        "completed": n,
        "expected": expected_total,
        "pct_complete": round(100 * n / expected_total, 1) if expected_total else 0,
        "duplicates_dropped": n_dupes,
        "unique_cases": actual_cases,
        "unique_conditions": actual_conditions,
        "unique_trials": actual_trials,
        "unique_models": actual_models,
    }

    if n == 0:
        m["condition_metrics"] = {}
        return m

    # Per-condition metrics
    conditions = sorted(set(r.get("condition") for r in deduped))
    cond_metrics = {}

    for cond in conditions:
        ce = [r for r in deduped if r.get("condition") == cond]
        cn = len(ce)

        ev_list = [r.get("evaluation", {}) for r in ce]
        passes = sum(1 for ev in ev_list if ev.get("pass"))

        # V2 categories
        cats = Counter(ev.get("v2_category") for ev in ev_list)

        # Classifier dimensions
        dims = {}
        for dim in ("reasoning_internal_consistency_dim", "reasoning_internal_consistency_dim", "commitments_extracted_dim",
                     "commitments_satisfied_dim", "reasoning_code_alignment_dim"):
            vals = Counter(ev.get(dim) for ev in ev_list if ev.get(dim))
            rated = sum(vals.values())
            dims[dim] = {
                "CORRECT": _rate(vals.get("CORRECT", 0), rated),
                "PARTIAL": _rate(vals.get("PARTIAL", 0), rated),
                "WRONG": _rate(vals.get("WRONG", 0), rated),
                "rated": rated,
            }

        # Parse tiers
        tiers_list = [ev.get("v2_parse_tiers", {}) for ev in ev_list]
        exec_valid = sum(1 for t in tiers_list if t.get("exec_parse_valid"))
        fmt_valid = sum(1 for t in tiers_list if t.get("format_valid"))
        rec_valid = sum(1 for t in tiers_list if t.get("recovery_parse_valid"))
        recoverable = sum(1 for t in tiers_list if t.get("recoverable"))
        has_tiers = sum(1 for t in tiers_list if t)

        cond_metrics[cond] = {
            "n": cn,
            "pass": _rate(passes, cn),
            "categories": {cat: _rate(cnt, cn) for cat, cnt in cats.most_common()},
            "dimensions": dims,
            "parse_tiers": {
                "has_data": has_tiers,
                "exec_valid": _rate(exec_valid, cn),
                "format_valid": _rate(fmt_valid, cn),
                "recovery_valid": _rate(rec_valid, cn),
                "recoverable": _rate(recoverable, cn),
                "serialization_tax": _rate(rec_valid - exec_valid, cn),
            },
        }

    m["condition_metrics"] = cond_metrics

    # Cross-condition: BL vs LEG intervention effect
    bl_key = next((c for c in conditions if "baseline" in c), None)
    leg_key = next((c for c in conditions if c.startswith("leg_reduction_v2") and "lean" not in c), None)

    if bl_key and leg_key:
        bl_by_case = {r.get("case_id"): r for r in deduped if r.get("condition") == bl_key}
        lg_by_case = {r.get("case_id"): r for r in deduped if r.get("condition") == leg_key}
        common = set(bl_by_case) & set(lg_by_case)

        helps = hurts = both_pass = both_fail = 0
        for cid in common:
            bp = bl_by_case[cid].get("evaluation", {}).get("pass", False)
            lp = lg_by_case[cid].get("evaluation", {}).get("pass", False)
            if bp and lp: both_pass += 1
            elif not bp and not lp: both_fail += 1
            elif not bp and lp: helps += 1
            else: hurts += 1

        m["intervention_effect"] = {
            "compared_cases": len(common),
            "helps": helps,
            "hurts": hurts,
            "both_pass": both_pass,
            "both_fail": both_fail,
            "net": helps - hurts,
        }

        bl_pr = cond_metrics.get(bl_key, {}).get("pass", {}).get("pct", 0)
        lg_pr = cond_metrics.get(leg_key, {}).get("pass", {}).get("pct", 0)
        m["delta_pass_bl_leg"] = round(lg_pr - bl_pr, 4)

    # Per-family metrics (if failure_mode in case case_data)
    family_rows = defaultdict(list)
    for r in deduped:
        fm = r.get("failure_mode") or r.get("evaluation", {}).get("failure_mode")
        if fm:
            family_rows[fm].append(r)

    if family_rows:
        family_metrics = {}
        for fm, frows in sorted(family_rows.items()):
            fn = len(frows)
            fp = sum(1 for r in frows if r.get("evaluation", {}).get("pass"))
            family_metrics[fm] = _rate(fp, fn)
        m["family_metrics"] = family_metrics

    # ── PER-CASE METRICS ──
    m["case_metrics"] = _compute_case_metrics(deduped, conditions)

    # ── PER-MODEL METRICS (if multiple models) ──
    models = sorted(set(r.get("model") for r in deduped))
    if len(models) > 1:
        model_metrics = {}
        for mdl in models:
            mdl_rows = [r for r in deduped if r.get("model") == mdl]
            mdl_m = {}
            for cond in conditions:
                ce = [r for r in mdl_rows if r.get("condition") == cond]
                cn = len(ce)
                if cn == 0:
                    continue
                passes = sum(1 for r in ce if r.get("evaluation", {}).get("pass"))
                mdl_m[cond] = _rate(passes, cn)
            model_metrics[mdl] = mdl_m
        m["model_metrics"] = model_metrics

    return m


def _compute_case_metrics(deduped: list[dict], conditions: list[str]) -> dict:
    """Compute per-case metrics: pass table, LEG detection, intervention, stability."""

    # Group by (case_id, condition) across all trials/models
    case_cond = defaultdict(list)  # (case_id, condition) -> [row, ...]
    for r in deduped:
        case_cond[(r.get("case_id"), r.get("condition"))].append(r)

    case_ids = sorted(set(cid for cid, _ in case_cond))

    # 1. Per-case pass/fail table with trial counts
    case_pass_table = {}
    for cid in case_ids:
        cond_results = {}
        for cond in conditions:
            rows = case_cond.get((cid, cond), [])
            n_trials = len(rows)
            n_pass = sum(1 for r in rows if r.get("evaluation", {}).get("pass"))
            cond_results[cond] = {"pass": n_pass, "total": n_trials}
        case_pass_table[cid] = cond_results

    # 2. Per-case LEG detection
    case_leg = {}
    for cid in case_ids:
        leg_conds = []
        for cond in conditions:
            rows = case_cond.get((cid, cond), [])
            leg_count = sum(
                1 for r in rows
                if r.get("evaluation", {}).get("v2_category") == "LEG_v2"
            )
            if leg_count > 0:
                leg_conds.append({"condition": cond, "count": leg_count,
                                  "total": len(rows)})
        if leg_conds:
            case_leg[cid] = leg_conds

    # 3. Per-case intervention effect (BL vs LEG)
    bl_key = next((c for c in conditions if "baseline" in c), None)
    leg_key = next((c for c in conditions if c.startswith("leg_reduction_v2")
                    and "lean" not in c), None)

    case_intervention = {}
    leg_helps_cases = []
    leg_hurts_cases = []

    if bl_key and leg_key:
        for cid in case_ids:
            bl_rows = case_cond.get((cid, bl_key), [])
            lg_rows = case_cond.get((cid, leg_key), [])
            if not bl_rows or not lg_rows:
                continue

            # Majority vote across trials
            bl_pass_n = sum(1 for r in bl_rows if r.get("evaluation", {}).get("pass"))
            lg_pass_n = sum(1 for r in lg_rows if r.get("evaluation", {}).get("pass"))
            bl_majority = bl_pass_n > len(bl_rows) / 2
            lg_majority = lg_pass_n > len(lg_rows) / 2

            if bl_majority and not lg_majority:
                effect = "HURTS"
                bl_cat = _majority_category(bl_rows)
                lg_cat = _majority_category(lg_rows)
                leg_hurts_cases.append({
                    "case_id": cid, "bl_cat": bl_cat, "leg_cat": lg_cat,
                    "bl_pass": f"{bl_pass_n}/{len(bl_rows)}",
                    "leg_pass": f"{lg_pass_n}/{len(lg_rows)}",
                })
            elif not bl_majority and lg_majority:
                effect = "HELPS"
                bl_cat = _majority_category(bl_rows)
                lg_cat = _majority_category(lg_rows)
                leg_helps_cases.append({
                    "case_id": cid, "bl_cat": bl_cat, "leg_cat": lg_cat,
                    "bl_pass": f"{bl_pass_n}/{len(bl_rows)}",
                    "leg_pass": f"{lg_pass_n}/{len(lg_rows)}",
                })
            elif bl_majority and lg_majority:
                effect = "BOTH_PASS"
            else:
                effect = "BOTH_FAIL"

            case_intervention[cid] = {
                "effect": effect,
                "bl_pass": f"{bl_pass_n}/{len(bl_rows)}",
                "leg_pass": f"{lg_pass_n}/{len(lg_rows)}",
            }

    # 4. Cross-trial stability
    unstable_cases = []
    for cid in case_ids:
        for cond in conditions:
            rows = case_cond.get((cid, cond), [])
            if len(rows) < 2:
                continue
            pass_vals = set(bool(r.get("evaluation", {}).get("pass")) for r in rows)
            if len(pass_vals) > 1:
                n_pass = sum(1 for r in rows if r.get("evaluation", {}).get("pass"))
                unstable_cases.append({
                    "case_id": cid, "condition": cond,
                    "pass": n_pass, "total": len(rows),
                })

    return {
        "case_pass_table": case_pass_table,
        "case_leg": case_leg,
        "case_intervention": case_intervention,
        "leg_helps_cases": leg_helps_cases,
        "leg_hurts_cases": leg_hurts_cases,
        "unstable_cases": unstable_cases,
    }


def _majority_category(rows: list[dict]) -> str:
    """Return most common v2_category across rows."""
    cats = Counter(r.get("evaluation", {}).get("v2_category", "?") for r in rows)
    return cats.most_common(1)[0][0] if cats else "?"
