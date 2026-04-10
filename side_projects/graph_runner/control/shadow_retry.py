"""Shadow mode for retry: run both legacy retry_v2 and transitional retry controller.

The transitional controller preserves retry_v2 semantics by delegating
per-attempt stages to V2 stage functions. This shadow mode validates
the controller layer, not full graph-native retry.

Returns the legacy result authoritatively.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("t3.shadow_retry")


def run_shadow_retry(
    case: dict,
    model: str,
    condition: str,
    logger: Any,
    case_start_eid: int = 0,
) -> tuple[str, str, dict]:
    """Run both retry backends, compare trajectories, return legacy."""
    from core.pipeline.orchestration.retry_v2 import run_retry_v2

    # Legacy (canonical)
    cid, cond, legacy_ev = run_retry_v2(
        case, model, condition, logger, case_start_eid,
    )

    # Graph (shadow)
    graph_ev = None
    graph_error = None
    try:
        from unittest.mock import MagicMock
        from side_projects.graph_runner.control.retry_controller import (
            run_retry_graph,
        )
        shadow_logger = MagicMock()
        _, _, graph_ev = run_retry_graph(
            case, model, condition, shadow_logger, case_start_eid,
        )
    except Exception as exc:
        graph_error = f"{type(exc).__name__}: {exc}"
        log.warning(
            "shadow retry_graph failed for %s: %s", cid, graph_error,
        )

    if graph_ev is not None:
        diffs = compare_retry_results(cid, legacy_ev, graph_ev)
        if diffs:
            log.warning(
                "SHADOW RETRY MISMATCH %s: %d diffs", cid, len(diffs),
            )
            for d in diffs[:10]:
                log.info(
                    "  attempt=%s field=%s legacy=%s graph=%s",
                    d.get("attempt_index", "final"),
                    d["field"],
                    _trunc(d["legacy"]),
                    _trunc(d["graph"]),
                )
        else:
            log.info("SHADOW RETRY MATCH %s", cid)
    elif graph_error:
        log.warning("SHADOW RETRY ERROR %s: %s", cid, graph_error)

    return cid, cond, legacy_ev


def compare_retry_results(
    cid: str, legacy: dict, graph: dict,
) -> list[dict]:
    """Compare retry results field by field. Returns list of diffs."""
    diffs: list[dict] = []

    # Top-level fields
    for field_name in ("pass", "score", "num_attempts",
                       "best_attempt_idx", "retry_passed_at"):
        lv = legacy.get(field_name)
        gv = graph.get(field_name)
        if lv != gv:
            diffs.append({
                "field": f"top.{field_name}",
                "legacy": lv,
                "graph": gv,
            })

    # Evaluation
    l_eval = legacy.get("evaluation", {})
    g_eval = graph.get("evaluation", {})
    for field_name in ("outcome_class", "LEG", "LEG_subtype",
                       "execution_pass", "reasoning_correct",
                       "translation_consistent"):
        lv = l_eval.get(field_name)
        gv = g_eval.get(field_name)
        if lv != gv:
            diffs.append({
                "field": f"evaluation.{field_name}",
                "legacy": lv,
                "graph": gv,
            })

    # Trajectory length
    l_traj = legacy.get("trajectory", [])
    g_traj = graph.get("trajectory", [])
    if len(l_traj) != len(g_traj):
        diffs.append({
            "field": "trajectory.length",
            "legacy": len(l_traj),
            "graph": len(g_traj),
        })

    # Per-attempt comparison
    for k in range(min(len(l_traj), len(g_traj))):
        le = l_traj[k]
        ge = g_traj[k]
        for field_name in ("parse_valid", "code_length"):
            lv = le.get(field_name)
            gv = ge.get(field_name)
            if lv != gv:
                diffs.append({
                    "attempt_index": k,
                    "field": field_name,
                    "legacy": lv,
                    "graph": gv,
                })

        l_exec = le.get("execution", {})
        g_exec = ge.get("execution", {})
        for field_name in ("pass", "score", "execution_category"):
            lv = l_exec.get(field_name)
            gv = g_exec.get(field_name)
            if lv != gv:
                diffs.append({
                    "attempt_index": k,
                    "field": f"execution.{field_name}",
                    "legacy": lv,
                    "graph": gv,
                })

    # Reconstruction
    l_recon = legacy.get("reconstruction", {})
    g_recon = graph.get("reconstruction", {})
    for field_name in ("recon_status", "artifact_id", "parse_mode",
                       "strict_parse_valid", "recovery_parse_valid"):
        lv = l_recon.get(field_name)
        gv = g_recon.get(field_name)
        if lv != gv:
            diffs.append({
                "field": f"reconstruction.{field_name}",
                "legacy": lv,
                "graph": gv,
            })

    # Spec oracle
    l_spec = legacy.get("spec_oracle")
    g_spec = graph.get("spec_oracle")
    if (l_spec is None) != (g_spec is None):
        diffs.append({
            "field": "spec_oracle.presence",
            "legacy": l_spec is not None,
            "graph": g_spec is not None,
        })
    elif l_spec and g_spec:
        l_depth = l_spec.get("llm_depth", {}).get("depth")
        g_depth = g_spec.get("llm_depth", {}).get("depth")
        if l_depth != g_depth:
            diffs.append({
                "field": "spec_oracle.depth",
                "legacy": l_depth,
                "graph": g_depth,
            })

    return diffs


def _trunc(val: Any, maxlen: int = 80) -> str:
    s = repr(val)
    return s if len(s) <= maxlen else s[:maxlen] + "..."
