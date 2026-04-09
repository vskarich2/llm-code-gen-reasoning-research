"""Centralized axis system. Single source of truth for directory nesting order,
prefixes, type constraints, and required/optional status.

All path construction MUST use AXIS_ORDER and AXIS_SPECS.
No manual string concatenation for artifact paths anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.logging_v2.enums import Axis


@dataclass(frozen=True)
class AxisSpec:
    axis: Axis
    prefix: str | None
    required: bool
    zero_indexed: bool
    value_type: type


AXIS_ORDER: tuple[Axis, ...] = (
    Axis.CONDITION,
    Axis.MODEL,
    Axis.CASE,
    Axis.TRIAL,
    Axis.PATH,
    Axis.NODE,
    Axis.CALL,
)

AXIS_SPECS: dict[Axis, AxisSpec] = {
    Axis.CONDITION: AxisSpec(axis=Axis.CONDITION, prefix=None,     required=True,  zero_indexed=False, value_type=str),
    Axis.MODEL:     AxisSpec(axis=Axis.MODEL,     prefix=None,     required=True,  zero_indexed=False, value_type=str),
    Axis.CASE:      AxisSpec(axis=Axis.CASE,      prefix=None,     required=True,  zero_indexed=False, value_type=str),
    Axis.TRIAL:     AxisSpec(axis=Axis.TRIAL,      prefix="trial_", required=True,  zero_indexed=True,  value_type=int),
    Axis.PATH:      AxisSpec(axis=Axis.PATH,       prefix="path_",  required=True,  zero_indexed=True,  value_type=int),
    Axis.NODE:      AxisSpec(axis=Axis.NODE,       prefix=None,     required=False, zero_indexed=False, value_type=str),
    Axis.CALL:      AxisSpec(axis=Axis.CALL,       prefix="call_",  required=False, zero_indexed=False, value_type=str),
}

FILESYSTEM_FORBIDDEN = frozenset({"/", "\\", ":", "..", "\x00"})


def validate_filesystem_safe(value: str, axis: Axis) -> None:
    for char in FILESYSTEM_FORBIDDEN:
        if char in value:
            raise ValueError(
                f"Axis {axis.value} value {value!r} contains "
                f"forbidden character {char!r}"
            )
