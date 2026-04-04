"""Invariant specification schema for T3 benchmark.

Implements the (PRE, ACTION, POST_REQUIRED, POST_FORBIDDEN, META) model
from the invariant test overhaul plan v4.
"""

from dataclasses import dataclass, field
from enum import Enum


class EquivalencePolicy(str, Enum):
    BEHAVIOR_ONLY = "behavior_only"
    SIDE_EFFECT_PRESERVATION = "behavior_plus_side_effect_preservation"
    SIDE_EFFECT_TIMING = "behavior_plus_side_effect_timing"
    LIFECYCLE_PRESERVATION = "behavior_plus_lifecycle_preservation"
    SUBSYSTEM_PRESERVATION = "behavior_plus_subsystem_preservation"
    COMPENSATION_SEMANTICS = "behavior_plus_compensation_semantics"
    PROPAGATION_SEMANTICS = "behavior_plus_propagation_semantics"
    BOUNDARY_PRESERVATION = "behavior_plus_boundary_preservation"


class MechanismEvidenceLevel(str, Enum):
    NONE = "NONE"
    EXISTENCE = "EXISTENCE"
    EXERCISE = "EXERCISE"
    NECESSITY = "NECESSITY"


class StrengthLevel(str, Enum):
    INVALID = "INVALID"
    WEAK = "WEAK"
    USABLE = "USABLE"
    STRONG = "STRONG"
    RESEARCH_GRADE = "RESEARCH_GRADE"


class BcmvSubtype(str, Enum):
    REMOVAL = "BCMV_REMOVAL"
    BYPASS = "BCMV_BYPASS"
    BOUNDARY = "BCMV_BOUNDARY"
    DECORATIVE = "BCMV_DECORATIVE"
    NON_NECESSARY = "BCMV_NON_NECESSARY"


class BoundaryConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Classification(str, Enum):
    TRUE_FIX = "TRUE_FIX"
    PARTIAL_FIX = "PARTIAL_FIX"
    LUCKY_FIX = "LUCKY_FIX"
    BCMV = "BCMV"
    DEGENERATE_PASS = "DEGENERATE_PASS"
    TRAP_FIX = "TRAP_FIX"
    FAIL = "FAIL"
    CRASH = "CRASH"
    PARSE_FAILURE = "PARSE_FAILURE"


@dataclass
class Assertion:
    expr: str
    message: str
    category: str  # value | predicate | relational | identity | trace


@dataclass
class DegeneratePattern:
    name: str
    implementation: str
    why_it_passes: str
    detection: str


@dataclass
class BoundaryCheck:
    check_type: str  # call_routing | source_of_truth | dependency_direction
    description: str
    check: str
    confidence: BoundaryConfidence


@dataclass
class NecessityConditions:
    critical_path_trigger: str
    trigger_exercised_by: str
    coverage_proof: str
    downgrade_if_not_exercised: str = "EXERCISE"


@dataclass
class MechanismRequirements:
    required: bool
    evidence_level: MechanismEvidenceLevel = MechanismEvidenceLevel.NONE
    constraints: list[dict] = field(default_factory=list)
    preserved_subsystems: list[str] = field(default_factory=list)
    forbidden_bypasses: list[str] = field(default_factory=list)
    necessity_conditions: NecessityConditions | None = None
    necessity_probe: dict | None = None


@dataclass
class InvariantSpec:
    """Full invariant specification per plan v4 schema."""

    # Identity
    invariant_id: str
    family: str
    case_id: str
    bug_pattern: str
    semantic_domain: str

    # Equivalence policy
    equivalence_policy: EquivalencePolicy
    mechanism_evidence_level: MechanismEvidenceLevel
    acceptable_mechanisms: list[str] = field(default_factory=list)
    forbidden_mechanisms: list[str] = field(default_factory=list)

    # Scope
    boundary_type: str = "local"
    statefulness: str = "stateless"

    # State surfaces
    observational_surface: list[str] = field(default_factory=list)
    hidden_state_surface: list[str] = field(default_factory=list)
    required_unchanged_state: list[str] = field(default_factory=list)

    # Post-state
    assertions: list[Assertion] = field(default_factory=list)
    happy_path_obligations: list[Assertion] = field(default_factory=list)
    forbidden_post_state: list[DegeneratePattern] = field(
        default_factory=list
    )

    # Mechanism
    mechanism_requirements: MechanismRequirements = field(
        default_factory=lambda: MechanismRequirements(required=False)
    )
    mechanism_evidence_requirements: list[str] = field(
        default_factory=list
    )

    # Boundary
    boundary_checks: list[BoundaryCheck] = field(default_factory=list)

    # Complement / adversarial
    complement_conditions: list[dict] = field(default_factory=list)
    mutation_sensitivity: list[str] = field(default_factory=list)
    degenerate_pass_patterns: list[DegeneratePattern] = field(
        default_factory=list
    )

    # Strength
    semantic_strength_level: StrengthLevel = StrengthLevel.WEAK
    strength_gaps: list[str] = field(default_factory=list)
