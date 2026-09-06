# 系统优化 Phase 3 剩余工作计划

## 摘要

本计划承接此前已批准的 Phase 3 系统细节优化工作。阶段 1（9 个 GIS 模块注册）已完成，阶段 2.1（physics.py 合规性改造）已完成约 90%。本计划聚焦剩余 13 项工作：完成 physics.py 收尾、5 个算法文件合规性改造、数据流兼容性修复、4 个 UI 增强方向、后端 stub 注册、最终验证。

## 当前状态分析

### 已完成
- ✅ **阶段 1**：9 个 GIS 基础工具模块已注册到 [node_template_registry.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/node_template_registry.py#L828)（buffer_analysis / zonal_statistics / raster_calculator / vector_to_raster / raster_to_vector / reclassify / contour / slope_aspect / watershed）
- ✅ **阶段 2.1 主体**：[physics.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/algorithms/physics.py#L1) 顶部已提取 ~30 个命名常量（Mironov 系数、VWC 系数、物理阈值）；`build_mironov_context` 已加边界检查；`vwc_from_ndvi` / `tau_from_ndvi` / `_fresnel_reflectance_kernel_py` / `_mironov_dielectric_kernel_py` / `_broadcast_to_shape` / `fresnel_reflectance` / `build_fresnel_context` / `_fresnel_reflectance_kernel` / `fresnel_reflectance_from_context` / `mironov_dielectric` 已有 docstring

### 待完成（本计划范围）
1. physics.py 剩余 2 个函数 docstring
2. omega.py / block_inversion.py / ndvi.py / station.py / fy.py 合规性改造
3. inversion_daily.json 数据流断裂修复
4. 4 个 UI 增强方向
5. 后端 stub 注册 9 个 GIS 模块
6. 验证

---

## 提议变更

### 阶段 2.1 收尾：physics.py 剩余 docstring

**文件**：[physics.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/algorithms/physics.py#L373)

**变更**：
- `_mironov_dielectric_kernel`（第 373 行）：添加 docstring，说明输入 soil_moisture 单位 m³/m³，zxmvt/znd/zkd/znb/zkb/znu/zku 为 MironovContext 预计算无量纲系数，输出 (epsilon_real, epsilon_imag) 无量纲
- `mironov_dielectric_from_context`（第 395 行）：添加 docstring，说明输入 soil_moisture 单位 m³/m³，context 为 MironovContext，返回复介电常数（无量纲）

**为什么**：保证所有公开/半公开函数都有量纲注释，便于后续维护和算法审查。

---

### 阶段 2.2：omega.py 合规性改造

**文件**：[omega.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/algorithms/omega.py#L1)（2290 行，41 个函数/类）

**变更**：
1. **复用 inversion 常量**：`OmegaConfig.alpha0: float = 0.1771`（第 33 行）改为引用 `inversion._POLARIZATION_MIXING_Q`，避免重复定义极化混合系数
   - 在文件顶部 `from algorithms.inversion import _POLARIZATION_MIXING_Q`（若未导入）
   - `alpha0: float = _POLARIZATION_MIXING_Q`
2. **日期格式常量**：`make_date_blocks`（第 1118 行）使用的 `"%Y%m%d"` 格式提取为模块级常量 `_DATE_KEY_FORMAT = "%Y%m%d"`
3. **docstring 添加**：为以下关键函数添加量纲注释 docstring（简短，1-3 行）：
   - `OmegaConfig` 类：说明各字段量纲（freq_ghz 单位 GHz，alpha0/omega0/tau_rel_frac 无量纲，bounds_* 无量纲，block_days 单位天，pixel_chunk_size 单位像素数）
   - `build_omega_config` / `build_omega_field_config`：说明输入 params 字典、返回 dataclass
   - `_rough_reflectance` / `_rough_reflectance_from_context`：说明 theta_deg 单位度，h_value/alpha_value 无量纲，rh/rv 无量纲反射率
   - `tb_forward_single_temp` / `tb_forward_dual_temp`：说明输入 TB 单位 K，ts 单位 K，输出 TB 单位 K
   - `_tb_forward_single_temp_kernel` / `_tb_forward_dual_temp_kernel`：同上
   - `resid_halpha_single_temp` / `resid_halpha_dual_temp` / `resid_omega_block_single_temp` / `resid_omega_block_dual_temp`：说明残差单位 K（亮温残差）
   - `ddca_single_temp` / `ddca_dual_temp`：说明输出 sm 单位 m³/m³，vod 无量纲
   - `make_date_blocks`：说明输入 date_keys 格式 YYYYMMDD，返回按 block_days 分组的索引列表
   - `pick_lcurve_corner`：说明 L 曲线拐点选择算法
   - `retrieve_omega_pixel_timeseries` / `execute_omega_retrieval`：说明主入口函数，输入 payload 含 TB/Ts/NDVI 等，输出含 omega/h/tau 时间序列

**为什么**：omega.py 是核心反演算法，41 个函数中多数无 docstring，量纲不明确导致维护困难。复用 inversion 常量避免 0.1771 在两处定义产生不一致风险。

**注意**：私有辅助函数（`_finite_difference_jacobian` 等）只加简短一行 docstring，不过度注释。

---

### 阶段 2.3：block_inversion.py 合规性改造

**文件**：[block_inversion.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/algorithms/block_inversion.py#L1)（275 行）

**变更**：
1. **docstring 添加**：
   - `BlockFieldConfig` 类：说明各 aliases 字段对应 .mat 文件中的变量名
   - `build_block_field_config`：说明从 params 字典构建配置
   - `normalize_date_keys`：说明输入可为 None/标量/数组，返回日期字符串列表
   - `_broadcast_matrix` / `_as_time_pixel_matrix` / `_as_static_vector`：说明广播规则和量纲（输入可为标量/1D/2D，目标 shape 为 (nt, npix)）
   - `load_h_matrix`：说明 H 参数（粗糙度参数，无量纲）的加载优先级（dh_mat_path > payload > fallback_h）
   - `execute_block_inversion`：主入口，说明输入 payload 含 TBv/TBh/IA/Ts/NDVI 等（单位 K / 度 / 无量纲），freq_ghz 单位 GHz，输出含 SM_mat（m³/m³）/VOD_mat（无量纲）/DH_mat（无量纲）
2. **freq_ghz 边界检查**：在 `execute_block_inversion` 开头添加 `if not (0.1 <= freq_ghz <= 40.0): raise ValueError(...)`，复用 physics.py 的 `_FREQ_GHZ_MIN` / `_FREQ_GHZ_MAX`（通过 `from algorithms.physics import _FREQ_GHZ_MIN, _FREQ_GHZ_MAX`）

**为什么**：block_inversion 是批量反演入口，无 docstring 且无参数校验，错误输入会导致深层 numpy 错误难以定位。

---

### 阶段 2.4：ndvi.py 合规性改造

**文件**：[ndvi.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/algorithms/ndvi.py#L1)（279 行）

**变更**：
1. **提取 SG 滤波常量**（文件顶部）：
   ```python
   # Savitzky-Golay 滤波默认参数
   _SG_DEFAULT_POLYORDER = 6
   _SG_DEFAULT_WINDOW_LENGTH = 9
   _SG_DEFAULT_GAP_THRESHOLD_DAYS = 30
   _SG_DEFAULT_STEP_DAYS = 8
   _SG_MIN_VALID_POINTS = 4  # SG 滤波最少有效观测点数
   # NDVI 有效范围
   _NDVI_VALID_MIN = 0.0
   _NDVI_VALID_MAX = 1.0
   # 质量度量分位数
   _NDVI_RANGE_PERCENTILE_LOW = 5.0
   _NDVI_RANGE_PERCENTILE_HIGH = 95.0
   _NDVI_MIN_VALID_OBS = 3  # 质量度量最少有效观测数
   ```
2. **替换 magic numbers**：
   - `vi_sg_interpolate`：`4` → `_SG_MIN_VALID_POINTS`，`gap_threshold_days=30` → `_SG_DEFAULT_GAP_THRESHOLD_DAYS`，`sg_polyorder=6` → `_SG_DEFAULT_POLYORDER`，`sg_window_length=9` → `_SG_DEFAULT_WINDOW_LENGTH`
   - `process_ndvi_stack_to_daily`：同上替换默认值，`(daily_stack < 0.0) | (daily_stack > 1.0)` → `(daily_stack < _NDVI_VALID_MIN) | (daily_stack > _NDVI_VALID_MAX)`
   - `build_ndvi_quality_metrics`：`3` → `_NDVI_MIN_VALID_OBS`，`95.0`/`5.0` → `_NDVI_RANGE_PERCENTILE_HIGH`/`_NDVI_RANGE_PERCENTILE_LOW`
3. **docstring 添加**：
   - `build_datetime_sequence` / `to_day_numbers`：说明输入日期、输出 ordinal 数
   - `vi_sg_interpolate`：说明 SG 滤波插值算法，输入 data 单位无量纲（NDVI 0-1）
   - `process_ndvi_stack_to_daily`：说明输入 ndvi_stack shape (rows, cols, time)，输出 daily_stack shape (rows, cols, days)
   - `build_ndvi_quality_metrics` / `merge_ndvi_quality_metrics`：说明输出指标含义（mean/max/min/range/vali/diff/od）

**为什么**：ndvi.py 中 SG 参数在多个函数中重复硬编码，修改默认值需多处同步。提取常量后单一修改点。

---

### 阶段 2.5：station.py 合规性改造

**文件**：[station.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/algorithms/station.py#L1)（部分截断，约 400+ 行）

**变更**：
1. **提取质量常量**（文件顶部）：
   ```python
   # 站点数据质量标志
   _QUALITY_FLAG_GOOD = 1
   # 深度单位转换（cm → m）
   _CM_TO_M = 0.01
   # 日期格式
   _DATE_KEY_FORMAT = "%Y%m%d"
   ```
2. **替换 magic numbers**：
   - `filter_station_records`：`max_depth_cm / 100.0` → `max_depth_cm * _CM_TO_M`，`record.quality_flag != 1` → `record.quality_flag != _QUALITY_FLAG_GOOD`，`record.soil_moisture != record.soil_moisture` → `math.isnan(record.soil_moisture)`（更清晰表达 NaN 检查意图）
   - `aggregate_station_records_daily`：`quality_flag=1` → `quality_flag=_QUALITY_FLAG_GOOD`
   - `build_site_time_series_matrix`：`"%Y%m%d"` → `_DATE_KEY_FORMAT`
3. **docstring 添加**：
   - `filter_station_records`：说明各过滤条件
   - `aggregate_station_records_daily`：说明按 (year, month, day, depth) 分组取均值
   - `build_site_time_series_matrix`：说明返回 date_axis 和 values（单位 m³/m³）
   - `build_station_site_matrix`：说明返回 site_matrix shape (n_sites, n_days)
   - `nearest_grid_indices` / `sample_grid_values`：说明最近邻网格匹配
   - `build_station_validation_outputs`：说明验证输出结构

**为什么**：`record.soil_moisture != record.soil_moisture` 是利用 NaN 不等于自身的技巧，但可读性差，应用 `math.isnan` 明确表达意图。

---

### 阶段 2.6：fy.py 合规性改造

**文件**：[fy.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/algorithms/providers/Python/algorithms/fy.py#L1)（394 行）

**变更**：
1. **提取常量**（文件顶部）：
   ```python
   # GDAL 地理坐标系
   _GDAL_SRS_EPSG4326 = "EPSG:4326"
   # FY 数据 nodata 默认值
   _FY_DEFAULT_SRC_NODATA = -32767.0
   _FY_LATLON_SRC_NODATA = 65535.0
   # 默认重叠处理方式
   _FY_DEFAULT_OVERLAP = "average"
   ```
2. **替换 magic strings**：`build_geoloc_metadata_block` 中的 `"EPSG:4326"` → `_GDAL_SRS_EPSG4326`
3. **docstring 添加**：
   - `FyDatasetProfile` / `FyCommandStep` 类：说明字段含义
   - `FY3D_PROFILE` 等常量：说明各卫星配置
   - `resolve_gdal_bins`：说明 GDAL 可执行文件查找逻辑
   - `hdf_sds_uri`：说明 HDF5 SDS URI 格式
   - `build_geoloc_metadata_block`：说明 GEOLOCATION 元数据块
   - `build_fy_daily_command_steps`：说明命令步骤生成逻辑

**为什么**：fy.py 处理风云卫星数据，"EPSG:4326" 硬编码在元数据块中，提取常量便于未来支持其他投影。

---

### 阶段 3：数据流兼容性修复

**文件**：[inversion_daily.json](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/.data/workflow_definitions/system/inversion_daily.json#L1)

**问题分析**：
- 节点 2（data/time_range）输出 `time_range` 端口，但无任何 link 引用它 → 输出悬空
- 节点 3（module/inversion_daily）只有 1 个输入 `input_mat`，无 `time_range` 输入端口 → 时间范围无法传入反演模块
- links 数组中 `[2, 3, 0, 4, 0, "data"]` 实际是 node 3 → node 4 的连接，但 link id=2 未连接 node 2

**变更**：
1. 节点 3 的 inputs 添加 time_range 端口：
   ```json
   "inputs": [
     { "name": "input_mat", "type": "data" },
     { "name": "time_range", "type": "data" }
   ]
   ```
2. links 数组添加新 link 连接 node 2 → node 3：
   ```json
   [3, 2, 0, 3, 1, "data"]
   ```
   （link id=3, from node 2 slot 0, to node 3 slot 1, type "data"）
3. 检查其他 4 个 JSON（smap_soil_moisture.json / omega_block.json / block_inversion.json / weather_wind_field.json）是否有类似悬空输出/断裂连接，按需修复

**为什么**：data/time_range 节点存在但输出未连接，用户配置的时间范围无法影响反演结果，导致全量处理而非按时间过滤。

---

### 阶段 4.1：节点库增强

**文件**：[WorkflowNodePalette.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/workflow/WorkflowNodePalette.vue#L1)

**变更**：
1. **引擎过滤标签**：在搜索框下方添加引擎过滤标签栏（全部 / 天气 / Python / GEE / 通用），点击后只显示对应引擎的节点。基于 `tpl.type` 前缀判断引擎（weather/ / python_provider/ / gee/ / 其他）
2. **颜色标识**：节点项左侧添加 3px 引擎色条（weather=橙色 #ff9540, python_provider=绿色 #4caf50, gee=蓝色 #2196f3, common=青色 #00bcd4），与画布节点颜色一致
3. **收藏夹**：
   - 添加 `favorites` ref（Set<string>），持久化到 localStorage key `workflow_node_favorites`
   - 节点项右上角添加星标按钮，点击切换收藏
   - 分类列表顶部添加"★ 收藏"分组，显示所有收藏节点
4. **最近使用**：
   - 添加 `recentTypes` ref（string[]），持久化到 localStorage key `workflow_node_recent`，最多 10 个
   - `handleAddNode` 时将 tpl.type 加入 recentTypes（去重、移到头部）
   - 分类列表顶部添加"🕐 最近使用"分组

**为什么**：53 个节点跨 13 个分类，用户难以快速定位。引擎过滤 + 收藏 + 最近使用可大幅提升查找效率。

---

### 阶段 4.2：参数编辑增强

**文件**：[WorkflowInspector.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/workflow/WorkflowInspector.vue#L1)

**变更**：
1. **参数分组**：将参数按 `group` 字段（需在 node_template_registry.py 的 _param 添加 group 字段，或基于 key 前缀推断）分组显示，每组有可折叠标题。若无 group 则归入"基本参数"
2. **默认值对比**：参数标签旁显示默认值（灰色小字），当前值与默认值不同时高亮（橙色边框），便于识别已修改参数
3. **数组编辑器**：对 `type: "array"` 参数（如 remap_table、aliases），渲染为可增删行的表格编辑器，每行一个输入框，而非单个 JSON 文本框
4. **依赖联动**：参数 meta 支持 `depends_on` 字段（如 `distance_unit` 依赖 `distance` 存在），当依赖参数未设置时禁用当前参数并显示提示
5. **tooltip**：参数描述（`description`）以 ℹ 图标悬浮 tooltip 形式显示，而非占空间的文本行

**为什么**：当前参数编辑是扁平列表，复杂节点（如 raster_calculator 有 7 个参数）信息密度低，缺少默认值参考和类型提示。

---

### 阶段 4.3：工作流模板

**文件**：新建 3 个 JSON + 修改 [WorkflowLeftSidebar.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/workflow/WorkflowLeftSidebar.vue#L1)

**变更**：
1. 新建 3 个系统工作流 JSON（在 `Code/backend/.data/workflow_definitions/system/`）：
   - `ndvi_sm_correlation.json`：NDVI 与土壤湿度相关性分析工作流（data/source → ndvi_process → correlation → output/map_layer）
   - `watershed_analysis.json`：流域分析工作流（data/source_dem → gis/slope_aspect → gis/watershed → output/map_layer）
   - `multi_temporal_sm.json`：多时相土壤湿度工作流（data/source → data/time_range → module/inversion_daily → gis/zonal_statistics → output/map_layer）
2. WorkflowLeftSidebar.vue 添加"模板"分区，与"系统预设"分区并列，显示这 3 个模板工作流，支持"基于模板新建"

**为什么**：提供开箱即用的典型工作流，降低用户上手成本，同时验证新增 GIS 模块与现有模块的数据流兼容性。

---

### 阶段 4.4：画布交互优化

**文件**：[WorkflowCanvas.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/workflow/WorkflowCanvas.vue#L1) + [litegraph-setup.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/workflow/litegraph-setup.ts#L1)

**变更**：
1. **节点引擎颜色**：在 litegraph-setup.ts 的节点注册中，根据 type 前缀设置节点 title 颜色（weather=橙色, python_provider=绿色, gee=蓝色, common/gis=青色），与节点库色条一致
2. **连接线类型颜色**：`getPortColor` 函数已存在，扩展为连接线颜色也按端口类型着色（data=灰色, data:raster=绿色, data:geojson=橙色, data:timeseries=紫色, value:number=蓝色, value:string=黄色）
3. **对齐辅助线**：拖动节点时，若与其他节点的 x 或 y 边缘距离 < 5px，显示红色虚线辅助线，并对齐到该边缘
4. **迷你地图**：画布右下角添加迷你地图（LiteGraph 内置 `LGraphMiniMap`），显示整体节点布局，支持点击跳转

**为什么**：节点引擎颜色缺失导致画布上无法快速区分节点类型；连接线全灰色导致数据流类型不直观；对齐辅助线和迷你地图提升大工作流操作效率。

---

### 阶段 5：后端 stub 注册 9 个 GIS 模块

**文件**：[python_provider_bridge_service.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/services/python_provider_bridge_service.py#L41)

**变更**：在 `_PENDING_IMPLEMENTATION_MODULES` frozenset 中添加 9 个 GIS 模块名：
```python
_PENDING_IMPLEMENTATION_MODULES = frozenset({
    # ... 现有 15 个 ...
    "gis_buffer_analysis",
    "gis_zonal_statistics",
    "gis_raster_calculator",
    "gis_vector_to_raster",
    "gis_raster_to_vector",
    "gis_reclassify",
    "gis_contour",
    "gis_slope_aspect",
    "gis_watershed",
})
```

**为什么**：9 个 GIS 模块已在节点模板注册表登记，但后端无对应算法实现。添加到 stub 列表后，workflow 提交会返回 `pending_implementation` 状态而非调用 provider 报错，用户体验更友好。

---

### 阶段 6：验证

**命令**：
1. 前端类型检查：`cd Code/frontend && npx vue-tsc --noEmit`
2. 后端 Python 编译检查（6 个算法文件 + bridge service）：
   ```
   python -m py_compile Code/algorithms/providers/Python/algorithms/physics.py
   python -m py_compile Code/algorithms/providers/Python/algorithms/omega.py
   python -m py_compile Code/algorithms/providers/Python/algorithms/block_inversion.py
   python -m py_compile Code/algorithms/providers/Python/algorithms/ndvi.py
   python -m py_compile Code/algorithms/providers/Python/algorithms/station.py
   python -m py_compile Code/algorithms/providers/Python/algorithms/fy.py
   python -m py_compile Code/backend/app/services/python_provider_bridge_service.py
   ```
3. JSON 校验：用 `python -c "import json; json.load(open(...))"` 校验修复后的 inversion_daily.json 和 3 个新模板 JSON
4. 节点模板注册表加载验证：启动后端，访问 `/workflow-definitions/node-templates` 确认返回 53 个模板

---

## 假设与决策

1. **omega.py 复用 inversion 常量**：假设 `_POLARIZATION_MIXING_Q` 可从 `algorithms.inversion` 导入（已确认第 19 行定义）。决策：导入私有常量可接受，因同包内共享物理常量是合理的。
2. **station.py NaN 检查改写**：`record.soil_moisture != record.soil_moisture` 改为 `math.isnan(record.soil_moisture)`。假设 soil_moisture 为 float 类型（StationRecord dataclass 定义确认）。决策：若 soil_moisture 可能为 None，保留原写法或用 `record.soil_moisture is None or math.isnan(record.soil_moisture)`。
3. **inversion_daily.json 修复**：假设节点 3 的 `time_range` 输入端口名与后端 `workflow_request_resolver.py` 期望一致。决策：先检查 resolver 逻辑，若后端不消费 time_range 端口则只修复前端连接而不添加端口。
4. **UI 阶段 4.2 参数分组**：假设 node_template_registry.py 的 `_param` 当前无 `group` 字段。决策：若添加 group 字段需修改后端模板结构，影响范围大，改为前端基于 key 前缀推断分组（如 `tbv_*` → "亮温字段", `ndvi_*` → "NDVI 字段"）。
5. **阶段 4.3 模板 JSON**：假设新建工作流 JSON 的 engine 字段为 "python_provider"。决策：gis/* 模块 engine 为 "common"，但 workflow engine 仍为 "python_provider"（因为 bridge 路由基于 workflow engine）。
6. **不过度改造**：遵循用户"细节修改和补充"的定位，不重构算法核心逻辑，只做常量提取、docstring、边界检查、UI 增强。

## 验证步骤

1. **Python 编译**：所有修改的 .py 文件通过 `python -m py_compile`
2. **前端类型**：`vue-tsc --noEmit` 无新增类型错误
3. **JSON 合法性**：所有修改/新建的 JSON 可被 `json.load` 解析
4. **功能验证**（用户手动）：
   - 刷新 http://localhost:5175，打开流配置
   - 节点库显示 53 个节点，新增引擎过滤标签和收藏功能
   - 选择 inversion_daily 工作流，节点 2 → 节点 3 连接显示
   - 拖动节点时显示对齐辅助线，右下角显示迷你地图
   - 选中节点，参数面板按分组显示，有默认值对比和 tooltip
   - 左侧栏显示"模板"分区，包含 3 个新模板

## 执行顺序

按依赖关系执行：
1. 阶段 2.1 收尾（physics.py）→ 阶段 2.2（omega.py）→ 阶段 2.3（block_inversion.py）→ 阶段 2.4（ndvi.py）→ 阶段 2.5（station.py）→ 阶段 2.6（fy.py）
2. 阶段 3（数据流修复）
3. 阶段 5（stub 注册，需在阶段 4.3 模板前完成，确保模板中的 gis 模块可提交）
4. 阶段 4.1 → 4.2 → 4.3 → 4.4（UI 增强，相互独立可并行）
5. 阶段 6（验证）
