"""Shadow mode for single-attempt: run both legacy_v2 and graph_v1, compare results.

Returns the legacy result authoritatively. Graph result is non-blocking validation.
Any graph failure does NOT affect the pipeline.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("t3.shadow_compare")


def run_shadow(
    case: dict,
    model: str,
    condition: str,
    logger: Any,
    case_start_eid: int | str = 0,
) -> tuple[str, str, dict]:
    """Run both backends, compare, return legacy result.

    The graph result is NEVER returned to the caller.
    Any graph failure does NOT affect the pipeline.
    """
    from core.pipeline.orchestration.execution_v2 import run_v2

    # Run legacy (canonical, authoritative)
    cid, cond, legacy_ev = run_v2(
        case, model, condition, logger, case_start_eid,
    )

    # Run graph (shadow, non-authoritative)
    graph_ev = None
    graph_error = None
    try:
        from side_projects.graph_runner.control.run_single_attempt import (
            run_graph_v1,
        )
        from unittest.mock import MagicMock
        shadow_logger = MagicMock()
        _, _, graph_ev = run_graph_v1(
            case, model, condition, shadow_logger, case_start_eid,
        )
    except Exception as exc:
        graph_error = f"{type(exc).__name__}: {exc}"
        log.warning("shadow graph_v1 failed for %s: %s", cid, graph_error)

    # Compare
    if graph_ev is not None:
        report = compare_events(cid, legacy_ev, graph_ev)
        if report["mismatches"]:
            log.warning(
                "SHADOW MISMATCH %s: %d fields differ: %s",
                cid, len(report["mismatches"]),
                sorted(report["mismatches"].keys()),
            )
            for field_name, detail in report["mismatches"].items():
                log.info(
                    "  %s: legacy=%s graph=%s",
                    field_name,
                    _trunc(detail["legacy"]),
                    _trunc(detail["graph"]),
                )
        else:
            log.info("SHADOW MATCH %s: all fields identical", cid)
    elif graph_error:
        log.warning("SHADOW ERROR %s: %s", cid, graph_error)

    # Always return the legacy result
    return cid, cond, legacy_ev


# ============================================================
# COMPARISON
# ============================================================

COMPARE_TOP_KEYS = [
    "pass",
    "score",
    "case_id",
    "condition",
    "model",
]

COMPARE_EVALUATION_KEYS = [
    "execution_pass",
    "reconstruction_success",
    "routing_valid",
    "outcome_class",
    "LEG",
    "LEG_subtype",
    "oracle_correct",
    "reasoning_correct",
    "classifier_ran",
    "translation_consistent",
]

COMPARE_RECON_KEYS = [
    "recon_status",
    "parsing_mode",
    "strict_parse_valid",
    "recovery_parse_valid",
    "artifact_id",
]

COMPARE_SPEC_ORACLE_KEYS = [
    "status",
]


def compare_events(
    cid: str, legacy: dict, graph: dict,
) -> dict:
    """Compare two event dicts field by field. Returns report."""
    mismatches: dict[str, dict] = {}

    # Top-level fields
    for key in COMPARE_TOP_KEYS:
        lv = legacy.get(key)
        gv = graph.get(key)
        if lv != gv:
            mismatches[f"top.{key}"] = {"legacy": lv, "graph": gv}

    # Evaluation section
    l_eval = legacy.get("evaluation", {})
    g_eval = graph.get("evaluation", {})
    for key in COMPARE_EVALUATION_KEYS:
        lv = l_eval.get(key)
        gv = g_eval.get(key)
        if lv != gv:
            mismatches[f"evaluation.{key}"] = {
                "legacy": lv, "graph": gv,
            }

    # Reconstruction section
    l_recon = legacy.get("reconstruction", {})
    g_recon = graph.get("reconstruction", {})
    for key in COMPARE_RECON_KEYS:
        lv = l_recon.get(key)
        gv = g_recon.get(key)
        if lv != gv:
            mismatches[f"reconstruction.{key}"] = {
                "legacy": lv, "graph": gv,
            }

    # Spec oracle
    l_spec = legacy.get("spec_oracle")
    g_spec = graph.get("spec_oracle")
    if l_spec is not None and g_spec is not None:
        for key in COMPARE_SPEC_ORACLE_KEYS:
            lv = l_spec.get(key)
            gv = g_spec.get(key)
            if lv != gv:
                mismatches[f"spec_oracle.{key}"] = {
                    "legacy": lv, "graph": gv,
                }
        # Depth comparison
        l_depth = l_spec.get("llm_depth", {}).get("depth")
        g_depth = g_spec.get("llm_depth", {}).get("depth")
        if l_depth != g_depth:
            mismatches["spec_oracle.depth"] = {
                "legacy": l_depth, "graph": g_depth,
            }
    elif (l_spec is None) != (g_spec is None):
        mismatches["spec_oracle.presence"] = {
            "legacy": l_spec is not None,
            "graph": g_spec is not None,
        }

    return {
        "case_id": cid,
        "match": len(mismatches) == 0,
        "mismatches": mismatches,
        "fields_compared": (
            len(COMPARE_TOP_KEYS)
            + len(COMPARE_EVALUATION_KEYS)
            + len(COMPARE_RECON_KEYS)
        ),
    }


def _trunc(val: Any, maxlen: int = 80) -> str:
    s = repr(val)
    return s if len(s) <= maxlen else s[:maxlen] + "..."
