"""Derived columns and data transformations. No Streamlit imports."""

from __future__ import annotations

import pandas as pd


def add_failure_stage_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    if "parse_failure" not in out.columns:
        out["parse_failure"] = (
            ~out.get("execution_eligible", pd.Series(False, index=out.index)).fillna(False)
            & out.get("parse_status", pd.Series("", index=out.index)).fillna("").astype(str).str.contains(
                "parse", case=False, na=False
            )
        )

    if "reconstruction_failure" not in out.columns:
        recon_status = out.get("reconstruction_status", pd.Series("", index=out.index)).fillna("").astype(str)
        recon_status_v2 = out.get("recon_status", pd.Series("", index=out.index)).fillna("").astype(str)
        out["reconstruction_failure"] = (
            recon_status.str.contains("fail|invalid|error", case=False, na=False)
            | recon_status_v2.str.contains("fail|invalid|error", case=False, na=False)
        )

    if "execution_failure" not in out.columns:
        exec_pass = out.get("exec_pass", pd.Series(False, index=out.index)).fillna(False)
        out["execution_failure"] = ~exec_pass

    if "reasoning_failure" not in out.columns:
        mech = out.get("mechanism_dim", pd.Series("", index=out.index)).fillna("").astype(str)
        out["reasoning_failure"] = ~mech.eq("CORRECT")

    if "stage_terminal" not in out.columns:
        stage = pd.Series("success", index=out.index, dtype="object")
        stage = stage.mask(out["parse_failure"], "parse_failure")
        stage = stage.mask(~out["parse_failure"] & out["reconstruction_failure"], "reconstruction_failure")
        stage = stage.mask(
            ~out["parse_failure"] & ~out["reconstruction_failure"] & out["execution_failure"],
            "execution_failure",
        )
        out["stage_terminal"] = stage

    return out
