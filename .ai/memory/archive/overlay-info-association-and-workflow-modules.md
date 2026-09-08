# Overlay 信息关联显示、工作流分析模块与时间轴联动 — 实施计划

> 用户请求："完成一些细节，包括分析框中的信息的正常关联显示，可以添加导出数据、配置拟合、均值等方法的模块在工作流模块中，允许与时间轴显示同步等等细节。"

## 摘要

本计划覆盖三块细节增强：
1. **InfoPanel 信息关联显示** — 在分析框中显示 overlay 元数据（调色板/值域/单位/当前时间）、点击地图查询 overlay 像素值、叠加图层时间与主图层联动显示。
2. **新增工作流模块** — 在 `modules/` 注册三个后端模块：`data_export`（导出 MAT/NetCDF/GeoTIFF/CSV）、`curve_fitting`（线性/多项式/指数拟合）、`statistics`（均值/中位数/标准差/分区统计）。
3. **多图层时间联动** — 多个时间序列 overlay 步进时联动；InfoPanel 显示当前联动时间。保留现有 TimelineScrubber（0-23h 天气）不变。

## 当前状态分析

### InfoPanel（`Code/frontend/src/components/InfoPanel.vue`，935 行）
- **叠加图层列表**（L155-164, L705-725）：仅显示 `name / category / availabilityState`，**缺少** palette / vmin / vmax / unit / currentTime。
- **props**（L18-28）：接收 `pointWeather` 等，**未接收** overlay 时间状态。
- **点击查询**：仅 `pointWeather`（天气图层），overlay 图层点击无任何响应。

### Overlay 模块（`Code/frontend/src/components/map/overlay-image-module.ts`，205 行）
- `OverlayTimeState`（L5-16）已含 `palette / unit / vmin / vmax / currentTime / timeList`，但仅在 MapCanvas 内部使用。
- `setOverlayTime(layerId, time)`（L179-196）单图层切换，**无联动机制**。
- `overlayTimeStates` 在 MapCanvas（L79）作为 computed，**未传出**。

### 后端 Overlay 注册（`Code/backend/app/services/overlay_registry.py`，360 行）
- `OverlaySpec` dataclass 含 `resolve_png()` / `resolve_bounds()` / `meta_dict()`，**无 `resolve_value()`**。
- 静态图层源数据路径分散（`_DEM_DIR` / `_GPCP_DIR` / `_PROJECT_OUTPUT`），未在 spec 中记录。
- `layer_router.py`（L85-107）已有 `/overlay-preview`、`/overlay-bounds`、`/overlays`，**无 `/overlay-value`**。

### 点击处理（`Code/frontend/src/views/DashboardView.vue`，L128-131）
```typescript
function handleMapPointSelect(point: { lng: number; lat: number }) {
  selectedMapPoint.value = point
  void layersStore.fetchPointWeather(point.lng, point.lat, activeLayer.value.catalogId)
}
```
仅查询天气，**未查询 overlay**。

### 工作流模块（`Code/algorithms/providers/Python/modules/`）
- 现有模块：`smap.py` / `ndvi.py` / `fy.py` / `omega.py` / `station.py` / `inversion.py` / `block_inversion.py` / `bundles.py` / `compat.py`。
- 注册模式：`@register_module_decorator(name="...", aliases=[...])` + `BaseModule` 子类，`pkgutil.iter_modules` 自动发现。
- 现有分析函数（可直接复用）：
  - `analysis/timeseries_analysis.py`：`TrendAnalysis.linear_trend()` / `mann_kendall()` / `anomaly()`，`CorrelationAnalysis.pixelwise_correlation()` / `timeseries_correlation()`。
  - `analysis/spatial_stats.py`：`ZonalStats.compute_stats()` / `compute_zonal_mean()` / `compute_landcover_stats()`。
- 现有输出：`output/__init__.py` 的 `OutputCoordinator`（`write_raster` / `write_table` / `add_mat` / `build_manifest`）。
- **无 export / fitting / statistics 模块**。

## 实施变更

### 变更 1：后端 OverlaySpec 增加源数据字段 + `resolve_value()`

**文件**：`Code/backend/app/services/overlay_registry.py`

**目的**：为 `/overlay-value` 端点提供按 (lng, lat, time) 采样像素值的能力。

**修改**：
1. 在 `OverlaySpec` dataclass 新增可选字段：
   ```python
   source_path: Path | None = None          # 静态图层源数据文件
   source_pattern: str | None = None        # 时间序列源数据文件名模板（含 {time}）
   source_variable: str | None = None       # 读取的变量名
   source_reader: str = "auto"              # auto | mat | netcdf | geotiff
   ```
2. 新增方法 `resolve_value(self, lng: float, lat: float, time: str | None = None) -> dict`：
   - 解析源文件路径（静态用 `source_path`，时间序列用 `source_pattern.format(time=time)`）。
   - 调用 `universal_reader.read_data(path, variable=source_variable)`（已有模块，支持 MAT v7.3 / NetCDF / GeoTIFF / HDF5）。
   - 读取 bounds（复用 `resolve_bounds()` 的 JSON），将 (lng, lat) 映射到数组索引（最近邻）。
   - 返回 `{"value": float, "unit": self.unit, "layer_id": self.layer_id, "time": time, "lng": lng, "lat": lat}`。
   - 值为 NaN / nodata 时 `value=None`。
3. 在 8 个 `register_overlay(...)` 调用中补充源数据字段：
   - `dem-etopo`：`source_path=_DEM_DIR / "ETOPO_2022_v1_60s_bed.nc"`, `source_variable="z"`, `source_reader="netcdf"`
   - `landcover-cn` / `hfp-cn` / `aridity-cn`：指向 `Tools/export_overlay_assets.py` 导出时使用的源 GeoTIFF / npz 路径（从该脚本读取实际路径）。
   - `omega-output`：`source_path=_PROJECT_OUTPUT / "stage4_cross_analysis" / "sm_ts_mean.mat"`, `source_variable="sm_ts_mean"`
   - `smap-sm-ts`：`source_pattern=str(_PROJECT_OUTPUT / "stage1_smap_mat" / "SMAP_L3_SM_P_{time}_R*.mat")`, `source_variable="sm_dca"`, `source_reader="mat"`（用 glob 匹配 R 编号）
   - `gpcp-precip-ts`：`source_pattern=str(_GPCP_DIR / "GPCPMON_L3_{time}_V3.2.nc4")`, `source_variable="precip"`, `source_reader="netcdf"`
   - `lab-output`：复用 `omega-output` 的源

### 变更 2：新增 `/overlay-value` 端点

**文件**：`Code/backend/app/api/routers/layer_router.py`

**修改**：在 L107 后新增端点：
```python
@router.get("/overlay-value/{layer_id}", tags=["overlay"])
def get_overlay_value(
    layer_id: str,
    lng: float = Query(...),
    lat: float = Query(...),
    time: str | None = Query(default=None),
) -> dict[str, Any]:
    """查询 overlay 图层在指定点的像素值。"""
    spec = get_overlay_spec(layer_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No overlay for layer: {layer_id}")
    return spec.resolve_value(lng, lat, time)
```

**依赖**：`universal_reader` 模块（位于 `Code/algorithms/providers/Python/data_access/universal_reader.py`）。后端需能 import 此模块；若路径不在 sys.path，在 `overlay_registry.py` 顶部 `sys.path.insert` 加入。

### 变更 3：InfoPanel 增强 — 显示 overlay 元数据与像素值

**文件**：`Code/frontend/src/components/InfoPanel.vue`

**修改**：
1. **新增 props**（L18-28 后追加）：
   ```typescript
   overlayTimeStates?: OverlayTimeState[]  // 从 MapCanvas 透传
   overlayPointValues?: OverlayPointValue[]  // 点击地图查询到的 overlay 像素值
   ```
   新增类型定义（在同文件或 `stores/layers/types.ts`）：
   ```typescript
   interface OverlayPointValue {
     layerId: string
     layerName: string
     value: number | null
     unit: string
     time: string | null
     lng: number
     lat: number
   }
   ```
2. **增强 overlayLayers computed**（L155-164）：将 `overlayTimeStates` 与 `activeLayersDisplay` join，补充 `palette / vmin / vmax / unit / currentTime` 字段。
3. **扩展叠加图层列表模板**（L705-725）：在每个 `<li>` 中追加：
   - 调色板色带（CSS 渐变条，根据 palette 名称映射）
   - 值域标签 `{{ layer.vmin }} ~ {{ layer.vmax }} {{ layer.unit }}`
   - 当前时间标签（仅时间序列图层显示 `{{ formatTime(layer.currentTime) }}`）
4. **新增 overlay 像素值查询结果区**（在叠加图层列表后插入新 `<section>`）：
   - 当 `overlayPointValues.length > 0` 时显示
   - 每条记录显示：图层名 / 值（或 "无数据"）/ 单位 / 时间 / 坐标
5. **顶部摘要联动**（L405-414 meta-list）：若 `displayLayer` 是时间序列 overlay，在 meta-list 中追加 `当前时间: {{ formatTime(displayLayer.currentTime) }}`。

### 变更 4：MapCanvas → DashboardView → InfoPanel 数据透传

**文件**：`Code/frontend/src/components/MapCanvas.vue`

**修改**：
1. 新增 `defineExpose` 项：`getOverlayTimeStates: () => overlayTimeStates.value`
2. 或者更优：通过 emit 事件 `@overlay-time-update` 把 `overlayTimeStates` 传出（避免破坏现有 expose bridge）。

**文件**：`Code/frontend/src/views/DashboardView.vue`

**修改**：
1. 新增响应式状态：
   ```typescript
   const overlayTimeStates = ref<OverlayTimeState[]>([])
   const overlayPointValues = ref<OverlayPointValue[]>([])
   ```
2. MapCanvas 事件绑定新增 `@overlay-time-update="overlayTimeStates = $event"`。
3. 扩展 `handleMapPointSelect`（L128-131）：
   ```typescript
   async function handleMapPointSelect(point: { lng: number; lat: number }) {
     selectedMapPoint.value = point
     void layersStore.fetchPointWeather(point.lng, point.lat, activeLayer.value.catalogId)
     // 查询所有可见的 overlay 图层像素值
     const visibleOverlayIds = overlayTimeStates.value.map(s => s.layerId)
     const results = await Promise.all(
       visibleOverlayIds.map(id => fetchOverlayValue(id, point.lng, point.lat))
     )
     overlayPointValues.value = results.filter(Boolean)
   }
   ```
4. 新增 `fetchOverlayValue` 辅助函数：`GET /overlay-value/{id}?lng=...&lat=...&time=...`（time 从 overlayTimeStates 取当前时间）。
5. InfoPanel 渲染（template 中）传入 `:overlay-time-states="overlayTimeStates"` `:overlay-point-values="overlayPointValues"`。

### 变更 5：多图层时间联动

**文件**：`Code/frontend/src/components/map/overlay-image-module.ts`

**修改**：
1. 新增内部状态 `linkTimeEnabled = ref(false)`。
2. 新增方法 `setLinkTime(enabled: boolean)`：切换联动开关。
3. 修改 `setOverlayTime(layerId, time)`（L179-196）：若 `linkTimeEnabled.value` 为 true，在更新当前图层后，遍历其他 time-series 图层，找到与 `time` 最接近的时间标签（按字符串排序或索引对齐），调用自身递归切换（避免无限循环：仅当目标 time 与当前不同时才切换）。
4. `OverlayImageModule` 接口（L18-29）新增 `linkTimeEnabled: Ref<boolean>` 和 `setLinkTime`。

**文件**：`Code/frontend/src/components/MapCanvas.vue`

**修改**：
1. 新增 `linkTimeEnabled` computed（从 overlayImageModule 读取）。
2. 在时间控制 widget 旁新增 "🔗 联动" 切换按钮（仅当 `activeTimeSeriesOverlays.length > 1` 时显示）。
3. `overlayStepTime`（L84-93）：联动开启时，调用 `setOverlayTime` 后会自动联动其他图层。

### 变更 6：新增工作流模块 — `data_export`

**新文件**：`Code/algorithms/providers/Python/modules/export.py`

**目的**：将上游产物（manifest products / numpy 数组 / 文件路径）导出为 MAT / NetCDF / GeoTIFF / CSV。

**实现**：
```python
@register_module_decorator(name="data_export", aliases=["data_export_pipeline"])
class DataExportModule(BaseModule):
    name = "data_export"
    description = "Export upstream products to MAT/NetCDF/GeoTIFF/CSV formats."
    input_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest", required=False),
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
    ]
    output_ports = [PortSpec(name="manifest", kind="artifact", data_class="product_manifest")]

    def execute(self, inputs, params, ctx):
        # 1. 读取上游 manifest（若有）或 datasource_selection 中的文件路径
        # 2. 根据 algorithm_params["format"] (mat|netcdf|geotiff|csv) 调用对应写出器
        # 3. 使用 OutputCoordinator 统一输出到 output_dir
        # 4. 返回新 manifest
```
- 复用 `OutputCoordinator.write_raster` / `add_mat` / `write_table`。
- 复用 `data_access.universal_reader.read_data` 读取源文件。
- 支持参数：`format`（必填）、`variables`（可选，逗号分隔）、`output_dir`（可选，默认 `ctx.workspace / "products" / "export"`）。

### 变更 7：新增工作流模块 — `curve_fitting`

**新文件**：`Code/algorithms/providers/Python/modules/fitting.py`

**目的**：对时间序列数据执行线性 / 多项式 / 指数拟合。

**实现**：
```python
@register_module_decorator(name="curve_fitting", aliases=["curve_fitting_pipeline"])
class CurveFittingModule(BaseModule):
    name = "curve_fitting"
    description = "Curve fitting (linear / polynomial / exponential) on time-series data."
    input_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest", required=False),
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
    ]
    output_ports = [PortSpec(name="manifest", kind="artifact", data_class="product_manifest")]

    def execute(self, inputs, params, ctx):
        # 1. 读取输入数据（manifest 中的产物路径 或 datasource_selection）
        # 2. 根据 algorithm_params["method"] 调用:
        #    - "linear": TrendAnalysis.linear_trend()  (复用现有)
        #    - "polynomial": numpy.polyfit + poly1d
        #    - "exponential": scipy.optimize.curve_fit 拟合 y = a*exp(b*x)
        # 3. 输出拟合参数 + 拟合曲线 MAT/CSV
        # 4. 返回 manifest
```
- 复用 `TrendAnalysis.linear_trend()`（`analysis/timeseries_analysis.py`）。
- 多项式与指数拟合直接使用 `numpy.polyfit` / `scipy.optimize.curve_fit`。
- 支持参数：`method`（linear|polynomial|exponential）、`degree`（多项式阶数，默认 2）、`variable`（待拟合变量名）。

### 变更 8：新增工作流模块 — `statistics`

**新文件**：`Code/algorithms/providers/Python/modules/statistics.py`

**目的**：计算均值 / 中位数 / 标准差 / 分区统计。

**实现**：
```python
@register_module_decorator(name="statistics", aliases=["statistics_pipeline"])
class StatisticsModule(BaseModule):
    name = "statistics"
    description = "Compute mean / median / std / zonal statistics on raster data."
    input_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest", required=False),
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
    ]
    output_ports = [PortSpec(name="manifest", kind="artifact", data_class="product_manifest")]

    def execute(self, inputs, params, ctx):
        # 1. 读取输入数据
        # 2. 根据 algorithm_params["mode"] 调用:
        #    - "global": ZonalStats.compute_stats(data)  (复用现有)
        #    - "zonal": ZonalStats.compute_zonal_mean(data, zones)
        #    - "landcover": ZonalStats.compute_landcover_stats(data, landcover)
        #    - "timeseries": 对 3D 数据逐时间片计算均值
        # 3. 输出统计结果 MAT/CSV
        # 4. 返回 manifest
```
- 复用 `ZonalStats.compute_stats()` / `compute_zonal_mean()` / `compute_landcover_stats()`（`analysis/spatial_stats.py`）。
- 支持参数：`mode`（global|zonal|landcover|timeseries）、`zones_source`（分区数据源）、`variable`。

## 假设与决策

1. **`/overlay-value` 实现**：优先读取源数据文件（NetCDF/MAT/GeoTIFF）以获取精确值；若源文件不可用则降级返回 404。不使用 PNG 像素反推（精度不足）。
2. **universal_reader 复用**：后端 `overlay_registry.py` 通过 `sys.path.insert` 引入 `Code/algorithms/providers/Python` 目录以使用 `data_access.universal_reader`。这与 `timeseries_analysis.py` 的独立运行模式（L8-9）一致。
3. **联动策略**：多图层联动采用 "索引对齐 + 字符串接近匹配" 策略 — 当图层 A 切换到 time[i] 时，图层 B 切换到其 timeList 中与 A 的新时间最接近的标签（按字典序）。若某图层无匹配则保持不变。
4. **模块输入约定**：三个新模块均接受可选的 `manifest` 输入端口（来自上游模块产物）和 `datasource_selection`（独立数据源）。若两者都缺失则报错。
5. **不新增前端配置 UI**：用户确认模块仅通过 `/workflow-runs` API 触发，前端不新增参数表单。InfoPanel 的导出按钮（若添加）仅作为快捷入口，调用通用 `data_export` 模块。
6. **TimelineScrubber 不变**：保留现有 0-23h 天气时间轴；overlay 时间联动独立于天气时间轴。
7. **模块自动发现**：三个新 `.py` 文件放入 `modules/` 目录后，`registry.py` 的 `pkgutil.iter_modules`（L29）会自动加载，无需修改 `registry.py`。

## 验证步骤

### 后端验证
1. 重启后端服务（`python launch.py stop && python launch.py start`）。
2. `GET /overlays` 返回 8 个 layer_id。
3. `GET /overlay-value/dem-etopo?lng=105&lat=35` 返回 `{"value": <高程值>, "unit": "m", ...}`。
4. `GET /overlay-value/smap-sm-ts?lng=105&lat=35&time=20230101` 返回 SMAP 土壤湿度值。
5. `GET /modules`（或等价端点）返回包含 `data_export` / `curve_fitting` / `statistics` 的模块列表。
6. 通过 `/workflow-runs` 提交 `data_export` 任务（指定一个已有 MAT 文件作为输入），验证输出 MAT/CSV 文件生成。

### 前端验证
1. 启动前端 dev server。
2. 打开 Dashboard，激活 SMAP 时间序列 overlay + GPCP 时间序列 overlay。
3. **InfoPanel 叠加图层列表**：每个图层显示调色板色带、值域（0.0 ~ 0.5 m³/m³）、当前时间标签。
4. **点击地图**：InfoPanel 新增 "Overlay 像素值" 区段，显示两个图层在该点的值。
5. **联动开关**：点击 "🔗 联动" 按钮，步进 SMAP 时间，GPCP 时间自动跟随到最接近的月份。
6. **InfoPanel 顶部摘要**：当选中 SMAP 图层时，meta-list 显示 "当前时间: 2023-01-01"。
7. 浏览器 Console 无报错，无失败网络请求。

### 工作流模块验证
1. 在 Python provider 独立测试三个模块的 `execute()`：
   - `data_export`：读取一个 SMAP MAT 文件，导出为 CSV，验证 CSV 行数合理。
   - `curve_fitting`：对 ERA5 温度时间序列做线性拟合，验证 slope / intercept 非NaN。
   - `statistics`：对 SMAP 土壤湿度做 global 统计，验证 mean / std / median 字段存在。
2. 通过 `/workflow-runs` 端到端提交，验证 manifest 生成、产物文件落盘。

## 实施顺序

1. **后端**：`overlay_registry.py`（OverlaySpec 扩展 + resolve_value）→ `layer_router.py`（/overlay-value 端点）。
2. **后端模块**：`modules/export.py` → `modules/fitting.py` → `modules/statistics.py`。
3. **前端 overlay 联动**：`overlay-image-module.ts`（联动逻辑）→ `MapCanvas.vue`（联动按钮 + 事件透传）。
4. **前端 InfoPanel**：`InfoPanel.vue`（props + 元数据显示 + 像素值区段）→ `DashboardView.vue`（状态 + fetchOverlayValue + 透传）。
5. **验证**：按上述验证步骤逐项检查。
