"""Regression: resolve_time_bounds must not raise AttributeError on None time_range."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

PROVIDER_ROOT = (
    Path(__file__).resolve().parents[2] / "Code" / "algorithms" / "providers" / "Python"
)
sys.path.insert(0, str(PROVIDER_ROOT))

import contracts.job  # noqa: F401, E402  # break circular import

from utils.request_time import resolve_time_bounds  # noqa: E402


def test_resolve_time_bounds_none_raises_clear_value_error() -> None:
    with pytest.raises(ValueError, match="需要时间范围"):
        resolve_time_bounds(
            time_range=None,
            algorithm_params={},
            module_label="fy_daily",
        )


def test_resolve_time_bounds_from_algorithm_params_dates() -> None:
    start, end = resolve_time_bounds(
        time_range=None,
        algorithm_params={"start_date": "20251201", "end_date": "20251208"},
        module_label="fy_daily",
    )
    assert start.strftime("%Y%m%d") == "20251201"
    assert end.strftime("%Y%m%d") == "20251208"


def test_resolve_time_bounds_prefers_time_range_object() -> None:
    class _TR:
        start = datetime(2025, 12, 1)
        end = datetime(2025, 12, 8)

    start, end = resolve_time_bounds(
        time_range=_TR(),
        algorithm_params={"start_date": "20200101", "end_date": "20200102"},
        module_label="fy_daily",
    )
    assert start.year == 2025
    assert end.day == 8


def test_resolve_time_bounds_from_start_at_end_at_attrs() -> None:
    """API/shared TimeRange uses start_at/end_at; must backfill fy_download."""

    class _ApiTR:
        start_at = datetime(2025, 12, 15, 0, 0, 0)
        end_at = datetime(2025, 12, 15, 23, 59, 59)

    start, end = resolve_time_bounds(
        time_range=_ApiTR(),
        algorithm_params={},
        module_label="fy_download",
    )
    assert start.strftime("%Y%m%d") == "20251215"
    assert end.strftime("%Y%m%d") == "20251215"


def test_resolve_time_bounds_from_dict_start_at() -> None:
    start, end = resolve_time_bounds(
        time_range={"start_at": "2025-12-15T00:00:00", "end_at": "2025-12-16T00:00:00"},
        algorithm_params={},
        module_label="fy_download",
    )
    assert start.day == 15
    assert end.day == 16


def test_resolve_time_bounds_start_only_from_time_range_dict() -> None:
    """仅有 start_at 时不得被空 algorithm_params 覆盖掉。"""
    start, end = resolve_time_bounds(
        time_range={"start_at": "2025-12-15T00:00:00"},
        algorithm_params={},
        module_label="fy_download",
    )
    assert start.strftime("%Y%m%d") == "20251215"
    assert end.strftime("%Y%m%d") == "20251215"
