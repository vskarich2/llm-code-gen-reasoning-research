#!/usr/bin/env bash
# LEG Ablation: baseline + leg_reduction × 3 models × 8 trials
# Process-based: one OS process per (model, trial), max 8 concurrent.
#
# Usage:
#   bash scripts/run_ablation_leg_8t.sh
#   bash scripts/run_ablation_leg_8t.sh --smoke   (3 cases, 1 trial)
#
# Monitor:
#   watch -n5 cat logs/dashboard_gpt-5-mini.txt

set -euo pipefail
cd "$(dirname "$0")/.."

# ============================================================
# CONFIG
# ============================================================

CASES="cases_v2.json"
CONDITIONS="baseline,leg_reduction"
MODELS=("gpt-5.4-mini" "gpt-5-mini" "gpt-4o-mini")

SMOKE=false
if [ "${1:-}" = "--smoke" ]; then
    SMOKE=true
fi

if [ "$SMOKE" = true ]; then
    TRIALS=1
    # Use first 3 cases only for smoke test
    CASE_FILTER="--case-id alias_config_a"
    # We'll run 3 separate processes, one per model, each with 1 case
    # For a proper smoke test, we run 3 cases — but --case-id only takes one.
    # Instead, use a small cases file or run without filter and accept full cases.
    # For now: run all cases but only 1 trial. The smoke test e2e will verify counts.
    CASE_FILTER=""
    echo "=== SMOKE TEST MODE ==="
else
    TRIALS=8
    CASE_FILTER=""
fi

N_CASES=$(.venv/bin/python -c "import json; print(len(json.loads(open('$CASES').read())))")
N_CONDS=$(echo "$CONDITIONS" | tr ',' '\n' | wc -l | tr -d ' ')
N_MODELS=${#MODELS[@]}
TOTAL_PER_RUN=$((N_CASES * N_CONDS))
TOTAL=$((TOTAL_PER_RUN * TRIALS * N_MODELS))
MAX_CONCURRENT=8

echo "========================================"
echo "  LEG ABLATION (process-based)"
echo "  Cases: $N_CASES"
echo "  Conditions: $CONDITIONS"
echo "  Models: ${MODELS[*]}"
echo "  Trials: $TRIALS"
echo "  Max concurrent: $MAX_CONCURRENT"
echo "  Evals per run: $TOTAL_PER_RUN"
echo "  Total eval calls: $TOTAL"
echo "========================================"
echo

# ============================================================
# SETUP
# ============================================================

ABLATION_DIR="logs/ablation_runs"
mkdir -p "$ABLATION_DIR"

MANIFEST=$(mktemp)
trap "rm -f $MANIFEST" EXIT

# Generate work manifest: MODEL TRIAL UUID
for model in "${MODELS[@]}"; do
    for trial in $(seq 1 $TRIALS); do
        UUID=$(uuidgen | tr '[:upper:]' '[:lower:]' | cut -c1-8)
        echo "$model $trial $UUID" >> "$MANIFEST"
    done
done

TOTAL_WORKERS=$(wc -l < "$MANIFEST" | tr -d ' ')
echo "Generated manifest: $TOTAL_WORKERS workers"

# Pre-create all run directories (needed for stdout redirect in xargs)
while IFS=' ' read -r MODEL TRIAL UUID; do
    mkdir -p "${ABLATION_DIR}/run_${MODEL}_t${TRIAL}_${UUID}"
done < "$MANIFEST"

# ============================================================
# START DASHBOARD
# ============================================================

MODELS_CSV=$(IFS=,; echo "${MODELS[*]}")
.venv/bin/python scripts/update_dashboards.py \
    --ablation-dir "$ABLATION_DIR" \
    --models "$MODELS_CSV" \
    --n-cases "$N_CASES" \
    --n-conditions "$N_CONDS" \
    --n-trials "$TRIALS" &
DASHBOARD_PID=$!
echo "Dashboard process started: PID=$DASHBOARD_PID"

# ============================================================
# RUN WORKERS
# ============================================================

echo
echo "Launching $TOTAL_WORKERS workers (max $MAX_CONCURRENT concurrent)..."
echo

# Worker function
run_worker() {
    local MODEL="$1" TRIAL="$2" UUID="$3"
    local RUN_DIR="${ABLATION_DIR}/run_${MODEL}_t${TRIAL}_${UUID}"

    echo "[$(date "+%H:%M:%S")] START model=$MODEL trial=$TRIAL uuid=$UUID"

    .venv/bin/python runner.py \
        --model "$MODEL" \
        --trial "$TRIAL" \
        --run-id "$UUID" \
        --run-dir "$RUN_DIR" \
        --cases "$CASES" \
        --conditions "$CONDITIONS" \
        --total-jobs "$TOTAL_PER_RUN" \
        $CASE_FILTER \
        > "$RUN_DIR/runner_output.txt" 2>&1

    local EXIT_CODE=$?
    if [ $EXIT_CODE -ne 0 ]; then
        echo "[ERROR] FAILED model=$MODEL trial=$TRIAL (exit $EXIT_CODE)" >&2
        return $EXIT_CODE
    fi

    echo "[$(date "+%H:%M:%S")] DONE  model=$MODEL trial=$TRIAL"
}
export -f run_worker
export ABLATION_DIR CASES CONDITIONS TOTAL_PER_RUN CASE_FILTER

# Launch workers with bounded concurrency using background processes + wait
PIDS=()
WORKER_ERRORS=0

while IFS=' ' read -r MODEL TRIAL UUID; do
    # Wait if we've hit max concurrent
    while [ ${#PIDS[@]} -ge "$MAX_CONCURRENT" ]; do
        # Wait for any one child to finish
        for i in "${!PIDS[@]}"; do
            if ! kill -0 "${PIDS[$i]}" 2>/dev/null; then
                wait "${PIDS[$i]}" || WORKER_ERRORS=$((WORKER_ERRORS + 1))
                unset 'PIDS[$i]'
                PIDS=("${PIDS[@]}")  # reindex
                break
            fi
        done
        sleep 0.1
    done

    run_worker "$MODEL" "$TRIAL" "$UUID" &
    PIDS+=($!)
done < "$MANIFEST"

# Wait for remaining workers
for pid in "${PIDS[@]}"; do
    wait "$pid" || WORKER_ERRORS=$((WORKER_ERRORS + 1))
done

XARGS_EXIT=$WORKER_ERRORS

# ============================================================
# STOP DASHBOARD
# ============================================================

echo
echo "Stopping dashboard process..."
kill "$DASHBOARD_PID" 2>/dev/null || true
wait "$DASHBOARD_PID" 2>/dev/null || true

# ============================================================
# REPORT
# ============================================================

echo
if [ "$XARGS_EXIT" -ne 0 ]; then
    echo "========================================"
    echo "  [ERROR] One or more workers FAILED (xargs exit=$XARGS_EXIT)"
    echo "  Check runner_output.txt in each run dir for details."
    echo "========================================"
    echo
    echo "  Failed runs:"
    for dir in "$ABLATION_DIR"/run_*; do
        if [ -f "$dir/runner_output.txt" ] && grep -q "Traceback" "$dir/runner_output.txt" 2>/dev/null; then
            echo "    $dir"
        fi
    done
    exit 1
fi

echo "========================================"
echo "  ALL $TOTAL_WORKERS WORKERS COMPLETE"
echo "  Total eval calls: $TOTAL"
echo "========================================"
echo
echo "  Next steps:"
echo "    .venv/bin/python scripts/merge_and_validate.py --ablation-dir $ABLATION_DIR --n-models $N_MODELS --n-cases $N_CASES --n-conditions $N_CONDS --n-trials $TRIALS"
echo "    .venv/bin/python scripts/paper_analysis.py --input logs/events_merged.jsonl --output-dir logs/paper_outputs"
echo
echo "  Dashboards:"
for model in "${MODELS[@]}"; do
    echo "    watch -n5 cat logs/dashboard_${model}.txt"
done
