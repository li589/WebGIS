# CGDA 实施计划：图层工作流配置与分析面板图表优化

## 摘要

本计划针对 CGDA 系统的两大核心领域进行系统性改进：(1) 修复图层与工作流之间的连接差距，为缺失工作流的 `python_provider` 图层补建 seed 并修复双向链接；(2) 统一分析面板的图表渲染技术栈，修复数据流缺陷（`numericValue` 丢失、24h 截断、硬编码演示点），按量纲和时间轴类型分离多图层图表，合并冗余显示区块。

## 现状分析

### 图层-工作流连接差距

| 指标 | 数量 | 占比 |
|------|------|------|
| 图层总数 | 55 | 100% |
| 有 workflow_id 的图层 | 4 | 7.3% |
| 完全无 workflow 连接的图层 | 48 | 87.3% |
| Workflow seed 总数 | 43 | 100% |
| 有 linked_layer_id 的 seed | 12 | 27.9% |

**关键差距：**
- 3 个 `python_provider` 图层缺失工作流连接：`ndvi`、`ref-smap-sm-202512-l3`、`ref-fy-tb-202512-mwri`
- `ref-smap-sm-202512-l3` 被 2 个 seed 单向引用但图层无 `workflow_id`
- 无交叉校验机制，链接断裂无法自动发现
- 9 个 `smap-aux-*` 辅助图层和 31 个 `overlay_registry` 图层按设计不需要工作流

### 分析面板图表问题

**数据流缺陷：**
- `pointWeatherHourlyChartRows` 丢弃 `numericValue`，导致 SVG 图表依赖正则回退解析
- 24 小时天气数据被截断为 8 小时（`.slice(0, Math.max(8, activeHour + 1))`）
- 硬编码演示点 `(11.25, 19.7623)`（非洲坐标，与系统默认范围无关）
- `useOverlayData` 与 `useUnifiedChartData` 逻辑高度重叠

**渲染缺陷：**
- 两套并行图表系统：`PointTimeSeriesChart`（SVG 手绘，无坐标轴刻度）vs `MultiLayerTimeSeriesChart`（ECharts）
- `MultiOverlayBarChart` 无 tooltip 交互
- 量纲混搭：温度(°C)、风速(m/s)、降水(mm)、NDVI 在同一图表中对比
- 时间轴异构：天气逐小时 vs 栅格 8 天块混在同一 X 轴
- 区块冗余：统一分析 + 叠加对比 + 点时间序列三区块内容重叠
- 矢量数据分类空实现
- 图表中无单独序列开关

## 实施方案

### 阶段 A：后端图层-工作流链接修复（P0/P1）

#### A1. 修复 `ref-smap-sm-202512-l3` 双向链接 [P0]

**文件：** `Code/backend/app/catalog_seeds/layer_descriptors.json`

**改动：** 在 `ref-smap-sm-202512-l3` 图层描述符中添加 `workflow_id` 和 `workflow_name` 字段，指向 `smap_soil_moisture_local` seed。

**原因：** 该图层 `engine` 为 `python_provider`，已有 2 个 seed 通过 `linked_layer_id` 指向它，但图层缺少反向链接。`workflow_request_resolver.py` 使用 `descriptor.workflow_name` 查找 seed 并提取 `algorithm_params`，缺失时回退到 `module_name` 但不会读取 seed 中的 `algorithm_params`。

**具体改动：**
```json
{
  "layer_id": "ref-smap-sm-202512-l3",
  "module_name": "smap_daily",
  "engine": "python_provider",
  "workflow_name": "smap_soil_moisture_local",
  "workflow_id": "smap_soil_moisture_local",
  "default_task_type": "smap_daily"
}
```

选择 `smap_soil_moisture_local`（本地数据读取链路）而非 `open_data_nsidc_smap_sample`（开放数据下载样例）作为主工作流，因为本地运行场景更常用。

#### A2. 为 `ref-fy-tb-202512-mwri` 创建工作流 seed [P1]

**新建文件：** `Code/backend/workflow_seeds/system/fy_tb_local_read.json`

**原因：** 该图层 `engine` 为 `python_provider`，`module_name` 为 `fy_daily`，`default_data_access_sources` 指向 `FY_MWRI_HDF` 数据集，但无对应工作流 seed。

**seed 设计：**
- `_meta.engine`: `"python_provider"`
- `_meta.linked_layer_id`: `"ref-fy-tb-202512-mwri"`
- `_meta.category`: `"data_access"`
- 节点：`data/source`（FY MWRI HDF 路径）→ `extract/variable`（亮温变量提取）→ `format/convert`（转 .mat）
- 参照 `smap_soil_moisture_local.json` 的结构

**同时在 `layer_descriptors.json` 中为该图层添加：**
```json
"workflow_name": "fy_tb_local_read",
"workflow_id": "fy_tb_local_read"
```

#### A3. 为 `ndvi` 图层创建工作流 seed [P1]

**新建文件：** `Code/backend/workflow_seeds/system/ndvi_local_read.json`

**原因：** `ndvi` 图层 `engine` 为 `python_provider`，`module_name` 为 `ndvi_daily`，但无工作流 seed。

**seed 设计：**
- `_meta.engine`: `"python_provider"`
- `_meta.linked_layer_id`: `"ndvi"`
- `_meta.category`: `"data_access"`
- 节点：`data/source`（NDVI 路径）→ `module/ndvi_daily`（算法模块）→ `output/map_layer`
- `module/ndvi_daily` 节点的 `properties.algorithm_params` 需与 `ndvi_daily` 模块签名匹配

**同时在 `layer_descriptors.json` 中为 `ndvi` 添加：**
```json
"workflow_name": "ndvi_local_read",
"workflow_id": "ndvi_local_read"
```

#### A4. 标注天气 demo seed 的单向链接 [P2]

**文件：** `Code/backend/workflow_seeds/system/weather_temperature_grid_demo.json`、`weather_wind_field_demo.json`

**改动：** 在 `_meta` 中添加 `notes` 字段说明这是演示用链接，天气图层主路径为 tile 服务，不设置图层 `workflow_id`。

**原因：** 天气图层走 tile 主路径，不占 workflow 池（项目约束）。`linked_layer_id` 用于编辑器联调，不应移除，但需明确标注为单向引用。

#### A5. 添加图层-工作流交叉校验机制 [P2]

**新建文件：** `Code/backend/app/services/layer_workflow_validator.py`

**设计：**
```python
def validate_layer_workflow_links() -> list[ValidationIssue]:
    """交叉校验图层描述符与工作流 seed 的双向链接一致性。
    检查项：
    1. python_provider 图层有 workflow_name 时，对应 seed 必须存在
    2. seed 有 linked_layer_id 时，对应图层必须存在
    3. python_provider 图层无 workflow_name 时，记录 warning
    4. overlay_registry 图层不应有 workflow_id
    5. 天气图层（source_type=weather）不应有 workflow_id
    """
```

**新建测试文件：** `Test/backend/test_layer_workflow_validation.py`

测试用例：
1. 所有 `python_provider` 图层的 `workflow_name` 对应的 seed 存在
2. 所有 seed 的 `linked_layer_id` 对应的图层存在
3. 天气图层无 `workflow_id`
4. `overlay_registry` 图层无 `workflow_id`

---

### 阶段 B：前端图表数据流修复（P0/P1）

#### B1. 修复 `numericValue` 丢失 [P0]

**文件：** `Code/frontend/src/components/info-panel/useWeatherPointData.ts`

**改动：** 修改 `pointWeatherHourlyChartRows` 和 `pointWeatherHourlyRows`，在映射时保留/计算 `numericValue`。

**原因：** 当前 `pointWeatherHourlyChartRows` 丢弃 `numericValue`，导致 `PointTimeSeriesChart` 依赖正则 `parseFloat(item.metric.replace(/[^0-9.-]+/g, ''))` 回退解析，精度和可靠性差。

**具体改动：**
```typescript
// pointWeatherHourlyRows 中添加 numericValue
const pointWeatherHourlyRows = computed(() => {
  return (weather.hourly ?? [])
    .map((entry, index) => {
      const metricValue = /* 现有计算逻辑 */
      return {
        time: formatHour(entry.time),
        metric: formatMetric(metricValue, pointWeatherMetric.value.unit),
        numericValue: metricValue,  // 新增
        active: index === activeHour,
      }
    })
})

// pointWeatherHourlyChartRows 传递 numericValue
const pointWeatherHourlyChartRows = computed(() => {
  return pointWeatherHourlyRows.value.map((row) => ({
    time: row.time,
    metric: row.metric,
    numericValue: row.numericValue,  // 新增
    active: row.active,
  }))
})
```

**同步修改：** `InfoPanelVisualTab.vue` 的 props 类型定义，将 `pointWeatherHourlyChartRows` 类型添加 `numericValue?: number`。

#### B2. 修复 24 小时数据截断 [P0]

**文件：** `Code/frontend/src/components/info-panel/useWeatherPointData.ts`

**改动：** 移除 `.slice(0, Math.max(8, activeHour + 1))` 截断逻辑。

**原因：** 该 slice 将小时数据截断为最多 8 条，天气 API 返回的 `hourly` 数组通常含 24 小时数据，截断导致时序图只能看到 1/3 的数据。

**具体改动：**
```typescript
// 移除 slice，显示全部小时数据
return (weather.hourly ?? [])
  .map((entry, index) => { ... })
  .filter((entry) => entry.metric !== `-- ${pointWeatherMetric.value.unit}`.trim())
```

#### B3. 移除硬编码演示点 [P1]

**文件：** `Code/frontend/src/views/dashboard/useMapInspect.ts`

**改动：**
1. `queryDefaultOverlaySeries` 函数中改为使用图层 `extent` 的中心点
2. watcher 移除 `immediate: true`，改为仅在已有选点时触发

**原因：** 硬编码坐标 `(11.25, 19.7623)` 对应非洲地区，与系统默认范围（中国南方）无关。

**具体改动：**
```typescript
function queryDefaultOverlaySeries() {
  const extent = displayLayer.value?.extent
  if (extent) {
    const lng = (extent.west + extent.east) / 2
    const lat = (extent.south + extent.north) / 2
    emit('queryOverlaySeries', { lng, lat })
  }
}

// watcher 移除 immediate
watch(
  () => selectedLayerDisplay.value?.importedRasterOverlayLayerId,
  (overlayId) => {
    if (!overlayId || selectedMapPoint.value) return
  },
  // 移除 { immediate: true }
)
```

#### B4. 合并 `useOverlayData` 与 `useUnifiedChartData` 重复逻辑 [P2]

**文件：** `Code/frontend/src/components/info-panel/useUnifiedChartData.ts`、`useOverlayData.ts`

**改动：** 将 `useOverlayData` 中与 `useUnifiedChartData` 重复的栅格图层信息构建逻辑提取为共享内部函数，`useOverlayData` 调用 `useUnifiedChartData` 的计算结果。

**原因：** 两个 composable 都遍历 `overlayTimeStates` + `activeLayersDisplay` 构建栅格图层信息，逻辑高度重叠但实现略有差异，容易产生不一致。

---

### 阶段 C：图表渲染统一化（P1）

#### C1. 用 ECharts 替换 SVG 手绘图表 [P1]

**文件：** `Code/frontend/src/components/info-panel/InfoPanelVisualTab.vue`

**改动：** 在 `InfoPanelVisualTab.vue` 中用 `MultiLayerTimeSeriesChart` 替代 `PointTimeSeriesChart` 的所有使用点，将 `hourlyRows` 转换为 `MultiLayerSeries` 格式。

**原因：** `PointTimeSeriesChart`（SVG 手绘）无坐标轴刻度、固定 320x120 不可缩放、无 tooltip 交互、无图例、无 dataZoom。`MultiLayerTimeSeriesChart`（ECharts）已有完整基础设施。

**具体方案：**
1. 天气点查时序（第 289-293 行）和 overlay 点时序（第 337-342 行）用 `MultiLayerTimeSeriesChart` 替换
2. 数据转换：`hourlyRows` → `[{ id, name, data: hourlyRows.map(r => ({ time: r.time, value: r.numericValue ?? null })) }]`
3. 保留 `PointTimeSeriesChart.vue` 文件但不再使用（避免破坏其他潜在引用）

#### C2. 为 `MultiOverlayBarChart` 添加 tooltip 交互 [P2]

**文件：** `Code/frontend/src/components/info-panel/MultiOverlayBarChart.vue`

**改动：** 将 CSS 柱状图改为 ECharts 横向柱状图，支持 tooltip。

**原因：** 当前纯 CSS 实现无 hover 反馈，数值只能通过文本读取。

**方案：** 复用 ECharts 注册模式，`series.type: 'bar'`，`yAxis.type: 'category'`（横向），`tooltip.trigger: 'item'`。保持 props 接口 `OverlayBarItem[]` 不变。

#### C3. 增强 `MultiLayerTimeSeriesChart` legend 交互 [P2]

**文件：** `Code/frontend/src/components/info-panel/MultiLayerTimeSeriesChart.vue`

**改动：** 确保 legend 可见且可点击切换序列显示。

**具体改动：**
- `legend.selectedMode: true`
- `legend.icon: 'circle'` 增强视觉辨识
- 添加 `legend.textStyle.color` 明确可点击样式

---

### 阶段 D：量纲与时间轴分离（P3）

#### D1. 量纲感知的图表分组 [P3]

**文件：** `Code/frontend/src/components/info-panel/useUnifiedChartData.ts`、`InfoPanelVisualTab.vue`

**改动：** 新增 `unitGroups` 计算属性，按 `unit` 分组。组合模式中不再将所有图层放入一个图表，而是按 `unitGroups` 渲染多个图表。

**原因：** 温度(°C)、风速(m/s)、降水(mm)、NDVI 在同一图表中对比无物理意义，数值范围差异大导致小值序列不可见。

**具体方案：**
1. `useUnifiedChartData.ts` 新增 `unitGroups: computed<Record<string, { unit: string; series: MultiLayerSeries[]; pointValues: UnifiedPointValue[] }>>`
2. `InfoPanelVisualTab.vue` 组合模式 section 改为 `v-for="group in unitGroups"` 渲染多个图表
3. 每个图表标题包含单位（如"温度类图层时序 (°C)"）

#### D2. 时间轴类型分离 [P3]

**文件：** `Code/frontend/src/components/info-panel/useUnifiedChartData.ts`、`InfoPanelVisualTab.vue`

**改动：** 将天气逐小时时序与栅格 8 天块时序分离到不同的图表中。

**原因：** 天气时间标签为 `HH:00`，栅格为 `MM-DD → MM-DD`，混在同一 X 轴导致排序混乱。

**具体方案：**
1. `allTimeSeries` 拆分为 `hourlyTimeSeries`（天气）和 `blockTimeSeries`（栅格）
2. 组合模式分别渲染"逐小时时序"和"时间块时序"两个图表

---

### 阶段 E：布局整合与交互优化（P2/P3）

#### E1. 合并冗余图表区块 [P2]

**文件：** `Code/frontend/src/components/info-panel/InfoPanelVisualTab.vue`

**改动：** 移除独立的 `overlay-compare` section 和 `overlay-point-series` section，合并到 `unified-layer-analysis` section 中。

**原因：** 三个 section 内容重叠：统一分析已包含"点值对比"和"时间序列对比"，叠加对比又单独渲染柱状图，点时间序列又单独渲染时序图。

**具体方案：**
1. 移除独立的 `overlay-compare` section（其数据已被统一分析覆盖）
2. 将 `overlay-point-series` 的时序合并到统一分析的"时间序列对比"中
3. 当仅有 1 个可见图层时，自动切到单序列视图
4. 保留 `point-weather` section（天气点查有独特的元数据行）

#### E2. 矢量数据分类实现 [P3]

**文件：** `Code/frontend/src/components/info-panel/useUnifiedChartData.ts`

**改动：** 识别矢量图层（`render_type === 'vector'` 或 `'point'`）并归入 `vector` 类别。

**原因：** 当前 `pointValuesByCategory.vector` 和 `timeSeriesByCategory.vector` 始终为空数组，系统中存在矢量图层但完全缺失。

#### E3. 优化 `fetchAllOverlaySeries` 性能 [P3]

**文件：** `Code/frontend/src/views/dashboard/useMapInspect.ts`

**改动：** 添加并发限制池，限制同时 in-flight 的请求数（建议 `MAX_CONCURRENT = 8`）。

**原因：** 一个时序图层可能有 30+ 时间块，所有图层所有时间块同时请求可能过多。

---

### 阶段 F：测试与验证（贯穿全程）

#### F1. 后端测试

**新建测试文件：** `Test/backend/test_layer_workflow_validation.py`

**运行命令：**
```
CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_layer_workflow_validation.py Test/backend/test_catalog_placeholder_filter.py -p no:cacheprovider --basetemp="Test/.pytest-be"
```

#### F2. 前端测试

**新建测试文件：**
- `Test/frontend/components/info-panel/use-weather-point-data.test.ts`
- `Test/frontend/components/info-panel/use-unified-chart-data.test.ts`

**运行命令：**
```
cd Code/frontend && npm run test && npm run lint && npm run build
```

#### F3. 集成验证

按 AGENTS.md "改X则跑Y" 映射：
1. 图层目录改动：`pytest Test/backend/test_data_source_paths.py Test/backend/test_data_root_policy.py -q`，然后 `python launch.py start fastapi` 后 `GET /layers` 验证 `workflow_id`
2. 前端改动：`npm run test && npm run lint && npm run build`，然后 `python launch.py start gateway --rebuild-frontend` 浏览器验证
3. 契约检查：`npm run check:catalog && npm run check:openapi`
4. 工作流编译：`pytest Test/backend/test_workflow_graph_compiler.py -q`

## 假设与决策

### 关键决策

| 决策 | 选择 | 理由 | 成本变更 |
|------|------|------|---------|
| `ref-smap-sm` 主工作流 | `smap_soil_moisture_local` | 本地读取链路比开放数据下载更常用 | 改 `linked_layer_id` 即可切换 |
| `PointTimeSeriesChart` 处理方式 | 在使用点替换为 `MultiLayerTimeSeriesChart`，保留文件 | 减少维护负担，保持回退能力 | 恢复 SVG 实现即可 |
| `MultiOverlayBarChart` 改造 | 改用 ECharts | 与时间序列图技术栈一致 | 恢复 CSS 实现即可 |
| 天气 demo seed 处理 | 保留 `linked_layer_id` + 添加 notes | 天气走 tile 路径，seed 用于编辑器联调 | 移除 notes 字段 |
| 量纲分组方式 | 按 `unit` 字段分组 | 物理量纲不同不应在同一坐标轴对比 | 修改 `unitGroups` 逻辑 |
| 硬编码演示点处理 | 改用图层 extent 中心点 | 保持自动加载功能但使用合理坐标 | 恢复硬编码即可 |

### 假设

1. `ndvi_daily` 和 `fy_daily` 模块的 `algorithm_params` 签名可通过 `template_deriver.py` 的 `list_module_templates()` 推导
2. 天气 API 返回的 `hourly` 数组包含完整 24 小时数据
3. 图层描述符中的 `extent` 字段在大部分 `overlay_registry` 图层中存在
4. 前端 ECharts 按需引入的模块（LineChart/BarChart/Grid/Tooltip/Legend/DataZoom）已足够支持新需求

## 改动文件汇总

### 后端（阶段 A）

| 文件 | 操作 | 阶段 |
|------|------|------|
| `Code/backend/app/catalog_seeds/layer_descriptors.json` | 修改 | A1, A2, A3 |
| `Code/backend/workflow_seeds/system/fy_tb_local_read.json` | 新建 | A2 |
| `Code/backend/workflow_seeds/system/ndvi_local_read.json` | 新建 | A3 |
| `Code/backend/workflow_seeds/system/weather_temperature_grid_demo.json` | 修改 | A4 |
| `Code/backend/workflow_seeds/system/weather_wind_field_demo.json` | 修改 | A4 |
| `Code/backend/app/services/layer_workflow_validator.py` | 新建 | A5 |
| `Test/backend/test_layer_workflow_validation.py` | 新建 | F1 |

### 前端（阶段 B-E）

| 文件 | 操作 | 阶段 |
|------|------|------|
| `Code/frontend/src/components/info-panel/useWeatherPointData.ts` | 修改 | B1, B2 |
| `Code/frontend/src/views/dashboard/useMapInspect.ts` | 修改 | B3, E3 |
| `Code/frontend/src/components/info-panel/useUnifiedChartData.ts` | 修改 | B4, D1, D2, E2 |
| `Code/frontend/src/components/info-panel/useOverlayData.ts` | 修改 | B4 |
| `Code/frontend/src/components/info-panel/InfoPanelVisualTab.vue` | 修改 | C1, D1, D2, E1 |
| `Code/frontend/src/components/info-panel/MultiOverlayBarChart.vue` | 修改 | C2 |
| `Code/frontend/src/components/info-panel/MultiLayerTimeSeriesChart.vue` | 修改 | C3 |
| `Code/frontend/src/components/InfoPanel.vue` | 修改 | D1, D2 |
| `Test/frontend/components/info-panel/use-weather-point-data.test.ts` | 新建 | F2 |
| `Test/frontend/components/info-panel/use-unified-chart-data.test.ts` | 新建 | F2 |

## 执行顺序

```
阶段 A（后端）与阶段 B-E（前端）可并行执行。

A1 → A2 → A3 → A4 → A5 → F1

B1 → B2 → B3 → B4 → C1 → C2 → C3 → D1 → D2 → E1 → E2 → E3 → F2 → F3
```

### 优先级分组

| 优先级 | 任务 | 理由 |
|--------|------|------|
| P0（阻断性） | A1, B1, B2 | 修复数据丢失和功能断裂 |
| P1（核心功能） | A2, A3, B3, C1, E1 | 新增缺失工作流、统一图表渲染、消除冗余布局 |
| P2（健壮性） | A4, A5, B4, C2, C3 | 校验机制、代码清理、交互增强 |
| P3（优化） | D1, D2, E2, E3 | 量纲分离、矢量分类、性能优化 |

## 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 新增 seed 的 `algorithm_params` 与模块签名不匹配 | 参照 `template_deriver.py` 推导签名，运行 `pytest Test/backend/test_workflow_graph_compiler.py -q` |
| ECharts 替换 SVG 导致回归 | 保持 props 接口不变，保留 `PointTimeSeriesChart` 文件作回退，新增前端测试覆盖 |
| 移除硬编码演示点影响演示流程 | 改用图层 `extent` 中心点，确保 `extent` 存在时才触发 |
| 量纲分组后图表数量过多 | 同单位仅 1 个图层时不显示分组标题；单位种类超过 3 个时默认切分类模式 |

## 提交规范

遵循 Conventional Commits：
- 阶段 A：`fix(catalog): repair layer-workflow bidirectional links and add missing seeds`
- 阶段 B：`fix(info-panel): fix numericValue loss and 24h truncation in weather point data`
- 阶段 C：`refactor(info-panel): unify chart rendering with ECharts`
- 阶段 D：`feat(info-panel): separate charts by unit and time axis type`
- 阶段 E：`refactor(info-panel): consolidate redundant chart sections and add vector category`

每个阶段完成后执行 `pre-commit run --all-files`。
