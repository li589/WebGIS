# 端到端工作流流水线实施计划 v4

## 总体目标

构建和执行工作流，实现自动远程数据拉取/下载、处理和显示，同时完善前端触发机制。本文档基于 v3 计划的已完成部件，聚焦剩余修复、验证与集成工作。

## 当前实现状态盘点

### 已完成部件（代码已存在，需验证）

| # | 部件 | 文件 | 状态 |
|---|------|------|------|
| A1 | 算法核心 `omega_sf.py` | `algorithms/providers/Python/algorithms/omega_sf.py` | 代码完成，语法编译通过 |
| A2 | 模块注册 `omega_sf_fenkuai.py` | `algorithms/providers/Python/modules/omega_sf_fenkuai.py` | 3 输出（SM/VOD/OMEGA） |
| A3 | 请求模板 | `contracts/request_templates.py` | 手动 RequestTemplateSpec 已添加 |
| A4 | SSH 同步模块 | `algorithms/providers/Python/ingest/remote_sync.py` | SFTP/FileBrowser 双路径 |
| A5 | NSIDC 下载模块 | `algorithms/providers/Python/ingest/nsidc_download.py` | earthaccess + HTTP Basic 回退 |
| A6 | FY 预处理模块 | `algorithms/providers/Python/ingest/fy_preprocess.py` | FySatelliteConfig 参数化 |
| A7 | 下载节点注册 | `algorithms/providers/Python/modules/download_nodes.py` | 3 节点已注册 |
| B1 | 节点模板（后端） | `app/services/node_template_registry.py` | 4 模板已注册（L266/321/346/2107） |
| B2 | 后端配置 | `app/core/config.py` + `.env` | SSH/Earthdata/FileBrowser 字段已添加 |
| B3 | 远程浏览 API | `app/api/routers/remote_browser_router.py` | `/api/remote/list` + `/api/remote/test`，已注册 |
| B4 | 工作流种子（FY） | `workflow_seeds/system/omega_sf_fenkuai_fy_single.json` | 7 节点，FY 单温度全流程 |
| B5 | 工作流种子（SMAP） | `workflow_seeds/system/omega_sf_fenkuai_smap_single.json` | 4 节点，SMAP 单温度全流程 |
| C1 | 下载节点表单入口 | `node-forms/DownloadNodeForm.vue` | 按 node.type 分发 |
| C2 | SSH 同步表单 | `node-forms/SshSyncForm.vue` | 服务器选择 + 远程浏览 + 日期范围 |
| C3 | NSIDC 下载表单 | `node-forms/NsidcDownloadForm.vue` | 日期范围 + 版本 + 本地路径 |
| C4 | FY 预处理表单 | `node-forms/FyPreprocessForm.vue` | 卫星选择 + 轨道模式 |
| C5 | 远程目录浏览器 | `node-forms/RemoteDirBrowser.vue` | 目录树浏览对话框 |
| C6 | WorkflowInspector 集成 | `WorkflowInspector.vue` | download/* 节点走专用表单 |
| C7 | 流水线启动器 | `PipelineLauncher.vue` | 卡片选择 + 日期参数 + 高级参数 |
| C8 | 编辑器流水线按钮 | `WorkflowEditorPanel.vue` | "流水线"按钮 + handlePipelineLaunch |
| C9 | 运行对话框多图层 | `WorkflowRunDialog.vue` | mode='multi' + 批量名称编辑 |
| C10 | 节点进度类型 | `stores/layers/types.ts` | NodeProgress 接口 + JobLayerItem.nodeProgress |
| C11 | 节点进度解析 | `stores/layers/index.ts` | applyWorkflowEventsToJobLayer 解析 node_progress |
| C12 | 节点进度渲染 | `WorkflowStatusPanel.vue` | STAGE_ICONS + 节点进度区块 |

### 存在的缺陷（需修复）

| # | 缺陷 | 位置 | 严重性 | 影响 |
|---|------|------|--------|------|
| D1 | `createOutputLayers` 方法不存在 | `stores/workflow-output-layers.ts` | **致命** | WorkflowEditorPanel.vue L286 调用了 `outputStore.createOutputLayers()`，但 store 中只有 `createOutputLayer`（单数），多图层模式会运行时报错 |
| D2 | 后端不转发 node_progress 事件 | `python_provider_bridge_service.py` | **高** | 算法模块调用 `ctx.logger_adapter.emit_progress()` 但 bridge service 的 execute() 只发 2 个高层事件（progress=74/95），前端 node_progress 解析逻辑永远不会触发 |
| D3 | LoggerAdapter 实现缺失 | bridge service 未实现 LoggerAdapter 接口 | **高** | dispatch.py 期望 LoggerAdapter 实例传入，但 bridge service 未提供实现，导致算法执行时 logger_adapter 可能为 None 或缺失 |

---

## Part 1：修复致命缺陷 D1 — createOutputLayers 方法

**目标**：在 `workflow-output-layers.ts` 中添加 `createOutputLayers` 批量创建方法，使 WorkflowEditorPanel 的 multi 模式能正常工作。

### 修改文件

`Code/frontend/src/stores/workflow-output-layers.ts`

### 修改内容

在 `createOutputLayer` 方法之后、`updateRunStatus` 之前，添加：

```typescript
/** 批量创建产出图层条目（multi 模式） */
function createOutputLayers(
  targets: Array<{ name: string; group: string }>,
  sourceWorkflowId: string,
  sourceLayerId: string,
  engine: string,
): WorkflowOutputLayerEntry[] {
  return targets.map((t) =>
    createOutputLayer({
      name: t.name,
      group: t.group,
      sourceWorkflowId,
      sourceLayerId,
      engine,
    }),
  )
}
```

在 store 的 return 对象中添加 `createOutputLayers`。

### 验证

```bash
cd Code/frontend
npm run lint -- src/stores/workflow-output-layers.ts
```

---

## Part 2：修复缺陷 D2+D3 — 后端 node_progress 事件转发

**目标**：让 bridge service 在执行算法期间，将算法模块内部的 `emit_stage_start` / `emit_progress` / `emit_stage_end` 调用转发为前端可解析的 `node_progress` 事件。

### 方案分析

bridge service 的 `execute()` 方法接收 `event_factory` 参数，用于创建事件。当前只在执行完成后发 2 个事件（progress=74/95）。

算法模块（download_nodes.py, omega_sf_fenkuai.py）通过 `ctx.logger_adapter.emit_progress()` 发送进度。`LoggerAdapter` 是一个 Protocol 接口（`algorithms/providers/Python/interfaces/logger.py`），需要在 bridge service 侧提供实现。

### 修改文件

`Code/backend/app/services/python_provider_bridge_service.py`

### 修改内容

1. **新增 `_EventForwardingLoggerAdapter` 内部类**：

```python
class _EventForwardingLoggerAdapter:
    """将算法模块的 emit_* 调用转发为 event_factory 事件。"""

    def __init__(self, event_factory, run_id: str, node_label_map: dict[str, str] | None = None):
        self._event_factory = event_factory
        self._run_id = run_id
        self._node_label_map = node_label_map or {}
        self._current_stage: str | None = None

    def bind_context(self, job_id: str, run_id: str) -> None:
        self._run_id = run_id

    def emit_stage_start(self, stage: str, message: str) -> None:
        self._current_stage = stage
        self._emit_node_progress(stage, 0, message)

    def emit_progress(self, stage: str, progress: float, message: str) -> None:
        # progress 可能是 0-1 或 0-100，统一为 0-100
        pct = int(progress * 100) if progress <= 1.0 else int(progress)
        self._emit_node_progress(stage, pct, message)

    def emit_warning(self, stage: str, message: str, extra=None) -> None:
        self._emit_node_progress(stage, -1, message, warning=True)

    def emit_error(self, stage: str, message: str, extra=None) -> None:
        self._emit_node_progress(stage, -1, message, error=True)

    def emit_artifact(self, stage: str, artifact_uri: str, artifact_type: str) -> None:
        pass  # 前端暂不处理 artifact 事件

    def emit_stage_end(self, stage: str, message: str) -> None:
        self._emit_node_progress(stage, 100, message)
        self._current_stage = None

    def _emit_node_progress(self, stage: str, progress: int, message: str, warning=False, error=False):
        if self._event_factory is None:
            return
        node_label = self._node_label_map.get(stage, stage)
        # 映射 stage -> 前端阶段分类
        stage_category = _classify_stage(stage)
        event = self._event_factory(
            channel="log",
            message=message,
            progress=progress if 0 <= progress <= 100 else None,
            payload={
                "node_progress": {
                    "node_id": stage,
                    "node_label": node_label,
                    "stage": stage_category,
                    "progress": max(0, min(100, progress)),
                    "message": message,
                }
            },
        )
        # event 通过 event_factory 内部队列发送，无需额外操作
```

2. **添加 stage 分类辅助函数**：

```python
def _classify_stage(stage: str) -> str:
    """将算法 stage 名称映射为前端阶段分类。"""
    stage_lower = stage.lower()
    if any(k in stage_lower for k in ("ssh_sync", "nsidc", "download", "sync")):
        return "download"
    if any(k in stage_lower for k in ("fy_preprocess", "preprocess", "geolocation")):
        return "preprocess"
    if any(k in stage_lower for k in ("omega_sf", "inversion", "sf_invert", "ddca", "block")):
        return "inversion"
    if any(k in stage_lower for k in ("output", "export", "write")):
        return "output"
    return "processing"
```

3. **在 `execute()` 方法中注入 logger_adapter**：

在 `execute()` 方法中，构建 `request_payload` 后、调用 `service.submit_job` 前，创建 adapter 实例。但由于 `submit_job` 是同步调用且内部已封装了 dispatch.py 的执行流程，需要确认 dispatch.py 是否接受外部 logger_adapter。

**替代方案（推荐）**：如果 `submit_job` 不支持传入 logger_adapter，则在 `execute()` 方法的 events 列表中，基于 `job_result` 中的进度信息构建 node_progress 事件。同时在 `result_dto` 的 products 中为每个输出（SM/VOD/OMEGA）生成独立的 result_ref。

### 验证

```bash
cd Code/backend
pytest tests/test_workflow_routes.py -q
# 启动后端后手动测试
python launch.py start fastapi
# 提交一个 omega_sf_fenkuai 工作流，观察事件流中是否包含 node_progress
```

---

## Part 3：多输出 result_ref 生成验证

**目标**：确保 `python_provider_result_builder.py` 为 omega_sf_fenkuai 的 3 个输出（SM/VOD/OMEGA）生成独立的 `WorkflowResultReference`。

### 检查文件

`Code/backend/app/services/python_provider_result_builder.py`

### 检查内容

1. `build_result_refs()` 方法是否遍历 `job_result` 中的 `products` 列表
2. 每个 `ProductRef`（name=SM/VOD/OMEGA）是否生成独立的 `WorkflowResultReference`
3. 每个 result_ref 的 `title` 是否为 US-ASCII（如 "SM"、"VOD"、"OMEGA"）
4. `result_type` 是否为 `map_layer` 以便前端叠加

### 预期行为

- omega_sf_fenkuai 执行后返回 3 个 result_refs
- 前端收到 3 个 `map_layer` 类型的 result_refs 后，依次创建 jobLayer 并叠加

---

## Part 4：后端全面验证

### 4a. 模块编译与导入

```bash
cd Code/algorithms/providers/Python
python -m py_compile algorithms/omega_sf.py
python -m py_compile modules/omega_sf_fenkuai.py
python -m py_compile modules/download_nodes.py
python -m py_compile ingest/remote_sync.py
python -m py_compile ingest/nsidc_download.py
python -m py_compile ingest/fy_preprocess.py
```

### 4b. 节点模板注册验证

```bash
cd Code/backend
python -c "
from app.services.node_template_registry import get_all_node_templates
types = [t['type'] for t in get_all_node_templates()]
assert 'module/omega_sf_fenkuai' in types, 'omega_sf_fenkuai not registered'
assert 'download/ssh_sync' in types, 'ssh_sync not registered'
assert 'download/nsidc_smap_download' in types, 'nsidc_smap_download not registered'
assert 'download/fy_preprocess' in types, 'fy_preprocess not registered'
print('All 4 node templates registered OK')
"
```

### 4c. 工作流种子编译

```bash
cd Code/backend
python -c "
import json
for f in ['omega_sf_fenkuai_fy_single.json', 'omega_sf_fenkuai_smap_single.json']:
    d = json.load(open(f'workflow_seeds/system/{f}'))
    assert d['workflow_id'], f'{f}: missing workflow_id'
    assert d['_meta']['linked_layer_id'] == 'omega-sf-fenkuai', f'{f}: wrong linked_layer_id'
    assert 'pipeline' in d['_meta'].get('tags', []), f'{f}: missing pipeline tag'
    assert len(d['nodes']) > 0, f'{f}: no nodes'
    print(f'{f}: OK ({len(d[\"nodes\"])} nodes)')
"

pytest tests/test_workflow_graph_compiler.py -q
```

### 4d. 工作流路由 + 业务回归

```bash
cd Code/backend
pytest tests/test_workflow_routes.py tests/test_interaction_hub.py tests/test_business_regression.py -q
```

### 4e. 远程浏览 API（需启动 FastAPI）

```bash
python launch.py start fastapi
# 测试连接
curl "http://127.0.0.1:8000/api/remote/test?server=win11"
# 测试目录列表
curl "http://127.0.0.1:8000/api/remote/list?server=win11&path=E/"
```

---

## Part 5：前端全面验证

### 5a. Lint 检查

```bash
cd Code/frontend
npm run lint
```

### 5b. 单元测试

```bash
cd Code/frontend
npm run test
```

### 5c. 构建

```bash
cd Code/frontend
npm run build
```

### 5d. OpenAPI 契约检查

```bash
cd Code/frontend
npm run check:openapi
```

### 5e. 关键组件手动检查清单

- [ ] `workflow-output-layers.ts` 导出 `createOutputLayers` 方法
- [ ] `WorkflowRunDialog.vue` multi 模式下"批量创建并运行"按钮可点击
- [ ] `PipelineLauncher.vue` 能加载到 pipeline 标签的工作流种子
- [ ] `WorkflowInspector.vue` 选中 download/* 节点时显示专用表单
- [ ] `WorkflowStatusPanel.vue` 展开 job 后显示节点进度区块（如有事件）

---

## Part 6：端到端集成验证

### 前提条件

1. 数据整理脚本已完成（12 类目录结构就绪）
2. 至少有少量测试数据可用（如 1-2 天的 SMAP .mat 文件）
3. SSH 密钥/凭据已配置（如需远程下载）
4. NSIDC Earthdata 账号已配置（如需 NSIDC 下载）

### 验证步骤

1. **全栈启动**：`python launch.py start`
2. **前端打开工作流编辑器**
3. **点击"流水线"按钮**
4. **选择"SF 块反演全流程（SMAP 单温度）"模板**
5. **设置日期范围**：如 2025-01-01 ~ 2025-01-08（1 个 8-day 块）
6. **确认启动**
7. **观察 WorkflowStatusPanel**：
   - 整体进度条更新
   - 节点级进度区块（如 D2 修复后）：下载/预处理/反演各阶段
8. **验证地图上自动叠加图层**：
   - multi 模式应生成 3 个图层（SM/VOD/OMEGA）
   - 图层面板中 3 个图层按分组显示
9. **在图层面板中验证**：
   - 3 个图层可独立切换可见性
   - 每个图层有独立配色方案
   - 点击图层可查看详细信息

### 降级验证（数据不足时）

如果完整算法因数据不足无法运行，验证以下降级路径：

1. **工作流提交成功**：即使算法最终失败，提交和事件流应正常工作
2. **错误信息可读**：失败时状态面板显示有意义的错误诊断
3. **重试机制**：失败后可点击"重试"按钮重新提交
4. **下载节点独立测试**：在工作流编辑器中单独添加 `download/ssh_sync` 节点，配置参数后运行

---

## 实施顺序与依赖

```
Part 1 (D1 修复) ──────────────────────────────────────────┐
                                                            ├──→ Part 5 (前端验证)
Part 2 (D2+D3 修复) ──→ Part 3 (result_ref 验证) ──→ Part 4 (后端验证) ──┤
                                                            └──→ Part 6 (端到端集成)
```

**并行策略**：
- Part 1 可立即开始（独立前端修复，5 分钟）
- Part 2 可与 Part 1 并行（后端修复，需理解 bridge service 执行链路）
- Part 3 依赖 Part 2（需确认 result_builder 行为）
- Part 4 依赖 Part 2+3（后端验证需修复完成）
- Part 5 依赖 Part 1（前端验证需 D1 修复）
- Part 6 依赖 Part 4+5（端到端需前后端均通过）

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| `submit_job` 内部不接受外部 logger_adapter，D2 修复无法注入 | 改为在 `execute()` 返回的 events 中，基于 `job_result` 元数据构建 node_progress 事件；或修改 dispatch.py 接受可选 logger_adapter 参数 |
| omega_sf_fenkuai 算法运行时依赖大量 .mat 辅助数据，本地可能缺失 | 种子中 data_source 节点标注数据路径；提供 ssh_sync 节点可选下载；端到端验证使用降级路径 |
| NSIDC 下载受网络/凭据限制 | nsidc_smap_download 节点设计为可选；种子默认使用本地数据路径 |
| FY 预处理依赖 GDAL 可执行文件 | fy_preprocess.py 已实现 `_resolve_gdal_bins()` 延迟定位 |
| Celery metadata 不支持非 ASCII | 所有 result_ref title 使用 US-ASCII（SM/VOD/OMEGA） |
| 数据整理脚本未完成 | 端到端验证可使用已有数据子集；工作流种子中路径基于 12 类目录结构，与整理后结构一致 |
| 前端 createOutputLayers 调用签名不匹配 | 确保 store 方法签名与 WorkflowEditorPanel.vue L286-291 调用完全一致 |

## 预计工作量

| Part | 描述 | 预计时间 |
|------|------|----------|
| 1 | D1 修复：createOutputLayers | 5 分钟 |
| 2 | D2+D3 修复：node_progress 事件转发 | 30-60 分钟 |
| 3 | 多输出 result_ref 验证 | 15 分钟 |
| 4 | 后端全面验证 | 20 分钟 |
| 5 | 前端全面验证 | 15 分钟 |
| 6 | 端到端集成验证 | 30 分钟 |
| **总计** | | **~2-3 小时** |
