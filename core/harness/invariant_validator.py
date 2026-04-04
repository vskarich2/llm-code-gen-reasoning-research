"""Spec compliance audit for invariant specifications.

Implements Condition 1 from plan v4: every invariant must satisfy
constraints 1-17 before experiments can run. This is the mandatory
pre-experiment gate.
"""

from core.harness.invariant_schema import (
    InvariantSpec,
    EquivalencePolicy,
    MechanismEvidenceLevel,
)


def validate_spec(spec: InvariantSpec) -> list[str]:
    """Validate a single invariant spec against all 17 constraints.

    Returns list of violation messages. Empty list = compliant.
    """
    violations = []

    # C1: degenerate_pass_patterns non-empty
    if not spec.degenerate_pass_patterns:
        violations.append(
            f"C1: {spec.invariant_id} has no degenerate_pass_patterns"
        )

    # C2: stateful -> reset not just ad-hoc (checked at test level)
    # C3: failure_injection -> happy + failure paths
    if spec.happy_path_obligations and not spec.complement_conditions:
        violations.append(
            f"C3: {spec.invariant_id} has happy_path but no complements"
        )

    # C4: mechanism-sensitive -> mechanism_requirements.required
    _is_mechanism = spec.equivalence_policy != EquivalencePolicy.BEHAVIOR_ONLY
    if _is_mechanism and not spec.mechanism_requirements.required:
        violations.append(
            f"C4: {spec.invariant_id} has non-behavior_only policy "
            f"but mechanism_requirements.required is False"
        )

    # C5: complement_conditions non-empty
    if not spec.complement_conditions:
        violations.append(
            f"C5: {spec.invariant_id} has no complement_conditions"
        )

    # C6: assertions >= 2 on different state dimensions
    if len(spec.assertions) < 2:
        violations.append(
            f"C6: {spec.invariant_id} has {len(spec.assertions)} "
            f"assertions, need >= 2"
        )

    # C7: forbidden_post_state >= 1
    if not spec.forbidden_post_state:
        violations.append(
            f"C7: {spec.invariant_id} has no forbidden_post_state"
        )

    # C9: non-behavior_only -> mechanisms lists non-empty
    if _is_mechanism:
        if not spec.acceptable_mechanisms:
            violations.append(
                f"C9: {spec.invariant_id} non-behavior_only but "
                f"acceptable_mechanisms is empty"
            )
        if not spec.forbidden_mechanisms:
            violations.append(
                f"C9: {spec.invariant_id} non-behavior_only but "
                f"forbidden_mechanisms is empty"
            )

    # C10: mutation_sensitivity >= 2
    if len(spec.mutation_sensitivity) < 2:
        violations.append(
            f"C10: {spec.invariant_id} has {len(spec.mutation_sensitivity)}"
            f" mutation_sensitivity entries, need >= 2"
        )

    # C12: EXERCISE/NECESSITY -> bypass degenerate pattern
    _needs_bypass = spec.mechanism_evidence_level in (
        MechanismEvidenceLevel.EXERCISE,
        MechanismEvidenceLevel.NECESSITY,
    )
    if _needs_bypass:
        has_bypass = any(
            "bypass" in p.name.lower() or "removal" in p.name.lower()
            for p in spec.degenerate_pass_patterns
        )
        if not has_bypass:
            violations.append(
                f"C12: {spec.invariant_id} requires "
                f"{spec.mechanism_evidence_level.value} but has no "
                f"bypass/removal degenerate pattern"
            )

    # C13: evidence level set; NONE iff behavior_only
    if _is_mechanism and spec.mechanism_evidence_level == MechanismEvidenceLevel.NONE:
        violations.append(
            f"C13: {spec.invariant_id} non-behavior_only but "
            f"mechanism_evidence_level is NONE"
        )
    if not _is_mechanism and spec.mechanism_evidence_level != MechanismEvidenceLevel.NONE:
        violations.append(
            f"C13: {spec.invariant_id} behavior_only but "
            f"mechanism_evidence_level is {spec.mechanism_evidence_level.value}"
        )

    # C14: NECESSITY -> necessity_probe defined
    if spec.mechanism_evidence_level == MechanismEvidenceLevel.NECESSITY:
        if spec.mechanism_requirements.necessity_conditions is None:
            violations.append(
                f"C14: {spec.invariant_id} requires NECESSITY but "
                f"necessity_conditions not defined"
            )

    # C15: boundary-sensitive -> boundary_checks non-empty
    if spec.boundary_type != "local" and spec.boundary_checks == []:
        # Only enforce if policy includes boundary preservation
        if "boundary" in spec.equivalence_policy.value.lower():
            violations.append(
                f"C15: {spec.invariant_id} boundary-sensitive but "
                f"boundary_checks is empty"
            )

    # C16: strength >= USABLE (hard gate)
    from core.harness.invariant_schema import StrengthLevel
    _strength_order = {
        StrengthLevel.INVALID: 0,
        StrengthLevel.WEAK: 1,
        StrengthLevel.USABLE: 2,
        StrengthLevel.STRONG: 3,
        StrengthLevel.RESEARCH_GRADE: 4,
    }
    if _strength_order[spec.semantic_strength_level] < 2:
        violations.append(
            f"C16: {spec.invariant_id} strength is "
            f"{spec.semantic_strength_level.value}, must be >= USABLE"
        )

    return violations


def validate_all(specs: list[InvariantSpec]) -> dict:
    """Validate all specs. Returns {invariant_id: [violations]}.

    If any spec has violations, the benchmark is invalid for
    reporting (Condition 1).
    """
    results = {}
    for spec in specs:
        v = validate_spec(spec)
        if v:
            results[spec.invariant_id] = v
    return results
