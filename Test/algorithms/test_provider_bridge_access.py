"""Regression: portal credential resolve must find ``_backend_bridge`` off sys.path."""

from __future__ import annotations

import sys
from pathlib import Path


PROVIDER_ROOT = Path(__file__).resolve().parents[2] / "Code" / "algorithms" / "providers" / "Python"


def test_load_backend_bridge_when_provider_root_missing_from_sys_path() -> None:
    # Ensure package imports resolve, then strip the provider root before load.
    root = str(PROVIDER_ROOT.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)

    # Fresh import of the helper (avoid cached bridge from other tests).
    sys.modules.pop("_backend_bridge", None)
    sys.modules.pop("modules.provider_bridge_access", None)

    from modules.provider_bridge_access import load_backend_bridge

    sys.path[:] = [p for p in sys.path if Path(p).resolve() != Path(root).resolve()]
    sys.modules.pop("_backend_bridge", None)

    bridge = load_backend_bridge()
    assert hasattr(bridge, "get_portal_credentials")
    assert bridge.__file__ and bridge.__file__.endswith("_backend_bridge.py")
