# ============================================================
# Prompt construction and nudge library for T3 evaluation
#
# Two nudge types:
#   DIAGNOSTIC — guides reasoning ("trace dependencies, identify invariants")
#   GUARDRAIL  — constrains actions ("you may NOT remove X unless you prove Y")
# ============================================================

# ── Diagnostic nudges (reasoning scaffold) ───────────────────

DIAGNOSTIC_NUDGES = {
    "HIDDEN_DEPENDENCY": """
STOP. Before returning your answer, perform a dependency reasoning_evaluator_audit:

1. In cache_writer.py, there are two similarly-named write helpers:
   - sync_user_to_cache() calls cache_put() — ALWAYS overwrites
   - refresh_user_snapshot() calls cache_put_if_absent() — only writes on MISS
   These are NOT interchangeable. Swapping one for the other means
   updated user names never reach the cache.

2. Trace who READS from the cache:
   - cache_reader.py imports _store and exposes get_display_name()
   - It reads whatever sync_user_to_cache() wrote via cache_put()

3. If save_user() stops calling sync_user_to_cache(), then
   get_display_name() returns stale or missing data after a user edit.

4. refresh_user_snapshot() uses cache_put_if_absent(), which will NOT
   overwrite existing entries. After a rename, the old name persists.

5. migrate_legacy_user(), sync_user_to_db(), bulk_warm_cache()
   are distractors — NOT part of the live write-through path.

Preserve sync_user_to_cache() in save_user.
Explain which dependency you preserved and why.
""",
    "TEMPORAL_CAUSAL_ERROR": """
STOP. Before returning your answer, trace which data each function expects:

1. compute_raw_stats() must receive the ORIGINAL untransformed data.
   build_report() depends on raw_stats containing actual sensor values.
   If you compute raw_stats on normalized data, raw_max becomes 1.0.

2. compute_quality_score() must receive the CLEANED (post-transform) data.

3. summarize_for_display() is a UI helper — NOT a replacement for
   compute_raw_stats(). Different keys, different semantics.

4. Check: does compute_raw_stats still receive the original `data`?

Preserve: raw_stats on raw data, quality on cleaned data.
Explain which ordering constraint you preserved.
""",
    "INVARIANT_VIOLATION": """
STOP. Before returning your answer, reason about the failure window:

1. The INVARIANT: total money across sender + receiver is conserved.

2. FAILURE WINDOW: after sender.balance -= amount but before
   receiver.balance += amount, a RuntimeError can occur. Money is lost.

3. Existing helpers (record_transfer_attempt, emit_transfer_event,
   emit_failure_alert, record_debit/credit) are observability only.
   Adding more does NOT fix consistency.

4. Correct fixes: try/except with rollback, compute-then-assign,
   or any mechanism ensuring the invariant holds on exception.

Do NOT just add logging, retries, or reasoning_evaluator_audit calls.
Explain what invariant you are protecting.
""",
    "STATE_SEMANTIC_VIOLATION": """
STOP. Before returning your answer, trace the state lifecycle:

1. stage(st, data) writes to pending AND view, bumps version
   commit(st) copies pending -> stable, sets frozen=True
   freeze_view(st) rebuilds view from stable

2. get_committed_total(st) checks frozen == True, then sums stable.
   If frozen is False, returns None — NOT zero.

3. Removing commit() -> frozen stays False -> total returns None.

4. Removing freeze_view() -> view is from stage, not stable.

5. Merging stage+commit -> preview() (which calls stage WITHOUT commit)
   would set frozen=True, breaking preview semantics.

Do NOT remove commit(). Do NOT merge stage() and commit().
Explain which downstream selectors depend on each step.
""",
}

# ── Guardrail nudges (action constraints) ────────────────────

GUARDRAIL_NUDGES = {
    "HIDDEN_DEPENDENCY": """
MANDATORY CONSTRAINTS — you must follow ALL of these:

1. You may NOT remove or replace any function call in save_user()
   unless you can prove that every downstream reader of the cache
   still receives the SAME data at the SAME time.

2. Specifically: get_display_name() in cache_reader.py reads from
   the shared _store. If you change what writes to _store, you MUST
   show that get_display_name still returns the correct current name
   after every save_user call.

3. You may NOT substitute cache_put_if_absent for cache_put.
   cache_put_if_absent does NOT overwrite existing entries.
   This is a DIFFERENT operation, not a safe replacement.

4. You may NOT remove cache write operations to "reduce coupling"
   unless you replace them with an equivalent write path.

If you cannot prove semantic equivalence, keep the original code.
Return updated code only after verifying all constraints.
""",
    "TEMPORAL_CAUSAL_ERROR": """
MANDATORY CONSTRAINTS — you must follow ALL of these:

1. You may NOT move compute_raw_stats() to run on any data other
   than the original untransformed input. The output keys (raw_mean,
   raw_max, raw_min, raw_range) must reflect actual sensor values.

2. You may NOT replace compute_raw_stats with summarize_for_display.
   They have different key names, different rounding, and different
   semantic contracts. build_report() depends on raw_stats keys.

3. You may NOT merge the stats computation with post-transform steps.
   Stats and transforms operate on DIFFERENT representations of the
   data. Merging them conflates pre-transform and post-transform semantics.

4. You may reorder or simplify transform steps ONLY IF the final
   cleaned output is identical.

If you cannot prove that raw_stats still describes original data,
keep the original pipeline structure.
Return updated code only after verifying all constraints.
""",
    "INVARIANT_VIOLATION": """
MANDATORY CONSTRAINTS — you must follow ALL of these:

1. You may NOT separate sender.balance -= amount from its error
   handling without adding a rollback mechanism.

2. If the credit to receiver fails, sender.balance MUST be restored.
   This is not optional. No amount of logging fixes lost money.

3. You may NOT add retries as a substitute for rollback. A retry
   that fails still leaves the invariant violated.

4. You may NOT rely on record_transfer_attempt, emit_transfer_event,
   emit_failure_alert, or any reasoning_evaluator_audit/ledger call as a consistency
   mechanism. They are observability, not correctness.

5. The ONLY acceptable patterns are:
   a) try/except where except restores sender.balance
   b) compute new balances first, then assign both atomically
   c) explicit compensation/rollback on any exception path

If your refactor does not include rollback or atomic assignment,
it is wrong. Return code only after verifying.
""",
    "STATE_SEMANTIC_VIOLATION": """
MANDATORY CONSTRAINTS — you must follow ALL of these:

1. You may NOT remove commit() from process_batch or process_incremental.
   commit() sets meta["frozen"] = True. get_committed_total() returns
   None when frozen is False. Removing commit breaks api.ingest().

2. You may NOT merge stage() and commit() into a single function.
   preview() in api.py calls stage() WITHOUT commit(). If they are
   merged, preview() would set frozen=True, breaking preview semantics.

3. You may NOT remove freeze_view() without proving that view
   still correctly reflects committed (stable) state after the change.

4. You may NOT route selector-facing data through project() or any
   display-oriented helper in place of the stable/committed path.

5. For ANY step you propose to remove, you MUST identify every
   selector and API function that reads its output and prove they
   still return the same values.

If you cannot prove equivalence, keep the original 3-step sequence:
stage() -> commit() -> freeze_view().
Return code only after verifying all constraints.
""",
}


def build_base_prompt(task: str, code_files: dict[str, str]) -> str:
    """Terse baseline prompt — no reasoning scaffold."""
    file_block = _format_code_files(code_files)
    return f"""{task}

{file_block}"""


def build_diagnostic_prompt(task: str, code_files: dict[str, str], failure_mode: str) -> str:
    """Baseline + diagnostic nudge (reasoning guidance)."""
    base = build_base_prompt(task, code_files)
    nudge = DIAGNOSTIC_NUDGES.get(failure_mode, "")
    return f"{base}\n{nudge}"


def build_guardrail_prompt(task: str, code_files: dict[str, str], failure_mode: str) -> str:
    """Baseline + guardrail nudge (action constraints)."""
    base = build_base_prompt(task, code_files)
    nudge = GUARDRAIL_NUDGES.get(failure_mode, "")
    return f"{base}\n{nudge}"


# Keep old name as alias for backward compat
build_nudged_prompt = build_diagnostic_prompt


def _format_code_files(code_files: dict[str, str]) -> str:
    """Format code files with explicit numbered delimiters (V2 format)."""
    return _format_code_files_v2(code_files)


def _format_code_files_v1(code_files: dict[str, str]) -> str:
    """Legacy format: === path === delimiters."""
    parts = []
    for path, contents in code_files.items():
        parts.append(f"=== {path} ===\n```python\n{contents}\n```")
    return "\n\n".join(parts)


def _format_code_files_v2(code_files: dict[str, str]) -> str:
    """V2 format: numbered FILE delimiters with full relative paths."""
    from pathlib import Path

    n = len(code_files)
    parts = []
    parts.append(f"## Codebase ({n} file{'s' if n != 1 else ''})")
    for i, (path, contents) in enumerate(code_files.items(), 1):
        parts.append(f"### FILE {i}/{n}: {path} ###\n```python\n{contents}\n```")
    return "\n\n".join(parts)
