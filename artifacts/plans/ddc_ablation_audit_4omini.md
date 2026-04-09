================================================================================
DDC ABLATION AUDIT: gpt-4o-mini × 38 cases × 2 conditions × 5 trials
Run directory: logs/ablation_ddc_4omini/2026-04-06_01-42-36_ablation_ddc_4omini_001
================================================================================

SYSTEM DESCRIPTION: DEEP DEPENDENCY CHAIN (DDC) BENCHMARK
================================================================================

The Deep Dependency Chain (DDC) benchmark measures an LLM's ability to trace
bugs through multi-node pipelines and fix them at the correct depth. Each case
is a 4-node processing pipeline where a bug is introduced at one node (the
"corruption node"), propagates through intermediate nodes, and becomes
observable as a symptom at a downstream node. The LLM sees the full pipeline
code and a task description of the symptom, and must produce a fix.

Each pipeline follows the pattern: source node -> corruption node ->
propagation node -> output node. For example, the serialization_pipeline
case has the chain record_builder -> serializer -> compressor -> transport,
where the serializer converts timestamps from ISO strings to epoch integers.
The compressor's string-based dedup and the transport's output both break
because they expect strings. The 8 case families cover different domains:
auth context (org ID prefix stripping), billing aggregation (timezone boundary
misattribution), config derivation (string port type), event ETL (user ID
case corruption), logging pipeline (severity truncation), ML feature pipeline
(off-by-one window), search index (metadata field pollution), and
serialization pipeline (epoch type conversion).

The key innovation is trap variants. Each case family has 4 trap variants
(trap_1, trap_3, trap_4, trap_5) where a "partial fix" has already been
applied at a specific depth in the chain. Trap_1 (depth D) compensates at
the endpoint — the final node patches the symptom. Trap_3 (depth C) applies
a heuristic at a middle node that works for the primary dataset but fails on
edge cases. Trap_4 (depth B) overrides at a downstream node by re-deriving
the correct value, hiding the upstream corruption from the main output but
leaving bypass consumers exposed. Trap_5 (depth B) adds a parallel field
with the correct value alongside the corrupted original, so downstream nodes
work via the new field but bypass consumers still read the corrupted one.
These traps test whether an LLM will anchor on an existing partial fix
instead of tracing to the root cause.

The evaluation uses two oracles. The generic oracle (LLM-based) evaluates
whether the model's root_cause text correctly describes the bug mechanism —
what goes wrong and how it propagates. The spec oracle (code-based) runs
the case's invariant functions and classifies the fix depth as A (root fix),
B-D (trap-level fix), or F (worse than any known trap). Together they
distinguish mechanism identification (did the LLM understand the bug?) from
depth identification (did the LLM fix it at the right place?). This
separation reveals a systematic gap: LLMs frequently describe the correct
mechanism but fix at the wrong depth.

The benchmark produces 38 cases total: 8 baselines (raw buggy code) and 30
trap variants (2-4 per family, depending on which traps are implementable
in the pipeline). Each case has a task description that describes only the
observable symptoms without naming the buggy node or the fix. Reference fixes,
test files, and oracle invariants are validated through the same subprocess
execution path used in production. The directed depth hint system provides
three levels of retry feedback (gentle, directed, explicit) that can be
injected when the spec oracle detects a wrong-depth fix, testing whether
LLMs can be redirected upstream with varying degrees of specificity.

The depth hint is generated deterministically, not by an LLM. After each
failed attempt, the spec oracle classifies the LLM's fix depth. If the
depth is not A (root fix), the retry system injects a hint as the critique
text. The hint is selected by a config parameter (depth_hint_level) from
three fixed templates. The "gentle" hint says the root cause is upstream
without further guidance. The "directed" hint tells the model to trace the
data flow backward and find which node first corrupts the value. The
"explicit" hint names the specific file and describes the bug. In prior
testing on gpt-5-mini with serialization_pipeline_chain_trap_1, gentle
failed (0/3 attempts), directed succeeded (passed on retry), and explicit
succeeded (passed on retry). The directed level is used for ablation runs
as the best balance between guidance and not giving away the answer.

HINT IMPACT: WHERE THE DIRECTED HINT MADE A DIFFERENCE
================================================================================

The aggregate numbers (baseline 41% vs critique+hint 44%) obscure the
hint's real effect. On 24 of the 38 cases, the pass rate is identical
across conditions — either the model always solves it (100%/100%) or never
does (0%/0%). The hint only matters on the boundary cases where the model
sometimes succeeds. The most dramatic effect is event_etl_chain_trap_3,
which goes from 1/5 (20%) on baseline to 5/5 (100%) with the hint — a
case where the model identifies the right file (normalizer.py) but
implements the trap_3 heuristic (preserve case for values with _ or -)
instead of fully fixing the lowercasing. The hint redirects it to remove
all lowercasing rather than refining the heuristic. Other gains include
serialization_pipeline_chain_trap_5 (1/5 to 3/5), search_index_chain_trap_5
(0/5 to 2/5), and serialization_pipeline_chain_trap_1 and trap_4 (2/5 to
3/5 each). The hint hurts on two cases: serialization_pipeline_chain
baseline drops from 2/5 to 0/5, and auth_context_chain_trap_4 drops from
5/5 to 3/5 — in both cases the model's first attempt was already correct
but the critique condition's independent first attempt happened to fail,
and the hint couldn't recover it. The hint's 4% aggregate improvement
masks a pattern of strong targeted gains on specific trap variants offset
by noise on cases the model handles inconsistently.

Cases where the directed hint fixed failures (critique condition, a0→a1):

  event_etl_chain_trap_3:
    3 of 5 trials: a0 reproduced trap_3 heuristic → hint → a1 removed
    all lowercasing. The model knew the right file but needed the hint to
    abandon the heuristic and make a broader fix.

  serialization_pipeline_chain_trap_5:
    1 of 5 trials: a0 fixed serializer.py but left created_at_iso field
    logic → hint → a1 simplified to just preserving created_at as ISO.

  search_index_chain_trap_5:
    2 of 5 trials: a0 worked with clean_content parallel field → hint →
    a1 fixed content_fields directly in the extractor.

  serialization_pipeline_chain_trap_1:
    1 of 5 trials: a0 fixed transport.py (trap endpoint) → hint → a1
    moved fix to serializer.py.

  serialization_pipeline_chain_trap_4:
    1 of 5 trials: a0 fixed compressor.py (trap override) → hint → a1
    moved fix to serializer.py.

================================================================================

1. OVERALL RESULTS
----------------------------------------
  baseline_v3: 77/190 (41%)
  critique_strict_v3: 83/190 (44%)

2. PER-CASE PASS RATES (baseline / critique+hint)
----------------------------------------
  auth_context_chain                            0/5  0/5
  auth_context_chain_trap_1                     0/5  0/5
  auth_context_chain_trap_3                     0/5  0/5
  auth_context_chain_trap_4                     5/5  3/5
  auth_context_chain_trap_5                     0/5  0/5
  billing_aggregation_chain                     0/5  0/5
  billing_aggregation_chain_trap_1              0/5  0/5
  billing_aggregation_chain_trap_3              0/5  0/5
  billing_aggregation_chain_trap_4              0/5  0/5
  billing_aggregation_chain_trap_5              0/5  0/5
  config_derivation_chain                       0/5  0/5
  config_derivation_chain_trap_1                0/5  0/5
  config_derivation_chain_trap_3                5/5  5/5
  config_derivation_chain_trap_4                5/5  5/5
  config_derivation_chain_trap_5                5/5  5/5
  event_etl_chain                               0/5  0/5
  event_etl_chain_trap_1                        0/5  0/5
  event_etl_chain_trap_3                        1/5  5/5
  event_etl_chain_trap_4                        0/5  0/5
  event_etl_chain_trap_5                        5/5  5/5
  logging_pipeline_chain                        5/5  5/5
  logging_pipeline_chain_trap_1                 0/5  0/5
  logging_pipeline_chain_trap_3                 5/5  5/5
  logging_pipeline_chain_trap_4                 5/5  5/5
  logging_pipeline_chain_trap_5                 5/5  5/5
  ml_feature_chain                              5/5  5/5
  ml_feature_chain_trap_1                       0/5  0/5
  ml_feature_chain_trap_3                       0/5  0/5
  ml_feature_chain_trap_4                       5/5  5/5
  ml_feature_chain_trap_5                       5/5  5/5
  search_index_chain                            0/5  0/5
  search_index_chain_trap_3                     5/5  5/5
  search_index_chain_trap_5                     0/5  2/5
  serialization_pipeline_chain                  2/5  0/5
  serialization_pipeline_chain_trap_1           2/5  3/5
  serialization_pipeline_chain_trap_3           4/5  4/5
  serialization_pipeline_chain_trap_4           2/5  3/5
  serialization_pipeline_chain_trap_5           1/5  3/5

3. LEG ANALYSIS (Reasoning-Execution Gap)
----------------------------------------

3a. R+E- (Correct reasoning, failed execution):
  Total: 72 instances

  config_derivation_chain_trap_1: 10 instances
    changed: ['deriver.py'] (should fix: parser.py)
    root_cause: derive_settings_node function's pool_size calculation uses port directly, leading to incorrect pool_size when PORT is a 
    oracle_just: The ground truth explains that parse_config leaves PORT as a string causing derive_settings to do string repetition when

  auth_context_chain: 8 instances
    changed: ['resolver.py'] (should fix: normalizer.py)
    root_cause: resolve_permissions_node function is incorrectly using the org_id after normalization, which leads to incorrect user loo
    oracle_just: The ground truth states normalize_context strips the 'ORG-'/'DEPT-' prefix causing lookups like '100:alice' to fail, and

  ml_feature_chain_trap_1: 5 instances
    changed: ['features.py', 'scaler.py', 'scorer.py'] (should fix: features.py)
    root_cause: _engineer_features_buggy function has a logic error in calculating the rolling mean, which leads to incorrect scaling an
    oracle_just: The developer correctly identifies that _engineer_features_buggy miscalculates the rolling mean — matching the ground tr

  ml_feature_chain_trap_3: 5 instances
    changed: ['features.py'] (should fix: features.py)
    root_cause: features.py: _engineer_features_buggy function incorrectly calculates the rolling mean by using 'window - 1' instead of 
    oracle_just: The ground truth states the rolling mean is computed with window-1 instead of window in feature_engineer_node, and the d

  billing_aggregation_chain: 5 instances
    changed: ['plan_resolver.py', 'rate_engine.py', 'invoice_builder.py'] (should fix: collector.py)
    root_cause: _resolve_tier function incorrectly assigns tiers based on the maximum units without considering timezone offsets, leadin
    oracle_just: The ground truth identifies collector.aggregate_usage grouping by local date (ts[:10]) and ignoring tz_offset as the roo

  search_index_chain: 5 instances
    changed: ['tokenizer.py'] (should fix: extractor.py)
    root_cause: tokenize_node function is incorrectly tokenizing the author names as valid tokens, leading to false positives in search 
    oracle_just: The ground truth states extract_fields adds metadata (e.g., author) into content_fields instead of only CONTENT_KEYS, an

  event_etl_chain_trap_3: 4 instances
    changed: ['normalizer.py'] (should fix: normalizer.py)
    root_cause: normalize function is converting user IDs to lowercase, causing 'SYSADMIN' to be transformed to 'sysadmin', which does n
    oracle_just: The ground truth states normalize lowercases user_id values (so 'SYSADMIN' becomes 'sysadmin' and fails lookup against c

  serialization_pipeline_chain_trap_5: 4 instances
    changed: ['serializer.py'] (should fix: serializer.py)
    root_cause: serialize function must correctly set the 'created_at' field to the ISO format instead of the epoch timestamp when loggi
    oracle_just: The ground truth shows serialize converts created_at to an epoch int (so debug logs read ints), and the developer correc

  auth_context_chain_trap_3: 4 instances
    changed: ['resolver.py'] (should fix: normalizer.py)
    root_cause: resolve_permissions_node function fails to handle DEPT- prefixed and numeric-only org IDs correctly because it only chec
    oracle_just: The ground truth states normalize_context strips the org_id prefix (e.g., "ORG-100" → "100"), and the developer likewise

  auth_context_chain_trap_5: 4 instances
    changed: ['resolver.py'] (should fix: normalizer.py)
    root_cause: resolve_permissions_node function uses normalized['org_id'] instead of normalized['canonical_org_id'] to fetch user perm
    oracle_just: The ground truth says normalize_context strips the org_id while saving the original in canonical_org_id causing a corrup

  search_index_chain_trap_5: 3 instances
    changed: ['extractor.py'] (should fix: extractor.py)
    root_cause: extract_fields function does not filter out metadata fields, leading to their inclusion in extracted data.
    oracle_just: The developer correctly identifies that extract_fields fails to filter out metadata fields (claiming content_fields incl

  config_derivation_chain: 2 instances
    changed: ['deriver.py'] (should fix: parser.py)
    root_cause: derive_settings_node function's pool_size calculation is incorrect because it multiplies the port (a string) by 2, leadi
    oracle_just: The ground truth states parse_config fails to convert PORT to an int causing derive_settings' pool_size = port * 2 to pe

  serialization_pipeline_chain: 2 instances
    changed: ['serializer.py'] (should fix: serializer.py)
    root_cause: serialize function's use of EPOCH_TABLE to convert 'created_at' timestamps to epoch values is causing incorrect formats,
    oracle_just: The ground truth says serialize looks up ISO 'created_at' strings in EPOCH_TABLE and replaces them with epoch integers c

  serialization_pipeline_chain_trap_3: 2 instances
    changed: ['serializer.py'] (should fix: serializer.py)
    root_cause: serialize function's reconverted variable incorrectly replaces 'T' with a space, resulting in a non-ISO 8601 format.
    oracle_just: The ground truth states serialize's reconverted value replaces the 'T' with a space and thus produces non-ISO 8601 times

  auth_context_chain_trap_1: 2 instances
    changed: ['resolver.py'] (should fix: normalizer.py)
    root_cause: resolve_permissions_node function assigns the wrong tier due to incorrect key formation when looking up user records in 
    oracle_just: The ground truth identifies normalize_context stripping the org_id prefix (corrupting the key used by resolve_permission

  auth_context_chain_trap_4: 2 instances
    changed: [] (should fix: normalizer.py)
    root_cause: 
    oracle_just: The ground truth identifies normalize_context stripping the org_id prefix (corrupting org_id for downstream consumers), 

  serialization_pipeline_chain_trap_1: 2 instances
    changed: ['transport.py'] (should fix: serializer.py)
    root_cause: transport_node function's 'created_at' variable is coerced to a string without formatting, leading to incorrect timestam
    oracle_just: The ground truth states serialize converts ISO timestamps to epoch integers (which later get stringified into non-ISO st

  billing_aggregation_chain_trap_1: 1 instances
    changed: ['plan_resolver.py'] (should fix: collector.py)
    root_cause: _resolve_tier function incorrectly determines the tier based on the maximum units instead of the total units used, leadi
    oracle_just: The ground truth says aggregate_usage groups by the local date (not converting timestamps to UTC), while the developer c

  event_etl_chain: 1 instances
    changed: ['enricher.py'] (should fix: normalizer.py)
    root_cause: enrich_node function is using the user_id directly without normalizing it, causing mismatches with USER_PROFILES keys.
    oracle_just: The ground truth states normalize lowercases user_id (corrupting its case) which breaks the case-sensitive USER_PROFILES

  logging_pipeline_chain_trap_1: 1 instances
    changed: ['dashboard.py'] (should fix: collector.py)
    root_cause: render_dashboard_node function incorrectly calculates alert_count by using metrics.get(ALERT_THRESHOLD, 0) which returns
    oracle_just: The ground truth specifies that collect_events_node truncates severity strings (e.g., 'CRITICAL'→'CRIT') causing misclas

3b. R-E+ (Wrong reasoning, passed execution — lucky fixes):
  Total: 4 instances
  auth_context_chain_trap_4 (baseline_v3 trial_002):
    oracle: WRONG
    oracle_just: The ground truth explains that normalize_context strips the org_id prefix but resolve_permissions reconstructs the prefixed key (so permission checks 
    changed: ['normalizer.py']
    root_cause: normalize_context function modifies org_id incorrectly by removing the prefix, leading to mismatches in the USER_DB lookup in resolve_permissions_node

  logging_pipeline_chain_trap_4 (baseline_v3 trial_005):
    oracle: WRONG
    oracle_just: The ground truth states the bug is truncation of severity to four chars (e.g., CRITICAL→CRIT) that the aggregator remaps so dashboard counts stay corr
    changed: ['collector.py']
    root_cause: collect_events_node function truncates severity values to the first four characters, which causes 'ERROR' to be stored as 'ERRO', leading to incorrect

  auth_context_chain_trap_4 (critique_strict_v3 trial_003):
    oracle: WRONG
    oracle_just: The developer claims normalize_context's prefix removal causes USER_DB lookup mismatches in resolve_permissions_node, but the ground truth explains re
    changed: ['normalizer.py']
    root_cause: normalize_context function modifies org_id incorrectly by removing the prefix, leading to mismatches in the USER_DB lookup in resolve_permissions_node

  serialization_pipeline_chain_trap_1 (critique_strict_v3 trial_003):
    oracle: WRONG
    oracle_just: The ground truth says serialize converts created_at ISO strings to epoch integers (which causes epoch strings later), but the reasoning incorrectly cl
    changed: ['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']
    root_cause: serialize function must convert 'created_at' to epoch format, but it currently uses the ISO string directly, leading to incorrect timestamp formats do

4. ORACLE LENIENCY AUDIT
----------------------------------------
Cases where oracle=CORRECT but model fixed the WRONG FILE:

  config_derivation_chain_trap_1: 10 instances
    should fix: parser.py
    actually fixed: ['deriver.py']
    root_cause: derive_settings_node function's pool_size calculation uses port directly, leading to incorrect pool_size when PORT is a string instead of an integer.
    oracle said: The ground truth explains that parse_config leaves PORT as a string causing derive_settings to do string repetition when computing pool_size, and the 

  auth_context_chain: 8 instances
    should fix: normalizer.py
    actually fixed: ['resolver.py']
    root_cause: resolve_permissions_node function is incorrectly using the org_id after normalization, which leads to incorrect user lookups in USER_DB.
    oracle said: The ground truth states normalize_context strips the 'ORG-'/'DEPT-' prefix causing lookups like '100:alice' to fail, and the developer correctly claim

  search_index_chain: 5 instances
    should fix: extractor.py
    actually fixed: ['tokenizer.py']
    root_cause: tokenize_node function is incorrectly tokenizing the author names as valid tokens, leading to false positives in search results.
    oracle said: The ground truth states extract_fields adds metadata (e.g., author) into content_fields instead of only CONTENT_KEYS, and the developer similarly argu

  auth_context_chain_trap_3: 4 instances
    should fix: normalizer.py
    actually fixed: ['resolver.py']
    root_cause: resolve_permissions_node function fails to handle DEPT- prefixed and numeric-only org IDs correctly because it only checks for ORG- prefixed IDs in th
    oracle said: The ground truth states normalize_context strips the org_id prefix (e.g., "ORG-100" → "100"), and the developer likewise blames the normalization step

  auth_context_chain_trap_5: 4 instances
    should fix: normalizer.py
    actually fixed: ['resolver.py']
    root_cause: resolve_permissions_node function uses normalized['org_id'] instead of normalized['canonical_org_id'] to fetch user permissions, leading to mismatched
    oracle said: The ground truth says normalize_context strips the org_id while saving the original in canonical_org_id causing a corrupted org_id to propagate to con

  billing_aggregation_chain: 4 instances
    should fix: collector.py
    actually fixed: ['plan_resolver.py', 'rate_engine.py', 'invoice_builder.py']
    root_cause: _resolve_tier function incorrectly assigns tiers based on the maximum units without considering timezone offsets, leading to incorrect tier assignment
    oracle said: The ground truth identifies collector.aggregate_usage grouping by local date (ts[:10]) and ignoring tz_offset as the root cause, while the developer c

  config_derivation_chain: 2 instances
    should fix: parser.py
    actually fixed: ['deriver.py']
    root_cause: derive_settings_node function's pool_size calculation is incorrect because it multiplies the port (a string) by 2, leading to an invalid pool_size val
    oracle said: The ground truth states parse_config fails to convert PORT to an int causing derive_settings' pool_size = port * 2 to perform string repetition, and t

  search_index_chain_trap_5: 2 instances
    should fix: extractor.py
    actually fixed: ['tokenizer.py']
    root_cause: tokenize_node function is using 'clean_content' which does not include metadata fields, but 'content_fields' which does include them is not being filt
    oracle said: The ground truth identifies that extract_fields places all string-valued fields (including metadata) into content_fields, and the developer's root_cau

  auth_context_chain_trap_1: 2 instances
    should fix: normalizer.py
    actually fixed: ['resolver.py']
    root_cause: resolve_permissions_node function assigns the wrong tier due to incorrect key formation when looking up user records in USER_DB.
    oracle said: The ground truth identifies normalize_context stripping the org_id prefix (corrupting the key used by resolve_permissions_node), and the developer lik

  auth_context_chain_trap_4: 2 instances
    should fix: normalizer.py
    actually fixed: []
    root_cause: 
    oracle said: The ground truth identifies normalize_context stripping the org_id prefix (corrupting org_id for downstream consumers), and the developer's root cause

  serialization_pipeline_chain_trap_1: 2 instances
    should fix: serializer.py
    actually fixed: ['transport.py']
    root_cause: transport_node function's 'created_at' variable is coerced to a string without formatting, leading to incorrect timestamp formats for downstream ISO p
    oracle said: The ground truth states serialize converts ISO timestamps to epoch integers (which later get stringified into non-ISO strings), and the developer's ro

  serialization_pipeline_chain: 1 instances
    should fix: serializer.py
    actually fixed: []
    root_cause: 
    oracle said: The ground truth states serialize converts created_at ISO strings to epoch integers via EPOCH_TABLE (leading to integer timestamps downstream), and th

  billing_aggregation_chain_trap_1: 1 instances
    should fix: collector.py
    actually fixed: ['plan_resolver.py']
    root_cause: _resolve_tier function incorrectly determines the tier based on the maximum units instead of the total units used, leading to incorrect rate applicati
    oracle said: The ground truth says aggregate_usage groups by the local date (not converting timestamps to UTC), while the developer correctly blames collector.py f

  event_etl_chain: 1 instances
    should fix: normalizer.py
    actually fixed: ['enricher.py']
    root_cause: enrich_node function is using the user_id directly without normalizing it, causing mismatches with USER_PROFILES keys.
    oracle said: The ground truth states normalize lowercases user_id (corrupting its case) which breaks the case-sensitive USER_PROFILES lookup, and the developer's r

  logging_pipeline_chain_trap_1: 1 instances
    should fix: collector.py
    actually fixed: ['dashboard.py']
    root_cause: render_dashboard_node function incorrectly calculates alert_count by using metrics.get(ALERT_THRESHOLD, 0) which returns 0 for non-critical events, le
    oracle said: The ground truth specifies that collect_events_node truncates severity strings (e.g., 'CRITICAL'→'CRIT') causing misclassification, and the developer'

5. SPEC ORACLE DEPTH CLASSIFICATION
----------------------------------------
  depth A: 160 instances
  depth D: 44 instances
  depth F: 176 instances

Per-case depth (baseline condition, trial 1):
  auth_context_chain                            depth= F  pass=False  oracle=CORRECT
  auth_context_chain_trap_1                     depth= F  pass=False  oracle=WRONG
  auth_context_chain_trap_3                     depth= F  pass=False  oracle=WRONG
  auth_context_chain_trap_4                     depth= A  pass=True  oracle=PARTIAL
  auth_context_chain_trap_5                     depth= F  pass=False  oracle=WRONG
  billing_aggregation_chain                     depth= F  pass=False  oracle=WRONG
  billing_aggregation_chain_trap_1              depth= F  pass=False  oracle=WRONG
  billing_aggregation_chain_trap_3              depth= F  pass=False  oracle=UNASSESSED
  billing_aggregation_chain_trap_4              depth= F  pass=False  oracle=WRONG
  billing_aggregation_chain_trap_5              depth= F  pass=False  oracle=WRONG
  config_derivation_chain                       depth= F  pass=False  oracle=CORRECT
  config_derivation_chain_trap_1                depth= F  pass=False  oracle=CORRECT
  config_derivation_chain_trap_3                depth= A  pass=True  oracle=CORRECT
  config_derivation_chain_trap_4                depth= A  pass=True  oracle=CORRECT
  config_derivation_chain_trap_5                depth= A  pass=True  oracle=CORRECT
  event_etl_chain                               depth= F  pass=False  oracle=WRONG
  event_etl_chain_trap_1                        depth= F  pass=False  oracle=WRONG
  event_etl_chain_trap_3                        depth= F  pass=False  oracle=CORRECT
  event_etl_chain_trap_4                        depth= F  pass=False  oracle=WRONG
  event_etl_chain_trap_5                        depth= A  pass=True  oracle=CORRECT
  logging_pipeline_chain                        depth= A  pass=True  oracle=CORRECT
  logging_pipeline_chain_trap_1                 depth= F  pass=False  oracle=WRONG
  logging_pipeline_chain_trap_3                 depth= A  pass=True  oracle=CORRECT
  logging_pipeline_chain_trap_4                 depth= A  pass=True  oracle=CORRECT
  logging_pipeline_chain_trap_5                 depth= A  pass=True  oracle=CORRECT
  ml_feature_chain                              depth= A  pass=True  oracle=PARTIAL
  ml_feature_chain_trap_1                       depth= F  pass=False  oracle=CORRECT
  ml_feature_chain_trap_3                       depth= F  pass=False  oracle=CORRECT
  ml_feature_chain_trap_4                       depth= A  pass=True  oracle=CORRECT
  ml_feature_chain_trap_5                       depth= A  pass=True  oracle=CORRECT
  search_index_chain                            depth= D  pass=False  oracle=WRONG
  search_index_chain_trap_3                     depth= A  pass=True  oracle=CORRECT
  search_index_chain_trap_5                     depth= D  pass=False  oracle=WRONG
  serialization_pipeline_chain                  depth= D  pass=False  oracle=CORRECT
  serialization_pipeline_chain_trap_1           depth= A  pass=True  oracle=CORRECT
  serialization_pipeline_chain_trap_3           depth= A  pass=True  oracle=CORRECT
  serialization_pipeline_chain_trap_4           depth= D  pass=False  oracle=WRONG
  serialization_pipeline_chain_trap_5           depth= D  pass=False  oracle=WRONG

6. DIRECTED HINT EFFECTIVENESS
----------------------------------------
Critique condition: attempt 0 (no hint) → attempt 1 (after directed hint)

  Total hints given: 96
  Hints that fixed: 4 (4% if hint_tried else 0)

Cases where directed hint fixed the failure:
  event_etl_chain_trap_3 (trial_002):
    a0 changed: ['normalizer.py']
    a1 changed: ['normalizer.py']
    hint: Your fix compensates for corrupted data at a downstream node. Trace the data flow backward: which node first transforms the value into the wrong form?
    a1 root_cause: The user IDs are being incorrectly transformed to lowercase in the normalizer, which causes mismatches with the keys in USER_PROFILES. The transformat

  serialization_pipeline_chain_trap_5 (trial_003):
    a0 changed: ['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']
    a1 changed: ['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']
    hint: Your fix compensates for corrupted data at a downstream node. Trace the data flow backward: which node first transforms the value into the wrong form?
    a1 root_cause: The 'serialize' function incorrectly sets the 'created_at' field to the epoch timestamp instead of the ISO format, which is the source of the corrupti

  event_etl_chain_trap_3 (trial_004):
    a0 changed: ['normalizer.py']
    a1 changed: ['normalizer.py']
    hint: Your fix compensates for corrupted data at a downstream node. Trace the data flow backward: which node first transforms the value into the wrong form?
    a1 root_cause: The user IDs are being incorrectly transformed to lowercase in the normalizer, which causes mismatches with the keys in USER_PROFILES. The transformat

  event_etl_chain_trap_3 (trial_005):
    a0 changed: ['normalizer.py']
    a1 changed: ['normalizer.py']
    hint: Your fix compensates for corrupted data at a downstream node. Trace the data flow backward: which node first transforms the value into the wrong form?
    a1 root_cause: The user IDs are being incorrectly transformed to lowercase in the normalizer, which causes mismatches with the keys in USER_PROFILES. The transformat

Cases where directed hint did NOT help (sample):
  auth_context_chain (trial_001):
    a0 changed: ['resolver.py'] → a1 changed: ['normalizer.py', 'resolver.py']
    a1 root_cause: The org_id is being incorrectly normalized in the normalizer.py, leading to corrupted data that affects downstream nodes
  auth_context_chain_trap_1 (trial_001):
    a0 changed: ['resolver.py'] → a1 changed: ['normalizer.py', 'resolver.py']
    a1 root_cause: The issue originates from the normalization process where the user data is incorrectly formatted before reaching the res
  auth_context_chain_trap_3 (trial_001):
    a0 changed: ['resolver.py'] → a1 changed: ['normalizer.py', 'resolver.py']
    a1 root_cause: The issue originates from the data transformation process where organization IDs are incorrectly formatted. The node res
  auth_context_chain_trap_4 (trial_001):
    a0 changed: [] → a1 changed: []
    a1 root_cause: 
  auth_context_chain_trap_5 (trial_001):
    a0 changed: ['resolver.py'] → a1 changed: ['normalizer.py', 'resolver.py']
    a1 root_cause: The issue originates from the normalization process where the 'org_id' is incorrectly set instead of 'canonical_org_id'.
  billing_aggregation_chain (trial_001):
    a0 changed: ['plan_resolver.py', 'rate_engine.py', 'invoice_builder.py'] → a1 changed: ['plan_resolver.py', 'rate_engine.py', 'invoice_builder.py']
    a1 root_cause: The _resolve_tier function incorrectly assigns tiers based on the maximum units without considering timezone offsets, le
  billing_aggregation_chain_trap_1 (trial_001):
    a0 changed: ['plan_resolver.py'] → a1 changed: ['collector.py', 'plan_resolver.py']
    a1 root_cause: The initial transformation of usage records in the collector node incorrectly aggregates or formats the units, leading t
  config_derivation_chain (trial_001):
    a0 changed: ['deriver.py'] → a1 changed: ['parser.py', 'deriver.py']
    a1 root_cause: The initial value for 'max_conn' is being incorrectly set in the parser, leading to invalid pool_size calculations downs
  config_derivation_chain_trap_1 (trial_001):
    a0 changed: ['deriver.py'] → a1 changed: ['deriver.py', 'parser.py']
    a1 root_cause: The initial data source is providing the port as a string instead of an integer, leading to downstream issues in the der
  event_etl_chain (trial_001):
    a0 changed: ['enricher.py'] → a1 changed: ['source.py', 'enricher.py']
    a1 root_cause: The user_id is being introduced in an inconsistent format (case sensitivity, presence of hyphens) at the source of the d

7. MECHANISM vs DEPTH: THE CORE FINDING
----------------------------------------

The generic oracle evaluates MECHANISM identification (what goes wrong and how).
The spec oracle evaluates DEPTH (where the fix is applied in the chain).
These are genuinely different dimensions.

Evidence from this ablation:

  Mechanism correct + test failed (baseline): 31 instances

Examples:
  auth_context_chain:
    Mechanism (oracle=CORRECT): "resolve_permissions_node function is incorrectly using the org_id after normalization, which leads t"
    Intervention (wrong file): changed ['resolver.py'], should fix normalizer.py
    Depth: F

  config_derivation_chain:
    Mechanism (oracle=CORRECT): "derive_settings_node function's pool_size calculation is incorrect because it multiplies the port (a"
    Intervention (wrong file): changed ['deriver.py'], should fix parser.py
    Depth: F

  config_derivation_chain_trap_1:
    Mechanism (oracle=CORRECT): "derive_settings_node function's pool_size calculation uses port directly, leading to incorrect pool_"
    Intervention (wrong file): changed ['deriver.py'], should fix parser.py
    Depth: F

  event_etl_chain_trap_3:
    Mechanism (oracle=CORRECT): "normalize function is converting user IDs to lowercase, causing 'SYSADMIN' to be transformed to 'sys"
    Intervention (wrong file): changed ['normalizer.py'], should fix normalizer.py
    Depth: F

  ml_feature_chain_trap_1:
    Mechanism (oracle=CORRECT): "_engineer_features_buggy function has a logic error in calculating the rolling mean, which leads to "
    Intervention (wrong file): changed ['features.py', 'scaler.py', 'scorer.py'], should fix features.py
    Depth: F

  ml_feature_chain_trap_3:
    Mechanism (oracle=CORRECT): "features.py: _engineer_features_buggy function incorrectly calculates the rolling mean by using 'win"
    Intervention (wrong file): changed ['features.py'], should fix features.py
    Depth: F

  serialization_pipeline_chain:
    Mechanism (oracle=CORRECT): "serialize function's use of EPOCH_TABLE to convert 'created_at' timestamps to epoch values is causin"
    Intervention (wrong file): changed ['serializer.py'], should fix serializer.py
    Depth: D

  serialization_pipeline_chain_trap_5:
    Mechanism (oracle=CORRECT): "serialize function must correctly set the 'created_at' field to the ISO format instead of the epoch "
    Intervention (wrong file): changed ['serializer.py'], should fix serializer.py
    Depth: D

  search_index_chain_trap_5:
    Mechanism (oracle=CORRECT): "extract_fields function does not filter out metadata fields, leading to their inclusion in extracted"
    Intervention (wrong file): changed ['extractor.py'], should fix extractor.py
    Depth: D

  serialization_pipeline_chain_trap_3:
    Mechanism (oracle=CORRECT): "serialize function's reconverted variable incorrectly replaces 'T' with a space, resulting in a non-"
    Intervention (wrong file): changed ['serializer.py'], should fix serializer.py
    Depth: D

Conclusion: LLMs can correctly identify bug mechanisms but systematically
choose to fix at the wrong depth — compensating downstream rather than
repairing the source. This is a measurable, reproducible reasoning-execution
gap that the DDC benchmark quantifies through trap variants.

8. ALL INTERVENTION SENTENCES (directed hint text)
----------------------------------------

The directed hint given on retry:

  "Your fix compensates for corrupted data at a downstream node.
   Trace the data flow backward: which node first transforms the
   value into the wrong form? The node that introduces the corruption
   is the one that should be fixed, not the nodes that consume the
   corrupted value. Your current fix will break on edge cases because
   it works around the problem instead of eliminating it."

Given to 96 failed attempts. Fixed 4 (4%).

For comparison, the other hint levels (tested on serialization_pipeline_chain_trap_1):

GENTLE (failed — 3/3 attempts still wrong):
  "Your fix addresses the symptom at a downstream node, but the
   root cause is upstream. The data is already wrong before it
   reaches the node you modified. Look earlier in the pipeline
   for where the correct value was first corrupted."

EXPLICIT (succeeded — passed on attempt 1):
  "Your fix is in the wrong file. The root cause is in
   serializer.py: serialize converts created_at from ISO string
   to epoch integer via EPOCH_TABLE lookup. Fix that node directly
   instead of compensating downstream."

================================================================================
9. DEEP DIVE: MODEL REASONING ON HARD CASES
================================================================================

9a. billing_aggregation_chain (0% across all hints and conditions)
----------------------------------------------------------------------
The model NEVER identifies the collector as the problem. Across all 9 hint
runs and 5 baseline trials, it consistently blames _resolve_tier in
plan_resolver.py — "incorrectly assigns tiers without considering timezone
offsets." It tries to make the tier resolver timezone-aware instead of
fixing the collector's date grouping.

The model doesn't understand that the UNIT COUNT is wrong, not the tier
logic. The tier table correctly maps 85→growth and 100→enterprise. The
problem is that the collector produces 85 (local date grouping) instead of
100 (UTC grouping). But the model sees "wrong tier" as the symptom and
concludes the tier assignment is broken.

Every hint bounces off because the model's mental model of the bug is
fundamentally wrong at the causal level — not just at the depth level.
No amount of "go upstream" helps when the model doesn't understand that
unit aggregation (collector) feeds into tier resolution (plan_resolver).

9b. config_derivation_chain_trap_1 (0% across all hints, 100% LEG)
----------------------------------------------------------------------
The model ALWAYS identifies the right mechanism ("port is a string,
multiplication gives wrong result") but ALWAYS fixes deriver.py instead of
parser.py. Even "name the exact statement that first mutates the value"
doesn't redirect it — the model names derive_settings_node's multiplication
as "the statement" instead of parse_config's failure to convert.

The model sees the deriver as the corruption point because that's where
string multiplication happens. It doesn't recognize that parse_config
SHOULD have already converted PORT to int — the parser's omission is
the root cause, not the deriver's arithmetic on the string it received.

This is a pure depth error: correct mechanism, wrong fault attribution.
The model treats the first VISIBLE error (string × 2 = repeat) as the
first CAUSAL error (parser didn't convert). This distinction between
"where the symptom appears" and "where the corruption originates" is
exactly what the DDC benchmark measures.

9c. event_etl_chain_trap_3 (variable — sometimes passes, never hint-fixed)
----------------------------------------------------------------------
The model is anchored on the trap_3 heuristic pattern. When it succeeds
(a0 pass), it's because it independently chose to remove lowercasing
broadly. When it fails, it reproduces or extends the heuristic:
  - Adds 'SYSADMIN' as a special case (hardcoded string match)
  - Keeps the _/- preservation and adds more patterns
  - In one case, literally reproduced the exact trap_3 code

The "edge_case_anti_heuristic" hint produced a lucky pass: the model
hardcoded `if v == 'SYSADMIN': preserve` alongside the existing heuristic.
This passed the test but is a brittle fix that would fail on any new
all-caps user. The model can't generalize from "SYSADMIN fails" to
"user_id should never be lowercased."

CORE INSIGHT: gpt-4o-mini doesn't distinguish between "where the symptom
manifests" and "where the corruption originates." For billing it sees wrong
tiers and fixes the tier logic. For config_derivation it sees string
multiplication and fixes the multiplier. For event_etl it sees failed
lookups and adds special cases. None of the 9 hints can fix this because
the model's causal model is wrong at a level deeper than intervention
depth — it doesn't understand the concept of upstream corruption
propagating through a pipeline.
