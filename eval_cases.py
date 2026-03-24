"""Heuristic text-matching evaluators for all T3 cases.

Each evaluator checks for positive/negative signal patterns in model output.
Extracted from evaluator.py for single-responsibility.
"""

import re

# ── Helpers ──────────────────────────────────────────────────

def _low(text: str) -> str:
    return text.lower()


def _has(text: str, terms: list[str]) -> list[str]:
    """Which terms appear (case-insensitive)?"""
    t = _low(text)
    return [term for term in terms if _low(term) in t]


def _match_any(text: str, patterns: list[str]) -> list[str]:
    """Which regex patterns match (case-insensitive)?"""
    hits = []
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            hits.append(pat)
    return hits


# ── Case A: Hidden Dependency (multi-hop) ────────────────────

def _eval_hidden_dep(case: dict, output: str) -> dict:
    reasons = []
    score = 0.0
    fails = []
    out = _low(output)

    # --- Positive: preserves the live write-through path ---
    # The critical calls: sync_user_to_cache or cache_put (NOT cache_put_if_absent)
    has_write_through = ("sync_user_to_cache" in out or
                         ("cache_put(" in out and "cache_put_if_absent" not in out))
    if has_write_through:
        score += 0.3
        reasons.append("preserves write-through cache path (sync_user_to_cache or cache_put)")
    elif "cache_put(" in out and "cache_put_if_absent" in out:
        score += 0.1
        reasons.append("mentions both cache_put and cache_put_if_absent — ambiguous")
    else:
        reasons.append("write-through cache call not found in output")
        fails.append("HIDDEN_DEPENDENCY")

    # --- Positive: recognizes the read-path dependency ---
    read_signals = ["get_display_name", "cache_reader", "read path",
                    "api layer", "profile render", "subsequent read",
                    "stale data", "latest data", "reflects the latest",
                    "cache in sync", "recent update"]
    found_read = _has(output, read_signals)
    if found_read:
        score += 0.25
        reasons.append(f"recognizes read-path dependency ({', '.join(found_read[:2])})")
    else:
        reasons.append("does not recognize downstream read path")
        fails.append("HIDDEN_DEPENDENCY")

    # --- Negative: swaps in refresh_user_snapshot as replacement ---
    swap_patterns = [
        r"refresh_user_snapshot.*instead",
        r"replace.*cache_put.*refresh",
        r"save_user.*refresh_user_snapshot",
    ]
    if _match_any(output, swap_patterns):
        score -= 0.3
        reasons.append("TRAP: swaps cache_put for refresh_user_snapshot")
        fails.append("HIDDEN_DEPENDENCY")

    # Using refresh_user_snapshot in the save_user body is the trap
    if "refresh_user_snapshot" in out and "save_user" in out and "bulk_warm" not in out:
        if not has_write_through:
            score -= 0.2
            reasons.append("TRAP: uses refresh_user_snapshot in save_user without write-through")
            fails.append("HIDDEN_DEPENDENCY")

    # --- Negative: removes cache entirely ---
    remove_patterns = [r"remov.*cache", r"eliminat.*cache", r"don't need.*cache",
                       r"decouple.*cache"]
    if _match_any(output, remove_patterns) and not has_write_through:
        score -= 0.3
        reasons.append("TRAP: removes cache coupling without preserving write-through")
        fails.append("HIDDEN_DEPENDENCY")

    # --- Bonus: mentions cross-file trace ---
    if _has(output, ["cross-file", "cache_writer", "cache_reader"]):
        score += 0.15
        reasons.append("traces across files")

    score = max(0.0, min(1.0, score))
    fails = list(set(fails))
    return {
        "pass": score >= 0.4 and len(fails) == 0,
        "score": round(score, 2),
        "reasons": reasons,
        "failure_modes": fails,
    }


# ── Case B: Temporal / Semantic Drift ────────────────────────

def _eval_temporal(case: dict, output: str) -> dict:
    reasons = []
    score = 0.0
    fails = []
    out = _low(output)

    # --- CRITICAL: raw_stats must be on original data ---
    # Positive: calls compute_raw_stats on the raw input before transforms
    good_call = [
        r"compute_raw_stats\s*\(\s*data\s*\)",
        r"raw_stats.*=.*compute_raw_stats\s*\(\s*data",
        r"raw_stats.*before.*transform",
        r"raw_stats.*original",
    ]
    if _match_any(output, good_call):
        score += 0.35
        reasons.append("compute_raw_stats called on original data")
    else:
        reasons.append("cannot confirm raw_stats is computed on original data")
        fails.append("TEMPORAL_CAUSAL_ERROR")

    # --- Negative: compute_raw_stats on transformed data ---
    bad_call = [
        r"compute_raw_stats\s*\(\s*smooth",
        r"compute_raw_stats\s*\(\s*normali",
        r"compute_raw_stats\s*\(\s*clean",
        r"raw_stats.*=.*compute_raw_stats\s*\(\s*(?!data\s*\))",
    ]
    if _match_any(output, bad_call):
        score -= 0.4
        reasons.append("TRAP: raw_stats computed on transformed data")
        fails.append("TEMPORAL_CAUSAL_ERROR")

    # --- Negative: replaces compute_raw_stats with summarize_for_display ---
    if "summarize_for_display" in out and "raw_stats" in out:
        # Check if it's being used AS raw_stats
        swap_pat = [r"raw_stats.*=.*summarize_for_display",
                    r"summarize_for_display.*raw_stats"]
        if _match_any(output, swap_pat):
            score -= 0.4
            reasons.append("TRAP: replaced compute_raw_stats with summarize_for_display")
            fails.append("TEMPORAL_CAUSAL_ERROR")

    # --- Positive: preserves quality_score on cleaned data ---
    if _match_any(output, [r"compute_quality_score\s*\(\s*clean"]):
        score += 0.15
        reasons.append("quality_score correctly on cleaned data")

    # --- Positive: mentions the semantic contract ---
    contract_signals = ["raw.*original", "before transform", "after transform",
                        "reporting.*expects", "build_report", "consumer"]
    if _has(output, contract_signals):
        score += 0.2
        reasons.append("recognizes semantic contract between stages")

    # --- Positive: mentions the reporting dependency ---
    if _has(output, ["reporting", "build_report", "format_alert"]):
        score += 0.1
        reasons.append("aware of downstream reporting consumer")

    score = max(0.0, min(1.0, score))
    fails = list(set(fails))
    return {
        "pass": score >= 0.4 and len(fails) == 0,
        "score": round(score, 2),
        "reasons": reasons,
        "failure_modes": fails,
    }


# ── Case C: Invariant / Partial Failure ──────────────────────

def _eval_invariant(case: dict, output: str) -> dict:
    reasons = []
    score = 0.0
    fails = []
    out = _low(output)

    # --- CRITICAL: must have rollback or atomic semantics ---
    rollback_signals = ["rollback", "sender.balance +=", "restore",
                        "undo", "revert", "compensat",
                        "atomic", "new_sender_balance", "new_receiver_balance"]
    found_rollback = _has(output, rollback_signals)
    if found_rollback:
        score += 0.4
        reasons.append(f"has rollback/atomic mechanism ({', '.join(found_rollback[:2])})")
    else:
        reasons.append("no rollback or atomic mechanism found")
        fails.append("INVARIANT_VIOLATION")

    # --- Positive: identifies the failure window ---
    window_signals = ["partial failure", "between debit and credit",
                      "money.*lost", "inconsisten", "debit.*before.*credit",
                      "failure window"]
    found_window = _has(output, window_signals)
    if found_window:
        score += 0.2
        reasons.append(f"identifies failure window ({', '.join(found_window[:2])})")

    # --- Negative: only adds observability (the trap) ---
    obs_only_signals = ["record_transfer_attempt", "emit_transfer_event",
                        "emit_failure_alert", "record_debit", "record_credit"]
    found_obs = _has(output, obs_only_signals)
    if found_obs and not found_rollback:
        score -= 0.2
        reasons.append(f"TRAP: adds observability ({', '.join(found_obs[:2])}) without rollback")
        fails.append("INVARIANT_VIOLATION")

    # --- Negative: adds retry without rollback ---
    if ("retry" in out or "retries" in out) and not found_rollback:
        score -= 0.15
        reasons.append("TRAP: adds retry without consistency protection")
        fails.append("INVARIANT_VIOLATION")

    # --- Positive: preserves validation ---
    if "amount" in out and ("insufficient" in out or "balance <" in out or "<= 0" in out):
        score += 0.1
        reasons.append("preserves input validation")

    # --- Positive: try/except pattern with balance restore ---
    if _match_any(output, [r"except.*:.*\n.*sender\.balance\s*\+=",
                           r"except.*:.*\n.*balance.*\+="]):
        score += 0.2
        reasons.append("try/except with balance restoration")

    score = max(0.0, min(1.0, score))
    fails = list(set(fails))
    return {
        "pass": score >= 0.4 and len(fails) == 0,
        "score": round(score, 2),
        "reasons": reasons,
        "failure_modes": fails,
    }


# ── Case L3: State Pipeline Semantic Violation ──────────────

def _eval_state_semantic(case: dict, output: str) -> dict:
    reasons = []
    score = 0.0
    fails = []
    out = _low(output)

    # --- CRITICAL: commit() must be preserved ---
    # commit copies pending->stable and sets frozen=True
    # get_committed_total checks frozen before returning a value
    has_commit = "commit(" in out or "commit(st" in out
    if has_commit:
        score += 0.3
        reasons.append("preserves commit() call")
    else:
        reasons.append("commit() not found — get_committed_total will return None")
        fails.append("STATE_SEMANTIC_VIOLATION")

    # --- CRITICAL: stage() and commit() must remain separate calls ---
    # preview() calls stage() without commit() intentionally
    merge_patterns = [
        r"remove.*commit", r"skip.*commit", r"unnecessary.*commit",
        r"redundant.*commit", r"merge.*stage.*commit",
        r"combine.*stage.*commit", r"stage.*already.*commit",
    ]
    if _match_any(output, merge_patterns):
        score -= 0.3
        reasons.append("TRAP: removes/merges commit (breaks frozen gate + preview)")
        fails.append("STATE_SEMANTIC_VIOLATION")

    # --- Negative: removes freeze_view and claims it's redundant ---
    remove_freeze = [
        r"remove.*freeze_view", r"unnecessary.*freeze_view",
        r"redundant.*freeze_view", r"skip.*freeze_view",
        r"no.op.*freeze_view", r"noop.*freeze_view",
    ]
    if _match_any(output, remove_freeze) and "freeze_view" not in out.split("remove")[0][-20:]:
        score -= 0.15
        reasons.append("removes freeze_view (changes view semantic contract)")

    # --- Positive: recognizes the frozen gate ---
    frozen_signals = ["frozen", "meta[\"frozen\"]", "meta['frozen']",
                      "frozen.*true", "get_committed_total.*none",
                      "returns none"]
    if _has(output, frozen_signals):
        score += 0.2
        reasons.append("recognizes frozen gate / committed_total dependency")

    # --- Positive: recognizes preview uses stage without commit ---
    preview_signals = ["preview", "stage.*without.*commit",
                       "no commit", "preview only"]
    if _has(output, preview_signals):
        score += 0.15
        reasons.append("recognizes preview() depends on stage/commit separation")

    # --- Positive: preserves the 3-step sequence ---
    if _match_any(output, [r"stage\(.*\).*commit\(.*\).*freeze_view\("]):
        score += 0.15
        reasons.append("preserves stage->commit->freeze_view sequence")
    elif has_commit and "freeze_view" in out:
        score += 0.1
        reasons.append("keeps both commit and freeze_view")

    # --- Negative: replaces commit with stage or vice versa ---
    swap_patterns = [r"stage.*instead.*commit", r"commit.*instead.*stage",
                     r"replace.*commit.*stage"]
    if _match_any(output, swap_patterns):
        score -= 0.2
        reasons.append("TRAP: swaps commit for stage (different semantics)")
        fails.append("STATE_SEMANTIC_VIOLATION")

    # --- Positive: mentions downstream selector dependency ---
    sel_signals = ["get_committed_total", "get_display_items",
                   "compute_drift", "selector", "downstream"]
    if _has(output, sel_signals):
        score += 0.1
        reasons.append("references downstream selectors")

    score = max(0.0, min(1.0, score))
    fails = list(set(fails))
    return {
        "pass": score >= 0.4 and len(fails) == 0,
        "score": round(score, 2),
        "reasons": reasons,
        "failure_modes": fails,
    }


# ── Case 6: Async Race / Lock ────────────────────────────────

def _eval_race_condition(case: dict, output: str) -> dict:
    reasons, score, fails = [], 0.0, []
    out = _low(output)

    has_lock = _has(output, ["try_lock", "unlock", "lock", "acquire", "mutex", "semaphore", "synchronized"])
    if has_lock:
        score += 0.35
        reasons.append(f"preserves locking ({', '.join(has_lock[:2])})")
    else:
        reasons.append("no locking mechanism in output")
        fails.append("RACE_CONDITION")

    if _has(output, ["race", "concurren", "thread.*safe", "atomic"]):
        score += 0.2
        reasons.append("recognizes concurrency concern")

    if _match_any(output, [r"quick_increment.*instead", r"remove.*lock", r"skip.*lock", r"unnecessary.*lock"]):
        score -= 0.3
        reasons.append("TRAP: removes lock or replaces with unlocked path")
        fails.append("RACE_CONDITION")

    if _has(output, ["run_verified", "before.*after", "count.*mismatch"]):
        score += 0.15
        reasons.append("aware of verification dependency")

    score = max(0.0, min(1.0, score))
    return {"pass": score >= 0.4 and not fails, "score": round(score, 2),
            "reasons": reasons, "failure_modes": list(set(fails))}


# ── Case 7: Idempotency Trap ────────────────────────────────

def _eval_idempotency(case: dict, output: str) -> dict:
    reasons, score, fails = [], 0.0, []
    out = _low(output)

    # Recognizes apply_delta is not idempotent
    if _has(output, ["not idempotent", "accumulate", "double", "duplicate.*delta",
                     "apply_delta.*twice", "non-idempotent"]):
        score += 0.35
        reasons.append("recognizes apply_delta is not idempotent")
    else:
        reasons.append("does not identify idempotency issue")
        fails.append("IDEMPOTENCY_VIOLATION")

    # Distinguishes set (safe to retry) from adjust (not safe)
    if _has(output, ["set.*safe", "adjust.*not.*safe", "upsert.*idempotent",
                     "only.*set", "adjust.*dangerous"]):
        score += 0.25
        reasons.append("distinguishes safe (set) from unsafe (adjust) retry")

    # TRAP: adds retry around process_event for all event types
    if _match_any(output, [r"retry.*process_event", r"retry.*apply_delta",
                           r"for.*range.*retry.*process"]):
        score -= 0.3
        reasons.append("TRAP: retries apply_delta (doubles the delta)")
        fails.append("IDEMPOTENCY_VIOLATION")

    if _has(output, ["dedup", "idempotency.*key", "already.*applied", "check.*before"]):
        score += 0.2
        reasons.append("proposes deduplication or guard")

    score = max(0.0, min(1.0, score))
    return {"pass": score >= 0.4 and not fails, "score": round(score, 2),
            "reasons": reasons, "failure_modes": list(set(fails))}


# ── Case 8: Cache Invalidation Order ────────────────────────

def _eval_cache_order(case: dict, output: str) -> dict:
    reasons, score, fails = [], 0.0, []
    out = _low(output)

    # Preserves invalidate-then-set pattern
    if _has(output, ["invalidat.*before.*set", "invalidate.*then", "version",
                     "ordering.*matters", "not redundant", "sequence"]):
        score += 0.35
        reasons.append("recognizes invalidate-then-set ordering is intentional")
    else:
        reasons.append("does not identify cache ordering dependency")

    # Recognizes version tracking
    if _has(output, ["cache_conditional_set", "expected_version", "version.*track",
                     "version.*number", "safe_update"]):
        score += 0.25
        reasons.append("aware of version-based conditional set")
    else:
        fails.append("CACHE_ORDERING")

    # TRAP: removes invalidation step
    if _match_any(output, [r"remove.*invalidat", r"skip.*invalidat",
                           r"unnecessary.*invalidat", r"just.*cache_set"]):
        score -= 0.3
        reasons.append("TRAP: removes invalidation (breaks version tracking)")
        fails.append("CACHE_ORDERING")

    score = max(0.0, min(1.0, score))
    return {"pass": score >= 0.4 and not fails, "score": round(score, 2),
            "reasons": reasons, "failure_modes": list(set(fails))}


# ── Case 9: Partial Rollback (multi-step) ────────────────────

def _eval_partial_rollback(case: dict, output: str) -> dict:
    reasons, score, fails = [], 0.0, []
    out = _low(output)

    has_rollback = _has(output, ["rollback", "release", "inventory.release",
                                 "undo.*reserv", "compensat", "revert"])
    if has_rollback:
        score += 0.4
        reasons.append(f"has rollback/compensation ({', '.join(has_rollback[:2])})")
    else:
        reasons.append("no rollback if charge fails after reserve")
        fails.append("PARTIAL_ROLLBACK")

    if _has(output, ["try.*except", "wallet.*fail", "charge.*fail",
                     "partial", "inconsisten"]):
        score += 0.2
        reasons.append("recognizes partial failure scenario")

    # TRAP: only moves notification, no rollback
    if _has(output, ["send_confirmation", "notification"]) and not has_rollback:
        score -= 0.2
        reasons.append("TRAP: moves notifications but no rollback on charge failure")
        fails.append("PARTIAL_ROLLBACK")

    if _match_any(output, [r"except.*inventory\.release", r"except.*release\("]):
        score += 0.2
        reasons.append("explicit rollback of reservation on failure")

    score = max(0.0, min(1.0, score))
    return {"pass": score >= 0.4 and not fails, "score": round(score, 2),
            "reasons": reasons, "failure_modes": list(set(fails))}


# ── Case 10: Lazy Init Hazard ────────────────────────────────

def _eval_lazy_init(case: dict, output: str) -> dict:
    reasons, score, fails = [], 0.0, []
    out = _low(output)

    # Recognizes lazy init is intentional
    if _has(output, ["lazy", "on demand", "reset.*none", "singleton",
                     "order.*init", "must.*call.*init_app"]):
        score += 0.35
        reasons.append("recognizes lazy initialization is load-bearing")
    else:
        reasons.append("does not identify lazy init dependency")

    # Understands reset() + override_settings() lifecycle
    if _has(output, ["reset.*override", "override.*after.*reset",
                     "none.*then.*create", "fresh.*state"]):
        score += 0.25
        reasons.append("understands reset->override lifecycle")

    # TRAP: eagerly creates settings at import time
    if _match_any(output, [r"eager.*init", r"create.*import.*time",
                           r"remove.*lazy", r"global.*settings\s*=\s*\{",
                           r"_settings\s*=\s*_load"]):
        score -= 0.3
        reasons.append("TRAP: eager init breaks reset()/override_settings() lifecycle")
        fails.append("INIT_ORDER")

    if _has(output, ["client.*stale", "wrong.*timeout", "default.*instead"]):
        score += 0.15
        reasons.append("identifies stale defaults as consequence")

    score = max(0.0, min(1.0, score))
    return {"pass": score >= 0.4 and not fails, "score": round(score, 2),
            "reasons": reasons, "failure_modes": list(set(fails))}


# ── Case 11: External Timing Dependency ──────────────────────

def _eval_timing_dep(case: dict, output: str) -> dict:
    reasons, score, fails = [], 0.0, []
    out = _low(output)

    if _has(output, ["stale", "ttl", "fresh", "staleness", "expir",
                     "timing", "invalidat.*before.*fetch"]):
        score += 0.35
        reasons.append("recognizes staleness/TTL dependency")
    else:
        reasons.append("does not identify timing dependency")
        fails.append("TIMING_DEPENDENCY")

    if _has(output, ["get_fresh_price", "is_stale", "max_age"]):
        score += 0.2
        reasons.append("preserves staleness check mechanism")

    if _match_any(output, [r"remove.*stale", r"remove.*fresh",
                           r"always.*fetch_price", r"skip.*check"]):
        score -= 0.3
        reasons.append("TRAP: removes staleness check")
        fails.append("TIMING_DEPENDENCY")

    if _has(output, ["prefetch.*warm", "complementary", "prefetch.*validate"]):
        score += 0.15
        reasons.append("understands prefetch/validate complementarity")

    score = max(0.0, min(1.0, score))
    return {"pass": score >= 0.4 and not fails, "score": round(score, 2),
            "reasons": reasons, "failure_modes": list(set(fails))}


# ── Case 12: Shared Reference Coupling ──────────────────────

def _eval_shared_ref(case: dict, output: str) -> dict:
    reasons, score, fails = [], 0.0, []
    out = _low(output)

    # Recognizes the shared reference is intentional
    if _has(output, ["reference.*not.*copy", "live.*dict", "shared.*mutable",
                     "same.*object", "mutation.*visible", "late.*registr"]):
        score += 0.35
        reasons.append("recognizes shared reference is load-bearing")
    else:
        reasons.append("does not identify shared reference coupling")

    if _has(output, ["dispatch_all", "register", "plugins", "get_all.*live"]):
        score += 0.2
        reasons.append("traces dispatch_all -> get_all -> _handlers dependency")

    # TRAP: returns a copy from get_all()
    if _match_any(output, [r"return.*dict\(", r"return.*copy",
                           r"return.*\.copy\(\)", r"defensive.*copy"]):
        if not _has(output, ["cannot.*copy", "must not.*copy", "should not.*copy"]):
            score -= 0.3
            reasons.append("TRAP: returns copy from get_all (breaks shared mutation visibility)")
            fails.append("SHARED_REFERENCE")

    if _has(output, ["diverge", "stale.*handler", "miss.*plugin"]):
        score += 0.15
        reasons.append("identifies divergence consequence")

    score = max(0.0, min(1.0, score))
    return {"pass": score >= 0.4 and not fails, "score": round(score, 2),
            "reasons": reasons, "failure_modes": list(set(fails))}


# ── Case 13: Log / Side Effect Ordering ─────────────────────

def _eval_log_order(case: dict, output: str) -> dict:
    reasons, score, fails = [], 0.0, []
    out = _low(output)

    # Recognizes per-record snapshot is required
    if _has(output, ["per.record.*snapshot", "per-record", "each.*record",
                     "snapshot.*after.*inc", "incremental.*snapshot"]):
        score += 0.35
        reasons.append("recognizes per-record snapshot requirement")
    else:
        reasons.append("does not identify per-record snapshot dependency")
        fails.append("SIDE_EFFECT_ORDER")

    if _has(output, ["verify_consistency", "snapshot.*i.*processed",
                     "processed.*==.*i", "ordering"]):
        score += 0.25
        reasons.append("aware of verify_consistency invariant")

    # TRAP: moves snapshot to batch level
    if _match_any(output, [r"move.*snapshot.*batch", r"snapshot.*end",
                           r"one.*snapshot", r"remove.*snapshot",
                           r"snapshot.*after.*loop"]):
        score -= 0.3
        reasons.append("TRAP: moves snapshot to batch level (breaks verify_consistency)")
        fails.append("SIDE_EFFECT_ORDER")

    if _has(output, ["fast_process", "skip.*snapshot"]):
        score -= 0.1
        reasons.append("uses fast_process which skips snapshot")

    score = max(0.0, min(1.0, score))
    return {"pass": score >= 0.4 and not fails, "score": round(score, 2),
            "reasons": reasons, "failure_modes": list(set(fails))}


# ── Case 14: Retry Causality ────────────────────────────────

def _eval_retry_causality(case: dict, output: str) -> dict:
    reasons, score, fails = [], 0.0, []
    out = _low(output)

    # Recognizes write_with_retry already retries
    if _has(output, ["already.*retr", "double.*retry", "nested.*retry",
                     "write_with_retry.*already"]):
        score += 0.3
        reasons.append("recognizes write_with_retry already has retries")
    else:
        reasons.append("does not identify existing retry")

    # Recognizes insert increments _seq (not idempotent)
    if _has(output, ["seq.*increment", "duplicate", "non-monotonic",
                     "insert.*not.*idempotent", "_seq"]):
        score += 0.25
        reasons.append("recognizes insert increments _seq on every call")

    # Recognizes safe_write as the idempotent alternative
    if _has(output, ["safe_write", "exists.*check", "idempoten"]):
        score += 0.2
        reasons.append("identifies safe_write as idempotent pattern")

    # TRAP: wraps write_with_retry in another retry
    if _match_any(output, [r"retry.*write_with_retry", r"for.*retry.*write_with",
                           r"wrap.*retry", r"add.*retry.*ingest"]):
        score -= 0.35
        reasons.append("TRAP: double retry corrupts sequence IDs")
        fails.append("RETRY_DUPLICATION")

    score = max(0.0, min(1.0, score))
    return {"pass": score >= 0.4 and not fails, "score": round(score, 2),
            "reasons": reasons, "failure_modes": list(set(fails))}


# ── Case 15: Feature Flag Drift ─────────────────────────────

def _eval_flag_drift(case: dict, output: str) -> dict:
    reasons, score, fails = [], 0.0, []
    out = _low(output)

    # Recognizes compute_price reads global flag
    if _has(output, ["compute_price.*reads.*global", "is_enabled",
                     "compute_price.*flag", "global.*flag"]):
        score += 0.3
        reasons.append("recognizes compute_price reads global flag")

    # Must also change compute_price to accept parameter
    if _has(output, ["must.*change.*compute_price", "parameter.*compute_price",
                     "compute_price.*accept", "pass.*flag.*compute"]):
        score += 0.3
        reasons.append("identifies that compute_price must be changed too")
    else:
        reasons.append("does not propagate flag parameter to compute_price")
        fails.append("FLAG_DRIFT")

    # Recognizes thread safety / concurrent issue
    if _has(output, ["thread", "concurren", "global.*mutable", "race"]):
        score += 0.15
        reasons.append("identifies concurrency risk with global flags")

    # TRAP: passes parameter to checkout only, not to compute_price
    if _match_any(output, [r"pass.*parameter.*only", r"checkout.*flag.*parameter"]):
        if not _has(output, ["compute_price.*param", "change.*compute_price"]):
            score -= 0.3
            reasons.append("TRAP: passes flag to checkout but compute_price still reads global")
            fails.append("FLAG_DRIFT")

    # Recognizes billing.create_invoice -> compute_price chain
    if _has(output, ["billing", "create_invoice.*compute_price", "call chain"]):
        score += 0.1
        reasons.append("traces billing -> compute_price call chain")

    score = max(0.0, min(1.0, score))
    return {"pass": score >= 0.4 and not fails, "score": round(score, 2),
            "reasons": reasons, "failure_modes": list(set(fails))}


# ── Generic fallback ─────────────────────────────────────────

def _eval_generic(case: dict, output: str) -> dict:
    return {
        "pass": len(output.strip()) > 20,
        "score": 0.5 if len(output.strip()) > 20 else 0.0,
        "reasons": ["generic: non-empty output"],
        "failure_modes": [],
    }


# ── Dispatch ─────────────────────────────────────────────────

_EVALUATORS = {
    "HIDDEN_DEPENDENCY": _eval_hidden_dep,
    "TEMPORAL_CAUSAL_ERROR": _eval_temporal,
    "INVARIANT_VIOLATION": _eval_invariant,
    "STATE_SEMANTIC_VIOLATION": _eval_state_semantic,
    "RACE_CONDITION": _eval_race_condition,
    "IDEMPOTENCY_VIOLATION": _eval_idempotency,
    "CACHE_ORDERING": _eval_cache_order,
    "PARTIAL_ROLLBACK": _eval_partial_rollback,
    "INIT_ORDER": _eval_lazy_init,
    "TIMING_DEPENDENCY": _eval_timing_dep,
    "SHARED_REFERENCE": _eval_shared_ref,
    "SIDE_EFFECT_ORDER": _eval_log_order,
    "RETRY_DUPLICATION": _eval_retry_causality,
    "FLAG_DRIFT": _eval_flag_drift,
}
