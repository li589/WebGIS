#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""诊断脚本：检查 EASE-Grid .mat 元数据 + CMFD GeoTIFF bounds 差异。

输出：
1. forest_ratio / soil_ddca / omega_fy / omega 的 .mat 元数据（CRS/Transform/形状）
2. CMFD precip 的 src.bounds vs 基于像素中心计算的 _bounds_from_centers 差值
3. 验证 EASE-Grid 9km 像素尺寸：18 × 500.4475 = 9008.055 vs 当前硬编码 9000.879
"""

from __future__ import annotations

import sys
from pathlib import Path
import numpy as np


def _read_mat_auto(path: Path) -> dict:
    try:
        from scipy.io import loadmat

        m = loadmat(str(path))
        return {k: v for k, v in m.items() if not k.startswith("__")}
    except Exception:
        import h5py

        result = {}
        with h5py.File(str(path), "r") as f:
            for k in f.keys():
                arr = f[k][:]
                if arr.ndim == 2:
                    arr = arr.T
                result[k] = arr
        return result


def inspect_ease_mat(label: str, path: Path, var_name: str) -> None:
    print(f"\n=== {label}: {path.name} ===")
    if not path.exists():
        print(f"  [SKIP] File not found: {path}")
        return
    m = _read_mat_auto(path)
    keys = list(m.keys())
    print(f"  Keys: {keys}")
    if var_name not in m:
        print(f"  [WARN] Variable {var_name} not found")
        return
    data = m[var_name]
    print(f"  {var_name}.shape: {data.shape}")
    print(f"  {var_name}.dtype: {data.dtype}")

    # 元数据字段
    for meta_key in (
        "CRS",
        "crs",
        "Transform",
        "transform",
        "Resolution_meters",
        "resolution_meters",
        "lat",
        "lon",
        "latitude",
        "longitude",
    ):
        if meta_key in m:
            val = m[meta_key]
            if isinstance(val, np.ndarray) and val.size <= 10:
                print(f"  {meta_key}: {val.ravel().tolist()}")
            elif isinstance(val, np.ndarray):
                print(
                    f"  {meta_key}: shape={val.shape}, min={np.nanmin(val):.4f}, max={np.nanmax(val):.4f}"
                )
            else:
                print(f"  {meta_key}: {val}")

    # EASE-Grid 像素尺寸验证
    if "Transform" in m:
        t = m["Transform"].ravel()
        if len(t) >= 6:
            pixel_x = abs(float(t[1]))
            pixel_y = abs(float(t[5]))
            print(f"  Transform 解析: pixel_x={pixel_x:.4f}m, pixel_y={pixel_y:.4f}m")
            print(f"  18 × pixel_x = {18 * pixel_x:.4f}m (EASE-Grid 9km 标称值)")
            print("  当前硬编码 _EASE_GRID_9K_PIXEL_SIZE = 9000.879 (错误)")
            print(f"  正确值应为 18 × {pixel_x:.4f} = {18 * pixel_x:.4f}m")


def inspect_cmfd_tif() -> None:
    print("\n=== CMFD Precipitation GeoTIFF bounds ===")
    tif_path = Path(r"I:\Geograph_DataSet\Precipitation\pre_2002_01.tif")
    if not tif_path.exists():
        print(f"  [SKIP] File not found: {tif_path}")
        return
    import rasterio

    with rasterio.open(tif_path) as src:
        print(f"  width x height: {src.width} x {src.height}")
        print(f"  src.bounds (outer edges): {src.bounds}")
        print(f"  src.transform: {src.transform}")
        print(f"  src.crs: {src.crs}")
        print(f"  src.nodata: {src.nodata}")

        # 当前 export 用 src.bounds
        sb_west, sb_south, sb_east, sb_north = src.bounds

        # 像素中心范围（取4个角点中心）
        # 顶部左侧像素中心: transform * (0.5, 0.5)
        # 底部右侧像素中心: transform * (width-0.5, height-0.5)
        # 4 corner centers
        tl_x, tl_y = src.transform * (0.5, 0.5)
        tr_x, tr_y = src.transform * (src.width - 0.5, 0.5)
        bl_x, bl_y = src.transform * (0.5, src.height - 0.5)
        br_x, br_y = src.transform * (src.width - 0.5, src.height - 0.5)
        print(f"  Pixel centers - TL: ({tl_x:.4f}, {tl_y:.4f})")
        print(f"  Pixel centers - TR: ({tr_x:.4f}, {tr_y:.4f})")
        print(f"  Pixel centers - BL: ({bl_x:.4f}, {bl_y:.4f})")
        print(f"  Pixel centers - BR: ({br_x:.4f}, {br_y:.4f})")

        # _bounds_from_centers 等价: min/max + 半像素扩展
        pixel_w = abs(src.transform[0])
        pixel_h = abs(src.transform[4])
        center_west = min(tl_x, bl_x)
        center_east = max(tr_x, br_x)
        center_north = max(tl_y, tr_y)
        center_south = min(bl_y, br_y)
        bc_west = center_west - pixel_w / 2
        bc_east = center_east + pixel_w / 2
        bc_north = center_north + pixel_h / 2
        bc_south = center_south - pixel_h / 2
        print(
            f"  _bounds_from_centers 等价 (W,S,E,N): ({bc_west:.4f}, {bc_south:.4f}, {bc_east:.4f}, {bc_north:.4f})"
        )
        print(
            f"  差值 (src.bounds - centers_ext): "
            f"ΔW={sb_west - bc_west:+.4f}, ΔS={sb_south - bc_south:+.4f}, "
            f"ΔE={sb_east - bc_east:+.4f}, ΔN={sb_north - bc_north:+.4f}"
        )
        # 像素大小
        print(f"  像素大小: w={pixel_w:.6f}°, h={pixel_h:.6f}°")


def main() -> int:
    print("=" * 70)
    print("Overlay Bounds Diagnostic")
    print("=" * 70)

    # EASE-Grid .mat files
    inspect_ease_mat(
        "Forest Ratio",
        Path(r"I:\Geograph_DataSet\InversionResults\Forest_Ratio_9KM_2020.mat"),
        "Forest_Ratio",
    )
    inspect_ease_mat(
        "Soil DDCA",
        Path(r"I:\Geograph_DataSet\Soil_Ecological_Data\DDCA\DDCA_DH\H\20150401.mat"),
        "DH",
    )
    inspect_ease_mat(
        "Omega FY",
        Path(r"I:\Geograph_DataSet\InversionResults\fy_avg\doy_025.mat"),
        "OMEGA_AVG",
    )
    inspect_ease_mat(
        "Omega (smap_avg)",
        Path(r"I:\Geograph_DataSet\InversionResults\smap_avg\doy_017.mat"),
        "OMEGA_AVG",
    )

    # CMFD GeoTIFF
    inspect_cmfd_tif()

    print("\n" + "=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
