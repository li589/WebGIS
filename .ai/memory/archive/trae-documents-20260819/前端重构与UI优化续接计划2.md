# 前端重构与 UI 优化续接计划（第二轮）

## 摘要

前一轮计划共 8 个 Phase，经代码现状核查：Phase 0/1/4/5/6 已完整完成，Phase 2/3/7/8 存在残留问题。本计划聚焦 7 项未完成工作，按"先修 Bug、再收尾"的优先级推进。核心 Bug 2 个（Chip muted 样式缺失、selectors 响应式丢失），收尾项 5 个（EXEMPT_PATHS 同步、@deprecated 标记、hex 残留处理、source-btn 决策、useBreakpoint 推广），大型迁移 1 项（37 文件消费方分批迁移）。

## 当前状态分析

### 已完成（无需修改）

| Phase | 领域 | 状态 | 关键证据 |
|-------|------|------|---------|
| Phase 0 | 时间轴单测 | ✅ 完成 | `layer-timeline.test.ts`(228行20用例) + `weather-timeline.test.ts`(316行18用例) |
| Phase 1 | Token 迁移收尾 | ✅ 完成 | 5 个新 token 已定义（tokens.css 行25-29/158-162），5 处内联 rgba 已替换，token-map.ts 标注已移除 |
| Phase 4 | CSS 外部化 | ✅ 完成 | TimelineScrubber.styles.css(457行) + TimelineScrubber.global.css(47行) + MapCanvas.styles.css(757行)，SFC 内零内联 style |
| Phase 5 | useWorkflowState 重构 | ✅ 完成 | WorkflowStateOptions interface(13字段)，pointWeather 已移除，InfoPanel.vue 调用已更新 |
| Phase 6 | Deprecated 别名清理 | ✅ 完成 | 9 个 api-reexports 别名 + 3 个模块别名全部清除，全项目 grep 0 引用 |

### 需续接的问题

| 优先级 | Phase | 问题 | 类型 |
|--------|-------|------|------|
| P0 | Phase 2 | Chip.vue 缺少 `.chip--muted` CSS | 可见 Bug |
| P1 | Phase 7 | selectors.ts 响应式丢失 | 功能 Bug |
| P2 | Phase 8 | EXEMPT_PATHS 不同步（25 vs 11 条） | 工具误报 |
| P3 | Phase 7 | index.ts 缺少 @deprecated 标签 | 规范缺失 |
| P4 | Phase 8 | 7 处 hex 残留 | 规范收尾 |
| P5 | Phase 2 | source-btn 未替换 SegmentedControl | 设计决策 |
| P6 | Phase 3 | useBreakpoint 无消费方 | 功能闲置 |
| P7 | Phase 7 | 37 文件消费方迁移 | 大型迁移 |

## 实施方案

### Step 1 [P0] Chip.vue 添加 `.chip--muted` 样式

**文件**: `src/components/ui/Chip.vue`

**问题**: TypeScript 已声明 `variant?: '...| 'muted'`（行14），但 `<style scoped>` 无 `.chip--muted` 选择器。ModeToolbar.vue 中 `availabilityVariant` 在无数据状态返回 `'muted'`，导致 Chip 无背景/边框/文字色。

**修改**: 在 `.chip--info`（行113）之后、`.chip--disabled`（行115）之前插入：

```css
/* 变体：muted */
.chip--muted {
  background: var(--surface-sunken);
  border-color: var(--border-subtle);
  color: var(--text-faint);
}
```

**决策依据**: `--surface-sunken`（凹陷容器背景）+ `--border-subtle`（极淡边框）+ `--text-faint`（极淡文字）组合表达"静默/无数据"语义。

**验证**: `npm run lint && npx vue-tsc -b && npm run build && npm test`；手动验证无数据图层时可用性 Chip 显示淡灰样式。

---

### Step 2 [P1] selectors.ts 响应式修复

**文件**: `src/stores/layers/selectors.ts`

**问题**: 三个 selector composable 返回普通对象，state 字段取 `store.xxx`（自动解包快照值），消费方解构后丢失响应式。文件头注释（行13-18）承认此问题并建议直接用 `storeToRefs`。

**修改**: 重构为 `storeToRefs` + action 引用模式：

```typescript
import { storeToRefs } from 'pinia'
import { useLayersStore } from './index'

export function useLayerWorkspace() {
  const store = useLayersStore()
  const {
    activeLayers, sidebarView, selectedInstanceId, currentHour,
    isSubmitting, runtimeLayerCatalogLoading,
    activeLayersDisplay, selectedLayerDisplay, activeLayerCount,
    sidebarViewLabel, catalogJobStatus, catalogRunReadiness,
    layerLibrary,
  } = storeToRefs(store)

  return {
    // Reactive state (Refs / ComputedRefs)
    activeLayers, sidebarView, selectedInstanceId, currentHour,
    isSubmitting, runtimeLayerCatalogLoading,
    activeLayersDisplay, selectedLayerDisplay, activeLayerCount,
    sidebarViewLabel, catalogJobStatus, catalogRunReadiness,
    layerLibrary,
    // Non-reactive static data
    layerCategories: store.layerCategories,
    // Actions
    addLayer: store.addLayer,
    /* ... 其余 actions 直接引用 ... */
  }
}
```

对 `useLayerViewport()` 和 `useWorkflowRun()` 应用相同模式：state 字段通过 `storeToRefs` 返回 Ref，actions 保持直接引用。

**关键注意**:
- `layerCategories` 是 `LAYER_CATEGORIES` 静态常量，`storeToRefs` 不返回它，需单独 `store.layerCategories` 引用
- 删除文件头注释中"For reactive state, use storeToRefs"的变通说明
- **无破坏性变更**: 当前 0 个消费方使用 selectors

**验证**: `npm run lint && npx vue-tsc -b && npm run build && npm test`

---

### Step 3 [P2] EXEMPT_PATHS 同步

**文件**: `scripts/audit-ui-tokens.mjs` + `src/styles/token-map.ts`

**问题**: token-map.ts 有 25 条豁免路径，audit-ui-tokens.mjs 仅 11 条（缺 16 条，多 1 条 `scalar-field-webgl-controller.ts`）。审计脚本大量误报。

**修改**:

1. 在 `token-map.ts` 的 `EXEMPT_PATHS` 中补充 `src/components/map/scalar-field-webgl-controller.ts`

2. 在 `audit-ui-tokens.mjs` 中替换硬编码数组为动态解析：

```javascript
function loadExemptPaths() {
  const tokenMapPath = join(SRC_ROOT, 'styles/token-map.ts')
  const content = readFileSync(tokenMapPath, 'utf-8')
  const match = content.match(/export const EXEMPT_PATHS = \[([\s\S]*?)\]/)
  if (!match) throw new Error('无法从 token-map.ts 解析 EXEMPT_PATHS')
  const paths = match[1].match(/'([^']+)'/g)
  if (!paths) throw new Error('EXEMPT_PATHS 为空或格式异常')
  return paths.map(s => s.slice(1, -1))
}

const SELF_EXEMPT = ['src/styles/token-map.ts']
const EXEMPT_PATHS = [...loadExemptPaths(), ...SELF_EXEMPT]
```

**决策依据**: token-map.ts 作为单一真源，审计脚本动态读取，消除两处维护点。

**验证**: `npm run audit:tokens` — 误报应大幅减少，仅剩真实非豁免 hex。

---

### Step 4 [P3] index.ts 添加 @deprecated 标签

**文件**: `src/stores/layers/index.ts`

**问题**: 行60-63 有散文式注释但无 `@deprecated` JSDoc 标签，IDE 不显示删除线提示。

**修改**: 在 return 块前添加 `@deprecated` JSDoc：

```typescript
  /**
   * @deprecated 逐步迁移到 selector composables（`./selectors.ts`）。
   * 新代码请使用 useLayerWorkspace() / useLayerViewport() / useWorkflowRun()。
   */
  return {
```

**验证**: `npm run lint && npx vue-tsc -b && npm run build && npm test`

---

### Step 5 [P4] hex 残留处理

#### 5a. CSS var fallback（3 处，保留并改进审计）

| 文件 | 行 | hex | 上下文 | 决策 |
|------|-----|-----|--------|------|
| `LayerSidebar.styles.css` | 864 | `#67d4ff` | `var(--accent, #67d4ff)` | 保留 |
| `OpenMeteoSyncSettings.vue` | 888 | `#c9b896` | `var(--text-secondary, #c9b896)` | 保留 |
| `WeatherProviderSettings.vue` | 1180 | `#c9b896` | `var(--text-secondary, #c9b896)` | 保留 |

在 `audit-ui-tokens.mjs` 中跳过 `var(--xxx, #hex)` fallback 模式。

#### 5b. WorkflowNodePalette 节点类型语义色（4 处）

**文件**: `src/components/workflow/WorkflowNodePalette.vue`

**推荐方案**: 新增 4 个 token 到 `tokens.css` 并登记到 `token-map.ts`：

```css
/* tokens.css */
--port-time: #ff8fb1;
--port-numeric: #ffd5a8;
--port-text: #ffe08a;
--recent-accent: #c084fc;
```

在 WorkflowNodePalette.vue 中将硬编码 hex 替换为 `var(--xxx)`。

**备选方案**: 若不想增加 token 数量，将 WorkflowNodePalette.vue 添加到 EXEMPT_PATHS（端口色属数据可视化语义色）。

**验证**: `npm run audit:tokens` — 非豁免 hex 为 0。

---

### Step 6 [P5] source-btn 保留决策

**文件**: `src/components/ModeToolbar.vue` 行322-340 + `ModeToolbar.styles.css` 行146-190

**决策: 保留 source-btn 原生实现，不替换为 SegmentedControl**

**理由**:
- `locked` 态需"可点击 + 视觉降级 + 引导修复"，SegmentedControl 的 `disabled` 是"不可点击"，语义不同
- 强行扩展 SegmentedControl API 增加 `locked` 状态，收益不大
- `.source-btn` 样式已使用设计 token，与设计系统一致

**验证**: 无代码变更，仅记录决策。

---

### Step 7 [P6] useBreakpoint 推广使用

**文件**: `src/composables/useBreakpoint.ts`（已实现）+ 目标组件

**策略**: 仅在需要 JS 侧条件渲染/逻辑分支的场景接入，不为使用而使用。

**首批接入**: ModeToolbar.vue — 用 `isMobile` 控制小屏下次要按钮（截图/工作流文字标签）的显隐。

```typescript
import { useBreakpoint } from '../composables/useBreakpoint'
const { isMobile } = useBreakpoint()
```

**验证**: `npm run lint && npx vue-tsc -b && npm run build && npm test`

---

### Step 8 [P7] 消费方分批迁移

**前提**: Step 2（selectors 响应式修复）必须先完成。

**迁移原则**:
- 按域分批：workspace → viewport → workflow-run → 杂项
- 每批迁移后 lint + tsc + build + test 全绿才进入下一批
- store 内部文件不迁移
- `useLayersStore()` 不删除（向后兼容）

**迁移模式**:

迁移前:
```typescript
const layersStore = useLayersStore()
const { activeLayers } = storeToRefs(layersStore)
```

迁移后:
```typescript
const workspace = useLayerWorkspace()
const { activeLayers } = workspace  // 已是 Ref
```

**分批**:

| 批次 | 域 | 文件数 | 代表文件 |
|------|---|--------|---------|
| Batch 1 | workspace | ~8 | LayerSidebar.vue, InfoPanel.vue, useImportExport.ts |
| Batch 2 | viewport | ~6 | MapCanvas.vue, useMapInspect.ts, useWeatherCoverage.ts |
| Batch 3 | workflow-run | ~6 | WorkflowStatusPanel.vue, useWorkflowState.ts |
| Batch 4 | 杂项 | ~8 | ModeToolbar.vue, DataSourceSettings.vue, DashboardView.vue |

**每批验证**: `npm run lint && npx vue-tsc -b && npm run build && npm test`

**关键风险**: 部分消费方直接用 `layersStore.xxx`（快照访问，不带 `.value`），迁移后需改为 `workspace.xxx.value`。需逐个检查。

## 依赖关系

```
Step 1 (Chip muted) ──────────────> 验证
Step 2 (selectors 响应式) ─────────> 验证
  ├── Step 3 (EXEMPT_PATHS) ──────> 验证 (audit:tokens)
  ├── Step 4 (@deprecated) ───────> 验证
  ├── Step 5 (hex 残留) ──────────> 验证 (audit:tokens)
  ├── Step 6 (source-btn 决策) ───> 无代码变更
  ├── Step 7 (useBreakpoint) ─────> 验证
  └── Step 8 (消费方迁移)
       ├── Batch 1 ──> 验证
       ├── Batch 2 ──> 验证
       ├── Batch 3 ──> 验证
       └── Batch 4 ──> 验证
```

## 假设与决策

1. **Chip muted 用 surface-sunken + border-subtle + text-faint**: 表达"无数据"弱化语义，与 success/warning/danger 形成完整变体矩阵。
2. **selectors 重构为 storeToRefs**: 修复响应式丢失是前置必要条件，当前 0 消费方故无破坏。
3. **EXEMPT_PATHS 动态解析**: token-map.ts 作为单一真源，正则提取字符串数组，容错性强。
4. **CSS var fallback 保留**: `var(--token, #hex)` 是标准防御性写法，审计脚本应排除。
5. **WorkflowNodePalette 端口色新增 token**: 端口语义色应纳入设计系统而非豁免，保持 token 体系完整。
6. **source-btn 保留**: locked 态交互语义与 SegmentedControl disabled 不同，不强行替换。
7. **useBreakpoint 仅用于 JS 逻辑场景**: 纯样式响应继续用 CSS @media，避免无谓 JS 开销。
8. **消费方分 4 批迁移**: 每批独立可交付，降低单次变更风险。

## 验证步骤

每个 Step 完成后:
```
cd Code/frontend && npm run lint && npx vue-tsc -b && npm run build && npm test
```

Step 3/5 额外:
```
cd Code/frontend && npm run audit:tokens
```

全部完成后的终态验收:
- Chip.vue 有 `.chip--muted` 样式
- selectors.ts 使用 `storeToRefs` 返回 Refs
- `audit-ui-tokens.mjs` 的 EXEMPT_PATHS 从 token-map.ts 动态读取
- `index.ts` 扁平返回标记 `@deprecated`
- 非豁免文件零内联 hex/rgba（CSS var fallback 除外）
- `useBreakpoint` 至少在 1 个组件中使用
- 消费方全部迁移到 selector composables（4 批完成）
- `useLayersStore()` 扁平返回保留但标记 @deprecated
- lint / tsc / build / test / audit:tokens 全绿
