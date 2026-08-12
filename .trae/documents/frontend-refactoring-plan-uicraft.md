# CGDA 前端 UI 重构计划（UICraft 工作流）

> 工作流：assess（评估基线）→ correct structure（纠正结构）→ refine expression（精炼表达）→ finish & verify（收尾验证）
> 主工作流：normalize（对齐设计系统）+ extract（提取复用组件/Token）
> 设计系统真源：`Code/frontend/src/styles/tokens.css` V1.0（不改动，仅迁移至其约定）

---

## 零、Assess — 评估基线与审计结论

### 0.1 设计系统现状（已验证，保留不动）

| 维度 | 现状 | 评分 |
|------|------|------|
| Token 层 | `tokens.css` V1.0 完整覆盖颜色/间距/字号/动效/elevation/z-index/断点/触控 | 4/4 |
| 基础组件 | 9 个在 `src/components/ui/`：AppButton, Card, Chip, IconButton, PanelDock, Skeleton, Tabs, TextField, Tooltip | 3/4（PanelDock 功能缺口） |
| 主题切换 | `[data-theme='light']` 覆盖层已定义，仅覆盖颜色 token | 4/4 |
| 暗色模式 | 完整，低透明黑玻璃层级 | 4/4 |

### 0.2 漂移诊断（已用 grep 验证）

| 问题 | 实测值 | 说明 |
|------|--------|------|
| 硬编码 hex | 531 处 / 30 文件（`components/` 下） | 去除 tokens.css 自身 + 数据可视化文件后约 530 处需迁移 |
| 低于 12px floor 的 font-size | 298 处 / 20 文件 | 全部低于 `--font-size-caption: 0.8rem` |
| 非标断点 | 6 处（1100px×2, 820px×2, 900px×2） | 应统一到 640/768/1024/1280 |
| !important | 57 处 / 10 文件（含 litegraph 27） | 排除第三方后 30 处需处理 |
| 超大文件 | InfoPanel 4097 行, LayerSidebar 2649 行, DashboardView 1513 行, TimelineScrubber 1246 行, ControlPanel 893 行, ModeToolbar 757 行 | 目标 <400 行/文件 |
| 面板容器变体 | BasePanel + ControlPanel + CompositePanel + PanelDock + Card = 5 种 | 收敛到 2 种（PanelDock + Card） |
| 按钮变体 | 6 种自制类名（weather-mini-btn / imported-export-btn / wind-mode-seg-btn / weather-layer-btn / panel-tools__btn / 散布原生 button） | 收敛到 AppButton + IconButton |

### 0.3 豁免清单（不迁移、不改动）

| 文件 | 原因 |
|------|------|
| `src/components/map/weather-render.ts` | 数据可视化调色板（WEATHER_PALETTES），语义数据色 |
| `src/components/map/layer-symbology.ts` | 图层符号化调色板 |
| `src/components/map/wind-particle-webgl-shaders.ts` | WebGL 着色器颜色 |
| `src/components/map/scalar-field-webgl-shaders.ts` | WebGL 着色器颜色 |
| `src/components/workflow/litegraph-ui-overrides.css` | 第三方库覆写，27 处 !important 保留 |
| `src/styles/tokens.css` | Token 定义真源 |
| `src/components/control-panel-geometry.ts` | 纯函数已有测试，复用不改写 |

---

## 一、Correct Structure — P0/P1 结构纠正

### P0-1：面板容器收敛 — PanelDock 吸收 ControlPanel 能力

**目标**：5 种面板容器 → 2 种（PanelDock 浮层面板 + Card 静态卡片）。BasePanel、ControlPanel、CompositePanel 退役。

**原因**：PanelDock.vue（310 行）仅有折叠/关闭/复位，缺失拖拽/缩放/localStorage 持久化；ControlPanel.vue（893 行）实现了这些但用 BasePanel 做底壳（含硬编码 hex）。CompositePanel 是透传 wrapper（24 行，零附加逻辑）。

**改动文件**：

| 文件 | 行数 | 改动 |
|------|------|------|
| `src/components/ui/PanelDock.vue` | 310 → ~520 | 吸收 ControlPanel 的 drag/resize/persist 逻辑；复用 `control-panel-geometry.ts` 纯函数；新增 `draggable` `resizable` `handlePosition` `panelKey` `minWidth/maxWidth/minHeight/maxHeight` props；localStorage key 格式 `geo-panel:{panelKey}` 保持兼容 |
| `src/components/ControlPanel.vue` | 893 → 删除 | 逻辑迁移至 PanelDock 后删除 |
| `src/components/BasePanel.vue` | 38 → 删除 | 硬编码 hex + 非标渐变，功能被 Card 替代 |
| `src/components/CompositePanel.vue` | 47 → 删除 | 透传 wrapper，无附加逻辑 |

**新建文件**：

| 文件 | 用途 |
|------|------|
| `src/components/ui/usePanelDragResize.ts` | 从 ControlPanel 提取的拖拽/缩放 composable（pointer 事件、clamp、persist debounce）；纯逻辑，可单测 |
| `Test/frontend/components/use-panel-drag-resize.test.ts` | composable 单测（clamp 边界、persist 序列化、resize delta 方向） |

**关键约束**：
- `control-panel-geometry.ts` 的 6 个纯函数复用不改写，已有测试在 `Test/frontend/components/control-panel-geometry.test.ts`。
- localStorage key `geo-panel:{panelKey}` 格式不变，保证现有用户布局不丢。
- Vue 3 composable 必须在 `setup()` 同步调用，不能在 pointer 事件回调里调用。
- PanelDock 新增 props 的默认值须与 ControlPanel 现有默认值一致。

**迁移调用点**：

| 调用方 | 当前 | 迁移后 |
|--------|------|--------|
| `DashboardView.vue` | `<ControlPanel panelKey="analysis">` | `<PanelDock position="right" :draggable="true" :resizable="true" panelKey="analysis">` |
| `TimelinePanel.vue` | `<ControlPanel panelKey="timeline">` | `<PanelDock position="bottom" panelKey="timeline">` |
| 其他使用 BasePanel 的地方 | `<BasePanel>` | `<Card>` 或 `<PanelDock>` 视场景 |

**验证**：
```powershell
cd Code/frontend; npm run test -- control-panel-geometry use-panel-drag-resize
cd Code/frontend; npm run lint; npm run build
```
手动检查：拖拽/缩放/刷新恢复/折叠展开/移动端禁用拖拽。

**依赖**：无前置，可首先执行。

**风险**：PanelDock props API 扩展后需同步所有调用点；`isRightDockedPanel(panelKey)` 硬编码 `'analysis'` 需扩展。

---

### P0-2：硬编码 Token 迁移基础设施

**目标**：为后续大规模 hex→token 迁移建立映射表和 lint 规则。

**新建文件**：

| 文件 | 用途 |
|------|------|
| `src/styles/token-map.ts` | hex→token 映射表（如 `#5ad5ff` → `var(--accent)`, `#d8e6f5` → `var(--text-primary)`）；含语义说明 |
| `eslint-rules/no-hardcoded-colors.js` | 自定义 ESLint 规则：禁止 `<style>` 段和内联 `style="..."` 中出现未注册的 hex；初始 warn 级别 |
| `scripts/audit-ui-tokens.mjs` | 审计脚本：扫描 `src/` 下所有 .vue/.ts 的 hex 和低于 floor 的 font-size，输出报告；含文件路径白名单排除数据可视化文件 |

**改动文件**：

| 文件 | 改动 |
|------|------|
| `Code/frontend/eslint.config.js` | 注册自定义规则 `no-hardcoded-colors`，初始 `warn`；数据可视化文件设文件级豁免 |

**验证**：
```powershell
node scripts/audit-ui-tokens.mjs --baseline > token-baseline-before.txt
cd Code/frontend; npm run lint
```

**依赖**：无前置。后续所有 P2 迁移任务依赖此基础设施。

---

### P1-1：InfoPanel.vue 拆分（4097 行 → 目标 <400 行/文件）

**目标**：按功能域拆分为子组件 + composable。InfoPanel.vue 保留为壳（tab 容器 + 状态分发）。

**拆分方案**：

| 新文件 | 从 InfoPanel 提取的内容 | 预估行数 |
|--------|------------------------|---------|
| `src/components/info-panel/InfoPanelWeatherTab.vue` | 天气 provider 选择、天气图层操作、wind-mode 分段按钮 | ~350 |
| `src/components/info-panel/InfoPanelImportedTab.vue` | 导入图层的导出按钮组（GeoJson/Csv/Shp/NC/PNG/TIF） | ~250 |
| `src/components/info-panel/InfoPanelLegendSection.vue` | 图例渲染、palette 选择、legend gradient/stops | ~300 |
| `src/components/info-panel/InfoPanelExportButtons.vue` | 通用导出按钮组 → 收敛为 AppButton + IconButton | ~120 |
| `src/components/info-panel/useInfoPanelState.ts` | weatherProvider fetch/abort、import hint flash、tab 状态管理 composable | ~200 |
| `src/components/info-panel/info-panel-styles.css` | InfoPanel 专有样式（迁移后 hex→token，font-size→token） | ~600 |

**改动文件**：

| 文件 | 行数 | 改动 |
|------|------|------|
| `src/components/InfoPanel.vue` | 4097 → ~350 | 仅保留壳：props、tab 路由、子组件组合 |

**关键约束**：
- 已有 `src/components/info-panel/` 目录（`result-adapter.ts`、`analysis-panel-summary.ts` 等），新文件放入同目录。
- `buildResultDisplayModel`、`resolveAnalysisStageKind` 等已有纯函数复用，不重写。
- Vue 3 composable 在 `setup()` 顶部同步调用。

**验证**：
```powershell
cd Code/frontend; npm run test -- info-panel analysis-panel-summary analysis-tab-focus
cd Code/frontend; npm run lint; npm run build
node scripts/audit-ui-tokens.mjs > token-infopanel-after.txt
```
手动检查：四 tab 切换、天气 provider 加载/切换/abort、导出功能、图例渲染、暗色/浅色主题。

**依赖**：P0-2（审计脚本用于前后对比）。

---

### P1-2：LayerSidebar.vue 拆分（2649 行 → 目标 <400 行/文件）

**目标**：按图层类型分组拆分。

**拆分方案**：

| 新文件 | 从 LayerSidebar 提取的内容 | 预估行数 |
|--------|--------------------------|---------|
| `src/components/layer-sidebar/LayerGroupSection.vue` | 单个图层分组的折叠/列表/拖拽排序 | ~300 |
| `src/components/layer-sidebar/LayerVisibilityToggle.vue` | 图层显隐开关 + opacity 滑块 | ~200 |
| `src/components/layer-sidebar/LayerContextMenu.vue` | 右键菜单 UI 层（复用已有 `layer-context-menu.ts` 逻辑） | ~250 |
| `src/components/layer-sidebar/WeatherLayerControls.vue` | 天气图层专用控件（palette 选择、time 链接） | ~280 |
| `src/components/layer-sidebar/useLayerSidebarState.ts` | 图层列表过滤、展开态、拖拽排序 composable | ~200 |
| `src/components/layer-sidebar/layer-sidebar-styles.css` | 专有样式（83 处 hex、57 处 font-size 待迁移） | ~500 |

**改动文件**：

| 文件 | 行数 | 改动 |
|------|------|------|
| `src/components/LayerSidebar.vue` | 2649 → ~350 | 保留壳：分组容器、搜索过滤、子组件组合 |

**关键约束**：
- `layer-context-menu.ts` 已有测试，提取 UI 组件时复用其逻辑。
- `catalog.ts` 的 LAYER_LIBRARY 常量不可改动（有 `npm run check:catalog` 守护）。

**验证**：
```powershell
cd Code/frontend; npm run test -- layer-sidebar layer-context-menu layer-naming layer-display-names
cd Code/frontend; npm run check:catalog
cd Code/frontend; npm run lint; npm run build
```
手动检查：展开/折叠/搜索/拖拽排序/右键菜单/天气 palette 切换/opacity 滑块。

**依赖**：P0-2。与 P1-1 并行可行。

---

### P1-3：非标断点归一化（6 处 → 0 处）

**目标**：统一到 tokens.css 定义的 `--bp-sm:640px` / `--bp-md:768px` / `--bp-lg:1024px` / `--bp-xl:1280px`。

**改动文件**：

| 文件 | 行号 | 当前值 | 目标值 |
|------|------|--------|--------|
| `src/views/DashboardView.vue` | 1601 | `max-width: 1100px` | `max-width: 1024px` |
| `src/views/DashboardView.vue` | 1624 | `max-width: 820px` | `max-width: 768px` |
| `src/components/MapCanvas.vue` | 1361 | `max-width: 820px` | `max-width: 768px` |
| `src/components/ControlPanel.vue` | 912 | `max-width: 900px` | 随 P0-1 删除 |
| `src/components/TimelinePanel.vue` | 555 | `max-width: 900px` | `max-width: 768px` |
| `src/components/ModeToolbar.vue` | 819 | `max-width: 1100px` | `max-width: 1024px` |

**关键约束**：JavaScript 中的 `window.innerWidth` 比较值也同步修改（如 `< 820` → `768`，`< 900` → `768`）。

**验证**：
```powershell
cd Code/frontend; npm run test; npm run lint; npm run build
# grep 基线（应返回 0）
rg "(max-width|min-width):\s*(820|900|1100)px" Code/frontend/src/
```

**依赖**：P0-1（ControlPanel 删除后减少一处）。可与 P1-1/P1-2 并行。

---

### P1-4：DashboardView.vue 拆分（1513 行 → 目标 <400 行/文件）

**目标**：将布局编排与面板逻辑分离。

**拆分方案**：

| 新文件 | 从 DashboardView 提取的内容 | 预估行数 |
|--------|--------------------------|---------|
| `src/views/dashboard/DashboardLayout.vue` | 纯布局网格（left rail / center map / right panel / bottom timeline） | ~200 |
| `src/views/dashboard/useDashboardLayout.ts` | 面板显隐/位置/响应式布局 composable | ~250 |

**改动文件**：

| 文件 | 行数 | 改动 |
|------|------|------|
| `src/views/DashboardView.vue` | 1513 → ~300 | 保留路由入口 + 布局组合 + 数据初始化 |

**验证**：
```powershell
cd Code/frontend; npm run test -- auth-router
cd Code/frontend; npm run lint; npm run build
```

**依赖**：P0-1（PanelDock 替换 ControlPanel 后，DashboardView 调用点需同步改）。

---

## 二、Refine Expression — P2 表达精炼

### P2-1：硬编码 hex → Token 迁移（逐文件）

**目标**：将 ~530 处 UI 装饰 hex 迁移为 `var(--token)` 引用。按文件 hex 密度排序执行。

**迁移顺序**（按 hex 数量降序，拆分后文件优先）：

| 批次 | 文件 | hex 数 | 前置依赖 |
|------|------|--------|---------|
| 2a | InfoPanel.vue + 拆分出的 info-panel/* | 142 | P1-1 完成后 |
| 2b | LayerSidebar.vue + 拆分出的 layer-sidebar/* | 83 | P1-2 完成后 |
| 2c | TimelineScrubber.vue | 38 | 无 |
| 2d | MapCanvas.vue（UI 层 hex，不含 WebGL 渲染色） | 32 | 无 |
| 2e | settings/*（8 个文件） | ~128 | 无 |
| 2f | workflow/*（含 BboxInputField, DateInputField 等） | ~70 | 无 |
| 2g | data-manager/ui/*（DataExportPanel, DataImportPanel 等） | ~100 | 无 |
| 2h | 剩余散布文件（AppErrorBoundary, LoadingOverlay 等） | ~30 | 无 |

**迁移规则**（基于 `token-map.ts`）：

| hex 模式 | 目标 token |
|----------|-----------|
| `#f0faff` | `var(--text-strong)` |
| `#d8e6f5` | `var(--text-primary)` |
| `#9fb6cc` | `var(--text-secondary)` |
| `#5ad5ff` | `var(--accent)` |
| `#88dfff` | `var(--accent-strong)` |
| `#020814` | `var(--surface-base)` |
| `rgba(8,17,31,0.86)` | `var(--surface-1)` |
| `rgba(13,23,39,0.92)` | `var(--surface-2)` |
| `rgba(136,192,255,0.16)` | `var(--border-default)` |
| `rgba(90,213,255,0.12)` | `var(--accent-surface)` |
| 其他无精确匹配 | 找最近语义 token；若为全新色值则记录到迁移报告，人工裁决。不新增 token |

**验证**（每批次执行）：
```powershell
node scripts/audit-ui-tokens.mjs > token-after-batch-X.txt
cd Code/frontend; npm run lint; npm run build
```
手动检查：暗色/浅色主题视觉回归；focus-visible 焦点环一致。

**依赖**：P0-2。P2-1a 依赖 P1-1，P2-1b 依赖 P1-2。

**风险**：rgba 透明度变体多，映射时需判断语义（表面 vs 边框 vs 悬停）；迁移后浅色主题可能出现对比度不足。

---

### P2-2：低于 12px floor 的 font-size 迁移

**目标**：将 ~298 处低于 `--font-size-caption: 0.8rem (12px)` 的字号统一到 Token。

**迁移规则**：

| 当前值 | 目标 token |
|--------|-----------|
| `0.6rem` ~ `0.79rem` | `var(--font-size-caption)` |
| `10px` / `11px` | `var(--font-size-caption)` |
| `0.81rem` ~ `0.86rem` | `var(--font-size-body)` |

**迁移顺序**：与 P2-1 同批次执行（同文件 hex 和 font-size 一起改），减少文件往返。

**验证**：
```powershell
node scripts/audit-ui-tokens.mjs --check-font-floor
cd Code/frontend; npm run lint; npm run build
# grep 基线（应趋近 0）
rg "font-size:\s*0?\.[0-7]\d*rem" Code/frontend/src/ --count
rg "font-size:\s*(10|11)px" Code/frontend/src/ --count
```

**依赖**：P0-2。与 P2-1 同批次执行。

---

### P2-3：按钮变体收敛（6 种 → AppButton + IconButton）

**目标**：消除 6 种自制按钮实现，统一到 `AppButton`（文字/图标+文字）和 `IconButton`（纯图标）。

**改动方案**：

| 原变体 | 收敛到 | props |
|--------|--------|-------|
| `weather-mini-btn` | `<AppButton variant="ghost" size="xs">` | icon 通过 `#icon` slot 传入 |
| `imported-export-btn` | `<AppButton variant="secondary" size="sm">` | |
| `wind-mode-seg-btn` | `<IconButton :active="isActive" size="sm">` 或 `<SegmentedControl>`（P2-6） | |
| `weather-layer-btn` | `<AppButton variant="secondary" size="sm">` | |
| `panel-tools__btn` | `<IconButton>` | 随 P0-1 PanelDock 迁移 |
| 散布原生 `<button>` | `<AppButton>` 或 `<IconButton>` | 按场景选择 |

**改动文件**（按批次）：InfoPanel/* (P1-1 后) → LayerSidebar/* (P1-2 后) → TimelineScrubber/Panel → ModeToolbar → settings/* → data-manager/ui/* → workflow/*

**关键约束**：AppButton 的 `icon` prop 当前是字符串（emoji），需扩展为接受 `#icon` slot 传 lucide 组件。IconButton 已有 `#icon` slot。

**验证**：
```powershell
cd Code/frontend; npm run test; npm run lint; npm run build
```
手动检查：点击区域 ≥36px(md)/≥28px(sm)/≥24px(xs)；focus-visible 环一致；hover/active/disabled/loading 态一致。

**依赖**：P1-1/P1-2（拆分后文件更小，替换更安全）。

---

### P2-4：Emoji 字符 → lucide-vue-next SVG 图标

**目标**：将 UI 展示类 emoji 替换为 lucide-vue-next SVG 图标组件。

**改动文件**（仅 UI 展示类，逻辑标记类保留）：

| 文件 | emoji 用途 | lucide 替换 |
|------|-----------|-------------|
| DashboardView.vue | 面板标题图标 | `Map` / `Layers` / `Clock` / `Settings` |
| LayerSidebar.vue | 图层类型图标 | `Layers` / `Cloud` / `Box` |
| DataImportMenu.vue | 导入类型图标 | `Upload` / `FileUp` / `Database` |
| DataImportPanel.vue | 操作图标 | `Upload` / `X` / `Check` |
| RasterImportConfirmDialog.vue | 状态图标 | `AlertTriangle` / `CheckCircle` |
| DataExportPanel.vue | 导出格式图标 | `Download` / `FileDown` |
| DataWorkspace.vue | 工作区图标 | `Table` / `Layers` |

**新建文件**：

| 文件 | 用途 |
|------|------|
| `src/components/ui/icons.ts` | 统一导出项目使用的 lucide 图标组件，避免各文件分散 import |

**关键约束**：lucide-vue-next 已安装 ^0.577.0；替换时保持 `aria-label` 不变；图标尺寸与 IconButton 的 `iconSize` 对齐。

**验证**：
```powershell
cd Code/frontend; npm run lint; npm run build
```
手动检查：图标在暗色/浅色主题下可见（`currentColor` 跟随文字色）；屏幕阅读器不朗读 emoji。

**依赖**：可与 P2-3 同批次执行。

---

### P2-5：!important 削减（组件文件 30 处 → 目标 ≤5 处）

**目标**：减少组件文件中的 !important（litegraph-ui-overrides.css 的 27 处保留）。

**当前分布**：

| 文件 | !important 数 | 处理方式 |
|------|-------------|---------|
| `workflow/WorkflowTimerPanel.vue` | 6 | 提高选择器特异性替代 |
| `InfoPanel.vue` | 5 | P1-1 拆分后重新审视 |
| `ControlPanel.vue` | 4 | P0-1 迁移至 PanelDock 后审视 |
| `data-manager/ui/DataExportPanel.vue` | 5 | 提高特异性 |
| `workflow/WorkflowLeftSidebar.vue` | 2 | 提高特异性 |
| `workflow/WorkflowRightSidebar.vue` | 2 | 提高特异性 |
| `MapCanvas.vue` | 2 | 提高特异性 |
| `ui/PanelDock.vue` | 2 | 用属性选择器替代 |
| `LoginView.vue` | 2 | 提高特异性 |

**策略**：用更精确的选择器（如 `.panel-dock--bottom .panel-dock__body`）替代 `!important`；折叠态用 `[data-collapsed="true"]` 属性选择器。

**验证**：
```powershell
rg "!important" Code/frontend/src/components/ --count
# 排除 litegraph-ui-overrides.css 后应 ≤5
cd Code/frontend; npm run lint; npm run build
```

**依赖**：P0-1、P1-1。

---

### P2-6：提取分段控件组件 SegmentedControl（可选）

**目标**：InfoPanel 的 `wind-mode-seg-btn` 和 ModeToolbar 的模式切换都是分段控件，提取为通用组件。

**新建文件**：

| 文件 | 用途 |
|------|------|
| `src/components/ui/SegmentedControl.vue` | 分段选择控件：`options` prop（label/value/icon）、`modelValue` v-model、互斥高亮、键盘方向键导航 |
| `Test/frontend/components/segmented-control.test.ts` | 单测：选项切换、键盘导航、disabled 选项 |

**改动文件**：InfoPanelWeatherTab.vue（P1-1 拆分后）和 ModeToolbar.vue 中的分段控件替换为 `<SegmentedControl>`。

**验证**：
```powershell
cd Code/frontend; npm run test -- segmented-control
cd Code/frontend; npm run lint; npm run build
```

**依赖**：P1-1、P2-3。

---

### P2-7：Select 组件建设

**目标**：当前项目缺少统一的 Select 下拉组件，多处使用原生 `<select>` 或自定义实现。

**新建文件**：

| 文件 | 用途 |
|------|------|
| `src/components/ui/Select.vue` | 统一下拉选择：`modelValue`/`options`/`placeholder`/`size`/`disabled`/`block` props；`--surface-sunken` 底 + `--border-default` 边框；下拉面板 `--surface-3` + `--elevation-3`；lucide `ChevronDown` 箭头；`role="listbox"`/`role="option"`/`aria-selected`；键盘上下键导航 |
| `Test/frontend/components/ui/select.test.ts` | 单测 |

**验证**：
```powershell
cd Code/frontend; npm run test -- select
cd Code/frontend; npm run lint; npm run build
```
手动检查：键盘 Tab/Enter/上下键/Escape；暗色/浅色主题。

**依赖**：无前置。

---

## 三、Finish & Verify — P3 收尾验证

### P3-1：无障碍审计

**目标**：对重构后的主要界面进行 WCAG AA 合规检查。

**检查清单**：

| 检查项 | 方法 | 标准 |
|--------|------|------|
| 文本对比度 | Chrome DevTools Accessibility panel | 正常文本 ≥4.5:1，大文本 ≥3:1 |
| 焦点可见性 | 键盘 Tab 遍历 | focus-visible 环 ≥2px，对比度 ≥3:1 |
| 触控目标 | 测量可点击元素 | ≥36px（`--touch-min`） |
| 标题层级 | DOM 检查 | h1 → h2 → h3 无跳级 |
| 按钮语义 | grep `<div.*@click` | 无 div 模拟按钮 |
| aria-label | 检查所有 IconButton | 有 label |
| 表单标签 | 检查 TextField 与 label 关联 | label for 或 aria-labelledby |

**验证**：用 Chrome DevTools Accessibility panel 对 `localhost:5175` 做全页扫描；纯键盘完成图层切换/面板拖拽/tab 切换/导出操作全流程。

**依赖**：P1/P2 全部完成后。

---

### P3-2：性能验证

**目标**：确认重构未引入性能退化，且有改善。

**指标**：

| 指标 | 测量方法 | 目标 |
|------|---------|------|
| 首次加载 JS bundle | `npm run build` 后看 dist/assets 体积 | 不增大（拆分后应略减） |
| InfoPanel 首次渲染 | Chrome Performance profile | 比基线快（4097 行 → 350 行壳 + 懒加载子组件） |
| 主题切换耗时 | Chrome Performance profile | <100ms |
| Lighthouse Performance | Chrome Lighthouse | ≥90（desktop） |

**改动**：若需懒加载子组件，在壳中用 `defineAsyncComponent`。

**依赖**：P1/P2 全部完成后。

---

### P3-3：文档更新

**改动/新建文件**：

| 文件 | 改动 |
|------|------|
| `Docs/03-规范协议/frontend-design-system.md`（新建） | Token 层结构、组件清单（含新增 Select/SegmentedControl）、PanelDock props API、按钮使用规范、断点约定、数据色豁免清单 |
| `src/components/ui/README.md`（新建） | 组件库索引：每个组件的 props/事件/slot/使用示例 |
| `.uicraft.md`（项目根新建） | UICraft 设计上下文：品牌色、排版基线、动效哲学、断点约定 |

**依赖**：P0-P2 全部完成后。

---

### P3-4：最终全量验证

**验证命令**（按 AGENTS.md「改 X 则跑 Y」映射）：
```powershell
cd Code/frontend; npm run test
cd Code/frontend; npm run lint
cd Code/frontend; npm run build
cd Code/frontend; npm run check:catalog
cd Code/frontend; npm run check:openapi
node scripts/audit-ui-tokens.mjs > token-final.txt
```

**手动回归清单**：
- [ ] 登录页 → Dashboard 加载
- [ ] 图层面板：展开/折叠/搜索/拖拽排序/右键菜单
- [ ] 地图：平移/缩放/图层叠加/天气瓦片渲染
- [ ] 信息面板：四 tab 切换/天气 provider/导出
- [ ] 时间线：播放/暂停/步进/拖拽
- [ ] 工作流编辑器：节点拖拽/连线/保存/运行
- [ ] 设置页：各设置面板/数据源/系统状态
- [ ] 数据工作区：导入/导出/属性表
- [ ] 面板拖拽/缩放/折叠/持久化（刷新恢复）
- [ ] 暗色 → 浅色主题切换（全界面无退化）
- [ ] 768px / 1024px 断点布局正确
- [ ] 纯键盘完成核心操作流程

---

## 四、任务依赖关系图

```
P0-1 PanelDock 收敛 ──────┬──→ P1-3 断点归一化（ControlPanel 删除后减少一处）
                          ├──→ P1-4 DashboardView 拆分
                          ├──→ P2-3 按钮收敛（panel-tools__btn 随迁）
                          └──→ P2-5 !important 削减（PanelDock 的 2 处）
P0-2 Token 迁移基础设施 ──┬──→ P1-1 InfoPanel 拆分（审计脚本前后对比）
                          ├──→ P1-2 LayerSidebar 拆分
                          ├──→ P2-1 hex→Token 迁移（全部批次）
                          └──→ P2-2 font-size 迁移
P1-1 InfoPanel 拆分 ──────┬──→ P2-1a InfoPanel hex 迁移
                          ├──→ P2-2a InfoPanel font-size 迁移
                          ├──→ P2-3a InfoPanel 按钮收敛
                          ├──→ P2-4 InfoPanel emoji 替换
                          └──→ P2-5 InfoPanel !important 削减
P1-2 LayerSidebar 拆分 ───┬──→ P2-1b LayerSidebar hex 迁移
                          ├──→ P2-2b LayerSidebar font-size 迁移
                          └──→ P2-3b LayerSidebar 按钮收敛
P2-7 Select 组件 ─────────┘（独立，无前置）
P2-3 按钮收敛 ─────────────┬──→ P2-6 SegmentedControl 提取
P2-4 Emoji 替换 ───────────┘
P0-P2 全部完成 ───────────→ P3-1 无障碍审计 → P3-2 性能验证 → P3-3 文档 → P3-4 最终验证
```

**可并行批次**：
- P0-1 与 P0-2 完全独立，可并行。
- P1-1 与 P1-2 独立（不同文件），可并行。
- P1-3 与 P1-1/P1-2 可并行。
- P2-1c~h（TimelineScrubber/MapCanvas/settings/workflow/data-manager）与 P2-1a/b 可并行。
- P2-3 与 P2-4 可同批次执行。
- P2-7（Select 组件）独立无前置，任何阶段可做。

---

## 五、风险汇总

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| PanelDock 吸收 ControlPanel 逻辑后，localStorage key 格式不兼容导致用户布局丢失 | 高 | 保持 `geo-panel:{panelKey}` 格式不变；PersistedPanelState 接口字段完全继承 |
| InfoPanel 拆分时子组件间状态共享断裂（7 个 store 引用分散） | 高 | composable 集中 store 订阅；子组件通过 props 接收只读数据，emit 事件回传 |
| hex→token 映射不精确导致浅色主题对比度退化 | 中 | 每批次迁移后用 Chrome DevTools 对比度检查；token-map.ts 标注每对映射的语义角色 |
| 非标断点修改后布局在 768px/1024px 临界点抖动 | 中 | 逐文件修改后立即在对应断点手动验证；先改 CSS 媒体查询，再改 JS innerWidth 比较 |
| 按钮收敛时 AppButton `icon` prop 类型不兼容 lucide 组件 | 中 | 优先用 `#icon` slot 传 lucide 组件；AppButton API 向后兼容字符串 icon |
| 数据可视化色被误迁移到 token | 高 | lint 规则文件级豁免；审计脚本路径白名单排除；token-map.ts 文档中明确豁免清单 |
| Vue 3 composable 在异步回调中调用导致警告 | 中 | composable 在 setup() 同步调用，pointer 事件只操作 ref 不调 composable |
| `control-panel-geometry.ts` 纯函数被重写破坏现有测试 | 中 | 明确复用不改写；PanelDock 直接 import 现有 6 个函数 |

---

## 六、度量基线与验收标准

| 指标 | 基线（当前） | 验收目标 | 度量方法 |
|------|------------|---------|---------|
| 硬编码 hex（UI 装饰色） | ~530 处 / 30 文件 | ≤20 处 | `node scripts/audit-ui-tokens.mjs` |
| 低于 12px floor 的 font-size | ~298 处 / 20 文件 | 0 处 | 审计脚本 `--check-font-floor` |
| 非标断点 | 6 处 | 0 处 | `rg "(820\|900\|1100)px" src/` |
| !important（排除 litegraph） | 30 处 | ≤5 处 | `rg "!important" src/components/` 减去 litegraph 27 |
| 面板容器变体 | 5 种 | 2 种（PanelDock + Card） | 文件存在性检查 |
| 按钮变体 | 6 种自制类名 | 0 种 | grep 自制类名 |
| InfoPanel.vue 行数 | 4097 | <400 | 行数统计 |
| LayerSidebar.vue 行数 | 2649 | <400 | 行数统计 |
| DashboardView.vue 行数 | 1513 | <400 | 行数统计 |
| Emoji（UI 展示） | 8+ 文件 | 0 文件 | 人工审查 |
| 前端测试 | 全量通过 | 全量通过 | `npm run test` |
| Lint | — | 全量通过 | `npm run lint` |
| Build | — | 全量通过 | `npm run build` |
| Catalog 检查 | — | 通过 | `npm run check:catalog` |
| OpenAPI 检查 | — | 通过 | `npm run check:openapi` |
| WCAG AA 对比度 | 部分失败 | 全部通过 | Chrome DevTools Accessibility |
| Lighthouse Performance | 未测量 | ≥90（desktop） | Chrome Lighthouse |

---

本计划遵循 UICraft 工作流：先纠正结构（面板容器收敛、大文件拆分、断点归一化），再精炼表达（hex→token、font-size floor、按钮/图标统一、!important 削减），最后收尾验证（无障碍、性能、文档）。数据可视化语义色（weather-render.ts、layer-symbology.ts）和第三方库覆写（litegraph-ui-overrides.css）全程豁免。`control-panel-geometry.ts` 纯函数复用不改写。
