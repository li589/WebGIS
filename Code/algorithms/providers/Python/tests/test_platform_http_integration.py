from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from contracts.data import DataRequest
from contracts.event import LogEvent
from contracts.job import JobRequest, JobResult
from contracts.product import OutputSpec, ProductManifest
from contracts.runtime import RegionSpec, TimeRange
from interfaces.product_sink import RasterProduct, TableProduct
from service.http_server import build_http_job_service
from service.platform_http_client import PlatformHttpClient
from service.platform_service_factory import build_platform_http_job_service


def _build_request() -> JobRequest:
    return JobRequest(
        job_id="platform-http-job-001",
        pipeline_name="workflow",
        task_type="ndvi_daily",
        time_range=TimeRange(
            start=datetime(2025, 1, 1, tzinfo=UTC),
            end=datetime(2025, 1, 2, tzinfo=UTC),
        ),
        region=RegionSpec(kind="global", value={}),
        datasource_selection={"input_dir": "D:/platform/input"},
        algorithm_params={},
        output_spec=OutputSpec(),
        module_name="ndvi_daily",
    )


class _PlatformHttpState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.authorization_headers: list[str | None] = []
        self.queued_submissions: list[dict[str, object]] = []
        self.acked_submissions: list[str] = []
        self.status_events: list[dict[str, object]] = []
        self.completed_jobs: list[dict[str, object]] = []
        self.log_events: list[dict[str, object]] = []
        self.persisted_manifests: list[dict[str, object]] = []


def _create_platform_handler(state: _PlatformHttpState):
    class PlatformHandler(BaseHTTPRequestHandler):
        server_version = "platform-http-test/0.1"

        def do_POST(self) -> None:  # noqa: N802
            payload = self._read_json()
            with state.lock:
                state.authorization_headers.append(self.headers.get("Authorization"))

            if self.path == "/api/v1/platform/submissions":
                with state.lock:
                    state.queued_submissions.append(dict(payload))
                return self._send_json({"accepted": True})

            if self.path == "/api/v1/platform/submissions/claim":
                with state.lock:
                    item = None if not state.queued_submissions else state.queued_submissions.pop(0)
                return self._send_json(item)

            if self.path == "/api/v1/platform/submissions/ack":
                with state.lock:
                    state.acked_submissions.append(str(payload["submission_id"]))
                return self._send_json({"acked": True})

            if self.path == "/api/v1/platform/run-context":
                return self._send_json({"job_id": payload["job_id"], "platform": "http"})

            if self.path == "/api/v1/platform/job-status":
                with state.lock:
                    state.status_events.append(dict(payload))
                return self._send_json({"accepted": True})

            if self.path == "/api/v1/platform/job-completions":
                with state.lock:
                    state.completed_jobs.append(dict(payload))
                return self._send_json({"accepted": True})

            if self.path == "/api/v1/platform/data-assets/discover":
                return self._send_json(
                    [
                        {
                            "uri": "https://platform.example.com/assets/demo-001",
                            "dataset_name": payload["dataset_name"],
                            "variables": list(payload.get("variables") or []),
                            "metadata": {"source": "platform-http"},
                        }
                    ]
                )

            if self.path == "/api/v1/platform/data-bundles/resolve":
                return self._send_json(
                    {
                        "bundle_id": "bundle-http-001",
                        "dataset_name": payload["dataset_name"],
                        "variables": list(payload.get("variables") or []),
                        "time_range": dict(payload["time_range"]),
                        "storage_mode": payload.get("acquire_mode") or "lazy",
                        "local_paths": [],
                        "remote_refs": ["https://platform.example.com/bundles/demo-001"],
                        "metadata": {"resolved_by": "platform-http"},
                        "is_materialized": False,
                    }
                )

            if self.path == "/api/v1/platform/data-bundles/acquire":
                response = dict(payload)
                response["metadata"] = {**dict(payload.get("metadata") or {}), "acquired": True}
                return self._send_json(response)

            if self.path == "/api/v1/platform/data-bundles/materialize":
                response = dict(payload)
                response["is_materialized"] = True
                response["local_paths"] = ["D:/platform/materialized/demo-001.mat"]
                return self._send_json(response)

            if self.path == "/api/v1/platform/log-events":
                with state.lock:
                    state.log_events.append(dict(payload))
                return self._send_json({"accepted": True})

            if self.path == "/api/v1/platform/products/raster":
                return self._send_json(
                    {
                        "name": payload["name"],
                        "type": "platform_raster",
                        "uri": payload["uri"],
                        "variable": payload["variable"],
                        "tags": {"backend": "platform-http"},
                    }
                )

            if self.path == "/api/v1/platform/products/table":
                return self._send_json(
                    {
                        "name": payload["name"],
                        "type": "platform_table",
                        "uri": payload["uri"],
                        "tags": {"backend": "platform-http"},
                    }
                )

            if self.path == "/api/v1/platform/manifests":
                with state.lock:
                    state.persisted_manifests.append(dict(payload))
                return self._send_json({"uri": f"platform://manifests/{payload['run_id']}.json"})

            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            _ = (format, args)

        def _read_json(self) -> dict[str, object]:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            return json.loads(raw_body.decode("utf-8"))

        def _send_json(self, payload: object) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return PlatformHandler


@contextmanager
def _platform_http_server():
    state = _PlatformHttpState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _create_platform_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def _patched_platform_env(base_url: str, *, token: str = "secret-token"):
    previous = {
        "MAT2PY_PLATFORM_BASE_URL": os.environ.get("MAT2PY_PLATFORM_BASE_URL"),
        "MAT2PY_PLATFORM_TOKEN": os.environ.get("MAT2PY_PLATFORM_TOKEN"),
    }
    os.environ["MAT2PY_PLATFORM_BASE_URL"] = base_url
    os.environ["MAT2PY_PLATFORM_TOKEN"] = token
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class PlatformHttpIntegrationTests(unittest.TestCase):
    def test_platform_http_client_supports_queue_and_platform_adapter_methods(self) -> None:
        with _platform_http_server() as (state, base_url):
            client = PlatformHttpClient(base_url=base_url, token="secret-token")
            request = _build_request()

            from service.job_queue import QueuedJobSubmission

            queued_submission = QueuedJobSubmission(
                submission_id="sub-http-001",
                request=request,
                enqueued_at=datetime(2025, 1, 1, tzinfo=UTC),
            )
            client.publish_submission(queued_submission)
            claimed = client.claim_submission(timeout=0.1)
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.submission_id, "sub-http-001")
            client.ack_submission(claimed)

            context = client.build_run_context(request)
            self.assertEqual(context["platform"], "http")

            client.update_job_status(request.job_id, "run-http-001", "planning", {"step": 1})
            client.complete_job(
                JobResult(
                    job_id=request.job_id,
                    run_id="run-http-001",
                    status="success",
                    started_at=datetime(2025, 1, 1, tzinfo=UTC),
                    finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
                )
            )

            data_request = DataRequest(
                dataset_name="demo_dataset",
                variables=["v1"],
                time_range=request.time_range,
            )
            assets = client.discover_assets(data_request)
            bundle = client.resolve_bundle(data_request)
            bundle = client.acquire_bundle(bundle)
            bundle = client.materialize_bundle(bundle)

            client.emit_log_event(
                LogEvent(
                    job_id=request.job_id,
                    run_id="run-http-001",
                    stage="dispatch",
                    event_type="stage_start",
                    timestamp=datetime(2025, 1, 1, tzinfo=UTC),
                    message="start",
                )
            )
            raster_ref = client.persist_raster(
                RasterProduct(name="demo_raster", uri="memory://demo.tif", variable="demo")
            )
            table_ref = client.persist_table(
                TableProduct(name="demo_table", uri="memory://demo.parquet", table_type="table")
            )
            manifest_uri = client.persist_manifest(
                ProductManifest(job_id=request.job_id, run_id="run-http-001")
            )

            self.assertEqual(assets[0].metadata["source"], "platform-http")
            self.assertTrue(bundle.metadata["acquired"])
            self.assertTrue(bundle.is_materialized)
            self.assertEqual(raster_ref.type, "platform_raster")
            self.assertEqual(table_ref.type, "platform_table")
            self.assertEqual(manifest_uri, "platform://manifests/run-http-001.json")
            self.assertEqual(state.acked_submissions, ["sub-http-001"])
            self.assertEqual(state.status_events[0]["status"], "planning")
            self.assertEqual(state.completed_jobs[0]["run_id"], "run-http-001")
            self.assertEqual(state.log_events[0]["event_type"], "stage_start")
            self.assertTrue(all(header == "Bearer secret-token" for header in state.authorization_headers))

    def test_platform_http_job_service_runs_async_job_end_to_end(self) -> None:
        workspace = tempfile.mkdtemp()

        def fake_run_job(request, scheduler_adapter, datasource_adapter, logger_adapter, product_sink=None, workspace=None):
            scheduler_adapter.get_run_context(request)
            scheduler_adapter.update_status(request.job_id, "run-http-002", "running", {"queue": "platform"})
            if product_sink is not None:
                manifest_uri = product_sink.write_manifest(
                    ProductManifest(job_id=request.job_id, run_id="run-http-002")
                )
            else:
                manifest_uri = None
            result = JobResult(
                job_id=request.job_id,
                run_id="run-http-002",
                status="success",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
                manifest_uri=manifest_uri,
            )
            scheduler_adapter.complete(result)
            return result

        with _platform_http_server() as (state, base_url):
            with _patched_platform_env(base_url):
                service, worker, _client = build_platform_http_job_service(
                    workspace=workspace,
                    run_job_fn=fake_run_job,
                    start_worker=False,
                )

                response = service.submit_job_async(_to_request_payload(_build_request()))
                self.assertEqual(response.status_code, 202)
                submission_id = response.body["submission_id"]
                self.assertEqual(len(state.queued_submissions), 1)

                processed = worker.process_next(timeout=0.01)
                self.assertTrue(processed)

                status_response = service.get_job_status(submission_id)
                self.assertEqual(status_response.status_code, 200)
                self.assertEqual(status_response.body["state"], "completed")
                self.assertEqual(status_response.body["run_id"], "run-http-002")
                self.assertEqual(status_response.body["job_result"]["status"], "success")
                self.assertEqual(status_response.body["result_dto"]["artifacts"]["manifest_uri"], "platform://manifests/run-http-002.json")
                self.assertEqual(state.acked_submissions, [submission_id])
                self.assertEqual(state.status_events[0]["status"], "running")
                self.assertEqual(state.completed_jobs[0]["run_id"], "run-http-002")
                self.assertEqual(state.persisted_manifests[0]["run_id"], "run-http-002")

    def test_http_server_builder_supports_platform_queue_backend(self) -> None:
        workspace = tempfile.mkdtemp()
        with _platform_http_server() as (_state, base_url):
            with _patched_platform_env(base_url):
                service = build_http_job_service(
                    workspace=workspace,
                    queue_backend="platform",
                    start_worker=False,
                )
                response = service.get_health_response()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.body["job_queue"], "PlatformJobQueue")
                self.assertEqual(response.body["async_job_store"], "FileAsyncJobRegistry")


def _to_request_payload(request: JobRequest) -> dict[str, object]:
    return {
        "job_id": request.job_id,
        "pipeline_name": request.pipeline_name,
        "task_type": request.task_type,
        "time_range": {
            "start": request.time_range.start.isoformat(),
            "end": request.time_range.end.isoformat(),
        },
        "region": {
            "kind": request.region.kind,
            "value": dict(request.region.value),
        },
        "datasource_selection": dict(request.datasource_selection),
        "algorithm_params": dict(request.algorithm_params),
        "output_spec": {
            "raster_format": request.output_spec.raster_format,
            "table_format": request.output_spec.table_format,
            "include_qc": request.output_spec.include_qc,
            "include_manifest": request.output_spec.include_manifest,
            "extra": dict(request.output_spec.extra),
        },
        "module_name": request.module_name,
    }


if __name__ == "__main__":
    unittest.main()
