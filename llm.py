# ============================================================
# LLM call wrapper — real API with mock fallback
#
# ALL parameters come from experiment_config. No hardcoded values.
# ============================================================

import logging
import os

_llm_log = logging.getLogger("t3.llm")
_mock_warning_emitted = False

# V1 output instruction (legacy — single code blob)
_JSON_OUTPUT_INSTRUCTION_V1 = """

Return your response as a single valid JSON object with this exact schema:

{"reasoning": "<your explanation>", "plan": ["<step 1>", "<step 2>"], "code": "<your complete fixed code>"}

ALL THREE fields are REQUIRED and must be non-null strings (or list of strings for plan):
- "reasoning" MUST be a non-null string explaining your analysis. NEVER set it to null.
- "plan" MUST be a non-empty list of strings, one step per element.
- "code" MUST be a non-null string containing the complete fixed source code.

Rules:
- Do NOT include markdown (no ```python blocks)
- Do NOT include text outside the JSON
- Do NOT set any field to null
- Return ONLY the JSON object, nothing else"""

# V2 output instruction (file-dict format with UNCHANGED sentinel)
_JSON_OUTPUT_INSTRUCTION_V2_TEMPLATE = """

Return your response as a single valid JSON object with this schema:

{{"reasoning": "<your analysis of the bug and fix>", "files": {{{file_entries}}}}}

RULES:
- "reasoning" MUST be a non-empty string explaining your analysis.
- "files" MUST contain one entry for EVERY file listed above.
- For files you did NOT modify, set the value to the exact string "UNCHANGED".
- For files you DID modify, include the COMPLETE updated file contents.
- Do NOT include markdown formatting inside file values.
- Do NOT omit any file from the "files" object.
- Return ONLY the JSON object, nothing else."""


def _build_json_output_instruction_v2(file_paths: list[str] | None = None) -> str:
    """Build V2 output instruction with file entries matching the prompt."""
    if not file_paths:
        return _JSON_OUTPUT_INSTRUCTION_V1
    entries = ", ".join(f'"{p}": "<complete file contents or UNCHANGED>"' for p in file_paths)
    return _JSON_OUTPUT_INSTRUCTION_V2_TEMPLATE.format(file_entries=entries)


def _get_output_format() -> str:
    """Get output format from config. Returns 'v1' or 'v2'."""
    try:
        from experiment_config import get_config
        return get_config().execution.output_format
    except (RuntimeError, ImportError):
        return "v1"  # config not loaded yet (e.g. during import)


def _get_model_spec(model_name: str):
    """Get model parameters from config. Returns (temperature, top_p) or defaults."""
    try:
        from experiment_config import get_config
        config = get_config()
        spec = config.get_generation_model(model_name)
        return spec.temperature, spec.top_p
    except (RuntimeError, ImportError, ValueError):
        # Config not loaded or model not in generation list (e.g. evaluator model)
        # Fall back to evaluator config
        try:
            from experiment_config import get_config
            config = get_config()
            if model_name == config.models.evaluator.name:
                return config.models.evaluator.temperature, 1.0
        except Exception:
            pass
        return 0.0, 1.0


def call_model(prompt: str, model: str, raw: bool = False,
               file_paths: list[str] | None = None) -> str:
    """Call an LLM. Falls back to mock if no API key is set.

    Args:
        model: Model name. MUST be provided by caller (from config).
        raw: If True, send prompt as-is without appending JSON output instruction.
        file_paths: If provided and output_format is v2, use V2 file-dict instruction.
    """
    import time as _time
    api_key = os.environ.get("OPENAI_API_KEY")

    output_fmt = _get_output_format()
    if raw:
        full_prompt = prompt
    elif output_fmt == "v2" and file_paths:
        full_prompt = prompt + _build_json_output_instruction_v2(file_paths)
    else:
        full_prompt = prompt + _JSON_OUTPUT_INSTRUCTION_V1

    if not api_key or api_key == "sk-dummy":
        global _mock_warning_emitted
        if not _mock_warning_emitted:
            _llm_log.warning(
                "MOCK MODE ACTIVE: No valid OPENAI_API_KEY. "
                "All model calls use llm_mock. Results are NOT from a real model."
            )
            _mock_warning_emitted = True
        from llm_mock import mock_call
        return mock_call(full_prompt)

    _llm_log.debug("API_CALL_START model=%s prompt_len=%d raw=%s",
                    model, len(full_prompt), raw)
    t0 = _time.monotonic()
    result = _openai_call(full_prompt, model, api_key)
    elapsed = _time.monotonic() - t0
    _llm_log.debug("API_CALL_END model=%s elapsed=%.1fs response_len=%d",
                    model, elapsed, len(result))
    return result


def get_model_config() -> dict:
    """Return the model config for logging. Reads from experiment config."""
    try:
        from experiment_config import get_config
        config = get_config()
        return {
            "temperature": config.models.generation[0].temperature if config.models.generation else 0.0,
            "top_p": config.models.generation[0].top_p if config.models.generation else 1.0,
            "output_format": config.execution.output_format,
        }
    except (RuntimeError, ImportError):
        return {"temperature": 0.0, "top_p": 1.0, "output_format": "v1"}


def _openai_call(prompt: str, model: str, api_key: str) -> str:
    """Real OpenAI API call with config-driven settings."""
    from openai import OpenAI

    temperature, top_p = _get_model_spec(model)

    client = OpenAI(api_key=api_key)
    kwargs = dict(model=model, input=prompt, store=False)
    # Some models don't support temperature
    try:
        from experiment_config import get_config
        no_temp = get_config().models.no_temperature_prefixes
    except (RuntimeError, ImportError):
        no_temp = ("o1", "o3", "o4", "gpt-5")
    if not any(model.startswith(p) for p in no_temp):
        kwargs["temperature"] = temperature
    response = client.responses.create(**kwargs)
    return response.output_text
