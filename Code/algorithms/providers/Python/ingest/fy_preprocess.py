r"""FY-3B/3D MWRI HDF 亮温预处理模块。

合并自 Matlab 目录下的 FY3B.py 和 FY3dfinalfinal.py，提供统一的 GDAL 预处理接口：
- HDF geolocation 校正（geoloc → EPSG:4326）
- 日内轨道拼接（gdalbuildvrt + gdalwarp）
- 多通道合并（TB + SensorZenith → GeoTIFF/HDF5/NetCDF）
- EASE-Grid 2.0 (EPSG:6933) 重投影

用法：
    from ingest.fy_preprocess import FyPreprocessor, FySatelliteConfig

    config = FySatelliteConfig.for_fy3d()
    prep = FyPreprocessor(config)
    prep.process_date_range(
        input_dir=r"I:\Geograph_DataSet\Soil_Moisture\FY3D",
        output_dir=r"I:\Geograph_DataSet\Soil_Moisture\FY3D\output",
        start_date="2015-01-01",
        end_date="2015-12-31",
        orbit_mode="MWRID",
        band_ids=[1, 2],
    )
"""

from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from collections.abc import Sequence

import h5py
import netCDF4 as nc
import numpy as np
import rasterio

# EASE-Grid 2.0 全球投影参数（精确 NSIDC 对称角点，禁止两位小数近似）
from data_access.ease_grid_constants import EASE2_GLOBAL_BOUNDS, EASE2_SHAPE_9KM
import contextlib

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GDAL 可执行文件定位（跨平台：Windows OSGeo4W/QGIS/conda 布局 + Linux
# conda/PATH；env CGDA_GDAL_BIN 两平台均优先生效）
# ---------------------------------------------------------------------------

_FORCE_GDAL_BIN = r"C:\OSGeo4W\bin"  # 仅 Windows 探测（历史 OSGeo4W 布局）
_IS_WINDOWS = os.name == "nt"
_GDAL_SUFFIX = ".exe" if _IS_WINDOWS else ""


def _qgis_candidates() -> list[str]:
    """QGIS 官方安装布局候选（仅 Windows：``C:\\Program Files\\QGIS*\\bin``）。"""
    if not _IS_WINDOWS:
        return []
    import glob as _glob

    roots = _glob.glob(r"C:\Program Files\QGIS*\bin") + _glob.glob(
        r"C:\Program Files (x86)\QGIS*\bin"
    )
    return sorted(roots, reverse=True)


def _resolve_gdal_bins() -> tuple[str, str, str, str, str]:
    """定位 GDAL 可执行文件（gdal_translate / gdalbuildvrt / gdalwarp / gdalinfo）。

    解析顺序（按平台）：
    - 环境变量 ``CGDA_GDAL_BIN``（两平台均优先，指向含 GDAL CLI 的 bin 目录）
    - Windows：历史 OSGeo4W 默认 → QGIS 官方安装目录
      （``C:\\Program Files\\QGIS*\\bin``，取最高版本）→ conda（Library/bin）
    - Linux/macOS：conda（``$CONDA_PREFIX/bin`` 与解释器同级 bin）
    - PATH（``shutil.which``，两平台）
    """

    def _ok(p: str | None) -> bool:
        return bool(p) and os.path.exists(p)

    def _try_prefix(prefix: str) -> tuple[str, str, str, str, str] | None:
        if not prefix or not os.path.isdir(prefix):
            return None
        t = os.path.join(prefix, "gdal_translate" + _GDAL_SUFFIX)
        b = os.path.join(prefix, "gdalbuildvrt" + _GDAL_SUFFIX)
        w = os.path.join(prefix, "gdalwarp" + _GDAL_SUFFIX)
        i = os.path.join(prefix, "gdalinfo" + _GDAL_SUFFIX)
        if all(map(_ok, [t, b, w, i])):
            return t, b, w, i, prefix
        return None

    fb = os.environ.get("CGDA_GDAL_BIN", "").strip().rstrip("/\\")
    found = _try_prefix(fb)
    if found:
        return found

    if _IS_WINDOWS:
        for prefix in (_FORCE_GDAL_BIN, *_qgis_candidates()):
            found = _try_prefix(prefix)
            if found:
                return found

    # conda：Windows 为 <prefix>/Library/bin；Linux 为 <prefix>/bin。
    cp = os.environ.get("CONDA_PREFIX", "")
    conda_candidates = [
        os.path.join(cp, "Library", "bin"),
        os.path.join(cp, "bin"),
    ]
    exe = os.path.abspath(sys.executable)
    exe_base = os.path.dirname(os.path.dirname(exe))
    conda_candidates.append(os.path.join(exe_base, "Library", "bin"))
    conda_candidates.append(os.path.join(exe_base, "bin"))
    for cand in conda_candidates:
        found = _try_prefix(cand)
        if found:
            return found

    t = shutil.which("gdal_translate") or shutil.which("gdal_translate.exe")
    b = shutil.which("gdalbuildvrt") or shutil.which("gdalbuildvrt.exe")
    w = shutil.which("gdalwarp") or shutil.which("gdalwarp.exe")
    i = shutil.which("gdalinfo") or shutil.which("gdalinfo.exe")
    if t and b and w and i:
        return t, b, w, i, os.path.dirname(t)

    raise FileNotFoundError(
        "GDAL executables not found. "
        + (
            "Tried CGDA_GDAL_BIN, OSGeo4W, QGIS, conda and PATH."
            if _IS_WINDOWS
            else "Tried CGDA_GDAL_BIN, conda($CONDA_PREFIX/bin) and PATH."
        )
    )


# 延迟解析：允许模块在无 GDAL 环境下导入，实际使用时再解析
GDAL_TRANSLATE: str = ""
GDAL_BUILDVRT: str = ""
GDAL_WARP: str = ""
GDAL_INFO: str = ""
GDAL_BIN_PREFIX: str = ""


def _maybe_set_qgis_gdal_driver_path(bin_prefix: str) -> None:
    """QGIS 安装的 HDF5 驱动在 ``apps/gdal/lib/gdalplugins``，须设 GDAL_DRIVER_PATH。

    未设置时 gdal_translate 读 ``HDF5:"…"`` 会报
    ``plugin gdal_HDF5.dll is not available … GDAL_DRIVER_PATH is not set``，
    导致 fy_preprocess 全波段 SKIP、产物目录空仍「成功」。
    已有环境变量时不覆盖（尊重用户/运维显式配置）。
    """
    existing = os.environ.get("GDAL_DRIVER_PATH", "").strip()
    if existing:
        return
    if not bin_prefix:
        return
    root = os.path.dirname(os.path.abspath(bin_prefix))
    plugins = os.path.join(root, "apps", "gdal", "lib", "gdalplugins")
    if not os.path.isdir(plugins):
        return
    marker_dll = os.path.join(plugins, "gdal_HDF5.dll")
    marker_so = os.path.join(plugins, "gdal_HDF5.so")
    if not (os.path.exists(marker_dll) or os.path.exists(marker_so)):
        # 无 HDF5 插件时不设（避免掩盖其它驱动缺失）
        return
    os.environ["GDAL_DRIVER_PATH"] = plugins
    logger.info("GDAL_DRIVER_PATH set to QGIS plugins: %s", plugins)


def _ensure_gdal_bins() -> None:
    """延迟解析 GDAL 可执行文件路径，仅在首次实际使用时执行。"""
    global GDAL_TRANSLATE, GDAL_BUILDVRT, GDAL_WARP, GDAL_INFO, GDAL_BIN_PREFIX
    if GDAL_TRANSLATE:
        return
    bins = _resolve_gdal_bins()
    GDAL_TRANSLATE, GDAL_BUILDVRT, GDAL_WARP, GDAL_INFO, GDAL_BIN_PREFIX = bins
    _maybe_set_qgis_gdal_driver_path(GDAL_BIN_PREFIX)


# ---------------------------------------------------------------------------
# 卫星配置
# ---------------------------------------------------------------------------

_EASE2_GLOBAL_EXTENT = EASE2_GLOBAL_BOUNDS
_EASE2_GLOBAL_SIZE = (EASE2_SHAPE_9KM[1], EASE2_SHAPE_9KM[0])  # (cols, rows)

_TB_BAND_NAMES = [
    "10V",
    "10H",
    "18V",
    "18H",
    "23V",
    "23H",
    "36V",
    "36H",
    "89V",
    "89H",
]


@dataclass(frozen=True, slots=True)
class FySatelliteConfig:
    """卫星特定配置参数。"""

    satellite: str  # "FY3B" | "FY3D"
    tb_sds_path: str
    lat_sds_path: str
    lon_sds_path: str
    zen_sds_path: str
    zenith_name: str
    src_nodata: float
    dst_nodata: float
    latlon_nodata: float
    zen_nodata_fallback: float
    tb_slope: float
    tb_intercept: float
    zen_slope: float
    zen_intercept: float
    auto_detect_nodata: bool = False
    auto_detect_scale: bool = False

    @staticmethod
    def for_fy3d() -> FySatelliteConfig:
        """FY-3D MWRI 配置。"""
        return FySatelliteConfig(
            satellite="FY3D",
            tb_sds_path="//Calibration/EARTH_OBSERVE_BT_10_to_89GHz",
            lat_sds_path="//Geolocation/Latitude",
            lon_sds_path="//Geolocation/Longitude",
            zen_sds_path="//Geolocation/Sensor_Zenith",
            zenith_name="Sensor_Zenith",
            src_nodata=-32767.0,
            dst_nodata=-32767.0,
            latlon_nodata=65535.0,
            zen_nodata_fallback=32767.0,
            tb_slope=0.01,
            tb_intercept=327.679993,
            zen_slope=0.01,
            zen_intercept=0.0,
            auto_detect_nodata=False,
            auto_detect_scale=False,
        )

    @staticmethod
    def for_fy3b() -> FySatelliteConfig:
        """FY-3B MWRI 配置（增强版：自动识别 nodata 和 scale/offset）。"""
        return FySatelliteConfig(
            satellite="FY3B",
            tb_sds_path="//EARTH_OBSERVE_BT_10_to_89GHz",
            lat_sds_path="//Latitude",
            lon_sds_path="//Longitude",
            zen_sds_path="//SensorZenith",
            zenith_name="SensorZenith",
            src_nodata=-999.0,
            dst_nodata=-999.0,
            latlon_nodata=999.9,
            zen_nodata_fallback=32767.0,
            tb_slope=0.01,
            tb_intercept=327.679993,
            zen_slope=0.01,
            zen_intercept=0.0,
            auto_detect_nodata=True,
            auto_detect_scale=True,
        )

    @property
    def output_prefix(self) -> str:
        return f"{self.satellite}_GBAL_L1"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _hdf_sds(hdf_path: str, sds_path: str) -> str:
    """构造 HDF5 SDS URI。"""
    return f'HDF5:"{hdf_path}":{sds_path}'


def _run_gdalinfo(target_path: str) -> str:
    cmd = [GDAL_INFO, target_path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    return proc.stdout


def _parse_nodata_from_gdalinfo(text: str) -> float | None:
    m = re.search(r"NoData Value\s*=\s*([^\r\n]+)", text)
    if m:
        try:
            return float(m.group(1).strip().strip('"').strip("'"))
        except ValueError:
            pass
    for pat in (r"_FillValue\s*=\s*([^\r\n]+)", r"FillValue\s*=\s*([^\r\n]+)"):
        m = re.search(pat, text)
        if m:
            try:
                return float(m.group(1).strip().strip('"').strip("'"))
            except ValueError:
                pass
    return None


def _parse_metadata_value(text: str, key: str) -> str | None:
    m = re.search(rf"{re.escape(key)}\s*=\s*([^\r\n]+)", text)
    return m.group(1).strip() if m else None


def _get_src_nodata(
    hdf_path: str, sds_path: str, fallback: float, label: str = ""
) -> float:
    try:
        text = _run_gdalinfo(_hdf_sds(hdf_path, sds_path))
        nd = _parse_nodata_from_gdalinfo(text)
        if nd is not None:
            logger.info("%s 源 nodata 自动识别为: %s", label, nd)
            return nd
    except Exception as e:
        logger.warning(
            "%s 读取 gdalinfo 失败，改用 fallback=%s。错误：%s", label, fallback, e
        )
    logger.warning("%s 未识别到源 nodata，使用 fallback=%s", label, fallback)
    return float(fallback)


def _get_tb_scale_offset(hdf_path: str) -> tuple[float, float]:
    slope, intercept = 0.01, 327.679993
    try:
        text = _run_gdalinfo(hdf_path)
        v1 = _parse_metadata_value(
            text, "Calibration_EARTH_OBSERVE_BT_10_to_89GHz_Slope"
        )
        v2 = _parse_metadata_value(
            text, "Calibration_EARTH_OBSERVE_BT_10_to_89GHz_Intercept"
        )
        if v1 is not None:
            slope = float(v1)
        if v2 is not None:
            intercept = float(v2)
        logger.info("TB 系数: slope=%s, intercept=%s", slope, intercept)
    except Exception as e:
        logger.warning("无法自动读取 TB 系数，使用默认值。错误：%s", e)
    return slope, intercept


def _get_zen_scale_offset(hdf_path: str, zen_sds_path: str) -> tuple[float, float]:
    slope, intercept = 0.01, 0.0
    try:
        text = _run_gdalinfo(_hdf_sds(hdf_path, zen_sds_path))
        v1 = _parse_metadata_value(text, "Slope")
        v2 = _parse_metadata_value(text, "Intercept")
        if v1 is not None:
            slope = float(v1)
        if v2 is not None:
            intercept = float(v2)
        logger.info("SensorZenith 系数: slope=%s, intercept=%s", slope, intercept)
    except Exception as e:
        logger.warning("无法自动读取 SensorZenith 系数，使用默认值。错误：%s", e)
    return slope, intercept


def _check_nodata(
    path: str,
    expected: float | None = None,
    expected_epsg: int | None = None,
    expected_size: tuple[int, int] | None = None,
    label: str = "",
) -> None:
    try:
        with rasterio.open(path) as ds:
            nodas = ds.nodatavals
            try:
                crs_epsg = ds.crs.to_epsg() if ds.crs else None
            except Exception:
                crs_epsg = None
            size = (ds.width, ds.height)
        logger.debug(
            "[CHECK] %s | %s | bands=%d nodata=%s",
            label,
            os.path.basename(path),
            len(nodas),
            nodas,
        )
        if expected is not None:
            for i, v in enumerate(nodas, 1):
                if v is not None and abs(float(v) - expected) > 1e-6:
                    logger.debug("  WARN: band#%d nodata=%s != %s", i, v, expected)
        if expected_epsg is not None and crs_epsg != expected_epsg:
            logger.debug("  WARN: EPSG=%s != %s", crs_epsg, expected_epsg)
        if expected_size is not None and size != tuple(expected_size):
            logger.debug("  WARN: size=%s != %s", size, tuple(expected_size))
    except Exception as e:
        logger.debug("[CHECK] %s | 打开失败：%s", label, e)


# ---------------------------------------------------------------------------
# 预处理器
# ---------------------------------------------------------------------------


@dataclass
class FyPreprocessOptions:
    """预处理选项。"""

    band_ids: list[int] = field(default_factory=lambda: [1, 2])  # 10V, 10H
    orbit_mode: str = "MWRID"  # "MWRID" | "MWRIA" | "Both"
    overlap_option: str = "average"
    outfile_type: int = 2  # 0:GTiff 1:NetCDF 2:HDF5
    spatial_extent: int = 0  # 0:全球 1:单点 2:矩形 3:Shapefile
    point: tuple[float, float] = (120.0, 20.0)
    buffer_xy: tuple[float, float] = (0.01, 0.01)
    lat_lon_bbox: tuple[float, float, float, float] = (-110.0, -10.0, 110.0, 10.0)
    shapefile_path: str = ""


class FyPreprocessor:
    """FY-3B/3D MWRI 亮温预处理器。

    封装 HDF geolocation 校正、日内拼接、多通道合并和重投影逻辑。
    所有路径通过方法参数传入，不依赖全局变量。
    """

    def __init__(self, config: FySatelliteConfig) -> None:
        self.config = config
        self._band_names = _TB_BAND_NAMES
        _ensure_gdal_bins()  # 延迟解析 GDAL 可执行文件

    def _geoloc_hdf(
        self,
        subdataset_path: str,
        hdf_path: str,
        file_name: str,
        band_ids_one: list[int],
        work_folder: str,
    ) -> str | None:
        """单通道 geoloc → EPSG:4326。"""
        assert len(band_ids_one) == 1
        band_name = self._band_names[band_ids_one[0] - 1]
        os.makedirs(work_folder, exist_ok=True)

        cfg = self.config

        # 源 nodata（可选自动识别）
        if cfg.auto_detect_nodata:
            if subdataset_path == cfg.tb_sds_path:
                src_nodata = _get_src_nodata(
                    hdf_path,
                    cfg.tb_sds_path,
                    cfg.src_nodata,
                    f"{file_name} {band_name} TB",
                )
            elif subdataset_path == cfg.zen_sds_path:
                src_nodata = _get_src_nodata(
                    hdf_path,
                    cfg.zen_sds_path,
                    cfg.zen_nodata_fallback,
                    f"{file_name} Zenith",
                )
            else:
                src_nodata = cfg.src_nodata
            lat_nodata = _get_src_nodata(
                hdf_path, cfg.lat_sds_path, cfg.latlon_nodata, f"{file_name} Latitude"
            )
            lon_nodata = _get_src_nodata(
                hdf_path, cfg.lon_sds_path, cfg.latlon_nodata, f"{file_name} Longitude"
            )
        else:
            src_nodata = cfg.src_nodata
            lat_nodata = cfg.latlon_nodata
            lon_nodata = cfg.latlon_nodata

        # 1) 数据 VRT
        data_uri = _hdf_sds(hdf_path, subdataset_path)
        vrt_path = os.path.join(work_folder, f"temp_{file_name[:-4]}_{band_name}.vrt")
        cmd = [
            GDAL_TRANSLATE,
            "-of",
            "VRT",
            "-a_nodata",
            str(src_nodata),
            "-b",
            str(band_ids_one[0]),
            data_uri,
            vrt_path,
        ]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            logger.warning(
                "[SKIP] %s %s: gdal_translate 数据VRT 失败。错误：%s",
                file_name,
                band_name,
                e,
            )
            return None

        # 2) 纬度/经度 VRT
        vrtlat_path = os.path.join(work_folder, f"lat_{file_name[:-4]}_{band_name}.vrt")
        lat_uri = _hdf_sds(hdf_path, cfg.lat_sds_path)
        cmd = [
            GDAL_TRANSLATE,
            "-of",
            "VRT",
            "-a_nodata",
            str(lat_nodata),
            lat_uri,
            vrtlat_path,
        ]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            logger.warning(
                "[SKIP] %s %s: gdal_translate 纬度VRT 失败。错误：%s",
                file_name,
                band_name,
                e,
            )
            return None

        vrtlon_path = os.path.join(work_folder, f"lon_{file_name[:-4]}.vrt")
        lon_uri = _hdf_sds(hdf_path, cfg.lon_sds_path)
        cmd = [
            GDAL_TRANSLATE,
            "-of",
            "VRT",
            "-a_nodata",
            str(lon_nodata),
            lon_uri,
            vrtlon_path,
        ]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            logger.warning(
                "[SKIP] %s %s: gdal_translate 经度VRT 失败。错误：%s",
                file_name,
                band_name,
                e,
            )
            return None

        # 3) 注入 GEOLOCATION metadata
        metadata_content = f"""<Metadata domain="GEOLOCATION">
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
    """
        new_vrt_path = vrt_path.replace(".vrt", "new.vrt")
        inserted = False
        with (
            open(vrt_path, encoding="utf-8") as f,
            open(new_vrt_path, "w", encoding="utf-8") as g,
        ):
            for line in f:
                if not inserted and "<GCPList" in line:
                    g.write(metadata_content)
                    inserted = True
                g.write(line)

        vrt_path0 = os.path.join(
            work_folder, f"temp_{file_name[:-4]}_{band_name}new.vrt"
        )
        tif_path = os.path.join(work_folder, f"vrt_{file_name[:-4]}_{band_name}.tif")

        # 4) geoloc → 4326
        logger.info("开始地理查找表校正... (%s)", band_name)
        cmd = [
            GDAL_WARP,
            "-overwrite",
            "-geoloc",
            "-t_srs",
            "EPSG:4326",
            "-srcnodata",
            str(src_nodata),
            "-dstnodata",
            str(cfg.dst_nodata),
            "-of",
            "GTiff",
            "-ot",
            "Float32",
            "-r",
            "average",
            "-co",
            "COMPRESS=LZW",
            "-co",
            "PREDICTOR=3",
            "-co",
            "TILED=YES",
            vrt_path0,
            tif_path,
        ]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            logger.warning(
                "[SKIP] %s %s: gdalwarp -geoloc 失败。错误：%s", file_name, band_name, e
            )
            return None

        _check_nodata(
            vrt_path0, expected=src_nodata, label=f"VRT (geoloc src) {band_name}"
        )
        _check_nodata(
            tif_path, expected=cfg.dst_nodata, label=f"geoloc→4326 输出 {band_name}"
        )
        return band_name

    def _merge_allto_tif(
        self, work_folder: str, band_name: str, day: str, options: FyPreprocessOptions
    ) -> str | None:
        """日内拼接 + 重投影。"""
        os.makedirs(work_folder, exist_ok=True)
        cfg = self.config
        mosaic_vrt = os.path.join(work_folder, f"mosaic_{band_name}.vrt")

        src_list = sorted(glob.glob(os.path.join(work_folder, f"vrt*{band_name}.tif")))
        if not src_list:
            logger.warning("[SKIP] %s: 没有找到可拼接的 geoloc 结果。", band_name)
            return None

        cmd = [
            GDAL_BUILDVRT,
            "-srcnodata",
            str(cfg.dst_nodata),
            "-vrtnodata",
            str(cfg.dst_nodata),
            mosaic_vrt,
            *src_list,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            logger.warning(
                "[SKIP] %s: gdalbuildvrt 失败。错误：\n%s", band_name, proc.stderr
            )
            return None
        _check_nodata(
            mosaic_vrt, expected=cfg.dst_nodata, label=f"mosaic_{band_name}.vrt"
        )

        output_tif_path = os.path.join(
            work_folder,
            f"{cfg.output_prefix}_{band_name}_{day}_{options.orbit_mode}_0.tif",
        )
        output_tif_path0 = os.path.join(
            work_folder,
            f"{cfg.output_prefix}_{band_name}_{day}_{options.orbit_mode}_01.tif",
        )

        # 4326 融合
        cmd = [
            GDAL_WARP,
            "-of",
            "GTiff",
            "-ot",
            "Float32",
            "-r",
            options.overlap_option,
            "-srcnodata",
            str(cfg.dst_nodata),
            "-dstnodata",
            str(cfg.dst_nodata),
            "-co",
            "COMPRESS=LZW",
            "-co",
            "PREDICTOR=3",
            "-co",
            "TILED=YES",
            mosaic_vrt,
            output_tif_path0,
        ]
        subprocess.run(cmd, check=True)
        _check_nodata(
            output_tif_path0, expected=cfg.dst_nodata, label="mosaic→4326 输出"
        )

        # 空间范围裁剪 / 重投影
        if options.spatial_extent == 0:
            cmd = (
                f'"{GDAL_WARP}" -overwrite -t_srs EPSG:6933 '
                f"-te {_EASE2_GLOBAL_EXTENT[0]} {_EASE2_GLOBAL_EXTENT[1]} "
                f"{_EASE2_GLOBAL_EXTENT[2]} {_EASE2_GLOBAL_EXTENT[3]} "
                f"-ts {_EASE2_GLOBAL_SIZE[0]} {_EASE2_GLOBAL_SIZE[1]} -r average "
                f"-srcnodata {cfg.dst_nodata} -dstnodata {cfg.dst_nodata} "
                f"-of GTiff -ot Float32 "
                f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
                f'"{output_tif_path0}" "{output_tif_path}"'
            )
        elif options.spatial_extent == 1:
            min_x = options.point[0] - options.buffer_xy[0]
            max_x = options.point[0] + options.buffer_xy[0]
            min_y = options.point[1] - options.buffer_xy[1]
            max_y = options.point[1] + options.buffer_xy[1]
            cmd = (
                f'"{GDAL_WARP}" -of GTiff -ot Float32 -r {options.overlap_option} '
                f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
                f"-te {min_x} {min_y} {max_x} {max_y} "
                f'"{mosaic_vrt}" "{output_tif_path}"'
            )
        elif options.spatial_extent == 2:
            cmd = (
                f'"{GDAL_WARP}" -of GTiff -ot Float32 -r {options.overlap_option} '
                f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
                f"-te {options.lat_lon_bbox[0]} {options.lat_lon_bbox[1]} "
                f"{options.lat_lon_bbox[2]} {options.lat_lon_bbox[3]} "
                f'"{mosaic_vrt}" "{output_tif_path}"'
            )
        else:
            out0 = os.path.join(
                work_folder,
                f"{cfg.output_prefix}_{band_name}_{day}_{options.orbit_mode}_0.tif",
            )
            out1 = os.path.join(
                work_folder,
                f"{cfg.output_prefix}_{band_name}_{day}_{options.orbit_mode}.tif",
            )
            cmd = [
                GDAL_WARP,
                "-of",
                "GTiff",
                "-ot",
                "Float32",
                "-r",
                options.overlap_option,
                "-co",
                "COMPRESS=LZW",
                "-co",
                "PREDICTOR=3",
                "-co",
                "TILED=YES",
                mosaic_vrt,
                out0,
            ]
            subprocess.run(cmd, check=True)
            cmd = [
                GDAL_WARP,
                "-cutline",
                options.shapefile_path,
                "-crop_to_cutline",
                "-of",
                "GTiff",
                "-ot",
                "Float32",
                "-co",
                "COMPRESS=LZW",
                "-co",
                "PREDICTOR=3",
                "-co",
                "TILED=YES",
                out0,
                out1,
            ]
            output_tif_path = out1

        subprocess.run(cmd, check=True)

        if options.spatial_extent == 0:
            _check_nodata(
                output_tif_path,
                expected=cfg.dst_nodata,
                expected_epsg=6933,
                expected_size=_EASE2_GLOBAL_SIZE,
                label="4326→EASE2 输出",
            )
        else:
            _check_nodata(
                output_tif_path, expected=cfg.dst_nodata, label="4326/裁剪 输出"
            )

        # 清理临时文件
        for p in (output_tif_path0, mosaic_vrt):
            with contextlib.suppress(OSError):
                os.remove(p)

        return output_tif_path

    def _merge_day(
        self,
        files: list[str],
        input_dir: str,
        tb_name: str,
        work_folder: str,
        day: str,
        options: FyPreprocessOptions,
    ) -> int:
        """合并 TB 多通道 + SensorZenith，输出 GeoTIFF/HDF5/NetCDF。"""
        if not files:
            return 0

        cfg = self.config
        su_t = 0
        tb_band_names = (
            ["10V", "10H"]
            if options.band_ids == [1, 2]
            else [f for i, f in enumerate(self._band_names, 1) if i in options.band_ids]
        )

        # 获取 scale/offset（可选自动识别）
        first_hdf = os.path.join(input_dir, files[0])
        if cfg.auto_detect_scale:
            tb_slope, tb_intercept = _get_tb_scale_offset(first_hdf)
            zen_slope, zen_intercept = _get_zen_scale_offset(
                first_hdf, cfg.zen_sds_path
            )
        else:
            tb_slope, tb_intercept = cfg.tb_slope, cfg.tb_intercept
            zen_slope, zen_intercept = cfg.zen_slope, cfg.zen_intercept

        # 逐文件 geoloc
        for file_name in files:
            hdf_path = os.path.join(input_dir, file_name)
            for idx in options.band_ids:
                self._geoloc_hdf(
                    cfg.tb_sds_path, hdf_path, file_name, [idx], work_folder
                )
            self._geoloc_hdf(cfg.zen_sds_path, hdf_path, file_name, [1], work_folder)
            su_t += 1

        if su_t == 0:
            return 0

        # 日内拼接
        tb_tifs: list[str] = []
        for bname in tb_band_names:
            t = self._merge_allto_tif(work_folder, bname, day, options)
            if not t:
                return 0
            tb_tifs.append(t)
        ia_tif = self._merge_allto_tif(work_folder, cfg.zenith_name, day, options)
        if not ia_tif:
            return 0

        # 多波段合并
        band_tag = "".join(tb_band_names)
        tb_band_name = f"{tb_name}_{band_tag}"

        mergy_vrt0 = os.path.join(
            work_folder,
            f"{cfg.output_prefix}_{tb_band_name}_{day}_{options.orbit_mode}_1.vrt",
        )
        merge_inputs = tb_tifs + [ia_tif]
        cmd = [
            GDAL_BUILDVRT,
            "-separate",
            "-srcnodata",
            str(cfg.dst_nodata),
            "-vrtnodata",
            str(cfg.dst_nodata),
            mergy_vrt0,
            *merge_inputs,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.exists(mergy_vrt0):
            logger.error("gdalbuildvrt(separate) 失败：%s", proc.stderr)
            return 0

        selected = tb_band_names + [cfg.zenith_name]
        metadata_args: list[str] = []
        for i, name in enumerate(selected, start=1):
            metadata_args.extend(["-mo", f"Band_{i}={name}"])
        mergy_filetifname = os.path.join(
            work_folder,
            f"{cfg.output_prefix}_{tb_band_name}_{day}_{options.orbit_mode}.tif",
        )
        cmd = [
            GDAL_TRANSLATE,
            "-of",
            "GTiff",
            "-a_nodata",
            str(cfg.dst_nodata),
            "-ot",
            "Float32",
            "-co",
            "COMPRESS=LZW",
            "-co",
            "PREDICTOR=3",
            "-co",
            "TILED=YES",
            *metadata_args,
            mergy_vrt0,
            mergy_filetifname,
        ]
        subprocess.run(cmd, check=True)
        with contextlib.suppress(OSError):
            os.remove(mergy_vrt0)

        # 输出
        if options.outfile_type == 1:
            self._write_netcdf(
                mergy_filetifname,
                work_folder,
                tb_band_name,
                day,
                options,
                selected,
                tb_slope,
                tb_intercept,
                zen_slope,
                zen_intercept,
            )
        elif options.outfile_type == 2:
            self._write_hdf5(
                mergy_filetifname,
                work_folder,
                tb_band_name,
                day,
                options,
                selected,
                tb_slope,
                tb_intercept,
                zen_slope,
                zen_intercept,
            )

        # 清理
        for pattern in ["vrt*.tif", "*.vrt"]:
            for f in glob.glob(os.path.join(work_folder, pattern)):
                with contextlib.suppress(OSError):
                    os.remove(f)

        return 1

    def _write_netcdf(
        self,
        mergy_filetifname: str,
        work_folder: str,
        tb_band_name: str,
        day: str,
        options: FyPreprocessOptions,
        selected: list[str],
        tb_slope: float,
        tb_intercept: float,
        zen_slope: float,
        zen_intercept: float,
    ) -> None:
        cfg = self.config
        output_path = os.path.join(
            work_folder,
            f"{cfg.output_prefix}_{tb_band_name}_{day}_{options.orbit_mode}.nc",
        )
        with rasterio.open(mergy_filetifname) as src0:
            band0 = src0.read(1)
        ncfile = nc.Dataset(output_path, "w", format="NETCDF4")
        ncfile.createDimension("x", band0.shape[0])
        ncfile.createDimension("y", band0.shape[1])
        with rasterio.open(mergy_filetifname) as src:
            for idx, band_name in enumerate(selected, start=1):
                arr = src.read(idx, masked=True).astype(np.float32)
                band = np.ma.filled(arr, np.nan)
                if band_name == cfg.zenith_name:
                    # 数值专项 W5：数据体写 NaN，则 _FillValue 必须同为 NaN——
                    # 旧实现写后赋非标准属性 FillValue=-32767 与数据体不一致，
                    # 标准自动掩膜消费端掩不住。创建期 fill_value 设标准 _FillValue。
                    var = ncfile.createVariable(
                        band_name, np.float32, ("x", "y"), fill_value=np.nan
                    )
                    var[:, :] = band
                    var.units = "degree"
                    var.Valid_range = [0, 18000]
                    var.Intercept = zen_intercept
                    var.Slope = zen_slope
                    var.Long_name = cfg.zenith_name
                else:
                    number_part = "".join(filter(str.isdigit, band_name))
                    letter_part = "".join(filter(str.isalpha, band_name))
                    vari_name = f"EARTH OBSERVE BT {number_part}GHz {letter_part}"
                    var = ncfile.createVariable(
                        vari_name, np.float32, ("x", "y"), fill_value=np.nan
                    )
                    var[:, :] = band
                    var.units = "K"
                    var.Valid_range = [-32766, 10000]
                    var.Intercept = tb_intercept
                    var.Slope = tb_slope
                    var.Long_name = f"{number_part}GHZ {letter_part} Earth Observation Brightness Temperature"
        ncfile.close()
        logger.info("%s 融合成功", output_path)

    def _write_hdf5(
        self,
        mergy_filetifname: str,
        work_folder: str,
        tb_band_name: str,
        day: str,
        options: FyPreprocessOptions,
        selected: list[str],
        tb_slope: float,
        tb_intercept: float,
        zen_slope: float,
        zen_intercept: float,
    ) -> None:
        cfg = self.config
        output_path = os.path.join(
            work_folder,
            f"{cfg.output_prefix}_{tb_band_name}_{day}_{options.orbit_mode}.hdf",
        )
        tmp_hdf = output_path + ".tmp"
        try:
            with h5py.File(tmp_hdf, "w") as h5, rasterio.open(mergy_filetifname) as src:
                for idx, band_name in enumerate(selected, start=1):
                    arr = src.read(idx, masked=True).astype(np.float32)
                    band = np.ma.filled(arr, np.nan)
                    if band_name == cfg.zenith_name:
                        d = h5.create_dataset(band_name, data=band)
                        d.attrs.update(
                            {
                                "units": "degree",
                                "Valid range": "0 18000",
                                "FillValue": cfg.dst_nodata,
                                "Intercept": zen_intercept,
                                "Slope": zen_slope,
                                "Long_name": cfg.zenith_name,
                            }
                        )
                    else:
                        number_part = "".join(filter(str.isdigit, band_name))
                        letter_part = "".join(filter(str.isalpha, band_name))
                        vari_name = f"EARTH OBSERVE BT {number_part}GHz {letter_part}"
                        d = h5.create_dataset(vari_name, data=band)
                        d.attrs.update(
                            {
                                "units": "K",
                                "Valid range": "-32766 10000",
                                "FillValue": cfg.dst_nodata,
                                "Intercept": tb_intercept,
                                "Slope": tb_slope,
                                "Long_name": (
                                    f"{number_part}GHZ {letter_part} Earth Observation "
                                    f"Brightness Temperature"
                                ),
                            }
                        )
            os.replace(tmp_hdf, output_path)
            logger.info("%s 融合成功", output_path)
        except Exception:
            try:
                if os.path.exists(tmp_hdf):
                    os.remove(tmp_hdf)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def process_date_range(
        self,
        input_dir: str | Path,
        output_dir: str | Path,
        start_date: str,
        end_date: str,
        orbit_mode: str = "MWRID",
        band_ids: Sequence[int] | None = None,
        outfile_type: int = 2,
        spatial_extent: int = 0,
    ) -> list[str]:
        """处理指定日期范围内的所有 HDF 文件。

        Args:
            input_dir: HDF 输入目录
            output_dir: 输出根目录
            start_date: 起始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            orbit_mode: 轨道模式 ("MWRID" / "MWRIA" / "Both")
            band_ids: 波段 ID 列表 (1=10V, 2=10H, ...)
            outfile_type: 输出格式 (0:GTiff, 1:NetCDF, 2:HDF5)
            spatial_extent: 空间范围 (0:全球, 1:单点, 2:矩形, 3:Shapefile)

        Returns:
            已处理日期列表
        """
        input_dir = str(input_dir)
        output_dir = str(output_dir)
        options = FyPreprocessOptions(
            band_ids=list(band_ids) if band_ids else [1, 2],
            orbit_mode=orbit_mode,
            outfile_type=outfile_type,
            spatial_extent=spatial_extent,
        )

        # 构造日期列表
        start = parse_fy_date(start_date)
        end = parse_fy_date(end_date)
        date_keys = build_date_keys(start, end)
        if not date_keys:
            logger.warning("输入的时间范围无效")
            return []

        # 输出目录
        if orbit_mode == "Both":
            out_mwrid = os.path.join(output_dir, "MWRID")
            out_mwria = os.path.join(output_dir, "MWRIA")
            os.makedirs(out_mwrid, exist_ok=True)
            os.makedirs(out_mwria, exist_ok=True)
        else:
            os.makedirs(output_dir, exist_ok=True)

        # 扫描 HDF 文件并按日期+轨道分组
        logger.info("开始扫描 %s ...", input_dir)
        all_files = [f for f in os.listdir(input_dir) if f.endswith(".HDF")]
        logger.info("扫描完成，HDF 文件数: %d", len(all_files))

        files_by_day: dict[str, dict[str, list[str]]] = {}
        for file_name in all_files:
            m = re.search(r"(\d{8})", file_name)
            if not m:
                continue
            d = m.group(1)
            if d not in files_by_day:
                files_by_day[d] = {"A": [], "D": []}
            if "MWRID" in file_name:
                files_by_day[d]["D"].append(file_name)
            if "MWRIA" in file_name:
                files_by_day[d]["A"].append(file_name)

        processed_days: list[str] = []
        for i, day in enumerate(date_keys, 1):
            if i % 20 == 0:
                logger.info("进度: %d/%d，当前日期: %s", i, len(date_keys), day)

            rec = files_by_day.get(day, {"A": [], "D": []})
            a_files = rec["A"]
            d_files = rec["D"]
            if not (a_files or d_files):
                continue

            if orbit_mode == "MWRID" and d_files:
                logger.info("%s [MWRID] 文件数=%d", day, len(d_files))
                if self._merge_day(
                    d_files, input_dir, "MWRID", output_dir, day, options
                ):
                    processed_days.append(day)
                else:
                    logger.warning("%s [MWRID] 合并失败（无有效输出）", day)
            elif orbit_mode == "MWRIA" and a_files:
                logger.info("%s [MWRIA] 文件数=%d", day, len(a_files))
                if self._merge_day(
                    a_files, input_dir, "MWRIA", output_dir, day, options
                ):
                    processed_days.append(day)
                else:
                    logger.warning("%s [MWRIA] 合并失败（无有效输出）", day)
            elif orbit_mode == "Both":
                if d_files:
                    logger.info("%s [MWRID] 文件数=%d", day, len(d_files))
                    if self._merge_day(
                        d_files, input_dir, "MWRID", out_mwrid, day, options
                    ):
                        processed_days.append(day)
                    else:
                        logger.warning("%s [MWRID] 合并失败（无有效输出）", day)
                if a_files:
                    logger.info("%s [MWRIA] 文件数=%d", day, len(a_files))
                    if self._merge_day(
                        a_files, input_dir, "MWRIA", out_mwria, day, options
                    ):
                        if day not in processed_days:
                            processed_days.append(day)
                    else:
                        logger.warning("%s [MWRIA] 合并失败（无有效输出）", day)

        if not processed_days:
            logger.warning("输入的时间范围内无数据存在或全部预处理失败")
        return processed_days


def build_date_keys(start_time: datetime, end_time: datetime) -> list[str]:
    """构造日期键列表 (YYYYMMDD)。"""
    keys: list[str] = []
    current = start_time
    while current <= end_time:
        keys.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return keys


def parse_fy_date(value: str) -> datetime:
    """解析 ``YYYY-MM-DD`` / ``YYYY.MM.DD`` / ``YYYYMMDD`` 日期输入。

    种子 ``{YYYYMMDD}`` 占位符展开后为紧凑格式，与
    ``fy_download._iter_date_range`` 的宽容策略保持一致。
    """
    v = str(value).strip()
    if len(v) == 8 and v.isdigit():
        return datetime.strptime(v, "%Y%m%d")
    return datetime.strptime(v.replace(".", "-"), "%Y-%m-%d")
