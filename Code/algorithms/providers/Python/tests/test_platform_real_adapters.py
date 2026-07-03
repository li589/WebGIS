from __future__ import annotations

import unittest
from datetime import UTC, datetime

from contracts.data import DataBundle, DataRequest
from contracts.event import LogEvent
from contracts.job import JobRequest, JobResult
from contracts.product import OutputSpec, ProductManifest, ProductRef
from contracts.runtime import RegionSpec, TimeRange
from interfaces.datasource import DataAsset
from interfaces.product_sink import RasterProduct, TableProduct
from service.platform_datasource_adapter import PlatformDataSourceAdapter
from service.platform_logger_adapter import PlatformLoggerAdapter
from service.platform_product_sink import PlatformProductSink
from service.platform_scheduler_adapter import PlatformSchedulerAdapter


def _build_request() -> JobRequest:
    return JobRequest(
        job_id="job-real-001",
        pipeline_name="workflow",
        task_type="workflow",
        time_range=TimeRange(start=datetime(2025, 1, 1), end=datetime(2025, 1, 2)),
        region=RegionSpec(kind="global", value={}),
        datasource_selection={},
        algorithm_params={},
        output_spec=OutputSpec(),
    )


class _FakePlatformClient:
    def __init__(self) -> None:
        self.statuses = []
        self.completions = []
        self.events = []

    def build_run_context(self, request: JobRequest) -> dict[str, object]:
        return {"trace_id": request.job_id, "platform": "demo"}

    def update_job_status(self, job_id: str, run_id: str, status: str, detail=None) -> None:
        self.statuses.append((job_id, run_id, status, detail))

    def complete_job(self, result: JobResult) -> None:
        self.completions.append(result.run_id)

    def discover_assets(self, request: DataRequest) -> list[DataAsset]:
        return [DataAsset(uri="memory://asset-001", dataset_name=request.dataset_name, variables=list(request.variables))]

    def resolve_bundle(self, request: DataRequest) -> DataBundle:
        return DataBundle(
            bundle_id="bundle-real-001",
            dataset_name=request.dataset_name,
            variables=request.variables,
            time_range=request.time_range,
            storage_mode=request.acquire_mode,
        )

    def acquire_bundle(self, bundle: DataBundle) -> DataBundle:
        bundle.metadata["acquired"] = True
        return bundle

    def materialize_bundle(self, bundle: DataBundle) -> DataBundle:
        bundle.is_materialized = True
        bundle.local_paths.append("D:/platform/bundle.mat")
        return bundle

    def emit_log_event(self, event: LogEvent) -> None:
        self.events.append(event)

    def persist_raster(self, product: RasterProduct) -> ProductRef:
        return ProductRef(name=product.name, type="platform_raster", uri=product.uri, variable=product.variable)

    def persist_table(self, product: TableProduct) -> ProductRef:
        return ProductRef(name=product.name, type="platform_table", uri=product.uri)

    def persist_manifest(self, manifest: ProductManifest) -> str:
        return f"memory://manifest/{manifest.run_id}.json"


class PlatformRealAdapterTests(unittest.TestCase):
    def test_platform_scheduler_adapter_supports_platform_client(self) -> None:
        client = _FakePlatformClient()
        adapter = PlatformSchedulerAdapter(platform_client=client)
        request = _build_request()
        result = JobResult(
            job_id=request.job_id,
            run_id="run-real-001",
            status="success",
            started_at=datetime(2025, 1, 1, tzinfo=UTC),
            finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
        )

        context = adapter.get_run_context(request)
        adapter.update_status(request.job_id, "run-real-001", "planning", {"step": 1})
        adapter.complete(result)

        self.assertEqual(context["platform"], "demo")
        self.assertEqual(client.statuses[0][2], "planning")
        self.assertEqual(client.completions, ["run-real-001"])

    def test_platform_scheduler_adapter_supports_direct_callables(self) -> None:
        statuses = []
        completed = []
        adapter = PlatformSchedulerAdapter(
            run_context_provider=lambda request: {"job_id": request.job_id, "source": "callable"},
            status_publisher=lambda job_id, run_id, status, detail=None: statuses.append((job_id, status)),
            completion_publisher=lambda result: completed.append(result.status),
        )
        request = _build_request()
        result = JobResult(
            job_id=request.job_id,
            run_id="run-real-002",
            status="success",
            started_at=datetime(2025, 1, 1, tzinfo=UTC),
            finished_at=datetime(2025, 1, 1, 0, 2, tzinfo=UTC),
        )

        context = adapter.get_run_context(request)
        adapter.update_status(request.job_id, "run-real-002", "running")
        adapter.complete(result)

        self.assertEqual(context["source"], "callable")
        self.assertEqual(statuses[0][1], "running")
        self.assertEqual(completed, ["success"])

    def test_platform_datasource_logger_and_product_adapters_support_platform_client(self) -> None:
        client = _FakePlatformClient()
        datasource = PlatformDataSourceAdapter(platform_client=client)
        logger = PlatformLoggerAdapter(platform_client=client)
        sink = PlatformProductSink(platform_client=client)
        request = DataRequest(
            dataset_name="demo",
            variables=["v1"],
            time_range=TimeRange(start=datetime(2025, 1, 1), end=datetime(2025, 1, 2)),
        )

        assets = datasource.discover(request)
        bundle = datasource.resolve(request)
        bundle = datasource.acquire(bundle)
        bundle = datasource.materialize(bundle)
        logger.bind_context("job-real-001", "run-real-003")
        logger.emit_stage_start("dispatch", "start")
        raster_ref = sink.write_raster(RasterProduct(name="r", uri="memory://r.tif", variable="R"))
        table_ref = sink.write_table(TableProduct(name="t", uri="memory://t.parquet", table_type="table"))
        manifest_uri = sink.write_manifest(ProductManifest(job_id="job-real-001", run_id="run-real-003"))

        self.assertEqual(assets[0].dataset_name, "demo")
        self.assertTrue(bundle.metadata["acquired"])
        self.assertTrue(bundle.is_materialized)
        self.assertEqual(client.events[1].event_type, "stage_start")
        self.assertEqual(raster_ref.type, "platform_raster")
        self.assertEqual(table_ref.type, "platform_table")
        self.assertEqual(manifest_uri, "memory://manifest/run-real-003.json")

    def test_platform_logger_and_product_adapters_support_direct_callables(self) -> None:
        events = []
        logger = PlatformLoggerAdapter(emit_event_fn=lambda event: events.append(event))
        sink = PlatformProductSink(
            persist_raster_fn=lambda product: ProductRef(name=product.name, type="direct_raster", uri=product.uri, variable=product.variable),
            persist_table_fn=lambda product: ProductRef(name=product.name, type="direct_table", uri=product.uri),
            persist_manifest_fn=lambda manifest: f"direct://{manifest.run_id}.json",
        )

        logger.bind_context("job-real-002", "run-real-004")
        logger.emit_artifact("dispatch", "memory://artifact", "job_manifest")
        raster_ref = sink.write_raster(RasterProduct(name="r2", uri="memory://r2.tif", variable="R2"))
        table_ref = sink.write_table(TableProduct(name="t2", uri="memory://t2.parquet", table_type="table"))
        manifest_uri = sink.write_manifest(ProductManifest(job_id="job-real-002", run_id="run-real-004"))

        self.assertEqual(events[1].event_type, "artifact")
        self.assertEqual(raster_ref.type, "direct_raster")
        self.assertEqual(table_ref.type, "direct_table")
        self.assertEqual(manifest_uri, "direct://run-real-004.json")


if __name__ == "__main__":
    unittest.main()
