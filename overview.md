# 图层平台子系统 P1 完成

## 本轮交付（三个 commit，已推送 dev）

### 1. `e04a950` — 双写真源 + 侧栏徽标 + online_sync 统一入口
- **lifecycle 真源接通**：lifecycle 域自持 `mapOverlayTimeStates` ref，MapCanvas sync 模块经 `onOverlayTimeStatesChanged` 双写（`setMapOverlayTimeStates`），废弃 bindings 空 stub
- **侧栏生命周期徽标**：图层卡片显示 fresh/stale/updating/missing/failed，复用 TimelineScrubber 同款样式
- **POST /layer-assets/{layer_id}/sync**：`workflow_kind=online_sync` 统一入口
  - 未启用 online_temporal → `skipped-unsupported`（200，不报错）
  - 同图层活跃 online_sync run → `in-flight` 复用（不重复提交）
  - `time_key` YYYY-MM / YYYY-MM-DD 自动解析为 time_range
  - prefetch/low 优先级走 batch 队列

### 2. `dc19964` — 课题组工作流模板一键显示入口
- **GET /workflows/templates**：聚合 workflow_seeds/system + workflow_definitions/user 中 `is_template=true` 或 tags 含 template/lab 的定义
- **POST /workflows/templates/{id}/runs**：按模板定义构建 WorkflowSubmitRequest（`workflow_kind=lab_template`），支持 parameters/time_range/resource_profile/auto_display 覆盖
- 系统种子（analysis_buffer 等）已有 `is_template` 标记，入口直接可用

### 3. 契约链闭环
- 新增契约：LayerOnlineSyncRequest/Response、WorkflowTemplateSummary/ListResponse/RunRequest/RunResponse
- export_openapi（206 paths）→ gen:types → api-reexports → check:openapi 全部通过

## 验证

| 检查 | 结果 |
|---|---|
| 后端接口测试 | 12 + 12 全绿 |
| 前端 vitest | 1330 测试全绿 |
| type-check | 0 error |
| build | 通过 |
| check:openapi | 206 paths 通过 |
| 冒烟 | templates 返回模板列表；sync 对未启用图层返回 skipped-unsupported |

## 后端已重启生效

新接口立即可用：
- `GET /layer-assets/{layer_id}`（P0）
- `GET /layers/{layer_id}/lifecycle`（P0）
- `POST /layer-assets/{layer_id}/sync`（P1）
- `GET /workflows/templates`（P1）
- `POST /workflows/templates/{id}/runs`（P1）

## 后续 P2 建议

1. 前端课题组面板 UI（模板列表 + 一键运行按钮 + 完成后自动上图轮询链）
2. online_sync 前端编排器接入新接口（替换现有直接 runWorkflowForCatalog 路径）
3. 在线源凭证管理（GEE 账号池 / 门户凭证统一）
4. 大数据 COG/瓦片服务接入新图层类型

## P2 完成情况（2026-08-25）

四项全部落地：P2-1 模板面板（LayerSidebarTemplates + 自动上图轮询链）、
P2-2 编排器接入统一 online_sync 入口（三分支语义映射 + 自动回退）、
P2-3 统一在线源凭证状态（GET /config/online-sources，四源聚合只报布尔）、
P2-4 direct 源图层（COG/GeoTIFF 免烘焙直通动态瓦片）。

### 子系统职责边界（COG/瓦片服务架构归位，2026-08-25）

| 职责 | 归属 | 落点 |
| --- | --- | --- |
| COG/瓦片服务**接入**（源文件入库、direct 源形态判定、bounds/元数据生成） | 数据源管理子系统 | `app/data_io/services/direct_source.py`（`find_direct_source` 单一真源 + `register_direct_geotiff` 接入 API） |
| 图层的**显示、渲染、加载**（注册表、瓦片渲染、前端 image/raster 模式切换） | 图层平台子系统 | `app/services/overlay_registry.py`（lazy-load 委托 data_io 判定）、`overlay_tile_service.py`、前端 `overlay-image-module.ts` |
| 分析调用编排 | 图层平台子系统 | workflow bridge 链 + 编排器（见 P2-2） |

依赖方向：`data_io.direct_source → overlay_registry`（注册，与 raster_register 同向）；
`overlay_registry → data_io.direct_source` 仅函数内延迟 import（委托判定，规避循环）。

direct 源接入方式：`register_direct_geotiff(src_path, layer_id=..., palette=...)`
（Python API），或手工在 `IMPORTS_DIR/imported-<id>/` 放 `source.tif/.cog` +
`bounds.json`（lazy-load 自动识别）。
