# Repository Map

Quick reference for navigating this codebase. Read this first.

---

## Directory Layout

```
t3_code_generation/
├── core/                          # ALL production source code
│   ├── config/                    # Configuration system
│   │   ├── constants.py           # V2_CONDITIONS, condition labels
│   │   ├── experiment_config.py   # YAML config loading + validation
│   │   ├── paths.py               # PROJECT_ROOT and path constants
│   │   ├── preflight.py           # Pre-run config validation
│   │   └── config_storage/        # 1,284 experiment YAML configs
│   │       └── focused_50t/       # Main 50-trial production configs
│   │
│   ├── pipeline/                  # Generation + execution pipeline
│   │   ├── orchestration/         # Run control
│   │   │   ├── runner.py          # Entry point — loads config, dispatches conditions
│   │   │   ├── execution_v2.py    # V2 single-shot path (9 stages)
│   │   │   ├── retry_v2.py        # V2 retry path (up to 3 attempts)
│   │   │   └── orchestrate.py     # Multi-worker orchestration
│   │   │
│   │   ├── prompting/             # Strict prompt compiler (13 modules)
│   │   │   ├── compiler.py        # compile(program, inputs) → CompiledPrompt
│   │   │   ├── registry.py        # Loads components + metadata, validates
│   │   │   ├── contracts.py       # PromptComponent, PromptProgram, CompiledPrompt
│   │   │   ├── sections.py        # Section enum (14 structural sections)
│   │   │   ├── validator.py       # Ordering, deps, collisions, input checks
│   │   │   ├── section_parser.py  # Parses section markers from rendered output
│   │   │   ├── metadata.py        # Loads component_metadata.yaml, AST drift checks
│   │   │   ├── tracking.py        # Runtime variable access tracking (Jinja2)
│   │   │   ├── exceptions.py      # 17 error types
│   │   │   ├── preflight.py       # Startup validation
│   │   │   ├── provenance.py      # Provenance serialization
│   │   │   └── tools.py           # generate_metadata_from_ast CLI
│   │   │
│   │   ├── parsing/
│   │   │   └── parser_v2.py       # Three-tier parser (execution/format/recovery)
│   │   │
│   │   ├── execution/
│   │   │   ├── exec_canonical.py  # Subprocess execution (13 categories)
│   │   │   ├── test_loader.py     # Shared: load_module_from_code, _load_v2_test
│   │   │   └── module_exec.py     # Module-level execution utilities
│   │   │
│   │   ├── llm.py                 # OpenAI/Anthropic API wrapper
│   │   ├── reconstructor.py       # 5-gate file reconstruction
│   │   └── code_assembly.py       # Code assembly with import rewriting
│   │
│   ├── evaluation/                # Reasoning evaluation + metrics
│   │   ├── evaluator_v2.py        # V2 classifier (4 dimensions + failure type)
│   │   ├── metrics_v2.py          # V2Signals, LEG_v2, category computation
│   │   ├── reasoning_v2.py        # Commitment normalization, NormalizedArtifact
│   │   ├── mapping_v2.py          # Canonical bug-family mapping
│   │   ├── score_execution.py     # leg_candidate, lucky_fix_candidate flags
│   │   ├── ast_eval.py            # AST-based code evaluation
│   │   ├── ast_checkers.py        # AST checker implementations
│   │   └── oracle_eval/           # Ground-truth oracle evaluator (standalone)
│   │       └── reasoning_truth.py
│   │
│   ├── contracts/
│   │   ├── contracts_v2.py        # CONDITION_TO_SCHEMA, SCHEMA_REQUIRED_FIELDS
│   │   └── contract.py            # CGE contract parsing (v1)
│   │
│   ├── registry/
│   │   ├── condition_registry.py  # 36 conditions (11 v2 + 25 v1)
│   │   └── prompt_registry.py     # Old registry (shim → legacy)
│   │
│   ├── harness/
│   │   └── run_case.py            # Subprocess entry point for test execution
│   │
│   ├── logging_/
│   │   ├── logging_core.py        # Canonical event schema v7
│   │   ├── call_logger.py         # Per-LLM-call logging
│   │   ├── live_metrics.py        # Real-time dashboard metrics
│   │   └── v2_metrics.py          # V2 aggregation dashboard
│   │
│   ├── prompts/                   # Prompt templates + metadata
│   │   ├── components/            # All .j2 templates (canonical source)
│   │   ├── component_metadata.yaml # Authoritative input contracts
│   │   ├── component_versions.json # Version-hash registry
│   │   ├── prompt_manifest.yaml   # Condition → component mapping
│   │   └── registry.yaml          # Nudge texts + CGE instructions
│   │
│   ├── reasoning_schema.py        # Shared constants (schema version, field names, VALID_FAILURE_TYPES)
│   ├── scm_data.py                # Structural causal model evidence data
│   ├── text_extraction.py         # Code extraction utilities
│   └── types.py                   # Shared type definitions
│
├── case_data/                     # Benchmark cases (DATA, not code)
│   ├── cases_v2.json              # 58 cases with full metadata
│   ├── code_snippets_v2/          # 58 dirs of buggy Python code
│   ├── tests_v2/                  # 28 invariant test files (test_{family}.py)
│   ├── reference_fixes/           # Known-good fixes for validation
│   ├── ast_specs.json             # AST checker specifications
│   └── validation/                # Case validation data
│
├── CLAUDE_RULES/                  # Claude Code operating rules
│   ├── ENTRYPOINT.md              # Mandatory plan→approve→implement→audit protocol
│   ├── core/                      # Hard constraints, code quality, architecture
│   ├── tasks/                     # Task-specific rules (refactor, debug, feature)
│   └── audits/                    # Pre/post-action checklists
│
├── scripts/                       # Research tooling (NEVER DELETE)
│   └── (74 Python + 3 shell scripts)
│
├── artifacts/                     # Generated outputs and documentation
│   ├── plans/                     # Versioned implementation plans
│   ├── docs/                      # PROJECT_OVERVIEW.md and design docs
│   ├── audits/                    # Forensic audit reports
│   ├── analysis/                  # Analysis reports (leg_effect_canonical_report.md)
│   ├── analysis_output/           # Aggregated metrics
│   ├── outputs/                   # Final paper analysis results
│   └── deep_research_reports/     # Extended research documents
│
├── logs/                          # Experiment run logs (100+ run dirs)
│   └── {run_name}/               # events.jsonl, calls/, metrics.json
│
├── dashboard/                     # Live monitoring dashboard
│
├── side_projects/                 # Independent projects (graph_runner, reddit_med_signal)
│
├── CLAUDE.md                      # Top-level operating rules (loads CLAUDE_RULES/)
├── REPO_MAP.md                    # THIS FILE
└── pyproject.toml                 # Python project config, pytest settings
```

---

## V2 Production Path (the files that run experiments)

These are the ~15 files that matter for production execution. Everything else is support, analysis, or legacy.

```
runner.py → execution_v2.py (single-shot) OR retry_v2.py (retry)
  │
  ├── prompting/compiler.py    — assembles prompt from .j2 components
  ├── llm.py                   — calls OpenAI/Anthropic API
  ├── parser_v2.py             — extracts JSON from model response
  ├── reconstructor.py         — rebuilds source files from JSON
  ├── exec_canonical.py        — executes code in subprocess
  │   └── harness/run_case.py  — subprocess entry point
  ├── evaluator_v2.py          — LLM-based reasoning classifier (4 dims)
  ├── metrics_v2.py            — derives LEG/lucky_fix/category from signals
  ├── reasoning_v2.py          — normalizes commitments
  └── logging_core.py          — persists canonical events
```

**Import rule**: V2 production code imports from `core.*` only. It never imports from `legacy/` or from shim paths.

---

## Prompt System

| File | Purpose |
|---|---|
| `core/prompts/components/*.j2` | Jinja2 templates (canonical source, ~35 files) |
| `core/prompts/component_metadata.yaml` | Authoritative input contracts for every component |
| `core/prompts/component_versions.json` | Version-hash registry for drift detection |
| `core/prompts/prompt_manifest.yaml` | Maps conditions → component lists |
| `core/pipeline/prompting/compiler.py` | `compile(program, inputs) → CompiledPrompt` |
| `core/pipeline/prompting/registry.py` | Loads components + metadata, validates |
| `core/pipeline/prompting/metadata.py` | AST drift checks, condition expression engine |

**Key v2 components** (the ones used in production):
- `task_and_code.j2` — task description + code files (shared)
- `output_instruction_v3.j2` — JSON output format spec
- `leg_reduction_v2.j2` — 5-step structured reasoning (full)
- `leg_reduction_lean_v2.j2` — compressed structured reasoning (lean)
- `classify_reasoning_v2.j2` — 4-dimension reasoning classifier
- `critique_mismatch_v2.j2` — one-sentence mismatch critique
- `critique_strict.j2` / `critique_moderate.j2` / `critique_aggressive.j2` — retry critique variants
- `critique_retry.j2` — retry prompt with optional critique
- `test_feedback_retry.j2` — test-feedback retry prompt

---

## Case Data

| Location | What |
|---|---|
| `case_data/cases_v2.json` | 58 cases with full metadata (family, difficulty, failure_mode, ground_truth_bug, etc.) |
| `case_data/code_snippets_v2/{family_difficulty}/` | Buggy Python source files |
| `case_data/tests_v2/test_{family}.py` | Invariant tests: `test_a(mod)`, `test_b(mod)`, `test_c(mod)` |
| `case_data/reference_fixes/` | Known-good fix implementations |

**Families**: 28 (alias_config, async_race_lock, cache_invalidation_order, ..., wrong_condition)
**Difficulties**: A (simple), B (cross-function), C (cross-boundary), L3 (deep causal)
**Failure modes**: 22 types (ALIASING, STALE_CACHE, HIDDEN_DEPENDENCY, ...)

---

## Evaluation Pipeline Quick Reference

```
Model Response (raw text)
  │
  ├── parser_v2.py → ParsedGenerationV2 (full_json, files_dict, parse_status)
  │     Tiers: execution (drives pipeline) → format (diagnostic) → recovery (diagnostic)
  │
  ├── reconstructor.py → ReconstructionResult (status, files)
  │     Gates: UNCHANGED → empty → sentinel phrase → ast.parse → semantic check
  │     Blocks on: RECON_EMPTY_FILE, RECON_SENTINEL_MISMATCH, RECON_INVALID_CODE
  │
  ├── exec_canonical.py → {pass, score, category}
  │     Categories: EXECUTION_SUCCESS (1.0), INVARIANT_FAILURE (0.2),
  │                 INVARIANT_CRASH (0.1), SYNTAX/IMPORT/NAME/TIMEOUT (0.0)
  │
  ├── evaluator_v2.py → ClassifierResultV2 (4 dimensions + failure_type)
  │     Dimensions: mechanism_identified, commitments_extracted,
  │                 commitments_satisfied, reasoning_code_alignment
  │     Each: CORRECT | PARTIAL | WRONG
  │
  └── metrics_v2.py → V2Signals → v2_category
        Categories: interpretable_success, LEG_v2, lucky_fix_v2,
                    full_failure_v2, alignment_failure_pass, classifier_failure_v2
```

---

## Experimental Conditions

| Condition | Type | What it does |
|---|---|---|
| `baseline_v2` | Single-shot | Task + code + JSON output instruction |
| `leg_reduction_v2` | Single-shot | 5-step structured reasoning scaffold (full) |
| `leg_reduction_lean_v2` | Single-shot | Compressed reasoning scaffold (lean) |
| `retry_bare_retry_v2` | Retry (3x) | Previous response + same prompt, no feedback |
| `retry_leg_critique_strict_v2` | Retry (3x) | Mismatch critique between reasoning and code |
| `retry_reasoning_only_critique_v1` | Retry (3x) | Reasoning weakness feedback (no code access) |

---

## Key Files to Read First

If you're trying to understand the system, read these in order:

1. `core/pipeline/orchestration/runner.py` — entry point, dispatch logic
2. `core/pipeline/orchestration/execution_v2.py` — the 9-stage single-shot pipeline
3. `core/pipeline/parsing/parser_v2.py` — how model responses are parsed
4. `core/pipeline/execution/exec_canonical.py` — how code is executed
5. `core/evaluation/evaluator_v2.py` — how reasoning is classified
6. `core/evaluation/metrics_v2.py` — how categories are derived
7. `core/prompts/component_metadata.yaml` — what each prompt component expects

---

## Legacy Code

Legacy (v1) code has been moved to `legacy/` with shims at original import paths. Shims emit `DeprecationWarning` on import and raise `RuntimeError` if `STRICT_V2_ONLY=1` is set.

**V1 files in legacy** (if `legacy/` dir is populated):
- `legacy/orchestration/` — evaluator.py, execution.py, retry_harness.py, leg_evaluator.py
- `legacy/evaluation/` — reasoning.py, failure_classifier.py, disagreement_classifier.py, eval_cases.py
- `legacy/parsing/` — parse.py (v1 8-tier parser)
- `legacy/execution/` — exec_eval.py (in-process execution + _CASE_TESTS)
- `legacy/generation/` — assembly_engine.py, prompt_registry.py, templates.py

**Rule**: V2 production code never imports from `legacy/`. Scripts and tests may use shim paths.

---

## Experiment Logs

Run logs are in `logs/{run_name}/` with:
- `events.jsonl` — canonical event stream (schema v7)
- `calls/` — per-LLM-call JSON files (prompt + response + metadata)
- `metrics.json` — aggregated run metrics

Config files are in `core/config/config_storage/` (1,284 YAML files).

---

## Common Tasks

| Task | Start here |
|---|---|
| Run an experiment | `python core/pipeline/orchestration/runner.py --config core/config/config_storage/{name}.yaml` |
| Check a case's buggy code | `case_data/code_snippets_v2/{family}_{difficulty}/` |
| Check a case's test | `case_data/tests_v2/test_{family}.py` |
| See case metadata | `case_data/cases_v2.json` |
| Read experiment results | `logs/{run_name}/events.jsonl` |
| Read analysis reports | `artifacts/analysis/` and `artifacts/docs/` |
| Check what a prompt looks like | `core/prompts/components/{name}.j2` |
| Check prompt contracts | `core/prompts/component_metadata.yaml` |
| Validate prompt system | `python -c "from core.pipeline.prompting.preflight import ..."` |
