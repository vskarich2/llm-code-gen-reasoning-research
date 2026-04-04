"""Tests for config_shadowing (L3 — structural vs contingent cause).

Invariant: both request and background paths must use timeout=30.
           Anti-hardcoding: if DEFAULTS is changed, both paths must reflect
           the change (proves they read from the config layer, not hardcoded).

Equivalence policy: behavior_plus_propagation_semantics
Mechanism evidence: EXERCISE
Strength: STRONG (V2.1 — was WEAK, added anti-hardcoding + structural check)

V2.1: hardcoded `return {"timeout": 30}` now correctly FAILS because the
      anti-hardcoding check changes DEFAULTS and re-checks.
"""


def test(mod):
    """Test config propagation with anti-hardcoding probe."""
    errors = []

    # --- PRIMARY CHECK: both paths use timeout=30 ---
    try:
        result = mod.run_system_check()
    except Exception as e:
        return False, [f"run_system_check raised: {e}"]

    req = result.get("request", {}).get("timeout")
    bg = result.get("background", {}).get("timeout")

    if req != 30:
        errors.append(f"request timeout={req}, expected 30")
    if bg != 30:
        errors.append(f"background timeout={bg}, expected 30")

    # --- ANTI-HARDCODING: change DEFAULTS and verify propagation ---
    # If the fix hardcodes 30 in service.py instead of fixing defaults.py,
    # this probe will catch it because changing DEFAULTS won't affect output.
    defaults_dict = getattr(mod, "DEFAULTS", None)
    if defaults_dict is not None and isinstance(defaults_dict, dict):
        original_timeout = defaults_dict.get("timeout")

        # Mutate DEFAULTS to a different value
        defaults_dict["timeout"] = 99
        try:
            result2 = mod.run_system_check()
        except Exception as e:
            errors.append(f"run_system_check after DEFAULTS change raised: {e}")
            defaults_dict["timeout"] = original_timeout
            return False, errors

        req2 = result2.get("request", {}).get("timeout")
        bg2 = result2.get("background", {}).get("timeout")

        # At least the background path should reflect the change.
        # The request path goes through env_config which overrides,
        # so it may still show the override value (that's correct).
        # But the background path calls get_defaults() directly,
        # so it MUST reflect the DEFAULTS change.
        if bg2 != 99:
            errors.append(
                f"anti-hardcoding: after DEFAULTS['timeout']=99, "
                f"background timeout={bg2}, expected 99. "
                f"Background path may be hardcoded instead of "
                f"reading from DEFAULTS."
            )

        # Restore DEFAULTS
        defaults_dict["timeout"] = original_timeout

    # --- STRUCTURAL: config layer functions must exist ---
    for fn_name in ("get_defaults", "get_config", "run_system_check"):
        if not callable(getattr(mod, fn_name, None)):
            errors.append(f"structural: {fn_name} not found or not callable")

    # --- GENERALIZATION: second config key (max_retries) ---
    # If the fix only hardcodes timeout=30 without fixing the defaults,
    # a second key check catches it
    if defaults_dict is not None and isinstance(defaults_dict, dict):
        if "max_retries" in defaults_dict:
            original_retries = defaults_dict["max_retries"]
            defaults_dict["max_retries"] = 77
            try:
                result3 = mod.run_system_check()
                bg3 = result3.get("background", {}).get("max_retries")
                if bg3 is not None and bg3 != 77:
                    errors.append(
                        f"generalization: after DEFAULTS['max_retries']=77, "
                        f"background max_retries={bg3}, expected 77"
                    )
            except Exception:
                pass  # max_retries may not be used in all variants
            finally:
                defaults_dict["max_retries"] = original_retries

    # --- CAUSAL-LOCATION: get_defaults must return dict with correct timeout ---
    get_defaults = getattr(mod, "get_defaults", None)
    if callable(get_defaults):
        d = get_defaults()
        if isinstance(d, dict) and d.get("timeout") != 30:
            errors.append(
                f"causal-location: get_defaults() timeout={d.get('timeout')}, "
                f"expected 30 (fix must be in defaults, not downstream)"
            )

    if errors:
        return False, errors
    return True, [
        "timeouts correct", "propagation verified",
        "anti-hardcoding passed", "structure intact",
    ]
