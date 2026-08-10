"""配置面 HTTP 请求/响应模型（供 FastAPI OpenAPI 与前端 gen:types 共用）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
    minio: MinioPublicConfig | None = None
    discovered_datasets: list[DiscoveredDataset] = Field(default_factory=list)
    open_data_presets: dict[str, str] = Field(default_factory=dict)
    open_data_preset_labels: dict[str, str] = Field(default_factory=dict)
    portal_credentials: dict[str, PortalCredentialPublic] = Field(default_factory=dict)
    remote_layer_data_uris: dict[str, Any] = Field(default_factory=dict)
    static_cache: StaticCacheSummary | None = None
    workflow_hint: str | None = None


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


class DataSourcePathsUpdateRequest(BaseModel):
    """更新地理数据根 / 产物根（写入 Code/backend/.env，需重启后端生效）。"""

    data_root: str = Field(..., min_length=1, description="绝对路径且目录必须存在")
    output_root: str | None = Field(
        default=None,
        description="可选；留空则默认为 {data_root}/ProjectOutput",
    )


class DataSourcePathsUpdateResponse(BaseModel):
    data_root: str
    output_root: str
    effective_data_root: str
    effective_output_root: str
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
