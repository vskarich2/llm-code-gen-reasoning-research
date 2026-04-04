"""Stage 3 output: format analysis report from computed metrics."""

from datetime import datetime


def _pct(v):
    return f"{v:.1%}" if v is not None else "—"


def _pp(v):
    return f"{v:+.1%}" if v is not None else "—"


def _pval(v):
    if v is None:
        return "—"
    if v < 0.001:
        return f"{v:.1e}"
    return f"{v:.4f}"


def format_report(pooled, deltas, tests_a, tests_b, tests_c,
                  tests_d, stability, unjdg_shift, recon_ctrl,
                  model_regimes, exclusion, conversion, n_total,
                  reliability=None):
    """Build full markdown report."""
    L = ["# Oracle Intervention Ablation — Full Results", "",
         f"**Date**: {datetime.now().isoformat()[:10]}",
         f"**Total matched events**: {n_total}", ""]

    # Reliability
    if reliability:
        L += ["## 0. Oracle Reliability", ""]
        L.append(f"- A vs A2 (stochasticity): "
                 f"{reliability.get('agree_a_a2', '—')}")
        L.append(f"- A vs B (prompt sensitivity): "
                 f"{reliability.get('agree_a_b', '—')}")
        L.append(f"- Cohen's kappa (A vs B): "
                 f"{reliability.get('kappa_a_b', '—')}")
        L.append("")

    # Table 1
    L += ["## 1. Pooled Intervention Summary (Table 1)", "",
          "| Cond | N | CORRECT | PARTIAL | WRONG | UNJDG | "
          "Pass | P\\|C | P\\|P | P\\|W | StrictLEG | SoftLEG "
          "| Lucky |",
          "|------|---|---------|---------|-------|-------|"
          "------|------|------|------|-----------|---------|"
          "-------|"]
    for cond in ["baseline_v2", "leg_reduction_v2",
                 "leg_reduction_lean_v2"]:
        m = pooled.get(cond, {})
        short = {"baseline_v2": "base",
                 "leg_reduction_v2": "LEG",
                 "leg_reduction_lean_v2": "lean"}[cond]
        L.append(
            f"| {short} | {m.get('n',0)} | "
            f"{_pct(m.get('correct'))} | "
            f"{_pct(m.get('partial'))} | "
            f"{_pct(m.get('wrong'))} | "
            f"{_pct(m.get('unjudgable'))} | "
            f"{_pct(m.get('pass'))} | "
            f"{_pct(m.get('pass_given_C'))} | "
            f"{_pct(m.get('pass_given_P'))} | "
            f"{_pct(m.get('pass_given_W'))} | "
            f"{_pct(m.get('strict_leg'))} | "
            f"{_pct(m.get('soft_leg'))} | "
            f"{_pct(m.get('lucky_fix'))} |")

    # Table 2
    L += ["", "## 2. Intervention Deltas (Table 2)", "",
          "| Comparison | Δ Pass | Δ CORRECT | Δ P\\|C | Δ P\\|P "
          "| Δ SoftLEG | Δ Lucky |",
          "|------------|--------|-----------|--------|--------"
          "|-----------|---------|"]
    for d in deltas:
        L.append(
            f"| {d['comparison']} | "
            f"{_pp(d.get('d_pass'))} | "
            f"{_pp(d.get('d_correct'))} | "
            f"{_pp(d.get('d_pass_C'))} | "
            f"{_pp(d.get('d_pass_P'))} | "
            f"{_pp(d.get('d_soft_leg'))} | "
            f"{_pp(d.get('d_lucky'))} |")

    # Table 3: Core Tests
    L += ["", "## 3. Core Tests A–D (Table 3)", ""]
    for ca, cb, name in [
        ("baseline_v2", "leg_reduction_v2", "base→LEG"),
        ("baseline_v2", "leg_reduction_lean_v2", "base→lean"),
        ("leg_reduction_v2", "leg_reduction_lean_v2", "LEG→lean"),
    ]:
        L.append(f"### {name}")
        L.append("")
        L.append("| Test | N_eff | Δ Pass | McNemar p | 95% CI |")
        L.append("|------|-------|--------|-----------|--------|")
        for tname, tdata in [
            ("A concordant-C", tests_a),
            ("B baseline-C", tests_b),
            ("C concordant-CP", tests_c),
            ("D baseline-CP", tests_d),
        ]:
            t = tdata.get(name, {})
            ci = (f"[{_pp(t.get('ci_lo'))}, {_pp(t.get('ci_hi'))}]"
                  if t.get("ci_lo") is not None else "—")
            L.append(
                f"| {tname} | {t.get('n', 0)} | "
                f"{_pp(t.get('delta'))} | "
                f"{_pval(t.get('p'))} | {ci} |")
        L.append("")

    # Reasoning Stability
    L += ["## 4. Reasoning Stability", "",
          "| Comparison | N | Stay CORRECT | → PARTIAL "
          "| → WRONG | → UNJDG |",
          "|------------|---|-------------|-----------|"
          "---------|---------|"]
    for name, s in stability.items():
        L.append(
            f"| {name} | {s.get('n', 0)} | "
            f"{_pct(s.get('stay_correct'))} | "
            f"{_pct(s.get('degrade_partial'))} | "
            f"{_pct(s.get('degrade_wrong'))} | "
            f"{_pct(s.get('degrade_unjudgable'))} |")

    # UNJUDGABLE shift
    L += ["", "## 5. UNJUDGABLE Shift", ""]
    for cond in ["baseline_v2", "leg_reduction_v2",
                 "leg_reduction_lean_v2"]:
        L.append(f"- {cond}: {_pct(unjdg_shift.get(cond))}")
    L.append(f"- Δ base→LEG: {_pp(unjdg_shift.get('d_base_leg'))}")
    L.append(f"- Δ base→lean: {_pp(unjdg_shift.get('d_base_lean'))}")

    # Reconstruction control
    L += ["", "## 6. Reconstruction Control (Table 5)", "",
          "| Comp | Strict Δ Pass | Recon Δ Pass | "
          "Strict Δ P\\|C | Recon Δ P\\|C | \\|S−R\\| | Sensitive? |",
          "|------|--------------|-------------|"
          "-------------|------------|--------|-----------|"]
    for r in recon_ctrl:
        L.append(
            f"| {r['comparison']} | "
            f"{_pp(r.get('strict_d_pass'))} | "
            f"{_pp(r.get('recon_d_pass'))} | "
            f"{_pp(r.get('strict_d_pass_C'))} | "
            f"{_pp(r.get('recon_d_pass_C'))} | "
            f"{_pct(r.get('strict_recon_diff'))} | "
            f"{'†' if r.get('recon_sensitive') else ''} |")

    # Model regimes
    L += ["", "## 7. Per-Model Regime (Table 4)", "",
          "| Model | N | P(C) | P(P\\|C) | Regime | "
          "Δ Pass(lean) | Δ C(lean) | UNJDG% | Excl? |",
          "|-------|---|------|---------|--------|"
          "-------------|----------|--------|-------|"]
    for m in model_regimes:
        L.append(
            f"| {m['model'][:25]} | {m['n']} | "
            f"{_pct(m.get('p_correct'))} | "
            f"{_pct(m.get('p_pass_C'))} | "
            f"{m.get('regime', '?')} | "
            f"{_pp(m.get('d_pass_lean'))} | "
            f"{_pp(m.get('d_correct_lean'))} | "
            f"{_pct(m.get('unjudgable_rate'))} | "
            f"{'YES' if m.get('excluded') else ''} |")

    # Exclusion sensitivity
    if exclusion.get("excluded_models"):
        L += ["", "## 8. Exclusion Sensitivity", "",
              f"Excluded models: {exclusion['excluded_models']}"]

    # Conversion matrix (Table 6)
    L += ["", "## 9. LEG Conversion Matrix (Table 6)", "",
          "| Condition | P(pass\\|C) | P(pass\\|P) | P(pass\\|W) "
          "| N_C | N_P | N_W |",
          "|-----------|-----------|-----------|-----------|"
          "-----|-----|-----|"]
    for cond in ["baseline_v2", "leg_reduction_v2",
                 "leg_reduction_lean_v2"]:
        m = pooled.get(cond, {})
        short = {"baseline_v2": "base",
                 "leg_reduction_v2": "LEG",
                 "leg_reduction_lean_v2": "lean"}[cond]
        L.append(
            f"| {short} | "
            f"{_pct(m.get('pass_given_C'))} | "
            f"{_pct(m.get('pass_given_P'))} | "
            f"{_pct(m.get('pass_given_W'))} | "
            f"{m.get('n_C', 0)} | {m.get('n_P', 0)} | "
            f"{m.get('n_W', 0)} |")

    return "\n".join(L)
