"""Three-Axis Evaluation Page — 5-class outcome taxonomy.

Displays the formal evaluation model:
  S (serialization) × E (execution) × R (reasoning)
  → 5-class outcome: serialization_failure, reasoning_failure,
    LEG, unsupported_success, interpretable_success
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from dashboard.components.charts import static_bar_chart
from dashboard.components.example_detail import render_example_detail
from dashboard.components.styling import style_dataframe
from dashboard.tab_docs import render_tab_docs


OUTCOME_ORDER = [
    "interpretable_success",
    "unsupported_success",
    "LEG",
    "reasoning_failure",
    "serialization_failure",
]

OUTCOME_COLORS = {
    "interpretable_success": "#4caf50",
    "unsupported_success": "#ff9800",
    "LEG": "#f44336",
    "reasoning_failure": "#9e9e9e",
    "serialization_failure": "#607d8b",
}


def render_three_axis_evaluation(df: pd.DataFrame) -> None:
    st.subheader("Three-Axis Evaluation (5-Class Taxonomy)")
    render_tab_docs("three_axis")

    if "outcome_class" not in df.columns:
        st.warning("outcome_class not available. Apply evaluation fields first.")
        return

    # ── 2.1 GLOBAL SUMMARY ──
    st.markdown("##### Global Summary")
    n = len(df)
    cols = st.columns(4)
    cols[0].metric("Total Attempts", f"{n:,}")
    cols[1].metric("Serialization Rate", f"{df['serialization_success'].mean():.1%}" if n else "—")
    cols[2].metric("Execution Rate", f"{df['execution_success'].mean():.1%}" if n else "—")
    cols[3].metric("Reasoning Rate", f"{df['reasoning_sufficient'].mean():.1%}" if n else "—")

    cols2 = st.columns(4)
    serialized = df[df["serialization_success"]]
    cols2[0].metric("LEG Rate", f"{df['LEG'].mean():.1%}" if n else "—")
    cols2[1].metric("Interpretable Success", f"{(df['outcome_class'] == 'interpretable_success').mean():.1%}" if n else "—")
    cols2[2].metric("Unsupported Success", f"{(df['outcome_class'] == 'unsupported_success').mean():.1%}" if n else "—")
    cols2[3].metric("Reasoning Failure", f"{(df['outcome_class'] == 'reasoning_failure').mean():.1%}" if n else "—")

    # ── 2.2 FIVE-CLASS DISTRIBUTION ──
    st.markdown("---")
    st.markdown("##### Five-Class Outcome Distribution")

    dist = df["outcome_class"].value_counts()
    dist_pct = df["outcome_class"].value_counts(normalize=True)

    # Reindex to canonical order
    dist = dist.reindex(OUTCOME_ORDER).fillna(0).astype(int)
    dist_pct = dist_pct.reindex(OUTCOME_ORDER).fillna(0)

    col_chart, col_table = st.columns([2, 1])
    with col_chart:
        static_bar_chart(dist)
    with col_table:
        dist_df = pd.DataFrame({"count": dist, "pct": dist_pct}).reset_index()
        dist_df.columns = ["outcome_class", "count", "pct"]
        st.dataframe(
            style_dataframe(dist_df, metric_columns=["count", "pct"]),
            use_container_width=True,
            hide_index=True,
        )

    # ── 2.3 CONDITIONAL ON SERIALIZATION ──
    st.markdown("---")
    st.markdown("##### Conditional on Serialization Success")

    if len(serialized) > 0:
        cond_dist = serialized["outcome_class"].value_counts(normalize=True)
        cond_dist = cond_dist.reindex(
            [c for c in OUTCOME_ORDER if c != "serialization_failure"]
        ).fillna(0)

        col_c1, col_c2 = st.columns([2, 1])
        with col_c1:
            static_bar_chart(cond_dist)
        with col_c2:
            cond_df = pd.DataFrame({
                "outcome": cond_dist.index,
                "rate": cond_dist.values,
            })
            st.dataframe(cond_df, use_container_width=True, hide_index=True)
    else:
        st.info("No serialization-successful events.")

    # ── 2.4 BREAKDOWN BY CONDITION ──
    st.markdown("---")
    st.markdown("##### Outcome by Condition")

    if "condition" in df.columns:
        by_cond = (
            df.groupby("condition")
            .agg(
                n=("outcome_class", "size"),
                pass_rate=("execution_success", "mean"),
                LEG_rate=("LEG", "mean"),
                reasoning_failure_rate=("reasoning_sufficient", lambda x: (~x).mean()),
                serialization_failure_rate=("serialization_success", lambda x: (~x).mean()),
            )
            .reset_index()
            .sort_values("condition")
        )
        st.dataframe(
            style_dataframe(by_cond, metric_columns=["n", "pass_rate", "LEG_rate", "reasoning_failure_rate", "serialization_failure_rate"]),
            use_container_width=True,
            hide_index=True,
        )

        # Stacked outcome by condition
        outcome_by_cond = (
            df.groupby(["condition", "outcome_class"])
            .size()
            .rename("count")
            .reset_index()
            .pivot(index="condition", columns="outcome_class", values="count")
            .fillna(0)
        )
        # Reorder columns
        ordered_cols = [c for c in OUTCOME_ORDER if c in outcome_by_cond.columns]
        outcome_by_cond = outcome_by_cond[ordered_cols]
        static_bar_chart(outcome_by_cond)

    # ── 2.5 LEG SUBTYPE ──
    st.markdown("---")
    st.markdown("##### LEG Subtype Analysis")

    leg_df = df[df["LEG"]]
    if len(leg_df) > 0:
        subtype_dist = leg_df["LEG_subtype"].value_counts()
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.metric("Total LEG", f"{len(leg_df):,}")
            st.metric("Congruent", f"{(leg_df['LEG_subtype'] == 'congruent').sum():,}")
            st.metric("Incongruent", f"{(leg_df['LEG_subtype'] == 'incongruent').sum():,}")
        with col_s2:
            static_bar_chart(subtype_dist)
    else:
        st.info("No LEG events in current selection.")

    # ── 2.6 CONFUSION MATRIX ──
    st.markdown("---")
    st.markdown("##### Reasoning × Execution Confusion Matrix")

    if len(serialized) > 0:
        matrix = pd.DataFrame(
            index=["Execution Pass", "Execution Fail"],
            columns=["Reasoning Sufficient", "Not Sufficient"],
            data=[
                [
                    (serialized["execution_success"] & serialized["reasoning_sufficient"]).sum(),
                    (serialized["execution_success"] & ~serialized["reasoning_sufficient"]).sum(),
                ],
                [
                    (~serialized["execution_success"] & serialized["reasoning_sufficient"]).sum(),
                    (~serialized["execution_success"] & ~serialized["reasoning_sufficient"]).sum(),
                ],
            ],
        )
        st.dataframe(
            matrix.style.background_gradient(cmap="Blues"),
            use_container_width=True,
        )
        st.caption("IS = Interpretable Success, US = Unsupported Success, LEG = LEG, RF = Reasoning Failure")

    # ── 2.7 EXAMPLES PANEL ──
    st.markdown("---")
    st.markdown("##### Example Events by Outcome Class")

    example_class = st.selectbox(
        "Select outcome class",
        OUTCOME_ORDER,
        key="three_axis_example_class",
    )

    examples = df[df["outcome_class"] == example_class]
    n_examples = min(5, len(examples))
    if n_examples > 0:
        sample = examples.sample(n_examples, random_state=42)
        # Summary columns vary by outcome class
        summary_cols = ["case_id", "model", "condition"]
        if example_class == "serialization_failure":
            summary_cols += [c for c in [
                "parse_status", "recon_status", "reconstruction_status",
                "serialization_failure_type",
            ] if c in sample.columns]
        elif example_class == "LEG":
            summary_cols += [c for c in [
                "mechanism_dim", "alignment_dim", "LEG_subtype",
                "exec_category",
            ] if c in sample.columns]
        elif example_class == "unsupported_success":
            summary_cols += [c for c in [
                "mechanism_dim", "alignment_dim", "exec_category",
            ] if c in sample.columns]
        else:
            summary_cols += [c for c in [
                "exec_pass", "mechanism_dim", "alignment_dim",
                "exec_category",
            ] if c in sample.columns]
        st.dataframe(
            sample[summary_cols],
            use_container_width=True,
            hide_index=True,
        )

        for idx, row in sample.iterrows():
            label = f"{row.get('case_id', '?')} | {row.get('model', '?')} | {row.get('condition', '?')}"
            with st.expander(label):
                render_example_detail(row, example_class)
    else:
        st.info(f"No {example_class} events in current selection.")
