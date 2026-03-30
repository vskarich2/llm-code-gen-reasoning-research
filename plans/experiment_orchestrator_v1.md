# Experiment Orchestrator — System Design

**Date:** 2026-03-28
**Status:** Plan (no code yet)
**Replaces:** `scripts/run_ablation_leg_8t.sh` + manual bash orchestration

---

## 1. High-Level Architecture

```
┌─────────────────────┐
│  experiment.yaml     │  ← single source of truth
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│  Orchestrator        │  ← generates work items, manages pool
│  (orchestrator.py)   │
└──────────┬──────────┘
           │
    ┌──────▼──────┐
    │ ProcessPool  │  ← concurrent.futures.ProcessPoolExecutor
    │ (N workers)  │
    └──┬───┬───┬──┘
       │   │   │
    ┌──▼┐ ┌▼──┐┌▼──┐
    │W1 │ │W2 ││W3 │  ← each worker: one (model, condition, trial)
    └─┬─┘ └─┬─┘└─┬─┘
      │     │    │
    ┌─▼─┐ ┌─▼─┐┌─▼─┐
    │run│ │run││run│  ← isolated directory per run
    └───┘ └───┘└───┘
           │
┌──────────▼──────────┐
│  Aggregator          │  ← reads completed runs, computes metrics
│  (aggregate.py)      │
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│  Dashboard           │  ← consumes aggregated metrics
└─────────────────────┘
```

**Separation of concerns:**
- **Config** defines WHAT to run (models, conditions, trials, cases)
- **Orchestrator** decides WHEN and WHERE to run (scheduling, parallelism)
- **Worker** does ONE run (model × condition × trial) in isolation
- **Aggregator** computes metrics AFTER runs complete (no shared writes)
- **Dashboard** displays metrics (read-only consumer)

No component writes to another component's files. Workers never write global state.

---

## 2. Experiment Config Design

### Schema

```yaml
experiment:
  name: "baseline_vs_leg_v2"
  description: "Compare baseline and LEG-reduction across 3 models"
  seed: 42

models:
  generation:
    - name: "gpt-5.4-mini"
      temperature: 0.0
      max_tokens: 4096
    - name: "gpt-5-mini"
      temperature: 0.0
      max_tokens: 4096
    - name: "gpt-4o-mini"
      temperature: 0.0
      max_tokens: 4096

  evaluator:
    name: "gpt-5.4-mini"
    temperature: 0.0

conditions:
  - baseline
  - leg_reduction

trials: 8

cases:
  source: "cases_v2.json"
  max_cases: 0  # 0 = all

execution:
  parallelism: 8
  timeout_per_run_seconds: 600
  retry_failed: false

output:
  base_dir: "experiments/"
  # Final path: experiments/{name}/{model}/{condition}/trial_{i}/

preflight:
  validate_cases: true
  evaluator_sanity: true
  cost_gate_cases: 5
```

### Validation rules

At load time, the orchestrator validates:
1. All model names are non-empty strings
2. All conditions are in `VALID_CONDITIONS` from constants.py
3. `trials >= 1`
4. `parallelism >= 1` and `<= 32`
5. `cases.source` file exists and has `>= 1` case
6. Output directory is writable
7. No duplicate model/condition pairs

Validation failure → hard crash with specific error. No partial execution.

### Extensibility

Adding a new condition: add string to `conditions` list. The runner already knows how to dispatch (via `execution.py:build_prompt`).

Adding a new model: add entry to `models.generation` list.

Adding a new metric: change the aggregator, not the orchestrator or workers.

---

## 3. Orchestrator Design

### Job generation

```python
work_items = []
for model in config.models.generation:
    for condition in config.conditions:
        for trial in range(1, config.trials + 1):
            work_items.append(WorkItem(
                model=model.name,
                condition=condition,
                trial=trial,
                run_id=f"{model.name}_{condition}_t{trial}_{uuid4().hex[:8]}",
            ))
```

Total work items = `len(models) × len(conditions) × trials`.

Example: 3 models × 2 conditions × 8 trials = 48 work items.

### Scheduling

```python
with ProcessPoolExecutor(max_workers=config.execution.parallelism) as pool:
    futures = {pool.submit(run_single, item, config): item for item in work_items}
    for future in as_completed(futures):
        item = futures[future]
        try:
            result = future.result()
            log_completion(item, result)
        except Exception as e:
            log_failure(item, e)
```

Work items are submitted all at once. The pool handles scheduling. `as_completed` provides real-time progress reporting.

### Progress reporting

The orchestrator prints progress to stdout:
```
[12/48] gpt-5.4-mini/baseline/t3 DONE (58 cases, 54 pass, 93.1%)
[13/48] gpt-5-mini/leg_reduction/t1 DONE (58 cases, 47 pass, 81.0%)
[14/48] gpt-4o-mini/baseline/t2 FAILED: RuntimeError: API timeout
```

No shared files. Progress is tracked in the orchestrator process only.

---

## 4. Run Execution Model

### What a single run does

```python
def run_single(item: WorkItem, config: ExperimentConfig) -> RunResult:
    # 1. Create isolated run directory
    run_dir = config.output.base_dir / item.model / item.condition / f"trial_{item.trial}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # 2. Write metadata
    write_metadata(run_dir, item, config)

    # 3. Load cases
    cases = load_cases(config.cases.source)

    # 4. For each case: prompt → generate → parse → reconstruct → evaluate
    events = []
    for case in cases:
        event = run_case(case, item.model, item.condition, config)
        events.append(event)
        append_event(run_dir / "events.jsonl", event)

    # 5. Write run-level metrics
    metrics = compute_run_metrics(events)
    write_json(run_dir / "metrics.json", metrics)

    # 6. Return summary
    return RunResult(item=item, metrics=metrics, error=None)
```

### Inputs
- `WorkItem`: model name, condition, trial number, run_id
- `ExperimentConfig`: full config (cases, model params, evaluator settings)

### Outputs (per run directory)
- `metadata.json`: model, condition, trial, config_hash, timestamps, git hash
- `events.jsonl`: one line per (case × condition) evaluation
- `metrics.json`: aggregate pass rate, score distribution for this run
- `calls/`: per-LLM-call logs (prompt, response, latency)

### Isolation guarantees
- Each worker writes ONLY to its own `run_dir`
- No shared mutable state between workers
- No global file writes
- If a worker crashes, only its directory is affected
- Other workers continue unaffected

---

## 5. Logging System

### Directory structure

```
experiments/
  baseline_vs_leg_v2/              ← experiment name
    experiment.yaml                 ← frozen copy of config
    manifest.json                   ← list of all runs with status

    gpt-5.4-mini/
      baseline/
        trial_1/
          metadata.json
          events.jsonl
          metrics.json
          calls/
            000001.json
            000002.json
            ...
        trial_2/
          ...
      leg_reduction/
        trial_1/
          ...

    gpt-5-mini/
      baseline/
        ...

    aggregated/                     ← written by aggregator, not workers
      per_model.json
      per_condition.json
      per_trial.json
      dashboard.json
```

### File formats

**metadata.json** (written once at run start, updated at run end):
```json
{
  "model": "gpt-5.4-mini",
  "condition": "baseline",
  "trial": 1,
  "run_id": "gpt-5.4-mini_baseline_t1_a3f8c2d1",
  "config_hash": "sha256:abc123...",
  "prompt_version": "sha256:def456...",
  "git_hash": "1f173ea",
  "start_time": "2026-03-28T10:00:00",
  "end_time": "2026-03-28T10:05:23",
  "total_cases": 58,
  "status": "completed"
}
```

**events.jsonl** (append-only, one line per case evaluation):
```json
{"case_id": "alias_config_a", "pass": true, "score": 1.0, "code_correct": true, "reasoning_correct": null, "elapsed_seconds": 3.2, "timestamp": "..."}
```

**metrics.json** (written once at run end):
```json
{
  "pass_rate": 0.937,
  "total_cases": 58,
  "total_pass": 54,
  "mean_score": 0.89,
  "ran_rate": 1.0
}
```

### Write guarantees

- `events.jsonl`: append-only, one `os.write()` + `os.fsync()` per event (same as current `emit_event`)
- `metadata.json`: written atomically (write to `.tmp`, fsync, rename)
- `metrics.json`: written once after all cases complete
- No file is written by more than one process

---

## 6. Metrics Aggregation

### When aggregation happens

The aggregator runs as a separate step AFTER workers complete. NOT during execution. NOT in workers.

```python
# Orchestrator calls after all workers finish:
aggregate_experiment("experiments/baseline_vs_leg_v2/")
```

### What it computes

**Per model:**
```json
{
  "gpt-5.4-mini": {
    "baseline": {"pass_rate": 0.937, "n_trials": 8, "std": 0.02},
    "leg_reduction": {"pass_rate": 0.810, "n_trials": 8, "std": 0.03}
  }
}
```

**Per condition (across models):**
```json
{
  "baseline": {"mean_pass_rate": 0.925, "models": 3},
  "leg_reduction": {"mean_pass_rate": 0.805, "models": 3}
}
```

**Per trial (for stability analysis):**
```json
{
  "gpt-5.4-mini": {
    "baseline": [0.93, 0.95, 0.94, 0.93, 0.92, 0.95, 0.94, 0.93]
  }
}
```

### How dashboard consumes

The aggregator writes `aggregated/dashboard.json` in the format the existing dashboard expects. The dashboard reads this file — no change to dashboard code needed.

---

## 7. Parallelism Model

### Process pool design

```python
ProcessPoolExecutor(max_workers=min(config.execution.parallelism, len(work_items)))
```

Each worker is a separate OS process. No shared memory. No threads. No GIL contention.

### Task queue

All work items are submitted upfront. The pool's internal queue handles ordering. Workers pull the next item when they finish.

### Resource limits

- Default parallelism: 8 (matches current ablation script)
- API rate limiting: each worker makes sequential API calls for its cases. With 8 workers × ~2 calls per case (generation + classifier), peak is ~16 concurrent API calls. OpenAI rate limits handle this.
- Memory: each worker loads one case at a time. No accumulation.
- Disk: each worker writes to its own directory. No contention.

### Graceful shutdown

On `SIGINT` or `SIGTERM`:
1. Orchestrator catches signal
2. Calls `pool.shutdown(wait=False, cancel_futures=True)`
3. Running workers finish their current case (not mid-API-call), write partial results
4. Orchestrator writes manifest with `status: "interrupted"` for incomplete runs
5. Clean exit

---

## 8. Failure Handling Strategy

### Run-level failures

If a worker raises an exception:
1. The `ProcessPoolExecutor` catches it
2. The orchestrator logs: `{run_id} FAILED: {error}`
3. The manifest records `status: "failed"` with error details
4. Other workers continue unaffected

### Case-level failures

If a single case fails within a run (API error, parse error, execution crash):
1. The error is recorded in `events.jsonl` with `pass: false` and error details
2. The run continues to the next case
3. Run-level metrics reflect the failure

### Retry policy

Default: `retry_failed: false`. Failed runs are NOT retried automatically.

If `retry_failed: true`:
- After all initial runs complete, the orchestrator re-submits failed runs (same config, new run_id)
- Maximum 1 retry per run
- Both attempts are recorded in the manifest

### Partial experiment handling

If the orchestrator is interrupted:
- Completed runs have full data in their directories
- Incomplete runs have partial `events.jsonl` (whatever was written before interruption)
- The manifest shows which runs completed, which failed, which were interrupted
- Re-running with the same config will detect existing completed runs and skip them (idempotent)

---

## 9. Reproducibility Guarantees

### Config hashing

```python
config_hash = sha256(canonical_yaml(config)).hexdigest()
```

The config is serialized deterministically (sorted keys, no comments) and hashed. Every run records this hash. Same config → same hash → same experiment parameters.

### Metadata recording

Every run records:
- `config_hash`: proves the config hasn't changed
- `git_hash`: proves the code hasn't changed
- `prompt_version`: hash of the rendered prompt template (from assembly engine)
- `model`: exact model name and parameters
- `timestamp`: when the run started
- `seed`: random seed (if applicable)

### Deterministic behavior

- Temperature = 0 for all models (set in config, enforced)
- Cases processed in the same order (sorted by case_id)
- No randomness in prompt construction, assembly, or evaluation
- The only non-determinism is the LLM API itself (temperature=0 is near-deterministic but not guaranteed by all providers)

### Re-running

To reproduce an experiment:
1. Check out the git hash from the metadata
2. Use the frozen `experiment.yaml` from the experiment directory
3. Run the orchestrator with that config
4. Results will match within LLM non-determinism

---

## 10. Migration Plan

### Phase 1: Implement orchestrator (replaces bash script)

New files:
- `orchestrate.py` — main entry point
- `experiment_schema.py` — config loading and validation (extend existing `experiment_config.py`)

Usage:
```bash
.venv/bin/python orchestrate.py --config experiments/baseline_vs_leg_v2.yaml
```

The orchestrator calls `runner.py:run_single_case()` (extract from existing `_run_ablation_mode`) for each work item. No changes to the evaluation pipeline.

### Phase 2: Implement aggregator (replaces dashboard updater)

New file:
- `aggregate.py` — reads completed run directories, writes aggregated metrics

Replaces: `scripts/update_dashboards.py` (the background process that scanned run dirs every 30s)

### Phase 3: Preflight integration

The orchestrator runs preflight checks before submitting any work:
1. `validate_cases_v2.py` checks (all 5 + metadata alignment)
2. Evaluator sanity (exec_evaluate on canary case)
3. Cost gate (run N cases, verify pass_rate > 0)
4. Config validation

All checks must pass before any API call is made.

### Phase 4: Remove bash scripts

After the orchestrator is stable:
- Delete `scripts/run_ablation_leg_8t.sh`
- Delete `scripts/update_dashboards.py`
- Delete `scripts/validate_smoke.py` (absorbed into orchestrator preflight)
- Update Makefile: `make run` → `python orchestrate.py --config <yaml>`

### Minimal disruption

- The evaluation pipeline (`exec_eval.py`, `evaluator.py`, `execution.py`, `parse.py`) is UNCHANGED
- The test infrastructure (`tests_v2/`, `validate_cases_v2.py`) is UNCHANGED
- The config system (`experiment_config.py`, `configs/`) is EXTENDED, not replaced
- Workers call the same `evaluate_output()` → `exec_evaluate()` path as today

The migration is a new orchestration layer on top of the existing pipeline, not a rewrite of the pipeline itself.
