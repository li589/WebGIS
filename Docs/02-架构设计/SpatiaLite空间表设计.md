# SpatiaLite 空间表设计

> 本轮（2026-08-05）落地了 `overlays(geom)` 表；`aoi` / `stations` 为**本轮仅设计**，待后续按需实现。
> 实现计划见 `C:\Users\likr\.workbuddy\plans\toasty-aurora-curie.md`。

## 背景

CGDA 后端 SQLite 元数据层通过 `mod_spatialite` 扩展获得服务端空间 SQL 能力，作为从「纯 SQLite
元数据」过渡到「服务端空间 SQL」的**隔离数据平面**（独立 `spatial.sqlite`，不迁 Postgres、不动
高风险区 state DB）。加载器见 `app/services/spatialite_loader.py`，仓库见
`app/services/spatial_repository.py`。

关键区分：
- `load_into(conn)` —— 仅启用空间 SQL 函数（ST_*/GeomFromText/BuildMBR...），对所有连接调。
- `init_spatial_metadata(conn)` —— 填充 `spatial_ref_sys` 等元数据表，**只对 spatial.sqlite 调一次**，
  绝不复用到 state DB。

## 1. overlays(geom) —— 已实现

承载 overlay 图层的 WGS84 边界多边形，用于服务端视口相交查询（替代前端 O(N) 浏览器侧过滤）。

```sql
SELECT InitSpatialMetaData(1);                                    -- 仅新库，吞 already
CREATE TABLE IF NOT EXISTS overlays (
    layer_id   TEXT PRIMARY KEY,
    source     TEXT NOT NULL,          -- 'builtin' | 'imported'
    name       TEXT,
    type       TEXT,                   -- 'static' | 'time-series'
    minzoom    INTEGER,                -- 本轮 OverlaySpec 无此字段，暂 NULL
    maxzoom    INTEGER,
    updated_at TEXT NOT NULL
);
SELECT AddGeometryColumn('overlays','geom',4326,'POLYGON','XY');   -- 幂等
SELECT CreateSpatialIndex('overlays','geom');                      -- 建 idx_overlays_geom (R*Tree)
```

- 写：`upsert_overlay_bounds` 先 `overlay_safe_wgs84_bounds` 处理日界线（east 可 >180，unwrap），
  构造 `POLYGON((w s,e s,e n,w n,w s))` 用 `GeomFromText(?, 4326)` + `ON CONFLICT DO UPDATE`。
- 查：`query_intersects(w,s,e,n, zoom=None)` = `ST_Intersects(geom, BuildMBR(?,?,?, ?,4326))`
  + 可选 `(? >= minzoom OR minzoom IS NULL) AND (? <= maxzoom OR maxzoom IS NULL)`，走 R*Tree 索引。
- 回退：扩展不可用 / geom 列缺失 / 表空 → 返回 `[]`，端点 `/overlays/intersect` 走 `bounds.json` 全扫描
  （`source: "fallback_bounds_json"`）。
- 导入：`Tools/import_overlay_bounds_to_spatialite.py` 一次性把 `list_overlay_ids()` 各层
  `read_bounds()["bounds"]` 导入。

## 2. aoi（多边形 AOI）—— 仅设计，未实现

机构自定义/导入的感兴趣区（行政区、流域、项目研究区等）。

```sql
CREATE TABLE aoi (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    category   TEXT,              -- 'preset' | 'imported' | 'project'
    source     TEXT,              -- 'env_map_aoi_presets' | 'shapefile' | 'drawn' | 'geojson'
    props_json TEXT NOT NULL DEFAULT '{}',   -- 面积、人口、备注等扩展属性
    updated_at TEXT NOT NULL
);
SELECT AddGeometryColumn('aoi','geom',4326,'MULTIPOLYGON','XY');
SELECT CreateSpatialIndex('aoi','geom');
```

迁移路径（设计）：
- 启动 upsert：`BACKEND_MAP_AOI_PRESETS`（JSON env）→ 启动时 upsert 到 `aoi`（source='env_map_aoi_presets'）。
- Shapefile 导入：`Tools/import_aoi.py` 用 pyshp 读 `.shp` → WKT → `GeomFromText(?, 4326)`（多部件用
  `MULTIPOLYGON`）；属性写 `props_json`。
- 前端绘制：`POST /aoi` 接收 GeoJSON Polygon → `GeomFromText` 入库（source='drawn'）。
- 查询：`ST_Intersects(geom, BuildMBR(...))` 视口过滤；`ST_Contains(geom, GeomFromText('POINT(...)',4326))`
  判点落入哪些 AOI。

## 3. stations（点要素：气象站/观测点）—— 仅设计，未实现

```sql
CREATE TABLE stations (
    id         TEXT PRIMARY KEY,
    code       TEXT,              -- 站点编号（如 CMA 站号）
    name       TEXT NOT NULL,
    props_json TEXT NOT NULL DEFAULT '{}',   -- 海拔、类型、归属等
    updated_at TEXT NOT NULL
);
SELECT AddGeometryColumn('stations','geom',4326,'POINT','XY');
SELECT CreateSpatialIndex('stations','geom');
```

迁移路径（设计）：
- CSV/GeoJSON 导入：`Tools/import_stations.py`，每行 `lng,lat` → `GeomFromText('POINT(lng lat)', 4326)`。
- 查询：视口内站点 `ST_Intersects(geom, BuildMBR(...))`；最近邻 `ORDER BY ST_Distance(geom,
  GeomFromText('POINT(...)',4326)) LIMIT k`。

## 设计约定（三类表共享）

- **SRID 统一 4326（WGS84）**：与 MapLibre/overlay/天气引擎约定一致；非 WGS84 数据入库前由
  `crs_transformer` 投影到 4326。
- **几何列用 `AddGeometryColumn`**：而非直接在 `CREATE TABLE` 写 BLOB 列，保证 SpatiaLite 元数据
  登记 + 类型校验 + 触发器联动。
- **空间索引必建 `CreateSpatialIndex`**：R*Tree 虚拟表 `idx_<table>_<col>`，否则全表扫。
- **日界线 unwrap 约定**：视口/几何 east 可 > 180（与 `overlay_safe_wgs84_bounds` 一致），
  `BuildMBR` 直接用 unwrap 值。
- **写入低频**：AOI/stations 写入仅在导入/编辑时发生，与 workflow_state 高频写不在同一文件，
  无新并发争用（WAL 单写锁）。
- **回退契约**：所有空间查询在扩展不可用时返回空集，调用方据此走内存/文件回退，绝不抛。
