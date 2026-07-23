"""数据预处理管道 — 多格式数据 (HDF5/NetCDF/GeoTIFF) 转换为反演算法所需的 .mat 格式。

依赖:
  - UniversalDataReader: 跨格式统一读取器 (同目录 universal_reader.py)
  - scipy.io.savemat: 保存 .mat (v5 格式，兼容旧版 MATLAB)
  - numpy: 数组操作

使用示例:
    from data_access.data_preprocessor import DataPreprocessor

    pre = DataPreprocessor("I:/Geograph_DataSet")
    pre.convert_smap_to_mat(
        smap_h5_path="I:/Geograph_DataSet/SMAP/SMAP_L3_SM_P_20230110_R18290_001.h5",
        output_dir="I:/Geograph_DataSet/SMAP/mat",
    )
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 支持独立运行: 将上级目录 (Python/) 加入 sys.path，使 data_access 包可被导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from scipy.io import savemat

from data_access.universal_reader import CHINA_BBOX, UniversalDataReader

# SMAP 变量名 → .mat 输出变量名映射
SMAP_VAR_MAP: dict[str, str] = {
    "soil_moisture": "SM",
    "surface_temperature": "Ts",
    "tb_h_corrected": "TBh",
    "tb_v_corrected": "TBv",
    "vegetation_water_content": "VWC",
    "clay_fraction": "CF",
}

# SMAP HDF5 AM 组前缀
_SMAP_AM_GROUP = "Soil_Moisture_Retrieval_Data_AM"


class DataPreprocessor:
    """数据预处理管道 — 多格式数据转 .mat。"""

    def __init__(self, data_root: str | Path = "I:/Geograph_DataSet"):
        self.data_root = Path(data_root)

    # ------------------------------------------------------------------
    # SMAP HDF5 → .mat
    # ------------------------------------------------------------------

    def convert_smap_to_mat(
        self,
        smap_h5_path: Path,
        output_dir: Path,
        bbox: tuple = CHINA_BBOX,
        variables: list[str] | None = None,
    ) -> Path:
        """将 SMAP HDF5 转换为 .mat 格式。

        - 读取 SMAP HDF5 中 AM 组变量 (soil_moisture, surface_temperature,
          tb_h_corrected, tb_v_corrected, vegetation_water_content, clay_fraction)
        - 裁剪到中国区域
        - 输出 .mat 文件包含: SM, Ts, TBh, TBv, VWC, CF, lat, lon
        - 变量名映射: soil_moisture→SM, surface_temperature→Ts,
          tb_h_corrected→TBh, tb_v_corrected→TBv,
          vegetation_water_content→VWC, clay_fraction→CF
        """
        smap_h5_path = Path(smap_h5_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 默认读取全部 AM 组变量
        var_list = list(SMAP_VAR_MAP.keys()) if variables is None else variables

        reader = UniversalDataReader(smap_h5_path)
        mat_dict: dict[str, np.ndarray] = {}
        lat_ref = None
        lon_ref = None

        for var in var_list:
            if var not in SMAP_VAR_MAP:
                # 未在映射表中的变量，直接用原名作为输出键
                out_key = var
            else:
                out_key = SMAP_VAR_MAP[var]
            # SMAP HDF5 变量路径: Soil_Moisture_Retrieval_Data_AM/<var>
            var_path = f"{_SMAP_AM_GROUP}/{var}"
            data = reader.read_variable(var_path, bbox=bbox)
            mat_dict[out_key] = np.asarray(data.values, dtype=np.float64)
            # 所有变量共享同一坐标网格，取首个有效坐标
            if lat_ref is None and data.lat is not None:
                lat_ref = np.asarray(data.lat)
            if lon_ref is None and data.lon is not None:
                lon_ref = np.asarray(data.lon)

        # 写入坐标变量
        if lat_ref is not None:
            mat_dict["lat"] = lat_ref
        if lon_ref is not None:
            mat_dict["lon"] = lon_ref

        # 输出文件名: <源文件名>.mat
        out_path = output_dir / f"{smap_h5_path.stem}.mat"
        # v5 格式，兼容旧版 MATLAB; 保留 NaN 不替换为 -9999
        savemat(str(out_path), mat_dict, format="5", do_compression=True)
        return out_path

    # ------------------------------------------------------------------
    # ERA5 NetCDF → 每日 .mat
    # ------------------------------------------------------------------

    def convert_era5_to_daily_mat(
        self,
        era5_nc_path: Path,
        output_dir: Path,
        bbox: tuple = CHINA_BBOX,
        day_indices: list[int] | None = None,
    ) -> list[Path]:
        """将 ERA5 SMCI NetCDF 转换为每日 .mat 文件。

        - 读取 ERA5 NetCDF 的 SMCI 变量
        - 按 day_indices 提取指定天 (默认全部天)
        - 每天输出一个 .mat 文件: ERA5_SMCI_YYYYMMDD.mat
        - 包含: SMCI, lat, lon, time
        """
        era5_nc_path = Path(era5_nc_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 一次性读取全部时间层 (time_index=None)
        reader = UniversalDataReader(era5_nc_path)
        data = reader.read_variable("SMCI", bbox=bbox, time_index=None)

        values = np.asarray(data.values, dtype=np.float64)
        lat = np.asarray(data.lat) if data.lat is not None else None
        lon = np.asarray(data.lon) if data.lon is not None else None
        time_vals = np.asarray(data.time) if data.time is not None else None

        # 确定时间维度位置
        # UniversalDataReader 对 NetCDF 3D 数据返回 (time, lat, lon)
        if values.ndim == 3:
            n_times = values.shape[0]
        elif values.ndim == 2:
            # 仅一天或单层
            n_times = 1
            values = values[np.newaxis, ...]
        else:
            n_times = 0

        # 解析时间字符串 → 日期 (ERA5 时间变量为 "YYYYMMDD" 字符串)
        date_strings = self._parse_era5_dates(time_vals, n_times)

        # 选择要处理的天索引
        if day_indices is None:
            indices = list(range(n_times))
        else:
            indices = [i for i in day_indices if 0 <= i < n_times]

        out_paths: list[Path] = []
        for idx in indices:
            day_data = values[idx]
            # 时间标签 (优先日期字符串，否则用索引)
            date_label = (
                date_strings[idx] if idx < len(date_strings) else f"day{idx:04d}"
            )

            mat_dict: dict[str, np.ndarray] = {
                "SMCI": day_data,
                "time": np.array([date_label]),
            }
            if lat is not None:
                mat_dict["lat"] = lat
            if lon is not None:
                mat_dict["lon"] = lon

            out_path = output_dir / f"ERA5_SMCI_{date_label}.mat"
            savemat(str(out_path), mat_dict, format="5", do_compression=True)
            out_paths.append(out_path)

        return out_paths

    # ------------------------------------------------------------------
    # GeoTIFF → .mat
    # ------------------------------------------------------------------

    def convert_geotiff_to_mat(
        self,
        tif_path: Path,
        output_path: Path,
        bbox: tuple = CHINA_BBOX,
        variable_name: str = "data",
    ) -> Path:
        """将 GeoTIFF 转换为 .mat 格式。

        - 读取 GeoTIFF 数据
        - 裁剪到指定区域
        - 输出 .mat 文件包含: <variable_name>, lat, lon
        """
        tif_path = Path(tif_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        reader = UniversalDataReader(tif_path)
        data = reader.read_variable(bbox=bbox, band=1)

        mat_dict: dict[str, np.ndarray] = {
            variable_name: np.asarray(data.values, dtype=np.float64),
        }
        if data.lat is not None:
            mat_dict["lat"] = np.asarray(data.lat)
        if data.lon is not None:
            mat_dict["lon"] = np.asarray(data.lon)

        savemat(str(output_path), mat_dict, format="5", do_compression=True)
        return output_path

    # ------------------------------------------------------------------
    # 构建反演算法完整输入数据集
    # ------------------------------------------------------------------

    def build_retrieval_inputs(
        self,
        smap_dir: Path,
        era5_path: Path,
        output_dir: Path,
        bbox: tuple = CHINA_BBOX,
        date_range: tuple[str, str] | None = None,
    ) -> dict[str, list[Path]]:
        """构建反演算法所需的完整输入数据集。

        - 转换 SMAP 日数据为 .mat (遍历 smap_dir 下所有 .h5 文件)
        - 转换 ERA5 为每日 .mat
        - 转换静态数据 (clay_fraction 来自 SMAP, landcover 为 GeoTIFF) 为 .mat
        - 返回 {smap_daily: [...], era5_daily: [...], static: [...]}

        Args:
            date_range: 可选 (start, end)，"YYYYMMDD" 格式，用于筛选日期范围。
        """
        smap_dir = Path(smap_dir)
        era5_path = Path(era5_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 解析日期范围
        date_start, date_end = None, None
        if date_range is not None:
            date_start, date_end = date_range

        result: dict[str, list[Path]] = {
            "smap_daily": [],
            "era5_daily": [],
            "static": [],
        }

        # 1) SMAP 日数据 → .mat
        smap_out = output_dir / "smap"
        smap_files = sorted(smap_dir.glob("*.h5"))
        for h5_file in smap_files:
            # 按文件名中的日期筛选
            smap_date = self._extract_date_from_filename(h5_file.name)
            if (
                smap_date is not None
                and date_start is not None
                and date_end is not None
            ):
                if not (date_start <= smap_date <= date_end):
                    continue
            try:
                out = self.convert_smap_to_mat(h5_file, smap_out, bbox=bbox)
                result["smap_daily"].append(out)
            except Exception as exc:  # noqa: BLE001
                print(f"[SMAP] 跳过 {h5_file.name}: {exc}")

        # 2) ERA5 → 每日 .mat
        era5_out = output_dir / "era5"
        day_indices = None
        if date_start is not None and date_end is not None:
            # 读取时间坐标以计算 day_indices
            day_indices = self._compute_day_indices(era5_path, date_start, date_end)
        try:
            era5_paths = self.convert_era5_to_daily_mat(
                era5_path, era5_out, bbox=bbox, day_indices=day_indices
            )
            result["era5_daily"].extend(era5_paths)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERA5] 转换失败: {exc}")

        # 3) 静态数据 → .mat
        static_out = output_dir / "static"
        # clay_fraction: 从首个 SMAP 文件提取
        if smap_files:
            try:
                self._export_static_clay_fraction(smap_files[0], static_out, bbox)
                result["static"].append(static_out / "clay_fraction.mat")
            except Exception as exc:  # noqa: BLE001
                print(f"[static] clay_fraction 提取失败: {exc}")
        # landcover: 在 data_root 下查找 GeoTIFF (MCD12Q1 等)
        lc_path = self._find_landcover_tif()
        if lc_path is not None:
            try:
                self.convert_geotiff_to_mat(
                    lc_path,
                    static_out / "landcover.mat",
                    bbox=bbox,
                    variable_name="landcover",
                )
                result["static"].append(static_out / "landcover.mat")
            except Exception as exc:  # noqa: BLE001
                print(f"[static] landcover 转换失败: {exc}")

        return result

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_era5_dates(time_vals: np.ndarray | None, n_times: int) -> list[str]:
        """将 ERA5 时间坐标解析为 'YYYYMMDD' 字符串列表。"""
        if time_vals is None:
            return [f"day{i:04d}" for i in range(n_times)]
        dates: list[str] = []
        for t in time_vals:
            s = str(t)
            # 尝试从字符串中提取 8 位日期 (YYYYMMDD)
            m = re.search(r"(\d{8})", s)
            if m:
                dates.append(m.group(1))
            else:
                # 尝试解析 ISO 日期 (YYYY-MM-DD) → YYYYMMDD
                m_iso = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
                if m_iso:
                    y, mo, d = m_iso.groups()
                    dates.append(f"{y}{int(mo):02d}{int(d):02d}")
                else:
                    dates.append(s)
        return dates

    @staticmethod
    def _extract_date_from_filename(name: str) -> str | None:
        """从文件名中提取 8 位日期 (YYYYMMDD)。"""
        m = re.search(r"(\d{8})", name)
        return m.group(1) if m else None

    def _compute_day_indices(
        self, nc_path: Path, date_start: str, date_end: str
    ) -> list[int]:
        """根据日期范围计算 ERA5 NetCDF 的时间索引列表。

        仅读取时间坐标变量 (不读取数据)，效率较高。
        """
        from netCDF4 import Dataset, num2date

        indices: list[int] = []
        with Dataset(nc_path) as ds:
            time_var = None
            for name in ("time",):
                if name in ds.variables:
                    time_var = ds.variables[name]
                    break
            if time_var is None:
                return indices
            try:
                times = num2date(
                    time_var[:],
                    time_var.units,
                    getattr(time_var, "calendar", "standard"),
                )
                time_strings = [str(t) for t in times]
            except (AttributeError, ValueError):
                time_strings = [str(t) for t in time_var[:]]

            for i, s in enumerate(time_strings):
                m = re.search(r"(\d{8})", s)
                if not m:
                    continue
                d = m.group(1)
                if date_start <= d <= date_end:
                    indices.append(i)
        return indices

    def _export_static_clay_fraction(
        self, smap_h5_path: Path, output_dir: Path, bbox: tuple
    ) -> Path:
        """从 SMAP HDF5 中提取静态变量 clay_fraction 并保存为 .mat。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        reader = UniversalDataReader(smap_h5_path)
        data = reader.read_variable(f"{_SMAP_AM_GROUP}/clay_fraction", bbox=bbox)
        mat_dict: dict[str, np.ndarray] = {
            "CF": np.asarray(data.values, dtype=np.float64),
        }
        if data.lat is not None:
            mat_dict["lat"] = np.asarray(data.lat)
        if data.lon is not None:
            mat_dict["lon"] = np.asarray(data.lon)

        out_path = output_dir / "clay_fraction.mat"
        savemat(str(out_path), mat_dict, format="5", do_compression=True)
        return out_path

    def _find_landcover_tif(self) -> Path | None:
        """在 data_root 下查找土地覆盖 GeoTIFF (MCD12Q1 等)。"""
        if not self.data_root.exists():
            return None
        # 常见土地覆盖数据文件名关键词
        patterns = ["*MCD12Q1*", "*landcover*", "*land_cover*", "*LC*", "*IGBP*"]
        for pattern in patterns:
            for tif in self.data_root.rglob(f"{pattern}.tif"):
                return tif
            for tif in self.data_root.rglob(f"{pattern}.tiff"):
                return tif
        return None


if __name__ == "__main__":
    # 独立运行: 打印基本信息与可用方法
    pre = DataPreprocessor()
    print("DataPreprocessor 已就绪, data_root =", pre.data_root)
    print(
        "可用方法: convert_smap_to_mat, convert_era5_to_daily_mat, "
        "convert_geotiff_to_mat, build_retrieval_inputs"
    )
