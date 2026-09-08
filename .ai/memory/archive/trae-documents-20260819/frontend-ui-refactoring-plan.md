# CGDA 前端 UI 重构计划

> 基于已完成的前端 UI 优化调研报告与 UICraft 技能工作流制定。
> 工作流顺序：评估 → 修正结构 → 精炼表达 → 验证打磨
> 主要工作流：normalize（对齐设计系统）+ extract（提取可复用组件/token）

## 一、现状基线

| 指标 | 实测值 | 目标 |
|------|--------|------|
| 硬编码 hex 颜色 | 1289 处 / 66 文件 | 全部迁移至 token（数据色板除外） |
| InfoPanel.vue 行数 | 4097 行 | 拆分后 < 800 行/文件 |
| LayerSidebar.vue 行数 | 2649 行 | 拆分后 < 800 行/文件 |
| DashboardView.vue 行数 | 1513 行 | 抽离 composables 后 < 500 行 |
| 低于 12px 字号 | 30+ 处 | 全部提升至 `--font-size-caption`（0.8rem） |
| 非标准断点 | 6 处（820/900/1100px） | 统一至 token 640/768/1024/1280 |
| 工作流 !important | 37 处 / 4 文件 | 降至 < 10（仅保留 LiteGraph 库覆盖） |
| emoji 字符 | 20+ 处 / 8 文件 | 全部替换为 lucide-vue-next SVG |
| 按钮实现变体 | 6 种 | 收敛到 AppButton + IconButton 2 种 |
| 面板壳容器 | 4 种（BasePanel/ControlPanel/PanelDock/Card） | 收敛到 PanelDock + Card 2 种 |

**已有基础**：Token 体系完整（`tokens.css` V1.0）；9 个基础组件已落地；双主题支持完善；登录页/日志/截图等高频 UI 已升级。

---

## 二、P0：顶栏重构 + 面板系统统一

### P0-1：ModeToolbar 顶栏重构

**文件**：`Code/frontend/src/components/ModeToolbar.vue`（845 行）

**改动内容**：
1. 交互模式按钮组（移动/选择/测量/清除）→ 替换为 `IconButton`（`size="sm"`，`active` 绑定 `uiStore.interactionMode`）
2. 截图/工作流/设置/日志按钮 → 替换为 `AppButton`（`variant="secondary"`，`size="sm"`，lucide 图标通过 `#icon` slot 传入）
3. 底图风格组（`style-group`）→ 替换为 `Tabs`（`variant="segmented"`，`compact`）
4. 来源选择器（`source-pill`）→ 保留自定义结构（locked 态特殊处理），内部颜色走 token
5. `log-badge` 字号 `10px` → `var(--font-size-caption)`（0.8rem）
6. `dim-toggle` 2D/3D 切换 → 保留自定义（暖色 3D 态），硬编码 `rgba(255,200,120,...)` → `var(--accent-warm)` 系列
7. 响应式断点 `1100px` → `1024px`（`--bp-lg`）
8. brand-mark 渐变 `#2f7eff` → 新增 token `--accent-blue-deep`

**原因**：6 种按钮变体收敛到 2 种设计系统组件，消除视觉不一致

**验证**：`npm run test && npm run lint && npm run build`；手动验证按钮交互态 + 响应式 + 键盘 Tab

### P0-2：PanelDock 功能补全

**文件**：
- `Code/frontend/src/components/ui/PanelDock.vue`（344 行 → 扩展至约 600 行）
- `Code/frontend/src/components/ControlPanel.vue`（893 行，功能迁移源）
- `Code/frontend/src/components/control-panel-geometry.ts`（保留并复用）

**改动内容**：
从 ControlPanel 迁移以下能力到 PanelDock：
1. **拖拽**：`startDragging`/`handlePointerMove`/`stopDragging`（PointerEvent）
2. **缩放**：`startResizing`/`handleResizeMove`/`stopResizing`（四角手柄）
3. **持久化**：`readPersistedState` + `watch` + localStorage（key: `geo-panel:${panelKey}`）
4. **隐藏态胶囊**：`restore-pill` UI + 拖拽 + 点击恢复
5. **布局快照**：`visibleLayoutSnapshot` 机制
6. 新增 props：`draggable`/`resizable`/`panelKey`/`defaultWidth`/`defaultHeight`/`minWidth`/`minHeight`/`handlePosition`
7. 新增 emit：`update:visible`（v-model:visible）
8. CSS 全部使用 token，替代 ControlPanel 中的 `rgba(12,22,38,0.65)` 等硬编码值
9. 标题栏操作按钮（折叠/复位/隐藏）→ 使用 `IconButton`（`size="xs"`）
10. 响应式：`window.innerWidth < 900` → `< 768`（`--bp-md`），禁用拖拽/缩放

**原因**：PanelDock 是设计系统组件（Token 完整），ControlPanel 是历史组件（硬编码多）。迁移后减少面板壳变体。

**验证**：`npm run test -- control-panel-geometry && npm run lint && npm run build`；手动验证拖拽/缩放/刷新恢复/隐藏恢复

### P0-3：DashboardView 切换 ControlPanel → PanelDock

**文件**：`Code/frontend/src/views/DashboardView.vue`

**改动内容**：
1. import 从 `ControlPanel` 改为 `PanelDock`
2. 模板中 `<ControlPanel>` → `<PanelDock>`，props 对齐
3. `analysisPanelRef` 类型适配 PanelDock expose 的方法签名
4. LayerSidebar 和 InfoPanel 的容器壳也改用 PanelDock

**依赖**：P0-2 完成后执行

**验证**：`npm run test && npm run build`；手动验证所有面板的拖拽/缩放/折叠/隐藏恢复

---

## 三、P1：Token 迁移重灾区 + 字号统一 + Select 组件

### P1-1：InfoPanel.vue Token 迁移

**文件**：`Code/frontend/src/components/InfoPanel.vue`（4097 行，142 处硬编码 hex）

**改动内容**：
1. 逐块替换硬编码颜色：
   - `#dfeefe`/`#d5e5f5`/`#d9ebfb` → `var(--text-primary)` 或 `var(--text-secondary)`
   - `#f3fbff` → `var(--text-strong)`
   - `#8cb5d9` → `var(--text-muted)`
   - `rgba(136,192,255,0.xx)` → `var(--border-subtle/default/strong)` 按透明度匹配
   - `rgba(8,18,33,0.xx)` → `var(--surface-1/2)`
   - `rgba(13,23,39,0.xx)` → `var(--surface-2)`
   - `rgba(90,162,255,0.xx)` → `var(--accent-surface)`/`var(--border-accent)`
2. 字号修复（7+ 处低于 12px）：`0.68rem`/`0.62rem`/`0.58rem`/`0.72rem` → 全部 `var(--font-size-caption)`
3. emoji 替换：`☀`→lucide `Sun`、`⚡`→`Zap`、`🌍`→`Globe`、`⚠️`→`AlertTriangle`

**验证**：`npm run test && npm run lint && npm run build`；`rg "#[0-9a-fA-F]{3,8}" InfoPanel.vue` 返回 0；暗色/浅色主题视觉回归

### P1-2：LayerSidebar.vue Token 迁移

**文件**：`Code/frontend/src/components/LayerSidebar.vue`（2649 行，83 处硬编码 hex）

**改动内容**：
1. 同 P1-1 方式逐块替换硬编码颜色为 token
2. emoji 替换（6+ 处）：`🔒`→`Lock`、`⚙`→`Settings`、`☰`→`GripVertical`、`✓`→`Check`、`✕`→`X`
3. 字号检查并修复所有低于 0.8rem 的值

**验证**：同 P1-1

### P1-3：全局面板字号 floor 统一

**文件**（多文件）：
- `ControlPanel.vue`：`0.72rem`/`0.7rem` → `var(--font-size-caption)`
- `DashboardView.vue`：`0.68rem` → `var(--font-size-caption)`
- `AttributeTable.vue`：10+ 处 `0.58rem`~`0.78rem` → `var(--font-size-caption)`
- `AppErrorBoundary.vue`：`0.78rem` → `var(--font-size-caption)`
- `NotFoundView.vue`：`0.82rem` → `var(--font-size-body)`
- `TimelineScrubber.vue`：检查并修复

**验证**：`rg "font-size:\s*0\.[0-7][0-9]?rem" --glob "*.vue" src/` 返回 0

### P1-4：Select 组件建设

**新文件**：`Code/frontend/src/components/ui/Select.vue`

**改动内容**：
1. API 设计：`modelValue`/`options`/`placeholder`/`size`/`disabled`/`block` props + `update:modelValue` emit
2. 视觉规格：`--surface-sunken` 底 + `--border-default` 边框 + `--radius-md` 圆角；sm=28px/md=36px 高度
3. 下拉面板：`--surface-3` + `--elevation-3`；选项 hover `--surface-hover`；selected `--accent-surface`
4. 箭头：lucide `ChevronDown`
5. 无障碍：`role="listbox"`/`role="option"`/`aria-selected`，键盘上下键导航
6. 支持 `prefers-reduced-motion`
7. 新建测试 `Test/frontend/components/ui/select.test.ts`

**验证**：`npm run test && npm run lint && npm run build`；键盘验证 Tab/Enter/上下键/Escape

---

## 四、P2：响应式统一 + Dashboard 瘦身 + 工作流样式

### P2-1：响应式断点统一

**文件**（6 处非标准断点）：
- `DashboardView.vue`：`1100px`→`1024px`；`820px`→`768px`
- `MapCanvas.vue`：`820px`→`768px`
- `ModeToolbar.vue`：`1100px`→`1024px`（在 P0-1 中一并处理）
- `ControlPanel.vue`：`900px`→`768px`
- `TimelinePanel.vue`：`900px`→`768px`
- JS 中 `window.innerWidth` 比较值也统一为 `< 768`

**验证**：`rg "(max-width|min-width):\s*(820|900|1100)px" --glob "*.vue" src/` 返回 0

### P2-2：DashboardView 瘦身 — 抽离 composables

**文件**：
- `Code/frontend/src/views/DashboardView.vue`（1513 行 → 目标 < 500 行）
- 新建 composables（`Code/frontend/src/composables/`）

**抽离以下 composables**：
1. **`useWeatherCoverage.ts`**：`refreshWeatherCoverage`/`weatherCoverage`/`coverageAbort`/`coverageSourceLabel`/`tileForecastHour` + 定时刷新
2. **`useTimelineSnap.ts`**：`snapTimelineToLatestValid`/`snapTimelineToLayerLatest`/`pendingSnapCatalogIds`/`selectedCatalogId` + 相关 watch
3. **`useImportedRasterTimeSync.ts`**：`refreshImportedRasterEffectiveTimes` + overlay 时间状态管理
4. **`useTimelineSegments.ts`**：`timelineSegments` computed + `buildRunTimelineAvailability` + 粒度切换/播放控制
5. **`usePanelVisibility.ts`**：`screenshotOpen`/`workflowStatusOpen`/`logOpen`/`settingsOpen` + `analysisPanelRef`

**注意**：Vue 3 composable 必须在 `setup()` 同步阶段调用，不能在异步回调中调用生命周期钩子。

**依赖**：P0-3 完成（面板组件已切换）

**验证**：`npm run test && npm run lint && npm run build`；新建 composable 测试；手动验证时间轴/天气覆盖/图层 snap 行为不变

### P2-3：工作流编辑器样式初步统一

**文件**：
- `litegraph-ui-overrides.css`（27 处 !important）→ **保留 !important**（第三方库覆盖合理），但 token 化颜色值
- `workflow-editor-chrome.css` → 滚动条颜色用 token
- `WorkflowStatusPanel.vue`（80 处 hex）→ token 迁移
- `WorkflowEditorPanel.vue`（45 处 hex）→ token 迁移
- `WorkflowNodePalette.vue`（38 处 hex）→ token 迁移
- `PipelineLauncher.vue`（33 处 hex）→ token 迁移
- `WorkflowLeftSidebar.vue`/`WorkflowRightSidebar.vue`/`WorkflowTimerPanel.vue` → 评估并移除非必要的 !important

**原则**：LiteGraph 的 `!important` 是 CSS 特异性要求，不是代码质量问题，保留。精力放在 token 化颜色值上。

**验证**：`npm run test && npm run lint && npm run build`；手动验证节点拖拽/连线/右键菜单/搜索框

---

## 五、P3：TimelineScrubber 语义化

### P3-1：TimelineScrubber 语义化重构

**文件**：`Code/frontend/src/components/TimelineScrubber.vue`（1246 行，38 处硬编码 hex）

**改动内容**：
1. **ARIA 语义化**：滑块 `role="slider"` + `aria-valuemin/max/now`；可用性条 `role="meter"`；日期导航用 `<button>`
2. **键盘交互**：左右箭头微调（1 step）、上下箭头大调（10 step）、Home/End 跳首尾、Space 播放/暂停
3. **Token 迁移**：38 处硬编码 hex 全部替换
4. **复用 UI 组件**：播放/暂停/前进/后退 → `IconButton`；时间粒度切换 → `Tabs`（segmented）；时间标签 → `Chip`
5. 响应式断点统一

**验证**：`npm run test && npm run lint && npm run build`；键盘验证 + 屏幕阅读器验证 + `rg "#[0-9a-fA-F]{3,8}" TimelineScrubber.vue` 返回 0

---

## 六、跨步骤公共事项

### P-Common-1：BasePanel 退役

PanelDock 补全 + ControlPanel 迁移完成后，确认 `rg "BasePanel" --glob "*.vue" src/` 无引用后删除 `BasePanel.vue`。

### P-Common-2：全局 emoji 清理

8 个文件 20+ 处 emoji 全部替换为 lucide-vue-next SVG 组件：
- `DashboardView.vue`：`🌐`→`Globe`
- `InfoPanel.vue`：`☀`→`Sun`、`⚡`→`Zap`、`🌍`→`Globe`、`⚠️`→`AlertTriangle`
- `LayerSidebar.vue`：`🔒`→`Lock`、`⚙`→`Settings`、`☰`→`GripVertical`、`✓`→`Check`、`✕`→`X`
- `DataImportMenu.vue`/`DataWorkspace.vue`/`DataExportPanel.vue`/`DataImportPanel.vue`/`RasterImportConfirmDialog.vue`：各 emoji 替换

### P-Common-3：Token 补充

`Code/frontend/src/styles/tokens.css` 中补充：
1. `--accent-blue-deep`：brand-mark 渐变用
2. `--scrollbar-thumb`/`--scrollbar-track`：统一滚动条配色
3. `--font-weight-bold`：如 log-badge 等需要（当前 token 仅 regular/medium）
4. 检查浅色主题对应值

---

## 七、实施顺序与依赖

```
P0-2 (PanelDock 补全) ──┐
                         ├──→ P0-3 (Dashboard 切换) ──→ P2-2 (Dashboard 瘦身)
P0-1 (ModeToolbar) ──────┘
                                      ↓
P-Common-3 (token 补充) ─────────────┐
P1-4 (Select 组件) ──────────────────┤
P1-1 (InfoPanel Token) ──────────────┼──→ P-Common-2 (emoji 清理)
P1-2 (LayerSidebar Token) ──────────┤
P1-3 (字号 floor 统一) ──────────────┘
                                      ↓
P2-1 (断点统一) ───────────────────┐
P2-3 (工作流样式) ─────────────────┘
                                      ↓
P3-1 (TimelineScrubber 语义化)
                                      ↓
P-Common-1 (BasePanel 退役)
```

**关键依赖**：
- P0-2 必须先于 P0-3（PanelDock 功能补全后才能替代 ControlPanel）
- P-Common-3 与 P1 同步进行（迁移中发现缺失 token 时补充）
- P2-2 依赖 P0-3 完成
- P-Common-1 在最后执行

---

## 八、验证策略

每步完成后执行：
```powershell
cd Code/frontend
npm run test
npm run lint
npm run build
npm run check:catalog
npm run check:openapi
```

**视觉回归清单**：
1. 暗色/浅色主题下所有面板/按钮/芯片颜色一致
2. 响应式：640/768/1024/1280 四断点布局正常
3. 键盘：Tab 遍历所有交互元素，focus-visible 环可见
4. `prefers-reduced-motion`：动效全部禁用
5. 空状态/加载态/错误态正常
6. 工作流编辑器 LiteGraph 右键菜单/搜索框/对话框正常

**grep 验证基线（最终目标）**：
- 硬编码 hex（目标 < 50，仅保留地图渲染层数据色）
- 低于 12px 字号（目标 0）
- 非标准断点（目标 0）
- emoji（目标 0）

---

## 九、风险与注意事项

1. **ControlPanel → PanelDock 迁移**：拖拽/缩放逻辑涉及大量边界情况（右侧 dock 钉边、resize offset 补偿、隐藏态胶囊拖拽阈值），必须保留 `control-panel-geometry.ts` 纯函数，逐个方法迁移并测试。

2. **LiteGraph `!important`**：`litegraph-ui-overrides.css` 中的 27 处 `!important` 是覆盖第三方库样式的合理手段，保留。精力放在 token 化颜色值上。

3. **地图渲染层 hex**：`weather-render.ts` 等文件中的 129 处 hex 可能是数据可视化色带（温度/降水色阶），是数据语义色而非 UI 装饰色，**不应**盲目迁移到设计 token，需逐个判断。

4. **Vue 3 composable 限制**：composable 必须在 `setup()` 同步阶段调用，不能在异步回调中调用 `onMounted`/`onBeforeUnmount`。

5. **前端测试不受 WorkBuddy shim 影响**：WorkBuddy 的 safe-delete shim 仅影响后端 pytest，前端 vitest 正常执行。
