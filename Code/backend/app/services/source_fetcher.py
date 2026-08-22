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
from datetime import datetime, UTC
import hashlib
import http.client
import json
import logging
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, unquote

from app.core.config import settings
from app.services.object_store import object_store

if TYPE_CHECKING:
    from shared.remote_sources.access_control import AccessPolicyContext

logger = logging.getLogger(__name__)

# HTTP 抓取默认超时（秒）。提取为模块级常量便于后续配置化。
# TODO: 后续若引入 requests 库，可改用 requests.Session 复用连接池以提升抓取性能；
#       当前项目仅依赖 urllib，保持现有实现以避免新增依赖。
DEFAULT_HTTP_TIMEOUT = 60

# Range 断点续传策略（对齐 ingest/_http_resume.py 语义）：
# - 瞬时错误（网络异常 / IncompleteRead / 5xx / 429）指数退避重试，预算 3 次；
# - 协议纠正（Range 被忽略 / 416 / ETag 变化）整体重下，预算 2 次；
# - 其余 4xx 立即失败；object_store 始终只接收完整文件（.part 完成后才入库）。
HTTP_RESUME_MAX_RETRIES = 3
HTTP_RESUME_MAX_RESTARTS = 2
HTTP_RESUME_INITIAL_BACKOFF = 1.0
HTTP_RESUME_JITTER = 0.25
HTTP_RESUME_CHUNK_SIZE = 1024 * 1024
_TRANSIENT_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
_DOWNLOAD_USER_AGENT = "cgda-backend-download-service/1.0"


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


def _http_staging_dir() -> Path:
    """HTTP 断点续传暂存目录（.part + sidecar），落在统一缓存根下。"""
    root = Path(settings.cache_dir) / "http_fetch"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _parse_content_range_total(value: str | None) -> int | None:
    """解析 ``Content-Range: bytes 100-199/1234`` 尾部的总长度；``*`` 或缺失返回 None。"""
    if not value:
        return None
    tail = value.rsplit("/", 1)[-1].strip()
    if tail.isdigit():
        return int(tail)
    return None


def _read_part_sidecar(sidecar_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_part_sidecar(
    sidecar_path: Path,
    *,
    total: int | None,
    etag: str | None,
    content_type: str | None,
) -> None:
    sidecar_path.write_text(
        json.dumps(
            {"total": total, "etag": etag, "content_type": content_type},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class HttpSourceFetcher(SourceFetcher):
    """HTTP/HTTPS 源抓取器（Range 断点续传 + 退避重试）。

    下载先落到暂存 ``.part`` 文件；完成后一次性 ``put_stream`` 入库，
    object_store 保持「完整或不存在」语义。抓取中断时暂存保留，
    下次对同一 artifact_key 的抓取携带 ``Range`` 从断点继续。
    """

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
        fetched_at = datetime.now(UTC).isoformat()
        artifact_key = f"{artifact_key_prefix}/{ref_id}"
        try:
            # SSRF 校验（含重定向每跳再校验）在 _download_with_resume 的
            # safe_urlopen 内完成，避免 urlopen 默认跟随 3xx 绕过到环回。
            staging_dir = _http_staging_dir()
            digest = hashlib.sha1(artifact_key.encode("utf-8")).hexdigest()[:16]
            part_path = staging_dir / f"{digest}.part"
            sidecar_path = staging_dir / f"{digest}.json"

            content_type, total = self._download_with_resume(
                source_uri, part_path, sidecar_path
            )
            # 完整文件才入库；入库失败时暂存保留，下次跳过网络直接重传
            with open(part_path, "rb") as f:
                stored = object_store.put_stream(
                    object_key=artifact_key,
                    stream=f,
                    content_type=content_type,
                    length=total,
                    metadata={
                        "source_uri": source_uri,
                        "ref_id": ref_id,
                        "fetched_at": fetched_at,
                    },
                )
            part_path.unlink(missing_ok=True)
            sidecar_path.unlink(missing_ok=True)
            return FetchResult(
                ref_id=ref_id,
                success=True,
                artifact_key=artifact_key,
                fetched_bytes=stored.content_length,
                content_type=content_type,
                local_path=str(stored.file_path) if stored.file_path else None,
                fetched_at=fetched_at,
            )
        except Exception as exc:  # pragma: no cover - 依赖运行时网络环境
            logger.warning(
                "HTTP fetch failed for ref=%s uri=%s: %s", ref_id, source_uri, exc
            )
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error=f"HTTP fetch failed: {exc}",
                fetched_at=fetched_at,
            )

    def _download_with_resume(
        self,
        source_uri: str,
        part_path: Path,
        sidecar_path: Path,
    ) -> tuple[str, int | None]:
        """下载 source_uri 到 part_path，返回 (content_type, 总字节数)。"""
        from app.core.ssrf import default_allow_private, safe_urlopen

        state = _read_part_sidecar(sidecar_path)
        offset = part_path.stat().st_size if part_path.exists() else 0
        total_state = state.get("total")
        if isinstance(total_state, int) and total_state >= 0 and offset == total_state:
            # 上次调用已完成暂存但未入库（进程崩溃/入库失败）：跳过网络直接重传
            return (
                state.get("content_type") or "application/octet-stream",
                total_state,
            )

        retries = 0
        restarts = 0
        while True:
            offset = part_path.stat().st_size if part_path.exists() else 0
            headers = {"User-Agent": _DOWNLOAD_USER_AGENT}
            if offset > 0:
                headers["Range"] = f"bytes={offset}-"
                logger.info(
                    "HTTP fetch resuming ref download from byte %d: %s",
                    offset,
                    source_uri,
                )
            try:
                with safe_urlopen(
                    source_uri,
                    timeout=DEFAULT_HTTP_TIMEOUT,
                    headers=headers,
                    allow_private=default_allow_private(),
                ) as response:
                    (
                        content_type,
                        total,
                        mode,
                        restart,
                    ) = self._inspect_response(response, state)
                    if restart:
                        if restarts >= HTTP_RESUME_MAX_RESTARTS:
                            raise RuntimeError(
                                "origin keeps invalidating the resume state; "
                                f"giving up: {source_uri}"
                            )
                        restarts += 1
                        part_path.unlink(missing_ok=True)
                        state = {}
                        continue

                    if mode == "wb":
                        state = {}
                    with open(part_path, mode) as out_f:
                        while True:
                            chunk = response.read(HTTP_RESUME_CHUNK_SIZE)
                            if not chunk:
                                break
                            out_f.write(chunk)
                    size = part_path.stat().st_size
                    if total is not None and size > total:
                        # 服务端多发了尾部字节：按声明长度截齐
                        with open(part_path, "r+b") as f:
                            f.truncate(total)
                        size = total
                    _write_part_sidecar(
                        sidecar_path,
                        total=total,
                        etag=response.headers.get("ETag"),
                        content_type=content_type,
                    )
                    if total is None or size >= total:
                        return content_type, total if total is not None else size
                    raise http.client.IncompleteRead(size, total)
            except HTTPError as exc:
                if exc.code == 416 and offset > 0:
                    # Range 起点超出资源当前大小：暂存已过期，整体重下
                    if restarts >= HTTP_RESUME_MAX_RESTARTS:
                        raise
                    restarts += 1
                    part_path.unlink(missing_ok=True)
                    state = {}
                    continue
                if exc.code in _TRANSIENT_HTTP_CODES:
                    if retries >= HTTP_RESUME_MAX_RETRIES:
                        raise
                    retries += 1
                    self._sleep_backoff(retries)
                    continue
                raise
            except (URLError, TimeoutError, ConnectionError, http.client.HTTPException):
                if retries >= HTTP_RESUME_MAX_RETRIES:
                    raise
                retries += 1
                self._sleep_backoff(retries)
                continue

    def _inspect_response(
        self,
        response: Any,
        state: dict[str, Any],
    ) -> tuple[str, int | None, str, bool]:
        """解析响应头，返回 (content_type, total, 写入模式, 是否需要重下)。

        206 → 追加写（Range 生效）；200 → 整写（含服务端忽略 Range 的情形）。
        """
        code = getattr(response, "status", None)
        if code is None:
            getcode = getattr(response, "getcode", None)
            code = getcode() if callable(getcode) else 200
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        etag = response.headers.get("ETag")

        if code == 206:
            total = _parse_content_range_total(response.headers.get("Content-Range"))
            state_etag = state.get("etag")
            if state_etag and etag and state_etag != etag:
                # 源内容已变更：断点对应的旧字节失效，整体重下
                return content_type, None, "wb", True
            return content_type, total, "ab", False

        if code != 200:
            raise RuntimeError(f"unexpected HTTP status {code}")
        length_header = response.headers.get("Content-Length")
        total = (
            int(length_header) if length_header and length_header.isdigit() else None
        )
        # offset>0 时服务端忽略 Range 返回整文件：重置为整写模式
        return content_type, total, "wb", False

    @staticmethod
    def _sleep_backoff(retries: int) -> None:
        delay = HTTP_RESUME_INITIAL_BACKOFF * (2 ** (retries - 1))
        delay += random.uniform(0, HTTP_RESUME_JITTER * delay)
        time.sleep(delay)


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
        fetched_at = datetime.now(UTC).isoformat()
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
                content_type = response.headers.get(
                    "Content-Type", "application/octet-stream"
                )
                content_length_header = response.headers.get("Content-Length")
                content_length = (
                    int(content_length_header)
                    if content_length_header and content_length_header.isdigit()
                    else None
                )
                artifact_key = f"{artifact_key_prefix}/{ref_id}"
                # R1: Stream MinIO object directly to object_store,
                # avoiding full-in-memory read for large objects.
                stored = object_store.put_stream(
                    object_key=artifact_key,
                    stream=response,
                    content_type=content_type,
                    length=content_length,
                    metadata={
                        "source_uri": source_uri,
                        "ref_id": ref_id,
                        "fetched_at": fetched_at,
                    },
                )
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:
            logger.warning(
                "MinIO fetch failed for ref=%s uri=%s: %s", ref_id, source_uri, exc
            )
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error=f"MinIO fetch failed: {exc}",
                fetched_at=fetched_at,
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
        fetched_at = datetime.now(UTC).isoformat()
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
            # local://tiles/t.bin 的首段会被 urlparse 归入 netloc，
            # 拼回 path 头部以免丢段（G1-04 顺带修复该解析缺陷）
            if parsed.netloc:
                raw_path = parsed.netloc + unquote(parsed.path)
            elif parsed.path:
                raw_path = unquote(parsed.path)
            else:
                raw_path = source_uri[len("local://") :]
            local_path = Path(raw_path)

        # G1-04：file:// / local:// 源必须约束在 download_source_root 内，
        # 防止 source_uri 指向服务器任意路径（.env / 凭据库等）造成本地文件泄露。
        root_raw = (settings.download_source_root or "").strip()
        if root_raw:
            root_path = Path(root_raw).resolve()
            if not local_path.is_absolute():
                local_path = root_path / local_path
            # resolve() 归一化 ../ 与符号链接后再判界，防穿越与 symlink 逃逸
            local_path = local_path.resolve()
            if not local_path.is_relative_to(root_path):
                logger.warning(
                    "Local source rejected (outside download source root): %s",
                    source_uri,
                )
                return FetchResult(
                    ref_id=ref_id,
                    success=False,
                    error="Local file is outside the configured download source root",
                    fetched_at=fetched_at,
                )
        elif settings.environment == "production":
            # production fail-closed：未配置根时禁用本地文件源（对齐 BACKEND_DATA_ROOT 策略）
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error=(
                    "BACKEND_DOWNLOAD_SOURCE_ROOT is not configured; "
                    "local file sources are disabled in production"
                ),
                fetched_at=fetched_at,
            )
        else:
            logger.warning(
                "BACKEND_DOWNLOAD_SOURCE_ROOT not set; local source fetch is "
                "unconstrained (non-production only): %s",
                source_uri,
            )

        if not local_path.exists() or not local_path.is_file():
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error=f"Local file not found: {local_path}",
                fetched_at=fetched_at,
            )

        try:
            content_type = "application/octet-stream"
            suffix = local_path.suffix.lower()
            if suffix in {".json", ".geojson"}:
                content_type = "application/json"
            elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
                content_type = f"image/{suffix[1:]}"

            file_size = local_path.stat().st_size
            artifact_key = f"{artifact_key_prefix}/{ref_id}"
            # R1: Stream local file to object_store, avoiding full-in-memory read.
            with open(local_path, "rb") as f:
                stored = object_store.put_stream(
                    object_key=artifact_key,
                    stream=f,
                    content_type=content_type,
                    length=file_size,
                    metadata={
                        "source_uri": source_uri,
                        "ref_id": ref_id,
                        "fetched_at": fetched_at,
                        "origin_path": str(local_path),
                    },
                )
        except Exception as exc:
            logger.warning(
                "Local file read failed for ref=%s path=%s: %s", ref_id, local_path, exc
            )
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error=f"Local file read failed: {exc}",
                fetched_at=fetched_at,
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
        fetched_at = datetime.now(UTC).isoformat()
        try:
            from app.services.remote_auth_resolver import resolve_remote_auth
            from shared.remote_sources.download import download_remote_uri
            from shared.remote_sources.limits import get_max_remote_bytes

            auth = resolve_remote_auth(source_uri)
            cache_dir = Path(settings.cache_dir) / "remote_fetch"
            # Phase 4：构建访问策略上下文，传入 download_remote_uri 执行校验
            policy_ctx = _build_access_policy_context(source_uri)
            local_path, _stat = download_remote_uri(
                source_uri,
                auth,
                target_dir=cache_dir,
                max_bytes=get_max_remote_bytes(settings.remote_max_bytes),
                policy_context=policy_ctx,
            )
            file_size = local_path.stat().st_size
            artifact_key = f"{artifact_key_prefix}/{ref_id}"
            # R1: Stream downloaded remote file to object_store, avoiding
            # full-in-memory read for large remote files.
            with open(local_path, "rb") as f:
                stored = object_store.put_stream(
                    object_key=artifact_key,
                    stream=f,
                    content_type="application/octet-stream",
                    length=file_size,
                    metadata={
                        "source_uri": source_uri,
                        "ref_id": ref_id,
                        "fetched_at": fetched_at,
                    },
                )
        except Exception as exc:
            logger.warning(
                "Remote fetch failed for ref=%s uri=%s: %s", ref_id, source_uri, exc
            )
            return FetchResult(
                ref_id=ref_id,
                success=False,
                error=f"Remote fetch failed: {exc}",
                fetched_at=fetched_at,
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

    P0-10：demo:// 是占位数据源（不产生真实数据）。development 环境保留用于联调/
    展出演示；production 环境默认直接 fail（避免占位符静默冒充真实结果），除非显式
    设 BACKEND_DEMO_SOURCES_ENABLED=true（如展演需以 production 模式运行）。
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
        from app.core.config import settings

        if settings.environment != "development" and not settings.demo_sources_enabled:
            raise ValueError(
                "demo:// 为占位演示数据源，不产生真实数据，当前环境（"
                f"{settings.environment}）已禁用。展出演示请设 "
                "BACKEND_DEMO_SOURCES_ENABLED=true 显式开启，或使用真实数据源。"
            )
        fetched_at = datetime.now(UTC).isoformat()
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


# ── Phase 4：访问策略上下文构建 ────────────────────────────────────────────


def _build_access_policy_context(source_uri: str) -> "AccessPolicyContext | None":
    """从 source_uri 构建访问策略上下文（失败时返回 None = 跳过校验）。

    用于 RemoteProtocolSourceFetcher.fetch() 下载前注入 access_mode 校验。
    使用 try/except 包裹，确保远程源访问异常不影响主流程。
    """
    try:
        from shared.remote_sources.access_control import (
            build_policy_context_from_uri,
        )
        from app.services.remote_source_registry import get_remote_source_registry
        from app.services.remote_dataset_grants import get_remote_dataset_grants

        sources_reg = get_remote_source_registry()
        grants_reg = get_remote_dataset_grants()
        ctx = build_policy_context_from_uri(
            source_uri,
            source_registry=sources_reg,
            grants_registry=grants_reg,
        )
        return ctx
    except Exception:  # noqa: BLE001 — 访问控制注入失败不阻断下载
        logger.debug(
            "Access policy context build failed, skipping check", exc_info=True
        )
        return None


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
                        fetched_at=datetime.now(UTC).isoformat(),
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
