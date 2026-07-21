"""
配置管理 API 路由

提供以下端点：
- GET /config/general — 获取常规配置
- GET /config/api-keys — 列出 API Key
- PUT /config/api-keys/{key_name} — 新增/更新 API Key
- DELETE /config/api-keys/{key_name} — 删除 API Key
- POST /config/api-keys/{key_name}/test — 测试 API Key
- PUT /config/api-keys/{key_name}/toggle — 启用/禁用
- GET /config/api-keys/{key_name}/history — 密钥历史（脱敏）
- POST /config/api-keys/{key_name}/history/{history_id}/restore — 恢复历史版本
- DELETE /config/api-keys/{key_name}/history/{history_id} — 删除单条历史
- DELETE /config/api-keys/{key_name}/history — 清空历史
- GET /config/gee/accounts — 列出 GEE 账户
- POST /config/gee/accounts — 新增 GEE 账户
- DELETE /config/gee/accounts/{account_id} — 删除 GEE 账户
- POST /config/gee/accounts/{account_id}/test — 测试 GEE 账户
- PUT /config/gee/accounts/{account_id}/toggle — 启用/禁用
- POST /config/gee/accounts/reload — 重载账户池
- GET /config/gee/runtime — GEE 运行时配置
- GET /config/weather — 天气 API 配置
- PUT /config/weather/model — 更新全局默认天气模型（DB 持久化）
- GET /config/weather/providers — 列出天气源 Provider
- GET /config/weather/providers/{provider_id} — 获取单个 Provider 详情
- PUT /config/weather/providers/{provider_id} — 更新 Provider 配置
- POST /config/weather/providers/{provider_id}/test — 测试 Provider 连通性
- PUT /config/weather/providers/{provider_id}/toggle — 启用/禁用 Provider
- PUT /config/weather/providers/{provider_id}/priority — 调整 Provider 优先级
- DELETE /config/weather/providers/{provider_id} — 删除 Provider DB 配置
- GET /config/remote-storage — 列出远程存储凭证 Profile
- PUT /config/remote-storage/{profile_id} — 新增/更新 Profile
- DELETE /config/remote-storage/{profile_id} — 删除 Profile
- PUT /config/remote-storage/{profile_id}/toggle — 启用/禁用
- POST /config/remote-storage/{profile_id}/test — 测试连通性
- GET /config/data-source — 数据源配置
- GET /config/about — 项目信息
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_gee_account_management_enabled, require_write_access
from app.services import config_service
from shared.contracts.config_contracts import (
    ApiKeyHistoryClearResponse,
    ApiKeyHistoryItem,
    ApiKeyToggleRequest,
    ApiKeyUpdateRequest,
    GeeAccountCreateRequest,
    GeeAccountToggleRequest,
    ReloadResultResponse,
    RemoteStorageHistoryClearResponse,
    RemoteStorageHistoryItem,
    RemoteStorageTestRequest,
    RemoteStorageTestResponse,
    RemoteStorageToggleRequest,
    RemoteStorageUpsertRequest,
    TestResultResponse,
    WeatherProviderPriorityRequest,
    WeatherProviderTestResponse,
    WeatherProviderToggleRequest,
    WeatherProviderUpdateRequest,
    WeatherModelUpdateRequest,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


# ── 常规配置 ──────────────────────────────────────────────────────────────────

@router.get("/general")
async def get_general_config():
    """获取常规配置（脱敏）。"""
    return config_service.get_general_config()


# ── API Key 管理 ──────────────────────────────────────────────────────────────

@router.get("/api-keys")
async def list_api_keys():
    """列出所有 API Key（脱敏）。"""
    return config_service.list_api_keys()


@router.put("/api-keys/{key_name}", dependencies=[Depends(require_write_access)])
async def update_api_key(key_name: str, request: ApiKeyUpdateRequest):
    """新增或更新 API Key。"""
    if not request.key_value.strip():
        raise HTTPException(status_code=400, detail="key_value 不能为空")
    result = config_service.upsert_api_key(
        key_name=key_name,
        key_value=request.key_value.strip(),
        display_name=request.display_name,
        description=request.description,
        enabled=request.enabled,
        history_label=request.history_label,
    )
    if not result:
        raise HTTPException(status_code=500, detail="保存失败")
    return result


@router.delete("/api-keys/{key_name}", dependencies=[Depends(require_write_access)])
async def delete_api_key(key_name: str):
    """删除 API Key。"""
    deleted = config_service.delete_api_key(key_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"API Key '{key_name}' 不存在")
    return {"deleted": True, "key_name": key_name}


@router.post(
    "/api-keys/{key_name}/test",
    response_model=TestResultResponse,
    dependencies=[Depends(require_write_access)],
)
async def test_api_key(key_name: str):
    """测试 API Key 是否有效。"""
    success, message = await config_service.test_api_key(key_name)
    return TestResultResponse(success=success, message=message)


@router.put("/api-keys/{key_name}/toggle", dependencies=[Depends(require_write_access)])
async def toggle_api_key(key_name: str, request: ApiKeyToggleRequest):
    """启用/禁用 API Key。无值时返回 400；env-only 会物化到 DB。"""
    try:
        return config_service.toggle_api_key(key_name, request.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/api-keys/{key_name}/history",
    response_model=list[ApiKeyHistoryItem],
    dependencies=[Depends(require_write_access)],
)
async def list_api_key_history(key_name: str):
    """列出密钥历史版本（脱敏）。"""
    return config_service.list_api_key_history(key_name)


@router.post(
    "/api-keys/{key_name}/history/{history_id}/restore",
    dependencies=[Depends(require_write_access)],
)
async def restore_api_key_history(key_name: str, history_id: int):
    """将历史版本恢复为当前密钥。"""
    try:
        return config_service.restore_api_key_history(key_name, history_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/api-keys/{key_name}/history/{history_id}",
    dependencies=[Depends(require_write_access)],
)
async def delete_api_key_history_entry(key_name: str, history_id: int):
    deleted = config_service.delete_api_key_history_entry(key_name, history_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"历史记录 #{history_id} 不存在")
    return {"deleted": True, "key_name": key_name, "history_id": history_id}


@router.delete(
    "/api-keys/{key_name}/history",
    response_model=ApiKeyHistoryClearResponse,
    dependencies=[Depends(require_write_access)],
)
async def clear_api_key_history(key_name: str):
    deleted = config_service.clear_api_key_history(key_name)
    return ApiKeyHistoryClearResponse(key_name=key_name, deleted=deleted)


# ── GEE 账户管理 ──────────────────────────────────────────────────────────────

@router.get("/gee/accounts")
async def list_gee_accounts():
    """列出所有 GEE 账户（脱敏）。"""
    return config_service.list_gee_accounts()


@router.post(
    "/gee/accounts",
    dependencies=[Depends(require_write_access), Depends(require_gee_account_management_enabled)],
)
async def create_gee_account(request: GeeAccountCreateRequest):
    """新增 GEE 账户。"""
    if not request.account_id.strip():
        raise HTTPException(status_code=400, detail="account_id 不能为空")
    if not request.service_account_json:
        raise HTTPException(status_code=400, detail="service_account_json 不能为空")

    # 验证 JSON 包含必要字段
    required_fields = ("client_email", "private_key", "private_key_id")
    missing = [f for f in required_fields if f not in request.service_account_json]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"service_account_json 缺少必要字段: {missing}",
        )

    try:
        result = config_service.add_gee_account(
            account_id=request.account_id.strip(),
            service_account_json=request.service_account_json,
            display_name=request.display_name,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("[config_routes] Failed to add GEE account: %s", request.account_id)
        raise HTTPException(status_code=500, detail="添加 GEE 账户时发生内部错误，请检查日志")


@router.delete(
    "/gee/accounts/{account_id}",
    dependencies=[Depends(require_write_access), Depends(require_gee_account_management_enabled)],
)
async def delete_gee_account(account_id: str):
    """删除 GEE 账户。"""
    deleted = config_service.delete_gee_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"GEE 账户 '{account_id}' 不存在")
    return {"deleted": True, "account_id": account_id}


@router.post(
    "/gee/accounts/{account_id}/test",
    response_model=TestResultResponse,
    dependencies=[Depends(require_write_access)],
)
async def test_gee_account(account_id: str):
    """测试 GEE 账户凭证是否有效。"""
    success, message = await config_service.test_gee_account(account_id)
    return TestResultResponse(success=success, message=message)


@router.put(
    "/gee/accounts/{account_id}/toggle",
    dependencies=[Depends(require_write_access), Depends(require_gee_account_management_enabled)],
)
async def toggle_gee_account(account_id: str, request: GeeAccountToggleRequest):
    """启用/禁用 GEE 账户。"""
    toggled = config_service.toggle_gee_account(account_id, request.enabled)
    if not toggled:
        raise HTTPException(status_code=404, detail=f"GEE 账户 '{account_id}' 不存在")
    return {"account_id": account_id, "enabled": request.enabled}


@router.post(
    "/gee/accounts/reload",
    response_model=ReloadResultResponse,
    dependencies=[Depends(require_write_access), Depends(require_gee_account_management_enabled)],
)
async def reload_gee_accounts():
    """重载 GEE 账户池。"""
    success, count, message = config_service.reload_gee_account_pool()
    return ReloadResultResponse(success=success, account_count=count, message=message)


# ── GEE 运行时配置 ────────────────────────────────────────────────────────────

@router.get("/gee/runtime")
async def get_gee_runtime_config():
    """获取 GEE 运行时配置。"""
    return config_service.get_gee_runtime_config()


# ── 天气 API 配置 ─────────────────────────────────────────────────────────────

@router.get("/weather")
async def get_weather_config():
    """获取天气 API 配置。"""
    return config_service.get_weather_config()


@router.put(
    "/weather/model",
    dependencies=[Depends(require_write_access)],
)
async def update_weather_default_model(request: WeatherModelUpdateRequest):
    """更新全局默认天气模型（SQLite 持久化，立即影响无参 coverage / 瓦片默认 model）。"""
    try:
        return config_service.set_weather_default_model(request.default_model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 天气源 Provider 管理 ──────────────────────────────────────────────────────

@router.get("/weather/providers")
async def list_weather_providers(include_disabled: bool = True):
    """列出所有天气源 Provider。"""
    return config_service.list_weather_providers(include_disabled=include_disabled)


@router.get("/weather/providers/{provider_id}")
async def get_weather_provider(provider_id: str):
    """获取单个天气源 Provider 详情。"""
    result = config_service.get_weather_provider(provider_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"天气源 Provider '{provider_id}' 不存在")
    return result


@router.put(
    "/weather/providers/{provider_id}",
    dependencies=[Depends(require_write_access)],
)
async def update_weather_provider(provider_id: str, request: WeatherProviderUpdateRequest):
    """更新天气源 Provider 配置（enabled/priority/config）。"""
    try:
        result = config_service.update_weather_provider(
            provider_id,
            enabled=request.enabled,
            priority=request.priority,
            config=request.config,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        logger.exception("[config_routes] Failed to update weather provider: %s", provider_id)
        raise HTTPException(status_code=500, detail="更新天气源 Provider 时发生内部错误，请检查日志")
    if result is None:
        raise HTTPException(status_code=404, detail=f"天气源 Provider '{provider_id}' 不存在")
    return result


@router.post(
    "/weather/providers/{provider_id}/test",
    response_model=WeatherProviderTestResponse,
    dependencies=[Depends(require_write_access)],
)
async def test_weather_provider(provider_id: str):
    """测试天气源 Provider 连通性。"""
    result = config_service.test_weather_provider(provider_id)
    return WeatherProviderTestResponse(**result)


@router.put(
    "/weather/providers/{provider_id}/toggle",
    dependencies=[Depends(require_write_access)],
)
async def toggle_weather_provider(provider_id: str, request: WeatherProviderToggleRequest):
    """启用/禁用天气源 Provider。"""
    try:
        result = config_service.toggle_weather_provider(provider_id, request.enabled)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail=f"天气源 Provider '{provider_id}' 不存在")
    return {"provider_id": provider_id, "enabled": request.enabled}


@router.put(
    "/weather/providers/{provider_id}/priority",
    dependencies=[Depends(require_write_access)],
)
async def set_weather_provider_priority(provider_id: str, request: WeatherProviderPriorityRequest):
    """调整天气源 Provider 优先级。"""
    try:
        result = config_service.set_weather_provider_priority(provider_id, request.priority)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail=f"天气源 Provider '{provider_id}' 不存在")
    return {"provider_id": provider_id, "priority": request.priority}


@router.delete(
    "/weather/providers/{provider_id}",
    dependencies=[Depends(require_write_access)],
)
async def delete_weather_provider(provider_id: str):
    """删除天气源 Provider 的 DB 配置记录。

    注意：删除后内置 Provider 会回退到代码默认配置；如需彻底禁用请使用 toggle 端点。
    """
    deleted = config_service.delete_weather_provider(provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' 在 DB 中无配置记录")
    return {"deleted": True, "provider_id": provider_id}


# ── 远程存储凭证 ──────────────────────────────────────────────────────────────

@router.get("/remote-storage")
async def list_remote_storage_profiles(include_disabled: bool = True):
    return config_service.list_remote_storage_profiles(include_disabled=include_disabled)


@router.put(
    "/remote-storage/{profile_id}",
    dependencies=[Depends(require_write_access)],
)
async def upsert_remote_storage_profile(profile_id: str, request: RemoteStorageUpsertRequest):
    try:
        return config_service.upsert_remote_storage_profile(
            profile_id,
            protocol=request.protocol,
            host=request.host,
            port=request.port,
            username=request.username,
            secret=request.secret,
            private_key_pem=request.private_key_pem,
            domain=request.domain,
            extra=request.extra,
            display_name=request.display_name,
            enabled=request.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/remote-storage/{profile_id}",
    dependencies=[Depends(require_write_access)],
)
async def delete_remote_storage_profile(profile_id: str):
    deleted = config_service.delete_remote_storage_profile(profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return {"deleted": True, "profile_id": profile_id}


@router.put(
    "/remote-storage/{profile_id}/toggle",
    dependencies=[Depends(require_write_access)],
)
async def toggle_remote_storage_profile(profile_id: str, request: RemoteStorageToggleRequest):
    ok = config_service.toggle_remote_storage_profile(profile_id, request.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return {"profile_id": profile_id, "enabled": request.enabled}


@router.post(
    "/remote-storage/{profile_id}/test",
    response_model=RemoteStorageTestResponse,
    dependencies=[Depends(require_write_access)],
)
async def test_remote_storage_profile(
    profile_id: str,
    request: RemoteStorageTestRequest | None = None,
):
    uri = request.uri if request else None
    result = config_service.test_remote_storage_profile(profile_id, uri=uri)
    return RemoteStorageTestResponse(**result)


@router.get(
    "/remote-storage/{profile_id}/history",
    response_model=list[RemoteStorageHistoryItem],
    dependencies=[Depends(require_write_access)],
)
async def list_remote_storage_history(profile_id: str):
    return config_service.list_remote_storage_history(profile_id)


@router.post(
    "/remote-storage/{profile_id}/history/{history_id}/restore",
    dependencies=[Depends(require_write_access)],
)
async def restore_remote_storage_history(profile_id: str, history_id: int):
    try:
        return config_service.restore_remote_storage_history(profile_id, history_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/remote-storage/{profile_id}/history/{history_id}",
    dependencies=[Depends(require_write_access)],
)
async def delete_remote_storage_history_entry(profile_id: str, history_id: int):
    deleted = config_service.delete_remote_storage_history_entry(profile_id, history_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"历史记录 #{history_id} 不存在")
    return {"deleted": True, "profile_id": profile_id, "history_id": history_id}


@router.delete(
    "/remote-storage/{profile_id}/history",
    response_model=RemoteStorageHistoryClearResponse,
    dependencies=[Depends(require_write_access)],
)
async def clear_remote_storage_history(profile_id: str):
    deleted = config_service.clear_remote_storage_history(profile_id)
    return RemoteStorageHistoryClearResponse(profile_id=profile_id, deleted=deleted)


# ── 数据源配置 ────────────────────────────────────────────────────────────────

@router.get("/data-source")
async def get_data_source_config():
    """获取数据源配置。"""
    return config_service.get_data_source_config()


@router.get("/data-cache/overview")
async def get_data_cache_overview():
    """静态 materialize 缓存概览。"""
    return config_service.get_data_cache_overview_api()


@router.post("/data-cache/evict", dependencies=[Depends(require_write_access)])
async def evict_data_cache(payload: dict[str, Any] | None = None):
    """清理静态缓存（按 URI/名称或过期时间）。"""
    body = payload or {}
    return config_service.evict_data_cache_api(
        uri_or_name=body.get("uri_or_name"),
        older_than_seconds=body.get("older_than_seconds"),
    )


@router.put("/data-source/open-data-presets", dependencies=[Depends(require_write_access)])
async def update_open_data_presets(payload: dict[str, Any]):
    """更新 NOAA/NASA/ESA 开放数据 base URL 预设。"""
    presets = payload.get("open_data_presets") or payload
    if not isinstance(presets, dict):
        raise HTTPException(status_code=400, detail="open_data_presets must be an object")
    return config_service.update_open_data_presets(presets)


@router.put("/data-source/remote-layer-uris", dependencies=[Depends(require_write_access)])
async def update_remote_layer_uris(payload: dict[str, Any]):
    """更新图层 URI 覆盖（等价 BACKEND_REMOTE_LAYER_DATA_URIS）。"""
    uris = payload.get("remote_layer_data_uris") or payload
    if not isinstance(uris, dict):
        raise HTTPException(status_code=400, detail="remote_layer_data_uris must be an object")
    return config_service.update_remote_layer_data_uris(uris)


# ── 关于 ──────────────────────────────────────────────────────────────────────

@router.get("/about")
async def get_about_info():
    """获取项目信息。"""
    return config_service.get_about_info()
