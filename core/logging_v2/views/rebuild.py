"""Rebuild all materialized views from WAL + call artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from core.logging_v2.config import LoggingV2Config
from core.logging_v2.views.intermediate import build_ir
from core.logging_v2.views.registry import VIEW_REGISTRY
from core.logging_v2.views.renderers import render_case_detail


def rebuild_views(
    run_root: Path, config: LoggingV2Config,
) -> None:
    """Rebuild all materialized views from WAL + call artifacts.

    Views are derived artifacts. This function is idempotent.
    """
    ir = build_ir(run_root)

    views_dir = run_root / config.materialized_views_dirname
    views_dir.mkdir(parents=True, exist_ok=True)

    for view_spec in VIEW_REGISTRY.values():
        content = view_spec.renderer(ir, config)
        write_atomic(views_dir / view_spec.filename, content)

    cases_dir = views_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    for case_id in sorted(ir.events_by_case.keys()):
        content = render_case_detail(case_id, ir, config)
        write_atomic(cases_dir / f"{case_id}.md", content)


def write_atomic(path: Path, content: str) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
