"""Overlay registry path-traversal regression tests (G1-01).

Covers time-list whitelist validation and ``..``-segment defense-in-depth for
``resolve_png`` / ``resolve_bounds`` / ``resolve_source_path`` (used by
``/overlay-preview``, ``/overlay-bounds``, ``/overlay-tiles``, ``/overlay-value``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.overlay_registry import OverlaySpec


def _time_series_spec(
    tmp_path: Path,
    *,
    time_list: list[str] | None = None,
    source_pattern: str | None = None,
) -> OverlaySpec:
    overlay_dir = tmp_path / "overlay"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    return OverlaySpec(
        layer_id="test-ts",
        overlay_dir=overlay_dir,
        category="time-series",
        time_pattern="preview_{time}.png",
        bounds_pattern="bounds_{time}.json",
        time_list=time_list if time_list is not None else ["20230101", "20230102"],
        default_time="20230101",
        source_pattern=source_pattern
        or str(overlay_dir / "src_{time}.mat"),
        source_variable="v",
        source_reader="mat",
    )


def _expect_404(exc: HTTPException) -> None:
    assert exc.status_code == 404


def test_resolve_bounds_rejects_traversal(tmp_path: Path) -> None:
    spec = _time_series_spec(tmp_path)
    with pytest.raises(HTTPException) as ei:
        spec.resolve_bounds("../../etc/passwd")
    _expect_404(ei.value)


def test_resolve_source_path_rejects_traversal(tmp_path: Path) -> None:
    spec = _time_series_spec(tmp_path)
    with pytest.raises(HTTPException) as ei:
        spec.resolve_source_path("../../etc/passwd")
    _expect_404(ei.value)


def test_resolve_source_path_rejects_glob_traversal(tmp_path: Path) -> None:
    # Glob branch: pattern contains a wildcard after the traversal segment.
    spec = _time_series_spec(
        tmp_path, source_pattern=str(tmp_path / "overlay" / "src_{time}_*.mat")
    )
    with pytest.raises(HTTPException) as ei:
        spec.resolve_source_path("../../etc/passwd")
    _expect_404(ei.value)


def test_resolve_png_rejects_traversal(tmp_path: Path) -> None:
    spec = _time_series_spec(tmp_path)
    with pytest.raises(HTTPException) as ei:
        spec.resolve_png("../../etc/passwd")
    _expect_404(ei.value)


def test_resolve_bounds_rejects_unknown_time(tmp_path: Path) -> None:
    spec = _time_series_spec(tmp_path)
    with pytest.raises(HTTPException) as ei:
        spec.resolve_bounds("19990101")
    _expect_404(ei.value)


def test_resolve_source_path_rejects_unknown_time(tmp_path: Path) -> None:
    spec = _time_series_spec(tmp_path)
    with pytest.raises(HTTPException) as ei:
        spec.resolve_source_path("19990101")
    _expect_404(ei.value)


def test_resolve_requires_time_for_time_series(tmp_path: Path) -> None:
    spec = _time_series_spec(tmp_path, time_list=["20230101"])
    # default_time set → resolves; but a spec without default and without time → 400.
    spec_no_default = _time_series_spec(tmp_path, time_list=["20230101"])
    spec_no_default.default_time = None
    with pytest.raises(HTTPException) as ei:
        spec_no_default.resolve_bounds(None)
    assert ei.value.status_code == 400
    assert spec.resolve_bounds(None).name == "bounds_20230101.json"


def test_legit_time_resolves(tmp_path: Path) -> None:
    overlay_dir = tmp_path / "overlay"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    (overlay_dir / "src_20230101.mat").write_bytes(b"fake")
    (overlay_dir / "bounds_20230101.json").write_text("{}", encoding="utf-8")
    (overlay_dir / "preview_20230101.png").write_bytes(b"fake")
    spec = _time_series_spec(tmp_path)

    assert spec.resolve_bounds("20230101").name == "bounds_20230101.json"
    assert spec.resolve_source_path("20230101").name == "src_20230101.mat"
    assert spec.resolve_png("20230101").name == "preview_20230101.png"


def test_empty_time_list_still_blocks_traversal(tmp_path: Path) -> None:
    # Defense-in-depth: even when time_list is empty the ``..`` segment is blocked.
    spec = _time_series_spec(tmp_path, time_list=[])
    with pytest.raises(HTTPException) as ei:
        spec.resolve_bounds("../../etc/passwd")
    _expect_404(ei.value)
    with pytest.raises(HTTPException) as ei:
        spec.resolve_source_path("../../etc/passwd")
    _expect_404(ei.value)


def test_static_overlay_unaffected(tmp_path: Path) -> None:
    overlay_dir = tmp_path / "static_overlay"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    (overlay_dir / "bounds.json").write_text("{}", encoding="utf-8")
    spec = OverlaySpec(
        layer_id="test-static",
        overlay_dir=overlay_dir,
        category="static",
        png_filename="preview.png",
        bounds_filename="bounds.json",
    )
    assert spec.resolve_bounds(None).name == "bounds.json"
    # Static layers ignore the time param entirely.
    assert spec.resolve_bounds("../../etc/passwd").name == "bounds.json"
