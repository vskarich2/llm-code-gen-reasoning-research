#!/bin/bash
# V2 Ablation: baseline + leg_reduction × 3 models × 2 trials
# 696 total eval calls
#
# Usage: bash scripts/run_ablation_v2.sh
# Monitor: watch -n5 cat logs/live_metrics_dashboard.txt

set -e
cd "$(dirname "$0")/.."

CASES="cases_v2.json"
CONDITIONS="baseline,leg_reduction"
PARALLEL=8
MODELS=("gpt-5-mini" "gpt-4o-mini" "gpt-5.4-mini")
TRIALS=2

N_CASES=$(".venv/bin/python" -c "import json; print(len(json.loads(open('$CASES').read())))")
N_CONDS=$(echo "$CONDITIONS" | tr ',' '\n' | wc -l | tr -d ' ')
TOTAL_EVALS=$((N_CASES * N_CONDS * ${#MODELS[@]} * TRIALS))

echo "========================================"
echo "  V2 ABLATION"
echo "  Cases: $N_CASES"
echo "  Conditions: $CONDITIONS"
echo "  Models: ${MODELS[*]}"
echo "  Trials: $TRIALS"
echo "  Parallel: $PARALLEL"
echo "  Total eval calls: $TOTAL_EVALS"
echo "========================================"
echo

FIRST_RUN=true

for trial in $(seq 1 $TRIALS); do
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  TRIAL $trial / $TRIALS"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    for model in "${MODELS[@]}"; do
        echo
        echo "▸ Model: $model (trial $trial)"
        echo "  Starting at $(date '+%H:%M:%S')"

        CLEAR_FLAG=""
        if [ "$FIRST_RUN" = true ]; then
            CLEAR_FLAG="--clear-events"
            FIRST_RUN=false
        fi

        .venv/bin/python runner.py \
            --cases "$CASES" \
            --model "$model" \
            --conditions "$CONDITIONS" \
            --parallel "$PARALLEL" \
            --total-jobs "$TOTAL_EVALS" \
            $CLEAR_FLAG \
            2>&1 | tee "/tmp/ablation_${model}_t${trial}.txt" | tail -5

        echo "  Finished at $(date '+%H:%M:%S')"

        # Brief pause between models to ensure log timestamps don't collide
        sleep 2
    done
done

echo
echo "========================================"
echo "  ABLATION COMPLETE"
echo "  Logs: logs/"
echo "  Dashboard: logs/live_metrics_dashboard.txt"
echo "========================================"
