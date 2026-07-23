from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from data_access.contracts import DataRequestV2, ResourceRef, build_resource_ref

logger = logging.getLogger(__name__)

_DEFAULT_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024  # 512 MiB


def _max_download_bytes(metadata: dict[str, object] | None = None) -> int:
    if metadata:
        raw = metadata.get("max_bytes")
        if raw is not None:
            try:
                value = int(raw)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                pass
    env = os.getenv("BACKEND_REMOTE_MAX_BYTES", "").strip()
    if env:
        try:
            value = int(env)
            if value > 0:
                return value
        except ValueError:
            pass
    return _DEFAULT_MAX_DOWNLOAD_BYTES


def _timeout_seconds(metadata: dict[str, object] | None = None) -> float:
    if metadata and metadata.get("timeout") is not None:
        try:
            return max(1.0, float(metadata["timeout"]))
        except (TypeError, ValueError):
            pass
    return 120.0


def _headers_digest(headers: dict[str, str]) -> str:
    if not headers:
        return ""
    # Exclude conditional / cache-control request headers from digest identity
    skip = {"if-none-match", "if-modified-since", "user-agent"}
    items = sorted(
        (k.lower(), v) for k, v in headers.items() if k.lower() not in skip and v
    )
    if not items:
        return ""
    return hashlib.sha256(
        json.dumps(items, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


def build_http_cache_key(uri: str, headers: dict[str, str] | None = None) -> str:
    digest = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:24]
    hdr = _headers_digest(headers or {})
    if hdr:
        return f"{digest}_{hdr}"
    return digest


def _meta_sidecars(local_path: Path) -> Path:
    return local_path.with_suffix(local_path.suffix + ".httpmeta.json")


def _load_sidecar(local_path: Path) -> dict[str, str]:
    meta_path = _meta_sidecars(local_path)
    if not meta_path.is_file():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return (
            {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        )
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sidecar(local_path: Path, payload: dict[str, str]) -> None:
    meta_path = _meta_sidecars(local_path)
    try:
        meta_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("Failed to write HTTP cache sidecar %s: %s", meta_path, exc)


class HttpSource:
    name = "http"
    supported_schemes = ("http", "https")

    def can_handle(self, uri: str) -> bool:
        parsed = urlparse(uri)
        return parsed.scheme.lower() in {"http", "https"}

    def locate(
        self,
        uri: str,
        *,
        request: DataRequestV2 | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ResourceRef:
        _ = request
        parsed = urlparse(uri)
        return build_resource_ref(
            uri=uri,
            source_kind="online",
            storage_backend=parsed.scheme.lower(),
            metadata=dict(metadata or {}),
        )

    def materialize(
        self,
        resource: ResourceRef,
        *,
        target_dir: Path | None = None,
    ) -> ResourceRef:
        """Download remote HTTP(S) resource to a local cache path.

        Honours ``metadata["http_headers"]``, optional ``timeout`` / ``max_bytes``,
        and ``force_refresh``. Uses ETag / Last-Modified sidecars for conditional GET.
        Never returns a fake ``deferred`` ready state — either materializes or raises.
        """
        destination_root = (
            Path(target_dir)
            if target_dir is not None
            else Path.cwd() / ".data" / "http_cache"
        )
        destination_root.mkdir(parents=True, exist_ok=True)

        meta = dict(resource.metadata or {})
        raw_headers = meta.get("http_headers")
        extra_headers: dict[str, str] = {}
        if isinstance(raw_headers, dict):
            extra_headers = {
                str(k): str(v)
                for k, v in raw_headers.items()
                if str(k).strip() and str(v)
            }

        force_refresh = bool(meta.get("force_refresh"))
        cache_key = build_http_cache_key(resource.uri, extra_headers)
        parsed = urlparse(resource.uri)
        suffix = Path(parsed.path).suffix or ".bin"
        local_path = destination_root / f"{cache_key}{suffix}"

        sidecar = _load_sidecar(local_path)
        cache_hit = False

        if local_path.exists() and local_path.stat().st_size > 0 and not force_refresh:
            # Conditional revalidation when we have validators
            if sidecar.get("etag") or sidecar.get("last_modified"):
                try:
                    cache_hit = self._conditional_revalidate(
                        resource.uri,
                        local_path,
                        extra_headers=extra_headers,
                        sidecar=sidecar,
                        meta=meta,
                    )
                except ValueError:
                    # Fall through to full download on revalidation failure
                    cache_hit = False
            else:
                cache_hit = True

        if not cache_hit:
            logger.info(
                "Materializing HTTP resource %s -> %s", resource.uri, local_path
            )
            self._download(
                resource.uri,
                local_path,
                extra_headers=extra_headers,
                meta=meta,
            )

        staged_metadata = dict(resource.metadata)
        staged_metadata["materialization_status"] = "ready"
        staged_metadata["local_path"] = str(local_path)
        staged_metadata["cache_hit"] = cache_hit
        staged_metadata["cache_key"] = cache_key
        if target_dir is not None:
            staged_metadata["target_dir"] = str(target_dir)

        return build_resource_ref(
            uri=local_path.as_uri(),
            source_kind=resource.source_kind,
            format=resource.format,
            logical_type=resource.logical_type,
            storage_backend="local",
            local_path=str(local_path),
            metadata=staged_metadata,
        )

    def _merge_request_headers(
        self,
        extra_headers: dict[str, str],
        *,
        conditional: dict[str, str] | None = None,
    ) -> dict[str, str]:
        headers = {"User-Agent": "CGDA-DataAccess/1.0"}
        headers.update(extra_headers)
        if conditional:
            headers.update(conditional)
        return headers

    def _conditional_revalidate(
        self,
        uri: str,
        local_path: Path,
        *,
        extra_headers: dict[str, str],
        sidecar: dict[str, str],
        meta: dict[str, object],
    ) -> bool:
        conditional: dict[str, str] = {}
        if sidecar.get("etag"):
            conditional["If-None-Match"] = sidecar["etag"]
        if sidecar.get("last_modified"):
            conditional["If-Modified-Since"] = sidecar["last_modified"]
        headers = self._merge_request_headers(extra_headers, conditional=conditional)
        req = Request(uri, headers=headers)
        timeout = _timeout_seconds(meta)
        try:
            with urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                if int(status) == 304:
                    return True
                # Unexpected 200 with body — treat as full refresh
                self._write_response_body(resp, local_path, meta)
                self._update_sidecar_from_response(local_path, resp)
                return False
        except HTTPError as exc:
            if exc.code == 304:
                return True
            raise ValueError(f"HTTP revalidate failed for {uri}: {exc}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ValueError(f"HTTP revalidate failed for {uri}: {exc}") from exc

    def _download(
        self,
        uri: str,
        local_path: Path,
        *,
        extra_headers: dict[str, str],
        meta: dict[str, object],
    ) -> None:
        headers = self._merge_request_headers(extra_headers)
        req = Request(uri, headers=headers)
        timeout = _timeout_seconds(meta)
        try:
            with urlopen(req, timeout=timeout) as resp:
                self._write_response_body(resp, local_path, meta)
                self._update_sidecar_from_response(local_path, resp)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            local_path.unlink(missing_ok=True)
            _meta_sidecars(local_path).unlink(missing_ok=True)
            raise ValueError(f"HTTP materialize failed for {uri}: {exc}") from exc

    def _write_response_body(
        self, resp, local_path: Path, meta: dict[str, object]
    ) -> None:
        max_bytes = _max_download_bytes(meta)
        written = 0
        with local_path.open("wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    local_path.unlink(missing_ok=True)
                    raise ValueError(
                        f"HTTP materialize exceeded {max_bytes} bytes for {getattr(resp, 'url', local_path)}"
                    )
                out.write(chunk)

    def _update_sidecar_from_response(self, local_path: Path, resp) -> None:
        payload: dict[str, str] = {}
        etag = resp.headers.get("ETag") or resp.headers.get("etag")
        last_mod = resp.headers.get("Last-Modified") or resp.headers.get(
            "last-modified"
        )
        if etag:
            payload["etag"] = str(etag)
        if last_mod:
            payload["last_modified"] = str(last_mod)
        if payload:
            _save_sidecar(local_path, payload)
