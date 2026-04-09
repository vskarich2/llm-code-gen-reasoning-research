"""View registry. Enum-keyed. All views are pure functions of RunIR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core.logging_v2.config import LoggingV2Config
from core.logging_v2.enums import ViewName
from core.logging_v2.views.intermediate import RunIR
from core.logging_v2.views.renderers import (
    render_failures,
    render_index,
    render_llm_calls,
    render_summary,
    render_timeline,
    render_trial_table,
)


@dataclass(frozen=True)
class ViewSpec:
    name: ViewName
    filename: str
    renderer: Callable[[RunIR, LoggingV2Config], str]


VIEW_REGISTRY: dict[ViewName, ViewSpec] = {
    ViewName.SUMMARY:     ViewSpec(ViewName.SUMMARY,     "summary.md",     render_summary),
    ViewName.TIMELINE:    ViewSpec(ViewName.TIMELINE,     "timeline.md",    render_timeline),
    ViewName.FAILURES:    ViewSpec(ViewName.FAILURES,     "failures.md",    render_failures),
    ViewName.LLM_CALLS:   ViewSpec(ViewName.LLM_CALLS,   "llm_calls.md",   render_llm_calls),
    ViewName.TRIAL_TABLE: ViewSpec(ViewName.TRIAL_TABLE, "trial_table.md", render_trial_table),
    ViewName.INDEX:       ViewSpec(ViewName.INDEX,       "index.json",     render_index),
}
