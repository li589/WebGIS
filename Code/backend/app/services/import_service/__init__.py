"""Backward-compatible re-export of data I/O services.

Prefer ``app.data_io.services`` for new code.
"""

import warnings

warnings.warn(
    "app.services.import_service is deprecated; use app.data_io.services instead",
    DeprecationWarning,
    stacklevel=2,
)

from app.data_io.services import *  # noqa: F403, E402
