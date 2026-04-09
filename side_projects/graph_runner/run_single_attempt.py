"""Graph-backed single-attempt execution.

Drop-in replacement for execution_v2.run_v2() for single-attempt conditions.
Produces the exact same (case_id, condition, ev) tuple and event schema.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from unittest.mock import MagicMock

from side_projects.graph_runner.constants import (
    KEY_CASE,
    KEY_CONDITION,
    KEY_CONFIG,
    KEY_MODEL,
    KEY_RETRY_CONTEXT,
)
from side_projects.graph_runner.dag import build_pipeline_graph, SEED_KEYS
from side_projects.graph_runner.engine.scheduler import run_graph
from side_projects.graph_runner.engine.types import ExecutionContext

log = logging.getLogger("t3.graph_single_attempt")

# Single-attempt conditions eligible for graph backend
GRAPH_ELIGIBLE_CONDITIONS = frozenset({
    "baseline_v2",
    "leg_reduction_v2",
    "leg_reduction_lean_v2",
    "baseline_v3",
    "leg_reduction_lean_v3",
})


def run_graph_v1(
    case: dict,
    model: str,
    condition: str,
    logger: Any,
    case_start_eid: int | str = 0,
) -> tuple[str, str, dict]:
    """Run single-attempt pipeline via graph engine.

    Returns (case_id, condition, ev) — same signature as run_v2().
    The ev dict matches the case.end event payload schema exactly.
    """
    from core.config.experiment_config import get_config

    config = get_config()
    cid = case["id"]

    if condition not in GRAPH_ELIGIBLE_CONDITIONS:
        raise ValueError(
            f"run_graph_v1 called with non-eligible condition: "
            f"{condition!r}. Only single-attempt conditions are "
            f"supported: {sorted(GRAPH_ELIGIBLE_CONDITIONS)}"
        )

    graph = build_pipeline_graph(config)

    seed = {
        KEY_CASE: case,
        KEY_CONDITION: condition,
        KEY_MODEL: model,
        KEY_CONFIG: config,
        KEY_RETRY_CONTEXT: None,
    }

    context = ExecutionContext(
        run_id=str(case_start_eid),
        case_id=cid,
        model=model,
        condition=condition,
        config=config,
        logger=logger,
    )

    t0 = time.monotonic()
    summary = run_graph(graph, seed=seed, context=context)
    elapsed = time.monotonic() - t0

    if summary.failed_nodes:
        log.error(
            "graph_v1 %s: %d nodes failed: %s",
            cid, len(summary.failed_nodes), summary.failed_nodes,
        )

    vals = summary.final_state.values
    ev = vals.get("final_result", {})

    if not ev:
        log.error("graph_v1 %s: final_result is empty", cid)
        ev = {
            "case_id": cid,
            "condition": condition,
            "model": model,
            "pass": False,
            "score": 0.0,
            "graph_engine_failure": True,
            "failed_nodes": list(summary.failed_nodes),
            "skipped_nodes": list(summary.skipped_nodes),
        }

    # Log via the existing logger if available
    if logger is not None:
        try:
            parsed_gen = vals.get("parsed_generation")
            artifact = vals.get("normalized_reasoning")
            logger.end_case(
                cid,
                raw_ev=ev,
                condition=condition,
                parent_event_id=case_start_eid,
            )
            prompt = vals.get("prompt", "")
            raw_response = vals.get("raw_response", "")
            gen_eid = vals.get("gen_event_id")
            classify_eid = vals.get("classify_event_id")
            logger.log_run(
                cid=cid,
                condition=condition,
                model=model,
                prompt=prompt,
                response=raw_response,
                parsed=_build_parsed_compat(parsed_gen),
                elapsed=elapsed,
                gen_event_id=gen_eid,
                classify_event_id=classify_eid,
            )
        except Exception as exc:
            log.warning(
                "graph_v1 %s: logging failed: %s", cid, exc,
            )

    return cid, condition, ev


def _build_parsed_compat(parsed_gen: Any) -> dict:
    """Build backward-compatible parsed dict for logger.log_run()."""
    if parsed_gen is None:
        return {"code": "", "reasoning": ""}
    fj = parsed_gen.full_json or {}
    return {
        "code": "",
        "reasoning": fj.get("root_cause", ""),
    }
