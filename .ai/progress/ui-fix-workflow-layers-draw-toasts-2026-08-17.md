# UI 修复：工作流图层组织 / 多边形绘制 / 提示框统一（2026-08-17）

对应计划：`.trae/documents/工作流图层组织与绘制及提示框优化计划-2026-08-17.md`
模式：brooks-sweep 范围化（三任务模块），Safe/Extended-Safe 直接应用，无 Residual 遗留。

## 修复清单（全部完成）

### 任务1：工作流图层组织（C 档 = 前端 F1-F3 + 后端 F4）

| 项 | 文件 | 内容 |
|---|---|---|
| F1 | `Code/frontend/src/stores/layers/run-layers.ts` | `cleanupUnproducedRunLayers` 增加 `{ succeeded }` 选项：产物成员保留不加「（部分）」、组置 `ready`、空占位移除；接线于轮询终态（`workflow-poller.ts:363-368`）与恢复链已成功 run（`workflow-runner.ts:505-512`），均在 `attachAlgorithmProductOverlays` 完成后调用 |
| F2 | `Code/frontend/src/stores/layers/workflow-runner.ts` | `ensureRestoredRunGroup` 占位标签三级来源：已恢复成员真实标签 → manifest（`workflowDefinitionForRestore` 从 runtime 目录 descriptor 的 `workflow_definition` 解析，`explicitExpectedOutputTags` 取 `extra.outputs`/节点 `properties.main_layers`）→ 旧 run 回退 `SM/VOD/OMEGA` |
| F3 | `Code/frontend/src/stores/layers/run-layers.ts` | 游离兜底命名优先级：manifest 输出名 → 产品标签 → 工作流显示名 → 去前缀标题 → overlay id（技术名最后）；归组绑定优先级保持 |
| F4 | `Code/backend/app/data_io/services/raster_timeseries.py` | `stable_imported_layer_id` 哈希成分去 run_id，改 `layer_key`（workflow 语义维度）；`resolve_block_timeseries_layer_id` 传 `layer_key`，同 workflow 重复 run → 同 `imported-*` id → upsert 覆盖（时间窗替换语义） |

### 任务2：多边形绘制

| 项 | 文件 | 内容 |
|---|---|---|
| D1 | `Code/frontend/src/components/map/draw-module.ts` | 预览拆双线层：`draw-preview-path-layer`（已画折线整段实线 3px/0.9）+ `draw-preview`（末点→光标虚线 `[4,3]`）；矩形拖拽整框虚线预览保留 |
| D2 | `draw-toolbar.vue` / `ZonalStatsCard.vue` / `VectorAttributeTable.vue` | 未定义 CSS 变量（`--surface-elevated/--border/--surface/--hover/--text`）替换为已定义 token（`--surface-1/2`、`--border-default/subtle/strong`、`--surface-hover`、`--text-primary/secondary`）——工具栏背景恢复实底 |
| D3 | `map-canvas-runtime-watcher.ts` + `map-canvas-runtime-module.ts` + `map-canvas-module-bundle.ts` | 新增 `watchDrawState`（sync key：drawMode/features/vertices/isDrawing/selected，不含 hover 避免高频）；组装器接线 `getDrawSyncKey`/`onDrawStateChange` → `drawModule.syncFromStore()`——修复移除图层/清除/撤销后地图残留 |
| D4 | `Code/frontend/src/data-manager/adapters/export.ts` | 空预览导出报错文案改为明确指引（保存绘制图层后再导出）；不新增草稿直导（用户确认） |

### 任务3：提示框统一（中上、110px 基准、实底）

| 项 | 文件 | 内容 |
|---|---|---|
| T1 | `DataImportMenu.vue` | `import-toast`：`top:110px` 居中、背景 `--surface-1` 实底 + blur、z=`--z-loading-20`；error 变体同实底 |
| T2 | `LoadingOverlay.vue`（compact） | 顶栏细进度条下移至 96px（避开 24.8~90px 顶栏带） |
| T3 | `MapCanvas.styles.css` | 地图内 4 提示（tile-error/weather-*）保持 110px 基准（原有，作对齐基准不动） |
| T4 | `ServiceConnectivityBanner.vue` | z 硬编码 12000 → `--z-debug` token（仅 token 化，不改行为） |

## 验证结果（2026-08-17）

| 项 | 命令 | 结果 |
|---|---|---|
| V1 前端单测（draw 相关） | `npm run test -- draw-module runtime-watcher run-layers --run` | 87/87 ✓ |
| V1' workflow-runner（含 F2 新增 3 用例） | `npm run test -- workflow-runner --run` | 31/31 ✓ |
| V2 前端全量 | `npm run test -- --run` | 134 文件 952 测试 ✓ + 12 文件因 vitest forks worker 启动失败补跑 133/133 ✓（worker 错误为机器负载环境问题，非代码缺陷） |
| V3 lint | `npm run lint` | 0 error（2 既有 warning，`MultiOverlayBarChart.vue` 非本轮改动） |
| V4 build | `npm run build` | ✓ 5.11s |
| V5 check:catalog / check:openapi | `npm run check:catalog` / `check:openapi` | ✓ 52 items 同步 / 契约指纹一致 |
| V6 后端 | `pytest Test/backend/test_raster_timeseries_upsert.py Test/backend/test_import_raster_crs.py`（shim 禁用前缀 + `--basetemp=Test/.pytest-be`） | 18/18 ✓ |

### V7 浏览器实测（Gateway :5175，Playwright + Pinia 直读）

截图存 `.ai/progress/v7-screenshots/`：

1. **图层组织** ✓：侧栏 `method-smap-omega-doy-dynamic` 以图层组展示（「可拆分 · 3 层」），SM/VOD/ω 成员各有真实时间块（20251227_20251231），无空占位 chip。
2. **绘制中边显示** ✓：polygon 模式 4 顶点 + hoverPoint 注入后，`draw-preview-path-layer` 实线折线实时渲染（截图 `draw-edges-with-hover`），未闭合状态末端开放；线色 `#2b7fff` 3px。注：预览条件含 `hoverPoint`（真实鼠标操作恒满足；合成事件注入无 mousemove 时不可见，非缺陷）。
3. **工具栏背景** ✓：`draw-toolbar` computed `background: rgba(255,255,255,0.96)` 实底，非透明。
4. **移除后清除** ✓：移除绘制图层（confirm 防误删）→ 面板条目消失、draw-toolbar 消失、地图多边形完全清除（截图 `after-remove-check`），退出绘制模式。
5. **提示框位置** ✓：compact 进度条 top=96px（顶栏底 79px 之下）；`import-toast` CSS top=110px 居中 `--surface-1` 实底。

## 新增/修改测试

- `Test/frontend/components/map/draw-module.test.ts`（新增）：预览线渲染（path+cursor 分类）、store 清空同步、图层清理。
- `Test/frontend/components/map/map-canvas-runtime-watcher.test.ts`：新增 `watchDrawState` 用例（mapReady 门控 + key 变化触发）。
- `Test/frontend/components/map/map-canvas-runtime-module.test.ts`：补 draw 依赖注入与幂等/销毁断言。
- `Test/frontend/stores/layers/run-layers.test.ts`：新增 succeeded 清理两用例（空占位移除/产物不加「（部分）」；全空组移除）。
- `Test/frontend/stores/layers/workflow-runner.test.ts`：新增 `restoreActiveWorkflows` F2 三用例（manifest extra.outputs 优先 / nodes main_layers 回退 / 无 manifest 回退 SM-VOD-OMEGA），含 `createRunLayerGroup`/`bindRunIdToGroup` 真实写回 harness。
- `Test/backend/test_raster_timeseries_upsert.py`：`layer_key` 去重三用例（跨 run 同 id 覆盖、空 layer_key 回退 run_id 哈希、legacy id 兼容）。

## 遗留与说明

- vitest forks worker 启动失败（环境负载）：全量跑需补跑失败 worker 的文件集合；CI Ubuntu 不受影响。
- `--z-toast:100` 与实际 toast z 体系脱节：按计划记为 Residual 未动。
- 旧 `imported-{旧哈希}` 目录不迁移，仍可懒加载；新 run 起全部走 `layer_key` 维度 id。
- 提交：未自动 commit（sweep 惯例）；提交时按仓库硬约定 `git add -A` 全量暂存后一次提交。
