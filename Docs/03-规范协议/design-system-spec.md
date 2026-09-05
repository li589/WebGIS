# CGDA 前端设计系统规范（商业级界面升级）

> 状态：评审稿（V0.1）— 尚未实施，供 UI / 工程评审后再落地。
> 适用范围：`Code/frontend`（Vue 3 + TS + Vite + MapLibre 深色 GIS 主题）。
> 目标：在现有「地图为核心」的沉浸式骨架上，通过**设计系统 First** 把界面提升到现代、克制、自然的商业级水平。
> 设计基调：深空蓝青（accent `#5ad5ff`）+ 玻璃层级 + 一致组件语言 + 地图优先的留白。

---

## 0. 文档目的与范围

本文档是 CGDA 前端视觉语言的**单一真源**。它定义：

- 设计令牌（颜色 / 字号 / 间距 / 圆角 / 阴影 / 动效），替换当前散落的 229 个内联 hex；
- 组件库规格（按钮 / 芯片 / 卡片 / 标签 / 面板 dock 等）；
- 图标、信息架构、状态体系与无障碍基线；
- 从现状到 token 化的分阶段迁移路径与文件映射。

**不在本文档范围**：业务逻辑、地图渲染算法、后端契约。

---

## 1. 设计原则

| 原则 | 含义 |
|---|---|
| 地图优先 | 地图是主角，UI 是浮层；chrome 让位于数据，提供「聚焦模式」一键沉浸。 |
| 玻璃层级 | 浮层用统一玻璃拟态（blur + 1px 内高光 + 低透明黑阴影），保证在亮/暗地图上都可读。 |
| 克制一致 | 字重只用 400/500 两档；圆角、间距、动效全部走 token；不引入一次性样式。 |
| 可达 | WCAG AA：正文对比度 ≥ 4.5:1，最小字号 12px，焦点环可见，尊重 `reduced-motion`。 |
| 自然 | 动效短促（120–320ms）、缓出、有物理感；hover 微抬升而非生硬变色。 |

---

## 2. 设计令牌（Design Tokens）

所有组件**必须**引用 `var(--*)`，禁止内联 hex（除一次性品牌渐变外）。迁移见 §8。

### 2.1 颜色

```css
:root {
  /* 文本 */
  --text-strong:   #f0faff;
  --text-primary:  #d8e6f5;
  --text-secondary:#9fb6cc;
  --text-muted:    #8aa8bf;
  --text-faint:    #6e8ba0;
  --text-disabled: #5a7080;

  /* 强调 / 品牌 */
  --accent:        #5ad5ff;
  --accent-strong: #88dfff;
  --accent-warm:   #ffc878;

  /* 语义状态（文字色 + 表面 + 边框三件套） */
  --success:       #9ff8cf;  --success-surface: rgba(159,248,207,.12); --success-border: rgba(159,248,207,.30);
  --warning:       #ffb070;  --warning-surface: rgba(255,176,112,.12); --warning-border: rgba(255,176,112,.30);
  --danger:        #ff8c64;  --danger-surface:  rgba(255,140,100,.12); --danger-border:  rgba(255,140,100,.30);
  --info:          var(--accent);

  /* 表面层级（暗色：越上层越亮、越不透明） */
  --surface-base:    #020814;
  --surface-sunken:  rgba(4,12,23,.60);
  --surface-1:       rgba(8,17,31,.86);   /* 浮层底，提高到 .86 保证地图强数据时可读 */
  --surface-2:       rgba(13,23,39,.92);
  --surface-3:       rgba(18,30,48,.96);
  --surface-hover:   rgba(20,40,66,.98);

  /* 边框三级 */
  --border-subtle:  rgba(136,192,255,.08);
  --border-default: rgba(136,192,255,.16);
  --border-strong:  rgba(90,213,255,.36);
  --border-accent:  rgba(90,213,255,.28);
}
```

### 2.2 字号与字重

正文下限 **12px**（商业级可读基线），取消当前 8–10px 微字。

```css
:root {
  --fs-caption: 12px;  /* 标签 / 辅助，floor */
  --fs-body:    13px;  /* 正文 */
  --fs-title:   14px;  /* 小标题 / 面板标题 */
  --fs-subtitle:16px;  /* 区块标题 */
  --fs-h2:      20px;
  --fs-h1:      24px;
}
/* 字重仅两档，体现克制 */
:root { --fw-regular: 400; --fw-medium: 500; }
```

### 2.3 间距（4 的倍数）

```css
:root {
  --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
  --sp-5: 24px; --sp-6: 32px; --sp-7: 48px;
}
```

### 2.4 圆角

```css
:root {
  --radius-sm: 6px;  --radius-md: 8px;  --radius-lg: 12px;
  --radius-xl: 16px; --radius-pill: 999px;
}
```

### 2.5 阴影 / Elevation（暗色实现）

用「低透明黑阴影 + 1px 内高光」表达层级，避免平面感的来源。

```css
:root {
  --glass-blur: 16px;                 /* 统一玻璃模糊，替代当前 12/18 不一 */
  --elevation-1: 0 1px 2px rgba(0,0,0,.30),  inset 0 1px 0 rgba(255,255,255,.04);
  --elevation-2: 0 6px 16px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.05);
  --elevation-3: 0 16px 40px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.06);
  --elevation-modal: 0 30px 70px rgba(0,0,0,.55);
}
```

### 2.6 动效

> 现行真源：`Code/frontend/src/styles/tokens.css` + `motion.css`（macOS / Apple HIG 取向）。
> 禁止硬编码 `0.2s ease` / `transition: all`；控件优先 `--motion-interactive-*` / `--motion-surface-*` / `--motion-sheet-*`。

```css
:root {
  --motion-press:  80ms;
  --motion-fast:   120ms;
  --motion-base:   200ms;
  --motion-slow:   280ms;
  --ease-standard: cubic-bezier(0.16, 1, 0.3, 1);   /* 减速出场 */
  --ease-soft:     cubic-bezier(0.25, 0.1, 0.25, 1); /* 微交互 */
  --ease-emphasized: cubic-bezier(0.22, 1, 0.36, 1);
}
```

### 2.7 层级 z-index

```css
:root {
  --z-map: 0; --z-overlay: 20; --z-panel: 24;
  --z-popover: 60; --z-modal: 80; --z-toast: 100;
}
```

---

## 3. 组件库规范

组件统一放 `Code/frontend/src/components/ui/`，props 走 TS interface，状态用 class 后缀（`--hover/--active/--disabled`）。

### 3.1 基础组件清单

| 组件 | 用途 | 关键规格 |
|---|---|---|
| `AppButton` | 主/次/文字按钮 | 高 32px；圆角 `--radius-md`；次按钮 `surface-2` + `--border-default`；hover 用 `--surface-hover` + `--elevation-1` |
| `IconButton` | 图标操作（替换当前 emoji 与散 SVG） | 36×36 / 紧凑 28×28；`--radius-md`；hover 微亮；统一 `currentColor` 描边图标 |
| `Chip` | 状态/标签（替换散 status-chip） | 圆角 pill；语义色走 `--*-surface/--*-border`；字号 `--fs-caption` |
| `Card` | 信息容器（右侧分析卡片化） | `--surface-2` + `--border-default` + `--radius-lg` + `--elevation-1`；padding `--sp-4` |
| `Tabs` / `SegmentedControl` | 底图风格、时间粒度切换 | 容器 `surface-sunken` + pill；active 用 `--accent` 描边 + 微亮 |
| `Tooltip` | 悬停说明 | Teleport 到 body；`--tooltip-*` 配色 + `--z-tooltip` 顶置；caption / medium；短文案优先，过长省略；延迟 200ms |
| `TextField` / `Select` | 设置/搜索输入 | 统一聚焦环 `--border-strong` + 微光 |
| `Skeleton` | 加载占位 | 同色块 + 微光 sweep（`--motion-slow`） |
| `PanelDock` | 浮层面板壳（演进 `ControlPanel`） | 玻璃 + `--elevation-2`；统一标题栏/折叠/复位/隐藏三件套 |

### 3.2 组件状态约定（统一语言）

- **Default**：`--surface-2` + `--border-default`，文字 `--text-primary`。
- **Hover**：`--surface-hover` + `--elevation-1` + `translateY(-1px)`。
- **Active/Pressed**：`--accent` 描边 + `--accent-surface` 微底。
- **Focus-visible**：`outline: 2px solid var(--accent); outline-offset: 2px`（**所有可交互元素强制**）。
- **Disabled**：`--text-disabled` + 无阴影 + `pointer-events:none`。

---

## 4. 图标规范

**统一采用 SVG 描边图标库（lucide / heroicons 风格，24×24 viewBox，`stroke="currentColor"`），替换当前 emoji 与字符图标。**

| 现状 | 位置 | 替换为 |
|---|---|---|
| 📋 | `ModeToolbar` 日志 | `list` / `scroll-text` 图标 |
| ⚙ | `ModeToolbar` 设置 | `settings` 图标 |
| ◫ | `ModeToolbar` 截图 | `camera` 图标 |
| ⬡ | `ModeToolbar` 工作流 | `hexagon` / `workflow` 图标 |
| ◇◆▦◑⛰ | `ModeToolbar` 底图风格 | 对应 SVG（none/satellite/street/dark/terrain） |
| 移动/选择/测量内联 SVG | `ModeToolbar` | 保留 SVG，但统一 1.5 stroke + `currentColor` 与尺寸 |

规则：图标尺寸 14/16/20 三档；不用 emoji；跨平台一致；颜色继承 `currentColor`。

---

## 5. 信息架构与布局

保持「地图核心」骨架，重构 chrome 的信息密度：

- **顶栏（收敛）**：`品牌` + `全局搜索 / 命令面板(Cmd-K)` + `主导航` + `账户`；底图风格/源选择收进设置或折叠菜单；运行/同步状态归并为**右侧统一状态集群**（一个 Chip group，不再散落多 chip）。
- **左图层抽屉**：默认 slim rail（可折叠），含搜索 + 分组 + 统一图标列表。
- **右分析 dock**：常驻 dock，信息**卡片化**分组（图层属性 / 点查 / 时序），统一间距与留白。
- **底栏时间轴**：固定 dock，含进度 + 播放 + 粒度 `SegmentedControl`；色段做成语义化 legend。
- **聚焦模式**：一键隐藏所有 chrome，纯地图沉浸（Esc 退出）。
- **命令面板（Cmd-K）**：全局搜索图层 / 动作 / 导航，提升专业感与效率（P2 落地）。

---

## 6. 状态体系（统一语言）

| 状态 | 表现 |
|---|---|
| Loading | `Skeleton` 微光 + 局部 spinner，禁止全屏转圈盖住地图 |
| Empty | 居中图标 + 一句引导文案（如「拖入数据或点击导入」） |
| Error | `--danger` Chip / 内联提示 + 重试按钮，勿用原生 alert |
| Success | `--success` 短暂 toast（右下角，`--z-toast`） |

---

## 7. 无障碍基线（WCAG AA）

- 正文对比度 ≥ 4.5:1；大字 ≥ 3:1（用 `--text-*` 与 `--surface-*` 组合校验）。
- 所有可交互元素 **focus-visible 焦点环**可见。
- 支持 `prefers-reduced-motion: reduce` → 关闭 hover 位移与 skeleton sweep，仅保留透明度过渡。
- 触控目标 ≥ 36×36px（IconButton 最小 28 但外扩 hit area 到 36）。
- 语义 HTML + ARIA：`role="tablist/tab"`、`aria-selected`、图标按钮 `aria-label`。
- 数字用 `font-variant-numeric: tabular-nums`（时间/坐标对齐）。

---

## 8. 迁移路径（229 hex → token）

| 阶段 | 内容 | 落点文件 | 风险 |
|---|---|---|---|
| **S1** | 扩展 `tokens.css` 到 §2 全套令牌；`main.css` 接入 | `src/styles/tokens.css` | 低 |
| **S2** | 建 `components/ui/*` 基础组件（Btn/IconBtn/Chip/Card/Tabs/Tooltip/Skeleton/PanelDock） | `src/components/ui/*` | 低 |
| **S3** | 逐组件替换散样式：`ModeToolbar` → 顶栏收敛 + SVG 图标；`ControlPanel/BasePanel` → `PanelDock` + elevation；`TimelineScrubber` → 语义化；`InfoPanel`/`LayerSidebar` → 卡片化 | 对应 `.vue` | 中 |
| **S4** | 校验：`grep -rn "#[0-9a-f]\{3,6\}" src` 唯一值数下降；`vitest` 组件测试；视觉 QA（亮/暗地图可读、对比度、reduced-motion） | — | 中 |

**回退策略**：每个 `.vue` 单独 PR，保留原组件别名，便于逐块回滚；不一次性大改。

---

## 9. 落地文件映射

| 现状文件 | 改造动作 |
|---|---|
| `src/styles/tokens.css` | 从 11 令牌扩展到 §2 全套 |
| `src/styles/main.css` | 接入新令牌，root 字号维持 15px |
| `src/components/ModeToolbar.vue` | 顶栏收敛 + emoji→SVG 图标 + 状态集群 |
| `src/components/ControlPanel.vue` `BasePanel.vue` | 演进为 `PanelDock`（玻璃 + elevation + dock） |
| `src/components/TimelineScrubber.vue` | 语义化色段 + 粒度 `SegmentedControl` |
| `src/components/InfoPanel.vue` `LayerSidebar.vue` | 卡片化、统一间距/图标 |
| `src/components/ui/*`（新建） | 基础组件库 |
| `src/views/DashboardView.vue` | 聚焦模式开关 + 命令面板挂载点 |

---

## 10. 评审检查清单（落地前确认）

- [ ] 最小字号 ≥ 12px，无 8–10px 微字
- [ ] 无 emoji 图标，全部 SVG `currentColor`
- [ ] 玻璃 blur 统一 16px，浮层不透明度 ≥ 0.86
- [ ] 所有交互元素 focus-visible 环
- [ ] 动效 120/200/320ms + reduced-motion 分支
- [ ] 顶栏信息密度下降、状态归并
- [ ] 暗/亮地图下浮层文字可读（视觉 QA）
