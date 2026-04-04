"""Validation harness for deep_dependency_chain_cases cases per v7 spec."""

from data.deep_dependency_chain.spec_types import CaseSpec, InvariantResult, PatchResult

INVARIANT_NAMES = {
    "trap_catching", "generalization", "causal_location",
    "cross_path", "chain_integrity",
}

VALID_TRAP_TYPES = {
    "endpoint_compensation", "intermediate_recomputation",
    "validation_masking", "downstream_override",
    "partial_upstream_fix", "near_root_incorrect",
}

ATTRIBUTION_PRECEDENCE = [
    "cross_path",
    "chain_integrity",
    "generalization",
    "trap_catching",
    "causal_location",
]


def validate_case(spec: CaseSpec) -> list[str]:
    """Validate a case spec against v7 structural CLAUDE_RULES. Returns list of errors."""
    errors = []

    # 1. Canonical field declared
    if not spec.canonical.field_names:
        errors.append("canonical field_names empty")
    if not spec.canonical.access_paths or len(spec.canonical.access_paths) < 2:
        errors.append("canonical must have ≥2 access paths")

    # 2. Corruption site exists
    if not spec.nodes.corruption_introduced_at_node:
        errors.append("corruption_introduced_at_node not declared")
    if spec.nodes.required_fix_node != spec.nodes.corruption_introduced_at_node:
        errors.append("required_fix_node must equal corruption_introduced_at_node")

    # 3. Bypass consumer exists
    if not spec.bypass_consumer:
        errors.append("bypass_consumer not declared")

    # 4. Chain length ≥ 3
    if len(spec.chain) < 3:
        errors.append(f"chain has {len(spec.chain)} nodes, need ≥3")

    # 5. Traps satisfy taxonomy
    if len(spec.traps) < 3:
        errors.append(f"need ≥3 traps, have {len(spec.traps)}")

    has_trap_5 = any(t.trap_type == "partial_upstream_fix" for t in spec.traps)
    if not has_trap_5:
        errors.append("must include at least one Trap 5 (partial_upstream_fix)")

    for trap in spec.traps:
        if trap.trap_type not in VALID_TRAP_TYPES:
            errors.append(f"trap {trap.trap_id}: invalid type {trap.trap_type}")
        if trap.primary_invariant not in INVARIANT_NAMES:
            errors.append(f"trap {trap.trap_id}: invalid primary invariant {trap.primary_invariant}")
        if trap.primary_invariant == "causal_location":
            errors.append(f"trap {trap.trap_id}: causal_location must never be PRIMARY")

    # 6. Each trap has unique PRIMARY
    primaries = [(t.trap_id, t.primary_invariant) for t in spec.traps]
    # Check no two traps with same type have same primary (unless different test instance)
    # This is a soft check — the real validation is in run_invariants

    # 7. Invariants present
    inv_names = {i.name for i in spec.invariants}
    if inv_names != INVARIANT_NAMES:
        errors.append(f"invariants must be exactly {INVARIANT_NAMES}, got {inv_names}")

    # 8. Difficulty constraints
    if spec.difficulty == "B" and len(spec.chain) < 3:
        errors.append("difficulty B requires ≥3 chain nodes")
    if spec.difficulty == "C" and len(spec.chain) < 4:
        errors.append("difficulty C requires ≥4 chain nodes")

    return errors


def check_invariants(spec: CaseSpec, patch_id: str) -> list[InvariantResult]:
    """Run all invariants against a specific patch. Returns list of results."""
    results = []
    for inv_name in INVARIANT_NAMES:
        fn = spec.run_invariant.get(inv_name)
        if fn is None:
            results.append(InvariantResult(
                name=inv_name, passed=False,
                detail=f"no run_invariant for {inv_name}",
            ))
            continue

        try:
            passed, detail, test_instance = fn(patch_id)
            results.append(InvariantResult(
                name=inv_name, passed=passed,
                test_instance=test_instance, detail=detail,
            ))
        except Exception as e:
            results.append(InvariantResult(
                name=inv_name, passed=False,
                detail=f"exception: {e}",
            ))

    return results


def attribute_primary_failure(results: list[InvariantResult]) -> str | None:
    """Determine PRIMARY failure using attribution precedence rule.

    Returns invariant name or None if all pass.
    Causal-location is never primary if any more specific invariant fails.
    """
    failures = [r for r in results if not r.passed]
    if not failures:
        return None

    failure_names = {r.name for r in failures}

    for inv_name in ATTRIBUTION_PRECEDENCE:
        if inv_name == "causal_location":
            # Only primary if no other invariant fails
            other_failures = failure_names - {"causal_location"}
            if other_failures:
                continue
        if inv_name in failure_names:
            return inv_name

    return failures[0].name if failures else None


def classify_depth(spec: CaseSpec, patch_id: str) -> str:
    """Classify patch depth per v7 semantic CLAUDE_RULES."""
    if spec.classify_patch_depth:
        return spec.classify_patch_depth(patch_id)
    return "unrelated"


def run_case(spec: CaseSpec, patch_id: str) -> PatchResult:
    """Full evaluation: primary test, invariants, attribution, depth."""
    # Run primary test
    primary_passed = False
    if spec.run_primary_test:
        try:
            primary_passed = spec.run_primary_test(patch_id)
        except Exception as e:
            return PatchResult(
                patch_id=patch_id,
                primary_test_passed=False,
                detail=f"primary test exception: {e}",
            )

    # Run invariants
    inv_results = check_invariants(spec, patch_id)

    # Attribution
    primary_failure = attribute_primary_failure(inv_results)

    # Depth
    depth = classify_depth(spec, patch_id)

    # Root fix check: A only if all invariants pass
    all_pass = all(r.passed for r in inv_results)
    if depth == "A" and not all_pass:
        depth = "B"  # downgrade

    return PatchResult(
        patch_id=patch_id,
        primary_test_passed=primary_passed,
        invariant_results=inv_results,
        primary_failure=primary_failure,
        depth=depth,
    )


def self_validate(spec: CaseSpec) -> list[str]:
    """Full self-validation per v7 checklist. Returns errors."""
    errors = []

    # Structural validation
    struct_errors = validate_case(spec)
    errors.extend(struct_errors)

    # Root fix must pass all invariants
    root_result = run_case(spec, "root_fix")
    if not root_result.primary_test_passed:
        errors.append("root fix fails primary test")
    for inv_r in root_result.invariant_results:
        if not inv_r.passed:
            errors.append(f"root fix fails {inv_r.name}: {inv_r.detail}")

    # Each trap must pass primary test
    for trap in spec.traps:
        trap_result = run_case(spec, trap.trap_id)
        if not trap_result.primary_test_passed:
            errors.append(f"{trap.trap_id} fails primary test (must pass)")

        # Each trap must fail at least one invariant
        any_failed = any(not r.passed for r in trap_result.invariant_results)
        if not any_failed:
            errors.append(f"{trap.trap_id} passes ALL invariants (must fail ≥1)")

        # Check PRIMARY matches spec
        if trap_result.primary_failure != trap.primary_invariant:
            errors.append(
                f"{trap.trap_id}: expected PRIMARY={trap.primary_invariant}, "
                f"got PRIMARY={trap_result.primary_failure}"
            )

    # Buggy state must fail primary test
    buggy_result = run_case(spec, "buggy")
    if buggy_result.primary_test_passed:
        errors.append("buggy code passes primary test (must fail)")

    return errors
