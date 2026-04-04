# T3 Benchmark — Full Codebase Architecture Audit

## 0. Config Wiring Audit (ADDENDUM)

**Critical finding: 24 of ~48 config fields are DEAD. 50% of config surface is theater.**

### Dead Fields (parsed from YAML, never read)

| Field | Default | Impact |
|---|---|---|
| `experiment.seed` | 42 | Non-determinism despite config seed. Never set on random/numpy. |
| `evaluation.execution_mode` | "subprocess" | DEAD. Confused with `execution.mode` which IS wired. |
| `evaluation.leg_enabled` | True | Cannot toggle LEG evaluation via config. |
| `evaluation.failure_classification_enabled` | True | Cannot toggle failure classification. |
| `evaluation.alignment_enabled` | True | Cannot toggle alignment computation. |
| `evaluation.subprocess_timeout` | 30 | DEAD duplicate of `execution.subprocess_timeout` which IS wired. |
| `evaluator.max_reasoning_chars` | 1000 | Never truncates reasoning. `max_task_chars`/`max_code_chars` ARE wired. |
| `execution.import_summary` | False | Never read. |
| `execution.file_ordering` | "dependency" | Never read. |
| `cases.mode` | "all" | Never read. Cannot switch modes. |
| `cases.subset` | [] | Never read. Cannot filter subset. |
| `cases.difficulty_filter` | None | Never read. |
| `cases.family_filter` | None | Never read. |
| `cases.exclude` | [] | Never read. Cannot exclude cases. |
| `conditions[].contract_enabled` | False | Never read. Gate uses condition name. |
| `conditions[].contract_injection_point` | None | Never read. |
| `conditions[].critique_model` | None | Never read. Uses evaluator model. |
| `logging.level` | "INFO" | Never set on Python loggers. |
| `logging.store.raw_prompts` | True | Never read. Always stored. |
| `logging.store.raw_outputs` | True | Never read. Always stored. |
| `logging.redis.*` (3 fields) | various | Never read. redis_metrics.py is dead code. |
| `retry_defaults.enabled` | False | Only used in config validation, not runtime. |

### Silent Defaults (try/except masks config errors)

| Location | Field | Fallback | Risk |
|---|---|---|---|
| `llm.py:22` `_get_output_format()` | output_format | "v1" | Schema changes silently |
| `llm.py:32` `_get_model_spec()` | temperature/top_p | 0.0/1.0 | API params revert without warning |
| `llm.py:202` `_get_anthropic_max_tokens()` | max_tokens | 4096 | Silently capped |
| `logging_core.py:652` `_get_model_temperature()` | temperature | None | Logs show None |
| `logging_core.py:669` `_get_model_max_tokens()` | max_tokens | None | Logs show None |

### Duplicate/Confused Fields

- `subprocess_timeout` in BOTH `EvaluationConfig` (DEAD) and `ExecutionConfig` (WIRED)
- `evaluation.execution_mode` (DEAD) vs `execution.mode` (WIRED) — naming collision

---

## 1. Executive Summary

52 Python files at top level. 8,561 lines of canonical runtime code. 3,216 lines of dead/orphan/legacy code (37% of canonical). The system has **two intentionally parallel execution paths** (v1 and v2) that share infrastructure correctly. The v1 path is still reachable and actively used for 18+ conditions. The v2 path handles 3 primary ablation conditions plus retry variants. This is not a migration failure — both paths are live by design.

**The system is cleaner than expected.** The logging refactor successfully eliminated global state. The assembly engine is a genuine single point of enforcement. Config loading is unified. There is no split-brain on the canonical execution path.

**However, there are real problems:**
- 3,216 lines of dead code still on disk
- 2 competing template systems (templates.py + templates/ vs prompts/ + assembly_engine)
- 2 dead logging systems (call_logger.py, live_metrics.py) still on disk
- retry_harness.py bypasses assembly_engine for prompt construction after iteration 0
- Several orphan modules with no importers
- graph_runner/ is a disconnected parallel universe (24 files, zero integration)
- v2_dashboard.py and v2_metrics.py duplicate aggregate.py's job

---

## 2. File-by-File Classification Table

### Canonical Runtime (19 files, 8,561 lines)

| File | Lines | Purpose | Status | Evidence |
|------|-------|---------|--------|----------|
| `runner.py` | 711 | Entry point, orchestrator | CANONICAL | All CLI entry goes here |
| `parallel_runner.py` | 339 | Multi-worker orchestration | CANONICAL | Called when num_workers > 1 |
| `execution.py` | 932 | V1 dispatch + prompt build | CANONICAL | Routes all v1 conditions |
| `execution_v2.py` | 206 | V2 dispatch | CANONICAL | Routes baseline_v2, leg_*_v2 |
| `evaluator.py` | 400 | V1 evaluation + classifier | CANONICAL | evaluate_output() used by all v1 |
| `evaluator_v2.py` | 296 | V2 classifier + assembly | CANONICAL | Used by execution_v2, retry_v2 |
| `exec_eval.py` | 900 | Code execution engine | CANONICAL | SOLE code execution authority |
| `llm.py` | 204 | LLM API wrapper | CANONICAL | All LLM calls route here |
| `parse.py` | 350 | V1 response parser (3-tier) | CANONICAL | Used by all v1 evaluation |
| `parser_v2.py` | 400 | V2 response parser (3-tier) | CANONICAL | Used by execution_v2, retry_v2 |
| `reconstructor.py` | 200 | File-dict reconstruction | CANONICAL | Used by v2 pipeline |
| `reasoning.py` | 350 | V1 reasoning schema | CANONICAL | Schema v3, category computation |
| `reasoning_v2.py` | 250 | V2 reasoning normalization | CANONICAL | NormalizedReasoningArtifactV2 |
| `assembly_engine.py` | 123 | Prompt construction (Jinja2) | CANONICAL | Enforced single entry point |
| `prompts.py` | 27 | Code file formatting | CANONICAL | _format_code_files utility |
| `prompt_registry.py` | 194 | Template + nudge registry | CANONICAL | Loads .j2 + registry.yaml |
| `logging_core.py` | 624 | Centralized logging | CANONICAL | All events flow through here |
| `experiment_config.py` | 549 | Config loader + validator | CANONICAL | Single source of truth |
| `constants.py` | 137 | Condition names + categories | CANONICAL | Structural invariants enforced |

### V1-Specific (still reachable, 5 files, 2,737 lines)

| File | Lines | Purpose | Status | Evidence |
|------|-------|---------|--------|----------|
| `retry_harness.py` | 1757 | V1 retry probe | CANONICAL | Routes retry_no_contract etc |
| `leg_reduction.py` | 100 | LEG schema parsing | CANONICAL | Routes leg_reduction condition |
| `leg_evaluator.py` | 150 | LEG analysis (side-channel) | LIVE_SUPPORT | Analysis only, never controls execution |
| `contract.py` | 200 | Contract schema + parsing | CANONICAL | Routes contract_gated condition |
| `diff_gate.py` | 530 | Contract validation | CANONICAL | 6 gate checks for CGE |

### V2-Specific (5 files, 1,185 lines)

| File | Lines | Purpose | Status | Evidence |
|------|-------|---------|--------|----------|
| `retry_v2.py` | 550 | V2 retry harness | CANONICAL | Routes retry_*_v2 conditions |
| `contracts_v2.py` | 100 | V2 schema contracts | CANONICAL | Field validation for v2 |
| `metrics_v2.py` | 200 | V2 signal derivation | CANONICAL | derive_v2_signals() |
| `mapping_v2.py` | 135 | Case→family mapping | CANONICAL | Used by reasoning_v2 |
| `exec_canonical.py` | 200 | Subprocess execution | CANONICAL | Optional backend (config flag) |

### Live Support (10 files, 2,891 lines)

| File | Lines | Purpose | Status | Evidence |
|------|-------|---------|--------|----------|
| `condition_registry.py` | 400 | Case/condition compatibility | LIVE_SUPPORT | Preflight validation |
| `scm_data.py` | 300 | SCM evidence data | LIVE_SUPPORT | Required by SCM conditions |
| `failure_classifier.py` | 200 | Heuristic failure typing | LIVE_SUPPORT | Used by retry + LEG |
| `code_assembly.py` | 500 | Code assembly engine | CANONICAL | Used by exec_eval |
| `module_exec.py` | 300 | Dual execution (side-channel) | LIVE_SUPPORT | Monitoring, never controls |
| `disagreement_classifier.py` | 200 | Concat vs module analysis | LIVE_SUPPORT | Used by evaluator.py |
| `merge_run.py` | 200 | Parallel run merger | LIVE_SUPPORT | Used by parallel_runner |
| `_stdlib.py` | 50 | Stdlib whitelist | LIVE_SUPPORT | Import validation |
| `nudges/*.py` (4 files) | 441 | Nudge operator system | CANONICAL | Case→operator routing |
| `llm_mock.py` | 200 | Mock LLM responses | LIVE_SUPPORT | Test/offline mode |

### Dead / Orphan / Legacy (12 files, 3,216 lines)

| File | Lines | Purpose | Status | Evidence |
|------|-------|---------|--------|----------|
| `call_logger.py` | 261 | Old call logging | **DEAD** | Zero production importers |
| `live_metrics.py` | 496 | Old event/metrics system | **DEAD** | Zero production importers |
| `templates.py` | 449 | Old Jinja2 registry | **DEAD** | Only imported by tests |
| `eval_cases.py` | 12 | Text matching utilities | **ORPHAN** | Zero importers |
| `create.py` | 50 | Graph runner scaffold | **DEAD** | Zero importers, scaffold script |
| `join_reasoning_execution.py` | 100 | Reasoning join | **ORPHAN** | Zero importers |
| `score_execution.py` | 150 | Scoring utilities | **ORPHAN** | Zero importers |
| `redis_metrics.py` | 150 | Redis stream emitter | **DEAD** | Zero production importers |
| `preflight_check.py` | 100 | Standalone preflight | **DUPLICATE** | runner.py has preflight_verify_tests |
| `v2_dashboard.py` | 300 | V2 dashboard writer | **DUPLICATE** | Overlaps aggregate.py |
| `v2_metrics.py` | 400 | V2 metrics computation | **DUPLICATE** | Overlaps aggregate.py + metrics_v2.py |
| `templates/` (7 .jinja2 files) | ~100 | Old prompt templates | **DEAD** | Only referenced by templates.py |

### Analysis / Script Tools (3 files, 929 lines)

| File | Lines | Purpose | Status | Evidence |
|------|-------|---------|--------|----------|
| `aggregate.py` | 257 | Post-hoc event aggregation | ANALYSIS_TOOL | CLI entry point |
| `orchestrate.py` | 396 | V5 orchestrator | ANALYSIS_TOOL | Alternative to runner.py |
| `validate_cases_v2.py` | 276 | Case validation | DEV_TOOL | CLI entry point |

### Disconnected System (24 files)

| Directory | Purpose | Status | Evidence |
|-----------|---------|--------|----------|
| `graph_runner/` | DAG-based execution | **DISCONNECTED** | Zero imports from any production file |

---

## 3. Critical Workflow Traces

### Workflow 1: V2 Ablation Run (PRIMARY TODAY)

```
runner.py:main()
  → experiment_config.load_config()
  → prompt_registry.load_prompt_registry()
  → runner.py:run_ablation_mode()
    → logging_core.RunLogger() created
    → runner.py:run_all()
      → runner.py:_run_one()
        → logger.start_case()
        → runner.py:_run_one_inner()
          → execution_v2.run_v2()
            → assembly_engine.build() [prompt]
            → llm.call_model() [generation]
            → parser_v2.parse_v2_execution() [parse]
            → reasoning_v2.normalize_generation_v2() [normalize]
            → reconstructor.reconstruct_strict() [reconstruct]
            → exec_eval.exec_evaluate() [execute]
            → evaluator_v2.build_classifier_v2_vars() [classify]
            → llm.call_model() [classification]
            → evaluator_v2.parse_classifier_v2_output()
            → metrics_v2.derive_v2_signals()
            → logger.end_case() + logger.log_run()
    → logger.finalize()
```

**Alternate path:** When `config.execution.mode == "canonical"`, `exec_canonical.exec_canonical()` replaces `exec_eval.exec_evaluate()`.

### Workflow 2: V1 Single Condition Run

```
runner.py:_run_one_inner()
  → execution.run_single()
    → execution.build_prompt()
      → assembly_engine.build()
    → execution._attempt_and_evaluate()
      → llm.call_model()
      → execution.evaluate_case()
        → parse.parse_model_response() [3-tier]
        → execution._do_reconstruction()
        → evaluator.evaluate_output()
          → exec_eval.exec_evaluate()
          → evaluator.llm_classify() [v1 classifier]
    → logger.end_case() + logger.log_run()
```

### Workflow 3: Prompt Construction

**Canonical path (assembly_engine):**
```
execution.build_prompt() OR execution_v2.run_v2()
  → assembly_engine.resolve_condition() [from prompt_manifest.yaml]
  → assembly_engine.build(components, variables) [Jinja2 render]
  → RenderedPrompt with hashes + provenance
```

**Violation paths (bypass assembly_engine):**
```
retry_harness.py:1140-1157 — iteration k>0 builds via list.join()
retry_v2.py:40-124 — _CRITIQUE_PROMPTS hardcoded .format() strings
retry_v2.py:226-352 — retry prompt via f-string concatenation
```

### Workflow 4: Logging

**Canonical (logging_core.RunLogger):**
```
runner.py creates RunLogger → passes through entire stack
  → log_call() via llm.py:call_model()
  → end_case() via execution functions
  → log_run() via execution functions
  → finalize() at end of run
```

**Dead paths (still on disk):**
```
call_logger.py — zero importers in production
live_metrics.py — zero importers in production
```

---

## 4. Duplicate / Parallel Path Analysis

### 4.1 Template Systems (DUPLICATE)

| System | Files | Used by | Status |
|--------|-------|---------|--------|
| `assembly_engine.py` + `prompts/components/*.j2` + `prompt_registry.py` | 21 .j2 templates | All production code | CANONICAL |
| `templates.py` + `templates/*.jinja2` | 7 .jinja2 templates | Only test files | DEAD |

**Finding:** `templates.py` (449 lines) and `templates/` (7 files) are completely dead. Zero production importers. The assembly_engine replaced this system entirely. The old templates are architectural ghosts.

### 4.2 Logging Systems (DUPLICATE)

| System | File | Used by | Status |
|--------|------|---------|--------|
| `logging_core.py` (RunLogger) | 624 lines | All production code | CANONICAL |
| `call_logger.py` | 261 lines | Nothing | DEAD |
| `live_metrics.py` | 496 lines | Nothing | DEAD |

**Finding:** The Step 3 logging refactor successfully eliminated all production imports of `call_logger.py` and `live_metrics.py`. They are dead code. 757 lines deletable.

### 4.3 Metrics / Dashboard Systems (DUPLICATE)

| System | Files | Purpose | Status |
|--------|-------|---------|--------|
| `aggregate.py` | 257 lines | Post-hoc event aggregation from events.jsonl | CANONICAL |
| `v2_metrics.py` | 400 lines | Metrics from merged_run.jsonl | DUPLICATE |
| `v2_dashboard.py` | 300 lines | Dashboard text from v2_metrics | DUPLICATE |
| `live_metrics.py` | 496 lines | Old live metrics | DEAD |

**Finding:** `v2_metrics.py` and `v2_dashboard.py` compute metrics from `merged_run.jsonl` — a parallel data source to `events.jsonl`. This creates two metric computation paths that can diverge. `aggregate.py` is the canonical post-hoc aggregator for the new logging system.

### 4.4 Preflight / Validation (DUPLICATE)

| System | File | Used by | Status |
|--------|------|---------|--------|
| `runner.py:preflight_verify_tests()` | Inline in runner.py | Production runs | CANONICAL |
| `preflight_check.py` | 100 lines standalone | CLI standalone | DUPLICATE |

**Finding:** `preflight_check.py` reimplements what `runner.py:preflight_verify_tests()` already does. It's a standalone script that should call the canonical function instead.

### 4.5 Retry Prompt Construction (BYPASS)

| Path | Mechanism | Goes through assembly_engine? |
|------|-----------|------------------------------|
| Iteration k=0 | `assembly_engine.build()` | YES |
| Iteration k>0 (retry_harness.py) | List `.join()` + f-strings | NO |
| Mismatch critique (retry_v2.py) | `_CRITIQUE_PROMPTS.format()` | NO |
| Critique retry (retry_v2.py) | f-string concatenation | NO |

**Finding:** Retry iterations after the first bypass the assembly_engine entirely. No provenance tracking, no prompt hashing, no component audit trail for retry prompts. This is a genuine enforcement violation.

---

## 5. Dead Code and Migration Artifact Audit

### Confirmed Dead (safe to delete)

| File | Lines | Why dead | Blocker |
|------|-------|----------|---------|
| `call_logger.py` | 261 | Zero production importers after Step 3 refactor | Tests (test_call_logger.py, test_prompt_provenance.py) |
| `live_metrics.py` | 496 | Zero production importers after Step 3 refactor | Scripts (update_dashboards.py) |
| `templates.py` | 449 | Superseded by assembly_engine + prompt_registry | Tests (test_templates.py, test_integration_config_template.py) |
| `templates/` (7 files) | ~100 | Only referenced by dead templates.py | None |
| `eval_cases.py` | 12 | Zero importers | None |
| `create.py` | 50 | Graph runner scaffold script | None |
| `join_reasoning_execution.py` | 100 | Zero importers | None |
| `score_execution.py` | 150 | Zero importers | None |
| `redis_metrics.py` | 150 | Zero production importers | Scripts only |

**Total deletable: ~1,768 lines**

### Migration Artifacts (from v1→v2 transition)

| File | Status | Why it's an artifact |
|------|--------|---------------------|
| `evaluator.compute_alignment()` | DEPRECATED in code | Wrapper kept for retry_harness backward compat |
| `evaluator._REASONING_SIGNALS` | DEPRECATED in code | Keyword heuristics, logging only |
| `reasoning.enforce_schema_version()` | STALE | Schema v3 was for old events.jsonl; new canonical schema replaces |

### Graph Runner (disconnected system)

| Directory | Files | Lines | Status |
|-----------|-------|-------|--------|
| `graph_runner/` | 24 .py files | ~2,000 | DISCONNECTED |

Zero imports from any production file. Zero integration with runner.py, execution.py, or any canonical path. This is an experimental prototype that never shipped. It has its own state management, its own contracts, its own executors, its own prompt builder — a complete parallel universe.

---

## 6. Major Architectural Findings

### Finding 1: The system is NOT split-brained — v1 and v2 are intentionally parallel

Both paths are live by design. V1 handles 18+ conditions (baseline, diagnostic, guardrail, SCM, reasoning variants). V2 handles 3 primary conditions (baseline_v2, leg_reduction_v2, leg_reduction_lean_v2) plus retry variants. They share `exec_eval.py`, `llm.py`, `assembly_engine.py`, `logging_core.py`, and `experiment_config.py`. They intentionally do NOT share parsers, evaluators, or reasoning schemas. This is correct.

### Finding 2: 3,216 lines of dead code (37% of canonical runtime)

`call_logger.py`, `live_metrics.py`, `templates.py`, `templates/`, and 6 orphan files total 3,216 lines of dead code. This is not dangerous (nothing imports them) but it creates false confidence — a new contributor could easily think `templates.py` or `call_logger.py` are active.

### Finding 3: Retry prompt construction bypasses the canonical assembly engine

`retry_harness.py` (iterations k>0) and `retry_v2.py` (mismatch critique) build prompts via raw string concatenation, violating the assembly_engine's documented enforcement. These prompts have no provenance tracking. This means retry experiment analysis cannot reconstruct what prompt was sent.

### Finding 4: graph_runner/ is a complete parallel universe with zero integration

24 files implementing an alternative execution architecture. Own state, own contracts, own executors, own prompt builder. Never called by any production code. Either integrate it or delete it.

### Finding 5: v2_dashboard.py and v2_metrics.py create a shadow metrics path

These compute metrics from `merged_run.jsonl` — a different data source than `events.jsonl` (which `aggregate.py` uses). Two metric computation paths from two data sources is a divergence risk. The canonical path is `events.jsonl` → `aggregate.py`.

### Finding 6: templates.py is a ghost that looks alive

449 lines with a full Jinja2 registry, render functions, hash computation, and preflight validation. Has tests. Looks important. Is completely dead — superseded by `assembly_engine.py` + `prompt_registry.py` + `prompts/components/*.j2`. Only imported by test files.

### Finding 7: call_logger.py and live_metrics.py are ghosts that look alive

757 combined lines with complete implementations. Documented. Have tests. Zero production importers after the Step 3 logging refactor. The canonical logging path is `logging_core.RunLogger`.

### Finding 8: The orchestrate.py system is an alternative entry point with a different config schema

`orchestrate.py` loads YAML with `yaml.safe_load` directly (not `experiment_config.load_config()`). It has a flat `conditions` list vs nested dict. It creates `OrchestratorLogger` + per-worker `RunLogger`. It uses `ProcessPoolExecutor` directly. This is the v5 orchestrator that was never fully wired to the production path. `runner.py` + `parallel_runner.py` is the actual production path.

---

## 7. Proposed Canonical Ownership Model

| Concept | Owner | Files |
|---------|-------|-------|
| Entry point / orchestration | runner.py, parallel_runner.py | 2 files |
| V1 execution dispatch | execution.py | 1 file |
| V2 execution dispatch | execution_v2.py | 1 file |
| Prompt construction | assembly_engine.py, prompt_registry.py, prompts/ | 3 + templates |
| V1 parsing | parse.py | 1 file |
| V2 parsing | parser_v2.py | 1 file |
| Code execution | exec_eval.py, code_assembly.py | 2 files |
| V1 evaluation | evaluator.py, reasoning.py | 2 files |
| V2 evaluation | evaluator_v2.py, reasoning_v2.py, metrics_v2.py | 3 files |
| V1 retry | retry_harness.py | 1 file |
| V2 retry | retry_v2.py | 1 file |
| Logging | logging_core.py | 1 file |
| Config | experiment_config.py, constants.py | 2 files |
| Contract gating | contract.py, diff_gate.py | 2 files |
| Condition routing | condition_registry.py | 1 file |
| Post-hoc analysis | aggregate.py | 1 file |

---

## 8. Proposed Directory Tree

```
t3_code_generation/
├── runner.py                    # Entry point (stays at root)
├── parallel_runner.py           # Multi-worker orchestration
├── experiment_config.py         # Config loader
├── constants.py                 # Condition registry
├── logging_core.py              # Centralized logging
├── llm.py                       # LLM API wrapper
├── llm_mock.py                  # Mock responses
│
├── prompts/                     # Prompt system (SINGLE OWNER)
│   ├── assembly_engine.py       # Build function
│   ├── registry.py              # Template + nudge loader
│   ├── formatter.py             # Code file formatting (was prompts.py)
│   ├── components/              # .j2 templates (unchanged)
│   ├── registry.yaml            # Nudge texts
│   └── prompt_manifest.yaml     # Condition→component mapping
│
├── execution/                   # Execution dispatch
│   ├── v1.py                    # V1 dispatch (was execution.py)
│   ├── v2.py                    # V2 dispatch (was execution_v2.py)
│   ├── evaluate_case.py         # Shared pipeline (extract from execution.py)
│   └── contract_gated.py        # CGE (extract from execution.py)
│
├── parsing/                     # Response parsing
│   ├── v1.py                    # V1 parser (was parse.py)
│   ├── v2.py                    # V2 parser (was parser_v2.py)
│   ├── leg.py                   # LEG parser (was leg_reduction.py)
│   └── reconstructor.py         # File-dict reconstruction
│
├── evaluation/                  # Evaluation + classification
│   ├── exec_eval.py             # Code execution engine
│   ├── code_assembly.py         # Code assembly
│   ├── evaluator_v1.py          # V1 evaluation (was evaluator.py)
│   ├── evaluator_v2.py          # V2 evaluation
│   ├── reasoning_v1.py          # V1 reasoning schema (was reasoning.py)
│   ├── reasoning_v2.py          # V2 reasoning normalization
│   ├── contracts_v2.py          # V2 schema contracts
│   └── metrics_v2.py            # V2 signal derivation
│
├── retry/                       # Retry harnesses
│   ├── v1.py                    # V1 retry (was retry_harness.py)
│   └── v2.py                    # V2 retry (was retry_v2.py)
│
├── support/                     # Support modules
│   ├── condition_registry.py    # Case/condition compat
│   ├── failure_classifier.py    # Heuristic failure typing
│   ├── scm_data.py              # SCM evidence data
│   ├── mapping_v2.py            # Case→family mapping
│   ├── module_exec.py           # Dual execution (side-channel)
│   ├── disagreement_classifier.py
│   ├── _stdlib.py               # Stdlib whitelist
│   └── merge_run.py             # Parallel run merger
│
├── nudges/                      # Nudge operator system (unchanged)
│
├── analysis/                    # Post-hoc analysis tools
│   ├── aggregate.py             # Event aggregation
│   ├── validate_cases.py        # Case validation
│   └── orchestrate.py           # V5 orchestrator (if kept)
│
├── scripts/                     # Runner scripts (unchanged)
├── tests/                       # Test suite (unchanged)
├── tests_v2/                    # Case test functions (unchanged)
├── configs/                     # YAML configs (unchanged)
│
└── DELETED/                     # (not committed — removed entirely)
    ├── call_logger.py
    ├── live_metrics.py
    ├── templates.py
    ├── templates/
    ├── eval_cases.py
    ├── create.py
    ├── join_reasoning_execution.py
    ├── score_execution.py
    ├── redis_metrics.py
    ├── preflight_check.py
    ├── v2_dashboard.py
    ├── v2_metrics.py
    └── graph_runner/            # (or integrate properly)
```

---

## 9. Staged Refactor Plan

### Stage 1: Delete confirmed dead code
**Objective:** Remove files with zero production importers.
**Files:** `call_logger.py`, `live_metrics.py`, `templates.py`, `templates/`, `eval_cases.py`, `create.py`, `join_reasoning_execution.py`, `score_execution.py`, `redis_metrics.py`, `preflight_check.py`
**Risk:** LOW — zero production importers verified.
**Validation:** `grep -rl` confirms no production imports. Delete associated tests too (`test_call_logger.py`, `test_prompt_provenance.py`, `test_templates.py`, `test_integration_config_template.py`).
**Becomes deletable:** ~1,768 lines + test files.

### Stage 2: Resolve v2_dashboard / v2_metrics overlap
**Objective:** Decide whether `v2_dashboard.py` + `v2_metrics.py` stay (scripts use them) or get replaced by `aggregate.py`.
**Files:** `v2_dashboard.py`, `v2_metrics.py`, `aggregate.py`
**Risk:** MEDIUM — scripts depend on v2_dashboard/v2_metrics.
**Validation:** Verify scripts can switch to aggregate.py or keep v2_* as script-only tools.
**Invariant:** No metric computation divergence between events.jsonl and merged_run.jsonl paths.

### Stage 3: Fix retry prompt assembly bypass
**Objective:** Route ALL retry prompt construction through assembly_engine.
**Files:** `retry_harness.py` (lines 1140-1157), `retry_v2.py` (lines 40-124, 226-352)
**Risk:** MEDIUM — changes prompt content for retry iterations (could affect experiment reproducibility).
**Validation:** Verify retry prompts are byte-identical before/after for existing conditions.
**Becomes canonical:** All prompts go through assembly_engine with full provenance.

### Stage 4: Decide graph_runner fate
**Objective:** Either integrate graph_runner into the canonical path or delete it.
**Files:** `graph_runner/` (24 files, ~2,000 lines)
**Risk:** LOW if deleted. HIGH if integrated (major architectural change).
**Validation:** Confirm zero production dependencies.

### Stage 5: Directory restructure
**Objective:** Move files into ownership-based directory structure.
**Risk:** HIGH — breaks all imports. Requires updating every file.
**Validation:** Full test suite must pass after restructure.
**Approach:** Use a Python-aware rename tool or do it as one atomic commit.

---

## 10. Deletion Candidates

| File | Lines | Why deletable | Blocker | Stage |
|------|-------|---------------|---------|-------|
| `call_logger.py` | 261 | Zero production importers | test_call_logger.py, test_prompt_provenance.py | 1 |
| `live_metrics.py` | 496 | Zero production importers | scripts/update_dashboards.py | 1 |
| `templates.py` | 449 | Superseded by assembly_engine | test_templates.py, test_integration_config_template.py | 1 |
| `templates/` (7 files) | ~100 | Only referenced by dead templates.py | None | 1 |
| `eval_cases.py` | 12 | Zero importers | None | 1 |
| `create.py` | 50 | Graph runner scaffold | None | 1 |
| `join_reasoning_execution.py` | 100 | Zero importers | None | 1 |
| `score_execution.py` | 150 | Zero importers | None | 1 |
| `redis_metrics.py` | 150 | Zero production importers | None | 1 |
| `preflight_check.py` | 100 | Duplicates runner.py:preflight_verify_tests | None | 1 |
| `graph_runner/` | ~2,000 | Zero integration | Decision needed | 4 |

---

## 11. Open Uncertainties

### 11.1 Is orchestrate.py intended to replace runner.py?
**Why unclear:** orchestrate.py has a different config schema and uses ProcessPoolExecutor directly. It was built as "v5 orchestrator" but runner.py + parallel_runner.py is the actual production path.
**Resolution:** Ask project lead. If orchestrate.py is the future, it needs to adopt ExperimentConfig. If not, move to analysis/.

### 11.2 Should graph_runner/ be integrated or deleted?
**Why unclear:** It's a complete alternative execution architecture with 24 files. Zero integration. Could be a planned replacement or an abandoned experiment.
**Resolution:** Ask project lead. If keeping, needs integration plan. If not, delete.

### 11.3 Are v1 conditions still running in production ablations?
**Why unclear:** The current YAML configs use v2 conditions (baseline_v2, etc.). But v1 conditions (baseline, diagnostic, etc.) are still reachable and have tests.
**Resolution:** Check recent ablation configs. If only v2 is used, v1 path could be marked deprecated.

### 11.4 Does exec_canonical.py see production use?
**Why unclear:** It's behind `config.execution.mode == "canonical"` which is not the default.
**Resolution:** Check if any production configs set this flag.
