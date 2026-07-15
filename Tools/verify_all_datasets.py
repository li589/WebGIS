"""验证所有数据集的通用读取能力与数据质量。

对 I:\\Geograph_DataSet\\ 下每个数据集使用 UniversalDataReader 进行:
  1. 格式检测与变量列表
  2. 中国区域裁剪读取 (bbox=[73, 15, 137, 59])
  3. 数据统计 (min/max/mean/std/NaN占比)
  4. 坐标范围检查 (lat/lon 覆盖)
  5. 已知问题检测 (异常值/填充值/时间格式)

输出: 控制台报告 + Tools/reports/dataset_verification.json
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# 强制 stdout 使用 UTF-8，避免 Windows PowerShell GBK 乱码
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import numpy as np

# 添加 Code 目录到 sys.path
CODE_ROOT = Path(__file__).resolve().parent.parent / "Code"
sys.path.insert(0, str(CODE_ROOT / "algorithms" / "providers" / "Python" / "data_access"))

from universal_reader import UniversalDataReader, DataArray, CHINA_BBOX

DATA_ROOT = Path("I:/Geograph_DataSet")
REPORT_PATH = Path(__file__).resolve().parent / "reports" / "dataset_verification.json"


def fmt_stat(values: np.ndarray) -> dict:
    """计算数据统计信息。"""
    finite = values[np.isfinite(values)]
    total = values.size
    nan_count = total - finite.size
    if finite.size == 0:
        return {"total_pixels": int(total), "nan_count": int(nan_count), "nan_ratio": 1.0}
    return {
        "total_pixels": int(total),
        "valid_pixels": int(finite.size),
        "nan_count": int(nan_count),
        "nan_ratio": round(nan_count / total, 4) if total > 0 else 0,
        "min": round(float(finite.min()), 4),
        "max": round(float(finite.max()), 4),
        "mean": round(float(finite.mean()), 4),
        "std": round(float(finite.std()), 4),
    }


def fmt_coord(arr: np.ndarray | None, name: str) -> dict:
    """格式化坐标信息。"""
    if arr is None:
        return {f"{name}_available": False}
    finite = arr[np.isfinite(arr)] if arr.dtype.kind == "f" else arr
    if finite.size == 0:
        return {f"{name}_available": False}
    shape = list(arr.shape)
    return {
        f"{name}_available": True,
        f"{name}_shape": shape,
        f"{name}_min": round(float(finite.min()), 4),
        f"{name}_max": round(float(finite.max()), 4),
        f"{name}_ndim": arr.ndim,
    }


def verify_dataset(
    label: str,
    file: str,
    variable: str | None = None,
    bbox: tuple[float, float, float, float] | None = CHINA_BBOX,
    time_index: int | None = None,
    band: int = 1,
    skip_china: bool = False,
) -> dict:
    """验证单个数据集。"""
    result = {"label": label, "file": file, "status": "pending"}
    try:
        reader = UniversalDataReader(file)
        result["format"] = reader.format
        all_vars = reader.list_variables()
        result["variables"] = all_vars[:20]  # 限制前20个

        # MAT 文件: 如果 variable 为 None, 自动选择第一个数据变量
        actual_variable = variable
        if actual_variable is None and reader.format == "mat":
            coord_names = {"lat", "latitude", "lon", "longitude", "time"}
            data_vars = [v for v in all_vars if v.lower() not in coord_names]
            if data_vars:
                actual_variable = data_vars[0]
            else:
                actual_variable = all_vars[0] if all_vars else None

        # 读取数据
        data = reader.read_variable(
            variable=actual_variable,
            bbox=bbox if not skip_china else None,
            time_index=time_index,
            band=band,
        )

        result["var_name"] = data.var_name
        result["shape"] = list(data.values.shape)
        result["crs"] = data.crs
        result["stats"] = fmt_stat(data.values)
        result.update(fmt_coord(data.lat, "lat"))
        result.update(fmt_coord(data.lon, "lon"))
        if data.time is not None:
            result["time_available"] = True
            result["time_count"] = len(data.time) if hasattr(data.time, "__len__") else 1
            result["time_first"] = str(data.time[0]) if len(data.time) > 0 else None
            result["time_last"] = str(data.time[-1]) if len(data.time) > 0 else None
        else:
            result["time_available"] = False

        result["attrs"] = {k: str(v)[:100] for k, v in data.attrs.items() if not isinstance(v, (dict, list))}
        result["status"] = "ok"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc().split("\n")[-3:]

    return result


def main():
    datasets = [
        # ── 已在 Omega 项目中验证的数据集（快速确认） ──
        {
            "label": "SMAP L3 SM P (HDF5)",
            "file": str(DATA_ROOT / "SMAP" / "SMAP_L3_SM_P_20230110_R18290_001.h5"),
            "variable": "Soil_Moisture_Retrieval_Data_AM/soil_moisture",
        },
        {
            "label": "MCD12Q1 LandCover 2020 (GeoTIFF)",
            "file": str(DATA_ROOT / "LandCover" / "MCD12Q1_2020.tif"),
            "variable": None,
        },
        {
            "label": "HFP 2020 (GeoTIFF)",
            "file": str(DATA_ROOT / "HumanFootprint" / "hfp2020.tif"),
            "variable": None,
        },
        {
            "label": "InversionResults smap_avg doy_017 (MAT)",
            "file": str(DATA_ROOT / "InversionResults" / "smap_avg" / "doy_017.mat"),
            "variable": "omega",
        },

        # ── 待验证数据集 ──
        # DEM
        {
            "label": "GEBCO 2024 DEM (NetCDF)",
            "file": str(DATA_ROOT / "DEM" / "GEBCO_2024.nc"),
            "variable": "elevation",
        },
        {
            "label": "Italy DEM GEBCO2024 (GeoTIFF)",
            "file": str(DATA_ROOT / "DEM" / "Italy_GEBCO2024" / "Italy_DEM_GEBCO2024.tif"),
            "variable": None,
            "skip_china": True,  # 意大利区域，不裁剪中国
        },

        # Precipitation / CMFD
        {
            "label": "CMFD Precipitation 2002-01 (GeoTIFF)",
            "file": str(DATA_ROOT / "Precipitation" / "pre_2002_01.tif"),
            "variable": None,
        },
        {
            "label": "CMFD Precipitation 2002-02 (GeoTIFF)",
            "file": str(DATA_ROOT / "Precipitation" / "pre_2002_02.tif"),
            "variable": None,
        },

        # LandCover - CLCD
        {
            "label": "CLCD 1997 (GeoTIFF)",
            "file": str(DATA_ROOT / "LandCover" / "CLCD_v01_1997.tif"),
            "variable": None,
        },

        # BIOMASS (大文件, 只读中国区域)
        {
            "label": "ESACCI BIOMASS 2020 (NetCDF, 17.3GB)",
            "file": str(DATA_ROOT / "Biomass" / "ESACCI-BIOMASS-L4-AGB-MERGED-100m-2020-fv6.0.nc"),
            "variable": "agb",
        },

        # ERA5 DWAA SMCI (GeoTIFF)
        {
            "label": "ERA5 DWAA SMCI 2020 (GeoTIFF)",
            "file": str(DATA_ROOT / "Hazards" / "DWAA_result" / "DW_T7" / "ERA5_2020_DW_SMCI.tif"),
            "variable": None,
        },
        {
            "label": "ERA5 WDAA SMCI 2020 (GeoTIFF)",
            "file": str(DATA_ROOT / "Hazards" / "DWAA_result" / "WD_T7" / "ERA5_2020_WD_SMCI.tif"),
            "variable": None,
        },

        # CO2
        {
            "label": "MeanCarbonDioxide (GeoTIFF)",
            "file": str(DATA_ROOT / "CO2" / "MidLayerCO2Column" / "TIF" / "MeanCarbonDioxide.tif"),
            "variable": None,
        },

        # Soil Ecological Data (MAT)
        {
            "label": "Soil DDCA 20150401 (MAT)",
            "file": str(DATA_ROOT / "Soil_Ecological_Data" / "DDCA" / "DDCA_DH" / "H" / "20150401.mat"),
            "variable": None,  # 先列出变量
        },

        # InversionResults fy_avg
        {
            "label": "InversionResults fy_avg doy_025 (MAT)",
            "file": str(DATA_ROOT / "InversionResults" / "fy_avg" / "doy_025.mat"),
            "variable": None,
        },

        # Forest Ratio
        {
            "label": "Forest_Ratio_9KM_2020 (MAT)",
            "file": str(DATA_ROOT / "InversionResults" / "Forest_Ratio_9KM_2020.mat"),
            "variable": None,
        },
    ]

    results = []
    print("=" * 80)
    print("数据集通用读取验证报告")
    print(f"数据根目录: {DATA_ROOT}")
    print(f"中国区域 bbox: {CHINA_BBOX}")
    print("=" * 80)

    for i, ds in enumerate(datasets, 1):
        label = ds.pop("label")
        print(f"\n[{i}/{len(datasets)}] {label}")
        print(f"  文件: {ds['file']}")

        result = verify_dataset(label=label, **ds)
        results.append(result)

        if result["status"] == "ok":
            stats = result.get("stats", {})
            print(f"  格式: {result['format']} | 变量: {result.get('var_name', '—')}")
            print(f"  形状: {result['shape']} | CRS: {result.get('crs', '—')}")
            if "valid_pixels" in stats:
                print(f"  有效: {stats['valid_pixels']}/{stats['total_pixels']} ({1-stats['nan_ratio']:.1%})")
                print(f"  值域: [{stats['min']}, {stats['max']}] | 均值: {stats['mean']} | 标准差: {stats['std']}")
            if result.get("lat_available"):
                print(f"  纬度: [{result['lat_min']}, {result['lat_max']}] shape={result['lat_shape']}")
            if result.get("lon_available"):
                print(f"  经度: [{result['lon_min']}, {result['lon_max']}] shape={result['lon_shape']}")
            if result.get("time_available"):
                print(f"  时间: {result.get('time_count', 0)} 步 | 首={result.get('time_first')} | 末={result.get('time_last')}")
            var_list = result.get("variables", [])
            if var_list:
                print(f"  变量列表({len(var_list)}): {var_list[:8]}")
        else:
            print(f"  ❌ 错误: {result.get('error', 'unknown')}")

    # 保存 JSON 报告
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n{'=' * 80}")
    print(f"验证完成! 报告已保存: {REPORT_PATH}")

    # 汇总统计
    ok_count = sum(1 for r in results if r["status"] == "ok")
    err_count = sum(1 for r in results if r["status"] == "error")
    print(f"成功: {ok_count}/{len(results)} | 失败: {err_count}/{len(results)}")

    if err_count > 0:
        print("\n失败数据集:")
        for r in results:
            if r["status"] == "error":
                print(f"  - {r['label']}: {r.get('error', 'unknown')}")


if __name__ == "__main__":
    main()
