"""Depth-direction hints for DDC cases.

When the spec oracle detects the LLM fixed at the wrong depth,
these hints guide the LLM upstream toward the root cause.

Used by the retry system as an alternative to LLM-generated critique.
"""

HINT_LEVELS = (
    # Original 3
    "gentle", "directed", "explicit",
    # Round 1: 9 hints
    "first_corruption", "anti_compensation", "dataflow_backtrace",
    "representation_purity", "single_node", "invariant_oriented",
    "edge_case_anti_heuristic", "upstream_only", "corruption_node_id",
    # Round 2: 10 hints (grouped by strategy)
    # Group 1: Force localization
    "first_mutation_constraint", "single_assignment_constraint", "no_downstream_edits",
    # Group 2: Force representation correctness
    "representation_preservation", "round_trip_invariant", "no_derived_fix",
    # Group 3: Force minimality
    "one_function_constraint", "one_edit_constraint",
    # Group 4: Force causal consistency
    "cross_path_consistency", "origin_consistency",
)

HINT_TEMPLATES = {
    # ── Original 3 ──
    "gentle": (
        "Your fix addresses the symptom at a downstream node, but the "
        "root cause is upstream. The data is already wrong before it "
        "reaches the node you modified. Look earlier in the pipeline "
        "for where the correct value was first corrupted."
    ),
    "directed": (
        "Your fix compensates for corrupted data at a downstream node. "
        "Trace the data flow backward: which node first transforms the "
        "value into the wrong form? The node that introduces the corruption "
        "is the one that should be fixed, not the nodes that consume the "
        "corrupted value. Your current fix will break on edge cases because "
        "it works around the problem instead of eliminating it."
    ),
    # ── Round 1 ──
    "first_corruption": (
        "The fix belongs at the first node where the value becomes wrong, "
        "not at any downstream consumer."
    ),
    "anti_compensation": (
        "Do not compensate for the bad value downstream; repair the "
        "transformation that originally corrupts it."
    ),
    "dataflow_backtrace": (
        "Trace the data backward from the symptom and stop at the first "
        "transformation that changes its representation incorrectly."
    ),
    "representation_purity": (
        "Preserve the canonical field itself rather than adding a parallel "
        "corrected field or patching a derived value."
    ),
    "single_node": (
        "Make the smallest possible fix by changing only the node that "
        "introduces the corruption unless another file is strictly required."
    ),
    "invariant_oriented": (
        "Choose the fix that makes both the main path and any bypass "
        "consumers see the same corrected value."
    ),
    "edge_case_anti_heuristic": (
        "If your fix depends on a special-case adjustment, hardcoded "
        "correction, or heuristic threshold, it is probably at the wrong depth."
    ),
    "upstream_only": (
        "Prefer an upstream repair even if a downstream change would make "
        "the visible output pass on the primary example."
    ),
    "corruption_node_id": (
        "Name the exact statement that first mutates the value into the "
        "wrong form, and fix that statement directly."
    ),
    # ── Group 1: Force localization ──
    "first_mutation_constraint": (
        "Identify the exact line where the value is first modified "
        "incorrectly and change only that line."
    ),
    "single_assignment_constraint": (
        "The bug originates from one incorrect assignment or transformation; "
        "fix that assignment directly."
    ),
    "no_downstream_edits": (
        "Do not modify any code that only consumes the value; only modify "
        "where the value is created or transformed."
    ),
    # ── Group 2: Force representation correctness ──
    "representation_preservation": (
        "The fix must preserve the original representation instead of "
        "reconstructing or reinterpreting it downstream."
    ),
    "round_trip_invariant": (
        "The value should remain correct if passed through the pipeline "
        "and back without additional correction logic."
    ),
    "no_derived_fix": (
        "Do not compute a corrected value from a corrupted one; fix the "
        "source of corruption instead."
    ),
    # ── Group 3: Force minimality ──
    "one_function_constraint": (
        "The correct fix modifies exactly one function; if you changed "
        "more than one, you are likely fixing symptoms."
    ),
    "one_edit_constraint": (
        "The intended fix can be expressed as a single conceptual change "
        "(e.g., one transformation rule)."
    ),
    # ── Group 4: Force causal consistency ──
    "cross_path_consistency": (
        "The corrected value must be identical for all consumers, including "
        "any bypass or alternative access paths."
    ),
    "origin_consistency": (
        "All uses of this value should reflect the same correction; do not "
        "fix only one usage site."
    ),


    # ── Ablation v4: 3-axis conditions ──
    "v4_first_corruption": (
        "The fix belongs at the first point where the value is modified "
        "incorrectly, not at any downstream consumer."
    ),
    "v4_minimality": (
        "Modify only the code necessary to fix the bug; do not change "
        "unrelated files."
    ),
    "v4_transformation_localization": (
        "The bug is a specific incorrect transformation of a value; fix "
        "that transformation directly instead of restructuring or adding "
        "new logic."
    ),
    "v4_no_refactor": (
        "This is not a refactoring task; do not reorganize or redesign "
        "the code\u2014only correct the faulty logic where it already exists."
    ),
    "v4_impl_scope": (
        "This is not a refactoring task; only correct the faulty transformation "
        "where it occurs, and do not modify unrelated files."
    ),
    "v4_location_impl": (
        "The fix belongs at the first point where the value is modified "
        "incorrectly, and it should be implemented as a direct correction "
        "of that transformation."
    ),
    "v4_location_scope_impl": (
        "The fix belongs at the first point where the value is modified "
        "incorrectly; fix that transformation directly, and do not modify "
        "unrelated files."
    ),


    # ── Plumbing hints ──
    "trace_value": (
        "Trace the value from where it is first created to where it is consumed; "
        "identify the first point where its representation becomes incorrect."
    ),
    "fix_transformation_not_consumer": (
        "If a value is transformed incorrectly at any point in the pipeline, "
        "fix that transformation rather than patching the consumer."
    ),

    # ── Ablation conditions ──
    "retry_only": "No additional guidance. Try again.",
    "c2_first_corruption": (
        "The fix belongs at the first point where the value is modified "
        "incorrectly, not at any downstream consumer."
    ),
    "c3_anti_compensation": (
        "Do not compensate for the bad value downstream; fix the "
        "transformation that originally corrupts it."
    ),
    "c4_minimality": (
        "Modify only the code necessary to fix the bug; do not change "
        "unrelated files."
    ),
    "c5_single_file": (
        "The correct fix is contained in a single file; do not modify "
        "other files."
    ),
    "c6_first_corruption_minimality": (
        "The fix belongs at the first point where the value is modified "
        "incorrectly, and you should modify only that location without "
        "changing unrelated files."
    ),
    "c7_anti_compensation_single_file": (
        "Do not compensate downstream; fix the original corruption in "
        "exactly one file and leave other files unchanged."
    ),
    "c8_no_touch": (
        "Do not modify any file unless you are certain it contains the "
        "root cause."
    ),
}


def generate_depth_hint(
    case: dict,
    spec_oracle_result: dict | None,
    level: str = "directed",
) -> str | None:
    """Generate a depth hint based on spec oracle analysis.

    Returns None if:
      - Not a DDC case
      - Spec oracle didn't run
      - LLM already passed (depth A)
    """
    if spec_oracle_result is None:
        return None
    if spec_oracle_result.get("status") != "evaluated":
        return None

    llm_depth = spec_oracle_result.get("llm_depth", {})
    depth = llm_depth.get("depth")

    if depth == "A":
        return None

    # Explicit level uses case-specific info
    if level == "explicit":
        gt = case.get("ground_truth_bug", {})
        bug_location = gt.get("location", "")
        bug_file = bug_location.split("::")[0] if "::" in bug_location else ""
        ogt = case.get("oracle_ground_truth", {})
        mechanism_source = ogt.get("mechanism_source", "")
        if bug_file and mechanism_source:
            return (
                f"Your fix is in the wrong file. The root cause is in "
                f"{bug_file}: {mechanism_source}. Fix that node directly "
                f"instead of compensating downstream."
            )

    return HINT_TEMPLATES.get(level)

