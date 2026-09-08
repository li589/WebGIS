# 远程访问功能集成化接入计划（v2 — 基于用户决策与架构审计）

## 摘要

将 NDVI 图层、SMAP 数据、风云数据接入在线拉取能力，使用户可在分析模块界面中直接运行图层工作流并实时显示在线数据计算结果。

**用户决策**：
- **风云数据**：三路并行接入 — ① NAS 远程拉取（`Chenhaojun/fy` 目录，部署环境直连，开发环境走 Cloudflare 隧道 + filebrowser）② NSMC 门户 HTTP 预设 ③ 创建专业风云卫星数据下载模块节点
- **NDVI**：NASA Earthdata + GEE 两者都支持

**架构审计发现（Health Score: 78/100）**：在接入新数据源前，需先消除预设字典重复定义（R3）和算法层向上依赖（R5），否则新增数据源的修改点将达到 6+ 文件（Shotgun Surgery）。

---

## 当前状态分析

### 已有能力（无需改动）

| 子系统 | 现状 | 关键文件 |
|--------|------|---------|
| HTTP 开放数据下载 | `download/http_open_data` 节点 + 9 个预设（NASA/NSIDC/NOAA/ESA） | `data_access_nodes.py` L183-193, L303-399 |
| SMAP 在线拉取 | `omega_avg_daily_smap_online.json`，`nsidc_data` 预设 + `earthdata` 凭证 | `workflow_seeds/system/omega_avg_daily_smap_online.json` |
| GLDAS 在线拉取 | `omega_avg_daily_gldas_online.json`，`gldas_download` 专用节点 | `workflow_seeds/system/omega_avg_daily_gldas_online.json` |
| SSH 远程同步 | `ssh_sync` 节点，支持 HPC/NAS/Win11 | `data_access_nodes.py` L92-235 |
| 工作流提交/轮询/产物挂载 | 完整链路：submit → poll → attach overlays | `workflow-runner.ts`, `workflow-poller.ts`, `run-layers.ts` |
| 在线时间编排器 | `OnlineTemporalOrchestrator`：时间轴选点 → 自动提交 → 预取 | `online-temporal-orchestrator.ts` |
| 图层能力判定 | `supportsOnlineTemporalCapability()` + `GET /layers/{id}/online-temporal` | `layer-capabilities.ts`, `layer_router.py` L161-176 |
| GEE 桥接 | `GeeBridgeService`：账号池 + 工作流提交 + 导出轮询 | `gee_bridge_service.py` |
| 凭证管理 | Portal credentials + remote auth resolver + 加密存储 | `data_access_nodes.py` L208-300, `remote_auth_resolver.py` |
| 条件 GET 缓存 | HttpSource 支持 ETag/Last-Modified + 魔法字节嗅探 | `data_access/sources/http.py` |
| 产物 → 图层渲染 | `materialize-map-layers` → overlay 注册 → MapLibre image source | `python_provider_result_builder.py`, `overlay-image-module.ts` |

### 架构审计发现（需在接入前修复）

| 风险 | 严重度 | 发现 | 影响 |
|------|--------|------|------|
| R3 Knowledge Duplication | 🟡 Warning | `_DEFAULT_OPEN_DATA_PRESETS` 在 `data_access_nodes.py` L183 和 `data_cache_service.py` L178 重复定义 | 新增预设需两处同步，遗漏导致运行时 404 |
| R5 Dependency Disorder | 🟡 Warning | 算法层 `data_access_nodes.py` import `app.services.config_service`；`remote.py` import `app.services.remote_auth_resolver` | 算法包无法脱离后端独立测试 |
| R2 Change Propagation | 🟡 Warning | 新增一个数据源需修改 5-6 文件（Shotgun Surgery） | 扩展成本高，遗漏风险大 |
| Testability Seam | 🟡 Warning | 凭证解析无接口边界，`_resolve_earthdata_portal_userpass()` 直接调用后端 | 下载节点单元测试覆盖率为零 |
| R1 Cognitive Overload | 🟢 Suggestion | `data_access_nodes.py` 1026 行，9 个模块 + 6 个辅助函数混合 | 新增节点定位困难 |

### 缺口识别

| # | 缺口 | 影响 | 复杂度 |
|---|------|------|--------|
| G1 | NDVI 仅有本地工作流种子，无在线拉取种子 | NDVI 图层 `online_temporal.enabled=true` 但实际不可用 | 低 |
| G2 | 风云数据无在线下载能力（NAS/NSMC/专用模块三路均缺） | FY 数据完全依赖本地落盘 | 高 — 三路并行 |
| G3 | FY 图层目录无 `online_temporal` 配置 | 前端无法触发 FY 在线获取 | 低 |
| G4 | 分析面板缺少在线获取状态 UI 指示 | 用户无法感知在线拉取进度 | 低 |
| G5 | NDVI 无 GEE 在线获取种子 | 用户无法通过 GEE 获取 NDVI | 中 — 需 GEE 工作流定义 |

---

## 提议变更

### 阶段 0：架构修复（审计发现前置）

#### 0a. 消除预设字典重复定义（R3 修复）

**文件**：
- `Code/backend/app/services/data_cache_service.py` L178-196（保留为单一真源）
- `Code/algorithms/providers/Python/modules/data_access_nodes.py` L183-193（删除副本，改为运行时注入读取）

**变更**：
1. `data_cache_service.py` 中的 `DEFAULT_OPEN_DATA_PRESETS` 保持为唯一定义
2. `data_access_nodes.py` 中的 `_DEFAULT_OPEN_DATA_PRESETS` 删除，改为从 `datasource_selection.open_data_presets` 读取（`python_provider_request_builder.py` L215 已在提交时注入此字段）
3. `HttpOpenDataModule.execute()` 中 `presets = dict(_DEFAULT_OPEN_DATA_PRESETS)` 改为 `presets = dict(ctx.datasource_selection.get("open_data_presets", {}))`，若为空则回退到硬编码最小集（仅 `nasa_earthdata` + `nsidc_data`，作为 safety net）

**效果**：新增预设只需在 `data_cache_service.py` 一处添加，消除 R3 重复。

#### 0b. 消除算法层向上依赖（R5 修复 — 最小化变更）

**文件**：`Code/algorithms/providers/Python/modules/data_access_nodes.py`

**变更**：`_resolve_earthdata_portal_userpass()` 中的 `from app.services.config_service import get_portal_credentials_runtime` 改为延迟导入 + 上下文优先模式：

```python
def _resolve_earthdata_portal_userpass(ctx: NodeExecutionContext, cred_profile: str):
    # 1. 优先从上下文获取（已由 request_builder 注入）
    portal_creds = ctx.datasource_selection.get("portal_credentials", {})
    if cred_profile in portal_creds:
        return portal_creds[cred_profile]["username"], portal_creds[cred_profile]["password"]
    
    # 2. 若标记了懒加载但未注入，延迟导入后端服务（保持兼容）
    if ctx.datasource_selection.get("portal_credentials_resolve"):
        from app.services.config_service import get_portal_credentials_runtime  # 延迟导入
        runtime_creds = get_portal_credentials_runtime()
        if cred_profile in runtime_creds:
            return runtime_creds[cred_profile]["username"], runtime_creds[cred_profile]["password"]
    
    return None, None
```

**设计决策**：不立即做完整的依赖反转（需要定义接口 + 注入容器），而是通过"上下文优先 + 延迟导入"降低耦合度。延迟导入使算法包在 `import` 阶段不再失败，可在无后端环境下的测试中 mock 上下文。

**文件**：`Code/algorithms/providers/Python/data_access/sources/remote.py`

**变更**：`from app.services.remote_auth_resolver import resolve_remote_auth` 同样改为延迟导入 + 上下文优先：

```python
def _resolve_auth(self, uri: str, settings, metadata: dict):
    # 1. 优先从 metadata 获取已解析的 auth
    if "auth" in metadata:
        return metadata["auth"]
    # 2. 延迟导入
    from app.services.remote_auth_resolver import resolve_remote_auth
    return resolve_remote_auth(uri)
```

---

### 阶段 1：风云数据三路在线接入（G2）

#### 1a. NAS 远程拉取路径

**用户场景**：部署环境可直接访问 NAS 上的 `Chenhaojun/fy` 目录；开发环境通过 Cloudflare 隧道 + filebrowser 访问。

**文件**：`Code/backend/workflow_seeds/system/fy_tb_nas_read.json`（新建）

**内容**：使用 `remote_fetch` 节点从 NAS 拉取 FY 数据。

```
remote_fetch (uri=smb://nas/Chenhaojun/fy/YYYY.MM.DD/?cred=nas_profile)
  → module/fy_preprocess (satellite=FY3D, orbit_mode=MWRID, band_ids=[1,2])
  → output/map_layer (layer_id=ref-fy-tb-202512-mwri)
```

**关键属性**：
- `uri`: `smb://nas/Chenhaojun/fy/{YYYY.MM.DD}/?cred=nas_profile`（占位符由 resolver 替换）
- `_meta.tags`: `["sample", "remote"]`
- `_meta.category`: `data_access`
- `extra.purpose`: `nas_fy_pipeline`
- `extra.scheme`: `smb`

**凭证配置**：在 `remote_storage_credentials.sqlite3` 中注册 `nas_profile`（SMB 协议，host=nas 主机名/IP，username/password 或 guest）。

**Cloudflare 隧道适配**：开发环境若需通过 filebrowser HTTP 访问，可将 `uri` 改为 `https://filebrowser.example.com/api/...?cred=cf_tunnel`，由 `HttpSource` 处理（filebrowser API 返回文件流）。此模式在种子的 `_meta.notes` 中标注。

#### 1b. NSMC 门户 HTTP 预设路径

**文件**：
- `Code/backend/app/services/data_cache_service.py` L178-196（单一真源，阶段 0a 修复后）
- `Code/algorithms/providers/Python/modules/data_access_nodes.py` L195-205（`_PORTAL_CRED_ALIASES`）

**变更**：在 `DEFAULT_OPEN_DATA_PRESETS` 中新增：

```python
"cma_nsmc": "https://satellite.nsmc.org.cn/",
"cma_data": "https://data.nsmc.org.cn/",
```

在 `_PORTAL_CRED_ALIASES` 中新增：

```python
"nsmc": ("nsmc", "cma_nsmc", "cma_data", "fy"),
```

**文件**：`Code/backend/workflow_seeds/system/fy_tb_nsmc_online.json`（新建）

**内容**：通过 NSMC 门户在线拉取 FY-3 MWRI HDF 亮温数据。

```
download/http_open_data (preset=cma_nsmc, cred_profile=nsmc)
  → archive/extract (member_glob=*.HDF, recurse_once=true)
  → module/fy_preprocess (satellite=FY3D, orbit_mode=MWRID, band_ids=[1,2])
  → output/map_layer (layer_id=ref-fy-tb-202512-mwri)
```

#### 1c. 专业风云卫星数据下载模块节点

**用户要求**：在工作流模块中创建一个专业的 FY 卫星数据下载节点。

**文件**：`Code/algorithms/providers/Python/modules/fy_download.py`（新建）

**模块设计**：

```python
class FYDownloadModule(BaseModule):
    """风云卫星数据专用下载模块。
    
    支持：
    - FY-3B/3D MWRI 亮温（L1B HDF）
    - FY-4A AGRI GIIRS（L1B HDF）
    - 日期范围 + 轨道类型筛选
    - NSMC 门户认证（token/cookie）
    - 断点续传（基于 HttpSource 条件 GET 缓存）
    - 多源回退：NSMC → NAS → 本地缓存
    """
    
    module_name = "fy_download"
    task_type = "fy_download"
    
    def execute(self, ctx: NodeExecutionContext) -> ProductManifest:
        satellite = ctx.algorithm_params.get("satellite", "FY3D")
        date_range = ctx.algorithm_params.get("date_range", {})
        data_source = ctx.algorithm_params.get("data_source", "nsmc")  # nsmc | nas | auto
        band_ids = ctx.algorithm_params.get("band_ids", [1, 2])
        
        if data_source == "nsmc":
            return self._download_from_nsmc(ctx, satellite, date_range, band_ids)
        elif data_source == "nas":
            return self._fetch_from_nas(ctx, satellite, date_range, band_ids)
        else:  # auto: NSMC → NAS fallback
            try:
                return self._download_from_nsmc(ctx, satellite, date_range, band_ids)
            except DownloadError:
                return self._fetch_from_nas(ctx, satellite, date_range, band_ids)
```

**注册**：在 `data_access_nodes.py` 的模块注册表中添加 `fy_download`（或在 `__init__.py` 中导入 `fy_download` 模块）。

**文件**：`Code/backend/workflow_seeds/system/fy_tb_online_read.json`（新建）

```
module/fy_download (data_source=auto, satellite=FY3D, band_ids=[1,2])
  → module/fy_preprocess (satellite=FY3D, orbit_mode=MWRID)
  → output/map_layer (layer_id=ref-fy-tb-202512-mwri)
```

#### 1d. 节点模板注册

**文件**：`Code/backend/app/services/node_template_registry.py` L252-268

**变更**：
1. 在 `download/http_open_data` 节点的 `preset` 枚举中新增 `cma_nsmc` 和 `cma_data`
2. 新增 `module/fy_download` 节点模板，参数包括 `satellite`（FY3D/FY3B/FY4A）、`data_source`（nsmc/nas/auto）、`band_ids`、`date_range`

#### 1e. FY 图层 online_temporal 配置

**文件**：`Code/backend/app/catalog_seeds/layer_descriptors.json`

**变更**：在 `ref-fy-tb-202512-mwri` 图层描述符中新增：

```json
{
  "online_temporal": {
    "enabled": true,
    "coverage_start": "2020-01",
    "coverage_end": "2025-12",
    "native_step": "1D",
    "max_batch": 7,
    "prefetch_depth": 1,
    "queue_tag": "temporal-fetch",
    "priority": "low"
  },
  "workflow_online_name": "fy_tb_online_read",
  "workflow_aliases": ["fy_tb_local_read", "fy_tb_nas_read", "fy_tb_nsmc_online", "fy_tb_online_read"]
}
```

---

### 阶段 2：NDVI 双源在线接入（G1 + G5）

#### 2a. NASA Earthdata 在线种子

**文件**：`Code/backend/workflow_seeds/system/ndvi_online_read.json`（新建）

```
download/http_open_data (preset=nasa_earthdata, cred_profile=earthdata)
  → archive/extract (member_glob=*.tif, recurse_once=true)
  → module/ndvi_daily (rescale=-1,1, nodata=-9999)
  → output/map_layer (layer_id=ndvi, colormap=ndvi, rescale=-1,1)
```

**关键属性**：
- `preset`: `nasa_earthdata`（LP DAAC VIIRS VNP13 系列）
- `cred_profile`: `earthdata`（复用现有凭证）
- `relative_path`: 含 `YYYY.MM.DD` 占位符
- `_meta.linked_layer_id`: `ndvi`
- `extra.purpose`: `online_ndvi_pipeline`

#### 2b. GEE NDVI 在线种子

**文件**：`Code/backend/workflow_seeds/system/ndvi_gee_read.json`（新建）

**内容**：通过 GEE 桥接服务获取 MODIS/VIIRS NDVI 产品。

```
gee/export (workflow=ndvi_gee_export, manifest_uri=gee://projects/.../ndvi_export.json)
  → output/map_layer (layer_id=ndvi, colormap=ndvi, rescale=-1,1)
```

**GEE 工作流定义**（嵌入种子的 `algorithm_params.gee_request.workflow`）：

```javascript
// GEE NDVI export workflow
var collection = ee.ImageCollection('MODIS/061/MOD13A2')
  .filterDate(start_date, end_date)
  .select('NDVI');
var image = collection.mean();
Export.image.toAsset({
  image: image,
  description: 'ndvi_export',
  region: geometry,
  scale: 1000,
  crs: 'EPSG:4326'
});
```

**关键属性**：
- `_meta.engine`: `gee`（GEE 引擎而非 python_provider）
- `_meta.linked_layer_id`: `ndvi`
- `extra.purpose`: `gee_ndvi_pipeline`
- `extra.scheme`: `GEE_MODIS_NDVI`

#### 2c. NDVI 图层目录更新

**文件**：`Code/backend/app/catalog_seeds/layer_descriptors.json`

**变更**：NDVI 图层描述符新增在线工作流关联：

```json
{
  "workflow_online_name": "ndvi_online_read",
  "workflow_gee_name": "ndvi_gee_read",
  "workflow_aliases": ["ndvi_local_read", "ndvi_online_read", "ndvi_gee_read"]
}
```

**设计决策**：前端通过 `workflow_aliases` 列表提供数据源切换 UI；`online_temporal` 触发时默认使用 `workflow_online_name`（Earthdata），用户可在图层设置中切换为 `workflow_gee_name`（GEE）。

---

### 阶段 3：后端时间占位符替换（跨种子通用）

**文件**：`Code/backend/app/services/workflow_request_resolver.py`

**变更**：在 `_PythonProviderPopulator` 或 `_flatten_ui_workflow_definition()` 中，当 `time_range` 存在且节点 `relative_path` / `uri` 含日期占位符时，自动替换。

**替换规则**：

| 占位符 | 替换为 | 示例 |
|--------|--------|------|
| `{YYYY.MM.DD}` | `time_range.start_at` 的 `%Y.%m.%d` | `2025.06.01` |
| `{YYYY-MM}` | `time_range.start_at` 的 `%Y-%m` | `2025-06` |
| `{YYYYMMDD}` | `time_range.start_at` 的 `%Y%m%d` | `20250601` |
| `YYYY.MM.DD`（无花括号） | 同上 | 同上 |

**触发条件**：`time_range` 非空 + 节点 properties 含 `relative_path` 或 `uri` 且其中含占位符模式。

**影响范围**：仅影响含占位符的种子，本地工作流（如 `ndvi_local_read`）不含占位符，不受影响。

---

### 阶段 4：前端在线获取状态 UI（G4）

**文件**：
- `Code/frontend/src/views/dashboard/useOnlineTemporalIntegration.ts`
- `Code/frontend/src/components/info-panel/InfoPanelToolsTab.vue`（或图层管理面板）

**变更**：

1. 在 `useOnlineTemporalIntegration.ts` 中将 `currentFetchStatus` 和 `fetchEntries` 暴露给 Dashboard 组件：
```typescript
return {
  // ... 现有返回值 ...
  onlineFetchStatus: readonly(currentFetchStatus),
  fetchEntries: readonly(fetchEntries),
}
```

2. 在图层管理面板中为支持 `online_temporal` 的图层添加状态徽标：
```vue
<template v-if="layer.capabilities?.onlineTemporal">
  <span :class="`fetch-badge fetch-${fetchStatus}`">
    {{ fetchStatusText }}
  </span>
</template>
```

3. 状态文案映射：
- `submitting` → "提交中…"
- `in-flight` → "拉取中…"
- `succeeded` → "已就绪"
- `failed` → "获取失败"
- `cooling` → "冷却中"

**不新增组件**，仅扩展现有组件的 computed 属性。

---

## 假设与决策

### A1：NDVI 双源 — Earthdata 为默认，GEE 为可选
- **理由**：用户要求两者都支持；Earthdata 复用现有 `earthdata` 凭证，产出直接为 GeoTIFF；GEE 适合需要大范围合成或自定义算法的场景
- **实现**：`workflow_online_name` 默认指向 Earthdata 种子，`workflow_gee_name` 指向 GEE 种子，前端提供切换 UI

### A2：风云三路 — NAS 为部署默认，NSMC 为开发/独立环境，专用模块为统一入口
- **理由**：部署环境可直接访问 NAS（性能最优，无需 NSMC 凭证）；开发环境通过 Cloudflare 隧道访问同一 NAS 或走 NSMC；专用 `fy_download` 模块提供 `data_source=auto` 自动回退
- **实现**：三份种子（`fy_tb_nas_read` / `fy_tb_nsmc_online` / `fy_tb_online_read`），`workflow_aliases` 列出全部，`fy_tb_online_read`（专用模块）作为 `workflow_online_name` 默认值

### A3：架构修复（阶段 0）先于功能开发
- **理由**：审计发现 R3（预设重复）和 R5（向上依赖）若不先修复，新增 CMA/NSMC 预设需在两处同步添加，且新增 `fy_download` 模块会继承向上依赖问题
- **影响范围**：阶段 0 变更最小化（延迟导入 + 上下文优先），不改变现有功能行为

### A4：时间占位符替换在后端 resolver 中执行
- **理由**：前端 `OnlineTemporalOrchestrator` 已构建 `time_range` 并传入 `runWorkflowForCatalog`，后端 resolver 在展平工作流时替换占位符是最自然的注入点
- **影响范围**：仅影响含占位符的种子，本地工作流不受影响

### A5：保持本地工作流种子向后兼容
- **理由**：`ndvi_local_read` 和 `fy_tb_local_read` 已被现有图层引用，不能删除或重命名；新增在线种子作为并行选项

---

## 验证步骤

### V0：架构修复验证
```bash
# 1. 预设单一真源验证
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -c "
import sys; sys.path.insert(0, 'Code/algorithms/providers/Python')
# 验证算法层不再有独立预设字典
from modules import data_access_nodes
assert not hasattr(data_access_nodes, '_DEFAULT_OPEN_DATA_PRESETS') or len(data_access_nodes._DEFAULT_OPEN_DATA_PRESETS) <= 2, '预设字典应已精简为 safety net'
print('OK: 预设单一真源')
"

# 2. 算法层 import 验证（不应在 import 时失败）
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -c "
import sys; sys.path.insert(0, 'Code/algorithms/providers/Python')
from modules import data_access_nodes
from data_access.sources.remote import RemoteSource
print('OK: 算法层无 import 时向上依赖')
"
```

### V1：NDVI 在线种子验证
```bash
# 种子 JSON 格式校验
Env/Python312/python.exe -c "import json; json.load(open('Code/backend/workflow_seeds/system/ndvi_online_read.json'))"
Env/Python312/python.exe -c "import json; json.load(open('Code/backend/workflow_seeds/system/ndvi_gee_read.json'))"

# 种子加载测试（后端启动后）
curl http://127.0.0.1:8000/workflow-definitions/ndvi_online_read
curl http://127.0.0.1:8000/workflow-definitions/ndvi_gee_read
```

### V2：风云三路种子验证
```bash
# 种子 JSON 格式校验
Env/Python312/python.exe -c "import json; json.load(open('Code/backend/workflow_seeds/system/fy_tb_nas_read.json'))"
Env/Python312/python.exe -c "import json; json.load(open('Code/backend/workflow_seeds/system/fy_tb_nsmc_online.json'))"
Env/Python312/python.exe -c "import json; json.load(open('Code/backend/workflow_seeds/system/fy_tb_online_read.json'))"

# 预设注册检查（单一真源）
Env/Python312/python.exe -c "
import sys; sys.path.insert(0, 'Code/backend')
from app.services.data_cache_service import DEFAULT_OPEN_DATA_PRESETS
assert 'cma_nsmc' in DEFAULT_OPEN_DATA_PRESETS
print('OK: cma_nsmc preset in single source')
"

# FY 下载模块注册检查
Env/Python312/python.exe -c "
import sys; sys.path.insert(0, 'Code/algorithms/providers/Python')
from modules.fy_download import FYDownloadModule
print('OK: FYDownloadModule registered')
"
```

### V3：工作流种子编译验证
```bash
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_workflow_graph_compiler.py -q --basetemp="Test/.pytest-be"
```

### V4：配置与鉴权验证
```bash
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_config_security.py Test/backend/test_api_keys_basemap.py Test/backend/test_auth.py -q --basetemp="Test/.pytest-be"
```

### V5：图层目录与契约检查
```bash
cd Code/frontend && npm run check:catalog
cd Code/frontend && npm run check:openapi
```

### V6：前端测试
```bash
cd Code/frontend && npm run test && npm run lint && npm run build
```

### V7：端到端联调
```bash
# 1. 启动后端
Env/Python312/python.exe launch.py start fastapi

# 2. NDVI Earthdata 在线工作流
curl -X POST http://127.0.0.1:8000/workflow-runs \
  -H "Content-Type: application/json" \
  -d '{"layer_id":"ndvi","workflow_name":"ndvi_online_read","time_range":{"start_at":"2025-06-01T00:00:00","end_at":"2025-06-02T00:00:00","granularity":"day"}}'

# 3. FY 专用模块在线工作流
curl -X POST http://127.0.0.1:8000/workflow-runs \
  -H "Content-Type: application/json" \
  -d '{"layer_id":"ref-fy-tb-202512-mwri","workflow_name":"fy_tb_online_read","time_range":{"start_at":"2025-06-01T00:00:00","end_at":"2025-06-02T00:00:00","granularity":"day"}}'

# 4. NDVI GEE 在线工作流
curl -X POST http://127.0.0.1:8000/workflow-runs \
  -H "Content-Type: application/json" \
  -d '{"layer_id":"ndvi","workflow_name":"ndvi_gee_read","time_range":{"start_at":"2025-06-01T00:00:00","end_at":"2025-06-02T00:00:00","granularity":"day"}}'
```

---

## 实施顺序

```
阶段 0（架构修复）
  ├── 0a. 消除预设字典重复（data_cache_service.py ← data_access_nodes.py）
  └── 0b. 消除向上依赖（data_access_nodes.py + remote.py 延迟导入）
       ↓
阶段 1（风云三路）
  ├── 1a. NAS 远程拉取种子（fy_tb_nas_read.json）
  ├── 1b. NSMC 门户预设 + 种子（data_cache_service.py + fy_tb_nsmc_online.json）
  ├── 1c. 专业 FY 下载模块（fy_download.py + fy_tb_online_read.json）
  ├── 1d. 节点模板注册（node_template_registry.py）
  └── 1e. FY 图层 online_temporal 配置（layer_descriptors.json）
       ↓
阶段 2（NDVI 双源）
  ├── 2a. Earthdata 在线种子（ndvi_online_read.json）
  ├── 2b. GEE NDVI 种子（ndvi_gee_read.json）
  └── 2c. NDVI 图层目录更新（layer_descriptors.json）
       ↓
阶段 3（后端占位符替换）
  └── workflow_request_resolver.py
       ↓
阶段 4（前端 UI）
  └── useOnlineTemporalIntegration.ts + 图层状态徽标
       ↓
验证 V0-V7
```

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| NAS Cloudflare 隧道在开发环境可能不稳定 | `fy_download` 模块 `data_source=auto` 自动回退到 NSMC；NAS 种子标记 `is_template=true`，用户可配置隧道地址 |
| NSMC 门户可能需要特殊认证（非 Bearer/Basic） | `_resolve_portal_headers` 已支持 `auth_type=header`；若 NSMC 使用 Cookie 认证，在 portal credentials 中配置 `token_header=Cookie` |
| GEE NDVI 导出可能耗时较长（大范围合成） | GEE 种子 `priority=low`；导出状态由 `GeeBridgeService._execute_export_poll()` 轮询；前端显示导出进度 |
| 时间占位符替换可能影响非在线工作流 | 仅在 `time_range` 存在且 `relative_path` 含占位符模式时触发；本地工作流不含占位符 |
| 阶段 0 延迟导入可能掩盖循环依赖 | 延迟导入仅用于 `config_service` 和 `remote_auth_resolver`；后续可通过定义 `CredentialProvider` 接口彻底解耦 |
| `fy_download.py` 新模块增加算法包复杂度 | 模块设计为薄编排层，核心下载逻辑复用 `HttpSource` / `RemoteSource`；按数据源域拆分是审计建议的长期重构方向 |
