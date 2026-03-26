"""Tests for templates.py — registry, rendering, hashing, validation."""

import hashlib
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from templates import (
    TEMPLATE_REGISTRY, TemplateSpec, render, render_with_metadata,
    init_template_hashes, get_template_hash, _reset_template_hashes, _reset_env,
    validate_template_allowed_logic, preflight_validate_templates,
    TemplateNotFoundError, TemplateMissingVarError, TemplateExtraVarError, TemplateError,
    _get_env,
)


@pytest.fixture(autouse=True)
def _ensure_hashes_initialized():
    """Ensure template hashes are initialized for each test."""
    _reset_template_hashes()
    _reset_env()
    init_template_hashes()
    yield
    _reset_template_hashes()
    _reset_env()


# ── T1: Missing variable raises TemplateMissingVarError ──

def test_missing_variable_raises():
    with pytest.raises(TemplateMissingVarError, match="task"):
        render("base", {"code_files_block": "x"})


# ── T2: Extra variable raises TemplateExtraVarError ──

def test_extra_variable_raises():
    with pytest.raises(TemplateExtraVarError, match="extra"):
        render("base", {"task": "x", "code_files_block": "y", "extra": "z"})


# ── T3: Unknown template name raises TemplateNotFoundError ──

def test_unknown_template_raises():
    with pytest.raises(TemplateNotFoundError, match="nonexistent"):
        render("nonexistent", {})


# ── T4: Correct render produces expected output ──

def test_base_renders_correctly():
    result = render("base", {"task": "Fix the bug", "code_files_block": "def f(): pass"})
    assert "Fix the bug" in result
    assert "def f(): pass" in result


# ── T5: Empty variable value renders empty ──

def test_empty_string_variable():
    result = render("base", {"task": "", "code_files_block": ""})
    assert isinstance(result, str)


# ── T6: StrictUndefined catches template-level typos ──

def test_strict_undefined_catches_typo():
    from jinja2 import Environment, StrictUndefined, UndefinedError
    env = Environment(undefined=StrictUndefined)
    template = env.from_string("{{ typo }}")
    with pytest.raises(UndefinedError):
        template.render(task="x")


# ── T7: Retry template renders with all required vars ──

def test_retry_template_renders():
    result = render("retry", {
        "task": "Fix", "code_files_block": "code",
        "previous_code": "old", "test_output": "FAILED",
        "failure_reason": "logic error", "step_number": "1",
    })
    assert "step 1" in result
    assert "FAILED" in result


# ── T8: All registered templates can be dry-rendered ──

def test_all_templates_dry_render():
    for name, spec in TEMPLATE_REGISTRY.items():
        placeholders = {v: f"__{v}__" for v in spec.required_vars}
        result = render(name, placeholders)
        assert isinstance(result, str)
        assert len(result) > 0


# ── T10: Forbidden logic in template detected ──

def test_preflight_detects_forbidden_logic(tmp_path):
    bad_template = tmp_path / "bad.jinja2"
    bad_template.write_text("{% for x in items %}{{ x }}{% endfor %}")
    with pytest.raises(TemplateError, match="forbidden tag"):
        validate_template_allowed_logic(bad_template)


# ── T10b: Allowed if-blocks pass validation ──

def test_preflight_allows_if_blocks(tmp_path):
    good_template = tmp_path / "good.jinja2"
    good_template.write_text("{% if x %}{{ x }}{% else %}default{% endif %}")
    validate_template_allowed_logic(good_template)  # should not raise


# ── T11: Template hash is deterministic ──

def test_template_hash_deterministic():
    spec = TEMPLATE_REGISTRY["base"]
    h1 = get_template_hash("base")
    assert len(h1) == 64  # SHA-256 hex
    # Re-init and check same hash
    _reset_template_hashes()
    _reset_env()
    init_template_hashes()
    h2 = get_template_hash("base")
    assert h1 == h2


# ── T13: render_with_metadata returns correct metadata ──

def test_render_with_metadata():
    rendered, meta = render_with_metadata("base", {"task": "x", "code_files_block": "y"})
    assert meta["template_name"] == "base"
    assert "template_hash" in meta
    assert len(meta["template_hash"]) == 64
    assert meta["variables"] == {"task": "x", "code_files_block": "y"}
    assert meta["rendered_length"] == len(rendered)


# ── T14: get_template_hash before init raises RuntimeError ──

def test_get_hash_before_init_raises():
    _reset_template_hashes()
    with pytest.raises(RuntimeError, match="before init_template_hashes"):
        get_template_hash("base")


# ── T15: init_template_hashes called twice raises RuntimeError ──

def test_double_init_raises():
    # Already initialized by fixture, so second call should raise
    _reset_template_hashes()
    _reset_env()
    init_template_hashes()
    with pytest.raises(RuntimeError, match="called twice"):
        init_template_hashes()


# ── T16: Hash uses Jinja2 loader source ──

def test_hash_matches_jinja_source():
    env = _get_env()
    spec = TEMPLATE_REGISTRY["base"]
    jinja_name = spec.path.replace("templates/", "")
    source, _, _ = env.loader.get_source(env, jinja_name)
    expected = hashlib.sha256(source.encode("utf-8")).hexdigest()
    actual = get_template_hash("base")
    assert actual == expected


# ── T17: Contract templates render correctly ──

def test_contract_elicit_renders():
    result = render("contract_elicit", {
        "task": "Fix", "code_files_block": "code", "contract_schema": "{...}",
    })
    assert "Execution Contract" in result
    assert "{...}" in result


def test_contract_code_renders():
    result = render("contract_code", {
        "task": "Fix", "code_files_block": "code", "contract_json": '{"x": 1}',
    })
    assert "must_change" in result


def test_contract_retry_renders():
    result = render("contract_retry", {
        "task": "Fix", "code_files_block": "code",
        "contract_json": '{"x": 1}', "violations_text": "- bad thing",
    })
    assert "VIOLATIONS" in result


def test_classify_renders():
    result = render("classify", {
        "failure_types": "A, B, C", "task": "Fix", "code": "pass", "reasoning": "because",
    })
    assert "REASONING_CORRECT" in result
