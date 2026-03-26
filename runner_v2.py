"""Thin wrapper to call runner.py's main() directly.

Usage:
    .venv/bin/python runner_v2.py --model gpt-5.4-mini --cases cases_v2.json --conditions baseline --case-id l3_state_pipeline
    .venv/bin/python runner_v2.py --model gpt-5.4-mini --cases cases_v2.json --conditions baseline,leg_reduction
"""

from runner import main

if __name__ == "__main__":
    main()
