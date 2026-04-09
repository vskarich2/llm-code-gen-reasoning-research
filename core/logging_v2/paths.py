"""Single path-building function. ALL artifact paths go through here.

No other module constructs artifact paths by string concatenation,
f-strings, or manual / joining.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.logging_v2.axes import (
    AXIS_ORDER,
    AXIS_SPECS,
    validate_filesystem_safe,
)
from core.logging_v2.enums import ArtifactGroup, Axis


def build_artifact_path(
    run_root: Path,
    artifact_group: ArtifactGroup,
    axes: dict[Axis, Any],
    leaf: str | None = None,
) -> Path:
    """Build a fully validated artifact path from axis values.

    Iterates AXIS_ORDER. For each axis present in axes dict, appends
    the prefixed value to the path. Validates types, zero-indexing,
    and filesystem safety.

    Args:
        run_root: Root of the run directory.
        artifact_group: ArtifactGroup enum member.
        axes: Mapping of Axis enum → value.
        leaf: Optional filename to append at the end.

    Returns:
        Complete Path.

    Raises:
        ValueError: Missing required axis, negative index, unsafe chars.
        TypeError: Value type does not match AxisSpec.value_type.
    """
    # NOTE: artifacts root is intentionally fixed to "artifacts" per spec.
    # Do not derive from config to avoid multi-source-of-truth issues.
    parts: list[str] = [
        "artifacts",
        artifact_group.value,
    ]

    for axis in AXIS_ORDER:
        spec = AXIS_SPECS[axis]

        if axis not in axes:
            if spec.required:
                raise ValueError(
                    f"Required axis {axis.value!r} missing from axes dict"
                )
            continue

        value = axes[axis]

        if not isinstance(value, spec.value_type):
            raise TypeError(
                f"Axis {axis.value!r} expects {spec.value_type.__name__}, "
                f"got {type(value).__name__}: {value!r}"
            )

        if spec.zero_indexed and isinstance(value, int) and value < 0:
            raise ValueError(
                f"Axis {axis.value!r} must be >= 0, got {value}"
            )

        str_value = str(value)

        if isinstance(value, str):
            validate_filesystem_safe(str_value, axis)

        if spec.prefix is not None:
            segment = f"{spec.prefix}{str_value}"
        else:
            segment = str_value

        parts.append(segment)

    result = run_root
    for part in parts:
        result = result / part

    if leaf is not None:
        result = result / leaf

    return result
