"""Tests for config.py — loading, validation, structural invariants."""

import copy
import os
import sys
import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import (
    load_config,
    _validate_and_build,
    ConfigError,
    ExperimentConfig,
    ConditionConfig,
    RetryConfig,
    log_resolved_config,
    get_template_for_condition,
)


def _minimal_conditions():
    """Minimal valid conditions dict."""
    return {
        "baseline": {"template": "base"},
        "retry_no_contract": {"template": "base", "retry_template": "retry"},
        "contract_gated": {
            "template": "contract_elicit",
            "next_template": "contract_code",
            "retry_template": "contract_retry",
        },
    }


def valid_config_dict():
    """Return a valid raw config dict for testing."""
    return {
        "experiment": {
            "version": 1,
            "name": "test_experiment",
            "models": ["gpt-4o-mini"],
        },
        "conditions": _minimal_conditions(),
        "retry": {
            "enabled": True,
            "max_steps": 5,
            "strategy": "linear",
        },
        "execution": {
            "parallel": 1,
            "cases_file": "cases_v2.json",
            "timeout_total_seconds": 360,
            "timeout_per_step_seconds": 60,
        },
        "logging": {
            "run_dir_pattern": "ablation_runs/run_{model}_t{trial}_{uuid}",
            "log_resolved_config": True,
        },
    }


# ── C1: Missing required field ──


def test_missing_experiment_name():
    raw = valid_config_dict()
    del raw["experiment"]["name"]
    with pytest.raises(ConfigError, match="name"):
        _validate_and_build(raw)


# ── C2: Wrong type ──


def test_wrong_type_max_steps():
    raw = valid_config_dict()
    raw["retry"]["max_steps"] = "five"
    with pytest.raises(ConfigError, match="max_steps.*int.*str"):
        _validate_and_build(raw)


# ── C3: Unknown field ──


def test_unknown_retry_field_rejected():
    raw = valid_config_dict()
    raw["retry"]["unknown_field"] = True
    with pytest.raises(ConfigError, match="Unknown keys"):
        _validate_and_build(raw)


# ── C4: Config is immutable ──


def test_config_immutable():
    raw = valid_config_dict()
    config = _validate_and_build(raw)
    with pytest.raises(AttributeError):
        config.name = "modified"


# ── C5: Invalid condition name ──


def test_invalid_condition_name():
    raw = valid_config_dict()
    raw["conditions"]["nonexistent_condition"] = {"template": "base"}
    with pytest.raises(ConfigError, match="not a valid condition"):
        _validate_and_build(raw)


# ── C6: Condition missing template key ──


def test_condition_missing_template():
    raw = valid_config_dict()
    raw["conditions"]["baseline"] = {}
    with pytest.raises(ConfigError, match="template is required"):
        _validate_and_build(raw)


# ── C7: Condition unknown key ──


def test_condition_unknown_key():
    raw = valid_config_dict()
    raw["conditions"]["baseline"]["bogus"] = "value"
    with pytest.raises(ConfigError, match="Unknown keys"):
        _validate_and_build(raw)


# ── C8: Condition template not in registry ──


def test_condition_template_not_in_registry():
    raw = valid_config_dict()
    raw["conditions"]["baseline"]["template"] = "nonexistent_template"
    with pytest.raises(ConfigError, match="does not match"):
        _validate_and_build(raw)


# ── C9: max_steps out of range ──


def test_max_steps_out_of_range():
    raw = valid_config_dict()
    raw["retry"]["max_steps"] = 0
    with pytest.raises(ConfigError, match="\\[1, 20\\]"):
        _validate_and_build(raw)


# ── C10: Valid config loads ──


def test_valid_config_loads():
    raw = valid_config_dict()
    config = _validate_and_build(raw)
    assert config.version == 1
    assert config.name == "test_experiment"
    assert isinstance(config.models, tuple)
    assert isinstance(config.retry, RetryConfig)
    assert isinstance(config.conditions, dict)
    assert isinstance(config.conditions["baseline"], ConditionConfig)


# ── C11: config_resolved.yaml matches ──


def test_config_resolved_matches(tmp_path):
    raw = valid_config_dict()
    config = _validate_and_build(raw)
    log_resolved_config(config, tmp_path)
    resolved = yaml.safe_load((tmp_path / "config_resolved.yaml").read_text())
    assert resolved["retry"]["max_steps"] == config.retry.max_steps
    assert resolved["version"] == config.version


# ── C12: Missing top-level section ──


def test_missing_top_level_section():
    raw = valid_config_dict()
    del raw["conditions"]
    with pytest.raises(ConfigError, match="Missing required top-level keys"):
        _validate_and_build(raw)


# ── C13: Unknown top-level section ──


def test_unknown_top_level_section():
    raw = valid_config_dict()
    raw["prompt_vars"] = {"required": ["task"]}
    with pytest.raises(ConfigError, match="Unknown top-level keys"):
        _validate_and_build(raw)


# ── C14: Empty conditions ──


def test_empty_conditions_rejected():
    raw = valid_config_dict()
    raw["conditions"] = {}
    with pytest.raises(ConfigError, match="non-empty"):
        _validate_and_build(raw)


# ── C15: Wrong config version ──


def test_wrong_config_version_rejected():
    raw = valid_config_dict()
    raw["experiment"]["version"] = 999
    with pytest.raises(ConfigError, match="not compatible"):
        _validate_and_build(raw)


# ── C16: Missing config version ──


def test_missing_config_version_rejected():
    raw = valid_config_dict()
    del raw["experiment"]["version"]
    with pytest.raises(ConfigError, match="version"):
        _validate_and_build(raw)


# ── C17: Simple condition with retry_template rejected ──


def test_simple_condition_rejects_retry_template():
    raw = valid_config_dict()
    raw["conditions"]["baseline"]["retry_template"] = "retry"
    with pytest.raises(ConfigError, match="simple condition.*MUST NOT have retry_template"):
        _validate_and_build(raw)


# ── C18: Simple condition with next_template rejected ──


def test_simple_condition_rejects_next_template():
    raw = valid_config_dict()
    raw["conditions"]["baseline"]["next_template"] = "contract_code"
    with pytest.raises(ConfigError, match="simple condition.*MUST NOT have next_template"):
        _validate_and_build(raw)


# ── C19: Retry condition missing retry_template ──


def test_retry_condition_requires_retry_template():
    raw = valid_config_dict()
    del raw["conditions"]["retry_no_contract"]["retry_template"]
    with pytest.raises(ConfigError, match="retry condition.*MUST have retry_template"):
        _validate_and_build(raw)


# ── C20: Retry condition with next_template ──


def test_retry_condition_rejects_next_template():
    raw = valid_config_dict()
    raw["conditions"]["retry_no_contract"]["next_template"] = "contract_code"
    with pytest.raises(ConfigError, match="retry condition.*MUST NOT have next_template"):
        _validate_and_build(raw)


# ── C21: Multistep condition missing next_template ──


def test_multistep_condition_requires_next_template():
    raw = valid_config_dict()
    del raw["conditions"]["contract_gated"]["next_template"]
    with pytest.raises(ConfigError, match="multistep condition.*MUST have next_template"):
        _validate_and_build(raw)


# ── C22: Multistep condition missing retry_template ──


def test_multistep_condition_requires_retry_template():
    raw = valid_config_dict()
    del raw["conditions"]["contract_gated"]["retry_template"]
    with pytest.raises(ConfigError, match="multistep condition.*MUST have retry_template"):
        _validate_and_build(raw)


# ── C23: get_template_for_condition ──


def test_get_template_for_condition_initial():
    raw = valid_config_dict()
    config = _validate_and_build(raw)
    assert get_template_for_condition(config, "baseline", "initial") == "base"
    assert get_template_for_condition(config, "retry_no_contract", "initial") == "base"
    assert get_template_for_condition(config, "contract_gated", "initial") == "contract_elicit"


def test_get_template_for_condition_retry():
    raw = valid_config_dict()
    config = _validate_and_build(raw)
    assert get_template_for_condition(config, "retry_no_contract", "retry") == "retry"
    assert get_template_for_condition(config, "contract_gated", "retry") == "contract_retry"


def test_get_template_for_condition_next():
    raw = valid_config_dict()
    config = _validate_and_build(raw)
    assert get_template_for_condition(config, "contract_gated", "next") == "contract_code"


def test_get_template_for_condition_missing_retry():
    raw = valid_config_dict()
    config = _validate_and_build(raw)
    with pytest.raises(ConfigError, match="no retry_template"):
        get_template_for_condition(config, "baseline", "retry")


def test_get_template_for_condition_missing_next():
    raw = valid_config_dict()
    config = _validate_and_build(raw)
    with pytest.raises(ConfigError, match="no next_template"):
        get_template_for_condition(config, "baseline", "next")


def test_get_template_for_condition_unknown_condition():
    raw = valid_config_dict()
    config = _validate_and_build(raw)
    with pytest.raises(ConfigError, match="not found"):
        get_template_for_condition(config, "nonexistent", "initial")


# ── C24: Empty models list ──


def test_empty_models_rejected():
    raw = valid_config_dict()
    raw["experiment"]["models"] = []
    with pytest.raises(ConfigError, match="non-empty"):
        _validate_and_build(raw)


# ── C25: parallel out of range ──


def test_parallel_out_of_range():
    raw = valid_config_dict()
    raw["execution"]["parallel"] = 100
    with pytest.raises(ConfigError, match="\\[1, 32\\]"):
        _validate_and_build(raw)
