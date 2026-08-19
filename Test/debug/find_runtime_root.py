"""搜索可能的运行时根目录（含近期日志/状态库文件）。

用法: python find_runtime_root.py
"""
import datetime
import os
from pathlib import Path

BASES = [
    Path(r"I:\Geograph_DataSet\_runtime"),
    Path(r"I:\test\_runtime"),
    Path(r"D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend\.data\_runtime"),
    Path(r"D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\.data\_runtime"),
]
now = datetime.datetime.now()
for base in BASES:
    if not base.exists():
        print(f"== {base} (missing)")
        continue
    print(f"== {base} ==")
    try:
        for p in sorted(base.rglob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)[:6]:
            mt = datetime.datetime.fromtimestamp(p.stat().st_mtime)
            print(f"  {mt:%m-%d %H:%M} {p.stat().st_size:>10} {p.relative_to(base)}")
        for p in base.glob("workflow_state/*.sqlite3*"):
            mt = datetime.datetime.fromtimestamp(p.stat().st_mtime)
            print(f"  {mt:%m-%d %H:%M} {p.stat().st_size:>10} {p.relative_to(base)}")
    except OSError as e:
        print("  err:", e)
