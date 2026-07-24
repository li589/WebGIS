#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量导出叠加图层预览资产（PNG + bounds JSON）。

为后端 overlay_registry.py 中注册的每个图层生成地理配准 PNG 预览图。
输出目录: I:\\Geograph_DataSet\\ProjectOutput\\2023-01_Omega_Inversion\\_overlays\\

支持的图层（Phase 1.6 扩展后）:
  1. dem-etopo           — ETOPO_2022 bed topography (global, terrain)
  2. landcover-cn        — MCD12Q1 landcover (China 0.25deg, IGBP)
  3. hfp-cn              — Human Footprint (China 0.25deg, hot)
  4. aridity-cn          — Aridity Index (China 0.25deg, BrBG)
  5. omega-output [TS]   — Omega inversion avg 时间序列 (doy 017-030, 14 天, plasma)
  6. smap-sm-ts [TS]     — SMAP soil moisture 时间序列 (China, 13 days)
  7. gpcp-precip-ts [TS] — GPCP monthly precipitation 时间序列 (global, 24 months)
  8. gebco-dem-cn        — GEBCO 2024 DEM (China)
  9. cmfd-precip-cn      — CMFD 降水 (China 1km, 2002-01)
 10. clcd-cn             — CLCD 1997 土地覆盖 (China)
 11. biomass-cn          — ESACCI BIOMASS 2020 (China)
 12. era5-dwaa-cn        — ERA5 白天热浪事件 (China, 2020)
 13. era5-wdaa-cn        — ERA5 夜间热浪事件 (China, 2020)
 14. co2-cn              — GOSAT 中层 CO2 柱浓度 (China)
 15. soil-ddca [TS]      — Soil DDCA DH 时间序列 (2015-04 ~ 2022-12, 采样 60 天)
 16. omega-fy-output [TS]— Omega FY avg 时间序列 (doy 025-030, 6 天, magma)
 17. forest-ratio        — Forest Ratio 9KM 2020 (global EASE-Grid 9km, YlGn)
  18. landscape-metrics-9km — Shannon 多样性指数 SHDI (global EASE-Grid 9km, cividis) [Phase 1.6 新增]
  19. vod-dec2025 [TS]    — VOD 植被光学厚度时间序列 (2025-12, 31 天, magma) [Phase 2 新增]
  20. sm-dec2025 [TS]     — SM 土壤湿度时间序列 (2025-12, 31 天, YlGnBu) [Phase 2 新增]
  21. omega-dec2025 [TS]  — Omega 反演时间序列 (2025-12, 31 天, plasma) [Phase 2 新增]

[TS] = 时间序列图层，输出多张按时间索引的 PNG + bounds JSON。
"""

from __future__ import annotations

import json
import sys
import os
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore", category=UserWarning)

# matplotlib Agg backend
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Output root
_OUT_ROOT = Path(r"I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion\_overlays")
_CHINA_BBOX = (73.0, 15.0, 137.0, 59.0)

# ── Phase 1.6: 课题组时间序列源数据目录（与 overlay_registry.py 同步）──────────
_INVERSION_RESULTS_ROOT = Path(r"I:\Geograph_DataSet\InversionResults")
_OMEGA_SMAP_AVG_DIR = _INVERSION_RESULTS_ROOT / "smap_avg"
_OMEGA_FY_AVG_DIR = _INVERSION_RESULTS_ROOT / "fy_avg"
_SOIL_DDCA_H_DIR = Path(r"I:\Geograph_DataSet\Soil_Ecological_Data\DDCA\DDCA_DH\H")
_LANDSCAPE_METRICS_MAT = (
    _INVERSION_RESULTS_ROOT / "Landscape_Metrics_LandOnly_9KM_2020.mat"
)

# ── Phase 2: 课题组 VOD/SM 产品族（2025-12 时间序列，EASE-Grid 9km）──────────
# SmapSoil_VOD_SM/YYYYMMDD.mat (v7.3 HDF5) 含 OMEGA / SM / VOD 三个变量，shape (1624, 3856)
_SMAP_SOIL_VOD_SM_DIR = Path(
    r"I:\Geograph_DataSet\Soil_Ecological_Data\SmapSoil_VOD_SM"
)


def _doy_time_list(directory: Path, prefix: str = "doy_") -> list[str]:
    """从 InversionResults/smap_avg|fy_avg 目录推断 doy 时间序列标签。

    文件名形如 ``doy_017.mat`` → 标签 ``'017'``。
    与 overlay_registry.py 中的同名 helper 保持一致，确保导出的 PNG 时间标签
    与运行时 time_list 完全匹配。
    """
    if not directory.exists():
        return []
    tags: list[str] = []
    for f in sorted(directory.glob(f"{prefix}*.mat")):
        stem = f.stem  # 'doy_017'
        if stem.startswith(prefix):
            tag = stem[len(prefix) :]
            if tag.isdigit():
                tags.append(tag)
    return tags


def _soil_ddca_time_list(limit: int = 60) -> list[str]:
    """从 Soil_Ecological_Data/DDCA/DDCA_DH/H 目录推断日期时间序列标签。

    文件名形如 ``20150401.mat`` → 标签 ``'20150401'``。
    限制最多 limit 个标签（均匀采样），与 overlay_registry.py 中的同名 helper 一致。
    实际数据范围：2015-04-01 ~ 2022-12-31（~2747 天），采样后约 60 个时间点。
    """
    if not _SOIL_DDCA_H_DIR.exists():
        return []
    tags: list[str] = []
    for f in sorted(_SOIL_DDCA_H_DIR.glob("*.mat")):
        stem = f.stem
        if len(stem) == 8 and stem.isdigit():
            tags.append(stem)
    if len(tags) > limit:
        step = max(1, len(tags) // limit)
        tags = tags[::step][:limit]
    return tags


def _date8_time_list(directory: Path, limit: int | None = None) -> list[str]:
    """通用 8 位日期时间序列标签扫描：YYYYMMDD.mat → 'YYYYMMDD'。

    与 ``_soil_ddca_time_list`` 逻辑一致，但接受任意目录参数，且 ``limit=None``
    时不采样（返回全部日期）。供 Phase 2 VOD/SM 产品族使用。

    Args:
        directory: 包含 YYYYMMDD.mat 文件的目录
        limit: 可选，最大标签数（均匀采样）；None 表示返回全部

    Returns:
        排序后的 8 位日期字符串列表
    """
    if not directory.exists():
        return []
    tags: list[str] = []
    for f in sorted(directory.glob("*.mat")):
        stem = f.stem
        if len(stem) == 8 and stem.isdigit():
            tags.append(stem)
    if limit is not None and len(tags) > limit:
        step = max(1, len(tags) // limit)
        tags = tags[::step][:limit]
    return tags


def _render_png(
    data: np.ndarray,
    png_path: Path,
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    transparent: bool = True,
) -> None:
    """Render 2D array to a borderless PNG (no axes, no colorbar).

    写入策略（绕过外部 HDD 上的 PIL ``open(filename, "w+b")`` 权限问题）：
    1. matplotlib 输出到 ``io.BytesIO`` 内存缓冲（不触碰磁盘）
    2. 用 ``Path.write_bytes()`` 直接写文件（Python 内置 open "wb" 模式，
       比 PIL 的 "w+b" 模式兼容性更好，能绕过 Windows 文件锁/杀软扫描）
    3. 若目标已存在且被锁，``write_bytes`` 会先 unlink 再写；失败则退避重试

    经验：外部 HDD (I:) 上 PIL ``Image.save()`` 偶发 PermissionError，
    即使是新文件也会失败；改用 ``write_bytes`` 后稳定通过。
    """
    import io
    import time

    png_path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(data, dtype=np.float64)
    if data.ndim != 2:
        raise ValueError(f"Expected 2D array, got {data.ndim}D")

    n_lat, n_lon = data.shape
    # 关键修复：figsize 与数据行列严格 1:1（dpi=100 → 1 inch = 100 px）
    # 最小 1.0 英寸避免极小数组渲染失败，但不再钳位到 2 英寸（避免 PNG 拉伸导致偏移）
    figsize = (max(n_lon / 100, 1.0), max(n_lat / 100, 1.0))
    fig = plt.figure(figsize=figsize, frameon=False)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    # Mask NaN as transparent
    masked = np.ma.masked_invalid(data)
    ax.imshow(
        masked,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        aspect="auto",
        origin="upper",
        interpolation="nearest",
    )

    # 渲染到内存缓冲（matplotlib 输出 PNG 字节流）
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, transparent=transparent, pad_inches=0)
    plt.close(fig)
    png_bytes = buf.getvalue()

    # 写入磁盘（带重试，处理外部 HDD 瞬时锁）
    max_attempts = 5
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            # write_bytes 内部用 open("wb")，比 PIL 的 open("w+b") 兼容性更好
            # 若目标已存在且被锁，write_bytes 会失败 → 进入重试
            png_path.write_bytes(png_bytes)
            break
        except PermissionError as e:
            last_err = e
            if attempt < max_attempts:
                wait = 0.5 * attempt  # 0.5s, 1s, 1.5s, 2s, 2.5s
                print(
                    f"  [RETRY {attempt}/{max_attempts}] {png_path.name} locked, waiting {wait:.1f}s..."
                )
                time.sleep(wait)
            else:
                # 最后一次尝试：写临时文件 + os.replace 原子替换
                import os

                tmp_path = png_path.parent / f"{png_path.name}.tmp_{os.getpid()}.png"
                try:
                    tmp_path.write_bytes(png_bytes)
                    os.replace(tmp_path, png_path)
                    break
                except PermissionError:
                    raise
    if last_err is not None:
        print(f"  [WARN] {png_path.name} saved after retries (last_err={last_err})")
    print(f"  [OK] PNG saved: {png_path.name} ({n_lat}x{n_lon})")


def _write_bounds(
    bounds_path: Path, layer_id: str, bounds: tuple[float, float, float, float]
) -> None:
    """Write bounds JSON file (临时文件 + 原子替换，处理外部 HDD 文件锁)."""
    import time

    bounds_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "layer_id": layer_id,
        "bounds": list(bounds),  # [west, south, east, north]
        "crs": "EPSG:4326",
    }
    text = json.dumps(data, indent=2)
    tmp_path = bounds_path.parent / f"{bounds_path.name}.tmp_{os.getpid()}.json"
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            tmp_path.write_text(text, encoding="utf-8")
            os.replace(tmp_path, bounds_path)
            break
        except PermissionError:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except PermissionError:
                    pass
            if attempt < max_attempts:
                time.sleep(0.5 * attempt)
            else:
                raise
    print(
        f"  [OK] bounds saved: {bounds_path.name} (W{bounds[0]:.1f} S{bounds[1]:.1f} E{bounds[2]:.1f} N{bounds[3]:.1f})"
    )


def _bounds_from_centers(lat_1d, lon_1d):
    """从像素中心坐标数组计算地理边界 (west, south, east, north)。

    坐标数组存储的是像素中心点，但 bounds JSON 需要像素外边界。
    本函数向外扩展半个像素间距，避免数据整体偏移。

    支持传入 1D 或 2D 数组（2D 会先 ravel）。
    自动过滤 NaN/Inf 值，避免 SMAP 等 .mat 中含 NaN 坐标导致结果为 NaN。

    Args:
        lat_1d: 纬度数组（1D 或 2D，升序或降序均可）
        lon_1d: 经度数组（1D 或 2D，升序或降序均可）

    Returns:
        (west, south, east, north) — WGS84 经纬度边界；若坐标全无效返回全 NaN
    """
    lat = np.asarray(lat_1d, dtype=np.float64).ravel()
    lon = np.asarray(lon_1d, dtype=np.float64).ravel()
    # 过滤 NaN / Inf，避免中位数计算返回 NaN
    lat = lat[np.isfinite(lat)]
    lon = lon[np.isfinite(lon)]
    if len(lat) == 0 or len(lon) == 0:
        return (float("nan"), float("nan"), float("nan"), float("nan"))
    # 排序后取相邻差的中位数，避免 2D ravel 后跨行跳变导致 diff 异常
    lat_sorted = np.sort(lat)
    lon_sorted = np.sort(lon)
    dlat = float(np.median(np.abs(np.diff(lat_sorted)))) if len(lat_sorted) > 1 else 0.0
    dlon = float(np.median(np.abs(np.diff(lon_sorted)))) if len(lon_sorted) > 1 else 0.0
    north = float(lat_sorted[-1] + dlat / 2)
    south = float(lat_sorted[0] - dlat / 2)
    east = float(lon_sorted[-1] + dlon / 2)
    west = float(lon_sorted[0] - dlon / 2)
    return (west, south, east, north)


# EASE-Grid 2.0 9km 标准定义（NSIDC）
# 注意：500m 网格的像素尺寸 = 500.4475m；9km 标称 = 18 × 500.4475 = 9008.0552m
# 早期硬编码 9000.879 是错误的（差 7.18m/像素，1624 行累计偏差 11.6km）
_EASE_GRID_9K_CRS = "EPSG:6933"
_EASE_GRID_9K_PIXEL_SIZE = 9008.0552  # 米（= 18 × 500.4475，NSIDC 标准）
_EASE_GRID_9K_UL_X = -17367530.45  # 上左角 x（米）
_EASE_GRID_9K_UL_Y = 7314540.83  # 上左角 y（米）


def _ease_grid_9k_transform():
    """返回 EASE-Grid 2.0 9km 的 Affine 变换（rasterio 约定）。"""
    from rasterio.transform import from_origin

    return from_origin(
        _EASE_GRID_9K_UL_X,
        _EASE_GRID_9K_UL_Y,
        _EASE_GRID_9K_PIXEL_SIZE,
        _EASE_GRID_9K_PIXEL_SIZE,
    )


def _ease_grid_9k_transform_from_mat(mat_dict):
    """从 .mat 元数据构建 EASE-Grid transform（优先用 .mat 提供的真实参数）。

    .mat 中 Transform 是 6 元素 [a, b, c, d, e, f]（仿射）：
      x = a*col + b*row + c
      y = d*col + e*row + f
    .mat 中像素尺寸 500.4475m（500m 网格），但数据是 9km 重采样后的产品。
    实际 9km 像素 = 18 × 500.4475 = 9008.0552m（与 _EASE_GRID_9K_PIXEL_SIZE 一致）。

    Args:
        mat_dict: _read_mat_auto() 返回的字典

    Returns:
        rasterio.Affine 或 None（无元数据时）
    """
    if "Transform" not in mat_dict or "CRS" not in mat_dict:
        return None
    try:
        from rasterio.transform import Affine

        t = np.asarray(mat_dict["Transform"]).ravel()
        if len(t) < 6:
            return None
        # 优先使用 .mat 中的真实像素尺寸（500.4475 × 18 = 9008.0552）
        # 但 .mat Transform 给的是 500m 网格参数，9km 数据需要 × 18
        # 检测：如果像素尺寸接近 500m，则 × 18 转为 9km
        pixel_x = abs(float(t[1]))
        if 400 < pixel_x < 600:  # 500m 网格
            scale = 18
            a = float(t[1]) * scale
            e = float(t[5]) * scale
            c = float(t[0])  # 上左 x
            f = float(t[3])  # 上左 y
            return Affine(a, 0.0, c, 0.0, e, f)
        # 否则按原样使用
        return Affine(
            float(t[1]), float(t[2]), float(t[0]), float(t[4]), float(t[5]), float(t[3])
        )
    except Exception:
        return None


def _reproject_ease_to_wgs84(
    data, target_resolution=0.1, clip_bounds=_CHINA_BBOX, mat_dict=None
):
    """将 EASE-Grid 2.0 9km 数据重投影到 WGS84 等经纬度网格，并裁剪到指定区域。

    EASE-Grid 2.0 9km 是圆柱等积投影（EPSG:6933），行间距随纬度变化。
    直接当作经纬度会导致高纬度地区偏移上百公里。本函数使用 rasterio.warp
    重采样到等经纬度网格，确保地理定位准确。

    重要：全球 EASE-Grid 数据 (-180,-84,180,85) 通过 MapLibre image source 渲染时，
    4 角线性插值在 Web Mercator 投影下高纬度严重拉伸（南北方向）。
    因此重投影后必须裁剪到中国区域 (73,15,137,59)，避免高纬度 Mercator 拉伸。

    Args:
        data: (n_lat, n_lon) 2D array，EASE-Grid 2.0 9km 数据
        target_resolution: 目标分辨率（度），默认 0.1°
        clip_bounds: (west, south, east, north) 裁剪边界，默认中国区域；
                     None 表示不裁剪（保留全球范围，仅用于诊断）
        mat_dict: 可选，.mat 元数据字典（用于读取真实 Transform）

    Returns:
        (reprojected_data, bounds) — bounds = (west, south, east, north)
    """
    from rasterio.warp import reproject, calculate_default_transform
    from rasterio.enums import Resampling

    # 优先使用 .mat 提供的真实 Transform
    src_transform = None
    if mat_dict is not None:
        src_transform = _ease_grid_9k_transform_from_mat(mat_dict)
    if src_transform is None:
        src_transform = _ease_grid_9k_transform()

    src_crs = _EASE_GRID_9K_CRS
    dst_crs = "EPSG:4326"

    n_lat, n_lon = data.shape
    # 计算目标网格的 transform 和尺寸
    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs,
        dst_crs,
        n_lon,
        n_lat,
        *_ease_grid_9k_transform_bounds(src_transform, n_lon, n_lat),
        resolution=target_resolution,
    )

    dst_data = np.full((dst_height, dst_width), np.nan, dtype=np.float64)
    reproject(
        source=data,
        destination=dst_data,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=Resampling.nearest,  # 分类数据用最近邻；连续数据可改 bilinear
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )

    # 计算 WGS84 边界（dst_transform 的像素边界）
    west = dst_transform[2]
    east = dst_transform[2] + dst_transform[0] * dst_width
    north = dst_transform[5]
    south = dst_transform[5] + dst_transform[4] * dst_height

    # 裁剪到指定区域（默认中国），避免高纬度 Web Mercator 拉伸
    if clip_bounds is not None:
        dst_data, west, south, east, north = _clip_wgs84_array(
            dst_data,
            dst_transform,
            west=west,
            south=south,
            east=east,
            north=north,
            clip_bounds=clip_bounds,
        )

    return dst_data, (float(west), float(south), float(east), float(north))


def _clip_wgs84_array(data, transform, west, south, east, north, clip_bounds):
    """裁剪 WGS84 网格数组到指定边界。

    Args:
        data: (n_lat, n_lon) 2D array
        transform: rasterio Affine transform
        west, south, east, north: 当前数据的地理边界
        clip_bounds: (west, south, east, north) 目标裁剪边界

    Returns:
        (clipped_data, new_west, new_south, new_east, new_north)
    """
    cw, cs, ce, cn = clip_bounds
    # 求交集（避免裁剪到数据范围外）
    cw = max(cw, west)
    cs = max(cs, south)
    ce = min(ce, east)
    cn = min(cn, north)
    if cw >= ce or cs >= cn:
        # 无交集，返回原数据
        return data, west, south, east, north

    pixel_w = abs(transform[0])
    pixel_h = abs(transform[4])
    if pixel_w <= 0 or pixel_h <= 0:
        return data, west, south, east, north

    # 计算裁剪后的像素索引（按行列计算）
    # transform: x = a*col + c; y = e*row + f
    # 假设 a > 0, e < 0（北朝上，西朝左）
    a = transform[0]
    c = transform[2]
    e = transform[4]
    f = transform[5]
    if a > 0 and e < 0:
        col_w = int(np.floor((cw - c) / a))
        col_e = int(np.ceil((ce - c) / a))
        row_n = int(np.floor((cn - f) / e))
        row_s = int(np.ceil((cs - f) / e))
    else:
        # 不支持的 transform 方向，跳过裁剪
        return data, west, south, east, north

    n_lat, n_lon = data.shape
    col_w = max(0, min(col_w, n_lon))
    col_e = max(0, min(col_e, n_lon))
    row_n = max(0, min(row_n, n_lat))
    row_s = max(0, min(row_s, n_lat))
    if col_w >= col_e or row_n >= row_s:
        return data, west, south, east, north

    clipped = data[row_n:row_s, col_w:col_e]
    # 裁剪后的边界：用像素外边沿
    new_west = c + col_w * a
    new_east = c + col_e * a
    new_north = f + row_n * e
    new_south = f + row_s * e
    return clipped, new_west, new_south, new_east, new_north


def _ease_grid_9k_transform_bounds(transform, width, height):
    """计算 rasterio transform 的地理边界 (west, south, east, north)。"""
    # transform * (col, row) → (x, y)
    # 左上角 (0, 0)，右下角 (width, height)
    x_ul, y_ul = transform * (0, 0)
    x_lr, y_lr = transform * (width, height)
    return (min(x_ul, x_lr), min(y_ul, y_lr), max(x_ul, x_lr), max(y_ul, y_lr))


# ──────────────────────────────────────────────────────────────────────────────
# 1. DEM ETOPO_2022
# ──────────────────────────────────────────────────────────────────────────────


def export_dem_etopo() -> None:
    print("\n=== DEM ETOPO_2022 ===")
    tif_path = Path(
        r"I:\Geograph_DataSet\DEM\ETOPO_2022\ETOPO_2022_v1_60s_N90W180_surface.tif"
    )
    if not tif_path.exists():
        print("  [SKIP] File not found")
        return

    import rasterio
    from rasterio.enums import Resampling

    out_dir = _OUT_ROOT / "dem"
    # Downsample to ~0.5 degree for manageable PNG size
    with rasterio.open(tif_path) as src:
        # Global ETOPO 60s: 10800 x 21600. Downsample by factor 12 -> 900 x 1800
        scale = 12
        data = src.read(
            1,
            out_shape=(src.height // scale, src.width // scale),
            resampling=Resampling.average,
        ).astype(np.float32)
        # Get bounds from source
        west, south, east, north = src.bounds
        # Replace nodata with NaN
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = np.nan

    print(
        f"  Data shape: {data.shape}, range: {np.nanmin(data):.1f} to {np.nanmax(data):.1f}"
    )
    _render_png(
        data, out_dir / "etopo_bed_overlay.png", cmap="terrain", vmin=-8000, vmax=8000
    )
    _write_bounds(
        out_dir / "etopo_bed_overlay_bounds.json",
        "dem-etopo",
        (float(west), float(south), float(east), float(north)),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2-4. China regional .mat files (landcover, hfp, aridity)
# ──────────────────────────────────────────────────────────────────────────────


def _read_mat_v5(path: Path) -> dict:
    """Read v5/v6 .mat file using scipy.io.loadmat."""
    from scipy.io import loadmat

    m = loadmat(str(path))
    return {k: v for k, v in m.items() if not k.startswith("__")}


def _read_mat_v73(path: Path) -> dict:
    """Read v7.3 .mat file using h5py (with transpose)."""
    import h5py

    result = {}
    with h5py.File(str(path), "r") as f:
        for k in f.keys():
            arr = f[k][:]
            # h5py reads MATLAB data in column-major; 2D arrays need transpose
            if arr.ndim == 2:
                arr = arr.T
            result[k] = arr
    return result


def _read_mat_auto(path: Path) -> dict:
    """Auto-detect .mat format and read accordingly."""
    try:
        return _read_mat_v5(path)
    except Exception:
        return _read_mat_v73(path)


def export_thematic_layers() -> None:
    print("\n=== Thematic layers (landcover, hfp, aridity) ===")
    stage2 = Path(
        r"I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion\stage2_aligned"
    )
    out_dir = _OUT_ROOT / "thematic"

    # 修复：从 .mat 读取实际 lat/lon 坐标计算 bounds，不再使用硬编码 _CHINA_BBOX
    for fname, varname, layer_id, cmap, vmin, vmax in [
        ("landcover_025.mat", "landcover", "landcover-cn", "nipy_spectral", 1, 17),
        ("hfp_025.mat", "hfp", "hfp-cn", "hot", 0, 50),
        ("aridity_025.mat", "aridity", "aridity-cn", "BrBG", 0, 2),
    ]:
        path = stage2 / fname
        if not path.exists():
            print(f"  [SKIP] {fname} not found")
            continue
        m = _read_mat_v5(path)
        data = m[varname].astype(np.float64)
        if varname == "landcover":
            data[data == 0] = np.nan
        # 从 .mat 读取实际坐标，计算像素外边界
        lat = m.get("lat")
        lon = m.get("lon")
        if lat is not None and lon is not None:
            bounds = _bounds_from_centers(lat, lon)
        else:
            bounds = _CHINA_BBOX  # fallback
            print(f"  [WARN] {fname} has no lat/lon, using _CHINA_BBOX fallback")
        print(f"  {layer_id}: {data.shape}, bounds={bounds}")
        _render_png(
            data, out_dir / f"{varname}_overlay.png", cmap=cmap, vmin=vmin, vmax=vmax
        )
        _write_bounds(out_dir / f"{varname}_overlay_bounds.json", layer_id, bounds)


# ──────────────────────────────────────────────────────────────────────────────
# 5. Omega inversion result 时间序列（doy 017-030，14 天）
# ──────────────────────────────────────────────────────────────────────────────


def export_omega_ts() -> None:
    """导出 omega-output 时间序列：每个 doy 一个 PNG + bounds JSON。

    输出文件：
      - ``_OVERLAY_PNG_ROOT/omega_ts/omega_avg_{tag}.png``（tag = '017', '018', ...）
      - ``_OVERLAY_PNG_ROOT/omega_ts/omega_avg_{tag}_bounds.json``
      - ``_OVERLAY_PNG_ROOT/omega_ts/omega_avg_overlay_bounds.json``（通用备用 bounds）

    与 overlay_registry.py 中 ``omega-output`` OverlaySpec 的 time_pattern / bounds_pattern
    严格对齐，确保运行时按 time_list 索引到的 PNG 都存在。
    """
    print("\n=== Omega inversion time series (doy 017-030) ===")
    if not _OMEGA_SMAP_AVG_DIR.exists():
        print(f"  [SKIP] Directory not found: {_OMEGA_SMAP_AVG_DIR}")
        return

    out_dir = _OUT_ROOT / "omega_ts"
    times = _doy_time_list(_OMEGA_SMAP_AVG_DIR)
    if not times:
        print("  [SKIP] No doy_*.mat files found")
        return

    print(f"  Found {len(times)} doy files: {times[0]}-{times[-1]}")
    generic_bounds: tuple[float, float, float, float] | None = None

    for tag in times:
        mat_path = _OMEGA_SMAP_AVG_DIR / f"doy_{tag}.mat"
        if not mat_path.exists():
            print(f"  [SKIP] doy_{tag}.mat not found")
            continue

        m = _read_mat_auto(mat_path)
        if "OMEGA_AVG" not in m:
            print(f"  [SKIP] doy_{tag}.mat: OMEGA_AVG not found, keys={list(m.keys())}")
            continue
        data = m["OMEGA_AVG"].astype(np.float64)
        data[data <= 0] = np.nan
        if "count_grid" in m:
            count = m["count_grid"]
            data[count == 0] = np.nan

        try:
            data, bounds = _reproject_ease_to_wgs84(
                data, target_resolution=0.1, mat_dict=m
            )
        except Exception as e:
            print(f"  [WARN] doy_{tag} reproject failed, fallback to global: {e}")
            bounds = (-180.0, -90.0, 180.0, 90.0)

        if generic_bounds is None:
            generic_bounds = bounds

        vmax = float(np.nanpercentile(data, 99))
        print(
            f"  doy_{tag}: range={np.nanmin(data):.4f}-{np.nanmax(data):.4f}, "
            f"vmax={vmax:.4f}, bounds={bounds}"
        )
        _render_png(
            data, out_dir / f"omega_avg_{tag}.png", cmap="plasma", vmin=0, vmax=vmax
        )
        _write_bounds(out_dir / f"omega_avg_{tag}_bounds.json", "omega-output", bounds)

    # 通用 bounds 备用（overlay_registry 中 bounds_filename 指向此文件）
    if generic_bounds is not None:
        _write_bounds(
            out_dir / "omega_avg_overlay_bounds.json", "omega-output", generic_bounds
        )


# ──────────────────────────────────────────────────────────────────────────────
# 6. SMAP soil moisture time series
# ──────────────────────────────────────────────────────────────────────────────


def export_smap_ts() -> None:
    print("\n=== SMAP SM time series ===")
    smap_dir = Path(
        r"I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion\stage1_smap_mat"
    )
    if not smap_dir.exists():
        print("  [SKIP] Directory not found")
        return

    out_dir = _OUT_ROOT / "smap_ts"
    files = sorted(smap_dir.glob("SMAP_L3_SM_P_*.mat"))
    print(f"  Found {len(files)} SMAP .mat files")

    # 修复：优先使用 .mat 内实际坐标，无坐标时回退到 _CHINA_BBOX
    generic_bounds = None

    for f in files:
        # Extract date tag: SMAP_L3_SM_P_20230101_R18290_001.mat -> 20230101
        # Find the 8-digit date part
        tag = None
        for part in f.stem.split("_"):
            if len(part) == 8 and part.isdigit():
                tag = part
                break
        if tag is None:
            continue

        m = _read_mat_auto(f)
        # SMAP .mat has SM, Ts, TBh, TBv, VWC, CF, lat, lon
        sm_key = None
        for k in m:
            if k.upper() == "SM" or "soil_moisture" in k.lower():
                sm_key = k
                break
        if sm_key is None:
            # Try first non-coordinate variable
            coord_keys = {
                "lat",
                "lon",
                "latitude",
                "longitude",
                "count_grid",
                "used_years",
                "ts",
                "tbh",
                "tbv",
                "vwc",
                "cf",
            }
            for k in m:
                if k.lower() not in coord_keys:
                    sm_key = k
                    break
        if sm_key is None:
            print(f"  [SKIP] {f.name}: no soil moisture variable found")
            continue

        data = m[sm_key].astype(np.float64)
        # Replace fill values with NaN
        data[data < 0] = np.nan
        data[data > 1] = np.nan

        # 从 .mat 读取实际坐标计算 bounds
        # 注意：不能用 Python `or`，因为 numpy array 多元素时无法求布尔值
        lat = m.get("lat")
        if lat is None:
            lat = m.get("latitude")
        lon = m.get("lon")
        if lon is None:
            lon = m.get("longitude")
        if lat is not None and lon is not None:
            bounds = _bounds_from_centers(lat, lon)
            if generic_bounds is None:
                generic_bounds = bounds
        else:
            bounds = _CHINA_BBOX
            if generic_bounds is None:
                generic_bounds = bounds

        print(
            f"  {tag}: {data.shape}, key={sm_key}, range={np.nanmin(data):.3f}-{np.nanmax(data):.3f}, bounds={bounds}"
        )
        _render_png(
            data, out_dir / f"smap_sm_{tag}.png", cmap="YlGnBu", vmin=0, vmax=0.5
        )
        _write_bounds(out_dir / f"smap_sm_{tag}_bounds.json", "smap-sm-ts", bounds)

    # Also write a generic bounds file
    _write_bounds(
        out_dir / "smap_sm_ts_bounds.json",
        "smap-sm-ts",
        generic_bounds if generic_bounds is not None else _CHINA_BBOX,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 7. GPCP monthly precipitation time series
# ──────────────────────────────────────────────────────────────────────────────


def export_gpcp_ts() -> None:
    print("\n=== GPCP precipitation time series ===")
    gpcp_dir = Path(r"I:\Geograph_DataSet\Weather\Precipitation\Precipitation\dataset")
    if not gpcp_dir.exists():
        print("  [SKIP] Directory not found")
        return

    out_dir = _OUT_ROOT / "gpcp_ts"
    files = sorted(gpcp_dir.glob("GPCPMON_L3_*_V3.2.nc4"))
    print(f"  Found {len(files)} GPCP files (1983-2010)")

    # Sample 24 months evenly across the full range
    total = len(files)
    sample_count = min(24, total)
    if total > sample_count:
        step = total / sample_count
        indices = [int(i * step) for i in range(sample_count)]
    else:
        indices = list(range(total))

    import xarray as xr

    for idx in indices:
        f = files[idx]
        parts = f.stem.split("_")
        if len(parts) < 3 or len(parts[2]) != 6:
            continue
        tag = parts[2]  # e.g., 198301

        ds = xr.open_dataset(str(f))
        var = "sat_gauge_precip"
        if var not in ds:
            var = list(ds.data_vars)[0]

        # Data shape: (1, lat, lon) -> squeeze time dimension
        arr = ds[var].values[0]  # (360, 720)
        # Replace fill values
        arr = np.where(arr < 0, np.nan, arr).astype(np.float64)

        # Global bounds for 0.5 degree grid
        # lat: -89.75 to 89.75, lon: -179.75 to 179.75 (center of pixels)
        # Use cell edges: -90 to 90, -180 to 180
        bounds = (-180.0, -90.0, 180.0, 90.0)

        print(f"  {tag}: {arr.shape}, range={np.nanmin(arr):.2f}-{np.nanmax(arr):.2f}")
        vmax = float(np.nanpercentile(arr, 99))
        _render_png(
            arr, out_dir / f"gpcp_{tag}.png", cmap="YlGnBu", vmin=0, vmax=max(vmax, 10)
        )
        _write_bounds(out_dir / f"gpcp_{tag}_bounds.json", "gpcp-precip-ts", bounds)

        ds.close()

    # Generic bounds
    _write_bounds(
        out_dir / "gpcp_ts_bounds.json", "gpcp-precip-ts", (-180.0, -90.0, 180.0, 90.0)
    )


# ──────────────────────────────────────────────────────────────────────────────
# 8. GEBCO 2024 DEM (NetCDF, 中国区域)
# ──────────────────────────────────────────────────────────────────────────────


def export_gebco_dem() -> None:
    print("\n=== GEBCO 2024 DEM (China) ===")
    nc_path = Path(r"I:\Geograph_DataSet\DEM\GEBCO_2024.nc")
    if not nc_path.exists():
        print("  [SKIP] File not found")
        return

    from netCDF4 import Dataset

    out_dir = _OUT_ROOT / "gebco_dem"
    bounds = _CHINA_BBOX

    with Dataset(nc_path) as ds:
        lat = ds.variables["lat"][:]
        lon = ds.variables["lon"][:]
        elev = ds.variables["elevation"]
        west, south, east, north = bounds
        lat_idx = np.where((lat >= south) & (lat <= north))[0]
        lon_idx = np.where((lon >= west) & (lon <= east))[0]
        if len(lat_idx) == 0 or len(lon_idx) == 0:
            print("  [SKIP] No data in China bbox")
            return
        # 降采样: 目标 ~2000x2000
        step = max(1, len(lat_idx) // 2000)
        lat_sl = slice(int(lat_idx[0]), int(lat_idx[-1]) + 1, step)
        lon_sl = slice(int(lon_idx[0]), int(lon_idx[-1]) + 1, step)
        data = elev[lat_sl, lon_sl].astype(np.float64)
        # NetCDF lat 是升序（南→北），_render_png 使用 origin="upper"（顶部=北）
        # 需要翻转为北→南，使图像第一行对应北方
        if lat[0] < lat[-1]:
            data = data[::-1, :]
        # 实际 bounds 用采样后的坐标（修复：补半像素边界，避免整体偏移）
        lat_s = lat[lat_sl]
        lon_s = lon[lon_sl]
        actual_bounds = _bounds_from_centers(lat_s, lon_s)

    print(
        f"  Data shape: {data.shape}, range: {np.nanmin(data):.1f} to {np.nanmax(data):.1f}"
    )
    _render_png(
        data, out_dir / "gebco_dem_overlay.png", cmap="terrain", vmin=-2000, vmax=6000
    )
    _write_bounds(
        out_dir / "gebco_dem_overlay_bounds.json", "gebco-dem-cn", actual_bounds
    )


# ──────────────────────────────────────────────────────────────────────────────
# 9. CMFD Precipitation (GeoTIFF, 中国区域)
# ──────────────────────────────────────────────────────────────────────────────


def export_cmfd_precip() -> None:
    print("\n=== CMFD Precipitation (China 1km) ===")
    tif_path = Path(r"I:\Geograph_DataSet\Precipitation\pre_2002_01.tif")
    if not tif_path.exists():
        print("  [SKIP] File not found")
        return

    import rasterio
    from rasterio.enums import Resampling

    out_dir = _OUT_ROOT / "cmfd_precip"
    bounds = _CHINA_BBOX

    with rasterio.open(tif_path) as src:
        # 降采样到 ~2000x2000
        scale = max(1, max(src.width, src.height) // 2000)
        data = src.read(
            1,
            out_shape=(src.height // scale, src.width // scale),
            resampling=Resampling.average,
        ).astype(np.float64)
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = np.nan
        # int16, 单位 0.1mm, 转为 mm
        data = data / 10.0
        west, south, east, north = src.bounds

    print(
        f"  Data shape: {data.shape}, range: {np.nanmin(data):.1f} to {np.nanmax(data):.1f} mm"
    )
    vmax = float(np.nanpercentile(data, 99))
    _render_png(
        data,
        out_dir / "cmfd_precip_overlay.png",
        cmap="YlGnBu",
        vmin=0,
        vmax=max(vmax, 10),
    )
    _write_bounds(
        out_dir / "cmfd_precip_overlay_bounds.json",
        "cmfd-precip-cn",
        (float(west), float(south), float(east), float(north)),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 10. CLCD 1997 (GeoTIFF, 中国区域, 降采样)
# ──────────────────────────────────────────────────────────────────────────────


def export_clcd() -> None:
    print("\n=== CLCD 1997 (China) ===")
    tif_path = Path(r"I:\Geograph_DataSet\LandCover\CLCD_v01_1997.tif")
    if not tif_path.exists():
        print("  [SKIP] File not found")
        return

    import rasterio
    from rasterio.windows import from_bounds, Window
    from rasterio.enums import Resampling

    out_dir = _OUT_ROOT / "clcd"
    bounds = _CHINA_BBOX

    with rasterio.open(tif_path) as src:
        win = from_bounds(*bounds, src.transform)
        full_win = Window(0, 0, src.width, src.height)
        win = win.intersection(full_win).round_offsets().round_lengths()
        # 降采样到 ~2000x2000
        scale = max(1, max(win.width, win.height) // 2000)
        data = src.read(
            1,
            window=win,
            out_shape=(win.height // scale, win.width // scale),
            resampling=Resampling.mode,
        ).astype(np.float64)
        # CLCD: 0=填充, 1-9 分类
        data[data == 0] = np.nan
        # 使用 window_bounds 获取窗口的地理边界 (west, south, east, north)
        # 注意: 不能用 xy(offset="ll")/xy(offset="ur"), 那样会取像素内边沿导致整体偏移 1 个像素
        actual_bounds = tuple(float(v) for v in src.window_bounds(win))

    print(
        f"  Data shape: {data.shape}, classes: {np.nanmin(data):.0f} to {np.nanmax(data):.0f}"
    )
    _render_png(data, out_dir / "clcd_overlay.png", cmap="tab10", vmin=1, vmax=9)
    _write_bounds(out_dir / "clcd_overlay_bounds.json", "clcd-cn", actual_bounds)


# ──────────────────────────────────────────────────────────────────────────────
# 11. ESACCI BIOMASS 2020 (NetCDF, 中国区域, 降采样)
# ──────────────────────────────────────────────────────────────────────────────


def export_biomass() -> None:
    print("\n=== ESACCI BIOMASS 2020 (China) ===")
    nc_path = Path(
        r"I:\Geograph_DataSet\Biomass\ESACCI-BIOMASS-L4-AGB-MERGED-100m-2020-fv6.0.nc"
    )
    if not nc_path.exists():
        print("  [SKIP] File not found")
        return

    from netCDF4 import Dataset

    out_dir = _OUT_ROOT / "biomass"
    bounds = _CHINA_BBOX

    with Dataset(nc_path) as ds:
        lat = ds.variables["lat"][:]
        lon = ds.variables["lon"][:]
        agb = ds.variables["agb"]
        fill_value = getattr(agb, "_FillValue", -32768)
        west, south, east, north = bounds
        lat_idx = np.where((lat >= south) & (lat <= north))[0]
        lon_idx = np.where((lon >= west) & (lon <= east))[0]
        if len(lat_idx) == 0 or len(lon_idx) == 0:
            print("  [SKIP] No data in China bbox")
            return
        # 降采样: 目标 ~2000x2000, 分块读取
        lat_step = max(1, len(lat_idx) // 2000)
        lon_step = max(1, len(lon_idx) // 2000)
        lat_sl = slice(int(lat_idx[0]), int(lat_idx[-1]) + 1, lat_step)
        lon_sl = slice(int(lon_idx[0]), int(lon_idx[-1]) + 1, lon_step)
        # 分块读取避免内存爆炸
        data = None
        chunk_rows = 5000
        for r_start in range(int(lat_idx[0]), int(lat_idx[-1]) + 1, chunk_rows):
            r_end = min(r_start + chunk_rows, int(lat_idx[-1]) + 1)
            chunk = agb[0, r_start:r_end:lat_step, lon_sl]
            if data is None:
                data = chunk.astype(np.float64)
            else:
                data = np.vstack([data, chunk.astype(np.float64)])
        data[data == fill_value] = np.nan
        # NetCDF lat 升序时翻转（同 GEBCO 修复）
        if lat[0] < lat[-1]:
            data = data[::-1, :]
        lat_s = lat[lat_sl]
        lon_s = lon[lon_sl]
        # 修复：补半像素边界，避免整体偏移
        actual_bounds = _bounds_from_centers(lat_s, lon_s)

    print(
        f"  Data shape: {data.shape}, range: {np.nanmin(data):.1f} to {np.nanmax(data):.1f} Mg/ha"
    )
    vmax = float(np.nanpercentile(data, 98))
    _render_png(
        data, out_dir / "biomass_overlay.png", cmap="YlGn", vmin=0, vmax=max(vmax, 50)
    )
    _write_bounds(out_dir / "biomass_overlay_bounds.json", "biomass-cn", actual_bounds)


# ──────────────────────────────────────────────────────────────────────────────
# 12. ERA5 DWAA/WDAA SMCI 2020 (GeoTIFF, 多波段事件标识, band 100)
# ──────────────────────────────────────────────────────────────────────────────


def export_era5_dwaa() -> None:
    print("\n=== ERA5 DWAA SMCI 2020 (event flag) ===")
    tif_path = Path(
        r"I:\Geograph_DataSet\Hazards\DWAA_result\DW_T7\ERA5_2020_DW_SMCI.tif"
    )
    if not tif_path.exists():
        print("  [SKIP] File not found")
        return

    import rasterio
    from rasterio.windows import from_bounds

    out_dir = _OUT_ROOT / "era5_dwaa"
    bounds = _CHINA_BBOX

    with rasterio.open(tif_path) as src:
        win = from_bounds(*bounds, src.transform).round_offsets().round_lengths()
        # 读 band 100 (年中), 合并多个波段的事件标识
        # 累加 band 1-366 中值为 1 的次数
        event_count = np.zeros((win.height, win.width), dtype=np.float64)
        for band in range(1, src.count + 1):
            data = src.read(band, window=win)
            event_count[data == 1] += 1
        event_count[event_count == 0] = np.nan
        # 使用 window_bounds 获取窗口的地理边界 (west, south, east, north)
        # 注意: 不能用 xy(offset="ll")/xy(offset="ur"), 那样会取像素内边沿导致整体偏移 1 个像素
        actual_bounds = tuple(float(v) for v in src.window_bounds(win))

    print(
        f"  Event count shape: {event_count.shape}, max events: {np.nanmax(event_count):.0f}"
    )
    vmax = float(np.nanmax(event_count)) if np.isfinite(np.nanmax(event_count)) else 10
    _render_png(
        event_count,
        out_dir / "era5_dwaa_overlay.png",
        cmap="YlOrRd",
        vmin=1,
        vmax=max(vmax, 5),
    )
    _write_bounds(
        out_dir / "era5_dwaa_overlay_bounds.json", "era5-dwaa-cn", actual_bounds
    )


def export_era5_wdaa() -> None:
    print("\n=== ERA5 WDAA SMCI 2020 (event flag) ===")
    tif_path = Path(
        r"I:\Geograph_DataSet\Hazards\DWAA_result\WD_T7\ERA5_2020_WD_SMCI.tif"
    )
    if not tif_path.exists():
        print("  [SKIP] File not found")
        return

    import rasterio
    from rasterio.windows import from_bounds

    out_dir = _OUT_ROOT / "era5_wdaa"
    bounds = _CHINA_BBOX

    with rasterio.open(tif_path) as src:
        win = from_bounds(*bounds, src.transform).round_offsets().round_lengths()
        event_count = np.zeros((win.height, win.width), dtype=np.float64)
        for band in range(1, src.count + 1):
            data = src.read(band, window=win)
            event_count[data == 1] += 1
        event_count[event_count == 0] = np.nan
        # 使用 window_bounds 获取窗口的地理边界 (west, south, east, north)
        # 注意: 不能用 xy(offset="ll")/xy(offset="ur"), 那样会取像素内边沿导致整体偏移 1 个像素
        actual_bounds = tuple(float(v) for v in src.window_bounds(win))

    print(
        f"  Event count shape: {event_count.shape}, max events: {np.nanmax(event_count):.0f}"
    )
    vmax = float(np.nanmax(event_count)) if np.isfinite(np.nanmax(event_count)) else 10
    _render_png(
        event_count,
        out_dir / "era5_wdaa_overlay.png",
        cmap="YlGnBu",
        vmin=1,
        vmax=max(vmax, 5),
    )
    _write_bounds(
        out_dir / "era5_wdaa_overlay_bounds.json", "era5-wdaa-cn", actual_bounds
    )


# ──────────────────────────────────────────────────────────────────────────────
# 13. MeanCarbonDioxide (GeoTIFF, 中国区域)
# ──────────────────────────────────────────────────────────────────────────────


def export_co2() -> None:
    print("\n=== MeanCarbonDioxide (China) ===")
    tif_path = Path(
        r"I:\Geograph_DataSet\CO2\MidLayerCO2Column\TIF\MeanCarbonDioxide.tif"
    )
    if not tif_path.exists():
        print("  [SKIP] File not found")
        return

    import rasterio

    out_dir = _OUT_ROOT / "co2"
    bounds = _CHINA_BBOX

    with rasterio.open(tif_path) as src:
        data = src.read(1).astype(np.float64)
        west, south, east, north = src.bounds

    print(
        f"  Data shape: {data.shape}, range: {np.nanmin(data):.2f} to {np.nanmax(data):.2f} ppm"
    )
    _render_png(data, out_dir / "co2_overlay.png", cmap="RdYlGn_r", vmin=386, vmax=391)
    _write_bounds(
        out_dir / "co2_overlay_bounds.json",
        "co2-cn",
        (float(west), float(south), float(east), float(north)),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 14. Soil DDCA 时间序列（中国 9km，2015-04 ~ 2022-12，采样 60 天）
# ──────────────────────────────────────────────────────────────────────────────


def export_soil_ddca_ts() -> None:
    """导出 soil-ddca 时间序列：每个采样日期一个 PNG + bounds JSON。

    输出文件：
      - ``_OVERLAY_PNG_ROOT/soil_ddca_ts/soil_ddca_{tag}.png``（tag = '20150401', ...）
      - ``_OVERLAY_PNG_ROOT/soil_ddca_ts/soil_ddca_{tag}_bounds.json``
      - ``_OVERLAY_PNG_ROOT/soil_ddca_ts/soil_ddca_overlay_bounds.json``（通用备用 bounds）

    采样逻辑与 overlay_registry.py 中 ``_soil_ddca_time_list(limit=60)`` 完全一致：
    从 2747 个日文件中均匀采样 60 个时间点，避免时间轴过长。
    """
    print("\n=== Soil DDCA time series (2015-04 ~ 2022-12, sampled 60) ===")
    if not _SOIL_DDCA_H_DIR.exists():
        print(f"  [SKIP] Directory not found: {_SOIL_DDCA_H_DIR}")
        return

    out_dir = _OUT_ROOT / "soil_ddca_ts"
    times = _soil_ddca_time_list(limit=60)
    if not times:
        print("  [SKIP] No YYYYMMDD.mat files found")
        return

    print(f"  Found {len(times)} sampled dates: {times[0]}-{times[-1]}")
    generic_bounds: tuple[float, float, float, float] | None = None

    for tag in times:
        mat_path = _SOIL_DDCA_H_DIR / f"{tag}.mat"
        if not mat_path.exists():
            print(f"  [SKIP] {tag}.mat not found")
            continue

        m = _read_mat_auto(mat_path)
        if "DH" not in m:
            print(f"  [SKIP] {tag}.mat: DH not found, keys={list(m.keys())}")
            continue
        data = m["DH"].astype(np.float64)
        data[data < 0] = np.nan

        try:
            data, bounds = _reproject_ease_to_wgs84(
                data, target_resolution=0.1, mat_dict=m
            )
        except Exception as e:
            print(f"  [WARN] {tag} reproject failed, fallback to global: {e}")
            bounds = (-180.0, -90.0, 180.0, 90.0)

        if generic_bounds is None:
            generic_bounds = bounds

        vmax = float(np.nanpercentile(data, 99))
        print(
            f"  {tag}: range={np.nanmin(data):.2f}-{np.nanmax(data):.2f}, "
            f"vmax={vmax:.2f}, bounds={bounds}"
        )
        _render_png(
            data,
            out_dir / f"soil_ddca_{tag}.png",
            cmap="viridis",
            vmin=0,
            vmax=max(vmax, 1),
        )
        _write_bounds(out_dir / f"soil_ddca_{tag}_bounds.json", "soil-ddca", bounds)

    if generic_bounds is not None:
        _write_bounds(
            out_dir / "soil_ddca_overlay_bounds.json", "soil-ddca", generic_bounds
        )


# ──────────────────────────────────────────────────────────────────────────────
# 15. Omega FY avg 时间序列（doy 025-030，6 天）
# ──────────────────────────────────────────────────────────────────────────────


def export_omega_fy_ts() -> None:
    """导出 omega-fy-output 时间序列：每个 doy 一个 PNG + bounds JSON。

    输出文件：
      - ``_OVERLAY_PNG_ROOT/omega_fy_ts/omega_fy_{tag}.png``（tag = '025', '026', ...）
      - ``_OVERLAY_PNG_ROOT/omega_fy_ts/omega_fy_{tag}_bounds.json``
      - ``_OVERLAY_PNG_ROOT/omega_fy_ts/omega_fy_overlay_bounds.json``（通用备用 bounds）
    """
    print("\n=== Omega FY avg time series (doy 025-030) ===")
    if not _OMEGA_FY_AVG_DIR.exists():
        print(f"  [SKIP] Directory not found: {_OMEGA_FY_AVG_DIR}")
        return

    out_dir = _OUT_ROOT / "omega_fy_ts"
    times = _doy_time_list(_OMEGA_FY_AVG_DIR)
    if not times:
        print("  [SKIP] No doy_*.mat files found")
        return

    print(f"  Found {len(times)} doy files: {times[0]}-{times[-1]}")
    generic_bounds: tuple[float, float, float, float] | None = None

    for tag in times:
        mat_path = _OMEGA_FY_AVG_DIR / f"doy_{tag}.mat"
        if not mat_path.exists():
            print(f"  [SKIP] doy_{tag}.mat not found")
            continue

        m = _read_mat_auto(mat_path)
        if "OMEGA_AVG" not in m:
            print(f"  [SKIP] doy_{tag}.mat: OMEGA_AVG not found, keys={list(m.keys())}")
            continue
        data = m["OMEGA_AVG"].astype(np.float64)
        data[data <= 0] = np.nan
        if "count_grid" in m:
            count = m["count_grid"]
            data[count == 0] = np.nan

        try:
            data, bounds = _reproject_ease_to_wgs84(
                data, target_resolution=0.1, mat_dict=m
            )
        except Exception as e:
            print(f"  [WARN] doy_{tag} reproject failed, fallback to global: {e}")
            bounds = (-180.0, -90.0, 180.0, 90.0)

        if generic_bounds is None:
            generic_bounds = bounds

        vmax = float(np.nanpercentile(data, 99))
        print(
            f"  doy_{tag}: range={np.nanmin(data):.4f}-{np.nanmax(data):.4f}, "
            f"vmax={vmax:.4f}, bounds={bounds}"
        )
        _render_png(
            data, out_dir / f"omega_fy_{tag}.png", cmap="magma", vmin=0, vmax=vmax
        )
        _write_bounds(
            out_dir / f"omega_fy_{tag}_bounds.json", "omega-fy-output", bounds
        )

    if generic_bounds is not None:
        _write_bounds(
            out_dir / "omega_fy_overlay_bounds.json", "omega-fy-output", generic_bounds
        )


# ──────────────────────────────────────────────────────────────────────────────
# 16. Forest_Ratio 9KM 2020 (MAT, 全球 9km)
# ──────────────────────────────────────────────────────────────────────────────


def export_forest_ratio() -> None:
    print("\n=== Forest Ratio 9KM 2020 ===")
    mat_path = Path(r"I:\Geograph_DataSet\InversionResults\Forest_Ratio_9KM_2020.mat")
    if not mat_path.exists():
        print("  [SKIP] File not found")
        return

    out_dir = _OUT_ROOT / "forest_ratio"

    m = _read_mat_auto(mat_path)
    if "Forest_Ratio" not in m:
        print("  [SKIP] Variable Forest_Ratio not found")
        return
    data = m["Forest_Ratio"].astype(np.float64)
    data[data < 0] = np.nan

    print(
        f"  Data shape: {data.shape}, range: {np.nanmin(data):.3f} to {np.nanmax(data):.3f}"
    )
    # 修复：EASE-Grid 2.0 9km 重投影到 WGS84 + 裁剪到中国区域（避免全球 Mercator 拉伸）
    try:
        data, bounds = _reproject_ease_to_wgs84(data, target_resolution=0.1, mat_dict=m)
        print(f"  forest_ratio reprojected: {data.shape}, bounds={bounds}")
    except Exception as e:
        print(
            f"  [WARN] EASE-Grid reproject failed, falling back to global bounds: {e}"
        )
        bounds = (-180.0, -90.0, 180.0, 90.0)
    _render_png(data, out_dir / "forest_ratio_overlay.png", cmap="YlGn", vmin=0, vmax=1)
    _write_bounds(out_dir / "forest_ratio_overlay_bounds.json", "forest-ratio", bounds)


# ──────────────────────────────────────────────────────────────────────────────
# 17. Landscape Metrics 9km 2020 — SHDI（Phase 1.6 新增）
# ──────────────────────────────────────────────────────────────────────────────


def export_landscape_metrics() -> None:
    """导出 landscape-metrics-9km 静态图层：Shannon 多样性指数 SHDI。

    输出文件：
      - ``_OVERLAY_PNG_ROOT/landscape_metrics/landscape_metrics_overlay.png``
      - ``_OVERLAY_PNG_ROOT/landscape_metrics/landscape_metrics_overlay_bounds.json``

    数据源 ``Landscape_Metrics_LandOnly_9KM_2020.mat`` 含 4 个景观指数
    (PD/ED/SHDI/CONTAG) + Forest_Ratio + 元数据 (Transform/CRS/Resolution_meters)。
    Phase 1 仅暴露 SHDI；其余 3 个可后续通过相似方式扩展（修改 source_variable 即可）。
    """
    print("\n=== Landscape Metrics 9km 2020 (SHDI) ===")
    if not _LANDSCAPE_METRICS_MAT.exists():
        print(f"  [SKIP] File not found: {_LANDSCAPE_METRICS_MAT}")
        return

    out_dir = _OUT_ROOT / "landscape_metrics"

    m = _read_mat_auto(_LANDSCAPE_METRICS_MAT)
    if "SHDI" not in m:
        print(f"  [SKIP] Variable SHDI not found, keys={list(m.keys())}")
        return
    data = m["SHDI"].astype(np.float64)
    # SHDI 理论范围 [0, ~2.22]；负值或 NaN 视为无效
    data[data < 0] = np.nan

    print(
        f"  Data shape: {data.shape}, range: {np.nanmin(data):.4f} to {np.nanmax(data):.4f}"
    )
    # EASE-Grid 2.0 9km 重投影到 WGS84 + 裁剪到中国区域
    # .mat 含 Transform (500m 网格，需 × 18 = 9008.0552m) + CRS (EPSG:6933)
    try:
        data, bounds = _reproject_ease_to_wgs84(data, target_resolution=0.1, mat_dict=m)
        print(f"  landscape_metrics reprojected: {data.shape}, bounds={bounds}")
    except Exception as e:
        print(
            f"  [WARN] EASE-Grid reproject failed, falling back to global bounds: {e}"
        )
        bounds = (-180.0, -90.0, 180.0, 90.0)
    # SHDI 取 99 分位作为 vmax，避免极端值压缩色彩
    vmax = float(np.nanpercentile(data, 99))
    _render_png(
        data,
        out_dir / "landscape_metrics_overlay.png",
        cmap="cividis",
        vmin=0,
        vmax=max(vmax, 1.0),
    )
    _write_bounds(
        out_dir / "landscape_metrics_overlay_bounds.json",
        "landscape-metrics-9km",
        bounds,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 18-20. Phase 2: VOD / SM / Omega 2025-12 时间序列（SmapSoil_VOD_SM 产品族）
# ──────────────────────────────────────────────────────────────────────────────


def _export_smap_soil_vod_sm_ts(
    varname: str,
    layer_id: str,
    out_subdir: str,
    cmap: str,
    vmin: float,
    vmax: float | None,
    unit: str,
    label: str,
) -> None:
    """通用导出器：从 SmapSoil_VOD_SM/YYYYMMDD.mat 读取指定变量并导出时间序列。

    Phase 2 共用逻辑，供 VOD / SM / OMEGA 三个变量复用。每个变量导出 31 天
    （2025-12-01 ~ 2025-12-31）的 PNG + bounds JSON + 通用 bounds。

    数据源 .mat 为 v7.3 HDF5 格式，shape (3856, 1624) → h5py 读取后转置为
    (1624, 3856)，与 EASE-Grid 9km 标准一致。文件无 Transform/CRS 元数据，
    使用默认 EASE-Grid 9km transform 重投影到 WGS84 + 裁剪到中国区域。

    Args:
        varname: .mat 中的变量名（'VOD' / 'SM' / 'OMEGA'）
        layer_id: 图层 ID（'vod-dec2025' / 'sm-dec2025' / 'omega-dec2025'）
        out_subdir: 输出子目录名（'vod_ts' / 'sm_ts' / 'omega_2025_ts'）
        cmap: matplotlib colormap 名称
        vmin: 色彩映射下界
        vmax: 色彩映射上界；None 表示用 99 分位
        unit: 变量单位（用于元数据）
        label: 人类可读标签（用于日志）
    """
    print(f"\n=== {label} time series (2025-12, SmapSoil_VOD_SM/{varname}) ===")
    if not _SMAP_SOIL_VOD_SM_DIR.exists():
        print(f"  [SKIP] Directory not found: {_SMAP_SOIL_VOD_SM_DIR}")
        return

    out_dir = _OUT_ROOT / out_subdir
    times = _date8_time_list(_SMAP_SOIL_VOD_SM_DIR, limit=None)
    if not times:
        print("  [SKIP] No YYYYMMDD.mat files found")
        return

    print(f"  Found {len(times)} daily files: {times[0]}-{times[-1]}")
    generic_bounds: tuple[float, float, float, float] | None = None

    for tag in times:
        mat_path = _SMAP_SOIL_VOD_SM_DIR / f"{tag}.mat"
        if not mat_path.exists():
            print(f"  [SKIP] {tag}.mat not found")
            continue

        m = _read_mat_auto(mat_path)
        if varname not in m:
            print(f"  [SKIP] {tag}.mat: {varname} not found, keys={list(m.keys())}")
            continue
        data = m[varname].astype(np.float64)
        # VOD/SM/OMEGA 负值视为无效（物理上无意义）
        data[data < 0] = np.nan

        try:
            data, bounds = _reproject_ease_to_wgs84(
                data, target_resolution=0.1, mat_dict=m
            )
        except Exception as e:
            print(f"  [WARN] {tag} reproject failed, fallback to global: {e}")
            bounds = (-180.0, -90.0, 180.0, 90.0)

        if generic_bounds is None:
            generic_bounds = bounds

        # vmax 自适应（若未指定）
        eff_vmax = vmax
        if eff_vmax is None:
            eff_vmax = float(np.nanpercentile(data, 99))
        print(
            f"  {tag}: range={np.nanmin(data):.4f}-{np.nanmax(data):.4f}, "
            f"vmax={eff_vmax:.4f}, bounds={bounds}"
        )
        _render_png(
            data,
            out_dir / f"{out_subdir}_{tag}.png",
            cmap=cmap,
            vmin=vmin,
            vmax=eff_vmax,
        )
        _write_bounds(out_dir / f"{out_subdir}_{tag}_bounds.json", layer_id, bounds)

    if generic_bounds is not None:
        _write_bounds(
            out_dir / f"{out_subdir}_overlay_bounds.json", layer_id, generic_bounds
        )


def export_vod_ts() -> None:
    """导出 vod-dec2025 时间序列：植被光学厚度 VOD（2025-12，31 天）。

    输出文件：
      - ``_OVERLAY_PNG_ROOT/vod_ts/vod_ts_{tag}.png``（tag = '20251201', ...）
      - ``_OVERLAY_PNG_ROOT/vod_ts/vod_ts_{tag}_bounds.json``
      - ``_OVERLAY_PNG_ROOT/vod_ts/vod_ts_overlay_bounds.json``（通用 bounds）
    """
    _export_smap_soil_vod_sm_ts(
        varname="VOD",
        layer_id="vod-dec2025",
        out_subdir="vod_ts",
        cmap="magma",
        vmin=0,
        vmax=None,
        unit="",
        label="VOD",
    )


def export_sm_dec2025_ts() -> None:
    """导出 sm-dec2025 时间序列：土壤湿度 SM（2025-12，31 天）。

    输出文件：
      - ``_OVERLAY_PNG_ROOT/sm_ts/sm_ts_{tag}.png``（tag = '20251201', ...）
      - ``_OVERLAY_PNG_ROOT/sm_ts/sm_ts_{tag}_bounds.json``
      - ``_OVERLAY_PNG_ROOT/sm_ts/sm_ts_overlay_bounds.json``（通用 bounds）
    """
    _export_smap_soil_vod_sm_ts(
        varname="SM",
        layer_id="sm-dec2025",
        out_subdir="sm_ts",
        cmap="YlGnBu",
        vmin=0,
        vmax=0.6,
        unit="m³/m³",
        label="Soil Moisture",
    )


def export_omega_2025_ts() -> None:
    """导出 omega-dec2025 时间序列：Omega 植被光学厚度（2025-12，31 天）。

    与现有 ``omega-output`` (doy 017-030 多年均值) 互补，提供 2025 年 12 月
    每日的 Omega 反演结果，可用于季节性对比与近期监测。

    输出文件：
      - ``_OVERLAY_PNG_ROOT/omega_2025_ts/omega_2025_ts_{tag}.png``
      - ``_OVERLAY_PNG_ROOT/omega_2025_ts/omega_2025_ts_{tag}_bounds.json``
      - ``_OVERLAY_PNG_ROOT/omega_2025_ts/omega_2025_ts_overlay_bounds.json``
    """
    _export_smap_soil_vod_sm_ts(
        varname="OMEGA",
        layer_id="omega-dec2025",
        out_subdir="omega_2025_ts",
        cmap="plasma",
        vmin=0,
        vmax=None,
        unit="Omega",
        label="Omega 2025-12",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 60)
    print("Overlay Assets Export Tool")
    print("=" * 60)

    _OUT_ROOT.mkdir(parents=True, exist_ok=True)

    tasks = [
        ("DEM ETOPO", export_dem_etopo),
        ("Thematic", export_thematic_layers),
        ("Omega TS", export_omega_ts),
        ("SMAP TS", export_smap_ts),
        ("GPCP TS", export_gpcp_ts),
        ("GEBCO DEM", export_gebco_dem),
        ("CMFD Precip", export_cmfd_precip),
        ("CLCD", export_clcd),
        ("BIOMASS", export_biomass),
        ("ERA5 DWAA", export_era5_dwaa),
        ("ERA5 WDAA", export_era5_wdaa),
        ("CO2", export_co2),
        ("Soil DDCA TS", export_soil_ddca_ts),
        ("Omega FY TS", export_omega_fy_ts),
        ("Forest Ratio", export_forest_ratio),
        ("Landscape Metrics", export_landscape_metrics),
        # ── Phase 2: 课题组 VOD/SM/Omega 2025-12 产品族 ──
        ("VOD TS", export_vod_ts),
        ("SM Dec2025 TS", export_sm_dec2025_ts),
        ("Omega 2025 TS", export_omega_2025_ts),
    ]

    results = {}
    for name, func in tasks:
        try:
            func()
            results[name] = "OK"
        except Exception as e:
            print(f"\n  [FAIL] {name}: {e}")
            import traceback

            traceback.print_exc()
            results[name] = f"FAIL: {e}"

    print("\n" + "=" * 60)
    print("Summary:")
    for name, status in results.items():
        marker = "[OK]" if status == "OK" else "[FAIL]"
        print(f"  {marker} {name}: {status}")
    print("=" * 60)
    return 0 if all(v == "OK" for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
