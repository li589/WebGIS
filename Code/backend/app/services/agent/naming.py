"""用户可见文案工具：正文只说人话，内部 id 只留给过程面板。

背景（用户 2026-10-21 反馈）：问「有什么图层」时回复成
「风云卫星反演（id：123456677）」，用户完全看不懂。

根因不是模型表达差，而是 demo 规则引擎与兜底文案把 ``catalog_id`` /
``layer_id`` / ``instance_id`` 拼进了正文（9 + 4 处），甚至把工具返回的
整段 JSON 截断后糊进回复。本模块收敛成唯一入口：

- 正文：只用图层的**中文显示名**，查不到名字就说「该图层」，绝不吐 id。
- 过程面板（``steps``）：id 照旧保留，排查问题时不丢信息。

约定：``human_layer_name`` 永远不返回空串，调用方不必再做兜底。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

#: 查不到中文名时的通用称呼。宁可含糊，也不要把 imported-xxx 甩给用户。
UNKNOWN_LAYER_NAME = "该图层"

#: 数值超过这个位数才考虑做千分位/科学计数，避免 0.123 被格式化成 0.12
_DEFAULT_DIGITS = 3


def _clean(value: Any) -> str:
    return str(value or "").strip()


def build_layer_name_map(
    client_context: Mapping[str, Any] | None,
) -> dict[str, str]:
    """从 client_context.active_layers 提取 ``catalog_id -> 中文名`` 映射。"""
    out: dict[str, str] = {}
    if not isinstance(client_context, Mapping):
        return out
    layers = client_context.get("active_layers")
    if not isinstance(layers, Sequence) or isinstance(layers, (str, bytes)):
        return out
    for item in layers:
        if not isinstance(item, Mapping):
            continue
        cid = _clean(item.get("catalog_id"))
        name = _clean(item.get("name"))
        if cid and name and name != cid:
            out[cid] = name
    return out


def is_internal_id(text: str) -> bool:
    """粗判一段文字是不是内部 id（不该出现在正文里）。

    命中 ``imported-xxxx`` / ``wf-run-xxx`` / ``20251201_20260201`` /
    纯数字长串这类形态。
    """
    t = _clean(text)
    if not t:
        return False
    if t.isdigit() and len(t) >= 6:
        return True
    lowered = t.casefold()
    for prefix in ("imported-", "wf-run-", "wf-", "run-", "layer-", "overlay-"):
        if lowered.startswith(prefix):
            return True
    # 8 位日期帧 20251201 或多日窗口 20251201_20251231
    if len(t) in (8, 17) and t.replace("_", "").isdigit():
        return True
    return False


def human_layer_name(
    catalog_id: str | None,
    client_context: Mapping[str, Any] | None = None,
    *,
    default: str | None = None,
) -> str:
    """把 catalog_id 翻成中文名；翻不出来就给通用称呼，**绝不返回 id**。"""
    cid = _clean(catalog_id)
    if cid:
        mapped = build_layer_name_map(client_context).get(cid)
        if mapped:
            return mapped
    fallback = _clean(default)
    if fallback and not is_internal_id(fallback):
        return fallback
    return UNKNOWN_LAYER_NAME


def join_layer_names(
    catalog_ids: Sequence[str],
    client_context: Mapping[str, Any] | None = None,
    *,
    limit: int = 5,
) -> str:
    """把若干 id 拼成「A、B、C」这样一句中文，超出部分用「等 N 个」收尾。"""
    names: list[str] = []
    seen: set[str] = set()
    for cid in catalog_ids:
        name = human_layer_name(cid, client_context)
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    if not names:
        return UNKNOWN_LAYER_NAME
    if len(names) > limit:
        return "、".join(names[:limit]) + f" 等 {len(names)} 个图层"
    return "、".join(names)


def fmt_value(
    value: Any, unit: str | None = None, *, digits: int = _DEFAULT_DIGITS
) -> str:
    """数值 + 单位的可读写法：``0.123 m³/m³``，而不是 ``0.12345678``。"""
    u = _clean(unit)
    if value is None:
        return "无值"
    if isinstance(value, bool):
        return ("是" if value else "否") + (f" {u}" if u else "")
    if isinstance(value, (int, float)):
        num = float(value)
        if num != num or num in (float("inf"), float("-inf")):
            return "无值"
        if num == 0:
            text = "0"
        elif abs(num) >= 1000:
            text = f"{num:,.2f}".rstrip("0").rstrip(".")
        elif abs(num) >= 1:
            text = f"{num:.{digits}f}".rstrip("0").rstrip(".")
        else:
            text = f"{num:.{max(digits, 4)}f}".rstrip("0").rstrip(".")
        return f"{text} {u}".strip()
    text = _clean(value)
    return f"{text} {u}".strip() if u else text


def layer_brief(
    catalog_id: str,
    client_context: Mapping[str, Any] | None = None,
    *,
    display_name: str | None = None,
) -> str:
    """图层简介一行：``土壤水分（SMAP 平均）``，不含任何 id。"""
    return human_layer_name(catalog_id, client_context, default=display_name)
