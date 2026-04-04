# Config System Redesign v3 — Full Diagnosis, Spec, and Migration Plan

## Changes from v2

- **Added Section 3.7: Config vs Runtime State Separation** — explicit architectural boundary between immutable config and mutable runtime state, preventing future drift
- **Added Section 3.8: Config Invariant Registry** — formal link from config fields to behavioral invariants to execution semantics, connecting to LEG metric and reasoning gap work
- **Expanded Section 6: Test Strategy** — semantic behavior tests are now mandatory (not optional), with monotonicity, boundary, and interaction test categories
- **Added Section 6.6: Cross-Module Invariant Tests** — system behavior consistency across modules, not just "field is used"
- **Added Migration Phase 0.5: Full-Run Access Logging** — instrument existing system to log all config reads before deleting anything
- No audit findings or diagnosis changed — all data carried forward from v2

---

## 1. System Audit

### 1.1 By the Numbers

- **48 config fields** defined in ExperimentConfig dataclass tree
- **24 fields are dead** — parsed from YAML, stored in dataclass, never read by any production code
- **5 fields are silently defaulted** — try/except swallows config errors and returns hardcoded fallbacks
- **7 hardcoded constants** in retry_harness.py and retry_v2.py have matching config fields that are never read
- **8 locations** wrap `get_config()` in try/except with silent fallback
- **0 locations** log a warning when falling back to default

### 1.2 Findings by Failure Mode

#### Silent Failures (errors swallowed)

| Location | Config Field | Fallback | Mechanism |
|---|---|---|---|
| `llm.py:22` `_get_output_format()` | `execution.output_format` | `"v1"` | try/except(RuntimeError, ImportError) |
| `llm.py:32` `_get_model_spec()` | temperature, top_p | 0.0, 1.0 | Nested try/except |
| `llm.py:147` `get_model_config()` | generation[0].* | `{"temperature": 0.0, "top_p": 1.0}` | try/except |
| `llm.py:173` `_openai_call()` | no_temperature_prefixes | `("o1", "o3", "o4", "gpt-5")` | try/except |
| `llm.py:208` `_get_anthropic_max_tokens()` | max_tokens | 4096 | try/except |
| `logging_core.py:652` `_get_model_temperature()` | temperature | None | Nested try/except |
| `logging_core.py:669` `_get_model_max_tokens()` | max_tokens | None | Nested try/except |
| `execution.py:136` `_capture_prompt_assembly()` | experiment.name | None | try/except |

#### Broken Plumbing (config defined but never reaching consumers)

| Config Field | What Happens |
|---|---|
| `experiment.seed` | No seeding code exists. Non-deterministic. |
| `cases.difficulty_filter`, `family_filter`, `exclude`, `mode`, `subset`, `min_files` | load_cases() ignores all filters. |
| `cases.max_cases` | CLI `--max-cases` used instead. Config field ignored. |
| `evaluation.leg_enabled`, `failure_classification_enabled`, `alignment_enabled` | Always run. Cannot be disabled. |
| `logging.level` | Never applied to Python loggers. |
| `retry_defaults.*` (all 13 fields) | Module-level hardcoded constants used instead. |
| `conditions[].contract_enabled`, `critique_enabled`, `critique_model` | Routing by name-match, not config. |
| `evaluator.max_reasoning_chars` | Never used for truncation. |

#### Schema Drift

| Issue | Details |
|---|---|
| `subprocess_timeout` in TWO classes | `EvaluationConfig` (DEAD) and `ExecutionConfig` (WIRED). |
| `evaluation.execution_mode` vs `execution.mode` | Different fields, same apparent meaning. Only `execution.mode` works. |
| Retry config defaults == hardcoded constants | Same values mask the bug. Changing config has no effect. |

#### Symptom Masking

| Symptom | Mask | Root Cause |
|---|---|---|
| Config might not be loaded when llm.py called | 5 try/except in llm.py | Config should be injected, not globally accessed |
| Model spec might not match | Nested fallback chain | Should be validated at load for all needed models |
| Temperature prefix list stale | Hardcoded fallback tuple | Should be in model config |

---

## 2. Root Cause Analysis

**Root Cause 1: Global singleton with defensive callers.** `get_config()` returns a global. Every consumer wraps access in try/except because the singleton might be None. Creates N independent fallback paths instead of one validated load.

**Root Cause 2: Aspirational schema.** Fields added for features that were never implemented. Schema grew ahead of code.

**Root Cause 3: Name-matching condition routing.** `_run_one_inner()` routes by string match, making ConditionConfig flags dead.

**Root Cause 4: Retry harnesses predate config.** Module-level constants were never rewired to read from config. Same default values make the bug invisible.

**Root Cause 5: No separation between config and runtime state.** The system has no architectural boundary between immutable experiment parameters (config) and mutable execution state (counters, caches, intermediate results). This blurs the line between "what was configured" and "what happened at runtime," making it impossible to reason about config-to-behavior correspondence.

---

## 3. Target Architecture — Canonical Config System Spec

### 3.1 Core Invariant

> A config field cannot exist in the system unless it is:
> 1. declared in the canonical schema
> 2. loaded through the canonical loader
> 3. propagated through the canonical runtime context
> 4. either consumed during execution or explicitly listed in UNUSED_FIELDS_ALLOWLIST
> 5. covered by a propagation test
> 6. linked to at least one behavioral invariant in the invariant registry
> 7. separated from runtime state by a frozen boundary

### 3.2 Five Layers

**Layer 1 — Schema** (`config/schema.py`)
Single typed definition of all config fields using Pydantic v2 with `extra="forbid"` and `frozen=True`. No duplicate defaults anywhere. No fallback defaults outside schema.

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)
```

Unknown YAML fields -> hard failure at load. Missing required fields -> hard failure. Invalid types/enums -> hard failure.

**Layer 2 — Loader** (`config/loader.py`)
Single entrypoint: `load_config(*paths) -> AppConfig`. No other code instantiates AppConfig. All validation crashes immediately.

**Layer 3 — Propagation** (`config/runtime.py`)
Config wrapped in `RuntimeContext(config, access_tracker, runtime_state)`. Every execution path receives RuntimeContext explicitly. No module-level config reads. No `get_config()` singleton. Runtime state is explicitly separated from config (see Section 3.7).

```python
@dataclass
class RuntimeContext:
    config: AppConfig          # frozen — immutable experiment parameters
    access: AccessTracker      # mutable — tracks which config paths were read
    state: RuntimeState        # mutable — execution counters, caches, timings
```

**Layer 4 — Consumption + Tracking** (`config/access.py`)
Consumers read via `cfg(ctx, "execution.mode")` which records access. Every consumer declares `CONSUMES_CONFIG`. Tests verify declared == accessed == wired.

**Layer 5 — Invariant Registry** (`config/invariants.py`)
Every config field is linked to one or more behavioral invariants that describe what the field controls. The registry connects config -> invariants -> execution semantics. See Section 3.8.

### 3.3 Twelve Invariants

| # | Invariant | Enforcement |
|---|-----------|-------------|
| 1 | All config fields declared in exactly one schema file | Pydantic `extra="forbid"` + single schema.py |
| 2 | No hidden defaults outside canonical schema | Semgrep ban on `dict.get(k, default)`, `try/except: return default` |
| 3 | No code reads config unless it receives RuntimeContext | CI grep: zero `get_config()` outside bootstrap |
| 4 | Config immutable after load | Pydantic `frozen=True` |
| 5 | Every field consumed or in UNUSED_FIELDS_ALLOWLIST | `test_all_fields_consumed_or_exempt` |
| 6 | Every consumer declares fields via CONSUMES_CONFIG | `test_declared_usage_matches_runtime` |
| 7 | Unknown YAML fields -> hard failure | Pydantic `extra="forbid"` |
| 8 | Missing required fields -> hard failure | Pydantic required fields |
| 9 | One canonical name per config path (no aliases) | Schema review |
| 10 | Config says X -> behavior reflects X | Per-field semantic behavior tests |
| 11 | Config and runtime state occupy separate namespaces | Structural enforcement in RuntimeContext |
| 12 | Every config field linked to behavioral invariant(s) | `test_all_fields_have_invariants` |

### 3.4 Access Tracking

```python
@dataclass
class AccessTracker:
    accessed_paths: set[str] = field(default_factory=set)
    def record(self, path: str) -> None:
        self.accessed_paths.add(path)

def cfg(ctx: RuntimeContext, path: str):
    current = ctx.config
    for segment in path.split("."):
        current = getattr(current, segment)
    ctx.access.record(path)
    return current

def cfg_checked(ctx: RuntimeContext, path: str, allowed: set[str]):
    if path not in allowed:
        raise AssertionError(f"Undeclared config access: {path}")
    return cfg(ctx, path)
```

### 3.5 Consumer Declaration Pattern

```python
CONSUMES_CONFIG = {"execution.mode", "execution.subprocess_timeout"}

def execute_case(case, ctx):
    mode = cfg_checked(ctx, "execution.mode", CONSUMES_CONFIG)
    timeout = cfg_checked(ctx, "execution.subprocess_timeout", CONSUMES_CONFIG)
```

### 3.6 Bootstrap Pattern

```python
def main():
    config = load_config(Path(args.config))
    ctx = RuntimeContext(
        config=config,
        access=AccessTracker(),
        state=RuntimeState(),
    )
    run_ablation_mode(args, ctx)
```

One load. One context. One propagation path. No globals.

### 3.7 Config vs Runtime State Separation (NEW in v3)

#### The Problem

The current codebase mixes immutable experiment parameters with mutable execution state in the same namespace. Module-level variables serve double duty: some are config-derived constants, others are accumulated runtime state. This causes:

1. **Ambiguity at read sites:** Is this value from config or from a prior execution step?
2. **Accidental mutation:** Config-like values get modified during execution (e.g., retry counters stored alongside retry thresholds).
3. **Architectural drift:** New developers don't know where to put a new field — config or runtime? So they pick whichever is convenient, blurring the boundary further.
4. **Reproducibility bugs:** If config and state are entangled, replaying an experiment requires reconstructing both, but only config is serialized to YAML.

#### The Rule

**Config** is immutable, set before execution, serialized to YAML, and sufficient to reproduce the experiment. **Runtime state** is mutable, accumulated during execution, and ephemeral.

| Property | Config | Runtime State |
|---|---|---|
| Mutability | Frozen after load | Mutable during execution |
| Lifetime | Entire experiment | Per-case or per-run |
| Serialization | YAML (input) | Log events (output) |
| Source of truth | YAML file | Execution pipeline |
| Examples | temperature, max_retries, subprocess_timeout | attempt_count, elapsed_time, cached_results |

#### The Boundary

```python
@dataclass(frozen=True)
class AppConfig:
    """Immutable experiment parameters. Set once. Never modified."""
    execution: ExecutionConfig
    models: ModelsConfig
    retry: RetryConfig
    # ...

@dataclass
class RuntimeState:
    """Mutable execution state. Accumulated during run. Not config."""
    cases_completed: int = 0
    total_api_calls: int = 0
    access_log: list[str] = field(default_factory=list)
    # Per-case state is created fresh, not stored here
```

The `RuntimeContext` holds both but keeps them structurally separated:
- `ctx.config` is frozen (Pydantic `frozen=True` or `@dataclass(frozen=True)`)
- `ctx.state` is mutable (plain dataclass)
- No field exists in both
- Tests verify: `set(config_fields) & set(state_fields) == empty`

#### What This Prevents

1. **Retry threshold drift:** `retry.similarity_threshold` stays in config (frozen). `current_attempt_count` stays in state (mutable). They can never be confused.
2. **Temperature mutation:** `models.generation.temperature` stays in config. The actual temperature sent to the API is derived from config at call time, never stored in a mutable location.
3. **Counter accumulation:** Case counters, timing accumulators, and cache hit rates are runtime state, not config. They don't appear in `AppConfig`.

### 3.8 Config Invariant Registry (NEW in v3)

#### Purpose

The invariant registry is a formal mapping from config fields to the behavioral properties they control. It answers the question: **"If I change field X, what behavior should change, and how?"**

This connects directly to:
- **LEG metric:** The reasoning gap between "config says X" and "system does X" is exactly the LEG pattern applied to the config layer.
- **Reasoning gap work:** If a config field's behavioral invariant cannot be stated, the field has no operational meaning and should be deleted.
- **Execution semantics:** The registry links config -> invariants -> execution, making it possible to verify that the system obeys its own configuration.

#### Structure

```python
@dataclass(frozen=True)
class ConfigInvariant:
    field_path: str                    # e.g., "retry.similarity_threshold"
    description: str                   # Human-readable: "Controls minimum cosine similarity for duplicate detection"
    behavioral_property: str           # What behavior changes: "retry deduplication threshold"
    monotonicity: str | None           # "increasing" | "decreasing" | None
                                       # e.g., higher threshold -> fewer retries accepted as duplicates
    boundary_values: list[dict]        # [{value: 0.0, behavior: "accept all"}, {value: 1.0, behavior: "accept none"}]
    interaction_fields: list[str]      # Other fields this interacts with: ["retry.max_attempts"]
    modules_affected: list[str]        # Which modules' behavior changes: ["retry_harness", "retry_v2"]
    test_name: str                     # Corresponding behavior test: "test_similarity_threshold_changes_dedup"

CONFIG_INVARIANTS: dict[str, list[ConfigInvariant]] = {
    "retry.similarity_threshold": [
        ConfigInvariant(
            field_path="retry.similarity_threshold",
            description="Minimum cosine similarity to classify a retry response as duplicate",
            behavioral_property="retry deduplication sensitivity",
            monotonicity="increasing",
            boundary_values=[
                {"value": 0.0, "behavior": "all responses accepted as non-duplicate"},
                {"value": 1.0, "behavior": "only exact matches classified as duplicate"},
                {"value": 0.95, "behavior": "default: near-exact match required"},
            ],
            interaction_fields=["retry.max_attempts"],
            modules_affected=["retry_harness", "retry_v2"],
            test_name="test_similarity_threshold_monotonic",
        ),
    ],
    "models.generation.temperature": [
        ConfigInvariant(
            field_path="models.generation.temperature",
            description="Sampling temperature for generation model",
            behavioral_property="response randomness",
            monotonicity="increasing",
            boundary_values=[
                {"value": 0.0, "behavior": "deterministic (greedy) generation"},
                {"value": 2.0, "behavior": "maximum randomness"},
            ],
            interaction_fields=["models.generation.top_p"],
            modules_affected=["llm"],
            test_name="test_temperature_propagates_to_api_call",
        ),
    ],
    "execution.subprocess_timeout": [
        ConfigInvariant(
            field_path="execution.subprocess_timeout",
            description="Maximum seconds for subprocess execution of model code",
            behavioral_property="execution time limit",
            monotonicity="increasing",
            boundary_values=[
                {"value": 0, "behavior": "immediate timeout"},
                {"value": 1, "behavior": "very short timeout, most cases fail"},
                {"value": 300, "behavior": "generous timeout, most cases complete"},
            ],
            interaction_fields=[],
            modules_affected=["exec_eval", "exec_canonical"],
            test_name="test_subprocess_timeout_kills_slow_code",
        ),
    ],
    # ... one entry per live config field
}
```

#### Registry Invariants

1. Every live config field MUST have at least one entry in `CONFIG_INVARIANTS`
2. Every `ConfigInvariant.test_name` MUST correspond to an actual test function
3. If `monotonicity` is set, a monotonicity test MUST exist (see Section 6.5)
4. If `interaction_fields` is non-empty, an interaction test MUST exist (see Section 6.5)
5. If `boundary_values` lists extreme values, boundary tests MUST exist (see Section 6.5)

#### Enforcement

```python
def test_all_fields_have_invariants():
    """Every live config field must be registered in CONFIG_INVARIANTS."""
    all_fields = flatten_schema_paths(AppConfig)
    registered = set(CONFIG_INVARIANTS.keys())
    exempt = UNUSED_FIELDS_ALLOWLIST
    unregistered = all_fields - registered - exempt
    assert unregistered == set(), f"Config fields without invariants: {unregistered}"

def test_all_invariant_tests_exist():
    """Every ConfigInvariant.test_name must correspond to a real test."""
    for field, invariants in CONFIG_INVARIANTS.items():
        for inv in invariants:
            assert hasattr(test_module, inv.test_name), \
                f"Missing test {inv.test_name} for invariant on {field}"
```

---

## 4. What Changes

**DELETE from schema (24 fields):**
- `experiment.seed`, `experiment.description`, `experiment.tags`
- `evaluation.execution_mode`, `evaluation.leg_enabled`, `evaluation.failure_classification_enabled`, `evaluation.alignment_enabled`, `evaluation.subprocess_timeout`
- `evaluator.max_reasoning_chars`
- `execution.import_summary`, `execution.file_ordering`
- `cases.mode`, `cases.subset`, `cases.difficulty_filter`, `cases.family_filter`, `cases.exclude`, `cases.min_files`
- `conditions[].contract_enabled`, `conditions[].contract_injection_point`, `conditions[].critique_model`
- `logging.level`, `logging.store_raw_prompts`, `logging.store_raw_outputs`
- `logging.redis_enabled`, `logging.redis_url`, `logging.redis_stream_maxlen`
- `retry_defaults.enabled`

**WIRE to consumers (replace hardcoded constants):**
- Retry config -> retry_harness.py and retry_v2.py
- `cases.max_cases` -> runner.py

**REMOVE silent fallbacks:**
- 5 try/except blocks in llm.py
- 2 try/except blocks in logging_core.py
- 1 try/except in execution.py

**ADD (new in v3):**
- `config/invariants.py` — invariant registry linking fields to behavioral properties
- `RuntimeState` dataclass — explicit mutable state, separate from config
- Semantic behavior tests for every live field (monotonicity, boundary, interaction)
- Cross-module invariant tests

---

## 5. Migration Plan

### Phase 0: Freeze
No new config fields until canonical schema exists. Verify dead-field list with automated grep.

### Phase 0.5: Full-Run Access Logging (NEW in v3)

**Goal:** Before deleting ANY field, instrument the existing system to log every config field access across a complete experiment run. This creates an empirical ground truth for which fields are actually read, preventing accidental regressions from the grep-based audit.

**Why this matters:** The v2 dead-field list was constructed by grepping source code. Grep misses:
- Dynamic access (`getattr(config, field_name)`)
- Config passed through dicts or kwargs
- Fields read by third-party code or plugins
- Fields read only under specific condition/model combinations not covered by the audit's test runs

**Action:**
1. Add a lightweight access logger to `get_config()` that records every attribute access:
```python
class LoggingConfig:
    """Wrapper that logs all attribute access. Temporary instrumentation."""
    def __init__(self, wrapped):
        self._wrapped = wrapped
        self._accessed = set()
    def __getattr__(self, name):
        self._accessed.add(name)
        return getattr(self._wrapped, name)
```
2. Run a FULL experiment (all cases, all conditions, all models) with logging enabled
3. Export the `_accessed` set
4. Compare with grep-based dead-field list
5. Any field that grep says is dead but logging says was accessed -> investigate before deleting
6. Produce a signed-off dead-field list with both grep and runtime evidence

**Files:** `experiment_config.py` (temporary instrumentation, removed after Phase 1)
**Validation:** Dead-field list from grep matches dead-field list from runtime logging. Any discrepancy investigated and resolved.
**Risk:** None. Temporary instrumentation. Removed after validation.

### Phase 1: Schema + Loader
Build Pydantic schema with only live fields. Delete 24 dead fields. `extra="forbid"`, `frozen=True`. YAML configs that set deleted fields emit WARNING.
**Files:** `config/schema.py` (new), `config/loader.py` (new), `experiment_config.py` (modified)

### Phase 1.5: Config vs Runtime State Separation (NEW in v3)

**Goal:** Establish the `RuntimeState` dataclass and split RuntimeContext into frozen config + mutable state.

**Action:**
1. Create `config/runtime.py` with `RuntimeContext` holding both `AppConfig` (frozen) and `RuntimeState` (mutable)
2. Identify all module-level mutable variables that are currently entangled with config (e.g., retry counters stored alongside retry thresholds)
3. Move mutable state into `RuntimeState`
4. Add structural test: `test_config_state_disjoint` verifies no field name appears in both `AppConfig` and `RuntimeState`

**Files:** `config/runtime.py` (new)
**Validation:** `test_config_state_disjoint` passes. No field in both namespaces.

### Phase 2: Compatibility Shim
One `config/migration.py` adapter from new AppConfig to legacy ExperimentConfig interface. Allows gradual migration.
**Files:** `config/migration.py` (new)

### Phase 3: Propagation
Change all entrypoints to accept RuntimeContext. Ban `get_config()` in runtime code.
**Files:** `runner.py`, `execution.py`, `execution_v2.py`, `evaluator.py`, `retry_harness.py`, `retry_v2.py`

### Phase 4: Consumer Migration
Per-module: add `CONSUMES_CONFIG`, use `cfg_checked`, add behavior tests. Wire retry config (replace 7 hardcoded constants). Eliminate llm.py try/except (pass model params explicitly). Eliminate logging_core.py try/except.
**Files:** `llm.py`, `logging_core.py`, `retry_harness.py`, `retry_v2.py`, `execution.py`, `execution_v2.py`, `evaluator.py`

### Phase 4.5: Invariant Registry Population (NEW in v3)

**Goal:** Build the `CONFIG_INVARIANTS` registry for every live config field.

**Action:**
1. For each live field in the Pydantic schema, define at least one `ConfigInvariant`
2. Specify `monotonicity`, `boundary_values`, and `interaction_fields` where applicable
3. Name the corresponding behavior test
4. Enable `test_all_fields_have_invariants`

**Files:** `config/invariants.py` (new)
**Validation:** `test_all_fields_have_invariants` passes. Every field registered.

### Phase 5: Coverage Gate
Enable `test_all_fields_consumed_or_exempt` with temporary UNUSED_FIELDS_ALLOWLIST.

### Phase 5.5: Semantic Behavior Tests (NEW in v3)

**Goal:** Write the mandatory semantic behavior tests derived from the invariant registry.

**Action:** For each `ConfigInvariant`, write the test named in `test_name`. See Section 6.5 for test categories and requirements.

**Files:** `tests/test_config_behavior.py` (new)
**Validation:** All `test_name` references in registry resolve to passing tests.

### Phase 6: Burn Down
Wire or delete every allowlisted field. No permanent exemptions.

### Phase 7: Remove Shim
Delete `config/migration.py`. CI fails on legacy config imports.

---

## 6. Test Strategy

### 6.1 Schema Tests
- `test_unknown_fields_fail`: ghost YAML field -> ValidationError
- `test_missing_required_field_fails`: missing evaluator.name -> ValidationError
- `test_config_round_trip`: load -> dump -> reload -> identical

### 6.2 Propagation Tests
- `test_retry_reads_config_not_constants`: set threshold=0.5, verify used
- `test_temperature_propagates_to_api`: set temp=1.5, mock API, verify kwargs
- `test_max_cases_from_config`: set max_cases=2, verify 2 cases loaded

### 6.3 Failure Injection
- `test_no_silent_fallback_in_llm`: call_model without params -> crash (no default)
- `test_config_immutable`: assign to frozen field -> FrozenInstanceError

### 6.4 Invariant Enforcement
- `test_no_get_config_in_production`: grep confirms zero singleton reads
- `test_no_try_except_around_config`: AST scan confirms zero fallback patterns
- `test_runtime_context_required`: inspect entrypoint signatures for ctx param
- `test_declared_usage_matches_runtime`: accessed_paths <= CONSUMES_CONFIG
- `test_all_fields_consumed_or_exempt`: (all_fields - accessed - allowlist) == empty
- `test_all_fields_have_invariants`: every field registered in CONFIG_INVARIANTS (NEW in v3)
- `test_config_state_disjoint`: no field name in both AppConfig and RuntimeState (NEW in v3)

### 6.5 Semantic Behavior Tests (NEW in v3 — MANDATORY)

The v2 plan had a single line: "For every meaningful field, assert non-default value changes behavior." That is necessary but insufficient. A field can "change behavior" in a trivial way that doesn't verify the field does what it claims.

**Semantic behavior tests** verify that the field controls the specific behavioral property it claims to control, across its full operational range.

#### Three categories — at least one per field, all three for critical fields:

**A. Monotonicity Tests**

For fields with `monotonicity` in their `ConfigInvariant`:

```python
def test_similarity_threshold_monotonic():
    """Higher threshold -> fewer responses classified as duplicate."""
    ctx_low = make_ctx(retry={"similarity_threshold": 0.5})
    ctx_high = make_ctx(retry={"similarity_threshold": 0.99})

    dupes_low = count_duplicates(run_retry_case(ctx_low, fixed_responses))
    dupes_high = count_duplicates(run_retry_case(ctx_high, fixed_responses))

    # Higher threshold is stricter -> fewer duplicates detected -> more retries
    assert dupes_low >= dupes_high, (
        f"Monotonicity violated: threshold 0.5 found {dupes_low} dupes, "
        f"threshold 0.99 found {dupes_high} dupes"
    )
```

Pattern: `field_value_1 < field_value_2 -> metric_1 {<=, >=} metric_2`

Required for: `retry.similarity_threshold`, `retry.max_attempts`, `retry.max_total_seconds`, `execution.subprocess_timeout`, `models.generation.temperature`

**B. Boundary Tests**

For fields with `boundary_values` in their `ConfigInvariant`:

```python
def test_subprocess_timeout_zero_fails_all():
    """Timeout of 0 should cause all subprocess executions to fail."""
    ctx = make_ctx(execution={"subprocess_timeout": 0})
    result = exec_evaluate(trivial_case, trivial_code, ctx)
    assert result["error_type"] == "timeout"

def test_subprocess_timeout_generous_passes():
    """Timeout of 300 should allow trivial cases to complete."""
    ctx = make_ctx(execution={"subprocess_timeout": 300})
    result = exec_evaluate(trivial_case, known_good_code, ctx)
    assert result["pass"] is True
```

Pattern: at each boundary value, verify the documented behavior holds.

Required for: every field with `boundary_values` in its `ConfigInvariant`.

**C. Interaction Tests**

For fields with `interaction_fields` in their `ConfigInvariant`:

```python
def test_temperature_top_p_interaction():
    """When temperature=0, top_p should be irrelevant (greedy decoding)."""
    ctx_a = make_ctx(models={"generation": {"temperature": 0.0, "top_p": 0.5}})
    ctx_b = make_ctx(models={"generation": {"temperature": 0.0, "top_p": 1.0}})

    # Mock API call, extract kwargs
    kwargs_a = capture_api_kwargs(ctx_a)
    kwargs_b = capture_api_kwargs(ctx_b)

    # At temperature=0, both should produce identical behavior
    # (implementation detail: some APIs ignore top_p at temp=0)
    # The test verifies the interaction is understood and handled
    assert kwargs_a["temperature"] == 0.0
    assert kwargs_b["temperature"] == 0.0

def test_max_attempts_similarity_threshold_interaction():
    """With max_attempts=1, similarity_threshold is irrelevant (no retry to compare)."""
    ctx = make_ctx(retry={"max_attempts": 1, "similarity_threshold": 0.5})
    result = run_retry_case(ctx, responses_that_would_be_duplicate)
    # Only one attempt made, so duplicate detection never triggers
    assert result["attempts"] == 1
```

Pattern: when field A is at an extreme, field B's effect should be documented and verified.

Required for: every field pair listed in `interaction_fields`.

#### Summary: Minimum Test Coverage Per Field

| Field Type | Minimum Tests |
|---|---|
| Numeric with monotonicity | 1 monotonicity + 2 boundary |
| Numeric without monotonicity | 2 boundary |
| Boolean/enum | 1 per value (behavior test) |
| String (e.g., model name) | 1 propagation test |
| Field with interactions | 1 interaction test per interaction |

### 6.6 Cross-Module Invariant Tests (NEW in v3)

The v2 plan verified that individual fields propagate to individual consumers. But config fields don't operate in isolation — they affect system behavior across module boundaries. Cross-module invariant tests verify that the SYSTEM behaves consistently, not just that individual modules read the right values.

#### What "consistent across modules" means

If `models.generation.temperature` is set to 1.5:
- `llm.py` must send `temperature=1.5` in the API call (propagation)
- `logging_core.py` must record `temperature=1.5` in the log event (observability)
- `execution_v2.py` must pass `temperature=1.5` to the LLM call (wiring)
- The API response's randomness must be consistent with temperature=1.5 (behavioral)

If ANY module disagrees about the value, the system is inconsistent.

#### Test Pattern

```python
def test_temperature_consistent_across_modules():
    """Temperature from config must reach API, logs, and metrics identically."""
    ctx = make_ctx(models={"generation": {"temperature": 1.5}})

    # Run a case through the full pipeline
    with capture_all_module_reads(ctx) as reads:
        run_v2(case, model, condition, ctx)

    # Verify all modules saw the same temperature
    api_temp = reads["llm"]["temperature"]
    log_temp = reads["logging_core"]["temperature"]
    exec_temp = reads["execution_v2"]["temperature"]

    assert api_temp == log_temp == exec_temp == 1.5, (
        f"Temperature inconsistent: api={api_temp}, log={log_temp}, exec={exec_temp}"
    )
```

#### Required Cross-Module Tests

| Config Field | Modules That Must Agree | Test Name |
|---|---|---|
| `models.generation.temperature` | llm, logging_core, execution_v2 | `test_temperature_consistent_across_modules` |
| `models.generation.name` | llm, logging_core, execution_v2 | `test_model_name_consistent_across_modules` |
| `retry.max_attempts` | retry_harness, retry_v2, logging_core | `test_max_attempts_consistent_across_modules` |
| `retry.similarity_threshold` | retry_harness, retry_v2 | `test_similarity_threshold_consistent_across_modules` |
| `execution.subprocess_timeout` | exec_eval, exec_canonical | `test_timeout_consistent_across_execution_modes` |
| `execution.mode` | execution, execution_v2, runner | `test_execution_mode_consistent_across_modules` |

#### Consistency Invariant

For every config field F that is consumed by modules M1, M2, ..., Mn:

```
cfg_value = cfg(ctx, F)
for module in [M1, M2, ..., Mn]:
    assert module.observed_value_of(F) == cfg_value
```

This is stronger than individual propagation tests because it catches:
- Module A reads from config, module B reads from a stale cache
- Module A reads from config, module B reads from a module-level constant
- Module A reads from config, module B receives the value through a different path that introduces a transformation

---

## 7. Adding a New Config Field (Mandatory Workflow)

1. Add field to `config/schema.py`
2. Add to config fixture YAML
3. Register in `CONFIG_INVARIANTS` with monotonicity, boundaries, interactions
4. Add to consumer's `CONSUMES_CONFIG`
5. Read via `cfg_checked(ctx, path, CONSUMES_CONFIG)`
6. Write `test_<field>_changes_behavior` (monotonicity/boundary/interaction as applicable)
7. Write cross-module consistency test if field is read by >1 module
8. Coverage test passes

Skipping any step -> CI fails.

---

## 8. Definition of Done

The config system is fixed when ALL are true:

1. Every field in canonical Pydantic schema
2. Every entrypoint accepts RuntimeContext
3. No business logic imports config globally
4. No fallback defaults outside loader
5. Every consumer declares usage via CONSUMES_CONFIG
6. Every read tracked via cfg/cfg_checked
7. Every field consumed or explicitly exempted
8. Every meaningful field has semantic behavior test(s) — monotonicity, boundary, AND interaction where applicable
9. Duplicate/confused fields deleted
10. UNUSED_FIELDS_ALLOWLIST is empty
11. Every field registered in CONFIG_INVARIANTS with behavioral properties
12. Cross-module consistency tests pass for all multi-consumer fields
13. Config and runtime state structurally separated (disjoint namespaces, frozen vs mutable)
14. Full-run access logging validated dead-field list before any deletions

---

## Appendix A: Files to Create

| File | Purpose | Phase |
|---|---|---|
| `config/schema.py` | Pydantic schema for all live config fields | 1 |
| `config/loader.py` | Single load entrypoint | 1 |
| `config/runtime.py` | RuntimeContext with config + state separation | 1.5 |
| `config/access.py` | cfg(), cfg_checked(), AccessTracker | 1 |
| `config/migration.py` | Compatibility shim (temporary) | 2 |
| `config/invariants.py` | CONFIG_INVARIANTS registry | 4.5 |
| `tests/test_config_behavior.py` | Semantic behavior tests | 5.5 |
| `tests/test_config_crossmodule.py` | Cross-module consistency tests | 5.5 |

## Appendix B: Files to Modify

| File | Modification | Phase |
|---|---|---|
| `experiment_config.py` | Add temporary access logging; then replace with Pydantic schema | 0.5, 1 |
| `runner.py` | Accept RuntimeContext, wire max_cases | 3 |
| `execution.py` | Accept RuntimeContext, pass model params | 3, 4 |
| `execution_v2.py` | Accept RuntimeContext | 3, 4 |
| `llm.py` | Remove try/except, accept explicit params | 4 |
| `logging_core.py` | Remove try/except, accept params at construction | 4 |
| `retry_harness.py` | Delete module constants, read from config | 4 |
| `retry_v2.py` | Delete module constants, read from config | 4 |
| `evaluator.py` | Accept RuntimeContext | 3, 4 |

## Appendix C: v2 -> v3 Delta Summary

| Addition | Section | Rationale |
|---|---|---|
| Config vs Runtime State Separation | 3.7, Phase 1.5 | Prevents architectural drift between immutable parameters and mutable execution state |
| Config Invariant Registry | 3.8, Phase 4.5 | Formal link from config -> behavioral invariants -> execution; connects to LEG metric |
| Semantic Behavior Tests (mandatory) | 6.5, Phase 5.5 | Monotonicity, boundary, and interaction tests replace weak "field changes behavior" |
| Cross-Module Invariant Tests | 6.6, Phase 5.5 | System-level consistency, not just per-field propagation |
| Full-Run Access Logging | Phase 0.5 | Empirical validation of dead-field list before deletion, prevents accidental regressions |
| Root Cause 5 | Section 2 | Config/state entanglement identified as root cause of drift |
| Invariants 11, 12 | Section 3.3 | Config-state disjointness and invariant registry coverage |
