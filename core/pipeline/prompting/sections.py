"""Typed structural section system.

Closed vocabulary. Every component declares which sections it emits.
The compiler validates rendered output against declarations.
Adding a new section requires adding to the enum.
"""

from enum import Enum


class Section(str, Enum):
    """Valid structural sections for prompt composition."""

    TASK_CONTEXT = "task_context"
    CODE_CONTEXT = "code_context"
    REASONING_INSTRUCTION = "reasoning_instruction"
    OUTPUT_INSTRUCTION = "output_instruction"
    NUDGE_DIAGNOSTIC = "nudge_diagnostic"
    NUDGE_REASONING = "nudge_reasoning"
    NUDGE_SCM = "nudge_scm"
    SAFETY_INSTRUCTION = "safety_instruction"
    RETRY_FEEDBACK = "retry_feedback"
    CRITIQUE_INSTRUCTION = "critique_instruction"
    EVALUATION_INSTRUCTION = "evaluation_instruction"
    EVALUATION_RUBRIC = "evaluation_rubric"
    BUG_CONTEXT = "bug_context"
    CGE_INSTRUCTION = "cge_instruction"


# Sections that may appear at most once per program (default).
# All sections are singleton unless the program declares allow_multi_emit.
SINGLETON_SECTIONS: frozenset[Section] = frozenset({
    Section.TASK_CONTEXT,
    Section.CODE_CONTEXT,
    Section.OUTPUT_INSTRUCTION,
    Section.EVALUATION_INSTRUCTION,
})

# All valid section values for fast lookup
VALID_SECTION_VALUES: frozenset[str] = frozenset(s.value for s in Section)
