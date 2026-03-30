from graph_runner.state import ExecutionState, Artifact
from graph_runner.stage_spec import StageResult


def build_prompt_executor(state: ExecutionState) -> StageResult:
    case = state.get("case").value

    task = case.get("task", "")
    code_files = case.get("code_files", [])

    prompt = f"""TASK:
{task}

CODE FILES:
{code_files}
"""

    state.add_artifact(
        "prompt",
        Artifact.create(
            type="prompt",
            value=prompt,
        ),
    )

    return StageResult(state=state, outcome="success")
