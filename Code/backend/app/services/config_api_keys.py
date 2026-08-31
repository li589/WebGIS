"""L3 抽取：API Key 管理域。

从 config_service.py 拆分，负责 API Key 的 CRUD、历史管理、生效逻辑与测试。
包含：天地图、百度、高德、Bing、后端认证（backend_auth）。

依赖：
- app.services.api_keys_repository: 持久化
- app.services.api_config: ApiConfigManager 同步
- app.services.effective_config: 写入后 rehydrate
- app.core.ssrf: 出站 URL 校验
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Repository factory ──────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _get_api_keys_repository():
    """单例获取 ApiKeysRepository。"""
    from app.services.api_keys_repository import ApiKeysRepository

    db_path = str(Path(settings.gee_credentials_db_path).parent / "api_keys.sqlite3")
    return ApiKeysRepository(
        db_path=db_path,
        encryption_key=settings.gee_credentials_encryption_key,
        history_limit=settings.api_key_history_limit,
    )


# ── Predefined key metadata ─────────────────────────────────────────────────


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
    "bing": {
        "display_name": "Bing",
        "description": "Bing 底图可选 Key（当前瓦片模板可不填；预留与设置页对齐）",
    },
    "backend_auth": {
        "display_name": "后端认证",
        "description": "后端 API 访问令牌，用于保护写接口（X-Api-Key）",
    },
}


def _env_api_key_value(key_name: str) -> str:
    """从环境变量获取 API Key 值（DB 无行时的回退）。"""
    env_map = {
        "tianditu": settings.tianditu_api_key,
        "baidu": settings.baidu_api_key,
        "backend_auth": settings.api_key,
        "gaode": os.getenv("BACKEND_GAODE_API_KEY", ""),
        "bing": os.getenv("BACKEND_BING_API_KEY", ""),
    }
    return str(env_map.get(key_name) or "").strip()


def _annotate_key_entry(entry: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Attach source / has_value for settings UI + basemap availability."""
    annotated = dict(entry)
    annotated["source"] = source
    masked = str(annotated.get("masked_value") or "")
    annotated["has_value"] = bool(masked)
    return annotated


# ── CRUD ─────────────────────────────────────────────────────────────────────


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
    display_name: str | None = None,
    description: str | None = None,
    enabled: bool = True,
    history_label: str | None = None,
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
        from app.services.effective_config import (
            bump_effective_config_version,
            hydrate_effective_config,
        )

        hydrate_effective_config()
        bump_effective_config_version()
    except Exception:  # noqa: BLE001 — best-effort rehydrate, logged
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
        _sync_api_config_manager_key(key_name, get_effective_api_key(key_name) or "")
        try:
            from app.services.effective_config import (
                bump_effective_config_version,
                hydrate_effective_config,
            )

            hydrate_effective_config()
            bump_effective_config_version()
        except Exception:  # noqa: BLE001 — best-effort rehydrate, logged
            logger.exception(
                "Failed to rehydrate effective config after api key delete"
            )
    return deleted


def toggle_api_key(key_name: str, enabled: bool) -> dict[str, Any]:
    """启用/禁用 API Key。

    - 已有 DB 行：直接改 enabled
    - 仅有 env、无 DB 行：启用时物化到 DB；禁用时写入 DB 并 enabled=0
    - 无值：抛 ValueError，路由映射 400
    """
    repo = _get_api_keys_repository()
    meta = _API_KEY_META.get(key_name, {})
    info = repo.get_key_info(key_name)

    if info is None:
        env_value = _env_api_key_value(key_name)
        if not env_value:
            raise ValueError("请先保存 API Key 后再启用/禁用")
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
        from app.services.effective_config import (
            bump_effective_config_version,
            hydrate_effective_config,
        )

        hydrate_effective_config()
        bump_effective_config_version()
    except Exception:  # noqa: BLE001 — best-effort rehydrate, logged
        logger.exception("Failed to rehydrate effective config after api key toggle")

    info = repo.get_key_info(key_name) or {}
    if not info.get("display_name"):
        info["display_name"] = meta.get("display_name", key_name)
    return _annotate_key_entry(info, source="db")


# ── Effective key resolution ─────────────────────────────────────────────────


def _sync_api_config_manager_key(key_name: str, key_value: str) -> None:
    """将 effective key 投影到 ApiConfigManager。"""
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
    except Exception:  # noqa: BLE001 — best-effort sync, logged
        logger.exception("Failed to sync api_config_manager for key=%s", key_name)


@lru_cache(maxsize=32)
def _get_effective_api_key_cached(key_name: str) -> str | None:
    """DB 行存在时仅在 enabled 时生效；无 DB 行才回退 env。"""
    repo = _get_api_keys_repository()
    info = repo.get_key_info(key_name)
    if info is not None:
        return repo.get_key_value(key_name)

    env_value = _env_api_key_value(key_name)
    return env_value or None


def get_effective_api_key(key_name: str) -> str | None:
    """获取生效的 API Key（公开接口）。"""
    return _get_effective_api_key_cached(key_name)


def has_api_key_db_row(key_name: str) -> bool:
    """是否存在该 key 的 DB 行（无论 enabled）。

    发布就绪修复（P1-6）用于吊销语义：DB 有行（含禁用）时以 DB 为准、不回落 env。
    """
    return _get_api_keys_repository().get_key_info(key_name) is not None


def is_basemap_key_available(key_name: str) -> bool:
    """Whether a basemap provider key is currently effective (for UI gating)."""
    return bool(get_effective_api_key(key_name))


# ── Key testing ──────────────────────────────────────────────────────────────


async def test_api_key(key_name: str) -> tuple[bool, str]:
    """测试 API Key 是否有效。返回 (success, message)。"""
    key_value = get_effective_api_key(key_name)
    if not key_value:
        return False, "API Key 未配置"

    repo = _get_api_keys_repository()

    try:
        if key_name == "tianditu":
            import httpx

            from app.core.ssrf import SSRFBlockedError, validate_outbound_url
            from app.services.tile_proxy_service import TIANDITU_SERVER_USER_AGENT

            url = f"https://t0.tianditu.gov.cn/img_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=img&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILECOL=0&TILEROW=0&TILEMATRIX=0&tk={key_value}"
            try:
                validate_outbound_url(url, allow_private=False)
            except (SSRFBlockedError, ValueError) as exc:
                repo.update_test_status(key_name, "failed")
                return False, f"出站 URL 校验失败: {exc}"
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(10.0, connect=5.0)
                ) as client:
                    resp = await client.get(
                        url, headers={"User-Agent": TIANDITU_SERVER_USER_AGENT}
                    )
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
            import httpx

            from app.core.ssrf import SSRFBlockedError, validate_outbound_url

            url = f"https://maponline0.bdimg.com/tile/?qt=tile&x=0&y=0&z=1&styles=pl&v=020&udt=20231201&ak={key_value}"
            try:
                validate_outbound_url(url, allow_private=False)
            except (SSRFBlockedError, ValueError) as exc:
                repo.update_test_status(key_name, "failed")
                return False, f"出站 URL 校验失败: {exc}"
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(10.0, connect=5.0)
                ) as client:
                    resp = await client.get(
                        url, headers={"User-Agent": "CGDA-Backend/1.0"}
                    )
                if resp.status_code == 200:
                    repo.update_test_status(key_name, "ok")
                    return True, "百度地图 API Key 有效"
                elif resp.status_code == 403:
                    repo.update_test_status(key_name, "ok")
                    return (
                        True,
                        "百度地图 API Key 格式有效（瓦片访问受限但 key 已配置）",
                    )
                else:
                    msg = f"百度地图 API 返回 HTTP {resp.status_code}"
                    repo.update_test_status(key_name, "failed")
                    return False, msg
            except httpx.HTTPError as e:
                repo.update_test_status(key_name, "failed")
                return False, f"百度地图 API 测试失败: {e}"
        elif key_name == "backend_auth":
            if len(key_value) >= 8:
                repo.update_test_status(key_name, "ok")
                return True, "后端认证 Key 已配置"
            else:
                repo.update_test_status(key_name, "failed")
                return False, "后端认证 Key 长度不足（至少8位）"
        else:
            if key_value:
                repo.update_test_status(key_name, "ok")
                return True, f"API Key '{key_name}' 已配置"
            else:
                repo.update_test_status(key_name, "failed")
                return False, f"API Key '{key_name}' 为空"
    except Exception as e:  # noqa: BLE001 — test failure catch-all, logged
        logger.exception("test_api_key failed for key=%s", key_name)
        repo.update_test_status(key_name, "failed")
        return False, f"测试失败: {e}"
