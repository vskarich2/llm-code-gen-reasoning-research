"""Stat registry. Enum-keyed. Adding a stat = one enum + one function + one entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.logging_v2.enums import Axis, StatName
from core.logging_v2.stats.builtins import (
    compute_attempt_count,
    compute_leg_rate,
    compute_mean_latency,
    compute_parse_rate,
    compute_pass_rate,
)
from core.logging_v2.views.intermediate import RunIR


@dataclass(frozen=True)
class StatSpec:
    name: StatName
    compute: Callable[[RunIR, list[Axis]], dict[str, Any]]
    axes: list[Axis]


STAT_REGISTRY: dict[StatName, StatSpec] = {
    StatName.PASS_RATE: StatSpec(
        StatName.PASS_RATE, compute_pass_rate,
        [Axis.CONDITION, Axis.MODEL],
    ),
    StatName.LEG_RATE: StatSpec(
        StatName.LEG_RATE, compute_leg_rate,
        [Axis.CONDITION, Axis.MODEL],
    ),
    StatName.ATTEMPT_COUNT: StatSpec(
        StatName.ATTEMPT_COUNT, compute_attempt_count,
        [Axis.CONDITION, Axis.MODEL, Axis.CASE],
    ),
    StatName.PARSE_SUCCESS_RATE: StatSpec(
        StatName.PARSE_SUCCESS_RATE, compute_parse_rate,
        [Axis.CONDITION, Axis.MODEL],
    ),
    StatName.MEAN_LATENCY_MS: StatSpec(
        StatName.MEAN_LATENCY_MS, compute_mean_latency,
        [Axis.CONDITION, Axis.MODEL, Axis.NODE],
    ),
}
