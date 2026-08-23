"""geo_math 双实现 golden 锁（架构审查 P3-4）。

背景：算法包禁止 import backend service（既有铁律），geo_math 因此双份
（backend ``app/services/geo_math.py`` vs algorithms
``data_access/geo_math.py``）。golden 测试锁两实现**共享函数**在相同输入
下逐位一致——任一侧改动（改公式/改舍入/改展开策略）必须两侧同步，
否则跨链路网格几何漂移。

不比较 backend 独有函数（is_finite_number/wrap_longitude/…）与
``pixel_center_axis`` 的 ``descending`` 参数（algorithms 版无此参数，
ascending 语义两侧一致）。
"""

from __future__ import annotations

import math

import pytest

from app.services import geo_math as backend_geo_math
from data_access import geo_math as algo_geo_math

_LNG_CASES: list[list[float]] = [
    [],
    [116.0],
    [73.0, 137.0],
    [-179.9, 179.9],  # 跨日界线
    [179.0, -179.0],
    [170.0, -170.0, 175.0],
    [-180.0, 180.0],  # 全球
    [0.0, 120.0, 240.0],  # 展开超 180
    [float("nan"), 116.0, float("inf"), 117.0],  # 混入非有限
    [116.0, 116.0],  # 零跨度
]

_SPAN_CASES: list[tuple[float, float]] = [
    (0.25, 0.1),
    (44.0, 0.25),
    (360.0, 0.25),
    (64.0, 9008.0552 / 111319.49),  # EASE 9km 度量
    (1.0, 3.0),  # span < res → 1
    (0.30000000000000004, 0.1),  # 浮点余数 → 3
    (7.0, 2.0),
    (100.0, 7.0),
]

_AXIS_CASES: list[tuple[float, float, int]] = [
    (73.0, 137.0, 256),
    (-180.0, 180.0, 1440),
    (15.0, 59.0, 176),
    (0.0, 1.0, 1),
    (-20037508.342789244, 20037508.342789244, 512),  # Mercator 米制
    (59.0, 15.0, 176),  # 降序 span（res 为负）
]


class TestGeoMathGolden:
    @pytest.mark.parametrize("lngs", _LNG_CASES)
    def test_lng_span_from_list(self, lngs: list[float]) -> None:
        assert backend_geo_math.lng_span_from_list(lngs) == (
            algo_geo_math.lng_span_from_list(lngs)
        )

    @pytest.mark.parametrize("span,res", _SPAN_CASES)
    def test_grid_size_from_span(self, span: float, res: float) -> None:
        assert backend_geo_math.grid_size_from_span(span, res) == (
            algo_geo_math.grid_size_from_span(span, res)
        )

    def test_grid_size_error_semantics_aligned(self) -> None:
        """两侧对非法输入的抛错语义一致（非有限 / 非正分辨率均 ValueError）。"""
        for bad in ((float("nan"), 1.0), (1.0, float("inf")), (1.0, 0.0), (1.0, -1.0)):
            with pytest.raises(ValueError):
                backend_geo_math.grid_size_from_span(*bad)
            with pytest.raises(ValueError):
                algo_geo_math.grid_size_from_span(*bad)

    @pytest.mark.parametrize("start,stop,count", _AXIS_CASES)
    def test_pixel_center_axis(self, start: float, stop: float, count: int) -> None:
        b = backend_geo_math.pixel_center_axis(start, stop, count)
        a = algo_geo_math.pixel_center_axis(start, stop, count)
        assert len(b) == len(a)
        for x, y in zip(b, a):
            # 逐位一致（同一公式）；防御浮点编译差异用极小容差
            assert x == pytest.approx(y, abs=1e-12, rel=1e-15)

    def test_pixel_center_axis_matches_from_bounds(self) -> None:
        """golden 基准：中心坐标必须与 rasterio from_bounds 语义一致。"""
        from rasterio.transform import from_bounds

        west, east, count = 73.0, 137.0, 256
        t = from_bounds(west, 0.0, east, 1.0, count, 1)
        axis = backend_geo_math.pixel_center_axis(west, east, count)
        for i, center in enumerate(axis):
            x, _ = t * (i + 0.5, 0.5)
            assert center == pytest.approx(x, abs=1e-12)

    def test_pixel_center_axis_error_semantics_aligned(self) -> None:
        for bad in ((0.0, 1.0, 0), (0.0, 1.0, -3)):
            with pytest.raises(ValueError):
                backend_geo_math.pixel_center_axis(*bad)
            with pytest.raises(ValueError):
                algo_geo_math.pixel_center_axis(*bad)
        for bad_axis in ((float("nan"), 1.0, 4), (0.0, float("inf"), 4)):
            with pytest.raises(ValueError):
                backend_geo_math.pixel_center_axis(*bad_axis)
            with pytest.raises(ValueError):
                algo_geo_math.pixel_center_axis(*bad_axis)

    def test_dtypes_and_finiteness(self) -> None:
        out = algo_geo_math.pixel_center_axis(0.0, 10.0, 5)
        assert len(out) == 5
        assert all(math.isfinite(v) for v in out)
        assert out[0] == pytest.approx(1.0)
        assert out[-1] == pytest.approx(9.0)
