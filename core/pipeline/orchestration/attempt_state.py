"""AttemptState — typed container for all pipeline state in one attempt.

Populated stage by stage. Used by both single-shot (execution_v2) and
retry (retry_v2) paths. Eliminates state loss and duplicate pipeline code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AttemptState:
    """All pipeline state for one attempt."""

    # ── Identity ──
    case_id: str = ""
    condition: str = ""
    model: str = ""
    attempt_idx: int = 0

    # ── Stage 1: Generation ──
    prompt: str = ""
    prompt_meta: dict = field(default_factory=dict)
    raw_response: str = ""
    gen_event_id: Any = 0

    # ── Stage 2: Parsing ──
    strict_parse: Any = None       # ParsedGenerationV2
    recovery_parse: Any = None     # ParsedGenerationV2
    format_parse: Any = None       # ParsedGenerationV2
    routing: Any = None            # RoutingDecision
    parsed_gen: Any = None         # the selected ParsedGenerationV2

    # Canonical parsing semantics (set explicitly in stage_parse)
    strict_parse_valid: bool = False
    recovery_parse_valid: bool = False
    parse_mode: str = "failed"     # "strict" | "recovered" | "failed"
    recovery_used: bool = False
    # retry_eligible = at least one executable artifact exists.
    # If neither parser produced a structurally valid, schema-valid
    # output that the reconstructor can consume, there is nothing
    # to execute and retrying would waste an API call on the same
    # format failure.
    retry_eligible: bool = False
    # execution_source = routing.selected_source — what was actually
    # executed, not what could have been executed.
    execution_source: str = ""     # "strict" | "recovery" | "none"
    retry_triggered: bool = False  # True when attempt_idx > 0

    # ── Stage 3: Oracle ──
    oracle_result: dict = field(default_factory=dict)

    # ── Stage 4: Normalize ──
    artifact: Any = None           # NormalizedReasoningArtifactV2

    # ── Stage 5: Reconstruction ──
    recon: Any = None              # ReconstructionResult
    code: str = ""                 # full materialized code for classifier
    artifact_id: str = ""

    # ── Stage 6: Classification ──
    classifier_result: Any = None  # ClassifierResultV2
    classify_event_id: Any = 0

    # ── Stage 7: AST ──
    ast_result: dict = field(default_factory=dict)

    # ── Stage 8: Execution ──
    exec_result: dict = field(default_factory=dict)
    passed: bool = False

    # ── Stage 9: Derived metrics ──
    disagreement: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    evaluation: dict = field(default_factory=dict)

    # ── Timing ──
    start_time: float = 0.0
    elapsed: float = 0.0
