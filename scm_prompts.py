"""SCM prompt builders for T3 experimental conditions.

Generates prompts from SCM evidence data. Does NOT modify evaluation.
"""

from scm_data import get_scm


def build_scm_descriptive(base: str, case_id: str) -> str:
    """SCM structure presented informationally — no enforcement."""
    scm = get_scm(case_id)
    if not scm:
        return base

    edges_text = "\n".join(f"  {eid}: {desc}" for eid, desc in scm["edges"].items())
    interventions = scm.get("critical_constraint", {})
    failure = interventions.get("failure_trace", "")

    return base + f"""

The following causal dependencies exist in this code:

Dependencies:
{edges_text}

Known breaking change:
{failure}

Use this information to guide your refactoring.
"""


def build_scm_constrained(base: str, case_id: str) -> str:
    """SCM + forced 4-step verification."""
    scm = get_scm(case_id)
    if not scm:
        return base

    edges_text = "\n".join(f"  {eid}: {desc}" for eid, desc in scm["edges"].items())
    constraints_text = "\n".join(
        f"  {cid}: {c['text']}\n    → protects: {', '.join(c['invariants'])}"
        for cid, c in scm["constraints"].items()
    )
    invariants_text = "\n".join(f"  {iid}: {desc}" for iid, desc in scm["invariants"].items())

    return base + f"""

CAUSAL DEPENDENCY ANALYSIS — you MUST complete all steps before writing code.

STEP 1 — DEPENDENCIES:
{edges_text}

STEP 2 — CONSTRAINTS:
{constraints_text}

STEP 3 — INVARIANTS:
{invariants_text}

STEP 4 — For EACH change you propose, verify all constraints still hold.
If ANY constraint is violated, do NOT make that change.

Write your refactored code only after completing all steps.
"""


def build_scm_constrained_evidence(base: str, case_id: str) -> str:
    """Full SCM + evidence IDs + critical constraint analysis + post-check."""
    scm = get_scm(case_id)
    if not scm:
        return base

    funcs_text = "\n".join(f"  {fid} = {desc}" for fid, desc in scm["functions"].items())
    vars_text = "\n".join(f"  {vid} = {desc}" for vid, desc in scm["variables"].items())
    edges_text = "\n".join(f"  {eid}: {desc}" for eid, desc in scm["edges"].items())
    invariants_text = "\n".join(f"  {iid}: {desc}" for iid, desc in scm["invariants"].items())
    constraints_text = "\n".join(
        f"  {cid}: {c['text']}\n    → protects: {', '.join(c['invariants'])}"
        for cid, c in scm["constraints"].items()
    )

    cc = scm.get("critical_constraint", {})
    cc_id = cc.get("id", "?")
    cc_why = cc.get("why_fragile", "")
    cc_trace = cc.get("failure_trace", "")

    inv_checks = "\n".join(
        f"  {iid}: Does this still hold? Verified by which F*, E*?"
        for iid in scm["invariants"]
    )

    return base + f"""

EVIDENCE-GROUNDED CAUSAL ANALYSIS — you MUST use the IDs below.

STEP 1 — FUNCTIONS AND STATE:
{funcs_text}
{vars_text}

STEP 2 — DEPENDENCIES (cite E* IDs):
{edges_text}

STEP 3 — INVARIANTS (cite I* IDs):
{invariants_text}

STEP 3.5 — CRITICAL CONSTRAINT ANALYSIS:

The most fragile constraint is {cc_id}:
Why fragile: {cc_why}
Failure trace: {cc_trace}

STEP 4 — CONSTRAINTS (cite C* IDs):
{constraints_text}

For EACH proposed change, state:
  Change: [describe]
  Functions affected: [F*]
  Edges affected: [E*]
  Constraints: [C*]
  Invariants at risk: [I*]

STEP 5 — WRITE CODE

STEP 6 — POST-CHECK (cite I* and C*):
{inv_checks}

RULES:
- You MUST cite IDs when making claims
- Every ID must be from the list above — do not invent new IDs
- If you cannot satisfy all constraints, keep the original code unchanged
"""


def build_scm_constrained_evidence_minimal(base: str, case_id: str) -> str:
    """Critical evidence set only — top 2-3 edges, 1-2 invariants."""
    scm = get_scm(case_id)
    if not scm:
        return base

    ces = scm.get("critical_evidence_set", {})
    funcs = ces.get("functions", [])
    edges = ces.get("edges", [])
    invariants = ces.get("invariants", [])
    constraints = ces.get("constraints", [])

    f_text = "\n".join(f"  {f} = {scm['functions'].get(f, '?')}" for f in funcs)
    e_text = "\n".join(f"  {e}: {scm['edges'].get(e, '?')}" for e in edges)
    i_text = "\n".join(f"  {i}: {scm['invariants'].get(i, '?')}" for i in invariants)
    c_text = "\n".join(f"  {c}: {scm['constraints'].get(c, {}).get('text', '?')}" for c in constraints)

    return base + f"""

CRITICAL DEPENDENCIES — you must preserve these.

{e_text}

Key constraint:
{c_text}

Invariant to protect:
{i_text}

For each change, cite which of these IDs are affected.
After writing code, verify each invariant still holds.
"""


def build_evidence_only(base: str, case_id: str) -> str:
    """Evidence IDs + constraints + invariants, NO edge list."""
    scm = get_scm(case_id)
    if not scm:
        return base

    funcs_text = "\n".join(f"  {fid} = {desc}" for fid, desc in scm["functions"].items())
    vars_text = "\n".join(f"  {vid} = {desc}" for vid, desc in scm["variables"].items())
    constraints_text = "\n".join(
        f"  {cid}: {c['text']}" for cid, c in scm["constraints"].items()
    )
    invariants_text = "\n".join(f"  {iid}: {desc}" for iid, desc in scm["invariants"].items())

    return base + f"""

Evidence catalog (NOTE: no dependency graph provided — determine relationships yourself):

Functions:
{funcs_text}
State:
{vars_text}
Constraints:
{constraints_text}
Invariants:
{invariants_text}

For each change, cite which F*, C*, I* are affected.
After writing code, verify each invariant still holds.
"""


def build_length_matched_control(base: str, case_id: str) -> str:
    """Same token count as scm_constrained_evidence, NO causal info."""
    return base + """

Additional context for this refactoring task:

This codebase handles data management across multiple modules with different
responsibilities. The system supports both real-time operations and batch
processing workflows. Some functions handle persistence while others manage
in-memory state for fast access. Multiple helper functions exist for different
access patterns throughout the codebase. The system must handle various update
patterns and maintain consistency across all access paths. Some functions appear
similar in purpose but serve different operational contexts. Consider the
interaction patterns between modules when making changes to code structure.
Background processes may access shared state differently from foreground
request handlers. Each module has specific responsibilities that should be
preserved during refactoring. Helper functions may have subtle behavioral
differences despite similar naming conventions.

Return the updated code.
"""
