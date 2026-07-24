"""Unit tests for A1/A2 NDVI HDF preprocess helpers (no real HDF required)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from ingest.ndvi_hdf_preprocess import (
    apply_ndvi_qa_mask,
    detect_source_kind,
    parse_ydoy_from_filename,
)


def test_detect_source_kind() -> None:
    assert detect_source_kind("VNP13C1.A2010009.h5") == "viirs"
    assert detect_source_kind("MOD13C1.A2010009.hdf") == "modis"
    with pytest.raises(ValueError):
        detect_source_kind("foo.tif")


def test_parse_ydoy_from_filename_matlab_slice() -> None:
    # Matlab hdfname(10:16) on VNP13C1.A2010009... → 2010009
    path = Path("VNP13C1.A2010009.h5")
    assert parse_ydoy_from_filename(path) == datetime(2010, 1, 9)


def test_apply_ndvi_qa_mask() -> None:
    ndvi = np.array([[5000, 12000], [-3000, 2500]], dtype=np.float64)
    qa = np.array([[0, 0], [0, 2]], dtype=np.float64)
    out = apply_ndvi_qa_mask(ndvi, qa)
    assert out[0, 0] == pytest.approx(0.5)
    assert np.isnan(out[0, 1])
    assert np.isnan(out[1, 0])
    assert np.isnan(out[1, 1])
