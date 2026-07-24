#!/usr/bin/env python3
"""分析扫描检查点文件，输出数据分类统计。"""

import json
import sys
from collections import Counter
from pathlib import Path


def analyze_checkpoint(checkpoint_path: str) -> None:
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"服务器: {data['server']}")
    print(f"扫描时间: {data['scan_time']}")
    print(f"已扫描目录: {data['dirs_scanned']}")
    print(f"找到文件: {data['files_found']}")
    print(f"截断文件: {data['files_truncated']}")
    print(f"目录深度分布: {data['dirs_by_depth']}")
    print()

    # 按扩展名统计
    ext_counter = Counter()
    ext_size = Counter()
    cat_counter = Counter()
    cat_size = Counter()
    top_dirs = Counter()
    top_dirs_size = Counter()

    for item in data["results"]:
        ext_counter[item["extension"]] += 1
        ext_size[item["extension"]] += item["size_bytes"]
        for cat in item["categories"]:
            cat_counter[cat] += 1
            cat_size[cat] += item["size_bytes"]
        # 提取顶层目录
        path = item["remote_path"]
        parts = path.strip("/").split("/")
        if len(parts) > 1:
            key = parts[0] + "/" + parts[1]
            top_dirs[key] += 1
            top_dirs_size[key] += item["size_bytes"]
        elif len(parts) == 1:
            top_dirs[parts[0]] += 1
            top_dirs_size[parts[0]] += item["size_bytes"]

    def fmt_size(size_bytes: int) -> str:
        if size_bytes == 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        while size >= 1024 and i < len(units) - 1:
            size /= 1024
            i += 1
        return f"{size:.1f} {units[i]}"

    print("=== 按扩展名统计 ===")
    print(f"  {'扩展名':<12s} {'数量':>8s} {'大小':>12s}")
    print(f"  {'─'*12} {'─'*8} {'─'*12}")
    for ext, count in ext_counter.most_common():
        print(f"  {ext:<12s} {count:>8d} {fmt_size(ext_size[ext]):>12s}")

    print()
    print("=== 按分类统计 ===")
    print(f"  {'分类':<12s} {'数量':>8s} {'大小':>12s}")
    print(f"  {'─'*12} {'─'*8} {'─'*12}")
    for cat, count in cat_counter.most_common():
        print(f"  {cat:<12s} {count:>8d} {fmt_size(cat_size[cat]):>12s}")

    print()
    print("=== Top 30 顶层目录（按文件数） ===")
    print(f"  {'数量':>6s} {'大小':>12s}  路径")
    print(f"  {'─'*6} {'─'*12}  {'─'*40}")
    for dir_path, count in top_dirs.most_common(30):
        print(f"  {count:>6d} {fmt_size(top_dirs_size[dir_path]):>12s}  {dir_path}")

    # 总大小
    total_size = sum(item["size_bytes"] for item in data["results"])
    print(f"\n总大小: {fmt_size(total_size)}")

    # Top 20 大文件
    print("\n=== Top 20 大文件 ===")
    sorted_files = sorted(data["results"], key=lambda x: x["size_bytes"], reverse=True)
    print(f"  {'大小':<12s} {'分类':<16s} 路径")
    print(f"  {'─'*12} {'─'*16} {'─'*50}")
    for item in sorted_files[:20]:
        cats = ",".join(item["categories"][:2])
        path_display = item["remote_path"]
        if len(path_display) > 60:
            path_display = "..." + path_display[-57:]
        print(f"  {item['size_human']:<12s} {cats:<16s} {path_display}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # 默认查找最新的检查点文件
        report_dir = Path(
            r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Tools\reports"
        )
        checkpoints = sorted(
            report_dir.glob("checkpoint_*.json"), key=lambda p: p.stat().st_mtime
        )
        if checkpoints:
            print(f"使用最新检查点: {checkpoints[-1]}")
            analyze_checkpoint(str(checkpoints[-1]))
        else:
            print(
                "未找到检查点文件。用法: python analyze_checkpoint.py <checkpoint.json>"
            )
            sys.exit(1)
    else:
        analyze_checkpoint(sys.argv[1])
