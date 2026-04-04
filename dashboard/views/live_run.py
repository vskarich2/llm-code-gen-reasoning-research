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

    # ── Auto-refresh ──
    if snap.status == "running":
        interval = st.slider(
            "Refresh interval (sec)", 2, 30, 5,
            key="live_run_interval",
        )
        time.sleep(interval)
        st.rerun()


def _render_live_metrics(run_dir: Path) -> None:
    """Read merged_events.jsonl and compute live pass rate."""
    merged = run_dir / "merged_events.jsonl"
    if not merged.exists():
        return

    try:
        total = 0
        passed = 0
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

        if total > 0:
            st.markdown("##### Live Metrics")
            cols = st.columns(3)
            cols[0].metric("Events Merged", f"{total:,}")
            cols[1].metric("Pass Rate", f"{passed / total:.1%}")
            cols[2].metric("Passed", f"{passed:,} / {total:,}")
    except OSError:
        pass
