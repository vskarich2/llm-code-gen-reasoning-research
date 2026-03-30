#!/usr/bin/env python3

from pathlib import Path

BASE = Path("graph_runner")

STRUCTURE = {
    "__init__.py": "",
    "graph_runner.py": "",
    "state.py": "",
    "stage_spec.py": "",
    "transitions.py": "",
    "graph_factory.py": "",
    "policy.py": "",
    "shadow_runner.py": "",
    "executors": {
        "__init__.py": "",
        "generate.py": "",
        "classify.py": "",
        "critique.py": "",
        "exec_eval.py": "",
        "reconstruct.py": "",
        "build_prompt.py": "",
        "apply_nudge.py": "",
        "retry.py": "",
        "diff_gate.py": "",
    },
    "adapters": {
        "__init__.py": "",
        "legacy_adapter.py": "",
    },
    "contracts": {
        "__init__.py": "",
        "response_contract.py": "",
        "execution_contract.py": "",
        "input_contract.py": "",
    },
}


def create_structure(base: Path, structure: dict, overwrite: bool = False) -> None:
    for name, content in structure.items():
        path = base / name

        if isinstance(content, dict):
            path.mkdir(parents=True, exist_ok=True)
            create_structure(path, content, overwrite)
        else:
            if path.exists() and not overwrite:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")


if __name__ == "__main__":
    create_structure(BASE, STRUCTURE, overwrite=False)
    print(f"Graph runner structure created at: {BASE.resolve()}")