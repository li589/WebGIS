# 图层平台结构化框架与统一工作流

## 当前已完成

- 静态图层已纳入统一资产工作流：`POST /overlay-asset-workflows/{layer_id}`。
- 工作流先检查烘焙资产和 `bake_version`，fresh 立即 succeeded，stale/missing 由 Celery 后台烘焙。
- 大数据源不进入交互直读：GEBCO 等重资产只通过后台烘焙/资产接口显示。
- 前端添加目录图层统一走 `runWorkflowForCatalog`，分析图层走分析工作流，静态 overlay 自动分流到资产工作流。
- ERA5 多波段瓦片波段链已修复：DWAA/WDAA 统一使用 `source_band=183`。
- 深浅主题视觉系统已 token 化，双主题对比度回归通过。

## 新框架

已新增 `Docs/03-架构设计/图层平台结构化框架-2026-08-24.md`，定义：

- LayerDescriptor / LayerAsset / LayerLifecycle / WorkflowRun / RenderBinding / DataSource 六类领域对象。
- 图层接入分类：analysis、asset、weather、online、imported、maintenance。
- 工作流分类：analysis、asset_bake、online_sync、ingest、download、weather_viewport、maintenance。
- 大数据硬规则：交互请求不读大源；大数据必须走烘焙、金字塔、瓦片或 COG；更新必须 bump bake_version。
- 在线数据流程：在线源同步 → 版本快照 → 资产烘焙 → 地图刷新 → 时间轴更新。
- 课题组工作流一键显示契约：模板化参数 → run → result_refs → materialize-map-layers → 自动上图/时间轴同步。

## 当前系统到框架的映射

已具备：

- 统一 run 状态模型。
- 资产工作流入口。
- `bake_version` 资产版本。
- 大数据交互保护。
- 删除运行中图层时取消 run 并防回弹。

待补强：

1. run 显式写入 `workflow_kind`。
2. 增加 `GET /layer-assets/{layer_id}`。
3. 增加 `GET /layers/{layer_id}/lifecycle`。
4. 渲染几何元数据显式化，逐步替代宽高启发式。
5. 时间轴读取 lifecycle，显示 fresh/stale/updating。
6. 在线源接入统一为 sync job + asset workflow。

## 最新提交

- `ed0ad3c feat(layers): 统一图层资产工作流与烘焙调度`
- 已推送 `dev`
- MATLAB 原始算法目录继续保留，未纳入本轮。
