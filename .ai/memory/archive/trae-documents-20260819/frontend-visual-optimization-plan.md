# CGDA 前端视觉优化实施计划

## 概述

基于 UICraft 技能的「审计 → 修正结构 → 精炼表达 → 验证」工作流，将 14 项视觉问题按 P0-P3 优先级分四阶段执行。标杆组件为 `ModeToolbar.styles.css`（设计令牌一致、focus-visible 完整、仅 1 处硬编码颜色）和 `WorkflowStatusButton.vue`（完整使用 motion/ease token、prefers-reduced-motion 完整）。

### 量化审计摘要

| 维度 | 审计结果 |
|------|---------|
| 硬编码 `rgba()` | InfoPanel 54 处、LayerSidebar 35 处、MapCanvas 34 处、WorkflowEditorPanel 24 处 |
| 硬编码 `X.XXs ease` | 全组件目录 214 处，跨 30 个文件 |
| `:focus-visible` 覆盖 | 仅 10 个文件有，4 大目标面板均缺失 |
| `prefers-reduced-motion` 覆盖 | 26 个文件有，InfoPanel.styles.css 和 WorkflowNodePalette.vue 缺失 |
| 无视觉变化 hover | MapCanvas `.locate-error-close`、InfoPanel `.weather-mini-btn`、LayerSidebar `.category-header`、SettingsPanel `.session-chip` |

---

## 阶段一（P0）：动效令牌统一与硬编码颜色清除

### 为什么先做

动效时长和缓动函数的不一致导致整体界面节奏混乱——同一 hover 动画在不同组件中以不同速度和曲线运行。硬编码 `rgba()` 绕过了 tokens.css 的主题系统，导致浅色主题切换时部分元素不跟随。这是结构性问题，必须在装饰性优化之前解决。

### 1.1 动效时长统一

**目标文件（4 个）：**
- `Code/frontend/src/components/info-panel/InfoPanel.styles.css`（18 处）
- `Code/frontend/src/components/MapCanvas.styles.css`（18 处）
- `Code/frontend/src/components/layer-sidebar/LayerSidebar.styles.css`（38 处）
- `Code/frontend/src/components/workflow/WorkflowEditorPanel.vue`（21 处）

**映射规则：**

| 硬编码值 | 替换为 | 语义 |
|---------|-------|------|
| `0.12s` / `0.14s` / `0.15s` / `0.16s` | `var(--motion-fast)` (120ms) | 微交互：颜色、边框、背景切换 |
| `0.18s` / `0.2s` / `0.22s` | `var(--motion-base)` (200ms) | 标准交互：面板展开、位移、阴影 |
| `0.24s` / `0.28s` / `0.35s` / `0.45s` | `var(--motion-slow)` (320ms) | 大幅位移、透明度渐变、进度条 |

特殊情况：`0.01s ease`（强制即时切换）保留为 `1ms`；`0.08s`（拖拽即时反馈）映射为 `var(--motion-fast)`；`linear` 保留不替换（用于 keyframes 旋转/循环）。

### 1.2 缓动函数统一

将所有 `ease` 和裸 `cubic-bezier(...)` 替换为 token：
- `ease` → `var(--ease-standard)`（90% 的 hover/transition）
- `cubic-bezier(0.25, 0.46, 0.45, 0.94)` → `var(--ease-standard)`
- `cubic-bezier(0.22, 1, 0.36, 1)` → `var(--ease-emphasized)`

### 1.3 硬编码 rgba 颜色清除

**目标文件（4 个）：** 同 1.1 的 4 个文件 + `tokens.css`

**分类处理策略：**

- **A 类（直接映射现有 token）**：`rgba(90, 213, 255, 0.12)` → `var(--accent-surface)`，`rgba(90, 213, 255, 0.3)` → `var(--accent-border)`
- **B 类（语义匹配但数值偏差）**：统一到 token 值（偏差通常 0.02-0.04，视觉无感知）
- **C 类（无对应 token）**：在 tokens.css 新增 token：
  ```css
  :root {
    --surface-blue-tint: rgba(90, 162, 255, 0.10);
    --border-blue-tint: rgba(90, 162, 255, 0.16);
    --surface-violet-tint: rgba(126, 168, 255, 0.14);
    --border-violet-tint: rgba(126, 168, 255, 0.18);
    --shadow-ambient: rgba(1, 8, 16, 0.14);
    --shadow-ambient-strong: rgba(0, 0, 0, 0.24);
  }
  ```
  以及对应的 `[data-theme='light']` 覆盖。
- **D 类（MapCanvas 氛围渐变）**：新增氛围 token：
  ```css
  :root {
    --ambient-blue-glow: rgba(66, 130, 255, 0.14);
    --ambient-blue-soft: rgba(82, 134, 255, 0.12);
    --ambient-warm-glow: rgba(255, 196, 120, 0.12);
  }
  [data-theme='light'] {
    --ambient-blue-glow: rgba(30, 100, 180, 0.10);
    --ambient-blue-soft: rgba(30, 100, 180, 0.08);
    --ambient-warm-glow: rgba(201, 122, 20, 0.08);
  }
  ```
- **E 类（LoadingOverlay 硬编码）**：`rgba(0, 0, 0, 0.55)` → `var(--shadow-ambient-strong)`；`rgba(136, 223, 255, 0.12)` → `var(--accent-surface)`

### 1.4 `transition: all` 精确化

将 `transition: all 0.16s ease`（WorkflowEditorPanel 3 处、SettingsPanel 1 处、NodePalette 1 处）改为明确属性列表，减少不必要的样式计算。

### 验证

1. 深色/浅色主题下逐页截图对比（地图主界面、工作流编辑器、加载状态）
2. Grep 验证目标文件中硬编码动效值大幅减少
3. 主题切换测试：确认之前硬编码颜色的元素现在跟随主题变化
4. `npm run lint`

### 性能

纯 token 替换不改变渲染属性，零性能影响。统一后浏览器可更好地复用样式规则缓存。

---

## 阶段二（P1）：无障碍与交互状态补全

### 为什么在 P0 之后

token 统一后，交互状态样式可基于一致的 token 体系编写，避免二次返工。

### 2.1 `:focus-visible` 样式补全

**目标文件（4 个）：**
- `MapCanvas.styles.css` — 约 8 个选择器
- `InfoPanel.styles.css` — 约 15 个选择器
- `LayerSidebar.styles.css` — 约 12 个选择器
- `SettingsPanel.vue` — 约 3 个选择器

统一模式（参照 ModeToolbar.styles.css）：
```css
<selector>:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
```

### 2.2 `prefers-reduced-motion` 补全

**目标文件（2 个）：**
- `InfoPanel.styles.css`（完全缺失）— 追加 `@media (prefers-reduced-motion: reduce)` 块，禁用所有 transition
- `WorkflowNodePalette.vue`（完全缺失）— 同上，并禁用 hover transform

### 2.3 修复无视觉变化的 hover 状态

**A. MapCanvas `.locate-error-close:hover`**
- 问题：hover 时 `color: var(--danger)` 与默认相同
- 修复：改为 `color: var(--accent-strong)` + `transform: translateY(-1px)` + `:active` 复位

**B. InfoPanel `.weather-mini-btn:hover`**
- 问题：hover 时 `border-color: var(--border-strong)` 与默认相同
- 修复：改为 `border-color: var(--accent-border)` + `background: var(--accent-surface)` + `color: var(--accent)`

**C. LayerSidebar `.category-header:hover`**
- 问题：hover 时 `background: var(--surface-sunken)` 与默认相同
- 修复：改为 `background: var(--surface-hover)`

**D. SettingsPanel `.session-chip:hover`**
- 问题：hover 时 border-color 和 background 与默认完全相同
- 修复：改为 `border-color: var(--success)` + `background: var(--success-border)`

### 验证

1. Tab 键键盘导航：确认每个可交互元素获得焦点时有清晰 outline
2. 鼠标悬停 4 个修复的元素：确认有明显视觉变化
3. 系统开启「减少动态效果」：确认 InfoPanel 和 NodePalette 所有 transition 被禁用
4. `npm run lint && npm run test`

### 性能

`:focus-visible` 仅键盘聚焦时触发；`transition: none` 减少动画计算；hover 修改使用 transform/background-color/border-color，均为低代价属性。

---

## 阶段三（P2）：动画体验补全

### 为什么在 P1 之后

属于「精炼表达」阶段，需要在结构（token）和基础交互（focus/hover）就绪后进行。

### 3.1 WorkflowNodePalette 分类展开/折叠高度动画

**目标文件：** `WorkflowNodePalette.vue`

将 `v-if` 硬切换改为 `grid-template-rows: 0fr → 1fr` CSS 动画方案（零 JS 测量）：
```css
.category-items {
  display: grid;
  grid-template-rows: 1fr;
  transition: grid-template-rows var(--motion-base) var(--ease-standard),
              opacity var(--motion-base) var(--ease-standard);
  overflow: hidden;
}
.category-items.collapsed {
  grid-template-rows: 0fr;
  opacity: 0;
}
```

### 3.2 litegraph-ui-overrides.css 菜单入场动画

**目标文件：** `litegraph-ui-overrides.css`

追加 CSS 入场动画（菜单动态创建/移除 DOM，无法用 Vue Transition）：
```css
.litegraph.litecontextmenu { animation: litegraph-menu-enter var(--motion-fast) var(--ease-decelerate); }
.litegraph.graphdialog { animation: litegraph-dialog-enter var(--motion-fast) var(--ease-decelerate); }

@keyframes litegraph-menu-enter {
  from { opacity: 0; transform: translateY(-4px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
```
含 `prefers-reduced-motion` 降级。

### 3.3 WorkflowEditorPanel 按钮 `:active` 按压反馈

**目标文件：** `WorkflowEditorPanel.vue`

为所有 button 类元素添加统一的 `:active` 反馈（使用 `translateY(1px)` 而非 `scale`）：
```css
.header-btn:active,
.dialog-btn:active,
.validation-action-btn:active {
  transform: translateY(1px);
  box-shadow: inset 0 1px 3px var(--shadow-ambient);
}
```
含 `prefers-reduced-motion` 降级。

### 3.4 LoadingOverlay 主题适配与 z-index 修正

**目标文件：** `LoadingOverlay.vue` + `tokens.css`

- **z-index 统一**：tokens.css 新增 `--z-loading: 200`，替换硬编码 `9999`/`9998`
- **硬编码颜色清除**（与阶段一 C/E 类配合）
- **`.sat-body` 渐变修正**：`linear-gradient(135deg, var(--warning), var(--warning))` → `linear-gradient(135deg, var(--warning), var(--accent-warm))`
- **`.loading-fade` transition 统一**：`0.22s ease` → `var(--motion-base) var(--ease-standard)`

### 验证

1. NodePalette 分类展开/折叠有平滑高度过渡（约 200ms），reduce-motion 下直接显示/隐藏
2. litegraph 右键菜单有轻微向下滑入效果
3. 工作流编辑器按钮点击有 1px 下沉反馈
4. LoadingOverlay 遮罩正确覆盖所有面板，浅色主题下颜色正确
5. `npm run lint && npm run build`

### 性能

`grid-template-rows` 动画仅启动时触发一次 layout；菜单 `scale` 入场创建临时合成层，移除后释放；`translateY(1px)` 仅合成层变换。

---

## 阶段四（P3）：视觉精炼与收尾验证

### 4.1 间距 token 注释校正

**目标文件：** `tokens.css`

修正注释为实际语义（保留数值，零风险）：
```css
/* ═══ 间距（近似 4px 基数，经光学微调） ═══ */
--space-1: 0.22rem; /* 3.3px — 极紧（光学微调） */
```

### 4.2 `.reduce-motion` 选择器简化

**目标文件：** `MapCanvas.styles.css`

用 `:is()` 合并多层 `:not()` 长链选择器：
```css
/* 改前 — 5 个选择器各带 :not() 长链 */
/* 改后 */
.map-stage.map-stage-global-view:not(.map-stage-distribution)
  :is(.map-fog, .time-sheen, .time-band, .weather-overlay, .grid-overlay) {
  opacity: 0 !important;
}
```

### 4.3 全量验证

1. `npm run lint && npm run test && npm run build`
2. `npm run check:openapi && npm run check:catalog`
3. 视觉回归矩阵：深色/浅色主题下逐页检查（地图、信息面板、图层侧栏、工作流编辑器、设置面板、加载状态）
4. 无障碍扫描：axe DevTools 或 Lighthouse，确认 focus visible + 颜色对比度 WCAG AA
5. reduce-motion 全量验证：所有 hover/transition 被禁用，无布局跳变
6. 性能验证：Chrome DevTools Performance 录制，确认无长任务（>50ms）

---

## 总结矩阵

| 阶段 | 优先级 | 核心目标 | 涉及文件数 | 关键改动 |
|------|--------|---------|-----------|---------|
| 一 | P0 | token 统一化 | 5 | ~147 处硬编码 rgba → token；~95 处硬编码时长/缓动 → token |
| 二 | P1 | 无障碍补全 | 4 | ~38 个 `:focus-visible`；2 个 `prefers-reduced-motion` 块；4 个 hover 修复 |
| 三 | P2 | 动画体验 | 5 | v-if→grid 动画；菜单入场；`:active` 反馈；z-index/主题修正 |
| 四 | P3 | 视觉精炼 | 2 | 注释校正；`:is()` 简化；全量回归验证 |
| **合计** | — | — | **~12 个独立文件** | — |

## 全局性能策略

1. **优先合成层属性**：所有动画使用 `transform`/`opacity`/`filter`，避免 `width`/`height` 动画（`grid-template-rows` 是唯一例外）
2. **GPU 加速提示**：保留现有 `will-change` 和 `translateZ(0)`，不新增不必要的 `will-change`
3. **contain 属性**：保持 MapCanvas 的 `contain: layout style paint` 和 InfoPanel 的 `contain: layout style`
4. **避免 `transition: all`**：改为明确属性列表
5. **reduce-motion 差异化**：LoadingOverlay「放慢而非停止」，其他组件直接禁用
