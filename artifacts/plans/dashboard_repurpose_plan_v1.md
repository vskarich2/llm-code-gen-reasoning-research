# Dashboard Repurpose Plan — v1

**Date:** 2026-04-03
**Status:** PLAN ONLY
**Scope:** Repurpose existing debate dashboard for LEG/code-generation experiment metrics
**Source dashboard:** `dashboard/` (FastAPI + vanilla JS, debate/portfolio domain)

---

## 1. Current Dashboard Architecture

The existing dashboard is a FastAPI backend (`server.py`) serving vanilla JS (`static/js/`) with no build system. It has a clean layered architecture:

```
app.js → router.js → views/* → components/* → utils/*
                              → api/*
```

**Backend:** `server.py` (FastAPI) + `run_scanner.py` (94k lines, data loading/computation)
**Frontend:** vanilla JS ES modules, 3 CSS files, no framework
**Data source:** `logging/runs/` directory tree (debate experiment logs)

### Current views and what they show

| View | Purpose | Debate-specific? |
|---|---|---|
| `runsView.js` | List experiments + runs with search/filter | **Reusable** — structure is generic |
| `ablationView.js` | Aggregate stats across experiments | **Reusable** — card layout is generic |
| `runDetail/index.js` | Single run deep-dive with collapsible sections | **Reusable** — section pattern is generic |
| `runDetail/overviewSection.js` | Run metadata summary | Partially debate-specific |
| `runDetail/roundsSection.js` | Per-round debate text | **Debate-specific** — replace |
| `runDetail/judgePortfolioSection.js` | Judge allocation table | **Debate-specific** — replace |
| `runDetail/pidSection.js` | PID controller trajectory | **Debate-specific** — replace |
| `runDetail/pidStatsSection.js` | PID stats | **Debate-specific** — replace |
| `runDetail/critSection.js` | CRIT reasoning scores | Partially reusable (reasoning eval concept) |
| `runDetail/divergenceSection.js` | Agent opinion divergence | **Debate-specific** — replace |
| `runDetail/portfolioSection.js` | Portfolio allocation over time | **Debate-specific** — replace |
| `runDetail/fileExplorerSection.js` | Browse raw run files | **Fully reusable** |

### Current API endpoints

| Endpoint | Purpose | Keep? |
|---|---|---|
| `GET /runs/` | List experiments | **Keep** — adapt data source |
| `GET /runs/{experiment}` | List runs in experiment | **Keep** — adapt |
| `GET /runs/{experiment}/{run_id}` | Run detail | **Keep** — adapt |
| `GET /runs/{experiment}/{run_id}/tree` | File tree | **Keep as-is** |
| `GET /runs/{experiment}/{run_id}/file` | Read file | **Keep as-is** |
| `GET /api/ablation` | Aggregate summary | **Replace** — new metrics |
| `GET /runs/.../performance` | Portfolio performance | **Replace** |
| `GET /runs/.../pid` | PID trajectory | **Remove** |
| `GET /runs/.../crit` | CRIT scores | **Adapt** — reasoning eval is analogous |
| `GET /runs/.../divergence` | Opinion divergence | **Remove** |
| `GET /runs/.../collapse` | Agent collapse | **Remove** |
| `GET /runs/.../portfolio` | Portfolio trajectory | **Remove** |
| `GET /runs/.../round/{n}` | Round detail | **Remove** |
| Various `/api/ablation/*` | Paired tests, debate impact | **Replace** |

---

## 2. Target Dashboard — What We Need

### 2.1 Data source

Replace `logging/runs/` with `logs/` (our experiment log directories). Each log directory contains:
- `merged_events.jsonl` — all case evaluation events
- `config.snapshot.yaml` — experiment config
- `manifest.json` — run metadata
- `workers/` — per-case worker dirs with `calls_flat/` (raw LLM prompts/responses)

### 2.2 Required views

#### View 1: Experiments List (adapt existing `runsView`)
- List all log directories grouped by experiment name
- Show per-experiment: # models, # conditions, # cases, # trials, pass rate, LEG rate
- Filter/search by experiment name

#### View 2: Experiment Detail (adapt existing `runDetail`)
Collapsible sections:

**Section A: Overview**
- Models, conditions, cases, total trials
- Config snapshot

**Section B: LEG Rates Table**
- Grouped by (model, condition)
- Columns: pass_rate, reasoning_rate, leg_rate, lucky_fix_rate, count

**Section C: Case × Model Delta Table**
- For each condition pair: pass_delta, leg_delta per (case, model)
- Sortable, filterable
- Color-coded: green for help, red for harm

**Section D: Family Effects**
- Grouped by family
- Mean pass_delta, mean leg_delta, # helps, # harms per intervention

**Section E: Heterogeneity**
- Per-case: has_help, has_hurt, heterogeneous flag
- Family-level heterogeneity rate

**Section F: LEG Conversion**
- LEG-suffering pairs with conversion ratios
- Subtype classification (convertible / belief-correctable / irreducible)

**Section G: Model Behavior**
- Per-model: pass delta, LEG delta, % helped, % hurt, LEG→pass conversion

**Section H: File Explorer** (keep existing)
- Browse raw worker dirs, calls_flat, events.jsonl

#### View 3: Aggregate / Cross-Experiment (adapt existing `ablationView`)
- Intervention comparison table (the key summary table from our analysis)
- Family × Intervention matrix
- Failure type classification summary
- Cross-model consistency

### 2.3 Required API endpoints

| Endpoint | Purpose | Data source |
|---|---|---|
| `GET /api/experiments` | List log directories with summary stats | `logs/*/merged_events.jsonl` |
| `GET /api/experiments/{name}` | Full experiment data | `logs/{name}/merged_events.jsonl` |
| `GET /api/experiments/{name}/leg-rates` | LEG decomposition table | Computed from events |
| `GET /api/experiments/{name}/case-deltas` | Case × model delta table | Paired analysis |
| `GET /api/experiments/{name}/family-effects` | Family-level aggregation | Grouped paired deltas |
| `GET /api/experiments/{name}/heterogeneity` | Heterogeneity analysis | compute_case_heterogeneity |
| `GET /api/experiments/{name}/leg-conversion` | LEG conversion table | LEG-suffering analysis |
| `GET /api/experiments/{name}/model-behavior` | Per-model stats | Grouped by model |
| `GET /api/experiments/{name}/tree` | File tree | Existing, adapt path |
| `GET /api/experiments/{name}/file` | Read file | Existing, adapt path |
| `GET /api/aggregate` | Cross-experiment summary | All logs combined |
| `GET /api/aggregate/family-intervention` | Family × intervention matrix | All logs, paired |
| `GET /api/aggregate/failure-types` | Failure type classification | Mechanism diagnosis |

---

## 3. Implementation Plan

### Phase 1: Backend — Replace `run_scanner.py` with LEG data loader

**Estimated scope:** New file `dashboard/leg_scanner.py` (~300 lines)

This module replaces `run_scanner.py` and provides all data loading + computation for the new endpoints. It reuses `analysis/load_logs.py` as its core data engine.

Functions needed:
- `list_experiments(logs_base)` — scan log directories, return summary stats per experiment
- `get_experiment_detail(logs_base, name)` — load merged_events, return full dataset
- `compute_leg_rates(df)` — reuse from `analysis/load_logs.py`
- `compute_case_deltas(df, cond_a, cond_b)` — reuse from `analysis/load_logs.py`
- `compute_family_effects(df)` — reuse from `analysis/load_logs.py`
- `compute_heterogeneity(df, cond_a, cond_b)` — reuse from `analysis/load_logs.py`
- `compute_leg_conversion(df, cond_a, cond_b)` — from `run_leg_subtypes.py` logic
- `compute_model_behavior(df, cond_a, cond_b)` — per-model aggregation
- `get_file_tree(logs_base, name)` — adapt existing
- `read_file(logs_base, name, path)` — adapt existing
- `compute_aggregate(logs_base)` — cross-experiment summary
- `compute_family_intervention_matrix(logs_base)` — from `run_family_intervention_comparison.py`

**Key design decision:** The scanner pre-computes and caches DataFrames on first access. Experiment data is loaded once, then all endpoint computations are fast DataFrame operations.

### Phase 2: Backend — Replace `server.py` endpoints

**Estimated scope:** Modify `server.py` (~200 lines changed)

- Remove all debate-specific endpoints (portfolio, pid, crit, divergence, collapse, rounds)
- Remove debate-specific imports (`run_scanner` → `leg_scanner`)
- Add new endpoints per Section 2.3
- Update `RUNS_BASE` to point to `logs/` instead of `logging/runs/`
- Keep file explorer endpoints (adapt paths)
- Keep static file serving

### Phase 3: Frontend — Replace views

**Estimated scope:** ~600 lines of new/modified JS

#### 3a: Update `api/runs.js` → `api/experiments.js`
- Replace all fetch functions with new endpoint URLs
- Add new fetch functions for LEG-specific endpoints

#### 3b: Update `runsView.js` → experiment list
- Replace run table columns with: experiment name, models, conditions, cases, pass rate, LEG rate
- Keep search/filter pattern
- Keep experiment selector pattern

#### 3c: Replace `runDetail/` sections
- **Keep:** `overviewSection.js` (adapt fields), `fileExplorerSection.js` (as-is)
- **Replace:** All debate sections with new sections:
  - `legRatesSection.js` — LEG decomposition table
  - `caseDeltaSection.js` — case × model delta table with color coding
  - `familyEffectsSection.js` — family-level effects table
  - `heterogeneitySection.js` — heterogeneity table
  - `legConversionSection.js` — LEG conversion analysis
  - `modelBehaviorSection.js` — per-model stats

#### 3d: Replace `ablationView.js` → aggregate view
- Replace debate ablation cards with intervention comparison matrix
- Add family × intervention heatmap
- Add failure type summary

#### 3e: Update `components/`
- **Keep:** `card.js` (generic), `table.js` (generic), `charts.js` (adapt for LEG charts)
- **Remove:** `critDiagnostics.js`, `financialSignificance.js`, `financialTests.js`, `ablation.js`
- **Add:** `legTable.js` (color-coded delta tables), `heatmap.js` (family × intervention)

### Phase 4: Frontend — Update HTML and CSS

- `index.html`: Change title to "LEG Benchmark Dashboard", update nav links
- `base.css` / `components.css`: Add color-coding for help/harm deltas (green/red), heatmap styles
- `layout.css`: Minimal changes — existing layout works

### Phase 5: Update CI and tests

- Update `tests/` for new endpoints and views
- Update `run_dashboard.sh` if path references changed
- Update architecture rules if layer structure changed

---

## 4. What We Keep vs Replace vs Remove

| Component | Action | Reason |
|---|---|---|
| `server.py` | **Modify** | New endpoints, same framework |
| `run_scanner.py` | **Replace** with `leg_scanner.py` | Completely different data domain |
| `backfill_dashboard_metrics.py` | **Remove** | Debate-specific |
| `static/index.html` | **Modify** | Title, nav labels |
| `static/js/app.js` | **Keep** | Generic routing/init |
| `static/js/router.js` | **Modify** | Update route names |
| `static/js/state.js` | **Modify** | Replace debate state with LEG state |
| `static/js/api/client.js` | **Keep** | Generic fetch wrapper |
| `static/js/api/runs.js` | **Replace** | New endpoints |
| `static/js/views/runsView.js` | **Modify** | New columns, same pattern |
| `static/js/views/ablationView.js` | **Replace** | Different aggregate metrics |
| `static/js/views/runDetail/index.js` | **Modify** | New sections |
| `static/js/views/runDetail/overviewSection.js` | **Modify** | New fields |
| `static/js/views/runDetail/fileExplorerSection.js` | **Keep** | Already generic |
| All other runDetail sections | **Replace** | Debate-specific |
| `static/js/components/card.js` | **Keep** | Generic |
| `static/js/components/table.js` | **Keep** | Generic |
| `static/js/components/charts.js` | **Modify** | New chart types |
| Debate-specific components | **Remove** | Not applicable |
| `static/js/utils/*` | **Keep** | Generic DOM/format utilities |
| `static/css/*` | **Modify** | Add LEG-specific styles |
| `rules/` | **Modify** | Update architecture rules for new modules |
| `tests/` | **Replace** | New test cases |
| `ci/` | **Keep** | CI pipeline still applies |

---

## 5. Data Flow

```
logs/                           dashboard/leg_scanner.py          server.py           static/js/
├── experiment_a/               ┌──────────────────────┐         ┌──────────┐        ┌────────────┐
│   ├── merged_events.jsonl ──→ │ load via             │──→      │ FastAPI   │──→     │ fetch()    │
│   ├── config.snapshot.yaml    │ analysis/load_logs.py│         │ endpoints │        │ → render() │
│   └── workers/                │                      │         └──────────┘        └────────────┘
├── experiment_b/               │ compute:             │
│   └── ...                     │   leg_rates          │
└── experiment_c/               │   case_deltas        │
    └── ...                     │   family_effects     │
                                │   heterogeneity      │
                                │   leg_conversion     │
                                └──────────────────────┘
```

---

## 6. Constraints

1. **No framework introduction** — vanilla JS only, matching existing architecture
2. **Layer rules preserved** — `utils → components → views`, no upward imports
3. **Components stay pure** — data in, HTML string out, no DOM access
4. **viewToken guard** — all async DOM writes check stale token
5. **No new dependencies** — FastAPI, uvicorn already installed
6. **`analysis/load_logs.py` is the single data engine** — `leg_scanner.py` wraps it, does not reimplement
7. **Existing CI pipeline must pass** — eslint, dependency-cruiser, semgrep, architecture checks

---

## 7. Execution Order

1. **Phase 1** first — backend is independently testable via curl
2. **Phase 3a** next — API layer, then views can be built
3. **Phase 3b-3d** — one view at a time, test each
4. **Phase 2** — final endpoint cleanup (remove debate endpoints after views are replaced)
5. **Phase 4** — CSS polish
6. **Phase 5** — CI and tests last

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| `run_scanner.py` is 94k lines — hard to know what's reusable | Don't reuse it. Write `leg_scanner.py` from scratch, wrapping `load_logs.py` |
| Data loading is slow for large experiment sets | Cache DataFrames in memory on first load; add loading indicator |
| Existing tests reference debate-specific DOM elements | Replace tests entirely — they test debate views that no longer exist |
| `analysis/load_logs.py` default `cases_path` may not resolve from dashboard context | Pass explicit path via `core.config.paths.PROJECT_ROOT / "data/cases_v2.json"` |
| CI rules may reject new files that don't match old architecture expectations | Update architecture checker baseline after structural changes |
