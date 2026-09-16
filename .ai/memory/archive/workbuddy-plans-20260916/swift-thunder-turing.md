# 缓存优先 + 后台刷新（Commit 1：消除"未配置分析工作流引擎"对添加路径的污染）

## 背景与根因

用户报告"很多图层显示未配置分析工作流引擎"，经探索发现**这不是阻断，是文案污染**：
- overlay_registry 的 static/time-series 图层（aridity-cn / gpcp-precip-ts / clcd-cn）确实**没有** python_provider/gee 工作流引擎
- 但它们的 PNG 缓存**已经天然工作**：`map-canvas-non-weather-layer-sync-module.ts:92-97` 通过 `knownOverlayIds` 自动加载 PNG overlay
- 真正问题：两处把"运行阻断文案"`getCatalogRunBlockReason` 用在了"添加/已添加"上下文，UI 显示红色"未配置"警示
- 用户读到"未配置"就以为图层坏了

## 设计原则

**最小修改 = 大效果**：
- 后端零变更（PNG 缓存机制完整）
- 前端不改 `supportsAnalysisWorkflow` / `getCatalogRunBlockReason`（仍被工作流运行/提交守卫正确使用，workflow-runner.ts:992-1005）
- 新增两个纯函数（catalog-runtime.ts），分流"添加"vs"运行"两套语义

## Commit 1 实现

### 1. `Code/frontend/src/stores/layers/catalog-runtime.ts` 新增（~15 行）

```ts
function isOverlayDisplayOnlyLayer(catalogId: string): boolean {
  const engine = getCatalogWorkflowEngine(resolveBackendLayerId(catalogId)) ?? ''
  return engine === 'overlay_registry' || engine === ''
}

function getCatalogAddBlockReason(catalogId: string): string | null {
  if (isOverlayDisplayOnlyLayer(catalogId)) return null
  return getCatalogRunBlockReason(catalogId)
}
```

### 2. `Code/frontend/src/components/layer-sidebar/LayerSidebarLibrary.vue:304` 调用点改

```vue
:title="getCatalogAddBlockReason(effectiveSourceId(item)) ?? ''"
```

效果：添加按钮的 tooltip 对 overlay 图层为空（不显示"未配置"污染）。

### 3. `Code/frontend/src/components/LayerSidebar.vue:129` 文案分流

在 `getCatalogSemanticNote` 内 blockReason 分支前加：

```ts
if (isOverlayDisplayOnlyLayer(catalogId)) {
  return '静态叠加：已加载缓存影像'  // 中性文案替代"未配置"红色警示
}
```

效果：已添加的 overlay 图层卡片显示"静态叠加：已加载缓存影像"（绿色/中性徽标），不再红色"未配置"。

## 验证

### 单元测试（`Test/frontend/stores/layers/catalog-runtime.test.ts`）

```ts
describe('getCatalogAddBlockReason / isOverlayDisplayOnlyLayer', () => {
  it('overlay_registry 引擎 → 添加永不阻断（null）')
  it('空 engine → 添加永不阻断（null）')
  it('python_provider 引擎 → 添加可能阻断（继承 getCatalogRunBlockReason）')
})
```

### 浏览器实测
- 添加 aridity-cn / gpcp-precip-ts / clcd-cn 不再弹"未配置"
- PNG 正常渲染（地图显示彩色叠加）
- 已添加卡片显示"静态叠加：已加载缓存影像"中性徽标
- 运行/工作流提交按钮的"未配置"阻断文案**保持不变**（点运行才会看到——这是正确的）

## 不做（留作 Commit 2 待用户验证后决定）

- 后端 `/overlays/{id}/cache-info` 端点
- 图层卡片"缓存/最新/加载中"自动状态机
- 自动化后台刷新
- `dataState` 扩展 `overlayLoadState` 字段（仅做不动——动它会牵连 `AutoStatsCard`/`ZonalStatsCard`/`InfoPanelMetaTab` 等统计逻辑）

## 风险与回滚

- 纯增量修改（4 个文件、新增 2 个函数、修改 2 处调用点）
- 不改任何既有行为：运行/提交守卫完全保留
- 单 commit revert 即可回退到原状

## 提交

```
fix(layers): 消除"未配置分析工作流引擎"对 overlay 图层添加路径的文案污染

- catalog-runtime.ts 新增 isOverlayDisplayOnlyLayer +
  getCatalogAddBlockReason（添加路径独立于运行路径语义）
- LayerSidebarLibrary.vue:304 添加按钮 tooltip 改用
  getCatalogAddBlockReason（overlay 图层不显示"未配置"）
- LayerSidebar.vue:129 getCatalogSemanticNote 增 overlay 分流，
  返回中性文案"静态叠加：已加载缓存影像"
- 测试 3 例覆盖两种引擎分支
- 后端零变更（PNG 缓存与 map-canvas-non-weather-layer-sync-module
  已天然支持 overlay 图层自动加载）
```
