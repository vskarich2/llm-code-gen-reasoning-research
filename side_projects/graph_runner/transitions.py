from side_projects.graph_runner.state import ExecutionState


def has_prompt(state: ExecutionState) -> bool:
    return state.has("prompt")


def has_raw_response(state: ExecutionState) -> bool:
    return state.has("raw_response")


def can_execute(state: ExecutionState) -> bool:
    return state.has("parsed_response") and not state.has("parse_error")
