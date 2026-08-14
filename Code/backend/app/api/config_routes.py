"""
配置管理 API 路由

提供以下端点：
- GET /config/general — 获取常规配置（需读鉴权）
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
- GET /config/remote-storage/{profile_id} — 单条 Profile（脱敏）
- PUT /config/remote-storage/{profile_id} — 新增/更新 Profile（支持双路径字段）
- DELETE /config/remote-storage/{profile_id} — 删除 Profile
- PUT /config/remote-storage/{profile_id}/toggle — 启用/禁用
- POST /config/remote-storage/{profile_id}/test — 测试连通性（双路径回退感知）
- POST /config/remote-storage/{profile_id}/browse — 浏览目录（read 权限）
- POST /config/remote-storage/{profile_id}/search — 名称搜索（read 权限）
- POST /config/remote-storage/{profile_id}/failover — 手动切换主/备路径
- GET /config/data-source — 数据源配置（含生效/待重启数据根）
- PUT /config/data-source/paths — 更新数据根/产物根（写 .env，需重启后端）
- GET /config/data-source/datasets — 可用数据集注册表（read 权限）
- POST /config/data-source/datasets/rescan — 重扫数据根（admin）
- PUT /config/data-source/datasets/{dataset_id} — 新增/更新数据集（admin）
- DELETE /config/data-source/datasets/{dataset_id} — 删除数据集（admin；内置条目拒删）
- GET /config/remote-sources — 可访问远程数据源别名 + 能力徽标（read）
- PUT /config/remote-sources/{remote_source_id} — 新增/更新别名（admin）
- DELETE /config/remote-sources/{remote_source_id} — 删除别名（admin）
- POST /config/service/restart — 调度重启 FastAPI+Worker+Beat
- GET /config/about — 项目信息
"""

import logging

import anyio
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import (
    require_config_read_access,
    require_gee_account_management_enabled,
    require_config_management_access,
)
from app.services import config_service
from shared.contracts.config_contracts import (
    AboutInfo,
    ApiKeyDeletedResponse,
    ApiKeyHistoryClearResponse,
    ApiKeyHistoryDeletedResponse,
    ApiKeyHistoryItem,
    ApiKeyItem,
    ApiKeyToggleRequest,
    ApiKeyUpdateRequest,
    DataCacheEvictRequest,
    DataCacheEvictResponse,
    DataCacheOverview,
    DataSourceConfig,
    DeletedResponse,
    DataSourcePathsUpdateRequest,
    DataSourcePathsUpdateResponse,
    DatasetRescanResponse,
    DatasetUpsertRequest,
    AvailableDatasetEntry,
    GeeAccountCreateRequest,
    GeeAccountDeletedResponse,
    GeeAccountItem,
    GeeAccountToggleRequest,
    GeeAccountToggleResponse,
    GeeRuntimeConfig,
    GeneralConfig,
    OpenDataPresetsUpdateRequest,
    OpenDataPresetsUpdateResponse,
    PortalCatalogEntry,
    PortalCatalogResponse,
    PortalCredentialUpsertRequest,
    PortalCredentialsMapResponse,
    PortalSearchResponse,
    PortalTestResponse,
    PortalUpsertRequest,
    ReloadResultResponse,
    RemoteLayerUrisUpdateRequest,
    RemoteLayerUrisUpdateResponse,
    RemoteStorageDeletedResponse,
    RemoteStorageHistoryClearResponse,
    RemoteStorageHistoryDeletedResponse,
    RemoteStorageHistoryItem,
    RemoteStorageProfile,
    RemoteStorageTestRequest,
    RemoteStorageTestResponse,
    RemoteStorageToggleRequest,
    RemoteStorageToggleResponse,
    RemoteStorageUpsertRequest,
    RemoteBrowseRequest,
    RemoteBrowseResponse,
    RemoteSearchRequest,
    RemoteSearchResponse,
    RemoteFailoverRequest,
    RemoteFailoverResponse,
    RemoteSourceEntry,
    RemoteSourceUpsertRequest,
    ServiceRestartRequest,
    ServiceRestartResponse,
    TestResultResponse,
    WeatherConfig,
    WeatherModelUpdateRequest,
    WeatherProviderDeletedResponse,
    WeatherProviderItem,
    WeatherProviderPriorityRequest,
    WeatherProviderPriorityResponse,
    WeatherProviderTestResponse,
    WeatherProviderToggleRequest,
    WeatherProviderToggleResponse,
    WeatherProviderUpdateRequest,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


# ── 常规配置 ──────────────────────────────────────────────────────────────────


@router.get(
    "/general",
    response_model=GeneralConfig,
    dependencies=[Depends(require_config_read_access)],
)
async def get_general_config():
    """获取常规配置（脱敏；需读鉴权，redis_url 口令已脱敏）。"""
    return config_service.get_general_config()


# ── API Key 管理 ──────────────────────────────────────────────────────────────


@router.get(
    "/api-keys",
    response_model=list[ApiKeyItem],
    dependencies=[Depends(require_config_read_access)],
)
async def list_api_keys():
    """列出所有 API Key（脱敏）。"""
    return config_service.list_api_keys()


@router.put(
    "/api-keys/{key_name}",
    response_model=ApiKeyItem,
    dependencies=[Depends(require_config_management_access)],
)
async def update_api_key(key_name: str, request: ApiKeyUpdateRequest):
    """新增或更新 API Key。"""
    if not request.key_value.strip():
        raise HTTPException(status_code=400, detail="key_value 不能为空")
    result = await anyio.to_thread.run_sync(
        lambda: config_service.upsert_api_key(
            key_name=key_name,
            key_value=request.key_value.strip(),
            display_name=request.display_name,
            description=request.description,
            enabled=request.enabled,
            history_label=request.history_label,
        )
    )
    if not result:
        raise HTTPException(status_code=500, detail="保存失败")
    return result


@router.delete(
    "/api-keys/{key_name}",
    response_model=ApiKeyDeletedResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def delete_api_key(key_name: str):
    """删除 API Key。"""
    deleted = await anyio.to_thread.run_sync(config_service.delete_api_key, key_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"API Key '{key_name}' 不存在")
    return ApiKeyDeletedResponse(deleted=True, key_name=key_name)


@router.post(
    "/api-keys/{key_name}/test",
    response_model=TestResultResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def test_api_key(key_name: str):
    """测试 API Key 是否有效。"""
    success, message = await config_service.test_api_key(key_name)
    return TestResultResponse(success=success, message=message)


@router.put(
    "/api-keys/{key_name}/toggle",
    response_model=ApiKeyItem,
    dependencies=[Depends(require_config_management_access)],
)
async def toggle_api_key(key_name: str, request: ApiKeyToggleRequest):
    """启用/禁用 API Key。无值时返回 400；env-only 会物化到 DB。"""
    try:
        return await anyio.to_thread.run_sync(
            config_service.toggle_api_key, key_name, request.enabled
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/api-keys/{key_name}/history",
    response_model=list[ApiKeyHistoryItem],
    dependencies=[Depends(require_config_management_access)],
)
async def list_api_key_history(key_name: str):
    """列出密钥历史版本（脱敏）。"""
    return config_service.list_api_key_history(key_name)


@router.post(
    "/api-keys/{key_name}/history/{history_id}/restore",
    response_model=ApiKeyItem,
    dependencies=[Depends(require_config_management_access)],
)
async def restore_api_key_history(key_name: str, history_id: int):
    """将历史版本恢复为当前密钥。"""
    try:
        return config_service.restore_api_key_history(key_name, history_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/api-keys/{key_name}/history/{history_id}",
    response_model=ApiKeyHistoryDeletedResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def delete_api_key_history_entry(key_name: str, history_id: int):
    deleted = config_service.delete_api_key_history_entry(key_name, history_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"历史记录 #{history_id} 不存在")
    return ApiKeyHistoryDeletedResponse(
        deleted=True, key_name=key_name, history_id=history_id
    )


@router.delete(
    "/api-keys/{key_name}/history",
    response_model=ApiKeyHistoryClearResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def clear_api_key_history(key_name: str):
    deleted = config_service.clear_api_key_history(key_name)
    return ApiKeyHistoryClearResponse(key_name=key_name, deleted=deleted)


# ── GEE 账户管理 ──────────────────────────────────────────────────────────────


@router.get(
    "/gee/accounts",
    response_model=list[GeeAccountItem],
    dependencies=[Depends(require_config_read_access)],
)
async def list_gee_accounts():
    """列出所有 GEE 账户（脱敏）。"""
    return config_service.list_gee_accounts()


@router.post(
    "/gee/accounts",
    response_model=GeeAccountItem,
    dependencies=[
        Depends(require_config_management_access),
        Depends(require_gee_account_management_enabled),
    ],
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
    except Exception:  # noqa: BLE001 — route-level catch-all, logged and mapped to 500
        logger.exception(
            "[config_routes] Failed to add GEE account: %s", request.account_id
        )
        raise HTTPException(
            status_code=500, detail="添加 GEE 账户时发生内部错误，请检查日志"
        )


@router.delete(
    "/gee/accounts/{account_id}",
    response_model=GeeAccountDeletedResponse,
    dependencies=[
        Depends(require_config_management_access),
        Depends(require_gee_account_management_enabled),
    ],
)
async def delete_gee_account(account_id: str):
    """删除 GEE 账户。"""
    deleted = config_service.delete_gee_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"GEE 账户 '{account_id}' 不存在")
    return GeeAccountDeletedResponse(deleted=True, account_id=account_id)


@router.post(
    "/gee/accounts/{account_id}/test",
    response_model=TestResultResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def test_gee_account(account_id: str):
    """测试 GEE 账户凭证是否有效。"""
    success, message = await config_service.test_gee_account(account_id)
    return TestResultResponse(success=success, message=message)


@router.put(
    "/gee/accounts/{account_id}/toggle",
    response_model=GeeAccountToggleResponse,
    dependencies=[
        Depends(require_config_management_access),
        Depends(require_gee_account_management_enabled),
    ],
)
async def toggle_gee_account(account_id: str, request: GeeAccountToggleRequest):
    """启用/禁用 GEE 账户。"""
    toggled = config_service.toggle_gee_account(account_id, request.enabled)
    if not toggled:
        raise HTTPException(status_code=404, detail=f"GEE 账户 '{account_id}' 不存在")
    return GeeAccountToggleResponse(account_id=account_id, enabled=request.enabled)


@router.post(
    "/gee/accounts/reload",
    response_model=ReloadResultResponse,
    dependencies=[
        Depends(require_config_management_access),
        Depends(require_gee_account_management_enabled),
    ],
)
async def reload_gee_accounts():
    """重载 GEE 账户池。"""
    success, count, message = config_service.reload_gee_account_pool()
    return ReloadResultResponse(success=success, account_count=count, message=message)


# ── GEE 运行时配置 ────────────────────────────────────────────────────────────


@router.get(
    "/gee/runtime",
    response_model=GeeRuntimeConfig,
    dependencies=[Depends(require_config_read_access)],
)
async def get_gee_runtime_config():
    """获取 GEE 运行时配置。"""
    return config_service.get_gee_runtime_config()


# ── 天气 API 配置 ─────────────────────────────────────────────────────────────


@router.get(
    "/weather",
    response_model=WeatherConfig,
    dependencies=[Depends(require_config_read_access)],
)
async def get_weather_config():
    """获取天气 API 配置。"""
    return config_service.get_weather_config()


@router.put(
    "/weather/model",
    response_model=WeatherConfig,
    dependencies=[Depends(require_config_management_access)],
)
async def update_weather_default_model(request: WeatherModelUpdateRequest):
    """更新全局默认天气模型（SQLite 持久化，立即影响无参 coverage / 瓦片默认 model）。"""
    try:
        config_service.set_weather_default_model(request.default_model)
        return config_service.get_weather_config()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 天气源 Provider 管理 ──────────────────────────────────────────────────────


@router.get(
    "/weather/providers",
    response_model=list[WeatherProviderItem],
    dependencies=[Depends(require_config_read_access)],
)
async def list_weather_providers(include_disabled: bool = True):
    """列出所有天气源 Provider。"""
    return config_service.list_weather_providers(include_disabled=include_disabled)


@router.get(
    "/weather/providers/{provider_id}",
    response_model=WeatherProviderItem,
    dependencies=[Depends(require_config_read_access)],
)
async def get_weather_provider(provider_id: str):
    """获取单个天气源 Provider 详情。"""
    result = config_service.get_weather_provider(provider_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"天气源 Provider '{provider_id}' 不存在"
        )
    return result


@router.put(
    "/weather/providers/{provider_id}",
    response_model=WeatherProviderItem,
    dependencies=[Depends(require_config_management_access)],
)
async def update_weather_provider(
    provider_id: str, request: WeatherProviderUpdateRequest
):
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
    except Exception:  # noqa: BLE001 — route-level catch-all, logged and mapped to 500
        logger.exception(
            "[config_routes] Failed to update weather provider: %s", provider_id
        )
        raise HTTPException(
            status_code=500, detail="更新天气源 Provider 时发生内部错误，请检查日志"
        )
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"天气源 Provider '{provider_id}' 不存在"
        )
    return result


@router.post(
    "/weather/providers/{provider_id}/test",
    response_model=WeatherProviderTestResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def test_weather_provider(provider_id: str):
    """测试天气源 Provider 连通性。"""
    result = config_service.test_weather_provider(provider_id)
    return WeatherProviderTestResponse(**result)


@router.put(
    "/weather/providers/{provider_id}/toggle",
    response_model=WeatherProviderToggleResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def toggle_weather_provider(
    provider_id: str, request: WeatherProviderToggleRequest
):
    """启用/禁用天气源 Provider。"""
    try:
        result = config_service.toggle_weather_provider(provider_id, request.enabled)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"天气源 Provider '{provider_id}' 不存在"
        )
    return WeatherProviderToggleResponse(
        provider_id=provider_id, enabled=request.enabled
    )


@router.put(
    "/weather/providers/{provider_id}/priority",
    response_model=WeatherProviderPriorityResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def set_weather_provider_priority(
    provider_id: str, request: WeatherProviderPriorityRequest
):
    """调整天气源 Provider 优先级。"""
    try:
        result = config_service.set_weather_provider_priority(
            provider_id, request.priority
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"天气源 Provider '{provider_id}' 不存在"
        )
    return WeatherProviderPriorityResponse(
        provider_id=provider_id, priority=request.priority
    )


@router.delete(
    "/weather/providers/{provider_id}",
    response_model=WeatherProviderDeletedResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def delete_weather_provider(provider_id: str):
    """删除天气源 Provider 的 DB 配置记录。

    注意：删除后内置 Provider 会回退到代码默认配置；如需彻底禁用请使用 toggle 端点。
    """
    deleted = config_service.delete_weather_provider(provider_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"Provider '{provider_id}' 在 DB 中无配置记录"
        )
    return WeatherProviderDeletedResponse(deleted=True, provider_id=provider_id)


# ── 远程存储凭证 ──────────────────────────────────────────────────────────────


@router.get(
    "/remote-storage",
    response_model=list[RemoteStorageProfile],
    dependencies=[Depends(require_config_read_access)],
)
async def list_remote_storage_profiles(include_disabled: bool = True):
    return config_service.list_remote_storage_profiles(
        include_disabled=include_disabled
    )


@router.get(
    "/remote-storage/{profile_id}",
    response_model=RemoteStorageProfile,
    dependencies=[Depends(require_config_read_access)],
)
async def get_remote_storage_profile(profile_id: str):
    info = config_service.get_remote_storage_profile(profile_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return info


@router.put(
    "/remote-storage/{profile_id}",
    response_model=RemoteStorageProfile,
    dependencies=[Depends(require_config_management_access)],
)
async def upsert_remote_storage_profile(
    profile_id: str, request: RemoteStorageUpsertRequest
):
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
            alt_host=request.alt_host,
            alt_port=request.alt_port,
            alt_url=request.alt_url,
            fallback_mode=request.fallback_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/remote-storage/{profile_id}",
    response_model=RemoteStorageDeletedResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def delete_remote_storage_profile(profile_id: str):
    deleted = config_service.delete_remote_storage_profile(profile_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return RemoteStorageDeletedResponse(deleted=True, profile_id=profile_id)


@router.put(
    "/remote-storage/{profile_id}/toggle",
    response_model=RemoteStorageToggleResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def toggle_remote_storage_profile(
    profile_id: str, request: RemoteStorageToggleRequest
):
    ok = config_service.toggle_remote_storage_profile(profile_id, request.enabled)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return RemoteStorageToggleResponse(profile_id=profile_id, enabled=request.enabled)


@router.post(
    "/remote-storage/{profile_id}/test",
    response_model=RemoteStorageTestResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def test_remote_storage_profile(
    profile_id: str,
    request: RemoteStorageTestRequest | None = None,
):
    uri = request.uri if request else None
    result = await anyio.to_thread.run_sync(
        lambda: config_service.test_remote_storage_profile(profile_id, uri=uri)
    )
    return RemoteStorageTestResponse(**result)


@router.post(
    "/remote-storage/{profile_id}/browse",
    response_model=RemoteBrowseResponse,
    dependencies=[Depends(require_config_read_access)],
)
async def browse_remote_storage_profile(
    profile_id: str, request: RemoteBrowseRequest | None = None
):
    """浏览存储 profile 目录（双路径感知；standard 角色可浏览）。"""
    from app.services.remote_access import browser

    path = request.path if request else "/"
    try:
        result = await anyio.to_thread.run_sync(
            browser.browse_profile, profile_id, path
        )
    except browser.RemoteAccessAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except browser.RemoteAccessNetworkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except browser.RemoteAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RemoteBrowseResponse(**result)


@router.post(
    "/remote-storage/{profile_id}/search",
    response_model=RemoteSearchResponse,
    dependencies=[Depends(require_config_read_access)],
)
async def search_remote_storage_profile(profile_id: str, request: RemoteSearchRequest):
    """在存储 profile 内按名称搜索（能力因协议而异）。"""
    from app.services.remote_access import browser

    try:
        result = await anyio.to_thread.run_sync(
            lambda: browser.search_profile(
                profile_id,
                request.query,
                max_results=request.max_results,
                start_path=request.start_path,
            )
        )
    except browser.RemoteAccessAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except browser.RemoteAccessNetworkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except browser.RemoteAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RemoteSearchResponse(**result)


@router.post(
    "/remote-storage/{profile_id}/failover",
    response_model=RemoteFailoverResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def failover_remote_storage_profile(
    profile_id: str, request: RemoteFailoverRequest
):
    """手动切换主/备访问路径。"""
    try:
        return config_service.probe_failover(profile_id, request.target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/remote-storage/{profile_id}/history",
    response_model=list[RemoteStorageHistoryItem],
    dependencies=[Depends(require_config_management_access)],
)
async def list_remote_storage_history(profile_id: str):
    return config_service.list_remote_storage_history(profile_id)


@router.post(
    "/remote-storage/{profile_id}/history/{history_id}/restore",
    response_model=RemoteStorageProfile,
    dependencies=[Depends(require_config_management_access)],
)
async def restore_remote_storage_history(profile_id: str, history_id: int):
    try:
        return config_service.restore_remote_storage_history(profile_id, history_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/remote-storage/{profile_id}/history/{history_id}",
    response_model=RemoteStorageHistoryDeletedResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def delete_remote_storage_history_entry(profile_id: str, history_id: int):
    deleted = config_service.delete_remote_storage_history_entry(profile_id, history_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"历史记录 #{history_id} 不存在")
    return RemoteStorageHistoryDeletedResponse(
        deleted=True, profile_id=profile_id, history_id=history_id
    )


@router.delete(
    "/remote-storage/{profile_id}/history",
    response_model=RemoteStorageHistoryClearResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def clear_remote_storage_history(profile_id: str):
    deleted = config_service.clear_remote_storage_history(profile_id)
    return RemoteStorageHistoryClearResponse(profile_id=profile_id, deleted=deleted)


# ── 数据源配置 ────────────────────────────────────────────────────────────────


@router.get(
    "/data-source",
    response_model=DataSourceConfig,
    dependencies=[Depends(require_config_read_access)],
)
async def get_data_source_config():
    """获取数据源配置（磁盘扫描放到线程池，避免阻塞事件循环）。"""
    return await anyio.to_thread.run_sync(config_service.get_data_source_config)


@router.put(
    "/data-source/paths",
    response_model=DataSourcePathsUpdateResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def update_data_source_paths(request: DataSourcePathsUpdateRequest):
    """更新数据根 / 产物根（写入 .env；需重启 FastAPI+Worker+Beat 生效）。"""
    try:
        return await anyio.to_thread.run_sync(
            config_service.update_data_source_paths,
            request.data_root,
            request.output_root,
            request.static_cache_root,
            request.cache_dir,
            request.download_source_root,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/service/restart",
    status_code=202,
    response_model=ServiceRestartResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def restart_backend_service(request: ServiceRestartRequest | None = None):
    """调度重启 FastAPI + Celery Worker + Beat（不动 Docker / Vite）。"""
    body = request or ServiceRestartRequest()
    try:
        return config_service.schedule_ui_backend_restart(body.components)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/data-cache/overview",
    response_model=DataCacheOverview,
    dependencies=[Depends(require_config_read_access)],
)
async def get_data_cache_overview():
    """静态 materialize 缓存概览。"""
    return await anyio.to_thread.run_sync(config_service.get_data_cache_overview_api)


@router.post(
    "/data-cache/evict",
    response_model=DataCacheEvictResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def evict_data_cache(payload: DataCacheEvictRequest | None = None):
    """清理静态缓存（按 URI/名称或过期时间）。"""
    body = payload or DataCacheEvictRequest()
    return config_service.evict_data_cache_api(
        uri_or_name=body.uri_or_name,
        older_than_seconds=body.older_than_seconds,
    )


@router.put(
    "/data-source/open-data-presets",
    response_model=OpenDataPresetsUpdateResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def update_open_data_presets(payload: OpenDataPresetsUpdateRequest):
    """更新 NOAA/NASA/NSIDC/ESA 开放数据 base URL 预设。"""
    try:
        return config_service.update_open_data_presets(payload.open_data_presets)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/data-source/portal-credentials",
    response_model=PortalCredentialsMapResponse,
    dependencies=[Depends(require_config_read_access)],
)
async def get_portal_credentials():
    """开放门户凭证（脱敏）。"""
    return config_service.get_portal_credentials_public()


@router.put(
    "/data-source/portal-credentials/{portal_id}",
    response_model=PortalCredentialsMapResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def upsert_portal_credential(
    portal_id: str, payload: PortalCredentialUpsertRequest
):
    """新增/更新门户凭证（earthdata / nsidc / copernicus）。"""
    try:
        return config_service.upsert_portal_credential(
            portal_id, payload.model_dump(exclude_none=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/data-source/portal-credentials/{portal_id}",
    response_model=PortalCredentialsMapResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def delete_portal_credential(portal_id: str):
    """删除门户凭证。"""
    return config_service.delete_portal_credential(portal_id)


# ── 开放门户目录 ──────────────────────────────────────────────────────────────


@router.get(
    "/portals",
    response_model=PortalCatalogResponse,
    dependencies=[Depends(require_config_read_access)],
)
async def get_portal_catalog():
    """门户目录（内置 + 自定义，含凭据状态与 URL 覆盖态）。"""
    return await anyio.to_thread.run_sync(config_service.get_portal_catalog)


@router.put(
    "/portals/{portal_id}",
    response_model=PortalCatalogEntry,
    dependencies=[Depends(require_config_management_access)],
)
async def upsert_portal(portal_id: str, payload: PortalUpsertRequest):
    """自定义门户创建/更新；builtin 门户仅允许覆盖 base_url / alt_url。"""
    from app.services.portal_catalog import PortalCatalogError

    try:
        return config_service.upsert_portal(
            portal_id, payload.model_dump(exclude_none=True)
        )
    except PortalCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/portals/{portal_id}",
    response_model=RemoteStorageDeletedResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def delete_portal(portal_id: str):
    """删除自定义门户（builtin 不可删）。"""
    from app.services.portal_catalog import PortalCatalogError

    try:
        deleted = config_service.delete_portal(portal_id)
    except PortalCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Portal '{portal_id}' not found")
    return RemoteStorageDeletedResponse(deleted=True, profile_id=portal_id)


@router.post(
    "/portals/{portal_id}/test",
    response_model=PortalTestResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def test_portal(portal_id: str):
    """门户连通性测试（凭据感知，SSRF 校验）。"""
    from app.services.portal_catalog import PortalCatalogError

    try:
        return await anyio.to_thread.run_sync(config_service.test_portal, portal_id)
    except PortalCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/portals/{portal_id}/search",
    response_model=PortalSearchResponse,
    dependencies=[Depends(require_config_read_access)],
)
async def search_portal(
    portal_id: str,
    q: str,
    page_size: int = 20,
):
    """门户在线检索（仅 search_capability != none 的门户；本期实装 CMR）。"""
    from app.services.portal_catalog import (
        PortalCatalogError,
        PortalSearchUnsupported,
    )

    def _run() -> dict:
        return config_service.search_portal(portal_id, query=q, page_size=page_size)

    try:
        return await anyio.to_thread.run_sync(_run)
    except PortalSearchUnsupported as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PortalCatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put(
    "/data-source/remote-layer-uris",
    response_model=RemoteLayerUrisUpdateResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def update_remote_layer_uris(payload: RemoteLayerUrisUpdateRequest):
    """更新图层 URI 覆盖（等价 BACKEND_REMOTE_LAYER_DATA_URIS）。"""
    try:
        return config_service.update_remote_layer_data_uris(
            payload.remote_layer_data_uris
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── 可用数据集注册表 ──────────────────────────────────────────────────────────


@router.get(
    "/data-source/datasets",
    response_model=list[AvailableDatasetEntry],
    dependencies=[Depends(require_config_read_access)],
)
async def list_available_datasets(include_disabled: bool = True):
    """可用数据集注册表（manual/scan/algorithm_registry 三来源）。"""
    return config_service.list_available_datasets(include_disabled=include_disabled)


@router.post(
    "/data-source/datasets/rescan",
    response_model=DatasetRescanResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def rescan_available_datasets():
    """重扫数据根：未注册目录生成 source=scan 条目，已有条目刷新文件统计。"""
    return await anyio.to_thread.run_sync(config_service.rescan_available_datasets)


@router.put(
    "/data-source/datasets/{dataset_id}",
    response_model=AvailableDatasetEntry,
    dependencies=[Depends(require_config_management_access)],
)
async def upsert_available_dataset(dataset_id: str, payload: DatasetUpsertRequest):
    """新增/更新可用数据集；dataset_id 传 "new" 创建。写后失效 readiness 缓存。"""
    try:
        return config_service.upsert_available_dataset(dataset_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/data-source/datasets/{dataset_id}",
    response_model=DeletedResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def delete_available_dataset(dataset_id: str):
    """删除可用数据集（algorithm_registry 内置条目拒删）。"""
    try:
        deleted = config_service.delete_available_dataset(dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    return DeletedResponse(deleted=True)


# ── 可访问远程数据源（别名注册表） ────────────────────────────────────────────


@router.get(
    "/remote-sources",
    response_model=list[RemoteSourceEntry],
    dependencies=[Depends(require_config_read_access)],
)
async def list_remote_sources():
    """别名条目 + 引用源能力徽标（protocol/search/enabled/test 状态）。"""
    return config_service.list_remote_sources()


@router.put(
    "/remote-sources/{remote_source_id}",
    response_model=RemoteSourceEntry,
    dependencies=[Depends(require_config_management_access)],
)
async def upsert_remote_source(
    remote_source_id: str, payload: RemoteSourceUpsertRequest
):
    """新增/更新「可访问远程数据源」别名（供下载节点一键填充）。"""
    try:
        return config_service.upsert_remote_source_entry(
            remote_source_id, payload.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/remote-sources/{remote_source_id}",
    response_model=DeletedResponse,
    dependencies=[Depends(require_config_management_access)],
)
async def delete_remote_source(remote_source_id: str):
    """删除别名条目（不影响引用的 profile/门户本身）。"""
    if not config_service.delete_remote_source_entry(remote_source_id):
        raise HTTPException(
            status_code=404, detail=f"Remote source '{remote_source_id}' not found"
        )
    return DeletedResponse(deleted=True)


# ── 关于 ──────────────────────────────────────────────────────────────────────


@router.get("/about", response_model=AboutInfo)
async def get_about_info():
    """获取项目信息。"""
    return config_service.get_about_info()


# ── 缓存管理 ──────────────────────────────────────────────────────────────────


@router.post(
    "/cache/invalidate-templates",
    dependencies=[Depends(require_config_management_access)],
)
async def invalidate_template_caches():
    """P1-3：清除 workflow_request_resolver 的 lru_cache（module templates / dataset paths / provider helpers）。

    在以下场景需调用：
    - 修改了 MODULE_REQUEST_TEMPLATES 后（避免重启 FastAPI）
    - 修改了 provider dataset 配置后
    - admin 主动刷新缓存
    """
    from app.services.workflow_request_resolver import invalidate_template_cache

    invalidate_template_cache()
    return {"status": "ok", "message": "Template caches invalidated"}
