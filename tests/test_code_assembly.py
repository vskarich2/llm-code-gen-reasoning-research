"""Tests for code_assembly.py — the single source of truth for code assembly."""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from code_assembly import CodeAssembler, AssemblyResult, assemble


def _make_case(files: dict, reference_func: str = ""):
    """Helper: build a minimal case dict for assembly."""
    code_files = list(files.keys())
    return {
        "id": "test_case",
        "code_files": code_files,
        "code_files_contents": files,
        "failure_mode": "TEST",
        "reference_fix": {"function": reference_func} if reference_func else {},
    }


# ============================================================
# SINGLE FILE (no assembly)
# ============================================================


class TestSingleFile:

    def test_single_file_passthrough(self):
        case = _make_case({"a.py": "def f(): return 1"})
        r = assemble("def f(): return 2", case)
        assert r.status == "SUCCESS"
        assert r.assembly_used is False
        assert "def f(): return 2" in r.code

    def test_single_file_strips_local_imports(self):
        case = _make_case({"a.py": "def f(): pass"})
        r = assemble("from a import f\ndef g(): return f()", case, mode="safe")
        assert r.status == "SUCCESS"
        assert "from a import f" not in r.code
        assert "def g():" in r.code


# ============================================================
# MULTI FILE — BASIC ASSEMBLY
# ============================================================


class TestMultiFileBasic:

    def test_originals_first_model_last(self):
        case = _make_case({
            "a.py": "X = 1",
            "b.py": "Y = 2",
        })
        r = assemble("X = 99", case)
        assert r.status == "SUCCESS"
        assert r.assembly_used is True
        # Original X=1 appears before model X=99
        pos_orig = r.code.find("X = 1")
        pos_model = r.code.find("X = 99")
        assert pos_orig < pos_model

    def test_duplicate_defs_detected(self):
        case = _make_case({
            "a.py": "def f(): return 1",
            "b.py": "def g(): return 2",
        })
        r = assemble("def f(): return 99", case)
        assert "f" in r.duplicate_defs
        assert r.assembly_risky is True

    def test_all_unchanged_produces_originals(self):
        case = _make_case({
            "a.py": "def f(): return 1",
            "b.py": "def g(): return 2",
        })
        # Model produced empty code (all UNCHANGED)
        r = assemble("", case)
        # Should still have original content
        assert r.assembly_used is True

    def test_rename_detection(self):
        case = _make_case(
            {"a.py": "def create_config(): pass", "b.py": "X = 1"},
            reference_func="create_config",
        )
        r = assemble("def make_config(): pass", case)
        assert r.rename_error is True
        assert "create_config" in r.expected_func


# ============================================================
# IMPORT REWRITING — ALIASES
# ============================================================


class TestAliasRewriting:

    def test_from_import_as_rewritten(self):
        """from metrics import reset as metrics_reset → rename metrics_reset to reset."""
        case = _make_case({
            "metrics.py": "def reset(): pass\ndef increment(v): pass",
            "processor.py": "from metrics import increment",
        })
        model_code = (
            "from metrics import reset as metrics_reset, increment\n"
            "def process():\n"
            "    metrics_reset()\n"
            "    increment(1)\n"
        )
        r = assemble(model_code, case, mode="safe")
        assert r.status == "SUCCESS"
        # The import should be removed
        assert "from metrics import" not in r.code
        # metrics_reset should be renamed to reset
        assert "metrics_reset()" not in r.code
        assert "reset()" in r.code
        # increment should still be there
        assert "increment(1)" in r.code

    def test_ambiguous_alias_still_works(self):
        """Even if Y exists elsewhere, the rename Z→Y is still correct
        because Y is the real function name in the concat namespace."""
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = (
            "from metrics import reset as m_reset\n"
            "def process():\n"
            "    m_reset()\n"
        )
        r = assemble(model_code, case, mode="safe")
        assert "m_reset()" not in r.code
        assert "reset()" in r.code

    def test_multiple_aliases_in_one_import(self):
        case = _make_case({
            "inventory.py": "def reserve(): pass\ndef release(): pass\ndef reset(): pass",
            "main.py": "pass",
        })
        model_code = (
            "from inventory import reserve, release, reset as inv_reset\n"
            "def order():\n"
            "    reserve()\n"
            "    inv_reset()\n"
        )
        r = assemble(model_code, case, mode="safe")
        assert "from inventory" not in r.code
        assert "inv_reset()" not in r.code
        assert "reset()" in r.code
        assert "reserve()" in r.code


# ============================================================
# IMPORT REWRITING — MODULE-QUALIFIED ACCESS
# ============================================================


class TestModuleQualified:

    def test_import_x_with_attr_access_resolved(self):
        """import metrics; metrics.reset() — resolved via namespace synthesis."""
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = (
            "import metrics\n"
            "def process():\n"
            "    metrics.reset()\n"
        )
        r = assemble(model_code, case, mode="safe")
        assert r.status == "SUCCESS"
        # Import removed, namespace synthesized
        assert "import metrics" not in r.code
        assert "_T3_NS" in r.code or "SimpleNamespace" in r.code
        assert len(r.qualified_imports_resolved) > 0

    def test_import_x_no_attr_access_removed(self):
        """import metrics with no metrics.* usage — safe to remove."""
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = (
            "import metrics\n"
            "def process():\n"
            "    reset()\n"
        )
        r = assemble(model_code, case, mode="safe")
        assert "import metrics" not in r.code
        assert "reset()" in r.code

    def test_import_x_as_y_with_attr_resolved(self):
        """import metrics as _m; _m.reset() — resolved via namespace synthesis."""
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = (
            "import metrics as _m\n"
            "def process():\n"
            "    _m.reset()\n"
        )
        r = assemble(model_code, case, mode="safe")
        assert r.status == "SUCCESS"
        assert "import metrics" not in r.code
        assert "_m = " in r.code


# ============================================================
# STAR IMPORTS AND RELATIVE IMPORTS
# ============================================================


class TestStarAndRelative:

    def test_star_import_removed(self):
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = "from metrics import *\ndef process(): reset()\n"
        r = assemble(model_code, case, mode="safe")
        assert "from metrics import *" not in r.code
        assert "reset()" in r.code

    def test_relative_import_removed(self):
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = "from . import metrics\ndef process(): pass\n"
        r = assemble(model_code, case, mode="safe")
        assert "from . import" not in r.code

    def test_stdlib_imports_preserved(self):
        case = _make_case({
            "a.py": "pass",
            "b.py": "pass",
        })
        model_code = "import os\nimport json\nfrom collections import defaultdict\ndef f(): pass\n"
        r = assemble(model_code, case, mode="safe")
        assert "import os" in r.code
        assert "import json" in r.code
        assert "from collections import defaultdict" in r.code


# ============================================================
# SYNTAX ERRORS
# ============================================================


class TestSyntaxErrors:

    def test_model_syntax_error_reported(self):
        case = _make_case({
            "a.py": "def f(): return 1",
            "b.py": "def g(): return 2",
        })
        r = assemble("def f(\n    broken syntax", case)
        assert r.status == "SYNTAX_ERROR" or "syntax" in " ".join(r.warnings).lower()

    def test_syntax_error_in_original_warned(self):
        case = _make_case({
            "a.py": "def f(:\n    broken",
            "b.py": "def g(): return 2",
        })
        r = assemble("def h(): return 3", case)
        # Should still attempt assembly (original files may have artifacts)


# ============================================================
# NORMALIZATION
# ============================================================


class TestNormalization:

    def test_markdown_fences_stripped(self):
        case = _make_case({
            "a.py": "X = 1",
            "b.py": "Y = 2",
        })
        model_code = "```python\ndef f(): return 42\n```"
        r = assemble(model_code, case)
        assert "```" not in r.code
        assert "def f(): return 42" in r.code

    def test_escaped_newlines_unescaped(self):
        case = _make_case({
            "a.py": "X = 1",
            "b.py": "Y = 2",
        })
        model_code = "def f():\\n    return 42"
        r = assemble(model_code, case)
        assert "\\n" not in r.code
        assert "return 42" in r.code


# ============================================================
# COMPAT MODE
# ============================================================


class TestCompatMode:

    def test_compat_strips_local_imports(self):
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = "from metrics import reset\ndef process(): reset()\n"
        r = assemble(model_code, case, mode="compat")
        assert "from metrics import reset" not in r.code
        assert "reset()" in r.code

    def test_compat_preserves_stdlib(self):
        case = _make_case({
            "metrics.py": "def f(): pass",
            "processor.py": "pass",
        })
        model_code = "import os\nfrom metrics import f\ndef g(): pass\n"
        r = assemble(model_code, case, mode="compat")
        assert "import os" in r.code
        assert "from metrics" not in r.code

    def test_compat_does_not_rename_aliases(self):
        """Compat mode has the old bug — aliases are NOT renamed."""
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = "from metrics import reset as m_reset\ndef f(): m_reset()\n"
        r = assemble(model_code, case, mode="compat")
        # Compat strips the import but does NOT rename
        assert "from metrics" not in r.code
        # m_reset is still there (the old bug)
        assert "m_reset()" in r.code


# ============================================================
# COLLISION DETECTION
# ============================================================


class TestCollisions:

    def test_model_overriding_original_is_allowed(self):
        case = _make_case({
            "a.py": "def f(): return 1",
            "b.py": "def g(): return 2",
        })
        r = assemble("def f(): return 99", case)
        assert "f" in r.duplicate_defs
        assert r.status == "SUCCESS"  # Allowed — model override

    def test_assembly_result_has_provenance(self):
        case = _make_case({
            "a.py": "def f(): return 1",
            "b.py": "def g(): return 2",
        })
        r = assemble("def f(): return 99", case)
        assert r.sources["model_only"] is False
        assert "f" in r.sources["overridden"]


# ============================================================
# IDEMPOTENCY
# ============================================================


class TestIdempotency:

    def test_double_assembly_same_result(self):
        case = _make_case({
            "metrics.py": "def reset(): pass\ndef increment(v): pass",
            "processor.py": "from metrics import increment",
        })
        model_code = "from metrics import reset as m_reset\ndef process(): m_reset()\n"
        r1 = assemble(model_code, case, mode="safe")
        r2 = assemble(model_code, case, mode="safe")
        assert r1.code == r2.code
        assert r1.status == r2.status


# ============================================================
# DETERMINISM
# ============================================================


class TestDeterminism:

    def test_same_input_same_output(self):
        case = _make_case({
            "a.py": "X = 1\ndef f(): return X",
            "b.py": "Y = 2\ndef g(): return Y",
        })
        model_code = "def f(): return 42"
        results = [assemble(model_code, case, mode="safe") for _ in range(5)]
        codes = [r.code for r in results]
        assert len(set(codes)) == 1  # All identical


# ============================================================
# QUALIFIED IMPORT RESOLUTION
# ============================================================


class TestQualifiedImports:

    def test_import_x_attr_resolved(self):
        """import metrics; metrics.reset() → namespace synthesized."""
        case = _make_case({
            "metrics.py": "def reset(): pass\ndef increment(v): pass",
            "processor.py": "pass",
        })
        model_code = "import metrics\ndef process():\n    metrics.reset()\n    metrics.increment(1)\n"
        r = assemble(model_code, case, mode="safe")
        assert r.status == "SUCCESS", f"Expected SUCCESS, got {r.status}: {r.errors}"
        assert "import metrics" not in r.code
        assert "SimpleNamespace" in r.code or "_T3_NS" in r.code
        assert "metrics = " in r.code
        assert len(r.qualified_imports_resolved) > 0

    def test_import_x_as_y_resolved(self):
        """import metrics as m; m.reset() → namespace with alias."""
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = "import metrics as m\ndef process():\n    m.reset()\n"
        r = assemble(model_code, case, mode="safe")
        assert r.status == "SUCCESS", f"Expected SUCCESS, got {r.status}: {r.errors}"
        assert "m = " in r.code
        assert len(r.qualified_imports_resolved) > 0

    def test_constant_access_resolved(self):
        """import metrics; x = metrics.DEFAULT → constant resolved."""
        case = _make_case({
            "metrics.py": "DEFAULT = 42\ndef reset(): pass",
            "processor.py": "pass",
        })
        model_code = "import metrics\ndef process():\n    return metrics.DEFAULT\n"
        r = assemble(model_code, case, mode="safe")
        assert r.status == "SUCCESS"
        assert "DEFAULT" in r.code

    def test_missing_symbol_fails(self):
        """import metrics; metrics.nonexistent() → REWRITE_ERROR."""
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = "import metrics\ndef process():\n    metrics.nonexistent()\n"
        r = assemble(model_code, case, mode="safe")
        assert r.status == "REWRITE_ERROR"
        assert any("nonexistent" in e for e in r.qualified_imports_failed)

    def test_dynamic_access_keeps_import(self):
        """getattr(metrics, 'reset') → import kept (cannot resolve dynamically).

        The import is kept, which will fail at runtime with ModuleNotFoundError.
        This is correct: we surface the error rather than silently corrupting bindings.
        """
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = "import metrics\ndef process():\n    return getattr(metrics, 'reset')\n"
        r = assemble(model_code, case, mode="safe")
        # Import is KEPT — dynamic access blocks resolution
        assert "import metrics" in r.code
        assert any("dynamic" in w.lower() or "getattr" in w.lower() for w in r.warnings)

    def test_collision_fails(self):
        """import metrics; import audit; both define reset → REWRITE_ERROR."""
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "audit.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = "import metrics\nimport audit\ndef process():\n    metrics.reset()\n    audit.reset()\n"
        r = assemble(model_code, case, mode="safe")
        assert r.status == "REWRITE_ERROR"
        assert any("collision" in e.lower() for e in r.qualified_imports_failed)

    def test_shadowing_fails(self):
        """metrics = something_else → REWRITE_ERROR."""
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = "import metrics\nmetrics = 'overwritten'\ndef process():\n    metrics.reset()\n"
        r = assemble(model_code, case, mode="safe")
        assert r.status == "REWRITE_ERROR"
        assert any("reassigned" in e.lower() for e in r.qualified_imports_failed)

    def test_alias_rewriting_still_works(self):
        """Regression: from X import Y as Z still works."""
        case = _make_case({
            "metrics.py": "def reset(): pass",
            "processor.py": "pass",
        })
        model_code = "from metrics import reset as r\ndef f(): r()\n"
        r = assemble(model_code, case, mode="safe")
        assert r.status == "SUCCESS"
        assert "from metrics" not in r.code
        assert "r()" not in r.code  # renamed to reset()
        assert "reset()" in r.code

    def test_stdlib_qualified_preserved(self):
        """import copy; copy.deepcopy(...) — stdlib NOT touched."""
        case = _make_case({
            "a.py": "pass",
            "b.py": "pass",
        })
        model_code = "import copy\ndef f(x):\n    return copy.deepcopy(x)\n"
        r = assemble(model_code, case, mode="safe")
        assert r.status == "SUCCESS"
        assert "import copy" in r.code
        assert "copy.deepcopy" in r.code
        assert len(r.qualified_imports_resolved) == 0

    def test_execution_works(self):
        """End-to-end: assembled code with namespace actually runs."""
        case = _make_case({
            "metrics.py": "_counter = 0\ndef increment(v):\n    global _counter\n    _counter += v\ndef get(): return _counter",
            "processor.py": "pass",
        })
        model_code = "import metrics\ndef process(items):\n    for i in items:\n        metrics.increment(i)\n    return metrics.get()\n"
        r = assemble(model_code, case, mode="safe")
        assert r.status == "SUCCESS", f"status={r.status}, errors={r.errors}"
        # Actually execute it
        ns = {}
        exec(compile(r.code, "<test>", "exec"), ns)
        result = ns["process"]([1, 2, 3])
        assert result == 6
