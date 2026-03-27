"""Nudge operator registry.

A NudgeOperator is a named, reusable reasoning intervention that transforms
a base prompt into a nudged prompt. Operators are generic (not case-specific)
and target a class of failure mode.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass
class NudgeOperator:
    name: str
    kind: str  # "diagnostic" or "guardrail"
    description: str
    build_prompt: Callable[[str], str]


_REGISTRY: dict[str, NudgeOperator] = {}


def register(operator: NudgeOperator):
    """Register an operator by name."""
    _REGISTRY[operator.name] = operator


def get(name: str) -> NudgeOperator:
    """Retrieve a registered operator. Raises KeyError if not found."""
    if name not in _REGISTRY:
        raise KeyError(
            f"No operator registered with name {name!r}. " f"Available: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[name]


def list_operators() -> list[str]:
    """Return all registered operator names."""
    return list(_REGISTRY.keys())


def list_by_kind(kind: str) -> list[str]:
    """Return operator names filtered by kind ('diagnostic' or 'guardrail')."""
    return [name for name, op in _REGISTRY.items() if op.kind == kind]
