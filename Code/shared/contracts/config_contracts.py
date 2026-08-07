"""配置面 HTTP 请求/响应模型（供 FastAPI OpenAPI 与前端 gen:types 共用）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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


class GeeAccountCreateRequest(BaseModel):
    account_id: str
    service_account_json: dict
    display_name: str | None = None


class GeeAccountToggleRequest(BaseModel):
    enabled: bool


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
        description="默认 fastapi+worker+beat；不允许 docker/frontend",
    )


class ServiceRestartResponse(BaseModel):
    accepted: bool
    components: list[str]
    delay_seconds: float
    message: str
    ui_restart_enabled: bool
