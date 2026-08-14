# 工作流种子（Seed）命名与分类规范

> 权威约定：设计 / 新增 / 修改 `Code/backend/workflow_seeds/system/*.json` 或用户工作流 `_meta` 时遵循本文。
> AI 入口技能：`.ai/skills/workflow-design.md`。
> 实现加载：`Code/backend/app/services/workflow_definition_service.py`（`_build_meta` / `_ID_PATTERN`）。

## 1. 三套「分类」勿混用

| 体系 | 位置 | 用途 |
|------|------|------|
| **工作流种子** `_meta.category` / `_meta.tags` | `workflow_seeds` / 定义 JSON | 模板库分组、过滤、文档检索 |
| **节点调色板** 中文 category | 前端 LiteGraph 节点注册 | 画布左侧节点分组（与 seed 无关） |
| **图层 catalog** `category` / `tags` | 图层库 / 规范文档图层节 | 地图图层分类（与 seed 无关） |

本文只约束**工作流种子**。所谓「标记」= `_meta.tags` + `_meta` 标志位，**不**另造 `markers` 字段。

## 2. 标识与文件

- **`workflow_id` / 文件名**：`snake_case`，匹配 `^[a-zA-Z0-9][a-zA-Z0-9_\-]*$`，文件为 `{workflow_id}.json`。
- 示例：`omega_avg_daily_smap_single`、`weather_temperature_grid_demo`、`open_data_nsidc_smap_sample`。
- 禁止路径穿越字符、空格、中文 ID。

## 3. `_meta` 必填 / 推荐字段

| 字段 | 必填 | 取值 / 说明 |
|------|------|-------------|
| `kind` | 是 | `system` \| `user` |
| `engine` | 是 | `python_provider` \| `weather` \| `gee` \| `common` |
| `name` | 是 | 展示名（可中文） |
| `description` | 推荐 | 目的 / 前置 / 产出 / 关键配置 |
| `author` | 推荐 | `system` 或作者标识 |
| `readonly` | system 种子 | `true` |
| `is_template` | system 种子 | `true` |
| `linked_layer_id` | 推荐 | 关联图层 catalog id（定时器 / 状态 UI 可用） |
| `category` | 推荐 | 主分类（单选，见下） |
| `tags` | 推荐 | 多选标记（见下） |

## 4. `category`（主分类，单选）

允许值（与现网种子对齐）：

| 值 | 用途 |
|----|------|
| `inversion` | 反演主链（omega / sf 等） |
| `weather` | 天气引擎相关模板 |
| `data_access` | 开放数据下载 / 转换样例 |
| `analysis` | 统计分析 / 直方图 / 分区等分析流 |
| `demo` | 纯演示（一般更推荐把 `demo` 放在 **tags**，category 用业务类） |

## 5. `tags`（标记，多选）

现有词汇（新增须先改本文再改 seed）：

`pipeline` · `omega_avg` · `omega_block` · `sf_inversion` · `d1` · `demo` · `sample` · `download` · `local` · `gldas_online` · `weather` · `analysis` · `statistics` · `histogram` · `timeseries` · `chart` · `raster` · `zonal` · `preprocess` · `gis` · `fusion` · `report` · `stub_v1` · `ui-panel` · `buffer`

约定：

- `pipeline`：多节点主链路模板。
- `demo` / `sample`：演示或样例，不作为生产默认定时任务。
- `local` / `*_online`：数据来源暗示。
- 算法族用稳定前缀（`omega_*`、`sf_*`）。
- `stub_v1`：2026-08 新启用的预处理 / GIS / 统计 / 融合样例种子。
- `preprocess` / `gis` / `fusion` / `report`：功能域标记（可与 `analysis` category 并存）。
- `ui-panel`：InfoPanel 分析面板固化模板（`analysis_*.json`），勿强制 `pipeline`。
- `buffer`：缓冲分析相关。
### `_meta.resource_profile`（可选）

| 值 | 说明 |
|----|------|
| `standard` | 默认；走 analysis/algorithm standard 队列槽 |
| `heavy` | 大栅格 warp / 插值 / 流域等；提交时写入 `WorkflowSubmitRequest.resource_profile` |

未写时：提交路径可按图中重模块（`preprocess_reproject` 等）自动升为 `heavy`。

## 6. 引擎与定时器提交

定时器触发时后端按 `_meta.engine` 注入提交体（见 `workflow_timer_service._build_submit_payload`）：

- `python_provider` / `common` → `algorithm_request.workflow_name` + `workflow_definition`
- `weather` → `weather_request`
- `gee` → `gee_request`

`payload_overrides` 可覆盖参数；空 overrides 时仍应能靠定义体提交，勿依赖已废弃的 `extra.default_*`  alone。

## 7. Celery / 产物元数据

- `WorkflowResultReference.title` 与 `create_artifact_result_ref(title=...)` **仅 US-ASCII 英文**（见 `project-conventions.md`）。
- 中文展示名放 `_meta.name` / UI copy，不进 Celery 元数据 title。

## 8. 检查清单（改 seed 前）

1. `workflow_id` 合法且与文件名一致。
2. `_meta.engine` / `category` / `tags` 在允许表内。
3. system 种子含 `readonly` + `is_template`。
4. 有合理 `linked_layer_id`（若有对应图层）。
5. 描述写清前置数据与产出路径约定。
6. 若新增 tag/category，先更新本文与 `.ai/skills/workflow-design.md`。
