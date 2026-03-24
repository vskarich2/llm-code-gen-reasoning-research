"""Tests for silent_default family (silent_failure).

Invariant: Feature flag lookups must return the actual configured value,
           not silently fall back to a default due to key mismatch.
"""


def test_a(mod):
    """Level A: camelCase key silently misses snake_case flag."""
    # Reset module state
    if hasattr(mod, "FLAGS"):
        mod.FLAGS = {
            "dark_mode": True,
            "beta_features": False,
            "new_dashboard": True,
            "analytics_v2": False,
        }

    is_enabled = getattr(mod, "is_enabled", None)
    if is_enabled is None:
        return False, ["is_enabled not found"]

    try:
        # "darkMode" should resolve to "dark_mode" which is True
        result = is_enabled("darkMode")
    except Exception as e:
        return False, [f"is_enabled raised: {e}"]

    if not result:
        return False, [
            f"is_enabled('darkMode') returned False. "
            f"Flag 'dark_mode' is True but camelCase lookup missed it."
        ]

    return True, ["camelCase flag correctly resolves to snake_case key"]


def test_b(mod):
    """Level B: misspelled intermediate key in dot-path traversal."""
    is_analytics = getattr(mod, "is_analytics_enabled", None)
    if is_analytics is None:
        return False, ["is_analytics_enabled not found"]

    try:
        result = is_analytics()
    except Exception as e:
        return False, [f"is_analytics_enabled raised: {e}"]

    if not result:
        return False, [
            f"is_analytics_enabled() returned False. "
            f"Config has feature.analytics.enabled=True but path traversal "
            f"failed due to wrong intermediate key."
        ]

    return True, ["analytics flag correctly traversed via dot-path"]


def test_c(mod):
    """Level C: env key mismatch causes wrong fallback in flag chain."""
    # Reset env state if accessible
    if hasattr(mod, "_ENV"):
        mod._ENV = {
            "FEATURE_DARK_MODE": "true",
            "FEATURE_BETA": "false",
            "FEATURE_ANALYTICS": "true",
            "APP_DEBUG": "false",
        }
    if hasattr(mod, "_FILE_CONFIG"):
        mod._FILE_CONFIG = {
            "dark_mode": True,
            "beta": False,
            "analytics": True,
        }

    is_enabled = getattr(mod, "is_enabled", None)
    get_source = getattr(mod, "get_flag_source", None)
    if is_enabled is None:
        return False, ["is_enabled not found"]
    if get_source is None:
        return False, ["get_flag_source not found"]

    try:
        source = get_source("dark_mode")
    except Exception as e:
        return False, [f"get_flag_source raised: {e}"]

    if source != "env":
        return False, [
            f"get_flag_source('dark_mode') returned '{source}', expected 'env'. "
            f"Env var FEATURE_DARK_MODE exists but lookup uses wrong key, "
            f"causing silent fallback to '{source}' layer."
        ]

    return True, ["dark_mode flag correctly sourced from env layer"]
