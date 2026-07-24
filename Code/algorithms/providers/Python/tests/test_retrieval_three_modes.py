"""Retrieval-01: dh/ddca/omega three-mode output branches."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from scipy.io import savemat

from contracts.job import JobRequest
from contracts.product import OutputSpec, ProductManifest
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
from workflow.executor import WorkflowRunner
from workflow.presets import build_retrieval_workflow_definition


class RetrievalThreeModesTests(unittest.TestCase):
    """Retrieval-01: dh/ddca/omega modes produce correct product types."""

    def _make_bundle_mat(self, tmp_dir: Path) -> Path:
        mat_path = tmp_dir / "bundle.mat"
        savemat(
            mat_path,
            {
                "TBv": np.zeros((1, 5), dtype=np.float64),
                "TBh": np.zeros((1, 5), dtype=np.float64),
                "IA": np.zeros((1, 5), dtype=np.float64),
                "Ts": np.zeros((1, 5), dtype=np.float64),
                "sm_dca": np.zeros((1, 5), dtype=np.float64),
                "NDVI": np.zeros((1, 5), dtype=np.float64),
                "SF": np.zeros((1, 5), dtype=np.float64),
                "Albedo": np.zeros((1, 5), dtype=np.float64),
                "B": np.zeros((1, 5), dtype=np.float64),
                "CF": np.zeros((1, 5), dtype=np.float64),
                "BD": np.zeros((1, 5), dtype=np.float64),
                "H": np.zeros((1, 5), dtype=np.float64),
            },
            do_compression=True,
        )
        return mat_path

    def _mock_payload(self) -> dict:
        return {
            "TBv_mat": np.zeros((1, 5), dtype=np.float64),
            "TBh_mat": np.zeros((1, 5), dtype=np.float64),
            "IA_mat": np.zeros((1, 5), dtype=np.float64),
            "Ts_mat": np.zeros((1, 5), dtype=np.float64),
            "SMref_mat": np.zeros((1, 5), dtype=np.float64),
            "NDVI_mat": np.zeros((1, 5), dtype=np.float64),
            "SF_mat": np.zeros((1, 5), dtype=np.float64),
            "Albedo": np.zeros((1, 5), dtype=np.float64),
            "B": np.zeros((1, 5), dtype=np.float64),
            "CF": np.zeros((1, 5), dtype=np.float64),
            "BD": np.zeros((1, 5), dtype=np.float64),
            "H": np.zeros((1, 5), dtype=np.float64),
            "DH_mat": np.zeros((1, 5), dtype=np.float64),
            "porosity": np.zeros((1, 5), dtype=np.float64),
            "LC": np.zeros((1, 5), dtype=np.float64),
            "NDVI_v_max": np.zeros((1, 5), dtype=np.float64),
            "NDVI_v_min": np.zeros((1, 5), dtype=np.float64),
            "lat_9km": np.zeros((1, 5), dtype=np.float64),
            "lon_9km": np.zeros((1, 5), dtype=np.float64),
            "date_keys": ["20200101"],
        }

    def _run_workflow(
        self, request: JobRequest, payload_data: dict | None = None
    ) -> ProductManifest:
        tmp_dir = Path(tempfile.mkdtemp())
        ctx = RuntimeContext(
            job_id=request.job_id,
            run_id=f"run-{request.job_id}",
            workspace=tmp_dir,
            tmp_dir=tmp_dir / "tmp",
            cache_dir=tmp_dir / "cache",
        )
        payload_data = payload_data or self._mock_payload()
        mock_bundle = MagicMock()
        mock_bundle.date_keys = ["20200101"]
        mock_bundle.data = dict(payload_data)
        mock_bundle.missing_dates = []
        mock_bundle.pixel_count = 5
        with (
            patch(
                "modules.bundles.build_timeseries_bundle_from_range",
                return_value=mock_bundle,
            ),
            patch("ingest.mat_bundle.load_mat_file", return_value=payload_data),
            patch(
                "algorithms.block_inversion.load_mat_file", return_value=payload_data
            ),
            patch("modules.block_inversion.load_mat_file", return_value=payload_data),
        ):
            definition = build_retrieval_workflow_definition(request)
            runner = WorkflowRunner()
            workflow_result = runner.run(definition, request, ctx)
        final_manifest_ref = workflow_result.outputs.get("final_manifest")
        if hasattr(final_manifest_ref, "artifact_id"):
            return runner.artifact_store.load(final_manifest_ref.artifact_id)
        return final_manifest_ref

    def test_dh_mode_produces_dh_block_and_daily_mats(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp())
        bundle_path = self._make_bundle_mat(tmp_dir)
        output_dir = tmp_dir / "output"
        output_dir.mkdir()

        request = JobRequest(
            job_id="retrieval-dh",
            pipeline_name="dummy",
            workflow_name="retrieval_workflow",
            task_type="retrieval",
            time_range=TimeRange(start=datetime(2020, 1, 1), end=datetime(2020, 1, 10)),
            region=RegionSpec(kind="global", value={}),
            datasource_selection={
                "smap_daily_mat": str(bundle_path),
                "ndvi_daily_mat": str(bundle_path),
                "ancillary_mat": str(bundle_path),
            },
            algorithm_params={"mode": "dh"},
            output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
        )

        result = self._run_workflow(request)
        self.assertIsNotNone(result)
        product_types = {p.type for p in result.products}
        self.assertIn("dh_block_mat", product_types)
        self.assertIn("dh_daily_mat", product_types)

    def test_ddca_mode_produces_sm_vod_and_daily_mats(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp())
        bundle_path = self._make_bundle_mat(tmp_dir)
        output_dir = tmp_dir / "output"
        output_dir.mkdir()

        request = JobRequest(
            job_id="retrieval-ddca",
            pipeline_name="dummy",
            workflow_name="retrieval_workflow",
            task_type="retrieval",
            time_range=TimeRange(start=datetime(2020, 1, 1), end=datetime(2020, 1, 10)),
            region=RegionSpec(kind="global", value={}),
            datasource_selection={
                "smap_daily_mat": str(bundle_path),
                "ndvi_daily_mat": str(bundle_path),
                "ancillary_mat": str(bundle_path),
                "dh_mat": str(bundle_path),
            },
            algorithm_params={"mode": "ddca"},
            output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
        )

        result = self._run_workflow(request)
        self.assertIsNotNone(result)
        product_types = {p.type for p in result.products}
        self.assertIn("sm_vod_block_mat", product_types)
        self.assertIn("sm_daily_mat", product_types)
        self.assertIn("vod_daily_mat", product_types)

    def test_omega_mode_produces_omega_block_daily_and_qc_layers(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp())
        bundle_path = self._make_bundle_mat(tmp_dir)
        output_dir = tmp_dir / "output"
        output_dir.mkdir()
        fixed_mat = tmp_dir / "omega_fixed.mat"
        calib_mat = tmp_dir / "exp0_calib.mat"
        savemat(fixed_mat, {"fixed": np.zeros((1, 5))}, do_compression=True)
        savemat(calib_mat, {"calib": np.zeros((1, 5))}, do_compression=True)

        request = JobRequest(
            job_id="retrieval-omega",
            pipeline_name="dummy",
            workflow_name="retrieval_workflow",
            task_type="retrieval",
            time_range=TimeRange(start=datetime(2020, 1, 1), end=datetime(2020, 1, 10)),
            region=RegionSpec(kind="global", value={}),
            datasource_selection={
                "smap_daily_mat": str(bundle_path),
                "ndvi_daily_mat": str(bundle_path),
                "ancillary_mat": str(bundle_path),
                "omega_fixed_mat": str(fixed_mat),
                "exp0_calib_mat": str(calib_mat),
            },
            algorithm_params={"mode": "omega"},
            output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
        )

        result = self._run_workflow(request)
        self.assertIsNotNone(result)
        product_types = {p.type for p in result.products}
        self.assertIn("omega_block_mat", product_types)
        self.assertIn("omega_daily_mat", product_types)
        self.assertIn("qc_condk_mat", result.qc_layers)

    def test_omega_mode_accepts_flat_timeseries_vectors(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp())
        output_dir = tmp_dir / "output"
        output_dir.mkdir()
        fixed_mat = tmp_dir / "omega_fixed.mat"
        calib_mat = tmp_dir / "exp0_calib.mat"
        savemat(fixed_mat, {"fixed": np.zeros((1, 5))}, do_compression=True)
        savemat(calib_mat, {"calib": np.zeros((1, 5))}, do_compression=True)

        request = JobRequest(
            job_id="retrieval-omega-flat",
            pipeline_name="dummy",
            workflow_name="retrieval_workflow",
            task_type="retrieval",
            time_range=TimeRange(start=datetime(2020, 1, 1), end=datetime(2020, 1, 10)),
            region=RegionSpec(kind="global", value={}),
            datasource_selection={
                "smap_daily_mat": str(tmp_dir / "bundle.mat"),
                "ndvi_daily_mat": str(tmp_dir / "bundle.mat"),
                "ancillary_mat": str(tmp_dir / "bundle.mat"),
                "omega_fixed_mat": str(fixed_mat),
                "exp0_calib_mat": str(calib_mat),
            },
            algorithm_params={"mode": "omega"},
            output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
        )

        flat_payload = {
            "TBv_mat": np.zeros(5, dtype=np.float64),
            "TBh_mat": np.zeros(5, dtype=np.float64),
            "IA_mat": np.zeros(5, dtype=np.float64),
            "Ts_mat": np.zeros(5, dtype=np.float64),
            "SMref_mat": np.zeros(5, dtype=np.float64),
            "NDVI_mat": np.zeros(5, dtype=np.float64),
            "SF_mat": np.zeros(5, dtype=np.float64),
            "Albedo": np.zeros(5, dtype=np.float64),
            "B": np.zeros(5, dtype=np.float64),
            "CF": np.zeros(5, dtype=np.float64),
            "BD": np.zeros(5, dtype=np.float64),
            "H": np.zeros(5, dtype=np.float64),
            "porosity": np.zeros(5, dtype=np.float64),
            "LC": np.zeros(5, dtype=np.float64),
            "NDVI_v_max": np.zeros(5, dtype=np.float64),
            "NDVI_v_min": np.zeros(5, dtype=np.float64),
            "lat_9km": np.zeros(5, dtype=np.float64),
            "lon_9km": np.zeros(5, dtype=np.float64),
            "date_keys": ["20200101"],
        }

        tmp_dir.joinpath("bundle.mat").write_bytes(b"MAT")
        result = self._run_workflow(request, payload_data=flat_payload)

        product_types = {p.type for p in result.products}
        self.assertIn("omega_block_mat", product_types)
        self.assertIn("omega_daily_mat", product_types)


if __name__ == "__main__":
    unittest.main()
