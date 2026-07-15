"""全面检查已下载的数据，输出格式、变量、坐标等信息。

检查范围：
1. SMAP HDF5 - 土壤水分反演变量
2. omega .mat v7.3 - OMEGA_AVG 反演结果
3. CMFD NetCDF - 月度气象数据
4. MCD12Q1 GeoTIFF - 土地覆盖
5. CLCD GeoTIFF - 中国土地覆盖动态
6. China 1km GeoTIFF - 降水/温度
7. HFP GeoTIFF - 人类足迹
8. ISMN/FLUX CSV - 站点匹配
9. Landscape Metrics .mat - 景观指数
10. AridityIndex GeoTIFF - 干燥度指数
"""
from pathlib import Path
import json

ROOT = Path(r"I:\Geograph_DataSet")


def check_smap() -> dict:
    """检查 SMAP HDF5 文件。"""
    print("\n" + "=" * 70)
    print("1. SMAP HDF5 - 土壤水分数据")
    print("=" * 70)
    smap_dir = ROOT / "SMAP"
    files = sorted(smap_dir.glob("*.h5"))
    if not files:
        print("  无文件")
        return {"status": "no_files"}

    import h5py
    import numpy as np

    f = files[0]
    print(f"  文件: {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)")

    with h5py.File(f, "r") as h:
        # SMAP L3 结构
        print(f"  顶层 groups: {list(h.keys())}")

        # 查找 Soil_Moisture_Retrieval_Data
        target_groups = []
        for key in h.keys():
            if "Soil_Moisture_Retrieval_Data" in key:
                target_groups.append(key)

        variables = {}
        for gname in target_groups:
            g = h[gname]
            print(f"\n  [{gname}]")
            vars_in_g = []
            for vname in g.keys():
                v = g[vname]
                if hasattr(v, "shape"):
                    shape = v.shape
                    dtype = str(v.dtype)
                    # 读取部分数据统计
                    try:
                        data = v[:]
                        valid = data[data != v.fillvalue] if hasattr(v, "fillvalue") and v.fillvalue != 0 else data
                        if len(valid) > 0:
                            stats = f"min={valid.min():.4g}, max={valid.max():.4g}, mean={valid.mean():.4g}"
                        else:
                            stats = "all fillvalues"
                    except Exception:
                        stats = "N/A"
                    print(f"    {vname:<40} shape={str(shape):<20} dtype={dtype:<10} {stats}")
                    vars_in_g.append({
                        "name": vname,
                        "shape": list(shape),
                        "dtype": dtype,
                    })
            variables[gname] = vars_in_g

        # 检查关键反演变量
        print("\n  关键反演变量检查:")
        key_vars = [
            "soil_moisture", "surface_temperature", "tb_h_corrected", "tb_v_corrected",
            "vegetation_water_content", "clay_fraction", "sand_fraction",
            "static_water_body_fraction", "lat", "lon",
        ]
        found_keys = []
        for gname, vs in variables.items():
            for v in vs:
                if v["name"] in key_vars:
                    found_keys.append(v["name"])
        for kv in key_vars:
            mark = "OK" if kv in found_keys else "MISSING"
            print(f"    {kv:<40} {mark}")

    return {
        "status": "ok",
        "file": str(f),
        "groups": list(variables.keys()),
        "variables": variables,
        "key_vars_found": found_keys,
    }


def check_omega_mat() -> dict:
    """检查 omega .mat v7.3 文件。"""
    print("\n" + "=" * 70)
    print("2. omega .mat v7.3 - 反演结果")
    print("=" * 70)

    results = {}
    for subdir in ["smap_avg", "fy_avg"]:
        d = ROOT / "InversionResults" / subdir
        files = sorted(d.glob("doy_*.mat"))
        if not files:
            print(f"\n  [{subdir}] 无文件")
            results[subdir] = {"status": "no_files", "count": 0}
            continue

        print(f"\n  [{subdir}] {len(files)} 个文件")
        f = files[0]
        print(f"  文件: {f.name} ({f.stat().st_size / 1024 / 1024:.2f} MB)")

        import h5py
        import numpy as np

        with h5py.File(f, "r") as h:
            keys = list(h.keys())
            print(f"  变量: {keys}")
            vars_info = {}
            for k in keys:
                v = h[k]
                if hasattr(v, "shape"):
                    data = v[:]
                    # 过滤 NaN
                    valid = data[~np.isnan(data)] if data.dtype.kind == "f" else data
                    if len(valid) > 0:
                        stats = f"min={valid.min():.4g}, max={valid.max():.4g}, mean={valid.mean():.4g}"
                    else:
                        stats = "all NaN"
                    print(f"    {k:<20} shape={str(v.shape):<20} dtype={v.dtype}  {stats}")
                    vars_info[k] = {
                        "shape": list(v.shape),
                        "dtype": str(v.dtype),
                        "stats": stats,
                    }
            results[subdir] = {
                "status": "ok",
                "count": len(files),
                "file": str(f),
                "variables": vars_info,
            }

    return results


def check_cmfd_netcdf() -> dict:
    """检查 CMFD NetCDF 文件。"""
    print("\n" + "=" * 70)
    print("3. CMFD NetCDF - 月度气象数据")
    print("=" * 70)

    weather = ROOT / "Weather"
    files = sorted(weather.glob("*CMFD*.nc"))
    if not files:
        print("  无文件")
        return {"status": "no_files"}

    import netCDF4 as nc
    import numpy as np

    results = {}
    for f in files:
        print(f"\n  文件: {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)")
        with nc.Dataset(f) as ds:
            print(f"  全局属性:")
            for attr in list(ds.ncattrs())[:10]:
                print(f"    {attr}: {getattr(ds, attr)}")
            print(f"  维度: {dict((k, len(v)) for k, v in ds.dimensions.items())}")
            print(f"  变量:")
            for vname in ds.variables:
                v = ds.variables[vname]
                print(f"    {vname:<20} shape={v.shape} dtype={v.dtype}")
                for attr in list(v.ncattrs())[:5]:
                    print(f"      {attr}: {v.getncattr(attr)}")
            results[f.name] = {
                "dims": dict((k, len(v)) for k, v in ds.dimensions.items()),
                "variables": list(ds.variables.keys()),
            }

    return results


def check_geotiff(path: Path, title: str) -> dict:
    """检查 GeoTIFF 文件（使用 rasterio）。"""
    print(f"\n  [{title}] {path.name}")
    if not path.exists():
        print(f"    文件不存在")
        return {"status": "not_exists"}

    import rasterio
    import numpy as np
    from rasterio.crs import CRS

    try:
        ds = rasterio.open(str(path))
    except Exception as e:
        print(f"    打开失败: {e}")
        return {"status": "open_failed", "error": str(e)}

    if ds is None:
        print(f"    无法打开")
        return {"status": "open_failed"}

    w, h = ds.width, ds.height
    b = ds.count
    crs_obj = ds.crs
    gt = ds.transform

    # 识别坐标系
    crs_str = str(crs_obj) if crs_obj else "Unknown"
    if crs_obj and crs_obj.to_epsg() == 4326:
        crs = "EPSG:4326 (WGS84)"
    elif "Sinusoidal" in crs_str or (crs_obj and crs_obj.to_proj4() and "sinu" in crs_obj.to_proj4().lower()):
        crs = "Sinusoidal (MODIS)"
    else:
        crs = crs_str[:80]

    # 经纬度范围
    x_min = gt.c
    y_max = gt.f
    x_max = gt.c + w * gt.a
    y_min = gt.f + h * gt.e
    res_x = gt.a
    res_y = abs(gt.e)

    print(f"    尺寸: {w} x {h} x {b} band(s)")
    print(f"    坐标系: {crs}")
    if "4326" in crs:
        print(f"    分辨率: {res_x:.6f}° x {res_y:.6f}°")
    else:
        print(f"    分辨率: {res_x:.2f}m x {res_y:.2f}m")
    print(f"    范围: X=[{x_min:.4f}, {x_max:.4f}], Y=[{y_min:.4f}, {y_max:.4f}]")

    # 读取第一个 band 的统计
    try:
        arr = ds.read(1)
    except Exception as e:
        print(f"    读取数据失败: {e}")
        ds.close()
        return {"status": "read_failed", "error": str(e), "size": [w, h, b], "crs": crs}

    dtype = ds.dtypes[0]
    nodata = ds.nodata
    # 如果 NoData 未设置但数据类型是有符号整型，尝试检测 -32768 等常见填充值
    if nodata is None and arr.dtype.kind in ("i", "u"):
        if arr.dtype == np.int16 and arr.min() == -32768:
            nodata = -32768
        elif arr.dtype == np.int32 and arr.min() == -2147483648:
            nodata = -2147483648

    if nodata is not None:
        valid = arr[arr != nodata]
    else:
        valid = arr
    if len(valid) > 0:
        print(f"    数据类型: {dtype}")
        print(f"    NoData: {nodata}")
        print(f"    有效像素: {len(valid)} / {arr.size} ({100 * len(valid) / arr.size:.1f}%)")
        if valid.dtype.kind in ("f", "i", "u"):
            print(f"    值范围: min={valid.min()}, max={valid.max()}, mean={valid.mean():.4f}")

    ds.close()

    return {
        "status": "ok",
        "size": [w, h, b],
        "crs": crs,
        "resolution": [res_x, res_y],
        "bounds": [x_min, y_min, x_max, y_max],
        "dtype": dtype,
        "nodata": nodata,
        "valid_pixels": int(len(valid)),
        "total_pixels": int(arr.size),
    }


def check_geotiffs() -> dict:
    """检查所有 GeoTIFF 文件。"""
    print("\n" + "=" * 70)
    print("4. GeoTIFF 数据检查")
    print("=" * 70)

    results = {}

    # MCD12Q1
    print("\n  --- MCD12Q1 土地覆盖 ---")
    for f in sorted((ROOT / "LandCover").glob("MCD12Q1_*.tif")):
        year = f.stem.split("_")[-1]
        results[f"MCD12Q1_{year}"] = check_geotiff(f, f"MCD12Q1 {year}")

    # CLCD
    print("\n  --- CLCD 中国土地覆盖动态 ---")
    for f in sorted((ROOT / "LandCover").glob("CLCD_*.tif")):
        results[f.stem] = check_geotiff(f, f"CLCD")

    # China 1km 降水
    print("\n  --- China 1km 降水 ---")
    for f in sorted((ROOT / "Precipitation").glob("pre_*.tif")):
        results[f.stem] = check_geotiff(f, f"Precipitation")

    # China 1km 温度
    print("\n  --- China 1km 温度 ---")
    for f in sorted((ROOT / "Weather").glob("tmp_*.tif")):
        results[f.stem] = check_geotiff(f, f"Temperature")

    # HFP
    print("\n  --- Human Footprint ---")
    for f in sorted((ROOT / "HumanFootprint").glob("hfp*.tif")):
        results[f.stem] = check_geotiff(f, f"Human Footprint")

    # Aridity Index
    print("\n  --- Aridity Index ---")
    for f in sorted((ROOT / "Others").glob("AridityIndex*.tif")):
        results[f.stem] = check_geotiff(f, f"Aridity Index")

    return results


def check_csv() -> dict:
    """检查 CSV 文件。"""
    print("\n" + "=" * 70)
    print("5. CSV 数据检查")
    print("=" * 70)

    csv_file = ROOT / "Station" / "ISMN_vs_Fluxnet2015.csv"
    if not csv_file.exists():
        print("  文件不存在")
        return {"status": "not_exists"}

    import pandas as pd

    df = pd.read_csv(csv_file)
    print(f"  文件: {csv_file.name}")
    print(f"  行数: {len(df)}")
    print(f"  列数: {len(df.columns)}")
    print(f"  列名: {list(df.columns)}")
    print(f"  前 5 行:")
    print(df.head().to_string())

    return {
        "status": "ok",
        "rows": len(df),
        "columns": list(df.columns),
    }


def check_landscape_mat() -> dict:
    """检查 Landscape Metrics .mat 文件。"""
    print("\n" + "=" * 70)
    print("6. Landscape Metrics .mat - 景观指数")
    print("=" * 70)

    results = {}
    for fname in ["Landscape_Metrics_LandOnly_9KM_2020.mat", "Forest_Ratio_9KM_2020.mat"]:
        f = ROOT / "InversionResults" / fname
        if not f.exists():
            print(f"  {fname}: 不存在")
            results[fname] = {"status": "not_exists"}
            continue

        print(f"\n  文件: {fname} ({f.stat().st_size / 1024 / 1024:.1f} MB)")

        # 先试 scipy
        try:
            from scipy.io import loadmat
            import numpy as np

            data = loadmat(str(f))
            # 过滤 __ 开头的元数据
            vars = {k: v for k, v in data.items() if not k.startswith("__")}
            print(f"  格式: MAT v5 (scipy.io.loadmat)")
            print(f"  变量: {list(vars.keys())}")
            for k, v in vars.items():
                if hasattr(v, "shape"):
                    valid = v[~np.isnan(v)] if v.dtype.kind == "f" else v
                    if len(valid) > 0:
                        stats = f"min={valid.min():.4g}, max={valid.max():.4g}, mean={valid.mean():.4g}"
                    else:
                        stats = "all NaN"
                    print(f"    {k:<30} shape={str(v.shape):<20} dtype={v.dtype}  {stats}")
            results[fname] = {
                "status": "ok",
                "format": "v5",
                "variables": list(vars.keys()),
            }
        except NotImplementedError:
            # v7.3, 用 h5py
            import h5py
            import numpy as np

            with h5py.File(f, "r") as h:
                keys = list(h.keys())
                print(f"  格式: MAT v7.3 (h5py)")
                print(f"  变量: {keys}")
                for k in keys:
                    v = h[k]
                    if hasattr(v, "shape"):
                        data = v[:]
                        valid = data[~np.isnan(data)] if data.dtype.kind == "f" else data
                        if len(valid) > 0:
                            stats = f"min={valid.min():.4g}, max={valid.max():.4g}, mean={valid.mean():.4g}"
                        else:
                            stats = "all NaN"
                        print(f"    {k:<30} shape={str(v.shape):<20} dtype={v.dtype}  {stats}")
                results[fname] = {
                    "status": "ok",
                    "format": "v7.3",
                    "variables": keys,
                }

    return results


def main() -> None:
    print("=" * 70)
    print("全面数据检查报告")
    print(f"根目录: {ROOT}")
    print("=" * 70)

    report = {}
    report["smap"] = check_smap()
    report["omega"] = check_omega_mat()
    report["cmfd"] = check_cmfd_netcdf()
    report["geotiffs"] = check_geotiffs()
    report["csv"] = check_csv()
    report["landscape"] = check_landscape_mat()

    # 保存报告
    report_path = Path(r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Tools\reports\data_inspection.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n\n报告已保存: {report_path}")


if __name__ == "__main__":
    main()
