#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""快速验证 _reproject_ease_to_wgs84() 的中国裁剪修复。

只运行 4 个 EASE-Grid 图层导出：
  - forest_ratio (含 .mat Transform 元数据)
  - soil_ddca (无元数据，使用硬编码 9008.0552m)
  - omega (smap_avg, 无元数据)
  - omega_fy (fy_avg, 无元数据)

验证点：
  1. 重投影后 bounds 接近中国区域 (73,15,137,59)，不再是全球 (-180,-84,180,85)
  2. PNG 尺寸显著减小（从 ~3600×1800 降至 ~640×440）
  3. 像素尺寸修正后定位准确
"""

from __future__ import annotations

import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent))

from export_overlay_assets import (
    export_forest_ratio,
    export_soil_ddca,
    export_omega,
    export_omega_fy,
    _CHINA_BBOX,
)


def main() -> int:
    print("=" * 70)
    print("EASE-Grid Reproject Fix Verification")
    print(f"  Expected China bounds: {_CHINA_BBOX}")
    print("=" * 70)

    tasks = [
        ("Forest Ratio", export_forest_ratio),
        ("Soil DDCA", export_soil_ddca),
        ("Omega (smap_avg)", export_omega),
        ("Omega FY (fy_avg)", export_omega_fy),
    ]

    results = {}
    for name, func in tasks:
        print()
        try:
            func()
            results[name] = "OK"
        except Exception as e:
            import traceback

            traceback.print_exc()
            results[name] = f"FAIL: {e}"

    print("\n" + "=" * 70)
    print("Summary:")
    for name, status in results.items():
        marker = "[OK]" if status == "OK" else "[FAIL]"
        print(f"  {marker} {name}: {status}")
    print("=" * 70)

    # 验证 PNG 文件大小
    print("\n=== PNG File Sizes (中国裁剪后应显著变小) ===")
    out_root = Path(
        r"I:\Geograph_DataSet\ProjectOutput\2023-01_Omega_Inversion\_overlays"
    )
    for subdir, fname in [
        ("forest_ratio", "forest_ratio_overlay.png"),
        ("soil_ddca", "soil_ddca_overlay.png"),
        ("omega", "omega_avg_overlay.png"),
        ("omega_fy", "omega_fy_overlay.png"),
    ]:
        p = out_root / subdir / fname
        if p.exists():
            size_kb = p.stat().st_size / 1024
            print(f"  {subdir}/{fname}: {size_kb:.1f} KB")
        else:
            print(f"  {subdir}/{fname}: [MISSING]")

    # 验证 bounds JSON
    print("\n=== Bounds JSON (应在中国区域 73,15,137,59 附近) ===")
    import json

    for subdir, fname in [
        ("forest_ratio", "forest_ratio_overlay_bounds.json"),
        ("soil_ddca", "soil_ddca_overlay_bounds.json"),
        ("omega", "omega_avg_overlay_bounds.json"),
        ("omega_fy", "omega_fy_overlay_bounds.json"),
    ]:
        p = out_root / subdir / fname
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            b = data.get("bounds", [])
            print(f"  {subdir}: bounds={b}")
        else:
            print(f"  {subdir}: [MISSING]")

    return 0 if all(v == "OK" for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
