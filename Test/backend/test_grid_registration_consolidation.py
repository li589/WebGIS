"""网格几何收敛（P2）与像元配准归一化（P1.5）回归锁。

背景（2026-08-24 架构审查，Docs/05-专题研究/其它专题/网格坐标系与像元配准
架构审查-2026-08-24.md）：

P2 — EASE 常数/重投影四处重复收敛为唯一真源：
  - EASE UL 角点表 / preset 几何 → grid_presets.EASE_UL_BY_CRS / GRID_PRESETS
  - EASE→Mercator 重投影 → grid_reproject.reproject_to_mercator_linear
  （overlay_recolor / overlay_registry / Tools 导出脚本一律引用，禁止再硬编码）

P1.5 — 全仓零 AREA_OR_POINT 处理的系统性缺口：
  - cell_registration.coords_to_area_bounds 统一判定中心（Point，CF 坐标变量
    约定 → 四边外扩半步长）vs 边缘（Area → min/max 即 bounds）
  - MAT 内嵌 lat/lon bounds（python_provider_result_builder）此前直接
    min/max——中心坐标源（如 aridity .mat）整体少算半像元
  - GRIB bounds（raster_science）隐式中心外扩 → 显式走共享实现
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

from app.data_io.services.cell_registration import (
    CELL_REGISTRATION_AREA,
    CELL_REGISTRATION_POINT,
    coords_to_area_bounds,
    infer_cell_registration,
)
from app.data_io.services.grid_presets import (
    EASE_UL_BY_CRS,
    GRID_PRESETS,
    ease_grid_from_shape,
    ease_grid_transform,
    list_grid_presets,
)
from app.data_io.services.grid_reproject import (
    MERCATOR_MAX_LAT,
    reproject_to_mercator_linear,
)

# ── P2：EASE 权威表与共享变换 ─────────────────────────────────────────────


class TestEaseUlTable:
    def test_ul_table_covers_all_ease_crs(self) -> None:
        assert set(EASE_UL_BY_CRS) == {
            "EPSG:6933",
            "EPSG:6931",
            "EPSG:6932",
            "EPSG:3408",
            "EPSG:3409",
            "EPSG:3410",
        }

    def test_ul_6933_full_precision(self) -> None:
        # NSIDC 官方对称角点（全精度，禁止用 west+cols*res 浮点累加推算）
        x, y = EASE_UL_BY_CRS["EPSG:6933"]
        assert x == pytest.approx(-17367530.445161516)
        assert y == pytest.approx(7314540.830865865)

    def test_ul_hemi_laea(self) -> None:
        for crs in ("EPSG:6931", "EPSG:6932", "EPSG:3408", "EPSG:3409"):
            assert EASE_UL_BY_CRS[crs] == (-9_000_000.0, 9_000_000.0)

    def test_ease_grid_transform_corners(self) -> None:
        preset = GRID_PRESETS["ease2-global-9km"]
        t = ease_grid_transform("EPSG:6933", float(preset["resolution"]))
        # 左上角
        assert t * (0, 0) == pytest.approx(EASE_UL_BY_CRS["EPSG:6933"])
        # 右下角 = UL + cols*res, UL - rows*res
        x, y = t * (preset["cols"], preset["rows"])
        assert x == pytest.approx(-EASE_UL_BY_CRS["EPSG:6933"][0])
        assert y == pytest.approx(-EASE_UL_BY_CRS["EPSG:6933"][1])

    def test_ease_grid_transform_unknown_crs_raises(self) -> None:
        with pytest.raises(ValueError, match="No EASE-Grid preset"):
            ease_grid_transform("EPSG:4326", 1000.0)


class TestEaseShapeMatching:
    """任意 EASE 网格（不止 9km）按 shape 匹配 preset 并构建变换。"""

    @pytest.mark.parametrize(
        ("shape", "preset_id", "crs"),
        [
            ((1624, 3856), "ease2-global-9km", "EPSG:6933"),
            ((584, 1388), "ease2-global-25km", "EPSG:6933"),
            ((406, 964), "ease2-global-36km", "EPSG:6933"),
            ((4872, 11568), "ease2-global-3km", "EPSG:6933"),
            ((720, 720), "ease2-north-25km", "EPSG:6931"),
            ((2000, 2000), "ease2-north-9km", "EPSG:6931"),
            ((721, 721), "ease1-north-25km", "EPSG:3408"),
        ],
    )
    def test_match_ease_shapes(self, shape, preset_id, crs) -> None:
        matched = ease_grid_from_shape(shape)
        assert matched is not None
        pid, p_crs, transform = matched
        assert pid == preset_id
        assert p_crs == crs
        # transform 锚定 preset bounds 的西北角（north-up 不旋转）
        west, south, east, north = GRID_PRESETS[preset_id]["bounds"]
        assert transform * (0, 0) == pytest.approx((west, north))
        # 东南角：cols×res 与对称域宽有亚像素差（25km preset 既有设计：
        # bounds 用 NSIDC 对称角点防浮点越界，网格锚定 UL），容差 1 像素
        res = float(GRID_PRESETS[preset_id]["resolution"])
        x, y = transform * (
            GRID_PRESETS[preset_id]["cols"],
            GRID_PRESETS[preset_id]["rows"],
        )
        assert abs(x - east) < res
        assert abs(y - south) < res

    def test_transposed_shape_matches_same_preset(self) -> None:
        # MATLAB v7.3 存 (cols, rows)：匹配到同一 preset（几何不变）
        assert ease_grid_from_shape((3856, 1624))[0] == "ease2-global-9km"

    def test_non_ease_shape_returns_none(self) -> None:
        assert ease_grid_from_shape((4320, 2160)) is None  # Koppen 0.083° 网格
        assert ease_grid_from_shape((176, 256)) is None  # aridity 中国区
        assert ease_grid_from_shape(None) is None


class TestSharedReproject:
    def test_global_equirect_to_mercator_linear(self) -> None:
        """EPSG:4326 全球 2° 网格 → Mercator 线性 1440×1440 + 全幅 bounds。"""
        from rasterio.transform import from_origin

        data = np.arange(90 * 180, dtype=np.float64).reshape(90, 180)
        src_t = from_origin(-180.0, 90.0, 2.0, 2.0)
        out, bounds = reproject_to_mercator_linear(
            data, src_t, "EPSG:4326", target_resolution=0.25
        )
        assert out.shape == (1440, 1440)
        w, s, e, n = bounds
        assert w == -180.0 and e == 180.0
        assert s == -MERCATOR_MAX_LAT and n == MERCATOR_MAX_LAT
        # 值域传递（nearest 采样不引入新值）
        finite = out[np.isfinite(out)]
        assert finite.min() >= data.min() - 1e-9
        assert finite.max() <= data.max() + 1e-9

    def test_global_mercator_idl_harmonization(self) -> None:
        """全球全幅网格在 IDL (±180°) 处左右边缘列完成数据协调。"""
        from rasterio.transform import from_origin

        # 构造一个跨日界线但边缘单侧有值的栅格
        data = np.full((10, 20), np.nan, dtype=np.float64)
        data[5, 0] = 42.0  # -180° 端有值
        # 180° 端为 NaN
        src_t = from_origin(-180.0, 85.0, 18.0, 17.0)
        out, bounds = reproject_to_mercator_linear(
            data, src_t, "EPSG:4326", target_resolution=1.0
        )
        assert bounds[0] == -180.0 and bounds[2] == 180.0
        # 验证协调机制：若某一列有效，对侧边缘列被填补或一致化
        row5 = out[out.shape[0] // 2]
        c0, c_last = row5[0], row5[-1]
        if np.isfinite(c0) or np.isfinite(c_last):
            assert c0 == pytest.approx(c_last)


class TestConsumersUseSharedSource:
    """消费方（overlay_recolor / overlay_registry）不再自带 EASE 常数。"""

    def test_overlay_recolor_constants_from_preset(self) -> None:
        from app.services import overlay_recolor as m

        assert m._EASE_GLOBAL_9K_SHAPE == (
            GRID_PRESETS["ease2-global-9km"]["rows"],
            GRID_PRESETS["ease2-global-9km"]["cols"],
        )
        # 模块内不再有自有 EASE 常数副本
        assert not hasattr(m, "_EASE_GRID_9K_PIXEL_SIZE")
        assert not hasattr(m, "_EASE_EASE_UL")

    def test_overlay_recolor_reprojects_any_ease_shape(self) -> None:
        """参数化验证：25km EASE 全球源同样被重投影（不再只认 9km）。"""
        from app.services.overlay_recolor import _reproject_ease_to_mercator_linear

        data = np.full((584, 1388), 5.0)
        out = _reproject_ease_to_mercator_linear(data)
        assert out.shape == (1440, 1440)
        assert np.isfinite(out).any()

    def test_overlay_recolor_passthrough_non_ease(self) -> None:
        from app.services.overlay_recolor import _reproject_ease_to_mercator_linear

        data = np.ones((176, 256))
        out = _reproject_ease_to_mercator_linear(data)
        assert out is data  # 非 EASE 形状原样返回

    def test_overlay_registry_constants_from_preset(self) -> None:
        from app.services.overlay_registry import OverlaySpec

        assert OverlaySpec._EASE_GRID_9K_PIXEL_SIZE == pytest.approx(
            float(GRID_PRESETS["ease2-global-9km"]["resolution"])
        )
        assert (
            OverlaySpec._EASE_GRID_9K_UL_X,
            OverlaySpec._EASE_GRID_9K_UL_Y,
        ) == (
            pytest.approx(EASE_UL_BY_CRS["EPSG:6933"][0]),
            pytest.approx(EASE_UL_BY_CRS["EPSG:6933"][1]),
        )

    def test_all_presets_declare_area_registration(self) -> None:
        for p in list_grid_presets():
            if p["id"] == "custom":
                continue
            assert p["cell_registration"] == CELL_REGISTRATION_AREA, p["id"]


# ── P1.5：像元配准归一化 ──────────────────────────────────────────────────


class TestInferCellRegistration:
    def test_edge_coordinates(self) -> None:
        assert infer_cell_registration(177, 176) == CELL_REGISTRATION_AREA

    def test_center_coordinates(self) -> None:
        assert infer_cell_registration(176, 176) == CELL_REGISTRATION_POINT

    def test_mismatch(self) -> None:
        assert infer_cell_registration(100, 176) == "unknown"
        assert infer_cell_registration(176, None) == "unknown"


class TestCoordsToAreaBounds:
    def test_point_expands_half_step(self) -> None:
        # aridity 中国区实型：lat 59→15（176 中心），lon 73→137（256 中心）
        lat = np.linspace(59.0, 15.0, 176)
        lon = np.linspace(73.0, 137.0, 256)
        result = coords_to_area_bounds(lat, lon, (176, 256))
        assert result is not None
        bounds, reg = result
        assert reg == CELL_REGISTRATION_POINT
        w, s, e, n = bounds
        assert w == pytest.approx(72.875, abs=1e-3)
        assert e == pytest.approx(137.125, abs=1e-3)
        assert s == pytest.approx(14.875, abs=1e-3)
        assert n == pytest.approx(59.125, abs=1e-3)

    def test_area_edges_asis(self) -> None:
        lat = np.linspace(59.0, 15.0, 177)  # N+1 边缘坐标
        lon = np.linspace(73.0, 137.0, 257)
        result = coords_to_area_bounds(lat, lon, (176, 256))
        assert result is not None
        bounds, reg = result
        assert reg == CELL_REGISTRATION_AREA
        assert bounds == pytest.approx([73.0, 15.0, 137.0, 59.0])

    def test_default_point_without_shape(self) -> None:
        lat = np.array([10.0, 20.0, 30.0])
        lon = np.array([100.0, 101.0, 102.0])
        bounds, reg = coords_to_area_bounds(lat, lon)
        assert reg == CELL_REGISTRATION_POINT
        # lat 步长 10 → ±5；lon 步长 1 → ±0.5
        assert bounds == pytest.approx([99.5, 5.0, 102.5, 35.0])

    def test_descending_coords_sorted(self) -> None:
        # .mat 常见北在前降序——归一化内部排序
        lat = np.array([30.0, 20.0, 10.0])
        lon = np.array([102.0, 101.0, 100.0])
        bounds, _ = coords_to_area_bounds(lat, lon)
        assert bounds == pytest.approx([99.5, 5.0, 102.5, 35.0])

    def test_invalid_returns_none(self) -> None:
        assert coords_to_area_bounds(np.array([1.0]), np.array([1.0, 2.0])) is None
        assert coords_to_area_bounds(
            np.array([np.nan, 2.0]), np.array([1.0, 2.0])
        ) is None
        # 外扩后越界（北极 / 日界线）
        assert coords_to_area_bounds(
            np.array([89.99, 90.0]), np.array([1.0, 2.0])
        ) is None
        assert coords_to_area_bounds(
            np.array([10.0, 20.0]), np.array([179.99, 180.0])
        ) is None


class TestMatLatlonBoundsRegistration:
    """_read_mat_latlon_bounds：中心坐标源外扩半格（P1.5 主修复点）。"""

    def test_center_coords_mat_expands(self, tmp_path: Path) -> None:
        from app.services.python_provider_result_builder import (
            _read_mat_latlon_bounds,
        )

        mat = tmp_path / "center.mat"
        savemat(
            str(mat),
            {
                "lat": np.linspace(59.0, 15.0, 176),
                "lon": np.linspace(73.0, 137.0, 256),
                "data": np.zeros((176, 256)),
            },
        )
        result = _read_mat_latlon_bounds(mat)
        assert result is not None
        bounds, reg = result
        assert reg == CELL_REGISTRATION_POINT
        assert bounds[0] == pytest.approx(72.875, abs=1e-3)
        assert bounds[3] == pytest.approx(59.125, abs=1e-3)

    def test_edge_coords_mat_asis(self, tmp_path: Path) -> None:
        from app.services.python_provider_result_builder import (
            _read_mat_latlon_bounds,
        )

        mat = tmp_path / "edge.mat"
        savemat(
            str(mat),
            {
                "lat": np.linspace(59.0, 15.0, 177),
                "lon": np.linspace(73.0, 137.0, 257),
                "data": np.zeros((176, 256)),
            },
        )
        result = _read_mat_latlon_bounds(mat)
        assert result is not None
        bounds, reg = result
        assert reg == CELL_REGISTRATION_AREA
        assert bounds == pytest.approx([73.0, 15.0, 137.0, 59.0])

    def test_missing_coords_returns_none(self, tmp_path: Path) -> None:
        from app.services.python_provider_result_builder import (
            _read_mat_latlon_bounds,
        )

        mat = tmp_path / "nocoord.mat"
        savemat(str(mat), {"data": np.zeros((4, 4))})
        assert _read_mat_latlon_bounds(mat) is None


class TestGribBoundsUsesSharedHelper:
    def test_grib_geo_bounds_expands_half_step(self) -> None:
        """GRIB 中心坐标 → 共享归一化外扩半格（行为与旧隐式实现一致）。"""

        class _Var:
            def __init__(self, values: np.ndarray) -> None:
                self.values = values
                self.shape = values.shape

        class _DS(dict):
            data_vars = ("t2m",)

        ds = _DS(
            {
                "latitude": _Var(np.array([30.0, 20.0, 10.0])),
                "longitude": _Var(np.array([100.0, 101.0, 102.0])),
                "t2m": _Var(np.zeros((3, 3))),
            }
        )
        from app.data_io.services.raster_science import _grib_geo_bounds

        # lat 步长 10 → ±5；lon 步长 1 → ±0.5（中心坐标外扩）
        assert _grib_geo_bounds(ds) == pytest.approx([99.5, 5.0, 102.5, 35.0])
