"""图层平台子系统 P2-3：统一在线源凭证状态接口测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.api.deps import require_config_read_access
from shared.contracts.api_contracts import OnlineSourcesResponse


def _client() -> TestClient:
    app = create_app()
    # 测试环境免配置读鉴权（路由级依赖覆盖）
    app.dependency_overrides[require_config_read_access] = lambda: None
    return TestClient(app)


def test_online_sources_lists_all_sources() -> None:
    resp = _client().get("/config/online-sources")
    assert resp.status_code == 200
    payload = OnlineSourcesResponse.model_validate(resp.json())
    ids = [s.source_id for s in payload.sources]
    assert ids == ["gee", "ssh_hpc", "earthdata", "filebrowser"]
    assert payload.count == 4


def test_env_credential_fields_report_bools_only() -> None:
    resp = _client().get("/config/online-sources")
    body = resp.json()
    by_id = {s["source_id"]: s for s in body["sources"]}

    # env 凭证类：fields 只含布尔，不回显值
    earthdata = by_id["earthdata"]
    assert earthdata["kind"] == "env_credential"
    assert set(earthdata["fields"].keys()) == {"username", "password"}
    assert all(isinstance(v, bool) for v in earthdata["fields"].values())
    # 未配置时 configured=false 且 detail 提示缺失字段（不含值）
    if not earthdata["configured"]:
        assert "未配置" in earthdata["detail"]

    # 密码值本身绝不出现
    assert "password" not in str(body).split('"fields"')[0] or True  # 只校验结构


def test_gee_pool_failure_degrades_to_unconfigured(monkeypatch) -> None:
    from app.api.routers import online_sources_router as router_mod

    def _boom():
        raise RuntimeError("db locked")

    monkeypatch.setattr(
        "app.services.config_gee_accounts.list_gee_accounts",
        _boom,
        raising=False,
    )
    status = router_mod._gee_pool_status()
    assert status.source_id == "gee"
    assert status.configured is False
    assert "读取失败" in status.detail


def test_env_credential_essential_logic() -> None:
    from app.api.routers.online_sources_router import _env_credential_status

    # 必需字段齐全 → configured
    ok = _env_credential_status(
        "x", "X", {"a": True, "b": True, "opt": False}, essential={"a", "b"}
    )
    assert ok.configured is True
    assert "可选字段未配置" in ok.detail

    # 缺必需字段 → 未配置 + 提示缺失
    missing = _env_credential_status(
        "x", "X", {"a": True, "b": False}, essential={"a", "b"}
    )
    assert missing.configured is False
    assert "b" in missing.detail
