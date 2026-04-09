"""Generate cases_v2.json entries for all DDC variant cases.

Run: .venv/bin/python case_data/deep_dependency_chain_cases/generate_cases_v2_entries.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
CASES_V2 = PROJECT_ROOT / "case_data" / "cases_v2.json"

# Difficulty ratings by trap depth
TRAP_DIFFICULTY = {
    "trap_1": "D",
    "trap_3": "C",
    "trap_4": "B+",
    "trap_5": "B+",
}

# Task descriptions from the approved plan
VARIANT_TASKS = {
    "auth_context_chain": {
        "trap_1": "A recent patch to the resource gate was applied to handle permission failures more gracefully. Write operations now succeed for some users, but the authorization appears to bypass actual permission checks — users with \"default\" tier are being granted access they shouldn't have. Identify the underlying issue.",
        "trap_3": "The permission resolver was updated to handle org ID lookup failures by attempting an \"ORG-\" prefix fallback. Primary users now resolve correctly, but the system fails for organizations that use non-standard prefixes (like \"DEPT-\" or numeric-only org IDs). Find the root cause.",
        "trap_4": "The permission resolver was enhanced to try all known org ID prefixes when lookup fails. Permission resolution now works correctly for most users, but the normalized context still contains the stripped org_id. Audit logs and replay consumers read the wrong org_id. Find and fix the source of the inconsistency.",
        "trap_5": "The context normalizer was updated to include a canonical_org_id field alongside the existing org_id. Downstream permission resolution now uses the canonical field and works correctly. However, the original org_id field is still stripped, and some consumers read org_id directly. Fix the root issue so all consumers see the correct org_id.",
    },
    "billing_aggregation_chain": {
        "trap_1": "The invoice builder was patched to detect likely mis-tiered customers: when a growth-tier invoice exceeds $8, it overrides to enterprise pricing. This fixes the primary customer's bill, but a legitimate 85-unit growth customer now gets incorrectly downgraded to enterprise rates. Identify why the override exists and fix the actual problem.",
        "trap_3": "The usage collector was updated to apply a UTC adjustment by always shifting timestamps back by one hour. This produces correct billing for the primary customer (UTC+1), but customers in other timezones (e.g., UTC-5) get incorrect unit counts. Find the root cause of the timezone handling issue.",
        "trap_4": "The collector applies a timezone correction using a hardcoded UTC+1 offset, ignoring the actual timezone offset provided in the dataset. Primary billing appears correct, but staging environments and customers in different timezones see wrong unit counts. Fix the timezone handling.",
        "trap_5": "The collector was updated to compute a corrected_units field using proper UTC conversion, while leaving the original units field unchanged for backward compatibility. The plan resolver reads corrected_units and produces correct tier assignments. However, audit dashboards and other consumers still read the original units field and show wrong values. Fix the inconsistency.",
    },
    "config_derivation_chain": {
        "trap_1": "The service initializer was patched to detect abnormal pool_size values: if pool_size is a string or exceeds 20000, it falls back to 16160. The service now starts successfully on the primary port (8080). However, when deployed with PORT=443, the pool_size should be 886 but instead gets the fallback value 16160. Identify the upstream issue causing invalid pool_size values.",
        "trap_3": "The settings deriver was updated to cast port to int before computing pool_size. The derived settings (pool_size, listen_address) are now correct. However, the config audit endpoint still reports port as a string type, and other consumers that read the parsed config directly see the wrong type. Find the root cause.",
        "trap_4": "The settings deriver re-reads and converts the port value from the parsed config before computing derived settings. Pool_size and listen_address are correct in the service output. However, the parsed config audit still shows port_type=\"str\" instead of \"int\". Fix the source of the type inconsistency.",
        "trap_5": "The config parser was updated to include a port_int field alongside the original string port field. The settings deriver reads port_int and produces correct derived values. However, the config audit reads the port field and reports it as type \"str\". Fix the parser so all consumers see the correct port type.",
    },
    "event_etl_chain": {
        "trap_1": "The event writer was patched to default unknown-tier purchase events to \"standard\" tier. Alice's events now show tier=\"standard\" instead of \"unknown\". However, Alice should be \"premium\" (not \"standard\"), and the replay queue still contains lowercased user IDs that break downstream routing. Identify the root cause.",
        "trap_3": "The normalizer was updated with a heuristic: values containing underscores or hyphens are preserved as-is (assumed to be identifiers), while other values are lowercased. This fixes Alice_Smith and Carol-Wu. However, the user SYSADMIN (all-caps, no separator) gets lowercased to \"sysadmin\" and fails profile lookup. Fix the normalization logic.",
        "trap_4": "The enricher was modified to perform case-insensitive user profile lookups. All users now resolve to the correct tier. However, the replay queue (which reads directly from normalized events) still contains lowercased user IDs, causing incorrect event routing. Fix the source of the case corruption.",
        "trap_5": "The normalizer now preserves the original user_id in an original_user_id field while still lowercasing the user_id field. The enricher was updated to use original_user_id for lookups and correctly resolves all tiers. However, the replay queue reads user_id (not original_user_id) and routes events using the lowercased value. Fix the inconsistency.",
    },
    "logging_pipeline_chain": {
        "trap_1": "The dashboard renderer was patched to add UNKNOWN event counts to the CRITICAL alert count, since truncated severities were landing in UNKNOWN. The primary dataset now shows correct alert counts. However, on an INFO-only dataset with no critical events, the dashboard falsely reports critical alerts because UNKNOWN events (from truncated \"WARNING\" to \"WARN\") get promoted. Fix the root cause.",
        "trap_3": "The metric aggregator was updated to use fuzzy prefix matching: if a severity string is a prefix of a known level (or vice versa), it counts toward that level. Metric counts are now correct. However, the log lines themselves still display truncated severity names like \"[CRIT]\" and \"[WARN]\" instead of the full names. Fix the source of the truncation.",
        "trap_4": "The metric aggregator now maps known truncated severity strings back to their full names (CRIT to CRITICAL, WARN to WARNING) before counting. Dashboard metrics are correct. However, the compliance export reads severity directly from collected events and reports truncated values, disagreeing with the dashboard. Fix the root cause of the truncation.",
        "trap_5": "The event collector now includes an original_severity field alongside the truncated severity field. The metric aggregator uses original_severity for accurate counting. However, the compliance export reads the severity field and exports truncated values. Log lines also display truncated severity. Fix the collector so all consumers see correct severity.",
    },
    "ml_feature_chain": {
        "trap_1": "The model scorer was calibrated with a -0.1 bias correction to compensate for observed score inflation. Primary predictions now fall within the expected range. However, on a short dataset [5, 15] with window=3, the correction pushes the score to 0.0 when it should be approximately 0.1. The bias correction does not generalize. Find the upstream cause of the score inflation.",
        "trap_3": "The scaler was patched to subtract 5.0 from rolling_mean before standardization, compensating for an observed upward bias in the feature. Primary scores are now correct. However, on the varied dataset [10, 20, 50], the score is approximately 0.5 instead of the expected 0.433. The hardcoded correction does not generalize. Fix the source of the feature bias.",
        "trap_4": "The feature engineer was updated to pass raw values and window_size through to the scaler. The scaler now re-computes rolling_mean from the raw data, producing correct scaled values and predictions. However, the feature monitoring dashboard reads rolling_mean from the feature dict and reports the wrong value. Fix the feature engineer so all consumers see the correct rolling_mean.",
        "trap_5": "The feature engineer now computes a corrected_rolling_mean using the full window alongside the existing (buggy) rolling_mean. The scaler uses corrected_rolling_mean for standardization and produces correct scores. However, the monitoring dashboard reads rolling_mean and displays the wrong feature value. Fix the feature engineer so the primary rolling_mean field is correct.",
    },
    "search_index_chain": {
        "trap_3": "The field extractor was updated to only include \"title\" and \"body\" fields in content_fields, which successfully removes metadata from the index. However, tag-based searches no longer work — searching for \"javascript\" returns no results even though doc3 has that tag. The extractor is filtering too aggressively. Fix it so all content fields are included without metadata.",
        "trap_5": "The field extractor was updated to include a clean_content dict (containing only content keys) alongside the original content_fields. The tokenizer was updated to read from clean_content, and the search index is now clean. However, the raw field audit (which reads content_fields keys directly) still reports metadata fields present. Fix the extractor so content_fields itself only contains content keys.",
    },
    "serialization_pipeline_chain": {
        "trap_1": "The transport layer was patched to convert all timestamps to strings before sending. The output now reports timestamp_types=[\"str\"]. However, the timestamp values are strings like \"1743501600\" (stringified epoch integers) rather than ISO format \"2026-04-01T10:00:00\". Downstream consumers that parse ISO timestamps still fail. Find where the non-ISO values originate.",
        "trap_3": "The serializer was updated to convert timestamps back to a human-readable format after the epoch conversion. Timestamps are now strings, but they use space separators (\"2026-04-01 10:00:00\") instead of the ISO 8601 \"T\" separator. Downstream parsers expecting the \"T\" separator fail. Fix the serializer to produce correct ISO format.",
        "trap_4": "The compressor was enhanced to detect integer timestamps and convert them back to ISO strings before deduplication. Compressed output and transport timestamps are correct ISO strings. However, the debug log (which reads serialized records directly) still shows epoch integers. Fix the source of the epoch conversion.",
        "trap_5": "The serializer was updated to include a created_at_iso field alongside the epoch created_at. The compressor uses created_at_iso for dedup and copies it to created_at in output. Transport timestamps are correct ISO strings. However, the debug log reads created_at directly from serialized records and shows epoch integers. Fix the serializer so created_at itself is the ISO string.",
    },
}

# Trap descriptions (what makes it a trap — shown to evaluator, not LLM)
VARIANT_TRAPS = {
    "trap_1": "The endpoint/final node has been patched to compensate for the upstream bug. The symptom is masked but the root cause remains. The fix is superficial — it breaks on edge cases or alternate consumers.",
    "trap_3": "A middle node applies a heuristic or hardcoded correction that works for the primary test case but fails on alternate datasets or edge cases.",
    "trap_4": "A downstream node re-derives or compensates for the corrupted data, producing correct output through the main path. But a bypass consumer still reads the corrupted upstream data.",
    "trap_5": "The buggy node adds a corrected field alongside the corrupted one. Downstream nodes use the new field, but bypass consumers and other readers still access the original corrupted field.",
}


def _get_generated_files(case_name, variant):
    """Get code_files paths for a variant case."""
    gen_dir = ROOT / case_name / "generated_cases" / f"{case_name}_{variant}"
    if not gen_dir.exists():
        return None
    files = []
    # data.py first, then node files in chain order, skip pipeline.py and __init__.py
    for f in sorted(gen_dir.glob("*.py")):
        if f.name in ("__init__.py", "pipeline.py"):
            continue
        rel = f.relative_to(PROJECT_ROOT / "case_data")
        files.append(str(rel))
    return files


def _get_baseline_entry(cases, baseline_id):
    """Find the baseline case entry."""
    for c in cases:
        if c["id"] == baseline_id:
            return c
    return None


def generate_variant_entries():
    with open(CASES_V2) as f:
        cases = json.load(f)

    existing_ids = {c["id"] for c in cases}
    new_entries = []

    for baseline_id, trap_tasks in VARIANT_TASKS.items():
        baseline = _get_baseline_entry(cases, baseline_id)
        if not baseline:
            print(f"WARNING: baseline {baseline_id} not found in cases_v2.json")
            continue

        case_name = baseline_id.replace("_chain", "")

        for trap_id, task_text in trap_tasks.items():
            variant_id = f"{baseline_id}_{trap_id}"
            if variant_id in existing_ids:
                print(f"  SKIP {variant_id} (already exists)")
                continue

            code_files = _get_generated_files(case_name, trap_id)
            if not code_files:
                print(f"  SKIP {variant_id} (no generated files)")
                continue

            entry = {
                "id": variant_id,
                "family": baseline_id,
                "difficulty": TRAP_DIFFICULTY.get(trap_id, "C"),
                "task": task_text,
                "failure_mode": baseline.get("failure_mode", "LOGIC"),
                "trap": VARIANT_TRAPS.get(trap_id, ""),
                "code_files": code_files,
                "ground_truth_bug": baseline["ground_truth_bug"],
                "oracle_ground_truth": baseline["oracle_ground_truth"],
            }
            new_entries.append(entry)
            print(f"  ADD {variant_id} ({len(code_files)} files)")

    if new_entries:
        cases.extend(new_entries)
        with open(CASES_V2, "w") as f:
            json.dump(cases, f, indent=2)
        print(f"\nAdded {len(new_entries)} variant entries. Total cases: {len(cases)}")
    else:
        print("\nNo new entries to add.")

    return new_entries


if __name__ == "__main__":
    generate_variant_entries()
