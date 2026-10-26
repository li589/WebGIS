"""Agent chat orchestrator — memory, tools, demo/LLM paths, CoT steps."""

from __future__ import annotations

import json
import logging
import os
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
        summary = catalog_summary(cred=cred, limit=40)
        if summary:
            blob = json.dumps(summary, ensure_ascii=False)[:3000]
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
        "get_workflow_run, get_layer_coverage, list_workflow_timers (admin)\n"
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
        "- resolved.reason 说明“该日期落在某个时间块内”时，要如实告诉用户"
        "“这几天取的是同一块的值，所以数值相同是正常的”，**不得说成日期切换失效**。"
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
                if not server_calls:
                    break
                steps.append(
                    {
                        "type": "thought",
                        "summary": f"工具跳 {hop}/{max_hops}",
                    }
                )
                tool_result_blocks: list[dict[str, Any]] = []
                for sc in server_calls:
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
                            "tool_use_id": sc.get("id") or "tool",
                            "content": json.dumps(tres, ensure_ascii=False),
                        }
                    )
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
            if not server_calls:
                break
            hops_used = hop
            steps.append(
                {
                    "type": "thought",
                    "summary": f"工具跳 {hop}/{max_hops}",
                }
            )
            messages_oai.append(message_obj)
            for sc in server_calls:
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
                        "tool_call_id": sc.get("id") or "call",
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
