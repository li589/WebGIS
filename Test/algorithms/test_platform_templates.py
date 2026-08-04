from __future__ import annotations

import unittest
from datetime import UTC, datetime

from contracts.data import DataBundle, DataRequest
from contracts.job import JobRequest, JobResult
from contracts.product import OutputSpec, ProductManifest, ProductRef
from contracts.runtime import RegionSpec, TimeRange
from interfaces.product_sink import RasterProduct, TableProduct
from service.platform_templates import (
    PlatformDataSourceAdapterTemplate,
    PlatformLoggerAdapterTemplate,
    PlatformProductSinkTemplate,
    PlatformSchedulerAdapterTemplate,
)


def _build_request() -> JobRequest:
    return JobRequest(
        job_id="job-template-001",
        pipeline_name="workflow",
        task_type="workflow",
        time_range=TimeRange(start=datetime(2025, 1, 1), end=datetime(2025, 1, 2)),
        region=RegionSpec(kind="global", value={}),
        datasource_selection={},
        algorithm_params={},
        output_spec=OutputSpec(),
    )


class _SchedulerTemplate(PlatformSchedulerAdapterTemplate):
    def __init__(self) -> None:
        super().__init__()
        self.statuses = []
        self.completed = []

    def build_run_context(self, request: JobRequest) -> dict[str, object]:
        return {"job_id": request.job_id, "tenant": "demo"}

    def push_status(
        self, *, job_id: str, run_id: str, status: str, detail=None
    ) -> None:
        self.statuses.append((job_id, run_id, status, detail))

    def push_completion(self, result: JobResult) -> None:
        self.completed.append(result.run_id)


class _DataSourceTemplate(PlatformDataSourceAdapterTemplate):
    def resolve_bundle(self, request: DataRequest) -> DataBundle:
        return DataBundle(
            bundle_id="bundle-template-001",
            dataset_name=request.dataset_name,
            variables=request.variables,
            time_range=request.time_range,
            storage_mode=request.acquire_mode,
        )


class _LoggerTemplate(PlatformLoggerAdapterTemplate):
    def __init__(self) -> None:
        super().__init__()
        self.events = []

    def emit_platform_event(self, event) -> None:
        self.events.append(event)


class _ProductSinkTemplate(PlatformProductSinkTemplate):
    def persist_raster(self, product: RasterProduct) -> ProductRef:
        return ProductRef(
            name=product.name, type="raster", uri=product.uri, variable=product.variable
        )

    def persist_table(self, product: TableProduct) -> ProductRef:
        return ProductRef(name=product.name, type="table", uri=product.uri)

    def persist_manifest(self, manifest: ProductManifest) -> str:
        return f"memory://{manifest.run_id}.json"


class PlatformTemplateTests(unittest.TestCase):
    def test_scheduler_template_can_be_specialized(self) -> None:
        adapter = _SchedulerTemplate()
        request = _build_request()
        result = JobResult(
            job_id=request.job_id,
            run_id="run-template-001",
            status="success",
            started_at=datetime(2025, 1, 1, tzinfo=UTC),
            finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
        )

        context = adapter.get_run_context(request)
        adapter.update_status(
            request.job_id, "run-template-001", "planning", {"node_count": 1}
        )
        adapter.complete(result)

        self.assertEqual(context["tenant"], "demo")
        self.assertEqual(adapter.statuses[0][2], "planning")
        self.assertEqual(adapter.completed, ["run-template-001"])

    def test_datasource_logger_and_product_templates_can_be_specialized(self) -> None:
        request = DataRequest(
            dataset_name="demo",
            variables=["v1"],
            time_range=TimeRange(start=datetime(2025, 1, 1), end=datetime(2025, 1, 2)),
        )
        datasource = _DataSourceTemplate()
        logger = _LoggerTemplate()
        sink = _ProductSinkTemplate()

        bundle = datasource.resolve(request)
        bundle = datasource.materialize(bundle)
        logger.bind_context("job-template-001", "run-template-002")
        logger.emit_stage_start("dispatch", "start")
        raster = sink.write_raster(
            RasterProduct(name="r", uri="memory://r.tif", variable="R")
        )
        table = sink.write_table(
            TableProduct(name="t", uri="memory://t.parquet", table_type="table")
        )
        manifest_uri = sink.write_manifest(
            ProductManifest(job_id="job-template-001", run_id="run-template-002")
        )

        self.assertTrue(bundle.is_materialized)
        self.assertEqual(logger.events[1].event_type, "stage_start")
        self.assertEqual(raster.type, "raster")
        self.assertEqual(table.type, "table")
        self.assertEqual(manifest_uri, "memory://run-template-002.json")


if __name__ == "__main__":
    unittest.main()
