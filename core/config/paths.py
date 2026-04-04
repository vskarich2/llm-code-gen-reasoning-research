"""Central path module. Single source of truth for all repo-relative paths.

Rules:
- Only run/output roots may come from config or arbitrary string resolution.
- Repo asset paths must never come from config or arbitrary strings.
- No module in the critical path may reference repo layout except through this module.
"""

from pathlib import Path

# ── Repo root (computed once) ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Case data ──
CASE_DATA_DIR       = PROJECT_ROOT / "case_data"
CASES_V2_PATH       = CASE_DATA_DIR / "cases_v2.json"
TESTS_V2_DIR        = CASE_DATA_DIR / "tests_v2"
CODE_SNIPPETS_DIR   = CASE_DATA_DIR / "code_snippets_v2"
REFERENCE_FIXES_DIR = CASE_DATA_DIR / "reference_fixes"
AST_SPECS_PATH      = CASE_DATA_DIR / "ast_specs.json"
VALIDATION_DIR      = CASE_DATA_DIR / "validation"

# ── Prompts ──
PROMPTS_DIR         = PROJECT_ROOT / "core" / "prompts"
COMPONENTS_DIR      = PROMPTS_DIR / "components"
PROMPT_MANIFEST     = PROMPTS_DIR / "prompt_manifest.yaml"
COMPONENT_META      = PROMPTS_DIR / "component_metadata.yaml"

# ── Harness ──
HARNESS_SCRIPT      = PROJECT_ROOT / "core" / "harness" / "run_case.py"

# ── Default output root ──
DEFAULT_LOGS_DIR    = PROJECT_ROOT / "logs"

# ── Canonical output filenames ──
MANIFEST_FILENAME       = "manifest.json"
EVENTS_FILENAME         = "events.jsonl"
MERGED_EVENTS_FILENAME  = "merged_events.jsonl"
CONFIG_SNAPSHOT_FILENAME = "config.snapshot.yaml"
LOCK_FILENAME           = "orchestrator.lock"
HEARTBEAT_FILENAME      = "heartbeat.json"
TRIAL_CONFIG_FILENAME   = "trial_config.yaml"
STDOUT_LOG_FILENAME     = "stdout.log"
STDERR_LOG_FILENAME     = "stderr.log"


def resolve_run_dir(run_dir_str: str) -> Path:
    """Resolve configured output directory root.

    Only run/output roots may use this. Repo asset paths must never
    pass through this function.
    """
    p = Path(run_dir_str)
    return (p if p.is_absolute() else PROJECT_ROOT / p).resolve()


def resolve_test_path(family: str) -> Path:
    """Resolve test file path for a case family."""
    return TESTS_V2_DIR / f"test_{family}.py"
