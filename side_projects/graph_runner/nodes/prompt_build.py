"""PromptBuildNode — compile the generation prompt from case + condition.

Wraps the prompt compiler. Handles retry_context for attempt 1+ prompts.
Pure node: no side effects.
"""

from __future__ import annotations

from typing import Any

from side_projects.graph_runner.constants import (
    CASE_FIELD_LOGICAL_FILE_KEYS,
    KEY_CASE,
    KEY_CONDITION,
    KEY_CONFIG,
    KEY_PROMPT,
    KEY_PROMPT_META,
    KEY_RETRY_CONTEXT,
    NODE_TYPE_PURE,
)
from side_projects.graph_runner.node_interface import BaseNode, NodeResult


class PromptBuildNode(BaseNode):
    NAME = "PromptBuildNode"
    INPUT_KEYS = frozenset({
        KEY_CASE, KEY_CONDITION, KEY_CONFIG, KEY_RETRY_CONTEXT,
    })
    OUTPUT_KEYS = frozenset({KEY_PROMPT, KEY_PROMPT_META})
    NODE_TYPE = NODE_TYPE_PURE

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        case = inputs[KEY_CASE]
        condition = inputs[KEY_CONDITION]
        config = inputs[KEY_CONFIG]
        retry_ctx = inputs[KEY_RETRY_CONTEXT]

        if retry_ctx is not None:
            prompt, prompt_meta = self.build_retry_prompt(
                case, condition, config, retry_ctx,
            )
        else:
            prompt, prompt_meta = self.build_fresh_prompt(
                case, condition, config,
            )

        return NodeResult(outputs={
            KEY_PROMPT: prompt,
            KEY_PROMPT_META: prompt_meta,
        })

    def build_fresh_prompt(
        self, case: dict, condition: str, config: Any,
    ) -> tuple[str, dict]:
        """Build attempt-0 generation prompt via the V2 compiler."""
        from core.pipeline.orchestration.execution_v2 import (
            _render_generation_prompt,
        )
        return _render_generation_prompt(case, condition, config)

    def build_retry_prompt(
        self, case: dict, condition: str, config: Any,
        retry_ctx: dict,
    ) -> tuple[str, dict]:
        """Build attempt-1+ retry prompt from retry_context fields.

        Uses the same compiler path but with retry-specific templates.
        Falls back to fresh prompt if retry_context has no useful content.
        """
        from core.pipeline.orchestration.execution_v2 import (
            _render_generation_prompt, _compile_prompt_from_components,
        )
        import hashlib as hl
        import json as j

        code_files = case.get(CASE_FIELD_LOGICAL_FILE_KEYS, {})
        file_paths = list(code_files.keys())
        file_keys_example = ", ".join(
            f'"{p}": "<complete file contents or UNCHANGED>"'
            for p in file_paths
        )
        schema_line = (
            '{"root_cause": "<...>", "fix_strategy": "<...>", '
            '"files": {' + file_keys_example + '}}'
        )

        prev_raw = retry_ctx.get("prev_raw", "")
        depth_hint = retry_ctx.get("depth_hint")
        critique_text = retry_ctx.get("critique_text", "")

        effective_critique = depth_hint if depth_hint else critique_text

        if effective_critique or "critique" in condition:
            compiled = _compile_prompt_from_components(
                ("critique_retry",),
                {
                    "prev_raw": prev_raw,
                    "mismatch_critique": effective_critique or "",
                    "schema_line": schema_line,
                },
            )
            prompt = compiled.final_prompt
        else:
            prompt, _ = _render_generation_prompt(case, condition, config)

        prompt_meta = {
            "prompt_family": condition,
            "prompt_name": "retry",
            "prompt_hash": hl.sha256(prompt.encode()).hexdigest()[:16],
            "retry_attempt": retry_ctx.get("attempt_index", 1),
        }

        return prompt, prompt_meta
