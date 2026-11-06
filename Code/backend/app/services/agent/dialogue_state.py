"""会话级「取数对象」状态：这一轮到底在讲哪一层、哪个变量、哪个区域、哪一天。

## 为什么需要它（2026-11-06 定位结论）

外部测试三条失败（切换后产品被换掉、「其余不变」把区域丢了、兜底补的是页面
当前层全幅数据）看起来是三个 bug，实际上是同一个缺口：**服务端没有任何地方
记着上一轮说的是谁**。选层只看本轮文本，抠不到就回落到「页面当前选中层」；
区域解析失败就直接退回全幅。补关键词、补正则都只能在「这一句恰好说得像」时
生效，说不像就必然错——而且错得很像真的。

所以这里把「本会话已确认的对象」显式存下来，每轮：

1. 先从会话文件读出来（``session_store.load_topic_state``）；
2. 与本轮文本解析出的实体合并：**用户这轮提到的项覆盖旧值，没提到的沿用**；
3. 取数一律用合并后的对象，不再看「页面当前选中层」的脸色；
4. 本轮结束后写回（``session_store.append_turn(state=...)``）。

状态与聊天消息存在**同一个 json** 里（``state`` 键），因此自动共用会话的
TTL 清理与每用户配额，不引入新的文件类别。
"""

from __future__ import annotations

import re
from typing import Any

#: 只有这五个键会被持久化（其余键一律丢弃，避免把任意内容写进会话文件）。
KEYS: tuple[str, ...] = ("layer_id", "layer_name", "variable", "region", "date")

#: 单字段最大长度（区域名、日期都很短，超长一律截断）
_MAX_LEN = 64

#: 变量口径：只认这三类。值是前端/工具都能理解的短标识。
VARIABLE_SM = "sm"
VARIABLE_VOD = "vod"
VARIABLE_OMEGA = "omega"

#: 变量识别表。与 ``mock_orchestrator._LAYER_ALIASES`` 同源，但这里只判变量，
#: 不判图层——图层要靠「页面上的实际层」来定。
_VARIABLE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"vod|植被光学厚度|光学厚度", re.I), VARIABLE_VOD),
    (
        re.compile(r"土壤水|土壤湿|含水量|墒情|(?<![a-z])sm(?![a-z])", re.I),
        VARIABLE_SM,
    ),
    (re.compile(r"omega|ω|散射", re.I), VARIABLE_OMEGA),
)

#: 变量 → 中文说法（写进回复与提示词，不出现内部标识）
VARIABLE_LABELS: dict[str, str] = {
    VARIABLE_SM: "土壤水分",
    VARIABLE_VOD: "植被光学厚度",
    VARIABLE_OMEGA: "等效散射 ω",
}


def variable_from_text(text: str) -> str | None:
    """从用户这句话里认出变量口径；一句话点了多个变量时返回 ``None``（不猜）。"""
    if not text:
        return None
    hits = {var for pattern, var in _VARIABLE_PATTERNS if pattern.search(text)}
    if len(hits) == 1:
        return next(iter(hits))
    return None


#: 图层名 → 变量。**不能复用变量识别表**：产品的族名里都带「散射约束产品」，
#: 那串「散射」会把每一层都判成 ω，而 VOD 层名里同时有「VOD」和「散射」，
#: 用「多命中即放弃」的规则会得到 None（2026-11-06 实测：四层 VOD 因此全部认不出）。
#: 层名是结构化文本，按「最具体的变量词优先」逐条判即可。
_NAME_VARIABLE_ORDER: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"vod|植被光学厚度", re.I), VARIABLE_VOD),
    (re.compile(r"土壤水|土壤湿|含水量|墒情"), VARIABLE_SM),
    (re.compile(r"ω|omega", re.I), VARIABLE_OMEGA),
)


def variable_from_name(name: str) -> str | None:
    """从图层显示名里认出变量（层名里通常就写着「土壤水分 / VOD / ω」）。"""
    text = name or ""
    for pattern, var in _NAME_VARIABLE_ORDER:
        if pattern.search(text):
            return var
    return None


def sanitize(raw: Any) -> dict[str, str]:
    """把任意来源的 dict 收敛成合法状态；非法内容一律丢弃。"""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key in KEYS:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()[:_MAX_LEN]
        if text:
            out[key] = text
    variable = out.get("variable")
    if variable and variable not in VARIABLE_LABELS:
        out.pop("variable", None)
    # 层名与变量自相矛盾时**以层名为准**：层名是「这一层到底是什么」的直接证据，
    # variable 是从它推出来的。2026-11-06 实盘见过 {layer_name: 等效散射 ω,
    # variable: sm}——这种状态会让提示词自己打架，模型于是再去挑一个「同变量」
    # 的层，越挑越偏。
    name_var = variable_from_name(out.get("layer_name") or "")
    if name_var and out.get("variable") and name_var != out["variable"]:
        out["variable"] = name_var
    return out


def merge(previous: Any, **patch: Any) -> dict[str, str]:
    """把本轮解析出的实体合并进旧状态。

    ``patch`` 里值为 ``None`` / 空串表示「本轮没提到」⇒ 保留旧值；
    要显式清空请传 ``clear={"region"}``。这条规则正是「其余不变」能成立的前提：
    用户只说日期时，其余字段原样带过去。
    """
    state = sanitize(previous)
    clear = patch.pop("clear", None)
    if isinstance(clear, (set, frozenset, list, tuple)):
        for key in clear:
            state.pop(str(key), None)
    for key, value in patch.items():
        if key not in KEYS or value is None:
            continue
        text = str(value).strip()[:_MAX_LEN]
        if text:
            state[key] = text
    return sanitize(state)


def describe(state: Any) -> str:
    """给提示词用的一句话描述；空状态返回空串（不占 token）。"""
    clean = sanitize(state)
    if not clean:
        return ""
    parts: list[str] = []
    if clean.get("layer_name"):
        parts.append(f"图层「{clean['layer_name']}」")
    elif clean.get("variable"):
        parts.append(
            f"变量「{VARIABLE_LABELS.get(clean['variable'], clean['variable'])}」"
        )
    if clean.get("region"):
        parts.append(f"区域「{clean['region']}」")
    if clean.get("date"):
        parts.append(f"日期 {clean['date']}")
    if not parts:
        return ""
    return "；".join(parts)


def identity_matches(state: Any, *, layer_id: str | None = None) -> bool:
    """这一层的 id 是否就是状态里记着的那一层。"""
    clean = sanitize(state)
    recorded = clean.get("layer_id")
    if not recorded or not layer_id:
        return False
    return recorded == str(layer_id).strip()
