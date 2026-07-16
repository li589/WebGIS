"""Phase0：配置写保护与有效配置投影。"""
from __future__ import annotations

import sys
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parents[2]
# Code root must precede providers/Python — the latter also contains an `algorithms/`
# package that would shadow `Code/algorithms.providers`.
_PYTHON_PROVIDER = _CODE_ROOT / "algorithms" / "providers" / "Python"
for _p in (_PYTHON_PROVIDER, _CODE_ROOT):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


def _route_dependency_callables(route) -> list:
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return []
    result = []
    for dep in dependant.dependencies or []:
        call = getattr(dep, "call", None)
        if call is not None:
            result.append(call)
    return result


def test_config_api_key_write_requires_auth_when_enabled():
    from app.api import config_routes
    from app.api.deps import require_write_access

    mutating = [
        route
        for route in config_routes.router.routes
        if getattr(route, "methods", None) and route.methods & {"PUT", "POST", "DELETE"}
    ]
    assert mutating, "expected mutating config routes"
    for route in mutating:
        dep_calls = _route_dependency_callables(route)
        assert require_write_access in dep_calls, f"route {route.path} missing require_write_access"


def test_import_raster_requires_write_access():
    from app.api.deps import require_write_access
    from app.api.routers.import_router import router as import_router

    routes = [
        r
        for r in import_router.routes
        if getattr(r, "methods", None) and "POST" in r.methods
    ]
    assert routes
    for route in routes:
        dep_calls = _route_dependency_callables(route)
        assert require_write_access in dep_calls


def test_runtime_ghost_keys_rejected():
    from app.services.workflow.runtime_status_service import ALLOWED_RUNTIME_CONFIG_KEYS

    assert "demo_snapshot_provider" not in ALLOWED_RUNTIME_CONFIG_KEYS.get("backend", set())
    assert "demo_source_mode" not in ALLOWED_RUNTIME_CONFIG_KEYS.get("frontend", set())
    assert not ALLOWED_RUNTIME_CONFIG_KEYS.get("workflow")


def test_backend_auth_uses_effective_secret(monkeypatch):
    from app.services import effective_config

    monkeypatch.setattr(effective_config, "_hydrated", True)
    monkeypatch.setattr(
        effective_config,
        "_snapshot",
        effective_config.RuntimeSnapshot(
            api_keys={"backend_auth": "db-auth-key"},
            hydrated=True,
        ),
    )
    assert effective_config.get_backend_auth_key() == "db-auth-key"
