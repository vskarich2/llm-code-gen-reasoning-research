# Plan: YAML Config Migration Script (v1)

## Task Type
FEATURE -- new standalone migration script

## Scope
Create a single new file: `scripts/migrate_yaml_configs.py`

## What It Does
Reads all `*.yaml` files in `core/config/config_storage/`, applies canonical
default backfills and dead-config removal, writes them back in place.

## Mutations Applied

### (a) execution section -- backfill missing keys
Keys and defaults:
- worker_stagger_seconds: 3
- subprocess_timeout: 30
- worker_timeout_seconds: 600
- worker_graceful_shutdown_seconds: 30
- mode: "canonical"
- keep_eval_dirs: false
- validate_prompts: true
- recovery_execution: true
- max_orchestrator_attempts: 10
- anthropic_client_timeout: 120.0
- anthropic_max_output_tokens: 8192

### (b) evaluation section -- backfill missing keys
Keys and defaults:
- classifier_mode: "blind"
- reasoning_correct_mode: "strict"
- classifier_template: "classify_reasoning_v2"
- classifier_schema_variant: "v2_semicolon"
- generation_schema_variant: "v2"

### (c) evaluation.subprocess_timeout -- REMOVE
Misplaced; belongs in execution.

### (d) models.no_temperature_prefixes -- backfill if missing
Default: ["o1", "o3", "o4", "gpt-5"]

### (e) logging.store -- REMOVE entire sub-section
Dead config.

### (f) Skip logic
- Skip `default.yaml` entirely.
- Skip sections that don't exist in a file (minimal configs).

## Output
Per-file summary of fields added/removed. Total count of files touched.

## Files Modified
- NEW: `scripts/migrate_yaml_configs.py`

## Invariants
- No hardcoded experimental parameters (this is a migration tool, not experiment code).
- No silent failures -- all file I/O errors logged/raised.
- Max 50 lines per function, max 300 lines per file.

## Risks
- None significant. Script is idempotent (re-running is safe).
