# ============================================================
# Code file formatting utility for T3 evaluation
#
# ALL prompt text and nudge content has moved to:
#   prompts/components/*.j2  (templates)
#   prompts/registry.yaml    (nudge text entries)
#   assembly_engine.py       (single build path)
# ============================================================


def _format_code_files(code_files: dict[str, str]) -> str:
    """Format code files with explicit numbered delimiters (V2 format).

    This is DATA FORMATTING, not prompt construction.
    Turns a dict of {path: content} into a human-readable code block.
    """
    return _format_code_files_v2(code_files)


def _format_code_files_v2(code_files: dict[str, str]) -> str:
    """V2 format: ## Codebase (N files) with numbered FILE headers."""
    n = len(code_files)
    parts = [f"## Codebase ({n} file{'s' if n != 1 else ''})"]
    for i, (path, content) in enumerate(code_files.items(), 1):
        parts.append(f"\n### FILE {i}/{n}: {path} ###")
        parts.append(f"```python\n{content}\n```")
    return "\n".join(parts)
