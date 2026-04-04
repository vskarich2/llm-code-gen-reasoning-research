"""Tests for config YAML serialization round-trip safety.

Ensures config_to_dict() produces output that:
1. Contains only YAML-safe types (no tuples, frozensets)
2. Round-trips through safe_dump/safe_load without mutation
3. Can be re-parsed by load_config() into an equivalent config
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest
import yaml

from core.config.experiment_config import (
    ExperimentConfig,
    OracleConfig,
    config_to_dict,
    load_config,
)

CONFIG_PATH = "core/config/config_storage/smoke_oracle_inline.yaml"
DEFAULT_CONFIG_PATH = "core/config/config_storage/default.yaml"


def _load_fresh(path: str) -> ExperimentConfig:
    """Load config without polluting the global singleton across tests."""
    import core.config.experiment_config as mod
    old = mod._config
    try:
        return load_config(path)
    finally:
        mod._config = old


# ── TYPE SAFETY ──


def _check_yaml_safe_types(obj, path="root"):
    """Recursively assert obj contains only YAML-safe types."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert isinstance(k, str), f"Non-string dict key at {path}: {k!r} ({type(k)})"
            _check_yaml_safe_types(v, f"{path}.{k}")
        return
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            _check_yaml_safe_types(v, f"{path}[{i}]")
        return
    pytest.fail(f"Non-YAML-safe type at {path}: {type(obj).__name__} = {obj!r}")


def test_config_to_dict_no_tuples():
    """config_to_dict must not contain tuples."""
    config = _load_fresh(CONFIG_PATH)
    d = config_to_dict(config)
    _check_yaml_safe_types(d)


def test_config_to_dict_no_tuples_default():
    """Same check on default config."""
    config = _load_fresh(DEFAULT_CONFIG_PATH)
    d = config_to_dict(config)
    _check_yaml_safe_types(d)


def test_no_temperature_prefixes_is_list():
    """no_temperature_prefixes must be a list, not tuple."""
    config = _load_fresh(CONFIG_PATH)
    assert isinstance(config.models.no_temperature_prefixes, list)
    d = config_to_dict(config)
    assert isinstance(d["models"]["no_temperature_prefixes"], list)


# ── ROUND-TRIP ──


def test_safe_dump_safe_load_roundtrip():
    """safe_dump → safe_load must produce identical dict."""
    config = _load_fresh(CONFIG_PATH)
    d = config_to_dict(config)
    yaml_str = yaml.safe_dump(d, default_flow_style=False)
    reloaded = yaml.safe_load(yaml_str)
    assert reloaded == d, f"Round-trip mismatch:\n{_diff(d, reloaded)}"


def test_safe_dump_safe_load_roundtrip_default():
    """Same check on default config."""
    config = _load_fresh(DEFAULT_CONFIG_PATH)
    d = config_to_dict(config)
    yaml_str = yaml.safe_dump(d, default_flow_style=False)
    reloaded = yaml.safe_load(yaml_str)
    assert reloaded == d


# ── RE-PARSE ──


def test_config_to_dict_reparseable():
    """config_to_dict output must be loadable by load_config."""
    config = _load_fresh(CONFIG_PATH)
    d = config_to_dict(config)
    yaml_str = yaml.safe_dump(d, default_flow_style=False)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_str)
        tmp = f.name
    try:
        config2 = _load_fresh(tmp)
        assert config2.oracle.inline_enabled == config.oracle.inline_enabled
        assert config2.oracle.partial_mode == config.oracle.partial_mode
        assert config2.evaluation.leg_enabled == config.evaluation.leg_enabled
        assert config2.evaluation.classifier_mode == config.evaluation.classifier_mode
        assert config2.logging.redis_enabled == config.logging.redis_enabled
        assert config2.models.no_temperature_prefixes == config.models.no_temperature_prefixes
        assert len(config2.models.generation) == len(config.models.generation)
        assert list(config2.conditions.keys()) == list(config.conditions.keys())
    finally:
        os.unlink(tmp)


def test_config_to_dict_reparseable_default():
    """Same check on default config (more conditions, more fields)."""
    config = _load_fresh(DEFAULT_CONFIG_PATH)
    d = config_to_dict(config)
    yaml_str = yaml.safe_dump(d, default_flow_style=False)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_str)
        tmp = f.name
    try:
        config2 = _load_fresh(tmp)
        assert config2.evaluation.leg_enabled == config.evaluation.leg_enabled
        assert config2.logging.redis_enabled == config.logging.redis_enabled
        assert len(config2.conditions) == len(config.conditions)
    finally:
        os.unlink(tmp)


# ── NESTING ──


def test_evaluation_section_nested():
    """evaluation section must have nested leg/failure_classification/alignment."""
    config = _load_fresh(CONFIG_PATH)
    d = config_to_dict(config)
    ev = d["evaluation"]
    assert "leg" in ev and isinstance(ev["leg"], dict), f"leg not nested: {ev}"
    assert "leg_enabled" not in ev, f"flat leg_enabled still present: {ev}"
    assert ev["leg"]["enabled"] is True


def test_logging_section_nested():
    """logging section must have nested redis."""
    config = _load_fresh(CONFIG_PATH)
    d = config_to_dict(config)
    lg = d["logging"]
    assert "redis" in lg and isinstance(lg["redis"], dict), f"redis not nested: {lg}"
    assert "redis_enabled" not in lg, f"flat redis_enabled still present: {lg}"


def test_oracle_section_present():
    """oracle section must be present in config_to_dict output."""
    config = _load_fresh(CONFIG_PATH)
    d = config_to_dict(config)
    assert "oracle" in d, f"oracle section missing from config_to_dict"
    assert d["oracle"]["inline_enabled"] is True
    assert d["oracle"]["partial_mode"] == "lenient"
    assert d["oracle"]["sampling_strategy"] == "ALWAYS"


# ── HELPERS ──


def _diff(a, b, path=""):
    """Find first difference between two dicts for error messages."""
    if type(a) != type(b):
        return f"Type mismatch at {path}: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for k in set(list(a.keys()) + list(b.keys())):
            if k not in a:
                return f"Missing key at {path}: {k} (in b but not a)"
            if k not in b:
                return f"Extra key at {path}: {k} (in a but not b)"
            d = _diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
    elif isinstance(a, list):
        if len(a) != len(b):
            return f"List length at {path}: {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _diff(x, y, f"{path}[{i}]")
            if d:
                return d
    elif a != b:
        return f"Value mismatch at {path}: {a!r} vs {b!r}"
    return ""
