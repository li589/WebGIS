from __future__ import annotations

import unittest
from datetime import UTC, datetime

from contracts.data import DataBundle, DataRequest
from contracts.job import JobRequest, JobResult
from contracts.product import OutputSpec, ProductManifest
from contracts.runtime import RegionSpec, TimeRange
from service.platform_adapters import (
    CallbackDataSourceAdapter,
    CallbackLoggerAdapter,
    CallbackProductSink,
    CallbackSchedulerAdapter,
    TrackingSchedulerAdapter,
)


def _build_request() -> JobRequest:
    return JobRequest(
        job_id="job-001",
        pipeline_name="workflow",
        task_type="workflow",
        time_range=TimeRange(start=datetime(2025, 1, 1), end=datetime(2025, 1, 2)),
        region=RegionSpec(kind="global", value={}),
        datasource_selection={},
        algorithm_params={},
        output_spec=OutputSpec(),
    )


class PlatformAdapterTests(unittest.TestCase):
    def test_callback_scheduler_adapter_invokes_callbacks(self) -> None:
        events = []
        completed = []
        request = _build_request()
        result = JobResult(
            job_id=request.job_id,
            run_id="run-001",
            status="success",
            started_at=datetime(2025, 1, 1, tzinfo=UTC),
            finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
        )
        adapter = CallbackSchedulerAdapter(
            get_run_context=lambda req: {"trace_id": req.job_id},
            update_status=lambda job_id, run_id, status, detail=None: events.append(
                (job_id, run_id, status, detail)
            ),
            complete=lambda job_result: completed.append(job_result.run_id),
        )

        context = adapter.get_run_context(request)
        adapter.update_status("job-001", "run-001", "running", {"stage": "dispatch"})
        adapter.complete(result)

        self.assertEqual(context["trace_id"], "job-001")
        self.assertEqual(events[0][2], "running")
        self.assertEqual(completed, ["run-001"])

    def test_tracking_scheduler_adapter_forwards_delegate_and_hooks(self) -> None:
        delegate_events = []
        tracked_events = []
        completed = []
        delegate = CallbackSchedulerAdapter(
            update_status=lambda job_id,
            run_id,
            status,
            detail=None: delegate_events.append((job_id, run_id, status)),
            complete=lambda result: completed.append(result.status),
        )
        adapter = TrackingSchedulerAdapter(
            delegate,
            on_status=lambda job_id, run_id, status, detail=None: tracked_events.append(
                (job_id, run_id, status)
            ),
            on_complete=lambda result: tracked_events.append(
                ("complete", result.run_id, result.status)
            ),
        )
        result = JobResult(
            job_id="job-001",
            run_id="run-002",
            status="success",
            started_at=datetime(2025, 1, 1, tzinfo=UTC),
            finished_at=datetime(2025, 1, 1, 0, 2, tzinfo=UTC),
        )

        adapter.update_status("job-001", "run-002", "planning")
        adapter.complete(result)

        self.assertEqual(delegate_events[0][2], "planning")
        self.assertEqual(tracked_events[0][2], "planning")
        self.assertEqual(tracked_events[1][0], "complete")
        self.assertEqual(completed, ["success"])

    def test_callback_datasource_adapter_and_product_sink_are_usable(self) -> None:
        request = DataRequest(
            dataset_name="demo",
            variables=["v1"],
            time_range=TimeRange(start=datetime(2025, 1, 1), end=datetime(2025, 1, 2)),
        )
        bundle = DataBundle(
            bundle_id="bundle-001",
            dataset_name="demo",
            variables=["v1"],
            time_range=request.time_range,
            storage_mode="lazy",
        )
        datasource = CallbackDataSourceAdapter(resolve=lambda req: bundle)
        product_sink = CallbackProductSink(
            write_manifest=lambda manifest: f"memory://{manifest.run_id}.json"
        )

        resolved = datasource.resolve(request)
        materialized = datasource.materialize(resolved)
        manifest_uri = product_sink.write_manifest(
            ProductManifest(job_id="job", run_id="run-003")
        )

        self.assertEqual(resolved.bundle_id, "bundle-001")
        self.assertTrue(materialized.is_materialized)
        self.assertEqual(manifest_uri, "memory://run-003.json")

    def test_callback_logger_adapter_emits_structured_log_events(self) -> None:
        captured = []
        logger = CallbackLoggerAdapter(emit=lambda event: captured.append(event))

        logger.bind_context("job-001", "run-004")
        logger.emit_stage_start("dispatch", "start")
        logger.emit_artifact("dispatch", "file:///artifact", "job_manifest")
        logger.emit_stage_end("dispatch", "done")

        self.assertEqual(captured[0].event_type, "bind")
        self.assertEqual(captured[1].job_id, "job-001")
        self.assertEqual(captured[2].extra["artifact_type"], "job_manifest")
        self.assertEqual(captured[3].event_type, "stage_end")


if __name__ == "__main__":
    unittest.main()
