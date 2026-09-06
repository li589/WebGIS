# CGDA「数据」功能优化与增强计划

## 概要

对前端 `data-manager` 模块进行三阶段递进优化：P0 Bug 修复（后端数据泄漏、无效轮询、遮罩穿透）→ P1 UX 改进（配额展示、错误可见性、多要素缩放、拖放反馈、大小预估）→ P2 功能增强（键盘导航、数据质量提示、作业过滤、列表虚拟化）。共 12 项改动，涉及 ~15 个文件，每项可独立提交。

## 现状分析

### 架构概况

前端 `Code/frontend/src/data-manager/` 三层结构：
- `core/`：API 客户端 (`api.ts`)、工作台状态 (`workspace-store.ts`)、HTTP 封装、认证、属性显示、矢量分组
- `adapters/`：图层适配 (`layers.ts`)、导出适配 (`export.ts`)
- `ui/`：7 个组件 — DataWorkspace / DataImportPanel / DataExportPanel / AttributeTable / LayerDetails / JobsPanel / DataImportMenu

后端 `Code/backend/app/data_io/api/router.py` 提供 38 个端点（上传、矢量/栅格/文档导入、属性 CRUD、导出、异步作业、配额查询）。

### 已确认问题

| 编号 | 严重性 | 问题 | 定位 |
|------|--------|------|------|
| P0-1 | Bug | `removeLayer` 不清理后端数据，配额泄漏 | `LayerDetails.vue` L134-139 |
| P0-2 | Bug | JobsPanel 固定 2.5s 轮询，空闲时持续请求 | `JobsPanel.vue` L63-68 |
| P0-3 | Bug | 导入遮罩 `pointer-events: none`，操作穿透 | `DataImportMenu.vue` L244 |
| P1-4 | UX | 无存储配额展示（后端有端点未调用） | `workspace-store.ts` / `DataWorkspace.vue` |
| P1-5 | UX | AttributeTable 元数据错误被静默吞掉 | `AttributeTable.vue` L157-165 |
| P1-6 | UX | `zoomToSelected` 仅支持单要素 | `AttributeTable.vue` L385-396 |
| P1-7 | UX | DataWorkspace 无拖放视觉反馈 | `DataWorkspace.vue` |
| P1-8 | UX | 导出面板无文件大小预估 | `DataExportPanel.vue` |
| P2-9 | 功能 | 属性表无键盘导航 | `AttributeTable.vue` |
| P2-10 | 功能 | 无数据质量提示（空值率/坐标异常） | `AttributeTable.vue` / `attr-display.ts` |
| P2-11 | 功能 | JobsPanel 无状态过滤 | `JobsPanel.vue` |
| P2-12 | 性能 | 导出图层列表无虚拟化 | `DataExportPanel.vue` |

## 实施方案

### 阶段一：P0 Bug 修复

#### P0-1 removeLayer 不清理后端数据

**文件**：`Code/frontend/src/data-manager/ui/LayerDetails.vue`、`Code/frontend/src/data-manager/adapters/layers.ts`

**问题**：`LayerDetails.vue` L134-139 的 `removeLayer()` 仅调 `layersStore.removeLayer(id)`，未调 `adapters/layers.ts` L61-70 的 `removeImportedLayer()`（后者会调 `deleteImportedLayer(backendLayerId)` 发 `DELETE /import/layers/{layerId}`）。经 grep 确认 `removeImportedLayer` 当前无任何调用方，仅从 `index.ts` 导出。

**改动**：
1. `adapters/layers.ts` L67-69：将 catch 块从静默吞错改为 `throw`（确保后端清理失败可感知）
2. `LayerDetails.vue`：
   - import `removeImportedLayer` from `'../adapters/layers'`
   - 新增 `removing` ref
   - `removeLayer()` 改为 async，调 `removeImportedLayer(id, backendId)`；catch 中降级调 `layersStore.removeLayer(id)` 并设 error 提示
   - 模板删除按钮绑定 `:disabled="removing"`

**验证**：`npm run test && npm run lint`；功能验证：导入矢量 → 删除 → 检查 `GET /import/quota` 的 `used_bytes` 下降

#### P0-2 JobsPanel 自适应轮询

**文件**：`Code/frontend/src/data-manager/ui/JobsPanel.vue`

**改动**：移除 `setInterval`，改用递归 `setTimeout`：
- 有 `queued`/`running` 作业时间隔 2s（`POLL_ACTIVE_MS`）
- 全部 `succeeded`/`failed`/`cancelled` 时间隔 15s（`POLL_IDLE_MS`）
- `cancel()` 后立即 `scheduleNext()` 重设间隔
- `onUnmounted` 清理 timer

**验证**：DevTools Network 观察请求间隔变化；关闭面板后请求停止

#### P0-3 导入遮罩拦截操作

**文件**：`Code/frontend/src/data-manager/ui/DataImportMenu.vue`

**改动**：`.import-spinner` 的 `pointer-events: none` → `pointer-events: auto`；`.spinner-card` 追加 `pointer-events: auto`

**验证**：导入大文件时点击地图/面板被遮罩拦截

### 阶段二：P1 UX 改进

#### P1-4 存储配额展示

**文件**：`core/api.ts`、`core/workspace-store.ts`、`ui/DataWorkspace.vue`、`ui-copy/data.ts`

**改动**：
1. `api.ts` 追加 `fetchImportQuota()` 和 `reclaimImportSpace()` — 调用 `GET /import/quota` 和 `POST /import/quota/reclaim`（后端 `paths.py` L125-141 返回 `used_bytes/limit_bytes/free_bytes/used_ratio/ephemeral_bytes` 等）
2. `workspace-store.ts` 新增 `importQuota` shallowRef 和 `refreshImportQuota()`；`openDataWorkspace` 中触发首次加载
3. `DataWorkspace.vue` 在 header 与 body 之间插入配额进度条（`used_ratio > 0.85` 时 warn 样式）+ 回收按钮
4. `ui-copy/data.ts` 追加配额相关文案

**注意**：`GET /import/quota` 依赖 `require_write_access`，只读账户 403 时 catch 静默处理不阻断

**验证**：`npm run test && npm run lint && npm run build`；打开工作台 → 配额条显示；导入后增长；回收后 ephemeral 归零

#### P1-5 AttributeTable 元数据错误可见

**文件**：`ui/AttributeTable.vue`

**改动**：`loadMetaAndRows()` catch 块保留错误信息为 `metaError` 字符串，在 `load()` 完成后若 `error.value` 为空则写入 `元数据加载失败：${metaError}`（不阻断行数据加载）

**验证**：模拟 meta 端点 500 → 属性表显示错误但行数据正常

#### P1-6 zoomToSelected 多要素 fitBounds

**文件**：`core/workspace-store.ts`、`components/map/imported-layer-module.ts`、`components/MapCanvas.vue`、`ui/AttributeTable.vue`

**改动**：
1. `workspace-store.ts`：`dataWorkspaceHighlight` 类型扩展可选 `features?: GeoJSON.Feature[]`
2. `imported-layer-module.ts` L393：`setFeatureHighlight` 签名从 `(id, feature: GeoJSON.Feature | null)` 扩展为 `(id, feature: GeoJSON.Feature | GeoJSON.Feature[] | null)`，内部统一转数组。`_collectBounds` 已支持多要素遍历（L94-96），无需改动
3. `MapCanvas.vue` L388：`mod.setFeatureHighlight(hl.instanceId, hl.features ?? hl.feature)`
4. `AttributeTable.vue` L385-396：`zoomToSelected` 传 `features: feats.length > 1 ? feats : undefined`

**向后兼容**：联合类型扩展，现有单要素调用无需修改

**验证**：`npm run test && npm run lint`；属性表 Ctrl+多选 → 缩放到选中 → 地图 fitBounds 覆盖全部选中要素

#### P1-7 DataWorkspace 拖放反馈

**文件**：`ui/DataWorkspace.vue`

**改动**：
- import `useDataImportFlow` 的 `processFiles`
- `<aside>` 绑定 `@dragenter/@dragover/@dragleave/@drop`
- `localDropActive` ref 控制边框高亮样式 `.ws-drop-active`
- dragOver 时 `e.dataTransfer.dropEffect = 'copy'`
- 释放后调 `processFiles(e.dataTransfer.files)` 自动分流到导入 Tab

**验证**：从文件管理器拖文件到工作台 → 边框高亮 → 释放后切到导入 Tab

#### P1-8 导出文件大小预估

**文件**：`ui/DataExportPanel.vue`

**改动**：
- 新增 `estimatedSize` computed：矢量按 `JSON.stringify(geojson)` 的 Blob 大小乘以格式系数（CSV ×0.4, SHP-zip ×0.6, GeoJSON ×1.0）；栅格标记为 `-1`（不可预估）
- 多时刻时乘以 `selectedTimes.length`
- 导出按钮上方显示预估提示

**验证**：选矢量图层 → 切换格式 → 预估大小变化；选栅格 → 显示不可预估

### 阶段三：P2 功能增强

#### P2-9 属性表键盘导航

**文件**：`ui/AttributeTable.vue`

**改动**：
- 新增 `focusedCell` ref 和 `onTableKeydown` 函数
- 支持 Arrow/Tab/Shift+Tab/Enter/F2/Escape 键
- `editing` 状态下不触发导航（`if (editing.value) return`）
- `<table>` 添加 `tabindex="0"` 和 `@keydown`；`<td>` 添加 `tabindex="-1"` 和 focused 样式
- 焦点移动后 `scrollIntoView({ block: 'nearest' })`

**验证**：`npm run test && npm run lint`；Tab 向右、Shift+Tab 向左、Arrow 上下、Enter 进入编辑

#### P2-10 数据质量提示

**文件**：`core/attr-display.ts`、`ui/AttributeTable.vue`

**改动**：
1. `attr-display.ts` 追加 `analyzeDataQuality(features, fields)` 函数：
   - 空值率 > 50% 为 warn，> 20% 为 info
   - 坐标超出 WGS84 范围（lng ±180, lat ±90）为 warn（可能 CRS 不匹配）
2. `AttributeTable.vue` 在 `load()` 成功后调用 `analyzeDataQuality`，结果存入 `qualityIssues` ref
3. 模板在 `.sel-hint` 下方展示前 5 条质量提示

**验证**：`npm run test`；新增测试覆盖空值率检测和坐标范围异常检测

#### P2-11 JobsPanel 状态过滤

**文件**：`ui/JobsPanel.vue`

**改动**：
- 新增 `statusFilter` ref（`'all' | 'active' | 'succeeded' | 'failed'`）
- `filteredItems` computed 按状态过滤
- 工具栏添加过滤按钮组（全部 / 进行中 / 成功 / 失败）
- 模板 `v-for` 改用 `filteredItems`

**验证**：切换过滤按钮 → 列表只显示对应状态作业

#### P2-12 导出列表 CSS 虚拟化

**文件**：`ui/DataExportPanel.vue`

**改动**：`.layer-list` 追加 `contain: strict`；`.layer-list li` 追加 `content-visibility: auto; contain-intrinsic-size: 2.2rem`（Chromium 85+ 支持，与项目目标浏览器一致）

**验证**：`npm run build`；导入 50+ 图层 → 导出面板列表滚动流畅

## 假设与决策

1. **P0-1 修改 `removeImportedLayer` catch 行为**：grep 确认无其他调用方，安全修改
2. **P1-6 联合类型扩展**：`setFeatureHighlight` 签名扩展为 `GeoJSON.Feature | GeoJSON.Feature[] | null`，向后兼容
3. **P1-4 配额 API 鉴权**：`require_write_access` 限制，只读账户 403 时静默处理
4. **P2-9 编辑模式冲突**：`editing` 状态下键盘导航不触发
5. **P2-12 虚拟化方案**：采用 CSS `content-visibility` 而非引入虚拟滚动库，因实际图层数通常 < 20

## 验证步骤

每阶段完成后执行全量验证：
```
cd Code/frontend && npm run test
cd Code/frontend && npm run lint
cd Code/frontend && npm run build
cd Code/frontend && npm run check:openapi
cd Code/frontend && npm run check:catalog
```

每项独立提交，遵循 Conventional Commits：
- `fix(data-manager): removeLayer 清理后端存储避免配额泄漏`
- `perf(data-manager): JobsPanel 自适应轮询减少空闲请求`
- `fix(data-manager): 导入遮罩拦截用户操作防止状态不一致`
- `feat(data-manager): 展示存储配额用量与回收`
- `fix(data-manager): 属性表元数据加载失败时展示错误`
- `feat(data-manager): zoomToSelected 支持多要素 fitBounds`
- `feat(data-manager): 工作台面板拖放视觉反馈`
- `feat(data-manager): 导出面板文件大小预估`
- `feat(data-manager): 属性表键盘导航`
- `feat(data-manager): 数据质量提示`
- `feat(data-manager): 作业面板状态过滤`
- `perf(data-manager): 导出图层列表 CSS 虚拟化`
