# -*- coding: utf-8 -*-
# 在gdal311，多切换一下，$env:GDAL_DRIVER_PATH = "C:\OSGeo4W\bin\gdalplugins"

import sys, os, subprocess, glob
import json, re
import numpy as np, pandas as pd, calendar
import rasterio
import netCDF4 as nc, h5py

# ====================== 固定使用 OSGeo4W 的 GDAL ======================
FORCE_GDAL_BIN = r"C:\OSGeo4W\bin"
OSGEO4W_PY     = r"C:\OSGeo4W\bin\python.exe"
OSGEO4W_MERGE  = r"C:\OSGeo4W\bin\gdal_merge.py"
OSGEO4W_MERGE_BAT = r"C:\OSGeo4W\bin\gdal_merge.bat"

# ====================== 定位 GDAL 可执行文件 ======================
def _resolve_gdal_bins():
    def ok(p): return p and os.path.exists(p)
    tried = []
    def try_prefix(prefix):
        if not prefix or not os.path.isdir(prefix): return None
        t = os.path.join(prefix, "gdal_translate.exe")
        b = os.path.join(prefix, "gdalbuildvrt.exe")
        w = os.path.join(prefix, "gdalwarp.exe")
        i = os.path.join(prefix, "gdalinfo.exe")
        tried.extend([t,b,w,i])
        return (t,b,w,i,prefix) if all(map(ok,[t,b,w,i])) else None

    # 0) 强制 OSGeo4W\bin
    fb = (FORCE_GDAL_BIN or "").strip().rstrip("/\\")
    found = try_prefix(fb)
    if found: return found

    # 1) CONDA_PREFIX\Library\bin
    cp = os.environ.get("CONDA_PREFIX","")
    found = try_prefix(os.path.join(cp, "Library", "bin"))
    if found: return found

    # 2) 从 python.exe 反推 \Library\bin
    exe = os.path.abspath(sys.executable)
    found = try_prefix(os.path.join(os.path.dirname(os.path.dirname(exe)), "Library", "bin"))
    if found: return found

    # 3) PATH
    import shutil as _sh
    t = _sh.which("gdal_translate") or _sh.which("gdal_translate.exe")
    b = _sh.which("gdalbuildvrt")  or _sh.which("gdalbuildvrt.exe")
    w = _sh.which("gdalwarp")      or _sh.which("gdalwarp.exe")
    i = _sh.which("gdalinfo")      or _sh.which("gdalinfo.exe")
    tried.extend([t,b,w,i])
    if t and b and w and i:
        return t,b,w,i,os.path.dirname(t)

    detail = "\n  - ".join([str(x) for x in tried if x])
    raise FileNotFoundError("未能定位到 GDAL 可执行文件。\n已尝试：\n  - " + detail)

GDAL_TRANSLATE, GDAL_BUILDVRT, GDAL_WARP, GDAL_INFO, GDAL_BIN_PREFIX = _resolve_gdal_bins()

# ====================== 小工具：nodata 检查 ======================
def check_nodata(path, expected=-32767, expected_epsg=None, expected_size=None, label=''):
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
            for i,v in enumerate(nodas,1):
                if v is None or int(v) != int(expected):
                    ok = False
                    print(f'        WARN: band#{i} nodata={v} != {expected}')
            if ok: print('        OK: nodata 全部匹配预期。')
        if expected_epsg is not None:
            if crs_epsg != expected_epsg: print(f'        WARN: EPSG={crs_epsg} != {expected_epsg}')
            else: print(f'        OK: EPSG={crs_epsg}')
        if expected_size is not None:
            if size != tuple(expected_size): print(f'        WARN: size={size} != {tuple(expected_size)}')
            else: print(f'        OK: size={size}')
    except Exception as e:
        print(f'[CHECK] {label} | 打开失败：{e}')

# *********************************  用户输入参数  **********************************
FY_folder   = r'E:\FY3D_output\缺汇总'
band_ids    = [1, 2]          # 10V, 10H —— 单通道法会逐个处理
op_orbit    = 'MWRID'         # 'MWRID'/'MWRIA'/'Both'
output_root = r'E:\FY3D_output\que'

year_start, year_end   = 2015, 2025
month_start, month_end = 1, 12

dates_str_list = []
for y in range(year_start, year_end+1):
    sm = month_start if y==year_start else 1
    em = month_end   if y==year_end   else 12
    for m in range(sm, em+1):
        last_day = calendar.monthrange(y,m)[1]
        for d in pd.date_range(pd.Timestamp(y,m,1), pd.Timestamp(y,m,last_day), freq='D'):
            dates_str_list.append(d.strftime('%Y%m%d'))
if not dates_str_list:
    print("------输入的时间范围无效!!! ------"); sys.exit(0)

overlap_option = 'average'
outfile_type   = 2           # 0:GTiff 1:NetCDF 2:HDF5

spatial_extent = 0  # 0 全球；1 单点；2 矩形；3 Shapefile
if spatial_extent == 1:
    point = [120, 20]; buffer_x, buffer_y = 0.01, 0.01
if spatial_extent == 2:
    lat_lon = [-110, -10, 110, 10]
if spatial_extent == 3:
    shapefile_path = r'E:\FY3D\FY3D\output2\china.shp'
# **********************************  用户输入参数结束  **********************************

# ====================== 构造 HDF5 SDS URI ======================
def _hdf5_sds(hdf_path, sds_path):
    """返回 HDF5:"<win路径原样>":<SDS 路径> —— 不动斜杠"""
    return f'HDF5:"{hdf_path}":{sds_path}'

# ====================== 单通道 geoloc → 4326 ======================
def geoloc_hdf(subdataset_path, file, band_names, band_ids_one, work_folder):
    """
    保持原流程：直接全幅 -geoloc。
    仅改动：若 gdalwarp 失败就打印 [SKIP] 并返回 None，让外层继续下一个颗粒。
    """
    assert len(band_ids_one) == 1
    band_name = band_names[band_ids_one[0] - 1]  # 如 '10V'

    os.makedirs(work_folder, exist_ok=True)
    hdf_path = os.path.join(FY_folder, file)

    # 1) 数据 VRT
    data_uri = _hdf5_sds(hdf_path, subdataset_path)
    vrt_path = os.path.join(work_folder, f'temp_{file[:-4]}_{band_name}.vrt')
    cmd = f'"{GDAL_TRANSLATE}" -of VRT -a_nodata -32767 -b {band_ids_one[0]} {data_uri} "{vrt_path}"'
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f'[SKIP] {file} {band_name}: gdal_translate 数据VRT 失败（已跳过）。错误：{e}')
        return None

    # 2) 纬度/经度 VRT（nodata=65535）
    vrtlat_path = os.path.join(work_folder, f'lat_{file[:-4]}_{band_name}.vrt')
    lat_uri = _hdf5_sds(hdf_path, '//Geolocation/Latitude')
    cmd = f'"{GDAL_TRANSLATE}" -of VRT -a_nodata 65535 {lat_uri} "{vrtlat_path}"'
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f'[SKIP] {file} {band_name}: gdal_translate 纬度VRT 失败（已跳过）。错误：{e}')
        return None

    vrtlon_path = os.path.join(work_folder, f'lon_{file[:-4]}.vrt')  # 保持你的原命名
    lon_uri = _hdf5_sds(hdf_path, '//Geolocation/Longitude')
    cmd = f'"{GDAL_TRANSLATE}" -of VRT -a_nodata 65535 {lon_uri} "{vrtlon_path}"'
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f'[SKIP] {file} {band_name}: gdal_translate 经度VRT 失败（已跳过）。错误：{e}')
        return None

    # 3) 注入 GEOLOCATION（SRS=EPSG:4326；仅为规范化，无数值影响）
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
    with open(vrt_path, encoding='utf-8') as f, open(vrt_path.replace('.vrt', 'new.vrt'), 'w', encoding='utf-8') as g:
        insert_metadata = False
        for line in f:
            if '</Metadata>' in line: insert_metadata = True
            if '<GCPList Projection="GEOGCS[&quot;WGS 84&quot' in line and insert_metadata:
                g.write(metadata_content); insert_metadata = False
            g.write(line)

    vrt_path0 = os.path.join(work_folder, f'temp_{file[:-4]}_{band_name}new.vrt')
    tif_path  = os.path.join(work_folder, f'vrt_{file[:-4]}_{band_name}.tif')

    # 4) geoloc → 4326
    print(f'开始地理查找表校正... ({band_name})')
    cmd = (
        f'"{GDAL_WARP}" -overwrite -geoloc -t_srs EPSG:4326 '
        f'-srcnodata -32767 -dstnodata -32767 '
        f'-of GTiff -ot Float32 -r {overlap_option} '
        f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
        f'"{vrt_path0}" "{tif_path}"'
    )
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f'[SKIP] {file} {band_name}: gdalwarp -geoloc 失败（已跳过并继续）。错误：{e}')
        return None

    check_nodata(vrt_path0, expected=-32767, label=f'VRT (geoloc src) {band_name}')
    check_nodata(tif_path,  expected=-32767, label=f'geoloc→4326 输出 {band_name}')
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
    cmd = f'"{GDAL_BUILDVRT}" -srcnodata -32767 -vrtnodata -32767 "{mosaic_vrt}" {inputs}'
    print("Running:", cmd)
    proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        print(f"[SKIP] {band_name}: gdalbuildvrt 失败（已跳过）。错误：\n{proc.stderr}")
        return None
    print("VRT creation successful.")
    check_nodata(mosaic_vrt, expected=-32767, label=f'mosaic_{band_name}.vrt (日内拼接)')

    # 4326 → EASE2
    print('开始融合数据...')
    output_tif_path  = os.path.join(work_folder, f'FY3D_GBAL_L1_{band_name}_{day}_{op_orbit}_0.tif')
    output_tif_path0 = os.path.join(work_folder, f'FY3D_GBAL_L1_{band_name}_{day}_{op_orbit}_01.tif')

    cmd = (
        f'"{GDAL_WARP}" -of GTiff -ot Float32 -r {overlap_option} '
        f'-srcnodata -32767 -dstnodata -32767 '
        f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
        f'"{mosaic_vrt}" "{output_tif_path0}"'
    )
    subprocess.run(cmd, shell=True, check=True)
    check_nodata(output_tif_path0, expected=-32767, label='mosaic→4326 输出')

    if spatial_extent == 0:
        cmd = (
            f'"{GDAL_WARP}" -overwrite -t_srs EPSG:6933 '
            f'-te -17367530.45 -7314540.83 17367530.45 7314540.83 '
            f'-ts 3856 1624 -r average '
            f'-srcnodata -32767 -dstnodata -32767 '
            f'-of GTiff -ot Float32 '
            f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
            f'"{output_tif_path0}" "{output_tif_path}"'
        )
    elif spatial_extent == 1:
        min_x, max_x = point[0]-buffer_x, point[0]+buffer_x
        min_y, max_y = point[1]-buffer_y, point[1]+buffer_y
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
        out0 = os.path.join(work_folder, f'FY3D_GBAL_L1_{band_name}_{day}_{op_orbit}_0.tif')
        out1 = os.path.join(work_folder, f'FY3D_GBAL_L1_{band_name}_{day}_{op_orbit}.tif')
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
        check_nodata(output_tif_path, expected=-32767, expected_epsg=6933, expected_size=(3856,1624), label='4326→EASE2 输出')
    else:
        check_nodata(output_tif_path, expected=-32767, label='4326/裁剪 输出')

    try: os.remove(output_tif_path0)
    except: pass
    try: os.remove(mosaic_vrt)
    except: pass

    return output_tif_path

# ====================== 合并（TB 多通道 + IA） ======================
def mergy_day(files_str_list, tb_name, work_folder):
    if not files_str_list: return 0
    su_t = 0
    tb_band_names = ['10V','10H'] if band_ids==[1,2] else [f for i,f in enumerate(['10V','10H','18V','18H','23V','23H','36V','36H','89V','89H'],1) if i in band_ids]
    zenith_name   = 'Sensor_Zenith'

    # 逐文件 geoloc：TB 各通道 + IA
    for file in files_str_list:
        for idx in band_ids:
            geoloc_hdf('//Calibration/EARTH_OBSERVE_BT_10_to_89GHz', file,
                       ['10V','10H','18V','18H','23V','23H','36V','36H','89V','89H'], [idx], work_folder)
        geoloc_hdf('//Geolocation/Sensor_Zenith', file, [zenith_name], [1], work_folder)
        su_t += 1
    if su_t == 0: return 0

    # 日内拼接
    tb_tifs = []
    for bname in tb_band_names:
        t = merge_allto_tif(work_folder, bname)
        if not t: return 0
        tb_tifs.append(t)
    ia_tif = merge_allto_tif(work_folder, zenith_name)
    if not ia_tif: return 0

    # 合并
    # band_tag = ''.join(tb_band_names)
    # tb_band_name = f'{tb_name}_{band_tag}'
    # mergy_filetifname0 = os.path.join(work_folder, f'FY3D_GBAL_L1_{tb_band_name}_{day}_{op_orbit}_1.tif')
    # inputs = " ".join(f'"{p}"' for p in (tb_tifs + [ia_tif]))
    # cmd = (
    #     f'"{sys.executable}" -m osgeo_utils.gdal_merge '
    #     f'-o "{mergy_filetifname0}" -separate '
    #     f'-a_nodata -32767 -n -32767 '
    #     f'-co "COMPRESS=PACKBITS" -co "TILED=YES" '
    #     f'{inputs}'
    # )
    # proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # 用 OSGeo4W 的 python 直接跑 gdal_merge.py（不要用 .bat，也不要自己拼 inputs 字符串）
    # --- 用 OSGeo4W 的 python 直接跑 gdal_merge.py（不走 .bat）---
    # 合并
    # ===== 合并：用 gdalbuildvrt -separate（不走 python，避免 ImportError: site）=====
    # 合并
    band_tag = ''.join(tb_band_names)
    tb_band_name = f'{tb_name}_{band_tag}'

    # ===== 合并：用 gdalbuildvrt -separate（不走 python，避免 ImportError: site）=====
    mergy_vrt0 = os.path.join(
        work_folder, f'FY3D_GBAL_L1_{tb_band_name}_{day}_{op_orbit}_1.vrt'
    )

    inputs = " ".join(f'"{p}"' for p in (tb_tifs + [ia_tif]))

    cmd = (
        f'"{GDAL_BUILDVRT}" -separate '
        f'-srcnodata -32767 -vrtnodata -32767 '
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
    mergy_filetifname = os.path.join(work_folder, f'FY3D_GBAL_L1_{tb_band_name}_{day}_{op_orbit}.tif')

    # 最终 GeoTIFF（从 VRT 导出）
    cmd = (
        f'"{GDAL_TRANSLATE}" -of GTiff -a_nodata -32767 -ot Float32 '
        f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
        f'{metadata_strs} "{mergy_vrt0}" "{mergy_filetifname}"'
    )
    subprocess.run(cmd, shell=True, check=True)

    try:
        os.remove(mergy_vrt0)
    except:
        pass


    # ===== 输出（按 nodata 掩膜 → NaN；不把 0 当缺测） =====
    if outfile_type == 1:
        output_nc_path = os.path.join(work_folder, f'FY3D_GBAL_L1_{tb_band_name}_{day}_{op_orbit}.nc')
        with rasterio.open(mergy_filetifname) as src0:
            band0 = src0.read(1)
        ncfile = nc.Dataset(output_nc_path, 'w', format='NETCDF4')
        ncfile.createDimension('x', band0.shape[0]); ncfile.createDimension('y', band0.shape[1])
        with rasterio.open(mergy_filetifname) as src:
            for idx, band_name in enumerate(selected, start=1):
                arr = src.read(idx, masked=True).astype(np.float32)
                band = np.ma.filled(arr, np.nan)
                if band_name == 'Sensor_Zenith':
                    var = ncfile.createVariable(band_name, np.float32, ('x','y'))
                    var[:, :] = band; var.units='degree'; var.Valid_range=[0,18000]
                    var.FillValue=-32767; var.Intercept=0; var.Slope=0.010000; var.Long_name='Sensor_Zenith'
                else:
                    number_part = ''.join(filter(str.isdigit, band_name))
                    letter_part = ''.join(filter(str.isalpha, band_name))
                    vari_name = f'EARTH OBSERVE BT {number_part}GHz {letter_part}'
                    var = ncfile.createVariable(vari_name, np.float32, ('x','y'))
                    var[:, :] = band; var.units='K'; var.Valid_range=[-32766,10000]
                    var.FillValue=-32767; var.Intercept=327.679993; var.Slope=0.010000
                    var.Long_name = f'{number_part}GHZ {letter_part} Earth Observation Brightness Temperature'
        ncfile.close()
        print(f'{output_nc_path} 融合成功')

    if outfile_type == 2:
        output_hdf_path = os.path.join(work_folder, f'FY3D_GBAL_L1_{tb_band_name}_{day}_{op_orbit}.hdf')
        tmp_hdf = output_hdf_path + '.tmp'
        try:
            with h5py.File(tmp_hdf, 'w') as h5, rasterio.open(mergy_filetifname) as src:
                for idx, band_name in enumerate(selected, start=1):
                    arr = src.read(idx, masked=True).astype(np.float32)
                    band = np.ma.filled(arr, np.nan)
                    if band_name == 'Sensor_Zenith':
                        d = h5.create_dataset(band_name, data=band)
                        d.attrs.update({'units':'degree','Valid range':'0 18000','FillValue':-32767,
                                        'Intercept':0,'Slope':0.010000,'Long_name':'Sensor_Zenith'})
                    else:
                        number_part = ''.join(filter(str.isdigit, band_name))
                        letter_part = ''.join(filter(str.isalpha, band_name))
                        vari_name = f'EARTH OBSERVE BT {number_part}GHz {letter_part}'
                        d = h5.create_dataset(vari_name, data=band)
                        d.attrs.update({'units':'K','Valid range':'-32766 10000','FillValue':-32767,
                                        'Intercept':327.679993,'Slope':0.010000,
                                        'Long_name':f'{number_part}GHZ {letter_part} Earth Observation Brightness Temperature'})
            os.replace(tmp_hdf, output_hdf_path)
            print(f'{output_hdf_path} 融合成功')
        except Exception:
            try:
                if os.path.exists(tmp_hdf): os.remove(tmp_hdf)
            except: pass
            raise

    # 清理
    try:
        for p in [os.path.join(work_folder, 'vrt*.tif'), os.path.join(work_folder, '*.vrt')]:
            for f in glob.glob(p):
                try: os.remove(f)
                except: pass
    except: pass

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

    # 名称常量
    subdataset_path1 = '//Calibration/EARTH_OBSERVE_BT_10_to_89GHz'
    subdataset_path2 = '//Geolocation/Sensor_Zenith'
    band_names = ['10V','10H','18V','18H','23V','23H','36V','36H','89V','89H']

    # 目录策略
    if op_orbit == 'Both':
        out_MWRID = os.path.join(output_root, 'MWRID')
        out_MWRIA = os.path.join(output_root, 'MWRIA')
        os.makedirs(out_MWRID, exist_ok=True); os.makedirs(out_MWRIA, exist_ok=True)
    else:
        os.makedirs(output_root, exist_ok=True)

    day_exist = False
    for day in dates_str_list:
        A_files, D_files = [], []
        for file in os.listdir(FY_folder):
            if file.endswith('.HDF') and day in file:
                day_exist = True
                if 'MWRID' in file: D_files.append(file)
                if 'MWRIA' in file: A_files.append(file)

        if not (A_files or D_files): continue

        if op_orbit == 'MWRID' and D_files:
            print(day, '[MWRID]')
            mergy_day(D_files, 'MWRID', output_root)
        elif op_orbit == 'MWRIA' and A_files:
            print(day, '[MWRIA]')
            mergy_day(A_files, 'MWRIA', output_root)
        elif op_orbit == 'Both':
            if D_files:
                print(day, '[MWRID]'); mergy_day(D_files, 'MWRID', out_MWRID)
            if A_files:
                print(day, '[MWRIA]'); mergy_day(A_files, 'MWRIA', out_MWRIA)

    if not day_exist:
        print("------输入的时间范围内无数据存在!!! ------"); sys.exit(0)



# # -*- coding: utf-8 -*-
# # 在gdal311，多切换一下
# import sys, os, subprocess, glob
# import json, re
# import numpy as np, pandas as pd, calendar
# import rasterio
# import netCDF4 as nc, h5py

# # ====================== 固定使用 OSGeo4W 的 GDAL ======================
# FORCE_GDAL_BIN = r"C:\OSGeo4W\bin"

# # ====================== 定位 GDAL 可执行文件 ======================
# def _resolve_gdal_bins():
#     def ok(p): return p and os.path.exists(p)
#     tried = []
#     def try_prefix(prefix):
#         if not prefix or not os.path.isdir(prefix): return None
#         t = os.path.join(prefix, "gdal_translate.exe")
#         b = os.path.join(prefix, "gdalbuildvrt.exe")
#         w = os.path.join(prefix, "gdalwarp.exe")
#         i = os.path.join(prefix, "gdalinfo.exe")
#         tried.extend([t,b,w,i])
#         return (t,b,w,i,prefix) if all(map(ok,[t,b,w,i])) else None

#     # 0) 强制 OSGeo4W\bin
#     fb = (FORCE_GDAL_BIN or "").strip().rstrip("/\\")
#     found = try_prefix(fb)
#     if found: return found

#     # 1) CONDA_PREFIX\Library\bin
#     cp = os.environ.get("CONDA_PREFIX","")
#     found = try_prefix(os.path.join(cp, "Library", "bin"))
#     if found: return found

#     # 2) 从 python.exe 反推 \Library\bin
#     exe = os.path.abspath(sys.executable)
#     found = try_prefix(os.path.join(os.path.dirname(os.path.dirname(exe)), "Library", "bin"))
#     if found: return found

#     # 3) PATH
#     import shutil as _sh
#     t = _sh.which("gdal_translate") or _sh.which("gdal_translate.exe")
#     b = _sh.which("gdalbuildvrt")  or _sh.which("gdalbuildvrt.exe")
#     w = _sh.which("gdalwarp")      or _sh.which("gdalwarp.exe")
#     i = _sh.which("gdalinfo")      or _sh.which("gdalinfo.exe")
#     tried.extend([t,b,w,i])
#     if t and b and w and i:
#         return t,b,w,i,os.path.dirname(t)

#     detail = "\n  - ".join([str(x) for x in tried if x])
#     raise FileNotFoundError("未能定位到 GDAL 可执行文件。\n已尝试：\n  - " + detail)

# GDAL_TRANSLATE, GDAL_BUILDVRT, GDAL_WARP, GDAL_INFO, GDAL_BIN_PREFIX = _resolve_gdal_bins()

# # ====================== 小工具：nodata 检查 ======================
# def check_nodata(path, expected=-32767, expected_epsg=None, expected_size=None, label=''):
#     try:
#         with rasterio.open(path) as ds:
#             nodas = ds.nodatavals
#             try:
#                 crs_epsg = ds.crs.to_epsg() if ds.crs else None
#             except Exception:
#                 crs_epsg = None
#             size = (ds.width, ds.height)
#         print(f'[CHECK] {label} | {os.path.basename(path)}')
#         print(f'        bands={len(nodas)} nodata={nodas}')
#         if expected is not None:
#             ok = True
#             for i,v in enumerate(nodas,1):
#                 if v is None or int(v) != int(expected):
#                     ok = False
#                     print(f'        WARN: band#{i} nodata={v} != {expected}')
#             if ok: print('        OK: nodata 全部匹配预期。')
#         if expected_epsg is not None:
#             if crs_epsg != expected_epsg: print(f'        WARN: EPSG={crs_epsg} != {expected_epsg}')
#             else: print(f'        OK: EPSG={crs_epsg}')
#         if expected_size is not None:
#             if size != tuple(expected_size): print(f'        WARN: size={size} != {tuple(expected_size)}')
#             else: print(f'        OK: size={size}')
#     except Exception as e:
#         print(f'[CHECK] {label} | 打开失败：{e}')

# # *********************************  用户输入参数  **********************************
# FY_folder   = r'F:\FY3D_MWRI\19-23'
# band_ids    = [1, 2]          # 10V, 10H —— 单通道法会逐个处理
# op_orbit    = 'MWRID'         # 'MWRID'/'MWRIA'/'Both'
# output_root = r'F:\FY3D_output\MWRIDfinalfinal'

# year_start, year_end   = 2019, 2024
# month_start, month_end = 1, 12

# dates_str_list = []
# for y in range(year_start, year_end+1):
#     sm = month_start if y==year_start else 1
#     em = month_end   if y==year_end   else 12
#     for m in range(sm, em+1):
#         last_day = calendar.monthrange(y,m)[1]
#         for d in pd.date_range(pd.Timestamp(y,m,1), pd.Timestamp(y,m,last_day), freq='D'):
#             dates_str_list.append(d.strftime('%Y%m%d'))
# if not dates_str_list:
#     print("------输入的时间范围无效!!! ------"); sys.exit(0)

# overlap_option = 'average'
# outfile_type   = 2           # 0:GTiff 1:NetCDF 2:HDF5

# spatial_extent = 0  # 0 全球；1 单点；2 矩形；3 Shapefile
# if spatial_extent == 1:
#     point = [120, 20]; buffer_x, buffer_y = 0.01, 0.01
# if spatial_extent == 2:
#     lat_lon = [-110, -10, 110, 10]
# if spatial_extent == 3:
#     shapefile_path = r'E:\FY3D\FY3D\output2\china.shp'
# # **********************************  用户输入参数结束  **********************************

# # ====================== 构造 HDF5 SDS URI ======================
# def _hdf5_sds(hdf_path, sds_path):
#     """返回 HDF5:"<win路径原样>":<SDS 路径> —— 不动斜杠"""
#     return f'HDF5:"{hdf_path}":{sds_path}'

# # ====================== 单通道 geoloc → 4326 ======================
# def geoloc_hdf(subdataset_path, file, band_names, band_ids_one, work_folder):
#     """
#     单通道法：一次仅处理一个波段索引（band_ids_one 长度为 1）
#     —— 直接用 HDF5:"file":<SDS>；不再走 gdalinfo 枚举。
#     —— 所有 GDAL 调用改为“字符串命令 + shell=True”。
#     """
#     assert len(band_ids_one) == 1
#     band_name = band_names[band_ids_one[0] - 1]  # 如 '10V'

#     os.makedirs(work_folder, exist_ok=True)
#     hdf_path = os.path.join(FY_folder, file)

#     # 1) 数据 VRT（修复：-b 位置置于 src/dst 之前）
#     data_uri = _hdf5_sds(hdf_path, subdataset_path)
#     vrt_path = os.path.join(work_folder, f'temp_{file[:-4]}_{band_name}.vrt')
#     cmd = (
#         f'"{GDAL_TRANSLATE}" -of VRT -a_nodata -32767 '
#         f'-b {band_ids_one[0]} {data_uri} "{vrt_path}"'
#     )
#     subprocess.run(cmd, shell=True, check=True)

#     # 2) 纬度/经度 VRT
#     vrtlat_path = os.path.join(work_folder, f'lat_{file[:-4]}_{band_name}.vrt')
#     lat_uri = _hdf5_sds(hdf_path, '//Geolocation/Latitude')
#     cmd = f'"{GDAL_TRANSLATE}" -of VRT -a_nodata 65535 {lat_uri} "{vrtlat_path}"'
#     subprocess.run(cmd, shell=True, check=True)

#     vrtlon_path = os.path.join(work_folder, f'lon_{file[:-4]}.vrt')
#     lon_uri = _hdf5_sds(hdf_path, '//Geolocation/Longitude')
#     cmd = f'"{GDAL_TRANSLATE}" -of VRT -a_nodata 65535 {lon_uri} "{vrtlon_path}"'
#     subprocess.run(cmd, shell=True, check=True)

#     # 3) 注入 GEOLOCATION —— SRS 单一条目
#     metadata_content = f'''<Metadata domain="GEOLOCATION">
#             <MDI key="LINE_OFFSET">0</MDI>
#             <MDI key="LINE_STEP">1</MDI>
#             <MDI key="PIXEL_OFFSET">0</MDI>
#             <MDI key="PIXEL_STEP">1</MDI>
#             <MDI key="SRS">GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],TOWGS84[0,0,0,0,0,0,0],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],AUTHORITY["EPSG","4326"]]</MDI>
#             <MDI key="X_BAND">1</MDI>
#             <MDI key="X_DATASET">{vrtlon_path}</MDI>
#             <MDI key="Y_BAND">1</MDI>
#             <MDI key="Y_DATASET">{vrtlat_path}</MDI>
#         </Metadata>
#     '''
#     with open(vrt_path, encoding='utf-8') as f, open(vrt_path.replace('.vrt', 'new.vrt'), 'w', encoding='utf-8') as g:
#         insert_metadata = False
#         for line in f:
#             if '</Metadata>' in line: insert_metadata = True
#             if '<GCPList Projection="GEOGCS[&quot;WGS 84&quot' in line and insert_metadata:
#                 g.write(metadata_content); insert_metadata = False
#             g.write(line)

#     vrt_path0 = os.path.join(work_folder, f'temp_{file[:-4]}_{band_name}new.vrt')
#     tif_path  = os.path.join(work_folder, f'vrt_{file[:-4]}_{band_name}.tif')

#     # 4) geoloc → 4326
#     print(f'开始地理查找表校正... ({band_name})')
#     cmd = (
#         f'"{GDAL_WARP}" -geoloc -t_srs EPSG:4326 '
#         f'-srcnodata -32767 -dstnodata -32767 '
#         f'-of GTiff -ot Float32 -r {overlap_option} '
#         f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
#         f'"{vrt_path0}" "{tif_path}"'
#     )
#     subprocess.run(cmd, shell=True, check=True)

#     check_nodata(vrt_path0, expected=-32767, label=f'VRT (geoloc src) {band_name}')
#     check_nodata(tif_path,  expected=-32767, label=f'geoloc→4326 输出 {band_name}')
#     return band_name

# # ====================== 日内拼接 + 重投影 ======================
# def merge_allto_tif(work_folder, band_name):
#     os.makedirs(work_folder, exist_ok=True)
#     mosaic_vrt = os.path.join(work_folder, f'mosaic_{band_name}.vrt')

#     src_list = sorted(glob.glob(os.path.join(work_folder, f'vrt*{band_name}.tif')))
#     if not src_list:
#         print(f'没有找到待拼接的文件：{os.path.join(work_folder, f"vrt*{band_name}.tif")}')
#         return None

#     inputs = ' '.join(f'"{p}"' for p in src_list)
#     # === 关键改动：显式声明 nodata，防止 nodata 参与平均 ===
#     cmd = f'"{GDAL_BUILDVRT}" -srcnodata -32767 -vrtnodata -32767 "{mosaic_vrt}" {inputs}'
#     print("Running:", cmd)
#     proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
#     if proc.returncode != 0:
#         print(f"Error executing gdalbuildvrt:\n{proc.stderr}")
#         return None
#     print("VRT creation successful.")
#     check_nodata(mosaic_vrt, expected=-32767, label=f'mosaic_{band_name}.vrt (日内拼接)')

#     # 4326 → EASE2
#     print('开始融合数据...')
#     output_tif_path  = os.path.join(work_folder, f'FY3D_GBAL_L1_{band_name}_{day}_{op_orbit}_0.tif')
#     output_tif_path0 = os.path.join(work_folder, f'FY3D_GBAL_L1_{band_name}_{day}_{op_orbit}_01.tif')

#     # 先到 4326（修复：显式 Float32 + 压缩预测器=3）
#     cmd = (
#         f'"{GDAL_WARP}" -of GTiff -ot Float32 -r {overlap_option} '
#         f'-srcnodata -32767 -dstnodata -32767 '
#         f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
#         f'"{mosaic_vrt}" "{output_tif_path0}"'
#     )
#     subprocess.run(cmd, shell=True, check=True)
#     check_nodata(output_tif_path0, expected=-32767, label='mosaic→4326 输出')

#     # 再到 EASE2（各范围分支统一 Float32 + 压缩）
#     if spatial_extent == 0:
#         cmd = (
#             f'"{GDAL_WARP}" -overwrite -t_srs EPSG:6933 '
#             f'-te -17367530.45 -7314540.83 17367530.45 7314540.83 '
#             f'-ts 3856 1624 -r average '
#             f'-srcnodata -32767 -dstnodata -32767 '
#             f'-of GTiff -ot Float32 '
#             f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
#             f'"{output_tif_path0}" "{output_tif_path}"'
#         )
#     elif spatial_extent == 1:
#         min_x, max_x = point[0]-buffer_x, point[0]+buffer_x
#         min_y, max_y = point[1]-buffer_y, point[1]+buffer_y
#         cmd = (
#             f'"{GDAL_WARP}" -of GTiff -ot Float32 -r {overlap_option} '
#             f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
#             f'-te {min_x} {min_y} {max_x} {max_y} '
#             f'"{mosaic_vrt}" "{output_tif_path}"'
#         )
#     elif spatial_extent == 2:
#         cmd = (
#             f'"{GDAL_WARP}" -of GTiff -ot Float32 -r {overlap_option} '
#             f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
#             f'-te {lat_lon[0]} {lat_lon[1]} {lat_lon[2]} {lat_lon[3]} '
#             f'"{mosaic_vrt}" "{output_tif_path}"'
#         )
#     else:
#         out0 = os.path.join(work_folder, f'FY3D_GBAL_L1_{band_name}_{day}_{op_orbit}_0.tif')
#         out1 = os.path.join(work_folder, f'FY3D_GBAL_L1_{band_name}_{day}_{op_orbit}.tif')
#         cmd = (
#             f'"{GDAL_WARP}" -of GTiff -ot Float32 -r {overlap_option} '
#             f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" "{mosaic_vrt}" "{out0}"'
#         )
#         subprocess.run(cmd, shell=True, check=True)
#         print('开始剪切...')
#         cmd = (
#             f'"{GDAL_WARP}" -cutline "{shapefile_path}" -crop_to_cutline '
#             f'-of GTiff -ot Float32 -co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" "{out0}" "{out1}"'
#         )
#         output_tif_path = out1

#     subprocess.run(cmd, shell=True, check=True)

#     if spatial_extent == 0:
#         check_nodata(output_tif_path, expected=-32767, expected_epsg=6933, expected_size=(3856,1624), label='4326→EASE2 输出')
#     else:
#         check_nodata(output_tif_path, expected=-32767, label='4326/裁剪 输出')

#     try: os.remove(output_tif_path0)
#     except: pass
#     try: os.remove(mosaic_vrt)
#     except: pass

#     return output_tif_path

# # ====================== 合并（TB 多通道 + IA） ======================
# def mergy_day(files_str_list, tb_name, work_folder):
#     if not files_str_list: return 0
#     su_t = 0
#     tb_band_names = ['10V','10H'] if band_ids==[1,2] else [f for i,f in enumerate(['10V','10H','18V','18H','23V','23H','36V','36H','89V','89H'],1) if i in band_ids]
#     zenith_name   = 'Sensor_Zenith'

#     # 逐文件 geoloc：TB 各通道 + IA
#     for file in files_str_list:
#         for idx in band_ids:
#             geoloc_hdf('//Calibration/EARTH_OBSERVE_BT_10_to_89GHz', file, ['10V','10H','18V','18H','23V','23H','36V','36H','89V','89H'], [idx], work_folder)
#         geoloc_hdf('//Geolocation/Sensor_Zenith', file, [zenith_name], [1], work_folder)
#         su_t += 1
#     if su_t == 0: return 0

#     # 日内拼接
#     tb_tifs = []
#     for bname in tb_band_names:
#         t = merge_allto_tif(work_folder, bname)
#         if not t: return 0
#         tb_tifs.append(t)
#     ia_tif = merge_allto_tif(work_folder, zenith_name)
#     if not ia_tif: return 0

#     # 合并
#     band_tag = ''.join(tb_band_names)
#     tb_band_name = f'{tb_name}_{band_tag}'
#     mergy_filetifname0 = os.path.join(work_folder, f'FY3D_GBAL_L1_{tb_band_name}_{day}_{op_orbit}_1.tif')
#     inputs = " ".join(f'"{p}"' for p in (tb_tifs + [ia_tif]))
#     cmd = (
#         f'"{sys.executable}" -m osgeo_utils.gdal_merge '
#         f'-o "{mergy_filetifname0}" -separate '
#         f'-a_nodata -32767 -n -32767 '
#         f'-co "COMPRESS=PACKBITS" -co "TILED=YES" '
#         f'{inputs}'
#     )
#     proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
#     if proc.returncode != 0 or (not os.path.exists(mergy_filetifname0)):
#         print('gdal_merge 失败：', proc.stderr)
#         print('命令：', cmd)
#         return 0

#     selected = tb_band_names + [zenith_name]
#     metadata_strs = " ".join(f'-mo Band_{i}={name}' for i, name in enumerate(selected, start=1))
#     mergy_filetifname = os.path.join(work_folder, f'FY3D_GBAL_L1_{tb_band_name}_{day}_{op_orbit}.tif')

#     # 最终 GeoTIFF（修复：显式压缩/预测器/分块 + Float32）
#     cmd = (
#         f'"{GDAL_TRANSLATE}" -of GTiff -a_nodata -32767 -ot Float32 '
#         f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
#         f'{metadata_strs} "{mergy_filetifname0}" "{mergy_filetifname}"'
#     )
#     subprocess.run(cmd, shell=True, check=True)
#     try: os.remove(mergy_filetifname0)
#     except: pass

#     # ===== 输出（按 nodata 掩膜 → NaN；不把 0 当缺测） =====
#     if outfile_type == 1:
#         output_nc_path = os.path.join(work_folder, f'FY3D_GBAL_L1_{tb_band_name}_{day}_{op_orbit}.nc')
#         with rasterio.open(mergy_filetifname) as src0:
#             band0 = src0.read(1)
#         ncfile = nc.Dataset(output_nc_path, 'w', format='NETCDF4')
#         ncfile.createDimension('x', band0.shape[0]); ncfile.createDimension('y', band0.shape[1])
#         with rasterio.open(mergy_filetifname) as src:
#             for idx, band_name in enumerate(selected, start=1):
#                 arr = src.read(idx, masked=True).astype(np.float32)
#                 band = np.ma.filled(arr, np.nan)
#                 if band_name == 'Sensor_Zenith':
#                     var = ncfile.createVariable(band_name, np.float32, ('x','y'))
#                     var[:, :] = band; var.units='degree'; var.Valid_range=[0,18000]
#                     var.FillValue=-32767; var.Intercept=0; var.Slope=0.010000; var.Long_name='Sensor_Zenith'
#                 else:
#                     number_part = ''.join(filter(str.isdigit, band_name))
#                     letter_part = ''.join(filter(str.isalpha, band_name))
#                     vari_name = f'EARTH OBSERVE BT {number_part}GHz {letter_part}'
#                     var = ncfile.createVariable(vari_name, np.float32, ('x','y'))
#                     var[:, :] = band; var.units='K'; var.Valid_range=[-32766,10000]
#                     var.FillValue=-32767; var.Intercept=327.679993; var.Slope=0.010000
#                     var.Long_name = f'{number_part}GHZ {letter_part} Earth Observation Brightness Temperature'
#         ncfile.close()
#         print(f'{output_nc_path} 融合成功')

#     if outfile_type == 2:
#         output_hdf_path = os.path.join(work_folder, f'FY3D_GBAL_L1_{tb_band_name}_{day}_{op_orbit}.hdf')
#         tmp_hdf = output_hdf_path + '.tmp'
#         try:
#             with h5py.File(tmp_hdf, 'w') as h5, rasterio.open(mergy_filetifname) as src:
#                 for idx, band_name in enumerate(selected, start=1):
#                     arr = src.read(idx, masked=True).astype(np.float32)
#                     band = np.ma.filled(arr, np.nan)
#                     if band_name == 'Sensor_Zenith':
#                         d = h5.create_dataset(band_name, data=band)
#                         d.attrs.update({'units':'degree','Valid range':'0 18000','FillValue':-32767,
#                                         'Intercept':0,'Slope':0.010000,'Long_name':'Sensor_Zenith'})
#                     else:
#                         number_part = ''.join(filter(str.isdigit, band_name))
#                         letter_part = ''.join(filter(str.isalpha, band_name))
#                         vari_name = f'EARTH OBSERVE BT {number_part}GHz {letter_part}'
#                         d = h5.create_dataset(vari_name, data=band)
#                         d.attrs.update({'units':'K','Valid range':'-32766 10000','FillValue':-32767,
#                                         'Intercept':327.679993,'Slope':0.010000,
#                                         'Long_name':f'{number_part}GHZ {letter_part} Earth Observation Brightness Temperature'})
#             os.replace(tmp_hdf, output_hdf_path)
#             print(f'{output_hdf_path} 融合成功')
#         except Exception:
#             try:
#                 if os.path.exists(tmp_hdf): os.remove(tmp_hdf)
#             except: pass
#             raise

#     # 清理
#     try:
#         for p in [os.path.join(work_folder, 'vrt*.tif'), os.path.join(work_folder, '*.vrt')]:
#             for f in glob.glob(p):
#                 try: os.remove(f)
#                 except: pass
#     except: pass

#     return 1

# # ====================== 主流程 ======================
# if __name__ == '__main__':
#     print("PY :", sys.version)
#     try:
#         from osgeo import gdal
#         print("GDAL VersionInfo():", gdal.VersionInfo())
#     except Exception as e:
#         print("导入 osgeo 失败（不影响外部 exe 调用）：", e)
#     print("GDAL_TRANSLATE :", GDAL_TRANSLATE)
#     print("GDAL_BUILDVRT  :", GDAL_BUILDVRT)
#     print("GDAL_WARP      :", GDAL_WARP)
#     print("GDAL_INFO      :", GDAL_INFO)

#     # 名称常量
#     subdataset_path1 = '//Calibration/EARTH_OBSERVE_BT_10_to_89GHz'
#     subdataset_path2 = '//Geolocation/Sensor_Zenith'
#     band_names = ['10V','10H','18V','18H','23V','23H','36V','36H','89V','89H']

#     # 目录策略
#     if op_orbit == 'Both':
#         out_MWRID = os.path.join(output_root, 'MWRID')
#         out_MWRIA = os.path.join(output_root, 'MWRIA')
#         os.makedirs(out_MWRID, exist_ok=True); os.makedirs(out_MWRIA, exist_ok=True)
#     else:
#         os.makedirs(output_root, exist_ok=True)

#     day_exist = False
#     for day in dates_str_list:
#         A_files, D_files = [], []
#         for file in os.listdir(FY_folder):
#             if file.endswith('.HDF') and day in file:
#                 day_exist = True
#                 if 'MWRID' in file: D_files.append(file)
#                 if 'MWRIA' in file: A_files.append(file)

#         if not (A_files or D_files): continue

#         if op_orbit == 'MWRID' and D_files:
#             print(day, '[MWRID]')
#             mergy_day(D_files, 'MWRID', output_root)
#         elif op_orbit == 'MWRIA' and A_files:
#             print(day, '[MWRIA]')
#             mergy_day(A_files, 'MWRIA', output_root)
#         elif op_orbit == 'Both':
#             if D_files:
#                 print(day, '[MWRID]'); mergy_day(D_files, 'MWRID', out_MWRID)
#             if A_files:
#                 print(day, '[MWRIA]'); mergy_day(A_files, 'MWRIA', out_MWRIA)

#     if not day_exist:
#         print("------输入的时间范围内无数据存在!!! ------"); sys.exit(0)
