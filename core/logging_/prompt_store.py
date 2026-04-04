"""Plain-text prompt file writer.

Writes exact prompts as plain text for inspection and reproducibility.
One file per LLM call. Filenames use logger-allocated prompt_id for traceability.

This module is the ONLY writer of prompt text files.
Prompt logging is always on. Not configurable. Not optional.
"""

import os
from pathlib import Path


def write_prompt(run_dir: Path, prompt_id: int, call_slot: int,
                 prompt: str) -> str:
    """Write prompt to plain text file. Returns relative path from run_dir.

    prompt_id: allocated by logger.next_prompt_id(), one per logical unit
    call_slot: allocated by logger.next_call_slot(), increments per call

    Thread-safe via O_CREAT|O_EXCL (atomic create, fails on collision).
    Directory creation failure raises RuntimeError (not silently ignored).
    """
    prompt_dir = run_dir / "prompts"
    try:
        prompt_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(
            f"Failed to create prompt directory {prompt_dir}: {e}. "
            f"Run directory may be unwritable."
        ) from e

    filename = f"p{prompt_id:06d}_call{call_slot}.txt"
    path = prompt_dir / filename

    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, prompt.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)

    return f"prompts/{filename}"


def validate_prompt_file(run_dir: Path, prompt_meta: dict) -> None:
    """Verify prompt file exists and matches declared hash/length.

    Raises RuntimeError on any mismatch. Used by smoke gate validation.
    """
    import hashlib

    pf = prompt_meta.get("prompt_file")
    if pf is None:
        raise RuntimeError("prompt_meta.prompt_file is None")

    path = run_dir / pf
    if not path.exists():
        raise RuntimeError(f"Prompt file missing: {path}")

    content = path.read_text(encoding="utf-8")
    if len(content) != prompt_meta["prompt_length"]:
        raise RuntimeError(
            f"Prompt file length mismatch: file={len(content)}, "
            f"declared={prompt_meta['prompt_length']}"
        )

    actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if actual_hash != prompt_meta["prompt_hash"]:
        raise RuntimeError(
            f"Prompt file hash mismatch: file={actual_hash[:16]}, "
            f"declared={prompt_meta['prompt_hash'][:16]}"
        )
