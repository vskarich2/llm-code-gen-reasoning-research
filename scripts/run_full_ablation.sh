#!/usr/bin/env bash
# Full ablation: 3 models x 5 trials x 58 cases x 2 conditions = 1740 evals
# Parallelism: up to 6 concurrent runner processes
# Resume-safe: re-run this script to pick up where it left off.
#
# Usage:
#   bash scripts/run_full_ablation.sh

set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=".venv/bin/python"
MAX_PARALLEL=6
LOG_DIR="logs/ablation_full"
CONFIGS_DIR="configs/ablation_full"

mkdir -p "$LOG_DIR"

# Collect all 15 config_storage
CONFIGS=($(ls "$CONFIGS_DIR"/*.yaml | sort))
echo "=== FULL ABLATION ==="
echo "  Configs: ${#CONFIGS[@]}"
echo "  Parallelism: $MAX_PARALLEL"
echo ""

# For each config, find its matching timestamp dir (if any) for resume.
# Match by run_id in metadata.json.
find_resume_dir() {
    local cfg="$1"
    local run_id
    run_id=$($PYTHON -c "import yaml; c=yaml.safe_load(open('$cfg')); print(c['run']['run_id'])")
    local model_dir
    model_dir=$($PYTHON -c "import yaml; c=yaml.safe_load(open('$cfg')); print(c['run']['run_dir'])")

    if [ ! -d "$model_dir" ]; then
        echo ""
        return
    fi

    for ts_dir in $(ls -1r "$model_dir" 2>/dev/null); do
        local meta="$model_dir/$ts_dir/metadata.json"
        if [ -f "$meta" ]; then
            local meta_run_id
            meta_run_id=$($PYTHON -c "import json; print(json.load(open('$meta')).get('run_id',''))")
            if [ "$meta_run_id" = "$run_id" ]; then
                local events="$model_dir/$ts_dir/events.jsonl"
                if [ -f "$events" ]; then
                    local n_events
                    n_events=$(wc -l < "$events" | tr -d ' ')
                    if [ "$n_events" -gt 0 ] && [ "$n_events" -lt 116 ]; then
                        # 116 = 58 cases x 2 conditions = complete single trial
                        echo "$ts_dir"
                        return
                    fi
                fi
            fi
        fi
    done
    echo ""
}

echo "Scanning for resumable runs..."
declare -A RESUME_ARGS
SKIP_COUNT=0
for cfg in "${CONFIGS[@]}"; do
    resume_dir=$(find_resume_dir "$cfg")
    if [ -n "$resume_dir" ]; then
        RESUME_ARGS["$cfg"]="--resume $resume_dir"
        n_events=$(wc -l < "$($PYTHON -c "import yaml; c=yaml.safe_load(open('$cfg')); print(c['run']['run_dir'])")/$resume_dir/events.jsonl" | tr -d ' ')
        echo "  RESUME: $(basename $cfg .yaml) -> $resume_dir ($n_events events)"
    fi
    # Check if already complete (116 events)
    run_dir=$($PYTHON -c "import yaml; c=yaml.safe_load(open('$cfg')); print(c['run']['run_dir'])")
    run_id=$($PYTHON -c "import yaml; c=yaml.safe_load(open('$cfg')); print(c['run']['run_id'])")
    for ts_dir in $(ls -1r "$run_dir" 2>/dev/null); do
        meta="$run_dir/$ts_dir/metadata.json"
        if [ -f "$meta" ]; then
            meta_run_id=$($PYTHON -c "import json; print(json.load(open('$meta')).get('run_id',''))" 2>/dev/null || echo "")
            if [ "$meta_run_id" = "$run_id" ]; then
                events="$run_dir/$ts_dir/events.jsonl"
                if [ -f "$events" ]; then
                    n=$(wc -l < "$events" | tr -d ' ')
                    if [ "$n" -ge 116 ]; then
                        echo "  COMPLETE: $(basename $cfg .yaml) ($n events) — skipping"
                        RESUME_ARGS["$cfg"]="SKIP"
                        SKIP_COUNT=$((SKIP_COUNT + 1))
                    fi
                fi
            fi
        fi
    done 2>/dev/null || true
done
echo "  $SKIP_COUNT already complete"
echo ""

# Launch processes
RUNNING=0
PIDS=()
CFG_NAMES=()

for cfg in "${CONFIGS[@]}"; do
    resume_arg="${RESUME_ARGS[$cfg]:-}"

    # Skip completed runs
    if [ "$resume_arg" = "SKIP" ]; then
        continue
    fi

    name=$(basename "$cfg" .yaml)
    log_file="$LOG_DIR/${name}.log"

    echo "[LAUNCH] $name ${resume_arg:+(resuming)}"
    $PYTHON runner.py --config "$cfg" $resume_arg >> "$log_file" 2>&1 &
    PIDS+=($!)
    CFG_NAMES+=("$name")
    RUNNING=$((RUNNING + 1))

    if [ "$RUNNING" -ge "$MAX_PARALLEL" ]; then
        wait -n || true
        RUNNING=$((RUNNING - 1))
    fi
done

echo ""
echo "${#PIDS[@]} processes launched. Waiting..."
echo ""
echo "Monitor with:"
echo "  .venv/bin/python scripts/monitor_ablation.py"
echo ""

# Wait for all
FAILURES=0
for i in "${!PIDS[@]}"; do
    if ! wait "${PIDS[$i]}"; then
        echo "  FAILED: ${CFG_NAMES[$i]}"
        FAILURES=$((FAILURES + 1))
    else
        echo "  DONE: ${CFG_NAMES[$i]}"
    fi
done

echo ""
echo "=== COMPLETE ==="
echo "  Total launched: ${#PIDS[@]}, Failed: $FAILURES, Skipped: $SKIP_COUNT"
if [ "$FAILURES" -gt 0 ]; then
    echo "  Re-run this script to resume failed runs."
fi
