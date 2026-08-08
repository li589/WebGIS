"""Optional GRIB read via cfgrib (skip when deps missing)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("cfgrib")
pytest.importorskip("xarray")

from data_access.universal_reader import UniversalDataReader  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "Test" / ".tmp-chart-debug" / "nomads_smoke.grib2"


@pytest.mark.skipif(not SAMPLE.is_file(), reason="local NOMADS smoke GRIB missing")
def test_universal_reader_grib_t2m() -> None:
    reader = UniversalDataReader(SAMPLE)
    data = reader.read_variable("t2m")
    assert data.var_name == "t2m"
    assert data.values is not None
    assert getattr(data.values, "size", 0) > 0


@pytest.mark.skipif(not SAMPLE.is_file(), reason="local NOMADS smoke GRIB missing")
def test_universal_reader_grib_magic_opaque_suffix(tmp_path: Path) -> None:
    opaque = tmp_path / "filter_gfs_0p25.pl"
    opaque.write_bytes(SAMPLE.read_bytes())
    reader = UniversalDataReader(opaque)
    assert reader.format == "grib"
    data = reader.read_variable("t2m")
    assert getattr(data.values, "size", 0) > 0
