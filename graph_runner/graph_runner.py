from __future__ import annotations

from typing import List

from graph_runner.state import ExecutionState
from graph_runner.stage_spec import StageSpec


class GraphRunner:
    def __init__(self, stages: List[StageSpec]):
        self.stages = stages

    def run(self, initial_state: ExecutionState) -> ExecutionState:
        state = initial_state

        for stage in self.stages:
            if not stage.should_run(state):
                continue

            stage.validate_inputs(state)

            result = stage.executor(state)
            state = result.state

        return state
