# CGDA 数据源管理与工作流深度审计与修复计划

> 日期：2026-08-15 ｜ 模式：Plan（审计 + 修复） ｜ 语言：中文
> 依据：staff-engineer-mode 路由（primary=`data-pipeline-reliability`，secondary=`data-contracts`），3 个 Explore 子代理 + 主会话实测验证。

## 1. 摘要

对 CGDA 的**数据源管理系统**、**工作流系统**、**特殊数据底层支持组件**进行深度审计，目标：确认「数据源 → 图层 → 工作流 → 数据节点 → 结果回传」全链路通畅、功能无异常。

审计已**实测确认 2 个 P0 阻断**（FY 在线/NAS 数据链路断裂、fy_download 日期范围失效），并发现多个 P1 缺口（压缩格式不全、跨平台隐患、重复实现、硬编码）。本计划按 Phase A（P0 修复）→ B（特殊数据支持补齐）→ C（数据源↔工作流连接加固）→ D（跨平台/版本适配）→ E（全量验证）推进。

## 2. 现状分析（已实测确认）

### 2.1 P0 阻断（实测复现）

| # | 问题 | 证据 |
|---|------|------|
| P0-1 | **FY 在线/NAS 种子编译失败（3/4）**。`fy_tb_nas_read.json` 用 `remote_fetch`、`module/fy_preprocess`；`fy_tb_online_read.json` 用 `module/fy_download`、`module/fy_preprocess`；`fy_tb_nsmc_online.json` 用 `module/fy_preprocess`。注册表规范 type 为 `download/remote_fetch`、`download/fy_download`、`download/fy_preprocess`。后端 `_NODE_TYPE_ALIASES`（`node_template_registry.py:3594`）与前端 `NODE_TYPE_ALIASES`（`litegraph-setup.ts:114`）均只有 `algorithm/omega_avg_daily` 一条别名。编译器 `compile_litegraph_to_workflow_definition`（`workflow_graph_compiler.py:167-169`）对未知类型抛 `WorkflowGraphCompileError`。**实测**：3/4 FY 种子编译抛 `未知节点类型`。**无任何测试覆盖 FY 种子编译**（`Test/backend` 无 `fy_tb` 引用）。 | 影响近期重点「FY 在线获取」端到端断裂 |
| P0-2 | **`fy_download` 日期范围失效**。`fy_download.py:219` `date_path = start_date.replace("-", ".")` 仅用 start_date 下载单日；`end_date` 只写入 manifest extra（:256），未参与下载循环。`_download_from_nsmc` / `_fetch_from_nas` 均为单 date_path 签名。 | 用户选日期范围时只下载首日 |

### 2.2 P1 缺口（探索确认）

| # | 问题 | 位置 |
|---|------|------|
| P1-1 | 压缩格式仅支持 zip/rar；**tar/tar.gz/tgz/gz/7z 不支持**（科研数据常见 .tar.gz 分发） | `Code/backend/app/data_io/services/archive_safe.py` |
| P1-2 | `vendor/unrar/linux-x64/unrar` **缺失**（仅 win-x64/UnRAR.exe）；Linux 解压 RAR 依赖 `apt install unrar` 或 7-Zip | `Code/backend/vendor/unrar/` |
| P1-3 | `_find_7z()` **硬编码 Windows 路径**（`C:\Program Files\7-Zip\7z.exe`），Linux 仅 PATH | `archive_safe.py` |
| P1-4 | **重复实现**：`_store_path_manifest` ×4（`data_access_nodes.py`/`download_nodes.py`/`fy_download.py`/`graph_io.py`）；门户凭证解析 ×3（`download_nodes._resolve_earthdata_portal_userpass`/`data_access_nodes._resolve_portal_headers`/`fy_download._download_from_nsmc`），NSIDC→Earthdata 回退仅一处；open_data_presets 双真源（`data_access_nodes._DEFAULT_OPEN_DATA_PRESETS` vs `data_cache_service.DEFAULT_OPEN_DATA_PRESETS`） | 算法包 modules/ |
| P1-5 | **硬编码**：`fy_download.py:141` NAS 兜底 URI（`smb://nas/Chenhaojun/fy/...?cred=nas_profile`）、NSMC 缺省 base URL；`gldas_nc4_to_mat` 硬编码 `IGBP_9km_12.mat`；`remote_sync.py` HPC 默认 host/username/key 内嵌 | 算法包 |
| P1-6 | `ssh_sync` 模板 `server_type` options 只列 `["hpc","win11","nas"]`，但实现把非遗留值当「远程与存储」profile id 解析——**模板与实现能力不一致** | `node_template_registry.py` vs `download_nodes.py:244` |
| P1-7 | `download/fy_download` 输入端口 kind=`config`（绑定 `request:datasource_selection`），其它下载节点用 `data:source`——端口体系不一致 | `node_template_registry.py` |

### 2.3 P2 关注（探索确认，非阻断）

| # | 问题 | 位置 |
|---|------|------|
| P2-1 | 数据源双轨：`remote_sources`（远程别名）与 `available_datasets`（本地数据集）两套注册表；overlay 源数据解析走 `overlay_registry.resolve_source_path` 未接入 dataset registry | `remote_source_registry.py` / `dataset_registry_service.py` / `overlay_registry.py` |
| P2-2 | 缓存失效耦合：`_resolve_provider_dataset_path` 的 `@lru_cache`（`workflow_request_resolver.py`）依赖写操作调 `invalidate_template_cache`；`remote_auth_resolver._repo()` 的 `@lru_cache` 同理 | `workflow_request_resolver.py` / `remote_auth_resolver.py` |
| P2-3 | 旧式 `remote_browser_router.py`（hpc/win11/nas 内置，`require_write_access`）与新式 `remote_access/browser.py`（profile 驱动，仅 read）并存，权限模型不一致 | 后端 services/ |
| P2-4 | 两套 AESGCM 加密实现：`portal_credentials._encrypt_blob` vs `remote_storage_credentials_repository` | 后端 services/ |
| P2-5 | 跨平台硬编码：`data_preprocessor.py` 默认 `data_root="I:/Geograph_DataSet"`；前端 `crs-detector.ts` 与后端 `_crs_detector.py` 不一致（无 6933/3857/UTM 推断） | 算法包 / 前端 crs/ |
| P2-6 | SMAP revision（`R18290`）未解析，无 v5/v6 显式版本共存机制（NSIDC 下载固定 v6） | `ingest/smap.py` / `ingest/nsidc_download.py` |
| P2-7 | `_data_access_requests` 与画布 `data/source` 节点双通道绑定，存在重复/覆盖风险（resolver 注释自述） | `workflow_request_resolver.py` |
| P2-8 | `/config/remote-storage/{id}/browse` 与 `/search` 仅需 read 权限，demo 角色可浏览远程目录结构 | `config_routes.py` |

## 3. 建议变更

### Phase A — P0 阻断修复（FY 数据链路）【必做】

**A1. 修复 FY 种子节点类型**（3 个文件 + 别名防御 + 测试）
- 改种子文件为规范 type（与 GLDAS 种子风格一致）：
  - `Code/backend/workflow_seeds/system/fy_tb_nas_read.json`：节点 1 `remote_fetch` → `download/remote_fetch`；节点 2 `module/fy_preprocess` → `download/fy_preprocess`
  - `Code/backend/workflow_seeds/system/fy_tb_online_read.json`：节点 1 `module/fy_download` → `download/fy_download`；节点 2 `module/fy_preprocess` → `download/fy_preprocess`
  - `Code/backend/workflow_seeds/system/fy_tb_nsmc_online.json`：节点 3 `module/fy_preprocess` → `download/fy_preprocess`
- 后端 `_NODE_TYPE_ALIASES`（`node_template_registry.py:3594`）补防御别名：`remote_fetch`→`download/remote_fetch`、`module/fy_preprocess`→`download/fy_preprocess`、`module/fy_download`→`download/fy_download`（兼容历史画布）
- 前端 `NODE_TYPE_ALIASES`（`litegraph-setup.ts:114`）同步补同 3 条别名
- 新增测试 `Test/backend/test_system_seeds_compile.py`：遍历 `workflow_seeds/system/*.json` 全部编译冒烟（替代/扩展 `test_stub_v1_seeds_compile.py` 的 14 个白名单）

**A2. 修复 `fy_download` 日期范围**（1 个文件 + 测试）
- `Code/algorithms/providers/Python/modules/fy_download.py`：将单 `date_path` 改为日期范围循环——`start_date`~`end_date`（含）逐日生成 `date_path`，对 NSMC/NAS 逐日取数并汇总结果目录；`end_date` 为空时退化为单日（保持现状行为）。manifest extra 保留完整 start/end
- 新增测试 `Test/algorithms/test_fy_download.py`：单日（end 空）、多日范围、auto 回退路径

### Phase B — 特殊数据底层支持组件补齐【必做】

**B1. `archive_safe.py` 扩展 tar/tar.gz/tgz/gz/7z**
- `Code/backend/app/data_io/services/archive_safe.py`：
  - tar/tar.gz/tgz/gz：用标准库 `tarfile` 实现 `safe_extract_tar()`，复用现有 `_sanitize_member_name` / `_assert_under_dest` / 炸弹防护（成员数、解压体积、单成员体积、压缩比、危险扩展名、符号链接拒绝）
  - 7z：`safe_extract_7z()` 走外部 CLI，跨平台探测（见 B3）
  - `safe_extract_archive()` 分派表补充新后缀
- 扩展 `Test/backend/test_archive_safe.py`：tar.gz 正常解压、路径穿越拒绝、炸弹防护、危险成员拒绝

**B2. Linux unrar 依赖策略**
- 决策：**不在仓库提交 linux-x64/unrar 二进制**（license/体积）。`_find_unrar_tool()` 已支持系统 PATH `unrar`，确认 Linux 回退链（PATH unrar → 7-Zip）可用即可
- 更新 `Code/backend/vendor/unrar/README.md`：明确 Linux 需 `apt install unrar` 或 7-Zip，标注 win-x64 已落地、linux-x64 未随仓库分发

**B3. `_find_7z()` 跨平台探测**
- `archive_safe.py`：`_find_7z()` 改为 PATH 搜索（`shutil.which("7z"/"7za"/"7zz")`）+ 常见安装路径（Windows `C:\Program Files\7-Zip\7z.exe` 等；Linux `/usr/bin/7z` 等）

### Phase C — 数据源↔工作流连接与节点适配加固【必做】

**C1. 节点模板/实现契约对齐**
- `node_template_registry.py`：`ssh_sync` 模板 `server_type` options 补充 profile 说明（非遗留值即「远程与存储」profile id），使模板与 `download_nodes.py:244` 实现一致；`download/fy_download` 的 `config` 端口差异在模板描述中文档化（fy_download 依赖 `request:datasource_selection` 绑定，保持现状）

**C2. 门户凭证解析收敛（低风险重构）**
- 统一三处门户凭证懒加载（`download_nodes._resolve_earthdata_portal_userpass` / `data_access_nodes._resolve_portal_headers` / `fy_download._download_from_nsmc`）到单一 helper（复用 `portal_credentials_resolve`），保留 NSIDC→Earthdata 回退语义
- open_data_presets 双真源：明确 `data_cache_service.DEFAULT_OPEN_DATA_PRESETS` 为真源，`data_access_nodes._DEFAULT_OPEN_DATA_PRESETS` 仅作兜底并在注释标注

**C3. 缓存失效审计**
- 核对 `_resolve_provider_dataset_path` 的 `@lru_cache` 所有失效调用点：dataset upsert/delete/rescan 均须触发 `invalidate_template_cache`；`remote_auth_resolver._repo()` 在 profile 增删改后失效。补测试覆盖「改数据集后路径解析不陈旧」

### Phase D — 跨平台与多版本适配【按需】

**D1. 硬编码文档化（不做激进删除）**
- `data_preprocessor.py` 默认 `data_root="I:/Geograph_DataSet"` → 改为环境/配置注入优先、默认空字符串，避免 Linux 误用
- `remote_sync.py` HPC 默认 host/user/key、`fy_download.py` NAS 兜底 URI / NSMC base URL、`gldas_nc4_to_mat` 的 `IGBP_9km_12.mat`：确认均可经配置覆盖，在模块 docstring 标注「默认值/兜底，可经配置覆盖」

**D2. SMAP 版本策略文档化**
- `ingest/smap.py` / `ingest/nsidc_download.py`：确认 NSIDC 下载固定 v6 的现状，在 `.ai/skills/multi-source-data-ingestion.md` 记录版本策略（当前不新增 R18290 解析，除非出现实际多版本需求）

**D3. 前端 CRS 一致性**
- 确认导入主链路走后端 `_crs_detector.py`（后端权威），前端 `crs-detector.ts` 仅展示。在 `Docs/03-规范协议/` 记录前后端检测差异，不强制对齐（避免范围膨胀）

### Phase E — 全量验证【必做】

- E1：`Test/backend/test_system_seeds_compile.py`（全量种子编译冒烟）+ `Test/algorithms/test_fy_download.py` + `test_archive_safe.py` 扩展 + `test_node_template_ports.py` 扩展（FY 节点端口）
- E2：全量回归（仓库根，关 safe-delete shim 约定）：
  - 后端：`CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend -p no:cacheprovider --basetemp="Test/.pytest-be"`
  - 算法：`Env/Python312/python.exe -m pytest Test/algorithms`
  - 前端：`cd Code/frontend && npm run test && npm run lint && npm run build`
  - 契约/目录：`npm run check:openapi`、`npm run check:catalog`
  - `pre-commit run --all-files`
- E3：联调烟测（若环境允许）：`launch.py restart backend` 后 `GET /workflow-definitions` 确认 FY 种子可加载；提交 `fy_tb_online_read` 种子 dry-validate 通过

## 4. 假设与决策

| 决策 | 说明 |
|------|------|
| FY 种子改规范 type + 别名防御双管齐下 | 种子是真源应用规范 type；别名仅作历史画布兼容兜底，避免破坏已有用户画布 |
| 不在仓库提交 linux unrar 二进制 | license/体积权衡；README + 探测链确认即可 |
| tar/gz 用标准库 tarfile，7z 走外部 CLI | tarfile 纯 Python 跨平台零依赖；7z 无纯 Python 可靠实现 |
| 硬编码以文档化为主，不做激进删除 | 多为默认值/兜底，删除有破坏风险；仅 `data_preprocessor.py` 默认根改为配置注入 |
| 门户凭证解析收敛为低风险重构 | 语义一致性（NSIDC→Earthdata 回退）值得统一；`_store_path_manifest` ×4 收敛延后（非阻断） |
| 双轨数据源注册表（remote_sources vs available_datasets）保持现状 | 已各自接线（远程别名供下载节点、本地数据集供 readiness/路径解析），本次仅补文档，不强行合并 |
| 前端 CRS 与后端不一致不强制对齐 | 导入主链路后端权威；避免范围膨胀 |

## 5. 验证步骤（验收标准）

1. `test_system_seeds_compile.py` 全量种子编译通过（含 4 个 FY 种子）
2. `test_fy_download.py` 通过（单日/多日/回退）
3. `test_archive_safe.py` tar.gz/7z 用例通过
4. 后端 pytest + 算法 pytest + 前端 vitest/lint/build + check:openapi + check:catalog + pre-commit 全绿
5. 联调：FY 种子 dry-validate 通过，`GET /workflow-definitions` 无「未定义节点」
6. 审计报告输出至 `Docs/06-代码审查/`（含 P0/P1/P2 清单、修复记录、残留项）
