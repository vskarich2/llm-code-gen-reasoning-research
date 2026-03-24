#!/usr/bin/env bash
# Run T3 ablation.
# Usage: scripts/run_ablation.sh <model> [conditions] [parallel]
# Example: scripts/run_ablation.sh gpt-4o-mini baseline 6
#          scripts/run_ablation.sh gpt-4.1-nano baseline,diagnostic 6
set -euo pipefail
cd "$(dirname "$0")/.."
VENV="$(pwd)/.venv/bin"

MODEL="${1:?Usage: run_ablation.sh <model> [conditions] [parallel]}"
CONDITIONS="${2:-baseline}"
PARALLEL="${3:-6}"

exec "$VENV/python" runner.py --model "$MODEL" --conditions "$CONDITIONS" --parallel "$PARALLEL"
