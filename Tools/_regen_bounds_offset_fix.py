#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""临时脚本: 仅重新生成受偏移 bug 影响的 3 个图层的 bounds JSON。

修复内容: export_overlay_assets.py 中 export_clcd / export_era5_dwaa / export_era5_wdaa
原本使用 xy(offset="ll")/xy(offset="ur") 计算窗口地理边界, 导致 bounds 向内偏移 1 个像素
(0.25 deg, 约 28km 南北 + 14km 东西). 现改用 src.window_bounds(win) 正确计算.

本脚本只调用这 3 个函数, 避免重新运行耗时的 GPCP/SMAP 时间序列导出.
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保能 import 同目录下的 export_overlay_assets 模块
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import export_overlay_assets as exp


def main() -> int:
    print("=" * 60)
    print("Regenerate bounds for offset-fix affected layers")
    print("=" * 60)

    exp._OUT_ROOT.mkdir(parents=True, exist_ok=True)

    tasks = [
        ("CLCD", exp.export_clcd),
        ("ERA5 DWAA", exp.export_era5_dwaa),
        ("ERA5 WDAA", exp.export_era5_wdaa),
    ]

    results = {}
    for name, func in tasks:
        try:
            func()
            results[name] = "OK"
        except Exception as e:
            print(f"\n  [FAIL] {name}: {e}")
            import traceback

            traceback.print_exc()
            results[name] = f"FAIL: {e}"

    print("\n" + "=" * 60)
    print("Summary:")
    for name, status in results.items():
        marker = "[OK]" if status == "OK" else "[FAIL]"
        print(f"  {marker} {name}: {status}")
    print("=" * 60)
    return 0 if all(v == "OK" for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
