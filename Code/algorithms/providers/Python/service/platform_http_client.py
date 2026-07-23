from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from contracts.data import DataBundle, DataRequest
from contracts.event import LogEvent
from contracts.job import JobRequest, JobResult
from contracts.product import ProductManifest, ProductRef
from contracts.runtime import TimeRange
from contracts.serialization import coerce_job_request
from interfaces.datasource import DataAsset
from interfaces.product_sink import RasterProduct, TableProduct
from service.job_queue import QueuedJobSubmission


@dataclass(frozen=True, slots=True)
class PlatformHttpRoutes:
    publish_submission_path: str = "/api/v1/platform/submissions"
    claim_submission_path: str = "/api/v1/platform/submissions/claim"
    ack_submission_path: str = "/api/v1/platform/submissions/ack"
    run_context_path: str = "/api/v1/platform/run-context"
    update_status_path: str = "/api/v1/platform/job-status"
    complete_job_path: str = "/api/v1/platform/job-completions"
    discover_assets_path: str = "/api/v1/platform/data-assets/discover"
    resolve_bundle_path: str = "/api/v1/platform/data-bundles/resolve"
    acquire_bundle_path: str = "/api/v1/platform/data-bundles/acquire"
    materialize_bundle_path: str = "/api/v1/platform/data-bundles/materialize"
    emit_log_event_path: str = "/api/v1/platform/log-events"
    persist_raster_path: str = "/api/v1/platform/products/raster"
    persist_table_path: str = "/api/v1/platform/products/table"
    persist_manifest_path: str = "/api/v1/platform/manifests"


DEFAULT_PLATFORM_HTTP_ROUTES = PlatformHttpRoutes()


class PlatformHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        timeout: float = 30.0,
        routes: PlatformHttpRoutes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")
        if not normalized_base_url:
            raise ValueError("base_url is required")
        self._base_url = normalized_base_url
        self._token = None if token is None else token.strip() or None
        self._timeout = float(timeout)
        self._routes = PlatformHttpRoutes() if routes is None else routes
        self._headers = {} if headers is None else dict(headers)

    def publish_submission(self, item: QueuedJobSubmission) -> None:
        self._post(
            self._routes.publish_submission_path, _queued_submission_to_payload(item)
        )

    def claim_submission(
        self, *, timeout: float | None = None
    ) -> QueuedJobSubmission | None:
        payload = self._post(
            self._routes.claim_submission_path,
            {} if timeout is None else {"timeout": timeout},
        )
        if payload in (None, "", {}):
            return None
        if not isinstance(payload, dict):
            raise TypeError("claim_submission response must be an object or null")
        return _queued_submission_from_payload(payload)

    def ack_submission(self, item: QueuedJobSubmission) -> None:
        self._post(
            self._routes.ack_submission_path,
            {
                "submission_id": item.submission_id,
                "enqueued_at": item.enqueued_at.isoformat(),
            },
        )

    def build_run_context(self, request: JobRequest) -> dict[str, Any]:
        payload = self._post(self._routes.run_context_path, _to_jsonable(request))
        if payload is None:
            return {"job_id": request.job_id}
        if not isinstance(payload, dict):
            raise TypeError("build_run_context response must be an object")
        return dict(payload)

    def update_job_status(
        self,
        job_id: str,
        run_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._post(
            self._routes.update_status_path,
            {
                "job_id": job_id,
                "run_id": run_id,
                "status": status,
                "detail": {} if detail is None else _to_jsonable(detail),
            },
        )

    def complete_job(self, result: JobResult) -> None:
        self._post(self._routes.complete_job_path, _to_jsonable(result))

    def discover_assets(self, request: DataRequest) -> list[DataAsset]:
        payload = self._post(self._routes.discover_assets_path, _to_jsonable(request))
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise TypeError("discover_assets response must be a list")
        return [
            _data_asset_from_payload(item) for item in payload if isinstance(item, dict)
        ]

    def resolve_bundle(self, request: DataRequest) -> DataBundle:
        payload = self._post(self._routes.resolve_bundle_path, _to_jsonable(request))
        if not isinstance(payload, dict):
            raise TypeError("resolve_bundle response must be an object")
        return _data_bundle_from_payload(payload)

    def acquire_bundle(self, bundle: DataBundle) -> DataBundle:
        payload = self._post(self._routes.acquire_bundle_path, _to_jsonable(bundle))
        if not isinstance(payload, dict):
            raise TypeError("acquire_bundle response must be an object")
        return _data_bundle_from_payload(payload)

    def materialize_bundle(self, bundle: DataBundle) -> DataBundle:
        payload = self._post(self._routes.materialize_bundle_path, _to_jsonable(bundle))
        if not isinstance(payload, dict):
            raise TypeError("materialize_bundle response must be an object")
        return _data_bundle_from_payload(payload)

    def emit_log_event(self, event: LogEvent) -> None:
        self._post(self._routes.emit_log_event_path, _to_jsonable(event))

    def persist_raster(self, product: RasterProduct) -> ProductRef:
        payload = self._post(self._routes.persist_raster_path, _to_jsonable(product))
        if not isinstance(payload, dict):
            raise TypeError("persist_raster response must be an object")
        return _product_ref_from_payload(payload)

    def persist_table(self, product: TableProduct) -> ProductRef:
        payload = self._post(self._routes.persist_table_path, _to_jsonable(product))
        if not isinstance(payload, dict):
            raise TypeError("persist_table response must be an object")
        return _product_ref_from_payload(payload)

    def persist_manifest(self, manifest: ProductManifest) -> str:
        payload = self._post(self._routes.persist_manifest_path, _to_jsonable(manifest))
        if isinstance(payload, str) and payload.strip():
            return payload
        if isinstance(payload, dict):
            uri = payload.get("uri")
            if isinstance(uri, str) and uri.strip():
                return uri
        raise TypeError(
            "persist_manifest response must be a non-empty string or an object containing uri"
        )

    def _post(self, path: str, payload: object) -> Any:
        request = Request(
            url=_join_url(self._base_url, path),
            data=json.dumps(_to_jsonable(payload), ensure_ascii=False).encode("utf-8"),
            headers=self._build_headers(),
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                body = response.read()
        except HTTPError as exc:
            body = exc.read()
            message = _decode_error_body(body)
            raise RuntimeError(
                f"Platform HTTP request failed: {exc.code} {request.full_url} {message}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"Platform HTTP request failed: {request.full_url} {exc.reason}"
            ) from exc
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return body.decode("utf-8", errors="replace")

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        }
        headers.update(self._headers)
        if self._token:
            headers.setdefault("Authorization", f"Bearer {self._token}")
        return headers


def build_platform_http_client_from_env(
    *,
    base_url: str | None = None,
    token: str | None = None,
    timeout: float | None = None,
) -> PlatformHttpClient:
    resolved_base_url = base_url or os.getenv("MAT2PY_PLATFORM_BASE_URL")
    if resolved_base_url is None or not resolved_base_url.strip():
        raise ValueError("MAT2PY_PLATFORM_BASE_URL is required for platform HTTP mode.")
    resolved_token = token if token is not None else os.getenv("MAT2PY_PLATFORM_TOKEN")
    resolved_timeout = timeout
    if resolved_timeout is None:
        timeout_text = os.getenv("MAT2PY_PLATFORM_TIMEOUT", "").strip()
        resolved_timeout = float(timeout_text) if timeout_text else 30.0
    routes = PlatformHttpRoutes(
        publish_submission_path=os.getenv(
            "MAT2PY_PLATFORM_PUBLISH_SUBMISSION_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.publish_submission_path,
        ),
        claim_submission_path=os.getenv(
            "MAT2PY_PLATFORM_CLAIM_SUBMISSION_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.claim_submission_path,
        ),
        ack_submission_path=os.getenv(
            "MAT2PY_PLATFORM_ACK_SUBMISSION_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.ack_submission_path,
        ),
        run_context_path=os.getenv(
            "MAT2PY_PLATFORM_RUN_CONTEXT_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.run_context_path,
        ),
        update_status_path=os.getenv(
            "MAT2PY_PLATFORM_UPDATE_STATUS_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.update_status_path,
        ),
        complete_job_path=os.getenv(
            "MAT2PY_PLATFORM_COMPLETE_JOB_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.complete_job_path,
        ),
        discover_assets_path=os.getenv(
            "MAT2PY_PLATFORM_DISCOVER_ASSETS_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.discover_assets_path,
        ),
        resolve_bundle_path=os.getenv(
            "MAT2PY_PLATFORM_RESOLVE_BUNDLE_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.resolve_bundle_path,
        ),
        acquire_bundle_path=os.getenv(
            "MAT2PY_PLATFORM_ACQUIRE_BUNDLE_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.acquire_bundle_path,
        ),
        materialize_bundle_path=os.getenv(
            "MAT2PY_PLATFORM_MATERIALIZE_BUNDLE_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.materialize_bundle_path,
        ),
        emit_log_event_path=os.getenv(
            "MAT2PY_PLATFORM_EMIT_LOG_EVENT_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.emit_log_event_path,
        ),
        persist_raster_path=os.getenv(
            "MAT2PY_PLATFORM_PERSIST_RASTER_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.persist_raster_path,
        ),
        persist_table_path=os.getenv(
            "MAT2PY_PLATFORM_PERSIST_TABLE_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.persist_table_path,
        ),
        persist_manifest_path=os.getenv(
            "MAT2PY_PLATFORM_PERSIST_MANIFEST_PATH",
            DEFAULT_PLATFORM_HTTP_ROUTES.persist_manifest_path,
        ),
    )
    return PlatformHttpClient(
        base_url=resolved_base_url,
        token=resolved_token,
        timeout=float(resolved_timeout),
        routes=routes,
    )


def _join_url(base_url: str, path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return urljoin(f"{base_url}/", normalized_path.lstrip("/"))


def _decode_error_body(payload: bytes) -> str:
    if not payload:
        return ""
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return payload.decode("utf-8", errors="replace")
    if isinstance(decoded, dict):
        for key in ("developer_message", "message", "error", "detail"):
            value = decoded.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(decoded)


def _queued_submission_to_payload(item: QueuedJobSubmission) -> dict[str, Any]:
    return {
        "submission_id": item.submission_id,
        "request": _to_jsonable(item.request),
        "enqueued_at": item.enqueued_at.isoformat(),
    }


def _queued_submission_from_payload(payload: dict[str, Any]) -> QueuedJobSubmission:
    return QueuedJobSubmission(
        submission_id=str(payload["submission_id"]),
        request=coerce_job_request(payload["request"]),
        enqueued_at=_parse_datetime(payload["enqueued_at"]),
    )


def _data_asset_from_payload(payload: dict[str, Any]) -> DataAsset:
    return DataAsset(
        uri=str(payload["uri"]),
        dataset_name=str(payload["dataset_name"]),
        variables=[str(item) for item in payload.get("variables") or []],
        metadata=dict(payload.get("metadata") or {}),
    )


def _data_bundle_from_payload(payload: dict[str, Any]) -> DataBundle:
    return DataBundle(
        bundle_id=str(payload["bundle_id"]),
        dataset_name=str(payload["dataset_name"]),
        variables=[str(item) for item in payload.get("variables") or []],
        time_range=_time_range_from_payload(payload["time_range"]),
        storage_mode=str(payload["storage_mode"]),
        local_paths=[str(item) for item in payload.get("local_paths") or []],
        remote_refs=[str(item) for item in payload.get("remote_refs") or []],
        metadata=dict(payload.get("metadata") or {}),
        is_materialized=bool(payload.get("is_materialized", False)),
    )


def _product_ref_from_payload(payload: dict[str, Any]) -> ProductRef:
    return ProductRef(
        name=str(payload["name"]),
        type=str(payload["type"]),
        uri=str(payload["uri"]),
        variable=None if payload.get("variable") is None else str(payload["variable"]),
        tags={
            str(key): str(value)
            for key, value in dict(payload.get("tags") or {}).items()
        },
    )


def _time_range_from_payload(payload: object) -> TimeRange:
    if not isinstance(payload, dict):
        raise TypeError("time_range payload must be an object")
    return TimeRange(
        start=_parse_datetime(payload["start"]),
        end=_parse_datetime(payload["end"]),
        step=None if payload.get("step") is None else str(payload["step"]),
    )


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("datetime payload must be a string")
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    return value
