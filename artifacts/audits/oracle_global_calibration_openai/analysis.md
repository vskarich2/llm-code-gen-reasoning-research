# Oracle Reasoning Evaluator — Stage 1 Results

**Date**: 2026-04-03
**Total samples**: 5711
**Evaluated**: 5671
**Coverage**: 99.3%

## 1. Label Distribution

| Label | Count | Rate |
|-------|-------|------|
| CORRECT | 4980 | 87.2% |
| PARTIAL | 298 | 5.2% |
| WRONG | 393 | 6.9% |
| UNJUDGABLE | 40 | 0.7% |

## 2. TRUE LEG Metrics

- **Strict LEG**: 8.8%
- **Soft LEG**: 11.5%
- **Lucky fix**: 3.1%

## 3. Calibration

- Old mc=True rate: 99.8%
- New CORRECT rate: 87.8%
- **Delta**: 12.0%

## 4. Per-Model Breakdown

| Model | N | CORRECT | LEG_strict | Lucky |
|-------|---|---------|------------|-------|
| gpt-4.1-nano | 1250 | 84.7% | 9.9% | 2.2% |
| gpt-4o-mini | 1291 | 87.5% | 22.7% | 2.1% |
| gpt-5 | 150 | 64.0% | 0.0% | 0.0% |
| gpt-5-mini | 1575 | 87.7% | 3.5% | 4.3% |
| gpt-5.4-mini | 1405 | 93.5% | 1.8% | 3.9% |

## 5. Sample Results

| Case | Model | Cond | Truth | Pass | LEG? | Justification |
|------|-------|------|-------|------|------|---------------|
| alias_config_a | gpt-4o-mini | retry_ba | CORRECT | P |  | The developer correctly pinpoints config.py::create_config r |
| commit_gate | gpt-4o-mini | retry_ba | PARTIAL | P |  | The developer correctly points to the removed commit() in pi |
| silent_default_a | gpt-4o-mini | retry_le | CORRECT | P |  | The developer correctly pins flags.py::is_enabled as the cul |
| lazy_init_a | gpt-4o-mini | retry_re | CORRECT | P |  | The developer correctly identifies that _default_host was ea |
| alias_config_a | gpt-5.4-mini | retry_ba | CORRECT | P |  | The developer correctly identifies the root cause (create_co |
| commit_gate | gpt-5.4-mini | retry_le | CORRECT | P |  | Developer correctly identifies that pipeline.py::process_bat |
| partial_update_b | gpt-5.4-mini | retry_le | CORRECT | P |  | The developer correctly pinpoints profile.py::update_profile |
| lazy_init_b | gpt-5.4-mini | retry_re | CORRECT | P |  | The developer correctly identifies that client.py eagerly ca |
| mutable_default_a | gpt-5-mini | retry_ba | CORRECT | P |  | The developer correctly identifies the mutable-default accum |
| use_before_set_b | gpt-5-mini | retry_ba | CORRECT | P |  | The developer correctly pins the root cause to loader.load ( |
| false_fix_deadlock | gpt-5-mini | retry_ba | CORRECT | F | LEG | The developer correctly pinpoints resources.py::make_transfe |
| index_misalign_c | gpt-5-mini | retry_re | CORRECT | P |  | Developer correctly identifies report.py::insert_column as u |
| use_before_set_b | gpt-5-mini | retry_re | CORRECT | P |  | The developer correctly identifies loader.load as the root c |
| index_misalign_a | gpt-4.1-nano | retry_ba | CORRECT | P |  | The developer correctly identifies the oracle's mechanism in |
| wrong_condition_b | gpt-4.1-nano | retry_le | CORRECT | P |  | Developer correctly identifies that policy.py::is_allowed us |
| early_return_c | gpt-4.1-nano | retry_re | CORRECT | P |  | The developer correctly identifies payment.py::charge early- |
| alias_config_b | gpt-4.1-nano | retry_re | CORRECT | P |  | The developer correctly identifies config.py::create_config  |
| alias_config_b | gpt-4o-mini | retry_ba | CORRECT | F | LEG | Developer correctly identifies config.py::create_config retu |
| overdetermination | gpt-4o-mini | retry_ba | CORRECT | F | LEG | The developer correctly identifies api.py::update_product ca |
| feature_flag_drift | gpt-4o-mini | retry_le | CORRECT | F | LEG | The developer correctly identifies that api.py::checkout fai |
| lazy_init_b | gpt-4o-mini | retry_re | CORRECT | P |  | The developer correctly pinpoints client.py's _client_config |
| partial_update_a | gpt-5.4-mini | retry_ba | CORRECT | P |  | The developer correctly identifies the root cause (profile.u |
| overdetermination | gpt-5.4-mini | retry_le | CORRECT | P |  | The developer correctly pinpoints api.update_product as call |
| partial_update_c | gpt-5.4-mini | retry_le | CORRECT | P |  | The developer correctly identifies profile.update_profile's  |
| lazy_init_c | gpt-5.4-mini | retry_re | CORRECT | P |  | The developer correctly identifies the eager capture in clie |
| use_before_set_a | gpt-5-mini | retry_ba | PARTIAL | P |  | The developer correctly locates the conditional-only assignm |
| early_return_a | gpt-5-mini | retry_ba | CORRECT | P |  | The developer correctly points to payment.py::process_paymen |
| ordering_dependenc | gpt-5-mini | retry_ba | CORRECT | P |  | The developer correctly pinpoints pipeline.py::process as th |
| lost_update | gpt-5-mini | retry_re | CORRECT | P |  | The developer correctly locates the non-atomic read-modify-w |
| l3_state_pipeline | gpt-5-mini | retry_re | CORRECT | P |  | The developer correctly identifies that removing commit() an |
| stale_cache_c | gpt-4.1-nano | retry_ba | CORRECT | P |  | The developer correctly identifies catalog.py::update_produc |
| invariant_partial_ | gpt-4.1-nano | retry_le | PARTIAL | F |  | The developer correctly points to transfer_service.execute_t |
| index_misalign_a | gpt-4.1-nano | retry_re | CORRECT | P |  | The developer exactly identifies the oracle mechanism in rep |
| alias_config_c | gpt-4.1-nano | retry_re | CORRECT | P |  | The developer correctly identifies that config.py::create_co |
| alias_config_c | gpt-4o-mini | retry_ba | CORRECT | P |  | The developer correctly identifies config.py::create_config  |
| use_before_set_c | gpt-4o-mini | retry_ba | CORRECT | P |  | The developer correctly pinpoints pipeline.py::find_best as  |
| commit_gate | gpt-4o-mini | retry_le | PARTIAL | P |  | The developer correctly points to pipeline.py::process_batch |
| mutable_default_a | gpt-4o-mini | retry_re | CORRECT | P |  | The developer correctly identifies the oracle's mechanism: e |
| lazy_init_a | gpt-5.4-mini | retry_ba | CORRECT | P |  | The developer correctly identifies the eager capture of _def |
| ordering_dependenc | gpt-5.4-mini | retry_le | CORRECT | P |  | The developer correctly identifies pipeline.py::process as c |
| stale_cache_a | gpt-5.4-mini | retry_le | CORRECT | P |  | The developer correctly identifies catalog.py::update_produc |
| mutable_default_a | gpt-5.4-mini | retry_re | CORRECT | P |  | The developer explicitly identifies queue.py::enqueue's muta |
| early_return_a | gpt-5-mini | retry_ba | CORRECT | P |  | The developer correctly identifies the root cause (the early |
| alias_config_a | gpt-5-mini | retry_le | CORRECT | P |  | The developer correctly identifies the root cause (config =  |
| silent_default_c | gpt-5-mini | retry_le | PARTIAL | P |  | The developer correctly identifies the env key name typo in  |
| ordering_dependenc | gpt-5-mini | retry_re | CORRECT | P |  | The developer correctly identifies pipeline.py::process drop |
| commit_gate | gpt-5-mini | retry_re | CORRECT | P |  | The developer explicitly identifies the removed commit() and |
| stale_cache_c | gpt-4.1-nano | retry_ba | CORRECT | P |  | Developer correctly identifies catalog.py::update_product as |
| partial_rollback_b | gpt-4.1-nano | retry_le | CORRECT | P |  | The developer correctly identifies order_service.py::place_o |
| index_misalign_b | gpt-4.1-nano | retry_re | CORRECT | P |  | The developer correctly identifies that report.py's delete_c |