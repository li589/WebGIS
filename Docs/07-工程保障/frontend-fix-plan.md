# CGDA 前端代码修复与优化计划

> 审计日期：2026-08-12
> 审计范围：用户最近修改的 8 个前端文件（tokens.css、main.css、ModeToolbar.vue、Tooltip.vue、Tabs.vue、Skeleton.vue、PanelDock.vue、TextField.vue）
> 严重等级：P0=阻断性错误 | P1=设计规范违反 | P2=体验改进

---

## 问题总览

| 等级 | 数量 | 说明 |
|------|------|------|
| P0 | 3 | 会导致界面显示异常或编译错误，必须立即修复 |
| P1 | 5 | 违反设计系统规范，影响视觉一致性 |
| P2 | 4 | 体验改进项，可分阶段迭代 |

---

## P0 — 阻断性错误（必须立即修复）

### P0-1：tokens.css 被严重回退，大量 CSS 变量缺失

**问题**：当前 `tokens.css`（57 行）从之前的完整版本（180 行）被简化为最小版本，导致 `ModeToolbar.vue` 等组件引用了大量不存在的 CSS 变量：

缺失的令牌：
- **表面层级**：`--surface-1`、`--surface-2`、`--surface-3`、`--surface-hover`（当前只有 `--surface-panel`、`--surface-raised`、`--surface-sunken`，命名不一致）
- **玻璃效果**：`--glass-blur`
- **阴影层级**：`--elevation-1`、`--elevation-2`、`--elevation-3`、`--elevation-modal`
- **动效**：`--motion-fast`、`--motion-base`、`--motion-slow`、`--ease-standard`、`--ease-emphasized`、`--ease-decelerate`
- **语义色三件套**：`--success-surface/border`、`--warning-surface/border`、`--danger-surface/border`、`--info-surface/border`
- **字重**：`--font-weight-regular`、`--font-weight-medium`
- **z-index 层级**：`--z-map`、`--z-overlay`、`--z-panel`、`--z-popover`、`--z-modal`、`--z-toast`
- **字号 floor 被违反**：`--font-size-micro: 8.7px`、`--font-size-caption: 9.3px`、`--font-size-body: 10.8px`，都低于 12px 商业化可读下限
- **浅色主题**：`[data-theme='light']` 覆盖块被完全删除
- **缺失 token**：`--radius-xl`、`--space-6`、`--space-7`、`--font-size-h1/h2/subtitle`

**修复方案**：
1. 恢复完整的 tokens.css，包含：
   - 6 级文本色 + 3 级品牌色
   - 4 组语义色（文字+表面+边框三件套）
   - 6 级表面层级（surface-base/sunken/1/2/3/hover）
   - 4 级边框
   - 5 级圆角（sm/md/lg/xl/pill）
   - 7 级间距（space-1~7，4px 基数）
   - 6 级字号（caption 12px/body 13px/title 14px/subtitle 16px/h2 20px/h1 24px）
   - 2 级字重（400/500）
   - 4 级 elevation（含内高光）
   - glass-blur: 16px
   - 3 档动效时长 + 3 种缓动
   - 7 层 z-index
2. 完整恢复 `[data-theme='light']` 浅色主题覆盖
3. 移除所有低于 12px 的字号定义（micro 8.7px 等）

**文件**：`Code/frontend/src/styles/tokens.css`

---

### P0-2：Tabs.vue 语法错误 — 多余的 `</script>` 标签

**问题**：`Tabs.vue` 第 70 行存在多余的 `</script>` 结束标签，会导致编译失败。

```vue
// 第 68-71 行
</template>

</script>    ← 这个是多余的，template 后面应该直接是 <style>

<style scoped>
```

**修复方案**：删除第 70 行的 `</script>`。

**文件**：`Code/frontend/src/components/ui/Tabs.vue`

---

### P0-3：main.css 回退，颜色硬编码 + 浅色主题丢失

**问题**：
- `color: #d9e6f2` 硬编码，应使用 `var(--text-primary)`
- 浅色主题的 `[data-theme='light']` 样式块被删除（背景渐变、颜色覆盖等）

**修复方案**：
1. 将 `color: #d9e6f2` 改回 `color: var(--text-primary)`
2. 恢复 `[data-theme='light']` 样式块，包含：
   - 颜色覆盖
   - 背景渐变（暖白底）
3. 确保 `font-family` 等引用正确

**文件**：`Code/frontend/src/styles/main.css`

---

## P1 — 设计规范违反（高优先级）

### P1-1：大量字号低于 12px floor

**问题文件及位置**：

| 文件 | 位置 | 当前字号 | 问题 |
|------|------|----------|------|
| `ModeToolbar.vue` | `.brand-eyebrow` | 10px | 品牌辅助文字过小 |
| `ModeToolbar.vue` | `.log-badge` | 10px | 徽章数字过小 |
| `ModeToolbar.vue` | `.style-btn` | 11px | 底图风格按钮过小 |
| `ModeToolbar.vue` | `.source-btn` | 10px | 来源选择按钮过小 |
| `ModeToolbar.vue` | `.chip` | 11px | 状态 chip 过小 |
| `TextField.vue` | `.text-field-error` | 11px | 错误提示过小 |
| `Tabs.vue` | `.tabs--compact .tabs-item` | 11px | 紧凑模式字号过小 |
| `AppButton.vue` | `.app-btn--xs` | 11px | xs 按钮字号过小 |

**修复方案**：
1. 所有字号统一提升到 ≥12px（使用 `var(--font-size-caption)`）
2. 按钮/chip 高度相应调整以保持比例
3. xs 按钮建议改为 28px 高、12px 字号（取消 xs 尺寸或对齐 floor）
4. badge 数字可保留 10px 但需配合更大的容器（18px+ 高度）

---

### P1-2：新组件样式不符合设计系统规范

**Tooltip.vue**：
- 问题：字号硬编码 `12px`（应用 `var(--font-size-caption)`）；边框 `--border-subtle` 过淡，建议 `--border-default`；背景应用 `--surface-3` 是对的，但需要补全
- 修复：使用 token 引用；调整过渡动画的方向（top 位置的 tooltip 应该从 translateY(-4px) 进入，bottom 从 translateY(4px)）

**Skeleton.vue**：
- 问题：shimmer 动画只是颜色交替（surface-1 → surface-2 → surface-1），不是标准的微光 sweep 效果
- 修复：使用 `linear-gradient` + `background-position` 动画实现从左到右的微光扫过效果

**PanelDock.vue**：
- 问题：折叠按钮 24px、操作按钮 26px，小于 WCAG 建议的最小触控目标 36px（桌面端可接受 28px 但需外扩 hit area）；折叠时 body 使用 `v-show` 无过渡动画；折叠图标旋转方向需要修正（展开时箭头朝下，折叠到 rail 时箭头朝右）
- 修复：折叠/展开添加宽度过渡动画；按钮增加 padding 扩大点击区域；修正图标方向逻辑

**TextField.vue**：
- 问题：清除按钮 20px 偏小；错误提示 11px 过小；search 图标 padding 可优化
- 修复：清除按钮增大到 22-24px；错误提示提升到 12px

---

### P1-3：ModeToolbar 未复用已有的 UI 组件

**问题**：`ModeToolbar.vue` 自行实现了 `.tool-btn`、`.mode-btn`、`.chip` 样式，没有复用已建好的 `AppButton`、`IconButton`、`Chip` 组件，导致：
- 样式重复维护
- 交互状态（hover/active/focus/disabled）不一致
- 违背设计系统"单一真源"原则

**修复方案**：
1. `.mode-btn`（移动/选择/测量）→ 使用 `IconButton` 组件
2. `.tool-btn`（截图/工作流/设置/日志）→ 使用 `AppButton` 组件（ghost 或 secondary 变体）
3. `.style-btn`/`.source-btn` 组 → 使用 `Tabs` 组件（segmented 变体）
4. `.chip` 状态标签 → 使用 `Chip` 组件

---

### P1-4：内联 rgba 颜色未走语义 token

**问题**：`ModeToolbar.vue` 中有多处硬编码 rgba 颜色：
- `.mode-btn.active`: `background: rgba(60, 120, 200, 0.32)` → 应使用 `--info-surface` 或定义 `--accent-surface`
- `.mode-btn--clear:hover`: `background: rgba(220, 80, 80, 0.28)` → 应使用 `--danger-surface`
- `.style-btn.active`: `background: rgba(10, 132, 255, 0.5)` → 应使用 `--accent-surface`
- `.source-btn.active`: `background: rgba(10, 132, 255, 0.22)` → 同上
- `.availability-empty`: `rgba(187, 137, 255, 0.2/.1)` 紫色未在设计系统中定义，需确认意图

**修复方案**：
1. 为 accent 添加 `--accent-surface` / `--accent-border` token
2. 将所有硬编码 rgba 替换为语义 token 引用
3. 确认 `availability-empty` 的紫色是否为有意设计（与现有 accent/warm 不同），若是则添加到 tokens 作为 `--neutral` 或类似语义色

---

### P1-5：缺少 `--accent-surface` / `--accent-border` 令牌

**问题**：语义色体系中 success/warning/danger/info 都有 surface/border 三件套，但主品牌色 `--accent` 缺少对应的 surface/border，导致组件需要硬编码。

**修复方案**：在 tokens.css 中补充：
```css
--accent-surface: rgba(90, 213, 255, 0.12);
--accent-border: rgba(90, 213, 255, 0.30);
```

---

## P2 — 体验改进项（中优先级）

### P2-1：PanelDock 折叠/展开动画不流畅

**问题**：当前 PanelDock 折叠时 body 用 `v-show` 直接隐藏，宽度变化有 CSS transition 但内容无淡入淡出。

**修复方案**：使用 Vue `<Transition>` 包裹 body，配合高度/透明度过渡。

---

### P2-2：Skeleton sweep 动画实现

**问题**：当前 Skeleton 只是颜色闪烁，不是标准的微光扫过效果。

**修复方案**：
```css
.skeleton {
  background: linear-gradient(
    90deg,
    var(--surface-1) 25%,
    var(--surface-2) 50%,
    var(--surface-1) 75%
  );
  background-size: 200% 100%;
  animation: skeleton-sweep 1.5s ease-in-out infinite;
}
@keyframes skeleton-sweep {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
```

---

### P2-3：响应式断点令牌缺失

**问题**：设计系统缺少响应式断点 token，ModeToolbar 中硬编码了 `@media (max-width: 1100px)`。

**修复方案**：在 tokens.css 中添加断点变量（CSS 中可通过 JS 读取或使用 `@custom-media` 提案，或直接定义为注释中的约定值并在组件中统一使用）。

---

### P2-4：缺少 Select 组件

**问题**：设计系统规划中的 `Select` 下拉选择组件尚未创建。

**修复方案**：按设计系统规范创建 `src/components/ui/Select.vue`，参考 TextField 的样式模式。

---

## 修复执行顺序

建议按以下顺序执行修复，避免依赖冲突：

### 第一轮（修复 P0 阻断性问题）
1. ✅ 恢复完整 `tokens.css`（P0-1 + P1-5）
2. ✅ 修复 `Tabs.vue` 语法错误（P0-2）
3. ✅ 修复 `main.css` 回退（P0-3）

### 第二轮（修复 P1 规范问题）
4. 统一所有字号到 ≥12px floor（P1-1）
5. 修复新组件样式问题（Tooltip/Skeleton/PanelDock/TextField）（P1-2）
6. 补充 `--accent-surface/border` token，替换内联 rgba（P1-4 + P1-5）

### 第三轮（P1 组件复用 + P2 体验优化）
7. ModeToolbar 重构，复用 AppButton/IconButton/Chip/Tabs（P1-3）
8. PanelDock 动画优化（P2-1）
9. Skeleton sweep 动画（P2-2）
10. 创建 Select 组件（P2-4）

---

## 做得好的部分

需要肯定的是，以下改动方向正确且质量较高：

1. **图标系统迁移到 lucide-vue-next**：正确引入了 lucide 图标库，替换了 emoji，符合设计系统规范
2. **新建了 5 个基础 UI 组件**：Tooltip、Tabs、Skeleton、PanelDock、TextField 的创建方向正确，填补了组件库空缺
3. **ModeToolbar 信息架构优化**：右侧状态集群（status-cluster）的设计正确，收敛了分散的状态显示
4. **响应式意识**：ModeToolbar 中添加了 `@media (max-width: 1100px)` 的响应式适配，是好的开始
5. **focus-visible 统一**：新组件都正确实现了 `outline: 2px solid var(--accent)` 焦点环
6. **prefers-reduced-motion 支持**：新组件都尊重了 reduced-motion 偏好

---

## 验证清单

修复完成后需验证：

- [ ] `npm run build` 编译通过，无错误无警告
- [ ] `npm run dev` 启动后界面正常显示，无缺失样式
- [ ] 暗色/亮色主题切换正常
- [ ] 所有交互元素有可见的 focus-visible 环
- [ ] 最小字号 ≥12px（品牌 eyebrow 等装饰性文字除外但需 ≥10px）
- [ ] ModeToolbar 在桌面端布局正常
- [ ] 新组件（Tooltip/Tabs/Skeleton/PanelDock/TextField）功能正常
- [ ] `npm run lint` 通过
- [ ] `npm run test` 通过
