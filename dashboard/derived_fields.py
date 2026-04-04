"""Derived field registry — computed columns added to the attempt DataFrame.

Each entry: column_name → function(df) → Series.
Functions operate on the full DataFrame. No side effects. No I/O.
Dependencies must reference only FIELD_REGISTRY columns or earlier derived fields.
"""

import pandas as pd


def _is_leg(df: pd.DataFrame) -> pd.Series:
    rc = df["reasoning_correct"].fillna(False).astype(bool)
    ep = df["exec_pass"].fillna(False).astype(bool)
    return rc & ~ep


def _is_lucky_fix(df: pd.DataFrame) -> pd.Series:
    rc = df["reasoning_correct"].fillna(False).astype(bool)
    ep = df["exec_pass"].fillna(False).astype(bool)
    return ~rc & ep


def _parse_success(df: pd.DataFrame) -> pd.Series:
    return df["parse_status"].fillna("").eq("success")


def _is_reconstructable(df: pd.DataFrame) -> pd.Series:
    return _parse_success(df)


def _recon_pass(df: pd.DataFrame) -> pd.Series:
    return df["exec_pass"].fillna(False) & df["is_reconstructable"]


def _is_retry(df: pd.DataFrame) -> pd.Series:
    return df["attempt_idx"] > 0


def _chain_id(df: pd.DataFrame) -> pd.Series:
    return (
        df["model"].astype(str) + "|"
        + df["condition"].astype(str) + "|"
        + df["case_id"].astype(str) + "|"
        + df["trial_idx"].astype(str)
    )


# Ordered dict — derived fields are applied in this order.
# Later fields may depend on earlier ones.
DERIVED_FIELDS = {
    "chain_id": _chain_id,
    "parse_success": _parse_success,
    "is_reconstructable": _is_reconstructable,
    "is_leg": _is_leg,
    "is_lucky_fix": _is_lucky_fix,
    "recon_pass": _recon_pass,
    "is_retry": _is_retry,
}


def apply_derived_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all derived fields to a DataFrame. Returns a new DataFrame."""
    df = df.copy()
    for name, fn in DERIVED_FIELDS.items():
        df[name] = fn(df)
    return df
