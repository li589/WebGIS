#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量导出叠加图层预览资产（PNG + bounds JSON）。

为后端 overlay_registry.py 中注册的每个图层生成地理配准 PNG 预览图。
输出目录: I:\\Geograph_DataSet\\ProjectOutput\\2023-01_Omega_Inversion\\_overlays\\

地理配准约定（2026-08 重构）：
  - 所有 PNG 输出到 **Web Mercator 线性网格**（行/列在 EPSG:3857 平面均匀）。
    MapLibre ImageSource 以 4 角坐标在 Mercator 平面双线性插值渲染，等经纬
    图像在中高纬会偏移十几度、±90° 角点无法表示（GPCP 不可显示的根因）。
  - 全球层 bounds 为 (-180, -85.0511, 180, 85.0511)；中国层为中国窗口。
  - 全球产品（smap-aux 9 层、forest-ratio、landscape-metrics、dem-etopo、
    gpcp）默认输出全球全幅，不再硬裁剪到中国。

CLI：
  python Tools/export_overlay_assets.py                        # 全量
  python Tools/export_overlay_assets.py --tasks smap-aux,forest-ratio,landscape-metrics
  python Tools/export_overlay_assets.py --tasks gpcp-rewarp    # 修既有 GPCP 资产
  python Tools/export_overlay_assets.py --extent global        # 强制全球（诊断）
  python Tools/export_overlay_assets.py --dry-run              # 只打印计划

支持的图层（节选；完整清单见 _build_task_table）：
  1. dem-etopo           — ETOPO_2022 bed topography (global, terrain)
  5. omega-output [TS]   — Omega inversion avg 时间序列 (doy 017-030, 14 天, plasma)
  7. gpcp-precip-ts [TS] — GPCP monthly precipitation 时间序列 (global, 24 months)
  17. forest-ratio        — Forest Ratio 9KM 2020 (global EASE-Grid 9km, YlGn)
  18. landscape-metrics-9km — Shannon 多样性指数 SHDI (global EASE-Grid 9km, cividis)
  22. smap-aux-* (9 层)   — SMAP 辅助数据静态层 (albedo/bd/sf/b/cf/h/igbp/koppen/vi-qa)

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
from data_root import resolve_data_root

# Output root
_OUT_ROOT = resolve_data_root() / "ProjectOutput" / "2023-01_Omega_Inversion" / "_overlays"

# 资产烘焙版本：改动渲染几何/行序等影响已有 PNG 正确性的逻辑时递增，
# 后端 asset_bake_tasks 据此自动重烘陈旧资产。版本史：
#   1 = 初版（thematic 族存在行序上下翻转 bug）
#   2 = 行序修复（2026-08-24，imshow origin 校准 + thematic 重烘）
#   3 = 中国区域静态层（thematic/ERA5）后端 Mercator 线性重投影，
#       不再依赖浏览器条带补偿（2026-08-24 真实地图偏移复现修复）
#   4 = GPCP 低值透明 + Blues 对比度修复（2026-08-24 真实白屏复现）
BAKE_VERSION = 4
_CHINA_BBOX = (73.0, 15.0, 137.0, 59.0)

# extent 模式：auto = 按任务表声明；global/china = CLI 强制覆盖（诊断用）
_EXTENT_MODE = "auto"


def _resolve_extent(declared: str) -> str:
    """返回生效 extent（"global" | "china"）：CLI --extent 非 auto 时覆盖任务声明。"""
    return _EXTENT_MODE if _EXTENT_MODE != "auto" else declared


def _extent_clip(extent: str):
    """extent → 重投影裁剪窗口；global 返回 None（全球全幅）。"""
    return None if extent == "global" else _CHINA_BBOX


def _extent_res_deg(extent: str, china_deg: float = 0.1, global_deg: float = 0.25) -> float:
    """extent → 输出分辨率（度）：全球层用较粗分辨率控制 PNG 尺寸。"""
    return global_deg if extent == "global" else china_deg

# ── Phase 1.6: 课题组时间序列源数据目录（与 overlay_registry.py 同步）──────────
_INVERSION_RESULTS_ROOT = resolve_data_root() / "Inversion_Results"
_OMEGA_SMAP_AVG_DIR = _INVERSION_RESULTS_ROOT / "smap_avg"
_OMEGA_FY_AVG_DIR = _INVERSION_RESULTS_ROOT / "fy_avg"
_SOIL_DDCA_H_DIR = resolve_data_root() / "Soil_Moisture" / "DDCA" / "DDCA_DH" / "H"
_LANDSCAPE_METRICS_MAT = (
    _INVERSION_RESULTS_ROOT / "Landscape_Metrics_LandOnly_9KM_2020.mat"
)

# ── Phase 2: 课题组 VOD/SM 产品族（2025-12 时间序列，EASE-Grid 9km）──────────
# SmapSoil_VOD_SM/YYYYMMDD.mat (v7.3 HDF5) 含 OMEGA / SM / VOD 三个变量，shape (1624, 3856)
_SMAP_SOIL_VOD_SM_DIR = Path(
    r"I:\Geograph_DataSet\Soil_Moisture\SMAP_Soil_VOD_SM"
)


def _doy_time_list(directory: Path, prefix: str = "doy_") -> list[str]:
    """从 Inversion_Results/smap_avg|fy_avg 目录推断 doy 时间序列标签。

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
    """从 Soil_Moisture/DDCA/DDCA_DH/H 目录推断日期时间序列标签。

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
        # 资产烘焙版本（自愈机制用）：app/tasks/asset_bake_tasks.py 启动/定期
        # 校验 bake_version < BAKE_VERSION 的资产并自动重烘（2026-08-24：
        # 旧版行序翻转 PNG 曾靠手工重烘修复——资产新鲜度不再依赖外部操作）。
        # 版本史：1=初版（存在行序翻转 bug）；2=行序修复（imshow origin 校准）
        "bake_version": BAKE_VERSION,
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


# ── EASE / Mercator 共享几何与重投影（2026-08-24 P2 收敛）───────────────────
# 唯一真源：Code/backend/app/data_io/services/{grid_presets,grid_reproject}.py。
# 通过 importlib 按文件路径直接加载（不触发 app 包初始化链），Tools 可独立
# 运行；本地不再保留任何 EASE 常数 / 重投影副本。
# 注意：500m 网格的像素尺寸 = 500.4475m；9km 标称 = 18 × 500.4475 = 9008.0552m
# （早期硬编码 9000.879 是错误的，差 7.18m/像素，1624 行累计偏差 11.6km）。
import importlib.util as _ilu


def _load_shared_module(name: str):
    """按文件路径加载后端共享纯依赖模块（grid_presets / grid_reproject）。"""
    mod_path = (
        Path(__file__).resolve().parents[1]
        / "Code"
        / "backend"
        / "app"
        / "data_io"
        / "services"
        / f"{name}.py"
    )
    if not mod_path.is_file():
        raise RuntimeError(f"shared module not found: {mod_path}")
    spec = _ilu.spec_from_file_location(f"_cgda_shared_{name}", mod_path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_grid_presets = _load_shared_module("grid_presets")
_grid_reproject = _load_shared_module("grid_reproject")

EASE_UL_BY_CRS = _grid_presets.EASE_UL_BY_CRS
GRID_PRESETS = _grid_presets.GRID_PRESETS
ease_grid_transform = _grid_presets.ease_grid_transform
ease_grid_from_shape = _grid_presets.ease_grid_from_shape

_EASE_GRID_9K_CRS = "EPSG:6933"
_EASE_GRID_9K_PIXEL_SIZE = float(
    GRID_PRESETS["ease2-global-9km"]["resolution"]
)  # 米（= 18 × 500.4475，NSIDC 标准）

# Mercator 常数与重投影实现（与后端 overlay 链共享同一份）
_MERCATOR_MAX_LAT = _grid_reproject.MERCATOR_MAX_LAT
_MERCATOR_MAX_Y = _grid_reproject.MERCATOR_MAX_Y
_METERS_PER_DEGREE_EQUATOR = _grid_reproject.METERS_PER_DEGREE_EQUATOR
_reproject_to_mercator_linear = _grid_reproject.reproject_to_mercator_linear


def _ease_grid_transform(
    src_crs: str = _EASE_GRID_9K_CRS, resolution_m: float = _EASE_GRID_9K_PIXEL_SIZE
):
    """按 (CRS, 分辨率) 返回 EASE-Grid 仿射变换（委托共享真源 grid_presets）。

    覆盖 EASE-Grid 2.0 全球（6933）与半球 LAEA（6931/6932），以及
    NSIDC EASE-Grid 1.0（3408/3409/3410，球体 R=6371228）。角点查
    ``EASE_UL_BY_CRS``；1.0 与 2.0 角点不同，不可混用。
    """
    return ease_grid_transform(src_crs, resolution_m)


def _ease_grid_9k_transform():
    """返回 EASE-Grid 2.0 9km 的 Affine 变换（rasterio 约定）。"""
    return _ease_grid_transform(_EASE_GRID_9K_CRS, _EASE_GRID_9K_PIXEL_SIZE)


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


# _reproject_to_mercator_linear 已下沉为共享实现（上方 importlib 别名），
# 签名不变：(data, src_transform, src_crs, target_resolution=0.25,
# clip_bounds=None, resampling="nearest") → (out_data, (w, s, e, n))。
# 为什么目标是 Mercator 线性而非等经纬：MapLibre ImageSource 以 4 角坐标
# 在 Mercator 平面双线性插值渲染，等经纬图像在中高纬会偏移十几度。


def _reproject_ease_to_wgs84(
    data,
    target_resolution=0.1,
    clip_bounds=_CHINA_BBOX,
    mat_dict=None,
    src_crs=_EASE_GRID_9K_CRS,
):
    """将 EASE-Grid 数据重投影到 Web Mercator 线性网格，并裁剪到指定窗口。

    EASE-Grid 2.0 是圆柱等积投影（EPSG:6933），行间距随纬度变化。直接当作
    经纬度会导致高纬度地区偏移上百公里。本函数重采样到 MapLibre ImageSource
    渲染精确的 Mercator 线性网格（见 ``_reproject_to_mercator_linear``）。

    Args:
        data: (n_lat, n_lon) 2D array，EASE-Grid 数据
        target_resolution: 目标分辨率（度，赤道处），默认 0.1°；全球层建议 0.25°
        clip_bounds: (west, south, east, north) 裁剪边界，默认中国区域；
                     None 表示全球全幅（-180 ~ 180, ±85.0511）
        mat_dict: 可选，.mat 元数据字典（用于读取真实 Transform）
        src_crs: 源 CRS，默认 EASE-Grid 2.0 全球（EPSG:6933）

    Returns:
        (reprojected_data, bounds) — bounds = (west, south, east, north)
    """
    src_transform = None
    if mat_dict is not None:
        src_transform = _ease_grid_9k_transform_from_mat(mat_dict)
    if src_transform is None:
        src_transform = _ease_grid_transform(src_crs)

    return _reproject_to_mercator_linear(
        data,
        src_transform,
        src_crs,
        target_resolution=target_resolution,
        clip_bounds=clip_bounds,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. DEM ETOPO_2022
# ──────────────────────────────────────────────────────────────────────────────


def export_dem_etopo() -> None:
    print("\n=== DEM ETOPO_2022 ===")
    # 2026-08-25 路径修复：实际文件在 Geological/DEM/ETOPO_2022/ 下
    # （此前缺 Geological 层 → [SKIP] File not found → 资产永远 stale，
# 图层逐一验证报障定位）
    tif_path = Path(
        r"I:\Geograph_DataSet\Geological\DEM\ETOPO_2022\ETOPO_2022_v1_60s_N90W180_surface.tif"
    )
    if not tif_path.exists():
        print("  [SKIP] File not found")
        return

    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin

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
        # 等经纬源网格的仿射（下采样后像素 = scale × 原像素）
        src_transform = from_origin(
            west,
            north,
            (east - west) / (src.width // scale),
            (north - south) / (src.height // scale),
        )
        src_crs = str(src.crs) if src.crs else "EPSG:4326"

    print(
        f"  Data shape: {data.shape}, range: {np.nanmin(data):.1f} to {np.nanmax(data):.1f}"
    )
    # 全球层：重投影到 Web Mercator 线性网格（±90° 角点 MapLibre 无法渲染，
    # 且等经纬行分布在中高纬会偏移十几度）
    data, bounds = _reproject_to_mercator_linear(
        data, src_transform, src_crs, target_resolution=0.5
    )
    print(f"  dem-etopo reprojected: {data.shape}, bounds={bounds}")
    _render_png(
        data, out_dir / "etopo_bed_overlay.png", cmap="terrain", vmin=-8000, vmax=8000
    )
    _write_bounds(out_dir / "etopo_bed_overlay_bounds.json", "dem-etopo", bounds)


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
        # ImageSource 在 Web Mercator 平面插值；不能把等经纬数组直接写 PNG
        # 再依赖前端条带补偿（条带异步失败即回退成数百公里南偏/拉伸）。
        # 以 .mat 的真实像元外边界构建源 Affine，在烘焙阶段一次性重投影为
        # Mercator-y 线性资产，浏览器仅做单张 image source 贴图即可精确显示。
        from rasterio.transform import from_bounds

        src_transform = from_bounds(*bounds, data.shape[1], data.shape[0])
        data, mercator_bounds = _reproject_to_mercator_linear(
            data,
            src_transform,
            "EPSG:4326",
            target_resolution=0.25,
            clip_bounds=bounds,
            resampling="nearest" if varname == "landcover" else "bilinear",
        )
        print(f"  {layer_id}: mercator={data.shape}, bounds={mercator_bounds}")
        _render_png(
            data, out_dir / f"{varname}_overlay.png", cmap=cmap, vmin=vmin, vmax=vmax
        )
        _write_bounds(out_dir / f"{varname}_overlay_bounds.json", layer_id, mercator_bounds)


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
            # 不再回退全球 bounds：未重投影的 EASE 网格配全球 bounds 会被
            # MapLibre 拉伸到错误位置（历史上“大变样”事故的来源），跳过该帧
            print(f"  [WARN] doy_{tag} reproject failed, skip frame: {e}")
            continue

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
        _write_bounds(out_dir / f"smap_sm_{tag}_bounds.json", "ref-smap-sm-202512-l3", bounds)

    # Also write a generic bounds file
    _write_bounds(
        out_dir / "smap_sm_ts_bounds.json",
        "ref-smap-sm-202512-l3",
        generic_bounds if generic_bounds is not None else _CHINA_BBOX,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 7. GPCP monthly precipitation time series
# ──────────────────────────────────────────────────────────────────────────────


def export_gpcp_ts() -> None:
    print("\n=== GPCP precipitation time series ===")
    gpcp_dir = resolve_data_root() / "Weather" / "Precipitation" / "Precipitation" / "dataset"
    if not gpcp_dir.exists():
        gpcp_dir = resolve_data_root() / "Meteorological" / "Weather" / "Precipitation" / "Precipitation" / "dataset"
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

        # 0.5° 等经纬源网格 → Web Mercator 线性网格（720×720）。
        # 旧版直接写 (-180,-90,180,90)：±90° 角点 MapLibre 无法渲染 → 图层不显示。
        from rasterio.transform import from_origin as _from_origin

        src_transform = _from_origin(-180.0, 90.0, 0.5, 0.5)
        arr, bounds = _reproject_to_mercator_linear(
            arr, src_transform, "EPSG:4326", target_resolution=0.5
        )

        print(f"  {tag}: {arr.shape}, range={np.nanmin(arr):.2f}-{np.nanmax(arr):.2f}")
        # GPCP 月降水大面积低值（中位数约 1 mm/day）。YlGnBu 的最低端
        # 接近白色，叠加 0.8 opacity 会把底图整块洗白；将近零降水透明，
        # 并使用深色起始的 Blues，确保有效降水与底图均可辨。
        arr[arr <= 0.05] = np.nan
        vmax = float(np.nanpercentile(arr, 99))
        _render_png(
            arr, out_dir / f"gpcp_{tag}.png", cmap="Blues", vmin=0.05, vmax=max(vmax, 10)
        )
        _write_bounds(out_dir / f"gpcp_{tag}_bounds.json", "gpcp-precip-ts", bounds)

        ds.close()

    # Generic bounds（与最新一帧一致；Mercator 全幅）
    _write_bounds(
        out_dir / "gpcp_ts_bounds.json",
        "gpcp-precip-ts",
        (-180.0, -_MERCATOR_MAX_LAT, 180.0, _MERCATOR_MAX_LAT),
    )


def export_gpcp_rewarp() -> None:
    """把既有 GPCP 资产 PNG（等经纬 ±90° 旧格式）原地重变形为 Mercator 线性。

    源 NC 数据目录缺失无法重导出时，用本任务直接修复已导出的 PNG：
    对每帧按行最近邻重采样（行从纬度均匀 → Mercator y 均匀），并重写
    bounds JSON 为 Mercator 全幅。只改资产文件，不触碰源数据。
    """
    print("\n=== GPCP asset re-warp (equirect -> mercator-linear) ===")
    out_dir = _OUT_ROOT / "gpcp_ts"
    pngs = sorted(out_dir.glob("gpcp_*.png")) if out_dir.exists() else []
    if not pngs:
        print("  [SKIP] No existing gpcp_*.png assets found")
        return

    from PIL import Image

    # 源：0.5° 等经纬，纬度中心 -89.75..89.75（360 行）
    lat_centers = 90.0 - (np.arange(360) + 0.5) * 0.5
    # 目标：Mercator y 均匀的 720 行（0.5° 等效），反解各行纬度中心
    t_edges = np.linspace(-_MERCATOR_MAX_LAT, _MERCATOR_MAX_LAT, 721)
    y_edges = np.log(np.tan(np.deg2rad(t_edges) / 2 + np.pi / 4))
    y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])
    tgt_lat = np.rad2deg(2 * np.arctan(np.exp(y_centers)) - np.pi / 2)

    # 每个目标行取最近源行（源行号按纬度降序 → 反转索引）
    src_rows = np.searchsorted(-lat_centers, -tgt_lat)  # lat_centers 降序
    src_rows = np.clip(src_rows, 0, len(lat_centers) - 1)

    n_fixed = 0
    for png in pngs:
        bounds_json = png.with_name(png.stem + "_bounds.json")
        img = Image.open(png)
        if img.size[1] != len(lat_centers):
            print(f"  [SKIP] {png.name}: unexpected height {img.size[1]}")
            continue
        # 按行最近邻采样（源行纬度均匀 → 目标行 Mercator y 均匀），列保持 720
        arr = np.asarray(img)
        warped_arr = arr[src_rows, :]
        out_img = Image.fromarray(warped_arr)
        out_img.save(png)
        _write_bounds(
            bounds_json,
            "gpcp-precip-ts",
            (-180.0, -_MERCATOR_MAX_LAT, 180.0, _MERCATOR_MAX_LAT),
        )
        n_fixed += 1
        print(f"  [OK] {png.name} re-warped ({img.size[1]}x{img.size[0]} -> 720x720)")

    generic = out_dir / "gpcp_ts_bounds.json"
    if generic.exists() or n_fixed:
        _write_bounds(
            generic,
            "gpcp-precip-ts",
            (-180.0, -_MERCATOR_MAX_LAT, 180.0, _MERCATOR_MAX_LAT),
        )
    print(f"  Re-warped {n_fixed} PNG(s)")


def export_china_rewarp() -> None:
    """把中国窗口等经纬资产 PNG 原地重变形为 Mercator 线性（2026-08-22）。

    背景：thematic（hfp/aridity/landcover）与 clcd 资产是 2026-07 旧版等经纬
    渲染 + WGS84 矩形 bounds；MapLibre ImageSource 在 Mercator 平面插值，
    等纬度图像在中高纬偏北（用户实测 HFP ~190km、AI 干旱指数/CLCD 同症）。

    修法：源行纬度均匀 [s,n] → 重采样为 Mercator-y 均匀行（最近邻），
    bounds 四角保持 WGS84 不变（MapLibre 转 Mercator 后与行对齐）。
    """
    print("\n=== China-window asset re-warp (equirect -> mercator-linear) ===")
    from PIL import Image

    targets = [
        ("thematic/hfp_overlay.png", "hfp-cn"),
        ("thematic/aridity_overlay.png", "aridity-cn"),
        ("thematic/landcover_overlay.png", "landcover-cn"),
        ("clcd/clcd_overlay.png", "clcd-cn"),
        ("gebco_dem/gebco_dem_overlay.png", "gebco-dem-cn"),
    ]
    n_fixed = 0
    for rel, layer_id in targets:
        png = _OUT_ROOT / rel
        bounds_json = png.with_name(png.stem + "_bounds.json")
        if not png.exists():
            print(f"  [SKIP] {rel} not found")
            continue
        try:
            bj = json.loads(bounds_json.read_text(encoding="utf-8"))
            if bj.get("rewarped"):
                print(f"  [SKIP] {rel}: already re-warped (idempotent guard)")
                continue
            bounds = bj["bounds"]
        except Exception as exc:
            print(f"  [SKIP] {rel}: bad bounds json ({exc})")
            continue
        w, s, e, n = (float(v) for v in bounds)
        img = Image.open(png)
        arr = np.asarray(img)
        h = arr.shape[0]

        def merc_y(lat_deg: float) -> float:
            t = np.deg2rad(np.clip(lat_deg, -_MERCATOR_MAX_LAT, _MERCATOR_MAX_LAT))
            return float(np.log(np.tan(np.pi / 4 + t / 2)))

        y_s, y_n = merc_y(s), merc_y(n)
        # 目标行中心（Mercator y 均匀）反解纬度
        y_centers = y_s + (np.arange(h) + 0.5) / h * (y_n - y_s)
        tgt_lat = np.rad2deg(2 * np.arctan(np.exp(y_centers)) - np.pi / 2)
        # 源行索引（等纬度，j=0 = 北边界 n）
        src_rows = np.clip(((n - tgt_lat) / (n - s) * h).round().astype(int), 0, h - 1)
        warped = arr[src_rows, :]
        Image.fromarray(warped).save(png)
        # bounds 保持 WGS84 四角不变（重采样已补偿 Mercator 拉伸）；
        # 写 rewarped 标记防二次重采样（幂等保护）
        bj["rewarped"] = True
        bounds_json.write_text(json.dumps(bj, ensure_ascii=False, indent=2), encoding="utf-8")
        n_fixed += 1
        print(f"  [OK] {rel} re-warped ({h} rows, bounds [{w:.2f},{s:.2f},{e:.2f},{n:.2f}])")
    print(f"  Re-warped {n_fixed} PNG(s)")


def export_dem_rewarp() -> None:
    """把既有 DEM 资产 PNG（等经纬 ±90° 旧格式）原地重变形为 Mercator 线性。

    源 GeoTIFF 缺失无法重导出时，用本任务直接修复已导出的 PNG：
    按行最近邻重采样（纬度均匀 → Mercator y 均匀）并重写 bounds JSON。
    """
    print("\n=== DEM asset re-warp (equirect -> mercator-linear) ===")
    out_dir = _OUT_ROOT / "dem"
    png = out_dir / "etopo_bed_overlay.png"
    bounds_json = out_dir / "etopo_bed_overlay_bounds.json"
    if not png.exists():
        print("  [SKIP] No existing etopo_bed_overlay.png asset found")
        return

    from PIL import Image

    img = Image.open(png)
    if img.size != (1800, 900):
        print(f"  [SKIP] Unexpected size {img.size}, expected (1800, 900)")
        return

    # 源：0.2° 等经纬，纬度中心 -89.0..89.0（900 行）
    lat_centers = 90.0 - (np.arange(900) + 0.5) * 0.2
    # 目标：Mercator y 均匀的 720 行（0.25° 等效），反解各行纬度中心
    t_edges = np.linspace(-_MERCATOR_MAX_LAT, _MERCATOR_MAX_LAT, 721)
    y_edges = np.log(np.tan(np.deg2rad(t_edges) / 2 + np.pi / 4))
    y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])
    tgt_lat = np.rad2deg(2 * np.arctan(np.exp(y_centers)) - np.pi / 2)

    src_rows = np.searchsorted(-lat_centers, -tgt_lat)  # lat_centers 降序
    src_rows = np.clip(src_rows, 0, len(lat_centers) - 1)

    arr = np.asarray(img)
    warped_arr = arr[src_rows, :]
    Image.fromarray(warped_arr).save(png)
    _write_bounds(
        bounds_json,
        "dem-etopo",
        (-180.0, -_MERCATOR_MAX_LAT, 180.0, _MERCATOR_MAX_LAT),
    )
    print(f"  [OK] {png.name} re-warped (900x1800 -> 720x1800)")

    generic = out_dir / "dem_bounds.json"
    if generic.exists():
        _write_bounds(
            generic,
            "dem-etopo",
            (-180.0, -_MERCATOR_MAX_LAT, 180.0, _MERCATOR_MAX_LAT),
        )


# ──────────────────────────────────────────────────────────────────────────────
# 8. GEBCO 2024 DEM (NetCDF, 中国区域)
# ──────────────────────────────────────────────────────────────────────────────


def export_gebco_dem() -> None:
    print("\n=== GEBCO 2024 DEM (China) ===")
    # 与 overlay_registry._GEBCO_NC 对齐
    nc_path = resolve_data_root() / "Geological" / "DEM" / "GEBCO_2024.nc"
    if not nc_path.exists():
        # 旧路径兼容
        alt = resolve_data_root() / "DEM" / "GEBCO_2024.nc"
        nc_path = alt if alt.exists() else nc_path
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
    tif_path = resolve_data_root() / "Precipitation" / "pre_2002_01.tif"
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
    # 与 overlay_registry._CLCD_TIF 路径对齐（旧 LandCover/ 路径已失效）
    tif_path = resolve_data_root() / "Ecological_Vegetation" / "LandCover" / "CLCD_v01_1997.tif"
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
        src_transform = src.window_transform(win)
        src_crs = str(src.crs) if src.crs else "EPSG:4326"

    # 后端烘焙为 Mercator 线性行；避免浏览器端条带化失败时图层南偏/拉伸。
    event_count, actual_bounds = _reproject_to_mercator_linear(
        event_count, src_transform, src_crs, target_resolution=0.25, clip_bounds=actual_bounds
    )
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
        src_transform = src.window_transform(win)
        src_crs = str(src.crs) if src.crs else "EPSG:4326"

    # 后端烘焙为 Mercator 线性行；避免浏览器端条带化失败时图层南偏/拉伸。
    event_count, actual_bounds = _reproject_to_mercator_linear(
        event_count, src_transform, src_crs, target_resolution=0.25, clip_bounds=actual_bounds
    )
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
    """MeanCarbonDioxide 全球层（GOSAT L3 粗网格 2.5°x2.0°）。

    2026-08-23 重写：
    - 源路径修正（原 I:\\Geograph_DataSet\\CO2\\... 已失效，实际位于
      Atmospheric\\CO2\\MidLayerCO2Column\\TIF\\，此前 File-not-found 一直
      SKIP，07-18 旧资产未再更新）。
    - 重投影到 Mercator 线性网格（_reproject_to_mercator_linear）——旧资产
      直接用源 bounds（north=90 超 Mercator 上限 85.051）贴图导致南北
      大范围拉伸。
    - bilinear 重采样：源 2.5° 粗网格的连续量（CO₂ ppm）线性插值合理，
      缓解瓦片块状感（nearest 会放大块状）。
    - vmin/vmax 用源数据 p1/p99（386-391 为旧数据范围，实测 370-407）。
    """
    print("\n=== MeanCarbonDioxide (global, GOSAT L3) ===")
    tif_path = Path(
        r"I:\Geograph_DataSet\Atmospheric\CO2\MidLayerCO2Column\TIF\MeanCarbonDioxide.tif"
    )
    if not tif_path.exists():
        print(f"  [SKIP] File not found: {tif_path}")
        return

    import rasterio

    out_dir = _OUT_ROOT / "co2"

    with rasterio.open(tif_path) as src:
        data = src.read(1).astype(np.float64)
        src_transform = src.transform
        src_crs = src.crs or "EPSG:4326"
        print(
            f"  source: {data.shape}, bounds={tuple(round(b, 2) for b in src.bounds)}, "
            f"range={np.nanmin(data):.2f}~{np.nanmax(data):.2f} ppm"
        )

    # 全球全幅 Mercator 线性网格；north=90 由管线 clamp 到 85.051
    data, bounds = _reproject_to_mercator_linear(
        data,
        src_transform,
        str(src_crs),
        target_resolution=0.25,
        clip_bounds=None,
        resampling="bilinear",
    )
    print(f"  reprojected (mercator-linear): {data.shape}, bounds={bounds}")

    vmin, vmax = _smap_aux_continuous_range(data)
    print(f"  display range (p1/p99): vmin={vmin}, vmax={vmax}")
    _render_png(
        data, out_dir / "co2_overlay.png", cmap="RdYlGn_r", vmin=vmin, vmax=vmax
    )
    _write_bounds(out_dir / "co2_overlay_bounds.json", "co2-cn", bounds)


# ──────────────────────────────────────────────────────────────────────────────
# 14. Soil DDCA 时间序列（中国 9km，2015-04 ~ 2022-12，采样 60 天）
# ──────────────────────────────────────────────────────────────────────────────


def export_soil_ddca_ts() -> None:
    """导出 ref-ddca-sm-201504-202512 时间序列：每个采样日期一个 PNG + bounds JSON。

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
            # 不回退全球 bounds（同 omega 路径），重投影失败跳过该帧
            print(f"  [WARN] {tag} reproject failed, skip frame: {e}")
            continue

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
        _write_bounds(out_dir / f"soil_ddca_{tag}_bounds.json", "ref-ddca-sm-201504-202512", bounds)

    if generic_bounds is not None:
        _write_bounds(
            out_dir / "soil_ddca_overlay_bounds.json", "ref-ddca-sm-201504-202512", generic_bounds
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
            # 不再回退全球 bounds：未重投影的 EASE 网格配全球 bounds 会被
            # MapLibre 拉伸到错误位置（历史上“大变样”事故的来源），跳过该帧
            print(f"  [WARN] doy_{tag} reproject failed, skip frame: {e}")
            continue

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
    mat_path = resolve_data_root() / "Inversion_Results" / "Forest_Ratio_9KM_2020.mat"
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
    # EASE-Grid 2.0 9km 重投影到 Web Mercator 线性网格（全球产品，默认全球全幅）
    extent = _resolve_extent("global")
    try:
        data, bounds = _reproject_ease_to_wgs84(
            data,
            target_resolution=_extent_res_deg(extent),
            clip_bounds=_extent_clip(extent),
            mat_dict=m,
        )
        print(f"  forest_ratio reprojected ({extent}): {data.shape}, bounds={bounds}")
    except Exception as e:
        print(f"  [WARN] EASE-Grid reproject with .mat metadata failed: {e}")
        # 重试：使用默认 EASE-Grid 9km transform（不依赖 .mat 元数据）
        try:
            data, bounds = _reproject_ease_to_wgs84(
                data,
                target_resolution=_extent_res_deg(extent),
                clip_bounds=_extent_clip(extent),
                mat_dict=None,
            )
            print(
                f"  forest_ratio reprojected (default transform, {extent}): "
                f"{data.shape}, bounds={bounds}"
            )
        except Exception as e2:
            print(f"  [ERROR] EASE-Grid reproject failed entirely: {e2}")
            print(
                "  [SKIP] Skipping forest_ratio export — "
                "un-reprojected data with wrong bounds would cause severe coordinate offset"
            )
            return
    _render_png(data, out_dir / "forest_ratio_overlay.png", cmap="YlGn", vmin=0, vmax=1)
    _write_bounds(out_dir / "forest_ratio_overlay_bounds.json", "forest-ratio", bounds)


# ──────────────────────────────────────────────────────────────────────────────
# 21. SMAP 辅助数据静态图层（9 层，EASE-Grid 9km / 全球 0.083°）
#     命名与 overlay_registry.py 的 smap-aux-* 条目严格一致；
#     旧版 aux_*/ 目录为全球范围未重投影导出（地理定位错误），由本节取代
# ──────────────────────────────────────────────────────────────────────────────

_SMAP_AUX_DATA_DIR = resolve_data_root() / "Soil_Moisture" / "SMAP_Auxiliary_Data"


def _smap_aux_continuous_range(data: np.ndarray) -> tuple[float, float]:
    """中国区裁剪后连续场的显示范围：1% / 99% 分位（打印后同步回注册表）。"""
    valid = data[np.isfinite(data)]
    if valid.size == 0:
        return (0.0, 1.0)
    vmin = float(np.percentile(valid, 1))
    vmax = float(np.percentile(valid, 99))
    if vmax <= vmin:
        vmax = vmin + 1.0
    return (round(vmin, 4), round(vmax, 4))


def export_smap_aux_layers() -> None:
    """导出 9 个 smap-aux-* 静态叠加层 PNG + bounds（registry 命名）。

    - EASE-Grid 9km 场（albedo/bd/sf/b/cf/h/igbp/vi-qa）：重投影到 Web Mercator
      线性网格（全球产品，默认全球全幅 0.25°）。
    - Koppen 为全球 0.083° 等经纬网格：构建源仿射后同样重投影（全球全幅）。
    - 分类场（igbp/koppen）：0 视为无效掩膜，vmin/vmax 固定类别范围。
    - 连续场：vmin/vmax 取 1%/99% 分位并打印——注册表需同步该值以保持
      图例与 PNG 一致。
    """
    print("\n=== SMAP auxiliary static layers (9 layers) ===")
    aux_extent = _resolve_extent("global")

    ease_fields = [
        ("Albedo.mat", "ALBEDO", "smap_aux_albedo", "smap-aux-albedo", "YlOrRd"),
        ("BD.mat", "BD", "smap_aux_bd", "smap-aux-bd", "YlOrBr"),
        ("SF.mat", "SF", "smap_aux_sf", "smap-aux-sf", "YlGn"),
        ("B.mat", "B", "smap_aux_b", "smap-aux-b", "RdBu"),
        ("CF.mat", "CF", "smap_aux_cf", "smap-aux-cf", "PuBu"),
        ("H.mat", "H", "smap_aux_h", "smap-aux-h", "Oranges"),
        (
            "IGBP_9km_12.mat",
            "IGBP_9km_12",
            "smap_aux_igbp",
            "smap-aux-igbp",
            "nipy_spectral",
        ),
        ("VI_v_qa.mat", "NDVI_v_mean", "smap_aux_vi_qa", "smap-aux-vi-qa", "RdYlGn"),
    ]
    discrete = {"smap-aux-igbp"}

    for mat_file, var, subdir, layer_id, cmap in ease_fields:
        src = _SMAP_AUX_DATA_DIR / mat_file
        print(f"\n--- {layer_id} ({mat_file}:{var}) ---")
        if not src.exists():
            print(f"  [SKIP] File not found: {src}")
            continue
        m = _read_mat_auto(src)
        if var not in m:
            print(f"  [SKIP] Variable {var} not found, keys={list(m.keys())[:10]}")
            continue
        data = np.asarray(m[var], dtype=np.float64)
        if layer_id in discrete:
            data[data == 0] = np.nan
        try:
            data, bounds = _reproject_ease_to_wgs84(
                data,
                target_resolution=_extent_res_deg(aux_extent),
                clip_bounds=_extent_clip(aux_extent),
            )
            print(f"  reprojected ({aux_extent}): {data.shape}, bounds={bounds}")
        except Exception as e:
            print(f"  [FAIL] EASE-Grid reproject failed: {e}")
            continue
        out_dir = _OUT_ROOT / subdir
        if layer_id in discrete:
            vmin, vmax = 1, 17
        else:
            vmin, vmax = _smap_aux_continuous_range(data)
            print(f"  display range (p1/p99): vmin={vmin}, vmax={vmax}")
        _render_png(
            data,
            out_dir / f"{subdir}_overlay.png",
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
        )
        _write_bounds(
            out_dir / f"{subdir}_overlay_bounds.json", layer_id, bounds
        )

    # Koppen：全球 0.083° 等经纬网格 → 与 EASE 场同样重投影到 Mercator 线性网格
    print("\n--- smap-aux-koppen (Koppen_present_083.mat:Koppen) ---")
    src = _SMAP_AUX_DATA_DIR / "Koppen_present_083.mat"
    if not src.exists():
        print(f"  [SKIP] File not found: {src}")
        return
    m = _read_mat_auto(src)
    if "Koppen" not in m:
        print(f"  [SKIP] Variable Koppen not found, keys={list(m.keys())[:10]}")
        return
    data = np.asarray(m["Koppen"], dtype=np.float64)
    data[data == 0] = np.nan
    lat_raw = np.asarray(m["lat_kop"], dtype=np.float64)
    lon_raw = np.asarray(m["lon_kop"], dtype=np.float64)
    # 坐标可能是 2D 网格（规则网格取首列/首行即 1D 轴）
    lat = lat_raw[:, 0].ravel() if lat_raw.ndim == 2 else lat_raw.ravel()
    lon = lon_raw[0, :].ravel() if lon_raw.ndim == 2 else lon_raw.ravel()
    if lat.size != data.shape[0] or lon.size != data.shape[1]:
        print(
            f"  [SKIP] Grid mismatch: data {data.shape} vs lat {lat.size}/lon {lon.size}"
        )
        return
    # 坐标可能降序（北→南），统一为行号升纬度
    if lat[0] > lat[-1]:
        lat = lat[::-1]
        data = data[::-1, :]
    try:
        from rasterio.transform import from_origin as _from_origin

        dlat = float(np.median(np.abs(np.diff(lat))))
        dlon = float(np.median(np.abs(np.diff(lon))))
        src_transform = _from_origin(
            float(lon[0] - dlon / 2), float(lat[-1] + dlat / 2), dlon, dlat
        )
        data, bounds = _reproject_to_mercator_linear(
            data,
            src_transform,
            "EPSG:4326",
            target_resolution=_extent_res_deg(aux_extent, china_deg=0.083),
            clip_bounds=_extent_clip(aux_extent),
        )
        print(f"  koppen reprojected ({aux_extent}): {data.shape}, bounds={bounds}")
    except Exception as e:
        print(f"  [FAIL] Koppen reproject failed: {e}")
        return
    out_dir = _OUT_ROOT / "smap_aux_koppen"
    _render_png(
        data, out_dir / "smap_aux_koppen_overlay.png", cmap="Set3", vmin=1, vmax=30
    )
    _write_bounds(
        out_dir / "smap_aux_koppen_overlay_bounds.json", "smap-aux-koppen", bounds
    )


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
    # EASE-Grid 2.0 9km 重投影到 Web Mercator 线性网格（全球产品，默认全球全幅）
    # .mat 含 Transform (500m 网格，需 × 18 = 9008.0552m) + CRS (EPSG:6933)
    extent = _resolve_extent("global")
    try:
        data, bounds = _reproject_ease_to_wgs84(
            data,
            target_resolution=_extent_res_deg(extent),
            clip_bounds=_extent_clip(extent),
            mat_dict=m,
        )
        print(
            f"  landscape_metrics reprojected ({extent}): {data.shape}, bounds={bounds}"
        )
    except Exception as e:
        print(f"  [WARN] EASE-Grid reproject with .mat metadata failed: {e}")
        # 重试：使用默认 EASE-Grid 9km transform（不依赖 .mat 元数据）
        try:
            data, bounds = _reproject_ease_to_wgs84(
                data,
                target_resolution=_extent_res_deg(extent),
                clip_bounds=_extent_clip(extent),
                mat_dict=None,
            )
            print(
                f"  landscape_metrics reprojected (default transform, {extent}): "
                f"{data.shape}, bounds={bounds}"
            )
        except Exception as e2:
            print(f"  [ERROR] EASE-Grid reproject failed entirely: {e2}")
            print(
                "  [SKIP] Skipping landscape_metrics export — "
                "un-reprojected data with wrong bounds would cause severe coordinate offset"
            )
            return
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
        layer_id: 图层 ID（'vod-dec2025' / 'prod-fy_smap_station-sm_vod_omega-202512-fusion' / 'omega-dec2025'）
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
            # 不回退全球 bounds（同 omega 路径），重投影失败跳过该帧
            print(f"  [WARN] {tag} reproject failed, skip frame: {e}")
            continue

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
    """导出 prod-fy_smap_station-sm_vod_omega-202512-fusion 时间序列：土壤湿度 SM（2025-12，31 天）。

    输出文件：
      - ``_OVERLAY_PNG_ROOT/sm_ts/sm_ts_{tag}.png``（tag = '20251201', ...）
      - ``_OVERLAY_PNG_ROOT/sm_ts/sm_ts_{tag}_bounds.json``
      - ``_OVERLAY_PNG_ROOT/sm_ts/sm_ts_overlay_bounds.json``（通用 bounds）
    """
    _export_smap_soil_vod_sm_ts(
        varname="SM",
        layer_id="prod-fy_smap_station-sm_vod_omega-202512-fusion",
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


def _build_task_table() -> list[dict]:
    """导出任务表：key / 显示名 / 执行函数 / 声明 extent / 覆盖的 layer_id。

    extent 语义：
      - "global"：全球产品（默认输出全球全幅 Mercator 线性网格 0.25°）
      - "china" ：中国区域产品（中国窗口 0.1°）
      - "native"：全球产品且天然全球网格（GPCP/DEM，不受 --extent 裁剪）
    CLI ``--extent global|china`` 可强制覆盖（诊断用），``auto`` 按声明执行。
    """
    return [
        {"key": "dem-etopo", "name": "DEM ETOPO", "func": export_dem_etopo,
         "extent": "native", "layers": ["dem-etopo"]},
        {"key": "thematic", "name": "Thematic", "func": export_thematic_layers,
         "extent": "china", "layers": ["landcover-cn", "hfp-cn", "aridity-cn"]},
        {"key": "omega-ts", "name": "Omega TS", "func": export_omega_ts,
         "extent": "china", "layers": ["omega-output"]},
        {"key": "smap-ts", "name": "SMAP TS", "func": export_smap_ts,
         "extent": "china", "layers": ["ref-smap-sm-202512-l3"]},
        {"key": "gpcp-ts", "name": "GPCP TS", "func": export_gpcp_ts,
         "extent": "native", "layers": ["gpcp-precip-ts"]},
        {"key": "gpcp-rewarp", "name": "GPCP Re-warp", "func": export_gpcp_rewarp,
         "extent": "native", "layers": ["gpcp-precip-ts"]},
        {"key": "china-rewarp", "name": "China Re-warp", "func": export_china_rewarp,
         "extent": "native", "layers": ["landcover-cn", "hfp-cn", "aridity-cn", "clcd-cn"]},
        {"key": "dem-rewarp", "name": "DEM Re-warp", "func": export_dem_rewarp,
         "extent": "native", "layers": ["dem-etopo"]},
        {"key": "gebco-dem", "name": "GEBCO DEM", "func": export_gebco_dem,
         "extent": "china", "layers": ["gebco-dem-cn"]},
        {"key": "cmfd-precip", "name": "CMFD Precip", "func": export_cmfd_precip,
         "extent": "china", "layers": ["cmfd-precip-cn"]},
        {"key": "clcd", "name": "CLCD", "func": export_clcd,
         "extent": "china", "layers": ["clcd-cn"]},
        {"key": "biomass", "name": "BIOMASS", "func": export_biomass,
         "extent": "china", "layers": ["biomass-cn"]},
        {"key": "era5-dwaa", "name": "ERA5 DWAA", "func": export_era5_dwaa,
         "extent": "china", "layers": ["era5-dwaa-cn"]},
        {"key": "era5-wdaa", "name": "ERA5 WDAA", "func": export_era5_wdaa,
         "extent": "china", "layers": ["era5-wdaa-cn"]},
        {"key": "co2", "name": "CO2", "func": export_co2,
         "extent": "china", "layers": ["co2-cn"]},
        {"key": "soil-ddca-ts", "name": "Soil DDCA TS", "func": export_soil_ddca_ts,
         "extent": "china", "layers": ["ref-ddca-sm-201504-202512"]},
        {"key": "omega-fy-ts", "name": "Omega FY TS", "func": export_omega_fy_ts,
         "extent": "china", "layers": ["omega-fy-output"]},
        {"key": "forest-ratio", "name": "Forest Ratio", "func": export_forest_ratio,
         "extent": "global", "layers": ["forest-ratio"]},
        {"key": "landscape-metrics", "name": "Landscape Metrics",
         "func": export_landscape_metrics,
         "extent": "global", "layers": ["landscape-metrics-9km"]},
        {"key": "smap-aux", "name": "SMAP Aux Layers", "func": export_smap_aux_layers,
         "extent": "global",
         "layers": [
             "smap-aux-albedo", "smap-aux-bd", "smap-aux-sf", "smap-aux-b",
             "smap-aux-cf", "smap-aux-h", "smap-aux-igbp", "smap-aux-vi-qa",
             "smap-aux-koppen",
         ]},
        # ── Phase 2: 课题组 VOD/SM/Omega 2025-12 产品族 ──
        {"key": "vod-ts", "name": "VOD TS", "func": export_vod_ts,
         "extent": "china", "layers": ["vod-dec2025"]},
        {"key": "sm-dec2025-ts", "name": "SM Dec2025 TS", "func": export_sm_dec2025_ts,
         "extent": "china", "layers": ["prod-fy_smap_station-sm_vod_omega-202512-fusion"]},
        {"key": "omega-2025-ts", "name": "Omega 2025 TS", "func": export_omega_2025_ts,
         "extent": "china", "layers": ["omega-dec2025"]},
    ]


def main(argv: list[str] | None = None) -> int:
    global _EXTENT_MODE, _OUT_ROOT

    import argparse

    parser = argparse.ArgumentParser(
        description="批量导出叠加图层预览资产（PNG + bounds JSON）",
    )
    parser.add_argument(
        "--tasks",
        default="all",
        help=(
            "逗号分隔的任务 key（见任务表），或 'all'（默认全量）。"
            " 例：--tasks smap-aux,forest-ratio,landscape-metrics,gpcp-rewarp"
        ),
    )
    parser.add_argument(
        "--extent",
        choices=["auto", "global", "china"],
        default="auto",
        help=(
            "强制覆盖任务声明的输出范围（诊断用）；auto=按任务表声明。"
            " global=全球全幅（-180~180, ±85.0511, 0.25°），china=中国窗口 0.1°"
        ),
    )
    parser.add_argument(
        "--out-root",
        default=None,
        help="覆盖输出根目录（默认 I:\\...\\_overlays）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将执行的任务与目标 bounds/分辨率，不写任何文件",
    )
    args = parser.parse_args(argv)

    if args.out_root:
        _OUT_ROOT = Path(args.out_root)
    _EXTENT_MODE = args.extent

    print("=" * 60)
    print("Overlay Assets Export Tool")
    print(f"  out_root: {_OUT_ROOT}")
    print(f"  extent:   {_EXTENT_MODE}")
    print("=" * 60)

    task_table = _build_task_table()
    if args.tasks.strip().lower() == "all":
        selected = task_table
    else:
        by_key = {t["key"]: t for t in task_table}
        unknown = []
        selected = []
        for key in [k.strip() for k in args.tasks.split(",") if k.strip()]:
            if key in by_key:
                selected.append(by_key[key])
            else:
                unknown.append(key)
        if unknown:
            print(f"[ERROR] Unknown task keys: {', '.join(unknown)}")
            print("Available keys:")
            for t in task_table:
                print(f"  {t['key']:<18} ({t['extent']})  {t['name']}")
            return 2

    if args.dry_run:
        print("\n[dry-run] Selected tasks:")
        for t in selected:
            eff = _resolve_extent(t["extent"])
            clip = _extent_clip(eff)
            res = _extent_res_deg(eff)
            if t["extent"] == "native":
                target = "native-global (source grid extent, --extent ignored)"
            else:
                target = (
                    f"clip={clip or 'FULL GLOBE (-180~180, ±85.05)'}, res={res} deg"
                )
            print(f"  {t['key']:<18} extent={t['extent']:<7} {target}")
            print(f"    layers: {', '.join(t['layers'])}")
        return 0

    _OUT_ROOT.mkdir(parents=True, exist_ok=True)

    results = {}
    for task in selected:
        name = task["name"]
        try:
            task["func"]()
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
