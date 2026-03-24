# ============================================================
# LLM call wrapper — real API with mock fallback
#
# Determinism: temperature=0.0, top_p=1.0 for all calls.
# ============================================================

import logging
import os

_llm_log = logging.getLogger("t3.llm")
_mock_warning_emitted = False

# Determinism config — used for all model calls
MODEL_CONFIG = {
    "temperature": 0.0,
    "top_p": 1.0,
}

# Suffix appended to all prompts requesting structured output
_JSON_OUTPUT_INSTRUCTION = """

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


def call_model(prompt: str, model: str = "gpt-4.1-nano", raw: bool = False) -> str:
    """Call an LLM. Falls back to mock if no API key is set.

    Args:
        raw: If True, send prompt as-is without appending JSON output instruction.
             Used by contract elicitation which has its own output format.
    """
    import threading, time as _time
    api_key = os.environ.get("OPENAI_API_KEY", "")
    full_prompt = prompt if raw else prompt + _JSON_OUTPUT_INSTRUCTION

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

    tid = threading.current_thread().name
    _llm_log.debug("API_CALL_START thread=%s model=%s prompt_len=%d raw=%s",
                    tid, model, len(full_prompt), raw)
    t0 = _time.monotonic()
    result = _openai_call(full_prompt, model, api_key)
    elapsed = _time.monotonic() - t0
    _llm_log.debug("API_CALL_END thread=%s model=%s elapsed=%.1fs response_len=%d",
                    tid, model, elapsed, len(result))
    return result


def get_model_config() -> dict:
    """Return the determinism config for logging."""
    return dict(MODEL_CONFIG)


_NO_TEMP_MODELS = ("o1", "o3", "o4", "gpt-5")


def _openai_call(prompt: str, model: str, api_key: str) -> str:
    """Real OpenAI API call with deterministic settings."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    kwargs = dict(model=model, input=prompt, store=False)
    if not any(model.startswith(p) for p in _NO_TEMP_MODELS):
        kwargs["temperature"] = MODEL_CONFIG["temperature"]
    response = client.responses.create(**kwargs)
    return response.output_text
