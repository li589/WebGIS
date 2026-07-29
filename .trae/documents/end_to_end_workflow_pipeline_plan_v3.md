# 端到端工作流流水线实施计划 v3

## 当前状态

### 已完成部件（验证通过）

| 部件 | 文件 | 验证方式 |
|------|------|----------|
| 算法核心 `omega_sf.py` | `algorithms/providers/Python/algorithms/omega_sf.py` | 语法编译通过 |
| 模块注册 `omega_sf_fenkuai.py` | `algorithms/providers/Python/modules/omega_sf_fenkuai.py` | 语法编译通过，3 输出（SM/VOD/OMEGA） |
| 请求模板 | `contracts/request_templates.py` | 手动 RequestTemplateSpec 已添加 |
| SSH 同步模块 | `ingest/remote_sync.py` | 608 行，SFTP/FileBrowser 双路径 |
| NSIDC 下载模块 | `ingest/nsidc_download.py` | 620 行，earthaccess + HTTP Basic 回退 |
| FY 预处理模块 | `ingest/fy_preprocess.py` | 947 行，FySatelliteConfig 参数化 |
| 下载节点注册 | `modules/download_nodes.py` | 3 节点：ssh_sync / nsidc_smap_download / fy_preprocess |
| **Part 1: 节点模板** | `node_template_registry.py` | 4 模板已注册（L266/321/346/2107） |
| **Part 2: 后端配置** | `config.py` + `.env` | SSH/Earthdata/FileBrowser 字段已添加 |
| **Part 3: 远程浏览 API** | `remote_browser_router.py` | `/api/remote/list` + `/api/remote/test`，已注册到 main.py |

### 待实施部件

---

## Part 4：工作流种子创建

**目标**：创建 2 个系统工作流种子，将 omega_sf_fenkuai 算法节点与数据源节点编排为可运行流水线。

### 4a. `omega_sf_fenkuai_fy_single.json`（FY 单温度全流程）

**文件**：`Code/backend/workflow_seeds/system/omega_sf_fenkuai_fy_single.json`

**节点拓扑**（7 个节点）：

```
[data_source: SMAP]  [data_source: anc_root]  [data_source: FY3D_TB]
       ↓                    ↓                        ↓
[data_source: FY3B_TB] [data_source: NDVI_clim] [data_source: gldas_mat]
       ↘                    ↓                        ↙
                    [module/omega_sf_fenkuai]
                              ↓ manifest
```

**数据源节点 properties**（path 基于 I 盘 12 类目录结构）：

| 节点 ID | dataset_key | path | 说明 |
|---------|-------------|------|------|
| 1 | smap_folder | Soil_Moisture/SMAP_Origin_Data | 逐日 SMAP .mat（TBv/TBh/IA/Ts/vwc/SM） |
| 2 | anc_root | SMAP_ancillary | 静态辅助库（IGBP_9km_12/Albedo/B/BD/CF/H/SF） |
| 3 | fy3d_folder | Soil_Moisture/FY3D_TB | 逐日 FY3D TB .mat |
| 4 | fy3b_folder | Soil_Moisture/FY3B_TB | 逐日 FY3B TB .mat（FY3B→FY3D 匹配用） |
| 5 | ndvi_clim_folder | Ecological_Vegetation/NDVI/climatology | NDVI DOY 气候态 |
| 6 | gldas_mat_folder | Meteorological/Weather/GLDAS | GLDAS 温度数据（DUAL 方案用） |

**算法节点 properties**：

```json
{
  "module_name": "omega_sf_fenkuai",
  "task_type": "omega_sf_fenkuai",
  "algorithm_params": {
    "tb_source": "FY",
    "fy_platform": "3D",
    "sm_source": "SMAP",
    "temp_scheme": "ORIG_TS",
    "sf_mode": "INVERTED_DAILY",
    "sf_invert_mode": "POINT1",
    "ndvi_mode": "DOY_CLIM",
    "omega_fixed_mode": "PFT",
    "match_enable": true,
    "match_method": "bias",
    "block_days": 8,
    "start_date": "20250101",
    "end_date": "20251231",
    "enable_parallel": true,
    "pixel_chunk_size": 200000
  }
}
```

**links**：6 个 data_source 节点的输出全部连接到算法节点的 `datasource_selection` 输入端口（slot 0）。

**_meta**：
```json
{
  "kind": "system",
  "engine": "python_provider",
  "name": "SF 块反演全流程（FY 单温度）",
  "description": "omega_sf_fenkuai 完整流水线：FY3D/FY3B 亮温 + SMAP 辅助 → 8-day 分块 → SF 倒推 → 块级 h/alpha/OMEGA 优化 → DDCA SM/VOD 反演。输出 SM/VOD/OMEGA 三图层。",
  "author": "system",
  "readonly": true,
  "is_template": true,
  "linked_layer_id": "omega-sf-fenkuai",
  "tags": ["pipeline", "sf_inversion"]
}
```

### 4b. `omega_sf_fenkuai_smap_single.json`（SMAP 单温度全流程）

**文件**：`Code/backend/workflow_seeds/system/omega_sf_fenkuai_smap_single.json`

**节点拓扑**（4 个节点）：

```
[data_source: SMAP]  [data_source: anc_root]  [data_source: NDVI_clim]
       ↘                    ↓                        ↙
                    [module/omega_sf_fenkuai]
                              ↓ manifest
```

**与 4a 的差异**：
- `tb_source="SMAP"`，无 FY3D/FY3B 节点
- `algorithm_params.freq_ghz=1.4`（L波段）
- 无 `match_enable` / `match_method` 参数
- 节点数更少（4 → 3 个 data_source + 1 个算法节点）

### 4c. 图层注册（可选，本次预埋）

**文件**：`Code/backend/app/services/overlay_registry.py`

需在 `_build_overlays()` 中预注册 `omega-sf-fenkuai` 图层条目，或在工作流运行后动态注册。本次先在种子的 `linked_layer_id` 中声明，实际图层注册可在首次运行后由 result_builder 自动完成。

**验证命令**：
```bash
cd Code/backend
pytest tests/test_workflow_graph_compiler.py -q
# 验证种子 JSON 可被编译器解析
python -c "import json; d=json.load(open('workflow_seeds/system/omega_sf_fenkuai_fy_single.json')); assert d['workflow_id']=='omega_sf_fenkuai_fy_single'; print('OK')"
```

---

## Part 5a：下载节点参数 UI

**目标**：为 `download/ssh_sync`、`download/nsidc_smap_download`、`download/fy_preprocess` 三类节点提供专用参数表单，支持远程目录浏览。

### 新建文件

| 文件 | 职责 |
|------|------|
| `node-forms/DownloadNodeForm.vue` | 统一入口，按 `node.type` 分发到子表单 |
| `node-forms/SshSyncForm.vue` | SSH 同步专用表单（服务器选择 + 远程浏览 + 日期范围） |
| `node-forms/NsidcDownloadForm.vue` | NSIDC 下载专用表单（日期范围 + 版本 + 本地路径） |
| `node-forms/FyPreprocessForm.vue` | FY 预处理专用表单（卫星选择 + 轨道模式 + 输出格式） |
| `node-forms/RemoteDirBrowser.vue` | 远程目录浏览对话框组件 |

### SshSyncForm.vue 关键交互

1. **服务器选择**：下拉框（HPC / Win11 / NAS），选择后自动填充 host/port/user 默认值
2. **远程路径**：输入框 + "浏览"按钮
   - 点击"浏览" → 调用 `GET /api/remote/list?server=hpc&path=...`
   - 弹出 `RemoteDirBrowser` 对话框，显示目录树
   - 双击目录进入，单击选中，"确定"后回填路径
3. **本地路径**：输入框，默认 `I:\Geograph_DataSet\...`（可手动修改）
4. **日期范围**：两个日期输入框（YYYYMMDD 格式），可选
5. **文件过滤**：多选标签（.mat / .h5 / .nc / .tif / .txt）
6. **连接状态指示器**：调用 `GET /api/remote/test?server=hpc` 显示绿/红灯

### RemoteDirBrowser.vue 设计

```
┌─ 远程目录浏览 ──────────────────────┐
│ 路径: /public/shared_data/          │
│ ┌─────────────────────────────────┐ │
│ │ 📁 Chenhaojun/                  │ │
│ │ 📁 FY3D_output/                 │ │
│ │ 📁 SMAP_data/                   │ │
│ │ 📄 readme.txt                   │ │
│ └─────────────────────────────────┘ │
│ [↑ 上级]  [确定]  [取消]            │
└─────────────────────────────────────┘
```

### 修改 WorkflowInspector.vue

在 `<template>` 的"自定义属性"区域之前插入分支：

```vue
<!-- 下载节点专用表单 -->
<DownloadNodeForm
  v-if="selectedNode?.type?.startsWith('download/')"
  :node="selectedNode"
  :readonly="readonly"
  @update-property="handlePropertyChange"
/>
<!-- 通用属性（非下载节点） -->
<section v-else-if="Object.keys(localProperties).length" class="inspector-section">
  ...
</section>
```

**验证命令**：
```bash
cd Code/frontend
npm run test -- download-node-form
npm run lint
```

---

## Part 5b：一键流水线入口

**目标**：在工作流编辑器工具栏增加"流水线"按钮，弹出预置流水线选择器，用户选择后一键启动。

### 新建文件

| 文件 | 职责 |
|------|------|
| `PipelineLauncher.vue` | 流水线启动器对话框 |

### PipelineLauncher.vue 设计

```
┌─ 端到端流水线 ─────────────────────────────┐
│                                            │
│  ┌─ SF 块反演全流程（FY 单温度）─────────┐  │
│  │ FY3D/FY3B → SMAP → SF倒推 → 3图层   │  │
│  │ [SM] [VOD] [OMEGA]                   │  │
│  │                          [启动 →]    │  │
│  └─────────────────────────────────────┘  │
│                                            │
│  ┌─ SF 块反演全流程（SMAP 单温度）─────┐  │
│  │ SMAP TB → SF倒推 → 3图层            │  │
│  │ [SM] [VOD] [OMEGA]                   │  │
│  │                          [启动 →]    │  │
│  └─────────────────────────────────────┘  │
│                                            │
└────────────────────────────────────────────┘
```

**交互流程**：
1. 从 `/api/workflow-definitions` 过滤 `tags` 含 `pipeline` 的种子
2. 每张卡片展示名称、描述、输出图层标签
3. 点击"启动"后：
   - 弹出轻量参数面板（仅 start_date / end_date / 数据范围选择）
   - 用户确认后调用 `compileWorkflowGraph` → `POST /workflow-runs`
   - 自动关闭对话框，打开 `WorkflowStatusPanel`
4. 不经过 `WorkflowRunDialog`（流水线模式自动创建新产出图层）

### 修改 WorkflowEditorPanel.vue

在 `header-actions` 区域，"运行"按钮左侧增加"流水线"按钮：

```vue
<button class="header-btn pipeline" @click="showPipelineLauncher = true" title="端到端流水线">
  <span aria-hidden="true">🚀</span>
  <span>流水线</span>
</button>
```

在 `<template>` 底部增加：

```vue
<PipelineLauncher
  v-if="showPipelineLauncher"
  @close="showPipelineLauncher = false"
  @launch="handlePipelineLaunch"
/>
```

**验证命令**：
```bash
cd Code/frontend
npm run test -- pipeline-launcher
npm run lint
```

---

## Part 5c：运行进度增强

**目标**：在状态面板中展示节点级进度（下载阶段 / 预处理阶段 / 反演阶段），而非仅整体进度条。

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `stores/layers/types.ts` | `JobLayerItem` 增加 `nodeProgress` 字段 |
| `stores/layers/index.ts` | `applyWorkflowEventsToJobLayer` 解析 `node_progress` 事件 |
| `components/workflow/WorkflowStatusPanel.vue` | 渲染节点级进度区块 |

### 类型扩展

```typescript
// types.ts
interface NodeProgress {
  nodeId: string;
  nodeLabel: string;
  stage: string;        // "download" | "preprocess" | "inversion" | "output"
  progress: number;     // 0-100
  message?: string;
  artifacts?: string[];
}

interface JobLayerItem {
  // ... 现有字段
  nodeProgress?: NodeProgress[];  // 新增
}
```

### 事件解析

后端 `python_provider_bridge_service.py` 在执行 download_nodes 和 omega_sf_fenkuai 时，通过 `logger_adapter.emit_progress()` 发送进度事件。前端需解析事件 payload 中的 `node_progress` 字段：

```typescript
if (event.payload?.node_progress) {
  const np = event.payload.node_progress;
  const existing = nextNodeProgress.find(p => p.nodeId === np.node_id);
  if (existing) {
    Object.assign(existing, { stage: np.stage, progress: np.progress, message: np.message });
  } else {
    nextNodeProgress.push({
      nodeId: np.node_id,
      nodeLabel: np.node_label,
      stage: np.stage,
      progress: np.progress,
      message: np.message,
    });
  }
}
```

### 状态面板渲染

在 `JobLayerItem` 展开区域（`diagnosticNotes` 下方）增加"节点进度"区块：

```
┌─ 节点进度 ─────────────────────────┐
│ 📥 SSH 同步        [████████░░] 80% │
│    已下载 24/30 文件               │
│ ⚙ FY 预处理        [██████████] 100%│
│    处理完成 8 天                   │
│ 🔬 SF 块反演       [██░░░░░░░░] 20% │
│    像元 40000/200000               │
└────────────────────────────────────┘
```

**验证命令**：
```bash
cd Code/frontend
npm run test -- workflow-status-panel
```

---

## Part 5d：三图层自动生成

**目标**：当工作流包含 `module/omega_sf_fenkuai` 节点（3 个输出）时，运行对话框自动提供"多图层"模式，一次运行生成 SM / VOD / OMEGA 三个独立图层。

### 修改 WorkflowRunDialog.vue

1. **新增 computed `outputCount`**：检测工作流定义中 `module/omega_sf_fenkuai` 节点的输出数量
   - 从 `store.nodeTemplates` 查到节点模板的 `outputs` 数组
   - 若算法节点声明 3 个输出（SM/VOD/OMEGA），`outputCount = 3`

2. **运行模式增加第三个选项 `multi`**：
   - `default` — 覆盖上次（单图层，现有逻辑）
   - `new` — 新建单图层（现有逻辑）
   - `multi` — **自动生成 N 个图层**（N = outputCount）

3. **`multi` 模式 UI**：
   - 自动生成的图层名称列表（如 "omega_sf_fenkuai_SM"、"omega_sf_fenkuai_VOD"、"omega_sf_fenkuai_OMEGA"）
   - 每个图层可编辑名称 + 选择/新建分组
   - "全部使用相同分组"复选框（默认勾选）

4. **`WorkflowRunTarget` 接口扩展**：
```typescript
interface WorkflowRunTarget {
  mode: 'default' | 'new' | 'multi';
  name?: string;
  group?: string;
  targets?: Array<{ name: string; group: string }>;  // multi 模式
}
```

### 修改 workflow-output-layers.ts

新增 `createOutputLayers` 批量创建方法：

```typescript
function createOutputLayers(
  targets: Array<{ name: string; group: string }>,
  sourceLayerId: string
): WorkflowOutputLayerEntry[] {
  return targets.map(t => createOutputLayer(t.name, t.group, sourceLayerId));
}
```

### 修改 WorkflowEditorPanel.vue

`handleRunConfirm` 适配多目标：

```typescript
function handleRunConfirm(target: WorkflowRunTarget) {
  // ... 现有逻辑
  if (target.mode === 'multi' && target.targets) {
    // 批量创建输出图层
    outputStore.createOutputLayers(target.targets, linkedLayerId);
  }
  emit('run', workflowId, linkedLayerId, target, graphData);
}
```

### 后端配合

`python_provider_bridge_service.py` 在处理 omega_sf_fenkuai 的 `ProductManifest` 时，为每个 `ProductRef`（SM/VOD/OMEGA）生成独立 `WorkflowResultReference`：
- 每个 result_ref 的 `title` 必须为 US-ASCII（如 "SM"、"VOD"、"OMEGA"）
- 前端收到多个 `map_layer` 类型的 result_refs 后，依次创建 jobLayer 并叠加

**验证命令**：
```bash
cd Code/frontend
npm run test -- workflow-run-dialog
npm run lint
```

---

## Part 6：验证

### 后端验证

```bash
# 1. 节点模板注册（已验证）
cd Code/backend
python -c "from app.services.node_template_registry import get_all_node_templates; types = [t['type'] for t in get_all_node_templates()]; assert 'module/omega_sf_fenkuai' in types; assert 'download/ssh_sync' in types; print('OK')"

# 2. 工作流种子编译
pytest tests/test_workflow_graph_compiler.py -q

# 3. 工作流路由 + 业务回归
pytest tests/test_workflow_routes.py tests/test_interaction_hub.py tests/test_business_regression.py -q

# 4. 远程浏览 API（需启动 FastAPI）
python launch.py start fastapi
curl "http://127.0.0.1:8000/api/remote/test?server=hpc"
curl "http://127.0.0.1:8000/api/remote/list?server=hpc&path=/public/shared_data"
```

### 前端验证

```bash
cd Code/frontend
npm run test -- download-node-form pipeline-launcher workflow-status-panel workflow-run-dialog
npm run lint
npm run build
npm run check:openapi
```

### 端到端集成

1. `python launch.py start`（全栈启动）
2. 前端打开工作流编辑器 → 点击"流水线"按钮
3. 选择"SF 块反演全流程（FY 单温度）"模板
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
Part 4 (工作流种子) ──────┬──→ Part 5b (一键入口)
                          │
Part 3 (远程浏览 API) ────┴──→ Part 5a (下载节点 UI)
                                    │
Part 5c (进度增强) ─────────────────┤
                                    │
Part 5d (三图层自动生成) ───────────┤
                                    │
                                    └──→ Part 6 (验证)
```

**并行策略**：
- Part 4 可立即开始（后端独立文件）
- Part 5a 依赖 Part 3（已完成，可立即开始）
- Part 5b 依赖 Part 4（种子需先创建）
- Part 5c / Part 5d 可与 Part 5a / 5b 并行（不同组件）
- Part 6 在所有部件完成后执行

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| `omega_sf_fenkuai` 算法运行时依赖大量 .mat 辅助数据，本地可能缺失 | 种子中 data_source 节点标注 "需先运行 D1 omega_block 或手动准备数据"；提供 `ssh_sync` 节点可选下载 |
| NSIDC 下载受网络/凭据限制 | `nsidc_smap_download` 节点设计为可选；种子中默认使用本地数据路径 |
| FY 预处理依赖 GDAL 可执行文件 | `fy_preprocess.py` 已实现 `_resolve_gdal_bins()` 延迟定位；种子中 FY 节点为可选 |
| 前端多输出机制改动较大 | 分两阶段：先支持 `mode: 'multi'` 的 UI（D4），后端 result_builder 多 result_ref 可后续迭代 |
| SSH 密钥可能在测试期间过期 | 远程浏览 API 的 `test` 端点会返回连接状态；前端表单显示连接状态指示器 |
| Celery metadata 不支持非 ASCII | 所有 `WorkflowResultReference.title` 和 `create_artifact_result_ref(title=...)` 必须为 US-ASCII |
