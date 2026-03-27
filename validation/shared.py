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
    """Build prompt using the OLD legacy system."""
    from prompts import build_base_prompt
    from nudges.router import (
        apply_diagnostic, apply_guardrail, apply_guardrail_strict,
        apply_counterfactual, apply_reason_then_act, apply_self_check,
        apply_counterfactual_check, apply_test_driven,
    )
    code_files = case["code_files_contents"]
    base = build_base_prompt(case["task"], code_files)
    case_id = case["id"]
    hard = case.get("hard_constraints", [])

    if condition == "baseline":
        return base
    elif condition == "diagnostic":
        return apply_diagnostic(case_id, base)
    elif condition == "guardrail":
        return apply_guardrail(case_id, base)
    elif condition == "guardrail_strict":
        return apply_guardrail_strict(case_id, base, hard)
    elif condition == "counterfactual":
        return apply_counterfactual(case_id, base)
    elif condition == "reason_then_act":
        return apply_reason_then_act(case_id, base)
    elif condition == "self_check":
        return apply_self_check(case_id, base)
    elif condition == "counterfactual_check":
        return apply_counterfactual_check(case_id, base)
    elif condition == "test_driven":
        return apply_test_driven(case_id, base)
    elif condition == "repair_loop":
        return apply_diagnostic(case_id, base)
    elif condition == "structured_reasoning":
        from reasoning_prompts import build_structured_reasoning
        return build_structured_reasoning(base)
    elif condition == "free_form_reasoning":
        from reasoning_prompts import build_free_form_reasoning
        return build_free_form_reasoning(base)
    elif condition == "branching_reasoning":
        from reasoning_prompts import build_branching_reasoning
        return build_branching_reasoning(base)
    else:
        raise ValueError(f"Unmigrated condition: {condition}")


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
