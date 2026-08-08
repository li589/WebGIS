"""从文件名 / 用户输入解析导入栅格的时间标签。

单文件导入仍按 static overlay 落盘（preview.png），但可写入 time_list /
native_step 供前端时间轴跟随。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

_YMD = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)")
_YMD_RANGE = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})[_-](\d{4})(\d{2})(\d{2})(?!\d)")
_YMD_DOT = re.compile(r"(?<!\d)(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})(?!\d)")
_YMD_DASH_RANGE = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})[_~-](\d{4})-(\d{2})-(\d{2})(?!\d)"
)


def _valid_ymd(y: int, m: int, d: int) -> bool:
    try:
        date(y, m, d)
        return True
    except ValueError:
        return False


def _fmt(y: int, m: int, d: int) -> str:
    return f"{y:04d}{m:02d}{d:02d}"


def _parse_ymd_token(raw: str) -> str | None:
    s = (raw or "").strip().replace("-", "").replace(".", "")
    if not re.fullmatch(r"\d{8}", s):
        return None
    y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    if not _valid_ymd(y, m, d):
        return None
    return _fmt(y, m, d)


def _native_step_for_range(start: str, end: str) -> str:
    d0 = datetime.strptime(start, "%Y%m%d").date()
    d1 = datetime.strptime(end, "%Y%m%d").date()
    days = (d1 - d0).days + 1
    if days <= 1:
        return "1d"
    if 6 <= days <= 10:
        return "8d"
    if 28 <= days <= 31:
        return "1m"
    return f"{days}d"


def guess_time_label_from_filename(name: str) -> dict[str, Any] | None:
    """从文件名猜时间点或时间段。

    Returns:
        ``{kind, time_list, default_time, native_step, label}`` 或 ``None``。
    """
    stem = str(name or "")
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]

    m = _YMD_RANGE.search(stem) or _YMD_DASH_RANGE.search(stem)
    if m:
        y1, mo1, d1, y2, mo2, d2 = (int(x) for x in m.groups())
        if _valid_ymd(y1, mo1, d1) and _valid_ymd(y2, mo2, d2):
            a, b = _fmt(y1, mo1, d1), _fmt(y2, mo2, d2)
            if a > b:
                a, b = b, a
            label = f"{a}_{b}"
            return {
                "kind": "range",
                "time_list": [label],
                "default_time": label,
                "native_step": _native_step_for_range(a, b),
                "label": label,
            }

    m = _YMD.search(stem)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        if _valid_ymd(y, mo, d):
            label = _fmt(y, mo, d)
            return {
                "kind": "point",
                "time_list": [label],
                "default_time": label,
                "native_step": "1d",
                "label": label,
            }

    m = _YMD_DOT.search(stem)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        if _valid_ymd(y, mo, d):
            label = _fmt(y, mo, d)
            return {
                "kind": "point",
                "time_list": [label],
                "default_time": label,
                "native_step": "1d",
                "label": label,
            }

    return None


def build_temporal_meta(
    *,
    temporal_mode: str = "auto",
    time_label: str | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
    native_step: str | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    """根据模式与用户输入生成写入 bounds/meta 的时间字段。

    单文件导入 overlay ``category`` 始终为 ``static``（预览文件布局），
    但 ``time_list`` 非空时前端可挂时间轴。
    """
    mode = (temporal_mode or "auto").strip().lower()
    if mode not in {"auto", "static", "point", "range"}:
        raise ValueError("temporal_mode 须为 auto | static | point | range")

    empty: dict[str, Any] = {
        "category": "static",
        "time_list": [],
        "default_time": None,
        "current_time": None,
        "native_step": None,
        "follow_policy": None,
        "temporal_kind": "static",
        "temporal_source": "none",
        "temporal_mode": mode,
    }

    if mode == "static":
        return empty

    if mode == "point":
        label = _parse_ymd_token(time_label or time_start or "")
        if not label:
            raise ValueError("时间点模式需要有效日期（YYYYMMDD 或 YYYY-MM-DD）")
        step = (native_step or "1d").strip() or "1d"
        return {
            "category": "static",
            "time_list": [label],
            "default_time": label,
            "current_time": label,
            "native_step": step,
            "follow_policy": "containing",
            "temporal_kind": "point",
            "temporal_source": "manual",
            "temporal_mode": mode,
        }

    if mode == "range":
        a = _parse_ymd_token(time_start or "")
        b = _parse_ymd_token(time_end or "")
        if time_label and not (a and b):
            raw = (time_label or "").strip()
            m = re.fullmatch(r"(\d{8})[_-](\d{8})", raw)
            if m:
                a, b = m.group(1), m.group(2)
            elif "_" in raw:
                parts = raw.split("_", 1)
                a = _parse_ymd_token(parts[0])
                b = _parse_ymd_token(parts[1]) if len(parts) > 1 else None
        if not a or not b:
            raise ValueError("时间段模式需要起止日期（YYYYMMDD）")
        if a > b:
            a, b = b, a
        label = f"{a}_{b}"
        step = (native_step or _native_step_for_range(a, b)).strip()
        return {
            "category": "static",
            "time_list": [label],
            "default_time": label,
            "current_time": label,
            "native_step": step,
            "follow_policy": "containing",
            "temporal_kind": "range",
            "temporal_source": "manual",
            "temporal_mode": mode,
        }

    guessed = guess_time_label_from_filename(source_name or "")
    if not guessed:
        return {**empty, "temporal_mode": "auto"}
    step = (native_step or guessed["native_step"] or "1d").strip()
    return {
        "category": "static",
        "time_list": list(guessed["time_list"]),
        "default_time": guessed["default_time"],
        "current_time": guessed["default_time"],
        "native_step": step,
        "follow_policy": "containing",
        "temporal_kind": guessed["kind"],
        "temporal_source": "auto",
        "temporal_mode": "auto",
    }
