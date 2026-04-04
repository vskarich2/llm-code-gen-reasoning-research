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
    """Find oracle prompt/response from call artifacts."""
    prompt_path = row.get("prompt_path", "")
    if not prompt_path or not pd.notna(prompt_path):
        return "", ""
    # Oracle call is typically call_id 2 (between generation and classification)
    base_dir = Path(prompt_path).parent
    # Look for oracle_eval flat file
    oracle_files = sorted(base_dir.glob("*_oracle_eval.txt"))
    if oracle_files:
        text = oracle_files[0].read_text(encoding="utf-8")
        return split_prompt_response(text)
    return "", ""


def render_pipeline_trace(df: pd.DataFrame) -> None:
    st.subheader("Pipeline Trace")
    render_tab_docs("pipeline_trace")
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

    # Load artifacts
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

    oracle_prompt, oracle_response = _find_oracle_artifact(row)

    parsed_json = extract_primary_json_from_row(row)

    # ══════════════════════════════════════════════════════════
    # SECTION 1: PROMPTS AND RESPONSES (top)
    # ══════════════════════════════════════════════════════════
    st.markdown("##### Agent Interaction")

    _case = row.get("case_id", "?")
    _model = row.get("model", "?")
    _cond = row.get("condition", "?")
    _att = row.get("attempt_idx", 0)
    prompt_label = f"{_case} | {_model} | {_cond} | attempt {_att}"
    st.caption(prompt_label)
    if prompt_text:
        with st.expander("Generation Prompt", expanded=False):
            st.code(prompt_text[:20000], language="text")
    if response_text:
        with st.expander("Generation Response", expanded=False):
            st.code(response_text[:20000], language="text")
    if parsed_json:
        with st.expander("Parsed JSON (from agent)", expanded=False):
            st.json(parsed_json)

    cls_template = row.get("classifier_template", row.get("classifier_prompt_variant", ""))
    cls_mode = row.get("classifier_mode", "")
    cls_label = f"Classifier: {cls_template}" if cls_template else "Classifier"
    if cls_mode:
        cls_label += f" ({cls_mode})"
    st.markdown(f"##### {cls_label}")
    if cls_prompt:
        with st.expander("Classifier Prompt", expanded=False):
            st.code(cls_prompt[:20000], language="text")
    if cls_response:
        with st.expander("Classifier Response", expanded=False):
            st.code(cls_response[:20000], language="text")
    elif not cls_prompt:
        st.caption("Classifier artifacts not available.")

    st.markdown("##### Oracle Reasoning Evaluator")

    # Oracle verdict display
    oracle_truth = row.get("oracle_reasoning_truth")
    oracle_correct = row.get("oracle_correct")
    oracle_status = row.get("oracle_status")
    oracle_just = row.get("oracle_justification")

    if oracle_truth and pd.notna(oracle_truth):
        oracle_icon = "✅" if oracle_truth == "CORRECT" else ("🟡" if oracle_truth == "PARTIAL" else "❌")
        st.markdown(f"{oracle_icon} **Oracle verdict: {oracle_truth}** (correct={_to_native(oracle_correct)}, status={oracle_status})")
        if oracle_just and pd.notna(oracle_just):
            st.caption(str(oracle_just))
    else:
        st.caption("Oracle not available for this event.")

    if oracle_prompt:
        with st.expander("Oracle Prompt", expanded=False):
            st.code(oracle_prompt[:20000], language="text")
    if oracle_response:
        with st.expander("Oracle Response", expanded=False):
            st.code(oracle_response[:20000], language="text")

    # ══════════════════════════════════════════════════════════
    # SECTION 2: ORIGINAL CASE CODE
    # ══════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("##### Original Case Code")
    code_files = case_meta.get("code_files", [])
    if not code_files:
        st.caption("No original case file metadata available.")
    else:
        for file_path in code_files:
            # Try with case_data/ prefix first, then bare path
            path = Path("case_data") / file_path
            if not path.exists():
                path = Path(file_path)
            with st.expander(str(file_path), expanded=False):
                if path.exists():
                    st.code(path.read_text(encoding="utf-8"), language="python")
                else:
                    st.caption(f"File not found: tried case_data/{file_path} and {file_path}")

    # Generated code
    st.markdown("##### Generated Code")
    extracted_code = row.get("_extracted_code")
    if extracted_code and pd.notna(extracted_code) and str(extracted_code).strip():
        st.code(str(extracted_code), language="python")
    else:
        st.caption("No extracted code available for this event.")

    # ══════════════════════════════════════════════════════════
    # SECTION 3: PIPELINE STAGES (bottom)
    # ══════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("##### Pipeline Stage Details")

    stage_cols = st.columns(2)

    with stage_cols[0]:
        with st.container(border=True):
            parse_status = str(row.get("parse_status", "—"))
            parse_ok = not _safe_bool(row.get("parse_failure"))
            render_stage_status("Parse", "success" if parse_ok else "failure", parse_status)
            st.json(_clean_dict({
                "strict_parse_valid": row.get("strict_parse_valid"),
                "recovery_parse_valid": row.get("recovery_parse_valid"),
                "strict_structurally_valid": row.get("strict_structurally_valid"),
                "recovery_structurally_valid": row.get("recovery_structurally_valid"),
                "execution_eligible": row.get("execution_eligible"),
            }))

        with st.container(border=True):
            recon_status = str(row.get("reconstruction_status", row.get("recon_status", "—")))
            recon_ok = not _safe_bool(row.get("reconstruction_failure"))
            render_stage_status("Reconstruction", "success" if recon_ok else "failure", recon_status)
            st.json(_clean_dict({
                "reconstruction_mode": row.get("reconstruction_mode"),
                "files_changed": row.get("files_changed"),
                "files_missing": row.get("files_missing"),
                "files_extra": row.get("files_extra"),
                "syntax_errors": row.get("syntax_errors"),
                "structural_errors": row.get("structural_errors"),
                "recovery_types": row.get("recovery_types"),
            }))

    with stage_cols[1]:
        with st.container(border=True):
            exec_ok = _safe_bool(row.get("exec_pass"))
            exec_detail = str(row.get("exec_category", "—"))
            render_stage_status("Execution", "success" if exec_ok else "failure", exec_detail)
            st.json(_clean_dict({
                "exec_pass": row.get("exec_pass"),
                "score": row.get("score"),
                "exec_category": row.get("exec_category"),
                "exec_reasons": row.get("exec_reasons"),
            }))

        with st.container(border=True):
            ast_status = str(row.get("ast_status", "—"))
            ast_correct = row.get("ast_correct")
            ast_icon = "success" if _to_native(ast_correct) is True else ("failure" if _to_native(ast_correct) is False else "info")
            render_stage_status("AST", ast_icon, ast_status)
            st.json(_clean_dict({
                "ast_status": row.get("ast_status"),
                "ast_correct": row.get("ast_correct"),
                "ast_score": row.get("ast_score"),
            }))

        with st.container(border=True):
            outcome = classify_outcome_label(row)
            render_stage_status("Outcome", "info", outcome)

            # Oracle verdict from inline oracle
            oracle_val = row.get("oracle_reasoning_truth")
            disagree_type = row.get("reasoning_disagreement_type")

            st.json(_clean_dict({
                "outcome_class": row.get("outcome_class"),
                "exec_pass": row.get("exec_pass"),
                "oracle_verdict": oracle_val if pd.notna(oracle_val) else None,
                "oracle_correct": row.get("oracle_correct"),
                "classifier_mechanism": row.get("classifier_mechanism"),
                "ast_correct": row.get("ast_correct"),
                "disagreement": disagree_type if pd.notna(disagree_type) else None,
            }))
