====================================================================================================
DDC METRICS AUDIT: 3-AXIS RECOMPUTATION
====================================================================================================

METRIC DEFINITIONS
------------------------------------------------------------
mechanism_correct:  oracle_label in {CORRECT, PARTIAL}
  Evaluates: did the model's root_cause text describe the bug mechanism?
  Does NOT evaluate: intervention location, file choice, code correctness

location_correct:   reference_fix.file in changed_files
  Evaluates: did the model touch the file containing the root cause?
  Deterministic — no LLM judgment involved

execution_pass:     spec_oracle.depth == 'A' OR test_pass == True
  Evaluates: did the model's code actually fix the bug?
  Uses spec oracle (code-based, 0% error rate) as primary signal

LEG (corrected):    mechanism_correct AND location_correct AND NOT execution_pass
  The model understood the bug AND touched the right file BUT the code was wrong
  This is stricter than the old LEG which only required mechanism_correct

Lucky:              (NOT mechanism_correct OR NOT location_correct) AND execution_pass
  The model passed despite wrong reasoning OR wrong file

COMPARISON VS OLD METRICS
------------------------------------------------------------
Old LEG = mechanism_correct AND NOT execution_pass
  Problem: counted cases where model described mechanism but fixed wrong file
  These are not execution gaps — they are location errors

New LEG = mechanism_correct AND location_correct AND NOT execution_pass
  Only counts cases where the model knew what AND where, but failed how

Old LEG total: 164
New LEG total: 124
Reclassified as location errors: 40
  (cases that were old-LEG but are NOT new-LEG because location_correct=False)

AGGREGATE TABLE
----------------------------------------------------------------------------------------------------
model          condition                             n  mech   loc  exec  pass   LEG lucky files
----------------------------------------------------------------------------------------------------
gpt-4o-mini    c1_retry_only                        23  0.38  0.75  0.50  0.13  0.13  0.00  1.13
gpt-4o-mini    c2_first_corruption                  23  0.45  0.78  0.43  0.13  0.17  0.00  1.13
gpt-4o-mini    c3_anti_compensation                 23  0.48  1.00  0.30  0.13  0.30  0.00  1.43
gpt-4o-mini    c4_minimality                        23  0.26  0.83  0.40  0.09  0.13  0.00  1.00
gpt-4o-mini    c5_single_file                       23  0.36  0.75  0.33  0.09  0.17  0.00  0.96
gpt-4o-mini    c6_first_corruption_minimality       23  0.41  0.89  0.50  0.17  0.17  0.00  1.09
gpt-4o-mini    c7_anti_compensation_single_file     22  0.33  0.86  0.50  0.14  0.14  0.00  0.95
gpt-4o-mini    c8_no_touch                          22  0.20  0.75  0.00  0.00  0.14  0.00  0.86
gpt-4o-mini    v4c1_first_corruption                23  0.30  0.67  0.25  0.04  0.13  0.00  1.13
gpt-4o-mini    v4c2_minimality                      23  0.38  0.88  0.57  0.17  0.13  0.00  0.91
gpt-4o-mini    v4c3_transformation_localization     23  0.14  0.33  1.00  0.09  0.00  0.04  0.96
gpt-4o-mini    v4c4_no_refactor                     23  0.30  0.83  0.40  0.09  0.13  0.00  0.87
gpt-4o-mini    v4c5_impl_scope                      23  0.18  0.75  0.33  0.09  0.09  0.04  0.96
gpt-4o-mini    v4c6_location_impl                   23  0.38  0.75  0.50  0.17  0.13  0.04  1.00
gpt-4o-mini    v4c7_location_scope_impl             23  0.50  0.90  0.33  0.13  0.26  0.00  1.00
gpt-5-mini     c1_retry_only                         8  0.50  0.50  1.00  0.25  0.00  0.00  1.25
gpt-5-mini     c2_first_corruption                   8  0.62  1.00  0.80  0.50  0.12  0.00  1.62
gpt-5-mini     c3_anti_compensation                  8  0.50  1.00  0.50  0.25  0.25  0.00  1.88
gpt-5-mini     c4_minimality                         8  0.62  0.60  1.00  0.38  0.00  0.00  1.00
gpt-5-mini     c5_single_file                        8  0.62  0.60  0.67  0.25  0.12  0.00  1.00
gpt-5-mini     c6_first_corruption_minimality        8  0.75  0.83  0.60  0.38  0.25  0.00  1.00
gpt-5-mini     c7_anti_compensation_single_file      8  0.75  0.83  0.60  0.38  0.25  0.00  1.00
gpt-5-mini     c8_no_touch                           8  0.62  0.60  0.67  0.25  0.12  0.00  0.88
gpt-5-mini     v4c1_first_corruption                 8  0.38  1.00  0.67  0.25  0.12  0.00  1.38
gpt-5-mini     v4c2_minimality                       8  0.50  0.50  0.50  0.12  0.12  0.00  1.00
gpt-5-mini     v4c3_transformation_localization      8  0.62  1.00  0.80  0.50  0.12  0.00  1.62
gpt-5-mini     v4c4_no_refactor                      8  0.50  0.50  1.00  0.25  0.00  0.00  1.00
gpt-5-mini     v4c5_impl_scope                       8  0.50  0.75  0.33  0.12  0.25  0.00  1.00
gpt-5-mini     v4c6_location_impl                    8  0.62  1.00  0.80  0.50  0.12  0.00  1.50
gpt-5-mini     v4c7_location_scope_impl              8  0.50  1.00  1.00  0.50  0.00  0.00  1.00
gpt-5.4-mini   c1_retry_only                        16  0.40  1.00  0.50  0.19  0.19  0.00  4.69
gpt-5.4-mini   c2_first_corruption                  16  1.00  1.00  0.50  0.50  0.50  0.00  5.00
gpt-5.4-mini   c3_anti_compensation                 16  0.69  1.00  0.73  0.50  0.19  0.00  4.69
gpt-5.4-mini   c4_minimality                        16  0.31  1.00  0.40  0.12  0.19  0.00  4.50
gpt-5.4-mini   c5_single_file                       16  0.31  0.60  0.33  0.06  0.12  0.00  1.50
gpt-5.4-mini   c6_first_corruption_minimality       16  0.75  1.00  0.67  0.50  0.25  0.00  4.75
gpt-5.4-mini   c7_anti_compensation_single_file     16  0.44  1.00  0.57  0.25  0.19  0.00  3.50
gpt-5.4-mini   c8_no_touch                          16  0.56  1.00  0.78  0.62  0.12  0.19  4.25
gpt-5.4-mini   v4c1_first_corruption                16  0.88  1.00  0.64  0.56  0.31  0.00  5.00
gpt-5.4-mini   v4c2_minimality                      16  0.56  0.89  0.38  0.19  0.31  0.00  4.12
gpt-5.4-mini   v4c3_transformation_localization     16  0.62  1.00  0.50  0.31  0.31  0.00  5.00
gpt-5.4-mini   v4c4_no_refactor                     16  0.62  0.90  0.44  0.25  0.31  0.00  4.69
gpt-5.4-mini   v4c5_impl_scope                      16  0.50  1.00  0.50  0.25  0.25  0.00  4.50
gpt-5.4-mini   v4c6_location_impl                   16  0.62  1.00  0.80  0.56  0.12  0.06  5.00
gpt-5.4-mini   v4c7_location_scope_impl             16  0.81  0.92  0.67  0.56  0.25  0.06  4.44

TOP LEG CASES (mechanism + location correct, execution failed)
----------------------------------------------------------------------------------------------------
  gpt-5.4-mini × ml_feature_chain_trap_1: 13 occurrences
    changed: ['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'], ref: features.py
    root_cause: The previous fix changed the rolling window logic, but the real issue is that the feature pipeline is not preserving the
  gpt-4o-mini × ml_feature_chain_trap_3: 12 occurrences
    changed: ['features.py'], ref: features.py
    root_cause: _engineer_features_buggy function incorrectly calculates the rolling mean by using an incorrect window size, leading to 
  gpt-4o-mini × ml_feature_chain_trap_1: 10 occurrences
    changed: ['features.py'], ref: features.py
    root_cause: _engineer_features_buggy function has a logic error in calculating the rolling mean for short datasets, leading to incor
  gpt-4o-mini × auth_context_chain: 7 occurrences
    changed: ['normalizer.py', 'resolver.py'], ref: normalizer.py
    root_cause: The normalization of org_id in the normalizer.py file is incorrectly splitting the org_id on '-' and only taking the sec
  gpt-5.4-mini × billing_aggregation_chain_trap_3: 7 occurrences
    changed: ['collector.py', 'data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py'], ref: collector.py
    root_cause: The timestamp conversion bug is introduced inside _to_utc: it assumes a fixed timezone offset, so every event is shifted
  gpt-5.4-mini × ml_feature_chain_trap_3: 7 occurrences
    changed: ['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'], ref: features.py
    root_cause: The bug is in features._engineer_features_buggy: it incorrectly shortens the rolling window by one when selecting values
  gpt-4o-mini × event_etl_chain_trap_3: 6 occurrences
    changed: ['normalizer.py'], ref: normalizer.py
    root_cause: The normalize function is incorrectly converting user IDs to lowercase, which causes mismatches with the keys in USER_PR
  gpt-5.4-mini × billing_aggregation_chain_trap_5: 6 occurrences
    changed: ['collector.py', 'data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py'], ref: collector.py
    root_cause: The bug is introduced in collector.aggregate_usage when it groups events by the local timestamp date (event['ts'][:10]) 
  gpt-5-mini × billing_aggregation_chain: 6 occurrences
    changed: ['collector.py'], ref: collector.py
    root_cause: collector.aggregate_usage ignored the dataset tz offset semantics and applied an incorrect transformation. The previous 
  gpt-5.4-mini × billing_aggregation_chain_trap_4: 5 occurrences
    changed: ['collector.py', 'data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py'], ref: collector.py
    root_cause: collector.aggregate_usage was still emitting period buckets derived from the raw event date instead of applying the bill

TOP LUCKY CASES (execution passed despite wrong mechanism or location)
----------------------------------------------------------------------------------------------------
  gpt-5.4-mini × ml_feature_chain_trap_3: 2 occurrences
    mechanism=False, location=True
    changed: ['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'], ref: features.py
    root_cause: The earlier diagnosis was incorrect: features._engineer_features_buggy() is not the root cause. The feature engineering 
  gpt-4o-mini × event_etl_chain_trap_3: 2 occurrences
    mechanism=False, location=True
    changed: ['normalizer.py'], ref: normalizer.py
    root_cause: normalize function is not handling the user_id 'SYSADMIN' correctly due to the absence of a transformation for the under
  gpt-5.4-mini × billing_aggregation_chain_trap_3: 1 occurrences
    mechanism=False, location=True
    changed: ['collector.py'], ref: collector.py
    root_cause: The earlier diagnosis was too broad. The only confirmed issue is in collector.py: aggregate_usage uses the dataset's tz_
  gpt-5.4-mini × ml_feature_chain_trap_1: 1 occurrences
    mechanism=False, location=True
    changed: ['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'], ref: features.py
    root_cause: The prior diagnosis was wrong: `features._engineer_features_buggy()` is already using `min(window, len(values))`, so the
  gpt-4o-mini × search_index_chain_trap_5: 1 occurrences
    mechanism=False, location=True
    changed: ['extractor.py'], ref: extractor.py
    root_cause: The extract_fields function in extractor.py incorrectly includes metadata fields in content_fields and clean_content.
  gpt-5.4-mini × auth_context_chain_trap_4: 1 occurrences
    mechanism=False, location=True
    changed: ['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'], ref: normalizer.py
    root_cause: normalizer.py::normalize_context is stripping the org_id prefix too early by rewriting values like ORG-100 -> 100 and DE

EXAMPLES: MECHANISM CORRECT, WRONG LOCATION
----------------------------------------------------------------------------------------------------
  gpt-4o-mini × auth_context_chain:
    changed: ['resolver.py'], correct: normalizer.py
    root_cause: The resolve_permissions_node function is incorrectly normalizing org_id by splitting on '-' and only taking the second p
  gpt-4o-mini × config_derivation_chain_trap_1:
    changed: ['deriver.py'], correct: parser.py
    root_cause: The derive_settings_node function's pool_size calculation uses port directly, which can lead to incorrect results if POR
  gpt-4o-mini × auth_context_chain_trap_5:
    changed: ['resolver.py'], correct: normalizer.py
    root_cause: The 'org_id' is being set incorrectly in the 'resolve_permissions_node' function, using 'normalized["org_id"]' instead o
  gpt-4o-mini × config_derivation_chain:
    changed: ['deriver.py'], correct: parser.py
    root_cause: The pool_size calculation in the derive_settings_node function incorrectly uses the port as a string, leading to an inva
  gpt-5.4-mini × serialization_pipeline_chain_trap_1:
    changed: ['transport.py'], correct: serializer.py
    root_cause: The failure is not in transport normalization logic. The real issue is that the transport layer is receiving epoch integ
  gpt-5.4-mini × auth_context_chain_trap_4:
    changed: ['resolver.py'], correct: normalizer.py
    root_cause: The bug is in resolver.py: the resolver should preserve the canonical org identifier from USER_DB when a matching user r
  gpt-5-mini × serialization_pipeline_chain_trap_1:
    changed: ['transport.py'], correct: serializer.py
    root_cause: transport_node coerced numeric epoch timestamps into plain decimal strings (e.g. '1743501600') instead of ISO-formatted 
  gpt-5-mini × serialization_pipeline_chain_trap_4:
    changed: ['compressor.py'], correct: serializer.py
    root_cause: compressor.compress_node converted timestamps only on a copied output record (out = dict(rec)) and returned those copies

EXAMPLES: CORRECT LOCATION, FAILED EXECUTION (true LEG)
----------------------------------------------------------------------------------------------------
  gpt-4o-mini × billing_aggregation_chain_trap_4:
    changed: ['collector.py'], correct: collector.py
    root_cause: The aggregate_usage function in collector.py is aggregating units based on the local timestamp without considering the t
  gpt-4o-mini × ml_feature_chain_trap_3:
    changed: ['features.py'], correct: features.py
    root_cause: _engineer_features_buggy function incorrectly calculates the rolling mean by using an incorrect window size, leading to 
  gpt-4o-mini × event_etl_chain_trap_3:
    changed: ['normalizer.py'], correct: normalizer.py
    root_cause: The normalize function is incorrectly converting user IDs to lowercase, which causes mismatches with the keys in USER_PR
  gpt-4o-mini × auth_context_chain:
    changed: ['normalizer.py', 'resolver.py'], correct: normalizer.py
    root_cause: The normalization of org_id in the normalizer.py file is incorrectly splitting the org_id on '-' and only taking the sec
  gpt-4o-mini × ml_feature_chain_trap_1:
    changed: ['features.py'], correct: features.py
    root_cause: _engineer_features_buggy function has a logic error in calculating the rolling mean for short datasets, leading to incor
  gpt-4o-mini × search_index_chain:
    changed: ['extractor.py', 'tokenizer.py'], correct: extractor.py
    root_cause: The 'author' field is being included in the content fields during the extraction process, leading to incorrect tokenizat
  gpt-4o-mini × serialization_pipeline_chain_trap_5:
    changed: ['serializer.py'], correct: serializer.py
    root_cause: The 'created_at' field is being set incorrectly to the epoch timestamp instead of the ISO format in the serialize functi
  gpt-4o-mini × auth_context_chain_trap_5:
    changed: ['normalizer.py', 'resolver.py'], correct: normalizer.py
    root_cause: The transformation in the normalizer is incorrectly setting 'org_id' instead of 'canonical_org_id', leading to the use o

MODEL COMPARISON ACROSS AXES
----------------------------------------------------------------------------------------------------
  gpt-4o-mini (n=343):
    mechanism_accuracy:     0.31  (106/343)
    localization_accuracy:  0.81  (86/106 of mechanism-correct)
    execution_fidelity:     0.41  (35/86 of mechanism+location correct)
    LEG_rate:              0.149  (51/343)

  gpt-5-mini (n=120):
    mechanism_accuracy:     0.57  (69/120)
    localization_accuracy:  0.78  (54/69 of mechanism-correct)
    execution_fidelity:     0.72  (39/54 of mechanism+location correct)
    LEG_rate:              0.125  (15/120)

  gpt-5.4-mini (n=240):
    mechanism_accuracy:     0.60  (145/240)
    localization_accuracy:  0.97  (140/145 of mechanism-correct)
    execution_fidelity:     0.59  (82/140 of mechanism+location correct)
    LEG_rate:              0.242  (58/240)

LEG FAILURE MODE BREAKDOWN
----------------------------------------------------------------------------------------------------
111/124 LEG cases (90%) are INVARIANT_FAILURE — the code ran successfully but produced wrong
output. The model touched the right file, the reconstruction worked, the code executed, but
the fix was logically incorrect. These are genuine implementation errors, not build/syntax/
reconstruction problems.

The remaining 13:
- 8 NAME_ERROR (all gpt-4o-mini) — the code referenced an undefined variable, so it crashed
  at runtime. The model wrote syntactically valid but semantically broken code.
- 3 INVARIANT_CRASH — the code crashed during test execution (e.g., wrong types passed
  between pipeline nodes).
- 2 IMPORT_FAILURE (gpt-5-mini) — the model imported a module that doesn't exist in the
  sandbox (e.g., from datetime import datetime).

Zero reconstruction failures. Every LEG case had recon=SUCCESS. The pipeline assembled the
code correctly — the model's code was simply wrong.

For gpt-5.4-mini specifically: 57/58 LEG cases are INVARIANT_FAILURE. The model produces
syntactically valid, importable, runnable code that touches the right file — but the logic
doesn't fix the bug. This is pure implementation quality failure, not an infrastructure issue.
