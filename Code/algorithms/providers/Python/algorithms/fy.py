from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ingest.fy import FyDailyJobPlan

# ─── GDAL 地理坐标系常量 ─────────────────────────────────────────────────────
_GDAL_SRS_EPSG4326 = "EPSG:4326"

# ─── FY 数据默认 nodata 值 ───────────────────────────────────────────────────
_FY_DEFAULT_SRC_NODATA = -32767.0
_FY_LATLON_SRC_NODATA = 65535.0

# ─── 默认重叠处理方式 ───────────────────────────────────────────────────────
_FY_DEFAULT_OVERLAP = "average"


@dataclass(frozen=True, slots=True)
class FyDatasetProfile:
    """风云卫星数据集配置档案。

    各字段说明: satellite 卫星标识，tb_sds_path/lat_sds_path/lon_sds_path/zen_sds_path
    为 HDF5 SDS 路径，tb_band_names 为亮温波段名元组，*_src_nodata 为源数据 nodata 值，
    tb_scale/tb_offset 为亮温缩放/偏移，zen_scale/zen_offset 为天顶角缩放/偏移。
    量纲: tb 亮温单位 K（经 scale/offset 转换后），lat/lon 单位度，zen 天顶角单位度。
    """

    satellite: str
    tb_sds_path: str
    lat_sds_path: str
    lon_sds_path: str
    zen_sds_path: str
    tb_band_names: tuple[str, ...]
    zenith_name: str
    tb_src_nodata: float
    lat_lon_src_nodata: float
    zen_src_nodata: float
    dst_nodata: float
    output_prefix: str
    tb_scale: float
    tb_offset: float
    zen_scale: float
    zen_offset: float


@dataclass(frozen=True, slots=True)
class FyCommandStep:
    """GDAL 命令步骤描述。name 步骤名，command 命令字符串，outputs 输出文件路径元组。"""

    name: str
    command: str
    outputs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


FY3D_PROFILE = FyDatasetProfile(
    satellite="FY3D",
    tb_sds_path="//Calibration/EARTH_OBSERVE_BT_10_to_89GHz",
    lat_sds_path="//Geolocation/Latitude",
    lon_sds_path="//Geolocation/Longitude",
    zen_sds_path="//Geolocation/Sensor_Zenith",
    tb_band_names=(
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
    ),
    zenith_name="Sensor_Zenith",
    tb_src_nodata=-32767.0,
    lat_lon_src_nodata=65535.0,
    zen_src_nodata=-32767.0,
    dst_nodata=-32767.0,
    output_prefix="FY3D_GBAL_L1",
    tb_scale=0.01,
    tb_offset=327.68,
    zen_scale=0.01,
    zen_offset=0.0,
)


FY3B_PROFILE = FyDatasetProfile(
    satellite="FY3B",
    tb_sds_path="//EARTH_OBSERVE_BT_10_to_89GHz",
    lat_sds_path="//Latitude",
    lon_sds_path="//Longitude",
    zen_sds_path="//SensorZenith",
    tb_band_names=(
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
    ),
    zenith_name="SensorZenith",
    tb_src_nodata=-999.0,
    lat_lon_src_nodata=999.9,
    zen_src_nodata=32767.0,
    dst_nodata=-999.0,
    output_prefix="FY3B_GBAL_L1",
    tb_scale=0.01,
    tb_offset=327.68,
    zen_scale=0.01,
    zen_offset=0.0,
)


def get_fy_profile(satellite: str) -> FyDatasetProfile:
    satellite = satellite.upper()
    if satellite == "FY3B":
        return FY3B_PROFILE
    if satellite == "FY3D":
        return FY3D_PROFILE
    return FY3D_PROFILE


def resolve_gdal_bins(force_bin: str | None = None) -> dict[str, str]:
    """查找 GDAL 可执行文件路径。优先 force_bin 指定目录，其次 PATH 环境变量。返回含 gdal_translate/gdalbuildvrt/gdalwarp/gdalinfo 的字典。"""
    import shutil

    candidates: list[Path] = []
    if force_bin:
        candidates.append(Path(force_bin))

    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        candidates.append(Path(conda_prefix) / "Library" / "bin")

    for candidate in candidates:
        translate = candidate / "gdal_translate.exe"
        buildvrt = candidate / "gdalbuildvrt.exe"
        warp = candidate / "gdalwarp.exe"
        info = candidate / "gdalinfo.exe"
        if all(path.exists() for path in (translate, buildvrt, warp, info)):
            return {
                "gdal_translate": str(translate),
                "gdalbuildvrt": str(buildvrt),
                "gdalwarp": str(warp),
                "gdalinfo": str(info),
            }

    translate = shutil.which("gdal_translate") or shutil.which("gdal_translate.exe")
    buildvrt = shutil.which("gdalbuildvrt") or shutil.which("gdalbuildvrt.exe")
    warp = shutil.which("gdalwarp") or shutil.which("gdalwarp.exe")
    info = shutil.which("gdalinfo") or shutil.which("gdalinfo.exe")
    return {
        "gdal_translate": translate or "gdal_translate",
        "gdalbuildvrt": buildvrt or "gdalbuildvrt",
        "gdalwarp": warp or "gdalwarp",
        "gdalinfo": info or "gdalinfo",
    }


def hdf_sds_uri(hdf_path: str, sds_path: str) -> str:
    """构造 HDF5 SDS 的 GDAL URI（HDF5:"path":sds_path 格式），路径中的双引号被 URL 编码。"""
    escaped = hdf_path.replace('"', "%22")
    return f'HDF5:"{escaped}":{sds_path}'


def build_geoloc_metadata_block(lon_vrt_path: str, lat_vrt_path: str) -> str:
    """构建 GDAL GEOLOCATION 元数据块（XML 字符串）。

    使用 _GDAL_SRS_EPSG4326 坐标系，将经纬度 VRT 文件绑定为地理定位元数据。
    """
    return (
        '<Metadata domain="GEOLOCATION">\n'
        '    <MDI key="LINE_OFFSET">0</MDI>\n'
        '    <MDI key="LINE_STEP">1</MDI>\n'
        '    <MDI key="PIXEL_OFFSET">0</MDI>\n'
        '    <MDI key="PIXEL_STEP">1</MDI>\n'
        f'    <MDI key="SRS">{_GDAL_SRS_EPSG4326}</MDI>\n'
        '    <MDI key="X_BAND">1</MDI>\n'
        f'    <MDI key="X_DATASET">{lon_vrt_path}</MDI>\n'
        '    <MDI key="Y_BAND">1</MDI>\n'
        f'    <MDI key="Y_DATASET">{lat_vrt_path}</MDI>\n'
        "</Metadata>\n"
    )


def build_fy_daily_command_steps(
    plan: FyDailyJobPlan,
    band_ids: tuple[int, ...] = (1, 2),
    overlap_option: str = _FY_DEFAULT_OVERLAP,
    spatial_mode: str = "global",
    gdal_bin: str | None = None,
) -> list[FyCommandStep]:
    """构建风云卫星日处理 GDAL 命令步骤列表。

    流程: HDF5 SDS 提取 → 地理定位 VRT → 重投影（gdalwarp）→ 拼接（gdalbuildvrt + gdal_translate）。
    band_ids 指定处理的波段编号（1-based），overlap_option 控制重叠区处理方式，spatial_mode 控制空间范围。
    """
    profile = get_fy_profile(plan.satellite)
    gdal_bins = resolve_gdal_bins(force_bin=gdal_bin)
    work_dir = Path(plan.work_dir)
    steps: list[FyCommandStep] = []

    selected_tb_band_names = tuple(
        profile.tb_band_names[index - 1] for index in band_ids
    )
    all_output_tifs: list[str] = []

    for input_file in plan.input_files:
        file_name = Path(input_file).stem

        for band_id in band_ids:
            band_name = profile.tb_band_names[band_id - 1]
            data_vrt = work_dir / f"temp_{file_name}_{band_name}.vrt"
            lat_vrt = work_dir / f"lat_{file_name}_{band_name}.vrt"
            lon_vrt = work_dir / f"lon_{file_name}.vrt"
            geoloc_vrt = work_dir / f"temp_{file_name}_{band_name}new.vrt"
            geoloc_tif = work_dir / f"vrt_{file_name}_{band_name}.tif"

            steps.append(
                FyCommandStep(
                    name=f"translate_tb_vrt_{band_name}",
                    command=(
                        f'"{gdal_bins["gdal_translate"]}" -of VRT '
                        f'-a_nodata {profile.tb_src_nodata} -b {band_id} '
                        f'{hdf_sds_uri(input_file, profile.tb_sds_path)} "{data_vrt}"'
                    ),
                    outputs=(str(data_vrt),),
                )
            )
            steps.append(
                FyCommandStep(
                    name=f"translate_lat_vrt_{band_name}",
                    command=(
                        f'"{gdal_bins["gdal_translate"]}" -of VRT '
                        f'-a_nodata {profile.lat_lon_src_nodata} '
                        f'{hdf_sds_uri(input_file, profile.lat_sds_path)} "{lat_vrt}"'
                    ),
                    outputs=(str(lat_vrt),),
                )
            )
            steps.append(
                FyCommandStep(
                    name=f"translate_lon_vrt_{band_name}",
                    command=(
                        f'"{gdal_bins["gdal_translate"]}" -of VRT '
                        f'-a_nodata {profile.lat_lon_src_nodata} '
                        f'{hdf_sds_uri(input_file, profile.lon_sds_path)} "{lon_vrt}"'
                    ),
                    outputs=(str(lon_vrt),),
                )
            )
            steps.append(
                FyCommandStep(
                    name=f"inject_geoloc_metadata_{band_name}",
                    command=f"WRITE_GEOLOC_METADATA {data_vrt} -> {geoloc_vrt}",
                    outputs=(str(geoloc_vrt),),
                    metadata={
                        "source_vrt": str(data_vrt),
                        "target_vrt": str(geoloc_vrt),
                        "geoloc_metadata": build_geoloc_metadata_block(
                            str(lon_vrt), str(lat_vrt)
                        ),
                    },
                )
            )
            steps.append(
                FyCommandStep(
                    name=f"warp_geoloc_4326_{band_name}",
                    command=(
                        f'"{gdal_bins["gdalwarp"]}" -overwrite -geoloc -t_srs EPSG:4326 '
                        f'-srcnodata {profile.tb_src_nodata} -dstnodata {profile.dst_nodata} '
                        f'-of GTiff -ot Float32 -r {overlap_option} '
                        f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
                        f'"{geoloc_vrt}" "{geoloc_tif}"'
                    ),
                    outputs=(str(geoloc_tif),),
                )
            )
            all_output_tifs.append(str(geoloc_tif))

        zen_name = profile.zenith_name
        zen_vrt = work_dir / f"temp_{file_name}_{zen_name}.vrt"
        lat_vrt = work_dir / f"lat_{file_name}_{zen_name}.vrt"
        lon_vrt = work_dir / f"lon_{file_name}.vrt"
        zen_geoloc_vrt = work_dir / f"temp_{file_name}_{zen_name}new.vrt"
        zen_geoloc_tif = work_dir / f"vrt_{file_name}_{zen_name}.tif"
        steps.append(
            FyCommandStep(
                name="translate_zenith_vrt",
                command=(
                    f'"{gdal_bins["gdal_translate"]}" -of VRT '
                    f'-a_nodata {profile.zen_src_nodata} -b 1 '
                    f'{hdf_sds_uri(input_file, profile.zen_sds_path)} "{zen_vrt}"'
                ),
                outputs=(str(zen_vrt),),
            )
        )
        steps.append(
            FyCommandStep(
                name="translate_zenith_lat_vrt",
                command=(
                    f'"{gdal_bins["gdal_translate"]}" -of VRT '
                    f'-a_nodata {profile.lat_lon_src_nodata} '
                    f'{hdf_sds_uri(input_file, profile.lat_sds_path)} "{lat_vrt}"'
                ),
                outputs=(str(lat_vrt),),
            )
        )
        steps.append(
            FyCommandStep(
                name="translate_zenith_lon_vrt",
                command=(
                    f'"{gdal_bins["gdal_translate"]}" -of VRT '
                    f'-a_nodata {profile.lat_lon_src_nodata} '
                    f'{hdf_sds_uri(input_file, profile.lon_sds_path)} "{lon_vrt}"'
                ),
                outputs=(str(lon_vrt),),
            )
        )
        steps.append(
            FyCommandStep(
                name="inject_geoloc_metadata_zenith",
                command=f"WRITE_GEOLOC_METADATA {zen_vrt} -> {zen_geoloc_vrt}",
                outputs=(str(zen_geoloc_vrt),),
                metadata={
                    "source_vrt": str(zen_vrt),
                    "target_vrt": str(zen_geoloc_vrt),
                    "geoloc_metadata": build_geoloc_metadata_block(
                        str(lon_vrt), str(lat_vrt)
                    ),
                },
            )
        )
        steps.append(
            FyCommandStep(
                name="warp_geoloc_4326_zenith",
                command=(
                    f'"{gdal_bins["gdalwarp"]}" -overwrite -geoloc -t_srs EPSG:4326 '
                    f'-srcnodata {profile.zen_src_nodata} -dstnodata {profile.dst_nodata} '
                    f'-of GTiff -ot Float32 -r {overlap_option} '
                    f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
                    f'"{zen_geoloc_vrt}" "{zen_geoloc_tif}"'
                ),
                outputs=(str(zen_geoloc_tif),),
            )
        )
        all_output_tifs.append(str(zen_geoloc_tif))

    merged_outputs: list[str] = []
    for band_name in (*selected_tb_band_names, profile.zenith_name):
        band_geoloc_tifs = [
            path for path in all_output_tifs if path.endswith(f"_{band_name}.tif")
        ]
        mosaic_vrt = work_dir / f"mosaic_{band_name}.vrt"
        mosaic_4326 = (
            work_dir
            / f"{profile.output_prefix}_{band_name}_{plan.date_key}_{plan.orbit_type}_01.tif"
        )
        final_tif = (
            work_dir
            / f"{profile.output_prefix}_{band_name}_{plan.date_key}_{plan.orbit_type}.tif"
        )
        input_arg = " ".join(f'"{path}"' for path in band_geoloc_tifs)
        steps.append(
            FyCommandStep(
                name=f"buildvrt_daily_{band_name}",
                command=(
                    f'"{gdal_bins["gdalbuildvrt"]}" '
                    f'-srcnodata {profile.dst_nodata} -vrtnodata {profile.dst_nodata} '
                    f'"{mosaic_vrt}" {input_arg}'
                ),
                outputs=(str(mosaic_vrt),),
            )
        )
        steps.append(
            FyCommandStep(
                name=f"warp_daily_4326_{band_name}",
                command=(
                    f'"{gdal_bins["gdalwarp"]}" -of GTiff -ot Float32 -r {overlap_option} '
                    f'-srcnodata {profile.dst_nodata} -dstnodata {profile.dst_nodata} '
                    f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
                    f'"{mosaic_vrt}" "{mosaic_4326}"'
                ),
                outputs=(str(mosaic_4326),),
            )
        )
        if spatial_mode == "global":
            command = (
                f'"{gdal_bins["gdalwarp"]}" -overwrite -t_srs EPSG:6933 '
                f'-te -17367530.45 -7314540.83 17367530.45 7314540.83 '
                f'-ts 3856 1624 -r average '
                f'-srcnodata {profile.dst_nodata} -dstnodata {profile.dst_nodata} '
                f'-of GTiff -ot Float32 '
                f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
                f'"{mosaic_4326}" "{final_tif}"'
            )
        else:
            command = (
                f'"{gdal_bins["gdalwarp"]}" -of GTiff -ot Float32 -r {overlap_option} '
                f'-srcnodata {profile.dst_nodata} -dstnodata {profile.dst_nodata} '
                f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
                f'"{mosaic_vrt}" "{final_tif}"'
            )
        steps.append(
            FyCommandStep(
                name=f"warp_daily_final_{band_name}",
                command=command,
                outputs=(str(final_tif),),
            )
        )
        merged_outputs.append(str(final_tif))

    merged_vrt = (
        work_dir
        / f"{profile.output_prefix}_{plan.orbit_type}_10V10H_{plan.date_key}_1.vrt"
    )
    merged_tif = (
        Path(plan.output_dir)
        / f"{profile.output_prefix}_{plan.orbit_type}_10V10H_{plan.date_key}.tif"
    )
    multi_input_arg = " ".join(f'"{path}"' for path in merged_outputs)
    band_names = (*selected_tb_band_names, profile.zenith_name)
    metadata_args = " ".join(
        f"-mo Band_{idx}={name}" for idx, name in enumerate(band_names, start=1)
    )
    steps.append(
        FyCommandStep(
            name="buildvrt_multiband",
            command=(
                f'"{gdal_bins["gdalbuildvrt"]}" -separate '
                f'-srcnodata {profile.dst_nodata} -vrtnodata {profile.dst_nodata} '
                f'"{merged_vrt}" {multi_input_arg}'
            ),
            outputs=(str(merged_vrt),),
        )
    )
    steps.append(
        FyCommandStep(
            name="translate_multiband_tif",
            command=(
                f'"{gdal_bins["gdal_translate"]}" -of GTiff -a_nodata {profile.dst_nodata} -ot Float32 '
                f'-co "COMPRESS=LZW" -co "PREDICTOR=3" -co "TILED=YES" '
                f'{metadata_args} "{merged_vrt}" "{merged_tif}"'
            ),
            outputs=(str(merged_tif),),
        )
    )
    return steps


def get_fy_daily_multiband_output_path(plan: FyDailyJobPlan) -> Path:
    profile = get_fy_profile(plan.satellite)
    return (
        Path(plan.output_dir)
        / f"{profile.output_prefix}_{plan.orbit_type}_10V10H_{plan.date_key}.tif"
    )


def write_fy_command_plan_json(
    steps: list[FyCommandStep], output_path: str | Path
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(step) for step in steps]
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output_path
