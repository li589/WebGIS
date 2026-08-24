from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MapMode(str, Enum):
    mode_2d = "2d"
    mode_3d = "3d"


class LayerSourceType(str, Enum):
    demo = "demo"
    gee = "gee"
    cog = "cog"
    vector_tile = "vector_tile"
    algorithm_output = "algorithm_output"
    weather = "weather"


class LayerRenderType(str, Enum):
    raster = "raster"
    vector = "vector"
    point = "point"
    heatmap = "heatmap"


class TimeGranularity(str, Enum):
    hour = "hour"
    day = "day"
    month = "month"


class BoundingBox(BaseModel):
    # east 容许 >180（跨日界线 unwrap，如 170..235.5），与 layer_router
    # Query(ge=-180, le=360) 约定一致；west 同步放宽避免 unwrap 视口 west>180。
    west: float = Field(ge=-180.0, le=360.0)
    south: float = Field(ge=-90.0, le=90.0)
    east: float = Field(ge=-180.0, le=360.0)
    north: float = Field(ge=-90.0, le=90.0)
    crs: str = "EPSG:4326"

    @model_validator(mode="after")
    def _validate_bounds_order(self) -> BoundingBox:
        # south must always be <= north; west <= east is NOT enforced because
        # antimeridian-crossing bounds (e.g. west=170, east=-170) are valid
        # and supported by layer_router (ge=-180, le=360) and geo_math.
        if self.south > self.north:
            raise ValueError("south must be <= north")
        return self


class LayerStyleHint(BaseModel):
    palette: str | None = None
    unit_label: str | None = None
    opacity: float = 1.0


class LayerCapabilities(BaseModel):
    render_strategy: str | None = None
    paint_mode: str | None = None
    data_domain: str | None = None
    primary_metric: str | None = None
    supports_particle_flow: bool = False
    supports_map_layer: bool = False
    supports_viewport_refresh: bool = False
    viewport_refresh_mode: str | None = None
    legend_ticks: list[float | int | str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    delivery_modes: list[str] = Field(default_factory=list)
    result_interfaces: list[str] = Field(default_factory=list)


class LayerPresentation(BaseModel):
    """X1: 图层 UI 呈现元数据 — 后端下发，前端消费的唯一真源。

    将原前端 ``LAYER_LIBRARY`` 中的 UI 样式字段（accentColor / accentGlow /
    chipTone / metricLabel / metricUnit / metricPrecision / updateLabel /
    sourceLabel）迁移到后端种子 JSON，经 ``GET /layers`` 下发。
    前端 ``LAYER_LIBRARY`` 仅在 API 不可用时作离线兜底。
    """
    accent_color: str | None = None
    """UI 强调色（hex），如 '#67d4ff'。"""
    accent_glow: str | None = None
    """UI 辉光色（rgba），如 'rgba(103, 212, 255, 0.34)'。"""
    chip_tone: str | None = None
    """UI 标签底色（rgba），如 'rgba(103, 212, 255, 0.18)'。"""
    metric_label: str | None = None
    """指标标签，如 '风速' / 'NDVI'。"""
    metric_unit: str | None = None
    """指标单位，如 'm/s' / ''。"""
    metric_precision: int | None = None
    """指标小数精度，如 1。"""
    update_label: str | None = None
    """更新频率文案，如 '每小时更新' / '按时间维度'。"""
    source_label: str | None = None
    """数据源文案，如 '天气引擎（多源）'。"""


class LayerSourceDef(BaseModel):
    """X1: 图层数据源定义 — 从前端 catalog.ts 迁移到后端 JSON。

    单源图层含 1 项；合并组虚拟条目含多个成员源。
    前端通过 codegen 或运行时 API 消费，``source_id`` 映射为前端 ``LayerSource.id``。
    """
    source_id: str
    """源标识，与 layer_id 对齐（合并组的成员 layer_id）。"""
    name: str
    """源显示名。"""
    description: str = ""
    url_template: str = ""
    needs_auth: bool = False
    needs_backend_transform: bool = False
    coord_sys: str = "EPSG:4326"
    update_frequency: str = ""
    attribution: str | None = None


class LayerCategoryDef(BaseModel):
    """X1: 图层分类定义 — 后端下发，消除前后端分类双写。"""
    id: str
    name: str
    icon: str | None = None
    accent_color: str | None = None
    chip_tone: str | None = None
    sub_categories: list[str] = Field(default_factory=list)


class LayerCategoryResponse(BaseModel):
    items: list[LayerCategoryDef]


class OnlineTemporalCapability(BaseModel):
    """在线时间获取能力声明。

    标记图层支持"用户选时间点 → 自动在线获取 → 动态刷新"流程。
    None 表示该图层不支持在线历史时间获取。
    """
    enabled: bool = False
    """是否启用在线时间获取。"""
    coverage_start: str | None = None
    """可获取的时间范围起点（ISO 日期或 'YYYY-MM'）。"""
    coverage_end: str | None = None
    """可获取的时间范围终点。"""
    native_step: str = "1d"
    """原生时间步（'1d' / '8d' / '1M' / '1Y'），与 descriptor 时间粒度对齐。"""
    max_batch: int = 12
    """单次批量获取的最大时间点数。"""
    prefetch_depth: int = 1
    """预获取相邻时间点深度（前后各 N 步）。"""
    queue_tag: str = "temporal-fetch"
    """工作流提交时的 queue_tag，用于与视口驱动工作流区分。"""
    priority: str = "low"
    """提交优先级（'low' | 'normal'），预取用 low 避免抢占用户操作。"""


class WorkflowVariantDef(BaseModel):
    """工作流变体定义（X2：同一图层的多执行形态，如在线/本地反演）。

    LayerDescriptor.workflow_variants 以变体键（"online" / "local"）映射到具体种子；
    前端据此在分析框渲染「反演来源」切换控件，默认提交 descriptor.workflow_id
    所指变体（约定为默认变体）。
    """

    workflow_id: str
    """变体对应的 workflow 种子 id（如 omega_sf_fenkuai_fy_online）。"""
    label: str | None = None
    """变体展示名（如 "在线反演" / "本地反演"）；缺省时前端按变体键回退显示。"""
    credential_profile: str | None = None
    """在线变体所需门户凭据 profile（"nsmc" / "earthdata" 等）；
    readiness 二元语义据此判定在线变体可用性。"""


class LayerDescriptor(BaseModel):
    layer_id: str
    dataset_key: str
    display_name: str
    description: str
    category: str
    source_type: LayerSourceType
    render_type: LayerRenderType
    supported_map_modes: list[MapMode]
    supports_time: bool = True
    is_realtime: bool = False
    default_visible: bool = False
    status: str = "available"
    time_granularity: TimeGranularity | None = None
    default_time_offset: int | None = None
    extent: BoundingBox
    style: LayerStyleHint = Field(default_factory=LayerStyleHint)
    capabilities: LayerCapabilities = Field(default_factory=LayerCapabilities)
    tags: list[str] = Field(default_factory=list)
    module_name: str | None = None
    engine: str | None = None
    workflow_name: str | None = None
    workflow_id: str | None = None
    workflow_definition: dict[str, Any] | None = None
    # 需求2（2026-08-22）：工作流中文命名配置（group_title / output_labels），
    # 由种子 extra / descriptor workflow_extra 透传，前端建组优先读取。
    workflow_extra: dict[str, Any] | None = None
    default_task_type: str | None = None
    default_data_access_sources: dict[str, list[str]] = Field(default_factory=dict)
    run_readiness: str = "ready"
    run_readiness_summary: str | None = None
    run_readiness_notes: list[str] = Field(default_factory=list)
    # ── 课题组数据集元数据扩展（Phase 1：扩展和细化）──────────────────────────────
    # 用于课题组数据集的归属、时间范围与数据源引用追踪；其他图层可留空。
    data_owner: str | None = None
    """数据归属（课题组成员：Wangc / Wangxd / Liuzheng / Chenhaojun / LiuSJ / Wangxy / Lab）。
    课题组派生数据集填写组员名（与 NAS 顶级目录对齐）；本机派生数据填 'Lab'；外部公开数据留空。
    """
    temporal_coverage: str | None = None
    """时间覆盖范围的人类可读描述，例如 '2023-01' / '2018-2020' / '1985-2023' / 'doy 017-030'。
    用于图层信息面板展示；时间序列图层也应填写以表明整体覆盖区间。
    """
    source_reference: str | None = None
    """数据源引用（DOI / URL / 数据集官方页面）。
    例如 'https://doi.org/10.5281/zenodo.4417810' (CLCD)；用于学术引用与溯源。
    """
    sub_category: str | None = None
    """课题组数据二级分类：'模型输入' | '模型输出' | '辅助数据'；其它分类可留空。"""
    presentation: LayerPresentation = Field(default_factory=LayerPresentation)
    """X1: UI 呈现元数据（accentColor / metricLabel / sourceLabel 等）。
    后端种子 JSON 提供，前端 ``LAYER_LIBRARY`` 仅在 API 不可用时作离线兜底。"""
    # ── X1: 数据源与合并组（外部化字段）────────────────────────────────────────
    sources: list[LayerSourceDef] = Field(default_factory=list)
    """图层数据源列表（X1）。单源图层含 1 项；合并组含多个成员源。"""
    merged_into: str | None = None
    """若此图层已合并到某个多源组，此处记录目标 catalog_id。"""
    is_merged_group: bool = False
    """标记此条目为合并组虚拟条目（含 members 列表，自身不对应实际数据）。"""
    members: list[str] = Field(default_factory=list)
    """合并组成员的 layer_id 列表（仅 is_merged_group=true 时有效）。"""
    is_admin_boundary: bool = False
    """是否为行政区边界图层。"""
    online_temporal: OnlineTemporalCapability | None = None
    """在线时间获取能力声明。None 表示该图层不支持在线历史时间获取。"""
    workflow_variants: dict[str, WorkflowVariantDef] | None = None
    """工作流变体（X2）。键为变体名（"online" / "local"），值为对应种子定义；
    None 表示单变体图层（仅 descriptor.workflow_id 一条执行路径）。"""


class LayerCatalogResponse(BaseModel):
    items: list[LayerDescriptor]
    categories: list[LayerCategoryDef] = Field(default_factory=list)
    """X1: 类别定义随 catalog 一起下发，前端无需维护静态 LAYER_CATEGORIES。"""


class SpatialFilter(BaseModel):
    filter_type: str = "bbox"
    bbox: BoundingBox | None = None
    region_code: str | None = None
    region_name: str | None = None


class TimeRange(BaseModel):
    start_at: datetime
    end_at: datetime
    granularity: TimeGranularity = TimeGranularity.hour

    @model_validator(mode="after")
    def _validate_time_order(self) -> TimeRange:
        if self.start_at > self.end_at:
            raise ValueError("start_at must be <= end_at")
        return self


class ExecutionStatus(str, Enum):
    accepted = "accepted"
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    # 失败分类修复：新增 retry_pending 中间态，表示瞬态失败等待自动重试
    retry_pending = "retry_pending"


class FailureCategory(str, Enum):
    """失败分类枚举，区分可重试与不可重试失败。"""

    # ---- 终态：不可重试 ----
    validation_error = "validation_error"
    not_found = "not_found"
    permission_denied = "permission_denied"
    contract_violation = "contract_violation"
    terminal_failure = "terminal_failure"

    # ---- 瞬态：可重试 ----
    transient_network = "transient_network"
    transient_upstream = "transient_upstream"
    rate_limited = "rate_limited"
    timeout = "timeout"

    # ---- 部分成功 ----
    partial_success = "partial_success"
    degraded = "degraded"

    @property
    def retryable(self) -> bool:
        """该类别是否可重试。"""
        return self in {
            FailureCategory.transient_network,
            FailureCategory.transient_upstream,
            FailureCategory.rate_limited,
            FailureCategory.timeout,
            FailureCategory.partial_success,
        }


class WorkflowPriority(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"
    critical = "critical"


class WorkflowResourceProfile(str, Enum):
    light = "light"
    standard = "standard"
    heavy = "heavy"
    batch = "batch"


class WorkflowCommandType(str, Enum):
    analysis = "analysis"
    layer_preview = "layer_preview"
    export = "export"
    refresh_data = "refresh_data"
    sync_demo = "sync_demo"
    custom = "custom"


class ResultKind(str, Enum):
    json = "json"
    table = "table"
    chart = "chart"
    map_layer = "map_layer"
    log = "log"
    file = "file"
    text = "text"
    diagnostic = "diagnostic"


class ChartType(str, Enum):
    """Generic analysis chart kinds (raster/vector agnostic)."""

    line = "line"
    bar = "bar"
    histogram = "histogram"
    scatter = "scatter"
    boxplot = "boxplot"


class ChartSeriesSpec(BaseModel):
    """One named series inside a ChartSpec."""

    name: str = "series"
    x: list[float | int | str] = Field(default_factory=list)
    y: list[float | int | None] = Field(default_factory=list)


class ChartSpec(BaseModel):
    """Structured chart payload for ``ResultKind.chart`` inline_data.

    Compatible with the legacy demo shape ``{chart_type, x, y, series_name}``:
    when ``series`` is empty, consumers may fall back to top-level ``x``/``y``.
    """

    schema_version: str = "1"
    chart_type: ChartType = ChartType.line
    title: str = "Chart"
    x_label: str = ""
    y_label: str = ""
    unit: str = ""
    series: list[ChartSeriesSpec] = Field(default_factory=list)
    # Legacy flat axes (demo provider + compact histogram)
    x: list[float | int | str] = Field(default_factory=list)
    y: list[float | int | None] = Field(default_factory=list)
    series_name: str | None = None
    bins: list[float] | None = None
    categories: list[str] | None = None


class TableSpec(BaseModel):
    """Structured table payload for ``ResultKind.table`` inline_data."""

    schema_version: str = "1"
    title: str = "Table"
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    units: dict[str, str] = Field(default_factory=dict)
    dtypes: dict[str, str] = Field(default_factory=dict)


class EventChannel(str, Enum):
    status = "status"
    log = "log"
    data = "data"
    chart = "chart"
    notification = "notification"
    system = "system"


class LogLevel(str, Enum):
    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"


class RuntimeConfigScope(str, Enum):
    frontend = "frontend"
    backend = "backend"
    provider = "provider"
    workflow = "workflow"
    system = "system"


class FrontendCommandType(str, Enum):
    preload = "preload"
    clear_cache = "clear_cache"
    cleanup = "cleanup"
    cancel_run = "cancel_run"
    reload_catalog = "reload_catalog"
    custom = "custom"


class ServiceHealth(str, Enum):
    ok = "ok"
    busy = "busy"
    degraded = "degraded"
    offline = "offline"


class ClientIdentity(BaseModel):
    client_id: str | None = None
    session_id: str | None = None
    page: str | None = None
    view_id: str | None = None
    user_agent: str | None = None


class RuntimeMapContext(BaseModel):
    active_layer_id: str | None = None
    basemap_mode: str | None = None
    map_mode: MapMode = MapMode.mode_2d
    viewport_bbox: BoundingBox | None = None


class AlgorithmOutputSpec(BaseModel):
    raster_format: str = "COG"
    table_format: str = "parquet"
    include_qc: bool = True
    include_manifest: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


class AlgorithmWorkflowRequest(BaseModel):
    module_name: str | None = None
    workflow_name: str | None = None
    workflow_definition: dict[str, Any] | str | None = None
    workflow_entry_name: str | None = None
    datasource_selection: dict[str, Any] = Field(default_factory=dict)
    algorithm_params: dict[str, Any] = Field(default_factory=dict)
    output_spec: AlgorithmOutputSpec = Field(default_factory=AlgorithmOutputSpec)
    resource_hint: dict[str, Any] | None = None
    cache_policy: dict[str, Any] | None = None
    resume_policy: dict[str, Any] | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    task_type: str | None = None
    region: dict[str, Any] | None = None
    time_range: dict[str, Any] | None = None
    # 算法级优先级提示（1/5/8/9），未设置时由 bridge 从外层 WorkflowSubmitRequest.priority 映射
    priority: int | None = None


class GeeWorkflowRequest(BaseModel):
    """GEE 引擎工作流请求。

    与 AlgorithmWorkflowRequest 平行：
    - workflow / context 直接对应 webgis_gee 的 WorkflowSubmissionPayload
    - 当 workflow_definition 非空时，作为 GEE WorkflowDefinition 字典传入
    - manifest_uri 用于导出状态轮询场景（command_type=custom 且仅查询导出状态时使用）
    """

    workflow: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    workflow_id: str | None = None
    manifest_uri: str | None = None
    update_manifest: bool = False
    tags: dict[str, str] = Field(default_factory=dict)


class WeatherWorkflowRequest(BaseModel):
    """天气引擎工作流请求。

    与 GeeWorkflowRequest / AlgorithmWorkflowRequest 平行：
    - workflow / context 直接对应 weatherengine 的 WorkflowDefinition
    - layer_id 用于指定天气图层（wind-field / temperature / precipitation）
    """

    workflow: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    workflow_id: str | None = None
    layer_id: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class RetryPolicy(BaseModel):
    """统一重试策略。

    适用于所有 bridge service 的瞬态失败重试。
    bridge 层只做失败分类（抛 BridgeExecutionError），hub 层根据 retryable 决定是否重试。
    """

    max_attempts: int = 3
    initial_backoff_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 60.0
    jitter_ratio: float = 0.2

    def compute_backoff(self, attempt: int) -> float:
        """计算第 attempt 次重试的退避秒数（含抖动）。"""
        import random

        base = min(
            self.max_backoff_seconds,
            self.initial_backoff_seconds
            * (self.backoff_multiplier ** max(0, attempt - 1)),
        )
        jitter = base * self.jitter_ratio
        return base + random.uniform(-jitter, jitter)


class WorkflowSubmitRequest(BaseModel):
    command_type: WorkflowCommandType
    command_label: str | None = None
    layer_id: str | None = None
    priority: WorkflowPriority = WorkflowPriority.normal
    resource_profile: WorkflowResourceProfile = WorkflowResourceProfile.standard
    realtime_preferred: bool = False
    queue_tag: str | None = None
    spatial_filter: SpatialFilter | None = None
    time_range: TimeRange | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    # M13 修复：旧字段保留向后兼容，标记 deprecated
    algorithm_request: AlgorithmWorkflowRequest | dict[str, Any] = Field(
        default_factory=AlgorithmWorkflowRequest
    )
    gee_request: GeeWorkflowRequest | dict[str, Any] | None = None
    weather_request: WeatherWorkflowRequest | dict[str, Any] | None = None
    config_overrides: dict[str, Any] = Field(default_factory=dict)
    requested_outputs: list[ResultKind | str] = Field(
        default_factory=lambda: [ResultKind.json]
    )
    client: ClientIdentity = Field(default_factory=ClientIdentity)
    map_context: RuntimeMapContext = Field(default_factory=RuntimeMapContext)
    correlation_id: str | None = None
    # 失败分类修复：顶层统一重试策略，覆盖各 bridge 的瞬态失败
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    # 内部字段：重试时由 hub 注入，表示当前是第几次尝试（首次为 1，不填等同于 1）
    retry_attempt: int | None = None


class WorkflowAcceptedResponse(BaseModel):
    run_id: str
    status: ExecutionStatus
    status_url: str
    events_url: str
    created_at: datetime
    message: str


class WorkflowResultReference(BaseModel):
    result_id: str
    result_kind: ResultKind
    title: str
    mime_type: str
    inline_data: dict[str, Any] | None = None
    resource_url: str | None = None
    resource_backend: str | None = None
    resource_key: str | None = None
    resource_size_bytes: int | None = None
    updated_at: datetime


class WorkflowEvent(BaseModel):
    event_id: str
    run_id: str
    channel: EventChannel
    level: LogLevel = LogLevel.info
    message: str
    created_at: datetime
    progress: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowEventsResponse(BaseModel):
    run_id: str
    items: list[WorkflowEvent]


class WorkflowAnalysisResultDto(BaseModel):
    workflow_entry_name: str | None = None
    layer_id: str | None = None
    requested_hour: float | None = None
    compatibility_mode: str | None = None
    summary: str | None = None
    status_label: str | None = None
    metric_label: str | None = None
    metric_value: float | int | str | None = None
    metric_unit: str | None = None
    hotspot_count: int | None = None
    availability_state: str | None = None
    data_state_mode: str | None = None
    result_category: str = "analysis"
    results: dict[str, str | None] = Field(default_factory=dict)
    # Optional typed analysis payloads (forces ChartSpec/TableSpec into OpenAPI)
    charts: list[ChartSpec] = Field(default_factory=list)
    tables: list[TableSpec] = Field(default_factory=list)


class WorkflowProviderResultDto(BaseModel):
    workflow_entry_name: str | None = None
    layer_id: str | None = None
    provider_key: str | None = None
    summary: str | None = None
    metric_label: str | None = None
    metric_unit: str | None = None
    metric_value: float | int | str | None = None
    status_label: str | None = None
    confidence_label: str | None = None
    hotspot_count: int | None = None
    series_point_count: int | None = None
    result_category: str = "provider"
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowDownloadResultDto(BaseModel):
    workflow_entry_name: str | None = None
    layer_id: str | None = None
    requested_hour: float | None = None
    compatibility_mode: str | None = None
    summary: str | None = None
    status_label: str | None = None
    availability_state: str | None = None
    data_state_mode: str | None = None
    download_ticket_id: str | None = None
    execution_status: str | None = None
    job_state: dict[str, Any] = Field(default_factory=dict)
    follow_up_policy: str | None = None
    source_mode: str | None = None
    refresh_policy: str | None = None
    cache_status: str | None = None
    cache_key: str | None = None
    manifest_result_id: str | None = None
    result_category: str = "download"
    results: dict[str, str | None] = Field(default_factory=dict)


WorkflowResultDto = (
    WorkflowAnalysisResultDto
    | WorkflowProviderResultDto
    | WorkflowDownloadResultDto
    | dict[str, Any]
)


class WorkflowRunStatusResponse(BaseModel):
    run_id: str
    status_url: str | None = None
    events_url: str | None = None
    command_type: WorkflowCommandType
    command_label: str | None = None
    layer_id: str | None = None
    priority: WorkflowPriority = WorkflowPriority.normal
    resource_profile: WorkflowResourceProfile = WorkflowResourceProfile.standard
    realtime_preferred: bool = False
    queue_tag: str | None = None
    status: ExecutionStatus
    progress: int
    message: str
    created_at: datetime
    updated_at: datetime
    spatial_filter: SpatialFilter | None = None
    time_range: TimeRange | None = None
    requested_outputs: list[ResultKind | str] = Field(default_factory=list)
    client: ClientIdentity = Field(default_factory=ClientIdentity)
    map_context: RuntimeMapContext = Field(default_factory=RuntimeMapContext)
    config_overrides: dict[str, Any] = Field(default_factory=dict)
    executor_metadata: dict[str, Any] = Field(default_factory=dict)
    result_refs: list[WorkflowResultReference] = Field(default_factory=list)
    result_dto: WorkflowResultDto | None = None
    diagnostics: list[str] = Field(default_factory=list)


class WorkflowRunViewSummaryRow(BaseModel):
    label: str
    value: str


class WorkflowRunViewResponse(BaseModel):
    run_id: str
    category: str
    title: str
    subtitle: str
    status_text: str
    progress_text: str
    summary: str | None = None
    metric_rows: list[WorkflowRunViewSummaryRow] = Field(default_factory=list)
    result_url: str | None = None
    artifact_refs: list[WorkflowResultReference] = Field(default_factory=list)
    can_show_link: bool = False
    updated_at: datetime


# ── 图层平台子系统：资产状态与生命周期聚合契约（P0，2026-08-24） ─────────────


class LayerAssetStateResponse(BaseModel):
    """单图层烘焙资产状态（GET /layer-assets/{layer_id}）。"""

    layer_id: str
    asset_state: str
    """missing | unversioned | stale | fresh"""

    bake_version: int | None = None
    current_bake_version: int

    png_exists: bool = False
    bounds_exists: bool = False

    category: str = "static"
    """static | time-series"""

    time_list: list[str] = Field(default_factory=list)
    default_time: str | None = None

    asset_task: str | None = None
    """可用的烘焙任务 key；None 表示该图层暂未配置烘焙任务。"""


class LayerLifecycleRunSummary(BaseModel):
    """lifecycle 聚合中的最近 run 摘要（不含完整 payload）。"""

    run_id: str
    workflow_kind: str | None = None
    status: str
    progress: int
    message: str | None = None
    updated_at: datetime


class LayerLifecycleResponse(BaseModel):
    """图层生命周期聚合视图（GET /layers/{layer_id}/lifecycle）。

    前端不再自行拼接 jobLayer/overlayTimeStates/asset_state，
    统一从本响应读取「资产 + 最近 run + 时间轴」状态。
    """

    layer_id: str
    asset: LayerAssetStateResponse
    recent_runs: list[LayerLifecycleRunSummary] = Field(default_factory=list)

    lifecycle_state: str
    """fresh | stale | updating | missing | failed"""

    message: str | None = None
    updated_at: datetime


class LayerOnlineSyncRequest(BaseModel):
    """在线源同步请求（POST /layer-assets/{layer_id}/sync，图层平台子系统 P1）。

    统一入口：在线时间获取/在线源拉取不再让前端自行拼 workflow 提交参数。
    服务端据此创建 ``workflow_kind=online_sync`` 的 run，并复用现有
    workflow-runs 状态/事件/取消契约。失败时保留旧资产显示。
    """

    time_key: str | None = None
    """目标时间块 key（如 '2023-01' / '2023-01-15'）；缺省=图层 default_time。"""

    time_range: TimeRange | None = None
    """显式时间范围；与 time_key 至少给一个。"""

    is_prefetch: bool = False
    """是否预获取（低优先级，达到并发上限可跳过）。"""

    priority: str = "normal"
    """'low' | 'normal'；预获取通常 low。"""


class LayerOnlineSyncResponse(BaseModel):
    """在线源同步响应：复用 WorkflowAcceptedResponse 语义。"""

    run_id: str | None = None
    """已创建或复用的 run id；skip 原因为 cooldown/succeeded 时为既有 run。"""

    status: str
    """submitted | in-flight | cooldown | succeeded | skipped-unsupported"""

    message: str
    layer_id: str
    time_key: str | None = None
    status_url: str | None = None
    events_url: str | None = None


# ── 图层平台子系统 P1：课题组工作流模板一键显示 ─────────────────────────────


class WorkflowTemplateSummary(BaseModel):
    """课题组工作流模板摘要（GET /workflows/templates）。

    从 workflow_seeds/system + workflow_definitions/user 聚合；
    is_template=true 或 tags 含 "template"/"lab" 的定义视为课题组模板。
    """

    workflow_id: str
    name: str
    description: str | None = None
    engine: str = "unknown"
    """python_provider | gee | weather | analysis"""

    linked_layer_id: str | None = None
    """模板完成后自动上图的目标图层（None=仅运行不上图）"""

    auto_display: bool = True
    """完成后是否自动 materialize-map-layers"""

    resource_profile: str = "standard"
    """light | standard | heavy | batch（realtime 为 light 别名）"""

    is_template: bool = True
    readonly: bool = False
    kind: str = "system"
    node_count: int = 0
    tags: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class WorkflowTemplateListResponse(BaseModel):
    items: list[WorkflowTemplateSummary] = Field(default_factory=list)
    count: int


class WorkflowTemplateRunRequest(BaseModel):
    """模板一键运行请求（POST /workflows/templates/{workflow_id}/runs）。"""

    parameters: dict[str, Any] = Field(default_factory=dict)
    """模板参数覆盖（与种子 defaults 合并）。"""

    time_range: TimeRange | None = None
    resource_profile: str | None = None
    """覆盖模板默认资源档位。"""

    auto_display: bool | None = None
    """覆盖模板默认 auto_display。"""


class WorkflowTemplateRunResponse(BaseModel):
    """模板一键运行响应：复用 WorkflowAcceptedResponse 语义。"""

    run_id: str
    status: str
    message: str
    workflow_id: str
    linked_layer_id: str | None = None
    auto_display: bool = True
    status_url: str | None = None
    events_url: str | None = None


class WeatherLayerRenderHint(BaseModel):
    layer_id: str
    paint_mode: str = "point_symbol"
    palette: str
    primary_metric: str
    unit_label: str
    opacity: float = 0.82
    legend_ticks: list[float | int | str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class WeatherPointCurrent(BaseModel):
    temperature_2m: float | None = None
    apparent_temperature: float | None = None
    precipitation: float | None = None
    rain: float | None = None
    weather_code: int | None = None
    cloud_cover: float | None = None
    pressure_msl: float | None = None
    surface_pressure: float | None = None
    wind_speed_10m: float | None = None
    wind_direction_10m: float | None = None
    wind_gusts_10m: float | None = None
    # 风场高层（Open-Meteo 风塔高度层）
    wind_speed_80m: float | None = None
    wind_direction_80m: float | None = None
    wind_speed_120m: float | None = None
    wind_direction_120m: float | None = None
    wind_speed_180m: float | None = None
    wind_direction_180m: float | None = None
    # 温度高层
    temperature_80m: float | None = None
    temperature_120m: float | None = None
    temperature_180m: float | None = None
    # 之前缺失的近地面变量
    relative_humidity_2m: float | None = None
    dew_point_2m: float | None = None
    visibility: float | None = None
    # 气压层变量（Open-Meteo pressure_levels 参数对应字段）
    # 当前值取自 hourly 数组首小时；保留 None 表示未请求气压层
    wind_speed_850hPa: float | None = None
    wind_direction_850hPa: float | None = None
    temperature_850hPa: float | None = None
    wind_speed_500hPa: float | None = None
    wind_direction_500hPa: float | None = None
    temperature_500hPa: float | None = None
    wind_speed_200hPa: float | None = None
    wind_direction_200hPa: float | None = None
    temperature_200hPa: float | None = None


class WeatherPointHourlyEntry(BaseModel):
    time: datetime
    temperature_2m: float | None = None
    precipitation: float | None = None
    wind_speed_10m: float | None = None
    primary_metric: str | None = None
    primary_value: float | None = None


class WeatherPointResponse(BaseModel):
    provider: str
    model: str
    resolved_model: str | None = None
    layer_id: str
    latitude: float
    longitude: float
    place_name: str | None = None
    timezone: str | None = None
    fetched_at: datetime
    observation_time: datetime | None = None
    cache_status: str
    summary: str
    current: WeatherPointCurrent = Field(default_factory=WeatherPointCurrent)
    hourly: list[WeatherPointHourlyEntry] = Field(default_factory=list)
    render_hint: WeatherLayerRenderHint
    diagnostics: list[str] = Field(default_factory=list)


class RuntimeConfigPatch(BaseModel):
    scope: RuntimeConfigScope
    key: str
    value: Any
    description: str | None = None


class RuntimeConfigUpdateRequest(BaseModel):
    items: list[RuntimeConfigPatch]
    client: ClientIdentity = Field(default_factory=ClientIdentity)


class RuntimeConfigUpdateResponse(BaseModel):
    accepted: bool
    updated_at: datetime
    applied_count: int
    message: str
    config_snapshot: dict[str, dict[str, Any]]


class RuntimeConfigSnapshotResponse(BaseModel):
    """GET /runtime/config — scope→key→value overrides (merged defaults + DB)."""

    model_config = ConfigDict(extra="allow")


class BackendServiceStatus(BaseModel):
    service_name: str
    health: ServiceHealth
    message: str
    updated_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class RuntimeStatusResponse(BaseModel):
    overall_health: ServiceHealth
    service_name: str
    environment: str
    updated_at: datetime
    active_run_count: int
    config_snapshot: dict[str, dict[str, Any]]
    services: list[BackendServiceStatus] = Field(default_factory=list)


class SystemResourceSnapshot(BaseModel):
    """系统级资源快照（psutil 采集，轻量非阻塞）。"""

    cpu_percent: float | None = None
    memory_total_mb: float | None = None
    memory_used_mb: float | None = None
    memory_percent: float | None = None
    disk_total_mb: float | None = None
    disk_used_mb: float | None = None
    disk_percent: float | None = None


class ProcessResourceSnapshot(BaseModel):
    """单个后端进程资源快照。"""

    pid: int
    name: str
    cpu_percent: float | None = None
    memory_rss_mb: float | None = None
    threads: int | None = None
    status: str | None = None


class ResourceUsageResponse(BaseModel):
    """GET /runtime/resources — 后端进程与宿主系统资源占用。"""

    updated_at: datetime
    system: SystemResourceSnapshot | None = None
    processes: list[ProcessResourceSnapshot] = Field(default_factory=list)
    worker_count: int | None = None


class FrontendCommandRequest(BaseModel):
    command_type: FrontendCommandType
    target: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    client: ClientIdentity = Field(default_factory=ClientIdentity)
    correlation_id: str | None = None


class FrontendCommandResponse(BaseModel):
    accepted: bool
    command_type: FrontendCommandType
    target: str | None = None
    created_at: datetime
    message: str
    next_action: str | None = None


# ─── InfoPanel GIS analysis tools ─────────────────────────────────────────────


class AnalysisToolParamField(BaseModel):
    key: str
    type: str = "string"
    title: str = ""
    description: str | None = None
    default: Any = None
    min: float | None = None
    max: float | None = None
    unit: str | None = None
    options: list[str] | None = None


class AnalysisToolDescriptor(BaseModel):
    tool_id: str
    title: str
    description: str = ""
    category: str = "analysis"
    input_kinds: list[str] = Field(default_factory=list)
    param_schema: list[AnalysisToolParamField] = Field(default_factory=list)
    workflow_template_id: str
    outputs: list[str] = Field(default_factory=list)
    resource_profile: str = "standard"
    concurrency_key: str = "layer_tool"
    enabled: bool = True
    disabled_reason: str | None = None


class AnalysisToolListResponse(BaseModel):
    layer_id: str | None = None
    layer_kind: str = "any"
    items: list[AnalysisToolDescriptor] = Field(default_factory=list)


class AnalysisMapPoint(BaseModel):
    lng: float
    lat: float


class AnalysisRunRequest(BaseModel):
    tool_id: str
    layer_id: str
    overlay_layer_id: str | None = None
    zones_overlay_layer_id: str | None = None
    zones_geojson_path: str | None = None
    geojson_path: str | None = None
    map_point: AnalysisMapPoint | None = None
    bbox: BoundingBox | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    show_on_map: bool = True


class OnlineSourceCredentialStatus(BaseModel):
    """单个在线数据源的凭证就绪状态（GET /config/online-sources）。

    图层平台子系统 P2-3：统一凭证可见性聚合。不迁移各源凭证存储
    （GEE=加密 SQLite 账号池；SSH HPC/Earthdata/FileBrowser=.env），
    仅收口「配置了没有 / 可用不可用」的管理可见性。
    """

    source_id: str
    """gee | ssh_hpc | earthdata | filebrowser"""

    display_name: str

    kind: str
    """account_pool=加密账号池；env_credential=环境变量凭证"""

    configured: bool
    """该源已具备可用凭证（账号池有启用账号 / 必需 env 字段齐全）"""

    detail: str
    """人类可读的就绪描述（不含任何明文密钥）"""

    account_count: int | None = None
    """账号池类：总账号数"""

    enabled_count: int | None = None
    """账号池类：启用账号数"""

    last_tested_at: str | None = None
    """账号池类：最近一次凭证测试时间"""

    last_test_status: str | None = None
    """账号池类：最近测试结果 ok/failed"""

    fields: dict[str, bool] = Field(default_factory=dict)
    """env 凭证类：字段名 → 是否已配置（只报布尔，不回显值）"""


class OnlineSourcesResponse(BaseModel):
    """统一在线源凭证状态响应。"""

    sources: list[OnlineSourceCredentialStatus] = Field(default_factory=list)
    count: int
