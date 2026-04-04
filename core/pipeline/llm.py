# ============================================================
# LLM call wrapper — real API with mock fallback
#
# ALL parameters come from experiment_config. No hardcoded values.
# ============================================================

import logging
import os
from dataclasses import dataclass

_llm_log = logging.getLogger("t3.llm")
_mock_warning_emitted = False


@dataclass(frozen=True)
class ModelCallResult:
    """Structured return from call_model. event_id is always set."""
    response: str
    event_id: int | str


def _is_anthropic_model(model: str) -> bool:
    """Return True if model name indicates an Anthropic Claude model."""
    return model.startswith("claude-")

# ALL OUTPUT INSTRUCTIONS DELETED — now in prompts/components/output_instruction_v1.j2 and v2.j2
# Access via: assembly_engine.build(["output_instruction_v1"], {}) or ["output_instruction_v2"]


def _get_model_spec(model_name: str):
    """Get model parameters from config. Crashes if config unavailable."""
    from core.config.experiment_config import get_config
    config = get_config()
    try:
        spec = config.get_generation_model(model_name)
        return spec.temperature, spec.top_p
    except ValueError:
        if model_name == config.models.evaluator.name:
            return config.models.evaluator.temperature, 1.0
        raise ValueError(
            f"Model '{model_name}' not found in generation models or evaluator"
        )


def call_model(
    prompt: str, model: str, raw: bool = False, file_paths: list[str] | None = None,
    logger=None, case_id: str | None = None,
    phase: str = "generation", condition: str | None = None,
    prompt_assembly: dict | None = None,
    parent_event_id: int | str | None = None,
) -> ModelCallResult:
    """Call an LLM. Falls back to mock if no API key is set.

    Returns ModelCallResult with .response and .event_id.
    event_id is None if no logger was provided.
    """
    import time as _time

    is_anthropic = _is_anthropic_model(model)
    if is_anthropic:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
    full_prompt = prompt

    if not api_key or api_key == "sk-dummy":
        global _mock_warning_emitted
        if not _mock_warning_emitted:
            _llm_log.warning(
                "MOCK MODE ACTIVE: No valid OPENAI_API_KEY. "
                "All model calls use llm_mock. Results are NOT from a real model."
            )
            _mock_warning_emitted = True
        from core.pipeline.llm_mock import mock_call

        t0 = _time.monotonic()
        result = mock_call(full_prompt)
        elapsed = _time.monotonic() - t0
        eid = _log_call_if_logger(logger, model, full_prompt, result, elapsed, None,
                                  case_id, phase, condition, prompt_assembly, parent_event_id)
        return ModelCallResult(response=result, event_id=eid)

    _llm_log.debug("API_CALL_START model=%s prompt_len=%d raw=%s", model, len(full_prompt), raw)
    t0 = _time.monotonic()
    try:
        if is_anthropic:
            result = _anthropic_call(full_prompt, model, api_key)
        else:
            result = _openai_call(full_prompt, model, api_key)
    except Exception as e:
        elapsed = _time.monotonic() - t0
        _log_call_if_logger(logger, model, full_prompt, "", elapsed, str(e),
                            case_id, phase, condition, prompt_assembly, parent_event_id)
        raise
    elapsed = _time.monotonic() - t0
    _llm_log.debug(
        "API_CALL_END model=%s elapsed=%.1fs response_len=%d", model, elapsed, len(result)
    )
    eid = _log_call_if_logger(logger, model, full_prompt, result, elapsed, None,
                              case_id, phase, condition, prompt_assembly, parent_event_id)
    return ModelCallResult(response=result, event_id=eid)


def _log_call_if_logger(
    logger, model: str, prompt: str, response: str, elapsed: float,
    error: str | None, case_id: str | None, phase: str,
    condition: str | None, prompt_assembly: dict | None,
    parent_event_id: int | str | None,
) -> int | str | None:
    """Log call via explicit logger. Returns event_id, or None if no logger.

    Call logging failure raises — silent logging failure is prohibited.
    """
    if logger is None:
        return None
    return logger.log_call(
        model=model,
        prompt=prompt,
        response=response,
        elapsed_seconds=elapsed,
        case_id=case_id or "unknown",
        phase=phase,
        parent_event_id=parent_event_id or 0,
        condition=condition,
        error=error,
        prompt_assembly=prompt_assembly,
    )


def _openai_call(prompt: str, model: str, api_key: str) -> str:
    """Real OpenAI API call with config-driven settings."""
    from openai import OpenAI

    temperature, top_p = _get_model_spec(model)

    client = OpenAI(api_key=api_key)
    kwargs = dict(model=model, input=prompt, store=False)
    # Some models don't support temperature
    from core.config.experiment_config import get_config
    no_temp = get_config().models.no_temperature_prefixes
    if not any(model.startswith(p) for p in no_temp):
        kwargs["temperature"] = temperature
    response = client.responses.create(**kwargs)
    return response.output_text


def _anthropic_call(prompt: str, model: str, api_key: str) -> str:
    """Anthropic Claude API call with config-driven settings."""
    import anthropic

    temperature, _top_p = _get_model_spec(model)
    max_tokens = _get_anthropic_max_tokens(model)

    from core.config.experiment_config import get_config
    client = anthropic.Anthropic(
        api_key=api_key,
        timeout=get_config().execution.anthropic_client_timeout,
    )
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return message.content[0].text


def _get_anthropic_max_tokens(model: str) -> int:
    """Get max output tokens for Anthropic models from config."""
    from core.config.experiment_config import get_config
    config = get_config()
    cap = config.execution.anthropic_max_output_tokens
    try:
        spec = config.get_generation_model(model)
        return min(spec.max_tokens, cap)
    except ValueError:
        return cap
