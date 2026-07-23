#!/usr/bin/env python3
"""分析扫描报告，按时间分辨率筛选下载候选文件。

根据文件名中的日期模式，将远程文件分为：
  - 日数据（文件名含 YYYYMMDD 或 YYYY_DOY）：建议下载 ~30 天
  - 月数据（文件名含 YYYYMM）：建议下载 ~3 个月
  - 年数据（文件名含 YYYY 且无月/日）：建议下载 ~3 年
  - 静态/无时间：按需下载

输出下载候选清单 JSON 文件，供 remote_data_scanner.py download 使用。
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPORT_DIR = Path(
    r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Tools\reports"
)
OUTPUT_PATH = REPORT_DIR / "download_candidates.json"

# 中国区域大致经纬度范围（用于筛选已有区域切片）
CHINA_BBOX = {"lon_min": 73, "lon_max": 136, "lat_min": 18, "lat_max": 54}


def detect_temporal_resolution(name: str) -> str:
    """根据文件名推断时间分辨率。"""
    lower = name.lower()

    # 日数据：YYYYMMDD 或 YYYY_DOY
    if re.search(r"\d{8}", name) or re.search(r"\d{4}_\d{3}", name):
        return "daily"
    if re.search(r"_d\d{8}", lower) or re.search(r"_d20\d{6}", lower):
        return "daily"

    # 月数据：YYYYMM（6位数字，不以日结尾）
    if re.search(r"_\d{6}[._]", name) or re.search(r"\d{4}\d{2}\.", name):
        return "monthly"

    # 年数据：YYYY（4位数字）
    year_matches = re.findall(r"(20\d{2}|19\d{2})", name)
    if year_matches:
        return "yearly"

    return "static"


def extract_date_info(name: str) -> dict:
    """提取文件名中的日期信息。"""
    info = {"year": None, "month": None, "day": None, "doy": None}

    # YYYYMMDD
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", name)
    if m:
        info["year"] = int(m.group(1))
        info["month"] = int(m.group(2))
        info["day"] = int(m.group(3))
        return info

    # YYYY_DOY
    m = re.search(r"(20\d{2})_(\d{3})", name)
    if m:
        info["year"] = int(m.group(1))
        info["doy"] = int(m.group(2))
        return info

    # YYYYMM
    m = re.search(r"(20\d{2})(\d{2})(?:[._]|$)", name)
    if m:
        info["year"] = int(m.group(1))
        info["month"] = int(m.group(2))
        return info

    # YYYY
    m = re.search(r"(20\d{2}|19\d{2})", name)
    if m:
        info["year"] = int(m.group(1))

    return info


def is_china_region(name: str, path: str) -> bool:
    """检查文件是否可能覆盖中国区域（或为全球数据）。"""
    lower = (name + " " + path).lower()

    # 全球数据默认包含中国
    global_keywords = [
        "global",
        "world",
        "esa",
        "smap",
        "gldas",
        "era5",
        "gpm",
        "trmm",
        "igbp",
        "mcd12",
        "esacci",
        "biomass",
        "hfp",
        "forest_height",
        "canopy",
        "dem",
        "srtm",
        "gebco",
    ]
    for kw in global_keywords:
        if kw in lower:
            return True

    # 明确的中国/亚洲区域
    china_keywords = [
        "china",
        "asia",
        "sasia",
        "nasia",
        "sam_",
        "中国",
        "亚洲",
        "chinese",
        "beijing",
        "yangtze",
    ]
    for kw in china_keywords:
        if kw in lower:
            return True

    # 经纬度切片（检查是否在中国范围内）
    # 如 N30E110, S20W060 等命名
    tile_match = re.search(r"([NS])(\d{1,2})([EW])(\d{1,3})", name, re.IGNORECASE)
    if tile_match:
        lat = int(tile_match.group(2)) * (
            1 if tile_match.group(1).upper() == "N" else -1
        )
        lon = int(tile_match.group(4)) * (
            1 if tile_match.group(3).upper() == "E" else -1
        )
        if (
            CHINA_BBOX["lat_min"] <= lat <= CHINA_BBOX["lat_max"]
            and CHINA_BBOX["lon_min"] <= lon <= CHINA_BBOX["lon_max"]
        ):
            return True
        return False

    return True  # 默认包含


def select_candidates(report_path: Path) -> dict:
    """分析报告并选择下载候选。"""
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    # 收集所有文件
    all_files: list[dict] = []
    if "by_server" in report:
        for srv_data in report["by_server"].values():
            all_files.extend(srv_data["files"])
    elif "results" in report:
        all_files = report["results"]

    print(f"报告文件: {report_path.name}")
    print(f"总文件数: {len(all_files)}")

    # 按时间分辨率分组
    by_resolution: dict[str, list[dict]] = defaultdict(list)
    for f in all_files:
        res = detect_temporal_resolution(f["name"])
        f["_temporal"] = res
        f["_china"] = is_china_region(f["name"], f.get("remote_path", ""))
        by_resolution[res].append(f)

    print("\n按时间分辨率分布:")
    for res in ["daily", "monthly", "yearly", "static"]:
        files = by_resolution[res]
        total_size = sum(f["size_bytes"] for f in files)
        china_count = sum(1 for f in files if f["_china"])
        print(
            f"  {res:8s}: {len(files):5d} 文件 ({china_count} 中国相关), "
            f"总大小 {total_size / 1e9:.1f} GB"
        )

    # 选择候选文件
    candidates: list[dict] = []

    # 1. 日数据：选最近30天，优先小文件
    daily_files = [f for f in by_resolution["daily"] if f["_china"]]
    daily_files.sort(key=lambda x: (x.get("_date_year", 0), x["size_bytes"]))
    # 取最近30个日文件，且单个文件 < 500MB
    daily_candidates = [f for f in daily_files if f["size_bytes"] < 500 * 1024 * 1024][
        -30:
    ]

    # 2. 月数据：选最近3个月
    monthly_files = [f for f in by_resolution["monthly"] if f["_china"]]
    monthly_files.sort(key=lambda x: x["size_bytes"])
    monthly_candidates = [
        f for f in monthly_files if f["size_bytes"] < 500 * 1024 * 1024
    ][-3:]

    # 3. 年数据：选最近3年，每个数据集最多1个文件/年
    yearly_files = [f for f in by_resolution["yearly"] if f["_china"]]
    # 按目录分组，每组取最近3年
    yearly_by_dir: dict[str, list[dict]] = defaultdict(list)
    for f in yearly_files:
        dir_path = str(Path(f.get("remote_path", "")).parent)
        yearly_by_dir[dir_path].append(f)

    yearly_candidates: list[dict] = []
    for dir_path, files in yearly_by_dir.items():
        # 按年份排序，取最近3年
        for f in files:
            date_info = extract_date_info(f["name"])
            f["_date_info"] = date_info
        files.sort(key=lambda x: x.get("_date_info", {}).get("year", 0), reverse=True)
        # 每组最多取3个，且单个文件 < 20GB
        for f in files[:3]:
            if f["size_bytes"] < 20 * 1024 * 1024 * 1024:
                yearly_candidates.append(f)

    # 4. 静态/小文件数据：omega 结果、ISMN/FLUX 站点等
    static_files = [f for f in by_resolution["static"] if f["_china"]]
    static_small = [f for f in static_files if f["size_bytes"] < 500 * 1024 * 1024]
    # 按 .mat 文件优先（omega 结果）
    static_candidates = sorted(
        static_small,
        key=lambda x: (
            0 if x["extension"] == ".mat" else 1,
            x["size_bytes"],
        ),
    )[:50]

    # 合并候选
    candidates = (
        daily_candidates + monthly_candidates + yearly_candidates + static_candidates
    )

    total_size = sum(f["size_bytes"] for f in candidates)
    print("\n=== 下载候选 ===")
    print(
        f"日数据: {len(daily_candidates)} 文件, {sum(f['size_bytes'] for f in daily_candidates)/1e9:.1f} GB"
    )
    print(
        f"月数据: {len(monthly_candidates)} 文件, {sum(f['size_bytes'] for f in monthly_candidates)/1e9:.1f} GB"
    )
    print(
        f"年数据: {len(yearly_candidates)} 文件, {sum(f['size_bytes'] for f in yearly_candidates)/1e9:.1f} GB"
    )
    print(
        f"静态/小文件: {len(static_candidates)} 文件, {sum(f['size_bytes'] for f in static_candidates)/1e9:.1f} GB"
    )
    print(f"总计: {len(candidates)} 文件, {total_size/1e9:.1f} GB")

    # 打印详细列表
    print(f"\n--- 日数据候选 ({len(daily_candidates)}) ---")
    for f in daily_candidates[:10]:
        print(f"  {f['size_human']:>12s}  {f['server']:6s}  {f['remote_path']}")
    if len(daily_candidates) > 10:
        print(f"  ... and {len(daily_candidates) - 10} more")

    print(f"\n--- 月数据候选 ({len(monthly_candidates)}) ---")
    for f in monthly_candidates:
        print(f"  {f['size_human']:>12s}  {f['server']:6s}  {f['remote_path']}")

    print(f"\n--- 年数据候选 ({len(yearly_candidates)}) ---")
    for f in yearly_candidates:
        print(f"  {f['size_human']:>12s}  {f['server']:6s}  {f['remote_path']}")

    print(f"\n--- 静态/小文件候选 ({len(static_candidates)}) ---")
    for f in static_candidates[:20]:
        print(f"  {f['size_human']:>12s}  {f['server']:6s}  {f['remote_path']}")
    if len(static_candidates) > 20:
        print(f"  ... and {len(static_candidates) - 20} more")

    # 保存候选清单
    output = {
        "description": "Download candidates for China region testing",
        "total_files": len(candidates),
        "total_size_human": _format_size(total_size),
        "by_temporal": {
            "daily": len(daily_candidates),
            "monthly": len(monthly_candidates),
            "yearly": len(yearly_candidates),
            "static": len(static_candidates),
        },
        "files": candidates,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n候选清单已保存: {OUTPUT_PATH}")

    return output


def _format_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}"


if __name__ == "__main__":
    # 找最新的扫描报告
    reports = sorted(REPORT_DIR.glob("scan_report_*.json"))
    if not reports:
        print("未找到扫描报告文件")
        sys.exit(1)

    report_path = reports[-1]
    print(f"使用报告: {report_path}")

    # 也检查 win11 检查点
    checkpoints = sorted(REPORT_DIR.glob("checkpoint_win11_*.json"))
    if checkpoints:
        print(f"Win11 检查点: {checkpoints[-1]}")

    select_candidates(report_path)
