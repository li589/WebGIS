"""Agent chat orchestrator — memory, tools, demo/LLM paths, CoT steps."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime
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


class AgentRequestLimitError(RuntimeError):
    """The request exceeded an internal per-turn budget; the model is not down."""


def _max_tool_hops() -> int:
    """Bounded multi-hop tool rounds (Phase C). Env: BACKEND_AGENT_MAX_TOOL_HOPS."""
    raw = os.getenv("BACKEND_AGENT_MAX_TOOL_HOPS", "4")
    try:
        return max(1, min(8, int(raw)))
    except (TypeError, ValueError):
        return 4


def _total_timeout_seconds() -> float:
    """整轮对话总超时（秒）。Env: ``BACKEND_AGENT_TOTAL_TIMEOUT``，0 表示关闭。

    单次模型调用已有 ``BACKEND_AGENT_LLM_TIMEOUT``（默认 30s），但一次对话可能
    多跳工具（默认 4 跳），每跳各调一次模型，最坏 120s。这道总闸给「整轮」一个
    上限：超过就停止继续取数、按已有结果收尾，避免用户无限等下去。
    """
    raw = os.getenv("BACKEND_AGENT_TOTAL_TIMEOUT", "120")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 120.0
    if value <= 0:
        return 0.0
    return max(15.0, min(600.0, value))


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
        # 对外不提 token / 上限 / 步骤数 / 工具名——那是内部机制，用户只需要
        # 「怎么问才能出数」。旧文案讲了「累计输入超过单次上限」还教用户去左侧点选
        # 图层省步骤，实测把用户带进系统内部视角，且依然拿不到答案。
        return (
            "这次没算成，跟数据无关：这一问要逐个区域分别取数，一轮接一轮算下来"
            "超出了单次能处理的量，中途停下了。\n\n"
            "**地图本身不受影响**：底图、图层、时间轴、点查都能正常用。\n\n"
            "把范围收窄一点就能出数：\n"
            "1. 需要几个区域对比时，**一次点名 2~3 个**，比如"
            "「河南、山东、河北的土壤水分平均值分别是多少」，我一次算完；\n"
            "2. 或者先问一个省，拿到数再接着问下一个。"
        )
    # 余额不足（402）必须单独分流：它的报错里带「HTTP 402」，会被下面
    # _friendly_tool_error 的 HTTP 状态码兜底翻成「取数服务暂时不可用」——
    # 2026-11-08 实测就撞到这一条，用户看到「取数服务不可用」会去查存储/网关，
    # 而真正要做的是给模型账号充值。它跟取数链路一点关系都没有。
    if re.search(r"insufficient[_ ]?balance|余额不足|\b402\b", detail or "", re.I):
        return (
            "地图助手这次没答，跟数据无关：**模型服务的账号余额用完了**——"
            "服务端回的是「余额不足」，所以连问题都没送到模型那里。\n\n"
            "**地图本身不受影响**：底图、图层、时间轴、点查都能正常用；"
            "已算过的数也不会变。\n\n"
            "恢复办法只有一个：到模型服务商控制台把余额补上，不用改任何配置，"
            "充完下一条提问就能正常答。"
        )
    hint = _friendly_tool_error(detail) or "模型服务没有响应"
    return (
        f"地图助手这次没连上模型服务：{hint}。\n\n"
        "**地图不受影响**：底图、图层、时间轴、点查都能正常用。\n\n"
        "可以稍后重试，或在「设置 → Agent 配置」里换一个模型 / 换成「演示（无网）」。"
    )


def _request_limit_reply() -> str:
    return "这次请求内容较多，没能完整处理。请把操作拆成两句话后再试。"


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


#: 工具入参里代表「图层」的字段名（不同工具叫法不同）
_LAYER_ARG_KEYS = ("catalog_id", "layer_id", "dataset_id")


def _requested_layer_from_args(args: dict[str, Any]) -> str:
    for key in _LAYER_ARG_KEYS:
        val = str((args or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _tool_step_summary(name: str, args: dict[str, Any], result: Any = None) -> str:
    """渲染「执行流程」里那一条工具调用记录。

    2026-11-09 实测（外部反馈「传参有误」）：旧写法逐字记 ``模型传进来的 args``，
    而工具内部会**改写** catalog_id —— 产品粘性把请求改回会话基线那层、目录层 id
    （``method-*``）映射成 ``imported-*`` 产物。改写结果只写在返回体里，从不回写
    记录 ⇒ 记录里的层号可以根本不是真正读的那一层。用户看到的「图层编号填成了
    风云产品」就是这么来的：数值是对的，执行记录在骗人。

    所以有返回体时，把**实际取数层**补在同一行（请求 == 实际就不补，免得刷噪音）。
    风云动态与 SMAP 动态在广州市的量级几乎一样（0.1506/68 vs 0.1482/69），
    光看数字根本分不出串没串，只有这一行能让用户当场核对。
    """
    base = f"{name}({json.dumps(args or {}, ensure_ascii=False)[:80]})"
    if not isinstance(result, dict):
        return base
    actual = str(
        result.get("resolved_layer_id") or result.get("catalog_id") or ""
    ).strip()
    if not actual:
        return base
    requested = _requested_layer_from_args(args)
    if requested and requested == actual:
        return base
    display = str(result.get("display_name") or "").strip()
    label = f"（{display}）" if display else ""
    if not requested:
        return f"{base} → 实际取 {actual}{label}（会话沿用）"
    reason = "按会话产品" if result.get("layer_source") == "session" else "目录层映射"
    return f"{base} → 实际取 {actual}{label}（{reason}）"


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


_READ_ONLY_DATA_TOOL_NAMES = frozenset(
    {
        "search_layers",
        "get_layer_meta",
        "get_layer_coverage",
        "get_layer_statistics",
        "sample_layer_point",
    }
)


def _tools_openai_for_message(message: str) -> list[dict[str, Any]]:
    """Avoid resending unrelated write/workflow schemas on read-only data turns."""

    tools = _all_tools_openai()
    if not _wants_statistics(message):
        return tools
    return [
        item
        for item in tools
        if str((item.get("function") or {}).get("name") or "")
        in _READ_ONLY_DATA_TOOL_NAMES
    ]


def _tools_anthropic_for_message(message: str) -> list[dict[str, Any]]:
    tools = _all_tools_anthropic()
    if not _wants_statistics(message):
        return tools
    return [
        item
        for item in tools
        if str(item.get("name") or "") in _READ_ONLY_DATA_TOOL_NAMES
    ]


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
    # 时间轴日期 ≠ 今天。模型会把 client_context.timeline.date 当成「今天」报出去
    # （2026-11-07 实测 N：问「今天几号」，答「今天是 2025-12-16」——那只是用户
    # 正在看的那一帧）。真实日期由服务端给，别让它自己猜。
    try:
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001 - 取不到就不写，不因一句时间让整轮挂掉
        today = ""
    if today:
        parts.append(
            "## 真实日期\n"
            f"- 今天是 **{today}**（服务器本地时间）。\n"
            "- `client_context.timeline.date` 是用户**正在看的这一帧**，不是今天。"
            "被问「今天 / 现在 / 几号」时用上面这个真实日期，并把时间轴停在哪天单独说清，"
            "不许把时间轴日期说成今天。"
        )
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
        "- **但用户明确点名口径或来源时必须换**（「改用平均版 / 换动态版 / 切成季均 / "
        "换成风云那套 / 要 SMAP 的」）：他点名的这一项**优先于「沿用上一轮」，也优先于"
        "上面那条「不要重新挑」**，立刻切到他点名的那一支重新取数，并在正文写明"
        "「这次改用 X 版」。判不准是不是点名时，宁可照他字面换——换了会说明，"
        "不换就是把上一版的数据当成这一版报给他。\n"
        "- **换版本后必须重新取数**：不许把上一版的数字照着念一遍改成新版的名字，"
        "也不许因为新版在某天没有有效像元，就悄悄退回旧版出数。新版取不到就如实说"
        "取不到，并说明这一版的时间口径（单日帧 / 多日块）。\n"
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
        "- **「换成 / 切到 / 换回 / 切回 + 产品名或版本」是换画面，不只是换数**"
        "（「换成动态版」「换回平均版」「切到风云那套」）：除了按新层取数，必须同时下发"
        "`set_layer_visibility` 把该层显示出来（同变量的其他层会让位），并在正文写"
        "「已下发显示 X」。**不许只在后台换数、再把「要显示的话告诉我」丢回给用户**——"
        "他已经说过了。2026-11-08 实测 r73/r74 各一次：「换成动态版，然后算广州市 11 月"
        "13 日的平均」，数据算对了（0.148 / 69 像元），但地图上还是原来那层，用户得再说"
        "一遍。\n"
        "- **「切回 / 切到 / 换回 / 显示 + 图层名或变量名」同样算换画面**（「切回土壤水分"
        "图层」「把土壤水分显示出来」「切到 VOD 那层」）：「土壤水分」「VOD」「ω」这类"
        "**变量/图层名**出现在切回/切到/显示这类动词后面时，也是要画面跟着切，"
        "不是只问数值。取数之外同样下发 `set_layer_visibility` 显示该层，正文写"
        "「已下发显示 X」。2026-11-09 实测：说「切回土壤水分图层」却只后台统计、"
        "画面仍停在 CMFD 降水，用户以为切换没生效。\n"
        "  仍区分「改用 / 用 X 算」：那只是换取数口径，画面不动。\n"
        "- **「只显示 / 只留 / 仅显示 / 单独显示 + 图层名或变量名」要传 `solo`**"
        "（「只显示土壤水分图层」「只留这一层」）：用户说了「只 / 仅 / 单独」，是要"
        "**清场**，除目标层外全部收起，不是普通加一层。下发 "
        "`set_layer_visibility(catalog_id=<id>, visible=true, solo=true, display_name=<名>)`，"
        "正文写「已只显示 X，其余图层已收起」。不带 `solo` 时前端只收起**同变量**的"
        "其他层，别的产品组照旧，用户看到的不是「只显示」。目标层名/变量名能唯一定位"
        "时就**直接下发**，不要再反问「要哪一个」——除非真存在多个无法区分的候选。\n"
        "- **「切换图层到 X 日期 / 把 X 图层切到某天」**（「图层」后面跟日期）："
        "这是**换画面**，不是只问数值。要同时做两件事：① 若目标图层不在 "
        "client_context.active_layers 里，先用 search_layers 找到它并下发 "
        "`set_layer_visibility(catalog_id=<id>, visible=true)` 把它勾选显示出来；"
        "② 再下发 `set_timeline(date=...)` 把时间轴切过去。**只切时间轴不勾选图层、"
        "或只回「要显示的话告诉我」都是错的**。若用户没点名哪个图层、"
        "client_context.active_layers 里也没有可对应的图层，就明确问「要切哪一层到这天」，"
        "**不许静默拿会话上一轮的取数对象当目标**——那会把别的图层的时间轴切了，"
        "用户看到的画面跟说的对不上。（2026-11-10 线上实测：「切换图层到 12 月 15 日」"
        "被静默按上一轮的 SMAP 切了时间轴，且没勾选任何图层。）\n"
        "## 界面意图回执是「已下发」，不是「已执行」\n"
        "- 下发 set_layer_visibility / set_timeline / remove_layer / set_layer_symbology "
        "后，工具回执只表示**已交给浏览器**（executed=false）。此时正文只能写"
        "「已下发 / 已提交」，**不许写「已显示 / 已切换成功 / 已完成」**。\n"
        "- **也不许写「等待执行 / 稍后执行 / 正在执行」**：界面意图在你回复结束后"
        "由浏览器**立即**执行，不存在等待状态。要下发就下发，做不了就明说做不了，"
        "不要用悬置说法把结果挂起来。（2026-11-09 外部实测：正文停在「等待执行」，"
        "成败只出现在下方回执，用户不知道操作到底做没做。）\n"
        "- **宣称了就必须下发**：正文里说「已发出切换请求 / 已下发 XX」的**那一轮**，"
        "ui_intents 里必须有对应的意图。只在正文里说做了、实际没下发意图，"
        "用户看到的就是操作没生效还找不到原因。（2026-11-09 外部实测：追问里说"
        "「已发出切换底图请求」，地图仍是街道底图，且没有任何操作回执。）\n"
        "- 真实结果看 `client_context.intent_results`（前端执行完才上报，"
        "每项含意图名、ok 与说明）。"
        "上一轮 ok=false 时，这一轮要先承认「上次那条没有生效」并说明原因，"
        "**不许把失败说成成功，也不许当没发生过**。\n"
        # 2026-11-11 用户复测第 4 条：多步指令必须逐项报成败。
        "- **一句话里有多个动作时，逐项报结果**：用户说“隐藏 CMFD 和 VOD”这类并列要求，"
        "做了几个就报几个；其中任何一个没做成（图层库里定位不到、被页面拒绝），"
        "必须点名“X 那一步没有执行”并说原因，"
        "**不许**只报成功项（用户会以为都做了），也**不许**笼统回一句“没有执行”。\n"
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
        # 2026-11-11 用户复测第 1 条：不得把「选中」说成「勾选」。
        "- **勾选显示（visible）与选中查看（selected）是两件事，不许混说**："
        "visible 决定这层在不在画面上，selected 只表示右侧分析面板当前指向它。"
        "隐藏某层时前端仍会把它设为选中（这是设计行为），所以 "
        "`visible=false` + `selected=true` 是常见组合，**不等于“已勾选”**。"
        "表述要分开：「「X」已隐藏，只是当前选中」／「「X」已勾选显示」。"
        "只要存在 visible=true 的图层，就**不得**说“当前没有勾选任何图层”。\n"
        # 2026-11-11 用户复测第 2 条：纯日期指令不带图层动作。
        "- **只要求切日期时不要动图层**：用户只说“把时间轴切到 12 月 / 日期设到某天”、"
        "没点名任何图层或变量时，只下发 `set_timeline` 一条即可。"
        "**不要**顺带下发 `set_layer_visibility`，**更不许**在正文里写"
        "“没有勾选你要的图层”——用户根本没有要求勾选。\n"
        # 2026-11-11 用户复测第 3 条：静态图层不能切日期。
        "- **静态图层不能切日期**：前端回执会返回“「X」是静态数据，没有时间维度，"
        "不支持切换日期”。收到这种回执时正文只写两件事：① 这层已添加/已显示；"
        "② 它是静态数据，没有时间维度，不能切日期。"
        "**不许**改口说“已切到某天”，也**不许**改切别的图层来顶替。\n"
        "- **「单位 / 时间范围 / 显示状态」这类复合状态问题，要逐项回答、一项不漏**："
        "单位照 unit_label（土壤水分 m³/m³，VOD 与 ω 说“无量纲”）；显示状态照 "
        "visible/selected；**时间范围要分清两层意思**——用户问“这层的时间范围”时，"
        "若是在问当前画面停在哪，就说 timeline 当前时间块（time_blocks 里包含 "
        "timeline.date 的那一块，如 2025-07-01 ~ 07-31）；若是在问产品总共覆盖多久，"
        "才说 temporal_coverage / period_start~period_end。**两者不是一回事，"
        "禁止把产品总覆盖（如“2025-07 到 12 共 40 帧”）当成当前显示的时间块报给他**。\n"
        "- 状态问答**只答被问到的项，不要顺带讲算法/反演原理**：用户问“单位是多少”"
        "就只答单位，不要展开 SM 是怎么反演出来的。\n"
        "## 只读查询不得改视图\n"
        "- 用户只是问“多少 / 有没有 / 是什么 / 哪个 / 怎么样”这类只读问题时，"
        "**只准调用只读工具**，**不得下发任何改变画面的 UI 意图**："
        "set_timeline、set_timeline_playing、set_layer_visibility、set_layer_opacity、"
        "set_layer_symbology、fit_layer、fit_china、locate_coordinate、switch_basemap、"
        "remove_layer、reorder_layer 一律不要碰；"
        "也**不得**为了让数值“看起来对”而先切日期再取数。\n"
        "- 只有用户明确要求“切到某天 / 显示出来 / 调透明 / 定位到某地 / 换底图”时，"
        "才下发对应的视图意图。判别标准只有一条：**用户要不要画面跟着变。**\n"
        "- **打开目录里还没挂上页面的层是允许的**：用户说「打开 CMFD 降水」"
        "这类**不在** client_context.active_layers 里的层时，先用 search_layers "
        "拿到 layer_id，再下发 `set_layer_visibility(catalog_id=<layer_id>, visible=true)`，"
        "浏览器会自动从图层库添加并显示；**不要只回「查到了目录条目」就结束**，"
        "也不要编造「图层库搜不到」。（2026-11-09 外部实测：开场示例推荐"
        "「打开 CMFD 降水」，助手却只查条目未添加，用户以为功能坏了。）\n"
        "- 下发 `set_layer_visibility` 时**尽量带上 `display_name`**（用 search_layers / "
        "get_layer_meta 返回的图层名，如「CMFD 区域降水」）：前端回执要靠它把"
        "「已显示『该图层』」写成「已显示『CMFD 区域降水』」。目录参考层尤其要带——"
        "它刚被添加、前端那一刻还查不到它的显示名，不带就只剩「该图层」。\n"
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
        "- **用户问的量纲/属性与变量不符时，先澄清、不许硬算**：三个变量各有各的物理量，"
        "土壤水分是体积含水率（m³/m³）、植被光学厚度 VOD 是无量纲衰减量、等效散射 ω 是"
        "无量纲散射系数。用户若问「土壤水分的温度」「光学厚度的湿度」「ω 的单位是多少」"
        "这类**该变量并不具备的物理量/量纲**，**先说明该变量的正确量纲和单位**，"
        "再问一句是否要按它本身的含义取值；**严禁当作没看见、直接返回该变量的统计数**"
        "（2026-11-09 实测：问“土壤水分的温度是多少”，模型直接返回 0.1534 m³/m³，"
        "答非所问）。\n"
        "- **目录/数据清单查询不许对「服务是否正常」下乐观断言**：用户问「有哪些降水数据」"
        "这类目录清单时，只陈述目录里真实有的条目；**工具返回里没有明确的健康状态时，"
        "不许说「检索服务正常 / 服务可用」**——那只是目录查到了，不代表背后的天气/数据"
        "服务此刻在线。若工具返回带了服务状态（available / unavailable / error），"
        "照它如实说「该数据源当前不可用 / 取数失败」，不要笼统说正常"
        "（2026-11-10 实测：答「检索服务正常」的同时天气接口实际返回 503）。\n"
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
        "严禁说成“该日没有数据”**。**例外**：若 error 里已经写明“晚于覆盖终点”"
        "“早于覆盖起点”或“最新只到 YYYYMMDD”，那就不属于取数失败——照它的说法"
        "讲清边界即可，不要再补一句“取数失败”，否则同一段话自相矛盾"
        "（2026-11-07 实测：先说“取数服务出错、属于取数失败”，下一句又说“最新只到"
        " 2026-02-08、还没生成到今天”）。"
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
        "- **点值就是点值，绝不擅自换成区域均值**：用户说“点值 / 采样 / 这个点的值 / "
        "北京这个点的土壤水分”时，只能用 sample_layer_point 取点值。"
        "① 地图上没有选点（client_context.map_point 为空）→ 如实说“地图上还没选点，"
        "我无法取点值”，**禁止**改去调 get_layer_statistics 按“北京市行政边界”统计一个"
        "均值来顶替；② 用户没给坐标也没选点、却带了个地名（如“北京”）时，同样**先说明"
        "“点值需要一个具体坐标或地图选点，地名我只能做区域统计”，并问一句是否要改按区域**"
        "，而不是直接算区域均值糊弄过去（2026-11-10 实测：问“北京点值”，被擅自改成"
        "北京市均值 0.246，口径被悄悄换掉）。\n"
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
        "- **同一层同一时间只统计一次，绝不复述两遍**：`method-*` 产品族 id 与它本次"
        "解析出的 `imported-*` 是**同一层**，不许当两层各调一次统计、更不许把同一组数"
        "在正文里列两遍（2026-11-08 实测：一次问两个变量，模型把 method 与 imported "
        "各算一遍，四条项目里两两重复）。一次问 N 个变量 ⇒ 第一轮就并行发起 N 个统计，"
        "别一跳一跳串行（串行到第 4 跳时早期结果已压缩，容易答“数字没回传”）。\n"
        "- **像元分母口径**：`total_pixels` 是读取窗口（analyzed_height×analyzed_width）"
        "的像元总数，**含行政区边界外**；行政边界内的分母工具没有单独统计。正文只把 "
        "`valid_pixels` 说成「边界内有效像元数」，**不许**说「边界内共 total_pixels 个"
        "像元」。返回里带 total_pixels_note 时以它为准。（2026-11-09 外部实测：北京"
        "统计 195 个有效像元，模型却说「边界内共 437 个像元」——437 是 23×19 的窗口数。）\n"
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
        "`variable` 会是 unknown。念 `group_hint`：\n"
        "  · **用户已经点名变量**（例：“土壤水分和植被光学厚度分别是多少”）⇒ 直接从 "
        "`group_members` 里取 `variable_label` 对得上的那个 `overlay_layer_id` 调 "
        "get_layer_statistics，有几个变量就取几次、逐个给数；**这些成员层就算没挂在"
        "页面上也能统计**，严禁因为“页面只挂了一层”就回答“本机只有这一层”、"
        "或叫用户去数据管理页确认是否已生成。**本机有没有这一支产物，唯一判据是 "
        "`group_members` 里列没列**。\n"
        "  · 用户**没点名变量** ⇒ 才把 `group_members` 里的变量层列给他挑，选定再统计。\n"
        "- **「哪些省最高/最低」「全国排名」「逐省都比一遍」这类要扫描 30 多个行政区的提问，"
        "严禁逐省循环调用 get_layer_statistics**：一轮接一轮地算会累积超出单次处理量，"
        "最后白跑十几轮还给不出数（2026-11-08 实测 34 省排名跑到 51k token 被中止）。"
        "正确做法：只取用户点名的、或 3~5 个代表性省份给出对比，并明说"
        "“逐省排名要一个个算、一次问不完，你指定几个省我做对比”。"
        "**任何情况下都不许把 token、上限、步骤数、内部工具名这类机制讲给用户**，"
        "也不许教用户“先去左侧点选图层”来省步骤。\n"
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


def _drop_model_day_over_month(
    message: str, state: dict[str, str] | None, patch: dict[str, str]
) -> dict[str, str]:
    """整月口径不许被模型自己挑的那一天改写。

    用户上一轮问的是「2025 年 12 月」（状态里 ``date=2025-12``），这一轮只说
    「换成广州市呢」，模型却按页面日期传 ``time=2025-12-15``。这个日期一旦写回
    状态，下一句追问就彻底没有月份了，而且本轮取数也会退到那天（广州 12-15 是
    整片缺测）。用户没有点具体某一天时，月份保持粘住。

    2026-11-09 r116 实测：「河南 12 月」→「换成广州市呢」被答成「12-15 这天
    没有有效像元」，与上一句的整月口径不是一回事。
    """
    if not isinstance(patch, dict) or "date" not in patch:
        return patch
    if not isinstance(state, dict):
        return patch
    if not re.fullmatch(r"\d{4}-\d{2}", str(state.get("date") or "")):
        return patch
    if _DAY_GIVEN_RE.search(message or ""):
        return patch
    out = dict(patch)
    out.pop("date", None)
    return out


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
        canonical = canonical_layer_state(
            local, display=str(res.get("display_name") or "").strip()
        )
        patch.update(canonical)
        # 2026-11-09：把「变量 → 真读到的产物」单独记进跨轮映射（var_layers），
        # 防产品粘性单槽被非三变量层（CMFD 降水）覆盖后丢版本。只记三变量。
        var = str(canonical.get("variable") or "")
        lid = str(canonical.get("layer_id") or "")
        if var and var in dialogue_state.VARIABLE_LABELS and lid:
            patch["var_layers"] = dialogue_state._dump_var_layers({var: lid})
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
#
# 阈值 2000 的来由（2026-11-08 r59-d2 实测）：一份完整统计返回约 1994 字符，
# 而数值（min/max/std）与时间口径（value_basis）排在 1075~1641 位。阈值曾为 700，
# 会把这些字段按位置切掉，模型跳到第 4 跳只能回「数字没回传上来」。
# 这里就用「阈值够大」解决：常见统计/检索返回整份保留，只有真正冗长的才截。
# 不做按字段挑拣重排的花活——那套逻辑自己又会引入新 bug（列表被丢光、切出半截 JSON）。
_TOOL_RESULT_KEEP_CHARS = 2000

_SHRINK_NOTE = "…（内容过长，后续已省略）"


def _shrink_tool_text(text: str, limit: int = _TOOL_RESULT_KEEP_CHARS) -> str:
    """把一份超长工具返回截断：够短就原样返回，超了才按位置切并注明已省略。

    故意做得很笨：不重排字段、不挑拣 JSON、不动列表结构。
    """
    if not isinstance(text, str) or len(text) <= limit:
        return text
    return text[:limit] + _SHRINK_NOTE


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
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        # OpenAI 协议：role=tool，content 是 JSON 字符串
        if role == "tool" and isinstance(content, str) and len(content) > limit:
            m["content"] = _shrink_tool_text(content, limit)
            continue
        # Anthropic 协议：user 消息里嵌 tool_result block
        if role == "user" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                inner = block.get("content")
                if isinstance(inner, str) and len(inner) > limit:
                    block["content"] = _shrink_tool_text(inner, limit)


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
# 2026-11-08 实测 r70-A3：「11 月 9 日到 16 日**这几天**平均下来是多少」里的
# 「这几天」是口语的日期区间（＝这些天），却命中了本正则的 `几天`，于是统计闸门
# 被关掉，模型那句零工具调用、凭空编造的 8 个逐日数值（0.1130/71、0.1140/72…，
# 磁盘上任何 tif 都对不上）原样流给了用户。「这几天/那几天/前几天/最近几天」是
# 数量为「几」的天，不是「几天」这个疑问词，用后顾断言排掉，`多少天` 不受影响。
_TIME_STRUCTURE_RE = re.compile(
    r"时间片|时间块|时间清单|时间轴|多少天|(?<![这那前近])几天|片数|补了几天"
    r"|几个时次|多少时次",
    re.I,
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


#: 「这个值准不准 / 精度多少 / 误差多大」——问的是**数据质量**，不是要一个均值。
#: 2026-11-07 r25 实测：`_STATISTICS_WORDS` 里有「像元」和「多少」，于是
#: 「取到的这个像元值精度是多少？误差多大」命中统计闸门，整段被换成
#: **整幅全球**的均值 0.1653 / 363201 个有效像元（占 5.8%）——用户问的是刚
#: 算出来的河南值准不准，拿到的却是一个口径完全不同、却看着像答案的数字。
#: 「不确定度多大」「置信度多少」同样中招。这类问题系统里没有精度字段，
#: 正确答案是「没有登记精度指标」，只能交给模型说边界，不能由规则引擎代答。
_QUALITY_QUESTION_RE = re.compile(
    r"精度|误差|不确定度|置信|可信度|准不准|准吗|靠谱|可靠性|校验|验证|分辨率|像元大小",
    re.I,
)


#: 「把 0.2025 换成每亩多少吨水」——用户已经把数值给出来了，要的是**单位换算**，
#: 不是一次新的取数。句中的「多少」会命中 _STATISTICS_WORDS，于是规则引擎把整段
#: 换成整层统计。2026-11-07 r42-i 实测：问「每亩多少吨水」，答的是整幅
#: 0.1653 m³/m³ / 363201 个有效像元（5.8%）—— 数值没错，但一个都没回答他的问题；
#: 正确做法是说明「换成水量需要容重和土层厚度，这两项这层没有」。
#: 判据必须**同时**满足「有换算动词」和「消息里已经有小数」：
#: R 那种「把河南省这个平均值换算成百分比是多少」没给数值，仍要走统计取数，
#: 不能被这条误伤（那是本轮唯一需要先出数再换算的问法）。
_UNIT_CONVERSION_RE = re.compile(r"换算|折合|相当于|换成|转换为", re.I)
_GIVEN_DECIMAL_RE = re.compile(r"(?<![\d.])\d+\.\d+(?![\d])")


def _is_given_value_conversion(text: str) -> bool:
    """是不是「拿我给的这个数去换算单位」（不需要再取一次统计）。"""
    if not text:
        return False
    return bool(_UNIT_CONVERSION_RE.search(text) and _GIVEN_DECIMAL_RE.search(text))


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
    # 排除「数据质量」类提问：问的是准不准/精度/误差，答案不在这层数据里。
    # 放行的话会被规则引擎换成整幅均值（r25 实测 3/3），口径完全不对。
    if _QUALITY_QUESTION_RE.search(text):
        return False
    # 排除「拿用户自己给的数去换单位」：他要的是换算，不是再取一次数（r42-i）
    if _is_given_value_conversion(text):
        return False
    return bool(_STATISTICS_WORDS.search(text))


#: 「区间里挑一天」类提问：答案不是合并值，别被区间重算顶掉（2026-11-08 r75）。
_RANGE_PICK_RE = re.compile(r"哪一天|哪天|哪日|最大|最小|最高|最低|极值")


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
        # 「3 位有效数字相等」救不了「模型把参考值四舍五入」：0.0593 写成 0.059、
        # 0.20253 写成 0.2 时两边位数不同，字符串对不上。2026-11-07 实测 R：正文写
        # 「标准差 0.059」，工具返回 0.0593 ⇒ 被判编造、整段重写成模板句。
        # 再兜一层相对误差（0.6%），抄上一轮那种整套数（0.293 对 0.2025，差 45%）
        # 照样拦得住。
        if ref and abs(value - ref) <= 0.006 * abs(ref):
            return True
        # 相对误差对**很小的数**太苛刻：0.0295 写成 0.03 是「保留 2 位小数」的标准
        # 转写，绝对差只有 0.0005，肉眼完全一样，但相对差 1.7% 超过 0.6% 阈值。
        # 2026-11-07 实测新疆：模型把标准差 0.0295 写成 0.03 ⇒ 被判编造、整段重写。
        # 补一层**绝对误差**（保留 2 位小数的舍入界 0.005），只对「两边都足够小」
        # 的数生效，大数不受影响（0.293 对 0.2025 差 0.09 照样拦）。
        if ref and abs(value - ref) <= 0.005 and abs(ref) < 0.1:
            return True
        # 上一层的 ``abs(ref) < 0.1`` 门槛把 0.165→0.17 这种「保留 2 位小数」的
        # 正常转写漏掉了：0.165 恰好 >0.1，吃不到绝对误差兜底，相对误差 3% 也超
        # 0.6%，于是被判编造。2026-11-07 实测 c（问「有没有 0 或负值」）：模型把
        # 整幅均值 0.165 写成 0.17、最大值 0.808 写成 0.81，就这两个数被误判，
        # 整段换成模板句。舍入误差是**绝对**的（round(x,2) 误差 ≤0.005），与数值
        # 大小无关——所以这里再加一层：两边都是**普通小数**（都不是整数、也都不
        # 是「有效像元」那种大计数），绝对差落在保留 2 位小数的舍入界内即可视为
        # 同一个数。界取 0.006 而非 0.005，是因为 0.17-0.165 的精确舍入误差恰是
        # 0.005，浮点表示下会变成 0.0050000000000000044 刚好越界；0.006 既容纳
        # 浮点误差，又远小于「换整套数」的 0.09（0.293 vs 0.2025 照样拦）。
        if (
            ref
            and not value.is_integer()
            and not ref.is_integer()
            and abs(value - ref) <= 0.006
        ):
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
    # 2026-11-08 补中间那个变量名：模型最常写「平均土壤水分：0.064」
    # 「平均 VOD 0.1516」，而旧正则只允许「平均」后面直接接连接词，于是这一句
    # 一个数都收不上来 ⇒ 严格校验把整段当成「没有统计量名」，退到宽松判据放行，
    # 写错的均值也能过关（r68 那次「正文 0.064、工具取的却是动态版」就是这么漏的）。
    r"(?:平均值|均值|平均|最大值|最小值|最高值|最低值|最高|最低|标准差|中位数)"
    r"\s*(?:的)?\s*"
    r"(?:土壤水分|土壤湿度|土壤墒情|墒情|含水量|植被光学厚度|光学厚度|"
    r"等效散射|散射\s*ω|ω|vod|smv|smw|sm)?\s*"
    r"(?:是|为|约|大约|在|[:：])?\s*[*_`]*\s*(\d+(?:\.\d+)?)"
    # 「有效像元 1995」「有效像元：1995」
    r"|(?:有效像元|有效栅格|像元数|栅格数)\s*(?:数)?\s*[:：为是]?\s*(\d[\d,]*)"
    # 「1995 个有效像元」
    r"|(\d[\d,]*)\s*个\s*(?:有效)?(?:像元|栅格)"
)


#: 正文里**写着百分号**的统计值：``平均值约 20.25%``。
#: 工具只返回 0.2025 这种小数，百分数是模型自己乘 100 的换算——不能拿原值直接比，
#: 也不能一律放行（2026-11-07 实测 R：写对了 20.25% 却被判「均值对不上」整段重写；
#: 而 r27 那次因为 20.25% 没挨着「平均值」就过掉了，同一个问法两种结果）。
#: 这里单独收出来，按 ÷100 与之比对，既留校验力又不误伤换算。
_STAT_PERCENT_RE = re.compile(
    r"(?:平均值|均值|平均|最大值|最小值|最高值|最低值|最高|最低|标准差|中位数)"
    r"\s*(?:是|为|约|大约|在|[:：])?\s*[*_`]*\s*(\d+(?:\.\d+)?)\s*[%％]"
)


def _stat_percent_values(text: str) -> set[float]:
    """正文里以百分数形式写出的统计值（``平均值约 20.25%``）。"""
    raw = _DATE_LIKE_RE.sub(" ", text or "")
    out: set[float] = set()
    for token in _STAT_PERCENT_RE.findall(raw):
        try:
            out.add(float(token))
        except ValueError:
            continue
    return out


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
        # 判据是「本轮那个区域名有没有出现在正文里」，不是拿正则抽出的片段去比。
        # 那个正则左侧贪心：「按河南省行政边界」会抽成「按河南省」，于是正文明明
        # 写的就是河南，也被判成张冠李戴、整段换成模板句（2026-11-07 实测 R：
        # 原文本已把 0.2025 换算成 20.25%，被这条误报打掉）。
        if _REGION_MENTION_RE.search(text) and region not in text:
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
    mentioned = {m.group(0) for m in _REGION_MENTION_RE.finditer(text or "")}
    if len(mentioned) < 2:
        return False
    known: set[str] = set()
    for row in facts.get("stats_list") or []:
        if isinstance(row, dict) and row.get("region"):
            known.add(str(row["region"]))
    single = facts.get("stats")
    if isinstance(single, dict) and single.get("region"):
        known.add(str(single["region"]))
    # 用**包含**比，不能用集合相减：``_REGION_MENTION_RE`` 左侧是贪心的，
    # 「按河南省行政边界」抽出来的是「按河南省」，跟工具返回的「河南省」相减
    # 永远非空 ⇒ 同一句话被当成在跨轮对比别处（2026-11-07 实测 R 就栽在这条上，
    # 换算成百分比的正确答案被整段重写）。
    return not all(any(k in m for k in known) for m in mentioned)


#: 「这一次没取到」的说法。只用于「明明取到了却谎报没有」这一类矛盾判定，
#: 不参与数值校验——「该区域没有有效观测」「这一片整幅是空的」是另外的说法。
_UNAVAILABLE_CLAIM_RE = re.compile(
    r"没有取到|没取到|取不到|未取到|没有拿到|没拿到|"
    r"取数没有命中|没有命中|没有算出|没算出|没有返回数值|没有返回结果|"
    r"给不出数值|给不出数"
)


def _claims_unavailable_but_has_stats(
    reply: str, stats_list: list[dict[str, Any]] | None
) -> bool:
    """正文说「这个变量这次没取到」，可本轮这个变量的统计明明成功了。

    2026-11-08 r72 实测 3/3：产品粘性把植被光学厚度 / 等效散射 ω 的统计请求
    改回了土壤水分，模型于是如实转述「另外两个变量这次没有取到」。粘性已修，
    但这类**谎报没数据**比直接报错更难发现——用户会以为本机没有这一层，
    转头去重跑几小时的工作流。所以再加一道：一次问多个变量时，只要某一组
    的数明明在本轮工具返回里，却写成「取不到」，就按工具返回整段补齐。
    """
    text = str(reply or "")
    if not text or not _UNAVAILABLE_CLAIM_RE.search(text):
        return False
    items = [
        d
        for d in (stats_list or [])
        if isinstance(d, dict) and d.get("mean") is not None
    ]
    # 只有一份统计时不算矛盾：那多半是「这一片没有有效像元」「该区域没观测」，
    # 由别的分支负责说清，不该在这里整段重写。
    if len(items) < 2:
        return False
    for chunk in re.split(r"[。！？\n；;]", text):
        if not _UNAVAILABLE_CLAIM_RE.search(chunk):
            continue
        for data in items:
            name = str(data.get("display_name") or "").strip()
            if name and name in chunk:
                return True
    return False


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
    # 本轮答复由**服务端重算**得出（见 _statistics_fallback_reply 的
    # ``authoritative`` 标记）：这句话本身就是工具数据的确定性投影，
    # 再拿「工具返回过的数」去校验它，反而会把月份/区间口径重算出来的正确答复
    # 改回模型自己挑的那一天。2026-11-09 r113 实测即此。
    if any(isinstance(s, dict) and s.get("authoritative") for s in (steps or [])):
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
    pct_values = _stat_percent_values(text)
    plain_values = stat_values - pct_values
    if (plain_values or pct_values) and not _has_cross_round_region(text, facts):
        numbers_ok = all(_number_matches(v, whitelist) for v in plain_values)
        # 0.2025 → 20.25% 是模型乘 100 的换算，工具从不返回百分数：按 ÷100 比。
        # 保留校验力——20.25% 对上的是 0.2025，写成 15.07% 仍然拦得住。
        numbers_ok = numbers_ok and all(
            _number_matches(round(v / 100.0, 10), whitelist) for v in pct_values
        )
    else:
        numbers_ok = any(_number_matches(value, whitelist) for value in mentioned)
    # 数值对得上还不够：正文可能把这一层说成另一颗卫星/另一个区域/另一天。
    # 只在报了数值时查（身份类问答会被误伤），带「上一轮/相比」的整句豁免。
    conflict = _fact_conflict(text, facts)
    if (
        numbers_ok
        and not conflict
        and not _claims_unavailable_but_has_stats(text, facts.get("stats_list"))
    ):
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


#: 句子里「像行政区」的写法：用来兜「认不出来也要说清楚」。
_REGION_TOKEN_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,8}(?:自治区|特别行政区|省|市|盟|州|地区)"
)
#: 这些不是具体地名，别拿去做「认不出行政区」的提示。
_NOT_PLACE_WORDS = (
    "地级市",
    "县级市",
    "副省级市",
    "城市",
    "都市",
    "全市",
    "全省",
    "全国",
    "省市",
    "地市",
    "城区",
    "市区",
    "地区",
)
#: 正则只能按「后缀」切，会把前面的年月/动词一起吃进来（「2025年12月河兰省」
#: 会得到「月河兰省」），这些首字一律剥掉再拿去解析。
#: 注意别加「日」——「日喀则市」是地名。
_PLACE_LEAD_TRIM = "年月号的在了是和与及对把将换成改调看查算给按问请帮还就也又再"


def _trim_place_token(token: str) -> str:
    """把「月河南省」「换成河南省」这类前缀动词/时间词剥成纯地名。"""
    out = str(token or "")
    while out and out[0] in _PLACE_LEAD_TRIM:
        out = out[1:]
    return out


def _has_region_scoped_stats(steps: list[dict[str, Any]]) -> bool:
    """本轮取数里有没有「按行政区 / 矩形框」算出来的统计。"""
    for step in steps or []:
        if not isinstance(step, dict) or step.get("type") != "tool_result":
            continue
        data: Any = step.get("detail")
        if isinstance(data, str) and data.strip().startswith("{"):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                continue
        if isinstance(data, dict) and data.get("scope") in ("region", "bbox"):
            return True
    return False


def _unknown_region_token(message: str) -> str | None:
    """句子里提到一个「像行政区、但解析不出来」的名字；没有则 None。"""
    try:
        from app.services.agent.region import resolve_region
    except Exception:  # noqa: BLE001 - 区域库缺失时不做这个判断
        return None
    # 两个降噪工具（都来自规则引擎那一侧，避免两处口径漂移）：
    #   1) ``_clean_place_token``：剥掉候选里混进的「产品/日期/统计/范围」等普通名词；
    #   2) ``_region_from_known_names``：候选里其实包含一个能认出来的行政区名。
    # 2026-11-09 实测的三句误报全靠这两条挡住：「产品和地区沿用刚刚那次统计」、
    # 「地区和日期保持广州市」、「统计范围改为河南省」——数值本身是对的，
    # 只是正文凭空多一句「这个地名我没认出来」。
    clean_token = None
    known_region = None
    try:
        from app.services.agent.mock_orchestrator import (
            _clean_place_token,
            _region_from_known_names,
        )

        clean_token = _clean_place_token
        known_region = _region_from_known_names
    except Exception:  # noqa: BLE001 - 导入失败就只做原来的判断
        pass
    for match in _REGION_TOKEN_RE.finditer(str(message or "")):
        text = str(message or "")
        start = match.start()
        token = match.group(0)
        while token and token[0] in _PLACE_LEAD_TRIM:
            token = token[1:]
            start += 1
        # 「12月18日广州市」这种：正则会把「日广州市」一起切进来。只有紧跟在
        # 数字后面的「日 / 号」才是日期尾巴——「日喀则市」不能剥（见上面注释）。
        while token and token[0] in "日号" and start > 0 and text[start - 1].isdigit():
            token = token[1:]
            start += 1
        if len(token) < 3 or token in _NOT_PLACE_WORDS:
            continue
        # 剥掉粘在名字前后的动词/普通名词：「统计范围改为河南省」→「河南省」，
        # 「产品和地区」→ 剥完不成名 → 丢掉（不是地名）。
        if clean_token is not None:
            token = clean_token(token)
            if not token:
                continue
        if known_region is not None:
            try:
                if known_region(token):
                    continue
            except Exception:  # noqa: BLE001
                pass
        try:
            if resolve_region(token) is not None:
                continue
        except Exception:  # noqa: BLE001
            continue
        return token
    return None


#: 用户把「中国 / 全国 / 全境 / 我国」当成统计范围，但系统只有省级和地级市
#: 行政区掩膜，没有「中国全境」这个范围——resolve_region 认不出它，模型于是
#: 静默落到**全球整幅栅格**（SMAP 是全球产品），把全球均值当成中国值回给用户
#: （2026-11-10 线上实测 P0：「中国区域 / 全国 / 中国境内」均返 0.153=全球）。
_CHINA_SCOPE_RE = re.compile(
    r"中国(?!气象局|科学院|科学研究院|工程院|政府|央行|人民银行)"
    r"(?:全境|全图|范围|境内|区域|地区)?|全国|全境|我国"
)


def _mentions_china_scope(message: str) -> bool:
    """这句话是不是把「中国 / 全国」当成统计范围（而非缩放视图）。"""
    return bool(_CHINA_SCOPE_RE.search(str(message or "")))


def _stats_region_info(steps: list[dict[str, Any]]) -> tuple[str, str]:
    """本轮统计实际用的行政区名与级别 ``(region, region_level)``。

    取最后一份按区域算的统计（多区域比较时最后一条就是最后落定的那次）。
    级别来自工具返回的 ``region_level``（``province`` / ``city``）：省和地级市
    的说法不一样，写错会让人以为系统把省降成了市。
    """
    found: tuple[str, str] = ("", "")
    for step in steps or []:
        if not isinstance(step, dict) or step.get("type") != "tool_result":
            continue
        data: Any = step.get("detail")
        if isinstance(data, str) and data.strip().startswith("{"):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                continue
        if (
            isinstance(data, dict)
            and data.get("scope") == "region"
            and data.get("region")
        ):
            found = (str(data["region"]), str(data.get("region_level") or ""))
    return found


def _stats_region(steps: list[dict[str, Any]]) -> str | None:
    """本轮统计实际用的行政区名（取最后一份按区域算的统计）。"""
    return _stats_region_info(steps)[0] or None


def _append_region_scope_note(
    message: str, reply: str, steps: list[dict[str, Any]]
) -> str:
    """把「你要的区域其实没按那个范围算」补一句到正文末尾。

    两类必须点名，否则用户会拿错值：

    1. **县 / 市辖区一级**（系统只到省与地级市）。2026-11-09 r113 实测：问
       「广州市天河区的平均土壤水分」，模型自己把 region 降成「广州市」，
       答复只写「按广州市行政边界」，全程没出现「天河区」三个字——用户会
       把整市值当成天河区的。规则引擎里那道县区提示写了 ``if not region``，
       区域一旦解析成市就被跳过，所以必须在最终正文上补。
    2. **行政区名解析不出来**（写错字、库里没有），结果退回整幅栅格。
       答复虽写了「整层」，但用户问的是那个地方，得点名说没认出来，
       否则「整幅均值」会被当成「那个地方的均值」。
    """
    text = str(reply or "")
    if not text:
        return reply
    msg = str(message or "")

    county = None
    try:
        from app.services.agent.mock_orchestrator import _county_like_region_name

        county = _county_like_region_name(msg)
    except Exception:  # noqa: BLE001 - 区域库缺失时不做这个判断
        county = None
    if county and county not in text:
        # 范围一律以**统计工具真正用的行政区**为准（`_stats_region` 读的是工具
        # 返回里的 ``region`` 字段）。原话里找市名只是兜底：模型可能把「天河区」
        # 顺成别的市、也可能沿用上一轮的区域，照着原话拼出来的「按 X 整市算」
        # 会和实际取数对不上（2026-11-09 用户复测：「产品和地区」被当区县时报
        # 「按地级市统计」，而工具实际按广州市边界算）。
        used_region, used_level = _stats_region_info(steps)
        city = used_region
        level = used_level
        if not city:
            idx = msg.find(county)
            if idx > 0:
                head = re.search(r"([\u4e00-\u9fa5]{2,6}市)$", msg[:idx])
                if head:
                    city = _trim_place_token(head.group(1)) or None
                    level = "city" if city else ""
        if city and level == "province":
            scope = f"「{city}」全省"
        elif city:
            scope = f"「{city}」整市"
        else:
            scope = "它所属的地级市"
        return text + (
            f"\n\n补一句口径：你说的「{county}」是县/区一级，系统只做到**省级和地级市**，"
            f"切不出这一级的边界。上面的数是按{scope}的范围算的，不是「{county}」单独的值；"
            "要精确到区县，给我一个矩形范围（西、南、东、北四个经纬度），我按框统计。"
        )

    if not _has_region_scoped_stats(steps):
        # 「中国 / 全国」优先于一般地名兜底：它不是「认不出的行政区」，而是
        # 系统根本没有这一级范围。全球产品落到整幅＝全球，必须点明，否则用户
        # 会把全球均值当成中国值（2026-11-10 线上实测 P0）。
        if _mentions_china_scope(msg) and "全球" not in text and "整幅栅格" not in text:
            return text + (
                "\n\n补一句口径：你说的「中国 / 全国」不是系统里可统计的行政区范围——"
                "目前只做到**省级和地级市**，没有「中国全境」这一级掩膜，"
                "而这类数据是全球产品，所以上面的数实际是按**全球整幅栅格**算的，"
                "不是中国范围内的值。要中国全境的口径，请给我一个矩形范围"
                "（西、南、东、北四个经纬度，例如 [73, 18, 135, 53] 附近），"
                "我按框统计。"
            )
        unknown = _unknown_region_token(msg)
        if unknown and unknown not in text:
            return text + (
                f"\n\n另外要说明：你提到的「{unknown}」我没能对应到系统里的行政区，"
                "所以这次算的是**整幅栅格**，不是那个地方的范围。"
                "如果它是某个省或地级市，请再说一次规范名称；也可以直接给我矩形范围。"
            )
        return text

    # 句子里的地名没认出来，但结果仍按某个行政区算了——说明这一轮悄悄换成了
    # 别的区域（模型把「河兰省」顺成了「河南省」，或者沿用了上一轮的区域）。
    # 不点明的话，用户会把那个省的值当成自己写的地方的值。
    unknown = _unknown_region_token(msg)
    if unknown and unknown not in text:
        used = _stats_region(steps)
        if used and used not in unknown:
            return text + (
                f"\n\n另外要说明：你说的「{unknown}」我没在系统里找到，"
                f"上面的数是按「{used}」算的。如果不是这个区域，请再说一次规范名称。"
            )
    return text


#: 用户问了某变量**并不具备**的物理量/量纲，模型却没澄清、直接给数（2026-11-09
#: 实测「土壤水分的温度是多少」→ 模型凭记忆直接回 0.1534 m³/m³，一次工具都没调，
#: 工具层/规则引擎都拦不到）。这道守卫在答复**返回前**兜底：提问里同时出现
#: 「变量词 + 该变量不存在的量纲词」，而答复正文没有澄清时，整段换成澄清话术。
_DIMENSION_MISMATCH: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("土壤水分", "土壤湿度", "含水量", "墒情"), ("温度", "气温", "湿度", "降水")),
    (("植被光学厚度", "光学厚度", "vod"), ("湿度", "降水", "温度")),
    (("等效散射", "散射", "ω", "omega"), ("温度", "湿度", "降水")),
)
#: 答复里出现了这些澄清语，说明模型已经正确处理，不再拦截。
_DIMENSION_CLARIFY_RE = re.compile(
    r"没有.{0,6}(这个|该|这个物理)?量|不是.{0,4}(温度|湿度|降水)|无量纲|澄清|不具备"
)


def _guard_dimension_mismatch(message: str, reply: str) -> str:
    """提问问错了量纲时，把答复换成「先澄清」的话，不许直接给数。"""
    text = str(reply or "")
    if not text:
        return reply
    msg = str(message or "")
    low = msg.casefold()
    if not low:
        return reply
    # 模型已经澄清了，就放行原文（不重复打断）
    if _DIMENSION_CLARIFY_RE.search(text):
        return reply
    for var_words, wrong_units in _DIMENSION_MISMATCH:
        var_hit = next((w for w in var_words if w.casefold() in low), None)
        if not var_hit:
            continue
        unit_hit = next((u for u in wrong_units if u in low), None)
        if not unit_hit:
            continue
        # 命中「变量 + 错误量纲」，且答复没澄清 → 拦截重写
        return (
            f"「{var_hit}」这个变量不包含「{unit_hit}」这个物理量，"
            "这个问题我没法按字面回答。\n\n"
            f"如果你想看的是「{var_hit}」本身的数值，我可以按某一天/某区域取它的"
            "均值并告诉你正确的单位；如果是想问别的变量，请说清楚具体是哪个。"
        )
    return reply


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


#: 规则引擎**按整段口径算出了合并值**的证据词（两个分支各有一个专属词）。
#:
#: ★ 2026-11-08 r98 实测（用户重启后仍被答成 12-15 单日，两次）：
#: 原先这里只认「合并平均」，而「合并平均」只出现在**逐日合并**分支
#: （``X 日到 Y 日``，mock_orchestrator:1865）。用户问的是「25 年 12 月」，
#: 引擎走的是**整月块**分支（mock_orchestrator:2255），文案里写的是
#: 「整月合成块」，一个「合并平均」都没有 ⇒ 被判成「引擎没走区间分支」⇒
#: 模型那句「12-15 这天 247 个像元全缺测」被原样放行，引擎算对的
#: 0.3399 被丢掉。凡是引擎**真按月份/区间合并过**的文案，这里都得认。
_PERIOD_MERGED_MARKERS = ("合并平均", "整月合成块")


def _asks_date_range(
    message: str, state: dict[str, str] | None, client_context: dict[str, Any] | None
) -> bool:
    """这句话里是不是一个 ≥2 天的日期区间。

    判据与 ``mock_orchestrator._parse_date_range`` 同源（直接复用，避免两处漂移）：
    区间要先有「月/日」才能认，所以「9 日到 16 日」这种说法需要一个基准日期，
    依次取会话状态里的日期、页面时间轴日期。
    """
    try:
        from app.services.agent.mock_orchestrator import _parse_date_range
    except Exception:  # pragma: no cover - 极端情况下退回「不当区间看」
        return False
    day = ""
    if isinstance(state, dict):
        day = str(state.get("date") or "")
    if not day and isinstance(client_context, dict):
        timeline = client_context.get("timeline")
        if isinstance(timeline, dict):
            day = str(timeline.get("date") or "")
    try:
        return _parse_date_range(message or "", day) is not None
    except Exception:  # pragma: no cover
        return False


def _asks_month_scope(
    message: str, state: dict[str, str] | None, client_context: dict[str, Any] | None
) -> bool:
    """这句话问的是不是「某一个月」（整月口径），而不是某一天。

    ★ 2026-11-08（用户实测「25 年 12 月广州的平均土壤水分」被答成 12-01 单日）：
    ``_parse_date_range`` 只认「X 日到 Y 日」，对「25 年 12 月」直接返回 None，
    于是 ``range_question=False`` —— 而模型这一轮调过一次 ``get_layer_statistics``，
    闸门按「调过工具就尊重原文」放行，模型自己挑的那一天就成了答案。

    实测模型挑的是 12-01：该层（风云卫星 平均散射约束 · 土壤水分）12 月只有
    12-01/02/03 三个按需补出的单日帧，12-01 在广州 247 个像元全缺测，于是
    「12 月平均」被答成「这天算不出平均值」，还附带一句「换成 12-16/12-13/12-18」。
    数值一个都没错，粒度完全不是用户问的。月份必须与「X 日到 Y 日」同等对待，
    一律交给引擎按整月合并。

    年份借会话状态或页面时间轴；借不到时 ``_parse_month_arg`` 返回 None，
    这里也跟着返回 False（不把「12 月」当成可算的请求，让上层去问哪一年）。
    """
    try:
        from app.services.agent.mock_orchestrator import _parse_month_arg
    except Exception:  # pragma: no cover - 极端情况下退回「不当月份看」
        return False
    # 句子已经点到某一天（「12 月 16 日」「2025-12-16」）就不再按月看：他要的是
    # 那一天的观测，按月合并会把他的日期吞掉。`_parse_month_arg` 只认到「年月」，
    # 「2025年12月16日」也能被它认成 (2025, 12)，必须在这里先挡。
    if _DAY_GIVEN_RE.search(message or ""):
        return False
    year: int | None = None
    if isinstance(state, dict):
        raw = str(state.get("date") or "")
        if len(raw) >= 4 and raw[:4].isdigit():
            year = int(raw[:4])
    if year is None and isinstance(client_context, dict):
        timeline = client_context.get("timeline")
        if isinstance(timeline, dict):
            raw = str(timeline.get("date") or "")
            if len(raw) >= 4 and raw[:4].isdigit():
                year = int(raw[:4])
    try:
        return _parse_month_arg(message or "", year) is not None
    except Exception:  # pragma: no cover
        return False


#: 「12 月 16 日」「2025-12-16」「20251216」这类**具体某一天**的写法。
#: 用来判断「沿用上一轮整月口径」会不会把用户明确指的那一天顶掉。
_DAY_GIVEN_RE = re.compile(
    r"\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?"
    r"|\d{8}(?![\d_])"
    r"|(?<!\d)\d{1,2}\s*月\s*\d{1,2}\s*[日号]"
    r"|(?<![\d月])\d{1,2}\s*[日号]"
)


def _carried_month_scope(message: str, state: dict[str, str] | None) -> bool:
    """这一句没提月份，但上一轮记着**整月口径**——算不算沿用那个月。

    2026-11-09 r116 实测：「2025年12月河南省的平均土壤水分」之后接
    「换成广州市呢」，月份整个丢掉、退回页面那天（12-15），而广州 12-15
    是整片缺测，于是答成「这天算不出」——和上一句的整月口径不是一回事。
    状态里整月口径存成 ``2025-12``（见 ``_entities_state_patch``）。

    只在这一句**没有另给具体日期**时才沿用：用户说了「12 月 16 日」就以他说的为准。
    """
    if not isinstance(state, dict):
        return False
    if not re.fullmatch(r"\d{4}-\d{2}", str(state.get("date") or "")):
        return False
    return not _DAY_GIVEN_RE.search(message or "")


#: 明确的「回指上文」措辞。这类词单独出现在**首轮**＝用户在引用不存在的历史。
#:
#: 只收毫不含糊的说法：「再说一遍/这个/那个」太宽（可能指当前选中的层），
#: 一律不收，避免把正常提问误判成回指。
_BACKREF_RE = re.compile(r"刚才|刚刚|上一条|上一轮|上轮|上次|前面问|前面说|刚说")

_MISSING_HISTORY_REPLY = (
    "这是一个新对话，我这边没有你之前问过的记录，接不上「刚才那个数」。\n\n"
    "你把下面三件事告诉我，我立刻算：\n"
    "1. 哪一层（例如「SMAP 动态散射约束产品 · 土壤水分」）；\n"
    "2. 哪一天或哪一段时间；\n"
    "3. 范围（整幅，还是某个省/市）。\n\n"
    "如果只是想看当前选中这一层的整体情况，直接说「这一层的平均值」就行。"
)


def _refers_to_missing_history(message: str, state: dict[str, str] | None) -> bool:
    """首轮（没有任何可继承上文）却用「刚才/上一轮」回指 ⇒ 必须澄清，不许出数。

    2026-11-08 实测：新会话第一句问「刚才我问的那个数是多少来着？」，规则引擎
    按页面选中层重算了一遍，还在正文里写「本轮没有重新指定的部分沿用上一轮」。
    数值本身是对的（就是当前层的整幅均值），但「沿用上一轮」是不实说法——
    用户会以为它真记得上一轮，进而以为跨会话记忆存在。宁可澄清，不许编连续性。
    """
    if not _BACKREF_RE.search(message or ""):
        return False
    if not isinstance(state, dict):
        return True
    return not any(
        str(state.get(key) or "").strip()
        for key in ("layer_id", "layer_name", "region", "date")
    )


def _statistics_fallback_reply(
    message: str,
    reply: str,
    steps: "_EventSteps",
    sid: str,
    client_context: dict[str, Any] | None,
    *,
    state: dict[str, str] | None = None,
    history_state: dict[str, str] | None = None,
) -> tuple[str, dict[str, str] | None]:
    r"""统计请求的确定性兜底：模型没调过任何取数工具时，正文里的数字一律不可信。

    ``state`` 是本轮合并后的会话状态（供选层用）；``history_state`` 是**进入本轮
    之前**的状态，只用来回答「有没有上文可继承」（见 _refers_to_missing_history）。

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
    # 当前指令优先于历史统计状态。模型即使沿用上轮任务发起了统计调用，运行时也会
    # 拦截；这里同时禁止确定性统计兜底再次绕过运行时直接计算。
    from app.services.agent.server_tools_runtime import (
        _tool_blocked_by_current_instruction,
    )

    if _tool_blocked_by_current_instruction("get_layer_statistics", message):
        cleared = dialogue_state.merge(
            state,
            clear={
                "layer_id",
                "layer_name",
                "variable",
                "region",
                "date",
                "var_layers",
            },
        )
        return reply, cleared

    # 首轮回指（「刚才那个数」）先于统计判定：这类话看着像要数，其实要的是
    # 上文；硬算一遍会伪造出不存在的跨轮连续性（见 _refers_to_missing_history）。
    if _refers_to_missing_history(
        message, history_state if history_state is not None else state
    ):
        steps.append(
            {
                "type": "thought",
                "summary": "首轮却引用了上文，已改为澄清而不是重新取数",
            }
        )
        return _MISSING_HISTORY_REPLY, None
    # 日期区间（≥2 天）先于「模型调过工具就放行」：多天合并是纯算术，模型算得出来，
    # 但**口径不可控**。2026-11-08 r75 实测同一句话「11 月 9 日到 16 日这几天平均
    # 下来是多少」——规则引擎按有效像元加权给 0.1000，模型自己把 4 个日均值简单
    # 平均得 0.095，两条路两个数。同一天、同一区域、同一个问题给两个数，比算错
    # 更难发现（用户只会记住其中一个）。所以区间一律由引擎算，模型调没调工具都一样。
    # 例外：问的是「区间里哪一天最大/最小」这类**挑一天**的问题，答案不是合并值，
    # 引擎那段「合并平均 + 逐日明细」答非所问，仍交给模型（它有逐日数）。
    _month_carried = _carried_month_scope(message, state)
    range_question = bool(
        (
            _wants_statistics(message)
            and (
                _asks_date_range(message, state, client_context)
                or _asks_month_scope(message, state, client_context)
                or _month_carried
            )
        )
        # 「换成广州市呢」这类纯换对象的追问不含「平均/多少」，_wants_statistics
        # 是 False；但它这一轮真去取了数（模型自己调了 get_layer_statistics），
        # 而上一轮是整月口径 ⇒ 必须由引擎按整月重算，否则会答成页面那天。
        or (_month_carried and _statistics_tool_called(list(steps)))
    ) and not _RANGE_PICK_RE.search(message or "")
    if _statistics_tool_called(list(steps)) and not range_question:
        return reply, None
    if not range_question and not _wants_statistics(message):
        # 闸门之外的第二道（2026-11-08 r70-A3 实测）：那一轮 0 次工具调用，
        # 正文却写着「平均土壤水分是 0.1097」和 8 个逐日值。只要**正文里挂着
        # 统计量名的数**、而本轮一次数据工具都没调，这些数就必然来自历史或凭空
        # 生成——闸门关没关都不能放它过去。对比/单位换算类是真的不必重新取数
        # （见 _DIFF_QUESTION_RE、_is_given_value_conversion 的注释），仍然放过。
        if not _stat_values(reply):
            return reply, None
        if _DIFF_QUESTION_RE.search(message or "") or _is_given_value_conversion(
            message or ""
        ):
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
        # 区间问题要靠引擎那段「合并平均 / 逐日明细」才作数。引擎若因为认不出层、
        # 或落到县区级说明而没走区间分支，就不拿它顶替模型原文（模型这一轮真调过
        # 工具的话，它的数是 grounding 过的）。
        # 月份口径同理：整月块分支的文案是「整月合成块」，与逐日合并的
        # 「合并平均」是两套措辞，见 _PERIOD_MERGED_MARKERS 的实测说明。
        if range_question and not any(k in text for k in _PERIOD_MERGED_MARKERS):
            if _statistics_tool_called(list(steps)):
                return reply, None
            return (_UNGROUNDED_REPLY if _looks_numeric(reply) else reply), None
        steps.append(
            {
                "type": "tool_result",
                "summary": (
                    (
                        "服务端按整月块取数（该层时间清单里就有整月块，未拆成单日）"
                        if "整月合成块" in text
                        else "服务端重算日期区间合并（口径固定为按有效像元加权）"
                    )
                    if range_question
                    else "服务端强制取数（模型本轮未调用任何数据工具）"
                ),
                "detail": text[:800],
                # ★ 2026-11-09：这一段是**服务端自己重算**的结果，不是模型原文。
                # 标了它，_guard_reply_numbers 就不会再拿「模型自己那次工具调用」
                # 当参照把这句正确的答复改回去（r113 实测：问「25年12月河南省」，
                # 模型自带 12-15 单日帧 0.115/8 像元、引擎整月块算出 0.2484/1284，
                # 守卫把白名单只建成前者，于是把正确的整月答复重写成了 0.115/8）。
                "authoritative": True,
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
    # 整轮总超时：多跳取数到点就停，不再继续调用模型（2026-11-10 老师实测
    # 一轮 27s+ 还在「工具跳 1/4」等待）。0 = 关闭。
    _total_timeout = _total_timeout_seconds()
    _deadline = time.monotonic() + _total_timeout if _total_timeout > 0 else None
    _timed_out = False
    client_context = sanitize_client_context(client_context)

    def finish_direct(
        reply: str,
        *,
        provider_suffix: str,
        summary: str,
        intents: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return a deterministic answer without paying for a model round-trip."""

        nonlocal topic_state
        ui_intents = intents or []
        if ui_intents:
            topic_state = dialogue_state.merge(
                topic_state,
                **_state_patch_from_intents(ui_intents, client_context),
            )
        steps.append({"type": "thought", "summary": summary})
        usage = {
            "prompt_tokens": estimate_tokens(message),
            "completion_tokens": estimate_tokens(reply),
            "total_tokens": 0,
            "estimated": True,
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        append_turn(
            user_id=user_id,
            session_id=sid,
            user_message=_compress_history_user(message),
            assistant_message=reply,
            state=topic_state,
        )
        out = {
            "session_id": sid,
            "reply": reply,
            "ui_intents": ui_intents,
            "provider": (
                provider_kind
                if not provider_suffix
                else f"{provider_kind}-{provider_suffix}"
            ),
            "profile_id": profile_id,
            "usage": usage,
            "steps": list(steps),
            "confirmations": [],
        }
        _emit_stream_tail(on_event, reply=reply, ui_intents=ui_intents)
        return out

    # 2026-11-08 实测：用户问「20251301 那天广州市土壤水分多少」，13 月被当成
    # 「这句话没给日期」，于是拿会话上一轮的 11-16 去取数，正文还写「你请求的日期
    # 是 2025-11-16」——把系统补的日期说成用户请求的日期。数值有出处，归属是假的。
    # 日期写错就当场说错，一条数都不出，也不动会话状态。
    from app.services.agent.mock_orchestrator import _invalid_date_hint

    bad_date = _invalid_date_hint(message)
    if bad_date:
        reply = (
            f"「{bad_date}」不是一个有效日期，这次没有取数。\n\n"
            "请给一个真实存在的日子（如 2025-11-13，或紧凑写法 20251113）；"
            "要查一段时间就写成「2025-11-09 到 2025-11-16」。"
        )
        steps.append(
            {"type": "thought", "summary": "日期校验未通过", "detail": bad_date}
        )
        usage = {
            "prompt_tokens": estimate_tokens(message),
            "completion_tokens": estimate_tokens(reply),
            "total_tokens": 0,
            "estimated": True,
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        append_turn(
            user_id=user_id,
            session_id=sid,
            user_message=_compress_history_user(message),
            assistant_message=reply,
            state=topic_state,
        )
        out = {
            "session_id": sid,
            "reply": reply,
            "ui_intents": [],
            "provider": f"{protocol}-guard",
            "profile_id": profile_id,
            "usage": usage,
            "steps": list(steps),
            "confirmations": [],
        }
        _emit_stream_tail(on_event, reply=reply, ui_intents=[])
        return out

    # 新会话里的“刚才/上一轮”没有可继承事实，直接澄清。此前这句也会把完整
    # 系统提示与全部工具定义发给模型，实测浪费约 2 万 token。
    if not history and _refers_to_missing_history(message, topic_state):
        return finish_direct(
            _MISSING_HISTORY_REPLY,
            provider_suffix="history-guard",
            summary="新会话没有可继承的旧答案，已直接澄清",
        )

    # 在模型调用前处理已经审核通过的项目知识与拒答边界。这样普通模式、
    # 本地模型和规则演示模式不会因模型差异而给出不同或未经证实的答案。
    from app.services.agent.knowledge_guard import project_knowledge_reply

    knowledge_reply = project_knowledge_reply(message)
    if knowledge_reply is not None:
        steps.append(
            {
                "type": "thought",
                "summary": "已按项目知识边界回答",
                "detail": "使用已审核的标准口径，未调用外部搜索或数据工具",
            }
        )
        usage = {
            "prompt_tokens": estimate_tokens(message),
            "completion_tokens": estimate_tokens(knowledge_reply),
            "total_tokens": 0,
            "estimated": True,
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        append_turn(
            user_id=user_id,
            session_id=sid,
            user_message=_compress_history_user(message),
            assistant_message=knowledge_reply,
            state=topic_state,
        )
        out = {
            "session_id": sid,
            "reply": knowledge_reply,
            "ui_intents": [],
            "provider": f"{provider_kind}-knowledge-guard",
            "profile_id": profile_id,
            "usage": usage,
            "steps": list(steps),
            "confirmations": [],
        }
        _emit_stream_tail(on_event, reply=knowledge_reply, ui_intents=[])
        return out

    _unresolved_map_targets: list[str] = []
    deterministic_actions = _resolve_deterministic_map_actions(
        message, client_context, unresolved=_unresolved_map_targets
    )
    if deterministic_actions is not None:
        return finish_direct(
            _map_actions_reply(deterministic_actions, _unresolved_map_targets),
            provider_suffix="" if protocol == "demo" else "map-actions-rule",
            summary="多步骤地图操作已拆解并按顺序下发，未调用模型",
            intents=deterministic_actions,
        )

    # 纯时间切换属于确定性的界面操作，不需要携带完整目录与工具集询问模型。
    # 含“查询/统计/多少”等取数意图的复合请求仍走正常工具链。
    simple_timeline = bool(
        re.search(r"切到|切至|跳到|调整.{0,4}时间|时间轴.{0,6}(?:设|改|切)", message)
        and re.search(r"(?:19|20)\d{2}[-/年]\d{1,2}[-/月]\d{1,2}", message)
        and not re.search(r"查询|统计|计算|均值|平均值|多少|数值|取数", message)
    )
    if simple_timeline:
        deterministic = mock_chat(
            message,
            session_id=sid,
            client_context=client_context,
            state=topic_state,
        )
        direct_intents = [
            item
            for item in (deterministic.get("ui_intents") or [])
            if isinstance(item, dict)
        ]
        if direct_intents and all(
            str(item.get("name") or "") == "set_timeline" for item in direct_intents
        ):
            return finish_direct(
                str(deterministic.get("reply") or "已下发时间切换请求。"),
                provider_suffix="timeline-rule",
                summary="简单时间切换已由本地规则处理，未调用模型",
                intents=direct_intents,
            )

    # 纯底图切换同属确定性界面操作（2026-11-10 线上实测 P0：模型对「切换为
    # 天地图影像」等 4 种说法都不调工具，却回「已下发」，completion_tokens=18）。
    # 底图切换没有取数语义，直接走规则引擎直出 switch_basemap，绝不外呼模型。
    # 含取数意图的复合句仍走正常工具链。
    simple_basemap = bool(
        re.search(r"底图|basemap|天地图|高德|esri|osm|openstreetmap", message, re.I)
        and re.search(r"切换|换成|改为|换到|切到|切至", message)
        and not re.search(r"查询|统计|计算|均值|平均值|多少|数值|取数", message)
    )
    if simple_basemap:
        deterministic = mock_chat(
            message,
            session_id=sid,
            client_context=client_context,
            state=topic_state,
        )
        direct_intents = [
            item
            for item in (deterministic.get("ui_intents") or [])
            if isinstance(item, dict)
        ]
        if direct_intents and all(
            str(item.get("name") or "") == "switch_basemap" for item in direct_intents
        ):
            return finish_direct(
                str(deterministic.get("reply") or "已切换底图。"),
                provider_suffix="basemap-rule",
                summary="底图切换已由本地规则处理，未调用模型",
                intents=direct_intents,
            )

    # 纯图层显隐（只显示/只留/单独显示/显示/隐藏）同属确定性界面操作。
    # 2026-11-10 老师复测用例 04：一句「只显示风云…组中的植被光学厚度，保持其他
    # 不变」，模型却 search_layers×3 + get_layer_meta 查满 4 跳预算、没轮到下发
    # 显示就答「工具次数用完」。显隐没有取数语义，目标层往往就挂在页面上，一步
    # 定位、一步下发即可，不耗工具预算。解析逻辑见 `_resolve_simple_visibility`。
    _vis_intent = _resolve_simple_visibility(message, client_context)
    if _vis_intent is not None:
        _vis_visible = bool(_vis_intent["args"]["visible"])
        _vis_name = str(_vis_intent["args"].get("display_name") or "该图层")
        return finish_direct(
            f"已显示「{_vis_name}」。" if _vis_visible else f"已隐藏「{_vis_name}」。",
            provider_suffix="visibility-rule",
            summary="图层显隐已由本地规则定位并下发，未调用模型",
            intents=[_vis_intent],
        )

    # 「中国 / 全国」作为统计范围是确定性不可支持的情况：系统只到省级和地级市，
    # 没有「中国全境」掩膜。若不拦截，模型会把「中国区域」沿用成上一轮的省（实测
    # 先问河北再问中国 → 答成河北 0.2403），或静默拿全球均值冒充中国值
    # （2026-11-10 线上实测 P0-2）。含取数词的「中国/全国」直接规则直出，不走模型。
    # 纯视图（「缩放到中国」）不带取数词，仍走 fit_china 正常路径。
    china_scope_stats = bool(
        _mentions_china_scope(message)
        and re.search(r"查询|统计|计算|均值|平均值|多少|数值|取数|平均", message)
    )
    if china_scope_stats:
        reply = (
            "「中国 / 全国」不是系统里可统计的行政区范围——目前只做到**省级和地级市**，"
            "没有「中国全境」这一级掩膜，所以这次没有取数，也没有拿别的地区或全球整幅的数值顶替。\n\n"
            "两条路任选：\n"
            "① 换成具体的省或地级市（例如「河南省」「广州市」），我按行政边界统计；\n"
            "② 给我一个矩形范围（西、南、东、北四个经纬度，例如 [73, 18, 135, 53] 附近），"
            "我按这个框统计。"
        )
        return finish_direct(
            reply,
            provider_suffix="china-scope-rule",
            summary="「中国/全国」作为统计范围不可支持，已规则直出并给出替代口径",
        )

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

    # 「进这一轮之前」的会话状态快照。下面的 merge 会把**页面选中层**也补成基线
    # （为了让「其余不变」有东西可继承，详见 _state_patch_from_message），于是
    # 合并之后的状态**不再能回答「我上一轮到底记过什么」**——首轮新会话也会
    # 因为页面挂着层而看起来"有上文"。凡是"有没有上文"的判断必须用这个快照。
    state_before_turn = dict(topic_state)
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
    round_tools_anthropic = _tools_anthropic_for_message(message)
    round_tools_openai = _tools_openai_for_message(message)
    budget_tools = (
        round_tools_anthropic if protocol == "anthropic" else round_tools_openai
    )
    est_in = _estimate_prompt_tokens(
        system=system,
        history=history,
        message=message,
        tools=budget_tools,
    )
    if budget and est_in > budget:
        reply = _request_limit_reply()
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
                tools=round_tools_anthropic or None,
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
            seen_server_calls: set[str] = set()
            for hop in range(1, max_hops + 1):
                all_uses = _anthropic_tool_uses(data.get("content"))
                if not all_uses:
                    break
                current_signatures = {
                    f"{c['name']}:{json.dumps(c.get('args') or {}, sort_keys=True, ensure_ascii=False)}"
                    for c in all_uses
                    if c["name"] in _SERVER_TOOLS
                }
                if current_signatures and current_signatures <= seen_server_calls:
                    server_calls = []
                    steps.append(
                        {
                            "type": "thought",
                            "summary": "检测到重复工具请求，已停止重复查询",
                        }
                    )
                    break
                seen_server_calls.update(current_signatures)
                # 整轮总超时：到点停止继续取数，跳出后用已有结果收尾，不再外呼。
                if _deadline is not None and time.monotonic() > _deadline:
                    _timed_out = True
                    steps.append(
                        {
                            "type": "thought",
                            "summary": "整轮用时超过上限，已停止继续取数",
                        }
                    )
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
                    **_drop_model_day_over_month(
                        message,
                        topic_state,
                        _state_patch_from_tool_calls(all_uses, client_context),
                    ),
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
                    step_idx = len(steps)
                    steps.append(
                        {
                            "type": "tool",
                            "summary": _tool_step_summary(
                                str(sc["name"]), dict(sc.get("args") or {})
                            ),
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
                    # 记录补上「实际取数层」：工具可能已把 catalog_id 改写掉
                    steps[step_idx]["summary"] = _tool_step_summary(
                        str(sc["name"]), dict(sc.get("args") or {}), tres
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
                        tools=round_tools_anthropic,
                    )
                    if hop_est > budget:
                        raise AgentRequestLimitError(
                            f"工具多轮累计输入预估约 {hop_est} token，"
                            f"超过单次上限 {budget} token，已中止。"
                        )
                data = anthropic_compat.messages_create(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    system=system,
                    messages=messages,
                    tools=round_tools_anthropic or None,
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
                message,
                reply,
                steps,
                sid,
                client_context,
                state=topic_state,
                history_state=state_before_turn,
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
            # 区域口径兜底：县/区一级、或地名没认出来时，必须在正文里点明
            reply = _append_region_scope_note(message, reply, list(steps))
            # 量纲兜底：问「土壤水分的温度」这类变量不具备的量纲时，先澄清不硬给数
            reply = _guard_dimension_mismatch(message, reply)
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
            tools=round_tools_openai or None,
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
        seen_server_calls: set[str] = set()

        for hop in range(1, max_hops + 1):
            if not calls:
                break
            current_signatures = {
                f"{c['name']}:{json.dumps(c.get('args') or {}, sort_keys=True, ensure_ascii=False)}"
                for c in calls
                if c.get("name") in _SERVER_TOOLS
            }
            if current_signatures and current_signatures <= seen_server_calls:
                server_calls = []
                steps.append(
                    {
                        "type": "thought",
                        "summary": "检测到重复工具请求，已停止重复查询",
                    }
                )
                break
            seen_server_calls.update(current_signatures)
            hops_used = hop
            # 整轮总超时：到点停止继续取数，跳出后用已有结果收尾，不再外呼。
            if _deadline is not None and time.monotonic() > _deadline:
                _timed_out = True
                steps.append(
                    {
                        "type": "thought",
                        "summary": "整轮用时超过上限，已停止继续取数",
                    }
                )
                break
            # 同 Anthropic 分支：先快照这一跳之前的基线，再做 merge。
            # 否则粘性拿到的是「本次模型自己选的层」，判定必然放行。
            pre_call_state = topic_state
            # 同 Anthropic 分支：模型查过的层要记进会话状态
            topic_state = dialogue_state.merge(
                topic_state,
                **_drop_model_day_over_month(
                    message,
                    topic_state,
                    _state_patch_from_tool_calls(calls, client_context),
                ),
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
                step_idx = len(steps)
                steps.append(
                    {
                        "type": "tool",
                        "summary": _tool_step_summary(
                            str(sc["name"]), dict(sc.get("args") or {})
                        ),
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
                # 同上：记录里补出工具**实际读的那份产物**（粘性/目录映射会改写 id）
                steps[step_idx]["summary"] = _tool_step_summary(
                    str(sc["name"]), dict(sc.get("args") or {}), tres
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
                    tools=round_tools_openai,
                )
                if hop_est > budget:
                    raise AgentRequestLimitError(
                        f"工具多轮累计输入预估约 {hop_est} token，"
                        f"超过单次上限 {budget} token，已中止。"
                    )
            data = openai_compat.chat_completions(
                base_url=base_url,
                api_key=oai_key,
                model=model,
                messages=messages_oai,
                tools=round_tools_openai or None,
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
            # 整轮已超时则不再外呼模型补答，只用已有工具结果确定性合成。
            _final = _finalize_after_hop_limit(
                reply,
                list(steps),
                complete=(
                    None
                    if _timed_out
                    else lambda: _oai_complete_no_tools(
                        base_url=base_url,
                        api_key=oai_key,
                        model=model,
                        messages=messages_oai,
                        max_tokens=max_out,
                    )
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
            message,
            reply,
            steps,
            sid,
            client_context,
            state=topic_state,
            history_state=state_before_turn,
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
        # 同 Anthropic 分支：区域口径（县区级 / 地名认不出）必须在正文里点明
        reply = _append_region_scope_note(message, reply, list(steps))
        # 量纲兜底：问「土壤水分的温度」这类变量不具备的量纲时，先澄清不硬给数
        reply = _guard_dimension_mismatch(message, reply)
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
    except (LlmClientError, AgentRequestLimitError):
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


#: 用户**明确要求改画面**的动词。命中这些词 + 本轮零意图下发 + 正文却写完成态，
#: 就是「空口承诺」——模型嘴上说「已下发/已移除」，其实一条意图都没下发。
#: 2026-11-07 实测 r56/r58/r59：问「把这个图层删掉」，4 次里 2 次模型不调任何
#: 工具、不下发 remove_layer，却回「已下发移除…请求」。
_VIEW_WRITE_VERBS = re.compile(
    r"删|移除|删除|隐藏|显示|打开|添加|透明|定位|缩放|换底图|切(?:换)?底图|"
    r"切到|切至|跳到|切换|换成|换到|改为|调整时间|时间轴.{0,6}(?:设|改|切)|"
    r"播放|暂停|配色|着色|换个色|渐变色|符号化"
)
#: 正文里的「完成态」措辞——只有真正下发过意图才许出现。
#: 2026-11-08 补：模型还写过「已把「…」从图层面板移除」「已从…移除」，是「已+动词+宾语」
#: 的变体，不命中「已移除」固定词 → 补「已把/已从/已将」这类及物完成态开头。
_VIEW_DONE_WORDS = re.compile(
    r"已下发|已移除|已删除|已切换|已隐藏|已显示|已完成|已设置|已定位|已缩放|已暂停|已播放|"
    r"已把|已从|已将|已为|已关掉|已收起"
)

#: 「切换图层 + 日期」复合指令的两半：前半要求勾选某图层，后半要求切时间轴。
#: 2026-11-10 实测：同样一句「切换到风云动态图层，日期设到某天」，4 次里 1 次模型
#: 只下发 set_timeline、漏了 set_layer_visibility，正文却写「下发了显示 + 切时间轴」。
#: 这类「部分意图 + 正文夸大」现有零意图守卫（_guard_unclaimed_view_intent）拦不住，
#: 需要单独看「点名了图层却没勾选」这一半。
#: 2026-11-11 修（用户复测第 2 条：只切日期却被附加「没有勾选你要的图层」）：
#: 旧版把「切(到|回|换)」「图层」直接当图层动作词，而「切到」同样出现在日期说法里
#: （「把时间轴切到 12 月」），于是纯日期指令被判成复合指令，正文被整段改写成
#: 「没有勾选你要的图层」。现在要求**动作词与具名图层/变量同时出现**：句中没有
#: 可指代的图层名或变量名时，压根不存在「该勾哪一层」的问题，一律放行。
_LAYER_TARGET_WORDS = re.compile(
    r"图层|产品组|产品|这层|那层|这一层|那一层|本层|"
    r"土壤水|SM\b|VOD|植被光学|ω|omega|散射|"
    r"降水|降雨|气温|温度|蒸散|干旱|植被|"
    r"风云|SMAP|CMFD|GPCP|MODIS|NSMC",
    re.I,
)
_LAYER_VERB_WORDS = re.compile(
    r"切(?:换)?(?:到|至|回)|换(?:到|回|成)|显示|打开|勾选|取消勾选|"
    r"隐藏|关掉|关闭|收起|添加|移除|删除"
)
_DATE_SCOPE_WORDS = re.compile(
    r"\d{4}\s*年|\d{1,2}\s*月\s*\d{1,2}\s*日|日期|时间轴|切到.*(?:月|日|天)|"
    # 2026-11-11：补 ISO 写法。模型与前端回执都用 ``2025-12-15``，
    # 旧正则只认「2025年12月15日」，于是复合指令根本没被识别到。
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|"
    r"设(?:到|成|为).*(?:月|日|天)|哪(?:天|一日)"
)


def _guard_partial_layer_switch_intent(
    message: str, result: dict[str, Any]
) -> dict[str, Any]:
    """「切换图层到日期」这类复合指令：点名了图层却没勾选，正文不许说成两条都下发。

    只针对一种明确的情况：用户这句话既要求**勾选/显示某个具名图层或变量**，又要求
    **切日期/时间轴**（含日期数字或「日期/时间轴」），但本轮只下发了 ``set_timeline``、
    漏了 ``set_layer_visibility``，且正文写了完成态。

    2026-11-10 实测：模型偶发漏发 set_layer_visibility，却回「已下发显示 + 切时间轴」，
    用户看到时间轴动了、图层没勾上，还以为是操作没做完。这里把正文纠正成如实说明，
    不替它补发（补发需要准确的 catalog_id，模型这轮既然没给，说明没把握）。
    """
    try:
        text = message or ""
        # 必须同时命中「图层动作」「具名图层/变量」「日期」三层意思，才是复合指令。
        # 缺了具名对象一律不拦：只切日期的请求没有「该勾哪一层」这回事（2026-11-11）。
        if not _LAYER_VERB_WORDS.search(text):
            return result
        if not _LAYER_TARGET_WORDS.search(text):
            return result
        if not _DATE_SCOPE_WORDS.search(text):
            return result
        intents = result.get("ui_intents")
        if not isinstance(intents, list) or not intents:
            return result  # 零意图交给 _guard_unclaimed_view_intent 处理
        names = {str(i.get("name") or "") for i in intents if isinstance(i, dict)}
        # 图层已经勾选，或根本没切时间轴（不属于本守卫盯的「切了时间却漏勾选」），都不拦
        if "set_layer_visibility" in names:
            return result
        if "set_timeline" not in names:
            return result
        reply = result.get("reply")
        if not isinstance(reply, str) or not _VIEW_DONE_WORDS.search(reply):
            return result
        fixed = (
            "这次我只把时间轴切过去了，但**没有勾选你要的图层**（图层显示指令没有成功下发）。"
            "麻烦你再点一次图层名，我重新把图层显示出来。"
        )
        result = dict(result)
        result["reply"] = fixed
        logger.warning(
            "agent.intent.partial_layer_switch: timeline set but layer not shown; "
            "rewrote reply (was %d chars)",
            len(reply),
        )
    except Exception:  # pragma: no cover - 兜底，纠正失败不该影响对话
        logger.debug("guard partial layer switch intent failed", exc_info=True)
    return result


def _guard_unclaimed_view_intent(
    message: str, result: dict[str, Any]
) -> dict[str, Any]:
    """写视图请求若一条意图都没下发，正文不许写成「已下发/已移除」这种完成态。

    模型偶发地「口头承诺」：用户要删图层/调透明/换底图，它既不调工具、也不在
    ui_intents 里下发意图，直接回一句「已下发移除…」。前端拿不到任何意图，
    画面纹丝不动，用户却以为操作成功了。这道闸门只在「用户明确要求改画面 +
    本轮零意图 + 正文写了完成态」三者同时成立时，把正文纠正成如实说明。

    不替它补发意图——补发需要准确参数（删哪个 catalog_id、透明到多少），模型
    这一轮既然没给，说明它没把握；强行造参数比让用户重说一遍更危险。
    """
    try:
        text = message or ""
        if not _VIEW_WRITE_VERBS.search(text):
            return result
        intents = result.get("ui_intents")
        if isinstance(intents, list) and intents:
            return result
        reply = result.get("reply")
        if not isinstance(reply, str) or not _VIEW_DONE_WORDS.search(reply):
            return result
        fixed = (
            "我这次没能把操作下发到界面上（没有生成对应的界面指令）。"
            "麻烦你再说一遍要做什么，我重新下发；如果连续两次都没生效，"
            "可能是这一层正在计算中被拒绝，届时以界面提示为准。"
        )
        result = dict(result)
        result["reply"] = fixed
        logger.warning(
            "agent.intent.unclaimed: view-write requested but zero intents; "
            "rewrote reply (was %d chars)",
            len(reply),
        )
    except Exception:  # pragma: no cover - 兜底，纠正失败不该影响对话
        logger.debug("guard unclaimed view intent failed", exc_info=True)
    return result


_MUTATING_UI_INTENTS = frozenset(
    {
        "set_layer_visibility",
        "set_layer_opacity",
        "fit_layer",
        "fit_china",
        "zoom_to_china",
        "locate_coordinate",
        "fly_to_location",
        "fly_to",
        "switch_basemap",
        "set_basemap",
        "set_timeline",
        "set_timeline_playing",
        "remove_layer",
        "reorder_layer",
        "set_layer_symbology",
    }
)

#: 否定/只读限定：用户明说「不要/别/不许 + 动作」，或「只告诉我/只回答/保持原样/
#: 不要改动」。这类句子里虽然可能出现「打开/切换」等写动词，但语义是**禁止操作**，
#: 绝不能因为 _VIEW_WRITE_VERBS 命中写动词就放行模型顺手加的那些 UI 意图。
#: 2026-11-10 实测 A12/D01：「不要打开 GPCP，只告诉我单位」却切了选中图层+时间轴；
#: 「打开不存在的图层，别选其他」却显示了 GPCP——根因都是写动词放行掩盖了否定语义。
_NEGATION_OR_READONLY_HINT = re.compile(
    r"不要|别|不许|别把|无需|不用|不必|不需要|不要动|别动|保持(?:原样|不变|现状)|"
    r"只(?:告诉|回答|问|查|看|要)我|仅(?:告诉|回答|查|看)|"
    r"不改|不要改|别改|不许改|不要操作|不要选|别选|不许选|不要换|别换|"
    r"若(?:不存在|没有).{0,6}(?:说明|告知|告诉)|不存在.{0,6}(?:说明|告知)",
    re.I,
)

_MAP_ACTION_SPLIT = re.compile(r"(?:、|，|,|；|;|以及|并且|同时|和|及|再|然后)")


def _resolve_deterministic_map_actions(
    message: str,
    client_context: dict[str, Any] | None,
    *,
    unresolved: list[str] | None = None,
) -> list[dict[str, Any]] | None:
    """Resolve common multi-step layer/date commands without an LLM tool loop.

    ``unresolved``（2026-11-11 新增）用于回收「用户点名了、但图层库里定位不到」的
    子句，由 ``_map_actions_reply`` 写进回执的「未执行」段——否则多步指令只报成功项，
    用户看不出哪一步漏了。
    """
    text = str(message or "").strip()
    if not text or _NEGATION_OR_READONLY_HINT.search(text):
        return None
    if re.search(r"查询|统计|计算|均值|平均值|多少|数值|取数|工作流|运行", text):
        return None
    has_visibility = bool(
        re.search(r"显示|打开|添加|隐藏|关掉|关闭显示|hide|show", text, re.I)
    )
    has_date = bool(
        re.search(r"切到|切至|跳到|日期|时间轴|设到|设为|改到", text)
        and re.search(r"(?:19|20)\d{2}(?:[-/年]\d{1,2}){2}|(?<!\d)\d{8}(?!\d)", text)
    )
    if not has_visibility and not has_date:
        return None
    try:
        from app.services.agent import mock_orchestrator as _mo

        layers = _mo._normalize_layers(client_context)
        intents: list[dict[str, Any]] = []
        seen: set[tuple[str, bool]] = set()
        inherited_visible = not bool(re.search(r"隐藏|关掉|关闭显示|hide", text, re.I))
        clauses = [p.strip() for p in _MAP_ACTION_SPLIT.split(text) if p.strip()]
        for clause in clauses:
            if not re.search(
                r"图层|降水|土壤水|VOD|植被光学|ω|omega|散射", clause, re.I
            ):
                continue
            pick = _mo._resolve_layer(clause, layers, allow_demo_fallback=False)
            if pick is None:
                pick = _mo._catalog_pick(clause)
            if pick is None:
                # 第二个并列对象常省略动作词；用整句再解析一次作为最后尝试。
                pick = _mo._resolve_layer(clause, layers, allow_demo_fallback=True)
            if pick is None:
                # 2026-11-11：以前这里静默丢弃，用户点名 3 个只解析出 2 个时
                # 第 3 个在回执里彻底消失，成了「笼统说没执行」。记下来交给回执。
                if unresolved is not None:
                    label = re.sub(r"^(?:请|帮我|把|将|再|然后|同时|并且)+", "", clause)
                    label = re.sub(
                        r"(?:显示|打开|添加|隐藏|关掉|关闭显示|show|hide)出来?$",
                        "",
                        label.strip(),
                    ).strip(" 的了")
                    unresolved.append(label or clause)
                continue
            if re.search(r"隐藏|关掉|关闭显示|hide", clause, re.I):
                visible = False
            elif re.search(r"显示|打开|添加|show", clause, re.I):
                visible = True
            else:
                visible = inherited_visible
            key = (pick.catalog_id, visible)
            if key in seen:
                continue
            seen.add(key)
            intents.append(
                {
                    "name": "set_layer_visibility",
                    "args": {
                        "catalog_id": pick.catalog_id,
                        "visible": visible,
                        "display_name": pick.name,
                    },
                }
            )
        if has_date:
            day = _mo._parse_date_arg(text)
            if day:
                args: dict[str, Any] = {"date": day}
                shown = [
                    i
                    for i in intents
                    if i["name"] == "set_layer_visibility"
                    and i["args"].get("visible") is True
                ]
                if shown:
                    args["catalog_id"] = shown[-1]["args"]["catalog_id"]
                intents.append({"name": "set_timeline", "args": args})
        if not intents:
            return None
        visibility_count = sum(
            1 for item in intents if item["name"] == "set_layer_visibility"
        )
        # 单一显隐继续走既有捷径/模型路径；这里只接管真正的复合操作。
        # 例外（2026-11-11）：用户点名了多个目标、但其中有定位不到的（unresolved 非空）——
        # 这时必须接管，才能如实报「做成了哪几个、哪个没做」，交给模型反而会笼统带过。
        if has_visibility and not has_date and visibility_count < 2 and not unresolved:
            return None
        # A composite request must not be partially claimed as successful.
        if has_visibility and not any(
            i["name"] == "set_layer_visibility" for i in intents
        ):
            return None
        if has_date and not any(i["name"] == "set_timeline" for i in intents):
            return None
        return intents
    except Exception:  # pragma: no cover
        logger.debug("deterministic map action parsing failed", exc_info=True)
        return None


def _map_actions_reply(
    intents: list[dict[str, Any]],
    unresolved: list[str] | None = None,
) -> str:
    shown: list[str] = []
    hidden: list[str] = []
    day = ""
    for intent in intents:
        args = intent.get("args") if isinstance(intent.get("args"), dict) else {}
        if intent.get("name") == "set_layer_visibility":
            name = str(args.get("display_name") or args.get("catalog_id") or "图层")
            (shown if args.get("visible") is True else hidden).append(name)
        elif intent.get("name") == "set_timeline":
            day = str(args.get("date") or "")
    parts: list[str] = []
    if shown:
        parts.append("已显示" + "、".join(f"「{x}」" for x in shown))
    if hidden:
        parts.append("已隐藏" + "、".join(f"「{x}」" for x in hidden))
    if day:
        parts.append(f"日期已切换到 {day}")
    # 2026-11-11 用户复测第 4 条：多步指令只报成功项，漏做的那一步彻底消失，
    # 用户只看到「已隐藏 CMFD」，以为 VOD 也做了。这里把没定位到的目标点名列出。
    if unresolved:
        uniq = list(dict.fromkeys(x for x in unresolved if x))
        if uniq:
            brief = "、".join(f"「{x}」" for x in uniq[:3])
            more = f" 等 {len(uniq)} 项" if len(uniq) > 3 else ""
            parts.append(
                f"另有 {brief}{more} 这一步**没有执行**——图层库里没定位到对应图层"
            )
    return "；".join(parts) + "。"


def _resolve_simple_visibility(
    message: str, client_context: dict[str, Any] | None
) -> dict[str, Any] | None:
    """纯图层显隐的确定性解析：命中则返回可直接下发的 intent，否则 None。

    2026-11-10 老师复测用例 04：一句「只显示风云…组中的植被光学厚度，保持其他
    不变」，模型却 search_layers×3 + get_layer_meta 查满 4 跳预算、没轮到下发显示
    就答「工具次数用完」。显隐没有取数语义，目标层往往就挂在页面上，一步定位、
    一步下发即可，不耗工具预算。

    关键：**不信任 mock_chat**（它对带「微波反演产品—平均散射约束模型组」目录描述
    的复杂显隐句会把「显示植被光学厚度」错解析成「显示土壤水分」），而是直接用
    ``_resolve_layer`` 精确解析（其内部已保证命中的名字片段一定出现在消息里）。
    解析不到就返回 None，由调用方 fall through 交给模型，绝不直出一个可能串层的意图。
    """
    if not re.search(
        r"只显示|只留|仅显示|单独显示|只打开|显示|打开|隐藏|关掉|关闭显示",
        message or "",
        re.I,
    ):
        return None
    # 排除取数/统计/工作流/底图/时间轴等非纯显隐语义
    if re.search(
        r"查询|统计|计算|均值|平均值|多少|数值|取数|工作流|运行|跑一下|提交",
        message or "",
    ):
        return None
    if re.search(
        r"底图|basemap|天地图|高德|esri|osm|openstreetmap", message or "", re.I
    ):
        return None
    if re.search(r"切到|切至|跳到|时间轴|日期|定位|飞到|缩放到", message or ""):
        return None
    try:
        from app.services.agent import mock_orchestrator as _mo

        layers = _mo._normalize_layers(client_context)
        pick = _mo._resolve_layer(message or "", layers, allow_demo_fallback=False)
        if pick is None:
            return None
        visible = not re.search(r"隐藏|关掉|关闭显示|hide", message or "", re.I)
        return {
            "name": "set_layer_visibility",
            "args": {
                "catalog_id": pick.catalog_id,
                "visible": visible,
                "display_name": pick.name,
            },
        }
    except Exception:  # pragma: no cover - 解析失败不该拦住这一轮
        logger.debug("simple_visibility 规则解析失败", exc_info=True)
        return None


def _guard_read_only_ui_intents(message: str, result: dict[str, Any]) -> dict[str, Any]:
    """只读提问不允许模型顺手新增图层、切时间或改变地图视图。"""

    try:
        # 否定/只读限定优先于写动词判定：用户说「不要打开 X」「只告诉我单位，
        # 保持原样」时，哪怕句子里有「打开」这类写动词，也是**禁止操作**，
        # 一律清空 mutating intents（2026-11-10 A12/D01 实测）。
        if _NEGATION_OR_READONLY_HINT.search(message or ""):
            intents = result.get("ui_intents")
            if isinstance(intents, list) and intents:
                kept = [
                    item
                    for item in intents
                    if not (
                        isinstance(item, dict)
                        and str(item.get("name") or "") in _MUTATING_UI_INTENTS
                    )
                ]
                if len(kept) != len(intents):
                    result = dict(result)
                    result["ui_intents"] = kept
                    reply = str(result.get("reply") or "").rstrip()
                    note = "本次是只读请求，没有改变地图上的图层、时间或显示状态。"
                    if note not in reply:
                        result["reply"] = f"{reply}\n\n{note}" if reply else note
                    logger.warning(
                        "agent.intent.negation: removed %d mutating intents",
                        len(intents) - len(kept),
                    )
            return result
        if _VIEW_WRITE_VERBS.search(message or ""):
            return result
        intents = result.get("ui_intents")
        if not isinstance(intents, list) or not intents:
            return result
        kept = [
            item
            for item in intents
            if not (
                isinstance(item, dict)
                and str(item.get("name") or "") in _MUTATING_UI_INTENTS
            )
        ]
        if len(kept) == len(intents):
            return result
        result = dict(result)
        result["ui_intents"] = kept
        reply = str(result.get("reply") or "").rstrip()
        note = "本次是只读查询，没有改变地图上的图层、时间或显示状态。"
        if note not in reply:
            result["reply"] = f"{reply}\n\n{note}" if reply else note
        logger.warning(
            "agent.intent.read_only: removed %d mutating intents",
            len(intents) - len(kept),
        )
    except Exception:  # pragma: no cover
        logger.debug("guard read-only intents failed", exc_info=True)
    return result


def _explicit_map_variable(text: str) -> str | None:
    cleaned = str(text or "")
    hits: set[str] = set()
    if re.search(r"降水|降雨|precip|rain", cleaned, re.I):
        hits.add("precip")
    variable = dialogue_state.variable_from_text(cleaned)
    if variable:
        hits.add(variable)
    return next(iter(hits)) if len(hits) == 1 else None


def _intent_layer_variable(intent: dict[str, Any]) -> str | None:
    args = intent.get("args") if isinstance(intent.get("args"), dict) else {}
    text = " ".join(
        str(args.get(key) or "") for key in ("display_name", "catalog_id", "layer_id")
    )
    if re.search(r"降水|降雨|precip|rain", text, re.I):
        return "precip"
    return dialogue_state.variable_from_name(text)


def _guard_layer_variable_intents(
    message: str, result: dict[str, Any]
) -> dict[str, Any]:
    """Never execute a layer action for a different explicit variable."""
    requested = _explicit_map_variable(message)
    if requested is None:
        return result
    intents = result.get("ui_intents")
    if not isinstance(intents, list) or not intents:
        return result
    kept: list[dict[str, Any]] = []
    rejected = False
    for item in intents:
        if not isinstance(item, dict) or item.get("name") not in {
            "set_layer_visibility",
            "remove_layer",
            "fit_layer",
        }:
            kept.append(item)
            continue
        actual = _intent_layer_variable(item)
        if actual is not None and actual != requested:
            rejected = True
            continue
        kept.append(item)
    if not rejected:
        return result
    result = dict(result)
    result["ui_intents"] = kept
    labels = {
        "precip": "降水",
        "sm": "土壤水分",
        "vod": "植被光学厚度",
        "omega": "等效散射 ω",
    }
    result["reply"] = (
        f"没有执行图层操作：识别到的目标不是你要求的“{labels.get(requested, requested)}”图层。"
        "请明确图层名称后重试。"
    )
    logger.warning("agent.intent.variable_mismatch requested=%s", requested)
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
            _guard_partial_layer_switch_intent(
                message,
                _guard_unclaimed_view_intent(
                    message,
                    _order_ui_intents(
                        _guard_layer_variable_intents(
                            message,
                            _guard_read_only_ui_intents(
                                message,
                                _run_chat_impl(
                                    message,
                                    session_id=session_id,
                                    client_context=client_context,
                                    user_id=user_id,
                                    cred=cred,
                                    on_event=on_event,
                                ),
                            ),
                        ),
                        client_context,
                    ),
                ),
            )
        )
    except ValueError:
        # 参数/配置类错误（消息过长、无配置档）仍交给路由转 422，
        # 不属于「服务不可用」，不该被降级吞掉。
        raise
    except AgentRequestLimitError as exc:
        logger.info("agent request limited: %s", exc)
        return _degraded_result(
            session_id=session_id,
            reply=_request_limit_reply(),
            provider="limited",
            reason=str(exc),
            on_event=on_event,
        )
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
