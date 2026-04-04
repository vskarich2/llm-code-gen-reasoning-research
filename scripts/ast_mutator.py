"""Three-layer AST mutation system.

Layer 1: Semantic Targeting — identify what invariant structure to break
Layer 2: AST Localization — find the exact nodes that implement it
Layer 3: AST Transformation — apply structured mutation

No regex. No string replacement. Every mutation maps to a causal invariant violation.
"""

import ast
import copy
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# LAYER 1: SEMANTIC TARGETS
# ============================================================

@dataclass
class SemanticTarget:
    """Describes what invariant structure to break."""
    kind: str           # e.g., "copy_call", "method_call", "comparison", "branch", "assignment"
    node: ast.AST       # the exact AST node
    function: str       # enclosing function name
    line: int           # line number
    description: str    # human-readable description of what this target does for the invariant


@dataclass
class MutationIntent:
    """Describes the intended invariant violation."""
    target: SemanticTarget
    transform: str      # name of the transform to apply
    expected_violation: str  # what invariant this breaks


@dataclass
class MutationOutcome:
    """Result of attempting a mutation."""
    applied: bool
    mutated_code: str | None
    intent: MutationIntent | None
    targets_found: int
    rejection_reason: str | None


# ============================================================
# LAYER 2: AST LOCALIZATION — FINDERS
# ============================================================

def _enclosing_function(tree: ast.Module, node: ast.AST) -> str | None:
    """Find the function name that encloses a node."""
    for parent in ast.walk(tree):
        if isinstance(parent, ast.FunctionDef):
            for child in ast.walk(parent):
                if child is node:
                    return parent.name
    return None


def find_copy_calls(tree: ast.Module) -> list[SemanticTarget]:
    """Find .copy(), dict(), {**x} calls that create independent copies."""
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # x.copy()
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "copy"
                    and not node.args and not node.keywords):
                fn = _enclosing_function(tree, node)
                targets.append(SemanticTarget(
                    kind="copy_call", node=node, function=fn or "?",
                    line=getattr(node, "lineno", 0),
                    description=f".copy() call creating independent object",
                ))
            # dict(x)
            elif (isinstance(node.func, ast.Name) and node.func.id == "dict"
                  and len(node.args) == 1 and not node.keywords):
                fn = _enclosing_function(tree, node)
                targets.append(SemanticTarget(
                    kind="copy_call", node=node, function=fn or "?",
                    line=getattr(node, "lineno", 0),
                    description=f"dict() call creating independent copy",
                ))
    return targets


def find_method_calls(tree: ast.Module, method_names: list[str]) -> list[SemanticTarget]:
    """Find calls to specific methods (e.g., .pop(), .release(), .append())."""
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute) and func.attr in method_names:
                fn = _enclosing_function(tree, node)
                targets.append(SemanticTarget(
                    kind="method_call", node=node, function=fn or "?",
                    line=getattr(node, "lineno", 0),
                    description=f".{func.attr}() call",
                ))
    return targets


def find_function_calls(tree: ast.Module, func_names: list[str]) -> list[SemanticTarget]:
    """Find standalone function call statements by name."""
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id in func_names:
                fn = _enclosing_function(tree, node)
                targets.append(SemanticTarget(
                    kind="function_call", node=node, function=fn or "?",
                    line=getattr(node, "lineno", 0),
                    description=f"{func.id}() call",
                ))
    return targets


def find_comparisons(tree: ast.Module, ops: list[type] = None) -> list[SemanticTarget]:
    """Find comparison operators (>=, <=, ==, etc.)."""
    ops = ops or [ast.GtE, ast.LtE]
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op in node.ops:
                if type(op) in ops:
                    fn = _enclosing_function(tree, node)
                    targets.append(SemanticTarget(
                        kind="comparison", node=node, function=fn or "?",
                        line=getattr(node, "lineno", 0),
                        description=f"comparison with {type(op).__name__}",
                    ))
    return targets


def find_branches(tree: ast.Module) -> list[SemanticTarget]:
    """Find if/elif/else branches."""
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and node.orelse:
            fn = _enclosing_function(tree, node)
            targets.append(SemanticTarget(
                kind="branch", node=node, function=fn or "?",
                line=getattr(node, "lineno", 0),
                description="if/else branch",
            ))
    return targets


def find_assignments_to(tree: ast.Module, names: list[str]) -> list[SemanticTarget]:
    """Find assignments to specific variable names (e.g., display_name, _cache)."""
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                # x["key"] = ...
                if isinstance(target, ast.Subscript):
                    if isinstance(target.value, ast.Name) and target.value.id in names:
                        fn = _enclosing_function(tree, node)
                        targets.append(SemanticTarget(
                            kind="assignment", node=node, function=fn or "?",
                            line=getattr(node, "lineno", 0),
                            description=f"assignment to {target.value.id}[...]",
                        ))
                    if isinstance(target.slice, ast.Constant) and target.slice.value in names:
                        fn = _enclosing_function(tree, node)
                        targets.append(SemanticTarget(
                            kind="assignment", node=node, function=fn or "?",
                            line=getattr(node, "lineno", 0),
                            description=f"assignment to ...['{target.slice.value}']",
                        ))
                # x = ...
                if isinstance(target, ast.Name) and target.id in names:
                    fn = _enclosing_function(tree, node)
                    targets.append(SemanticTarget(
                        kind="assignment", node=node, function=fn or "?",
                        line=getattr(node, "lineno", 0),
                        description=f"assignment to {target.id}",
                    ))
    return targets


def find_default_params(tree: ast.Module, is_none: bool = True) -> list[SemanticTarget]:
    """Find function parameters with None defaults (mutable default pattern)."""
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for i, default in enumerate(node.args.defaults):
                if is_none and isinstance(default, ast.Constant) and default.value is None:
                    param_idx = len(node.args.args) - len(node.args.defaults) + i
                    param_name = node.args.args[param_idx].arg
                    targets.append(SemanticTarget(
                        kind="default_param", node=node, function=node.name,
                        line=getattr(node, "lineno", 0),
                        description=f"parameter {param_name}=None (guards mutable default)",
                    ))
    return targets


def find_insert_calls(tree: ast.Module) -> list[SemanticTarget]:
    """Find list.insert(pos, val) calls."""
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Attribute) and node.func.attr == "insert"
                    and len(node.args) == 2):
                fn = _enclosing_function(tree, node)
                targets.append(SemanticTarget(
                    kind="insert_call", node=node, function=fn or "?",
                    line=getattr(node, "lineno", 0),
                    description="list.insert(pos, val) maintaining index alignment",
                ))
    return targets


def find_augmented_assignments(tree: ast.Module, attr_names: list[str]) -> list[SemanticTarget]:
    """Find obj.attr += value augmented assignments."""
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Attribute) and node.target.attr in attr_names:
                obj_name = node.target.value.id if isinstance(node.target.value, ast.Name) else "?"
                fn = _enclosing_function(tree, node)
                targets.append(SemanticTarget(
                    kind="aug_assign", node=node, function=fn or "?",
                    line=getattr(node, "lineno", 0),
                    description=f"{obj_name}.{node.target.attr} {type(node.op).__name__}= ...",
                ))
    return targets


def find_constants(tree: ast.Module, value: Any) -> list[SemanticTarget]:
    """Find specific constant values in the AST."""
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == value:
            fn = _enclosing_function(tree, node)
            targets.append(SemanticTarget(
                kind="constant", node=node, function=fn or "?",
                line=getattr(node, "lineno", 0),
                description=f"constant value {value!r}",
            ))
    return targets


def find_subscript_reads(tree: ast.Module, var_names: list[str]) -> list[SemanticTarget]:
    """Find x["key"] reads (for eager capture mutations)."""
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Subscript):
            sub = node.value
            if isinstance(sub.value, ast.Name) and sub.value.id in var_names:
                fn = _enclosing_function(tree, node)
                targets.append(SemanticTarget(
                    kind="subscript_read", node=node, function=fn or "?",
                    line=getattr(node, "lineno", 0),
                    description=f"return {sub.value.id}[...] (lazy read)",
                ))
    return targets


# ============================================================
# LAYER 3: AST TRANSFORMATIONS
# ============================================================

class _RemoveCopy(ast.NodeTransformer):
    """Transform .copy()/dict() → direct reference."""
    def __init__(self, target_node):
        self.target_node = target_node
        self.applied = False

    def visit_Call(self, node):
        self.generic_visit(node)
        if node is self.target_node:
            self.applied = True
            if isinstance(node.func, ast.Attribute) and node.func.attr == "copy":
                return node.func.value
            if isinstance(node.func, ast.Name) and node.func.id == "dict":
                return node.args[0]
        return node


class _DeleteStatement(ast.NodeTransformer):
    """Delete a specific statement node, replacing with pass if needed."""
    def __init__(self, target_node):
        self.target_node = target_node
        self.applied = False

    def visit(self, node):
        result = super().visit(node)
        return result

    def generic_visit(self, node):
        for field_name, value in ast.iter_fields(node):
            if isinstance(value, list):
                new_list = []
                for item in value:
                    if isinstance(item, ast.AST):
                        if item is self.target_node:
                            self.applied = True
                            new_list.append(ast.Pass())
                            continue
                    new_list.append(item)
                    if isinstance(item, ast.AST):
                        self.visit(item)
                setattr(node, field_name, new_list)
            elif isinstance(value, ast.AST):
                self.visit(value)
        return node


class _FlipComparison(ast.NodeTransformer):
    """Change >= to > or <= to <."""
    def __init__(self, target_node):
        self.target_node = target_node
        self.applied = False

    def visit_Compare(self, node):
        self.generic_visit(node)
        if node is self.target_node:
            new_ops = []
            for op in node.ops:
                if isinstance(op, ast.GtE):
                    new_ops.append(ast.Gt())
                    self.applied = True
                elif isinstance(op, ast.LtE):
                    new_ops.append(ast.Lt())
                    self.applied = True
                else:
                    new_ops.append(op)
            node.ops = new_ops
        return node


class _RemoveBranch(ast.NodeTransformer):
    """Remove else/elif branch from an if statement."""
    def __init__(self, target_node):
        self.target_node = target_node
        self.applied = False

    def visit_If(self, node):
        self.generic_visit(node)
        if node is self.target_node and node.orelse:
            node.orelse = []
            self.applied = True
        return node


class _InsertToAppend(ast.NodeTransformer):
    """Change list.insert(pos, val) to list.append(val)."""
    def __init__(self, target_node):
        self.target_node = target_node
        self.applied = False

    def visit_Call(self, node):
        self.generic_visit(node)
        if node is self.target_node:
            node.func.attr = "append"
            node.args = [node.args[1]]
            self.applied = True
        return node


class _ChangeConstant(ast.NodeTransformer):
    """Change a constant value."""
    def __init__(self, target_node, new_value):
        self.target_node = target_node
        self.new_value = new_value
        self.applied = False

    def visit_Constant(self, node):
        if node is self.target_node:
            node.value = self.new_value
            self.applied = True
        return node


class _RestoreMutableDefault(ast.NodeTransformer):
    """Change def f(x=None) to def f(x=[]) and remove the None guard."""
    def __init__(self, target_node, param_name):
        self.target_node = target_node
        self.param_name = param_name
        self.applied = False

    def visit_FunctionDef(self, node):
        if node is not self.target_node:
            self.generic_visit(node)
            return node
        # Change None default to []
        for i, default in enumerate(node.args.defaults):
            if isinstance(default, ast.Constant) and default.value is None:
                param_idx = len(node.args.args) - len(node.args.defaults) + i
                if node.args.args[param_idx].arg == self.param_name:
                    node.args.defaults[i] = ast.List(elts=[], ctx=ast.Load())
                    self.applied = True
        # Remove `if param is None: param = []`
        new_body = []
        for stmt in node.body:
            if isinstance(stmt, ast.If) and self.applied:
                test = stmt.test
                if (isinstance(test, ast.Compare) and len(test.ops) == 1
                        and isinstance(test.ops[0], ast.Is)
                        and isinstance(test.left, ast.Name)
                        and test.left.id == self.param_name):
                    continue
            new_body.append(stmt)
        if new_body != node.body:
            node.body = new_body
        self.generic_visit(node)
        return node


# ============================================================
# MUTATION APPLICATION
# ============================================================

def _apply_transform(code: str, tree: ast.Module, target: SemanticTarget,
                     transformer_class, *args) -> str | None:
    """Apply a targeted AST transformation. Returns mutated code or None."""
    tree_copy = copy.deepcopy(tree)

    # Re-locate the target node in the copy by line number and kind
    target_in_copy = None
    for node in ast.walk(tree_copy):
        if (type(node) == type(target.node)
                and getattr(node, "lineno", -1) == target.line):
            target_in_copy = node
            break

    if target_in_copy is None:
        return None

    transformer = transformer_class(target_in_copy, *args)
    new_tree = transformer.visit(tree_copy)

    if not transformer.applied:
        return None

    ast.fix_missing_locations(new_tree)
    try:
        result = ast.unparse(new_tree)
        return result if result != code else None
    except Exception:
        return None


# ============================================================
# SEMANTIC MUTATION OPERATORS
# ============================================================

@dataclass
class SemanticOperator:
    name: str
    description: str
    families: list[str]
    invariant_violated: str

    def find_targets(self, tree: ast.Module) -> list[SemanticTarget]:
        raise NotImplementedError

    def mutate(self, code: str, tree: ast.Module, target: SemanticTarget) -> str | None:
        raise NotImplementedError


class RemoveCopyOperator(SemanticOperator):
    def __init__(self):
        super().__init__(
            "remove_copy", "Remove .copy()/dict() → shared reference aliasing",
            ["alias_config"], "independence: returned objects share memory",
        )

    def find_targets(self, tree):
        return find_copy_calls(tree)

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _RemoveCopy)


class RemoveMethodCallOperator(SemanticOperator):
    def __init__(self, name, desc, families, invariant, method_names):
        super().__init__(name, desc, families, invariant)
        self.method_names = method_names

    def find_targets(self, tree):
        return find_method_calls(tree, self.method_names)

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _DeleteStatement)


class RemoveFunctionCallOperator(SemanticOperator):
    def __init__(self, name, desc, families, invariant, func_names):
        super().__init__(name, desc, families, invariant)
        self.func_names = func_names

    def find_targets(self, tree):
        return find_function_calls(tree, self.func_names)

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _DeleteStatement)


class FlipComparisonOperator(SemanticOperator):
    def __init__(self):
        super().__init__(
            "flip_comparison", "Change >= to > or <= to < (off-by-one)",
            ["wrong_condition"], "boundary: off-by-one at threshold",
        )

    def find_targets(self, tree):
        return find_comparisons(tree, [ast.GtE, ast.LtE])

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _FlipComparison)


class RemoveBranchOperator(SemanticOperator):
    def __init__(self):
        super().__init__(
            "remove_branch", "Remove else/elif branch from dispatch",
            ["missing_branch"], "branch_coverage: valid input gets no output",
        )

    def find_targets(self, tree):
        return find_branches(tree)

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _RemoveBranch)


class InsertToAppendOperator(SemanticOperator):
    def __init__(self):
        super().__init__(
            "insert_to_append", "Change insert(pos,val) to append(val)",
            ["index_misalign"], "structure_alignment: wrong position in parallel array",
        )

    def find_targets(self, tree):
        return find_insert_calls(tree)

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _InsertToAppend)


class ChangeConstantOperator(SemanticOperator):
    def __init__(self, name, desc, families, invariant, old_value, new_value):
        super().__init__(name, desc, families, invariant)
        self.old_value = old_value
        self.new_value = new_value

    def find_targets(self, tree):
        return find_constants(tree, self.old_value)

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _ChangeConstant, self.new_value)


class RestoreMutableDefaultOperator(SemanticOperator):
    PARAM_NAMES = ["queue", "seen", "history", "items", "results", "acc", "memo",
                   "visited", "cache", "collected", "batch"]

    def __init__(self):
        super().__init__(
            "restore_mutable_default", "Restore mutable default argument",
            ["mutable_default"], "idempotence: state shared across calls",
        )

    def find_targets(self, tree):
        return find_default_params(tree, is_none=True)

    def mutate(self, code, tree, target):
        # Find the parameter name from the target
        node = target.node
        if isinstance(node, ast.FunctionDef):
            for i, default in enumerate(node.args.defaults):
                if isinstance(default, ast.Constant) and default.value is None:
                    param_idx = len(node.args.args) - len(node.args.defaults) + i
                    param_name = node.args.args[param_idx].arg
                    result = _apply_transform(code, tree, target, _RestoreMutableDefault, param_name)
                    if result:
                        return result
        return None


class RemoveAssignmentOperator(SemanticOperator):
    def __init__(self, name, desc, families, invariant, target_names):
        super().__init__(name, desc, families, invariant)
        self.target_names = target_names

    def find_targets(self, tree):
        return find_assignments_to(tree, self.target_names)

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _DeleteStatement)


# ============================================================
# LAYER 3b: ADVANCED TRANSFORMERS (for mutation plans)
# ============================================================

class _SwapCallArgument(ast.NodeTransformer):
    """Swap a function call's argument from one name to another.

    e.g., compute_raw_stats(case_data) → compute_raw_stats(cleaned)
    """
    def __init__(self, target_node, old_name: str, new_name: str):
        self.target_node = target_node
        self.old_name = old_name
        self.new_name = new_name
        self.applied = False

    def visit_Call(self, node):
        self.generic_visit(node)
        if node is self.target_node:
            for i, arg in enumerate(node.args):
                if isinstance(arg, ast.Name) and arg.id == self.old_name:
                    node.args[i] = ast.Name(id=self.new_name, ctx=ast.Load())
                    self.applied = True
                    return node
        return node


class _AddModuleLevelAssignment(ast.NodeTransformer):
    """Add an eager capture assignment at module level.

    e.g., Add: _cached = _settings["host"] after _settings = {...}
    """
    def __init__(self, source_var: str, key: str, capture_name: str):
        self.source_var = source_var
        self.key = key
        self.capture_name = capture_name
        self.applied = False

    def visit_Module(self, node):
        new_body = []
        for stmt in node.body:
            new_body.append(stmt)
            # After the source variable assignment, add the capture
            if (isinstance(stmt, ast.Assign) and not self.applied):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == self.source_var:
                        capture = ast.Assign(
                            targets=[ast.Name(id=self.capture_name, ctx=ast.Store())],
                            value=ast.Subscript(
                                value=ast.Name(id=self.source_var, ctx=ast.Load()),
                                slice=ast.Constant(value=self.key),
                                ctx=ast.Load(),
                            ),
                        )
                        new_body.append(capture)
                        self.applied = True
        node.body = new_body
        return node


class _ReplaceReturnWithCaptured(ast.NodeTransformer):
    """Replace return x["key"] with return _captured_var."""
    def __init__(self, source_var: str, key: str, capture_name: str):
        self.source_var = source_var
        self.key = key
        self.capture_name = capture_name
        self.applied = False

    def visit_Return(self, node):
        if (isinstance(node.value, ast.Subscript)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == self.source_var
                and isinstance(node.value.slice, ast.Constant)
                and node.value.slice.value == self.key):
            node.value = ast.Name(id=self.capture_name, ctx=ast.Load())
            self.applied = True
        return node


class _RemoveDictEntry(ast.NodeTransformer):
    """Remove a specific key from a dict literal."""
    def __init__(self, key_to_remove: str):
        self.key_to_remove = key_to_remove
        self.applied = False

    def visit_Dict(self, node):
        self.generic_visit(node)
        new_keys = []
        new_values = []
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == self.key_to_remove:
                self.applied = True
                continue
            new_keys.append(k)
            new_values.append(v)
        if self.applied:
            node.keys = new_keys
            node.values = new_values
        return node


class _RemoveElifByTest(ast.NodeTransformer):
    """Remove a specific elif branch that tests for a particular value."""
    def __init__(self, test_value: str):
        self.test_value = test_value
        self.applied = False

    def visit_If(self, node):
        self.generic_visit(node)
        # Check if this elif tests for our value
        if node.orelse:
            new_orelse = []
            for child in node.orelse:
                if isinstance(child, ast.If):
                    # Check if this elif's test mentions our value
                    test_src = ast.dump(child.test)
                    if self.test_value in test_src:
                        # Skip this elif — carry its else forward
                        new_orelse.extend(child.orelse)
                        self.applied = True
                        continue
                new_orelse.append(child)
            node.orelse = new_orelse
        return node


class _RemoveInitAssignment(ast.NodeTransformer):
    """Remove a variable initialization that precedes a conditional.

    Finds: var = [] / var = None / var = 0 before an if block.
    """
    def __init__(self, var_name: str):
        self.var_name = var_name
        self.applied = False

    def visit_FunctionDef(self, node):
        new_body = []
        for i, stmt in enumerate(node.body):
            if (isinstance(stmt, ast.Assign) and not self.applied):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == self.var_name:
                        # Check if next statement is an if
                        if i + 1 < len(node.body) and isinstance(node.body[i + 1], ast.If):
                            self.applied = True
                            continue  # skip this assignment
            new_body.append(stmt)
        if self.applied:
            node.body = new_body if new_body else [ast.Pass()]
        self.generic_visit(node)
        return node


# ============================================================
# PLAN-BASED OPERATORS (coordinate multiple edits)
# ============================================================

class SwapArgumentOperator(SemanticOperator):
    """Swap a function call argument to use the wrong variable."""
    def __init__(self, name, desc, families, invariant, func_name, old_arg, new_arg):
        super().__init__(name, desc, families, invariant)
        self.func_name = func_name
        self.old_arg = old_arg
        self.new_arg = new_arg

    def find_targets(self, tree):
        targets = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == self.func_name:
                    for arg in node.args:
                        if isinstance(arg, ast.Name) and arg.id == self.old_arg:
                            fn = _enclosing_function(tree, node)
                            targets.append(SemanticTarget(
                                kind="call_argument", node=node, function=fn or "?",
                                line=getattr(node, "lineno", 0),
                                description=f"{self.func_name}({self.old_arg}) → should use {self.new_arg}",
                            ))
        return targets

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _SwapCallArgument, self.old_arg, self.new_arg)


class EagerCaptureOperator(SemanticOperator):
    """Add module-level eager capture + replace lazy reads with captured value.

    This is a MULTI-EDIT plan: add assignment + replace return.
    """
    def __init__(self):
        super().__init__(
            "eager_capture", "Add eager module-level capture of config value",
            ["lazy_init"], "lifecycle: stale value after reset",
        )

    def find_targets(self, tree):
        """Find return x['key'] statements that read from config dicts."""
        targets = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Subscript):
                sub = node.value
                if (isinstance(sub.value, ast.Name)
                        and isinstance(sub.slice, ast.Constant)
                        and isinstance(sub.slice.value, str)):
                    fn = _enclosing_function(tree, node)
                    targets.append(SemanticTarget(
                        kind="lazy_read", node=node, function=fn or "?",
                        line=getattr(node, "lineno", 0),
                        description=f"return {sub.value.id}['{sub.slice.value}'] (lazy read)",
                    ))
        return targets

    def mutate(self, code, tree, target):
        """Multi-edit: add capture + replace return."""
        sub = target.node.value
        source_var = sub.value.id
        key = sub.slice.value
        capture_name = f"_cached_{key}"

        try:
            tree_copy = copy.deepcopy(tree)
        except Exception:
            return None

        # Step 1: Add module-level capture
        adder = _AddModuleLevelAssignment(source_var, key, capture_name)
        tree_copy = adder.visit(tree_copy)
        if not adder.applied:
            return None

        # Step 2: Replace return with captured value
        replacer = _ReplaceReturnWithCaptured(source_var, key, capture_name)
        tree_copy = replacer.visit(tree_copy)
        if not replacer.applied:
            return None

        ast.fix_missing_locations(tree_copy)
        try:
            result = ast.unparse(tree_copy)
            return result if result != code else None
        except Exception:
            return None


class RemoveDictEntryOperator(SemanticOperator):
    """Remove a specific key from a dict literal (missing branch/case)."""
    def __init__(self, name, desc, families, invariant, keys_to_try):
        super().__init__(name, desc, families, invariant)
        self.keys_to_try = keys_to_try

    def find_targets(self, tree):
        targets = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k in node.keys:
                    if isinstance(k, ast.Constant) and k.value in self.keys_to_try:
                        fn = _enclosing_function(tree, node)
                        targets.append(SemanticTarget(
                            kind="dict_entry", node=node, function=fn or "?",
                            line=getattr(node, "lineno", 0),
                            description=f"dict entry '{k.value}'",
                        ))
        return targets

    def mutate(self, code, tree, target):
        """Try removing each key. Returns first successful mutation."""
        for key in self.keys_to_try:
            tree_copy = copy.deepcopy(tree)
            remover = _RemoveDictEntry(key)
            tree_copy = remover.visit(tree_copy)
            if remover.applied:
                ast.fix_missing_locations(tree_copy)
                try:
                    result = ast.unparse(tree_copy)
                    if result != code:
                        return result
                except Exception:
                    continue
        return None

    def mutate_all(self, code, tree, target):
        """Return ALL possible mutations (one per removable key)."""
        results = []
        for key in self.keys_to_try:
            tree_copy = copy.deepcopy(tree)
            remover = _RemoveDictEntry(key)
            tree_copy = remover.visit(tree_copy)
            if remover.applied:
                ast.fix_missing_locations(tree_copy)
                try:
                    result = ast.unparse(tree_copy)
                    if result != code:
                        results.append(result)
                except Exception:
                    continue
        return results


class RemoveElifOperator(SemanticOperator):
    """Remove a specific elif branch by test value."""
    def __init__(self, name, desc, families, invariant, test_values):
        super().__init__(name, desc, families, invariant)
        self.test_values = test_values

    def find_targets(self, tree):
        targets = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and node.orelse:
                for child in node.orelse:
                    if isinstance(child, ast.If):
                        test_src = ast.dump(child.test)
                        for val in self.test_values:
                            if val in test_src:
                                fn = _enclosing_function(tree, node)
                                targets.append(SemanticTarget(
                                    kind="elif_branch", node=node, function=fn or "?",
                                    line=getattr(node, "lineno", 0),
                                    description=f"elif branch testing '{val}'",
                                ))
        return targets

    def mutate(self, code, tree, target):
        for val in self.test_values:
            tree_copy = copy.deepcopy(tree)
            remover = _RemoveElifByTest(val)
            tree_copy = remover.visit(tree_copy)
            if remover.applied:
                ast.fix_missing_locations(tree_copy)
                try:
                    result = ast.unparse(tree_copy)
                    if result != code:
                        return result
                except Exception:
                    continue
        return None


class RemoveInitializationOperator(SemanticOperator):
    """Remove variable initialization before a conditional (use-before-set)."""
    def __init__(self):
        super().__init__(
            "remove_initialization",
            "Remove variable init before conditional → use-before-set",
            ["use_before_set"],
            "no_exception: variable undefined on edge path",
        )

    def find_targets(self, tree):
        targets = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for i, stmt in enumerate(node.body):
                    if isinstance(stmt, ast.Assign):
                        for target_node in stmt.targets:
                            if isinstance(target_node, ast.Name):
                                # Check if followed by an if
                                if i + 1 < len(node.body) and isinstance(node.body[i + 1], ast.If):
                                    targets.append(SemanticTarget(
                                        kind="init_before_if", node=stmt,
                                        function=node.name,
                                        line=getattr(stmt, "lineno", 0),
                                        description=f"{target_node.id} = ... before if block",
                                    ))
        return targets

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _DeleteStatement)


class RemoveReturnValueOperator(SemanticOperator):
    """Change a return to return the wrong thing (e.g., cached stale value)."""
    def __init__(self, name, desc, families, invariant):
        super().__init__(name, desc, families, invariant)

    def find_targets(self, tree):
        targets = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and node.value is not None:
                fn = _enclosing_function(tree, node)
                if fn:
                    targets.append(SemanticTarget(
                        kind="return", node=node, function=fn,
                        line=getattr(node, "lineno", 0),
                        description=f"return statement in {fn}",
                    ))
        return targets

    def mutate(self, code, tree, target):
        """Replace return value with a stale/default value."""
        tree_copy = copy.deepcopy(tree)
        for node in ast.walk(tree_copy):
            if (isinstance(node, ast.Return)
                    and getattr(node, "lineno", -1) == target.line):
                # Replace with return None (simulating silent fallback)
                node.value = ast.Constant(value=None)
                ast.fix_missing_locations(tree_copy)
                try:
                    result = ast.unparse(tree_copy)
                    return result if result != code else None
                except Exception:
                    return None
        return None


# ============================================================
# ADVANCED TRANSFORMERS: PROGRAM-LEVEL REWRITES
# ============================================================

class _RelaxComparison(ast.NodeTransformer):
    """Relax a comparison: Lt→LtE, Gt→GtE (allow one extra past boundary)."""
    def __init__(self, target_node):
        self.target_node = target_node
        self.applied = False

    def visit_Compare(self, node):
        self.generic_visit(node)
        if node is self.target_node:
            new_ops = []
            for op in node.ops:
                if isinstance(op, ast.Lt):
                    new_ops.append(ast.LtE())
                    self.applied = True
                elif isinstance(op, ast.Gt):
                    new_ops.append(ast.GtE())
                    self.applied = True
                else:
                    new_ops.append(op)
            node.ops = new_ops
        return node


class _CorruptStringConstant(ast.NodeTransformer):
    """Change a specific string constant to a plausible wrong variant."""
    def __init__(self, target_node, new_value: str):
        self.target_node = target_node
        self.new_value = new_value
        self.applied = False

    def visit_Constant(self, node):
        if node is self.target_node and isinstance(node.value, str):
            node.value = self.new_value
            self.applied = True
        return node


class _UnwrapTryExcept(ast.NodeTransformer):
    """Remove try/except, keeping only the try body. Deletes rollback handlers."""
    def __init__(self, target_node):
        self.target_node = target_node
        self.applied = False

    def visit_Try(self, node):
        self.generic_visit(node)
        if node is self.target_node:
            self.applied = True
            # Return just the try body statements as a flat sequence
            # We need to splice these into the parent's body
            node._unwrapped_body = node.body
            return node
        return node

    def visit_FunctionDef(self, node):
        """Handle unwrapping at the function body level."""
        new_body = []
        for stmt in node.body:
            if isinstance(stmt, ast.Try) and stmt is self.target_node:
                new_body.extend(stmt.body)
                self.applied = True
            else:
                new_body.append(stmt)
        node.body = new_body
        self.generic_visit(node)
        return node


class _ReassociateBoolOp(ast.NodeTransformer):
    """Transform And(Not(x), Or(y, z)) → Or(And(Not(x), y), z).

    This reintroduces the precedence bug: without explicit parentheses,
    Python parses `not a and b or c` as `((not a) and b) or c`.
    """
    def __init__(self, target_node):
        self.target_node = target_node
        self.applied = False

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        if node is not self.target_node:
            return node
        # Match: And([Not(x), Or([y, z])])
        if not isinstance(node.op, ast.And):
            return node
        if len(node.values) != 2:
            return node
        left, right = node.values
        if not isinstance(right, ast.BoolOp) or not isinstance(right.op, ast.Or):
            return node
        if len(right.values) != 2:
            return node
        # Transform to: Or(And(left, right.values[0]), right.values[1])
        y, z = right.values
        new_node = ast.BoolOp(
            op=ast.Or(),
            values=[
                ast.BoolOp(op=ast.And(), values=[left, y]),
                z,
            ],
        )
        self.applied = True
        return new_node


class _HoistClosureVariable(ast.NodeTransformer):
    """Replace closure-local list creation with shared module-level reference.

    Inside a function (decorator): change `var = []` to `var = _SHARED_VAR`
    """
    def __init__(self, var_name: str, shared_name: str):
        self.var_name = var_name
        self.shared_name = shared_name
        self.applied = False

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        for i, stmt in enumerate(node.body):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == self.var_name:
                        if isinstance(stmt.value, ast.List) and len(stmt.value.elts) == 0:
                            stmt.value = ast.Name(id=self.shared_name, ctx=ast.Load())
                            self.applied = True
                            return node
        return node


# ============================================================
# ADVANCED OPERATORS (for the final 7 cases)
# ============================================================

class RelaxBoundaryOperator(SemanticOperator):
    """Relax comparison boundaries: Lt→LtE, Gt→GtE (off-by-one)."""
    def __init__(self):
        super().__init__(
            "relax_boundary", "Relax < to <= or > to >= (off-by-one at boundary)",
            ["wrong_condition"], "boundary: allows one extra past threshold",
        )

    def find_targets(self, tree):
        return find_comparisons(tree, [ast.Lt, ast.Gt])

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _RelaxComparison)


class CorruptStringLiteralOperator(SemanticOperator):
    """Corrupt a string constant used as a lookup key."""

    CORRUPTION_STRATEGIES = [
        # Pluralization drift
        lambda s: s + "s" if not s.endswith("s") else s[:-1],
        # Underscore removal
        lambda s: s.replace("_", "", 1) if "_" in s else None,
        # Underscore insertion (at first uppercase boundary or after prefix)
        lambda s: s.replace("FEATURE_", "FEATURE") if "FEATURE_" in s else None,
        # Segment removal (drop last dot-segment)
        lambda s: ".".join(s.split(".")[:-1]) if "." in s else None,
        # Component swap
        lambda s: s.replace("feature.", "features.") if "feature." in s else s.replace("features.", "feature."),
    ]

    def __init__(self):
        super().__init__(
            "corrupt_string_literal", "Corrupt config/env key string constant",
            ["silent_default"], "no_silent_fallback: lookup misses configured value due to key mismatch",
        )

    def find_targets(self, tree):
        """Find string constants used as function arguments or dict values — not docstrings."""
        targets = []
        # Collect string nodes that are function call arguments
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        val = arg.value
                        if len(val) > 3 and ("." in val or "_" in val):
                            fn = _enclosing_function(tree, node)
                            targets.append(SemanticTarget(
                                kind="string_argument", node=arg, function=fn or "module",
                                line=getattr(arg, "lineno", 0),
                                description=f"string argument '{val}' in function call",
                            ))
            # Dict value strings (env var keys, config keys)
            if isinstance(node, ast.Dict):
                for v in node.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        val = v.value
                        if len(val) > 3 and ("_" in val or val.isupper()):
                            fn = _enclosing_function(tree, node)
                            targets.append(SemanticTarget(
                                kind="string_dict_value", node=v, function=fn or "module",
                                line=getattr(v, "lineno", 0),
                                description=f"dict value string '{val}' (potential env/config key)",
                            ))
        return targets

    def mutate(self, code, tree, target):
        original_val = target.node.value
        for strategy in self.CORRUPTION_STRATEGIES:
            corrupted = strategy(original_val)
            if corrupted and corrupted != original_val:
                result = _apply_transform(code, tree, target, _CorruptStringConstant, corrupted)
                if result and result != code:
                    return result
        return None

    def mutate_all(self, code, tree, target):
        """Return ALL plausible corruptions of the target string."""
        results = []
        original_val = target.node.value
        for strategy in self.CORRUPTION_STRATEGIES:
            corrupted = strategy(original_val)
            if corrupted and corrupted != original_val:
                result = _apply_transform(code, tree, target, _CorruptStringConstant, corrupted)
                if result and result != code:
                    results.append(result)
        return results


class UnwrapTryExceptPlan(SemanticOperator):
    """Remove try/except block, keeping only try body. Deletes rollback."""
    def __init__(self):
        super().__init__(
            "unwrap_try_except", "Remove try/except rollback protection",
            ["invariant_partial_fail", "partial_rollback"],
            "state_conservation: no rollback on failure, partial state persists",
        )

    def find_targets(self, tree):
        targets = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and node.handlers:
                fn = _enclosing_function(tree, node)
                targets.append(SemanticTarget(
                    kind="try_except", node=node, function=fn or "?",
                    line=getattr(node, "lineno", 0),
                    description="try/except with rollback handler",
                ))
        return targets

    def mutate(self, code, tree, target):
        """Replace try/except with just the try body."""
        tree_copy = copy.deepcopy(tree)
        # Find the matching Try node in the copy
        for func_node in ast.walk(tree_copy):
            if isinstance(func_node, ast.FunctionDef):
                new_body = []
                changed = False
                for stmt in func_node.body:
                    if (isinstance(stmt, ast.Try)
                            and getattr(stmt, "lineno", -1) == target.line):
                        new_body.extend(stmt.body)
                        changed = True
                    else:
                        new_body.append(stmt)
                if changed:
                    func_node.body = new_body
                    ast.fix_missing_locations(tree_copy)
                    try:
                        result = ast.unparse(tree_copy)
                        return result if result != code else None
                    except Exception:
                        return None
        return None


class ReassociateBoolOpPlan(SemanticOperator):
    """Transform And(Not(x), Or(y, z)) → Or(And(Not(x), y), z) (precedence bug)."""
    def __init__(self):
        super().__init__(
            "reassociate_boolop", "Break boolean grouping (operator precedence bug)",
            ["wrong_condition"], "boundary: wrong boolean precedence allows forbidden cases",
        )

    def find_targets(self, tree):
        targets = []
        for node in ast.walk(tree):
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
                if len(node.values) == 2:
                    left, right = node.values
                    if isinstance(right, ast.BoolOp) and isinstance(right.op, ast.Or):
                        fn = _enclosing_function(tree, node)
                        targets.append(SemanticTarget(
                            kind="bool_grouping", node=node, function=fn or "?",
                            line=getattr(node, "lineno", 0),
                            description="And(_, Or(_, _)) — explicit grouping to reassociate",
                        ))
        return targets

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _ReassociateBoolOp)


class SharedClosureStatePlan(SemanticOperator):
    """Break closure isolation by hoisting local list to shared module-level state."""
    def __init__(self):
        super().__init__(
            "shared_closure_state", "Hoist closure-local list to shared module state",
            ["mutable_default"], "idempotence: decorator state leaks across decorated functions",
        )

    def find_targets(self, tree):
        """Find closure-local list assignments inside nested functions (decorators)."""
        targets = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Check if this function contains a nested function (decorator pattern)
                for child in ast.walk(node):
                    if isinstance(child, ast.FunctionDef) and child is not node:
                        # This is a decorator with inner function
                        # Find list assignments in the outer function body
                        for stmt in node.body:
                            if isinstance(stmt, ast.Assign):
                                for t in stmt.targets:
                                    if isinstance(t, ast.Name) and isinstance(stmt.value, ast.List):
                                        targets.append(SemanticTarget(
                                            kind="closure_local_list", node=node,
                                            function=node.name,
                                            line=getattr(stmt, "lineno", 0),
                                            description=f"closure-local {t.id} = [] in decorator {node.name}",
                                        ))
                        break
        return targets

    def mutate(self, code, tree, target):
        """Multi-edit: add module-level shared list + replace closure-local with reference."""
        tree_copy = copy.deepcopy(tree)

        # Find the variable name from the decorator function
        var_name = None
        for func_node in ast.walk(tree_copy):
            if (isinstance(func_node, ast.FunctionDef)
                    and func_node.name == target.function):
                for stmt in func_node.body:
                    if isinstance(stmt, ast.Assign):
                        for t in stmt.targets:
                            if isinstance(t, ast.Name) and isinstance(stmt.value, ast.List):
                                var_name = t.id
                                break
                break

        if not var_name:
            return None

        shared_name = f"_SHARED_{var_name.upper()}"

        # Step 1: Add module-level shared list
        shared_assign = ast.Assign(
            targets=[ast.Name(id=shared_name, ctx=ast.Store())],
            value=ast.List(elts=[], ctx=ast.Load()),
        )
        tree_copy.body.insert(0, shared_assign)

        # Step 2: Replace closure-local assignment with shared reference
        hoister = _HoistClosureVariable(var_name, shared_name)
        tree_copy = hoister.visit(tree_copy)

        if not hoister.applied:
            return None

        ast.fix_missing_locations(tree_copy)
        try:
            result = ast.unparse(tree_copy)
            return result if result != code else None
        except Exception:
            return None


# ============================================================
# OPERATOR REGISTRY
# ============================================================

SEMANTIC_OPERATORS: list[SemanticOperator] = [
    # Aliasing
    RemoveCopyOperator(),

    # Cache invalidation
    RemoveMethodCallOperator(
        "remove_cache_invalidation",
        "Remove cache .pop()/.clear()/invalidate() calls",
        ["stale_cache", "cache_invalidation_order"],
        "consistency: reads return stale case_data after write",
        ["pop", "clear", "invalidate"],
    ),

    # Field sync
    RemoveAssignmentOperator(
        "remove_field_sync",
        "Remove dependent field assignment (display_name, full_name, etc.)",
        ["partial_update"],
        "field_sync: dependent field not updated when primary changes",
        ["display_name", "full_name", "verified", "display"],
    ),

    # Mutable default
    RestoreMutableDefaultOperator(),

    # Side effect / ledger
    RemoveMethodCallOperator(
        "remove_ledger_append",
        "Remove ledger/log .append() for edge case path",
        ["early_return", "effect_order"],
        "side_effect: missing audit trail entry",
        ["append"],
    ),

    # Rollback
    RemoveMethodCallOperator(
        "remove_rollback",
        "Remove .release()/.rollback() in exception handler",
        ["partial_rollback", "invariant_partial_fail"],
        "state_conservation: partial state on failure",
        ["release", "rollback", "unreserve"],
    ),

    # Boundary condition
    FlipComparisonOperator(),

    # Missing branch
    RemoveBranchOperator(),

    # Index alignment
    InsertToAppendOperator(),

    # Config value
    ChangeConstantOperator(
        "wrong_timeout", "Change timeout 30 → 5",
        ["config_shadowing"], "consistency: wrong config value",
        30, 5,
    ),

    # Cache sync
    RemoveFunctionCallOperator(
        "remove_cache_sync",
        "Remove cache synchronization function call",
        ["hidden_dep_multihop"],
        "consistency: cache not updated after write",
        ["sync_user_to_cache", "cache_put", "refresh_user_snapshot", "cache_set"],
    ),

    # Feature flag
    RemoveFunctionCallOperator(
        "remove_flag_sync",
        "Remove feature flag enable/disable call",
        ["feature_flag_drift"],
        "consistency: flag state drifts from intent",
        ["enable", "disable"],
    ),

    # Pipeline commit/freeze
    RemoveFunctionCallOperator(
        "remove_commit_gate",
        "Remove commit/freeze step from pipeline",
        ["commit_gate", "l3_state_pipeline"],
        "ordering: uncommitted state visible to downstream",
        ["commit", "freeze_view", "freeze"],
    ),

    # Conservation
    RemoveFunctionCallOperator(
        "remove_credit",
        "Remove credit/receiver-side of transfer",
        ["invariant_partial_fail"],
        "state_conservation: debit without credit",
        ["record_credit", "credit"],
    ),

    # Ordering / buffer drain
    RemoveMethodCallOperator(
        "remove_buffer_drain",
        "Remove buffer .clear() after drain",
        ["ordering_dependency", "l3_state_pipeline"],
        "ordering: buffered items lost",
        ["clear"],
    ),

    # Duplicate prevention
    RemoveMethodCallOperator(
        "remove_dedup",
        "Remove deduplication check",
        ["retry_dup"],
        "idempotence: duplicate side effects",
        ["discard", "remove"],
    ),

    # Redundant writer
    RemoveFunctionCallOperator(
        "remove_correct_writer",
        "Remove the correct writer, keeping the stale one",
        ["overdetermination"],
        "consistency: stale computed value persists",
        ["write_fresh", "write_direct", "compute_and_store"],
    ),

    # Normalization skip
    RemoveFunctionCallOperator(
        "skip_normalization",
        "Remove key normalization call",
        ["silent_default"],
        "no_silent_fallback: lookup misses configured value",
        ["_normalize_key", "normalize_key", "normalize"],
    ),

    # Temporal ordering
    RemoveFunctionCallOperator(
        "remove_pre_transform_stats",
        "Remove pre-transform statistics computation",
        ["temporal_drift"],
        "consistency: stats computed on wrong case_data",
        ["compute_raw_stats"],
    ),

    # Atomicity
    RemoveFunctionCallOperator(
        "remove_lock",
        "Remove lock/unlock calls",
        ["async_race_lock", "lost_update", "check_then_act", "false_fix_deadlock"],
        "atomicity: unprotected concurrent access",
        ["try_lock", "unlock", "acquire", "release", "lock"],
    ),

    # Lazy init → eager capture (plan-based: multi-edit)
    EagerCaptureOperator(),
    RemoveAssignmentOperator(
        "remove_lazy_read",
        "Remove lazy dict read, forcing stale cached value",
        ["lazy_init"],
        "lifecycle: stale value after reset",
        ["_config", "_settings", "config", "settings"],
    ),

    # Temporal drift: swap argument to use wrong variable
    SwapArgumentOperator(
        "swap_stats_arg", "Swap compute_raw_stats argument to use transformed case_data",
        ["temporal_drift"], "consistency: stats computed on wrong case_data",
        "compute_raw_stats", "case_data", "cleaned",
    ),
    SwapArgumentOperator(
        "swap_stats_arg_norm", "Swap compute_raw_stats argument (normalized variant)",
        ["temporal_drift"], "consistency: stats computed on wrong case_data",
        "compute_raw_stats", "case_data", "normalized",
    ),

    # Missing branch: remove dict entry (comprehensive key list)
    RemoveDictEntryOperator(
        "remove_role_entry", "Remove a role entry from permissions dict",
        ["missing_branch"], "branch_coverage: valid role gets no permissions",
        ["moderator", "service_account", "editor", "manager", "reviewer", "guest",
         "admin", "user", "operator", "viewer"],
    ),
    # Missing branch: remove elif
    RemoveElifOperator(
        "remove_elif_branch", "Remove elif branch for a specific role/case",
        ["missing_branch"], "branch_coverage: valid case falls through",
        ["moderator", "service_account", "editor", "manager", "guest"],
    ),

    # Use-before-set: remove initialization
    RemoveInitializationOperator(),

    # Wrong condition: tighten comparisons (>=→>, <=→<)
    FlipComparisonOperator(),
    # Wrong condition: relax comparisons (<→<=, >→>=)
    RelaxBoundaryOperator(),
    # Wrong condition: boolean reassociation (precedence bug)
    ReassociateBoolOpPlan(),

    # Silent default: corrupt string literal (key mismatch / env var drift)
    CorruptStringLiteralOperator(),
    # Silent default: remove normalization + replace return with None
    RemoveReturnValueOperator(
        "return_none", "Replace return value with None (silent fallback)",
        ["silent_default"], "no_silent_fallback: configured value lost",
    ),

    # Try/except unwrap (removes rollback protection)
    UnwrapTryExceptPlan(),

    # Shared closure state (decorator history leakage)
    SharedClosureStatePlan(),

    # Config shadowing: also try value 5 (common wrong default)
    ChangeConstantOperator(
        "wrong_timeout_5", "Change timeout constant to wrong value",
        ["config_shadowing"], "consistency: wrong config value",
        30, 5,
    ),
    ChangeConstantOperator(
        "wrong_timeout_from_5", "Change timeout from 5 to something else",
        ["config_shadowing"], "consistency: wrong config value",
        5, 99,
    ),

    # Index misalign: also target slice assignments
    RemoveMethodCallOperator(
        "remove_insert_method", "Remove .insert() call entirely",
        ["index_misalign"], "structure_alignment: parallel arrays desynchronized",
        ["insert"],
    ),

    # False fix deadlock: remove combined atomic step
    RemoveAssignmentOperator(
        "remove_atomic_result",
        "Remove the result of atomic operation",
        ["false_fix_deadlock"],
        "atomicity: operation not completed",
        ["result", "transferred", "success"],
    ),

]


class RemoveAugAssignOperator(SemanticOperator):
    """Remove augmented assignment (obj.attr += value)."""
    def __init__(self, name, desc, families, invariant, attr_names):
        super().__init__(name, desc, families, invariant)
        self.attr_names = attr_names

    def find_targets(self, tree):
        return find_augmented_assignments(tree, self.attr_names)

    def mutate(self, code, tree, target):
        return _apply_transform(code, tree, target, _DeleteStatement)


# Add to registry
SEMANTIC_OPERATORS.append(RemoveAugAssignOperator(
    "remove_balance_credit",
    "Remove receiver.balance += amount (conservation violation)",
    ["invariant_partial_fail"],
    "state_conservation: debit without credit, balance not conserved",
    ["balance"],
))


def get_operators_for_family(family: str) -> list[SemanticOperator]:
    """Return all operators applicable to a family."""
    return [op for op in SEMANTIC_OPERATORS if family in op.families]


def get_all_operators() -> list[SemanticOperator]:
    return list(SEMANTIC_OPERATORS)


# ============================================================
# MULTI-FILE SUPPORT
# ============================================================

def mutate_file_in_case(case: dict, file_path: str, operator: SemanticOperator) -> MutationOutcome:
    """Apply a semantic operator to one file within a multi-file case.

    Returns MutationOutcome with the mutated file content.
    """
    code = case.get("code_files_contents", {}).get(file_path)
    if not code:
        return MutationOutcome(
            applied=False, mutated_code=None, intent=None, targets_found=0,
            rejection_reason=f"file {file_path} not found in case",
        )

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return MutationOutcome(
            applied=False, mutated_code=None, intent=None, targets_found=0,
            rejection_reason=f"syntax error in source: {e}",
        )

    targets = operator.find_targets(tree)
    if not targets:
        return MutationOutcome(
            applied=False, mutated_code=None, intent=None, targets_found=0,
            rejection_reason=f"operator '{operator.name}' found no targets in {file_path}",
        )

    # Try each target until one produces a valid mutation
    for target in targets:
        intent = MutationIntent(
            target=target,
            transform=operator.name,
            expected_violation=operator.invariant_violated,
        )
        mutated = operator.mutate(code, tree, target)
        if mutated and mutated != code:
            return MutationOutcome(
                applied=True, mutated_code=mutated, intent=intent,
                targets_found=len(targets), rejection_reason=None,
            )

    return MutationOutcome(
        applied=False, mutated_code=None, intent=MutationIntent(
            target=targets[0], transform=operator.name,
            expected_violation=operator.invariant_violated,
        ),
        targets_found=len(targets),
        rejection_reason=f"operator '{operator.name}' found {len(targets)} targets but none produced a valid mutation",
    )
