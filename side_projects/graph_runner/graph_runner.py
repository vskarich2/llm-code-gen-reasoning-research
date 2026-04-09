from __future__ import annotations

import logging
from typing import Any, List

from side_projects.graph_runner.state import ExecutionState
from side_projects.graph_runner.stage_spec import StageSpec
from core.graph.invariants import validate_pipeline_state
from core.constants.pipeline_constants import KEY_INVARIANTS

_log = logging.getLogger("t3.graph_runner")


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

            # Build a view dict for the validator: index + invariants
            view = dict(state.index)
            view[KEY_INVARIANTS] = invariants
            validate_pipeline_state(state=view, stage=stage.name)
            # Collect any violations appended by the validator
            invariants = view[KEY_INVARIANTS]

        # Store accumulated invariants in final state
        from side_projects.graph_runner.state import Artifact
        if invariants:
            state.add_artifact(
                KEY_INVARIANTS,
                Artifact.create(
                    type="invariant_violations",
                    value=invariants,
                ),
            )

        return state
