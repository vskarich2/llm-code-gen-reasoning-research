# Oracle Reasoning Evaluator — Stage 1 Results

**Date**: 2026-04-01
**Total samples**: 500
**Evaluated**: 467
**Coverage**: 93.4%

## 1. Label Distribution

| Label | Count | Rate |
|-------|-------|------|
| CORRECT | 291 | 58.2% |
| PARTIAL | 108 | 21.6% |
| WRONG | 68 | 13.6% |
| UNJUDGABLE | 33 | 6.6% |

## 2. TRUE LEG Metrics

- **Strict LEG**: 13.7%
- **Soft LEG**: 35.5%
- **Lucky fix**: 3.2%

## 3. Calibration

- Old mc=True rate: 99.4%
- New CORRECT rate: 62.3%
- **Delta**: 37.0%

## 4. Per-Model Breakdown

| Model | N | CORRECT | LEG_strict | Lucky |
|-------|---|---------|------------|-------|
| claude-3-haiku-20240307 | 18 | 50.0% | 0.0% | 50.0% |
| claude-haiku-4-5-20251001 | 54 | 81.5% | 31.5% | 0.0% |
| claude-sonnet-4-20250514 | 54 | 50.0% | 0.0% | 0.0% |
| claude-sonnet-4-6 | 54 | 53.7% | 5.6% | 0.0% |
| gpt-4.1-nano | 73 | 74.0% | 24.7% | 2.7% |
| gpt-4o-mini | 52 | 63.5% | 13.5% | 0.0% |
| gpt-5 | 54 | 51.9% | 1.9% | 0.0% |
| gpt-5-mini | 54 | 63.0% | 20.4% | 5.6% |
| gpt-5.4-mini | 54 | 61.1% | 13.0% | 1.9% |

## 5. Sample Results

| Case | Model | Cond | Truth | Pass | LEG? | Justification |
|------|-------|------|-------|------|------|---------------|
| early_return_a | claude-3-haiku- | baseline | UNJUDGABLE | F |  |  |
| early_return_a | claude-3-haiku- | baseline | UNJUDGABLE | F |  |  |
| early_return_a | claude-3-haiku- | baseline | UNJUDGABLE | F |  |  |
| config_shadowing | claude-3-haiku- | baseline | WRONG | P | LUCKY | The developer blames get_defaults for returning DEFAULTS dir |
| config_shadowing | claude-3-haiku- | baseline | WRONG | P | LUCKY | The developer blames get_defaults() returning the DEFAULTS d |
| early_return_a | claude-3-haiku- | leg_redu | UNJUDGABLE | F |  |  |
| lost_update | claude-3-haiku- | leg_redu | UNJUDGABLE | F |  |  |
| config_shadowing | claude-3-haiku- | leg_redu | CORRECT | P |  | The developer correctly pinpoints defaults.py::DEFAULTS (tim |
| config_shadowing | claude-3-haiku- | leg_redu | CORRECT | P |  | The developer correctly identifies the root cause as DEFAULT |
| config_shadowing | claude-3-haiku- | leg_redu | UNJUDGABLE | F |  |  |
| lost_update | claude-3-haiku- | leg_redu | UNJUDGABLE | F |  |  |
| lost_update | claude-3-haiku- | leg_redu | UNJUDGABLE | F |  |  |
| feature_flag_drift | claude-haiku-4- | baseline | CORRECT | F | LEG | The developer correctly pinpoints that api.checkout accepts  |
| check_then_act | claude-haiku-4- | baseline | CORRECT | F | LEG | The developer correctly identifies the non-atomic check-then |
| hidden_dep_multiho | claude-haiku-4- | baseline | CORRECT | P |  | The developer correctly identifies that sync_user_to_cache a |
| hidden_dep_multiho | claude-haiku-4- | baseline | CORRECT | P |  | The developer correctly identifies that the two functions di |
| invariant_partial_ | claude-haiku-4- | leg_redu | PARTIAL | F |  | The developer correctly spots that execute_transfer (transfe |
| lost_update | claude-haiku-4- | leg_redu | CORRECT | F | LEG | The developer correctly identifies the bug in make_increment |
| feature_flag_drift | claude-haiku-4- | leg_redu | CORRECT | P |  | The developer correctly identifies that api.py::checkout acc |
| feature_flag_drift | claude-haiku-4- | leg_redu | CORRECT | P |  | Correctly identifies that api.py::checkout's use_new_pricing |
| feature_flag_drift | claude-haiku-4- | leg_redu | CORRECT | P |  | Developer correctly identifies that api.py::checkout accepts |
| invariant_partial_ | claude-haiku-4- | leg_redu | PARTIAL | F |  | The developer correctly points to transfer_service.execute_t |
| lost_update | claude-haiku-4- | leg_redu | CORRECT | F | LEG | The developer correctly pins the root cause to counter.py::m |
| feature_flag_drift | claude-haiku-4- | leg_redu | CORRECT | P |  | The developer correctly identifies api.py::checkout as the c |
| feature_flag_drift | claude-haiku-4- | leg_redu | CORRECT | P |  | The developer correctly identifies that api.py::checkout acc |
| config_shadowing | claude-sonnet-4 | baseline | PARTIAL | F |  | The developer blames run_background_job() calling get_defaul |
| config_shadowing | claude-sonnet-4 | baseline | PARTIAL | F |  | The developer blames run_background_job for calling get_defa |
| early_return_a | claude-sonnet-4 | baseline | CORRECT | P |  | The developer correctly identifies that payment.py::process_ |
| early_return_a | claude-sonnet-4 | baseline | CORRECT | P |  | The developer correctly identifies that payment.py::process_ |
| early_return_a | claude-sonnet-4 | baseline | CORRECT | P |  | The developer correctly identifies that payment.py::process_ |
| config_shadowing | claude-sonnet-4 | leg_redu | PARTIAL | F |  | The developer blames run_background_job calling get_defaults |
| config_shadowing | claude-sonnet-4 | leg_redu | PARTIAL | F |  | The developer blames run_background_job for using get_defaul |
| early_return_a | claude-sonnet-4 | leg_redu | CORRECT | P |  | The developer correctly identifies the root cause (process_p |
| early_return_a | claude-sonnet-4 | leg_redu | CORRECT | P |  | The developer correctly identifies process_payment's early r |
| config_shadowing | claude-sonnet-4 | leg_redu | PARTIAL | F |  | The developer blames run_background_job for calling get_defa |
| lost_update | claude-sonnet-4 | leg_redu | WRONG | F |  | The oracle says the bug is a non-atomic read-modify-write in |
| early_return_a | claude-sonnet-4 | leg_redu | CORRECT | P |  | The developer correctly identifies payment.py::process_payme |
| early_return_a | claude-sonnet-4 | leg_redu | CORRECT | P |  | The developer correctly identifies process_payment's early r |
| early_return_a | claude-sonnet-4 | leg_redu | CORRECT | P |  | Developer correctly identifies that payment.py::process_paym |
| config_shadowing | claude-sonnet-4 | baseline | WRONG | F |  | The developer blames service.run_background_job for bypassin |
| config_shadowing | claude-sonnet-4 | baseline | PARTIAL | F |  | The developer blames run_background_job calling get_defaults |
| temporal_drift_b | claude-sonnet-4 | baseline | CORRECT | P |  | The developer correctly identifies pipeline.py::pipeline cal |
| temporal_drift_b | claude-sonnet-4 | baseline | CORRECT | P |  | Developer correctly identifies that pipeline.py::pipeline ca |
| config_shadowing | claude-sonnet-4 | leg_redu | PARTIAL | F |  | The developer blames run_background_job() in service.py for  |
| config_shadowing | claude-sonnet-4 | leg_redu | PARTIAL | F |  | The developer correctly spots that service.run_background_jo |
| temporal_drift_b | claude-sonnet-4 | leg_redu | CORRECT | P |  | The developer correctly identifies the root cause and locati |
| hidden_dep_multiho | claude-sonnet-4 | leg_redu | PARTIAL | P |  | The developer correctly highlights the semantic mismatch bet |
| temporal_drift_b | claude-sonnet-4 | leg_redu | CORRECT | P |  | The developer correctly identifies pipeline.py::pipeline cal |
| lost_update | claude-sonnet-4 | leg_redu | CORRECT | F | LEG | The developer pinpoints the non-atomic read-modify-write in  |
| hidden_dep_multiho | claude-sonnet-4 | leg_redu | WRONG | F |  | Although the developer correctly notes the differing semanti |