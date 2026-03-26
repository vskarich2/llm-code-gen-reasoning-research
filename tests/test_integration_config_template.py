"""Integration tests — config + template system working together."""

import os
import sys
import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import load_config, _validate_and_build, ConfigError, get_template_for_condition, log_resolved_config
from templates import (
    TEMPLATE_REGISTRY, render, render_with_metadata, log_rendered_prompt,
    init_template_hashes, get_template_hash, _reset_template_hashes, _reset_env,
    preflight_validate_templates,
)
from constants import SIMPLE_CONDITIONS, RETRY_CONDITIONS, MULTISTEP_CONDITIONS
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def _ensure_hashes():
    _reset_template_hashes()
    _reset_env()
    init_template_hashes()
    yield
    _reset_template_hashes()
    _reset_env()


def _load_test_config():
    """Build a valid config from the real experiment.yaml."""
    _reset_template_hashes()
    _reset_env()
    # Need fresh hashes since _validate_and_build doesn't init them
    raw_path = BASE_DIR / "experiment.yaml"
    if not raw_path.exists():
        pytest.skip("experiment.yaml not found")
    raw = yaml.safe_load(raw_path.read_text())
    init_template_hashes()
    return _validate_and_build(raw)


# ── I1: Config condition selects correct template ──

def test_config_condition_selects_template():
    config = _load_test_config()
    cond_cfg = config.conditions["baseline"]
    assert cond_cfg.template == "base"
    assert cond_cfg.template in TEMPLATE_REGISTRY


# ── I2: Retry condition has retry_template ──

def test_config_retry_condition_has_retry_template():
    config = _load_test_config()
    cond_cfg = config.conditions["retry_no_contract"]
    assert cond_cfg.retry_template == "retry"
    assert cond_cfg.retry_template in TEMPLATE_REGISTRY


# ── I3: Contract condition has all three templates ──

def test_config_contract_has_all_templates():
    config = _load_test_config()
    cond_cfg = config.conditions["contract_gated"]
    assert cond_cfg.template == "contract_elicit"
    assert cond_cfg.next_template == "contract_code"
    assert cond_cfg.retry_template == "contract_retry"


# ── I4: get_template_for_condition returns correct template per phase ──

def test_get_template_for_condition():
    config = _load_test_config()
    assert get_template_for_condition(config, "retry_no_contract", "initial") == "base"
    assert get_template_for_condition(config, "retry_no_contract", "retry") == "retry"
    assert get_template_for_condition(config, "contract_gated", "next") == "contract_code"


# ── I5: get_template_for_condition raises on missing phase ──

def test_get_template_for_condition_missing_phase():
    config = _load_test_config()
    with pytest.raises(ConfigError, match="no retry_template"):
        get_template_for_condition(config, "baseline", "retry")


# ── I6: Rendered prompt matches expected ──

def test_rendered_prompt_matches_expected():
    result = render("base", {"task": "Fix the bug", "code_files_block": "code here"})
    assert result.strip() == "Fix the bug\n\ncode here"


# ── I7: Full pipeline: config -> template -> prompt ──

def test_full_pipeline():
    config = _load_test_config()
    tpl_name = config.conditions["baseline"].template
    rendered = render(tpl_name, {
        "task": "Fix the bug",
        "code_files_block": "def f(): pass",
    })
    assert len(rendered) > 0
    assert "{{ " not in rendered


# ── I8: config_resolved.yaml written and matches ──

def test_e2e_config_logged(tmp_path):
    config = _load_test_config()
    log_resolved_config(config, tmp_path)
    written = yaml.safe_load((tmp_path / "config_resolved.yaml").read_text())
    assert written["retry"]["max_steps"] == config.retry.max_steps


# ── I9: Prompt log record contains full variables and hash ──

def test_prompt_log_record_complete():
    variables = {"task": "x", "code_files_block": "y"}
    rendered, meta = render_with_metadata("base", variables)
    record = log_rendered_prompt(
        meta["template_name"], meta["template_hash"],
        meta["variables"], rendered,
    )
    assert record["template_hash"] == meta["template_hash"]
    assert record["variables"] == variables
    assert record["rendered_prompt"] == rendered


# ── I10: Structural invariants enforced end-to-end ──

def test_structural_invariants_e2e():
    config = _load_test_config()
    for cond_name, cond_cfg in config.conditions.items():
        if cond_name in SIMPLE_CONDITIONS:
            assert cond_cfg.retry_template is None, f"{cond_name} should have no retry_template"
            assert cond_cfg.next_template is None, f"{cond_name} should have no next_template"
        elif cond_name in RETRY_CONDITIONS:
            assert cond_cfg.retry_template is not None, f"{cond_name} should have retry_template"
            assert cond_cfg.next_template is None, f"{cond_name} should have no next_template"
        elif cond_name in MULTISTEP_CONDITIONS:
            assert cond_cfg.retry_template is not None, f"{cond_name} should have retry_template"
            assert cond_cfg.next_template is not None, f"{cond_name} should have next_template"


# ── I11: preflight_validate_templates passes on valid config ──

def test_preflight_validates_successfully():
    _reset_template_hashes()
    _reset_env()
    raw_path = BASE_DIR / "experiment.yaml"
    if not raw_path.exists():
        pytest.skip("experiment.yaml not found")
    raw = yaml.safe_load(raw_path.read_text())
    config = _validate_and_build(raw)
    preflight_validate_templates(config)
    # If we get here, preflight passed
    assert get_template_hash("base") is not None
