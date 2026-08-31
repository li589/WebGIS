"""Safe access to the top-level ``_backend_bridge`` module.

``_backend_bridge`` lives at the Python provider root. In-process backend runs
may leave that root off ``sys.path`` after a scoped import; this helper
loads the bridge by absolute path so portal/remote credential lookups do not
raise ``ModuleNotFoundError: No module named '_backend_bridge'`` mid-workflow.

Lives under ``modules`` so it remains importable via the already-loaded
``modules`` package even when the provider root was removed from ``sys.path``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_BRIDGE_NAME = "_backend_bridge"


def load_backend_bridge() -> ModuleType:
    existing = sys.modules.get(_BRIDGE_NAME)
    if existing is not None:
        return existing

    try:
        import _backend_bridge as bridge

        return bridge
    except ModuleNotFoundError:
        pass

    provider_root = Path(__file__).resolve().parents[1]
    bridge_path = provider_root / f"{_BRIDGE_NAME}.py"
    if not bridge_path.is_file():
        raise ModuleNotFoundError(
            f"No module named {_BRIDGE_NAME!r} (expected at {bridge_path})"
        )

    provider_root_str = str(provider_root)
    if provider_root_str not in sys.path:
        sys.path.insert(0, provider_root_str)

    spec = importlib.util.spec_from_file_location(_BRIDGE_NAME, bridge_path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(
            f"No module named {_BRIDGE_NAME!r} (failed to load {bridge_path})"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[_BRIDGE_NAME] = module
    spec.loader.exec_module(module)
    return module
