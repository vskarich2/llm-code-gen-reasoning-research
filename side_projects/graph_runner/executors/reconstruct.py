from side_projects.graph_runner.state import ExecutionState, Artifact
from side_projects.graph_runner.stage_spec import StageResult
from side_projects.graph_runner.contracts.response_contract import ResponseContract, ResponseContractError


def parse_executor(state: ExecutionState) -> StageResult:
    raw = state.get("raw_response").value

    try:
        validated = ResponseContract.validate(raw)
    except ResponseContractError as e:
        artifact = Artifact.create(
            type="parse_error",
            value=str(e),
        )
        state.add_artifact("parse_error", artifact)
        return StageResult(state=state, outcome="error")

    artifact = Artifact.create(
        type="parsed_response",
        value=validated,
    )

    state.add_artifact("parsed_response", artifact)
    return StageResult(state=state, outcome="success")
