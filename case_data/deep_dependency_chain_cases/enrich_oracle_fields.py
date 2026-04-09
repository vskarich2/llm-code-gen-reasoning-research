"""Enrich oracle_ground_truth fields for all DDC cases.

Each variant gets its own mechanism_steps and mechanism_outcome that
describe the causal chain through the VARIANT'S code, not the baseline.

Run: .venv/bin/python case_data/deep_dependency_chain_cases/enrich_oracle_fields.py
"""

import json
from pathlib import Path

CASES_V2 = Path(__file__).resolve().parents[2] / "case_data" / "cases_v2.json"


# ── Shared per-family fields ─────────────────────────────────
# mechanism_source and mechanism_property are always the same
# (the root cause and violated invariant don't change across variants)

SHARED = {
    "auth_context_chain": {
        "mechanism_source": "normalize_context strips the prefix from org_id by splitting on '-' and keeping only the numeric suffix",
        "mechanism_property": "org_id must preserve its full prefix (e.g., 'ORG-100') through normalization for downstream DB lookups to succeed",
    },
    "billing_aggregation_chain": {
        "mechanism_source": "aggregate_usage groups events by local date (ts[:10]) instead of converting to UTC first",
        "mechanism_property": "billing period assignment must use UTC timestamps, not local timestamps, to correctly count units across timezone boundaries",
    },
    "config_derivation_chain": {
        "mechanism_source": "parse_config reads PORT from env as a string and does not convert it to int",
        "mechanism_property": "parsed config port must be an integer so that downstream arithmetic (port * 2) produces a numeric pool_size, not string repetition",
    },
    "event_etl_chain": {
        "mechanism_source": "normalize lowercases all string field values including user_id using v.lower()",
        "mechanism_property": "user_id must preserve its original case because USER_PROFILES keys are case-sensitive (e.g., 'Alice_Smith', not 'alice_smith')",
    },
    "logging_pipeline_chain": {
        "mechanism_source": "collect_events_node truncates severity to 4 characters using severity[:4]",
        "mechanism_property": "severity field must be the full string ('CRITICAL', 'WARNING', 'ERROR', 'INFO') for exact-match counting in the metric aggregator to work",
    },
    "ml_feature_chain": {
        "mechanism_source": "feature_engineer_node computes rolling mean with window_size - 1 instead of window_size",
        "mechanism_property": "rolling mean must average the last window_size values (e.g., window=3 means average of last 3), not window_size - 1 values",
    },
    "search_index_chain": {
        "mechanism_source": "extract_fields includes all string-valued fields from the document in content_fields, not just content keys",
        "mechanism_property": "content_fields must contain only CONTENT_KEYS (title, body, tags), excluding metadata fields (id, author, created_at)",
    },
    "serialization_pipeline_chain": {
        "mechanism_source": "serialize converts created_at from ISO string to epoch integer via EPOCH_TABLE lookup",
        "mechanism_property": "created_at must remain an ISO 8601 string ('YYYY-MM-DDTHH:MM:SS') throughout the pipeline for downstream string-based operations to work",
    },
}


# ── Per-variant fields ───────────────────────────────────────
# Each entry has: mechanism_steps, mechanism_outcome, trap_description

VARIANTS = {
    # ── auth_context ─────────────────────────────────────────
    "auth_context_chain": {
        "mechanism_steps": [
            "normalize_context receives parsed token with org_id='ORG-100'",
            "it splits on '-' and replaces org_id with '100' (the suffix only)",
            "resolve_permissions_node looks up 'ORG-100:alice' in USER_DB but the key is now '100:alice'",
            "lookup fails, user gets default tier with restricted permissions",
            "check_gate_node denies write access because default tier lacks write permission",
        ],
        "mechanism_outcome": "all users with prefixed org IDs (ORG-, DEPT-) are denied access they should have",
        "trap_description": "No trap",
    },
    "auth_context_chain_trap_1": {
        "mechanism_steps": [
            "normalize_context strips org_id prefix: 'ORG-100' becomes '100'",
            "resolve_permissions_node fails to find '100:alice' in USER_DB, assigns default tier",
            "check_gate_node has been patched to grant access for default-tier users",
            "access is granted but with wrong tier — default instead of enterprise",
            "the stripped org_id '100' propagates to audit logs and bypass consumers",
        ],
        "mechanism_outcome": "writes succeed but under the wrong tier (default instead of enterprise), and org_id is corrupted in all downstream consumers",
        "trap_description": "check_gate_node defaults to granted=True for default tier users, masking the denied-access symptom without fixing the org_id corruption in normalize_context",
    },
    "auth_context_chain_trap_3": {
        "mechanism_steps": [
            "normalize_context strips org_id prefix: 'ORG-100' becomes '100'",
            "resolve_permissions_node fails lookup for '100:alice', retries with 'ORG-' prefix prepended → 'ORG-100:alice' succeeds",
            "users with ORG- prefix resolve correctly",
            "users with DEPT- prefix (e.g., 'DEPT-50') get 'ORG-' prepended → 'ORG-50:carol' which does not exist in USER_DB",
            "DEPT- users still fail lookup and get default tier",
        ],
        "mechanism_outcome": "ORG-prefixed users work but DEPT-prefixed and other non-ORG users still fail because the resolver guesses 'ORG-' as the prefix",
        "trap_description": "resolve_permissions_node retries lookup with 'ORG-' prefix prepended, which works for ORG-prefixed orgs but fails for DEPT- or other prefixes because the real prefix was stripped by normalize_context",
    },
    "auth_context_chain_trap_4": {
        "mechanism_steps": [
            "normalize_context strips org_id prefix: 'ORG-100' becomes '100'",
            "resolve_permissions_node tries all known prefixes (ORG-, DEPT-, etc.) to reconstruct the key",
            "lookup succeeds for most users because the correct prefix is tried",
            "permissions are resolved correctly through the main path",
            "but the normalized context still contains org_id='100' (stripped), which bypass consumers read directly",
        ],
        "mechanism_outcome": "permission checks pass but audit logs and replay consumers see the corrupted org_id '100' instead of 'ORG-100'",
        "trap_description": "resolve_permissions_node tries all known prefixes to find a match, succeeding for the main path but leaving the corrupted org_id in the normalized context for bypass consumers that read it directly",
    },
    "auth_context_chain_trap_5": {
        "mechanism_steps": [
            "normalize_context strips org_id prefix: 'ORG-100' becomes '100'",
            "normalize_context also stores the original value in canonical_org_id='ORG-100'",
            "resolve_permissions_node reads canonical_org_id for lookup, finds 'ORG-100:alice' in USER_DB",
            "permissions resolve correctly using the alternate field",
            "but org_id in the normalized context is still '100', and bypass consumers read org_id, not canonical_org_id",
        ],
        "mechanism_outcome": "permission resolution works via canonical_org_id but org_id remains corrupted; any consumer reading org_id directly sees '100' instead of 'ORG-100'",
        "trap_description": "normalize_context adds a canonical_org_id field with the original value while still stripping org_id, so resolve_permissions_node succeeds using the alternate field but bypass consumers reading org_id see the stripped value",
    },

    # ── billing_aggregation ──────────────────────────────────
    "billing_aggregation_chain": {
        "mechanism_steps": [
            "aggregate_usage receives events with local timestamps and a tz_offset field",
            "it extracts the billing period by slicing ts[:10] (local date), ignoring tz_offset",
            "boundary events (e.g., local 00:30 Apr 2 with tz=+1 = UTC 23:30 Apr 1) get assigned to the wrong period",
            "April 1 shows 85 units instead of 100 because 15 boundary events are misassigned to April 2",
            "resolve_plan maps 85 units to 'growth' tier instead of correct 'enterprise' tier",
            "compute_charges applies growth rate ($0.10) instead of enterprise rate ($0.05)",
        ],
        "mechanism_outcome": "customer is overcharged at $8.50 (growth) instead of correct $5.00 (enterprise) due to timezone misattribution of boundary events",
        "trap_description": "No trap",
    },
    "billing_aggregation_chain_trap_1": {
        "mechanism_steps": [
            "aggregate_usage groups by local date, misassigning 15 boundary events → April 1 = 85 units",
            "resolve_plan maps 85 units to growth tier",
            "compute_charges computes 85 × $0.10 = $8.50",
            "build_invoice detects growth tier with total > $8 and overrides to enterprise pricing",
            "primary customer's invoice shows correct enterprise rate",
            "but a legitimate 85-unit customer (no timezone issue) also gets overridden to enterprise, paying $4.25 instead of correct $8.50",
        ],
        "mechanism_outcome": "primary customer's bill looks correct but legitimate growth-tier customers are incorrectly downgraded to enterprise pricing by the hardcoded override",
        "trap_description": "build_invoice overrides growth-tier invoices exceeding $8 to enterprise pricing, fixing the primary customer's bill but incorrectly downgrading legitimate 85-unit growth customers",
    },
    "billing_aggregation_chain_trap_3": {
        "mechanism_steps": [
            "aggregate_usage applies a hardcoded -1 hour shift to all timestamps before extracting the date",
            "for tz=+1 customers, this correctly converts local to UTC: boundary events at local 00:30 Apr 2 → 23:30 Apr 1",
            "April 1 correctly shows 100 units for the primary customer",
            "for tz=-5 customers, the -1 hour shift is wrong: local 23:00 Apr 1 should be UTC 04:00 Apr 2, but shift gives 22:00 Apr 1",
            "tz=-5 April 1 shows 100 units instead of correct 80 because boundary events aren't shifted far enough",
        ],
        "mechanism_outcome": "primary customer (tz=+1) is billed correctly by coincidence, but any other timezone produces wrong unit counts because the shift is hardcoded to -1 hour instead of using actual tz_offset",
        "trap_description": "aggregate_usage applies a hardcoded -1 hour UTC shift, which works for the primary customer (tz=+1) but produces wrong results for any other timezone (e.g., tz=-5 needs a +5 hour shift)",
    },
    "billing_aggregation_chain_trap_4": {
        "mechanism_steps": [
            "aggregate_usage calls _to_utc with hardcoded tz=1 instead of dataset_dict['tz_offset']",
            "for the primary customer (actual tz=+1), the hardcoded value matches → correct UTC conversion",
            "April 1 correctly shows 100 units for the primary customer",
            "for tz=-5 customers, _to_utc shifts by -1 hour (hardcoded) instead of +5 hours",
            "boundary events are misassigned, producing wrong unit counts for non-+1 timezones",
        ],
        "mechanism_outcome": "primary billing is correct because hardcoded tz=1 matches the primary customer's actual timezone, but all other timezones get wrong unit counts",
        "trap_description": "aggregate_usage applies a hardcoded tz=1 offset ignoring the actual tz_offset from the dataset, producing correct results only when the real offset happens to be +1",
    },
    "billing_aggregation_chain_trap_5": {
        "mechanism_steps": [
            "aggregate_usage groups by local date (buggy), producing units=85 for April 1",
            "aggregate_usage also computes corrected_units using proper _to_utc conversion, getting 100",
            "both units=85 and corrected_units=100 are stored in the usage record",
            "resolve_plan reads corrected_units and correctly assigns enterprise tier",
            "invoice shows correct enterprise pricing at $5.00",
            "but audit dashboards read the original units field and display 85 instead of 100",
        ],
        "mechanism_outcome": "invoice is correct via corrected_units but audit and monitoring consumers read the original units field and show the wrong count of 85",
        "trap_description": "aggregate_usage adds a corrected_units field using proper UTC conversion alongside the buggy units field; resolve_plan reads corrected_units but audit consumers still read the original wrong units",
    },

    # ── config_derivation ────────────────────────────────────
    "config_derivation_chain": {
        "mechanism_steps": [
            "parse_config reads env['PORT'] ('8080') and stores it as a string in parsed['port']",
            "derive_settings_node computes pool_size = port * 2, which for string '8080' yields '80808080' (string repetition)",
            "derive_settings_node computes listen_address as 'host:8080' (happens to look correct as a string)",
            "init_service_node receives pool_size='80808080' (a string), detects invalid type, returns status='error'",
        ],
        "mechanism_outcome": "service fails to initialize with invalid pool_size error because string multiplication produced '80808080' instead of integer 16160",
        "trap_description": "No trap",
    },
    "config_derivation_chain_trap_1": {
        "mechanism_steps": [
            "parse_config stores PORT as string '8080'",
            "derive_settings_node computes pool_size = '8080' * 2 = '80808080' (string repeat)",
            "init_service_node detects the invalid pool_size and falls back to hardcoded 16160",
            "service starts successfully on PORT=8080 with pool_size=16160 (happens to be correct)",
            "on PORT=443, correct pool_size should be 886 but the fallback still gives 16160",
        ],
        "mechanism_outcome": "service starts but with a hardcoded fallback pool_size that is only correct for PORT=8080; other ports get the wrong pool_size",
        "trap_description": "init_service_node caps pool_size to 16160 when it's a string or exceeds 20000, fixing the primary port but producing the wrong fallback value for other ports (e.g., PORT=443 should give 886, not 16160)",
    },
    "config_derivation_chain_trap_3": {
        "mechanism_steps": [
            "parse_config stores PORT as string '8080'",
            "derive_settings_node casts port to int before computing: pool_size = int('8080') * 2 = 16160",
            "derived settings (pool_size, listen_address) are correct",
            "init_service_node starts successfully",
            "but parsed config still has port='8080' (string), and the config audit endpoint reads parsed config directly",
            "audit reports port_type='str' instead of 'int'",
        ],
        "mechanism_outcome": "service runs correctly but config audit reports port as string type because the parser never converted it — the deriver worked around it locally",
        "trap_description": "derive_settings_node casts port to int before computing pool_size, producing correct derived settings, but the parsed config still has port as a string — the config audit endpoint reports port_type='str'",
    },
    "config_derivation_chain_trap_4": {
        "mechanism_steps": [
            "parse_config stores PORT as string '8080'",
            "derive_settings_node re-reads and converts port from parsed config: int(parsed['port']) = 8080",
            "pool_size = 8080 * 2 = 16160, listen_address = 'host:8080' — both correct",
            "init_service_node starts successfully",
            "but parsed config port is still string '8080', and config audit reads it directly",
        ],
        "mechanism_outcome": "service runs correctly but config audit shows port_type='str' because the parser stores it as string and the deriver's local conversion doesn't propagate back",
        "trap_description": "derive_settings_node re-reads and converts the port value from parsed config before math, producing correct settings, but the parsed config object still contains the string port for bypass consumers",
    },
    "config_derivation_chain_trap_5": {
        "mechanism_steps": [
            "parse_config stores PORT as string '8080' in port, and also stores int 8080 in port_int",
            "derive_settings_node reads port_int (8080) and computes pool_size = 8080 * 2 = 16160",
            "derived settings are correct",
            "init_service_node starts successfully",
            "but config audit reads the port field (not port_int) and reports type 'str'",
        ],
        "mechanism_outcome": "service works via port_int but config audit reads the original port field and reports it as string type, creating an inconsistency between the service's actual port and the audit report",
        "trap_description": "parse_config adds a port_int field alongside the string port; derive_settings_node reads port_int and computes correctly, but the config audit reads the original port field and reports it as type 'str'",
    },

    # ── event_etl ────────────────────────────────────────────
    "event_etl_chain": {
        "mechanism_steps": [
            "normalize iterates all key-value pairs and applies v.lower() to every string value",
            "user_id 'Alice_Smith' becomes 'alice_smith'",
            "enrich_node looks up 'alice_smith' in USER_PROFILES which has key 'Alice_Smith'",
            "case-sensitive lookup fails, user gets tier='unknown' and region='unknown'",
            "write_events outputs events with tier='unknown' for all users",
        ],
        "mechanism_outcome": "all events are written with tier='unknown' because the normalizer corrupts user_id case, breaking the enricher's profile lookup",
        "trap_description": "No trap",
    },
    "event_etl_chain_trap_1": {
        "mechanism_steps": [
            "normalize lowercases user_id: 'Alice_Smith' → 'alice_smith'",
            "enrich_node lookup fails → tier='unknown'",
            "write_events detects unknown tier on a purchase event and defaults to 'standard'",
            "Alice shows tier='standard' instead of correct 'premium'",
            "replay queue (bypass) still contains lowercased user_id 'alice_smith'",
        ],
        "mechanism_outcome": "purchase events get tier='standard' (wrong — Alice is premium) and the replay queue routes events using lowercased user_ids",
        "trap_description": "write_events defaults unknown-tier purchase events to 'standard', which masks the symptom but assigns the wrong tier (Alice should be 'premium', not 'standard') and leaves the replay queue with lowercased user_ids",
    },
    "event_etl_chain_trap_3": {
        "mechanism_steps": [
            "normalize uses a heuristic: values with '_' or '-' are preserved, others are lowercased",
            "Alice_Smith (has '_') → preserved → enrich_node finds her → tier='premium'",
            "Carol-Wu (has '-') → preserved → enrich_node finds her → tier='premium'",
            "SYSADMIN (no separator) → lowercased to 'sysadmin' → not found in USER_PROFILES",
            "SYSADMIN gets tier='unknown' instead of 'admin'",
        ],
        "mechanism_outcome": "users with separators in their names resolve correctly, but users without separators (like SYSADMIN) are still lowercased and fail lookup",
        "trap_description": "normalize uses a heuristic that preserves case for values containing '_' or '-' (working for Alice_Smith and Carol-Wu) but lowercases values without separators (SYSADMIN becomes 'sysadmin', failing lookup)",
    },
    "event_etl_chain_trap_4": {
        "mechanism_steps": [
            "normalize lowercases user_id: 'Alice_Smith' → 'alice_smith'",
            "enrich_node builds a case-insensitive map: {'alice_smith': {...}, 'bob_jones': {...}, ...}",
            "lookup succeeds for all users → correct tiers assigned",
            "write_events outputs correct tier information",
            "but replay queue reads user_id from normalized events, which is still 'alice_smith'",
            "event routing uses lowercased user_id instead of original 'Alice_Smith'",
        ],
        "mechanism_outcome": "enrichment works correctly via case-insensitive lookup but the replay queue (bypass) routes events using lowercased user_ids, causing incorrect downstream routing",
        "trap_description": "enrich_node builds a case-insensitive lookup map {k.lower(): v}, finding all users correctly, but the replay queue (bypass consumer) still contains lowercased user_ids from normalize, causing wrong event routing",
    },
    "event_etl_chain_trap_5": {
        "mechanism_steps": [
            "normalize lowercases user_id: 'Alice_Smith' → 'alice_smith'",
            "normalize also stores original value in original_user_id='Alice_Smith'",
            "enrich_node reads original_user_id for lookup → finds Alice → tier='premium'",
            "write_events outputs correct tier",
            "but replay queue reads user_id (not original_user_id) → routes using 'alice_smith'",
        ],
        "mechanism_outcome": "enrichment works via original_user_id but the replay queue reads the lowercased user_id field, routing events to the wrong destination",
        "trap_description": "normalize adds an original_user_id field with the preserved case while still lowercasing user_id; enrich_node reads original_user_id and resolves correctly, but the replay queue reads user_id and routes with the lowercased value",
    },

    # ── logging_pipeline ─────────────────────────────────────
    "logging_pipeline_chain": {
        "mechanism_steps": [
            "collect_events_node slices each event's severity to 4 chars: 'CRITICAL'→'CRIT', 'WARNING'→'WARN', 'ERROR'→'ERRO', 'INFO'→'INFO'",
            "format_logs_node renders log lines with truncated severity: '[CRIT]' instead of '[CRITICAL]'",
            "aggregate_metrics_node counts by exact severity match against SEVERITY_LEVELS keys",
            "truncated strings 'CRIT', 'WARN', 'ERRO' don't match any key → counted as UNKNOWN",
            "only 'INFO' (already 4 chars) matches; all other events become UNKNOWN",
            "render_dashboard_node shows critical_count=0 and UNKNOWN=4",
        ],
        "mechanism_outcome": "dashboard reports zero critical alerts and 4 unknown events because truncated severity strings don't match the aggregator's exact-match keys",
        "trap_description": "No trap",
    },
    "logging_pipeline_chain_trap_1": {
        "mechanism_steps": [
            "collect_events_node truncates severity: 'CRITICAL'→'CRIT', 'WARNING'→'WARN'",
            "aggregate_metrics_node counts 'CRIT' and 'WARN' as UNKNOWN (no exact match)",
            "render_dashboard_node adds UNKNOWN count to critical_count",
            "primary dataset: 2 CRITICAL + 2 WARNING → 4 UNKNOWN → critical_count=4 (shows alert)",
            "INFO-only dataset: 'WARN' from truncated WARNING → UNKNOWN=1 → critical_count=1 (false alert)",
        ],
        "mechanism_outcome": "dashboard shows alerts on the primary dataset but creates false alerts on datasets without any critical events because truncated WARNING events get promoted to CRITICAL",
        "trap_description": "render_dashboard_node adds UNKNOWN count to critical_count, which shows correct alerts for CRITICAL-containing datasets but creates false alerts on INFO/WARNING-only datasets where truncated 'WARN' becomes UNKNOWN and gets promoted",
    },
    "logging_pipeline_chain_trap_3": {
        "mechanism_steps": [
            "collect_events_node truncates severity: 'CRITICAL'→'CRIT', 'WARNING'→'WARN'",
            "format_logs_node renders log lines with truncated severity: '[CRIT]', '[WARN]'",
            "aggregate_metrics_node uses fuzzy prefix matching: 'CRITICAL'.startswith('CRIT') → counts as CRITICAL",
            "metric counts are correct: CRITICAL=2, WARNING=2, INFO=1",
            "render_dashboard_node shows correct critical_count=2",
            "but compliance export reads severity directly from collected events → 'CRIT', 'WARN'",
            "log lines still display '[CRIT]' not '[CRITICAL]'",
        ],
        "mechanism_outcome": "metrics are correct via fuzzy matching but compliance export and log lines still contain truncated severity strings, disagreeing with the dashboard",
        "trap_description": "aggregate_metrics_node uses fuzzy prefix matching, correctly mapping CRIT→CRITICAL for counting, but the compliance export and log lines still contain truncated severity strings from the collector",
    },
    "logging_pipeline_chain_trap_4": {
        "mechanism_steps": [
            "collect_events_node truncates severity: 'CRITICAL'→'CRIT', 'WARNING'→'WARN'",
            "format_logs_node renders log lines with truncated severity: '[CRIT]', '[WARN]'",
            "aggregate_metrics_node maps truncated strings back via lookup dict: CRIT→CRITICAL, WARN→WARNING",
            "metric counts are correct: CRITICAL=2, WARNING=2, INFO=1",
            "render_dashboard_node shows correct critical_count=2",
            "but compliance export reads severity from collected events → still 'CRIT', 'WARN'",
            "dashboard says CRITICAL=2 but export has zero CRITICAL entries",
        ],
        "mechanism_outcome": "metrics are correct via remapping but compliance export reads the raw truncated severity, creating a disagreement between dashboard and export",
        "trap_description": "aggregate_metrics_node maps truncated strings back to full names via a lookup dict before counting, producing correct metrics, but the compliance export (bypass) reads severity directly from collected events and shows truncated values",
    },
    "logging_pipeline_chain_trap_5": {
        "mechanism_steps": [
            "collect_events_node truncates severity to 4 chars but also stores original_severity",
            "format_logs_node renders log lines using truncated severity: '[CRIT]', '[WARN]'",
            "aggregate_metrics_node reads original_severity for counting → correct metrics",
            "render_dashboard_node shows correct critical_count=2",
            "but compliance export reads severity (not original_severity) → 'CRIT', 'WARN'",
            "log lines display truncated severity",
        ],
        "mechanism_outcome": "metrics are correct via original_severity but compliance export and log lines use the truncated severity field, showing 'CRIT' and 'WARN' instead of full names",
        "trap_description": "collect_events_node adds original_severity alongside the truncated severity field; aggregate_metrics_node uses original_severity for counting, but the compliance export reads severity (truncated) and log lines display '[CRIT]' not '[CRITICAL]'",
    },

    # ── ml_feature ───────────────────────────────────────────
    "ml_feature_chain": {
        "mechanism_steps": [
            "feature_engineer_node sets actual_window = min(window - 1, len(values)) instead of min(window, len(values))",
            "for primary data [10,20,30,40,50] with window=3: actual_window=2 instead of 3",
            "rolling_mean = (40+50)/2 = 45.0 instead of correct (30+40+50)/3 = 40.0",
            "scaler_node standardizes: (45-30)/15 = 1.0 instead of correct (40-30)/15 = 0.667",
            "model_scorer_node computes: 0.5 + 0.3×1.0 = 0.8 instead of correct 0.5 + 0.3×0.667 = 0.7",
        ],
        "mechanism_outcome": "prediction score is 0.8 instead of 0.7 due to the off-by-one window making rolling mean 45 instead of 40",
        "trap_description": "No trap",
    },
    "ml_feature_chain_trap_1": {
        "mechanism_steps": [
            "feature_engineer_node uses window-1: rolling_mean = 45.0 (buggy)",
            "scaler_node standardizes: (45-30)/15 = 1.0",
            "model_scorer_node computes 0.5 + 0.3×1.0 = 0.8, then subtracts 0.1 bias → 0.7",
            "primary score is correct (0.7) by coincidence of the bias matching the error",
            "short dataset [5,15]: both buggy and correct give mean=10, score=0.1, but bias makes it 0.0",
            "varied dataset [10,20,50]: buggy mean=35, correct mean=26.67; error is 8.33, not 5.0 → bias of 0.1 in score space doesn't compensate",
        ],
        "mechanism_outcome": "primary score is correct by coincidence but the hardcoded -0.1 bias over-corrects short datasets and under-corrects varied datasets",
        "trap_description": "model_scorer_node subtracts a hardcoded 0.1 bias from all scores (0.8-0.1=0.7), which works for the primary dataset but over-corrects on short datasets (score 0.1 becomes 0.0) and under-corrects on varied datasets",
    },
    "ml_feature_chain_trap_3": {
        "mechanism_steps": [
            "feature_engineer_node uses window-1: rolling_mean = 45.0 (buggy)",
            "scaler_node subtracts hardcoded 5.0 from rolling_mean before standardizing: 45-5=40",
            "standardized: (40-30)/15 = 0.667 → score = 0.5 + 0.3×0.667 = 0.7",
            "primary score is correct because buggy-correct difference is exactly 5.0",
            "varied dataset [10,20,50]: buggy mean=35, correct mean=26.67 → error is 8.33, not 5.0",
            "scaler subtracts 5.0: 35-5=30, scaled=0, score=0.5 instead of correct 0.433",
        ],
        "mechanism_outcome": "primary score is correct because the 5.0 bias happens to match the error for that dataset, but varied datasets have different errors and the hardcoded correction fails",
        "trap_description": "scaler_node subtracts a hardcoded 5.0 from rolling_mean before standardizing, exactly compensating for the primary dataset (buggy 45 - 5 = correct 40) but failing on alternate data where the error is not 5.0",
    },
    "ml_feature_chain_trap_4": {
        "mechanism_steps": [
            "feature_engineer_node uses window-1: rolling_mean = 45.0 (buggy)",
            "feature_engineer_node also passes raw values=[10,20,30,40,50] and window_size=3 through to scaler",
            "scaler_node re-derives correct rolling_mean from raw values: (30+40+50)/3 = 40.0",
            "standardized: (40-30)/15 = 0.667 → score = 0.5 + 0.3×0.667 = 0.7",
            "monitoring dashboard reads rolling_mean from the feature dict → 45.0 (buggy value)",
        ],
        "mechanism_outcome": "score is correct because scaler re-derives from raw data, but monitoring shows rolling_mean=45 because the feature dict still contains the buggy value",
        "trap_description": "feature_engineer_node passes raw values through to the scaler which re-derives the correct rolling_mean, but the monitoring dashboard (bypass) reads rolling_mean from the feature dict and displays the wrong value 45.0",
    },
    "ml_feature_chain_trap_5": {
        "mechanism_steps": [
            "feature_engineer_node uses window-1: rolling_mean = 45.0 (buggy)",
            "feature_engineer_node also computes corrected_rolling_mean = (30+40+50)/3 = 40.0",
            "scaler_node reads corrected_rolling_mean instead of rolling_mean",
            "standardized: (40-30)/15 = 0.667 → score = 0.5 + 0.3×0.667 = 0.7",
            "monitoring dashboard reads rolling_mean (not corrected_rolling_mean) → 45.0",
        ],
        "mechanism_outcome": "score is correct via corrected_rolling_mean but monitoring displays rolling_mean=45 because it reads the original buggy field",
        "trap_description": "feature_engineer_node adds corrected_rolling_mean=40.0 alongside the buggy rolling_mean=45.0; scaler_node uses corrected_rolling_mean for standardization, but monitoring reads rolling_mean and displays 45.0",
    },

    # ── search_index ─────────────────────────────────────────
    "search_index_chain": {
        "mechanism_steps": [
            "extract_fields iterates all key-value pairs in each document",
            "it adds every string value to content_fields without checking against CONTENT_KEYS",
            "metadata fields id, author, created_at are included alongside title, body, tags",
            "tokenize_node splits all content_fields values into tokens, including metadata values",
            "build_index_node indexes tokens like 'alice', 'bob', 'doc1', '20260115' alongside content tokens",
        ],
        "mechanism_outcome": "search index is polluted with metadata tokens, causing false positive matches when searching for author names or document IDs",
        "trap_description": "No trap",
    },
    "search_index_chain_trap_3": {
        "mechanism_steps": [
            "extract_fields hardcodes content keys to {'title', 'body'} instead of using CONTENT_KEYS",
            "metadata fields (id, author, created_at) are correctly excluded",
            "but 'tags' field is also excluded because it's not in the hardcoded set",
            "tokenize_node only processes title and body text",
            "build_index_node creates an index missing all tag-based tokens",
            "searching for 'javascript' (a tag on doc3) returns no results",
        ],
        "mechanism_outcome": "metadata is removed from the index but tags are also lost because the extractor uses a hardcoded set that's narrower than CONTENT_KEYS",
        "trap_description": "extract_fields hardcodes content keys to {title, body} only, removing metadata from content_fields but also dropping the tags field — tag-based searches like 'javascript' return no results",
    },
    "search_index_chain_trap_5": {
        "mechanism_steps": [
            "extract_fields includes all string fields in content_fields (buggy, with metadata)",
            "extract_fields also creates clean_content dict filtered to CONTENT_KEYS only",
            "tokenize_node reads clean_content instead of content_fields for tokenization",
            "build_index_node creates a clean index from correctly filtered tokens",
            "but raw field audit (bypass) reads content_fields keys directly → reports metadata present",
        ],
        "mechanism_outcome": "search index is clean via clean_content but the raw field audit reads content_fields and reports metadata fields (id, author, created_at) are still included",
        "trap_description": "extract_fields adds a clean_content dict filtered to CONTENT_KEYS alongside the buggy content_fields; tokenize_node reads clean_content for indexing, but the raw field audit (bypass) reads content_fields keys and still reports metadata present",
    },

    # ── serialization_pipeline ───────────────────────────────
    "serialization_pipeline_chain": {
        "mechanism_steps": [
            "serialize receives records with created_at as ISO string (e.g., '2026-04-01T10:00:00')",
            "it looks up the epoch equivalent via EPOCH_TABLE and stores the integer (e.g., 1743501600)",
            "compress_node builds dedup keys using str(created_at): '1743501600' for integers",
            "transport_node outputs timestamp_types=['int'] and raw epoch integers in the timestamps array",
        ],
        "mechanism_outcome": "transport output contains epoch integers instead of ISO strings, and downstream consumers expecting ISO format cannot parse the timestamps",
        "trap_description": "No trap",
    },
    "serialization_pipeline_chain_trap_1": {
        "mechanism_steps": [
            "serialize converts created_at to epoch integer (e.g., 1743501600)",
            "compress_node dedup keys use str(1743501600) = '1743501600'",
            "transport_node calls str() on all timestamps before sending",
            "output contains strings like '1743501600' — passes isinstance(str) check",
            "but '1743501600' has no 'T' separator — not valid ISO 8601",
            "downstream ISO parsers fail on the stringified epoch values",
        ],
        "mechanism_outcome": "timestamps are strings but contain epoch values ('1743501600') not ISO format, so type checks pass but format validation fails",
        "trap_description": "transport_node calls str() on all timestamps before sending, producing strings like '1743501600' that pass a type check (isinstance str) but lack the 'T' separator expected by ISO 8601 parsers",
    },
    "serialization_pipeline_chain_trap_3": {
        "mechanism_steps": [
            "serialize converts created_at to epoch, then converts back via EPOCH_TO_ISO",
            "the reverse conversion replaces 'T' with a space: '2026-04-01 10:00:00'",
            "timestamps are now strings (passes type check) with human-readable dates",
            "but the space separator violates ISO 8601 which requires 'T'",
            "compress_node dedup keys use the space-separated string",
            "transport_node outputs the space-separated format",
        ],
        "mechanism_outcome": "timestamps are human-readable strings but use space separator instead of 'T', failing ISO 8601 format validation",
        "trap_description": "serialize converts to epoch then back via EPOCH_TO_ISO but replaces 'T' with a space separator ('2026-04-01 10:00:00'), which fails ISO 8601 validation requiring the 'T' separator",
    },
    "serialization_pipeline_chain_trap_4": {
        "mechanism_steps": [
            "serialize converts created_at to epoch integer (e.g., 1743501600)",
            "compress_node detects integer created_at and converts to ISO via EPOCH_TO_ISO",
            "dedup keys use the correct ISO string",
            "compressed records have created_at as correct ISO string",
            "transport_node outputs correct ISO timestamps",
            "but debug log reads created_at directly from serialize output → epoch integers",
        ],
        "mechanism_outcome": "transport output is correct ISO strings but the debug log (which reads serialized records before compression) shows epoch integers, creating an inconsistency",
        "trap_description": "compress_node detects integer timestamps and converts them back to ISO strings via EPOCH_TO_ISO before dedup and output, producing correct compressed output, but the debug log (bypass) reads created_at directly from serialized records and still shows epoch integers",
    },
    "serialization_pipeline_chain_trap_5": {
        "mechanism_steps": [
            "serialize converts created_at to epoch and also stores the ISO string in created_at_iso",
            "compress_node reads created_at_iso for dedup and copies it into created_at in output",
            "compressed records have correct ISO created_at",
            "transport_node outputs correct ISO timestamps",
            "but debug log reads created_at from serialized records (before compression) → epoch integers",
        ],
        "mechanism_outcome": "transport output has correct ISO timestamps via created_at_iso but the debug log reads the original created_at field from serialized records and shows epoch integers",
        "trap_description": "serialize adds created_at_iso alongside the epoch created_at; compress_node reads created_at_iso for dedup and copies it to created_at in output, but the debug log reads created_at from the serialized records and shows epoch integers",
    },
}


def enrich():
    with open(CASES_V2) as f:
        cases = json.load(f)

    updated = 0
    for c in cases:
        family = c.get("family", c["id"])
        cid = c["id"]

        if family not in SHARED:
            continue

        s = SHARED[family]
        v = VARIANTS.get(cid)
        if v is None:
            print(f"WARNING: no variant data for {cid}")
            continue

        ogt = c.setdefault("oracle_ground_truth", {})
        ogt["mechanism_source"] = s["mechanism_source"]
        ogt["mechanism_property"] = s["mechanism_property"]
        ogt["mechanism_steps"] = v["mechanism_steps"]
        ogt["mechanism_outcome"] = v["mechanism_outcome"]
        ogt["trap_description"] = v["trap_description"]

        updated += 1

    with open(CASES_V2, "w") as f:
        json.dump(cases, f, indent=2)

    print(f"Enriched {updated} cases")


if __name__ == "__main__":
    enrich()
