"""V2 enrichment: stricter difficulty calibration, tighter leakage control.

Run: .venv/bin/python scripts/enrich_task_prompts_v2.py
"""

import json
from pathlib import Path

SPLIT_DIR = Path("case_data/cases_split")

E = {}

# ============================================================
# ALIAS_CONFIG family
# A: names function + symptom. B: names symptom, lists functions ambiguously. C: system-level symptom only.
# ============================================================

E["alias_config_a"] = {
    "enriched_task_prompt":
        "The create_config function returns a configuration dictionary, but modifications made by one "
        "caller are visible to subsequent callers. For example, after one caller sets timeout=5, "
        "a fresh call to create_config returns timeout=5 instead of the default 30. "
        "Correct the implementation so that callers receive independent configurations.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Refactor this configuration module for clarity' — no symptom, no anchoring. "
        "SYMPTOM: 'mutation leaked: cfg2[timeout]=5, expected 30'. "
        "INCLUDED: the affected function name (create_config) and the concrete value mismatch. "
        "WITHHELD: the mechanism (reference aliasing vs copy), the fix (DEFAULTS.copy()), and the "
        "internal variable DEFAULTS. "
        "LEAKAGE CHECK: naming create_config is fair for A — the model still must determine WHY "
        "the returned dict is shared. The prompt does not say 'copy' or 'reference'. "
        "DIFFICULTY: A — function named, symptom concrete, one diagnosis step remains. "
        "FAMILY: B does not name create_config; C does not name any function.",
}

E["alias_config_b"] = {
    "enriched_task_prompt":
        "Configuration state persists incorrectly between calls. After modifying settings returned "
        "by the config system, subsequent calls reflect those modifications instead of returning "
        "fresh defaults. The config flow involves create_config, get_settings, and merge_overrides. "
        "Identify the source of the persistence and fix it.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'get_settings() returns stale data. Simplify the config loading.' — misleading "
        "'simplify' instruction. "
        "SYMPTOM: 'mutation leaked: cfg2[timeout]=5, expected 30'. "
        "INCLUDED: the behavioral symptom (persistence across calls) and all three functions in the "
        "config flow. "
        "WITHHELD: which function is the root cause (create_config), the internal mechanism "
        "(reference aliasing), and the fix. merge_overrides is included because it's the trap "
        "(it correctly copies). "
        "LEAKAGE CHECK: listing three functions preserves ambiguity — the model must inspect all "
        "three to determine which one shares state. "
        "DIFFICULTY: B — symptom described, localization partial (3 candidates). "
        "FAMILY: A names create_config directly; C does not name any functions.",
}

E["alias_config_c"] = {
    "enriched_task_prompt":
        "Requests served by the middleware observe configuration values set during previous requests. "
        "For example, a debug override applied in one request persists into the next. "
        "The system spans config.py, middleware.py, and handler.py. "
        "Fix the configuration flow so that each request starts with clean defaults.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Requests seeing config from previous requests. Simplify the config flow.' "
        "SYMPTOM: 'debug override leaked: r2[debug]=True, expected False'. "
        "INCLUDED: the cross-request leakage symptom and the file list. "
        "WITHHELD: which file has the bug, which function, the mechanism (aliasing in create_config), "
        "and the existence of merge_overrides (the trap). "
        "LEAKAGE CHECK: three files listed without any localization — model must trace the full "
        "config→middleware→handler flow. "
        "DIFFICULTY: C — system-level symptom, no function named, no mechanism hinted. "
        "FAMILY: A names create_config; B names three functions; C names only files.",
}

# ============================================================
# EARLY_RETURN family
# Key: avoid saying 'every call must produce a ledger entry' — that's the fix.
# ============================================================

E["early_return_a"] = {
    "enriched_task_prompt":
        "The payment processor's ledger verification fails. After processing two payments "
        "(including one for amount zero), verify_ledger reports a count mismatch — the ledger "
        "has fewer entries than expected. Fix process_payment so that the ledger is consistent "
        "with the number of payment calls made.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'verify_ledger(2) returned False — zero-amount payment not recorded'. "
        "INCLUDED: the function name, the zero-amount trigger, the count mismatch. "
        "WITHHELD: that a specific early-return path skips the ledger append, the fix location. "
        "LEAKAGE CHECK: saying 'count mismatch' rather than 'every call must append' avoids "
        "directly encoding the fix. The model must trace the zero-amount path. "
        "DIFFICULTY: A — function named, trigger condition given. "
        "FAMILY: B does not name the trigger; C describes only the symptom.",
}

E["early_return_b"] = {
    "enriched_task_prompt":
        "Ledger record counts do not match the number of payment processing calls. The mismatch "
        "appears when certain transaction patterns are processed. The system uses payment.py "
        "and ledger.py. Fix the implementation so that ledger accounting is complete.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Ledger counts don't match transaction count' — close but mentioned duplicate "
        "transactions directly. "
        "SYMPTOM: 'verify(3) returned False — duplicate transaction not recorded'. "
        "INCLUDED: the count mismatch and both files. "
        "WITHHELD: that the duplicate-transaction path triggers the issue, the early return, "
        "the specific code path. The phrase 'certain transaction patterns' preserves ambiguity. "
        "LEAKAGE CHECK: not naming the duplicate path means the model must inspect multiple "
        "code paths in process_payment. "
        "DIFFICULTY: B — symptom + files, no path identification. "
        "FAMILY: A names process_payment and the zero-amount trigger; C names neither.",
}

E["early_return_c"] = {
    "enriched_task_prompt":
        "The audit trail is incomplete — verification reports fewer entries than expected after "
        "a series of charge operations. The system involves payment.py, ledger.py, and audit.py. "
        "Fix the implementation so that audit completeness is maintained across all charge paths.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Audit log missing entries for cached charges' — named the cache path directly. "
        "SYMPTOM: 'verify_completeness(3) returned False — cached charge not recorded'. "
        "INCLUDED: the count mismatch and three files. "
        "WITHHELD: that the cache-hit path is the culprit, the specific function (charge), "
        "the early return mechanism. Saying 'all charge paths' hints at multiple paths without "
        "naming which one fails. "
        "LEAKAGE CHECK: three files, no path identification, no function named. "
        "DIFFICULTY: C — symptom only, three files, no localization. "
        "FAMILY: A names process_payment + zero-amount; B names files + 'certain patterns'; "
        "C names only files + 'all paths'.",
}

# ============================================================
# EFFECT_ORDER family
# Critical: do NOT say 'one per item' — that's the fix.
# ============================================================

E["effect_order_a"] = {
    "enriched_task_prompt":
        "After process_batch processes 3 items, the snapshot count is 1 instead of 3. "
        "The batch processing and snapshotting are not producing consistent counts. "
        "Fix the implementation so that snapshot counts match item counts after batch processing.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. PREVIOUS ENRICHED: said 'one snapshot per item processed' "
        "which directly encodes the fix. "
        "SYMPTOM: 'expected 3 snapshots (one per item), got 1'. "
        "INCLUDED: the function name, the count mismatch (3 vs 1). "
        "WITHHELD: that the snapshot is taken at batch level instead of per-item — the phrase "
        "'match item counts' describes the invariant without prescribing 'move inside loop'. "
        "LEAKAGE CHECK: 'match item counts' is the expected behavior, not the implementation "
        "instruction. The model must determine where and how the snapshot is taken. "
        "DIFFICULTY: A — function named, counts given. "
        "FAMILY: B does not name the function; C is more abstract.",
}

E["effect_order_b"] = {
    "enriched_task_prompt":
        "After batch processing, the recorded event count does not match the number of items "
        "processed — the count is significantly lower than expected. The system uses processor.py "
        "and metrics.py. Fix the implementation so that event recording is consistent with "
        "processing.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Event counts don't match items processed' — accurate. PREVIOUS ENRICHED: "
        "said 'one event per item' which directly encodes the fix. "
        "SYMPTOM: 'expected 3 events (one per item), got 1'. "
        "INCLUDED: the count mismatch and both files. "
        "WITHHELD: that event emission is at batch level, the function name, the specific count. "
        "'Significantly lower' rather than '1 instead of 3' is less prescriptive. "
        "LEAKAGE CHECK: not naming the function or saying 'per item'. "
        "DIFFICULTY: B — two files, no function, no explicit count. "
        "FAMILY: A names process_batch and gives exact counts; C gives even less.",
}

E["effect_order_c"] = {
    "enriched_task_prompt":
        "Audit completeness checks fail after batch processing — recorded entries are fewer "
        "than expected. The system involves processor.py, metrics.py, and audit.py. "
        "Fix the implementation so that auditing is consistent with actual processing.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Audit log has fewer entries than items' — accurate. PREVIOUS ENRICHED: "
        "said 'one audit entry per item' — fix leakage. "
        "SYMPTOM: 'expected 3 audit entries (one per item), got 1'. "
        "INCLUDED: the audit mismatch and three files. "
        "WITHHELD: everything about batch-level vs per-item, the function, the exact count, "
        "the fast_process trap (legitimately batches on a different path). "
        "LEAKAGE CHECK: 'fewer than expected' preserves the need to trace why. "
        "DIFFICULTY: C — three files, no function, no count, trap preserved. "
        "FAMILY: clear separation — A has function + counts, B has files + approximate, "
        "C has only files + abstract mismatch.",
}

# ============================================================
# INDEX_MISALIGN family
# ============================================================

E["index_misalign_a"] = {
    "enriched_task_prompt":
        "After inserting a new entry at position 0 in the report, get_entry(0) returns the wrong "
        "value — the label is correct but the value belongs to a different entry. "
        "Fix add_entry so that labels and values remain correctly paired after positional insertion.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'get_entry(0) returned (gamma, 10), expected (gamma, 30)'. "
        "INCLUDED: the function, the positional insertion trigger, the mismatch. "
        "WITHHELD: that insert uses different strategies for labels vs values (insert vs append). "
        "LEAKAGE: naming the function and trigger is fair for A — model must still find the "
        "differing insertion strategies. "
        "DIFFICULTY: A. FAMILY: B describes column deletion symptom; C describes validation failure.",
}

E["index_misalign_b"] = {
    "enriched_task_prompt":
        "After deleting a column from the report, row data appears under the wrong headers. "
        "The system uses report.py and data.py. Fix the column deletion so that all report "
        "structures remain consistent.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Report columns are misaligned after deletion' — accurate. "
        "SYMPTOM: 'After deleting age column, city is 30, expected NYC'. "
        "INCLUDED: the column-deletion trigger and both files. "
        "WITHHELD: that the header is deleted but row data is not, the specific function. "
        "DIFFICULTY: B. FAMILY: A names the function; C describes only validation failure.",
}

E["index_misalign_c"] = {
    "enriched_task_prompt":
        "Report validation fails after inserting a new column — internal structures are out of sync. "
        "The system involves report.py, data.py, and formatter.py. "
        "Fix the implementation so that all parallel structures remain consistent after modifications.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Report formatting breaks after inserting column' — accurate. "
        "SYMPTOM: 'validate() failed: header/width count mismatch'. "
        "INCLUDED: the trigger (column insertion), the validation failure, three files. "
        "WITHHELD: which structure is out of sync (column_widths), that recalculate_widths "
        "exists but is not called. 'Parallel structures' hints at the class of bug without "
        "naming the specific missing update. "
        "DIFFICULTY: C. FAMILY: A names function + mismatch type; B names trigger + files; "
        "C names trigger + validation failure + files.",
}

# ============================================================
# LAZY_INIT family
# ============================================================

E["lazy_init_a"] = {
    "enriched_task_prompt":
        "After calling reset_settings and updating the configuration, get_host still returns "
        "the old value ('localhost' instead of 'prod.example.com'). "
        "Fix the settings system so that resets take effect on subsequent reads.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'get_host() returned stale value: localhost, expected prod.example.com'. "
        "INCLUDED: the function name, the stale value, the reset operation. "
        "WITHHELD: that values are captured eagerly at module level (the mechanism). "
        "DIFFICULTY: A — function and symptom named. "
        "FAMILY: B mentions two files without naming the function; C mentions three files.",
}

E["lazy_init_b"] = {
    "enriched_task_prompt":
        "After resetting configuration, the client module still returns old values. "
        "The system uses config.py and client.py. Fix the implementation so that "
        "configuration resets propagate correctly.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'After resetting config, client still uses old timeout' — accurate. "
        "SYMPTOM: 'get_timeout() returned stale value: 30, expected 99'. "
        "INCLUDED: the stale-after-reset symptom and both files. "
        "WITHHELD: which file has the bug, how values are captured, the function name. "
        "DIFFICULTY: B — two files, no function named. "
        "FAMILY: A names get_host; C names three files.",
}

E["lazy_init_c"] = {
    "enriched_task_prompt":
        "Configuration changes do not propagate through the system. After a reset, multiple "
        "values across different components remain stale. The system spans config.py, client.py, "
        "and handler.py. Fix the implementation so that resets take full effect.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Config reset doesn't propagate through client to handler' — named the chain. "
        "SYMPTOM: 'api_key stale, base_url stale'. "
        "INCLUDED: the multi-value stale symptom and three files. "
        "WITHHELD: the propagation direction (config→client→handler), which file captures eagerly, "
        "the client.refresh() trap. "
        "DIFFICULTY: C — three files, no chain direction, no function named. "
        "FAMILY: clear ladder — A names function, B names files, C names files + abstract symptom.",
}

# ============================================================
# MISSING_BRANCH family
# ============================================================

E["missing_branch_a"] = {
    "enriched_task_prompt":
        "The permissions system returns empty permissions for moderator users, but moderators "
        "should have a defined permission set. Fix the access control so that all valid roles "
        "receive appropriate permissions.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'moderator got empty permissions, expected non-empty set'. "
        "INCLUDED: the role (moderator) and the symptom (empty permissions). "
        "WITHHELD: the function name (get_permissions), the specific fix (add a branch). "
        "DIFFICULTY: A — role and symptom named. "
        "FAMILY: B names the role but not the expected permission set; C is cross-boundary.",
}

E["missing_branch_b"] = {
    "enriched_task_prompt":
        "Guest users receive no access at all despite being a valid role in the system. "
        "The system uses auth.py and roles.py. Fix the role handling so that guest users "
        "receive their expected access level.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Guest users get no access' — accurate. "
        "SYMPTOM: 'guest has no read access, expected read-only'. "
        "INCLUDED: the role (guest), the symptom, two files. "
        "WITHHELD: the function name, the dispatch dict, the specific expected permissions "
        "(read-only). validate_role trap not mentioned. "
        "DIFFICULTY: B — role + files, no function, no specific permission spec. "
        "FAMILY: A names the role + symptom; C is cross-boundary with permission spec.",
}

E["missing_branch_c"] = {
    "enriched_task_prompt":
        "Service accounts are denied access even though middleware accepts them. The expected "
        "access is read and write, but not admin. The system involves auth.py, middleware.py, "
        "and roles.py. Fix the authorization so that service accounts receive correct permissions.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Service accounts denied despite middleware allowing' — accurate. "
        "SYMPTOM: 'service_account got can_read=False, expected True'. "
        "INCLUDED: the role, the cross-boundary symptom (middleware accepts, handler denies), "
        "the exact permission spec (read+write, not admin), three files. "
        "WITHHELD: which file needs the fix (auth.py), the trap (fixing middleware only). "
        "NOTE: the permission spec IS intentionally included because without it, models "
        "consistently give can_admin=True. This is a necessary fairness constraint, not leakage. "
        "DIFFICULTY: C — cross-boundary, but permission spec included for correctness. "
        "FAMILY: A is single-function; B is two-file; C is three-file cross-boundary.",
}

# ============================================================
# MUTABLE_DEFAULT family
# ============================================================

E["mutable_default_a"] = {
    "enriched_task_prompt":
        "Calling enqueue twice with different tasks produces unexpected accumulation — the second "
        "call's result contains items from the first call. Fix the implementation so that each "
        "call to enqueue operates independently.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'second enqueue() leaked state: got 2 items, expected 1'. "
        "INCLUDED: the function name and the accumulation symptom. "
        "WITHHELD: the mutable default mechanism, the parameter name (queue=[]), the fix. "
        "DIFFICULTY: A — function named, symptom concrete. "
        "FAMILY: B describes symptom without naming function; C is cross-module.",
}

E["mutable_default_b"] = {
    "enriched_task_prompt":
        "When processing batches sequentially, valid tasks from the second batch are skipped "
        "if they appeared in the first batch. The system uses worker.py and queue.py. "
        "Fix the implementation so that each batch processes all its tasks independently.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Workers skip valid tasks on second batch' — accurate. "
        "SYMPTOM: 'task_x skipped in second call due to stale seen set'. "
        "INCLUDED: the skip symptom and both files. "
        "WITHHELD: the function name, the seen set, the mutable default mechanism. "
        "DIFFICULTY: B — two files, no function named. "
        "FAMILY: A names enqueue; C is cross-module with decorator.",
}

E["mutable_default_c"] = {
    "enriched_task_prompt":
        "Job history leaks between independently scheduled jobs — a job scheduled after another "
        "inherits history entries it should not have. The system involves scheduler.py, worker.py, "
        "and queue.py. Fix the implementation so that each job has isolated state.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Scheduler history is shared across jobs' — accurate. "
        "SYMPTOM: 'schedule_batch history leaked from schedule_one'. "
        "INCLUDED: the cross-job leakage symptom and three files. "
        "WITHHELD: the decorator closure, the shared mutable list, the function name. "
        "DIFFICULTY: C — three files, no function, decorator trap preserved. "
        "FAMILY: A names function; B names files; C adds a third file + abstract symptom.",
}

# ============================================================
# PARTIAL_ROLLBACK family
# ============================================================

E["partial_rollback_a"] = {
    "enriched_task_prompt":
        "When payment fails during order processing, inventory remains reserved instead of being "
        "released. After a failed order, available inventory is 7 instead of the expected 10. "
        "Fix place_order so that failed operations do not leave partial state.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'failure path: available=7, expected 10 (reservation not rolled back)'. "
        "INCLUDED: the function name, the failure path symptom, the concrete values. "
        "WITHHELD: the specific rollback mechanism (try/except + release). "
        "DIFFICULTY: A — function and values named. "
        "FAMILY: B names files but not function; C involves multi-resource cleanup.",
}

E["partial_rollback_b"] = {
    "enriched_task_prompt":
        "Inventory gets stuck in a reserved state after downstream payment failures. The system "
        "uses order_service.py and inventory.py. Fix the order flow so that inventory state is "
        "correctly restored when operations fail.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Inventory stuck as reserved after payment failure' — accurate. "
        "SYMPTOM: 'failure path: available=7, expected 10'. "
        "INCLUDED: the stuck-reservation symptom and both files. "
        "WITHHELD: the function name, the specific compensation mechanism. "
        "DIFFICULTY: B — two files, no function. "
        "FAMILY: A names place_order; C involves three files + audit.",
}

E["partial_rollback_c"] = {
    "enriched_task_prompt":
        "After a payment gateway failure, multiple resources are left in an inconsistent state — "
        "inventory remains reserved and orphaned records persist. The system involves "
        "order_service.py, inventory.py, and payment.py. Fix the implementation so that all "
        "side effects are properly cleaned up on failure.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Inventory and audit corrupted after payment failure' — accurate. "
        "SYMPTOM: 'available=15, expected 20; audit_log has 1 entries, expected 0'. "
        "INCLUDED: the multi-resource inconsistency and three files. "
        "WITHHELD: the specific resources (inventory + audit), the function name, the "
        "retry-instead-of-rollback trap. "
        "DIFFICULTY: C — three files, multi-resource, no localization. "
        "FAMILY: A names function + values; B names two files; C is multi-resource across three.",
}

# ============================================================
# PARTIAL_UPDATE family
# ============================================================

E["partial_update_a"] = {
    "enriched_task_prompt":
        "After updating a user's name, the display_name field still shows the old value. "
        "Fix update_profile so that dependent fields stay consistent when primary fields change.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'display_name not synced: display_name=Alice, expected Bob'. "
        "INCLUDED: the function name and the specific desynchronized field. "
        "WITHHELD: which line is missing, the exact update statement. "
        "DIFFICULTY: A. FAMILY: B mentions files without naming the specific field; C is multi-field.",
}

E["partial_update_b"] = {
    "enriched_task_prompt":
        "After updating user profile fields, derived values are not recalculated and become "
        "inconsistent with their source fields. The system uses profile.py and validation.py. "
        "Fix the profile update so that all derived state remains consistent.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Users report their full name not updating' — named full_name directly. "
        "SYMPTOM: 'full_name not synced: full_name=Alice Smith, expected Bob Smith'. "
        "INCLUDED: the derived-value desync and both files. "
        "WITHHELD: which specific derived field (full_name), the function name, the "
        "validate_name trap. "
        "DIFFICULTY: B — two files, abstract 'derived values'. "
        "FAMILY: A names update_profile + display_name; C is multi-field across three files.",
}

E["partial_update_c"] = {
    "enriched_task_prompt":
        "After changing profile fields, dependent state is not refreshed — flags and cached "
        "values remain stale. The system involves profile.py, validation.py, and notifications.py. "
        "Fix the implementation so that all dependent state is correctly updated.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'After changing email, old greeting still shows' — missed verified flag. "
        "SYMPTOM: 'verified not reset: verified=True, expected False'. "
        "INCLUDED: the abstract multi-field staleness and three files. "
        "WITHHELD: which fields (verified, cached_greeting), which trigger (email change), "
        "the validate_email trap. "
        "DIFFICULTY: C — three files, multiple affected fields, no specific field named. "
        "FAMILY: A names function + specific field; B names files + 'derived values'; "
        "C names files + 'dependent state'.",
}

# ============================================================
# RETRY_DUP family
# ============================================================

E["retry_dup_a"] = {
    "enriched_task_prompt":
        "The message sender produces duplicate messages on successful sends — after sending one "
        "message, the store contains multiple copies. Fix retry_send so that successful operations "
        "produce exactly one message.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'success path: 3 messages, expected 1'. "
        "INCLUDED: the function name and duplication symptom. "
        "WITHHELD: the missing break, the retry loop structure. "
        "DIFFICULTY: A. FAMILY: B names files; C is multi-module.",
}

E["retry_dup_b"] = {
    "enriched_task_prompt":
        "Messages are duplicated in the store after sending. Both store entries and notifications "
        "are affected. The system uses sender.py and store.py. Fix the send logic so that each "
        "successful send produces exactly one record.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Messages appearing twice in store' — accurate. "
        "SYMPTOM: '2 messages, expected 1; 2 notifications, expected 1'. "
        "INCLUDED: the duplication across store + notifications, both files. "
        "WITHHELD: the function name, the retry loop, the missing break. "
        "DIFFICULTY: B. FAMILY: A names the function; C involves three files.",
}

E["retry_dup_c"] = {
    "enriched_task_prompt":
        "Messages are being delivered multiple times — sometimes 2, sometimes more. The system "
        "involves pipeline.py, sender.py, and store.py. Fix the delivery logic so that each "
        "message is processed exactly once.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Messages appearing 3-4 times' — accurate. "
        "SYMPTOM: '2 messages, expected 1' at pipeline level. "
        "INCLUDED: the variable duplication count and three files. "
        "WITHHELD: the nested retry structure, which layer causes multiplication. "
        "DIFFICULTY: C — three files, variable count suggests compounding. "
        "FAMILY: A names function; B names files; C is cross-module with variable count.",
}

# ============================================================
# SILENT_DEFAULT family
# ============================================================

E["silent_default_a"] = {
    "enriched_task_prompt":
        "The is_enabled function returns False for the 'darkMode' flag even though the flag "
        "is configured as True (under the key 'dark_mode'). Fix the flag lookup so that it "
        "returns the configured value.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'is_enabled(darkMode) returned False. Flag dark_mode is True but camelCase "
        "lookup missed'. The test output itself reveals the naming mismatch. "
        "INCLUDED: the function, both key forms. This is forced by the evidence — the symptom "
        "itself exposes the mismatch. "
        "WITHHELD: nothing beyond what the evidence already reveals. "
        "DIFFICULTY: A — the evidence forces high explicitness. "
        "FAMILY: B does not show both key forms; C mentions only env var path.",
}

E["silent_default_b"] = {
    "enriched_task_prompt":
        "The analytics feature flag always reports as disabled despite being set to True in the "
        "configuration. The system uses flags.py and config.py. Fix the flag resolution so that "
        "it returns the configured value.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Analytics flag always off despite being enabled' — accurate. "
        "SYMPTOM: 'is_analytics_enabled() returned False. Config has feature.analytics.enabled=True'. "
        "INCLUDED: the symptom and both files. "
        "WITHHELD: the nested path traversal bug, the wrong intermediate key, the function name. "
        "DIFFICULTY: B — two files, no path detail. "
        "FAMILY: A shows both key forms; C involves env var chain.",
}

E["silent_default_c"] = {
    "enriched_task_prompt":
        "A feature flag ignores its environment variable override and falls back to a different "
        "source. The system involves flags.py, config.py, and env.py. Fix the flag resolution "
        "chain so that environment overrides take precedence.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Feature flag ignores env var override' — accurate. "
        "SYMPTOM: 'get_flag_source(dark_mode) returned config, expected env'. "
        "INCLUDED: the fallback symptom and three files. "
        "WITHHELD: the env var key mismatch, the specific wrong key, the fallback chain details. "
        "DIFFICULTY: C — three files, abstract 'falls back to different source'. "
        "FAMILY: A reveals key forms; B names two files; C is three-file chain.",
}

# ============================================================
# STALE_CACHE family
# ============================================================

E["stale_cache_a"] = {
    "enriched_task_prompt":
        "After calling update_product with a new price, get_product still returns the old price "
        "(10.0 instead of 25.0). Fix the catalog so that reads reflect the latest writes.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'stale cache: price=10.0, expected 25.0'. "
        "INCLUDED: both function names and the concrete values. "
        "WITHHELD: the caching mechanism, the missing invalidation. "
        "DIFFICULTY: A. FAMILY: B mentions files; C mentions architecture.",
}

E["stale_cache_b"] = {
    "enriched_task_prompt":
        "Product data is stale after updates — reads return old values even after writes. "
        "The system uses catalog.py and cache.py. Fix the update flow so that subsequent "
        "reads return current data.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Products show old prices after updates' — accurate. "
        "SYMPTOM: 'stale cache: price=10.0, expected 25.0'. "
        "INCLUDED: the stale-read symptom and both files. "
        "WITHHELD: the function names, the cache.warm() trap. "
        "DIFFICULTY: B. FAMILY: A names functions; C mentions architecture.",
}

E["stale_cache_c"] = {
    "enriched_task_prompt":
        "The API returns stale product data after updates. The system uses a multi-layer caching "
        "architecture across catalog.py, cache.py, and api.py. Fix the implementation so that "
        "updates are visible to all read paths.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'API returns stale product data' — accurate. "
        "SYMPTOM: 'stale local cache: price=10.0, expected 50.0'. "
        "INCLUDED: the stale-read symptom, three files, multi-layer hint. "
        "WITHHELD: which cache layer is missed (local), the function names. "
        "DIFFICULTY: C — three files, multi-layer hint preserves some ambiguity about "
        "which layer is stale. "
        "FAMILY: A names functions; B names files; C adds architecture context.",
}

# ============================================================
# TEMPORAL_DRIFT family
# ============================================================

E["temporal_drift_a"] = {
    "enriched_task_prompt":
        "The pipeline's raw_stats computation returns normalized values instead of raw values — "
        "raw_max is 1.0 instead of the expected 80. Fix the pipeline so that raw statistics "
        "reflect the original input data.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'raw_max=1.0, expected 80 (computed on normalized data instead of original)'. "
        "INCLUDED: the function (raw_stats), the concrete wrong value, the diagnostic hint "
        "(normalized vs original). The symptom itself reveals this. "
        "WITHHELD: the temporal ordering fix (move before transform). "
        "DIFFICULTY: A — evidence forces explicitness. "
        "FAMILY: B drops the diagnostic hint; C is abstract.",
}

E["temporal_drift_b"] = {
    "enriched_task_prompt":
        "Raw statistics report unexpected values — maximums are 1.0 instead of expected hundreds. "
        "The system uses pipeline.py and transforms.py. Fix the implementation so that raw "
        "statistics correctly reflect the input data.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Raw stats show normalized values instead of actual' — named the cause. "
        "SYMPTOM: 'raw_max=1.0, expected 500'. "
        "INCLUDED: the approximate wrong value and both files. "
        "WITHHELD: that the issue is temporal ordering, the function names, the "
        "summarize_for_display trap. "
        "DIFFICULTY: B. FAMILY: A names raw_stats and gives diagnostic; C is abstract.",
}

E["temporal_drift_c"] = {
    "enriched_task_prompt":
        "The report shows incorrect raw metrics — values that should be in the hundreds appear "
        "as 1.0. The system involves pipeline.py, transforms.py, and metrics.py. "
        "Fix the data flow so that raw metrics reflect the original input.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Report shows wrong raw metrics' — accurate. "
        "SYMPTOM: 'raw_max=1.0, expected 120'. "
        "INCLUDED: the approximate wrong value and three files. "
        "WITHHELD: that the issue is temporal ordering, which function, which stage. "
        "DIFFICULTY: C — three files, abstract 'data flow'. "
        "FAMILY: A names function + diagnostic; B names files; C is abstract across three files.",
}

# ============================================================
# USE_BEFORE_SET family
# ============================================================

E["use_before_set_a"] = {
    "enriched_task_prompt":
        "The transform function returns stale results when called with an empty list — it "
        "produces output from a previous call instead of an empty result. Fix the implementation "
        "so that each call is independent of prior calls.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'transform([]) returned [2, 4, 6], expected []'. "
        "INCLUDED: the function name and the stale-on-empty symptom. "
        "WITHHELD: the uninitialized variable mechanism. "
        "DIFFICULTY: A. FAMILY: B mentions files; C is more abstract.",
}

E["use_before_set_b"] = {
    "enriched_task_prompt":
        "The system reports incorrect status after processing empty input — the status reflects "
        "a previous successful run instead of the current empty input. The system uses loader.py "
        "and pipeline.py. Fix the implementation so that status accurately reflects each run.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Pipeline crashes on empty data source' — inaccurate (it's stale, not crash). "
        "SYMPTOM: 'status is loaded after empty input — stale from previous call'. "
        "INCLUDED: the stale-status symptom and both files. "
        "WITHHELD: the function name, which variable, the conditional assignment pattern. "
        "DIFFICULTY: B. FAMILY: A names function; C is across three files.",
}

E["use_before_set_c"] = {
    "enriched_task_prompt":
        "A search function returns results from a previous call when no items match the current "
        "criteria. The system involves pipeline.py, loader.py, and validator.py. "
        "Fix the implementation so that no-match cases return None rather than stale results.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Processing crashes when no items match filter' — inaccurate (stale, not crash). "
        "SYMPTOM: 'find_best returned {id: h1, value: 100} for below-threshold, expected None'. "
        "INCLUDED: the stale-result-on-no-match symptom and three files. "
        "WITHHELD: the function name (find_best), the loop variable pattern. "
        "DIFFICULTY: C — three files, no function named. "
        "FAMILY: A names function; B names files; C is abstract across three files.",
}

# ============================================================
# WRONG_CONDITION family
# ============================================================

E["wrong_condition_a"] = {
    "enriched_task_prompt":
        "The rate limiter allows one extra request beyond the configured limit. When the limit "
        "is 5 and exactly 5 requests have been made, the limiter incorrectly reports 'not limited'. "
        "Fix the boundary condition in is_rate_limited.",

    "enriched_task_prompt_justification":
        "OLD TASK: generic refactor. "
        "SYMPTOM: 'is_rate_limited(5, 5)=False, expected True'. "
        "INCLUDED: the function name, the boundary value, the off-by-one direction. "
        "WITHHELD: the specific operator (> vs >=). "
        "DIFFICULTY: A — function + boundary named. "
        "FAMILY: B describes behavior without naming function; C is more abstract.",
}

E["wrong_condition_b"] = {
    "enriched_task_prompt":
        "The rate limiter allows requests that exceed individual limits — requests pass when "
        "either the quota or the rate limit is exceeded, but they should only pass when both "
        "are within bounds. The system uses policy.py and limiter.py. Fix the policy logic.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Rate limiter allows too many requests' — accurate. "
        "SYMPTOM: 'quota exceeded but allowed; rate exceeded but allowed'. "
        "INCLUDED: the 'either exceeds' symptom and both files. "
        "WITHHELD: the specific operator (OR vs AND), the function name. "
        "NOTE: the prompt describes the semantic requirement (both within bounds) which is "
        "close to the fix but necessary for fairness — without it the model can't know the intent. "
        "DIFFICULTY: B. FAMILY: A names function + boundary; C is precedence-level.",
}

E["wrong_condition_c"] = {
    "enriched_task_prompt":
        "The authorization logic incorrectly allows expired tokens for exempt users. Expiry "
        "should always block access regardless of exemption status. The system involves "
        "limiter.py, policy.py, and middleware.py. Fix the logic so that expiry takes precedence.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Expired tokens still allowed for exempt users' — accurate. "
        "SYMPTOM: 'expired+exempt allowed (should block)'. "
        "INCLUDED: the semantic requirement (expiry overrides exemption) and three files. "
        "WITHHELD: that it's an operator precedence error, the specific expression, the function. "
        "DIFFICULTY: C — three files, semantic description only. "
        "FAMILY: A names function + boundary; B names files + policy; C is semantic across three files.",
}

# ============================================================
# STANDALONE CASES (all C or L3)
# ============================================================

E["async_race_lock"] = {
    "enriched_task_prompt":
        "The verified pipeline produces results with missing fields — expected 'before' and 'after' "
        "values are absent. The system spans worker.py, scheduler.py, state.py, and api.py. "
        "Fix the implementation so that the verified pipeline produces complete results.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'handle_verified_request is not working correctly' — misdirects to wrong function. "
        "SYMPTOM: 'result[0] missing before/after — process_item with locking was not used'. "
        "INCLUDED: the missing-field symptom and all four files. "
        "WITHHELD: that the issue is about lock removal, which function to preserve, "
        "the quick_increment vs process_item distinction. "
        "DIFFICULTY: C — four files, missing-field symptom only.",
}

E["cache_invalidation_order"] = {
    "enriched_task_prompt":
        "After removing what appeared to be a redundant cache invalidation step from update_record, "
        "reads return stale data and the version-tracking protocol is broken. Restore the correct "
        "cache update sequence. The system spans service.py, cache.py, db.py, and api.py.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Remove the unnecessary cache invalidation step' — adversarial, told model "
        "to introduce the bug. "
        "SYMPTOM: 'stale cache after update; version protocol: stale conditional_set succeeded'. "
        "INCLUDED: that the invalidation was removed and it broke things, the version protocol "
        "symptom. This case is unusual — the task must be honest that a removal caused the bug. "
        "WITHHELD: exactly why invalidate-before-set matters (versioning mechanism). "
        "DIFFICULTY: C — the model must understand the version-tracking protocol.",
}

E["check_then_act"] = {
    "enriched_task_prompt":
        "Under concurrent interleaving, two withdrawals from the same account both succeed even "
        "when the combined amount exceeds the balance, resulting in a negative balance. "
        "Fix the withdrawal logic so the balance cannot go negative under any interleaving.",

    "enriched_task_prompt_justification":
        "OLD TASK: gave exact scenario — appropriate for concurrency. "
        "SYMPTOM: 'interleaved: balance went negative (-60)'. "
        "INCLUDED: the interleaving scenario and the invariant (non-negative balance). "
        "WITHHELD: the check-then-act pattern name, the specific atomicity fix. "
        "DIFFICULTY: C — concurrency case, the trap is partial locking.",
}

E["commit_gate"] = {
    "enriched_task_prompt":
        "After simplifying the pipeline by removing steps that appeared redundant, the committed "
        "total is null and the view does not reflect the committed data. Restore the pipeline "
        "steps necessary for correct state transitions.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Restore the necessary steps' — already honest framing. "
        "SYMPTOM: 'committed total is null'. "
        "INCLUDED: that steps were removed and two things broke (total + view). "
        "WITHHELD: which specific functions (commit, freeze_view), why they're independent. "
        "DIFFICULTY: L3 — the trap is restoring only one of the two functions.",
}

E["config_shadowing"] = {
    "enriched_task_prompt":
        "The background job uses an incorrect timeout value (5 instead of 30). The request path "
        "works correctly. The system involves defaults.py, env_config.py, and service.py. "
        "Fix the configuration so that the correct timeout is used on all paths.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Background job uses the wrong timeout (5 instead of 30)' — accurate but "
        "gave exact values. "
        "SYMPTOM: 'background timeout=5, expected 30; anti-hardcoding test also fails'. "
        "INCLUDED: the wrong value, that request path works (masking clue), three files. "
        "WITHHELD: that DEFAULTS itself has the wrong value, the env override masking mechanism, "
        "the trap (fix service.py to call get_config instead of get_defaults). "
        "DIFFICULTY: L3 — the model must find the structural root cause, not the contingent fix.",
}

E["false_fix_deadlock"] = {
    "enriched_task_prompt":
        "Concurrent transfers between two resources deadlock when run in opposite directions. "
        "Fix the locking so that transfers never deadlock while preserving the total resource "
        "invariant (A + B = 200).",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Concurrent transfers deadlock. Fix the locking.' — accurate. "
        "SYMPTOM: 'interleaved deadlocked: deadlock: B already locked'. "
        "INCLUDED: the deadlock symptom and the invariant constraint. "
        "WITHHELD: canonical lock ordering as the fix. The invariant prevents removing locks. "
        "DIFFICULTY: C — traps: remove locks (race), add timeout (hides bug).",
}

E["feature_flag_drift"] = {
    "enriched_task_prompt":
        "The checkout function accepts a use_new_pricing parameter but the pricing calculation "
        "does not change when the flag is set. The system spans api.py, billing.py, pricing.py, "
        "and flags.py. Fix the implementation so that the pricing parameter takes effect.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'checkout function takes a use_new_pricing flag but pricing doesn't respect it' "
        "— accurate. Previous enriched gave exact expected total (900) which is unnecessary. "
        "SYMPTOM: 'total=1000, expected 900'. "
        "INCLUDED: the flag-not-propagating symptom and four files. "
        "WITHHELD: which file breaks the chain, the global flag mechanism, the expected value. "
        "DIFFICULTY: C — four-file call chain tracing.",
}

E["hidden_dep_multihop"] = {
    "enriched_task_prompt":
        "After saving a user with a new name, display name reads still return the old value. "
        "The system has multiple cache-related functions across user_service.py, cache_writer.py, "
        "cache_reader.py, and user_repo.py. Fix the save path so that reads reflect updates.",

    "enriched_task_prompt_justification":
        "OLD TASK: told model to consolidate functions — adversarial. "
        "SYMPTOM: 'cache not overwritten: get_display_name returned Alice, expected Bob'. "
        "INCLUDED: the stale-read symptom and four files. "
        "WITHHELD: which cache function to use (cache_put vs cache_put_if_absent), the "
        "semantic difference between the two. "
        "DIFFICULTY: C — four files, hidden dependency between cache write semantics.",
}

E["invariant_partial_fail"] = {
    "enriched_task_prompt":
        "After a failed transfer, money is lost — the sender's balance decreases but the "
        "receiver's balance does not increase. The total across both accounts should always "
        "be conserved. The system involves transfer_service.py, models.py, ledger.py, and "
        "audit.py. Fix the implementation so that balance is always conserved.",

    "enriched_task_prompt_justification":
        "OLD TASK: told model to extract logging into wrapper — adversarial misdirection. "
        "SYMPTOM: 'failure path: total=50, expected=100 (sender=50, receiver=0)'. "
        "INCLUDED: the invariant violation (money lost) and four files. "
        "WITHHELD: the debit-before-credit ordering, the missing rollback mechanism. "
        "The trap (focus on logging) is completely removed from the new framing. "
        "DIFFICULTY: C — four files, the model must trace the failure path.",
}

E["l3_state_pipeline"] = {
    "enriched_task_prompt":
        "After simplifying the pipeline by removing steps that appeared redundant, the committed "
        "state is empty, the frozen flag is not set, and the view is not rebuilt. The system "
        "spans pipeline.py, state.py, reducers.py, selectors.py, and api.py. Restore the "
        "pipeline so that all state invariants hold.",

    "enriched_task_prompt_justification":
        "OLD TASK: told model to remove 'unnecessary' steps — adversarial. "
        "SYMPTOM: 'meta.frozen is False; stable is empty; get_committed_total returns None'. "
        "INCLUDED: the three broken invariants and five files. "
        "WITHHELD: which functions (commit, freeze_view), why they're independently necessary. "
        "DIFFICULTY: C — five files, state machine tracing.",
}

E["lost_update"] = {
    "enriched_task_prompt":
        "Two concurrent increments to the same counter produce a value of 1 instead of 2. "
        "Fix the counter so that it is correct under any interleaving of operations.",

    "enriched_task_prompt_justification":
        "OLD TASK: gave exact scenario — appropriate for concurrency. "
        "SYMPTOM: 'interleaved: expected 2, got 1'. "
        "INCLUDED: the exact interleaving failure. "
        "WITHHELD: the read-modify-write pattern name, the atomicity fix. "
        "DIFFICULTY: C — trap is locking only the write (read still stale).",
}

E["ordering_dependency"] = {
    "enriched_task_prompt":
        "When process() is called before init(), the item is silently lost. After the sequence "
        "[process(a), init(), process(b)], only item b appears — item a is missing. "
        "Fix the implementation so that all items are processed regardless of arrival order.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'process() runs before init() and items are lost' — accurate. "
        "SYMPTOM: 'broken order: expected 2 processed items, got 1'. "
        "INCLUDED: the exact failing sequence and the lost-item symptom. "
        "WITHHELD: buffering as the fix, the lock trap (mutual exclusion, not ordering). "
        "DIFFICULTY: C.",
}

E["overdetermination"] = {
    "enriched_task_prompt":
        "Product updates produce stale data. After two sequential updates (42 then 99), the "
        "stored value is 42 instead of 99. The system has two writer paths across api.py, "
        "store.py, writer_a.py, and writer_b.py. Fix the update flow so that the final "
        "value always reflects the most recent write.",

    "enriched_task_prompt_justification":
        "OLD TASK: 'Simplify by removing the redundant writer' — adversarial. "
        "SYMPTOM: 'after update(42) then update(99), got value=42, expected 99'. "
        "INCLUDED: the stale-overwrite symptom, the two-writer hint, four files. "
        "WITHHELD: which writer is stale (write_cached), which to remove. "
        "DIFFICULTY: C — four files, trap is removing the wrong writer.",
}


def main():
    files = sorted(SPLIT_DIR.glob("*.json"))
    total = 0
    enriched = 0
    skipped = []

    for fpath in files:
        cases = json.loads(fpath.read_text())
        modified = False
        for case in cases:
            cid = case.get("id", "unknown")
            total += 1
            if cid not in E:
                skipped.append(cid)
                continue
            case["enriched_task_prompt"] = E[cid]["enriched_task_prompt"]
            case["enriched_task_prompt_justification"] = E[cid]["enriched_task_prompt_justification"]
            enriched += 1
            modified = True
        if modified:
            fpath.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")

    print(f"Total: {total}, Enriched: {enriched}, Skipped: {len(skipped)} {skipped}")

    # Family ladder audit
    families = {}
    for fpath in files:
        cases = json.loads(fpath.read_text())
        for c in cases:
            fam = c.get("family", c["id"])
            families.setdefault(fam, []).append(c)

    print("\nFamily ladder check:")
    for fam, cases in sorted(families.items()):
        if len(cases) > 1:
            prompts = [(c["difficulty"], len(c.get("enriched_task_prompt", ""))) for c in cases]
            prompts.sort(key=lambda x: x[0])
            print(f"  {fam}: {', '.join(f'{d}={l}ch' for d, l in prompts)}")


if __name__ == "__main__":
    main()
