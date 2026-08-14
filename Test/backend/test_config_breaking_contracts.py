"""F5 破坏性契约测试：open-data-presets / remote-layer-uris 两个 PUT 端点。

背景（Phase 2 审查发现 F5）：`shared/contracts/config_contracts.py` 新增了
`OpenDataPresetsUpdateRequest/Response` 与 `RemoteLayerUrisUpdateRequest/Response`
（本轮 +99 行），但对应 HTTP 端点无契约测试——重构/演进时可能静默破坏前端。

端点（已在 `config_routes.py` 确认，注意路径含 `/data-source/` 前缀）：
- PUT /config/data-source/open-data-presets  → OpenDataPresetsUpdateResponse
- PUT /config/data-source/remote-layer-uris  → RemoteLayerUrisUpdateResponse

验证点：
① `extra="ignore"` 只透传声明字段（请求带多余字段被丢弃、不报错）；
② 更新后响应结构符合契约（用契约模型反序列化并断言字段形状）；
③ 必要字段缺失的校验行为（422）。
另含破坏性变更锁定：裸 dict（未包裹）仍应 422。
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from shared.contracts.config_contracts import (
    OpenDataPresetsUpdateResponse,
    RemoteLayerUrisUpdateResponse,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "app.services.effective_config.get_backend_auth_key",
        lambda: "test-key",
    )
    # RBAC v2: 配置管理路由需 admin 角色。
    monkeypatch.setattr(
        "app.core.config.settings",
        replace(settings, api_key_role="admin"),
    )
    return TestClient(create_app(), headers={"X-API-Key": "test-key"})


# ── PUT /config/data-source/open-data-presets ──────────────────────────────


def test_open_data_presets_accepts_wrapped_body(client: TestClient):
    presets = {"noaa_nomads": "https://nomads.ncep.noaa.gov/"}
    resp = client.put("/config/data-source/open-data-presets", json={"open_data_presets": presets})
    assert resp.status_code == 200
    data = resp.json()
    # 响应结构符合契约（含 open_data_presets 字段，值原样透传）
    assert data == {"open_data_presets": presets}
    validated = OpenDataPresetsUpdateResponse.model_validate(data)
    assert validated.open_data_presets == presets


def test_open_data_presets_extra_fields_ignored(client: TestClient):
    # 请求体带未声明字段（extra="ignore"）→ 不报错、不 422，多余字段被丢弃
    resp = client.put(
        "/config/data-source/open-data-presets",
        json={
            "open_data_presets": {"esa_cds": "https://cds.climate.copernicus.eu/"},
            "not_a_declared_field": "should-be-dropped",
            "another_extra": {"nested": True},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "not_a_declared_field" not in data
    assert "another_extra" not in data
    assert data == {
        "open_data_presets": {"esa_cds": "https://cds.climate.copernicus.eu/"}
    }


def test_open_data_presets_missing_required_field_rejected(client: TestClient):
    # open_data_presets 为必填字段，缺失 → 422
    resp = client.put("/config/data-source/open-data-presets", json={})
    assert resp.status_code == 422


def test_open_data_presets_bare_dict_rejected(client: TestClient):
    # 破坏性变更锁定：旧「接受裸 dict」行为已移除，裸 dict → 422
    resp = client.put(
        "/config/data-source/open-data-presets",
        json={"noaa_nomads": "https://nomads.ncep.noaa.gov/"},
    )
    assert resp.status_code == 422


# ── PUT /config/data-source/remote-layer-uris ──────────────────────────────


def test_remote_layer_uris_accepts_wrapped_body(client: TestClient):
    uris = {"layer_foo": {"ds_a": "https://example.com/a/"}}
    resp = client.put(
        "/config/data-source/remote-layer-uris", json={"remote_layer_data_uris": uris}
    )
    assert resp.status_code == 200
    data = resp.json()
    # 服务层把单个字符串 uri 规范化为 list[str]；响应结构符合契约
    assert data == {
        "remote_layer_data_uris": {"layer_foo": {"ds_a": ["https://example.com/a/"]}}
    }
    validated = RemoteLayerUrisUpdateResponse.model_validate(data)
    assert validated.remote_layer_data_uris["layer_foo"]["ds_a"] == [
        "https://example.com/a/"
    ]


def test_remote_layer_uris_extra_fields_ignored(client: TestClient):
    resp = client.put(
        "/config/data-source/remote-layer-uris",
        json={
            "remote_layer_data_uris": {
                "layer_bar": {"ds_b": ["https://example.com/b/", "https://example.com/c/"]}
            },
            "surprise": "dropped",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "surprise" not in data
    assert data == {
        "remote_layer_data_uris": {
            "layer_bar": {"ds_b": ["https://example.com/b/", "https://example.com/c/"]}
        }
    }


def test_remote_layer_uris_missing_required_field_rejected(client: TestClient):
    # remote_layer_data_uris 为必填字段，缺失 → 422
    resp = client.put("/config/data-source/remote-layer-uris", json={})
    assert resp.status_code == 422


def test_remote_layer_uris_bare_dict_rejected(client: TestClient):
    # 破坏性变更锁定：裸 dict（未包裹）→ 422
    resp = client.put(
        "/config/data-source/remote-layer-uris",
        json={"layer_foo": {"ds_a": "https://example.com/a/"}},
    )
    assert resp.status_code == 422
