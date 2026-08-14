"""Analysis tool catalog (InfoPanel GIS tools).

Loads ``app/catalog_seeds/analysis_tools.json`` and filters tools by layer
input kind (raster / vector / point / weather).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from shared.contracts.api_contracts import (
    AnalysisToolDescriptor,
    AnalysisToolListResponse,
    AnalysisToolParamField,
)

logger = logging.getLogger(__name__)

_SEED_PATH = (
    Path(__file__).resolve().parents[1] / "catalog_seeds" / "analysis_tools.json"
)

# Layer capability → tools that require one of these input_kinds
_WEATHER_KINDS = frozenset({"weather", "realtime"})
_RASTER_HINTS = frozenset(
    {"raster", "cog", "imported_raster", "overlay", "science", "omega"}
)
_VECTOR_HINTS = frozenset({"vector", "geojson", "imported_vector", "point"})


def _parse_param(raw: dict[str, Any]) -> AnalysisToolParamField:
    return AnalysisToolParamField(
        key=str(raw.get("key") or ""),
        type=str(raw.get("type") or "string"),
        title=str(raw.get("title") or raw.get("key") or ""),
        description=(
            str(raw["description"]) if raw.get("description") is not None else None
        ),
        default=raw.get("default"),
        min=raw.get("min") if isinstance(raw.get("min"), (int, float)) else None,
        max=raw.get("max") if isinstance(raw.get("max"), (int, float)) else None,
        unit=str(raw["unit"]) if raw.get("unit") is not None else None,
        options=[str(o) for o in raw.get("options") or []]
        if isinstance(raw.get("options"), list)
        else None,
    )


def _parse_tool(raw: dict[str, Any]) -> AnalysisToolDescriptor:
    params_raw = raw.get("param_schema") or []
    params = [
        _parse_param(p) for p in params_raw if isinstance(p, dict) and p.get("key")
    ]
    return AnalysisToolDescriptor(
        tool_id=str(raw.get("tool_id") or ""),
        title=str(raw.get("title") or ""),
        description=str(raw.get("description") or ""),
        category=str(raw.get("category") or "analysis"),
        input_kinds=[str(k) for k in (raw.get("input_kinds") or [])],
        param_schema=params,
        workflow_template_id=str(raw.get("workflow_template_id") or ""),
        outputs=[str(o) for o in (raw.get("outputs") or [])],
        resource_profile=str(raw.get("resource_profile") or "standard"),
        concurrency_key=str(raw.get("concurrency_key") or "layer_tool"),
    )


@lru_cache(maxsize=1)
def load_analysis_tools() -> list[AnalysisToolDescriptor]:
    if not _SEED_PATH.is_file():
        logger.warning("analysis_tools seed missing: %s", _SEED_PATH)
        return []
    try:
        data = json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to load analysis_tools.json")
        return []
    if not isinstance(data, list):
        return []
    tools = [_parse_tool(item) for item in data if isinstance(item, dict)]
    return [t for t in tools if t.tool_id and t.workflow_template_id]


def get_tool(tool_id: str) -> AnalysisToolDescriptor | None:
    want = str(tool_id or "").strip()
    for tool in load_analysis_tools():
        if tool.tool_id == want:
            return tool
    return None


def resolve_layer_input_kind(
    *,
    layer_id: str | None,
    source_type: str | None = None,
    overlay_layer_id: str | None = None,
    has_vector: bool = False,
    has_raster: bool = False,
    is_weather: bool = False,
    is_point_only: bool = False,
) -> str:
    """Best-effort layer kind for tool filtering."""
    if is_weather:
        return "weather"
    if is_point_only:
        return "point"
    if has_vector and not has_raster:
        return "vector"
    if has_raster or overlay_layer_id:
        return "raster"
    st = str(source_type or "").lower()
    if st in _WEATHER_KINDS or "weather" in st:
        return "weather"
    if st in _VECTOR_HINTS or "vector" in st:
        return "vector"
    if st in _RASTER_HINTS or "raster" in st or "cog" in st:
        return "raster"
    lid = str(layer_id or "").lower()
    if lid.startswith("imported-") or "overlay" in lid:
        return "raster"
    return "any"


def list_tools_for_layer(
    *,
    layer_id: str | None = None,
    source_type: str | None = None,
    overlay_layer_id: str | None = None,
    has_vector: bool = False,
    has_raster: bool = False,
    is_weather: bool = False,
    is_point_only: bool = False,
) -> AnalysisToolListResponse:
    kind = resolve_layer_input_kind(
        layer_id=layer_id,
        source_type=source_type,
        overlay_layer_id=overlay_layer_id,
        has_vector=has_vector,
        has_raster=has_raster,
        is_weather=is_weather,
        is_point_only=is_point_only,
    )
    items: list[AnalysisToolDescriptor] = []
    for tool in load_analysis_tools():
        allowed = {k.lower() for k in tool.input_kinds} or {"any"}
        if kind == "weather":
            # Phase-1: disable most GIS on weather tiles
            enabled = "weather" in allowed or "point" in allowed
            reason = None if enabled else "天气瓦片层请先导出/导入为静态栅格后再分析"
        elif kind == "any":
            enabled = True
            reason = None
        elif "any" in allowed or kind in allowed:
            enabled = True
            reason = None
        elif kind == "point" and "vector" in allowed:
            enabled = True
            reason = None
        else:
            enabled = False
            reason = f"当前图层类型「{kind}」不支持该工具（需要 {sorted(allowed)}）"
        items.append(
            tool.model_copy(
                update={
                    "enabled": enabled,
                    "disabled_reason": reason,
                }
            )
        )
    return AnalysisToolListResponse(
        layer_id=layer_id,
        layer_kind=kind,
        items=items,
    )
