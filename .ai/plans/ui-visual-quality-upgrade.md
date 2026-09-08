# UI视觉质量升级与性能优化计划

## 概要

本计划专注于**减少AI感/廉价感**、**提升UI性能**、**统一组件样式**，目标达到Figma/Linear级别的专业SaaS工具视觉标准。登录页保持现状不改动。

---

## 当前问题诊断

### 性能问题
| 问题 | 影响 | 涉及文件 |
|------|------|----------|
| 76处`backdrop-filter: blur()`，10+种不同模糊值 | GPU负担重，低端设备卡顿 | 全局 |
| 仪表盘同时渲染5-6层blur叠加 | 帧率下降 | PanelDock, ModeToolbar, LogPanel等 |
| `--glass-blur: 16px` token存在但未被统一使用 | 性能未优化 | tokens.css |
| 每个组件定义自己的blur值 | 无法全局控制 | 各组件 |

### 视觉问题
| 问题 | 影响 | 涉及文件 |
|------|------|----------|
| 27处`box-shadow: 0 0 Npx`发光效果 | "霓虹灯到处亮"的廉价感 | AppButton, PanelDock, Chip, Tabs |
| AppButton primary的shimmer动画 | 典型AI生成UI特征 | AppButton.vue |
| PanelDock多层渐变背景+高光线 | 视觉复杂度过高 | PanelDock.vue |
| Tabs active的text-shadow发光 | 装饰性过强 | Tabs.vue |
| 各组件opacity/间距硬编码 | 样式不统一 | 多个组件 |

---

## 实施计划

### 阶段一：Token系统统一与硬编码清理

**目标**：建立统一的设计基础，消除不一致

#### 1.1 `styles/tokens.css` 修改

```css
/* 删除重复定义（保留219-228行版本） */
/* --category-weather, --category-raster, --category-vector 及其 surface/border 变体 */

/* 修正非rem值 */
--touch-min: 2.25rem;  /* 原 36px */

/* 统一panel背景token */
--surface-panel: var(--surface-1);  /* 替代原来的top/bottom渐变 */

/* 新增内部高亮token */
--inner-highlight: rgba(255, 255, 255, 0.06);
--inner-highlight-strong: rgba(255, 255, 255, 0.1);

/* 新增glow token（统一发光半径） */
--glow-sm: 0 0 8px var(--accent-surface);
--glow-md: 0 0 12px var(--accent-surface);
--glow-lg: 0 0 16px var(--accent-surface);
```

#### 1.2 `components/ui/AppButton.vue` 修改

| 改动 | 原值 | 新值 |
|------|------|------|
| gap | `0.35rem` | `var(--space-2)` |
| padding sm | `0 0.5rem` | `0 var(--space-3)` |
| padding md | `0 0.6rem` | `0 var(--space-4)` |
| padding lg | `0 0.85rem` | `0 var(--space-5)` |
| padding xl | `0 1.2rem` | `0 var(--space-6)` |
| disabled opacity | `0.6` | `var(--text-disabled)` |
| **移除shimmer动画** | `::after`伪元素 | 删除 |
| **移除primary glow** | `--accent-glow-sm` | 删除 |

#### 1.3 `components/ui/Chip.vue` 修改

| 改动 | 原值 | 新值 |
|------|------|------|
| padding | `0.4rem 0.8rem` | `var(--space-2) var(--space-4)` |
| gap | `0.3rem` | `var(--space-2)` |
| **移除glow** | `0 0 8px var(--*-surface)` | 删除 |
| **移除scale微交互** | `scale(1.08/0.96)` | 删除 |

#### 1.4 `components/ui/Tabs.vue` 修改

| 改动 | 原值 | 新值 |
|------|------|------|
| **移除text-shadow** | `0 0 12px var(--accent-surface)` | 删除 |
| 内部高亮 | `rgba(255, 255, 255, 0.08)` | `var(--inner-highlight)` |
| disabled opacity | `0.5` | `var(--text-disabled)` |
| segmented gap | `2px` | `var(--space-1)` |
| segmented padding | `2px` | `var(--space-1)` |

---

### 阶段二：性能优化（backdrop-filter统一）

**目标**：减少GPU负担，提升帧率

#### 2.1 `styles/tokens.css` 修改

```css
/* 统一blur值，从16px降至12px减少计算量 */
--glass-blur: 12px;
```

#### 2.2 `components/ui/PanelDock.vue` 修改

| 改动 | 原值 | 新值 |
|------|------|------|
| **删除panel级blur** | `--panel-backdrop-blur: 12px` | 使用`--glass-blur` |
| **移除header saturate** | `blur(12px) saturate(1.08)` | `blur(var(--glass-blur))` |
| **移除restore pill blur** | `backdrop-filter: blur(12px)` | 删除 |
| **移除drag glow** | `0 0 18px var(--accent-surface)` | 删除 |
| **移除collapsed hover glow** | `0 0 14px var(--accent-surface)` | 删除 |
| 内部高亮 | `rgba(255, 255, 255, 0.06)` | `var(--inner-highlight)` |
| 拖拽边框高亮 | `rgba(255, 255, 255, 0.08)` | `var(--inner-highlight-strong)` |

#### 2.3 `components/ui/AppModal.vue` 修改

| 改动 | 原值 | 新值 |
|------|------|------|
| **移除backdrop blur** | `blur(5px)` | 删除（已有面板blur） |

#### 2.4 `components/toolbar/LogPanel.vue` 修改

| 改动 | 原值 | 新值 |
|------|------|------|
| **合并blur** | `blur(4px) + blur(24px)` | `blur(var(--glass-blur))` |

#### 2.5 其他组件

- 扫描所有`backdrop-filter`使用，统一为`--glass-blur`或移除冗余blur

---

### 阶段三：面板视觉简化

**目标**：Figma/Linear风格的清晰层次

#### 3.1 `components/ui/PanelDock.vue` 简化

| 改动 | 原值 | 新值 |
|------|------|------|
| **简化背景** | 三重渐变（linear + 2 radial） | 单一`var(--surface-panel)` |
| **移除顶部高光线** | `::before`伪元素 | 删除 |
| **hover效果简化** | elevation + glow | 仅elevation变化 |
| **restore pill简化** | blur + opacity + glow | 仅opacity变化 |

#### 3.2 `styles/main.css` 清理

| 改动 | 说明 |
|------|------|
| 移除`.hover-lift` | 改为组件内使用`--elevation-*` |
| 移除`.hover-glow` | 不再使用glow效果 |

#### 3.3 `styles/tokens.css` 清理

| 改动 | 说明 |
|------|------|
| 移除`--accent-glow-sm/md` | 不再使用glow效果 |
| 移除`--ambient-*-glow` | 简化氛围效果 |

---

## 不改动的部分

| 部分 | 原因 |
|------|------|
| 登录页 | 用户选择保持现状 |
| Card.vue | 已是最佳实践（98% token adherence） |
| ECharts图表主题 | 不在本次范围 |
| WebGL着色器 | 不受token系统影响 |
| 骨架屏/加载动画 | 已有独立计划覆盖 |

---

## 验证步骤

### 1. 构建验证
```bash
cd Code/frontend
npm run build
```
- 确保无编译错误
- 检查CSS中是否有未定义的var()引用

### 2. Lint验证
```bash
cd Code/frontend
npm run lint
```

### 3. 视觉验证（需人工）
- [ ] 仪表盘：面板背景简化，无多余glow
- [ ] 面板拖拽：无glow效果，仅elevation变化
- [ ] 按钮hover：无shimmer动画，无glow
- [ ] Tabs切换：无text-shadow发光
- [ ] Chips显示：无glow效果
- [ ] 模态框：无backdrop blur叠加
- [ ] 日志面板：blur层减少

### 4. 性能验证（需人工）
- [ ] 面板拖拽流畅度提升
- [ ] 低端GPU设备帧率改善
- [ ] 减少GPU内存占用

### 5. 代码质量
- [ ] 无硬编码颜色/发光半径（除特殊效果如渐变）
- [ ] 所有opacity使用token或统一值
- [ ] 所有间距使用`--space-*`token

---

## 预期效果

| 指标 | 当前 | 目标 |
|------|------|------|
| backdrop-filter实例数 | 76 | <20 |
| blur值种类 | 10+ | 1-2 |
| glow效果数 | 27 | 0 |
| 硬编码opacity | 散布 | 统一到token |
| 视觉风格 | 玻璃态+霓虹 | Figma/Linear简洁 |

---

## 参考文档

- 现有UI优化计划：`.ai/plans/ui-optimization-and-basemap-audit-plan.md`
- 设计Token系统：`Code/frontend/src/styles/tokens.css`
- 组件库：`Code/frontend/src/components/ui/`
