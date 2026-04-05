"""Pipeline trace tab: stage-by-stage inspection of a single attempt."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.components.selectors import build_case_selection
from dashboard.data.loaders import load_cases
from dashboard.leg_scanner import read_artifact, split_prompt_response
from dashboard.tab_docs import render_tab_docs
from dashboard.views.case_explorer import _safe_bool, classify_outcome_label, extract_primary_json_from_row


def _to_native(val):
    """Convert numpy/pandas types to native Python for clean JSON display."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    if hasattr(val, 'item'):
        return val.item()
    return val


def _clean_dict(d: dict) -> dict:
    """Convert all values in a dict to native Python types."""
    return {k: _to_native(v) for k, v in d.items()}


def parse_classifier_response(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    if not lines:
        return parsed
    parts = [p.strip() for p in lines[0].split(";")]
    if len(parts) >= 5:
        parsed["mechanism_identified"] = parts[0]
        parsed["commitments_extracted"] = parts[1]
        parsed["commitments_satisfied"] = parts[2]
        parsed["reasoning_code_alignment"] = parts[3]
        parsed["failure_type"] = parts[4]
    if len(lines) > 1:
        parsed["confidence"] = lines[1]
    for line in lines[2:]:
        lower = line.lower()
        if lower.startswith("counterfactual:"):
            parsed["counterfactual"] = line.split(":", 1)[1].strip()
        elif lower.startswith("evidence:"):
            parsed["evidence"] = line.split(":", 1)[1].strip()
        elif lower.startswith("judgment:"):
            parsed["judgment"] = line.split(":", 1)[1].strip()
    return parsed


def render_stage_status(label: str, status: str, detail: str | None = None) -> None:
    icon = {
        "success": "✅",
        "warning": "🟡",
        "failure": "❌",
        "info": "ℹ️",
    }.get(status, "ℹ️")
    st.markdown(f"**{icon} {label}**")
    if detail:
        st.caption(detail)


def _find_oracle_artifact(row) -> tuple[str, str]:
    """Find oracle prompt/response from call artifacts for this attempt.

    Finds the oracle_eval file that immediately follows this attempt's
    generation file (by file number), handling interleaved retry layouts.
    """
    prompt_path = row.get("prompt_path", "")
    if not prompt_path or not pd.notna(prompt_path):
        return "", ""
    gen_file = Path(prompt_path)
    base_dir = gen_file.parent
    oracle_files = sorted(base_dir.glob("*_oracle_eval.txt"))
    if not oracle_files:
        return "", ""
    # Find the oracle file right after this generation file
    gen_num = gen_file.name.split("_")[0]
    for of in oracle_files:
        of_num = of.name.split("_")[0]
        if of_num > gen_num:
            text = of.read_text(encoding="utf-8")
            return split_prompt_response(text)
    return "", ""


def _render_retry_trajectory(chain: pd.DataFrame, current_row) -> None:
    """Render retry trajectory summary showing all attempts."""
    st.markdown("---")
    st.markdown("##### Retry Trajectory")

    n_attempts = int(current_row.get("n_attempts", 1))
    traj_type = current_row.get("trajectory_type", "")
    current_att = _to_native(current_row.get("attempt_idx", 0))

    st.caption(f"{n_attempts} attempts | type: {traj_type}")

    # Build summary table for all attempts
    attempts = chain.sort_values("attempt_idx")
    for _, att_row in attempts.iterrows():
        att_idx = _to_native(att_row.get("attempt_idx", 0))
        is_current = (att_idx == current_att)
        marker = " **(viewing)**" if is_current else ""

        exec_pass = _safe_bool(att_row.get("exec_pass"))
        exec_icon = "pass" if exec_pass else "fail"
        exec_cat = att_row.get("exec_category", "")

        oracle_truth = att_row.get("oracle_reasoning_truth", "")
        oracle_icon = ""
        if oracle_truth and pd.notna(oracle_truth):
            oracle_icon = {"CORRECT": "R=1", "PARTIAL": "R=~", "WRONG": "R=0"}.get(str(oracle_truth), "R=?")

        cls_ric = att_row.get("classifier_ric") or att_row.get("classifier_mechanism", "")
        cls_ccc = att_row.get("classifier_ccc") or att_row.get("classifier_commitments_satisfied", "")

        summary = f"E={'pass' if exec_pass else 'fail'}"
        if oracle_icon:
            summary += f" | {oracle_icon}"
        if cls_ric and pd.notna(cls_ric):
            summary += f" | RIC={cls_ric}"
        if cls_ccc and pd.notna(cls_ccc):
            summary += f" | CCC={cls_ccc}"
        if exec_cat and pd.notna(exec_cat):
            summary += f" | {exec_cat}"

        icon = "green" if exec_pass else "red"
        label = f"Attempt {att_idx}{marker}: {summary}"
        with st.expander(label, expanded=is_current):
            cols = st.columns(4)
            with cols[0]:
                st.metric("Execution", "PASS" if exec_pass else "FAIL")
            with cols[1]:
                ot = str(oracle_truth) if oracle_truth and pd.notna(oracle_truth) else "N/A"
                st.metric("Oracle", ot)
            with cols[2]:
                r = str(cls_ric) if cls_ric and pd.notna(cls_ric) else "N/A"
                st.metric("RIC", r)
            with cols[3]:
                c = str(cls_ccc) if cls_ccc and pd.notna(cls_ccc) else "N/A"
                st.metric("CCC", c)

            # Show critique if present
            critique = att_row.get("mismatch_critique")
            if critique and pd.notna(critique) and str(critique).strip():
                st.markdown("**Critique received before this attempt:**")
                st.info(str(critique))

            # Show disagreement
            dis_type = att_row.get("reasoning_disagreement_type")
            if dis_type and pd.notna(dis_type):
                st.caption(f"Disagreement: {dis_type}")


def render_pipeline_trace(df: pd.DataFrame) -> None:
    st.subheader("Pipeline Trace")
    render_tab_docs("pipeline_trace")
    chain = build_case_selection(df, "pipelinetrace")
    if chain.empty:
        st.info("No data for this selection.")
        return

    cases = load_cases()
    attempts = chain.sort_values("attempt_idx")
    first_row = attempts.iloc[0]
    case_meta = cases.get(str(first_row.get("case_id")), {})
    n_attempts = len(attempts)

    # ── Original case code (shared across attempts, show once) ──
    st.markdown("##### Original Case Code")
    code_files = case_meta.get("code_files", [])
    if not code_files:
        st.caption("No original case file metadata available.")
    else:
        for file_path in code_files:
            path = Path("case_data") / file_path
            if not path.exists():
                path = Path(file_path)
            with st.expander(str(file_path), expanded=False):
                if path.exists():
                    st.code(path.read_text(encoding="utf-8"), language="python")
                else:
                    st.caption(f"File not found.")

    # ── Render each attempt's prompts/responses ──
    attempt_rows = list(attempts.iterrows())
    for att_i, (_, row) in enumerate(attempt_rows):
        att_idx = _to_native(row.get("attempt_idx", att_i))
        exec_pass = _safe_bool(row.get("exec_pass"))
        icon = "✅" if exec_pass else "❌"
        st.markdown("---")
        st.markdown(f"### {icon} Attempt {att_idx}")
        prev_row = attempt_rows[att_i - 1][1] if att_i > 0 else None
        _render_single_attempt(row, case_meta, att_idx, n_attempts, prev_row)

    # ── Pipeline stage details (all attempts, at bottom) ──
    st.markdown("---")
    for att_i, (_, row) in enumerate(attempts.iterrows()):
        att_idx = _to_native(row.get("attempt_idx", att_i))
        label = f"Pipeline Stage Details — Attempt {att_idx}" if n_attempts > 1 else "Pipeline Stage Details"
        with st.expander(label, expanded=False):
            _render_stage_details(row)


def _render_single_attempt(row, case_meta, att_idx, n_attempts, prev_row=None) -> None:
    """Render one attempt's full pipeline trace."""
    # Critique from previous attempt (shows first, before agent prompt)
    if prev_row is not None:
        crit_path = prev_row.get("critique_path")
        if crit_path and pd.notna(crit_path):
            crit_text = read_artifact(crit_path)
            if crit_text:
                crit_prompt, crit_response = split_prompt_response(crit_text)
                st.markdown("**Critique** (from previous attempt)")
                if crit_prompt:
                    with st.expander("Critique Prompt", expanded=False):
                        st.code(crit_prompt[:20000], language="text")
                if crit_response:
                    with st.expander("Critique Response", expanded=True):
                        st.code(crit_response[:5000], language="text")

    # Load artifacts
    prompt_path = row.get("prompt_path")
    prompt_text, response_text = "", ""
    if prompt_path and pd.notna(prompt_path):
        artifact_text = read_artifact(prompt_path)
        if artifact_text:
            prompt_text, response_text = split_prompt_response(artifact_text)

    cls_prompt, cls_response = "", ""
    cls_parsed: dict[str, str] = {}
    cls_path = row.get("classify_path")
    if cls_path and pd.notna(cls_path):
        cls_text = read_artifact(cls_path)
        if cls_text:
            cls_prompt, cls_response = split_prompt_response(cls_text)
            cls_parsed = parse_classifier_response(cls_response or cls_text)

    oracle_prompt, oracle_response = _find_oracle_artifact(row)
    parsed_json = extract_primary_json_from_row(row)

    # ── Agent ──
    if prompt_text or response_text or parsed_json:
        st.markdown("**Agent**")
        if prompt_text:
            with st.expander("Prompt", expanded=False):
                st.code(prompt_text[:20000], language="text")
        if response_text:
            with st.expander("Response", expanded=False):
                st.code(response_text[:20000], language="text")
        if parsed_json:
            with st.expander("Parsed JSON", expanded=False):
                st.json(parsed_json)
        extracted_code = row.get("_extracted_code")
        if extracted_code and pd.notna(extracted_code) and str(extracted_code).strip():
            with st.expander("Generated Code", expanded=False):
                st.code(str(extracted_code), language="python")

    # ── Classifier ──
    if cls_prompt or cls_response:
        st.markdown("**Classifier**")
        if cls_prompt:
            with st.expander("Prompt", expanded=False):
                st.code(cls_prompt[:20000], language="text")
        if cls_response:
            with st.expander("Response", expanded=False):
                st.code(cls_response[:20000], language="text")

    # ── Oracle ──
    oracle_truth = row.get("oracle_reasoning_truth")
    has_oracle = oracle_prompt or oracle_response or (oracle_truth and pd.notna(oracle_truth))
    if has_oracle:
        st.markdown("**Oracle**")
        if oracle_prompt:
            with st.expander("Prompt", expanded=False):
                st.code(oracle_prompt[:20000], language="text")
        if oracle_response:
            with st.expander("Response", expanded=False):
                st.code(oracle_response[:20000], language="text")
        if oracle_truth and pd.notna(oracle_truth):
            o_icon = "✅" if oracle_truth == "CORRECT" else ("🟡" if oracle_truth == "PARTIAL" else "❌")
            oracle_just = row.get("oracle_justification")
            st.markdown(f"{o_icon} **Verdict: {oracle_truth}**")
            if oracle_just and pd.notna(oracle_just):
                st.caption(str(oracle_just))


def _render_stage_details(row) -> None:
    """Render parse/recon/execution/outcome stage cards for one attempt."""
    stage_cols = st.columns(2)

    with stage_cols[0]:
        with st.container(border=True):
            parse_ok = not _safe_bool(row.get("parse_failure"))
            render_stage_status("Parse", "success" if parse_ok else "failure",
                                str(row.get("parse_status", "—")))
            st.json(_clean_dict({
                "execution_eligible": row.get("execution_eligible"),
                "strict_parse_valid": row.get("strict_parse_valid"),
                "recovery_parse_valid": row.get("recovery_parse_valid"),
            }))

        with st.container(border=True):
            recon_ok = not _safe_bool(row.get("reconstruction_failure"))
            render_stage_status("Reconstruction", "success" if recon_ok else "failure",
                                str(row.get("recon_status", row.get("reconstruction_status", "—"))))
            st.json(_clean_dict({
                "files_changed": row.get("files_changed"),
                "files_missing": row.get("files_missing"),
                "syntax_errors": row.get("syntax_errors"),
                "recovery_types": row.get("recovery_types"),
            }))

    with stage_cols[1]:
        with st.container(border=True):
            exec_ok = _safe_bool(row.get("exec_pass"))
            render_stage_status("Execution", "success" if exec_ok else "failure",
                                str(row.get("exec_category", "—")))
            st.json(_clean_dict({
                "exec_pass": row.get("exec_pass"),
                "score": row.get("score"),
                "exec_reasons": row.get("exec_reasons"),
            }))

        with st.container(border=True):
            outcome = classify_outcome_label(row)
            render_stage_status("Outcome", "info", outcome)
            oracle_val = row.get("oracle_reasoning_truth")
            st.json(_clean_dict({
                "outcome_class": row.get("outcome_class"),
                "oracle_verdict": oracle_val if pd.notna(oracle_val) else None,
                "oracle_correct": row.get("oracle_correct"),
                "ast_status": row.get("ast_status"),
            }))
