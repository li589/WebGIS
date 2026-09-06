# 分析面板 GIS 分析工具扩展计划

## 概述

在分析面板（InfoPanelToolsTab）中新增 6 个常规 GIS 分析操作工具，将已注册但未暴露的算法模块接入现有分析工具框架，使用户可直接对选中图层执行地形分析、栅格运算、格式转换和流域分析。

## 现状分析

### 已有 5 个工具（可用）

| tool_id | 模块 | 输入类型 | 功能 |
|---------|------|---------|------|
| `gis.buffer` | `gis_buffer_analysis` | vector/point | 缓冲区 |
| `gis.zonal_stats` | `gis_zonal_statistics` | raster | 分区统计 |
| `gis.clip` | `preprocess_clip` | raster | 栅格裁剪 |
| `stats.histogram` | `stats_histogram` | raster | 直方图 |
| `gis.reclassify` | `gis_reclassify` | raster | 栅格重分类 |

### 已注册但未暴露的 6 个模块（本计划目标）

| 模块名 | 节点类型 | 输入端口 | 输出 | 描述 |
|--------|---------|---------|------|------|
| `gis_contour` | `gis/contour` | raster | GeoJSON | 等值线提取 |
| `gis_slope_aspect` | `gis/slope_aspect` | raster(DEM) | GeoTIFF×2 | 坡度坡向 |
| `gis_raster_calculator` | `gis/raster_calculator` | raster(A/B) | GeoTIFF | 栅格计算器 |
| `gis_vector_to_raster` | `gis/vector_to_raster` | vector | GeoTIFF | 矢量转栅格 |
| `gis_raster_to_vector` | `gis/raster_to_vector` | raster | GeoJSON | 栅格转矢量 |
| `gis_watershed` | `gis/watershed` | raster(DEM)+point | GeoJSON | 流域分析 |

### 框架成熟度

分析工具框架已完全打通：`analysis_tools.json`（工具目录）→ `analysis_*.json`（workflow 种子）→ `analysis_run_service.py`（请求构建+参数注入）→ Celery 执行 → 结果回传 InfoPanel。新增工具是**配置任务**，不涉及架构变更。

## 变更清单

### 1. 工具目录种子 — `Code/backend/app/catalog_seeds/analysis_tools.json`

在现有 5 个工具后追加 6 个条目：

```json
{
  "tool_id": "gis.contour",
  "title": "等值线",
  "description": "从栅格表面提取等值线，产出 GeoJSON 线要素。",
  "category": "gis",
  "input_kinds": ["raster"],
  "param_schema": [
    { "key": "interval", "type": "number", "title": "等值距", "default": 100, "min": 0.01 },
    { "key": "band", "type": "integer", "title": "波段", "default": 0, "min": 0 },
    { "key": "smoothing", "type": "enum", "title": "平滑", "default": "true", "options": ["true", "false"] }
  ],
  "workflow_template_id": "analysis_contour",
  "outputs": ["file"],
  "resource_profile": "standard",
  "concurrency_key": "layer_tool"
}
```

```json
{
  "tool_id": "gis.slope_aspect",
  "title": "坡度坡向",
  "description": "从 DEM 计算坡度（度）和坡向（度），产出两个 GeoTIFF。",
  "category": "gis",
  "input_kinds": ["raster"],
  "param_schema": [
    { "key": "z_unit", "type": "enum", "title": "高程单位", "default": "meters", "options": ["meters", "feet"] },
    { "key": "algorithm", "type": "enum", "title": "算法", "default": "horn", "options": ["horn", "zevenbergen"] }
  ],
  "workflow_template_id": "analysis_slope_aspect",
  "outputs": ["map_layer", "file"],
  "resource_profile": "standard",
  "concurrency_key": "layer_tool"
}
```

```json
{
  "tool_id": "gis.raster_calc",
  "title": "栅格计算器",
  "description": "对栅格执行表达式运算（支持 A、B 变量和算术运算），产出新 GeoTIFF。",
  "category": "gis",
  "input_kinds": ["raster"],
  "param_schema": [
    { "key": "expression", "type": "string", "title": "表达式", "default": "A", "description": "支持 A、B 变量，如 A*2、(A+B)/2" },
    { "key": "nodata_handling", "type": "enum", "title": "NoData 处理", "default": "propagate", "options": ["propagate", "zero", "ignore"] }
  ],
  "workflow_template_id": "analysis_raster_calc",
  "outputs": ["map_layer", "file"],
  "resource_profile": "standard",
  "concurrency_key": "layer_tool"
}
```

```json
{
  "tool_id": "gis.vector_to_raster",
  "title": "矢量转栅格",
  "description": "将矢量要素按属性字段栅格化为 GeoTIFF。",
  "category": "gis",
  "input_kinds": ["vector"],
  "param_schema": [
    { "key": "attribute_field", "type": "string", "title": "属性字段", "default": "", "description": "留空则燃烧值为 1" },
    { "key": "resolution", "type": "number", "title": "分辨率", "default": 0.01, "min": 0.0001, "description": "度（地理坐标）或米（投影坐标）" },
    { "key": "fill_value", "type": "number", "title": "填充值", "default": 0 }
  ],
  "workflow_template_id": "analysis_vector_to_raster",
  "outputs": ["map_layer", "file"],
  "resource_profile": "standard",
  "concurrency_key": "layer_tool"
}
```

```json
{
  "tool_id": "gis.raster_to_vector",
  "title": "栅格转矢量",
  "description": "将栅格像元多边形化为 GeoJSON（阈值以上提取边界）。",
  "category": "gis",
  "input_kinds": ["raster"],
  "param_schema": [
    { "key": "band", "type": "integer", "title": "波段", "default": 0, "min": 0 },
    { "key": "threshold", "type": "number", "title": "阈值", "default": 0, "description": "仅提取值 > 阈值的像元" },
    { "key": "simplify_tolerance", "type": "number", "title": "简化容差", "default": 0, "min": 0 }
  ],
  "workflow_template_id": "analysis_raster_to_vector",
  "outputs": ["file"],
  "resource_profile": "standard",
  "concurrency_key": "layer_tool"
}
```

```json
{
  "tool_id": "gis.watershed",
  "title": "流域分析",
  "description": "从 DEM 和地图选点（汇流点）执行 D8 流域划分，产出 GeoJSON。",
  "category": "gis",
  "input_kinds": ["raster"],
  "param_schema": [
    { "key": "fill_threshold", "type": "number", "title": "洼地填充阈值", "default": 0.01, "min": 0 },
    { "key": "max_dem_pixels", "type": "integer", "title": "最大像元数", "default": 4000000, "min": 100000 }
  ],
  "workflow_template_id": "analysis_watershed",
  "outputs": ["file"],
  "resource_profile": "heavy",
  "concurrency_key": "layer_tool"
}
```

### 2. Workflow 种子文件（6 个新文件）

目录：`Code/backend/workflow_seeds/system/`

每个种子遵循 `analysis_clip.json` 的单节点模式（data/source → module → 隐式输出），不走多节点 demo 链。

**`analysis_contour.json`**：data/source(dataset_key=input_path) → gis/contour(interval, band, smoothing)

**`analysis_slope_aspect.json`**：data/source(dataset_key=input_path) → gis/slope_aspect(z_unit, algorithm)

**`analysis_raster_calc.json`**：data/source(dataset_key=input_path) → gis/raster_calculator(expression, nodata_handling)

**`analysis_vector_to_raster.json`**：data/source(dataset_key=input_path) → gis/vector_to_raster(attribute_field, resolution, fill_value)

**`analysis_raster_to_vector.json`**：data/source(dataset_key=input_path) → gis/raster_to_vector(band, threshold, simplify_tolerance)

**`analysis_watershed.json`**：data/source(dataset_key=input_path) + data/source(dataset_key=pour_points_path) → gis/watershed(fill_threshold, max_dem_pixels)

种子结构示例（以 contour 为例）：
```json
{
  "_meta": {
    "kind": "system",
    "engine": "python_provider",
    "name": "Analysis: contour",
    "description": "InfoPanel contour. Inject raster path.",
    "author": "system",
    "readonly": true,
    "is_template": true,
    "linked_layer_id": null,
    "tags": ["analysis", "gis", "contour", "ui-panel"],
    "category": "analysis",
    "resource_profile": "standard"
  },
  "workflow_id": "analysis_contour",
  "name": "Analysis: contour",
  "description": "data/source → gis/contour",
  "nodes": [
    {
      "id": 1,
      "type": "data/source",
      "pos": [60, 120],
      "properties": {
        "path": "{DATA_ROOT}/_runtime/smoke_stub.tif",
        "dataset_key": "input_path"
      }
    },
    {
      "id": 2,
      "type": "gis/contour",
      "pos": [360, 160],
      "properties": {
        "interval": 100,
        "band": 0,
        "smoothing": true
      }
    }
  ],
  "links": [
    [1, 1, 2, 2, 1]
  ]
}
```

### 3. 后端分析运行服务 — `Code/backend/app/services/analysis_run_service.py`

#### 3a. `_inject_tool_params` 函数扩展

在现有 if-elif 链末尾追加 6 个新 tool_id 分支：

```python
elif tool_id == "gis.contour" and ntype == "gis/contour":
    for key in ("interval", "band", "smoothing"):
        if key in params and params[key] is not None:
            props[key] = params[key]
elif tool_id == "gis.slope_aspect" and ntype == "gis/slope_aspect":
    for key in ("z_unit", "algorithm"):
        if key in params and params[key] is not None:
            props[key] = params[key]
elif tool_id == "gis.raster_calc" and ntype == "gis/raster_calculator":
    for key in ("expression", "nodata_handling"):
        if key in params and params[key] is not None:
            props[key] = params[key]
elif tool_id == "gis.vector_to_raster" and ntype == "gis/vector_to_raster":
    for key in ("attribute_field", "resolution", "fill_value"):
        if key in params and params[key] is not None:
            props[key] = params[key]
elif tool_id == "gis.raster_to_vector" and ntype == "gis/raster_to_vector":
    for key in ("band", "threshold", "simplify_tolerance"):
        if key in params and params[key] is not None:
            props[key] = params[key]
elif tool_id == "gis.watershed" and ntype == "gis/watershed":
    for key in ("fill_threshold", "max_dem_pixels"):
        if key in params and params[key] is not None:
            props[key] = params[key]
```

#### 3b. `build_analysis_submit_request` 函数扩展

将 6 个新 tool_id 加入栅格输入注入分支（与 `gis.clip`、`stats.histogram`、`gis.reclassify` 同组）：

```python
elif tool.tool_id in {
    "gis.clip", "stats.histogram", "gis.reclassify",
    "gis.contour", "gis.slope_aspect", "gis.raster_calc",
    "gis.raster_to_vector", "gis.watershed",
}:
    if not primary_path:
        raise AnalysisRunError(f"{tool.title}需要栅格输入（overlay_layer_id）")
    _inject_node_path(nodes, dataset_key="input_path", path=primary_path)
```

**watershed 特殊处理**：需要 pour_points（汇流点）。复用 `gis.buffer` 的 `_write_point_geojson` 逻辑：

```python
if tool.tool_id == "gis.watershed":
    if req.map_point is not None:
        pour_path = _write_point_geojson(req.map_point.lng, req.map_point.lat)
        _inject_node_path(nodes, dataset_key="pour_points_path", path=pour_path)
    elif params.get("imported_vector_layer_id"):
        pour_path = str(resolve_imported_vector_geojson(
            str(params["imported_vector_layer_id"])
        ))
        _inject_node_path(nodes, dataset_key="pour_points_path", path=pour_path)
    elif req.geojson_path:
        _inject_node_path(nodes, dataset_key="pour_points_path",
                          path=str(_assert_path_under_allowed_roots(str(req.geojson_path))))
```

**vector_to_raster 特殊处理**：需要矢量输入而非栅格。与 `gis.buffer` 类似，从导入矢量或 geojson_path 解析：

```python
elif tool.tool_id == "gis.vector_to_raster":
    if req.geojson_path:
        primary_path = str(_assert_path_under_allowed_roots(str(req.geojson_path)))
    elif params.get("imported_vector_layer_id"):
        primary_path = str(resolve_imported_vector_geojson(
            str(params["imported_vector_layer_id"])
        ))
    if not primary_path:
        raise AnalysisRunError("矢量转栅格需要矢量输入（导入矢量层或 geojson_path）")
    _inject_node_path(nodes, dataset_key="input_path", path=primary_path)
```

### 4. 前端 InfoPanelToolsTab.vue — `Code/frontend/src/components/info-panel/InfoPanelToolsTab.vue`

#### 4a. `canRun` 计算属性扩展

将新栅格工具加入栅格要求检查：

```typescript
if (
  [
    'gis.clip', 'stats.histogram', 'gis.reclassify', 'gis.zonal_stats',
    'gis.contour', 'gis.slope_aspect', 'gis.raster_calc',
    'gis.raster_to_vector', 'gis.watershed',
  ].includes(tool.tool_id) &&
  !props.displayLayer.isImportedRaster &&
  !props.displayLayer.importedRasterOverlayLayerId
) {
  return false
}
```

**watershed 额外检查**：需要地图选点（pour point）：

```typescript
if (tool.tool_id === 'gis.watershed' && !props.selectedMapPoint) {
  return false
}
```

**vector_to_raster 检查**：需要导入矢量层：

```typescript
if (tool.tool_id === 'gis.vector_to_raster') {
  const hasVector = Boolean(
    props.displayLayer.isImported && props.displayLayer.importedVectorBackendLayerId,
  )
  if (!hasVector) return false
}
```

#### 4b. `runDisabledReason` 计算属性扩展

加入对应的禁用提示：

- watershed 无选点 → `"请先进入选择模式并在地图选点作为汇流点"`
- vector_to_raster 无矢量层 → `"需要已导入的矢量图层"`
- 其他栅格工具 → 复用现有 `"需要已导入的静态栅格图层"`

#### 4c. `onRun` 函数扩展

watershed 提交时传入 `mapPoint`（与 buffer 相同路径，runner 已支持）。
vector_to_raster 提交时传入 `imported_vector_layer_id`（与 buffer 相同路径）。

无需额外代码变更 — 现有 `runner.submitTool` 已接受 `mapPoint` 和 `params.imported_vector_layer_id`。

### 5. 前端 analysis-runner store — `Code/frontend/src/stores/analysis-runner.ts`

无需变更。`submitTool` 已通过 `params` 透传所有参数，`mapPoint` 已支持。

## 假设与决策

1. **单栅格表达式**：栅格计算器首期仅暴露单栅格（A）表达式。双栅格（A+B）需要第二个图层选择器，属于后续迭代。
2. **watershed 汇流点**：复用地图选点机制（与 buffer 工具一致），单点流域划分。多点批量划分属于后续迭代。
3. **vector_to_raster 分辨率**：默认 0.01 度（约 1km），用户可调。不自动推导目标 CRS。
4. **smoothing 参数**：contour 的 smoothing 在模块中是 boolean，但在 param_schema 中用 enum("true"/"false") 表示，因为前端表单组件不支持 boolean 类型。后端 `_inject_tool_params` 需将字符串转为 boolean。
5. **resource_profile**：watershed 标记为 heavy（DEM 像素迭代），其余为 standard。
6. **不新增 input_kind**：所有工具复用现有 raster/vector/point 三种 input_kind，不引入新类型。
7. **workflow 种子中的 path 占位符**：使用 `{DATA_ROOT}/_runtime/smoke_stub.tif` 占位，运行时由 `analysis_run_service._inject_node_path` 覆盖为实际图层路径。

## 验证步骤

### 后端验证

1. **工具目录加载**：
   ```
   Env/Python312/python.exe -c "from app.services.analysis_tool_catalog import load_analysis_tools; [print(t.tool_id, t.title) for t in load_analysis_tools()]"
   ```
   预期输出 11 个工具（原 5 + 新 6）。

2. **workflow 种子加载**：
   ```
   Env/Python312/python.exe -c "from app.services.workflow_definition_service import get_definition; [print(d) for d in ['analysis_contour','analysis_slope_aspect','analysis_raster_calc','analysis_vector_to_raster','analysis_raster_to_vector','analysis_watershed'] if get_definition(d)]"
   ```

3. **图层过滤**：
   ```
   Env/Python312/python.exe -c "from app.services.analysis_tool_catalog import list_tools_for_layer; r = list_tools_for_layer(layer_id='test', has_raster=True); [print(t.tool_id, t.enabled) for t in r.items]"
   ```
   预期：raster 工具全部 enabled，vector_to_raster disabled。

4. **现有测试不回归**：
   ```
   CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend/test_analysis_run_service.py Test/backend/test_analysis_tool_catalog.py -q
   ```

5. **新增测试**：在 `Test/backend/` 中新增 `test_analysis_tools_expanded.py`，验证：
   - `load_analysis_tools()` 返回 11 个工具
   - `list_tools_for_layer(has_raster=True)` 中 6 个新工具全部 enabled
   - `list_tools_for_layer(has_vector=True)` 中 `gis.vector_to_raster` enabled
   - `build_analysis_submit_request` 对每个新 tool_id 能正确构建 `WorkflowSubmitRequest`
   - watershed 的 pour_points 注入逻辑

### 前端验证

6. **构建**：
   ```
   cd Code/frontend && npm run build
   ```

7. **测试**：
   ```
   cd Code/frontend && npm run test
   ```

8. **手动验证**：启动系统（`start.bat`），选中一个导入的栅格图层，打开分析面板工具 Tab，确认：
   - 工具列表显示 11 个工具 chip
   - 选中"等值线"显示 interval/band/smoothing 参数表单
   - 选中"坡度坡向"显示 z_unit/algorithm 下拉
   - 选中"栅格计算器"显示 expression 文本框
   - 选中"流域分析"提示需要地图选点
   - 运行任一工具后状态正确流转（提交中→运行中→完成）
