"""omega_sf_fenkuai 时间窗对齐门禁：无 allow_align 不改窗。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules.omega_sf_fenkuai import _align_window_to_available


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(logger_adapter=None)


def test_align_window_raises_coverage_gap_when_not_allowed(tmp_path: Path) -> None:
    # 本地只有 2025-11，请求 2026-08 → 零交集；未放宽则 fail-closed 抛 coverage_gap
    for day in range(1, 9):
        (tmp_path / f"202511{day:02d}.mat").write_bytes(b"x")

    params = {"start_date": "20260808", "end_date": "20260815"}
    with patch(
        "algorithms.omega_sf._scan_folder_dates",
        return_value=[datetime(2025, 11, d) for d in range(1, 9)],
    ):
        try:
            _align_window_to_available(
                params, str(tmp_path), _ctx(), allow_align=False
            )
            raise AssertionError("expected ValueError coverage_gap")
        except ValueError as exc:
            msg = str(exc)
            assert "error_code=coverage_gap" in msg
            assert "零交集" in msg


def test_align_window_shifts_when_allowed(tmp_path: Path) -> None:
    params = {"start_date": "20260808", "end_date": "20260815"}
    available = [datetime(2025, 11, d) for d in range(1, 16)]
    with patch("algorithms.omega_sf._scan_folder_dates", return_value=available):
        out = _align_window_to_available(
            params, str(tmp_path), _ctx(), allow_align=True
        )
    assert out["end_date"] == "20251115"
    assert out["start_date"] == "20251108"


def test_align_window_keeps_when_intersection(tmp_path: Path) -> None:
    params = {"start_date": "20251101", "end_date": "20251108"}
    available = [datetime(2025, 11, d) for d in range(1, 16)]
    with patch("algorithms.omega_sf._scan_folder_dates", return_value=available):
        out = _align_window_to_available(
            params, str(tmp_path), _ctx(), allow_align=True
        )
    assert out["start_date"] == "20251101"
    assert out["end_date"] == "20251108"
