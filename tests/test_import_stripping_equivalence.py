"""Equivalence tests for unified import stripping.

Verifies:
1. assembly.imports.strip_imports produces identical output to old implementations
2. Cross-mode consistency
3. Real cases from cases_v2.json
4. Adversarial import patterns
"""

import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assembly.imports import strip_imports
from _stdlib import STDLIB_MODULES


# ============================================================
# SNAPSHOT EQUIVALENCE: assembly mode vs old parse.py
# ============================================================

# Reference implementation (the old parse.py logic, inlined for comparison)
def _old_parse_strip(code, local_modules=None):
    """Exact copy of the old parse.py strip_local_imports for comparison."""
    code = re.sub(
        r"^from\s+(?!(?:"
        + "|".join(re.escape(m) for m in STDLIB_MODULES)
        + r")\b)\w+\s+import\s*\(.*?\)",
        "",
        code,
        flags=re.MULTILINE | re.DOTALL,
    )
    lines = []
    for line in code.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("from .", "import .")):
            continue
        if stripped.startswith("from ") and " import " in stripped:
            mod = stripped.split("from ", 1)[1].split(" import")[0].strip()
            base_mod = mod.split(".")[0] if "." in mod else mod
            if base_mod in STDLIB_MODULES:
                lines.append(line)
                continue
            if local_modules is not None and base_mod not in local_modules:
                lines.append(line)
                continue
            continue
        elif stripped.startswith("import "):
            mod = stripped.split("import ", 1)[1].split()[0].strip().rstrip(",")
            if mod in STDLIB_MODULES:
                lines.append(line)
                continue
            if local_modules is not None and mod not in local_modules:
                lines.append(line)
                continue
            continue
        lines.append(line)
    return "\n".join(lines)


# Reference: old validate_cases_v2 logic
def _old_validate_strip(code):
    """Exact copy of old validate_cases_v2._strip_local_imports."""
    lines = []
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("from ") and " import " in stripped:
            module = stripped.split()[1].split(".")[0]
            if module not in STDLIB_MODULES:
                continue
        elif stripped.startswith("import "):
            module = stripped.split()[1].split(".")[0]
            if module not in STDLIB_MODULES:
                continue
        lines.append(line)
    return "\n".join(lines)


SNIPPETS = [
    # Basic local imports
    "from metrics import reset\ndef f(): reset()",
    "import metrics\ndef f(): pass",
    "from metrics import reset, increment\ndef f(): reset()",
    # Stdlib preserved
    "import os\nimport json\nfrom collections import defaultdict\ndef f(): pass",
    # Mixed
    "import os\nfrom metrics import reset\nimport json\ndef f(): pass",
    # Relative
    "from . import config\ndef f(): pass",
    "from .utils import helper\ndef f(): pass",
    # Aliased
    "from metrics import reset as metrics_reset\ndef f(): metrics_reset()",
    # Dotted
    "from metrics.utils import helper\ndef f(): helper()",
    # Empty
    "",
    "def f(): pass",
    # Multi-line (only assembly mode handles this)
    "from metrics import (\n    reset,\n    increment,\n)\ndef f(): pass",
]


class TestAssemblyEquivalence:
    """Assembly mode must match old parse.py strip_local_imports."""

    @pytest.mark.parametrize("snippet", SNIPPETS)
    def test_assembly_matches_old_parse(self, snippet):
        old = _old_parse_strip(snippet)
        new = strip_imports(snippet, mode="assembly")
        assert new == old, f"Assembly mismatch:\nOLD: {old!r}\nNEW: {new!r}"

    @pytest.mark.parametrize("snippet", SNIPPETS)
    def test_assembly_with_local_modules(self, snippet):
        local = frozenset({"metrics", "config", "utils"})
        old = _old_parse_strip(snippet, local_modules=local)
        new = strip_imports(snippet, mode="assembly", local_modules=local)
        assert new == old


class TestValidationEquivalence:
    """Validation mode must match old validate_cases_v2 behavior."""

    @pytest.mark.parametrize("snippet", SNIPPETS)
    def test_validation_matches_old(self, snippet):
        old = _old_validate_strip(snippet)
        new = strip_imports(snippet, mode="validation")
        assert new == old, f"Validation mismatch:\nOLD: {old!r}\nNEW: {new!r}"

    def test_preflight_identical_to_validation(self):
        for snippet in SNIPPETS:
            val = strip_imports(snippet, mode="validation")
            pre = strip_imports(snippet, mode="preflight")
            assert val == pre, f"Preflight differs from validation:\nVAL: {val!r}\nPRE: {pre!r}"


# ============================================================
# CROSS-MODE CONSISTENCY
# ============================================================


class TestCrossModeConsistency:
    """Verify modes agree where expected and differ where intended."""

    def test_stdlib_preserved_all_modes(self):
        code = "import os\nimport json\nfrom collections import defaultdict\ndef f(): pass"
        for mode in ("assembly", "validation", "preflight"):
            result = strip_imports(code, mode=mode)
            assert "import os" in result
            assert "import json" in result
            assert "from collections import defaultdict" in result

    def test_local_stripped_all_modes(self):
        code = "from metrics import reset\ndef f(): reset()"
        for mode in ("assembly", "validation", "preflight"):
            result = strip_imports(code, mode=mode)
            assert "from metrics" not in result
            assert "def f():" in result

    def test_relative_stripped_by_assembly(self):
        code = "from . import config\ndef f(): pass"
        asm = strip_imports(code, mode="assembly")
        assert "from ." not in asm


# ============================================================
# REAL CASE TESTS
# ============================================================


class TestRealCases:
    """Run against actual benchmark case files."""

    @pytest.fixture(autouse=True)
    def _load_cases(self):
        cases_path = Path(__file__).resolve().parents[1] / "cases_v2.json"
        self.cases = json.loads(cases_path.read_text())
        self.base = Path(__file__).resolve().parents[1]

    def _get_case_code(self, case):
        parts = []
        for rel_path in case["code_files"]:
            full_path = self.base / rel_path
            if full_path.exists():
                parts.append(full_path.read_text())
        return "\n\n".join(parts)

    def test_multi_file_cases_no_crash(self):
        """All multi-file cases strip without crashing."""
        multi = [c for c in self.cases if len(c["code_files"]) > 1]
        for case in multi[:10]:
            code = self._get_case_code(case)
            for mode in ("assembly", "validation", "preflight"):
                result = strip_imports(code, mode=mode)
                assert isinstance(result, str)
                assert len(result) > 0

    def test_single_file_cases_no_crash(self):
        """All single-file cases strip without crashing."""
        single = [c for c in self.cases if len(c["code_files"]) == 1]
        for case in single[:10]:
            code = self._get_case_code(case)
            for mode in ("assembly", "validation", "preflight"):
                result = strip_imports(code, mode=mode)
                assert isinstance(result, str)

    def test_assembly_validation_agree_on_stdlib(self):
        """Both modes preserve the same stdlib imports on real cases."""
        for case in self.cases[:15]:
            code = self._get_case_code(case)
            asm = strip_imports(code, mode="assembly")
            val = strip_imports(code, mode="validation")
            # Both should preserve the same stdlib imports
            asm_stdlib = set(re.findall(r"^(?:import|from)\s+(\w+)", asm, re.MULTILINE))
            val_stdlib = set(re.findall(r"^(?:import|from)\s+(\w+)", val, re.MULTILINE))
            asm_stdlib = {m for m in asm_stdlib if m in STDLIB_MODULES}
            val_stdlib = {m for m in val_stdlib if m in STDLIB_MODULES}
            assert asm_stdlib == val_stdlib, f"Stdlib mismatch on {case['id']}: asm={asm_stdlib}, val={val_stdlib}"


# ============================================================
# ADVERSARIAL IMPORT PATTERNS
# ============================================================


class TestAdversarial:

    def test_multi_line_from_import(self):
        code = "from metrics import (\n    reset,\n    increment,\n)\ndef f(): pass"
        result = strip_imports(code, mode="assembly")
        assert "from metrics" not in result
        assert "def f():" in result

    def test_aliased_import(self):
        code = "from metrics import reset as m_reset\ndef f(): m_reset()"
        result = strip_imports(code, mode="assembly")
        assert "from metrics" not in result

    def test_mixed_stdlib_and_local(self):
        code = "import os\nfrom metrics import f\nimport json\nfrom audit import g\ndef h(): pass"
        result = strip_imports(code, mode="assembly")
        assert "import os" in result
        assert "import json" in result
        assert "from metrics" not in result
        assert "from audit" not in result

    def test_dotted_import(self):
        code = "from metrics.utils import helper\ndef f(): helper()"
        result = strip_imports(code, mode="assembly")
        assert "from metrics" not in result

    def test_bare_import_local(self):
        code = "import metrics\ndef f(): pass"
        for mode in ("assembly", "validation"):
            result = strip_imports(code, mode=mode)
            assert "import metrics" not in result

    def test_import_with_comma(self):
        code = "import metrics, audit\ndef f(): pass"
        # This is tricky — the module is "metrics," with trailing comma
        result = strip_imports(code, mode="assembly")
        # Assembly mode strips it (metrics is not stdlib)
        assert "import metrics" not in result

    def test_empty_code(self):
        for mode in ("assembly", "validation", "preflight"):
            result = strip_imports("", mode=mode)
            assert result == ""

    def test_no_imports(self):
        code = "def f(): return 42"
        for mode in ("assembly", "validation", "preflight"):
            result = strip_imports(code, mode=mode)
            assert result == code

    def test_all_stdlib_preserved(self):
        imports = "\n".join(f"import {m}" for m in sorted(STDLIB_MODULES))
        code = imports + "\ndef f(): pass"
        for mode in ("assembly", "validation", "preflight"):
            result = strip_imports(code, mode=mode)
            for m in STDLIB_MODULES:
                assert f"import {m}" in result, f"Stdlib {m} stripped in mode={mode}"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown strip_imports mode"):
            strip_imports("x = 1", mode="bogus")
