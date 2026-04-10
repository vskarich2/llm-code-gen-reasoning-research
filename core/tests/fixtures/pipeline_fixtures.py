"""Shared test fixtures for pipeline integration tests.

All test data loading, response building, and adapter construction
is centralized here. Tests must NOT replicate this logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.utils.paths import (
    get_case_data_dir,
    get_cases_v2_path,
    get_config_dir,
    get_reference_fixes_dir,
)
from side_projects.graph_runner.replay.adapter import (
    LLMRequest,
    LLMResponse,
)

SMOKE_CONFIG_NAME = "smoke_ddc_cases.yaml"


# ============================================================
# CONFIG
# ============================================================

def load_test_config() -> Any:
    """Load the canonical test config. Idempotent."""
    from core.config.experiment_config import (
        get_config,
        is_config_loaded,
        load_config,
    )
    if not is_config_loaded():
        load_config(str(get_config_dir() / SMOKE_CONFIG_NAME))
    return get_config()


def get_first_generation_model(config: Any) -> str:
    """Return the first generation model name from config."""
    return config.models.generation[0].name


def get_first_single_attempt_condition(config: Any) -> str:
    """Return a single-attempt condition from config."""
    for cond_name in config.conditions:
        if not cond_name.startswith("retry_") and not cond_name.startswith("critique_"):
            return cond_name
    return next(iter(config.conditions))


def get_first_retry_condition(config: Any) -> str:
    """Return a retry/critique condition from config."""
    for cond_name in config.conditions:
        if cond_name.startswith("critique_") or cond_name.startswith("retry_"):
            return cond_name
    raise ValueError("No retry/critique condition found in config")


# ============================================================
# CASE LOADING
# ============================================================

def load_all_cases() -> list[dict]:
    with open(get_cases_v2_path()) as f:
        return json.load(f)


def load_case_by_id(case_id: str) -> tuple[dict, list[dict]]:
    """Load a case with file contents populated."""
    all_cases = load_all_cases()
    case = next(c for c in all_cases if c["id"] == case_id)
    return enrich_case(case), all_cases


def enrich_case(case: dict) -> dict:
    """Populate code_files_contents and logical_file_keys."""
    case = dict(case)
    case_data = get_case_data_dir()
    contents = {}
    for fp in case["code_files"]:
        contents[fp] = (case_data / fp).read_text()
    case["code_files_contents"] = contents
    case["logical_file_keys"] = {
        fp.rsplit("/", 1)[-1]: content
        for fp, content in contents.items()
    }
    return case


def get_first_ddc_case_id() -> str:
    """Return the first DDC baseline case ID from the case list."""
    from core.constants.pipeline_constants import DDC_FAMILIES
    for case in load_all_cases():
        cid = case["id"]
        if cid in DDC_FAMILIES:
            return cid
    raise ValueError("No DDC baseline case found")


# ============================================================
# RESPONSE BUILDING
# ============================================================

def build_fixed_response(case: dict, all_cases: list[dict]) -> str:
    """Build a generation response with the reference fix applied."""
    ref_dir = get_reference_fixes_dir()
    ref_path = ref_dir / f"{case['id']}.py"
    ref_code = ref_path.read_text()
    bug_file = case["reference_fix"]["file"]
    files = {}
    for fp in case["code_files"]:
        fn = fp.rsplit("/", 1)[-1]
        files[fn] = ref_code if fn == bug_file else "UNCHANGED"
    return json.dumps({
        "root_cause": f"Bug in {bug_file}: incorrect logic",
        "fix_strategy": "Fix the root cause directly",
        "code_commitments": ["Must fix the identified bug"],
        "files": files,
    })


def build_buggy_response(case: dict) -> str:
    """Build a response with all files UNCHANGED (no fix)."""
    files = {
        fp.rsplit("/", 1)[-1]: "UNCHANGED" for fp in case["code_files"]
    }
    return json.dumps({
        "root_cause": "No issue found",
        "fix_strategy": "No change",
        "code_commitments": ["None"],
        "files": files,
    })


# ============================================================
# ADAPTER BUILDING
# ============================================================

class PromptClassifyingAdapter:
    """Adapter that classifies prompts by content and returns appropriate responses.

    Uses prompt content markers to distinguish generation, oracle,
    classifier, and critique calls. No hardcoded strings leak to tests.
    """

    def __init__(self, gen_response: str) -> None:
        self.gen_response = gen_response
        self.calls: list[dict[str, Any]] = []
        self.call_count = 0

    def call(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        call_type = classify_prompt(request.prompt)
        self.calls.append({
            "type": call_type,
            "model": request.model,
            "len": len(request.prompt),
        })

        if call_type == "oracle":
            return LLMResponse(text=build_oracle_response())
        if call_type == "classifier":
            return LLMResponse(text=build_classifier_response())
        if call_type == "critique":
            return LLMResponse(text="The fix targets the wrong location.")
        return LLMResponse(text=self.gen_response)


def classify_prompt(prompt: str) -> str:
    """Classify a prompt by its structural markers."""
    lower = prompt.lower()
    if "ground truth bug specification" in lower:
        return "oracle"
    if "bug_type:" in lower and "bug_location:" in lower:
        return "oracle"
    if "true mechanism" in lower:
        return "oracle"
    if ("internal consistency" in lower
            and "reasoning_internal_consistency" in lower):
        return "classifier"
    if "auditing consistency" in lower:
        return "critique"
    if "mismatch" in lower and "root cause:" in lower:
        return "critique"
    return "generation"


def build_oracle_response() -> str:
    return "CORRECT\nThe reasoning correctly identifies the root cause."


def build_classifier_response() -> str:
    return json.dumps({
        "reasoning_internal_consistency": "CORRECT",
        "reasoning_internal_consistency_justification":
            "Root cause identifies the source correctly.",
        "commitments_internal_consistency": "CORRECT",
        "commitments_internal_consistency_justification":
            "Commitments follow from fix strategy.",
        "commitments_code_consistency": "CORRECT",
        "commitments_code_consistency_justification":
            "Code implements stated commitments.",
        "reasoning_code_alignment": "CORRECT",
        "reasoning_code_alignment_justification":
            "Code changes match the fix strategy.",
    })


# ============================================================
# RECORDING LOGGER
# ============================================================

class RecordingLogger:
    """Stub logger that records all calls for assertion."""

    def __init__(self) -> None:
        self.end_case_calls: list[tuple] = []
        self.log_run_calls: list[tuple] = []
        self.start_case_calls: list[str] = []
        self.error_calls: list[tuple] = []
        self.ctr = 0

    def start_case(self, case_id: str) -> Any:
        self.start_case_calls.append(case_id)

        class Handle:
            trace_id = "test_trace"
            event_id = 1
        return Handle()

    def end_case(self, *args: Any, **kwargs: Any) -> int:
        self.end_case_calls.append((args, kwargs))
        self.ctr += 1
        return self.ctr

    def log_run(self, *args: Any, **kwargs: Any) -> None:
        self.log_run_calls.append((args, kwargs))

    def log_call(self, **kwargs: Any) -> int:
        self.ctr += 1
        return self.ctr

    def log_structured_error(self, *a: Any, **kw: Any) -> None:
        self.error_calls.append((a, kw))

    def fail_case(self, *a: Any, **kw: Any) -> None:
        pass

    def new_trajectory(self) -> None:
        pass


# ============================================================
# REPLAY FIXTURE HELPERS
# ============================================================

def write_replay_fixture(
    tmp_path: Path, records: list[dict],
) -> Path:
    """Write replay records to a JSONL file under tmp_path."""
    path = tmp_path / "fixtures" / "replay.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path
