"""Tests for shared raster ops and newly enabled stub workflow modules."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


class _FakeArtifactStore:
    def __init__(self) -> None:
        self.items: dict[str, object] = {}

    def put(self, artifact, payload=None) -> object:
        self.items[artifact.artifact_id] = payload
        return artifact

    def load(self, artifact_id: str) -> object:
        return self.items[artifact_id]


def _ctx(workspace: Path):
    from workflow.schemas import NodeExecutionContext

    request = SimpleNamespace(
        job_id="job-1",
        datasource_selection={},
        region=None,
        time_range=SimpleNamespace(start="2023-01-01", end="2023-01-02"),
    )
    runtime = SimpleNamespace(run_id="run-1", workspace=str(workspace))
    return NodeExecutionContext(
        workflow_id="wf",
        node_id="n1",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=_FakeArtifactStore(),  # type: ignore[arg-type]
        logger_adapter=None,
    )


def _write_demo_tif(path: Path, value: float = 10.0) -> Path:
    import rasterio
    from rasterio.transform import from_origin

    data = np.full((20, 20), value, dtype=np.float64)
    data[0, 0] = np.nan
    transform = from_origin(100.0, 30.0, 0.1, 0.1)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=20,
        width=20,
        count=1,
        dtype="float64",
        crs="EPSG:4326",
        transform=transform,
        nodata=np.nan,
    ) as dst:
        dst.write(data, 1)
    return path


class RasterOpsTests(unittest.TestCase):
    def test_safe_expression_and_remap(self) -> None:
        # Break known circular import: contracts ↔ workflow via eager contracts.__init__
        import contracts.job  # noqa: F401
        from modules._raster_ops import (
            RasterOpsValidationError,
            apply_remap,
            parse_remap_table,
            safe_raster_expression,
        )

        a = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
        b = np.array([[1.0, 1.0], [1.0, 1.0]], dtype=np.float64)
        out = safe_raster_expression("A * 2 + B", {"A": a, "B": b})
        np.testing.assert_allclose(out, [[3, 5], [7, 9]])

        with self.assertRaises(RasterOpsValidationError):
            safe_raster_expression("__import__('os').system('x')", {"A": a})

        rules = parse_remap_table("0-2:1,2-5:2")
        remapped = apply_remap(a, rules, nodata_value=-9999)
        self.assertEqual(remapped[0, 0], 1.0)
        self.assertEqual(remapped[1, 1], 2.0)


class StubModulesSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import contracts.job  # noqa: F401
        from modules import registry as module_registry

        cls.registry = module_registry

    def test_all_former_stubs_registered(self) -> None:
        names = set(self.registry.list_modules())
        expected = {
            "preprocess_reproject",
            "preprocess_resample",
            "preprocess_clip",
            "preprocess_mask",
            "stats_spatial_mean",
            "stats_temporal_trend",
            "stats_anomaly_detect",
            "stats_correlation",
            "fusion_spatial_interpolate",
            "fusion_multi_source_merge",
            "viz_report_export",
            "viz_statistics_summary",
            "gis_buffer_analysis",
            "gis_zonal_statistics",
            "gis_raster_calculator",
            "gis_vector_to_raster",
            "gis_raster_to_vector",
            "gis_reclassify",
            "gis_contour",
            "gis_slope_aspect",
            "gis_watershed",
        }
        missing = expected - names
        self.assertFalse(missing, f"missing modules: {missing}")

    def test_preprocess_clip_and_spatial_mean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            tif = _write_demo_tif(Path(tmp) / "demo.tif", value=5.0)
            ctx = _ctx(workspace)

            clip = self.registry.get_module("preprocess_clip").execute(
                {"raster": str(tif), "bbox": [100.0, 28.0, 102.0, 30.0]},
                {"buffer_meters": 0},
                ctx,
            )
            self.assertTrue(Path(str(clip["raster"])).exists())

            mean = self.registry.get_module("stats_spatial_mean").execute(
                {"raster": clip["raster"]},
                {"statistic": "mean", "band": 0},
                ctx,
            )
            self.assertAlmostEqual(float(mean["value"]), 5.0, places=5)

    def test_mask_reproject_calculator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            a = _write_demo_tif(Path(tmp) / "a.tif", value=2.0)
            m = _write_demo_tif(Path(tmp) / "m.tif", value=1.0)
            ctx = _ctx(workspace)

            masked = self.registry.get_module("preprocess_mask").execute(
                {"raster": str(a), "mask": str(m)},
                {"mask_value": 0, "invert": False},
                ctx,
            )
            self.assertTrue(Path(str(masked["raster"])).exists())

            calc = self.registry.get_module("gis_raster_calculator").execute(
                {"a": str(a)},
                {"expression": "A * 3"},
                ctx,
            )
            self.assertTrue(Path(str(calc["result"])).exists())

            reproj = self.registry.get_module("preprocess_reproject").execute(
                {"raster": str(a)},
                {"target_crs": "EPSG:3857", "resampling": "nearest"},
                ctx,
            )
            self.assertTrue(Path(str(reproj["raster"])).exists())

    def test_buffer_and_interpolate_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            ctx = _ctx(workspace)
            gj = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [113.0, 23.0]},
                        "properties": {"value": 10.0},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [113.2, 23.1]},
                        "properties": {"value": 20.0},
                    },
                ],
            }
            buf = self.registry.get_module("gis_buffer_analysis").execute(
                {"points": gj, "distance": 500},
                {"distance_unit": "meters", "segments": 8},
                ctx,
            )
            self.assertTrue(Path(str(buf["buffer"])).exists())

            interp = self.registry.get_module("fusion_spatial_interpolate").execute(
                {"points": gj, "bbox": [112.9, 22.9, 113.3, 23.2]},
                {"method": "idw", "resolution": 0.05, "value_field": "value"},
                ctx,
            )
            self.assertTrue(Path(str(interp["raster"])).exists())

            report = self.registry.get_module("viz_report_export").execute(
                {"manifest": buf["manifest"]},
                {"format": "html"},
                ctx,
            )
            self.assertTrue(Path(str(report["filepath"])).exists())

    def test_trend_correlation_anomaly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            ctx = _ctx(workspace)
            series = {
                "times": ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05"],
                "values": [1.0, 2.0, 3.0, 4.0, 100.0],
                "lon": 113.0,
                "lat": 23.0,
            }
            trend = self.registry.get_module("stats_temporal_trend").execute(
                {"timeseries": series},
                {"trend_method": "linear"},
                ctx,
            )
            self.assertTrue(Path(str(trend["result"])).exists())

            corr = self.registry.get_module("stats_correlation").execute(
                {
                    "x": {"values": [1, 2, 3, 4, 5]},
                    "y": {"values": [2, 4, 6, 8, 10]},
                },
                {"method": "pearson", "lag_days": 0},
                ctx,
            )
            self.assertAlmostEqual(float(corr["coefficient"]), 1.0, places=6)

            anom = self.registry.get_module("stats_anomaly_detect").execute(
                {"timeseries": series},
                {"method": "zscore", "threshold": 1.5},
                ctx,
            )
            anom_path = Path(str(anom["anomalies"]))
            self.assertTrue(anom_path.exists())
            payload = json.loads(anom_path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(payload["features"]), 1)

    def test_slope_and_watershed_guards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            # DEM with gradient
            import rasterio
            from rasterio.transform import from_origin

            dem_path = Path(tmp) / "dem.tif"
            yy, xx = np.mgrid[0:30, 0:30]
            dem = (xx + yy).astype(np.float64)
            transform = from_origin(100.0, 30.0, 0.01, 0.01)
            with rasterio.open(
                dem_path,
                "w",
                driver="GTiff",
                height=30,
                width=30,
                count=1,
                dtype="float64",
                crs="EPSG:4326",
                transform=transform,
            ) as dst:
                dst.write(dem, 1)

            ctx = _ctx(workspace)
            slope = self.registry.get_module("gis_slope_aspect").execute(
                {"dem": str(dem_path)},
                {"algorithm": "horn"},
                ctx,
            )
            self.assertTrue(Path(str(slope["slope"])).exists())
            self.assertTrue(Path(str(slope["aspect"])).exists())

            pour = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [100.15, 29.85],
                        },
                        "properties": {},
                    }
                ],
            }
            ws = self.registry.get_module("gis_watershed").execute(
                {"dem": str(dem_path), "pour_points": pour},
                {"flow_direction": "d8", "max_dem_pixels": 4_000_000},
                ctx,
            )
            self.assertTrue(Path(str(ws["watershed"])).exists())

    def test_stub_v1_pipeline_topologies(self) -> None:
        """Offline smoke mirroring stub_v1 system seed topologies."""
        from modules._raster_ops import RasterOpsValidationError

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            tif = _write_demo_tif(Path(tmp) / "smoke_stub.tif", value=5.0)
            points = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [113.0, 23.0]},
                        "properties": {"value": 10.0},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [113.2, 23.1]},
                        "properties": {"value": 20.0},
                    },
                ],
            }
            zones = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [100.0, 28.0],
                                    [102.0, 28.0],
                                    [102.0, 30.0],
                                    [100.0, 30.0],
                                    [100.0, 28.0],
                                ]
                            ],
                        },
                        "properties": {"id": 1},
                    }
                ],
            }
            ctx = _ctx(workspace)

            # preprocess_clip_reproject_basic
            clipped = self.registry.get_module("preprocess_clip").execute(
                {"raster": str(tif), "bbox": [100.0, 28.0, 102.0, 30.0]},
                {},
                ctx,
            )
            reproj = self.registry.get_module("preprocess_reproject").execute(
                {"raster": clipped["raster"]},
                {"target_crs": "EPSG:3857"},
                ctx,
            )
            self.assertTrue(Path(str(reproj["raster"])).exists())

            # analysis_raster_calc + analysis_reclassify
            calc = self.registry.get_module("gis_raster_calculator").execute(
                {"a": str(tif)},
                {"expression": "A * 2"},
                ctx,
            )
            reclass = self.registry.get_module("gis_reclassify").execute(
                {"raster": calc["result"]},
                {"remap_table": "0-10:1,10-100:2"},
                ctx,
            )
            self.assertTrue(Path(str(reclass["raster"])).exists())

            # analysis_buffer + analysis_zonal_stats
            buf = self.registry.get_module("gis_buffer_analysis").execute(
                {"points": points, "distance": 500},
                {"distance_unit": "meters"},
                ctx,
            )
            zonal = self.registry.get_module("gis_zonal_statistics").execute(
                {"raster": str(tif), "zones": zones},
                {"statistic": "mean"},
                ctx,
            )
            self.assertTrue(Path(str(buf["buffer"])).exists())
            self.assertTrue(Path(str(zonal["stats"])).exists())

            # stats_mean_summary_report_basic
            mean = self.registry.get_module("stats_spatial_mean").execute(
                {"raster": str(tif)},
                {"statistic": "mean"},
                ctx,
            )
            summary = self.registry.get_module("viz_statistics_summary").execute(
                {"raster": str(tif)},
                {},
                ctx,
            )
            report = self.registry.get_module("viz_report_export").execute(
                {"manifest": summary["manifest"]},
                {"format": "html"},
                ctx,
            )
            self.assertAlmostEqual(float(mean["value"]), 5.0, places=5)
            self.assertTrue(Path(str(report["filepath"])).exists())

            # fusion_idw_interpolate_basic
            interp = self.registry.get_module("fusion_spatial_interpolate").execute(
                {"points": points, "bbox": [112.9, 22.9, 113.3, 23.2]},
                {"method": "idw", "resolution": 0.05, "value_field": "value"},
                ctx,
            )
            self.assertTrue(Path(str(interp["raster"])).exists())

            # validation failures
            with self.assertRaises(RasterOpsValidationError):
                self.registry.get_module("preprocess_clip").execute(
                    {"raster": str(tif)},
                    {},
                    ctx,
                )
            with self.assertRaises(RasterOpsValidationError):
                self.registry.get_module("gis_raster_calculator").execute(
                    {"a": str(tif)},
                    {"expression": "__import__('os').system('x')"},
                    ctx,
                )
            with self.assertRaises(RasterOpsValidationError):
                self.registry.get_module("fusion_spatial_interpolate").execute(
                    {"points": points, "bbox": [112.9, 22.9, 113.3, 23.2]},
                    {"method": "idw", "max_points": 1, "value_field": "value"},
                    ctx,
                )

    def test_windowed_spatial_mean_path(self) -> None:
        import contracts.job  # noqa: F401
        from modules._raster_ops import (
            _FULL_READ_BUDGET_BYTES,
            reduce_raster_blocks,
        )

        with tempfile.TemporaryDirectory() as tmp:
            # Force windowed reduce helper on a small file (API contract)
            tif = _write_demo_tif(Path(tmp) / "w.tif", value=3.0)
            value, count = reduce_raster_blocks(tif, statistic="mean", band=0)
            self.assertAlmostEqual(value, 3.0, places=5)
            self.assertGreater(count, 0)
            self.assertGreater(_FULL_READ_BUDGET_BYTES, 0)


if __name__ == "__main__":
    unittest.main()
