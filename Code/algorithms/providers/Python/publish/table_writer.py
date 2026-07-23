"""table_writer.py - Parquet 表格写出。

提供 TableWriter 类和 write_timeseries 辅助函数，
用于将 pandas DataFrame 写出为 Parquet 格式。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

if TYPE_CHECKING:
    import pandas as pd


# ---------------------------------------------------------------------------
# 内部延迟导入（用于运行时检查）
# ---------------------------------------------------------------------------


def _check_dependencies() -> tuple[Any, Any, Any]:
    """检查并导入 pandas / pyarrow 依赖，失败时给出友好提示。"""
    try:
        import pandas as pd
    except ImportError as e:
        raise ImportError(
            "pandas 未安装，无法使用 TableWriter。" " 请运行: pip install pandas"
        ) from e

    try:
        import pyarrow as pa
    except ImportError as e:
        raise ImportError(
            "pyarrow 未安装，无法使用 TableWriter。" " 请运行: pip install pyarrow"
        ) from e

    try:
        import pyarrow.parquet as pq
    except ImportError as e:
        raise ImportError(
            "pyarrow.parquet 未安装，无法使用 TableWriter。"
            " 请运行: pip install pyarrow"
        ) from e

    return pd, pa, pq


# ---------------------------------------------------------------------------
# TableWriter
# ---------------------------------------------------------------------------


class TableWriter:
    """表格数据写出器，支持 Parquet 格式。

    将 pandas DataFrame 写出为 Apache Parquet 格式，
    支持 snappy 压缩和自定义元数据。
    """

    def __init__(self, output_dir: Path | str, overwrite: bool = False):
        """初始化表格写出器。

        参数：
            output_dir: 输出目录
            overwrite: 是否覆盖已存在的文件
        """
        self.output_dir = Path(output_dir)
        self.overwrite = overwrite

    def write(
        self,
        df: "pd.DataFrame",
        output_name: str,
        *,
        index: bool = False,
        compression: str = "snappy",
        metadata: Optional[dict] = None,
    ) -> dict:
        """将 pandas DataFrame 写出为 Parquet 格式。

        参数：
            df: 要写出的 DataFrame
            output_name: 输出文件名（不含扩展名）
            index: 是否写入索引列
            compression: 压缩算法，默认 "snappy"（可选 "gzip", "brotli", None）
            metadata: 自定义元数据字典，会写入 Parquet 文件元数据

        返回：
            dict: {
                "path": str,
                "uri": str,
                "rows": int,
                "columns": list[str],
                "size_bytes": int,
            }
        """
        pd, pa, pq = _check_dependencies()

        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)

        output_file = self.output_dir / f"{output_name}.parquet"
        if output_file.exists() and not self.overwrite:
            raise FileExistsError(f"文件已存在（overwrite=False）: {output_file}")

        # 准备 Parquet 元数据
        parquet_metadata: dict[str, Any] = {}
        if metadata:
            parquet_metadata.update(metadata)

        # 添加写入时间
        parquet_metadata["write_time"] = datetime.utcnow().isoformat()

        # 添加行数和列信息
        parquet_metadata["rows"] = len(df)
        parquet_metadata["columns"] = list(df.columns)

        # 写出 DataFrame
        table = pa.Table.from_pandas(df, preserve_index=index)

        # 写入元数据到 schema
        if parquet_metadata:
            new_schema = table.schema.with_metadata(parquet_metadata)
            table = table.cast(new_schema)

        pq.write_table(
            table,
            output_file,
            compression=compression,
        )

        # 验证文件
        if not output_file.exists():
            raise IOError(f"写出失败，文件不存在: {output_file}")
        file_size = output_file.stat().st_size
        if file_size == 0:
            raise IOError(f"写出失败，文件大小为 0: {output_file}")

        # 返回相对路径
        rel_path = str(output_file.relative_to(self.output_dir))

        return {
            "path": rel_path,
            "uri": str(output_file.resolve().as_uri()),
            "rows": len(df),
            "columns": list(df.columns),
            "size_bytes": file_size,
        }

    def write_bytes(
        self,
        df: "pd.DataFrame",
        output_name: str,
        *,
        index: bool = False,
        compression: str = "snappy",
        metadata: Optional[dict] = None,
    ) -> tuple[bytes, dict]:
        """将 pandas DataFrame 序列化为 Parquet bytes 和元数据（不写文件）。

        参数：
            df: 要写出的 DataFrame
            output_name: 输出文件名（不含扩展名）
            index: 是否包含索引列
            compression: 压缩算法，默认 "snappy"
            metadata: 自定义元数据字典

        返回：
            (bytes, dict): Parquet 字节数据和元数据字典。
                元数据: {"path": str, "rows": int, "columns": list[str], "size_bytes": int}
        """
        from io import BytesIO

        pd, pa, pq = _check_dependencies()

        parquet_metadata: dict[str, Any] = {}
        if metadata:
            parquet_metadata.update(metadata)
        parquet_metadata["write_time"] = datetime.utcnow().isoformat()
        parquet_metadata["rows"] = len(df)
        parquet_metadata["columns"] = list(df.columns)

        table = pa.Table.from_pandas(df, preserve_index=index)
        if parquet_metadata:
            new_schema = table.schema.with_metadata(parquet_metadata)
            table = table.cast(new_schema)

        buf = BytesIO()
        pq.write_table(table, buf, compression=compression)
        parquet_bytes = buf.getvalue()
        if len(parquet_bytes) == 0:
            raise IOError("Parquet 序列化失败，缓冲区为空")

        rel_path = f"{output_name}.parquet"
        return parquet_bytes, {
            "path": rel_path,
            "rows": len(df),
            "columns": list(df.columns),
            "size_bytes": len(parquet_bytes),
        }


# ---------------------------------------------------------------------------
# write_timeseries - 时序数据写出辅助函数
# ---------------------------------------------------------------------------


def write_timeseries(
    times: list[str] | np.ndarray,
    values: np.ndarray,
    columns: list[str],
    output_path: Path | str,
    *,
    station_ids: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """将时序数据写出为 Parquet。

    参数：
        times: 时间序列，ISO 格式时间字符串列表或 numpy datetime64 数组
        values: 数值数组，shape (n_times, n_stations) 或 (n_times,)
        columns: 数据列名列表，与 values 的列数对应
        output_path: 输出文件路径
        station_ids: 站点 ID 列表（用于行索引名称）
        metadata: 自定义元数据字典

    返回：
        dict: {
            "path": str,
            "uri": str,
            "rows": int,
            "columns": list[str],
            "size_bytes": int,
        }
    """
    pd, pa, pq = _check_dependencies()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 转换时间
    if isinstance(times, np.ndarray):
        # 兼容 numpy datetime64
        if np.issubdtype(times.dtype, np.datetime64):
            times = pd.to_datetime(times).isoformat()
        else:
            times = list(times)

    # 标准化 values 为 2D 数组
    values = np.asarray(values)
    if values.ndim == 1:
        values = values.reshape(-1, 1)
    elif values.ndim != 2:
        raise ValueError(f"values 数组维度必须为 1D 或 2D，当前为 {values.ndim}D")

    n_times = len(times)
    n_stations = values.shape[1]

    if len(columns) != n_stations:
        raise ValueError(
            f"columns 长度 ({len(columns)}) 与 values 列数 ({n_stations}) 不匹配"
        )

    # 构建 DataFrame
    data_dict: dict[str, Any] = {"time": times}
    for i, col in enumerate(columns):
        data_dict[col] = values[:, i]

    df = pd.DataFrame(data_dict)
    df.set_index("time", inplace=True)

    # 写入 Parquet
    table = pa.Table.from_pandas(df, preserve_index=False)

    # 添加元数据
    meta_dict: dict[str, Any] = {
        "write_time": datetime.utcnow().isoformat(),
        "n_times": n_times,
        "columns": columns,
    }
    if station_ids:
        meta_dict["station_ids"] = station_ids
    if metadata:
        meta_dict.update(metadata)

    if meta_dict:
        new_schema = table.schema.with_metadata(meta_dict)
        table = table.cast(new_schema)

    pq.write_table(table, output_path, compression="snappy")

    # 验证文件
    if not output_path.exists():
        raise IOError(f"时序数据写出失败: {output_path}")
    file_size = output_path.stat().st_size
    if file_size == 0:
        raise IOError(f"时序数据写出失败，文件大小为 0: {output_path}")

    return {
        "path": str(output_path),
        "uri": str(output_path.resolve().as_uri()),
        "rows": n_times,
        "columns": columns,
        "size_bytes": file_size,
    }
