# Live Run Dashboard — Plan v1

## Problem

There's no way to monitor a running experiment from the dashboard. You launch a run, then have to `tail -f` log files and `jq` the manifest to understand what's happening. The dashboard only works on completed experiments.

## Goal

A "Live Run" tab in the dashboard that shows real-time progress of an active experiment — progress bar, live metrics, error stream — by reading the manifest and worker event files while the orchestrator is running.

## What already exists

1. **`orchestrate.py`** — the multi-worker orchestrator. Writes:
   - `manifest.json` — canonical state. Updated atomically on every state transition (PENDING → RUNNING → SUCCEEDED/FAILED). Contains all work items with state, attempt, exit_code, error.
   - `config.snapshot.yaml` — frozen config at launch time.
   - `merged_events.jsonl` — appended as workers complete and get merged.
   - Per-worker: `heartbeat.json` (every 30s), `events.jsonl`, `stdout.log`, `stderr.log`.

2. **`runner.py`** — the per-worker runner. Writes heartbeat every 30s with: work_id, instance_id, pid, current_case_id, cases_completed, sequence.

3. **`dashboard/live_loader.py`** — already has `LiveState` with incremental WAL reading (file offset tracking). Currently only used by the "Live Mode" toggle which just reloads the whole experiment periodically.

4. **`dashboard/app.py`** — has a `live_mode` toggle with `poll_interval` slider.

## Design

### Data source: manifest.json (not events)

The manifest is the single source of truth for run progress. It's updated atomically by the orchestrator on every state transition. Reading it gives us:
- Total work items and their states (PENDING, RUNNING, SUCCEEDED, FAILED)
- Per-item: model, condition, trial, case_id, attempt count, exit_code, error message
- Overall status (running, completed, failed)
- Timestamps (started_at, completed_at per item)

This is much simpler and more reliable than parsing events.jsonl for progress.

### Architecture

```
New tab: "Live Run"

User selects a run directory (any dir with manifest.json)
  ↓
Dashboard polls manifest.json every N seconds
  ↓
Renders:
  1. Progress bar (SUCCEEDED+FAILED / total)
  2. State summary cards (PENDING, RUNNING, SUCCEEDED, FAILED counts)
  3. Live pass rate (from merged_events.jsonl as it grows)
  4. Error stream (FAILED items with error messages)
  5. Active workers (RUNNING items with heartbeat info)
  6. Config snapshot
```

### Components

#### 1. Run selector (sidebar or tab-level)

Scan `logs/` for directories containing `manifest.json`. Show them sorted by modification time. User picks one. Could also accept a path input for custom locations.

#### 2. Manifest poller

```python
def load_manifest(run_dir: Path) -> dict:
    manifest_path = run_dir / "manifest.json"
    return json.loads(manifest_path.read_text())
```

Called every poll cycle. Manifest is typically <1MB even for large runs (1700 items = ~500KB). Fast to read.

#### 3. Progress bar

```
[████████████░░░░░░░░] 1700/1740 (97.7%) — 1700 succeeded, 0 running, 40 failed
```

Use `st.progress()` for the bar, `st.metric()` cards for counts.

Progress = (SUCCEEDED + FAILED) / total. RUNNING items are in-flight.

#### 4. Live metrics

As workers complete, their events get merged into `merged_events.jsonl`. We can incrementally read this (using the existing `LiveState` pattern) and compute live pass rate, LEG rate, etc.

This won't have ALL results until the run is done, but it'll show the trend as results come in.

#### 5. Error stream

Filter manifest work items where `state == "FAILED"`. Show:
- work_id (which tells you model, condition, trial, case)
- error message
- attempt number
- Optionally: link to stderr.log

#### 6. Active workers table

Filter `state == "RUNNING"`. For each, read heartbeat.json to get:
- PID (is it still alive?)
- Current case_id
- Cases completed
- Last heartbeat time (stale = possibly hung)

#### 7. Config display

Same as overview tab — read `config.snapshot.yaml` and display.

### Files to create/modify

| File | Change |
|------|--------|
| `dashboard/views/live_run.py` | **NEW** — the Live Run tab renderer |
| `dashboard/data/manifest_loader.py` | **NEW** — manifest.json + heartbeat reader |
| `dashboard/app.py` | Add "Live Run" tab to TAB_ORDER, render it |
| `dashboard/components/sidebar.py` | Add run directory selector for live monitoring |

### What this does NOT do

- Does NOT launch runs (user launches via `python orchestrate.py --config ...` as before)
- Does NOT modify the orchestrator or runner code
- Does NOT use websockets or server-sent events — just file polling via Streamlit's rerun model
- Does NOT replace the existing experiment loader — completed runs still load via the existing path

### Polling strategy

Use Streamlit's existing `live_mode` + `st.rerun()` pattern. When the Live Run tab is active and a run is selected:
1. Read manifest.json
2. If status is "running", auto-refresh every `poll_interval` seconds
3. If status is "completed" or "failed", stop polling

### Risks

- **Manifest read during atomic write**: The orchestrator writes manifest atomically (write-then-rename). A partial read shouldn't happen, but we should catch JSON decode errors gracefully.
- **Large merged_events.jsonl**: For long runs, the merged file grows. The LiveState offset tracker handles this — only reads new lines.
- **Stale heartbeats**: A worker can crash without updating heartbeat. Show "last seen" time and flag if >60s stale.

### UX sketch

```
Live Run
─────────────────────────────────────────
[Select run: ▼ v3_full_ablation         ]

Status: RUNNING          Elapsed: 12m 34s
[████████████████░░░░] 1420/1740 (81.6%)

 SUCCEEDED    RUNNING    FAILED    PENDING
   1400         12         8         320

Pass Rate (so far): 82.4%    LEG Rate: 5.2%

─── Errors (8) ──────────────────────────
▶ gpt_5_mini__baseline_v2__trial_002__stale_cache_a
  attempt 1 | TimeoutError: subprocess timed out after 30s

▶ gpt_5_mini__baseline_v3__trial_001__async_race_lock
  attempt 2 | RECON_INVALID_CODE: syntax error in test.py

─── Active Workers (12) ─────────────────
  worker_001  PID 45231  case: alias_config_c  last heartbeat: 3s ago
  worker_002  PID 45232  case: commit_gate      last heartbeat: 1s ago
  ...

─── Config ──────────────────────────────
▶ config.snapshot.yaml
```
