"""Reasoning interface prompt builders.

Three reasoning modes:
  structured_reasoning — step-by-step with labeled sections (current baseline style)
  free_form_reasoning  — no structure imposed, just "think and produce code"
  branching_reasoning  — Tree-of-Thought-lite: consider 2 approaches, pick best
"""


def build_structured_reasoning(base: str) -> str:
    """Structured step-by-step: identify deps → check invariants → write code."""
    return base + """

Follow these steps in order:

Step 1: Identify all dependencies and shared state across files.
Step 2: List any invariants that must be preserved (ordering, conservation, gates).
Step 3: For each change you plan to make, verify it does not break any invariant.
Step 4: Write the refactored code.
"""


def build_free_form_reasoning(base: str) -> str:
    """No structure — just ask for reasoning + code."""
    return base + """

Think carefully about this code before making changes, then return the updated code.
"""


def build_branching_reasoning(base: str) -> str:
    """Tree-of-Thought-lite: consider two approaches, evaluate each, pick one."""
    return base + """

Before writing code, consider TWO different approaches to this refactoring:

APPROACH A:
- Describe approach A briefly
- What would change?
- What could break?

APPROACH B:
- Describe approach B briefly
- What would change?
- What could break?

EVALUATION:
- Which approach preserves all existing behavior?
- Which approach risks breaking downstream consumers?

Pick the safer approach and write the code.
"""
