"""Unit tests for analysis.histogram (float64, nodata, bin edges)."""

from __future__ import annotations

import numpy as np
import pytest

from analysis.histogram import compute_histogram, histogram_to_chart_spec


def test_histogram_basic_counts():
    data = np.array([1.0, 2.0, 2.0, 3.0, 3.0, 3.0], dtype=np.float64)
    hist = compute_histogram(data, bins=3, value_range=(1.0, 3.0))
    assert hist["stats"]["count"] == 6.0
    assert abs(sum(hist["counts"]) - 6.0) < 1e-9
    assert len(hist["edges"]) == 4
    assert len(hist["counts"]) == 3


def test_histogram_nodata_and_nan():
    data = np.array([1.0, np.nan, -9999.0, 2.0, np.inf], dtype=np.float64)
    hist = compute_histogram(data, bins=4, nodata=-9999.0)
    assert hist["stats"]["count"] == 2.0
    assert hist["stats"]["min"] == 1.0
    assert hist["stats"]["max"] == 2.0


def test_histogram_all_nan():
    data = np.full(8, np.nan, dtype=np.float64)
    hist = compute_histogram(data, bins=5)
    assert hist["stats"]["count"] == 0.0
    assert all(c == 0.0 for c in hist["counts"])


def test_histogram_degenerate_single_value():
    data = np.ones(10, dtype=np.float64) * 42.0
    hist = compute_histogram(data, bins=5)
    assert hist["stats"]["count"] == 10.0
    assert sum(hist["counts"]) == 10.0
    # max must fall in last bin via nextafter widening
    assert hist["edges"][-1] > hist["edges"][-2]


def test_histogram_large_values_float64():
    # Keep magnitudes large but below float64 square overflow (~1e154)
    data = np.array([1e100, 1e100, 2e100], dtype=np.float64)
    hist = compute_histogram(data, bins=4)
    assert np.isfinite(hist["stats"]["mean"])
    assert hist["stats"]["count"] == 3.0
    assert np.isfinite(hist["stats"]["std"])


def test_histogram_to_chart_spec_shape():
    hist = compute_histogram(np.linspace(0, 1, 100), bins=10)
    chart = histogram_to_chart_spec(hist, title="Histogram (x)")
    assert chart["schema_version"] == "1"
    assert chart["chart_type"] == "histogram"
    assert len(chart["series"][0]["x"]) == 10
    assert len(chart["series"][0]["y"]) == 10


def test_histogram_bins_too_small():
    with pytest.raises(ValueError):
        compute_histogram(np.array([1.0, 2.0]), bins=1)
