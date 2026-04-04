"""Failure Taxonomy tab — full causal decomposition (R, T, E axes)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.charts import static_bar_chart
from dashboard.tab_docs import render_tab_docs


# ── Section 1: Summary Cards ──

def _render_summary_cards(df: pd.DataFrame) -> None:
    st.markdown("##### Outcome Summary")
    n = len(df)
    if n == 0:
        st.info("No data.")
        return

    oc = df["outcome_class"]
    counts = [
        ("Success", "interpretable_success"),
        ("LEG", "LEG"),
        ("Lucky Fix", "lucky_fix"),
        ("Coherent Incorr.", "coherent_incorrect"),
        ("Incoherent Incorr.", "incoherent_incorrect"),
        ("Serial. Failure", "serialization_failure"),
    ]
    # Also pick up any outcome classes not in the list
    known = {c for _, c in counts}
    for val in oc.dropna().unique():
        if val not in known:
            counts.append((val, val))

    rows = []
    for label, key in counts:
        count = int((oc == key).sum())
        if count > 0:
            rows.append({"Outcome": label, "Count": count,
                         "%": f"{100 * count / n:.1f}%"})

    summary = pd.DataFrame(rows)
    st.dataframe(summary, use_container_width=True, hide_index=True)
    st.caption(f"Total: {n:,} events")


# ── Section 2: R × E Matrix ──

def _render_re_matrix(df: pd.DataFrame) -> None:
    st.markdown("##### R × E Matrix (Reasoning × Execution)")

    has_r = "reasoning_correct" in df.columns and df["reasoning_correct"].notna().any()
    has_e = "execution_success" in df.columns
    if not has_r or not has_e:
        st.caption("reasoning_correct or execution_success not available.")
        return

    assessable = df[df["reasoning_correct"].notna() & df["serialization_success"]].copy()
    n = len(assessable)
    if n == 0:
        st.caption("No assessable events (serialized + oracle available).")
        return

    R = assessable["reasoning_correct"].astype(bool)
    E = assessable["execution_success"].astype(bool)

    r1e1 = int((R & E).sum())
    r1e0 = int((R & ~E).sum())
    r0e1 = int((~R & E).sum())
    r0e0 = int((~R & ~E).sum())

    matrix = pd.DataFrame(
        index=["R=1 (Correct)", "R=0 (Incorrect)"],
        columns=["E=1 (Pass)", "E=0 (Fail)"],
        data=[
            [f"{r1e1} ({100*r1e1/n:.1f}%)", f"{r1e0} ({100*r1e0/n:.1f}%)"],
            [f"{r0e1} ({100*r0e1/n:.1f}%)", f"{r0e0} ({100*r0e0/n:.1f}%)"],
        ],
    )
    st.dataframe(matrix, use_container_width=True)
    st.caption(
        "R=1,E=1 = Interpretable Success | R=1,E=0 = LEG | "
        "R=0,E=1 = Lucky Fix | R=0,E=0 = Reasoning Failure")


# ── Section 3: LEG Breakdown ──

def _render_leg_breakdown(df: pd.DataFrame) -> None:
    st.markdown("##### LEG Breakdown")

    leg = df[df["outcome_class"] == "LEG"]
    n_leg = len(leg)
    if n_leg == 0:
        st.caption("No LEG events in selection.")
        return

    st.metric("Total LEG", f"{n_leg:,}")

    if "LEG_subtype" in leg.columns and leg["LEG_subtype"].notna().any():
        subtypes = leg["LEG_subtype"].value_counts()
        rows = []
        for subtype, count in subtypes.items():
            rows.append({
                "Subtype": subtype,
                "Count": int(count),
                "Pct of LEG": f"{100 * count / n_leg:.1f}%",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(
            "translation_failure: reasoning correct but code doesn't reflect it (T=0) | "
            "execution_failure: reasoning + translation correct but tests fail (T=1)")
    else:
        st.caption("LEG_subtype not available.")


# ── Section 4: R × T Matrix ──

def _render_rt_matrix(df: pd.DataFrame) -> None:
    st.markdown("##### R × T Matrix (Reasoning × Translation)")

    has_r = "reasoning_correct" in df.columns and df["reasoning_correct"].notna().any()
    has_t = "translation_consistent" in df.columns and df["translation_consistent"].notna().any()
    if not has_r or not has_t:
        st.caption("reasoning_correct or translation_consistent not available.")
        return

    assessable = df[
        df["reasoning_correct"].notna() &
        df["translation_consistent"].notna() &
        df["serialization_success"]
    ].copy()
    n = len(assessable)
    if n == 0:
        st.caption("No events with both R and T available.")
        return

    R = assessable["reasoning_correct"].astype(bool)
    T = assessable["translation_consistent"].astype(bool)

    r1t1 = int((R & T).sum())
    r1t0 = int((R & ~T).sum())
    r0t1 = int((~R & T).sum())
    r0t0 = int((~R & ~T).sum())

    matrix = pd.DataFrame(
        index=["R=1 (Correct)", "R=0 (Incorrect)"],
        columns=["T=1 (Consistent)", "T=0 (Inconsistent)"],
        data=[
            [f"{r1t1} ({100*r1t1/n:.1f}%)", f"{r1t0} ({100*r1t0/n:.1f}%)"],
            [f"{r0t1} ({100*r0t1/n:.1f}%)", f"{r0t0} ({100*r0t0/n:.1f}%)"],
        ],
    )
    st.dataframe(matrix, use_container_width=True)
    st.caption(
        "R=1,T=1 = correct + consistent | R=1,T=0 = translation failure | "
        "R=0,T=1 = coherent incorrect | R=0,T=0 = incoherent incorrect")


# ── Section 5: Execution Failure Breakdown ──

def _render_exec_failure_breakdown(df: pd.DataFrame) -> None:
    st.markdown("##### Execution Failure Breakdown")

    failed = df[~df["execution_success"]]
    if len(failed) == 0:
        st.caption("No execution failures.")
        return

    if "exec_category" in failed.columns:
        cat_col = "exec_category"
    elif "execution_category" in failed.columns:
        cat_col = "execution_category"
    else:
        st.caption("execution_category not available.")
        return

    dist = failed[cat_col].value_counts()
    n_fail = len(failed)
    rows = []
    for cat, count in dist.items():
        rows.append({
            "Category": cat,
            "Count": int(count),
            "Pct of Failures": f"{100 * count / n_fail:.1f}%",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Section 6: Classifier Dimensions ──

def _render_classifier_dims(df: pd.DataFrame) -> None:
    st.markdown("##### Classifier Dimension Distribution")

    dim_cols = {
        "RIC": "reasoning_internal_consistency",
        "CIC": "commitments_internal_consistency",
        "CCC": "commitments_code_consistency",
        "RCA": "reasoning_code_alignment",
    }

    # Check if any v3 dims exist (either as flat columns or from classifier_dims)
    available = {}
    for short, full in dim_cols.items():
        if full in df.columns and df[full].notna().any():
            available[short] = full

    # Also check classifier_mechanism for v2 fallback
    if not available:
        if "classifier_mechanism" in df.columns and df["classifier_mechanism"].notna().any():
            st.caption("V3 classifier dimensions not available. Showing v2 mechanism only.")
            dist = df["classifier_mechanism"].value_counts()
            st.dataframe(
                dist.reset_index().rename(columns={"index": "Value", "classifier_mechanism": "Value", "count": "Count"}),
                use_container_width=True, hide_index=True)
            return
        st.caption("No classifier dimension data available.")
        return

    rows = []
    for short, full in available.items():
        vals = df[full].dropna()
        n = len(vals)
        if n == 0:
            continue
        correct = int((vals == "CORRECT").sum())
        incorrect = int((vals == "INCORRECT").sum())
        rows.append({
            "Dimension": short,
            "Full Name": full,
            "CORRECT": correct,
            "INCORRECT": incorrect,
            "Correct%": f"{100 * correct / n:.1f}%",
            "N": n,
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.caption("No classifier dimension values found.")


# ── Section 7: Oracle Granularity ──

def _render_oracle_granularity(df: pd.DataFrame) -> None:
    st.markdown("##### Oracle Verdict Distribution")

    col = None
    if "oracle_reasoning_truth" in df.columns and df["oracle_reasoning_truth"].notna().any():
        col = "oracle_reasoning_truth"
    elif "oracle_label" in df.columns and df["oracle_label"].notna().any():
        col = "oracle_label"

    if col is None:
        st.caption("No oracle verdict data available.")
        return

    verdicts = df[col].dropna()
    n = len(verdicts)
    dist = verdicts.value_counts()

    rows = []
    for verdict in ["CORRECT", "PARTIAL", "WRONG", "UNJUDGABLE"]:
        count = int(dist.get(verdict, 0))
        rows.append({
            "Verdict": verdict,
            "Count": count,
            "Pct": f"{100 * count / n:.1f}%" if n else "—",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("PARTIAL is shown separately — NOT collapsed into WRONG or CORRECT.")


# ── Main render ──

def render_failure_taxonomy(df: pd.DataFrame) -> None:
    st.subheader("Failure Taxonomy")
    render_tab_docs("failure_taxonomy")

    if "outcome_class" not in df.columns:
        st.warning("outcome_class not available. Run with v4 evaluation pipeline.")
        return

    _render_summary_cards(df)
    st.markdown("---")
    _render_re_matrix(df)
    st.markdown("---")
    _render_leg_breakdown(df)
    st.markdown("---")
    _render_rt_matrix(df)
    st.markdown("---")
    _render_exec_failure_breakdown(df)
    st.markdown("---")
    _render_classifier_dims(df)
    st.markdown("---")
    _render_oracle_granularity(df)
