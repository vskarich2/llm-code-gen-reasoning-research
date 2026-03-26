"""Immutable prompt view for T3 benchmark.

Token reduction produces a PromptView without mutating the original manifest.
"""

import ast
import logging
from dataclasses import dataclass

_log = logging.getLogger("t3.prompt_view")


@dataclass(frozen=True)
class PromptView:
    """Immutable snapshot of what the model will see after token reduction."""
    files_full: tuple[tuple[str, str], ...]        # ((rel_path, content), ...) shown in full
    files_summarized: tuple[tuple[str, str], ...]   # ((rel_path, signatures), ...) shown as signatures
    files_dropped: tuple[str, ...]                  # rel_paths not shown
    reduction_level: int                            # 0=none, 1=whitespace, 2=summarized, 3=dropped, 4=infeasible
    original_file_count: int
    token_estimate: int
    infeasible: bool

    @property
    def shown_file_paths(self) -> list[str]:
        """All file paths visible to the model (full or summarized)."""
        return [p for p, _ in self.files_full] + [p for p, _ in self.files_summarized]

    @property
    def full_file_paths(self) -> list[str]:
        """File paths shown in full (model may modify these)."""
        return [p for p, _ in self.files_full]

    def to_log_dict(self) -> dict:
        return {
            "reduction_level": self.reduction_level,
            "original_file_count": self.original_file_count,
            "files_full": [p for p, _ in self.files_full],
            "files_summarized": [p for p, _ in self.files_summarized],
            "files_dropped": list(self.files_dropped),
            "token_estimate": self.token_estimate,
            "infeasible": self.infeasible,
        }


def _estimate_tokens(text: str, model: str = "") -> int:
    """Estimate token count. Uses tiktoken if available, else char/4 heuristic."""
    try:
        import tiktoken
        try:
            enc = tiktoken.encoding_for_model(model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        _log.warning("tiktoken not installed -- using char/4 heuristic for token estimation")
        return len(text) // 4


def _strip_whitespace(content: str) -> str:
    """Strip blank lines and trailing whitespace. Preserves semantics."""
    lines = [line.rstrip() for line in content.splitlines()]
    # Remove consecutive blank lines (keep at most one)
    result = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                result.append(line)
            prev_blank = True
        else:
            result.append(line)
            prev_blank = False
    return "\n".join(result)


def _extract_signatures(content: str) -> str:
    """Extract function/class signatures and docstrings only."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        # Can't parse -> return first 20 lines as fallback
        return "\n".join(content.splitlines()[:20])

    lines = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = f"def {node.name}({ast.dump(node.args) if not node.args.args else ', '.join(a.arg for a in node.args.args)}):"
            lines.append(sig)
            docstring = ast.get_docstring(node)
            if docstring:
                lines.append(f'    """{docstring}"""')
            lines.append("    ...")
            lines.append("")
        elif isinstance(node, ast.ClassDef):
            lines.append(f"class {node.name}:")
            docstring = ast.get_docstring(node)
            if docstring:
                lines.append(f'    """{docstring}"""')
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = ", ".join(a.arg for a in item.args.args)
                    lines.append(f"    def {item.name}({args}):")
                    lines.append("        ...")
            lines.append("")
        elif isinstance(node, ast.Assign):
            # Module-level assignments (constants)
            lines.append(ast.get_source_segment(content, node) or "")
        elif isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            lines.append(ast.get_source_segment(content, node) or "")

    return "\n".join(lines) if lines else content[:500]


# ============================================================
# Token budgets — read from config
# ============================================================

def get_token_budget(model: str) -> int:
    """Return the effective token budget for a model from config."""
    from experiment_config import get_config
    return get_config().execution.token_budgets.get_budget(model)


def classify_file_priority(file_paths: list[str],
                           import_graph: dict[str, list[str]],
                           reference_fix_file: str | None) -> dict[str, str]:
    """Assign priority to each file based on role in the bug.

    Returns: {rel_path: "CRITICAL" | "DIRECT_DEPENDENCY" | "SECONDARY"}
    """
    from pathlib import Path

    priorities = {}
    bug_file = reference_fix_file

    # Compute dependencies by stem name for matching
    stem_to_path = {Path(f).stem: f for f in file_paths}
    direct_dep_stems = set()
    reverse_dep_stems = set()

    if bug_file:
        bug_stem = Path(bug_file).stem
        direct_dep_stems = set(import_graph.get(bug_stem, []))
        for stem, deps in import_graph.items():
            if bug_stem in deps:
                reverse_dep_stems.add(stem)

    for f in file_paths:
        stem = Path(f).stem
        if f == bug_file or (bug_file and stem == Path(bug_file).stem):
            priorities[f] = "CRITICAL"
        elif stem in direct_dep_stems or stem in reverse_dep_stems:
            priorities[f] = "DIRECT_DEPENDENCY"
        else:
            priorities[f] = "SECONDARY"

    # If no bug file known, all files are CRITICAL (no reduction possible)
    if not bug_file:
        for f in file_paths:
            priorities[f] = "CRITICAL"

    return priorities


def build_prompt_view(file_paths: list[str],
                      files: dict[str, str],
                      import_graph: dict[str, list[str]],
                      reference_fix_file: str | None,
                      prompt_renderer,
                      condition: str,
                      model: str = "") -> PromptView:
    """Build an immutable PromptView within token budget. Never mutates inputs.

    Args:
        file_paths: ordered list of file relative paths
        files: rel_path -> content (NOT mutated)
        import_graph: stem -> [imported stems]
        reference_fix_file: rel_path of the primary bug file (or None)
        prompt_renderer: callable(files_full, files_summarized, files_dropped, condition) -> str
        condition: experiment condition name
        model: model name for budget lookup
    """
    budget = get_token_budget(model)
    priorities = classify_file_priority(file_paths, import_graph, reference_fix_file)

    # Work on copies -- inputs never mutated
    working = dict(files)

    # Level 0: Full prompt
    files_full = tuple((f, working[f]) for f in file_paths)
    view0 = PromptView(
        files_full=files_full, files_summarized=(), files_dropped=(),
        reduction_level=0, original_file_count=len(files),
        token_estimate=0, infeasible=False,
    )
    prompt = prompt_renderer(view0, condition)
    tokens = _estimate_tokens(prompt, model)
    if tokens <= budget:
        return PromptView(
            files_full=files_full, files_summarized=(), files_dropped=(),
            reduction_level=0, original_file_count=len(files),
            token_estimate=tokens, infeasible=False,
        )

    # Level 1: Strip whitespace from SECONDARY files
    files_l1 = {}
    for f in file_paths:
        if priorities[f] == "SECONDARY":
            files_l1[f] = _strip_whitespace(working[f])
        else:
            files_l1[f] = working[f]
    files_full_l1 = tuple((f, files_l1[f]) for f in file_paths)
    view1 = PromptView(
        files_full=files_full_l1, files_summarized=(), files_dropped=(),
        reduction_level=1, original_file_count=len(files),
        token_estimate=0, infeasible=False,
    )
    prompt = prompt_renderer(view1, condition)
    tokens = _estimate_tokens(prompt, model)
    if tokens <= budget:
        return PromptView(
            files_full=files_full_l1, files_summarized=(), files_dropped=(),
            reduction_level=1, original_file_count=len(files),
            token_estimate=tokens, infeasible=False,
        )

    # Level 2: Summarize SECONDARY files
    full_l2 = []
    summarized_l2 = []
    for f in file_paths:
        if priorities[f] == "SECONDARY":
            summarized_l2.append((f, _extract_signatures(working[f])))
        else:
            full_l2.append((f, working[f]))
    view2 = PromptView(
        files_full=tuple(full_l2), files_summarized=tuple(summarized_l2),
        files_dropped=(), reduction_level=2,
        original_file_count=len(files), token_estimate=0, infeasible=False,
    )
    prompt = prompt_renderer(view2, condition)
    tokens = _estimate_tokens(prompt, model)
    if tokens <= budget:
        return PromptView(
            files_full=tuple(full_l2), files_summarized=tuple(summarized_l2),
            files_dropped=(), reduction_level=2,
            original_file_count=len(files), token_estimate=tokens, infeasible=False,
        )

    # Level 3: Drop SECONDARY files
    full_l3 = [(f, working[f]) for f in file_paths if priorities[f] != "SECONDARY"]
    dropped = tuple(f for f in file_paths if priorities[f] == "SECONDARY")
    view3 = PromptView(
        files_full=tuple(full_l3), files_summarized=(), files_dropped=dropped,
        reduction_level=3, original_file_count=len(files),
        token_estimate=0, infeasible=False,
    )
    prompt = prompt_renderer(view3, condition)
    tokens = _estimate_tokens(prompt, model)
    if tokens <= budget:
        return PromptView(
            files_full=tuple(full_l3), files_summarized=(), files_dropped=dropped,
            reduction_level=3, original_file_count=len(files),
            token_estimate=tokens, infeasible=False,
        )

    # Level 4: Infeasible
    return PromptView(
        files_full=tuple(full_l3), files_summarized=(), files_dropped=dropped,
        reduction_level=4, original_file_count=len(files),
        token_estimate=tokens, infeasible=True,
    )
