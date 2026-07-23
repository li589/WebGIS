from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, TimeRange
from contracts.validation import JobRequestValidationError, validate_job_request
from runner.dispatch import run_job
from tests.test_run_job_dispatch import (
    _RecordingDataSource,
    _RecordingLogger,
    _RecordingScheduler,
)
from utils.local_adapters import LocalProductSink


class JobRequestValidationTests(unittest.TestCase):
    def _build_request(self, *, pipeline_name: str = "workflow") -> JobRequest:
        return JobRequest(
            job_id="job-validation",
            pipeline_name=pipeline_name,
            task_type="workflow",
            time_range=TimeRange(start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)),
            region=RegionSpec(kind="global", value={}),
            datasource_selection={},
            algorithm_params={},
            output_spec=OutputSpec(),
        )

    def test_validate_job_request_rejects_module_name_with_workflow_definition(
        self,
    ) -> None:
        request = self._build_request()
        request.module_name = "ndvi_daily"
        request.workflow_definition = {
            "workflow_id": "wf-inline",
            "nodes": [],
            "outputs": [{"name": "final_manifest", "source": "input:dummy"}],
        }

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        self.assertIn("cannot be combined", str(ctx.exception))

    def test_validate_job_request_allows_workflow_name_as_module_workflow_alias(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "ndvi_daily"
        request.module_name = "ndvi_daily"
        request.workflow_name = "custom-module-wrapper"
        request.datasource_selection = {"input_dir": "demo"}

        validated = validate_job_request(request)

        self.assertIs(validated, request)

    def test_validate_job_request_rejects_workflow_placeholder_without_selector(
        self,
    ) -> None:
        request = self._build_request(pipeline_name="workflow")

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        self.assertIn("placeholder", str(ctx.exception))

    def test_validate_job_request_rejects_real_pipeline_name_when_module_name_is_used(
        self,
    ) -> None:
        request = self._build_request(pipeline_name="ndvi_daily_pipeline")
        request.module_name = "ndvi_daily"

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        self.assertIn("must be 'workflow'", str(ctx.exception))

    def test_validate_job_request_rejects_unknown_module_name(self) -> None:
        request = self._build_request()
        request.module_name = "missing_module"

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        self.assertIn("Unknown module_name", str(ctx.exception))

    def test_validate_job_request_rejects_unknown_workflow_name(self) -> None:
        request = self._build_request()
        request.workflow_name = "missing_workflow"

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        self.assertIn("Unknown workflow_name", str(ctx.exception))

    def test_validate_job_request_accepts_registered_compat_pipeline(self) -> None:
        request = self._build_request(pipeline_name="retrieval_workflow_pipeline")

        validated = validate_job_request(request)

        self.assertIs(validated, request)

    def test_validate_job_request_rejects_missing_required_module_datasource_key(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "smap_daily"
        request.module_name = "smap_daily"

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        self.assertIn("requires datasource_selection keys", str(ctx.exception))
        self.assertIn("input_dir", str(ctx.exception))

    def test_validate_job_request_accepts_smap_module_with_data_access_request(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "smap_daily"
        request.module_name = "smap_daily"
        request.datasource_selection = {
            "_data_access_requests": {
                "SMAP_SPL3SMP_E": {
                    "selector": {"uris": ["D:/prepared/smap"]},
                }
            }
        }

        validated = validate_job_request(request)

        self.assertIs(validated, request)

    def test_validate_job_request_accepts_ndvi_module_with_data_access_request(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "ndvi_daily"
        request.module_name = "ndvi_daily"
        request.datasource_selection = {
            "_data_access_requests": {
                "NDVI_16DAY_RASTER": {
                    "selector": {"uris": ["D:/prepared/ndvi"]},
                }
            }
        }

        validated = validate_job_request(request)

        self.assertIs(validated, request)

    def test_validate_job_request_accepts_fy_module_with_data_access_request(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "fy_daily"
        request.module_name = "fy_daily"
        request.datasource_selection = {
            "_data_access_requests": {
                "FY_MWRI_HDF": {
                    "selector": {"uris": ["D:/prepared/fy_hdf"]},
                }
            }
        }

        validated = validate_job_request(request)

        self.assertIs(validated, request)

    def test_validate_job_request_accepts_station_module_with_data_access_request(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "station_daily"
        request.module_name = "station_daily"
        request.datasource_selection = {
            "_data_access_requests": {
                "ISMN_STM_OR_CASMOS_TXT": {
                    "selector": {"uris": ["D:/prepared/station"]},
                }
            }
        }

        validated = validate_job_request(request)

        self.assertIs(validated, request)

    def test_validate_job_request_accepts_inversion_module_with_data_access_request(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "inversion_daily"
        request.module_name = "inversion_daily"
        request.datasource_selection = {
            "_data_access_requests": {
                "daily_bundle_mat": {
                    "selector": {"uris": ["D:/prepared/daily_bundle.mat"]},
                }
            }
        }

        validated = validate_job_request(request)

        self.assertIs(validated, request)

    def test_validate_job_request_accepts_block_inversion_module_with_data_access_request(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "block_inversion"
        request.module_name = "block_inversion"
        request.datasource_selection = {
            "_data_access_requests": {
                "timeseries_bundle_mat": {
                    "selector": {"uris": ["D:/prepared/timeseries_bundle.mat"]},
                }
            }
        }

        validated = validate_job_request(request)

        self.assertIs(validated, request)

    def test_validate_job_request_accepts_omega_block_module_with_data_access_request(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "omega_block"
        request.module_name = "omega_block"
        request.datasource_selection = {
            "_data_access_requests": {
                "timeseries_bundle_mat": {
                    "selector": {"uris": ["D:/prepared/timeseries_bundle.mat"]},
                }
            }
        }

        validated = validate_job_request(request)

        self.assertIs(validated, request)

    def test_validate_job_request_rejects_invalid_module_algorithm_mode(self) -> None:
        request = self._build_request()
        request.task_type = "block_inversion"
        request.module_name = "block_inversion"
        request.datasource_selection = {"input_mat": "demo.mat"}
        request.algorithm_params = {"mode": "bad-mode"}

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        self.assertIn("rejects algorithm_params.mode", str(ctx.exception))

    def test_validate_job_request_rejects_module_task_type_mismatch(self) -> None:
        request = self._build_request()
        request.task_type = "retrieval"
        request.module_name = "smap_daily"
        request.datasource_selection = {"input_dir": "demo"}

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        self.assertIn("rejects task_type", str(ctx.exception))

    def test_validate_job_request_rejects_missing_retrieval_workflow_inputs_for_omega_mode(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "retrieval"
        request.workflow_name = "retrieval_workflow"
        request.algorithm_params = {"mode": "omega"}

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        self.assertIn("omega_fixed_mat", str(ctx.exception))
        self.assertIn("exp0_calib_mat", str(ctx.exception))

    def test_validate_job_request_accepts_retrieval_workflow_inputs_for_omega_mode(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "retrieval"
        request.workflow_name = "retrieval_workflow"
        request.algorithm_params = {"mode": "omega"}
        request.datasource_selection = {
            "omega_fixed_mat": "a.mat",
            "exp0_calib_mat": "b.mat",
        }

        validated = validate_job_request(request)

        self.assertIs(validated, request)

    def test_validate_job_request_accepts_retrieval_workflow_data_access_inputs_for_omega_mode(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "retrieval"
        request.workflow_name = "retrieval_workflow"
        request.algorithm_params = {"mode": "omega"}
        request.datasource_selection = {
            "_data_access_requests": {
                "omega_fixed_mat": {
                    "selector": {"uris": ["D:/prepared/omega_fixed.mat"]}
                },
                "exp0_calib_mat": {
                    "selector": {"uris": ["D:/prepared/exp0_calib.mat"]}
                },
            }
        }

        validated = validate_job_request(request)

        self.assertIs(validated, request)

    def test_validate_job_request_rejects_partial_retrieval_workflow_data_access_inputs_for_omega_mode(
        self,
    ) -> None:
        request = self._build_request()
        request.task_type = "retrieval"
        request.workflow_name = "retrieval_workflow"
        request.algorithm_params = {"mode": "omega"}
        request.datasource_selection = {
            "_data_access_requests": {
                "omega_fixed_mat": {
                    "selector": {"uris": ["D:/prepared/omega_fixed.mat"]}
                },
            }
        }

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        self.assertIn("exp0_calib_mat", str(ctx.exception))

    def test_validate_job_request_rejects_explicit_workflow_missing_required_input_binding(
        self,
    ) -> None:
        request = self._build_request()
        request.workflow_definition = {
            "workflow_id": "wf-inline-required-input",
            "nodes": [
                {
                    "node_id": "module_node",
                    "node_type": "module",
                    "input_bindings": {"datasource_selection": "input:source_value"},
                    "params": {"module_name": "daily_bundle"},
                }
            ],
            "outputs": [
                {"name": "final_manifest", "source": "node:module_node.manifest"}
            ],
        }

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        self.assertIn("requires datasource_selection keys", str(ctx.exception))
        self.assertIn("source_value", str(ctx.exception))

    def test_validate_job_request_accepts_explicit_workflow_data_access_request_for_required_input(
        self,
    ) -> None:
        request = self._build_request()
        request.workflow_definition = {
            "workflow_id": "wf-inline-data-access",
            "nodes": [
                {
                    "node_id": "module_node",
                    "node_type": "module",
                    "input_bindings": {"input_mat": "input:source_value"},
                    "params": {"module_name": "block_inversion"},
                }
            ],
            "outputs": [
                {"name": "final_manifest", "source": "node:module_node.manifest"}
            ],
        }
        request.datasource_selection = {
            "_data_access_requests": {
                "source_value": {
                    "selector": {"uris": ["D:/prepared/inline_bundle.mat"]},
                }
            }
        }

        validated = validate_job_request(request)

        self.assertIs(validated, request)

    def test_run_job_fails_fast_on_conflicting_selectors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _RecordingDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            request = self._build_request(pipeline_name="workflow")
            request.module_name = "ndvi_daily"
            request.workflow_definition = {
                "workflow_id": "wf-inline",
                "nodes": [],
                "outputs": [{"name": "final_manifest", "source": "input:dummy"}],
            }

            result = run_job(
                request,
                scheduler,
                datasource,
                logger,
                product_sink=sink,
                workspace=workspace,
            )

            self.assertEqual(result.status, "failed")
            self.assertIn("cannot be combined", result.error_summary)


if __name__ == "__main__":
    unittest.main()
