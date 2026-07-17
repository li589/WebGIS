# 系统细节优化计划

> **范围**：模块扩充 + 数据结构修复 + UI 优化 + 算法合规性
> **基线**：当前 30 个节点模板（common 5 + weather 11 + python_provider 10 + gee 4）

## 当前状态分析

### 节点模板问题清单

| 问题 | 影响 | 位置 |
|------|------|------|
| 端口类型 "data" 过于宽泛 | 无法防止错误连接（如 wind_field 输出连接到 smap_daily 输入） | node_template_registry.py 全局 |
| `data/bbox` 输出 type="geometry"，但 `weather/wind_field_render` 的 bbox 输入 type="data" | 类型不兼容，LiteGraph 不允许连接 | node_template_registry.py L72, L172 |
| `data/time_range` 输出无下游消费者 | smap_soil_moisture.json 中 node 2 未连接到任何节点 | system/smap_soil_moisture.json L29-36 |
| `module/inversion_daily` 的 `freq_ghz` (number) 无 default | 用户必须手动填写，否则得到空值 | node_template_registry.py L407 |
| `module/block_inversion` 的 `freq_ghz`/`pixel_chunk_size` 无 default | 同上 | node_template_registry.py L425-426 |
| `module/omega_block` 的 `freq_ghz`/`temp_scheme` 无 default | 同上 | node_template_registry.py L445-446 |
| `data/bbox` 的 west/south/east/north (number) 无 default | 新增节点时输入框为空 | node_template_registry.py L75-78 |
| `data/time_range` 的 start_at/end_at 无 default | 同上 | node_template_registry.py L58-59 |
| `gee/select_bands` 的 bands type="array" | 前端 `mapParamTypeToWidget` 不支持 array | node_template_registry.py L552, litegraph-setup.ts L183 |
| WorkflowInspector enum 参数用 text input | 用户需手动输入选项值，易出错 | WorkflowInspector.vue L227-234 |
| 节点库按引擎分类（general/weather/...） | 不符合"按功能"查找直觉 | WorkflowNodePalette.vue L24-29 |

### 算法合规性问题

| 问题 | 位置 |
|------|------|
| `f_sm_cost` 中 `lambda_value = 20.0` 是 magic constant | algorithms/providers/Python/algorithms/inversion.py L115 |
| `tb_model` 中 `_ = (tbv_obs, tbh_obs)` 无操作遗留代码 | inversion.py L83 |
| `rough_reflectance` 与 `rough_reflectance_from_context` 重复逻辑 | inversion.py L32-47 |

---

## 第一阶段：数据结构修复（基础设施层）

> 先修复类型系统，确保后续新增模块有正确的类型基础。

### 1.1 细化端口类型系统

**文件**: `Code/backend/app/services/node_template_registry.py`

引入分层端口类型，保持向后兼容：

| 原类型 | 新类型 | 用途 | 颜色建议 |
|--------|--------|------|---------|
| "data" | "data" (保留为通用) | 通用数据流 | 灰色 |
| - | "data:mat" | .mat 文件（Python Provider 输出） | 橙色 |
| - | "data:raster" | 栅格数据（GEE 影像、天气网格） | 蓝色 |
| - | "data:geojson" | GeoJSON 矢量数据 | 绿色 |
| - | "data:timeseries" | 时间序列 .mat | 紫色 |
| - | "data:source" | 数据源引用（路径/URI） | 青色 |
| "value" | "value:number" | 数值 | 浅黄 |
| "value" | "value:string" | 字符串 | 浅黄 |
| "geometry" | "geometry:bbox" | 空间范围 | 红色 |
| - | "value:time_range" | 时间范围 | 粉色 |

**连接规则**（前端 `litegraph-setup.ts` 实现）：
- 相同类型：允许连接
- `data` → `data:*`：允许连接（通用 → 具体）
- `data:*` → `data`：允许连接（具体 → 通用）
- `data:mat` → `data:raster`：**禁止**（不同子类型）
- 其他不同类型：禁止

### 1.2 修复现有节点模板的端口类型

**文件**: `Code/backend/app/services/node_template_registry.py`

按新类型系统更新所有 30 个节点模板的 inputs/outputs type：

- `data/source` 输出: `data` → `data:source`
- `data/time_range` 输出: `data` → `value:time_range`
- `data/bbox` 输出: `geometry` → `geometry:bbox`
- `module/smap_daily` 输入: `data` → `data:source`；输出: `data` → `data:mat`
- `module/inversion_daily` 输入: `data` → `data:mat`；输出: `data` → `data:mat`
- `weather/wind_field_render` 的 bbox 输入: `data` → `geometry:bbox`
- `weather/*_render` 输出: `geojson` → `data:geojson`
- `gee/image` 输出: `raster` → `data:raster`
- `output/map_layer` 输入: `data` → `data`（保持通用）
- `output/file` 输入: `data` → `data`（保持通用）

### 1.3 补全缺失的参数默认值

**文件**: `Code/backend/app/services/node_template_registry.py`

| 节点 | 参数 | 默认值 |
|------|------|--------|
| `module/inversion_daily` | `freq_ghz` | `1.4`（L 波段 SMAP 标称频率） |
| `module/block_inversion` | `freq_ghz` | `1.4` |
| `module/block_inversion` | `pixel_chunk_size` | `512` |
| `module/omega_block` | `freq_ghz` | `1.4` |
| `module/omega_block` | `temp_scheme` | `"default"` |
| `data/bbox` | `west/south/east/north` | `0.0` |
| `data/time_range` | `start_at/end_at` | `""` |
| `data/time_range` | `granularity` | 已有 `"day"` |
| `module/daily_bundle` | `tb_source`/`sm_source`/`ndvi_mode` | `"default"` |
| `module/timeseries_bundle` | `tb_source`/`sm_source` | `"default"` |

### 1.4 前端类型校验与 array 支持

**文件**: `Code/frontend/src/components/workflow/litegraph-setup.ts`

- `mapParamTypeToWidget`：新增 `array` → `text`（逗号分隔输入，运行时解析为数组）
- 新增 `checkConnectionValid` 函数，在 `LGraphCanvas.onConnectNode` 中调用，实现 1.1 的连接规则
- 端口类型颜色：在 `getEngineColor` 旁新增 `getPortColor(type)` 返回类型对应颜色

### 1.5 修复系统预设工作流断裂连接

**文件**: `Code/backend/.data/workflow_definitions/system/smap_soil_moisture.json`

- node 3 (`module/smap_daily`) 新增 `time_range` 输入端口
- 新增 link: `[3, 2, 0, 3, 1, "value:time_range"]`
- `module/smap_daily` 节点模板新增 `time_range` 输入端口（optional）

---

## 第二阶段：新增基础模块

> 用户优先选择：数据预处理、统计分析、数据融合与可视化（共 3 类，约 15 个新节点）

### 2.1 数据预处理模块（5 个新节点）

**文件**: `Code/backend/app/services/node_template_registry.py` → 追加到 `_NODE_TEMPLATES`

| type | engine | title | inputs | outputs | params |
|------|--------|-------|--------|---------|--------|
| `preprocess/reproject` | `common` | 重投影 | `data:raster`, `geometry:bbox`(optional) | `data:raster` | `target_crs`(string, default "EPSG:4326"), `resampling`(enum: nearest/bilinear/cubic, default "nearest") |
| `preprocess/resample` | `common` | 重采样 | `data:raster` | `data:raster` | `target_resolution`(number, default 1000), `resampling`(enum, default "nearest"), `unit`(enum: meters/degrees, default "meters") |
| `preprocess/format_convert` | `common` | 格式转换 | `data` | `data` | `input_format`(enum: netcdf/hdf5/geotiff/mat), `output_format`(enum: geotiff/cog/mat/json, default "geotiff") |
| `preprocess/clip` | `common` | 裁剪 | `data:raster`, `geometry:bbox` | `data:raster` | `buffer_meters`(number, default 0) |
| `preprocess/mask` | `common` | 掩膜 | `data:raster`, `data:raster`(mask) | `data:raster` | `mask_value`(number, default 0), `invert`(boolean, default false) |

### 2.2 统计分析模块（5 个新节点）

| type | engine | title | inputs | outputs | params |
|------|--------|-------|--------|---------|--------|
| `stats/spatial_mean` | `common` | 空间均值 | `data:raster` | `value:number` | `statistic`(enum: mean/median/min/max/std, default "mean"), `band`(number, default 0) |
| `stats/temporal_trend` | `common` | 时间趋势分析 | `data:timeseries` | `data:geojson` | `trend_method`(enum: linear/theil_sen/mann_kendall, default "linear"), `confidence_level`(number, default 0.95) |
| `stats/anomaly_detect` | `common` | 异常检测 | `data:timeseries` | `data:geojson` | `method`(enum: zscore/iqr/dbscan, default "zscore"), `threshold`(number, default 2.0) |
| `stats/correlation` | `common` | 相关性分析 | `data:timeseries`(x), `data:timeseries`(y) | `value:number` | `method`(enum: pearson/spearman/kendall, default "pearson"), `lag_days`(number, default 0) |
| `stats/histogram` | `common` | 直方图统计 | `data:raster` | `data:geojson` | `bins`(number, default 50), `band`(number, default 0), `density`(boolean, default false) |

### 2.3 数据融合与可视化模块（5 个新节点）

| type | engine | title | inputs | outputs | params |
|------|--------|-------|--------|---------|--------|
| `fusion/spatial_interpolate` | `common` | 空间插值 | `data:geojson`(points), `geometry:bbox` | `data:raster` | `method`(enum: idw/kriging/nearest, default "idw"), `power`(number, default 2.0), `resolution`(number, default 1000) |
| `fusion/multi_source_merge` | `common` | 多源融合 | `data:raster`(primary), `data:raster`(secondary) | `data:raster` | `method`(enum: weighted/pca/bayesian, default "weighted"), `weight_primary`(number, default 0.6) |
| `viz/chart_generate` | `common` | 图表生成 | `data` | `value:string`(base64 PNG) | `chart_type`(enum: line/bar/scatter/heatmap/boxplot, default "line"), `title`(string), `x_label`(string), `y_label`(string), `width`(number, default 800), `height`(number, default 600) |
| `viz/report_export` | `common` | 报表导出 | `data`(多输入) | `value:string`(文件路径) | `format`(enum: pdf/html/docx/markdown, default "html"), `template`(string), `include_charts`(boolean, default true) |
| `viz/statistics_summary` | `common` | 统计摘要 | `data` | `data:geojson` | `include_mean`(boolean, default true), `include_std`(boolean, default true), `include_percentiles`(boolean, default true), `percentile_list`(string, default "25,50,75") |

### 2.4 后端 stub 实现

**文件**: `Code/backend/app/services/python_provider_bridge_service.py`

为每个新模块的 `node_class` 添加最小 stub 实现：
- 注册到 bridge service 的模块映射表
- 返回 `{"status": "pending_implementation", "node_class": "..."}`
- 确保 workflow 可以提交但会返回"模块开发中"状态

---

## 第三阶段：UI 优化

### 3.1 节点库按功能分类

**文件**: `Code/frontend/src/stores/workflow-definitions.ts`

修改 `templatesByCategory` computed，将分类逻辑从"按引擎"改为"按功能"：

```
数据输入 → data/source, data/time_range, data/bbox
数据预处理 → preprocess/* (5 个新节点)
遥感处理 → module/smap_daily, module/ndvi_daily, module/fy_daily, module/station_daily
合成 → module/daily_bundle, module/timeseries_bundle
反演 → module/inversion_daily, module/block_inversion, module/omega_block
统计分析 → stats/* (5 个新节点)
数据融合 → fusion/* (3 个新节点)
可视化 → viz/* (3 个新节点)
天气-数据抓取 → weather/forecast_fetch, weather/grid_fetch
天气-渲染 → weather/wind_field_render, weather/temperature_render, ...
天气-处理 → weather/point_parse, weather/summary_generate
GEE-数据 → gee/image
GEE-处理 → gee/cloud_mask, gee/clip, gee/select_bands
输出 → output/map_layer, output/file
```

**文件**: `Code/frontend/src/components/workflow/WorkflowNodePalette.vue`

- 更新 `CATEGORY_LABELS` 和 `ENGINE_ICONS` 为功能分类
- 每个分类项显示引擎图标小标签（区分来源引擎）
- 节点项增加输入/输出类型颜色标识

### 3.2 属性检查器参数渲染优化

**文件**: `Code/frontend/src/components/workflow/WorkflowInspector.vue`

| 参数类型 | 当前渲染 | 优化后渲染 |
|----------|---------|-----------|
| number | `<input type="number">` | 加 `min`/`max`/`step` 属性，显示单位后缀 |
| enum (有 options) | `<input type="text">` | `<select>` 下拉框 |
| boolean | `<input type="checkbox">` | 开关样式 toggle |
| array | 不支持 | 逗号分隔文本输入 + 提示 |
| string (有 default) | `<input type="text">` | 加 placeholder |

具体实现：
- 从 `nodeTemplate.params` 获取参数的 `options`/`default`/`description`
- 新增 `getParamUnit(key)` 返回单位（如 "GHz"、"度"、"天"、"米"）
- 新增 `getParamRange(key)` 返回 `{min, max, step}`（从 description 解析或硬编码）
- enum 类型用 `<select>` 渲染，options 来自模板

### 3.3 参数验证与提示

**文件**: `Code/frontend/src/components/workflow/WorkflowInspector.vue`

- 经度范围验证：-180 ~ 180
- 纬度范围验证：-90 ~ 90
- 频率验证：1.0 ~ 40.0 GHz
- 时间格式验证：ISO 8601
- 验证失败时输入框红色边框 + 错误提示

### 3.4 端口类型可视化

**文件**: `Code/frontend/src/components/workflow/litegraph-setup.ts`

- `getPortColor(type)` 函数返回端口颜色
- 在节点构造函数中设置 input/output slot 的 `color` 属性
- 连线颜色根据来源端口类型着色

### 3.5 参数单位与描述显示

**文件**: `Code/backend/app/services/node_template_registry.py`

在 `_param` 函数中新增 `unit` 和 `range` 可选字段：

```python
def _param(key, kind="string", default=None, description="", options=None,
           unit=None, min_val=None, max_val=None, step=None):
    p = {"key": key, "type": kind, "default": default, "description": description}
    if options: p["options"] = options
    if unit: p["unit"] = unit
    if min_val is not None: p["min"] = min_val
    if max_val is not None: p["max"] = max_val
    if step is not None: p["step"] = step
    return p
```

为关键参数补充单位：
- `freq_ghz`: unit="GHz", min=0.1, max=40, step=0.1
- `west/south/east/north`: unit="度", min=-180/-90, max=180/90, step=0.01
- `pixel_chunk_size`: unit="像素", min=64, max=4096, step=64
- `resolution`: unit="米", min=10, max=10000, step=10

---

## 第四阶段：算法合规性

### 4.1 替换 magic constants

**文件**: `Code/algorithms/providers/Python/algorithms/inversion.py`

| magic constant | 命名常量 | 物理含义 |
|---------------|---------|---------|
| `lambda_value = 20.0` (L115) | `_TAU_REGULARIZATION_LAMBDA = 20.0` | tau 正则化系数（L2 惩罚强度） |

### 4.2 清理遗留代码

**文件**: `Code/algorithms/providers/Python/algorithms/inversion.py`

- 删除 `tb_model` 中 `_ = (tbv_obs, tbh_obs)` (L83) — 无操作赋值
- 或者：如果 `tbv_obs`/`tbh_obs` 本应参与计算（如残差计算），添加实际使用逻辑

### 4.3 消除重复代码

**文件**: `Code/algorithms/providers/Python/algorithms/inversion.py`

- `rough_reflectance` 和 `rough_reflectance_from_context` 合并为单一函数
- 提取公共的 `q_value` 和 `exp_term` 计算逻辑

### 4.4 边界条件与异常值处理

**文件**: `Code/algorithms/providers/Python/algorithms/inversion.py`

- `tb_model`: 检查 `soil_moisture` 范围 [0, 0.6]（物理约束）
- `tb_model`: 检查 `tau_value >= 0`（光学厚度非负）
- `tb_model`: 检查 `h_value >= 0`（粗糙度非负）
- `f_sm_cost`: 检查 `freq_ghz` 在合理范围 [0.1, 40]
- 超出范围时返回 `float('inf')` 而非物理无意义值

### 4.5 量纲注释补充

**文件**: `Code/algorithms/providers/Python/algorithms/inversion.py`

为每个函数添加量纲注释：
- `tb_model`: 输入 TB 单位 K（开尔文），输出 TB 单位 K
- `f_sm_cost`: 返回残差向量，单位 K
- `rough_reflectance`: 输入/输出无量纲（反射率 0-1）
- `build_tb_model_context`: freq_ghz 单位 GHz，theta_deg 单位度

---

## 实施顺序与依赖

```
第一阶段（数据结构修复）
  ├── 1.1 端口类型系统设计
  ├── 1.2 更新现有 30 个节点模板端口类型
  ├── 1.3 补全参数默认值
  ├── 1.4 前端类型校验 + array 支持
  └── 1.5 修复工作流断裂连接
        ↓
第二阶段（新增 15 个模块）
  ├── 2.1 数据预处理模块（5 个）
  ├── 2.2 统计分析模块（5 个）
  ├── 2.3 数据融合与可视化模块（5 个）
  └── 2.4 后端 stub 实现
        ↓
第三阶段（UI 优化）
  ├── 3.1 节点库按功能分类
  ├── 3.2 属性检查器参数渲染优化
  ├── 3.3 参数验证与提示
  ├── 3.4 端口类型可视化
  └── 3.5 参数单位与描述
        ↓
第四阶段（算法合规性）
  ├── 4.1 替换 magic constants
  ├── 4.2 清理遗留代码
  ├── 4.3 消除重复代码
  ├── 4.4 边界条件处理
  └── 4.5 量纲注释
```

## 假设与决策

1. **端口类型兼容性**：保持 "data" 作为通用类型，新增子类型 "data:mat" 等，通过前端连接校验钩子实现类型安全，不破坏现有工作流定义
2. **新模块后端实现**：第二阶段先添加节点模板和 stub，实际算法实现由后续迭代完成
3. **UI 分类切换**：从"按引擎"改为"按功能"分类，但保留引擎图标作为辅助标识
4. **算法修改最小化**：只修改 `inversion.py` 中明确的问题，不重构整体算法结构
5. **参数 unit/range 字段**：在 `_param` 函数中新增可选字段，向后兼容（现有参数不传则无 unit/range）

## 验证步骤

1. **后端**：
   - `python -m py_compile` 检查所有修改的 .py 文件
   - 启动 FastAPI 后端，访问 `/workflow-definitions/node-templates` 确认 45 个节点模板（30 现有 + 15 新增）
   - 访问 `/workflow-definitions` 确认 5 个系统预设工作流加载正常

2. **前端**：
   - `npx vue-tsc --noEmit` 确认无类型错误
   - 打开工作流编辑器，确认节点库按功能分类显示
   - 拖入新节点，确认参数面板用 select 下拉框渲染 enum
   - 拖入 data/bbox 节点，连接到 weather/wind_field_render，确认类型兼容
   - 拖入 data/source，尝试连接到 weather/wind_field_render 的 latitude 输入，确认类型校验拦截

3. **算法**：
   - `python -m py_compile Code/algorithms/providers/Python/algorithms/inversion.py`
   - 运行现有反演测试（如有），确认结果一致

4. **集成**：
   - 打开 smap_soil_moisture 工作流，确认 time_range 节点已连接
   - 运行工作流，确认无类型错误
