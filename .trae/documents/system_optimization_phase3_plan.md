# 系统细节优化 Phase 3 实施计划

> **范围**：基于上一轮已完成的 44 模板 + 端口类型系统 + 基础 UI 框架，本轮聚焦于：(1) 新增 GIS 基础工具模块；(2) 全部算法文件合规性改造；(3) 数据流兼容性修复；(4) UI 四个方向增强。

## 当前状态分析

### 模块清单（44个，按引擎/分类）
- 通用: 5（data/source, data/time_range, data/bbox, output/map_layer, output/file）
- 数据预处理: 5（preprocess/*，全部 stub）
- 统计分析: 5（stats/*，全部 stub）
- 数据融合: 2（fusion/*，全部 stub）
- 可视化: 3（viz/*，全部 stub）
- 天气引擎: 11（weather/*）
- Python Provider: 9（module/*，已实现）
- GEE: 4（gee/*）

### 已发现的问题
1. **`inversion_daily.json` 断裂连接**：node 1 输出 `data`，但 node 3 期望 `data:mat`；node 2 输出 `data`，但 node 3 无 `time_range` 输入端口
2. **`inversion_daily` 节点本身**：缺少 `time_range` 输入端口，无法过滤时间范围
3. **`physics.py` 合规性问题**：20+ magic constants（Mironov 介电模型系数）、缺少量纲注释、缺少 soil_moisture/clay_fraction 边界检查
4. **`omega.py` 合规性问题**：`OmegaConfig.alpha0 = 0.1771` 与 `inversion.py._POLARIZATION_MIXING_Q = 0.1771` 重复定义；多个函数缺 docstring（`_resolve_payload_vector` 等）；`make_date_blocks` 使用硬编码 `"%Y%m%d"` 格式
5. **`block_inversion.py` 合规性问题**：`_broadcast_matrix`、`_as_time_pixel_matrix`、`_as_static_vector` 无量纲注释；`execute_block_inversion` 缺少 docstring
6. **`ndvi.py` 合规性问题**：`sg_polyorder=6`、`sg_window_length=9` 是 magic constants；`process_ndvi_stack_to_daily` 的 `gap_threshold_days=30` 与 `vi_sg_interpolate` 默认值不一致（30 vs 16，与节点模板 `gap_threshold_days` 默认 16 矛盾）
7. **`station.py` 合规性问题**：`quality_flag != 1` 是 magic constant；`max_depth_cm / 100.0` 转换缺量纲注释
8. **`fy.py` 合规性问题**：大量字符串拼接命令、缺少错误处理、函数缺少 docstring；`-te -17367530.45 -7314540.83 17367530.45 7314540.83` 是 EPSG:6933 全球范围 magic numbers
9. **UI 缺失**：节点库无引擎过滤、无收藏夹；参数编辑器无分组、无默认值对比；无示例工作流模板；画布节点缺引擎颜色边框

### 端口类型系统（已建立）
```
data              通用数据流（向后兼容）
data:mat          .mat 文件
data:raster       栅格数据
data:geojson      GeoJSON 矢量数据
data:timeseries   时间序列 .mat
data:source       数据源引用
value:number      数值
value:string      字符串
value:time_range  时间范围
geometry:bbox     空间范围
```

---

## 实施方案

### 阶段 1：新增 GIS 基础工具模块（9个新模块）

**文件**：`Code/backend/app/services/node_template_registry.py`

新增 9 个 GIS 节点模板（追加到 `_NODE_TEMPLATES` 末尾，GEE 节点之前）：

| type | category | 输入 | 输出 | 关键参数 |
|------|----------|------|------|----------|
| `gis/buffer_analysis` | GIS工具 | points(data:geojson), distance(value:number) | buffer(data:geojson) | distance_unit(enum: meters/kilometers/degrees) |
| `gis/zonal_statistics` | GIS工具 | raster(data:raster), zones(data:geojson) | stats(data:geojson) | statistic(enum: mean/median/sum/min/max/count), band(number) |
| `gis/raster_calculator` | GIS工具 | a(data:raster), b(data:raster, optional) | result(data:raster) | expression(string), nodata_handling(enum: propagate/zero/ignore) |
| `gis/vector_to_raster` | GIS工具 | vector(data:geojson), bbox(geometry:bbox) | raster(data:raster) | attribute_field(string), resolution(number, unit 米), dtype(enum: float32/int32/uint8) |
| `gis/raster_to_vector` | GIS工具 | raster(data:raster) | vector(data:geojson) | band(number), threshold(number), simplify_tolerance(number, unit 米) |
| `gis/reclassify` | GIS工具 | raster(data:raster) | raster(data:raster) | remap_table(string, 逗号分隔如 "0-30:1,30-60:2,60-100:3"), nodata_value(number) |
| `gis/contour` | GIS工具 | raster(data:raster) | contours(data:geojson) | interval(number), band(number), smoothing(boolean) |
| `gis/slope_aspect` | GIS工具 | dem(data:raster) | slope(data:raster), aspect(data:raster) | z_unit(enum: meters/feet), algorithm(enum: horn/zevenbergen) |
| `gis/watershed` | GIS工具 | dem(data:raster), pour_points(data:geojson) | watershed(data:geojson) | fill_threshold(number), flow_direction(enum: d8/dinf) |

**同时更新**：
- `Code/backend/app/services/python_provider_bridge_service.py`：将 9 个新模块加入 `_PENDING_IMPLEMENTATION_MODULES` frozenset

### 阶段 2：算法合规性改造（6个文件）

#### 2.1 `Code/algorithms/providers/Python/algorithms/physics.py`

**Magic constants 提取**（添加到文件顶部）：
```python
# 真空介电常数 (F/m)
_VACUUM_PERMITTIVITY = 8.854e-12
# 高频水介电常数（无量纲）
_WATER_HIGH_FREQ_DIELECTRIC = 4.9
# Mironov 2017 介电模型系数（无量纲）
_MIRONOV_COEFF_A0 = 1.634
_MIRONOV_COEFF_A1 = -0.539
_MIRONOV_COEFF_A2 = 0.2748
_MIRONOV_COEFF_B0 = 0.03952
_MIRONOV_COEFF_B1 = -0.04038
_MIRONOV_COEFF_XMVT0 = 0.02863
_MIRONOV_COEFF_XMVT1 = 0.30673
# Mironov 束缚水介电模型系数
_MIRONOV_BOUND_WATER_EPS_INF_A0 = 79.8
_MIRONOV_BOUND_WATER_EPS_INF_A1 = -85.4
_MIRONOV_BOUND_WATER_EPS_INF_A2 = 32.7
_MIRONOV_BOUND_WATER_TAU_A0 = 1.062e-11
_MIRONOV_BOUND_WATER_TAU_A1 = 3.450e-12
_MIRONOV_BOUND_WATER_SIGMA_A0 = 0.3112
_MIRONOV_BOUND_WATER_SIGMA_A1 = 0.467
# Mironov 自由水介电模型系数
_MIRONOV_FREE_WATER_EPS_INF = 100.0
_MIRONOV_FREE_WATER_TAU = 8.5e-12
_MIRONOV_FREE_WATER_SIGMA_A0 = 0.3631
_MIRONOV_FREE_WATER_SIGMA_A1 = 1.217
# NDVI-VWC 经验公式系数（Jackson 1999）
_VWC_NDVI_COEFF_A = 1.9134
_VWC_NDVI_COEFF_B = -0.3215
# 物理量阈值
_VWC_MAX_VALID = 30.0      # m³/m³
_TAU_MAX_VALID = 5.0       # 无量纲
_LANDCOVER_WATER = 0
_LANDCOVER_CROP = 10
_LANDCOVER_GRASS = 12
```

**改造内容**：
- `build_mironov_context`：用命名常量替换所有 magic numbers；添加 `freq_ghz` 范围检查（`0.1 <= freq_ghz <= 40`）
- `vwc_from_ndvi`：用 `_VWC_NDVI_COEFF_A/B` 替换 `1.9134`/`-0.3215`；用 `_LANDCOVER_*` 替换 `0`/`10`/`12`；用 `_VWC_MAX_VALID` 替换 `30`
- `tau_from_ndvi`：用 `_TAU_MAX_VALID` 替换 `5`
- 为所有公开函数添加量纲注释 docstring
- 为 `_fresnel_reflectance_kernel_py`、`_mironov_dielectric_kernel_py` 添加 docstring

#### 2.2 `Code/algorithms/providers/Python/algorithms/omega.py`

**改造内容**：
- `OmegaConfig.alpha0` 默认值 `0.1771` 改为引用 `inversion._POLARIZATION_MIXING_Q`（共享常量）；或在 omega.py 顶部 import 并复用
- 为所有公开函数添加 docstring（量纲注释）：`_rough_reflectance`、`_build_tb_forward_context`、`tb_forward_single_temp`、`tb_forward_dual_temp`、`make_date_blocks`、`pick_lcurve_corner`、`qc_block_jacobian_cond`、`retrieve_omega_pixel_timeseries`、`execute_omega_retrieval`
- 为私有辅助函数添加简短 docstring：`_resolve_payload_vector`、`_resolve_fixed_omega_vector`、`_resolve_exp0_calib_vectors`、`_build_empty_exp2_info`、`_coerce_timeseries_matrix`、`_require_timeseries_shape`
- `make_date_blocks` 添加日期格式常量 `_DATE_KEY_FORMAT = "%Y%m%d"` 并在 docstring 中说明
- `qc_block_jacobian_cond` 拆分内部逻辑为更小辅助函数（可选，仅添加注释说明三段：omega 列、tau 列、h 列）

#### 2.3 `Code/algorithms/providers/Python/algorithms/block_inversion.py`

**改造内容**：
- 为 `BlockFieldConfig`、`build_block_field_config`、`normalize_date_keys`、`_broadcast_matrix`、`_as_time_pixel_matrix`、`_as_static_vector`、`load_h_matrix`、`execute_block_inversion` 添加 docstring（含量纲注释）
- `execute_block_inversion` 添加 `freq_ghz` 范围检查（与 inversion.py 一致）
- `_broadcast_matrix`/`_as_time_pixel_matrix` 在 docstring 中说明输入/输出形状约定（nt × npix）

#### 2.4 `Code/algorithms/providers/Python/algorithms/ndvi.py`

**改造内容**：
- 提取 magic constants：
  ```python
  _SG_DEFAULT_POLYORDER = 6
  _SG_DEFAULT_WINDOW_LENGTH = 9
  _NDVI_VALID_MIN = 0.0
  _NDVI_VALID_MAX = 1.0
  ```
- 修复 `process_ndvi_stack_to_daily` 默认值 `gap_threshold_days=30` 与 `vi_sg_interpolate` 默认值 `30` 不一致问题：统一为 30（与节点模板 `gap_threshold_days` 默认 16 矛盾，需同时更新节点模板默认值为 30 或将算法默认值改为 16）。**决策**：将节点模板 `gap_threshold_days` 默认值从 16 改为 30，与算法默认值对齐
- `vi_sg_interpolate`、`process_ndvi_stack_to_daily` 添加 docstring（量纲：NDVI 无量纲 0-1，days 单位天）
- `build_datetime_sequence`、`to_day_numbers`、`_linear_interp_with_nan` 添加简短 docstring

#### 2.5 `Code/algorithms/providers/Python/algorithms/station.py`

**改造内容**：
- 提取 magic constants：
  ```python
  _STATION_QUALITY_GOOD = 1
  _M_TO_CM_FACTOR = 100.0
  ```
- `filter_station_records`、`aggregate_station_records_daily`、`build_site_time_series_matrix` 添加 docstring（量纲：soil_moisture 单位 m³/m³，depth 单位 m，lat/lon 单位度）
- `filter_station_records` 中 `record.soil_moisture != record.soil_moisture` NaN 检查改为 `math.isnan()` 更清晰

#### 2.6 `Code/algorithms/providers/Python/algorithms/fy.py`

**改造内容**：
- 提取 EPSG:6933 全球范围常量：
  ```python
  # EPSG:6933 投影全球范围（m）
  _EPSG6933_GLOBAL_WEST = -17367530.45
  _EPSG6933_GLOBAL_SOUTH = -7314540.83
  _EPSG6933_GLOBAL_EAST = 17367530.45
  _EPSG6933_GLOBAL_NORTH = 7314540.83
  _EPSG6933_GLOBAL_WIDTH_PX = 3856
  _EPSG6933_GLOBAL_HEIGHT_PX = 1624
  ```
- 为 `FyDatasetProfile`、`FyCommandStep`、`FY3D_PROFILE`、`FY3B_PROFILE`、`get_fy_profile`、`resolve_gdal_bins`、`hdf_sds_uri`、`build_geoloc_metadata_block`、`build_fy_daily_command_steps`、`get_fy_daily_multiband_output_path`、`write_fy_command_plan_json` 添加 docstring
- `build_fy_daily_command_steps` 中 `-te` 参数替换为命名常量
- `resolve_gdal_bins` 添加返回值说明 docstring

### 阶段 3：数据流兼容性修复

#### 3.1 修复 `Code/backend/.data/workflow_definitions/system/inversion_daily.json`

**问题**：
- node 1 (data/source) 输出 `data`，但 node 3 (module/inversion_daily) 期望 `data:mat`
- node 2 (data/time_range) 输出 `data`，但 node 3 无 time_range 输入端口
- node 3 输出 `data`，但 node 4 期望 `data`

**修复**：
- node 1 输出类型 `data` → `data:source`
- node 2 输出类型 `data` → `value:time_range`
- node 3 输入新增 `time_range` 端口；`input_mat` 类型 `data` → `data:mat`
- node 3 输出 `data` → `data:mat`
- node 4 输入 `data` 保持（output/map_layer 接受通用 data）
- links 修正：
  - `[1, 1, 0, 3, 0, "data:source"]`（data/source → input_mat）
  - `[2, 2, 0, 3, 1, "value:time_range"]`（time_range → time_range）
  - `[3, 3, 0, 4, 0, "data:mat"]`（inversion_mat → output）

#### 3.2 更新 `Code/backend/app/services/node_template_registry.py` 中 `module/inversion_daily` 节点

**当前**：
```python
"inputs": [
    _port("input_mat", "data:mat", description="daily_bundle 输出的 .mat 文件"),
],
```

**改为**：
```python
"inputs": [
    _port("input_mat", "data:mat", description="daily_bundle 输出的 .mat 文件"),
    _port("time_range", "value:time_range", required=False, description="时间范围（可选，用于过滤）"),
],
```

#### 3.3 检查并修复其他系统工作流 JSON

检查 `block_inversion.json`、`omega_block.json`、`weather_wind_field.json` 是否存在类似的端口类型不匹配问题。如有，按相同模式修复。

### 阶段 4：UI 优化（4个方向）

#### 4.1 节点库增强

**文件**：`Code/frontend/src/components/workflow/WorkflowNodePalette.vue`

**改造内容**：
1. **引擎过滤标签栏**：在搜索框下方添加 5 个引擎过滤标签（全部/通用/天气/Python/GEE），点击切换显示
2. **引擎颜色标识**：每个节点项左侧添加 4px 宽的引擎颜色条（通用=灰、天气=橙、Python=绿、GEE=蓝、输出=青）
3. **收藏夹**：节点项右侧添加 ☆/★ 切换按钮；新增"收藏"分类组置顶显示；收藏列表持久化到 localStorage
4. **最近使用**：新增"最近使用"分类组置顶显示（保留最近 10 个使用的节点类型），持久化到 localStorage
5. 在 `addNode` emit 时同时记录到最近使用列表

**新增常量**：
```typescript
const ENGINE_COLORS: Record<string, string> = {
  common: '#6e8ba0',
  weather: '#ffb84d',
  python_provider: '#78ffa0',
  gee: '#5ad5ff',
}
const ENGINE_LABELS: Record<string, string> = {
  common: '通用',
  weather: '天气',
  python_provider: 'Python',
  gee: 'GEE',
}
```

#### 4.2 参数编辑增强

**文件**：`Code/frontend/src/components/workflow/WorkflowInspector.vue`

**改造内容**：
1. **参数分组**：按 `param.group` 字段（新增可选字段）分组渲染；无 group 的归入"通用"组
2. **默认值对比**：每个参数右侧显示"默认: {defaultValue}"小字（如果当前值与默认值不同，高亮显示）
3. **复杂数组编辑器**：`array` 类型参数改为列表编辑器（添加/删除项按钮），每项单独输入；保留逗号分隔文本作为快速输入
4. **依赖参数联动**：参数可声明 `depends_on`（如 `power` 依赖 `method=idw`）；当依赖条件不满足时参数禁用并灰显
5. **参数说明 tooltip**：参数 label 旁加 ⓘ 图标，hover 显示完整 description

**实现**：在 `node_template_registry.py` 的 `_param` 函数新增可选 `group` 和 `depends_on` 参数；前端 `NodeTemplate` 类型扩展对应字段。

#### 4.3 工作流模板

**新增文件**：
- `Code/backend/.data/workflow_definitions/templates/smap_full_pipeline.json`：SMAP 完整反演流程（data/source → smap_daily → daily_bundle → inversion_daily → output/map_layer）
- `Code/backend/.data/workflow_definitions/templates/ndvi_sm_correlation.json`：NDVI 与土壤湿度相关性分析（module/ndvi_daily → module/inversion_daily → stats/correlation → viz/chart_generate）
- `Code/backend/.data/workflow_definitions/templates/weather_analysis.json`：天气分析（weather/forecast_fetch → weather/wind_field_render + weather/temperature_render → output/map_layer）

每个模板包含 4-6 个节点，演示典型数据流，标记为 `"readonly": false` 允许用户基于模板修改。

**前端**：在 `WorkflowEditorPanel.vue` 左侧栏添加"模板"分区，与"系统预设"分区并列。

#### 4.4 画布交互优化

**文件**：`Code/frontend/src/components/workflow/WorkflowCanvas.vue` 和 `litegraph-setup.ts`

**改造内容**：
1. **节点引擎颜色边框**：在 `litegraph-setup.ts` 的 `WorkflowNode` 构造函数中，根据 `engine` 字段设置 `this.bgcolor`（节点背景色）和 `this.color`（标题栏色）：
   ```typescript
   const engineColors: Record<string, { bg: string; header: string }> = {
     common: { bg: 'rgba(40, 50, 65, 0.9)', header: '#6e8ba0' },
     weather: { bg: 'rgba(65, 50, 40, 0.9)', header: '#ffb84d' },
     python_provider: { bg: 'rgba(40, 65, 50, 0.9)', header: '#78ffa0' },
     gee: { bg: 'rgba(40, 55, 65, 0.9)', header: '#5ad5ff' },
   }
   ```
2. **连接线类型颜色**：在 `litegraph-setup.ts` 中通过 `LGraphCanvas.default_link_color` 或重写 `drawLinks`，根据 link 的 type 字段着色（复用 `getPortColor`）
3. **对齐辅助线**：在 `WorkflowCanvas.vue` 的拖拽逻辑中，检测附近节点边缘，显示对齐辅助线（CSS 实现，通过 canvas overlay div）
4. **迷你地图**：在画布右下角添加迷你地图组件，显示所有节点的缩略位置，点击跳转

**实现优先级**：1 和 2 必须实现；3 和 4 可根据复杂度选择性实现（如果时间允许）。

### 阶段 5：后端 stub 注册新增模块

**文件**：`Code/backend/app/services/python_provider_bridge_service.py`

在 `_PENDING_IMPLEMENTATION_MODULES` frozenset 中追加 9 个新 GIS 模块名：
```python
_PENDING_IMPLEMENTATION_MODULES = frozenset({
    # 现有 15 个...
    "preprocess_reproject", "preprocess_resample", ...
    # 新增 9 个 GIS 模块
    "gis_buffer_analysis", "gis_zonal_statistics", "gis_raster_calculator",
    "gis_vector_to_raster", "gis_raster_to_vector", "gis_reclassify",
    "gis_contour", "gis_slope_aspect", "gis_watershed",
})
```

### 阶段 6：验证

1. **前端类型检查**：`npx vue-tsc --noEmit`（在 `Code/frontend/` 目录下）
2. **Python 编译检查**：对所有修改的算法文件执行 `python -m py_compile`
3. **JSON 校验**：验证所有修改的工作流 JSON 文件结构正确
4. **节点模板完整性**：启动后端，访问 `/workflow-definitions/node-templates` 确认模板数量从 44 增至 53

---

## 假设与决策

1. **GIS 模块全部为 stub**：本轮不实现算法逻辑，仅注册模板和 stub 拦截，与现有 preprocess/stats/fusion/viz 模块保持一致
2. **算法合规性改造不改变函数签名**：仅提取常量、添加 docstring、添加边界检查，不改签名以避免破坏现有调用
3. **`omega.py` 与 `inversion.py` 的 Q 参数复用**：通过 import 复用 `_POLARIZATION_MIXING_Q`，避免重复定义
4. **`ndvi.py` gap_threshold_days 默认值统一为 30**：以算法默认值为准，更新节点模板
5. **UI 阶段 4.4 对齐辅助线和迷你地图为可选**：如果实现复杂度过高，可降级为仅实现节点引擎颜色和连接线颜色
6. **工作流模板标记为非只读**：允许用户基于模板修改并另存
7. **所有新增/修改文本使用中文**：与现有代码风格一致

## 验证步骤

1. `cd Code/frontend && npx vue-tsc --noEmit` — exit code 0
2. `python -m py_compile Code/algorithms/providers/Python/algorithms/physics.py Code/algorithms/providers/Python/algorithms/omega.py Code/algorithms/providers/Python/algorithms/block_inversion.py Code/algorithms/providers/Python/algorithms/ndvi.py Code/algorithms/providers/Python/algorithms/station.py Code/algorithms/providers/Python/algorithms/fy.py Code/algorithms/providers/Python/algorithms/inversion.py` — exit code 0
3. `python -m py_compile Code/backend/app/services/node_template_registry.py Code/backend/app/services/python_provider_bridge_service.py` — exit code 0
4. JSON 文件用 `python -c "import json; json.load(open('...'))"` 校验
5. 启动后端，GET `/workflow-definitions/node-templates` 确认 53 个模板
6. 启动前端，打开工作流编辑器，确认：
   - 节点库显示 9 个新 GIS 工具节点
   - 节点库顶部有引擎过滤标签和"收藏"/"最近使用"分类
   - 选中节点后画布显示引擎颜色边框
   - 参数编辑器按分组渲染并显示默认值
   - 左侧栏有"模板"分区，包含 3 个示例工作流
