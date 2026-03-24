#!/usr/bin/env bash
# Run the full T3 test suite.
# Usage: scripts/run_tests.sh [pytest-args...]
# Example: scripts/run_tests.sh -v
#          scripts/run_tests.sh tests/test_invariants.py -v
set -euo pipefail
cd "$(dirname "$0")/.."
VENV="$(pwd)/.venv/bin"
exec "$VENV/python" -m pytest "${@:--v}" tests/
