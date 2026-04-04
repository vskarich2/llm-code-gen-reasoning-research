"""Oracle tab + oracle-only mode."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.components.styling import style_dataframe, style_field_introspection_table
from dashboard.derived_fields import DERIVED_FIELDS
from dashboard.schema import FIELD_REGISTRY


def render_oracle(df: pd.DataFrame) -> None:
    st.subheader("Oracle")
    if "oracle_verdict" not in df.columns:
        st.info("No oracle labels loaded.")
        return

    valid = df[df["oracle_verdict"].notna()].copy()
    if valid.empty:
        st.info("Oracle labels were loaded but did not match the filtered rows.")
        return

    cols = st.columns(4)
    cols[0].metric("Oracle-Labeled Rows", f"{len(valid):,}")
    judged = valid[valid["oracle_verdict"] != "UNJUDGABLE"]
    accuracy = (judged["oracle_verdict"] == "CORRECT").mean() if len(judged) else 0.0
    cols[1].metric("Oracle Accuracy", f"{accuracy:.1%}")
    cols[2].metric("Correct", f"{(valid['oracle_verdict'] == 'CORRECT').sum():,}")
    cols[3].metric("Incorrect", f"{(valid['oracle_verdict'] == 'INCORRECT').sum():,}")

    overall = (
        valid["oracle_verdict"]
        .value_counts()
        .rename_axis("oracle_verdict")
        .reset_index(name="count")
    )
    st.bar_chart(overall.set_index("oracle_verdict")["count"], use_container_width=True)

    by_model = (
        valid.groupby(["model", "oracle_verdict"])
        .size()
        .rename("count")
        .reset_index()
        .pivot(index="model", columns="oracle_verdict", values="count")
        .fillna(0)
        .reset_index()
    )
    st.markdown("##### By Model")
    st.dataframe(
        style_dataframe(by_model, metric_columns=[c for c in by_model.columns if by_model[c].dtype in ("float64", "int64", "float32", "int32")]),
        use_container_width=True,
        hide_index=True,
    )

    by_condition = (
        valid.groupby(["condition", "oracle_verdict"])
        .size()
        .rename("count")
        .reset_index()
        .pivot(index="condition", columns="oracle_verdict", values="count")
        .fillna(0)
        .reset_index()
    )
    st.markdown("##### By Condition")
    st.dataframe(
        style_dataframe(by_condition, metric_columns=[c for c in by_condition.columns if by_condition[c].dtype in ("float64", "int64", "float32", "int32")]),
        use_container_width=True,
        hide_index=True,
    )


def render_field_introspection(df: pd.DataFrame) -> None:
    st.subheader("Field Introspection")

    rows: list[dict[str, Any]] = []
    for column in sorted(df.columns):
        series = df[column]
        try:
            unique = int(series.nunique())
        except TypeError:
            unique = 0
        try:
            sample = series.dropna().iloc[:3].tolist() if series.notna().any() else []
        except TypeError:
            sample = ["(unrenderable)"]
        source = "derived"
        if column in FIELD_REGISTRY:
            source = FIELD_REGISTRY[column]["source"]
        elif column in DERIVED_FIELDS:
            source = "derived"

        sample_text = str(sample)
        rows.append(
            {
                "column": column,
                "dtype": str(series.dtype),
                "null_%": round(float(series.isna().mean() * 100), 1),
                "unique": unique,
                "source": source,
                "sample": sample_text[:77] + "..." if len(sample_text) > 80 else sample_text,
            }
        )

    intro = pd.DataFrame(rows)

    only_problematic = st.checkbox(
        "Show only problematic columns",
        value=False,
        key="field_introspection_problematic_only",
    )
    if only_problematic:
        intro = intro[
            (intro["null_%"] > 10)
            | (intro["unique"] == 1)
            | intro["column"].str.contains("error|parse|fail", case=False, na=False)
        ]

    st.dataframe(
        style_field_introspection_table(intro),
        use_container_width=True,
        hide_index=True,
        height=min(38 * len(intro) + 38, 1200),
    )


def render_oracle_only_mode(oracle_df: pd.DataFrame, live_mode: bool, poll_interval: int) -> None:
    st.markdown(
        " | ".join(
            [
                f"**{len(oracle_df):,} oracle labels**",
                f"**{oracle_df['model'].nunique():,} models**" if "model" in oracle_df.columns else "",
                f"**{oracle_df['condition'].nunique():,} conditions**" if "condition" in oracle_df.columns else "",
                f"**{oracle_df['case_id'].nunique():,} cases**" if "case_id" in oracle_df.columns else "",
            ]
        )
    )
    tabs = st.tabs(["Oracle", "Field Introspection"])
    with tabs[0]:
        render_oracle(oracle_df)
    with tabs[1]:
        render_field_introspection(oracle_df)
    if live_mode:
        time.sleep(poll_interval)
        st.cache_data.clear()
        st.rerun()
