"""Read-only server tool runtime for Agent (search_layers)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_ALLOWED_TOOLS = frozenset({"search_layers"})


def execute_server_tool(
    name: str,
    args: dict[str, Any],
    *,
    cred: Any = None,
) -> dict[str, Any]:
    """Execute an allowed server tool. Raises ValueError for unknown/blocked tools."""
    tool = (name or "").strip()
    if tool == "run_workflow":
        return {
            "ok": False,
            "error": "run_workflow 未启用（本阶段禁止自动提交工作流）",
        }
    if tool not in _ALLOWED_TOOLS:
        return {"ok": False, "error": f"未知或未授权的服务端工具: {tool}"}
    if tool == "search_layers":
        return _search_layers(args, cred=cred)
    return {"ok": False, "error": f"未实现: {tool}"}


def _search_layers(args: dict[str, Any], *, cred: Any) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    try:
        limit = int(args.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(50, limit))
    if not query:
        return {"ok": False, "error": "query 不能为空"}

    from app.core.config import settings
    from app.services.layer_catalog import get_layer_catalog

    catalog = get_layer_catalog()
    items = list(catalog.items or [])
    env = (settings.environment or "").strip().lower()
    if env not in {"development", "dev", "test", "testing"}:
        items = [i for i in items if getattr(i, "status", None) != "placeholder"]

    layer_ids = [str(getattr(i, "layer_id", "") or "") for i in items]
    accessible = _filter_ids(layer_ids, cred)
    accessible_set = set(accessible)

    q = query.casefold()
    hits: list[dict[str, Any]] = []
    for item in items:
        lid = str(getattr(item, "layer_id", "") or "")
        if lid not in accessible_set:
            continue
        display = str(getattr(item, "display_name", "") or "")
        desc = str(getattr(item, "description", "") or "")
        tags = getattr(item, "tags", None) or []
        tag_s = " ".join(str(t) for t in tags) if isinstance(tags, list) else str(tags)
        blob = f"{lid} {display} {desc} {tag_s}".casefold()
        if q in blob:
            hits.append(
                {
                    "layer_id": lid,
                    "display_name": display,
                    "category": str(getattr(item, "category", "") or ""),
                    "description": desc[:200],
                }
            )
        if len(hits) >= limit:
            break

    return {"ok": True, "query": query, "count": len(hits), "layers": hits}


def _filter_ids(layer_ids: list[str], cred: Any) -> list[str]:
    if cred is None:
        return list(layer_ids)
    role = getattr(cred, "role", None)
    if role == "admin":
        return list(layer_ids)
    user_id = getattr(cred, "user_id", None)
    source = getattr(cred, "source", None)
    if user_id is None:
        if source in {"service_key", "dev_bypass"}:
            return list(layer_ids)
        return []
    try:
        from app.services.permission_repository import get_permission_repository

        return get_permission_repository().batch_filter_accessible(
            int(user_id), "layer", layer_ids
        )
    except Exception:
        logger.exception("ACL filter failed for search_layers")
        return []


def catalog_summary(*, cred: Any = None, limit: int = 40) -> list[dict[str, str]]:
    """Lightweight id/name list for system prompt injection."""
    from app.core.config import settings
    from app.services.layer_catalog import get_layer_catalog

    catalog = get_layer_catalog()
    items = list(catalog.items or [])
    env = (settings.environment or "").strip().lower()
    if env not in {"development", "dev", "test", "testing"}:
        items = [i for i in items if getattr(i, "status", None) != "placeholder"]
    ids = [str(getattr(i, "layer_id", "") or "") for i in items]
    accessible = set(_filter_ids(ids, cred))
    out: list[dict[str, str]] = []
    for item in items:
        lid = str(getattr(item, "layer_id", "") or "")
        if lid not in accessible:
            continue
        out.append(
            {
                "layer_id": lid,
                "display_name": str(getattr(item, "display_name", "") or lid),
            }
        )
        if len(out) >= limit:
            break
    return out


def load_server_tools_openai() -> list[dict[str, Any]]:
    """OpenAI tool defs for allowed server tools only (mtime-cached)."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "agentKits" / "tools" / "server_tools.json"
    try:
        mtime = path.stat().st_mtime if path.is_file() else None
    except OSError:
        mtime = None

    cache = getattr(load_server_tools_openai, "_cache", None)
    if (
        isinstance(cache, tuple)
        and len(cache) == 2
        and cache[0] == mtime
        and mtime is not None
    ):
        return [dict(t) for t in cache[1]]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        load_server_tools_openai._cache = (mtime, [])  # type: ignore[attr-defined]
        return []
    tools_raw = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools_raw, list):
        load_server_tools_openai._cache = (mtime, [])  # type: ignore[attr-defined]
        return []
    out: list[dict[str, Any]] = []
    for item in tools_raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name not in _ALLOWED_TOOLS:
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(item.get("description") or name),
                    "parameters": item.get("args")
                    or {"type": "object", "properties": {}},
                },
            }
        )
    load_server_tools_openai._cache = (mtime, out)  # type: ignore[attr-defined]
    return [dict(t) for t in out]


def load_server_tools_anthropic() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in load_server_tools_openai():
        fn = t.get("function") or {}
        out.append(
            {
                "name": fn.get("name"),
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return out
