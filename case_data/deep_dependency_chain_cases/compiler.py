"""Minimal shared compiler for deep dependency chain generated cases."""

from __future__ import annotations

import ast
import importlib.util
import pprint
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ALLOWED_IMPORTS = {"math", "statistics", "typing"}
ANNOTATION_NODE_RE = re.compile(r"#\s*@node:\s*([A-Za-z0-9_]+)\s*$")
ANNOTATION_ROLE_RE = re.compile(r"#\s*@role:\s*([A-Za-z0-9_]+)\s*$")


def _find_case_file(case_name: str) -> Path:
    case_dir = ROOT / case_name / "cases"
    matches = sorted(case_dir.glob("case_*.py"))
    if not matches:
        raise ValueError(f"no case file found for {case_name}")
    return matches[0]


def _load_case_module(case_name: str):
    case_file = _find_case_file(case_name)
    module_name = f"deep_dependency_chain_{case_name}"
    spec = importlib.util.spec_from_file_location(module_name, case_file)
    if spec is None or spec.loader is None:
        raise ValueError(f"failed to load module spec for {case_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, case_file


def _get_top_level_imports(tree: ast.Module, source: str) -> list[str]:
    import_lines: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue

        allowed = True
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".")[0]
                if root_name not in ALLOWED_IMPORTS:
                    allowed = False
                    break
        else:
            module_name = (node.module or "").split(".")[0]
            if module_name not in ALLOWED_IMPORTS:
                allowed = False

        if allowed:
            import_source = ast.get_source_segment(source, node)
            if import_source:
                import_lines.append(import_source)

    return import_lines


def _get_annotation_block(lines: list[str], lineno: int) -> dict[str, str]:
    node_name = None
    role_name = None
    index = lineno - 2
    block: list[str] = []

    while index >= 0:
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("#"):
            block.append(stripped)
            index -= 1
            continue
        if stripped == "":
            index -= 1
            continue
        break

    for line in reversed(block):
        node_match = ANNOTATION_NODE_RE.match(line)
        if node_match:
            node_name = node_match.group(1)
        role_match = ANNOTATION_ROLE_RE.match(line)
        if role_match:
            role_name = role_match.group(1)

    result = {}
    if node_name:
        result["node"] = node_name
    if role_name:
        result["role"] = role_name
    return result


def _extract_functions(module, case_file: Path) -> dict:
    source = case_file.read_text()
    lines = source.splitlines()
    tree = ast.parse(source)
    top_level_imports = _get_top_level_imports(tree, source)

    functions = []
    function_sources = {}
    function_nodes = {}

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue

        function_source = ast.get_source_segment(source, node)
        if not function_source:
            continue

        function_sources[node.name] = function_source
        function_nodes[node.name] = node

        annotations = _get_annotation_block(lines, node.lineno)
        if "node" not in annotations or "role" not in annotations:
            continue

        body_lines = function_source.splitlines()[1:]
        body_text = "\n".join(body_lines)
        functions.append(
            {
                "name": node.name,
                "node": annotations["node"],
                "role": annotations["role"],
                "source": function_source,
                "body_text": body_text,
                "helpers": [],
                "module": case_file.name,
                "ast": node,
            }
        )

    return {
        "source": source,
        "tree": tree,
        "top_level_imports": top_level_imports,
        "functions": functions,
        "function_sources": function_sources,
        "function_nodes": function_nodes,
        "data_globals": getattr(module, "CASE_DATA_GLOBALS", []),
    }


def _validate_single_arg(function_record: dict, case_name: str):
    args = function_record["ast"].args
    positional = len(args.posonlyargs) + len(args.args)
    if positional != 1 or args.vararg or args.kwarg or args.kwonlyargs:
        raise ValueError(
            f"{case_name}: function {function_record['name']} must accept exactly one positional argument"
        )


def _select_node_functions(case_name: str, spec, extracted: dict, variant: str | None = None) -> dict[str, dict]:
    by_node: dict[str, dict[str, list[dict]]] = {}
    valid_nodes = {chain_node.name for chain_node in spec.chain}

    for function_record in extracted["functions"]:
        node_name = function_record["node"]
        if node_name not in valid_nodes:
            raise ValueError(f"{case_name}: annotated node {node_name!r} not found in spec.chain")
        by_node.setdefault(node_name, {}).setdefault(function_record["role"], []).append(function_record)

    selected = {}
    for chain_node in spec.chain:
        role_map = by_node.get(chain_node.name, {})
        chosen_role = None

        if variant and role_map.get(variant):
            chosen_role = variant
        elif role_map.get("buggy"):
            chosen_role = "buggy"
        elif role_map.get("main"):
            chosen_role = "main"
        else:
            raise ValueError(f"{case_name}: node {chain_node.name!r} is missing both buggy and main annotations")

        matches = role_map[chosen_role]
        if len(matches) != 1:
            raise ValueError(
                f"{case_name}: node {chain_node.name!r} has {len(matches)} functions for role {chosen_role!r}"
            )

        selected[chain_node.name] = matches[0]
        _validate_single_arg(matches[0], case_name)

    return selected


def _collect_helpers(function_record: dict, function_sources: dict[str, str]) -> list[dict]:
    helpers = []
    helper_names = []
    seen = {function_record["name"]}
    pending_texts = [function_record["body_text"]]

    while pending_texts:
        body_text = pending_texts.pop(0)
        for helper_name, helper_source in function_sources.items():
            if helper_name in seen:
                continue
            if re.search(rf"\b{re.escape(helper_name)}\b", body_text):
                seen.add(helper_name)
                helpers.append({"name": helper_name, "source": helper_source})
                helper_names.append(helper_name)
                pending_texts.append(helper_source)

    function_record["helpers"] = helper_names
    return helpers


def _validate_helper_resolution(function_record: dict, function_sources: dict[str, str], case_name: str):
    referenced_names = set(re.findall(r"\b(_[A-Za-z0-9_]+)\b", function_record["body_text"]))
    unresolved = sorted(name for name in referenced_names if name not in function_sources)
    if unresolved:
        raise ValueError(
            f"{case_name}: function {function_record['name']} references unresolved helpers: {', '.join(unresolved)}"
        )


def _collect_data_imports(source_text: str, data_global_names: list[str]) -> list[str]:
    used = []
    for name in data_global_names:
        if re.search(rf"\b{re.escape(name)}\b", source_text):
            used.append(name)
    return used


def _rename_function(function_source: str, original_name: str, emitted_name: str) -> str:
    renamed = re.sub(
        rf"\bdef\s+{re.escape(original_name)}\b",
        f"def {emitted_name}",
        function_source,
        count=1,
    )
    if renamed == function_source:
        raise ValueError(f"failed to rename function {original_name} to {emitted_name}")
    return renamed


def _strip_comments(code: str) -> str:
    """Remove all comments and docstrings from generated code."""
    lines = []
    for line in code.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if "#" in line:
            in_string = False
            string_char = None
            cut_at = None
            for i, ch in enumerate(line):
                if in_string:
                    if ch == string_char and (i == 0 or line[i - 1] != "\\"):
                        in_string = False
                elif ch in ('"', "'"):
                    in_string = True
                    string_char = ch
                elif ch == "#":
                    cut_at = i
                    break
            if cut_at is not None:
                line = line[:cut_at].rstrip()
        lines.append(line)

    result = "\n".join(lines)

    result = re.sub(r'"""[\s\S]*?"""', "", result)
    result = re.sub(r"'''[\s\S]*?'''", "", result)

    cleaned = []
    for line in result.splitlines():
        if line.strip():
            cleaned.append(line)
        elif cleaned and cleaned[-1].strip():
            cleaned.append(line)

    return "\n".join(cleaned).strip() + "\n"


def _build_node_file(case_name: str, chain_node, function_record: dict, extracted: dict) -> str:
    _validate_helper_resolution(function_record, extracted["function_sources"], case_name)
    helpers = _collect_helpers(function_record, extracted["function_sources"])
    file_parts = []

    if extracted["top_level_imports"]:
        file_parts.append("\n".join(extracted["top_level_imports"]))

    global_names = set(_collect_data_imports(function_record["source"], extracted["data_globals"]))
    for helper in helpers:
        global_names.update(_collect_data_imports(helper["source"], extracted["data_globals"]))

    if global_names:
        file_parts.append(f"from data import {', '.join(sorted(global_names))}")

    for helper in helpers:
        file_parts.append(helper["source"])

    renamed_function = _rename_function(function_record["source"], function_record["name"], chain_node.function)
    file_parts.append(renamed_function)

    rendered = "\n\n".join(part for part in file_parts if part.strip()).strip() + "\n"
    function_signature = f"def {chain_node.function}("
    if not rendered.strip() or function_signature not in rendered:
        raise ValueError(f"generated file for node {chain_node.name} is empty or missing {chain_node.function}")
    return _strip_comments(rendered)


def _build_data_file(module, data_globals: list[str]) -> str:
    if not data_globals:
        raise ValueError("CASE_DATA_GLOBALS is required")

    lines = []
    for name in data_globals:
        if not hasattr(module, name):
            raise ValueError(f"missing declared data global: {name}")
        value = getattr(module, name)
        rendered = pprint.pformat(value, sort_dicts=False)
        lines.append(f"{name} = {rendered}")

    content = "\n\n".join(lines).strip() + "\n"
    if not content.strip():
        raise ValueError("generated data.py is empty")
    return content


def _build_pipeline_file(spec, data_globals: list[str]) -> str:
    import_lines = []
    data_names = []
    if "RAW_DATA" in data_globals:
        data_names.append("RAW_DATA")
    elif "RAW_EVENTS" in data_globals:
        data_names.append("RAW_EVENTS")
    else:
        raise ValueError("pipeline requires RAW_DATA or RAW_EVENTS")

    import_lines.append(f"from data import {', '.join(data_names)}")

    for chain_node in spec.chain:
        module_name = Path(chain_node.module).stem
        import_lines.append(f"from {module_name} import {chain_node.function}")

    body_lines = [
        "def run_pipeline(dataset=\"primary\"):",
        "    if \"RAW_DATA\" in globals():",
        "        data = RAW_DATA[dataset]",
        "    else:",
        "        data = RAW_EVENTS[dataset]",
        "    value = data",
    ]

    for chain_node in spec.chain:
        body_lines.append(f"    value = {chain_node.function}(value)")

    body_lines.append("    return value")
    content = "\n".join(import_lines) + "\n\n\n" + "\n".join(body_lines) + "\n"
    if not content.strip():
        raise ValueError("generated pipeline.py is empty")
    return content


def _write_files(output_dir: Path, files: dict[str, str]):
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        if not content.strip():
            raise ValueError(f"refusing to write empty generated file: {filename}")
        (output_dir / filename).write_text(content)
    for filename in files:
        file_path = output_dir / filename
        if not file_path.exists() or not file_path.read_text().strip():
            raise ValueError(f"generated file missing or empty: {filename}")


def _get_available_variants(extracted: dict) -> list[str]:
    """Return list of variant names (trap_1, trap_3, etc.) found in annotations."""
    variants = set()
    for fn in extracted["functions"]:
        role = fn["role"]
        if role.startswith("trap_"):
            variants.add(role)
    return sorted(variants)


def compile_single_case(case_name: str, variant: str | None = None) -> dict:
    module, case_file = _load_case_module(case_name)
    spec = module.build_case()
    extracted = _extract_functions(module, case_file)
    selected = _select_node_functions(case_name, spec, extracted, variant=variant)

    label = f"{case_name}" if not variant else f"{case_name} ({variant})"
    print(f"Compiling {label}:")
    for chain_node in spec.chain:
        function_record = selected[chain_node.name]
        print(f"  {chain_node.name} → {function_record['name']} [{function_record['role']}]")

    files = {
        "__init__.py": '"""Generated case package."""\n',
        "data.py": _build_data_file(module, extracted["data_globals"]),
    }
    for chain_node in spec.chain:
        files[chain_node.module] = _build_node_file(case_name, chain_node, selected[chain_node.name], extracted)
    files["pipeline.py"] = _build_pipeline_file(spec, extracted["data_globals"])

    dir_name = case_name if not variant else f"{case_name}_{variant}"
    output_dir = ROOT / case_name / "generated_cases" / dir_name
    _write_files(output_dir, files)

    return {
        "case_name": case_name,
        "variant": variant,
        "output_dir": str(output_dir),
        "files": files,
    }


def compile_all_cases() -> list[dict]:
    results = []
    for case_dir in sorted(ROOT.iterdir()):
        if not case_dir.is_dir():
            continue
        if not (case_dir / "cases").exists():
            continue

        case_name = case_dir.name
        module, case_file = _load_case_module(case_name)
        extracted = _extract_functions(module, case_file)

        results.append(compile_single_case(case_name))

        for variant in _get_available_variants(extracted):
            results.append(compile_single_case(case_name, variant=variant))

    return results


if __name__ == "__main__":
    compile_all_cases()
