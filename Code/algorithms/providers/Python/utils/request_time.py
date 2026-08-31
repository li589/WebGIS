"""Resolve JobRequest time bounds with clear errors when time_range is missing."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse_date_param(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_bounds_from_time_range(
    time_range: Any,
) -> tuple[datetime | None, datetime | None]:
    """Accept algorithm TimeRange (.start/.end), API TimeRange (.start_at/.end_at), or dict."""
    if time_range is None:
        return None, None

    start_raw: object = None
    end_raw: object = None
    if isinstance(time_range, dict):
        start_raw = (
            time_range.get("start")
            or time_range.get("start_at")
            or time_range.get("start_date")
        )
        end_raw = (
            time_range.get("end")
            or time_range.get("end_at")
            or time_range.get("end_date")
        )
    else:
        start_raw = getattr(time_range, "start", None)
        if start_raw is None:
            start_raw = getattr(time_range, "start_at", None)
        end_raw = getattr(time_range, "end", None)
        if end_raw is None:
            end_raw = getattr(time_range, "end_at", None)

    return _parse_date_param(start_raw), _parse_date_param(end_raw)


def resolve_time_bounds(
    *,
    time_range: Any | None,
    algorithm_params: dict[str, object] | None = None,
    module_label: str = "module",
) -> tuple[datetime, datetime]:
    """Return (start, end) from JobRequest.time_range or algorithm_params dates.

    Raises ``ValueError`` with an actionable message when neither is available.
    Avoids the opaque ``NoneType has no attribute 'start'`` crash path.

    Accepts both provider ``TimeRange(start, end)`` and shared-contract
    ``TimeRange(start_at, end_at)`` / dict forms so layer-panel submits that
    only carry top-level time_range still backfill fy_download.start_date.
    """
    tr_start, tr_end = _extract_bounds_from_time_range(time_range)
    if tr_start is not None and tr_end is not None:
        return tr_start, tr_end

    params = algorithm_params or {}
    param_start = _parse_date_param(params.get("start_date") or params.get("start_at"))
    param_end = _parse_date_param(params.get("end_date") or params.get("end_at"))
    # 勿用空 params 覆盖 time_range 已解析出的半边（例如仅有 start_at）
    start = tr_start or param_start
    end = tr_end or param_end
    if start is not None and end is not None:
        return start, end
    # 仅有 start：按日粒度补 end=start（单日在线拉取）
    if start is not None and end is None:
        return start, start

    raise ValueError(
        f"{module_label} 需要时间范围（time_range），但本次请求未提供。"
        "请在主界面时间轴选择日期后重跑，或在工作流中配置 data/time_range 节点。"
    )
