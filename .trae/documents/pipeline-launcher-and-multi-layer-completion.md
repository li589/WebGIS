# 流水线启动器与三图层自动生成 — 收尾计划

## 摘要

本计划完成"一键流水线入口 (Part 5b)"和"三图层自动生成 (Part 5d)"两个功能的收尾工作。经过代码审查，绝大部分实现已完成，唯一缺失的是 `stores/workflow-output-layers.ts` 中的 `createOutputLayers` 批量创建方法。`WorkflowEditorPanel.vue` 的 `handleRunConfirm` 已在调用此方法（第 286 行），但 store 中尚未定义，导致 TypeScript 编译会失败。本计划补全该方法并运行验证。

## 当前状态分析

### 已完成的工作

1. **PipelineLauncher.vue** — 已创建，功能完整
   - Props: `visible` (boolean)
   - Emits: `close`, `launch` (workflowId, params)
   - 从 `_meta.tags` 过滤含 "pipeline" 的系统工作流
   - 卡片展示名称、描述、输出图层标签（`extra.outputs`）
   - 日期输入（原生 `input type="date"`，YYYYMMDD ↔ YYYY-MM-DD 转换）
   - 高级参数可折叠区域
   - 暗色主题样式

2. **WorkflowEditorPanel.vue** — 已修改，功能完整
   - 导入 PipelineLauncher 组件（第 30 行）
   - `showPipelineLauncher` ref（第 80 行）
   - `pendingPipelineParams` ref（第 83 行）
   - "流水线"按钮在 header-actions 中，位于"运行"按钮左侧（第 566-574 行）
   - `handleRunConfirm` 适配 multi 模式，调用 `outputStore.createOutputLayers(...)`（第 276-306 行）
   - `applyPipelineParamsToGraph` 辅助函数注入流水线参数到 graphData（第 312-337 行）
   - `handlePipelineLaunch` 方法加载工作流定义并暂存参数（第 342-360 行）
   - PipelineLauncher 组件挂载在 template 底部（第 736-740 行）
   - `.header-btn.pipeline` CSS 样式（第 902 行）

3. **WorkflowRunDialog.vue** — 已修改，功能完整
   - `WorkflowRunTarget` 接口扩展 `multi` 模式（第 16-24 行）
   - `outputCount` computed 检测 omega_sf_fenkuai 节点（第 64-78 行）
   - `outputTags` computed 从 `extra.outputs` 读取输出标签（第 81-90 行）
   - `multiNamePrefix` computed 提取模块名作为图层名前缀（第 93-105 行）
   - multi 模式 UI：图层名称可编辑列表、分组选择器、"全部使用相同分组"复选框（第 318-381 行）
   - `handleConfirm` 适配 multi 模式 emit targets（第 160-168 行）
   - multi 模式相关 CSS 样式（第 586-646 行）

### 缺失的工作

4. **stores/workflow-output-layers.ts** — 未修改，缺少 `createOutputLayers` 批量方法

   `WorkflowEditorPanel.vue` 第 286-291 行已调用：
   ```typescript
   outputStore.createOutputLayers(
     target.targets,                      // Array<{ name: string; group: string }>
     currentDefinition.value.workflow_id,  // string (sourceWorkflowId)
     linkedLayerId,                       // string (sourceLayerId)
     currentEngine.value,                 // string (engine)
   )
   ```

   但 store 中只有 `createOutputLayer`（单数，第 109-127 行），没有 `createOutputLayers`（复数）。这会导致 TypeScript 编译错误和方法不存在运行时错误。

## 拟定变更

### 文件: `Code/frontend/src/stores/workflow-output-layers.ts`

**变更内容**: 新增 `createOutputLayers` 批量创建方法

**位置**: 在现有 `createOutputLayer` 方法之后（约第 127 行之后），`updateRunStatus` 方法之前

**实现**:
```typescript
/**
 * 批量创建产出图层条目（用于 multi 模式一次性创建多个输出图层）。
 * 内部复用 createOutputLayer，确保每个条目的 localId 唯一。
 */
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

**导出**: 在 store 的 return 语句中添加 `createOutputLayers`

**原因**: `WorkflowEditorPanel.vue` 的 `handleRunConfirm` 在 multi 模式下需要一次性创建多个输出图层条目。批量方法复用现有 `createOutputLayer` 逻辑，保证 localId 唯一性和持久化行为一致。

**向后兼容**: 新增方法不影响现有 `createOutputLayer` 单数方法的行为。

## 假设与决策

1. **方法签名**: 使用 4 个位置参数 `(targets, sourceWorkflowId, sourceLayerId, engine)` 而非用户原始需求中的 2 参数版本。原因：实际调用方 `WorkflowEditorPanel.vue` 已使用 4 参数签名，且 `createOutputLayer` 单数方法也需要这 4 个信息（sourceWorkflowId / sourceLayerId / engine）。2 参数版本无法提供足够的上下文信息。

2. **复用 createOutputLayer**: 批量方法内部调用现有 `createOutputLayer`，而非重复实现创建逻辑。这保证 localId 生成、默认值处理（空名称 → 时间戳、空分组 → "默认分组"）、`entries.value.unshift` 行为完全一致。

3. **返回值**: 返回 `WorkflowOutputLayerEntry[]`（创建的条目数组），与单数方法返回单个 entry 的模式一致，便于调用方日志记录或后续操作。

4. **无额外 UI 变更**: WorkflowRunDialog.vue 和 WorkflowEditorPanel.vue 已完整实现 multi 模式 UI 和调用逻辑，无需进一步修改。

## 验证步骤

1. **TypeScript 编译检查**:
   ```bash
   cd Code/frontend && npm run build
   ```
   确认无 TypeScript 错误，特别是 `createOutputLayers` 方法存在且签名匹配调用方。

2. **Lint 检查**:
   ```bash
   cd Code/frontend && npm run lint
   ```
   确认无 eslint 错误。

3. **单元测试**（如果存在相关测试）:
   ```bash
   cd Code/frontend && npm run test
   ```
   确认现有测试不回归。

4. **功能验证（手动）**:
   - 打开工作流编辑器，确认"流水线"按钮显示在"运行"按钮左侧
   - 点击"流水线"按钮，确认 PipelineLauncher 对话框弹出并加载流水线卡片
   - 选择含 omega_sf_fenkuai 节点的工作流，点击"运行"，确认运行对话框显示"多图层自动生成"选项
   - 选择 multi 模式，确认可编辑图层名称列表和分组选择器正常显示
   - 确认"批量创建并运行"按钮在填写有效名称后可点击
