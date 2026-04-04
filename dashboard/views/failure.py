"""Failure decomposition tab."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.charts import static_bar_chart
from dashboard.components.styling import style_dataframe
from dashboard.tab_docs import render_tab_docs


def _terminal_stage_counts(df: pd.DataFrame) -> pd.DataFrame:
    counts = (
        df["stage_terminal"]
        .value_counts()
        .rename_axis("stage")
        .reset_index(name="count")
    )
    counts["pct"] = counts["count"] / counts["count"].sum() if counts["count"].sum() else 0.0
    order = ["success", "execution_failure", "reconstruction_failure", "parse_failure"]
    counts["stage_order"] = counts["stage"].apply(lambda x: order.index(x) if x in order else len(order))
    return counts.sort_values("stage_order").drop(columns=["stage_order"])


def render_failure_decomposition(df: pd.DataFrame) -> None:
    st.subheader("Failure Decomposition")
    render_tab_docs("failure")

    cols = st.columns(4)
    parse_fail = float(df["parse_failure"].mean()) if len(df) else 0.0
    recon_fail = float(df["reconstruction_failure"].mean()) if len(df) else 0.0
    exec_fail = float(df["execution_failure"].mean()) if len(df) else 0.0
    reasoning_fail = float(df["reasoning_failure"].mean()) if len(df) else 0.0

    cols[0].metric("Parse Failure", f"{parse_fail:.1%}")
    cols[1].metric("Reconstruction Failure", f"{recon_fail:.1%}")
    cols[2].metric("Execution Failure", f"{exec_fail:.1%}")
    cols[3].metric("Reasoning Failure", f"{reasoning_fail:.1%}")

    st.markdown("---")
    st.markdown("##### Terminal Stage")

    terminal = _terminal_stage_counts(df)
    static_bar_chart(terminal.set_index("stage")["count"])
    st.dataframe(
        style_dataframe(terminal, metric_columns=["count", "pct"]),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("##### Terminal Stage by Model × Condition")
    by_mc = (
        df.groupby(["model", "condition", "stage_terminal"])
        .size()
        .rename("count")
        .reset_index()
    )
    if not by_mc.empty:
        pivot = by_mc.pivot_table(
            index=["model", "condition"],
            columns="stage_terminal",
            values="count",
            fill_value=0,
        ).reset_index()
        st.dataframe(
            style_dataframe(pivot, metric_columns=[c for c in pivot.columns if pivot[c].dtype in ("float64", "int64", "float32", "int32")]),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("##### Failure Funnel")
    funnel = pd.DataFrame(
        {
            "stage": [
                "all_attempts",
                "execution_eligible",
                "reconstruction_ok",
                "execution_pass",
                "reasoning_correct",
            ],
            "count": [
                len(df),
                int(df.get("execution_eligible", pd.Series(False, index=df.index)).fillna(False).sum()),
                int((~df["reconstruction_failure"]).sum()),
                int(df.get("exec_pass", pd.Series(False, index=df.index)).fillna(False).sum()),
                int((~df["reasoning_failure"]).sum()),
            ],
        }
    )
    static_bar_chart(funnel.set_index("stage")["count"])
    st.dataframe(style_dataframe(funnel, metric_columns=["count"]), use_container_width=True, hide_index=True)
