"""L3 抽取：GEE 账户管理域。

从 config_service.py 拆分，负责 GEE 服务账户的 CRUD、启用/禁用、凭证测试
与 facade 重载。

依赖：
- app.services.gee_credentials_repository: 持久化
- app.services.gee_bridge_service: facade 重载
- app.gee.core.src.webgis_gee.accounts.credentials: 凭证加载与测试
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Repository factory ──────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _get_gee_credentials_repository():
    """单例获取 GeeCredentialsRepository。"""
    from app.services.gee_credentials_repository import GeeCredentialsRepository

    return GeeCredentialsRepository(
        db_path=settings.gee_credentials_db_path,
        encryption_key=settings.gee_credentials_encryption_key,
    )


# ── CRUD ─────────────────────────────────────────────────────────────────────


def list_gee_accounts() -> list[dict[str, Any]]:
    """列出所有 GEE 账户（脱敏）。"""
    repo = _get_gee_credentials_repository()
    return repo.list_accounts(include_disabled=True)


def add_gee_account(
    account_id: str,
    service_account_json: dict[str, Any],
    display_name: str | None = None,
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


# ── Credential testing ──────────────────────────────────────────────────────


async def test_gee_account(account_id: str) -> tuple[bool, str]:
    """测试 GEE 账户凭证是否有效。"""
    repo = _get_gee_credentials_repository()
    sa_json = repo.get_account_credentials(account_id)
    if not sa_json:
        repo.update_test_status(account_id, "failed")
        return False, f"GEE 账户 '{account_id}' 不存在或凭证为空"

    try:
        from app.gee.core.src.webgis_gee.accounts.credentials import (
            GeeCredentialsLoader,
        )

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
    except Exception as e:  # noqa: BLE001 — test failure catch-all, logged
        logger.exception("test_gee_account failed for account=%s", account_id)
        repo.update_test_status(account_id, "failed")
        return False, f"测试失败: {e}"


# ── Facade reload ───────────────────────────────────────────────────────────


def _reload_gee_facade() -> None:
    """重载 GEE facade，使账户池变更生效。"""
    try:
        from app.services.gee_bridge_service import reload_gee_facade

        reload_gee_facade()
        logger.info("GEE facade reloaded after account change")
    except Exception as e:  # noqa: BLE001 — best-effort facade reload, logged
        # 尽力而为：facade 重载失败不影响账户变更已持久化
        logger.warning("Failed to reload GEE facade: %s", e)


def reload_gee_account_pool() -> tuple[bool, int, str]:
    """手动重载 GEE 账户池。返回 (success, account_count, message)。"""
    try:
        _reload_gee_facade()
        repo = _get_gee_credentials_repository()
        accounts = repo.list_accounts(enabled_only=True)
        return True, len(accounts), f"账户池已重载，共 {len(accounts)} 个启用账户"
    except Exception as e:  # noqa: BLE001 — reload failure catch-all, logged
        logger.exception("reload_gee_account_pool failed")
        return False, 0, f"重载失败: {e}"
