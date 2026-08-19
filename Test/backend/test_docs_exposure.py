"""API 交互文档暴露开关测试（安全审计 2026-08-20 P1）。

覆盖：
- docs_enabled=False → /docs /redoc 404；/openapi.json 保持 200（用户决策：
  仅禁交互页，schema 端点保留供工具调用）
- docs_enabled=True → /docs /redoc 200
- ``_default_docs_enabled`` 推导矩阵（production/test fail-secure、
  development 默认开、BACKEND_DOCS_ENABLED 双向覆盖）
- docs 关闭时 ``app.openapi()`` 仍产出完整 schema（F14 闸门保护）

注意：Settings 为 frozen dataclass，字段默认值在 import 时求值——
测试必须 ``dataclasses.replace`` 显式构造变体并替换 ``app.main.settings``
（模块级绑定，仅替换 cfg_mod.settings 对 create_app 无效）。
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_CODE_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PROVIDER = _CODE_ROOT / "algorithms" / "providers" / "Python"
for _p in (_PYTHON_PROVIDER, _CODE_ROOT):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


def _make_client(monkeypatch: pytest.MonkeyPatch, docs_enabled: bool) -> TestClient:
    from app.core.config import settings

    monkeypatch.setattr(
        "app.main.settings", replace(settings, docs_enabled=docs_enabled)
    )
    from app.main import create_app

    return TestClient(create_app())


@pytest.fixture()
def _isolate_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "false")


def test_docs_disabled_returns_404(_isolate_env, monkeypatch):
    client = _make_client(monkeypatch, docs_enabled=False)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_openapi_json_kept_when_docs_disabled(_isolate_env, monkeypatch):
    """/openapi.json 不受开关影响（用户决策：保留供工具调用）。"""
    client = _make_client(monkeypatch, docs_enabled=False)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json().get("paths")


def test_docs_enabled_serves_docs(_isolate_env, monkeypatch):
    client = _make_client(monkeypatch, docs_enabled=True)
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


def test_openapi_schema_exportable_when_docs_disabled(_isolate_env, monkeypatch):
    """F14 闸门保护：docs 关闭时 app.openapi() 仍产出完整 schema。"""
    client = _make_client(monkeypatch, docs_enabled=False)
    schema = client.app.openapi()
    assert schema and schema.get("paths"), "app.openapi() 不依赖文档路由"


@pytest.mark.parametrize(
    ("docs_env", "backend_env", "expected"),
    [
        (None, "production", False),  # fail-secure 默认
        (None, None, False),  # BACKEND_ENV 缺省 → production
        (None, "test", False),
        (None, "development", True),
        (None, "dev", True),
        ("true", "production", True),  # 显式逃生门
        ("false", "development", False),  # 显式关闭
        ("1", "production", True),
        ("0", "development", False),
    ],
)
def test_default_docs_enabled_derivation(
    monkeypatch, docs_env: str | None, backend_env: str | None, expected: bool
):
    from app.core.config import _default_docs_enabled

    monkeypatch.delenv("BACKEND_DOCS_ENABLED", raising=False)
    monkeypatch.delenv("BACKEND_ENV", raising=False)
    if docs_env is not None:
        monkeypatch.setenv("BACKEND_DOCS_ENABLED", docs_env)
    if backend_env is not None:
        monkeypatch.setenv("BACKEND_ENV", backend_env)
    assert _default_docs_enabled() is expected
