"""Unit tests for D2 avg-omega algorithm (algorithms/omega_avg.py).

Covers the 4 stage functions:
  - build_raw_omega_daily_cache (Stage A)
  - build_doy_omega_climatology (Stage B)
  - extract_halpha_maps (Stage C)
  - retrieve_daily_with_avg_omega (Stage D, with mocked daily bundle)

The provider package has a circular import (contracts <-> workflow); importing
``contracts`` first breaks the cycle (same pattern as service/job_api.py).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

# ── Provider path setup (must precede algorithm imports) ─────────────────────
_PROVIDER_ROOT = (
    Path(__file__).resolve().parents[2] / "algorithms" / "providers" / "Python"
)
if str(_PROVIDER_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROVIDER_ROOT))

import contracts  # noqa: E402, F401 — break circular import: contracts first
from algorithms.omega_avg import (  # noqa: E402
    build_omega_avg_config,
    build_raw_omega_daily_cache,
    build_doy_omega_climatology,
    extract_halpha_maps,
    retrieve_daily_with_avg_omega,
)
from scipy.io import savemat  # noqa: E402


# ─── Shared fixtures ────────────────────────────────────────────────────────

_GRID_SHAPE = (6, 8)  # small grid for fast tests
_NPIX = _GRID_SHAPE[0] * _GRID_SHAPE[1]


def _make_omega_vec(seed: int) -> np.ndarray:
    """Synthetic 1D OMEGA vector (npix,) with plausible albedo range [0, 0.3]."""
    rng = np.random.default_rng(seed)
    return np.clip(0.10 + 0.05 * rng.standard_normal(_NPIX), 0.0, 0.3)


def _make_omega_2d(seed: int) -> np.ndarray:
    return _make_omega_vec(seed).reshape(_GRID_SHAPE)


# ─── Stage A: build_raw_omega_daily_cache ───────────────────────────────────


def test_build_raw_omega_daily_cache_creates_2d_files(tmp_path: Path) -> None:
    """Stage A reads daily_omega/{date}.mat (1D OMEGA) → {year}/{date}.mat (2D)."""
    omega_block_dir = tmp_path / "omega_block"
    daily_dir = omega_block_dir / "daily_omega"
    daily_dir.mkdir(parents=True)
    cache_dir = tmp_path / "cache"

    # Create 3 daily OMEGA files for 2023
    for i, date_key in enumerate(["20230101", "20230102", "20230103"]):
        savemat(
            daily_dir / f"{date_key}.mat",
            {"OMEGA": _make_omega_vec(seed=100 + i)},
            do_compression=True,
        )

    result = build_raw_omega_daily_cache(
        omega_block_dir=omega_block_dir,
        output_cache_dir=cache_dir,
        years=[2023],
        grid_shape=_GRID_SHAPE,
    )

    assert result["cached_days"] == 3
    assert result["skipped_days"] == 362  # 365 - 3
    assert 2023 in result["years"]
    # Verify cached file has 2D OMEGA_2d
    from scipy.io import loadmat

    cached = loadmat(cache_dir / "2023" / "20230101.mat")
    assert "OMEGA_2d" in cached
    assert cached["OMEGA_2d"].shape == _GRID_SHAPE


def test_build_raw_omega_daily_cache_size_mismatch_raises(tmp_path: Path) -> None:
    """Stage A raises ValueError when OMEGA vector size != grid npix."""
    daily_dir = tmp_path / "omega_block" / "daily_omega"
    daily_dir.mkdir(parents=True)
    savemat(
        daily_dir / "20230101.mat",
        {"OMEGA": np.zeros(_NPIX + 1)},  # wrong size
        do_compression=True,
    )
    with pytest.raises(ValueError, match="!= grid npix"):
        build_raw_omega_daily_cache(
            omega_block_dir=tmp_path / "omega_block",
            output_cache_dir=tmp_path / "cache",
            years=[2023],
            grid_shape=_GRID_SHAPE,
        )


# ─── Stage B: build_doy_omega_climatology ───────────────────────────────────


def test_build_doy_omega_climatology_computes_mean(tmp_path: Path) -> None:
    """Stage B computes per-DOY nanmean → OMEGA_AVG, count → count_grid."""
    cache_dir = tmp_path / "cache"
    doy_dir = tmp_path / "doy"

    # Create 2 years of cache for DOY 1 (Jan 1)
    for year in [2022, 2023]:
        year_dir = cache_dir / str(year)
        year_dir.mkdir(parents=True)
        savemat(
            year_dir / f"{year}0101.mat",
            {"OMEGA_2d": _make_omega_2d(seed=year)},
            do_compression=True,
        )

    result = build_doy_omega_climatology(
        cache_dir=cache_dir,
        output_doy_dir=doy_dir,
        years=[2022, 2023],
        grid_shape=_GRID_SHAPE,
    )

    assert result["doy_files"] >= 1
    from scipy.io import loadmat

    doy1 = loadmat(doy_dir / "doy_001.mat")
    assert "OMEGA_AVG" in doy1
    assert doy1["OMEGA_AVG"].shape == _GRID_SHAPE
    assert "count_grid" in doy1
    # Both years present → count == 2 everywhere
    assert np.all(doy1["count_grid"] == 2.0)
    # OMEGA_AVG should equal nanmean of the two years
    expected = np.nanmean(
        np.stack([_make_omega_2d(2022), _make_omega_2d(2023)]), axis=0
    )
    np.testing.assert_allclose(doy1["OMEGA_AVG"], expected, atol=1e-12)
    # used_years should list both years
    assert set(int(y) for y in doy1["used_years"].ravel()) == {2022, 2023}


def test_build_doy_omega_climatology_skips_missing_doy(tmp_path: Path) -> None:
    """Stage B only writes DOY files for DOYs that have data."""
    cache_dir = tmp_path / "cache"
    doy_dir = tmp_path / "doy"
    year_dir = cache_dir / "2023"
    year_dir.mkdir(parents=True)
    # Only DOY 1 (Jan 1)
    savemat(
        year_dir / "20230101.mat",
        {"OMEGA_2d": _make_omega_2d(seed=1)},
        do_compression=True,
    )
    result = build_doy_omega_climatology(
        cache_dir=cache_dir,
        output_doy_dir=doy_dir,
        years=[2023],
        grid_shape=_GRID_SHAPE,
    )
    assert result["doy_files"] == 1
    assert (doy_dir / "doy_001.mat").exists()
    assert not (doy_dir / "doy_002.mat").exists()


# ─── Stage C: extract_halpha_maps ───────────────────────────────────────────


def test_extract_halpha_maps_reshapes_vectors(tmp_path: Path) -> None:
    """Stage C reshapes 1D h_star_vec/alpha_star_vec → 2D grids."""
    h_vec = np.clip(
        0.5 + 0.1 * np.random.default_rng(301).standard_normal(_NPIX), 0.0, 3.0
    )
    alpha_vec = np.clip(
        0.15 + 0.03 * np.random.default_rng(302).standard_normal(_NPIX), 0.05, 0.35
    )
    block_path = tmp_path / "omega_block_20230101_20230108.mat"
    savemat(
        block_path,
        {"h_star_vec": h_vec, "alpha_star_vec": alpha_vec},
        do_compression=True,
    )
    h_map, alpha_map = extract_halpha_maps(block_path, _GRID_SHAPE)
    assert h_map.shape == _GRID_SHAPE
    assert alpha_map.shape == _GRID_SHAPE
    np.testing.assert_allclose(h_map.ravel(), h_vec)
    np.testing.assert_allclose(alpha_map.ravel(), alpha_vec)


def test_extract_halpha_maps_size_mismatch_raises(tmp_path: Path) -> None:
    """Stage C raises ValueError when vector size != grid npix."""
    block_path = tmp_path / "block.mat"
    savemat(
        block_path,
        {"h_star_vec": np.zeros(_NPIX + 1), "alpha_star_vec": np.zeros(_NPIX)},
        do_compression=True,
    )
    with pytest.raises(ValueError, match="h_star_vec size"):
        extract_halpha_maps(block_path, _GRID_SHAPE)


# ─── Stage D: retrieve_daily_with_avg_omega (mocked daily bundle) ───────────


def _make_mock_bundle() -> dict:
    """Build a mock daily bundle return (matches build_daily_bundle_for_date output)."""
    rng = np.random.default_rng(401)
    static = {
        "LC": rng.integers(1, 13, size=_NPIX).astype(np.float64),
        "lat_9km": None,
        "lon_9km": None,
        "Albedo": np.full(_NPIX, 0.10),
        "B": np.full(_NPIX, 0.20),
        "SF_static": np.full(_NPIX, 0.08),
        "BD": np.full(_NPIX, 1350.0),
        "H": np.full(_NPIX, 0.10),
        "CF": np.full(_NPIX, 0.20),
        "porosity": np.full(_NPIX, 0.45),
        "NDVI_v_max": np.full(_NPIX, 0.60),
        "NDVI_v_min": np.full(_NPIX, 0.10),
    }
    return {
        "date_str": "20230101",
        "TBv": np.full(_NPIX, 255.0),
        "TBh": np.full(_NPIX, 210.0),
        "IA": np.full(_NPIX, 40.0),
        "Ts": np.full(_NPIX, 290.0),
        "TC": np.full(_NPIX, 292.0),
        "Tsoil1": np.full(_NPIX, 288.0),
        "Tsoil2": np.full(_NPIX, 287.0),
        "Ct": np.full(_NPIX, 291.0),
        "TG": np.full(_NPIX, 288.0),
        "SM_ref": np.full(_NPIX, 0.25),
        "NDVI": np.full(_NPIX, 0.35),
        "SF": np.full(_NPIX, 0.08),
        "vwc": np.full(_NPIX, 5.0),
        **static,
    }


def test_retrieve_daily_with_avg_omega_single_temp(tmp_path: Path) -> None:
    """Stage D (ORIG_TS) produces SM/VOD/OMEGA .mat for one day."""
    doy_dir = tmp_path / "doy"
    doy_dir.mkdir()
    savemat(
        doy_dir / "doy_001.mat",
        {"OMEGA_AVG": np.full(_GRID_SHAPE, 0.10)},
        do_compression=True,
    )
    output_dir = tmp_path / "out"
    config = build_omega_avg_config(
        {"target_year": 2023, "enable_parallel": False, "print_every_days": 1}
    )

    # Mock DailyBundleConfig with temp_scheme=ORIG_TS
    class _MockBundleConfig:
        temp_scheme = "ORIG_TS"

    # NOTE: build_daily_bundle_for_date is imported INSIDE retrieve_daily_with_avg_omega
    # (from ingest.daily_bundle import build_daily_bundle_for_date), so it is never a
    # module-level attribute of algorithms.omega_avg. Patch at the source module so the
    # function-local `from X import Y` picks up the mock via getattr(sys.modules[X], Y).
    with patch(
        "ingest.daily_bundle.build_daily_bundle_for_date",
        return_value=_make_mock_bundle(),
    ):
        result = retrieve_daily_with_avg_omega(
            target_year=2023,
            omega_avg_doy_dir=doy_dir,
            h_map=np.full(_GRID_SHAPE, 0.50),
            alpha_map=np.full(_GRID_SHAPE, 0.15),
            datasource_selection={},
            config=config,
            daily_bundle_config=_MockBundleConfig(),
            lin_pix=None,
            grid_shape=_GRID_SHAPE,
            output_dir=output_dir,
        )

    # Only DOY 1 has data; 2023-01-01 should be processed
    assert result["days_processed"] >= 1
    from scipy.io import loadmat

    day_path = output_dir / "20230101.mat"
    assert day_path.exists()
    data = loadmat(day_path)
    assert data["SM"].shape == _GRID_SHAPE
    assert data["VOD"].shape == _GRID_SHAPE
    assert data["OMEGA"].shape == _GRID_SHAPE
    # SM should be in plausible range [0, porosity]
    sm = data["SM"]
    valid = sm[np.isfinite(sm)]
    assert valid.size > 0
    assert np.all(valid >= 0.0)
    assert np.all(valid <= 0.60)


def test_retrieve_daily_with_avg_omega_dual_temp(tmp_path: Path) -> None:
    """Stage D (DUAL) uses tc/tg path and produces valid SM/VOD."""
    doy_dir = tmp_path / "doy"
    doy_dir.mkdir()
    savemat(
        doy_dir / "doy_001.mat",
        {"OMEGA_AVG": np.full(_GRID_SHAPE, 0.10)},
        do_compression=True,
    )
    output_dir = tmp_path / "out"
    config = build_omega_avg_config(
        {"target_year": 2023, "enable_parallel": False, "print_every_days": 1}
    )

    class _MockBundleConfig:
        temp_scheme = "DUAL"

    # NOTE: build_daily_bundle_for_date is imported INSIDE retrieve_daily_with_avg_omega
    # (from ingest.daily_bundle import build_daily_bundle_for_date), so it is never a
    # module-level attribute of algorithms.omega_avg. Patch at the source module so the
    # function-local `from X import Y` picks up the mock via getattr(sys.modules[X], Y).
    with patch(
        "ingest.daily_bundle.build_daily_bundle_for_date",
        return_value=_make_mock_bundle(),
    ):
        result = retrieve_daily_with_avg_omega(
            target_year=2023,
            omega_avg_doy_dir=doy_dir,
            h_map=np.full(_GRID_SHAPE, 0.50),
            alpha_map=np.full(_GRID_SHAPE, 0.15),
            datasource_selection={},
            config=config,
            daily_bundle_config=_MockBundleConfig(),
            lin_pix=None,
            grid_shape=_GRID_SHAPE,
            output_dir=output_dir,
        )

    assert result["days_processed"] >= 1
    from scipy.io import loadmat

    data = loadmat(output_dir / "20230101.mat")
    assert data["SM"].shape == _GRID_SHAPE
    sm = data["SM"]
    valid = sm[np.isfinite(sm)]
    assert valid.size > 0
    assert np.all(valid >= 0.0)


def test_retrieve_daily_skips_missing_doy(tmp_path: Path) -> None:
    """Stage D skips days where DOY climatology file is missing."""
    doy_dir = tmp_path / "doy"
    doy_dir.mkdir()  # empty — no doy_*.mat files
    output_dir = tmp_path / "out"
    config = build_omega_avg_config(
        {"target_year": 2023, "enable_parallel": False, "print_every_days": 50}
    )

    class _MockBundleConfig:
        temp_scheme = "ORIG_TS"

    # NOTE: build_daily_bundle_for_date is imported INSIDE retrieve_daily_with_avg_omega
    # (from ingest.daily_bundle import build_daily_bundle_for_date), so it is never a
    # module-level attribute of algorithms.omega_avg. Patch at the source module so the
    # function-local `from X import Y` picks up the mock via getattr(sys.modules[X], Y).
    with patch(
        "ingest.daily_bundle.build_daily_bundle_for_date",
        return_value=_make_mock_bundle(),
    ):
        result = retrieve_daily_with_avg_omega(
            target_year=2023,
            omega_avg_doy_dir=doy_dir,
            h_map=np.full(_GRID_SHAPE, 0.50),
            alpha_map=np.full(_GRID_SHAPE, 0.15),
            datasource_selection={},
            config=config,
            daily_bundle_config=_MockBundleConfig(),
            lin_pix=None,
            grid_shape=_GRID_SHAPE,
            output_dir=output_dir,
        )

    assert result["days_processed"] == 0
    assert result["days_skipped"] == 365


# ─── Config builder ─────────────────────────────────────────────────────────


def test_build_omega_avg_config_defaults() -> None:
    cfg = build_omega_avg_config({})
    assert cfg.avg_build_start_year == 2015
    assert cfg.avg_build_end_year == 2025
    assert cfg.freq_ghz == 1.4
    assert cfg.lambda_tau == 20.0
    assert cfg.pixel_chunk_size == 200_000
    assert cfg.enable_parallel is True


def test_build_omega_avg_config_override() -> None:
    cfg = build_omega_avg_config(
        {
            "target_year": 2024,
            "avg_build_start_year": 2018,
            "avg_build_end_year": 2024,
            "freq_ghz": 1.41,
            "lambda_tau": 15.0,
            "pixel_chunk_size": 50000,
            "enable_parallel": False,
        }
    )
    assert cfg.avg_build_start_year == 2018
    assert cfg.avg_build_end_year == 2024
    assert cfg.freq_ghz == 1.41
    assert cfg.lambda_tau == 15.0
    assert cfg.pixel_chunk_size == 50000
    assert cfg.enable_parallel is False
