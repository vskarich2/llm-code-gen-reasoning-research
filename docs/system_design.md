# T3 Code Generation Benchmark — System Design Document

## Overview

T3 is a benchmark framework that measures how LLMs reason about and fix subtle code bugs. It combines **execution-based testing** (behavioral ground truth) with **LLM-based classification** (reasoning assessment) to evaluate both code correctness and reasoning quality.

The core research question: When a model produces incorrect code, is the bottleneck *understanding* (can't identify the bug) or *execution* (understands the bug but can't fix it)?

---

## Architecture Layers

```
┌─────────────────────────────────────────────────┐
│  Layer 1: Entry + Config                         │
│  runner.py, experiment_config.py, config.py      │
├─────────────────────────────────────────────────┤
│  Layer 2: Case Management                        │
│  cases_v2.json, validate_cases_v2.py,            │
│  condition_registry.py                           │
├─────────────────────────────────────────────────┤
│  Layer 3: Prompt Building + Nudge System         │
│  prompts.py, execution.py:build_prompt(),        │
│  nudges/, scm_prompts.py, templates/             │
├─────────────────────────────────────────────────┤
│  Layer 4: LLM Integration                        │
│  llm.py, call_logger.py                          │
├─────────────────────────────────────────────────┤
│  Layer 5: Response Parsing + Reconstruction      │
│  parse.py, reconstructor.py                      │
├─────────────────────────────────────────────────┤
│  Layer 6: Execution + Evaluation                 │
│  exec_eval.py, evaluator.py, subprocess_eval.py  │
├─────────────────────────────────────────────────┤
│  Layer 7: Advanced Execution Modes               │
│  leg_reduction.py, retry_harness.py,             │
│  contract.py, diff_gate.py                       │
├─────────────────────────────────────────────────┤
│  Layer 8: Classification + Failure Analysis      │
│  failure_classifier.py, eval_cases.py            │
├─────────────────────────────────────────────────┤
│  Layer 9: Metrics + Observability                │
│  live_metrics.py, redis_metrics.py               │
├─────────────────────────────────────────────────┤
│  Layer 10: Audit + Validation Infrastructure     │
│  preflight_check.py, tests/, tests_v2/,          │
│  reasoning_evaluator_audit/                      │
└─────────────────────────────────────────────────┘
```

---

## Execution Flow

### Single case evaluation (the core path)

```
runner.py:main()
  → load_cases("cases_v2.json")           # Load 58 bug cases + code files
  → preflight_verify_tests(cases)          # Verify test functions exist
  → validate_run(cases, conditions)        # Check case-condition compatibility
  → run_all(cases, model, conditions)
    → for each (case, condition):
        → build_prompt(case, condition)    # Build prompt with nudge/template
        → call_model(model, prompt)        # LLM API call → raw response
        → parse_model_response(raw)        # Extract reasoning + code
        → reconstruct_strict(...)          # Map file-dict → code files (if needed)
        → evaluate_output(case, parsed)
            → exec_evaluate(case, code)    # BEHAVIORAL: run code, check tests
            → llm_classify(reasoning)      # REASONING: LLM judges quality
            → compute_alignment()          # Reasoning-code consistency
        → emit_event(...)                  # Record to events.jsonl
```

### Ablation mode (multi-model, multi-trial)

The shell script `scripts/run_ablation_leg_8t.sh` orchestrates:
1. Cost protection gate (5 cases, verifies pipeline works)
2. Spawns 8 parallel workers per model
3. Each worker runs `runner.py --run-dir <dir> --trial <n>`
4. Dashboard process aggregates events.jsonl files
5. Post-run sanity checks (ran_rate, pass_rate, distribution)

---

## Key Components

### Cases (`cases_v2.json`)

58 bug cases organized by:
- **family**: Bug pattern group (e.g., `alias_config`, `mutable_default`)
- **difficulty**: A (easy, single-file), B (medium), C (hard, multi-file)
- **failure_mode**: Bug category (ALIASING, RACE_CONDITION, MUTABLE_DEFAULT, etc.)

Each case contains:
- `code_files`: Buggy source code
- `task`: Natural language description of the refactoring request
- `ground_truth_bug`: Root cause, location, invariant, fix pattern
- `reference_fix`: The minimal correct fix
- `test_contract`: Setup, execution, assertions for behavioral testing

### Conditions (25 intervention types)

Conditions are reasoning interventions applied to the prompt. They range from simple nudges to complex multi-step protocols:

| Category | Conditions | Description |
|----------|-----------|-------------|
| Base | baseline | No intervention — control |
| Nudges | diagnostic, guardrail, guardrail_strict | Guide or constrain reasoning |
| Reasoning formats | structured_reasoning, free_form, branching | Change how model structures its answer |
| SCM | scm_descriptive, scm_constrained, etc. | Provide causal graph of dependencies |
| Multi-step | repair_loop, retry_*, contract_gated | Multiple LLM calls with feedback |
| LEG-specific | leg_reduction | Structured self-correction with revision history |

### Evaluation (two sources of truth)

**Behavioral evaluation** (`exec_eval.py`):
- Compiles model code via `exec()` into an in-memory module
- For multi-file cases, assembles original files + model changes via `_assemble_program()`
- Runs test function against the loaded module
- Returns `pass`, `score`, `ran`, execution details
- This is ground truth — code either passes the test or it doesn't

**Reasoning evaluation** (`evaluator.py:llm_classify()`):
- Sends model's reasoning + code + task to a classifier LLM
- Classifier judges: "Did this developer correctly identify the root cause?"
- Returns `reasoning_correct` (YES/NO), `failure_type`
- **STATUS: DISQUALIFIED** — Phase 0 audit showed the classifier is unreliable (brevity bias, non-determinism at temp=0, 33% accuracy on known-good reasoning). See `reasoning_evaluator_audit/phase0_report.md`.

### Derived metrics

| Metric | Formula | Status |
|--------|---------|--------|
| **pass_rate** | code passes execution tests | Trustworthy |
| **code_correct** | same as pass (from execution) | Trustworthy |
| **reasoning_correct** | LLM classifier judgment | **UNRELIABLE** |
| **LEG rate** | reasoning_correct AND NOT code_correct | **UNRELIABLE** (depends on classifier) |
| **Lucky fix rate** | NOT reasoning_correct AND code_correct | **UNRELIABLE** (depends on classifier) |
| **Exec\|Reason** | P(code_correct \| reasoning_correct) | **UNRELIABLE** |

### Prompt building

Prompts are built through a layered system:
1. `build_base_prompt()`: Task description + code files
2. Condition-specific modification (nudge, template, or multi-step protocol)
3. Output format instruction (JSON with `reasoning` + `files` dict)
4. For multi-step conditions: feedback from prior attempts

Templates live in `templates/` as Jinja2 files. Nudges are registered operators in `nudges/core.py` mapped to cases via `nudges/mapping.py`.

### Response parsing

`parse.py` uses a 3-tier strategy:
1. Direct `json.loads()` on the raw response
2. Extract from markdown code blocks, then parse
3. Find `{...}` substring, try to parse

The parsed response produces a `files` dict (file path → code content). The `reconstructor.py` maps this back to the case's file structure, resolving `UNCHANGED` markers to original content.

### Assembly (`_assemble_program`)

For multi-file cases:
1. Concatenate all original files (with cross-file imports stripped)
2. Append model's changed files
3. Later definitions override earlier ones (Python top-to-bottom execution)
4. Load via `exec()` into a single module

Only changed files go into `parsed["code"]` — originals are supplied by assembly. This avoids double-definition bugs.

---

## Data Flow

### Per-run directory structure

```
logs/ablation_runs/run_{model}_{trial}_{uuid}/
  metadata.json          # Model, trial, start/end time, run_id
  events.jsonl           # One event per (case, condition) — live metrics
  run.jsonl              # Full evaluation details per case
  run_prompts.jsonl      # Exact prompts sent to model
  run_responses.jsonl    # Raw model responses
  runner_output.txt      # Stdout/stderr from runner process
```

### Event schema (events.jsonl)

Each line is a JSON object with:
- `case_id`, `model`, `condition`, `trial`, `run_id`
- `pass`, `score`, `reasoning_correct`, `code_correct`
- `failure_type`, `category`
- Parse/reconstruction metadata (code_source, parse_tier, reconstruction_status)

---

## Safety Infrastructure

### 11-layer guarantee

The system enforces: *"It is impossible to run a full ablation with a broken pipeline, broken evaluator, invalid test oracle, or incorrect experiment configuration without triggering a failure before significant cost is incurred."*

| Layer | What it catches |
|-------|----------------|
| L-2: Experiment config | Wrong model, conditions, case file |
| L-1: Oracle validation | Test functions incompatible or insensitive |
| L0: Evaluator correctness | exec_evaluate broken |
| L1: Reference fix validation | Reference fixes incorrect |
| L2: Integration tests | Wiring bugs, reconstruction failures |
| L3: Regression tests | Reintroduction of known bugs |
| L4: Invariant assertions | reconstruction SUCCESS → code not empty |
| L5: Cost protection gate | Pipeline broken (5 cases before full run) |
| L6: Execution sanity | ran_rate < 50% → abort |
| L7: Distribution guard | 0% pass, all-same-category → abort |
| L8: Dashboard guards | Degenerate metrics mid-run |

### Key invariants

- `ran=False AND total_tests>0` is structurally impossible (assertion in `_exec_info`)
- Reconstruction SUCCESS → `parsed["code"]` is non-empty
- Empty code → `ran=False, total_tests=0`
- Tests cannot run without model code being loaded into a module first

---

## Configuration

### Primary config: `configs/default.yaml`

Controls: model parameters, condition settings, retry limits, evaluation mode, logging.

### Experiment config: `experiment.yaml`

High-level experiment definition: name, models, conditions, execution settings.

### Constants: `constants.py`

All condition names, valid condition sets, category labels. Single source of truth.

---

## Current Status

### Working
- Full execution pipeline (parse → reconstruct → assemble → execute → evaluate)
- 58 bug cases across 22 failure modes, 3 difficulty levels
- 25 reasoning intervention conditions
- Cost protection gate + 303 safety tests
- Audit logging with 21 fields per classifier call

### Known Issues
- **Reasoning classifier disqualified** (brevity bias + non-determinism)
- `mutable_default_b` has incorrect `reference_fix.function` metadata
- LEG/lucky/reasoning metrics are unreliable; only code_correct is trustworthy
- `experiment.yaml` model list is stale (doesn't include gpt-5.4-mini)

### Partial Data
- gpt-5.4-mini: 790/928 events (~85% complete)
- gpt-5-mini: 113/928 events (~12% complete)
- gpt-4o-mini: no data
