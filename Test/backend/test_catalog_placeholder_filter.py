"""占位图层在非 development 环境应从 /layers 过滤。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.api.routers.layer_router import _catalog_items_for_environment


def test_placeholder_layers_kept_in_development() -> None:
    items = [
        SimpleNamespace(layer_id="a", status="available"),
        SimpleNamespace(layer_id="b", status="placeholder"),
    ]
    with patch("app.api.routers.layer_router.settings") as s:
        s.environment = "development"
        out = _catalog_items_for_environment(items)
    assert [i.layer_id for i in out] == ["a", "b"]


def test_placeholder_layers_filtered_in_production() -> None:
    items = [
        SimpleNamespace(layer_id="a", status="available"),
        SimpleNamespace(layer_id="b", status="placeholder"),
    ]
    with patch("app.api.routers.layer_router.settings") as s:
        s.environment = "production"
        out = _catalog_items_for_environment(items)
    assert [i.layer_id for i in out] == ["a"]
