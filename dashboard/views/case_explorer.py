"""Case explorer tab: attempt timeline, focus attempt, delta view."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.components.selectors import build_case_selection
from dashboard.components.styling import style_dataframe
from dashboard.leg_scanner import read_artifact, split_prompt_response


def _safe_bool(value: Any) -> bool:
    if pd.isna(value) if not isinstance(value, (list, dict, bool)) else False:
        return False
    return bool(value)


def classify_outcome_label(row: pd.Series) -> str:
    if _safe_bool(row.get("exec_pass")) and _safe_bool(row.get("is_leg")):
        return "alignment_failure_pass"
    if _safe_bool(row.get("exec_pass")) and _safe_bool(row.get("is_lucky_fix")):
        return "lucky_fix"
    if _safe_bool(row.get("exec_pass")):
        return "pass"
    if _safe_bool(row.get("is_leg")):
        return "LEG"
    return "failure"


def extract_primary_json_from_row(row: pd.Series) -> dict[str, Any] | None:
    prompt_path = row.get("prompt_path")
    if not prompt_path or pd.isna(prompt_path):
        return None
    text = read_artifact(prompt_path)
    if not text:
        return None
    _, response = split_prompt_response(text)
    stripped = response.strip()
    start = stripped.find("{")
    if start < 0:
        return None
    depth = 0
    for idx in range(start, len(stripped)):
        char = stripped[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        if depth == 0:
            try:
                value = json.loads(stripped[start : idx + 1])
            except json.JSONDecodeError:
                return None
            return value if isinstance(value, dict) else None
    return None


def render_case_explorer(df: pd.DataFrame) -> None:
    st.subheader("Case Explorer")
    chain = build_case_selection(df, "caseexplorer")
    if chain.empty:
        st.info("No data for this selection.")
        return

    timeline = chain.copy()
    timeline["outcome"] = timeline.apply(classify_outcome_label, axis=1)
    timeline["attempt_label"] = timeline["attempt_idx"].apply(lambda x: f"attempt_{int(x)}")

    st.markdown("##### Attempt Timeline")
    tl_cols = st.columns(5)
    last = timeline.iloc[-1]
    tl_cols[0].metric("Attempts", f"{len(timeline):,}")
    tl_cols[1].metric("Final Pass", "Yes" if _safe_bool(last.get("exec_pass")) else "No")
    tl_cols[2].metric("Final LEG", "Yes" if _safe_bool(last.get("is_leg")) else "No")
    tl_cols[3].metric("Final Category", str(last.get("exec_category", "—")))
    tl_cols[4].metric("Final Outcome", classify_outcome_label(last))

    display_cols = [
        c for c in [
            "attempt_idx", "outcome", "exec_pass", "is_leg", "is_lucky_fix",
            "mechanism_dim", "commitments_dim", "alignment_dim",
            "exec_category", "reconstruction_status", "parse_status",
        ]
        if c in timeline.columns
    ]
    st.dataframe(style_dataframe(timeline[display_cols], metric_columns=[]), use_container_width=True, hide_index=True)

    if len(timeline) > 1:
        st.markdown("##### Attempt Progression")
        progression = timeline.set_index("attempt_label")[["exec_pass", "is_leg"]].astype(int)
        st.line_chart(progression, use_container_width=True)

        selected_attempt = st.select_slider(
            "Focus Attempt",
            options=timeline["attempt_idx"].tolist(),
            value=timeline["attempt_idx"].tolist()[-1],
            key="caseexplorer_focus_attempt",
        )
    else:
        selected_attempt = timeline["attempt_idx"].iloc[0]

    row = timeline[timeline["attempt_idx"] == selected_attempt].iloc[0]

    st.markdown("---")
    st.markdown("##### Focus Attempt Summary")
    summary_cols = st.columns(4)
    summary_cols[0].metric("Execution", "PASS" if _safe_bool(row.get("exec_pass")) else "FAIL")
    summary_cols[1].metric("LEG", "Yes" if _safe_bool(row.get("is_leg")) else "No")
    summary_cols[2].metric("Mechanism", str(row.get("mechanism_dim", "—")))
    summary_cols[3].metric("Alignment", str(row.get("alignment_dim", "—")))

    if "mismatch_critique" in row and pd.notna(row.get("mismatch_critique")):
        st.info(str(row.get("mismatch_critique")))

    parsed_json = extract_primary_json_from_row(row)
    if parsed_json:
        if parsed_json.get("root_cause"):
            st.markdown("**Root Cause**")
            st.caption(str(parsed_json["root_cause"]))
        if parsed_json.get("fix_strategy"):
            st.markdown("**Fix Strategy**")
            st.caption(str(parsed_json["fix_strategy"]))
        commitments = parsed_json.get("code_commitments")
        if isinstance(commitments, list) and commitments:
            st.markdown("**Code Commitments**")
            for commitment in commitments:
                st.caption(f"- {commitment}")

    if len(timeline) > 1 and selected_attempt > timeline["attempt_idx"].min():
        prev = timeline[timeline["attempt_idx"] == selected_attempt - 1]
        if not prev.empty:
            prev_row = prev.iloc[0]
            st.markdown("##### Delta vs Previous Attempt")
            delta_cols = st.columns(3)
            delta_cols[0].metric(
                "Execution",
                f"{'PASS' if _safe_bool(row.get('exec_pass')) else 'FAIL'}",
                delta=f"{'PASS' if _safe_bool(row.get('exec_pass')) else 'FAIL'} from {'PASS' if _safe_bool(prev_row.get('exec_pass')) else 'FAIL'}",
            )
            delta_cols[1].metric("Mechanism", str(row.get("mechanism_dim", "—")))
            delta_cols[2].metric("Alignment", str(row.get("alignment_dim", "—")))
