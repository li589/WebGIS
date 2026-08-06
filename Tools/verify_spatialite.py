#!/usr/bin/env python
"""打印 mod_spatialite 探测结果 + GEOS/PROJ/spatialite 版本。

用法（仓库根）：
    Env/Python312/python.exe Tools/verify_spatialite.py

Windows 缺失时会给出 gaia-gis 预编译包下载与放置指引。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "Code" / "backend"))
sys.path.insert(0, str(_REPO / "Code"))

from app.services import spatialite_loader  # noqa: E402


def main() -> int:
    spatialite_loader.reset_probe_cache()
    probe = spatialite_loader._probe()
    print(f"available : {probe.available}")
    print(f"path      : {probe.path}")
    print(f"reason    : {probe.reason or '(ok)'}")
    print(f"platform  : {sys.platform}")
    if not probe.available:
        print()
        if sys.platform == "win32":
            print("Windows 安装指引（三选一，放置后重跑本脚本确认版本输出）：")
            print("  1. OSGeo4W 安装器装 spatialite 包，设 OSGEO4W_ROOT 环境变量；")
            print("     loader 会自动探测 %OSGEO4W_ROOT%\\bin\\mod_spatialite.dll")
            print("  2. 从 gaia-gis 官网 (https://www.gaia-gis.it/) 下载 libspatialite 预编译包，")
            print("     整套解压到 Env/Python312/Extras/spatialite/（含 mod_spatialite.dll + 同源")
            print("     GEOS/PROJ/RT-Topo/freexl/iconv，靠 add_dll_directory 隔离，勿与 rasterio.libs 混用）")
            print("  3. 或设 BACKEND_SPATIALITE_PATH 指向任意位置的 mod_spatialite.dll")
        else:
            print("Linux 安装指引：")
            print("  sudo apt-get install -y libsqlite3-mod-spatialite")
        return 1
    conn = sqlite3.connect(":memory:")
    if not spatialite_loader.load_into(conn):
        print("load_into 失败（详见上方日志）")
        return 1
    for sql in (
        "SELECT spatialite_version()",
        "SELECT geos_version()",
        "SELECT proj_version()",
        "SELECT rttopo_version()",
    ):
        try:
            r = conn.execute(sql).fetchone()
            print(f"{sql:32s} -> {r[0] if r else None}")
        except Exception as e:  # noqa: BLE001
            print(f"{sql:32s} -> ERROR: {e}")
    print("\nOK: SpatiaLite 可用。可继续跑 import_overlay_bounds_to_spatialite.py 与测试。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
