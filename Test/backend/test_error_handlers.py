"""Global API error handler tests."""

from __future__ import annotations

import sys
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


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_ENV", "test")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("BACKEND_OUTPUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setenv("BACKEND_WORKFLOW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BACKEND_API_KEYS_ENABLED", "false")

    import app.core.config as cfg_mod
    from app.core.config import Settings

    cfg_mod.settings = Settings()

    from app.main import create_app

    return TestClient(create_app())


def test_not_found_includes_request_id(api_client: TestClient):
    resp = api_client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert "request_id" in body
    assert body["request_id"]


def test_validation_error_includes_request_id(api_client: TestClient):
    resp = api_client.post("/auth/login", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert "request_id" in body
    assert isinstance(body["detail"], list)


def test_model_validator_value_error_serializes_cleanly(monkeypatch):
    """Pydantic model_validator 抛 ValueError 时，errors() 的 ctx 携带原始异常对象；
    422 响应必须可 JSON 序列化（回归：此前 TypeError: Object of type ValueError
    is not JSON serializable → 500）。"""
    from app.main import create_app

    monkeypatch.setenv("BACKEND_DATA_ROOT", str(Path(__file__).parent / ".tmp-data"))
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key", lambda: "test-key"
    )
    client = TestClient(create_app(), headers={"X-API-Key": "test-key"})
    resp = client.post(
        "/import/transform-point",
        json={"points": [], "source_crs": "EPSG:4326", "target_crs": "EPSG:4326"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["request_id"]
    assert isinstance(body["detail"], list)
    assert "points must not be empty" in body["detail"][0]["msg"]


def test_internal_error_includes_request_id(api_client: TestClient, monkeypatch):
    from app.main import create_app

    app = create_app()

    @app.get("/__test_boom")
    def _boom():
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/__test_boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "Internal server error"
    assert body["request_id"]
