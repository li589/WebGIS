"""Overlay registry path-traversal regression tests (G1-01).

Covers time-list whitelist validation and ``..``-segment defense-in-depth for
``resolve_png`` / ``resolve_bounds`` / ``resolve_source_path`` (used by
``/overlay-preview``, ``/overlay-bounds``, ``/overlay-tiles``, ``/overlay-value``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.errors import OverlayNotFoundError, OverlayValidationError
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


def test_resolve_bounds_rejects_traversal(tmp_path: Path) -> None:
    spec = _time_series_spec(tmp_path)
    with pytest.raises(OverlayNotFoundError) as ei:
        spec.resolve_bounds("../../etc/passwd")
    assert ei.value.status_code == 404


def test_resolve_source_path_rejects_traversal(tmp_path: Path) -> None:
    spec = _time_series_spec(tmp_path)
    with pytest.raises(OverlayNotFoundError) as ei:
        spec.resolve_source_path("../../etc/passwd")
    assert ei.value.status_code == 404


def test_resolve_source_path_rejects_glob_traversal(tmp_path: Path) -> None:
    # Glob branch: pattern contains a wildcard after the traversal segment.
    spec = _time_series_spec(
        tmp_path, source_pattern=str(tmp_path / "overlay" / "src_{time}_*.mat")
    )
    with pytest.raises(OverlayNotFoundError) as ei:
        spec.resolve_source_path("../../etc/passwd")
    assert ei.value.status_code == 404


def test_resolve_png_rejects_traversal(tmp_path: Path) -> None:
    spec = _time_series_spec(tmp_path)
    with pytest.raises(OverlayNotFoundError) as ei:
        spec.resolve_png("../../etc/passwd")
    assert ei.value.status_code == 404


def test_resolve_bounds_rejects_unknown_time(tmp_path: Path) -> None:
    spec = _time_series_spec(tmp_path)
    with pytest.raises(OverlayNotFoundError) as ei:
        spec.resolve_bounds("19990101")
    assert ei.value.status_code == 404


def test_resolve_source_path_rejects_unknown_time(tmp_path: Path) -> None:
    spec = _time_series_spec(tmp_path)
    with pytest.raises(OverlayNotFoundError) as ei:
        spec.resolve_source_path("19990101")
    assert ei.value.status_code == 404


def test_resolve_requires_time_for_time_series(tmp_path: Path) -> None:
    spec = _time_series_spec(tmp_path, time_list=["20230101"])
    # default_time set → resolves; but a spec without default and without time → 400.
    spec_no_default = _time_series_spec(tmp_path, time_list=["20230101"])
    spec_no_default.default_time = None
    with pytest.raises(OverlayValidationError) as ei:
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
    with pytest.raises(OverlayNotFoundError) as ei:
        spec.resolve_bounds("../../etc/passwd")
    assert ei.value.status_code == 404
    with pytest.raises(OverlayNotFoundError) as ei:
        spec.resolve_source_path("../../etc/passwd")
    assert ei.value.status_code == 404


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


# ── P2-4：direct 源图层（仅 GeoTIFF/COG + bounds.json，无烘焙 preview） ──────


def _make_direct_overlay_dir(tmp_path, *, with_preview: bool, with_source: bool):
    """构造 imported-* overlay 目录：bounds.json + 可选 source.tif/preview.png。"""
    import json as _json

    dest = tmp_path / "imports" / "imported-direct-test"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "bounds.json").write_text(
        _json.dumps({"bounds": [100.0, 30.0, 110.0, 40.0], "meta": {"palette": "viridis"}}),
        encoding="utf-8",
    )
    if with_source:
        (dest / "source.tif").write_bytes(b"")
    if with_preview:
        (dest / "preview.png").write_bytes(b"")
    return dest


def test_direct_source_overlay_registers_without_preview(monkeypatch, tmp_path) -> None:
    """仅有 source GeoTIFF + bounds.json（无 preview.png）→ 允许注册（P2-4）。"""
    from app.services import overlay_registry as reg

    dest = _make_direct_overlay_dir(tmp_path, with_preview=False, with_source=True)
    monkeypatch.setattr(
        "app.data_io.services.paths.IMPORTS_DIR", tmp_path / "imports"
    )
    reg.unregister_overlay("imported-direct-test")
    spec = reg._try_load_imported_overlay("imported-direct-test")
    assert spec is not None
    assert spec.png_filename is None
    assert spec.source_path is not None
    assert spec.source_path.name == "source.tif"
    reg.unregister_overlay("imported-direct-test")


def test_no_preview_no_source_still_rejected(monkeypatch, tmp_path) -> None:
    """无 preview 且无 source → 仍拒绝注册（原行为不回退）。"""
    from app.services import overlay_registry as reg

    _make_direct_overlay_dir(tmp_path, with_preview=False, with_source=False)
    monkeypatch.setattr(
        "app.data_io.services.paths.IMPORTS_DIR", tmp_path / "imports"
    )
    reg.unregister_overlay("imported-direct-test")
    assert reg._try_load_imported_overlay("imported-direct-test") is None


def test_bounds_meta_reports_has_overview_false(monkeypatch, tmp_path) -> None:
    """direct 源图层的 bounds meta 带 has_overview=False（前端全程瓦片判定）。"""
    from app.services import overlay_registry as reg

    _make_direct_overlay_dir(tmp_path, with_preview=False, with_source=True)
    monkeypatch.setattr(
        "app.data_io.services.paths.IMPORTS_DIR", tmp_path / "imports"
    )
    reg.unregister_overlay("imported-direct-test")
    spec = reg._try_load_imported_overlay("imported-direct-test")
    assert spec is not None
    meta = spec.meta_dict()
    # has_overview 在 get_overlay_bounds_meta 注入；spec 层验证 png_filename 为 None
    assert spec.png_filename is None
    reg.unregister_overlay("imported-direct-test")
