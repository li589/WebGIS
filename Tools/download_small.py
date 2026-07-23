#!/usr/bin/env python3
"""分批下载：先下载小文件（< 500 MB），大文件稍后处理。"""

import sys

sys.path.insert(
    0, r"d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Tools"
)
from download_curated import (
    FileBrowserClient,
    LOCAL_ROOT,
    SERVERS,
    DOWNLOAD_LIST,
    _format_size,
)
from pathlib import Path
import time

MAX_SIZE_MB = 500  # 只下载 < 500 MB 的文件


def main():
    # 按大小排序，小的先下载
    small_files = [(s, r, d, desc) for s, r, d, desc in DOWNLOAD_LIST]
    # 我们无法提前知道文件大小，所以按描述中的大小提示排序
    # 实际上我们按下载列表顺序，但跳过已知的大文件

    # 已知大文件（> 500 MB）的路径关键词
    large_keywords = [
        "ESACCI-BIOMASS",
        "ERA5_20",
        "ERA5_2019_SMCI",
        "ERA5_2018_SMCI",
        "hfp2018",
        "CLCD_v01_1997_albert",
        "CLCD_v01_1997.tif",
        "Landscape_Metrics",
        "Forest_Ratio",
    ]

    to_download = []
    skipped_large = []

    for server, remote_path, local_subdir, desc in DOWNLOAD_LIST:
        filename = Path(remote_path).name
        local_path = LOCAL_ROOT / local_subdir / filename

        # 跳过已存在的
        if local_path.exists():
            print(f"SKIP (exists): {filename} -> {local_subdir}\\")
            continue

        # 跳过大文件
        is_large = any(kw.lower() in remote_path.lower() for kw in large_keywords)
        if is_large:
            skipped_large.append((server, remote_path, local_subdir, desc))
            continue

        to_download.append((server, remote_path, local_subdir, desc))

    print(f"待下载: {len(to_download)} 个小文件")
    print(f"跳过大文件: {len(skipped_large)} 个（稍后处理）")
    print()

    # 按服务器分组
    by_server = {}
    for server, remote_path, local_subdir, desc in to_download:
        by_server.setdefault(server, []).append((remote_path, local_subdir, desc))

    total_ok = 0
    total_fail = 0

    for server_key, items in by_server.items():
        cfg = SERVERS[server_key]
        client = FileBrowserClient(cfg["base_url"], cfg["username"], cfg["password"])
        client.login()
        print(f"[{server_key}] 下载 {len(items)} 个文件...")

        for i, (remote_path, local_subdir, desc) in enumerate(items, 1):
            filename = Path(remote_path).name
            local_path = LOCAL_ROOT / local_subdir / filename

            try:
                print(f"  [{i}/{len(items)}] {desc}")
                start = time.time()
                size = client.download_file(remote_path, local_path)
                elapsed = time.time() - start
                speed = size / elapsed if elapsed > 0 else 0
                print(
                    f"    OK: {_format_size(size)} in {elapsed:.1f}s ({_format_size(int(speed))}/s)"
                )
                total_ok += 1
                time.sleep(0.12)
            except Exception as exc:
                print(f"    FAILED: {exc}")
                total_fail += 1
                if local_path.exists():
                    try:
                        local_path.unlink()
                    except:
                        pass

    print()
    print(f"小文件下载完成: {total_ok} 成功, {total_fail} 失败")

    if skipped_large:
        print(f"\n跳过的大文件 ({len(skipped_large)}):")
        for s, r, d, desc in skipped_large:
            print(f"  {desc}: {r}")


if __name__ == "__main__":
    main()
