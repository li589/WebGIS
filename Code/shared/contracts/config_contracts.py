"""配置面 HTTP 请求/响应模型（供 FastAPI OpenAPI 与前端 gen:types 共用）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyUpdateRequest(BaseModel):
    key_value: str
    display_name: str | None = None
    description: str | None = None
    enabled: bool = True
    """Optional label stored on the archived previous version when rotating."""
    history_label: str | None = None


class ApiKeyToggleRequest(BaseModel):
    enabled: bool


class ApiKeyHistoryItem(BaseModel):
    id: int
    key_name: str
    masked_value: str
    label: str | None = None
    created_at: datetime
    superseded_at: datetime
    source: str


class ApiKeyHistoryClearResponse(BaseModel):
    key_name: str
    deleted: int


class ApiKeyItem(BaseModel):
    """脱敏 API Key 列表项（GET /config/api-keys）。"""

    model_config = ConfigDict(extra="ignore")

    key_name: str
    display_name: str
    description: str | None = None
    masked_value: str = ""
    enabled: bool = False
    source: str | None = None
    has_value: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None
    last_tested_at: str | None = None
    last_test_status: str | None = None


class GeeAccountCreateRequest(BaseModel):
    account_id: str
    service_account_json: dict
    display_name: str | None = None


class GeeAccountToggleRequest(BaseModel):
    enabled: bool


class GeeAccountItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    account_id: str
    display_name: str | None = None
    project_id: str | None = None
    account_type: str = "service_account"
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""
    last_tested_at: str | None = None
    last_test_status: str | None = None


class GeeRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gee_enabled: bool
    max_parallel_exports: int
    max_parallel_uploads: int
    max_parallel_downloads: int
    account_cooldown_seconds: int
    storage_backend: str
    local_storage_root: str
    api_account_management_enabled: bool
    credentials_encryption_enabled: bool


class TestResultResponse(BaseModel):
    success: bool
    message: str


class ReloadResultResponse(BaseModel):
    success: bool
    account_count: int
    message: str


class WeatherProviderUpdateRequest(BaseModel):
    enabled: bool | None = None
    priority: int | None = None
    config: dict | None = None


class WeatherProviderToggleRequest(BaseModel):
    enabled: bool


class WeatherProviderPriorityRequest(BaseModel):
    priority: int = Field(..., ge=0)


class WeatherProviderTestResponse(BaseModel):
    provider_id: str
    success: bool
    message: str
    tested_at: datetime


class WeatherModelUpdateRequest(BaseModel):
    """全局默认天气模型（持久化到 DB，影响 coverage / 瓦片 / 点预报）。"""

    default_model: str = Field(..., min_length=1, description="如 ecmwf_ifs025")


class WeatherSyncCron(BaseModel):
    model_config = ConfigDict(extra="ignore")

    minute: str
    hour: str
    timezone: str = "UTC"


class WeatherSupportedModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str = ""
    region: str = ""
    update_interval: str = ""


class WeatherConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_model: str
    default_model_source: str | None = None
    sync_domains: list[str] = Field(default_factory=list)
    sync_enabled: bool | None = None
    sync_cron: WeatherSyncCron | None = None
    supported_models: list[WeatherSupportedModel] = Field(default_factory=list)
    model_in_sync_domains: bool | None = None
    cache_ttl_seconds: int
    refresh_forecast_hours: int
    schedule_enabled: bool
    default_latitude: float
    default_longitude: float
    default_place_name: str
    max_active_weather_tile_runs: int
    warning: str | None = None


class WeatherProviderStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    healthy: bool = False
    circuit_state: str = "n/a"
    last_error: str | None = None
    daily_quota: int | None = None
    daily_used: int | None = None
    daily_remaining: int | None = None
    cache_hits: int = 0
    cache_misses: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    enabled: bool | None = None


class WeatherProviderConfigField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    label: str = ""
    field_type: str = "string"
    required: bool = False
    default: Any = None
    description: str | None = None
    options: list[str] = Field(default_factory=list)
    placeholder: str | None = None


class WeatherProviderItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider_id: str
    display_name: str
    provider_type: str
    version: str = ""
    description: str = ""
    homepage_url: str | None = None
    requires_api_key: bool = False
    supported_capabilities: list[str] = Field(default_factory=list)
    priority: int = 0
    enabled: bool = True
    status: WeatherProviderStatus = Field(default_factory=WeatherProviderStatus)
    config_schema: list[WeatherProviderConfigField] = Field(default_factory=list)
    current_config: dict[str, Any] = Field(default_factory=dict)
    persisted_config: dict[str, Any] | None = None
    last_tested_at: str | None = None
    last_test_status: str | None = None
    is_builtin: bool = True


class MapAoiPreset(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    west: float
    south: float
    east: float
    north: float


class GeneralConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    environment: str
    host: str
    port: int
    service_name: str
    data_root: str = ""
    output_root: str = ""
    cache_dir: str = ""
    log_dir: str = ""
    log_level: str = "INFO"
    max_active_runs: int = 0
    max_requested_outputs: int = 0
    redis_url: str = ""
    storage_backend: str = "local"
    reload: bool = False
    max_active_weather_tile_runs: int | None = None
    weather_cache_ttl_seconds: int | None = None
    weather_refresh_forecast_hours: int | None = None
    cache_default_ttl_seconds: int | None = None
    provider_max_hotspots: int | None = None
    provider_max_series_points: int | None = None
    provider_table_chunk_size: int | None = None
    provider_series_chunk_size: int | None = None
    result_inline_max_bytes: int | None = None
    celery_task_soft_time_limit: int | None = None
    celery_task_time_limit: int | None = None
    celery_task_always_eager: bool | None = None
    celery_worker_concurrency: int | None = None
    celery_worker_prefetch_multiplier: int | None = None
    celery_worker_max_tasks_per_child: int | None = None
    workflow_node_parallelism: int | None = None
    algorithm_max_parallel_workers: int | None = None
    task_memory_budget_mb: int | None = None
    task_cpu_budget_cores: int | None = None
    cors_origins: list[str] | None = None
    object_store_backend: str | None = None
    object_store_public_base: str | None = None
    result_artifact_dir: str | None = None
    workflow_state_dir: str | None = None
    python_provider_root: str | None = None
    python_provider_workspace: str | None = None
    map_default_longitude: float | None = None
    map_default_latitude: float | None = None
    map_default_zoom: float | None = None
    map_default_tile_source: str | None = None
    map_aoi_presets: list[MapAoiPreset] | None = None


class MinioPublicConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    endpoint: str
    bucket: str
    secure: bool = False


class DiscoveredDataset(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    path: str
    file_count: int | None = None
    file_count_truncated: bool | None = None


class StaticCacheSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cache_root: str
    ttl_seconds: int
    ttl_unlimited: bool
    entry_count: int
    total_bytes: int


class PortalCredentialPublic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    auth_type: str = ""
    username: str = ""
    has_token: bool = False
    has_password: bool = False
    source: str | None = None
    use_for_nsidc: bool | None = None
    use_earthdata: bool | None = None
    client_id: str | None = None
    account_count: int = 0


class OnlineTileSource(BaseModel):
    """用户注册的 WMTS/XYZ 在线瓦片源（不包含明文密钥）。"""

    model_config = ConfigDict(extra="ignore")

    source_id: str
    display_name: str
    service_type: Literal["wmts", "xyz"]
    url_template: str
    layer: str = ""
    style: str = "default"
    tile_matrix_set: str = ""
    image_format: str = "image/png"
    coordinate_system: str = "EPSG:3857"
    auth_ref: str | None = None
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""
    last_test_status: str | None = None
    last_tested_at: str | None = None
    config_status: str = "configured"


class OnlineTileSourceUpsertRequest(BaseModel):
    """PUT /config/online-tile-sources/{source_id} body."""

    model_config = ConfigDict(extra="ignore")

    display_name: str = Field(..., min_length=1, max_length=120)
    service_type: Literal["wmts", "xyz"]
    url_template: str = Field(..., min_length=1, max_length=2000)
    layer: str = ""
    style: str = "default"
    tile_matrix_set: str = ""
    image_format: str = "image/png"
    coordinate_system: str = "EPSG:3857"
    auth_ref: str | None = None
    enabled: bool = True


class DataSourceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    storage_backend: str
    data_root: str = ""
    output_root: str = ""
    env_data_root: str | None = None
    env_output_root: str | None = None
    pending_restart: bool | None = None
    ui_restart_enabled: bool | None = None
    download_source_root: str = ""
    download_real_fetch_enabled: bool = False
    tile_proxy_enabled: bool = False
    tile_proxy_cache_ttl_seconds: int = 0
    static_cache_root: str = ""
    cache_dir: str = ""
    minio: MinioPublicConfig | None = None
    discovered_datasets: list[DiscoveredDataset] = Field(default_factory=list)
    available_datasets: list[AvailableDatasetEntry] = Field(default_factory=list)
    open_data_presets: dict[str, str] = Field(default_factory=dict)
    open_data_preset_labels: dict[str, str] = Field(default_factory=dict)
    portal_credentials: dict[str, PortalCredentialPublic] = Field(default_factory=dict)
    remote_layer_data_uris: dict[str, Any] = Field(default_factory=dict)
    static_cache: StaticCacheSummary | None = None
    workflow_hint: str | None = None
    online_tile_sources: list[OnlineTileSource] = Field(default_factory=list)


class AvailableDatasetEntry(BaseModel):
    """可用数据集注册表条目（available_datasets 表行）。"""

    model_config = ConfigDict(extra="ignore")

    dataset_id: str
    logical_name: str
    path: str
    file_format: str = ""
    variables: list[str] = Field(default_factory=list)
    time_range: str = ""
    resolution: str = ""
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    source: str = "manual"
    enabled: bool = True
    file_count: int | None = None
    last_scanned_at: str | None = None
    created_at: str = ""
    updated_at: str = ""


class DatasetUpsertRequest(BaseModel):
    """PUT /config/data-source/datasets/{dataset_id} body。

    dataset_id 传 "new"（或空）时创建新条目；logical_name 冲突且非同一条目返回 400。
    source=algorithm_registry 条目：仅 path/描述/启停/元数据可改，改名/删除被拒。
    """

    model_config = ConfigDict(extra="ignore")

    logical_name: str
    path: str
    file_format: str | None = None
    variables: list[str] | None = None
    time_range: str | None = None
    resolution: str | None = None
    tags: list[str] | None = None
    description: str | None = None
    enabled: bool = True


class DatasetRescanResponse(BaseModel):
    root: str = ""
    created: int = 0
    created_names: list[str] = Field(default_factory=list)
    refreshed: int = 0
    entries: list[AvailableDatasetEntry] = Field(default_factory=list)


class RemoteSourceRefBadge(BaseModel):
    """引用源能力徽标（存储 profile 或门户）。"""

    model_config = ConfigDict(extra="ignore")

    protocol: str | None = None
    enabled: bool | None = None
    last_test_status: str | None = None
    display_name: str = ""
    search_capability: str | None = None
    requires_credentials: bool | None = None
    name: str = ""


class RemoteSourceEntry(BaseModel):
    """「可访问远程数据源」别名条目 + 引用源能力。"""

    model_config = ConfigDict(extra="ignore")

    remote_source_id: str
    kind: str
    ref_id: str
    remote_path: str = ""
    display_name: str = ""
    cache_policy: str = "standard"
    # Phase 4：访问模式（legacy/site_compatible）+ 归档标记
    access_mode: str = "legacy"
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""
    ref: RemoteSourceRefBadge | None = None
    ref_exists: bool = False


class RemoteSourceUpsertRequest(BaseModel):
    """PUT /config/remote-sources/{remote_source_id} body."""

    model_config = ConfigDict(extra="ignore")

    kind: str
    ref_id: str
    remote_path: str = ""
    display_name: str = ""
    cache_policy: str = "standard"
    # Phase 4：访问模式（legacy/site_compatible）+ 归档
    access_mode: str = "legacy"
    archived: bool = False


class RemoteDatasetGrant(BaseModel):
    """「具体数据集选取模式」授权条目 + 门户能力徽标。"""

    model_config = ConfigDict(extra="ignore")

    grant_id: str
    portal_id: str
    dataset_key: str
    dataset_title: str = ""
    dataset_description: str = ""
    provider_kind: str = ""
    time_start: str = ""
    time_end: str = ""
    path_prefix: str = ""
    search_meta: str = "{}"
    enabled: bool = True
    archived: bool = False
    migrated_from: str = ""
    created_at: str = ""
    updated_at: str = ""
    ref: RemoteSourceRefBadge | None = None
    ref_exists: bool = False


class RemoteDatasetGrantUpsertRequest(BaseModel):
    """PUT /config/remote-datasets/grants/{grant_id} body.

    grant_id 可省略（由 portal_id/dataset_key 派生）；
    UNIQUE(portal_id, dataset_key) 冲突时幂等合并到既有条目。
    """

    model_config = ConfigDict(extra="ignore")

    portal_id: str
    dataset_key: str
    dataset_title: str = ""
    dataset_description: str = ""
    provider_kind: str = ""
    time_start: str = ""
    time_end: str = ""
    path_prefix: str = ""
    search_meta: str = "{}"
    enabled: bool = True


class RemoteDatasetPolicyDataset(BaseModel):
    """策略投影中的单条数据集（编辑器下拉/校验用）。"""

    model_config = ConfigDict(extra="ignore")

    grant_id: str = ""
    dataset_key: str
    title: str = ""
    path_prefix: list[str] = Field(default_factory=list)


class RemoteDatasetPolicy(BaseModel):
    """单门户的远程数据集访问策略投影（GET /config/remote-datasets/policy）。

    未出现在列表中的门户 = 未管控 → 消费方放行。
    """

    model_config = ConfigDict(extra="ignore")

    portal_id: str
    managed: bool = True
    compatible: bool = False
    datasets: list[RemoteDatasetPolicyDataset] = Field(default_factory=list)


class MigrationReport(BaseModel):
    """存量迁移报告（GET /config/remote-sources/migrate-legacy）。"""

    model_config = ConfigDict(extra="ignore")

    dry_run: bool
    total: int
    migrated_to_grants: int
    upgraded_site_compatible: int
    kept_legacy: int
    already_done: bool
    safe_mode: bool
    details: list[dict[str, Any]] = Field(default_factory=list)


class RegisterAndAddRequest(BaseModel):
    """POST /config/remote-sources/register-and-add body（2026-08-25 P2）。

    原子完成「注册 + 数据集记录 + 工作流编排提示」：
    - 注册 remote_source（统一 site_compatible 整源）；
    - dataset_keys 逐条写入 remote_dataset_grants（一键上图选集记录，
      不限制整源访问——用户决策 2026-08-25）；
    - 有门户→工作流映射时返回 workflow_hint（Wave 2 引导/后续自动链）。
    """

    model_config = ConfigDict(extra="ignore")

    alias: str
    kind: str  # 'portal' | 'storage_profile'
    ref_id: str
    display_name: str = ""
    remote_path: str = ""
    # 选中数据集（空 = 整源注册，或用映射默认数据集）
    dataset_keys: list[str] = Field(default_factory=list)


class WorkflowHint(BaseModel):
    """门户→工作流映射的编排提示（portal_workflow_map.build_workflow_hint）。"""

    model_config = ConfigDict(extra="ignore")

    workflow: str
    node_type: str
    # 有种子层（engine=python_provider）时非空——自动链直接提交该层工作流
    layer_id: str | None = None
    dataset_keys: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    auto_chain_ready: bool = False


class RegisterAndAddResponse(BaseModel):
    """register-and-add 响应：注册结果 + 数据集记录 + 工作流提示。

    auto_chain 生效（hint.layer_id 存在）时 run_id 非空——已自动提交
    「下载→预处理→烘焙→入图层库」工作流，前端可轮询 run 状态。
    """

    model_config = ConfigDict(extra="ignore")

    remote_source: RemoteSourceEntry
    grants: list["RemoteDatasetGrant"] = Field(default_factory=list)
    workflow_hint: WorkflowHint | None = None
    # 自动链提交的 workflow run（未提交/提交失败降级时为 None）
    run_id: str | None = None
    # 自动链提交失败原因（降级提示用；成功时为空）
    auto_chain_message: str = ""


class DataCacheEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    path: str
    size_bytes: int
    mtime: float
    age_seconds: int


class DataCacheOverview(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cache_root: str
    ttl_seconds: int
    ttl_unlimited: bool
    entry_count: int
    total_bytes: int
    entries: list[DataCacheEntry] = Field(default_factory=list)
    data_root: str = ""
    output_root: str = ""
    discovered_datasets: list[DiscoveredDataset] = Field(default_factory=list)


class AboutModule(BaseModel):
    name: str
    description: str


class AboutInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_name: str
    version: str
    description: str
    tech_stack: list[str] = Field(default_factory=list)
    modules: list[AboutModule] = Field(default_factory=list)
    architecture_summary: str = ""


class RemoteStorageUpsertRequest(BaseModel):
    protocol: str
    host: str = ""
    port: int | None = None
    username: str | None = None
    secret: str | None = None
    private_key_pem: str | None = None
    domain: str | None = None
    # None preserves existing extra on update; {} clears protocol extras
    extra: dict | None = None
    display_name: str | None = None
    # None preserves existing enabled flag on update
    enabled: bool | None = None
    # 双路径（合并写入 extra.alt；任一字段非 None 即触发合并，None 的字段保留原值；
    # host/url 置空字符串清除对应备用字段；port 传 0 显式清除备用端口）
    alt_host: str | None = Field(
        default=None, description="备用访问路径主机/URL（隧道），写入 extra.alt.host"
    )
    alt_port: int | None = Field(
        default=None,
        description="备用访问路径端口，写入 extra.alt.port；0 表示显式清除",
    )
    alt_url: str | None = Field(
        default=None,
        description="备用 base URL（http/https/filebrowser），写入 extra.alt.url",
    )
    fallback_mode: str | None = Field(
        default=None, description="回退模式 auto|manual|off，写入 extra.fallback_mode"
    )


class RemoteStorageToggleRequest(BaseModel):
    enabled: bool


class RemoteStorageTestRequest(BaseModel):
    """Optional probe URI; defaults to protocol://host/."""

    uri: str | None = None


class RemoteStorageTestResponse(BaseModel):
    profile_id: str
    success: bool
    message: str
    tested_at: datetime


class RemoteStorageHistoryItem(BaseModel):
    id: int
    profile_id: str
    masked_secret: str
    has_private_key: bool = False
    label: str | None = None
    created_at: datetime
    superseded_at: datetime
    source: str


class RemoteStorageHistoryClearResponse(BaseModel):
    profile_id: str
    deleted: int


class RemoteStorageProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    profile_id: str
    protocol: str
    host: str = ""
    port: int | None = None
    username: str | None = None
    has_secret: bool = False
    has_private_key: bool = False
    domain: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    display_name: str = ""
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""
    last_tested_at: str | None = None
    last_test_status: str | None = None
    # 双路径便捷回显（真源在 extra.alt / extra.fallback_mode / extra.failover_state）
    alt_host: str = ""
    alt_port: int | None = None
    alt_url: str = ""
    fallback_mode: str = "auto"
    failover_state: dict[str, Any] = Field(default_factory=dict)


class RemoteEntryItem(BaseModel):
    """远程目录条目（浏览/搜索通用）。"""

    name: str
    is_dir: bool = False
    size: int | None = None
    mtime: float | None = None
    path: str | None = None


class RemoteBrowseRequest(BaseModel):
    path: str = "/"


class RemoteBrowseResponse(BaseModel):
    profile_id: str
    protocol: str
    path: str
    via: str = Field(description="本次实际使用的路径：primary | alt")
    items: list[RemoteEntryItem] = Field(default_factory=list)


class RemoteSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    max_results: int = Field(default=200, ge=1, le=500)
    start_path: str = Field(
        default="/", description="搜索起点目录（默认根；用于在当前目录子树内搜索）"
    )


class RemoteSearchResponse(BaseModel):
    profile_id: str
    protocol: str
    query: str
    start_path: str = "/"
    via: str
    items: list[RemoteEntryItem] = Field(default_factory=list)
    truncated: bool = Field(
        default=False, description="结果已达 max_results 上限，可能存在未扫到的匹配"
    )
    failed_dirs: int = Field(
        default=0, description="递归扫描中列举失败的子目录数（部分结果）"
    )


class RemoteFailoverRequest(BaseModel):
    target: str = Field(..., pattern="^(primary|alt)$")


class RemoteFailoverResponse(BaseModel):
    profile_id: str
    active: str
    updated: bool
    message: str


class DataSourcePathsUpdateRequest(BaseModel):
    """更新地理数据根 / 产物根（写入 Code/backend/.env，需重启后端生效）。"""

    data_root: str = Field(..., min_length=1, description="绝对路径且目录必须存在")
    output_root: str | None = Field(
        default=None,
        description="可选；留空则默认为 {data_root}/ProjectOutput",
    )
    static_cache_root: str | None = Field(
        default=None,
        description="可选；静态下载缓存根（BACKEND_STATIC_CACHE_ROOT），不存在时自动创建",
    )
    cache_dir: str | None = Field(
        default=None,
        description="可选；通用缓存目录（BACKEND_CACHE_DIR），不存在时自动创建",
    )
    download_source_root: str | None = Field(
        default=None,
        description="可选；下载源根目录（BACKEND_DOWNLOAD_SOURCE_ROOT），不存在时自动创建",
    )


class DataSourcePathsUpdateResponse(BaseModel):
    data_root: str
    output_root: str
    effective_data_root: str
    effective_output_root: str
    static_cache_root: str | None = None
    cache_dir: str | None = None
    download_source_root: str | None = None
    pending_restart: bool
    env_path: str
    message: str


class ServiceRestartRequest(BaseModel):
    components: list[str] | None = Field(
        default=None,
        description=(
            "Advisory only today: values are validated (fastapi|worker|beat) but "
            "the server always restarts the full backend group. "
            "docker/frontend are rejected."
        ),
    )


class ServiceRestartResponse(BaseModel):
    accepted: bool
    components: list[str]
    delay_seconds: float
    message: str
    ui_restart_enabled: bool


class PortalCredentialsMapResponse(BaseModel):
    portal_credentials: dict[str, PortalCredentialPublic]


class PortalCredentialAccount(BaseModel):
    """多账号轮换条目（NSMC 等限额门户）。"""

    model_config = ConfigDict(extra="ignore")

    username: str = ""
    token: str = ""
    password: str = ""


class PortalCredentialUpsertRequest(BaseModel):
    """PUT /config/data-source/portal-credentials/{portal_id} body."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool | None = None
    auth_type: str | None = None
    username: str | None = None
    token: str | None = None
    password: str | None = None
    client_id: str | None = None
    token_header: str | None = None
    use_for_nsidc: bool | None = None
    use_earthdata: bool | None = None
    clear_secrets: bool | None = None
    accounts: list[PortalCredentialAccount] | None = None


class PortalDef(BaseModel):
    """门户目录条目元数据（内置与自定义统一）。"""

    model_config = ConfigDict(extra="ignore")

    portal_id: str
    name: str
    organization: str = ""
    region: str = Field(
        default="international", description="international | china"
    )
    base_url: str
    alt_url: str | None = None
    website: str = ""
    description: str = ""
    requires_credentials: bool = False
    auth_type: str = Field(
        default="none", description="bearer | basic | header | token | none"
    )
    token_header: str | None = None
    credential_profile: str = Field(
        default="", description="凭据键（规范 id）；空 = portal_id 自身"
    )
    credentials_hint: str = ""
    search_capability: str = Field(default="none", description="cmr | none")
    builtin: bool = True


class PortalCatalogEntry(PortalDef):
    """目录条目 + 运行时状态（URL 覆盖 / 凭据状态）。"""

    effective_base_url: str = ""
    base_url_overridden: bool = False
    effective_alt_url: str | None = None
    has_credentials: bool = False
    credential_source: str = "none"
    account_count: int = 0


class PortalCatalogResponse(BaseModel):
    portals: list[PortalCatalogEntry] = Field(default_factory=list)


class PortalUpsertRequest(BaseModel):
    """PUT /config/portals/{portal_id} body。

    builtin 门户：仅 base_url（覆盖 open_data_presets）与 alt_url 生效，空串清除覆盖；
    自定义门户：全字段创建/更新（name/base_url 必填）。
    """

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    organization: str | None = None
    region: str | None = None
    base_url: str | None = None
    alt_url: str | None = None
    website: str | None = None
    description: str | None = None
    requires_credentials: bool | None = None
    auth_type: str | None = None
    token_header: str | None = None
    credential_profile: str | None = None
    credentials_hint: str | None = None
    search_capability: str | None = None


class PortalTestResponse(BaseModel):
    portal_id: str
    ok: bool
    status_code: int | None = None
    via_credentials: bool = False
    message: str
    tested_url: str = ""


class PortalSearchDatasetItem(BaseModel):
    """在线检索结果条目（数据集级，plan 阶段 2 数据集化改造）。

    dataset_key 为白名单主键（CMR short_name / CDSE 任务_产品模式 / CDS collection id）；
    extra 携带 provider 特定信息（version/data_center/count/sample_product_id/data_link 等）。
    """

    model_config = ConfigDict(extra="ignore")

    dataset_key: str
    title: str = ""
    description: str = ""
    time_start: str = ""
    time_end: str = ""
    provider_kind: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class PortalSearchResponse(BaseModel):
    portal_id: str
    query: str
    page_size: int = 20
    count: int = 0
    items: list[PortalSearchDatasetItem] = Field(default_factory=list)


class DataCacheEvictRequest(BaseModel):
    uri_or_name: str | None = None
    older_than_seconds: int | None = None


class DataCacheEvictResponse(BaseModel):
    removed: list[str] = Field(default_factory=list)
    cache_root: str
    removed_count: int | None = None


class OpenDataPresetsUpdateRequest(BaseModel):
    open_data_presets: dict[str, str]


class OpenDataPresetsUpdateResponse(BaseModel):
    open_data_presets: dict[str, str]


class RemoteLayerUrisUpdateRequest(BaseModel):
    remote_layer_data_uris: dict[str, Any]


class RemoteLayerUrisUpdateResponse(BaseModel):
    remote_layer_data_uris: dict[str, dict[str, list[str]]]


class DeletedResponse(BaseModel):
    deleted: bool


class ApiKeyDeletedResponse(DeletedResponse):
    key_name: str


class ApiKeyHistoryDeletedResponse(DeletedResponse):
    key_name: str
    history_id: int


class GeeAccountDeletedResponse(DeletedResponse):
    account_id: str


class WeatherProviderDeletedResponse(DeletedResponse):
    provider_id: str


class RemoteStorageDeletedResponse(DeletedResponse):
    profile_id: str


class RemoteStorageHistoryDeletedResponse(DeletedResponse):
    profile_id: str
    history_id: int


class ApiKeyToggleResponse(BaseModel):
    key_name: str
    enabled: bool


class GeeAccountToggleResponse(BaseModel):
    account_id: str
    enabled: bool


class WeatherProviderToggleResponse(BaseModel):
    provider_id: str
    enabled: bool


class WeatherProviderPriorityResponse(BaseModel):
    provider_id: str
    priority: int


class RemoteStorageToggleResponse(BaseModel):
    profile_id: str
    enabled: bool


# ── 部署与数据源配置中心（deployment.config.json）────────────────────────────


class DeploymentDataGroup(BaseModel):
    """data 组：数据根与导入导出。空串/None = 未设置（不覆盖）。"""

    data_root: str | None = Field(default=None, description="地理数据根目录（绝对路径，必须已存在）")
    output_root: str | None = Field(default=None, description="产出结果/报告/分析图表输出根（绝对路径，必须已存在）")
    project_backup_root: str | None = Field(default=None, description="项目备份根（绝对路径）")


class DeploymentRuntimeGroup(BaseModel):
    """runtime 组：运行时目录与日志。"""

    runtime_root: str | None = Field(default=None, description="运行时根；未设时派生自 <data_root>/_runtime")
    workflow_state_dir: str | None = Field(default=None, description="工作流状态目录")
    log_dir: str | None = Field(default=None, description="后端日志目录")
    log_level: str | None = Field(default=None, description="DEBUG | INFO | WARNING | ERROR")
    result_artifact_dir: str | None = Field(default=None, description="工作流产物/工件目录")
    python_provider_workspace: str | None = Field(default=None, description="Python 算法工作区")
    spatialite_db_path: str | None = Field(default=None, description="SpatiaLite 数据库文件路径")


class DeploymentCachesGroup(BaseModel):
    """caches 组：各类缓存与下载源。"""

    cache_dir: str | None = Field(default=None, description="通用缓存目录（不存在时自动创建）")
    static_cache_root: str | None = Field(default=None, description="静态物化缓存根")
    static_cache_ttl_seconds: int | None = Field(default=None, ge=0, description="静态缓存 TTL 秒（0=永不过期）")
    download_source_root: str | None = Field(default=None, description="真实数据保存与下载位置")
    cache_default_ttl_seconds: int | None = Field(default=None, ge=0, description="默认缓存 TTL 秒")
    tile_proxy_cache_ttl_seconds: int | None = Field(default=None, ge=0, description="瓦片代理缓存 TTL 秒")


class DeploymentImportsGroup(BaseModel):
    """imports 组：导入配额（字节）。"""

    max_imports_total_bytes: int | None = Field(default=None, ge=1, description="导入永久层总配额")
    imports_soft_reserve_bytes: int | None = Field(default=None, ge=0, description="导入软预留（0=禁用）")


class DeploymentDockerGroup(BaseModel):
    """docker 组：Docker / Open-Meteo（部分键需全量 restart）。"""

    minio_root_user: str | None = Field(default=None, description="MinIO root 用户")
    minio_root_password: str | None = Field(default=None, description="MinIO root 密码（留空保持不变，回显恒脱敏）")
    open_meteo_host_port: int | None = Field(default=None, ge=1, le=65535, description="Open-Meteo 宿主端口")
    open_meteo_data_volume: str | None = Field(default=None, description="Open-Meteo 共享 named volume 名")
    open_meteo_sync_domains: str | None = Field(default=None, description="同步气象模型（逗号分隔）")
    open_meteo_sync_variables: str | None = Field(default=None, description="同步变量列表（逗号分隔）")
    open_meteo_local_url: str | None = Field(default=None, description="Open-Meteo 本地 API URL（http(s)）")


class DeploymentConfigUpdateRequest(BaseModel):
    """部署配置整体写入请求（preview 与 PUT 共用）。"""

    schema_version: int = Field(default=1, description="配置 schema 版本（当前 1）")
    data: DeploymentDataGroup | None = None
    runtime: DeploymentRuntimeGroup | None = None
    caches: DeploymentCachesGroup | None = None
    imports: DeploymentImportsGroup | None = None
    docker: DeploymentDockerGroup | None = None
    notes: str | None = Field(default=None, description="备注（部署说明等）")


class DeploymentKeyValueStatus(BaseModel):
    """单键三方状态：运行值 / .env 值 / deployment.json 值。"""

    group: str
    group_label: str
    key: str
    env_key: str
    kind: str
    label: str
    restart_level: str
    must_exist: bool
    sensitive: bool
    double_write_sync: bool
    runtime_value: str
    env_value: str
    config_value: str
    source: str
    pending: bool


class DeploymentBackupInfo(BaseModel):
    name: str
    path: str
    size_bytes: int
    mtime: float


class DeploymentConfigStatus(BaseModel):
    path: str
    exists: bool
    schema_version: int
    applied_env_keys: list[str]
    keys: list[DeploymentKeyValueStatus]
    backups: list[DeploymentBackupInfo]
    pending_restart: bool
    env_path: str
    sync_env_path: str
    notes: str = ""


class DeploymentPreviewDiffItem(BaseModel):
    group: str
    key: str
    env_key: str
    old: str
    new: str
    restart_level: str
    derived: bool = False


class DeploymentConfigPreviewResponse(BaseModel):
    ok: bool
    errors: list[str]
    warnings: list[str]
    diff: list[DeploymentPreviewDiffItem]
    restart_level: str


class DeploymentConfigUpdateResponse(BaseModel):
    applied_env_keys: list[str]
    sync_env_keys: list[str]
    config_path: str
    env_path: str
    sync_env_path: str | None = None
    restart_level: str
    pending_restart: bool
    warnings: list[str]
    backups: list[str]
    message: str
