# 标题栏主工具栏重构计划

## 摘要

将标题栏重构为「左侧主工具栏 + 右侧保留元素」的双区布局。左侧主工具栏包含：数据导入（shp/geojson/csv/tif）、行政区边界开关、移动/选择模式按钮、截图、日志按钮。从图层侧边栏移除行政区边界快捷入口。矢量数据前端解析直接渲染，栅格数据（tif）走后端转 COG 后通过现有 overlay 机制加载。同时优化 overlay bounds 缓存以解决图层显示/隐藏时的重复请求问题。

---

## 现状分析

### 标题栏（ModeToolbar.vue）
- 两行布局，`toolbar-main` 使用 `align-items: flex-end`（右对齐）
- 第 1 行：品牌标识 + 底图风格切换 + 截图按钮 + 工作流状态 + 可用性 chip + 2D 指示器
- 第 2 行：地图源选择器 + 时间 chip + 图层信息 chip
- 截图按钮 `emit('openScreenshot')` → DashboardView 打开 ScreenshotExport.vue

### 行政区边界
- catalog.ts 中 `admin-boundary` 条目（`isAdminBoundary: true`），category 为 `boundary`
- LayerSidebar.vue 第 562-569 行：快捷添加按钮（`quick-add-row`）
- admin-boundary-module.ts：加载广东省市边界 GeoJSON，添加 `admin-fill`/`admin-line`/`admin-center-points` 图层
- layers store（index.ts）中大量 `isAdminBoundary` 逻辑分支，深度集成

### 移动/选择按钮
- MapCanvas.vue 第 437-468 行：`.interaction-mode-bar`，定位在 `bottom: 0.72rem; right: 3.8rem`
- 控制 `uiStore.interactionMode`（`'move' | 'select'`）
- 实际交互行为在 map-interaction-module.ts 中绑定

### 截图
- ModeToolbar.vue 中截图按钮 → `emit('openScreenshot')` → DashboardView 打开 ScreenshotExport.vue 模态框

### 数据导入
- 当前无任何数据导入功能
- 前端未安装 shpjs、papaparse
- 后端无文件上传端点（无 UploadFile 使用，无 python-multipart 依赖）
- 后端 rasterio 已可用（raster_preview_service.py 中使用）

### Overlay 加载性能问题
- overlay-image-module.ts 的 `_addOverlay` 每次添加图层都 `fetch('/overlay-bounds/${layerId}')`
- 隐藏时 `_removeOverlay` 完全移除 source，再次显示时重新 fetch bounds + 重建 source
- 导致每次显示/隐藏都请求后端

---

## 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 矢量导入实现 | 前端解析（shpjs/papaparse） | 无需后端改动，立即可用，浏览器直接渲染 GeoJSON |
| 栅格导入实现 | 后端转 COG + 现有 overlay 机制 | 复用 rasterio + raster_preview_service，前端统一 overlay 渲染 |
| CSV→SHP | 不生成 shp 文件，直接渲染为点 GeoJSON | Web 端无需 shp 文件，效果相同，避免额外依赖 |
| 行政区边界 | 保留 catalog 条目和 module，仅移除侧边栏 UI | store 中 isAdminBoundary 逻辑深度集成，最小改动 |
| 现有标题栏元素 | 保留并重新组织到右侧 | 用户选择「保留并重新组织」 |
| 日志内容 | 操作日志 + 工作流日志，带分类筛选 | 用户选择「两者都要」 |
| bounds 缓存 | 前端内存缓存 Map<layerId, boundsData> | 解决重复请求问题 |

---

## 标题栏布局设计

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ [品牌] [📁导入▼] [□边界] [✋][◎] [◫截图] [📋日志]     [空图][街道][影像][地形][深色] [⚙] [2D] │
│                                                                                │
│                                              [源: E O G] [05:00] [图层名] [3个]  │
└────────────────────────────────────────────────────────────────────────────────┘
```

- **左侧主工具栏**（非右对齐）：品牌标识 + 导入菜单 + 边界开关 + 移动/选择 + 截图 + 日志
- **右侧保留区**：底图风格切换、工作流状态、2D 指示器（第 1 行）；地图源、时间、图层信息（第 2 行）
- 整体 `justify-content: space-between`，左侧工具栏 `align-items: flex-start`，右侧 `align-items: flex-end`

---

## 变更清单

### 1. 新增依赖

**文件**: `Code/frontend/package.json`
- 新增 `shpjs`（解析 .shp 文件）
- 新增 `papaparse` + `@types/papaparse`（解析 CSV）

### 2. 新增前端组件

#### 2a. `Code/frontend/src/components/toolbar/DataImportMenu.vue`
导入数据下拉菜单组件。

- 下拉触发按钮「📁导入」，点击展开菜单
- 菜单项：
  - 「导入矢量（SHP/GeoJSON）」→ 触发隐藏 `<input type="file" accept=".shp,.zip,.geojson,.json">`
  - 「导入 CSV」→ 触发隐藏 `<input type="file" accept=".csv">` → 选择文件后打开 CsvImportDialog
  - 「导入栅格（TIF）」→ 触发隐藏 `<input type="file" accept=".tif,.tiff">` → 上传后端
- 矢量处理逻辑：
  - .shp/.zip：`shpjs(buffer)` → GeoJSON FeatureCollection
  - .geojson/.json：`JSON.parse(text)` → GeoJSON FeatureCollection
  - 调用 `importStore.addVectorLayer(name, geojson)` 添加为导入图层
- 栅格处理逻辑：
  - `FormData` 上传到 `POST /import/raster`
  - 后端返回 `{ layer_id, bounds, preview_url }`
  - 调用 `importStore.addRasterLayer(name, layerId, bounds)` 注册为 overlay
- 导入完成后记录日志（logStore.addLogEntry）
- 错误处理：文件解析失败、格式不支持等显示提示

#### 2b. `Code/frontend/src/components/toolbar/CsvImportDialog.vue`
CSV 导入配置对话框。

- Props: `file: File`
- 步骤 1：用 papaparse 解析 CSV，提取列名列表和前 5 行预览
- 步骤 2：用户选择：
  - X 列（经度）下拉框
  - Y 列（纬度）下拉框
  - 坐标系下拉框（EPSG:4326 默认 / EPSG:3857 / EPSG:32649 UTM 49N / 常见中国投影）
- 步骤 3：将每行转为 GeoJSON Point Feature，属性保留所有列
  - 若坐标系非 EPSG:4326，用 `proj4`（或后端）转换坐标
- 预览：显示前 5 个点的坐标转换结果
- 确认 → 调用 `importStore.addVectorLayer(filename, geojson)` 添加图层
- 依赖：如需坐标转换，新增 `proj4` + `@types/proj4` 依赖

#### 2c. `Code/frontend/src/components/toolbar/LogPanel.vue`
日志面板（滑入式，类似 WorkflowStatusPanel）。

- Props: 无（从 logStore 读取）
- Emits: `close`
- 顶部筛选标签：「全部」|「操作日志」|「工作流日志」
- 日志列表：每条显示时间戳、分类标签、消息、可选详情展开
- 操作日志来源：logStore 记录用户操作（图层增删、导入、截图、模式切换、边界开关）
- 工作流日志来源：logStore 订阅 layers store 中的 workflow 事件
- 底部「清空日志」按钮
- 样式：固定定位面板，从右侧滑入，半透明背景

#### 2d. `Code/frontend/src/components/map/imported-layer-module.ts`
导入图层的 MapLibre 渲染模块。

- 接口：
  ```typescript
  interface ImportedLayerModule {
    addVectorLayer(id: string, geojson: GeoJSON.FeatureCollection, name: string): void
    addRasterLayer(id: string, overlayLayerId: string): void  // 委托给 overlayImageModule
    removeLayer(id: string): void
    setLayerVisibility(id: string, visible: boolean): void
    setLayerOpacity(id: string, opacity: number): void
    setLayerStyle(id: string, style: { color?, width?, radius?, fill? }): void
    getLoadedIds(): string[]
  }
  ```
- 矢量渲染：
  - 为每个导入图层创建 GeoJSON source
  - 根据几何类型添加 circle/line/fill 图层
  - 默认样式：点（青色 #5ad5ff，半径 4）、线（青色，宽度 2）、面（半透明青色填充 + 边线）
  - 弹窗：点击 feature 显示属性表
- 栅格渲染：委托给现有 `overlayImageModule.syncOverlays`（将导入的 overlayLayerId 加入 active 列表）
- 清理：地图卸载时移除所有导入 source/layer

### 3. 新增前端 Store

#### 3a. `Code/frontend/src/stores/import.ts`
导入图层状态管理。

```typescript
interface ImportedLayer {
  id: string               // 唯一 ID（如 'imported-1700000000'）
  name: string             // 文件名或自定义名
  type: 'vector' | 'raster'
  geojson?: GeoJSON.FeatureCollection  // 矢量数据
  overlayLayerId?: string  // 栅格对应的 overlay ID
  visible: boolean
  opacity: number
  geometryType?: 'Point' | 'LineString' | 'Polygon' | 'MultiPoint' | 'MultiLineString' | 'MultiPolygon' | 'GeometryCollection'
  featureCount?: number
  addedAt: number
}
```
- State: `importedLayers: ImportedLayer[]`
- Actions:
  - `addVectorLayer(name, geojson)` → 生成 ID，推断几何类型，添加到列表
  - `addRasterLayer(name, overlayLayerId)` → 添加到列表
  - `removeLayer(id)`
  - `toggleVisibility(id)` / `setOpacity(id, opacity)`
  - `renameLayer(id, name)`
- 集成：导入图层也显示在图层侧边栏的「已添加」列表中（通过 layers store adapter 或直接在 LayerSidebar 渲染）

#### 3b. `Code/frontend/src/stores/log.ts`
日志状态管理。

```typescript
interface LogEntry {
  id: string
  timestamp: number
  category: 'operation' | 'workflow'
  type: string       // 如 'layer-add', 'import', 'screenshot', 'workflow-submit', 'workflow-complete'
  message: string
  details?: string
}
```
- State: `entries: LogEntry[]`（最多保留 500 条，超出自动移除最早的）
- Actions:
  - `addLogEntry(category, type, message, details?)`
  - `clearLogs()`
  - `clearCategory(category)`
- 自动记录：
  - 订阅 layers store 的 activeLayers 变化 → 记录图层增删
  - 订阅 workflow 事件 → 记录工作流提交/完成/失败
  - 提供全局可调用的 `logOperation(type, message)` 供各组件手动记录

### 4. 修改前端组件

#### 4a. `Code/frontend/src/components/ModeToolbar.vue` — 重大重构

**模板变更**：
- 在 `.toolbar` 内部新增左侧主工具栏区域 `.toolbar-primary`：
  ```
  <div class="toolbar-primary">
    <!-- 品牌保留在此 -->
    <div class="brand">...</div>
    <div class="primary-tools">
      <DataImportMenu />
      <button class="tool-btn" :class="{ active: isAdminBoundaryActive }" @click="toggleAdminBoundary">□边界</button>
      <div class="mode-group">
        <button :class="{ active: interactionMode === 'move' }" @click="setMode('move')">✋</button>
        <button :class="{ active: interactionMode === 'select' }" @click="setMode('select')">◎</button>
      </div>
      <button class="tool-btn" @click="emit('openScreenshot')">◫截图</button>
      <button class="tool-btn" @click="emit('openLog')">📋日志</button>
    </div>
  </div>
  ```
- 保留右侧 `.toolbar-main`（底图风格、源选择、时间、状态等），但移除截图按钮（移至左侧）
- 新增 emits: `openLog`

**脚本变更**：
- 新增 imports: `DataImportMenu`、`useImportStore`、`useLogStore`
- 新增 computed: `isAdminBoundaryActive`（从 layersStore.activeLayersDisplay 检查 isAdminBoundary）
- 新增 methods:
  - `toggleAdminBoundary()` → 有则移除，无则 `layersStore.addLayer('admin-boundary', true)`
  - `setMode(mode)` → `uiStore.setInteractionMode(mode)`
- 新增 props 传递: `interactionMode`（从 uiStore 读取或注入）

**样式变更**：
- `.toolbar` 改为 `justify-content: space-between`
- `.toolbar-primary` 左对齐，`align-items: center`
- `.primary-tools` 水平排列工具按钮，gap 0.3rem
- `.tool-btn` 统一按钮样式（圆角、半透明背景、hover 高亮、active 强调）
- `.mode-group` 按钮组样式（连体圆角）

#### 4b. `Code/frontend/src/components/MapCanvas.vue`

- **移除**第 437-468 行的 `.interaction-mode-bar` 模板（移动/选择按钮）
- **移除**第 1049-1095 行的 `.interaction-mode-bar` / `.interaction-btn` CSS
- **保留** `uiStore.interactionMode` 在 map-interaction-module 中的使用（实际行为不变）
- **新增** ImportedLayerModule 初始化（与 overlayImageModule 并列）：
  ```typescript
  importedLayerModule = createImportedLayerModule({ map: mapInstance, getMapReady: () => mapReady.value })
  ```
- **新增** watch importStore.importedLayers → 同步到 importedLayerModule

#### 4c. `Code/frontend/src/components/LayerSidebar.vue`

- **移除**第 562-569 行的行政区边界快捷添加区块（`quick-add-row`）
- **移除**相关 CSS（`.quick-add-row`、`.quick-add-btn`、`.qa-icon`、`.qa-tag`）
- **保留**第 792 行 `isAdminBoundary` 在已添加图层列表中的显示标签（边界图层通过工具栏添加后仍显示在列表中）
- **新增**导入图层在「已添加」列表中的渲染（从 importStore 读取，显示文件名、类型图标、几何类型）
  - 支持移除、可见性切换、透明度调节（复用现有图层行交互）

#### 4d. `Code/frontend/src/views/DashboardView.vue`

- 新增 imports: `LogPanel`
- 新增 state: `logOpen = ref(false)`
- 新增 handlers: `handleOpenLog()` / `handleCloseLog()`
- ModeToolbar 新增 prop/emit 传递 `@open-log="handleOpenLog"`
- 模板新增：
  ```html
  <LogPanel v-if="logOpen" @close="handleCloseLog" />
  ```

#### 4e. `Code/frontend/src/components/map/overlay-image-module.ts` — 性能优化

- 新增 `boundsCache = new Map<string, { bounds, meta }>()`
- `_addOverlay` 中先检查 `boundsCache.has(layerId)`，命中则跳过 fetch
- 未命中时 fetch 并存入 cache
- `syncOverlays` 移除图层时不清除 cache（仅清除 loadedOverlays），再次添加时使用缓存
- 新增 `clearBoundsCache(layerId?)` 方法（图层被永久移除时调用）

### 5. 后端变更（仅栅格导入）

#### 5a. `Code/backend/requirements.txt`
- 新增 `python-multipart==0.0.20`（FastAPI 文件上传依赖）

#### 5b. `Code/backend/app/api/routers/import_router.py` — 新增

```python
from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
import tempfile, uuid

router = APIRouter(prefix="/import", tags=["import"])

@router.post("/raster")
async def import_raster(file: UploadFile = File(...)):
    # 1. 保存上传文件到临时目录
    # 2. 用 rasterio 读取，转换为 COG 格式
    # 3. 用 RasterPreviewService 生成预览 PNG
    # 4. 计算 bounds
    # 5. 注册到 overlay_registry（动态注册）
    # 6. 返回 { layer_id, bounds, meta }
```

- 保存路径：`{BACKEND_OUTPUT_ROOT}/imported/{uuid}/`
- COG 转换：rasterio 打开 → 写入 COG 格式
- 预览 PNG：复用 `RasterPreviewService.render_cog_preview`
- bounds：从 rasterio 的 `bounds` 属性获取
- 动态注册：`overlay_registry.register_dynamic(layer_id, cog_path, png_path, bounds, meta)`

#### 5c. `Code/backend/app/app.py`（或主应用注册文件）
- 注册 `import_router` 到 FastAPI app

#### 5d. `Code/backend/app/services/overlay_registry.py` — 扩展
- 新增 `register_dynamic(layer_id, cog_path, png_path, bounds, meta)` 方法
- 动态注册的 overlay 与静态注册的具有相同的 OverlaySpec 结构
- 新增 `unregister_dynamic(layer_id)` 方法（导入图层移除时清理）

### 6. 不变的部分

- `catalog.ts` 中 `admin-boundary` 条目保留（store 逻辑依赖）
- `admin-boundary-module.ts` 保留（MapCanvas 仍调用 ensureLayers/syncOverlay）
- `ScreenshotExport.vue` 不变（仍通过 emit 打开）
- `map-interaction-module.ts` 不变（interactionMode 行为不变，只是触发位置变了）
- 后端 GEE/weather/algorithm 引擎不变

---

## 实施步骤

### 阶段 1：前端基础设施（无后端依赖）
1. 安装前端依赖：`npm install shpjs papaparse @types/papaparse`（+ proj4 如需坐标转换）
2. 创建 `stores/log.ts` — 日志 store
3. 创建 `stores/import.ts` — 导入图层 store
4. 创建 `components/map/imported-layer-module.ts` — 导入图层渲染模块
5. 创建 `components/toolbar/DataImportMenu.vue` — 导入菜单（矢量部分先实现）
6. 创建 `components/toolbar/CsvImportDialog.vue` — CSV 配置对话框
7. 创建 `components/toolbar/LogPanel.vue` — 日志面板

### 阶段 2：标题栏重构
8. 重构 `ModeToolbar.vue` — 左侧主工具栏 + 右侧保留元素
9. 修改 `MapCanvas.vue` — 移除 interaction-mode-bar，初始化 importedLayerModule
10. 修改 `LayerSidebar.vue` — 移除行政区边界快捷添加，新增导入图层列表渲染
11. 修改 `DashboardView.vue` — 接入 LogPanel，传递 openLog emit
12. 优化 `overlay-image-module.ts` — bounds 内存缓存

### 阶段 3：后端栅格导入
13. 后端 `requirements.txt` 新增 python-multipart
14. 创建 `import_router.py` — 栅格上传 + COG 转换 + 预览生成
15. 扩展 `overlay_registry.py` — 动态注册/注销
16. 注册路由到 app
17. 前端 DataImportMenu 接入栅格上传逻辑

### 阶段 4：集成日志
18. 在关键操作点添加 `logStore.addLogEntry` 调用：
    - LayerSidebar: 图层添加/移除
    - DataImportMenu: 导入成功/失败
    - ModeToolbar: 边界开关、模式切换、截图
    - layers store: 工作流提交/完成/失败（订阅现有事件）

---

## 验证步骤

1. **TypeScript 检查**：`cd Code/frontend && npm run type-check` 无错误
2. **浏览器视觉测试**：
   - 标题栏左侧显示主工具栏（导入/边界/移动选择/截图/日志），右侧保留底图风格等
   - 点击「边界」按钮 → 行政区边界叠加显示，再次点击隐藏
   - 点击「移动」「选择」→ 地图交互模式切换，右下角不再有按钮
   - 点击「截图」→ 截图模态框打开
   - 点击「日志」→ 日志面板滑入，显示操作记录
3. **矢量导入测试**：
   - 导入 .geojson 文件 → 图层显示在地图上和侧边栏列表中
   - 导入 .shp 文件（或 .zip）→ 正确解析并渲染
   - 导入 .csv 文件 → 弹出配置对话框 → 选择 XY 列和坐标系 → 点图层渲染
4. **栅格导入测试**：
   - 导入 .tif 文件 → 上传后端 → 转换 COG → overlay 渲染显示
5. **图层侧边栏**：
   - 行政区边界快捷添加按钮已移除
   - 导入的图层显示在已添加列表中，可移除/切换可见性/调透明度
6. **bounds 缓存**：
   - 添加 overlay 图层 → 隐藏 → 再次显示 → Network 面板中无 `/overlay-bounds` 重复请求
7. **日志面板**：
   - 执行各种操作 → 日志实时记录
   - 筛选标签切换 → 正确过滤
   - 清空按钮 → 清除所有日志

---

## 假设与约束

1. shpjs 能在浏览器中解析标准 .shp 文件（含 .dbf/.shx 的 .zip 包）
2. CSV 坐标转换使用 proj4 前端库（需新增依赖），或限制仅支持 EPSG:4326（无需转换）
3. 后端 rasterio 已安装且可用（raster_preview_service.py 已验证）
4. 导入的栅格文件大小限制由后端配置（建议 < 500MB）
5. 导入图层为会话级（刷新页面后丢失），不持久化存储（如需持久化需额外存储方案）
6. logStore 最多保留 500 条日志，超出自动移除最早记录
7. 行政区边界 catalog 条目保留，仅移除侧边栏 UI 入口
