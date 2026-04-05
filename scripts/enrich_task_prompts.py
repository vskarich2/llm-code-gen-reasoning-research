"""Enrich split case files with enriched_task_prompt and enriched_task_prompt_justification.

Processes every JSON file in case_data/cases_split/, analyzes the buggy code,
fixed code, test output, and difficulty, then writes calibrated task prompts.

Run: .venv/bin/python scripts/enrich_task_prompts.py
"""

import json
from pathlib import Path

SPLIT_DIR = Path("case_data/cases_split")


# ============================================================
# ENRICHMENTS — hand-authored per case, grounded in evidence
# ============================================================

ENRICHMENTS = {
    # ── ALIAS_CONFIG ──
    "alias_config_a": {
        "enriched_task_prompt": (
            "The create_config function in config.py returns a configuration dictionary based on DEFAULTS. "
            "However, when one caller modifies the returned config (e.g., setting timeout=5), subsequent callers "
            "also see that modification — config values are leaking between callers. "
            "Update create_config so that each caller receives an independent configuration dictionary. "
            "Preserve the existing public API and default values. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Refactor this configuration module for clarity') was too vague — it gave no "
            "symptom information at all. The failing test output shows 'mutation leaked: cfg2[timeout]=5, expected 30', "
            "confirming that config dicts returned by create_config share state. The rewritten prompt names the "
            "observable symptom (values leaking between callers) and the affected function (create_config), which "
            "is appropriate for difficulty A — the model should be able to localize the bug quickly given the "
            "function name and behavioral description. It withholds the specific fix (DEFAULTS.copy()) and does not "
            "name the aliasing mechanism. The prompt anchors the model to the real failure without trivializing diagnosis."
        ),
    },
    "alias_config_b": {
        "enriched_task_prompt": (
            "After changing configuration values and calling get_settings, the returned settings still reflect "
            "stale or mutated data from previous calls. The config loading involves create_config, get_settings, "
            "and merge_overrides. Identify why configuration state persists incorrectly between calls and fix it. "
            "Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task mentioned 'stale data' and 'simplify the config loading', which was somewhat "
            "on target but added a misleading instruction to simplify. The failing output is 'mutation leaked: "
            "cfg2[timeout]=5, expected 30'. The rewritten prompt describes the symptom (stale/mutated data persisting "
            "across calls) and mentions the three relevant functions without indicating which one is buggy — "
            "appropriate for difficulty B where the model must inspect interactions. merge_overrides is mentioned "
            "as context because it's the trap (it correctly copies, tempting the model to look there instead of "
            "create_config). The prompt does not reveal that create_config is the source of aliasing."
        ),
    },
    "alias_config_c": {
        "enriched_task_prompt": (
            "Requests served by the middleware are seeing configuration values from previous requests. "
            "For example, a debug override applied during one request persists into the next. "
            "The system involves config.py, middleware.py, and handler.py. Fix the configuration flow "
            "so that each request gets a clean configuration. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Requests are seeing config from previous requests. Simplify the config flow.') "
            "was reasonable but added a misleading 'simplify' instruction. The failing output is "
            "'debug override leaked: r2[debug]=True, expected False'. The rewritten prompt describes the "
            "cross-request leakage symptom and lists all three files without indicating which one has the bug. "
            "For difficulty C, the model must trace the config flow across middleware → config → handler to find "
            "that create_config returns DEFAULTS by reference. The trap (merge_overrides correctly copies) is "
            "not mentioned, preserving the search difficulty. The prompt is fair — it describes the exact symptom — "
            "but requires genuine cross-file tracing."
        ),
    },

    # ── EARLY_RETURN ──
    "early_return_a": {
        "enriched_task_prompt": (
            "The process_payment function in payment.py processes payments and records them in a ledger. "
            "After processing two payments (including one with amount=0), verify_ledger reports that "
            "not all payments were recorded. Update the implementation so that every call to "
            "process_payment results in a ledger entry, regardless of the payment amount. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Refactor this payment processor for clarity') gave no symptom. "
            "The failing output is 'verify_ledger(2) returned False — zero-amount payment not recorded'. "
            "The rewritten prompt describes the exact observable failure (ledger count mismatch after "
            "zero-amount payment) and names the affected function and invariant. For difficulty A, this "
            "directly points the model to the early-return path without naming it as an 'early return' bug. "
            "It withholds the specific code path (the if-amount-zero branch) but the symptom makes the "
            "issue locatable."
        ),
    },
    "early_return_b": {
        "enriched_task_prompt": (
            "Ledger record counts do not match the number of calls to process_payment. Specifically, when "
            "a duplicate transaction is processed, the ledger is missing an entry. The system involves "
            "payment.py and ledger.py. Fix the recording so that every call produces a ledger entry. "
            "Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Ledger counts don't match transaction count') was close but did not "
            "mention the duplicate-transaction path. The failing output is 'verify(3) returned False — "
            "duplicate transaction not recorded in ledger'. The rewritten prompt names the symptom "
            "(missing entry on duplicate) and the two files involved. For difficulty B, the model must "
            "trace the duplicate-detection path to find that the early return skips ledger.record(). "
            "The trap (ledger.get_summary handles missing entries gracefully) is not mentioned, preserving "
            "the need to inspect both files."
        ),
    },
    "early_return_c": {
        "enriched_task_prompt": (
            "The audit log is incomplete — cached charges are not being recorded. After three calls to "
            "charge() (including one that hits the cache), verify_completeness reports missing entries. "
            "The system involves payment.py, ledger.py, and audit.py. Fix the implementation so that "
            "the audit trail is complete for every charge call. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Audit log missing entries for cached charges') was accurate but brief. "
            "The failing output is 'verify_completeness(3) returned False — cached charge not recorded'. "
            "The rewritten prompt describes the symptom and mentions three files. For difficulty C, the "
            "model must trace the cache-hit path through charge() across multiple modules. The prompt "
            "does not reveal that the caching is correct and only the audit call is missing — that's the "
            "key diagnostic insight the model must reach independently."
        ),
    },

    # ── EFFECT_ORDER ──
    "effect_order_a": {
        "enriched_task_prompt": (
            "The process_batch function in processor.py processes a list of items and takes snapshots. "
            "After processing 3 items, only 1 snapshot exists instead of 3. Update the implementation "
            "so that one snapshot is created per item processed. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Refactor this event processor for clarity') gave no symptom. "
            "The failing output is 'expected 3 snapshots (one per item), got 1'. The rewritten prompt "
            "names the function, the count mismatch, and the expected invariant. For difficulty A, "
            "this clearly localizes the issue to the snapshot placement within process_batch."
        ),
    },
    "effect_order_b": {
        "enriched_task_prompt": (
            "After processing a batch of items, the event count does not match the item count — "
            "only 1 event is emitted for a batch of 3 items. The system uses processor.py and metrics.py. "
            "Fix the event emission so that one event is produced per item. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Event counts don't match items processed') was accurate. "
            "The failing output is 'expected 3 events (one per item), got 1'. The rewritten prompt "
            "describes the symptom and mentions both files. For difficulty B, the trap is that "
            "batch-level emission looks like a performance optimization. The prompt does not reveal "
            "whether the issue is in processor.py or metrics.py."
        ),
    },
    "effect_order_c": {
        "enriched_task_prompt": (
            "The audit log has fewer entries than items processed in a batch. After processing 3 items, "
            "only 1 audit entry exists. The system involves processor.py, metrics.py, and audit.py. "
            "Fix the implementation to produce one audit entry per item. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Audit log has fewer entries than items') was accurate. "
            "The failing output is 'expected 3 audit entries (one per item), got 1'. For difficulty C, "
            "the trap is that fast_process legitimately batches operations on a different path, making "
            "batch-level auditing look intentional. The prompt mentions three files without indicating "
            "which path is wrong."
        ),
    },

    # ── INDEX_MISALIGN ──
    "index_misalign_a": {
        "enriched_task_prompt": (
            "The report builder's add_entry function in report.py inserts labels and values, but after "
            "inserting at position 0, the label-value pairs are misaligned — get_entry(0) returns "
            "the wrong value for the label. Fix add_entry so that labels and values stay correctly paired "
            "after insertion at any position. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task was a generic refactor prompt. The failing output is "
            "'get_entry(0) returned (gamma, 10), expected (gamma, 30)'. The rewritten prompt "
            "names the function, the operation (insert at position), and the observable mismatch. "
            "For difficulty A, this directly points to the parallel-array insertion inconsistency."
        ),
    },
    "index_misalign_b": {
        "enriched_task_prompt": (
            "After deleting a column from the report, row data is misaligned with column headers. "
            "For example, after deleting the 'age' column, the 'city' column shows numeric values "
            "instead of city names. The system involves report.py and data.py. Fix the column deletion "
            "so that headers and row data remain aligned. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Report columns are misaligned after deletion') was accurate. "
            "The failing output is 'After deleting age column, first row city is 30, expected NYC'. "
            "For difficulty B, the trap is that render looks correct in isolation — the model must "
            "trace delete_column to see it removes the header but not the row data."
        ),
    },
    "index_misalign_c": {
        "enriched_task_prompt": (
            "Report formatting breaks after inserting a new column — the validation reports a mismatch "
            "between header count and column width count. The system involves report.py, data.py, and "
            "formatter.py. Fix the implementation so that all parallel structures stay consistent after "
            "column insertion. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Report formatting breaks after inserting column') was accurate. "
            "The failing output is 'validate() failed: header/width count mismatch'. For difficulty C, "
            "the model must find that insert_column updates headers and rows but not column_widths, "
            "and that recalculate_widths exists but is not called. The prompt mentions three files "
            "without indicating which structure is out of sync."
        ),
    },

    # ── LAZY_INIT ──
    "lazy_init_a": {
        "enriched_task_prompt": (
            "The get_host and get_timeout functions in service.py return stale configuration values after "
            "reset_settings is called. For example, after resetting and updating the host to 'prod.example.com', "
            "get_host still returns 'localhost'. Fix the implementation so that configuration changes "
            "take effect immediately. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task was a generic refactor prompt. The failing output is "
            "'get_host() returned stale value: localhost, expected prod.example.com'. "
            "The rewritten prompt describes the exact stale-value symptom and names the affected "
            "functions. For difficulty A, this clearly localizes the issue to how settings values "
            "are captured. It withholds the specific mechanism (eager capture at module level)."
        ),
    },
    "lazy_init_b": {
        "enriched_task_prompt": (
            "After resetting configuration, the client module still uses the old timeout value. "
            "The system involves config.py and client.py. Fix the implementation so that "
            "config resets propagate to the client. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('After resetting config, client still uses old timeout') was accurate. "
            "The failing output is 'get_timeout() returned stale value: 30, expected 99'. "
            "For difficulty B, the model must trace how client.py captures config values and determine "
            "that the capture happens at import time. The prompt names both files but does not reveal "
            "which file has the bug or how the value is captured."
        ),
    },
    "lazy_init_c": {
        "enriched_task_prompt": (
            "Configuration reset does not propagate through the system. After resetting, both the "
            "API key and base URL still reflect old values. The system involves config.py, client.py, "
            "and handler.py. Fix the implementation so that resets propagate correctly. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Config reset doesn't propagate through client to handler') was accurate "
            "but named the propagation chain too directly. The failing output shows 'api_key stale: "
            "default-key, expected new-secret-key; base_url stale'. For difficulty C, the model must "
            "trace the config→client→handler chain to find where values are captured eagerly. The trap "
            "(client.refresh() exists but handler doesn't call it) is not mentioned. The prompt "
            "describes the symptom without naming the propagation chain direction."
        ),
    },

    # ── MISSING_BRANCH ──
    "missing_branch_a": {
        "enriched_task_prompt": (
            "The get_permissions function in permissions.py handles admin and user roles, but moderator "
            "users receive empty permissions instead of their expected set. Update the access control "
            "so that moderator users receive appropriate permissions. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task was a generic refactor prompt. The failing output is "
            "'moderator got empty permissions, expected non-empty set'. The rewritten prompt "
            "names the function, the missing role, and the expected behavior. For difficulty A, "
            "this directly localizes the missing branch."
        ),
    },
    "missing_branch_b": {
        "enriched_task_prompt": (
            "Guest users receive no access at all — not even read access — despite being a valid role. "
            "The system uses auth.py and roles.py. Fix the role dispatch so that guest users "
            "receive their expected read-only permissions. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Guest users get no access. Fix the role dispatch.') was accurate. "
            "The failing output is 'guest has no read access, expected read-only'. For difficulty B, "
            "the trap is that validate_role exists but only checks format. The prompt names both files "
            "without revealing that the dispatch dict is missing the guest entry."
        ),
    },
    "missing_branch_c": {
        "enriched_task_prompt": (
            "Service accounts are being denied access even though middleware recognizes and accepts them. "
            "The system involves auth.py, middleware.py, and roles.py. Fix the authorization so that "
            "service accounts receive read and write access but not admin access. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Service accounts denied despite middleware allowing') was accurate. "
            "The failing output is 'service_account got can_read=False, expected True'. The rewritten "
            "prompt specifies the exact expected permissions (read+write, not admin) which is critical — "
            "models consistently give can_admin=True. For difficulty C, the model must trace the "
            "middleware→auth boundary. The trap (fixing middleware only) is not mentioned. The "
            "permission spec is included because without it, models always over-grant."
        ),
    },

    # ── MUTABLE_DEFAULT ──
    "mutable_default_a": {
        "enriched_task_prompt": (
            "The enqueue function in queue.py accumulates items across calls. After calling enqueue "
            "twice with different tasks, the second call's queue contains items from the first call. "
            "Fix enqueue so that each call starts with a fresh queue. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task was a generic refactor prompt. The failing output is "
            "'second enqueue() leaked state: got 2 items, expected 1'. The rewritten prompt "
            "describes the accumulation symptom and names the function. For difficulty A, this "
            "clearly localizes the issue without naming the mutable default mechanism."
        ),
    },
    "mutable_default_b": {
        "enriched_task_prompt": (
            "Workers skip valid tasks on the second batch. After processing one batch, a subsequent "
            "call to process_batch skips tasks that were in the first batch. The system uses "
            "worker.py and queue.py. Fix the implementation so that each batch processes all its tasks "
            "independently. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Workers skip valid tasks on second batch') was accurate. "
            "The failing output is 'task_x skipped in second call due to stale seen set'. "
            "For difficulty B, the trap is that the seen set looks like a deduplication optimization. "
            "The prompt does not mention the seen set or its persistence mechanism."
        ),
    },
    "mutable_default_c": {
        "enriched_task_prompt": (
            "The scheduler's job history is shared across independently scheduled jobs. After scheduling "
            "one job, a subsequently scheduled job inherits history entries from the first. The system "
            "involves scheduler.py, worker.py, and queue.py. Fix the implementation so that each "
            "scheduled job has its own independent history. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Scheduler history is shared across jobs') was accurate. "
            "The failing output is 'schedule_batch history leaked from schedule_one'. "
            "For difficulty C, the bug is in a decorator closure that shares a mutable list. "
            "The prompt describes the symptom across three files without revealing the decorator "
            "or closure mechanism."
        ),
    },

    # ── PARTIAL_ROLLBACK ──
    "partial_rollback_a": {
        "enriched_task_prompt": (
            "The place_order function in order.py reserves inventory and then charges payment. "
            "When payment fails, the inventory remains reserved instead of being released. "
            "Fix place_order so that inventory is released on payment failure. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task was a generic refactor prompt. The failing output is "
            "'failure path: available=7, expected 10 (reservation not rolled back)'. "
            "For difficulty A, the prompt names the function and the exact failure path behavior."
        ),
    },
    "partial_rollback_b": {
        "enriched_task_prompt": (
            "Inventory gets stuck in a reserved state after a payment gateway failure. The system "
            "uses order_service.py and inventory.py. Fix the order flow so that inventory reservations "
            "are properly released when downstream operations fail. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Inventory stuck as reserved after payment failure') was accurate. "
            "The failing output is 'failure path: available=7, expected 10'. For difficulty B, "
            "the model must trace the order flow across two files. The trap (notifications list) "
            "is not mentioned."
        ),
    },
    "partial_rollback_c": {
        "enriched_task_prompt": (
            "After a payment gateway failure, both inventory and audit state are left in an inconsistent "
            "state — inventory remains reserved and an orphaned audit entry persists. The system involves "
            "order_service.py, inventory.py, and payment.py. Fix the implementation so that all side "
            "effects are properly cleaned up on failure. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Inventory and audit corrupted after payment failure') was accurate. "
            "The failing output shows both 'available=15, expected 20' and 'audit_log has 1 entries, "
            "expected 0'. For difficulty C, the model must handle multi-resource rollback across three "
            "files. The trap (retrying the gateway instead of rolling back) is not mentioned."
        ),
    },

    # ── PARTIAL_UPDATE ──
    "partial_update_a": {
        "enriched_task_prompt": (
            "The update_profile function in profile.py updates a user's name but does not update "
            "the display_name, which should always match the current name. Fix update_profile so that "
            "display_name stays synchronized after name changes. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task was a generic refactor prompt. The failing output is "
            "'display_name not synced: display_name=Alice, expected Bob'. For difficulty A, "
            "the prompt names the function and the exact desynchronization."
        ),
    },
    "partial_update_b": {
        "enriched_task_prompt": (
            "After updating a user's first name, the full_name field still shows the old value. "
            "The system uses profile.py and validation.py. Fix the profile update so that all "
            "derived fields stay consistent with their source fields. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Users report their full name not updating') was accurate. "
            "The failing output is 'full_name not synced: full_name=Alice Smith, expected Bob Smith'. "
            "For difficulty B, the trap is that validate_name exists but doesn't fix the sync. "
            "The prompt mentions 'derived fields' generally rather than naming full_name as the only one."
        ),
    },
    "partial_update_c": {
        "enriched_task_prompt": (
            "After changing a user's email, the verified flag still shows True and the cached greeting "
            "still shows the old email. The system involves profile.py, validation.py, and "
            "notifications.py. Fix the profile update so that all dependent state is correctly "
            "refreshed when primary fields change. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('After changing email, old greeting still shows') was partially accurate "
            "but missed the verified flag issue. The failing output is 'verified not reset: verified=True, "
            "expected False'. For difficulty C, the model must identify multiple unsynchronized dependent "
            "fields across three files. The trap (validate_email runs but doesn't update verified) is "
            "not mentioned."
        ),
    },

    # ── RETRY_DUP ──
    "retry_dup_a": {
        "enriched_task_prompt": (
            "The retry_send function in sender.py is producing duplicate messages. After sending one "
            "message successfully, the store contains 3 copies instead of 1. Fix the retry logic so "
            "that successful sends produce exactly one message. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task was a generic refactor prompt. The failing output is "
            "'success path: 3 messages, expected 1'. For difficulty A, the prompt names the "
            "function and the exact duplication count."
        ),
    },
    "retry_dup_b": {
        "enriched_task_prompt": (
            "Messages are appearing twice in the store after a successful send. Both the store entry "
            "and the notification are duplicated. The system uses sender.py and store.py. Fix the "
            "retry logic so that each successful send produces exactly one store entry and one "
            "notification. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Messages appearing twice in store') was accurate. "
            "The failing output shows both duplicate store entries and duplicate notifications. "
            "For difficulty B, the trap is that store.append is non-idempotent."
        ),
    },
    "retry_dup_c": {
        "enriched_task_prompt": (
            "Messages are appearing multiple times — sometimes 2, sometimes 4 copies. The system "
            "involves pipeline.py, sender.py, and store.py. Fix the retry logic across the pipeline "
            "so that each message is delivered exactly once. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Messages appearing 3-4 times') was accurate. "
            "The failing output is '2 messages, expected 1' at the pipeline level. For difficulty C, "
            "nested retry loops cause exponential duplication. The trap is that adding an outer "
            "retry makes it worse. The prompt does not reveal the nesting structure."
        ),
    },

    # ── SILENT_DEFAULT ──
    "silent_default_a": {
        "enriched_task_prompt": (
            "The is_enabled function in flags.py always returns False for the 'darkMode' flag, even "
            "though the flag 'dark_mode' is configured as True. Fix the flag lookup so that it "
            "returns the configured value. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task was a generic refactor prompt. The failing output is "
            "'is_enabled(darkMode) returned False. Flag dark_mode is True but camelCase lookup missed'. "
            "For difficulty A, the prompt gives both the lookup key and the stored key, making "
            "the naming mismatch clear without explicitly calling it a 'key mismatch' bug."
        ),
    },
    "silent_default_b": {
        "enriched_task_prompt": (
            "The analytics feature flag always reports as disabled despite being enabled in the "
            "configuration. The system uses flags.py and config.py. Fix the flag lookup so that "
            "is_analytics_enabled returns the correctly configured value. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Analytics flag always off despite being enabled') was accurate. "
            "The failing output is 'is_analytics_enabled() returned False. Config has "
            "feature.analytics.enabled=True'. For difficulty B, the model must trace the nested "
            "config traversal to find the wrong intermediate key. The trap (validate_config checks "
            "top-level only) is not mentioned."
        ),
    },
    "silent_default_c": {
        "enriched_task_prompt": (
            "A feature flag ignores its environment variable override and falls through to a hardcoded "
            "default. The system involves flags.py, config.py, and env.py. Fix the flag resolution "
            "so that environment variable overrides are respected. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Feature flag ignores env var override') was accurate. "
            "The failing output is 'get_flag_source(dark_mode) returned config, expected env'. "
            "For difficulty C, the model must trace the env→config→default fallback chain and find "
            "the env var key mismatch. The trap (fallback chain looks resilient) is not mentioned."
        ),
    },

    # ── STALE_CACHE ──
    "stale_cache_a": {
        "enriched_task_prompt": (
            "The get_product function in catalog.py returns stale prices after update_product is called. "
            "After updating a product's price to 25.0, get_product still returns 10.0. Fix the catalog "
            "so that reads always reflect the latest updates. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task was a generic refactor prompt. The failing output is "
            "'stale cache: price=10.0, expected 25.0'. For difficulty A, the prompt names "
            "both functions and the exact stale value."
        ),
    },
    "stale_cache_b": {
        "enriched_task_prompt": (
            "Products show old prices after updates. The system uses catalog.py and cache.py. "
            "After calling update_product with a new price, get_product still returns the old price. "
            "Fix the update flow so that subsequent reads return current data. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Products show old prices after updates') was accurate. "
            "The failing output is 'stale cache: price=10.0, expected 25.0'. For difficulty B, "
            "the trap is that cache.warm() exists but pre-populates from DB rather than invalidating."
        ),
    },
    "stale_cache_c": {
        "enriched_task_prompt": (
            "The API returns stale product data even after updates. The system involves catalog.py, "
            "cache.py, and api.py, with a two-layer caching architecture. Fix the caching so that "
            "updates are visible to all read paths. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('API returns stale product data despite updates') was accurate. "
            "The failing output is 'stale local cache: price=10.0, expected 50.0'. For difficulty C, "
            "the two-layer cache (local + shared) means invalidating one layer is insufficient. "
            "The prompt mentions the two-layer architecture as a legitimate hint from the code "
            "structure but does not reveal which layer is missed."
        ),
    },

    # ── TEMPORAL_DRIFT ──
    "temporal_drift_a": {
        "enriched_task_prompt": (
            "The pipeline function in pipeline.py computes raw statistics, but the reported raw_max "
            "is 1.0 instead of the expected 80. The raw statistics appear to be computed on normalized "
            "data rather than the original input. Fix the pipeline so that raw_stats operates on "
            "the original untransformed data. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task was a generic refactor prompt. The failing output is "
            "'raw_max=1.0, expected 80 (computed on normalized data instead of original)'. "
            "For difficulty A, the prompt names the function and the exact wrong value, "
            "making the temporal ordering issue clear."
        ),
    },
    "temporal_drift_b": {
        "enriched_task_prompt": (
            "Raw statistics show normalized values instead of actual values. The reported raw_max "
            "is 1.0 instead of the expected 500. The system uses pipeline.py and transforms.py. "
            "Fix the pipeline so that raw statistics reflect the original input data. "
            "Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Raw stats show normalized values instead of actual') was accurate. "
            "The failing output is 'raw_max=1.0, expected 500'. For difficulty B, the trap is "
            "that summarize_for_display looks similar to raw_stats but serves a different purpose."
        ),
    },
    "temporal_drift_c": {
        "enriched_task_prompt": (
            "The report shows incorrect raw metrics — values that should be in the hundreds are "
            "showing as 1.0. The system involves pipeline.py, transforms.py, and metrics.py. "
            "Fix the data flow so that raw metrics reflect the original untransformed input. "
            "Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Report shows wrong raw metrics') was accurate. "
            "The failing output is 'raw_max=1.0, expected 120'. For difficulty C, the 4-stage "
            "pipeline and cross-file consumer make the temporal ordering issue harder to trace. "
            "The trap (consolidating raw_stats and summarize uses different keys) is not mentioned."
        ),
    },

    # ── USE_BEFORE_SET ──
    "use_before_set_a": {
        "enriched_task_prompt": (
            "The transform function in transform.py returns stale results when called with an empty "
            "list — it returns [2, 4, 6] from a previous call instead of []. Fix transform so that "
            "each call produces results based only on its own input. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task was a generic refactor prompt. The failing output is "
            "'transform([]) returned [2, 4, 6], expected [] (stale data from previous call leaked)'. "
            "For difficulty A, the prompt describes the exact stale-data symptom."
        ),
    },
    "use_before_set_b": {
        "enriched_task_prompt": (
            "The loader reports 'loaded' status even after being called with an empty data source. "
            "The status appears to be leftover from a previous successful call. The system uses "
            "loader.py and pipeline.py. Fix the implementation so that status correctly reflects "
            "each call's outcome. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Pipeline crashes on empty data source') was slightly inaccurate — "
            "it shows stale status, not a crash. The failing output is "
            "'status is loaded after empty input — stale status from previous call leaked'. "
            "For difficulty B, the model must trace how loader sets status conditionally."
        ),
    },
    "use_before_set_c": {
        "enriched_task_prompt": (
            "The find_best function returns a result from a previous call when no items match the "
            "current filter criteria. The system involves pipeline.py, loader.py, and validator.py. "
            "Fix the implementation so that find_best returns None when no items qualify. "
            "Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Processing crashes when no items match filter') was slightly inaccurate — "
            "the actual output shows a stale result, not necessarily a crash. The failing output is "
            "'find_best returned {id: h1, value: 100} for below-threshold records, expected None'. "
            "For difficulty C, the model must trace variable initialization across loop and filter paths."
        ),
    },

    # ── WRONG_CONDITION ──
    "wrong_condition_a": {
        "enriched_task_prompt": (
            "The is_rate_limited function in limiter.py allows one extra request beyond the limit. "
            "When the limit is 5 and 5 requests have been made, is_rate_limited returns False instead "
            "of True. Fix the boundary condition so that the limit is enforced exactly. "
            "Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task was a generic refactor prompt. The failing output is "
            "'is_rate_limited(5, 5)=False, expected True (at limit)'. For difficulty A, "
            "the prompt names the function and the exact boundary value."
        ),
    },
    "wrong_condition_b": {
        "enriched_task_prompt": (
            "The rate limiter allows requests that should be blocked. Both quota-exceeded and "
            "rate-exceeded requests are being allowed through. The system uses policy.py and "
            "limiter.py. Fix the policy so that requests are blocked when either limit is exceeded. "
            "Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Rate limiter allows too many requests') was accurate. "
            "The failing output shows both 'quota exceeded but allowed' and 'rate exceeded but allowed'. "
            "For difficulty B, the trap is that OR reads naturally in English. The prompt does not "
            "reveal the specific operator error."
        ),
    },
    "wrong_condition_c": {
        "enriched_task_prompt": (
            "Expired tokens are still being allowed for exempt users — the rate limiter should block "
            "all expired tokens regardless of exemption status. The system involves limiter.py, "
            "policy.py, and middleware.py. Fix the authorization logic so that expiry always takes "
            "precedence. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Expired tokens still allowed for exempt users') was accurate. "
            "The failing output is 'expired+exempt allowed (should block)'. For difficulty C, "
            "the bug is an operator precedence error in a boolean expression. The prompt describes "
            "the semantic requirement (expiry takes precedence) without revealing that the issue "
            "is precedence rather than logic."
        ),
    },

    # ── STANDALONE CASES ──

    # async_race_lock (C)
    "async_race_lock": {
        "enriched_task_prompt": (
            "The verified pipeline (run_verified) is producing results with missing fields. "
            "Results should contain 'before' and 'after' values from process_item, but these "
            "fields are absent. The system involves worker.py, scheduler.py, state.py, and api.py. "
            "Fix the implementation so that run_verified produces complete, correct results. "
            "Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task mentioned 'missing fields' and 'handle_verified_request not working', "
            "which misdirected to the wrong function. The failing output is "
            "'result[0] missing before/after — process_item with locking was not used'. "
            "For difficulty C, the real issue is that replacing process_item with quick_increment "
            "removes the lock that run_verified depends on. The prompt describes the symptom "
            "(missing fields) without revealing the lock semantics or which function to preserve. "
            "All four files are mentioned to preserve the cross-file search difficulty."
        ),
    },

    # cache_invalidation_order (C)
    "cache_invalidation_order": {
        "enriched_task_prompt": (
            "The update_record function performs a cache invalidation followed by a cache set. "
            "This appears redundant, but removing the invalidation step causes stale reads and "
            "breaks the version-tracking protocol used by safe_update. The current code has the "
            "invalidation removed. Restore the correct cache update sequence in update_record. "
            "Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task actively told the model to remove the invalidation (adversarial framing). "
            "The failing output shows 'stale cache after update' and 'version protocol: stale "
            "conditional_set succeeded'. The rewritten prompt is honest about the situation: the "
            "invalidation was removed and it broke things. For difficulty C, the model must understand "
            "the version-tracking protocol to know why invalidate-before-set is necessary. The prompt "
            "mentions safe_update as the dependent but does not explain the versioning mechanism."
        ),
    },

    # check_then_act (C)
    "check_then_act": {
        "enriched_task_prompt": (
            "Under concurrent interleaving, two withdrawals of 80 from a balance of 100 both succeed, "
            "leaving a negative balance of -60. The check and debit operations are not atomic. "
            "Fix the withdrawal logic so that the balance can never go negative under any interleaving. "
            "Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task gave the exact failure scenario, which is appropriate for this "
            "concurrency case since the symptom IS the specification. The failing output is "
            "'interleaved: balance went negative (-60)'. The rewritten prompt preserves the original's "
            "specificity and adds that check+debit are non-atomic. For difficulty C, the trap is "
            "that locking only the check step still allows both checks to pass."
        ),
    },

    # commit_gate (L3)
    "commit_gate": {
        "enriched_task_prompt": (
            "The pipeline's process_batch function was simplified by removing commit() and freeze_view() "
            "calls. After this change, the committed total is null and the view is not rebuilt. "
            "Restore the necessary pipeline steps so that the committed total is computed correctly "
            "and the view is consistent with the committed data. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('After simplifying the pipeline by removing commit and freeze_view, "
            "the system is broken. Restore the necessary steps.') was already honest about what happened. "
            "The failing output is 'committed total is null'. The rewritten prompt preserves this "
            "framing. For L3 difficulty, the trap is restoring only commit (passes total but fails "
            "consistency). The prompt mentions both total and view consistency so the model knows "
            "both invariants must be satisfied."
        ),
    },

    # config_shadowing (L3)
    "config_shadowing": {
        "enriched_task_prompt": (
            "The background job uses a timeout of 5 seconds instead of the expected 30. The request "
            "path works correctly because it applies environment overrides, but the background path "
            "reads from defaults directly. The system involves defaults.py, env_config.py, and "
            "service.py. Fix the configuration so that the correct timeout is used everywhere. "
            "Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('The background job uses the wrong timeout (5 instead of 30)') was "
            "accurate but too specific about the values. The failing output shows 'background "
            "timeout=5, expected 30' and 'anti-hardcoding: after DEFAULTS[timeout]=99, background "
            "timeout=5'. The rewritten prompt describes both paths (request vs background) to explain "
            "why the bug is masked. For L3 difficulty, the trap is fixing the background path to call "
            "get_config() (passes basic test but fails anti-hardcoding). The prompt does not reveal "
            "that the fix must be in DEFAULTS itself."
        ),
    },

    # false_fix_deadlock (C)
    "false_fix_deadlock": {
        "enriched_task_prompt": (
            "Concurrent transfers between two resources deadlock. When transfers run in opposite "
            "directions simultaneously, neither can complete. Fix the locking so that transfers "
            "never deadlock under any interleaving while preserving the total resource invariant "
            "(A + B = 200). Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Concurrent transfers deadlock. Fix the locking.') was accurate. "
            "The failing output is 'interleaved deadlocked: deadlock: B already locked'. "
            "For difficulty C, the traps are removing locks (introduces race) or adding timeout "
            "(hides bug). The prompt mentions the total invariant to prevent the model from "
            "just removing locks. It does not reveal that canonical lock ordering is the fix."
        ),
    },

    # feature_flag_drift (C)
    "feature_flag_drift": {
        "enriched_task_prompt": (
            "The checkout function accepts a use_new_pricing parameter, but the pricing calculation "
            "does not respect it. With use_new_pricing=True, the total should be 900 (10% discount "
            "on quantity >= 10) but it returns 1000. The system involves api.py, billing.py, "
            "pricing.py, and flags.py. Fix the flag propagation so that the pricing parameter "
            "takes effect. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('checkout function takes a use_new_pricing flag but pricing doesn't "
            "seem to respect it') was accurate. The failing output is 'total=1000, expected 900'. "
            "For difficulty C, the model must trace the call chain checkout→billing→pricing and "
            "find that pricing.compute_price reads the global flag instead of the parameter. "
            "The trap (passing flag to checkout only) is not mentioned. The prompt provides the "
            "expected calculation as a concrete anchor."
        ),
    },

    # hidden_dep_multihop (C)
    "hidden_dep_multihop": {
        "enriched_task_prompt": (
            "After saving a user with a new name, get_display_name still returns the old name. "
            "The system has multiple cache helper functions in user_service.py, cache_writer.py, "
            "cache_reader.py, and user_repo.py. Fix the save path so that display name reads "
            "reflect the latest saved value. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task told the model to consolidate two cache functions — an adversarial "
            "framing. The failing output is 'cache not overwritten: get_display_name returned Alice, "
            "expected Bob'. The rewritten prompt describes the symptom without directing the model "
            "to consolidate anything. For difficulty C, the model must discover that cache_put "
            "(unconditional overwrite) and cache_put_if_absent (conditional) have different semantics, "
            "and that save_user needs the overwrite variant. The prompt mentions four files to "
            "preserve the cross-file search difficulty."
        ),
    },

    # invariant_partial_fail (C)
    "invariant_partial_fail": {
        "enriched_task_prompt": (
            "The execute_transfer function sometimes loses money — after a failed transfer, the "
            "sender's balance has decreased but the receiver's balance has not increased. The total "
            "across both accounts should always be conserved. The system involves transfer_service.py, "
            "models.py, ledger.py, and audit.py. Fix the implementation so that balance is always "
            "conserved, even when transfers fail partway through. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task told the model to extract logging into a wrapper — an adversarial "
            "framing that misdirects toward refactoring instead of fixing the missing rollback. "
            "The failing output is 'failure path: total=50, expected=100 (sender=50, receiver=0)'. "
            "The rewritten prompt describes the invariant violation (money lost on failure) without "
            "mentioning logging or refactoring. For difficulty C, the model must find that the debit "
            "is applied before the credit attempt, and that no rollback exists. The trap (focus on "
            "logging/observability) is avoided by the new framing."
        ),
    },

    # l3_state_pipeline (C)
    "l3_state_pipeline": {
        "enriched_task_prompt": (
            "The pipeline's process_batch function was simplified by removing steps that appeared "
            "redundant. After simplification, the committed state is empty, the frozen flag is not "
            "set, and the view is inconsistent with stable data. The system involves pipeline.py, "
            "state.py, reducers.py, selectors.py, and api.py. Restore the pipeline so that all "
            "state invariants are satisfied. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task actively told the model to remove 'unnecessary' steps — adversarial "
            "framing. The failing output shows 'meta.frozen is False — commit() was removed' and "
            "'stable is empty — commit() did not promote pending'. The rewritten prompt is honest "
            "that steps were removed and things broke. For difficulty C, the model must understand "
            "the state machine (stage→commit→freeze_view) and that both commit and freeze_view are "
            "independently necessary. The prompt lists all five files to preserve cross-file difficulty."
        ),
    },

    # lost_update (C)
    "lost_update": {
        "enriched_task_prompt": (
            "Two concurrent increments to the same counter produce a final value of 1 instead of 2. "
            "Each increment reads the current value, adds 1, and writes back, but interleaved "
            "execution causes one update to be lost. Fix the increment logic so that the counter "
            "is correct under any interleaving. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task gave the exact failure scenario, which is appropriate for concurrency "
            "cases. The failing output is 'interleaved: expected 2, got 1'. The rewritten prompt "
            "describes the read-modify-write pattern explicitly. For difficulty C, the trap is "
            "locking only the write step (read still stale). The prompt does not reveal the "
            "specific atomicity solution."
        ),
    },

    # ordering_dependency (C)
    "ordering_dependency": {
        "enriched_task_prompt": (
            "When process() is called before init(), the item is silently dropped instead of being "
            "processed later. After the sequence [process(a), init(), process(b), shutdown()], only "
            "item b appears in the log — item a is lost. Fix the implementation so that all items "
            "are processed regardless of arrival order. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('process() runs before init() and items are lost') was accurate. "
            "The failing output is 'broken order: expected 2 processed items, got 1: "
            "[error:not_init:a, init, processed:b, shutdown]'. The rewritten prompt gives the "
            "exact sequence and expected outcome. For difficulty C, the trap is adding a lock "
            "(provides mutual exclusion, not ordering). The prompt does not mention buffering."
        ),
    },

    # overdetermination (C)
    "overdetermination": {
        "enriched_task_prompt": (
            "Product updates sometimes show stale data. After calling update_product(42) and then "
            "update_product(99), the stored value is 42 instead of 99. The system has two writer "
            "functions (write_fresh and write_cached) in api.py, store.py, writer_a.py, and "
            "writer_b.py. Fix the update flow so that the final stored value always reflects "
            "the most recent update. Return the updated code."
        ),
        "enriched_task_prompt_justification": (
            "The original task ('Simplify by removing the redundant writer') was adversarial — it told "
            "the model to remove a writer. The failing output is 'after update(42) then update(99), "
            "got value=42, expected 99'. The rewritten prompt describes the symptom and names both "
            "writers. For difficulty C, the trap is removing write_fresh (the correct one) instead "
            "of write_cached (the stale one). The prompt does not reveal which writer is stale."
        ),
    },
}


def main():
    files = sorted(SPLIT_DIR.glob("*.json"))
    total_cases = 0
    enriched = 0
    skipped = []
    ambiguous = []

    for fpath in files:
        cases = json.loads(fpath.read_text())
        modified = False

        for case in cases:
            cid = case.get("id", "unknown")
            total_cases += 1

            if cid not in ENRICHMENTS:
                skipped.append(cid)
                continue

            e = ENRICHMENTS[cid]
            case["enriched_task_prompt"] = e["enriched_task_prompt"]
            case["enriched_task_prompt_justification"] = e["enriched_task_prompt_justification"]
            enriched += 1
            modified = True

        if modified:
            fpath.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")

    print(f"Total cases: {total_cases}")
    print(f"Enriched: {enriched}")
    print(f"Skipped: {len(skipped)} {skipped}")
    print(f"Ambiguous: {len(ambiguous)} {ambiguous}")


if __name__ == "__main__":
    main()
