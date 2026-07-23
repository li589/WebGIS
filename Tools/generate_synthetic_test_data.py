#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate synthetic test .mat files for algorithm E2E testing.

These files contain physically plausible brightness-temperature and
auxiliary-variable arrays so that the inversion / block-inversion / omega
algorithms can run end-to-end without requiring the full daily_bundle →
timeseries_bundle preprocessing pipeline.

Generated files (in Tools/test_data/):
  1. synthetic_daily_bundle.mat   — for inversion_daily (mode="dh")
     2-D grid arrays (rows × cols) matching the stage1_smap_mat format.

  2. synthetic_timeseries_bundle.mat — for block_inversion & omega_block (mode="dh")
     2-D time-pixel matrices (nt × npix) matching the timeseries_bundle format.

Run:
    python Tools/generate_synthetic_test_data.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.io import savemat

OUTPUT_DIR = Path(__file__).resolve().parent / "test_data"

# ─── Grid dimensions ────────────────────────────────────────────────────────
# Daily bundle: 2-D grid (rows × cols) — small but realistic EASE-Grid subset.
_ROWS = 24
_COLS = 48

# Timeseries bundle: (nt × npix) where npix = _ROWS * _COLS.
_NT = 5
_NPIX = _ROWS * _COLS


def _make_daily_grid(base: float, spread: float, seed: int) -> np.ndarray:
    """Create a 2-D grid with spatial variation (sinusoidal + noise)."""
    rng = np.random.default_rng(seed)
    rows = np.arange(_ROWS).reshape(-1, 1)
    cols = np.arange(_COLS).reshape(1, -1)
    spatial = np.sin(rows / _ROWS * np.pi) * np.cos(cols / _COLS * np.pi)
    noise = rng.normal(0, spread * 0.05, size=(_ROWS, _COLS))
    return (base + spread * spatial + noise).astype(np.float64)


def _make_timeseries_matrix(
    base: float, spread: float, seed: int, temporal_var: float = 0.02
) -> np.ndarray:
    """Create a 2-D (nt × npix) matrix with spatial + temporal variation."""
    rng = np.random.default_rng(seed)
    spatial = np.sin(np.linspace(0, np.pi, _NPIX)).reshape(1, -1)
    temporal = np.sin(np.arange(_NT) / _NT * np.pi).reshape(-1, 1)
    noise = rng.normal(0, spread * 0.03, size=(_NT, _NPIX))
    return (base + spread * spatial + temporal_var * base * temporal + noise).astype(
        np.float64
    )


def _make_static_vector(base: float, spread: float, seed: int) -> np.ndarray:
    """Create a 1-D (npix,) vector with spatial variation."""
    rng = np.random.default_rng(seed)
    spatial = np.sin(np.linspace(0, np.pi, _NPIX))
    noise = rng.normal(0, spread * 0.05, size=_NPIX)
    return np.clip(base + spread * spatial + noise, 0.01, None).astype(np.float64)


def generate_daily_bundle() -> Path:
    """Generate synthetic daily bundle .mat for inversion_daily (mode="dh").

    Required variables (from extract_inversion_inputs):
      TBv, TBh, Ts, Tau_ini, CF, Albedo, porosity, IA
    """
    data = {
        # Brightness temperatures (K) — realistic SMAP range
        "TBv": _make_daily_grid(255.0, 15.0, seed=101),
        "TBh": _make_daily_grid(210.0, 12.0, seed=102),
        # Surface temperature (K)
        "Ts": _make_daily_grid(290.0, 8.0, seed=103),
        # Initial vegetation optical thickness
        "Tau_ini": _make_daily_grid(0.12, 0.05, seed=104),
        # Clay fraction (0-1)
        "CF": np.clip(_make_daily_grid(0.20, 0.08, seed=105), 0.01, 0.60),
        # Albedo (2-D grid — retrieve_dynamic_h_grid ravels all arrays to 1-D
        # and indexes them uniformly; a scalar would cause IndexError)
        "Albedo": _make_daily_grid(0.10, 0.02, seed=106),
        # Porosity (0-1)
        "porosity": np.clip(_make_daily_grid(0.45, 0.05, seed=107), 0.25, 0.55),
        # Incidence angle (degrees) — SMAP ~40°
        "IA": _make_daily_grid(40.0, 2.0, seed=108),
        # Lat/lon grid (for spatial context)
        "lat": np.linspace(15.0, 25.0, _ROWS).reshape(-1, 1).repeat(_COLS, axis=1),
        "lon": np.linspace(110.0, 120.0, _COLS).reshape(1, -1).repeat(_ROWS, axis=0),
    }
    out = OUTPUT_DIR / "synthetic_daily_bundle.mat"
    savemat(out, data, do_compression=True)
    return out


def generate_timeseries_bundle() -> Path:
    """Generate synthetic timeseries bundle .mat for block_inversion & omega_block.

    Required 2-D (nt × npix) matrices:
      TBv_mat, TBh_mat, IA_mat, Ts_mat, NDVI_mat, SF_mat,
      TC_mat, TG_mat, SMref_mat   (omega additionally needs these)

    Required 1-D (npix,) static vectors:
      Albedo, B, CF, porosity, LC, NDVI_v_max, NDVI_v_min, H, BD
    """
    data = {
        # ── 2-D time-pixel matrices (nt × npix) ──────────────────────────
        # Brightness temperatures (K)
        "TBv_mat": _make_timeseries_matrix(255.0, 15.0, seed=201),
        "TBh_mat": _make_timeseries_matrix(210.0, 12.0, seed=202),
        # Incidence angle (degrees)
        "IA_mat": _make_timeseries_matrix(40.0, 2.0, seed=203, temporal_var=0.0),
        # Surface temperature (K)
        "Ts_mat": _make_timeseries_matrix(290.0, 8.0, seed=204),
        # NDVI (0-1)
        "NDVI_mat": np.clip(
            _make_timeseries_matrix(0.35, 0.15, seed=205), 0.0, 0.9
        ),
        # Scattering factor
        "SF_mat": np.clip(
            _make_timeseries_matrix(0.08, 0.03, seed=206), 0.01, 0.20
        ),
        # Canopy temperature (K) — for omega
        "TC_mat": _make_timeseries_matrix(292.0, 7.0, seed=207),
        # Ground temperature (K) — for omega
        "TG_mat": _make_timeseries_matrix(288.0, 9.0, seed=208),
        # Reference soil moisture (0-1) — for omega
        "SMref_mat": np.clip(
            _make_timeseries_matrix(0.25, 0.08, seed=209), 0.02, 0.50
        ),
        # ── 1-D static vectors (npix,) ───────────────────────────────────
        # Albedo
        "Albedo": _make_static_vector(0.10, 0.02, seed=210),
        # H-polarization roughness parameter
        "B": _make_static_vector(0.20, 0.03, seed=211),
        # Clay fraction
        "CF": _make_static_vector(0.20, 0.08, seed=212),
        # Porosity
        "porosity": _make_static_vector(0.45, 0.05, seed=213),
        # Landcover (IGBP class 1-12)
        "LC": np.random.default_rng(214).integers(1, 13, size=_NPIX).astype(
            np.float64
        ),
        # NDVI max/min for vegetation parameterization
        "NDVI_v_max": np.clip(
            _make_static_vector(0.60, 0.10, seed=215), 0.2, 0.9
        ),
        "NDVI_v_min": np.clip(
            _make_static_vector(0.10, 0.03, seed=216), 0.01, 0.3
        ),
        # Static roughness parameter H
        "H": _make_static_vector(0.10, 0.02, seed=217),
        # Bulk density (kg/m³)
        "BD": _make_static_vector(1350.0, 50.0, seed=218),
        # ── Metadata ─────────────────────────────────────────────────────
        "date_keys": np.array(
            ["20230101", "20230103", "20230105", "20230107", "20230109"]
        ),
        "missing_dates": np.array([], dtype=object),
        "pixel_count": np.array(_NPIX, dtype=np.int64),
    }
    out = OUTPUT_DIR / "synthetic_timeseries_bundle.mat"
    savemat(out, data, do_compression=True)
    return out


# ─── D2 avg-omega daily synthetic inputs ────────────────────────────────────
# Small 10-day dataset matching the file layout that OmegaAvgDailyModule +
# build_daily_bundle_for_date expect (SMAP + ORIG_TS + DAILY_FILE + STATIC sf).
_D2_DATE_KEYS = [
    "20230101", "20230102", "20230103", "20230104", "20230105",
    "20230106", "20230107", "20230108", "20230109", "20230110",
]
_D2_NT = len(_D2_DATE_KEYS)


def _make_d2_timeseries_matrix(
    base: float, spread: float, seed: int, temporal_var: float = 0.02
) -> np.ndarray:
    """Create a 2-D (_D2_NT × npix) matrix for D2 omega_block output.

    Unlike _make_timeseries_matrix (which uses the global _NT=5), this uses
    _D2_NT=10 rows so daily_omega has one slice per test date.
    """
    rng = np.random.default_rng(seed)
    spatial = np.sin(np.linspace(0, np.pi, _NPIX)).reshape(1, -1)
    temporal = np.sin(np.arange(_D2_NT) / _D2_NT * np.pi).reshape(-1, 1)
    noise = rng.normal(0, spread * 0.03, size=(_D2_NT, _NPIX))
    return (base + spread * spatial + temporal_var * base * temporal + noise).astype(
        np.float64
    )


def _make_omega_block_mat() -> dict:
    """Build omega_block .mat payload: 1D vectors + 2D (nt×npix) matrices.

    Contains h_star_vec / alpha_star_vec (consumed by Stage C extract_halpha_maps)
    plus OMEGA_mat / SM_RET_mat / VOD_RET_mat / date_keys for completeness.
    """
    return {
        # 1D (npix,) static vectors — Stage C reshapes these to 2D grid
        "h_star_vec": np.clip(
            _make_static_vector(0.50, 0.10, seed=602), 0.05, 3.0
        ),
        "alpha_star_vec": np.clip(
            _make_static_vector(0.15, 0.03, seed=603), 0.05, 0.35
        ),
        # 2D (_D2_NT × npix) time-pixel matrices
        "OMEGA_mat": np.clip(
            _make_d2_timeseries_matrix(0.10, 0.02, seed=604), 0.0, 0.30
        ),
        "SM_RET_mat": np.clip(
            _make_d2_timeseries_matrix(0.25, 0.08, seed=605), 0.02, 0.50
        ),
        "VOD_RET_mat": np.clip(
            _make_d2_timeseries_matrix(0.12, 0.05, seed=606), 0.0, 0.60
        ),
        "date_keys": np.array(_D2_DATE_KEYS),
        # grid metadata
        "pixel_count": np.array(_NPIX, dtype=np.int64),
    }


def generate_omega_avg_daily_inputs() -> Path:
    """Generate synthetic D2 avg-omega daily inputs.

    Layout (under Tools/test_data/omega_avg_daily_inputs/):
      omega_block/
        omega_block_20230101_20230110.mat  — h_star_vec, alpha_star_vec, OMEGA_mat, date_keys
        daily_omega/{YYYYMMDD}.mat          — OMEGA (1D npix)  [Stage A input]
      smap_daily/{YYYYMMDD}.mat             — TBv, TBh, IA, Ts, vwc, SM  [daily_bundle input]
      ndvi_daily/{YYYYMMDD}.mat             — NDVI  [daily_bundle input, DAILY_FILE mode]
      ndvi_clim/                             — empty (DAILY_FILE mode does not read it)
      anc/
        IGBP_9km_12.mat                     — IGBP_9km_12 (2D int), lat_9km, lon_9km
        Albedo.mat, B.mat, SF.mat, BD.mat, H.mat, CF.mat  — 2D static grids
        NDVI_extrema.mat                    — NDVI_v_max, NDVI_v_min  [needed by tau_from_ndvi]
    """
    root = OUTPUT_DIR / "omega_avg_daily_inputs"
    # Clean stale copy so re-runs are deterministic
    if root.exists():
        import shutil
        shutil.rmtree(root)

    # ── omega_block output ───────────────────────────────────────────────
    omega_block_dir = root / "omega_block"
    daily_omega_dir = omega_block_dir / "daily_omega"
    daily_omega_dir.mkdir(parents=True, exist_ok=True)

    block_payload = _make_omega_block_mat()
    block_path = omega_block_dir / "omega_block_20230101_20230110.mat"
    savemat(block_path, block_payload, do_compression=True)

    # daily_omega/{date}.mat — one OMEGA vector per day (sliced from OMEGA_mat)
    omega_mat = np.asarray(block_payload["OMEGA_mat"])  # (nt, npix)
    for i, date_key in enumerate(_D2_DATE_KEYS):
        savemat(
            daily_omega_dir / f"{date_key}.mat",
            {"OMEGA": omega_mat[i]},
            do_compression=True,
        )

    # ── smap_daily/{date}.mat — TBv/TBh/IA/Ts/vwc/SM (2D grid) ───────────
    smap_dir = root / "smap_daily"
    smap_dir.mkdir(parents=True, exist_ok=True)
    for i, date_key in enumerate(_D2_DATE_KEYS):
        day_noise = i * 0.5
        savemat(
            smap_dir / f"{date_key}.mat",
            {
                "TBv": _make_daily_grid(255.0 + day_noise, 12.0, seed=700 + i),
                "TBh": _make_daily_grid(210.0 + day_noise, 10.0, seed=710 + i),
                "IA": _make_daily_grid(40.0, 1.5, seed=720 + i),
                "Ts": _make_daily_grid(290.0 + day_noise, 6.0, seed=730 + i),
                "vwc": np.clip(
                    _make_daily_grid(5.0, 1.0, seed=740 + i), 0.5, 15.0
                ),
                "SM": np.clip(
                    _make_daily_grid(0.25, 0.06, seed=750 + i), 0.02, 0.50
                ),
            },
            do_compression=True,
        )

    # ── ndvi_daily/{date}.mat — NDVI (2D grid) ───────────────────────────
    ndvi_dir = root / "ndvi_daily"
    ndvi_dir.mkdir(parents=True, exist_ok=True)
    for i, date_key in enumerate(_D2_DATE_KEYS):
        savemat(
            ndvi_dir / f"{date_key}.mat",
            {"NDVI": np.clip(_make_daily_grid(0.35, 0.12, seed=800 + i), 0.0, 0.9)},
            do_compression=True,
        )

    # ── ndvi_clim/ — empty dir (DAILY_FILE mode does not read it) ────────
    (root / "ndvi_clim").mkdir(parents=True, exist_ok=True)

    # ── anc/ static files ────────────────────────────────────────────────
    anc_dir = root / "anc"
    anc_dir.mkdir(parents=True, exist_ok=True)

    # IGBP_9km_12.mat — 2D integer landcover grid + lat/lon
    rng = np.random.default_rng(900)
    lat_grid = np.linspace(15.0, 25.0, _ROWS).reshape(-1, 1).repeat(_COLS, axis=1)
    lon_grid = np.linspace(110.0, 120.0, _COLS).reshape(1, -1).repeat(_ROWS, axis=0)
    savemat(
        anc_dir / "IGBP_9km_12.mat",
        {
            "IGBP_9km_12": rng.integers(1, 13, size=(_ROWS, _COLS)).astype(np.float64),
            "lat_9km": lat_grid,
            "lon_9km": lon_grid,
        },
        do_compression=True,
    )
    # Static 2D grids — names must match daily_bundle loader file paths
    savemat(anc_dir / "Albedo.mat", {"Albedo": _make_daily_grid(0.10, 0.02, seed=901)}, do_compression=True)
    savemat(anc_dir / "B.mat", {"B": _make_daily_grid(0.20, 0.03, seed=902)}, do_compression=True)
    # sf_static_aliases = ("SF_smap", "SF") — provide SF_smap
    savemat(anc_dir / "SF.mat", {"SF_smap": np.clip(_make_daily_grid(0.08, 0.02, seed=903), 0.01, 0.20)}, do_compression=True)
    # BD must be in g/cm³ (matching _MINERAL_PARTICLE_DENSITY=2.65 g/cm³ in
    # algorithms/omega.py) so porosity = 1 - BD/2.65 is in [0, 1].
    # 1.35 g/cm³ = 1350 kg/m³ (realistic soil bulk density) → porosity ≈ 0.49.
    savemat(anc_dir / "BD.mat", {"BD": _make_daily_grid(1.35, 0.05, seed=904)}, do_compression=True)
    savemat(anc_dir / "H.mat", {"H": _make_daily_grid(0.10, 0.02, seed=905)}, do_compression=True)
    savemat(anc_dir / "CF.mat", {"CF": np.clip(_make_daily_grid(0.20, 0.06, seed=906), 0.01, 0.60)}, do_compression=True)
    # NDVI extrema — needed by tau_from_ndvi (NDVI_v_max / NDVI_v_min)
    savemat(
        anc_dir / "NDVI_extrema.mat",
        {
            "NDVI_v_max": np.clip(_make_daily_grid(0.60, 0.08, seed=907), 0.2, 0.9),
            "NDVI_v_min": np.clip(_make_daily_grid(0.10, 0.02, seed=908), 0.01, 0.3),
        },
        do_compression=True,
    )

    return root


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    daily = generate_daily_bundle()
    print(f"✓ Daily bundle:       {daily}  ({daily.stat().st_size // 1024} KB)")

    ts = generate_timeseries_bundle()
    print(f"✓ Timeseries bundle:  {ts}  ({ts.stat().st_size // 1024} KB)")

    d2_root = generate_omega_avg_daily_inputs()
    d2_files = sum(1 for _ in d2_root.rglob("*") if _.is_file())
    print(f"✓ D2 avg-omega inputs: {d2_root}  ({d2_files} files)")

    # Quick sanity check — verify variables
    from scipy.io import loadmat

    for path, expected_keys in [
        (daily, {"TBv", "TBh", "Ts", "Tau_ini", "CF", "Albedo", "porosity", "IA"}),
        (
            ts,
            {
                "TBv_mat", "TBh_mat", "IA_mat", "Ts_mat", "NDVI_mat", "SF_mat",
                "TC_mat", "TG_mat", "SMref_mat",
                "Albedo", "B", "CF", "porosity", "LC", "NDVI_v_max",
                "NDVI_v_min", "H", "BD",
            },
        ),
    ]:
        loaded = loadmat(path)
        missing = expected_keys - set(loaded.keys())
        if missing:
            print(f"  ✗ MISSING in {path.name}: {missing}")
        else:
            print(f"  ✓ All {len(expected_keys)} required variables present in {path.name}")


if __name__ == "__main__":
    main()
