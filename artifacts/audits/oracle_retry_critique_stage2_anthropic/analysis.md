# Oracle Reasoning Evaluator — Stage 1 Results

**Date**: 2026-04-03
**Total samples**: 600
**Evaluated**: 599
**Coverage**: 99.8%

## 1. Label Distribution

| Label | Count | Rate |
|-------|-------|------|
| CORRECT | 246 | 41.0% |
| PARTIAL | 344 | 57.3% |
| WRONG | 9 | 1.5% |
| UNJUDGABLE | 1 | 0.2% |

## 2. TRUE LEG Metrics

- **Strict LEG**: 28.4%
- **Soft LEG**: 77.6%
- **Lucky fix**: 0.5%

## 3. Calibration

- Old mc=True rate: 99.3%
- New CORRECT rate: 41.1%
- **Delta**: 58.3%

## 4. Per-Model Breakdown

| Model | N | CORRECT | LEG_strict | Lucky |
|-------|---|---------|------------|-------|
| claude-haiku-4-5-20251001 | 199 | 87.4% | 80.9% | 1.0% |
| claude-sonnet-4-6 | 400 | 18.0% | 2.2% | 0.2% |

## 5. Sample Results

| Case | Model | Cond | Truth | Pass | LEG? | Justification |
|------|-------|------|-------|------|------|---------------|
| lost_update | claude-haiku-4- | baseline | CORRECT | F | LEG | The developer correctly identifies the bug in make_increment |
| lost_update | claude-haiku-4- | baseline | CORRECT | F | LEG | The developer correctly identifies the bug in make_increment |
| lost_update | claude-haiku-4- | baseline | CORRECT | F | LEG | The developer correctly identifies the non-atomic read-modif |
| lost_update | claude-haiku-4- | baseline | CORRECT | F | LEG | Developer correctly identifies the non-atomic read-modify-wr |
| lost_update | claude-haiku-4- | baseline | CORRECT | F | LEG | The developer correctly identifies the bug as a non-atomic r |
| lost_update | claude-haiku-4- | baseline | CORRECT | F | LEG | Developer correctly identifies the non-atomic read-modify-wr |
| lost_update | claude-haiku-4- | baseline | CORRECT | F | LEG | The developer correctly identifies the true mechanism — a no |
| lost_update | claude-haiku-4- | baseline | CORRECT | F | LEG | The developer correctly identifies the bug in make_increment |
| lost_update | claude-haiku-4- | baseline | CORRECT | F | LEG | The developer correctly locates the bug in make_increment_st |
| lost_update | claude-haiku-4- | baseline | CORRECT | P |  | The developer correctly identifies the real bug at make_incr |
| lost_update | claude-haiku-4- | baseline | CORRECT | F | LEG | The developer correctly names the root cause as the non-atom |
| lost_update | claude-haiku-4- | baseline | CORRECT | F | LEG | The developer correctly identifies the non-atomic read-modif |
| lost_update | claude-haiku-4- | baseline | CORRECT | F | LEG | The developer correctly identifies the oracle root cause (no |
| lost_update | claude-haiku-4- | leg_redu | CORRECT | F | LEG | The developer correctly names counter.py::make_increment_ste |
| lost_update | claude-haiku-4- | leg_redu | CORRECT | F | LEG | The developer correctly points to make_increment_steps and t |
| lost_update | claude-haiku-4- | leg_redu | CORRECT | F | LEG | The developer pinpoints counter.py::make_increment_steps as  |
| lost_update | claude-haiku-4- | leg_redu | PARTIAL | F |  | The developer correctly describes that make_increment_steps  |
| lost_update | claude-haiku-4- | leg_redu | PARTIAL | F |  | The developer correctly recommends making the read-modify-wr |
| lost_update | claude-haiku-4- | leg_redu | PARTIAL | F |  | The developer correctly points to counter.py::make_increment |
| lost_update | claude-haiku-4- | leg_redu | CORRECT | F | LEG | The developer correctly pins the bug to make_increment_steps |
| lost_update | claude-haiku-4- | leg_redu | CORRECT | F | LEG | The developer correctly identifies make_increment_steps as t |
| lost_update | claude-haiku-4- | leg_redu | PARTIAL | F |  | Developer correctly calls for making the increment atomic an |
| lost_update | claude-haiku-4- | leg_redu | CORRECT | F | LEG | The developer correctly identifies the non-atomic read-modif |
| lost_update | claude-haiku-4- | leg_redu | PARTIAL | F |  | They correctly identify counter.py::make_increment_steps and |
| lost_update | claude-haiku-4- | leg_redu | PARTIAL | F |  | The developer correctly points to make_increment_steps and p |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly identifies the true mechanism — a no |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly identifies the true mechanism (non-a |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly identifies the root cause as a non-a |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | Developer correctly identifies the non-atomic read-modify-wr |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly identifies the true mechanism in mak |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly points to counter.py::make_increment |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly identifies the non-atomic read-modif |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly identifies the non-atomic read-modif |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly identifies that make_increment_steps |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly identifies the non-atomic read-modif |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly identifies the non-atomic read-modif |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly identifies the non-atomic read-modif |
| lost_update | claude-haiku-4- | retry_ba | CORRECT | F | LEG | The developer correctly identifies the true mechanism (a non |
| lost_update | claude-haiku-4- | retry_le | CORRECT | P |  | The developer correctly identifies the root cause as the non |
| lost_update | claude-haiku-4- | retry_le | CORRECT | F | LEG | The developer correctly identifies the non-atomic read-modif |
| lost_update | claude-haiku-4- | retry_le | CORRECT | F | LEG | Reasoning correctly identifies the oracle mechanism—non-atom |
| lost_update | claude-haiku-4- | retry_le | CORRECT | F | LEG | The developer correctly identifies the root cause as a non-a |
| lost_update | claude-haiku-4- | retry_le | CORRECT | F | LEG | The developer correctly identifies the bug in make_increment |
| lost_update | claude-haiku-4- | retry_le | CORRECT | F | LEG | The developer correctly pins the failure to the non-atomic r |
| lost_update | claude-haiku-4- | retry_le | CORRECT | F | LEG | The developer correctly identifies the true mechanism — a no |
| lost_update | claude-haiku-4- | retry_le | CORRECT | F | LEG | The developer correctly identifies the true mechanism in cou |
| lost_update | claude-haiku-4- | retry_le | CORRECT | P |  | The developer correctly names the root cause in make_increme |
| lost_update | claude-haiku-4- | retry_le | WRONG | F |  | The developer wrongly blames a "shared captured" dictionary  |
| lost_update | claude-haiku-4- | retry_le | CORRECT | P |  | The developer correctly identifies the bug as the non-atomic |
| lost_update | claude-haiku-4- | retry_le | CORRECT | P |  | The developer correctly identifies the true mechanism (a non |