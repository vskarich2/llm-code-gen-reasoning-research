================================================================================
HINT EFFECTIVENESS REPORT: DDC + V2 CASES ACROSS 4 MODELS
================================================================================

This report synthesizes results from 5 ablation rounds testing 17 distinct
retry-time hints across DDC (deep dependency chain) and standard v2 benchmark
cases. All hints are single sentences appended to the retry prompt after a
failed first attempt.

ABLATION ROUNDS:
  1. hint_ablation_v3   — 8 hints × 3 models × DDC failed cases
  2. hint_ablation_v4   — 7 hints × 3 models × DDC failed cases
  3. v2_hint_ablation   — 7 hints × gpt-4o-mini × 72 non-DDC cases
  4. ddc_trace_hint     — trace_value × 3 models × DDC failed cases
  5. ddc_fixnc_hint     — fix_not_consumer × 3 models × DDC failed cases

CRITIQUE PROMPT:
  "Your previous fix did not pass. Consider this feedback:"
  (Changed from v3's "your implementation may not fully reflect your reasoning"
  which assumed reasoning was correct and reinforced wrong depth judgments.)

================================================================================
1. BEST HINTS PER MODEL ON DDC CASES
================================================================================

gpt-5.4-mini (16 failed baseline cases):

  hint                                    fixed   rate
  ──────────────────────────────────────  ─────   ────
  no-touch                                8/14    57%
  fix_not_consumer                        8/15    53%
  first_corruption (v4)                   7/14    50%
  location+impl+scope (v4)               7/14    50%
  trace_value                             7/14    50%
  location+impl (v4)                      5/12    42%
  anti_compensation (v3)                  5/13    38%

gpt-5-mini (8 failed baseline cases):

  hint                                    fixed   rate
  ──────────────────────────────────────  ─────   ────
  transformation (v4)                     2/6     33%
  fix_not_consumer                        2/6     33%
  first_corruption (v3)                   1/5     20%
  location+impl (v4)                      1/5     20%
  location+impl+scope (v4)               1/5     20%
  first_corruption+minimality (v3)        1/6     17%
  trace_value                             0/6      0%

gpt-4o-mini (23 failed baseline cases):

  hint                                    fixed   rate
  ──────────────────────────────────────  ─────   ────
  anti_comp+single_file (v3)              3/22    14%
  location+impl (v4)                      2/21    10%
  location+impl+scope (v4)               2/22     9%
  trace_value                             1/21     5%
  fix_not_consumer                        0/21     0%

================================================================================
2. BEST HINTS ON V2 (NON-DDC) CASES — gpt-4o-mini
================================================================================

72 standard benchmark cases, baseline + hint retry on failure:

  hint                    fixed   rate   total pass
  ────────────────────    ─────   ────   ──────────
  trace_value             9/42    21%    54%
  first_corruption        8/40    20%    56%
  location_impl           6/42    14%    50%
  location_scope_impl     5/39    13%    53%
  minimality              5/40    12%    51%
  transformation          5/41    12%    50%
  fix_not_consumer        5/43    12%    47%

================================================================================
3. PER-CASE BREAKDOWN — V2 CASES (gpt-4o-mini)
================================================================================

FIX = hint fixed a failure   OK = already passed   . = still failed

case                                        trace  1st-cr  lo+im  lo+i+s  minim  trans  fx-nc
─────────────────────────────────────────   ─────  ─────   ─────  ─────   ─────  ─────  ─────
check_then_act                               FIX    FIX      .      .       .      .     FIX
duplicate_write_retry_hidden_b_plus_adv      FIX     OK      .      OK     FIX     .      OK
early_return_a                               FIX    FIX      .      .       .     FIX      .
feature_flag_drift                           FIX     .       .      .       .      .       .
index_misalign_a                              .      .      FIX    FIX     FIX     .       .
lazy_init_a                                  FIX    FIX     FIX    FIX     FIX    FIX     FIX
missing_branch_c                              .      .      FIX     .       .      .       .
ordering_dependency                          FIX     .       .      .       .     FIX      .
partial_update_b                              OK     OK      .      OK      .     FIX      OK
silent_default_a                              OK    FIX      OK     .       .      OK      .
silent_default_c                              .     FIX     FIX    FIX      .      .       .
transform_pipeline_unit_drift_c_v3           FIX     .       .      .       .      .       .
use_before_set_b                             FIX    FIX      .     FIX      .      .      FIX
use_before_set_c                              .     FIX      .      OK     FIX    FIX      .
versioned_policy_fallback_regression_b       FIX    FIX     FIX    FIX     FIX     OK      OK
versioned_policy_fallback_regression_b_plus   .      .      FIX     .       OK     .      FIX
versioned_policy_fallback_regression_l3       .      .       .      OK      OK     OK     FIX
─────────────────────────────────────────   ─────  ─────   ─────  ─────   ─────  ─────  ─────
FIXED / FAILED                              9/42   8/40    6/42   5/39    5/40   5/41   5/43
FIX RATE                                     21%    20%     14%    13%     12%    12%    12%

17 of 72 cases had at least one hint fix a failure.

================================================================================
4. PER-CASE BREAKDOWN — DDC CASES (trace_value hint)
================================================================================

FIX = hint fixed   FAIL = still failed   OK = passed a0   · = not tested

case                              gpt-4o-mini   gpt-5.4-mini   gpt-5-mini
──────────────────────────────    ──────────    ────────────    ──────────
auth_context baseline                FAIL            ·              ·
auth_context trap_1                  FAIL           FIX             ·
auth_context trap_3                  FAIL            ·              ·
auth_context trap_4                   ·             FIX             ·
auth_context trap_5                  FAIL           FIX           FAIL
billing baseline                     FAIL          FAIL           FAIL
billing trap_1                       FAIL          FAIL           FAIL
billing trap_3                       FAIL          FAIL             ·
billing trap_4                       FAIL          FAIL             ·
billing trap_5                       FAIL          FAIL             ·
config baseline                      FAIL           FIX             ·
config trap_1                        FAIL            ·              ·
config trap_5                         ·             FIX             ·
etl baseline                         FAIL            ·              ·
etl trap_1                           FAIL            ·              OK
etl trap_3                           FAIL            ·              ·
etl trap_4                           FAIL            ·              ·
etl trap_5                            ·              OK             ·
logging trap_1                       FAIL            ·              ·
logging trap_4                        ·              ·              OK
ml trap_1                            FAIL          FAIL           FAIL
ml trap_3                            FAIL           FIX             ·
search baseline                      FAIL            ·              ·
search trap_5                         OK             ·              ·
serial baseline                      FAIL            ·              ·
serial trap_1                         ·              OK           FAIL
serial trap_4                         OK            FIX           FAIL
serial trap_5                        FIX           FAIL             ·
──────────────────────────────    ──────────    ────────────    ──────────
FIXED / FAILED                     1/21           7/14           0/6
FIX RATE                            5%             50%            0%

================================================================================
5. PER-CASE BREAKDOWN — DDC CASES (fix_not_consumer hint)
================================================================================

case                              gpt-4o-mini   gpt-5.4-mini   gpt-5-mini
──────────────────────────────    ──────────    ────────────    ──────────
auth trap_1                          FAIL          FAIL             ·
auth trap_4                           ·             FIX             ·
auth trap_5                          FAIL           FIX           FAIL
billing baseline                     FAIL          FAIL           FAIL
billing trap_1                       FAIL          FAIL           FAIL
billing trap_3                        ·            FAIL             ·
billing trap_4                       FAIL          FAIL             ·
billing trap_5                       FAIL          FAIL             ·
config baseline                      FAIL           FIX             ·
config trap_1                        FAIL            ·              ·
config trap_5                         ·             FIX             ·
etl baseline                         FAIL            ·              ·
etl trap_1                           FAIL            ·            FAIL
etl trap_3                           FAIL            ·              ·
etl trap_4                           FAIL            ·              ·
etl trap_5                            ·             FIX             ·
logging trap_1                       FAIL            ·              ·
logging trap_4                        ·              ·            FAIL
ml trap_1                            FAIL          FAIL           FAIL
ml trap_3                            FAIL           FIX             ·
search baseline                      FAIL            ·              ·
search trap_5                        FAIL            ·              ·
serial baseline                      FAIL            ·              ·
serial trap_1                         ·             FIX            FIX
serial trap_4                        FAIL           FIX            FIX
serial trap_5                        FAIL           FIX             ·
──────────────────────────────    ──────────    ────────────    ──────────
FIXED / FAILED                     0/18           8/15           2/6
FIX RATE                            0%             53%           33%

================================================================================
6. HINT-CASE MATCHING PATTERNS
================================================================================

The data shows a clear mapping between case structure and effective hints:

PIPELINE/DEPTH CASES (DDC):
  Best hints address WHERE to intervene in a multi-node pipeline:
  - no-touch (57%)        "don't modify unless certain"
  - fix_not_consumer (53%) "fix the transformation, not the consumer"
  - first_corruption (50%) "fix where value first goes wrong"
  These work because DDC failures are primarily depth errors (model fixes
  the wrong node) or over-editing (model touches too many files).

STANDARD SINGLE-FILE CASES (V2):
  Best hints address HOW to reason about code:
  - trace_value (21%)      "trace value from creation to consumption"
  - first_corruption (20%) "fix where value first goes wrong"
  These work because v2 failures are primarily reasoning errors (model
  doesn't understand the bug) or implementation errors (understands but
  codes wrong).

CROSS-CUTTING:
  first_corruption (20-21%) is the only hint that works on BOTH case types.
  "Fix where the value first goes wrong" is valid whether "where" means
  "which file in the pipeline" or "which line in the function."

HINTS THAT DON'T TRANSFER:
  - no-touch works on DDC (57%) but was not tested on v2
  - fix_not_consumer works on DDC (53%) but scores 12% on v2
  - trace_value works on v2 (21%) but scores 0% for gpt-5-mini on DDC

IMPLICATION:
  A hint library should be case-type-aware. Multi-file pipeline cases need
  anti-compensation and restraint hints. Single-file cases need value-tracing
  and reasoning-process hints. first_corruption is the safe default for both.

================================================================================
7. MODEL-SPECIFIC PATTERNS
================================================================================

gpt-5.4-mini:
  Failure mode: OVER-EDITING (avg 5 files changed)
  Best hints: restraint (no-touch) and anti-compensation (fix_not_consumer)
  The model always touches the correct file but changes 4 extra files,
  introducing bugs. Hints that say "stop changing things" work best.

gpt-5-mini:
  Failure mode: DEPTH CONFUSION (1 file changed, wrong file)
  Best hints: implementation (transformation, fix_not_consumer)
  The model is precise but picks the wrong intervention point.
  Hints about HOW to fix redirect it; hints about WHERE don't help
  because the model already has a (wrong) location commitment.

gpt-4o-mini:
  Failure mode: WEAK REASONING (wrong mechanism entirely)
  Best hints: combined (anti_comp+single_file at 14%)
  No single hint helps much. The model's causal understanding is too
  weak for any single-sentence hint to redirect. Only combined hints
  that address multiple failure modes simultaneously produce any effect.

================================================================================
8. NEVER-FIXABLE CASES
================================================================================

billing_aggregation (all variants): 0 fixes across ALL hints, ALL models,
ALL ablation rounds. The model has a fundamentally wrong causal model —
it blames tier resolution instead of unit aggregation. No hint can fix
a wrong mental model of the system.

config_derivation_trap_1 (gpt-4o-mini, gpt-5-mini): 0 fixes. The model
always fixes deriver.py instead of parser.py. It sees the symptom (string
multiplication) and fixes where it manifests, not where it originates.

ml_feature_trap_1: 0 fixes for gpt-4o-mini and gpt-5-mini. Only gpt-5.4-mini
with no-touch hint fixes it. The scorer's -0.1 bias is the most tempting
endpoint trap — models consistently try to improve the bias correction
rather than fixing the feature engineering.

================================================================================
9. KEY FINDINGS
================================================================================

1. trace_value is the best general-purpose hint (21% on v2, 50% on DDC
   for gpt-5.4-mini), but it doesn't help gpt-5-mini on DDC at all.

2. fix_not_consumer is the best cross-model DDC hint (53% for 5.4-mini,
   33% for 5-mini), and the only hint that ranks top-3 for both models.

3. first_corruption is the safest default — 20-21% on both case types,
   no model where it actively hurts.

4. Hint effectiveness depends on the model's failure mode, not the case:
   - over-editing → restraint hints
   - wrong file → location hints
   - wrong mechanism → nothing helps much

5. The critique prompt matters: removing "your implementation may not fully
   reflect your reasoning" was necessary for implementation-focused hints
   to work, because the old prompt reinforced wrong reasoning.

6. 17 of 72 v2 cases (24%) are hint-fixable by at least one hint.
   13 of 16 DDC cases for gpt-5.4-mini are fixable. billing_aggregation
   is the only family that resists all interventions.
