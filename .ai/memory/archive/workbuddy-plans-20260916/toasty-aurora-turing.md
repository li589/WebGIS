# CGDA 远程数据源数据集化改造 — 实现方案

## 目标与已确认决策

**问题**：「在线检索」与「可访问数据源」当前为文件级粒度（单 *.hdf 路径入库），应改为数据集（链接）级。

**已确认决策**（用户 2026-08-21）：
1. 检索 UI：纯数据集级展示（无文件预览下钻）
2. 访问控制：编辑器过滤 + 运行时后端硬校验（403）双层
3. 存量迁移：自动归并升级（路径推断数据集，失败 fallback 保留）
4. 管控范围：全部下载节点（http_open_data + fy/nsidc/gldas/cds/cdse/nomads 专用节点）

**核心语义**：站点「节点访问兼容」开关（全放行）OR 数据集白名单命中 → 放行（并集）；未配置任何授权的门户视为未管控 → 放行（向后兼容）。

**验收**：综合测试确保各源 × 目标数据集可下载（dry_run 矩阵，见 §7/阶段 6）。

---

## 0. 探索验证结论（关键文件+行号）

| 事实 | 位置 |
|---|---|
| remote_sources 表 schema（8 列，additive CREATE IF NOT EXISTS） | `Code/backend/app/services/remote_source_registry.py` L53-69 |
| 注册表 CRUD + 能力徽标 | 同上 L90-153 / L169-220 |
| 检索模板（CMR granules / CDSE OData / CDS collections） | `Code/backend/app/services/portal_catalog.py` L29-48 |
| search_portal 分发 + 三种 parser | 同上 L928-989、_parse_cmr_entry L832（granule 级）、_parse_cdse_entry L849（产品级）、_parse_cds_entry L873（collection 级） |
| 内置 19 门户（仅 nasa_cmr=cmr / esa_copernicus=cdse_odata / ecmwf_cds=cds 可检索；NSMC none） | 同上 L103-368 |
| 检索 API 路由 | `Code/backend/app/api/config_routes.py` L1041-1065 |
| remote-sources CRUD 路由 | 同上 L1138-1176 |
| 契约模型 | `Code/shared/contracts/config_contracts.py`（RemoteSourceEntry L413 / RemoteSourceUpsertRequest L430 / PortalSearchResponse L801） |
| 本地数据集实体范例（available_datasets 表、同库、_derive_dataset_id） | `Code/backend/app/services/dataset_registry_service.py` L53-75、L248-263 |
| http_open_data 节点模板（preset 固定 options=portal_id 列表） | `Code/backend/app/services/node_template_registry.py` L237-300 |
| 专用节点模板（fy L872 / nsidc L670 / gldas L706 / cds L368 / nomads L441 / cdse L536） | 同上 |
| http_open_data 执行（读 ctx.request.datasource_selection.open_data_presets） | `Code/algorithms/providers/Python/modules/data_access_nodes.py` HttpOpenDataModule L546-679（execute L573） |
| 专用节点参数合成 {**defaults, **params, **ap, **ds} | `Code/algorithms/providers/Python/modules/download_nodes.py` L283 等；`fy_download.py` L516 |
| 作业请求构建（注入 open_data_presets + portal_credentials_resolve 的位置） | `Code/backend/app/services/python_provider_request_builder.py` L131-149 |
| 提交链路 bridge（execute → build_job_request_payload → validate_job → submit） | `Code/backend/app/services/python_provider_bridge_service.py` L299-352 |
| 启动同步范例（迁移锚点） | `Code/backend/app/main.py` L84-95（sync_algorithm_datasets） |
| 前端：检索对话框（单文件 remote_path 落库） | `Code/frontend/src/components/settings/portals/PortalSearchDialog.vue` addAsSource L48-69 |
| 前端：数据源面板（整源注册 addDialog） | `Code/frontend/src/components/settings/data-source/RemoteDataSourcesPanel.vue` L113-156 |
| 前端：已注册表 | 同目录 `RegisteredRemoteSources.vue` |
| 前端：节点表单（presetOptions 动态来自门户目录） | `Code/frontend/src/components/workflow/node-forms/HttpOpenDataForm.vue` L73-105 |
| 前端：API + store | `Code/frontend/src/services/settings-api.ts` L681-764；`src/stores/settings.ts` L554-567 |
| OpenAPI 链 | `Code/backend/scripts/export_openapi.py` → `Code/frontend/openapi.json` → `npm run gen:types` → `src/types/api-contracts.ts`；`npm run check:openapi` 防漂移 |
| 测试位置/约定 | `Test/backend/test_remote_source_registry.py`、`test_portal_catalog.py`、`test_remote_sources.py`、`test_open_portal_data_access.py`、`test_dataset_registry.py`；根目录 `Env/Python312/python.exe -m pytest Test/backend`，需 REDIS_URL+ENVIRONMENT=test；vitest 在 Test/frontend |

## 1. 数据模型

### 1.1 新表 remote_dataset_grants（数据集白名单，同 research_data_settings.sqlite3，additive）

```sql
CREATE TABLE IF NOT EXISTS remote_dataset_grants (
    grant_id            TEXT PRIMARY KEY,   -- 别名 ID（用户命名，如 nasa-cmr-gldas-noah025）
    portal_id           TEXT NOT NULL,      -- 引用门户（portal_catalog 键）
    dataset_key         TEXT NOT NULL,      -- 数据集规范标识（见 §4.1 映射表）
    dataset_title       TEXT DEFAULT '',
    dataset_description TEXT DEFAULT '',
    provider_kind       TEXT DEFAULT '',    -- cmr | cdse_odata | cds | builtin_node
    time_start          TEXT DEFAULT '',
    time_end            TEXT DEFAULT '',
    path_prefix         TEXT DEFAULT '',    -- 门户 base_url 下的路径前缀（http_open_data 归属判断；多个以换行分隔）
    search_meta         TEXT DEFAULT '{}',  -- 检索元数据 JSON 快照（data_link/version/示例条目等）
    enabled             INTEGER NOT NULL DEFAULT 1,
    archived            INTEGER NOT NULL DEFAULT 0,
    migrated_from       TEXT DEFAULT '',    -- 存量迁移来源 remote_source_id（可空）
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE(portal_id, dataset_key)
);
```

新模块 `Code/backend/app/services/remote_dataset_grants.py`：Repository（对齐 remote_source_registry.py 范式：SQLiteConnectionPool、CREATE IF NOT EXISTS、upsert/delete/list/get、`get_remote_dataset_grants()` 单例、`RemoteDatasetGrantsError`）。UNIQUE(portal_id, dataset_key) 使「同一站点添加同一数据集」幂等合并（upsert ON CONFLICT 更新标题/前缀/时间范围，保留 created_at 与 enabled）。

### 1.2 remote_sources 表扩展（ALTER ADD COLUMN，additive）

```sql
ALTER TABLE remote_sources ADD COLUMN access_mode TEXT NOT NULL DEFAULT 'legacy';
-- legacy            旧文件级条目（迁移源；kind=storage_profile 例外，见下）
-- site_compatible   站点「节点访问兼容」开关条目（kind=portal、remote_path=''）
ALTER TABLE remote_sources ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
```

站点兼容开关 = 该 portal 存在一条 `kind='portal', access_mode='site_compatible', enabled=1, archived=0` 条目（幂等：upsert 前查询该 portal 既有开关条目则更新之）。`kind=storage_profile` 条目迁移时统一标 `access_mode='site_compatible'`（整源访问本就是全放行语义，不进入数据集管控）。

_init_schema 中用 `PRAGMA table_info(remote_sources)` 检测缺列后 ALTER（SQLite ADD COLUMN 幂等保护：捕获 OperationalError duplicate column）。

### 1.3 访问模式语义（并集）

有效权限(portal) = site_compatible 开关生效 OR dataset_key/路径前缀命中 grants。
**未配置任何授权的门户（无开关且白名单空）视为「未管控」→ 放行**（向后兼容：升级不断存量工作流）。门户一旦有任何授权条目即进入管控态。

## 2. 检索 API 改造（portal_catalog.py）

`search_portal(portal_id, query=..., page_size=...)` 返回改为数据集级，新统一条目结构：

```python
{
  "dataset_key": "GLDAS_NOAH025_3H",     # 白名单主键
  "title": "GLDAS Noah L4 3 hourly 0.25 deg V2.1",
  "description": "...",
  "time_start": "2000-02-24T00:00:00Z", "time_end": "",
  "provider_kind": "cmr",
  "extra": {"version": "2.1", "data_link": "...", "count": 3}   # provider 特定
}
```

三种 provider：
- **CMR**：模板改为 `{base}/search/collections.json?keyword={query}&page_size={page_size}`；新 parser `_parse_cmr_collection_entry`：dataset_key=`entry.short_name`（缺失回退 entry_title 去空格；实现时以真实响应验证字段）、title=entry_title、description=summary、time_start/end=entry.time_start/time_end、extra={version, data_center}。连通性测试 URL `_test_url_for`（L752）同步换 collections。
- **CDSE OData**：仍查 `/odata/v1/Products?$filter=contains(Name,'{query}')&$top=200`，但解析改为**聚合**：按产品名前两段（任务_产品级，如 `S2A_MSIL1C`、`S1A_IW_GRDH`）分组，每组产出一条数据集条目（dataset_key=模式、title=模式、extra={count, sample_product_id}）。产品级细节不再直接暴露。
- **CDS**：已是 collection 级，仅字段重排（dataset_key=id、title、description）。

契约（config_contracts.py）：`PortalSearchResultItem` 替换为 `PortalSearchDatasetItem`（dataset_key/title/description/time_start/time_end/provider_kind/extra: dict）；`PortalSearchResponse.items` 换类型。前端同步改（破坏性变更一次到位，UI 已确认纯数据集级展示）。

NSMC 等 search_capability='none' 门户不经过检索：其白名单来自「手动添加授权」对话框 + 专用节点内置数据集候选（§4.1）。

## 3. API 契约草案（新增）

```
GET    /config/remote-datasets/grants                → list[RemoteDatasetGrant]      (read)
PUT    /config/remote-datasets/grants/{grant_id}     → RemoteDatasetGrant            (admin；UNIQUE 冲突 400)
DELETE /config/remote-datasets/grants/{grant_id}     → DeletedResponse               (admin)
GET    /config/remote-datasets/policy                → RemoteDatasetPolicy[]         (read；编辑器过滤用)
POST   /config/remote-sources/migrate-legacy         → MigrationReport               (admin；手动重跑迁移)
```

- `RemoteDatasetGrant`：grant_id/portal_id/dataset_key/dataset_title/dataset_description/provider_kind/time_start/time_end/path_prefix/enabled/archived/migrated_from/created_at/updated_at + ref 徽标（复用 RemoteSourceRefBadge 风格：门户存在性/search_capability/凭据状态）。
- `RemoteDatasetPolicy`（编辑器消费的投影）：`{portal_id, managed: bool, compatible: bool, datasets: [{grant_id, dataset_key, title, path_prefix[]}]}`。
- `RemoteSourceEntry`/`RemoteSourceUpsertRequest` 增 `access_mode`（默认 legacy）、`archived`（只读）。
- 路由落 config_routes.py「可访问远程数据源」区块（L1135 附近）；服务门面落 config_service.py（对齐 L552-584 范式）。

## 4. 访问控制执行点

### 4.1 dataset_key 映射表（专用节点内置数据集建模）

| 节点 / node_class | 门户（portal_id） | dataset_key 规则 | 校验时机 |
|---|---|---|---|
| http_open_data | preset=portal_id（模板 options 即门户键） | relative_path 前缀匹配 grant.path_prefix（多前缀换行分隔） | 提交（参数）+ 运行时（上游 path 输入） |
| cmr_granule_search | nasa_cmr | = params.short_name | 提交 |
| cds_download | ecmwf_cds | = params.dataset | 提交 |
| gldas_download | nasa_gldas | = params.short_name（默认 GLDAS_NOAH025_3H） | 提交 |
| nsidc_smap_download | nsidc_data | = f"SPL3SMP_E_V{version}" | 提交 |
| fy_download | cma_nsmc | = f"{satellite}_{orbit_mode}"（FY3D_MWRID 等） | 提交 |
| nomads_grib_download | noaa_nomads | = f"nomads_{model}" | 提交 |
| cdse_download | esa_copernicus | product_ids/odata_filter 中产品名前两段模式（运行时解析） | 仅运行时 |
| remote_fetch / ssh_sync | storage_profile（kind 站点，天然全放行） | — | 不校验 |

### 4.2 运行时硬校验 — 推荐双层

**层 1（提交时，后端 FastAPI 进程）**：`python_provider_request_builder.build_job_request_payload` L131-149 处，在注入 open_data_presets 的同一位置追加注入 `ds["remote_dataset_policy"]`（§3 policy 投影，无敏感信息可随 job 持久化）；随后在 `PythonProviderBridgeService.execute`（bridge L324 之前）新增 `_validate_remote_dataset_access(workflow_definition, request_payload)`：遍历 workflow_definition.nodes，按 §4.1 表校验参数型 dataset_key；失败 raise `BridgeExecutionError(category=validation_error, message="门户 {pid} 数据集 {key} 未授权…")`（HTTP 层 403 语义）。上游动态输入（http_open_data 的 path 端口）提交时不可知 → 留层 2。

**层 2（provider 节点内，algorithms/providers/Python）**：新增共享 helper（放 `modules/_remote_access_guard.py`），各下载模块 execute 开头调用：

```python
def check_remote_dataset_access(ds, portal_id, *, dataset_key=None, rel_path=None):
    policy = (ds or {}).get("remote_dataset_policy") or {}
    p = policy.get(portal_id)
    if p is None or not p.get("managed"):
        return                      # 未管控门户：放行
    if p.get("compatible"):
        return                      # 兼容模式：全放行
    if dataset_key and dataset_key in p.get("datasets", {}):
        return
    if rel_path:
        norm = rel_path.lstrip("/")
        for d in p.get("datasets", []):
            for px in d.get("path_prefix", []):
                if norm.startswith(px.strip("/")):
                    return
    raise ValueError(f"远程数据集未授权：门户 {portal_id}，数据集 {dataset_key or rel_path}")
```

HttpOpenDataModule 在 resolve rel 后调用（rel=参数与输入合并值）；fy_download/gldas/nsidc/cds/nomads 在解析 resolved 参数后调用；cdse_download 在解析产品名后调用。这同时覆盖「提交时不可知的动态路径/产品 ID」。

### 4.3 编辑器过滤（前端）

- **HttpOpenDataForm.vue**：onMounted 并行拉 `GET /config/remote-datasets/policy`；presetOptions 改为「未管控门户全量 + 管控门户按 policy 显示（无数据集授权且无兼容开关的管控门户仍显示，但 relative_path 输入旁加警示）」；relative_path 输入时按当前门户 grants.path_prefix 做前缀校验提示（软提示，硬拦截在提交层）。
- **专用节点表单**（DownloadNodeForm.vue 及 gldas/nsidc/cds/fy/nomads 对应表单）：对应门户被管控时，short_name/dataset/model/satellite+orbit_mode 选项改由 policy.datasets 动态生成；未管控维持现有静态 options（node_template_registry 的 options 不动，避免破坏离线回退）。
- **工作流种子**（workflow_seeds/system/*.json 静态参数）：打开画布时表单校验对不在白名单的值显示错误文案「数据集未授权，请到 设置→数据源 添加」，编辑不阻断，提交被层 1 拦截并回显。

## 5. 存量迁移

### 5.1 推断规则（kind=portal 且 remote_path 非空）

1. **内置映射表优先**：静态表 `_BUILTIN_DATASET_HINTS: {portal_id: [(regex, dataset_key, path_prefix)]}`：
   - nasa_gldas/nasa_ges_disc：`(?:data/)?GLDAS(?:_NOAH025_3H)?` → `GLDAS_NOAH025_3H`，prefix `data/GLDAS`
   - nsidc_data：`SPL3SMP_E` → `SPL3SMP_E_V6`，prefix `nsidc-cumulus-prod-protected/SPL3SMP_E`
   - esa_copernicus/esa_download：`(S\d[AB]_[A-Z0-9_]+?)_` 任务_产品级模式 → dataset_key=模式
   - cma_nsmc/cma_data：`(FY3[BD])[^/]*?(MWRI[AD]?)` → `FY3D_MWRID` 型
   - noaa_nomads：`(gfs|gefs|gdas|nam|...)` → `nomads_gfs` 型
2. **通用短名规则**：remote_path 首段匹配 `^[A-Z][A-Z0-9_]{5,}$`（CMR 短名形态）→ dataset_key=首段、path_prefix=首段。
3. **fallback（推断失败）**：默认保守——原条目保持 `access_mode='legacy'`、不归档，前端标「待人工归并」，不打断任何现有访问；提供 Tools 脚本 `--safe` 选项可将该门户自动升级为 site_compatible（等价旧「整源」行为）。
4. 迁移动作：推断成功 → 写入 remote_dataset_grants（migrated_from=原条目 id、provider_kind 按门户、path_prefix 同步写入）；原条目 `archived=1`。`remote_path=''` 的 portal 条目 → 直接 `access_mode='site_compatible'`（原地升级，不归档）。storage_profile 条目 → `access_mode='site_compatible'`。

### 5.2 迁移形态

- 函数 `migrate_legacy_remote_sources(*, dry_run=False, safe=False) -> MigrationReport`（放 remote_source_registry.py 或新模块），幂等（KV 标记 `remote_source_migration_v2_done` + 条目 archived 幂等）。
- 启动一次性：main.py lifespan（L84 sync_algorithm_datasets 之后）调用；失败仅告警不阻断。
- 手动：`Tools/migrate_remote_sources_v2.py`（--dry-run/--safe，打印报告）+ API `POST /config/remote-sources/migrate-legacy`（UI「重新迁移」入口）。

## 6. 前端改造清单

| 文件 | 变更 |
|---|---|
| `settings/portals/PortalSearchDialog.vue` | 结果条目改数据集级（dataset_key/title/description/时间范围）；「添加为远程数据源」→「添加数据集授权」调 PUT grants；文案「该数据集授权后，未授权数据集将不可在工作流中访问」 |
| `settings/data-source/RemoteDataSourcesPanel.vue` | addDialog 增「访问模式」单选：节点访问兼容（写 site_compatible 条目）/ 指定数据集（引导打开检索对话框）；新增「手动添加数据集授权」入口（portal 下拉+dataset_key+显示名+path_prefix，供无检索能力门户如 NSMC） |
| `settings/data-source/RegisteredRemoteSources.vue` | 改为两段：兼容模式条目表（开关行）+ 数据集授权表（grant_id/门户/数据集/时间范围/启停/归档标记/删除）；归档 legacy 条目折叠展示 |
| `workflow/node-forms/HttpOpenDataForm.vue` | §4.3 policy 过滤 + 前缀提示 |
| `workflow/node-forms/DownloadNodeForm.vue` 及专用表单 | §4.3 动态 options |
| `services/settings-api.ts` + `stores/settings.ts` | fetchRemoteDatasetGrants/saveGrant/removeGrant/fetchRemoteDatasetPolicy；store 增 remoteDatasetGrants/remoteDatasetPolicy state |
| 类型链 | `python Code/backend/scripts/export_openapi.py` → `cd Code/frontend && npm run gen:types` → `npm run check:openapi` |
| `settings/portals/OpenPortalPanel.vue` | PortalSearchDialog props 不变则仅需回归验证 |

## 7. 测试方案

后端（Test/backend/，REDIS_URL+ENVIRONMENT=test）：
- `test_remote_dataset_grants.py`：CRUD、UNIQUE(portal_id,dataset_key) 幂等合并、enabled 开关、path_prefix 解析。
- `test_portal_catalog.py` 增补：CMR collections mock（feed.entry → dataset_key/title/time）、CDSE 聚合（产品名模式分组计数）、CDS 字段重排；_test_url_for 换端点。
- `test_remote_source_migration.py`：各门户路径推断矩阵、fallback 保留 legacy、remote_path=''→site_compatible、幂等二跑。
- `test_remote_dataset_policy.py`：policy 投影（managed/compatible/datasets）、builder 注入 ds["remote_dataset_policy"]、bridge 提交拦截（未授权 dataset_key → BridgeExecutionError；未管控门户放行；兼容开关放行）。
- 前端 vitest（Test/frontend/）：PortalSearchDialog 数据集条目渲染与添加调用、HttpOpenDataForm policy 过滤逻辑（可抽 composable 纯函数测试）。
- 综合下载验证：gldas_download（dry_run=true）×GLDAS_NOAH025_3H 授权/未授权；nomads model 授权矩阵；cds_download use=legacy 小文件；http_open_data 真实小对象（noaa_goes 免凭据）授权前后对比。CI 之外的手动验收清单（各源 × 数据集 dry_run 矩阵）写入阶段 6。

## 8. 实施顺序（6 个 commit，conventional commits）

1. **feat(config): 数据集授权注册表与 API** — remote_dataset_grants 表+Repository+契约+config_routes CRUD+测试。验证：pytest 新增全绿、check:openapi 通过。
2. **feat(config): 门户检索数据集级改造** — portal_catalog 三 provider+契约+测试；前端 gen:types。验证：mock 检索测试 + 手动对 CMR/CDS 真实端点 smoke。
3. **feat(config): remote_sources 访问模式扩展与存量迁移** — ALTER 列+推断迁移+main.py 启动钩子+Tools 脚本+API。验证：迁移测试矩阵 + 对现有 research_data_settings.sqlite3 副本 dry-run 报告。
4. **feat(workflow): 数据集访问策略注入与提交/运行时校验** — policy 投影+builder 注入+bridge 拦截+provider 侧 guard helper（algorithms 侧改动）+测试。验证：提交拦截测试 + provider 节点单测。
5. **feat(frontend): 数据集授权 UI 与编辑器过滤** — 设置页三组件+API/store+节点表单过滤+vitest。验证：vitest + 手动走查（检索添加→节点下拉过滤→提交拦截回显）。
6. **test(e2e): 各源数据集下载综合验证** — dry_run 矩阵脚本/清单 + 文档。验证：授权/未授权行为矩阵通过。

## 9. 风险与备注

- CMR collections.json 响应字段（short_name 顶级字段）需实现时以真实响应验证；缺失则回退 entry_title 派生（文档已注明）。
- PortalSearchResultItem 类型替换是破坏性契约变更：前后端必须同一 commit 批次内对齐（阶段 2 内完成 gen:types）。
- 「未管控门户放行」是兼容性决策，若产品要求默认拒绝，可加 settings 开关（BACKEND_REMOTE_DATASET_DEFAULT_DENY），本期不做。
- cdse_download 的 odata_filter 动态产品只能运行时校验（层 2），文档已在 §4.1 标注。
