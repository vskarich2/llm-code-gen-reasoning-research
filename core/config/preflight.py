"""Preflight validation. Fails fast if canonical assets are missing or output roots are invalid.

Called at runner/orchestrator startup before workers launch.
"""

from core.config.paths import (
    CASE_DATA_DIR, CASES_V2_PATH, TESTS_V2_DIR, COMPONENTS_DIR,
    PROMPT_MANIFEST, HARNESS_SCRIPT, resolve_run_dir,
)


def validate_startup(config=None) -> None:
    """Check that all canonical assets exist and output root is writable.

    Raises RuntimeError with structured error summary on failure.
    """
    missing = []
    for name, path in [
        ("CASE_DATA_DIR", CASE_DATA_DIR),
        ("CASES_V2_PATH", CASES_V2_PATH),
        ("TESTS_V2_DIR", TESTS_V2_DIR),
        ("COMPONENTS_DIR", COMPONENTS_DIR),
        ("PROMPT_MANIFEST", PROMPT_MANIFEST),
        ("HARNESS_SCRIPT", HARNESS_SCRIPT),
    ]:
        if not path.exists():
            missing.append(f"{name}: {path}")

    if config and hasattr(config, "run") and hasattr(config.run, "run_dir"):
        run_dir = resolve_run_dir(config.run.run_dir)
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            probe = run_dir / ".preflight_probe"
            probe.write_text("ok")
            probe.unlink()
        except OSError as e:
            missing.append(f"run_dir not writable: {run_dir} ({e})")

    if missing:
        raise RuntimeError(
            "Preflight failed — missing or invalid assets:\n"
            + "\n".join(f"  {m}" for m in missing)
        )
