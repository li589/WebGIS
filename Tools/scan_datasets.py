#!/usr/bin/env python3
"""
数据集文件清单扫描工具

递归扫描 I:\\Geograph_DataSet 下所有文件，记录序号、文件名、格式、大小、路径，
生成 JSON + CSV 供反复读取和精确查找。

用法:
    python Tools/scan_datasets.py                      # 基本扫描
    python Tools/scan_datasets.py --root I:\\Geograph_DataSet
    python Tools/scan_datasets.py --deep               # 深度扫描（读取 .mat/.nc/.tif 元数据）
    python Tools/scan_datasets.py --deep --limit 100   # 深度扫描，只处理前 100 个文件

输出:
    Tools/reports/dataset_inventory_<timestamp>.json   # 完整结构化数据
    Tools/reports/dataset_inventory_<timestamp>.csv    # CSV 格式（Excel 可打开）
    Tools/reports/dataset_inventory_latest.json        # 最新快捷链接
    Tools/reports/dataset_inventory_latest.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from data_root import resolve_data_root
from typing import Any

# ── 常量 ─────────────────────────────────────────────────────────────────────

DEFAULT_ROOT = str(resolve_data_root())
OUTPUT_DIR = Path(__file__).resolve().parent / "reports"

# 扩展名 → 格式分类映射
EXT_FORMAT_MAP: dict[str, str] = {
    # 栅格
    ".tif": "raster_geotiff",
    ".tiff": "raster_geotiff",
    ".img": "raster_erdas",
    ".asc": "raster_ascii",
    ".bil": "raster_binary",
    ".bsq": "raster_binary",
    ".vrt": "raster_vrt",
    # NetCDF / HDF
    ".nc": "netcdf",
    ".nc4": "netcdf",
    ".hdf": "hdf4",
    ".hdf5": "hdf5",
    ".h5": "hdf5",
    ".he5": "hdf5",
    # MATLAB
    ".mat": "matlab",
    # 矢量
    ".shp": "vector_shapefile",
    ".geojson": "vector_geojson",
    ".json": "vector_geojson",
    ".kml": "vector_kml",
    ".kmz": "vector_kmz",
    ".gpkg": "vector_geopackage",
    ".gml": "vector_gml",
    ".tab": "vector_mapinfo",
    # 压缩
    ".zip": "archive_zip",
    ".7z": "archive_7z",
    ".rar": "archive_rar",
    ".gz": "archive_gzip",
    ".tar": "archive_tar",
    ".tgz": "archive_targz",
    # 文本/表格
    ".csv": "text_csv",
    ".txt": "text_plain",
    ".tsv": "text_tsv",
    ".xml": "text_xml",
    ".yaml": "text_yaml",
    ".yml": "text_yaml",
    ".md": "text_markdown",
    ".ini": "text_config",
    ".cfg": "text_config",
    ".json5": "text_json",
    # 图片
    ".png": "image_png",
    ".jpg": "image_jpeg",
    ".jpeg": "image_jpeg",
    ".bmp": "image_bmp",
    ".gif": "image_gif",
    ".svg": "image_svg",
    ".webp": "image_webp",
    # PDF
    ".pdf": "document_pdf",
    # Excel
    ".xlsx": "spreadsheet_excel",
    ".xls": "spreadsheet_excel",
    # 可执行/库
    ".exe": "executable",
    ".dll": "library",
    ".py": "script_python",
    ".bat": "script_batch",
    ".sh": "script_shell",
    ".ps1": "script_powershell",
    # 其他
    ".db": "database",
    ".sqlite": "database",
    ".dat": "binary_data",
    ".bin": "binary_data",
    ".tmp": "temp",
    ".log": "log",
    ".gitkeep": "placeholder",
    ".pyc": "python_cache",
}

# 需要深度扫描的扩展名
DEEP_SCAN_EXTS = {".mat", ".nc", ".nc4", ".hdf", ".hdf5", ".h5", ".he5", ".tif", ".tiff"}


# ── 数据结构 ──────────────────────────────────────────────────────────────────


@dataclass
class FileEntry:
    """单个文件的清单记录"""

    index: int  # 序号（从 1 开始）
    filename: str  # 文件名（含扩展名）
    extension: str  # 扩展名（小写，含点）
    format: str  # 格式分类
    size_bytes: int  # 文件大小（字节）
    size_human: str  # 人类可读大小
    full_path: str  # 完整路径
    relative_path: str  # 相对于 root 的路径
    top_dir: str  # 顶层目录名
    sub_dir: str  # 子目录路径（相对于 top_dir）
    mtime: str  # 最后修改时间 ISO 格式
    # 深度扫描字段（可选）
    metadata: dict[str, Any] | None = None  # 变量名、维度、CRS 等


@dataclass
class ScanSummary:
    """扫描汇总统计"""

    scan_time: str  # 扫描时间
    root_dir: str  # 扫描根目录
    total_files: int  # 总文件数
    total_size_bytes: int  # 总大小（字节）
    total_size_human: str  # 总大小（人类可读）
    top_dirs: dict[str, dict[str, Any]] = field(default_factory=dict)  # 顶层目录统计
    by_format: dict[str, dict[str, Any]] = field(default_factory=dict)  # 按格式统计
    by_extension: dict[str, int] = field(default_factory=dict)  # 按扩展名统计
    scan_duration_sec: float = 0.0  # 扫描耗时（秒）
    deep_scan: bool = False  # 是否深度扫描
    unknown_files: list[dict[str, str]] = field(default_factory=list)  # 无法分类的文件


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def human_size(size_bytes: int) -> str:
    """将字节数转换为人类可读大小"""
    if size_bytes == 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def classify_format(ext: str) -> str:
    """根据扩展名分类文件格式"""
    ext_lower = ext.lower()
    return EXT_FORMAT_MAP.get(ext_lower, "unknown")


def format_mtime(ts: float) -> str:
    """格式化修改时间"""
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError):
        return "unknown"


def read_mat_metadata(filepath: str) -> dict[str, Any]:
    """读取 .mat 文件的变量名和形状"""
    try:
        import scipy.io as sio
        import h5py

        # 先尝试 v7.3 (HDF5) 格式
        try:
            with h5py.File(filepath, "r") as f:
                vars_info = {}
                for key in f.keys():
                    if isinstance(f[key], h5py.Dataset):
                        vars_info[key] = {
                            "shape": list(f[key].shape),
                            "dtype": str(f[key].dtype),
                        }
                return {"format": "mat_v73", "variables": vars_info}
        except Exception:
            pass

        # 回退到 v5/v7 格式
        mat = sio.loadmat(filepath, squeeze_me=False, struct_as_record=False)
        vars_info = {}
        for key in mat:
            if key.startswith("__"):
                continue
            val = mat[key]
            if hasattr(val, "shape"):
                vars_info[key] = {
                    "shape": list(val.shape),
                    "dtype": str(val.dtype),
                }
            else:
                vars_info[key] = {"type": type(val).__name__}
        return {"format": "mat_v5", "variables": vars_info}
    except Exception as e:
        return {"error": str(e)}


def read_netcdf_metadata(filepath: str) -> dict[str, Any]:
    """读取 NetCDF 文件的变量名和维度"""
    try:
        try:
            import netCDF4 as nc

            ds = nc.Dataset(filepath, "r")
            vars_info = {}
            for var in ds.variables:
                vars_info[var] = {
                    "shape": list(ds.variables[var].shape),
                    "dimensions": list(ds.variables[var].dimensions),
                    "dtype": str(ds.variables[var].dtype),
                }
            dims = {d: len(ds.dimensions[d]) for d in ds.dimensions}
            ds.close()
            return {"format": "netcdf", "variables": vars_info, "dimensions": dims}
        except ImportError:
            pass

        # 回退到 h5py
        import h5py

        with h5py.File(filepath, "r") as f:
            vars_info = {}
            for key in f.keys():
                if isinstance(f[key], h5py.Dataset):
                    vars_info[key] = {
                        "shape": list(f[key].shape),
                        "dtype": str(f[key].dtype),
                    }
            return {"format": "hdf5", "variables": vars_info}
    except Exception as e:
        return {"error": str(e)}


def read_geotiff_metadata(filepath: str) -> dict[str, Any]:
    """读取 GeoTIFF 文件的 CRS 和形状"""
    try:
        import rasterio

        with rasterio.open(filepath) as src:
            return {
                "format": "geotiff",
                "crs": str(src.crs) if src.crs else "unknown",
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "bounds": list(src.bounds) if src.bounds else None,
                "dtype": str(src.dtypes[0]) if src.dtypes else "unknown",
            }
    except Exception as e:
        return {"error": str(e)}


def read_deep_metadata(filepath: str, ext: str) -> dict[str, Any] | None:
    """深度读取文件元数据"""
    ext_lower = ext.lower()
    if ext_lower == ".mat":
        return read_mat_metadata(filepath)
    elif ext_lower in (".nc", ".nc4"):
        return read_netcdf_metadata(filepath)
    elif ext_lower in (".hdf5", ".h5", ".he5"):
        try:
            import h5py

            with h5py.File(filepath, "r") as f:
                vars_info = {}
                for key in f.keys():
                    if isinstance(f[key], h5py.Dataset):
                        vars_info[key] = {
                            "shape": list(f[key].shape),
                            "dtype": str(f[key].dtype),
                        }
                return {"format": "hdf5", "variables": vars_info}
        except Exception as e:
            return {"error": str(e)}
    elif ext_lower in (".tif", ".tiff"):
        return read_geotiff_metadata(filepath)
    return None


# ── 主扫描逻辑 ────────────────────────────────────────────────────────────────


def scan_directory(
    root: str,
    deep: bool = False,
    limit: int | None = None,
    progress_every: int = 2000,
) -> tuple[list[FileEntry], ScanSummary]:
    """扫描目录，返回文件清单和汇总统计"""

    root_path = Path(root)
    if not root_path.exists():
        raise FileNotFoundError(f"根目录不存在: {root}")

    start_time = time.time()
    entries: list[FileEntry] = []
    index = 0

    # 统计用
    total_size = 0
    top_dir_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"file_count": 0, "total_size_bytes": 0}
    )
    format_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"file_count": 0, "total_size_bytes": 0}
    )
    ext_stats: Counter = Counter()
    unknown_files: list[dict[str, str]] = []

    print(f"扫描根目录: {root_path}")
    print(f"深度扫描: {'是' if deep else '否'}")
    if limit:
        print(f"深度扫描限制: 前 {limit} 个文件")
    print("-" * 60)

    deep_scanned = 0

    for dirpath, dirnames, filenames in os.walk(root_path):
        # 跳过 .git 目录
        if ".git" in dirnames:
            dirnames.remove(".git")

        for filename in filenames:
            index += 1
            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, root_path)

            # 获取文件信息
            try:
                stat = os.stat(filepath)
            except OSError:
                continue

            ext = os.path.splitext(filename)[1]
            fmt = classify_format(ext)
            size = stat.st_size
            total_size += size

            # 计算目录层级
            parts = rel_path.replace("\\", "/").split("/")
            top_dir = parts[0] if len(parts) > 0 else ""
            sub_dir = "/".join(parts[1:-1]) if len(parts) > 2 else ""

            # 深度扫描
            metadata = None
            if deep and ext.lower() in DEEP_SCAN_EXTS:
                if limit is None or deep_scanned < limit:
                    metadata = read_deep_metadata(filepath, ext)
                    deep_scanned += 1

            entry = FileEntry(
                index=index,
                filename=filename,
                extension=ext.lower(),
                format=fmt,
                size_bytes=size,
                size_human=human_size(size),
                full_path=filepath,
                relative_path=rel_path.replace("\\", "/"),
                top_dir=top_dir,
                sub_dir=sub_dir,
                mtime=format_mtime(stat.st_mtime),
                metadata=metadata,
            )
            entries.append(entry)

            # 更新统计
            top_dir_stats[top_dir]["file_count"] += 1
            top_dir_stats[top_dir]["total_size_bytes"] += size
            format_stats[fmt]["file_count"] += 1
            format_stats[fmt]["total_size_bytes"] += size
            ext_stats[ext.lower()] += 1

            if fmt == "unknown" and ext:
                unknown_files.append({
                    "filename": filename,
                    "extension": ext.lower(),
                    "path": rel_path.replace("\\", "/"),
                })

            # 进度提示
            if index % progress_every == 0:
                elapsed = time.time() - start_time
                print(f"  [{index} files] {elapsed:.1f}s - {rel_path}")

    scan_duration = time.time() - start_time

    # 计算汇总
    for td, stats in top_dir_stats.items():
        stats["total_size_human"] = human_size(stats["total_size_bytes"])
    for fmt, stats in format_stats.items():
        stats["total_size_human"] = human_size(stats["total_size_bytes"])

    summary = ScanSummary(
        scan_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        root_dir=str(root_path),
        total_files=index,
        total_size_bytes=total_size,
        total_size_human=human_size(total_size),
        top_dirs=dict(sorted(top_dir_stats.items())),
        by_format=dict(sorted(format_stats.items())),
        by_extension=dict(sorted(ext_stats.items())),
        scan_duration_sec=round(scan_duration, 2),
        deep_scan=deep,
        unknown_files=unknown_files,
    )

    print("-" * 60)
    print(f"扫描完成: {index} files, {summary.total_size_human}, {scan_duration:.1f}s")
    if deep:
        print(f"深度扫描: {deep_scanned} files with metadata")
    if unknown_files:
        print(f"未知格式文件: {len(unknown_files)} 个")

    return entries, summary


# ── 输出 ──────────────────────────────────────────────────────────────────────


def save_results(
    entries: list[FileEntry],
    summary: ScanSummary,
    output_dir: Path,
) -> tuple[Path, Path]:
    """保存 JSON 和 CSV 结果，返回路径"""

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = output_dir / f"dataset_inventory_{timestamp}.json"
    csv_path = output_dir / f"dataset_inventory_{timestamp}.csv"
    latest_json = output_dir / "dataset_inventory_latest.json"
    latest_csv = output_dir / "dataset_inventory_latest.csv"

    # JSON
    result = {
        "summary": asdict(summary),
        "files": [asdict(e) for e in entries],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 复制为 latest
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # CSV
    fieldnames = [
        "index",
        "filename",
        "extension",
        "format",
        "size_bytes",
        "size_human",
        "top_dir",
        "sub_dir",
        "relative_path",
        "full_path",
        "mtime",
    ]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            row = {k: getattr(entry, k) for k in fieldnames}
            writer.writerow(row)

    # 复制为 latest CSV
    with open(latest_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            row = {k: getattr(entry, k) for k in fieldnames}
            writer.writerow(row)

    print(f"\n输出文件:")
    print(f"  JSON: {json_path}")
    print(f"  CSV:  {csv_path}")
    print(f"  Latest JSON: {latest_json}")
    print(f"  Latest CSV:  {latest_csv}")

    return json_path, csv_path


def print_summary(summary: ScanSummary) -> None:
    """打印汇总统计"""

    print("\n" + "=" * 60)
    print(" 汇总统计")
    print("=" * 60)

    print(f"\n扫描时间: {summary.scan_time}")
    print(f"根目录: {summary.root_dir}")
    print(f"总文件数: {summary.total_files}")
    print(f"总大小: {summary.total_size_human}")
    print(f"扫描耗时: {summary.scan_duration_sec}s")

    print(f"\n--- 按顶层目录 ---")
    print(f"{'目录名':<30} {'文件数':>8} {'大小':>12}")
    print("-" * 52)
    for td, stats in summary.top_dirs.items():
        print(f"{td:<30} {stats['file_count']:>8} {stats['total_size_human']:>12}")

    print(f"\n--- 按格式分类 ---")
    print(f"{'格式':<25} {'文件数':>8} {'大小':>12}")
    print("-" * 47)
    for fmt, stats in summary.by_format.items():
        print(f"{fmt:<25} {stats['file_count']:>8} {stats['total_size_human']:>12}")

    print(f"\n--- 按扩展名 ---")
    print(f"{'扩展名':<15} {'文件数':>8}")
    print("-" * 25)
    for ext, count in summary.by_extension.items():
        print(f"{ext:<15} {count:>8}")

    if summary.unknown_files:
        print(f"\n--- 未知格式文件 ({len(summary.unknown_files)} 个) ---")
        for uf in summary.unknown_files[:20]:
            print(f"  {uf['extension']:<10} {uf['path']}")
        if len(summary.unknown_files) > 20:
            print(f"  ... 还有 {len(summary.unknown_files) - 20} 个")


# ── 主入口 ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="数据集文件清单扫描工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python Tools/scan_datasets.py                      # 基本扫描
    python Tools/scan_datasets.py --deep               # 深度扫描（读取元数据，较慢）
    python Tools/scan_datasets.py --deep --limit 50    # 深度扫描前 50 个文件
    python Tools/scan_datasets.py --root D:\\Data       # 指定其他根目录
        """,
    )
    parser.add_argument(
        "--root",
        default=DEFAULT_ROOT,
        help=f"扫描根目录 (默认: {DEFAULT_ROOT})",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="深度扫描：读取 .mat/.nc/.tif 等文件的变量名、维度、CRS 等元数据",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="深度扫描时限制处理的文件数（用于测试）",
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_DIR),
        help=f"输出目录 (默认: {OUTPUT_DIR})",
    )
    args = parser.parse_args()

    # 扫描
    entries, summary = scan_directory(
        root=args.root,
        deep=args.deep,
        limit=args.limit,
    )

    # 保存
    json_path, csv_path = save_results(
        entries=entries,
        summary=summary,
        output_dir=Path(args.output),
    )

    # 打印汇总
    print_summary(summary)

    print(f"\n{'=' * 60}")
    print(" 扫描完成！")
    print(f"{'=' * 60}")
    print(f"\nJSON 文件可供 TRAE 读取分析: {json_path}")
    print(f"CSV 文件可用 Excel 打开查看: {csv_path}")
    print(f"\n提示: 如需深度扫描元数据，添加 --deep 参数")


if __name__ == "__main__":
    main()
