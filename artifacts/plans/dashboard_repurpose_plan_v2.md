# Dashboard Repurpose Plan — v2

**Supersedes:** dashboard_repurpose_plan_v1.md
**Date:** 2026-04-03
**Status:** PLAN ONLY

---

## Corrections from v1

| v1 mistake | v2 fix |
|---|---|
| Aggregation unit = case | Aggregation unit = (model, condition) ablation pair |
| Summary-first dashboard | Inspection-first: file explorer is the primary feature |
| Retry as minor feature | Retry is first-class: trajectory classification, recovery rates, attempt-level data |
| Metrics computed loosely | Metrics derived ONLY from WAL events, pure functions, strict field validation |
| `load_logs.py` as data engine | New `load_wal()` → `build_attempt_table()` pipeline that preserves attempt-level granularity |
| Reuse run_scanner.py | Discard entirely. New `leg_scanner.py` built from scratch |
| Tech: vanilla JS rewrite | Tech: Streamlit — faster to ship, interactive tables/filters built-in |

---

## 1. Design Principles

**LOG-DRIVEN:** The single source of truth is `merged_events.jsonl` (WAL) per experiment directory plus per-worker artifact files. No derived state. No in-memory accumulation. Everything reconstructable from disk.

**ABLATION-CENTRIC:** Top-level aggregation is always (model, condition). Case and attempt are drill-down levels, not primary grouping.

**INSPECTION-FIRST:** The file explorer is the most important feature. For any data point in any table, the user can drill down to the exact prompt, response, parsed JSON, reconstructed code, and execution result.

**RETRY-AWARE:** Retry dynamics are a first-class signal. Attempt chains are explicit. Trajectory classification (monotonic_fix, stagnation, oscillation, divergence) is computed and displayed.

---

## 2. Data Model

### 2.1 Canonical attempt-level DataFrame

One row per (case, model, condition, attempt). Built from WAL events only.

```
IDENTIFIERS
  run_id          str     from event run.run_id
  model           str     from event model
  condition       str     from event condition  
  case_id         str     from event case_id
  family          str     joined from cases_v2.json
  difficulty      str     joined from cases_v2.json
  trial_idx       int     from event trial
  attempt_idx     int     from event attempt (1-based)
  work_id         str     from event work_id
  instance_id     str     from event instance_id

EXECUTION
  exec_pass       bool    from payload.pass
  score           float   from payload.score
  tests_passed    int     from execution.tests_passed (nullable)
  tests_total     int     from execution.tests_run (nullable)
  runtime_ms      int     from execution.runtime_ms
  exec_category   str     from payload.execution_category

REASONING
  reasoning_correct   bool    from reasoning.reasoning_correct
  mechanism_label     str     from reasoning.failure_type
  confidence          str     from reasoning.confidence
  mechanism_dim       str     from payload.mechanism_identified_dim
  commitments_dim     str     from payload.commitments_extracted_dim
  satisfied_dim       str     from payload.commitments_satisfied_dim
  alignment_dim       str     from payload.reasoning_code_alignment_dim

LEG SIGNALS (derived, pure functions)
  is_leg          bool    reasoning_correct AND NOT exec_pass
  is_lucky_fix    bool    NOT reasoning_correct AND exec_pass

RETRY
  is_retry        bool    attempt_idx > 1
  retry_type      str     from condition name (bare_retry, critique_strict, reasoning_only, etc.)
  n_attempts      int     total attempts for this (case, model, condition, trial)

PARSE
  parse_success   bool    from v2_artifact.parse_status == "success"

ARTIFACTS (paths, NOT inline)
  worker_dir      str     path to worker directory
  prompt_path     str     path to calls_flat/NNNNNN_generation.txt
  response_path   str     same file (contains both prompt and response sections)
  classify_path   str     path to calls_flat/NNNNNN_classification.txt

TIMESTAMPS
  timestamp       str     from event timestamp
```

### 2.2 What is NOT in the DataFrame

- Full prompt text (stored on disk, referenced by path)
- Full response text (stored on disk, referenced by path)
- Reconstructed code (stored on disk)
- Classifier raw output (stored on disk)

These are accessed on-demand via the file explorer, never loaded into memory in bulk.

### 2.3 Data loading contract

```python
def load_wal(log_dir: Path) -> list[dict]:
    """Read merged_events.jsonl, return list of raw event dicts.
    
    ONLY reads case.end events (terminal events with results).
    No filtering. No transformation. Raw dicts from disk.
    Raises FileNotFoundError if WAL missing.
    """

def build_attempt_table(events: list[dict], cases_path: Path) -> pd.DataFrame:
    """Build canonical attempt-level DataFrame from raw events.
    
    - One row per case.end event
    - Joins family/difficulty from cases_v2.json
    - Computes derived LEG signals
    - Resolves artifact paths from work_id + attempt_idx
    - STRICT: raises on missing required fields, never silently drops
    """
```

---

## 3. Metric Functions (all pure, no side effects)

```python
def compute_ablation_summary(df) -> pd.DataFrame:
    """Group by (model, condition). Returns:
    pass_rate, leg_rate, lucky_fix_rate, reasoning_rate, 
    retry_success_rate, avg_attempts, count.
    """

def compute_family_breakdown(df) -> pd.DataFrame:
    """Group by (model, condition, family). Returns:
    pass_rate, leg_rate, count, delta_vs_baseline (if baseline present).
    """

def compute_retry_metrics(df) -> dict:
    """For retry conditions only. Returns:
    pct_improved, pct_degraded, pct_unchanged,
    trajectory_distribution: {monotonic_fix, stagnation, oscillation, divergence, single_shot},
    recovery_rate (fail→pass across attempts).
    """

def compute_case_deltas(df, cond_a, cond_b) -> pd.DataFrame:
    """Paired analysis on (case_id, model, trial_idx). Returns:
    per (case_id, model): pass_delta, leg_delta, paired_count.
    """

def classify_trajectory(attempts: pd.DataFrame) -> str:
    """For one (case, model, condition, trial) attempt chain. Returns:
    single_shot | monotonic_fix | stagnation | oscillation | divergence.
    """
```

---

## 4. Dashboard Structure (Streamlit)

### Tab 1: Ablation Overview

**Primary view.** Aggregated by (model, condition).

Content:
- Experiment selector (dropdown, multi-select for comparing experiments)
- Summary table: model × condition grid with pass_rate, LEG_rate, lucky_fix_rate, retry_success_rate, avg_attempts, count
- Color-coded cells: green >80% pass, yellow 30-80%, red <30%
- Click any cell → drills to Tab 2 filtered to that (model, condition)

### Tab 2: Family Breakdown

**Research-critical.** Shows where effects concentrate.

Content:
- Filtered by selected (model, condition) from Tab 1, or show all
- Table: family × metrics (pass_rate, LEG_rate, delta_vs_baseline)
- Condition comparison: side-by-side columns for baseline vs treatment
- Sortable by any column
- Click any family row → drills to Tab 4 filtered to that family

### Tab 3: Retry Analysis

**First-class retry signal.**

Content:
- Only retry conditions shown
- Top metrics: overall recovery rate, % improved, % degraded
- Trajectory distribution bar chart: monotonic_fix / stagnation / oscillation / divergence / single_shot
- Per-(case, model) table: attempt_1_pass, final_pass, trajectory_type, n_attempts
- Click any row → drills to Tab 4 showing the full attempt chain

### Tab 4: Attempt Inspector (FILE EXPLORER — HIGHEST PRIORITY)

**The core feature.** Full LLM trace inspection.

Selectors (cascading):
- Model → Condition → Case → Trial → Attempt

Display layout:

```
┌─────────────────────────────┬─────────────────────────────┐
│                             │                             │
│     PROMPT (full, raw)      │    RESPONSE (full, raw)     │
│     scrollable              │    scrollable               │
│                             │                             │
├─────────────────────────────┴─────────────────────────────┤
│                                                           │
│  PARSED JSON          │  EXECUTION RESULT                 │
│  - root_cause         │  - pass/fail                      │
│  - fix_strategy       │  - score                          │
│  - files dict keys    │  - error (if any)                 │
│                       │  - test output                    │
│                       │                                   │
├───────────────────────┴───────────────────────────────────┤
│                                                           │
│  CLASSIFIER OUTPUT (if exists)                            │
│  - 4 dimensions: mechanism / commitments / satisfied /    │
│    alignment                                              │
│  - failure_type, confidence                               │
│  - counterfactual, evidence, judgment                     │
│                                                           │
├───────────────────────────────────────────────────────────┤
│                                                           │
│  CRITIQUE (if retry attempt)                              │
│  - critique sentence that was fed to this attempt         │
│  - previous attempt's reasoning (for comparison)          │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

Data loading: reads `calls_flat/*.txt` files on-demand when user selects an attempt. Never preloaded.

For retry chains: show all attempts in sequence with attempt navigation (prev/next). Highlight what changed between attempts.

### Tab 5: Cross-Experiment Aggregate

**For comparing interventions across the full dataset.**

Content:
- Intervention comparison table (the key paper table):
  | Intervention | Mean Δpass | % Helped | % Hurt | Help/Harm ratio |
- Family × Intervention heatmap: mean pass_delta per (family, intervention)
- Failure type classification summary: EXECUTION_LIMITED / BELIEF_LIMITED / REPRESENTATION_LIMITED / etc.
- LEG subtype distribution: convertible / belief_correctable / irreducible

Requires loading multiple experiment directories simultaneously.

---

## 5. Implementation Plan

### Step 1: Data pipeline (`dashboard/leg_scanner.py`)

New file. ~250 lines.

```
load_wal(log_dir) → list[dict]
build_attempt_table(events, cases_path) → DataFrame
resolve_artifact_paths(row) → dict of paths
read_artifact(path) → str
```

- Reads ONLY from `merged_events.jsonl` and `workers/` directories
- Strict validation: raises on missing required fields
- No silent drops
- Pure functions, no global state

### Step 2: Metric module (`dashboard/leg_metrics.py`)

New file. ~150 lines.

All pure functions operating on the attempt-level DataFrame:
- `compute_ablation_summary(df)`
- `compute_family_breakdown(df)`
- `compute_retry_metrics(df)`
- `compute_case_deltas(df, cond_a, cond_b)`
- `classify_trajectory(attempts)`

No side effects. No I/O. DataFrame in, DataFrame/dict out.

### Step 3: Streamlit app (`dashboard/app.py`)

New file. ~400 lines.

5 tabs per Section 4. Uses `st.dataframe`, `st.columns`, `st.selectbox`, `st.code` for display. No custom JS needed — Streamlit handles interactivity.

Key interactions:
- Tab 1 cell click → sets filter, switches to Tab 2
- Tab 2 family click → sets filter, switches to Tab 4
- Tab 3 row click → sets filter, switches to Tab 4
- Tab 4 cascading selectors → loads artifact files on selection

### Step 4: Validation

Pick 3 random cases from existing logs. For each:
1. Read `merged_events.jsonl` manually → confirm DataFrame row matches
2. Read `workers/{work_id}/attempt_001/calls_flat/000001_generation.txt` → confirm prompt/response match what Tab 4 shows
3. Confirm pass/fail matches execution result
4. Confirm LEG flag matches reasoning_correct + exec_pass derivation

Document results.

---

## 6. Files Created / Modified

| File | Action | Lines (est) |
|---|---|---|
| `dashboard/leg_scanner.py` | NEW | 250 |
| `dashboard/leg_metrics.py` | NEW | 150 |
| `dashboard/app.py` | NEW | 400 |
| `dashboard/server.py` | KEEP (legacy, not used by new dashboard) | 0 changes |
| `dashboard/run_scanner.py` | KEEP (legacy, not used by new dashboard) | 0 changes |
| `dashboard/run_dashboard.sh` | MODIFY — add `streamlit run dashboard/app.py` option | 5 |

The new Streamlit app runs alongside the existing FastAPI dashboard — no destructive changes. The old dashboard continues to work for the debate project.

**Launch command:**
```bash
streamlit run dashboard/app.py
```

---

## 7. Dependency

One new dependency: `streamlit`. Install via:
```bash
uv pip install streamlit
```

No other new dependencies. pandas already installed.

---

## 8. Mapping: Logs → Dashboard

| Dashboard element | Data source | Computation |
|---|---|---|
| Ablation summary table | `merged_events.jsonl` → case.end events | `compute_ablation_summary(df)` grouped by (model, condition) |
| Family breakdown | Same events + cases_v2.json join | `compute_family_breakdown(df)` grouped by (model, condition, family) |
| Retry trajectory | Same events, filtered to attempt_idx > 1 | `classify_trajectory()` per attempt chain |
| Recovery rate | Same events, retry conditions only | % of (case, trial) chains where attempt_1 fails and final passes |
| Prompt text | `workers/{work_id}/attempt_{n}/calls_flat/000001_generation.txt` | Read on-demand, split at `--- RESPONSE ---` |
| Response text | Same file, after `--- RESPONSE ---` | Read on-demand |
| Classifier output | `workers/{work_id}/attempt_{n}/calls_flat/000002_classification.txt` | Read on-demand |
| Critique (retry) | `workers/{work_id}/attempt_{n}/calls_flat/000003_generation.txt` prompt section | Read on-demand, extract critique from retry prompt |
| Execution result | `payload.pass`, `payload.score`, `execution.error` from event | Already in DataFrame |
| LEG flag | `reasoning.reasoning_correct` AND NOT `payload.pass` | Derived column in DataFrame |

---

## 9. What v1 Got Wrong

| v1 assumption | Why wrong | v2 fix |
|---|---|---|
| Case-level aggregation is primary | Destroys ablation signal — the research question is about interventions, not cases | Aggregate by (model, condition) first |
| Summary tables are the main feature | You find bugs by reading prompts, not tables | File explorer is Tab 4, highest priority |
| Retry is a minor feature | Retry+critique is the dominant finding (9.8:1 help/harm ratio) | Dedicated retry analysis tab with trajectory classification |
| Metrics can be computed flexibly | Metrics must match the paper exactly: LEG = reasoning_correct AND NOT pass | Pure functions with strict definitions |
| Data from load_logs.py | load_logs.py aggregates to case-level, loses attempt granularity | New load_wal() preserves every event as a row |
| Vanilla JS port | Weeks of work for interactivity that Streamlit gives for free | Streamlit — ship in days, not weeks |
