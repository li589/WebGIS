# 配置管理器集成收尾计划

## 摘要

上一轮会话已完成配置管理器的全部后端与子组件（共 12 项任务），文件已落盘：
- 后端：`api_keys_repository.py` / `config_service.py` / `config_routes.py`，且 `main.py` 已注册 `config_router`
- 前端：`settings-api.ts` / `stores/settings.ts` / `SettingsPanel.vue` / `GeneralSettings.vue` / `DataSourceSettings.vue` / `AboutSettings.vue` / `ApiKeySettings.vue` / `GeeAccountSettings.vue`

本计划仅处理剩余的 **工具栏集成** 与 **验证** 工作（原计划任务 13–15），让"设置"按钮真正出现在工具栏中并完成端到端验证。

## 当前状态分析（基于 Phase 1 探查）

### ModeToolbar.vue（[文件](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/ModeToolbar.vue)）
- 当前 emits：`changeTileSource | openScreenshot | openWorkflowStatus | openLog`（L52–57）
- 截图按钮：L149–157
- 日志按钮：L160–169
- 中间**无**设置按钮
- `handleScreenshot` 模式（L95–98）可作为新增 `handleSettings` 的范式

### DashboardView.vue（[文件](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/views/DashboardView.vue)）
- 已有 `screenshotOpen` / `workflowStatusOpen` / `logOpen` 三个 ref（L44–46）作为模式范本
- `ScreenshotExport` 通过 `defineAsyncComponent` 异步加载（L47），SettingsPanel 沿用该模式
- `handleOpenScreenshot` / `handleCloseScreenshot`（L173–179）作为 handler 范本
- ModeToolbar 绑定位于 L262–272，已绑定 `@open-screenshot` / `@open-workflow-status` / `@open-log`
- 底部面板挂载区在 L353–372（ScreenshotExport / WorkflowStatusPanel / LogPanel），新增 SettingsPanel 紧邻 LogPanel

### SettingsPanel.vue（[文件](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/settings/SettingsPanel.vue)）
- 已确认 emits：`close: []`（L11–12）
- 与 LogPanel 一样采用右侧抽屉 + overlay 模式
- onMounted 中调用 `settingsStore.loadAll()`

### 后端集成
- `main.py` L25：`from app.api.config_routes import router as config_router`
- `main.py` L149：`app.include_router(config_router)` —— 已注册，无需改动

## 计划变更

### 任务 1：ModeToolbar.vue 添加"设置"按钮

**文件**：[Code/frontend/src/components/ModeToolbar.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/ModeToolbar.vue)

**1.1** 在 emits 定义（L52–57）末尾增加 `openSettings: []`：
```ts
const emit = defineEmits<{
  changeTileSource: [sourceId: TileSourceId]
  openScreenshot: []
  openWorkflowStatus: []
  openLog: []
  openSettings: []
}>()
```

**1.2** 在 `handleScreenshot` 之后（L98 后）新增 `handleSettings`：
```ts
function handleSettings() {
  emit('openSettings')
  logStore.logOperation('settings-open', '打开系统设置')
}
```

**1.3** 在截图按钮 `</button>`（L157）与 `<!-- 日志 -->` 注释（L159）之间插入"设置"按钮，使其位于"截图"与"日志"中间：
```vue
<!-- 设置 -->
<button
  class="tool-btn"
  type="button"
  title="系统设置"
  @click="handleSettings"
>
  <span class="btn-icon" aria-hidden="true">⚙</span>
  <span class="btn-label">设置</span>
</button>
```

无需新增 CSS —— 复用现有 `.tool-btn` / `.btn-icon` / `.btn-label` 样式（L311–343）。

### 任务 2：DashboardView.vue 集成 SettingsPanel

**文件**：[Code/frontend/src/views/DashboardView.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/views/DashboardView.vue)

**2.1** 在 `ScreenshotExport` 的 `defineAsyncComponent` 后（L47 后）追加 SettingsPanel 异步组件：
```ts
const SettingsPanel = defineAsyncComponent(() => import('../components/settings/SettingsPanel.vue'))
```

**2.2** 在 `logOpen` ref 之后（L46 后）追加 `settingsOpen`：
```ts
const settingsOpen = ref(false)
```

**2.3** 在 `handleCloseScreenshot` 之后（L179 后）新增两个 handler（与 `handleOpen/CloseWorkflowStatus` 风格一致）：
```ts
function handleOpenSettings() {
  settingsOpen.value = true
}

function handleCloseSettings() {
  settingsOpen.value = false
}
```

**2.4** 在 ModeToolbar 模板（L262–272）的 `@open-screenshot="handleOpenScreenshot"` 行后追加：
```vue
@open-settings="handleOpenSettings"
```

**2.5** 在 `LogPanel` 挂载块（L369–372）之后追加 SettingsPanel 挂载：
```vue
<SettingsPanel
  v-if="settingsOpen"
  @close="handleCloseSettings"
/>
```

### 任务 3：验证

**3.1 TypeScript 编译**

在 `Code/frontend` 目录运行：
```powershell
npx vue-tsc --noEmit
```
预期：无新增错误（已有的与本次改动无关的错误可忽略）。

**3.2 后端 API 冒烟测试**

在 `Code/backend` 目录运行 uvicorn 后，依次请求只读端点验证路由可访问：
- `GET /config/general` —— 返回系统信息
- `GET /config/api-keys` —— 返回 API Key 列表（含 tianditu / baidu / backend_auth 预设项，值为掩码）
- `GET /config/about` —— 返回项目架构信息
- `GET /config/gee/accounts` —— 返回 GEE 账号列表

预期：均返回 200 与合法 JSON 结构。

**3.3 端到端 UI 验证**

启动前端开发服务器，确认：
- 工具栏"截图"与"日志"之间出现"设置"按钮（⚙ 图标）
- 点击"设置"打开右侧抽屉
- 左侧 5 个分类标签（通用 / API 管理 / GEE 账户 / 数据源 / 关于）可切换
- 点击"关于"标签可查看架构思维导图
- 点击抽屉外部或关闭按钮可关闭

## 假设与决策

1. **不动既有设置子组件**：上一轮会话产出的 8 个前端文件 + 3 个后端文件已经完成且功能完整，本计划不修改它们的实现，只做"接线"。
2. **不重启后端做断言测试**：若后端服务已在运行，则做 curl 冒烟测试；否则跳过 3.2，仅做编译与 UI 验证。
3. **复用 ScreenshotExport 异步加载模式**：SettingsPanel 用 `defineAsyncComponent` 加载，与现有面板保持一致，避免首屏包体积膨胀。
4. **不引入新 CSS**：ModeToolbar 的 `.tool-btn` 系列样式已经覆盖"设置"按钮所需视觉表达。
5. **沿用 LogPanel overlay 模式**：SettingsPanel 内部已自带 overlay + 右侧抽屉结构，DashboardView 只需 `v-if` 挂载与 `@close` 监听，无需额外遮罩。
6. **不写 git commit**：除非用户明确要求；按 workspace 规则仅完成代码改动。

## 验证清单

- [ ] `ModeToolbar.vue` emits 包含 `openSettings: []`
- [ ] `ModeToolbar.vue` 模板中"设置"按钮位于"截图"与"日志"之间
- [ ] `DashboardView.vue` 引入 SettingsPanel 异步组件
- [ ] `DashboardView.vue` 存在 `settingsOpen` ref 与 `handleOpenSettings` / `handleCloseSettings`
- [ ] `DashboardView.vue` 在 ModeToolbar 上绑定 `@open-settings="handleOpenSettings"`
- [ ] `DashboardView.vue` 模板挂载 `<SettingsPanel v-if="settingsOpen" @close="handleCloseSettings" />`
- [ ] `npx vue-tsc --noEmit` 通过（无本次改动引入的错误）
- [ ] UI 中"设置"按钮可见且可打开抽屉，5 个分类标签可切换，可正常关闭
