"""Case/model/condition selection widgets."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def build_case_selection(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    col1, col2, col3, col4 = st.columns(4)

    model_values = sorted(df["model"].dropna().unique().tolist())
    with col1:
        model = st.selectbox("Model", model_values, key=f"{key_prefix}_model")

    condition_values = sorted(df[df["model"] == model]["condition"].dropna().unique().tolist())
    with col2:
        condition = st.selectbox("Condition", condition_values, key=f"{key_prefix}_condition")

    case_values = sorted(
        df[(df["model"] == model) & (df["condition"] == condition)]["case_id"].dropna().unique().tolist()
    )
    with col3:
        case_id = st.selectbox("Case", case_values, key=f"{key_prefix}_case")

    trials = sorted(
        df[
            (df["model"] == model)
            & (df["condition"] == condition)
            & (df["case_id"] == case_id)
        ]["trial_idx"].dropna().unique().tolist()
    )
    with col4:
        trial_idx = st.selectbox("Trial", trials, key=f"{key_prefix}_trial")

    chain = df[
        (df["model"] == model)
        & (df["condition"] == condition)
        & (df["case_id"] == case_id)
        & (df["trial_idx"] == trial_idx)
    ].sort_values("attempt_idx")
    return chain
