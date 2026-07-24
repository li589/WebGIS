"""重命名 I:\\Geograph_DataSet 中所有中文目录为英文。

策略：
1. 同盘重命名只更新目录项，瞬间完成
2. 按深度从深到浅执行，避免路径冲突
3. 保留原数据完整结构
"""

from pathlib import Path

ROOT = Path(r"I:\Geograph_DataSet")

# 重命名映射: (相对路径, 新名称)
# 顺序无关，会按深度排序后执行
RENAME_PLAN = [
    # ── AdminBoundary ──
    ("AdminBoundary/全国", "China"),
    ("AdminBoundary/全球", "Global"),
    ("AdminBoundary/北京", "Beijing"),
    ("AdminBoundary/广州", "Guangzhou"),
    ("AdminBoundary/China/行政区", "Admin"),
    ("AdminBoundary/Global/世界地图 shp", "WorldMap_shp"),
    ("AdminBoundary/Beijing/省市区村", "ProvinceCityDistrictVillage"),
    # ── CO2 ──
    ("CO2/中层二氧化碳柱浓度", "MidLayerCO2Column"),
    # ── Hazards 顶层 ──
    ("Hazards/全国自然灾害统计数据", "ChinaDisasterStats"),
    (
        "Hazards/全球\u201c复合灾害\u201d数据集 (1980-2020年)",
        "GlobalCompoundDisaster_1980_2020",
    ),
    ("Hazards/干旱指数", "DroughtIndex"),
    ("Hazards/滑坡数据", "Landslide"),
    ("Hazards/火灾数据", "FireData"),
    # ── Hazards/GlobalCompoundDisaster 子目录 ──
    (
        "Hazards/GlobalCompoundDisaster_1980_2020/1989-2018全球重大洪水shp",
        "Flood_1989_2018_shp",
    ),
    ("Hazards/GlobalCompoundDisaster_1980_2020/台风Shp格式", "Typhoon_shp"),
    ("Hazards/GlobalCompoundDisaster_1980_2020/地震shp数据", "Earthquake_shp"),
    (
        "Hazards/GlobalCompoundDisaster_1980_2020/复合灾害shp数据",
        "CompoundDisaster_shp",
    ),
    ("Hazards/GlobalCompoundDisaster_1980_2020/导出", "Exported"),
    # ── Hazards/Landslide 子目录 ──
    (
        "Hazards/Landslide/1915-2021年全球滑坡点及滑坡区域数据",
        "GlobalLandslide_1915_2021",
    ),
    ("Hazards/Landslide/CNDD-0119 中国自然灾害影响及损失", "CNDD_ChinaDisasterLoss"),
    (
        "Hazards/Landslide/中国大陆显著滑坡地震数据集（2000-2023）",
        "ChinaMainlandLandslideEarthquake_2000_2023",
    ),
    ("Hazards/Landslide/全国地质灾害shp", "ChinaGeoHazard_shp"),
    (
        "Hazards/Landslide/全球紧急事件数据库（1900-2025.2）",
        "GlobalEmergencyDB_1900_2025",
    ),
    ("Hazards/Landslide/复合灾害shp数据", "CompoundDisaster_shp"),
    # ── Soil_Ecological_Data ──
    ("Soil_Ecological_Data/武汉大学1985-2023CLCD", "WHU_CLCD_1985_2023"),
    # ── Station ──
    ("Station/全国观测站降雨数据", "China_Station_Rainfall"),
    ("Station/近20年全球数据", "Global_20yr"),
    ("Station/China_Station_Rainfall/_数据说明", "DataDescription"),
    ("Station/China_Station_Rainfall/广州", "Guangzhou"),
    # ── Transport ──
    ("Transport/出租车通行路号数据", "Taxi_RoadNumber"),
    # ── Weather ──
    ("Weather/温度", "Temperature"),
    ("Weather/降水", "Precipitation"),
    ("Weather/Precipitation/中国数据", "ChinaData"),
]


def main() -> None:
    # 按深度从深到浅排序（先重命名深层，再重命名浅层）
    plan_with_depth = []
    for rel_path, new_name in RENAME_PLAN:
        depth = rel_path.count("/")
        plan_with_depth.append((depth, rel_path, new_name))
    plan_with_depth.sort(key=lambda x: -x[0])  # 深度大的先执行

    print(f"重命名计划: {len(plan_with_depth)} 个目录")
    print(
        f"按深度从深到浅执行（深度 {plan_with_depth[0][0]} → {plan_with_depth[-1][0]}）"
    )
    print()

    succeeded = 0
    skipped = 0
    failed = 0

    for depth, rel_path, new_name in plan_with_depth:
        src = ROOT / rel_path
        dst = src.parent / new_name

        if not src.exists():
            print(f"  SKIP (not exists): {rel_path}")
            skipped += 1
            continue

        if dst.exists():
            print(f"  SKIP (target exists): {rel_path} -> {new_name}")
            skipped += 1
            continue

        try:
            src.rename(dst)
            print(f"  OK: {rel_path} -> {new_name}")
            succeeded += 1
        except Exception as e:
            print(f"  FAILED: {rel_path} -> {new_name}: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"完成: {succeeded} 成功, {skipped} 跳过, {failed} 失败")
    print("=" * 60)


if __name__ == "__main__":
    main()
