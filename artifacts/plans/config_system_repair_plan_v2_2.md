# Config System Repair Plan V2.2

Strict patch revision of V2.1. All V2.1 content remains in force except where explicitly superseded below.

---

## Changes from V2.1

| Fix | V2.1 Defect | V2.2 Correction |
|---|---|---|
| 1 | CONFIG_SCHEMA is not checked against dataclass fields at load time | Runtime bijection assertion: every dataclass field has a schema entry, every schema entry targets a real field |
| 2 | Pipeline contract validation uses ad-hoc structure checks | Explicit REQUIRED_*_FIELDS sets at every stage boundary with field-level assertions |
| 3 | Smoke gate runs only first generation model | Per-model smoke: at least one smoke case per distinct generation model |
| 4 | Full prompts not stored as plain-text files | Mandatory prompt_store.py writes `prompts/{event_id}_call{N}.txt`; events reference via prompt_meta |
| 5 | No truncation tracking | Every call record includes truncated + truncation_reason |
| 6 | Migration schema_default duplicates values in Python | Migration fallbacks loaded from canonical default.yaml, not hardcoded |
| 7 | CONFIG_LOG_COVERAGE only checks declarations, not actual emission | Runtime event validation on smoke events + sampled real events |

---

## FIX 1 — Schema Bijection Enforcement (supersedes V2.1 Fix 1 partial)

### Problem

V2.1's CONFIG_SCHEMA is an improvement over manual allow-lists but does not verify that every dataclass field appears in the schema, or that every schema target is a real field. A field added to ExecutionConfig but absent from CONFIG_SCHEMA is silently unpopulated.

### Solution

Add `_validate_schema_completeness()`, called once during `load_config()` before any parsing.

File: `core/config/experiment_config.py`

```python
def _validate_schema_completeness():
    """Verify CONFIG_SCHEMA and dataclass fields are in bijection.
    
    Every non-internal dataclass field must have a CONFIG_SCHEMA entry.
    Every CONFIG_SCHEMA target must be a real dataclass field or an
    acknowledged sub-object marker.
    
    Runs once at config load. Crashes on any mismatch.
    """
    # Collect all dataclass fields, grouped by section
    section_fields = {
        "execution": set(ExecutionConfig.__dataclass_fields__.keys()),
        "evaluation": set(EvaluationConfig.__dataclass_fields__.keys()),
        "logging": set(LoggingConfig.__dataclass_fields__.keys()),
        "models": set(ModelsConfig.__dataclass_fields__.keys()),
    }
    
    # Collect all schema targets, grouped by section
    schema_targets: dict[str, set[str]] = {}
    for yaml_path, (section, field) in CONFIG_SCHEMA.items():
        if section not in schema_targets:
            schema_targets[section] = set()
        schema_targets[section].add(field)
    
    errors = []
    for section, dc_fields in section_fields.items():
        st = schema_targets.get(section, set())
        
        # Remove acknowledged sub-object markers (prefixed with _sub_)
        real_targets = {f for f in st if not f.startswith("_sub_")}
        
        # Remove internal fields (prefixed with _)
        real_dc_fields = {f for f in dc_fields if not f.startswith("_")}
        
        # Exempt fields documented here with reason
        # ModelsConfig.generation, evaluator, failure_classifier_name, classifier_name
        # are parsed specially (list/object/property), not via CONFIG_SCHEMA 1:1 mapping
        _EXEMPT = {
            ("models", "generation"),           # list of ModelSpec, parsed specially
            ("models", "evaluator"),            # EvaluatorModelSpec, parsed specially
            ("models", "failure_classifier_name"),  # nullable, parsed specially
            ("models", "classifier_name"),      # @property, not a stored field
        }
        exempt_for_section = {f for (s, f) in _EXEMPT if s == section}
        real_dc_fields -= exempt_for_section
        
        missing_in_schema = real_dc_fields - real_targets
        extra_in_schema = real_targets - real_dc_fields
        
        if missing_in_schema:
            errors.append(
                f"CONFIG_SCHEMA missing mappings for {section}: "
                f"{sorted(missing_in_schema)}. "
                f"Add entries to CONFIG_SCHEMA for these dataclass fields."
            )
        if extra_in_schema:
            errors.append(
                f"CONFIG_SCHEMA has targets not in {section} dataclass: "
                f"{sorted(extra_in_schema)}. "
                f"Remove stale entries or add fields to the dataclass."
            )
    
    if errors:
        raise RuntimeError(
            "CONFIG SCHEMA BIJECTION FAILURE:\n" +
            "\n".join(f"  {e}" for e in errors)
        )
```

### When it runs

Called at the top of `load_config()`, before YAML is even read:

```python
def load_config(path: str, cli_overrides=None):
    _validate_schema_completeness()  # schema integrity first
    # ... rest of loading
```

This runs on every process startup. A field added to the dataclass without a CONFIG_SCHEMA entry crashes immediately with a message naming the missing field.

### Exempt fields

| Field | Section | Reason |
|---|---|---|
| `generation` | models | List of ModelSpec, parsed via loop not 1:1 mapping |
| `evaluator` | models | EvaluatorModelSpec, parsed as sub-object |
| `failure_classifier_name` | models | Nullable field parsed from `models.failure_classifier.name` |
| `classifier_name` | models | @property derived from other fields, not stored |

These exemptions are hardcoded in `_EXEMPT` with comments. No silent exemptions.

### Sub-objects

Schema entries like `("execution", "_sub_token_budgets")` use the `_sub_` prefix. These are filtered out of bijection checks because they represent YAML sub-sections parsed into nested dataclass fields, not 1:1 field mappings.

---

## FIX 2 — Explicit Pipeline Field Contracts (supersedes V2.1 Fix 2 partial)

### Design

File: `core/pipeline/orchestration/execution_v2.py` (top of file)

Define explicit required field sets for every stage boundary:

```python
# ── Pipeline stage contracts ──
# These sets define the EXACT fields each stage must produce for its consumer.
# Renaming, removing, or adding a field requires updating these sets.
# Validation runs at smoke gate and asserts field presence.

GENERATION_OUTPUT_CONTRACT = frozenset({
    "root_cause",
    "fix_strategy",
    "files",
})

CLASSIFIER_INPUT_CONTRACT = frozenset({
    "root_cause",
    "fix_strategy",
    "code",
    "task",
    "failure_types",
})

CLASSIFIER_OUTPUT_CONTRACT = frozenset({
    "mechanism_identified",
    "commitments_extracted",
    "commitments_satisfied",
    "reasoning_code_alignment",
})

EVALUATION_INPUT_CONTRACT = frozenset({
    "mechanism_identified",
    "commitments_extracted",
    "commitments_satisfied",
    "reasoning_code_alignment",
})
```

### Validation function

```python
def _validate_pipeline_contracts(config):
    """Verify stage boundaries produce required fields.
    
    1. Generation output contract: output_instruction template must require
       schema_line containing GENERATION_OUTPUT_CONTRACT fields.
    2. Classifier output → evaluation input: CLASSIFIER_OUTPUT_CONTRACT must
       be a superset of EVALUATION_INPUT_CONTRACT.
    3. Schema variant must be known.
    """
    # Contract 1: generation schema mentions required fields
    # This is enforced by the output_instruction template which embeds
    # a JSON schema containing root_cause, fix_strategy, files.
    # The compiler's validate_output_contract() checks this at compile time.
    # We verify the contract sets are consistent here.
    
    # Contract 2: classifier outputs cover evaluation inputs
    missing = EVALUATION_INPUT_CONTRACT - CLASSIFIER_OUTPUT_CONTRACT
    if missing:
        raise RuntimeError(
            f"Pipeline contract violation: CLASSIFIER_OUTPUT_CONTRACT "
            f"missing fields required by evaluation: {sorted(missing)}"
        )
    
    # Contract 3: schema variant is known
    variant = config.evaluation.classifier_schema_variant
    if variant not in {"v2_semicolon", "v3_json"}:
        raise RuntimeError(
            f"Pipeline contract violation: unknown classifier_schema_variant "
            f"'{variant}'. Known variants: v2_semicolon, v3_json"
        )
    
    gen_variant = config.evaluation.generation_schema_variant
    if gen_variant not in {"v2", "v3"}:
        raise RuntimeError(
            f"Pipeline contract violation: unknown generation_schema_variant "
            f"'{gen_variant}'. Known variants: v2, v3"
        )
```

### Runtime assertion in _classify_reasoning

Add to `_classify_reasoning()` after getting classifier result:

```python
# Verify classifier produced all required fields
for field in CLASSIFIER_OUTPUT_CONTRACT:
    val = getattr(classifier_result, field, None)
    if val is None and classifier_result.parse_error is None:
        raise RuntimeError(
            f"Classifier contract violation: field '{field}' is None "
            f"but classifier reported no parse error. "
            f"case={cid}, condition={condition}"
        )
```

### Where validation runs

- `_validate_pipeline_contracts(config)` runs in `_smoke_gate()` as Gate 3.5
- Runtime field assertions run on every case in `_classify_reasoning()`
- Contract set consistency (Contract 2) is also a static assertion — if someone edits the sets, the check catches it immediately

### Failure mode

Renaming `fix_strategy` to `fix_plan` in a template without updating GENERATION_OUTPUT_CONTRACT causes:
1. Smoke gate Gate 3 (prompt compilation) catches the schema_line mismatch
2. If it somehow passes compilation, the runtime assertion in _classify_reasoning catches the None field

---

## FIX 3 — Per-Model Smoke Coverage (supersedes V2.1 Section "FIX 4")

### Change

`_select_smoke_cases()` now returns a coverage matrix across models, not just conditions.

```python
def _select_smoke_models(config):
    """Select models for smoke coverage.
    
    Returns list of model names. At least one. At most two if multiple configured.
    """
    models = [m.name for m in config.models.generation]
    if len(models) <= 1:
        return models
    # First model + one additional (last, to maximize diversity)
    return [models[0], models[-1]]
```

### Updated smoke gate

```python
def _smoke_gate(config, cases, run_dir):
    """Mandatory pre-launch validation. Aborts on any failure."""
    print("SMOKE GATE: starting...", flush=True)
    
    smoke_cases = _select_smoke_cases(cases, config)
    smoke_models = _select_smoke_models(config)
    conditions = list(config.conditions.keys())
    retry_conditions = [c for c in conditions if config.conditions[c].retry.enabled]
    baseline_condition = conditions[0]
    
    # Gate 3: Compile ALL condition prompts
    _smoke_compile_all_prompts(config)
    print("  GATE 3: prompt compilation OK", flush=True)
    
    # Gate 3.5: Pipeline contract validation
    _validate_pipeline_contracts(config)
    print("  GATE 3.5: pipeline contracts OK", flush=True)
    
    # Gate 5: Per-model E2E
    for model_name in smoke_models:
        label = f"baseline_{model_name}"
        _smoke_execute_case(
            config, smoke_cases["baseline_single_file"],
            baseline_condition, run_dir, label, model_override=model_name)
        print(f"  GATE 5: {label} OK", flush=True)
        
        # Multi-file with first model only
        if model_name == smoke_models[0]:
            _smoke_execute_case(
                config, smoke_cases["multi_file"],
                baseline_condition, run_dir, "multi_file",
                model_override=model_name)
            print(f"  GATE 5: multi_file OK", flush=True)
    
    # Gate 5c: Retry (conditional, first model)
    if "retry" in smoke_cases and retry_conditions:
        _smoke_execute_retry(
            config, smoke_cases["retry"],
            retry_conditions[0], run_dir, model_override=smoke_models[0])
        print("  GATE 5c: retry E2E OK", flush=True)
    
    # Gate 5d: Grounded classifier (conditional, first model)
    if "grounded_classifier" in smoke_cases:
        _smoke_execute_case(
            config, smoke_cases["grounded_classifier"],
            baseline_condition, run_dir, "grounded_classifier",
            model_override=smoke_models[0])
        print("  GATE 5d: grounded classifier E2E OK", flush=True)
    
    # Gate 5e: Prompt file validation on smoke events
    _smoke_validate_prompt_files(run_dir)
    print("  GATE 5e: prompt file integrity OK", flush=True)
    
    # Gate 5f: Config-log emission validation on smoke events
    _smoke_validate_log_coverage(run_dir)
    print("  GATE 5f: config-log coverage OK", flush=True)
    
    print("SMOKE GATE: all checks passed", flush=True)
```

### _smoke_execute_case updated signature

```python
def _smoke_execute_case(config, case, condition, run_dir, label,
                        model_override=None):
    model = model_override or config.models.generation[0].name
    # ... rest same as V2.1
```

### Minimum coverage matrix

| Category | Model A (first) | Model B (last, if exists) |
|---|---|---|
| Baseline single-file | REQUIRED | REQUIRED |
| Multi-file | REQUIRED | not required |
| Retry | REQUIRED (if retry conditions) | not required |
| Grounded classifier | REQUIRED (if grounded mode) | not required |

If only one model is configured, Model A = Model B and the matrix collapses to V2.1 behavior.

---

## FIX 4 — Full Prompt Logging (new section)

### Current state

The system already stores full prompts in `calls/{call_id:06d}.json` files via both `call_logger.py:emit_call()` and `logging_core.py:RunLogger.log_call()`. Each call record includes `prompt_raw`, `prompt_hash` (SHA-256), `prompt_length`, and post-write hash verification.

Events.jsonl references calls via `request_path: "calls/{call_id:06d}.json"`.

### What is missing

1. No plain-text prompt-only files (current files are JSON with prompt+response+metadata)
2. No `truncated` / `truncation_reason` fields
3. No `prompt_meta` section in events.jsonl with direct hash+length+file reference

### New component: prompt_store.py

File: `core/logging_/prompt_store.py`

```python
"""Plain-text prompt file writer.

Writes exact prompts as plain text for inspection and reproducibility.
One file per LLM call. Filenames include event_id for traceability.

This module is the ONLY writer of prompt text files.
"""

import os
from pathlib import Path


def write_prompt(run_dir: Path, event_id: int | str, call_index: int,
                 prompt: str) -> str:
    """Write prompt to plain text file. Returns relative path from run_dir.
    
    Thread-safe via O_CREAT|O_EXCL (atomic create, fails on collision).
    """
    prompt_dir = run_dir / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"e{event_id:06d}_call{call_index}.txt"
    path = prompt_dir / filename
    
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, prompt.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    
    return f"prompts/{filename}"
```

### Integration in llm.py

File: `core/pipeline/llm.py`

In `call_model()`, immediately before the API call, after logging setup:

```python
import hashlib
from core.logging_.prompt_store import write_prompt

prompt_hash = hashlib.sha256(full_prompt.encode("utf-8")).hexdigest()
prompt_length = len(full_prompt)
truncated = False
truncation_reason = None

# Write plain-text prompt file
prompt_file = None
if logger is not None:
    prompt_file = write_prompt(
        run_dir=logger._run_dir,
        event_id=logger._event_counter + 1,  # next event ID
        call_index=0,  # incremented for multi-call events
        prompt=full_prompt,
    )
```

### prompt_meta in events

In `_log_call_if_logger()`, add prompt_meta to the call:

```python
prompt_meta = {
    "prompt_hash": prompt_hash,
    "prompt_length": prompt_length,
    "prompt_file": prompt_file,
    "truncated": truncated,
    "truncation_reason": truncation_reason,
}
```

This is passed through `logger.log_call()` and attached to the event via `prompt_assembly`.

### Multi-call safety

For retry conditions where one event triggers multiple LLM calls, `call_index` increments:
- Generation call: `call_index=0`
- Critique call: `call_index=1`
- Classifier hint call: `call_index=2`

The `call_index` is tracked by the caller (retry_v2.py, execution_v2.py) and passed to `call_model()`.

### Concurrency safety

`O_CREAT | O_EXCL` guarantees atomic file creation. If two workers somehow target the same file (impossible in practice since event_ids are per-worker), the second write fails loudly with `FileExistsError`.

### Storage layout

```
{run_dir}/
  prompts/
    e000001_call0.txt    # generation prompt, case 1
    e000002_call0.txt    # classifier prompt, case 1
    e000003_call0.txt    # generation prompt, case 2
    ...
  calls/
    000001.json          # full call record (existing, unchanged)
    ...
  events.jsonl           # references prompts/ via prompt_meta.prompt_file
```

### Config cleanup

`logging.store.raw_prompts` and `logging.store.raw_outputs` are already deleted in V2.1 (dead config, V24/V25). Prompt logging is always on. No config field controls it.

### Prompt file validation

```python
def validate_prompt_file(run_dir: Path, prompt_meta: dict) -> None:
    """Verify prompt file exists and matches declared hash/length."""
    import hashlib
    
    pf = prompt_meta.get("prompt_file")
    if pf is None:
        raise RuntimeError("prompt_meta.prompt_file is None")
    
    path = run_dir / pf
    if not path.exists():
        raise RuntimeError(f"Prompt file missing: {path}")
    
    content = path.read_text(encoding="utf-8")
    if len(content) != prompt_meta["prompt_length"]:
        raise RuntimeError(
            f"Prompt file length mismatch: file={len(content)}, "
            f"declared={prompt_meta['prompt_length']}"
        )
    
    actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if actual_hash != prompt_meta["prompt_hash"]:
        raise RuntimeError(
            f"Prompt file hash mismatch: file={actual_hash[:16]}, "
            f"declared={prompt_meta['prompt_hash'][:16]}"
        )
```

This runs in the smoke gate (Gate 5e) on all smoke events.

---

## FIX 5 — Truncation Tracking (new section)

### Design

Every LLM call record includes:

```python
"truncated": False,
"truncation_reason": None,
```

Currently, no truncation occurs in the codebase — prompts are passed to the API as-is. The fields are set to `False`/`None` at the call site.

### Where truncation is decided

The only place truncation can occur:

1. **Token budget guard** in `runner.py:_run_one()` — skips cases exceeding budget, does NOT truncate
2. **Provider max_tokens** — this is an output limit, not prompt truncation
3. **No other truncation point exists in the codebase**

Since truncation does not currently occur, every call logs `truncated=False, truncation_reason=None`. If a truncation mechanism is added in the future, it must set these fields at the truncation site before calling `call_model()`.

### Implementation

In `call_model()` signature, add parameters:

```python
def call_model(
    prompt: str, model: str, raw: bool = False,
    file_paths: list[str] | None = None,
    logger=None, case_id: str | None = None,
    phase: str = "generation", condition: str | None = None,
    prompt_assembly: dict | None = None,
    parent_event_id: int | str | None = None,
    truncated: bool = False,
    truncation_reason: str | None = None,
) -> ModelCallResult:
```

These values are forwarded into `prompt_meta` and stored with the call record. Callers that truncate must pass `truncated=True, truncation_reason="reason"`.

---

## FIX 6 — Migration Defaults from Canonical YAML (supersedes V2.1 Fix 7)

### Problem

V2.1's `schema_default` parameter in `_require()` duplicates default values in Python. Changing default.yaml without updating `schema_default` creates silent drift.

### Solution

During migration mode, load the canonical `default.yaml` once and use its values as fallbacks:

```python
_STRICT_PARSING = False
_CANONICAL_DEFAULTS: dict | None = None

def _load_canonical_defaults() -> dict:
    """Load default.yaml as a raw dict for migration fallback values.
    
    Called once. Cached. Used ONLY when _STRICT_PARSING is False.
    """
    global _CANONICAL_DEFAULTS
    if _CANONICAL_DEFAULTS is None:
        from core.config.paths import PROJECT_ROOT
        default_path = PROJECT_ROOT / "core" / "config" / "config_storage" / "default.yaml"
        import yaml
        _CANONICAL_DEFAULTS = yaml.safe_load(default_path.read_text())
    return _CANONICAL_DEFAULTS


def _require(d: dict, key: str, section: str):
    """Strict config extraction.
    
    When _STRICT_PARSING is True: crash on missing key.
    When _STRICT_PARSING is False: warn and fall back to canonical default.yaml value.
    """
    if key in d:
        return d[key]
    if _STRICT_PARSING:
        raise ValueError(
            f"CONFIG ERROR: {section}.{key} is REQUIRED but missing from YAML."
        )
    # Migration mode: look up value from canonical default.yaml
    canonical = _load_canonical_defaults()
    parts = section.split(".")
    node = canonical
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise ValueError(
                f"CONFIG MIGRATION ERROR: {section}.{key} missing from YAML "
                f"AND not found in canonical default.yaml at path '{section}'."
            )
    if not isinstance(node, dict) or key not in node:
        raise ValueError(
            f"CONFIG MIGRATION ERROR: {section}.{key} missing from YAML "
            f"AND not found in canonical default.yaml."
        )
    fallback = node[key]
    _log.warning(
        "CONFIG MIGRATION: %s.%s missing, using canonical default: %r. "
        "This becomes fatal when _STRICT_PARSING is enabled.",
        section, key, fallback,
    )
    return fallback
```

### What is eliminated

- No `schema_default=` parameter on `_require()` calls
- No hardcoded default literals in migration mode
- Fallbacks come exclusively from the canonical default.yaml
- If default.yaml is wrong, migration mode is also wrong — single source of truth preserved

### Migration lifecycle

1. Set `_STRICT_PARSING = False`
2. Run YAML migration script
3. Verify zero migration warnings across all 102 configs
4. Set `_STRICT_PARSING = True`
5. Delete `_STRICT_PARSING`, `_CANONICAL_DEFAULTS`, `_load_canonical_defaults()`, and the migration branch from `_require()`

After step 5, `_require()` is:
```python
def _require(d: dict, key: str, section: str):
    if key not in d:
        raise ValueError(f"CONFIG ERROR: {section}.{key} is REQUIRED but missing from YAML.")
    return d[key]
```

---

## FIX 7 — Config→Log Emission Validation (supersedes V2.1 Fix 8 partial)

### Problem

CONFIG_LOG_COVERAGE declares which log paths contain config values, but does not verify they actually appear in emitted events.

### Solution

Add runtime event validation that checks actual emission.

```python
# Required fields in case-end events (execution_eval type)
REQUIRED_EVENT_FIELDS = [
    "config.config_hash",
    "model_spec.name",
    "model_spec.temperature",
    "model_spec.max_tokens",
    "prompt_meta.prompt_hash",
    "prompt_meta.prompt_length",
    "prompt_meta.template_stack",
    "classification.classifier_mode",
    "classification.classifier_template",
    "classification.classifier_schema_variant",
    "reconstruction.recovery_execution_enabled",
    "execution.subprocess_timeout",
]

def _validate_event_log_coverage(ev: dict) -> list[str]:
    """Check that required log fields are present in an emitted event.
    
    Returns list of missing field paths (empty = all present).
    """
    missing = []
    for dotted_path in REQUIRED_EVENT_FIELDS:
        parts = dotted_path.split(".")
        node = ev
        found = True
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                found = False
                break
        if not found:
            missing.append(dotted_path)
    return missing
```

### Where it runs

**Smoke gate (Gate 5f):** After all smoke cases complete, read the smoke events.jsonl and validate every `execution_eval` event:

```python
def _smoke_validate_log_coverage(run_dir):
    """Verify config-sensitive fields are present in all smoke events."""
    smoke_dir = run_dir / "_smoke"
    events_path = smoke_dir / "events.jsonl"
    if not events_path.exists():
        raise RuntimeError("Smoke events file missing")
    
    import json
    with open(events_path) as f:
        for line in f:
            ev = json.loads(line)
            if ev.get("event_type_canonical") != "execution_eval":
                continue
            raw_ev = ev.get("raw_ev") or ev
            missing = _validate_event_log_coverage(raw_ev)
            if missing:
                raise RuntimeError(
                    f"Config-log coverage gap in smoke event: "
                    f"missing fields: {missing}"
                )
```

**Production (sampled):** In `_log_result()` in execution_v2.py, validate every Nth event (N=10):

```python
if logger._event_counter % 10 == 0:
    missing = _validate_event_log_coverage(ev)
    if missing:
        _log.error(
            "CONFIG-LOG COVERAGE GAP: event %d missing fields: %s",
            logger._event_counter, missing
        )
```

### Distinction

- **Declared coverage** (`CONFIG_LOG_COVERAGE` dict): verified by audit script at CI time
- **Actual emitted coverage** (`_validate_event_log_coverage`): verified at runtime on smoke events (mandatory) and sampled real events (warning-only)

---

## Updated Migration Plan (supersedes V2.1 migration plan)

### Step 1: Add infrastructure (no behavioral change)

File: `experiment_config.py`
- Add `CONFIG_SCHEMA` dict
- Add `CONFIG_LOG_COVERAGE` dict
- Add `_allowed_yaml_keys()` derivation from CONFIG_SCHEMA
- Add `_validate_schema_completeness()` bijection check
- Add `_require()` with `_STRICT_PARSING = False` and canonical-YAML fallback
- Add `_require_section()`
- Delete `_KNOWN_EXEC_FIELDS`

File: `execution_v2.py`
- Add pipeline contract field sets (GENERATION_OUTPUT_CONTRACT, etc.)

### Step 2: Update default.yaml

File: `default.yaml`
- Add all missing fields
- Remove misplaced/dead fields
- Verify: `load_config("default.yaml")` succeeds with zero warnings

### Step 3: Migrate YAML configs (dual-mode)

- Step 3a: `_STRICT_PARSING = False`, deploy `_require()` with canonical fallback
- Step 3b: Run `scripts/migrate_yaml_configs.py`
- Step 3c: Verify zero migration warnings for all 102 files
- Step 3d: `_STRICT_PARSING = True`, delete migration codepath

### Step 4: Strict parser + no-default dataclasses

File: `experiment_config.py`
- Remove all dataclass defaults from ExecutionConfig, EvaluationConfig, LoggingConfig
- Replace all `.get()` with `_require()` (strict, canonical fallback removed)
- Add unknown-key detection using `_allowed_yaml_keys()`
- Add new fields (recovery_execution, max_orchestrator_attempts, etc.)

### Step 5: Make prompt validation unconditional

File: `registry.py`
- Contract checks always run
- `validate_prompts` controls only style checks

### Step 6: Rewire consumers

Files: `retry_v2.py`, `orchestrate.py`, `exec_canonical.py`, `execution_v2.py`, `llm.py`
- Delete module constants, replace with config reads
- Remove getattr/hasattr
- Delete dead functions
- Add pipeline contract assertions in _classify_reasoning

### Step 7: Logical file keys (root-based)

File: `runner.py`
- `_compute_logical_key()` with `_LOGICAL_KEY_ROOT = "code_snippets_v2"`
- Update execution_v2.py

### Step 8: Unify test discovery

File: `run_case.py`
- Switch to `spec_from_file_location()`

### Step 9: Add prompt_store.py

File: `core/logging_/prompt_store.py`
- `write_prompt()` function
- Integration in `llm.py:call_model()`
- Add truncated/truncation_reason to call_model signature

### Step 10: Add smoke gate (coverage-complete, per-model)

File: `orchestrate.py`
- `_select_smoke_cases()` (4 categories)
- `_select_smoke_models()` (per-model coverage)
- `_smoke_gate()` with Gates 3, 3.5, 5a-5d, 5e (prompt validation), 5f (log coverage)
- Smoke calls `run_v2()` directly

### Step 11: Add reproducibility logging

Files: `execution_v2.py`, `retry_v2.py`
- config_hash, prompt_hash, template_stack, model_spec, logical_file_keys
- classifier config fields, retry config fields, subprocess_timeout
- REQUIRED_EVENT_FIELDS validation

### Step 12: Update audit script

File: `scripts/audit_config_usage.py`
- CONFIG_LOG_COVERAGE completeness check
- CONFIG_SCHEMA bijection check
- All forbidden-pattern checks from V2/V2.1

### Step 13: Validate

Run all checks from updated validation matrix.

---

## Updated Validation Matrix (addendum to V2.1)

All V2.1 checks retained. New V2.2 checks:

| # | Check | Pass Criterion |
|---|---|---|
| 34 | Schema bijection passes | `_validate_schema_completeness()` runs without error at config load |
| 35 | Schema bijection catches missing field | Add field to ExecutionConfig without CONFIG_SCHEMA entry → RuntimeError naming the field |
| 36 | Schema bijection catches stale entry | Add CONFIG_SCHEMA entry targeting nonexistent field → RuntimeError |
| 37 | Pipeline contracts validated | `_validate_pipeline_contracts()` passes in smoke gate |
| 38 | Pipeline contract catches rename | Rename CLASSIFIER_OUTPUT_CONTRACT field → RuntimeError at smoke or runtime |
| 39 | Multi-model smoke runs | With 2 generation models in config, smoke executes ≥2 baseline E2E (one per model) |
| 40 | Prompt file exists for every call | Every smoke event with prompt_meta has a valid prompt file at declared path |
| 41 | Prompt file hash matches | `validate_prompt_file()` passes for all smoke events |
| 42 | Prompt file length matches | Declared prompt_length matches actual file byte count |
| 43 | truncated field present | Every call record includes `truncated: false` (or true with reason) |
| 44 | truncation_reason field present | Every call record includes `truncation_reason: null` (or string) |
| 45 | Migration defaults from canonical YAML | During migration mode, fallback value for `execution.subprocess_timeout` comes from default.yaml, not Python literal |
| 46 | Migration toggle removed post-migration | `grep "_STRICT_PARSING\|_CANONICAL_DEFAULTS\|_load_canonical_defaults" core/config/experiment_config.py` → zero matches |
| 47 | Config-log emission validation passes | `_smoke_validate_log_coverage()` passes on all smoke events |
| 48 | REQUIRED_EVENT_FIELDS covers all observable config | Every CONFIG_LOG_COVERAGE entry not marked NON_OBSERVABLE has a corresponding REQUIRED_EVENT_FIELDS entry |

---

## Updated Closure Table (addendum to V2.1)

| Fix | Issue | Closed By |
|---|---|---|
| V2.2 Fix 1 | Dataclass field added without CONFIG_SCHEMA entry | `_validate_schema_completeness()` crashes at load (Step 1) |
| V2.2 Fix 2 | Stage boundary field renamed without updating contract | Explicit field-set assertions in `_validate_pipeline_contracts()` and `_classify_reasoning()` (Steps 1, 10) |
| V2.2 Fix 3 | Smoke passes on model A while model B is broken | Per-model smoke execution (Step 10) |
| V2.2 Fix 4 | Exact prompts not stored as inspectable files | `prompt_store.py` writes plain-text `prompts/` files (Step 9) |
| V2.2 Fix 5 | Truncation not tracked | `truncated`/`truncation_reason` in every call record (Step 9) |
| V2.2 Fix 6 | Migration defaults duplicated in Python | Canonical default.yaml loaded as fallback source (Step 3) |
| V2.2 Fix 7 | Config observability declared but not verified | `_validate_event_log_coverage()` on smoke + sampled events (Step 11) |
