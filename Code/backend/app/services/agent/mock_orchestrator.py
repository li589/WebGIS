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


def _normalize_layers(client_context: dict[str, Any] | None) -> list[dict[str, str]]:
    if not client_context:
        return []
    raw = client_context.get("active_layers")
    if isinstance(raw, list):
        out: list[dict[str, str]] = []
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
            out.append(
                {
                    "catalog_id": cid,
                    "instance_id": str(item.get("instance_id") or ""),
                    "name": name,
                }
            )
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


def _display(layer: dict[str, str]) -> str:
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


def _resolve_layer(
    message: str,
    layers: list[dict[str, str]],
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
    best: dict[str, dict[str, str]] = {}
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


def _layer_choices(layers: list[dict[str, str]]) -> str:
    """「要操作哪个图层？当前有 A、B、C」的可选项文案。"""
    if not layers:
        return "当前地图上没有活动图层，请先在左侧图层面板添加。"
    names = "、".join(f"「{_display(layer)}」" for layer in layers[:5])
    return f"请指明是哪个图层。当前有：{names}。"


def _visible_layer_names(layers: list[dict[str, str]]) -> str:
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


def _build_timeline_reply(
    args_tl: dict[str, Any],
    client_context: dict[str, Any] | None,
) -> tuple[str, bool]:
    """时间轴切换的回复 ``(文案, 是否允许下发意图)``。

    **先校验，再回答**：日期超出已知可用范围时明确说「没有切换」，
    而不是旧版那句空口的「正在更新时间轴」——用户会以为切成功了。
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
            span = f"{_readable_date(rng['start'])} 至 {_readable_date(rng['end'])}"
            frames = rng.get("frames")
            extra = (
                f"，共 {frames} 帧" if isinstance(frames, int) and frames > 0 else ""
            )
            return (
                f"{wanted} 不在当前图层的可用时间内，**没有切换**。\n\n"
                f"当前可用范围：{span}{extra}。\n"
                "要切到范围内的某一天，直接说日期即可。"
            ), False
    suffix = f"（{hour_txt}）" if hour_txt else ""
    return (
        f"已把时间轴切到 {wanted}{suffix}。\n"
        "若该图层这一天没有数据，会自动对齐到最近的可用帧，"
        "实际生效日期以气泡下方的执行结果为准。"
    ), True


def mock_chat(
    message: str,
    *,
    session_id: str | None = None,
    client_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return reply + optional ui_intents from keyword rules."""
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

    # List active layers
    if re.search(r"哪些.*(图层|层)|活动图层|当前图层|list.*layer", text, re.I):
        if not layers:
            reply = (
                "当前地图上还没有图层。可以在左侧「图层目录」里添加，"
                "或直接说「打开 CMFD 降水」让我帮你打开一个示例图层。"
            )
        else:
            lines = [f"- {_display(layer)}" for layer in layers]
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
    if re.search(r"底图|basemap|切换.*(图|影像|街道)|换成", text, re.I):
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
    if re.search(r"打开|显示|开启|show|enable|可见", text, re.I):
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
