"""Oracle-grounded reasoning evaluator.

Compares model reasoning against ground-truth bug mechanism.
Returns reasoning_truth: CORRECT / PARTIAL / WRONG / UNJUDGABLE.

NO LEAKAGE: This module never sees generated code, execution results,
reconstruction status, or prior classifier outputs.

Uses the shared prompt compiler (core/prompts/components/) for template
rendering. Oracle template is selected via config.oracle.prompt_template.
"""

from pathlib import Path

_VALID_LABELS = frozenset({"CORRECT", "PARTIAL", "WRONG", "UNJUDGABLE"})


def build_oracle_spec(case: dict) -> dict:
    """Extract oracle fields from a case dict.

    Reads from oracle_ground_truth (enriched schema) first,
    falls back to ground_truth_bug (legacy schema).
    """
    ogt = case.get("oracle_ground_truth", {})
    if ogt:
        return {
            "bug_type": ogt.get("bug_type", ""),
            "bug_location": ogt.get("bug_location", ""),
            "mechanism_source": ogt.get("mechanism_source", ""),
            "mechanism_property": ogt.get("mechanism_property", ""),
            "mechanism_steps": ogt.get("mechanism_steps", []),
            "mechanism_outcome": ogt.get("mechanism_outcome", ""),
            "trap_description": ogt.get("trap_description") or "No trap",
            "task": case.get("task", ""),
        }
    # Legacy fallback
    gt = case.get("ground_truth_bug", {})
    return {
        "bug_type": gt.get("type", ""),
        "bug_location": gt.get("location", ""),
        "mechanism_source": case.get("description", ""),
        "mechanism_property": gt.get("invariant", ""),
        "mechanism_steps": [case.get("description", "")],
        "mechanism_outcome": case.get("description", ""),
        "trap_description": case.get("trap", "No trap"),
        "task": case.get("task", ""),
    }


def load_buggy_code(case: dict, project_root: str) -> str:
    """Read and join original buggy code files for a case."""
    parts = []
    for rel_path in case.get("code_files", []):
        fp = Path(project_root) / "case_data" / rel_path
        if not fp.exists():
            fp = Path(project_root) / rel_path
        if fp.exists():
            parts.append(f"# {rel_path}\n{fp.read_text().strip()}")
    return "\n\n".join(parts)


def render_prompt(oracle: dict, root_cause: str,
                  fix_strategy: str, buggy_code: str,
                  template_name: str = "oracle_reasoning_truth") -> str:
    """Render the evaluator prompt via the shared prompt compiler.

    No generated code allowed. Template selected by name from
    core/prompts/components/.
    """
    from core.pipeline.orchestration.execution_v2 import _compile_prompt_from_components

    # Pre-render mechanism_steps list into a string — compiler forbids {% for %}
    steps = oracle.get("mechanism_steps", [])
    steps_text = "\n".join(f"* {step}" for step in steps) if steps else "* (not specified)"

    variables = {
        "task": oracle["task"],
        "buggy_code": buggy_code,
        "bug_type": oracle["bug_type"],
        "bug_location": oracle["bug_location"],
        "mechanism_source": oracle.get("mechanism_source", ""),
        "mechanism_property": oracle.get("mechanism_property", ""),
        "mechanism_steps": steps_text,
        "mechanism_outcome": oracle.get("mechanism_outcome", ""),
        "trap_description": oracle.get("trap_description", "No trap"),
        "root_cause": root_cause or "[MISSING]",
        "fix_strategy": fix_strategy or "[MISSING]",
    }

    result = _compile_prompt_from_components((template_name,), variables)
    return result.final_prompt


def parse_response(raw: str) -> tuple[str, str, str | None]:
    """Parse evaluator response into (label, justification, error).

    Returns (label, justification, None) on success.
    Returns ("UNJUDGABLE", "", error_msg) on failure.
    """
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    if len(lines) < 1:
        return "UNJUDGABLE", "", "empty_response"

    label = lines[0].upper().strip()
    if label not in _VALID_LABELS:
        return "UNJUDGABLE", raw, f"invalid_label:{lines[0]}"

    justification = lines[1] if len(lines) > 1 else ""
    return label, justification, None


def is_unjudgable(root_cause: str, fix_strategy: str) -> bool:
    """Pre-filter: skip evaluator call if reasoning is missing."""
    rc = (root_cause or "").strip()
    fs = (fix_strategy or "").strip()
    if not rc and not fs:
        return True
    if len(rc) + len(fs) < 20:
        return True
    return False
