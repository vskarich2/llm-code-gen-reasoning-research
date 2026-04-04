"""Pure text extraction utilities — regex-based code block extraction.

No pipeline dependencies. Only stdlib imports (re, logging).
"""

import logging
import re

log = logging.getLogger(__name__)


def extract_code(output: str) -> str:
    """Extract the last ```python block. Falls back to raw text."""
    blocks = re.findall(r"```python\s*\n(.*?)```", output, re.DOTALL)
    if blocks:
        return blocks[-1].strip()
    blocks = re.findall(r"```\s*\n(.*?)```", output, re.DOTALL)
    if blocks:
        return blocks[-1].strip()
    log.warning("extract_code: no code blocks found, returning raw (len=%d)", len(output))
    return output.strip()


def extract_all_code_blocks(output: str) -> list[tuple[str, str]]:
    """Extract all (filename_hint, code) pairs from model output."""
    blocks = []
    for m in re.finditer(
        r"(?:#\s*(\S+\.py)[^\n]*\n)?```python\s*\n(.*?)```",
        output,
        re.DOTALL,
    ):
        name = m.group(1) or f"block_{len(blocks)}.py"
        blocks.append((name, m.group(2).strip()))
    if not blocks:
        code = extract_code(output)
        if code:
            blocks.append(("candidate.py", code))
    return blocks
