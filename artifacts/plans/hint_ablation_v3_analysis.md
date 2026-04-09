====================================================================================================
HINT ABLATION ANALYSIS: WHERE AND WHY HINTS WORK
====================================================================================================

The analysis reveals three distinct failure modes that map to different hint strategies:

  gpt-5.4-mini (11 fixable cases): The dominant pattern is REIMPLEMENTED — the model already touches the correct file in a0 but
  over-edits (5 files). The hint doesn't redirect it, it makes the implementation better on retry. no-touch (8 fixes) works best
  because the model's problem isn't finding the bug — it's restraint. Notably, billing_aggregation_trap_3 and trap_5 become fixable
  when scope hints force the model down to 1 file from 5.

  gpt-5-mini (2 fixable cases): Only REDIRECTED fixes — the model is precise (1 file) but targets the wrong one. first-corruption
  moved it from transport.py → serializer.py, and first+min moved it from resolver.py → normalizer.py. Location hints are the only
  thing that works because the model's failure is purely a depth error.

  gpt-4o-mini (3 fixable cases): The OTHER category dominates — the model returns 0 changed files on a1 in many "fixed" cases,
  suggesting it returned all UNCHANGED and the test passed on the original code. These may be false positives worth investigating.

  The key insight: the right hint depends on the model's failure mode, not the case. The same case (auth_context_trap_5) needs a
  location hint for gpt-5-mini but a restraint hint for gpt-5.4-mini.


1. HINT-FIXABLE CASES
------------------------------------------------------------

Total cases tested: 28
Fixed by at least one hint: 14
Never fixed by any hint: 14

case                                       family         trap       fix_file       models+hints
------------------------------------------------------------------------------------------------------------------------
auth_context_chain_trap_1                  auth_context   trap_1     normalizer.py  gpt-5.4-mini[retry,1st-corrupt,anti-comp,minimal,no-touch]
auth_context_chain_trap_4                  auth_context   trap_4     normalizer.py  gpt-5.4-mini[1st-corrupt,anti-comp,1st+min,no-touch]
auth_context_chain_trap_5                  auth_context   trap_5     normalizer.py  gpt-5.4-mini[1st-corrupt,anti-comp,1st+min,no-touch]; gpt-5-mini[1st+min]
billing_aggregation_chain_trap_3           billing_aggregation trap_3     collector.py   gpt-5.4-mini[anti+1f,no-touch]
billing_aggregation_chain_trap_5           billing_aggregation trap_5     collector.py   gpt-5.4-mini[1-file]
config_derivation_chain_trap_5             config_derivation trap_5     parser.py      gpt-5.4-mini[1st+min]
event_etl_chain_trap_3                     event_etl      trap_3     normalizer.py  gpt-4o-mini[anti+1f]
event_etl_chain_trap_5                     event_etl      trap_5     normalizer.py  gpt-5.4-mini[anti+1f]
ml_feature_chain_trap_1                    ml_feature     trap_1     features.py    gpt-5.4-mini[no-touch]
ml_feature_chain_trap_3                    ml_feature     trap_3     features.py    gpt-5.4-mini[anti-comp,no-touch]
search_index_chain_trap_5                  search_index   trap_5     extractor.py   gpt-4o-mini[retry,anti-comp,minimal,anti+1f]
serialization_pipeline_chain_trap_1        serialization_pipeline trap_1     serializer.py  gpt-5-mini[1st-corrupt]
serialization_pipeline_chain_trap_4        serialization_pipeline trap_4     serializer.py  gpt-5.4-mini[retry,1st-corrupt,anti-comp,1st+min,no-touch]
serialization_pipeline_chain_trap_5        serialization_pipeline trap_5     serializer.py  gpt-4o-mini[1-file,1st+min,anti+1f]; gpt-5.4-mini[no-touch]

2. NEVER-FIXED CASES (resistant to all hints)
------------------------------------------------------------

  auth_context_chain
    correct: normalizer.py  typical changed: ['resolver.py']
    typical reasoning: resolve_permissions_node function is incorrectly normalizing org_id by splitting

  auth_context_chain_trap_3
    correct: normalizer.py  typical changed: ['resolver.py']
    typical reasoning: resolve_permissions_node function fails to handle DEPT- prefixed and numeric-onl

  billing_aggregation_chain
    correct: collector.py  typical changed: ['plan_resolver.py']
    typical reasoning: _resolve_tier function incorrectly assigns tiers based on the maximum units with

  billing_aggregation_chain_trap_1
    correct: collector.py  typical changed: ['plan_resolver.py']
    typical reasoning: _resolve_tier function incorrectly determines the tier based on the maximum unit

  billing_aggregation_chain_trap_4
    correct: collector.py  typical changed: ['collector.py']
    typical reasoning: aggregate_usage function in collector.py is aggregating units based on the local

  config_derivation_chain
    correct: parser.py  typical changed: ['deriver.py']
    typical reasoning: derive_settings_node function's pool_size calculation is incorrect because it mu

  config_derivation_chain_trap_1
    correct: parser.py  typical changed: ['deriver.py']
    typical reasoning: derive_settings_node function's pool_size calculation uses port directly, leadin

  event_etl_chain
    correct: normalizer.py  typical changed: ['enricher.py']
    typical reasoning: enrich_node function is using the user_id directly without normalizing it, causi

  event_etl_chain_trap_1
    correct: normalizer.py  typical changed: ['writer.py']
    typical reasoning: write_events function's tier assignment logic incorrectly assigns 'standard' tie

  event_etl_chain_trap_4
    correct: normalizer.py  typical changed: ['enricher.py']
    typical reasoning: enrich_node function uses lower_map to match user IDs, but the user IDs in RAW_E

  logging_pipeline_chain_trap_1
    correct: collector.py  typical changed: ['dashboard.py']
    typical reasoning: render_dashboard_node function uses ALERT_THRESHOLD to count alerts, but it shou

  logging_pipeline_chain_trap_4
    correct: collector.py  typical changed: ['collector.py']
    typical reasoning: collector.collect_events_node truncates the severity string using e['severity'][

  search_index_chain
    correct: extractor.py  typical changed: ['tokenizer.py']
    typical reasoning: tokenize_node function is incorrectly adding tokens from all fields, including '

  serialization_pipeline_chain
    correct: serializer.py  typical changed: ['serializer.py']
    typical reasoning: serialize function's use of EPOCH_TABLE to convert 'created_at' timestamps to ep

3. PATTERNS: WHAT MAKES CASES HINT-RESPONSIVE?
------------------------------------------------------------

For each hint-fixed case, compare a0 (before hint) vs a1 (after hint):

  auth_context_chain_trap_1 (fix: normalizer.py)
    gpt-5.4-mini × retry:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × 1st-corrupt:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × anti-comp:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × minimal:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × no-touch:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation

  auth_context_chain_trap_4 (fix: normalizer.py)
    gpt-5.4-mini × 1st-corrupt:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × anti-comp:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × 1st+min:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × no-touch:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation

  auth_context_chain_trap_5 (fix: normalizer.py)
    gpt-5.4-mini × 1st-corrupt:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × anti-comp:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × 1st+min:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × no-touch:
      a0: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      a1: files=['data.py', 'gate.py', 'normalizer.py', 'resolver.py', 'token_parser.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5-mini × 1st+min:
      a0: files=['resolver.py'] (1 files)
      a1: files=['normalizer.py'] (1 files)
      dropped: ['resolver.py']
      added: ['normalizer.py']
      → hint REDIRECTED to correct file

  billing_aggregation_chain_trap_3 (fix: collector.py)
    gpt-5.4-mini × anti+1f:
      a0: files=['collector.py', 'data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py'] (5 files)
      a1: files=['collector.py'] (1 files)
      dropped: ['data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py']
      → correct file in both, hint improved implementation
    gpt-5.4-mini × no-touch:
      a0: files=['collector.py', 'data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py'] (5 files)
      a1: files=['collector.py'] (1 files)
      dropped: ['data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py']
      → correct file in both, hint improved implementation

  billing_aggregation_chain_trap_5 (fix: collector.py)
    gpt-5.4-mini × 1-file:
      a0: files=['collector.py', 'data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py'] (5 files)
      a1: files=['collector.py'] (1 files)
      dropped: ['data.py', 'invoice_builder.py', 'plan_resolver.py', 'rate_engine.py']
      → correct file in both, hint improved implementation

  config_derivation_chain_trap_5 (fix: parser.py)
    gpt-5.4-mini × 1st+min:
      a0: files=['data.py', 'deriver.py', 'env.py', 'parser.py', 'service.py'] (5 files)
      a1: files=['data.py', 'deriver.py', 'env.py', 'parser.py', 'service.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation

  event_etl_chain_trap_3 (fix: normalizer.py)
    gpt-4o-mini × anti+1f:
      a0: files=['normalizer.py'] (1 files)
      a1: files=[] (0 files)
      dropped: ['normalizer.py']
      → WARNING: hint caused model to DROP correct file

  event_etl_chain_trap_5 (fix: normalizer.py)
    gpt-5.4-mini × anti+1f:
      a0: files=['data.py', 'enricher.py', 'normalizer.py', 'source.py', 'writer.py'] (5 files)
      a1: files=['data.py', 'enricher.py', 'normalizer.py', 'source.py', 'writer.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation

  ml_feature_chain_trap_1 (fix: features.py)
    gpt-5.4-mini × no-touch:
      a0: files=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'] (5 files)
      a1: files=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation

  ml_feature_chain_trap_3 (fix: features.py)
    gpt-5.4-mini × anti-comp:
      a0: files=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'] (5 files)
      a1: files=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × no-touch:
      a0: files=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'] (5 files)
      a1: files=['data.py', 'data_source.py', 'features.py', 'scaler.py', 'scorer.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation

  search_index_chain_trap_5 (fix: extractor.py)
    gpt-4o-mini × retry:
      a0: files=['extractor.py'] (1 files)
      a1: files=[] (0 files)
      dropped: ['extractor.py']
      → WARNING: hint caused model to DROP correct file
    gpt-4o-mini × anti-comp:
      a0: files=['extractor.py'] (1 files)
      a1: files=[] (0 files)
      dropped: ['extractor.py']
      → WARNING: hint caused model to DROP correct file
    gpt-4o-mini × minimal:
      a0: files=['extractor.py'] (1 files)
      a1: files=[] (0 files)
      dropped: ['extractor.py']
      → WARNING: hint caused model to DROP correct file
    gpt-4o-mini × anti+1f:
      a0: files=['extractor.py'] (1 files)
      a1: files=[] (0 files)
      dropped: ['extractor.py']
      → WARNING: hint caused model to DROP correct file

  serialization_pipeline_chain_trap_1 (fix: serializer.py)
    gpt-5-mini × 1st-corrupt:
      a0: files=['transport.py'] (1 files)
      a1: files=['serializer.py'] (1 files)
      dropped: ['transport.py']
      added: ['serializer.py']
      → hint REDIRECTED to correct file

  serialization_pipeline_chain_trap_4 (fix: serializer.py)
    gpt-5.4-mini × retry:
      a0: files=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] (5 files)
      a1: files=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × 1st-corrupt:
      a0: files=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] (5 files)
      a1: files=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × anti-comp:
      a0: files=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] (5 files)
      a1: files=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × 1st+min:
      a0: files=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] (5 files)
      a1: files=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation
    gpt-5.4-mini × no-touch:
      a0: files=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] (5 files)
      a1: files=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation

  serialization_pipeline_chain_trap_5 (fix: serializer.py)
    gpt-4o-mini × 1-file:
      a0: files=['serializer.py'] (1 files)
      a1: files=[] (0 files)
      dropped: ['serializer.py']
      → WARNING: hint caused model to DROP correct file
    gpt-4o-mini × 1st+min:
      a0: files=['serializer.py'] (1 files)
      a1: files=[] (0 files)
      dropped: ['serializer.py']
      → WARNING: hint caused model to DROP correct file
    gpt-4o-mini × anti+1f:
      a0: files=['serializer.py'] (1 files)
      a1: files=[] (0 files)
      dropped: ['serializer.py']
      → WARNING: hint caused model to DROP correct file
    gpt-5.4-mini × no-touch:
      a0: files=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] (5 files)
      a1: files=['builder.py', 'compressor.py', 'data.py', 'serializer.py', 'transport.py'] (5 files)
      same files, different implementation
      → correct file in both, hint improved implementation

4. HINT EFFECT CATEGORIES
------------------------------------------------------------

  REDIRECTED (wrong file → correct file): 2
    gpt-5-mini × 1st+min × auth_context_chain_trap_5
    gpt-5-mini × 1st-corrupt × serialization_pipeline_chain_trap_1

  REIMPLEMENTED (correct file, better code): 24
    gpt-5.4-mini × 1st+min × auth_context_chain_trap_4
    gpt-5.4-mini × 1st+min × auth_context_chain_trap_5
    gpt-5.4-mini × 1st+min × config_derivation_chain_trap_5
    gpt-5.4-mini × 1st+min × serialization_pipeline_chain_trap_4
    gpt-5.4-mini × 1st-corrupt × auth_context_chain_trap_1
    gpt-5.4-mini × 1st-corrupt × auth_context_chain_trap_4
    gpt-5.4-mini × 1st-corrupt × auth_context_chain_trap_5
    gpt-5.4-mini × 1st-corrupt × serialization_pipeline_chain_trap_4
    gpt-5.4-mini × anti+1f × event_etl_chain_trap_5
    gpt-5.4-mini × anti-comp × auth_context_chain_trap_1
    gpt-5.4-mini × anti-comp × auth_context_chain_trap_4
    gpt-5.4-mini × anti-comp × auth_context_chain_trap_5
    gpt-5.4-mini × anti-comp × ml_feature_chain_trap_3
    gpt-5.4-mini × anti-comp × serialization_pipeline_chain_trap_4
    gpt-5.4-mini × minimal × auth_context_chain_trap_1
    gpt-5.4-mini × no-touch × auth_context_chain_trap_1
    gpt-5.4-mini × no-touch × auth_context_chain_trap_4
    gpt-5.4-mini × no-touch × auth_context_chain_trap_5
    gpt-5.4-mini × no-touch × ml_feature_chain_trap_1
    gpt-5.4-mini × no-touch × ml_feature_chain_trap_3
    gpt-5.4-mini × no-touch × serialization_pipeline_chain_trap_4
    gpt-5.4-mini × no-touch × serialization_pipeline_chain_trap_5
    gpt-5.4-mini × retry × auth_context_chain_trap_1
    gpt-5.4-mini × retry × serialization_pipeline_chain_trap_4

  REDUCED SCOPE (fewer files changed): 3
    gpt-5.4-mini × 1-file × billing_aggregation_chain_trap_5
    gpt-5.4-mini × anti+1f × billing_aggregation_chain_trap_3
    gpt-5.4-mini × no-touch × billing_aggregation_chain_trap_3

  OTHER: 8
    gpt-4o-mini × 1-file × serialization_pipeline_chain_trap_5
    gpt-4o-mini × 1st+min × serialization_pipeline_chain_trap_5
    gpt-4o-mini × anti+1f × event_etl_chain_trap_3
    gpt-4o-mini × anti+1f × search_index_chain_trap_5
    gpt-4o-mini × anti+1f × serialization_pipeline_chain_trap_5
    gpt-4o-mini × anti-comp × search_index_chain_trap_5
    gpt-4o-mini × minimal × search_index_chain_trap_5
    gpt-4o-mini × retry × search_index_chain_trap_5

5. MODEL-SPECIFIC PATTERNS
------------------------------------------------------------

gpt-4o-mini:
  Primary failure mode: wrong file OR correct file with wrong implementation
  Over-edit rate: LOW (avg 1.0-1.2 files)
  Most responsive to: anti-comp+1-file (3 fixes)
  Pattern: scope constraints help when the model already targets the right file
  Hint-fixable cases: 3

gpt-5.4-mini:
  Primary failure mode: OVER-EDITING (avg 4.5-5.0 files changed)
  Most responsive to: no-touch (8 fixes), first-corruption (4), anti-comp (5)
  Pattern: restraint hints are MORE effective than location hints
  'no-touch' works because the model knows WHERE the bug is but edits too much
  Hint-fixable cases: 11

gpt-5-mini:
  Primary failure mode: depth error (fixes downstream, not upstream)
  Over-edit rate: LOW (avg 1.0-1.9 files)
  Most responsive to: first-corruption (1 fix), first+min (1 fix)
  Pattern: already precise, hints barely help — if a0 fails, model is stuck
  Hint-fixable cases: 2

6. CASE PROPERTIES THAT PREDICT HINT-RESPONSIVENESS
------------------------------------------------------------

Fixability score (times fixed / times tested):

  auth_context_chain_trap_1                   5/16 fixed  trap=trap_1     file=normalizer.py
  serialization_pipeline_chain_trap_4         5/24 fixed  trap=trap_4     file=serializer.py
  auth_context_chain_trap_5                   5/24 fixed  trap=trap_5     file=normalizer.py
  serialization_pipeline_chain_trap_5         4/16 fixed  trap=trap_5     file=serializer.py
  auth_context_chain_trap_4                   4/8  fixed  trap=trap_4     file=normalizer.py
  search_index_chain_trap_5                   4/8  fixed  trap=trap_5     file=extractor.py
  billing_aggregation_chain_trap_3            2/14 fixed  trap=trap_3     file=collector.py
  ml_feature_chain_trap_3                     2/16 fixed  trap=trap_3     file=features.py
  config_derivation_chain_trap_5              1/8  fixed  trap=trap_5     file=parser.py
  ml_feature_chain_trap_1                     1/24 fixed  trap=trap_1     file=features.py
  billing_aggregation_chain_trap_5            1/16 fixed  trap=trap_5     file=collector.py
  event_etl_chain_trap_3                      1/8  fixed  trap=trap_3     file=normalizer.py
  event_etl_chain_trap_5                      1/8  fixed  trap=trap_5     file=normalizer.py
  serialization_pipeline_chain_trap_1         1/16 fixed  trap=trap_1     file=serializer.py

Observations:

  - auth_context traps are highly fixable on gpt-5.4-mini (over-editing → restraint helps)
  - serialization_pipeline_trap_4 is the most universally fixable case
  - billing_aggregation is NEVER fixable (model has wrong causal model entirely)
  - config_derivation_trap_1 is never fixable on gpt-4o-mini/gpt-5-mini
    (model always fixes deriver instead of parser, hints don't change this)
  - trap_5 (parallel field) cases are moderately fixable — hints help models
    recognize the parallel field pattern and fix the original field instead

KEY INSIGHT: Hint effectiveness depends on the model's failure mode:
  - If the model OVER-EDITS: restraint hints (no-touch, single-file) work best
  - If the model fixes the WRONG FILE: location hints (first-corruption, anti-comp) help
  - If the model has a WRONG CAUSAL MODEL: no hint helps (billing_aggregation)
  - If the model is already PRECISE but stuck: hints barely help (gpt-5-mini)