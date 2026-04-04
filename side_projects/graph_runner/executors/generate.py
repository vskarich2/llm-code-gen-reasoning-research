import json
import os

from openai import OpenAI

from side_projects.graph_runner.state import ExecutionState, Artifact
from side_projects.graph_runner.stage_spec import StageResult


USE_REAL_LLM = os.environ.get("GRAPH_RUNNER_REAL_LLM", "0") == "1"

FORCE_FAILURE_MODE = None  # "malformed_json" | "missing_key" | "wrong_type" | "semantic_failure"

MODEL = "gpt-4o-mini"
TEMPERATURE = 0
MAX_TOKENS = 128000

JSON_INSTRUCTION = """

Return ONLY valid JSON with this exact schema:
{
  "reasoning": "...",
  "code": "..."
}
Do not include any extra text."""


def _call_llm(prompt: str) -> str:
    """Single LLM call. No retries. No streaming. No fallback."""
    client = OpenAI()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )
    return response.choices[0].message.content


def _safe_parse_json(text: str) -> dict:
    """Strict JSON parse. No fallback. No regex. No cleanup."""
    return json.loads(text)


def _fake_response() -> dict:
    return {
        "reasoning": "The bug is due to shared reference mutation.",
        "code": (
            "def create_config(overrides=None):\n"
            "    defaults = {'timeout': 30, 'retries': 3}\n"
            "    config = defaults.copy()\n"
            "    if overrides:\n"
            "        config.update(overrides)\n"
            "    return config"
        ),
    }


def _forced_failure_text() -> str:
    """Return raw text for the active FORCE_FAILURE_MODE."""
    if FORCE_FAILURE_MODE == "malformed_json":
        return 'Here is the answer: { "reasoning": "...", "code": "..." }'
    elif FORCE_FAILURE_MODE == "missing_key":
        return '{"code": "def f(): return 1"}'
    elif FORCE_FAILURE_MODE == "wrong_type":
        return '{"reasoning": 123, "code": "def f(): return 1"}'
    elif FORCE_FAILURE_MODE == "semantic_failure":
        return json.dumps({
            "reasoning": "Fix applied",
            "code": "def create_config(): return {'timeout': 30}",
        })
    else:
        raise ValueError(f"Unknown FORCE_FAILURE_MODE: {FORCE_FAILURE_MODE}")


def generate_executor(state: ExecutionState) -> StageResult:
    prompt = state.get("prompt").value

    # Forced failure mode — for testing system integrity
    if FORCE_FAILURE_MODE is not None:
        raw_text = _forced_failure_text()
        state.add_artifact(
            "raw_llm_text",
            Artifact.create(type="raw_llm_text", value=raw_text),
        )
        try:
            response = _safe_parse_json(raw_text)
        except (json.JSONDecodeError, ValueError) as e:
            state.add_artifact(
                "parse_error",
                Artifact.create(type="parse_error", value=f"JSON parse failed: {e}"),
            )
            return StageResult(state=state, outcome="error")
        state.add_artifact(
            "raw_response",
            Artifact.create(type="raw_response", value=response),
        )
        return StageResult(state=state, outcome="success")

    # Fake response mode (default for tests)
    if not USE_REAL_LLM:
        response = _fake_response()
        state.add_artifact(
            "raw_response",
            Artifact.create(type="raw_response", value=response),
        )
        return StageResult(state=state, outcome="success")

    # Real LLM path
    full_prompt = prompt + JSON_INSTRUCTION
    raw_text = _call_llm(full_prompt)

    # Store raw LLM text as-is — never modify, never clean
    state.add_artifact(
        "raw_llm_text",
        Artifact.create(type="raw_llm_text", value=raw_text),
    )

    # Strict JSON parse — no fallback, no cleanup
    try:
        response = _safe_parse_json(raw_text)
    except (json.JSONDecodeError, ValueError) as e:
        state.add_artifact(
            "parse_error",
            Artifact.create(type="parse_error", value=f"JSON parse failed: {e}"),
        )
        return StageResult(state=state, outcome="error")

    state.add_artifact(
        "raw_response",
        Artifact.create(type="raw_response", value=response),
    )

    return StageResult(state=state, outcome="success")
