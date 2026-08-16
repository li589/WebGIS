"""grid_presets / invalid value helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.data_io.services.grid_presets import (
    align_array_to_grid_preset,
    match_grid_preset,
    resolve_geo_reference,
    suggest_grid_preset,
)
from app.data_io.services.raster_science import (
    apply_invalid_values,
    extract_variable_to_geotiff,
)


def test_suggest_ease2_9km_shape():
    assert suggest_grid_preset([1624, 3856]) == "ease2-global-9km"
    assert suggest_grid_preset([1, 1624, 3856]) == "ease2-global-9km"
    assert suggest_grid_preset([100, 200]) is None


def test_match_ease2_transposed_shape():
    pid, transposed = match_grid_preset([3856, 1624])
    assert pid == "ease2-global-9km"
    assert transposed is True
    pid2, transposed2 = match_grid_preset([1624, 3856])
    assert pid2 == "ease2-global-9km"
    assert transposed2 is False


def test_align_array_auto_transpose_for_ease2():
    arr = np.zeros((3856, 1624), dtype=np.float32)
    aligned, did = align_array_to_grid_preset(
        arr, "ease2-global-9km", axis_order="auto"
    )
    assert did is True
    assert aligned.shape == (1624, 3856)


def test_align_array_swap_xy_alias_transpose():
    """swap_xy=True → axis_order=transpose：强制转置。"""
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    aligned, did = align_array_to_grid_preset(arr, "custom", axis_order="transpose")
    assert did is True
    assert aligned.shape == (4, 3)


def test_resolve_ease2_transform_symmetric():
    transform, crs, bounds = resolve_geo_reference(
        height=1624,
        width=3856,
        grid_preset="ease2-global-9km",
    )
    assert crs == "EPSG:6933"
    assert bounds[0] == -bounds[2]
    assert bounds[1] == -bounds[3]
    assert bounds[0] < bounds[2]
    assert transform is not None


def test_ease2_bounds_to_wgs84_not_collapsed():
    from app.services.crs import crs_transformer
    from app.data_io.services.grid_presets import GRID_PRESETS

    b = GRID_PRESETS["ease2-global-9km"]["bounds"]
    w, s, e, n = crs_transformer.transform_bounds(*b, "EPSG:6933", "EPSG:4326")
    assert w < e
    assert abs(w + 180) < 1e-6
    assert abs(e - 180) < 1e-6
    assert s < -85.0
    assert n > 85.0


def test_asymmetric_ease_east_clamped_and_normalized():
    """模拟 west+cols*res 浮点越界：仍应得到全球 WGS84 bounds。"""
    from app.services.crs import crs_transformer

    # 故意让 east 略大于有效域
    w, s, e, n = crs_transformer.transform_bounds(
        -17367530.445161516,
        -7314540.830865865,
        17367530.445173528,
        7314540.830865865,
        "EPSG:6933",
        "EPSG:4326",
    )
    assert w < e
    assert e - w > 359.0


def test_apply_invalid_values():
    arr = np.array([[1.0, -9999.0], [np.nan, 3.0]], dtype=np.float32)
    out = apply_invalid_values(arr, invalid_values=[-9999.0], nodata=-1.0)
    assert out[0, 1] == -1.0
    assert out[1, 0] == -1.0
    assert out[0, 0] == 1.0


def test_extract_transposed_mat_like_array(tmp_path: Path):
    """Transposed EASE2 array must be written as 1624×3856 GeoTIFF."""
    import h5py

    mat_path = tmp_path / "omega_transposed.mat"
    data = np.arange(3856 * 1624, dtype=np.float32).reshape(3856, 1624)
    with h5py.File(mat_path, "w") as f:
        f.create_dataset("OMEGA_grid", data=data)

    out = tmp_path / "out.tif"
    meta = extract_variable_to_geotiff(
        mat_path,
        variable_id="OMEGA_grid",
        output_tif=out,
        grid_preset="ease2-global-9km",
        source_crs="EPSG:6933",
        axis_order="auto",
    )
    assert meta["axis_transposed"] is True
    assert meta["height"] == 1624
    assert meta["width"] == 3856
    assert out.exists()


# ── GRIB（cfgrib）：inspect / 提取 / 上传校验 ──────────────────────────────

GRIB_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "Test"
    / "algorithms"
    / "fixtures"
    / "grib2_t2m_2x2.grib2"
)

pytest.importorskip("cfgrib", reason="GRIB 链路需 cfgrib")
pytest.importorskip("xarray", reason="GRIB 链路需 xarray")


def test_grib_fixture_present() -> None:
    assert GRIB_FIXTURE.is_file(), (
        f"{GRIB_FIXTURE} 缺失：在仓库根执行 "
        "Env/Python312/python.exe Test/algorithms/fixtures/generate_grib2_fixture.py 重新生成"
    )


def test_list_raster_variables_grib() -> None:
    from app.data_io.services.raster_science import list_raster_variables

    info = list_raster_variables(GRIB_FIXTURE)
    assert info["format"] == "grib2"
    assert info["needs_variable_select"] is True
    ids = [var["id"] for var in info["variables"]]
    assert "t2m" in ids
    t2m = next(var for var in info["variables"] if var["id"] == "t2m")
    assert t2m["shape"] == [2, 2]
    # 格点中心 (60,100)(59,101)，1° 步长 → 外扩半格 WSEN
    assert info["suggested_bounds"] == [99.5, 58.5, 101.5, 60.5]
    assert info["suggested_crs"] == "EPSG:4326"


def test_extract_grib_t2m_to_geotiff(tmp_path: Path) -> None:
    import rasterio

    out = tmp_path / "t2m.tif"
    meta = extract_variable_to_geotiff(
        GRIB_FIXTURE,
        variable_id="t2m",
        output_tif=out,
    )
    assert meta["crs"] == "EPSG:4326"
    assert meta["bounds"] == [99.5, 58.5, 101.5, 60.5]
    with rasterio.open(out) as src:
        assert (src.width, src.height) == (2, 2)
        band = src.read(1)
        assert float(band[0, 0]) == pytest.approx(274.15, abs=1e-2)
        assert src.nodata is not None
        assert float(band[1, 1]) == pytest.approx(float(src.nodata), abs=1e-6)


def test_extract_grib_unknown_variable() -> None:
    from app.data_io.services.raster_science import _load_2d_array

    with pytest.raises(ValueError, match="GRIB 变量不存在"):
        _load_2d_array(GRIB_FIXTURE, variable_id="nope", time_index=0)


def test_upload_validation_accepts_grib(tmp_path: Path) -> None:
    from app.data_io.services.upload_validation import (
        sniff_magic,
        validate_upload_filename,
    )

    assert validate_upload_filename("gfs.t06z.pgrb2.grib2").endswith(".grib2")
    grib_copy = tmp_path / "gfs.t06z.pgrb2.grib2"
    grib_copy.write_bytes(GRIB_FIXTURE.read_bytes())
    sniff_magic(grib_copy)  # GRIB 魔数匹配，不抛
    fake = tmp_path / "fake.grib2"
    fake.write_bytes(b"not-a-grib-payload")
    with pytest.raises(ValueError, match="不匹配"):
        sniff_magic(fake)
