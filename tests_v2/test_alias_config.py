"""Tests for alias_config family (shared_reference_aliasing).

Invariant: create_config() must return a FRESH dict every call.
           Mutating one config must NOT affect future calls or DEFAULTS.
"""


def test_a(mod):
    """Level A: direct aliasing in single file."""
    # Reset module state
    if hasattr(mod, "DEFAULTS"):
        mod.DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}
    if hasattr(mod, "reset_defaults"):
        mod.reset_defaults()

    create = getattr(mod, "create_config", None)
    if create is None:
        return False, ["create_config not found"]

    try:
        cfg1 = create({"timeout": 5})
        cfg2 = create()
    except Exception as e:
        return False, [f"create_config raised: {e}"]

    # cfg2 should have original defaults, not cfg1's overrides
    if cfg2.get("timeout") != 30:
        return False, [f"mutation leaked: cfg2['timeout']={cfg2.get('timeout')}, expected 30"]

    # DEFAULTS should be unmodified
    if hasattr(mod, "DEFAULTS") and mod.DEFAULTS.get("timeout") != 30:
        return False, [f"DEFAULTS corrupted: timeout={mod.DEFAULTS.get('timeout')}"]

    return True, ["create_config returns independent dicts"]


def test_b(mod):
    """Level B: aliasing through cached get_settings()."""
    # Reset module state
    if hasattr(mod, "DEFAULTS"):
        mod.DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}
    if hasattr(mod, "reset_defaults"):
        mod.reset_defaults()
    if hasattr(mod, "_cached_settings"):
        mod._cached_settings = None
    if hasattr(mod, "clear_cache"):
        mod.clear_cache()

    create = getattr(mod, "create_config", None)
    if create is None:
        return False, ["create_config not found"]

    try:
        # Call create_config with overrides, then call again clean
        cfg1 = create({"timeout": 5})
        cfg2 = create()
    except Exception as e:
        return False, [f"create_config raised: {e}"]

    if cfg2.get("timeout") != 30:
        return False, [f"mutation leaked: cfg2['timeout']={cfg2.get('timeout')}, expected 30"]

    if hasattr(mod, "DEFAULTS") and mod.DEFAULTS.get("timeout") != 30:
        return False, [f"DEFAULTS corrupted: timeout={mod.DEFAULTS.get('timeout')}"]

    return True, ["create_config returns independent dicts across calls"]


def test_c(mod):
    """Level C: aliasing through middleware caching across files."""
    # Reset module state
    if hasattr(mod, "DEFAULTS"):
        mod.DEFAULTS = {"timeout": 30, "retries": 3, "debug": False}
    if hasattr(mod, "reset_defaults"):
        mod.reset_defaults()

    create = getattr(mod, "create_config", None)
    handle = getattr(mod, "handle_request", None)

    if create is None:
        return False, ["create_config not found"]
    if handle is None:
        return False, ["handle_request not found"]

    try:
        # First request with debug override
        r1 = handle({"debug": True})
        # Second request with no overrides — should get clean defaults
        r2 = handle()
    except Exception as e:
        return False, [f"handle_request raised: {e}"]

    if r2.get("debug") is True:
        return False, [f"debug override leaked: r2['debug']={r2['debug']}, expected False"]

    if r2.get("timeout") != 30:
        return False, [f"timeout corrupted: r2['timeout']={r2.get('timeout')}, expected 30"]

    # Also verify DEFAULTS not corrupted
    if hasattr(mod, "DEFAULTS") and mod.DEFAULTS.get("debug") is True:
        return False, [f"DEFAULTS corrupted: debug={mod.DEFAULTS.get('debug')}"]

    return True, ["handle_request returns independent configs per call"]
