"""V2 dashboard writer — human-readable text snapshot.

Every percentage includes counts. Progress uses deduplicated counts.
"""

import os
import tempfile
from datetime import datetime
from pathlib import Path


def _pct(rate_dict: dict) -> str:
    """Format a rate dict as 'NN% (count/total)'."""
    if not rate_dict or rate_dict.get("total", 0) == 0:
        return "  -  (0/0)"
    return f"{rate_dict['pct']*100:5.1f}% ({rate_dict['count']}/{rate_dict['total']})"


def write_v2_dashboard(metrics: dict, dashboard_path: Path,
                       prev_metrics: dict | None = None) -> None:
    """Write v2 dashboard to file atomically."""
    lines = []
    w = lines.append

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    completed = metrics.get("completed", 0)
    expected = metrics.get("expected", "?")
    pct = metrics.get("pct_complete", 0)
    dupes = metrics.get("duplicates_dropped", 0)

    w("=" * 78)
    w("  T3 V2 LIVE DASHBOARD")
    w(f"  Updated: {now}")
    w(f"  Progress: {completed}/{expected} ({pct:.1f}%)")
    if dupes:
        w(f"  Duplicates dropped: {dupes}")
    w("=" * 78)

    # Delta from previous
    if prev_metrics:
        prev_completed = prev_metrics.get("completed", 0)
        delta_rows = completed - prev_completed
        if delta_rows > 0:
            w(f"  +{delta_rows} new rows since last update")

    cond_metrics = metrics.get("condition_metrics", {})

    if completed == 0:
        w("  (no case_data yet)")
        w("=" * 78)
        _write_atomic(lines, dashboard_path)
        return

    # ── S1: PASS RATES ──
    w("")
    w("-" * 78)
    w("  S1: PASS RATES")
    w("-" * 78)
    w(f"  {'Condition':<28} {'Pass Rate':>18}  {'N':>5}")
    w(f"  {'─' * 55}")
    for cond, cm in sorted(cond_metrics.items()):
        pr = cm.get("pass", {})
        w(f"  {cond:<28} {_pct(pr):>18}  {cm['n']:>5}")

    # BL vs LEG delta
    delta = metrics.get("delta_pass_bl_leg")
    if delta is not None:
        w(f"  BL→LEG delta: {delta*100:+.1f}pp")

    # ── S2: V2 CATEGORIES ──
    w("")
    w("-" * 78)
    w("  S2: V2 CATEGORIES")
    w("-" * 78)
    cat_names = [
        "interpretable_success", "LEG_v2", "alignment_failure_pass",
        "full_failure_v2", "parser_failure_v2",
    ]
    # Header
    header = f"  {'Cond':<15}"
    for cat in cat_names:
        short = cat.replace("interpretable_success", "INTERP") \
                    .replace("alignment_failure_pass", "ALIGN_F") \
                    .replace("full_failure_v2", "FULL_F") \
                    .replace("parser_failure_v2", "PARSE_F") \
                    .replace("LEG_v2", "LEG")
        header += f" {short:>8}"
    w(header)
    w(f"  {'─' * 60}")
    for cond, cm in sorted(cond_metrics.items()):
        cats = cm.get("categories", {})
        row = f"  {cond:<15}"
        for cat in cat_names:
            rd = cats.get(cat, {})
            cnt = rd.get("count", 0) if rd else 0
            row += f" {cnt:>8}"
        row += f"  (n={cm['n']})"
        w(row)

    # ── S3: LEG INTERVENTION EFFECT ──
    ie = metrics.get("intervention_effect")
    if ie:
        w("")
        w("-" * 78)
        w("  S3: LEG INTERVENTION EFFECT (BL vs LEG_v2)")
        w("-" * 78)
        w(f"  Compared cases: {ie['compared_cases']}")
        w(f"  HELPS:     {ie['helps']:>4}  (BL fails, LEG passes)")
        w(f"  HURTS:     {ie['hurts']:>4}  (BL passes, LEG fails)")
        w(f"  BOTH_PASS: {ie['both_pass']:>4}")
        w(f"  BOTH_FAIL: {ie['both_fail']:>4}")
        w(f"  Net: {ie['net']:+d}")

    # ── S4: PARSE TIERS ──
    has_any_tiers = any(
        cm.get("parse_tiers", {}).get("has_data", 0)
        for cm in cond_metrics.values()
    )
    if has_any_tiers:
        w("")
        w("-" * 78)
        w("  S4: PARSE TIERS")
        w("-" * 78)
        w(f"  {'Cond':<15} {'exec':>18} {'format':>18} {'recovery':>18} {'recoverable':>14}")
        w(f"  {'─' * 70}")
        for cond, cm in sorted(cond_metrics.items()):
            pt = cm.get("parse_tiers", {})
            ev = _pct(pt.get("exec_valid", {}))
            fv = _pct(pt.get("format_valid", {}))
            rv = _pct(pt.get("recovery_valid", {}))
            rc = pt.get("recoverable", {})
            rc_s = f"{rc.get('count', 0)}" if rc else "0"
            w(f"  {cond:<15} {ev:>18} {fv:>18} {rv:>18} {rc_s:>14}")

        # Serialization tax
        for cond, cm in sorted(cond_metrics.items()):
            pt = cm.get("parse_tiers", {})
            tax = pt.get("serialization_tax", {})
            if tax and tax.get("count", 0) > 0:
                w(f"  Serialization tax ({cond}): {tax['count']} events lost to formatting")

    # ── S5: CLASSIFIER DIMENSIONS ──
    has_dims = any(
        any(d.get("rated", 0) for d in cm.get("dimensions", {}).values())
        for cm in cond_metrics.values()
    )
    if has_dims:
        w("")
        w("-" * 78)
        w("  S5: CLASSIFIER DIMENSIONS (% CORRECT)")
        w("-" * 78)
        dim_labels = {
            "reasoning_internal_consistency_dim": "ric",
            "reasoning_internal_consistency_dim": "mechanism(legacy)",
            "commitments_extracted_dim": "extracted",
            "commitments_satisfied_dim": "satisfied",
            "reasoning_code_alignment_dim": "alignment",
        }
        for cond, cm in sorted(cond_metrics.items()):
            dims = cm.get("dimensions", {})
            rated_any = any(d.get("rated", 0) for d in dims.values())
            if not rated_any:
                continue
            w(f"  {cond}:")
            for dim_key, label in dim_labels.items():
                d = dims.get(dim_key, {})
                rated = d.get("rated", 0)
                if rated == 0:
                    continue
                c = d.get("CORRECT", {}).get("count", 0)
                p = d.get("PARTIAL", {}).get("count", 0)
                wr = d.get("WRONG", {}).get("count", 0)
                cpct = d.get("CORRECT", {}).get("pct", 0)
                w(f"    {label:<12} C={c:>3} P={p:>3} W={wr:>3}  ({cpct*100:.0f}% correct, n={rated})")

    # ── S6: FAMILY EFFECTS ──
    fm = metrics.get("family_metrics")
    if fm:
        w("")
        w("-" * 78)
        w("  S6: FAMILY PASS RATES")
        w("-" * 78)
        for family, rd in sorted(fm.items(), key=lambda x: -x[1].get("pct", 0)):
            w(f"  {family:<28} {_pct(rd)}")

    # ── S7: PER-MODEL PASS RATES ──
    model_metrics = metrics.get("model_metrics")
    if model_metrics:
        w("")
        w("-" * 78)
        w("  S7: PER-MODEL PASS RATES")
        w("-" * 78)
        all_conds = sorted(cond_metrics.keys())
        header = f"  {'Model':<20}"
        for c in all_conds:
            header += f" {c:>14}"
        w(header)
        w(f"  {'─' * (20 + 14 * len(all_conds))}")
        for mdl, mconds in sorted(model_metrics.items()):
            row = f"  {mdl:<20}"
            for c in all_conds:
                rd = mconds.get(c)
                if rd:
                    row += f" {_pct(rd):>14}"
                else:
                    row += f" {'—':>14}"
            w(row)

    # ── S8: PER-CASE TABLE ──
    cm = metrics.get("case_metrics", {})
    case_pass_table = cm.get("case_pass_table", {})
    if case_pass_table:
        all_conds = sorted(cond_metrics.keys())
        w("")
        w("-" * 78)
        w("  S8: PER-CASE PASS/FAIL")
        w("-" * 78)
        header = f"  {'Case':<28}"
        for c in all_conds:
            header += f" {c:>8}"
        w(header)
        w(f"  {'─' * (28 + 8 * len(all_conds))}")
        for cid in sorted(case_pass_table):
            conds = case_pass_table[cid]
            row = f"  {cid:<28}"
            for c in all_conds:
                cd = conds.get(c)
                if cd:
                    row += f" {cd['pass']}/{cd['total']:>5}"
                else:
                    row += f" {'—':>8}"
            w(row)

    # ── S9: LEG DETECTION (per case) ──
    case_leg = cm.get("case_leg", {})
    if case_leg:
        w("")
        w("-" * 78)
        w("  S9: LEG DETECTION (reasoning correct, code wrong)")
        w("-" * 78)
        for cid in sorted(case_leg):
            entries = case_leg[cid]
            parts = [f"{e['condition']}({e['count']}/{e['total']})" for e in entries]
            w(f"  {cid:<28} {', '.join(parts)}")

    # ── S10: TOP LEG HELPS / HURTS ──
    helps = cm.get("leg_helps_cases", [])
    hurts = cm.get("leg_hurts_cases", [])

    if helps:
        w("")
        w("-" * 78)
        w(f"  S10a: LEG HELPS ({len(helps)} cases — BL fails, LEG passes)")
        w("-" * 78)
        w(f"  {'Case':<28} {'BL':>8} {'BL cat':<18} {'LEG':>8} {'LEG cat':<18}")
        w(f"  {'─' * 72}")
        for h in sorted(helps, key=lambda x: x["case_id"]):
            w(f"  {h['case_id']:<28} {h['bl_pass']:>8} {h['bl_cat']:<18} {h['leg_pass']:>8} {h['leg_cat']:<18}")

    if hurts:
        w("")
        w("-" * 78)
        w(f"  S10b: LEG HURTS ({len(hurts)} cases — BL passes, LEG fails)")
        w("-" * 78)
        w(f"  {'Case':<28} {'BL':>8} {'BL cat':<18} {'LEG':>8} {'LEG cat':<18}")
        w(f"  {'─' * 72}")
        for h in sorted(hurts, key=lambda x: x["case_id"]):
            w(f"  {h['case_id']:<28} {h['bl_pass']:>8} {h['bl_cat']:<18} {h['leg_pass']:>8} {h['leg_cat']:<18}")

    # ── S11: CROSS-TRIAL STABILITY ──
    unstable = cm.get("unstable_cases", [])
    if unstable:
        w("")
        w("-" * 78)
        w(f"  S11: UNSTABLE CASES (different result across trials)")
        w("-" * 78)
        for u in sorted(unstable, key=lambda x: (x["case_id"], x["condition"])):
            w(f"  {u['case_id']:<28} {u['condition']:<15} {u['pass']}/{u['total']} pass")
    elif metrics.get("unique_trials", 1) > 1:
        w("")
        w("-" * 78)
        w("  S11: CROSS-TRIAL STABILITY")
        w("-" * 78)
        w("  All cases consistent across trials")

    # Delta details
    if prev_metrics:
        prev_cond = prev_metrics.get("condition_metrics", {})
        changes = []
        for cond in cond_metrics:
            curr_pr = cond_metrics[cond].get("pass", {}).get("pct", 0)
            prev_pr = prev_cond.get(cond, {}).get("pass", {}).get("pct", 0)
            diff = curr_pr - prev_pr
            if abs(diff) > 0.001:
                changes.append(f"{cond}: {prev_pr*100:.0f}% → {curr_pr*100:.0f}%")
        if changes:
            w("")
            w("-" * 78)
            w("  CHANGES SINCE LAST UPDATE")
            w("-" * 78)
            for c in changes:
                w(f"  {c}")

    w("")
    w("=" * 78)

    _write_atomic(lines, dashboard_path)


def _write_atomic(lines: list[str], path: Path) -> None:
    """Write text file atomically."""
    path = Path(path)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
