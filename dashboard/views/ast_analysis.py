"""AST + Structural Reasoning Page.

Displays AST structural verification signals and their relationship
to the 5-class outcome taxonomy.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.styling import style_dataframe


def render_ast_analysis(df: pd.DataFrame) -> None:
    st.subheader("AST + Structural Reasoning Analysis")

    if "ast_status" not in df.columns:
        st.warning("AST fields not available. No AST evaluation data in the loaded experiments.")
        return

    # ── 3.1 AST STATUS DISTRIBUTION ──
    st.markdown("##### AST Status Distribution")

    ast_dist = df["ast_status"].value_counts()
    col1, col2 = st.columns([2, 1])
    with col1:
        st.bar_chart(ast_dist, use_container_width=True)
    with col2:
        n = len(df)
        for status in ["correct", "incorrect", "unknown", "not_available", "not_measurable"]:
            count = (df["ast_status"] == status).sum()
            if count > 0:
                st.metric(status, f"{count:,} ({count/n:.1%})")

    # ── 3.2 AST VS OUTCOME CLASS ──
    st.markdown("---")
    st.markdown("##### AST Status × Outcome Class")

    if "outcome_class" in df.columns:
        cross = pd.crosstab(
            df["outcome_class"],
            df["ast_status"],
            margins=True,
        )
        st.dataframe(
            cross.style.background_gradient(cmap="Blues"),
            use_container_width=True,
        )

        # Normalized version
        cross_pct = pd.crosstab(
            df["outcome_class"],
            df["ast_status"],
            normalize="index",
        )
        st.markdown("*Row-normalized (proportion within each outcome class):*")
        st.dataframe(
            cross_pct.style.format("{:.1%}").background_gradient(cmap="Blues"),
            use_container_width=True,
        )

    # ── 3.3 STRUCTURAL CONSISTENCY METRICS ──
    st.markdown("---")
    st.markdown("##### Structural Consistency by Outcome Class")

    if "outcome_class" in df.columns and "ast_status" in df.columns:
        assessable = df[df["ast_status"].isin(["correct", "incorrect"])]
        if len(assessable) > 0:
            by_outcome = (
                assessable.groupby("outcome_class")
                .agg(
                    n=("ast_status", "size"),
                    ast_correct_rate=("ast_status", lambda x: (x == "correct").mean()),
                )
                .reset_index()
                .sort_values("ast_correct_rate", ascending=False)
            )
            st.dataframe(
                style_dataframe(by_outcome, metric_columns=["n", "ast_correct_rate"]),
                use_container_width=True,
                hide_index=True,
            )

    # ── 3.4 AST VS LEG ──
    st.markdown("---")
    st.markdown("##### AST in LEG vs Non-LEG Events")

    if "LEG" in df.columns:
        assessable = df[df["ast_status"].isin(["correct", "incorrect"])]
        if len(assessable) > 0:
            leg_ast = assessable.groupby("LEG").agg(
                n=("ast_status", "size"),
                ast_correct_rate=("ast_status", lambda x: (x == "correct").mean()),
            ).reset_index()
            leg_ast["LEG"] = leg_ast["LEG"].map({True: "LEG events", False: "Non-LEG events"})

            col_l1, col_l2 = st.columns(2)
            with col_l1:
                st.dataframe(
                    style_dataframe(leg_ast, metric_columns=["n", "ast_correct_rate"]),
                    use_container_width=True,
                    hide_index=True,
                )
            with col_l2:
                leg_only = assessable[assessable["LEG"]]
                if len(leg_only) > 0:
                    st.metric(
                        "AST Correct Rate in LEG",
                        f"{(leg_only['ast_status'] == 'correct').mean():.1%}",
                    )
                    st.caption(
                        "High AST-correct rate in LEG events indicates "
                        "the gap is execution fidelity, not structural."
                    )

    # ── AST BY MODEL ──
    st.markdown("---")
    st.markdown("##### AST Correct Rate by Model")

    if "model" in df.columns:
        assessable = df[df["ast_status"].isin(["correct", "incorrect"])]
        if len(assessable) > 0:
            by_model = (
                assessable.groupby("model")
                .agg(
                    n=("ast_status", "size"),
                    ast_correct_rate=("ast_status", lambda x: (x == "correct").mean()),
                    exec_pass_rate=("exec_pass", lambda x: x.fillna(False).mean()),
                )
                .reset_index()
                .sort_values("ast_correct_rate", ascending=False)
            )
            st.dataframe(
                style_dataframe(by_model, metric_columns=["n", "ast_correct_rate", "exec_pass_rate"]),
                use_container_width=True,
                hide_index=True,
            )

    # ── AST BY FAMILY ──
    st.markdown("---")
    st.markdown("##### AST Correct Rate by Family")

    if "family" in df.columns:
        assessable = df[df["ast_status"].isin(["correct", "incorrect"])]
        if len(assessable) > 0:
            by_family = (
                assessable.groupby("family")
                .agg(
                    n=("ast_status", "size"),
                    ast_correct_rate=("ast_status", lambda x: (x == "correct").mean()),
                    exec_pass_rate=("exec_pass", lambda x: x.fillna(False).mean()),
                    exec_gap=("ast_status", lambda x: (
                        ((x == "correct") & ~assessable.loc[x.index, "exec_pass"].fillna(False)).mean()
                    )),
                )
                .reset_index()
                .sort_values("exec_gap", ascending=False)
            )
            st.dataframe(
                style_dataframe(by_family, metric_columns=["n", "ast_correct_rate", "exec_pass_rate", "exec_gap"]),
                use_container_width=True,
                hide_index=True,
                height=min(38 * len(by_family) + 38, 800),
            )

    # ── 3.5 AST EXAMPLES ──
    st.markdown("---")
    st.markdown("##### AST Example Events")

    ast_filter = st.selectbox(
        "Filter by AST status",
        ["correct", "incorrect", "unknown", "not_available", "all"],
        key="ast_example_filter",
    )

    if ast_filter == "all":
        filtered = df
    else:
        filtered = df[df["ast_status"] == ast_filter]

    outcome_filter = st.selectbox(
        "Filter by outcome class",
        ["all", "LEG", "reasoning_failure", "interpretable_success", "unsupported_success", "serialization_failure"],
        key="ast_example_outcome",
    )
    if outcome_filter != "all" and "outcome_class" in filtered.columns:
        filtered = filtered[filtered["outcome_class"] == outcome_filter]

    n_examples = min(10, len(filtered))
    if n_examples > 0:
        sample = filtered.sample(n_examples, random_state=42)
        display_cols = [
            c for c in [
                "case_id", "model", "condition", "ast_status",
                "outcome_class", "exec_pass", "mechanism_dim",
                "exec_category",
            ]
            if c in sample.columns
        ]
        st.dataframe(sample[display_cols], use_container_width=True, hide_index=True)

        for idx, row in sample.iterrows():
            with st.expander(f"{row.get('case_id', '?')} | {row.get('model', '?')}"):
                code = row.get("_extracted_code")
                if code and pd.notna(code) and str(code).strip():
                    st.code(str(code)[:3000], language="python")
                else:
                    st.caption("No extracted code.")
                reasons = row.get("exec_reasons")
                if reasons and pd.notna(reasons):
                    st.markdown(f"**Failure reasons:** {reasons}")
    else:
        st.info("No events matching the selected filters.")
