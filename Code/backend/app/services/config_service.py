from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_api_keys_repository():
    """单例获取 ApiKeysRepository。"""
    from app.services.api_keys_repository import ApiKeysRepository

    db_path = str(
        __import__("pathlib").Path(settings.gee_credentials_db_path).parent / "api_keys.sqlite3"
    )
    return ApiKeysRepository(
        db_path=db_path,
        encryption_key=settings.gee_credentials_encryption_key,
        history_limit=settings.api_key_history_limit,
    )


@lru_cache(maxsize=1)
def _get_gee_credentials_repository():
    """单例获取 GeeCredentialsRepository。"""
    from app.services.gee_credentials_repository import GeeCredentialsRepository

    return GeeCredentialsRepository(
        db_path=settings.gee_credentials_db_path,
        encryption_key=settings.gee_credentials_encryption_key,
    )


# ── API Key 管理 ──────────────────────────────────────────────────────────────

# 预定义的 API Key 元信息
_API_KEY_META: dict[str, dict[str, str]] = {
    "tianditu": {
        "display_name": "天地图",
        "description": "天地图底图服务 API Key，从 https://console.tianditu.gov.cn/ 获取",
    },
    "baidu": {
        "display_name": "百度地图",
        "description": "百度地图底图服务 API Key，从 https://lbsyun.baidu.com/ 获取",
    },
    "gaode": {
        "display_name": "高德地图",
        "description": "高德底图可选 Key（当前瓦片模板可不填；预留与设置页对齐）",
    },
    "backend_auth": {
        "display_name": "后端认证",
        "description": "后端 API 访问令牌，用于保护写接口（X-Api-Key）",
    },
}


def _env_api_key_value(key_name: str) -> str:
    env_map = {
        "tianditu": settings.tianditu_api_key,
        "baidu": settings.baidu_api_key,
        "backend_auth": settings.api_key,
        "gaode": os.getenv("BACKEND_GAODE_API_KEY", ""),
    }
    return str(env_map.get(key_name) or "").strip()


def _annotate_key_entry(entry: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Attach source / has_value for settings UI + basemap availability."""
    annotated = dict(entry)
    annotated["source"] = source
    masked = str(annotated.get("masked_value") or "")
    annotated["has_value"] = bool(masked)
    return annotated


def list_api_keys() -> list[dict[str, Any]]:
    """列出所有 API Key（脱敏）。合并 DB、预定义元信息与 env 回退。"""
    from app.services.api_keys_repository import _mask_value

    repo = _get_api_keys_repository()
    db_keys = {k["key_name"]: k for k in repo.list_keys(include_disabled=True)}

    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for key_name, meta in _API_KEY_META.items():
        seen.add(key_name)
        if key_name in db_keys:
            entry = dict(db_keys[key_name])
            if not entry.get("display_name"):
                entry["display_name"] = meta["display_name"]
            if not entry.get("description"):
                entry["description"] = meta["description"]
            result.append(_annotate_key_entry(entry, source="db"))
            continue

        env_value = _env_api_key_value(key_name)
        if env_value:
            result.append(
                _annotate_key_entry(
                    {
                        "key_name": key_name,
                        "display_name": meta["display_name"],
                        "description": meta["description"],
                        "masked_value": _mask_value(env_value),
                        "enabled": True,
                        "created_at": None,
                        "updated_at": None,
                        "last_tested_at": None,
                        "last_test_status": None,
                    },
                    source="env",
                )
            )
        else:
            result.append(
                _annotate_key_entry(
                    {
                        "key_name": key_name,
                        "display_name": meta["display_name"],
                        "description": meta["description"],
                        "masked_value": "",
                        "enabled": False,
                        "created_at": None,
                        "updated_at": None,
                        "last_tested_at": None,
                        "last_test_status": None,
                    },
                    source="none",
                )
            )

    for key_name, entry in db_keys.items():
        if key_name not in seen:
            result.append(_annotate_key_entry(dict(entry), source="db"))

    return result


def upsert_api_key(
    key_name: str,
    key_value: str,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
    enabled: bool = True,
    history_label: Optional[str] = None,
    history_source: str = "user",
) -> dict[str, Any]:
    """新增或更新 API Key。"""
    repo = _get_api_keys_repository()

    meta = _API_KEY_META.get(key_name, {})
    resolved_display_name = display_name or meta.get("display_name", key_name)
    resolved_description = description or meta.get("description")

    result = repo.upsert_key(
        key_name=key_name,
        key_value=key_value,
        display_name=resolved_display_name,
        description=resolved_description,
        enabled=enabled,
        history_label=history_label,
        history_source=history_source,
    )
    _get_effective_api_key_cached.cache_clear()
    effective = get_effective_api_key(key_name) or ""
    _sync_api_config_manager_key(key_name, effective)
    try:
        from app.services.effective_config import hydrate_effective_config

        hydrate_effective_config()
    except Exception:
        logger.exception("Failed to rehydrate effective config after api key upsert")
    return _annotate_key_entry(result or {}, source="db")


def list_api_key_history(key_name: str) -> list[dict[str, Any]]:
    return _get_api_keys_repository().list_history(key_name)


def restore_api_key_history(key_name: str, history_id: int) -> dict[str, Any]:
    """Restore a historical value as the current key (archives current first)."""
    repo = _get_api_keys_repository()
    meta = _API_KEY_META.get(key_name, {})
    info = repo.get_key_info(key_name)
    if info is None:
        raise ValueError(f"API Key '{key_name}' 不存在，无法恢复历史")
    plaintext = repo.get_history_value(key_name, history_id)
    if plaintext is None:
        raise ValueError(f"历史记录 #{history_id} 不存在")
    return upsert_api_key(
        key_name=key_name,
        key_value=plaintext,
        display_name=info.get("display_name") or meta.get("display_name", key_name),
        description=info.get("description") or meta.get("description"),
        enabled=bool(info.get("enabled", True)),
        history_label=f"restore#{history_id}",
        history_source="restore",
    )


def delete_api_key_history_entry(key_name: str, history_id: int) -> bool:
    return _get_api_keys_repository().delete_history_entry(key_name, history_id)


def clear_api_key_history(key_name: str) -> int:
    return _get_api_keys_repository().clear_history(key_name)


def delete_api_key(key_name: str) -> bool:
    """删除 API Key。"""
    repo = _get_api_keys_repository()
    deleted = repo.delete_key(key_name)
    if deleted:
        _get_effective_api_key_cached.cache_clear()
        # 删除 DB 后回落到 env（若有）
        _sync_api_config_manager_key(key_name, get_effective_api_key(key_name) or "")
        try:
            from app.services.effective_config import hydrate_effective_config

            hydrate_effective_config()
        except Exception:
            logger.exception("Failed to rehydrate effective config after api key delete")
    return deleted


def toggle_api_key(key_name: str, enabled: bool) -> dict[str, Any]:
    """启用/禁用 API Key。

    - 已有 DB 行：直接改 enabled
    - 仅有 env、无 DB 行：启用时物化到 DB；禁用时写入 DB 并 enabled=0（阻止再回落到 env）
    - 无值：抛 ValueError，路由映射 400
    """
    repo = _get_api_keys_repository()
    meta = _API_KEY_META.get(key_name, {})
    info = repo.get_key_info(key_name)

    if info is None:
        env_value = _env_api_key_value(key_name)
        if not env_value:
            raise ValueError("请先保存 API Key 后再启用/禁用")
        # Materialize env into DB so enable/disable has a durable row
        repo.upsert_key(
            key_name=key_name,
            key_value=env_value,
            display_name=meta.get("display_name", key_name),
            description=meta.get("description"),
            enabled=enabled,
            history_source="env_materialize",
            archive_previous=False,
        )
    else:
        if not repo.set_enabled(key_name, enabled):
            raise ValueError(f"API Key '{key_name}' 更新失败")

    _get_effective_api_key_cached.cache_clear()
    effective = get_effective_api_key(key_name) or ""
    _sync_api_config_manager_key(key_name, effective)
    try:
        from app.services.effective_config import hydrate_effective_config

        hydrate_effective_config()
    except Exception:
        logger.exception("Failed to rehydrate effective config after api key toggle")

    return {"key_name": key_name, "enabled": enabled, "effective": bool(effective)}


def _sync_api_config_manager_key(key_name: str, key_value: str) -> None:
    """将 effective key 投影到 ApiConfigManager（不含明文出站以外的用途）。"""
    try:
        from app.services.api_config import ApiProvider, api_config_manager

        mapping = {
            "tianditu": ApiProvider.TIANDITU,
            "baidu": ApiProvider.BAIDU,
            "gaode": ApiProvider.GAODE,
        }
        provider = mapping.get(key_name)
        if provider is None:
            return
        if key_value:
            api_config_manager.update_api_key(provider, key_value)
        else:
            config = api_config_manager.get_config(provider)
            if config is not None:
                config.api_key = None
    except Exception:
        logger.exception("Failed to sync api_config_manager for key=%s", key_name)


@lru_cache(maxsize=32)
def _get_effective_api_key_cached(key_name: str) -> Optional[str]:
    """DB 行存在时仅在 enabled 时生效；无 DB 行才回退 env。"""
    repo = _get_api_keys_repository()
    info = repo.get_key_info(key_name)
    if info is not None:
        # Explicit DB row wins: disabled must NOT fall back to env
        return repo.get_key_value(key_name)

    env_value = _env_api_key_value(key_name)
    return env_value or None


def get_effective_api_key(key_name: str) -> Optional[str]:
    """获取生效的 API Key（公开接口）。"""
    return _get_effective_api_key_cached(key_name)


def is_basemap_key_available(key_name: str) -> bool:
    """Whether a basemap provider key is currently effective (for UI gating)."""
    return bool(get_effective_api_key(key_name))


async def test_api_key(key_name: str) -> tuple[bool, str]:
    """测试 API Key 是否有效。返回 (success, message)。"""
    key_value = get_effective_api_key(key_name)
    if not key_value:
        return False, "API Key 未配置"

    repo = _get_api_keys_repository()

    try:
        if key_name == "tianditu":
            # 测试天地图 API：请求一个瓦片（使用 httpx 异步客户端，避免阻塞事件循环）
            import httpx
            url = f"https://t0.tianditu.gov.cn/img_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=img&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILECOL=0&TILEROW=0&TILEMATRIX=0&tk={key_value}"
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                    resp = await client.get(url, headers={"User-Agent": "CGDA-Backend/1.0"})
                if resp.status_code == 200:
                    repo.update_test_status(key_name, "ok")
                    return True, "天地图 API Key 有效"
                else:
                    msg = f"天地图 API 返回 HTTP {resp.status_code}"
                    repo.update_test_status(key_name, "failed")
                    return False, msg
            except httpx.HTTPError as e:
                repo.update_test_status(key_name, "failed")
                return False, f"天地图 API 请求失败: {e}"
        elif key_name == "baidu":
            # 百度地图 API 测试（使用 httpx 异步客户端）
            import httpx
            url = f"https://maponline0.bdimg.com/tile/?qt=tile&x=0&y=0&z=1&styles=pl&v=020&udt=20231201&ak={key_value}"
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                    resp = await client.get(url, headers={"User-Agent": "CGDA-Backend/1.0"})
                if resp.status_code == 200:
                    repo.update_test_status(key_name, "ok")
                    return True, "百度地图 API Key 有效"
                elif resp.status_code == 403:
                    # 百度可能返回 403 但 key 仍然有效（只是瓦片限制）。
                    # httpx 不像 urllib 那样在 4xx 时抛异常，需显式检查 status_code。
                    repo.update_test_status(key_name, "ok")
                    return True, "百度地图 API Key 格式有效（瓦片访问受限但 key 已配置）"
                else:
                    msg = f"百度地图 API 返回 HTTP {resp.status_code}"
                    repo.update_test_status(key_name, "failed")
                    return False, msg
            except httpx.HTTPError as e:
                # 仅捕获网络/超时错误（httpx 不在 4xx/5xx 时抛 HTTPError）
                repo.update_test_status(key_name, "failed")
                return False, f"百度地图 API 测试失败: {e}"
        elif key_name == "backend_auth":
            # 后端认证 key 无法直接测试，只检查格式
            if len(key_value) >= 8:
                repo.update_test_status(key_name, "ok")
                return True, "后端认证 Key 已配置"
            else:
                repo.update_test_status(key_name, "failed")
                return False, "后端认证 Key 长度不足（至少8位）"
        else:
            # 通用测试：检查 key 非空
            if key_value:
                repo.update_test_status(key_name, "ok")
                return True, f"API Key '{key_name}' 已配置"
            else:
                repo.update_test_status(key_name, "failed")
                return False, f"API Key '{key_name}' 为空"
    except Exception as e:
        repo.update_test_status(key_name, "failed")
        return False, f"测试失败: {e}"


# ── GEE 账户管理 ──────────────────────────────────────────────────────────────

def list_gee_accounts() -> list[dict[str, Any]]:
    """列出所有 GEE 账户（脱敏）。"""
    repo = _get_gee_credentials_repository()
    return repo.list_accounts(include_disabled=True)


def add_gee_account(
    account_id: str,
    service_account_json: dict[str, Any],
    display_name: Optional[str] = None,
) -> dict[str, Any]:
    """新增 GEE 账户。"""
    repo = _get_gee_credentials_repository()
    result = repo.upsert_account(
        account_id=account_id,
        service_account_json=service_account_json,
        display_name=display_name,
    )
    # 账户变更后重载 GEE facade
    _reload_gee_facade()
    return result or {}


def delete_gee_account(account_id: str) -> bool:
    """删除 GEE 账户。"""
    repo = _get_gee_credentials_repository()
    deleted = repo.delete_account(account_id)
    if deleted:
        _reload_gee_facade()
    return deleted


def toggle_gee_account(account_id: str, enabled: bool) -> bool:
    """启用/禁用 GEE 账户。"""
    repo = _get_gee_credentials_repository()
    toggled = repo.set_enabled(account_id, enabled)
    if toggled:
        _reload_gee_facade()
    return toggled


async def test_gee_account(account_id: str) -> tuple[bool, str]:
    """测试 GEE 账户凭证是否有效。"""
    repo = _get_gee_credentials_repository()
    sa_json = repo.get_account_credentials(account_id)
    if not sa_json:
        repo.update_test_status(account_id, "failed")
        return False, f"GEE 账户 '{account_id}' 不存在或凭证为空"

    try:
        from app.gee.core.src.webgis_gee.accounts.credentials import GeeCredentialsLoader

        creds = GeeCredentialsLoader.load_service_account_credentials(sa_json)
        success, message = GeeCredentialsLoader.test_credentials(
            creds, sa_json.get("project_id") if isinstance(sa_json, dict) else None
        )
        repo.update_test_status(account_id, "ok" if success else "failed")
        return success, message
    except ImportError:
        # GEE 模块未安装
        repo.update_test_status(account_id, "failed")
        return False, "GEE 模块未安装，无法测试凭证"
    except Exception as e:
        repo.update_test_status(account_id, "failed")
        return False, f"测试失败: {e}"


def _reload_gee_facade() -> None:
    """重载 GEE facade，使账户池变更生效。"""
    try:
        from app.services.gee_bridge_service import reload_gee_facade
        reload_gee_facade()
        logger.info("GEE facade reloaded after account change")
    except Exception as e:
        logger.warning("Failed to reload GEE facade: %s", e)


def reload_gee_account_pool() -> tuple[bool, int, str]:
    """手动重载 GEE 账户池。返回 (success, account_count, message)。"""
    try:
        _reload_gee_facade()
        repo = _get_gee_credentials_repository()
        accounts = repo.list_accounts(enabled_only=True)
        return True, len(accounts), f"账户池已重载，共 {len(accounts)} 个启用账户"
    except Exception as e:
        return False, 0, f"重载失败: {e}"


# ── 常规配置 ──────────────────────────────────────────────────────────────────

def get_general_config() -> dict[str, Any]:
    """获取常规配置（脱敏）。"""
    return {
        "environment": settings.environment,
        "host": settings.host,
        "port": settings.port,
        "service_name": settings.service_name,
        "data_root": settings.data_root,
        "output_root": settings.output_root,
        "cache_dir": settings.cache_dir,
        "log_dir": settings.log_dir,
        "log_level": settings.log_level,
        "max_active_runs": settings.max_active_runs,
        "max_requested_outputs": settings.max_requested_outputs,
        "redis_url": settings.redis_url,
        "storage_backend": settings.storage_backend,
        "reload": settings.reload,
    }


# ── GEE 运行时配置 ────────────────────────────────────────────────────────────

def get_gee_runtime_config() -> dict[str, Any]:
    """获取 GEE 运行时配置。"""
    return {
        "gee_enabled": settings.gee_enabled,
        "max_parallel_exports": settings.gee_max_parallel_exports,
        "max_parallel_uploads": settings.gee_max_parallel_uploads,
        "max_parallel_downloads": settings.gee_max_parallel_downloads,
        "account_cooldown_seconds": settings.gee_account_cooldown_seconds,
        "storage_backend": settings.gee_storage_backend,
        "local_storage_root": settings.gee_local_storage_root,
        "api_account_management_enabled": settings.gee_api_account_management_enabled,
        "credentials_encryption_enabled": bool(settings.gee_credentials_encryption_key),
    }


# ── 天气 API 配置 ─────────────────────────────────────────────────────────────

def get_weather_config() -> dict[str, Any]:
    """获取天气 API 配置（含 runtime effective 覆盖）。"""
    from app.services.effective_config import get_runtime_snapshot, get_weather_cache_ttl_seconds

    snap = get_runtime_snapshot()
    return {
        "default_model": settings.weather_default_model,
        "cache_ttl_seconds": get_weather_cache_ttl_seconds(),
        "refresh_forecast_hours": settings.weather_refresh_forecast_hours,
        "schedule_enabled": settings.weather_schedule_enabled,
        "default_latitude": settings.weather_default_latitude,
        "default_longitude": settings.weather_default_longitude,
        "default_place_name": settings.weather_default_place_name,
        "max_active_weather_tile_runs": snap.max_active_weather_tile_runs,
    }


# ── 数据源配置 ────────────────────────────────────────────────────────────────

def get_data_source_config() -> dict[str, Any]:
    """获取数据源配置。"""
    return {
        "storage_backend": settings.storage_backend,
        "data_root": settings.data_root,
        "output_root": settings.output_root,
        "download_source_root": settings.download_source_root,
        "download_real_fetch_enabled": settings.download_real_fetch_enabled,
        "tile_proxy_enabled": settings.tile_proxy_enabled,
        "tile_proxy_cache_ttl_seconds": settings.tile_proxy_cache_ttl_seconds,
        "minio": {
            "endpoint": settings.minio_endpoint,
            "bucket": settings.minio_bucket,
            "secure": settings.minio_secure,
        } if settings.storage_backend == "minio" else None,
    }


# ── 关于信息 ──────────────────────────────────────────────────────────────────

def get_about_info() -> dict[str, Any]:
    """获取项目信息。"""
    return {
        "project_name": settings.service_name,
        "version": "0.1.0",
        "description": "综合地理态势数据分析与可视化系统",
        "tech_stack": [
            "Vue 3", "TypeScript", "Pinia", "MapLibre GL", "Vite",
            "FastAPI", "Python 3.11+", "Celery", "Redis", "SQLite",
            "MinIO", "Google Earth Engine", "Open-Meteo", "Docker",
        ],
        "modules": [
            {"name": "图层管理", "description": "多源图层目录、工作流驱动、实时瓦片"},
            {"name": "天气引擎", "description": "Open-Meteo 实时气象数据、风场粒子流渲染"},
            {"name": "GEE 引擎", "description": "Google Earth Engine 多账户并行、遥感分析"},
            {"name": "算法引擎", "description": "Python Provider 算法集成、双通道接口"},
            {"name": "工作流调度", "description": "Celery 分布式任务、队列路由、重试策略"},
            {"name": "数据管理", "description": "本地/远程数据源、导入导出、MinIO 持久化"},
        ],
        "architecture_summary": (
            "系统采用前后端分离架构：前端 Vue 3 + MapLibre GL 负责地图渲染与交互，"
            "后端 FastAPI 提供 RESTful API，Celery + Redis 处理异步工作流。"
            "支持 GEE、天气、算法三大引擎模块化接入，通过统一工作流端点调度。"
            "数据层支持本地文件系统、MinIO 对象存储和远程 FileBrowser 服务器。"
        ),
    }


# ── 天气源 Provider 管理 ──────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_weather_providers_repository():
    """单例获取 WeatherProvidersRepository。"""
    from app.services.weather_providers_repository import WeatherProvidersRepository

    db_path = str(
        __import__("pathlib").Path(settings.gee_credentials_db_path).parent
        / "weather_providers.sqlite3"
    )
    return WeatherProvidersRepository(
        db_path=db_path,
        encryption_key=settings.gee_credentials_encryption_key,
    )


def _get_weather_registry():
    """获取 Provider 注册表单例（惰性 import 避免循环依赖）。"""
    from app.weatherengine.provider_registry import get_registry
    return get_registry()


def _provider_to_dict(
    provider,
    *,
    priority: int,
    enabled: bool,
    db_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """将 Provider 实例转换为 UI 友好的字典（含运行时状态与 DB 持久化配置）。"""
    status = provider.get_status()
    config_schema = [
        {
            "key": f.key,
            "label": f.label,
            "field_type": f.field_type,
            "required": f.required,
            "default": f.default,
            "description": f.description,
            "options": list(f.options),
            "placeholder": f.placeholder,
        }
        for f in provider.get_config_schema()
    ]
    current_config = provider.get_current_config()

    # DB 中持久化的配置覆盖（可能为 None）
    persisted_config = db_record.get("config") if db_record else None

    return {
        "provider_id": provider.provider_id,
        "display_name": provider.display_name,
        "provider_type": provider.provider_type,
        "version": provider.version,
        "description": provider.description,
        "homepage_url": provider.homepage_url,
        "requires_api_key": provider.requires_api_key,
        "supported_capabilities": sorted(provider.supported_capabilities),
        "priority": priority,
        "enabled": enabled,
        # 运行时状态（用 registry 的 enabled 覆盖 status 中的占位值）
        "status": {
            "enabled": enabled,  # 覆盖 ProviderStatus 中的占位 True，保证 UI 一致
            "healthy": status.healthy,
            "circuit_state": status.circuit_state,
            "last_error": status.last_error,
            "daily_quota": status.daily_quota,
            "daily_used": status.daily_used,
            "daily_remaining": status.daily_remaining,
            "cache_hits": status.cache_hits,
            "cache_misses": status.cache_misses,
            "metadata": status.metadata,
        },
        # 配置
        "config_schema": config_schema,
        "current_config": current_config,
        "persisted_config": persisted_config,
        # 测试状态（来自 DB）
        "last_tested_at": db_record.get("last_tested_at") if db_record else None,
        "last_test_status": db_record.get("last_test_status") if db_record else None,
        "is_builtin": True,  # 当前所有 Provider 都是代码内置的；未来支持 DB 注册第三方
    }


def _ensure_weather_providers_registered() -> None:
    """设置页/配置读路径：惰性补注册默认天气源（含后续新增的 commercial providers）。"""
    try:
        from app.weatherengine.provider_registry import get_registry, register_default_providers

        register_default_providers()
        # 仅在 registry 刚从空变为有内容时应用一次 DB 覆盖；若已有 entries，
        # 启动路径已 apply 过。这里对缺失 provider 的新注册再次 apply 是安全的。
        apply_persisted_provider_overrides()
        _ = get_registry()
    except Exception:
        logger.exception("Lazy weather provider registration failed")


def list_weather_providers(*, include_disabled: bool = True) -> list[dict[str, Any]]:
    """列出所有天气源 Provider（合并 registry 运行时实例 + DB 持久化配置）。"""
    _ensure_weather_providers_registered()
    registry = _get_weather_registry()
    repo = _get_weather_providers_repository()

    # 从 DB 读取持久化配置
    db_records = {r["provider_id"]: r for r in repo.list_providers(include_disabled=include_disabled)}

    # 从 registry 读取运行时 Provider
    entries = registry.list_provider_entries()
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for provider, priority, enabled in entries:
        if not include_disabled and not enabled:
            continue
        db_record = db_records.get(provider.provider_id)
        # DB 中的 priority/enabled 覆盖 registry 默认值
        effective_priority = db_record["priority"] if db_record else priority
        effective_enabled = db_record["enabled"] if db_record else enabled
        result.append(
            _provider_to_dict(
                provider,
                priority=effective_priority,
                enabled=effective_enabled,
                db_record=db_record,
            )
        )
        seen_ids.add(provider.provider_id)

    # DB 中存在但 registry 中未注册的 Provider（理论上不会出现，但为完整性保留）
    for pid, db_record in db_records.items():
        if pid in seen_ids:
            continue
        result.append({
            "provider_id": pid,
            "display_name": db_record.get("display_name") or pid,
            "provider_type": db_record.get("provider_type") or "unknown",
            "version": "n/a",
            "description": "Provider registered in DB but not loaded at runtime (missing implementation).",
            "homepage_url": None,
            "requires_api_key": False,
            "supported_capabilities": [],
            "priority": db_record["priority"],
            "enabled": db_record["enabled"],
            "status": {
                "healthy": False,
                "circuit_state": "n/a",
                "last_error": "Provider not loaded at runtime",
                "daily_quota": None,
                "daily_used": None,
                "daily_remaining": None,
                "cache_hits": 0,
                "cache_misses": 0,
                "metadata": {},
            },
            "config_schema": [],
            "current_config": {},
            "persisted_config": db_record.get("config"),
            "last_tested_at": db_record.get("last_tested_at"),
            "last_test_status": db_record.get("last_test_status"),
            "is_builtin": False,
        })

    # 按 priority 升序排序
    result.sort(key=lambda x: (x["priority"], x["provider_id"]))
    return result


def get_weather_provider(provider_id: str) -> dict[str, Any] | None:
    """获取单个 Provider 详情。"""
    providers = list_weather_providers(include_disabled=True)
    for p in providers:
        if p["provider_id"] == provider_id:
            return p
    return None


def update_weather_provider(
    provider_id: str,
    *,
    enabled: bool | None = None,
    priority: int | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """更新 Provider 配置（写入 DB 并同步到运行时 registry）。"""
    registry = _get_weather_registry()
    repo = _get_weather_providers_repository()

    provider = registry.get_provider(provider_id)
    if provider is None:
        raise ValueError(f"Weather provider not found: {provider_id}")

    # 读取现有 DB 记录（若有）
    existing = repo.get_provider(provider_id)
    new_enabled = enabled if enabled is not None else (existing["enabled"] if existing else True)
    new_priority = priority if priority is not None else (existing["priority"] if existing else 100)
    new_config = config if config is not None else (existing["config"] if existing else None)

    # 写入 DB
    repo.upsert_provider(
        provider_id=provider_id,
        display_name=provider.display_name,
        provider_type=provider.provider_type,
        enabled=new_enabled,
        priority=new_priority,
        config=new_config,
    )

    # 同步到 registry 运行时
    registry.set_enabled(provider_id, new_enabled)
    registry.set_priority(provider_id, new_priority)

    # 应用配置到 Provider 实例
    if new_config is not None:
        try:
            provider.apply_config(new_config)
        except Exception as e:
            logger.warning("Failed to apply config to provider %s: %s", provider_id, e)

    return get_weather_provider(provider_id)


def toggle_weather_provider(provider_id: str, enabled: bool) -> dict[str, Any] | None:
    """启用/禁用 Provider。"""
    return update_weather_provider(provider_id, enabled=enabled)


def set_weather_provider_priority(provider_id: str, priority: int) -> dict[str, Any] | None:
    """调整 Provider 优先级。"""
    return update_weather_provider(provider_id, priority=priority)


def test_weather_provider(provider_id: str) -> dict[str, Any]:
    """测试 Provider 连通性，更新 DB 测试状态。

    禁用的 Provider 不会被测试（避免不必要的 API 调用与预算消耗）。
    对于 DB 中尚无记录的内置 Provider，会先 upsert 一条最小记录再写入测试状态。
    """
    registry = _get_weather_registry()
    repo = _get_weather_providers_repository()

    provider = registry.get_provider(provider_id)
    if provider is None:
        return {
            "provider_id": provider_id,
            "success": False,
            "message": f"Provider not found: {provider_id}",
        }

    # 禁用的 Provider 不执行测试，避免触发真实 API 调用消耗预算
    if not registry.is_enabled(provider_id):
        return {
            "provider_id": provider_id,
            "success": False,
            "message": f"Provider '{provider_id}' is disabled. Enable it before testing.",
        }

    success, message = provider.test_connection()
    status_str = "ok" if success else "failed"

    # 若 DB 中尚无该 Provider 记录，先 upsert 一条最小记录，确保测试状态能持久化
    if repo.get_provider(provider_id) is None:
        repo.upsert_provider(
            provider_id=provider_id,
            display_name=provider.display_name,
            provider_type=provider.provider_type,
            enabled=True,
            priority=100,
            config=None,
        )
    repo.update_test_status(provider_id, status_str)

    return {
        "provider_id": provider_id,
        "success": success,
        "message": message,
        "tested_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }


def delete_weather_provider(provider_id: str) -> bool:
    """删除 DB 中的 Provider 配置记录（不影响代码内置的 Provider 实例）。

    删除后，Provider 会回退到代码默认配置（enabled=True, priority=100）。
    若要彻底禁用内置 Provider，请使用 ``toggle_weather_provider(pid, False)``。
    """
    repo = _get_weather_providers_repository()
    deleted = repo.delete_provider(provider_id)
    if deleted:
        registry = _get_weather_registry()
        provider = registry.get_provider(provider_id)
        if provider is not None:
            registry.set_enabled(provider_id, True)
            registry.set_priority(provider_id, 100)
            try:
                provider.apply_config({})
            except Exception:
                logger.exception("Failed to reset provider config after delete: %s", provider_id)
    return deleted


# ── 远程存储凭证 ──────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_remote_storage_repository():
    from pathlib import Path

    from app.services.remote_storage_credentials_repository import RemoteStorageCredentialsRepository

    db_path = Path(settings.gee_credentials_db_path).parent / "remote_storage_credentials.sqlite3"
    return RemoteStorageCredentialsRepository(
        db_path=db_path,
        encryption_key=settings.gee_credentials_encryption_key,
        history_limit=settings.remote_storage_history_limit,
    )


def list_remote_storage_profiles(include_disabled: bool = True) -> list[dict[str, Any]]:
    return _get_remote_storage_repository().list_profiles(include_disabled=include_disabled)


def list_remote_storage_history(profile_id: str) -> list[dict[str, Any]]:
    return _get_remote_storage_repository().list_history(profile_id)


def restore_remote_storage_history(profile_id: str, history_id: int) -> dict[str, Any]:
    from app.services.remote_auth_resolver import clear_remote_auth_cache

    repo = _get_remote_storage_repository()
    info = repo.get_profile_info(profile_id)
    if info is None:
        raise ValueError(f"Profile not found: {profile_id}")
    bundle = repo.get_history_bundle(profile_id, history_id)
    if bundle is None:
        raise ValueError(f"历史记录 #{history_id} 不存在")
    result = repo.upsert(
        profile_id=profile_id,
        protocol=info["protocol"],
        host=info.get("host") or "",
        port=info.get("port"),
        username=info.get("username"),
        secret=bundle.get("secret") or "",
        private_key_pem=bundle.get("private_key_pem"),
        domain=info.get("domain"),
        extra=info.get("extra"),
        display_name=info.get("display_name"),
        enabled=info.get("enabled"),
    )
    clear_remote_auth_cache()
    return result


def delete_remote_storage_history_entry(profile_id: str, history_id: int) -> bool:
    return _get_remote_storage_repository().delete_history_entry(profile_id, history_id)


def clear_remote_storage_history(profile_id: str) -> int:
    return _get_remote_storage_repository().clear_history(profile_id)


def upsert_remote_storage_profile(
    profile_id: str,
    *,
    protocol: str,
    host: str = "",
    port: int | None = None,
    username: str | None = None,
    secret: str | None = None,
    private_key_pem: str | None = None,
    domain: str | None = None,
    extra: dict[str, Any] | None = None,
    display_name: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    from app.services.remote_auth_resolver import clear_remote_auth_cache

    result = _get_remote_storage_repository().upsert(
        profile_id=profile_id,
        protocol=protocol,
        host=host,
        port=port,
        username=username,
        secret=secret,
        private_key_pem=private_key_pem,
        domain=domain,
        extra=extra,
        display_name=display_name,
        enabled=enabled,
    )
    clear_remote_auth_cache()
    return result


def delete_remote_storage_profile(profile_id: str) -> bool:
    from app.services.remote_auth_resolver import clear_remote_auth_cache

    deleted = _get_remote_storage_repository().delete(profile_id)
    if deleted:
        clear_remote_auth_cache()
    return deleted


def toggle_remote_storage_profile(profile_id: str, enabled: bool) -> bool:
    from app.services.remote_auth_resolver import clear_remote_auth_cache

    ok = _get_remote_storage_repository().set_enabled(profile_id, enabled)
    if ok:
        clear_remote_auth_cache()
    return ok


def test_remote_storage_profile(profile_id: str, uri: str | None = None) -> dict[str, Any]:
    """Probe connectivity for a credential profile (auth/host, not object existence)."""
    from datetime import datetime, timezone

    from app.services.remote_auth_resolver import resolve_remote_auth
    from shared.remote_sources.download import probe_remote_connectivity, probe_remote_uri
    from shared.remote_sources.uri import redact_uri

    repo = _get_remote_storage_repository()
    info = repo.get_profile_info(profile_id)
    if info is None:
        return {
            "profile_id": profile_id,
            "success": False,
            "message": f"Profile not found: {profile_id}",
            "tested_at": datetime.now(timezone.utc).isoformat(),
        }
    if not info.get("enabled"):
        return {
            "profile_id": profile_id,
            "success": False,
            "message": "Profile is disabled",
            "tested_at": datetime.now(timezone.utc).isoformat(),
        }

    protocol = info["protocol"]
    host = info.get("host") or "localhost"
    port = info.get("port")
    host_part = f"{host}:{port}" if port is not None and protocol != "gs" else host

    if uri:
        probe_uri = uri
    elif protocol == "smb":
        share = (info.get("extra") or {}).get("default_share")
        if not share:
            return {
                "profile_id": profile_id,
                "success": False,
                "message": "SMB profile requires extra.default_share for connectivity probe",
                "tested_at": datetime.now(timezone.utc).isoformat(),
            }
        probe_uri = f"smb://{host_part}/{share}/"
    elif protocol == "gs":
        probe_uri = f"gs://{host}/"
    else:
        probe_uri = f"{protocol}://{host_part}/"

    try:
        if "cred=" not in probe_uri:
            sep = "&" if "?" in probe_uri else "?"
            probe_uri = f"{probe_uri}{sep}cred={profile_id}"
        auth = resolve_remote_auth(probe_uri)
        # Custom URI probes the given path; default probes connectivity only
        if uri:
            probe_remote_uri(probe_uri, auth)
        else:
            probe_remote_connectivity(probe_uri, auth)
        repo.update_test_status(profile_id, "ok")
        return {
            "profile_id": profile_id,
            "success": True,
            "message": f"Probe OK: {redact_uri(probe_uri)}",
            "tested_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        repo.update_test_status(profile_id, "failed")
        return {
            "profile_id": profile_id,
            "success": False,
            "message": str(exc),
            "tested_at": datetime.now(timezone.utc).isoformat(),
        }


def apply_persisted_provider_overrides() -> None:
    """启动时从 DB 加载 Provider 配置覆盖到 registry。

    在 ``register_default_providers`` 之后调用，使 DB 中的 enabled/priority/config 覆盖生效。
    """
    registry = _get_weather_registry()
    repo = _get_weather_providers_repository()

    try:
        records = repo.list_providers(include_disabled=True)
    except Exception as e:
        logger.warning("Failed to load weather provider overrides from DB: %s", e)
        return

    for record in records:
        pid = record["provider_id"]
        if registry.get_provider(pid) is None:
            # DB 中有记录但 registry 中无对应实例（实现未注册），跳过
            continue
        registry.set_enabled(pid, record["enabled"])
        registry.set_priority(pid, record["priority"])
        # 应用配置覆盖
        config = record.get("config")
        if config:
            provider = registry.get_provider(pid)
            if provider is not None:
                try:
                    provider.apply_config(config)
                except Exception as e:
                    logger.warning("Failed to apply persisted config to provider %s: %s", pid, e)
        logger.info(
            "Applied persisted override for weather provider %s: enabled=%s priority=%d",
            pid, record["enabled"], record["priority"],
        )

