"""把 NAS 上的单个 ``.mat`` 渲染成一张地图贴图（PNG + bounds JSON）。

渲染口径全部复用后端已有实现，不新造一套：
* 重投影：``app.data_io.services.grid_reproject.reproject_to_mercator_linear``
  （EASE-Grid 2.0 9km → Web Mercator 线性网格，MapLibre ImageSource 才不偏）
* 上色：``app.services.raster_preview_service.colorize_array_to_rgba``
  （读 catalog_seeds/palettes.json，与图例同源 ⇒ 图上颜色 = 图例颜色）
* 编码：``encode_rgba_png``

所以本模块只负责「读 .mat → 抠出一个变量 → 调上面三个函数」。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.services.nas_ondemand import config

logger = logging.getLogger(__name__)

# 与已有产物一致的烘焙版本号（bounds.json 里记录，供 asset_bake_tasks 判新旧）
BAKE_VERSION = 4


# ── .mat 读取（v5/v6 用 scipy，v7.3 用 h5py；与 export_overlay_assets 一致）──
def read_mat_v5(path: Path) -> dict[str, Any]:
    from scipy.io import loadmat

    raw = loadmat(str(path))
    return {k: v for k, v in raw.items() if not k.startswith("__")}


def read_mat_v73(path: Path) -> dict[str, Any]:
    import h5py

    result: dict[str, Any] = {}
    with h5py.File(str(path), "r") as fh:
        for key in fh.keys():
            node = fh[key]
            # 部分文件顶层含 HDF5「组」（如 raw_ω 的 QC/），不是数据，跳过
            if not isinstance(node, h5py.Dataset):
                continue
            arr = node[:]
            # h5py 按 MATLAB 列主序读，二维数组需转置
            if getattr(arr, "ndim", 0) == 2:
                arr = arr.T
            result[key] = arr
    return result


def read_mat_auto(path: Path) -> dict[str, Any]:
    try:
        return read_mat_v5(path)
    except Exception:  # noqa: BLE001 - v5 读不了就一定是 v7.3，保持与旧脚本一致
        return read_mat_v73(path)


# ── EASE-Grid 仿射变换（优先用 .mat 自带参数，否则用 9km 标准）──────────────
def ease_transform_from_mat(mat: dict[str, Any]):
    """从 .mat 的 Transform/CRS 元数据构建 rasterio Affine；缺失返回 None。"""
    if "Transform" not in mat or "CRS" not in mat:
        return None
    try:
        import numpy as np
        from rasterio.transform import Affine

        t = np.asarray(mat["Transform"]).ravel()
        if len(t) < 6:
            return None
        pixel_x = abs(float(t[1]))
        if 400 < pixel_x < 600:  # .mat 给的是 500m 网格参数，9km 数据需 ×18
            scale = 18
            return Affine(
                float(t[1]) * scale,
                0.0,
                float(t[0]),
                0.0,
                float(t[5]) * scale,
                float(t[3]),
            )
        return Affine(
            float(t[1]), float(t[2]), float(t[0]), float(t[4]), float(t[5]), float(t[3])
        )
    except Exception:  # noqa: BLE001 - 元数据异常时退回标准 9km 网格
        logger.warning("mat Transform 解析失败，退回 EASE-Grid 9km 标准网格")
        return None


def extract_variable(mat: dict[str, Any], variable: str):
    """从 .mat 字典里取出指定变量并清掉物理上无意义的负值。

    变量名在 NAS 上有多种写法（实测）：
      * ``SM`` / ``VOD``            —— smvod 目录
      * ``OMEGA``                    —— fy_avg_smvod 附带的 ω
      * ``OMEGA_grid``               —— *_raw_ω（动态散射，48 MB 大文件）
      * ``OMEGA_AVG``                —— *_avg_ω（按年内日序的气候态）
    因此按候选名依次尝试，避免对着同一逻辑变量写死一个键。
    """
    import numpy as np

    key = variable.upper()
    aliases = config.VARIABLE_ALIASES.get(key, (key,))
    found = next((a for a in aliases if a in mat), None)
    if found is None:
        raise ValueError(
            f".mat 里没有变量 {key}（尝试过 {list(aliases)}）；"
            f"实际包含：{sorted(k for k in mat)}"
        )
    data = np.asarray(mat[found], dtype=np.float64)
    if data.ndim != 2:
        raise ValueError(f"变量 {key} 不是二维数组，shape={data.shape}")
    # SM/VOD/OMEGA 负值视为无效（与 export_overlay_assets 口径一致）
    data[data < 0] = np.nan
    return data


_UNSET = object()


def reproject_to_map_grid(
    data,
    mat: dict[str, Any],
    *,
    clip_bounds: tuple[float, float, float, float] | None = _UNSET,  # type: ignore[assignment]
    target_resolution: float | None = None,
):
    """EASE-Grid → Mercator 线性网格；默认裁到中国窗口。

    不传 ``clip_bounds`` = 沿用 ``config.CLIP_BOUNDS``（中国窗口，独立 NAS 图层用）；
    显式传 ``None`` = **不裁**（全球全幅），用于「补帧进既有图层」——
    目标图层原本就是全球 2048 画幅，裁成中国区会让同一层的帧画幅不一致。
    """
    from app.data_io.services.grid_presets import ease_grid_transform
    from app.data_io.services.grid_reproject import reproject_to_mercator_linear

    src_transform = ease_transform_from_mat(mat)
    if src_transform is None:
        src_transform = ease_grid_transform("EPSG:6933", 9008.055)
    clip = config.CLIP_BOUNDS if clip_bounds is _UNSET else clip_bounds
    return reproject_to_mercator_linear(
        data,
        src_transform,
        "EPSG:6933",
        target_resolution=(
            config.TARGET_RESOLUTION_DEG
            if target_resolution is None
            else target_resolution
        ),
        clip_bounds=clip,
    )


def write_png(data, png_path: Path, *, palette: str, vmin: float, vmax: float) -> int:
    """上色 + 编码，写成带透明底的单帧 PNG。返回字节数。"""
    from app.services.raster_preview_service import (
        colorize_array_to_rgba,
        encode_rgba_png,
    )

    rgba = colorize_array_to_rgba(
        data,
        palette=palette,
        min_value=vmin,
        max_value=vmax,
        nodata_mode="transparent",
    )
    payload = encode_rgba_png(rgba)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = png_path.with_suffix(png_path.suffix + ".part")
    tmp.write_bytes(payload)
    tmp.replace(png_path)
    return len(payload)


# 全球 EASE-Grid 2.0 9km 的已知范围（与既有 ``source_*.tif`` 一致）。
# 用「范围 ÷ 数组宽高」现算像元大小，能自动适配 9km / 其它分辨率，
# 又不必依赖 .mat 里可能缺失的 Transform 元数据。
EASE_GLOBAL_WEST = -17367530.45
EASE_GLOBAL_NORTH = 7314540.83
EASE_GLOBAL_WIDTH_M = 34735060.90
EASE_GLOBAL_HEIGHT_M = 14629081.66
SOURCE_NODATA = -9999.0


def write_source_geotiff(path: Path, data, mat_shape: tuple[int, int]) -> int:
    """把**重投影之前**的原始网格写成 ``source_<时间>.tif``，返回字节数。

    为什么需要这个文件：``/overlay-tiles/{z}/{x}/{y}.png`` 只认 GeoTIFF 源
    （``overlay_registry.resolve_source_path`` → ``source_{time}.tif``）。
    只写 PNG 时，单日帧在瓦片渲染模式下必然 404 —— 2026-10-27 现场实测：
    ``?time=20251201_20251231 → 200``、``?time=20251119 → 404``。

    口径与既有产物一致：EPSG:6933、float32、nodata=-9999、deflate 压缩。
    """
    import numpy as np
    import rasterio
    from rasterio.transform import Affine

    h, w = int(mat_shape[0]), int(mat_shape[1])
    arr = np.asarray(data, dtype="float64")
    if arr.shape != (h, w):
        raise ValueError(f"数组 shape {arr.shape} 与声明的 {(h, w)} 不一致")

    transform = Affine(
        EASE_GLOBAL_WIDTH_M / w,
        0.0,
        EASE_GLOBAL_WEST,
        0.0,
        -EASE_GLOBAL_HEIGHT_M / h,
        EASE_GLOBAL_NORTH,
    )
    payload = np.where(np.isfinite(arr), arr, SOURCE_NODATA).astype("float32")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with rasterio.open(
        tmp,
        "w",
        driver="GTiff",
        height=h,
        width=w,
        count=1,
        dtype="float32",
        crs="EPSG:6933",
        transform=transform,
        nodata=SOURCE_NODATA,
        compress="deflate",
        tiled=False,
    ) as ds:
        ds.write(payload, 1)
    tmp.replace(path)
    return path.stat().st_size


def write_bounds(
    bounds_path: Path,
    layer_id: str,
    bounds: tuple[float, float, float, float],
) -> None:
    """写 bounds JSON（与 export_overlay_assets._write_bounds 同格式）。"""
    payload = {
        "layer_id": layer_id,
        "bounds": [float(v) for v in bounds],
        "crs": "EPSG:4326",
        "bake_version": BAKE_VERSION,
    }
    bounds_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = bounds_path.with_suffix(bounds_path.suffix + ".part")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(bounds_path)


def render_frame(
    mat_path: Path,
    *,
    variable: str,
    layer_id: str,
    png_path: Path,
    bounds_path: Path,
    palette: str,
    vmin: float,
    vmax: float,
    clip_bounds: tuple[float, float, float, float] | None = _UNSET,  # type: ignore[assignment]
    target_resolution: float | None = None,
    source_tif_path: Path | None = None,
) -> dict[str, Any]:
    """完整渲染一帧：读 .mat → 重投影 → 上色 → 落盘 PNG + bounds。

    Args:
        clip_bounds: 不传=中国窗口（独立 NAS 图层）；``None``=全球全幅（补帧进
            既有图层时必须与那层原有画幅一致）。
        target_resolution: 覆盖默认 0.1°（补帧按目标图层的 2048 画幅算）。
        source_tif_path: 给出时，额外写一份原始网格 GeoTIFF（瓦片渲染需要它）。

    Returns:
        诊断字典（range / shape / bounds / png_bytes），给 CLI 打验证日志用。
    """
    import numpy as np

    mat = read_mat_auto(mat_path)
    data = extract_variable(mat, variable)
    reprojected, bounds = reproject_to_map_grid(
        data, mat, clip_bounds=clip_bounds, target_resolution=target_resolution
    )
    png_bytes = write_png(reprojected, png_path, palette=palette, vmin=vmin, vmax=vmax)
    write_bounds(bounds_path, layer_id, bounds)
    tif_bytes = (
        write_source_geotiff(source_tif_path, data, data.shape)
        if source_tif_path is not None
        else 0
    )

    finite = np.isfinite(np.asarray(reprojected, dtype=np.float64))
    return {
        "shape": tuple(int(v) for v in np.asarray(reprojected).shape),
        "finite_pixels": int(finite.sum()),
        "vmin": (float(np.nanmin(reprojected)) if finite.any() else None),
        "vmax": (float(np.nanmax(reprojected)) if finite.any() else None),
        "bounds": [float(v) for v in bounds],
        "png_bytes": int(png_bytes),
        "tif_bytes": int(tif_bytes),
    }
