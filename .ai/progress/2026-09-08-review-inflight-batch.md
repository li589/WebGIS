# 2026-09-08 — 在飞批次代码审查（5b4c33f6 之后未推送 + 工作区）

## 范围

- 已提交未推送：`fd60753a..HEAD`（agent overlay 点查 / 绘制草稿 / 面板 UX / 管道时间记忆 / 阶段消息人话化 + 审查修复）
- 工作区 29 文件：转换→反演执行序 mat 依赖端口、绘制交互修复、统计卡片显示名/拖拽、种子补 map_layer 输出

## 结论

**无 P0/P1 阻断。** 关键正确性全部实证通过（seed 编译、端口解析、目录归属、测试全绿、ruff 绿）。

## P2（提交前必改）

- **prettier 门禁**：4 个工作区文件未过 `prettier --check` —— `stat-layer-display-name.ts`、`ZonalStatsCard.vue`、`map-canvas-non-weather-layer-sync-module.ts`、`port-tooltip.ts`。提交前 `prettier --write`，否则 pre-commit/CI 失败。

## P3（可留痕/可选）

1. `stat-layer-display-name.looksLikeLayerId` 泛化 snake_case 正则把 `Soil_Moisture` 判为 id（测试已固化）——未命中活动层映射的后端名如 `Brightness_Temperature` 会显示成「未命名图层」。建议保留前缀白名单、去泛化正则或未知回退 layer_name。
2. `pipeline-time-memory` 文档 vs 实现：docstring 写「最近一次成功提交」，实现是点击确认（无论成败）即覆盖。失败 run 也污染下次预填。建议 run 成功后写，或改文档。
3. `getDrawSyncKey` 几何摘要仅哈希外环长度：带内环要素仅改内环不触发重同步（当前草稿要素无内环，风险低）。
4. 完成要素退出绘制态后双渲染：`omitCompletedFeatures` 只在「绘制态且未落点」时省略 draw 层要素；退出 draw 模式后 draw fill/line 与 imported 草稿层同显。历史遗留，可把 omit 条件扩到「存在草稿层即省略」。
5. canvas `renderPlacedPath` 与 MapLibre preview `path` 层重复绘制同一段已放置折线（同色叠加）。二者择一。
6. `fy_tb_local_read.json` map_layer 节点 `colormap/rescale` 参数后端无消费方（模板仅 layer_id/display_name），死配置。
7. `displayNameByOverlayId` 现无条件 `map.set(catalogId,label)`（去掉 `!map.has`）：同 catalogId 多活动层后者覆盖，可误标。建议保留保护。
8. `isAssetOnlyWorkflowRun` 按 kind 整体豁免 attach——若 asset 类 run 未来兼产地图图层会被误跳（当前无此场景）。

## 实证证据

- seed 编译：5 个 online 种子 `data:mat` 依赖边全部正确解析；GLDAS 种子 `下载 path→转换 data` 直连成立；`fy_tb_local_read`/`smap_soil_moisture_local` map_layer 边成立。
- 新 layer_id（`ref-fy-tb-202512-mwri`、`ref-smap-sm-202512-l3`）BE `layer_descriptors.json` + FE `catalog-seeds.generated.json` 均已注册。
- 端口契约：`value→data` 跨 kind 不严格校验（validation.py 仅查端口名存在性），与既有 `path→data` 模式一致；新 mat 输入端口 `required=False` 不触发 required-not-bound。
- 测试实测：backend `test_workflow_graph_compiler` 11 ✓；`test_node_template_compile_coverage`+`test_module_phase_classification`+`test_omega_avg_algorithm`+`test_omega_avg_daily_module`+`test_agent_chat` 73 ✓；前端 draw/draw-store/humanize/stat-layer/pipeline-memory 40 ✓；run-layers/workspace-persist/agent-chat-helpers/workflow-status/info-panel 147 ✓；ruff 改动算法模块 ✓。
- prettier：4 文件未过（见 P2）。
