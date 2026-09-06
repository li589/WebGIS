# CGDA 前端重构/UI优化综合方案 V3（2026-08-12）

> 基于 V2 计划执行审计 + UI优化计划 + P2 Backlog 交叉验证后合并更新。
> V2 真源：`2026-08-12-frontend-refactoring-v2.md`
> UI优化真源：`ui-optimization-and-basemap-audit-plan.md`
> P2 Backlog 真源：`2026-08-12-p2-backlog-plan.md`

---

## 一、V2 计划执行审计：实际状态快照（2026-08-12）

### 已完成项（超出 V2 预期）

| V2 任务 | V2 状态 | V3 实测 | 证据 |
|---------|---------|---------|------|
| P2-5 !important 削减 | ⚠️ 部分完成(18处) | ✅ **完成** | 仅剩 2 处(LoginView `prefers-reduced-motion`，合理保留)；27 处在 litegraph-ui-overrides.css(豁免) |
| D2 god store 拆分(P2 Backlog) | ❌ 未开始 | ✅ **完成** | `stores/layers/index.ts` = 161 行(原 4464 行)；三域拆分到位 |
| icons.ts 统一导出 | ❌ 不存在 | ✅ **已存在** | `src/components/ui/icons.ts` 文件已在 |
| P0-P1 结构纠正(11项) | ✅ | ✅ 确认 | InfoPanel 333行/LayerSidebar 353行/DashboardView 423行 |

### 剩余项（V3 修正后的实际数据）

| 任务 | V2 基线 | V3 实测 | 变化 |
|------|---------|---------|------|
| P2-1 硬编码 hex → Token | 584处/62文件 | ~78处(.vue) + ~30处(.css/.ts) ≈ **~108处/25文件** | ↓ 81%（大量已迁移） |
| P2-3 按钮变体收敛 | 46处/4种 | **22处/4文件** | ↓ 52%（部分已收敛） |
| P2-4 Emoji → lucide SVG | 38处/25文件 | **67处/24文件** | ↑（V2 用窄匹配，V3 宽匹配覆盖更全） |
| P2-6 SegmentedControl | 不存在 | **不存在** | 待新建 |
| TimelineScrubber 拆分 | 1250行 | **1250行** | 未动 |
| 设计系统文档 | 3份待建 | **3份待建** | 未动 |
| P3-4 最终全量验证 | 待执行 | **待执行** | 依赖剩余项完成 |

### 预存阻断项（必须在 Wave 1 修复）

| 问题 | 文件 | 影响 |
|------|------|------|
| `vue/return-in-computed-property` lint error | `ui/IconButton.vue` L40 | lint 非零退出 |
| `TileSourceConfig.overlayUrlTemplate` build error | `map/basemap-module.ts` L56/L230 | vue-tsc/build 非零退出 |

> 2026-08-12 global-code-review 报告 lint 0 errors / build OK，但 p2-quick-wins 报告预存错误。
> 需在执行前重新验证当前 HEAD 状态。

---

## 二、综合方案：6 个 Wave

### 执行依赖图

```
Wave 0 (预存阻断修复) ──────► 解除 lint/build 门
  │
  ├── Wave 1 (Token 迁移收尾) ──────► ~108处 hex → var(--token)
  │     └── Wave 1b (UI优化: 登录页/加载动画/日志面板)
  │
  ├── Wave 2 (组件收敛) ──────► SegmentedControl + 按钮变体(22处) + emoji(67处)
  │
  ├── Wave 3 (TimelineScrubber 拆分) ──────► 1250行 → <400行 + 子组件
  │
  └── Wave 4 (文档 + 最终验证) ──────► 设计系统文档 + 全量回归
```

**可并行**：Wave 1 与 Wave 1b 可并行；Wave 2 与 Wave 3 可并行（不同文件域）。

---

### Wave 0：预存阻断修复（0.5 人日）

**目标**：解除 lint/build 非零退出，为后续所有 Wave 打开质量门。

| 序 | 文件 | 问题 | 修法 |
|----|------|------|------|
| 0-1 | `ui/IconButton.vue` L40 | computed 属性缺少 return 分支 | 补全 return 或改用三元的写法 |
| 0-2 | `map/basemap-module.ts` L56/L230 | `TileSourceConfig.overlayUrlTemplate` 属性不存在 | 在 `services/api-config.ts` 的 `TileSourceConfig` 接口补充 `overlayUrlTemplate?: string` |

**验证**：
```powershell
cd Code/frontend
npm run lint   # 0 errors
npm run build  # 0 errors
```

---

### Wave 1：Token 迁移收尾（2-3 人日）

**目标**：~108 处硬编码 hex → `var(--token)`；rgba() 表达式迁移。

#### 1.1 迁移范围（按文件 hex 密度降序）

| 批次 | 文件 | hex 估数 | rgba 估数 | 备注 |
|------|------|---------|---------|------|
| W1-a | `MapCanvas.vue` | 15 | 31 | 排除 WebGL 渲染色（weather-render.ts 等） |
| W1-b | `LoadingOverlay.vue` | 5 | 9 | hero 动画色彩 |
| W1-c | `LoginView.vue` | 3 | 10 | 登录页（与 Wave 1b 合并执行） |
| W1-d | `DataSourceSettings.vue` | 15 | — | |
| W1-e | `GeneralSettings.vue` | 6 | — | |
| W1-f | `OpenMeteoSyncSettings.vue` | 4 | — | |
| W1-g | `NodeCacheDialog.vue` | 7 | — | |
| W1-h | `AppErrorBoundary.vue` | 3 | — | |
| W1-i | `ScienceRasterImportDialog.vue` | — | 2 | |
| W1-j | `ModeToolbar.vue` | — | 5 | |
| W1-k | `main.css` | 5 | — | 全局样式残余 |
| W1-l | `InfoPanel.styles.css` | 需核实 | — | 集中样式文件 |
| W1-m | `LayerSidebar.styles.css` | 需核实 | — | 集中样式文件 |
| W1-n | `TimelineScrubber.vue` | 2 | — | 拆分前先迁移 |
| W1-o | 其余散布文件（各 1-4 处） | ~30 | — | 逐个处理 |

#### 1.2 迁移规则

使用已有 `token-map.ts` 映射表。核心映射：

| hex/rgba 模式 | 目标 token | 语义 |
|--------------|-----------|------|
| `#f0faff` / `#dfeefe` | `var(--text-strong)` / `var(--text-primary)` | 高亮文字 |
| `#9fb6cc` / `#8aa8bf` | `var(--text-secondary)` / `var(--text-muted)` | 次要文字 |
| `#5ad5ff` / `#88dfff` | `var(--accent)` / `var(--accent-strong)` | 强调色 |
| `#020814` / `#040c17` | `var(--surface-base)` | 最深背景 |
| `rgba(8,17,31,0.86)` | `var(--surface-1)` | 浮层表面 |
| `rgba(13,23,39,0.92)` | `var(--surface-2)` | 面板表面 |
| `rgba(136,192,255,0.16)` | `var(--border-default)` | 默认边框 |
| `rgba(90,213,255,0.12)` | `var(--accent-surface)` | 强调背景 |
| `#9ff8cf` / `#ff8c64` / `#ffb070` | `var(--success)` / `var(--danger)` / `var(--warning)` | 状态色 |

**豁免清单**（不迁移）：
- `styles/tokens.css` — Token 定义文件本身
- `styles/token-map.ts` — 映射表本身
- `map/weather-render.ts` — 数据可视化调色板
- `map/layer-symbology.ts` — 图层符号化调色板
- `map/wind-particle-webgl-shaders.ts` / `scalar-field-webgl-shaders.ts` — WebGL 着色器
- `workflow/litegraph-ui-overrides.css` — 第三方库覆写

#### 1.3 验证（每批次后）
```powershell
cd Code/frontend
npm run lint && npm run build
```

---

### Wave 1b：UI 优化任务（1.5-2 人日，与 Wave 1 可并行）

> 来源：`ui-optimization-and-basemap-audit-plan.md`

#### 1b-1 登录页视觉升级（LoginView.vue）

| 项 | 改动 |
|----|------|
| 品牌图标 | Unicode `◎` → SVG 地球图标（lucide Globe 或内联 SVG） |
| 字号统一 | label→`var(--font-size-caption)`(12px)，input→`var(--font-size-body)`(13px) |
| 玻璃态增强 | 提升 backdrop-blur，优化边框渐变 |
| 入场动画 | 卡片上浮+淡入（尊重 `prefers-reduced-motion`） |
| Hex 迁移 | 与 W1-c 合并，10 处 rgba → token |

#### 1b-2 日志面板优化（LogPanel.vue + log store）

| 项 | 改动 |
|----|------|
| 右上角 badge | 显示 `errorCount`（非总条数）；≥100 显示 "99+" |
| 错误为 0 时 | 不显示 badge 或中性色 |
| 字号统一 | badge/条目/时间戳 → 设计令牌 |
| 面板内样式 | 间距/颜色/滚动条适配新令牌 |

#### 1b-3 加载动画兼容性检查

| 文件 | 检查项 |
|------|--------|
| `Skeleton.vue` | sweep 动画颜色令牌化、12px 下限 |
| `InlineLoader.vue` | 字号≥12px、颜色令牌化 |
| `LoadingOverlay.vue` | hero 动画在修改后 CSS 变量下正常、`prefers-reduced-motion` |
| `MapCanvas.vue` 内置 skeleton | 硬编码颜色→令牌、与通用 Skeleton 视觉统一 |
| `DataImportMenu.vue` spinner | 同上 |

#### 1b-4 截图/数据组件样式适配

| 文件 | 改动 |
|------|------|
| `ScreenshotExport.vue` | 字号→令牌、硬编码 padding→CSS 变量、颜色令牌化 |
| `DataImportMenu.vue` | 全局非 scoped `.import-dropdown` → scoped 或唯一前缀；字号/间距令牌化 |

---

### Wave 2：组件收敛 + Emoji 清理（2-3 人日）

#### 2.1 新建 SegmentedControl.vue

**文件**：`src/components/ui/SegmentedControl.vue`

**API**：
- Props: `modelValue` / `options: { label, value, icon? }[]` / `size` / `disabled`
- Emits: `update:modelValue` / `change`
- 键盘：方向键导航、Enter 确认、Tab 跳出
- 视觉：互斥高亮、`--accent-surface` 选中态、`--surface-1` 未选中态

**测试**：`Test/frontend/components/ui/segmented-control.test.ts`

#### 2.2 按钮变体收敛（22 处 → 0）

| 原变体 | 收敛到 | 使用数 | 涉及文件 |
|--------|--------|--------|---------|
| `weather-mini-btn` | `<AppButton variant="ghost" size="xs">` | ~7 | InfoPanelMetaTab, InfoPanelVisualTab, InfoPanelToolsTab |
| `imported-export-btn` | `<AppButton variant="secondary" size="sm">` | ~7 | InfoPanelMetaTab |
| `wind-mode-seg-btn` | `<SegmentedControl>` | ~4 | InfoPanelStyleTab |
| `weather-layer-btn` | `<AppButton variant="secondary" size="sm">` | ~4 | InfoPanelStyleTab, InfoPanelMetaTab, InfoPanelToolsTab |

**CSS 清理**：`InfoPanel.styles.css` 中 15 处 class 定义删除。

**约束**：
- 保持 `aria-label` 不变
- 点击区域 ≥24px(xs) / ≥28px(sm) / ≥36px(md)
- AppButton `#icon` slot 传 lucide 组件

#### 2.3 Emoji → lucide SVG（67 处 / 24 文件）

按密度分批：

| 批次 | 文件 | emoji 数 | 替换映射 |
|------|------|---------|---------|
| W3-a | `WorkflowNodePalette.vue` | 15 | ☀→Sun, ⚙→Settings, 🌍→Globe 等 |
| W3-b | `SettingsPanel.vue` | 7 | ⚙→Settings, ⚠→AlertTriangle 等 |
| W3-c | `WeatherProviderSettings.vue` | 6 | ⚙→Settings, ⚠→AlertTriangle |
| W3-d | `WorkflowStatusPanel.vue` | 6 | ⚙→Settings, ⚠→AlertTriangle |
| W3-e | `WorkflowInspector.vue` | 3 | ☀→Sun, ⚡→Zap, 🌍→Globe |
| W3-f | `DataImportPanel.vue` | 3 | ✕→X, ⚠→AlertTriangle |
| W3-g | `node-forms/*.vue`（5 文件） | 10 | ✓→Check, ⚠→AlertTriangle |
| W3-h | 剩余 15 文件（各 1-2 处） | 17 | 逐个替换 |

**约束**：
- 逻辑标记类 emoji（如条件渲染中的 `✓`）需检查是否为 UI 展示
- lucide 使用 `currentColor`，自动适配暗色/浅色主题
- 图标 `aria-label` 保持与原 emoji 语义一致

---

### Wave 3：TimelineScrubber 拆分（2-3 人日，与 Wave 2 可并行）

**目标**：1250 行 → 壳 <400 行 + 子组件/composable

#### 3.1 拆分方案

| 新文件 | 提取内容 | 预估行数 |
|--------|---------|---------|
| `src/components/timeline/TimelineScrubberBar.vue` | 滑块主体、刻度、拖拽交互 | ~300 |
| `src/components/timeline/TimelineAvailabilityTrack.vue` | 可用性条 `role="meter"` | ~150 |
| `src/components/timeline/TimelineControls.vue` | 播放/暂停/前进/后退 + 粒度切换 | ~200 |
| `src/components/timeline/TimelineLabel.vue` | 时间标签 + 日期导航 | ~100 |
| `src/components/timeline/useTimelineScrubble.ts` | 拖拽状态、step 计算、键盘交互 | ~250 |
| `src/components/timeline/TimelineScrubber.styles.css` | 专有样式 | ~200 |
| `TimelineScrubber.vue`（壳） | 组件组合 + props/emit 声明 | ~200 |

#### 3.2 关键约束

- `role="slider"` + `aria-valuemin/max/now` 语义化
- 键盘：左右箭头微调(1 step)、上下箭头大调(10 step)、Home/End 跳首尾
- 复用 AppButton/IconButton 替代原生按钮
- Vue 3 composable 在 `setup()` 同步调用
- 拆分前确保 Wave 1 的 hex 迁移已完成（W1-n）

---

### Wave 4：文档 + 最终验证（1-2 人日）

#### 4.1 文档补建

| 文件 | 内容 |
|------|------|
| `Docs/03-规范协议/frontend-design-system.md` | Token 层结构、组件清单（含 SegmentedControl）、PanelDock API、按钮规范、断点约定、数据色豁免清单 |
| `src/components/ui/README.md` | 组件库索引：每个组件的 props/事件/slot/使用示例 |
| `.uicraft.md`（项目根） | UICraft 设计上下文：品牌色、排版基线、动效哲学 |

#### 4.2 最终全量验证

```powershell
cd Code/frontend
npm run test           # 全量 vitest
npm run lint           # 0 errors
npm run build          # 0 errors
npm run check:catalog  # 图层目录一致性
npm run check:openapi  # 前后端契约一致性
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

## 三、验收标准

| 指标 | V2 基线 | V3 实测基线 | 验收目标 | 度量方法 |
|------|---------|-----------|---------|---------|
| 硬编码 hex（UI 装饰色） | 584处 | ~108处 | ≤20处 | grep + 审计脚本 |
| !important（排除 litegraph） | 18处 | 2处(合理) | ≤5处 | grep 验证 |
| 自制按钮 class | 4种/46处 | 4种/22处 | 0种 | grep 验证 |
| Emoji（UI 展示） | 38处/25文件 | 67处/24文件 | 0处 | 人工审查 |
| TimelineScrubber.vue 行数 | 1250 | 1250 | <400 | 行数统计 |
| SegmentedControl | 不存在 | 不存在 | 存在且有测试 | 文件 + npm test |
| 设计系统文档 | 不存在 | 不存在 | 3份文档 | 文件存在性 |
| icons.ts | 不存在 | **已存在** | 存在 | 文件存在性 |
| god store 行数 | 4464 | 161 | <200 | 行数统计 |
| lint errors | 1(预存) | 1(预存) | 0 | `npm run lint` |
| build errors | 1(预存) | 1(预存) | 0 | `npm run build` |
| 前端测试 | 632 passed | 632 passed | 全量通过 | `npm run test` |
| Catalog 检查 | OK | OK | 通过 | `npm run check:catalog` |
| OpenAPI 检查 | OK | OK | 通过 | `npm run check:openapi` |

---

## 四、工作量估算

| Wave | 任务 | 估算（人日） | 依赖 |
|------|------|------------|------|
| Wave 0 | 预存阻断修复 | 0.5 | 无 |
| Wave 1 | Hex 迁移收尾 ~108处 | 2-3 | Wave 0 |
| Wave 1b | UI优化(登录/日志/加载/截图) | 1.5-2 | Wave 0（与 Wave 1 并行） |
| Wave 2 | SegmentedControl + 按钮收敛 + Emoji | 2-3 | Wave 0 |
| Wave 3 | TimelineScrubber 拆分 | 2-3 | Wave 1 完成后（W1-n hex 迁移） |
| Wave 4 | 文档 + 最终验证 | 1-2 | Wave 1-3 全部完成 |
| **合计** | | **9-13.5 人日** | |

> 相比 V2 的 11-17 人日，V3 因多项已完成（!important、god store、icons.ts）和工作量缩减（hex 584→108）而减少 ~30%。

---

## 五、风险与注意事项

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| hex→token 映射不精确导致浅色主题对比度退化 | 高 | 每批次迁移后 Chrome DevTools 对比度检查；token-map.ts 语义角色标注 |
| 数据可视化色被误迁移 | 高 | 豁免清单 + lint 规则文件级排除 |
| SegmentedControl 与 wind-mode-seg-btn 交互行为不一致 | 中 | 先写测试再迁移；保持键盘行为一致 |
| TimelineScrubber 拆分后时间轴播放/拖拽退化 | 高 | 拆分前 composable 覆盖所有交互路径；逐方法迁移并测试 |
| Emoji 替换后 lucide 在浅色主题下可见性 | 低 | lucide 使用 `currentColor`，自动跟随文字色 |
| 预存 lint/build error 修复引入回归 | 中 | Wave 0 修复后立即跑全量 test + build 验证 |
| node/npx 不在系统 PATH | 中 | 使用 `Code/frontend/node_modules/.bin/` 下的本地工具或配置 PATH |

---

## 六、执行优先级建议

```
Wave 0 (0.5d) ──────────────────────────────────────► 解除质量门
  │
  ├── Wave 1 (2-3d) ── Hex 迁移收尾 ────────────────┐
  │                                                   ├── 可并行
  ├── Wave 1b (1.5-2d) ── UI 优化 ──────────────────┘
  │
  ├── Wave 2 (2-3d) ── 组件收敛 + Emoji ───────────────► 与 Wave 3 可并行
  │
  ├── Wave 3 (2-3d) ── TimelineScrubber 拆分 ──────────► 依赖 Wave 1 (W1-n)
  │
  └── Wave 4 (1-2d) ── 文档 + 最终验证 ────────────────► 依赖全部完成
```

**建议执行顺序**（单人）：
1. Wave 0 → 2. Wave 1 + Wave 1b（并行）→ 3. Wave 2 → 4. Wave 3 → 5. Wave 4

**建议执行顺序**（双人并行）：
- 人 A: Wave 0 → Wave 1 → Wave 3
- 人 B: Wave 0 后 → Wave 1b → Wave 2 → Wave 4

---

## 七、与 P2 Backlog 的关系

本方案仅覆盖**前端**重构与 UI 优化。P2 Backlog 中的后端项（安全加固、架构收敛、并发可靠性、测试覆盖）独立排期，不与本方案冲突。

**已完成的 P2 项**（V3 确认）：
- D2 god store 拆分 ✅（前端，`stores/layers/index.ts` = 161 行）
- P2-5 !important 削减 ✅（仅剩 2 处合理保留）

**P2 Backlog 中仍需关注的前端相关项**：
- D1 store 反向 import components/map（`weather-tile-manager.ts` / `layers/index.ts` / `overlay-symbology.ts`）— Wave 1 完成后评估
- G3-02 `weather-tile-manager.ts` 2064 行过大 — 后续独立拆分
- P-02 前端时间轴 seek — 可与 Wave 3 TimelineScrubber 拆分合并实现

---

本方案基于 V2 计划的执行审计 + UI优化计划 + P2 Backlog 交叉验证后合并更新。V2 的结构纠正阶段（P0-P1）已全部完成，!important 削减与 god store 拆分在 V2 之后已完成。剩余工作集中在 Token 迁移收尾（量已大幅减少）、组件/Emoji 统一、TimelineScrubber 拆分、UI 视觉优化与文档补建。
