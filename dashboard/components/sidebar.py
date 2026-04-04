"""Sidebar rendering."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from dashboard.compute_engine import list_metrics
from dashboard.data.loaders import find_experiments
from dashboard.derived_fields import DERIVED_FIELDS
from dashboard.schema import FIELD_REGISTRY


def render_sidebar() -> tuple[list[str], list[tuple[str, Path]], bool, int]:
    st.sidebar.title("LEG Dashboard")

    st.sidebar.markdown("**Oracle**")
    oracle_files = {
        "oracle_intervention": Path("artifacts/audits/oracle_intervention/oracle_labels.jsonl"),
        "oracle_critique": Path("artifacts/audits/oracle_critique/oracle_labels.jsonl"),
    }

    selected_oracle: list[tuple[str, Path]] = []
    for name, path in oracle_files.items():
        if not path.exists():
            st.sidebar.caption(f"{name} (not found)")
            continue
        count = sum(1 for _ in path.open(encoding="utf-8"))
        label = f"{name} ({count:,} labels)"
        if st.sidebar.checkbox(label, value=False, key=f"oracle_{name}"):
            selected_oracle.append((name, path))

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Experiments**")

    selected_experiments: list[str] = []
    for exp in find_experiments():
        label = Path(exp).name
        parent = Path(exp).parent.name
        if parent != "logs":
            label = f"{parent}/{label}"
        if st.sidebar.checkbox(label, value=False, key=f"exp_{exp}"):
            selected_experiments.append(exp)

    st.sidebar.markdown("---")
    live_mode = st.sidebar.toggle("Live Mode", value=False)
    poll_interval = 5
    if live_mode:
        poll_interval = st.sidebar.slider("Poll interval (sec)", min_value=2, max_value=30, value=5)

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Metrics registry: {len(list_metrics())}")
    st.sidebar.caption(f"Schema fields: {len(FIELD_REGISTRY)} source + {len(DERIVED_FIELDS)} derived")

    return selected_experiments, selected_oracle, live_mode, poll_interval
