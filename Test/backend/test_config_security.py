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
    from app.api.deps import require_config_management_access, require_write_access

    # RBAC v2: 高危配置路由可使用 require_config_management_access（admin 级）
    # 替代 require_write_access，二者均提供写保护。
    accepted_write_guards = {require_write_access, require_config_management_access}

    mutating = [
        route
        for route in config_routes.router.routes
        if getattr(route, "methods", None) and route.methods & {"PUT", "POST", "DELETE"}
    ]
    assert mutating, "expected mutating config routes"
    for route in mutating:
        dep_calls = _route_dependency_callables(route)
        assert accepted_write_guards & set(dep_calls), (
            f"route {route.path} missing require_write_access "
            f"or require_config_management_access"
        )


def test_sensitive_config_gets_require_read_access():
    from app.api import config_routes
    from app.api.deps import require_config_read_access, require_write_access

    sensitive_suffixes = (
        "/api-keys",
        "/gee/accounts",
        "/gee/runtime",
        "/weather",
        "/weather/providers",
        "/remote-storage",
        "/data-source",
        "/data-cache/overview",
        "/data-source/portal-credentials",
    )
    for route in config_routes.router.routes:
        methods = getattr(route, "methods", None) or set()
        if "GET" not in methods:
            continue
        path = getattr(route, "path", "") or ""
        if not any(
            path.endswith(s) or path.endswith(s + "/") for s in sensitive_suffixes
        ):
            # also match templated provider detail
            if "/weather/providers/{provider_id}" not in path:
                continue
        dep_calls = _route_dependency_callables(route)
        assert (
            require_config_read_access in dep_calls or require_write_access in dep_calls
        ), f"sensitive GET {path} missing require_config_read_access"


def test_import_raster_requires_write_access():
    from app.api.deps import require_data_transfer_access, require_write_access
    from app.api.routers.import_router import router as import_router

    # RBAC v2: 数据导入路由可使用 require_data_transfer_access 替代
    # require_write_access，二者均提供写保护。
    accepted_write_guards = {require_write_access, require_data_transfer_access}

    routes = [
        r
        for r in import_router.routes
        if getattr(r, "methods", None) and "POST" in r.methods
    ]
    assert routes
    for route in routes:
        dep_calls = _route_dependency_callables(route)
        assert accepted_write_guards & set(dep_calls), (
            f"route {route.path} missing require_write_access "
            f"or require_data_transfer_access"
        )


def test_weather_sync_trigger_requires_write_access():
    from app.api.deps import require_write_access
    from app.api.routers.weather_router import router as weather_router

    routes = [
        r
        for r in weather_router.routes
        if getattr(r, "path", "") == "/weather/sync/trigger"
    ]
    assert len(routes) == 1
    dep_calls = _route_dependency_callables(routes[0])
    assert require_write_access in dep_calls


def test_runtime_ghost_keys_rejected():
    from app.services.workflow.runtime_status_service import ALLOWED_RUNTIME_CONFIG_KEYS

    assert "demo_snapshot_provider" not in ALLOWED_RUNTIME_CONFIG_KEYS.get(
        "backend", set()
    )
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


def _patch_settings(monkeypatch, patched):
    # credential_resolver / deps / effective_config 现动态读 app.core.config.settings，
    # 故只需 patch 单一真源即可覆盖全部下游模块。
    monkeypatch.setattr("app.core.config.settings", patched)


def test_require_write_access_dev_bypass_loopback(monkeypatch):
    from dataclasses import replace
    from unittest.mock import MagicMock

    from app.api import deps
    from app.core.config import settings

    patched = replace(settings, environment="development", api_keys_enabled=False)
    _patch_settings(monkeypatch, patched)
    monkeypatch.delenv("BACKEND_DEV_AUTH_BYPASS", raising=False)
    request = MagicMock()
    request.headers = {}
    request.cookies = {}
    request.client.host = "127.0.0.1"
    deps.require_write_access(request, x_api_key=None)  # no raise


def test_require_write_access_dev_bypass_denied_for_remote(monkeypatch):
    from dataclasses import replace
    from unittest.mock import MagicMock

    from fastapi import HTTPException

    from app.api import deps
    from app.core.config import settings

    patched = replace(settings, environment="development", api_keys_enabled=False)
    _patch_settings(monkeypatch, patched)
    monkeypatch.delenv("BACKEND_DEV_AUTH_BYPASS", raising=False)
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "",
    )
    request = MagicMock()
    request.headers = {}
    request.cookies = {}
    request.client.host = "10.0.0.5"
    try:
        deps.require_write_access(request, x_api_key=None)
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 503


def test_require_write_access_production_requires_key(monkeypatch):
    from dataclasses import replace
    from unittest.mock import MagicMock

    from fastapi import HTTPException

    from app.api import deps
    from app.core.config import settings

    monkeypatch.setattr(
        "app.core.config.settings",
        replace(settings, environment="production", api_keys_enabled=True),
    )
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "secret-key",
    )
    request = MagicMock()
    request.headers = {}
    request.client.host = "10.0.0.5"
    try:
        deps.require_write_access(request, x_api_key="wrong")
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 401
    deps.require_write_access(request, x_api_key="secret-key")


def test_dev_bypass_ignores_spoofed_xff_when_trust_proxy(monkeypatch):
    """X-Forwarded-For loopback must not bypass when direct peer is remote."""
    from dataclasses import replace
    from unittest.mock import MagicMock

    from fastapi import HTTPException

    from app.api import deps
    from app.core.config import settings

    monkeypatch.setattr(
        "app.core.config.settings",
        replace(
            settings,
            environment="development",
            api_keys_enabled=False,
            trust_proxy=True,
        ),
    )
    monkeypatch.delenv("BACKEND_DEV_AUTH_BYPASS", raising=False)
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "",
    )
    request = MagicMock()
    request.headers = {"x-forwarded-for": "127.0.0.1"}
    request.client.host = "10.0.0.5"
    try:
        deps.require_write_access(request, x_api_key=None)
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 503


def test_dev_bypass_allows_real_loopback_direct_peer(monkeypatch):
    from dataclasses import replace
    from unittest.mock import MagicMock

    from app.api import deps
    from app.core.config import settings

    patched = replace(
        settings, environment="development", api_keys_enabled=False, trust_proxy=True
    )
    _patch_settings(monkeypatch, patched)
    monkeypatch.delenv("BACKEND_DEV_AUTH_BYPASS", raising=False)
    request = MagicMock()
    request.headers = {"x-forwarded-for": "10.0.0.5"}
    request.cookies = {}
    request.client.host = "127.0.0.1"
    deps.require_write_access(request, x_api_key=None)  # no raise


def test_runtime_management_gets_require_read_access():
    from app.api.deps import require_config_read_access
    from app.api.routers.runtime_router import router as runtime_router

    paths = (
        "/runtime/status",
        "/runtime/metrics",
        "/runtime/api-config",
        "/runtime/tiles/providers",
        "/runtime/tiles/cache/stats",
    )
    for path in paths:
        routes = [r for r in runtime_router.routes if getattr(r, "path", "") == path]
        assert routes, f"missing route {path}"
        dep_calls = _route_dependency_callables(routes[0])
        assert require_config_read_access in dep_calls, f"{path} missing read auth"


def test_cleanup_gets_require_read_access():
    from app.api.deps import require_config_read_access
    from app.api.routers.cleanup_router import router as cleanup_router

    for path in ("/cleanup/stats", "/cleanup/node-caches"):
        routes = [r for r in cleanup_router.routes if getattr(r, "path", "") == path]
        assert routes, f"missing route {path}"
        dep_calls = _route_dependency_callables(routes[0])
        assert require_config_read_access in dep_calls, f"{path} missing read auth"
