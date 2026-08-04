"""Tests for import filename / manual temporal meta."""

from __future__ import annotations

from app.data_io.services.time_label import (
    build_temporal_meta,
    guess_time_label_from_filename,
)


def test_guess_point_from_filename() -> None:
    g = guess_time_label_from_filename("SM_20251227.tif")
    assert g is not None
    assert g["kind"] == "point"
    assert g["label"] == "20251227"
    assert g["native_step"] == "1d"


def test_guess_range_from_filename() -> None:
    g = guess_time_label_from_filename("block_20251203_20251210.mat")
    assert g is not None
    assert g["kind"] == "range"
    assert g["label"] == "20251203_20251210"
    assert g["native_step"] == "8d"


def test_guess_dotted_date() -> None:
    g = guess_time_label_from_filename("SMAP_L3_2025.12.03.h5")
    assert g is not None
    assert g["label"] == "20251203"


def test_build_auto_static_when_no_date() -> None:
    meta = build_temporal_meta(temporal_mode="auto", source_name="dem_wgs84.tif")
    assert meta["temporal_kind"] == "static"
    assert meta["time_list"] == []


def test_build_manual_point() -> None:
    meta = build_temporal_meta(temporal_mode="point", time_label="2025-12-27")
    assert meta["time_list"] == ["20251227"]
    assert meta["temporal_source"] == "manual"


def test_build_manual_range_and_static() -> None:
    meta = build_temporal_meta(
        temporal_mode="range",
        time_start="20251203",
        time_end="20251210",
    )
    assert meta["time_list"] == ["20251203_20251210"]
    assert meta["native_step"] == "8d"
    static = build_temporal_meta(temporal_mode="static", source_name="x_20251227.tif")
    assert static["time_list"] == []
