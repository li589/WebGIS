# Frontend

`Code/frontend/` 是本项目的前端工程根目录，当前已经是一个可运行的 `Vue 3 + TypeScript + Vite` 应用。它承担 WebGIS 的统一展示壳层，负责地图模式切换、图层管理、时间控制、任务入口和结果展示。

## 当前前端定位

当前前端的目标不是单纯做一个地图页面，而是组织一个能够统一承载多类地理分析任务的交互界面：

- `2D / 3D` 模式切换
- 图层面板与图层可见性控制
- 时间轴与时空范围控制
- 任务提交与结果回显
- 地图内容、状态面板与信息展示的统一组织

## 当前技术栈

- `Vue 3`
- `TypeScript`
- `Vite`
- `Pinia`
- `vue-router`
- 现有页面结构与组件化组织

## 关键目录与文件

- `src/main.ts`：应用入口，挂载 Vue、Pinia 和路由
- `src/App.vue`：最外层壳子，负责路由出口
- `src/app/router.ts`：页面路由配置
- `src/views/DashboardView.vue`：主页面视图，组织整体布局
- `src/stores/ui.ts`：全局 UI 状态，管理模式、图层和时间等信息
- `src/stores/layers/`：图层目录与图层状态
- `src/components/`：工具栏、侧栏、地图区、时间轴、信息面板等组件
- `src/services/runtime-api.ts`：与后端运行时 API 的交互封装
- `src/styles/main.css`：全局样式

## 当前界面补充说明

- `FloatingPanelFrame.vue` 负责图层/分析/时间轴等浮动面板的拖动、折叠、隐藏与复位
- `InfoPanel.vue` 当前承担“全图态势 + 调度器任务状态 + 选中图层/热点/结果”分段展示
- `TimelineScrubber.vue` 是独立时间轴组件，不应被浮动面板缩放逻辑影响
- `MapCanvas.vue` 负责地图底图、控件样式、热点同步，以及天气图层渲染

## 当前地图与天气渲染事实

`MapCanvas.vue` 已经从基础地图容器演进为前端地图渲染总入口，当前至少承担以下职责：

- 底图 source/layer 管理
- hotspot 同步与点击
- weatherengine 图层叠加
- 风场 canvas 覆盖层调度
- COG preview 栅格叠加

当前天气图层语义不是“单图层切换”，而是：

- `grid_fill` 图层可多图层并行叠加
- `point_symbol` 图层按各自 source/layer 独立渲染
- `particle_flow` 图层同一时刻只允许一个启用，由 `particleFlowCatalogId` 控制

前端当前还会把地图上下文写入图层状态：

- `currentMapCenter`
- `currentMapBBox`

这两个状态会进入 workflow 提交参数，影响天气图层产物范围与默认取样区域。

## 当前天气相关前端模块

天气渲染不再只靠一个组件，而是由一组组件和 helper 协作完成：

- `src/components/MapCanvas.vue`：统一调度 GeoJSON、preview raster 和 canvas overlay
- `src/components/InfoPanel.vue`：展示天气摘要、图例、图层元数据和可见图层摘要
- `src/components/map/weather-render.ts`：统一 `render_hint` 到地图颜色、透明度、图例 stops 的映射
- `src/components/map/wind-particle-canvas.ts`：风粒子流动画层
- `src/components/map/wind-barb-layer.ts`：风羽图层
- `src/components/map/wind-contour-layer.ts`：风速等值线图层
- `src/stores/layers/result-adapter.ts`：解析 `map_layer.payload.render_hint` 与 `layer_assets`
- `src/stores/layers/index.ts`：图层状态、workflow 提交、粒子流独占开关和地图视口状态

## 当前前端对后端天气契约的消费方式

前端当前稳定消费的天气结果字段包括：

- `render_hint`
- `point_feature`
- `layer_assets.geojson_url`
- `layer_assets.cog_preview_url`
- `layer_assets.cog_bbox`

其中：

- `render_hint` 统一驱动地图样式、图例和透明度
- `cog_preview_url + cog_bbox` 用于 MapLibre `image source + raster layer` 叠加
- `geojson_url` 作为 preview raster 不可用时的回退方案

## 当前页面结构理解

前端可以按“壳层 + 页面 + 组件 + 状态 + 服务”来理解：

### 壳层
`App.vue` 和 `main.ts` 负责把应用启动起来。

### 页面层
`DashboardView.vue` 负责组织主页面布局，是当前前端最重要的页面容器。

### 组件层
`ModeToolbar.vue`、`LayerSidebar.vue`、`MapCanvas.vue`、`TimelineScrubber.vue`、`InfoPanel.vue` 等组件分别承担交互、图层、地图、时间和信息展示职责。

### 状态层
`stores/` 负责保存 UI 状态、图层状态和页面共享状态。

### 服务层
`services/runtime-api.ts` 负责对接后端运行接口，不把后端调用逻辑散落在组件中。

## 前端运行链路

前端当前的典型工作方式是：

1. 应用启动
2. 加载全局状态和基础路由
3. 进入 Dashboard 主页面
4. 通过组件组合展示地图、侧栏、时间轴和信息面板
5. 用户切换模式、图层或时间范围
6. 调用 runtime API 提交或查询任务
7. 根据后端返回结果更新界面

## 前端与后端的关系

前端只负责交互和展示，不直接承载复杂算法逻辑。所有涉及任务执行、状态管理、结果读取和工作流查询的能力，都通过后端 API 完成。

当前前后端已经形成更明确的双通道消费方式：

- 控制流接口：用于任务状态、事件、取消、重试与运行态查询
- 数据流接口：用于结果视图、artifact 访问和展示数据获取

因此前端与后端的关系可以概括为：

- 前端负责“怎么展示”和“怎么操作”
- 后端负责“怎么执行”和“怎么回传”
- 共享协议负责“双方如何理解同一份数据”
- 结果视图接口负责“前端如何稳定消费后端结果”

## 推荐阅读顺序

如果你在接手前端，建议按以下顺序阅读：

1. `Code/frontend/README.md`
2. `Code/shared/contracts/README.md`
3. `Code/backend/README.md`
4. `Code/algorithms/providers/Python/README.md`

## 说明

- 当前前端已经进入真实工程阶段，不再是空骨架
- 文档应优先服务于当前实际组件、状态与服务结构
- 后续如果继续扩展地图引擎或图层能力，应优先保持交互层与服务层分离
