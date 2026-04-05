"""Live Run tab — real-time experiment monitoring.

Reads manifest.json and merged_events.jsonl from an active run
to show progress, live metrics, errors, and active workers.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.data.manifest_loader import (
    load_heartbeat,
    load_manifest,
)


def render_live_run(selected_experiments: list[str] | None = None) -> None:
    st.subheader("Live Run")

    if not selected_experiments:
        st.info("Select an experiment from the sidebar.")
        return

    # Show manifest for each selected experiment that has one
    has_manifest = False
    for exp_path in selected_experiments:
        run_dir = Path(exp_path)
        if not (run_dir / "manifest.json").exists():
            continue
        has_manifest = True
        if len(selected_experiments) > 1:
            st.markdown(f"##### {run_dir.name}")
        _render_run(run_dir)

    if not has_manifest:
        names = ", ".join(Path(p).name for p in selected_experiments)
        st.info(f"No manifest.json found for: {names}. "
                f"Only orchestrator-launched runs have manifests.")

def _render_run(run_dir: Path) -> None:
    """Render live monitoring for a single run directory."""
    snap = load_manifest(run_dir)

    if snap.error:
        st.error(snap.error)
        return

    # ── Status + progress ──
    completed = snap.succeeded + snap.failed
    progress = completed / snap.total if snap.total else 0.0

    status_icon = {
        "running": "🟢",
        "completed": "✅",
        "failed": "❌",
    }.get(snap.status, "⏳")

    st.markdown(f"**Status:** {status_icon} {snap.status}")
    st.progress(progress, text=f"{completed}/{snap.total} ({progress:.1%})")

    # ── State cards ──
    cols = st.columns(4)
    cols[0].metric("Succeeded", f"{snap.succeeded:,}")
    cols[1].metric("Running", f"{snap.running:,}")
    cols[2].metric("Failed", f"{snap.failed:,}")
    cols[3].metric("Pending", f"{snap.pending:,}")

    # ── Live metrics from merged_events ──
    _render_live_metrics(run_dir)

    # ── Errors ──
    if snap.failed_items:
        st.markdown(f"##### Errors ({len(snap.failed_items)})")
        for item in snap.failed_items[:50]:
            wid = item["work_id"]
            err = item.get("error", "unknown")
            attempt = item.get("attempt", 1)
            with st.expander(f"{wid} (attempt {attempt})"):
                st.markdown(f"**Case:** {item.get('case_id', '?')}")
                st.markdown(f"**Condition:** {item.get('condition', '?')}")
                st.markdown(f"**Exit code:** {item.get('exit_code', '?')}")
                st.code(str(err), language="text")

    # ── Active workers ──
    if snap.running_items:
        st.markdown(f"##### Active Workers ({len(snap.running_items)})")
        rows = []
        for item in snap.running_items:
            hb = load_heartbeat(run_dir, item["work_id"])
            row = {
                "work_id": item["work_id"],
                "case_id": item.get("case_id", "?"),
                "condition": item.get("condition", "?"),
            }
            if hb:
                row["current_case"] = hb.get("current_case_id", "?")
                row["completed"] = hb.get("cases_completed", "?")
                row["pid"] = hb.get("pid", "?")
                updated = hb.get("updated_at", "")
                row["last_heartbeat"] = updated
            rows.append(row)
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )

    # ── Config ──
    if snap.config_text:
        with st.expander("Config snapshot", expanded=False):
            st.code(snap.config_text, language="yaml")

    # Auto-refresh handled by main app live mode loop — no sleep/rerun here
    if snap.status == "running":
        st.caption("Auto-refreshing via Live Mode")


def _render_live_metrics(run_dir: Path) -> None:
    """Read merged_events.jsonl and compute live failure decomposition."""
    merged = run_dir / "merged_events.jsonl"
    if not merged.exists():
        return

    try:
        total = 0
        passed = 0
        outcomes: dict[str, int] = {}
        oracle_correct = 0
        oracle_total = 0
        ast_correct = 0
        ast_total = 0
        recon_statuses: dict[str, int] = {}
        exec_categories: dict[str, int] = {}
        classifier_ran = 0
        classifier_skipped = 0

        for line in merged.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event_type") != "case.end":
                continue
            total += 1
            payload = ev.get("payload", {})

            if payload.get("pass"):
                passed += 1

            # Outcome class
            oc = payload.get("evaluation", {}).get("outcome_class", "")
            if oc:
                outcomes[oc] = outcomes.get(oc, 0) + 1

            # Oracle
            oracle = payload.get("oracle", {})
            if oracle.get("oracle_correct") is not None:
                oracle_total += 1
                if oracle["oracle_correct"]:
                    oracle_correct += 1

            # AST
            ast_eval = payload.get("ast_eval", {})
            ast_status = ast_eval.get("status", "")
            if ast_status in ("measured_correct", "measured_incorrect"):
                ast_total += 1
                if ast_status == "measured_correct":
                    ast_correct += 1

            # Reconstruction
            recon = payload.get("reconstruction", {})
            rs = recon.get("recon_status", "")
            if rs:
                recon_statuses[rs] = recon_statuses.get(rs, 0) + 1

            # Execution category
            ec = payload.get("execution_category", "")
            if ec:
                exec_categories[ec] = exec_categories.get(ec, 0) + 1

            # Classifier
            cls = payload.get("classification", {})
            if cls.get("classifier_ran"):
                classifier_ran += 1
            elif cls:
                classifier_skipped += 1

        if total == 0:
            return

        # ── Metrics ──
        st.markdown("##### Live Metrics")

        oracle_pct = f"{oracle_correct / oracle_total:.1%}" if oracle_total else "—"
        ast_pct = f"{ast_correct / ast_total:.1%}" if ast_total else "—"
        exec_gap = "—"
        if oracle_total > 0:
            gap = (oracle_correct / oracle_total) - (passed / total)
            exec_gap = f"{gap:.1%}" if gap > 0 else "0%"
        recon_ok = recon_statuses.get("SUCCESS", 0)
        exec_ok = exec_categories.get("EXECUTION_SUCCESS", 0)

        # AST-Oracle agreement breakdown
        ast_oracle_agree = 0
        ast_oracle_total = 0
        ast_yes_oracle_no = 0  # AST more lenient
        ast_no_oracle_yes = 0  # Oracle more lenient
        # Per-case tracking for hotspots
        case_stats: dict[str, dict] = {}

        for line in merged.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event_type") != "case.end":
                continue
            p = ev.get("payload", {})
            a = p.get("ast_eval", {}).get("status", "")
            o = p.get("oracle", {}).get("oracle_correct")
            cid = ev.get("case_id", "?")
            model = p.get("model", ev.get("model", "?"))
            ep = p.get("pass", False)

            # Per-case stats
            key = f"{cid}|{model}"
            if key not in case_stats:
                case_stats[key] = {"case": cid, "model": model,
                                   "n": 0, "pass": 0, "oracle_ok": 0,
                                   "oracle_n": 0, "ast_ok": 0, "ast_n": 0}
            cs = case_stats[key]
            cs["n"] += 1
            if ep:
                cs["pass"] += 1
            if o is not None:
                cs["oracle_n"] += 1
                if o:
                    cs["oracle_ok"] += 1
            if a in ("measured_correct", "measured_incorrect"):
                cs["ast_n"] += 1
                if a == "measured_correct":
                    cs["ast_ok"] += 1

            if a in ("measured_correct", "measured_incorrect") and o is not None:
                ast_oracle_total += 1
                ast_ok = (a == "measured_correct")
                if ast_ok == o:
                    ast_oracle_agree += 1
                elif ast_ok and not o:
                    ast_yes_oracle_no += 1
                elif not ast_ok and o:
                    ast_no_oracle_yes += 1

        ast_oracle_pct = f"{ast_oracle_agree / ast_oracle_total:.1%}" if ast_oracle_total else "—"
        ast_lenient_pct = f"{ast_yes_oracle_no / ast_oracle_total:.1%}" if ast_oracle_total else "—"
        oracle_lenient_pct = f"{ast_no_oracle_yes / ast_oracle_total:.1%}" if ast_oracle_total else "—"

        def _cell(label, pct, count=""):
            if not label:
                return ""
            count_html = f" <span style='color:#fff'>({count})</span>" if count else ""
            return (
                f"<div style='font-size:0.9rem;color:#fff;white-space:nowrap'>{label}</div>"
                f"<div style='font-size:1.1rem;font-weight:600;white-space:nowrap;margin-bottom:0.6rem'>"
                f"<span style='color:#4ade80'>{pct}</span>{count_html}</div>"
            )

        def _row(items):
            cols = st.columns(6)
            for i, (label, pct, count) in enumerate(items):
                if label:
                    cols[i].markdown(_cell(label, pct, count), unsafe_allow_html=True)

        _row([
            ("Completed", f"{total:,}", ""),
            ("Pass Rate", f"{passed / total:.1%}", ""),
            ("Oracle Correct", oracle_pct, ""),
            ("AST Correct", ast_pct, ""),
            ("Exec Gap", exec_gap, ""),
            ("AST-Oracle Agree", ast_oracle_pct, ""),
        ])

        _row([
            ("AST+ Oracle- (Structure OK, Reasoning Wrong)", ast_lenient_pct, f"{ast_yes_oracle_no:,}"),
            ("", "", ""),
            ("AST- Oracle+ (Reasoning OK, Structure Wrong)", oracle_lenient_pct, f"{ast_no_oracle_yes:,}"),
            ("", "", ""),
            ("", "", ""),
            ("", "", ""),
        ])

        if outcomes:
            sorted_oc = sorted(outcomes.items(), key=lambda x: -x[1])[:6]
            _row([
                (oc, f"{100 * count / total:.1f}%", f"{count:,}")
                for oc, count in sorted_oc
            ] + [("", "", "")] * (6 - len(sorted_oc)))

        _row([
            ("Recon OK", f"{100 * recon_ok / total:.1f}%", f"{recon_ok:,}"),
            ("Exec Pass", f"{100 * exec_ok / total:.1f}%", f"{exec_ok:,}"),
            ("Classifier Ran", f"{100 * classifier_ran / total:.1f}%", f"{classifier_ran:,}"),
            ("", "", ""),
            ("", "", ""),
            ("", "", ""),
        ])

        # ── Metric documentation ──
        with st.expander("Metric definitions"):
            st.markdown("""
##### Row 1 — Core Rates

| Metric | Formula | Significance |
|--------|---------|-------------|
| **Completed** | Count of case.end events | Total evaluated attempts. All other metrics are computed over this denominator. |
| **Pass Rate** | `exec_pass / completed` | Ground-truth behavioral success. The model's code passed all test invariants. This is the primary outcome metric. **Low (<30%):** model struggles with these cases. **High (>80%):** cases may be too easy or model is strong. |
| **Oracle Correct** | `oracle_correct / oracle_evaluated` | Did the model correctly identify the bug mechanism? Judged by an oracle LLM comparing model reasoning against ground-truth bug specs. **Low (<50%):** model doesn't understand these bugs. **High (>90%):** model understands most bugs — if Pass Rate is much lower, that's the execution gap. |
| **AST Correct** | `ast_measured_correct / ast_measurable` | Does the generated code contain the correct structural pattern? Deterministic checker, no LLM. Only computed for cases with AST specs (52/58 cases). **High AST + Low Pass:** correct structure but wrong logic inside functions. |
| **Exec Gap** | `Oracle Correct - Pass Rate` | The Latent Execution Gap. How much reasoning signal is lost in implementation. **This is the core finding.** A 30% exec gap means models understand 30% more bugs than they can fix. **>20%:** significant gap. **>40%:** severe — models understand but can't implement. **<5%:** reasoning and execution are well-aligned. |
| **AST-Oracle Agree** | Agreement rate on cases where both AST and oracle have data | How often structural analysis and reasoning analysis agree. High agreement = the two signals are measuring similar things. Low agreement = they capture different failure modes. |

##### Row 2 — AST vs Oracle Disagreement

| Metric | Formula | Significance |
|--------|---------|-------------|
| **AST+ Oracle- (Structure OK, Reasoning Wrong)** | `(ast=correct AND oracle=wrong) / ast_oracle_total` | Model produced the right code structure but described the wrong root cause. Pattern matching without understanding. **High (>10%):** models are copying fix patterns without causal understanding. |
| **AST- Oracle+ (Reasoning OK, Structure Wrong)** | `(ast=incorrect AND oracle=correct) / ast_oracle_total` | Model identified the correct mechanism but generated wrong structure. Translation failure. **High (>15%):** models understand bugs but can't produce the right code shape — the structural version of LEG. |

##### Row 3 — Outcome Classes

| Outcome | Formula | Significance |
|---------|---------|-------------|
| **interpretable_success** | `oracle=correct AND exec=pass` | Model understood AND implemented correctly. The ideal outcome. |
| **LEG** | `oracle=correct AND exec=fail` | **Latent Execution Gap.** Model understood the bug but code doesn't work. The core research finding. Further split by translation axis (T): **execution_failure** (T=1, code matches reasoning but still fails) vs **translation_failure** (T=0, code doesn't match reasoning). |
| **lucky_fix** | `oracle=wrong AND exec=pass` | Code works but reasoning is wrong. Accidental correctness via pattern matching. **High (>5%):** tests may not discriminate enough, or model exploits heuristics. |
| **coherent_incorrect** | `oracle=wrong AND exec=fail AND T=1` | Wrong reasoning, but code is internally consistent with it. The model is coherently wrong. |
| **incoherent_incorrect** | `oracle=wrong AND exec=fail AND T=0` | Wrong reasoning AND code doesn't match it. Disorganized failure. |
| **serialization_failure** | `routing_valid=false` | Parser couldn't extract valid code from model output. Not a reasoning failure — a formatting failure. |

##### Row 4 — Pipeline Health

| Metric | Formula | Significance |
|--------|---------|-------------|
| **Recon OK** | `recon_status=SUCCESS / completed` | Reconstruction succeeded — model output was valid Python. **Low (<80%):** model produces unparseable/invalid code frequently. Check recon failure types. |
| **Exec Pass** | `execution_category=EXECUTION_SUCCESS / completed` | Same as Pass Rate. Shown here for pipeline context alongside recon and classifier. |
| **Classifier Ran** | `classifier_parse_ok / completed` | The blind classifier successfully parsed its response. **Low (<90%):** classifier prompt or model is producing malformed output. Check skip reasons. |

##### Hotspot Table

Shows case × model combinations where Oracle% is high but Pass% is low — the strongest LEG signals. Deduplicated to one row per case, preferring partial-success cases (more actionable than 0% pass cases which are just "hard"). Sorted by pass rate descending so the most interesting partial-gap cases appear first.
""")

        # ── Execution Gap Hotspots — interesting cases only ──
        if case_stats:
            st.markdown("<br><br>", unsafe_allow_html=True)
            st.markdown("##### Execution Gap Hotspots")
            hotspots = []
            for cs in case_stats.values():
                if cs["oracle_n"] < 3:
                    continue
                oracle_rate = cs["oracle_ok"] / cs["oracle_n"]
                pass_rate = cs["pass"] / cs["n"]
                gap = oracle_rate - pass_rate
                if gap <= 0.05:
                    continue
                hotspots.append({
                    "Case": cs["case"],
                    "Model": cs["model"],
                    "N": cs["n"],
                    "Pass": f"{100 * pass_rate:.0f}%",
                    "Oracle": f"{100 * oracle_rate:.0f}%",
                    "Gap": f"{100 * gap:.0f}%",
                    "_gap": gap,
                    "_pass": pass_rate,
                })

            if hotspots:
                # Deduplicate: group by case, show one row per case
                # with model that has the worst gap
                by_case: dict[str, list] = {}
                for h in hotspots:
                    by_case.setdefault(h["Case"], []).append(h)

                deduped = []
                for case, entries in by_case.items():
                    # Pick the entry with the most interesting gap
                    # (prefer partial pass over 0% pass — 0% is just "hard case")
                    interesting = [e for e in entries if e["_pass"] > 0]
                    if interesting:
                        best = max(interesting, key=lambda e: e["_gap"])
                    else:
                        best = max(entries, key=lambda e: e["_gap"])
                    models = sorted(set(e["Model"] for e in entries))
                    best["Model"] = ", ".join(models) if len(models) > 1 else models[0]
                    deduped.append(best)

                deduped.sort(key=lambda x: (-x["_pass"], -x["_gap"]))
                top = deduped[:10]

                if top:
                    display = pd.DataFrame(top).drop(columns=["_gap", "_pass", "Gap"])
                    st.dataframe(display, use_container_width=True, hide_index=True)

    except OSError:
        pass
