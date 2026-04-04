# Oracle Reasoning Evaluator — Stage 1 Results

**Date**: 2026-04-03
**Total samples**: 2400
**Evaluated**: 2343
**Coverage**: 97.6%

## 1. Label Distribution

| Label | Count | Rate |
|-------|-------|------|
| CORRECT | 1003 | 41.8% |
| PARTIAL | 522 | 21.8% |
| WRONG | 818 | 34.1% |
| UNJUDGABLE | 57 | 2.4% |

## 2. TRUE LEG Metrics

- **Strict LEG**: 31.9%
- **Soft LEG**: 52.5%
- **Lucky fix**: 2.6%

## 3. Calibration

- Old mc=True rate: 98.7%
- New CORRECT rate: 42.8%
- **Delta**: 55.9%

## 4. Per-Model Breakdown

| Model | N | CORRECT | LEG_strict | Lucky |
|-------|---|---------|------------|-------|
| gpt-4.1-nano | 391 | 1.3% | 0.0% | 13.6% |
| gpt-4o-mini | 953 | 41.7% | 33.9% | 0.2% |
| gpt-5-mini | 399 | 97.2% | 77.4% | 0.8% |
| gpt-5.4-mini | 600 | 35.5% | 19.2% | 0.3% |

## 5. Sample Results

| Case | Model | Cond | Truth | Pass | LEG? | Justification |
|------|-------|------|-------|------|------|---------------|
| async_race_lock | gpt-4o-mini | baseline | WRONG | F |  | The developer incorrectly claims the lock in worker.py::proc |
| async_race_lock | gpt-4o-mini | leg_redu | WRONG | F |  | The developer proposes removing the locking by replacing wor |
| async_race_lock | gpt-4o-mini | retry_ba | WRONG | F |  | The developer incorrectly blames process_item’s locking (wor |
| lost_update | gpt-5.4-mini | baseline | CORRECT | F | LEG | The developer pinpoints the bug in make_increment_steps as a |
| invariant_partial_ | gpt-5.4-mini | retry_ba | PARTIAL | F |  | The developer correctly points to execute_transfer and the i |
| false_fix_deadlock | gpt-5-mini | leg_redu | CORRECT | F | LEG | The developer correctly pinpoints resources.py::make_transfe |
| cache_invalidation | gpt-4.1-nano | leg_redu | WRONG | F |  | The developer incorrectly removes cache_invalidate in servic |
| config_shadowing | gpt-4o-mini | baseline | PARTIAL | F |  | The developer blames run_background_job for calling get_defa |
| config_shadowing | gpt-4o-mini | leg_redu | PARTIAL | F |  | They correctly point out run_background_job calls get_defaul |
| config_shadowing | gpt-4o-mini | retry_ba | PARTIAL | F |  | The developer blames run_background_job for calling get_defa |
| async_race_lock | gpt-5.4-mini | baseline | WRONG | F |  | The developer explicitly proposes replacing worker.process_i |
| lost_update | gpt-5.4-mini | retry_ba | CORRECT | P |  | The developer correctly pinpoints the non-atomic read-modify |
| missing_branch_c | gpt-5-mini | leg_redu | CORRECT | F | LEG | The developer correctly identifies that auth.authorize in au |
| l3_state_pipeline | gpt-4.1-nano | leg_redu | WRONG | F |  | The developer incorrectly labels commit() and freeze_view()  |
| early_return_b | gpt-4o-mini | baseline | CORRECT | F | LEG | The developer correctly identifies payment.py::process_payme |
| early_return_b | gpt-4o-mini | leg_redu | CORRECT | F | LEG | Developer correctly identifies payment.py::process_payment e |
| early_return_b | gpt-4o-mini | retry_ba | CORRECT | F | LEG | The developer correctly identifies payment.py::process_payme |
| invariant_partial_ | gpt-5.4-mini | baseline | PARTIAL | F |  | The developer correctly points to transfer_service.execute_t |
| async_race_lock | gpt-5.4-mini | retry_ba | WRONG | F |  | The developer proposes replacing worker.process_item (which  |
| false_fix_deadlock | gpt-5-mini | leg_redu | CORRECT | F | LEG | The developer correctly identifies the bug location (make_tr |
| cache_invalidation | gpt-4.1-nano | leg_redu | WRONG | P | LUCKY | The developer wrongly says cache_invalidate in service.py::u |
| invariant_partial_ | gpt-4o-mini | baseline | PARTIAL | F |  | The developer blames the logging calls (record_transfer_atte |
| invariant_partial_ | gpt-4o-mini | leg_redu | PARTIAL | F |  | The developer blames noisy logging and proposes extracting a |
| invariant_partial_ | gpt-4o-mini | retry_ba | PARTIAL | F |  | The developer blames interleaved logging (record_transfer_at |
| lost_update | gpt-5.4-mini | baseline | CORRECT | F | LEG | The developer correctly identifies counter.py::make_incremen |
| invariant_partial_ | gpt-5.4-mini | retry_ba | PARTIAL | F |  | The developer blames mixing observability with business logi |
| missing_branch_c | gpt-5-mini | leg_redu | CORRECT | F | LEG | The developer correctly pinpoints that auth.authorize in aut |
| l3_state_pipeline | gpt-4.1-nano | leg_redu | WRONG | F |  | The developer incorrectly claims commit() and freeze_view()  |
| use_before_set_b | gpt-4o-mini | baseline | CORRECT | F | LEG | The developer correctly identifies that loader.load fails to |
| use_before_set_b | gpt-4o-mini | leg_redu | CORRECT | F | LEG | The developer correctly pinpoints loader.load as the cause—_ |
| use_before_set_b | gpt-4o-mini | retry_ba | CORRECT | F | LEG | The developer correctly identifies that loader.load fails to |
| async_race_lock | gpt-5.4-mini | baseline | WRONG | F |  | The developer proposes removing the try_lock/unlock locking  |
| lost_update | gpt-5.4-mini | retry_ba | CORRECT | P |  | The developer correctly identifies the non-atomic read-modif |
| false_fix_deadlock | gpt-5-mini | leg_redu | CORRECT | F | LEG | The developer correctly identifies resources.py::make_transf |
| cache_invalidation | gpt-4.1-nano | leg_redu | WRONG | F |  | The developer argues update_record should drop cache_invalid |
| async_race_lock | gpt-4o-mini | baseline | WRONG | F |  | The developer incorrectly blames “unnecessary locking” and p |
| async_race_lock | gpt-4o-mini | leg_redu | WRONG | F |  | The developer proposes replacing worker.py::process_item wit |
| async_race_lock | gpt-4o-mini | retry_ba | WRONG | F |  | The developer incorrectly blames and removes the locking in  |
| invariant_partial_ | gpt-5.4-mini | baseline | PARTIAL | F |  | The developer blames mixing observability with business logi |
| async_race_lock | gpt-5.4-mini | retry_ba | WRONG | F |  | The developer wrongly concludes the try_lock/unlock in worke |
| missing_branch_c | gpt-5-mini | leg_redu | CORRECT | F | LEG | The developer correctly pinpoints that auth.authorize (auth. |
| l3_state_pipeline | gpt-4.1-nano | leg_redu | WRONG | F |  | The developer incorrectly concludes commit() and freeze_view |
| config_shadowing | gpt-4o-mini | baseline | UNJUDGABLE | F |  |  |
| config_shadowing | gpt-4o-mini | leg_redu | PARTIAL | F |  | The developer blames run_background_job using get_defaults() |
| config_shadowing | gpt-4o-mini | retry_ba | UNJUDGABLE | F |  |  |
| lost_update | gpt-5.4-mini | baseline | CORRECT | F | LEG | The developer correctly identifies the non-atomic read-modif |
| invariant_partial_ | gpt-5.4-mini | retry_ba | PARTIAL | F |  | They correctly point to transfer_service.execute_transfer an |
| false_fix_deadlock | gpt-5-mini | leg_redu | CORRECT | P |  | Developer explicitly names make_transfer_b_to_a_steps as loc |
| cache_invalidation | gpt-4.1-nano | leg_redu | WRONG | P | LUCKY | The developer incorrectly claims cache_invalidate in service |
| early_return_b | gpt-4o-mini | baseline | CORRECT | F | LEG | The developer correctly identifies payment.py::process_payme |