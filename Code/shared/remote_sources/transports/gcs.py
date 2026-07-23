from __future__ import annotations

import json
import logging
from pathlib import Path

from shared.remote_sources.limits import DEFAULT_MAX_REMOTE_BYTES
from shared.remote_sources.protocol import RemoteAuth, RemoteStat
from shared.remote_sources.uri import ParsedRemoteUri, redact_uri

logger = logging.getLogger(__name__)


class GcsTransport:
    name = "gcs"
    supported_schemes = ("gs",)

    def supports(self, parsed: ParsedRemoteUri) -> bool:
        return parsed.scheme == "gs"

    def _client(self, auth: RemoteAuth):
        try:
            from google.cloud import storage  # type: ignore
            from google.oauth2 import service_account  # type: ignore
        except ImportError as exc:
            raise ValueError("google-cloud-storage is required for gs:// URIs") from exc

        sa_json = (auth.extra or {}).get("service_account_json") or auth.password
        if not sa_json:
            raise ValueError(
                "GCS credential profile requires service_account_json (store in secret/password field)"
            )
        if isinstance(sa_json, str):
            info = json.loads(sa_json)
        else:
            info = sa_json
        credentials = service_account.Credentials.from_service_account_info(info)
        project = (auth.extra or {}).get("project_id") or info.get("project_id")
        return storage.Client(project=project, credentials=credentials)

    def stat(self, parsed: ParsedRemoteUri, auth: RemoteAuth) -> RemoteStat:
        client = self._client(auth)
        bucket = client.bucket(parsed.host)
        object_name = parsed.path.lstrip("/")
        if not object_name:
            if not bucket.exists():
                raise FileNotFoundError(
                    f"GCS bucket not found or inaccessible: {parsed.host}"
                )
            return RemoteStat(path="/", size=None, is_dir=True)

        blob = bucket.blob(object_name)
        if not blob.exists():
            raise FileNotFoundError(f"GCS object not found: {redact_uri(parsed.raw)}")
        blob.reload()
        return RemoteStat(
            path=parsed.path,
            size=int(blob.size) if blob.size is not None else None,
            is_dir=False,
            mtime=blob.updated.timestamp() if blob.updated else None,
        )

    def download_to(
        self,
        parsed: ParsedRemoteUri,
        auth: RemoteAuth,
        local_path: Path,
        *,
        max_bytes: int = DEFAULT_MAX_REMOTE_BYTES,
    ) -> RemoteStat:
        client = self._client(auth)
        bucket = client.bucket(parsed.host)
        object_name = parsed.path.lstrip("/")
        if not object_name:
            raise ValueError(f"GCS URI requires object path: {redact_uri(parsed.raw)}")
        blob = bucket.blob(object_name)
        if not blob.exists():
            raise FileNotFoundError(f"GCS object not found: {redact_uri(parsed.raw)}")
        blob.reload()
        if blob.size is not None and int(blob.size) > max_bytes:
            raise ValueError(
                f"GCS object exceeds max_bytes={max_bytes}: {redact_uri(parsed.raw)}"
            )
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(local_path))
        size = local_path.stat().st_size
        if size > max_bytes:
            local_path.unlink(missing_ok=True)
            raise ValueError(f"GCS download exceeded max_bytes={max_bytes}")
        logger.info(
            "GCS downloaded %s -> %s (%s bytes)",
            redact_uri(parsed.raw),
            local_path,
            size,
        )
        return RemoteStat(path=parsed.path, size=size, is_dir=False)
