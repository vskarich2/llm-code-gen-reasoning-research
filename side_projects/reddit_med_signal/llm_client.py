"""Thin OpenAI API wrapper with timeout, retry, and cost logging."""

from __future__ import annotations

import logging
import time

from openai import OpenAI

_log = logging.getLogger("reddit_med_signal.llm_client")


class LLMCallError(Exception):
    """Raised when all retries are exhausted."""


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def call_llm(
    prompt: str,
    model: str,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    timeout: int = 30,
    max_retries: int = 3,
    retry_base_delay: float = 2.0,
    response_format: dict | None = None,
    system_prompt: str | None = None,
) -> str:
    """Call the OpenAI API. Retries with exponential backoff.

    Returns the response text. Raises LLMCallError on failure.
    Logs model, token counts, latency, and estimated cost per call.
    """
    client = _get_client()
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        t0 = time.monotonic()
        try:
            kwargs: dict = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
            if response_format:
                kwargs["response_format"] = response_format
            response = client.chat.completions.create(**kwargs)
            elapsed = time.monotonic() - t0

            usage = response.usage
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            text = response.choices[0].message.content or ""

            _log.info(
                "LLM call: model=%s prompt_tok=%d completion_tok=%d "
                "latency=%.1fs attempt=%d/%d",
                model, prompt_tokens, completion_tokens,
                elapsed, attempt, max_retries,
            )
            return text

        except Exception as e:
            elapsed = time.monotonic() - t0
            last_error = e
            _log.warning(
                "LLM call failed (attempt %d/%d, %.1fs): %s",
                attempt, max_retries, elapsed, e,
            )
            if attempt < max_retries:
                delay = retry_base_delay * (2 ** (attempt - 1))
                time.sleep(delay)

    raise LLMCallError(
        f"All {max_retries} attempts failed for model={model}: {last_error}"
    )


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    input_rate_per_million: float,
    output_rate_per_million: float,
) -> float:
    """Estimate cost in USD."""
    input_cost = (prompt_tokens / 1_000_000) * input_rate_per_million
    output_cost = (completion_tokens / 1_000_000) * output_rate_per_million
    return input_cost + output_cost
