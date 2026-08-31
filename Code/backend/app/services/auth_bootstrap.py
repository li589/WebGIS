"""Seed default admin + dev API key on startup (development only)."""

from __future__ import annotations

import logging
import os

from app.core import config

logger = logging.getLogger(__name__)

DEV_DEFAULT_API_KEY = os.getenv("BACKEND_DEV_DEFAULT_API_KEY", "")
DEV_DEFAULT_ADMIN_USER = os.getenv("BACKEND_ADMIN_USERNAME", "admin")
DEV_DEFAULT_ADMIN_PASSWORD = os.getenv("BACKEND_ADMIN_PASSWORD", "")

# 仅这些绑定地址允许在 development 环境使用默认凭据
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_development() -> bool:
    return (config.settings.environment or "").lower() in {"development", "dev"}


def _is_production_like() -> bool:
    env = (config.settings.environment or "").lower()
    return env not in {"development", "dev", "test", "testing"}


def _check_dev_credentials_safety() -> None:
    """development 环境下，若服务绑定非 loopback 地址，拒绝使用默认凭据。

    防止开发默认凭据（已知明文）暴露在可达网络上。0.0.0.0 也拒绝（监听全部接口）。
    """
    host = (config.settings.host or "").strip()
    if not host:
        return  # 未配置 host 时不拦截（通常默认 127.0.0.1）
    if host not in _LOOPBACK_HOSTS:
        raise RuntimeError(
            "Development default credentials are not safe when binding to "
            f"non-loopback address '{host}'. Set BACKEND_ADMIN_PASSWORD and "
            "BACKEND_API_KEY explicitly, or bind to 127.0.0.1/localhost."
        )


def bootstrap_auth() -> None:
    """Ensure admin account exists; in development seed default API key when unset."""
    if not config.settings.user_auth_enabled:
        logger.info(
            "User auth disabled (BACKEND_USER_AUTH_ENABLED=false); skipping bootstrap"
        )
        return

    from app.services.theme_repository import get_theme_repository
    from app.services.user_repository import get_user_repository

    # users schema first (theme_id column), then seed themes + backfill.
    repo = get_user_repository()
    get_theme_repository().ensure_primary_theme()

    admin_user = (config.settings.admin_username or "").strip()
    admin_password = config.settings.admin_password or ""

    if not admin_user and _is_development():
        _check_dev_credentials_safety()
        admin_user = DEV_DEFAULT_ADMIN_USER
        admin_password = DEV_DEFAULT_ADMIN_PASSWORD

    user_count = repo.count_users()
    if user_count == 0:
        if _is_production_like():
            raise RuntimeError(
                "BACKEND_USER_AUTH_ENABLED=true but no users exist. "
                "Set BACKEND_ADMIN_USERNAME and BACKEND_ADMIN_PASSWORD before first start."
            )
        if not admin_user or not admin_password:
            raise RuntimeError(
                "No users in database and admin credentials not configured."
            )
        try:
            repo.create_user(
                username=admin_user,
                password=admin_password,
                role="admin",
            )
            logger.info("Bootstrapped initial admin user: %s", admin_user)
        except ValueError:
            # 多进程同时启动（uvicorn workers > 1）时，多个 worker 可能同时判定
            # count==0 并并发创建 admin；唯一约束冲突属正常竞争，重查即可。
            existing = repo.get_by_username(admin_user)
            if existing is None:
                raise
            logger.warning(
                "Initial admin already bootstrapped by another worker: %s", admin_user
            )

    get_theme_repository().ensure_primary_theme()

    if _is_development():
        _check_dev_credentials_safety()
        _bootstrap_dev_api_key()


def _bootstrap_dev_api_key() -> None:
    """When development has no backend_auth, seed a known dev write key."""
    env_key = (config.settings.api_key or "").strip()
    if env_key:
        return
    if config.settings.api_key is not None and config.settings.api_key.strip() == "":
        # 配置了空串（如 .env 中 BACKEND_API_KEY=）会被静默回退到 dev 默认 key，
        # 若 administrator 误以为已配置真实密钥，将使用已知的默认 key——显式告警。
        logger.warning(
            "BACKEND_API_KEY is configured but empty; falling back to dev default "
            "write key (bootstrap). Remove the empty value or set a real key."
        )

    from app.services.config_service import _get_api_keys_repository
    from app.services.effective_config import (
        get_backend_auth_key,
        hydrate_effective_config,
    )

    if get_backend_auth_key():
        return

    default_key = (config.settings.dev_default_api_key or DEV_DEFAULT_API_KEY).strip()
    if not default_key:
        logger.warning(
            "Development bootstrap: skipped backend_auth seed — "
            "BACKEND_API_KEY / BACKEND_DEV_DEFAULT_API_KEY are empty. "
            "Set an explicit key before enabling write APIs."
        )
        return
    repo = _get_api_keys_repository()
    repo.upsert_key(
        key_name="backend_auth",
        key_value=default_key,
        display_name="后端认证",
        description="开发环境默认写接口密钥（调试期自动填入）",
        history_source="bootstrap",
        archive_previous=False,
    )
    hydrate_effective_config()
    os.environ.setdefault("BACKEND_API_KEY", default_key)
    os.environ.setdefault("BACKEND_API_KEYS_ENABLED", "true")
    logger.warning(
        "Development bootstrap: seeded backend_auth=%s (set BACKEND_API_KEY in .env to override)",
        default_key[:4] + "****",
    )
