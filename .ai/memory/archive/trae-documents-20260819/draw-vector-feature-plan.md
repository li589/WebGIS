# 绘制矢量要素功能 — 实施方案

## 一、概述

在 CGDA 中新增"绘制"（Draw）交互模式，支持在地图上绘制多边形、矩形、线段，等价于 ArcGIS"新建要素"功能。绘制后自动分析面板展示栅格统计，支持图层全生命周期管理、属性表编辑、防刷新数据丢失。

## 二、当前状态分析

### 2.1 已有基础

| 区域 | 现有能力 | 文件 |
|------|---------|------|
| 交互模式 | `InteractionMode = 'move' \| 'select' \| 'measure'`，ModeToolbar 按钮组 | `stores/ui.ts`, `ModeToolbar.vue` |
| 测量模块 | 点击打点+双击完成，Canvas 标注层渲染距离/角度，GeoJSON 图层渲染路径 | `map/measure-module.ts`, `measure-canvas.ts`, `measure-geo.ts` |
| 矢量图层 | 完整导入/导出/CRUD，GeoJSON 存储，后端 `data_io` 路由 | `stores/layers/imported-vector.ts`, `data_io/api/router.py` |
| 图层管理 | UUID 实例 ID、命名规范、localStorage 持久化、400ms 防抖 | `stores/layers/active-layers.ts`, `workspace-persist.ts` |
| 分析工具 | `gis.zonal_stats` 分区统计（异步 workflow），`analysis-runner` store | `analysis_router.py`, `analysis_tools.json` |
| 分析面板 | `InfoPanelToolsTab` 工具提交 + `InfoPanelMetaTab` 元数据 | `info-panel/` 目录 |
| 底图要素提取 | `BasemapFeatureExtractCard.vue` 已有从底图提取矢量并创建图层的先例 | `info-panel/BasemapFeatureExtractCard.vue` |

### 2.2 缺失与问题

- **无绘制交互模式**：`InteractionMode` 无 `'draw'`，`map-interaction-module.ts` 无对应处理
- **无 draw 模块**：不存在类似 measure-module 的绘制交互和渲染层
- **无同步分区统计 API**：`gis.zonal_stats` 是异步 workflow，不适合"框选后实时显示"场景
- **无属性表组件**：没有矢量要素属性编辑 UI
- **无可移动编辑工具栏**：左下角区域无浮动工具栏组件
- **无草稿持久化**：刷新丢失编辑中数据

## 三、架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│  ModeToolbar.vue                                         │
│  [Move] [Select] [Measure] [Draw]  ← 新增按钮           │
├─────────────────────────────────────────────────────────┤
│  MapCanvas.vue                                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │  MapLibre GL (map-host)                           │   │
│  │  ├─ draw-features-layer (GeoJSON fill/line)       │   │
│  │  ├─ draw-vertices-layer (GeoJSON circle)          │   │
│  │  └─ draw-preview-layer (GeoJSON line, dashed)     │   │
│  ├─ draw-canvas.ts (Canvas 2D overlay, 顶点手柄)     │   │
│  └─ draw-toolbar.vue (左下角浮动编辑工具栏)          │   │
├─────────────────────────────────────────────────────────┤
│  InfoPanel (分析面板)                                    │
│  └─ ZonalStatsCard.vue (面要素后自动显示栅格统计)       │
├─────────────────────────────────────────────────────────┤
│  数据管理                                               │
│  ├─ draw-store.ts (Pinia, 绘制状态+草稿持久化)          │
│  ├─ stores/layers/ (现有图层管理, 扩展)                 │
│  └─ vector-attribute-table.vue (属性表)                 │
└─────────────────────────────────────────────────────────┘
```

### 3.2 核心数据流

```
用户点击 Draw 按钮
  → uiStore.setInteractionMode('draw')
  → mapInteractionModule 禁用 dragPan，设置 crosshair
  → drawModule.bindEvents() 激活绘制事件
  → drawStore 自动创建临时图层 (draft=true)
  → drawToolbar 出现在左下角

用户点击/拖拽绘制
  → drawModule 捕获 MapLibre click/mousemove/dblclick
  → drawStore 管理顶点栈 + undo 栈
  → GeoJSON 图层实时渲染
  → drawCanvas 渲染顶点手柄和预览线

用户完成多边形 (dblclick / 闭合)
  → drawModule.completeFeature()
  → drawStore 记录要素到 features[]
  → 如果是面要素 → 触发 zonal stats 计算
    → ZonalStatsCard 显示各栅格层均值/最值/像元数
  → drawToolbar 更新要素计数

用户点击保存
  → drawStore 收集所有 GeoJSON features
  → 调用后端 POST /import/vector 创建图层
  → 空图层跳过（丢弃）
  → 非空图层 → 登记到 layersStore
  → 清除草稿持久化
```

## 四、具体实施

### 阶段 1：基础设施 — 交互模式 + Store + 工具栏

#### 1.1 扩展 InteractionMode

**文件**: `Code/frontend/src/stores/ui.ts`

```typescript
// 第 22 行，扩展类型
export type InteractionMode = 'move' | 'select' | 'measure' | 'draw'
```

新增 `DrawState` 接口和 store 状态：

```typescript
export interface DrawState {
  mode: 'polygon' | 'rectangle' | 'line'
  features: DrawFeature[]        // 已完成的要素
  activeVertices: MeasurePoint[]  // 当前绘制中的顶点
  isDrawing: boolean
  hoverPoint: MeasurePoint | null
  selectedFeatureIndex: number | null
  undoStack: DrawFeature[][]
}
```

**文件**: 新建 `Code/frontend/src/stores/draw-store.ts`

独立的 Pinia store（不污染 uiStore），管理：
- `drawMode`: 绘制类型（polygon/rectangle/line）
- `features[]`: 已完成的要素（GeoJSON Feature 数组）
- `activeVertices[]`: 当前绘制中的顶点
- `undoStack`: 撤销栈（完整 features 快照）
- `draftLayerId`: 临时图层 ID
- `draftLayerName`: 临时图层名称
- 草稿持久化：`pagehide` 事件触发 `localStorage.setItem('geo:draw-draft:v1', JSON.stringify(snapshot))`
- 恢复：`onMounted` 时从 localStorage 读取

#### 1.2 模式按钮

**文件**: `Code/frontend/src/components/ModeToolbar.vue`

在 measure 按钮后添加 Draw 按钮（第 252 行附近）：

```html
<IconButton
  size="sm"
  :active="uiStore.interactionMode === 'draw'"
  label="绘制模式（点击添加顶点，双击完成）"
  @click="setInteractionMode('draw')"
>
  <template #icon><PenTool :size="14" /></template>
</IconButton>
```

需要新增 `PenTool` 图标到 `components/ui/icons`。

`setInteractionMode` 函数扩展（第 178 行）：
```typescript
function setInteractionMode(mode: 'move' | 'select' | 'measure' | 'draw') {
  uiStore.setInteractionMode(mode)
  // ...
}
```

#### 1.3 交互模块适配

**文件**: `Code/frontend/src/components/map/map-interaction-module.ts`

第 67-86 行 `applyInteractionMode()` 扩展 `'draw'` 分支：

```typescript
if (mode === 'select' || mode === 'measure' || mode === 'draw') {
  options.map.dragPan.disable()
  if (canvas?.style) {
    canvas.style.cursor = mode === 'draw' ? 'crosshair' : (mode === 'select' ? 'default' : 'crosshair')
  }
}
```

#### 1.4 可移动编辑工具栏

**文件**: 新建 `Code/frontend/src/components/map/draw-toolbar.vue`
**文件**: 新建 `Code/frontend/src/components/map/draw-toolbar.css`

功能：
- 左下角定位（`position: absolute; left: 1rem; bottom: 3.5rem; z-index: 20`）
- 可拖拽移动（mousedown + mousemove 更新 CSS transform）
- 工具按钮：多边形/矩形/线段切换（SegmentedControl）
- 操作按钮：撤销/重做/清除/保存
- 要素计数显示
- 仅在 `interactionMode === 'draw'` 时显示

与 `MapCanvas.vue` 集成：在模板中 `<DrawToolbar>` 置于 `.map-stage` 内部。

### 阶段 2：绘制核心 — Draw Module

#### 2.1 Draw 模块

**文件**: 新建 `Code/frontend/src/components/map/draw-module.ts`

参考 `measure-module.ts` 架构，核心差异：

| 对比 | measure-module | draw-module |
|------|---------------|-------------|
| 图层 | 3 层 (points/line/preview) | 3 层 (features-fill/features-line/vertices/preview) |
| 交互 | click→打点, dblclick→完成 | click→打点, dblclick→闭合多边形, click-drag→矩形 |
| 完成 | 写入 uiStore.measureState | 写入 drawStore.features[] |
| 渲染 | 单段路径 | 多个多边形/线+填充 |

**GeoJSON 图层**（MapLibre）：
- `draw-features-fill-layer` — 面要素填充（半透明，stroke 描边）
- `draw-features-line-layer` — 线要素 / 面边界描边
- `draw-vertices-layer` — 顶点圆点（当前绘制中为蓝色，已完成要素的选中顶点为白色）
- `draw-preview-layer` — 预览虚线（当前鼠标位置到最后一个顶点的连线）

**交互逻辑**：
- `click`: 添加顶点到 activeVertices
- `mousemove`: 更新 hoverPoint，渲染预览线
- `dblclick`: 闭合多边形 / 完成线
- `contextmenu`: 撤销最后一个顶点
- `mousedown+mousemove+mouseup`: 矩形拖拽（当 drawMode === 'rectangle' 时）
- 多边形自动闭合：最后一个顶点与首点距离 < 像素阈值时自动吸附

**矩形模式特殊处理**：
- `mousedown` 记录起始角点
- `mousemove` 渲染矩形预览（4 个点）
- `mouseup` 完成矩形要素

#### 2.2 Draw Canvas（顶点手柄渲染）

**文件**: 新建 `Code/frontend/src/components/map/draw-canvas.ts`

参考 `measure-canvas.ts` 架构，Canvas 2D 叠加层：
- 顶点手柄：小圆圈（半径 6px，白色填充+蓝色描边）
- 预览线：虚线连接最后顶点和鼠标位置
- 中点手柄（面要素边中点）：用于添加新顶点
- 选中要素高亮：黄色边框

### 阶段 3：图层管理

#### 3.1 自动创建临时图层

**文件**: `Code/frontend/src/stores/layers/active-layers.ts`

新增函数 `addDrawDraftLayer(name)`：
- 创建 `ActiveLayer`，`instanceId = UUID`，`catalogId = 'draw-draft-{uuid}'`
- `dataState: 'imported'`，`isImported: true`
- 初始 `importedVector.geojson = { type: 'FeatureCollection', features: [] }`
- `visible: true`，`opacity: 0.85`
- 命名规则：`绘制图层-{timestamp}`（用户可重命名）

**文件**: `Code/frontend/src/stores/draw-store.ts`

`beginDrawSession()` 调用 `addDrawDraftLayer()` 创建临时图层。

#### 3.2 保存图层

**文件**: `Code/frontend/src/stores/draw-store.ts`

`saveDrawLayer()` 函数：
1. 检查 `features.length === 0` → 丢弃，不保存
2. 构造 GeoJSON FeatureCollection
3. 调用 `POST /import/vector` 上传到后端（使用现有 `addImportedVectorLayer` 流程）
4. 后端返回 `layer_id`，更新 `backendLayerId`
5. 触发 `workspacePersist` 持久化
6. 清除草稿 localStorage

#### 3.3 编辑已有矢量图层

**文件**: `Code/frontend/src/stores/draw-store.ts`

`beginEditLayer(instanceId)` 函数：
1. 加载图层的 `geojson`（从 store 或 fetch `/import/layers/{id}/geojson`）
2. 填充 `drawStore.features[]`
3. 设置 `editingLayerId` 标记
4. 进入 draw 模式

保存时：
- 有 `editingLayerId` → 调用 `PATCH` 更新而非 `POST` 创建
- 更新 `updateImportedVectorGeojson()`

#### 3.4 图层操作（重命名、导出、删除）

**文件**: 复用现有 `stores/layers/active-layers.ts` 和 `data_io/api/router.py`

- 重命名：`PATCH /import/layers/{layer_id}/display-name`（已有）+ 同步 `layer-display-names.ts`
- 导出：`POST /export/layer`（已有 GeoJSON/CSV/SHP 格式）
- 删除：`removeLayer()` 现有流程
- 保存检查：后端 `POST /import/layers/{layer_id}/validate`（新增）校验几何有效性

### 阶段 4：栅格区域统计

#### 4.1 同步分区统计 API

**文件**: 新建 `Code/backend/app/api/routers/zonal_stats_router.py` 或扩展 `analysis_router.py`

新增端点 `POST /analysis/zonal-stats/sync`：

```python
class ZonalStatsSyncRequest(BaseModel):
    geojson: dict  # 面要素 GeoJSON
    overlay_layer_ids: list[str]  # 要统计的栅格图层 ID 列表

class ZonalStatsSyncResponse(BaseModel):
    results: list[LayerZonalStats]

class LayerZonalStats(BaseModel):
    layer_id: str
    layer_name: str
    mean: float | None
    max: float | None
    min: float | None
    sum: float | None
    count: int  # 像元数量
    std: float | None
    unit: str | None
```

**实现**（`zonal_stats_service.py`）：
1. 对每个 overlay_layer_id，读取栅格文件路径
2. 使用 `rasterio` 的 `mask` 功能裁剪 GeoJSON 区域
3. 计算 masked array 的统计量
4. 返回汇总结果

**注意**：同步 API 仅在小区域（< 1000 像元）时使用；大区域走异步 workflow。

#### 4.2 前端分析卡片

**文件**: 新建 `Code/frontend/src/components/info-panel/ZonalStatsCard.vue`

- 当 `drawStore` 中新增面要素时自动触发
- 调用 `POST /analysis/zonal-stats/sync`
- 显示表格：图层名 | 均值 | 最大值 | 最小值 | 像元数 | 标准差
- 使用 `useOverlayData` 现有模式获取图层元数据（单位等）
- 加载状态：骨架屏 + "正在计算区域统计…"
- 错误状态：显示错误信息 + 重试按钮

**集成到分析面板**：
- 在 `InfoPanelMetaTab.vue` 或 `InfoPanelVisualTab.vue` 中引入 `ZonalStatsCard`
- 当 `selectedLayer` 是 `draw` 类型的矢量图层时显示

### 阶段 5：属性表

#### 5.1 属性表组件

**文件**: 新建 `Code/frontend/src/components/data-manager/VectorAttributeTable.vue`

功能：
- 表格视图：列 = 属性字段，行 = 要素（按 FID 排序）
- 单元格编辑：双击进入编辑模式，Enter 提交，Esc 取消
- 添加字段：`POST /import/layers/{id}/fields`
- 删除字段：`DELETE /import/layers/{id}/fields/{name}`
- 重命名字段：`POST /import/layers/{id}/rename-field`
- 选择要素：点击行高亮对应地图要素 + 缩放到该要素
- 批量编辑：多选行 → 批量修改属性值
- 分页：`GET /import/layers/{id}/features?page=&size=`（后端已有）

**数据流**：
- 从后端 `GET /import/layers/{id}/features` 加载
- 编辑后 `PATCH /import/layers/{id}/features/{index}` 提交
- 乐观更新 + 失败回滚

#### 5.2 属性表入口

- 在 `LayerSidebar` 的矢量图层右键菜单添加"属性表"选项
- 或在 `InfoPanelMetaTab` 的矢量图层详情中添加"打开属性表"按钮
- 属性表以侧边面板或弹出面板形式展示

### 阶段 6：防刷新数据丢失

#### 6.1 草稿持久化

**文件**: `Code/frontend/src/stores/draw-store.ts`

```typescript
const DRAFT_STORAGE_KEY = 'geo:draw-draft:v1'

interface DrawDraft {
  version: 1
  savedAt: string
  features: GeoJSON.Feature[]
  drawMode: 'polygon' | 'rectangle' | 'line'
  draftLayerName: string
  editingLayerId: string | null
}

function saveDraft() {
  if (drawStore.features.length === 0) {
    localStorage.removeItem(DRAFT_STORAGE_KEY)
    return
  }
  localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify({
    version: 1,
    savedAt: new Date().toISOString(),
    features: drawStore.features,
    drawMode: drawStore.drawMode,
    draftLayerName: drawStore.draftLayerName,
    editingLayerId: drawStore.editingLayerId,
  }))
}
```

**触发时机**：
- `pagehide` 事件（浏览器关闭/刷新/导航离开）
- 每次 `features` 变化（400ms 防抖）
- `beforeunload` 事件：如果 `features.length > 0`，弹出确认对话框

**恢复**：`drawStore` 初始化时从 localStorage 读取草稿，提示用户"检测到未保存的绘制内容，是否恢复？"

### 阶段 7：图标

**文件**: 扩展 `Code/frontend/src/components/ui/icons`

新增图标：
- `PenTool` — 绘制模式按钮（钢笔工具图标）
- 使用 lucide-vue-next 的 `Pen` 或 `Edit3` 图标

### 阶段 8：后端验证

**文件**: 扩展 `Code/backend/app/data_io/api/router.py`

新增端点 `POST /import/layers/{layer_id}/validate`：

```python
@router.post("/import/layers/{layer_id}/validate")
async def validate_layer(layer_id: str):
    """验证图层几何有效性"""
    geojson = load_vector_geojson(layer_id)
    issues = []
    for i, feature in enumerate(geojson.features):
        if not feature.geometry:
            issues.append(f"要素 {i}: 无几何")
        elif not is_valid_geometry(feature.geometry):
            issues.append(f"要素 {i}: 几何无效（自交/空环等）")
    return {"valid": len(issues) == 0, "issues": issues}
```

## 五、文件清单

### 新建文件

| 文件 | 职责 |
|------|------|
| `Code/frontend/src/stores/draw-store.ts` | 绘制状态管理 + 草稿持久化 |
| `Code/frontend/src/components/map/draw-module.ts` | MapLibre 绘制交互核心 |
| `Code/frontend/src/components/map/draw-canvas.ts` | Canvas 2D 顶点手柄渲染 |
| `Code/frontend/src/components/map/draw-toolbar.vue` | 可移动编辑工具栏 |
| `Code/frontend/src/components/map/draw-toolbar.css` | 工具栏样式 |
| `Code/frontend/src/components/info-panel/ZonalStatsCard.vue` | 分区统计结果卡片 |
| `Code/frontend/src/components/data-manager/VectorAttributeTable.vue` | 属性表组件 |
| `Code/backend/app/services/zonal_stats_service.py` | 同步分区统计服务 |
| `Code/backend/app/api/routers/zonal_stats_router.py` | 分区统计 API 路由 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `Code/frontend/src/stores/ui.ts` | 扩展 `InteractionMode` 加 `'draw'`，新增 `DrawState` |
| `Code/frontend/src/components/ModeToolbar.vue` | 新增 Draw 按钮 + PenTool 图标导入 |
| `Code/frontend/src/components/map/map-interaction-module.ts` | `applyInteractionMode` 支持 `'draw'` |
| `Code/frontend/src/components/map/map-canvas-module-bundle.ts` | 创建并注入 `drawModule` |
| `Code/frontend/src/components/map/map-canvas-runtime-module.ts` | 运行时 watcher 支持 draw 模式 |
| `Code/frontend/src/components/map/map-canvas-runtime-watcher.ts` | 同步 draw 状态变化 |
| `Code/frontend/src/components/MapCanvas.vue` | 模板中引入 DrawToolbar，module bundle 绑定 |
| `Code/frontend/src/stores/layers/active-layers.ts` | 新增 `addDrawDraftLayer` |
| `Code/frontend/src/stores/layers/workspace-persist.ts` | 持久化支持 draw 类型图层 |
| `Code/frontend/src/components/ui/icons` | 新增 PenTool 图标导出 |
| `Code/backend/app/api/routers/__init__.py` | 注册 zonal_stats_router |
| `Code/backend/app/data_io/api/router.py` | 新增 validate 端点 |

### 测试文件

| 文件 | 测试内容 |
|------|---------|
| `Test/frontend/stores/draw-store.test.ts` | drawStore 状态管理、草稿持久化 |
| `Test/frontend/components/map/draw-module.test.ts` | 绘制交互逻辑、顶点管理 |
| `Test/frontend/components/map/draw-toolbar.test.ts` | 工具栏 UI 交互 |
| `Test/frontend/components/info-panel/ZonalStatsCard.test.ts` | 统计卡片渲染 |
| `Test/backend/test_zonal_stats_service.py` | 分区统计计算正确性 |

## 六、假设与决策

1. **绘制图层按导入矢量图层管理**：复用 `importedVector` 字段和 `data_io` 后端 API，不引入新图层类型。
2. **同步分区统计仅用于小区域**：多边形面积 < 1000 像元时同步返回；超出范围走异步 workflow。
3. **草稿仅存 localStorage**：不引入 IndexedDB；GeoJSON 体积可控（通常 < 100 要素）。
4. **属性表仅支持已有后端 API**：不分页加载全部要素（小数据集），大数据集走分页。
5. **Draw 按钮放在测量右边**：扩展 `.mode-group` 按钮组，不改变布局。
6. **工具栏初始位置左下角**：`bottom: 3.5rem, left: 1rem`，与地图注记 `.map-note` 上下错开。
7. **矩形模式用 mousedown-mousemove-mouseup**：与多边形 click 模式区分，通过 `drawMode` 状态切换。

## 七、验证步骤

1. **单元测试**：`npm run test -- draw-module draw-store draw-toolbar ZonalStatsCard`
2. **后端测试**：`Env/Python312/python.exe -m pytest Test/backend/test_zonal_stats_service.py`
3. **前端 lint + build**：`npm run lint && npm run build`
4. **手动验证清单**：
   - [ ] 点击 Draw 按钮进入绘制模式，光标变十字
   - [ ] 点击地图添加顶点，实时渲染预览线
   - [ ] 双击闭合多边形，要素出现在图层中
   - [ ] 矩形模式拖拽绘制矩形
   - [ ] 撤销/重做/清除操作正常
   - [ ] 左下角工具栏可拖拽移动
   - [ ] 绘制面要素后，分析面板显示栅格统计
   - [ ] 保存图层后，空图层被丢弃，非空图层持久化
   - [ ] 属性表可编辑、添加/删除字段
   - [ ] 刷新页面后草稿恢复提示
   - [ ] 可编辑已有矢量图层（添加/删除要素）
   - [ ] 图层重命名、导出功能正常
   - [ ] 设置中"地图分布淡底"开关正常