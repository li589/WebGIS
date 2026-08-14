# 工作流编辑器 UI 约定

## 滚动条

工作流编辑器内所有可滚动区域须使用统一细滚动条样式，避免浏览器默认粗滚动条破坏深色面板观感。

### 首选：`.wf-scroll`

定义于 `Code/frontend/src/components/workflow/workflow-editor-chrome.css`。

在组件 `<script setup>` 中：

```ts
import './workflow-editor-chrome.css'
```

在可滚动容器上添加 class `wf-scroll`，例如：

- `WorkflowTimerPanel`：`.timer-list`、`.timer-detail-pane`
- `PipelineLauncher`：`.pipeline-body`
- `NodeCacheDialog`：`.nc-list`
- 侧栏列表：与 `WorkflowLeftSidebar` / `WorkflowRightSidebar` 内联的 `::-webkit-scrollbar` 规则等效

### 规范

1. **禁止** 仅写 `overflow-y: auto` 而不应用 `.wf-scroll` 或组件内等效的 webkit + `scrollbar-width: thin` 规则。
2. 工作流编辑器外（如 `ControlPanel`、`LayerSidebar`）可使用各自的 CSS 变量或内联规则，但 thumb 色建议与 `rgba(90, 180, 255, 0.26~0.45)` 保持一致。
3. 新增对话框/面板时，在 PR 或自检中确认滚动区域已套统一样式。

## 只读预设工作流

系统种子 `_meta.readonly: true` 时，图结构不可编辑、不可保存，但 **排列**、**适配** 等纯视图操作应可用（排列仅调整画布布局，不写回定义）。
