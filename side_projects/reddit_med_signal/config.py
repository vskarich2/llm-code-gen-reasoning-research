"""Configuration loader. Reads YAML config and exposes typed settings."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

_log = logging.getLogger("reddit_med_signal.config")

_PROJECT_ROOT = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _PROJECT_ROOT / "config" / "default.yaml"


def load_config(path: str | Path | None = None) -> dict:
    """Load YAML config. Falls back to default.yaml if no path given."""
    config_path = Path(path) if path else _DEFAULT_CONFIG
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    _log.info("Loaded config from %s", config_path)
    return cfg


def get_project_root() -> Path:
    return _PROJECT_ROOT


def get_data_dir() -> Path:
    return _PROJECT_ROOT / "case_data"


def get_reports_dir() -> Path:
    return _PROJECT_ROOT / "reports"


def get_prompts_dir() -> Path:
    return _PROJECT_ROOT / "prompts"


def get_reddit_credentials() -> dict:
    """Read Reddit API credentials from environment variables."""
    client_id = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    user_agent = os.environ.get("REDDIT_USER_AGENT", "reddit_med_signal/0.1")
    if not client_id or not client_secret:
        raise RuntimeError(
            "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET must be set as env vars"
        )
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "user_agent": user_agent,
    }
