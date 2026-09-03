# Cesium / MapLibre 双引擎（实验）

> 活文档。默认 3D 仍为 **MapLibre globe**；Cesium 为设置开关下的实验路径。

## 选型与挂载

| 引擎 | 何时挂载 | 能力边界 |
|------|----------|----------|
| MapLibre globe | `enable3DView` 且 `globeRenderEngine=maplibre`（默认） | 主链：星空/太阳系背景、晨昏线、风场粒子/羽/流线、天气 GeoJSON |
| Cesium | `enable3DView` 且 `globeRenderEngine=cesium` 且 `viewMode=3d` | 实验：同源底图（`/unified-tiles`）、`/overlay-tiles` XYZ ImageryLayer、日夜光影、截图/缩放到图层、引擎互切视口桥；椭球底色浅蓝灰 `#9aa7b4` |

互斥：Dashboard 上 `showMapLibreCanvas` / `showCesiumHost` 不同时挂载。2D 模式始终 MapLibre。

设置入口：`AppearanceSettings` →「启用3D视图」下的渲染引擎分段控件；偏好落在 `cgda.settings_ui`（`settings-local.ts`）。

## 代码落点

```
Code/frontend/src/components/map/globe-engine/
  CesiumGlobeHost.vue          # 懒加载宿主
  view-bridge.ts               # MapLibre↔Cesium lng/lat/height 快照
  layer-extent.ts              # 共享图层 bounds 解析
  use-globe-render-engine.ts
  cesium/
    create-viewer.ts           # Viewer；勿传 skyAtmosphere:true
    basemap-adapter.ts
    overlay-tiles-adapter.ts   # 仅栅格 XYZ；跳过 weather-engine GeoJSON
    lighting.ts
    base-url.ts                # window.CESIUM_BASE_URL=/cesium/
```

构建：`vite-plugin-cesium` 把 Workers/Assets/Widgets 拷到 `dist/cesium/`；主库进 `vendor-cesium` chunk。

网关：`location ^~ /cesium/` → `try_files $uri =404`（禁止 SPA 回退成 HTML）。

## Gateway CSP（5175）

Vite 直连通常**无** CSP，故本地另开端口冒烟可能「能过」；同域 Gateway 必过 CSP。

`snippets/security-headers.conf` 的 `script-src` 需同时包含：

- `'wasm-unsafe-eval'` — `WebAssembly.compile` / `instantiate`（Cesium ThirdParty/Workers）
- `'unsafe-eval'` — Cesium Viewer 初始化中的 string-as-JS（`new Function` / `eval`）；**仅 wasm 不够**

改 CSP 后：`launch.py reload gateway`，浏览器硬刷新。冒烟页：`/cesium-smoke.html`（`public/`）。

## 已知不做（本阶段）

- 风场粒子 / 羽 / 流线 / 标量 WebGL CustomLayer 移植到 Cesium
- 太阳系背景在 Cesium 侧复刻
- `/weather/tiles` GeoJSON 管线（Cesium 仅 overlay PNG XYZ）

## 验证

### 自动化

- 单测：`Test/frontend/components/map/globe-engine-*.test.ts`、`globe-solar-system.test.ts`
- `cd Code/frontend && npm run build`（确认 lazy chunk + `dist/cesium/`）
- Gateway 基建冒烟：`http://localhost:5175/cesium-smoke.html`（CSP 关键字 + `/cesium/` 资源 + WASM instantiate；**不**在静态入口 `import('cesium')`）

### 手测清单（Dashboard）

| # | 步骤 | 期望 |
|---|------|------|
| 1 | 设置 → 外观 → 勾选启用 3D → 引擎选 Cesium → 顶栏 3D | 地球出现；banner 提示实验模式；无 CSP / listener 报错 |
| 2 | 工具栏「截图」导出 | 非黑屏；含地球与底图（`preserveDrawingBuffer` + render 后 toDataURL） |
| 3 | 侧栏对导入栅格「缩放到图层」 | Cesium `flyToBounds` 飞到包络 |
| 4 | 设置切回 MapLibre（仍 3D） | 视角大致连续（view-bridge）；风场粒子仍可用 |
| 5 | 再切 Cesium | 视角大致连续；overlay 栅格层若已打开应叠上 |
| 6 | MapLibre + 太阳系背景 | 太阳为柔和日冕，**无**中心橙红实心小圆 |
| 7 | 回 2D | MapLibre mercator；不强制套用 Cesium 高度跳变 |

说明：Vite 直连无 CSP 时「能过」、`:5175` 失败 → 先查 `security-headers.conf` 是否含 `'unsafe-eval'` + `'wasm-unsafe-eval'`，再 `launch.py reload gateway` 并硬刷新。
