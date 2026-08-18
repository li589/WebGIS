# -*- coding: utf-8 -*-
# FY-3B MWRI 处理版（由 FY-3D 代码适配）
# 建议直接使用 OSGeo4W 的 GDAL，不要混用 conda 的 GDAL

# $env:PATH = "C:\OSGeo4W\bin;" + $env:PATH
# $env:GDAL_DRIVER_PATH = "C:\OSGeo4W\bin\gdalplugins"
# $env:PROJ_LIB = "C:\OSGeo4W\share\proj"
# $env:PROJ_DATA = "C:\OSGeo4W\share\proj"
# $env:GDAL_DATA = "C:\OSGeo4W\share\gdal"
# $env:PYTHONHOME = ""
# $env:PYTHONPATH = ""
# -*- coding: utf-8 -*-

# -*- coding: utf-8 -*-
# FY-3B MWRI 处理版（在 FY-3D 代码基础上做最小改动）
# 重点：
# 1) 强制使用 OSGeo4W 的 GDAL/PROJ 环境
# 2) FY-3B 的源 nodata 不再手写猜测，优先从数据集元数据自动读取
# 3) geoloc/warp 后统一输出 nodata = -999，尽量保持你原始后处理逻辑不变

import os
import sys
import glob
import json
import re
import subprocess
import calendar

import numpy as np
import pandas as pd
import rasterio
import netCDF4 as nc
import h5py

# ====================== 强制绑定 OSGeo4W 运行环境 ======================
os.environ["PATH"] = r"C:\OSGeo4W\bin;" + os.environ.get("PATH", "")
os.environ["GDAL_DRIVER_PATH"] = r"C:\OSGeo4W\bin\gdalplugins"
os.environ["PROJ_LIB"] = r"C:\OSGeo4W\share\proj"
os.environ["PROJ_DATA"] = r"C:\OSGeo4W\share\proj"
os.environ["GDAL_DATA"] = r"C:\OSGeo4W\share\gdal"

# 避免混入 conda/python 环境残留
os.environ["PYTHONHOME"] = ""
os.environ["PYTHONPATH"] = ""

# ====================== 固定使用 OSGeo4W 的 GDAL ======================
FORCE_GDAL_BIN = r"C:\OSGeo4W\bin"
OSGEO4W_PY     = r"C:\OSGeo4W\bin\python.exe"
OSGEO4W_MERGE  = r"C:\OSGeo4W\bin\gdal_merge.py"
OSGEO4W_MERGE_BAT = r"C:\OSGeo4W\bin\gdal_merge.bat"

# ====================== FY-3B 固定参数 ======================
# FY-3B HDF4/HDF-EOS 风格产品中，当前你这批数据按 gdalinfo 的表现：
# TB:           //EARTH_OBSERVE_BT_10_to_89GHz
# Latitude:     //Latitude
# Longitude:    //Longitude
# SensorZenith: //SensorZenith
#
# 注意：
# 源 nodata 不再完全写死，优先从 gdalinfo / band metadata 自动读取。
# 为了保持后续拼接/融合逻辑尽量不变，geoloc 后统一输出为 -999。

TB_SDS_PATH   = '//EARTH_OBSERVE_BT_10_to_89GHz'
LAT_SDS_PATH  = '//Latitude'
LON_SDS_PATH  = '//Longitude'
ZEN_SDS_PATH  = '//SensorZenith'

COMMON_DST_NODATA = -999.0

TB_BAND_NAMES = ['10V','10H','18V','18H','23V','23H','36V','36H','89V','89H']
ZENITH_NAME   = 'SensorZenith'

# 仅作为兜底默认值：若元数据实在读不到，再退回这些
TB_SRC_NODATA_FALLBACK  = -999.0
LL_SRC_NODATA_FALLBACK  = 999.9
ZEN_SRC_NODATA_FALLBACK = 32767.0

# ====================== 定位 GDAL 可执行文件 ======================
def _resolve_gdal_bins():
    def ok(p):
        return p and os.path.exists(p)

    tried = []

    def try_prefix(prefix):
        if not prefix or not os.path.isdir(prefix):
            return None
        t = os.path.join(prefix, "gdal_translate.exe")
        b = os.path.join(prefix, "gdalbuildvrt.exe")
        w = os.path.join(prefix, "gdalwarp.exe")
        i = os.path.join(prefix, "gdalinfo.exe")
        tried.extend([t, b, w, i])
        return (t, b, w, i, prefix) if all(map(ok, [t, b, w, i])) else None

    fb = (FORCE_GDAL_BIN or "").strip().rstrip("/\\")
    found = try_prefix(fb)
    if found:
        return found

    cp = os.environ.get("CONDA_PREFIX", "")
    found = try_prefix(os.path.join(cp, "Library", "bin"))
    if found:
        return found

    exe = os.path.abspath(sys.executable)
    found = try_prefix(os.path.join(os.path.dirname(os.path.dirname(exe)), "Library", "bin"))
    if found:
        return found

    import shutil as _sh
    t = _sh.which("gdal_translate") or _sh.which("gdal_translate.exe")
    b = _sh.which("gdalbuildvrt")  or _sh.which("gdalbuildvrt.exe")
    w = _sh.which("gdalwarp")      or _sh.which("gdalwarp.exe")
    i = _sh.which("gdalinfo")      or _sh.which("gdalinfo.exe")
    tried.extend([t, b, w, i])
    if t and b and w and i:
        return t, b, w, i, os.path.dirname(t)

    detail = "\n  - ".join([str(x) for x in tried if x])
    raise FileNotFoundError("未能定位到 GDAL 可执行文件。\n已尝试：\n  - " + detail)

GDAL_TRANSLATE, GDAL_BUILDVRT, GDAL_WARP, GDAL_INFO, GDAL_BIN_PREFIX = _resolve_gdal_bins()

# ====================== 小工具：数值/NoData 检查 ======================
def _to_float_or_none(v):
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None

def _nodata_equal(a, b, tol=1e-6):
    fa = _to_float_or_none(a)
    fb = _to_float_or_none(b)
    if fa is None or fb is None:
        return False
    return abs(fa - fb) <= tol

def check_nodata(path, expected=None, expected_epsg=None, expected_size=None, label=''):
    try:
        with rasterio.open(path) as ds:
            nodas = ds.nodatavals
            try:
                crs_epsg = ds.crs.to_epsg() if ds.crs else None
            except Exception:
                crs_epsg = None
            size = (ds.width, ds.height)

        print(f'[CHECK] {label} | {os.path.basename(path)}')
        print(f'        bands={len(nodas)} nodata={nodas}')

        if expected is not None:
            ok = True
            for i, v in enumerate(nodas, 1):
                if not _nodata_equal(v, expected):
                    ok = False
                    print(f'        WARN: band#{i} nodata={v} != {expected}')
            if ok:
                print('        OK: nodata 全部匹配预期。')

        if expected_epsg is not None:
            if crs_epsg != expected_epsg:
                print(f'        WARN: EPSG={crs_epsg} != {expected_epsg}')
            else:
                print(f'        OK: EPSG={crs_epsg}')

        if expected_size is not None:
            if size != tuple(expected_size):
                print(f'        WARN: size={size} != {tuple(expected_size)}')
            else:
                print(f'        OK: size={size}')

    except Exception as e:
        print(f'[CHECK] {label} | 打开失败：{e}')

# ====================== 用户输入参数 ======================
FY_folder   = r'Y:\Chenhaojun\FY3B_汇总'
band_ids    = [1, 2]          # 10V, 10H
op_orbit    = 'MWRID'         # 'MWRID'/'MWRIA'/'Both'
output_root = r'Y:\Chenhaojun\3b1012'

year_start, year_end   = 2010, 2012
month_start, month_end = 1, 12

dates_str_list = []
for y in range(year_start, year_end + 1):
    sm = month_start if y == year_start else 1
    em = month_end   if y == year_end   else 12
    for m in range(sm, em + 1):
        last_day = calendar.monthrange(y, m)[1]
        for d in pd.date_range(pd.Timestamp(y, m, 1), pd.Timestamp(y, m, last_day), freq='D'):
            dates_str_list.append(d.strftime('%Y%m%d'))

if not dates_str_list:
    print("------输入的时间范围无效!!! ------")
    sys.exit(0)

overlap_option = 'average'
outfile_type   = 2           # 0:GTiff 1:NetCDF 2:HDF5

spatial_extent = 0  # 0 全球；1 单点；2 矩形；3 Shapefile
if spatial_extent == 1:
    point = [120, 20]
    buffer_x, buffer_y = 0.01, 0.01
if spatial_extent == 2:
    lat_lon = [-110, -10, 110, 10]
if spatial_extent == 3:
    shapefile_path = r'E:\FY3D\FY3D\output2\china.shp'

# ====================== 构造 SDS URI ======================
def _hdf_sds(hdf_path, sds_path):
    return f'HDF5:"{hdf_path}":{sds_path}'

# ====================== 读取 gdalinfo 文本 ======================
def run_gdalinfo_text(target_path):
    cmd = f'"{GDAL_INFO}" "{target_path}"'
    proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    return proc.stdout

def run_gdalinfo_text_sds(hdf_path, sds_path):
    uri = _hdf_sds(hdf_path, sds_path)
    cmd = f'"{GDAL_INFO}" "{uri}"'
    proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    return proc.stdout

# ====================== 从 gdalinfo 文本中解析 nodata ======================
def parse_nodata_from_gdalinfo_text(txt):
    # 优先找 "NoData Value="
    m = re.search(r'NoData Value\s*=\s*([^\r\n]+)', txt)
    if m:
        v = m.group(1).strip().strip('"').strip("'")
        try:
            return float(v)
        except Exception:
            pass

    # 再找各种 FillValue / _FillValue
    patterns = [
        r'_FillValue\s*=\s*([^\r\n]+)',
        r'FillValue\s*=\s*([^\r\n]+)',
    ]
    for pat in patterns:
        m = re.search(pat, txt)
        if m:
            v = m.group(1).strip().strip('"').strip("'")
            try:
                return float(v)
            except Exception:
                pass

    return None

def get_src_nodata_for_sds(hdf_path, sds_path, fallback_value, label=''):
    try:
        txt = run_gdalinfo_text_sds(hdf_path, sds_path)
        nd = parse_nodata_from_gdalinfo_text(txt)
        if nd is not None:
            print(f'[INFO] {label} 源 nodata 自动识别为: {nd}')
            return nd
    except Exception as e:
        print(f'[WARN] {label} 读取 gdalinfo 失败，改用 fallback={fallback_value}。错误：{e}')

    print(f'[WARN] {label} 未识别到源 nodata，使用 fallback={fallback_value}')
    return float(fallback_value)

# ====================== 读取物理系数（用于写输出属性，尽量和原始文件一致） ======================
def parse_metadata_value(txt, key):
    # 允许 key=... 或 key = ...
    m = re.search(rf'{re.escape(key)}\s*=\s*([^\r\n]+)', txt)
    if not m:
        return None
    return m.group(1).strip()

def get_tb_scale_offset_from_file(hdf_path):
    """
    从 FY-3B 原始文件 gdalinfo 顶层 metadata 读取 TB 的 Slope / Intercept。
    读不到时退回默认值：
        slope = 0.01
        intercept = 327.679993
    """
    slope = 0.01
    intercept = 327.679993

    try:
        txt = run_gdalinfo_text(hdf_path)
        v1 = parse_metadata_value(txt, 'Calibration_EARTH_OBSERVE_BT_10_to_89GHz_Slope')
        v2 = parse_metadata_value(txt, 'Calibration_EARTH_OBSERVE_BT_10_to_89GHz_Intercept')
        if v1 is not None:
            slope = float(v1)
        if v2 is not None:
            intercept = float(v2)
        print(f'[INFO] TB 系数: slope={slope}, intercept={intercept}')
    except Exception as e:
        print(f'[WARN] 无法自动读取 TB 系数，使用默认值 slope={slope}, intercept={intercept}。错误：{e}')

    return slope, intercept

def get_zen_scale_offset_from_sds(hdf_path):
    """
    从 SensorZenith 子数据集读取 Slope / Intercept。
    读不到时退回默认：
        slope = 0.01
        intercept = 0
    """
    slope = 0.01
    intercept = 0.0
    try:
        txt = run_gdalinfo_text_sds(hdf_path, ZEN_SDS_PATH)
        v1 = parse_metadata_value(txt, 'Slope')
        v2 = parse_metadata_value(txt, 'Intercept')
        if v1 is not None:
            slope = float(v1)
        if v2 is not None:
            intercept = float(v2)
        print(f'[INFO] SensorZenith 系数: slope={slope}, intercept={intercept}')
    except Exception as e:
        print(f'[WARN] 无法自动读取 SensorZenith 系数，使用默认值 slope={slope}, intercept={intercept}。错误：{e}')
    return slope, intercept

# ====================== 单通道 geoloc → 4326 ======================
def geoloc_hdf(subdataset_path, file, band_names, band_ids_one, work_folder):
    """
    保持原流程：
    translate -> lat/lon vrt -> 注入 GEOLOCATION -> gdalwarp(geoloc)
    仅增强：
    1) FY-3B 源 nodata 自动识别
    2) 输出 nodata 统一为 -999
    """
    assert len(band_ids_one) == 1
    band_name = band_names[band_ids_one[0] - 1]

    os.makedirs(work_folder, exist_ok=True)
    hdf_path = os.path.join(FY_folder, file)

    # 自动识别源 nodata
    if subdataset_path == TB_SDS_PATH:
        src_nodata = get_src_nodata_for_sds(hdf_path, TB_SDS_PATH, TB_SRC_NODATA_FALLBACK, label=f'{file} {band_name} TB')
    elif subdataset_path == ZEN_SDS_PATH:
        src_nodata = get_src_nodata_for_sds(hdf_path, ZEN_SDS_PATH, ZEN_SRC_NODATA_FALLBACK, label=f'{file} {band_name} Zenith')
    else:
        src_nodata = TB_SRC_NODATA_FALLBACK

    lat_nodata = get_src_nodata_for_sds(hdf_path, LAT_SDS_PATH, LL_SRC_NODATA_FALLBACK, label=f'{file} Latitude')
    lon_nodata = get_src_nodata_for_sds(hdf_path, LON_SDS_PATH, LL_SRC_NODATA_FALLBACK, label=f'{file} Longitude')

    # 1) 数据 VRT
    data_uri = _hdf_sds(hdf_path, subdataset_path)
    vrt_path = os.path.join(work_folder, f'temp_{file[:-4]}_{band_name}.vrt')

    cmd = f'"{GDAL_TRANSLATE}" -of VRT -a_nodata {src_nodata} -b {band_ids_one[0]} {data_uri} "{vrt_path}"'
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f'[SKIP] {file} {band_name}: gdal_translate 数据VRT 失败（已跳过）。错误：{e}')
        return None

    # 2) 纬度/经度 VRT
    vrtlat_path = os.path.join(work_folder, f'lat_{file[:-4]}_{band_name}.vrt')
    lat_uri = _hdf_sds(hdf_path, LAT_SDS_PATH)
    cmd = f'"{GDAL_TRANSLATE}" -of VRT -a_nodata {lat_nodata} {lat_uri} "{vrtlat_path}"'
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f'[SKIP] {file} {band_name}: gdal_translate 纬度VRT 失败（已跳过）。错误：{e}')
        return None

    vrtlon_path = os.path.join(work_folder, f'lon_{file[:-4]}.vrt')
    lon_uri = _hdf_sds(hdf_path, LON_SDS_PATH)
    cmd = f'"{GDAL_TRANSLATE}" -of VRT -a_nodata {lon_nodata} {lon_uri} "{vrtlon_path}"'
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f'[SKIP] {file} {band_name}: gdal_translate 经度VRT 失败（已跳过）。错误：{e}')
        return None

    # 3) 注入 geolocation metadata
    metadata_content = f'''<Metadata domain="GEOLOCATION">
            <MDI key="LINE_OFFSET">0</MDI>
            <MDI key="LINE_STEP">1</MDI>
            <MDI key="PIXEL_OFFSET">0</MDI>
            <MDI key="PIXEL_STEP">1</MDI>
            <MDI key="SRS">EPSG:4326</MDI>
            <MDI key="X_BAND">1</MDI>
            <MDI key="X_DATASET">{vrtlon_path}</MDI>
            <MDI key="Y_BAND">1</MDI>
            <MDI key="Y_DATASET">{vrtlat_path}</MDI>
        </Metadata>
    '''

    new_vrt_path = vrt_path.replace('.vrt', 'new.vrt')
    inserted = False
    with open(vrt_path, encoding='utf-8') as f, open(new_vrt_path, 'w', encoding='utf-8') as g:
        for line in f:
            if (not inserted) and ('<GCPList' in line):
                g.write(metadata_content)
                inserted = True
            g.write(line)
        if not inserted:
            # 某些 VRT 没有 GCPList，就在末尾前强插
            pass

    vrt_path0 = os.path.join(work_folder, f'temp_{file[:-4]}_{band_name}new.vrt')
    tif_path  = os.path.join(work_folder, f'vrt_{file[:-4]}_{band_name}.tif')

    # 4) geoloc → 4326
    print(f'开始地理查找表校正... ({band_name})')
    cmd = (
        f'"{GDAL_WARP}" -overwrite -geoloc -t_srs EPSG:4326 '
        f'-srcnodata {src_nodata} -dstnodata {COMMON_DST_NODATA} '
        f'-of GTiff -ot Float32 -r {overlap_option} '
        f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
        f'"{vrt_path0}" "{tif_path}"'
    )
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f'[SKIP] {file} {band_name}: gdalwarp -geoloc 失败（已跳过并继续）。错误：{e}')
        return None

    # 这里只是检查，不影响任何数据生成
    check_nodata(vrt_path0, expected=src_nodata, label=f'VRT (geoloc src) {band_name}')
    check_nodata(tif_path,  expected=COMMON_DST_NODATA, label=f'geoloc→4326 输出 {band_name}')
    return band_name

# ====================== 日内拼接 + 重投影 ======================
def merge_allto_tif(work_folder, band_name):
    os.makedirs(work_folder, exist_ok=True)
    mosaic_vrt = os.path.join(work_folder, f'mosaic_{band_name}.vrt')

    src_list = sorted(glob.glob(os.path.join(work_folder, f'vrt*{band_name}.tif')))
    if not src_list:
        print(f'[SKIP] {band_name}: 没有找到可拼接的 geoloc 结果，跳过该 band 的拼接。')
        return None

    inputs = ' '.join(f'"{p}"' for p in src_list)
    cmd = f'"{GDAL_BUILDVRT}" -srcnodata {COMMON_DST_NODATA} -vrtnodata {COMMON_DST_NODATA} "{mosaic_vrt}" {inputs}'
    print("Running:", cmd)
    proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        print(f"[SKIP] {band_name}: gdalbuildvrt 失败（已跳过）。错误：\n{proc.stderr}")
        return None
    print("VRT creation successful.")
    check_nodata(mosaic_vrt, expected=COMMON_DST_NODATA, label=f'mosaic_{band_name}.vrt (日内拼接)')

    print('开始融合数据...')
    output_tif_path  = os.path.join(work_folder, f'FY3B_GBAL_L1_{band_name}_{day}_{op_orbit}_0.tif')
    output_tif_path0 = os.path.join(work_folder, f'FY3B_GBAL_L1_{band_name}_{day}_{op_orbit}_01.tif')

    cmd = (
        f'"{GDAL_WARP}" -of GTiff -ot Float32 -r {overlap_option} '
        f'-srcnodata {COMMON_DST_NODATA} -dstnodata {COMMON_DST_NODATA} '
        f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
        f'"{mosaic_vrt}" "{output_tif_path0}"'
    )
    subprocess.run(cmd, shell=True, check=True)
    check_nodata(output_tif_path0, expected=COMMON_DST_NODATA, label='mosaic→4326 输出')

    if spatial_extent == 0:
        cmd = (
            f'"{GDAL_WARP}" -overwrite -t_srs EPSG:6933 '
            f'-te -17367530.45 -7314540.83 17367530.45 7314540.83 '
            f'-ts 3856 1624 -r average '
            f'-srcnodata {COMMON_DST_NODATA} -dstnodata {COMMON_DST_NODATA} '
            f'-of GTiff -ot Float32 '
            f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
            f'"{output_tif_path0}" "{output_tif_path}"'
        )
    elif spatial_extent == 1:
        min_x, max_x = point[0] - buffer_x, point[0] + buffer_x
        min_y, max_y = point[1] - buffer_y, point[1] + buffer_y
        cmd = (
            f'"{GDAL_WARP}" -of GTiff -ot Float32 -r {overlap_option} '
            f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
            f'-te {min_x} {min_y} {max_x} {max_y} '
            f'"{mosaic_vrt}" "{output_tif_path}"'
        )
    elif spatial_extent == 2:
        cmd = (
            f'"{GDAL_WARP}" -of GTiff -ot Float32 -r {overlap_option} '
            f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
            f'-te {lat_lon[0]} {lat_lon[1]} {lat_lon[2]} {lat_lon[3]} '
            f'"{mosaic_vrt}" "{output_tif_path}"'
        )
    else:
        out0 = os.path.join(work_folder, f'FY3B_GBAL_L1_{band_name}_{day}_{op_orbit}_0.tif')
        out1 = os.path.join(work_folder, f'FY3B_GBAL_L1_{band_name}_{day}_{op_orbit}.tif')
        cmd = (
            f'"{GDAL_WARP}" -of GTiff -ot Float32 -r {overlap_option} '
            f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" "{mosaic_vrt}" "{out0}"'
        )
        subprocess.run(cmd, shell=True, check=True)
        print('开始剪切...')
        cmd = (
            f'"{GDAL_WARP}" -cutline "{shapefile_path}" -crop_to_cutline '
            f'-of GTiff -ot Float32 -co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" "{out0}" "{out1}"'
        )
        output_tif_path = out1

    subprocess.run(cmd, shell=True, check=True)

    if spatial_extent == 0:
        check_nodata(output_tif_path, expected=COMMON_DST_NODATA, expected_epsg=6933, expected_size=(3856,1624), label='4326→EASE2 输出')
    else:
        check_nodata(output_tif_path, expected=COMMON_DST_NODATA, label='4326/裁剪 输出')

    try:
        os.remove(output_tif_path0)
    except:
        pass
    try:
        os.remove(mosaic_vrt)
    except:
        pass

    return output_tif_path

# ====================== 合并（TB 多通道 + IA） ======================
def mergy_day(files_str_list, tb_name, work_folder):
    if not files_str_list:
        return 0

    su_t = 0
    tb_band_names = ['10V', '10H'] if band_ids == [1, 2] else [f for i, f in enumerate(TB_BAND_NAMES, 1) if i in band_ids]
    zenith_name   = ZENITH_NAME

    # 取当天第一个文件的原始元数据，作为输出属性参考
    first_hdf = os.path.join(FY_folder, files_str_list[0])
    tb_slope, tb_intercept = get_tb_scale_offset_from_file(first_hdf)
    zen_slope, zen_intercept = get_zen_scale_offset_from_sds(first_hdf)

    # 逐文件 geoloc：TB 各通道 + IA
    for file in files_str_list:
        for idx in band_ids:
            geoloc_hdf(TB_SDS_PATH, file, TB_BAND_NAMES, [idx], work_folder)
        geoloc_hdf(ZEN_SDS_PATH, file, [zenith_name], [1], work_folder)
        su_t += 1

    if su_t == 0:
        return 0

    # 日内拼接
    tb_tifs = []
    for bname in tb_band_names:
        t = merge_allto_tif(work_folder, bname)
        if not t:
            return 0
        tb_tifs.append(t)

    ia_tif = merge_allto_tif(work_folder, zenith_name)
    if not ia_tif:
        return 0

    # 多波段合并
    band_tag = ''.join(tb_band_names)
    tb_band_name = f'{tb_name}_{band_tag}'

    mergy_vrt0 = os.path.join(work_folder, f'FY3B_GBAL_L1_{tb_band_name}_{day}_{op_orbit}_1.vrt')
    inputs = " ".join(f'"{p}"' for p in (tb_tifs + [ia_tif]))

    cmd = (
        f'"{GDAL_BUILDVRT}" -separate '
        f'-srcnodata {COMMON_DST_NODATA} -vrtnodata {COMMON_DST_NODATA} '
        f'"{mergy_vrt0}" {inputs}'
    )
    print("Running buildvrt(separate):", cmd)

    proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0 or (not os.path.exists(mergy_vrt0)):
        print("gdalbuildvrt(separate) 失败：", proc.stderr)
        print("命令：", cmd)
        return 0

    selected = tb_band_names + [zenith_name]
    metadata_strs = " ".join(f'-mo Band_{i}={name}' for i, name in enumerate(selected, start=1))
    mergy_filetifname = os.path.join(work_folder, f'FY3B_GBAL_L1_{tb_band_name}_{day}_{op_orbit}.tif')

    cmd = (
        f'"{GDAL_TRANSLATE}" -of GTiff -a_nodata {COMMON_DST_NODATA} -ot Float32 '
        f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
        f'{metadata_strs} "{mergy_vrt0}" "{mergy_filetifname}"'
    )
    subprocess.run(cmd, shell=True, check=True)

    try:
        os.remove(mergy_vrt0)
    except:
        pass

    # ===== 输出（仍保持“保存 geoloc 后浮点值”这一逻辑）=====
    if outfile_type == 1:
        output_nc_path = os.path.join(work_folder, f'FY3B_GBAL_L1_{tb_band_name}_{day}_{op_orbit}.nc')
        with rasterio.open(mergy_filetifname) as src0:
            band0 = src0.read(1)

        ncfile = nc.Dataset(output_nc_path, 'w', format='NETCDF4')
        ncfile.createDimension('x', band0.shape[0])
        ncfile.createDimension('y', band0.shape[1])

        with rasterio.open(mergy_filetifname) as src:
            for idx, band_name in enumerate(selected, start=1):
                arr = src.read(idx, masked=True).astype(np.float32)
                band = np.ma.filled(arr, np.nan)

                if band_name == ZENITH_NAME:
                    var = ncfile.createVariable(band_name, np.float32, ('x', 'y'))
                    var[:, :] = band
                    var.units = 'degree'
                    var.Valid_range = [0, 18000]
                    var.FillValue = COMMON_DST_NODATA
                    var.Intercept = zen_intercept
                    var.Slope = zen_slope
                    var.Long_name = ZENITH_NAME
                else:
                    number_part = ''.join(filter(str.isdigit, band_name))
                    letter_part = ''.join(filter(str.isalpha, band_name))
                    vari_name = f'EARTH OBSERVE BT {number_part}GHz {letter_part}'
                    var = ncfile.createVariable(vari_name, np.float32, ('x', 'y'))
                    var[:, :] = band
                    var.units = 'K'
                    var.Valid_range = [-32766, 10000]
                    var.FillValue = COMMON_DST_NODATA
                    var.Intercept = tb_intercept
                    var.Slope = tb_slope
                    var.Long_name = f'{number_part}GHZ {letter_part} Earth Observation Brightness Temperature'

        ncfile.close()
        print(f'{output_nc_path} 融合成功')

    if outfile_type == 2:
        output_hdf_path = os.path.join(work_folder, f'FY3B_GBAL_L1_{tb_band_name}_{day}_{op_orbit}.hdf')
        tmp_hdf = output_hdf_path + '.tmp'
        try:
            with h5py.File(tmp_hdf, 'w') as h5, rasterio.open(mergy_filetifname) as src:
                for idx, band_name in enumerate(selected, start=1):
                    arr = src.read(idx, masked=True).astype(np.float32)
                    band = np.ma.filled(arr, np.nan)

                    if band_name == ZENITH_NAME:
                        d = h5.create_dataset(band_name, data=band)
                        d.attrs.update({
                            'units': 'degree',
                            'Valid range': '0 18000',
                            'FillValue': COMMON_DST_NODATA,
                            'Intercept': zen_intercept,
                            'Slope': zen_slope,
                            'Long_name': ZENITH_NAME
                        })
                    else:
                        number_part = ''.join(filter(str.isdigit, band_name))
                        letter_part = ''.join(filter(str.isalpha, band_name))
                        vari_name = f'EARTH OBSERVE BT {number_part}GHz {letter_part}'
                        d = h5.create_dataset(vari_name, data=band)
                        d.attrs.update({
                            'units': 'K',
                            'Valid range': '-32766 10000',
                            'FillValue': COMMON_DST_NODATA,
                            'Intercept': tb_intercept,
                            'Slope': tb_slope,
                            'Long_name': f'{number_part}GHZ {letter_part} Earth Observation Brightness Temperature'
                        })

            os.replace(tmp_hdf, output_hdf_path)
            print(f'{output_hdf_path} 融合成功')

        except Exception:
            try:
                if os.path.exists(tmp_hdf):
                    os.remove(tmp_hdf)
            except:
                pass
            raise

    # 清理
    try:
        for p in [os.path.join(work_folder, 'vrt*.tif'), os.path.join(work_folder, '*.vrt')]:
            for f in glob.glob(p):
                try:
                    os.remove(f)
                except:
                    pass
    except:
        pass

    return 1

# ====================== 主流程 ======================
if __name__ == '__main__':
    print("PY :", sys.version)
    try:
        from osgeo import gdal
        print("GDAL VersionInfo():", gdal.VersionInfo())
    except Exception as e:
        print("导入 osgeo 失败（不影响外部 exe 调用）：", e)

    print("GDAL_TRANSLATE :", GDAL_TRANSLATE)
    print("GDAL_BUILDVRT  :", GDAL_BUILDVRT)
    print("GDAL_WARP      :", GDAL_WARP)
    print("GDAL_INFO      :", GDAL_INFO)

    if op_orbit == 'Both':
        out_MWRID = os.path.join(output_root, 'MWRID')
        out_MWRIA = os.path.join(output_root, 'MWRIA')
        os.makedirs(out_MWRID, exist_ok=True)
        os.makedirs(out_MWRIA, exist_ok=True)
    else:
        os.makedirs(output_root, exist_ok=True)

    print('开始扫描 FY_folder ...')
    all_files = [f for f in os.listdir(FY_folder) if f.endswith('.HDF')]
    print(f'扫描完成，HDF 文件数: {len(all_files)}')

    # 先把文件按日期分组，只做一次
    files_by_day = {}
    for file in all_files:
        m = re.search(r'(\d{8})', file)
        if not m:
            continue

        d = m.group(1)
        if d not in files_by_day:
            files_by_day[d] = {'A': [], 'D': []}

        if 'MWRID' in file:
            files_by_day[d]['D'].append(file)
        if 'MWRIA' in file:
            files_by_day[d]['A'].append(file)

    day_exist = False
    for i, day in enumerate(dates_str_list, 1):
        if i % 20 == 0:
            print(f'进度: {i}/{len(dates_str_list)}，当前日期: {day}')

        rec = files_by_day.get(day, {'A': [], 'D': []})
        A_files = rec['A']
        D_files = rec['D']

        if not (A_files or D_files):
            continue

        day_exist = True

        if op_orbit == 'MWRID' and D_files:
            print(day, '[MWRID]', f'文件数={len(D_files)}')
            mergy_day(D_files, 'MWRID', output_root)

        elif op_orbit == 'MWRIA' and A_files:
            print(day, '[MWRIA]', f'文件数={len(A_files)}')
            mergy_day(A_files, 'MWRIA', output_root)

        elif op_orbit == 'Both':
            if D_files:
                print(day, '[MWRID]', f'文件数={len(D_files)}')
                mergy_day(D_files, 'MWRID', out_MWRID)
            if A_files:
                print(day, '[MWRIA]', f'文件数={len(A_files)}')
                mergy_day(A_files, 'MWRIA', out_MWRIA)

    if not day_exist:
        print("------输入的时间范围内无数据存在!!! ------")
        sys.exit(0)
