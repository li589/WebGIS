# 端到端工作流流水线实施计划 v2

## 概述

将 `omega_sf_fenkuai.m` 完整迁移的 Python 算法模块、远程数据下载/同步节点集成到工作流系统，创建端到端工作流种子，完善前端触发机制（下载节点参数 UI、一键流水线入口、运行进度增强、三图层自动生成），实现"远程数据拉取→预处理→SF 块反演→3 图层展示"的自动化流水线。

## 已完成部件（验证通过）

| 部件 | 文件 | 行数 | 说明 |
|------|------|------|------|
| 算法核心 | `algorithms/omega_sf.py` | 1480 | OmegaSfConfig + SF 倒推 + FY3B→FY3D 匹配 + 块反演主循环 + PFT/pixel OMEGA |
| 模块注册 | `modules/omega_sf_fenkuai.py` | 338 | @register_module_decorator，3 输出（SM/VOD/OMEGA），数据源键映射 |
| 请求模板 | `contracts/request_templates.py` | +80 | omega_sf_fenkuai 手动 RequestTemplateSpec |
| SSH 同步 | `ingest/remote_sync.py` | 608 | ServerConfig + SFTP/FileBrowser 双路径 + 断点续传 |
| NSIDC 下载 | `ingest/nsidc_download.py` | 620 | earthaccess + CMR + HTTP Basic Auth 回退 + 断点续传 |
| FY 预处理 | `ingest/fy_preprocess.py` | 947 | FySatelliteConfig + GDAL geoloc + 拼接 + 重投影 |
| 下载节点 | `modules/download_nodes.py` | 454 | SshSyncModule + NsidcSmapDownloadModule + FyPreprocessModule |
| .env 路径映射 | `Code/backend/.env` | — | BACKEND_REMOTE_LAYER_DATA_URIS 已含 omega_sf 全部 9 个数据源键的 I 盘路径 |

## 待实施部件

### Part 1：节点模板注册（后端，阻塞前端）

**文件**：`Code/backend/app/services/node_template_registry.py`

在 `_NODE_TEMPLATES` 列表中新增 4 个节点模板：

#### 1a. `module/omega_sf_fenkuai`（算法节点）

```python
{
    "type": "module/omega_sf_fenkuai",
    "engine": "python_provider",
    "category": "反演",
    "title": "SF 块反演 (omega_sf)",
    "description": "SF 块反演 + OMEGA 识别：8-day 分块、逐日 SF 倒推、块级 h/alpha/OMEGA 优化、DDCA SM/VOD 反演。输出 SM/VOD/OMEGA 三图层。",
    "inputs": [
        _port("datasource_selection", "data:source", required=False, description="数据源选择（smap_folder/anc_root/fy3d_folder 等）"),
        _port("algorithm_params", "value:any", required=False, description="算法参数覆盖"),
    ],
    "outputs": [
        _port("manifest", "data", description="产物清单（含 SM/VOD/OMEGA 三个 ProductRef）"),
    ],
    "params": [
        _param("tb_source", "string", default="FY", options=["FY", "SMAP"], description="亮温数据源"),
        _param("fy_platform", "string", default="3D", options=["3D", "3B"], description="FY 平台（tb_source=FY 时）"),
        _param("sm_source", "string", default="SMAP", options=["SMAP", "ISMN", "DDCA"], description="土壤水分参考源"),
        _param("temp_scheme", "string", default="ORIG_TS", options=["ORIG_TS", "DUAL"], description="温度方案"),
        _param("sf_mode", "string", default="INVERTED_DAILY", options=["STATIC", "INVERTED_DAILY"], description="SF 模式"),
        _param("sf_invert_mode", "string", default="POINT1", options=["POINT1", "NDVIMIN"], description="SF 倒推模式"),
        _param("ndvi_mode", "string", default="DOY_CLIM", options=["DAILY_FILE", "DOY_CLIM"], description="NDVI 模式"),
        _param("omega_fixed_mode", "string", default="PFT", options=["PFT", "PIXEL"], description="OMEGA 固定模式"),
        _param("match_enable", "boolean", default=True, description="启用 FY3B→FY3D 匹配"),
        _param("match_method", "string", default="bias", options=["none", "bias", "cdf"], description="匹配方法"),
        _param("block_days", "number", default=8, min_val=1, max_val=16, step=1, unit="天", description="块大小"),
        _param("start_date", "string", default="20250101", description="起始日期 YYYYMMDD"),
        _param("end_date", "string", default="20251231", description="结束日期 YYYYMMDD"),
        _param("enable_parallel", "boolean", default=True, description="启用并行"),
        _param("pixel_chunk_size", "number", default=200000, min_val=10000, max_val=500000, step=10000, description="像元分块大小"),
    ],
    "node_class": "omega_sf_fenkuai",
}
```

#### 1b. `download/ssh_sync`（SSH 同步节点）

```python
{
    "type": "download/ssh_sync",
    "engine": "common",
    "category": "数据获取与解析",
    "title": "SSH/SFTP 同步",
    "description": "从 HPC/Win11/NAS 远程服务器增量同步数据到本地。支持日期过滤、断点续传、FileBrowser REST API。",
    "inputs": [
        _port("data", "data:source", required=False, description="上游数据源引用（可选）"),
    ],
    "outputs": [
        _port("path", "value:string", description="本地落盘路径"),
        _port("manifest", "data", description="产物清单"),
    ],
    "params": [
        _param("server_type", "string", default="hpc", options=["hpc", "win11", "nas"], description="服务器类型"),
        _param("remote_path", "string", description="远程目录路径"),
        _param("local_path", "string", description="本地目标目录"),
        _param("start_date", "string", description="起始日期 YYYYMMDD（可选过滤）"),
        _param("end_date", "string", description="结束日期 YYYYMMDD（可选过滤）"),
        _param("file_filter", "string", description="文件扩展名过滤（如 .mat,.h5）"),
        _param("max_depth", "number", default=4, min_val=1, max_val=10, step=1, description="最大递归深度"),
    ],
    "node_class": "ssh_sync",
}
```

#### 1c. `download/nsidc_smap_download`（NSIDC 下载节点）

```python
{
    "type": "download/nsidc_smap_download",
    "engine": "common",
    "category": "数据获取与解析",
    "title": "NSIDC SMAP 下载",
    "description": "从 NASA NSIDC 下载 SMAP L3 SPL3SMP_E V6 土壤湿度数据。支持日期范围、增量下载、earthaccess 认证。",
    "inputs": [],
    "outputs": [
        _port("path", "value:string", description="本地落盘目录"),
        _port("manifest", "data", description="产物清单"),
    ],
    "params": [
        _param("start_date", "string", description="起始日期 YYYYMMDD"),
        _param("end_date", "string", description="结束日期 YYYYMMDD"),
        _param("local_path", "string", description="本地目标目录"),
        _param("version", "string", default="6", options=["5", "6"], description="产品版本"),
    ],
    "node_class": "nsidc_smap_download",
}
```

#### 1d. `download/fy_preprocess`（FY 预处理节点）

```python
{
    "type": "download/fy_preprocess",
    "engine": "common",
    "category": "数据获取与解析",
    "title": "FY 亮温预处理",
    "description": "FY-3B/3D MWRI HDF 亮温预处理：geolocation 校正、日内轨道拼接、多通道合并、重投影。",
    "inputs": [
        _port("data", "data:source", required=False, description="上游数据源（可选）"),
    ],
    "outputs": [
        _port("path", "value:string", description="输出目录"),
        _port("manifest", "data", description="产物清单"),
    ],
    "params": [
        _param("satellite", "string", default="FY3D", options=["FY3D", "FY3B"], description="卫星"),
        _param("input_dir", "string", description="HDF 输入目录"),
        _param("output_dir", "string", description="输出目录"),
        _param("start_date", "string", description="起始日期 YYYYMMDD"),
        _param("end_date", "string", description="结束日期 YYYYMMDD"),
        _param("orbit_mode", "string", default="MWRID", options=["MWRID", "MWRIA", "Both"], description="轨道模式"),
        _param("outfile_type", "string", default="HDF5", options=["GTiff", "NetCDF", "HDF5"], description="输出格式"),
    ],
    "node_class": "fy_preprocess",
}
```

**验证**：`python -c "from app.services.node_template_registry import get_node_template; assert get_node_template('module/omega_sf_fenkuai') is not None; assert get_node_template('download/ssh_sync') is not None"`

---

### Part 2：后端配置补充（Part E1）

**文件**：`Code/backend/app/core/config.py` + `Code/backend/.env`

#### config.py 新增字段

在 `Settings` dataclass 中新增：

```python
# ── SSH 远程同步 ──
ssh_hpc_host: str = "127.0.0.1"
ssh_hpc_port: int = 2222
ssh_hpc_user: str = "likr6008"
ssh_hpc_key_path: str = "~/.ssh/seahpc_key"
ssh_win11_alias: str = "win11-lab"
ssh_win11_user: str = "qiujianqiu"

# ── Earthdata 凭据 ──
earthdata_username: str = ""
earthdata_password: str = ""

# ── FileBrowser ──
filebrowser_nas_url: str = "https://nasfile.personaltunnel.dpdns.org"
filebrowser_win11_url: str = "https://win11file.personaltunnel.dpdns.org"
filebrowser_user: str = "user"
filebrowser_password: str = ""
```

#### .env 新增变量

```env
# ---- SSH 远程同步 ----
BACKEND_SSH_HPC_HOST=127.0.0.1
BACKEND_SSH_HPC_PORT=2222
BACKEND_SSH_HPC_USER=likr6008
BACKEND_SSH_HPC_KEY_PATH=~/.ssh/seahsc_key
BACKEND_SSH_WIN11_ALIAS=win11-lab
BACKEND_SSH_WIN11_USER=qiujianqiu

# ---- Earthdata 凭据 ----
BACKEND_EARTHDATA_USERNAME=Rejoyce
BACKEND_EARTHDATA_PASSWORD=Diandian143

# ---- FileBrowser ----
BACKEND_FILEBROWSER_NAS_URL=https://nasfile.personaltunnel.dpdns.org
BACKEND_FILEBROWSER_WIN11_URL=https://win11file.personaltunnel.dpdns.org
BACKEND_FILEBROWSER_USER=user
BACKEND_FILEBROWSER_PASSWORD=remotefangwen123
```

**注意**：`config.py` 的 Settings 加载器需将 `BACKEND_` 前缀的环境变量映射到对应字段。需确认现有加载逻辑是否自动剥离 `BACKEND_` 前缀；若不是，需手动添加映射。

---

### Part 3：远程文件浏览 API（Part E2）

**文件**：
- `Code/backend/app/api/routers/remote_browser_router.py`（新建）
- `Code/backend/app/api/routers/__init__.py`（注册）

#### 端点设计

```
GET /api/remote/list?server=hpc&path=/public/shared_data
  → { "items": [{ "name": "...", "isDir": true, "size": 0 }, ...] }

GET /api/remote/test?server=hpc
  → { "ok": true, "server": "hpc", "latency_ms": 120 }
```

#### 实现逻辑

1. 根据 `server` 参数解析目标类型（hpc/win11/nas）
2. hpc/win11 → SFTP `listdir`（复用 `ingest.remote_sync._sftp_connect` + `_sftp_list_dir`）
3. nas → FileBrowser REST API `GET /api/resources/{path}`（复用 `ingest.remote_sync.filebrowser_login` + `_filebrowser_list_dir`）
4. 返回统一格式 `{ items: [{ name, isDir, size }] }`
5. 认证信息从 `settings`（Part 2 配置）注入，不暴露给前端

**鉴权**：该端点需 `X-API-Key`（与 `/config/*` 写操作一致），development 模式可旁路。

---

### Part 4：工作流种子创建（Part C）

**文件**：`Code/backend/workflow_seeds/system/`

#### 4a. `omega_sf_fenkuai_fy_single.json`

节点链路（LiteGraph 格式）：

```
[data_source: SMAP]          [data_source: FY3D]          [data_source: NDVI_clim]
       ↓                            ↓                            ↓
[data_source: anc_root]      [data_source: ndvi_folder]    [data_source: gldas_mat]
       ↘                            ↓                            ↙
                    [module/omega_sf_fenkuai]
                              ↓ manifest
```

关键 properties：
- 6 个 `data/source` 节点，path 指向 I 盘 12 类目录结构下的子路径
- 1 个 `module/omega_sf_fenkuai` 节点，algorithm_params 含 tb_source=FY, fy_platform=3D, sf_mode=INVERTED_DAILY 等
- links 将所有 data_source 的输出连接到算法节点的输入端口

algorithm_params（镜像 Matlab CFG 默认值）：
```json
{
  "tb_source": "FY",
  "fy_platform": "3D",
  "sm_source": "SMAP",
  "sf_mode": "INVERTED_DAILY",
  "sf_invert_mode": "POINT1",
  "ndvi_mode": "DOY_CLIM",
  "temp_scheme": "ORIG_TS",
  "omega_fixed_mode": "PFT",
  "match_enable": true,
  "match_method": "bias",
  "block_days": 8,
  "start_date": "20250101",
  "end_date": "20251231",
  "enable_parallel": true,
  "pixel_chunk_size": 200000
}
```

#### 4b. `omega_sf_fenkuai_smap_single.json`

与 4a 类似，但：
- `tb_source="SMAP"`，无需 FY3D/FY3B 节点
- 增加 `nsidc_smap_download` 可选节点（用户可选择本地已有或远程下载）
- algorithm_params 中 `freq_ghz=1.4`

#### 种子 _meta 结构

```json
{
  "_meta": {
    "kind": "system",
    "engine": "python_provider",
    "name": "SF 块反演全流程（FY 单温度）",
    "description": "...",
    "author": "system",
    "readonly": true,
    "is_template": true,
    "linked_layer_id": "omega-sf-fenkuai",
    "tags": ["pipeline", "sf_inversion"]
  }
}
```

**注意**：`linked_layer_id` 需在 `overlay_registry.py` 或等效图层注册表中预注册 `omega-sf-fenkuai` 图层条目。

---

### Part 5：前端完善

#### 5a. 下载节点参数 UI（D1）

**新建文件**：
- `Code/frontend/src/components/workflow/node-forms/DownloadNodeForm.vue` — 统一下载节点表单入口
- `Code/frontend/src/components/workflow/node-forms/SshSyncForm.vue` — SSH 同步专用表单
- `Code/frontend/src/components/workflow/node-forms/NsidcDownloadForm.vue` — NSIDC 下载专用表单
- `Code/frontend/src/components/workflow/node-forms/FyPreprocessForm.vue` — FY 预处理专用表单

**修改文件**：
- `Code/frontend/src/components/workflow/WorkflowInspector.vue` — 按节点 type 前缀分支渲染

**SshSyncForm.vue 关键交互**：
1. 服务器选择下拉（HPC / Win11 / NAS），选择后自动填充 host/port/user 默认值
2. 远程路径输入框 + "浏览"按钮 → 调用 `GET /api/remote/list?server=hpc&path=...` → 弹出目录树对话框
3. 本地路径输入（默认 `I:\Geograph_DataSet\...`，可手动修改）
4. 日期范围选择器（el-date-picker，YYYYMMDD 格式）
5. 文件过滤多选（.mat / .h5 / .nc / .tif / .txt）
6. 表单值变更时写回 `node.properties`

**WorkflowInspector.vue 修改**：
- 在 `groupedProperties` computed 之前增加 `specializedForm` computed
- 若 `node.type` 以 `download/` 开头，渲染 `<DownloadNodeForm>` 替代通用 ParamField 列表
- 若 `node.type` 以 `module/omega_sf_fenkuai` 开头，保持通用 ParamField（已有足够 params 定义）

**NodePalette 分类**：
- `WorkflowNodePalette.vue` 的 `CATEGORY_ICONS` 增加 `下载` 分类映射（已有的 "数据获取与解析" 可复用，无需新增分类）

#### 5b. 一键流水线入口（D2）

**新建文件**：
- `Code/frontend/src/components/workflow/PipelineLauncher.vue`

**修改文件**：
- `Code/frontend/src/components/workflow/WorkflowEditorPanel.vue` — 工具栏增加"流水线"按钮

**PipelineLauncher.vue 设计**：
1. 弹出对话框（el-dialog），标题"端到端流水线"
2. 展示预置流水线卡片列表（从 `/api/workflow-definitions` 过滤 `tags` 含 `pipeline` 的种子）
3. 每张卡片含：名称、描述、节点链路缩略图（SVG）、"启动"按钮
4. 点击"启动"后：
   - 读取种子 JSON（含 nodes/links）
   - 弹出轻量参数面板（仅显示 start_date / end_date / 数据源选择，可折叠高级参数）
   - 用户确认后调用 `compileWorkflowGraph` → `POST /workflow-runs`
   - 自动关闭对话框，打开 `WorkflowStatusPanel`
5. 不经过 `WorkflowRunDialog`（流水线模式自动创建新产出图层）

**WorkflowEditorPanel.vue 修改**：
- 在 `header-actions` 区域，"运行"按钮左侧增加"流水线"按钮（图标 🚀）
- 点击后 `emit('launch-pipeline')` 或直接渲染 `<PipelineLauncher>`
- `PipelineLauncher` 内部自行处理提交逻辑（复用 Dashboard 的 `submitWorkflowRun` 方法）

#### 5c. 运行进度增强（D3）

**修改文件**：
- `Code/frontend/src/stores/layers/types.ts` — `JobLayerItem` 增加 `nodeProgress` 字段
- `Code/frontend/src/stores/layers/index.ts` — `applyWorkflowEventsToJobLayer` 解析节点级事件
- `Code/frontend/src/components/workflow/WorkflowStatusPanel.vue` — 渲染节点级进度

**类型扩展**：
```typescript
// types.ts
interface NodeProgress {
  nodeId: string;
  nodeLabel: string;
  stage: string;        // "download" | "preprocess" | "inversion" | "output"
  progress: number;     // 0-100
  message?: string;
  artifacts?: string[]; // 产物路径列表
}

interface JobLayerItem {
  // ... 现有字段
  nodeProgress?: NodeProgress[];  // 新增
}
```

**事件解析**：
```typescript
// index.ts applyWorkflowEventsToJobLayer
// 解析 event.payload.node_progress（后端发送的节点级进度）
if (event.payload?.node_progress) {
  const np = event.payload.node_progress;
  const existing = nextNodeProgress.find(p => p.nodeId === np.node_id);
  if (existing) {
    Object.assign(existing, { stage: np.stage, progress: np.progress, message: np.message });
  } else {
    nextNodeProgress.push({ nodeId: np.node_id, nodeLabel: np.node_label, ... });
  }
}
```

**状态面板渲染**：
- 在 `JobLayerItem` 的展开区域（`diagnosticNotes` 下方）增加"节点进度"区块
- 每个节点一行：节点名 + 阶段标签 + 进度条 + 当前消息
- 下载阶段节点显示"已下载/总文件数"（从 `artifacts` 推断）

**后端配合**（可选，本次可先做前端预留）：
- `python_provider_bridge_service.py` 在执行 download_nodes 时发送 `node_progress` 事件
- 事件 payload 格式：`{ node_id, node_label, stage, progress, message, artifacts }`

#### 5d. 三图层自动生成（D4）

**修改文件**：
- `Code/frontend/src/components/workflow/WorkflowRunDialog.vue` — 多输出检测与选项
- `Code/frontend/src/stores/workflow-output-layers.ts` — 批量创建
- `Code/frontend/src/components/workflow/WorkflowEditorPanel.vue` — `handleRunConfirm` 适配多目标

**WorkflowRunDialog.vue 修改**：
1. 新增 computed `outputCount`：检测工作流定义中 `module/omega_sf_fenkuai` 节点的输出数量
   - 从 `store.nodeTemplates` 查到节点模板的 `outputs` 数组
   - 若算法节点声明 3 个输出（SM/VOD/OMEGA），`outputCount = 3`
2. 当 `outputCount > 1` 时，运行模式增加第三个选项 `multi`：
   - `default` — 覆盖上次（单图层，现有逻辑）
   - `new` — 新建单图层（现有逻辑）
   - `multi` — **自动生成 N 个图层**（N = outputCount）
3. `multi` 模式下显示：
   - 自动生成的图层名称列表（如 "omega_sf_fenkuai_SM"、"omega_sf_fenkuai_VOD"、"omega_sf_fenkuai_OMEGA"）
   - 每个图层可编辑名称 + 选择/新建分组
   - 一个"全部使用相同分组"复选框（默认勾选）
4. `WorkflowRunTarget` 接口扩展：
```typescript
interface WorkflowRunTarget {
  mode: 'default' | 'new' | 'multi';
  name?: string;
  group?: string;
  targets?: Array<{ name: string; group: string }>;  // multi 模式
}
```

**workflow-output-layers.ts 修改**：
- 新增 `createOutputLayers(targets: Array<{name, group}>, sourceLayerId: string): WorkflowOutputLayerEntry[]`
- 批量创建逻辑与现有 `createOutputLayer` 一致，循环调用

**后端配合**：
- `result_builder.py` 或 `python_provider_bridge_service.py` 在处理 omega_sf_fenkuai 的 `ProductManifest` 时，为每个 `ProductRef`（SM/VOD/OMEGA）生成独立 `WorkflowResultReference`
- 每个 result_ref 的 `title` 必须为 US-ASCII（如 "SM"、"VOD"、"OMEGA"）
- 前端收到多个 `map_layer` 类型的 result_refs 后，依次创建 jobLayer 并叠加

---

### Part 6：验证

#### 后端验证

```bash
# 1. 节点模板注册
cd Code/backend
python -c "from app.services.node_template_registry import get_all_node_templates; types = [t['type'] for t in get_all_node_templates()]; assert 'module/omega_sf_fenkuai' in types; assert 'download/ssh_sync' in types; assert 'download/nsidc_smap_download' in types; assert 'download/fy_preprocess' in types; print('OK')"

# 2. 工作流编译
pytest tests/test_workflow_graph_compiler.py -q

# 3. 工作流路由 + 业务回归
pytest tests/test_workflow_routes.py tests/test_interaction_hub.py tests/test_business_regression.py -q

# 4. 远程浏览 API（需启动 FastAPI）
python launch.py start fastapi
curl "http://127.0.0.1:8000/api/remote/test?server=hpc"
curl "http://127.0.0.1:8000/api/remote/list?server=hpc&path=/public/shared_data"
```

#### 前端验证

```bash
cd Code/frontend
npm run test -- download-node-form pipeline-launcher workflow-status-panel workflow-run-dialog
npm run lint
npm run build
npm run check:openapi
```

#### 端到端集成

1. `python launch.py start`（全栈启动）
2. 前端打开工作流编辑器 → 点击"流水线"按钮
3. 选择"FY-3D SF 块反演全流程"模板
4. 设置数据范围（如 2025-01-01 ~ 2025-01-08，1 个块用于测试）
5. 选择数据源：本地已有 / SSH 同步 / NSIDC 下载
6. 点击"启动"
7. 观察 WorkflowStatusPanel：
   - 下载阶段进度（若选择了远程下载）
   - 反演阶段节点级进度
8. 验证地图上自动叠加 3 个图层（SM / VOD / OMEGA）
9. 在图层面板中验证 3 个图层分组显示

---

## 实施顺序与依赖

```
Part 1 (节点模板) ──────┐
                        ├──→ Part 4 (工作流种子) ──→ Part 5b (一键入口)
Part 2 (后端配置) ──┐   │                              │
                    ├──→ Part 3 (远程浏览 API) ──→ Part 5a (下载节点 UI)
                    │                              │
                    └──────────────────────────────┤
                                                   ├──→ Part 6 (验证)
Part 5c (进度增强) ────────────────────────────────┤
Part 5d (三图层自动生成) ──────────────────────────┘
```

**并行策略**：
- Part 1 + Part 2 可并行（后端不同文件）
- Part 3 依赖 Part 2（需配置注入凭据）
- Part 4 依赖 Part 1（种子引用节点 type）
- Part 5a 依赖 Part 3（表单需调用远程浏览 API）
- Part 5b 依赖 Part 4（launcher 需读取种子列表）
- Part 5c / Part 5d 可与 Part 5a / 5b 并行（不同组件）

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| `omega_sf_fenkuai` 算法运行时依赖大量 .mat 辅助数据，本地可能缺失 | 种子中 data_source 节点标注 "需先运行 D1 omega_block 或手动准备数据"；提供 `ssh_sync` 节点可选下载 |
| NSIDC 下载受网络/凭据限制 | `nsidc_smap_download` 节点设计为可选；种子中默认使用本地数据路径 |
| FY 预处理依赖 GDAL 可执行文件 | `fy_preprocess.py` 已实现 `_resolve_gdal_bins()` 延迟定位；种子中 FY 节点为可选 |
| 前端多输出机制改动较大 | 分两阶段：先支持 `mode: 'multi'` 的 UI（D4），后端 result_builder 多 result_ref 可后续迭代 |
| `config.py` 环境变量映射可能不自动剥离 `BACKEND_` 前缀 | 需检查 `Settings` 的 `__post_init__` / `from_env` 逻辑，必要时手动添加字段映射 |
| SSH 密钥可能在测试期间过期（2026-08-23） | 远程浏览 API 的 `test` 端点会返回连接状态；前端表单显示连接状态指示器 |
