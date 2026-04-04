"""AST tree renderer for the dashboard.

Parses Python code into an AST and renders a human-readable structural
summary showing functions, classes, arguments, assignments, and key calls.
"""

from __future__ import annotations

import ast


def render_ast_tree(code: str) -> str:
    """Parse Python code and return a human-readable AST structure string.

    Returns a tree showing:
    - Module-level functions with arguments
    - Classes with methods
    - Key assignments (module-level)
    - Call sites within functions (first level only)
    - Return statements

    Returns error string if code is unparseable.
    """
    if not code or not code.strip():
        return "(empty code)"

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"(syntax error: {e})"

    lines: list[str] = []
    _walk_module(tree, lines, indent=0)
    return "\n".join(lines) if lines else "(no top-level definitions)"


def _walk_module(tree: ast.Module, lines: list[str], indent: int) -> None:
    """Walk module-level nodes and render structure."""
    prefix = "  " * indent
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            _render_function(node, lines, indent)
        elif isinstance(node, ast.AsyncFunctionDef):
            _render_function(node, lines, indent, async_=True)
        elif isinstance(node, ast.ClassDef):
            _render_class(node, lines, indent)
        elif isinstance(node, ast.Assign):
            _render_assignment(node, lines, indent)
        elif isinstance(node, ast.Import):
            names = ", ".join(a.name for a in node.names)
            lines.append(f"{prefix}import {names}")
        elif isinstance(node, ast.ImportFrom):
            names = ", ".join(a.name for a in node.names)
            lines.append(f"{prefix}from {node.module} import {names}")


def _render_function(node, lines: list[str], indent: int,
                     async_: bool = False) -> None:
    """Render a function definition with args, decorators, body summary."""
    prefix = "  " * indent
    keyword = "async def" if async_ else "def"

    # Decorators
    for dec in node.decorator_list:
        dec_name = _node_name(dec)
        lines.append(f"{prefix}@{dec_name}")

    # Signature
    args = _format_args(node.args)
    ret = ""
    if node.returns:
        ret = f" -> {_node_name(node.returns)}"
    lines.append(f"{prefix}{keyword} {node.name}({args}){ret}:")

    # Body summary
    _render_body_summary(node, lines, indent + 1)


def _render_class(node: ast.ClassDef, lines: list[str],
                  indent: int) -> None:
    """Render a class with its methods."""
    prefix = "  " * indent

    bases = ", ".join(_node_name(b) for b in node.bases) if node.bases else ""
    base_str = f"({bases})" if bases else ""

    for dec in node.decorator_list:
        lines.append(f"{prefix}@{_node_name(dec)}")
    lines.append(f"{prefix}class {node.name}{base_str}:")

    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _render_function(child, lines, indent + 1,
                             async_=isinstance(child, ast.AsyncFunctionDef))
        elif isinstance(child, ast.Assign):
            _render_assignment(child, lines, indent + 1)


def _render_body_summary(func_node, lines: list[str],
                         indent: int) -> None:
    """Render key structural elements inside a function body."""
    prefix = "  " * indent

    for node in ast.iter_child_nodes(func_node):
        if isinstance(node, ast.For):
            iter_name = _node_name(node.iter)
            target = _node_name(node.target)
            lines.append(f"{prefix}for {target} in {iter_name}:")
            # Show calls inside loop
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.Expr) and isinstance(child.value, ast.Call):
                    call_name = _node_name(child.value.func)
                    lines.append(f"{prefix}  {call_name}(...)")
        elif isinstance(node, ast.If):
            test = _node_name(node.test)
            lines.append(f"{prefix}if {test}:")
        elif isinstance(node, ast.With):
            items = ", ".join(_node_name(i.context_expr) for i in node.items)
            lines.append(f"{prefix}with {items}:")
        elif isinstance(node, ast.Return):
            if node.value:
                val = _node_name(node.value)
                lines.append(f"{prefix}return {val}")
            else:
                lines.append(f"{prefix}return")
        elif isinstance(node, ast.Assign):
            targets = ", ".join(_node_name(t) for t in node.targets)
            value = _node_name(node.value)
            lines.append(f"{prefix}{targets} = {value}")
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call_name = _node_name(node.value.func)
            call_args = ", ".join(_node_name(a) for a in node.value.args[:3])
            if len(node.value.args) > 3:
                call_args += ", ..."
            lines.append(f"{prefix}{call_name}({call_args})")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Nested function
            _render_function(node, lines, indent,
                             async_=isinstance(node, ast.AsyncFunctionDef))


def _render_assignment(node: ast.Assign, lines: list[str],
                       indent: int) -> None:
    """Render a module-level or class-level assignment."""
    prefix = "  " * indent
    targets = ", ".join(_node_name(t) for t in node.targets)
    value = _node_name(node.value)
    lines.append(f"{prefix}{targets} = {value}")


def _format_args(args: ast.arguments) -> str:
    """Format function arguments into a readable string."""
    parts: list[str] = []
    n_args = len(args.args)
    n_defaults = len(args.defaults)
    for i, arg in enumerate(args.args):
        name = arg.arg
        ann = f": {_node_name(arg.annotation)}" if arg.annotation else ""
        default_idx = i - (n_args - n_defaults)
        if default_idx >= 0:
            default_val = _node_name(args.defaults[default_idx])
            parts.append(f"{name}{ann}={default_val}")
        else:
            parts.append(f"{name}{ann}")
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    for kw in args.kwonlyargs:
        name = kw.arg
        ann = f": {_node_name(kw.annotation)}" if kw.annotation else ""
        parts.append(f"{name}{ann}")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    return ", ".join(parts)


_OP_MAP = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.Mod: "%", ast.Pow: "**", ast.FloorDiv: "//",
    ast.BitOr: "|", ast.BitAnd: "&", ast.BitXor: "^",
    ast.LShift: "<<", ast.RShift: ">>",
    ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
    ast.Gt: ">", ast.GtE: ">=", ast.Is: "is", ast.IsNot: "is not",
    ast.In: "in", ast.NotIn: "not in",
    ast.Not: "not ", ast.USub: "-", ast.UAdd: "+", ast.Invert: "~",
}


def _op_str(op) -> str:
    return _OP_MAP.get(type(op), "?")


def _node_name(node) -> str:
    """Best-effort single-line string representation of an AST node."""
    if node is None:
        return "None"
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_node_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Constant):
        r = repr(node.value)
        return r if len(r) < 40 else r[:37] + "..."
    if isinstance(node, ast.Call):
        func = _node_name(node.func)
        args = ", ".join(_node_name(a) for a in node.args[:2])
        if len(node.args) > 2:
            args += ", ..."
        return f"{func}({args})"
    if isinstance(node, ast.List):
        if not node.elts:
            return "[]"
        elts = ", ".join(_node_name(e) for e in node.elts[:3])
        return f"[{elts}{'...' if len(node.elts) > 3 else ''}]"
    if isinstance(node, ast.Dict):
        if not node.keys:
            return "{}"
        pairs = []
        for k, v in zip(node.keys[:2], node.values[:2]):
            pairs.append(f"{_node_name(k)}: {_node_name(v)}")
        return "{" + ", ".join(pairs) + ("..." if len(node.keys) > 2 else "") + "}"
    if isinstance(node, ast.Tuple):
        elts = ", ".join(_node_name(e) for e in node.elts[:3])
        return f"({elts})"
    if isinstance(node, ast.Subscript):
        return f"{_node_name(node.value)}[{_node_name(node.slice)}]"
    if isinstance(node, ast.BoolOp):
        op = "and" if isinstance(node.op, ast.And) else "or"
        return f" {op} ".join(_node_name(v) for v in node.values[:3])
    if isinstance(node, ast.Compare):
        left = _node_name(node.left)
        parts = [left]
        for op, comp in zip(node.ops, node.comparators):
            parts.append(_op_str(op))
            parts.append(_node_name(comp))
        return " ".join(parts)
    if isinstance(node, ast.UnaryOp):
        return f"{_op_str(node.op)}{_node_name(node.operand)}"
    if isinstance(node, ast.BinOp):
        return f"{_node_name(node.left)} {_op_str(node.op)} {_node_name(node.right)}"
    if isinstance(node, ast.JoinedStr):
        return "f'...'"
    if isinstance(node, ast.IfExp):
        return f"{_node_name(node.body)} if {_node_name(node.test)} else {_node_name(node.orelse)}"
    if isinstance(node, ast.Starred):
        return f"*{_node_name(node.value)}"
    if isinstance(node, ast.ListComp):
        return "[... for ...]"
    if isinstance(node, ast.DictComp):
        return "{... for ...}"
    if isinstance(node, ast.SetComp):
        return "{... for ...}"
    if isinstance(node, ast.GeneratorExp):
        return "(... for ...)"
    if isinstance(node, ast.Lambda):
        return "lambda ..."
    return f"<{type(node).__name__}>"
