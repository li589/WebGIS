# Frontend

`Code/frontend/` 是本项目的前端工程根目录，为可运行的 `Vue 3 + TypeScript + Vite` 应用。它承担 WebGIS 统一展示壳层：地图主舞台、图层管理、时间控制、任务入口与结果展示。

## 当前前端定位

- `2D-first`：MapLibre 为当前主地图引擎
- 天气图层：标准 z/x/y 瓦片加载 + Canvas 风场叠加；支持多 Provider 钉源（侧栏与 InfoPanel，偏好存 localStorage；`open-meteo-online` / `open-meteo-local` / 商业源）
- 图层面板、时间轴、工具栏「数据」工作台（导入/导出/属性表/详情/作业）、截图导出、工作流状态
- Cesium / vue-cesium 已在依赖中，尚未成为默认主界面模式

## 当前技术栈

- `Vue 3` + `TypeScript` + `Vite` + `Pinia` + `vue-router`
- `maplibre-gl`
- `vitest`
- `openapi-typescript`（`npm run gen:types` → `src/types/api-contracts.ts`）
- 自定义 Windy 风格组件（未使用 Naive UI）
- 辅助：`html2canvas` / `jspdf`（截图导出）；本地导入主路径走 `src/data-manager/`（`core/api.ts` → 后端 `/import/*`、`/export/*`，Vite 均需 proxy）

## 关键目录与文件

- `src/main.ts`：应用入口
- `src/App.vue`：路由出口
- `src/app/router.ts`：当前主路由 `/` → `DashboardView`
- `src/views/DashboardView.vue`：主布局（地图 + 面板 + 工具栏）
- `src/stores/ui.ts`：底图瓦片源、时间轴、交互模式等 UI 状态
- `src/stores/layers/`：图层目录、workflow 编排、result-adapter
- `src/stores/weather-tile-manager.ts`：天气瓦片并发、缓存与优先队列（缓存键含 provider）；`data-empty` 按 layerId 隔离，不因全局 `modelEmpty` 连坐其它层
- `src/stores/weather-source-prefs.ts`：每图层天气源偏好（auto / provider_id；旧 `open-meteo` 映射为 `open-meteo-online`）
- `src/stores/log.ts`：日志面板
- `src/data-manager/`：数据管理器（`ui/` 工作台面板、`core/` API 与 workspace store、`adapters/` 导出/图层注册）；`services/data-io.ts` 为兼容 re-export
- `src/services/runtime-api.ts`：workflow / runtime / weather providers-for-layer API 客户端
- `src/services/weather-tile-api.ts`：Mercator 瓦片数学与 `/weather/tiles` 请求（支持 `provider`）
- `src/components/map/`：地图模块化实现（底图、天气 overlay、风场 Canvas 等）
  - `weather-tile-banner.ts`：全图横幅按层隔离聚合（仅当可见天气层均无缓存且有错误时才盖 error）
  - `effective-layer-symbology.ts`：InfoPanel / LayerSidebar 图例同源（色板覆盖；`legend_ticks` 优先配置，不足时视口采样）
- `src/styles/main.css`：全局样式

### 天气模型 / Provider 缺口（瓦片热路径）

| 现象 | 说明 |
|------|------|
| `visibility` + 非 `gfs_global` | 能见度场主要来自 GFS；其它模型常返回 data-empty |
| 80 m 风 / 温度 | 无原生该高度场时由邻近层外推，非独立观测层 |
| `open-meteo-local` | 依赖 `cgda-open-meteo` volume；先 `python launch.py sync`（至少 `ecmwf_ifs025`，能见度需 `gfs_global`） |
| 编辑器天气 demo | 系统种子 `weather_temperature_grid_demo` / `weather_wind_field_demo`；主展示仍走 `/weather/tiles` |

### 选择 / 点击与分析框约定

| 通道 | 说明 |
|------|------|
| 图层选中 | `layersStore.selectedInstanceId` → LayerSidebar / InfoPanel「当前对象」 |
| 地图点查 | 工具栏「选择」模式点击，或漫游下 `Shift`+点击；结果进 InfoPanel「点天气」+ 地图橙点标记 |
| 点查图层 | 优先当前选中且可见的天气层；否则最顶层可见天气层 |
| 时间轴 | `tileForecastHour` 变化会刷新点查，并高亮对应小时条 |
| Overlay 像素 | 与点查同坐标；快速连点用序号丢弃过期响应 |
| 热点 | 地图钉与分析框列表双向可选 |

### 浮动面板（ControlPanel）缩放 / 位置

`ControlPanel.vue` + `control-panel-geometry.ts`：

| 行为 | 规则 |
|------|------|
| 分析框缩放 | 右下角手柄为 `bottom-left`；`overlay-right` 为 `width: max-content` 钉右缘，向左/下长高，其它角不动 |
| 拖动 | 只改 `offsetX/Y`（有限范围 clamp），**不改**宽高 |
| 记忆 | `localStorage` key `geo-panel:{panelKey}`；offset 与 width/height 分字段；未手动缩放时不写尺寸 |
| 缩放时 | 禁止再改 offset（分析框）；交互中关闭 transform 过渡，避免发飘 |

### 当前界面补充说明

- `ModeToolbar.vue`：标题栏工具（底图风格、行政区、数据导入/导出、截图、工作流入口等）
- `LayerSidebar.vue`：分类、搜索、批量显隐/移除、拖拽排序；`online-weather` 卡片接入运行时 `providers-for-layer` 选源
- `InfoPanel.vue`：态势摘要、workflow 状态、天气图例/数据源钉选、选中图层/热点信息（图例经 `effective-layer-symbology` 与侧栏色条同源；说明文案可跟 live `windDisplayMode`）
- `ControlPanel.vue`：图层 / 分析等浮动框（拖动记忆位置、角点缩放）
- `TimelineScrubber.vue` / `TimelinePanel.vue`：时间轴
- `ScreenshotExport.vue`：截图导出
- `workflow/`：全局工作流状态按钮与面板；`WorkflowEditorPanel` 画布 Run 提交编译后的 `workflow_definition`
- `toolbar/`：日志面板；数据入口见 `src/data-manager/ui/DataImportMenu.vue` + `DataWorkspace.vue`
- `data-manager/`：导入/导出/属性表/详情/作业；侧栏与 InfoPanel 仅调用 `openDataWorkspace` / `exportLayer`
- `settings/`：系统设置（**数据根 / 产物根可编辑**并「保存并重启后端」、数据源扫描、开放数据预设、静态缓存清理、远程存储 profile）
- `MapCanvas.vue`：地图运行时总入口（编排各 map 模块；天气错误横幅按层隔离，不因单层无数据盖住健康层）

## 当前地图与天气渲染事实

`MapCanvas.vue` 负责调度：

- 底图 source/layer 与行政区叠加
- hotspot 同步与点击
- 天气 overlay（GeoJSON / COG preview / Canvas）
- 风场粒子 / 流量场、风羽、等值线

天气图层语义：

- `grid_fill`：可多图层并行叠加；优先 `cog_preview_url + cog_bbox`，缺失时回退 GeoJSON
- `point_symbol`：按各自 source/layer 独立渲染
- `particle_flow`：同一时刻只允许一个 catalog，由 `particleFlowCatalogId` 控制；UI 三态 `particle` / `streamline`（流量场）/ `off`（网格色底）

### 风场粒子 / 流量场约定

| 模式 | 主实现 | 要点 |
|------|--------|------|
| 粒子流 `particle` | WebGL（`wind-particle-webgl-*`）；`?windgl=0` → Canvas `wind-particle-canvas.ts` | 默认路径；急流区降低 drop bump + 多子步 RK2；粒子与色场均按世界副本绘制，避免日界线半屏空白 |
| 流量场 `streamline` | Canvas `wind-streamline-layer.ts` | 视口∩grid 撒种；`lonWrapOffset` 仅在数据变化 / zoomend 重算；绘制 `base±360` 世界副本 |
| 网格 `off` | 风速色底（平滑开=WebGL 连续面，关=MapLibre 网格） | 无粒子流/流量场 |

用户可见文案以 `ui-copy` + `windDisplayModeLabel` 为准（粒子流 / 流量场 / 网格），**禁止**把 `particle_flow` / `streamline` / `off` 直接当 chip 展示。

### 底图默认与选项序

- 默认：`gaode-street`（`getDefaultTileSource()` / `ui.tileSourceId`）
- 街道 Tab 序：高德 → Bing → 其余；影像：高德卫星 → Bing 航空 → 其余
- 高德经 `/unified-tiles` 做 GCJ 瓦片索引转换；Bing Key 在设置「API 管理」可选配置
- 风格 Tab「空白」与源「空白」同词；pill 显示短名（高德 / Bing / Esri…）而非单字母
- 工具栏不再对高德/Bing 显示「需坐标转换」警告（属正常代理路径；缺 Key 仍显示「需配置底图 API Key」）

缩放 + 视口刷新后的已知坑与对策：

- **大范围 zoom-out 后视口几乎空白、贴边才有线**：曾因按全 grid 摊薄 `MAX_STREAMLINES`，且 wrap 用 bounds 均值 / 每帧重算落到错误世界副本。现按视口撒种 + `map.getCenter().lng` 算 wrap + 多副本绘制（`canvas-utils.computeCanvasLayout` / `resolveStreamlineSeedBounds`）。
- **粒子急流区闪烁**：WebGL/Canvas 共用压低的 `DROP_RATE_BUMP` 与位移钳制（见 `wind-particle-webgl-shaders.ts` / `wind-particle-canvas.ts`）。
- **半屏空白 / 错位叠影**：瓦片集合未变时仍须同步 bbox（`weather-tile-manager` view-only 路径）；粒子 Canvas 交互中勿频繁改 `lonWrapOffset`。
- **缩放后中间空洞、周围有数**：视口瓦片 `sortTilesCenterFirst` 先拉中心；merge 在覆盖未齐时用父级/邻近 z/**上一帧**垫底，且勿把稀缺帧写成 `lastMerged` 锚点。
- **日界线附近仅窄条有风场**：WebGL 粒子绘制与色场相同，按 `computeWorldWrapOffsets` 投多世界副本（`uploadParticlePointBuffer`）；Canvas/流线路径已有 `lonWrapOffset`。
- **亚太视口却只显示美洲风场**：`normalizeLngBounds` 必须以地图中心校正；禁止先把 east/west 各自折进 [-180,180] 再取短弧。错半球时改用含中心的互补弧（见 `map-viewport-sync.ts`）。
- **大范围（跨度>180°）仍只亮美洲**：merge→`buildWindGridFromGeoJSON` 须传视口 `LonFrame`（经度略 pad，丢弃帧外点）；`isLonInFrame` 接受 ±360 别名；`tileBoundsOverlapViewport` 禁止无脑 +360 别名。视口变更按**与当前视口重叠**驱逐错半球缓存（勿仅按 `desiredKeys`，否则会误删多 z 下垫 → 日界线小片空白）。宽跨度 `lastMerged` 覆盖门槛适中（约 0.65 / 中心或 0.85），允许 parent 垫底。
- **流量场半屏/零星不稳定**：跨日界线种子框保持连续弧（勿 min/max 压短）；`moveend`/`zoomend` 与同 checksum 网格更新均按当前视口重撒种子。
- **日界线附近只亮面积较大的半球**：`getBounds` 在 `renderWorldCopies` 下常漏掉以世界副本可见的另一侧。`buildMapViewportSnapshot` / `tilesInViewport` 用 `center ± worldSize` 估弧，经 `preferVisibleLngBounds` 在视觉跨 IDL 时升级 bbox，保证瓦片与 LonFrame 双侧齐全。
- **全球/近全球仍半屏 + 日界线阴影细带**：`getBounds` 常给出 ~340° 弧并在 ±180 留窄缝；跨度≥300° 时强制 `[-180,180]`。网格 fill 对跨日界线格元 `splitAntimeridianCellBounds` 拆成两侧短弧多边形，避免 MapLibre 画成长路径细带。
- **可见经度弧真源**：瓦片 / LonFrame / 粒子 roam / 流线撒种必须走 `resolveVisibleLngBounds`（或 `resolveVisibleViewportBBox`）；禁止生产路径单独 `normalizeLngBounds(getBounds())`（缺 worldSize 升级会半屏）。
- **缩放后天气瓦片偶发不加载 / 偏慢**：`weather-viewport` 的 maxWait 必须读 live `currentMap*`（勿闭包冻结首帧 snap），否则持续缩放越过 maxWait 会用过期视口清掉最新防抖；`map-interaction-module` 在 `zoom` 中途同步、`move` 节流（≥100ms）同步，在 `zoomend`/`moveend` 以 `{ immediate: true }` 零等待 flush。
- **多天气图层抢槽变慢**：全局并发对齐后端 semaphore（≤6）；换 tile z 时短时拉满 cap；`pickNextRequest` 同优先级跨图层 round-robin；可见层 ≥2 时邻域 depth 降为 1 并跳过邻小时预取，把槽位留给各层当前小时视口。
- **进度指示**：地图横幅需同时订阅 `activityVersion`（瓦片入队/完成）与 `statusVersion`；半填充且仍有 pending 时显示带 `cached/total` 的 partial；工作流状态面板天气行展示视口填充进度条。分析类 `supportsViewportDrivenRefresh` 仍走独立 500ms debounce，不与天气 immediate flush 混用。

地图上下文会进入图层状态并影响请求：

- `currentMapCenter`
- `currentMapBBox`
- `currentMapZoom`

天气数据加载主路径已演进为标准瓦片：

- `weather-tile-api.ts` → `GET /weather/tiles/{layer_id}/{z}/{x}/{y}`（热路径，不走 workflow 轮询）；`tilesInViewport` 经 `resolveVisibleLngBounds` 校正日界线
- 底图 MapLibre → `GET /unified-tiles/{layer_id}/{z}/{x}/{y}`
- `stores/layers/weather-viewport.ts`：视口防抖 / maxWait live-read / `immediate` flush
- `map-viewport-sync.ts`：`resolveVisibleLngBounds` 为可见经度弧真源（normalize + center/worldSize）；近全球跨度≥300° 闭合为世界
- `weather-tile-manager.ts` 负责视口瓦片集合、并发与预取；TTL/SWR、单层同小时 depth=3 邻域与邻小时视口预取；多层时 depth=1 且抑制邻小时；同优先级图层轮询；视口瓦片中心优先入队
- 图层无数据（422 / `data-empty`）只短路该 `layerId`；工作流六态贡献与地图横幅均不因其它层失败而连坐
- `submitWeatherTileWorkflow` 仅保留给显式扩展 DAG / 调试；计入后端 `weather_tile` 容量池
- 业务分析 workflow 使用独立的 `max_active_runs`（business 池）

## 当前天气相关前端模块

- `components/MapCanvas.vue`：总调度
- `components/map/weather-tile-banner.ts`：可见天气层横幅聚合（error / loading / partial）
- `components/map/effective-layer-symbology.ts`：有效符号学（图例色带 / ticks / explainer）
- `components/map/weather-overlay-*.ts`：overlay 解析、注册、渲染与会话
- `components/map/wind-particle-webgl-*.ts`：风粒子（默认 WebGL）
- `components/map/wind-particle-canvas.ts`：风粒子（Canvas 回退）
- `components/map/wind-streamline-layer.ts`：流量场（流线动画）
- `components/map/wind-barb-layer.ts`：风羽
- `components/map/wind-contour-layer.ts`：等值线
- `components/map/canvas-utils.ts`：`lonWrapOffset` / 布局（wrap 对齐相机中心）
- `components/map/weather-render.ts`：样式映射
- `ui-copy/`：验收中文词表（品牌 / 底图 / 风场 / 点查 / 图层 / 工作流 / 地图）
- `stores/layers/result-adapter.ts`：解析 `render_hint` 与 `layer_assets`
- `stores/layers/index.ts`：图层状态、workflow、粒子流独占与视口状态
- `stores/layers/weather-viewport.ts`：天气视口防抖 / maxWait / immediate flush
- `stores/weather-tile-manager.ts` / `weather-tile-cache-trim.ts`：瓦片调度与 LRU trim
- `stores/weather-tile-concurrency.ts`：AIMD 并发（上限 6，对齐后端 semaphore / Open-Meteo API pool）

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
