"""Core pipeline package."""


def _format_code_files(code_files: dict[str, str]) -> str:
    """Format code files with explicit numbered delimiters (V2 format).

    This is DATA FORMATTING, not prompt construction.
    Turns a dict of {path: content} into a human-readable code block.
    """
    n = len(code_files)
    parts = [f"## Codebase ({n} file{'s' if n != 1 else ''})"]
    for i, (path, content) in enumerate(code_files.items(), 1):
        parts.append(f"\n### FILE {i}/{n}: {path} ###")
        parts.append(f"```python\n{content}\n```")
    return "\n".join(parts)
