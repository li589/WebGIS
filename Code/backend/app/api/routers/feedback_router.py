"""问题反馈 API（网关反馈页双轨的「在线轨」）。

挂载前缀 ``/feedback/api``（nginx 在 ``location ^~ /feedback/`` 内嵌套反代到
FastAPI；后端宕机/维护期时前端自动降级为本地导出链路，不影响反馈可用性）。

端点矩阵：
- ``POST /feedback/api/reports``            匿名上传导出 JSON（multipart file），
  限流 + 大小/schema 校验 + 附件解包；返回 ``{reportId, token}``。
- ``GET  /feedback/api/session``            工程师端认证探测（admin session /
  admin 用户 Token / X-API-Key 服务密钥任一即可）。
- ``GET  /feedback/api/reports``            admin：服务端反馈摘要列表。
- ``GET  /feedback/api/reports/{rid}``      admin：完整报告 + 附件清单 + 进展。
- ``GET  /feedback/api/reports/{rid}/attachments/{name}``  admin：附件下载。
- ``GET  /feedback/api/reports/{rid}/response?token=``     用户凭上传时获得的
  token 查询自己反馈的处理进展（防编号枚举）。
- ``PUT  /feedback/api/reports/{rid}/response``            admin：发布/更新进展。

鉴权复用 credential_resolver（session cookie / X-API-Key 用户 Token /
服务密钥），不使用 Security() 声明以避免 openapi 安全契约漂移（F14 闸门）。
"""

from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.error_codes import AUTH_ERROR, CONFLICT_ERROR, ApiError
from app.api.rate_limit import client_ip
from app.services.credential_resolver import resolve_credential
from app.services.feedback_store import (
    MAX_ATTACHMENTS,
    MAX_UPLOAD_JSON_BYTES,
    get_feedback_store,
    validate_report_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback/api", tags=["feedback"])

_RESPONSE_STATUSES = {
    "received",
    "in_progress",
    "needs_info",
    "fixed",
    "closed",
    "rejected",
}
#: response 各字符串字段上限
_RESP_LIMITS = {
    "updatedAt": 40,
    "note": 300,
    "author": 40,
    "role": 40,
    "body": 2000,
    "name": 40,
}


def _require_feedback_admin(request: Request) -> dict:
    """工程师端鉴权：admin 会话 / admin 用户 Token / 服务密钥（role=admin）。

    dev_bypass 仅授 standard 角色，天然被拒绝——反馈处理台不开放开发旁路。
    """
    x_api_key = request.headers.get("x-api-key")
    ctx = resolve_credential(request, x_api_key)
    if ctx is not None and ctx.role == "admin":
        return {"username": ctx.username or "service", "source": ctx.source}
    if ctx is not None:
        raise ApiError(
            AUTH_ERROR,
            status_code=403,
            detail="Admin role required for feedback console.",
        )
    raise ApiError(
        AUTH_ERROR,
        status_code=401,
        detail="Authentication required.",
    )


def _clip(value: object, limit: int) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(value or ""))[:limit]


# ---------------------------------------------------------------------------
# 匿名：上传 + 进展查询
# ---------------------------------------------------------------------------


@router.post("/reports", status_code=201)
async def upload_report(request: Request, file: UploadFile = File(...)) -> dict:
    """接收用户导出的反馈 JSON（multipart 单文件），落盘并返回访问 token。"""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="上传文件为空。")
    if len(raw) > MAX_UPLOAD_JSON_BYTES:
        raise ApiError(
            CONFLICT_ERROR, status_code=413, detail="上传内容超过大小上限（60 MB）。"
        )
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail="不是合法的 JSON 文件。") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="JSON 结构不符（需要导出对象）。")

    report_id = str(payload.get("reportId") or "")
    inner = (
        payload.get("report") if isinstance(payload.get("report"), dict) else payload
    )
    if not report_id and isinstance(inner, dict):
        report_id = str(inner.get("id") or "")
    if not validate_report_id(report_id):
        raise HTTPException(
            status_code=422,
            detail="缺少或非法的反馈编号（需要 CGDA-BUG-* 导出文件）。",
        )

    attachments = payload.get("attachments")
    if attachments is not None and (
        not isinstance(attachments, list) or len(attachments) > MAX_ATTACHMENTS
    ):
        raise HTTPException(
            status_code=422, detail=f"附件数量超过上限（{MAX_ATTACHMENTS}）。"
        )

    store = get_feedback_store()
    if store.exists(report_id):
        raise ApiError(
            CONFLICT_ERROR,
            status_code=409,
            detail="该反馈编号已存在；如需重新提交请刷新反馈页生成新编号。",
        )
    try:
        token = store.save_report(report_id, payload, uploader_ip=client_ip(request))
    except FileExistsError:
        raise ApiError(CONFLICT_ERROR, status_code=409, detail="该反馈编号已存在。")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    logger.info("feedback uploaded report_id=%s ip=%s", report_id, client_ip(request))
    return {"reportId": report_id, "token": token}


@router.get("/reports/{report_id}/response")
def get_report_response(report_id: str, token: str = "") -> dict:
    """用户端进展查询：编号 + 上传时返回的 token（防编号枚举）。"""
    if not validate_report_id(report_id):
        raise HTTPException(status_code=404, detail="反馈不存在。")
    store = get_feedback_store()
    if not store.exists(report_id):
        raise HTTPException(status_code=404, detail="反馈不存在。")
    if not token or not store.verify_token(report_id, token):
        raise ApiError(AUTH_ERROR, status_code=401, detail="访问令牌无效。")
    response = store.read_response(report_id) or {"reportId": report_id, "status": None}
    return {
        "reportId": report_id,
        "response": response.get("status") and response or None,
    }


# ---------------------------------------------------------------------------
# 工程师端（admin）
# ---------------------------------------------------------------------------


@router.get("/session")
def feedback_session(admin: dict = Depends(_require_feedback_admin)) -> dict:
    """认证探测：成功返回身份信息（处理台据此启用服务端模式）。"""
    return {"authenticated": True, **admin}


@router.get("/reports")
def list_reports(admin: dict = Depends(_require_feedback_admin)) -> dict:
    return {"reports": get_feedback_store().list_summaries()}


@router.get("/reports/{report_id}")
def get_report(report_id: str, admin: dict = Depends(_require_feedback_admin)) -> dict:
    if not validate_report_id(report_id):
        raise HTTPException(status_code=404, detail="反馈不存在。")
    report = get_feedback_store().get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="反馈不存在。")
    return report


@router.get("/reports/{report_id}/attachments/{name}")
def download_attachment(
    report_id: str, name: str, admin: dict = Depends(_require_feedback_admin)
) -> FileResponse:
    path = get_feedback_store().attachment_path(report_id, name)
    if path is None:
        raise HTTPException(status_code=404, detail="附件不存在。")
    return FileResponse(path, filename=path.name)


@router.put("/reports/{report_id}/response")
async def put_report_response(
    report_id: str, request: Request, admin: dict = Depends(_require_feedback_admin)
) -> dict:
    """发布/更新处理进展（写入 response.json；用户端轮询可见）。"""
    if not validate_report_id(report_id):
        raise HTTPException(status_code=404, detail="反馈不存在。")
    store = get_feedback_store()
    if not store.exists(report_id):
        raise HTTPException(status_code=404, detail="反馈不存在。")
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001 - 统一 422
        raise HTTPException(status_code=422, detail="请求体不是合法 JSON。") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="请求体结构不符。")

    status_value = str(payload.get("status") or "")
    if status_value not in _RESPONSE_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status 取值须为：{'/'.join(sorted(_RESPONSE_STATUSES))}。",
        )

    def _clip_reply(r: object) -> dict | None:
        if not isinstance(r, dict):
            return None
        return {
            "author": _clip(r.get("author"), _RESP_LIMITS["author"]) or "开发者",
            "role": _clip(r.get("role"), _RESP_LIMITS["role"]),
            "body": _clip(r.get("body"), _RESP_LIMITS["body"]),
            "at": _clip(r.get("at"), _RESP_LIMITS["updatedAt"]),
        }

    def _clip_step(t: object) -> dict | None:
        if not isinstance(t, dict):
            return None
        step_status = str(t.get("status") or "")
        return {
            "status": step_status
            if step_status in _RESPONSE_STATUSES
            else status_value,
            "at": _clip(t.get("at"), _RESP_LIMITS["updatedAt"]),
            "note": _clip(t.get("note"), _RESP_LIMITS["note"]),
        }

    assignee_raw = payload.get("assignee")
    assignee = None
    if isinstance(assignee_raw, dict) and _clip(assignee_raw.get("name"), 40):
        assignee = {
            "name": _clip(assignee_raw.get("name"), 40),
            "role": _clip(assignee_raw.get("role"), 40),
        }

    replies = [_clip_reply(r) for r in (payload.get("replies") or [])[:50]]
    timeline = [_clip_step(t) for t in (payload.get("timeline") or [])[:30]]
    response_obj = {
        "reportId": report_id,
        "status": status_value,
        "updatedAt": _clip(payload.get("updatedAt"), _RESP_LIMITS["updatedAt"]),
        "assignee": assignee,
        "timeline": [t for t in timeline if t],
        "replies": [r for r in replies if r and r.get("body")],
    }
    store.write_response(report_id, response_obj)
    logger.info(
        "feedback response published report_id=%s status=%s by=%s",
        report_id,
        status_value,
        admin.get("username"),
    )
    return {"ok": True, "reportId": report_id, "response": response_obj}
