"""产物配色口径的回归防线（2026-11-12）。

来由：2026-11-11 22:02 一次工作流重跑（run-d3d49d0c9236）把风云组两个色带冲掉了：

* 兜底扫描路径**自己抄了一份**变量→色带表，与 ``_MAPPABLE_PRODUCTS`` 各自维护。
  主路径 ω 是 ``reds``（2026-10-20 用户指定），兜底却写 ``cividis`` ⇒ 只要走到
  兜底就换色。
* 风云平均 SM 在 2026-11-05 按老师要求手工改成 ``sm-classic``，但那是直接改盘上
  ``meta.json``（提交说明写「数据侧（未入库）」），默认表没动 ⇒ 重跑必回退。

两条规则在这里锁死：
1. 变量→色带/量程只认 ``_MAPPABLE_PRODUCTS``，兜底和主路径共用 ``_palette_for_layer``
   / ``_range_for_variable``，源码里不许再出现第二份字面量。
2. 某一层要用与产品默认不同的配色，登记 ``_LAYER_PALETTE_OVERRIDES``，且**只改配色、
   不动量程**。
"""

from __future__ import annotations

import inspect

from app.services import python_provider_result_builder as builder

#: 风云平均散射约束产品（老师指定「经典七色」的那一层）
FY_AVG = "method-fy-omega-doy-avg"
FY_DYNAMIC = "method-fy-omega-doy-dynamic"
SMAP_AVG = "method-smap-omega-doy-avg"


class TestLayerPaletteOverride:
    def test_fy_average_sm_pins_classic(self):
        assert builder._palette_for_layer("SM", FY_AVG) == "sm-classic"

    def test_other_sm_layers_keep_paper(self):
        """覆盖只针对风云平均那一层，别的 SM 一律仍是论文色带。"""
        assert builder._palette_for_layer("SM", FY_DYNAMIC) == "sm-paper"
        assert builder._palette_for_layer("SM", SMAP_AVG) == "sm-paper"
        assert builder._palette_for_layer("SM", "") == "sm-paper"

    def test_omega_comes_from_registry_single_source(self):
        """ω 跟着 _MAPPABLE_PRODUCTS 走（reds），不再被兜底写成 cividis。"""
        registry = builder._MAPPABLE_PRODUCTS["omega_sf_omega_block_dir"]["palette"]
        assert registry == "reds"
        assert builder._palette_for_layer("OMEGA", FY_AVG) == registry
        assert builder._palette_for_layer("OMEGA", SMAP_AVG) == registry

    def test_vod_unchanged(self):
        assert builder._palette_for_layer("VOD", FY_AVG) == "darkgreen-yellow"

    def test_override_does_not_touch_range(self):
        """换色 ≠ 改量程：SM 仍是 0–0.6，ω 0–0.5，VOD 0–1.5。"""
        assert builder._range_for_variable("SM") == (0.0, 0.6)
        assert builder._range_for_variable("OMEGA") == (0.0, 0.5)
        assert builder._range_for_variable("VOD") == (0.0, 1.5)

    def test_unknown_variable_falls_back_to_placeholder(self):
        """认不出的变量不给假色带，回落到函数默认值。"""
        assert builder._palette_for_layer("UNKNOWN", FY_AVG) == "cividis"
        assert builder._range_for_variable("UNKNOWN") == (None, None)


class TestNoSecondPaletteTable:
    """兜底扫描不许再维护第二份变量→色带表。"""

    def test_fallback_loop_uses_shared_helper(self):
        src = inspect.getsource(builder)
        assert "_palette_for_layer(variable, fallback_layer_key)" in src
        assert "_range_for_variable(variable)" in src

    def test_old_hardcoded_tuple_is_gone(self):
        src = inspect.getsource(builder)
        for literal in (
            '("SM", "SM", "sm-paper", 0.0, 0.6)',
            '("VOD", "VOD", "darkgreen-yellow", 0.0, 1.5)',
            '("OMEGA", "OMEGA", "cividis", 0.0, 0.5)',
        ):
            assert literal not in src, f"兜底又抄了一份字面量：{literal}"

    def test_override_table_only_holds_palette(self):
        """覆盖表里只允许 palette 键——量程不许借道覆盖表偷改。"""
        for layer_key, override in builder._LAYER_PALETTE_OVERRIDES.items():
            assert isinstance(override, dict)
            for variable, value in override.items():
                assert isinstance(value, str), f"{layer_key}/{variable} 不是色带名"
                assert isinstance(value, str) and value


class TestRerunKeepsExistingPalette:
    """重跑只更新数据，不换掉已落盘的色带（2026-11-11 事故的通用防线）。

    这一层保护不依赖任何覆盖表：只要该层 meta.json 里已经有 palette，重跑传入
    的产品默认配色就**不生效**。要强制换色必须显式 override_existing_palette=True。
    """

    @staticmethod
    def _write_mat(path, value: float = 0.4) -> None:
        import numpy as np
        from scipy.io import savemat

        arr = np.full((8, 8), np.nan, dtype=np.float64)
        arr[2:6, 2:6] = value
        savemat(str(path), {"SM": arr, "VOD": arr, "OMEGA": arr})

    @staticmethod
    def _imports(tmp_path, monkeypatch):
        imports = tmp_path / "imports"
        imports.mkdir()
        monkeypatch.setattr(
            "app.data_io.services.raster_timeseries.import_paths.imports_dir",
            lambda: imports,
        )
        return imports

    def _publish(self, tmp_path, palette, **kwargs):
        from app.data_io.services.raster_timeseries import upsert_block_dir_timeseries

        blocks = tmp_path / f"blocks-{palette}-{len(kwargs)}"
        blocks.mkdir(exist_ok=True)
        self._write_mat(blocks / "20251201_20251231.mat")
        return upsert_block_dir_timeseries(
            blocks,
            variable_id="SM",
            label="SM",
            run_id="run-palette-test",
            layer_key=FY_AVG,
            palette=palette,
            vmin=0.0,
            vmax=0.6,
            force=True,
            **kwargs,
        )

    def test_rerun_keeps_pinned_palette(self, tmp_path, monkeypatch):
        import json

        imports = self._imports(tmp_path, monkeypatch)
        first = self._publish(tmp_path, "sm-classic")
        meta_path = imports / first["layer_id"] / "meta.json"
        assert (
            json.loads(meta_path.read_text(encoding="utf-8"))["palette"] == "sm-classic"
        )

        second = self._publish(tmp_path, "sm-paper")
        assert second["layer_id"] == first["layer_id"]
        assert (
            json.loads(meta_path.read_text(encoding="utf-8"))["palette"] == "sm-classic"
        )

    def test_explicit_override_still_changes_palette(self, tmp_path, monkeypatch):
        import json

        imports = self._imports(tmp_path, monkeypatch)
        first = self._publish(tmp_path, "sm-classic")
        meta_path = imports / first["layer_id"] / "meta.json"
        self._publish(tmp_path, "sm-paper", override_existing_palette=True)
        assert (
            json.loads(meta_path.read_text(encoding="utf-8"))["palette"] == "sm-paper"
        )

    def test_first_publish_uses_given_palette(self, tmp_path, monkeypatch):
        import json

        imports = self._imports(tmp_path, monkeypatch)
        out = self._publish(tmp_path, "sm-paper")
        meta = json.loads(
            (imports / out["layer_id"] / "meta.json").read_text(encoding="utf-8")
        )
        assert meta["palette"] == "sm-paper"


class TestRerunKeepsExistingPalette:
    """重跑只更新数据，不换掉已落盘的色带（2026-11-11 事故的通用防线）。

    这一层保护不依赖任何覆盖表：只要该层 meta.json 里已经有 palette，重跑传入
    的产品默认配色就**不生效**。要强制换色必须显式 override_existing_palette=True。
    """

    @staticmethod
    def _write_mat(path, value: float = 0.4) -> None:
        import numpy as np
        from scipy.io import savemat

        arr = np.full((8, 8), np.nan, dtype=np.float64)
        arr[2:6, 2:6] = value
        savemat(str(path), {"SM": arr, "VOD": arr, "OMEGA": arr})

    @staticmethod
    def _imports(tmp_path, monkeypatch):
        imports = tmp_path / "imports"
        imports.mkdir()
        monkeypatch.setattr(
            "app.data_io.services.raster_timeseries.import_paths.imports_dir",
            lambda: imports,
        )
        return imports

    def _publish(self, tmp_path, palette, **kwargs):
        from app.data_io.services.raster_timeseries import upsert_block_dir_timeseries

        blocks = tmp_path / f"blocks-{palette}-{len(kwargs)}"
        blocks.mkdir(exist_ok=True)
        self._write_mat(blocks / "20251201_20251231.mat")
        return upsert_block_dir_timeseries(
            blocks,
            variable_id="SM",
            label="SM",
            run_id="run-palette-test",
            layer_key=FY_AVG,
            palette=palette,
            vmin=0.0,
            vmax=0.6,
            force=True,
            **kwargs,
        )

    def test_rerun_keeps_pinned_palette(self, tmp_path, monkeypatch):
        import json

        imports = self._imports(tmp_path, monkeypatch)
        first = self._publish(tmp_path, "sm-classic")
        meta_path = imports / first["layer_id"] / "meta.json"
        assert (
            json.loads(meta_path.read_text(encoding="utf-8"))["palette"] == "sm-classic"
        )

        second = self._publish(tmp_path, "sm-paper")
        assert second["layer_id"] == first["layer_id"]
        assert (
            json.loads(meta_path.read_text(encoding="utf-8"))["palette"] == "sm-classic"
        )

    def test_explicit_override_still_changes_palette(self, tmp_path, monkeypatch):
        import json

        imports = self._imports(tmp_path, monkeypatch)
        first = self._publish(tmp_path, "sm-classic")
        meta_path = imports / first["layer_id"] / "meta.json"
        self._publish(tmp_path, "sm-paper", override_existing_palette=True)
        assert (
            json.loads(meta_path.read_text(encoding="utf-8"))["palette"] == "sm-paper"
        )

    def test_first_publish_uses_given_palette(self, tmp_path, monkeypatch):
        import json

        imports = self._imports(tmp_path, monkeypatch)
        out = self._publish(tmp_path, "sm-paper")
        meta = json.loads(
            (imports / out["layer_id"] / "meta.json").read_text(encoding="utf-8")
        )
        assert meta["palette"] == "sm-paper"
