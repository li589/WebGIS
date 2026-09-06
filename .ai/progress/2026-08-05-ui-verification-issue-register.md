# CGDA UI 功能验证问题登记表

> **日期**：2026-08-05（初验） / **2026-08-06 回归**  
> **入口**：`http://localhost:5175`（Vite）+ FastAPI `:8000`  
> **方法**：Chrome DevTools MCP（snapshot / network / console / 交互）  
> **范围**：初验复现 + 文档化；2026-08-06 全流程回归见 [`.ai/progress/2026-08-06-regression-report.md`](./2026-08-06-regression-report.md)

---

## 环境快照

| 组件 | 状态 |
|------|------|
| Redis / MinIO / Open-Meteo | running（2026-08-06 回归仍就绪） |
| FastAPI `:8000` | 就绪 |
| Frontend Vite `:5175` | 就绪 |
| Worker ×7 + Beat | 运行中 |
| Nginx Gateway | 未运行（日常 Vite 路径，预期） |

---

## 验证覆盖矩阵

| 模块 | 状态 | 判据 / 备注 |
|------|------|-------------|
| 首屏 / MapLibre | 已验·通过（2026-08-06） | 底图、工具栏、时间轴、比例尺正常；无红错 |
| 图层库 ↔ 已添加 | 已验·通过（2026-08-06） | 库分类可浏览；persist 非空属预期（ID09） |
| 天气瓦片 + 时间轴 | 已验·通过（2026-08-06） | `/weather/tiles/temperature/...` 200；banner「完整数据」 |
| 底图样式 / 源 | 已验（上轮） | 街道↔影像；高德→OSM |
| 点查 | 已验·通过 | 温度主值有 °C；叠加非天气层多为 N/A（ID06） |
| 测量 | 已验·通过（2026-08-06） | 模式可进；有「清除测量路径」 |
| 截图导出 | **已验·通过（2026-08-06）** | 导出成功（另存为或面板「⬇ 点击下载」）；无 `map.render` / `color()` 致命错（ID11） |
| 数据导出 GeoTIFF | 已验·通过（上轮）/ 本回归 PARTIAL | 上轮「已导出 1 个图层」；2026-08-06 工作台可开但无已导入层可导出 |
| 工作流编辑器 / 定时器 | 已验（上轮） | 范例、节点库、定时器空态；本回归未新建定时器 |
| 工作流状态面板 | 已验·通过（2026-08-06） | 可开；瓦片进度可见 |
| 设置各 Tab | 已验·通过（2026-08-06） | 打开/关闭无崩 |
| FY/SMAP 成功闭环 | 阻塞 | `smap_folder` 等数据源未就绪（ID05）；不阻塞回归交付 |
| 定时器新建 + Beat 触发 | 待验 | 本轮未新建定时器 |
| 侧栏右键「导出 PNG」路径 | 待验 | 数据工作台路径已通；右键菜单路径未点 |
| 相关 vitest | 已验·通过（2026-08-06） | 54/54（expose-bridge / screenshot / overlay-symbology / analysis-panel-summary / weather-tile*） |

---

## 问题清单

### ID01 — 失败 run 刷新后 materialize → 409 黄条

- **严重度**: P1 | **类别**: bug / ux  
- **现象**: 启动后控制台 `materializeWorkflowMapLayers failed run-… 409`；分析面板常驻黄条「工作流结果图层加载失败：… ExecutionStatus.failed」；状态钮「失败 3」。本轮复现 run：`run-099649fb32ce`、`run-f96c6543d011`。  
- **涉及组件**:
  - FE `Code/frontend/src/views/DashboardView.vue` → `restoreActiveWorkflows`
  - FE `Code/frontend/src/stores/layers/index.ts` → `attachAlgorithmProductOverlays` / `workflowError`
  - FE `Code/frontend/src/services/runtime-api.ts` → `materializeWorkflowMapLayers`
  - BE `Code/backend/app/api/routers/workflow_router.py` → `materialize_workflow_map_layers`（状态不在 `{succeeded,running,accepted,queued}` → 409）
- **初步分析**: 后端拒绝 failed 物化属正确防护。前端恢复/附加 overlay 时只要带 `runId` 仍会 POST materialize；409 写入 `workflowError` 且不自动清空，导致黄条常驻。应在 failed/cancelled 跳过 materialize，或将 409 降级为可 dismiss 提示。  
- **复现步骤**: `launch.py start` → 打开 `:5175` → 观察分析面板黄条与 console warn。  
- **证据**: console msgid 92/136；本轮 Chrome 会话。  
- **状态**: fixed（2026-08-05：hydrate 对 failed 跳过 progressive materialize；409 不写 workflowError）  
- **2026-08-06 回归**: PASS — 硬刷新后无「工作流结果图层加载失败」黄条、无 materialize 409 黄条噪音。

---

### ID02 — 僵尸排队标 failed：`workflow_orphaned_stale_queue`

- **严重度**: P2 | **类别**: ops / expected-with-noise  
- **现象**: 工作流状态面板中 ω 分块反演失败，文案含「排队超时且 Celery 侧已无对应任务」；`error_code=workflow_orphaned_stale_queue`。  
- **涉及组件**:
  - BE `Code/backend/app/services/workflow/follow_up_dispatch_service.py` → `cleanup_stale_workflow_runs`
  - BE `Code/backend/app/main.py` lifespan 启动调用
  - FE `Code/frontend/src/components/workflow/WorkflowStatusPanel.vue`
- **初步分析**: FastAPI 重启后，DB 中仍 `accepted|queued|retry_pending`、超 ~15 min 且 Celery 无活跃 task 的 run 被标 failed。属恢复机制；与 ID01 叠加放大 UI 噪音。`running` 应跳过（避免误杀）。  
- **复现步骤**: 查看状态面板失败条目 diagnostics / error_code。  
- **证据**: 上轮/本轮状态面板快照。  
- **状态**: confirmed  
- **2026-08-06 回归**: 本会话状态面板失败计数为 0；机制仍 confirmed，未升优。

---

### ID03 — InfoPanel Vue Duplicate keys（进度日志）

- **严重度**: P2 | **类别**: bug  
- **现象**: 控制台 `[Vue warn]: Duplicate keys … "日志 · chunk 12/32 · pixel … · step2_omega"`。本轮未再触发（无新的 omega 进度推送），上轮已确认。  
- **涉及组件**: `Code/frontend/src/components/InfoPanel.vue` — `jobEventNotes` 列表 `:key="note"`（约 1490–1492 行）；数据来自 `eventMessages` / `diagnosticNotes`。  
- **初步分析**: 以整段文案作 key；相同进度文案重复推入时冲突。同文件报告区已用 ``:key="\`note-${idx}\`"``。修复：改用 index / 稳定 id，可选去重。  
- **复现步骤**: 运行会产生重复 eventMessages 的分析工作流（如 omega 块进度）。  
- **证据**: 上轮 console msgid 19/34。  
- **状态**: fixed（2026-08-05：`:key="\`job-note-${idx}\`"`）  
- **2026-08-06 回归**: PASS（代码准）— 无 omega 进度推送故未现场复现 Duplicate keys；key 已改为 index。

---

### ID04 — 天气层状态文案与分析面板不一致 / 冷启动等待感

- **严重度**: P2 | **类别**: ux  
- **现象**:
  1. **上轮**：新加温度后 banner 长期「等待瓦片」，network 已有大量 tile 200（常为 `hour=0/1` 预取）；切到 00:00 即「完整数据」。
  2. **本轮**：persist 已有温度层；选中后 NOW 22:00 显示「完整数据 / 已加载」，`/weather/tiles/...&hour=22` 返回 200。但分析面板仍显示 `running` / 「加载中」，与 banner「完整数据」冲突。  
- **涉及组件**:
  - FE `Code/frontend/src/stores/weather-tile-manager.ts`
  - FE `Code/frontend/src/stores/layers/index.ts`（availabilityLabel「等待瓦片」/「完整数据」）
  - FE `Code/frontend/src/components/InfoPanel.vue`（天气层 stage：running/加载中）
  - BE `weather_tile_routes` / WeatherTileService  
- **初步分析**: 瓦片 API 本身可用。问题在 (a) 冷启动时当前小时与预取队列优先级/状态聚合；(b) InfoPanel 天气 stage 未与 tile manager「完整数据」对齐。  
- **复现步骤**: 清空后新加温度观察冷启动；或选中已缓存温度层对比 banner vs 分析面板文案。  
- **证据**: 本轮 snapshot（22:00 完整数据 + 分析面板 running）；上轮 hour 预取 network。  
- **状态**: fixed（2026-08-05：`weather-tile-readiness` 统一 banner/stage 谓词）  
- **2026-08-06 回归**: PASS — 温度 banner「完整数据」时分析 stage = `succeeded` /「已缓存」（非 `running`+「加载中」）。

---

### ID05 — 图层库大量「默认数据源未就绪」

- **严重度**: P3 | **类别**: env  
- **现象**: HFP/CLCD/DEM/NDVI/多数课题组层按钮禁用；ω 分块反演提示 `smap_folder、anc_root、ndvi_clim_folder` 未就绪；「数据未就绪」按钮 disabled。能见度 + `ecmwf_ifs025` 提示模型不提供变量。  
- **涉及组件**: 图层 catalog seeds / readiness（FE catalog + BE descriptors）；分析面板运行按钮。  
- **初步分析**: 本地资产/路径未挂载时的预期门禁，非 UI 崩溃。与功能缺陷分开排序。能见度缺口与项目约定一致（需 `gfs_global`）。  
- **复现步骤**: 图层库浏览「土地利用 / 地形 / 课题组数据」。  
- **证据**: 图层库 snapshot。  
- **状态**: expected（env）  
- **2026-08-06 回归**: 仍阻塞记档；不阻塞本次回归交付。

---

### ID06 — 点查：天气主值正常，叠加对比非天气层多为 N/A

- **严重度**: P3 | **类别**: ux / expected-partial  
- **现象**: 选中温度 + 点查模式点地图 → 主点查 **27.5 °C**（23.150, 113.241，模型 ecmwf_ifs025，含时序）。叠加对比「11 个共显层」中干旱指数/ω/SM/VOD/OMEGA 等多为 N/A。UI 显示 cache 标签 `miss`。  
- **涉及组件**: ModeToolbar 点查、MapCanvas、InfoPanel 点查/叠加对比、`getOverlayValue` / weather point API。  
- **初步分析**: 天气点查主链正常。N/A 来自未物化/失败/待运行 overlay 或时刻不匹配，属数据态而非点查引擎故障。`miss` 为缓存命中提示，易被误解为失败。  
- **复现步骤**: 选中温度 → 点查 → 点中国南部视口。  
- **证据**: 本轮 snapshot（27.5 °C + 时序）。  
- **状态**: confirmed（主链 pass；叠加 N/A expected-partial）

---

### ID07 — overlay-bounds 404（aridity-cn / omega-sf-fenkuai）

- **严重度**: P2 | **类别**: bug / data  
- **现象**: console `Failed to load resource: 404`；`[Overlay] bounds fetch failed for aridity-cn: 404`。  
- **网络**:
  - `GET /overlay-bounds/aridity-cn` → 404 `{"detail":"Overlay bounds file not found: aridity_overlay_bounds.json"}`
  - `GET /overlay-bounds/omega-sf-fenkuai` → 404 `{"detail":"No overlay for layer: omega-sf-fenkuai"}`  
- **涉及组件**: FE overlay bounds 拉取；BE overlay-bounds 路由；干旱指数 / ω 目录层与 persist 恢复层。  
- **初步分析**: persist/目录层触发 bounds 请求，但对应 bounds 文件或 overlay 注册缺失。应：缺失时静默降级（勿刷 404 error）、或补齐 bounds 资产 / 避免对无 overlay 的 catalog 层请求。  
- **复现步骤**: 刷新带 aridity / omega-sf-fenkuai 的已添加层工作区。  
- **证据**: network reqid 268/269；console msgid 48/54。  
- **状态**: fixed（2026-08-05：ensureMeta 仅对 `/overlays` 注册层请求；bounds 404 负缓存）  
- **2026-08-06 回归**: PASS（附注）— 全程无 `/overlay-bounds/omega-sf-fenkuai`；`aridity-cn` 同会话曾见 2×404（未刷屏），其后添加/刷新未见循环。

---

### ID08 — 导出点击被 map canvas 拦截（历史）

- **严重度**: P3 | **类别**: ux（历史残留）  
- **现象**: 旧文档记载自动化点「导出 PNG/GeoTIFF」偶发被 map 拦截。  
- **本轮复验**: 数据工作台 → 导出 → 选中 SM 栅格 → GeoTIFF →「开始导出」→ **成功**（「已导出 1 个图层 · 20251227_20251231」）。点击未被 canvas 吞掉。  
- **涉及组件**: `DataExportPanel.vue`、`LayerSidebar.vue` 右键导出、`MapCanvas.vue`。  
- **初步分析**: 数据工作台路径当前可用。侧栏右键「导出 PNG」路径本轮未测；历史拦截可能已缓解或仅限特定叠层。  
- **复现步骤**: 数据 → 导出 → 开始导出。  
- **证据**: 本轮 snapshot footer「已导出 1 个图层」。  
- **状态**: mitigated（数据工作台）；右键路径 needs_repro

---

### ID09 — workspace-persist 刷新后非空已添加列表

- **严重度**: P3 | **类别**: docs  
- **现象**: 刷新后「已添加」约 12 层（含历史导入/失败关联层），与旧清单「空态」预期不一致。  
- **涉及组件**: `Code/frontend/src/stores/layers/workspace-persist.ts`、layers store hydrate。  
- **初步分析**: 现行约定下 persist 恢复属预期；旧 `ui-verification-steps.md` 空态期望已过时。除非产品要求「失败层不恢复」，否则非 bug。  
- **复现步骤**: 刷新 `:5175`，看已添加计数。  
- **证据**: 本轮首屏「12 个图层」。  
- **状态**: expected（docs 对齐）

---

### ID10 — 分析面板天气 stage 卡在 running/加载中（与 banner 冲突）

- **严重度**: P2 | **类别**: ux  
- **现象**: 温度层 banner / 时间轴已是「完整数据」「已加载」，分析面板仍显示 `running` + 「加载中」+「暂无图表」。  
- **涉及组件**: `InfoPanel.vue` 天气图层区块；weather tile / workflow status 字段映射。  
- **初步分析**: 天气热路径不占 workflow 池，但 UI 仍用 workflow-like stage（running）。应改为 tile-ready / cached 等语义，或与 `availabilityLabel` 同源。与 ID04 相关，单独登记便于修文案。  
- **复现步骤**: 选中已完整加载的温度层，看分析面板。  
- **证据**: 本轮 snapshot。  
- **状态**: fixed（与 ID04 同源：`resolveWeatherWorkflowStage`）  
- **2026-08-06 回归**: PASS — 与 ID04 同验：完整数据 ↔ succeeded/已缓存 对齐。

---

### ID11 — 截图导出失败（map.render / CSS color）

- **严重度**: P1 | **类别**: bug  
- **现象**: 打开「截图」→ 点「导出」失败。控制台：
  1. `[MapCanvas] captureMapCanvas failed: TypeError: map.render is not a function`（`map-canvas-expose-bridge.ts:116`，由 `ScreenshotExport.vue:111` 调用）
  2. `[ScreenshotExport] Capture failed: Error: Attempting to parse an unsupported color function "color"`（`ScreenshotExport.vue:211`）  
- **涉及组件**:
  - `Code/frontend/src/components/map/map-canvas-expose-bridge.ts` → `captureMapCanvas`（强制调用 `map.render()`）
  - `Code/frontend/src/components/ScreenshotExport.vue` → `capture`
  - MapLibre 实例 API 与 html-to-image/色值解析路径  
- **初步分析**: (1) 当前 MapLibre/封装实例可能无同步 `render()`，或类型断言掩盖了真实 API（应改用 `triggerRepaint` / 等 idle / `preserveDrawingBuffer`）；(2) 外壳截图路径解析现代 CSS `color(...)` 失败。两条错误链均阻塞截图主功能。  
- **复现步骤**: 工具栏「截图」→「导出」。  
- **证据**: console msgid 1320/1321。  
- **状态**: fixed（2026-08-05：render 回调内 toDataURL；scrub `color()` for html2canvas；另存为 + 面板手动下载兜底）  
- **2026-08-06 回归**: PASS — 导出成功（已生成 + ⬇ 点击下载）；无 Capture failed / `map.render` / `color()` 致命错。截图覆盖矩阵改为已验·通过。

---

## 建议修复优先级（不在本阶段改代码）

| 优先 | ID | 理由 |
|------|-----|------|
| 1 | ID11 | 截图主功能直接失败，无环境依赖 |
| 2 | ID01 | 每次刷新常驻黄条+409 噪音 |
| 3 | ID03 | Vue warn，改 key 成本低 |
| 4 | ID07 | 明确 404 URL，可静默降级或补资产 |
| 5 | ID04 / ID10 | 天气状态文案一致性 |
| 6 | ID02 | 运维机制；可改进 failed run dismiss UX |
| 7 | ID06 / ID05 / ID09 | 预期或部分环境；文档/文案即可 |
| 8 | ID08 | 数据工作台已通；仅右键路径可选复验 |

---

## 附录：本轮关键证据路径

- 历史截图：`.ai/progress/ui-verify-home.png`、`ui-verify-temperature.png`、`ui-verify-final.png`
- 本轮关键网络：`/overlay-bounds/aridity-cn`、`/overlay-bounds/omega-sf-fenkuai`
- 本轮点查：温度 27.5 °C @ 23.150, 113.241
- 本轮导出：GeoTIFF SM（部分）`20251227_20251231` 成功
- **2026-08-06 回归报告**：[`.ai/progress/2026-08-06-regression-report.md`](./2026-08-06-regression-report.md)
- 2026-08-06 vitest：54/54（map-canvas-expose-bridge / screenshot-export / overlay-symbology / analysis-panel-summary / weather-tile-readiness / weather-tile / weather-tile-banner）
