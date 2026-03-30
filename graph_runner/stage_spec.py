from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from graph_runner.state import ExecutionState


@dataclass
class StageResult:
    state: ExecutionState
    outcome: str  # "success" | "error" | "skipped"


@dataclass
class StageSpec:
    name: str
    input_keys: List[str]
    output_keys: List[str]
    executor: Callable[[ExecutionState], StageResult]
    guard: Optional[Callable[[ExecutionState], bool]] = None

    def validate_inputs(self, state: ExecutionState) -> None:
        missing = [k for k in self.input_keys if not state.has(k)]
        if missing:
            raise ValueError(f"Stage '{self.name}' missing inputs: {missing}")

    def should_run(self, state: ExecutionState) -> bool:
        if self.guard is None:
            return True
        return self.guard(state)
