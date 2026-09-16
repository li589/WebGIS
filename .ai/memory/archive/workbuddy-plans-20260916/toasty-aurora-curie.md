# CGDA SpatiaLite (mod_spatialite) 升级计划

## 目标与范围

为现有 SQLite 元数据层引入 SpatiaLite 空间扩展能力，作为从"纯 SQLite 元数据"过渡到"服务端空间 SQL"的隔离数据平面（不迁 Postgres、不动高风险区 state DB）。

**本轮交付**：
1. **地基（实施）**：跨平台 mod_spatialite 加载器 + 所有池化连接加载（优雅降级）+ 配置项 + 验证脚本。
2. **overlay 迁移（实施）**：磁盘 `bounds.json` → 独立 `spatial.sqlite` 的 `overlays(geom)` 表 + R*Tree + 服务端视口相交端点 + 双读回退。
3. **AOI/station 表（仅设计）**：schema + 迁移路径写入文档，本轮不实现。

**用户决策（已确认）**：
- 安装来源：gaia-gis 预编译包进 `Env/Python312/Extras/spatialite/`（主），OSGeo4W 自动探测（Win 备选），Linux 用 `apt install libsqlite3-mod-spatialite`；**必须跨 Win/Linux 兼容**（本地 Win + CI/Docker Ubuntu）。
- 加载作用域：**所有池化连接都加载**，但扩展缺失时优雅降级——state/metadata DB（workflow/api_keys/gee_credentials，AGENTS.md 高风险区）绝不能因加载失败而打不开。
- 不下放热路径：`point_in_tile_half_open`、`tile_bbox_wgs84`、rasterio reproject 保留纯 Python（DB 往返是回归）。

**本轮默认延后（非阻塞）**：
- `OverlaySpec` 暂无 minzoom/maxzoom 字段 → 导入时写 NULL，下轮给 OverlaySpec 加字段。
- 前端不本轮切换 `/overlays/intersect`；本轮只交付后端端点，前端下轮接入。
- mod_spatialite 依赖 DLL（GEOS/PROJ/RT-Topo/freexl/iconv）整套解压到 `Extras/spatialite/`，靠 PATH prepend 让 LoadLibrary 用同源依赖（不混用 rasterio.libs 的 GEOS）。

---

## 架构总览

```
现有 9 个 repository (state/metadata)  ──┐
                                         ├── _sqlite_pool._create_connection() L60 后注入
                                         │   spatialite_loader.load_into(conn)  ← 幂等/降级/不抛
bypass 直连: task_store / workflow_timer ┘

新建 spatial.sqlite (独立文件, 可删除回滚)
  └─ SpatialRepository → overlays(geom POLYGON 4326) + idx_overlays_geom (R*Tree)
       ↑ 一次性导入            ↓ query_intersects (ST_Intersects + BuildMBR)
  Tools/import_overlay_bounds_to_spatialite.py
       ↑ 源: overlay_registry + IMPORTS_DIR/<id>/bounds.json

layer_router.py → GET /overlays/intersect  (spatialite 优先, bounds.json 回退)
```

关键区分：`load_into(conn)`（仅启用空间 SQL 函数，对所有连接调）≠ `init_spatial_metadata(conn)`（填充 spatial_ref_sys 元数据表，**只对 spatial.sqlite 调一次**，绝不复用到 state DB）。

---

## 阶段 1：地基 — 加载器 + 池接线 + 配置

### 1.1 新建 `Code/backend/app/services/spatialite_loader.py`

跨平台加载器，核心 API：

- `_resolve_extension_path() -> Path | None`：搜索顺序
  1. env `BACKEND_SPATIALITE_PATH`（文件或目录）
  2. Windows: `Env/Python312/Extras/spatialite/mod_spatialite.dll` → `%OSGEO4W_ROOT%\bin\mod_spatialite.dll`
  3. Linux: `/usr/lib/x86_64-linux-gnu/mod_spatialite.so` → `/usr/lib/mod_spatialite.so` → 裸名 `mod_spatialite.so` 让 dlopen 走默认路径
- `_ensure_path_prepend(ext_dir)`：Windows 上把 ext_dir prepend 到 `os.environ["PATH"]`（一次性，保证 mod_spatialite 用同源 GEOS/PROJ，不被 rasterio.libs 的版本劫持）。
- `load_into(conn) -> bool`：`enable_load_extension(True)` → `load_extension(path)` → `enable_load_extension(False)`（立即关防滥用）；幂等（`conn._spatialite_loaded` 标记）；`sqlite3.OperationalError`/任何异常仅 `logger.warning` 返回 False，**永不抛**。
- `init_spatial_metadata(conn) -> bool`：`SELECT InitSpatialMetaData(1)`，吞 "already initialized"。
- `_probe() -> _ProbeResult(available, path, reason)`：缓存探测。先用 `:memory:` 探 stdlib 是否支持 `enable_load_extension`（python.org 3.12 Win 默认开），再解析路径。
- `is_available()` / `_enabled()`（读 `settings.spatialite_enabled`，懒导入避循环依赖，默认 True）。

### 1.2 改 `Code/backend/app/services/_sqlite_pool.py`（主注入点，已核实）

L60 `PRAGMA busy_timeout` 之后、L61 `return conn` 之前插入：
```python
conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
# SpatiaLite 扩展加载（统一/幂等/降级/不抛；失败仅 warn，不阻断 state DB）
try:
    from app.services import spatialite_loader
    spatialite_loader.load_into(conn)
except Exception:
    logger.warning("spatialite_loader.load_into failed for %s", self.db_path, exc_info=True)
return conn
```
覆盖全部 9 个 repository（每个 repo `__init__` 里 `SQLiteConnectionPool(self.db_path)`）。

### 1.3 改两处 bypass 直连（同样调 `load_into`，统一语义）

- `Code/backend/app/services/task_store.py` L137-141 `_connect()`：PRAGMA 之后加 `load_into`。
- `Code/backend/app/services/workflow_timer_service.py` L310 `PRAGMA busy_timeout=30000` 之后、`_initialize_schema()` 之前加 `load_into`。

> 推荐两个 bypass 也加载：用户决策"所有连接加载"，且 `load_into` 零风险；task_store 短连接加载开销可忽略（task 操作非高频）。

### 1.4 改 `Code/backend/app/core/config.py`（frozen dataclass 加字段，纯增量）

L463 `node_stubs_visible` 之后追加：
```python
spatialite_enabled: bool = (os.getenv("BACKEND_SPATIALITE_ENABLED", "true").lower() == "true")
spatialite_path: str = os.getenv("BACKEND_SPATIALITE_PATH", "")
spatialite_db_path: str = os.getenv("BACKEND_SPATIALITE_DB_PATH",
                                     str(BACKEND_ROOT / ".data" / "spatial.sqlite"))
```

### 1.5 改 `Code/backend/.env.example`（末尾追加 3 键 + 平台注释）

```dotenv
# ---- SpatiaLite (mod_spatialite) ----
BACKEND_SPATIALITE_ENABLED=true
# BACKEND_SPATIALITE_PATH=
# Windows 默认探测 Env/Python312/Extras/spatialite/mod_spatialite.dll，其次 %OSGEO4W_ROOT%\bin\
# Linux   默认探测 /usr/lib/x86_64-linux-gnu/mod_spatialite.so (apt: libsqlite3-mod-spatialite)
BACKEND_SPATIALITE_DB_PATH=
```

---

## 阶段 2：空间 schema — overlays(geom) + AOI 设计

### 2.1 新建 `Code/backend/app/services/spatial_repository.py`

`SpatialRepository.__init__` → `SQLiteConnectionPool(spatialite_db_path)` + `_initialize_schema()`。

bootstrap 顺序（精确 SQL，幂等）：
```sql
SELECT InitSpatialMetaData(1);                                    -- 仅新库，吞 already
CREATE TABLE IF NOT EXISTS overlays (
    layer_id TEXT PRIMARY KEY, source TEXT NOT NULL, name TEXT,
    type TEXT, minzoom INTEGER, maxzoom INTEGER, updated_at TEXT NOT NULL);
SELECT AddGeometryColumn('overlays','geom',4326,'POLYGON','XY');  -- 幂等，已存在抛 already
SELECT CreateSpatialIndex('overlays','geom');                     -- 建 idx_overlays_geom (R*Tree)
```

方法：
- `upsert_overlay_bounds(layer_id, source, name, type_, minzoom, maxzoom, w, s, e, n)`：先调 `geo_math.overlay_safe_wgs84_bounds` 处理日界线，构造 WKT `POLYGON((w s,e s,e n,w n,w s))`，`GeomFromText(?,4326)` + `ON CONFLICT(layer_id) DO UPDATE`。
- `query_intersects(w,s,e,n, zoom=None) -> list[dict]`：`ST_Intersects(geom, BuildMBR(?,?,?, ?,4326))` + 可选 zoom 范围过滤；扩展不可用或 geom 列缺失时返回 `[]`（触发上层回退）。

### 2.2 AOI / station 表（DESIGN ONLY，本轮不实现）

```sql
CREATE TABLE aoi (id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT,
                  source TEXT, props_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL);
SELECT AddGeometryColumn('aoi','geom',4326,'MULTIPOLYGON','XY');
SELECT CreateSpatialIndex('aoi','geom');

CREATE TABLE stations (id TEXT PRIMARY KEY, code TEXT, name TEXT NOT NULL, props_json TEXT);
SELECT AddGeometryColumn('stations','geom',4326,'POINT','XY');
SELECT CreateSpatialIndex('stations','geom');
```
迁移路径（设计）：AOI 从 `BACKEND_MAP_AOI_PRESETS`（JSON）启动 upsert；stations 从 CSV/GeoJSON 用 `GeomFromText('POINT(lng lat)',4326)` 导入。

---

## 阶段 3：overlay bounds.json → overlays(geom) 迁移

### 3.1 新建 `Tools/import_overlay_bounds_to_spatialite.py`

一次性导入：遍历 `overlay_registry._REGISTRY`（内置层）+ `IMPORTS_DIR/<imported-*>`（导入层），读各层 `bounds.json` 的 `bounds=[w,s,e,n]`，调 `SpatialRepository.upsert_overlay_bounds`。日界线由 `overlay_safe_wgs84_bounds` 统一处理。

### 3.2 改 `Code/backend/app/api/routers/layer_router.py`（已核实 L221-224）

L224 `/overlays` 之后追加端点（顶部需加 `import json`）：
```python
@router.get("/overlays/intersect", tags=["overlay"])
def get_overlays_in_viewport(
    west: float = Query(..., ge=-180, le=360),   # 容许 >180（跨日界线 unwrap）
    south: float = Query(..., ge=-90, le=90),
    east: float = Query(..., ge=-180, le=360),
    north: float = Query(..., ge=-90, le=90),
    zoom: int | None = Query(default=None, ge=0, le=24),
) -> dict[str, Any]:
    """视口相交 overlay 查询。spatialite 优先，bounds.json 回退。"""
    repo = SpatialRepository()
    hits = repo.query_intersects(west, south, east, north, zoom=zoom)
    if hits:
        return {"layer_ids": [h["layer_id"] for h in hits], "source": "spatialite"}
    # 回退：扫所有 overlay 的 bounds.json 做 AABB 相交
    matched = []
    for lid in list_overlay_ids():
        spec = get_overlay_spec(lid)
        ...读 spec.resolve_bounds() → overlay_safe_wgs84_bounds → AABB 相交...
    return {"layer_ids": matched, "source": "fallback_bounds_json"}
```

### 3.3 双读回退契约 + 移除时机

- spatialite 表空 / 扩展不可用 → `query_intersects` 返回 `[]` → 端点走 `fallback_bounds_json`。
- 移除时机：导入脚本在所有环境跑过 + CI 覆盖相交查询 + 一个迭代周期无 `fallback_bounds_json` 生产日志后，删回退分支（接口签名不变）。

---

## 阶段 4：测试 + CI

### 4.1 新建 `Test/backend/test_spatialite_loader.py`
- `test_load_into_graceful_when_missing`：monkeypatch `_probe` 返回 unavailable → `load_into` 返回 False 不抛。
- `test_load_into_re_disables_extension`：加载后再 `load_extension` 应被拒（已 re-disable）。
- `test_load_into_is_idempotent`：二次调用返回 True。
- `test_platform_path_resolution`：env 覆盖 / Win gaia-gis / OSGeo4W / Linux apt 路径解析。
- 扩展缺失时全部 `pytest.skip`，不阻断本地 Windows。

### 4.2 新建 `Test/backend/test_spatial_overlay_repository.py`
- `test_schema_bootstrap`：`PRAGMA table_info(overlays)` 含 `geom`；`idx_overlays_geom` 表存在。
- `test_insert_and_intersect`：插入两条不重叠 bbox，视口查命中正确一条。
- `test_antimeridian_polygon`：east>180（unwrap）跨日界线命中。
- `test_zoom_range_filter`：zoom 在 min/max 内命中，超出不命中。
- `test_fallback_when_unavailable`：`BACKEND_SPATIALITE_ENABLED=false` → `query_intersects` 返回 `[]`。

### 4.3 改 `Test/backend/conftest.py` L49 后追加
```python
if not os.environ.get("BACKEND_SPATIALITE_DB_PATH", "").strip():
    os.environ["BACKEND_SPATIALITE_DB_PATH"] = str(_PROJECT_TMP / "spatial_test.sqlite")
```

### 4.4 改 `.github/workflows/ci.yml` L76（Install unrar step 之后）追加 step
```yaml
- name: Install mod_spatialite (for spatial overlay tests)
  run: sudo apt-get update && sudo apt-get install -y libsqlite3-mod-spatialite
```

### 4.5 新建 `Tools/verify_spatialite.py`
打印 `_probe()` 结果 + `spatialite_version()` / `geos_version()` / `proj_version()`，Win 缺失时给出 gaia-gis 下载指引。

---

## 阶段 5：Rollout / Rollback / 风险

**灰度顺序**：放 mod_spatialite bundle 到 `Env/Python312/Extras/spatialite/` → `verify_spatialite.py` 确认版本 → 跑导入脚本 → 跑两个新测试 → 启动后端请求 `/overlays/intersect` 确认 `source: "spatialite"`。

**Rollback**：`BACKEND_SPATIALITE_ENABLED=false` → 所有连接跳过加载 → `/overlays/intersect` 自动回退 bounds.json；`Code/backend/.data/spatial.sqlite` 独立文件可直接删除。无需 schema 回滚。

**风险登记**：
| 风险 | 缓解 |
|---|---|
| Win DLL hell（mod_spatialite 的 GEOS/PROJ 与 rasterio.libs 版本不匹配） | PATH prepend 把 mod_spatialite 同目录置顶，用同源依赖；verify 脚本打印版本对比 |
| `_sqlite3.pyd` 未开 loadable extensions | `_probe()` 先 `:memory:` 探测；不支持则全降级 |
| 高风险区 state DB 被 `InitSpatialMetaData` 污染 | `load_into`（仅启用函数）对所有连接调；`init_spatial_metadata` 只对 spatial.sqlite 调，绝不复用 |
| 跨日界线视口漏命中 | 约定前端传 e>180（unwrap），与 `overlay_safe_wgs84_bounds` 一致；docstring 文档化 |
| 并发写 spatial.sqlite | overlay bounds 写入低频（仅导入/刷新），与 workflow_state 高频写不在同一文件，无新争用 |

---

## 文件变更清单

**新建（6）**：
- `Code/backend/app/services/spatialite_loader.py` — 跨平台加载器
- `Code/backend/app/services/spatial_repository.py` — overlays(geom) 表 + upsert + 相交查询
- `Tools/import_overlay_bounds_to_spatialite.py` — 一次性导入脚本
- `Tools/verify_spatialite.py` — 本地验证脚本
- `Test/backend/test_spatialite_loader.py` — 加载器单测
- `Test/backend/test_spatial_overlay_repository.py` — overlay 空间仓库单测

**修改（7）**：
- `Code/backend/app/services/_sqlite_pool.py` — L60 后插入 `load_into`（主注入点，已核实）
- `Code/backend/app/services/task_store.py` — L137-141 `_connect()` 加 `load_into`
- `Code/backend/app/services/workflow_timer_service.py` — L310 后加 `load_into`
- `Code/backend/app/core/config.py` — L463 后加 3 个 Settings 字段
- `Code/backend/.env.example` — 末尾加 3 个 `BACKEND_SPATIALITE_*` 键
- `Code/backend/app/api/routers/layer_router.py` — L224 后加 `/overlays/intersect` 端点 + 顶部 `import json`
- `.github/workflows/ci.yml` — L76 后加 `apt install libsqlite3-mod-spatialite` step
- `Test/backend/conftest.py` — L49 后加 spatial DB tmp 隔离

**不动（明确）**：`geo_math.py`（复用 `overlay_safe_wgs84_bounds`）、`field_mapping.py`（热路径）、`data_io/services/vector.py`（本轮不动矢量空间过滤）、`requirements.txt`（mod_spatialite 是二进制扩展非 PyPI 包）、现有 9 个 repository 的 `__init__`（pool 注入统一，repo 层无感知）。

---

## 执行检查表（按序）

- [ ] Win: 下载 gaia-gis `libspatialite-X.X.X-win-amd64.7z`，整套解压到 `Env/Python312/Extras/spatialite/`
- [ ] 新建 `spatialite_loader.py` + `spatial_repository.py`
- [ ] 改 `_sqlite_pool.py` L60 + `task_store.py` + `workflow_timer_service.py` 注入 `load_into`
- [ ] 改 `config.py` + `.env.example` 加 3 字段
- [ ] 跑 `Tools/verify_spatialite.py` 确认 spatialite/geos/proj 版本输出
- [ ] 新建 `import_overlay_bounds_to_spatialite.py` 并跑一次导入
- [ ] 改 `layer_router.py` 加 `/overlays/intersect` 端点
- [ ] 新建两个测试文件 + 改 `conftest.py`
- [ ] 本地 `Env/Python312/python.exe -m pytest Test/backend/test_spatialite_loader.py Test/backend/test_spatial_overlay_repository.py -q`
- [ ] 改 `ci.yml` 加 apt step；CI 全绿
- [ ] 启动后端，`GET /overlays/intersect?west=100&south=20&east=110&north=30` 确认 `source: "spatialite"`
- [ ] 文档：在 `.ai/docs/` 记录 AOI/station schema 设计（本轮仅设计）

## 验证命令

```bash
# 后端（仓库根，绕 safe-delete shim）
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= \
  Env/Python312/python.exe -m pytest Test/backend/test_spatialite_loader.py Test/backend/test_spatial_overlay_repository.py -p no:cacheprovider --basetemp="Test/.pytest-be"

# 本地 SpatiaLite 探测
Env/Python312/python.exe Tools/verify_spatialite.py

# 一次性导入
Env/Python312/python.exe Tools/import_overlay_bounds_to_spatialite.py
```
