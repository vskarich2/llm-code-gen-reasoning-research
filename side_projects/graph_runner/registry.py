"""Node registry — maps string IDs to node classes.

All node instantiation goes through this registry. No inline construction.
Extension contract: add one entry here + one config line to activate.
"""

from __future__ import annotations

from typing import Any, Type

from side_projects.graph_runner.constants import (
    NODE_ID_AST_VERIFY,
    NODE_ID_CLASSIFIER_AGGREGATION,
    NODE_ID_CLASSIFIER_REASONING,
    NODE_ID_EXECUTE,
    NODE_ID_GENERATE,
    NODE_ID_LOG,
    NODE_ID_NORMALIZE,
    NODE_ID_ORACLE_AGGREGATION,
    NODE_ID_ORACLE_INLINE,
    NODE_ID_PARSE,
    NODE_ID_RECONSTRUCT,
    NODE_ID_ROUTE,
    NODE_ID_SPEC_ORACLE,
)
from side_projects.graph_runner.node_interface import BaseNode


class NodeRegistry:
    """Singleton registry mapping string IDs to node classes.

    Validates:
      - No duplicate registrations
      - All registered classes are BaseNode subclasses
    """

    def __init__(self) -> None:
        self.entries: dict[str, Type[BaseNode]] = {}

    def register(
        self, node_id: str, node_cls: Type[BaseNode],
    ) -> None:
        if node_id in self.entries:
            raise ValueError(
                f"Duplicate node registration: {node_id!r} "
                f"(existing: {self.entries[node_id].__name__}, "
                f"new: {node_cls.__name__})"
            )
        if not (
            isinstance(node_cls, type) and issubclass(node_cls, BaseNode)
        ):
            raise TypeError(
                f"Registry entry {node_id!r} must be a BaseNode "
                f"subclass, got {node_cls!r}"
            )
        self.entries[node_id] = node_cls

    def get(self, node_id: str) -> Type[BaseNode]:
        if node_id not in self.entries:
            raise KeyError(
                f"Unknown node ID {node_id!r}. "
                f"Available: {sorted(self.entries.keys())}"
            )
        return self.entries[node_id]

    def has(self, node_id: str) -> bool:
        return node_id in self.entries

    def list_ids(self) -> list[str]:
        return sorted(self.entries.keys())


# Global registry instance
REGISTRY = NodeRegistry()


def register_phase1_nodes() -> None:
    """Register Phase 1 pure nodes."""
    from side_projects.graph_runner.nodes.parse import ParseNode
    from side_projects.graph_runner.nodes.route import RouteNode
    from side_projects.graph_runner.nodes.normalize import NormalizeNode
    from side_projects.graph_runner.nodes.reconstruct import ReconstructNode
    from side_projects.graph_runner.nodes.ast_verify import ASTNode
    from side_projects.graph_runner.nodes.spec_oracle import SpecOracleNode

    REGISTRY.register(NODE_ID_PARSE, ParseNode)
    REGISTRY.register(NODE_ID_ROUTE, RouteNode)
    REGISTRY.register(NODE_ID_NORMALIZE, NormalizeNode)
    REGISTRY.register(NODE_ID_RECONSTRUCT, ReconstructNode)
    REGISTRY.register(NODE_ID_AST_VERIFY, ASTNode)
    REGISTRY.register(NODE_ID_SPEC_ORACLE, SpecOracleNode)


def register_phase2_nodes() -> None:
    """Register Phase 2 effect nodes."""
    from side_projects.graph_runner.nodes.generate import GenerateNode
    from side_projects.graph_runner.nodes.execute import ExecuteNode
    from side_projects.graph_runner.nodes.log import LogNode

    REGISTRY.register(NODE_ID_GENERATE, GenerateNode)
    REGISTRY.register(NODE_ID_EXECUTE, ExecuteNode)
    REGISTRY.register(NODE_ID_LOG, LogNode)


def register_phase3_nodes() -> None:
    """Register Phase 3 oracle/classifier slot + aggregation nodes."""
    from side_projects.graph_runner.nodes.oracles.inline_oracle import (
        InlineOracleNode,
    )
    from side_projects.graph_runner.nodes.oracles.oracle_aggregation import (
        OracleAggregationNode,
    )
    from side_projects.graph_runner.nodes.classifiers.reasoning_classifier import (
        ReasoningClassifierNode,
    )
    from side_projects.graph_runner.nodes.classifiers.classifier_aggregation import (
        ClassifierAggregationNode,
    )

    REGISTRY.register(NODE_ID_ORACLE_INLINE, InlineOracleNode)
    REGISTRY.register(NODE_ID_ORACLE_AGGREGATION, OracleAggregationNode)
    REGISTRY.register(NODE_ID_CLASSIFIER_REASONING, ReasoningClassifierNode)
    REGISTRY.register(NODE_ID_CLASSIFIER_AGGREGATION, ClassifierAggregationNode)


# Auto-register on import
register_phase1_nodes()
register_phase2_nodes()
register_phase3_nodes()
