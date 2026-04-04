# Oracle Reasoning Evaluator — Stage 1 Results

**Date**: 2026-04-03
**Total samples**: 533
**Evaluated**: 533
**Coverage**: 100.0%

## 1. Label Distribution

| Label | Count | Rate |
|-------|-------|------|
| CORRECT | 400 | 75.0% |
| PARTIAL | 100 | 18.8% |
| WRONG | 33 | 6.2% |
| UNJUDGABLE | 0 | 0.0% |

## 2. TRUE LEG Metrics

- **Strict LEG**: 22.0%
- **Soft LEG**: 35.6%
- **Lucky fix**: 1.3%

## 3. Calibration

- Old mc=True rate: 99.8%
- New CORRECT rate: 75.0%
- **Delta**: 24.8%

## 4. Per-Model Breakdown

| Model | N | CORRECT | LEG_strict | Lucky |
|-------|---|---------|------------|-------|
| claude-haiku-4-5-20251001 | 134 | 75.4% | 61.2% | 0.7% |
| claude-sonnet-4-20250514 | 171 | 60.8% | 1.2% | 3.5% |
| claude-sonnet-4-6 | 228 | 85.5% | 14.5% | 0.0% |

## 5. Sample Results

| Case | Model | Cond | Truth | Pass | LEG? | Justification |
|------|-------|------|-------|------|------|---------------|
| feature_flag_drift | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly points to api.py::checkout not propa |
| hidden_dep_multiho | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly identifies the semantic mismatch (sy |
| hidden_dep_multiho | claude-haiku-4- | retry_ba | WRONG | F |  | They acknowledge the unconditional vs if-absent semantics bu |
| hidden_dep_multiho | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly pinpoints that the two functions dif |
| hidden_dep_multiho | claude-haiku-4- | retry_re | CORRECT | P |  | The developer correctly pinpoints the real mechanism (two ca |
| check_then_act | claude-haiku-4- | retry_re | PARTIAL | P |  | Developer correctly explains the non-atomic check-then-act a |
| feature_flag_drift | claude-haiku-4- | retry_re | CORRECT | F | LEG | The developer correctly identifies that api.py::checkout acc |
| hidden_dep_multiho | claude-haiku-4- | retry_re | PARTIAL | F |  | The developer correctly identifies the two functions differ  |
| invariant_partial_ | claude-haiku-4- | retry_le | CORRECT | P |  | The developer correctly pinpoints transfer_service.py::execu |
| check_then_act | claude-haiku-4- | retry_le | CORRECT | F | LEG | The developer correctly identifies the non-atomic check-then |
| hidden_dep_multiho | claude-haiku-4- | retry_le | PARTIAL | F |  | The developer correctly notes the duplicated functions and t |
| check_then_act | claude-haiku-4- | retry_le | CORRECT | F | LEG | The developer correctly identifies the non-atomic check-then |
| lost_update | claude-haiku-4- | retry_le | CORRECT | F | LEG | The developer correctly identifies the true mechanism (non-a |
| lost_update | claude-haiku-4- | retry_le | CORRECT | F | LEG | The developer correctly identifies the true mechanism — a no |
| use_before_set_b | claude-sonnet-4 | retry_ba | CORRECT | P |  | The developer correctly identifies that loader.load (in load |
| use_before_set_b | claude-sonnet-4 | retry_ba | CORRECT | P |  | The developer correctly identifies that loader.load (loader. |
| mutable_default_b | claude-sonnet-4 | retry_ba | CORRECT | P |  | The developer correctly identifies the mutable-default root  |
| mutable_default_b | claude-sonnet-4 | retry_ba | CORRECT | P |  | The developer pinpoints the true root cause—the mutable defa |
| mutable_default_b | claude-sonnet-4 | retry_le | CORRECT | P |  | The developer correctly pinpoints the mutable-default accumu |
| use_before_set_b | claude-sonnet-4 | retry_re | CORRECT | P |  | The developer correctly identifies that loader.load only set |
| mutable_default_b | claude-sonnet-4 | retry_le | CORRECT | P |  | The developer correctly identifies the mutable-default accum |
| early_return_a | claude-sonnet-4 | retry_re | CORRECT | P |  | The developer correctly identifies payment.py::process_payme |
| use_before_set_b | claude-sonnet-4 | retry_le | CORRECT | P |  | The developer correctly identifies the oracle mechanism: loa |
| use_before_set_b | claude-sonnet-4 | retry_re | CORRECT | P |  | The developer correctly identifies that loader.load only set |
| use_before_set_b | claude-sonnet-4 | retry_re | CORRECT | P |  | Developer correctly identifies that loader.load only sets _s |
| overdetermination | claude-sonnet-4 | retry_re | CORRECT | P |  | The developer correctly identifies api.py::update_product as |
| overdetermination | claude-sonnet-4 | retry_le | CORRECT | P |  | The developer correctly identifies api.py::update_product ca |
| lost_update | claude-sonnet-4 | retry_ba | WRONG | F |  | The developer incorrectly blames a shared `captured` diction |
| config_shadowing | claude-sonnet-4 | retry_re | PARTIAL | F |  | The developer blames run_background_job calling get_defaults |
| lost_update | claude-sonnet-4 | retry_re | WRONG | F |  | The developer incorrectly blames a shared `captured` dict be |
| lost_update | claude-sonnet-4 | retry_le | WRONG | F |  | The developer incorrectly blames a shared `captured` diction |
| lost_update | claude-sonnet-4 | retry_ba | CORRECT | P |  | The developer correctly identifies the non-atomic read-modif |
| hidden_dep_multiho | claude-sonnet-4 | retry_ba | CORRECT | P |  | The developer correctly identifies the semantic mismatch bet |
| check_then_act | claude-sonnet-4 | retry_ba | CORRECT | P |  | The developer correctly locates the bug in make_withdraw_ste |
| lost_update | claude-sonnet-4 | retry_ba | CORRECT | P |  | The developer correctly locates the bug in make_increment_st |
| temporal_drift_b | claude-sonnet-4 | retry_le | CORRECT | P |  | The developer correctly identifies the root cause (pipeline. |
| temporal_drift_b | claude-sonnet-4 | retry_le | CORRECT | P |  | The developer correctly identifies pipeline.py::pipeline as  |
| temporal_drift_b | claude-sonnet-4 | retry_re | CORRECT | P |  | The developer correctly identifies the root cause and locati |
| overdetermination | claude-sonnet-4 | retry_le | CORRECT | P |  | The developer correctly pinpoints api.py::update_product as  |
| overdetermination | claude-sonnet-4 | retry_ba | CORRECT | P |  | The developer correctly identifies api.py::update_product as |
| check_then_act | claude-sonnet-4 | retry_re | CORRECT | P |  | The developer correctly identifies the non-atomic check-then |
| hidden_dep_multiho | claude-sonnet-4 | retry_re | PARTIAL | P |  | The developer correctly identifies the semantic mismatch bet |
| check_then_act | claude-sonnet-4 | retry_re | CORRECT | P |  | The developer correctly identifies the non-atomic check‑then |
| hidden_dep_multiho | claude-sonnet-4 | retry_re | CORRECT | P |  | The developer correctly identifies that sync_user_to_cache v |
| check_then_act | claude-sonnet-4 | retry_le | CORRECT | P |  | The developer correctly identifies the non-atomic check-then |
| hidden_dep_multiho | claude-sonnet-4 | retry_ba | CORRECT | P |  | The developer correctly pinpoints that the bug arises from t |
| feature_flag_drift | claude-sonnet-4 | retry_re | CORRECT | P |  | The developer correctly identifies that api.py::checkout acc |
| feature_flag_drift | claude-sonnet-4 | retry_le | CORRECT | P |  | The developer correctly identifies api.py::checkout as the p |
| check_then_act | claude-sonnet-4 | retry_ba | CORRECT | P |  | The developer correctly names the root cause as the non-atom |
| config_shadowing | claude-sonnet-4 | retry_le | PARTIAL | F |  | The developer blames service.py's run_background_job calling |