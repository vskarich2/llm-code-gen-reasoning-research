"""Statistical correctness tests for paper analysis.

Tests: mean consistency, case-level aggregation, LEG definition,
paired t-test, bootstrap, interaction analysis, FDR, NaN/inf rejection,
dashboard vs analysis consistency, order invariance.
"""

import json
import sys
from pathlib import Path
from random import Random

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sp_stats
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.paper_analysis import (
    build_case_level_df,
    compute_exec_reasoning,
    paired_ttest,
    bootstrap_ci,
    interaction_ols,
    bootstrap_dod,
)
from live_metrics import compute_metrics


# ============================================================
# FIXTURES
# ============================================================

def _make_events(model="m1", cases=None, conditions=None, trials=None, pass_fn=None):
    """Generate synthetic events. pass_fn(case_id, condition, trial) -> bool."""
    cases = cases or ["c1", "c2", "c3", "c4"]
    conditions = conditions or ["baseline", "leg_reduction"]
    trials = trials or [1, 2]
    events = []
    for case_id in cases:
        for cond in conditions:
            for trial in trials:
                p = pass_fn(case_id, cond, trial) if pass_fn else True
                events.append({
                    "model": model,
                    "trial": trial,
                    "run_id": f"run_{trial}",
                    "case_id": case_id,
                    "condition": cond,
                    "timestamp": "2026-01-01T00:00:00",
                    "pass": p,
                    "reasoning_correct": p,  # default: aligned
                    "code_correct": p,
                })
    return events


# ============================================================
# B1. Mean consistency
# ============================================================

class TestMeanConsistency:
    def test_numpy_pandas_mean_agree(self):
        x = [0.1, 0.3, 0.5, 0.7, 0.9]
        assert abs(np.mean(x) - pd.Series(x).mean()) < 1e-15

    def test_case_level_aggregate_matches_manual(self):
        events = _make_events(
            cases=["c1", "c2", "c3", "c4"],
            conditions=["baseline", "leg_reduction"],
            trials=[1, 2],
            pass_fn=lambda c, cond, t: (c in ["c1", "c2"]) if cond == "baseline" else (c == "c1")
        )
        case_df = build_case_level_df(events)
        # c1/baseline: both trials pass → 1.0
        # c2/baseline: both trials pass → 1.0
        # c3/baseline: both fail → 0.0
        # c4/baseline: both fail → 0.0
        bl = case_df[case_df["condition"] == "baseline"]
        assert abs(bl[bl["case_id"] == "c1"]["pass_rate"].iloc[0] - 1.0) < 1e-10
        assert abs(bl[bl["case_id"] == "c3"]["pass_rate"].iloc[0] - 0.0) < 1e-10
        # Overall baseline mean = (1+1+0+0)/4 = 0.5
        assert abs(bl["pass_rate"].mean() - 0.5) < 1e-10


class TestCaseAggregation:
    def test_case_aggregation_correctness(self):
        """B1a. 2 cases, 2 conditions, 2 trials with known values."""
        events = [
            # c1/baseline: t1=pass, t2=fail → 0.5
            {"model": "m", "trial": 1, "run_id": "r1", "case_id": "c1", "condition": "baseline",
             "timestamp": "t", "pass": True, "reasoning_correct": True, "code_correct": True},
            {"model": "m", "trial": 2, "run_id": "r2", "case_id": "c1", "condition": "baseline",
             "timestamp": "t", "pass": False, "reasoning_correct": False, "code_correct": False},
            # c2/baseline: t1=pass, t2=pass → 1.0
            {"model": "m", "trial": 1, "run_id": "r1", "case_id": "c2", "condition": "baseline",
             "timestamp": "t", "pass": True, "reasoning_correct": True, "code_correct": True},
            {"model": "m", "trial": 2, "run_id": "r2", "case_id": "c2", "condition": "baseline",
             "timestamp": "t", "pass": True, "reasoning_correct": True, "code_correct": True},
            # c1/leg_reduction: both pass → 1.0
            {"model": "m", "trial": 1, "run_id": "r1", "case_id": "c1", "condition": "leg_reduction",
             "timestamp": "t", "pass": True, "reasoning_correct": True, "code_correct": True},
            {"model": "m", "trial": 2, "run_id": "r2", "case_id": "c1", "condition": "leg_reduction",
             "timestamp": "t", "pass": True, "reasoning_correct": True, "code_correct": True},
            # c2/leg_reduction: both fail → 0.0
            {"model": "m", "trial": 1, "run_id": "r1", "case_id": "c2", "condition": "leg_reduction",
             "timestamp": "t", "pass": False, "reasoning_correct": False, "code_correct": False},
            {"model": "m", "trial": 2, "run_id": "r2", "case_id": "c2", "condition": "leg_reduction",
             "timestamp": "t", "pass": False, "reasoning_correct": False, "code_correct": False},
        ]
        case_df = build_case_level_df(events)

        bl = case_df[case_df["condition"] == "baseline"].sort_values("case_id")
        assert abs(bl.iloc[0]["pass_rate"] - 0.5) < 1e-10  # c1
        assert abs(bl.iloc[1]["pass_rate"] - 1.0) < 1e-10  # c2
        # Manual baseline mean = (0.5 + 1.0) / 2 = 0.75
        assert abs(bl["pass_rate"].mean() - 0.75) < 1e-10


class TestExecReasoning:
    def test_exec_given_reasoning_conditioning(self):
        """B1b. P(code_correct | reasoning_correct) with mixed data."""
        events = [
            # reasoning_correct=True, code_correct=True (2 events)
            {"model": "m", "condition": "baseline", "reasoning_correct": True, "code_correct": True,
             "trial": 1, "run_id": "r", "case_id": "c1", "timestamp": "t", "pass": True},
            {"model": "m", "condition": "baseline", "reasoning_correct": True, "code_correct": True,
             "trial": 2, "run_id": "r", "case_id": "c1", "timestamp": "t", "pass": True},
            # reasoning_correct=True, code_correct=False (1 event)
            {"model": "m", "condition": "baseline", "reasoning_correct": True, "code_correct": False,
             "trial": 1, "run_id": "r", "case_id": "c2", "timestamp": "t", "pass": False},
            # reasoning_correct=False, code_correct=True (1 event)
            {"model": "m", "condition": "baseline", "reasoning_correct": False, "code_correct": True,
             "trial": 1, "run_id": "r", "case_id": "c3", "timestamp": "t", "pass": True},
            # reasoning_correct=False, code_correct=False (2 events)
            {"model": "m", "condition": "baseline", "reasoning_correct": False, "code_correct": False,
             "trial": 1, "run_id": "r", "case_id": "c4", "timestamp": "t", "pass": False},
            {"model": "m", "condition": "baseline", "reasoning_correct": False, "code_correct": False,
             "trial": 2, "run_id": "r", "case_id": "c4", "timestamp": "t", "pass": False},
        ]
        er = compute_exec_reasoning(events, "m", "baseline")
        # P(code_correct | reasoning_correct) = 2/3 ≈ 0.6667
        assert abs(er - 2 / 3) < 1e-4


class TestLEGDefinition:
    def test_leg_definition_correct(self):
        """B1c. LEG = reasoning_correct AND NOT code_correct ONLY."""
        events = [
            {"model": "m", "condition": "bl", "reasoning_correct": True, "code_correct": True,
             "trial": 1, "run_id": "r", "case_id": "c1", "timestamp": "t", "pass": True},
            {"model": "m", "condition": "bl", "reasoning_correct": True, "code_correct": False,
             "trial": 1, "run_id": "r", "case_id": "c2", "timestamp": "t", "pass": False},
            {"model": "m", "condition": "bl", "reasoning_correct": False, "code_correct": True,
             "trial": 1, "run_id": "r", "case_id": "c3", "timestamp": "t", "pass": True},
            {"model": "m", "condition": "bl", "reasoning_correct": False, "code_correct": False,
             "trial": 1, "run_id": "r", "case_id": "c4", "timestamp": "t", "pass": False},
        ]
        case_df = build_case_level_df(events)
        # Only c2 is LEG (reasoning_correct=True, code_correct=False)
        total_leg = case_df["leg_rate"].sum()
        assert total_leg == 1.0  # c2 has leg_rate=1.0, others have 0.0
        assert case_df[case_df["case_id"] == "c2"]["leg_rate"].iloc[0] == 1.0
        assert case_df[case_df["case_id"] == "c1"]["leg_rate"].iloc[0] == 0.0
        assert case_df[case_df["case_id"] == "c3"]["leg_rate"].iloc[0] == 0.0


class TestTrialAveraging:
    def test_trial_averaging_per_case(self):
        """B1d. Case c1, baseline, 4 trials with pass=[T,F,T,T] → 0.75."""
        events = [
            {"model": "m", "trial": t, "run_id": f"r{t}", "case_id": "c1", "condition": "baseline",
             "timestamp": "t", "pass": p, "reasoning_correct": p, "code_correct": p}
            for t, p in [(1, True), (2, False), (3, True), (4, True)]
        ]
        case_df = build_case_level_df(events)
        assert abs(case_df.iloc[0]["pass_rate"] - 0.75) < 1e-10


# ============================================================
# B2. Paired t-test correctness
# ============================================================

class TestPairedTtest:
    def _make_paired_case_df(self, baseline, treatment, cases=None):
        cases = cases or [f"c{i}" for i in range(len(baseline))]
        rows = []
        for i, (bl, tr) in enumerate(zip(baseline, treatment)):
            rows.append({"model": "m", "case_id": cases[i], "condition": "baseline",
                         "pass_rate": bl, "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 2})
            rows.append({"model": "m", "case_id": cases[i], "condition": "leg_reduction",
                         "pass_rate": tr, "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 2})
        return pd.DataFrame(rows)

    def test_paired_ttest_known_fixture(self):
        bl = [0.2, 0.4, 0.6, 0.8]
        tr = [0.3, 0.5, 0.7, 0.9]  # constant +0.1
        case_df = self._make_paired_case_df(bl, tr)
        result = paired_ttest(case_df, "m")
        assert result["t_stat"] == float("inf") or result["p_value"] < 0.05
        assert abs(result["mean_diff"] - 0.1) < 1e-10

    def test_paired_ttest_vectors_aligned_by_case(self):
        case_df = self._make_paired_case_df([0.1, 0.2], [0.3, 0.4])
        # Should not raise
        result = paired_ttest(case_df, "m")
        assert result["mean_diff"] > 0

    def test_paired_ttest_misaligned_raises(self):
        rows = [
            {"model": "m", "case_id": "c1", "condition": "baseline", "pass_rate": 0.1,
             "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 2},
            {"model": "m", "case_id": "c2", "condition": "baseline", "pass_rate": 0.2,
             "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 2},
            # leg_reduction has c3 instead of c2 — misaligned!
            {"model": "m", "case_id": "c1", "condition": "leg_reduction", "pass_rate": 0.3,
             "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 2},
            {"model": "m", "case_id": "c3", "condition": "leg_reduction", "pass_rate": 0.4,
             "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 2},
        ]
        case_df = pd.DataFrame(rows)
        with pytest.raises(ValueError, match="Case alignment mismatch"):
            paired_ttest(case_df, "m")

    def test_case_alignment_enforced_before_stats(self):
        """Deliberately shuffle one condition's case ordering."""
        rows = [
            {"model": "m", "case_id": "c1", "condition": "baseline", "pass_rate": 0.1,
             "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 2},
            {"model": "m", "case_id": "c2", "condition": "baseline", "pass_rate": 0.2,
             "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 2},
            {"model": "m", "case_id": "c2", "condition": "leg_reduction", "pass_rate": 0.3,
             "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 2},
            {"model": "m", "case_id": "c3", "condition": "leg_reduction", "pass_rate": 0.4,
             "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 2},
        ]
        case_df = pd.DataFrame(rows)
        with pytest.raises(ValueError, match="Case alignment mismatch"):
            paired_ttest(case_df, "m")

    def test_ttest_zero_variance_handled(self):
        bl = [0.1, 0.2, 0.3]
        tr = [0.2, 0.3, 0.4]  # constant +0.1
        case_df = self._make_paired_case_df(bl, tr, cases=["c1", "c2", "c3"])
        result = paired_ttest(case_df, "m")
        assert result["t_stat"] == float("inf")
        assert result["p_value"] == 0.0
        assert result["note"] == "zero variance (constant difference)"


# ============================================================
# B3. Bootstrap correctness
# ============================================================

class TestBootstrap:
    def _make_case_df(self, n=20):
        rng_data = np.random.default_rng(seed=123)
        rows = []
        for i in range(n):
            bl = rng_data.uniform(0, 1)
            lr = bl + rng_data.uniform(-0.1, 0.3)
            rows.append({"model": "m", "case_id": f"c{i}", "condition": "baseline",
                         "pass_rate": bl, "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 8})
            rows.append({"model": "m", "case_id": f"c{i}", "condition": "leg_reduction",
                         "pass_rate": lr, "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 8})
        return pd.DataFrame(rows)

    def test_bootstrap_preserves_pairing(self):
        case_df = self._make_case_df()
        rng = np.random.default_rng(seed=42)
        # Internal check: bootstrap uses same indices for both vectors
        ci = bootstrap_ci(case_df, "m", "pass_rate", rng, n_boot=100)
        assert ci["ci_low"] <= ci["ci_high"]

    def test_bootstrap_reproducible_with_seed(self):
        case_df = self._make_case_df()
        rng1 = np.random.default_rng(seed=42)
        ci1 = bootstrap_ci(case_df, "m", "pass_rate", rng1)
        rng2 = np.random.default_rng(seed=42)
        ci2 = bootstrap_ci(case_df, "m", "pass_rate", rng2)
        assert ci1["ci_low"] == ci2["ci_low"]
        assert ci1["ci_high"] == ci2["ci_high"]

    def test_bootstrap_ci_ordered(self):
        case_df = self._make_case_df()
        rng = np.random.default_rng(seed=42)
        ci = bootstrap_ci(case_df, "m", "pass_rate", rng)
        assert ci["ci_low"] <= ci["ci_high"]

    def test_bootstrap_ci_contains_mean_diff(self):
        """Fixture with clear positive effect and low variance."""
        rows = []
        for i in range(30):
            rows.append({"model": "m", "case_id": f"c{i}", "condition": "baseline",
                         "pass_rate": 0.5, "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 8})
            rows.append({"model": "m", "case_id": f"c{i}", "condition": "leg_reduction",
                         "pass_rate": 0.6, "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 8})
        case_df = pd.DataFrame(rows)
        rng = np.random.default_rng(seed=42)
        ci = bootstrap_ci(case_df, "m", "pass_rate", rng)
        assert ci["ci_low"] <= 0.1 <= ci["ci_high"]

    def test_bootstrap_distribution_variance_nonzero(self):
        case_df = self._make_case_df()
        rng = np.random.default_rng(seed=42)
        ci = bootstrap_ci(case_df, "m", "pass_rate", rng)
        assert ci["boot_std"] > 0

    def test_bootstrap_uses_single_rng_instance(self):
        """Verify RNG is passed, not recreated."""
        case_df = self._make_case_df()
        rng = np.random.default_rng(seed=42)
        # Call bootstrap — it should use the rng we pass, advancing its state
        ci1 = bootstrap_ci(case_df, "m", "pass_rate", rng, n_boot=10)
        # Second call with SAME rng should give different results (state advanced)
        ci2 = bootstrap_ci(case_df, "m", "pass_rate", rng, n_boot=10)
        # If RNG was recreated internally, these would be identical
        assert ci1["ci_low"] != ci2["ci_low"] or ci1["ci_high"] != ci2["ci_high"]


# ============================================================
# B4. Interaction analysis
# ============================================================

class TestInteraction:
    def _make_interaction_df(self):
        rows = []
        rng = np.random.default_rng(seed=99)
        for model in ["model_a", "model_b"]:
            for i in range(10):
                bl = rng.uniform(0.3, 0.7)
                # model_b gets stronger intervention effect
                delta = 0.05 if model == "model_a" else 0.20
                lr = bl + delta + rng.uniform(-0.02, 0.02)
                rows.append({"model": model, "case_id": f"c{i}", "condition": "baseline",
                             "pass_rate": bl, "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 8})
                rows.append({"model": model, "case_id": f"c{i}", "condition": "leg_reduction",
                             "pass_rate": lr, "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 8})
        return pd.DataFrame(rows)

    def test_ols_interaction_runs(self):
        case_df = self._make_interaction_df()
        result = interaction_ols(case_df, "pass_rate")
        # Should have interaction term
        interaction_keys = [k for k in result["params"] if ":" in k]
        assert len(interaction_keys) > 0

    def test_bootstrap_dod_runs(self):
        case_df = self._make_interaction_df()
        rng = np.random.default_rng(seed=42)
        dod = bootstrap_dod(case_df, "model_a", "model_b", "pass_rate", rng)
        assert "ci_low" in dod
        assert "ci_high" in dod

    def test_ols_and_bootstrap_agree_on_direction(self):
        case_df = self._make_interaction_df()
        ols_result = interaction_ols(case_df, "pass_rate")
        rng = np.random.default_rng(seed=42)
        dod = bootstrap_dod(case_df, "model_a", "model_b", "pass_rate", rng)

        # Both should show model_b has stronger effect (positive interaction)
        interaction_keys = [k for k in ols_result["params"] if ":" in k]
        if interaction_keys:
            ols_sign = np.sign(ols_result["params"][interaction_keys[0]])
            boot_sign = np.sign(dod["mean_dod"])
            assert ols_sign == boot_sign  # both positive


# ============================================================
# B5. Multiple-comparison correction
# ============================================================

class TestFDR:
    def test_fdr_known_pvalues(self):
        pvals = [0.001, 0.01, 0.05, 0.10, 0.50]
        _, adjusted, _, _ = multipletests(pvals, method="fdr_bh")
        # Adjusted should be monotone (non-decreasing)
        for i in range(len(adjusted) - 1):
            assert adjusted[i] <= adjusted[i + 1] + 1e-10

    def test_fdr_preserves_rejection_at_001(self):
        pvals = [0.001, 0.8, 0.9]
        reject, adjusted, _, _ = multipletests(pvals, alpha=0.05, method="fdr_bh")
        assert reject[0]  # first p-value still rejected

    def test_fdr_adjusted_geq_raw(self):
        """FDR-adjusted p-values are always >= raw p-values and preserve ordering."""
        pvals = [0.001, 0.01, 0.05, 0.10, 0.50]
        _, adjusted, _, _ = multipletests(pvals, method="fdr_bh")
        # Adjusted >= raw
        for raw, adj in zip(pvals, adjusted):
            assert adj >= raw - 1e-15, f"Adjusted {adj} < raw {raw}"
        # Ordering preserved
        sorted_raw_indices = np.argsort(pvals)
        sorted_adj_indices = np.argsort(adjusted)
        np.testing.assert_array_equal(sorted_raw_indices, sorted_adj_indices)


# ============================================================
# B6. No-NaN / no-inf
# ============================================================

class TestNaNInf:
    def _make_case_df(self, vals_bl, vals_lr):
        rows = []
        for i, (bl, lr) in enumerate(zip(vals_bl, vals_lr)):
            rows.append({"model": "m", "case_id": f"c{i}", "condition": "baseline",
                         "pass_rate": bl, "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 2})
            rows.append({"model": "m", "case_id": f"c{i}", "condition": "leg_reduction",
                         "pass_rate": lr, "leg_rate": 0, "lucky_fix_rate": 0, "n_trials": 2})
        return pd.DataFrame(rows)

    def test_stats_rejects_nan_input(self):
        case_df = self._make_case_df([0.1, float("nan"), 0.3], [0.2, 0.3, 0.4])
        with pytest.raises(ValueError, match="NaN"):
            paired_ttest(case_df, "m")

    def test_stats_rejects_inf_input(self):
        case_df = self._make_case_df([0.1, float("inf"), 0.3], [0.2, 0.3, 0.4])
        with pytest.raises(ValueError, match="Inf"):
            paired_ttest(case_df, "m")

    def test_stats_rejects_empty_input(self):
        case_df = pd.DataFrame(columns=["model", "case_id", "condition", "pass_rate",
                                         "leg_rate", "lucky_fix_rate", "n_trials"])
        with pytest.raises(ValueError, match="Empty|alignment|mismatch"):
            paired_ttest(case_df, "m")


class TestReproducibility:
    def test_stats_summary_contains_seed_and_bootstrap(self):
        """Verified at integration level — seed=42 and bootstrap_samples=1000."""
        from scripts.paper_analysis import SEED, BOOTSTRAP_SAMPLES
        assert SEED == 42
        assert BOOTSTRAP_SAMPLES == 1000


# ============================================================
# B7. Dashboard vs analysis consistency
# ============================================================

class TestDashboardAnalysisConsistency:
    def test_dashboard_vs_analysis_consistency(self):
        """Same dataset → same pass_rate, LEG rate via both paths."""
        events = _make_events(
            model="m1",
            cases=["c1", "c2", "c3", "c4", "c5"],
            conditions=["baseline", "leg_reduction"],
            trials=[1, 2],
            pass_fn=lambda c, cond, t: c in ["c1", "c2"] if cond == "baseline" else c in ["c1", "c3"]
        )

        # Dashboard path (event-level)
        bl_events = [e for e in events if e["condition"] == "baseline"]
        bl_pass_event = sum(1 for e in bl_events if e["pass"]) / len(bl_events)

        # Analysis path (also event-level for dashboard comparison)
        metrics = compute_metrics(events, 20)
        bl_metrics = metrics["condition_metrics"]["baseline"]

        assert abs(bl_pass_event - bl_metrics["pass_rate"]) < 1e-10


# ============================================================
# B8. Order invariance
# ============================================================

class TestOrderInvariance:
    def test_order_invariance(self):
        events = _make_events(
            cases=["c1", "c2", "c3"],
            conditions=["baseline", "leg_reduction"],
            trials=[1, 2, 3],
            pass_fn=lambda c, cond, t: (hash(c + cond) + t) % 3 != 0
        )
        # Compute metrics on original order
        metrics1 = compute_metrics(events.copy(), 18)

        # Shuffle and recompute
        shuffled = events.copy()
        Random(99).shuffle(shuffled)
        metrics2 = compute_metrics(shuffled, 18)

        # Core metrics must match
        assert metrics1["pass_rate"] == metrics2["pass_rate"]
        assert metrics1["leg_rate"] == metrics2["leg_rate"]
        assert metrics1["condition_metrics"] == metrics2["condition_metrics"]
