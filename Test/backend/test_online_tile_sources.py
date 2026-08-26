"""在线 WMTS/XYZ 瓦片源配置与 SSRF 边界回归。"""

from __future__ import annotations

import pytest


def test_online_tile_source_validation(monkeypatch, tmp_path):
    from app.services import config_service

    class Repo:
        value = []

        def get_json(self, _key, default):
            return self.value

        def set_json(self, _key, value):
            self.value = value

    repo = Repo()
    monkeypatch.setattr(config_service, "_research_data_repo", lambda: repo)
    row = config_service.upsert_online_tile_source(
        "demo-xyz",
        {
            "display_name": "Demo XYZ",
            "service_type": "xyz",
            "url_template": "https://tiles.example.org/{z}/{x}/{y}.png",
            "enabled": True,
        },
    )
    assert row["source_id"] == "demo-xyz"
    assert config_service.list_online_tile_sources()[0]["config_status"] == "configured"


def test_online_tile_source_rejects_private_and_invalid_templates(monkeypatch):
    from app.services import config_service

    with pytest.raises(ValueError, match="absolute http"):
        config_service.upsert_online_tile_source(
            "demo-xyz", {"display_name": "x", "service_type": "xyz", "url_template": "file:///tmp/{z}/{x}/{y}"}
        )
    with pytest.raises(ValueError, match="placeholders"):
        config_service.upsert_online_tile_source(
            "demo-xyz", {"display_name": "x", "service_type": "xyz", "url_template": "https://example.org/tile.png"}
        )
    with pytest.raises(ValueError, match="WMTS layer"):
        config_service.upsert_online_tile_source(
            "demo-wmts", {"display_name": "x", "service_type": "wmts", "url_template": "https://example.org/{z}/{x}/{y}"}
        )
