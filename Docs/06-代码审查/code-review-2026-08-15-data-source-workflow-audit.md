# 数据源管理与工作流深度审计报告

> 日期：2026-08-15 ｜ 审计模式：staff-engineer-mode（primary=`data-pipeline-reliability`，执行期 `testing-and-quality-gates`）
> 范围：数据源管理系统 ↔ 工作流系统连接、特殊数据底层支持组件（压缩/特殊格式/多版本适配/跨平台）、数据模块节点适配独立性
> 计划：`.trae/documents/2026-08-15-data-source-workflow-deep-audit.md`（Phase A→E）

## 1. 摘要

审计确认「数据源 → 图层 → 工作流 → 数据节点 → 结果回传」主链路在修复后**端到端通畅**。发现并修复 2 个 P0 阻断（FY 数据链路断裂、日期范围失效）、6 个 P1 缺口（压缩格式、跨平台探测、模板契约、凭证解析、缓存失效、硬编码），P2 项按「文档化/保持现状」决策处理并全部留痕。

## 2. P0 阻断修复（实测复现 → 修复 → 回归守卫）

| # | 问题 | 修复 | 回归守卫 |
|---|------|------|---------|
| P0-1 | 3/4 FY 系统种子编译失败：节点用旧式 type（`remote_fetch`、`module/fy_download`、`module/fy_preprocess`），注册表规范为 `download/*`，编译器对未知 type 抛错；无任何测试覆盖 | ① 3 个种子 JSON 改规范 type；② 后端 `_NODE_TYPE_ALIASES`（`node_template_registry.py`）+ 前端 `NODE_TYPE_ALIASES`（`litegraph-setup.ts`）补 3 条别名（历史画布兼容兜底） | `Test/backend/test_system_seeds_compile.py`：全部系统种子编译冒烟（GEE 引擎种子走运行时契约测试）+ `test_fy_seeds_use_registered_types` 禁止旧式 type 回潮 |
| P0-2 | `fy_download` 日期范围失效：只下载 `start_date` 单日，`end_date` 不参与循环 | 新增 `_iter_date_range`（含端点、≤366 天校验），NSMC/NAS 逐日取数、逐日源回退（auto 模式单日失败切源不放弃整天），manifest 汇总 | `Test/algorithms/test_fy_download.py`：单日/多日/auto 回退/越界拒绝等 10 用例 |

**E3 联调烟测（实测）**：服务层 `list_definitions()` 加载 54 个定义，4 个 FY 种子（`fy_tb_local_read` / `fy_tb_nas_read` / `fy_tb_nsmc_online` / `fy_tb_online_read`）全部在列；`fy_tb_online_read` 干跑提交经 `test_system_seed_runtime_engine_contract` 验证引擎请求注入正确。

## 3. P1 缺口修复

### B1+B3 特殊数据底层支持（压缩格式 × 跨平台）

`app/data_io/services/archive_safe.py` 扩展：

| 格式 | 实现 | 跨平台 |
|------|------|--------|
| `.zip` | `zipfile`（原有） | 纯 Python |
| `.tar` / `.tar.gz` / `.tgz` / `.tar.bz2` / `.tbz2` / `.tar.xz` / `.txz` | `tarfile`（`r:*` 透明解压） | 纯 Python |
| `.gz`（单文件） | `gzip` | 纯 Python |
| `.rar` | 控制台 UnRAR（7z CLI 回退） | vendor `win-x64/UnRAR.exe` → 系统 PATH `unrar`（探测须打印 `UNRAR`+`Usage`） |
| `.7z` | 7-Zip CLI | `_find_7z`：vendor → Windows `Program Files\7-Zip` / Linux `/usr/bin/7z`、`7za`、`7zz` → PATH；GUI（`7zFM`/`7zG`）排除 |

统一安全校验（全格式一致）：路径穿越、符号/硬链接拒绝、压缩炸弹（成员数 × 解压体积 × 压缩比）、MZ/SFX 拒绝、危险扩展名拒绝。`Test/backend/test_archive_safe.py` 扩至 40+ 用例。

### B2 Linux RAR 策略（决策留痕）

不在仓库提交 linux-x64 unrar 二进制（license/体积）；Linux 生产 `apt install unrar`（非 unrar-free）或 `p7zip-full` 回退。见 `Code/backend/vendor/unrar/README.md`。

### C1 ssh_sync 模板 ↔ 实现契约对齐

- `server_type` options 动态注入「远程与存储」profile id（`ssh`/`sftp`/`filebrowser` 且 enabled），`allow_custom: true`；模板契约测试锁定 options 前三 `["hpc","win11","nas"]`。
- 删除幽灵参数 `max_depth`（`sync_dataset` 无实现）；`file_filter` 支持字符串（`.mat,.h5`）与列表。
- `download/fy_download` 的 `config` 端口差异（绑定 `request:datasource_selection`）在模板描述文档化，保持现状。

### C2 门户凭证解析收敛

- 新增共享 `_resolve_portal_entry`（`modules/download_nodes.py`）：内联 `portal_credentials` 优先 → `portal_credentials_resolve` 经 `config_service.get_portal_credentials_runtime` 懒加载；`fy_download` NSMC 与 `nsidc_smap_download` Earthdata 均收敛至该入口，NSIDC→Earthdata 回退语义保留。
- `open_data_presets` 双真源：`portal_catalog.py` 为真源，模块内 fallback 显式标注「仅本地裸跑兜底，须与真源一致」。

### C3 动态 options 缓存失效审计

失效链实测确认：`upsert/delete/toggle_remote_storage_profile`、`upsert/delete_portal` → `_invalidate_profile_derived_caches` → `invalidate_portal_options_cache`（+ remote_auth_resolver / filebrowser token 缓存）。新增 3 个失效测试（`test_portal_catalog.py`）：门户 upsert/delete、存储 profile upsert 后 `presets` / `ssh_servers` 动态选项即时可见。修复测试隔离缺陷：基线断言改打桩后快照（真实仓储存在的 `seahpc` profile 不再泄入）。

### D 跨平台硬编码与多版本适配

| 项 | 处理 |
|----|------|
| `data_preprocessor.py` 默认根 `I:/Geograph_DataSet` | 改为显式参数 > `BACKEND_DATA_ROOT` 环境变量 > 空字符串（空根安全退化，landcover 查找返回 None） |
| `nsidc_download.DEFAULT_OUTPUT_DIR`（`I:\...`） | `BACKEND_DATA_ROOT` 注入优先，未设时保持原值（行为兼容）；工作流路径本就不依赖（节点落 `ctx.workspace`） |
| `remote_sync.ServerConfig` 工厂默认值 | docstring 标注「实验室兜底/示例，生产走 profile 注入」；`for_nas` 外部 DDNS 默认值（`*.personaltunnel.dpdns.org`，可被第三方注册）对齐后端安全决策改为空 + 显式校验 |
| `fy_download` NAS 兜底 URI / NSMC base URL | 标注可覆盖路径（`datasource_selection.nas_uri` / presets 真源） |
| `gldas_nc4_to_mat` 网格文件 | `ancillary_mat` 为必填参数，无硬编码（docstring 说明 IGBP_9km_12.mat 语义） |
| SMAP 版本策略 | `.ai/skills/multi-source-data-ingestion.md` 新增「SMAP 版本策略」节：v6 固定 + 参数可覆盖；R18290 revision 不解析为**已知接受行为**（同日不同 revision 覆盖），触发升级条件与下游耦合（按日期匹配输入）已写明 |
| CRS 前后端差异 | `Docs/03-规范协议/CRS检测前后端差异说明.md`：后端权威（rasterio/GeoJSON/bounds 三层 + 6933/3857/GK/UTM/XY 颠倒），前端仅 bounds 预览且无生产调用方；不强制对齐 |

## 4. P2 项处置（保持现状 + 留痕）

| # | 项 | 处置 |
|---|----|------|
| P2-1 | 双轨数据源注册表（`remote_sources` vs `available_datasets`） | 保持现状：各自接线（远程别名→下载节点；本地数据集→readiness/路径解析），不强合并 |
| P2-2 | `@lru_cache` 失效耦合 | C3 已补写路径失效测试；resolver 注释自述双通道绑定风险留痕 |
| P2-3 | 新旧 remote browser 权限模型不一致 | 未改（超出本次范围）；建议后续统一到 profile 驱动 + read 权限模型 |
| P2-4 | 两套 AESGCM 加密实现 | 未收敛（风险低，密钥同源）；后续统一到单一加密工具模块 |
| P2-8 | `/config/remote-storage/{id}/browse` 与 `/search` demo 可浏览目录结构 | 未改；机构交付前建议按 `delivery-checklist.md` 复核 |
| 遗留 | `_store_path_manifest` ×4 重复实现 | 计划明确延后（非阻断）；收敛时注意四处签名差异 |

## 5. 数据模块节点适配独立性结论

- **独立性成立**：各下载/数据节点（`remote_fetch`、`fy_download`、`fy_preprocess`、`ssh_sync`、`http_open_data`、`nsidc_smap_download`、`gldas_nc4_to_mat`）经统一契约（`datasource_selection` + `algorithm_params` 合并解析、`NodeExecutionContext` 注入 workspace/logger）独立执行，互不依赖运行顺序之外的隐式状态。
- **连接通畅性**：设置页（门户/远程存储 profile）→ `config_service` 写操作 → 缓存失效 → 节点模板动态 options → 画布节点参数，全链路经 C2/C3 修复后闭环；FY 在线链路（NSMC HTTP + NAS SMB 回退）P0 修复后可编译、可提交、可执行。

## 6. 验证矩阵（E 全量）

| 检查 | 命令 | 结果 |
|------|------|------|
| 后端全量回归 | `pytest Test/backend/`（仓库根，`ENVIRONMENT=test` + `REDIS_URL`，关 safe-delete shim） | **1129 passed, 2 skipped**；10 failed + 12 errors 全部为**既有问题**（归属见 §6.1，与本审计改动零关联，两轮复跑结果一致） |
| 算法包回归 | `pytest Test/algorithms/` | **411 passed**, 28 subtests passed（25.7s） |
| 前端单元 | `npm run test` | **699 passed**（127 files, 7.6s） |
| 前端 lint | `npm run lint` | **0 errors**（2 处既有 `no-explicit-any` warning，非本次引入） |
| 前端 build | `npm run build` | 成功（vue-tsc + vite；rolldown eval 提示为依赖既有行为） |
| OpenAPI 契约 | `npm run check:openapi` | **OK**（关键路径 + 操作指纹一致） |
| 图层目录 | `npm run check:catalog` | **OK**（55 items + 7 categories 与后端种子同步） |
| 全仓质量门 | `pre-commit run --all-files` | 通过（ruff / ruff-format / mypy / eslint / prettier / 通用钩子） |
| E3 联调烟测 | 服务层 `list_definitions()` + 种子提交契约 | 54 定义加载，4 FY 种子在列，引擎请求注入正确 |

### 6.1 后端失败归属（决定性验证：HEAD 干净 worktree 复跑）

对全部失败文件在 **HEAD 干净检出**（`git worktree`，无本审计任何改动）复跑，结果一致 → 均为既有问题，**非本审计引入的回归**：

| 失败桶 | 数量 | 根因（证据） |
|--------|------|-------------|
| `test_weather_coverage.py` + `test_weather_engine_settings_phase_a.py` ERROR | 12 | 测试引用 `weather_router.get_redis_client`，该属性在 commit `10b7eb1`（RBAC v2）中已移除——**HEAD 上的测试漂移**，CI 亦会红；建议按当前 router 接口重写桩 |
| `test_frontend_call_simulation.py` | 3 | 匿名调用 fail-closed 401（HEAD 干净树同样失败）；与本地 `.env` 无关，属 HEAD 既有测试/鉴权语义漂移 |
| `test_import_raster_crs.py` | 2 | `ValueError` 无法 JSON 序列化 / 422≠400（HEAD 干净树同样失败），既有异常处理器行为漂移 |
| `test_dataset_registry.py` | 5 | 主树失败（`assert 45 == 1`）但 **HEAD worktree 复制同款 `.env` 后通过** → 失败源于本地运行栈共享状态（`.data` 注册库已含 45 条真实数据集），测试未隔离注册库 DB；CI 无此状态不受影响 |

> 归属方法：改动集（13 个修改 + 4 个新增文件）与失败模块零交集；两轮全量复跑结果完全一致（确定性）；HEAD worktree 复跑隔离变量闭环。

## 7. 残留风险与建议

1. **`Test/` 下历史 pytest basetemp 目录锁死**（`.pytest-be*` 多个 junction 挂载点拒绝访问）：不影响 git 与运行（已 ignore），建议重启后清理或忽略。
2. **P2-3 / P2-4 / P2-8**（browser 权限模型、双加密实现、demo 目录浏览）建议列入下一次安全专项。
3. **SMAP revision**：出现 v5/v6 共存或 reprocessing 需求时按 `.ai/skills/multi-source-data-ingestion.md` 的触发条件实施。
4. **前端 `crs-detector.ts`**：确认为无生产调用方的预览工具；若未来 UI 需要预判，以导入接口返回为准（见 `Docs/03-规范协议/CRS检测前后端差异说明.md`）。
