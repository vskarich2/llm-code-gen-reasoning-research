#!/usr/bin/env python
"""Run ablation experiment from YAML config.

Usage:
    python scripts/run_ablation_config.py ablation_config.yaml
    python scripts/run_ablation_config.py ablation_config.yaml --dry-run
"""

import argparse
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    raise ImportError("pyyaml is required for config parsing. Install: pip install pyyaml")


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Run ablation from config")
    parser.add_argument("config", help="Path to YAML config file")
    parser.add_argument("--dry-run", action="store_true", help="Print commands only")
    args = parser.parse_args()

    config = load_config(args.config)
    models = config.get("models", [])
    conditions = config.get("conditions", [])
    cases_file = config.get("cases_file", "cases_v2.json")
    parallel = config.get("execution", {}).get("parallel", 6)

    base_dir = Path(__file__).resolve().parents[1]
    venv_python = base_dir / ".venv" / "bin" / "python"

    conds_str = ",".join(conditions)

    for model in models:
        cmd = [
            str(venv_python),
            str(base_dir / "runner.py"),
            "--model",
            model,
            "--cases",
            cases_file,
            "--conditions",
            conds_str,
            "--parallel",
            str(parallel),
        ]
        print(f"\n{'='*60}")
        print(f"Running: {model} × {len(conditions)} conditions")
        print(f"Command: {' '.join(cmd)}")
        print(f"{'='*60}")

        if args.dry_run:
            print("  [DRY RUN — skipped]")
            continue

        result = subprocess.run(cmd, cwd=str(base_dir))
        if result.returncode != 0:
            print(f"ERROR: {model} run failed with return code {result.returncode}")
            sys.exit(1)

    print("\nAll runs complete.")


if __name__ == "__main__":
    main()
