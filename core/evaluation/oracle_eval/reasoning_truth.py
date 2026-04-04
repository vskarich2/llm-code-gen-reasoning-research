"""Oracle-grounded reasoning evaluator.

Compares model reasoning against ground-truth bug mechanism.
Returns reasoning_truth: CORRECT / PARTIAL / WRONG / UNJUDGABLE.

NO LEAKAGE: This module never sees generated code, execution results,
reconstruction status, or prior classifier outputs.
"""

from pathlib import Path

import jinja2

_TEMPLATE_PATH = Path(__file__).parent / "reasoning_truth_prompt.j2"
_TEMPLATE = None
_VALID_LABELS = frozenset({"CORRECT", "PARTIAL", "WRONG", "UNJUDGABLE"})


def _get_template():
    global _TEMPLATE
    if _TEMPLATE is None:
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATE_PATH.parent)),
            undefined=jinja2.StrictUndefined)
        _TEMPLATE = env.get_template(_TEMPLATE_PATH.name)
    return _TEMPLATE


def build_oracle_spec(case: dict) -> dict:
    """Extract oracle fields from a case dict."""
    gt = case.get("ground_truth_bug", {})
    return {
        "bug_type": gt.get("type", ""),
        "bug_location": gt.get("location", ""),
        "invariant": gt.get("invariant", ""),
        "fix_pattern": gt.get("fix_pattern", ""),
        "mechanism_description": case.get("description", ""),
        "trap_description": case.get("trap", "No trap"),
        "task": case.get("task", ""),
    }


def load_buggy_code(case: dict, project_root: str) -> str:
    """Read and join original buggy code files for a case."""
    parts = []
    for rel_path in case.get("code_files", []):
        fp = Path(project_root) / rel_path
        if fp.exists():
            parts.append(f"# {rel_path}\n{fp.read_text().strip()}")
    return "\n\n".join(parts)


def render_prompt(oracle: dict, root_cause: str,
                  fix_strategy: str, buggy_code: str) -> str:
    """Render the evaluator prompt. No generated code allowed."""
    tmpl = _get_template()
    return tmpl.render(
        task=oracle["task"],
        buggy_code=buggy_code,
        bug_type=oracle["bug_type"],
        bug_location=oracle["bug_location"],
        invariant=oracle["invariant"],
        fix_pattern=oracle["fix_pattern"],
        mechanism_description=oracle["mechanism_description"],
        trap_description=oracle["trap_description"],
        root_cause=root_cause or "[MISSING]",
        fix_strategy=fix_strategy or "[MISSING]",
    )


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
