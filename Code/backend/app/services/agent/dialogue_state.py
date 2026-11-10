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

import json
import re
from typing import Any

#: 只有这几个键会被持久化（其余键一律丢弃，避免把任意内容写进会话文件）。
#: ``var_layers`` 是「变量 → 取数产物 id」的跨轮映射（2026-11-09 加）：防
#: 产品粘性被非三变量层（如 CMFD 降水）覆盖后丢版本。存成 JSON 字符串。
KEYS: tuple[str, ...] = (
    "layer_id",
    "layer_name",
    "variable",
    "region",
    "date",
    "var_layers",
)

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


#: 产品族名里的「散射」二字不是变量名：三套产品的全名都是「动态/平均散射约束产品」，
#: 留着它会让「SMAP 动态散射约束产品的土壤水分」同时命中 sm 与 omega，按
#: 「多命中即放弃」的规则直接返回 None —— 变量一致性防线（问土壤水分却拿 ω 算）
#: 因此整句失效。先剥掉族名，再认变量。2026-11-07 五句连问实测到。
_FAMILY_NOISE = re.compile(r"(?:(?:动态|平均)\s*)?散射约束(?:产品)?", re.I)


def variable_from_text(text: str) -> str | None:
    """从用户这句话里认出变量口径；一句话点了多个变量时返回 ``None``（不猜）。"""
    if not text:
        return None
    cleaned = _FAMILY_NOISE.sub(" ", str(text))
    hits = {var for pattern, var in _VARIABLE_PATTERNS if pattern.search(cleaned)}
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
    # var_layers 是 JSON 字符串，不按普通文本截断；解析失败就整条丢弃（不留脏数据）。
    var_layers_raw = out.get("var_layers")
    if var_layers_raw:
        parsed = _parse_var_layers(var_layers_raw)
        if parsed is None:
            out.pop("var_layers", None)
        else:
            out["var_layers"] = _dump_var_layers(parsed)
    # 层名与变量自相矛盾时**以层名为准**：层名是「这一层到底是什么」的直接证据，
    # variable 是从它推出来的。2026-11-06 实盘见过 {layer_name: 等效散射 ω,
    # variable: sm}——这种状态会让提示词自己打架，模型于是再去挑一个「同变量」
    # 的层，越挑越偏。
    name_var = variable_from_name(out.get("layer_name") or "")
    if name_var and out.get("variable") and name_var != out["variable"]:
        out["variable"] = name_var
    return out


def _parse_var_layers(raw: str) -> dict[str, str] | None:
    """把 var_layers 的 JSON 字符串解析成变量→层映射；非法返回 None。"""
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    out: dict[str, str] = {}
    for var, lid in obj.items():
        if var not in VARIABLE_LABELS:
            continue
        lid_text = str(lid).strip()[:_MAX_LEN]
        if lid_text:
            out[var] = lid_text
    return out or None


def _dump_var_layers(mapping: dict[str, str]) -> str:
    """把变量→层映射序列化成 var_layers 的 JSON 字符串。"""
    return json.dumps(mapping, ensure_ascii=False, sort_keys=True)


def var_layers_mapping(state: Any) -> dict[str, str]:
    """读出会话里「变量 → 层」的跨轮映射（空状态返回空 dict）。"""
    clean = sanitize(state)
    return _parse_var_layers(clean.get("var_layers") or "") or {}


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
    # var_layers 是「变量→层」的跨轮累积映射，不能像单值字段那样整条覆盖：
    # 否则「SM→CMFD→SM」里最后一次 merge 会把之前记的 sm 条目冲掉，产品粘性
    # 又退回单槽。这里把 patch 里的 var_layers 与旧映射按变量合并。
    incoming_var_layers = patch.pop("var_layers", None)
    for key, value in patch.items():
        if key not in KEYS or value is None:
            continue
        text = str(value).strip()[:_MAX_LEN]
        if text:
            state[key] = text
    if incoming_var_layers:
        mapping = var_layers_mapping(state)
        parsed = _parse_var_layers(str(incoming_var_layers)) or {}
        for var, lid in parsed.items():
            mapping[var] = lid
        state["var_layers"] = _dump_var_layers(mapping)
    return sanitize(state)


def remember_var_layer(state: Any, *, variable: str, layer_id: str) -> dict[str, str]:
    """在会话状态里追加/更新「变量 → 层」映射，返回新状态。

    2026-11-09 加：产品粘性原来只记单槽 ``layer_id``，被非三变量层（CMFD 降水）
    覆盖后，三变量层（sm/vod/omega）的版本记忆就丢了——「切回土壤水分」只能靠
    模型重新自选版本，口径静默漂移（单日帧 ↔ 8 天块）。这里给每个变量单独记
    一份它最近用过的产物 id，互不覆盖；只收三变量，其余变量（降水等）不写。
    """
    if variable not in VARIABLE_LABELS:
        return sanitize(state)
    lid = str(layer_id or "").strip()[:_MAX_LEN]
    if not lid:
        return sanitize(state)
    mapping = var_layers_mapping(state)
    mapping[variable] = lid
    clean = sanitize(state)
    clean["var_layers"] = _dump_var_layers(mapping)
    return clean


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
