"""下载链真实抓取器。

把 download_service 中 `demo://snapshots/...` 占位 source_uri 替换为真实抓取：
- http(s):// → HTTP 下载
- minio://bucket/key → MinIO 对象拉取
- file:///path 或 local://path → 本地文件复制

抓取后的字节通过 object_store 持久化为 artifact，返回 FetchResult 供 manifest 引用。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, unquote

from app.core.config import settings
from app.services.object_store import object_store

logger = logging.getLogger(__name__)

# HTTP 抓取默认超时（秒）。提取为模块级常量便于后续配置化。
# TODO: 后续若引入 requests 库，可改用 requests.Session 复用连接池以提升抓取性能；
#       当前项目仅依赖 urllib，保持现有实现以避免新增依赖。
DEFAULT_HTTP_TIMEOUT = 60


@dataclass
class FetchResult:
    """单个 source_ref 的抓取结果。"""

    ref_id: str
    success: bool
    artifact_key: str | None = None
    fetched_bytes: int = 0
    content_type: str | None = None
    local_path: str | None = None
    error: str | None = None
    fetched_at: str = ""


class SourceFetcher(ABC):
    """抓取器抽象基类。"""

    @abstractmethod
    def supports(self, source_uri: str) -> bool:
        """判断是否支持该 source_uri scheme。"""
        ...

    @abstractmethod
    def fetch(
        self,
        *,
        ref_id: str,
        source_uri: str,
        artifact_key_prefix: str,
    ) -> FetchResult:
        """抓取 source_uri 指向的资源，返回 FetchResult。"""
        ...


class HttpSourceFetcher(SourceFetcher):
    """HTTP/HTTPS 源抓取器。"""

    def supports(self, source_uri: str) -> bool:
        parsed = urlparse(source_uri)
        return parsed.scheme in {"http", "https"}

    def fetch(
        self,
        *,
        ref_id: str,
        source_uri: str,
        artifact_key_prefix: str,
    ) -> FetchResult:
        fetched_at = datetime.now(timezone.utc).isoformat()
        try:
            import urllib.request

            req = urllib.request.Request(
                source_uri,
                headers={"User-Agent": "cgda-backend-download-service/1.0"},
            )
            with urllib.request.urlopen(req, timeout=DEFAULT_HTTP_TIMEOUT) as response:  # noqa: S310 - 源 URL 由配置或 layer catalog 提供
                data = response.read()
                content_type = response.headers.get("Content-Type", "application/octet-stream")
        except Exception as exc:  # pragma: no cover - 依赖运行时网络环境
            logger.warning("HTTP fetch failed for ref=%s uri=%s: %s", ref_id, source_uri, exc)
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error=f"HTTP fetch failed: {exc}",
                fetched_at=fetched_at,
            )

        artifact_key = f"{artifact_key_prefix}/{ref_id}"
        stored = object_store.put_bytes(
            object_key=artifact_key,
            data=data,
            content_type=content_type,
            metadata={
                "source_uri": source_uri,
                "ref_id": ref_id,
                "fetched_at": fetched_at,
            },
        )
        return FetchResult(
            ref_id=ref_id,
            success=True,
            artifact_key=artifact_key,
            fetched_bytes=stored.content_length,
            content_type=content_type,
            local_path=str(stored.file_path) if stored.file_path else None,
            fetched_at=fetched_at,
        )


class MinioSourceFetcher(SourceFetcher):
    """MinIO 源抓取器，source_uri 格式：minio://bucket/key。"""

    def supports(self, source_uri: str) -> bool:
        parsed = urlparse(source_uri)
        # Align with Python MinioSource: accept both minio:// and s3://
        return parsed.scheme in {"minio", "s3"}

    def fetch(
        self,
        *,
        ref_id: str,
        source_uri: str,
        artifact_key_prefix: str,
    ) -> FetchResult:
        fetched_at = datetime.now(timezone.utc).isoformat()
        try:
            from minio import Minio  # type: ignore[import-not-found]
        except ImportError:
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error="MinIO dependency is not installed.",
                fetched_at=fetched_at,
            )

        parsed = urlparse(source_uri)
        bucket = parsed.netloc
        object_key = unquote(parsed.path.lstrip("/"))
        if not bucket or not object_key:
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error=f"Invalid minio uri: {source_uri}",
                fetched_at=fetched_at,
            )

        try:
            client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            response = client.get_object(bucket, object_key)
            try:
                data = response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:  # pragma: no cover - 依赖运行时 MinIO 环境
            logger.warning("MinIO fetch failed for ref=%s uri=%s: %s", ref_id, source_uri, exc)
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error=f"MinIO fetch failed: {exc}",
                fetched_at=fetched_at,
            )

        content_type = response.headers.get("Content-Type", "application/octet-stream")
        artifact_key = f"{artifact_key_prefix}/{ref_id}"
        stored = object_store.put_bytes(
            object_key=artifact_key,
            data=data,
            content_type=content_type,
            metadata={
                "source_uri": source_uri,
                "ref_id": ref_id,
                "fetched_at": fetched_at,
            },
        )
        return FetchResult(
            ref_id=ref_id,
            success=True,
            artifact_key=artifact_key,
            fetched_bytes=stored.content_length,
            content_type=content_type,
            local_path=str(stored.file_path) if stored.file_path else None,
            fetched_at=fetched_at,
        )


class LocalFileSourceFetcher(SourceFetcher):
    """本地文件源抓取器，source_uri 格式：file:///path 或 local://path。"""

    def supports(self, source_uri: str) -> bool:
        parsed = urlparse(source_uri)
        return parsed.scheme in {"file", "local"}

    def fetch(
        self,
        *,
        ref_id: str,
        source_uri: str,
        artifact_key_prefix: str,
    ) -> FetchResult:
        fetched_at = datetime.now(timezone.utc).isoformat()
        parsed = urlparse(source_uri)
        # file:///C:/path → C:/path；file:///path → /path
        # local://path → path（相对或绝对）
        if parsed.scheme == "file":
            # Windows: file:///C:/foo/bar → path=/C:/foo/bar，需去掉前导 /
            raw_path = unquote(parsed.path)
            if len(raw_path) > 2 and raw_path[0] == "/" and raw_path[2] == ":":
                # /C:/foo/bar → C:/foo/bar
                local_path = Path(raw_path[1:])
            else:
                local_path = Path(raw_path)
        else:
            local_path = Path(unquote(parsed.path) if parsed.path else source_uri[len("local://"):])

        if not local_path.exists() or not local_path.is_file():
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error=f"Local file not found: {local_path}",
                fetched_at=fetched_at,
            )

        try:
            data = local_path.read_bytes()
        except Exception as exc:  # pragma: no cover - 依赖运行时文件系统
            logger.warning("Local file read failed for ref=%s path=%s: %s", ref_id, local_path, exc)
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error=f"Local file read failed: {exc}",
                fetched_at=fetched_at,
            )

        content_type = "application/octet-stream"
        suffix = local_path.suffix.lower()
        if suffix in {".json", ".geojson"}:
            content_type = "application/json"
        elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
            content_type = f"image/{suffix[1:]}"

        artifact_key = f"{artifact_key_prefix}/{ref_id}"
        stored = object_store.put_bytes(
            object_key=artifact_key,
            data=data,
            content_type=content_type,
            metadata={
                "source_uri": source_uri,
                "ref_id": ref_id,
                "fetched_at": fetched_at,
                "origin_path": str(local_path),
            },
        )
        return FetchResult(
            ref_id=ref_id,
            success=True,
            artifact_key=artifact_key,
            fetched_bytes=stored.content_length,
            content_type=content_type,
            local_path=str(stored.file_path) if stored.file_path else None,
            fetched_at=fetched_at,
        )


class RemoteProtocolSourceFetcher(SourceFetcher):
    """sftp/smb/ftp/ftps/gs 抓取器，委托 shared.remote_sources + 凭证库。"""

    _SCHEMES = frozenset({"sftp", "smb", "ftp", "ftps", "gs", "gcs"})

    def supports(self, source_uri: str) -> bool:
        scheme = urlparse(source_uri).scheme.lower()
        if scheme == "gcs":
            scheme = "gs"
        return scheme in self._SCHEMES

    def fetch(
        self,
        *,
        ref_id: str,
        source_uri: str,
        artifact_key_prefix: str,
    ) -> FetchResult:
        fetched_at = datetime.now(timezone.utc).isoformat()
        try:
            from app.services.remote_auth_resolver import resolve_remote_auth
            from shared.remote_sources.download import download_remote_uri
            from shared.remote_sources.limits import get_max_remote_bytes

            auth = resolve_remote_auth(source_uri)
            cache_dir = Path(settings.cache_dir) / "remote_fetch"
            local_path, _stat = download_remote_uri(
                source_uri,
                auth,
                target_dir=cache_dir,
                max_bytes=get_max_remote_bytes(settings.remote_max_bytes),
            )
            data = local_path.read_bytes()
        except Exception as exc:
            logger.warning("Remote fetch failed for ref=%s uri=%s: %s", ref_id, source_uri, exc)
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error=f"Remote fetch failed: {exc}",
                fetched_at=fetched_at,
            )

        artifact_key = f"{artifact_key_prefix}/{ref_id}"
        stored = object_store.put_bytes(
            object_key=artifact_key,
            data=data,
            content_type="application/octet-stream",
            metadata={
                "source_uri": source_uri,
                "ref_id": ref_id,
                "fetched_at": fetched_at,
            },
        )
        return FetchResult(
            ref_id=ref_id,
            success=True,
            artifact_key=artifact_key,
            fetched_bytes=stored.content_length,
            content_type="application/octet-stream",
            local_path=str(stored.file_path) if stored.file_path else None,
            fetched_at=fetched_at,
        )


class DemoSourceFetcher(SourceFetcher):
    """demo:// scheme 兼容抓取器。

    为保持 legacy/demo 下载链路可继续联调，demo:// scheme 仍然走兼容成功路径，
    但只会生成最小的 compat artifact，确保 manifest 始终持有稳定的 resource_key。
    """

    def supports(self, source_uri: str) -> bool:
        parsed = urlparse(source_uri)
        return parsed.scheme == "demo"

    def fetch(
        self,
        *,
        ref_id: str,
        source_uri: str,
        artifact_key_prefix: str,
    ) -> FetchResult:
        fetched_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "ref_id": ref_id,
            "source_uri": source_uri,
            "note": "legacy/demo compatibility artifact; no production data fetched",
            "compatibility_mode": "legacy-demo",
            "fetched_at": fetched_at,
        }
        data = __import__("json").dumps(payload, ensure_ascii=False).encode("utf-8")
        artifact_key = f"{artifact_key_prefix}/{ref_id}"
        stored = object_store.put_bytes(
            object_key=artifact_key,
            data=data,
            content_type="application/json",
            metadata={
                "source_uri": source_uri,
                "ref_id": ref_id,
                "fetched_at": fetched_at,
                "demo": True,
                "compatibility_mode": "legacy-demo",
                "artifact_role": "compat-placeholder",
            },
        )
        return FetchResult(
            ref_id=ref_id,
            success=True,
            artifact_key=artifact_key,
            fetched_bytes=stored.content_length,
            content_type="application/json",
            local_path=str(stored.file_path) if stored.file_path else None,
            fetched_at=fetched_at,
        )


class SourceFetcherRegistry:
    """抓取器注册表，按 scheme 路由到对应 fetcher。"""

    def __init__(self) -> None:
        self._fetchers: list[SourceFetcher] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        self._fetchers = [
            HttpSourceFetcher(),
            MinioSourceFetcher(),
            RemoteProtocolSourceFetcher(),
            LocalFileSourceFetcher(),
            DemoSourceFetcher(),
        ]

    def register(self, fetcher: SourceFetcher) -> None:
        """注册自定义抓取器（插入到链首，优先匹配）。"""
        self._fetchers.insert(0, fetcher)

    def resolve(self, source_uri: str) -> SourceFetcher:
        """根据 source_uri 的 scheme 解析到对应 fetcher。"""
        for fetcher in self._fetchers:
            if fetcher.supports(source_uri):
                return fetcher
        raise ValueError(f"Unsupported source_uri scheme: {source_uri}")

    def fetch(
        self,
        *,
        ref_id: str,
        source_uri: str,
        artifact_key_prefix: str,
    ) -> FetchResult:
        """抓取单个 source_ref。"""
        fetcher = self.resolve(source_uri)
        return fetcher.fetch(
            ref_id=ref_id,
            source_uri=source_uri,
            artifact_key_prefix=artifact_key_prefix,
        )

    def fetch_many(
        self,
        *,
        source_refs: list[dict[str, Any]],
        artifact_key_prefix: str,
    ) -> list[FetchResult]:
        """批量抓取，单个失败不影响其他 source。"""
        results: list[FetchResult] = []
        for ref in source_refs:
            ref_id = str(ref.get("ref_id", "unknown"))
            source_uri = str(ref.get("source_uri", ""))
            if not source_uri:
                results.append(
                    FetchResult(
                        ref_id=ref_id,
                        success=False,
                        error="source_uri is empty",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
                continue
            results.append(
                self.fetch(
                    ref_id=ref_id,
                    source_uri=source_uri,
                    artifact_key_prefix=artifact_key_prefix,
                )
            )
        return results


# 单例
source_fetcher_registry = SourceFetcherRegistry()
