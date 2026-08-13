"""Unified credential resolution: session, user API token, service key."""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from typing import Literal

from fastapi import Request

from app.core import config

logger = logging.getLogger(__name__)

CredentialSource = Literal["session", "user_token", "service_key", "dev_bypass"]

_WRITE_ROLES = frozenset({"admin", "standard"})
_CONFIG_MANAGEMENT_ROLES = frozenset({"admin"})
_WORKFLOW_CREATE_ROLES = frozenset({"admin", "standard"})
# demo 可提交/运行工作流（受并发上限约束），不可改配置/创建定义
_WORKFLOW_RUN_ROLES = frozenset({"admin", "standard", "demo"})
LOOPBACK_IPS = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True)
class CredentialContext:
    source: CredentialSource
    role: str
    user_id: int | None = None
    username: str | None = None
    token_id: int | None = None


def _direct_client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _dev_auth_bypass_explicit() -> bool:
    return os.getenv("BACKEND_DEV_AUTH_BYPASS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _live_user(user_id: int) -> dict | None:
    from app.services.user_repository import get_user_repository

    user = get_user_repository().get_by_id(user_id)
    if not user or not user.get("enabled"):
        return None
    return user


def resolve_credential(
    request: Request,
    x_api_key: str | None,
) -> CredentialContext | None:
    """Resolve request to a credential context, or None if unauthenticated."""
    if config.settings.user_auth_enabled:
        ctx = _resolve_session(request)
        if ctx is not None:
            return ctx
        if x_api_key:
            ctx = _resolve_api_key(x_api_key)
            if ctx is not None:
                return ctx

    if not config.settings.user_auth_enabled or x_api_key:
        ctx = _resolve_service_key_only(x_api_key)
        if ctx is not None:
            return ctx

    if dev_bypass_allowed(request):
        return CredentialContext(
            source="dev_bypass",
            role="standard",
            user_id=None,
            username=None,
        )

    return None


def _resolve_session(request: Request) -> CredentialContext | None:
    from app.services.session_service import get_session

    token = request.cookies.get(config.settings.session_cookie_name)
    if not token or not isinstance(token, str):
        return None
    session = get_session(token)
    if not session:
        return None
    user_id = int(session["user_id"])
    user = _live_user(user_id)
    if user is None:
        from app.services.session_service import revoke_session

        revoke_session(token)
        return None
    return CredentialContext(
        source="session",
        role=str(user["role"]),
        user_id=user_id,
        username=str(user["username"]),
    )


def _resolve_api_key(x_api_key: str) -> CredentialContext | None:
    from app.services.user_token_repository import get_user_token_repository

    row = get_user_token_repository().resolve_token(x_api_key)
    if row is None:
        return None
    user = _live_user(int(row["user_id"]))
    if user is None:
        return None
    return CredentialContext(
        source="user_token",
        role=str(user["role"]),
        user_id=int(user["id"]),
        username=str(user["username"]),
        token_id=int(row["id"]),
    )


def _resolve_service_key_only(x_api_key: str | None) -> CredentialContext | None:
    if not x_api_key:
        return None
    from app.services.effective_config import get_backend_auth_key

    configured = get_backend_auth_key() or ""
    if not configured:
        return None
    if not secrets.compare_digest(x_api_key, configured):
        return None
    role = (config.settings.api_key_role or "standard").strip().lower()
    if role not in _WRITE_ROLES:
        role = "standard"
    return CredentialContext(
        source="service_key",
        role=role,
        user_id=None,
        username="service",
    )


def dev_bypass_allowed(request: Request) -> bool:
    if (
        not config.settings.api_keys_enabled
        and config.settings.environment == "development"
    ):
        direct_host = _direct_client_host(request)
        if _dev_auth_bypass_explicit() or direct_host in LOOPBACK_IPS:
            logger.warning(
                "API-key authentication bypassed (dev_bypass, direct_host=%s)",
                direct_host,
            )
            return True
    return False


def allows_write(ctx: CredentialContext | None) -> bool:
    if ctx is None:
        return False
    return ctx.role in _WRITE_ROLES


def allows_sensitive_read(ctx: CredentialContext | None) -> bool:
    return allows_write(ctx)


def can_manage_config(ctx: CredentialContext | None) -> bool:
    """配置管理权限：仅 admin。"""
    if ctx is None:
        return False
    return ctx.role in _CONFIG_MANAGEMENT_ROLES


def can_create_workflow(ctx: CredentialContext | None) -> bool:
    """工作流定义创建权限：admin + standard。"""
    if ctx is None:
        return False
    return ctx.role in _WORKFLOW_CREATE_ROLES


def can_run_workflow(ctx: CredentialContext | None) -> bool:
    """工作流运行权限：admin + standard + demo。"""
    if ctx is None:
        return False
    return ctx.role in _WORKFLOW_RUN_ROLES


def can_data_transfer(ctx: CredentialContext | None) -> bool:
    """数据上传/下载权限：admin + standard 无限制；demo 受全局开关管控。"""
    if ctx is None:
        return False
    if ctx.role in _WRITE_ROLES:
        return True
    if ctx.role == "demo":
        return config.settings.demo_data_transfer_enabled
    return False
