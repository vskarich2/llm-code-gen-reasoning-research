from __future__ import annotations

from graph_runner.state import ExecutionState, Artifact


def load_case_into_state(case: dict) -> ExecutionState:
    state = ExecutionState()

    state.add_artifact(
        "case",
        Artifact.create(
            type="case",
            value=case,
        ),
    )

    return state
