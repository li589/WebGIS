"""三联报障（续）后端回归：产物显示名不泄漏源文件名。

2026-08-24：product.name 常为源文件名（landcover_025.mat），经前端
normalizeProductTag 全串大写 + productTagLabel 透传，曾以
「LANDCOVER_025.MAT」整体成为图层显示名。后端修复 = 显示名优先
descriptor.display_name，产物名/stem 兜底一律剥数据扩展名。
"""

from __future__ import annotations

from pathlib import Path

from app.services.python_provider_result_builder import (
    _resolve_product_display_label,
)


class TestResolveProductDisplayLabel:
    def test_product_name_extension_stripped(self, tmp_path: Path) -> None:
        label = _resolve_product_display_label(
            "",
            {},
            {"name": "landcover_025.mat"},
            tmp_path / "landcover_025.mat",
        )
        assert label == "landcover_025"

    def test_tif_extension_stripped(self, tmp_path: Path) -> None:
        label = _resolve_product_display_label(
            "",
            {},
            {"name": "ARIDITY_025.TIF"},
            tmp_path / "aridity.tif",
        )
        assert label == "ARIDITY_025"

    def test_tags_layer_preferred_over_product_name(self, tmp_path: Path) -> None:
        label = _resolve_product_display_label(
            "",
            {"layer": "土地利用覆被"},
            {"name": "landcover_025.mat"},
            tmp_path / "landcover_025.mat",
        )
        assert label == "土地利用覆被"

    def test_stem_fallback(self, tmp_path: Path) -> None:
        label = _resolve_product_display_label(
            "",
            {},
            {},
            tmp_path / "hfp_025.mat",
        )
        assert label == "hfp_025"

    def test_descriptor_display_name_wins(self, tmp_path: Path, monkeypatch) -> None:
        from app.services import python_provider_result_builder as m

        class _Desc:
            display_name = "干旱指数"

        monkeypatch.setattr(
            "app.services.layer_catalog.get_layer_descriptor",
            lambda _lid: _Desc(),
        )
        label = _resolve_product_display_label(
            "aridity-cn",
            {},
            {"name": "aridity_025.mat"},
            tmp_path / "aridity_025.mat",
        )
        assert label == "干旱指数"
