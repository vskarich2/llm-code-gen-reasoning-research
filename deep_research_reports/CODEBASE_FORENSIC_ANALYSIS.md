# Codebase Forensic Analysis: Bug Introduction, Reasoning Failures, and Predictive Signals

**Date:** 2026-03-23
**Scope:** All non-merge commits by vskarich/veljko.skarich/vskarit
**Commits analyzed:** 48 non-merge commits, with deep diff analysis of 30
**Repository:** cs372research (multi-agent debate system for portfolio allocation)

---

## TASK 1 — BUG CYCLES

### Cycle 1: CRIT Scoring System Cascade

| Field | Value |
|---|---|
| **bug_id** | CRIT-001 |
| **introduction_commit** | `a272075` "CRIT." |
| **intermediate_fixes** | `910e056` "CRIT bugs", `fa62514` "More unbelievably bad CRIT bugs", `4bd787a` "Fixed CRIT bug" |
| **final_fix_commit** | `fa62514` (template defaults) + `4bd787a` (manifest/citations) |
| **files_changed** | `eval/crit/scorer.py`, `eval/crit/prompts/__init__.py`, `models/config.py`, `multi_agent/config.py`, `multi_agent/runner.py`, `multi_agent/graph/nodes.py`, `multi_agent/graph/mocks.py` |
| **diff_summary** | 4-commit fix chain: (1) silently returning fallback score 0.25 → raise RuntimeError, (2) wrong template defaults (enumerated→master) across 4 config files, (3) evidence citations field name mismatch (supported_by_claims→supporting_claims), (4) thesis field moved from top-level to inside reasoning dict |
| **span** | 3 days (Mar 5–8) |

---

### Cycle 2: Data Structure Incompleteness (Bracket Access)

| Field | Value |
|---|---|
| **bug_id** | STRUCT-001 |
| **introduction_commit** | `910e056` "CRIT bugs" (introduced new required fields in claims/position_rationale) |
| **fix_commit** | `04699d0` "Fixes." + `5329ffb` "Fix." |
| **files_changed** | `multi_agent/runner.py`, `multi_agent/graph/mocks.py`, 5 test files |
| **diff_summary** | New fields (evidence, assumptions, falsifiers, impacts_positions, position_rationale, orders) added to data model but: (a) mocks didn't include them, (b) code used `d["key"]` instead of `d.get("key", [])`. Fix: 15+ bracket accesses converted to `.get()` with defaults, all mocks enriched with required fields |

---

### Cycle 3: Retry State Accumulation

| Field | Value |
|---|---|
| **bug_id** | RETRY-001 |
| **introduction_commit** | `4481a4c` "Retry mechanism works" (implicitly; accumulation existed before this but was masked) |
| **fix_commit** | `3485396` "More bugs" + `4481a4c` itself (added `_latest_per_role()` deduplication) |
| **files_changed** | `multi_agent/runner.py`, `multi_agent/debate_logger.py`, `multi_agent/tests/test_pid_phase_toggles.py` |
| **diff_summary** | LangGraph reducer appends all entries (including stale retries) to `state["revisions"]`. Without deduplication, JS divergence metrics were computed on accumulated stale+fresh proposals. Fix: added `_latest_per_role()` to take only the most recent entry per agent role. Also fixed Round 2+ proposal logging (proposals only exist in Round 1) |

---

### Cycle 4: Telemetry Format Migration

| Field | Value |
|---|---|
| **bug_id** | TELEM-001 |
| **introduction_commit** | Gradual — new telemetry file format (`metrics_propose.json`, `metrics_revision.json`) introduced alongside legacy `metrics/` directory |
| **fix_commits** | `cba86f0` "Fixes.", `e880b82` "Fixed bugs" |
| **files_changed** | `tools/dashboard/run_scanner.py` |
| **diff_summary** | Dashboard code only read legacy format. Two fix commits: (1) added preference for new telemetry files with legacy fallback, (2) simplified from 280+ lines of nested conditionals to 140 lines with clear precedence. Both fixes touched the same function (`_extract_divergence_trajectories`). The second fix essentially rewrote the first |

---

### Cycle 5: Distributed Configuration Inconsistency

| Field | Value |
|---|---|
| **bug_id** | CONFIG-001 |
| **introduction_commit** | Unknown — default template names set independently in 4+ files |
| **fix_commit** | `fa62514` "More unbelievably bad CRIT bugs" |
| **files_changed** | `eval/crit/prompts/__init__.py`, `eval/crit/scorer.py`, `models/config.py`, `multi_agent/config.py` |
| **diff_summary** | All 4 files had `crit_user_template` defaulting to `"crit_user_enumerated.jinja"`. Correct value was `"crit_user_master.jinja"`. Fix: search-and-replace across all 4 files. The enumerated template was a development artifact that should never have been the default |

---

### Cycle 6: Race Conditions in File Creation

| Field | Value |
|---|---|
| **bug_id** | RACE-001 |
| **introduction_commit** | Concurrent execution of data pipeline workers |
| **fix_commit** | `4886723` "Fixed prompting issues" |
| **files_changed** | `data-pipeline/final_snapshots/snapshot_builder.py`, `multi_agent/debate_logger.py` |
| **diff_summary** | (a) Snapshot builder used `.json.tmp` temp suffix — multiple workers collided. Fix: `.json.tmp.{os.getpid()}`. (b) DebateLogger used `exist_ok=True` for run dirs, masking collisions. Fix: `exist_ok=False` + `_unique_run_dir()` that detects collision and increments suffix |

---

### Cycle 7: Silent Error Masking → Strict Failure

| Field | Value |
|---|---|
| **bug_id** | SILENT-001 |
| **introduction_commit** | Original system design (permissive) |
| **fix_commit** | `910e056` "CRIT bugs" |
| **files_changed** | `eval/crit/scorer.py`, `multi_agent/graph/llm.py`, `multi_agent/graph/nodes.py` |
| **diff_summary** | (a) CRIT scorer had `_FALLBACK_CRIT = 0.25` — returned fake score on any error. Fix: raise RuntimeError. (b) LLM JSON parser returned `{}` on parse failure. Fix: sanitize + retry, then raise ValueError. (c) Graph nodes used silent defaults for missing required fields. Fix: raise RuntimeError |

---

### Cycle 8: Test Infrastructure Drift

| Field | Value |
|---|---|
| **bug_id** | TEST-001 |
| **introduction_commit** | Dashboard refactored from inline HTML to external JS modules (multiple commits) |
| **fix_commit** | `0464549` "Fixed tests" + `5b60080` "Fixes." |
| **files_changed** | `tests/integration/test_dashboard_api.py`, `tests/integration/test_prompt_logger.py`, `multi_agent/tests/test_pid_phase_toggles.py` |
| **diff_summary** | (a) Integration tests checked for code in HTML `<script>` tags after refactor moved code to external `.js` files. Fix: tests now fetch external JS files and check there. (b) PID tests ran full debate flow hitting CRIT scorer, which crashed on mock data. Fix: set `runner._crit_scorer = None` for routing-only tests |

---

## TASK 2 — CAUSAL FAILURE ANALYSIS

### CRIT-001: CRIT Scoring Cascade

**A. What broke:** The entire CRIT evaluation pipeline produced wrong scores, used wrong templates, looked up wrong field names, and expected data in the wrong shape.

**B. Root causes:**
- **MISALIGNED_ABSTRACTION** — The CRIT bundle expected `thesis` at top level; code put it inside `reasoning` dict. Neither had a shared schema definition.
- **PARTIAL_STATE_UPDATE** — Template default was updated in one file (`eval/crit/prompts/__init__.py`) but not in the other 3 config files that also set it.
- **HIDDEN_DEPENDENCY** — `evidence_citations` was renamed to `supporting_claims` in one module without updating consumers.
- **SILENT_FAILURE** — Fallback score of 0.25 masked all of the above. Every CRIT evaluation returned 0.25 and nobody noticed because it was a plausible-looking number.

**C. Why it happened (reasoning failure):**
The CRIT system was introduced as a single commit (`a272075`) with evidence expansion. The commit touched `eval/evidence.py`, `multi_agent/runner.py`, and test files — but the bundle schema (what fields exist, where they live, what they're named) was implicit, not declared. There was no single source of truth for the CRIT bundle shape. When `runner.py` was modified to nest `thesis` inside `reasoning`, the CRIT scorer wasn't updated because the dependency wasn't visible. The developer assumed local correctness: "I changed the bundle builder, the tests pass, so it works." But the tests didn't cover the scorer's field access pattern.

**The critical reasoning error: treating an implicit protocol as a local concern.**

---

### STRUCT-001: Bracket Access on Missing Keys

**A. What broke:** `KeyError` crashes when LLM responses or mocks didn't include fields the code assumed were present.

**B. Root causes:**
- **EDGE_CASE_IGNORED** — `d["orders"]` works when the LLM returns the field; crashes when it doesn't.
- **PARTIAL_STATE_UPDATE** — 910e056 added new fields to the data model but didn't update all consumers or mocks.

**C. Why it happened:**
**Assumption: LLM output is structured.** The code was written as if LLM responses always match the expected schema. In practice, models omit fields, use different names, or return partial structures. The fix (15+ conversions to `.get()`) is defensive programming that should have been the default from the start.

**The critical reasoning error: trusting external input (LLM output) to match an internal schema.**

---

### RETRY-001: State Accumulation in Retries

**A. What broke:** JS divergence metrics were computed on accumulated stale entries from prior retry attempts, producing misleading results.

**B. Root causes:**
- **RETRY_LOGIC_BUG** — LangGraph's reducer appends all state updates. When a retry produces a new revision, the old revision stays in the list. No deduplication was performed.
- **HIDDEN_DEPENDENCY** — Downstream metrics computation assumed `state["revisions"]` contained exactly one entry per agent role.

**C. Why it happened:**
**Local reasoning about state.** The developer implementing retries focused on "generate a new revision" without tracing what happens to the old revision in the state list. LangGraph's append-only reducer was an implicit dependency that invalidated the assumption "revisions list has one entry per agent."

**The critical reasoning error: not modeling the state container's behavior (append-only) when reasoning about retry correctness.**

---

### TELEM-001: Telemetry Format Migration

**A. What broke:** Dashboard showed missing/stale divergence data because it read only the old telemetry format.

**B. Root causes:**
- **TEMPORAL_ORDERING_ERROR** — New telemetry format deployed to production runs before dashboard code was updated to read it.
- **LOGGING_INCONSISTENCY** — Two telemetry formats coexisted without a clear migration path.

**C. Why it happened:**
**Incremental migration without a flag day.** The new format was introduced alongside the old one, but the consumer (dashboard) wasn't updated atomically. The first fix (`cba86f0`) added dual-format support but was overly complex (280+ lines of nested fallbacks). The second fix (`e880b82`) rewrote it to 140 lines — essentially admitting the first fix was wrong.

**The critical reasoning error: underestimating the complexity of backward-compatible format migration.**

---

### CONFIG-001: Distributed Default Values

**A. What broke:** CRIT scorer used wrong Jinja template (enumerated vs. master), producing malformed prompts.

**B. Root causes:**
- **PARTIAL_STATE_UPDATE** — Default value defined in 4 separate files. When the correct template changed from enumerated to master, only some files were updated.
- **CONFOUNDING_VARIABLE** — The enumerated template produced valid-looking but semantically different output, making the bug hard to detect.

**C. Why it happened:**
**Copy-paste defaults without a single source of truth.** Each config class defined its own `crit_user_template = "crit_user_enumerated.jinja"` independently. There was no shared constant or config file. When the template changed, the developer updated the template files but not all the Python files that referenced them by name.

**The critical reasoning error: not recognizing that a default value duplicated across 4 files is a distributed invariant.**

---

### RACE-001: File Creation Races

**A. What broke:** Concurrent workers overwrote each other's temp files; concurrent debate runs got the same directory name.

**B. Root causes:**
- **EDGE_CASE_IGNORED** — Single-worker development didn't surface the race. Parallel execution (workers, multiple debate runs) did.
- **SILENT_FAILURE** — `exist_ok=True` masked the collision.

**C. Why it happened:**
**Testing under serialization, deploying under parallelism.** The code worked perfectly in single-process mode. The developer didn't reason about concurrent access because the development environment was sequential.

**The critical reasoning error: assuming the execution model of the development environment matches production.**

---

### SILENT-001: Permissive Error Handling

**A. What broke:** Evaluation scores were silently wrong for an unknown period. JSON parse failures returned empty objects that propagated silently.

**B. Root causes:**
- **SILENT_FAILURE** — Every failure path produced a valid-looking default (score 0.25, empty dict `{}`).
- **INVARIANT_VIOLATION** — The contract "CRIT score reflects actual evaluation quality" was violated by the fallback.

**C. Why it happened:**
**"Graceful degradation" as a design philosophy applied where it shouldn't be.** In data pipelines, returning a fallback on error is reasonable. In evaluation systems, a fallback score is a lie. The 0.25 fallback was particularly insidious because it's within the plausible range of real scores — nobody noticed it was always 0.25.

**The critical reasoning error: applying a "resilience" pattern (fallback values) to a "correctness" context (evaluation scoring).**

---

## TASK 3 — DIFF-LEVEL FORENSICS

### Bug 1: CRIT Fallback Score (SILENT-001)

**Before (buggy):**
```python
# eval/crit/scorer.py
_FALLBACK_CRIT = 0.25

def score(self, bundle):
    try:
        result = self._call_llm(bundle)
        return parse_score(result)
    except Exception:
        return {"score": _FALLBACK_CRIT, "reasoning": "fallback"}
```

**After (fixed):**
```python
def score(self, bundle):
    result = self._call_llm(bundle)
    return parse_score(result)  # raises on failure — caller must handle
```

**Why it broke:** Every LLM call that failed (bad JSON, timeout, malformed response) silently returned 0.25. Since CRIT scores normally range 0.0–1.0, the 0.25 didn't trigger any alarms. Downstream analysis treated it as a real (low) score.

**Why the fix works:** Raising an exception forces the caller to handle the failure explicitly — either retry, skip the case, or surface the error. No silent data corruption.

---

### Bug 2: Distributed Template Default (CONFIG-001)

**Before (buggy, in 4 files):**
```python
# eval/crit/prompts/__init__.py
crit_user_template: str = "crit_user_enumerated.jinja"

# eval/crit/scorer.py
crit_user_template: str = "crit_user_enumerated.jinja"

# models/config.py
crit_user_template: str = "crit_user_enumerated.jinja"

# multi_agent/config.py
crit_user_template: str = "crit_user_enumerated.jinja"
```

**After (fixed):**
```python
# All 4 files:
crit_user_template: str = "crit_user_master.jinja"
```

**Why it broke:** The enumerated template was a development artifact with a different prompt structure than the master template. Using it produced CRIT evaluations with the wrong format, leading to unparseable or misleading scores.

**Why the fix works:** All 4 files now agree on the template. But the deeper fix would be a single `CRIT_DEFAULT_TEMPLATE` constant imported everywhere. This wasn't done.

---

### Bug 3: Retry Accumulation (RETRY-001)

**Before (buggy):**
```python
# multi_agent/runner.py
# After retry, state["revisions"] contains:
# [agent_alpha_attempt1, agent_beta_attempt1, agent_alpha_attempt2]
# JS divergence computed on all 3 entries — double-counting alpha

divergence = compute_js_divergence(state["revisions"])
```

**After (fixed):**
```python
def _latest_per_role(self, decisions: list[dict]) -> list[dict]:
    """Deduplicate: keep only the latest entry per agent role."""
    seen = {}
    for d in decisions:
        role = d.get("role", d.get("agent_name"))
        seen[role] = d  # later entries overwrite earlier
    return list(seen.values())

# Now:
divergence = compute_js_divergence(self._latest_per_role(state["revisions"]))
```

**Why it broke:** LangGraph's reducer is append-only. A retry adds a new entry but doesn't remove the old one. The code assumed one entry per role.

**Why the fix works:** `_latest_per_role()` takes the last entry per role, which is the most recent attempt. Stale entries are filtered out.

---

### Bug 4: Race Condition in Temp Files (RACE-001)

**Before (buggy):**
```python
# snapshot_builder.py
tmp_path = out_path.with_suffix(".json.tmp")
write_json(tmp_path, data)
tmp_path.rename(out_path)  # Worker A and Worker B both write to same .json.tmp
```

**After (fixed):**
```python
tmp_path = out_path.with_suffix(f".json.tmp.{os.getpid()}")
write_json(tmp_path, data)
try:
    tmp_path.rename(out_path)
except OSError:
    tmp_path.unlink(missing_ok=True)  # another worker won the race
```

**Why it broke:** Two parallel workers generating the same snapshot would both write to `.json.tmp`, corrupting each other's output. The rename is atomic, but the write is not.

**Why the fix works:** PID-suffixed temp files ensure each worker writes to its own file. The rename is still a race (both try to rename to the same target), but now only one succeeds and the other cleans up gracefully.

---

### Bug 5: Bracket Access on LLM Output (STRUCT-001)

**Before (buggy):**
```python
# multi_agent/runner.py
orders = d["orders"]           # KeyError if LLM omits field
claims = d["claims"]           # KeyError if LLM omits field
evidence = claim["evidence"]   # KeyError
```

**After (fixed):**
```python
orders = d.get("orders", [])
claims = d.get("claims", [])
evidence = claim.get("evidence", [])
```

**Why it broke:** LLM responses don't always include every field. The code was written for the happy path.

**Why the fix works:** `.get()` with default provides a safe fallback. Empty lists propagate through downstream code without errors.

---

## TASK 4 — BUG PATTERN AGGREGATION

### Totals

| Metric | Value |
|---|---|
| **Total bug cycles identified** | 8 |
| **Total fix commits analyzed** | 30 |
| **Fix commits that were multi-part** | 4 (CRIT required 4 commits to fully fix) |
| **Files most frequently fixed** | `multi_agent/runner.py` (7 fix commits), `tools/dashboard/run_scanner.py` (4 fix commits), `eval/crit/scorer.py` (3 fix commits) |

### Distribution Across Failure Types

| Failure Type | Count | % | Bug IDs |
|---|---|---|---|
| **SILENT_FAILURE** | 3 | 19% | SILENT-001, part of CRIT-001, part of STRUCT-001 |
| **PARTIAL_STATE_UPDATE** | 3 | 19% | CONFIG-001, STRUCT-001, CRIT-001 (bundle shape) |
| **HIDDEN_DEPENDENCY** | 2 | 13% | CRIT-001 (field rename), RETRY-001 (LangGraph reducer) |
| **EDGE_CASE_IGNORED** | 2 | 13% | STRUCT-001 (missing fields), RACE-001 (parallelism) |
| **MISALIGNED_ABSTRACTION** | 1 | 6% | CRIT-001 (bundle schema) |
| **RETRY_LOGIC_BUG** | 1 | 6% | RETRY-001 |
| **LOGGING_INCONSISTENCY** | 1 | 6% | TELEM-001 |
| **TEMPORAL_ORDERING_ERROR** | 1 | 6% | TELEM-001 |
| **CONFOUNDING_VARIABLE** | 1 | 6% | CONFIG-001 (valid-looking wrong output) |
| **INVARIANT_VIOLATION** | 1 | 6% | SILENT-001 (score correctness contract) |

### Most Common Failure Mode: **SILENT_FAILURE + PARTIAL_STATE_UPDATE (tied at 19%)**

These two modes often co-occur: a partial update creates an inconsistency, and silent error handling masks it.

### Most Dangerous Failure Mode: **SILENT_FAILURE**

Silent failures are the most dangerous because they produce valid-looking but incorrect results. The CRIT fallback score of 0.25 is the canonical example — it's within range, it doesn't crash anything, but every evaluation is a lie. The developer's commit message ("More unbelievably bad CRIT bugs") suggests they were genuinely surprised at how long the bug persisted.

### Recurring Patterns

**Pattern 1: "Cascade of implicit schemas"**
The CRIT system had no explicit schema for its bundle/contract. Fields were added/renamed/moved across 4 commits by different code paths. Each change was locally correct but globally inconsistent. This produced a 4-commit fix chain.

**Pattern 2: "Defensive programming as afterthought"**
15+ bracket-access-to-`.get()` conversions happened in a single fix commit. The entire codebase assumed LLM output matched the expected schema. This is a systemic pattern, not a one-off bug.

**Pattern 3: "Fix the fix"**
Telemetry format migration required TWO fix commits — the first fix was too complex (280 lines of nested fallbacks) and was rewritten in the second fix (140 lines). The developer's mental model of the problem was wrong on the first attempt.

**Pattern 4: "Copy-paste configuration"**
The same default value (`crit_user_enumerated.jinja`) was independently defined in 4 files. No shared constant. Inevitable divergence.

---

### Answer: What kinds of reasoning errors does this codebase systematically exhibit?

**1. Implicit protocol reasoning.** The codebase treats data schemas as implicit contracts between producers and consumers. When a producer changes the schema (e.g., moving `thesis` inside `reasoning`), consumers aren't updated because the dependency isn't visible. This is the #1 reasoning failure in the codebase.

**2. Happy-path code, exception-path thinking.** Code is written for the case where everything works. LLM responses are assumed to be well-formed. Concurrent access is assumed not to happen. When these assumptions fail, the system either crashes (bracket access) or silently degrades (fallback scores).

**3. Local correctness assumed to imply global correctness.** Each commit is locally correct — the changed file does what the developer intended. But the change's effect on downstream consumers is not traced. This is the classic "works on my machine" failure applied to data flow.

**4. Overengineered resilience in the wrong place.** Fallback scores, `exist_ok=True`, empty-dict returns — these are resilience patterns applied to contexts that require correctness. The result is bugs that are harder to find because they don't crash.

---

## TASK 5 — RETRY / FLAPPING ANALYSIS

### Oscillating Fix: Telemetry Format (TELEM-001)

| Commit | What happened |
|---|---|
| (implicit) | New telemetry format deployed |
| `cba86f0` | Fix 1: Added dual-format support. 280+ lines of nested conditionals, 3 fallback paths |
| `e880b82` | Fix 2: Rewrote the same function. 140 lines, clear precedence order |

**Instability pattern:** Fix 1 was over-engineered. The developer tried to handle every possible combination of old/new format availability, producing code with ~8 conditional branches. This was fragile — any new data format change would require updating all branches. Fix 2 recognized that a clear preference order (new first, legacy fallback) is simpler and more maintainable.

**Why the model failed to converge:** The developer's mental model of "handle all cases" produced combinatorial complexity. The correct model was "prioritized fallback chain" — try the best source first, fall back to the next.

---

### Multi-Fix Cycle: CRIT System (CRIT-001)

| Commit | What was fixed | What was still broken |
|---|---|---|
| `a272075` | Evidence expansion introduced | Bundle schema not documented |
| `910e056` | Fallback score removed, JSON parsing hardened, validation added | Wrong template defaults, wrong field names |
| `fa62514` | Template defaults fixed (4 files), field names fixed, thesis location fixed | Missing manifest metadata, citation extraction |
| `4bd787a` | Manifest metadata added, citation extraction fallback, round numbering | (finally stable) |

**Instability pattern:** Each fix revealed a new layer of bugs. The CRIT system was introduced without integration tests that covered the full pipeline (prompt → LLM → parse → score). Each fix addressed what the developer could see at the time, but the silent failure mode (0.25 fallback) hid deeper issues.

**Why the model failed to converge:** No end-to-end test. Each fix was validated by running a subset of the pipeline. The full prompt→score→report chain was never tested atomically until after all 4 fixes were applied.

---

### Partial Fix: Data Structure Incompleteness (STRUCT-001)

| Commit | Scope of fix |
|---|---|
| `5329ffb` | Fixed `d["orders"]` and `d["claims"]` in `runner.py` |
| `04699d0` | Fixed 15+ more bracket accesses, enriched all mocks |

**Instability pattern:** The first fix addressed the two bracket accesses that the developer hit during testing. But the same pattern existed in 13+ other places. The second fix was a systematic sweep.

**Why the model failed to converge on first attempt:** The developer fixed the symptom they observed rather than searching for the pattern. A `grep` for `\["` in `runner.py` would have found all instances at once.

---

## TASK 6 — PROPOSED STRUCTURED LOGGING

### A. Log Schema (JSONL)

```json
{
    "timestamp": "2026-03-23T14:30:22.000Z",
    "event_type": "code_edit | reasoning | test_run | test_failure | retry | schema_change | config_change",
    "session_id": "uuid — groups events within one work session",
    "commit_context": {
        "branch": "rca-style-general-retry-mechanism",
        "parent_commit": "abc1234",
        "files_in_scope": ["multi_agent/runner.py", "eval/crit/scorer.py"]
    },
    "reasoning_trace": {
        "intent": "string — what the developer/agent is trying to accomplish",
        "assumptions": ["list of assumptions being made"],
        "dependencies_considered": ["list of downstream consumers checked"],
        "dependencies_not_considered": ["(filled post-hoc by reasoning_evaluator_audit)"]
    },
    "diff": {
        "file": "multi_agent/runner.py",
        "function": "_build_reasoning_bundle",
        "change_type": "field_rename | field_move | access_pattern | error_handling | new_function",
        "before_snippet": "...",
        "after_snippet": "..."
    },
    "test_result": {
        "ran": true,
        "passed": 14,
        "failed": 2,
        "failure_details": ["test_reasoning_bundle::test_thesis_location — KeyError: 'thesis'"]
    },
    "detected_failure_type": "SILENT_FAILURE | PARTIAL_STATE_UPDATE | HIDDEN_DEPENDENCY | null",
    "schema_impact": {
        "fields_added": ["reasoning.thesis"],
        "fields_removed": ["thesis"],
        "fields_renamed": {"supported_by_claims": "supporting_claims"},
        "consumers_checked": ["eval/crit/scorer.py"],
        "consumers_unchecked": ["multi_agent/runner.py:_build_reasoning_bundle"]
    }
}
```

### B. Hook Points

| Hook | When | What to Log |
|---|---|---|
| **pre_edit** | Before any code change | Intent, assumptions, files in scope |
| **post_edit** | After code change, before commit | Diff, change_type, schema_impact |
| **post_test** | After test suite runs | Pass/fail counts, failure details |
| **on_retry** | When a fix attempt fails and developer tries again | Prior reasoning, what assumption was wrong |
| **schema_audit** | When any data structure (dict shape, function signature) changes | All producers and consumers of that structure |
| **config_audit** | When any default value or config setting changes | All files that define the same setting |

### C. Minimal Implementation Plan

**1. Where to write logs:**
```
cs372research/
  .dev_logs/
    session_{timestamp}.jsonl    # one file per work session
```

**2. Integration approach — Git hooks + CLI wrapper:**

```bash
# .git/hooks/pre-commit (lightweight)
#!/bin/bash
# Capture changed files and warn about schema changes
python3 scripts/dev_log_precommit.py
```

```python
# scripts/dev_log_precommit.py
"""Pre-commit hook that:
1. Detects if any dict/dataclass field was added/removed/renamed
2. Checks if default values were changed
3. Logs a schema_audit event if so
4. Warns developer to check consumers
"""
```

**3. Non-breaking integration:**
- Logs are in `.dev_logs/` (gitignored)
- Hook is opt-in (developer installs via `make install-hooks`)
- No runtime cost — logging only happens during development, not in production
- Schema audit is static analysis (AST-based), not runtime

**4. Key detection: "distributed default" detector:**
```python
# scripts/check_distributed_defaults.py
"""Scan all .py files for the pattern:
    field_name: type = "literal_value"
Flag any literal that appears in 2+ files with the same field name.
"""
```

This would have caught CONFIG-001 immediately.

---

## TASK 7 — CRITICAL INSIGHT: Predictive Signals

### If reasoning traces had been captured, these signals would have predicted each bug BEFORE it happened:

---

**CRIT-001 (CRIT Scoring Cascade):**

| Signal | How it would appear in trace |
|---|---|
| **"No schema document referenced"** | Reasoning trace for `a272075` would show: intent="add evidence expansion to CRIT bundle" with `dependencies_considered: []` for the bundle consumer (scorer). A schema_audit event would show `fields_added: ["reasoning.thesis"]` with `consumers_unchecked: ["eval/crit/scorer.py"]` |
| **"Default value duplication"** | A config_audit event at commit time would flag: `crit_user_template` defined in 4 files with same literal value. Any change to one would require changing all 4 |

**Prediction rule:** `IF schema_impact.fields_added AND len(schema_impact.consumers_unchecked) > 0 THEN WARN("schema change has unchecked consumers")`

---

**STRUCT-001 (Bracket Access):**

| Signal | How it would appear in trace |
|---|---|
| **"New required field without consumer audit"** | The `910e056` commit added `evidence`, `assumptions`, `falsifiers` to the data model. A schema_audit would show these fields with `consumers: ["runner.py:_normalize_claims", "runner.py:_parse_action"]` — and a grep would find bracket access in those consumers |

**Prediction rule:** `IF schema_impact.fields_added AND any_consumer_uses_bracket_access(field) THEN WARN("new required field accessed via unsafe bracket notation")`

---

**RETRY-001 (State Accumulation):**

| Signal | How it would appear in trace |
|---|---|
| **"Assumption about container semantics"** | Reasoning trace would show: `assumptions: ["state['revisions'] has one entry per agent"]`. A dependency audit would flag: "LangGraph reducer is append-only — this assumption may be violated under retry" |

**Prediction rule:** `IF reasoning.assumptions contains "list has N entries" AND state_container is append-only THEN WARN("retry may accumulate entries beyond N")`

---

**CONFIG-001 (Distributed Defaults):**

| Signal | How it would appear in trace |
|---|---|
| **"Literal string as default in multiple files"** | A static analysis pass (the "distributed default detector" from Task 6) would flag this at any commit |

**Prediction rule:** `IF same_literal_default appears in N > 1 files THEN WARN("distributed invariant — changes must be synchronized")`

---

**RACE-001 (File Creation Race):**

| Signal | How it would appear in trace |
|---|---|
| **"Shared temp file path without PID/thread suffix"** | Reasoning trace would show: `assumptions: ["only one worker writes this file at a time"]`. An execution-model audit would flag: "parallel workers enabled — assumption may be violated" |

**Prediction rule:** `IF file_write uses shared path AND execution_model.parallel THEN WARN("race condition on shared temp file")`

---

**SILENT-001 (Fallback Scores):**

| Signal | How it would appear in trace |
|---|---|
| **"Catch-all exception returns valid-looking value"** | A code pattern detector would flag: `except Exception: return {plausible_value}` in an evaluation context. The key is the context: evaluation systems must NOT silently degrade |

**Prediction rule:** `IF except_clause returns valid_value AND function_context == "evaluation" THEN WARN("silent failure in evaluation — scores will be silently wrong")`

---

### Summary: The Meta-Signal

Every bug in this codebase shares one meta-signal:

> **An assumption was made about something outside the changed file, and that assumption was not checked.**

The assumptions fall into three categories:
1. **Schema assumptions** — "this dict has these keys" (CRIT-001, STRUCT-001)
2. **Execution model assumptions** — "this runs sequentially" / "this list has one entry per role" (RACE-001, RETRY-001)
3. **Configuration assumptions** — "this default is correct everywhere" (CONFIG-001)

A logging system that captures `reasoning.assumptions` and cross-references them against `schema_impact.consumers_unchecked` would have flagged 6 of 8 bug cycles before they shipped.

The remaining 2 (TELEM-001 format migration, TEST-001 infrastructure drift) require a different signal: **"consumer code was not updated alongside producer code."** This is detectable via a dependency graph that tracks which functions read which data formats.

---

**Bottom line: The codebase's bugs are not caused by lack of skill. They are caused by insufficient tracing of cross-module effects. Every fix commit reveals a dependency that was invisible at the time of the introduction commit. A structured logging system that makes these dependencies visible at edit time would prevent the majority of these bugs.**
