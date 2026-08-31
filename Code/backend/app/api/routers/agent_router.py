"""Agent chat + multi-profile config API (global admin + personal)."""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Iterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import check_resource_access, get_request_user, require_write_access
from app.api.error_codes import (
    AUTH_ERROR,
    NOT_FOUND_ERROR,
    UPSTREAM_ERROR,
    VALIDATION_ERROR,
    ApiError,
)

logger = logging.getLogger(__name__)
from app.core import config
from app.services.agent import config_service
from app.services.agent.clients.openai_compat import LlmClientError
from app.services.agent.config_service import AgentPermissionError
from app.services.agent.orchestrator import refresh_models_for_profile, run_chat
from app.services.credential_resolver import (
    CredentialContext,
    allows_write,
    dev_bypass_allowed,
)

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


class AgentConfirmation(BaseModel):
    confirmation_id: str
    action: str = "run_workflow"
    expires_at: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


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
    confirmations: list[AgentConfirmation] = Field(default_factory=list)


class AgentConfirmRequest(BaseModel):
    confirmation_id: str = Field(min_length=8, max_length=64)
    decision: Literal["approve", "reject"] = "approve"


class AgentConfirmResponse(BaseModel):
    confirmation_id: str
    status: str
    summary: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    status_url: str | None = None
    message: str = ""


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
    # Optional draft overrides so unsaved Base URL / API Key edits can refresh.
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=2048)


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
        VALIDATION_ERROR,
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


@router.delete(
    "/config/profiles/{profile_id}", response_model=AgentConfigBundleResponse
)
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
    if scope == "global" and role != "admin":
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅管理员可刷新全局配置档的模型列表。",
        )
    raw = config_service.get_profile_raw(pid, scope=scope, user_id=uid)
    if raw is None and scope == "personal":
        raw = config_service.get_profile_raw(pid, scope="global", user_id=uid)
        if raw is not None and role != "admin":
            raise ApiError(
                AUTH_ERROR,
                status_code=status.HTTP_403_FORBIDDEN,
                detail="仅管理员可刷新全局配置档的模型列表。",
            )
    if raw is None:
        raise ApiError(
            NOT_FOUND_ERROR,
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"配置档不存在: {pid}",
        )
    raw_for_refresh = dict(raw)
    draft_url = (payload.base_url or "").strip()
    if draft_url:
        raw_for_refresh["base_url"] = draft_url
    draft_key = (payload.api_key or "").strip() or None
    try:
        result = refresh_models_for_profile(raw_for_refresh, api_key_override=draft_key)
    except Exception as exc:
        logger.exception("agent models refresh crashed profile=%s", pid)
        result = {
            "models": [],
            "manual": True,
            "error": f"刷新模型列表失败：{exc}",
        }
    return AgentModelsRefreshResponse(
        profile_id=pid,
        models=[str(m) for m in (result.get("models") or []) if m is not None],
        manual=bool(result.get("manual")),
        error=str(result["error"]) if result.get("error") else None,
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
            VALIDATION_ERROR,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except LlmClientError as exc:
        raise ApiError(
            UPSTREAM_ERROR,
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return _chat_result_to_response(result)


def _sse_pack(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _chat_result_to_response(result: dict[str, Any]) -> AgentChatResponse:
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
    confirmations = [
        AgentConfirmation(
            confirmation_id=str(c.get("confirmation_id") or ""),
            action=str(c.get("action") or "run_workflow"),
            expires_at=str(c.get("expires_at") or ""),
            summary=dict(c.get("summary") or {})
            if isinstance(c.get("summary"), dict)
            else {},
            message=str(c.get("message") or ""),
        )
        for c in (result.get("confirmations") or [])
        if isinstance(c, dict) and c.get("confirmation_id")
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
        confirmations=confirmations,
    )


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "SSE stream: token | step | intent | done | error",
            "content": {"text/event-stream": {}},
        }
    },
)
def agent_chat_stream(
    payload: AgentChatRequest,
    request: Request,
    cred: CredentialContext | None = Depends(get_request_user),
) -> StreamingResponse:
    """SSE chat stream (Phase D). Events: token, step, intent, done, error."""
    _require_agent_access(request, cred)
    uid, _role = _cred_meta(cred)

    def event_iter() -> Iterator[str]:
        q: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()

        def on_event(kind: str, data: dict[str, Any]) -> None:
            q.put((kind, data))

        def worker() -> None:
            try:
                result = run_chat(
                    payload.message,
                    session_id=payload.session_id,
                    client_context=payload.client_context,
                    user_id=uid,
                    cred=cred,
                    on_event=on_event,
                )
                done = _chat_result_to_response(result).model_dump(mode="json")
                q.put(("done", done))
            except ValueError as exc:
                q.put(
                    (
                        "error",
                        {
                            "error_code": VALIDATION_ERROR,
                            "detail": str(exc),
                            "status_code": 422,
                        },
                    )
                )
            except LlmClientError as exc:
                q.put(
                    (
                        "error",
                        {
                            "error_code": UPSTREAM_ERROR,
                            "detail": str(exc),
                            "status_code": 502,
                        },
                    )
                )
            except Exception as exc:
                logger.exception("agent chat stream failed")
                q.put(
                    (
                        "error",
                        {
                            "error_code": UPSTREAM_ERROR,
                            "detail": f"模型调用失败：{exc}",
                            "status_code": 502,
                        },
                    )
                )
            finally:
                q.put(None)

        threading.Thread(target=worker, daemon=True, name="agent-chat-stream").start()
        while True:
            item = q.get()
            if item is None:
                break
            kind, data = item
            yield _sse_pack(kind, data)

    return StreamingResponse(
        event_iter(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/confirm", response_model=AgentConfirmResponse)
def agent_confirm(
    payload: AgentConfirmRequest,
    cred: CredentialContext | None = Depends(get_request_user),
    _write_ok: None = Depends(require_write_access),
) -> AgentConfirmResponse:
    """Approve or reject a pending Agent confirmation ticket (Phase B)."""
    _require_profile_write(cred)
    uid, role = _cred_meta(cred)
    from app.services.agent.agent_confirm import consume_confirmation
    from shared.contracts.api_contracts import WorkflowSubmitRequest

    try:
        consumed = consume_confirmation(
            payload.confirmation_id,
            user_id=uid,
            role=role,
            decision=payload.decision,
        )
    except ValueError as exc:
        raise _value_error(exc) from exc

    if consumed.get("status") == "rejected":
        return AgentConfirmResponse(
            confirmation_id=payload.confirmation_id,
            status="rejected",
            summary=dict(consumed.get("summary") or {}),
            message="已取消提交",
        )

    raw_payload = consumed.get("submit_payload")
    if not isinstance(raw_payload, dict):
        raise ApiError(
            VALIDATION_ERROR,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="确认票据缺少提交快照",
        )

    try:
        submit_req = WorkflowSubmitRequest.model_validate(raw_payload)
    except Exception as exc:
        raise ApiError(
            VALIDATION_ERROR,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"提交快照无效: {exc}",
        ) from exc

    if submit_req.layer_id:
        check_resource_access(cred, "layer", submit_req.layer_id)

    from app.services.workflow.service_container import submission_service

    try:
        accepted = submission_service.submit_workflow(
            submit_req,
            user_id=uid,
            role=role,
        )
    except ValueError as exc:
        raise ApiError(
            VALIDATION_ERROR,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info(
        "Agent confirmation approved confirmation_id=%s run_id=%s user=%s",
        payload.confirmation_id,
        accepted.run_id,
        uid,
    )

    return AgentConfirmResponse(
        confirmation_id=payload.confirmation_id,
        status="approved",
        summary=dict(consumed.get("summary") or {}),
        run_id=accepted.run_id,
        status_url=accepted.status_url,
        message=f"已提交工作流 {accepted.run_id}",
    )
