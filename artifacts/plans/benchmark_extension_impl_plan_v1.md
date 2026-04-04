# Benchmark Extension Implementation Plan v1

**Date:** 2026-04-01
**Status:** PLAN — awaiting approval
**Implements:** BENCHMARK_EXTENSION_PLAN_v5.md, Stage 0 + Stage 1

---

## Scope

Implement the gold-standard example case (`cache_bypass_attractor`) and 5 additional pilot cases (6 total for Stage 1). Each case requires:

1. Buggy code files in `code_snippets_v2/{case_id}/`
2. `CASE_DOC.md` per case
3. Test file in `tests_v2/test_{family}.py`
4. Reference fix in `reference_fixes/{case_id}.py`
5. Entry in `cases_v2.json`
6. Validation: no-op fails, reference fix passes, trap fixes fail

---

## Cases to Implement

### Case 1: `cache_bypass_attractor` (false_fix_attractor, B)

Fully specified in v5 plan Section 6. Multi-file case (3 files + test).

- **Files:** `cache_manager.py`, `data_store.py`, `report_generator.py`
- **Bug:** CacheManager.get() never writes back to cache after fetch
- **Attractor:** Fix counter/rate-limit in ReportGenerator (symptom-proximal)
- **Root cause:** Missing `self._cache[key] = result` in CacheManager.get()
- **Invariants:** cache-hit-no-fetch, multi-key generalization, causal-location (DataStore.fetch must still count)

### Case 2: `wrong_layer_compensate` (abstraction_leak, B)

- **Scenario:** A `Formatter` class calls a `Parser.parse()` method. Parser returns raw data with trailing whitespace. Formatter crashes on empty-after-strip results. Root cause: Parser should strip whitespace before returning. Attractor: Formatter adds strip() + null-check compensation at caller level.
- **Files:** `parser.py`, `formatter.py`
- **Bug:** `Parser.parse()` doesn't strip whitespace from fields
- **Trap 1:** Add `.strip()` in Formatter before using each field (wrong layer — caller compensation)
- **Trap 2:** Add null/empty check in Formatter output (defensive but wrong layer)
- **Trap 3:** Add a post-processing wrapper around Parser output in Formatter.__init__ (wrong layer)
- **Reference fix:** `Parser.parse()` strips whitespace before returning
- **Invariant:** Any new consumer of Parser.parse() must get clean data without its own stripping

### Case 3: `stale_config_reload` (false_fix_attractor, C)

- **Scenario:** A 3-file system: `config_loader.py` reads config, `validator.py` validates it, `app.py` runs the pipeline. After config reload, validator still sees old values because config_loader caches the parsed dict and validator holds a stale reference. Symptom: app.py validation fails after reload.
- **Files:** `config_loader.py`, `validator.py`, `app.py`
- **Bug:** `config_loader.reload()` replaces the internal dict reference but validator grabbed the old reference at init time
- **Attractor:** Patch `app.py` to re-validate or skip validation after reload (symptom-proximal)
- **Trap 2:** Patch `validator.py` to re-fetch config on every call (compensates, but wrong — config_loader should notify or return fresh ref)
- **Trap 3:** Add a `force_refresh` parameter to validator (defensive coding, doesn't fix root cause)
- **Reference fix:** `config_loader.reload()` mutates the existing dict in-place (`.clear()` + `.update()`) rather than replacing the reference, so all holders see the new values
- **Invariant:** After reload(), any existing reference to config must reflect new values

### Case 4: `dispatch_handler_trap` (control_flow_trap, B)

- **Scenario:** An event processor dispatches events to handlers by type. A `priority_event` should go to `handle_priority()` but due to a registration bug, it dispatches to `handle_standard()`. The standard handler processes it incorrectly (wrong timeout, missing escalation). Model is tempted to fix the standard handler's logic to accommodate priority events instead of fixing the dispatch.
- **Files:** `dispatcher.py`, `handlers.py`
- **Bug:** Dispatch table maps "priority" → handle_standard instead of handle_priority
- **Attractor (trap 1):** Add priority-event logic inside handle_standard (fixes symptom but wrong handler)
- **Trap 2:** Add a priority check at the start of handle_standard that redirects (patching handler instead of dispatch)
- **Trap 3:** Change handle_priority to call handle_standard first then add priority logic on top (wrong fix direction)
- **Reference fix:** Fix dispatch table entry: `"priority": handle_priority`
- **Invariant:** handle_standard must NOT contain any priority-specific logic; dispatch table must route priority→handle_priority

### Case 5: `dual_cause_ambiguous` (misinferred_dependency, B)

- **Scenario:** A report generator fails with wrong totals. Two plausible causes: (1) the aggregator function has an off-by-one in its loop bounds, (2) the data_loader function silently drops the last row due to an fencepost error in its pagination. Both are plausible from local inspection. The actual bug is in data_loader — it returns `rows[:limit]` when it should return `rows[:limit+1]` (fencepost). The aggregator is correct.
- **Files:** `data_loader.py`, `aggregator.py`, `report.py`
- **Bug:** `data_loader.fetch_page()` returns one fewer row than expected due to off-by-one in slice
- **Trap 1 (wrong cause):** Fix aggregator loop to iterate `range(len(data))` instead of `range(1, len(data))` — looks like an off-by-one fix but the aggregator is actually correct (it skips a header row)
- **Trap 2:** Add +1 adjustment in report.py when passing page size to data_loader (compensates but doesn't fix root cause)
- **Trap 3:** Change aggregator to handle short pages gracefully (defensive, doesn't fix the data loss)
- **Reference fix:** `data_loader.fetch_page()` returns `rows[:limit+1]` or equivalent
- **Invariant:** data_loader.fetch_page(limit=N) must return exactly N data rows (given sufficient source data)
- **Why misinferred_dependency:** Both the aggregator off-by-one and the data_loader fencepost are comparably plausible from local reading. A reviewer would need to trace the full data flow to disambiguate.

### Case 6: `incomplete_state_sync` (intervention_boundary, B)

- **Scenario:** A user profile update function correctly identifies it needs to update the database record (correct root cause, correct layer). It updates the name field but forgets to update the `modified_at` timestamp and the search index. Downstream queries use `modified_at` for cache invalidation, so stale data persists.
- **Files:** `profile.py`, `search_index.py`
- **Bug:** `profile.update()` writes new name to DB but doesn't update `modified_at` or search index
- **Trap 1:** Fix only `modified_at` but not search index (incomplete)
- **Trap 2:** Fix only search index but not `modified_at` (incomplete)
- **Trap 3:** Add a cache-busting parameter to downstream queries (wrong point — symptom compensation)
- **Reference fix:** `profile.update()` sets name, modified_at, AND calls search_index.reindex()
- **Invariant:** After update(), both modified_at > previous timestamp AND search_index.lookup(user_id) returns new name

---

## Files Touched

| Artifact | Count | Location |
|---|---|---|
| New case directories | 6 | `code_snippets_v2/{case_id}/` |
| New code files | ~15 | Inside case directories |
| New CASE_DOC.md files | 6 | Inside case directories |
| New test files | 6 | `tests_v2/test_{family}.py` |
| New reference fixes | 6 | `reference_fixes/{case_id}.py` |
| Modified: cases_v2.json | 1 | Add 6 entries |

No existing files are modified except `cases_v2.json` (append only).

---

## Validation Plan

For each case, after implementation:

1. Run no-op: confirm buggy code fails the test
2. Run reference fix: confirm fixed code passes the test
3. Manually apply each trap fix: confirm each fails at least one invariant
4. Verify validation matrix matches v5 plan spec

---

## Invariants

- No changes to runner.py, orchestrate.py, or any pipeline code
- All new cases use flat sibling imports only
- All new test functions follow `test(mod) -> (bool, list[str])` or `test_{difficulty}(mod)` signature
- All code files in same directory per case
- No new dependencies

---

## Implementation Order

1. `cache_bypass_attractor` — gold standard, fully specified, implement first as calibration
2. `dispatch_handler_trap` — simple 2-file, fast to validate
3. `wrong_layer_compensate` — 2-file abstraction_leak
4. `dual_cause_ambiguous` — 3-file misinferred_dependency
5. `stale_config_reload` — 3-file false_fix_attractor
6. `incomplete_state_sync` — 2-file intervention_boundary

Total estimated: ~15 code files + 6 test files + 6 CASE_DOC.md + 6 reference fixes + 6 cases_v2.json entries.
