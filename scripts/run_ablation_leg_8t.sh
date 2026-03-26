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
MODELS=("gpt-5-mini" "gpt-4o-mini")

SMOKE=false
if [ "${1:-}" = "--smoke" ]; then
    SMOKE=true
fi

if [ "$SMOKE" = true ]; then
    TRIALS=1
    CASE_FILTER="--max-cases 3"
    echo "=== SMOKE TEST MODE (3 cases, 1 trial) ==="
else
    TRIALS=8
    CASE_FILTER=""
fi

ALL_CASES=$(.venv/bin/python -c "import json; print(len(json.loads(open('$CASES').read())))")
if [ "$SMOKE" = true ]; then
    N_CASES=3
else
    N_CASES=$ALL_CASES
fi
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

# ============================================================
# COST PROTECTION GATE
# ============================================================

echo "=== COST PROTECTION GATE ==="

# Step 1: Evaluator sanity ($0, <1s)
echo "  Checking evaluator sanity..."
.venv/bin/python -c "
import sys
sys.path.insert(0, '.')
from runner import load_cases
from exec_eval import exec_evaluate
from validate_cases_v2 import load_reference_code
cases = load_cases(cases_file='$CASES')
canary = next(c for c in cases if c['id'] == 'alias_config_a')
ref = load_reference_code(canary)
result = exec_evaluate(canary, ref)
if not result['pass']:
    print(f'EVALUATOR BROKEN: reference fix fails. reasons={result.get(\"reasons\", [])}')
    sys.exit(1)
print('  Evaluator sanity: PASS')
" || { echo "COST PROTECTION FAILED: evaluator is broken"; exit 1; }

# Step 2: Gate run (1 model × 5 cases, ~$0.02)
GATE_DIR=$(mktemp -d "${ABLATION_DIR}/gate_XXXXXX")
GATE_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]' | cut -c1-8)

echo "  Running gate: 1 model × 5 cases..."
.venv/bin/python runner.py \
    --model "${MODELS[0]}" \
    --trial 0 \
    --run-id "$GATE_UUID" \
    --run-dir "$GATE_DIR" \
    --cases "$CASES" \
    --conditions "$CONDITIONS" \
    --total-jobs 10 \
    --max-cases 5 \
    --quiet \
    > "$GATE_DIR/runner_output.txt" 2>&1

GATE_EXIT=$?
if [ $GATE_EXIT -ne 0 ]; then
    echo "  COST PROTECTION FAILED: gate run exited with code $GATE_EXIT"
    tail -20 "$GATE_DIR/runner_output.txt"
    rm -rf "$GATE_DIR"
    exit 1
fi

# Step 3: Validate gate results
.venv/bin/python scripts/validate_smoke.py \
    --run-dir "$GATE_DIR" \
    --cases "$CASES" \
    --canary alias_config_a \
    --verbose

VALIDATE_EXIT=$?
rm -rf "$GATE_DIR"
if [ $VALIDATE_EXIT -ne 0 ]; then
    echo "COST PROTECTION GATE FAILED — refusing to proceed with full ablation"
    exit 1
fi
echo "=== Cost protection gate PASSED ==="
echo

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
