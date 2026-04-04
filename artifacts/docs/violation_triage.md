# Violation Triage Plan — System Architecture Aligned

**Date:** 2026-03-27
**Pipeline:** Prompt → LLM → Parse → Reconstruct → Execute → Evaluate → Classify → Log
**Total actionable violations:** 335 (Ruff) + 203 (Pyright) + 54 ERROR semgrep + 20 Vulture = **612**
**Noise (excluded):** 9,570 semgrep INFO/WARNING from overly broad heuristic rules

---

## Summary by Pipeline Layer

| Layer | Violations | P0 | P1 | P2 | P3 |
|-------|-----------|----|----|----|----|
| Runner/Orchestration | 67 | 1 | 2 | 3 | 61 |
| Prompt Construction | 8 | 0 | 0 | 1 | 7 |
| LLM Call Layer | 12 | 1 | 1 | 1 | 9 |
| Parsing Layer | 22 | 1 | 3 | 2 | 16 |
| Reconstruction Layer | 6 | 0 | 0 | 1 | 5 |
| Execution Layer | 95 | 1 | 2 | 5 | 87 |
| Evaluation Layer | 41 | 0 | 1 | 3 | 37 |
| Classification Layer | 17 | 0 | 1 | 1 | 15 |
| Logging/Observability | 45 | 0 | 3 | 2 | 40 |
| Config/Case Management | 39 | 0 | 0 | 2 | 37 |
| **Cross-cutting** | **260** | 0 | 0 | 92 | 168 |
| **TOTAL** | **612** | **4** | **13** | **113** | **482** |

---

## Root Cause Clusters

### RC1: Silent Exception Swallowing
**Severity: P0 — EXPERIMENT INVALIDATION**
**Count:** 11 findings
**Layers:** Parsing (3), LLM Call (1), Execution (2), Contract (2), Logging (2), Retry (1)
**Tool:** Semgrep `no-silent-except-pass`, `no-swallowed-exception`

**Invariant broken:** "No silent failures anywhere." This is the invariant that, when violated, caused the $20 wasted ablation. Silent exceptions in the parsing layer (`parse.py:94,122,202`) mean malformed model responses are silently dropped instead of producing errors. In `llm.py:77`, a failed API call is silently swallowed.

**Affected files and lines:**
- `parse.py:94` — JSON decode failure silenced (Parsing Layer)
- `parse.py:122` — Lenient parse failure silenced (Parsing Layer)
- `parse.py:202` — Code dict parse failure silenced (Parsing Layer)
- `llm.py:77` — LLM call failure silenced (LLM Call Layer)
- `exec_eval.py:198` — Module attribute check silenced (Execution Layer)
- `exec_eval.py:407` — Mutation test import silenced (Execution Layer)
- `contract.py:137,147` — Contract parse failures silenced (Execution Layer)
- `redis_live_dashboard.py:84` — Dashboard update silenced (Logging)
- `retry_harness.py:150` — Retry step failure silenced (Orchestration)
- `execution.py:208` — Legacy emit failure silenced (Logging)

**Root cause:** Defensive coding pattern applied inconsistently. Some are correct (Redis fire-and-forget). Others are dangerous (parse failures that should produce `reasoning_correct=None`).

**Systemic:** YES — the pattern repeats across 6 pipeline layers.

**Why this threatens validity:** A silent parse failure in `parse.py:94` means a valid model response could be silently dropped, producing `code=""`, which gets scored as `pass=False`. The model's actual performance is never measured. This is exactly what happened with the reconstruction wiring bug.

---

### RC2: Wildcard Import Breaking Module Boundaries
**Severity: P0 — EXPERIMENT INVALIDATION**
**Count:** 1 finding
**Layer:** Execution Layer
**Tool:** Semgrep `no-wildcard-import`, Ruff F403

**Invariant broken:** "No duplicate execution paths." `execution.py:12` has `from evaluator import *`, which imports every public name from evaluator into execution's namespace. This means execution.py has direct access to `exec_evaluate`, `llm_classify`, `compute_alignment`, `_CLASSIFY_PROMPT`, `_REASONING_SIGNALS`, and every other evaluator symbol — bypassing the architectural boundary that should exist between the execution orchestrator and the evaluation layer.

**Why this threatens validity:** If someone calls `exec_evaluate` through execution.py's namespace vs evaluator's namespace, they might get different behavior if evaluator is monkey-patched or reloaded. More critically, this wildcard import masks the real dependency graph — you can't tell what execution.py actually uses from evaluator.

**Systemic:** LOCAL — single line, single file.

---

### RC3: Ghost Dependencies (Dead Imports on Critical Path)
**Severity: P0 — EXPERIMENT INVALIDATION**
**Count:** 20 findings
**Layer:** Execution (13), Runner (3), Exec_eval (3), Experiment_config (2)
**Tool:** Vulture, Ruff F401, Pyright reportUnusedImport

**Invariant broken:** "Pipeline linearity — no duplicate execution paths." Dead imports in `execution.py` include 8 nudge operators (`apply_diagnostic`, `apply_guardrail`, etc.) and 2 legacy event functions (`EVENTS_PATH`, `_legacy_emit`). These are remnants of the old prompt building system that was replaced by `assembly_engine.py`/`prompt_registry.py`.

**Affected files:**
- `execution.py:17` — 8 unused nudge imports (old prompt system)
- `execution.py:265,269` — `EVENTS_PATH`, `_legacy_emit` (old metrics)
- `execution.py:953` — `build_leg_reduction_prompt` unused
- `runner.py:17` — `get_current_log_path`, `get_log_write_stats` unused
- `runner.py:565` — `get_call_count` unused
- `exec_eval.py:14,19` — `Any`, `_STDLIB_MODULES`, `extract_all_code_blocks` unused
- `experiment_config.py:18,25` — `copy`, `Any` unused

**Why this threatens validity:** Dead imports cause `execution.py` to silently load the old nudge system on every import. If those old modules have side effects or shared state, they contaminate the pipeline. More practically, they make the dependency graph unreadable — you can't determine the real execution path.

**Systemic:** LOCAL — deletable in one pass.

---

### RC4: Unsafe Optional Access in Test Harness
**Severity: P0 — EXPERIMENT INVALIDATION**
**Count:** 17 findings
**Layer:** Execution Layer (exec_eval.py)
**Tool:** Pyright reportOptionalCall

**Invariant broken:** "Execution correctness." In `exec_eval.py`, test functions use `getattr(mod, "function_name", None)` to extract functions from loaded modules, then call those functions without guaranteed None-checks. Pyright flags 17 locations where `None` could be called as a function.

**Example:** `exec_eval.py:172` — `process_event({"type": "set", ...})` where `process_event` was assigned via `getattr(mod, "process_event", None)`. The guard at line 166 (`if not all([process_event, get])`) catches this at runtime, but if someone adds a new test that forgets the guard, a `TypeError: 'NoneType' object is not callable` crash would kill the entire trial — not just the one case.

**Why this threatens validity:** An unguarded None call in one test crashes the entire worker process, losing all subsequent case results for that trial.

**Systemic:** LOCAL — all 17 are in `exec_eval.py` test functions using the same `getattr + all()` pattern.

---

### RC5: Global Mutable State Across Pipeline
**Severity: P1 — HIDDEN FAILURE RISK**
**Count:** 38 findings (semgrep ERROR)
**Layers:** Logging (9 in call_logger), LLM Call (1 in llm.py), Execution (3), Config (1), Metrics (2), Templates (4), Prompt Registry (8)
**Tool:** Semgrep `no-global-state`

**Invariant broken:** "No hidden state mutation across runs" and "Isolation between cases."

**Two categories:**

**Intentional (keep, whitelist):**
- `call_logger.py:42` — `_run_dir, _calls_dir, _flat_path` — per-run state, set once at init
- `execution.py:192` — `_ablation_events_path, _ablation_trial, _ablation_run_id` — ablation context
- `experiment_config.py:230` — `_config` singleton — loaded once, frozen
- `llm.py:115` — mock mode flag

**Risky (audit):**
- `prompt_registry.py:48,160` — 8 globals for registry state — if not properly reset between runs, prompts from run N leak into run N+1
- `templates.py:177,190,211,249` — 4 globals for template hashes — should be immutable after init
- `redis_metrics.py:35` — Redis client state
- `state.py:24,29,36` — Unknown state module
- `store.py:6,25` — Unknown store module

**Why this threatens validity:** If `prompt_registry` globals aren't reset between models in the ablation, model A's prompt configuration could bleed into model B's runs. The process-based architecture (separate OS processes per worker) mitigates this for the ablation, but legacy/serial mode is vulnerable.

**Systemic:** YES — 10+ modules use globals for different purposes.

---

### RC6: Silent Parse Failures Producing False Negatives
**Severity: P1 — HIDDEN FAILURE RISK**
**Count:** 3 findings (subset of RC1, parsing-specific)
**Layer:** Parsing Layer
**Tool:** Semgrep `no-silent-except-pass`

**Invariant broken:** "Parsing must produce valid structured outputs."

`parse.py:94,122,202` — Three `except: pass` blocks in the JSON parsing tiers. When a tier fails, it silently returns None and falls through to the next tier. This is *by design* (the 3-tier parser is supposed to try increasingly lenient strategies). BUT: if ALL tiers fail, the raw fallback path produces `code = raw_text`, which is almost certainly wrong.

The Fix D parse gate (already implemented) catches the downstream effect (reasoning_correct=None on empty reasoning). But the parse layer itself doesn't distinguish "intentionally fell through to next tier" from "all tiers failed and we're in raw fallback."

**Why this threatens validity:** A model response that is valid JSON but has an unexpected key name (e.g., `"fixed_code"` instead of `"code"`) will silently fall through all tiers and be treated as raw code. The model's actual code is never extracted.

**Systemic:** LOCAL — contained in parse.py's 3-tier architecture.

---

### RC7: Complexity Hotspots in Critical Functions
**Severity: P1 — HIDDEN FAILURE RISK**
**Count:** 10 findings
**Layers:** Execution (3), Evaluation (1), Parsing (1), Reconstruction (1), Metrics (2), Prompt (1), Exec_eval (1)
**Tool:** Ruff C901

**Functions exceeding complexity threshold (>10):**
- `exec_evaluate` (18) — Execution Layer — THE core evaluation function
- `compute_evidence_metrics` (21) — Evaluation Layer
- `_compute_observability` (21) — Execution Layer
- `compute_metrics` (16) — Metrics Layer
- `build_prompt` (14) — Prompt Construction
- `write_dashboard` (12) — Metrics Layer
- `_test_retry_ack_duplication` (13) — Execution Layer
- `parse_structured_output` (11) — Parsing Layer
- `reconstruct_strict` (11) — Reconstruction Layer
- `_compute_failure_source` (11) — Execution Layer

**Why this threatens validity:** `exec_evaluate` at complexity 18 has the most code paths of any function in the pipeline. Every early return, every exception handler, every assembly branch is a path that must be tested. The logging invariant bug (total_tests=2 on early returns) lived in this function's complexity. Higher complexity = more hiding places for bugs.

**Systemic:** YES — complexity concentrates at layer boundaries (where data transforms between pipeline stages).

---

### RC8: Missing Type Annotations on Pipeline Functions
**Severity: P2 — STRUCTURAL DEBT**
**Count:** 92 findings
**Layers:** All pipeline layers
**Tool:** Pyright reportMissingTypeArgument

**What:** Bare `dict`, `list`, `tuple` without type parameters in function signatures across execution.py (32), exec_eval.py (7), experiment_config.py (7), evaluator.py (10), live_metrics.py (8), parse.py (9), runner.py (12), others.

**Invariant affected:** "Data integrity across pipeline layers." Without typed dicts, there's no static guarantee that the `parsed` dict flowing from parse → reconstruct → evaluate has the expected keys. The reconstruction wiring bug (parsed["code"] = None) would have been caught by types if `parsed` was `TypedDict` with `code: str`.

**Systemic:** YES — every inter-layer data handoff uses untyped dicts.

---

### RC9: Unused Variables and Dead Assignments
**Severity: P2 — STRUCTURAL DEBT**
**Count:** 11 Ruff F841 + 13 Pyright reportUnusedVariable = ~20 unique
**Layers:** Execution (5), Eval (3), Runner (3), Metrics (1), others

**What:** Variables assigned but never used. Examples: `live_metrics.py:149` assigns `n_trials` but never reads it. Various `_` variables in exec_eval.py.

**Why this matters:** Dead assignments in the metrics layer could indicate a metric that was supposed to be computed but isn't. `n_trials` in live_metrics suggests trial-level analysis was planned but never implemented.

**Systemic:** LOCAL — fixable per-instance.

---

### RC10: Too Many Function Parameters
**Severity: P3 — HYGIENE**
**Count:** 7 findings
**Layers:** Execution (3), Runner (2), Retry (2)
**Tool:** Ruff PLR0913

**What:** Functions with >5 parameters. These are orchestration functions that take case, model, condition, config, etc. This is inherent to the pipeline's data-passing architecture.

**Fix type:** DEFER — would require introducing data classes for parameter bundles.

---

### RC11: Deferred Imports (Circular Dependency Symptom)
**Severity: P3 — HYGIENE**
**Count:** 66 findings
**Layers:** All
**Tool:** Ruff PLC0415

**Root cause:** The flat module architecture creates circular import chains (execution → evaluator → exec_eval, evaluator → experiment_config → ...). Deferred imports inside functions are the workaround.

**Fix type:** DEEP REFACTOR — would require restructuring into a proper package hierarchy with clear dependency ordering.

---

### RC12: Magic Numbers in Thresholds
**Severity: P3 — HYGIENE**
**Count:** 36 findings
**Layers:** Execution (8), Runner (6), Metrics (5), Eval (4), others
**Tool:** Ruff PLR2004

**What:** `0.5`, `10`, `0.95`, `0.05` used directly in comparisons. Most are experimental thresholds (score cutoffs, similarity thresholds, stagnation windows).

**Fix type:** DEFER — these belong in experiment_config.yaml, but extracting them is low-priority.

---

## Prioritized Execution Plan

### Phase 0 — Protect Experimental Validity (P0, 4 clusters)

| Order | Cluster | Count | Fix Type | Risk |
|-------|---------|-------|----------|------|
| **1** | RC2: Wildcard import | 1 | QUICK FIX — replace `from evaluator import *` with explicit names | None |
| **2** | RC3: Ghost dependencies | 20 | QUICK FIX — delete unused imports | Low (verify no dynamic usage) |
| **3** | RC1 (parse subset): Silent parse failures | 3 | QUICK FIX — add logging to parse.py except blocks | None |
| **4** | RC4: Unsafe optional access | 17 | MEDIUM — add type narrowing or explicit None checks in exec_eval test functions | Low |

### Phase 1 — Eliminate Hidden Failure Paths (P1, 4 clusters)

| Order | Cluster | Count | Fix Type | Risk |
|-------|---------|-------|----------|------|
| **5** | RC1 (non-parse): Silent exceptions | 8 | QUICK FIX — replace `pass` with `_log.warning()` | Low |
| **6** | RC5 (risky subset): Unaudited global state | ~10 | MEDIUM — audit prompt_registry, templates, state.py globals | Medium |
| **7** | RC6: Parse layer false negatives | 3 | MEDIUM — add parse tier tracking (which tier succeeded) | Low |
| **8** | RC7: Complexity in exec_evaluate | 1 | DEEP — extract sub-functions from 18-complexity function | Medium |

### Phase 2 — Strengthen Type Safety (P2, 2 clusters)

| Order | Cluster | Count | Fix Type | Risk |
|-------|---------|-------|----------|------|
| **9** | RC8: Missing type annotations | 92 | SYSTEMIC — add type params to all pipeline function signatures | None |
| **10** | RC9: Dead variables | 20 | QUICK FIX — delete or use | None |

### Phase 3 — Hygiene (P3, 3 clusters)

| Order | Cluster | Count | Fix Type | Risk |
|-------|---------|-------|----------|------|
| **11** | RC10: Parameter count | 7 | DEFER |
| **12** | RC11: Deferred imports | 66 | DEEP REFACTOR |
| **13** | RC12: Magic numbers | 36 | DEFER |

---

## Dependencies

```
RC2 (wildcard import) → RC3 (ghost deps)
  Both clean up execution.py's import surface.
  Fix wildcard FIRST so explicit imports are visible.

RC1 (silent exceptions) → RC6 (parse false negatives)
  Parse exceptions are a subset of RC1.
  Fix the general pattern, then audit parse-specific implications.

RC3 (ghost deps) → RC8 (type annotations)
  Remove dead imports BEFORE adding types — otherwise you're typing dead code.

RC7 (complexity) → RC4 (unsafe optional)
  Reducing exec_evaluate complexity makes the None-check pattern clearer.
```

---

## Quick Wins (< 30 min total)

1. Replace `from evaluator import *` with explicit imports in execution.py
2. Delete 20 unused imports across 4 files
3. Add `_log.warning(...)` to 11 silent except blocks
4. Fix 1 wildcard import
5. Delete 1 unused variable in live_metrics.py

**Combined impact:** Eliminates all P0 findings and most P1 findings. ~35 lines changed.

---

## Deep Refactors (not now)

1. **Module restructuring** to eliminate circular imports (RC11) — would require converting flat .py files into a proper package hierarchy
2. **TypedDict for pipeline data** (RC8) — would prevent another "parsed['code'] = None" class of bug at the type level
3. **Decompose exec_evaluate** (RC7) — extract assembly, loading, testing, and scoring into separate functions

---

## Noise / Exclusions

| Category | Count | Action |
|----------|-------|--------|
| Semgrep INFO rules | 6,114 | **REMOVE FROM CONFIG** — `assign-alias`, `implicit-none-return`, `inplace-mutation-*`, `partial-dict-update`, `debug-print`, `side-effect-after-loop`, `suspicious-comparison` are heuristics for evaluating LLM-generated code, not benchmark infrastructure |
| Semgrep WARNING false positives | 3,406 | **REMOVE FROM CONFIG** — `no-copy-dict-return` (989), `return-global-mutable` (989), `unreachable-code-after-return` (986), `cache-write-no-invalidate` (431) match every return/assignment |
| Ruff PLC0415 (deferred imports) | 66 | **SUPPRESS** — structural, requires package refactor |
| Ruff PLR2004 (magic numbers) | 36 | **SUPPRESS** — domain-specific thresholds |
| Ruff TRY003 (long messages) | 36 | **SUPPRESS** — detailed errors are correct for research |
| Test file violations | ~300 | **EXCLUDE** — tests have different standards |
| Pyright reportMissingTypeArgument | 92 | **FIX in Phase 2** — mechanical, no risk |
