# CGDA 前端重构方案 V2（2026-08-12）

> 基于 V1 计划（`frontend-ui-refactoring-plan.md` + `frontend-refactoring-plan-uicraft.md`）的执行审计结果更新。
> 工作流：Correct Structure（已完成）→ Refine Expression（进行中）→ Finish & Verify

---

## 一、执行审计：V1 计划完成情况

### 已完成（11 项）

| V1 任务 | 完成状态 | 实测结果 |
|---------|---------|---------|
| P0-1 面板容器收敛 | ✅ | BasePanel/ControlPanel/CompositePanel 已删除；PanelDock + usePanelDragResize 到位；TimelinePanel 74 行薄封装 |
| P0-2 Token 迁移基础设施 | ✅ | `token-map.ts` + `audit-ui-tokens.mjs` + `migrate-tokens.mjs` + `migrate-font-sizes.mjs` 均已就位 |
| P1-1 InfoPanel.vue 拆分 | ✅ | 4281 行 → 333 行（壳）；6 composables + 5 Tab 子组件在 `info-panel/` |
| P1-2 LayerSidebar.vue 拆分 | ✅ | 2910 行 → 353 行（壳）；5 composables + 4 子组件在 `layer-sidebar/` |
| P1-3 非标断点归一化 | ✅ | 6 处 → 0 处（仅剩 1 处非媒体查询的 `max-height: 900px`） |
| P1-4 DashboardView.vue 拆分 | ✅ | 1659 行 → 423 行；7 composables 在 `views/dashboard/` |
| P2-7 AppSelect 组件 | ✅ | AppSelect.vue 已建；39 个原生 `<select>` 全部迁移；业务 .vue 中 0 个裸 `<select>` |
| P3-1 无障碍审计 | ✅ | 18 个问题已修复（aria-label、role、tabindex、focus-visible） |
| P3-2 性能验证 | ✅ | vue-tsc 0 errors / ESLint 0 errors / build 1.49s / 632 tests |
| P3-3 文档更新 | ✅ | 重构总结报告已生成 |
| 字号 floor 统一 | ✅ | 低于 0.8rem 的 font-size：0 处 |

### 剩余工作（6 项 + 3 项新增）

| V1 任务 | 当前状态 | 实测数据 |
|---------|---------|---------|
| P2-1 硬编码 hex → Token | ❌ 未开始 | 584 处 / 62 文件 |
| P2-3 按钮变体收敛 | ❌ 未开始 | 4 种自制 class / 46 处使用，全部在 `info-panel/` |
| P2-4 Emoji → lucide SVG | ❌ 未开始 | 38 处 / 25 文件（指定集合）；119 处 / 40 文件（宽泛集合） |
| P2-5 !important 削减 | ⚠️ 部分完成 | 18 处 / 6 文件（目标 ≤5） |
| P2-6 SegmentedControl 组件 | ❌ 未开始 | 组件不存在；wind-mode-seg-btn 8 处待收敛 |
| P3-4 最终全量验证 | ❌ 待执行 | 需在剩余工作完成后执行 |
| **新增** TimelineScrubber 拆分 | ❌ 未开始 | 1250 行，需拆至 <400 行/文件 |
| **新增** icons.ts 统一导出 | ❌ 未开始 | 无统一 lucide 图标导出文件 |
| **新增** 设计系统文档 | ❌ 未开始 | `frontend-design-system.md` / `ui/README.md` / `.uicraft.md` 待建 |

---

## 二、剩余工作详细方案

### Wave 1：Token 迁移（P2-1 + P2-5）— 最大工作量

**目标**：584 处硬编码 hex → `var(--token)`；18 处 !important → ≤5 处

#### 1.1 Hex 迁移分批方案（按 hex 密度降序）

| 批次 | 文件 | hex 数 | 前置依赖 | 备注 |
|------|------|--------|---------|------|
| W1-a | `TimelineScrubber.vue` | 38 | 无 | 拆分前先迁移（减少拆分后文件数） |
| W1-b | `workflow/WorkflowStatusPanel.vue` | 34 | 无 | |
| W1-c | `workflow/WorkflowEditorPanel.vue` | 30 | 无 | |
| W1-d | `MapCanvas.vue`（UI 层 hex） | 28 | 无 | 排除 WebGL 渲染色 |
| W1-e | `settings/DataSourceSettings.vue` | 25 | 无 | |
| W1-f | `workflow/PipelineLauncher.vue` | 24 | 无 | |
| W1-g | `settings/WeatherProviderSettings.vue` | 21 | 无 | |
| W1-h | `settings/OpenMeteoSyncSettings.vue` | 19 | 无 | |
| W1-i | `workflow/WorkflowCanvas.vue` | 18 | 无 | |
| W1-j | `workflow/WorkflowRunDialog.vue` | 17 | 无 | |
| W1-k | `data-manager/ui/AttributeTable.vue` | 17 | 无 | |
| W1-l | `data-manager/ui/DataImportPanel.vue` | 16 | 无 | |
| W1-m | `workflow/WorkflowNodePalette.vue` | 16 | 无 | |
| W1-n | `data-manager/ui/ScienceRasterImportDialog.vue` | 14 | 无 | |
| W1-o | `data-manager/ui/DataExportPanel.vue` | 14 | 无 | |
| W1-p | `info-panel/InfoPanel.styles.css` | ~80 | 无 | 拆分后集中样式文件 |
| W1-q | `layer-sidebar/LayerSidebar.styles.css` | ~50 | 无 | 拆分后集中样式文件 |
| W1-r | 剩余 47 个文件（各 1-12 处） | ~165 | 无 | 散布文件，逐个处理 |

**迁移规则**（使用已有 `token-map.ts`）：

| hex 模式 | 目标 token | 语义 |
|----------|-----------|------|
| `#f0faff` / `#dfeefe` / `#d5e5f5` | `var(--text-strong)` / `var(--text-primary)` | 高亮文字 |
| `#9fb6cc` / `#8cb5d9` / `#6a8094` | `var(--text-secondary)` / `var(--text-muted)` | 次要文字 |
| `#5ad5ff` / `#2f7eff` | `var(--accent)` / `var(--accent-strong)` | 强调色 |
| `#020814` / `#040c17` | `var(--surface-base)` | 最深背景 |
| `rgba(8,17,31,0.86)` / `rgba(8,18,33,0.xx)` | `var(--surface-1)` | 面板表面 |
| `rgba(13,23,39,0.92)` / `rgba(13,23,39,0.xx)` | `var(--surface-2)` | 浮层表面 |
| `rgba(136,192,255,0.16)` / `rgba(136,192,255,0.xx)` | `var(--border-default)` / `var(--border-subtle)` | 边框 |
| `rgba(90,213,255,0.12)` / `rgba(90,162,255,0.xx)` | `var(--accent-surface)` / `var(--border-accent)` | 强调背景 |
| `#7dffb3` / `#ffb0b0` / `#ffd166` | `var(--success)` / `var(--danger)` / `var(--warning)` | 状态色 |

**豁免清单**（不迁移）：
- `map/weather-render.ts` — 数据可视化调色板
- `map/layer-symbology.ts` — 图层符号化调色板
- `map/wind-particle-webgl-shaders.ts` / `scalar-field-webgl-shaders.ts` — WebGL 着色器
- `workflow/litegraph-ui-overrides.css` — 第三方库覆写

**验证**（每批次）：
```powershell
cd Code/frontend; node scripts/audit-ui-tokens.mjs --baseline
cd Code/frontend; npm run lint; npm run build
```

#### 1.2 !important 削减方案

| 文件 | 当前 | 目标 | 策略 |
|------|------|------|------|
| `workflow/WorkflowTimerPanel.vue` | 6 | 2 | 保留全屏嵌入覆盖；提高选择器特异性替代其余 |
| `ui/PanelDock.vue` | 4 | 2 | 保留最大化覆盖；属性选择器替代折叠态 |
| `MapCanvas.vue` | 2 | 0 | 用 `hidden` 属性或 `v-show` 替代 `opacity: 0 !important` |
| `LoginView.vue` | 2 | 1 | 保留 `prefers-reduced-motion` 覆盖 |
| `workflow/WorkflowLeftSidebar.vue` | 2 | 0 | 用响应式布局替代 |
| `workflow/WorkflowRightSidebar.vue` | 2 | 0 | 用响应式布局替代 |

---

### Wave 2：组件收敛（P2-3 + P2-6 + icons.ts）

**目标**：4 种自制按钮 class → AppButton/IconButton；新建 SegmentedControl；统一 lucide 图标导出

#### 2.1 新建 `icons.ts`

**文件**：`src/components/ui/icons.ts`

统一导出项目使用的 lucide-vue-next 图标组件，避免各文件分散 import。包含：
- 通用：`Sun` `Zap` `Globe` `AlertTriangle` `Lock` `Settings` `GripVertical` `Check` `X` `Map` `Layers` `Clock` `Upload` `Download` `FileUp` `Database` `Table` `Box` `Cloud`
- 工作流：`Sun` `Zap` `Globe`（引擎类型）`Settings`（引擎配置）`AlertTriangle`（警告）
- 替代 emoji：`Check` `X` `AlertTriangle` `Search` `ChevronDown` 等

#### 2.2 新建 `SegmentedControl.vue`

**文件**：`src/components/ui/SegmentedControl.vue`

**API**：
- Props: `modelValue` / `options: { label, value, icon? }[]` / `size` / `disabled`
- Emits: `update:modelValue` / `change`
- 键盘：方向键导航、Enter 确认、Tab 跳出
- 视觉：互斥高亮、`--accent-surface` 选中态、`--surface-1` 未选中态

**测试**：`Test/frontend/components/ui/segmented-control.test.ts`

#### 2.3 按钮变体收敛

| 原变体 | 收敛到 | 使用数 | 涉及文件 |
|--------|--------|--------|---------|
| `weather-mini-btn` | `<AppButton variant="ghost" size="xs">` | 12 | InfoPanelMetaTab(5), InfoPanelVisualTab(3), InfoPanelToolsTab(2) + CSS(2) |
| `imported-export-btn` | `<AppButton variant="secondary" size="sm">` | 14 | InfoPanelMetaTab(12) + CSS(2) |
| `wind-mode-seg-btn` | `<SegmentedControl>` | 8 | InfoPanelStyleTab(1) + CSS(7) |
| `weather-layer-btn` | `<AppButton variant="secondary" size="sm">` | 12 | InfoPanelStyleTab(6), InfoPanelMetaTab(1), InfoPanelToolsTab(1) + CSS(4) |

**改动文件**：
- `src/components/info-panel/InfoPanelMetaTab.vue`
- `src/components/info-panel/InfoPanelStyleTab.vue`
- `src/components/info-panel/InfoPanelToolsTab.vue`
- `src/components/info-panel/InfoPanelVisualTab.vue`
- `src/components/info-panel/InfoPanel.styles.css`（删除对应 class 定义）

**关键约束**：
- AppButton 需支持 `#icon` slot 传 lucide 组件（已有）
- 替换时保持 `aria-label` 不变
- 点击区域 ≥24px(xs) / ≥28px(sm) / ≥36px(md)

---

### Wave 3：Emoji 清理（P2-4）

**目标**：38 处 UI 展示 emoji → lucide-vue-next SVG 图标

#### 3.1 按文件分批

| 批次 | 文件 | emoji 数 | 替换映射 |
|------|------|---------|---------|
| W3-a | `workflow/WorkflowNodePalette.vue` | 3 | ☀→Sun, ⚙→Settings, 🌍→Globe |
| W3-b | `workflow/WorkflowInspector.vue` | 3 | ☀→Sun, ⚡→Zap, 🌍→Globe |
| W3-c | `workflow/WorkflowStatusPanel.vue` | 2 | ⚙→Settings, ⚠→AlertTriangle |
| W3-d | `workflow/node-forms/*.vue`（5 个文件） | 10 | ✓→Check, ⚠→AlertTriangle |
| W3-e | `settings/WeatherProviderSettings.vue` | 2 | ⚙→Settings, ⚠→AlertTriangle |
| W3-f | `data-manager/ui/*.vue`（5 个文件） | 6 | ✕→X, ⚠→AlertTriangle |
| W3-g | `layer-sidebar/LayerSidebarLibrary.vue` | 2 | ✓→Check |
| W3-h | 剩余 11 个文件（各 1 处） | 10 | 逐个替换 |

**关键约束**：
- 逻辑标记类 emoji（如 `✓` 用于条件渲染标记）需检查是否为 UI 展示
- 替换后图标 `aria-label` 保持与原 emoji 语义一致
- 图标尺寸与 IconButton 的 `iconSize` 对齐

---

### Wave 4：TimelineScrubber 拆分

**目标**：1250 行 → 壳 <400 行 + 子组件/composable

#### 4.1 拆分方案

| 新文件 | 提取内容 | 预估行数 |
|--------|---------|---------|
| `src/components/timeline/TimelineScrubberBar.vue` | 滑块主体、刻度、拖拽交互 | ~300 |
| `src/components/timeline/TimelineAvailabilityTrack.vue` | 可用性条 `role="meter"` | ~150 |
| `src/components/timeline/TimelineControls.vue` | 播放/暂停/前进/后退按钮 + 粒度切换 | ~200 |
| `src/components/timeline/TimelineLabel.vue` | 时间标签显示 + 日期导航 | ~100 |
| `src/components/timeline/useTimelineScrubble.ts` | 拖拽状态、step 计算、键盘交互 composable | ~250 |
| `src/components/timeline/TimelineScrubber.styles.css` | 专有样式（38 处 hex 在 Wave 1 迁移后） | ~200 |
| `TimelineScrubber.vue`（壳） | 组件组合 + props/emit 声明 | ~200 |

**关键约束**：
- `role="slider"` + `aria-valuemin/max/now` 语义化
- 键盘：左右箭头微调（1 step）、上下箭头大调（10 step）、Home/End 跳首尾
- 复用 AppButton/IconButton 替代原生按钮
- Vue 3 composable 在 `setup()` 同步调用

---

### Wave 5：文档与最终验证（P3-3 补全 + P3-4）

#### 5.1 文档补建

| 文件 | 内容 |
|------|------|
| `Docs/03-规范协议/frontend-design-system.md` | Token 层结构、组件清单（含 SegmentedControl）、PanelDock API、按钮规范、断点约定、数据色豁免清单 |
| `src/components/ui/README.md` | 组件库索引：每个组件的 props/事件/slot/使用示例 |
| `.uicraft.md`（项目根） | UICraft 设计上下文：品牌色、排版基线、动效哲学 |

#### 5.2 最终全量验证

```powershell
cd Code/frontend
npm run test
npm run lint
npm run build
npm run check:catalog
npm run check:openapi
node scripts/audit-ui-tokens.mjs --baseline
```

**手动回归清单**：
- [ ] 登录页 → Dashboard 加载
- [ ] 图层面板：展开/折叠/搜索/拖拽排序/右键菜单
- [ ] 地图：平移/缩放/图层叠加/天气瓦片渲染
- [ ] 信息面板：四 tab 切换/天气 provider/导出
- [ ] 时间线：播放/暂停/步进/拖拽/键盘
- [ ] 工作流编辑器：节点拖拽/连线/保存/运行
- [ ] 设置页：各设置面板/数据源/系统状态
- [ ] 数据工作区：导入/导出/属性表
- [ ] 面板拖拽/缩放/折叠/持久化
- [ ] 暗色 → 浅色主题切换
- [ ] 768px / 1024px 断点布局
- [ ] 纯键盘完成核心操作

---

## 三、执行顺序与依赖

```
Wave 1 (Token 迁移 + !important)
  ├── W1-a TimelineScrubber hex ──┐
  ├── W1-b~o 各组件 hex ──────────┤
  ├── W1-p InfoPanel.styles.css ──┤
  ├── W1-q LayerSidebar.styles ───┤
  └── W1-r 散布文件 hex ──────────┘
                ↓
Wave 2 (组件收敛)
  ├── 2.1 icons.ts ──────────────┐
  ├── 2.2 SegmentedControl ──────┤
  └── 2.3 按钮变体收敛 ──────────┘
                ↓
Wave 3 (Emoji 清理) ─── 依赖 Wave 2 的 icons.ts
                ↓
Wave 4 (TimelineScrubber 拆分) ─── 依赖 Wave 1 的 hex 迁移
                ↓
Wave 5 (文档 + 最终验证)
```

**可并行**：
- Wave 1 各批次之间可并行（不同文件）
- Wave 2 的 icons.ts 和 SegmentedControl 可并行
- Wave 3 可在 Wave 2 完成后与 Wave 4 并行

---

## 四、验收标准

| 指标 | 当前基线 | 验收目标 | 度量方法 |
|------|---------|---------|---------|
| 硬编码 hex（UI 装饰色） | 584 处 / 62 文件 | ≤20 处 | `node scripts/audit-ui-tokens.mjs` |
| 低于 0.8rem font-size | 0 处 | 0 处 | 审计脚本 `--check-font-floor` |
| 非标断点 | 0 处 | 0 处 | grep 验证 |
| !important（排除 litegraph） | 18 处 | ≤5 处 | grep 验证 |
| 自制按钮 class | 4 种 / 46 处 | 0 种 | grep 验证 |
| Emoji（UI 展示） | 38 处 / 25 文件 | 0 处 | 人工审查 |
| TimelineScrubber.vue 行数 | 1250 | <400 | 行数统计 |
| SegmentedControl 组件 | 不存在 | 存在且有测试 | 文件存在性 + `npm run test` |
| icons.ts | 不存在 | 存在 | 文件存在性 |
| 设计系统文档 | 不存在 | 3 份文档 | 文件存在性 |
| 前端测试 | 全量通过 | 全量通过 | `npm run test` |
| Lint | — | 通过 | `npm run lint` |
| Build | — | 通过 | `npm run build` |
| Catalog 检查 | — | 通过 | `npm run check:catalog` |
| OpenAPI 检查 | — | 通过 | `npm run check:openapi` |

---

## 五、风险与注意事项

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| hex→token 映射不精确导致浅色主题对比度退化 | 高 | 每批次迁移后用 Chrome DevTools 对比度检查；token-map.ts 标注语义角色 |
| 数据可视化色被误迁移 | 高 | 审计脚本路径白名单排除；lint 规则文件级豁免 |
| SegmentedControl 与现有 wind-mode-seg-btn 交互行为不一致 | 中 | 新建后先写测试再迁移；保持键盘行为一致 |
| TimelineScrubber 拆分后时间轴播放/拖拽行为退化 | 高 | 拆分前确保 composable 覆盖所有交互路径；逐个方法迁移并测试 |
| Emoji 替换后 lucide 图标在暗色/浅色主题下可见性 | 低 | lucide 使用 `currentColor`，自动跟随文字色 |
| Wave 1 工作量大（584 处 hex）导致中途质量下降 | 中 | 分批次执行，每批次完成后验证 build + lint；可使用 `migrate-tokens.mjs` 脚本辅助 |

---

## 六、工作量估算

| Wave | 任务 | 估算（人日） |
|------|------|------------|
| Wave 1 | Hex 迁移 584 处 + !important 削减 | 5-7 |
| Wave 2 | icons.ts + SegmentedControl + 按钮收敛 | 2-3 |
| Wave 3 | Emoji 替换 38+ 处 | 1-2 |
| Wave 4 | TimelineScrubber 拆分 | 2-3 |
| Wave 5 | 文档 + 最终验证 | 1-2 |
| **合计** | | **11-17 人日** |

---

本方案基于 V1 计划的执行审计结果更新。V1 的结构纠正阶段（P0-P1）已全部完成，剩余工作集中在表达精炼（hex→token、按钮/图标统一、emoji 替换）和一个遗留大文件拆分（TimelineScrubber）。数据可视化语义色和第三方库覆写全程豁免。
