"""Mock agent orchestrator — keyword rules + UI intents (no real LLM).

``reply`` 一律只写人话：用图层的中文显示名，**不出现任何内部 id**
（``catalog_id`` / ``instance_id`` / ``overlay-xxx``）。id 只随 ``ui_intents``
的 ``args`` 传给前端执行，以及在过程面板里留痕。

用户 2026-10-21 反馈：问「有哪些图层」回的是「风云卫星反演（id：123456677）」，
看不懂。此前本文件有 9 处把 id 拼进正文，已全部改为中文名。
"""

from __future__ import annotations

import datetime
import re
import uuid
from typing import Any

from app.services.agent import dialogue_state
from app.services.agent.naming import (
    build_layer_name_map,
    human_layer_name,
    join_layer_names,
)

# Demo catalog ids used when client context has no match
_DEMO_PRECIP = "cmfd-precip-cn"
#: (正则, catalog_id, 中文名)。第三项用于回复文案，切勿再吐 id。
_DEMO_FALLBACKS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"cmfd|降水|precip|rain", re.I), _DEMO_PRECIP, "CMFD 区域降水"),
    (re.compile(r"dem|etopo|高程|地形", re.I), "dem-etopo", "ETOPO 高程"),
    (re.compile(r"clcd|土地|土地利用|land\s*cover", re.I), "clcd-cn", "CLCD 土地利用"),
    (re.compile(r"co2|二氧化碳", re.I), "co2-cn", "CO2 浓度"),
]

# Well-known city centers (WGS84) for demo locate heuristics
_CITY_COORDS: list[tuple[re.Pattern[str], float, float, str]] = [
    (re.compile(r"北京|beijing", re.I), 116.4074, 39.9042, "北京"),
    (re.compile(r"上海|shanghai", re.I), 121.4737, 31.2304, "上海"),
    (re.compile(r"广州|guangzhou", re.I), 113.2644, 23.1291, "广州"),
    (re.compile(r"深圳|shenzhen", re.I), 114.0579, 22.5431, "深圳"),
    (re.compile(r"成都|chengdu", re.I), 104.0665, 30.5723, "成都"),
    (re.compile(r"武汉|wuhan", re.I), 114.3055, 30.5928, "武汉"),
    (re.compile(r"西安|xian|xi'?an", re.I), 108.9398, 34.3416, "西安"),
    (re.compile(r"杭州|hangzhou", re.I), 120.1551, 30.2741, "杭州"),
]

_BASEMAP_HINTS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"天地图\s*(影像|卫星)|tianditu[-_\s]?img|影像底图", re.I),
        "tianditu-img",
        "天地图影像",
    ),
    (
        re.compile(r"天地图\s*(矢量|街道|电子)|tianditu[-_\s]?vec|矢量底图", re.I),
        "tianditu-vec",
        "天地图矢量",
    ),
    (
        re.compile(r"高德\s*(影像|卫星)|gaode[-_\s]?sat", re.I),
        "gaode-satellite",
        "高德影像",
    ),
    (
        re.compile(r"高德|gaode[-_\s]?street|街道底图", re.I),
        "gaode-street",
        "高德街道",
    ),
    (
        re.compile(r"esri\s*(imagery|影像)|esri[-_\s]?imagery", re.I),
        "esri-imagery",
        "Esri 影像",
    ),
    (re.compile(r"osm|openstreetmap", re.I), "osm-standard", "OSM 标准"),
]


class LayerPick:
    """一次图层指向：内部 id 给前端用，中文名给用户看。"""

    __slots__ = ("catalog_id", "name")

    def __init__(self, catalog_id: str, name: str) -> None:
        self.catalog_id = catalog_id
        self.name = name


def _known_label(catalog_id: str) -> str | None:
    """内置演示图层的已知中文名（前端没上报 name 时兜底用）。"""
    for _pattern, cid, label in _DEMO_FALLBACKS:
        if cid == catalog_id:
            return label
    return None


def _normalize_layers(client_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not client_context:
        return []
    raw = client_context.get("active_layers")
    if isinstance(raw, list):
        out: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("catalog_id") or "").strip()
            if not cid:
                continue
            name = str(item.get("name") or "").strip()
            if not name or name == cid:
                # 前端没给中文名（或直接拿 id 当名）时，不把 id 暴露给用户
                name = _known_label(cid) or f"图层 {len(out) + 1}"
            entry: dict[str, Any] = {
                "catalog_id": cid,
                "instance_id": str(item.get("instance_id") or ""),
                "name": name,
            }
            # 产物目录 id 必须一起带上：会话状态里记的往往是 imported-*，
            # 而 catalog_id 是目录编号 method-*，只比 catalog_id 永远对不上
            # （2026-11-07「只改区域却换了产品」的根因之一）。
            overlay_id = str(item.get("overlay_layer_id") or "").strip()
            if overlay_id:
                entry["overlay_layer_id"] = overlay_id
            # 与真模型路径保持一致：可见 / 选中状态（原生 bool）
            if item.get("visible") is not None:
                entry["visible"] = bool(item.get("visible"))
            if item.get("selected") is not None:
                entry["selected"] = bool(item.get("selected"))
            out.append(entry)
        return out
    ids = client_context.get("active_catalog_ids")
    if isinstance(ids, list):
        out = []
        for index, raw_id in enumerate(ids, start=1):
            cid = str(raw_id).strip()
            if not cid:
                continue
            out.append(
                {
                    "catalog_id": cid,
                    "instance_id": "",
                    # 只有 id 时先按已知图层反查中文名，仍查不到就按序号称呼
                    "name": _known_label(cid) or f"图层 {index}",
                }
            )
        return out
    return []


def _bare_layer_id(layer_id: str) -> str:
    """剥掉 ``imports/`` 前缀的空壳 id，仅用于「是不是同一层」的比较。

    前端传上来的 ``overlay_layer_id`` 有时带 ``imports/``，会话状态里存的是裸 id；
    不归一化就永远判不出「这就是上一轮那一层」。
    """
    lid = str(layer_id or "").strip().lstrip("/")
    if lid.startswith("imports/"):
        rest = lid[len("imports/") :]
        if rest.startswith(("imported-", "imports-")):
            return rest
    return lid


def _display(layer: dict[str, Any]) -> str:
    """活动图层列表项的中文名（``_normalize_layers`` 已保证不会是 id）。"""
    return str(layer.get("name") or "").strip() or "该图层"


def _name_keys(layer: dict[str, str]) -> list[str]:
    """图层名的可匹配片段，从长到短。

    用户很少念完整名字——「风云卫星反演（土壤水分）」他只会说「风云」。
    因此除全名外，还要试：去括号后的主体、按标点切开的片段、中文名前两字。
    命中越长的片段越可信；同等长度命中多个图层则视为歧义，交给调用方反问。
    """
    name = _display(layer)
    keys: set[str] = {name}
    base = re.sub(r"[（(][^)）]*[)）]", "", name).strip()
    if base:
        keys.add(base)
    for part in re.split(r"[·、,，/|\s]+", base or name):
        piece = part.strip()
        if len(piece) >= 2:
            keys.add(piece)
    if len(name) >= 3 and re.search(r"[\u4e00-\u9fff]", name):
        keys.add(name[:2])
    return sorted((k for k in keys if k), key=len, reverse=True)


#: 用户口语 → 图层名里可能出现的写法。
#: 图层名各产品写法不同（「土壤水分」「VOD 植被光学厚度」「等效散射 ω」），
#: 但用户只会说「VOD」「土壤水分」「散射」——不做这层映射，
#: 「VOD 的均值是多少」就会落到「当前选中图层」上，算成土壤水分（2026-10-26 实测缺陷 ①）。
_LAYER_ALIASES: list[tuple[re.Pattern[str], tuple[str, ...]]] = [
    (re.compile(r"vod|植被光学厚度|光学厚度", re.I), ("vod", "植被光学厚度")),
    (
        re.compile(r"土壤水|土壤湿|含水量|墒情|(?<![a-z])sm(?![a-z])", re.I),
        ("土壤水", "含水量", "墒情"),
    ),
    (re.compile(r"omega|ω|散射", re.I), ("散射", "ω", "omega")),
]

#: 2026-11-11 用户实测：「显示 SMAP **平均版**土壤水分」被这里裸的「平均」判成统计请求，
#: 于是「开启一层」变成了「取这个月的平均值」，还回「这层算不出数值」。
#: 「平均」后面接的是产品形态（版/散射/约束）时它是在点产品，不是要统计。
_STAT_VERB = re.compile(
    r"平均(?!版|散射|约束|产品)|均值|统计|像元数|最大|最小|mean|average", re.I
)
#: 界面动作动词（用于从复合指令里挑出「顺带要做的界面动作」）
_SIDE_VERB = re.compile(
    r"打开|显示|隐藏|移除|删除|去掉|切换|缩放|定位|飞到|置顶|置底|透明度", re.I
)
#: 复合指令切句：标点 + 常见连接词；「并」只在后面紧跟动词时切开，避免误伤「并且/并行」以外的情况
_CLAUSE_SPLIT = re.compile(
    r"[，,；;。]|然后|接着|同时|并且|再(?=把|将|打开|显示|隐藏|移除|切换|缩放|定位)|"
    r"并(?=把|将|打开|显示|隐藏|移除|切换|缩放|定位|算|统计)"
)


def _side_clauses(text: str) -> str:
    """抽出复合指令里「与统计无关、但用户想顺带做」的子句。

    「计算选中图层的均值，并把 VOD 图层打开」——统计分支原实现直接 return，
    后半句被丢掉，界面纹丝不动（2026-10-26 实测缺陷 ②）。
    """
    parts = [p.strip() for p in _CLAUSE_SPLIT.split(text) if p and p.strip()]
    keep = [p for p in parts if _SIDE_VERB.search(p) and not _STAT_VERB.search(p)]
    return "，".join(keep)


#: 显隐子句里多个并列目标的分隔符（「隐藏 A 和 B」只有一个方向词、两个目标）
_TARGET_SPLIT = re.compile(r"和|、|及|与|以及|,|，")
_HIDE_WORD = re.compile(r"隐藏|关闭显示|关掉|hide", re.I)
_SHOW_WORD = re.compile(r"显示|打开|开启|添加|show|enable", re.I)
_VIS_WORD = re.compile(r"隐藏|关闭显示|关掉|hide|显示|打开|开启|添加|show|enable", re.I)


def _multi_visibility_actions(
    text: str, layers: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]] | None:
    """把「隐藏 A 并显示 B」「隐藏 A 和 B」拆成逐条显隐动作。

    2026-11-11 老师复测暴露两个方向性错误，根因都是**全文只认一个方向词**：

    - 「隐藏植被光学厚度并显示 SMAP 土壤水分」：Hide 分支要求全文不含「显示」，
      于是整句落进 Show 分支，按第一个方向词给所有目标下发 ``visible=True``
      ——把用户要隐藏的层显示了，回执还说「已显示」。
    - 「隐藏植被光学厚度和土壤水分」：整句只解析出一个层，另一个静默丢弃，
      回执不提漏了哪个。

    这里按子句各自取方向词（无方向词的子句继承前一句），目标段再按「和/、/及」
    拆开逐个定位；定位不到的收进 ``missing``，由回执点名。

    返回 ``None`` 表示「不是多目标场景」，交回原有 Hide / Show 分支处理——
    单目标显隐是最高频请求，不能因为这次改动改变它的行为。
    """
    parts = [p.strip() for p in _CLAUSE_SPLIT.split(text) if p and p.strip()]
    if not parts:
        return None
    actions: list[dict[str, Any]] = []
    missing: list[str] = []
    seen: set[str] = set()
    inherited: bool | None = None
    for part in parts:
        if _HIDE_WORD.search(part):
            direction: bool | None = False
        elif _SHOW_WORD.search(part):
            direction = True
        else:
            direction = inherited
        if direction is not None:
            inherited = direction
        if direction is None:
            continue
        body = re.sub(
            r"(?:把|将|请|帮我|再|然后|同时|并且|的|了)", " ", _VIS_WORD.sub(" ", part)
        )
        body = body.strip(" 的了")
        if not body:
            continue
        targets = [
            t.strip(" 的了") for t in _TARGET_SPLIT.split(body) if t.strip(" 的了")
        ]
        # 层名本身含「和/与」时（如「呼和浩特」）整段能直接定位就不用再拆。
        # 只有**拆分后所有目标都定位不到**才回退整段——只要有一个目标能定位，
        # 就说明「和」是并列连接词。否则「CMFD 和 VOD」会被整段模糊匹配成 VOD，
        # CMFD 那一步静默消失（用户要隐藏两层，只隐藏一层且不报漏）。
        if len(targets) > 1 and all(
            _resolve_layer(t, layers, allow_demo_fallback=False) is None
            for t in targets
        ):
            if _resolve_layer(body, layers, allow_demo_fallback=False):
                targets = [body]
        for target in targets:
            if not target:
                continue
            pick = _resolve_layer(target, layers, allow_demo_fallback=False)
            if pick is None:
                missing.append(target)
                continue
            if pick.catalog_id in seen:
                continue
            seen.add(pick.catalog_id)
            actions.append(
                {
                    "name": "set_layer_visibility",
                    "args": {
                        "catalog_id": pick.catalog_id,
                        "visible": direction,
                        "display_name": pick.name,
                    },
                }
            )
    # 只有一个目标时不接管：单层显隐交给原分支，避免行为漂移
    if len(actions) + len(missing) < 2:
        return None
    return actions, missing


def _catalog_pick_by_group_and_variable(message: str) -> LayerPick | None:
    """「显示风云平均产品中的 VOD」→ 落到族内 VOD 那一层（2026-11-12）。

    ``_catalog_pick`` 拿**整句**去搜图层库，这句返回空：目录里的族名是
    「风云卫星 平均散射约束产品」，和口语的「风云平均产品」差着「卫星」
    「散射约束」两截。就算搜出族来，名字 token 判定也接不住——它要求「层名
    整体或首词」出现在消息里，而首词是「风云卫星」，消息里只有「风云」。
    两条路都断，于是「显示组里的 VOD」只能勾上族（相当于文件夹），画面不变。

    改法：换用**变量词**去搜。「植被光学厚度」这一搜能拿到全部四个族，再用
    消息里的来源 / 产品形态按 ``identity`` 收窄。收窄到唯一一个族，就展开到
    该变量的真实成员；仍有多个族则返回 ``None``，交给上层反问——绝不替用户
    挑族（挑错等于把 SMAP 的数据标成风云的）。
    """
    search_terms: list[str] = []
    for pattern, terms in _LAYER_ALIASES:
        if pattern.search(message):
            search_terms = list(terms)
            break
    want_var = ""
    for pattern, code in _GROUP_VARIABLE_HINTS:
        if pattern.search(message):
            want_var = code
            break
    if not search_terms or not want_var:
        return None
    # 没点来源也没点形态（「显示植被光学厚度」）就不该走这里：这句话本来就
    # 只指变量，交给普通选层逻辑按页面已挂的层挑，比在这里凭目录挑一个更稳。
    mentions_source = any(pat.search(message) for pat, _ in _IDENTITY_SOURCE_HINTS)
    mentions_family = any(pat.search(message) for pat, _ in _IDENTITY_FAMILY_HINTS)
    if not mentions_source and not mentions_family:
        return None
    chosen: list[dict[str, Any]] = []
    # 别名表里同一变量有多种说法（「vod」/「植被光学厚度」）。必须逐个试：
    # 图层库里的族名是中文（「风云卫星 平均散射约束产品」），拿 "vod" 去搜
    # 匹配不到族；反过来 "vod" 又会搜到别的不相干层。所以判据不是「有结果」，
    # 而是「这一搜的结果按来源/形态收窄后正好剩一个」。
    for term in search_terms:
        candidate_rows: list[dict[str, Any]] = []
        try:
            from app.services.agent.server_tools_runtime import _search_layers

            res = _search_layers({"query": term, "limit": 10}, cred=None)
        except Exception:
            continue
        for item in (res or {}).get("layers") or []:
            if not isinstance(item, dict):
                continue
            lid = str(item.get("layer_id") or "").strip()
            name = str(item.get("display_name") or "").strip()
            if lid and name:
                candidate_rows.append({"catalog_id": lid, "name": name})
        if not candidate_rows:
            continue
        narrowed = _narrow_by_identity(message, candidate_rows)
        if len(narrowed) == 1:
            chosen = narrowed
            break
    if not chosen:
        return None
    pick = LayerPick(str(chosen[0]["catalog_id"]), str(chosen[0]["name"]))
    return _expand_product_group(pick, message)


def _catalog_pick(message: str) -> LayerPick | None:
    """目录兜底：页面没有这一层时，从图层目录里按名字找一次（2026-11-09）。

    外部实测：开场示例推荐「打开 CMFD 降水」，但 ``_resolve_layer`` 只在页面
    活动层里挑，目录层永远落到反问 ⇒ 示例指令与实际能力不一致，用户以为坏了。
    前端 ``set_layer_visibility`` 本就支持「显示＝自动从图层库添加」
    （agent-ui-intent 的 addLayer 分支），所以这里只要把目录层的 catalog_id
    交给前端即可。    只在「名字确实出现在消息里」时才命中，避免把无关层挂上来。
    """
    # 「族 + 变量」的说法优先：整句在图层库里搜不到（见上面那个函数的注释）。
    grouped = _catalog_pick_by_group_and_variable(message)
    if grouped is not None:
        return grouped
    try:
        from app.services.agent.server_tools_runtime import _search_layers

        q = re.sub(
            r"打开|显示|开启|图层|图层库|请|帮我|一下|看看|那个|这个", " ", message
        )
        q = q.strip()
        if not q:
            return None
        res = _search_layers({"query": q, "limit": 5}, cred=None)
        items = [x for x in (res or {}).get("layers") or [] if isinstance(x, dict)]
        lower = message.lower()
        for it in items:
            name = str(it.get("display_name") or "").strip()
            lid = str(it.get("layer_id") or "").strip()
            if not name or not lid:
                continue
            # 2026-11-11 用户实测：「显示 SMAP 土壤水分图层」在活动层里判成歧义后
            # 落到这里，靠名字首词「SMAP」就命中了目录里的「SMAP 平均散射约束产品」——
            # 变量根本不是土壤水分，页面反而被切到一个错的产品，比反问更糟。
            # 消息点了变量词，就要求目录层名含同一组变量词。
            wanted = [terms for pat, terms in _LAYER_ALIASES if pat.search(message)]
            if wanted and not any(
                term.lower() in name.lower() for terms in wanted for term in terms
            ):
                continue
            # 名字整体或开头词（如「CMFD」）出现在消息里才算认出
            tokens = [name] + name.split()[:1]
            if any(t and t.lower() in lower for t in tokens):
                # 目录里命中的若是一个**产品族**（文件夹），同样要落到族内变量层，
                # 否则前端「显示」一个非栅格层，画面上什么都不会出现。
                return _expand_product_group(LayerPick(lid, name), message)
        return None
    except Exception:
        return None


#: 消息里的来源词 → ``resolve_layer_identity`` 的 ``source`` 值。
#: 与 ``_SOURCE_HINTS`` 的区别：那个拿去比对**层名**（"SMAP"/"风云"），
#: 这个拿去比对**身份**（"smap"/"fy"），因为层名里常常根本没有来源。
_IDENTITY_SOURCE_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"smap|斯玛普", re.I), "smap"),
    (re.compile(r"风云|风三|风四|nsmc|fy-?\s*[34]", re.I), "fy"),
)

#: 消息里的产品形态词 → ``product_family`` 的**可接受取值集合**。
#:
#: ``layer_identity._product_family`` 实际只会返回 ``dynamic`` / ``average`` /
#: ``raw`` 三种，而用户嘴里的「动态」对应的是 ``dynamic``。这里原来写死成
#: ``"raw"``，两边永远对不上：说「风云动态产品里的土壤水分」时收窄结果为空，
#: 助手只能回「没找到」——同一句话换成「平均」就好使，用户会以为动态版没有数据。
_IDENTITY_FAMILY_HINTS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"动态|逐日|每天|日尺度", re.I), ("dynamic", "raw")),
    (
        re.compile(r"平均(?!值|多少|是|为|约|大概|下|一|的|数|量)|月均|季均|气候态"),
        ("average",),
    ),
)

_IDENTITY_CACHE: dict[str, dict[str, Any]] = {}

#: ``product_family`` → 用户嘴里的叫法（反问和回执都要靠它区分同名层）。
#: ``product_family`` → 用户嘴里的叫法（反问和回执都要靠它区分同名层）。
#: ``raw`` 沿用旧叫法「动态版」：那些层（``imported-nas-fy-raw-*``）在业务上
#: 就是逐日动态帧，改名会让既有回执与用户熟悉的说法对不上。
_FAMILY_LABELS: dict[str, str] = {
    "average": "平均版",
    "dynamic": "动态版",
    "raw": "动态版",
}

#: 消息里的变量词 → 产品族成员 code，对齐 ``layer_identity._GROUP_VARIABLE_ROLES``
#: （``("SM","sm") ("VOD","vod") ("OMEGA","omega")``）。
#: 用户说「风云平均产品里的 VOD」时要靠它把「组」收窄到「组内那一层」。
_GROUP_VARIABLE_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"vod|植被光学厚度|光学厚度", re.I), "vod"),
    (re.compile(r"土壤水|土壤湿|soil\s*moisture", re.I), "sm"),
    (re.compile(r"散射|ω|omega", re.I), "omega"),
)

#: ``identity.source`` → ``_SOURCE_HINTS`` 里的中文标记，两套写法要能对上。
_SOURCE_MARKER: dict[str, str] = {"smap": "smap", "fy": "风云"}


def _layer_identity(catalog_id: Any) -> dict[str, Any]:
    """``catalog_id`` → 来源 / 变量 / 产品形态（读不出返回空 dict，绝不抛）。"""
    key = _bare_layer_id(str(catalog_id or "")).strip()
    if not key:
        return {}
    cached = _IDENTITY_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from app.services.agent.layer_identity import resolve_layer_identity

        value = resolve_layer_identity(key)
    except Exception:
        value = {}
    _IDENTITY_CACHE[key] = value
    return value


def _layer_is_static(catalog_id: Any) -> bool:
    """这一层是不是**没有时间维度**的静态数据（2026-11-11 老师复测第 3 条）。

    「添加 CMFD 并切换到 2025-12-01」时 CMFD 被页面标成静态，时间轴没动，旧实现
    却写「已切到」。前端 ``agent-ui-intent.ts`` 会拒绝静态层的 ``set_timeline``，
    但那条回执要下一轮才回到后端，本轮正文已经写出去了 ⇒ 后端必须在下发前自判。

    **判据必须三项同时成立**，否则一律返回 ``False``（当作有时序）：
    1. 盘上拿不到任何时间帧（``_local_time_keys`` 为空）；
    2. 这一层确实存在（overlay spec 或 ``meta.json`` 任一能确认）；
    3. 也没有按需补出过的单日帧。

    第 2 条是硬要求：图层 id 不存在（拼错、还没入库、测试里的临时 id）时
    「没有时间帧」是**判不出来**，不是「静态」。少了这一条，任何认不出的层都会
    被当成静态而拒绝切日期——那是把正常功能拦死。
    """
    cid = str(catalog_id or "").strip()
    if not cid:
        return False
    try:
        from app.services.agent.server_tools_runtime import (
            _local_time_keys,
            _ondemand_frame_dates,
        )

        if _local_time_keys(cid):
            return False
    except Exception:  # pragma: no cover - 读盘失败不该影响主链路
        return False
    exists = False
    try:
        from app.services.overlay_registry import get_overlay_spec

        exists = get_overlay_spec(cid) is not None
    except Exception:  # pragma: no cover
        exists = False
    if not exists:
        try:
            from app.data_io.services.paths import safe_import_child

            exists = (safe_import_child(cid) / "meta.json").is_file()
        except Exception:  # pragma: no cover
            exists = False
    if not exists:
        # 这一层根本找不到：判不出来，不能当成静态。
        return False
    try:
        return not _ondemand_frame_dates(cid)
    except Exception:  # pragma: no cover
        return True


def _static_target_name(catalog_id: Any, layers: list[dict[str, Any]]) -> str | None:
    """「日期要落到的那一层」若是静态数据，返回它的显示名，否则 ``None``。

    目标层判定：本次新添加/新显示的那层 → 页面当前那一层（唯一选中 → 唯一可见）。
    判不出来就不拦（宁可让前端去拒绝，也不误伤正常图层）。
    """
    cid = str(catalog_id or "").strip()
    layer: dict[str, Any] | None = None
    if cid:
        layer = next(
            (la for la in layers if str(la.get("catalog_id") or "") == cid), None
        )
    else:
        sel = [la for la in layers if la.get("selected")]
        vis = [la for la in layers if la.get("visible")]
        only = sel if len(sel) == 1 else (vis if len(vis) == 1 else [])
        if len(only) == 1:
            layer = only[0]
            cid = str(layer.get("catalog_id") or "")
    if not cid or not _layer_is_static(cid):
        return None
    if layer is not None:
        return _display(layer)
    return human_layer_name(cid, None, default="") or cid


def _expand_product_group(pick: LayerPick | None, message: str) -> LayerPick | None:
    """命中**产品族**时，按消息里的变量词落到族内具体成员。

    2026-11-11 老师复测第 3 条：「显示风云平均产品中的 VOD」只勾上了产品族
    （相当于文件夹），里面的 VOD 根本没打开。产品族自己不是栅格层
    （``is_product_group``），勾上它画面上不会有任何变化，用户只会看到「说是
    显示了，其实没变」。
    ``layer_identity`` 的 ``group_members`` 只列**盘上真有产物**的成员，据此挑
    一个真实 ``overlay_layer_id`` 下发即可。

    消息里没有变量词（只说「风云平均产品」）⇒ 原样返回，交给调用方反问，
    绝不替用户挑一个变量。
    """
    if pick is None:
        return None
    # 先看消息里有没有变量词：没有就直接返回，**不去查身份**。
    # ``_layer_identity`` 有进程级缓存，任何一次读不出身份的调用都会把「空身份」
    # 记在缓存里，影响后面同 id 的判断（实测会让「上一轮统计过哪层」的粘性逻辑
    # 失准）。能少调一次就少调一次。
    want = ""
    for pattern, code in _GROUP_VARIABLE_HINTS:
        if pattern.search(message):
            want = code
            break
    if not want:
        return pick
    ident = _layer_identity(pick.catalog_id)
    if not ident.get("is_product_group"):
        return pick
    members = [m for m in (ident.get("group_members") or []) if isinstance(m, dict)]
    if not members:
        return pick
    group_label = str(ident.get("product_group_label") or "").strip()
    for member in members:
        if str(member.get("variable") or "") != want:
            continue
        oid = str(member.get("overlay_layer_id") or "").strip()
        if not oid:
            continue
        label = str(member.get("variable_label") or "").strip()
        if group_label and label:
            return LayerPick(oid, f"{group_label} · {label}")
        return LayerPick(oid, label or pick.name)
    return pick


def _narrow_by_identity(
    message: str, layers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """用「来源 / 产品形态」把同名层收窄（2026-11-11 用户实测）。

    页面上 SMAP 平均 / SMAP 动态 / 风云平均 / 风云动态 四族的层名往往都叫
    「土壤水分」，而前端 ``active_layers`` 并不带来源字段——身份只存在
    ``catalog_id`` 里（``imported-nas-smap-avg-sm``）。旧实现在两个候选上直接
    反问「要打开哪个图层」，把用户已经说清楚的话又抛回去，于是新开对话单独说
    「显示 SMAP 土壤水分图层」永远切不过去，页面一直停在原来的层。

    收窄规则：
    - 消息点了来源 → 只留 ``source`` 对得上的；
    - 消息点了形态 → 只留 ``product_family`` 对得上的；
    - 身份读不出来的层**不淘汰**（宁可后面反问，也不凭猜测删候选）；
    - 来源和形态都没点名 → 原样返回，交给调用方反问。
    """
    if not layers:
        return layers
    want_source = next(
        (val for pat, val in _IDENTITY_SOURCE_HINTS if pat.search(message)), None
    )
    want_family = next(
        (val for pat, val in _IDENTITY_FAMILY_HINTS if pat.search(message)), None
    )
    if not want_source and not want_family:
        return layers
    kept: list[dict[str, Any]] = []
    for layer in layers:
        ident = _layer_identity(layer.get("catalog_id"))
        if not ident:
            kept.append(layer)
            continue
        if want_source and str(ident.get("source") or "") != want_source:
            continue
        if want_family and str(ident.get("product_family") or "") not in want_family:
            continue
        kept.append(layer)
    return kept


def _layer_display_with_identity(layer: dict[str, Any]) -> str:
    """层名 + 来源/形态前缀，用于区分同名的「土壤水分」。

    页面上四族都叫「土壤水分」，「已显示「土壤水分」」这种回执等于没说——
    用户不知道切的是 SMAP 平均还是风云动态（2026-11-11 用户实测）。
    只在名字里确实缺来源/形态时才补前缀，避免「SMAP SMAP 土壤水分」。
    """
    name = _display(layer)
    ident = _layer_identity(layer.get("catalog_id"))
    if not ident:
        return name
    source = str(ident.get("source_label") or "").strip()
    family = _FAMILY_LABELS.get(str(ident.get("product_family") or ""), "")
    parts: list[str] = []
    if source and source.lower() not in name.lower():
        parts.append(source)
    if family and family not in name:
        parts.append(family)
    if not parts:
        return name
    return f"{' '.join(parts)} · {name}"


def _page_has_named_candidate(message: str, layers: list[dict[str, Any]]) -> bool:
    """页面上有没有「字面或别名命中」的层，哪怕因为同名歧义没能定到唯一一个。

    2026-11-11 用户实测：「显示 SMAP 土壤水分图层」在页面上有两个候选（平均版 /
    动态版），``_resolve_layer`` 正确地不肯猜；但调用方紧接着去图层目录兜底，
    又加载了目录里第三个「SMAP L3 土壤水分」——用户要的那层本来就在页面上，
    结果反而多挂一层错的产品。页面既然有相关层，就该反问而不是换一个顶上。
    """
    lower = message.lower()
    for layer in layers:
        if any(key and key.lower() in lower for key in _name_keys(layer)):
            return True
    for pattern, terms in _LAYER_ALIASES:
        if not pattern.search(message):
            continue
        for layer in layers:
            name = _display(layer).lower()
            if any(term.lower() in name for term in terms):
                return True
    return False


def _resolve_layer(
    message: str,
    layers: list[dict[str, Any]],
    *,
    allow_demo_fallback: bool = True,
) -> LayerPick | None:
    """把消息里的图层指向解析成 ``LayerPick``；解析不出来返回 ``None``。

    与旧 ``_match_catalog`` 的关键差别：**不再瞎回落**。
    旧实现匹配不到就返回 ``layers[0]`` 或 CMFD 降水，于是「隐藏风云」实际隐藏了
    别的图层，回复却报成功——比不回答更糟。
    """
    lower = message.lower()
    # 最长命中优先；同长命中多个图层视为歧义 → 反问
    best_len = 0
    best: dict[str, dict[str, Any]] = {}
    for layer in layers:
        for key in _name_keys(layer):
            if key.lower() not in lower:
                continue
            if len(key) > best_len:
                best_len = len(key)
                best = {layer["catalog_id"]: layer}
            elif len(key) == best_len:
                best[layer["catalog_id"]] = layer
            break
    if len(best) == 1:
        only = next(iter(best.values()))
        return _expand_product_group(
            LayerPick(only["catalog_id"], _layer_display_with_identity(only)), message
        )
    if len(best) > 1:
        # 同名层（「土壤水分」有 SMAP/风云 各两版）：先按来源/形态收窄，
        # 收窄到唯一一层才算认得，收不窄才交给调用方反问（2026-11-11 用户实测）。
        narrowed = _narrow_by_identity(message, list(best.values()))
        if len(narrowed) == 1:
            only = narrowed[0]
            return _expand_product_group(
                LayerPick(only["catalog_id"], _layer_display_with_identity(only)),
                message,
            )
        return None

    # 口语别名（VOD / 土壤水分 / 散射）：全名对不上时按产品口径再试一次
    alias_hits: dict[str, dict[str, Any]] = {}
    for pattern, terms in _LAYER_ALIASES:
        if not pattern.search(message):
            continue
        for layer in layers:
            name_low = _display(layer).lower()
            if any(term.lower() in name_low for term in terms):
                alias_hits[layer["catalog_id"]] = layer
    if len(alias_hits) == 1:
        only = next(iter(alias_hits.values()))
        return _expand_product_group(
            LayerPick(only["catalog_id"], _layer_display_with_identity(only)), message
        )
    if len(alias_hits) > 1:
        # 「土壤水分」同时命中风云与 SMAP 两个图层：先按来源/形态收窄
        # （用户说了「SMAP」就不该再问他要哪一个），收不窄才不猜。
        narrowed = _narrow_by_identity(message, list(alias_hits.values()))
        if len(narrowed) == 1:
            only = narrowed[0]
            return _expand_product_group(
                LayerPick(only["catalog_id"], _layer_display_with_identity(only)),
                message,
            )
        return None

    if not allow_demo_fallback:
        return None
    for pattern, catalog_id, label in _DEMO_FALLBACKS:
        if pattern.search(message):
            # 已加入地图的图层优先用它的名字
            for layer in layers:
                if layer["catalog_id"] == catalog_id:
                    return LayerPick(catalog_id, _display(layer))
            return LayerPick(catalog_id, label)
    return None


def _layer_choices(layers: list[dict[str, Any]]) -> str:
    """「要操作哪个图层？当前有 A、B、C」的可选项文案。"""
    if not layers:
        return "当前地图上没有活动图层，请先在左侧图层面板添加。"
    names = "、".join(
        f"「{_layer_display_with_identity(layer)}」" for layer in layers[:5]
    )
    return f"请指明是哪个图层。当前有：{names}。"


def _visible_layer_names(layers: list[dict[str, Any]]) -> str:
    return join_layer_names([layer["catalog_id"] for layer in layers], None)


def _parse_opacity(message: str) -> float | None:
    m = re.search(r"(?:透明度|opacity)\s*[:=]?\s*(\d{1,3})\s*%?", message, re.I)
    if not m:
        m = re.search(r"(\d{1,3})\s*%", message)
    if not m:
        return None
    n = int(m.group(1))
    if n > 100:
        return None
    return max(0.0, min(1.0, n / 100.0))


def _parse_lng_lat(message: str) -> tuple[float, float] | None:
    """Parse explicit coordinates like 116.4,39.9 or lng=116 lat=40."""
    m = re.search(
        r"(?:lng|lon|longitude|经度)\s*[:=]?\s*(-?\d+(?:\.\d+)?)"
        r"[,\s]+"
        r"(?:lat|latitude|纬度)\s*[:=]?\s*(-?\d+(?:\.\d+)?)",
        message,
        re.I,
    )
    if m:
        lng, lat = float(m.group(1)), float(m.group(2))
    else:
        m = re.search(
            r"(-?\d{1,3}(?:\.\d+)?)\s*[,，]\s*(-?\d{1,2}(?:\.\d+)?)",
            message,
        )
        if not m:
            return None
        a, b = float(m.group(1)), float(m.group(2))
        # Heuristic: prefer (lng,lat) when both in range; swap if first looks like lat-only
        if abs(a) <= 180 and abs(b) <= 90:
            lng, lat = a, b
        elif abs(b) <= 180 and abs(a) <= 90:
            lng, lat = b, a
        else:
            return None
    if lng < -180 or lng > 180 or lat < -90 or lat > 90:
        return None
    return (lng, lat)


def _parse_date_arg(message: str) -> str | None:
    """从中文句子里抓日期，返回 ``YYYY-MM-DD``。

    验收会考「切换到2025年12月15日」这种自然说法，旧实现只认
    ``2025-12-15``，于是整句落到兜底的能力介绍——等于答非所问。
    """
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", message or "")
    if not m:
        m = re.search(r"(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})", message or "")
    if not m:
        m = re.search(
            r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?", message or ""
        )
    if not m:
        # 2026-11-08 补：`20251113` 这种紧凑写法原来完全认不出——用户写「20251113
        # 那天多少」，解析返回 None，于是**悄悄沿用上一轮的日期**去取数，还把那个
        # 日期写成「你请求的日期」。日期认不出必须能认不出得**有话说**，
        # 见 `_invalid_date_hint`。
        m = re.search(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)", message or "")
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # 2026-11-08 补：原来只校验 `1 <= day <= 31`，于是 `2025-11-31` / `2025-02-30`
    # 都能过，被当成有效日期去取数（取不到就回一句「该区域无观测」，看着像数据问题）。
    if not (1900 <= year <= 2200):
        return None
    try:
        datetime.date(year, month, day)
    except ValueError:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


#: 「2025 年 12 月」「25 年 12 月」「2025-12」「12 月」这类**只要年月、不要日**的说法。
#: 必须和 `_parse_date_arg` 分开：那边要求「年-月-日」齐全，于是 2026-11-08 实测
#: 「对啊，25年12月的」解析成 None，被当成「这句话没提日期」，静默落回页面时间轴
#: 停在的 07-31，把「12 月平均」答成 7 月块——日期丢了却一声不响，比算错更难发现。
#: 顺序：先认带年的完整年月，再认 2025-12，最后认光秃秃的「12 月」（年份只能借）。
_MONTH_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\d)(\d{4}|\d{2})\s*年\s*(\d{1,2})\s*月份?"),
    re.compile(r"(?<!\d)(\d{4})\s*[-/]\s*(\d{1,2})(?!\s*[-/])(?!\d)"),
    re.compile(r"(?<!\d)(\d{1,2})\s*月份?(?!\s*\d)"),
)

#: 「这句话里提到了某个月」。只用来判断「提了月但认不出是哪年哪月」，
#: 认得出与否交给 `_parse_month_arg`。
_MONTH_HINT_RE = re.compile(r"\d{1,4}\s*年\s*\d{1,2}\s*月|\d{1,2}\s*月份?(?!\s*\d)")


def _parse_month_arg(
    text: str, fallback_year: int | None = None
) -> tuple[int, int] | None:
    """从一句话里抓「年 + 月」，返回 ``(year, month)``；认不出返回 ``None``。

    两位年份按 20XX 解释（「25 年」= 2025）。只写了「12 月」时年份借上一轮或
    时间轴的年份；借不到就返回 ``None``，让上层去说「不知道是哪一年」，
    **绝不自己编一个年份**。
    """
    body = str(text or "")
    for index, pattern in enumerate(_MONTH_RES):
        m = pattern.search(body)
        if not m:
            continue
        if index == 2:
            if not fallback_year:
                return None
            year, month = int(fallback_year), int(m.group(1))
        else:
            raw_year, month = int(m.group(1)), int(m.group(2))
            year = raw_year + 2000 if raw_year < 100 else raw_year
        if not (1900 <= year <= 2200 and 1 <= month <= 12):
            return None
        return year, month
    return None


def _month_day_list(year: int, month: int) -> list[str]:
    """该月每一天，``YYYYMMDD``。给「这一月没有整月块、只能逐日合并」用。"""
    first = datetime.date(year, month, 1)
    nxt = datetime.date(
        year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1
    )
    days: list[str] = []
    cur = first
    while cur < nxt:
        days.append(cur.strftime("%Y%m%d"))
        cur += datetime.timedelta(days=1)
    return days


def _period_day(raw: Any) -> datetime.date | None:
    """把 ``period_start`` / ``period_end`` 解析成日期。

    工具层回的是 **8 位紧凑写法**（``20251201``），不是 ``2025-12-01``——
    按带横线的写法切片会静默解析失败，整月块判定永远为假，于是「12 月有数据」
    被误答成「这一层没有 12 月」。这里两种写法都认。
    """
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) != 8:
        return None
    try:
        return datetime.date(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def _month_scan(catalog_id: str, year: int, month: int) -> tuple[str | None, bool]:
    """扫该层的时间清单：返回 ``(整月块键 | None, 这一月在清单里出现过吗)``。

    为什么不直接「挑月里某一天去取、看它命中什么」：那样要么撞上按需补出的
    单日帧（12-15 那天广州 247 像元全空，于是把「12 月平均」答成「这一片没有
    有效像元」），要么把块键传给按需补帧逻辑，让它抛「日期必须是 8 位」——
    日志脏、还慢。时间清单是现成的事实，先读它就知道该走哪条路。
    """
    try:
        from app.services.agent.server_tools_runtime import _local_time_keys

        keys = _local_time_keys(catalog_id) or []
    except Exception:  # noqa: BLE001 - 清单读不到就退回逐日合并，不影响正确性
        return None, True
    prefix = f"{year:04d}{month:02d}"
    present = False
    for key in keys:
        text = str(key)
        if text.startswith(prefix) or f"_{prefix}" in text:
            present = True
        m = re.fullmatch(r"(\d{8})_(\d{8})", text)
        if m and m.group(1).startswith(prefix) and m.group(2).startswith(prefix):
            return f"{m.group(1)}_{m.group(2)}", True
    # 没有「起止都在本月内」的纯整月块时，退而取**完全覆盖本月**的最短块。
    #
    # 2026-11-09：逐日产品点单日不再折回长合成块之后，问「12 月」会落到某一天
    # 的单日帧上（广州 12-15 得 0.1275/51），和「整月平均」差得远——这是把
    # 用户问的「一个月」偷偷答成「一天」。这类层只有 `20251201_20260201`
    # 一片覆盖 12 月，就用它，并由 `_month_block_covers` 在正文里标明是合成块。
    try:
        from calendar import monthrange

        month_start = f"{prefix}01"
        month_end = f"{prefix}{monthrange(year, month)[1]:02d}"
        covering: list[str] = []
        for key in keys:
            mm = re.fullmatch(r"(\d{8})_(\d{8})", str(key))
            if not mm:
                continue
            if mm.group(1) <= month_start and mm.group(2) >= month_end:
                covering.append(f"{mm.group(1)}_{mm.group(2)}")
        if covering:
            from app.services.overlay_registry import _block_span_days

            return min(covering, key=_block_span_days), True
    except Exception:  # noqa: BLE001 - 算不出月长就维持原判定
        pass
    return None, present


def _month_block_covers(res: dict[str, Any], year: int, month: int) -> bool:
    """这条统计命中的时间块，是不是「该月的整月合成块」。

    判据：起止都在该月内，且跨度 ≥20 天。命中单日帧（起止同一天）或跨月块
    都算否——那些不该被当成月均值。
    """
    start = _period_day(res.get("period_start"))
    end = _period_day(res.get("period_end")) or start
    if start is None or end is None:
        return False
    if (start.year, start.month) != (year, month):
        return False
    if (end.year, end.month) != (year, month):
        return False
    return (end - start).days >= 20


#: 「看起来像日期」的四种写法。只用来判断「用户给了日期但那天不存在」，
#: 合法与否交给 ``datetime.date`` 定。
_DATE_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)((?:19|20)\d{2})/(\d{1,2})/(\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?"),
    re.compile(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)"),
)


def _invalid_date_hint(message: str) -> str | None:
    """句子里给了日期、但那一天不存在 ⇒ 返回原样片段，否则 ``None``。

    2026-11-08 实测：连着问过广州市 11-09~11-16 之后，用户改口问
    「20251301 那天广州市土壤水分多少」，系统把 13 月当成「没给日期」，
    直接拿上一轮的 11-16 去取数，回了一句「你请求的日期是 2025-11-16，
    实际取的是 11-09 至 11-16 这个块」——**把系统自己补的日期说成用户请求的**。
    数值本身来自真实栅格，但归属是假的，比算错更难发现。

    所以：日期写得不对就当场说不对，一条数都不出。
    """
    text = message or ""
    for pattern in _DATE_SHAPES:
        for m in pattern.finditer(text):
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if not (1900 <= year <= 2200):
                return m.group(0)
            try:
                datetime.date(year, month, day)
            except ValueError:
                return m.group(0)
    return None


def _timeline_data_range(
    client_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """读取前端上报的当前图层可用时间范围（``timeline.data_range``）。

    形如 ``{"start": "20251201", "end": "20260201", "frames": 63}``。
    没有上报时返回 ``None``——此时不要假装知道有没有数据。
    """
    if not isinstance(client_context, dict):
        return None
    tl = client_context.get("timeline")
    if not isinstance(tl, dict):
        return None
    rng = tl.get("data_range")
    if not isinstance(rng, dict):
        return None
    start = str(rng.get("start") or "").strip()
    end = str(rng.get("end") or "").strip()
    if not start or not end:
        return None
    frames = rng.get("frames")
    return {
        "start": start,
        "end": end,
        "frames": int(frames) if isinstance(frames, int) else None,
    }


def _compact_date(date_s: str) -> str:
    return date_s.replace("-", "").replace("/", "").strip()


def _readable_date(date_s: str) -> str:
    compact = _compact_date(date_s)
    if len(compact) == 8 and compact.isdigit():
        return f"{compact[0:4]}-{compact[4:6]}-{compact[6:8]}"
    return date_s


def _context_date(client_context: dict[str, Any] | None) -> str:
    """前端上报的当前时间轴日期（没有就是空串）。"""
    if not isinstance(client_context, dict):
        return ""
    timeline = client_context.get("timeline")
    if not isinstance(timeline, dict):
        return ""
    return str(timeline.get("date") or "").strip()


def _nas_coverage_range() -> tuple[str, str]:
    """NAS 逐日成果的覆盖范围（``YYYYMMDD``）。

    与 ``nas_ondemand/config.py`` 同源，采用延迟导入避免 services 之间循环依赖；
    取不到时退回常量，宁可多试一次也不要凭错范围拒掉用户请求。
    """
    try:
        from app.services.nas_ondemand.config import (
            DATA_COVERAGE_END,
            DATA_COVERAGE_START,
        )

        return DATA_COVERAGE_START, DATA_COVERAGE_END
    except Exception:  # pragma: no cover - 配置缺失时的兜底
        return "20150401", "20251231"


def _build_timeline_reply(
    args_tl: dict[str, Any],
    client_context: dict[str, Any] | None,
    *,
    static_name: str | None = None,
) -> tuple[str, bool]:
    """时间轴切换的回复 ``(文案, 是否允许下发意图)``。

    **先校验，再回答**：日期拿不到数据时明确说「没有切换」，
    而不是旧版那句空口的「正在更新时间轴」——用户会以为切成功了。

    2026-11-02 修：原来的判定把 ``timeline.data_range`` 当成了数据边界，
    范围外一律不下发意图。可 ``data_range`` 只是「时间轴清单里现有的块」
    （平均产品常常只有一个 ``20251201_20260201`` 整段块），而 NAS 逐日成果
    覆盖到 2015 年 —— 用户说「切到 2015-12-15」明明取得到，却被这句拒掉。
    现在改成：超出 data_range 但落在 NAS 覆盖内 ⇒ 照旧下发，让前端的按需补帧
    去取；只有真超出 NAS 覆盖才拒绝。

    ``static_name``（2026-11-11 老师复测第 3 条）：目标层是静态数据时，这一层
    根本没有时间维度，切日期不可能生效。直接说「不支持切换日期」并拒绝下发，
    不能让用户看到「已切到 X」而页面毫无变化。

    ``static_name`` 传空时（2026-11-12）这里**自己再看一眼** ``args_tl`` 里的
    ``catalog_id``：拦截不能依赖每个调用方都记得传参——漏传一处就退回「已切到」。
    """
    if not static_name:
        target_cid = str(args_tl.get("catalog_id") or "").strip()
        if target_cid and _layer_is_static(target_cid):
            # 目录层（cmfd-precip-cn）在页面上没有实例，
            # ``human_layer_name`` 查不到会回占位词「该图层」——正文写成
            # 「「该图层」是静态数据」等于没说。身份解析能读目录里的中文名。
            label = str(_layer_identity(target_cid).get("display_name") or "")
            if not label or label == target_cid:
                label = human_layer_name(target_cid, client_context, default="")
            static_name = label or target_cid
    if static_name:
        return (
            f"「{static_name}」是静态数据，没有时间维度，**不支持切换日期**，"
            "时间轴没有动。"
        ), False
    date_s = str(args_tl.get("date") or "").strip()
    hour = args_tl.get("hour")
    hour_txt = f"{int(hour):02d}:00" if isinstance(hour, int) else ""

    if not date_s:
        return (f"时间轴已切到 {hour_txt}。" if hour_txt else "时间轴已更新。"), True

    wanted = _readable_date(date_s)
    rng = _timeline_data_range(client_context)
    if rng is not None:
        target = _compact_date(date_s)
        start, end = _compact_date(rng["start"]), _compact_date(rng["end"])
        if target < start or target > end:
            nas_start, nas_end = _nas_coverage_range()
            if nas_start <= target <= nas_end:
                # 清单里没有，但 NAS 有这一天 ⇒ 交给前端按需补帧
                return (
                    f"已把时间轴切到 {wanted}。\n\n"
                    f"这一天不在当前时间轴清单里（清单里是 {_readable_date(rng['start'])} "
                    f"至 {_readable_date(rng['end'])}），正在按需从 NAS 取这一天的单日图，"
                    "取回后地图会换成单日；取不到会在执行结果里说明。"
                ), True
            span = f"{_readable_date(rng['start'])} 至 {_readable_date(rng['end'])}"
            frames = rng.get("frames")
            extra = (
                f"，共 {frames} 帧" if isinstance(frames, int) and frames > 0 else ""
            )
            return (
                f"{wanted} 不在 NAS 成果覆盖内，**没有切换**。\n\n"
                f"NAS 逐日成果覆盖 "
                f"{_readable_date(nas_start)} 至 {_readable_date(nas_end)}；"
                f"当前时间轴清单是 {span}{extra}。\n"
                "要切到范围内的某一天，直接说日期即可。"
            ), False
    suffix = f"（{hour_txt}）" if hour_txt else ""
    return (
        f"已把时间轴切到 {wanted}{suffix}。\n"
        "实际生效日期、以及到底显示单日图还是时间块，以气泡下方的执行结果为准。"
    ), True


def _pick_stat_target(
    layers: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    """挑统计目标：优先「选中」，其次「唯一可见」，再次「仅一个图层」。

    多个候选时返回需要反问的提示，绝不猜。
    """
    selected = [la for la in layers if la.get("selected")]
    if len(selected) == 1:
        return selected[0], None
    visible = [la for la in layers if la.get("visible")]
    if len(visible) == 1:
        return visible[0], None
    if len(layers) == 1:
        return layers[0], None
    if not layers:
        return None, "当前地图上没有图层，先添加一个再统计。"
    if len(selected) > 1:
        return None, "当前选中了多个图层，请先只选中要统计的那一个。"
    names = "、".join(f"「{_display(la)}」" for la in (visible or layers)[:5])
    return None, f"当前可见（或已加载）的图层有多个：{names}。请指明要统计哪一个。"


# 行政区名候选：够长才可能是名字，够短才不至于把整句吃进去。
# 只做「候选提取」，真伪一律由 resolve_region 裁决（见 _parse_region_arg）。
_REGION_CANDIDATE_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,10}?(?:特别行政区|自治区|自治州|省|市|地区|盟)"
)

#: 行政区名尾词（用于从全名里剥出简称，如「河南省」→「河南」）
_REGION_SUFFIX_RE = re.compile(
    r"(?:特别行政区|自治区|自治州|自治县|地区|省|市|盟|区|县)$"
)


def _known_region_names() -> tuple[str, ...]:
    """所有可识别的行政区全名（省 + 地级市），按长度从长到短。

    2026-11-06：原来只靠正则抓「XX省/XX市」，用户的自然说法会把动词一起吞进去
    （``findall('再回到河南省2025年12月15日')`` → ``['再回到河南省']``），
    校验必然失败、整句放弃，最后退回整幅全图统计——数字看着很正式，其实是全球均值。
    改成「拿已知行政区名去句子里扫」，无论前后挂什么动词都能认出来，也支持
    「河南」这种不带后缀的口语简称。
    """
    try:
        from app.services.agent.region import list_cities, list_provinces
    except Exception:  # noqa: BLE001 - 区域库缺失时退回纯正则
        return ()
    names = [*list_provinces(), *list_cities()]
    return tuple(sorted({n for n in names if n}, key=len, reverse=True))


def _region_from_known_names(text: str) -> str | None:
    """在句子里扫已知行政区名，返回命中全名（交给 resolve_region 归一）。

    同名不同级（吉林省 / 吉林市）时按「更长的名字优先、同长取位置更靠后」裁决
    —— 中文习惯是先大后小（「河南省郑州市」），所以靠后的那个才是用户真指的对象。
    """
    if not text:
        return None
    best: tuple[int, int, str] | None = None
    for full in _known_region_names():
        core = _REGION_SUFFIX_RE.sub("", full)
        pos = text.rfind(full)
        if pos < 0 and len(core) >= 2:
            pos = text.rfind(core)
        if pos < 0:
            continue
        key = (len(full), pos)
        if best is None or key > (best[0], best[1]):
            best = (len(full), pos, full)
    return best[2] if best else None


def _parse_region_arg(message: str) -> str | None:
    """从中文句子里抓行政区名（省/自治区/地级市），抓不到返回 None。

    2026-11-04 新增：外部测试问「广州市的土壤水分是多少」，规则引擎原来的统计
    分支只会算**整幅栅格**，于是「广州」被静默丢掉 —— 答出来的数看着像广州的、
    其实是全球均值，比答不出来更糟。这里把行政区名解析出来，交给
    ``_get_layer_statistics(region=...)`` 走行政边界掩膜。

    2026-11-06 改：先按「已知行政区名」扫全句（抗动词干扰、支持简称），
    再用旧正则候选兜底（区域库加载失败时仍能工作）。
    校验一律回落到 ``resolve_region``，宁可返回 None 也不猜。
    """
    text = str(message or "")
    if not text:
        return None
    try:
        from app.services.agent.region import resolve_region
    except Exception:  # noqa: BLE001 - 区域库缺失时退化为「不做区域统计」
        return None

    scanned = _region_from_known_names(text)
    if scanned:
        try:
            if resolve_region(scanned) is not None:
                return scanned
        except Exception:  # noqa: BLE001
            pass

    candidates = sorted(
        {m for m in _REGION_CANDIDATE_RE.findall(text)}, key=len, reverse=True
    )
    for cand in candidates[:8]:
        try:
            if resolve_region(cand) is not None:
                return cand
        except Exception:  # noqa: BLE001
            continue
    return None


def _mentions_unresolvable_region(message: str) -> bool:
    """这句话里是不是提到了一个「像行政区、但解析不出来」的名字。

    2026-11-09（第十八轮）实测：问「甲壳虫省」，``_parse_region_arg`` 认不出
    返回 None，``resolve_entities`` 于是把它当「没提区域」，沿用了上一轮的
    「山东省」算了个数，只在正文里补一句「没对应到甲壳虫省」——用户问的是
    一个地方，收到的却是另一个省的数。这里判断「文本里有个带行政区尾词的
    候选，但已知地名和 resolve_region 都认不出」，说明用户确实点了一个新地名、
    只是系统不认识，必须拦住「沿用上一轮区域」，交给下游转述「没认出」。

    只认带明确尾词（省/市/自治区/地区/盟…）的候选，避免把「河南省郑州市」
    里已经能认出的「河南省」误判成「认不出」；候选里**只要有一个**认不出就算，
    因为用户这句的主语就是那个认不出的地方。
    """
    text = str(message or "")
    if not text:
        return False
    try:
        from app.services.agent.region import resolve_region
    except Exception:  # noqa: BLE001 - 区域库缺失时不拦，维持原「沿用」行为
        return False
    cands = {m for m in _REGION_CANDIDATE_RE.findall(text)}
    if not cands:
        return False
    # 候选里能认出一个，说明用户指的就是那个已知地名，不是「认不出」。
    for cand in cands:
        if _region_from_known_names(cand) or _region_from_known_names(text):
            return False
        try:
            if resolve_region(cand) is not None:
                return False
        except Exception:  # noqa: BLE001
            continue
    return True


#: 县/市辖区级地名。工具侧明确只支持到地级市，并会回一句「这属于县/区一级」，
#: 但兜底路径认不出区域就直接**丢掉**、按整幅算（2026-11-08 r73 实测：
#: 问「天河区的土壤水分平均值」，答的是整层 0.1534，正文里连"天河"两个字都没有，
#: 用户会把它当成天河区的值——这比答不出来糟得多）。
_COUNTY_NAME_RE = re.compile(r"([\u4e00-\u9fa5]{2,4})(区|县|旗)(?![域划分])")
#: 泛指词：「这个区域」「山区」「城区」不是地名，别拿去当行政区查。
_AREA_GENERIC_WORDS = (
    "区域",
    "地区",
    "山区",
    "郊区",
    "城区",
    "辖区",
    "园区",
    "景区",
    "库区",
    "灾区",
    "市区",
    "县区",
    "社区",
    "小区",
    "校区",
    "矿区",
    "牧区",
    "林区",
    "片区",
    "湾区",
    "省区",
    "市区",
)
_AREA_GENERIC_PREFIX = "这那该本各某全其两三几"

#: 候选地名里一旦出现这些词，说明它是被正则顺手吞进来的**普通名词**，不是地名。
#:
#: 2026-11-09 实测：「只把统计日期改为 2025 年 11 月 13 日，**产品和地区**沿用刚刚
#: 那次统计」——``_COUNTY_NAME_RE`` 在「产品和地**区沿**用」处命中（后接「沿」，
#: 负向断言挡不住），抓出「产品和地区」；``_AREA_GENERIC_WORDS`` 只按整词比
#: 「地区」，候选前缀是「产品和」也挡不住 ⇒ 正文凭空多一句「你说的『产品和地区』
#: 是县/区一级」。这一串是产品/表格类提问里最常出现的名词，宁可漏提示，
#: 也不能编一个地名给用户看。
_PLACE_NOISE_WORDS = (
    "产品",
    "变量",
    "日期",
    "时间",
    "范围",
    "统计",
    "数据",
    "图层",
    "结果",
    "均值",
    "平均",
    "动态",
    "散射",
    "约束",
    "有效",
    "栅格",
    "像元",
    "口径",
    "信息",
    "内容",
    "条件",
    "参数",
    "设置",
    "保持",
    "沿用",
    "不变",
    "改成",
    "改为",
    "换成",
    "只把",
    "只改",
    "数值",
    "期间",
    "时段",
    "序列",
    "对比",
)


def _strip_generic_area_suffix(token: str) -> str:
    """剥掉尾巴上的泛称词语：「产品和地区」→「产品和」。"""
    out = str(token or "")
    for word in sorted(_AREA_GENERIC_WORDS, key=len, reverse=True):
        if out.endswith(word):
            return out[: -len(word)]
    return out


#: 候选地名前面常被正则一起吞进来的动词 / 连词 / 普通名词。
#: 不做单字「和 / 与 / 及」——「和田地区」这类真地名会遭殃。
_PLACE_LEAD_NOISE_RE = re.compile(
    r"^(?:只把|只改|仅把|仅改|改成|改为|换成|换个|换到|保持|沿用|统计|范围|"
    r"日期|时间|产品|变量|数据|图层|结果|均值|平均|动态|散射|约束|口径|"
    r"地区|区域|数值|期间|时段|序列|对比|的|在|是|了|把|将|对|按|就|也|都)+"
)


#: 候选名字前面的单字动词/虚词。刻意只收**几乎不可能当地名首字**的字
#: （「将 / 改 / 和 / 用」之类会撞上「将乐县 / 改则县 / 和田地区」，一律不收）。
_PLACE_LEAD_NOISE_CHARS = "拿看查算给问请帮也都又再的了在是把对按想要先我你他"


def _clean_place_token(token: str) -> str:
    """把候选地名前后粘着的动词/普通名词剥掉；剥完不像地名就返回空串。

    「换成天河区」「拿天河区」→「天河区」（保留真正的区县名）；
    「产品和地区」→ 剥掉「产品」、再去掉尾词「地区」，只剩「和」→ 空串（不是地名）。
    2026-11-09 实测：这两种候选出自同一句「产品和地区沿用刚刚那次统计」，
    必须一个挡掉、一个留下。
    """
    out = str(token or "")
    while out and out[0] in _PLACE_LEAD_NOISE_CHARS:
        out = out[1:]
    out = _PLACE_LEAD_NOISE_RE.sub("", out)
    while out and out[0] in _PLACE_LEAD_NOISE_CHARS:
        out = out[1:]
    out = _strip_generic_area_suffix(out)
    if len(out) < 2:
        return ""
    # 「内蒙古自治区」会被 ``_COUNTY_NAME_RE`` 切成「蒙古自治**区**」——这是省级
    # 名字被正则误伤，不是区县，别拿去提示。
    if out.endswith(("自治区", "特别行政区")):
        return ""
    if any(word in out for word in _PLACE_NOISE_WORDS):
        return ""
    return out


def _county_like_region_name(message: str) -> str | None:
    """这句话里有没有「X区 / X县 / X旗」这类县区级地名（只作提示用，不做统计）。

    认得出就返回地名（如「天河区」），交给调用方回一句「这一级算不了」；
    认不出返回 None。凡是能被 ``resolve_region`` 认出来的（省/地级市）都不算，
    泛称词（区域/城区/山区…）也不算——宁可漏提示，也不能把正常提问判成地名。
    """
    text = str(message or "")
    if not text:
        return None
    try:
        from app.services.agent.region import resolve_region
    except Exception:  # noqa: BLE001 - 区域库缺失时不做这个判断
        return None
    for m in _COUNTY_NAME_RE.finditer(text):
        frag = m.group(1) + m.group(2)
        # 「广州市天河区」这种写法：按省市州盟切开，只留最后一段
        if any(ch in frag[:-1] for ch in "省市州盟"):
            frag = re.split(r"[省市州盟]", frag)[-1] or frag
        if len(frag) < 3:
            continue
        # 「产品和地区」这类被顺手吞进来的短语不是地名（2026-11-09 实测误报）；
        # 「换成天河区」要剥回「天河区」仍然算。
        frag = _clean_place_token(frag)
        if not frag:
            continue
        if frag[0] in _AREA_GENERIC_PREFIX:
            continue
        if any(
            word.startswith(frag) or frag.startswith(word)
            for word in _AREA_GENERIC_WORDS
        ):
            continue
        try:
            if resolve_region(frag) is not None:
                continue
        except Exception:  # noqa: BLE001
            continue
        return frag
    return None


#: 追问标志：出现这些说法，说明用户是在**改上一轮那个对象**，不是另起一句。
#: 这是「只改日期，其余不变」能成立的前提——没提到的项必须原样带过去。
_FOLLOWUP_RE = re.compile(
    r"其余不变|其他不变|其余保持|其他保持|保持不变|其余照旧|其余相同|"
    r"只改|仅改|只把|仅把|只设|只调|"
    r"改成|改为|换到|换成|换个|"
    r"原来的日期|原日期|原来那天|刚才|还是那个|同一个地方|同样的地方|沿用|照旧",
)

#: 「那 12 月 16 日呢？」这类以「呢」收尾的追问，等于「沿用上一轮，只换这一项」
_TAIL_NE_RE = re.compile(r"呢[？?]?\s*$")

#: 用户明确说要整幅 / 全国口径：这时不能再沿用上一轮的行政区，否则会算成
#: 「河南省」却告诉用户是全国值（2026-11-07 补区域沿用时加的排除项）。
#: 2026-11-10 补「中国」：先问河北再问「中国区域」，原来的正则匹配不到「中国」，
#: 于是沿用成河北，答成河北的值。中国/全国都算「不要沿用上一轮区域」。
_NO_REGION_RE = re.compile(
    r"整幅|整层|整个|全国|全图|全球|全部区域|不分区域|不限区域|矩形框"
    r"|中国(?:全境|全图|范围|境内|区域|地区)?|我国"
)


def _mentions_china_scope(message: str) -> bool:
    """这句话是不是把「中国 / 全国」当成统计范围（而非缩放视图）。

    与 orchestrator._mentions_china_scope 同口径，避免两条路径漂移。
    排除「中国气象局 / 中国科学院」等机构名。
    """
    return bool(
        re.search(
            r"中国(?!气象局|科学院|科学研究院|工程院|政府|央行|人民银行)"
            r"(?:全境|全图|范围|境内|区域|地区)?|全国|全境|我国",
            str(message or ""),
        )
    )


#: 明确要求「沿用上一轮那个日期」（用户没重新给日期）
_DATE_CARRY_RE = re.compile(
    r"原来的日期|原日期|原来那天|同一个日期|同一个日子|那天|那一天"
)

#: 来源词 → 层名里的来源写法（用于同变量多层时把用户点的那一层挑出来）
_SOURCE_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"smap|斯玛普", re.I), "smap"),
    (re.compile(r"风云|fy-?\s*\d|fy3|fy4", re.I), "风云"),
)

#: 产品形态词 → 层名里的形态写法。同源两套只差「平均 / 动态」，不认这一层就会
#: 退回落点层（2026-11-06 实测：「SMAP 动态」被答成「风云平均」）。
#: 注意「平均**值**」是统计动词、不是产品形态：不收这个口子，用户每次问
#: 「平均值是多少」都会被当成点了「平均版」那一层（回溯测试当场踩到）。
_FORM_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"动态|逐日|每天|日尺度", re.I), "动态"),
    #: 2026-11-08 补：不只「平均值」。实测「这几天**平均多少**」被这句的
    #: 「平均」判成点了「平均版」那一层 ⇒ 与页面上的动态版互相矛盾 ⇒
    #: `_contradicts_hints` 认为页面没有他要的层 ⇒ 丢掉页面这层、改写成一堆
    #: 候选反问（用户看着就是「明明页面上就开着，还问我要哪一版」）。
    #: 「平均」后面跟的是**统计谓语**（多少/是多少/为/一下/的/数/量）时，
    #: 它问的是「算个平均值」，不是「要平均版产品」。
    (
        re.compile(
            r"平均(?!值|多少|是|为|约|大概|下|一|的|数|量)|月均|季均|气候态|多年", re.I
        ),
        "平均",
    ),
)


def _has_layer_hints(text: str) -> bool:
    """这句话里有没有「来源 / 产品形态」线索（用来判断值不值得收窄候选）。"""
    return any(p.search(text) for p, _ in _SOURCE_HINTS) or any(
        p.search(text) for p, _ in _FORM_HINTS
    )


def _contradicts_hints(text: str, layer: dict[str, Any]) -> bool:
    """消息点名的来源 / 产品形态，与这一层对不上 ⇒ 页面没有他要的那一层。

    2026-11-07 实测（游客模式连续追问）：页面只挂「风云卫星 平均 · 土壤水分」，
    用户明确说「查询 SMAP 动态散射约束产品的土壤水分」，解析器把**页面上那层
    风云**当成「用户点名的层」（``layer_from="message"``）返回，接着写进会话
    基线 —— 于是基线变成风云，下一句「只改日期」就粘在风云上，跨轮串产品。
    候选集里只有页面层，用户要的那层压根不在，正确做法是不定层（让他去搜），
    而不是拿最近的层顶上。
    """
    name = _display(layer)
    ident = _layer_identity(layer.get("catalog_id"))
    for pattern, marker in _SOURCE_HINTS:
        if not pattern.search(text):
            continue
        if marker in name.lower():
            continue
        # 层名里没有来源（页面上的「土壤水分」全都不带），只能看 catalog_id 的身份。
        # 不加这一条，「显示 SMAP 平均版土壤水分」会被判成"页面没有这层"而放弃
        # （2026-11-11 用户实测）。
        if _SOURCE_MARKER.get(str(ident.get("source") or "")) == marker:
            continue
        return True
    for pattern, marker in _FORM_HINTS:
        if not pattern.search(text):
            continue
        if marker in name:
            continue
        # 「动态」在身份里是 dynamic，raw 是原始——两个都要认，否则
        # 「页面上这层是动态版吗」永远判成对不上。
        want: tuple[str, ...] = ("dynamic", "raw") if marker == "动态" else ("average",)
        if str(ident.get("product_family") or "") in want:
            continue
        return True
    return False


def _layer_from_state(
    prior: dict[str, str],
    client_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """把会话基线（上一轮真取过的那一层）还原成一个可统计的「层」。

    2026-11-07 新增。背景：页面上只挂了 A 产品，用户这几轮一直在问 B 产品。
    ``_resolve_layer`` 在不能从文本里认出层名时会退到「页面上唯一那一层」，
    于是每轮都先选成 A，再被 ``_contradicts_hints`` 出口校验否掉——否掉之后
    旧实现就彻底放弃了，兜底只能回一句「这次没能取到可用的数值」。
    可会话基线里明明记着 B 的产物 id 和中文名，照它取数就能算出来。

    ``overlay_layer_id`` 是 ``_get_layer_statistics`` 真正要吃的产物 id：
    基线里若已是 ``imported-*`` 直接用；若是目录层 id（``method-*``，老会话
    或模型回填所致），再按页面反查一次。
    """
    prior_id = str(prior.get("layer_id") or "").strip()
    name = str(prior.get("layer_name") or "").strip()
    if not prior_id or not name:
        return None
    bare = _bare_layer_id(prior_id)
    overlay = bare if bare.startswith(("imported-", "wf-run-")) else ""
    if not overlay:
        try:
            from app.services.agent.server_tools_runtime import (
                _overlay_for_catalog_variable,
                _page_overlay_for_catalog,
            )

            overlay = _page_overlay_for_catalog(client_context, prior_id) or ""
            # 页面反查落空（用户已经把那层从页面撤掉、换成了别的产品）：用目录 id
            # + 变量反算产物目录，并验 meta.json 真在盘上。2026-11-07：不这么做，
            # 「只改日期」在页面换层之后就退化成「取不到数」，而产物就在盘上。
            if not overlay:
                overlay = _overlay_for_catalog_variable(
                    prior_id, str(prior.get("variable") or "")
                )
        except Exception:  # pragma: no cover - 反查失败不影响主流程
            overlay = ""
    # 只有产物目录真的在盘上才敢拿来取数：状态里的 id 可能早已被清理，
    # 拿一个不存在的 id 去统计只会得到一句「不是本地运行时产物」，
    # 反而不如老老实实反问（沿用 test_lost_layer_asks_instead_of_guessing 的契约）。
    if overlay.startswith("imported-"):
        try:
            from app.data_io.services.paths import safe_import_child

            if not safe_import_child(overlay).is_dir():
                return None
        except Exception:  # pragma: no cover - 判断不了就不冒险
            return None
        # 基线里的名字可能只是侧栏名（「土壤水分」），标题看不出是哪颗卫星。
        # 产物 id 在手，顺手补全成「SMAP 动态散射约束产品 · 土壤水分」。
        try:
            from app.services.agent.server_tools_runtime import _qualified_layer_name

            name = _qualified_layer_name(overlay, name) or name
        except Exception:  # pragma: no cover - 补名失败不影响取数
            pass
    return {
        "catalog_id": prior_id,
        "overlay_layer_id": overlay,
        "instance_id": "",
        "name": name,
        "visible": False,
        "selected": False,
        # 标记：这一层是从会话基线还原的，不是页面上的活动图层
        "virtual": True,
    }


def _same_variable_candidates(
    variable: str,
    layers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """列出「本机现在真能算」的同变量层：页面上的 + 目录产品族里已物化的成员。

    2026-11-07 新增。背景：页面只挂着「等效散射 ω」，用户问「河南省土壤水分」，
    这一层压根没有可统计的对象。旧实现回一句「当前地图上没有这一层的可统计
    版本」——可本机明明有四族「散射约束产品」都带土壤水分，用户被这句话挡在
    门外，还得自己回页面加图层。

    严格只收**盘上已有产物**的层：``group_members`` 由
    ``layer_identity._group_member_ids`` 按 sha1 反算目录名再验 ``meta.json``，
    盘上没有就不列（绝不凭目录名编一个数出来）。
    """
    out: list[dict[str, Any]] = []
    seen_name_source: set[tuple[str, str]] = set()

    def _add(entry: dict[str, Any]) -> None:
        # 去重键：「显示名 + 来源」。页面层与目录成员 id 对不上时（页面层用的是
        # 前端传的运行时 overlay_layer_id，目录层用 stable_imported_layer_id 反算的
        # oid，两者可能不一致），overlay_layer_id 主键会失效，靠 name+source 兜底。
        # 2026-11-10 实测：「SMAP 平均 · 植被光学厚度 / 等效散射 ω」在页面上挂着时，
        # 同一条候选被列了两遍。
        name_source = (str(entry.get("name") or ""), str(entry.get("source") or ""))
        if name_source[0] and name_source in seen_name_source:
            return
        seen_name_source.add(name_source)
        out.append(entry)

    def _qualified(layer: dict[str, Any]) -> str:
        """页面层只带侧栏名（「土壤水分」），补出产品族名才分得清是哪一层。"""
        base = _display(layer)
        oid = str(layer.get("overlay_layer_id") or "")
        if not oid:
            return base
        try:
            from app.services.agent.server_tools_runtime import _qualified_layer_name

            return _qualified_layer_name(oid, base) or base
        except Exception:  # pragma: no cover - 补名失败不影响候选
            return base

    def _source_of(layer_id: str) -> str:
        """smap / fy …… 判断「候选与页面是不是同一颗卫星」只看这个。"""
        if not layer_id:
            return ""
        try:
            from app.services.agent.server_tools_runtime import _layer_identity_fields

            return str(_layer_identity_fields(layer_id).get("source") or "")
        except Exception:  # pragma: no cover
            return ""

    # ① 页面上的同变量层（直接可算，排在前面）
    for la in layers:
        if dialogue_state.variable_from_name(_display(la)) != variable:
            continue
        oid = str(la.get("overlay_layer_id") or "")
        _add(
            {
                "catalog_id": str(la.get("catalog_id") or ""),
                "overlay_layer_id": oid,
                "instance_id": str(la.get("instance_id") or ""),
                "name": _qualified(la),
                "source": _source_of(oid)
                or _source_of(str(la.get("catalog_id") or "")),
                "on_page": True,
                "visible": bool(la.get("visible")),
                "selected": bool(la.get("selected")),
                "virtual": True,
            }
        )

    # ② 目录产品族里已物化的同变量成员
    try:
        from app.services.agent.layer_identity import identity_fields
        from app.services.layer_catalog import get_layer_catalog

        items = list(get_layer_catalog().items or [])
    except Exception:  # pragma: no cover - 目录不可用就只列页面层
        items = []

    for item in items:
        lid = str(getattr(item, "layer_id", "") or "")
        if not lid.startswith("method-"):
            continue
        try:
            fields = identity_fields(
                lid, display_name=str(getattr(item, "display_name", "") or "")
            )
        except Exception:  # pragma: no cover
            continue
        group = str(fields.get("product_group_label") or "").strip()
        for member in fields.get("group_members") or []:
            if not isinstance(member, dict) or member.get("variable") != variable:
                continue
            var_label = str(member.get("variable_label") or "").strip()
            if group and var_label and not group.endswith(var_label):
                name = f"{group} · {var_label}"
            else:
                name = group or var_label
            _add(
                {
                    "catalog_id": lid,
                    "overlay_layer_id": str(member.get("overlay_layer_id") or ""),
                    "instance_id": "",
                    "name": name,
                    "source": str(fields.get("source") or ""),
                    "on_page": False,
                    "visible": False,
                    "selected": False,
                    "virtual": True,
                }
            )

    out.sort(key=lambda e: (0 if e.get("on_page") else 1, str(e.get("name") or "")))
    return out


def _undecided_statistics_reply(
    *,
    text: str,
    entities: dict[str, Any],
    layers: list[dict[str, Any]],
    sid: str,
    intents: list[dict[str, Any]],
    lead: str = "",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """层定不下来时的答复：**要么直接算，要么给出固定的候选清单**。

    2026-11-07：原先这一步只回一句 ``why``，措辞随模型/状态变化，同一个问题
    两次问得到两种答复（一次自己挑了 SMAP 算出 0.2929，一次只回「当前地图上
    没有这一层」）。现在收敛成三条确定路径：

    1. 本机只有一种来源 ⇒ 没有可挑的余地，直接算；
    2. 有多种来源 ⇒ 固定格式列出来，绝不替用户挑（「土壤水分」四个口径的均值
       差别很大，替他挑就等于替他做了数据决定）；
    3. 一层都没有 ⇒ 如实说没有，并说明要怎么才能有。

    返回 ``(层, None)`` 表示用它继续取数，``(None, 回复)`` 表示到此为止。
    """
    variable = str(entities.get("variable") or "")
    why = str(entities.get("why") or "").strip() or "请先指定一个图层。"
    if not variable:
        return None, {
            "session_id": sid,
            "reply": why,
            "ui_intents": intents,
            "topic_state": {},
        }

    label = dialogue_state.VARIABLE_LABELS.get(variable, variable)
    # 只记「问的是哪个变量」和用户这一句明说的区域：层还没定，绝不写层
    # （写了就会被下一轮当基线用）。下一句「用 SMAP 动态的」靠它接上变量。
    patch: dict[str, str] = {"variable": variable}
    if entities.get("region") and entities.get("region_from") == "message":
        patch["region"] = str(entities["region"])
    cands = [
        c
        for c in _same_variable_candidates(variable, layers)
        if not _contradicts_hints(text, c)
    ]

    # ① 只有一种来源：**还得是页面这层、或与页面同源**才直接算。
    # 跨来源时（页面挂风云、唯一候选是 SMAP）不能替用户换卫星——那正是
    # _cross_source_guard 要拦的事，交给下面的清单让他自己点头。
    if len(cands) == 1:
        only = cands[0]
        page_sources = _page_sources(layers)
        if only.get("on_page") or (
            only.get("source") and str(only["source"]) in page_sources
        ):
            return only, None

    # ①.5 用户点名了**口径**（「换回平均版」）、但没点来源 ⇒ 别把别的卫星也摆出来
    # 让他挑。2026-11-08 实测 r69：动态版→平均版→动态版→「再换回平均版」，回了一句
    # 「本机有 2 个「土壤水分」的版本…我不替你挑」。上一轮刚用过 SMAP 平均，这句反问
    # 等于让用户把已经说过的话重复一遍；而口径已经定死，剩下的分歧只有来源，候选里
    # 与页面同源的**只有一个**，选它并不构成「替用户换卫星」（跨来源才需要点头，
    # 那是 _cross_source_guard 的职责）。同源候选仍多于一个时照旧列清单，不猜。
    #
    # 只说变量（「河南省的土壤水分平均值是多少」）时不走这条路：那时口径还没定，
    # 平均/动态两套结果差得不少，确实该让用户自己说（见
    # test_undecided_reply_lists_candidates_without_picking）。
    if len(cands) > 1:
        from app.services.agent.server_tools_runtime import _mentions_version

        if any(_mentions_version(text, fam) for fam in ("average", "dynamic")):
            page_sources = _page_sources(layers)
            same_source = [
                c
                for c in cands
                if c.get("on_page") or str(c.get("source") or "") in page_sources
            ]
            if len(same_source) == 1:
                return same_source[0], None

    # ② 有候选：列清单，让用户点名
    if cands:
        region = str(entities.get("region") or "").strip()
        day = str(entities.get("date") or "").strip()
        scope = "、".join(x for x in (region, _readable_date(day) if day else "") if x)
        tail = f"说一句「用 {_short_candidate_name(cands[0]['name'])}的」，" + (
            f"我就按「{scope}」算给你。" if scope else "我就算给你。"
        )
        head: list[str] = []
        if lead:
            head.append(lead)
        if len(cands) == 1:
            head.append(f"本机只有这一个「{label}」可算，但它不在页面上：")
            # 不写基线（还没定层），下一轮只能靠用户把这层的名字说出来
            # ⇒ 引导语必须点名，不能写「就用它」，否则下一句解析不到对象。
            tail = f"说一句「用 {_short_candidate_name(cands[0]['name'])}的」，" + (
                f"我就按「{scope}」算给你。" if scope else "我就算给你。"
            )
        else:
            head.append(
                f"本机有 {len(cands)} 个「{label}」的版本，来源和口径都不一样，"
                "均值差得不少，我不替你挑："
            )
        lines = [
            *head,
            "",
            *[f"· {c['name']}" for c in cands],
            "",
            tail,
        ]
        return None, {
            "session_id": sid,
            "reply": "\n".join(lines),
            "ui_intents": intents,
            "topic_state": patch,
        }

    # ③ 一层都没有
    pending = _unavailable_same_variable(variable)
    if pending:
        lname = "、".join(f"「{n}」" for n in pending[:2])
        more = f"等 {len(pending)} 个" if len(pending) > 2 else ""
        reply = (
            f"{lead}"
            f"本机现在还没有「{label}」的可统计产物，页面上也没有这一层。"
            f"目录里有{lname}{more}同类产品，但还没有生成过本地数据——"
            "先在「数据 → 产品」里跑一次工作流，回来我直接给你算。"
        )
    else:
        reply = lead + why if lead else why
    return None, {
        "session_id": sid,
        "reply": reply,
        "ui_intents": intents,
        "topic_state": patch,
    }


def _page_sources(layers: list[dict[str, Any]]) -> set[str]:
    """页面上现在挂着哪些来源（smap / fy…），用来判断「候选和页面是不是同一颗卫星」。"""
    out: set[str] = set()
    for la in layers:
        for lid in (
            str(la.get("overlay_layer_id") or ""),
            str(la.get("catalog_id") or ""),
        ):
            if not lid:
                continue
            try:
                from app.services.agent.server_tools_runtime import (
                    _layer_identity_fields,
                )

                src = str(_layer_identity_fields(lid).get("source") or "")
            except Exception:  # pragma: no cover
                src = ""
            if src:
                out.add(src)
                break
    return out


def _short_candidate_name(name: str) -> str:
    """「SMAP 动态散射约束产品 · 土壤水分」→「SMAP 动态」，用于引导句。"""
    head = str(name or "").split("·")[0].strip()
    return re.sub(r"(散射约束)?产品$", "", head).strip() or head


def _unavailable_same_variable(variable: str) -> list[str]:
    """目录里同变量、但本机还没有产物的层名（只用于解释「为什么算不了」）。"""
    try:
        from app.services.layer_catalog import get_layer_catalog

        items = list(get_layer_catalog().items or [])
    except Exception:  # pragma: no cover
        return []
    names: list[str] = []
    for item in items:
        lid = str(getattr(item, "layer_id", "") or "")
        name = str(getattr(item, "display_name", "") or "").strip()
        # 参考层（ref-*）是别人做好的成品，不算「本机待生产」的对象
        if not lid or lid.startswith(("method-", "ref-")) or not name:
            continue
        if dialogue_state.variable_from_name(name) != variable:
            continue
        if name not in names:
            names.append(name)
    return names


def _narrow_by_hints(
    text: str,
    candidates: list[dict[str, Any]],
    *,
    prefer_variable: str | None = None,
) -> dict[str, Any] | None:
    """同变量多层时，用「来源 + 产品形态」把用户点名的那一层挑出来。

    「SMAP 动态土壤水分」既不是完整层名、也不是唯一别名：旧实现别名命中多个
    就直接放放弃（返回 None），于是落到页面选中层——用户明明点了 SMAP 动态，
    拿到的是另一层的数据。这里按用户给的两个线索逐级收窄，只有收到唯一
    一个时才返回，仍然不收窄就返回 None（宁可反问，不猜）。
    """
    if not candidates:
        return None
    pool = list(candidates)
    for pattern, marker in _SOURCE_HINTS:
        if pattern.search(text):
            narrowed = [la for la in pool if marker in _display(la).lower()]
            if not narrowed:
                # 用户点名了来源，候选里一个都不是它 ⇒ 页面没有这层，别退回全集
                return None
            pool = narrowed
            break
    for pattern, marker in _FORM_HINTS:
        if pattern.search(text):
            narrowed = [la for la in pool if marker in _display(la)]
            if not narrowed:
                # 同理：点名「动态版」而候选全是平均版时不猜
                return None
            pool = narrowed
            break
    if len(pool) > 1 and prefer_variable:
        # 「换成 SMAP 动态那套」没说变量：按上一轮那个变量收敛（同一变量换产品形态，
        # 是最常见的追问），仍然多于一个就不猜。
        narrowed = [
            la
            for la in pool
            if dialogue_state.variable_from_name(_display(la)) == prefer_variable
        ]
        if len(narrowed) == 1:
            pool = narrowed
    return pool[0] if len(pool) == 1 else None


def _asks_page_layer_text(text: str) -> bool:
    """这一句是不是在要「页面上当前选中的那一层」。

    判定与 ``server_tools_runtime._asks_page_layer`` **同一份正则**：粘性那边认
    的说法，兜底这边必须认；两边各写一套迟早会分叉（一边取页面层、一边取上一轮，
    同一个问题两个答案）。
    """
    try:
        from app.services.agent.server_tools_runtime import _asks_page_layer
    except Exception:  # pragma: no cover
        return False
    return bool(_asks_page_layer(text))


def _page_layer_entry(
    layers: list[dict[str, Any]], client_context: dict[str, Any] | None
) -> dict[str, Any] | None:
    """页面**明确选中**的那一层在 ``layers`` 里的那一条（认不出就 None）。"""
    try:
        from app.services.agent.server_tools_runtime import _page_selected_layer_id

        want = _bare_layer_id(_page_selected_layer_id(client_context))
    except Exception:  # pragma: no cover
        return None
    if not want:
        return None
    for la in layers:
        ids = {
            _bare_layer_id(str(la.get("catalog_id") or "")),
            _bare_layer_id(str(la.get("overlay_layer_id") or "")),
            _bare_layer_id(str(la.get("instance_id") or "")),
        }
        if want in ids:
            return la
    return None


def resolve_entities(
    message: str,
    layers: list[dict[str, Any]],
    *,
    client_context: dict[str, Any] | None = None,
    state: dict[str, str] | None = None,
) -> dict[str, Any]:
    """把「这一轮到底在讲哪一层、哪个区域、哪一天」解析成一组实体。

    优先级（与系统提示词「选层顺序」一致，只是多了第 ⓪ 条）：

    ⓪ **上一轮记着的那个对象** —— 用户这轮没点名新产品/变量时沿用它；
    ① 本轮点名的层（完整层名 / 变量名 + 来源 + 形态 能收到唯一一层）；
    ② 页面选中层 → 唯一可见层 → 唯一候选（``_pick_stat_target``，仅前三步都落空时）。

    区域与日期同理：本轮提到了就用本轮的；没提到但用户明显在「改上一轮的
    对象」时，沿用上一轮的值——**这就是「其余不变」不丢东西的地方**。
    """
    text = str(message or "")
    prior = dialogue_state.sanitize(state)
    follow_up = bool(_FOLLOWUP_RE.search(text)) or bool(_TAIL_NE_RE.search(text))
    variable = dialogue_state.variable_from_text(text)
    # ★ 2026-11-07：省略变量的追问要能接上。「照候选清单说『用 SMAP 动态的』」
    # 这句里没有变量词，上一版 variable=None ⇒ 候选池为空 ⇒ 只认页面上那层
    # ω ⇒ 出口校验否掉 ⇒ 回一句「当前地图上没有与你点名的来源一致的图层」，
    # 用户照着提示说反而更糊涂。上一轮问的是哪个变量，这里继承下来。
    if variable is None and prior.get("variable") and _has_layer_hints(text):
        variable = str(prior["variable"])

    target: dict[str, Any] | None = None
    layer_from = ""
    why: str | None = None

    def _var_layers() -> list[dict[str, Any]]:
        if not variable:
            return []
        return [
            la
            for la in layers
            if dialogue_state.variable_from_name(_display(la)) == variable
        ]

    # ★ 2026-11-09（用户第三轮复测的兜底路径）：点名「当前图层 / 页面选中的这层」
    # ⇒ 就查页面选中层，**优先于「沿用上一轮」**。
    #
    # 本轮之前的修法只动了 ``_product_sticky_layer``（模型正常调工具那条路）。
    # 模型偶尔不调工具（本次实测：上一轮问的是土壤水分、页面选着风云 VOD，它选择
    # 反问「你要哪一个」），就落到 ``_statistics_fallback_reply`` ⇒ 走这里 ⇒
    # 优先级 ⓪「沿用上一轮」先命中 ⇒ 拿 state 里的 SMAP 土壤水分去算，
    # 与用户说的「当前图层」恰好相反。同一个问题在两条路径上给两个对象，
    # 用户只会觉得「时好时坏」。
    if _asks_page_layer_text(text):
        page_entry = _page_layer_entry(layers, client_context)
        if page_entry is not None:
            target = page_entry
            layer_from = "page"

    picked = (
        None
        if target is not None
        else _resolve_layer(text, layers, allow_demo_fallback=False)
    )
    if picked is not None:
        target = next(
            (la for la in layers if la.get("catalog_id") == picked.catalog_id), None
        )
        if target is not None:
            layer_from = "message"

    # 层名对不上、但用户点了变量并且给了来源/形态线索（「SMAP 动态土壤水分」）
    if target is None and (variable or _has_layer_hints(text)):
        target = _narrow_by_hints(
            text,
            _var_layers() or layers,
            prefer_variable=prior.get("variable"),
        )
        if target is not None:
            layer_from = "message"

    # 仍然定不下来 ⇒ 沿用上一轮那一层（前提：它还挂在页面上、变量也对得上）
    if target is None:
        prior_id = prior.get("layer_id") or ""
        if prior_id:
            # 2026-11-07：原来只比 catalog_id，而状态里的 id 可能是产物目录
            # （imported-*）、页面层的 catalog_id 却是目录编号（method-*），
            # 两边永远对不上 ⇒ “沿用上一轮”这一步形同虚设，直接掉到页面选中层，
            # 于是「只改区域」换成了另一颗卫星/另一个口径（外部复测第三组）。
            # 三个身份字段都比一遍，并剥掉 imports/ 前缀。
            want = _bare_layer_id(prior_id)
            candidate = next(
                (
                    la
                    for la in layers
                    if want
                    and want
                    in {
                        _bare_layer_id(str(la.get("catalog_id") or "")),
                        _bare_layer_id(str(la.get("overlay_layer_id") or "")),
                        _bare_layer_id(str(la.get("instance_id") or "")),
                    }
                ),
                None,
            )
            if candidate is not None:
                prior_var = prior.get("variable") or dialogue_state.variable_from_name(
                    _display(candidate)
                )
                if variable is None or variable == prior_var:
                    target = candidate
                    layer_from = "state"
            elif prior.get("layer_name"):
                # 上一轮那一层已经不在页面上了：只要它不与本轮点名的来源/形态
                # 矛盾，就照基线取数（详见 _layer_from_state 的注释）。
                restored = _layer_from_state(prior, client_context)
                if restored is not None:
                    prior_var2 = prior.get(
                        "variable"
                    ) or dialogue_state.variable_from_name(restored["name"])
                    if (
                        variable is None or variable == prior_var2
                    ) and not _contradicts_hints(text, restored):
                        target = restored
                        layer_from = "state"
    # 页面上只有这一层的同变量版本 ⇒ 只能是它
    if target is None:
        var_only = _var_layers()
        if len(var_only) == 1:
            target = var_only[0]
            layer_from = "variable"
    # 以上都不成立才看页面选中 / 唯一可见（保留旧行为，但降到最后）
    if target is None:
        # ★ 2026-11-06 修：用户已经点明变量时，兜底**只能在同变量的层里挑**。
        # 旧实现把全部图层交给 _pick_stat_target，于是「土壤水分的平均值是多少」
        # 会拿页面上选中的「等效散射 ω」算完、再印一个很正式的标题——变量明明
        # 认对了（sm），选层却没受它约束，等于自己打自己。
        same_var = _var_layers()
        if variable and same_var:
            target, why = _pick_stat_target(same_var)
            if target is not None:
                layer_from = "page"
        elif variable:
            # 页面上压根没有这个变量的层：说清楚，不要换一个顶上去
            why = (
                f"当前地图上没有「{dialogue_state.VARIABLE_LABELS.get(variable, variable)}」"
                "这一层的可统计版本。请先把它加回地图，或直接说图层名。"
            )
        else:
            target, why = _pick_stat_target(layers)
            if target is not None:
                layer_from = "page"
        if target is None and not (variable and same_var) and prior.get("layer_name"):
            # 上一轮算的那一层已经不在地图上了：宁可说不知道，也不要用别的层顶上。
            # （用户本轮已点明变量、且页面上确有该变量的层时除外——那种情况
            #   上面给的「这几个同变量层，你要哪个」更贴题。）
            why = (
                f"你上一轮问的是「{prior['layer_name']}」，这一层现在不在页面上，"
                "我不确定该统计哪一层。请先把它加回地图，或直接说要统计的图层名。"
            )

    # 出口校验：消息点名了来源 / 产品形态，最终选中的层却不是那个 ⇒ 页面没有
    # 他要的那一层，不能拿页面上那一层顶上去（详见 _contradicts_hints）。
    if target is not None and _contradicts_hints(text, target):
        target = None
        layer_from = ""
        why = (
            "当前地图上没有与你点名的来源 / 产品形态一致的图层，"
            "我不拿页面上另一层顶上；请确认产品名称，或先把它加到地图上。"
        )

    # 出口校验之后：用户点名了来源 / 产品形态，而页面没有这一层 ⇒ 去目录里
    # **已物化**的同变量产物中认一次。
    # 2026-11-07「照候选清单说『用 SMAP 动态的』」原先答不上来的根因就在这里：
    # `_resolve_layer` 会误命中页面上那层（哪怕文本里没层名），随后被出口校验
    # 否掉，旧逻辑到此为止 ⇒ 回「没有与你点名的来源一致的图层」。可盘上明明
    # 有 SMAP 动态的土壤水分，能直接算。
    if target is None and variable and _has_layer_hints(text):
        catalog_cands = _same_variable_candidates(variable, layers)
        if catalog_cands:
            picked_cat = _narrow_by_hints(text, catalog_cands, prefer_variable=variable)
            if picked_cat is not None and not _contradicts_hints(text, picked_cat):
                target = picked_cat
                layer_from = "catalog"
                why = None

    # 被出口校验否掉之后，再给会话基线一次机会：用户这几轮一直在问的层未必挂在
    # 页面上（页面可能停着另一颗卫星），但基线里记着它真取过的产物 id。
    # 2026-11-07 实测：第 5 句「明确用 SMAP 动态的土壤水分、广州 12-16」，
    # `_resolve_layer` 把页面那层风云当成了「点名的层」→ 出口校验否掉 → 旧逻辑
    # 直接放弃，模型这轮恰好没调工具 ⇒ 兜底答「这次没能取到可用的数值」，
    # 而上一轮同一个区域同一天刚算过。回落基线后这条路径能真算出数。
    if target is None and why and prior.get("layer_name"):
        restored = _layer_from_state(prior, client_context)
        if restored is not None:
            prior_var3 = prior.get("variable") or dialogue_state.variable_from_name(
                restored["name"]
            )
            if (variable is None or variable == prior_var3) and not _contradicts_hints(
                text, restored
            ):
                target = restored
                layer_from = "state"
                why = None

    region = _parse_region_arg(text)
    region_from = "message" if region else ""
    if (
        not region
        and follow_up
        and prior.get("region")
        and not _mentions_unresolvable_region(text)
    ):
        region = prior["region"]
        region_from = "state"
    # ★ 2026-11-07 补：层是按会话基线定下来的时候（layer_from == "state"），区域也该
    # 一起沿用。原来只认 _FOLLOWUP_RE（「其余不变」「只改」…），于是「平均值是多少」
    # 这种「问的还是刚才那个对象」被漏掉：层选对了 SMAP，区域却丢了 ⇒ 算成整幅
    # 0.1625 / 314109 像元，用户会当成河南的值（本地推演 F 场景复现）。
    # 用户明确要整幅 / 全国口径时不沿用，交给工具按整层算。
    elif (
        not region
        and prior.get("region")
        and (
            layer_from in ("state", "catalog")
            # 页面上只有一层时 _resolve_layer 会直接把它认成「用户点名」
            # （layer_from="message"）。若这一层就是上一轮那一层，用户的这一句
            # 其实还是在问同一个对象 —— 层没变，区域也不该凭空变成整层
            # （2026-11-08 r70：上一轮「广州市 11-13」，这一轮「这几天平均」算成整层）。
            or (
                layer_from == "message"
                and isinstance(target, dict)
                and str(prior.get("layer_id") or "")
                == str(target.get("catalog_id") or "")
            )
        )
        and not _NO_REGION_RE.search(text)
        and not _mentions_unresolvable_region(text)
    ):
        region = prior["region"]
        region_from = "state"

    day = _parse_date_arg(text)
    date_from = "message" if day else ""
    if not day:
        # 「12 月 16 日」这种省了年份的说法：年份只能从上一轮/时间轴继承，
        # 继承不到就不猜（宁可回落到时间轴当天的口径，也不能编个年份出来）。
        partial = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", text)
        if partial:
            month, dom = int(partial.group(1)), int(partial.group(2))
            year_hint = ""
            for candidate in (prior.get("date"), _context_date(client_context)):
                head = str(candidate or "")[:4]
                if head.isdigit():
                    year_hint = head
                    break
            if year_hint and 1 <= month <= 12 and 1 <= dom <= 31:
                day = f"{year_hint}-{month:02d}-{dom:02d}"
                date_from = "message"
    if not day and prior.get("date") and _DATE_CARRY_RE.search(text):
        day = prior["date"]
        date_from = "state"

    # 只要年月（「25 年 12 月」「2025-12」「12 月」）——用户要的是**整月口径**。
    # 单独带一个 `month` 字段回给统计分支：那里绝不能把它当成「这句话没提日期」
    # 去落回页面时间轴（2026-11-08 实测就是把 12 月的问题答成了 7 月块）。
    month_hint: tuple[int, int] | None = None
    if not day:
        year_hint_num = 0
        for candidate in (prior.get("date"), _context_date(client_context)):
            head = str(candidate or "")[:4]
            if head.isdigit():
                year_hint_num = int(head)
                break
        month_hint = _parse_month_arg(text, year_hint_num or None)

    if target is not None:
        variable = variable or dialogue_state.variable_from_name(_display(target))

    return {
        "layer": target,
        "layer_from": layer_from,
        "why": why,
        "variable": variable,
        "region": region,
        "region_from": region_from,
        "date": day,
        "date_from": date_from,
        "month": month_hint,
        "follow_up": follow_up,
    }


def _entities_state_patch(entities: dict[str, Any]) -> dict[str, str]:
    """把实体解析结果收敛成要写回会话的对象（只存用户真正说过的项）。"""
    patch: dict[str, str] = {}
    layer = entities.get("layer") or None
    if isinstance(layer, dict) and layer.get("catalog_id"):
        patch["layer_id"] = str(layer["catalog_id"])
        patch["layer_name"] = _display(layer)
    if entities.get("variable"):
        patch["variable"] = str(entities["variable"])
    if entities.get("region"):
        patch["region"] = str(entities["region"])
    # 日期只记用户明确说过 / 明确要求沿用的那一个；页面上的当前日期不算承诺
    if entities.get("date") and entities.get("date_from") in ("message", "state"):
        patch["date"] = str(entities["date"])
    elif entities.get("month"):
        # 「2025 年 12 月」这种整月口径也要记下来（存成 ``YYYY-MM``）：下一句
        # 「换成广州市呢」「换成植被光学厚度」没提时间，就得沿用这个月。
        # 2026-11-09 r116 实测：不记月份 ⇒ 追问退回页面那天（12-15），
        # 而 12-15 在广州是整片缺测，于是「河南 12 月 → 换广州」答成「这里算不出」。
        try:
            patch["date"] = (
                f"{int(entities['month'][0]):04d}-{int(entities['month'][1]):02d}"
            )
        except (TypeError, ValueError, IndexError):
            pass
    return patch


def _carry_note(entities: dict[str, Any]) -> str:
    """「沿用了上一轮的 X」提示句：用了旧对象就必须说，不能让用户以为换了。"""
    carried: list[str] = []
    layer = entities.get("layer")
    if entities.get("layer_from") == "state" and isinstance(layer, dict):
        carried.append(f"图层「{_display(layer)}」")
    if entities.get("region_from") == "state":
        carried.append(f"区域「{entities.get('region')}」")
    if entities.get("date_from") == "state":
        carried.append(f"日期 {_readable_date(str(entities.get('date')))}")
    if not carried:
        return ""
    return f"- 本轮没有重新指定的部分沿用上一轮：{'、'.join(carried)}\n"


def _percent_hint(unit: str | None, mean: Any, text: str) -> str | None:
    """用户问「换算成百分比」时，补一句确定性换算。

    2026-11-07 实测 r33：模型这一轮没调任何取数工具，按设计由规则引擎接管，
    答复里只有「均值：0.2025」，用户问的「百分比是多少」等于没答。只对体积含水量
    （m³/m³）成立——VOD 那种无量纲值乘 100 没有意义。
    """
    try:
        value = float(mean)
    except (TypeError, ValueError):
        return None
    unit_text = str(unit or "")
    if "m³/m³" not in unit_text and "m3/m3" not in unit_text.lower():
        return None
    if not re.search(r"百分|换算", str(text or "")):
        return None
    return f"- 换算成体积百分比：{value * 100:.2f}%（m³/m³ × 100，仅换单位不换口径）"


def _extreme_hint(unit: str | None, res: dict[str, Any], text: str) -> str | None:
    """用户问「最大值 / 最小值」时，直接把那个值点出来，别只给一个区间。

    2026-11-07 实测 r42-j：问「那最大值呢？」，规则引擎接管后只回了
    「范围：0.0820 ~ 0.4564」——答案藏在区间右端，前面还压着一条无关的均值，
    用户得自己找。这里补一句结论，口径照旧：这是**空间最大值**，不是时间峰值，
    也不代表测量精度。
    """
    body = str(text or "")
    try:
        if re.search(r"最大|最高|峰值", body):
            value = float(res.get("max"))
            label = "最大值"
        elif re.search(r"最小|最低", body):
            value = float(res.get("min"))
            label = "最小值"
        else:
            return None
    except (TypeError, ValueError):
        return None
    unit_text = str(unit or "").strip()
    tail = f" {unit_text}" if unit_text and unit_text != "1" else ""
    return f"- {label}：{value:.4f}{tail}（这是范围内单个像元的值，不是时间上的峰值）"


#: 「11 月 9 日到 16 日」「2025-11-09 至 2025-11-16」「9 日到 16 日」这类**日期区间**。
#: 按从具体到笼统的顺序匹配：先认完整年月日，再认「X 月 Y 日到 Z 日」，最后认
#: 省略月份的「Y 日到 Z 日」（月份从会话日期/页面日期借）。
_DATE_RANGE_RES = (
    re.compile(
        r"(20\d{2})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?\s*"
        r"(?:到|至|~|—|－|-)\s*(?:20\d{2}\s*[-/年])?(?:(\d{1,2})\s*[-/月]\s*)?(\d{1,2})"
    ),
    re.compile(
        r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?\s*(?:到|至|~|—|－|-)\s*"
        r"(?:(\d{1,2})\s*月\s*)?(\d{1,2})\s*日"
    ),
    # 这里必须有「日」收尾，否则「0.1 到 0.2 之间」也会被当成日期区间
    re.compile(r"(\d{1,2})\s*日\s*(?:到|至|~|—|－|-)\s*(\d{1,2})\s*日"),
)


def _parse_date_range(text: str, fallback_day: str | None) -> tuple[str, str] | None:
    """认出一句话里的日期区间，返回 (YYYYMMDD, YYYYMMDD)；认不出返回 None。

    只认**同一个月内或跨月**的连续区间，跨度限制在 2~62 天：区间统计要逐日真取数，
    一句「从 2020 到 2025 年」要是放过去，就会变成上千次栅格读取。
    """
    body = str(text or "")
    fb = _compact_date(str(fallback_day or ""))
    fb_year = int(fb[0:4]) if len(fb) == 8 and fb.isdigit() else None
    fb_month = int(fb[4:6]) if len(fb) == 8 and fb.isdigit() else None
    cands: list[tuple[int, int, int, int, int, int]] = []
    m = _DATE_RANGE_RES[0].search(body)
    if m:
        y1, m1, d1, m2, d2 = m.groups()
        y2 = int(y1)
        cands.append((int(y1), int(m1), int(d1), y2, int(m2 or m1), int(d2)))
    else:
        m = _DATE_RANGE_RES[1].search(body)
        if m and fb_year:
            m1, d1, m2, d2 = m.groups()
            cands.append((fb_year, int(m1), int(d1), fb_year, int(m2 or m1), int(d2)))
        else:
            m = _DATE_RANGE_RES[2].search(body)
            if m and fb_year and fb_month:
                d1, d2 = m.groups()
                cands.append((fb_year, fb_month, int(d1), fb_year, fb_month, int(d2)))
    for y1, m1, d1, y2, m2, d2 in cands:
        try:
            start = datetime.date(y1, m1, d1)
            end = datetime.date(y2, m2, d2)
        except ValueError:
            return None
        if end < start:
            start, end = end, start
        span = (end - start).days + 1
        if not 2 <= span <= 62:
            return None
        return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    return None


#: 工具层的「结构性」错误：换哪一天都一样失败，逐日重试毫无意义。
#:
#: 只有「这层根本不是可统计的栅格」「id 认不出」「没有权限」这三类算结构性；
#: 「这片区域这天没有有效像元」是数据本身的状态，属于可预期结果，不在此列。
_STRUCTURAL_STAT_ERROR_RE = re.compile(
    r"还没转成可统计的栅格|无法识别这个图层标识|无权访问"
)


def _user_facing_tool_error(err: str) -> str:
    """把工具层的 error 变成能直接给用户看的一句话。

    工具返回的 error 里经常内嵌**写给模型的指令**，例如实测的这一句：

        这一层目前算不出数值：…还没转成可统计的栅格。请只回答两件事，
        不要给任何数字：① … ② …。正文里不要出现 mat/GeoTIFF/imported-* 这类内部说法。

    兜底路径把 error 原样转述给用户时，这段"请只回答…"就成了莫名其妙的操作要求。
    只保留描述问题的那一句，指令部分丢掉。
    """
    body = str(err or "").strip()
    if not body:
        return ""
    return re.split(r"请只回答|请不要|不要给任何数字|正文里不要", body)[0].strip()


def _range_statistics_reply(
    *,
    text: str,
    target: dict[str, Any],
    region: str | None,
    days: list[str],
    name: str,
    sid: str,
    intents: list[dict[str, Any]],
    client_context: dict[str, Any] | None,
    state: dict[str, str] | None,
    entities: dict[str, Any],
) -> dict[str, Any]:
    """日期区间的只读统计：逐日真取数，再给一个口径写清楚的合并均值。

    2026-11-08 r70 实测留下的坑：一次 ``get_layer_statistics`` 只能读一片栅格，
    用户问「11 月 9 日到 16 日这几天平均多少」时，旧实现拿**第一天**算完就写成
    「整层的只读统计」——把 11-09 的 0.1586 说成 8 天的答案，数字是真、口径是假。
    模型的工具路径当时也各答各的（一句逐日列 8 个数、一句给「合并 0.1097」还编错）。
    这里固定成一种口径：**按各天有效像元数加权**（不是把日均值再平均），
    缺测日不计入，并把「几天有数、几天缺测、每天多少」一起交出去。
    """
    from app.services.agent.server_tools_runtime import _get_layer_statistics

    catalog_id = str(target.get("overlay_layer_id") or target["catalog_id"])
    rows: list[dict[str, Any]] = []
    struct_error = ""
    for day in days:
        args: dict[str, Any] = {"catalog_id": catalog_id, "time": day}
        if region:
            args["region"] = region
        res = _get_layer_statistics(
            args,
            cred=None,
            client_context=client_context,
            user_message=text,
            topic_state=state,
        )
        rows.append(
            {
                "day": day,
                "ok": bool(res.get("ok")),
                "mean": res.get("mean"),
                "min": res.get("min"),
                "max": res.get("max"),
                "pixels": int(res.get("valid_pixels") or 0),
                "daily": bool(res.get("is_daily_frame")),
                "actual": str(res.get("actual_time") or day),
                "block": "_" in str(res.get("actual_time") or ""),
                "error": str(res.get("error") or ""),
            }
        )
        # ★ 2026-11-08：「这一层根本不能统计」不属于「这几天没观测」。
        # 实测 imported-nas-fy-avg-sm 是原始 auto 产品，31 天逐日全部返回同一句
        # 「还没转成可统计的栅格」，旧实现跑满 31 次再答「这 31 天每天都没有有效
        # 像元」——原因说错、还白跑 31 次取数。结构性错误第一次就停，原样转述。
        err = str(res.get("error") or "")
        if err and _STRUCTURAL_STAT_ERROR_RE.search(err):
            struct_error = err
            break
        # ★ 2026-11-09（第十八轮）：区间逐日合并遇到「按需取数服务不可用」时，
        # 也得第一次就停。否则 NAS 隧道整个挂掉（HTTP 530）时，31 天 × 每次 3 次
        # 重试会把对话卡死 3 分多钟，最后还答错原因。这里只拦「服务不可用/
        # 取数过程出错」，不拦「上游该日确实没有成果」（nas_missing 仍逐日继续，
        # 那才是真的「这几天没观测」）。判据取自工具层带回的 ondemand_fetch.reason，
        # 与 _get_layer_statistics 里的措辞口径同源，避免两处漂移。
        _od = res.get("ondemand_fetch") if isinstance(res, dict) else None
        _od_reason = str((_od or {}).get("reason") or "")
        if _od_reason in ("nas_unreachable", "fetch_failed"):
            # 直接给用户看的中性说法，对齐 _ensure_ondemand_frame 里
            # nas_unreachable 分支的 hint：「必须说成取数服务暂时不可用」。
            struct_error = "取数服务暂时不可用，这一天的数据没法按需补取"
            break

    good = [r for r in rows if r["ok"] and r["pixels"] > 0]
    scope_prefix = f"按「{region}」行政边界" if region else "整层"
    span_text = f"{_readable_date(days[0])} 至 {_readable_date(days[-1])}"
    topic_state = _entities_state_patch(entities)
    if struct_error:
        clean = _user_facing_tool_error(struct_error)
        tail = "这次没有取到任何数值，也没有换成别的日期或版本顶替。"
        if "还没转成可统计的栅格" in clean:
            tail = (
                "换页面上已经出过图、能统计的图层，或者先把这个产品转成标准栅格再算。"
                "这次没有取到任何数值，也没有改用别的日期或版本顶替。"
            )
        return {
            "session_id": sid,
            "reply": f"{clean}\n\n{tail}",
            "ui_intents": intents,
            "topic_state": topic_state,
        }
    if not good:
        # 所有天都失败、且原因一致时，说原因而不是「每天都没有有效像元」——
        # 「这层不能统计」和「这层这几天没观测」是两件事，说错了用户会去重跑反演。
        distinct = {_user_facing_tool_error(r["error"]) for r in rows if r["error"]}
        if len(distinct) == 1:
            return {
                "session_id": sid,
                "reply": (
                    f"{distinct.pop()}\n\n"
                    f"所以 {span_text} 这 {len(days)} 天一个数都取不到，"
                    "这次没有改用别的日期或版本顶替。"
                ),
                "ui_intents": intents,
                "topic_state": topic_state,
            }
        return {
            "session_id": sid,
            "reply": (
                f"「{name}」{scope_prefix}在 {span_text} 这 {len(days)} 天里"
                "**每天都没有有效像元**，因此给不出任何平均值。"
                "这通常是上游这几天没有观测入库，换个日期区间或换成另一版本再试。"
            ),
            "ui_intents": intents,
            "topic_state": topic_state,
        }

    total_px = sum(r["pixels"] for r in good)
    combined = sum(float(r["mean"]) * r["pixels"] for r in good) / total_px
    lows = [float(r["min"]) for r in good if r["min"] is not None]
    highs = [float(r["max"]) for r in good if r["max"] is not None]
    missing = [r for r in rows if r not in good]
    blocky = [r for r in good if r["block"]]

    lines = [
        f"「{name}」{scope_prefix}，{span_text} 共 {len(days)} 天：",
        "",
        f"- 合并平均：**{combined:.4f}**（按每天的有效像元数加权，"
        f"不是把 {len(good)} 个日均值再平均）",
        f"- 有效像元合计：{total_px} 个；期间单像元最低 {min(lows):.4f}、最高 {max(highs):.4f}"
        if lows and highs
        else f"- 有效像元合计：{total_px} 个",
        f"- 有观测 {len(good)} 天，缺测 {len(missing)} 天——缺测日**不计入**合并平均",
        "",
        "逐日：",
    ]
    for r in rows:
        day_text = _readable_date(r["day"])
        if not (r["ok"] and r["pixels"] > 0):
            lines.append(f"- {day_text}：该区域没有有效观测")
        else:
            note = ""
            if r["block"] and r["actual"] != r["day"]:
                note = "（取到的是跨天合成块值）"
            lines.append(
                f"- {day_text}：{float(r['mean']):.4f}，有效像元 {r['pixels']} 个{note}"
            )
    if blocky:
        lines.extend(
            [
                "",
                f"说明：其中 {len(blocky)} 天在图层时间清单里没有单日帧，取到的是"
                "覆盖这些日期的多日合成块，块内各天共用同一个值。",
            ]
        )
    lines.append("")
    lines.append("本次只读统计，未创建图层、未写入产物、未提交工作流。")
    return {
        "session_id": sid,
        "reply": "\n".join(lines),
        "ui_intents": intents,
        "topic_state": topic_state,
    }


def _statistics_reply(
    text: str,
    layers: list[dict[str, Any]],
    client_context: dict[str, Any] | None,
    sid: str,
    intents: list[dict[str, Any]],
    *,
    state: dict[str, str] | None = None,
) -> dict[str, Any]:
    """整层只读统计（规则演示模式也能算，不再回答「没有统计能力」）。

    2026-11-06：取数对象改由 ``resolve_entities`` 决定——先认本轮点名的层与
    区域，认不出来再沿用会话里记着的那个对象，最后才回落到页面选中层。
    旧实现只做「本轮点名 → 页面选中」，于是「其余不变」这类追问必然换成页面
    上那一层、区域也一并丢失（外部测试第 2/3 条）。
    """
    entities = resolve_entities(
        text, layers, client_context=client_context, state=state
    )
    target = entities.get("layer")
    if not isinstance(target, dict):
        # 2026-11-07：这里原先直接回 why 一句，措辞随轮次漂移。改成交给
        # _undecided_statistics_reply：能唯一确定就直接算，有多种来源就列清单。
        picked, stop = _undecided_statistics_reply(
            text=text, entities=entities, layers=layers, sid=sid, intents=intents
        )
        if picked is None:
            return stop  # type: ignore[return-value]
        target = picked
        entities = {**entities, "layer": picked, "layer_from": "resolved"}
        # 这一句只点了层/口径（「再换回平均版」），区域和日期没提 ⇒ 沿用上一轮。
        # 2026-11-08 实测 r69 第 4 句：前三轮都是「广州市 / 2025-11-13」，这句却算成
        # 「整层 / 2025-12-16」（时间轴当天）——同一次对话里口径突然变了，用户看到的
        # 数字跟前三句没法比。原因：区域沿用只认 layer_from in ("state","catalog")，
        # 而这里标的是 "resolved"，于是两样都掉了。
        # 只在两种情况补：① 用户这句话带层线索（来源/形态词）；② **收窄出来的层
        # 就是上一轮那一层**——层没变，口径就不该自己变。②是 2026-11-08 r70 实测
        # 补的：上一轮「广州市 11-13」，这一轮「11 月 9 日到 16 日这几天平均下来是
        # 多少」既不带层线索也不带区域，于是区域整个丢掉、算成整层，数字跟上一轮
        # 没法比。问「土壤水分平均值」这种没说清是哪一层的，仍按原行为交给
        # _resolve_entities 决定，不擅自扩大沿用范围。
        _same_layer_as_before = bool(state) and str(state.get("layer_id") or "") == str(
            picked.get("catalog_id") or ""
        )
        if state and (_has_layer_hints(text) or _same_layer_as_before):
            if not entities.get("region") and state.get("region"):
                if not _NO_REGION_RE.search(text):
                    entities = {
                        **entities,
                        "region": str(state["region"]),
                        "region_from": "state",
                    }
            if not entities.get("date") and state.get("date"):
                entities = {
                    **entities,
                    "date": str(state["date"]),
                    "date_from": "state",
                }

    # ★ 通用防线：与选层逻辑解耦。将来谁再改选层、正则或兜底顺序，只要「用户
    # 说的变量」和「实际挑中的层变量」对不上，就在这里被拦住——绝不拿另一个
    # 变量算完、再印一个看着很正式的标题（2026-11-06：问土壤水分、答等效散射 ω）。
    said_var = str(entities.get("variable") or "")
    target_var = dialogue_state.variable_from_name(_display(target))
    if said_var and target_var and said_var != target_var:
        # 2026-11-07：这里只回一句「两个不是同一个变量」太干。用户问土壤水分、
        # 页面只挂着 ω 时，本机其实有四族可算的土壤水分——同一句话补上候选清单，
        # 「绝不拿别的变量顶替」这条契约不变，只是顺手告诉他有哪些能选。
        lead = (
            f"你说的是「{dialogue_state.VARIABLE_LABELS.get(said_var, said_var)}」，"
            f"但按当前页面能统计的是「{_display(target)}」——两个不是同一个变量，"
            "我不拿它顶替。"
        )
        picked, stop = _undecided_statistics_reply(
            text=text,
            entities={**entities, "variable": said_var},
            layers=layers,
            sid=sid,
            intents=intents,
            lead=lead,
        )
        if picked is None:
            return stop or {
                "session_id": sid,
                "reply": lead,
                "ui_intents": intents,
                "topic_state": {},
            }
        target = picked
        entities = {**entities, "layer": picked, "variable": said_var}

    from app.services.agent.server_tools_runtime import _get_layer_statistics

    day = entities.get("date")
    # 这一句没提日期（「换成广州市呢」），但上一轮记着时间口径 —— 沿用，别退回页面。
    # 原来这条沿用只写在「层还没定」的分支里；层一旦从会话状态取到就直接跳过了，
    # 于是追问会掉到页面时间轴那天（2026-11-09 r116 实测：河南 12 月 → 换广州 →
    # 取到 12-15，广州当天整片缺测，答成「算不出」）。整月口径存成 ``2025-12``，
    # 由下面那段 month_scope 认出来。
    if not day and not entities.get("month") and isinstance(state, dict):
        carried_date = str(state.get("date") or "").strip()
        if carried_date:
            day = carried_date
            entities = {**entities, "date": carried_date, "date_from": "state"}
    # 「2025 年 12 月」「25 年 12 月」这种**只要年月**的说法：用户要的是整月口径。
    # 绝不能落回页面时间轴——2026-11-08 实测就是拿页面停在的 07-31 顶上，
    # 把「12 月平均土壤水分」答成 7 月块（数值都真，月份全错，还一声不响）。
    month_scope: tuple[int, int] | None = None
    month_anchor = ""
    _raw_month = entities.get("month")
    if not day and _raw_month:
        try:
            month_scope = (int(_raw_month[0]), int(_raw_month[1]))
        except (TypeError, ValueError, IndexError):
            month_scope = None
    # 上一轮记的是整月口径（状态里存 ``2025-12``），这一句只换了区域或变量——
    # 沿用那个月，不能退回页面那一天。2026-11-09 r116 实测：「河南 12 月」之后
    # 接「换成广州市呢」，模型拿页面日期 12-15 去取，广州当天 247 像元全缺测，
    # 答复成了「这天算不出」，与上一句的整月口径完全不是一回事。
    if not month_scope:
        _carried_date = str(entities.get("date") or "")
        if re.fullmatch(r"\d{4}-\d{2}", _carried_date):
            try:
                month_scope = (int(_carried_date[:4]), int(_carried_date[5:7]))
            except ValueError:
                month_scope = None
    if month_scope:
        # 锚点必须是**整月块自己**（20251201_20251231），不能挑月里某一天：
        # 2026-11-08 实测取月中 12-15，正好命中按需补出的单日帧（preview_20251215），
        # 那天广州 247 个像元全 NoData，于是「12 月平均」被答成「这一片没有有效像元」；
        # 而 12 月整月块本身有 36/247 像元、均值 0.3399。差的就是锚点选在哪。
        # 具体用哪个键，等 target 定下来再查时间清单（见下面 month_anchor）。
        day = f"{month_scope[0]:04d}-{month_scope[1]:02d}-01"
    # 句子里明明提到了月份，却认不出是哪一年哪一月（「去年的 12 月」这种）：
    # 宁可说没听懂，也不能落回页面时间轴——那正是「12 月问题答成 7 月」的老路。
    if not day and not month_scope and _MONTH_HINT_RE.search(str(text or "")):
        return {
            "session_id": sid,
            "reply": (
                "你这句里提到了月份，但我没认出是**哪一年哪一月**，所以这次没有取数，"
                "也没有拿页面时间轴上停着的日期顶替。\n\n"
                "请说成年月，比如「2025 年 12 月」；或者说具体某一天，比如「2025-12-15」。"
            ),
            "ui_intents": intents,
            "topic_state": {},
        }
    if not day and isinstance(client_context, dict):
        timeline = client_context.get("timeline")
        if isinstance(timeline, dict):
            raw_date = str(timeline.get("date") or "").strip()
            if raw_date:
                day = raw_date
    # 「广州市」「四川省」这类行政区名必须进 region，否则算出来的是全球均值，
    # 用户会当成该市的值（外部测试 2026-11-04 就是这么错答的）。
    region = entities.get("region")

    # 县 / 市辖区一级算不了（只支持到地级市），但**绝不能静默按整幅算**：
    # 2026-11-08 r73 实测「天河区的土壤水分平均值」被答成整层 0.1534，正文里
    # 连"天河"都没出现，用户当成天河区的值拿去用。这里明确回一句并给两条出路。
    if not region:
        # 「中国 / 全国」也不是可统计的行政区范围（只到省与地级市），绝不能
        # 静默退回整幅全球、也不能沿用上一轮区域（2026-11-10 线上实测：先问河北
        # 再问「中国区域」被答成河北 0.2403）。明确回一句并给两条出路。
        if _mentions_china_scope(text):
            return {
                "session_id": sid,
                "reply": (
                    "「中国 / 全国」不是系统里可统计的行政区范围——目前只做到**省级和地级市**，"
                    "没有「中国全境」这一级掩膜，所以这次没有取数，也没有拿别的地区或全球整幅的数值顶替。\n\n"
                    "两条路任选：\n"
                    "① 换成具体的省或地级市（例如「河南省」「广州市」），我按行政边界统计；\n"
                    "② 给我一个矩形范围（西、南、东、北四个经纬度，例如 [73, 18, 135, 53] 附近），"
                    "我按这个框统计。"
                ),
                "ui_intents": intents,
                "topic_state": {},
            }
        _county = _county_like_region_name(text)
        if _county:
            return {
                "session_id": sid,
                "reply": (
                    f"「{_county}」这一级按行政边界算不了：现在只支持到**省 / 地级市**，"
                    "市辖区和县不在支持范围内。硬按整幅算出来的数不是你要的范围，"
                    "我不会拿它顶替。\n\n两条路：\n"
                    f"① 换成它所属的地级市（例如直接说「广州市」），我按市界掩膜算；\n"
                    "② 给我一个矩形范围（西、南、东、北四个经纬度），我按这个框统计。"
                ),
                "ui_intents": intents,
                "topic_state": {},
            }
        # 用户提了一个「带省/市尾词、但系统认不出」的地名（如「甲壳虫省」）——
        # 绝不能静默退回整幅，也不能沿用上一轮的区域。2026-11-09（第十八轮）实测
        # 问「甲壳虫省」被顺成上一轮的「山东省」算了数。这里明确转述「没认出」。
        if _mentions_unresolvable_region(text):
            return {
                "session_id": sid,
                "reply": (
                    "你提到的这个地名我没能对应到系统里的行政区，所以这次没有取数，"
                    "也没有拿别的地区或整幅的数值顶替。\n\n"
                    "请再给一次规范名称（省 / 自治区 / 地级市，例如「河南省」"
                    "「广州市」）；或者直接给我一个矩形范围（西、南、东、北四个经纬度），"
                    "我按这个框统计。"
                ),
                "ui_intents": intents,
                "topic_state": {},
            }

    # 日期区间（「11 月 9 日到 16 日」「9 日至 16 日」）走单独一条路：一片栅格只能
    # 代表一个时间块，拿区间里第一天算完再写成「整层的只读统计」，数字是真的、
    # 口径是假的（2026-11-08 r70 实测：问 8 天的平均，回了 11-09 的 0.1586）。
    # 模型路径当时还各答各的（一处逐日列 8 个数、一处给「合并 0.1097」且编错），
    # 所以这里把它钉成一种口径：逐日真取数 + 按有效像元加权合并。
    _rng = _parse_date_range(text, str(day or ""))
    if _rng:
        _start = datetime.date(int(_rng[0][0:4]), int(_rng[0][4:6]), int(_rng[0][6:8]))
        _end = datetime.date(int(_rng[1][0:4]), int(_rng[1][4:6]), int(_rng[1][6:8]))
        _days: list[str] = []
        _cur = _start
        while _cur <= _end:
            _days.append(_cur.strftime("%Y%m%d"))
            _cur += datetime.timedelta(days=1)
        return _range_statistics_reply(
            text=text,
            target=target,
            region=region,
            days=_days,
            name=_display(target),
            sid=sid,
            intents=intents,
            client_context=client_context,
            state=state,
            entities=entities,
        )

    _target_cid = str(target.get("overlay_layer_id") or target["catalog_id"])
    if month_scope:
        # 只在该层**确实有该月整月块**时才用块键取数；没有就直接走逐日合并。
        # 把块键发给按需补帧逻辑会抛「日期必须是 8 位」并拖慢整条链路。
        month_anchor, _month_present = _month_scan(
            _target_cid, month_scope[0], month_scope[1]
        )
        if not month_anchor:
            if not _month_present:
                return {
                    "session_id": sid,
                    "reply": (
                        f"「{_display(target)}」里**没有 {month_scope[0]} 年 "
                        f"{month_scope[1]:02d} 月的数据**，所以这个月的平均值取不到。\n\n"
                        "这次没有拿别的月份顶替。你可以换个月份，"
                        "或者让我把这一层实际有的时间块列出来。"
                    ),
                    "ui_intents": intents,
                    "topic_state": _entities_state_patch(entities),
                }
            return _range_statistics_reply(
                text=text,
                target=target,
                region=region,
                days=_month_day_list(month_scope[0], month_scope[1]),
                name=_display(target),
                sid=sid,
                intents=intents,
                client_context=client_context,
                state=state,
                entities=entities,
            )

    stat_args: dict[str, Any] = {
        # 2026-11-06：必须用页面那一层实际挂着的产物 id（imported-*）。
        # 目录层 id（method-*）在盘上没有同名目录，拿它统计只会得到
        # 「不是本地运行时产物」，兜底路径就会退化成一句「本次未取到数值」——
        # 而模型正常调工具时是同一条链路、同一天，本来能算出数。
        "catalog_id": _target_cid,
        "time": month_anchor or day or None,
    }
    if region:
        stat_args["region"] = region
    res = _get_layer_statistics(
        stat_args,
        cred=None,
        client_context=client_context,
        user_message=text,
        # 与模型路径同一条规矩：会话里记着的对象才是「上一轮那层」的事实源
        topic_state=state,
    )
    # 兜底：清单说有整月块、实际却没按整月块返回（工具异常/产物被换掉）时，
    # 不能把命中某一天的数当成月均值——改走逐日合并，口径与区间统计一致。
    if (
        month_scope
        and isinstance(res, dict)
        and not _month_block_covers(res, month_scope[0], month_scope[1])
    ):
        return _range_statistics_reply(
            text=text,
            target=target,
            region=region,
            days=_month_day_list(month_scope[0], month_scope[1]),
            name=_display(target),
            sid=sid,
            intents=intents,
            client_context=client_context,
            state=state,
            entities=entities,
        )
    topic_state = _entities_state_patch(entities)
    carry_note = _carry_note(entities)

    name = _display(target)
    # 工具侧判定「这一句没点名换产品」，把层改回了上一轮那层 ⇒ 标题必须跟着改，
    # 否则会出现「数字是 SMAP 动态、标题写着风云平均」这种更隐蔽的错。
    if res.get("product_pinned"):
        pinned_name = str(res.get("display_name") or "").strip()
        if pinned_name:
            name = pinned_name
        carry_note = "；".join(x for x in (carry_note, "产品沿用上一轮") if x)
    scope_prefix = f"按「{region}」行政边界" if region else "整层"
    if not res.get("ok"):
        # ★ 2026-11-07：``error`` 是**给模型看的指令**（跨来源守卫那份甚至写着
        # 「回答里不得出现任何统计数值」），旧代码把它原样拼进正文，用户会读到
        # 一段自我训话。工具给了 ``user_facing`` 就直接用它当整段回复。
        user_facing = str(res.get("user_facing") or "").strip()
        if user_facing:
            return {
                "session_id": sid,
                "reply": user_facing,
                "ui_intents": intents,
                "topic_state": {},
            }
        reason = str(res.get("error") or "统计未成功")
        # 空片（整片 NoData）要单独说清：这不是「取数失败」，而是这一片本来就没有数据。
        # 外部测试第 3 轮模型说「11 月 13 日没有对应日期」——日期在，是片子里没值。
        period_start = str(res.get("period_start") or "").strip()
        period_end = str(res.get("period_end") or "").strip()
        block = ""
        if period_start:
            block = _readable_date(period_start)
            if period_end and period_end != period_start:
                block += f" 至 {_readable_date(period_end)}"
        if res.get("valid_pixels") == 0 and block:
            asked = str(res.get("requested_time") or "").strip()
            asked_note = (
                f"你问的 {_readable_date(asked)} 就落在这一片里，"
                "这一片本身是空的（空产物），不是日期不存在。"
                if asked and asked != str(res.get("actual_time") or "")
                else ""
            )
            return {
                "session_id": sid,
                "reply": (
                    f"「{name}」{scope_prefix}在 {block} 这一片**没有任何有效像元**"
                    f"（整片 NoData，有效像元 0 个），因此无法给出均值。"
                    f"{asked_note}"
                    "本次只读统计，未创建图层、未提交工作流。"
                ),
                "ui_intents": intents,
                "topic_state": topic_state,
            }
        if res.get("available_blocks"):
            blocks = "、".join(str(b) for b in res["available_blocks"][:3])
            reason = f"{reason}（该图层可用时间块：{blocks}）"
        return {
            "session_id": sid,
            "reply": (
                f"「{name}」{scope_prefix}统计没有完成：{reason}。"
                f"{carry_note}未创建图层、未提交工作流。"
            ),
            "ui_intents": intents,
            "topic_state": topic_state,
        }

    source = str(res.get("source_label") or "").strip()
    unit = str(res.get("unit_label") or res.get("unit") or "").strip()
    period_start = str(res.get("period_start") or "").strip()
    period_end = str(res.get("period_end") or "").strip()
    if period_start and period_start != period_end:
        block = f"{_readable_date(period_start)} 至 {_readable_date(period_end)}"
    elif period_start:
        block = _readable_date(period_start)
    else:
        block = str(res.get("actual_time") or "")
    mean = res.get("mean")
    pct = res.get("valid_ratio")
    # 图层名里往往已含来源（「SMAP 土壤水分」），就别再补一个（SMAP）
    suffix = f"（{source}）" if source and source not in name else ""
    lines = [
        f"「{name}」{suffix}{scope_prefix}的只读统计：",
        (
            f"- 均值：{float(mean):.4f} {unit}".rstrip()
            if mean is not None
            else "- 均值：—"
        ),
        (
            f"- 范围：{float(res['min']):.4f} ~ {float(res['max']):.4f}"
            if res.get("min") is not None and res.get("max") is not None
            else "- 范围：—"
        ),
        # 2026-11-09 外部实测：分母 437 其实是读取窗口（23×19）总数、含边界外，
        # 模型把它说成「边界内共 437 个像元」。正文只把 valid_pixels 说成
        # 「边界内有效像元数」，不再拿 total_pixels 当行政边界分母。
        f"- 边界内有效像元：{res.get('valid_pixels')} 个"
        + (
            f"（读取窗口 {res.get('analyzed_height')}×{res.get('analyzed_width')}"
            f" 共 {res.get('total_pixels')} 像元，含边界外）"
            if res.get("analyzed_width") and res.get("analyzed_height")
            else ""
        )
        + (f"（占窗口 {float(pct) * 100:.1f}%）" if pct is not None else ""),
        f"- 实际数据时间块：{block}",
    ]
    if month_scope:
        # 问的是「某月」：明确说这是月均、不是某一天。否则用户会以为系统又给他
        # 挑了一天（12 月那次就是这么被质疑的：「一开始问的月，怎么又变成天的了」）。
        lines.insert(
            5,
            f"- 口径：你要的是 **{month_scope[0]} 年 {month_scope[1]:02d} 月整月**，"
            f"这一层该月本身就是整月合成块（{block}），"
            "所以上面的均值就是这个月的月均，不是某一天的值。",
        )
    # 问「换算成百分比」时补一句确定性换算（模型这一轮没调工具、由规则引擎接管
    # 的情况下，否则用户只拿到 0.2025，问的换算没答）
    hint = _percent_hint(unit, mean, text)
    if hint:
        lines.insert(2, hint)
    # 问「那最大值呢」时把值点出来，不用他从「范围」右端自己找
    extreme = _extreme_hint(unit, res, text)
    if extreme:
        lines.insert(3, extreme)
    requested = "" if month_scope else str(res.get("requested_time") or "").strip()
    if requested and requested != str(res.get("actual_time") or ""):
        lines.append(
            f"- 你请求的日期是 {_readable_date(requested)}，它落在上面的时间块内，"
            "该图层没有这一天的独立观测。"
            if res.get("is_single_block")
            else f"- 你请求的日期是 {_readable_date(requested)}，实际取的是上面那个时间块。"
        )
    if carry_note:
        # 沿用旧对象必须写明，否则用户会以为「其余不变」真的什么都没变
        lines.append(carry_note.rstrip("\n"))
    lines.append(
        f"统计范围是「{region}」行政边界内的有效像元（已排除 NoData），"
        "不是矩形框，也未按视口裁剪。"
        if region
        else "统计范围是整幅栅格的有效像元（已排除 NoData），不是点样本均值，也未按视口裁剪。"
    )
    lines.append("本次只读统计，未创建图层、未写入产物、未提交工作流。")
    return {
        "session_id": sid,
        "reply": "\n".join(lines),
        "ui_intents": intents,
        "topic_state": topic_state,
    }


def forced_statistics_reply(
    message: str,
    *,
    client_context: dict[str, Any] | None = None,
    session_id: str | None = None,
    state: dict[str, str] | None = None,
) -> dict[str, Any]:
    """服务端强制走一次「整层/行政边界统计」，不走关键词分流。

    2026-11-04 新增，给 ``orchestrator._statistics_fallback_reply`` 用：
    模型这一轮**一个取数工具都没调**时，不能再靠 ``_STAT_VERB`` 那串关键词判断
    （「是多少」压根不在里面，正是漏判的原因），直接进统计分支，算出真值。

    2026-11-06：多收一个 ``state``（本会话已确认的取数对象）。兜底是**唯一**
    能在模型不说话时给数字的路径，如果它没有上下文，就会拿「页面当前层 + 全幅」
    算出一个看着很正式、其实答非所问的数字——外部测试第 3 条就是这么错的。
    """
    sid = (session_id or "").strip() or str(uuid.uuid4())
    layers = _normalize_layers(client_context)
    return _statistics_reply(
        str(message or ""), layers, client_context, sid, [], state=state
    )


def mock_chat(
    message: str,
    *,
    session_id: str | None = None,
    client_context: dict[str, Any] | None = None,
    state: dict[str, str] | None = None,
    _allow_stats: bool = True,
) -> dict[str, Any]:
    """Return reply + optional ui_intents from keyword rules.

    ``_allow_stats=False`` 仅供内部递归调用（处理复合指令的第二个子句）使用，
    避免子句里再出现「均值」二字时又跳回统计分支造成死循环。
    ``state`` 是本会话已确认的取数对象，只影响统计分支的选层/选区域。
    """
    sid = (session_id or "").strip() or str(uuid.uuid4())
    text = (message or "").strip()
    layers = _normalize_layers(client_context)
    intents: list[dict[str, Any]] = []
    # 供 human_layer_name 兜底：把上下文里的 id→中文名登记进去
    name_ctx = {"active_layers": [dict(item) for item in layers]}
    if isinstance(client_context, dict) and isinstance(
        client_context.get("active_layers"), list
    ):
        name_ctx = client_context
    names = build_layer_name_map(name_ctx)

    def display(catalog_id: str, fallback: str | None = None) -> str:
        if catalog_id in names:
            return names[catalog_id]
        return human_layer_name(catalog_id, name_ctx, default=fallback)

    if not text:
        return {
            "session_id": sid,
            "reply": "请告诉我你想做什么，例如「打开降水图层」或「有哪些活动图层」。",
            "ui_intents": [],
        }

    # 项目核心术语与拒答边界由程序固定，演示模式与大模型模式使用同一口径。
    from app.services.agent.knowledge_guard import project_knowledge_reply

    knowledge_reply = project_knowledge_reply(text)
    if knowledge_reply is not None:
        return {"session_id": sid, "reply": knowledge_reply, "ui_intents": []}

    # 整层只读统计：必须排在「列图层」与「工作流」两个分支之前——
    # ① 「列图层」的 `当前图层` 会误命中「只读计算当前图层全范围均值」；
    # ② 「工作流」分支会把「不要运行任何工作流」当成工作流请求。
    #
    # 2026-10-27：复合指令（「算均值，并把 VOD 打开」）原来在这里直接 return，
    # 后半句被吞掉、界面纹丝不动。现在把非统计子句交给下一个分支递归执行，
    # 意图合并返回，正文另起一段说明。
    if _allow_stats and _STAT_VERB.search(text):
        result = _statistics_reply(
            text, layers, client_context, sid, intents, state=state
        )
        side = _side_clauses(text)
        if side and side.strip() != text.strip():
            follow = mock_chat(
                side,
                session_id=sid,
                client_context=client_context,
                state=state,
                _allow_stats=False,
            )
            extra = list(follow.get("ui_intents") or [])
            if extra:
                result["ui_intents"] = list(result.get("ui_intents") or []) + extra
                head = str(result.get("reply") or "").rstrip()
                tail = str(follow.get("reply") or "").strip()
                if tail:
                    result["reply"] = f"{head}\n\n另外：{tail}"
        return result

    # 「当前选中是哪个图层」——必须给出真名。
    # 原来这句落到通用兜底，答案只有「该图层」（2026-10-26 实测缺陷 ④）。
    if re.search(
        r"当前选中|选中了?哪|哪个图层.*选中|选中的(图层|是)|selected\s*layer",
        text,
        re.I,
    ):
        sel = [la for la in layers if la.get("selected")]
        vis = [la for la in layers if la.get("visible")]
        if len(sel) == 1:
            # 2026-11-11 老师复测：隐藏某层后问「现在选中的是哪个」，只答层名会让
            # 人以为它还画在图上（"selected" 和 "visible" 是两个概念）。勾选显示和
            # 选中查看必须分开说清楚，这一条要和提示词里的口径一致。
            title = _layer_display_with_identity(sel[0])
            if sel[0].get("visible"):
                reply = f"当前选中的是「{title}」，它同时也是勾选显示的。"
            else:
                reply = (
                    f"当前选中的是「{title}」——它是当前选中，但已隐藏，"
                    "画面上看不到。要让它重新显示，说「显示这一层」即可。"
                )
        elif not sel and len(vis) == 1:
            # 2026-11-11 用户实测：把其余层都隐藏、只剩一层可见，前端没有回传
            # selected（隐藏时仍设选中是前端设计，但可能落空）。旧实现先说
            # 「当前没有选中任何图层」，紧接着又说「土壤水分处于勾选显示状态」——
            # 同一句话里自相矛盾。唯一可见的那层就是用户眼里的当前层，照它回答。
            reply = (
                f"当前选中的是「{_layer_display_with_identity(vis[0])}」"
                "（它也是唯一勾选显示的图层）。"
            )
        elif not sel:
            if vis:
                names = "、".join(
                    f"「{_layer_display_with_identity(la)}」" for la in vis[:5]
                )
                reply = f"当前没有单独选中某一层；正在勾选显示的是：{names}。"
            elif layers:
                names = "、".join(
                    f"「{_layer_display_with_identity(la)}」" for la in layers[:5]
                )
                reply = f"当前没有选中任何图层，已加载的图层是：{names}。"
            else:
                reply = "当前地图上没有图层，也没有选中项。"
        else:
            names = "、".join(
                f"「{_layer_display_with_identity(la)}」" for la in sel[:5]
            )
            reply = f"当前选中了 {len(sel)} 个图层：{names}。"
        return {"session_id": sid, "reply": reply, "ui_intents": intents}

    # List active layers
    #
    # 2026-11-11 老师复测：「把当前图层切换到 2025年12月25日」日期没切。根因不是
    # 时间正则不认「切换到」，而是**这句先被这里的「当前图层」截胡**——直接列出
    # 图层清单就 return，日期压根没走到下面的时间分支。列出图层不会带完整日期，
    # 带了完整日期说明这句是「切时间」，让给时间分支。
    if _parse_date_arg(text) is None and re.search(
        r"哪些.*(图层|层)|活动图层|当前图层|查看.*图层|list.*layer", text, re.I
    ):
        if not layers:
            reply = (
                "当前地图上还没有图层。可以在左侧「图层目录」里添加，"
                "或直接说「打开 CMFD 降水」让我帮你打开一个示例图层。"
            )
        else:
            # 来源前缀：两个「土壤水分」分属 SMAP 与风云卫星，只有名字分不清
            # （报告优先4 的同一条根因）。拿不到来源就只写图层名。
            from app.services.agent.server_tools_runtime import _layer_identity_fields

            lines = []
            for layer in layers:
                title = _display(layer)
                try:
                    ident = _layer_identity_fields(str(layer.get("catalog_id") or ""))
                    source = str(ident.get("source_label") or "").strip()
                except Exception:
                    source = ""
                if source and source != "未标注来源" and source not in title:
                    title = f"{source} · {title}"
                lines.append(f"- {title}")
            reply = f"当前有 {len(layers)} 个活动图层：\n" + "\n".join(lines)
        return {"session_id": sid, "reply": reply, "ui_intents": intents}

    # Fit China (before generic fit / city locate)
    if re.search(
        r"中国\s*(全境|全图|范围|地图)|全国\s*(范围|全图)|缩放到\s*中国|"
        r"zoom\s*to\s*china|fit\s*china",
        text,
        re.I,
    ):
        intents.append({"name": "fit_china", "args": {}})
        return {
            "session_id": sid,
            "reply": "已缩放到中国全境。",
            "ui_intents": intents,
        }

    # Switch basemap
    #
    # 原来条件是 `切换.*(图|影像|街道)`，「切换到 VOD 图层」里的「图层」含「图」
    # 就被当成切底图，回「请说明要切换的底图」（2026-10-26 实测缺陷 ③）。
    # 现在必须出现真正的底图词（或明确的底图服务名），且句子里没有「图层/时间」。
    _basemap_words = re.search(
        r"底图|basemap|天地图|高德|esri|osm|openstreetmap", text, re.I
    )
    _basemap_swap = re.search(r"切换|换成|改为|换到", text, re.I) and re.search(
        r"影像|街道|地形|卫星|矢量|电子", text, re.I
    )
    if (_basemap_words or _basemap_swap) and not re.search(
        r"图层|时间轴|日期|帧", text, re.I
    ):
        for pattern, source_id, label in _BASEMAP_HINTS:
            if pattern.search(text):
                intents.append(
                    {
                        "name": "switch_basemap",
                        "args": {"basemap_id": source_id},
                    }
                )
                return {
                    "session_id": sid,
                    "reply": f"已切换到{label}底图。",
                    "ui_intents": intents,
                }
        return {
            "session_id": sid,
            "reply": (
                "请说明要切换的底图，例如「切换为天地图影像」或「高德街道底图」。"
            ),
            "ui_intents": [],
        }

    # Locate by explicit coordinates
    coords = _parse_lng_lat(text)
    if coords is not None and re.search(
        r"定位|飞到|坐标|经纬|locate|fly\s*to", text, re.I
    ):
        lng, lat = coords
        intents.append(
            {
                "name": "locate_coordinate",
                "args": {"lng": lng, "lat": lat, "zoom": 11},
            }
        )
        return {
            "session_id": sid,
            "reply": f"已定位到经度 {lng:.4f}、纬度 {lat:.4f}。",
            "ui_intents": intents,
        }

    # Locate well-known cities
    if re.search(r"定位|飞到|缩放到|去|locate|fly\s*to", text, re.I):
        for pattern, lng, lat, label in _CITY_COORDS:
            if pattern.search(text):
                intents.append(
                    {
                        "name": "locate_coordinate",
                        "args": {"lng": lng, "lat": lat, "zoom": 11},
                    }
                )
                return {
                    "session_id": sid,
                    "reply": f"已定位到{label}。",
                    "ui_intents": intents,
                }

    # Timeline play / pause
    if re.search(r"暂停.*(时间|播放|轴)|停止播放|pause", text, re.I):
        intents.append({"name": "set_timeline_playing", "args": {"playing": False}})
        return {
            "session_id": sid,
            "reply": "已暂停时间轴播放。",
            "ui_intents": intents,
        }
    if re.search(r"播放时间|开始播放|自动播放|play\s*timeline", text, re.I):
        intents.append({"name": "set_timeline_playing", "args": {"playing": True}})
        return {
            "session_id": sid,
            "reply": "已开始播放时间轴。",
            "ui_intents": intents,
        }

    # Set timeline clock
    hour_m = re.search(r"(?:设为|调到|跳到|时间)\s*(\d{1,2})\s*[点时:：]", text, re.I)
    date_str = _parse_date_arg(text)
    if hour_m or (
        date_str and re.search(r"时间|日期|时刻|切|跳|切到|timeline", text, re.I)
    ):
        args_tl: dict[str, Any] = {}
        if hour_m:
            h = int(hour_m.group(1))
            if 0 <= h <= 23:
                args_tl["hour"] = h
        if date_str:
            args_tl["date"] = date_str
        if args_tl:
            # 「添加 CMFD 并切换到 2025-12-01」：时间分支排在显隐分支之前，
            # 旧实现只下发 set_timeline 就 return，添加那一步**根本没执行**，
            # 回执却写「已切到」。老师复测（2026-11-11）：「它成功添加了 CMFD，
            # 但页面把这个图层标记为静态数据」——说明前端拿到了日期意图却没有
            # 对应的新实例可绑。这里先补添加，日期才能落到新加的实例上。
            added: list[str] = []
            pick_add: LayerPick | None = None
            if re.search(r"添加|加上|加载|打开|显示|开启", text, re.I):
                pick_add = _resolve_layer(text, layers)
                if pick_add is None and not _page_has_named_candidate(text, layers):
                    pick_add = _catalog_pick(text)
                if pick_add is not None:
                    added.append(pick_add.name)
                    intents.append(
                        {
                            "name": "set_layer_visibility",
                            "args": {
                                "catalog_id": pick_add.catalog_id,
                                "visible": True,
                                "display_name": pick_add.name,
                            },
                        }
                    )
            reply, changeable = _build_timeline_reply(
                args_tl,
                client_context,
                # 目标层：本次新添加的那层 → 页面当前那一层。静态层不能切日期，
                # 必须在正文里说清楚，而不是先写「已切到」再让前端拒绝。
                static_name=(
                    _static_target_name(
                        pick_add.catalog_id if pick_add is not None else None,
                        layers,
                    )
                ),
            )
            # 超出可用范围 ⇒ 不生成意图，避免「前端换了、正文说没数据」自相矛盾
            if changeable:
                intents.append({"name": "set_timeline", "args": args_tl})
            if added:
                reply = f"已把「{added[0]}」添加到地图并显示。\n" + reply
            return {"session_id": sid, "reply": reply, "ui_intents": intents}

    # Remove layer
    if re.search(r"移除|删除|去掉|remove\s*layer|remove\b", text, re.I):
        pick = _resolve_layer(text, layers)
        if not pick:
            return {
                "session_id": sid,
                "reply": _layer_choices(layers),
                "ui_intents": [],
            }
        intents.append(
            {
                "name": "remove_layer",
                "args": {
                    "catalog_id": pick.catalog_id,
                    "display_name": pick.name,
                },
            }
        )
        return {
            "session_id": sid,
            "reply": f"已从图层面板移除「{pick.name}」（后端产物保留，不会被删除）。",
            "ui_intents": intents,
        }

    # Reorder
    if re.search(r"置顶|提到最前|bring\s*to\s*front", text, re.I):
        pick = _resolve_layer(text, layers)
        if pick:
            intents.append(
                {
                    "name": "reorder_layer",
                    "args": {
                        "catalog_id": pick.catalog_id,
                        "action": "front",
                        "display_name": pick.name,
                    },
                }
            )
            return {
                "session_id": sid,
                "reply": f"已将「{pick.name}」移到最上层。",
                "ui_intents": intents,
            }
    if re.search(r"置底|沉到最后|send\s*to\s*back", text, re.I):
        pick = _resolve_layer(text, layers)
        if pick:
            intents.append(
                {
                    "name": "reorder_layer",
                    "args": {
                        "catalog_id": pick.catalog_id,
                        "action": "back",
                        "display_name": pick.name,
                    },
                }
            )
            return {
                "session_id": sid,
                "reply": f"已将「{pick.name}」移到最下层。",
                "ui_intents": intents,
            }

    # Multi-target visibility: 「隐藏 A 并显示 B」「隐藏 A 和 B」
    #
    # 必须先于下面两个互斥分支：旧实现 Hide 分支要求全文不含「显示」，于是
    # 「隐藏 A 并显示 B」整句落进 Show 分支并统一下发 visible=True，
    # 把要隐藏的层显示了；「隐藏 A 和 B」又只做 A 且不报漏。
    multi_vis = _multi_visibility_actions(text, layers)
    if multi_vis is not None:
        acts, missing_targets = multi_vis
        intents.extend(acts)
        lines: list[str] = []
        for act in acts:
            verb = "显示" if (act.get("args") or {}).get("visible") else "隐藏"
            lines.append(f"已{verb}「{(act.get('args') or {}).get('display_name')}」。")
        if missing_targets:
            shown = "、".join(f"「{m}」" for m in missing_targets[:3])
            lines.append(f"另有 {shown} 那一步没有执行——图层库里没定位到这个图层名。")
        if not lines:
            return {
                "session_id": sid,
                "reply": _layer_choices(layers),
                "ui_intents": intents,
            }
        return {"session_id": sid, "reply": "\n".join(lines), "ui_intents": intents}

    # Hide
    if re.search(r"隐藏|关闭显示|hide|关掉", text, re.I) and not re.search(
        r"打开|显示|show", text, re.I
    ):
        pick = _resolve_layer(text, layers, allow_demo_fallback=False)
        if not pick:
            return {
                "session_id": sid,
                "reply": _layer_choices(layers),
                "ui_intents": [],
            }
        intents.append(
            {
                "name": "set_layer_visibility",
                "args": {
                    "catalog_id": pick.catalog_id,
                    "visible": False,
                    "display_name": pick.name,
                },
            }
        )
        return {
            "session_id": sid,
            "reply": f"已隐藏「{pick.name}」。",
            "ui_intents": intents,
        }

    # Show / open
    #
    # 2026-10-27：补「切换到 / 切到 / 换到」——用户说「切换到 VOD 图层」时既不是
    # 打开也不是显示，原来会掉到通用兜底；底图分支加了排除后它能走到这里。
    if re.search(
        r"打开|显示|开启|show|enable|可见|切换到|切到|换到|转到|切换到", text, re.I
    ):
        pick = _resolve_layer(text, layers)
        if not pick and not _page_has_named_candidate(text, layers):
            # 2026-11-09：页面没有这一层时，去图层目录里找一次。开场示例
            # 推荐的「打开 CMFD 降水」不在页面活动层里，原实现永远反问，
            # 示例指令与实际能力不一致；前端支持显示即自动添加，交出去即可。
            # 2026-11-11：页面**有**相关层却因同名歧义没定下来时不许走这里，
            # 否则会加载目录里另一个同名产品，比反问更糟。
            pick = _catalog_pick(text)
        if not pick:
            if layers:
                names = "、".join(
                    f"「{_layer_display_with_identity(item)}」" for item in layers[:5]
                )
                reply = (
                    f"要打开哪个图层？当前有：{names}。\n"
                    "也可以直接说图层名，例如「打开 CMFD 降水」。"
                )
            else:
                reply = (
                    "要打开哪个图层？可以直接说图层名，例如「打开 CMFD 降水」"
                    "「打开高程」；想看全部可用图层可以说「搜索图层 干旱」。"
                )
            return {"session_id": sid, "reply": reply, "ui_intents": []}
        added = pick.catalog_id not in {item["catalog_id"] for item in layers}
        intents.append(
            {
                "name": "set_layer_visibility",
                "args": {
                    "catalog_id": pick.catalog_id,
                    "visible": True,
                    "display_name": pick.name,
                },
            }
        )
        reply = (
            f"已把「{pick.name}」添加到地图并显示。"
            if added
            else f"已显示「{pick.name}」。"
        )
        return {"session_id": sid, "reply": reply, "ui_intents": intents}

    # Opacity
    opacity = _parse_opacity(text)
    if opacity is not None or re.search(r"透明度|opacity", text, re.I):
        pick = _resolve_layer(text, layers, allow_demo_fallback=False)
        if opacity is None:
            return {
                "session_id": sid,
                "reply": "请给出透明度，例如「透明度 50%」。",
                "ui_intents": [],
            }
        if not pick:
            return {
                "session_id": sid,
                "reply": _layer_choices(layers),
                "ui_intents": [],
            }
        pct = int(round(opacity * 100))
        intents.append(
            {
                "name": "set_layer_opacity",
                "args": {
                    "catalog_id": pick.catalog_id,
                    "opacity": opacity,
                    "display_name": pick.name,
                },
            }
        )
        return {
            "session_id": sid,
            "reply": f"已把「{pick.name}」的透明度调为 {pct}%。",
            "ui_intents": intents,
        }

    # Fit / zoom to layer
    if re.search(r"定位|缩放到|飞到|fit|zoom\s*to|居中", text, re.I):
        pick = _resolve_layer(text, layers)
        instance_id = ""
        if pick:
            for layer in layers:
                if layer["catalog_id"] == pick.catalog_id and layer.get("instance_id"):
                    instance_id = layer["instance_id"]
                    break
        if not pick and not instance_id:
            return {
                "session_id": sid,
                "reply": _layer_choices(layers),
                "ui_intents": [],
            }
        args_fit: dict[str, Any] = {}
        if instance_id:
            args_fit["instance_id"] = instance_id
        if pick:
            args_fit["catalog_id"] = pick.catalog_id
            args_fit["display_name"] = pick.name
        intents.append({"name": "fit_layer", "args": args_fit})
        target_name = pick.name if pick else "该图层"
        return {
            "session_id": sid,
            "reply": f"已缩放到「{target_name}」的数据范围。",
            "ui_intents": intents,
        }

    # Workflow hint (no real submit)
    if re.search(r"运行|跑|提交|工作流|workflow|反演", text, re.I):
        return {
            "session_id": sid,
            "reply": (
                "当前是**规则演示模式**，不会自动提交工作流。"
                "请在图层侧栏或分析面板手动运行；"
                "配置大模型后可做到「先出确认卡，再提交」。"
            ),
            "ui_intents": [],
        }

    hint = _visible_layer_names(layers)
    return {
        "session_id": sid,
        "reply": (
            "我可以帮你：查看活动图层、打开/隐藏/移除图层、调透明度、"
            "缩放到图层或中国、定位城市与经纬度、切换底图、切换时间轴。\n\n"
            "试试「有哪些活动图层」「打开 CMFD 降水」「切换为天地图影像」。"
            + (f"\n\n当前图层：{hint}。" if layers else "")
        ),
        "ui_intents": [],
    }
