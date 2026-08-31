"""Regression: overlay recolor must NOT corner-crop large global grids.

历史根因（2026-08 用户报障"全球辅助图层局部裁剪+全屏拉伸"）：
``overlay_recolor._load_source_grid`` 的 .mat/.nc 分支曾用步长伪降采样
``values[::rs, ::cs][:oh, :ow]``。对 EASE-Grid 2.0 全球 9km(1624,3856) 且
scale=2048/3856≈0.531 → rs=cs=1 → 退化为左上角 53%×53% 纯裁剪
（纬度 85N~6N × 经度 -180~21E = 北美+南美北+北非+西欧，与用户描述逐字吻合），
再把该裁剪图贴全球 bounds → 南北大拉伸全屏。

本测试锁定两层回归：
  1. EASE-Grid 全球源 → 先做 Web Mercator 线性重投影（1440×1440，与烘焙资产
     同几何），输出为全覆盖等比（非左上裁剪），且角/心采样值来自源对应区域。
  2. 非 EASE 大网格（宽>2048）→ ``np.linspace`` 均匀重采样，不丢右下区数据
     （旧实现 rs=cs=1 时右/下被整块裁掉）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from scipy.io import savemat

from app.services.overlay_recolor import (
    _EASE_GLOBAL_9K_SHAPE,
    _MAX_PREVIEW_EDGE,
    _load_source_grid,
)

# EASE-Grid 2.0 全球 9km 几何常量（与 overlay_recolor 中一致，测试自校验用）
_EASE_UL_X = -17367530.45
_EASE_UL_Y = 7314540.83
_EASE_PX = 9008.0552
_EASE_CRS = "EPSG:6933"
_MERCATOR_MAX_Y = 20037508.342789244
_MERCATOR_RADIUS = 6378137.0


class _SpecStub:
    """最小化实现 _load_source_grid 所需的 OverlaySpec 接口子集。"""

    def __init__(
        self,
        path: Path,
        *,
        source_variable: str | None = None,
        source_reader: str = "mat",
    ) -> None:
        self._path = path
        self.source_variable = source_variable
        self.source_reader = source_reader

    def resolve_source_path(self, time: str | None = None) -> Path:
        return self._path


def _write_mat(path: Path, name: str, arr: np.ndarray) -> Path:
    """用例内构造 .mat（v5 变量名任意），供 UniversalDataReader 读取。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    savemat(str(path), {name: arr})
    return path


# ── 地理工具：EASE 源坐标（权威 PROJ 正算），供测试独立生成编码值 ──────────
def _ease_source_coords() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """返回源每条/列的经度网格(2D) 、纬度网格(2D) 与有效掩膜。

    用 pyproj（PROJ 权威实现）把 EASE(sc, row) 米坐标正算到 lon/lat —— 与
    ``overlay_recolor`` 的 rasterio.warp.reproject（同为 PROJ 内核）互为交叉验证。
    """
    from pyproj import Transformer

    h, w = _EASE_GLOBAL_9K_SHAPE
    tf = Transformer.from_crs(_EASE_CRS, "EPSG:4326", always_xy=True)
    rows = np.arange(h)
    cols = np.arange(w)
    cc, rr = np.meshgrid(cols, rows)
    x = _EASE_UL_X + (cc + 0.5) * _EASE_PX
    y = _EASE_UL_Y - (rr + 0.5) * _EASE_PX
    lon, lat = tf.transform(x, y)
    valid = np.isfinite(lat) & np.isfinite(lon)
    return lon, lat, valid


def _build_ease_source() -> np.ndarray:
    """构造 EASE 全球 9km 源：每个单元编码其真实经纬度，可解码核验全覆盖。

    编码：value = round(lat*10)*1000 + (lon + 180)。重投影/采样后任何输出值
    都可反解其源 (lat, lon)，与目标像素应处的经纬度对比即可判定几何是否对齐、
    是否漏裁某区域。
    """
    lon, lat, valid = _ease_source_coords()
    src = np.full(_EASE_GLOBAL_9K_SHAPE, np.nan, dtype=np.float64)
    src[valid] = np.round(lat[valid] * 10.0) * 1000.0 + (lon[valid] + 180.0)
    return src


def _decode(value: float) -> tuple[float, float]:
    """解码上面编码的源值 → (lat, lon)。"""
    lat = np.floor(value / 1000.0) / 10.0
    lon = value - np.floor(value / 1000.0) * 1000.0 - 180.0
    return float(lat), float(lon)


def _mercator_lat_at_row(r: int, h: int) -> float:
    """Mercator 线性网格第 r 行中心（北→南）对应的纬度中心。"""
    y = _MERCATOR_MAX_Y - (r + 0.5) * (2.0 * _MERCATOR_MAX_Y / h)
    return float(np.degrees(2.0 * np.arctan(np.exp(y / _MERCATOR_RADIUS)) - np.pi / 2.0))


def _mercator_lon_at_col(c: int, w: int) -> float:
    """Mercator 线性网格第 c 列中心（西→东）对应的经度中心。"""
    return -180.0 + (c + 0.5) * 360.0 / w


def _assert_geocoded_cell(
    grid: np.ndarray,
    r: int,
    c: int,
    *,
    tol_lat: float,
    tol_lon: float,
) -> None:
    """断言 grid[r, c] 解码的 (lat, lon) 落在目标像素经纬度容差内。"""
    v = float(grid[r, c])
    assert np.isfinite(v), f"cell ({r},{c}) should be finite"
    dec_lat, dec_lon = _decode(v)
    tgt_lat = _mercator_lat_at_row(r, grid.shape[0])
    tgt_lon = _mercator_lon_at_col(c, grid.shape[1])
    assert abs(dec_lon - tgt_lon) <= tol_lon, (
        f"lon mismatch at ({r},{c}): decoded={dec_lon:.3f} target={tgt_lon:.3f}"
    )
    assert abs(dec_lat - tgt_lat) <= tol_lat, (
        f"lat mismatch at ({r},{c}): decoded={dec_lat:.3f} target={tgt_lat:.3f}"
    )


# ── 用例 1：EASE 全球源 → Mercator 线性全覆盖，非左上裁剪 ──────────────────
def test_ease_global_grid_reprojects_full_coverage_and_geocoded(tmp_path: Path) -> None:
    src = _build_ease_source()
    mat = _write_mat(tmp_path / "ease_field.mat", "FIELD", src)
    spec = _SpecStub(mat, source_variable="FIELD", source_reader="mat")

    grid = _load_source_grid(spec, time=None)
    assert grid is not None
    # 输出为 Mercator 线性等比网格 —— 不再是左上角 863×2048 裁剪
    h, w = grid.shape
    assert w > _MAX_PREVIEW_EDGE * 0.5, f"expected full-width output, got w={w}"
    assert abs(h - w) <= max(2, int(0.02 * w)), f"expected ~square Mercator, got {h}×{w}"
    # 全覆盖：四角 + 中心 + 南北中轴均非空（旧裁剪只覆盖左上，右下必为 NaN）
    for r, c in [(5, 5), (2, w // 2), (h // 2, w // 2), (h - 3, w // 2), (h - 6, w - 6)]:
        assert np.isfinite(grid[r, c]), f"cell ({r},{c}) should be covered (full-coverage)"

    # 角/心解码值应来自源对应区域（几何对齐）
    _assert_geocoded_cell(grid, 5, 5, tol_lat=1.2, tol_lon=0.2)
    _assert_geocoded_cell(grid, h // 2, w // 2, tol_lat=0.2, tol_lon=0.2)
    _assert_geocoded_cell(grid, h - 6, w - 6, tol_lat=1.2, tol_lon=0.2)


def _build_wide_source(h: int, w: int) -> np.ndarray:
    """构造 h×w 大网格：左上/中心/右下各放 8×8 特征区块，其余为 0.15。

    旧实现 ``rs=max(1, h//oh)=1 → values[:oh,:ow]`` 纯裁剪会丢掉右下区块
    （末 h-oh 行、末 w-ow 列整块消失）；linspace 均匀采样（采样密度≈每 2 行/列
    取 1）下 8×8 区块必然至少被采到一次，三区块特征值必然全部保留。
    """
    arr = np.full((h, w), 0.15, dtype=np.float64)
    b = 8  # block size
    arr[0:b, 0:b] = 1.0  # 左上（旧 bug 恰好保留的区域）
    arr[h // 2 - b // 2 : h // 2 + b // 2, w // 2 - b // 2 : w // 2 + b // 2] = 2.0  # 中心
    arr[h - b : h, w - b : w] = 3.0  # 右下（旧 bug 必丢的区域 —— 回归核心判据）
    return arr


# ── 用例 2：非 EASE 大网格 → linspace 均匀重采样，不裁右下 ─────────────────
def test_non_ease_wide_grid_linspace_no_crop(tmp_path: Path) -> None:
    h, w = 900, 4000
    src = _build_wide_source(h, w)
    mat = _write_mat(tmp_path / "wide_field.mat", "FIELD", src)
    spec = _SpecStub(mat, source_variable="FIELD", source_reader="mat")

    grid = _load_source_grid(spec, time=None)
    assert grid is not None
    out_h, out_w = grid.shape
    # linspace 输出尺寸 = round(h*scale) × round(w*scale)，且宽轴钳到 2048
    assert out_w <= _MAX_PREVIEW_EDGE
    scale = min(_MAX_PREVIEW_EDGE / max(h, 1), _MAX_PREVIEW_EDGE / max(w, 1), 1.0)
    assert out_h == max(1, int(round(h * scale)))
    assert out_w == max(1, int(round(w * scale)))
    # 全覆盖证据：三个特征区块都保留（旧裁剪会整块丢右下）
    flattened = grid.ravel()
    assert 1.0 in flattened, "左上区块丢失"
    assert 2.0 in flattened, "中心区块丢失"
    assert 3.0 in flattened, "右下区块被裁剪丢失（回归核心判据）"
    # 旧 bug 的输出尺寸恰为 (461, 2048) 但内容只是左上 461×2048；新实现的
    # (461, 2048) 覆盖全图 —— 用右下区块存在性区分二者。


def test_non_ease_wide_grid_keeps_aspect_no_topleft_only(tmp_path: Path) -> None:
    """窄于 2048×2048 的网格不触发降采样，直接原样返回（保宽高比）。"""
    h, w = 600, 800
    src = np.full((h, w), 0.25, dtype=np.float64)
    mat = _write_mat(tmp_path / "small_field.mat", "FIELD", src)
    spec = _SpecStub(mat, source_variable="FIELD", source_reader="mat")

    grid = _load_source_grid(spec, time=None)
    assert grid is not None
    assert grid.shape == (h, w), f"small grid should pass through unchanged, got {grid.shape}"
    # 四角都应有值（无裁剪）
    assert grid[0, 0] == 0.25 and grid[h - 1, w - 1] == 0.25
