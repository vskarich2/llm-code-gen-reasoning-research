"""Code assembly for T3 benchmark — single source of truth.

Assembles executable Python from model output + original case files.
Handles import rewriting, normalization, validation, and concatenation.

Execution model: originals first, model overrides last (Python last-definition-wins).
This is the ONLY place assembly logic exists. No other file may assemble code.

Assembly modes:
  compat — normalize + concat only, no import rewriting (zero regression baseline)
  safe   — deterministic import rewrites only (aliases, star imports)
  full   — all rewrites including module-qualified access (future)
"""

import ast
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from core._stdlib import STDLIB_MODULES

_log = logging.getLogger("t3.assembly")

# ============================================================
# ASSEMBLY MODE
# ============================================================

ASSEMBLY_MODE = "safe"  # "compat" | "safe" | "full"


# ============================================================
# RESULT DATACLASS
# ============================================================


@dataclass
class AssemblyResult:
    code: str
    status: str  # SUCCESS | SYNTAX_ERROR | REWRITE_ERROR | ASSEMBLY_ERROR
    files_used: dict = field(default_factory=dict)  # path → "model" | "original" | "extra"
    rewrites_applied: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    # Compatibility fields (used by exec_eval)
    assembly_used: bool = False
    assembly_risky: bool = False
    rename_error: bool = False
    expected_func: str = ""
    duplicate_defs: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    # Qualified import resolution
    qualified_imports_resolved: list = field(default_factory=list)
    qualified_imports_failed: list = field(default_factory=list)
    qualified_import_warnings: list = field(default_factory=list)

    def __getitem__(self, key):
        """Dict-style access for backward compat with old tests."""
        return getattr(self, key)

    def get(self, key, default=None):
        """Dict-style .get() for backward compat."""
        return getattr(self, key, default)


# ============================================================
# CONTENT NORMALIZATION
# ============================================================


def _normalize_content(content: str) -> str:
    """Normalize model-produced file content.

    Handles:
    - Markdown fences (```python ... ```)
    - Escaped newlines when no real newlines present
    - Stray backticks

    Does NOT modify valid Python structure.
    """
    if not content or not content.strip():
        return content

    normalized = content

    # Strip markdown fences
    stripped = normalized.strip()
    if stripped.startswith("```"):
        first_nl = stripped.find("\n")
        if first_nl != -1:
            after_open = stripped[first_nl + 1:]
        else:
            after_open = ""
        if after_open.rstrip().endswith("```"):
            last_fence = after_open.rstrip().rfind("```")
            after_open = after_open[:last_fence]
        normalized = after_open

    # Unescape \\n and \\t when content has NO real newlines
    if "\n" not in normalized and "\\n" in normalized:
        normalized = normalized.replace("\\n", "\n").replace("\\t", "\t")

    return normalized


# ============================================================
# IMPORT ANALYSIS
# ============================================================


def _is_local_module(name: str, local_modules: frozenset) -> bool:
    """Check if a module name is a local (sibling) module."""
    base = name.split(".")[0] if "." in name else name
    if base in STDLIB_MODULES:
        return False
    if local_modules and base in local_modules:
        return True
    if not local_modules:
        # No context — treat all non-stdlib as local (conservative for assembly)
        return base not in STDLIB_MODULES
    return False


def _collect_import_info(tree: ast.AST, local_modules: frozenset) -> list[dict]:
    """Collect all import statements and classify them.

    Returns list of dicts with:
        node: ast node
        kind: "from_import" | "import" | "from_import_star"
        module: str
        is_local: bool
        names: list of (original_name, alias_or_none)
    """
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            is_local = _is_local_module(mod, local_modules)

            if any(alias.name == "*" for alias in node.names):
                imports.append({
                    "node": node,
                    "kind": "from_import_star",
                    "module": mod,
                    "is_local": is_local,
                    "names": [("*", None)],
                    "level": node.level,
                })
            else:
                names = [(alias.name, alias.asname) for alias in node.names]
                imports.append({
                    "node": node,
                    "kind": "from_import",
                    "module": mod,
                    "is_local": is_local,
                    "names": names,
                    "level": node.level,
                })

        elif isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                is_local = _is_local_module(mod, local_modules)
                imports.append({
                    "node": node,
                    "kind": "import",
                    "module": mod,
                    "is_local": is_local,
                    "names": [(alias.name, alias.asname)],
                    "level": 0,
                })

    return imports


def _find_attribute_usages(tree: ast.AST, module_name: str) -> list[ast.Attribute]:
    """Find all X.attr usages for a given module name X."""
    usages = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == module_name):
            usages.append(node)
    return usages


# ============================================================
# MODULE-QUALIFIED IMPORT RESOLUTION
# ============================================================


def _build_export_table(file_contents: list[tuple[str, str]], local_modules: frozenset) -> dict:
    """Build per-module export tables from file contents.

    Returns: {module_name: {symbol_name: True}} for each local module.
    Only includes top-level functions, classes, and assignments.
    """
    exports = {}
    for rel_path, content in file_contents:
        mod_name = rel_path.rsplit("/", 1)[-1].replace(".py", "")
        if mod_name not in local_modules:
            continue
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        symbols = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.add(node.name)
            elif isinstance(node, ast.ClassDef):
                symbols.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        symbols.add(target.id)
        exports[mod_name] = symbols
    return exports


def _detect_dynamic_access(tree: ast.AST, name: str) -> bool:
    """Check if module name is used in getattr(), __dict__, or reassigned."""
    for node in ast.walk(tree):
        # getattr(X, ...)
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == name):
            return True
        # X.__dict__
        if (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == name
                and node.attr == "__dict__"):
            return True
    return False


def _detect_shadowing(tree: ast.AST, name: str) -> bool:
    """Check if module name is reassigned anywhere (X = something)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return True
        if isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return True
    return False


def _resolve_qualified_imports(
    assembled_code: str,
    local_modules: frozenset,
    export_table: dict,
    model_code_tree: ast.AST | None,
    original_trees: list[ast.AST],
) -> tuple[str, list[dict], list[str], list[str]]:
    """Resolve module-qualified imports by synthesizing namespace objects.

    For each `import X` / `import X as Y` with X.attr usage:
    1. Verify all used attrs exist in module exports
    2. Check for collisions, dynamic access, shadowing
    3. Remove the import statement
    4. Append SimpleNamespace binding after all code

    Returns: (new_code, resolved, warnings, errors)
    """
    resolved = []
    warnings = []
    errors = []

    try:
        tree = ast.parse(assembled_code)
    except SyntaxError:
        return assembled_code, resolved, warnings, ["assembled code has syntax error — skipping qualified import resolution"]

    # Find all `import X` / `import X as Y` for local modules with attr usage
    qualified_imports = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            mod_name = alias.name
            if not _is_local_module(mod_name, local_modules):
                continue
            effective_name = alias.asname or mod_name
            attr_usages = _find_attribute_usages(tree, effective_name)
            if not attr_usages:
                continue
            qualified_imports.append({
                "node": node,
                "module": mod_name,
                "alias": alias.asname,
                "effective_name": effective_name,
                "attr_usages": attr_usages,
                "used_attrs": set(u.attr for u in attr_usages),
            })

    if not qualified_imports:
        return assembled_code, resolved, warnings, errors

    # Validate each qualified import
    nodes_to_remove = set()
    namespace_bindings = []  # (effective_name, {attr: attr, ...})

    # Check for cross-module collision: same attr name used via different modules
    all_qualified_attrs = {}  # attr_name → list of module names
    for qi in qualified_imports:
        for attr in qi["used_attrs"]:
            all_qualified_attrs.setdefault(attr, []).append(qi["module"])

    collisions = {attr: mods for attr, mods in all_qualified_attrs.items() if len(set(mods)) > 1}
    if collisions:
        for attr, mods in collisions.items():
            errors.append(
                f"REWRITE_ERROR: symbol collision — '{attr}' referenced via modules "
                f"{sorted(set(mods))}. Cannot resolve unambiguously."
            )
        return assembled_code, resolved, warnings, errors

    for qi in qualified_imports:
        mod_name = qi["module"]
        effective_name = qi["effective_name"]
        used_attrs = qi["used_attrs"]

        # Check for dynamic access
        if _detect_dynamic_access(tree, effective_name):
            errors.append(
                f"REWRITE_ERROR: dynamic access to '{effective_name}' "
                f"(getattr or __dict__). Cannot resolve safely."
            )
            return assembled_code, resolved, warnings, errors

        # Check for shadowing
        if _detect_shadowing(tree, effective_name):
            errors.append(
                f"REWRITE_ERROR: '{effective_name}' is reassigned. "
                f"Cannot synthesize namespace safely."
            )
            return assembled_code, resolved, warnings, errors

        # Check all used attrs exist in exports
        module_exports = export_table.get(mod_name, set())
        missing = used_attrs - module_exports
        if missing:
            errors.append(
                f"REWRITE_ERROR: '{effective_name}.{sorted(missing)[0]}' — "
                f"symbol '{sorted(missing)[0]}' not found in module '{mod_name}'. "
                f"Available: {sorted(module_exports)}"
            )
            return assembled_code, resolved, warnings, errors

        # All checks pass — mark for resolution
        nodes_to_remove.add(id(qi["node"]))
        namespace_bindings.append((effective_name, mod_name, sorted(used_attrs)))
        resolved.append({
            "type": "qualified_import_resolved",
            "module": mod_name,
            "effective_name": effective_name,
            "attrs": sorted(used_attrs),
        })

    if not nodes_to_remove:
        return assembled_code, resolved, warnings, errors

    # Remove import statements
    remover = _ImportRemover(nodes_to_remove)
    tree = remover.visit(tree)
    ast.fix_missing_locations(tree)

    try:
        code_without_imports = ast.unparse(tree)
    except Exception as e:
        errors.append(f"ast.unparse failed after import removal: {e}")
        return assembled_code, resolved, warnings, errors

    # Generate namespace bindings (AFTER all code)
    binding_lines = ["\n# --- Synthesized module namespaces (assembly) ---"]
    binding_lines.append("from types import SimpleNamespace as _T3_NS")
    for effective_name, mod_name, attrs in namespace_bindings:
        attr_bindings = ", ".join(f"{a}={a}" for a in attrs)
        binding_lines.append(f"{effective_name} = _T3_NS({attr_bindings})")

    namespace_code = "\n".join(binding_lines)
    final_code = code_without_imports + "\n" + namespace_code

    return final_code, resolved, warnings, errors


# ============================================================
# SAFE IMPORT REWRITING
# ============================================================


class _NameRewriter(ast.NodeTransformer):
    """AST transformer that renames identifiers."""

    def __init__(self, rename_map: dict[str, str]):
        self.rename_map = rename_map
        self.applied = []

    def visit_Name(self, node):
        if node.id in self.rename_map:
            old = node.id
            new = self.rename_map[old]
            self.applied.append({"type": "name_rename", "old": old, "new": new, "line": node.lineno})
            node.id = new
        return node


class _ImportRemover(ast.NodeTransformer):
    """AST transformer that removes specific import nodes."""

    def __init__(self, nodes_to_remove: set):
        self.nodes_to_remove = nodes_to_remove

    def visit_Import(self, node):
        if id(node) in self.nodes_to_remove:
            return None
        return node

    def visit_ImportFrom(self, node):
        if id(node) in self.nodes_to_remove:
            return None
        return node


def _rewrite_imports_safe(code: str, local_modules: frozenset,
                          all_assembled_names: set) -> tuple[str, list[dict], list[str]]:
    """Safe-mode import rewriting via AST.

    Rules:
    - from X import Y: delete if X is local (Y available from concat)
    - from X import Y as Z: delete import, rename Z → Y everywhere
      ONLY if Y is unambiguous in assembled namespace
    - from X import *: always delete (safe due to concat)
    - import X: keep if X.attr usage exists (can't safely rewrite)
      delete only if no attribute access
    - import X as Y: keep if Y.attr usage exists
      delete only if no attribute access
    - relative imports: always delete

    Returns (rewritten_code, rewrites_applied, warnings)
    """
    rewrites = []
    warnings = []

    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Can't parse — fall back to no rewriting
        warnings.append("AST parse failed — skipping import rewriting")
        return code, rewrites, warnings

    imports = _collect_import_info(tree, local_modules)
    local_imports = [imp for imp in imports if imp["is_local"] or imp["level"] > 0]

    if not local_imports:
        return code, rewrites, warnings

    nodes_to_remove = set()
    rename_map = {}

    for imp in local_imports:
        # Relative imports: always remove
        if imp["level"] > 0:
            nodes_to_remove.add(id(imp["node"]))
            rewrites.append({"type": "remove_relative_import", "module": imp["module"]})
            continue

        if imp["kind"] == "from_import_star":
            # from X import * — always safe to remove in concat
            nodes_to_remove.add(id(imp["node"]))
            rewrites.append({"type": "remove_star_import", "module": imp["module"]})
            continue

        if imp["kind"] == "from_import":
            # from X import a, b as c, d
            safe_to_remove = True
            for original_name, alias in imp["names"]:
                if alias is not None:
                    # from X import Y as Z — need to rename Z → Y
                    # Check: is Y unambiguous?
                    # For safety, we always do this rename — Y should exist
                    # in the concat namespace from the original file
                    rename_map[alias] = original_name
                    rewrites.append({
                        "type": "alias_rename",
                        "module": imp["module"],
                        "original": original_name,
                        "alias": alias,
                    })
                # else: from X import Y — Y will be available from concat
            nodes_to_remove.add(id(imp["node"]))
            rewrites.append({"type": "remove_from_import", "module": imp["module"],
                             "names": [n for n, _ in imp["names"]]})
            continue

        if imp["kind"] == "import":
            mod_name = imp["module"]
            alias = imp["names"][0][1]  # import X as Y → alias=Y
            effective_name = alias or mod_name

            # Check for X.attr or Y.attr usage, or dynamic access (getattr)
            attr_usages = _find_attribute_usages(tree, effective_name)
            has_dynamic = _detect_dynamic_access(tree, effective_name)

            if attr_usages or has_dynamic:
                # Module-qualified or dynamic access exists.
                # Qualified resolution (step 5.7) will handle attr_usages.
                # Dynamic access CANNOT be resolved — keep import, which will
                # cause ModuleNotFoundError at runtime. This is correct: we
                # surface the error rather than silently corrupting bindings.
                if has_dynamic:
                    warnings.append(
                        f"keeping 'import {mod_name}"
                        f"{' as ' + alias if alias else ''}' — "
                        f"dynamic access detected (getattr/__dict__), cannot resolve"
                    )
                    continue
                # attr_usages exist — don't remove here, let step 5.7 handle it
                continue

            # No attribute access — safe to remove
            nodes_to_remove.add(id(imp["node"]))
            rewrites.append({"type": "remove_bare_import", "module": mod_name})
            if alias:
                # import X as Y with no Y.attr — but Y might be used as a name
                # Check if Y is used as a bare Name anywhere
                y_usages = [n for n in ast.walk(tree)
                            if isinstance(n, ast.Name) and n.id == alias
                            and n is not imp["node"]]
                if y_usages:
                    warnings.append(
                        f"'import {mod_name} as {alias}': alias '{alias}' used as bare name "
                        f"{len(y_usages)} time(s) — keeping import to be safe"
                    )
                    nodes_to_remove.discard(id(imp["node"]))
                    rewrites.pop()  # undo the remove
                    continue

    # Apply removals
    if nodes_to_remove:
        remover = _ImportRemover(nodes_to_remove)
        tree = remover.visit(tree)
        ast.fix_missing_locations(tree)

    # Apply renames
    if rename_map:
        rewriter = _NameRewriter(rename_map)
        tree = rewriter.visit(tree)
        ast.fix_missing_locations(tree)
        rewrites.extend(rewriter.applied)

    try:
        result = ast.unparse(tree)
    except Exception as e:
        warnings.append(f"ast.unparse failed: {e} — returning original code")
        return code, rewrites, warnings

    return result, rewrites, warnings


def _strip_imports_compat(code: str, local_modules: frozenset) -> str:
    """Compat-mode: line-based import stripping (no AST).

    Same logic as the full assembly stripping but without multi-line
    handling or alias rewriting. Used when mode="compat".
    """
    lines = []
    for line in code.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("from .", "import .")):
            continue
        if stripped.startswith("from ") and " import " in stripped:
            mod = stripped.split("from ", 1)[1].split(" import")[0].strip()
            base = mod.split(".")[0] if "." in mod else mod
            if _is_local_module(base, local_modules):
                continue
        elif stripped.startswith("import "):
            mod = stripped.split("import ", 1)[1].split()[0].strip().rstrip(",")
            if _is_local_module(mod, local_modules):
                continue
        lines.append(line)
    return "\n".join(lines)


# ============================================================
# MAIN ASSEMBLER
# ============================================================


class CodeAssembler:
    """Single-path code assembler for T3 benchmark.

    Owns the entire pipeline: resolve → normalize → validate → rewrite → concat → validate.
    """

    def __init__(self, mode: str | None = None):
        self.mode = mode or ASSEMBLY_MODE

    def assemble(self, model_code: str, case: dict) -> AssemblyResult:
        """Assemble executable code from model output + original case files.

        Args:
            model_code: extracted code from model (may be single file or concatenated changed files)
            case: benchmark case dict with code_files, code_files_contents, reference_fix

        Returns:
            AssemblyResult with assembled code and full provenance.
        """
        code_contents = case.get("code_files_contents", {})
        code_files = case.get("code_files", [])
        local_modules = frozenset(
            p.rsplit("/", 1)[-1].replace(".py", "")
            for p in code_files if p.endswith(".py")
        )

        # Single-file case: no assembly needed
        if not code_contents or len(code_contents) <= 1:
            processed, rewrites, warnings = self._process_imports(model_code, local_modules, set())
            return AssemblyResult(
                code=processed,
                status="SUCCESS",
                files_used={"model": "model_only"},
                rewrites_applied=rewrites,
                warnings=warnings,
                assembly_used=False,
                sources={"model_only": True},
            )

        # Multi-file case: full assembly pipeline
        return self._assemble_multi_file(model_code, case, code_contents, code_files, local_modules)

    def _assemble_multi_file(self, model_code, case, code_contents, code_files, local_modules):
        """Full multi-file assembly pipeline."""
        warnings = []
        errors = []
        all_rewrites = []
        files_used = {}

        # ── Step 1: Resolve files ──
        original_parts = []
        for rel_path in code_files:
            content = code_contents.get(rel_path, "")
            if content:
                original_parts.append((rel_path, content))
                files_used[rel_path] = "original"

        # ── Step 2: Normalize original content ──
        normalized_originals = []
        for rel_path, content in original_parts:
            normalized = _normalize_content(content)
            if normalized != content:
                warnings.append(f"normalized: {rel_path}")
            normalized_originals.append((rel_path, normalized))

        # Normalize model code
        model_normalized = _normalize_content(model_code)
        if model_normalized != model_code:
            warnings.append("normalized: model_code")

        # ── Step 3: Validate syntax per-file (before rewriting) ──
        syntax_errors = {}
        for rel_path, content in normalized_originals:
            try:
                ast.parse(content)
            except SyntaxError as e:
                syntax_errors[rel_path] = str(e)

        try:
            ast.parse(model_normalized)
        except SyntaxError as e:
            syntax_errors["model_code"] = str(e)

        if "model_code" in syntax_errors:
            # Model code has syntax errors — can't proceed with AST rewriting
            # Fall through to compat mode concat
            warnings.append(f"model code has syntax error: {syntax_errors['model_code']}")

        # ── Step 4: Rewrite imports ──
        # Collect all names that will be in the assembled namespace
        all_names = set()
        for _, content in normalized_originals:
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        all_names.add(node.name)
                    elif isinstance(node, ast.ClassDef):
                        all_names.add(node.name)
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                all_names.add(target.id)
            except SyntaxError:
                pass

        # Process originals
        processed_originals = []
        for rel_path, content in normalized_originals:
            processed, rewrites, rwarn = self._process_imports(content, local_modules, all_names)
            processed_originals.append(processed)
            all_rewrites.extend([{**r, "file": rel_path} for r in rewrites])
            warnings.extend([f"{rel_path}: {w}" for w in rwarn])

        # Process model code
        model_processed, model_rewrites, model_warnings = self._process_imports(
            model_normalized, local_modules, all_names
        )
        all_rewrites.extend([{**r, "file": "model_code"} for r in model_rewrites])
        warnings.extend([f"model_code: {w}" for w in model_warnings])

        # ── Step 5: Concatenate (originals first, model last) ──
        original_concat = "\n\n".join(processed_originals)
        assembled = original_concat + "\n\n" + model_processed

        # ── Step 5.5: Detect duplicates and rename errors ──
        model_defs = set(re.findall(r"^(?:def|class)\s+(\w+)", model_processed, re.MULTILINE))
        original_defs = set(re.findall(r"^(?:def|class)\s+(\w+)", original_concat, re.MULTILINE))
        duplicates = sorted(model_defs & original_defs)

        expected_func = case.get("reference_fix", {}).get("function", "")
        rename_error = False
        if expected_func and expected_func in original_defs and expected_func not in model_defs:
            rename_error = True
            warnings.append(
                f"RENAME: model does not define '{expected_func}' — "
                f"original buggy version will run. Model defines: {sorted(model_defs)}"
            )

        # ── Step 5.7: Resolve module-qualified imports ──
        qualified_resolved = []
        qualified_failed = []
        qualified_warnings = []

        if self.mode in ("safe", "full"):
            export_table = _build_export_table(normalized_originals, local_modules)
            assembled, q_resolved, q_warnings, q_errors = _resolve_qualified_imports(
                assembled, local_modules, export_table, None, []
            )
            qualified_resolved = q_resolved
            qualified_warnings = q_warnings
            if q_errors:
                qualified_failed = q_errors
                # Qualified import errors are warnings, not hard failures —
                # the code may still work if the import happens to resolve at runtime
                warnings.extend(q_errors)
            all_rewrites.extend(q_resolved)
            warnings.extend(q_warnings)

        # ── Step 6: Validate final assembled code ──
        status = "SUCCESS"
        try:
            compile(assembled, "<assembly>", "exec")
        except SyntaxError as e:
            status = "SYNTAX_ERROR"
            errors.append(f"assembled code has syntax error: {e}")

        if qualified_failed and status == "SUCCESS":
            status = "REWRITE_ERROR"

        return AssemblyResult(
            code=assembled,
            status=status,
            files_used=files_used,
            rewrites_applied=all_rewrites,
            warnings=warnings,
            errors=errors,
            assembly_used=True,
            assembly_risky=len(duplicates) > 0,
            rename_error=rename_error,
            expected_func=expected_func,
            duplicate_defs=duplicates,
            sources={
                "model_only": False,
                "original_files": [p for p, _ in original_parts],
                "model_defs": sorted(model_defs),
                "original_defs": sorted(original_defs),
                "overridden": duplicates,
            },
            qualified_imports_resolved=qualified_resolved,
            qualified_imports_failed=qualified_failed,
            qualified_import_warnings=qualified_warnings,
        )

    def _process_imports(self, code: str, local_modules: frozenset,
                         all_names: set) -> tuple[str, list, list]:
        """Process imports according to current mode."""
        if self.mode == "compat":
            stripped = _strip_imports_compat(code, local_modules)
            return stripped, [], []
        elif self.mode in ("safe", "full"):
            return _rewrite_imports_safe(code, local_modules, all_names)
        else:
            raise RuntimeError(f"Unknown assembly mode: {self.mode}")


# ============================================================
# MODULE-LEVEL CONVENIENCE
# ============================================================


def assemble(model_code: str, case: dict, mode: str | None = None) -> AssemblyResult:
    """Module-level convenience function."""
    return CodeAssembler(mode=mode).assemble(model_code, case)


def assemble_original(case: dict, mode: str | None = None) -> AssemblyResult:
    """Assemble a case's original (buggy) code through the canonical assembly path.

    Used by validation and preflight to load case code with identical
    import handling as the real execution pipeline. No model code involved.
    """
    code_contents = case.get("code_files_contents", {})
    concat = "\n\n".join(code_contents.get(p, "") for p in case.get("code_files", []))
    return CodeAssembler(mode=mode).assemble(concat, case)


def assemble_code(code: str, case: dict, mode: str | None = None) -> AssemblyResult:
    """Assemble arbitrary code against a case through the canonical assembly path.

    Used by validation and preflight to load reference fixes, mutants, etc.
    """
    return CodeAssembler(mode=mode).assemble(code, case)
