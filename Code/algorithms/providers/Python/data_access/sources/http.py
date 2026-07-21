from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from data_access.contracts import DataRequestV2, ResourceRef, build_resource_ref

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024  # 512 MiB


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

        Never returns a fake ``deferred`` ready state — either materializes or raises.
        """
        destination_root = Path(target_dir) if target_dir is not None else Path.cwd() / ".data" / "http_cache"
        destination_root.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256(resource.uri.encode("utf-8")).hexdigest()[:24]
        parsed = urlparse(resource.uri)
        suffix = Path(parsed.path).suffix or ".bin"
        local_path = destination_root / f"{digest}{suffix}"

        if not local_path.exists() or local_path.stat().st_size == 0:
            logger.info("Materializing HTTP resource %s -> %s", resource.uri, local_path)
            req = Request(resource.uri, headers={"User-Agent": "CGDA-DataAccess/1.0"})
            try:
                with urlopen(req, timeout=120) as resp:
                    written = 0
                    with local_path.open("wb") as out:
                        while True:
                            chunk = resp.read(1024 * 1024)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > _MAX_DOWNLOAD_BYTES:
                                local_path.unlink(missing_ok=True)
                                raise ValueError(
                                    f"HTTP materialize exceeded {_MAX_DOWNLOAD_BYTES} bytes for {resource.uri}"
                                )
                            out.write(chunk)
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                local_path.unlink(missing_ok=True)
                raise ValueError(f"HTTP materialize failed for {resource.uri}: {exc}") from exc

        staged_metadata = dict(resource.metadata)
        staged_metadata["materialization_status"] = "ready"
        staged_metadata["local_path"] = str(local_path)
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
