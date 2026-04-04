"""Component metadata loading and validation.

Metadata is the SOLE source of truth for component contracts.
AST is used ONLY for drift detection.
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any, Callable

from jinja2 import Environment, meta

from core.pipeline.prompting.contracts import ConditionalGroup, PromptComponent
from core.pipeline.prompting.exceptions import (
    PromptForbiddenConstructError,
    PromptMetadataDriftError,
    PromptRegistryError,
    PromptUndeclaredVariableError,
)
from core.pipeline.prompting.sections import VALID_SECTION_VALUES, Section

# Tags forbidden in prompt templates
_FORBIDDEN_TAGS = frozenset({
    "for", "endfor", "macro", "endmacro", "call", "endcall",
    "filter", "endfilter", "set", "block", "endblock",
    "extends", "import", "from",
})

# AST node types allowed in condition expressions
_ALLOWED_EXPR_NODES = {
    ast.Expression, ast.Compare, ast.BoolOp, ast.UnaryOp, ast.Not,
    ast.Name, ast.Constant, ast.Tuple, ast.Load,
    ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.And, ast.Or,
}


def validate_forbidden_tags(name: str, raw_template: str) -> None:
    """Reject templates using forbidden Jinja2 constructs."""
    tags = re.findall(r"\{%-?\s*(\w+)", raw_template)
    for tag in tags:
        if tag in _FORBIDDEN_TAGS:
            raise PromptForbiddenConstructError(
                f"Component '{name}' uses forbidden tag '{{% {tag} %}}'. "
                f"Only if/elif/else/endif are allowed."
            )


def extract_jinja_variables(raw_template: str) -> frozenset[str]:
    """Extract all variable references from a Jinja2 template via AST."""
    env = Environment()
    parsed = env.parse(raw_template)
    return frozenset(meta.find_undeclared_variables(parsed))


def extract_conditional_test_variables(raw_template: str) -> frozenset[str]:
    """Extract variables used in {% if %} test expressions.

    These are variables used for branching, potentially control inputs.
    """
    # Match {% if VAR ... %} and {% elif VAR ... %} patterns
    # This is a heuristic — catches simple cases like {% if x %} and
    # {% if x == "y" %} but not complex nested expressions.
    pattern = r"\{%-?\s*(?:if|elif)\s+(\w+)"
    matches = re.findall(pattern, raw_template)
    return frozenset(matches)


def compile_condition_expr(expr: str) -> Callable[[dict[str, Any]], bool]:
    """Parse and compile a restricted condition expression.

    Supports: ==, !=, in, not in, and, or, not, string/bool/None literals.
    Rejects: function calls, attribute access, subscripts, arithmetic.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise PromptRegistryError(
            f"Invalid condition expression '{expr}': {e}"
        )

    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_EXPR_NODES:
            raise PromptRegistryError(
                f"Condition expression '{expr}' uses disallowed construct: "
                f"{type(node).__name__}. "
                f"Allowed: {sorted(n.__name__ for n in _ALLOWED_EXPR_NODES)}"
            )

    code = compile(tree, "<condition>", "eval")

    def evaluator(inputs: dict[str, Any]) -> bool:
        try:
            return bool(eval(code, {"__builtins__": {}}, inputs))  # noqa: S307
        except NameError as e:
            from core.pipeline.prompting.exceptions import PromptValidationError
            raise PromptValidationError(
                f"Condition '{expr}' references undefined variable: {e}"
            ) from e
        except Exception as e:
            from core.pipeline.prompting.exceptions import PromptValidationError
            raise PromptValidationError(
                f"Condition '{expr}' evaluation failed: {e}"
            ) from e

    return evaluator


def validate_template_against_metadata(component: PromptComponent) -> None:
    """Verify metadata and template are consistent.

    Raises:
        PromptUndeclaredVariableError: template uses variable not in metadata
        PromptMetadataDriftError: metadata declares non-control variable
            not referenced in template
    """
    ast_vars = extract_jinja_variables(component.raw_template)

    declared = component.all_declared_inputs

    undeclared = ast_vars - declared
    if undeclared:
        raise PromptUndeclaredVariableError(
            f"Template '{component.name}' references undeclared variables: "
            f"{sorted(undeclared)}. Declared: {sorted(declared)}"
        )

    # Check for declared-but-unreferenced (excluding control inputs)
    non_control_declared = declared - component.control_inputs
    unreferenced = non_control_declared - ast_vars
    if unreferenced:
        raise PromptMetadataDriftError(
            f"Metadata for '{component.name}' declares variables not "
            f"referenced in template: {sorted(unreferenced)}. "
            f"Either add to template, mark as control_input, or remove."
        )


def validate_control_inputs(component: PromptComponent) -> None:
    """Verify control inputs are actually used in conditionals.

    Control inputs must appear in at least one conditional group's
    condition_expr OR in a template {% if %} block.
    """
    cg_variables: set[str] = set()
    for cg in component.conditional_groups:
        # Extract variable names from condition expression
        try:
            tree = ast.parse(cg.condition_expr, mode="eval")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                cg_variables.add(node.id)

    ast_conditionals = extract_conditional_test_variables(component.raw_template)
    used_controls = cg_variables | ast_conditionals

    unused = component.control_inputs - used_controls
    if unused:
        raise PromptMetadataDriftError(
            f"Component '{component.name}' declares control_inputs "
            f"{sorted(unused)} not used in any conditional group or "
            "template {%% if %%} block."
        )


def load_component_from_metadata(
    name: str,
    template_path: Path,
    meta_entry: dict[str, Any],
) -> PromptComponent:
    """Build a PromptComponent from a metadata entry and template file.

    All contract fields come from meta_entry. Template file provides
    only raw_template and content_hash.
    """
    raw_template = template_path.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(raw_template.encode("utf-8")).hexdigest()

    # Parse exports as Section enum values
    exports: list[Section] = []
    for s in meta_entry.get("exports", []):
        if s not in VALID_SECTION_VALUES:
            raise PromptRegistryError(
                f"Component '{name}' exports unknown section '{s}'. "
                f"Valid: {sorted(VALID_SECTION_VALUES)}"
            )
        exports.append(Section(s))

    # Parse conditional groups
    cond_groups: list[ConditionalGroup] = []
    for cg_raw in meta_entry.get("conditional_groups", []):
        cond_fn = compile_condition_expr(cg_raw["condition_expr"])
        cond_groups.append(ConditionalGroup(
            name=cg_raw["name"],
            condition=cond_fn,
            condition_expr=cg_raw["condition_expr"],
            required_inputs=frozenset(cg_raw.get("required_inputs", [])),
            optional_inputs=frozenset(cg_raw.get("optional_inputs", [])),
        ))

    return PromptComponent(
        name=name,
        version=meta_entry.get("version", "0.0.0"),
        path=template_path,
        content_hash=content_hash,
        raw_template=raw_template,
        required_inputs=frozenset(meta_entry.get("required_inputs", [])),
        optional_inputs=frozenset(meta_entry.get("optional_inputs", [])),
        control_inputs=frozenset(meta_entry.get("control_inputs", [])),
        input_types=meta_entry.get("input_types", {}),
        conditional_groups=tuple(cond_groups),
        exports=tuple(exports),
        dependencies=tuple(meta_entry.get("dependencies", [])),
        before=tuple(meta_entry.get("before", [])),
        after=tuple(meta_entry.get("after", [])),
        forbidden_with=tuple(meta_entry.get("forbidden_with", [])),
        description=meta_entry.get("description", ""),
        tags=tuple(meta_entry.get("tags", [])),
    )


def generate_metadata_from_ast(template_path: Path) -> dict[str, Any]:
    """Generate DRAFT metadata from template AST.

    Returns a dict suitable for component_metadata.yaml.
    This is a DRAFT — human must review and confirm.
    All variables are classified as required by default.
    Conditional variables are classified as optional.
    """
    raw = template_path.read_text(encoding="utf-8")
    all_vars = extract_jinja_variables(raw)
    conditional_vars = extract_conditional_test_variables(raw)
    unconditional_vars = all_vars - conditional_vars

    return {
        "name": template_path.stem,
        "version": "1.0.0",
        "description": "AUTO-GENERATED — review required",
        "required_inputs": sorted(unconditional_vars),
        "optional_inputs": sorted(conditional_vars - unconditional_vars),
        "control_inputs": [],
        "input_types": {v: "str" for v in sorted(all_vars)},
        "conditional_groups": [],
        "exports": [],
        "dependencies": [],
        "before": [],
        "after": [],
        "forbidden_with": [],
        "tags": [],
    }
