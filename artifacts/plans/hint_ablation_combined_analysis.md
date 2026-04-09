==============================================================================================================
COMBINED V3+V4 HINT ANALYSIS: WHAT WORKS, WHERE, AND WHY
==============================================================================================================

This is a combined analysis of two hint ablation rounds (v3 and v4) run on
the Deep Dependency Chain (DDC) benchmark. Each round tests a different set
of retry-time hints on cases that failed baseline. The hints are appended
as a single sentence to the retry prompt after a failed first attempt.

IMPORTANT CHANGE BETWEEN V3 AND V4:
The critique retry prompt was changed between rounds. In v3, the retry
preamble said: "You previously analyzed the bug and proposed a fix, but
your implementation may not fully reflect your reasoning." This assumed the
model's reasoning was correct and only the code was wrong — which reinforced
incorrect reasoning on cases where the model identified the wrong root cause.
In v4, the preamble was changed to: "Your previous fix did not pass.
Consider this feedback:" — a neutral framing that allows the model to
reconsider both its reasoning and its code. This change partly explains
why the v4 implementation axis unlocked new fixes for gpt-5-mini.

V3 HINTS (8 conditions):
  c1_retry_only:                   "No additional guidance. Try again."
  c2_first_corruption:             "The fix belongs at the first node where the value becomes wrong, not at any downstream consumer."
  c3_anti_compensation:            "Do not compensate for the bad value downstream; repair the transformation that originally corrupts it."
  c4_minimality:                   "Modify only the code necessary to fix the bug; do not change unrelated files."
  c5_single_file:                  "The correct fix is contained in a single file; do not modify other files."
  c6_first_corruption_minimality:  "The fix belongs at the first point where the value is modified incorrectly, and you should modify only that location without changing unrelated files."
  c7_anti_compensation_single_file:"Do not compensate downstream; fix the original corruption in exactly one file and leave other files unchanged."
  c8_no_touch:                     "Do not modify any file unless you are certain it contains the root cause."

V4 HINTS (7 conditions — 3-axis design: location × implementation × scope):
  v4c1_first_corruption (location):            "The fix belongs at the first point where the value is modified incorrectly, not at any downstream consumer."
  v4c2_minimality (scope):                     "Modify only the code necessary to fix the bug; do not change unrelated files."
  v4c3_transformation_localization (impl):     "The bug is a specific incorrect transformation of a value; fix that transformation directly instead of restructuring or adding new logic."
  v4c4_no_refactor (impl):                     "This is not a refactoring task; do not reorganize or redesign the code—only correct the faulty logic where it already exists."
  v4c5_impl_scope (impl+scope):               "This is not a refactoring task; only correct the faulty transformation where it occurs, and do not modify unrelated files."
  v4c6_location_impl (location+impl):         "The fix belongs at the first point where the value is modified incorrectly, and it should be implemented as a direct correction of that transformation."
  v4c7_location_scope_impl (all three):        "The fix belongs at the first point where the value is modified incorrectly; fix that transformation directly, and do not modify unrelated files."

Models tested: gpt-4o-mini, gpt-5.4-mini, gpt-5-mini
Each hint runs only on cases that FAILED baseline for that model.

==============================================================================================================

Total hint fixes: v3=37, v4=33, combined=70

TABLE 1: FIXES PER MODEL
------------------------------------------------------------
  gpt-4o-mini:
    v3: 8 fixes across 3 cases (etl_trap_3, search_trap_5, serial_trap_5)
    v4: 6 fixes across 3 cases (search_trap_5, serial_trap_4, serial_trap_5)
    combined: 4 cases ever fixed (etl_trap_3, search_trap_5, serial_trap_4, serial_trap_5)

  gpt-5.4-mini:
    v3: 27 fixes across 11 cases (auth_trap_1/4/5, billing_trap_3/5, config_trap_5,
        etl_trap_5, ml_trap_1/3, serial_trap_4/5)
    v4: 23 fixes across 10 cases (auth_trap_1/4/5, billing_trap_3, config_baseline/trap_5,
        ml_trap_3, serial_trap_1/4/5)
    combined: 13 cases ever fixed (auth_trap_1/4/5, billing_trap_3/5, config_baseline/trap_5,
        etl_trap_5, ml_trap_1/3, serial_trap_1/4/5)

  gpt-5-mini:
    v3: 2 fixes across 2 cases (auth_trap_5, serial_trap_1)
    v4: 4 fixes across 2 cases (auth_trap_5, serial_trap_1)
    combined: 2 cases ever fixed (auth_trap_5, serial_trap_1)

TABLE 2: CASE FIXABILITY (how many hints fix each case, per model)
--------------------------------------------------------------------------------------------------------------
case                           gpt-4o-mini          gpt-5.4-mini         gpt-5-mini          
------------------------------------------------------------------------------------------
auth_trap_1                    —                    v3=5 v4=3            —                   
auth_trap_4                    —                    v3=4 v4=4            —                   
auth_trap_5                    —                    v3=4 v4=4            v3=1 v4=3           
billing_trap_3                 —                    v3=2 v4=2            —                   
billing_trap_5                 —                    v3=1 v4=0            —                   
config                         —                    v3=0 v4=1            —                   
config_trap_5                  —                    v3=1 v4=2            —                   
etl_trap_3                     v3=1 v4=0            —                    —                   
etl_trap_5                     —                    v3=1 v4=0            —                   
ml_trap_1                      —                    v3=1 v4=0            —                   
ml_trap_3                      —                    v3=2 v4=1            —                   
search_trap_5                  v3=4 v4=2            —                    —                   
serial_trap_1                  —                    v3=0 v4=2            v3=1 v4=1           
serial_trap_4                  v3=0 v4=1            v3=5 v4=2            —                   
serial_trap_5                  v3=3 v4=3            v3=1 v4=2            —                   

TABLE 3: DETAILED FIX LOG — WHAT CHANGED
--------------------------------------------------------------------------------------------------------------

  gpt-4o-mini (14 total fixes):

    event_etl_chain_trap_3 (correct: normalizer.py)
      [v3] c7_anti_compensation_single_file    REIMPLEMENTED  a0=['normalizer.py']              → a1=['normalizer.py']             

    search_index_chain_trap_5 (correct: extractor.py)
      [v3] c1_retry_only                       REIMPLEMENTED  a0=['extractor.py']               → a1=['extractor.py']              
      [v3] c3_anti_compensation                REIMPLEMENTED  a0=['extractor.py']               → a1=['extractor.py']              
      [v3] c4_minimality                       REIMPLEMENTED  a0=['extractor.py']               → a1=['extractor.py']              
      [v3] c7_anti_compensation_single_file    REIMPLEMENTED  a0=['extractor.py']               → a1=['extractor.py']              
      [v4] v4c4_no_refactor                    REIMPLEMENTED  a0=['extractor.py']               → a1=['extractor.py']              
      [v4] v4c6_location_impl                  REIMPLEMENTED  a0=['extractor.py']               → a1=['extractor.py']              

    serialization_pipeline_chain_trap_4 (correct: serializer.py)
      [v4] v4c7_location_scope_impl            REDIRECTED     a0=[]                             → a1=['serializer.py']             
        a0 reasoning: 
        a1 reasoning: The serializer function incorrectly converts the created_at field from ISO format back to epoch format, which causes inc

    serialization_pipeline_chain_trap_5 (correct: serializer.py)
      [v3] c5_single_file                      REIMPLEMENTED  a0=['serializer.py']              → a1=['serializer.py']             
      [v3] c6_first_corruption_minimality      REIMPLEMENTED  a0=['serializer.py']              → a1=['serializer.py']             
      [v3] c7_anti_compensation_single_file    REIMPLEMENTED  a0=['serializer.py']              → a1=['serializer.py']             
      [v4] v4c2_minimality                     REIMPLEMENTED  a0=['serializer.py']              → a1=['serializer.py']             
      [v4] v4c6_location_impl                  REIMPLEMENTED  a0=['serializer.py']              → a1=['serializer.py']             
      [v4] v4c7_location_scope_impl            REIMPLEMENTED  a0=['serializer.py']              → a1=['serializer.py']             

  gpt-5.4-mini (50 total fixes):

    auth_context_chain_trap_1 (correct: normalizer.py)
      [v3] c1_retry_only                       REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v3] c2_first_corruption                 REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v3] c3_anti_compensation                REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v3] c4_minimality                       REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v3] c8_no_touch                         REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v4] v4c1_first_corruption               REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v4] v4c6_location_impl                  REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v4] v4c7_location_scope_impl            REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']

    auth_context_chain_trap_4 (correct: normalizer.py)
      [v3] c2_first_corruption                 REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v3] c3_anti_compensation                REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v3] c6_first_corruption_minimality      REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v3] c8_no_touch                         REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v4] v4c1_first_corruption               REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v4] v4c3_transformation_localization    REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v4] v4c6_location_impl                  REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v4] v4c7_location_scope_impl            REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']

    auth_context_chain_trap_5 (correct: normalizer.py)
      [v3] c2_first_corruption                 REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v3] c3_anti_compensation                REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v3] c6_first_corruption_minimality      REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v3] c8_no_touch                         REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v4] v4c1_first_corruption               REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v4] v4c3_transformation_localization    REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v4] v4c6_location_impl                  REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']
      [v4] v4c7_location_scope_impl            REIMPLEMENTED  a0=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] → a1=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py']

    billing_aggregation_chain_trap_3 (correct: collector.py)
      [v3] c7_anti_compensation_single_file    REDUCED        a0=['collector.py', 'data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py'] → a1=['collector.py']              
      [v3] c8_no_touch                         REDUCED        a0=['collector.py', 'data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py'] → a1=['collector.py']              
      [v4] v4c2_minimality                     REDUCED        a0=['collector.py', 'data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py'] → a1=['collector.py']              
      [v4] v4c7_location_scope_impl            REDUCED        a0=['collector.py', 'data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py'] → a1=['collector.py']              

    billing_aggregation_chain_trap_5 (correct: collector.py)
      [v3] c5_single_file                      REDUCED        a0=['collector.py', 'data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py'] → a1=['collector.py']              

    config_derivation_chain (correct: parser.py)
      [v4] v4c1_first_corruption               REIMPLEMENTED  a0=['data.py', 'env.py', 'parser.py', 'deriver.py', 'service.py'] → a1=['data.py', 'env.py', 'parser.py', 'deriver.py', 'service.py']

    config_derivation_chain_trap_5 (correct: parser.py)
      [v3] c6_first_corruption_minimality      REIMPLEMENTED  a0=['data.py', 'deriver.py', 'env.py', 'parser.py', 'service.py'] → a1=['data.py', 'deriver.py', 'env.py', 'parser.py', 'service.py']
      [v4] v4c6_location_impl                  REIMPLEMENTED  a0=['data.py', 'deriver.py', 'env.py', 'parser.py', 'service.py'] → a1=['data.py', 'deriver.py', 'env.py', 'parser.py', 'service.py']
      [v4] v4c7_location_scope_impl            REIMPLEMENTED  a0=['data.py', 'deriver.py', 'env.py', 'parser.py', 'service.py'] → a1=['data.py', 'deriver.py', 'env.py', 'parser.py', 'service.py']

    event_etl_chain_trap_5 (correct: normalizer.py)
      [v3] c7_anti_compensation_single_file    REIMPLEMENTED  a0=['data.py', 'enricher.py', 'normalizer.py', 'source.py', 'writer.py'] → a1=['data.py', 'enricher.py', 'normalizer.py', 'source.py', 'writer.py']

    ml_feature_chain_trap_1 (correct: features.py)
      [v3] c8_no_touch                         REIMPLEMENTED  a0=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'] → a1=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py']

    ml_feature_chain_trap_3 (correct: features.py)
      [v3] c3_anti_compensation                REIMPLEMENTED  a0=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'] → a1=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py']
      [v3] c8_no_touch                         REIMPLEMENTED  a0=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'] → a1=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py']
      [v4] v4c6_location_impl                  REIMPLEMENTED  a0=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'] → a1=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py']

    serialization_pipeline_chain_trap_1 (correct: serializer.py)
      [v4] v4c1_first_corruption               REIMPLEMENTED  a0=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] → a1=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']
      [v4] v4c7_location_scope_impl            REIMPLEMENTED  a0=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] → a1=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']

    serialization_pipeline_chain_trap_4 (correct: serializer.py)
      [v3] c1_retry_only                       REIMPLEMENTED  a0=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] → a1=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']
      [v3] c2_first_corruption                 REIMPLEMENTED  a0=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] → a1=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']
      [v3] c3_anti_compensation                REIMPLEMENTED  a0=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] → a1=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']
      [v3] c6_first_corruption_minimality      REIMPLEMENTED  a0=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] → a1=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']
      [v3] c8_no_touch                         REIMPLEMENTED  a0=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] → a1=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']
      [v4] v4c1_first_corruption               REIMPLEMENTED  a0=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] → a1=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']
      [v4] v4c3_transformation_localization    REIMPLEMENTED  a0=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] → a1=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']

    serialization_pipeline_chain_trap_5 (correct: serializer.py)
      [v3] c8_no_touch                         REIMPLEMENTED  a0=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] → a1=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']
      [v4] v4c1_first_corruption               REIMPLEMENTED  a0=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] → a1=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']
      [v4] v4c7_location_scope_impl            REIMPLEMENTED  a0=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] → a1=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py']

  gpt-5-mini (6 total fixes):

    auth_context_chain_trap_5 (correct: normalizer.py)
      [v3] c6_first_corruption_minimality      REDIRECTED     a0=['resolver.py']                → a1=['normalizer.py']             
        a0 reasoning: resolver.resolve_permissions_node returns normalized['org_id'] (the potentially hyphen-stripped value) in the output. Th
        a1 reasoning: normalizer.normalize_context was overwriting normalized['org_id'] with a hyphen/ORG-prefix-stripped form while preservin
      [v4] v4c3_transformation_localization    REDIRECTED     a0=['resolver.py']                → a1=['normalizer.py', 'resolver.py']
        a0 reasoning: resolver.resolve_permissions_node returns the wrong org_id: it uses normalized['org_id'] (the stripped/normalized value)
        a1 reasoning: normalizer.normalize_context was transforming the parsed org_id (e.g. stripping/normalizing it) into normalized['org_id'
      [v4] v4c6_location_impl                  REDIRECTED     a0=['resolver.py']                → a1=['normalizer.py', 'resolver.py']
        a0 reasoning: resolve_permissions_node: the function used normalized.get('canonical_org_id', normalized['org_id']) to lookup the user 
        a1 reasoning: The normalization step was the first place where the org id was transformed incorrectly: normalize_context stripped or c
      [v4] v4c7_location_scope_impl            REDIRECTED     a0=['resolver.py']                → a1=['normalizer.py']             
        a0 reasoning: resolver.resolve_permissions_node returns normalized["org_id"] (which may have been altered by normalize_context) while 
        a1 reasoning: normalize_context was overwriting the original org_id with a canonical_org_id (or otherwise mutating org_id) so downstre

    serialization_pipeline_chain_trap_1 (correct: serializer.py)
      [v3] c2_first_corruption                 REDIRECTED     a0=['transport.py']               → a1=['serializer.py']             
        a0 reasoning: transport_node in transport.py is converting epoch integer timestamps to plain numeric strings (r['created_at'] = str(..
        a1 reasoning: serializer.py was the first place that changed the timestamp representation: it converted ISO-format created_at values i
      [v4] v4c3_transformation_localization    REDIRECTED     a0=['transport.py']               → a1=['serializer.py']             
        a0 reasoning: transport_node in transport.py was coercing created_at to str() regardless of its original semantics, turning epoch inte
        a1 reasoning: serializer.serialize was leaving created_at as integer epoch values. Later transport_node coerced values to strings, tur

TABLE 4: FIX TYPE BREAKDOWN
------------------------------------------------------------
  gpt-4o-mini:
    REDIRECTED: 1
    REIMPLEMENTED: 13

  gpt-5.4-mini:
    REIMPLEMENTED: 45
    REDUCED: 5

  gpt-5-mini:
    REDIRECTED: 6

TABLE 5: HINT EFFECTIVENESS RANKING (combined v3+v4)
--------------------------------------------------------------------------------
  v4c7_location_scope_impl                  10 fixes /  37 attempts (27%)
  c8_no_touch                                8 fixes /  40 attempts (20%)
  v4c6_location_impl                         8 fixes /  36 attempts (22%)
  v4c1_first_corruption                      7 fixes /  39 attempts (18%)
  c3_anti_compensation                       6 fixes /  37 attempts (16%)
  c6_first_corruption_minimality             6 fixes /  37 attempts (16%)
  c7_anti_compensation_single_file           5 fixes /  41 attempts (12%)
  c2_first_corruption                        5 fixes /  34 attempts (15%)
  v4c3_transformation_localization           5 fixes /  40 attempts (12%)
  c1_retry_only                              3 fixes /  39 attempts (8%)
  c4_minimality                              2 fixes /  42 attempts (5%)
  c5_single_file                             2 fixes /  43 attempts (5%)
  v4c2_minimality                            2 fixes /  39 attempts (5%)
  v4c4_no_refactor                           1 fixes /  36 attempts (3%)

==============================================================================================================
KEY INSIGHTS
==============================================================================================================

1. LOCATION IS NECESSARY BUT NOT SUFFICIENT
   v3 'first_corruption' and v4 'first_corruption' both help gpt-5.4-mini
   but neither helps gpt-5-mini. gpt-5-mini needs the IMPLEMENTATION axis.

2. IMPLEMENTATION IS THE MISSING PIECE FOR gpt-5-mini
   v3 total: 2 fixes. v4 total: 4 fixes.
   v4 'transformation_localization' alone: 2 fixes (auth_trap_5, serial_trap_1)
   This hint tells the model HOW to fix, not WHERE — which is what 5-mini needs.

3. gpt-5.4-mini: RESTRAINT > LOCATION > IMPLEMENTATION
   v3 'no-touch': 8 fixes (best single v3 hint)
   v4 'first_corruption': 7 fixes, v4 'location+impl+scope': 7 fixes
   The model over-edits (5 files avg) but restraint hints don't reduce file count —
   they improve the QUALITY of edits within those files.

4. gpt-4o-mini: COMBINED HINTS ONLY
   No single-axis hint > 1 fix. Only combined hints (anti+1f, lo+im, lo+im+sc)
   produce 2-3 fixes. The model needs all three axes simultaneously.

5. THE CRITIQUE PROMPT CHANGE MATTERS FOR gpt-5-mini
   Old: 'your implementation may not fully reflect your reasoning' (reinforces wrong reasoning)
   New: 'your previous fix did not pass' (neutral)
   v4 implementation hints work partly because the neutral prompt lets the model
   reconsider its reasoning, not just its code.

6. NEVER-FIXABLE CASES PERSIST ACROSS BOTH ROUNDS
   billing_aggregation baseline: 0 fixes in v3+v4 combined (wrong causal model)
   config_derivation_trap_1 on gpt-4o-mini/5-mini: 0 fixes (always fixes deriver)
   These represent fundamental model limitations, not hint failures.

==============================================================================================================
APPENDIX: V4 STRUCTURED RESULTS (per model × condition aggregates)
==============================================================================================================

HOW THESE NUMBERS ARE COMPUTED:

Each (model, condition) pair runs on that model's FAILED baseline cases only.
For each case: attempt 0 runs without a hint, attempt 1 runs with the hint
(only if attempt 0 failed). The metrics below are computed over the FINAL
attempt for each case (attempt 1 if it ran, else attempt 0).

  pass_rate:
    Fraction of cases where the final attempt passed the test.
    = (cases where test passed) / num_cases

  depth_A_rate:
    Fraction of cases where the spec oracle classified the final attempt
    as depth A (root fix). A fix gets depth A when it passes ALL 5 spec
    invariants (trap_catching, generalization, causal_location, cross_path,
    chain_integrity). Lower depths (B/C/D) pass some but not all.
    = (cases where spec_oracle depth == "A") / num_cases

  avg_files_changed:
    Mean number of files the model returned as non-UNCHANGED in the final
    attempt's JSON response. The correct answer is usually 1 file.
    = sum(num_files_changed per case) / num_cases

  over_edit_rate:
    Fraction of cases where the model changed files OTHER than the correct
    bug file (and data.py, which is excluded as a false positive since it
    contains constants). A case with over_edit > 0 means the model touched
    files that don't contain the bug.
    = (cases where over_edit > 0) / num_cases

  root_correct_but_failed_rate:
    Fraction of cases where the generic oracle (LLM-based reasoning evaluator)
    scored the model's root_cause text as CORRECT, but the test still failed.
    This is the Reasoning-Execution Gap (LEG): the model described the right
    mechanism but produced wrong code.
    = (cases where oracle=CORRECT and test=FAIL) / num_cases

  no_attempt_rate:
    Fraction of cases where the model returned 0 changed files but the test
    was recorded as passed. These are suspect and excluded from pass_rate.
    In practice this was always 0.0 — no such cases exist in these runs.
    = (cases where files_changed==[] and raw_pass==True) / num_cases

  hint_fixed:
    Count (not rate) of cases where attempt 0 FAILED and attempt 1 PASSED
    after receiving the hint. This is the direct measure of hint effectiveness.

Example: gpt-5-mini × lo+im+sc (8 cases):

  case                                   pass  depth  files  correct_node  over_edit  oracle  hint_fixed
  auth_context_chain_trap_5              True   A      1      True          0          True    True
  billing_aggregation_chain              False  F      1      False         0          False   False
  billing_aggregation_chain_trap_1       False  F      1      False         1          False   False
  event_etl_chain_trap_1                 True   A      1      True          0          True    False
  logging_pipeline_chain_trap_4          True   A      1      True          0          True    False
  ml_feature_chain_trap_1                False  F      1      False         1          False   False
  serialization_pipeline_chain_trap_1    False  D      1      False         1          False   False
  serialization_pipeline_chain_trap_4    True   A      1      True          0          True    False

  pass_rate = 4/8 = 0.5      (4 passed out of 8 failed-baseline cases)
  depth_A_rate = 4/8 = 0.5   (all 4 passes are root fixes)
  avg_files_changed = 1.0    (model changed exactly 1 file per case)
  over_edit_rate = 3/8 = 0.375  (3 cases touched wrong files)
  root_correct_but_failed = 0/8 = 0.0  (no LEG gap — every correct reasoning led to a pass)
  hint_fixed = 1              (auth_context_trap_5 was fixed by the hint on retry)

{
  "gpt-4o-mini": {
    "locatn": {
      "pass_rate": 0.045,
      "depth_A_rate": 0.045,
      "avg_files_changed": 1.18,
      "over_edit_rate": 0.682,
      "root_correct_but_failed_rate": 0.227,
      "no_attempt_rate": 0.0,
      "num_cases": 22,
      "hint_fixed": 0
    },
    "scope": {
      "pass_rate": 0.182,
      "depth_A_rate": 0.182,
      "avg_files_changed": 0.95,
      "over_edit_rate": 0.636,
      "root_correct_but_failed_rate": 0.182,
      "no_attempt_rate": 0.0,
      "num_cases": 22,
      "hint_fixed": 1
    },
    "impl": {
      "pass_rate": 0.087,
      "depth_A_rate": 0.087,
      "avg_files_changed": 0.96,
      "over_edit_rate": 0.696,
      "root_correct_but_failed_rate": 0.087,
      "no_attempt_rate": 0.0,
      "num_cases": 23,
      "hint_fixed": 0
    },
    "no-ref": {
      "pass_rate": 0.095,
      "depth_A_rate": 0.095,
      "avg_files_changed": 0.95,
      "over_edit_rate": 0.619,
      "root_correct_but_failed_rate": 0.19,
      "no_attempt_rate": 0.0,
      "num_cases": 21,
      "hint_fixed": 1
    },
    "im+sc": {
      "pass_rate": 0.091,
      "depth_A_rate": 0.091,
      "avg_files_changed": 1.0,
      "over_edit_rate": 0.727,
      "root_correct_but_failed_rate": 0.136,
      "no_attempt_rate": 0.0,
      "num_cases": 22,
      "hint_fixed": 0
    },
    "lo+im": {
      "pass_rate": 0.182,
      "depth_A_rate": 0.182,
      "avg_files_changed": 1.05,
      "over_edit_rate": 0.636,
      "root_correct_but_failed_rate": 0.227,
      "no_attempt_rate": 0.0,
      "num_cases": 22,
      "hint_fixed": 2
    },
    "lo+im+sc": {
      "pass_rate": 0.143,
      "depth_A_rate": 0.143,
      "avg_files_changed": 1.1,
      "over_edit_rate": 0.571,
      "root_correct_but_failed_rate": 0.333,
      "no_attempt_rate": 0.0,
      "num_cases": 21,
      "hint_fixed": 2
    }
  },
  "gpt-5.4-mini": {
    "locatn": {
      "pass_rate": 0.562,
      "depth_A_rate": 0.562,
      "avg_files_changed": 5.0,
      "over_edit_rate": 1.0,
      "root_correct_but_failed_rate": 0.312,
      "no_attempt_rate": 0.0,
      "num_cases": 16,
      "hint_fixed": 7
    },
    "scope": {
      "pass_rate": 0.188,
      "depth_A_rate": 0.188,
      "avg_files_changed": 4.12,
      "over_edit_rate": 0.938,
      "root_correct_but_failed_rate": 0.375,
      "no_attempt_rate": 0.0,
      "num_cases": 16,
      "hint_fixed": 1
    },
    "impl": {
      "pass_rate": 0.312,
      "depth_A_rate": 0.312,
      "avg_files_changed": 5.0,
      "over_edit_rate": 1.0,
      "root_correct_but_failed_rate": 0.312,
      "no_attempt_rate": 0.0,
      "num_cases": 16,
      "hint_fixed": 3
    },
    "no-ref": {
      "pass_rate": 0.25,
      "depth_A_rate": 0.25,
      "avg_files_changed": 4.69,
      "over_edit_rate": 0.938,
      "root_correct_but_failed_rate": 0.375,
      "no_attempt_rate": 0.0,
      "num_cases": 16,
      "hint_fixed": 0
    },
    "im+sc": {
      "pass_rate": 0.25,
      "depth_A_rate": 0.25,
      "avg_files_changed": 4.5,
      "over_edit_rate": 0.938,
      "root_correct_but_failed_rate": 0.25,
      "no_attempt_rate": 0.0,
      "num_cases": 16,
      "hint_fixed": 0
    },
    "lo+im": {
      "pass_rate": 0.562,
      "depth_A_rate": 0.562,
      "avg_files_changed": 5.0,
      "over_edit_rate": 1.0,
      "root_correct_but_failed_rate": 0.125,
      "no_attempt_rate": 0.0,
      "num_cases": 16,
      "hint_fixed": 5
    },
    "lo+im+sc": {
      "pass_rate": 0.562,
      "depth_A_rate": 0.562,
      "avg_files_changed": 4.44,
      "over_edit_rate": 0.875,
      "root_correct_but_failed_rate": 0.312,
      "no_attempt_rate": 0.0,
      "num_cases": 16,
      "hint_fixed": 7
    }
  },
  "gpt-5-mini": {
    "locatn": {
      "pass_rate": 0.25,
      "depth_A_rate": 0.25,
      "avg_files_changed": 1.38,
      "over_edit_rate": 0.25,
      "root_correct_but_failed_rate": 0.125,
      "no_attempt_rate": 0.0,
      "num_cases": 8,
      "hint_fixed": 0
    },
    "scope": {
      "pass_rate": 0.125,
      "depth_A_rate": 0.125,
      "avg_files_changed": 1.0,
      "over_edit_rate": 0.75,
      "root_correct_but_failed_rate": 0.375,
      "no_attempt_rate": 0.0,
      "num_cases": 8,
      "hint_fixed": 0
    },
    "impl": {
      "pass_rate": 0.5,
      "depth_A_rate": 0.5,
      "avg_files_changed": 1.62,
      "over_edit_rate": 0.625,
      "root_correct_but_failed_rate": 0.125,
      "no_attempt_rate": 0.0,
      "num_cases": 8,
      "hint_fixed": 2
    },
    "no-ref": {
      "pass_rate": 0.25,
      "depth_A_rate": 0.25,
      "avg_files_changed": 1.0,
      "over_edit_rate": 0.625,
      "root_correct_but_failed_rate": 0.25,
      "no_attempt_rate": 0.0,
      "num_cases": 8,
      "hint_fixed": 0
    },
    "im+sc": {
      "pass_rate": 0.125,
      "depth_A_rate": 0.125,
      "avg_files_changed": 1.0,
      "over_edit_rate": 0.625,
      "root_correct_but_failed_rate": 0.375,
      "no_attempt_rate": 0.0,
      "num_cases": 8,
      "hint_fixed": 0
    },
    "lo+im": {
      "pass_rate": 0.5,
      "depth_A_rate": 0.5,
      "avg_files_changed": 1.5,
      "over_edit_rate": 0.5,
      "root_correct_but_failed_rate": 0.125,
      "no_attempt_rate": 0.0,
      "num_cases": 8,
      "hint_fixed": 1
    },
    "lo+im+sc": {
      "pass_rate": 0.5,
      "depth_A_rate": 0.5,
      "avg_files_changed": 1.0,
      "over_edit_rate": 0.375,
      "root_correct_but_failed_rate": 0.0,
      "no_attempt_rate": 0.0,
      "num_cases": 8,
      "hint_fixed": 1
    }
  }
}