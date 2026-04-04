"""DEPRECATED — this module has moved to legacy/.

All public symbols are re-exported for backward compatibility.
New code should NOT import from this module.
"""
import os as _os

if _os.environ.get("STRICT_V2_ONLY") == "1":
    raise RuntimeError(
        f"STRICT_V2_ONLY is set and legacy module {__name__} was accessed. "
        "This import must be removed or updated."
    )

import warnings as _w
_w.warn(
    f"{__name__} is deprecated. Code has moved to legacy/.",
    DeprecationWarning,
    stacklevel=2,
)

from legacy.generation.prompt_registry import *  # noqa: F401,F403
from legacy.generation.prompt_registry import _reset_for_testing, _components, _loaded  # noqa: F401

