#!/usr/bin/env python3
"""重组 I:\\Geograph_DataSet 目录：将中文目录重命名为英文。

策略：
  - 同盘重命名（Move-Item/Path.rename）是瞬间操作，不移动数据
  - 需要先删除空的英文目录（如 Station），再重命名中文目录
  - 保留已是英文的目录（DEM, Gosat, Soil_Ecological_Data）

重命名计划：
  行政区数据  → AdminBoundary  (先删空的 AdminBoundary)
  ISD-Lite   → Station         (先删空的 Station)
  二氧化碳数据 → CO2
  交通数据    → Transport
  灾害数据    → Hazards
  栅格气象数据 → Weather
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(r"I:\Geograph_DataSet")

# (旧目录名, 新目录名, 是否需要先删除空的新目录)
RENAME_PLAN = [
    ("行政区数据", "AdminBoundary", True),  # AdminBoundary 已创建为空目录
    ("ISD-Lite", "Station", True),  # Station 已创建为空目录
    ("二氧化碳数据", "CO2", False),
    ("交通数据", "Transport", False),
    ("灾害数据", "Hazards", False),
    ("栅格气象数据", "Weather", False),
]


def main() -> None:
    print(f"数据根目录: {ROOT}")
    print(f"重组计划: {len(RENAME_PLAN)} 个目录重命名")
    print()

    # 先展示当前目录列表
    print("当前目录:")
    for d in sorted(ROOT.iterdir()):
        if d.is_dir():
            try:
                count = sum(1 for _ in d.rglob("*") if _.is_file())
            except PermissionError:
                count = -1
            print(f"  {d.name:30s}  ({count} items)")
    print()

    success = 0
    skipped = 0
    failed = 0

    for old_name, new_name, need_delete_empty in RENAME_PLAN:
        old_path = ROOT / old_name
        new_path = ROOT / new_name

        print(f"[{old_name}] -> [{new_name}]")

        # 检查旧目录是否存在
        if not old_path.exists():
            print("  SKIP: 旧目录不存在")
            skipped += 1
            continue

        # 如果需要先删除空的新目录
        if need_delete_empty and new_path.exists():
            # 检查是否为空
            try:
                children = list(new_path.iterdir())
                if len(children) == 0:
                    new_path.rmdir()
                    print(f"  删除空目录: {new_name}")
                else:
                    print(f"  ERROR: 新目录非空（{len(children)} 项），跳过")
                    failed += 1
                    continue
            except Exception as exc:
                print(f"  ERROR 删除空目录: {exc}")
                failed += 1
                continue

        # 检查新目录是否已存在
        if new_path.exists():
            print("  SKIP: 新目录已存在")
            skipped += 1
            continue

        # 执行重命名（同盘操作，瞬间完成）
        try:
            old_path.rename(new_path)
            print("  OK: 重命名成功")
            success += 1
        except Exception as exc:
            print(f"  ERROR: {exc}")
            failed += 1

    print()
    print("=" * 50)
    print(f"重组完成: {success} 成功, {skipped} 跳过, {failed} 失败")
    print("=" * 50)

    # 展示重组后的目录列表
    print("\n重组后目录:")
    for d in sorted(ROOT.iterdir()):
        if d.is_dir():
            try:
                count = sum(1 for _ in d.rglob("*") if _.is_file())
            except PermissionError:
                count = -1
            print(f"  {d.name:30s}  ({count} items)")


if __name__ == "__main__":
    main()
