"""Mock agent orchestrator — keyword rules + UI intents (no real LLM).

``reply`` 一律只写人话：用图层的中文显示名，**不出现任何内部 id**
（``catalog_id`` / ``instance_id`` / ``overlay-xxx``）。id 只随 ``ui_intents``
的 ``args`` 传给前端执行，以及在过程面板里留痕。

用户 2026-10-21 反馈：问「有哪些图层」回的是「风云卫星反演（id：123456677）」，
看不懂。此前本文件有 9 处把 id 拼进正文，已全部改为中文名。
"""

from __future__ import annotations

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

_STAT_VERB = re.compile(r"平均|均值|统计|像元数|最大|最小|mean|average", re.I)
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
        return LayerPick(only["catalog_id"], _display(only))
    if len(best) > 1:
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
        return LayerPick(only["catalog_id"], _display(only))
    if len(alias_hits) > 1:
        # 「土壤水分」同时命中风云与 SMAP 两个图层，且用户没点名来源 ⇒ 不猜
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
    names = "、".join(f"「{_display(layer)}」" for layer in layers[:5])
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
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1900 <= year <= 2200 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


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
    """
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
    (re.compile(r"平均(?!值)|月均|季均|气候态|多年", re.I), "平均"),
)


def _has_layer_hints(text: str) -> bool:
    """这句话里有没有「来源 / 产品形态」线索（用来判断值不值得收窄候选）。"""
    return any(p.search(text) for p, _ in _SOURCE_HINTS) or any(
        p.search(text) for p, _ in _FORM_HINTS
    )


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
            if narrowed:
                pool = narrowed
            break
    for pattern, marker in _FORM_HINTS:
        if pattern.search(text):
            narrowed = [la for la in pool if marker in _display(la)]
            if narrowed:
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

    picked = _resolve_layer(text, layers, allow_demo_fallback=False)
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
            candidate = next(
                (la for la in layers if la.get("catalog_id") == prior_id), None
            )
            if candidate is not None:
                prior_var = prior.get("variable") or dialogue_state.variable_from_name(
                    _display(candidate)
                )
                if variable is None or variable == prior_var:
                    target = candidate
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

    region = _parse_region_arg(text)
    region_from = "message" if region else ""
    if not region and follow_up and prior.get("region"):
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
        return {
            "session_id": sid,
            "reply": entities.get("why") or "请先指定一个图层。",
            "ui_intents": intents,
            "topic_state": {},
        }

    # ★ 通用防线：与选层逻辑解耦。将来谁再改选层、正则或兜底顺序，只要「用户
    # 说的变量」和「实际挑中的层变量」对不上，就在这里被拦住——绝不拿另一个
    # 变量算完、再印一个看着很正式的标题（2026-11-06：问土壤水分、答等效散射 ω）。
    said_var = str(entities.get("variable") or "")
    target_var = dialogue_state.variable_from_name(_display(target))
    if said_var and target_var and said_var != target_var:
        return {
            "session_id": sid,
            "reply": (
                f"你说的是「{dialogue_state.VARIABLE_LABELS.get(said_var, said_var)}」，"
                f"但按当前页面能统计的是「{_display(target)}」——两个不是同一个变量，"
                "我不拿它顶替。请先确认要统计哪一层（也可以直接说完整图层名）。"
            ),
            "ui_intents": intents,
            "topic_state": {},
        }

    from app.services.agent.server_tools_runtime import _get_layer_statistics

    day = entities.get("date")
    if not day and isinstance(client_context, dict):
        timeline = client_context.get("timeline")
        if isinstance(timeline, dict):
            raw_date = str(timeline.get("date") or "").strip()
            if raw_date:
                day = raw_date
    # 「广州市」「四川省」这类行政区名必须进 region，否则算出来的是全球均值，
    # 用户会当成该市的值（外部测试 2026-11-04 就是这么错答的）。
    region = entities.get("region")
    stat_args: dict[str, Any] = {
        # 2026-11-06：必须用页面那一层实际挂着的产物 id（imported-*）。
        # 目录层 id（method-*）在盘上没有同名目录，拿它统计只会得到
        # 「不是本地运行时产物」，兜底路径就会退化成一句「本次未取到数值」——
        # 而模型正常调工具时是同一条链路、同一天，本来能算出数。
        "catalog_id": str(target.get("overlay_layer_id") or target["catalog_id"]),
        "time": day or None,
    }
    if region:
        stat_args["region"] = region
    res = _get_layer_statistics(stat_args, cred=None, client_context=client_context)
    topic_state = _entities_state_patch(entities)
    carry_note = _carry_note(entities)

    name = _display(target)
    scope_prefix = f"按「{region}」行政边界" if region else "整层"
    if not res.get("ok"):
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
                    f"（整片 NoData，0/{res.get('total_pixels')}），因此无法给出均值。"
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
        f"- 有效像元：{res.get('valid_pixels')} / {res.get('total_pixels')}"
        + (f"（占 {float(pct) * 100:.1f}%）" if pct is not None else ""),
        f"- 实际数据时间块：{block}",
    ]
    requested = str(res.get("requested_time") or "").strip()
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
        if len(sel) == 1:
            reply = f"当前选中的是「{_display(sel[0])}」。"
        elif not sel:
            vis = [la for la in layers if la.get("visible")]
            if vis:
                names = "、".join(f"「{_display(la)}」" for la in vis[:5])
                reply = f"当前没有选中任何图层，正在显示的图层是：{names}。"
            elif layers:
                names = "、".join(f"「{_display(la)}」" for la in layers[:5])
                reply = f"当前没有选中任何图层，已加载的图层是：{names}。"
            else:
                reply = "当前地图上没有图层，也没有选中项。"
        else:
            names = "、".join(f"「{_display(la)}」" for la in sel[:5])
            reply = f"当前选中了 {len(sel)} 个图层：{names}。"
        return {"session_id": sid, "reply": reply, "ui_intents": intents}

    # List active layers
    if re.search(r"哪些.*(图层|层)|活动图层|当前图层|list.*layer", text, re.I):
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
            reply, changeable = _build_timeline_reply(args_tl, client_context)
            # 超出可用范围 ⇒ 不生成意图，避免「前端换了、正文说没数据」自相矛盾
            if changeable:
                intents.append({"name": "set_timeline", "args": args_tl})
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
        if not pick:
            if layers:
                names = "、".join(f"「{_display(item)}」" for item in layers[:5])
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
