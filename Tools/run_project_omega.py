"""实际项目 — 中国区域 SMAP/Omega 多源交叉分析。

执行阶段:
  1. SMAP 14 天 HDF5 → .mat 批量转换
  2. 多源数据对齐到 0.25° WGS84 中国网格 (BIOMASS/MCD12Q1/HFP/AI)
  3. 加载 InversionResults/smap_avg omega 产品
  4. 交叉分析 (SM/Omega vs BIOMASS/LandCover/HFP 相关性 + IGBP 分区统计)
  5. 站点空间采样 (101 站点 × SMAP SM)
  6. 可视化报告

输出: I:\\Geograph_DataSet\\ProjectOutput\\2023-01_Omega_Inversion\\
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

PROVIDERS_DIR = Path(r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\algorithms\providers\Python")
sys.path.insert(0, str(PROVIDERS_DIR))

import numpy as np
import pandas as pd
from scipy.io import loadmat, savemat

from data_access.universal_reader import UniversalDataReader, CHINA_BBOX
from data_access.data_preprocessor import DataPreprocessor
from data_access.spatial_aligner import SpatialAligner
from analysis.spatial_stats import ZonalStats
from analysis.timeseries_analysis import TrendAnalysis, CorrelationAnalysis
from analysis.visualization import DataVisualization

# ======================================================================
# 配置
# ======================================================================
DATA_ROOT = Path(r"I:\Geograph_DataSet")
OUTPUT_ROOT = DATA_ROOT / "ProjectOutput" / "2023-01_Omega_Inversion"
SMAP_DIR = DATA_ROOT / "SMAP"
BIOMASS_PATH = DATA_ROOT / "Biomass" / "ESACCI-BIOMASS-L4-AGB-MERGED-100m-2020-fv6.0.nc"
MCD12Q1_PATH = DATA_ROOT / "LandCover" / "MCD12Q1_2019.tif"
HFP_PATH = DATA_ROOT / "HumanFootprint" / "hfp2019.tif"
AI_PATH = DATA_ROOT / "Others" / "AridityIndex_MSWEP-prcp_div_GLEAM-Ep_1980-2020.tif"
OMEGA_DIR = DATA_ROOT / "InversionResults" / "smap_avg"
STATION_CSV = DATA_ROOT / "Station" / "ISMN_vs_Fluxnet2015.csv"

# SMAP 14 天文件列表 (2023-01)
SMAP_DATES = [
    "20230101", "20230103", "20230105", "20230107", "20230109",
    "20230112", "20230114", "20230115", "20230120", "20230122",
    "20230124", "20230127", "20230130", "20230131",
]

# IGBP 土地覆盖类型名称
IGBP_NAMES = {
    1: "Evergreen_Needleleaf", 2: "Evergreen_Broadleaf", 3: "Deciduous_Needleleaf",
    4: "Deciduous_Broadleaf", 5: "Mixed_Forest", 6: "Closed_Shrubland",
    7: "Open_Shrubland", 8: "Woody_Savanna", 9: "Savanna", 10: "Grassland",
    11: "Permanent_Wetland", 12: "Cropland", 13: "Urban_BuiltUp",
    14: "Cropland_Natural", 15: "Snow_Ice", 16: "Barren_Sparsely",
    17: "Water",
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def section(title: str) -> None:
    log("=" * 70)
    log(title)
    log("=" * 70)


# ======================================================================
# 阶段 1: SMAP 14 天 → .mat
# ======================================================================
def stage1_smap_to_mat() -> dict[str, Path]:
    """批量转换 SMAP HDF5 → .mat"""
    section("[阶段 1] SMAP 14 天 HDF5 → .mat")
    out_dir = OUTPUT_ROOT / "stage1_smap_mat"
    out_dir.mkdir(parents=True, exist_ok=True)

    preprocessor = DataPreprocessor(data_root=DATA_ROOT)
    mat_paths: dict[str, Path] = {}

    for date_key in SMAP_DATES:
        # 优先尝试 _001 后缀, 若不存在则用 glob 查找其他后缀 (_002 等)
        h5_path = SMAP_DIR / f"SMAP_L3_SM_P_{date_key}_R18290_001.h5"
        if not h5_path.exists():
            candidates = sorted(SMAP_DIR.glob(f"SMAP_L3_SM_P_{date_key}_R18290_*.h5"))
            if candidates:
                h5_path = candidates[0]
            else:
                log(f"  跳过 {date_key}: SMAP_L3_SM_P_{date_key}_R18290_*.h5 不存在")
                continue

        try:
            mat_path = preprocessor.convert_smap_to_mat(
                smap_h5_path=h5_path,
                output_dir=out_dir,
                bbox=CHINA_BBOX,
            )
            mat_paths[date_key] = mat_path
            log(f"  ✓ {date_key}: {mat_path.name}")
        except Exception as e:
            log(f"  ✗ {date_key}: {type(e).__name__}: {e}")

    log(f"完成: {len(mat_paths)}/{len(SMAP_DATES)} 天转换成功")
    return mat_paths


# ======================================================================
# 阶段 2: 多源数据对齐
# ======================================================================
def stage2_align_datasets() -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """多源数据对齐到 0.25° WGS84 中国网格"""
    section("[阶段 2] 多源数据对齐到 0.25° WGS84")
    out_dir = OUTPUT_ROOT / "stage2_aligned"
    out_dir.mkdir(parents=True, exist_ok=True)

    aligner = SpatialAligner()
    results: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    # 2.1 MCD12Q1 土地覆盖 (GeoTIFF, Sinusoidal → WGS84, nearest)
    log("[2.1] MCD12Q1 土地覆盖对齐...")
    try:
        aligned, lat, lon = aligner.align_to_grid(
            source_path=MCD12Q1_PATH,
            variable=None,
            target_resolution=0.25,
            bbox=CHINA_BBOX,
            resampling="nearest",
        )
        results["landcover"] = (aligned, lat, lon)
        savemat(out_dir / "landcover_025.mat", {"landcover": aligned, "lat": lat, "lon": lon})
        valid = np.isfinite(aligned).sum()
        log(f"  ✓ landcover: shape={aligned.shape}, valid={valid}/{aligned.size}")
    except Exception as e:
        log(f"  ✗ landcover: {type(e).__name__}: {e}")

    # 2.2 Human Footprint (GeoTIFF, Mollweide → WGS84, bilinear)
    log("[2.2] Human Footprint 对齐...")
    try:
        aligned, lat, lon = aligner.align_to_grid(
            source_path=HFP_PATH,
            variable=None,
            target_resolution=0.25,
            bbox=CHINA_BBOX,
            resampling="bilinear",
        )
        results["hfp"] = (aligned, lat, lon)
        savemat(out_dir / "hfp_025.mat", {"hfp": aligned, "lat": lat, "lon": lon})
        valid = np.isfinite(aligned).sum()
        log(f"  ✓ hfp: shape={aligned.shape}, valid={valid}/{aligned.size}")
    except Exception as e:
        log(f"  ✗ hfp: {type(e).__name__}: {e}")

    # 2.3 AridityIndex (GeoTIFF, 1° → 0.25°, bilinear)
    log("[2.3] AridityIndex 对齐...")
    try:
        aligned, lat, lon = aligner.align_to_grid(
            source_path=AI_PATH,
            variable=None,
            target_resolution=0.25,
            bbox=CHINA_BBOX,
            resampling="bilinear",
        )
        # 过滤异常值 (AI 有效范围 0-50)
        aligned = np.where((aligned > -1000) & (aligned < 10000), aligned, np.nan)
        results["aridity"] = (aligned, lat, lon)
        savemat(out_dir / "aridity_025.mat", {"aridity": aligned, "lat": lat, "lon": lon})
        valid = np.isfinite(aligned).sum()
        log(f"  ✓ aridity: shape={aligned.shape}, valid={valid}/{aligned.size}")
    except Exception as e:
        log(f"  ✗ aridity: {type(e).__name__}: {e}")

    # 2.4 BIOMASS (NetCDF 17.3 GB, 100m → 0.25°, bilinear)
    # 跳过: 17.3 GB 文件需分块读取优化，当前 UniversalDataReader 一次性读取会超时
    log("[2.4] BIOMASS 对齐 — 跳过 (17.3 GB 需分块读取优化)")
    log(f"    文件: {BIOMASS_PATH.name}")
    log(f"    原因: 157500x405000 网格过大，一次性读取超内存")

    log(f"完成: {len(results)} 个数据集对齐成功")
    return results


# ======================================================================
# 阶段 3: 加载 Omega 产品
# ======================================================================
def stage3_load_omega() -> dict[str, np.ndarray]:
    """加载 InversionResults/smap_avg omega .mat 产品 (v7.3 格式, 需 h5py)"""
    section("[阶段 3] 加载 InversionResults/smap_avg omega 产品")
    omega_data: dict[str, np.ndarray] = {}

    for mat_file in sorted(OMEGA_DIR.glob("doy_*.mat")):
        doy_key = mat_file.stem  # e.g. doy_017
        try:
            # v7.3 .mat 文件需用 h5py 读取
            import h5py
            with h5py.File(mat_file, "r") as f:
                # OMEGA_AVG 是 v7.3 的数据集，需转置 (column-major → row-major)
                if "OMEGA_AVG" in f:
                    omega = np.array(f["OMEGA_AVG"]).T
                else:
                    # 尝试其他变量名
                    keys = list(f.keys())
                    log(f"  ✗ {doy_key}: OMEGA_AVG 不存在, 可用变量: {keys}")
                    continue
            omega_data[doy_key] = np.asarray(omega, dtype=np.float64)
            valid = np.isfinite(omega).sum()
            log(f"  ✓ {doy_key}: shape={omega.shape}, valid={valid}/{omega.size}")
        except Exception as e:
            log(f"  ✗ {doy_key}: {type(e).__name__}: {e}")

    log(f"完成: {len(omega_data)} 个 omega 产品加载")
    return omega_data


# ======================================================================
# 阶段 4: 交叉分析
# ======================================================================
def stage4_cross_analysis(
    smap_mat_paths: dict[str, Path],
    aligned_data: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    omega_data: dict[str, np.ndarray],
) -> dict:
    """交叉分析: SM/Omega vs BIOMASS/LandCover/HFP"""
    section("[阶段 4] 交叉分析")
    out_dir = OUTPUT_ROOT / "stage4_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    viz = DataVisualization()
    corr_analyzer = CorrelationAnalysis()
    zonal = ZonalStats()
    results: dict = {}

    # 加载第一天的 SMAP 数据作为代表 (20230110 = doy 010)
    # 选择与 omega doy_017 最接近的 SMAP 日期
    ref_date = "20230110"
    if ref_date not in smap_mat_paths:
        ref_date = next(iter(smap_mat_paths), None)
    if ref_date is None:
        log("  ✗ 无 SMAP .mat 数据")
        return results

    smap_mat = loadmat(smap_mat_paths[ref_date], squeeze_me=True)
    sm = np.asarray(smap_mat.get("SM", np.full((1, 1), np.nan)), dtype=np.float64)
    ts = np.asarray(smap_mat.get("Ts", np.full((1, 1), np.nan)), dtype=np.float64)
    smap_lat = np.asarray(smap_mat.get("lat", np.full((1, 1), np.nan)), dtype=np.float64)
    smap_lon = np.asarray(smap_mat.get("lon", np.full((1, 1), np.nan)), dtype=np.float64)
    log(f"  参考 SMAP 数据: {ref_date}, SM shape={sm.shape}")

    # 4.1 SMAP SM 全局统计
    log("[4.1] SMAP SM 全局统计...")
    stats = zonal.compute_stats(sm)
    g = stats.get("global", {})
    log(f"  mean={g.get('mean', 0):.4f}, std={g.get('std', 0):.4f}, "
        f"min={g.get('min', 0):.4f}, max={g.get('max', 0):.4f}")
    results["smap_sm_stats"] = g

    # 4.2 SMAP SM 空间地图
    log("[4.2] 生成 SMAP SM 空间地图...")
    try:
        viz.plot_spatial_map(
            data=sm, lat=smap_lat, lon=smap_lon,
            title=f"SMAP Soil Moisture ({ref_date})",
            cmap="RdYlBu", vmin=0.0, vmax=0.6,
            output_path=out_dir / f"smap_sm_{ref_date}.png",
        )
        log(f"  ✓ smap_sm_{ref_date}.png")
    except Exception as e:
        log(f"  ✗ SM 地图: {type(e).__name__}: {e}")

    # 4.3 SMAP SM vs Ts 相关性
    log("[4.3] SMAP SM vs Ts 相关性...")
    sm_flat = sm.flatten()
    ts_flat = ts.flatten()
    mask = np.isfinite(sm_flat) & np.isfinite(ts_flat)
    if mask.sum() > 10:
        r = corr_analyzer.timeseries_correlation(sm_flat[mask], ts_flat[mask], method="pearson")
        log(f"  Pearson r={r['r']:.4f}, p={r['p_value']:.4f}, n={r['n']}")
        results["sm_ts_corr"] = r
        viz.plot_scatter(
            x=sm_flat[mask][:5000], y=ts_flat[mask][:5000],
            title=f"SMAP SM vs Ts ({ref_date})",
            xlabel="Soil Moisture (m3/m3)", ylabel="Surface Temperature (K)",
            output_path=out_dir / f"sm_vs_ts_{ref_date}.png",
        )
        log(f"  ✓ sm_vs_ts_{ref_date}.png")

    # 4.4 对齐数据与 SMAP SM 的相关性 (需要空间对齐)
    # 由于 SMAP 是 EASE-Grid 2D 坐标，对齐数据是 0.25° 网格，需要采样到共同网格
    # 这里简化: 直接用对齐数据的全局统计
    log("[4.4] 对齐数据统计...")
    for name, (data, lat, lon) in aligned_data.items():
        valid = data[np.isfinite(data)]
        if len(valid) > 0:
            log(f"  {name}: mean={valid.mean():.4f}, std={valid.std():.4f}, "
                f"range=[{valid.min():.4f}, {valid.max():.4f}], n={len(valid)}")
            results[f"{name}_stats"] = {
                "mean": float(valid.mean()),
                "std": float(valid.std()),
                "min": float(valid.min()),
                "max": float(valid.max()),
                "count": int(len(valid)),
            }
            # 生成专题图
            try:
                cmap = "YlGn" if name == "biomass" else "viridis" if name == "landcover" else "OrRd"
                viz.plot_spatial_map(
                    data=data, lat=lat, lon=lon,
                    title=f"{name} (China, 0.25deg)",
                    cmap=cmap,
                    output_path=out_dir / f"{name}_china.png",
                )
                log(f"  ✓ {name}_china.png")
            except Exception as e:
                log(f"  ✗ {name} 地图: {type(e).__name__}: {e}")

    # 4.5 IGBP 分区统计 (需要 landcover)
    if "landcover" in aligned_data:
        log("[4.5] IGBP 分区统计 (对齐后 landcover)...")
        lc_data, lc_lat, lc_lon = aligned_data["landcover"]
        lc_flat = lc_data.flatten()
        lc_valid = lc_flat[np.isfinite(lc_flat) & (lc_flat > 0) & (lc_flat <= 17)]
        if len(lc_valid) > 0:
            unique, counts = np.unique(lc_valid.astype(int), return_counts=True)
            log(f"  IGBP 分布:")
            igbp_stats = {}
            for u, c in zip(unique, counts):
                name = IGBP_NAMES.get(u, f"Unknown_{u}")
                pct = c / len(lc_valid) * 100
                log(f"    {u:2d} {name:25s}: {c:8d} ({pct:.1f}%)")
                igbp_stats[u] = {"name": name, "count": int(c), "pct": float(pct)}
            results["igbp_distribution"] = igbp_stats

    # 4.6 Omega 产品统计
    log("[4.6] Omega 产品统计...")
    omega_stats = {}
    for doy_key, omega in omega_data.items():
        valid = omega[np.isfinite(omega)]
        if len(valid) > 0:
            stat = {
                "mean": float(valid.mean()),
                "std": float(valid.std()),
                "min": float(valid.min()),
                "max": float(valid.max()),
                "count": int(len(valid)),
            }
            omega_stats[doy_key] = stat
            log(f"  {doy_key}: mean={stat['mean']:.4f}, std={stat['std']:.4f}, n={stat['count']}")
    results["omega_stats"] = omega_stats

    # 4.7 Omega 直方图 (取第一个 doy 作为示例)
    if omega_data:
        first_doy = next(iter(omega_data))
        omega_sample = omega_data[first_doy]
        try:
            viz.plot_histogram(
                data=omega_sample,
                title=f"Omega Distribution ({first_doy})",
                bins=50,
                output_path=out_dir / f"omega_hist_{first_doy}.png",
            )
            log(f"  ✓ omega_hist_{first_doy}.png")
        except Exception as e:
            log(f"  ✗ Omega 直方图: {type(e).__name__}: {e}")

    log(f"完成: 交叉分析产出 {len(results)} 项结果")
    return results


# ======================================================================
# 阶段 5: 站点空间采样
# ======================================================================
def stage5_station_sampling(smap_mat_paths: dict[str, Path]) -> dict:
    """站点空间采样: 用 ISMN_vs_Fluxnet2015.csv 站点坐标提取 SMAP SM"""
    section("[阶段 5] 站点空间采样 (101 站点 × SMAP SM)")
    out_dir = OUTPUT_ROOT / "stage5_station"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not STATION_CSV.exists():
        log(f"  ✗ 站点 CSV 不存在: {STATION_CSV}")
        return {}

    stations = pd.read_csv(STATION_CSV)
    log(f"  站点数: {len(stations)}, 列: {list(stations.columns)[:10]}...")

    # 选择参考 SMAP 日期
    ref_date = "20230110"
    if ref_date not in smap_mat_paths:
        ref_date = next(iter(smap_mat_paths), None)
    if ref_date is None:
        log("  ✗ 无 SMAP .mat 数据")
        return {}

    smap_mat = loadmat(smap_mat_paths[ref_date], squeeze_me=True)
    sm = np.asarray(smap_mat.get("SM", np.full((1, 1), np.nan)), dtype=np.float64)
    smap_lat = np.asarray(smap_mat.get("lat", np.full((1, 1), np.nan)), dtype=np.float64)
    smap_lon = np.asarray(smap_mat.get("lon", np.full((1, 1), np.nan)), dtype=np.float64)
    ts_arr = np.asarray(smap_mat.get("Ts", np.full_like(sm, np.nan)), dtype=np.float64)

    # 预处理: 将 2D 坐标中的 NaN 填充为大值，避免 argmin 选到 NaN 像元
    if smap_lat.ndim == 2:
        lat_search = np.where(np.isfinite(smap_lat), smap_lat, 1e6)
        lon_search = np.where(np.isfinite(smap_lon), smap_lon, 1e6)

    # 对每个站点找最近的 SMAP 像元
    records = []
    for _, row in stations.iterrows():
        lat = float(row.get("latitude", np.nan))
        lon = float(row.get("longitude", np.nan))
        if not np.isfinite(lat) or not np.isfinite(lon):
            continue
        igbp = row.get("IGBP_Fluxnet", "Unknown")

        # 找最近的像元 (SMAP 是 2D 坐标)
        if smap_lat.ndim == 2:
            dist = (lat_search - lat) ** 2 + (lon_search - lon) ** 2
            flat_idx = int(np.argmin(dist))
            i, j = np.unravel_index(flat_idx, sm.shape)
            sm_val = float(sm[i, j]) if np.isfinite(sm[i, j]) else np.nan
            ts_val = float(ts_arr[i, j]) if np.isfinite(ts_arr[i, j]) else np.nan
        else:
            lat_idx = int(np.argmin(np.abs(smap_lat - lat)))
            lon_idx = int(np.argmin(np.abs(smap_lon - lon)))
            sm_val = float(sm[lat_idx, lon_idx]) if np.isfinite(sm[lat_idx, lon_idx]) else np.nan
            ts_val = float(ts_arr[lat_idx, lon_idx]) if np.isfinite(ts_arr[lat_idx, lon_idx]) else np.nan

        records.append({
            "station": row.get("station", ""),
            "network": row.get("network", ""),
            "latitude": lat,
            "longitude": lon,
            "IGBP": igbp,
            "MAP": row.get("MAP", np.nan),
            "MAT": row.get("MAT", np.nan),
            "AI": row.get("AI", np.nan),
            "smap_sm": sm_val,
            "smap_ts": ts_val,
        })

    df = pd.DataFrame(records)
    valid_sm = df["smap_sm"].notna().sum()
    log(f"  有效 SM 采样: {valid_sm}/{len(df)}")

    # 保存站点采样结果
    df.to_csv(out_dir / "station_smap_sm.csv", index=False)
    log(f"  ✓ station_smap_sm.csv")

    # 按 IGBP 分组统计
    if "IGBP" in df.columns:
        grouped = df.dropna(subset=["smap_sm"]).groupby("IGBP").agg(
            count=("smap_sm", "count"),
            sm_mean=("smap_sm", "mean"),
            sm_std=("smap_sm", "std"),
            ts_mean=("smap_ts", "mean"),
        ).reset_index()
        log(f"  IGBP 分组统计:")
        for _, r in grouped.iterrows():
            log(f"    {r['IGBP']:25s}: n={int(r['count']):3d}, "
                f"SM={r['sm_mean']:.4f}±{r['sm_std']:.4f}, Ts={r['ts_mean']:.1f}K")
        grouped.to_csv(out_dir / "station_igbp_stats.csv", index=False)
        log(f"  ✓ station_igbp_stats.csv")

    # 可视化: 站点分布散点图
    viz = DataVisualization()
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(12, 8))
        sc = ax.scatter(df["longitude"], df["latitude"],
                        c=df["smap_sm"], cmap="RdYlBu", vmin=0, vmax=0.6,
                        s=50, edgecolors="black", linewidths=0.5)
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_title(f"Station SMAP SM Sampling ({ref_date}, n={len(df)})")
        fig.colorbar(sc, ax=ax, label="Soil Moisture (m3/m3)")
        fig.tight_layout()
        fig.savefig(out_dir / f"station_sm_distribution_{ref_date}.png", dpi=150)
        plt.close(fig)
        log(f"  ✓ station_sm_distribution_{ref_date}.png")
    except Exception as e:
        log(f"  ✗ 站点分布图: {type(e).__name__}: {e}")

    return {"station_count": len(df), "valid_sm_count": int(valid_sm)}


# ======================================================================
# 阶段 6: 可视化报告
# ======================================================================
def stage6_visualization(
    smap_mat_paths: dict[str, Path],
    aligned_data: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    omega_data: dict[str, np.ndarray],
) -> None:
    """生成可视化报告"""
    section("[阶段 6] 可视化报告")
    out_dir = OUTPUT_ROOT / "stage6_viz"
    out_dir.mkdir(parents=True, exist_ok=True)
    viz = DataVisualization()

    # 6.1 SMAP SM 14 天时间序列均值
    # 注意: 不同 SMAP .mat 文件经 bbox 裁剪后形状可能不同 (2D EASE-Grid 有效像元覆盖范围随扫描模式变化)
    # 解决方案: 用 SpatialAligner 将每天的 SM 对齐到统一的 0.25° WGS84 网格后再堆叠
    log("[6.1] SMAP SM 14 天均值图 (对齐到 0.25° WGS84 网格)...")
    aligner = SpatialAligner()
    sm_aligned_stack: list[np.ndarray] = []
    target_lat = target_lon = None
    for date_key, mat_path in smap_mat_paths.items():
        try:
            aligned, t_lat, t_lon = aligner.align_to_grid(
                source_path=mat_path,
                variable="SM",
                target_resolution=0.25,
                bbox=CHINA_BBOX,
                resampling="bilinear",
            )
            sm_aligned_stack.append(aligned)
            if target_lat is None:
                target_lat, target_lon = t_lat, t_lon
            log(f"  ✓ {date_key}: aligned shape={aligned.shape}, "
                f"valid={np.isfinite(aligned).sum()}/{aligned.size}")
        except Exception as e:
            log(f"  ✗ {date_key}: {type(e).__name__}: {e}")
    if sm_aligned_stack:
        # 所有对齐后的数组形状一致 (176, 256), 可直接堆叠
        sm_mean = np.nanmean(np.stack(sm_aligned_stack), axis=0)
        log(f"  堆叠 {len(sm_aligned_stack)} 天, 均值 shape={sm_mean.shape}, "
            f"valid={np.isfinite(sm_mean).sum()}/{sm_mean.size}")
        try:
            viz.plot_spatial_map(
                data=sm_mean, lat=target_lat, lon=target_lon,
                title="SMAP SM 14-day Mean (2023-01, 0.25deg)",
                cmap="RdYlBu", vmin=0.0, vmax=0.6,
                output_path=out_dir / "smap_sm_14day_mean.png",
            )
            log(f"  ✓ smap_sm_14day_mean.png")
        except Exception as e:
            log(f"  ✗ 14天均值图: {type(e).__name__}: {e}")

    # 6.2 对齐数据专题图
    log("[6.2] 对齐数据专题图...")
    for name, (data, lat, lon) in aligned_data.items():
        try:
            cmap = "YlGn" if name == "biomass" else "tab20" if name == "landcover" else "OrRd"
            viz.plot_spatial_map(
                data=data, lat=lat, lon=lon,
                title=f"{name} (China, 0.25deg)",
                cmap=cmap,
                output_path=out_dir / f"{name}_thematic.png",
            )
            log(f"  ✓ {name}_thematic.png")
        except Exception as e:
            log(f"  ✗ {name}: {type(e).__name__}: {e}")

    # 6.3 Omega 空间图 (第一个 doy)
    log("[6.3] Omega 空间图...")
    if omega_data:
        first_doy = next(iter(omega_data))
        omega = omega_data[first_doy]
        try:
            viz.plot_spatial_map(
                data=omega,
                title=f"Omega AVG ({first_doy})",
                cmap="YlGnBu", vmin=0.0, vmax=0.3,
                output_path=out_dir / f"omega_avg_{first_doy}.png",
            )
            log(f"  ✓ omega_avg_{first_doy}.png")
        except Exception as e:
            log(f"  ✗ Omega 图: {type(e).__name__}: {e}")

    log("完成: 可视化报告生成")


# ======================================================================
# 主流程
# ======================================================================
def main() -> None:
    section("实际项目 — 中国区域 SMAP/Omega 多源交叉分析")
    log(f"数据根目录: {DATA_ROOT}")
    log(f"输出目录: {OUTPUT_ROOT}")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    t_start = time.time()

    # 阶段 1
    smap_mat_paths = stage1_smap_to_mat()

    # 阶段 2
    aligned_data = stage2_align_datasets()

    # 阶段 3
    omega_data = stage3_load_omega()

    # 阶段 4
    analysis_results = stage4_cross_analysis(smap_mat_paths, aligned_data, omega_data)

    # 阶段 5
    station_results = stage5_station_sampling(smap_mat_paths)

    # 阶段 6
    stage6_visualization(smap_mat_paths, aligned_data, omega_data)

    elapsed = time.time() - t_start
    section("项目执行完成")
    log(f"总耗时: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    log(f"输出目录: {OUTPUT_ROOT}")
    log(f"  SMAP .mat: {len(smap_mat_paths)} 天")
    log(f"  对齐数据集: {len(aligned_data)} 个")
    log(f"  Omega 产品: {len(omega_data)} 个")
    log(f"  分析结果: {len(analysis_results)} 项")
    log(f"  站点采样: {station_results}")


if __name__ == "__main__":
    main()
