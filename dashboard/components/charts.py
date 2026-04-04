"""Static (non-zoomable) chart helpers.

Replaces st.bar_chart / st.line_chart which capture scroll events
and zoom instead of letting the page scroll.

Uses Altair without .interactive() — no scroll-zoom, no pan.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st


def static_bar_chart(
    data: pd.Series | pd.DataFrame,
    height: int = 300,
) -> None:
    """Render a non-zoomable bar chart with horizontal x labels."""
    if isinstance(data, pd.Series):
        df = data.reset_index()
        df.columns = ["category", "value"]
        chart = (
            alt.Chart(df)
            .mark_bar()
            .encode(
                x=alt.X(
                    "category:N",
                    sort=None,
                    axis=alt.Axis(labelAngle=0, labelLimit=0),
                ),
                y=alt.Y("value:Q"),
            )
            .properties(height=height)
        )
    else:
        df = data.reset_index()
        id_col = df.columns[0]
        value_cols = list(df.columns[1:])
        melted = df.melt(
            id_vars=id_col,
            value_vars=value_cols,
            var_name="series",
            value_name="value",
        )
        chart = (
            alt.Chart(melted)
            .mark_bar()
            .encode(
                x=alt.X(
                    f"{id_col}:N",
                    sort=None,
                    axis=alt.Axis(labelAngle=0, labelLimit=0),
                ),
                y=alt.Y("value:Q"),
                color=alt.Color("series:N"),
            )
            .properties(height=height)
        )
    st.altair_chart(chart, use_container_width=True)


def static_line_chart(
    data: pd.DataFrame,
    height: int = 300,
) -> None:
    """Render a non-zoomable line chart with horizontal x labels."""
    df = data.reset_index()
    id_col = df.columns[0]
    value_cols = list(df.columns[1:])
    melted = df.melt(
        id_vars=id_col,
        value_vars=value_cols,
        var_name="series",
        value_name="value",
    )
    chart = (
        alt.Chart(melted)
        .mark_line(point=True)
        .encode(
            x=alt.X(
                f"{id_col}:N",
                sort=None,
                axis=alt.Axis(labelAngle=0, labelLimit=0),
            ),
            y=alt.Y("value:Q"),
            color=alt.Color("series:N"),
        )
        .properties(height=height)
    )
    st.altair_chart(chart, use_container_width=True)
