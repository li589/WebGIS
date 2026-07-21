#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase 2 runner: 仅运行新增的 VOD/SM/Omega 2025-12 时间序列导出函数。

绕过已存在的静态 PNG（external HDD 上偶发 PermissionError），
只生成 Phase 2 课题组 VOD/SM/Omega 产品族图层资产。

新增图层（Phase 2）：
  - export_vod_ts           → vod_ts/vod_ts_{tag}.png × 31 (2025-12-01 ~ 2025-12-31)
  - export_sm_dec2025_ts    → sm_ts/sm_ts_{tag}.png × 31
  - export_omega_2025_ts    → omega_2025_ts/omega_2025_ts_{tag}.png × 31

数据源：I:\\Geograph_DataSet\\Soil_Ecological_Data\\SmapSoil_VOD_SM\\YYYYMMDD.mat
       v7.3 HDF5，含 OMEGA / SM / VOD 三个变量，shape (1624, 3856) on EASE-Grid 9km
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

# 确保能 import 同目录下的 export_overlay_assets
sys.path.insert(0, str(Path(__file__).resolve().parent))

import export_overlay_assets as E


def main() -> int:
    print("=" * 60)
    print("Phase 2 — VOD/SM/Omega 2025-12 time series exports")
    print("=" * 60)

    E._OUT_ROOT.mkdir(parents=True, exist_ok=True)

    tasks = [
        ("VOD TS (2025-12, 31 days, magma)", E.export_vod_ts),
        ("SM Dec2025 TS (2025-12, 31 days, YlGnBu)", E.export_sm_dec2025_ts),
        ("Omega 2025 TS (2025-12, 31 days, plasma)", E.export_omega_2025_ts),
    ]

    results = {}
    for name, func in tasks:
        print(f"\n>>> {name}")
        try:
            func()
            results[name] = "OK"
        except Exception as e:
            print(f"\n  [FAIL] {name}: {e}")
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
