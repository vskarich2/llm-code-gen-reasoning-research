"""LogNode — write final result to WAL.

Effect node: writes to filesystem.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from side_projects.graph_runner.runtime.constants import (
    KEY_FINAL_RESULT,
    KEY_LOG_STATUS,
    LOG_STATUS_SKIPPED,
    LOG_STATUS_WRITTEN,
    NODE_TYPE_EFFECT,
)
from side_projects.graph_runner.graph.node_interface import BaseNode, NodeResult


class LogNode(BaseNode):
    NAME = "LogNode"
    INPUT_KEYS = frozenset({KEY_FINAL_RESULT})
    OUTPUT_KEYS = frozenset({KEY_LOG_STATUS})
    NODE_TYPE = NODE_TYPE_EFFECT

    def __init__(self, output_path: Path | None = None) -> None:
        self.output_path = output_path

    def execute(self, inputs: dict[str, Any]) -> NodeResult:
        final_result = inputs[KEY_FINAL_RESULT]

        if self.output_path is None:
            return NodeResult(outputs={
                KEY_LOG_STATUS: LOG_STATUS_SKIPPED,
            })

        path = Path(self.output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        line = json.dumps(final_result, default=str)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            # Append atomically — rename to self if exists
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.unlink(tmp_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return NodeResult(outputs={KEY_LOG_STATUS: LOG_STATUS_WRITTEN})
