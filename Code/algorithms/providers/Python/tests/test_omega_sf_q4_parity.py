"""Regression tests for omega_sf preload fill + 8-day Dec 2025 blocks."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from algorithms.omega_sf import _fill_chunk_row, make_viirs8_blocks


def test_fill_chunk_row_matches_lin_pix_length() -> None:
    npix = 100
    full = np.arange(npix, dtype=np.float64)
    lin = np.array([10, 20, 30], dtype=np.int64)
    dest = np.full(3, np.nan)
    _fill_chunk_row(dest, full, lin)
    assert dest.tolist() == [10.0, 20.0, 30.0]


def test_fill_chunk_row_out_of_range_is_nan() -> None:
    full = np.array([1.0, 2.0], dtype=np.float64)
    lin = np.array([0, 5], dtype=np.int64)
    dest = np.zeros(2)
    _fill_chunk_row(dest, full, lin)
    assert dest[0] == 1.0
    assert np.isnan(dest[1])


def test_omega_sf_config_from_params_expands_bbox_list() -> None:
    from algorithms.omega_sf import OmegaSfConfig

    cfg = OmegaSfConfig.from_params(
        {"tb_source": "SMAP", "bbox": [15, -35, 35, -10], "max_pixels": 300}
    )
    assert cfg.bbox_west == 15.0
    assert cfg.bbox_south == -35.0
    assert cfg.bbox_east == 35.0
    assert cfg.bbox_north == -10.0
    assert cfg.max_pixels == 300


def test_make_viirs8_blocks_dec_2025_matches_matlab_ref() -> None:
    """Matlab Omega_Custom_Res Dec blocks: 03-10 / 11-18 / 19-26 / 27-31.

    With Dec-only tvec, the first calendar block starts 2025-11-25 (covers Dec 1-2).
    """
    start = datetime(2025, 12, 1)
    tvec = [start + timedelta(days=i) for i in range(31)]
    blocks = make_viirs8_blocks(tvec, block_days=8)
    ranges = [
        (b.strftime("%Y%m%d"), e.strftime("%Y%m%d"))
        for b, e in zip(blocks.starts, blocks.ends, strict=True)
    ]
    assert ranges[0] == ("20251125", "20251202")
    assert ("20251203", "20251210") in ranges
    assert ("20251211", "20251218") in ranges
    assert ("20251219", "20251226") in ranges
    assert ("20251227", "20251231") in ranges
