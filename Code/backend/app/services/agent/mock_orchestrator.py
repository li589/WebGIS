"""Mock agent orchestrator — keyword rules + UI intents (no real LLM)."""

from __future__ import annotations

import re
import uuid
from typing import Any


# Demo catalog ids used when client context has no match
_DEMO_PRECIP = "cmfd-precip-cn"
_DEMO_FALLBACKS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"cmfd|降水|precip|rain", re.I), _DEMO_PRECIP),
    (re.compile(r"dem|etopo|高程|地形", re.I), "dem-etopo"),
    (re.compile(r"clcd|土地|土地利用|land\s*cover", re.I), "clcd-cn"),
    (re.compile(r"co2|二氧化碳", re.I), "co2-cn"),
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
            out.append(
                {
                    "catalog_id": cid,
                    "instance_id": str(item.get("instance_id") or ""),
                    "name": str(item.get("name") or cid),
                }
            )
        return out
    ids = client_context.get("active_catalog_ids")
    if isinstance(ids, list):
        return [
            {"catalog_id": str(x).strip(), "instance_id": "", "name": str(x).strip()}
            for x in ids
            if str(x).strip()
        ]
    return []


def _match_catalog(message: str, layers: list[dict[str, str]]) -> str | None:
    lower = message.lower()
    for layer in layers:
        for key in (layer["catalog_id"], layer["name"]):
            if key and key.lower() in lower:
                return layer["catalog_id"]
    for pattern, catalog_id in _DEMO_FALLBACKS:
        if pattern.search(message):
            return catalog_id
    if layers:
        return layers[0]["catalog_id"]
    return None


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
    return lng, lat


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
                "当前没有活动图层。你可以先在左侧图层目录添加图层，"
                "或说「打开 CMFD 降水」让我帮你打开演示图层。"
            )
        else:
            lines = [
                f"- {L['name']} (`{L['catalog_id']}`)"
                + (f" · {L['instance_id'][:8]}…" if L.get("instance_id") else "")
                for L in layers
            ]
            reply = "当前活动图层：\n" + "\n".join(lines)
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
            "reply": "正在缩放到中国全境范围。",
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
                    "reply": f"正在切换底图为{label}（`{source_id}`）。",
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
            "reply": f"正在定位到坐标 ({lng:.4f}, {lat:.4f})。",
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
                    "reply": f"正在定位到{label}（{lng:.4f}, {lat:.4f}）。",
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
            "reply": "已开始时间轴播放。",
            "ui_intents": intents,
        }

    # Set timeline clock
    hour_m = re.search(r"(?:设为|调到|跳到|时间)\s*(\d{1,2})\s*[点时:：]", text, re.I)
    date_m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if hour_m or (date_m and re.search(r"时间|日期|时刻|timeline", text, re.I)):
        args_tl: dict[str, Any] = {}
        if hour_m:
            h = int(hour_m.group(1))
            if 0 <= h <= 23:
                args_tl["hour"] = h
        if date_m:
            args_tl["date"] = date_m.group(1)
        if args_tl:
            intents.append({"name": "set_timeline", "args": args_tl})
            return {
                "session_id": sid,
                "reply": "正在更新时间轴。",
                "ui_intents": intents,
            }

    # Remove layer
    if re.search(r"移除图层|删除图层|去掉图层|remove\s*layer", text, re.I):
        catalog_id = _match_catalog(text, layers)
        if not catalog_id:
            return {
                "session_id": sid,
                "reply": "请指定要移除的图层名称。",
                "ui_intents": [],
            }
        intents.append({"name": "remove_layer", "args": {"catalog_id": catalog_id}})
        return {
            "session_id": sid,
            "reply": f"正在移除图层 `{catalog_id}`。",
            "ui_intents": intents,
        }

    # Reorder
    if re.search(r"置顶|提到最前|bring\s*to\s*front", text, re.I):
        catalog_id = _match_catalog(text, layers)
        if catalog_id:
            intents.append(
                {
                    "name": "reorder_layer",
                    "args": {"catalog_id": catalog_id, "action": "front"},
                }
            )
            return {
                "session_id": sid,
                "reply": f"正在将 `{catalog_id}` 置顶。",
                "ui_intents": intents,
            }
    if re.search(r"置底|沉到最后|send\s*to\s*back", text, re.I):
        catalog_id = _match_catalog(text, layers)
        if catalog_id:
            intents.append(
                {
                    "name": "reorder_layer",
                    "args": {"catalog_id": catalog_id, "action": "back"},
                }
            )
            return {
                "session_id": sid,
                "reply": f"正在将 `{catalog_id}` 置底。",
                "ui_intents": intents,
            }

    # Hide
    if re.search(r"隐藏|关闭显示|hide|关掉", text, re.I) and not re.search(
        r"打开|显示|show", text, re.I
    ):
        catalog_id = _match_catalog(text, layers)
        if not catalog_id:
            return {
                "session_id": sid,
                "reply": "请指定要隐藏的图层名称或 catalog_id。",
                "ui_intents": [],
            }
        intents.append(
            {
                "name": "set_layer_visibility",
                "args": {"catalog_id": catalog_id, "visible": False},
            }
        )
        return {
            "session_id": sid,
            "reply": f"已隐藏图层 `{catalog_id}`。",
            "ui_intents": intents,
        }

    # Show / open
    if re.search(r"打开|显示|开启|show|enable|可见", text, re.I):
        catalog_id = _match_catalog(text, layers) or _match_catalog(text, [])
        if not catalog_id:
            catalog_id = _DEMO_PRECIP
        intents.append(
            {
                "name": "set_layer_visibility",
                "args": {"catalog_id": catalog_id, "visible": True},
            }
        )
        return {
            "session_id": sid,
            "reply": f"已为你打开图层 `{catalog_id}`。",
            "ui_intents": intents,
        }

    # Opacity
    opacity = _parse_opacity(text)
    if opacity is not None or re.search(r"透明度|opacity", text, re.I):
        catalog_id = _match_catalog(text, layers)
        if opacity is None:
            return {
                "session_id": sid,
                "reply": "请给出透明度，例如「透明度 50%」。",
                "ui_intents": [],
            }
        if not catalog_id:
            return {
                "session_id": sid,
                "reply": "请指定图层名称，例如「CMFD 降水透明度 50%」。",
                "ui_intents": [],
            }
        intents.append(
            {
                "name": "set_layer_opacity",
                "args": {"catalog_id": catalog_id, "opacity": opacity},
            }
        )
        return {
            "session_id": sid,
            "reply": f"已将 `{catalog_id}` 透明度设为 {int(round(opacity * 100))}%。",
            "ui_intents": intents,
        }

    # Fit / zoom to layer
    if re.search(r"定位|缩放到|飞到|fit|zoom\s*to|居中", text, re.I):
        catalog_id = _match_catalog(text, layers)
        instance_id = ""
        if catalog_id:
            for L in layers:
                if L["catalog_id"] == catalog_id and L.get("instance_id"):
                    instance_id = L["instance_id"]
                    break
        if not catalog_id and not instance_id:
            return {
                "session_id": sid,
                "reply": "请指定要定位的图层，或先添加活动图层。",
                "ui_intents": [],
            }
        args: dict[str, Any] = {}
        if instance_id:
            args["instance_id"] = instance_id
        if catalog_id:
            args["catalog_id"] = catalog_id
        intents.append({"name": "fit_layer", "args": args})
        return {
            "session_id": sid,
            "reply": f"正在缩放到图层 `{catalog_id or instance_id}`。",
            "ui_intents": intents,
        }

    # Workflow hint (no real submit)
    if re.search(r"运行|跑|提交|工作流|workflow|反演", text, re.I):
        return {
            "session_id": sid,
            "reply": (
                "当前为演示版助手，暂不自动提交工作流。"
                "请在图层侧栏或分析面板手动运行；后续版本会支持确认后提交。"
            ),
            "ui_intents": [],
        }

    return {
        "session_id": sid,
        "reply": (
            "我可以帮你：查看活动图层、打开/隐藏/移除图层、调透明度与色带、缩放到图层、"
            "缩放到中国、定位城市/坐标、切换底图、调整时间轴。"
            "试试「打开 CMFD 降水」「缩放到中国」或「切换为天地图影像」。"
        ),
        "ui_intents": [],
    }
