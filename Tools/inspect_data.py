#!/usr/bin/env python3
"""检查已下载数据的格式和内容。"""

from pathlib import Path

ROOT = Path(r"I:\Geograph_DataSet")


def check_smap_h5():
    """检查 SMAP HDF5 文件。"""
    print("=" * 60)
    print("SMAP HDF5 文件检查")
    print("=" * 60)
    smap_dir = ROOT / "SMAP"
    files = list(smap_dir.glob("*.h5"))
    print(f"文件数: {len(files)}")

    if not files:
        print("无文件")
        return

    f = files[0]
    print(f"检查: {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)")

    try:
        import h5py

        with h5py.File(f, "r") as h5:
            print("\nHDF5 结构:")

            def print_tree(name, obj):
                if isinstance(obj, h5py.Dataset):
                    print(f"  [Dataset] {name}  shape={obj.shape}  dtype={obj.dtype}")
                elif isinstance(obj, h5py.Group):
                    print(f"  [Group]   {name}/")

            h5.visititems(print_tree)

            # 检查常见 SMAP 变量
            print("\n根属性:")
            for k, v in h5.attrs.items():
                val_str = str(v)[:100]
                print(f"  {k}: {val_str}")
    except ImportError:
        print("h5py 未安装")
    except Exception as e:
        print(f"错误: {e}")
    print()


def check_omega_mat():
    """检查 omega .mat 文件。"""
    print("=" * 60)
    print("omega .mat 文件检查")
    print("=" * 60)
    inv_dir = ROOT / "InversionResults"
    files = list(inv_dir.glob("*.mat"))
    print(f"文件数: {len(files)}")

    if not files:
        print("无文件")
        return

    # 检查第一个文件
    f = sorted(files)[0]
    print(f"\n检查: {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)")

    try:
        try:
            import scipy.io as sio

            data = sio.loadmat(str(f))
            print("MATLAB v5/v6 格式 (scipy.io)")
        except Exception:
            import h5py

            with h5py.File(f, "r") as h5:
                data = {k: v for k, v in h5.items()}
            print("MATLAB v7.3 格式 (h5py)")

        print("\n变量:")
        for k, v in data.items():
            if k.startswith("__"):
                continue
            if hasattr(v, "shape"):
                print(f"  {k}: shape={v.shape}  dtype={v.dtype}")
            else:
                print(f"  {k}: {type(v)} = {str(v)[:100]}")
    except Exception as e:
        print(f"错误: {e}")

    # 检查 Landscape Metrics
    lm_file = inv_dir / "Landscape_Metrics_LandOnly_9KM_2020.mat"
    if lm_file.exists():
        print(f"\n检查: {lm_file.name} ({lm_file.stat().st_size / 1024 / 1024:.1f} MB)")
        try:
            import scipy.io as sio

            data = sio.loadmat(str(lm_file))
            for k, v in data.items():
                if k.startswith("__"):
                    continue
                if hasattr(v, "shape"):
                    print(f"  {k}: shape={v.shape}  dtype={v.dtype}")
        except Exception as e:
            print(f"  错误: {e}")
    print()


def check_tif():
    """检查 GeoTIFF 文件。"""
    print("=" * 60)
    print("GeoTIFF 文件检查")
    print("=" * 60)

    tif_files = []
    for subdir in ["LandCover", "Precipitation", "Weather", "HumanFootprint"]:
        d = ROOT / subdir
        if d.exists():
            tif_files.extend([(d, f) for f in d.glob("*.tif")])

    print(f"TIFF 文件数: {len(tif_files)}")

    if not tif_files:
        print("无文件")
        return

    try:
        import rasterio
        from rasterio.transform import from_bounds

        for d, f in tif_files[:5]:
            print(
                f"\n检查: {d.name}/{f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)"
            )
            try:
                with rasterio.open(f) as ds:
                    print(f"  CRS: {ds.crs}")
                    print(f"  Size: {ds.width} x {ds.height}")
                    print(f"  Bands: {ds.count}")
                    print(f"  Bounds: {ds.bounds}")
                    print(f"  Resolution: {ds.res}")
                    print(f"  Dtype: {ds.dtypes}")
                    # 读取少量数据
                    data = ds.read(1, window=((0, 5), (0, 5)))
                    print(
                        f"  Sample data (5x5): min={data.min():.2f} max={data.max():.2f} mean={data.mean():.2f}"
                    )
            except Exception as e:
                print(f"  错误: {e}")
    except ImportError:
        print("rasterio 未安装，尝试 GDAL...")
        try:
            from osgeo import gdal

            for d, f in tif_files[:3]:
                print(f"\n检查: {d.name}/{f.name}")
                ds = gdal.Open(str(f))
                if ds:
                    print(f"  Size: {ds.RasterXSize} x {ds.RasterYSize}")
                    print(f"  Bands: {ds.RasterCount}")
                    print(f"  Projection: {ds.GetProjection()[:80]}...")
        except ImportError:
            print("GDAL 也未安装")
    print()


def check_netcdf():
    """检查 NetCDF 文件。"""
    print("=" * 60)
    print("NetCDF 文件检查")
    print("=" * 60)

    nc_files = []
    for subdir in ["Weather"]:
        d = ROOT / subdir
        if d.exists():
            nc_files.extend([(d, f) for f in d.glob("*.nc")])

    print(f"NetCDF 文件数: {len(nc_files)}")

    if not nc_files:
        print("无文件")
        return

    try:
        import netCDF4 as nc

        for d, f in nc_files[:3]:
            print(
                f"\n检查: {d.name}/{f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)"
            )
            try:
                ds = nc.Dataset(str(f), "r")
                print("  全局属性:")
                for attr in ds.ncattrs()[:5]:
                    print(f"    {attr}: {str(ds.getncattr(attr))[:80]}")

                print("  维度:")
                for name, dim in ds.dimensions.items():
                    print(f"    {name}: {len(dim)}")

                print("  变量:")
                for name, var in ds.variables.items():
                    print(f"    {name}: shape={var.shape} dtype={var.dtype}")
                    if hasattr(var, "units"):
                        print(f"      units={var.units}")
                    if hasattr(var, "long_name"):
                        print(f"      long_name={var.long_name}")

                ds.close()
            except Exception as e:
                print(f"  错误: {e}")
    except ImportError:
        print("netCDF4 未安装")
    print()


def check_csv():
    """检查 CSV 文件。"""
    print("=" * 60)
    print("CSV 文件检查")
    print("=" * 60)

    csv_files = []
    for subdir in ["Station", "Others"]:
        d = ROOT / subdir
        if d.exists():
            csv_files.extend([(d, f) for f in d.glob("*.csv")])

    print(f"CSV 文件数: {len(csv_files)}")

    try:
        import pandas as pd

        for d, f in csv_files[:3]:
            print(f"\n检查: {d.name}/{f.name} ({f.stat().st_size / 1024:.1f} KB)")
            df = pd.read_csv(f, nrows=5)
            print(f"  列: {list(df.columns)}")
            print("  前5行:")
            print(df.to_string(index=False))
    except Exception as e:
        print(f"错误: {e}")
    print()


def main():
    print(f"数据根目录: {ROOT}")
    print()

    # 列出所有目录和文件数
    print("目录概览:")
    for d in sorted(ROOT.iterdir()):
        if d.is_dir():
            try:
                files = list(d.rglob("*"))
                file_count = sum(1 for f in files if f.is_file())
                size = sum(f.stat().st_size for f in files if f.is_file())
                print(
                    f"  {d.name:30s}  {file_count:8d} 文件  {size/1024/1024/1024:.2f} GB"
                )
            except Exception as e:
                print(f"  {d.name:30s}  (错误: {e})")
    print()

    check_smap_h5()
    check_omega_mat()
    check_tif()
    check_netcdf()
    check_csv()


if __name__ == "__main__":
    main()
