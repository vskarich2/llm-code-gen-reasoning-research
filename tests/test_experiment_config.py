"""L-2: Experiment Configuration Verification.

Validates that experiment configuration is correct BEFORE any API calls.
Catches: wrong case file, wrong conditions, wrong models, malformed prompts,
degenerate inputs, missing files.
"""

import json
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


# ============================================================
# HELPERS
# ============================================================

def _load_cases():
    cases_path = BASE / "cases_v2.json"
    return json.loads(cases_path.read_text(encoding="utf-8"))


def _load_case_with_contents(case):
    """Populate code_files_contents for a case."""
    case = dict(case)
    case["code_files_contents"] = {}
    for rel in case["code_files"]:
        case["code_files_contents"][rel] = (BASE / rel).read_text(encoding="utf-8")
    return case


# ============================================================
# CONFIG SNAPSHOT TESTS
# ============================================================

class TestConfigSnapshot:
    """Validate that the LEG ablation config matches expected values."""

    def test_cases_v2_has_expected_count(self):
        cases = _load_cases()
        assert len(cases) == 58, f"Expected 58 cases, got {len(cases)}"

    def test_no_duplicate_case_ids(self):
        cases = _load_cases()
        ids = [c["id"] for c in cases]
        dupes = [cid for cid in ids if ids.count(cid) > 1]
        assert len(set(dupes)) == 0, f"Duplicate case IDs: {set(dupes)}"

    def test_conditions_are_valid(self):
        from constants import VALID_CONDITIONS
        for cond in ["baseline", "leg_reduction"]:
            assert cond in VALID_CONDITIONS, f"{cond} not in VALID_CONDITIONS"

    def test_each_case_has_required_fields(self):
        cases = _load_cases()
        required = {"id", "family", "difficulty", "code_files", "failure_mode"}
        for c in cases:
            missing = required - set(c.keys())
            assert not missing, f"Case {c.get('id', '?')} missing: {missing}"

    def test_reference_fix_exists_for_every_case(self):
        cases = _load_cases()
        missing = []
        for c in cases:
            ref_path = BASE / "reference_fixes" / f"{c['id']}.py"
            if not ref_path.exists():
                missing.append(c["id"])
        assert not missing, f"Missing reference fixes: {missing}"


# ============================================================
# DEGENERATE INPUT TESTS
# ============================================================

class TestNoDegenerateInputs:
    """Catch empty, truncated, or malformed case files."""

    def test_case_count_above_minimum(self):
        cases = _load_cases()
        assert len(cases) >= 10, f"Only {len(cases)} cases — suspiciously small"

    def test_all_code_files_exist_and_nonempty(self):
        cases = _load_cases()
        problems = []
        for c in cases:
            for rel in c["code_files"]:
                path = BASE / rel
                if not path.exists():
                    problems.append(f"{c['id']}: {rel} does not exist")
                elif path.stat().st_size == 0:
                    problems.append(f"{c['id']}: {rel} is empty")
        assert not problems, f"Code file problems:\n" + "\n".join(problems)

    def test_each_case_has_code_files(self):
        cases = _load_cases()
        empty = [c["id"] for c in cases if not c.get("code_files")]
        assert not empty, f"Cases with no code_files: {empty}"

    def test_families_have_test_files(self):
        cases = _load_cases()
        missing = []
        families_checked = set()
        for c in cases:
            fam = c.get("family", "")
            if fam in families_checked:
                continue
            families_checked.add(fam)
            test_path = BASE / "tests_v2" / f"test_{fam}.py"
            if not test_path.exists():
                missing.append(fam)
        assert not missing, f"Missing test files for families: {missing}"


# ============================================================
# PROMPT TEMPLATE TESTS
# ============================================================

class TestPromptTemplate:
    """Verify prompts are well-formed and contain expected content."""

    @pytest.fixture
    def canary_case(self):
        cases = _load_cases()
        c = [x for x in cases if x["id"] == "alias_config_a"][0]
        return _load_case_with_contents(c)

    def test_baseline_prompt_contains_task(self, canary_case):
        from execution import build_prompt
        prompt, _ = build_prompt(canary_case, "baseline")
        assert isinstance(prompt, str)
        assert len(prompt) > 100, f"Prompt suspiciously short: {len(prompt)} chars"
        task_snippet = canary_case["task"][:50]
        assert task_snippet in prompt, "Task description not found in prompt"

    def test_baseline_prompt_contains_code(self, canary_case):
        from execution import build_prompt
        prompt, _ = build_prompt(canary_case, "baseline")
        for content in canary_case["code_files_contents"].values():
            snippet = content.strip()[:50]
            assert snippet in prompt, f"Code content not found in prompt: {snippet[:30]}..."

    def test_leg_reduction_prompt_is_different(self, canary_case):
        """leg_reduction builds its own prompt via build_leg_reduction_prompt, not build_prompt."""
        from execution import build_prompt
        from leg_reduction import build_leg_reduction_prompt
        bl_prompt, _ = build_prompt(canary_case, "baseline")
        lr_prompt = build_leg_reduction_prompt(
            canary_case["task"], canary_case["code_files_contents"]
        )
        assert bl_prompt != lr_prompt, "Baseline and leg_reduction prompts are identical — intervention not applied"

    def test_leg_reduction_prompt_nonempty(self, canary_case):
        from leg_reduction import build_leg_reduction_prompt
        prompt = build_leg_reduction_prompt(
            canary_case["task"], canary_case["code_files_contents"]
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 100, f"LEG reduction prompt suspiciously short: {len(prompt)} chars"
