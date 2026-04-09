# DDC Variant Task Descriptions — v1

Each section shows: the baseline task (for reference), then each trap variant's task description and rationale.

---

## auth_context_chain

**Baseline**: The auth middleware is incorrectly processing org IDs during context normalization. Users with prefixed org IDs (like "ORG-100") lose their prefix, causing permission lookups to fail and all writes to be denied.

**trap_1** (D — resource_gate defaults to granted=True for default tier):
> A recent patch to the resource gate was applied to handle permission failures more gracefully. Write operations now succeed for some users, but the authorization appears to bypass actual permission checks — users with "default" tier are being granted access they shouldn't have. Identify the underlying issue.

*Rationale: The LLM sees writes succeeding but for the wrong reason. The gate is papering over the broken lookup with a permissive default.*

**trap_3** (C — permission_resolver uses ORG- prefix fallback):
> The permission resolver was updated to handle org ID lookup failures by attempting an "ORG-" prefix fallback. Primary users now resolve correctly, but the system fails for organizations that use non-standard prefixes (like "DEPT-" or numeric-only org IDs). Find the root cause.

*Rationale: The prefix fallback works for the common case but is fragile — the LLM needs to see that the real fix is preserving the prefix upstream, not guessing it downstream.*

**trap_4** (B — permission_resolver tries all known prefixes):
> The permission resolver was enhanced to try all known org ID prefixes when lookup fails. Permission resolution now works correctly for most users, but the normalized context still contains the stripped org_id. Audit logs and replay consumers read the wrong org_id. Find and fix the source of the inconsistency.

*Rationale: The downstream fix compensates for permissions but the bypass path (audit/replay) still sees corrupted data.*

**trap_5** (B — context_normalizer adds canonical_org_id alongside stripped):
> The context normalizer was updated to include a `canonical_org_id` field alongside the existing `org_id`. Downstream permission resolution now uses the canonical field and works correctly. However, the original `org_id` field is still stripped, and some consumers read `org_id` directly. Fix the root issue so all consumers see the correct org_id.

*Rationale: The LLM sees the correct value available but in the wrong field. The real fix is to stop stripping the original field.*

---

## billing_aggregation_chain

**Baseline**: A billing system is generating incorrect invoices for customers near timezone boundaries. Some customers are being billed for fewer usage units than expected, resulting in wrong tier assignments and incorrect totals.

**trap_1** (D — invoice_builder overrides growth tier to enterprise pricing):
> The invoice builder was patched to detect likely mis-tiered customers: when a growth-tier invoice exceeds $8, it overrides to enterprise pricing. This fixes the primary customer's bill, but a legitimate 85-unit growth customer now gets incorrectly downgraded to enterprise rates. Identify why the override exists and fix the actual problem.

*Rationale: The LLM sees a hardcoded business rule that "fixes" the output. It needs to realize the override is compensating for a collector bug.*

**trap_3** (C — collector always shifts by -1h):
> The usage collector was updated to apply a UTC adjustment by always shifting timestamps back by one hour. This produces correct billing for the primary customer (UTC+1), but customers in other timezones (e.g., UTC-5) get incorrect unit counts. Find the root cause of the timezone handling issue.

*Rationale: The hardcoded shift only works for one timezone. The LLM needs to see that the collector should use the actual tz_offset from the data.*

**trap_4** (B — collector hardcodes tz=1 ignoring actual offset):
> The collector applies a timezone correction using a hardcoded UTC+1 offset, ignoring the actual timezone offset provided in the dataset. Primary billing appears correct, but staging environments and customers in different timezones see wrong unit counts. Fix the timezone handling.

*Rationale: Same as trap_3 but framed differently — the LLM sees a hardcoded value where a parameter should be used.*

**trap_5** (B — collector adds corrected_units alongside buggy units):
> The collector was updated to compute a `corrected_units` field using proper UTC conversion, while leaving the original `units` field unchanged for backward compatibility. The plan resolver reads `corrected_units` and produces correct tier assignments. However, audit dashboards and other consumers still read the original `units` field and show wrong values. Fix the inconsistency.

*Rationale: The correct value exists but in a parallel field. The real fix is to fix the original field, not add a workaround alongside it.*

---

## config_derivation_chain

**Baseline**: A service initialization pipeline is failing with an invalid pool_size error. The service cannot start because pool_size is computed as a string repetition instead of an integer multiplication.

**trap_1** (D — service_initializer caps pool_size at 16160):
> The service initializer was patched to detect abnormal pool_size values: if pool_size is a string or exceeds 20000, it falls back to 16160. The service now starts successfully on the primary port (8080). However, when deployed with PORT=443, the pool_size should be 886 but instead gets the fallback value 16160. Identify the upstream issue causing invalid pool_size values.

*Rationale: The fallback hides the symptom. The LLM needs to trace back to why pool_size is wrong in the first place.*

**trap_3** (C — settings_deriver casts port to int before math):
> The settings deriver was updated to cast port to int before computing pool_size. The derived settings (pool_size, listen_address) are now correct. However, the config audit endpoint still reports port as a string type, and other consumers that read the parsed config directly see the wrong type. Find the root cause.

*Rationale: The deriver compensates but the parsed config is still wrong. The cross-path audit catches this.*

**trap_4** (B — settings_deriver re-derives port from parsed config):
> The settings deriver re-reads and converts the port value from the parsed config before computing derived settings. Pool_size and listen_address are correct in the service output. However, the parsed config audit still shows port_type="str" instead of "int". Fix the source of the type inconsistency.

*Rationale: Same compensating behavior as trap_3, framed as the deriver being "smart" about its input. Audit (bypass) still sees the raw parsed config.*

**trap_5** (B — config_parser adds port_int alongside string port):
> The config parser was updated to include a `port_int` field alongside the original string `port` field. The settings deriver reads `port_int` and produces correct derived values. However, the config audit reads the `port` field and reports it as type "str". Fix the parser so all consumers see the correct port type.

*Rationale: Parallel field workaround. The LLM needs to fix the original field, not rely on the alternate one.*

---

## event_etl_chain

**Baseline**: An event processing pipeline is enriching all events with tier=unknown, meaning no user profiles are being resolved. The system processes purchase and audit events from multiple users. Identify the root cause and fix it so that users are correctly resolved to their profiles.

**trap_1** (D — writer defaults unknown tier to "standard" for purchases):
> The event writer was patched to default unknown-tier purchase events to "standard" tier. Alice's events now show tier="standard" instead of "unknown". However, Alice should be "premium" (not "standard"), and the replay queue still contains lowercased user IDs that break downstream routing. Identify the root cause.

*Rationale: The writer masks the symptom with a wrong default. The LLM needs to see that the tier should come from the actual profile lookup, not a hardcoded fallback.*

**trap_3** (C — normalizer preserves case for values with _ or -):
> The normalizer was updated with a heuristic: values containing underscores or hyphens are preserved as-is (assumed to be identifiers), while other values are lowercased. This fixes Alice_Smith and Carol-Wu. However, the user SYSADMIN (all-caps, no separator) gets lowercased to "sysadmin" and fails profile lookup. Fix the normalization logic.

*Rationale: The heuristic works for common cases but misses the edge case. The LLM needs to see that user_id should never be lowercased regardless of format.*

**trap_4** (B — enricher does case-insensitive lookup):
> The enricher was modified to perform case-insensitive user profile lookups. All users now resolve to the correct tier. However, the replay queue (which reads directly from normalized events) still contains lowercased user IDs, causing incorrect event routing. Fix the source of the case corruption.

*Rationale: The downstream fix works for enrichment but the bypass consumer still sees corrupted data.*

**trap_5** (B — normalizer adds original_user_id alongside lowercased):
> The normalizer now preserves the original user_id in an `original_user_id` field while still lowercasing the `user_id` field. The enricher was updated to use `original_user_id` for lookups and correctly resolves all tiers. However, the replay queue reads `user_id` (not `original_user_id`) and routes events using the lowercased value. Fix the inconsistency.

*Rationale: Parallel field pattern again. The real fix is to preserve user_id in place.*

---

## logging_pipeline_chain

**Baseline**: An event logging pipeline is reporting zero critical alerts even when critical events are present. The dashboard shows all non-INFO events as UNKNOWN severity.

**trap_1** (D — dashboard promotes UNKNOWN to CRITICAL count):
> The dashboard renderer was patched to add UNKNOWN event counts to the CRITICAL alert count, since truncated severities were landing in UNKNOWN. The primary dataset now shows correct alert counts. However, on an INFO-only dataset with no critical events, the dashboard falsely reports critical alerts because UNKNOWN events (from truncated "WARNING" → "WARN") get promoted. Fix the root cause.

*Rationale: The promotion heuristic creates false positives. The LLM needs to trace back to why events are UNKNOWN in the first place.*

**trap_3** (C — aggregator uses fuzzy prefix matching):
> The metric aggregator was updated to use fuzzy prefix matching: if a severity string is a prefix of a known level (or vice versa), it counts toward that level. Metric counts are now correct. However, the log lines themselves still display truncated severity names like "[CRIT]" and "[WARN]" instead of the full names. Fix the source of the truncation.

*Rationale: The aggregator compensates for counting, but the formatter still sees truncated data. The generalization invariant catches this.*

**trap_4** (B — aggregator maps truncated severity back to full name):
> The metric aggregator now maps known truncated severity strings back to their full names (CRIT→CRITICAL, WARN→WARNING) before counting. Dashboard metrics are correct. However, the compliance export reads severity directly from collected events and reports truncated values, disagreeing with the dashboard. Fix the root cause of the truncation.

*Rationale: The aggregator remaps for its own use, but the bypass consumer (compliance export) sees the raw truncated data.*

**trap_5** (B — collector adds original_severity alongside truncated):
> The event collector now includes an `original_severity` field alongside the truncated `severity` field. The metric aggregator uses `original_severity` for accurate counting. However, the compliance export reads the `severity` field and exports truncated values. Log lines also display truncated severity. Fix the collector so all consumers see correct severity.

*Rationale: Parallel field pattern. The fix is to stop truncating the original field.*

---

## ml_feature_chain

**Baseline**: An ML scoring pipeline is producing incorrect predictions. The rolling mean feature is being computed incorrectly, causing the scaler and scorer to operate on wrong values.

**trap_1** (D — scorer subtracts 0.1 bias correction):
> The model scorer was calibrated with a -0.1 bias correction to compensate for observed score inflation. Primary predictions now fall within the expected range. However, on a short dataset [5, 15] with window=3, the correction pushes the score to 0.0 when it should be ~0.1. The bias correction doesn't generalize. Find the upstream cause of the score inflation.

*Rationale: The scorer compensates with a magic number that works for one dataset. The LLM needs to find the feature engineering bug.*

**trap_3** (C — scaler subtracts hardcoded 5.0 from rolling_mean):
> The scaler was patched to subtract 5.0 from rolling_mean before standardization, compensating for an observed upward bias in the feature. Primary scores are now correct. However, on the varied dataset [10, 20, 50], the score is ~0.5 instead of the expected ~0.433. The hardcoded correction doesn't generalize. Fix the source of the feature bias.

*Rationale: The hardcoded subtraction only works when the buggy-correct difference is exactly 5.0. Different data exposes the fragility.*

**trap_4** (B — scaler re-derives rolling_mean from raw values):
> The feature engineer was updated to pass raw values and window_size through to the scaler. The scaler now re-computes rolling_mean from the raw data, producing correct scaled values and predictions. However, the feature monitoring dashboard reads rolling_mean from the feature dict and reports the wrong value. Fix the feature engineer so all consumers see the correct rolling_mean.

*Rationale: The scaler compensates by re-deriving, but the bypass consumer (monitoring) reads the buggy feature value.*

**trap_5** (B — feature_engineer adds corrected_rolling_mean):
> The feature engineer now computes a `corrected_rolling_mean` using the full window alongside the existing (buggy) `rolling_mean`. The scaler uses `corrected_rolling_mean` for standardization and produces correct scores. However, the monitoring dashboard reads `rolling_mean` and displays the wrong feature value. Fix the feature engineer so the primary rolling_mean field is correct.

*Rationale: Parallel field pattern. The LLM needs to fix rolling_mean directly.*

---

## search_index_chain

**Baseline**: A document search pipeline is producing incorrect results: searching for author names returns documents (they should not), and the search index appears polluted.

**trap_3** (C — field_extractor hardcodes {title, body}, drops tags):
> The field extractor was updated to only include "title" and "body" fields in content_fields, which successfully removes metadata from the index. However, tag-based searches no longer work — searching for "javascript" returns no results even though doc3 has that tag. The extractor is filtering too aggressively. Fix it so all content fields are included without metadata.

*Rationale: The hardcoded set is too narrow — it fixes metadata pollution but drops a legitimate content field. The LLM needs to use the CONTENT_KEYS constant.*

**trap_5** (B — field_extractor adds clean_content alongside buggy content_fields):
> The field extractor was updated to include a `clean_content` dict (containing only content keys) alongside the original `content_fields`. The tokenizer was updated to read from `clean_content`, and the search index is now clean. However, the raw field audit (which reads `content_fields` keys directly) still reports metadata fields present. Fix the extractor so `content_fields` itself only contains content keys.

*Rationale: Parallel field pattern. Bypass consumer reads the polluted original field.*

---

## serialization_pipeline_chain

**Baseline**: A record serialization pipeline is outputting epoch integers instead of ISO timestamp strings. Downstream consumers expecting ISO format (YYYY-MM-DDTHH:MM:SS) are receiving raw epoch numbers.

**trap_1** (D — transport coerces all timestamps to strings):
> The transport layer was patched to convert all timestamps to strings before sending. The output now reports timestamp_types=["str"]. However, the timestamp values are strings like "1743501600" (stringified epoch integers) rather than ISO format "2026-04-01T10:00:00". Downstream consumers that parse ISO timestamps still fail. Find where the non-ISO values originate.

*Rationale: str(epoch_int) passes a type check but not a format check. The LLM needs to trace back to the serializer.*

**trap_3** (C — serializer reconverts epoch back to ISO with space separator):
> The serializer was updated to convert timestamps back to a human-readable format after the epoch conversion. Timestamps are now strings, but they use space separators ("2026-04-01 10:00:00") instead of the ISO 8601 "T" separator. Downstream parsers expecting the "T" separator fail. Fix the serializer to produce correct ISO format.

*Rationale: Close but wrong — the reconversion introduces a format error. The LLM needs to see that the round-trip through epoch is unnecessary.*

**trap_4** (B — compressor maps epoch to ISO before dedup):
> The compressor was enhanced to detect integer timestamps and convert them back to ISO strings before deduplication. Compressed output and transport timestamps are correct ISO strings. However, the debug log (which reads serialized records directly) still shows epoch integers. Fix the source of the epoch conversion.

*Rationale: Downstream compensation. The bypass consumer (debug log) still sees the raw serializer output.*

**trap_5** (B — serializer adds created_at_iso alongside epoch):
> The serializer was updated to include a `created_at_iso` field alongside the epoch `created_at`. The compressor uses `created_at_iso` for dedup and copies it to `created_at` in output. Transport timestamps are correct ISO strings. However, the debug log reads `created_at` directly from serialized records and shows epoch integers. Fix the serializer so `created_at` itself is the ISO string.

*Rationale: Parallel field pattern. The real fix is to stop converting to epoch in the first place.*
