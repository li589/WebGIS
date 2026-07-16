# Frontend

`Code/frontend/` 是本项目的前端工程根目录，为可运行的 `Vue 3 + TypeScript + Vite` 应用。它承担 WebGIS 统一展示壳层：地图主舞台、图层管理、时间控制、任务入口与结果展示。

## 当前前端定位

- `2D-first`：MapLibre 为当前主地图引擎
- 天气图层：标准 z/x/y 瓦片加载 + Canvas 风场叠加
- 图层面板、时间轴、工具栏导入、截图导出、工作流状态
- Cesium / vue-cesium 已在依赖中，尚未成为默认主界面模式

## 当前技术栈

- `Vue 3` + `TypeScript` + `Vite` + `Pinia` + `vue-router`
- `maplibre-gl`
- `vitest`
- `openapi-typescript`（`npm run gen:types` → `src/types/api-contracts.ts`）
- 自定义 Windy 风格组件（未使用 Naive UI）
- 辅助：`html2canvas` / `jspdf`（截图导出）、`papaparse` / `shpjs` / `proj4`（导入与投影）

## 关键目录与文件

- `src/main.ts`：应用入口
- `src/App.vue`：路由出口
- `src/app/router.ts`：当前主路由 `/` → `DashboardView`
- `src/views/DashboardView.vue`：主布局（地图 + 面板 + 工具栏）
- `src/stores/ui.ts`：底图瓦片源、时间轴、交互模式等 UI 状态
- `src/stores/layers/`：图层目录、workflow 编排、result-adapter
- `src/stores/weather-tile-manager.ts`：天气瓦片并发、缓存与优先队列
- `src/stores/import.ts` / `src/stores/log.ts`：数据导入与日志面板
- `src/services/runtime-api.ts`：workflow / runtime API 客户端
- `src/services/weather-tile-api.ts`：Mercator 瓦片数学与 `/weather/tiles` 请求
- `src/components/map/`：地图模块化实现（底图、天气 overlay、风场 Canvas 等）
- `src/styles/main.css`：全局样式

## 当前界面补充说明

- `ModeToolbar.vue`：标题栏工具（底图风格、行政区、导入、截图、工作流入口等）
- `LayerSidebar.vue`：分类、搜索、批量显隐/移除、拖拽排序、多数据源选择
- `InfoPanel.vue`：态势摘要、workflow 状态、天气图例、选中图层/热点信息
- `TimelineScrubber.vue` / `TimelinePanel.vue`：时间轴
- `ScreenshotExport.vue`：截图导出
- `workflow/`：全局工作流状态按钮与面板
- `toolbar/`：数据导入菜单、CSV 对话框、日志面板
- `MapCanvas.vue`：地图运行时总入口（编排各 map 模块）

## 当前地图与天气渲染事实

`MapCanvas.vue` 负责调度：

- 底图 source/layer 与行政区叠加
- hotspot 同步与点击
- 天气 overlay（GeoJSON / COG preview / Canvas）
- 风场粒子、风羽、等值线

天气图层语义：

- `grid_fill`：可多图层并行叠加；优先 `cog_preview_url + cog_bbox`，缺失时回退 GeoJSON
- `point_symbol`：按各自 source/layer 独立渲染
- `particle_flow`：同一时刻只允许一个 catalog，由 `particleFlowCatalogId` 控制

地图上下文会进入图层状态并影响请求：

- `currentMapCenter`
- `currentMapBBox`

天气数据加载主路径已演进为标准瓦片：

- `weather-tile-api.ts` → `GET /weather/tiles/{layer_id}/{z}/{x}/{y}`（热路径，不走 workflow 轮询）
- 底图 MapLibre → `GET /unified-tiles/{layer_id}/{z}/{x}/{y}`
- `weather-tile-manager.ts` 负责视口瓦片集合、并发与预取
- `submitWeatherTileWorkflow` 仅保留给显式扩展 DAG / 调试；计入后端 `weather_tile` 容量池
- 业务分析 workflow 使用独立的 `max_active_runs`（business 池）

## 当前天气相关前端模块

- `components/MapCanvas.vue`：总调度
- `components/map/weather-overlay-*.ts`：overlay 解析、注册、渲染与会话
- `components/map/wind-particle-canvas.ts`：风粒子（Canvas 2D）
- `components/map/wind-barb-layer.ts`：风羽
- `components/map/wind-contour-layer.ts`：等值线
- `components/map/canvas-utils.ts` / `weather-render.ts`：布局与样式映射
- `stores/layers/result-adapter.ts`：解析 `render_hint` 与 `layer_assets`
- `stores/layers/index.ts`：图层状态、workflow、粒子流独占与视口状态

## 当前前端对后端契约的消费方式

稳定消费字段包括：

- `render_hint`
- `point_feature`
- `layer_assets.geojson_url`
- `layer_assets.cog_preview_url`
- `layer_assets.cog_bbox`

控制流走 `runtime-api.ts`（`workflow-runs` / runtime）；配置面走 `settings-api.ts`（`/config/*`，见工具栏「设置」）；天气瓦片面走 `weather-tile-api.ts`（`/weather/tiles`），底图走 `/unified-tiles`。类型优先与 `src/types/api-contracts.ts` 对齐。

开发联调注意：`vite.config.ts` 必须代理 `/config`，否则设置面板会出现「配置加载失败 / unreachable」。

## 页面结构理解

- 壳层：`App.vue` / `main.ts`
- 页面：`DashboardView.vue`
- 组件：工具栏、侧栏、地图、时间轴、信息面板、工作流面板
- 状态：`stores/`
- 服务：`services/`（勿把后端调用散落在组件中）

## 前端运行链路

1. 启动应用，进入 Dashboard
2. 加载底图与图层目录
3. 用户切换图层 / 时间 / 视口
4. 天气层通过瓦片管理器按需拉取并渲染；分析任务通过 workflow-runs 提交并轮询
5. InfoPanel / 工作流面板消费状态与结果视图

## 前端与后端的关系

- 前端负责“怎么展示”和“怎么操作”
- 后端负责“怎么执行”和“怎么回传”
- 共享协议 / OpenAPI 类型负责双方如何理解同一份数据

双通道：

- 控制流：任务状态、事件、取消、重试、runtime
- 数据流：结果 view、artifact、preview、统一瓦片

## 推荐阅读顺序

1. `Code/frontend/README.md`
2. `Code/shared/contracts/README.md`
3. `Code/backend/README.md`
4. `Code/docs/双通道接口设计总结.md`

## 说明

- 文档应优先服务当前实际组件、状态与服务结构
- 扩展地图引擎或图层能力时，保持交互层与服务层分离
- 天气瓦片必须走 `/weather/tiles`；不要再把天气层挂到 `/unified-tiles`；旧 `/tiles` 前缀已删除
