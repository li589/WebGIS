#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量导出叠加图层预览资产（PNG + bounds JSON）。

为后端 overlay_registry.py 中注册的每个图层生成地理配准 PNG 预览图。
输出目录: I:\\Geograph_DataSet\\ProjectOutput\\2023-01_Omega_Inversion\\_overlays\\

支持的图层:
  1. dem-etopo      — ETOPO_2022 bed topography (global, terrain)
  2. landcover-cn   — MCD12Q1 landcover (China 0.25deg, IGBP)
  3. hfp-cn         — Human Footprint (China 0.25deg, hot)
  4. aridity-cn     — Aridity Index (China 0.25deg, BrBG)
  5. omega-output   — Omega inversion avg (global EASE-Grid 9km, plasma)
  6. smap-sm-ts     — SMAP soil moisture time series (China, 13 days)
  7. gpcp-precip-ts — GPCP monthly precipitation (global, 24 months)
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
import matplotlib.colors as mcolors

# Output root
_OUT_ROOT = Path(r"I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion\_overlays")
_CHINA_BBOX = (73.0, 15.0, 137.0, 59.0)


def _render_png(
    data: np.ndarray,
    png_path: Path,
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    transparent: bool = True,
) -> None:
    """Render 2D array to a borderless PNG (no axes, no colorbar)."""
    png_path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(data, dtype=np.float64)
    if data.ndim != 2:
        raise ValueError(f"Expected 2D array, got {data.ndim}D")

    n_lat, n_lon = data.shape
    # Figure size proportional to data shape, dpi=100
    figsize = (max(n_lon / 100, 2), max(n_lat / 100, 2))
    fig = plt.figure(figsize=figsize, frameon=False)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    # Mask NaN as transparent
    masked = np.ma.masked_invalid(data)
    ax.imshow(masked, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto", origin="upper", interpolation="nearest")
    fig.savefig(png_path, dpi=100, transparent=transparent, pad_inches=0)
    plt.close(fig)
    print(f"  [OK] PNG saved: {png_path.name} ({n_lat}x{n_lon})")


def _write_bounds(bounds_path: Path, layer_id: str, bounds: tuple[float, float, float, float]) -> None:
    """Write bounds JSON file."""
    bounds_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "layer_id": layer_id,
        "bounds": list(bounds),  # [west, south, east, north]
        "crs": "EPSG:4326",
    }
    bounds_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  [OK] bounds saved: {bounds_path.name} (W{bounds[0]:.1f} S{bounds[1]:.1f} E{bounds[2]:.1f} N{bounds[3]:.1f})")


# ──────────────────────────────────────────────────────────────────────────────
# 1. DEM ETOPO_2022
# ──────────────────────────────────────────────────────────────────────────────

def export_dem_etopo() -> None:
    print("\n=== DEM ETOPO_2022 ===")
    tif_path = Path(r"I:\Geograph_DataSet\DEM\ETOPO_2022\ETOPO_2022_v1_60s_N90W180_surface.tif")
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

    print(f"  Data shape: {data.shape}, range: {np.nanmin(data):.1f} to {np.nanmax(data):.1f}")
    _render_png(data, out_dir / "etopo_bed_overlay.png", cmap="terrain",
                vmin=-8000, vmax=8000)
    _write_bounds(out_dir / "etopo_bed_overlay_bounds.json", "dem-etopo",
                  (float(west), float(south), float(east), float(north)))


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
    stage2 = Path(r"I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion\stage2_aligned")
    out_dir = _OUT_ROOT / "thematic"
    bounds = _CHINA_BBOX

    # Landcover
    lc_path = stage2 / "landcover_025.mat"
    if lc_path.exists():
        m = _read_mat_v5(lc_path)
        data = m["landcover"].astype(np.float64)
        # Replace 0 (water/fill) with NaN
        data[data == 0] = np.nan
        print(f"  landcover: {data.shape}, classes: {np.nanmin(data):.0f}-{np.nanmax(data):.0f}")
        _render_png(data, out_dir / "landcover_overlay.png", cmap="nipy_spectral",
                    vmin=1, vmax=17)
        _write_bounds(out_dir / "landcover_overlay_bounds.json", "landcover-cn", bounds)
    else:
        print("  [SKIP] landcover not found")

    # HFP
    hfp_path = stage2 / "hfp_025.mat"
    if hfp_path.exists():
        m = _read_mat_v5(hfp_path)
        data = m["hfp"].astype(np.float64)
        print(f"  hfp: {data.shape}, range: {np.nanmin(data):.2f}-{np.nanmax(data):.2f}")
        _render_png(data, out_dir / "hfp_overlay.png", cmap="hot",
                    vmin=0, vmax=50)
        _write_bounds(out_dir / "hfp_overlay_bounds.json", "hfp-cn", bounds)
    else:
        print("  [SKIP] hfp not found")

    # Aridity
    ar_path = stage2 / "aridity_025.mat"
    if ar_path.exists():
        m = _read_mat_v5(ar_path)
        data = m["aridity"].astype(np.float64)
        print(f"  aridity: {data.shape}, range: {np.nanmin(data):.3f}-{np.nanmax(data):.3f}")
        _render_png(data, out_dir / "aridity_overlay.png", cmap="BrBG",
                    vmin=0, vmax=2)
        _write_bounds(out_dir / "aridity_overlay_bounds.json", "aridity-cn", bounds)
    else:
        print("  [SKIP] aridity not found")


# ──────────────────────────────────────────────────────────────────────────────
# 5. Omega inversion result
# ──────────────────────────────────────────────────────────────────────────────

def export_omega() -> None:
    print("\n=== Omega inversion ===")
    omega_path = Path(r"I:\Geograph_DataSet\InversionResults\smap_avg\doy_017.mat")
    if not omega_path.exists():
        print("  [SKIP] File not found")
        return

    out_dir = _OUT_ROOT / "omega"
    m = _read_mat_auto(omega_path)
    data = m["OMEGA_AVG"].astype(np.float64)
    # Replace 0 / invalid with NaN
    data[data <= 0] = np.nan
    # Also mask count_grid == 0 if available
    if "count_grid" in m:
        count = m["count_grid"]
        data[count == 0] = np.nan

    print(f"  omega: {data.shape}, range: {np.nanmin(data):.4f}-{np.nanmax(data):.4f}")
    # Clip extreme values for visualization
    vmax = float(np.nanpercentile(data, 99))
    _render_png(data, out_dir / "omega_avg_overlay.png", cmap="plasma",
                vmin=0, vmax=vmax)
    # EASE-Grid 2.0 global: lat -90 to 90, lon -180 to 180
    _write_bounds(out_dir / "omega_avg_overlay_bounds.json", "omega-output",
                  (-180.0, -90.0, 180.0, 90.0))


# ──────────────────────────────────────────────────────────────────────────────
# 6. SMAP soil moisture time series
# ──────────────────────────────────────────────────────────────────────────────

def export_smap_ts() -> None:
    print("\n=== SMAP SM time series ===")
    smap_dir = Path(r"I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion\stage1_smap_mat")
    if not smap_dir.exists():
        print("  [SKIP] Directory not found")
        return

    out_dir = _OUT_ROOT / "smap_ts"
    bounds = _CHINA_BBOX
    files = sorted(smap_dir.glob("SMAP_L3_SM_P_*.mat"))
    print(f"  Found {len(files)} SMAP .mat files")

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
            coord_keys = {"lat", "lon", "latitude", "longitude", "count_grid", "used_years", "ts", "tbh", "tbv", "vwc", "cf"}
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

        print(f"  {tag}: {data.shape}, key={sm_key}, range={np.nanmin(data):.3f}-{np.nanmax(data):.3f}")
        _render_png(data, out_dir / f"smap_sm_{tag}.png", cmap="YlGnBu",
                    vmin=0, vmax=0.5)
        _write_bounds(out_dir / f"smap_sm_{tag}_bounds.json", "smap-sm-ts", bounds)

    # Also write a generic bounds file
    _write_bounds(out_dir / "smap_sm_ts_bounds.json", "smap-sm-ts", bounds)


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
        _render_png(arr, out_dir / f"gpcp_{tag}.png", cmap="YlGnBu",
                    vmin=0, vmax=max(vmax, 10))
        _write_bounds(out_dir / f"gpcp_{tag}_bounds.json", "gpcp-precip-ts", bounds)

        ds.close()

    # Generic bounds
    _write_bounds(out_dir / "gpcp_ts_bounds.json", "gpcp-precip-ts",
                  (-180.0, -90.0, 180.0, 90.0))


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
        # 实际 bounds 用采样后的坐标
        lat_s = lat[lat_sl]
        lon_s = lon[lon_sl]
        actual_bounds = (float(lon_s.min()), float(lat_s.min()),
                         float(lon_s.max()), float(lat_s.max()))

    print(f"  Data shape: {data.shape}, range: {np.nanmin(data):.1f} to {np.nanmax(data):.1f}")
    _render_png(data, out_dir / "gebco_dem_overlay.png", cmap="terrain",
                vmin=-2000, vmax=6000)
    _write_bounds(out_dir / "gebco_dem_overlay_bounds.json", "gebco-dem-cn",
                  actual_bounds)


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
        data = src.read(1, out_shape=(src.height // scale, src.width // scale),
                        resampling=Resampling.average).astype(np.float64)
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = np.nan
        # int16, 单位 0.1mm, 转为 mm
        data = data / 10.0
        west, south, east, north = src.bounds

    print(f"  Data shape: {data.shape}, range: {np.nanmin(data):.1f} to {np.nanmax(data):.1f} mm")
    vmax = float(np.nanpercentile(data, 99))
    _render_png(data, out_dir / "cmfd_precip_overlay.png", cmap="YlGnBu",
                vmin=0, vmax=max(vmax, 10))
    _write_bounds(out_dir / "cmfd_precip_overlay_bounds.json", "cmfd-precip-cn",
                  (float(west), float(south), float(east), float(north)))


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
        data = src.read(1, window=win,
                        out_shape=(win.height // scale, win.width // scale),
                        resampling=Resampling.mode).astype(np.float64)
        # CLCD: 0=填充, 1-9 分类
        data[data == 0] = np.nan
        # 使用 window_bounds 获取窗口的地理边界 (west, south, east, north)
        # 注意: 不能用 xy(offset="ll")/xy(offset="ur"), 那样会取像素内边沿导致整体偏移 1 个像素
        actual_bounds = tuple(float(v) for v in src.window_bounds(win))

    print(f"  Data shape: {data.shape}, classes: {np.nanmin(data):.0f} to {np.nanmax(data):.0f}")
    _render_png(data, out_dir / "clcd_overlay.png", cmap="tab10",
                vmin=1, vmax=9)
    _write_bounds(out_dir / "clcd_overlay_bounds.json", "clcd-cn",
                  actual_bounds)


# ──────────────────────────────────────────────────────────────────────────────
# 11. ESACCI BIOMASS 2020 (NetCDF, 中国区域, 降采样)
# ──────────────────────────────────────────────────────────────────────────────

def export_biomass() -> None:
    print("\n=== ESACCI BIOMASS 2020 (China) ===")
    nc_path = Path(r"I:\Geograph_DataSet\Biomass\ESACCI-BIOMASS-L4-AGB-MERGED-100m-2020-fv6.0.nc")
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
        actual_bounds = (float(lon_s.min()), float(lat_s.min()),
                         float(lon_s.max()), float(lat_s.max()))

    print(f"  Data shape: {data.shape}, range: {np.nanmin(data):.1f} to {np.nanmax(data):.1f} Mg/ha")
    vmax = float(np.nanpercentile(data, 98))
    _render_png(data, out_dir / "biomass_overlay.png", cmap="YlGn",
                vmin=0, vmax=max(vmax, 50))
    _write_bounds(out_dir / "biomass_overlay_bounds.json", "biomass-cn",
                  actual_bounds)


# ──────────────────────────────────────────────────────────────────────────────
# 12. ERA5 DWAA/WDAA SMCI 2020 (GeoTIFF, 多波段事件标识, band 100)
# ──────────────────────────────────────────────────────────────────────────────

def export_era5_dwaa() -> None:
    print("\n=== ERA5 DWAA SMCI 2020 (event flag) ===")
    tif_path = Path(r"I:\Geograph_DataSet\Hazards\DWAA_result\DW_T7\ERA5_2020_DW_SMCI.tif")
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

    print(f"  Event count shape: {event_count.shape}, max events: {np.nanmax(event_count):.0f}")
    vmax = float(np.nanmax(event_count)) if np.isfinite(np.nanmax(event_count)) else 10
    _render_png(event_count, out_dir / "era5_dwaa_overlay.png", cmap="YlOrRd",
                vmin=1, vmax=max(vmax, 5))
    _write_bounds(out_dir / "era5_dwaa_overlay_bounds.json", "era5-dwaa-cn",
                  actual_bounds)


def export_era5_wdaa() -> None:
    print("\n=== ERA5 WDAA SMCI 2020 (event flag) ===")
    tif_path = Path(r"I:\Geograph_DataSet\Hazards\DWAA_result\WD_T7\ERA5_2020_WD_SMCI.tif")
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

    print(f"  Event count shape: {event_count.shape}, max events: {np.nanmax(event_count):.0f}")
    vmax = float(np.nanmax(event_count)) if np.isfinite(np.nanmax(event_count)) else 10
    _render_png(event_count, out_dir / "era5_wdaa_overlay.png", cmap="YlGnBu",
                vmin=1, vmax=max(vmax, 5))
    _write_bounds(out_dir / "era5_wdaa_overlay_bounds.json", "era5-wdaa-cn",
                  actual_bounds)


# ──────────────────────────────────────────────────────────────────────────────
# 13. MeanCarbonDioxide (GeoTIFF, 中国区域)
# ──────────────────────────────────────────────────────────────────────────────

def export_co2() -> None:
    print("\n=== MeanCarbonDioxide (China) ===")
    tif_path = Path(r"I:\Geograph_DataSet\CO2\MidLayerCO2Column\TIF\MeanCarbonDioxide.tif")
    if not tif_path.exists():
        print("  [SKIP] File not found")
        return

    import rasterio
    out_dir = _OUT_ROOT / "co2"
    bounds = _CHINA_BBOX

    with rasterio.open(tif_path) as src:
        data = src.read(1).astype(np.float64)
        west, south, east, north = src.bounds

    print(f"  Data shape: {data.shape}, range: {np.nanmin(data):.2f} to {np.nanmax(data):.2f} ppm")
    _render_png(data, out_dir / "co2_overlay.png", cmap="RdYlGn_r",
                vmin=386, vmax=391)
    _write_bounds(out_dir / "co2_overlay_bounds.json", "co2-cn",
                  (float(west), float(south), float(east), float(north)))


# ──────────────────────────────────────────────────────────────────────────────
# 14. Soil DDCA (MAT, 中国 9km)
# ──────────────────────────────────────────────────────────────────────────────

def export_soil_ddca() -> None:
    print("\n=== Soil DDCA (China 9km) ===")
    mat_path = Path(r"I:\Geograph_DataSet\Soil_Ecological_Data\DDCA\DDCA_DH\H\20150401.mat")
    if not mat_path.exists():
        print("  [SKIP] File not found")
        return

    out_dir = _OUT_ROOT / "soil_ddca"
    # DDCA 9km EASE-Grid: lat -90 to 90, lon -180 to 180
    bounds = (-180.0, -90.0, 180.0, 90.0)

    m = _read_mat_auto(mat_path)
    if "DH" not in m:
        print(f"  [SKIP] Variable DH not found, keys: {list(m.keys())}")
        return
    data = m["DH"].astype(np.float64)
    data[data < 0] = np.nan

    print(f"  Data shape: {data.shape}, range: {np.nanmin(data):.2f} to {np.nanmax(data):.2f}")
    vmax = float(np.nanpercentile(data, 99))
    _render_png(data, out_dir / "soil_ddca_overlay.png", cmap="viridis",
                vmin=0, vmax=max(vmax, 1))
    _write_bounds(out_dir / "soil_ddca_overlay_bounds.json", "soil-ddca",
                  bounds)


# ──────────────────────────────────────────────────────────────────────────────
# 15. InversionResults fy_avg omega (MAT, 全球 9km)
# ──────────────────────────────────────────────────────────────────────────────

def export_omega_fy() -> None:
    print("\n=== Omega FY avg (doy 025) ===")
    mat_path = Path(r"I:\Geograph_DataSet\InversionResults\fy_avg\doy_025.mat")
    if not mat_path.exists():
        print("  [SKIP] File not found")
        return

    out_dir = _OUT_ROOT / "omega_fy"
    bounds = (-180.0, -90.0, 180.0, 90.0)

    m = _read_mat_auto(mat_path)
    if "OMEGA_AVG" not in m:
        print(f"  [SKIP] Variable OMEGA_AVG not found")
        return
    data = m["OMEGA_AVG"].astype(np.float64)
    data[data <= 0] = np.nan
    if "count_grid" in m:
        count = m["count_grid"]
        data[count == 0] = np.nan

    print(f"  Data shape: {data.shape}, range: {np.nanmin(data):.4f} to {np.nanmax(data):.4f}")
    vmax = float(np.nanpercentile(data, 99))
    _render_png(data, out_dir / "omega_fy_overlay.png", cmap="magma",
                vmin=0, vmax=vmax)
    _write_bounds(out_dir / "omega_fy_overlay_bounds.json", "omega-fy-output",
                  bounds)


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
    bounds = (-180.0, -90.0, 180.0, 90.0)

    m = _read_mat_auto(mat_path)
    if "Forest_Ratio" not in m:
        print(f"  [SKIP] Variable Forest_Ratio not found")
        return
    data = m["Forest_Ratio"].astype(np.float64)
    data[data < 0] = np.nan

    print(f"  Data shape: {data.shape}, range: {np.nanmin(data):.3f} to {np.nanmax(data):.3f}")
    _render_png(data, out_dir / "forest_ratio_overlay.png", cmap="YlGn",
                vmin=0, vmax=1)
    _write_bounds(out_dir / "forest_ratio_overlay_bounds.json", "forest-ratio",
                  bounds)


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
        ("Omega", export_omega),
        ("SMAP TS", export_smap_ts),
        ("GPCP TS", export_gpcp_ts),
        ("GEBCO DEM", export_gebco_dem),
        ("CMFD Precip", export_cmfd_precip),
        ("CLCD", export_clcd),
        ("BIOMASS", export_biomass),
        ("ERA5 DWAA", export_era5_dwaa),
        ("ERA5 WDAA", export_era5_wdaa),
        ("CO2", export_co2),
        ("Soil DDCA", export_soil_ddca),
        ("Omega FY", export_omega_fy),
        ("Forest Ratio", export_forest_ratio),
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
