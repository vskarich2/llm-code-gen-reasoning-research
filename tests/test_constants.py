"""Tests for constants.py — condition names, labels, and categories."""

import pytest


def test_valid_conditions_frozen():
    from constants import VALID_CONDITIONS
    assert isinstance(VALID_CONDITIONS, frozenset)


def test_labels_unique():
    from constants import COND_LABELS
    assert len(set(COND_LABELS.values())) == len(COND_LABELS)


def test_every_condition_has_label():
    from constants import ALL_CONDITIONS, COND_LABELS
    for c in ALL_CONDITIONS:
        assert c in COND_LABELS, f"Condition {c} has no label"


def test_condition_categories_exhaustive():
    from constants import VALID_CONDITIONS, RETRY_CONDITIONS, MULTISTEP_CONDITIONS, SIMPLE_CONDITIONS
    assert RETRY_CONDITIONS | MULTISTEP_CONDITIONS | SIMPLE_CONDITIONS == VALID_CONDITIONS


def test_condition_categories_non_overlapping():
    from constants import RETRY_CONDITIONS, MULTISTEP_CONDITIONS, SIMPLE_CONDITIONS
    assert not (RETRY_CONDITIONS & MULTISTEP_CONDITIONS)
    assert not (RETRY_CONDITIONS & SIMPLE_CONDITIONS)
    assert not (MULTISTEP_CONDITIONS & SIMPLE_CONDITIONS)


def test_config_version_is_int():
    from constants import CURRENT_CONFIG_VERSION
    assert isinstance(CURRENT_CONFIG_VERSION, int)
    assert CURRENT_CONFIG_VERSION >= 1


def test_retry_conditions_contents():
    from constants import RETRY_CONDITIONS
    assert "retry_no_contract" in RETRY_CONDITIONS
    assert "retry_with_contract" in RETRY_CONDITIONS
    assert "retry_adaptive" in RETRY_CONDITIONS
    assert "retry_alignment" in RETRY_CONDITIONS
    assert "repair_loop" in RETRY_CONDITIONS


def test_multistep_conditions_contents():
    from constants import MULTISTEP_CONDITIONS
    assert "contract_gated" in MULTISTEP_CONDITIONS


def test_simple_conditions_exclude_retry_and_multistep():
    from constants import SIMPLE_CONDITIONS
    assert "baseline" in SIMPLE_CONDITIONS
    assert "diagnostic" in SIMPLE_CONDITIONS
    assert "retry_no_contract" not in SIMPLE_CONDITIONS
    assert "contract_gated" not in SIMPLE_CONDITIONS
