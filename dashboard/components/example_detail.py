"""Example event detail renderer for outcome class examples."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from dashboard.leg_scanner import read_artifact, split_prompt_response


def _has_value(val: Any) -> bool:
    """True if val is non-null, non-empty. Safe for scalars, lists, dicts."""
    if val is None:
        return False
    try:
        if pd.isna(val):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(val, (list, dict)) and not val:
        return False
    if isinstance(val, str) and not val.strip():
        return False
    return True


def render_example_detail(row: pd.Series, outcome_class: str) -> None:
    """Render detail panel for one example event, tailored by class."""
    # ── Header metrics (always shown) ──
    cols = st.columns(4)
    cols[0].markdown(f"**Execution:** {'PASS' if row.get('exec_pass') else 'FAIL'}")
    cols[1].markdown(f"**Mechanism:** {row.get('mechanism_dim', '—')}")
    cols[2].markdown(f"**Alignment:** {row.get('alignment_dim', '—')}")
    satisfied = row.get("satisfied_dim", row.get("commitments_dim", "—"))
    cols[3].markdown(f"**Commitments:** {satisfied}")

    # ── Class-specific context ──
    if outcome_class == "LEG":
        st.info(
            "**Why LEG:** reasoning was judged CORRECT but code failed "
            "execution. The model understood the bug but couldn't "
            "implement the fix."
        )
        subtype = row.get("LEG_subtype", "")
        if subtype:
            st.markdown(f"**LEG Subtype:** {subtype}")
        label = row.get("mechanism_label")
        if _has_value(label):
            st.markdown(f"**Failure Type:** {label}")

    elif outcome_class == "serialization_failure":
        sftype = row.get("serialization_failure_type", "")
        parse_s = row.get("parse_status", "")
        recon_s = row.get(
            "recon_status", row.get("reconstruction_status", ""),
        )
        st.warning(
            f"**Why serialization failure:** {sftype or 'unknown'}. "
            f"Parse: {parse_s or '—'}. "
            f"Reconstruction: {recon_s or '—'}."
        )
        syn = row.get("syntax_errors")
        if _has_value(syn):
            st.markdown(f"**Syntax Errors:** `{syn}`")
        recov = row.get("recovery_types")
        if _has_value(recov):
            st.markdown(f"**Recovery Attempted:** {recov}")

    elif outcome_class == "unsupported_success":
        st.info(
            "**Why unsupported success:** code passed tests but "
            "reasoning was judged incorrect. This is a 'lucky fix'."
        )

    elif outcome_class == "reasoning_failure":
        reasons = row.get("exec_reasons")
        if _has_value(reasons):
            st.markdown(f"**Execution Failure Reasons:** {reasons}")

    # ── Code or raw response ──
    code = row.get("_extracted_code")
    if _has_value(code):
        st.code(str(code)[:5000], language="python")
    else:
        _show_raw_response_fallback(row)

    # ── Execution failure reasons (only when execution was reached) ──
    if outcome_class in ("LEG", "reasoning_failure"):
        reasons = row.get("exec_reasons")
        if _has_value(reasons):
            st.markdown(f"**Execution Failure Reasons:** {reasons}")


def _show_raw_response_fallback(row: pd.Series) -> None:
    """When no extracted code exists, show raw model response."""
    prompt_path = row.get("prompt_path")
    if prompt_path and pd.notna(prompt_path):
        artifact = read_artifact(str(prompt_path))
        if artifact:
            _, response = split_prompt_response(artifact)
            if response.strip():
                st.markdown("**Raw Model Response** (no extracted code):")
                st.code(response[:5000], language="json")
                return
    st.caption("No extracted code. Response artifact not found.")
