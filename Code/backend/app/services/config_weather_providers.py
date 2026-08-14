"""天气源 Provider 管理域。

从 ``config_service.py`` 抽取的天气源 Provider CRUD / 测试 / 持久化覆盖逻辑。
包含：
- Repository / Registry 单例获取
- Provider 字典序列化
- 列表 / 详情 / 更新 / 启停 / 优先级 / 测试 / 删除
- 启动时 DB 覆盖应用（``apply_persisted_provider_overrides``）
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


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
        from app.weatherengine.provider_registry import (
            get_registry,
            register_default_providers,
        )

        register_default_providers()
        # 仅在 registry 刚从空变为有内容时应用一次 DB 覆盖；若已有 entries，
        # 启动路径已 apply 过。这里对缺失 provider 的新注册再次 apply 是安全的。
        apply_persisted_provider_overrides()
        _ = get_registry()
    except Exception:  # noqa: BLE001 — best-effort lazy registration, logged
        # 尽力而为：惰性注册失败不应阻塞配置读取
        logger.exception("Lazy weather provider registration failed")


def list_weather_providers(*, include_disabled: bool = True) -> list[dict[str, Any]]:
    """列出所有天气源 Provider（合并 registry 运行时实例 + DB 持久化配置）。"""
    _ensure_weather_providers_registered()
    registry = _get_weather_registry()
    repo = _get_weather_providers_repository()

    # 从 DB 读取持久化配置
    db_records = {
        r["provider_id"]: r
        for r in repo.list_providers(include_disabled=include_disabled)
    }

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

    # DB 中存在但 registry 中未注册的 Provider（过滤遗留 open-meteo，避免 UI 出现第三条幽灵行）
    from app.weatherengine.provider_ids import (
        OPEN_METEO_LEGACY_ID,
        OPEN_METEO_ONLINE_ID,
    )

    legacy = db_records.get(OPEN_METEO_LEGACY_ID)
    if legacy is not None and OPEN_METEO_LEGACY_ID not in seen_ids:
        # 一次性清理：遗留 id 合并到 online 后删除 DB 行
        try:
            online_existing = db_records.get(OPEN_METEO_ONLINE_ID)
            if online_existing is None:
                repo.upsert_provider(
                    provider_id=OPEN_METEO_ONLINE_ID,
                    display_name=legacy.get("display_name") or "Open-Meteo (Online)",
                    provider_type=legacy.get("provider_type") or "free_api",
                    enabled=bool(legacy.get("enabled", True)),
                    priority=int(legacy.get("priority", 1)),
                    config=legacy.get("config") or {},
                )
            repo.delete_provider(OPEN_METEO_LEGACY_ID)
            logger.info(
                "Migrated/removed legacy weather provider id %s", OPEN_METEO_LEGACY_ID
            )
        except Exception as exc:  # noqa: BLE001 — best-effort legacy cleanup, logged
            # 尽力而为：遗留 open-meteo 清理失败不应阻塞列表返回
            logger.warning("Failed to purge legacy open-meteo DB row: %s", exc)

    for pid, db_record in db_records.items():
        if pid in seen_ids:
            continue
        if pid == OPEN_METEO_LEGACY_ID:
            continue
        result.append(
            {
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
            }
        )

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
    new_enabled = (
        enabled if enabled is not None else (existing["enabled"] if existing else True)
    )
    new_priority = (
        priority
        if priority is not None
        else (existing["priority"] if existing else 100)
    )
    new_config = (
        config if config is not None else (existing["config"] if existing else None)
    )

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
        except Exception as e:  # noqa: BLE001 — best-effort config apply, logged
            logger.error("Failed to apply config to provider %s: %s", provider_id, e)

    return get_weather_provider(provider_id)


def toggle_weather_provider(provider_id: str, enabled: bool) -> dict[str, Any] | None:
    """启用/禁用 Provider。"""
    return update_weather_provider(provider_id, enabled=enabled)


def set_weather_provider_priority(
    provider_id: str, priority: int
) -> dict[str, Any] | None:
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
        "tested_at": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat(),
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
            except Exception:  # noqa: BLE001 — best-effort config reset, logged
                # 尽力而为：重置 config 失败不应阻塞 DB 删除
                logger.exception(
                    "Failed to reset provider config after delete: %s", provider_id
                )
    return deleted


def apply_persisted_provider_overrides() -> None:
    """启动时从 DB 加载 Provider 配置覆盖到 registry。

    在 ``register_default_providers`` 之后调用，使 DB 中的 enabled/priority/config 覆盖生效。
    """
    from app.weatherengine.provider_ids import OPEN_METEO_LOCAL_ID, OPEN_METEO_ONLINE_ID

    registry = _get_weather_registry()
    repo = _get_weather_providers_repository()

    try:
        records = repo.list_providers(include_disabled=True)
    except Exception as e:  # noqa: BLE001 — best-effort DB read, logged and falls back
        # 尽力而为：DB 读取失败时回退到默认配置
        logger.warning("Failed to load weather provider overrides from DB: %s", e)
        return

    by_id = {r["provider_id"]: r for r in records}
    online_rec = by_id.get(OPEN_METEO_ONLINE_ID)
    local_rec = by_id.get(OPEN_METEO_LOCAL_ID)

    # 清理遗留 open-meteo DB 行（合并到 online）
    legacy_rec = by_id.get("open-meteo")
    if legacy_rec is not None:
        try:
            if online_rec is None:
                repo.upsert_provider(
                    provider_id=OPEN_METEO_ONLINE_ID,
                    display_name=legacy_rec.get("display_name")
                    or "Open-Meteo (Online)",
                    provider_type=legacy_rec.get("provider_type") or "free_api",
                    enabled=bool(legacy_rec.get("enabled", True)),
                    priority=int(legacy_rec.get("priority", 1)),
                    config=legacy_rec.get("config") or {},
                )
            repo.delete_provider("open-meteo")
            logger.info("Purged legacy weather provider id open-meteo on startup")
            records = repo.list_providers(include_disabled=True)
            by_id = {r["provider_id"]: r for r in records}
            online_rec = by_id.get(OPEN_METEO_ONLINE_ID)
            local_rec = by_id.get(OPEN_METEO_LOCAL_ID)
        except Exception as e:  # noqa: BLE001 — best-effort legacy purge, logged
            # 尽力而为：遗留行清理失败不阻塞覆盖应用
            logger.warning("Failed to purge legacy open-meteo row: %s", e)

    # 一次性迁移：旧默认 online=0 / local=1 → 产品默认 local=0 / online=1
    if (
        online_rec is not None
        and local_rec is not None
        and int(online_rec.get("priority", 99)) == 0
        and int(local_rec.get("priority", 99)) == 1
    ):
        try:
            repo.upsert_provider(
                provider_id=OPEN_METEO_LOCAL_ID,
                enabled=bool(local_rec.get("enabled", True)),
                priority=0,
                config=local_rec.get("config") or {},
            )
            repo.upsert_provider(
                provider_id=OPEN_METEO_ONLINE_ID,
                enabled=bool(online_rec.get("enabled", True)),
                priority=1,
                config=online_rec.get("config") or {},
            )
            local_rec["priority"] = 0
            online_rec["priority"] = 1
            logger.info(
                "Migrated weather provider priorities to local-first "
                "(open-meteo-local=0, open-meteo-online=1)"
            )
            records = repo.list_providers(include_disabled=True)
        except Exception as e:  # noqa: BLE001 — best-effort priority migration, logged
            # 尽力而为：优先级迁移失败不阻塞覆盖应用
            logger.warning(
                "Failed to migrate open-meteo priorities to local-first: %s", e
            )

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
                except Exception as e:  # noqa: BLE001 — best-effort per-provider config apply, logged
                    # 尽力而为：单个 provider config 应用失败不阻塞其余
                    logger.warning(
                        "Failed to apply persisted config to provider %s: %s", pid, e
                    )
        logger.info(
            "Applied persisted override for weather provider %s: enabled=%s priority=%d",
            pid,
            record["enabled"],
            record["priority"],
        )
