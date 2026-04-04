"""Stage 3: Compute all metrics, tests, tables for oracle intervention."""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

LABELS = ["CORRECT", "PARTIAL", "WRONG", "UNJUDGABLE"]
CONDS = ["baseline_v2", "leg_reduction_v2", "leg_reduction_lean_v2"]
COMPARISONS = [
    ("baseline_v2", "leg_reduction_v2", "base→LEG"),
    ("baseline_v2", "leg_reduction_lean_v2", "base→lean"),
    ("leg_reduction_v2", "leg_reduction_lean_v2", "LEG→lean"),
]


def _rate(num, den):
    return num / den if den > 0 else None


def _pct(v):
    return f"{v:.1%}" if v is not None else "—"


# ── Statistics ────────────────────────────────────────────────


def mcnemar_test(a, b, c, d):
    """McNemar test on 2x2 discordant table. Returns p-value."""
    disc = b + c
    if disc == 0:
        return 1.0
    if disc < 25:
        from math import comb
        # Exact binomial
        p = 0.0
        for k in range(min(b, c), disc + 1):
            p += comb(disc, k) * 0.5 ** disc
        return min(1.0, 2 * p)
    chi2 = (b - c) ** 2 / disc
    # chi2 with df=1 survival function
    from math import erfc, sqrt
    return erfc(sqrt(chi2 / 2) / sqrt(1))


def paired_bootstrap_ci(pairs, n_boot=5000):
    """Bootstrap CI for Δ = mean(pair[1]) - mean(pair[0])."""
    import random
    n = len(pairs)
    if n == 0:
        return 0.0, 0.0, 0.0
    deltas = []
    for _ in range(n_boot):
        sample = random.choices(pairs, k=n)
        d = sum(p[1] - p[0] for p in sample) / n
        deltas.append(d)
    deltas.sort()
    lo = deltas[int(0.025 * n_boot)]
    hi = deltas[int(0.975 * n_boot)]
    point = sum(p[1] - p[0] for p in pairs) / n
    return point, lo, hi


# ── Grouping helpers ──────────────────────────────────────────


def _group_by_triple(rows):
    """Group joined rows by (case_id, model, trial) → {cond: row}."""
    triples = defaultdict(dict)
    for r in rows:
        tk = (r["case_id"], r["model"], r["trial"])
        triples[tk][r["condition"]] = r
    return triples


def _judgable(rows):
    return [r for r in rows if r["reasoning_truth"] != "UNJUDGABLE"]


def _recon_ok(rows):
    return [r for r in rows
            if r.get("reconstruction_status") == "SUCCESS"]


# ── Table 1: Pooled intervention summary ─────────────────────


def compute_pooled_metrics(rows):
    """Table 1: per-condition metrics."""
    table = {}
    for cond in CONDS:
        cr = [r for r in rows if r["condition"] == cond]
        jdg = _judgable(cr)
        n = len(cr)
        nj = len(jdg)
        nc = sum(1 for r in jdg if r["reasoning_truth"] == "CORRECT")
        np_ = sum(1 for r in jdg if r["reasoning_truth"] == "PARTIAL")
        nw = sum(1 for r in jdg if r["reasoning_truth"] == "WRONG")
        nu = n - nj
        ps = sum(1 for r in cr if r["execution_pass"])
        pc = sum(1 for r in jdg
                 if r["reasoning_truth"] == "CORRECT"
                 and r["execution_pass"])
        pp = sum(1 for r in jdg
                 if r["reasoning_truth"] == "PARTIAL"
                 and r["execution_pass"])
        pw = sum(1 for r in jdg
                 if r["reasoning_truth"] == "WRONG"
                 and r["execution_pass"])
        table[cond] = {
            "n": n, "n_judgable": nj,
            "correct": _rate(nc, nj), "partial": _rate(np_, nj),
            "wrong": _rate(nw, nj),
            "unjudgable": _rate(nu, n),
            "pass": _rate(ps, n),
            "pass_given_C": _rate(pc, nc),
            "pass_given_P": _rate(pp, np_),
            "pass_given_W": _rate(pw, nw),
            "strict_leg": _rate(nc - pc, nj),
            "soft_leg": _rate((nc - pc) + (np_ - pp), nj),
            "lucky_fix": _rate(pw, nj),
            "n_C": nc, "n_P": np_, "n_W": nw, "n_U": nu,
        }
    return table


# ── Table 6: LEG Conversion Matrix ───────────────────────────


def compute_conversion_matrix(rows):
    """P(pass|label) per condition."""
    return compute_pooled_metrics(rows)  # already has pass_given_*


# ── Table 2: Intervention deltas ──────────────────────────────


def compute_intervention_deltas(rows):
    """Table 2: deltas between conditions."""
    pooled = compute_pooled_metrics(rows)
    table = []
    for ca, cb, name in COMPARISONS:
        a, b = pooled[ca], pooled[cb]
        table.append({
            "comparison": name,
            "d_pass": _safe_sub(b["pass"], a["pass"]),
            "d_correct": _safe_sub(b["correct"], a["correct"]),
            "d_pass_C": _safe_sub(b["pass_given_C"], a["pass_given_C"]),
            "d_pass_P": _safe_sub(b["pass_given_P"], a["pass_given_P"]),
            "d_soft_leg": _safe_sub(b["soft_leg"], a["soft_leg"]),
            "d_lucky": _safe_sub(b["lucky_fix"], a["lucky_fix"]),
        })
    return table


def _safe_sub(a, b):
    if a is None or b is None:
        return None
    return a - b


# ── Core Tests A-D ────────────────────────────────────────────


def _paired_test(triples, cond_a, cond_b, filter_fn):
    """Run McNemar + bootstrap on filtered matched pairs."""
    pairs = []
    a_ct, b_ct, c_ct, d_ct = 0, 0, 0, 0
    for tk, conds in triples.items():
        if cond_a not in conds or cond_b not in conds:
            continue
        ra, rb = conds[cond_a], conds[cond_b]
        if not filter_fn(ra, rb):
            continue
        pa = int(ra["execution_pass"])
        pb = int(rb["execution_pass"])
        pairs.append((pa, pb))
        if pa and pb:
            a_ct += 1
        elif pa and not pb:
            b_ct += 1
        elif not pa and pb:
            c_ct += 1
        else:
            d_ct += 1

    n = len(pairs)
    if n == 0:
        return {"n": 0, "delta": None, "p": None,
                "ci_lo": None, "ci_hi": None}

    delta, ci_lo, ci_hi = paired_bootstrap_ci(pairs)
    p = mcnemar_test(a_ct, b_ct, c_ct, d_ct)
    return {"n": n, "delta": delta, "p": p,
            "ci_lo": ci_lo, "ci_hi": ci_hi,
            "a": a_ct, "b": b_ct, "c": c_ct, "d": d_ct}


def compute_test_A(rows):
    """Concordant-correct: CORRECT in both conditions."""
    triples = _group_by_triple(rows)
    results = {}
    for ca, cb, name in COMPARISONS:
        results[name] = _paired_test(
            triples, ca, cb,
            lambda ra, rb: (
                ra["reasoning_truth"] == "CORRECT"
                and rb["reasoning_truth"] == "CORRECT"))
    return results


def compute_test_B(rows):
    """Baseline-correct: CORRECT in baseline only."""
    triples = _group_by_triple(rows)
    results = {}
    for ca, cb, name in COMPARISONS:
        base = ca
        results[name] = _paired_test(
            triples, ca, cb,
            lambda ra, rb: ra["reasoning_truth"] == "CORRECT")
    return results


def compute_test_C(rows):
    """Concordant-adequate: C∪P in both conditions."""
    triples = _group_by_triple(rows)
    adequate = {"CORRECT", "PARTIAL"}
    results = {}
    for ca, cb, name in COMPARISONS:
        results[name] = _paired_test(
            triples, ca, cb,
            lambda ra, rb: (
                ra["reasoning_truth"] in adequate
                and rb["reasoning_truth"] in adequate))
    return results


def compute_test_D(rows):
    """Baseline-adequate: C∪P in baseline only."""
    triples = _group_by_triple(rows)
    adequate = {"CORRECT", "PARTIAL"}
    results = {}
    for ca, cb, name in COMPARISONS:
        results[name] = _paired_test(
            triples, ca, cb,
            lambda ra, rb: ra["reasoning_truth"] in adequate)
    return results


# ── Reasoning Stability ──────────────────────────────────────


def compute_reasoning_stability(rows):
    """For baseline-correct triples, track label under treatment."""
    triples = _group_by_triple(rows)
    table = {}
    for ca, cb, name in COMPARISONS:
        stay_c, to_p, to_w, to_u = 0, 0, 0, 0
        for tk, conds in triples.items():
            if ca not in conds or cb not in conds:
                continue
            if conds[ca]["reasoning_truth"] != "CORRECT":
                continue
            tb = conds[cb]["reasoning_truth"]
            if tb == "CORRECT":
                stay_c += 1
            elif tb == "PARTIAL":
                to_p += 1
            elif tb == "WRONG":
                to_w += 1
            else:
                to_u += 1
        total = stay_c + to_p + to_w + to_u
        table[name] = {
            "n": total,
            "stay_correct": _rate(stay_c, total),
            "degrade_partial": _rate(to_p, total),
            "degrade_wrong": _rate(to_w, total),
            "degrade_unjudgable": _rate(to_u, total),
        }
    return table


# ── UNJUDGABLE Shift ─────────────────────────────────────────


def compute_unjudgable_shift(rows):
    """P(UNJUDGABLE) per condition + deltas."""
    table = {}
    for cond in CONDS:
        cr = [r for r in rows if r["condition"] == cond]
        nu = sum(1 for r in cr if r["reasoning_truth"] == "UNJUDGABLE")
        table[cond] = _rate(nu, len(cr))
    table["d_base_leg"] = _safe_sub(
        table.get("leg_reduction_v2"), table.get("baseline_v2"))
    table["d_base_lean"] = _safe_sub(
        table.get("leg_reduction_lean_v2"), table.get("baseline_v2"))
    return table


# ── Reconstruction Control ────────────────────────────────────


def compute_reconstruction_control(rows):
    """Strict vs recon-only deltas."""
    strict_pooled = compute_pooled_metrics(rows)
    recon_rows = _recon_ok(rows)
    recon_pooled = compute_pooled_metrics(recon_rows)

    table = []
    for ca, cb, name in COMPARISONS:
        s_dp = _safe_sub(
            strict_pooled[cb]["pass"], strict_pooled[ca]["pass"])
        r_dp = _safe_sub(
            recon_pooled[cb]["pass"],
            recon_pooled[ca]["pass"]) if cb in recon_pooled else None
        s_dpc = _safe_sub(
            strict_pooled[cb]["pass_given_C"],
            strict_pooled[ca]["pass_given_C"])
        r_dpc = _safe_sub(
            recon_pooled[cb]["pass_given_C"],
            recon_pooled[ca]["pass_given_C"]
        ) if cb in recon_pooled else None
        diff = abs(s_dp - r_dp) if (
            s_dp is not None and r_dp is not None) else None
        table.append({
            "comparison": name,
            "strict_d_pass": s_dp, "recon_d_pass": r_dp,
            "strict_d_pass_C": s_dpc, "recon_d_pass_C": r_dpc,
            "strict_recon_diff": diff,
            "recon_sensitive": diff is not None and diff > 0.05,
        })
    return table


# ── Per-Model Regime ──────────────────────────────────────────


def compute_model_regimes(rows):
    """Table 4: per-model regime classification."""
    models = sorted(set(r["model"] for r in rows))
    table = []
    for model in models:
        mr = [r for r in rows if r["model"] == model]
        base = _judgable([r for r in mr if r["condition"] == "baseline_v2"])
        lean = _judgable([
            r for r in mr
            if r["condition"] == "leg_reduction_lean_v2"])
        if not base:
            continue
        n = len(mr)
        nc = sum(1 for r in base if r["reasoning_truth"] == "CORRECT")
        pc = _rate(nc, len(base))
        pc_pass = sum(
            1 for r in base
            if r["reasoning_truth"] == "CORRECT"
            and r["execution_pass"])
        ppc = _rate(pc_pass, nc)
        # Regime
        if pc is not None and pc < 0.5:
            regime = "reasoning-limited"
        elif ppc is not None and ppc < 0.7:
            regime = "execution-limited"
        else:
            regime = "capable"
        # Lean deltas
        lnc = sum(1 for r in lean if r["reasoning_truth"] == "CORRECT")
        lpc = _rate(lnc, len(lean)) if lean else None
        lpass = _rate(
            sum(1 for r in lean if r["execution_pass"]),
            len(lean)) if lean else None
        bpass = _rate(
            sum(1 for r in base if r["execution_pass"]),
            len(base))
        unjdg_rate = _rate(
            sum(1 for r in mr
                if r["reasoning_truth"] == "UNJUDGABLE"),
            n)
        table.append({
            "model": model, "n": n,
            "p_correct": pc, "p_pass_C": ppc,
            "regime": regime,
            "d_pass_lean": _safe_sub(lpass, bpass),
            "d_correct_lean": _safe_sub(lpc, pc),
            "unjudgable_rate": unjdg_rate,
            "excluded": unjdg_rate is not None and unjdg_rate > 0.8,
        })
    return table


# ── Model Exclusion Sensitivity ───────────────────────────────


def compute_exclusion_sensitivity(rows):
    """Re-run pooled with/without excluded models."""
    regimes = compute_model_regimes(rows)
    excluded = {r["model"] for r in regimes if r["excluded"]}
    if not excluded:
        return {"excluded_models": [], "impact": "none"}

    full = compute_pooled_metrics(rows)
    filtered = compute_pooled_metrics(
        [r for r in rows if r["model"] not in excluded])
    deltas = {}
    for cond in CONDS:
        deltas[cond] = {
            "pass_full": full[cond]["pass"],
            "pass_excl": filtered[cond]["pass"],
            "correct_full": full[cond]["correct"],
            "correct_excl": filtered[cond]["correct"],
        }
    return {
        "excluded_models": list(excluded),
        "deltas": deltas,
    }
