"""Enforcement tests — verify the single canonical assembly path invariant.

These tests PREVENT regression by scanning the codebase for violations.
If any test fails, someone has introduced an alternate assembly path.
"""

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]

# Files that are ALLOWED to contain assembly/import logic
ASSEMBLY_ALLOWED = {
    "code_assembly.py",
}

# Files that legitimately exec code (post-assembly)
EXEC_ALLOWED = {
    "code_assembly.py",          # compile() for validation
    "exec_eval.py",              # load_module_from_code — post-assembly exec
    "validate_cases_v2.py",      # load_module — post-assembly exec
    "graph_runner/executors/exec_eval.py",  # separate system
}

# Test files that legitimately call load_module_from_code with trivial code
TEST_EXEC_ALLOWED = {
    "tests/test_execution_runs.py",  # tests module loader directly with no-import code
}


def _scan_py_files():
    """Yield all .py files in repo, excluding __pycache__ and .venv."""
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv", "node_modules", ".git")]
        for f in files:
            if f.endswith(".py"):
                yield Path(root) / f


class TestNoForkedStripping:
    """No file outside code_assembly.py may implement import stripping."""

    def test_no_strip_local_imports_definitions(self):
        """No function named _strip_local_imports or strip_local_imports outside assembly."""
        violations = []
        for path in _scan_py_files():
            rel = str(path.relative_to(REPO))
            if rel in ASSEMBLY_ALLOWED:
                continue
            content = path.read_text(errors="ignore")
            if re.search(r"def\s+_?strip_local_imports\b", content):
                violations.append(rel)
        assert not violations, f"Forked strip_local_imports found in: {violations}"

    def test_no_stdlib_set_definitions(self):
        """No file outside _stdlib.py may define its own _STDLIB set."""
        violations = []
        for path in _scan_py_files():
            rel = str(path.relative_to(REPO))
            if rel == "_stdlib.py":
                continue
            if rel.startswith("tests/"):
                continue  # test files may define test data
            content = path.read_text(errors="ignore")
            # Look for _STDLIB = { or _STDLIB = set( or _STDLIB = frozenset(
            if re.search(r"^_STDLIB\s*=\s*[{(]", content, re.MULTILINE):
                violations.append(rel)
        assert not violations, f"Forked _STDLIB definition found in: {violations}"

    def test_no_import_from_parse_strip(self):
        """No file may import strip_local_imports or classify_import from parse.py."""
        violations = []
        for path in _scan_py_files():
            rel = str(path.relative_to(REPO))
            content = path.read_text(errors="ignore")
            if re.search(r"from\s+parse\s+import\s+.*strip_local", content):
                violations.append(f"{rel}: imports strip_local_imports from parse")
            if re.search(r"from\s+parse\s+import\s+.*classify_import", content):
                violations.append(f"{rel}: imports classify_import from parse")
        assert not violations, f"Legacy parse imports found:\n" + "\n".join(violations)

    def test_no_import_rewrite_outside_assembly(self):
        """No file outside code_assembly.py may use ast.ImportFrom or _NameRewriter."""
        violations = []
        for path in _scan_py_files():
            rel = str(path.relative_to(REPO))
            if rel in ASSEMBLY_ALLOWED:
                continue
            if rel.startswith("scripts/ast_mutator") or rel.startswith("scripts/mutation"):
                continue  # AST mutator legitimately uses ast nodes
            if rel.startswith("tests/test_assembly_invariant"):
                continue  # this test file references names for scanning
            content = path.read_text(errors="ignore")
            # Check for actual USAGE (import or instantiation), not string mentions
            if re.search(r"(?:from|import).*_NameRewriter|_NameRewriter\(", content):
                violations.append(f"{rel}: uses internal assembly transformers")
            if re.search(r"(?:from|import).*_ImportRemover|_ImportRemover\(", content):
                violations.append(f"{rel}: uses internal assembly transformers")
        assert not violations, f"Assembly internals used outside assembly:\n" + "\n".join(violations)


class TestNoAssemblyBypass:
    """No code may bypass assembly to reach execution."""

    def test_validate_load_module_requires_case(self):
        """validate_cases_v2.load_module must require case parameter."""
        content = (REPO / "validate_cases_v2.py").read_text()
        # Must NOT have case=None or Optional[case]
        assert "case: dict | None" not in content, "load_module still has optional case"
        assert "case=None" not in content, "load_module still has case=None default"

    def test_no_raw_exec_in_scripts(self):
        """Scripts must not exec code without assembly."""
        content = (REPO / "scripts" / "test_invariant.py").read_text()
        # Must use assemble_code, not raw exec
        assert "assemble_code" in content, "test_invariant.py does not use canonical assembly"
        # Should not have bare exec(code, ...)
        lines = content.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("exec(") and "asm" not in stripped and "compile" not in stripped:
                if "exec_module" not in stripped:  # importlib.exec_module is OK
                    pytest.fail(f"test_invariant.py line {i+1}: raw exec without assembly: {stripped}")


class TestSingleEntrypoint:
    """CodeAssembler.assemble() must be the only assembly entrypoint."""

    def test_assemble_program_is_thin_wrapper(self):
        """exec_eval._assemble_program must only delegate to CodeAssembler."""
        content = (REPO / "exec_eval.py").read_text()
        # Find _assemble_program function body
        match = re.search(r"def _assemble_program\(.*?\).*?:\n(.*?)(?=\ndef |\Z)",
                          content, re.DOTALL)
        assert match, "_assemble_program not found"
        body = match.group(1)
        # Must contain CodeAssembler
        assert "CodeAssembler" in body, "_assemble_program does not delegate to CodeAssembler"
        # Must NOT contain inline assembly logic
        assert "\\n\\n\".join" not in body, "_assemble_program has inline concatenation"
        assert "strip_local" not in body, "_assemble_program has inline stripping"

    def test_load_module_from_code_no_transformation(self):
        """load_module_from_code must not transform code."""
        content = (REPO / "exec_eval.py").read_text()
        match = re.search(r"def load_module_from_code\(.*?\).*?:\n(.*?)(?=\ndef |\Z)",
                          content, re.DOTALL)
        assert match, "load_module_from_code not found"
        body = match.group(1)
        # Strip docstring (everything between first """ and next """)
        body_no_doc = re.sub(r'""".*?"""', '', body, flags=re.DOTALL)
        # Strip comments
        code_lines = [l for l in body_no_doc.split("\n")
                      if l.strip() and not l.strip().startswith("#")]
        code_text = "\n".join(code_lines).lower()
        assert "strip" not in code_text, "load_module_from_code still strips imports in code"
        assert "rewrite" not in code_text, "load_module_from_code rewrites imports in code"
