"""Enrich cases_v2.json with oracle_ground_truth fields.

Run: .venv/bin/python scripts/enrich_oracle_fields.py
"""

import json
from pathlib import Path

CASES_PATH = Path("case_data/cases_v2.json")

# Hand-authored oracle_ground_truth for every case.
# Each entry: case_id -> oracle_ground_truth dict

ENRICHMENTS = {
    # ── ALIAS_CONFIG ──
    "alias_config_a": {
        "bug_type": "shared_reference_mutation",
        "bug_location": "config.py::create_config",
        "mechanism_source": "create_config returns the DEFAULTS dict object directly",
        "mechanism_property": "returned config shares mutable state with the module-level DEFAULTS",
        "mechanism_steps": [
            "create_config returns DEFAULTS by reference (not a copy)",
            "caller mutates the returned dict",
            "mutation modifies the global DEFAULTS object",
            "subsequent calls to create_config return the corrupted DEFAULTS",
        ],
        "mechanism_outcome": "later config reads observe values corrupted by earlier callers",
        "trap_description": None,
    },
    "alias_config_b": {
        "bug_type": "shared_reference_mutation",
        "bug_location": "config.py::create_config",
        "mechanism_source": "create_config returns the DEFAULTS dict object directly",
        "mechanism_property": "returned config shares mutable state with the module-level DEFAULTS",
        "mechanism_steps": [
            "create_config returns DEFAULTS by reference",
            "get_settings caches the returned dict and mutates it",
            "mutation propagates to the global DEFAULTS",
            "subsequent calls observe corrupted defaults",
        ],
        "mechanism_outcome": "get_settings returns settings contaminated by prior calls",
        "trap_description": "merge_overrides correctly copies its input, so it looks safe — but create_config is the source of aliasing",
    },
    "alias_config_c": {
        "bug_type": "shared_reference_mutation",
        "bug_location": "config.py::create_config",
        "mechanism_source": "create_config returns the DEFAULTS dict object directly",
        "mechanism_property": "returned config shares mutable state with the module-level DEFAULTS",
        "mechanism_steps": [
            "create_config returns DEFAULTS by reference",
            "middleware caches the config dict across requests",
            "request-specific mutations contaminate the cached object",
            "the cached object IS the global DEFAULTS",
            "subsequent requests observe corrupted config",
        ],
        "mechanism_outcome": "middleware serves config corrupted by prior request mutations",
        "trap_description": "merge_overrides in config.py correctly copies, making it look like aliasing is handled",
    },

    # ── PARTIAL_UPDATE ──
    "partial_update_a": {
        "bug_type": "incomplete_field_sync",
        "bug_location": "profile.py::update_profile",
        "mechanism_source": "update_profile updates name but not the dependent display_name field",
        "mechanism_property": "dependent fields must be updated atomically when their source changes",
        "mechanism_steps": [
            "update_profile sets the name field",
            "display_name (derived from name) is not updated",
            "subsequent reads of display_name return the stale value",
        ],
        "mechanism_outcome": "display_name is inconsistent with the updated name",
        "trap_description": None,
    },
    "partial_update_b": {
        "bug_type": "incomplete_field_sync",
        "bug_location": "profile.py::update_profile",
        "mechanism_source": "update_profile updates first/last name but not the derived full_name",
        "mechanism_property": "dependent fields must be updated atomically when their source changes",
        "mechanism_steps": [
            "update_profile sets first_name and last_name",
            "full_name (derived from first + last) is not recomputed",
            "subsequent reads of full_name return the stale concatenation",
        ],
        "mechanism_outcome": "full_name does not reflect the updated first/last name",
        "trap_description": "validate_name exists but only validates format, does not fix the sync",
    },
    "partial_update_c": {
        "bug_type": "incomplete_field_sync",
        "bug_location": "profile.py::update_profile",
        "mechanism_source": "update_profile updates email but not verified flag or cached_greeting",
        "mechanism_property": "dependent fields must be updated atomically when their source changes",
        "mechanism_steps": [
            "update_profile sets the email field",
            "verified flag is not reset to False",
            "cached_greeting (contains old email) is not invalidated",
        ],
        "mechanism_outcome": "profile shows verified=True for a new unverified email, greeting shows old email",
        "trap_description": "validate_email runs but only checks format, does not update the verified flag",
    },

    # ── STALE_CACHE ──
    "stale_cache_a": {
        "bug_type": "cache_invalidation_missing",
        "bug_location": "catalog.py::update_product",
        "mechanism_source": "update_product writes to DB but does not invalidate the cache",
        "mechanism_property": "cache must be invalidated after any write to the backing store",
        "mechanism_steps": [
            "get_product populates cache on first read",
            "update_product writes new data to the database",
            "cache entry for the product is not invalidated",
            "subsequent get_product returns stale cached value",
        ],
        "mechanism_outcome": "get_product returns outdated data after update_product",
        "trap_description": None,
    },
    "stale_cache_b": {
        "bug_type": "cache_invalidation_missing",
        "bug_location": "catalog.py::update_product",
        "mechanism_source": "update_product writes to DB but does not call cache.invalidate()",
        "mechanism_property": "cache must be invalidated after any write to the backing store",
        "mechanism_steps": [
            "get_product populates cache on first read",
            "update_product writes new data to the database",
            "cache.invalidate() is not called",
            "subsequent get_product returns stale cached value",
        ],
        "mechanism_outcome": "get_product returns outdated data after update_product",
        "trap_description": "cache.warm() exists but pre-populates from DB, does not invalidate stale entries",
    },
    "stale_cache_c": {
        "bug_type": "cache_invalidation_missing",
        "bug_location": "catalog.py::update_product",
        "mechanism_source": "update_product invalidates shared cache but not the local cache layer",
        "mechanism_property": "all cache layers must be invalidated after a write",
        "mechanism_steps": [
            "two-layer cache: local (fast) and shared (distributed)",
            "update_product invalidates the shared cache",
            "local cache still holds the stale entry",
            "api reads local cache first, gets stale data",
        ],
        "mechanism_outcome": "get_product returns stale data from local cache despite shared cache being invalidated",
        "trap_description": "invalidating the shared cache looks sufficient, but the local cache is a separate layer that also needs invalidation",
    },

    # ── LAZY_INIT ──
    "lazy_init_a": {
        "bug_type": "eager_capture_breaks_lifecycle",
        "bug_location": "service.py::get_settings",
        "mechanism_source": "settings value captured eagerly at module import time",
        "mechanism_property": "configuration values must be read lazily so resets take effect",
        "mechanism_steps": [
            "module-level code captures config value at import time",
            "reset_settings updates the config source",
            "get_settings returns the captured (stale) value, not the current one",
        ],
        "mechanism_outcome": "reset_settings has no effect on subsequent get_settings calls",
        "trap_description": None,
    },
    "lazy_init_b": {
        "bug_type": "eager_capture_breaks_lifecycle",
        "bug_location": "client.py::get_db_url",
        "mechanism_source": "client.py captures config at import time into a module-level variable",
        "mechanism_property": "configuration values must be read lazily so resets take effect",
        "mechanism_steps": [
            "client module captures config value at import time",
            "reset_settings updates the config source",
            "client still holds the import-time snapshot",
            "get_db_url returns the stale captured value",
        ],
        "mechanism_outcome": "config reset does not propagate to client module",
        "trap_description": "client imports the config module correctly, but captures the value eagerly rather than reading lazily",
    },
    "lazy_init_c": {
        "bug_type": "eager_capture_breaks_lifecycle",
        "bug_location": "client.py::get_api_key",
        "mechanism_source": "config→client→handler chain where client captures config eagerly",
        "mechanism_property": "configuration values must be read lazily so resets take effect",
        "mechanism_steps": [
            "config module holds the settings",
            "client module captures config at import time",
            "handler module uses client's captured value",
            "reset_settings updates config but client/handler have stale copies",
        ],
        "mechanism_outcome": "handler uses stale config despite reset",
        "trap_description": "client.refresh() exists but handler doesn't call it after reset",
    },

    # ── MUTABLE_DEFAULT ──
    "mutable_default_a": {
        "bug_type": "mutable_default_accumulation",
        "bug_location": "queue.py::enqueue",
        "mechanism_source": "enqueue uses a mutable default argument (queue=[])",
        "mechanism_property": "each function call must start with an independent empty collection",
        "mechanism_steps": [
            "enqueue has default parameter queue=[]",
            "Python evaluates the default once at function definition",
            "first call appends to the shared list",
            "second call sees items from the first call",
        ],
        "mechanism_outcome": "tasks accumulate across calls, producing duplicate/stale entries",
        "trap_description": None,
    },
    "mutable_default_b": {
        "bug_type": "mutable_default_accumulation",
        "bug_location": "worker.py::process_batch",
        "mechanism_source": "process_batch uses a mutable default argument (seen=set())",
        "mechanism_property": "each function call must start with an independent empty collection",
        "mechanism_steps": [
            "process_batch has default parameter seen=set()",
            "Python evaluates the default once at function definition",
            "first call adds IDs to the shared seen set",
            "second call skips valid tasks whose IDs are already in seen",
        ],
        "mechanism_outcome": "valid tasks are incorrectly skipped in subsequent calls",
        "trap_description": "the seen set looks like a deduplication optimization, masking that it persists across calls",
    },
    "mutable_default_c": {
        "bug_type": "mutable_default_accumulation",
        "bug_location": "scheduler.py::with_history",
        "mechanism_source": "with_history decorator creates a shared mutable list in its closure",
        "mechanism_property": "each decorated function call must start with an independent history",
        "mechanism_steps": [
            "with_history defines history=[] in the decorator closure",
            "the closure is shared across all calls to the decorated function",
            "each call appends to the shared history list",
            "history accumulates across all invocations",
        ],
        "mechanism_outcome": "decorated functions carry history from prior calls, producing incorrect state",
        "trap_description": "decorator closure hides the sharing — the list is not visible as a default argument",
    },

    # ── EFFECT_ORDER ──
    "effect_order_a": {
        "bug_type": "batch_level_side_effect",
        "bug_location": "processor.py::process_batch",
        "mechanism_source": "snapshot/side-effect emitted once at batch level instead of per item",
        "mechanism_property": "one side effect must be produced per item processed",
        "mechanism_steps": [
            "process_batch iterates over items and processes each",
            "snapshot is taken once after the loop (batch level)",
            "verify_consistency expects one snapshot per item",
        ],
        "mechanism_outcome": "verify_consistency fails because snapshot count does not match item count",
        "trap_description": None,
    },
    "effect_order_b": {
        "bug_type": "batch_level_side_effect",
        "bug_location": "processor.py::process_batch",
        "mechanism_source": "emit_event called once at batch level instead of per item",
        "mechanism_property": "one side effect must be produced per item processed",
        "mechanism_steps": [
            "process_batch iterates over items",
            "emit_event is called once after the loop",
            "verification checks that event count equals item count",
        ],
        "mechanism_outcome": "event count is 1 regardless of how many items were processed",
        "trap_description": "batching the emit looks like a performance optimization",
    },
    "effect_order_c": {
        "bug_type": "batch_level_side_effect",
        "bug_location": "processor.py::process_batch",
        "mechanism_source": "audit_log called once at batch level instead of per item",
        "mechanism_property": "one side effect must be produced per item processed",
        "mechanism_steps": [
            "process_batch iterates over items",
            "audit_log is called once after the loop",
            "verify_audit checks for per-item audit entries",
        ],
        "mechanism_outcome": "audit log has one entry instead of one per item",
        "trap_description": "fast_process legitimately batches operations (different code path), making batch-level audit look intentional",
    },

    # ── USE_BEFORE_SET ──
    "use_before_set_a": {
        "bug_type": "conditional_variable_unset",
        "bug_location": "transform.py::transform",
        "mechanism_source": "result variable set only inside an if-branch, read unconditionally after",
        "mechanism_property": "variables must be initialized before use on all code paths",
        "mechanism_steps": [
            "transform sets result inside an if-branch (when data is non-empty)",
            "empty data skips the if-branch",
            "code after the branch reads result unconditionally",
            "NameError on empty input",
        ],
        "mechanism_outcome": "NameError when input data is empty",
        "trap_description": None,
    },
    "use_before_set_b": {
        "bug_type": "conditional_variable_unset",
        "bug_location": "loader.py::load",
        "mechanism_source": "status variable set only on success path, read unconditionally",
        "mechanism_property": "variables must be initialized before use on all code paths",
        "mechanism_steps": [
            "loader sets status only when load succeeds",
            "on failure, status is never assigned",
            "pipeline reads loader.status unconditionally",
        ],
        "mechanism_outcome": "AttributeError or NameError when load fails",
        "trap_description": "loader.status looks like it should always be set because the success path is the common case",
    },
    "use_before_set_c": {
        "bug_type": "conditional_variable_unset",
        "bug_location": "pipeline.py::find_best",
        "mechanism_source": "variable set inside loop body, read after loop",
        "mechanism_property": "variables must be initialized before use on all code paths",
        "mechanism_steps": [
            "find_best sets best_item inside a for-loop body",
            "if items is empty, loop body never executes",
            "code after the loop reads best_item",
        ],
        "mechanism_outcome": "NameError when items list is empty",
        "trap_description": "adding a default inside the loop body (wrong scope) doesn't help when loop doesn't execute",
    },

    # ── RETRY_DUP ──
    "retry_dup_a": {
        "bug_type": "retry_missing_break",
        "bug_location": "sender.py::retry_send",
        "mechanism_source": "retry_send always executes retry iteration regardless of success",
        "mechanism_property": "retry loop must stop on success to prevent duplicate operations",
        "mechanism_steps": [
            "retry_send calls send()",
            "send succeeds on first attempt",
            "retry logic does not break on success",
            "send is called again, producing a duplicate",
        ],
        "mechanism_outcome": "message appears twice in the sent store",
        "trap_description": None,
    },
    "retry_dup_b": {
        "bug_type": "retry_missing_break",
        "bug_location": "sender.py::send_with_retry",
        "mechanism_source": "send_with_retry does not break on success, duplicating store entry and notification",
        "mechanism_property": "retry loop must stop on success to prevent duplicate operations",
        "mechanism_steps": [
            "send_with_retry calls send()",
            "send succeeds and appends to store",
            "retry loop continues without break",
            "send is called again, appending a second entry and notification",
        ],
        "mechanism_outcome": "duplicate store entries and duplicate notifications",
        "trap_description": "store.append is non-idempotent — each call adds another entry",
    },
    "retry_dup_c": {
        "bug_type": "retry_missing_break",
        "bug_location": "pipeline.py::ingest",
        "mechanism_source": "nested retry in pipeline causes exponential duplicate execution",
        "mechanism_property": "retry loop must stop on success to prevent duplicate operations",
        "mechanism_steps": [
            "ingest has its own retry loop",
            "inner send also has retry logic",
            "neither breaks on success",
            "duplicates multiply exponentially across retry layers",
        ],
        "mechanism_outcome": "exponential number of duplicate messages",
        "trap_description": "adding an outer retry makes the duplication worse, not better",
    },

    # ── PARTIAL_ROLLBACK ──
    "partial_rollback_a": {
        "bug_type": "missing_compensation",
        "bug_location": "order.py::place_order",
        "mechanism_source": "place_order reserves inventory then charges; charge failure leaves inventory reserved",
        "mechanism_property": "failed multi-step operations must not leave partial state",
        "mechanism_steps": [
            "place_order calls reserve_inventory (succeeds)",
            "place_order calls charge_payment (fails)",
            "no exception handler to release the reserved inventory",
        ],
        "mechanism_outcome": "inventory is permanently reserved for a failed order",
        "trap_description": None,
    },
    "partial_rollback_b": {
        "bug_type": "missing_compensation",
        "bug_location": "order_service.py::place_order",
        "mechanism_source": "place_order reserves inventory then calls gateway; gateway failure leaves inventory reserved",
        "mechanism_property": "failed multi-step operations must not leave partial state",
        "mechanism_steps": [
            "place_order calls reserve_inventory via OrderService (succeeds)",
            "place_order calls payment gateway (fails)",
            "no compensation to release inventory through OrderService",
        ],
        "mechanism_outcome": "inventory reserved but order never completed",
        "trap_description": "notifications list is present but not related to the rollback bug",
    },
    "partial_rollback_c": {
        "bug_type": "missing_compensation",
        "bug_location": "order_service.py::place_order",
        "mechanism_source": "gateway fails after reserve+audit; must undo both reserve and audit",
        "mechanism_property": "failed multi-step operations must not leave partial state",
        "mechanism_steps": [
            "place_order reserves inventory (succeeds)",
            "place_order creates audit entry (succeeds)",
            "place_order calls payment gateway (fails)",
            "neither inventory nor audit entry is rolled back",
        ],
        "mechanism_outcome": "orphaned inventory reservation and audit entry for a failed order",
        "trap_description": "retrying the gateway instead of rolling back — retry may also fail and leaves partial state longer",
    },

    # ── TEMPORAL_DRIFT ──
    "temporal_drift_a": {
        "bug_type": "computation_on_wrong_stage_data",
        "bug_location": "pipeline.py::pipeline",
        "mechanism_source": "raw_stats computed after transform step instead of before",
        "mechanism_property": "raw_stats must operate on original untransformed data",
        "mechanism_steps": [
            "pipeline transforms the data (normalize, clean, etc.)",
            "raw_stats is called on the transformed data",
            "raw_stats returns normalized values instead of raw values",
        ],
        "mechanism_outcome": "raw_stats reports transformed values, not actual raw statistics",
        "trap_description": None,
    },
    "temporal_drift_b": {
        "bug_type": "computation_on_wrong_stage_data",
        "bug_location": "pipeline.py::pipeline",
        "mechanism_source": "raw_stats called on cleaned (post-transform) data",
        "mechanism_property": "raw_stats must operate on original untransformed data",
        "mechanism_steps": [
            "pipeline cleans/transforms data",
            "raw_stats is called on the cleaned data",
            "raw_stats returns cleaned values, not raw values",
        ],
        "mechanism_outcome": "raw_stats reports cleaned values instead of original raw statistics",
        "trap_description": "summarize_for_display looks similar to raw_stats but serves a different purpose",
    },
    "temporal_drift_c": {
        "bug_type": "computation_on_wrong_stage_data",
        "bug_location": "pipeline.py::pipeline",
        "mechanism_source": "raw_stats called after transform in a 4-stage pipeline",
        "mechanism_property": "raw_stats must operate on original untransformed data",
        "mechanism_steps": [
            "4-stage pipeline: load → transform → analyze → export",
            "raw_stats is called in the analyze stage on transformed data",
            "cross-file consumer reads raw_stats expecting pre-transform values",
        ],
        "mechanism_outcome": "downstream consumer gets transformed values labeled as raw",
        "trap_description": "consolidating raw_stats and summarize looks clean but they operate on different stage data (different keys)",
    },

    # ── MISSING_BRANCH ──
    "missing_branch_a": {
        "bug_type": "unhandled_role",
        "bug_location": "permissions.py::get_permissions",
        "mechanism_source": "get_permissions handles admin and user but not moderator",
        "mechanism_property": "all valid roles must have explicit permission mappings",
        "mechanism_steps": [
            "get_permissions checks role against known branches",
            "moderator role is not handled",
            "function returns None for moderator",
        ],
        "mechanism_outcome": "moderator gets no permissions (None) instead of correct permission set",
        "trap_description": None,
    },
    "missing_branch_b": {
        "bug_type": "unhandled_role",
        "bug_location": "auth.py::get_access",
        "mechanism_source": "dispatch dict is missing the guest role entry",
        "mechanism_property": "all valid roles must have explicit permission mappings",
        "mechanism_steps": [
            "get_access uses a dict dispatch for role → permissions",
            "guest role is not in the dispatch dict",
            "dict.get returns empty default for guest",
        ],
        "mechanism_outcome": "guest role silently gets empty permissions",
        "trap_description": "validate_role exists but only validates that the role string is non-empty, doesn't check dispatch coverage",
    },
    "missing_branch_c": {
        "bug_type": "unhandled_role",
        "bug_location": "auth.py::authorize",
        "mechanism_source": "middleware handles service_account but auth.authorize does not",
        "mechanism_property": "all valid roles must have explicit permission mappings in all auth layers",
        "mechanism_steps": [
            "middleware correctly handles service_account role",
            "middleware calls auth.authorize for permission check",
            "auth.authorize does not have a service_account branch",
            "authorize returns default/denied for service_account",
        ],
        "mechanism_outcome": "service_account is denied despite middleware accepting it",
        "trap_description": "fixing only middleware (where service_account is handled) misses that auth.authorize also needs the branch",
    },

    # ── WRONG_CONDITION ──
    "wrong_condition_a": {
        "bug_type": "operator_error",
        "bug_location": "limiter.py::is_rate_limited",
        "mechanism_source": "uses > instead of >= in rate limit check",
        "mechanism_property": "boundary condition must include the limit value itself",
        "mechanism_steps": [
            "is_rate_limited checks count > limit",
            "when count == limit, the check is False",
            "one extra request is allowed beyond the limit",
        ],
        "mechanism_outcome": "rate limit allows limit+1 requests instead of limit",
        "trap_description": None,
    },
    "wrong_condition_b": {
        "bug_type": "operator_error",
        "bug_location": "policy.py::is_allowed",
        "mechanism_source": "uses OR instead of AND in compound condition",
        "mechanism_property": "both conditions must be true simultaneously for the policy to apply",
        "mechanism_steps": [
            "is_allowed checks condition_a OR condition_b",
            "either condition alone satisfies the check",
            "should require both conditions (AND)",
        ],
        "mechanism_outcome": "policy is too permissive — allows when only one condition is met",
        "trap_description": "OR reads naturally in English ('allowed if A or B') but the logic requires AND",
    },
    "wrong_condition_c": {
        "bug_type": "operator_error",
        "bug_location": "limiter.py::should_allow",
        "mechanism_source": "operator precedence error in boolean expression",
        "mechanism_property": "boolean expressions must be parenthesized to enforce intended precedence",
        "mechanism_steps": [
            "should_allow has a compound boolean expression",
            "Python operator precedence evaluates it differently than intended",
            "the effective condition does not match the policy",
        ],
        "mechanism_outcome": "rate limiting logic produces wrong allow/deny decisions",
        "trap_description": "the boolean expression reads correctly in English but precedence makes it evaluate differently",
    },

    # ── EARLY_RETURN ──
    "early_return_a": {
        "bug_type": "skipped_side_effect",
        "bug_location": "payment.py::process_payment",
        "mechanism_source": "zero-amount payment returns early, skipping ledger append",
        "mechanism_property": "ledger must have an entry for every call regardless of amount",
        "mechanism_steps": [
            "process_payment checks if amount is zero",
            "zero amount triggers early return",
            "ledger.append is after the early return point",
            "ledger is missing the zero-amount entry",
        ],
        "mechanism_outcome": "verify_ledger fails because ledger count does not match call count",
        "trap_description": None,
    },
    "early_return_b": {
        "bug_type": "skipped_side_effect",
        "bug_location": "payment.py::process_payment",
        "mechanism_source": "duplicate transaction returns cached result, skipping ledger.record()",
        "mechanism_property": "ledger must have an entry for every call regardless of cache hit",
        "mechanism_steps": [
            "process_payment detects duplicate transaction ID",
            "returns cached result immediately",
            "ledger.record() is after the early return",
            "ledger is missing the duplicate-path entry",
        ],
        "mechanism_outcome": "ledger count does not match total call count",
        "trap_description": "ledger.get_summary handles missing entries gracefully, masking the count mismatch",
    },
    "early_return_c": {
        "bug_type": "skipped_side_effect",
        "bug_location": "payment.py::charge",
        "mechanism_source": "cached charge returns early, skipping audit.log_charge()",
        "mechanism_property": "audit must have an entry for every charge call regardless of cache",
        "mechanism_steps": [
            "charge detects cached result",
            "returns cached value immediately",
            "audit.log_charge is after the early return",
            "audit log is missing the cached-path entry",
        ],
        "mechanism_outcome": "audit is incomplete — cached charges are unrecorded",
        "trap_description": "the caching is correct behavior — the bug is only the missing audit call on the cached path",
    },

    # ── INDEX_MISALIGN ──
    "index_misalign_a": {
        "bug_type": "parallel_structure_desync",
        "bug_location": "report.py::add_entry",
        "mechanism_source": "labels.insert(pos) but values.append() — different insertion strategies",
        "mechanism_property": "parallel arrays must use the same insertion strategy to stay aligned",
        "mechanism_steps": [
            "add_entry inserts label at position pos",
            "add_entry appends value at the end",
            "labels and values are now misaligned at index pos",
        ],
        "mechanism_outcome": "label at index i does not correspond to value at index i",
        "trap_description": None,
    },
    "index_misalign_b": {
        "bug_type": "parallel_structure_desync",
        "bug_location": "report.py::add_row",
        "mechanism_source": "delete_column removes header but not corresponding row data",
        "mechanism_property": "parallel structures must be updated together",
        "mechanism_steps": [
            "delete_column removes the header at column index",
            "row data arrays are not updated",
            "headers and row data are now misaligned",
        ],
        "mechanism_outcome": "rendered report shows data under wrong column headers",
        "trap_description": "render looks correct in isolation because it just zips headers with row data",
    },
    "index_misalign_c": {
        "bug_type": "parallel_structure_desync",
        "bug_location": "report.py::add_row",
        "mechanism_source": "insert_column updates headers and rows but not column_widths array",
        "mechanism_property": "all parallel structures must be updated together",
        "mechanism_steps": [
            "insert_column adds header and row data for new column",
            "column_widths array is not updated",
            "column_widths has fewer entries than headers",
        ],
        "mechanism_outcome": "rendering fails or produces wrong widths for columns after the insertion point",
        "trap_description": "recalculate_widths method exists but is not called after insert_column",
    },

    # ── SILENT_DEFAULT ──
    "silent_default_a": {
        "bug_type": "key_name_mismatch",
        "bug_location": "flags.py::is_enabled",
        "mechanism_source": "caller uses camelCase key but dict uses snake_case",
        "mechanism_property": "flag lookup key must exactly match the stored key",
        "mechanism_steps": [
            "is_enabled looks up flag using camelCase name",
            "flags dict stores keys in snake_case",
            "dict.get returns default (False) for the non-matching key",
        ],
        "mechanism_outcome": "flag always returns False regardless of configured value",
        "trap_description": None,
    },
    "silent_default_b": {
        "bug_type": "key_name_mismatch",
        "bug_location": "flags.py::is_analytics_enabled",
        "mechanism_source": "nested config traversal uses wrong intermediate key",
        "mechanism_property": "nested key path must match the actual config structure",
        "mechanism_steps": [
            "is_analytics_enabled traverses nested config dict",
            "uses wrong key at an intermediate level",
            "intermediate lookup returns None/default",
            "falls back to default (False) silently",
        ],
        "mechanism_outcome": "analytics flag always returns False regardless of config",
        "trap_description": "validate_config checks top-level keys only, doesn't catch nested key mismatch",
    },
    "silent_default_c": {
        "bug_type": "key_name_mismatch",
        "bug_location": "flags.py::is_enabled",
        "mechanism_source": "environment variable key name does not match expected key",
        "mechanism_property": "env var lookup key must exactly match the set variable name",
        "mechanism_steps": [
            "is_enabled tries env var lookup",
            "env var name doesn't match (e.g., FEATURE_X vs FEATURE-X)",
            "falls through to config lookup",
            "config key also mismatches",
            "falls through to hardcoded default",
        ],
        "mechanism_outcome": "flag returns hardcoded default, ignoring both env var and config",
        "trap_description": "the fallback chain (env → config → default) looks resilient, masking that neither lookup actually matches",
    },

    # ── SINGLETON / L3 CASES ──
    "l3_state_pipeline": {
        "bug_type": "removed_causally_necessary_steps",
        "bug_location": "pipeline.py::process_batch",
        "mechanism_source": "commit() and freeze_view() removed from process_batch as 'redundant'",
        "mechanism_property": "commit and freeze_view are independently necessary: commit for the frozen gate, freeze_view for view consistency",
        "mechanism_steps": [
            "process_batch originally called commit(st) and freeze_view(st)",
            "both were removed as apparently redundant",
            "commit sets frozen=True which get_committed_total depends on",
            "freeze_view rebuilds view from sorted stable for consistency",
            "without both, committed total and view are incorrect",
        ],
        "mechanism_outcome": "get_committed_total returns wrong value and view is inconsistent with stable state",
        "trap_description": "removing commit() or merging stage+commit loses the frozen gate; removing freeze_view breaks preview semantics",
    },
    "cache_invalidation_order": {
        "bug_type": "ordering_dependency_removed",
        "bug_location": "service.py::update_record",
        "mechanism_source": "invalidate-then-set ordering in update_record is intentional for version tracking",
        "mechanism_property": "invalidation must precede cache set for conditional cache versioning to work",
        "mechanism_steps": [
            "update_record invalidates cache (bumps version counter)",
            "update_record sets new cache value (uses version for conditional write)",
            "removing the 'redundant' invalidation breaks the version counter",
            "cache_conditional_set silently fails without the version bump",
        ],
        "mechanism_outcome": "cache is not updated — read_record returns stale data",
        "trap_description": "the invalidation looks redundant before a set, but it's required for the version-tracking protocol",
    },
    "feature_flag_drift": {
        "bug_type": "parameter_not_propagated",
        "bug_location": "api.py::checkout",
        "mechanism_source": "checkout accepts use_new_pricing param but pricing.compute_price reads global flag instead",
        "mechanism_property": "parameter must propagate through the entire call chain to the point of use",
        "mechanism_steps": [
            "checkout accepts use_new_pricing parameter",
            "checkout calls create_invoice → billing → pricing",
            "pricing.compute_price reads the global is_enabled flag",
            "the use_new_pricing parameter is never passed to compute_price",
        ],
        "mechanism_outcome": "checkout(use_new_pricing=True) has no effect — pricing uses global flag state",
        "trap_description": "passing the flag to checkout only looks correct, but compute_price still reads the global, ignoring the parameter",
    },
    "invariant_partial_fail": {
        "bug_type": "missing_rollback_on_failure",
        "bug_location": "transfer_service.py::execute_transfer",
        "mechanism_source": "execute_transfer debits sender then may fail before crediting receiver",
        "mechanism_property": "sender.balance + receiver.balance must be conserved at all times",
        "mechanism_steps": [
            "execute_transfer debits sender.balance",
            "credit to receiver may fail (exception)",
            "no exception handler to restore sender.balance",
            "money is lost — debited from sender but never credited to receiver",
        ],
        "mechanism_outcome": "balance conservation invariant violated — total money decreases on failure",
        "trap_description": "extracting a clean helper and moving logging to a wrapper improves observability but does not add rollback",
    },
    "async_race_lock": {
        "bug_type": "lock_removal_breaks_atomicity",
        "bug_location": "worker.py::process_item",
        "mechanism_source": "task asks to replace process_item (locked) with quick_increment (unlocked)",
        "mechanism_property": "run_verified requires atomic read-increment-read which depends on the lock",
        "mechanism_steps": [
            "process_item uses try_lock/unlock for atomic counting",
            "task asks to replace with quick_increment (no locking)",
            "run_verified depends on atomic read-increment-read",
            "without the lock, concurrent access produces incorrect counts",
        ],
        "mechanism_outcome": "run_verified gets incorrect counter values due to race condition",
        "trap_description": "quick_increment looks simpler and functionally equivalent, but removes the atomicity guarantee run_verified depends on",
    },
    "hidden_dep_multihop": {
        "bug_type": "function_semantic_mismatch",
        "bug_location": "user_service.py::save_user",
        "mechanism_source": "two cache write functions have different overwrite semantics",
        "mechanism_property": "save_user must use unconditional overwrite (cache_put) for write-through",
        "mechanism_steps": [
            "cache_put always overwrites (unconditional write-through)",
            "cache_put_if_absent only writes if key is missing (conditional)",
            "save_user uses sync_user_to_cache which calls cache_put",
            "consolidating to cache_put_if_absent breaks write-through updates",
        ],
        "mechanism_outcome": "get_display_name returns stale name after save_user because cache was not overwritten",
        "trap_description": "cache_put_if_absent looks safer (no accidental overwrite), but save_user needs unconditional overwrite",
    },
    "config_shadowing": {
        "bug_type": "structural_default_masked_by_override",
        "bug_location": "defaults.py::DEFAULTS",
        "mechanism_source": "DEFAULTS has wrong timeout value (5 instead of 30), masked by env override on request path",
        "mechanism_property": "DEFAULTS must contain correct values because not all paths apply overrides",
        "mechanism_steps": [
            "DEFAULTS dict has timeout: 5 (wrong, should be 30)",
            "request path calls get_config() which applies env override → gets 30",
            "background path calls get_defaults() directly → gets 5",
            "env override masks the wrong default on the request path",
        ],
        "mechanism_outcome": "background tasks use timeout=5 instead of 30, causing premature timeouts",
        "trap_description": "fixing background to call get_config() instead of get_defaults() is a contingent fix that passes the test but leaves the structural cause (wrong default value)",
    },
    "commit_gate": {
        "bug_type": "absent_causally_necessary_steps",
        "bug_location": "pipeline.py::process_batch",
        "mechanism_source": "commit() and freeze_view() both absent from process_batch",
        "mechanism_property": "commit sets the frozen gate for selectors; freeze_view rebuilds view from sorted stable",
        "mechanism_steps": [
            "process_batch should call commit(st) and freeze_view(st)",
            "commit sets frozen=True which gate functions check",
            "freeze_view rebuilds view from sorted stable for consistency",
            "without both, selectors see unfrozen state and view is stale",
        ],
        "mechanism_outcome": "committed total is wrong and view does not match stable state",
        "trap_description": "restoring only commit passes the total check but fails the consistency check — both are needed",
    },
    "overdetermination": {
        "bug_type": "stale_cache_overwrite",
        "bug_location": "api.py::update_product",
        "mechanism_source": "two writers both write product data; write_cached uses stale cache on second call",
        "mechanism_property": "only the authoritative writer should persist the final value",
        "mechanism_steps": [
            "update_product calls write_fresh (computes correct value)",
            "update_product calls write_cached (reads from cache, may be stale)",
            "write_cached runs second and overwrites write_fresh's correct value",
        ],
        "mechanism_outcome": "store contains stale cached value instead of freshly computed value",
        "trap_description": "removing write_fresh (the more complex writer) instead of write_cached (the stale one) makes the problem worse",
    },
    "lost_update": {
        "bug_type": "non_atomic_read_modify_write",
        "bug_location": "counter.py::make_increment_steps",
        "mechanism_source": "read and write are separate non-atomic steps",
        "mechanism_property": "read-modify-write must be a single atomic operation",
        "mechanism_steps": [
            "increment reads current value",
            "increment computes new value (current + 1)",
            "increment writes new value",
            "two interleaved increments both read 0, both write 1",
        ],
        "mechanism_outcome": "after N increments, value is less than N (updates lost)",
        "trap_description": "locking only the write step still allows both reads to see the same stale value",
    },
    "check_then_act": {
        "bug_type": "non_atomic_check_then_act",
        "bug_location": "bank.py::make_withdraw_steps",
        "mechanism_source": "balance check and debit are separate non-atomic steps",
        "mechanism_property": "check-then-act must be a single atomic operation",
        "mechanism_steps": [
            "withdraw checks balance >= amount",
            "withdraw debits balance",
            "two interleaved withdrawals both pass the check before either debits",
            "both debits succeed, overdrawing the account",
        ],
        "mechanism_outcome": "balance goes negative — overdraft despite check",
        "trap_description": "locking only the check step still allows both checks to pass before either debit executes",
    },
    "ordering_dependency": {
        "bug_type": "ordering_violation_no_buffer",
        "bug_location": "pipeline.py::process",
        "mechanism_source": "process runs before init and fails; items are dropped instead of buffered",
        "mechanism_property": "all items must be processed regardless of arrival order",
        "mechanism_steps": [
            "process is called before init has run",
            "process detects uninitialized state",
            "process logs error and skips the item",
            "item is permanently lost",
        ],
        "mechanism_outcome": "items that arrive before init are silently dropped",
        "trap_description": "adding a lock provides mutual exclusion but not ordering — items still arrive before init",
    },
    "false_fix_deadlock": {
        "bug_type": "circular_lock_ordering",
        "bug_location": "resources.py::make_transfer_b_to_a_steps",
        "mechanism_source": "opposite lock ordering between transfer_a_to_b and transfer_b_to_a",
        "mechanism_property": "locks must be acquired in a canonical global order to prevent deadlock",
        "mechanism_steps": [
            "transfer_a_to_b locks A then B",
            "transfer_b_to_a locks B then A",
            "concurrent execution: one holds A waiting for B, other holds B waiting for A",
            "deadlock — neither can proceed",
        ],
        "mechanism_outcome": "deadlock when transfers run concurrently in opposite directions",
        "trap_description": "removing locks introduces races; adding timeout hides the deadlock without fixing ordering",
    },
}


def main():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    case_ids = {c["id"] for c in cases}
    enrichment_ids = set(ENRICHMENTS.keys())

    missing = case_ids - enrichment_ids
    extra = enrichment_ids - case_ids
    if missing:
        print(f"ERROR: Missing enrichments for: {sorted(missing)}")
        return
    if extra:
        print(f"WARNING: Extra enrichments for non-existent cases: {sorted(extra)}")

    # Apply enrichments
    for case in cases:
        cid = case["id"]
        ogt = ENRICHMENTS[cid]
        # Validate required fields
        for field in ("bug_type", "bug_location", "mechanism_source",
                      "mechanism_property", "mechanism_steps", "mechanism_outcome"):
            assert field in ogt and ogt[field], f"Missing/empty {field} for {cid}"
        assert isinstance(ogt["mechanism_steps"], list) and len(ogt["mechanism_steps"]) >= 1, \
            f"mechanism_steps must be non-empty list for {cid}"
        case["oracle_ground_truth"] = ogt

    # Write back
    CASES_PATH.write_text(
        json.dumps(cases, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"Enriched {len(cases)} cases with oracle_ground_truth")

    # Consistency check
    print("\n=== CONSISTENCY CHECK ===")
    for case in cases:
        cid = case["id"]
        ogt = case["oracle_ground_truth"]
        gt = case.get("ground_truth_bug", {})
        rf = case.get("reference_fix", {})

        # Check bug_type matches
        if ogt["bug_type"] != gt.get("type"):
            print(f"  MISMATCH {cid}: ogt.bug_type={ogt['bug_type']} vs gt.type={gt.get('type')}")

        # Check location consistency
        if ogt["bug_location"] != gt.get("location"):
            print(f"  LOCATION {cid}: ogt={ogt['bug_location']} vs gt={gt.get('location')}")

        # Check trap consistency
        trap = case.get("trap", "")
        if trap == "No trap" and ogt.get("trap_description") is not None:
            print(f"  TRAP {cid}: case.trap='No trap' but ogt.trap_description is set")
        if trap != "No trap" and ogt.get("trap_description") is None:
            print(f"  TRAP {cid}: case.trap='{trap}' but ogt.trap_description is None")

    print("\nDone.")


if __name__ == "__main__":
    main()
