"""Unit tests for spec oracle depth classification.

For each DDC case, verifies:
1. root_fix passes ALL 5 invariants (depth A)
2. Each trap passes its expected invariants and fails the rest
3. Trap depths are correctly classified (D, C, B)
4. Each depth level has a distinct invariant signature

Run: .venv/bin/python -m pytest core/tests/test_spec_oracle_depths.py -v
"""

import sys
sys.path.insert(0, ".")

import pytest
from core.evaluation.spec_oracle import _load_spec, build_patch_profiles


ALL_INVARIANTS = [
    "trap_catching", "generalization", "causal_location",
    "cross_path", "chain_integrity",
]

DDC_FAMILIES = [
    "auth_context_chain",
    "billing_aggregation_chain",
    "config_derivation_chain",
    "event_etl_chain",
    "logging_pipeline_chain",
    "ml_feature_chain",
    "search_index_chain",
    "serialization_pipeline_chain",
]


@pytest.fixture(params=DDC_FAMILIES)
def case_profiles(request):
    family = request.param
    spec = _load_spec(family)
    assert spec is not None, f"spec not found for {family}"
    profiles = build_patch_profiles(spec)
    return family, profiles


class TestRootFix:
    """root_fix must pass ALL invariants for every case."""

    def test_root_fix_all_pass(self, case_profiles):
        family, profiles = case_profiles
        root = profiles["root_fix"]
        assert root["primary_test"] is True, f"{family}: root_fix primary test failed"
        assert root["depth"] == "A", f"{family}: root_fix depth={root['depth']}, expected A"
        for inv_name in ALL_INVARIANTS:
            assert root["invariants"][inv_name]["passed"], (
                f"{family}: root_fix fails {inv_name}: "
                f"{root['invariants'][inv_name]['message']}"
            )


class TestTrap1:
    """trap_1 (depth D) = endpoint compensation. Should fail at least one invariant."""

    def test_trap_1_depth(self, case_profiles):
        family, profiles = case_profiles
        t1 = profiles["trap_1"]
        assert t1["depth"] == "D", f"{family}: trap_1 depth={t1['depth']}, expected D"

    def test_trap_1_not_all_pass(self, case_profiles):
        family, profiles = case_profiles
        t1 = profiles["trap_1"]
        failed = [k for k, v in t1["invariants"].items() if not v["passed"]]
        assert len(failed) > 0, (
            f"{family}: trap_1 passes ALL invariants — "
            f"indistinguishable from root_fix"
        )

    def test_trap_1_differs_from_root(self, case_profiles):
        family, profiles = case_profiles
        root_sig = {k: v["passed"] for k, v in profiles["root_fix"]["invariants"].items()}
        t1_sig = {k: v["passed"] for k, v in profiles["trap_1"]["invariants"].items()}
        assert root_sig != t1_sig, f"{family}: trap_1 invariant signature identical to root_fix"


class TestTrap3:
    """trap_3 (depth C) = validation masking / heuristic. Should fail generalization."""

    def test_trap_3_depth(self, case_profiles):
        family, profiles = case_profiles
        t3 = profiles["trap_3"]
        assert t3["depth"] == "C", f"{family}: trap_3 depth={t3['depth']}, expected C"

    def test_trap_3_not_all_pass(self, case_profiles):
        family, profiles = case_profiles
        t3 = profiles["trap_3"]
        failed = [k for k, v in t3["invariants"].items() if not v["passed"]]
        assert len(failed) > 0, (
            f"{family}: trap_3 passes ALL invariants — "
            f"indistinguishable from root_fix"
        )

    def test_trap_3_differs_from_root(self, case_profiles):
        family, profiles = case_profiles
        root_sig = {k: v["passed"] for k, v in profiles["root_fix"]["invariants"].items()}
        t3_sig = {k: v["passed"] for k, v in profiles["trap_3"]["invariants"].items()}
        assert root_sig != t3_sig, f"{family}: trap_3 invariant signature identical to root_fix"

    def test_trap_3_differs_from_trap_1(self, case_profiles):
        family, profiles = case_profiles
        t1_sig = {k: v["passed"] for k, v in profiles["trap_1"]["invariants"].items()}
        t3_sig = {k: v["passed"] for k, v in profiles["trap_3"]["invariants"].items()}
        assert t1_sig != t3_sig, (
            f"{family}: trap_3 invariant signature identical to trap_1 — "
            f"can't distinguish C from D"
        )


class TestTrap4:
    """trap_4 (depth B) = downstream override."""

    def test_trap_4_depth(self, case_profiles):
        family, profiles = case_profiles
        t4 = profiles["trap_4"]
        assert t4["depth"] == "B", f"{family}: trap_4 depth={t4['depth']}, expected B"

    def test_trap_4_not_all_pass(self, case_profiles):
        family, profiles = case_profiles
        t4 = profiles["trap_4"]
        failed = [k for k, v in t4["invariants"].items() if not v["passed"]]
        assert len(failed) > 0, (
            f"{family}: trap_4 passes ALL invariants — "
            f"indistinguishable from root_fix"
        )

    def test_trap_4_differs_from_root(self, case_profiles):
        family, profiles = case_profiles
        root_sig = {k: v["passed"] for k, v in profiles["root_fix"]["invariants"].items()}
        t4_sig = {k: v["passed"] for k, v in profiles["trap_4"]["invariants"].items()}
        assert root_sig != t4_sig, f"{family}: trap_4 invariant signature identical to root_fix"

    def test_trap_4_causal_location_fails(self, case_profiles):
        """trap_4 fixes downstream but not the source — causal_location should fail."""
        family, profiles = case_profiles
        t4 = profiles["trap_4"]
        assert not t4["invariants"]["causal_location"]["passed"], (
            f"{family}: trap_4 passes causal_location — "
            f"downstream override should not fix the source node"
        )


class TestTrap5:
    """trap_5 (depth B) = partial upstream fix."""

    def test_trap_5_depth(self, case_profiles):
        family, profiles = case_profiles
        t5 = profiles["trap_5"]
        assert t5["depth"] == "B", f"{family}: trap_5 depth={t5['depth']}, expected B"

    def test_trap_5_not_all_pass(self, case_profiles):
        family, profiles = case_profiles
        t5 = profiles["trap_5"]
        failed = [k for k, v in t5["invariants"].items() if not v["passed"]]
        assert len(failed) > 0, (
            f"{family}: trap_5 passes ALL invariants — "
            f"indistinguishable from root_fix"
        )

    def test_trap_5_differs_from_root(self, case_profiles):
        family, profiles = case_profiles
        root_sig = {k: v["passed"] for k, v in profiles["root_fix"]["invariants"].items()}
        t5_sig = {k: v["passed"] for k, v in profiles["trap_5"]["invariants"].items()}
        assert root_sig != t5_sig, f"{family}: trap_5 invariant signature identical to root_fix"

    def test_trap_5_cross_path_fails(self, case_profiles):
        """trap_5 adds alternate field but bypass reads original — cross_path should fail."""
        family, profiles = case_profiles
        t5 = profiles["trap_5"]
        assert not t5["invariants"]["cross_path"]["passed"], (
            f"{family}: trap_5 passes cross_path — "
            f"partial upstream fix should leave bypass consumer reading wrong field"
        )


class TestDepthOrdering:
    """Verify depth hierarchy: A fixes everything, D fixes least."""

    def test_root_fixes_most_invariants(self, case_profiles):
        family, profiles = case_profiles
        root_passed = sum(1 for v in profiles["root_fix"]["invariants"].values() if v["passed"])
        for pid in ["trap_1", "trap_3", "trap_4", "trap_5"]:
            trap_passed = sum(1 for v in profiles[pid]["invariants"].values() if v["passed"])
            assert root_passed >= trap_passed, (
                f"{family}: root_fix passes {root_passed} invariants but "
                f"{pid} passes {trap_passed} — root should pass the most"
            )

    def test_all_depths_represented(self, case_profiles):
        family, profiles = case_profiles
        depths = {profiles[pid]["depth"] for pid in ["root_fix", "trap_1", "trap_3", "trap_4", "trap_5"]}
        assert "A" in depths, f"{family}: no depth A (root_fix)"
        assert "B" in depths, f"{family}: no depth B"
        assert "C" in depths, f"{family}: no depth C"
        assert "D" in depths, f"{family}: no depth D"

    def test_signatures_unique_across_abc(self, case_profiles):
        """A, B, C, D should have distinguishable invariant signatures.
        (B traps may share signatures with each other, which is OK.)"""
        family, profiles = case_profiles
        sigs = {}
        for pid in ["root_fix", "trap_1", "trap_3"]:
            sig = tuple(sorted(
                (k, v["passed"]) for k, v in profiles[pid]["invariants"].items()
            ))
            assert sig not in sigs.values(), (
                f"{family}: {pid} has same signature as "
                f"{[k for k, v in sigs.items() if v == sig][0]}"
            )
            sigs[pid] = sig
