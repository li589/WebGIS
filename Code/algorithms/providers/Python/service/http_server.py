from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from service.job_api import (
    JobService,
    ServiceResponse,
    build_local_job_service,
    build_local_persistent_job_service,
)
from service.job_queue import FileJobQueue
from service.platform_service_factory import build_platform_http_job_service


def create_handler(job_service: JobService):
    class JobApiHandler(BaseHTTPRequestHandler):
        server_version = "mat2py-job-api/0.1"

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/health":
                self._send_response(job_service.get_health_response())
                return
            if path == "/schemas/job-request":
                self._send_response(job_service.get_job_request_schema_response())
                return
            if path == "/schemas/workflow-definition":
                self._send_response(
                    job_service.get_workflow_definition_schema_response()
                )
                return
            if path == "/api/v1/modules":
                self._send_response(job_service.list_modules_response())
                return
            if path == "/api/v1/workflows":
                self._send_response(job_service.list_workflows_response())
                return
            if path.startswith("/api/v1/modules/"):
                module_name = path.removeprefix("/api/v1/modules/").strip("/")
                if module_name:
                    self._send_response(
                        job_service.describe_module_response(module_name)
                    )
                    return
            if path.startswith("/api/v1/workflows/"):
                workflow_path = path.removeprefix("/api/v1/workflows/").strip("/")
                if workflow_path.endswith("/panel-schema"):
                    workflow_name = workflow_path.removesuffix("/panel-schema").strip(
                        "/"
                    )
                    if workflow_name:
                        self._send_response(
                            job_service.get_workflow_panel_schema_response(
                                workflow_name
                            )
                        )
                        return
                if workflow_path.endswith("/ui-schema"):
                    workflow_name = workflow_path.removesuffix("/ui-schema").strip("/")
                    if workflow_name:
                        self._send_response(
                            job_service.get_workflow_ui_schema_response(workflow_name)
                        )
                        return
                if workflow_path:
                    self._send_response(
                        job_service.describe_workflow_response(workflow_path)
                    )
                    return
            if path.startswith("/jobs/"):
                submission_id = path.removeprefix("/jobs/").strip("/")
                if submission_id:
                    self._send_response(job_service.get_job_status(submission_id))
                    return
            self._send_response(_not_found_response(path))

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            raw_body = self._read_request_body()
            if raw_body is None:
                return
            if path == "/jobs":
                self._send_response(job_service.submit_job(raw_body))
                return
            if path == "/jobs/async":
                self._send_response(job_service.submit_job_async(raw_body))
                return
            if path == "/jobs/validate":
                self._send_response(job_service.validate_job(raw_body))
                return
            self._send_response(_not_found_response(path))

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            _ = (format, args)

        def _read_request_body(self) -> str | None:
            length_header = self.headers.get("Content-Length", "0")
            try:
                content_length = int(length_header)
            except ValueError:
                self._send_response(
                    ServiceResponse(
                        status_code=400,
                        body={
                            "error_type": "invalid_http_request",
                            "error_code": "invalid_content_length",
                            "http_status": 400,
                            "retryable": False,
                            "user_message": "HTTP 请求头不合法。",
                            "developer_message": "Content-Length must be an integer.",
                        },
                    )
                )
                return None

            payload_bytes = (
                self.rfile.read(content_length) if content_length > 0 else b""
            )
            try:
                return payload_bytes.decode("utf-8")
            except UnicodeDecodeError:
                self._send_response(
                    ServiceResponse(
                        status_code=400,
                        body={
                            "error_type": "invalid_http_request",
                            "error_code": "request_body_not_utf8",
                            "http_status": 400,
                            "retryable": False,
                            "user_message": "请求体编码不正确。",
                            "developer_message": "HTTP request body must be valid UTF-8 text.",
                        },
                    )
                )
                return None

        def _send_response(self, response: ServiceResponse) -> None:
            payload = _encode_json_bytes(response.body)
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return JobApiHandler


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    job_service: JobService | None = None,
) -> ThreadingHTTPServer:
    resolved_service = job_service or build_local_job_service()
    return ThreadingHTTPServer((host, port), create_handler(resolved_service))


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    workspace: str | None = None,
    queue_backend: str = "memory",
    persistent_state: bool = False,
    start_worker: bool = True,
) -> None:
    server = create_server(
        host=host,
        port=port,
        job_service=build_http_job_service(
            workspace=workspace,
            queue_backend=queue_backend,
            persistent_state=persistent_state,
            start_worker=start_worker,
        ),
    )
    with server:
        print(f"mat2py job API listening on http://{host}:{port}")
        server.serve_forever()


def build_http_job_service(
    *,
    workspace: str | None = None,
    queue_backend: str = "memory",
    persistent_state: bool = False,
    start_worker: bool = True,
) -> JobService:
    resolved_workspace = None if workspace is None else Path(workspace)
    if queue_backend not in {"memory", "file", "platform"}:
        raise ValueError(f"Unsupported queue backend: {queue_backend}")
    if queue_backend == "platform":
        if resolved_workspace is None:
            raise ValueError("workspace is required when queue_backend='platform'.")
        service, _worker, _platform_client = build_platform_http_job_service(
            workspace=resolved_workspace,
            start_worker=start_worker,
        )
        return service
    if queue_backend == "memory":
        if persistent_state:
            if resolved_workspace is None:
                raise ValueError(
                    "workspace is required when persistent_state is enabled."
                )
            return build_local_persistent_job_service(
                workspace=resolved_workspace,
                start_worker=start_worker,
            )
        return build_local_job_service(
            workspace=resolved_workspace,
            start_worker=start_worker,
        )
    if resolved_workspace is None:
        raise ValueError("workspace is required when queue_backend='file'.")
    file_queue = FileJobQueue(resolved_workspace / "service_state" / "queue")
    return build_local_persistent_job_service(
        workspace=resolved_workspace,
        job_queue=file_queue,
        start_worker=start_worker,
    )


def _not_found_response(path: str) -> ServiceResponse:
    return ServiceResponse(
        status_code=404,
        body={
            "error_type": "not_found",
            "error_code": "route_not_found",
            "http_status": 404,
            "retryable": False,
            "user_message": "请求的接口不存在。",
            "developer_message": f"Unsupported route: {path}",
        },
    )


def _encode_json_bytes(payload: dict[str, Any]) -> bytes:
    import json

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the mat2py minimal HTTP job API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--workspace", default=None)
    parser.add_argument(
        "--queue-backend", choices=("memory", "file", "platform"), default="memory"
    )
    parser.add_argument("--persistent-state", action="store_true")
    parser.add_argument("--no-worker", action="store_true")
    return parser


if __name__ == "__main__":
    options = _build_parser().parse_args()
    serve(
        host=options.host,
        port=options.port,
        workspace=options.workspace,
        queue_backend=options.queue_backend,
        persistent_state=options.persistent_state,
        start_worker=not options.no_worker,
    )
