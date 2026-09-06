# CGDA 前端 UI 视觉设计增强 — 商业级提升实施计划

## 摘要

本计划对 CGDA（综合地理数据分析系统）前端进行四个阶段的视觉设计增强：排版基础设施升级（字体族替换 + 五档字重）、视觉纹理与氛围营造（噪点叠层 + 玻璃拟态深度 + 动画渐变边框）、组件视觉精炼（9 个 UI 组件的 `<style scoped>` 增强）、微交互编排（面板错开入场 + 列表项错开 + 空状态视觉化）。所有改动不改变组件 API，通过现有 CSS token 系统实施，保持暗/浅色主题对等，遵循 `prefers-reduced-motion` 降级。

## 现状分析

### 技术栈
Vue 3 + TypeScript + Vite + Pinia；MapLibre 2D 地图；Cesium 3D（实验性）；lucide-vue-next 图标；ECharts 图表；litegraph.js 工作流编辑器。

### 已有设计系统
- **Token 系统**：`src/styles/tokens.css` 定义了完整的暗/浅色主题 token（颜色分层、间距、字号、动效、elevation、z-index），注释标注"发布就绪 V1.0 — 商业级升级"
- **Token 审计**：`src/styles/token-map.ts` + `audit:tokens` 脚本 + ESLint 规则，禁止组件内联 hex
- **UI 组件库**：AppButton、Card、Chip、IconButton、PanelDock、SegmentedControl、Tabs、TextField、Tooltip、Skeleton
- **主题系统**：`stores/theme.ts`，dark/light/system 三模式
- **动效哲学**：克制（120–320ms）、缓出、有物理感（translateY / shadow 不用 scale）

### 当前弱点（对照 frontend-design 技能指南）
1. **字体**：使用 `Inter, 'Segoe UI', 'PingFang SC'` — Inter 被技能指南明确标注为"AI 通用字体"，缺乏辨识度
2. **字重**：仅 400/500 两档，`--font-weight-semibold` 和 `--font-weight-bold` 均映射到 500，排版层级扁平
3. **纹理**：背景为纯渐变，缺乏噪点/颗粒/微图案等触感纹理
4. **微交互**：限于基础 hover transform，无错开入场、无编排式动画
5. **组件视觉**：功能完备但视觉表达保守，缺少渐变边框、内发光、光泽扫过等商业级细节
6. **空状态**：纯文本，缺乏视觉化表达

## 设计方向

**精密科学仪器（Precision Scientific Instrument）**

参考高端天文台控制台、气象监测站、卫星地面站的操作界面美学。深空蓝青主基调不变，通过纹理、字体、微交互提升到"科研级精密工具"的视觉质感。紧凑布局、信息密度高、水平对齐优先。

## 实施计划

### 阶段一：排版基础设施（Typography Foundation）

**目标**：替换通用字体栈，建立五档字重层级，引入等宽数据字体。

#### 1.1 字体加载

**文件**：`Code/frontend/index.html`

在 `<head>` 中添加 Google Fonts 预连接和加载链接：
- **Sora**（可变字体，300-700 权重）— 几何无衬线，技术感与几何特征，小尺寸下可读性优异，与 Inter/Space Grotesk 有明确视觉区分度
- **IBM Plex Mono**（400/500/600 三档）— 等宽数据字体，科研数据展示场景的技术权威感

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
```

**内网备选**：如 Google Fonts 不可达，将字体文件下载至 `src/assets/fonts/`，通过 `@font-face` 本地引用。

#### 1.2 Token 更新

**文件**：`Code/frontend/src/styles/tokens.css`

在 `:root` 中：
- 新增字体族 token：`--font-sans`（Sora + 中文回退）、`--font-mono`（IBM Plex Mono + 回退）
- 字重从两档扩展为五档：`--font-weight-light: 300`、`--font-weight-regular: 400`、`--font-weight-medium: 500`、`--font-weight-semibold: 600`、`--font-weight-bold: 700`
- **关键**：移除现有 `--font-weight-semibold: 500` 和 `--font-weight-bold: 500` 别名映射，解除压缩

#### 1.3 全局字体应用

**文件**：`Code/frontend/src/styles/main.css`

将 `:root` 的 `font-family` 从硬编码 `Inter, 'Segoe UI', ...` 替换为 `var(--font-sans)`。

#### 1.4 等宽字体应用

在数据展示场景引入 `var(--font-mono)` + `font-variant-numeric: tabular-nums`：
- `TimelineScrubber`：时间标签、步长值
- `InfoPanel`：坐标读数、数值参数
- `LogPanel`：日志时间戳
- `WorkflowInspector` / `ParamField`：节点参数值
- `LayerSidebar`：图层 ID、数据源标识

#### 1.5 字重层级应用

| 组件 | 当前 | 目标 | 说明 |
|------|------|------|------|
| LoginView `.brand-copy h1` | bold(500) | bold(700) | 标题视觉冲击力增强 |
| LoginView `.eyebrow` | semibold(500) | semibold(600) | 标签辨识度增强 |
| Card `.app-card__title` | medium(500) | semibold(600) | 卡片标题层级提升 |
| DashboardView `.placeholder-3d-title` | semibold(500) | semibold(600) | 实际权重增强 |
| AppButton | medium(500) | 保持 500 | 按钮字重不变 |

**风险**：字重别名解除后，所有引用 `--font-weight-semibold`/`--font-weight-bold` 的组件将从 500 变为 600/700。需全局搜索引用清单，逐个检查 12px caption 在 700 字重下是否过粗。

**验证**：`cd Code/frontend && npm run audit:tokens && npm run lint`

---

### 阶段二：视觉纹理与氛围（Visual Texture & Atmosphere）

**目标**：为暗色玻璃拟态界面注入微妙纹理质感与深度。

#### 2.1 噪点纹理叠层

**新建文件**：`Code/frontend/src/styles/textures.css`

使用 SVG `feTurbulence` 生成噪点，内联为 data URI（避免额外网络请求），`position: fixed` + `pointer-events: none` + 4% 透明度全屏覆盖。暗色模式 `mix-blend-mode: screen`，浅色模式 `mix-blend-mode: overlay` + 3% 透明度。

**文件**：`Code/frontend/src/styles/main.css` — 在 `@import './tokens.css'` 后添加 `@import './textures.css'`

**文件**：`Code/frontend/src/App.vue` — 在 `<div class="page-shell">` 内最底层添加 `<div class="noise-overlay" aria-hidden="true"></div>`

#### 2.2 微几何图案

**文件**：`Code/frontend/src/styles/textures.css`

添加 `.micro-grid`（24px 网格线）和 `.dot-matrix`（16px 点阵）工具类，用于面板背景纹理和数据空状态。

#### 2.3 Glassmorphism 深度增强

**文件**：`Code/frontend/src/components/ui/PanelDock.vue`

添加 `::before` 伪元素作为顶部高光条（LoginView 已有先例），在表面背景中增加极淡径向渐变层模拟光线折射。

**文件**：`Code/frontend/src/components/ui/Card.vue`

使用 `mask-composite: exclude` 技术添加渐变边框（LoginView 的 `.login-card::before` 已验证此技术可用），标题栏底部分割线升级为渐变。

#### 2.4 CSS @property 动画渐变边框

**文件**：`Code/frontend/src/styles/textures.css`

注册 `@property --gradient-angle`，配合 `conic-gradient` 实现可动画化渐变边框。仅用于 hover/focus-active 状态，避免常驻动画性能开销。`@media (prefers-reduced-motion: reduce)` 中禁用。

#### 2.5 Token 扩展

**文件**：`Code/frontend/src/styles/tokens.css`

新增：`--noise-opacity-dark: 0.04`、`--noise-opacity-light: 0.03`、`--grid-pattern-size: 24px`、`--dot-pattern-size: 16px`

**验证**：`cd Code/frontend && npm run audit:tokens && npm run lint && npm run build`

---

### 阶段三：组件视觉精炼（Component Polish）

**目标**：逐个提升 UI 组件视觉质感。所有改动仅增强 `<style scoped>`，不改变组件 API。

#### 3.1 AppButton

**文件**：`Code/frontend/src/components/ui/AppButton.vue`

- Primary 变体：纯色背景 → 微妙渐变 `linear-gradient(135deg, var(--accent), var(--accent-strong))` + 内高光
- Hover：添加 `::after` 光泽扫过效果（gradient sweep，200% background-size，motion-slow 过渡）
- Focus-visible：增加发光环

#### 3.2 Card

**文件**：`Code/frontend/src/components/ui/Card.vue`

- 渐变边框（mask-composite 技术）
- 标题栏底部分割线渐变（`::after` 伪元素，左右内缩 `var(--space-4)`）
- Hover：elevation 从 1 提升到 2

#### 3.3 PanelDock

**文件**：`Code/frontend/src/components/ui/PanelDock.vue`

- 顶部高光条（`::before` 伪元素）
- 拖拽手柄 hover 增强（边框变色 + 背景变色）

#### 3.4 Chip

**文件**：`Code/frontend/src/components/ui/Chip.vue`

- 语义色变体增加内发光（`box-shadow: inset 0 0 0 1px ... , 0 0 8px ...`）
- 移除按钮 hover：`transform: scale(1.1)` + 背景变化

#### 3.5 SegmentedControl

**文件**：`Code/frontend/src/components/ui/SegmentedControl.vue`

- Active 项添加底部高光指示器（`::after` 伪元素，2px 高，25%-75% 宽度，accent 色 + 发光）

#### 3.6 Tabs

**文件**：`Code/frontend/src/components/ui/Tabs.vue`

- Tabs 变体 active 下划线增加发光（`text-shadow` + `border-bottom-color`）
- Segmented 变体 active 项增加微妙渐变背景 + elevation

#### 3.7 TextField

**文件**：`Code/frontend/src/components/ui/TextField.vue`

- Focus 状态的 `box-shadow` 从硬编码 rgba 替换为新 token `--accent-focus-ring`
- 搜索图标在 focus 时变色为 accent

#### 3.8 Skeleton

**文件**：`Code/frontend/src/components/ui/Skeleton.vue`

- 从线性渐变 sweep 升级为光泽扫过（200% background-size + shimmer 动画）

#### 3.9 新增 Token

**文件**：`Code/frontend/src/styles/tokens.css` + `token-map.ts`

新增 token：
- `--accent-focus-ring: rgba(90, 213, 255, 0.1)`（暗色）/ `rgba(10, 143, 196, 0.12)`（浅色）
- `--accent-glow-sm: 0 0 8px var(--accent-surface)`
- `--accent-glow-md: 0 0 16px var(--accent-surface)`

在 `token-map.ts` 的 `RGBA_MAP` 中添加 `--accent-focus-ring` 映射。

**验证**：`cd Code/frontend && npm run audit:tokens && npm run lint && npm run build && npm run test`

---

### 阶段四：微交互编排（Micro-interaction Choreography）

**目标**：通过 CSS-only 编排式动画注入"精密仪器响应感"。

#### 4.1 面板入场错开动画

**文件**：`Code/frontend/src/views/dashboard/DashboardView.styles.css`

为四个浮层面板添加编排式入场动画：
- `.overlay-top`：100ms 延迟，从上方滑入
- `.overlay-left`：200ms 延迟，从左侧滑入
- `.overlay-right`：300ms 延迟，从右侧滑入
- `.overlay-bottom`：400ms 延迟，从下方滑入

**关键**：`.overlay-bottom` 已有 `transform: translateX(-50%)` 居中定位，入场动画关键帧的 `to` 状态必须保持此变换。

#### 4.2 列表项错开入场

**文件**：`Code/frontend/src/components/layer-sidebar/LayerSidebarActive.vue` 及相关子组件

为图层列表项添加 `nth-child` 错开入场（50ms 步长，前 5 项递增，6+ 项不再增加延迟）。

#### 4.3 空状态视觉增强

将纯文本空状态升级为图标 + 点阵图案背景的视觉化空状态。使用阶段二的 `.dot-matrix` 纹理。

#### 4.4 Hover 工具类

**文件**：`Code/frontend/src/styles/main.css`

新增 `.hover-lift`（translateY + elevation）和 `.hover-glow`（border-color + box-shadow 发光）通用工具类。

#### 4.5 动效 Token + reduced-motion

**文件**：`Code/frontend/src/styles/tokens.css`

新增 `--motion-stagger-step: 30ms`、`--motion-enter-delay: 100ms`。

所有新增动画在 `@media (prefers-reduced-motion: reduce)` 中降级为静态。

**验证**：`cd Code/frontend && npm run audit:tokens && npm run lint && npm run build && npm run test`

---

## 依赖与顺序

```
阶段一（排版基础设施）→ 阶段二（视觉纹理）→ 阶段三（组件精炼）→ 阶段四（微交互编排）
```

- 阶段一是基础（字体变更影响所有组件的视觉度量）
- 阶段二和阶段三可部分并行，但 Card/PanelDock 的渐变边框依赖阶段二的 mask-composite 技术定义
- 阶段四依赖前三阶段完成

## 假设与决策

1. **字体来源**：假设目标部署环境可访问 Google Fonts。如内网不可达，使用本地 `@font-face` 备选方案
2. **字重别名解除**：决定移除 `--font-weight-semibold: 500` 和 `--font-weight-bold: 500` 的别名映射，引入真正的 600/700 权重。需逐个检查引用组件的视觉效果
3. **噪点叠层性能**：决定使用单个 `position: fixed` 元素全屏覆盖，不随滚动重绘，GPU 开销可控
4. **动画边框仅用于交互态**：决定 `@property` 动画渐变边框仅用于 hover/focus-active，避免常驻动画性能开销
5. **组件 API 不变**：所有改动仅增强 `<style scoped>`，不改变 props/slots/events
6. **暗/浅色主题对等**：所有新增效果在 `[data-theme='light']` 中提供对等实现

## 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 12px caption 在 700 字重下过粗 | 全局搜索 `--font-weight-bold` 引用，逐个评估；必要时在 caption 场景降级为 600 |
| Sora 可变字体文件较大（100-200KB） | 使用 `font-display: swap`；考虑 `size-adjust` 减少 FOUT 布局偏移 |
| SVG feTurbulence 噪点在低端设备影响性能 | 单个 fixed 元素不随滚动重绘；如需降级可改用 repeating-linear-gradient 模拟 |
| mask-composite 兼容性 | LoginView 已验证可用；双写 `-webkit-mask-composite: xor` 和 `mask-composite: exclude` |
| backdrop-filter 叠层过多 | 噪点叠层不使用 backdrop-filter；渐变边框伪元素用 `pointer-events: none` + `contain: layout paint` |

## 文件变更清单

### 新建
| 文件 | 内容 |
|------|------|
| `Code/frontend/src/styles/textures.css` | 噪点叠层、微几何图案、@property 动画边框系统 |

### 修改（Token 层）
| 文件 | 改动 |
|------|------|
| `Code/frontend/src/styles/tokens.css` | 字体族 token、五档字重、纹理/氛围/焦点环/发光/动效 token |
| `Code/frontend/src/styles/token-map.ts` | 添加 `--accent-focus-ring` rgba 映射 |
| `Code/frontend/src/styles/main.css` | 字体族引用、textures.css 导入、hover 工具类 |

### 修改（入口层）
| 文件 | 改动 |
|------|------|
| `Code/frontend/index.html` | Google Fonts 预连接 + Sora/IBM Plex Mono 加载 |

### 修改（组件层）
| 文件 | 改动 |
|------|------|
| `Code/frontend/src/components/ui/AppButton.vue` | primary 渐变+光泽扫过、focus 发光 |
| `Code/frontend/src/components/ui/Card.vue` | 渐变边框、标题分割线、hover elevation |
| `Code/frontend/src/components/ui/PanelDock.vue` | 顶部高光、手柄 hover 增强 |
| `Code/frontend/src/components/ui/Chip.vue` | 语义色内发光、移除按钮 hover |
| `Code/frontend/src/components/ui/SegmentedControl.vue` | active 底部指示器 |
| `Code/frontend/src/components/ui/Tabs.vue` | 下划线发光、segmented 渐变 |
| `Code/frontend/src/components/ui/TextField.vue` | focus token 化、图标变色 |
| `Code/frontend/src/components/ui/Skeleton.vue` | shimmer 升级 |

### 修改（视图层）
| 文件 | 改动 |
|------|------|
| `Code/frontend/src/views/dashboard/DashboardView.styles.css` | 面板入场错开动画 |
| `Code/frontend/src/views/LoginView.vue` | 字重应用 |
| `Code/frontend/src/components/layer-sidebar/LayerSidebarActive.vue` | 列表项错开入场 |
| `Code/frontend/src/App.vue` | 噪点叠层 div |

## 验证矩阵

| 检查项 | 命令 | 预期 |
|-------|------|------|
| Token 审计 | `npm run audit:tokens` | 无新增硬编码 hex |
| Lint | `npm run lint` | 无错误 |
| 构建 | `npm run build` | 成功 |
| 单元测试 | `npm run test` | 全部通过 |
| 暗色主题 | 手动 | 所有新增效果正确渲染 |
| 浅色主题 | 手动切换 | 对等渲染 |
| 减少动效 | 浏览器设置 | 所有动画降级 |
| WCAG AA | 对比度检查 | 正文 ≥ 4.5:1 |
| 性能 | DevTools | ≥ 50fps |
