from side_projects.graph_runner.state import ExecutionState, Artifact
from side_projects.graph_runner.graph_runner import GraphRunner
from side_projects.graph_runner.graph_factory import build_minimal_graph


def main():
    state = ExecutionState()

    # Seed initial prompt
    state.add_artifact(
        "prompt",
        Artifact.create(
            type="prompt",
            value="Fix the bug in create_config()",
        ),
    )

    graph = build_minimal_graph()
    runner = GraphRunner(graph)

    final_state = runner.run(state)

    result = final_state.get("parsed_response").value
    print("FINAL OUTPUT:")
    print(result)


if __name__ == "__main__":
    main()