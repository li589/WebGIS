"""统一节点模板注册表

汇聚天气引擎、Python Provider、GEE 三个引擎的节点模板，
为前端 ComfyUI 风格编辑器提供可拖拽的节点目录。
"""
from __future__ import annotations

from typing import Any


# ─── 端口规格工具 ────────────────────────────────────────────────────────────
def _port(name: str, kind: str, required: bool = True, description: str = "") -> dict[str, Any]:
    return {"name": name, "type": kind, "required": required, "description": description}


def _param(
    key: str,
    kind: str = "string",
    default: Any = None,
    description: str = "",
    options: list[str] | None = None,
    unit: str | None = None,
    min_val: float | None = None,
    max_val: float | None = None,
    step: float | None = None,
) -> dict[str, Any]:
    """构造参数描述字典。

    Args:
        key: 参数键名
        kind: 参数类型 (string/number/boolean/enum/array)
        default: 默认值
        description: 人类可读描述
        options: enum 类型的可选值列表
        unit: 物理单位 (如 "GHz"、"度"、"米"、"天")
        min_val: 数值下限
        max_val: 数值上限
        step: 数值步长
    """
    p: dict[str, Any] = {"key": key, "type": kind, "default": default, "description": description}
    if options:
        p["options"] = options
    if unit:
        p["unit"] = unit
    if min_val is not None:
        p["min"] = min_val
    if max_val is not None:
        p["max"] = max_val
    if step is not None:
        p["step"] = step
    return p


# ─── 节点模板定义 ────────────────────────────────────────────────────────────
# 每个模板包含: type, engine, category, title, description, inputs, outputs, params, node_class
# 端口类型系统:
#   data            通用数据流（向后兼容）
#   data:mat        .mat 文件（Python Provider 输出）
#   data:raster     栅格数据（GEE 影像、天气网格）
#   data:geojson    GeoJSON 矢量数据
#   data:timeseries 时间序列 .mat
#   data:source     数据源引用（路径/URI）
#   value:number    数值
#   value:string    字符串
#   value:time_range 时间范围
#   geometry:bbox   空间范围
# 连接规则: 相同类型允许; data <-> data:* 允许; data:* 之间禁止

_NODE_TEMPLATES: list[dict[str, Any]] = [

    # ═══ 通用节点 - 数据输入 ════════════════════════════════════════════════════
    {
        "type": "data/source",
        "engine": "common",
        "category": "数据输入",
        "title": "数据源",
        "description": "外部数据源输入节点，可配置数据集键和路径。",
        "inputs": [],
        "outputs": [
            _port("data", "data:source", description="数据源输出"),
        ],
        "params": [
            _param("dataset_key", "string", description="数据集标识符（如 SMAP_SPL3SMP_E）"),
            _param("path", "string", description="数据路径或 URI"),
            _param("pattern", "string", default="*", description="文件匹配模式"),
        ],
        "node_class": "data_source",
    },
    {
        "type": "data/time_range",
        "engine": "common",
        "category": "数据输入",
        "title": "时间范围",
        "description": "时间范围输入节点，定义工作流的起止时间。",
        "inputs": [],
        "outputs": [
            _port("time_range", "value:time_range", description="时间范围对象 {start_at, end_at, granularity}"),
        ],
        "params": [
            _param("start_at", "string", default="", description="起始时间 ISO 8601（如 2023-01-01）"),
            _param("end_at", "string", default="", description="结束时间 ISO 8601（如 2023-12-31）"),
            _param("granularity", "string", default="day", options=["hour", "day", "month"], description="时间粒度"),
        ],
        "node_class": "time_range",
    },
    {
        "type": "data/bbox",
        "engine": "common",
        "category": "数据输入",
        "title": "空间范围",
        "description": "空间范围（bbox）输入节点。",
        "inputs": [],
        "outputs": [
            _port("bbox", "geometry:bbox", description="空间范围 {west, south, east, north}"),
        ],
        "params": [
            _param("west", "number", default=0.0, description="西边界经度", unit="度", min_val=-180, max_val=180, step=0.01),
            _param("south", "number", default=0.0, description="南边界纬度", unit="度", min_val=-90, max_val=90, step=0.01),
            _param("east", "number", default=0.0, description="东边界经度", unit="度", min_val=-180, max_val=180, step=0.01),
            _param("north", "number", default=0.0, description="北边界纬度", unit="度", min_val=-90, max_val=90, step=0.01),
        ],
        "node_class": "bbox",
    },
    {
        "type": "output/map_layer",
        "engine": "common",
        "category": "输出",
        "title": "地图图层输出",
        "description": "将上游数据输出为地图图层。",
        "inputs": [
            _port("data", "data", description="要输出的图层数据"),
        ],
        "outputs": [],
        "params": [
            _param("layer_id", "string", description="目标图层标识符"),
            _param("display_name", "string", description="图层显示名称"),
        ],
        "node_class": "output_map_layer",
    },
    {
        "type": "output/file",
        "engine": "common",
        "category": "输出",
        "title": "文件输出",
        "description": "将上游数据输出为文件。",
        "inputs": [
            _port("data", "data", description="要输出的数据"),
        ],
        "outputs": [],
        "params": [
            _param("format", "string", default="mat", options=["mat", "geojson", "geotiff", "json", "csv"], description="输出文件格式"),
            _param("filename", "string", description="输出文件名"),
        ],
        "node_class": "output_file",
    },

    # ═══ 数据预处理模块 ════════════════════════════════════════════════════════
    {
        "type": "preprocess/reproject",
        "engine": "common",
        "category": "数据预处理",
        "title": "重投影",
        "description": "将栅格数据重投影到目标坐标系。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格"),
            _port("bbox", "geometry:bbox", required=False, description="可选空间范围"),
        ],
        "outputs": [
            _port("raster", "data:raster", description="重投影后栅格"),
        ],
        "params": [
            _param("target_crs", "string", default="EPSG:4326", description="目标坐标系"),
            _param("resampling", "string", default="nearest", options=["nearest", "bilinear", "cubic"], description="重采样方法"),
        ],
        "node_class": "preprocess_reproject",
    },
    {
        "type": "preprocess/resample",
        "engine": "common",
        "category": "数据预处理",
        "title": "重采样",
        "description": "改变栅格数据的空间分辨率。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格"),
        ],
        "outputs": [
            _port("raster", "data:raster", description="重采样后栅格"),
        ],
        "params": [
            _param("target_resolution", "number", default=1000, description="目标分辨率", unit="米", min_val=1, max_val=100000, step=1),
            _param("resampling", "string", default="nearest", options=["nearest", "bilinear", "cubic"], description="重采样方法"),
            _param("unit", "string", default="meters", options=["meters", "degrees"], description="分辨率单位"),
        ],
        "node_class": "preprocess_resample",
    },
    {
        "type": "preprocess/format_convert",
        "engine": "common",
        "category": "数据预处理",
        "title": "格式转换",
        "description": "在不同数据格式之间转换。",
        "inputs": [
            _port("data", "data", description="输入数据"),
        ],
        "outputs": [
            _port("data", "data", description="转换后数据"),
        ],
        "params": [
            _param("input_format", "string", default="auto", options=["auto", "netcdf", "hdf5", "geotiff", "mat"], description="输入格式（auto 自动检测）"),
            _param("output_format", "string", default="geotiff", options=["geotiff", "cog", "mat", "json"], description="输出格式"),
        ],
        "node_class": "preprocess_format_convert",
    },
    {
        "type": "preprocess/clip",
        "engine": "common",
        "category": "数据预处理",
        "title": "裁剪",
        "description": "按空间范围裁剪栅格数据。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格"),
            _port("bbox", "geometry:bbox", description="裁剪范围"),
        ],
        "outputs": [
            _port("raster", "data:raster", description="裁剪后栅格"),
        ],
        "params": [
            _param("buffer_meters", "number", default=0, description="缓冲区大小", unit="米", min_val=0, max_val=10000, step=10),
        ],
        "node_class": "preprocess_clip",
    },
    {
        "type": "preprocess/mask",
        "engine": "common",
        "category": "数据预处理",
        "title": "掩膜",
        "description": "用掩膜栅格遮蔽输入栅格的像元。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格"),
            _port("mask", "data:raster", description="掩膜栅格"),
        ],
        "outputs": [
            _port("raster", "data:raster", description="掩膜后栅格"),
        ],
        "params": [
            _param("mask_value", "number", default=0, description="掩膜值（等于此值的像元被遮蔽）"),
            _param("invert", "boolean", default=False, description="是否反转掩膜"),
        ],
        "node_class": "preprocess_mask",
    },

    # ═══ 统计分析模块 ══════════════════════════════════════════════════════════
    {
        "type": "stats/spatial_mean",
        "engine": "common",
        "category": "统计分析",
        "title": "空间均值",
        "description": "计算栅格数据的空间统计量。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格"),
        ],
        "outputs": [
            _port("value", "value:number", description="统计值"),
        ],
        "params": [
            _param("statistic", "string", default="mean", options=["mean", "median", "min", "max", "std"], description="统计量类型"),
            _param("band", "number", default=0, description="波段索引", min_val=0, max_val=100, step=1),
        ],
        "node_class": "stats_spatial_mean",
    },
    {
        "type": "stats/temporal_trend",
        "engine": "common",
        "category": "统计分析",
        "title": "时间趋势分析",
        "description": "分析时间序列数据的趋势（线性/Theil-Sen/Mann-Kendall）。",
        "inputs": [
            _port("timeseries", "data:timeseries", description="时间序列数据"),
        ],
        "outputs": [
            _port("result", "data:geojson", description="趋势分析结果 GeoJSON"),
        ],
        "params": [
            _param("trend_method", "string", default="linear", options=["linear", "theil_sen", "mann_kendall"], description="趋势分析方法"),
            _param("confidence_level", "number", default=0.95, description="置信水平", min_val=0.5, max_val=0.999, step=0.01),
        ],
        "node_class": "stats_temporal_trend",
    },
    {
        "type": "stats/anomaly_detect",
        "engine": "common",
        "category": "统计分析",
        "title": "异常检测",
        "description": "检测时间序列中的异常值（Z-score/IQR/DBSCAN）。",
        "inputs": [
            _port("timeseries", "data:timeseries", description="时间序列数据"),
        ],
        "outputs": [
            _port("anomalies", "data:geojson", description="异常点 GeoJSON"),
        ],
        "params": [
            _param("method", "string", default="zscore", options=["zscore", "iqr", "dbscan"], description="异常检测方法"),
            _param("threshold", "number", default=2.0, description="阈值（Z-score 标准差倍数）", min_val=1.0, max_val=5.0, step=0.1),
        ],
        "node_class": "stats_anomaly_detect",
    },
    {
        "type": "stats/correlation",
        "engine": "common",
        "category": "统计分析",
        "title": "相关性分析",
        "description": "计算两个时间序列的相关系数（Pearson/Spearman/Kendall）。",
        "inputs": [
            _port("x", "data:timeseries", description="X 序列"),
            _port("y", "data:timeseries", description="Y 序列"),
        ],
        "outputs": [
            _port("coefficient", "value:number", description="相关系数 [-1, 1]"),
        ],
        "params": [
            _param("method", "string", default="pearson", options=["pearson", "spearman", "kendall"], description="相关系数方法"),
            _param("lag_days", "number", default=0, description="滞后天数", unit="天", min_val=0, max_val=365, step=1),
        ],
        "node_class": "stats_correlation",
    },
    {
        "type": "stats/histogram",
        "engine": "common",
        "category": "统计分析",
        "title": "直方图统计",
        "description": "计算栅格数据的直方图分布。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格"),
        ],
        "outputs": [
            _port("histogram", "data:geojson", description="直方图 GeoJSON"),
        ],
        "params": [
            _param("bins", "number", default=50, description="分箱数量", min_val=5, max_val=500, step=1),
            _param("band", "number", default=0, description="波段索引", min_val=0, max_val=100, step=1),
            _param("density", "boolean", default=False, description="是否归一化为概率密度"),
        ],
        "node_class": "stats_histogram",
    },

    # ═══ 数据融合与可视化模块 ═══════════════════════════════════════════════════
    {
        "type": "fusion/spatial_interpolate",
        "engine": "common",
        "category": "数据融合",
        "title": "空间插值",
        "description": "将离散点数据插值为栅格（IDW/克里金/最近邻）。",
        "inputs": [
            _port("points", "data:geojson", description="离散点 GeoJSON"),
            _port("bbox", "geometry:bbox", description="插值范围"),
        ],
        "outputs": [
            _port("raster", "data:raster", description="插值结果栅格"),
        ],
        "params": [
            _param("method", "string", default="idw", options=["idw", "kriging", "nearest"], description="插值方法"),
            _param("power", "number", default=2.0, description="IDW 幂参数", min_val=1.0, max_val=6.0, step=0.5),
            _param("resolution", "number", default=1000, description="输出分辨率", unit="米", min_val=10, max_val=50000, step=10),
        ],
        "node_class": "fusion_spatial_interpolate",
    },
    {
        "type": "fusion/multi_source_merge",
        "engine": "common",
        "category": "数据融合",
        "title": "多源融合",
        "description": "融合两个栅格数据源（加权/PCA/贝叶斯）。",
        "inputs": [
            _port("primary", "data:raster", description="主数据源"),
            _port("secondary", "data:raster", description="辅助数据源"),
        ],
        "outputs": [
            _port("merged", "data:raster", description="融合结果"),
        ],
        "params": [
            _param("method", "string", default="weighted", options=["weighted", "pca", "bayesian"], description="融合方法"),
            _param("weight_primary", "number", default=0.6, description="主数据源权重", min_val=0.0, max_val=1.0, step=0.05),
        ],
        "node_class": "fusion_multi_source_merge",
    },
    {
        "type": "viz/chart_generate",
        "engine": "common",
        "category": "可视化",
        "title": "图表生成",
        "description": "根据数据生成图表（折线/柱状/散点/热力/箱线）。",
        "inputs": [
            _port("data", "data", description="输入数据"),
        ],
        "outputs": [
            _port("chart", "value:string", description="Base64 编码的 PNG 图像"),
        ],
        "params": [
            _param("chart_type", "string", default="line", options=["line", "bar", "scatter", "heatmap", "boxplot"], description="图表类型"),
            _param("title", "string", default="", description="图表标题"),
            _param("x_label", "string", default="", description="X 轴标签"),
            _param("y_label", "string", default="", description="Y 轴标签"),
            _param("width", "number", default=800, description="图表宽度", unit="像素", min_val=200, max_val=4000, step=50),
            _param("height", "number", default=600, description="图表高度", unit="像素", min_val=200, max_val=4000, step=50),
        ],
        "node_class": "viz_chart_generate",
    },
    {
        "type": "viz/report_export",
        "engine": "common",
        "category": "可视化",
        "title": "报表导出",
        "description": "将分析结果导出为报表（PDF/HTML/DOCX/Markdown）。",
        "inputs": [
            _port("data", "data", description="分析结果数据"),
        ],
        "outputs": [
            _port("filepath", "value:string", description="输出文件路径"),
        ],
        "params": [
            _param("format", "string", default="html", options=["pdf", "html", "docx", "markdown"], description="报表格式"),
            _param("template", "string", default="default", description="报表模板名称"),
            _param("include_charts", "boolean", default=True, description="是否包含图表"),
        ],
        "node_class": "viz_report_export",
    },
    {
        "type": "viz/statistics_summary",
        "engine": "common",
        "category": "可视化",
        "title": "统计摘要",
        "description": "生成数据统计摘要（均值/标准差/分位数）。",
        "inputs": [
            _port("data", "data", description="输入数据"),
        ],
        "outputs": [
            _port("summary", "data:geojson", description="统计摘要 GeoJSON"),
        ],
        "params": [
            _param("include_mean", "boolean", default=True, description="包含均值"),
            _param("include_std", "boolean", default=True, description="包含标准差"),
            _param("include_percentiles", "boolean", default=True, description="包含分位数"),
            _param("percentile_list", "string", default="25,50,75", description="分位数列表（逗号分隔）"),
        ],
        "node_class": "viz_statistics_summary",
    },

    # ═══ 天气引擎节点 ══════════════════════════════════════════════════════════
    {
        "type": "weather/forecast_fetch",
        "engine": "weather",
        "category": "天气-数据抓取",
        "title": "预报数据抓取",
        "description": "经天气引擎 Provider（Open-Meteo / WeatherAPI / OpenWeather 等）抓取预报数据。",
        "inputs": [
            _port("latitude", "value:number", description="中心纬度"),
            _port("longitude", "value:number", description="中心经度"),
            _port("layer_id", "value:string", description="天气图层标识"),
            _port("model", "value:string", required=False, description="气象模型，可选"),
            _port("forecast_hours", "value:number", required=False, description="预报小时数，可选"),
            _port("provider_id", "value:string", required=False, description="钉选天气源 Provider ID，可选"),
        ],
        "outputs": [
            _port("forecast", "data", description="原始预报数据"),
            _port("cache_status", "value:string", description="缓存状态 (hit/miss)"),
            _port("layer_spec", "data", description="图层规格字典"),
            _port("provider_id", "value:string", description="实际使用的天气源"),
        ],
        "params": [
            _param("default_model", "string", default="icon_seamless", description="默认气象模型"),
            _param("provider_id", "string", default="", description="钉选天气源 Provider ID（空=自动）"),
        ],
        "node_class": "weather_forecast_fetch",
    },
    {
        "type": "weather/grid_fetch",
        "engine": "weather",
        "category": "天气-数据抓取",
        "title": "网格数据抓取",
        "description": "经天气引擎 Provider 抓取网格化天气数据用于渲染。",
        "inputs": [
            _port("layer_id", "value:string", description="天气图层标识"),
            _port("latitude", "value:number", description="中心纬度"),
            _port("longitude", "value:number", description="中心经度"),
            _port("forecast_hours", "value:number", required=False, description="预报小时数"),
            _port("bbox", "geometry:bbox", required=False, description="空间范围"),
            _port("provider_id", "value:string", required=False, description="钉选天气源 Provider ID，可选"),
        ],
        "outputs": [
            _port("grid_data", "data:raster", description="网格化天气数据"),
            _port("hour", "value:number", description="当前小时"),
            _port("provider_id", "value:string", description="实际使用的天气源"),
        ],
        "params": [
            _param("provider_id", "string", default="", description="钉选天气源 Provider ID（空=自动）"),
        ],
        "node_class": "weather_grid_fetch",
    },
    {
        "type": "weather/wind_field_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "风场渲染",
        "description": "基于预报数据生成风场矢量 GeoJSON，支持粒子流动画。",
        "inputs": [
            _port("weather_point", "data", required=False, description="上游点位数据，未提供时自行获取"),
            _port("latitude", "value:number", description="中心纬度"),
            _port("longitude", "value:number", description="中心经度"),
            _port("grid_data", "data:raster", required=False, description="上游网格数据（优先）"),
            _port("layer_id", "value:string", required=False, description="目标图层标识，默认 wind-field"),
            _port("viewport_bbox", "geometry:bbox", required=False, description="前端视口 bbox"),
            _port("bbox", "geometry:bbox", required=False, description="空间过滤 bbox"),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="风场矢量 GeoJSON FeatureCollection"),
        ],
        "params": [],
        "node_class": "weather_wind_field",
    },
    {
        "type": "weather/temperature_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "温度渲染",
        "description": "生成温度栅格图层。",
        "inputs": [
            _port("grid_data", "data:raster", required=False, description="上游网格数据"),
            _port("latitude", "value:number", description="中心纬度"),
            _port("longitude", "value:number", description="中心经度"),
            _port("layer_id", "value:string", required=False, description="目标图层标识"),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="温度栅格 GeoJSON"),
        ],
        "params": [],
        "node_class": "weather_temperature_grid_render",
    },
    {
        "type": "weather/precipitation_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "降水渲染",
        "description": "生成降水栅格图层。",
        "inputs": [
            _port("grid_data", "data:raster", required=False, description="上游网格数据"),
            _port("latitude", "value:number", description="中心纬度"),
            _port("longitude", "value:number", description="中心经度"),
            _port("layer_id", "value:string", required=False, description="目标图层标识"),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="降水栅格 GeoJSON"),
        ],
        "params": [],
        "node_class": "weather_precipitation_grid_render",
    },
    {
        "type": "weather/humidity_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "湿度渲染",
        "description": "生成湿度栅格图层。",
        "inputs": [
            _port("grid_data", "data:raster", required=False, description="上游网格数据"),
            _port("latitude", "value:number", description="中心纬度"),
            _port("longitude", "value:number", description="中心经度"),
            _port("layer_id", "value:string", required=False, description="目标图层标识"),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="湿度栅格 GeoJSON"),
        ],
        "params": [],
        "node_class": "weather_humidity_grid_render",
    },
    {
        "type": "weather/pressure_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "气压渲染",
        "description": "生成气压栅格图层。",
        "inputs": [
            _port("grid_data", "data:raster", required=False, description="上游网格数据"),
            _port("latitude", "value:number", description="中心纬度"),
            _port("longitude", "value:number", description="中心经度"),
            _port("layer_id", "value:string", required=False, description="目标图层标识"),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="气压栅格 GeoJSON"),
        ],
        "params": [],
        "node_class": "weather_pressure_grid_render",
    },
    {
        "type": "weather/visibility_render",
        "engine": "weather",
        "category": "天气-渲染",
        "title": "能见度渲染",
        "description": "生成能见度栅格图层。",
        "inputs": [
            _port("grid_data", "data:raster", required=False, description="上游网格数据"),
            _port("latitude", "value:number", description="中心纬度"),
            _port("longitude", "value:number", description="中心经度"),
            _port("layer_id", "value:string", required=False, description="目标图层标识"),
        ],
        "outputs": [
            _port("geojson", "data:geojson", description="能见度栅格 GeoJSON"),
        ],
        "params": [],
        "node_class": "weather_visibility_grid_render",
    },
    {
        "type": "weather/tile_render",
        "engine": "weather",
        "category": "天气-瓦片",
        "title": "天气瓦片渲染",
        "description": "生成天气瓦片用于前端地图显示。",
        "inputs": [
            _port("grid_data", "data:raster", description="上游网格数据"),
            _port("layer_id", "value:string", description="目标图层标识"),
            _port("z", "value:number", description="缩放级别"),
            _port("x", "value:number", description="瓦片 X 坐标"),
            _port("y", "value:number", description="瓦片 Y 坐标"),
        ],
        "outputs": [
            _port("tile", "data", description="渲染后的瓦片数据"),
        ],
        "params": [],
        "node_class": "weather_tile_render",
    },
    {
        "type": "weather/point_parse",
        "engine": "weather",
        "category": "天气-处理",
        "title": "点位解析",
        "description": "解析天气点位查询结果。",
        "inputs": [
            _port("latitude", "value:number", description="纬度"),
            _port("longitude", "value:number", description="经度"),
            _port("layer_id", "value:string", description="天气图层标识"),
        ],
        "outputs": [
            _port("weather_point", "data", description="解析后的天气点位数据"),
        ],
        "params": [],
        "node_class": "weather_point_parse",
    },
    {
        "type": "weather/summary_generate",
        "engine": "weather",
        "category": "天气-处理",
        "title": "摘要生成",
        "description": "生成天气摘要文本。",
        "inputs": [
            _port("weather_point", "data", description="天气点位数据"),
            _port("layer_id", "value:string", required=False, description="图层标识"),
        ],
        "outputs": [
            _port("summary", "value:string", description="天气摘要文本"),
        ],
        "params": [],
        "node_class": "weather_summary_generate",
    },

    # ═══ Python Provider 模块节点 ══════════════════════════════════════════════
    {
        "type": "module/smap_daily",
        "engine": "python_provider",
        "category": "遥感处理",
        "title": "SMAP 日常处理",
        "description": "读取 SMAP L3 HDF5 文件，转换为 .mat 格式。",
        "inputs": [
            _port("input_dir", "data:source", description="SMAP HDF5 文件目录"),
            _port("time_range", "value:time_range", required=False, description="时间范围（可选，用于过滤文件）"),
        ],
        "outputs": [
            _port("smap_daily_mat", "data:mat", description="SMAP 日常 .mat 输出"),
        ],
        "params": [],
        "node_class": "smap_daily",
    },
    {
        "type": "module/ndvi_daily",
        "engine": "python_provider",
        "category": "遥感处理",
        "title": "NDVI 日常处理",
        "description": "读取 NDVI 16 日栅格数据，生成日常 NDVI .mat 文件。",
        "inputs": [
            _port("input_dir", "data:source", description="NDVI 栅格文件目录"),
        ],
        "outputs": [
            _port("ndvi_daily_mat", "data:mat", description="NDVI 日常 .mat 输出"),
        ],
        "params": [
            _param("emit_quality_products", "boolean", default=False, description="是否输出质量产品"),
            _param("sg_step_days", "number", default=1, description="SG 滤波步长", unit="天", min_val=1, max_val=30, step=1),
            _param("gap_threshold_days", "number", default=16, description="间隔阈值", unit="天", min_val=1, max_val=60, step=1),
        ],
        "node_class": "ndvi_daily",
    },
    {
        "type": "module/fy_daily",
        "engine": "python_provider",
        "category": "遥感处理",
        "title": "风云数据处理",
        "description": "读取风云三号 MWRI HDF 数据，提取多波段亮温。",
        "inputs": [
            _port("input_dir", "data:source", description="FY MWRI HDF 文件目录"),
        ],
        "outputs": [
            _port("fy_daily_mat", "data:mat", description="FY 日常 .mat 输出"),
        ],
        "params": [
            _param("orbit_mode", "string", default="MWRID", options=["MWRID", "MWRIA", "Both"], description="轨道模式"),
            _param("band_ids", "string", description="波段 ID 列表（逗号分隔，如 1,2,3）"),
        ],
        "node_class": "fy_daily",
    },
    {
        "type": "module/station_daily",
        "engine": "python_provider",
        "category": "遥感处理",
        "title": "站点数据处理",
        "description": "读取 ISMN/CASMOS 站点数据，生成验证产品。",
        "inputs": [
            _port("input_dir", "data:source", description="站点数据文件目录"),
        ],
        "outputs": [
            _port("station_mat", "data:mat", description="站点 .mat 输出"),
        ],
        "params": [
            _param("source_type", "string", default="ISMN", options=["ISMN", "CASMOS"], description="数据源类型"),
        ],
        "node_class": "station_daily",
    },
    {
        "type": "module/inversion_daily",
        "engine": "python_provider",
        "category": "反演",
        "title": "单日反演",
        "description": "基于日常合成数据进行微波反演，输出土壤湿度(SM)、植被光学厚度(VOD)等。",
        "inputs": [
            _port("input_mat", "data:mat", description="daily_bundle 输出的 .mat 文件"),
        ],
        "outputs": [
            _port("inversion_mat", "data:mat", description="反演结果 .mat"),
        ],
        "params": [
            _param("mode", "string", default="dh", options=["dh", "ddca"], description="反演模式"),
            _param("freq_ghz", "number", default=1.4, description="频率", unit="GHz", min_val=0.1, max_val=40, step=0.1),
        ],
        "node_class": "inversion_daily",
    },
    {
        "type": "module/block_inversion",
        "engine": "python_provider",
        "category": "反演",
        "title": "批量反演",
        "description": "基于时间序列合成数据进行批量反演。",
        "inputs": [
            _port("input_mat", "data:timeseries", description="timeseries_bundle 输出的 .mat 文件"),
        ],
        "outputs": [
            _port("block_mat", "data:mat", description="批量反演结果 .mat"),
        ],
        "params": [
            _param("mode", "string", default="dh", options=["dh", "ddca"], description="反演模式"),
            _param("freq_ghz", "number", default=1.4, description="频率", unit="GHz", min_val=0.1, max_val=40, step=0.1),
            _param("pixel_chunk_size", "number", default=512, description="像素分块大小", unit="像素", min_val=64, max_val=4096, step=64),
            _param("write_daily_files", "boolean", default=False, description="是否输出每日文件"),
        ],
        "node_class": "block_inversion",
    },
    {
        "type": "module/omega_block",
        "engine": "python_provider",
        "category": "反演",
        "title": "Omega 反演",
        "description": "基于时间序列数据进行 Omega 反演，支持多种实验模式。",
        "inputs": [
            _port("input_mat", "data:timeseries", description="timeseries_bundle 输出的 .mat 文件"),
        ],
        "outputs": [
            _port("omega_mat", "data:mat", description="Omega 反演结果 .mat"),
        ],
        "params": [
            _param("exp_mode", "string", default="Exp0", options=["Exp0", "EXP1A", "EXP1B", "EXP2"], description="实验模式"),
            _param("freq_ghz", "number", default=1.4, description="频率", unit="GHz", min_val=0.1, max_val=40, step=0.1),
            _param("temp_scheme", "string", default="default", description="温度方案"),
            _param("write_daily_files", "boolean", default=False, description="是否输出每日文件"),
        ],
        "node_class": "omega_block",
    },
    {
        "type": "module/daily_bundle",
        "engine": "python_provider",
        "category": "合成",
        "title": "日常合成",
        "description": "将 SMAP、NDVI、FY 等日常产品合成为统一 .mat 格式，供反演使用。",
        "inputs": [
            _port("smap_daily_mat", "data:mat", required=False, description="SMAP 日常 .mat"),
            _port("ndvi_daily_mat", "data:mat", required=False, description="NDVI 日常 .mat"),
            _port("fy3b_folder", "data:source", required=False, description="FY3B 数据目录"),
            _port("fy3d_folder", "data:source", required=False, description="FY3D 数据目录"),
        ],
        "outputs": [
            _port("daily_bundle_mat", "data:mat", description="日常合成 .mat 输出"),
        ],
        "params": [
            _param("tb_source", "string", default="default", description="亮温数据源"),
            _param("sm_source", "string", default="default", description="土壤湿度数据源"),
            _param("ndvi_mode", "string", default="default", description="NDVI 模式"),
        ],
        "node_class": "daily_bundle",
    },
    {
        "type": "module/timeseries_bundle",
        "engine": "python_provider",
        "category": "合成",
        "title": "时间序列合成",
        "description": "将日常合成产品汇总为时间序列 .mat 格式。",
        "inputs": [
            _port("daily_mat_sources", "data:mat", description="日常 .mat 文件目录"),
        ],
        "outputs": [
            _port("timeseries_bundle_mat", "data:timeseries", description="时间序列 .mat 输出"),
        ],
        "params": [
            _param("tb_source", "string", default="default", description="亮温数据源"),
            _param("sm_source", "string", default="default", description="土壤湿度数据源"),
        ],
        "node_class": "timeseries_bundle",
    },

    # ═══ GIS 基础工具模块 ═══════════════════════════════════════════════════════
    {
        "type": "gis/buffer_analysis",
        "engine": "common",
        "category": "GIS工具",
        "title": "缓冲区分析",
        "description": "对矢量点/线/面创建缓冲区。",
        "inputs": [
            _port("points", "data:geojson", description="输入矢量要素 GeoJSON"),
            _port("distance", "value:number", description="缓冲距离"),
        ],
        "outputs": [
            _port("buffer", "data:geojson", description="缓冲区 GeoJSON"),
        ],
        "params": [
            _param("distance_unit", "string", default="meters", options=["meters", "kilometers", "degrees"], description="缓冲距离单位"),
            _param("segments", "number", default=16, description="圆弧段数（曲线光滑度）", min_val=3, max_val=128, step=1),
        ],
        "node_class": "gis_buffer_analysis",
    },
    {
        "type": "gis/zonal_statistics",
        "engine": "common",
        "category": "GIS工具",
        "title": "分区统计",
        "description": "按矢量分区计算栅格统计量。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格"),
            _port("zones", "data:geojson", description="分区矢量 GeoJSON"),
        ],
        "outputs": [
            _port("stats", "data:geojson", description="分区统计结果 GeoJSON"),
        ],
        "params": [
            _param("statistic", "string", default="mean", options=["mean", "median", "sum", "min", "max", "count"], description="统计量类型"),
            _param("band", "number", default=0, description="波段索引", min_val=0, max_val=100, step=1),
            _param("all_touched", "boolean", default=False, description="是否统计所有接触像元（否则仅统计中心点在内的像元）"),
        ],
        "node_class": "gis_zonal_statistics",
    },
    {
        "type": "gis/raster_calculator",
        "engine": "common",
        "category": "GIS工具",
        "title": "栅格计算器",
        "description": "对栅格执行数学表达式运算（如 A*2 + B）。",
        "inputs": [
            _port("a", "data:raster", description="输入栅格 A"),
            _port("b", "data:raster", required=False, description="输入栅格 B（可选）"),
        ],
        "outputs": [
            _port("result", "data:raster", description="计算结果栅格"),
        ],
        "params": [
            _param("expression", "string", default="A", description="表达式，变量名 A/B/C，支持 + - * / ** 等"),
            _param("nodata_handling", "string", default="propagate", options=["propagate", "zero", "ignore"], description="NoData 处理方式"),
        ],
        "node_class": "gis_raster_calculator",
    },
    {
        "type": "gis/vector_to_raster",
        "engine": "common",
        "category": "GIS工具",
        "title": "矢量转栅格",
        "description": "将矢量数据栅格化为栅格图层。",
        "inputs": [
            _port("vector", "data:geojson", description="输入矢量 GeoJSON"),
            _port("bbox", "geometry:bbox", description="输出栅格范围"),
        ],
        "outputs": [
            _port("raster", "data:raster", description="栅格化结果"),
        ],
        "params": [
            _param("attribute_field", "string", description="用于赋值的矢量属性字段名"),
            _param("resolution", "number", default=1000, description="输出分辨率", unit="米", min_val=1, max_val=100000, step=1),
            _param("dtype", "string", default="float32", options=["float32", "int32", "uint8"], description="输出数据类型"),
            _param("fill_value", "number", default=0, description="背景填充值"),
        ],
        "node_class": "gis_vector_to_raster",
    },
    {
        "type": "gis/raster_to_vector",
        "engine": "common",
        "category": "GIS工具",
        "title": "栅格转矢量",
        "description": "将栅格数据转换为矢量多边形或等值线。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格"),
        ],
        "outputs": [
            _port("vector", "data:geojson", description="矢量化结果 GeoJSON"),
        ],
        "params": [
            _param("band", "number", default=0, description="波段索引", min_val=0, max_val=100, step=1),
            _param("threshold", "number", default=0, description="阈值化（大于此值的像元转矢量）"),
            _param("simplify_tolerance", "number", default=0, description="简化容差", unit="米", min_val=0, max_val=10000, step=1),
        ],
        "node_class": "gis_raster_to_vector",
    },
    {
        "type": "gis/reclassify",
        "engine": "common",
        "category": "GIS工具",
        "title": "重分类",
        "description": "按重映射表对栅格值重新分类。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格"),
        ],
        "outputs": [
            _port("raster", "data:raster", description="重分类后栅格"),
        ],
        "params": [
            _param("remap_table", "string", default="", description='重映射表，逗号分隔如 "0-30:1,30-60:2,60-100:3"'),
            _param("nodata_value", "number", default=-9999, description="输出 NoData 值"),
        ],
        "node_class": "gis_reclassify",
    },
    {
        "type": "gis/contour",
        "engine": "common",
        "category": "GIS工具",
        "title": "等值线提取",
        "description": "从栅格表面提取等值线。",
        "inputs": [
            _port("raster", "data:raster", description="输入栅格表面（如 DEM）"),
        ],
        "outputs": [
            _port("contours", "data:geojson", description="等值线 GeoJSON"),
        ],
        "params": [
            _param("interval", "number", default=100, description="等值线间距", min_val=0.01, max_val=10000, step=0.01),
            _param("band", "number", default=0, description="波段索引", min_val=0, max_val=100, step=1),
            _param("smoothing", "boolean", default=True, description="是否平滑等值线"),
        ],
        "node_class": "gis_contour",
    },
    {
        "type": "gis/slope_aspect",
        "engine": "common",
        "category": "GIS工具",
        "title": "坡度坡向",
        "description": "从 DEM 计算坡度（度）和坡向（度）。",
        "inputs": [
            _port("dem", "data:raster", description="输入 DEM 栅格"),
        ],
        "outputs": [
            _port("slope", "data:raster", description="坡度栅格（度）"),
            _port("aspect", "data:raster", description="坡向栅格（度，0=北 90=东）"),
        ],
        "params": [
            _param("z_unit", "string", default="meters", options=["meters", "feet"], description="高程单位"),
            _param("algorithm", "string", default="horn", options=["horn", "zevenbergen"], description="坡度算法"),
        ],
        "node_class": "gis_slope_aspect",
    },
    {
        "type": "gis/watershed",
        "engine": "common",
        "category": "GIS工具",
        "title": "流域分析",
        "description": "基于 DEM 和出水点提取流域边界。",
        "inputs": [
            _port("dem", "data:raster", description="输入 DEM 栅格"),
            _port("pour_points", "data:geojson", description="出水点 GeoJSON"),
        ],
        "outputs": [
            _port("watershed", "data:geojson", description="流域边界 GeoJSON"),
        ],
        "params": [
            _param("fill_threshold", "number", default=0.01, description="填洼阈值", min_val=0, max_val=1, step=0.01),
            _param("flow_direction", "string", default="d8", options=["d8", "dinf"], description="流向算法"),
        ],
        "node_class": "gis_watershed",
    },

    # ═══ GEE 节点 ═════════════════════════════════════════════════════════════
    {
        "type": "gee/image",
        "engine": "gee",
        "category": "GEE-数据",
        "title": "GEE 影像加载",
        "description": "从 Google Earth Engine 加载影像 Asset。",
        "inputs": [],
        "outputs": [
            _port("image", "data:raster", description="GEE 影像对象"),
        ],
        "params": [
            _param("asset_id", "string", description="GEE Asset ID"),
        ],
        "node_class": "gee_image",
    },
    {
        "type": "gee/cloud_mask",
        "engine": "gee",
        "category": "GEE-处理",
        "title": "云掩膜",
        "description": "对 Sentinel-2 影像执行云掩膜。",
        "inputs": [
            _port("image", "data:raster", description="输入影像"),
        ],
        "outputs": [
            _port("masked", "data:raster", description="掩膜后影像"),
        ],
        "params": [],
        "node_class": "gee_cloud_mask",
    },
    {
        "type": "gee/clip",
        "engine": "gee",
        "category": "GEE-处理",
        "title": "裁剪",
        "description": "按几何范围裁剪影像。",
        "inputs": [
            _port("image", "data:raster", description="输入影像"),
            _port("geometry", "geometry:bbox", description="裁剪范围"),
        ],
        "outputs": [
            _port("clipped", "data:raster", description="裁剪后影像"),
        ],
        "params": [],
        "node_class": "gee_clip",
    },
    {
        "type": "gee/select_bands",
        "engine": "gee",
        "category": "GEE-处理",
        "title": "波段选择",
        "description": "选择或重命名影像波段。",
        "inputs": [
            _port("image", "data:raster", description="输入影像"),
        ],
        "outputs": [
            _port("image", "data:raster", description="波段选择后影像"),
        ],
        "params": [
            _param("bands", "array", default=[], description="要选择的波段列表（逗号分隔）"),
            _param("rename", "array", default=[], description="重命名后的波段列表（逗号分隔）"),
        ],
        "node_class": "gee_select_bands",
    },
]


# ─── 查询接口 ────────────────────────────────────────────────────────────────
def get_all_node_templates() -> list[dict[str, Any]]:
    """返回所有节点模板的列表。"""
    return [dict(t) for t in _NODE_TEMPLATES]


def get_node_templates_by_engine(engine: str) -> list[dict[str, Any]]:
    """按引擎过滤节点模板。"""
    return [dict(t) for t in _NODE_TEMPLATES if t["engine"] == engine]


def get_node_template(node_type: str) -> dict[str, Any] | None:
    """按类型获取单个节点模板。"""
    for t in _NODE_TEMPLATES:
        if t["type"] == node_type:
            return dict(t)
    return None


def get_node_template_summary() -> list[dict[str, str]]:
    """返回节点模板摘要列表（仅 type, engine, category, title）。"""
    return [
        {"type": t["type"], "engine": t["engine"], "category": t["category"], "title": t["title"]}
        for t in _NODE_TEMPLATES
    ]
