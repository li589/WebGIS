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
from app.services.agent import dialogue_state
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
    canonical_layer_state,
    catalog_summary,
    execute_server_tool,
    load_server_tools_anthropic,
    load_server_tools_openai,
)
from app.services.agent.session_store import (
    append_turn,
    load_history,
    load_topic_state,
)
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
    # 预算超限不是「连不上模型」——以前一律套「没连上模型服务」，用户会去
    # 查网络/换模型，白折腾。这里单独分流，直说「本次任务预算不足」（2026-10-29 用户要求）。
    # 2026-10-29 复盘后修文案：原版建议「新建会话」，但实测会话历史压缩后只占
    # 156~440 token（12 轮全满也就 1~2k），真正吃预算的是「固定开销 9947 +
    # 每轮工具返回重复发送」——这类问答天然要 3 轮（搜层 → 查覆盖 → 统计），
    # 第 3 轮必撞线。所以只给能真正省掉一轮的建议。
    if "超过单次上限" in detail or "累计输入预估" in detail:
        return (
            "这次没算成，跟数据无关：这一问要连着查几步"
            "（先定位图层 → 再核对日期 → 再按行政区统计），"
            "累计输入超过了单次上限，中途停下，没有把整段发给模型。\n\n"
            "**地图本身不受影响**：底图、图层、时间轴、点查都能正常用。\n\n"
            "想马上拿到结果，可以少走一步：\n"
            "1. 先在左侧把要问的那一层点上（让它成为当前选中的层），"
            "再问「这一层 2025-12-15 广州市平均是多少」——省掉「找层」那一步；\n"
            "2. 或者拆成两句问：先问「哪一层是 XX 产品」，拿到层名后再单独问数值。"
        )
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


#: 写进 steps[].detail 的体积上限。超过就换成"可解析的摘要"，绝不硬切 JSON。
_TOOL_DETAIL_LIMIT = 20000


def _tool_detail(payload: Any) -> str:
    """把工具返回写进 ``steps[].detail``，**保证仍然可以被 json.loads 还原**。

    2026-11-06 实测（P0）：旧写法是 ``json.dumps(res)[:800]``，直接切断 JSON。
    ``search_layers`` 正常返回就有 3306 字符，切完必然是 ``JSONDecodeError``；
    ``_synthesize_reply_from_tool_steps`` 于是静默 ``continue`` 到底、返回 None，
    最终用户看到的正文是「（模型未返回文本）」。

    触发条件很日常：模型连搜几次没搜到满意的层（撞满工具跳上限 4），这一轮就
    没有文本了 —— 三连测里两次空白。所以这里改成：不超限就原样存完整 JSON；
    超限则包一层仍然合法的摘要对象（``truncated=true``），让合成兜底至少能读到
    ``ok``/``preview``，而不是解析失败。
    """
    if isinstance(payload, str):
        return payload[:_TOOL_DETAIL_LIMIT]
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(payload)[:_TOOL_DETAIL_LIMIT]
    if len(text) <= _TOOL_DETAIL_LIMIT:
        return text
    ok = bool(payload.get("ok")) if isinstance(payload, dict) else True
    return json.dumps(
        {"ok": ok, "truncated": True, "preview": text[: _TOOL_DETAIL_LIMIT - 200]},
        ensure_ascii=False,
    )


#: 跳到上限时正文短于这个长度，就认定「没给出实质回答」，强制收尾再答一次。
#: 实测残留：27 字「我按「X」取数。」（开场白后没了）、66 字搜索结果列表。
_HOP_FINALIZE_MAX_CHARS = 150


def _oai_complete_no_tools(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> str:
    """工具跳用尽后的收尾补答：不带工具再问一次，逼模型用已有结果作答。

    为什么需要：``max_hops`` 用尽时模型刚发起的工具调用不会被执行，``reply``
    往往只剩工具调用前的那句开场白。用户看到「我按「X」取数。」就没了，没法
    判断是坏了还是在处理。这里把已有工具结果交给模型，要求它直接回答。
    失败一律返回空串，由调用方走确定性兜底，绝不让整轮对话挂掉。
    """
    msgs = list(messages)
    msgs.append(
        {
            "role": "user",
            "content": (
                "工具调用次数已用尽。请直接用上面工具已经返回的结果回答我，"
                "不要再调用工具。若结果不足以给出数值，就说明缺什么、"
                "我下一步该怎么做。不要编造任何上面没出现过的数字。"
            ),
        }
    )
    data = openai_compat.chat_completions(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=msgs,
        tools=None,
        max_tokens=max_tokens,
    )
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        return str(msg.get("content") or "").strip()
    return ""


def _finalize_after_hop_limit(
    reply: str,
    steps: list[dict[str, Any]],
    *,
    complete: Any = None,
) -> str:
    """跳到上限且正文过短时补一次收尾；拿不到就用工具结果合成，仍不行保留原样。"""
    text = (reply or "").strip()
    if len(text) >= _HOP_FINALIZE_MAX_CHARS:
        return reply
    if complete is not None:
        try:
            extra = (complete() or "").strip()
        except Exception:
            logger.debug("hop-limit finalize failed", exc_info=True)
            extra = ""
        if len(extra) >= 20:
            return extra
    synth = _synthesize_reply_from_tool_steps(steps)
    if synth and len(synth.strip()) > len(text):
        synth = synth.strip()
        # 兜底如果只是「图层库里相关有 N 个」的清单，跟用户自己看到的搜索框没区别，
        # 补一句追问才算把话说完。
        if synth.startswith(("图层库里", "未在图层库")):
            synth += (
                "\n\n还没确定用哪一层来统计——你告诉我用哪一个，我按你的区域和日期出数。"
            )
        return synth
    return reply


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
            # 工具自己给了面向用户的文案（user_facing）就直接用：失败结果的 error
            # 通常是写给模型的操作指令（含「不得出现数值」「不要提 mat」这类话），
            # 原样当正文会变成内部黑话。2026-11-07 实测：模型把 mat 报错整段抄给用户。
            if data.get("user_facing"):
                friendly = str(data.get("user_facing") or "").strip()
                if friendly:
                    return friendly
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
    # 一条都没合成出来，但这一轮确实调过工具（模型话没说完 / 撞满跳数）：
    # 绝不能把「（模型未返回文本）」这种占位符交给用户，给一句能继续往下走的话。
    if any(
        isinstance(s, dict) and s.get("type") in ("tool", "tool_result") for s in steps
    ):
        return (
            "这次查到的结果没能整理成结论。"
            "你可以把条件说得更具体一点（哪一层、哪一天、哪个区域），我再查一次。"
        )
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
    # 取数链路的技术错误（存储服务名、登录接口、HTTP 状态码）不进正文：
    # 2026-11-07 实测模型把「存储端登录接口返回 HTTP 530」原样抄给了用户。
    if "nas" in lowered or re.search(r"http\s*[45]\d\d", lowered) or "530" in text:
        return "取数服务暂时不可用，这次没取到数"
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
    if "intent_results" in client_context:
        # 上一轮界面意图的**真实执行结果**（前端执行完才上报）。
        # 服务端给模型的即时回执只能是「已下发、未执行」，模型要等这一项才知道
        # 到底成没成——这是"嘴上说已完成、页面没变"的唯一闭环。
        raw_results = client_context.get("intent_results")
        if isinstance(raw_results, list):
            slim_results: list[dict[str, Any]] = []
            for item in raw_results[-5:]:
                if not isinstance(item, dict):
                    continue
                entry_r: dict[str, Any] = {}
                name_r = str(item.get("name") or "").strip()[:64]
                if name_r:
                    entry_r["name"] = name_r
                if item.get("ok") is not None:
                    entry_r["ok"] = bool(item.get("ok"))
                msg_r = str(item.get("message") or "").strip()[:160]
                if msg_r:
                    entry_r["message"] = msg_r
                if entry_r:
                    slim_results.append(entry_r)
            if slim_results:
                cleaned["intent_results"] = slim_results
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
    topic_state: dict[str, str] | None = None,
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
    if safe_ctx and isinstance(safe_ctx.get("intent_results"), list):
        # 单独列出来，避免被上面 4000 字符的 blob 截掉——这条决定模型敢不敢说「已完成」
        rows: list[str] = []
        for item in safe_ctx["intent_results"]:
            if not isinstance(item, dict):
                continue
            mark = "成功" if item.get("ok") else "失败"
            rows.append(
                f"- {item.get('name') or '界面操作'}：{mark}"
                f"（{str(item.get('message') or '无说明')[:120]}）"
            )
        if rows:
            parts.append(
                "## 上一轮界面意图的真实执行结果（浏览器回报）\n"
                + "\n".join(rows)
                + "\n- 有失败项时，先承认「上次那条没有生效」再往下说，"
                "**不许把失败说成成功**；都成功就正常继续。"
            )
    topic_desc = dialogue_state.describe(topic_state)
    if topic_desc:
        # 服务端记住的取数对象。它不一定等于页面上选中的那一层——用户上一轮
        # 可能明确点名了另一层。追问（「其余不变」「只改日期」）必须以它为准。
        parts.append(
            "## 本会话已确认的取数对象\n"
            f"{topic_desc}\n"
            "- 用户说「其余不变 / 只改日期 / 还是那个 / 回到原来的」时，**只替换他这轮"
            "真正提到的那一项**，其余项用上面这份记录，不许改用页面选中层，也不许把"
            "区域悄悄丢掉改算全幅。\n"
            "- 上面这份记录与 client_context 的 selected 冲突时，**以这份记录为准**；"
            "确实要换对象，就在回答里写明「这次改用 X 层」。"
        )
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
        "## 跨轮追问：只改用户提到的那一项\n"
        "- 用户说「其余不变 / 其他不变 / 只改日期 / 只换区域 / 还是那个 / 回到原来的」时，"
        "**先读『本会话已确认的取数对象』**（系统提示里若给了这一段），把没提到的项原样"
        "沿用：他说改日期，就只换日期；**产品、变量、区域一个都不许变**。\n"
        "- 这类追问里，**页面当前选中哪一层与取数对象无关**。哪怕 client_context 的 "
        "selected 指向另一层，也要用本会话记录的那一层；真要改用别的层，必须在回答里"
        "写明「这次改用 X 层」。\n"
        "- **只说了变量、没另指来源或口径时**（「土壤水分的平均值是多少」「那 VOD 呢」），"
        "就统计『本会话已确认的取数对象』里的那一层，**不要重新挑**：同一变量有风云/SMAP、"
        "平均/动态好几支，重挑必然挑到别的支，数就不是他刚看的那一份了。\n"
        "- 用户点名了变量（土壤水分 / VOD / 等效散射 ω）时，取数工具的 catalog_id 必须"
        "是**同一变量**的层：页面选中的是别的变量时，改用同变量的层，或用一句话反问"
        "「哪一个（来源+口径）」，**绝不拿页面选中层顶替**——那会答出一个看着很正式、"
        "其实答非所问的数字。\n"
        "- **页面上根本没有这个变量的层时**（search_layers 里同变量的条目全是 "
        "`on_page=false`），先看目录里**本机已有产物**的同变量层（`on_page=false` 但 "
        "`layer_kind=runtime_product`，或产品族 `group_members` 里带产物的成员）：\n"
        "  · 只有一种来源、且与页面那层同源 ⇒ 直接统计它，正文写清用的是哪一层；\n"
        "  · 有多个来源、或换了另一颗卫星 ⇒ **列出候选让用户点名**（最多四个，每行"
        "一个层名，如「SMAP 动态散射约束产品 · 土壤水分」），绝不自己挑一个开算，"
        "也不许把 `catalog_reference`（参考层）混进候选；\n"
        "  · 本机一层都没有 ⇒ 用一句话说清「页面上现在挂的是〈当前层〉，〈要的变量〉"
        "这一片还没加载」，再给出两条明确的出路（把该变量图层加到页面，或者按当前这层取数）。\n"
        "- 无论走哪条路，都不许用另一颗卫星的同族产品顶替用户没点名的来源。\n"
        "- 同一个问题**最多换两种说法搜**。搜两次仍没有可用层，就按上一条如实说明缺层，"
        "不要用第三种、第四种措辞继续搜——那只会把工具跳数耗尽、最后答不出话。\n"
        "- 区域一旦确认过，就不要再退回「整幅」。只有在用户明确说「全图 / 全球 / 整层 / "
        "不限区域」时才去掉区域。回答里要点明「按 XX 边界统计」，让用户核对。\n"
        "- 取数工具返回里若出现 `product_pinned` 或 `layer_source=session`，说明这一句你"
        "没被要求换产品、工具已按上一轮那层取数：**回答必须沿用该层的名字**，并写明"
        "「产品沿用上一轮」，不许改口成别的卫星/别的口径（数字对、名字错同样是错）。\n"
        "- 用户点了新的产品形态或来源（「换成 SMAP 动态」「风云那套」）时，按新点名换层；"
        "换完在回答里写出新层名，不要悄悄换。\n"
        "## 界面意图回执是「已下发」，不是「已执行」\n"
        "- 下发 set_layer_visibility / set_timeline / remove_layer / set_layer_symbology "
        "后，工具回执只表示**已交给浏览器**（executed=false）。此时正文只能写"
        "「已下发 / 已提交」，**不许写「已显示 / 已切换成功 / 已完成」**。\n"
        "- 真实结果看 `client_context.intent_results`（前端执行完才上报，"
        "每项含意图名、ok 与说明）。"
        "上一轮 ok=false 时，这一轮要先承认「上次那条没有生效」并说明原因，"
        "**不许把失败说成成功，也不许当没发生过**。\n"
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
        "## 下发视图意图的那一轮：禁止替界面报日期\n"
        "- `set_layer_visibility` / `set_timeline` / `remove_layer` / `set_layer_symbology` "
        "这几条**由浏览器在你回复之后才执行**。切换图层会连带把时间轴按该图层的记忆日期"
        "跳过去，而那一刻的日期由界面回执给出（形如“已显示「X」，时间轴跟着切到 YYYY-MM-DD”）。"
        "所以这一轮的正文**不要写出切换后的具体日期**，只说“已按要求切换”即可；"
        "`client_context.timeline.date` 是**请求发出时**的日期，禁止把它当作切换后的日期播报。"
        "（2026-11-04 实测：页面已跳到 2026-02-02，回答却写“仍停在 2025-12-15”。）\n"
        "- 例外，且**优先于上一条**：用户是在**问**当前日期/画面状态（而不是让你改画面）时，"
        "仍按 client_context 如实回答“当前时间轴停在 X”。\n"
        "- 同样**不许**自行断言“这个日期在不在时间块 / 时间轴范围内”，也不许推测"
        "“前端会不会为它补帧”。只有工具返回里明确给了 time_list / available_dates / "
        "period_start~period_end 才能下这种判断；没查就说“已按你给的日期下发，"
        "实际命中哪一片以时间轴回显为准”。（2026-11-06 实测：7 月 1 日明明落在 "
        "2025-07-01~07-31 这一块内，回答却说“不在时间块范围内”。）\n"
        "- 同上，**不许**说某层的时间块“是 8 天块 / 正好是一整月 / 这一段就是一片”。"
        "块的长度只认 get_layer_coverage / get_layer_meta 返回的 native_step、"
        "time_blocks、period_start~period_end。各层粒度并不一样：动态产品是 8 天块，"
        "平均产品是**整月**一块（native_step=1M），同一个日期区间在两者身上根本不是"
        "一回事。（2026-11-06 实测：风云平均那层是整月合成，回答却称“12-11~12-18 "
        "正好是一个 8 天块”，把动态产品的粒度安到了平均产品头上。）\n"
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
        "- **get_layer_statistics 会自己去 NAS 补取这一天**（2026-11-05 起）："
        "时间清单里没有该日时，工具已自动按需补取单日帧，结果在返回的 ondemand_fetch 里。"
        "三种情况**必须分开说**："
        "① ok=true → 这一帧是刚按需补取的，**直接用数值回答**，并说明“已按需从 NAS "
        "取到这一天”，不要说成“清单里本来就有”；若同时带 temporal_basis_note，"
        "（ω 的日序气候态 / 8 天块共用）必须一并照说。"
        "② reason=nas_missing → 已尝试过，但 NAS 上该日确实没有成果，"
        "才可以说“这一天上游没有成果”。"
        "③ reason=fetch_failed → 是取数出错，**必须说“取数失败”，"
        "严禁说成“该日没有数据”**。"
        "④ reason=not_registered → 该层没有登记逐日数据源，只能取清单里已有的时间片。\n"
        "- **所选区域没数据 ≠ 整层没数据**：返回带 region_empty_hint 时，"
        "说明整幅有有效数据、只是这个区域在这一天没有有效像元。"
        "必须说“这一天这个区域没有有效观测”，不能说成“该图层没有这一天”；"
        "若用户要换日期，可从 suggested_times 里挑（这些已按该区域逐个核实过真有像元），"
        "也可以建议扩大范围。\n"
        "- **缺测原因不许自己编**：工具不返回质量标记（没有 qc / 云量字段），"
        "所以只能说“没有有效观测 / 缺测”，**禁止归因成“云覆盖 / 云遮挡 / 天气不好”**"
        "这类未经核实的解释（SMAP 等微波产品本来就能穿云）。用户追问原因时，"
        "如实说“这次没有质量标记，具体原因需要查该产品的处理记录”。\n"
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
        "## 一次问多项 / 单位 / 能力边界\n"
        "- **一次问多项就逐项给数**：用户一句话里问两个以上对象（多个变量、多个日期、"
        "多个区域、多个图层）时，**每一项都要单独给出数值和口径**，不许只答最后一项，"
        "也不许用“以这段为准”把前面已经答过的那一项作废。工具返回几条就答几条；"
        "其中某一项取不到时单独说明那一项的原因，不影响其它项照常回答。"
        "（2026-11-07 实测：问“土壤水分和光学厚度分别是多少”，两次数值都算出来了，"
        "正文只报了后一个，前一个被静默丢掉。）\n"
        "- **数值单位只写 `unit_label`**：返回里的 `unit` 是机器字段，无量纲常写成「1」，"
        "贴进正文就会变成“0.1507 1”这种读不通的写法。正文一律用 `unit_label`；"
        "它是“无量纲”时，写“无量纲”或者干脆不写单位。\n"
        "- **不确定的能力不许断言“平台没有”**：没有对应工具时，只能说“我这边没有直接"
        "导出/下载的能力”，并告诉用户去哪做（导出、下载在数据管理页的导出入口，"
        "支持 csv / geojson / shp / GeoTIFF / NetCDF / mat）。"
        "**严禁说成“平台没有提供这个功能”**——平台有这个功能，只是这个对话里没有调用它的"
        "工具，说成“没有功能”是事实错误。\n"
        "- **不许编造尝试次数与耗时**：工具只说“取数失败”时，就照实说“这次取数失败”，"
        "不许写“连续 3 次下载都出错”这类返回里根本没有的次数。底层报错（HTTP 状态码、"
        "服务名、接口名、目录名）也不要出现在正文，统一说成“取数服务暂时不可用”。\n"
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
        "- 统计对象：**只要用户说出“算/统计/取数/均值 + 某个产品名/变量名”，那个名字"
        "就是点名，优先级高于页面选中层，永远不许拿 selected=true 那层顶替**——"
        "哪怕用户同时说“页面别动 / 仍选中另一层”也一样，后台算的对象是点名的层，"
        "页面选中谁与计算对象无关。只有用户**完全没提任何产品名**时才用 "
        "selected=true 那层兜底，其次唯一可见层；多个候选且没指明才反问。\n"
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
        "  · `climatology`＝**多年气候态**（ω 平均组，NAS 上是 `doy_DDD.mat`，"
        "一棵文件对应全年同一天）：必须说“多年气候态 / 同期平均”，"
        "**严禁说成该日当天的观测**；`block_shared`＝ω 动态组的 8 天块共用值，"
        "必须给出块的起止日期并说明块内各天同值。\n"
        "- `layer_source=page` 表示用的是页面选中层，回答要点名是哪一层；"
        "出现 `layer_source_warning` 或 `page_candidates` 且形态不符时，必须从 "
        "`page_candidates` 里选形态匹配的那层、显式传 catalog_id 重算。\n"
        "- 时间口径以 `time_source` 为准（page/requested/layer_default）；`layer_default` "
        "时必须先说“本次用的是图层默认时间块，不是页面当前日期”。`period_start~period_end` "
        "是本次命中的那一片，`layer_span_*` 才是整层首尾，不得互换；`is_daily_frame=true` "
        "才能说“当天的独立观测”。\n"
        "- **一次列多个时间片时必须逐段对号**：每一行的均值与有效像元数只能来自该时间片"
        "自己那次工具返回（对号依据是 `period_start~period_end` / `value_basis`）。写完自查："
        "相邻两行数值和像元数一模一样时，先怀疑自己抄重了、回去核对工具返回；"
        "**没确认两块真的一样之前，不许把它解释成「持平 / 没有继续下降 / 处于低位」**。"
        "2026-11-06 实测过一次：把 12-03~12-10 块的 0.193 / 1340 抄给了 12-15 单日"
        "（真实是 0.293 / 163），并据此得出「12 月中旬持平」的错误结论。\n"
        "- 回答必须说清：用户指定的日期（用户没指定就说“当前时间轴停在 X”，"
        "**不要说成“你请求的日期”**）、实际命中的时间块、统计范围是整幅栅格而非视口，"
        "并给出 mean、valid_pixels 与 unit_label。`extent` 是本次真正统计到的经纬度框，"
        "一并说明；只有用户明确指定区域才传 bbox。\n"
        "- **用户说“某省/某市/某自治区/港澳台（整个行政区）平均”时，必须传 `region`"
        "（行政区名），不是 bbox**：后端按该行政区边界多边形做掩膜，只算边界内像元、"
        "不混入邻近行政区。回答里依 `region_level` 写“按「XX 省」行政边界统计”或"
        "“按「XX 市」行政边界统计”，绝不要说“矩形范围”。"
        "`region` 支持**省级**（省/自治区/直辖市/港澳台）和**地级市**（地级市/自治州/"
        "地区/盟）；**县/区一级不支持**——用户问“XX 县/XX 区”时如实说明“目前支持到"
        "地级市”，并问是否改用所属市或整省。\n"
        "- **只有用户明确给出经纬度框时才走 bbox**；出现 `scope=bbox` 时必须写明"
        "“按经纬度矩形框统计，不是行政区边界”，并给出框的西/南/东/北四至；"
        "**绝不能说成“XX 市平均值”**——矩形范围不等于行政辖区"
        "（2026-10-29 用户明确要求：广州一带用了矩形就要写成“广州附近矩形范围”）。"
        "用户说的是市名/省名却走了 bbox 属于错用，必须改传 `region` 重算。\n"
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


def _merge_intents(
    base: list[dict[str, Any]], extra: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """合并两批界面意图（同名同参的只留一份，后到的覆盖同名的旧参数）。

    2026-11-06：原来写的是 ``intents = more_intents``——**覆盖**而不是合并。
    模型在一次复合指令里先下发「显示 VOD」、下一跳再下发「切日期」时，第一跳
    的意图会被第二跳整批顶掉，用户看到的就是「说显示却什么都没变」。
    """
    merged: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for item in [*base, *extra]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        key = json.dumps([name, args], ensure_ascii=False, sort_keys=True)
        if key in index:
            continue
        index[key] = len(merged)
        merged.append({"name": name, "args": dict(args)})
    return merged


def _state_patch_from_message(
    message: str,
    client_context: dict[str, Any] | None,
    topic_state: dict[str, str] | None,
) -> dict[str, Any]:
    """从**用户这一句话**里解析「他在说哪一层 / 哪里 / 哪天」，写进会话状态。

    2026-11-06 补（同日第二次）：上一版只靠「模型调了工具」回写状态，实测模型
    会直接复述历史作答、一次工具都不调（用户第 1 句「SMAP 动态的土壤水分」就是
    这样），于是状态仍是空的，下一句「土壤水分的平均值是多少」只好自己挑一个
    同变量层——挑成了「风云卫星 平均」，答的不是刚才那一层。

    结论：状态要靠**确定性解析**维护，不能指望模型的调用习惯。
    解析不出唯一对象（返回 ``why``）或只是页面兜底时，一律不写——宁缺勿错。
    """
    if not (message or "").strip():
        return {}
    try:
        from app.services.agent import mock_orchestrator
    except Exception:  # pragma: no cover - 理论上不会发生
        return {}
    try:
        layers = mock_orchestrator._normalize_layers(client_context)
        got = mock_orchestrator.resolve_entities(
            message, layers, client_context=client_context, state=topic_state or {}
        )
    except Exception:  # noqa: BLE001 - 状态维护失败不该拦住这一轮对话
        logger.warning("解析会话对象失败", exc_info=True)
        return {}
    # 「页面当前选中层」不是用户点名的对象，但它**确实是这一轮实际取数的那一层**。
    # 2026-11-06 实测（外部复测）：恢复历史会话后说「只改 12 月 16 日，其余不变」，
    # 结果换成风云平均并返回 0.2413 / 1282 像元——串了产品。
    # 根因就在原来这里直接 `return {}`：连 region/date 一起丢掉，于是下一句
    # 「其余不变」手里什么都没有，只能回退到页面当前 selected；页面此时停在别的
    # 产品上，就换成了另一颗卫星。显式点名能过、隐式继承不能过，差别就在这里。
    # 现在的规则：区域/日期/变量照记；页面上来的层**只在还没有基线时**记一次，
    # 已有基线就不覆盖（用户没点名换层，不该被页面悄悄改掉）。
    prev = dialogue_state.sanitize(topic_state or {})
    # ★ 2026-11-07 补：`layer_from == "variable"`（页面只有这一个同变量层 ⇒ 只能是它）
    # 同样是**页面兜底**，不是用户点名的层。旧实现只认 "page"，于是第 2 句
    # 「只改日期」被标成 layer_from="variable"，照样走覆盖分支——实测把 SMAP 基线
    # 改成了页面上那层风云（`_state_patch_from_message` 单测复现：Q2/Q4 两处）。
    # 基线被页面悄悄换掉之后，第 5 句再点名 SMAP 时「基线=风云 / 页面=风云」而
    # 用户要 SMAP，兜底只会回一句「没取到数值」——用户看着就是「明明刚才还能查」。
    is_page_layer = got.get("layer_from") in ("page", "variable")
    if not is_page_layer and not mock_orchestrator._has_layer_hints(message):
        # 这句话**没点来源/产品形态**（「只改日期，其余不变」「区域改为广州」），
        # 解析却给出了一个层 —— 那只能是页面上挂着的那一层：``_resolve_layer``
        # 对不含层名的句子会退到页面当前项，并且把它标成 layer_from="message"。
        # 实测（2026-11-07 五句连问）：第 2 句就是这样把基线从 SMAP 改成页面风云，
        # 之后第 5 句点名 SMAP 时基线与页面互相矛盾，兜底只能回「没取到数值」。
        # 用户没点名换层，就不该被页面悄悄改掉基线。
        is_page_layer = True
    patch: dict[str, str] = {}
    conflict = False
    layer = got.get("layer")
    if isinstance(layer, dict) and layer.get("catalog_id"):
        cand = canonical_layer_state(
            str(layer["catalog_id"]),
            display=mock_orchestrator._display(layer),
            client_context=client_context,
        )
        # 「层」和「变量」互相矛盾 ⇒ 这条线索不可信，层和变量都别写。
        # 2026-11-07 实测：页面挂风云·土壤水分、上一轮是 SMAP 动态·土壤水分，
        # 用户说「那如果把变量换成光学厚度 VOD 呢」，解析结果是「页面那一层 +
        # 变量 vod」——层是土壤水分、变量却是 VOD，拼在一起就是
        # layer_id=风云 / variable=vod 这种根本不存在的组合。写进基线之后，
        # ① 跨来源守卫看到「基线=风云」，把用户明明要的 SMAP VOD 拦成「要确认」；
        # ② 下一句「只改日期」会粘到风云上——比原来的串产品更糟。
        # 变量冲突时层和变量都不写（保留上一轮那层当锚点），只更新区域/日期；
        # 真正取到哪一层，由本轮工具返回的 resolved 结果回填。
        want_var = str(got.get("variable") or "")
        cand_var = str(cand.get("variable") or "")
        if want_var and cand_var and want_var != cand_var:
            conflict = True
        elif not is_page_layer or not prev.get("layer_id"):
            patch.update(cand)
    if got.get("variable") and not conflict:
        patch["variable"] = str(got["variable"])
    if got.get("region"):
        patch["region"] = str(got["region"])
    if got.get("date"):
        patch["date"] = str(got["date"])
    # 用户换了变量（「换成 VOD」），但这一句定位不到具体某层：旧的 layer_id 已经
    # 肯定不是他要的对象，必须清掉——留着它下一次就会被当成「已确认的层」，
    # 于是变量和层名互相矛盾，又回到「问土壤水分答 ω」的老路上。
    if not patch.get("layer_id") and patch.get("variable"):
        prev_var = dialogue_state.variable_from_name(str(prev.get("layer_name") or ""))
        if prev_var and prev_var != patch["variable"]:
            patch["clear"] = ("layer_id", "layer_name")
    return patch


def _state_patch_from_tool_calls(
    uses: list[dict[str, Any]], client_context: dict[str, Any] | None
) -> dict[str, str]:
    """从本轮**真正执行过的取数工具**里回填「这一轮讲的是哪一层 / 哪天 / 哪个区域」。

    2026-11-06 补：``_state_patch_from_intents`` 只覆盖「模型下发界面意图」的情况。
    但更常见的路径是模型**直接调 get_layer_statistics / get_layer_coverage /
    get_layer_meta 作答**（用户问「SMAP 动态的土壤水分」就是这么答的），那条路
    一个字都不写会话状态。于是下一句「土壤水分的平均值是多少」手里什么都没有，
    只能看页面选中层——而页面停在上一次看的那一层（等效散射 ω），答非所问。
    模型查了哪一层，本身就是「这一轮的对象」，照实记下来就行。
    """
    patch: dict[str, str] = {}
    layers: list[dict[str, Any]] = []
    if isinstance(client_context, dict) and isinstance(
        client_context.get("active_layers"), list
    ):
        layers = [x for x in client_context["active_layers"] if isinstance(x, dict)]

    for item in uses:
        if not isinstance(item, dict):
            continue
        # 只看**真执行了的服务端工具**：界面意图（set_layer_visibility 等）此刻
        # 还没被浏览器执行，拿它记对象会把「想切但没切」记成「就在看它」。
        if str(item.get("name") or "") not in _SERVER_TOOLS:
            continue
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        cid = str(args.get("catalog_id") or "").strip()
        if not cid:
            continue
        # 2026-11-07：原来这里直接记模型传的目录层 id，再配页面上的层名，
        # 于是「id=SMAP 动态、名字=风云卫星平均」这种自相矛盾的组合被写进会话，
        # 下一轮模型照名字选层就直接串产品。现在 id/名字/变量统一由
        # canonical_layer_state 从 id 反查，任一处更新都不会只剩下半套。
        display = ""
        for la in layers:
            if str(la.get("catalog_id") or "") == cid:
                display = str(la.get("name") or "").strip()
                break
        patch.update(
            canonical_layer_state(cid, display=display, client_context=client_context)
        )
        region = str(args.get("region") or args.get("boundary") or "").strip()
        if region:
            patch["region"] = region
        when = str(args.get("time") or args.get("date") or "").strip()[:10]
        if len(when) == 10 and when[4] == "-":
            patch["date"] = when
    return patch


def _state_patch_from_tool_results(
    results: list[dict[str, Any]],
) -> dict[str, str]:
    """把「工具真正取到的那份产物」记进会话状态。

    2026-11-07 第二次外部复测：``_state_patch_from_tool_calls`` 记的是**模型传的
    catalog_id**，而模型习惯传目录层 id（``method-*``），那类 id 在盘上没有同名
    产物目录，``_baseline_layer_id`` 出于「拿它取数必然报错」的理由直接拒收。
    结果就是基线等于白记：下一句「区域改为广州市，日期和产品保持不变」照样退到
    页面选中层，又串成另一颗卫星（实测 SMAP 动态 → 风云动态 0.2032/66 像元）。

    工具自己知道映射后的产物 id（``resolved_layer_id``），照它记才准：
    基线变成``imported-*``，产品粘性才有东西可粘。
    """
    patch: dict[str, str] = {}
    for res in results:
        if not isinstance(res, dict) or not res.get("ok"):
            continue
        local = str(res.get("resolved_layer_id") or "").strip()
        if not local:
            # 2026-11-07 第五次外部复测（游客实测，广州串风云平均 0.3079/36）：
            # 粘性一旦纠正了模型传错的目录 id，工具返回的 ``catalog_id`` 已经
            # 被改写成**实际读的那份产物**（imported-*），于是
            # ``resolved_layer_id = local_id if local_id != catalog_id else ""``
            # 恒为空 —— 旧实现只认这个字段，等于这一跳什么都没记，基线留在
            # 模型传错的那颗卫星上。下一句「区域改为广州市」就照着错基线取数。
            # 工具返回的 catalog_id 本身就是既成事实，它像产物 id 就直接用。
            cid = str(res.get("catalog_id") or "").strip()
            if cid.startswith(("imported-", "wf-run-")):
                local = cid
        if not local:
            continue
        patch.update(
            canonical_layer_state(
                local, display=str(res.get("display_name") or "").strip()
            )
        )
    return patch


def _state_patch_from_intents(
    intents: list[dict[str, Any]],
    client_context: dict[str, Any] | None,
    *,
    keep_layer: bool = False,
) -> dict[str, str]:
    """从界面意图里回填「这一轮讲的是哪一层 / 哪一天」。

    用户说「显示风云 VOD，算一下均值」时，模型下发的 set_layer_visibility 就是
    他对「这一轮的对象」最明确的表达；不记下来，下一轮追问又只能靠页面猜。
    隐藏某一层（visible=false）不算——那是在说「别看了」，不是「就它」。

    ``keep_layer=True``：本轮工具已成功读过某一层，基线记的是**真读到的那份**。
    此时意图里的 catalog_id 只是模型的**请求参数**，可能正是被粘性纠正掉的那个
    错 id；再拿它覆盖就把正确基线冲了。2026-11-07 游客实测：模型传风云平均、
    工具实际读 SMAP，意图回填又把基线写回风云 ⇒ 下一句「只改区域」串成
    风云平均 0.3079 / 36 像元。这时只取日期，层一律不动。
    """
    patch: dict[str, str] = {}
    layers: list[dict[str, Any]] = []
    if isinstance(client_context, dict) and isinstance(
        client_context.get("active_layers"), list
    ):
        layers = [x for x in client_context["active_layers"] if isinstance(x, dict)]

    def _remember(cid: str) -> None:
        if not cid or keep_layer:
            return
        display = ""
        for la in layers:
            if str(la.get("catalog_id") or "") == cid:
                display = str(la.get("name") or "").strip()
                break
        patch.update(
            canonical_layer_state(cid, display=display, client_context=client_context)
        )

    for item in intents:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        if name == "set_layer_visibility":
            if args.get("visible") is False:
                continue
            _remember(str(args.get("catalog_id") or "").strip())
        elif name == "set_timeline":
            date = str(args.get("date") or "").strip()[:10]
            if date:
                patch["date"] = date
            _remember(str(args.get("catalog_id") or "").strip())
    return patch


# 一轮里模型可能同时下发「界面意图」和「服务端工具」（例如
# “切到 X 图层、日期设为 Y，然后算均值”）。OpenAI / Anthropic 都要求
# 每个 tool_call 都有配对的 tool 结果，否则第二次请求整轮直接 400：
#   An assistant message with 'tool_calls' must be followed by tool messages
#   responding to each 'tool_call_id'.
# 所以界面意图也要回一条占位结果，不能只回服务端工具那几条。
#
# ★ 2026-11-06：这条回执原来是写死的「成功」——
#     {"ok": true, "applied": "前端界面意图，由浏览器执行…"}
#   而此刻浏览器**还没执行**。模型读到 ok=true 就理直气壮地答「已完成」，
#   页面却纹丝不动（外部测试第 1 条「首次要求显示风云 VOD，回答称成功，
#   但页面仍选中 ω」）。现在如实标成「已下发、未执行」，真实结果由前端在
#   下一轮通过 client_context.intent_results 回报。
_UI_TOOL_ACK = json.dumps(
    {
        "ok": True,
        "status": "queued",
        "executed": False,
        "note": (
            "界面意图已下发给浏览器，此刻尚未执行。"
            "不要在正文里写「已显示 / 已切换 / 已设置成功」这类完成态；"
            "只能说「已下发，执行结果见气泡下方的提示」。"
            "真实执行结果会在下一轮的 client_context.intent_results 里回报。"
        ),
    },
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


# 存进会话历史的单条回复上限（字符）。回答开头必含「层名 + 关键数值结论」，
# 尾部是解释/建议，可安全截断——否则长会话里 12 轮完整回答就把 20000 预算顶爆。
# 2026-10-29 实测：连续十几轮后输入达 20000+，只因历史里堆了每轮几百字的完整回答。
_HISTORY_REPLY_MAX_CHARS = 200


def _compress_history_reply(reply: str) -> str:
    """把要写入会话历史的助手回复压到 ``_HISTORY_REPLY_MAX_CHARS`` 以内。

    只截尾部（开头是层名+数值结论，必须保留），不丢跨轮指代所需的锚点。
    空回复 / 短回复原样返回。
    """
    if not reply:
        return ""
    if len(reply) <= _HISTORY_REPLY_MAX_CHARS:
        return reply
    return reply[:_HISTORY_REPLY_MAX_CHARS] + "…（回答已压缩）"


_HISTORY_USER_MAX_CHARS = 400


def _compress_history_user(message: str) -> str:
    """写历史时压缩用户消息。

    常规提问（<=400 字）原样保留，不影响跨轮指代；只有粘贴大段文本才截断
    ——否则 12 轮 × 上千字的提问会单独把 20000 预算吃掉大半。
    """
    if not message:
        return ""
    if len(message) <= _HISTORY_USER_MAX_CHARS:
        return message
    return message[:_HISTORY_USER_MAX_CHARS] + "…（原文过长，已截断）"


# 多轮工具返回里，除最近一轮外都只保留前 N 字符。
_TOOL_RESULT_KEEP_CHARS = 700


def _shrink_old_tool_results(messages: list[dict[str, Any]]) -> None:
    """把**之前轮次**的工具返回压短，只让最近一轮保持完整。

    多轮工具调用（``max_hops`` 默认 4）时 messages 会累积 4 份完整工具返回
    （每份 1500~2800 token），单这一项就能把 20000 预算吃光——2026-10-29
    实测 20704 token 超限的主因就是它（system+工具 schema 已固定占 9333）。
    模型做下一步决策只需要「上一轮取到了什么」，更早的轮次留个开头就够。

    调用时机：在 append 新一轮工具返回**之前**，这样被压的永远是旧轮次。
    兼容两种协议：OpenAI 的 ``role=tool`` 消息、Anthropic 的 ``tool_result`` block。
    """
    limit = _TOOL_RESULT_KEEP_CHARS
    note = "…（早期轮次的工具返回已压缩，关键字段在开头）"
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        # OpenAI 协议：role=tool，content 是 JSON 字符串
        if role == "tool" and isinstance(content, str) and len(content) > limit:
            m["content"] = content[:limit] + note
            continue
        # Anthropic 协议：user 消息里嵌 tool_result block
        if role == "user" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                inner = block.get("content")
                if isinstance(inner, str) and len(inner) > limit:
                    block["content"] = inner[:limit] + note


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


_STATISTICS_WORDS = re.compile(
    # 2026-11-04 补「多少/是多少/多大」：外部测试第 2 轮问「广州市的土壤水分是多少」，
    # 这句话不含原有关键词，被判定为「不是统计请求」⇒ 兜底不触发 ⇒ 模型凭空报了
    # 0.148 m³/m³ 与 1024 个有效栅格（该时间片全球有效像元其实是 0）。
    r"平均|均值|统计|像元|mean|average|最大|最小|多少|是多少|多大",
    re.I,
)
# 产品族名自带「平均」二字（「SMAP 平均散射约束产品」），不剥掉的话
# 「这一层的 catalog_id 是多少」会被判成统计请求，进而被规则引擎覆盖成
# 「页面选中层的均值」。2026-10-29 实测第 4 问就是这么把正确答案吃掉的。
_LAYER_NAME_NOISE = re.compile(
    r"(?:动态|平均|月均|季均|逐日|daily|average|dynamic)?\s*散射约束产品|产品族",
    re.I,
)
# 时间结构类提问（片数/天数/时间清单）：答案在 time_list 与覆盖信息里，不是统计值
_TIME_STRUCTURE_RE = re.compile(
    r"时间片|时间块|时间清单|时间轴|多少天|几天|片数|补了几天|几个时次|多少时次", re.I
)

#: 改色标 / 改量程是**写操作**，不是统计请求。
#: 2026-11-06 实测：「把这个图层的最大值改成 0.5，最小值改成 0.1」里的「最大值」
#: 命中了 _STATISTICS_WORDS，兜底于是判成统计请求、整段替换成一段均值说明，而
#: 界面上的色标其实已经被 set_layer_symbology 改掉了 —— 正文说「本次只读统计，
#: 未写入产物」，实际已经改了视图，用户拿到的是自相矛盾的回执。
_THRESHOLD_WORD_RE = re.compile(
    r"最大值|最小值|上限|下限|量程|色标|阈值|vmax|vmin", re.I
)
_THRESHOLD_SET_VERB_RE = re.compile(
    r"改成|改为|设成|设为|调到|调成|调整为|调整到|改到|调到|改成", re.I
)
#: 只有「纯改阈值」才排除；「改完阈值再算平均」这种复合指令仍要出数
_STAT_KEEP_RE = re.compile(r"平均|均值|统计|像元|mean|average", re.I)

#: 对比 / 差值类追问：「跟河南比差多少」「比河南高多少」「两者相差多少」。
#: 2026-11-06 实测 3/3 全错：这些句子里的「多少」命中了 _STATISTICS_WORDS，
#: 模型这轮本来打算直接把上两轮的数值相减（它确实没调工具），结果被兜底判成
#: 「统计请求」，用上一轮的 region 重放了一遍单区均值 —— 用户问「差多少」，
#: 拿到的是「河南 = 0.2929」；说「两者相差多少」时上一轮 region 为空，更是
#: 重放成整幅 0.1625 / 31.4 万像元。数值本身没错，但答的不是他问的那件事。
#: 判据要放在 _STATISTICS_WORDS 之前：差值是「两个已有数」的运算，不是一次取数。
#: 注意：比较词里**不能**放单字「多/少」——「河南比河北的土壤水分是多少」里的
#: 「多」属于疑问词「多少」，放进去会把一切「A 比 B 是多少」误判成差值追问
#: （实测过，直接让整句统计请求失去兜底）。只用 差/高/低/大/小，多与少改写进
#: 下面第二支的固定搭配里。
_DIFF_QUESTION_RE = re.compile(
    r"(?:跟|和|与|同|比)[^，。？！]{0,15}?(?:差|高|低|大|小)(?:多少|几)?"
    r"|相差|差值|差多少|高多少|低多少|多多少|少多少"
    r"|谁(?:更|比较)?(?:高|低|大|小|干|湿|多|少)",
    re.I,
)


def _is_threshold_write(text: str) -> bool:
    """这句话是不是在改色标阈值（而不是要统计结果）。"""
    if not text:
        return False
    if not (_THRESHOLD_WORD_RE.search(text) and _THRESHOLD_SET_VERB_RE.search(text)):
        return False
    return not _STAT_KEEP_RE.search(text)


def _wants_statistics(message: str) -> bool:
    """用户这句话是不是在要整层统计（报告第二轮 A06~A08 的判据）。"""
    text = _LAYER_NAME_NOISE.sub(" ", message or "")
    # 排除「时间结构」类提问：它们同样含「多少/几个」，但答案在 time_list /
    # 覆盖信息里，跑统计只会把「本层共 13 片」换成一段无关的均值。
    if _TIME_STRUCTURE_RE.search(text):
        return False
    # 排除「改阈值/量程」：那是界面写操作，答案该由下发的意图说了算
    if _is_threshold_write(text):
        return False
    # 排除「对比/差值」：问的是两个已有数的差，重放单区统计只会答成其中一边
    # （2026-11-06 实测 3/3，见 _DIFF_QUESTION_RE 注释）。这类交给模型直接算，
    # 它上下文里本来就有上两轮的数值；真要重新取数时它会自己调工具，
    # 那时 _statistics_tool_called 会放行原文，不受这条影响。
    if _DIFF_QUESTION_RE.search(text):
        return False
    return bool(_STATISTICS_WORDS.search(text))


def _statistics_tool_called(steps: list[dict[str, Any]]) -> bool:
    """本轮是否真的调过取数类工具（统计 / 覆盖 / 元数据 / 点采样）。

    2026-10-29 补充：原先只认 get_layer_statistics，但身份类、时间口径类提问
    正确路径是 get_layer_coverage；它一被调用就说明模型确实在查这一层，
    此时规则引擎（只认页面选中层）不得介入。

    2026-11-06 补充 ``sample_layer_point``：点采样同样是「确实取到数了」。漏掉它
    的后果是——问「地图上我点的那个位置土壤水分是多少」时，工具正正常常返回
    0.193，兜底却因为「没认到统计工具」判成无出处，把整段正确答案换成一句
    「这次没有取到统计结果」。点采样功能因此对用户 100% 不可用（2026-11-06 实测）。
    """
    _data_tools = (
        "get_layer_statistics",
        "get_layer_coverage",
        "get_layer_meta",
        "sample_layer_point",
    )
    for step in steps:
        if str(step.get("type") or "") != "tool":
            continue
        summary = str(step.get("summary") or "")
        if any(name in summary for name in _data_tools):
            return True
    return False


_UNGROUNDED_REPLY = (
    "这次没能取到可用的数值，所以我不给结论——免得给你一个查不到出处的数。"
    "麻烦再说明一次要看哪一层、哪一天，我重新取；"
    "如果那天落在这个图层没有数据的时间段里，我会直接告诉你是哪几天。"
)

#: 正文里「N 个有效像元」与「有效像元：N 个」两种语序都要认——中文答案里
#: 后者更常见（「- 有效像元：1995 个」），只按前一种写会漏掉关键词后面的数字。
_PIXEL_MENTION_RE = re.compile(
    r"(\d[\d,]*)\s*个\s*(?:有效)?(?:像元|栅格)"
    r"|(?:有效像元|有效栅格|像元数|栅格数)\s*[:：]?\s*(\d[\d,]*)"
)


#: 这些键下的数字是「元数据计数」而不是取到的值（``limit=20``、``count=3``、
#: 图片宽高…）。收进白名单等于给正文开一张空白许可证——随便写个数就"匹配上"。
_NUMBER_KEY_SKIP = frozenset(
    {
        "limit",
        "count",
        "offset",
        "page",
        "page_size",
        "max_hops",
        "hop",
        "total_count",
        "n",
        "index",
        "code",
        "status",
        "size",
        "width",
        "height",
        "bytes",
        "elapsed_ms",
        "duration_ms",
    }
)


def _iter_numbers(obj: Any, key: str = ""):
    """递归取出对象里的数值（跳过布尔与元数据计数键）。"""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        if str(key).lower() not in _NUMBER_KEY_SKIP:
            yield float(obj)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_numbers(v, str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_numbers(v, key)


def _round_facts(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """本轮工具返回里的**全部**可信数值 + 最后一份统计/点采样事实。

    2026-11-07 第三次复测：原来只认 ``mean`` + ``valid_pixels``，于是
    ``sample_layer_point``（返回 ``samples[].value``，没有像元数）和覆盖查询
    （返回日期清单，没有均值）**完全不在校验范围内**——模型点了位却报个别的
    数、或者查覆盖却编个均值，都拦不住。白名单改成"本轮返回过什么数"，
    校验才谈得上覆盖全部取数工具。
    """
    payloads: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict) or step.get("type") != "tool_result":
            continue
        detail = step.get("detail")
        data: Any = detail if isinstance(detail, dict) else None
        if data is None and isinstance(detail, str) and detail.strip().startswith("{"):
            try:
                data = json.loads(detail)
            except json.JSONDecodeError:
                continue
        if not isinstance(data, dict) or data.get("truncated"):
            continue
        payloads.append(data)

    numbers: set[float] = set()
    stats: dict[str, Any] | None = None
    # 一次问多个变量时会有多份统计（每份一个 variable）。只留最后一份会让
    # 「分别是多少」的其余几项在重建时凭空消失（2026-11-07 实测：SM 与 VOD
    # 都算出来了，重建后只剩 VOD，还带着「以这段为准」把前一项作废）。
    stats_list: list[dict[str, Any]] = []
    sample: dict[str, Any] | None = None
    for data in payloads:
        numbers.update(_iter_numbers(data))
        if data.get("mean") is not None and data.get("valid_pixels") is not None:
            stats = data
            stats_list.append(data)
        if isinstance(data.get("samples"), list):
            sample = data
    # 派生值：正文常写「有效率约 49.7%」「比上一轮低 0.09」，这些数白名单里没有，
    # 不放行就会把正确答案当成编造。只补两类最常见的派生（占比、两数之差），
    # 别的派生一律按未匹配处理——宁可重写得朴素一点，也不放宽到形同虚设。
    derived: set[float] = set()
    if stats:
        try:
            valid = float(stats.get("valid_pixels"))
            total = float(stats.get("total_pixels"))
            if total:
                derived.add(round(valid / total * 100.0, 4))
        except (TypeError, ValueError):
            pass
    pool = list(numbers)[:40]
    for i, left in enumerate(pool):
        for right in pool[i + 1 :]:
            derived.add(round(abs(left - right), 6))
    return {
        "numbers": numbers | derived,
        "stats": stats,
        "stats_list": stats_list,
        "sample": sample,
    }


def _number_matches(value: float, whitelist: set[float]) -> bool:
    """正文里的数与白名单里的数是不是同一个。

    整数按精确值比（1995 与 1996 是两天不同的覆盖，不能算同一个）；
    小数按**3 位有效数字**比——「0.2929 写成 0.293」「0.2025 写成 0.203」都能过
    （2026-11-07 实测：``f"{0.2025324:.3g}"`` 就是 ``0.203``，四舍五入属正常转写，
    原注释把它写成「过不了」是错的）。而「0.293 对 0.2025」这种换了整套数的
    过不了——抄上一轮那类正好卡在这里。
    """
    for ref in whitelist:
        if value.is_integer() and ref.is_integer():
            if value == ref:
                return True
            continue
        if f"{value:.3g}" == f"{ref:.3g}":
            return True
    return False


#: 正文里的小数 + 贴着「像元/栅格」的整数。日期先剥掉，免得 2025-12-16 被当数值。
_DATE_LIKE_RE = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?|\d{8}(?:_\d{8})?")
_DECIMAL_RE = re.compile(r"\d+\.\d+")


def _reply_numbers(text: str) -> set[float]:
    """正文里「像统计结果」的数字。

    只认小数与有效像元/栅格数：``3 层``、``31 天``、``共 13 片`` 这类正常计数
    不参与校验，否则每句话都会被判成"数字对不上"。
    """
    raw = _DATE_LIKE_RE.sub(" ", text or "")
    out: set[float] = set()
    for token in _DECIMAL_RE.findall(raw):
        try:
            out.add(float(token))
        except ValueError:
            continue
    for groups in _PIXEL_MENTION_RE.findall(raw):
        token = (
            groups if isinstance(groups, str) else next((g for g in groups if g), "")
        )
        if not token:
            continue
        try:
            out.add(float(token.replace(",", "")))
        except ValueError:
            continue
    return out


#: 正文里**挂着统计量名**的数值：``平均值 0.203``、``有效像元 1995``。
#: 2026-11-07 第四次复测：只校验这一类。差值与百分比（``比河南低约 0.037``、
#: ``占该市范围约 26%``）是模型自己算的派生数，工具从未返回过，一并强校验会把
#: 正确的对比回答判成编造、整段替换成一句干巴巴的话。
_STAT_VALUE_RE = re.compile(
    # 「平均值 0.203」「平均值是 0.203」「平均值约 **0.203**」
    r"(?:平均值|均值|平均|最大值|最小值|最高值|最低值|最高|最低|标准差|中位数)"
    r"\s*(?:是|为|约|大约|在|[:：])?\s*[*_`]*\s*(\d+(?:\.\d+)?)"
    # 「有效像元 1995」「有效像元：1995」
    r"|(?:有效像元|有效栅格|像元数|栅格数)\s*(?:数)?\s*[:：为是]?\s*(\d[\d,]*)"
    # 「1995 个有效像元」
    r"|(\d[\d,]*)\s*个\s*(?:有效)?(?:像元|栅格)"
)


def _stat_values(text: str) -> set[float]:
    """正文里「必须与本轮取数对上」的那些数。

    只认紧跟在统计量名后面的数，以及贴着「个有效像元/栅格」的整数。日期先剥掉，
    免得 ``平均值 2025-12-16`` 里的年份被当成统计值。
    """
    raw = _DATE_LIKE_RE.sub(" ", text or "")
    out: set[float] = set()
    for groups in _STAT_VALUE_RE.findall(raw):
        token = (
            groups if isinstance(groups, str) else next((g for g in groups if g), "")
        )
        if not token:
            continue
        try:
            out.add(float(token.replace(",", "")))
        except ValueError:
            continue
    return out


#: 「这不是本轮、是在跟上一轮对比」的说法。带这些词的句子允许出现别的区域/
#: 日期/产品名——用户要的正是两轮对照，不能因为提了别的区域就整段重写。
_COMPARE_HINT_RE = re.compile(r"上一轮|上轮|此前|之前|相比|比上一|往期|前一轮|上一次")
_REGION_MENTION_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,6}(?:省|市|自治区|特别行政区|自治州)"
)
_FULL_DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?")
_SHORT_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})月(\d{1,2})日")
_VARIABLE_WORDS: dict[str, tuple[str, ...]] = {
    "sm": ("土壤水分", "土壤湿度", "含水量", "墒情"),
    "vod": ("vod", "植被光学厚度", "光学厚度"),
    "omega": ("ω", "omega", "等效散射"),
}


def _fact_names(facts: dict[str, Any]) -> list[str]:
    names: list[str] = []
    stats = facts.get("stats")
    if isinstance(stats, dict) and stats.get("display_name"):
        names.append(str(stats["display_name"]))
    sample = facts.get("sample")
    if isinstance(sample, dict):
        for item in sample.get("samples") or []:
            if isinstance(item, dict) and item.get("display_name"):
                names.append(str(item["display_name"]))
    return names


def _fact_conflict(text: str, facts: dict[str, Any]) -> str | None:
    """正文说的产品/区域/日期，与本轮工具返回的是不是同一回事。

    这道校验防的是「数值碰巧对、说法却错」：2026-11-07 外部报告里那两条，
    工具查的是河南，正文却写「区域改为广州市」；以及 14:18 那版工具查风云、
    正文写成「广州 SMAP 土壤水分」。数字匹配只看数，抓不到这种张冠李戴。

    只在正文确实报了数值时调用（身份类问答不受影响）；句子里带「上一轮/相比」
    这类对比说法时整体豁免，避免把正常的跨轮对照当成错误。
    """
    if not text or _COMPARE_HINT_RE.search(text):
        return None
    names = _fact_names(facts)
    if not names:
        return None
    low = text.casefold()
    joined = " ".join(names)
    joined_low = joined.casefold()

    fact_sources = {
        s
        for s, words in (("smap", ("smap",)), ("fy", ("风云",)))
        if any(w in joined_low for w in words)
    }
    text_sources = {
        s
        for s, words in (("smap", ("smap",)), ("fy", ("风云",)))
        if any(w in low for w in words)
    }
    if fact_sources and text_sources and not (text_sources & fact_sources):
        return "来源"

    fact_vars = {
        v for v, words in _VARIABLE_WORDS.items() if any(w in joined_low for w in words)
    }
    text_vars = {
        v for v, words in _VARIABLE_WORDS.items() if any(w in low for w in words)
    }
    if fact_vars and text_vars and not (text_vars & fact_vars):
        return "变量"

    stats = facts.get("stats") if isinstance(facts.get("stats"), dict) else {}
    region = str(stats.get("region") or "").strip()
    if region:
        seen = {m.group(0) for m in _REGION_MENTION_RE.finditer(text)}
        if seen and region not in seen:
            return "区域"

    actual = str(stats.get("actual_time") or "").strip()
    if re.fullmatch(r"\d{8}", actual):
        dates = set()
        for y, m, d in _FULL_DATE_RE.findall(text):
            dates.add(f"{int(y):04d}{int(m):02d}{int(d):02d}")
        for m, d in _SHORT_DATE_RE.findall(text):
            dates.add(f"{actual[:4]}{int(m):02d}{int(d):02d}")
        if dates and actual not in dates:
            return "日期"
    return None


def _stats_sentence(
    data: dict[str, Any] | None, *, with_lead: bool = False
) -> str | None:
    """单份整层统计 → 一句话（含层名、范围、时间块、数值、像元数）。

    单位取 ``unit_label``：``unit`` 是机器字段，无量纲写成「1」，直接贴进正文
    就会出现「0.1507 1」这种读不通的写法（2026-11-07 实测）。
    """
    if not isinstance(data, dict):
        return None
    try:
        mean = float(data.get("mean"))
        pixels = int(float(data.get("valid_pixels") or 0))
    except (TypeError, ValueError):
        return None
    name = str(data.get("display_name") or "").strip() or "这一层"
    unit = str(data.get("unit_label") or data.get("unit") or "").strip()
    if unit == "1":
        unit = "无量纲"
    region = str(data.get("region") or "").strip()
    where = f"按「{region}」行政边界" if region else "按整幅栅格"
    actual = str(data.get("actual_time") or "").strip()
    when = ""
    if re.fullmatch(r"\d{8}", actual):
        when = f"{actual[:4]}-{actual[4:6]}-{actual[6:]} "
    elif re.fullmatch(r"\d{8}_\d{8}", actual):
        when = (
            f"{actual[:4]}-{actual[4:6]}-{actual[6:8]} 至 "
            f"{actual[9:13]}-{actual[13:15]}-{actual[15:17]} 的合成块，"
        )
    value = f"{mean:.4g}" + (f" {unit}" if unit else "")
    head = f"我按「{name}」取数：" if with_lead else f"「{name}」"
    return f"{head}{where}，{when}平均值 {value}，有效像元 {pixels} 个。"


def _rebuild_stats_reply(
    data: dict[str, Any] | list[dict[str, Any]] | None,
) -> str | None:
    """按整层统计的工具返回，拼一段只有真事实的回答。

    支持一次多份（用户一句问多个变量/多个区域）：**每一份都要写出来**，
    不许只留最后一份——那等于把用户问的另一半静默丢掉。
    """
    if data is None:
        return None
    items = data if isinstance(data, list) else [data]
    lines = [s for s in (_stats_sentence(d) for d in items) if s]
    if not lines:
        return None
    if len(lines) == 1:
        one = next(
            (s for s in (_stats_sentence(d, with_lead=True) for d in items) if s),
            lines[0],
        )
        return f"{one}\n\n这是按你最后一句说的图层、区域和日期算出来的。"
    body = "\n".join(f"- {line}" for line in lines)
    return (
        f"这一问涉及 {len(lines)} 组数值，逐组列出（每组的图层、范围与时间块"
        f"见各项说明）：\n{body}\n\n"
        "以上都来自本轮取数，各组数值对应各自的图层与时间块，不是同一口径的拆分。"
    )


def _rebuild_sample_reply(data: dict[str, Any] | None) -> str | None:
    """按点采样的工具返回，拼一段只有真事实的回答。"""
    if not isinstance(data, dict):
        return None
    samples = data.get("samples")
    if not isinstance(samples, list):
        return None
    spot = ""
    try:
        spot = f"{float(data['lng']):.4g}°E、{float(data['lat']):.4g}°N "
    except (KeyError, TypeError, ValueError):
        spot = ""
    for item in samples:
        if not isinstance(item, dict) or item.get("value") is None:
            continue
        try:
            value = float(item["value"])
        except (TypeError, ValueError):
            continue
        name = str(item.get("display_name") or "").strip() or "这一层"
        unit = str(item.get("unit") or "").strip()
        actual = str(item.get("actual_time") or item.get("time") or "").strip()
        when = ""
        if re.fullmatch(r"\d{8}", actual):
            when = f"{actual[:4]}-{actual[4:6]}-{actual[6:]}，"
        shown = f"{value:.4g}" + (f" {unit}" if unit else "")
        return (
            f"我按「{name}」重新取了{spot}这个位置：{when}"
            f"该点数值 **{shown}**。\n\n"
            "这一段是按本轮工具返回写的；若与上一版不一致，以这段为准。"
        )
    # 样本全都没值（缺测 / 落在无数据区）：这时正文里的任何数值都没有出处。
    # 与其放它过去，不如照实说没有数——用户要的是能用的数，不是看着像数的数。
    if samples:
        when = str(data.get("time") or "").strip()
        when = f"{when} " if when else ""
        return (
            f"我在{spot}这个位置没有取到有效值：{when}该像元缺测，"
            "或者不落在这一层的有效范围内，所以这里不给数值。\n\n"
            "换一天或换个位置我可以重新取。"
        )
    return None


def _has_cross_round_region(text: str, facts: dict[str, Any]) -> bool:
    """正文是不是在拿「本轮没统计的区域」做对比。

    2026-11-07 实测：用户问「那跟广州市比差多少」，本轮只统计了广州，正文却把
    上一轮的河南一起写出来（0.166 对 0.203，差 0.037）——数值全真，只是河南那组
    不在本轮白名单里。逐个强校验会把这段正确的对比整段换成单边一句话，用户问的
    「差多少」反而没答。命中这里时退回「有一个对上就放行」的旧判据。

    只认「正文提到 2 个以上区域、且其中有本轮没统计的」——一次问两个变量
    （同一个区域）不受影响，那条路径仍然逐个校验。
    """
    mentioned = set(_REGION_MENTION_RE.findall(text or ""))
    if len(mentioned) < 2:
        return False
    known: set[str] = set()
    for row in facts.get("stats_list") or []:
        if isinstance(row, dict) and row.get("region"):
            known.add(str(row["region"]))
    single = facts.get("stats")
    if isinstance(single, dict) and single.get("region"):
        known.add(str(single["region"]))
    return bool(mentioned - known)


def _guard_reply_numbers(reply: str, steps: list[dict[str, Any]]) -> tuple[str, bool]:
    """正文里的数值必须是**本轮**工具返回过的那组，对不上就整段换掉。

    2026-11-07 游客模式复测（第三组「只改区域」）：工具这次查的是广州市，
    正文却写「0.203 / 1995 个，该区域共 4012 个像元」——1995 与 4012 全是
    上一轮**河南**的数字，整段是从历史里抄来的。当时那道闸门
    （``_statistics_fallback_reply``）只问「本轮有没有调过统计工具」，调过就
    放行模型原文，于是抄来的数原样流到用户眼前。

    判据分两层：

    1. 正文里**挂着统计量名**的数（平均值/均值/最大/最小/标准差/有效像元）——
       **每一个**都必须能对上本轮工具返回过的数，有一个对不上就整段重写。
       只要求「任意一个对上就放行」曾被一次问两个变量骗过：土壤水分写错
       （0.293/163，其实是 12-15 的值）、VOD 写对，整段被 VOD 掩护着流出去，
       用户拿到一半真一半假（2026-11-07 第四次复测实测）。
    2. 正文里没有统计量名时（身份问答、只讲范围）退回旧判据：只要有一个数
       对上就算本轮写的（两轮对比会同时出现两组数，那种不拦）。一个都对不上
       ⇒ 正文与本次取数无关，按工具返回重写。

    差值与百分比不参与第 1 层校验——``比河南低约 0.037``、``占约 26%`` 是模型
    自己算的派生数，工具从没返回过，一刀切会把正确的对比回答判成编造。
    """
    text = reply or ""
    if not text:
        return reply, False
    facts = _round_facts(steps)
    whitelist: set[float] = facts["numbers"]
    if not whitelist:
        return reply, False
    mentioned = _reply_numbers(text)
    if not mentioned:
        return reply, False
    # 2026-11-07 第四次复测：原来只要求「任意一个数对上就整段放行」，于是
    # 「土壤水分 0.293/163（错，0.293/163 其实是 12-15 的值）+ VOD 0.151/1340（对）」
    # 被 VOD 那两个正确数掩护过关，用户拿到一半真一半假——问「分别是多少」时
    # 最容易被骗过。改成：**每个挂着统计量名的数都必须对得上**。
    # 正文里没有统计量名（身份问答、只讲范围）时退回旧判据，不扩大误伤面。
    #
    # 跨轮对比是例外：用户问「那跟广州市比差多少」时，本轮只统计了广州，
    # 正文会把上一轮的河南一起写出来比（0.166 对 0.203，差 0.037）——数值全真，
    # 只是河南不在本轮白名单里。逐个强校验会把这段正确的对比整段打掉，
    # 换成一句只有广州的话，用户问的「差多少」反而没答。
    stat_values = _stat_values(text)
    if stat_values and not _has_cross_round_region(text, facts):
        numbers_ok = all(_number_matches(value, whitelist) for value in stat_values)
    else:
        numbers_ok = any(_number_matches(value, whitelist) for value in mentioned)
    # 数值对得上还不够：正文可能把这一层说成另一颗卫星/另一个区域/另一天。
    # 只在报了数值时查（身份类问答会被误伤），带「上一轮/相比」的整句豁免。
    conflict = _fact_conflict(text, facts)
    if numbers_ok and not conflict:
        return reply, False
    # 多份统计全部带上：一次问多个变量时只重建最后一份，会把用户问的其余项吞掉
    rebuilt = _rebuild_stats_reply(
        facts.get("stats_list") or facts["stats"]
    ) or _rebuild_sample_reply(facts["sample"])
    if not rebuilt:
        return reply, False
    logger.warning(
        "reply not grounded in this round: numbers_ok=%s conflict=%s mentioned=%s",
        numbers_ok,
        conflict,
        sorted(mentioned)[:6],
    )
    return rebuilt, True


def _looks_numeric(text: str) -> bool:
    """正文里是否出现了「像统计结果」的数字。

    判据刻意收窄：只认**小数**（0.148、0.0597）和**贴着统计量名**的整数
    （「有效像元 1024」「均值 12」）。这样「3 层」「31 天」「共 13 片」这类
    正常计数不会被误判成统计值，否则兜底会把好好的回答换成一句「未取到」。
    """
    raw = str(text or "")
    # 先摘掉日期形态，避免把 2025-11-13 / 20251109_20251116 当成统计值
    raw = re.sub(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?", " ", raw)
    raw = re.sub(r"\d{8}(?:_\d{8})?", " ", raw)
    if re.search(r"\d+\.\d+", raw):
        return True
    if re.search(r"(均值|平均值|有效像元|有效栅格)[^。；\n]{0,14}?\d", raw):
        return True
    if re.search(r"\d[^。；\n]{0,8}?(个有效像元|个有效栅格|个栅格)", raw):
        return True
    return False


def _grounded_statistics(text: str) -> bool:
    """规则引擎的答复是不是「真算过数」（它只在取数成功时会写这些词）。"""
    return any(k in text for k in ("均值", "有效像元", "有效栅格"))


def _statistics_fallback_reply(
    message: str,
    reply: str,
    steps: "_EventSteps",
    sid: str,
    client_context: dict[str, Any] | None,
    *,
    state: dict[str, str] | None = None,
) -> tuple[str, dict[str, str] | None]:
    r"""统计请求的确定性兜底：模型没调过任何取数工具时，正文里的数字一律不可信。

    报告第二轮 P1：「统计请求即使包含『当前图层』也不能只列图层或说明计划，
    核对来源、变量与日期后继续调用 get_layer_statistics，直到得到结果或明确报错」。
    真模型对「当前选中图层」这类模糊主语约束力弱，光靠系统提示不可靠；
    提示词已写死规则（## 整层统计），这里再加一道代码闸门。
    **只补文本，不下发任何改变视图的意图。**

    ★ 2026-11-04 重写（外部测试报告第 1 条「数值查询必须调用统计工具」）：
    旧实现在 ``_wants_statistics`` 命中后还有两道早退——

        if "均值" in reply: return reply
        if "取数" in reply or re.search(r"\d+\.\d+", reply): return reply

    第二道本意是「别用规则引擎覆盖正确答案」（10-29 赵测过：模型已取数时被
    覆盖成页面选中层的数字）。但「有小数」恰好也是**编造答案**的特征：
    11-04 实测模型没调任何工具，直接报「0.148 m³/m³、1024 个有效栅格」，
    而那个时间片全球有效像元是 0 ⇒ 编造的数字被当成了「已取数」放行。

    现在的判据改成**看有没有工具调用，而不是看正文长什么样**：
      1. 本轮调过 get_layer_statistics / coverage / meta ⇒ 尊重模型原文；
      2. 一次都没调过 ⇒ 规则引擎真算出数就整段替换，算不出来就把正文里
         的数值换成一句如实的「未取到」，绝不让无出处的数字流出去。
    """
    if not _wants_statistics(message) or _statistics_tool_called(list(steps)):
        return reply, None
    try:
        # 直接进统计分支，不走关键词分流：「是多少」这类说法不在 _STAT_VERB 里，
        # 经 mock_chat 会被当成普通对话，返回一段能力介绍，救不了场。
        from app.services.agent.mock_orchestrator import forced_statistics_reply

        fallback = forced_statistics_reply(
            message,
            client_context=client_context,
            session_id=sid,
            state=state,
        )
    except Exception:
        logger.debug("statistics fallback failed", exc_info=True)
        return _UNGROUNDED_REPLY if _looks_numeric(reply) else reply, None
    patch = fallback.get("topic_state") if isinstance(fallback, dict) else None
    topic_patch = dialogue_state.sanitize(patch) if patch else None
    text = str(fallback.get("reply") or "").strip()
    if text and _grounded_statistics(text):
        steps.append(
            {
                "type": "tool_result",
                "summary": "服务端强制取数（模型本轮未调用任何数据工具）",
                "detail": text[:800],
            }
        )
        return text, topic_patch
    # 规则引擎也算不出来：模型若给了数字，就是无出处的，必须收回
    if _looks_numeric(reply):
        steps.append(
            {
                "type": "tool_result",
                "summary": "已拦截无出处的数值（本轮未调用任何数据工具）",
                "detail": (text or "规则引擎未得到有效统计结果")[:400],
            }
        )
        return _UNGROUNDED_REPLY, None
    return reply, None


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
    # 本会话「已确认的取数对象」（图层 / 变量 / 区域 / 日期）。
    # 跨轮追问的唯一事实源：没有它，「其余不变」「只改日期」只能靠页面选中层猜，
    # 兜底补算也只能拿页面当前层 + 全幅顶上（2026-11-06 定位结论）。
    topic_state = load_topic_state(user_id=user_id, session_id=sid)
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
    # 读回时也压一次：老会话里在「压缩优化」之前写入的完整回答仍躺在磁盘上，
    # 只压 append_turn 救不了它们；这里对 assistant 内容再做一次截断，模型输入与
    # 预算估算走压缩版，前端展示（get_session_messages）不受影响。
    history = [
        {
            **m,
            "content": (
                _compress_history_reply(m["content"])
                if m.get("role") == "assistant"
                else _compress_history_user(m["content"])
            ),
        }
        for m in history
    ]
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
                    "detail": _tool_detail(tool_res),
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
                        "detail": _tool_detail(wf_res),
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
                    "detail": _tool_detail(sample_res),
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
                        "detail": _tool_detail(lm),
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
                    "detail": _tool_detail(lw),
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
                        "detail": _tool_detail(wm),
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
                    "detail": _tool_detail(ws),
                }
            )

        result = mock_chat(
            message, session_id=sid, client_context=client_context, state=topic_state
        )
        reply = str(result["reply"])
        topic_state = dialogue_state.merge(
            topic_state, **(result.get("topic_state") or {})
        )
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
            reply = f"（已结合此前 {len(history) // 2} 轮对话）\n{reply}"
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
            user_message=_compress_history_user(message),
            assistant_message=_compress_history_reply(reply),
            state=topic_state,
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

    # 用户这句话自己点名的对象，先落进会话状态：模型这一轮可能一次工具都不调
    # （复述历史就答了），那条路否则一个字都不会记。
    topic_state = dialogue_state.merge(
        topic_state,
        **_state_patch_from_message(message, client_context, topic_state),
    )

    system = _build_system(client_context, cred=cred, topic_state=topic_state)
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
            "**地图本身不受影响**：底图、图层、时间轴、点查都能正常用。\n\n"
            "这一问多半要连着查几步（定位图层 → 核对日期 → 统计），可以少走一步：\n"
            "1. 先在左侧把要问的那一层点上（让它成为当前选中的层），"
            "再问「这一层 2025-12-15 广州市平均是多少」；\n"
            "2. 或者拆成两句问：先问「哪一层是 XX 产品」，拿到层名后再单独问数值。"
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
        # 助手侧只存一行：超限提示本身有几百字，存完整版会让「失败→历史变肥→
        # 下次更容易失败」形成雪球（2026-10-29 实测 20030→20709→20704 就是它）。
        append_turn(
            user_id=user_id,
            session_id=sid,
            user_message=_compress_history_user(message),
            assistant_message="（上一轮提问超出单次输入预算，已中止，未取数）",
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
            "detail": f"protocol={protocol} history_turns={len(history) // 2}",
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
            # 本轮「工具真正读到的那一层」：一旦有值，界面意图就不再改写基线
            # （意图里的 catalog_id 是模型的请求参数，可能已被粘性纠正掉）。
            tool_layer_state: dict[str, str] = {}
            max_hops = _max_tool_hops()
            for hop in range(1, max_hops + 1):
                all_uses = _anthropic_tool_uses(data.get("content"))
                if not all_uses:
                    break
                # 产品粘性的判定基准必须是**这一跳之前**的会话基线。
                # 2026-11-07 实测：下面那句 merge 会把模型这一跳选的 catalog_id
                # 写进 topic_state，随后 execute_server_tool 拿到的「上一轮是谁」
                # 已经被本次选择覆盖 ⇒ 粘性看到 base == req，直接放行，「只改日期」
                # 照样落到页面选中层。所以先快照，再 merge。
                pre_call_state = topic_state
                # 模型查过哪一层 = 这一轮的对象，记进会话状态（否则下一句追问只能靠页面猜）
                topic_state = dialogue_state.merge(
                    topic_state,
                    **_state_patch_from_tool_calls(all_uses, client_context),
                )
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
                        # 用户原话交给工具侧的跨来源守卫：判断他有没有点名换卫星
                        user_message=message,
                        # 会话里记着的取数对象：没点名时优先用它，别拿页面选中层顶替。
                        # 传快照而不是 topic_state —— 后者已被本次模型选择覆盖。
                        topic_state=pre_call_state,
                    )
                    steps.append(
                        {
                            "type": "tool_result",
                            "summary": "待确认"
                            if tres.get("needs_confirmation")
                            else "工具返回",
                            "detail": _tool_detail(tres),
                        }
                    )
                    conf = _confirmation_from_tool_result(tres)
                    if conf:
                        confirmations.append(conf)
                    # 工具实际读的是哪份产物 ⇒ 立刻写进会话基线（见函数注释）
                    tool_patch = _state_patch_from_tool_results([tres])
                    if tool_patch:
                        tool_layer_state = tool_patch
                    topic_state = dialogue_state.merge(topic_state, **tool_patch)
                    tool_result_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": sc["id"],
                            "content": json.dumps(tres, ensure_ascii=False),
                        }
                    )
                server_calls = [c for c in all_uses if c["name"] in _SERVER_TOOLS]
                _shrink_old_tool_results(messages)
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
                    # 合并而不是覆盖：复合指令里第一跳的「显示某层」不能被第二跳顶掉
                    intents = _merge_intents(intents, intents2)
            if server_calls:
                steps.append(
                    {
                        "type": "thought",
                        "summary": f"已达工具跳上限 {max_hops}，停止继续调用工具",
                    }
                )
                # 同一处收尾也接上（本机跑 DeepSeek 不走这条，但两条分支行为不能
                # 再分叉——2026-11-07 就因为只改一路，守卫整轮没生效）。这里不额外
                # 发模型请求，直接用确定性合成兜底。
                _final = _finalize_after_hop_limit(reply, list(steps))
                if _final != reply:
                    reply = _final
                    steps.append(
                        {
                            "type": "thought",
                            "summary": "跳数用尽，已按已有工具结果补答",
                        }
                    )

            if not reply and not intents:
                reply = "（模型未返回文本）"
            reply = _ensure_visible_reply(reply, list(steps))
            reply, state_patch = _statistics_fallback_reply(
                message, reply, steps, sid, client_context, state=topic_state
            )
            if state_patch:
                topic_state = dialogue_state.merge(topic_state, **state_patch)
            # 正文数值必须来自本轮工具返回（模型会把上一轮的数字整段抄下来）
            reply, _numbers_rebuilt = _guard_reply_numbers(reply, list(steps))
            if _numbers_rebuilt:
                steps.append(
                    {
                        "type": "thought",
                        "summary": "正文数值与本轮取数对不上，已按工具返回重写",
                    }
                )
            if not intents:
                fallback = mock_chat(
                    message,
                    session_id=sid,
                    client_context=client_context,
                    state=topic_state,
                )
                if fallback.get("ui_intents"):
                    intents = fallback.get("ui_intents") or []
            topic_state = dialogue_state.merge(
                topic_state,
                **_state_patch_from_intents(
                    intents, client_context, keep_layer=bool(tool_layer_state)
                ),
            )
            usage = usage_from_anthropic(
                data, prompt_fallback=system + message, completion_fallback=reply
            )
            append_turn(
                user_id=user_id,
                session_id=sid,
                user_message=_compress_history_user(message),
                assistant_message=_compress_history_reply(reply),
                state=topic_state,
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
        # 同 Anthropic 分支：工具真正读到的那一层，界面意图不许再改
        tool_layer_state: dict[str, str] = {}
        max_hops = _max_tool_hops()
        oai_key = api_key or ("ollama" if provider_kind == "ollama" else None)

        for hop in range(1, max_hops + 1):
            if not calls:
                break
            hops_used = hop
            # 同 Anthropic 分支：先快照这一跳之前的基线，再做 merge。
            # 否则粘性拿到的是「本次模型自己选的层」，判定必然放行。
            pre_call_state = topic_state
            # 同 Anthropic 分支：模型查过的层要记进会话状态
            topic_state = dialogue_state.merge(
                topic_state, **_state_patch_from_tool_calls(calls, client_context)
            )
            steps.append(
                {
                    "type": "thought",
                    "summary": f"工具跳 {hop}/{max_hops}",
                }
            )
            _shrink_old_tool_results(messages_oai)
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
                    # 用户原话交给工具侧的跨来源守卫：判断他有没有点名换卫星。
                    # 2026-11-07 实测补上：上一版只在 Anthropic 那一路传了，DeepSeek
                    # （OpenAI 兼容路径）漏传 ⇒ 守卫拿到空原话直接放行，等于没装。
                    user_message=message,
                    # 会话里记着的取数对象：没点名时优先用它（页面选中层只作兜底）。
                    # 传快照，不能用已被本次选择覆盖的 topic_state。
                    topic_state=pre_call_state,
                )
                steps.append(
                    {
                        "type": "tool_result",
                        "summary": "待确认"
                        if tres.get("needs_confirmation")
                        else "工具返回",
                        "detail": _tool_detail(tres),
                    }
                )
                conf = _confirmation_from_tool_result(tres)
                if conf:
                    confirmations.append(conf)
                # 同上：把「真正读的产物」记成基线，下一句「只改区域」才粘得住
                tool_patch = _state_patch_from_tool_results([tres])
                if tool_patch:
                    tool_layer_state = tool_patch
                topic_state = dialogue_state.merge(topic_state, **tool_patch)
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
                intents = _merge_intents(intents, more_intents)
            server_calls = _server_calls(calls)

        if server_calls:
            steps.append(
                {
                    "type": "thought",
                    "summary": f"已达工具跳上限 {max_hops}，停止继续调用工具",
                }
            )
            # 跳到上限时模型只留下开场白（实测 27 字）或搜索结果列表（66 字），
            # 这里补一次不带工具的收尾，逼它用已经拿到的结果作答。
            _final = _finalize_after_hop_limit(
                reply,
                list(steps),
                complete=lambda: _oai_complete_no_tools(
                    base_url=base_url,
                    api_key=oai_key,
                    model=model,
                    messages=messages_oai,
                    max_tokens=max_out,
                ),
            )
            if _final != reply:
                reply = _final
                steps.append(
                    {
                        "type": "thought",
                        "summary": "跳数用尽，已按已有工具结果补答",
                    }
                )

        if not reply and not intents:
            reply = "（模型未返回文本）"
        reply = _ensure_visible_reply(reply, list(steps))
        reply, state_patch = _statistics_fallback_reply(
            message, reply, steps, sid, client_context, state=topic_state
        )
        if state_patch:
            topic_state = dialogue_state.merge(topic_state, **state_patch)
        # 同 Anthropic 分支：正文里的数必须是这一轮取到的那组
        reply, _numbers_rebuilt = _guard_reply_numbers(reply, list(steps))
        if _numbers_rebuilt:
            steps.append(
                {
                    "type": "thought",
                    "summary": "正文数值与本轮取数对不上，已按工具返回重写",
                }
            )
        if not intents:
            fallback = mock_chat(
                message,
                session_id=sid,
                client_context=client_context,
                state=topic_state,
            )
            heur = fallback.get("ui_intents") or []
            if heur:
                intents = heur
        topic_state = dialogue_state.merge(
            topic_state,
            **_state_patch_from_intents(
                intents, client_context, keep_layer=bool(tool_layer_state)
            ),
        )
        usage = usage_from_openai(
            data,
            prompt_fallback=system + message,
            completion_fallback=reply,
        )
        append_turn(
            user_id=user_id,
            session_id=sid,
            user_message=_compress_history_user(message),
            assistant_message=_compress_history_reply(reply),
            state=topic_state,
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


def _steps_layer_and_day(steps: list[dict[str, Any]]) -> tuple[str, str]:
    """从本轮工具返回里读出「实际读了哪份产物」与「实际命中的单日」。

    只认 ``period_start == period_end`` 的窄口径（单日 / 单日帧）：那是用户说
    「按 X 日算」时工具真正落到的帧。月块 / 多年平均不参与，否则一句
    「2025 年整年平均」会把时间轴莫名其妙切到某一天。
    """
    layer_id = ""
    day = ""
    for st in steps:
        if not isinstance(st, dict) or st.get("type") != "tool_result":
            continue
        raw = st.get("detail")
        if not isinstance(raw, str):
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict) or not data.get("ok"):
            continue
        cid = str(data.get("resolved_layer_id") or data.get("catalog_id") or "").strip()
        if cid.startswith(("imported-", "wf-run-")):
            layer_id = cid
        ps = str(data.get("period_start") or "").strip()
        pe = str(data.get("period_end") or "").strip()
        if len(ps) == 8 and ps == pe and ps.isdigit():
            day = f"{ps[:4]}-{ps[4:6]}-{ps[6:]}"
    return layer_id, day


def _catalog_of_overlay(client_context: dict[str, Any] | None, overlay_id: str) -> str:
    """产物 id → 页面上那一层的 catalog_id（前端按 catalog_id 认目标层）。"""
    if not overlay_id or not isinstance(client_context, dict):
        return ""
    layers = client_context.get("active_layers")
    if not isinstance(layers, list):
        return ""
    for item in layers:
        if not isinstance(item, dict):
            continue
        if str(item.get("overlay_layer_id") or "").strip() == overlay_id:
            return str(item.get("catalog_id") or "").strip()
    return ""


#: 会改变「当前在看哪一层」的意图，必须排在时间轴之前
_LAYER_CHANGE_INTENTS = ("set_layer_visibility", "remove_layer", "reorder_layer")
#: 时间轴意图：图层集合定下来之后再执行
_DAY_INTENTS = ("set_timeline",)
_PLAY_INTENTS = ("set_timeline_playing",)


def _intent_rank(name: str) -> int:
    if name in _LAYER_CHANGE_INTENTS:
        return 0
    if name in _DAY_INTENTS:
        return 2
    if name in _PLAY_INTENTS:
        return 3
    return 1


def _order_ui_intents(
    result: dict[str, Any], client_context: dict[str, Any] | None
) -> dict[str, Any]:
    """把这一批界面意图排成「先切层、再切日期」，并把日期对齐到实际取数那天。

    2026-11-07 游客实测（组合指令）：「切到 SMAP 动态 SM、按 12-16 算均值」——
    图层和数值都对，页面却停在 7 月 31 日。原因是三条意图按模型给的顺序下发：

    1. ``set_layer_visibility`` 一执行，前端时间轴会**按图层记忆**跳到该层上次
       停留的那一帧（那是既有设计，见 useTimelineSync）。谁排在它前面，谁被冲掉。
    2. 兜底/模型有时干脆只下发切层、不下发 ``set_timeline``，页面自然停在记忆帧，
       而正文说的却是 12-16 的统计值 —— 页面与数据对不上。

    所以在出口统一做两件事：按依赖排序；本轮既切了层、又出了单日数值时，补一条
    ``set_timeline`` 指向那天（已有则改正），让页面停的帧与回答里的日期一致。
    只动意图，不碰任何统计口径。
    """
    try:
        if not isinstance(result, dict):
            return result
        intents = result.get("ui_intents")
        if not isinstance(intents, list) or not intents:
            return result
        items = [x for x in intents if isinstance(x, dict)]
        if not items:
            return result
        # 稳定排序：同组内保持模型给的顺序
        items = sorted(items, key=lambda it: _intent_rank(str(it.get("name") or "")))

        shown: list[str] = []
        for it in items:
            if str(it.get("name") or "") != "set_layer_visibility":
                continue
            args = it.get("args") if isinstance(it.get("args"), dict) else {}
            if args.get("visible") is False:
                continue
            cid = str(args.get("catalog_id") or "").strip()
            if cid:
                shown.append(cid)
        # 切层之后要保持「看着的那一层」是最后显示的那层
        target_catalog = shown[-1] if shown else ""

        layer_id, day = _steps_layer_and_day(
            [s for s in (result.get("steps") or []) if isinstance(s, dict)]
        )
        if layer_id:
            actual = _catalog_of_overlay(client_context, layer_id)
            if actual and (not target_catalog or actual == target_catalog):
                target_catalog = actual
            elif actual and target_catalog and actual != target_catalog:
                # 切的是 A、算的是 B：不擅自把时间轴钉到 B 那天
                target_catalog = ""

        day_items = [i for i in items if str(i.get("name") or "") == "set_timeline"]
        if shown and day:
            if day_items:
                keep = day_items[-1]
                args = keep.get("args") if isinstance(keep.get("args"), dict) else {}
                old = str(args.get("date") or "").strip()[:10]
                if old != day:
                    args = dict(args)
                    args["date"] = day
                    keep["args"] = args
                    logger.info(
                        "agent.intent.timeline_aligned from=%s to=%s layer=%s",
                        old or "-",
                        day,
                        target_catalog or "-",
                    )
                if target_catalog and not str(args.get("catalog_id") or "").strip():
                    args = dict(args)
                    args["catalog_id"] = target_catalog
                    keep["args"] = args
                # 只留最后一条：多条 set_timeline 会互相覆盖，页面最终停在哪天不可控
                for extra in day_items[:-1]:
                    items.remove(extra)
            else:
                args = {"date": day}
                if target_catalog:
                    args["catalog_id"] = target_catalog
                items.append({"name": "set_timeline", "args": args})
                items = sorted(
                    items, key=lambda it: _intent_rank(str(it.get("name") or ""))
                )
                logger.info(
                    "agent.intent.timeline_added date=%s layer=%s",
                    day,
                    target_catalog or "-",
                )
        result["ui_intents"] = items
    except Exception:  # pragma: no cover - 排序失败不该影响对话
        logger.debug("order ui intents failed", exc_info=True)
    return result


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
            _order_ui_intents(
                _run_chat_impl(
                    message,
                    session_id=session_id,
                    client_context=client_context,
                    user_id=user_id,
                    cred=cred,
                    on_event=on_event,
                ),
                client_context,
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
