"""Agent chat orchestrator — memory, tools, demo/LLM paths, CoT steps."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.logging import get_request_id
from app.services.agent.clients import anthropic_compat, openai_compat
from app.services.agent.clients.openai_compat import LlmClientError
from app.services.agent.config_service import (
    get_effective_profile_raw,
    get_profile_api_key,
)
from app.services.agent.mock_orchestrator import mock_chat
from app.services.agent.naming import fmt_value, human_layer_name
from app.services.agent.server_tools_runtime import (
    ALLOWED_SERVER_TOOLS,
    catalog_summary,
    execute_server_tool,
    load_server_tools_anthropic,
    load_server_tools_openai,
)
from app.services.agent.session_store import append_turn, load_history
from app.services.agent.usage import (
    estimate_tokens,
    usage_from_anthropic,
    usage_from_openai,
)

logger = logging.getLogger(__name__)

_ALLOWED_INTENTS = frozenset(
    {
        "set_layer_visibility",
        "set_layer_opacity",
        "fit_layer",
        "list_active_layers",
        # Map viewport / basemap (FE aliases included so tool-call variants pass allowlist)
        "fit_china",
        "zoom_to_china",
        "locate_coordinate",
        "fly_to_location",
        "fly_to",
        "switch_basemap",
        "set_basemap",
        # P1 timeline / stack / symbology
        "set_timeline",
        "set_timeline_playing",
        "remove_layer",
        "reorder_layer",
        "set_layer_symbology",
    }
)
_SERVER_TOOLS = ALLOWED_SERVER_TOOLS

_CLIENT_CONTEXT_MAX_CHARS = 4000
_CLIENT_CONTEXT_MAX_LAYERS = 40

EventCallback = Callable[[str, dict[str, Any]], None]


def _max_tool_hops() -> int:
    """Bounded multi-hop tool rounds (Phase C). Env: BACKEND_AGENT_MAX_TOOL_HOPS."""
    raw = os.getenv("BACKEND_AGENT_MAX_TOOL_HOPS", "4")
    try:
        return max(1, min(8, int(raw)))
    except (TypeError, ValueError):
        return 4


# --- 并发闸门 / 降级 -------------------------------------------------------
# 地图助手与主服务同进程运行，路由是同步 def ⇒ 由 anyio 线程池（默认 40 线程）
# 承载。模型调用是 urllib 同步阻塞，若不设上限，几十个并发对话就能把线程池
# 占满，地图请求开始排队。这里加一道闸门：只放行少量对话，其余快速返回可读
# 提示（而不是把线程挂住 30 秒）。

_GATE_LOCK = threading.Lock()
_GATE: threading.BoundedSemaphore | None = None
_GATE_SIZE = -1


def _env_int(name: str, default: int, *, low: int, high: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return max(low, min(high, int(raw)))
    except (TypeError, ValueError):
        return default


def _gate() -> threading.BoundedSemaphore:
    """按配置惰性创建并发闸门（配置改了会自动重建）。"""
    global _GATE, _GATE_SIZE
    size = _env_int("BACKEND_AGENT_MAX_CONCURRENT", 2, low=1, high=16)
    with _GATE_LOCK:
        if _GATE is None or _GATE_SIZE != size:
            _GATE = threading.BoundedSemaphore(size)
            _GATE_SIZE = size
        return _GATE


def _gate_wait_seconds() -> float:
    return float(_env_int("BACKEND_AGENT_QUEUE_TIMEOUT", 15, low=0, high=120))


def _degraded_result(
    *,
    session_id: str | None,
    reply: str,
    provider: str,
    reason: str = "",
    on_event: EventCallback | None = None,
) -> dict[str, Any]:
    """构造一条「助手不可用但地图照用」的降级回复（HTTP 仍是 200）。"""
    sid = (session_id or "").strip() or uuid.uuid4().hex
    steps: list[dict[str, Any]] = [
        {
            "type": "thought",
            "summary": "助手已降级",
            "detail": reason or provider,
        }
    ]
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": estimate_tokens(reply),
        "total_tokens": estimate_tokens(reply),
        "estimated": True,
    }
    _emit_stream_tail(on_event, reply=reply, ui_intents=[])
    return {
        "session_id": sid,
        "reply": reply,
        "ui_intents": [],
        "provider": provider,
        "profile_id": None,
        "usage": usage,
        "steps": steps,
        "confirmations": [],
    }


def _busy_reply() -> str:
    return (
        "现在问助手的人有点多，这条没能排上。"
        "**地图本身不受影响**：底图、图层、时间轴、点查都可以正常用。\n\n"
        "稍等几秒再问一次即可。"
    )


def _llm_down_reply(detail: str) -> str:
    hint = _friendly_tool_error(detail) or "模型服务没有响应"
    return (
        f"地图助手这次没连上模型服务：{hint}。\n\n"
        "**地图不受影响**：底图、图层、时间轴、点查都能正常用。\n\n"
        "可以稍后重试，或在「设置 → Agent 配置」里换一个模型 / 换成「演示（无网）」。"
    )


def _prompt_token_budget() -> int:
    """单次请求的提示词 token 上限。

    Env: ``BACKEND_AGENT_MAX_PROMPT_TOKENS``（默认 20000；<=0 表示不限制）。
    用途：面向公众开放时，拦下超长提问/超长上下文，避免消耗项目额度。
    """
    raw = os.getenv("BACKEND_AGENT_MAX_PROMPT_TOKENS", "20000")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 20000
    return 0 if value <= 0 else max(1000, value)


def _estimate_prompt_tokens(
    *,
    system: str,
    history: list[dict[str, Any]],
    message: str,
    tools: list[dict[str, Any]] | None,
) -> int:
    """估算一次请求的输入 token（系统提示 + 历史 + 本次提问 + 工具定义）。

    工具 schema 占了每问约 2100~2300 token，必须算进来，否则拦截会失准。
    """
    total = estimate_tokens(system or "")
    total += estimate_tokens(message or "")
    for item in history or []:
        if isinstance(item, dict):
            total += estimate_tokens(str(item.get("content") or ""))
    if tools:
        try:
            total += estimate_tokens(json.dumps(tools, ensure_ascii=False))
        except (TypeError, ValueError):
            pass
    return total


def _estimate_messages_tokens(
    *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
) -> int:
    """估算多轮 messages（含工具结果）的总输入 token，用于工具跳二次守卫。"""
    total = estimate_tokens(system or "")
    for item in messages or []:
        try:
            total += estimate_tokens(json.dumps(item, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            continue
    if tools:
        try:
            total += estimate_tokens(json.dumps(tools, ensure_ascii=False))
        except (TypeError, ValueError):
            pass
    return total


class _EventSteps(list):
    """Step list that emits SSE ``step`` events on append (Phase D)."""

    def __init__(self, emit: EventCallback | None = None) -> None:
        super().__init__()
        self._emit = emit

    def append(self, step: Any) -> None:  # type: ignore[override]
        super().append(step)
        if self._emit and isinstance(step, dict):
            _emit_safe(self._emit, "step", dict(step))


def _emit_safe(emit: EventCallback | None, kind: str, data: dict[str, Any]) -> None:
    if not emit:
        return
    try:
        emit(kind, data)
    except Exception:
        logger.exception("agent on_event(%s) failed", kind)


def _token_chunks(text: str, *, size: int = 12) -> list[str]:
    t = text or ""
    if not t:
        return []
    return [t[i : i + size] for i in range(0, len(t), size)]


def _emit_stream_tail(
    emit: EventCallback | None,
    *,
    reply: str,
    ui_intents: list[Any],
) -> None:
    """Pseudo-stream reply tokens + intent events for SSE consumers."""
    if not emit:
        return
    for chunk in _token_chunks(reply):
        _emit_safe(emit, "token", {"text": chunk})
    for intent in ui_intents:
        if isinstance(intent, dict):
            _emit_safe(emit, "intent", dict(intent))


_EMPTY_REPLY_MARKERS = frozenset({"", "（模型未返回文本）"})


def _is_list_active_layers_query(message: str) -> bool:
    import re

    return bool(
        re.search(r"哪些.*(图层|层)|活动图层|当前图层|list.*layer", message or "", re.I)
    )


def _is_catalog_search_query(message: str) -> bool:
    """True when the user asks to search the layer library (not list active layers)."""
    text = message or ""
    if _is_list_active_layers_query(text):
        return False
    lower = text.casefold()
    if any(k in text for k in ("搜索图层", "查找图层", "搜图层")):
        return True
    if "search layer" in lower or "search layers" in lower:
        return True
    if ("搜索" in text or "查找" in text) and ("图层" in text or "图库" in text):
        return True
    if "search" in lower and ("layer" in lower or "图层" in text):
        return True
    return False


def _reply_needs_tool_synthesis(reply: str) -> bool:
    return (reply or "").strip() in _EMPTY_REPLY_MARKERS


def _synthesize_reply_from_tool_steps(steps: list[dict[str, Any]]) -> str | None:
    """Turn the latest useful tool_result into user-visible Chinese text.

    Models often call search_layers / sample tools and return empty ``content``;
    without this, the UI only shows a blank bubble or a collapsed「过程」panel.

    文案铁律（用户 2026-10-21 反馈「风云卫星反演（id：123456677）」看不懂）：
    正文只写中文显示名，**不拼 internal id，不糊 JSON**。id 留在 ``steps`` 里。
    """
    for step in reversed(steps):
        if not isinstance(step, dict) or step.get("type") != "tool_result":
            continue
        detail = step.get("detail")
        data: Any = None
        if isinstance(detail, dict):
            data = detail
        elif isinstance(detail, str) and detail.strip().startswith("{"):
            try:
                data = json.loads(detail)
            except json.JSONDecodeError:
                continue
        if not isinstance(data, dict):
            continue
        if not data.get("ok"):
            err = _friendly_tool_error(str(data.get("error") or ""))
            if err:
                return err
            continue
        layers = data.get("layers")
        if isinstance(layers, list):
            q = str(data.get("query") or "").strip()
            if not layers:
                hint = f"「{q}」" if q else "该关键词"
                return (
                    f"未在图层库中找到与{hint}匹配的图层。"
                    "若要查看地图上已添加的图层，请说「有哪些活动图层」。"
                )
            lines: list[str] = []
            for item in layers[:10]:
                if not isinstance(item, dict):
                    continue
                cid = str(item.get("layer_id") or item.get("catalog_id") or "").strip()
                fallback = str(item.get("display_name") or item.get("name") or "")
                label = human_layer_name(cid, None, default=fallback)
                if label not in lines:
                    lines.append(label)
            if not lines:
                continue
            head = (
                f"图层库里与「{q}」相关的有 {len(lines)} 个："
                if q
                else f"找到 {len(lines)} 个图层："
            )
            return head + "\n" + "\n".join(f"- {name}" for name in lines)
        samples = data.get("samples")
        if isinstance(samples, list) and samples:
            lines = []
            for s in samples[:8]:
                if not isinstance(s, dict):
                    continue
                cid = str(s.get("catalog_id") or "").strip()
                fallback = str(s.get("display_name") or "")
                label = human_layer_name(cid, None, default=fallback)
                if not s.get("ok"):
                    reason = _friendly_tool_error(str(s.get("error") or ""))
                    lines.append(f"- {label}：{reason or '这个点取不到值'}")
                    continue
                val_txt = fmt_value(s.get("value"), s.get("unit"))
                when = str(s.get("time") or "").strip()
                quality = str(s.get("quality_label") or "").strip()
                tail = " · ".join(x for x in (when, quality) if x)
                lines.append(f"- {label}：{val_txt}" + (f"（{tail}）" if tail else ""))
            if lines:
                coord = (
                    f"（{fmt_value(data.get('lng'))}, {fmt_value(data.get('lat'))}）"
                )
                return f"该点{coord}的取值：\n" + "\n".join(lines)
        layer_meta = data.get("layer")
        if isinstance(layer_meta, dict) and layer_meta.get("layer_id"):
            return _describe_layer_meta(layer_meta)
    return None


def _friendly_tool_error(raw: str) -> str:
    """把工具返回的英文/技术错误翻成用户看得懂的一句话。"""
    text = (raw or "").strip()
    if not text:
        return ""
    lowered = text.casefold()
    if "无权" in text or "permission" in lowered or "forbidden" in lowered:
        return "当前账号没有这个图层的查看权限"
    if "未找到" in text or "not found" in lowered:
        return "找不到这个图层，可能已下线或名称有误"
    if "nodata" in lowered or "缺测" in text:
        return "该位置没有有效数据（缺测）"
    if "timeout" in lowered or "超时" in text:
        return "数据服务响应超时，稍后再试"
    return text[:80]


def _describe_layer_meta(layer_meta: dict[str, Any]) -> str:
    """图层详情的人话版：名称、用途、时间覆盖、空间范围，不塞原始 JSON。"""
    lid = str(layer_meta.get("layer_id") or "").strip()
    name = human_layer_name(
        lid, None, default=str(layer_meta.get("display_name") or "")
    )
    parts: list[str] = [f"「{name}」"]
    desc = str(layer_meta.get("description") or "").strip()
    if desc:
        parts.append(desc[:200].rstrip("。") + "。")
    coverage = str(layer_meta.get("temporal_coverage") or "").strip()
    if coverage:
        parts.append(f"时间覆盖：{coverage}。")
    elif layer_meta.get("is_realtime"):
        parts.append("该图层为实时数据。")
    extent = layer_meta.get("extent")
    if isinstance(extent, dict):
        try:
            parts.append(
                "空间范围：经度 {:.2f}~{:.2f}、纬度 {:.2f}~{:.2f}。".format(
                    float(extent["west"]),
                    float(extent["east"]),
                    float(extent["south"]),
                    float(extent["north"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            pass
    summary = str(layer_meta.get("run_readiness_summary") or "").strip()
    if summary:
        parts.append(summary[:200])
    return "".join(parts)


def _ensure_visible_reply(
    reply: str, steps: list[dict[str, Any]], *, fallback: str = "（模型未返回文本）"
) -> str:
    if not _reply_needs_tool_synthesis(reply):
        return reply
    synthesized = _synthesize_reply_from_tool_steps(steps)
    if synthesized:
        return synthesized
    return reply.strip() or fallback


_kits_lock = threading.Lock()
_prompt_cache: tuple[float | None, str] | None = None
_ui_intents_cache: tuple[float | None, list[dict[str, Any]]] | None = None


def _kits_root() -> Path:
    return Path(__file__).resolve().parents[4] / "agentKits"


def _file_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime if path.is_file() else None
    except OSError:
        return None


def load_system_prompt() -> str:
    global _prompt_cache
    path = _kits_root() / "prompts" / "system.md"
    mtime = _file_mtime(path)
    with _kits_lock:
        if (
            _prompt_cache is not None
            and _prompt_cache[0] == mtime
            and mtime is not None
        ):
            return _prompt_cache[1]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = (
                "You are CGDA map companion. Reply in Chinese. "
                "Use tools for layer visibility/opacity/fit and search_layers when appropriate."
            )
            mtime = None
        _prompt_cache = (mtime, text)
        return text


def load_ui_intent_tools_openai() -> list[dict[str, Any]]:
    global _ui_intents_cache
    path = _kits_root() / "tools" / "ui_intents.json"
    mtime = _file_mtime(path)
    with _kits_lock:
        if (
            _ui_intents_cache is not None
            and _ui_intents_cache[0] == mtime
            and mtime is not None
        ):
            return [dict(t) for t in _ui_intents_cache[1]]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _ui_intents_cache = (mtime, [])
            return []
        intents = data.get("intents") if isinstance(data, dict) else None
        if not isinstance(intents, list):
            _ui_intents_cache = (mtime, [])
            return []
        tools: list[dict[str, Any]] = []
        for item in intents:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name not in _ALLOWED_INTENTS:
                continue
            tools.append(
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
        _ui_intents_cache = (mtime, tools)
        return [dict(t) for t in tools]


def load_ui_intent_tools_anthropic() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in load_ui_intent_tools_openai():
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


def _all_tools_openai() -> list[dict[str, Any]]:
    return load_ui_intent_tools_openai() + load_server_tools_openai()


def _all_tools_anthropic() -> list[dict[str, Any]]:
    return load_ui_intent_tools_anthropic() + load_server_tools_anthropic()


def sanitize_client_context(
    client_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Whitelist keys and bound size before prompt injection (W-5)."""
    if not client_context or not isinstance(client_context, dict):
        return None
    cleaned: dict[str, Any] = {}
    if "active_catalog_ids" in client_context:
        ids = client_context.get("active_catalog_ids")
        if isinstance(ids, list):
            cleaned["active_catalog_ids"] = [
                str(x)[:128] for x in ids[:_CLIENT_CONTEXT_MAX_LAYERS] if x is not None
            ]
    if "active_layers" in client_context:
        layers = client_context.get("active_layers")
        if isinstance(layers, list):
            slim: list[dict[str, Any]] = []
            for item in layers[:_CLIENT_CONTEXT_MAX_LAYERS]:
                if not isinstance(item, dict):
                    continue
                entry: dict[str, Any] = {}
                # overlay_layer_id 必留：运行时栅格（imported-*）点查只能靠它，
                # 旧白名单把它砍掉，导致点查一直拿不到 overlay 图层。
                for key in ("catalog_id", "instance_id", "name", "overlay_layer_id"):
                    if key in item and item[key] is not None:
                        entry[key] = str(item[key])[:256]
                # R04/R05：可见 / 选中必须保留原生 bool（str(True) 会变 "True"，
                # 模型读到字符串会判断失误）。
                for key in ("visible", "selected"):
                    if key in item and item[key] is not None:
                        entry[key] = bool(item[key])
                if entry:
                    slim.append(entry)
            cleaned["active_layers"] = slim
    # R04/R05：地图是否就绪 —— 决定助手能不能描述画面内容
    if "map_ready" in client_context:
        cleaned["map_ready"] = bool(client_context.get("map_ready"))
    if "map_error" in client_context:
        err = str(client_context.get("map_error") or "").strip()[:200]
        if err:
            cleaned["map_error"] = err
    if "map_point" in client_context:
        mp = client_context.get("map_point")
        if isinstance(mp, dict):
            lng_v: float | None = None
            lat_v: float | None = None
            try:
                lng_v = float(mp.get("lng", mp.get("lon", mp.get("longitude"))))
                lat_v = float(mp.get("lat", mp.get("latitude")))
            except (TypeError, ValueError):
                pass
            if (
                lng_v is not None
                and lat_v is not None
                and -180.0 <= lng_v <= 180.0
                and -90.0 <= lat_v <= 90.0
            ):
                cleaned["map_point"] = {
                    "lng": round(lng_v, 6),
                    "lat": round(lat_v, 6),
                }
    if "basemap_id" in client_context:
        bid = str(client_context.get("basemap_id") or "").strip()[:64]
        if bid:
            cleaned["basemap_id"] = bid
    if "timeline" in client_context:
        tl = client_context.get("timeline")
        if isinstance(tl, dict):
            slim_tl: dict[str, Any] = {}
            if "hour" in tl:
                try:
                    hour = int(tl["hour"])
                    if 0 <= hour <= 23:
                        slim_tl["hour"] = hour
                except (TypeError, ValueError):
                    pass
            if "date" in tl:
                date_s = str(tl.get("date") or "").strip()[:32]
                if date_s:
                    slim_tl["date"] = date_s
            if "playing" in tl:
                slim_tl["playing"] = bool(tl.get("playing"))
            rng = tl.get("data_range")
            if isinstance(rng, dict):
                # 当前图层的可用时间范围，用于「切到某天有没有数据」的校验。
                slim_rng: dict[str, Any] = {}
                for key in ("start", "end"):
                    val = str(rng.get(key) or "").strip()[:32]
                    if val:
                        slim_rng[key] = val
                frames = rng.get("frames")
                if isinstance(frames, int) and 0 < frames <= 100000:
                    slim_rng["frames"] = frames
                if slim_rng.get("start") and slim_rng.get("end"):
                    slim_tl["data_range"] = slim_rng
            if slim_tl:
                cleaned["timeline"] = slim_tl
    if "viewport" in client_context:
        vp = client_context.get("viewport")
        if isinstance(vp, dict):
            slim_vp: dict[str, Any] = {}
            for key in ("zoom",):
                if key in vp:
                    try:
                        slim_vp[key] = round(float(vp[key]), 4)
                    except (TypeError, ValueError):
                        pass
            center = vp.get("center")
            if isinstance(center, (list, tuple)) and len(center) >= 2:
                try:
                    lng_c = float(center[0])
                    lat_c = float(center[1])
                    if -180.0 <= lng_c <= 180.0 and -90.0 <= lat_c <= 90.0:
                        slim_vp["center"] = [round(lng_c, 6), round(lat_c, 6)]
                except (TypeError, ValueError):
                    pass
            bbox = vp.get("bbox")
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                try:
                    coords = [round(float(x), 6) for x in bbox[:4]]
                    slim_vp["bbox"] = coords
                except (TypeError, ValueError):
                    pass
            if slim_vp:
                cleaned["viewport"] = slim_vp
    if not cleaned:
        return None
    try:
        blob = json.dumps(cleaned, ensure_ascii=False)
    except (TypeError, ValueError):
        return None
    if len(blob) > _CLIENT_CONTEXT_MAX_CHARS:
        while (
            len(blob) > _CLIENT_CONTEXT_MAX_CHARS
            and isinstance(cleaned.get("active_layers"), list)
            and cleaned["active_layers"]
        ):
            cleaned["active_layers"].pop()
            blob = json.dumps(cleaned, ensure_ascii=False)
        if len(blob) > _CLIENT_CONTEXT_MAX_CHARS and isinstance(
            cleaned.get("active_catalog_ids"), list
        ):
            while (
                len(blob) > _CLIENT_CONTEXT_MAX_CHARS and cleaned["active_catalog_ids"]
            ):
                cleaned["active_catalog_ids"].pop()
                blob = json.dumps(cleaned, ensure_ascii=False)
    return cleaned


def _build_system(
    client_context: dict[str, Any] | None,
    *,
    cred: Any,
) -> str:
    system = load_system_prompt()
    parts: list[str] = [system]
    safe_ctx = sanitize_client_context(client_context)
    if safe_ctx:
        try:
            blob = json.dumps(safe_ctx, ensure_ascii=False)[:_CLIENT_CONTEXT_MAX_CHARS]
            parts.append(f"## Current client_context\n```json\n{blob}\n```")
        except (TypeError, ValueError):
            pass
    try:
        # 只放前 14 条做「目录里大概有什么」的提示：完整清单靠 search_layers。
        # 原来 40 条截 3000 字符要 843 token，是系统词里最贵又最不精确的一块。
        summary = catalog_summary(cred=cred, limit=14)
        if summary:
            blob = json.dumps(summary, ensure_ascii=False)[:1100]
            parts.append(f"## Catalog sample (accessible layers)\n```json\n{blob}\n```")
    except Exception:
        logger.exception("catalog_summary failed")
    parts.append(
        "## Tools\n"
        "- UI intents (client-executed): set_layer_visibility, set_layer_opacity, "
        "fit_layer, list_active_layers, fit_china, locate_coordinate, switch_basemap, "
        "set_timeline, set_timeline_playing, remove_layer, reorder_layer, set_layer_symbology\n"
        "- Server read tools (immediate): search_layers, list_workflows, get_layer_meta, "
        "get_workflow_meta, sample_layer_point, web_search, list_workflow_runs, "
        "get_workflow_run, get_layer_coverage, get_layer_statistics, "
        "list_workflow_timers (admin)\n"
        "- Server write: run_workflow (confirmation ticket — user must approve before submit; "
        "optional time_range + workflow_variant=online)\n"
        "- Prefer client_context.timeline / viewport / basemap_id for current map clock and view\n"
        "- Prefer get_layer_meta / get_workflow_meta for details; sample_layer_point for "
        "map coordinates + layer values (use client_context.map_point when user selected a point); "
        "web_search for public background knowledge only\n"
        "- Prefer fit_china for 中国全境/全国; locate_coordinate for explicit lng/lat or known cities; "
        "switch_basemap for 天地图影像/街道等底图切换; fit_layer only for a specific layer extent\n"
        "- Prefer search_layers before run_workflow; never claim a run was submitted "
        "until confirmation is approved\n"
        "## 选层优先级（先定层，再取数）\n"
        "- 用户说的卫星/产品名（SMAP、风云、L3、反演产品…）是**来源**，不是图层编号。"
        "按这个顺序裁决：① 本轮用户明确点名的层 > ② client_context 里 selected=true 的层 > "
        "③ visible=true 的层 > ④ 唯一可见层。\n"
        "- search_layers 的结果里 `on_page=true` 表示这一层正挂在用户页面上；"
        "`layer_kind=runtime_product`（运行产物）**优先于** `catalog_reference`（目录参考层）。"
        "用户没说清时，先按页面上的那一层回答，**不要跳到目录里的参考层**。\n"
        "- 同源同时存在「反演产品」与「L3 官方参考产品」两类时（search_layers 结果里 "
        "`product_class` 分别是 derived_product / reference_layer），**先反问一句**要哪一个，"
        "不许自己挑。选定后回答里用用户看到的名字，不要念编号。\n"
        "## 页面状态问答（必须逐项回答）\n"
        "- 被问到“现在显示的是什么/选中哪个/什么日期/哪颗卫星/地图好了吗”这类状态问题时，"
        "**必须基于 client_context 逐项回答**：已加载图层数、**可见**图层（visible=true）、"
        "**选中**图层（selected=true）、时间轴日期（timeline.date/hour）、图层来源"
        "（风云卫星 / SMAP / 地面站点 等，用 source_label）、地图是否就绪（map_ready）。"
        "**不得只答“已加载 N 层”就结束**；每项一行，简短，不展开解释。\n"
        "- 若 map_ready 为 false：必须明确说“地图尚未就绪/加载失败”（可带 map_error 的原因），"
        "**不得描述画面内容、不得假装看得到图层**。\n"
        "- 若 active_layers 里没有 visible=true 的图层，如实说“当前没有勾选显示的图层”，"
        "不要拿已加载图层冒充可见图层。\n"
        "## 只读查询不得改视图\n"
        "- 用户只是问“多少 / 有没有 / 是什么 / 哪个 / 怎么样”这类只读问题时，"
        "**只准调用只读工具**，**不得下发任何改变画面的 UI 意图**："
        "set_timeline、set_timeline_playing、set_layer_visibility、set_layer_opacity、"
        "set_layer_symbology、fit_layer、fit_china、locate_coordinate、switch_basemap、"
        "remove_layer、reorder_layer 一律不要碰；"
        "也**不得**为了让数值“看起来对”而先切日期再取数。\n"
        "- 只有用户明确要求“切到某天 / 显示出来 / 调透明 / 定位到某地 / 换底图”时，"
        "才下发对应的视图意图。判别标准只有一条：**用户要不要画面跟着变。**\n"
        "- 用户问的日期与时间轴当前日期不一致时，口头说明“当前时间轴停在 X，"
        "你问的是 Y，我按 Y 取数、没有动你的时间轴”，**不要顺手把时间轴切过去**。\n"
        "## 来源与单位\n"
        "- 来源只认工具/目录返回的 source_label（SMAP / 风云卫星 / 地面站点 / 多源融合 / 未标注来源），"
        "**不要用图层名字去猜卫星**，也不要自己编造。返回 unknown 时如实说“未标注来源”。\n"
        "- 单位只认 unit_label：土壤水分为 m³/m³，VOD 与等效散射 ω 为“无量纲”。"
        '**不要把 SM / VOD / OMEGA 当单位念出来**；无量纲时 unit 字段是字符 "1"，'
        "回答请说“无量纲”，不要说“单位是 1”。\n"
        "## 覆盖口径\n"
        "- 回答“某天有没有数据”必须用 get_layer_coverage 返回的 resolved.status "
        "（available / unavailable / unknown）和 resolved.reason，"
        "**不要直接念 local.count=0 就说没数据**。\n"
        "- get_layer_coverage 顶层的 **actual_time 才是权威命中**："
        "hit_source=ondemand_frame 表示这天是按需补帧拿到的独立单日帧"
        "（此时 is_daily_frame=true，**可以说“这就是当天的独立观测”**）；"
        "hit_source=block 才是落在某个时间块内。"
        "**resolved.actual_time 只是 time_list 里的块，不许拿它压过顶层 actual_time**——"
        "否则会把补帧单日说成“不是当天独立观测”，与统计结果自相矛盾。\n"
        "- 该日确实没有数据时，只说“该日没有数据”。若用户要替代日期，**只能从 "
        "available_dates 的 before / after（或 time_blocks）里原样挑**，并注明"
        "“这是该图层实际有的日期”；**禁止自己推断、凑整或编造日期**"
        "（例如凭空说“建议改查 12 月 15 日”）。\n"
        "- resolved.reason 说明“该日期落在某个时间块内”时，要如实告诉用户"
        "“这几天取的是同一块的值，所以数值相同是正常的”，**不得说成日期切换失效**。\n"
        "## 点查口径\n"
        "- sample_layer_point 返回的每条样值都带 requested_time（用户请求的日期）与 "
        "actual_time / period_start ~ period_end（实际命中的数据时间块）。"
        "**逐条按它自己的时间块说明**，不要拿第一个图层的区间套到其它图层上——"
        "风云与 SMAP 的时间块通常并不相同。\n"
        "- 请求日期不在 period_start ~ period_end 内（或 is_single_block=true）时，"
        "要说明“该产品这一版是整段合成，没有这一天的独立观测，取到的是整块数据”，"
        "**不得把请求日期当成实际观测日**。\n"
        "- get_layer_meta 的 native_step 只是「原始步长声明」，**不能据此回答"
        "“每日 1 帧 / 每 8 天 1 帧”**。要看同一次返回里的 is_single_block、"
        "time_span_days、temporal_summary：只有一片且跨多天时，必须说"
        "“单幅时间块（跨 N 天，非逐日）”，与 temporal_summary 的措辞保持一致。\n"
        "- get_layer_meta 的 temporal_coverage 只是描述符**声明值**；一旦 "
        "coverage_conflict=true，必须以 actual_temporal_coverage 为准，"
        "回答里不许念声明里的日期，也不许说“该图层覆盖某年某月”。\n"
        "## 取数对象自证（所有带数值/清单的回答通用）\n"
        "- **第一句照抄工具返回里的 `answer_lead`**（形如“我按「SMAP 动态散射约束产品 · "
        "土壤水分」取数”）。它只含层名、**不含编号**；照抄即可，不要自己往里加 id。"
        "**正文一律不写 `imported-` / `catalog_id` / 任何内部编号**，层名在同一段回答里"
        "只写一次，不要每句都“我按「X」取数”。\n"
        "**唯一例外**：用户明确问“catalog_id 是多少 / 哪一份是正规产物 / 有没有旧副本”时，"
        "才写出编号；其余一律只说层名。\n"
        "- 编号的作用在**你内部核对是哪一层**（返回里的 `catalog_id`），不是写给用户看的。"
        "层名已能区分动态层与平均层，所以用户看名字就能判断你有没有换层。\n"
        "- **返回里的字段名、代号、参数一律只给你自己判断用，正文必须译成人话。"
        "回答的详略按内容需要，该说的都要说（覆盖范围、块起止、口径、像元数、"
        "为什么取不到某天），不要为了短把该讲的删掉；只是不要出现内部黑话。**"
        "对照：\n"
        "  · `value_basis.kind=block` → 说“这是 2025-12-11 至 12-18 的跨天合成值”；"
        "不要说“value_basis=block / 命中的是块键 20251211_20251218”。\n"
        "  · `ondemand_frame` → 说“这天有按需补出的单日观测”；不要说“ondemand 帧”。\n"
        "  · `temporal_shape=hybrid` → 说“时间清单里只有多日块，但已按需补出 N 个单日帧”；"
        "不要念 `hybrid`。\n"
        "  · `is_stale_copy` / `sibling_copies` 一律不出现，旧副本这件事**直接照抄 "
        "`copy_status`** 那句话（“这一层是正规产物，同源另有一份较早的副本”/"
        "“这一层是旧副本，同源还有一份更完整的正规产物”）。\n"
        "  · `hit_source` / `temporal_summary` / `actual_time_blocks` / "
        "`daily_frame_count` / `ondemand_frame_count` 等字段名**一律不出现**。\n"
        "  · 日期键 `20251211_20251218` / `20260101` 写成“2025-12-11 至 12-18”/"
        "“2026-01-01”，不要把下划线原样贴出来。\n"
        "- **没有工具返回，就没有数字。** `ok=false` / `error` / "
        "`value_basis.kind=none` / 该日期既不在时间清单也没有按需补出的单日帧时，"
        "只能转述失败原因（例如“该图层没有 2025-12-15 的单日帧，最近的是 "
        "2025-12-11 至 12-18 这一段”），**严禁给任何数值**，**严禁**改用别的层、别的日期或"
        "自己算一个数顶上——那属于编造数据，比答不出来严重得多。\n"
        "- 用户说“**页面上那个 X 层**”时，按名从 client_context 的已添加图层里找 X，"
        "**不许用 selected=true 的那层顶替**（他勾的常常就是另一个产品）；"
        "找不到就说“已添加图层里没有叫 X 的层”，并列出可选层名。\n"
        "- 用户说“这是这一层 / 它 / 这个产品”时，**沿用上一轮你回答里写过的那个层名**"
        "（产品族 + 变量已足够唯一，例如「SMAP 动态散射约束产品 · 土壤水分」），"
        "不许因为页面勾选变了就悄悄换层；要换必须说明“这次改用 X 层”。\n"
        "- **但用户点名的变量与本层不同时，必须换层，不许拿“这层没有该变量”挡回去。**"
        "同一产品族把土壤水分 / 植被光学厚度 / 等效散射 ω 拆成了三个独立图层："
        "用户说“这个产品的植被光学厚度”而当前是土壤水分层，属于**同一产品族换变量**，"
        "正确做法是 `search_layers` 用「产品族名 + 变量名」找回同族那一层，拿到 "
        "`overlay_layer_id` 后**显式传 catalog_id** 再取数，回答里写新层名。"
        "（2026-10-29 实测：模型回答“这一层是土壤水分产品，本身不含植被光学厚度”就结束，"
        "还反问用户要哪一层——这属于该查没查。）\n"
        "- 报“时间清单几片 / 已补几天”这类结构性问题，数字只能取自**同一层的同一次"
        "返回**，**不许把两次不同图层的数字拼进一句话**；并且必须**点名单日帧的具体"
        "日期**，只报个数用户没法核对。日期来源写死：自带单日帧看 `daily_frame_dates`，"
        "按需补出的看 `ondemand_dates`——**不许自己猜**（2026-10-29 实测：只给个数时"
        "模型把补帧日期 2025-12-15 说成了“自带的那 1 个单日帧”，而自带的是 2026-01-01）。"
        "`ondemand_out_of_span` 里的日期在**本层时间范围之外**（多为历史遗留测试帧），"
        "默认不提；用户专门问才说，并注明它们不在本层覆盖期内。\n"
        "- 返回里带 `copy_status` 说明盘上有新旧两个目录（时间清单与补帧天数都不同）；"
        "`copy_status` 以“这一层是旧副本”开头时必须先声明“这一层是旧副本，正规产物是"
        "同源的另一个”，再回答，且**只许用同一个层的数字**。"
        "这话只在用户问起时讲，平时不要主动提副本；提副本时也**不报对方的编号**，"
        "只说“另有一份较早/更完整的同源产物”即可。\n"
        "## 整层统计（只读）\n"
        "- **用户问“某变量在某天/某块是多少”但没说地点时，默认就是整幅栅格统计**，"
        "直接调 get_layer_statistics（不传 bbox），报 mean 与有效像元数；"
        "**严禁反问“请给经纬度 / 请先在地图上选一个点”**——选择点属于 "
        "sample_layer_point，只有用户明确给出经纬度、或说“图上这一点/这个位置/我点的这里”"
        "时才用它。用户问“是多少”就是要一个数，不是要你教他怎么选点。\n"
        "- 要「整层/全图平均、有效像元数、最大最小值」→ 直接调 get_layer_statistics"
        "（传 catalog_id + 可选 time），不要用 sample_layer_point 的点值冒充全图均值。"
        "这句话里带统计动词（平均/均值/统计/像元数/最大/最小）时，必须以统计结果或"
        "明确失败原因结尾，不能只列图层、也不能只说“打算怎么算”。\n"
        "- 统计对象：用户没点名就用 selected=true 那层，其次唯一可见层；"
        "多个候选且没指明才反问。\n"
        "- **点名了产品形态就以形态为准，不要用页面选中层**：说“动态/逐日/单日/某一天”"
        "只能用 `temporal_shape=daily_series` 或 `hybrid`；说“平均/月均/季均/整段”才用 "
        "`single_block` 或 `block_series`。两层 `variable_label` 相同（都叫土壤水分）时，"
        "唯一可区分依据是 `temporal_shape` 与 `product_family`（dynamic/average/raw）——"
        "先 search_layers 拿到 id，再显式传给 get_layer_statistics。\n"
        "- `is_product_group=true`（`layer_kind=product_group`）是**产品族**，不是栅格层、"
        "不能统计。**严禁**说“这一层是等效散射 ω”——族名里的“散射”只是产品名用词，"
        "`variable` 会是 unknown。念 `group_hint`，把 `group_members` 里的变量层列给用户挑，"
        "选定再统计。\n"
        "- `mixed`＝层内混装单日帧与多日块，引用“某一天”必须说明命中哪一片；"
        "`hybrid`＝time_list 只有多日块但已按需补出单日帧（`ondemand_frame_count`>0），"
        "此时“只能取块合成值”是错的，别拿 time_list 的形状否定单日取值。\n"
        "- **值出自哪种帧以 `value_basis.kind` 为准，严禁自行推理**：`ondemand_frame`＝"
        "按需补出的单日帧、`daily_frame`＝自带单日帧（这两者可说“当天的独立观测”）、"
        "`block`＝多日合成块（必须说“跨天合成值”并给块起止）。`value_basis.note` 可照抄。"
        "**kind=ondemand_frame 时严禁说成块值或整段平均**。\n"
        "- `layer_source=page` 表示用的是页面选中层，回答要点名是哪一层；"
        "出现 `layer_source_warning` 或 `page_candidates` 且形态不符时，必须从 "
        "`page_candidates` 里选形态匹配的那层、显式传 catalog_id 重算。\n"
        "- 时间口径以 `time_source` 为准（page/requested/layer_default）；`layer_default` "
        "时必须先说“本次用的是图层默认时间块，不是页面当前日期”。`period_start~period_end` "
        "是本次命中的那一片，`layer_span_*` 才是整层首尾，不得互换；`is_daily_frame=true` "
        "才能说“当天的独立观测”。\n"
        "- 回答必须说清：用户指定的日期（用户没指定就说“当前时间轴停在 X”，"
        "**不要说成“你请求的日期”**）、实际命中的时间块、统计范围是整幅栅格而非视口，"
        "并给出 mean、valid_pixels 与 unit_label。`extent` 是本次真正统计到的经纬度框，"
        "一并说明；只有用户明确指定区域才传 bbox。\n"
        "- 只有 `is_single_block=true` 且 `ondemand_frame_count` 为 0 才能说“只有一个时间块、"
        "不同日期取到同一块”；>0 时必须说“只有一个块，但已按需补出 N 个单日帧”。\n"
        "- 该工具只读：不建图层、不写产物、不跑工作流，不需要确认卡。\n"
        "## 问“这层是什么 / 它的 id / 有没有旧副本”（禁止用统计工具）\n"
        "- 这类问题只调 **get_layer_coverage**（或 search_layers），**禁止调 "
        "get_layer_statistics**——统计返回的是一堆数值，会把话题从“是哪一层”拖到"
        "“有多少”，2026-10-29 实测就因此把「SMAP 平均散射约束产品 · 土壤水分」答成了"
        "页面选中的风云那层数据。\n"
        "- 返回里的 `catalog_id` 就是答案；search_layers 与 get_layer_coverage 都带 "
        "`copy_status`，问“有没有同源旧副本”时直接照抄 `copy_status` 那句话答"
        "（它已含“这一层是正规产物/旧副本，同源另有一份…”的结论与片数、天数对比），"
        "**不要报同源另一份的 id**。\n"
        "- 用户明确问**这一层自己**的 id / 编号时，**允许在回答里写出 imported- 开头的 id**"
        "（这一条优先于“不要念编号”的通用要求）；但同源**另一份**的编号仍不主动报。\n"
    )
    return "\n\n".join(parts)


def _confirmation_from_tool_result(tres: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(tres, dict):
        return None
    if not tres.get("needs_confirmation"):
        return None
    cid = str(tres.get("confirmation_id") or "").strip()
    if not cid:
        return None
    return {
        "confirmation_id": cid,
        "action": "run_workflow",
        "expires_at": str(tres.get("expires_at") or ""),
        "summary": tres.get("summary") if isinstance(tres.get("summary"), dict) else {},
        "message": str(tres.get("message") or ""),
    }


def _normalize_intents(raw: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name not in _ALLOWED_INTENTS:
            continue
        args = item.get("args")
        if not isinstance(args, dict):
            args = item.get("input") if isinstance(item.get("input"), dict) else {}
        out.append({"name": name, "args": dict(args)})
    return out


def _parse_openai_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []
    out: list[dict[str, Any]] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name = str(fn.get("name") or "").strip()
        args_raw = fn.get("arguments")
        args: dict[str, Any] = {}
        if isinstance(args_raw, str):
            try:
                parsed = json.loads(args_raw)
                if isinstance(parsed, dict):
                    args = parsed
            except json.JSONDecodeError:
                args = {}
        elif isinstance(args_raw, dict):
            args = args_raw
        out.append(
            {
                "id": str(tc.get("id") or ""),
                "name": name,
                "args": args,
            }
        )
    return out


def _intents_from_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _normalize_intents(
        [{"name": c["name"], "args": c.get("args") or {}} for c in calls]
    )


def _server_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in calls if c.get("name") in _SERVER_TOOLS]


# 一轮里模型可能同时下发「界面意图」和「服务端工具」（例如
# “切到 X 图层、日期设为 Y，然后算均值”）。OpenAI / Anthropic 都要求
# 每个 tool_call 都有配对的 tool 结果，否则第二次请求整轮直接 400：
#   An assistant message with 'tool_calls' must be followed by tool messages
#   responding to each 'tool_call_id'.
# 所以界面意图也要回一条占位结果，不能只回服务端工具那几条。
_UI_TOOL_ACK = json.dumps(
    {"ok": True, "applied": "前端界面意图，由浏览器执行，服务端无需返回数据"},
    ensure_ascii=False,
)


def _sanitize_assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    """只保留 role/content/tool_calls。

    部分服务（如带 reasoning_content 的推理模型）会回带额外字段，
    原样回放可能被严格校验的服务端拒绝，这里做一次白名单裁剪。
    """
    out: dict[str, Any] = {"role": "assistant"}
    content = message.get("content")
    out["content"] = content if isinstance(content, str) else (content or "")
    calls = message.get("tool_calls")
    if isinstance(calls, list) and calls:
        out["tool_calls"] = calls
    return out


def _anthropic_tool_uses(content: Any) -> list[dict[str, Any]]:
    """取出一轮 content 里的全部 tool_use（界面意图与服务端工具都在内）。"""
    if not isinstance(content, list):
        return []
    out: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "") != "tool_use":
            continue
        out.append(
            {
                "id": str(block.get("id") or "tool"),
                "name": str(block.get("name") or ""),
                "args": block.get("input")
                if isinstance(block.get("input"), dict)
                else {},
            }
        )
    return out


def _intents_from_anthropic_content(
    content: Any,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    text_parts: list[str] = []
    ui_raw: list[dict[str, Any]] = []
    server_raw: list[dict[str, Any]] = []
    if isinstance(content, str):
        return content, [], []
    if not isinstance(content, list):
        return "", [], []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = str(block.get("type") or "")
        if btype == "text":
            text_parts.append(str(block.get("text") or ""))
        elif btype == "tool_use":
            name = str(block.get("name") or "")
            args = block.get("input") if isinstance(block.get("input"), dict) else {}
            entry = {
                "id": str(block.get("id") or ""),
                "name": name,
                "args": args,
            }
            if name in _ALLOWED_INTENTS:
                ui_raw.append(entry)
            else:
                server_raw.append(entry)
    return (
        "\n".join(text_parts).strip(),
        _normalize_intents(ui_raw),
        server_raw,
    )


def refresh_models_for_profile(
    profile: dict[str, Any],
    *,
    api_key_override: str | None = None,
) -> dict[str, Any]:
    protocol = str(profile.get("protocol") or "demo")
    if protocol == "demo":
        return {"models": ["demo-rules"], "manual": False}
    base_url = str(profile.get("base_url") or "").strip()
    if not base_url:
        return {"models": [], "manual": True, "error": "未配置 base_url"}
    api_key = (api_key_override or "").strip() or get_profile_api_key(profile)
    kind = str(profile.get("provider_kind") or "")
    try:
        if kind == "ollama":
            models = openai_compat.list_ollama_tags(base_url=base_url)
            if not models:
                models = openai_compat.list_models(
                    base_url=base_url, api_key=api_key or "ollama"
                )
            return {"models": models, "manual": False}
        if protocol == "anthropic":
            models = anthropic_compat.list_models(base_url=base_url, api_key=api_key)
            return {"models": models, "manual": len(models) == 0}
        models = openai_compat.list_models(base_url=base_url, api_key=api_key)
        return {"models": models, "manual": False}
    except LlmClientError as exc:
        return {"models": [], "manual": True, "error": str(exc)}
    except Exception as exc:
        logger.exception("refresh_models_for_profile failed")
        return {
            "models": [],
            "manual": True,
            "error": f"刷新模型列表失败：{exc}",
        }


_STATISTICS_WORDS = re.compile(r"平均|均值|统计|像元|mean|average|最大|最小", re.I)
# 产品族名自带「平均」二字（「SMAP 平均散射约束产品」），不剥掉的话
# 「这一层的 catalog_id 是多少」会被判成统计请求，进而被规则引擎覆盖成
# 「页面选中层的均值」。2026-10-29 实测第 4 问就是这么把正确答案吃掉的。
_LAYER_NAME_NOISE = re.compile(
    r"(?:动态|平均|月均|季均|逐日|daily|average|dynamic)?\s*散射约束产品|产品族",
    re.I,
)


def _wants_statistics(message: str) -> bool:
    """用户这句话是不是在要整层统计（报告第二轮 A06~A08 的判据）。"""
    text = _LAYER_NAME_NOISE.sub(" ", message or "")
    return bool(_STATISTICS_WORDS.search(text))


def _statistics_tool_called(steps: list[dict[str, Any]]) -> bool:
    """本轮是否真的调过取数类工具（统计 / 覆盖 / 元数据）。

    2026-10-29 补充：原先只认 get_layer_statistics，但身份类、时间口径类提问
    正确路径是 get_layer_coverage；它一被调用就说明模型确实在查这一层，
    此时规则引擎（只认页面选中层）不得介入。
    """
    _data_tools = ("get_layer_statistics", "get_layer_coverage", "get_layer_meta")
    for step in steps:
        if str(step.get("type") or "") != "tool":
            continue
        summary = str(step.get("summary") or "")
        if any(name in summary for name in _data_tools):
            return True
    return False


def _statistics_fallback_reply(
    message: str,
    reply: str,
    steps: "_EventSteps",
    sid: str,
    client_context: dict[str, Any] | None,
) -> str:
    """统计请求的确定性兜底：模型没调工具、也没给出数值时，用规则引擎补一次。

    报告第二轮 P1：「统计请求即使包含『当前图层』也不能只列图层或说明计划，
    核对来源、变量与日期后继续调用 get_layer_statistics，直到得到结果或明确报错」。
    真模型对「当前选中图层」这类模糊主语约束力弱，光靠系统提示不可靠；
    提示词已写死规则（## 整层统计），这里再加一道代码兜底。
    **只补文本，不下发任何改变视图的意图。**
    """
    if not _wants_statistics(message) or _statistics_tool_called(list(steps)):
        return reply
    if "均值" in reply:
        return reply
    # 模型已经给出了具体数值或取数声明，说明它确实取了数；此时用规则引擎
    # （只认页面选中层）覆盖，等于把正确答案换成另一层的数字。
    # 2026-10-29 实测：第 4 问被这样覆盖成「风云卫星平均层 0.1294/120257」。
    # 注意：回答正文已按规范不再写 imported- 编号，判据改用「数值 / 取数声明」。
    if "取数" in reply or re.search(r"\d+\.\d+", reply):
        return reply
    try:
        fallback = mock_chat(message, session_id=sid, client_context=client_context)
    except Exception:
        logger.debug("statistics fallback failed", exc_info=True)
        return reply
    text = str(fallback.get("reply") or "").strip()
    # 规则引擎的统计答复一定带「均值」；若它也只给了图层列表，说明目标选择没接上，
    # 保留模型原文（宁可少说，也不要替换成另一种不准确的答复）。
    if not text or "均值" not in text:
        return reply
    steps.append(
        {
            "type": "tool_result",
            "summary": "服务端补调整层统计（模型本轮未调用工具）",
            "detail": text[:800],
        }
    )
    return text


def _run_chat_impl(
    message: str,
    *,
    session_id: str | None = None,
    client_context: dict[str, Any] | None = None,
    user_id: int | None = None,
    cred: Any = None,
    on_event: EventCallback | None = None,
) -> dict[str, Any]:
    sid = (session_id or "").strip() or uuid.uuid4().hex
    profile = get_effective_profile_raw(user_id=user_id)
    if profile is None:
        raise ValueError("无可用 Agent 配置档")

    protocol = str(profile.get("protocol") or "demo")
    profile_id = str(profile.get("id") or "")
    provider_kind = str(profile.get("provider_kind") or protocol)
    ctx_in = int(profile.get("context_window_input") or 4000)
    max_chars = max(500, min(4000, ctx_in * 2))
    if len(message) > max_chars:
        raise ValueError(f"消息过长（上限约 {max_chars} 字符，受配置档上下文窗口限制）")

    history = load_history(user_id=user_id, session_id=sid)
    # R06 排查指标：模型为什么没给出好回复，靠这三个值定位
    # （finish_reason 取自 choices[0]，不在 message 对象上）
    finish_reason = ""
    tool_calls_done = 0
    hops_used = 0
    steps: list[dict[str, Any]] = _EventSteps(on_event)
    steps.append(
        {
            "type": "thought",
            "summary": "已接受请求，开始处理…",
            "detail": f"protocol={protocol}",
        }
    )
    client_context = sanitize_client_context(client_context)

    if protocol == "demo":
        steps.append(
            {
                "type": "thought",
                "summary": "演示规则匹配",
                "detail": "使用关键词启发式生成 UI intents",
            }
        )
        # Optional: search_layers only for explicit catalog search (not「有哪些活动图层」)
        if _is_catalog_search_query(message):
            q = message
            for prefix in ("搜索图层", "查找图层", "搜图层", "搜索", "查找", "search"):
                if message.casefold().startswith(prefix.casefold()):
                    q = message[len(prefix) :].strip() or message
                    break
            steps.append(
                {
                    "type": "tool",
                    "summary": f"search_layers({q[:40]})",
                }
            )
            tool_res = execute_server_tool(
                "search_layers",
                {"query": q, "limit": 8},
                cred=cred,
                client_context=client_context,
            )
            steps.append(
                {
                    "type": "tool_result",
                    "summary": f"命中 {tool_res.get('count', 0)} 条",
                    "detail": json.dumps(tool_res, ensure_ascii=False)[:800],
                }
            )

        confirmations: list[dict[str, Any]] = []
        # Demo heuristic: propose run_workflow confirmation when user asks to run.
        if any(
            k in message
            for k in (
                "运行工作流",
                "跑工作流",
                "提交工作流",
                "run workflow",
                "执行工作流",
            )
        ):
            catalog_guess = ""
            ctx_ids: list[str] = []
            if isinstance(client_context, dict):
                raw_ids = client_context.get("active_catalog_ids")
                if isinstance(raw_ids, list):
                    ctx_ids = [str(x) for x in raw_ids if x]
                if not ctx_ids:
                    raw_layers = client_context.get("active_layers")
                    if isinstance(raw_layers, list):
                        for layer in raw_layers:
                            if isinstance(layer, dict) and layer.get("catalog_id"):
                                ctx_ids.append(str(layer["catalog_id"]))
            if ctx_ids:
                catalog_guess = ctx_ids[0]
            if catalog_guess:
                steps.append(
                    {
                        "type": "tool",
                        "summary": f"run_workflow({catalog_guess})",
                    }
                )
                wf_res = execute_server_tool(
                    "run_workflow",
                    {"catalog_id": catalog_guess},
                    cred=cred,
                    client_context=client_context,
                )
                steps.append(
                    {
                        "type": "tool_result",
                        "summary": "待确认"
                        if wf_res.get("needs_confirmation")
                        else "工具返回",
                        "detail": json.dumps(wf_res, ensure_ascii=False)[:800],
                    }
                )
                conf = _confirmation_from_tool_result(wf_res)
                if conf:
                    confirmations.append(conf)

        # Demo: sample map point / layer values
        if any(
            k in message
            for k in (
                "点值",
                "采样",
                "坐标",
                "这个点",
                "查数值",
                "sample",
                "point value",
            )
        ):
            steps.append({"type": "tool", "summary": "sample_layer_point"})
            sample_res = execute_server_tool(
                "sample_layer_point",
                {},
                cred=cred,
                client_context=client_context,
            )
            steps.append(
                {
                    "type": "tool_result",
                    "summary": f"采样 {sample_res.get('count', 0)} 层"
                    if sample_res.get("ok")
                    else "采样失败",
                    "detail": json.dumps(sample_res, ensure_ascii=False)[:800],
                }
            )

        # Demo: layer / workflow detail
        if any(
            k in message for k in ("图层详情", "图层信息", "layer detail", "layer meta")
        ):
            catalog_guess = ""
            if isinstance(client_context, dict):
                raw_ids = client_context.get("active_catalog_ids")
                if isinstance(raw_ids, list) and raw_ids:
                    catalog_guess = str(raw_ids[0])
            if catalog_guess:
                steps.append(
                    {"type": "tool", "summary": f"get_layer_meta({catalog_guess})"}
                )
                lm = execute_server_tool(
                    "get_layer_meta",
                    {"catalog_id": catalog_guess},
                    cred=cred,
                    client_context=client_context,
                )
                steps.append(
                    {
                        "type": "tool_result",
                        "summary": "图层元数据" if lm.get("ok") else "图层元数据失败",
                        "detail": json.dumps(lm, ensure_ascii=False)[:800],
                    }
                )

        # Demo: workflow detail
        if any(k in message for k in ("工作流详情", "工作流信息", "workflow detail")):
            steps.append({"type": "tool", "summary": "list_workflows"})
            lw = execute_server_tool(
                "list_workflows",
                {"limit": 5},
                cred=cred,
                client_context=client_context,
            )
            steps.append(
                {
                    "type": "tool_result",
                    "summary": f"工作流 {lw.get('count', 0)} 条",
                    "detail": json.dumps(lw, ensure_ascii=False)[:800],
                }
            )
            # If user mentions a specific id-like token, try get_workflow_meta
            wid_guess = ""
            for token in message.replace("，", " ").replace(",", " ").split():
                t = token.strip()
                if t and ("_" in t or t.startswith("wf") or t.endswith("_workflow")):
                    wid_guess = t[:128]
                    break
            if not wid_guess and isinstance(lw, dict):
                wfs = lw.get("workflows")
                if isinstance(wfs, list) and wfs and isinstance(wfs[0], dict):
                    wid_guess = str(wfs[0].get("workflow_id") or "")
            if wid_guess:
                steps.append(
                    {"type": "tool", "summary": f"get_workflow_meta({wid_guess})"}
                )
                wm = execute_server_tool(
                    "get_workflow_meta",
                    {"workflow_id": wid_guess},
                    cred=cred,
                    client_context=client_context,
                )
                steps.append(
                    {
                        "type": "tool_result",
                        "summary": "工作流元数据"
                        if wm.get("ok")
                        else "工作流元数据失败",
                        "detail": json.dumps(wm, ensure_ascii=False)[:800],
                    }
                )

        # Demo: web search
        if any(
            k in message
            for k in ("搜索一下", "联网搜索", "在线搜索", "web search", "搜一下")
        ):
            q = message
            for prefix in ("搜索一下", "联网搜索", "在线搜索", "web search", "搜一下"):
                if message.casefold().startswith(prefix.casefold()):
                    q = message[len(prefix) :].strip() or message
                    break
            steps.append({"type": "tool", "summary": f"web_search({q[:40]})"})
            ws = execute_server_tool(
                "web_search",
                {"query": q, "limit": 5},
                cred=cred,
                client_context=client_context,
            )
            steps.append(
                {
                    "type": "tool_result",
                    "summary": f"搜索 {ws.get('count', 0)} 条"
                    if ws.get("ok")
                    else "搜索失败",
                    "detail": json.dumps(ws, ensure_ascii=False)[:800],
                }
            )

        result = mock_chat(message, session_id=sid, client_context=client_context)
        reply = str(result["reply"])
        if confirmations:
            reply = (
                f"{reply}\n\n已生成工作流确认卡，请点击「确认提交」后才会真正排队。"
                if reply
                else "已生成工作流确认卡，请点击「确认提交」后才会真正排队。"
            )
        # Prefer tool synthesis when mock reply is empty but tools returned data
        reply = _ensure_visible_reply(
            reply, list(steps), fallback=reply or "（无回复）"
        )
        if history:
            reply = f"（已结合此前 {len(history)//2} 轮对话）\n{reply}"
        usage = {
            "prompt_tokens": estimate_tokens(message),
            "completion_tokens": estimate_tokens(reply),
            "total_tokens": 0,
            "estimated": True,
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        append_turn(
            user_id=user_id,
            session_id=str(result["session_id"]),
            user_message=message,
            assistant_message=reply,
        )
        ui_intents = result.get("ui_intents") or []
        logger.info(
            "agent.reply request_id=%s provider=demo finish_reason=%s reply_chars=%d"
            " tool_calls=%d hops=%d intents=%d",
            get_request_id() or "-",
            finish_reason or "-",
            len(reply),
            tool_calls_done,
            hops_used,
            len(ui_intents),
        )
        out = {
            "session_id": str(result["session_id"]),
            "reply": reply,
            "ui_intents": ui_intents,
            "provider": "demo",
            "profile_id": profile_id,
            "usage": usage,
            "steps": list(steps),
            "confirmations": confirmations,
        }
        _emit_stream_tail(on_event, reply=reply, ui_intents=ui_intents)
        return out

    model = str(profile.get("model") or "").strip()
    if not model:
        raise ValueError("当前配置档未设置模型名称，请在设置中填写或刷新模型列表")
    base_url = str(profile.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("当前配置档未设置 base_url")
    api_key = get_profile_api_key(profile)
    needs_key = provider_kind not in {"ollama", "demo"}
    if needs_key and not api_key:
        raise ValueError("当前配置档未设置 API Key，请在「设置 → Agent 配置」中填写")

    system = _build_system(client_context, cred=cred)
    max_out = min(4096, int(profile.get("context_window_output") or 2048))

    # 输入预算守卫：超限直接中止，绝不外呼（防公众乱问消耗项目额度）
    budget = _prompt_token_budget()
    budget_tools = (
        _all_tools_anthropic() if protocol == "anthropic" else _all_tools_openai()
    )
    est_in = _estimate_prompt_tokens(
        system=system,
        history=history,
        message=message,
        tools=budget_tools,
    )
    if budget and est_in > budget:
        reply = (
            f"这次提问预估需要约 {est_in} token，超过单次上限 {budget} token，"
            "已中止，没有发送给模型。\n\n"
            "可以这样绕过：\n"
            "1. 把问题拆小，一次只问一件事；\n"
            "2. 新建一个会话（历史越长，输入越大）；\n"
            "3. 少粘贴大段文本。"
        )
        steps.append(
            {
                "type": "thought",
                "summary": "输入超出预算，已中止",
                "detail": f"estimate≈{est_in} budget={budget}",
            }
        )
        usage = {
            "prompt_tokens": est_in,
            "completion_tokens": 0,
            "total_tokens": est_in,
            "estimated": True,
        }
        # 历史里只存截断版：否则超长提问会污染上下文，导致后续每问都超预算
        stored_message = (
            message if len(message) <= 200 else message[:200] + "…（原文过长，已截断）"
        )
        append_turn(
            user_id=user_id,
            session_id=sid,
            user_message=stored_message,
            assistant_message=reply,
        )
        out = {
            "session_id": sid,
            "reply": reply,
            "ui_intents": [],
            "provider": "guard",
            "profile_id": profile_id,
            "usage": usage,
            "steps": list(steps),
            "confirmations": [],
        }
        _emit_stream_tail(on_event, reply=reply, ui_intents=[])
        return out

    steps.append(
        {
            "type": "thought",
            "summary": f"调用模型 {model}",
            "detail": f"protocol={protocol} history_turns={len(history)//2}",
        }
    )

    try:
        if protocol == "anthropic":
            steps.append(
                {
                    "type": "thought",
                    "summary": "正在等待模型响应…",
                    "detail": f"{provider_kind}/{model}",
                }
            )
            messages: list[dict[str, Any]] = [
                {"role": m["role"], "content": m["content"]} for m in history
            ]
            messages.append({"role": "user", "content": message})
            data = anthropic_compat.messages_create(
                base_url=base_url,
                api_key=api_key,
                model=model,
                system=system,
                messages=messages,
                tools=_all_tools_anthropic() or None,
                max_tokens=max_out,
            )
            reply, intents, server_calls = _intents_from_anthropic_content(
                data.get("content")
            )
            confirmations: list[dict[str, Any]] = []
            max_hops = _max_tool_hops()
            for hop in range(1, max_hops + 1):
                all_uses = _anthropic_tool_uses(data.get("content"))
                if not all_uses:
                    break
                steps.append(
                    {
                        "type": "thought",
                        "summary": f"工具跳 {hop}/{max_hops}",
                    }
                )
                tool_result_blocks: list[dict[str, Any]] = []
                for sc in all_uses:
                    if sc["name"] not in _SERVER_TOOLS:
                        # 界面意图：必须回一条占位结果凑齐配对，否则下一轮 400
                        tool_result_blocks.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": sc["id"],
                                "content": _UI_TOOL_ACK,
                            }
                        )
                        continue
                    steps.append(
                        {
                            "type": "tool",
                            "summary": f"{sc['name']}({json.dumps(sc.get('args') or {}, ensure_ascii=False)[:80]})",
                        }
                    )
                    tres = execute_server_tool(
                        str(sc["name"]),
                        dict(sc.get("args") or {}),
                        cred=cred,
                        client_context=client_context,
                    )
                    steps.append(
                        {
                            "type": "tool_result",
                            "summary": "待确认"
                            if tres.get("needs_confirmation")
                            else "工具返回",
                            "detail": json.dumps(tres, ensure_ascii=False)[:800],
                        }
                    )
                    conf = _confirmation_from_tool_result(tres)
                    if conf:
                        confirmations.append(conf)
                    tool_result_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": sc["id"],
                            "content": json.dumps(tres, ensure_ascii=False),
                        }
                    )
                server_calls = [c for c in all_uses if c["name"] in _SERVER_TOOLS]
                messages.append({"role": "assistant", "content": data.get("content")})
                messages.append({"role": "user", "content": tool_result_blocks})
                if budget:
                    hop_est = _estimate_messages_tokens(
                        system=system,
                        messages=messages,
                        tools=_all_tools_anthropic(),
                    )
                    if hop_est > budget:
                        raise ValueError(
                            f"工具多轮累计输入预估约 {hop_est} token，"
                            f"超过单次上限 {budget} token，已中止。"
                        )
                data = anthropic_compat.messages_create(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    system=system,
                    messages=messages,
                    tools=_all_tools_anthropic() or None,
                    max_tokens=max_out,
                )
                reply2, intents2, server_calls = _intents_from_anthropic_content(
                    data.get("content")
                )
                if reply2:
                    reply = reply2
                if intents2:
                    intents = intents2
            if server_calls:
                steps.append(
                    {
                        "type": "thought",
                        "summary": f"已达工具跳上限 {max_hops}，停止继续调用工具",
                    }
                )

            if not reply and not intents:
                reply = "（模型未返回文本）"
            reply = _ensure_visible_reply(reply, list(steps))
            reply = _statistics_fallback_reply(
                message, reply, steps, sid, client_context
            )
            if not intents:
                fallback = mock_chat(
                    message, session_id=sid, client_context=client_context
                )
                if fallback.get("ui_intents"):
                    intents = fallback.get("ui_intents") or []
            usage = usage_from_anthropic(
                data, prompt_fallback=system + message, completion_fallback=reply
            )
            append_turn(
                user_id=user_id,
                session_id=sid,
                user_message=message,
                assistant_message=reply,
            )
            out = {
                "session_id": sid,
                "reply": reply,
                "ui_intents": intents,
                "provider": provider_kind,
                "profile_id": profile_id,
                "usage": usage,
                "steps": list(steps),
                "confirmations": confirmations,
            }
            _emit_stream_tail(on_event, reply=reply, ui_intents=intents)
            return out

        # OpenAI-compatible
        steps.append(
            {
                "type": "thought",
                "summary": "正在等待模型响应…",
                "detail": f"{provider_kind}/{model}",
            }
        )
        messages_oai: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in history:
            messages_oai.append({"role": m["role"], "content": m["content"]})
        messages_oai.append({"role": "user", "content": message})

        data = openai_compat.chat_completions(
            base_url=base_url,
            api_key=api_key or ("ollama" if provider_kind == "ollama" else None),
            model=model,
            messages=messages_oai,
            tools=_all_tools_openai() or None,
            max_tokens=max_out,
        )
        choices = data.get("choices")
        message_obj: dict[str, Any] = {}
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                finish_reason = str(first.get("finish_reason") or "") or finish_reason
                if isinstance(first.get("message"), dict):
                    message_obj = first["message"]

        calls = _parse_openai_tool_calls(message_obj)
        intents = _intents_from_tool_calls(calls)
        server_calls = _server_calls(calls)
        reply = str(message_obj.get("content") or "").strip()
        confirmations: list[dict[str, Any]] = []
        max_hops = _max_tool_hops()
        oai_key = api_key or ("ollama" if provider_kind == "ollama" else None)

        for hop in range(1, max_hops + 1):
            if not calls:
                break
            hops_used = hop
            steps.append(
                {
                    "type": "thought",
                    "summary": f"工具跳 {hop}/{max_hops}",
                }
            )
            messages_oai.append(_sanitize_assistant_message(message_obj))
            for sc in calls:
                call_id = str(sc.get("id") or "call")
                if sc.get("name") not in _SERVER_TOOLS:
                    # 界面意图：补齐配对，否则下一次请求整轮 400
                    messages_oai.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": _UI_TOOL_ACK,
                        }
                    )
                    continue
                tool_calls_done += 1
                steps.append(
                    {
                        "type": "tool",
                        "summary": f"{sc['name']}({json.dumps(sc.get('args') or {}, ensure_ascii=False)[:80]})",
                    }
                )
                tres = execute_server_tool(
                    str(sc["name"]),
                    dict(sc.get("args") or {}),
                    cred=cred,
                    client_context=client_context,
                )
                steps.append(
                    {
                        "type": "tool_result",
                        "summary": "待确认"
                        if tres.get("needs_confirmation")
                        else "工具返回",
                        "detail": json.dumps(tres, ensure_ascii=False)[:800],
                    }
                )
                conf = _confirmation_from_tool_result(tres)
                if conf:
                    confirmations.append(conf)
                messages_oai.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(tres, ensure_ascii=False),
                    }
                )
            if budget:
                hop_est = _estimate_messages_tokens(
                    system=system,
                    messages=messages_oai,
                    tools=_all_tools_openai(),
                )
                if hop_est > budget:
                    raise ValueError(
                        f"工具多轮累计输入预估约 {hop_est} token，"
                        f"超过单次上限 {budget} token，已中止。"
                    )
            data = openai_compat.chat_completions(
                base_url=base_url,
                api_key=oai_key,
                model=model,
                messages=messages_oai,
                tools=_all_tools_openai() or None,
                max_tokens=max_out,
            )
            choices = data.get("choices")
            message_obj = {}
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    finish_reason = (
                        str(first.get("finish_reason") or "") or finish_reason
                    )
                    if isinstance(first.get("message"), dict):
                        message_obj = first["message"]
            reply = str(message_obj.get("content") or reply).strip()
            calls = _parse_openai_tool_calls(message_obj)
            more_intents = _intents_from_tool_calls(calls)
            if more_intents:
                intents = more_intents
            server_calls = _server_calls(calls)

        if server_calls:
            steps.append(
                {
                    "type": "thought",
                    "summary": f"已达工具跳上限 {max_hops}，停止继续调用工具",
                }
            )

        if not reply and not intents:
            reply = "（模型未返回文本）"
        reply = _ensure_visible_reply(reply, list(steps))
        reply = _statistics_fallback_reply(message, reply, steps, sid, client_context)
        if not intents:
            fallback = mock_chat(message, session_id=sid, client_context=client_context)
            heur = fallback.get("ui_intents") or []
            if heur:
                intents = heur
        usage = usage_from_openai(
            data,
            prompt_fallback=system + message,
            completion_fallback=reply,
        )
        append_turn(
            user_id=user_id,
            session_id=sid,
            user_message=message,
            assistant_message=reply,
        )
        logger.info(
            "agent.reply request_id=%s provider=%s finish_reason=%s reply_chars=%d"
            " tool_calls=%d hops=%d intents=%d",
            get_request_id() or "-",
            provider_kind,
            finish_reason or "-",
            len(reply),
            tool_calls_done,
            hops_used,
            len(intents),
        )
        out = {
            "session_id": sid,
            "reply": reply,
            "ui_intents": intents,
            "provider": provider_kind,
            "profile_id": profile_id,
            "usage": usage,
            "steps": list(steps),
            "confirmations": confirmations,
        }
        _emit_stream_tail(on_event, reply=reply, ui_intents=intents)
        return out
    except LlmClientError:
        raise
    except Exception as exc:
        logger.exception("Agent LLM call failed profile=%s", profile_id)
        raise LlmClientError(f"模型调用失败：{exc}") from exc


def _attach_command_ids(result: dict[str, Any]) -> dict[str, Any]:
    """给每条 UI 指令补一个可追溯的 ``command_id``（R02）。

    放在 ``run_chat`` 出口统一处理，一处覆盖 demo（mock）与真模型两条返回，
    避免只改 ``_normalize_intents`` 时漏掉 mock 路径。

    只在缺失时补，重复调用不会换号；任何异常都吞掉，绝不因为加编号
    影响正常回复。
    """
    try:
        intents = result.get("ui_intents")
        if isinstance(intents, list):
            for item in intents:
                if isinstance(item, dict) and not item.get("command_id"):
                    item["command_id"] = f"cmd-{uuid.uuid4().hex[:8]}"
    except Exception:  # pragma: no cover - 兜底，编号失败不该影响对话
        logger.debug("attach command_id failed", exc_info=True)
    return result


def run_chat(
    message: str,
    *,
    session_id: str | None = None,
    client_context: dict[str, Any] | None = None,
    user_id: int | None = None,
    cred: Any = None,
    on_event: EventCallback | None = None,
) -> dict[str, Any]:
    """地图助手对话入口（唯一对外入口，含并发闸门与降级）。

    两道保险，目的是「助手出问题不牵连地图」：

    1. **并发闸门**：同时只放 ``BACKEND_AGENT_MAX_CONCURRENT``（默认 2）个对话
       进入模型调用；排不上的在 ``BACKEND_AGENT_QUEUE_TIMEOUT``（默认 15s）后
       直接收到一句可读提示，不再长时间占用线程池。
    2. **降级**：模型超时/断网/配错 Key 时不再抛 502，而是返回一条
       「地图不受影响」的中文回复（``provider="degraded"``），
       真实原因留在 ``steps`` 里供排查。
    """
    gate = _gate()
    if not gate.acquire(timeout=_gate_wait_seconds()):
        logger.warning("agent busy: no free slot, fast-fail")
        return _degraded_result(
            session_id=session_id,
            reply=_busy_reply(),
            provider="busy",
            reason=f"并发已满（上限 {_GATE_SIZE}）",
            on_event=on_event,
        )
    try:
        return _attach_command_ids(
            _run_chat_impl(
                message,
                session_id=session_id,
                client_context=client_context,
                user_id=user_id,
                cred=cred,
                on_event=on_event,
            )
        )
    except ValueError:
        # 参数/配置类错误（消息过长、无配置档）仍交给路由转 422，
        # 不属于「服务不可用」，不该被降级吞掉。
        raise
    except LlmClientError as exc:
        logger.warning("agent degraded: LLM error: %s", exc)
        return _degraded_result(
            session_id=session_id,
            reply=_llm_down_reply(str(exc)),
            provider="degraded",
            reason=str(exc),
            on_event=on_event,
        )
    except Exception as exc:
        logger.exception("agent degraded: unexpected failure")
        return _degraded_result(
            session_id=session_id,
            reply=_llm_down_reply(str(exc)),
            provider="degraded",
            reason=f"{type(exc).__name__}: {exc}",
            on_event=on_event,
        )
    finally:
        gate.release()
