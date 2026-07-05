from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MapMode(str, Enum):
    mode_2d = "2d"
    mode_3d = "3d"


class LayerSourceType(str, Enum):
    demo = "demo"
    gee = "gee"
    cog = "cog"
    vector_tile = "vector_tile"
    algorithm_output = "algorithm_output"


class LayerRenderType(str, Enum):
    raster = "raster"
    vector = "vector"
    point = "point"
    heatmap = "heatmap"


class TimeGranularity(str, Enum):
    hour = "hour"
    day = "day"
    month = "month"


class TaskType(str, Enum):
    layer_preview = "layer_preview"
    analysis = "analysis"
    export = "export"


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class BoundingBox(BaseModel):
    west: float
    south: float
    east: float
    north: float
    crs: str = "EPSG:4326"


class LayerStyleHint(BaseModel):
    palette: str | None = None
    unit_label: str | None = None
    opacity: float = 1.0


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
    tags: list[str] = Field(default_factory=list)


class LayerCatalogResponse(BaseModel):
    items: list[LayerDescriptor]


class DemoAvailabilityState(str, Enum):
    empty = "empty"
    partial = "partial"
    ready = "ready"


class DemoDataStateMode(str, Enum):
    demo = "demo"
    placeholder = "placeholder"
    mixed = "mixed"


class DemoFieldAliasMap(BaseModel):
    metric_value: list[str]
    hotspot_value: list[str]
    observation_time: list[str]
    status_label: list[str]


class DemoLayerSnapshot(BaseModel):
    layer_id: str
    display_name: str
    category: str
    metric_label: str
    metric_unit: str
    metric_precision: int
    update_label: str
    source_label: str
    accent_color: str
    accent_glow: str
    chip_tone: str
    data_state_mode: DemoDataStateMode
    data_state_label: str
    empty_state_label: str
    availability_state: DemoAvailabilityState
    trend_label: str
    summary: str
    status_label: str
    confidence_label: str
    requested_hour: float
    field_aliases: DemoFieldAliasMap
    raw_payload: dict[str, Any]


class DemoLayerSnapshotsResponse(BaseModel):
    requested_hour: float
    items: list[DemoLayerSnapshot]


class SpatialFilter(BaseModel):
    filter_type: str = "bbox"
    bbox: BoundingBox | None = None
    region_code: str | None = None
    region_name: str | None = None


class TimeRange(BaseModel):
    start_at: datetime
    end_at: datetime
    granularity: TimeGranularity = TimeGranularity.hour


class TaskSubmitRequest(BaseModel):
    layer_id: str
    task_type: TaskType = TaskType.analysis
    map_mode: MapMode = MapMode.mode_2d
    spatial_filter: SpatialFilter
    time_range: TimeRange
    parameters: dict[str, Any] = Field(default_factory=dict)
    requested_outputs: list[str] = Field(default_factory=lambda: ["json"])
    client_context: dict[str, Any] = Field(default_factory=dict)


class TaskAcceptedResponse(BaseModel):
    task_id: str
    status: TaskStatus
    status_url: str
    created_at: datetime
    message: str


class TaskResultReference(BaseModel):
    result_type: str
    mime_type: str
    inline_data: dict[str, Any] | None = None
    resource_url: str | None = None


class TaskStatusResponse(BaseModel):
    task_id: str
    layer_id: str
    task_type: TaskType
    status: TaskStatus
    progress: int
    message: str
    created_at: datetime
    updated_at: datetime
    spatial_filter: SpatialFilter
    time_range: TimeRange
    requested_outputs: list[str]
    result_refs: list[TaskResultReference] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class ExecutionStatus(str, Enum):
    accepted = "accepted"
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


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
    # M13 修复：旧字段保留向后兼容，标记 deprecated，新增引擎请使用 engine_kind + engine_requests
    algorithm_request: AlgorithmWorkflowRequest | dict[str, Any] = Field(default_factory=AlgorithmWorkflowRequest)
    gee_request: GeeWorkflowRequest | dict[str, Any] | None = None
    weather_request: WeatherWorkflowRequest | dict[str, Any] | None = None
    # 新扩展点：引擎无关的统一入口，避免每加一个引擎就新增 *_request 字段（OCP）
    # engine_kind 取值："gee" / "weather" / "algorithm" / "provider" / None
    # engine_requests: {engine_kind: request_dict}，支持多引擎并存
    engine_kind: str | None = None
    engine_requests: dict[str, dict[str, Any]] = Field(default_factory=dict)
    config_overrides: dict[str, Any] = Field(default_factory=dict)
    requested_outputs: list[ResultKind | str] = Field(default_factory=lambda: [ResultKind.json])
    client: ClientIdentity = Field(default_factory=ClientIdentity)
    map_context: RuntimeMapContext = Field(default_factory=RuntimeMapContext)
    correlation_id: str | None = None


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
    metric_label: str | None = None
    metric_value: float | int | str | None = None
    metric_unit: str | None = None
    hotspot_count: int | None = None
    availability_state: str | None = None
    data_state_mode: str | None = None
    result_category: str = "analysis"
    results: dict[str, str | None] = Field(default_factory=dict)


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


WorkflowResultDto = WorkflowAnalysisResultDto | WorkflowProviderResultDto | WorkflowDownloadResultDto | dict[str, Any]


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
    wind_speed_10m: float | None = None
    wind_direction_10m: float | None = None
    wind_gusts_10m: float | None = None


class WeatherPointHourlyEntry(BaseModel):
    time: datetime
    temperature_2m: float | None = None
    precipitation: float | None = None
    wind_speed_10m: float | None = None


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
