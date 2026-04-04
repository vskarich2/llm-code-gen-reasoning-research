"""Per-case reference panels for the Family Breakdown tab.

Renders each benchmark case as a collapsible expander showing:
- buggy code, fixed code, what changed, common failures.
All loaded dynamically from case_data/.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from dashboard.family_docs import FAMILY_NARRATIVES

_CASES_PATH = Path("case_data/cases_v2.json")
_SNIPPETS_ROOT = Path("case_data/code_snippets_v2")
_FIXES_ROOT = Path("case_data/reference_fixes")


def _load_cases() -> list[dict[str, Any]]:
    if not _CASES_PATH.exists():
        return []
    return json.loads(_CASES_PATH.read_text(encoding="utf-8"))


def _read_file(path: str | Path) -> str:
    p = Path(path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def _extract_function(source: str, func_name: str) -> str:
    """Extract a single function from source code by name."""
    lines = source.split("\n")
    start = None
    start_indent = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"def {func_name}(") or stripped.startswith(f"def {func_name} ("):
            start = i
            start_indent = len(line) - len(stripped)
            break
    if start is None:
        return ""
    # Collect until next def/class at same or lesser indent, or end
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= start_indent:
            stripped = line.lstrip()
            if stripped.startswith(("def ", "class ", "@")):
                end = i
                break
    # Trim trailing blank lines
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end])


def _extract_module_level(source: str) -> str:
    """Extract module-level code (assignments, constants) before functions."""
    lines = source.split("\n")
    end = len(lines)
    for i, line in enumerate(lines):
        if line.startswith("def ") or line.startswith("class "):
            end = i
            break
    result = "\n".join(lines[:end]).strip()
    return result if result else ""


def render_case_reference_panels() -> None:
    """Render collapsible per-case reference panels."""
    cases = _load_cases()
    if not cases:
        st.caption("No case data found.")
        return

    st.markdown("---")
    st.markdown("##### Case Reference (buggy code, fix, failure modes)")

    # Group by family
    families: dict[str, list[dict]] = {}
    for c in cases:
        fam = c["family"]
        families.setdefault(fam, []).append(c)

    for fam in sorted(families):
        fam_cases = sorted(families[fam], key=lambda x: x["difficulty"])
        narrative = FAMILY_NARRATIVES.get(fam, "")
        for case in fam_cases:
            _render_single_case(case, narrative)


def _render_single_case(case: dict[str, Any], narrative: str = "") -> None:
    """Render one case as a collapsible expander."""
    cid = case["id"]
    diff = case["difficulty"]
    desc = case.get("description", "")
    trap = case.get("trap", "")
    gt = case.get("ground_truth_bug", {})
    ref = case.get("reference_fix", {})
    invariant = gt.get("invariant", "")
    fix_pattern = gt.get("fix_pattern", "")
    bug_location = gt.get("location", "")
    ref_file = ref.get("file", "")
    ref_func = ref.get("function", "")
    ref_diff = ref.get("diff_summary", "")
    code_files = case.get("code_files", [])
    family = case.get("family", "")
    failure_mode = case.get("failure_mode", "")
    task = case.get("task", "")
    causal_depth = case.get("causal_depth", "")
    boundary = case.get("boundary_type", "")

    label = cid

    with st.expander(label, expanded=False):
        # ── Family narrative ──
        if narrative:
            st.markdown(f"**Family `{family}`** — {failure_mode}")
            st.markdown(narrative)
            st.markdown("---")

        # ── Case description ──
        st.markdown(f"**Description:** {desc}")
        st.markdown(f"**Task given to model:** *{task}*")

        # ── Metadata ──
        cols = st.columns(4)
        cols[0].markdown(f"**Difficulty:** {diff}")
        cols[1].markdown(f"**Bug location:** `{bug_location}`")
        cols[2].markdown(f"**Causal depth:** {causal_depth}")
        cols[3].markdown(f"**Boundary:** {boundary}")

        st.markdown(f"**Invariant:** {invariant}")
        if trap and trap != "No trap":
            st.warning(f"**Trap:** {trap}")

        # ── Buggy code ──
        if ref_file:
            buggy_path = Path("case_data") / ref_file if not Path(ref_file).exists() else Path(ref_file)
            buggy_source = _read_file(buggy_path)
            if buggy_source and ref_func:
                buggy_fn = _extract_function(buggy_source, ref_func)
                if buggy_fn:
                    st.markdown("**Buggy code:**")
                    st.code(buggy_fn, language="python")
                elif bug_location and "DEFAULTS" in bug_location.upper() or "timeout" in fix_pattern.lower():
                    # Module-level bug (e.g., config_shadowing)
                    mod_level = _extract_module_level(buggy_source)
                    if mod_level:
                        st.markdown("**Buggy code (module level):**")
                        st.code(mod_level, language="python")

        # ── Fixed code ──
        fix_path = _FIXES_ROOT / f"{cid}.py"
        fix_source = _read_file(fix_path)
        if fix_source and ref_func:
            fixed_fn = _extract_function(fix_source, ref_func)
            if fixed_fn:
                st.markdown("**Fixed code:**")
                st.code(fixed_fn, language="python")
            elif fix_source.strip():
                # Module-level fix
                mod_level = _extract_module_level(fix_source)
                if mod_level:
                    st.markdown("**Fixed code (module level):**")
                    st.code(mod_level, language="python")

        # ── Steps to fix ──
        st.markdown("**Steps to fix:**")
        steps = []
        if len(code_files) > 1:
            steps.append(
                f"Identify the bug in `{bug_location}` "
                f"(not in the {len(code_files) - 1} other file(s))"
            )
        if fix_pattern:
            steps.append(f"Apply fix: `{fix_pattern}`")
        if ref_diff:
            steps.append(f"Change: {ref_diff}")
        if invariant:
            steps.append(f"Verify invariant holds: {invariant}")
        for i, step in enumerate(steps, 1):
            st.markdown(f"{i}. {step}")

        # ── Common model failures ──
        if trap and trap != "No trap":
            st.markdown("**Common model failures:**")
            st.markdown(
                f"- Models often fall for the trap: *{trap}*"
            )
            if diff == "B":
                st.markdown(
                    "- At B difficulty, models fix the wrong function "
                    "or get distracted by the cross-function indirection."
                )
            elif diff == "C":
                st.markdown(
                    "- At C difficulty, the bug spans multiple files. "
                    "Models often fix a downstream symptom instead of "
                    "the root cause, or apply partial fixes that pass "
                    "some checks but not the invariant."
                )
            elif diff == "L3":
                st.markdown(
                    "- At L3 difficulty, the causal chain is non-obvious. "
                    "Models restore one step but miss that multiple steps "
                    "form a dependency chain where all are required."
                )

        # ── All case files (full contents) ──
        if code_files:
            st.markdown(f"**All case files ({len(code_files)}):**")
            for cf in code_files:
                cf_path = Path("case_data") / cf if not Path(cf).exists() else Path(cf)
                fname = Path(cf).name
                is_fix_file = (cf == ref_file)
                tag = " **(contains bug)**" if is_fix_file else ""
                file_source = _read_file(cf_path)
                if file_source:
                    with st.expander(f"{fname}{tag}", expanded=False):
                        st.code(file_source, language="python")
                else:
                    st.caption(f"{fname}: file not found")
