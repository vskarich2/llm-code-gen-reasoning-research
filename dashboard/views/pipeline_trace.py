"""Pipeline trace tab: stage-by-stage inspection of a single attempt."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.components.selectors import build_case_selection
from dashboard.data.loaders import load_cases
from dashboard.leg_scanner import read_artifact, split_prompt_response
from dashboard.views.case_explorer import _safe_bool, classify_outcome_label, extract_primary_json_from_row


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


def render_pipeline_trace(df: pd.DataFrame) -> None:
    st.subheader("Pipeline Trace")
    chain = build_case_selection(df, "pipelinetrace")
    if chain.empty:
        st.info("No data for this selection.")
        return

    attempt_options = chain["attempt_idx"].tolist()
    if len(attempt_options) > 1:
        attempt = st.select_slider(
            "Attempt",
            options=attempt_options,
            value=attempt_options[-1],
            key="pipelinetrace_attempt",
        )
    else:
        attempt = attempt_options[0]
    row = chain[chain["attempt_idx"] == attempt].iloc[0]
    cases = load_cases()
    case_meta = cases.get(str(row.get("case_id")), {})

    prompt_path = row.get("prompt_path")
    prompt_text = ""
    response_text = ""
    if prompt_path and pd.notna(prompt_path):
        artifact_text = read_artifact(prompt_path)
        if artifact_text:
            prompt_text, response_text = split_prompt_response(artifact_text)

    cls_prompt = ""
    cls_response = ""
    cls_parsed: dict[str, str] = {}
    cls_path = row.get("classify_path")
    if cls_path and pd.notna(cls_path):
        cls_text = read_artifact(cls_path)
        if cls_text:
            cls_prompt, cls_response = split_prompt_response(cls_text)
            cls_parsed = parse_classifier_response(cls_response or cls_text)

    parsed_json = extract_primary_json_from_row(row)

    stage_cols = st.columns(2)

    with stage_cols[0]:
        with st.container(border=True):
            render_stage_status(
                "Prompt",
                "success" if prompt_text else "warning",
                f"{prompt_text.count(chr(10)) + 1:,} lines" if prompt_text else "Prompt artifact missing",
            )
            if prompt_text:
                with st.expander("View Prompt", expanded=False):
                    st.code(prompt_text[:20000], language="text")

        with st.container(border=True):
            parse_status = str(row.get("parse_status", "—"))
            parse_ok = not _safe_bool(row.get("parse_failure"))
            render_stage_status("Parse", "success" if parse_ok else "failure", parse_status)
            parse_fields = {
                "strict_parse_valid": row.get("strict_parse_valid"),
                "recovery_parse_valid": row.get("recovery_parse_valid"),
                "strict_structurally_valid": row.get("strict_structurally_valid"),
                "recovery_structurally_valid": row.get("recovery_structurally_valid"),
                "execution_eligible": row.get("execution_eligible"),
            }
            st.json(parse_fields)
            if parsed_json:
                with st.expander("Parsed JSON", expanded=False):
                    st.json(parsed_json)

        with st.container(border=True):
            recon_status = str(row.get("reconstruction_status", row.get("recon_status", "—")))
            recon_ok = not _safe_bool(row.get("reconstruction_failure"))
            render_stage_status("Reconstruction", "success" if recon_ok else "failure", recon_status)
            recon_fields = {
                "reconstruction_mode": row.get("reconstruction_mode"),
                "files_changed": row.get("files_changed"),
                "files_missing": row.get("files_missing"),
                "files_extra": row.get("files_extra"),
                "syntax_errors": row.get("syntax_errors"),
                "structural_errors": row.get("structural_errors"),
                "recovery_types": row.get("recovery_types"),
            }
            st.json(recon_fields)

    with stage_cols[1]:
        with st.container(border=True):
            render_stage_status(
                "Raw Response",
                "success" if response_text else "warning",
                f"{response_text.count(chr(10)) + 1:,} lines" if response_text else "Response artifact missing",
            )
            if response_text:
                with st.expander("View Response", expanded=False):
                    st.code(response_text[:20000], language="text")

        with st.container(border=True):
            exec_ok = _safe_bool(row.get("exec_pass"))
            exec_detail = str(row.get("exec_category", "—"))
            render_stage_status("Execution", "success" if exec_ok else "failure", exec_detail)
            exec_fields = {
                "exec_pass": row.get("exec_pass"),
                "exec_category": row.get("exec_category"),
                "exec_reasons": row.get("exec_reasons"),
                "execution_trace": row.get("execution_trace"),
                "functions_detected": row.get("functions_detected"),
                "functions_called": row.get("functions_called"),
                "merge_conflicts": row.get("merge_conflicts"),
            }
            st.json(exec_fields)

        with st.container(border=True):
            mech = str(row.get("mechanism_dim", "—"))
            render_stage_status(
                "Classification",
                "success" if mech == "CORRECT" else "warning",
                mech,
            )
            if cls_prompt:
                with st.expander("Classifier Prompt", expanded=False):
                    st.code(cls_prompt[:20000], language="text")
            if cls_response:
                with st.expander("Classifier Response", expanded=False):
                    st.code(cls_response[:20000], language="text")
            if cls_parsed:
                st.json(cls_parsed)

        with st.container(border=True):
            outcome = classify_outcome_label(row)
            render_stage_status("Metrics", "info", outcome)
            metric_fields = {
                "exec_pass": row.get("exec_pass"),
                "is_leg": row.get("is_leg"),
                "is_lucky_fix": row.get("is_lucky_fix"),
                "reasoning_rate_proxy": row.get("reasoning_rate"),
                "oracle_verdict": row.get("oracle_verdict"),
            }
            st.json(metric_fields)

    st.markdown("---")
    st.markdown("##### Original Case Code")
    code_files = case_meta.get("code_files", [])
    if not code_files:
        st.caption("No original case file metadata available.")
    else:
        for file_path in code_files:
            path = Path(file_path)
            with st.expander(str(file_path), expanded=False):
                if path.exists():
                    st.code(path.read_text(encoding="utf-8"), language="python")
                else:
                    st.caption("File not found on disk.")

    extracted_code = row.get("_extracted_code")
    st.markdown("##### Generated Code")
    if extracted_code and pd.notna(extracted_code) and str(extracted_code).strip():
        st.code(str(extracted_code), language="python")
    else:
        st.caption("No extracted code available.")
