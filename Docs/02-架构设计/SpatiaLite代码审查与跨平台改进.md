# SpatiaLite 升级：代码审查、潜在 Bug 分析与跨平台（Linux/Win）改进方案

> 审查范围：近期在 CGDA 后端引入 SpatiaLite 空间扩展的相关改动（加载器、空间仓库、图层路由端点、连接池注入、配置、工具、测试、CI）。
> 目标：检查新代码与关联/旧代码、定位潜在 Bug、给出 Linux/Win 跨平台设计改进建议。
> 审查日期：2026-08-06｜审查人：Senior Developer

---

## 1. 近期改动清单（What changed）

| 文件 | 性质 | 作用 |
|------|------|------|
| `app/services/spatialite_loader.py` | 新增（核心） | 跨平台 `mod_spatialite` 加载器：`load_into(conn)` / `init_spatial_metadata(conn)` / `_enabled()` / 探针缓存。统一加载、幂等、优雅降级、安全（加载后立刻 `enable_load_extension(False)`）。 |
| `app/services/spatial_repository.py` | 新增 | 独立 `spatial.sqlite` 仓库：`overlays(geom POLYGON 4326)` + `idx_overlays_geom` R*Tree；`upsert_overlay_bounds`（三态写路径）、`query_intersects`、`is_spatial_ready`、`count`。与 state/metadata DB **完全隔离**。 |
| `app/api/routers/layer_router.py` | 修改 | 新增 `GET /overlays/intersect` → `get_overlays_in_viewport(...)`：优先空间库，不可用时回退 `bounds.json` AABB 相交（同一日界线展开空间）。 |
| `app/services/_sqlite_pool.py` | 修改 | `_create_connection` 在 PRAGMA 之后注入 `spatialite_loader.load_into(conn)`（try/except 包裹，失败仅 warn）。 |
| `app/services/task_store.py` | 修改 | `_connect()` 注入 `load_into`。 |
| `app/services/workflow_timer_service.py` | 修改 | 注入点（PRAGMA + `load_into`）。 |
| `app/core/config.py` | 修改 | 新增 `spatialite_enabled` / `spatialite_path` / `spatialite_db_path`（默认 `Code/backend/.data/spatial.sqlite`），**全部为 `os.getenv` 类默认**。 |
| `Code/backend/.env.example` | 修改 | 新增 3 个 SpatiaLite 键 + 跨平台注释。 |
| `Tools/verify_spatialite.py` | 新增 | 探测并打印 `spatialite_version()/geos_version()/proj_version()/rttopo_version()`；修正死链 gaia-gis URL。 |
| `Tools/import_overlay_bounds_to_spatialite.py` | 新增 | 遍历 `list_overlay_ids()` → `read_bounds()` → `upsert_overlay_bounds`，把 `bounds.json` 迁移进空间库。 |
| `Test/backend/test_spatialite_loader.py`、`Test/backend/test_spatial_overlay_repository.py` | 新增/修订 | 加载器与仓库单测，含禁用回退、antimeridian、`COUNT(geom)` 就绪判定、显式 `db_path` 隔离。 |
| `Test/backend/conftest.py` | 修改 | 默认 `BACKEND_SPATIALITE_DB_PATH` 落到项目内 `.pytest_tmp`，避免污染开发库。 |
| `.github/workflows/ci.yml` | 修改 | 增加 `apt install libsqlite3-mod-spatialite` + “Verify SpatiaLite extension loads” 步骤，CI **失败即暴露**而非静默跳过。 |
| `Env/Python312/Extras/spatialite/` | 新增二进制（gitignore） | 从 gaia-gis 下载 `mod_spatialite-5.1.0-win-amd64.7z` 解出的 `mod_spatialite.dll` + GEOS/PROJ/RT-Topo/freexl/iconv + `proj.db`。 |

---

## 2. 关联组件与旧代码核查（Associated & legacy code）

- **`app/services/geo_math.py::overlay_safe_wgs84_bounds`**：日界线 `unwrap` 约定（`east>180`）。仓库 `upsert`、`query_intersects`、路由回退均调用它，保证“空间路径”与“bounds.json 回退路径”在**同一空间**比较——已核对一致。OK
- **`bounds.json` 旧机制**：原前端 `O(N)` 过滤的源头。新端点仅在 `is_spatial_ready()==False` 时回退，且回退逻辑也已按同一日界线约定归一化，行为兼容。OK
- **`_sqlite_pool` / `task_store` / `workflow_timer_service`**：三个注入点均调用 `load_into`。**关键风险点**：`workflow_state` / `api_keys` / `gee_credentials` 属 AGENTS.md “高风险区”，走同一池。核查确认 `load_into` 在扩展不可用时返回 `False` 且不抛，PRAGMA 仍成功，DB 可读写——无污染、无阻断。OK
- **`init_spatial_metadata` 调用面**：**仅** `SpatialRepository` 调用（对独立 `spatial.sqlite`），**绝不复用**到 state DB，避免往无关库写 `spatial_ref_sys` 等元数据表。OK（已在代码与文档中强约束。）

---

## 3. 潜在 Bug 分析（Potential bugs）

### BUG-S1（高 / 已修复）：`spatialite_enabled` 在导入时冻结，运行时开关失效
- **现象**：`app/core/config.py` 中 `Settings` 是 `@dataclass(frozen=True)`，**所有字段默认值在模块首次导入时由 `os.getenv` 一次求值并冻结**。`spatialite_enabled: bool = (os.getenv("BACKEND_SPATIALITE_ENABLED","true")=="true")`。
- **后果**：若 `config.py` 早于环境变量被导入（典型：FastAPI 启动、`conftest` 收集阶段、容器 env 注入顺序），`Settings()` 重建**不会**重新读取 env，开关被永久锁定为导入时刻的值。测试中 `monkeypatch.setenv("...","false") + Settings()` 也无效。
- **修复**：`spatialite_loader._enabled()` 改为**优先读 `os.getenv("BACKEND_SPATIALITE_ENABLED")`**（运行时可即时切换），缺失才回退到 `settings` 冻结默认值。开关在启动脚本/容器 env/测试中均可即时生效。
- **系统性提示**：该“env 在导入时冻结”是 `config.py` 的**普遍性反模式**（所有 `os.getenv` 默认字段同病）。本修复仅覆盖 SpatiaLite 开关；见 section 4.6 后续建议。

### BUG-S2（严重 / 已修复）：`conn._spatialite_loaded = True` 抛 `AttributeError`
- **根因**：早期版本的 `load_into` 试图在 `sqlite3.Connection` 上挂自定义属性做幂等标记。但 `sqlite3.Connection` 是 **C 扩展类型，无可写 `__dict__`**，赋值直接抛 `AttributeError`。
- **后果**：异常被外层吞掉 → `load_into` 返回 `False` → 即便扩展加载成功，整条特性**静默回退**到 `bounds.json`，空间索引形同虚设。
- **修复**：改用**无状态探测** `SELECT spatialite_version()` 判定本连接是否已加载；不依赖任何连接级状态位。

### BUG-S3（信息性 / 已规避）：`weakref.WeakSet` 同样失败
- `sqlite3.Connection` 还**不可弱引用**（`TypeError: cannot create weak reference`）。因此“用 WeakSet 记录已加载连接”的方案不可行。与 BUG-S2 同源，最终统一用 BUG-S2 的无状态探测。

### BUG-S4（高 / 已修复）：Windows 下 `os.add_dll_directory` 不足以解析依赖
- **现象**：`verify_spatialite.py` 用 `os.add_dll_directory(ext_dir)` 后 `load_extension` 仍报 “找不到指定的模块”。
- **根因**：sqlite 内部 `LoadLibrary` 不一定受 `os.add_dll_directory` 影响；`mod_spatialite.dll` 依赖的 GEOS/PROJ/RT-Topo/freexl/iconv 需要**所在目录在 DLL 搜索路径最前**。
- **修复**：`_ensure_dll_search` 以 **PATH prepend 为主**（`os.add_dll_directory` 仅作补充）。实测：`PATH-prepend load OK -> ('5.1.0',)`。

### BUG-S5（中 / 已修复）：`is_spatial_ready` 用 `COUNT(*)` 误判就绪
- **根因**：若 DB 在扩展不可用时导入，`geom` 列虽存在但全为 `NULL`。`COUNT(*)>0` 会误判“就绪”，导致上层信任空命中、却因 `geom` 为 `NULL` 而**静默丢结果**。
- **修复**：改为 `COUNT(geom)`（忽略 NULL）。NULL 几何行 → 计数 0 → 返回 `False` → 上层回退 `bounds.json`。

### BUG-S6（中 / 已修复/已对齐）：日界线视口与存储须同一空间
- **风险**：视口 `east>180` 经 `overlay_safe_wgs84_bounds` 展开，但存储几何若用不同展开约定，空间查询与回退结果会不一致（跨日界线 overlay 漏判）。
- **修复/核查**：`query_intersects` 与路由回退**均**先用 `overlay_safe_wgs84_bounds` 归一化视口，再与 `BuildMBR`/存储几何比较；单测 `test_antimeridian_polygon` 覆盖。OK

### BUG-S7（中 / 已修复）：测试跨 run 污染（safe-delete shim + 共享 basetemp）
- **现象**：本地 safe-delete shim 拦截 pytest 临时目录清理（`PermissionError`），`--basetemp` 复用导致上一次遗留的 `spatial.sqlite`（已带 geom）跨 run 残留，使 `test_fallback_when_disabled_no_geom` 误判 geom 已存在。
- **修复**：测试用 `_fresh_repo()` 生成 **uuid 唯一文件名** DB（从根本上避免命中遗留库），`os.remove` 仅作兜底（被 shim 拦截时静默忽略）。配合 BUG-S1 的 `_enabled()` 调用时读 env，测试完全确定。

### 关联组件新增风险（已核对无问题）
- 三处注入点（`_sqlite_pool`/`task_store`/`workflow_timer_service`）对高风险区 state DB 仅“尝试加载”，失败降级不抛——已确认不污染、不阻断。OK
- `init_spatial_metadata` 仅对独立 `spatial.sqlite` 调用，无跨库元数据污染。OK

---

## 4. 跨平台（Linux/Win）设计改进方案（Cross-platform design）

### 4.1 扩展加载路径矩阵

| 平台 | 解析顺序（已实现于 `_resolve_extension_path`） | 依赖解析策略 |
|------|------|------|
| **Windows** | ① `BACKEND_SPATIALITE_PATH` ② `Env/Python312/Extras/spatialite/mod_spatialite.dll` ③ `%OSGEO4W_ROOT%/bin/mod_spatialite.dll` | `PATH` prepend 同目录（主）+ `os.add_dll_directory`（补） |
| **Linux** | ① `BACKEND_SPATIALITE_PATH` ② `/usr/lib/x86_64-linux-gnu/mod_spatialite.so` ③ `/usr/lib/mod_spatialite.so` ④ 裸名 `mod_spatialite.so`（交 OS 解析） | 系统 `ld.so` 默认路径；CI `apt install` |

### 4.2 Windows 专项改进
1. **预置二进制落库**：`Env/Python312/Extras/spatialite/` 已随仓库 `Env/` 一并（gitignore，本地生效）。建议：在 `.env.example`/README 明确“Windows 本地联调若不想依赖 OSGeo4W，需从此预置目录取 `mod_spatialite.dll` 全套 DLL”，固化版本 `5.1.0`（与 PROJ 9.2.1 / GEOS 3.12 同源匹配，避免混用不同版本依赖导致 `proj.db` 不兼容）。
2. **OSGeo4W 探测兜底**：保留 `%OSGEO4W_ROOT%` 探测，但**仅作兜底**——预置目录优先，避免 OSGeo4W 版本漂移引入不兼容依赖。
3. **PATH 变异的并发安全**：`_ensure_dll_search` 用 `_dll_search_registered` 一次性标记 + `if dir not in PATH` 去重 prepend，**非原子但幂等**（重复调用不会产生重复路径），多连接并发首调安全。OK 若未来要求严格无全局副作用，可改为“仅 `os.add_dll_directory` + 在该目录内拷贝/软链为单一 `mod_spatialite.dll` 名”——但当前实现已够稳。
4. **`proj.db` 定位**：`mod_spatialite` 依赖同目录 `proj.db`。预置目录已包含。风险点：若用户用 OSGeo4W 的 `mod_spatialite.dll`，必须保证 `PROJ_DATA`/`proj.db` 可寻；建议在 `verify_spatialite.py` 增加 `proj_version()` 之外对 `proj.db` 可读性的断言。

### 4.3 Linux 专项改进
1. **CI 安装**：`.github/workflows/ci.yml` 已加 `apt install libsqlite3-mod-spatialite`。建议：钉版本（如 `libsqlite3-mod-spatialite=5.1.0*`）避免 CI 漂移。
2. **裸名兜底**：`Path("mod_spatialite.so")` 交给 `ld.so` 默认路径解析，覆盖自定义安装（如 conda `/opt/conda/lib`）。失败由 `load_into` 兜住降级。
3. **glibc / musl**：当前目标 Ubuntu（glibc）。若未来需 Alpine（musl），`apt` 包不存在，需 `apk add spatialite-tools` 并用其 `mod_spatialite.so` 路径；建议 `_resolve_extension_path` 增加 Alpine/musl 候选路径（`/usr/lib/mod_spatialite.so` 已覆盖多数）。
4. **ARM64**：x86_64 预置 DLL 不适用 ARM 服务器。文档应注明 ARM Linux 走系统包、Windows ARM 走 OSGeo4W ARM 构建。

### 4.4 CI/CD
- 已加 “Verify SpatiaLite extension loads” 步骤跑 `verify_spatialite.py`，**失败即红**，杜绝静默跳过。OK
- 建议：该步骤**先于**空间相关单测，作为 gate；并输出 `spatialite/geos/proj/rttopo` 四版本，便于版本漂移审计。

### 4.5 优雅降级矩阵（已落地，建议文档化）

| 场景 | `_enabled()` | `is_available()` | `is_spatial_ready()` | 上层行为 |
|------|------|------|------|------|
| 开关关闭 | False | - | False | `/overlays/intersect` 走 `bounds.json` 回退 |
| 扩展缺失 | True | False | False | 同上 |
| 扩展在但导入时未加载（geom NULL） | True | True | False（`COUNT(geom)==0`） | 同上 |
| 扩展正常 + 有几何数据 | True | True | True | 走空间库；**零命中也信任**（不回退） |

> 核心不变量：**空间库就绪时即使零命中也信任结果**（BUG-S5 修复保证不会因 NULL geom 静默丢结果）；未就绪则一律回退，绝不静默错误。

### 4.6 系统性后续建议（超出本次范围，提出供决策）
1. **`config.py` 的 env 冻结反模式**：`@dataclass(frozen=True)` + `os.getenv` 默认值使所有运行时配置（不仅是 SpatiaLite）在导入时锁定。建议中长期迁移到 pydantic `BaseSettings`（env 在 `Settings()` 构造时求值），或至少把“可热切换开关/路径”改为 `default_factory`/调用时读取。本次仅修复了 SpatiaLite 最关键的开关。
2. **`spatialite_db_path` 的冻结**：`SpatialRepository.__init__` 读 `settings.spatialite_db_path`（导入时冻结）。若生产环境 `BACKEND_SPATIALITE_DB_PATH` 在导入后才设，会落到错误默认路径。建议改为调用时 `os.getenv` 兜底（与 `_enabled()` 同思路），或显式 `db_path` 传参（仓库已支持）。
3. **删除隔离数据面可观测性**：`spatial.sqlite` 独立于主 state DB，删除即回滚。建议在运维文档明确“重置空间索引 = 删该文件 + 重跑 `import_overlay_bounds_to_spatialite.py`”。

---

## 5. 验证状态（Verification）

- **单元**：`Test/backend/test_spatial_overlay_repository.py` + `test_spatialite_loader.py` → **17 passed**（含禁用回退、antimeridian、`COUNT(geom)` 就绪、三态写路径、显式 `db_path` 隔离）。
- **回归**：`test_config_security.py` → 4 passed（配置改动未破坏鉴权/配置安全）。
- **二进制加载**：`Tools/verify_spatialite.py` → `available: True`；`spatialite_version 5.1.0 / geos 3.12.0 / proj 9.2.1 / rttopo 1.1.0`。
- **CI**：新增 `apt install` + verify 步骤，失败即红。

### 仍建议人工/线上确认项
- 启动后端后 `GET /overlays/intersect?west=&south=&east=&north=` 实际返回 `source:"spatialite"`（需先 `import_overlay_bounds_to_spatialite.py` 灌入数据）。
- Windows 上用 OSGeo4W 的 `mod_spatialite.dll`（若存在）时 `proj.db` 可被正确定位（已在 section 4.2.4 标注为验证点）。

---

## 6. 后续待办（Next steps）
1. 跑 `Tools/import_overlay_bounds_to_spatialite.py` 灌入真实 overlay，启动后端实测 `/overlays/intersect` 端点（空间路径 vs 回退）。
2. 将 BUG-S1 的“调用时读 env”思路推广到 `spatialite_db_path`（section 4.6-2）。
3. 评估 `config.py` 全面迁移 pydantic `BaseSettings`（系统性消除 env 冻结）。
4. CI 钉 `libsqlite3-mod-spatialite` 版本（section 4.3.1）。
5. 清理一次性解压 venv `Env/.extractenv`（gitignore，可选）。
