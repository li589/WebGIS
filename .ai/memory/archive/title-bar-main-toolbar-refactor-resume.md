# 标题栏主工具栏重构 — 续接计划

## 摘要

续接上一会话的标题栏主工具栏重构任务。Phase 1（前端基础设施，7 个新文件）和 Phase 2 的 ModeToolbar.vue 重构已完成。本计划覆盖剩余的 Phase 2（4 个文件修改）、Phase 3（后端栅格导入）、Phase 4（日志集成）和验证步骤。

## 当前状态分析

### 已完成（Phase 1 + ModeToolbar）
- `stores/log.ts` ✅ — 日志 store（操作日志 + 工作流日志，最多 500 条）
- `stores/import.ts` ✅ — 导入图层 store（矢量/栅格，含 addVectorLayer/addRasterLayer/removeLayer）
- `components/map/imported-layer-module.ts` ✅ — MapLibre 渲染模块（fill/line/circle/symbol，点击弹窗）
- `components/toolbar/DataImportMenu.vue` ✅ — 导入下拉菜单（矢量/CSV/栅格三项）
- `components/toolbar/CsvImportDialog.vue` ✅ — CSV 配置对话框（papaparse + proj4）
- `components/toolbar/LogPanel.vue` ✅ — 右侧滑入式日志面板（筛选 + 展开详情）
- `types/shpjs-proj4.d.ts` ✅ — shpjs/proj4 类型声明
- `components/ModeToolbar.vue` ✅ — 左侧主工具栏（品牌 + 导入 + 边界开关 + 移动/选择 + 截图 + 日志）+ 右侧保留区（底图风格 + 工作流状态 + 2D + 源 + 时间 + 图层信息）

### 待完成

#### Phase 2：标题栏重构（4 个文件）
1. **MapCanvas.vue** — 移除右下角 interaction-mode-bar，初始化 ImportedLayerModule
2. **LayerSidebar.vue** — 移除行政区边界快捷添加区块
3. **DashboardView.vue** — 接入 LogPanel
4. **overlay-image-module.ts** — bounds 内存缓存（解决显示/隐藏重复请求）

#### Phase 3：后端栅格导入
5. **import_router.py**（新建）— `POST /import/raster` 接收 TIF，转 COG，生成预览 PNG + bounds JSON，动态注册到 overlay_registry
6. **main.py** — 注册 import_router
7. **requirements.txt** — 添加 python-multipart

#### Phase 4：日志集成
8. 在关键操作点添加 logStore 调用

---

## 变更清单

### 2a. MapCanvas.vue — 移除 interaction-mode-bar + 接入 ImportedLayerModule

**文件**: `Code/frontend/src/components/MapCanvas.vue`

**移除**:
- 第 437-468 行：`.interaction-mode-bar` 模板（移动/选择按钮组），含注释行 437
- 第 1049-1095 行：`.interaction-mode-bar` / `.interaction-mode-bar:hover` / `.interaction-btn` / `.interaction-btn:hover` / `.interaction-btn.active` CSS 块

**保留**:
- `uiStore.interactionMode` 在 map-interaction-module 中的使用（实际行为不变，ModeToolbar 已通过 `uiStore.setInteractionMode` 控制）

**新增**:
1. 第 13 行后新增 import：
   ```ts
   import { createImportedLayerModule } from './map/imported-layer-module'
   import { useImportStore } from '../stores/import'
   ```

2. 第 79-80 行附近（overlayImageModule 声明处）新增：
   ```ts
   let importedLayerModule: ReturnType<typeof createImportedLayerModule> | null = null
   ```

3. 第 302-309 行附近（overlayImageModule 初始化后）新增：
   ```ts
   // ─── Imported layer module (前端导入的矢量/栅格图层) ──────────────────────
   importedLayerModule = createImportedLayerModule({
     map: mapInstance,
     getMapReady: () => mapReady.value,
   })
   ```

4. 第 321-324 行附近（watch activeLayersDisplay 后）新增 watch importStore：
   ```ts
   // 同步导入的矢量图层到地图
   watch(
     () => importStore.importedLayers.map((l) => l.id + ':' + l.visible + ':' + l.opacity).join(','),
     () => {
       if (!importedLayerModule) return
       const imported = importStore.importedLayers
       const loadedIds = new Set(importedLayerModule.getLoadedIds())
       // 添加新导入的矢量图层
       for (const layer of imported) {
         if (layer.type === 'vector' && layer.geojson && !loadedIds.has(layer.id)) {
           importedLayerModule.addVectorLayer(layer.id, layer.geojson, layer.name)
         }
       }
       // 同步可见性和透明度
       for (const layer of imported) {
         importedLayerModule.setLayerVisibility(layer.id, layer.visible)
         importedLayerModule.setLayerOpacity(layer.id, layer.opacity)
       }
       // 移除已删除的图层
       for (const id of loadedIds) {
         if (!imported.some((l) => l.id === id)) {
           importedLayerModule.removeLayer(id)
         }
       }
     },
   )
   ```

5. onBeforeUnmount 中（第 328-330 行）新增清理：
   ```ts
   importedLayerModule?.dispose()
   ```

### 2b. LayerSidebar.vue — 移除行政区边界快捷添加

**文件**: `Code/frontend/src/components/LayerSidebar.vue`

**移除**: 第 562-569 行附近的行政区边界快捷添加按钮区块。需读取该区域精确内容后移除整个 `.quick-add` 相关区块（保留 `addCatalogItem` 函数本身，因为其他地方可能调用）。

**保留**: `catalog.ts` 中的 `admin-boundary` 条目（store 逻辑深度依赖 `isAdminBoundary`，约 30+ 处引用），`admin-boundary-module.ts` 不变。

### 2c. DashboardView.vue — 接入 LogPanel

**文件**: `Code/frontend/src/views/DashboardView.vue`

**新增**:
1. import（第 9 行后）：
   ```ts
   import LogPanel from '../components/toolbar/LogPanel.vue'
   ```

2. 第 41-42 行附近新增状态：
   ```ts
   const logOpen = ref(false)
   ```

3. 第 248-256 行的 ModeToolbar 模板中，新增 `@open-log` 处理：
   ```html
   @open-log="logOpen = true"
   ```

4. 第 338-347 行附近（ScreenshotExport 后）新增 LogPanel：
   ```html
   <LogPanel v-if="logOpen" @close="logOpen = false" />
   ```

### 2d. overlay-image-module.ts — bounds 内存缓存

**文件**: `Code/frontend/src/components/map/overlay-image-module.ts`

**问题**: 当前 `syncOverlays` 在图层隐藏时调用 `_removeOverlay` 删除 source/layer 并从 `loadedOverlays` 移除；再次显示时 `_addOverlay` 重新请求 `/overlay-bounds/{layerId}`，导致每次显示/隐藏都请求后端。

**修改**:
1. 第 55 行附近新增 boundsCache：
   ```ts
   const boundsCache = new Map<string, { bounds: [number, number, number, number]; meta: any }>()
   ```

2. `_addOverlay` 函数（第 113 行起）中，将 `fetch('/overlay-bounds/${layerId}')` 替换为缓存优先逻辑：
   ```ts
   let boundsData
   const cached = boundsCache.get(layerId)
   if (cached) {
     boundsData = { bounds: cached.bounds, meta: cached.meta }
   } else {
     const boundsResp = await fetch(`/overlay-bounds/${layerId}`)
     if (!boundsResp.ok) { ... return }
     boundsData = await boundsResp.json()
     boundsCache.set(layerId, { bounds: boundsData.bounds, meta: boundsData.meta ?? {} })
   }
   const bounds = boundsData.bounds
   const meta = boundsData.meta ?? {}
   ```

3. `_removeOverlay` 中**不清除** boundsCache（缓存跨显示/隐藏周期复用）

### 3a. import_router.py — 后端栅格导入（新建）

**文件**: `Code/backend/app/api/routers/import_router.py`（新建）

**功能**: `POST /import/raster` 接收 TIF 文件 → 转 COG → 生成预览 PNG + bounds JSON → 动态注册到 overlay_registry → 返回 layer_id + bounds

**实现要点**:
- 使用 `UploadFile` 接收文件（需 python-multipart）
- 保存到 `BACKEND_OUTPUT_ROOT/imports/{uuid}/{original_name}`
- 用 rasterio 读取 bounds（`dataset.bounds`）和计算降采样预览
- 复用 `RasterPreviewService.render_cog_preview` 生成 PNG（palette 用 'wind-blue' 默认）
- 生成 bounds JSON：`{"bounds": [west, south, east, north], "meta": {...}}`
- 动态调用 `overlay_registry.register_overlay(OverlaySpec(...))` 注册
- 返回 `{"layer_id": "imported-{uuid}", "bounds": [west, south, east, north]}`

**路由结构**:
```python
from fastapi import APIRouter, UploadFile, File, HTTPException
from app.services.overlay_registry import register_overlay, OverlaySpec
from app.services.raster_preview_service import raster_preview_service
import rasterio
from pathlib import Path
import uuid, json, shutil, os

router = APIRouter(prefix="/import", tags=["import"])

@router.post("/raster")
async def import_raster(file: UploadFile = File(...)):
    # 1. 保存文件
    # 2. rasterio 读取 bounds + 计算预览
    # 3. 生成 PNG + bounds JSON
    # 4. register_overlay 动态注册
    # 5. 返回 layer_id + bounds
```

**存储路径**:
- 导入文件: `{BACKEND_OUTPUT_ROOT}/imports/{uuid}/{filename}`
- 预览 PNG: `{BACKEND_OUTPUT_ROOT}/imports/{uuid}/preview.png`
- bounds JSON: `{BACKEND_OUTPUT_ROOT}/imports/{uuid}/bounds.json`

### 3b. main.py — 注册 import_router

**文件**: `Code/backend/app/main.py`

**修改**:
1. 第 10-19 行的 import 块新增：
   ```python
   from app.api.routers import import_router
   ```

2. 第 134-145 行的 `include_router` 块新增：
   ```python
   app.include_router(import_router)
   ```

### 3c. requirements.txt — 添加 python-multipart

**文件**: `Code/backend/requirements.txt`

**修改**: 末尾新增 `python-multipart`（FastAPI 文件上传依赖）

### 4. 日志集成

在以下关键操作点添加 `logStore.logOperation` 或 `logStore.logWorkflow` 调用：

**MapCanvas.vue**（map-interaction-module 或相关 watch 中）:
- 点天气查询成功/失败时 → `logStore.logWorkflow`

**LayerSidebar.vue**:
- 图层添加 → `logStore.logOperation('layer-add', ...)`
- 图层移除 → `logStore.logOperation('layer-remove', ...)`
- 图层显示/隐藏切换 → `logStore.logOperation('layer-visibility', ...)`

**注**: ModeToolbar.vue 和 DataImportMenu.vue 已内置日志调用，无需重复添加。

---

## 假设与决策

1. **行政区边界**: 保留 catalog 条目和 admin-boundary-module.ts（store 逻辑深度依赖），仅移除 LayerSidebar 快捷添加 UI，改为 ModeToolbar toggle 按钮（已完成）
2. **混合导入**: 矢量（shp/geojson/csv）前端解析直接渲染；栅格（tif）上传后端转 COG 后通过 overlay 机制加载
3. **boundsCache 生命周期**: 进程级内存缓存，不主动清除（导入栅格图层移除时也不清除，因为 overlay_registry 中的注册也不清除，允许再次添加时复用）
4. **import_router 存储路径**: 使用 `BACKEND_OUTPUT_ROOT/imports/` 目录，符合项目约定
5. **日志集成范围**: 仅在用户可见的关键操作点添加，避免过度日志（如地图拖动、缩放不记录）

---

## 验证步骤

### 前端验证
1. `cd Code/frontend && npx vue-tsc --noEmit` — TypeScript 类型检查无错误
2. `npm run dev` 启动开发服务器
3. 浏览器验证：
   - 标题栏左侧主工具栏显示：品牌 + 导入 + 边界 + 移动/选择 + 截图 + 日志
   - 右下角不再有 interaction-mode-bar
   - 点击「边界」按钮可开关行政区边界
   - 点击「日志」按钮右侧滑入日志面板
   - 导入 SHP/GeoJSON 文件后地图显示矢量要素
   - 导入 CSV 弹出配置对话框，选择 XY 列和坐标系后生成点图层
   - 导入 TIF 文件上传后端，成功后显示栅格图层
   - 图层显示/隐藏切换时 Network 面板不再重复请求 /overlay-bounds

### 后端验证
1. `cd Code/backend && pip install python-multipart`
2. 启动后端服务
3. `curl -X POST http://localhost:8000/import/raster -F "file=@test.tif"` 返回 `{"layer_id": "imported-xxx", "bounds": [...]}`
4. `GET /overlay-preview/imported-xxx` 返回 PNG 图片
5. `GET /overlay-bounds/imported-xxx` 返回 bounds JSON
