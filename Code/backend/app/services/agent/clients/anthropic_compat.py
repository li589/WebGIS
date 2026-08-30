"""Anthropic Messages API compatible client (SSRF-safe)."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin

from app.core.ssrf import SSRFBlockedError, default_allow_private, safe_urlopen
from app.services.agent.clients.openai_compat import LlmClientError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60.0
ANTHROPIC_VERSION = "2023-06-01"


def _normalize_base(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/") + "/"


def _headers(api_key: str | None) -> dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "anthropic-version": ANTHROPIC_VERSION,
    }
    if api_key:
        h["x-api-key"] = api_key
    return h


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    try:
        with safe_urlopen(
            url,
            timeout=timeout,
            headers=headers,
            data=data,
            method=method,
            allow_private=default_allow_private(),
            allow_loopback=True,
        ) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return {}
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"data": parsed}
    except SSRFBlockedError as exc:
        raise LlmClientError(f"模型地址被安全策略阻断：{exc}") from exc
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = str(exc.reason or "")
        raise LlmClientError(
            f"Anthropic 兼容服务返回 HTTP {exc.code}"
            + (f"：{detail}" if detail else ""),
            status_code=exc.code,
        ) from exc
    except URLError as exc:
        raise LlmClientError(f"无法连接 Anthropic 兼容服务：{exc.reason}") from exc
    except TimeoutError as exc:
        raise LlmClientError("Anthropic 兼容服务请求超时") from exc
    except OSError as exc:
        raise LlmClientError(f"无法连接 Anthropic 兼容服务：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise LlmClientError("Anthropic 兼容服务返回非 JSON") from exc


def messages_create(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.2,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    url = urljoin(_normalize_base(base_url), "v1/messages")
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
    return _request_json(
        "POST",
        url,
        headers=_headers(api_key),
        body=body,
        timeout=timeout,
    )


def list_models(*, base_url: str, api_key: str | None, timeout: float = 30.0) -> list[str]:
    """Best-effort; many Anthropic-compatible gateways lack models listing."""
    url = urljoin(_normalize_base(base_url), "v1/models")
    try:
        data = _request_json("GET", url, headers=_headers(api_key), timeout=timeout)
    except LlmClientError:
        return []
    items = data.get("data") or data.get("models")
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            out.append(str(item["id"]))
    return out
