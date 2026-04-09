"""Base node interface for the graph runner DAG.

All nodes inherit from BaseNode and declare explicit input/output keys.
The runner validates contracts before and after execution.
Nodes MUST NOT read undeclared keys or write undeclared keys.
Nodes MUST NOT mutate the input state dict.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Final, FrozenSet

from core.constants.pipeline_constants import (
    NODE_TYPE_EFFECT,
    NODE_TYPE_PURE,
    VALID_NODE_TYPES,
)

_log = logging.getLogger("t3.node_interface")


class NodeResult:
    """Return type from node execution.

    Contains ONLY the new keys produced by the node.
    The runner merges these into the pipeline state.
    """

    __slots__ = ("outputs", "outcome")

    def __init__(
        self,
        outputs: dict[str, Any],
        outcome: str = "success",
    ) -> None:
        self.outputs = outputs
        self.outcome = outcome


class BaseNode(ABC):
    """Abstract base class for all pipeline nodes.

    Subclasses MUST define:
      - NAME: str
      - INPUT_KEYS: frozenset[str]
      - OUTPUT_KEYS: frozenset[str]
      - NODE_TYPE: "pure" or "effect"
      - execute(inputs: dict) -> NodeResult
    """

    NAME: str
    INPUT_KEYS: FrozenSet[str]
    OUTPUT_KEYS: FrozenSet[str]
    NODE_TYPE: str  # NODE_TYPE_PURE or NODE_TYPE_EFFECT

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "__abstractmethods__", None):
            return
        for attr in ("NAME", "INPUT_KEYS", "OUTPUT_KEYS", "NODE_TYPE"):
            if not hasattr(cls, attr):
                raise TypeError(
                    f"Node class {cls.__name__} must define {attr}"
                )
        if cls.NODE_TYPE not in VALID_NODE_TYPES:
            raise TypeError(
                f"Node {cls.__name__}.NODE_TYPE must be "
                f"'{NODE_TYPE_PURE}' or '{NODE_TYPE_EFFECT}', "
                f"got {cls.NODE_TYPE!r}"
            )
        if not isinstance(cls.INPUT_KEYS, frozenset):
            raise TypeError(
                f"Node {cls.__name__}.INPUT_KEYS must be frozenset"
            )
        if not isinstance(cls.OUTPUT_KEYS, frozenset):
            raise TypeError(
                f"Node {cls.__name__}.OUTPUT_KEYS must be frozenset"
            )

    def validate_inputs(self, state: dict[str, Any]) -> None:
        """Check that all declared input keys are present in state."""
        missing = self.INPUT_KEYS - set(state.keys())
        if missing:
            raise ValueError(
                f"Node '{self.NAME}' missing required inputs: "
                f"{sorted(missing)}"
            )

    def validate_outputs(self, result: NodeResult) -> None:
        """Check that result contains exactly the declared output keys."""
        produced = set(result.outputs.keys())
        missing = self.OUTPUT_KEYS - produced
        extra = produced - self.OUTPUT_KEYS
        if missing:
            raise ValueError(
                f"Node '{self.NAME}' did not produce declared "
                f"outputs: {sorted(missing)}"
            )
        if extra:
            raise ValueError(
                f"Node '{self.NAME}' produced undeclared "
                f"outputs: {sorted(extra)}"
            )

    def run(self, state: dict[str, Any]) -> NodeResult:
        """Validate inputs, execute, validate outputs.

        This is the public entry point called by the runner.
        Subclasses override execute(), not run().
        """
        self.validate_inputs(state)
        inputs = {k: state[k] for k in self.INPUT_KEYS}
        result = self.execute(inputs)
        self.validate_outputs(result)
        return result

    @abstractmethod
    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        """Execute the node logic.

        Args:
            inputs: dict containing ONLY the declared INPUT_KEYS.

        Returns:
            NodeResult with outputs containing ONLY the declared
            OUTPUT_KEYS.
        """
        ...
