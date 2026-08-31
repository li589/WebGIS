"""OpenAI-compatible chat + models HTTP client (SSRF-safe)."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin

from app.core.ssrf import SSRFBlockedError, default_allow_private, safe_urlopen

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60.0


class LlmClientError(RuntimeError):
    """User-facing LLM HTTP / protocol error (no secrets)."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _normalize_base(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/") + "/"


def _headers(api_key: str | None) -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
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
        # Agent LLM 出站允许环回（本机 Ollama）；safe_urlopen 首参必须是 URL 字符串。
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
            f"模型服务返回 HTTP {exc.code}" + (f"：{detail}" if detail else ""),
            status_code=exc.code,
        ) from exc
    except URLError as exc:
        raise LlmClientError(f"无法连接模型服务：{exc.reason}") from exc
    except TimeoutError as exc:
        raise LlmClientError("模型服务请求超时") from exc
    except OSError as exc:
        raise LlmClientError(f"无法连接模型服务：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise LlmClientError("模型服务返回非 JSON") from exc


def chat_completions(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    url = urljoin(_normalize_base(base_url), "chat/completions")
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    return _request_json(
        "POST",
        url,
        headers=_headers(api_key),
        body=body,
        timeout=timeout,
    )


def list_models(
    *, base_url: str, api_key: str | None, timeout: float = 30.0
) -> list[str]:
    url = urljoin(_normalize_base(base_url), "models")
    data = _request_json("GET", url, headers=_headers(api_key), timeout=timeout)
    items = data.get("data")
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            out.append(str(item["id"]))
        elif isinstance(item, str):
            out.append(item)
    return out


def list_ollama_tags(*, base_url: str, timeout: float = 30.0) -> list[str]:
    """Ollama native GET /api/tags (base may be .../v1 — strip to root)."""
    root = (base_url or "").strip().rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    url = urljoin(root.rstrip("/") + "/", "api/tags")
    data = _request_json(
        "GET", url, headers={"Accept": "application/json"}, timeout=timeout
    )
    models = data.get("models")
    if not isinstance(models, list):
        return []
    out: list[str] = []
    for m in models:
        if isinstance(m, dict) and m.get("name"):
            out.append(str(m["name"]))
    return out
