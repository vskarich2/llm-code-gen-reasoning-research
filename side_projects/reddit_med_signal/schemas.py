"""Data schemas for the Reddit medication signal tool.

All Pydantic models for raw items, extraction records, aggregation results,
and intermediate classification signals.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ConflictType(str, Enum):
    DIRECT_CONTRADICTION = "direct_contradiction"
    TEMPORAL_VARIATION = "temporal_variation"
    DOSE_CONTEXT_VARIATION = "dose_context_variation"
    UNRESOLVED_HETEROGENEITY = "unresolved_heterogeneity"


# ---------------------------------------------------------------------------
# Raw retrieval
# ---------------------------------------------------------------------------

class RawItem(BaseModel):
    item_type: Literal["post", "comment"]
    reddit_id: str
    subreddit: str
    url: str
    author: Optional[str] = None
    created_utc: float
    score: int
    title: Optional[str] = None
    body: str
    parent_post_id: Optional[str] = None
    comment_depth: int = 0
    parent_comment_id: Optional[str] = None
    retrieved_at: str


# ---------------------------------------------------------------------------
# Firsthand signals (heuristic, pre-LLM)
# ---------------------------------------------------------------------------

class FirsthandSignals(BaseModel):
    has_first_person_pronoun: bool = False
    has_self_use_verb: bool = False
    has_secondhand_marker: bool = False
    has_advice_only_pattern: bool = False
    has_speculation_marker: bool = False
    heuristic_firsthand_score: Literal[
        "strong_yes", "weak_yes", "neutral", "weak_no", "strong_no"
    ] = "neutral"


# ---------------------------------------------------------------------------
# Extracted effects
# ---------------------------------------------------------------------------

class ReportedEffect(BaseModel):
    effect_raw: str
    effect_evidence_span: str
    effect_normalized: str = ""  # filled by normalization layer
    directionality: Literal["positive", "negative", "neutral", "ambiguous"]
    severity_hint: Literal["mild", "moderate", "severe", "unspecified"]
    is_secondorder: bool = False
    secondorder_chain: Optional[str] = None
    temporal_context: Optional[str] = None
    extraction_confidence: Literal["high", "medium", "low"] = "medium"


class ExtractedRecord(BaseModel):
    drug_query: str
    canonical_drug_name: str
    source_type: Literal["post", "comment"]
    subreddit: str
    reddit_id: str
    url: str
    authored_timestamp: float
    text_excerpt: str
    comment_depth: int = 0

    # Hybrid firsthand classification
    firsthand_heuristic: FirsthandSignals
    firsthand_llm: bool = False
    firsthand_llm_confidence: Literal["high", "medium", "low"] = "low"
    firsthand_final: bool = False
    firsthand_final_confidence: Literal["high", "medium", "low"] = "low"

    mentions_personal_use: bool = False
    reported_effects: List[ReportedEffect] = Field(default_factory=list)
    co_medications: List[str] = Field(default_factory=list)
    temporal_info: Optional[str] = None
    uncertainty_flags: List[str] = Field(default_factory=list)
    extraction_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

class EffectTheme(BaseModel):
    effect_normalized: str
    mention_count: int = 0
    weighted_count: float = 0.0
    directionality_breakdown: Dict[str, int] = Field(default_factory=dict)
    severity_breakdown: Dict[str, int] = Field(default_factory=dict)
    has_contradiction: bool = False
    secondorder_chains: List[str] = Field(default_factory=list)
    example_excerpts: List[str] = Field(default_factory=list)
    example_urls: List[str] = Field(default_factory=list)
    example_scores: List[float] = Field(default_factory=list)


class ConflictRecord(BaseModel):
    effect_a: str
    effect_b: str
    conflict_type: ConflictType
    evidence_summary: str = ""
    count_a: int = 0
    count_b: int = 0
    example_a: str = ""
    example_b: str = ""


class AggregationResult(BaseModel):
    drug_query: str
    canonical_drug_name: str
    total_raw_items: int = 0
    total_after_heuristic_filter: int = 0
    total_extraction_attempted: int = 0
    total_extraction_succeeded: int = 0
    total_extraction_failed: int = 0
    total_firsthand_high: int = 0
    total_firsthand_medium: int = 0
    total_firsthand_low: int = 0
    total_excluded: int = 0
    total_deduped: int = 0
    ungrounded_effects_dropped: int = 0
    is_sparse: bool = False
    themes: List[EffectTheme] = Field(default_factory=list)
    conflicts: List[ConflictRecord] = Field(default_factory=list)
    co_medication_counts: Dict[str, int] = Field(default_factory=dict)
    uncertainty_summary: Dict[str, int] = Field(default_factory=dict)
    unmapped_labels: List[str] = Field(default_factory=list)
    run_timestamp: str = ""
    config_snapshot: dict = Field(default_factory=dict)
