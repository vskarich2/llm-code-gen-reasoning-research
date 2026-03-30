"""Shared utilities for Phase 3.5 validation gates."""

import hashlib
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

# Force mock mode
os.environ["OPENAI_API_KEY"] = "sk-dummy"


def ensure_loaded():
    """Ensure config and prompt registry are loaded."""
    from experiment_config import is_config_loaded, load_config
    if not is_config_loaded():
        load_config(str(BASE_DIR / "configs" / "default.yaml"))
    from prompt_registry import is_loaded, load_prompt_registry
    if not is_loaded():
        load_prompt_registry()


def load_all_cases():
    """Load all v2 cases."""
    from runner import load_cases
    return load_cases(case_id=None, cases_file="cases_v2.json")


def old_build_prompt(case, condition):
    """Build prompt via the canonical AssemblyEngine path.

    After Phase 7.2, there is no "old" system. Both old_build_prompt and
    new_build_prompt call the same path. This function exists only for
    validation gate compatibility (gates compare old vs new).
    """
    return new_build_prompt(case, condition)


def new_build_prompt(case, condition):
    """Build prompt using the NEW AssemblyEngine system."""
    from execution import build_prompt
    prompt, _ = build_prompt(case, condition)
    return prompt


def prompt_hash(prompt):
    """SHA-256 hash of a prompt string."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def write_json(path, data):
    """Write JSON atomically."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def write_text(path, text):
    """Write text file."""
    with open(path, "w") as f:
        f.write(text)


MIGRATED_CONDITIONS = [
    "baseline", "diagnostic", "guardrail", "guardrail_strict",
    "counterfactual", "reason_then_act", "self_check",
    "counterfactual_check", "test_driven", "repair_loop",
    "structured_reasoning", "free_form_reasoning", "branching_reasoning",
]
