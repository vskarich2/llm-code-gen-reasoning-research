"""GraphRunner — sequential DAG executor with invariant validation.

Executes nodes in order. After each node:
  1. Validates pipeline invariants (core/graph/invariants.py — per-node checks)
  2. Validates full state invariants (state_invariants.py — cross-field checks)
Both validators log warnings and record violations in state[KEY_INVARIANTS].
Neither raises exceptions.
"""

from __future__ import annotations

import logging
from typing import Any, List

from side_projects.graph_runner.state import Artifact, ExecutionState
from side_projects.graph_runner.stage_spec import StageSpec
from side_projects.graph_runner.state_invariants import validate_full_state
from side_projects.graph_runner.constants import KEY_INVARIANTS

log = logging.getLogger("t3.graph_runner")


class GraphRunner:
    def __init__(self, stages: List[StageSpec]) -> None:
        self.stages = stages

    def run(self, initial_state: ExecutionState) -> ExecutionState:
        state = initial_state
        invariants: list[dict[str, Any]] = []

        for stage in self.stages:
            if not stage.should_run(state):
                continue

            stage.validate_inputs(state)

            result = stage.executor(state)
            state = result.state

            view = dict(state.index)
            view[KEY_INVARIANTS] = invariants
            validate_full_state(state=view, stage=stage.name)
            invariants = view[KEY_INVARIANTS]

        if invariants:
            state.add_artifact(
                KEY_INVARIANTS,
                Artifact.create(
                    type="invariant_violations",
                    value=invariants,
                ),
            )

        return state
