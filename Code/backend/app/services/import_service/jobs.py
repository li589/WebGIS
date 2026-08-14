import warnings

warnings.warn(
    "app.services.import_service is deprecated; use app.data_io.services instead",
    DeprecationWarning,
    stacklevel=2,
)

from app.data_io.services.jobs import *  # noqa: F403, E402
