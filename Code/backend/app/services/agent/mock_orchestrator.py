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

    # Fit / zoom
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
            "我可以帮你：查看活动图层、打开/隐藏图层、调透明度、缩放到图层。"
            "试试「打开 CMFD 降水」或「有哪些活动图层」。"
        ),
        "ui_intents": [],
    }
