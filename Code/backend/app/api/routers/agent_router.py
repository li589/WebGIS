"""Agent chat + multi-profile config API (global admin + personal)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from app.api.deps import get_request_user, require_write_access
from app.api.error_codes import AUTH_ERROR, ApiError
from app.core import config
from app.services.agent import config_service
from app.services.agent.clients.openai_compat import LlmClientError
from app.services.agent.config_service import AgentPermissionError
from app.services.agent.orchestrator import refresh_models_for_profile, run_chat
from app.services.credential_resolver import CredentialContext, allows_write, dev_bypass_allowed

router = APIRouter(prefix="/agent", tags=["agent"])

AgentProtocolLiteral = Literal["openai", "anthropic", "demo"]
AgentScopeLiteral = Literal["global", "personal"]
LegacyProviderLiteral = Literal["mock", "ollama", "openai_compatible"]


class AgentUiIntent(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class AgentTokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = False


class AgentStep(BaseModel):
    type: Literal["thought", "tool", "tool_result"] = "thought"
    summary: str
    detail: str | None = None


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=0, max_length=4000)
    session_id: str | None = Field(default=None, max_length=128)
    client_context: dict[str, Any] | None = None


class AgentChatResponse(BaseModel):
    session_id: str
    reply: str
    ui_intents: list[AgentUiIntent] = Field(default_factory=list)
    provider: str = "demo"
    profile_id: str | None = None
    usage: AgentTokenUsage | None = None
    steps: list[AgentStep] = Field(default_factory=list)


class AgentProfilePublic(BaseModel):
    id: str
    name: str
    provider_kind: str
    protocol: AgentProtocolLiteral
    base_url: str = ""
    model: str = ""
    context_window_input: int = 8192
    context_window_output: int = 4096
    preset_id: str | None = None
    scope: AgentScopeLiteral = "global"
    enabled: bool = False
    has_api_key: bool = False


class AgentPresetPublic(BaseModel):
    id: str
    name: str
    provider_kind: str
    protocol: AgentProtocolLiteral
    base_url: str = ""
    model: str = ""
    context_window_input: int = 8192
    context_window_output: int = 4096
    needs_api_key: bool = True


class AgentConfigBundleResponse(BaseModel):
    active_profile_id: str
    active_scope: AgentScopeLiteral = "global"
    can_manage_global: bool = False
    can_manage_personal: bool = False
    profiles: list[AgentProfilePublic] = Field(default_factory=list)
    presets: list[AgentPresetPublic] = Field(default_factory=list)


class AgentProfileCreateRequest(BaseModel):
    preset_id: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=128)
    scope: AgentScopeLiteral = "personal"


class AgentProfileUpdateRequest(BaseModel):
    scope: AgentScopeLiteral = "personal"
    name: str | None = Field(default=None, max_length=128)
    protocol: AgentProtocolLiteral | None = None
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=256)
    context_window_input: int | None = Field(default=None, ge=256, le=2_000_000)
    context_window_output: int | None = Field(default=None, ge=64, le=512_000)
    api_key: str | None = Field(default=None, max_length=2048)
    clear_api_key: bool = False


class AgentActiveRequest(BaseModel):
    profile_id: str = Field(min_length=1, max_length=64)
    scope: AgentScopeLiteral = "personal"


class AgentModelsRefreshRequest(BaseModel):
    profile_id: str | None = Field(default=None, max_length=64)
    scope: AgentScopeLiteral | None = None


class AgentModelsRefreshResponse(BaseModel):
    profile_id: str
    models: list[str] = Field(default_factory=list)
    manual: bool = False
    error: str | None = None


class AgentConfigResponse(BaseModel):
    provider: LegacyProviderLiteral = "mock"
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = "qwen2.5"
    has_api_key: bool = False


class AgentConfigUpdateRequest(BaseModel):
    provider: LegacyProviderLiteral | None = None
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=2048)
    clear_api_key: bool = False


def _require_agent_access(
    request: Request,
    cred: CredentialContext | None,
) -> None:
    if cred is not None:
        return
    if (
        not config.settings.api_keys_enabled
        and (config.settings.environment or "").lower()
        in {"development", "dev", "test", "testing"}
        and dev_bypass_allowed(request)
    ):
        return
    raise ApiError(
        AUTH_ERROR,
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


def _cred_meta(cred: CredentialContext | None) -> tuple[int | None, str | None]:
    if cred is None:
        return None, None
    return cred.user_id, cred.role


def _perm_error(exc: AgentPermissionError) -> ApiError:
    return ApiError(
        AUTH_ERROR,
        status_code=status.HTTP_403_FORBIDDEN,
        detail=str(exc),
    )


def _value_error(exc: ValueError) -> ApiError:
    return ApiError(
        AUTH_ERROR,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(exc),
    )


def _require_profile_write(cred: CredentialContext | None) -> None:
    """Writable role required (admin/standard); demo blocked."""
    if cred is None:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    if not allows_write(cred):
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this operation.",
        )


@router.get("/config", response_model=AgentConfigBundleResponse)
def get_agent_config(
    request: Request,
    cred: CredentialContext | None = Depends(get_request_user),
) -> AgentConfigBundleResponse:
    _require_agent_access(request, cred)
    uid, role = _cred_meta(cred)
    data = config_service.get_config_bundle(user_id=uid, role=role)
    return AgentConfigBundleResponse(**data)


@router.put("/config", response_model=AgentConfigResponse)
def put_agent_config_legacy(
    payload: AgentConfigUpdateRequest,
    request: Request,
    cred: CredentialContext | None = Depends(get_request_user),
    _write_ok: None = Depends(require_write_access),
) -> AgentConfigResponse:
    uid, role = _cred_meta(cred)
    try:
        data = config_service.update_agent_config(
            provider=payload.provider,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
            clear_api_key=payload.clear_api_key,
            user_id=uid,
            role=role,
        )
    except AgentPermissionError as exc:
        raise _perm_error(exc) from exc
    except ValueError as exc:
        raise _value_error(exc) from exc
    return AgentConfigResponse(**data)


@router.post("/config/profiles", response_model=AgentProfilePublic)
def create_agent_profile(
    payload: AgentProfileCreateRequest,
    cred: CredentialContext | None = Depends(get_request_user),
    _write_ok: None = Depends(require_write_access),
) -> AgentProfilePublic:
    _require_profile_write(cred)
    uid, role = _cred_meta(cred)
    try:
        data = config_service.create_profile_from_preset(
            payload.preset_id,
            name=payload.name,
            scope=payload.scope,
            user_id=uid,
            role=role,
        )
    except AgentPermissionError as exc:
        raise _perm_error(exc) from exc
    except ValueError as exc:
        raise _value_error(exc) from exc
    return AgentProfilePublic(**data)


@router.put("/config/profiles/{profile_id}", response_model=AgentProfilePublic)
def update_agent_profile(
    profile_id: str,
    payload: AgentProfileUpdateRequest,
    cred: CredentialContext | None = Depends(get_request_user),
    _write_ok: None = Depends(require_write_access),
) -> AgentProfilePublic:
    _require_profile_write(cred)
    uid, role = _cred_meta(cred)
    try:
        data = config_service.update_profile(
            profile_id,
            scope=payload.scope,
            user_id=uid,
            role=role,
            name=payload.name,
            protocol=payload.protocol,
            base_url=payload.base_url,
            model=payload.model,
            context_window_input=payload.context_window_input,
            context_window_output=payload.context_window_output,
            api_key=payload.api_key,
            clear_api_key=payload.clear_api_key,
        )
    except AgentPermissionError as exc:
        raise _perm_error(exc) from exc
    except ValueError as exc:
        raise _value_error(exc) from exc
    return AgentProfilePublic(**data)


@router.delete("/config/profiles/{profile_id}", response_model=AgentConfigBundleResponse)
def delete_agent_profile(
    profile_id: str,
    scope: AgentScopeLiteral = "personal",
    cred: CredentialContext | None = Depends(get_request_user),
    _write_ok: None = Depends(require_write_access),
) -> AgentConfigBundleResponse:
    _require_profile_write(cred)
    uid, role = _cred_meta(cred)
    try:
        data = config_service.delete_profile(
            profile_id, scope=scope, user_id=uid, role=role
        )
    except AgentPermissionError as exc:
        raise _perm_error(exc) from exc
    except ValueError as exc:
        raise _value_error(exc) from exc
    return AgentConfigBundleResponse(**data)


@router.post("/config/active", response_model=AgentConfigBundleResponse)
def set_active_agent_profile(
    payload: AgentActiveRequest,
    cred: CredentialContext | None = Depends(get_request_user),
    _write_ok: None = Depends(require_write_access),
) -> AgentConfigBundleResponse:
    _require_profile_write(cred)
    uid, role = _cred_meta(cred)
    try:
        if payload.scope == "global" and role != "admin":
            # Non-admin "use this global profile" → clear personal active
            if uid is None:
                raise AgentPermissionError("需要登录用户才能回退到全局配置档")
            data = config_service.clear_personal_active(user_id=uid, role=role)
        else:
            data = config_service.set_active_profile(
                payload.profile_id,
                scope=payload.scope,
                user_id=uid,
                role=role,
            )
    except AgentPermissionError as exc:
        raise _perm_error(exc) from exc
    except ValueError as exc:
        raise _value_error(exc) from exc
    return AgentConfigBundleResponse(**data)


@router.post("/config/use-global", response_model=AgentConfigBundleResponse)
def use_global_agent_profile(
    cred: CredentialContext | None = Depends(get_request_user),
    _write_ok: None = Depends(require_write_access),
) -> AgentConfigBundleResponse:
    """Clear personal active so chat falls back to global active."""
    _require_profile_write(cred)
    uid, role = _cred_meta(cred)
    if uid is None:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要登录用户",
        )
    try:
        data = config_service.clear_personal_active(user_id=uid, role=role)
    except AgentPermissionError as exc:
        raise _perm_error(exc) from exc
    return AgentConfigBundleResponse(**data)


@router.post("/models/refresh", response_model=AgentModelsRefreshResponse)
def refresh_agent_models(
    payload: AgentModelsRefreshRequest,
    request: Request,
    cred: CredentialContext | None = Depends(get_request_user),
) -> AgentModelsRefreshResponse:
    _require_agent_access(request, cred)
    uid, role = _cred_meta(cred)
    bundle = config_service.get_config_bundle(user_id=uid, role=role)
    pid = (payload.profile_id or bundle["active_profile_id"]).strip()
    scope: AgentScopeLiteral = payload.scope or bundle.get("active_scope") or "global"
    raw = config_service.get_profile_raw(pid, scope=scope, user_id=uid)
    if raw is None and scope == "personal":
        raw = config_service.get_profile_raw(pid, scope="global", user_id=uid)
    if raw is None:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"配置档不存在: {pid}",
        )
    result = refresh_models_for_profile(raw)
    return AgentModelsRefreshResponse(
        profile_id=pid,
        models=list(result.get("models") or []),
        manual=bool(result.get("manual")),
        error=result.get("error"),
    )


@router.post("/chat", response_model=AgentChatResponse)
def agent_chat(
    payload: AgentChatRequest,
    request: Request,
    cred: CredentialContext | None = Depends(get_request_user),
) -> AgentChatResponse:
    _require_agent_access(request, cred)
    uid, _role = _cred_meta(cred)
    try:
        result = run_chat(
            payload.message,
            session_id=payload.session_id,
            client_context=payload.client_context,
            user_id=uid,
            cred=cred,
        )
    except ValueError as exc:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except LlmClientError as exc:
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    usage_raw = result.get("usage")
    usage = AgentTokenUsage(**usage_raw) if isinstance(usage_raw, dict) else None
    steps = [
        AgentStep(
            type=str(s.get("type") or "thought"),  # type: ignore[arg-type]
            summary=str(s.get("summary") or ""),
            detail=s.get("detail"),
        )
        for s in (result.get("steps") or [])
        if isinstance(s, dict)
    ]
    return AgentChatResponse(
        session_id=str(result["session_id"]),
        reply=str(result["reply"]),
        ui_intents=[
            AgentUiIntent(name=str(i["name"]), args=dict(i.get("args") or {}))
            for i in (result.get("ui_intents") or [])
            if isinstance(i, dict)
        ],
        provider=str(result.get("provider") or "demo"),
        profile_id=result.get("profile_id"),
        usage=usage,
        steps=steps,
    )
