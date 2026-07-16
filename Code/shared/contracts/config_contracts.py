"""配置面 HTTP 请求/响应模型（供 FastAPI OpenAPI 与前端 gen:types 共用）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ApiKeyUpdateRequest(BaseModel):
    key_value: str
    display_name: str | None = None
    description: str | None = None
    enabled: bool = True


class ApiKeyToggleRequest(BaseModel):
    enabled: bool


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
    tested_at: str


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
    tested_at: str
