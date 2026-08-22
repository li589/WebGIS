from __future__ import annotations

import hashlib
import json
import logging
import os
import ssl
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from data_access.contracts import DataRequestV2, ResourceRef, build_resource_ref
from path_utils import local_path_to_uri

logger = logging.getLogger(__name__)

_DEFAULT_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024  # 512 MiB
# NSMC 门户（satellite.nsmc.org.cn）使用内部自签 CA 签发证书，公共信任库
# 无法验证（SSL: self-signed certificate in certificate chain）。仅对显式
# 域名放宽验证，其余 HTTPS 一律保持严格校验；空字符串可恢复全严格。
_DEFAULT_INSECURE_HOSTS = "satellite.nsmc.org.cn"


def _insecure_hosts() -> set[str]:
    raw = os.getenv("CGDA_HTTP_INSECURE_HOSTS")
    if raw is None:
        raw = _DEFAULT_INSECURE_HOSTS
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _insecure_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _ssl_verify_disabled(meta: dict[str, object] | None) -> bool:
    if not meta:
        return False
    raw = str(meta.get("ssl_verify", "1")).strip().lower()
    return raw in {"0", "false", "no", "off"}


def ssl_context_for(
    uri: str, meta: dict[str, object] | None = None
) -> ssl.SSLContext | None:
    """Return an SSL context for urlopen; ``None`` keeps default strict verification.

    请求级 ``metadata["ssl_verify"]=false`` 或域名命中 ``CGDA_HTTP_INSECURE_HOSTS``
    （默认含 NSMC 门户）时返回不验证上下文，并记录 warning 便于审计。
    """
    host = (urlparse(uri).hostname or "").lower()
    if _ssl_verify_disabled(meta):
        logger.warning(
            "HTTPS certificate verification disabled by request metadata for %s", host
        )
        return _insecure_ssl_context()
    if host and host in _insecure_hosts():
        logger.warning(
            "HTTPS certificate verification disabled for allowlisted host %s", host
        )
        return _insecure_ssl_context()
    return None


# 下载重试（指数退避 2s/4s；.part 半成品保留供 Range 续传）
_MAX_DOWNLOAD_ATTEMPTS = 3
_RETRY_BACKOFF_BASE_SECONDS = 2.0
# URL path suffixes that are scripts/filters, not payload extensions (NOMADS CGI).
_OPAQUE_URL_SUFFIXES = frozenset(
    {".pl", ".cgi", ".php", ".asp", ".aspx", ".jsp", ".py", ".exe"}
)


def _cache_suffix_from_url_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if not suffix or suffix in _OPAQUE_URL_SUFFIXES:
        return ".bin"
    return suffix


def _sniff_file_suffix(local_path: Path) -> str | None:
    """Return a better extension from magic bytes when URL suffix is opaque."""
    try:
        with local_path.open("rb") as fh:
            head = fh.read(16)
    except OSError:
        return None
    if head.startswith(b"GRIB"):
        return ".grib2"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    return None


def _maybe_rename_sniffed(local_path: Path) -> Path:
    if local_path.suffix.lower() not in {".bin", *_OPAQUE_URL_SUFFIXES}:
        return local_path
    sniffed = _sniff_file_suffix(local_path)
    if not sniffed or local_path.suffix.lower() == sniffed:
        return local_path
    target = local_path.with_suffix(sniffed)
    if target == local_path:
        return local_path
    try:
        if target.exists():
            target.unlink()
        local_path.rename(target)
        meta_src = _meta_sidecars(local_path)
        meta_dst = _meta_sidecars(target)
        if meta_src.is_file():
            if meta_dst.exists():
                meta_dst.unlink()
            meta_src.rename(meta_dst)
    except OSError:
        return local_path
    return target


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
        # P3 原子写：并发读（另一 worker 正在读 sidecar 元数据）与崩溃中断
        # 都会读到半截 JSON——先写临时文件再 os.replace 原子换名
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = meta_path.with_suffix(meta_path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, meta_path)
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
        suffix = _cache_suffix_from_url_path(parsed.path)
        local_path = destination_root / f"{cache_key}{suffix}"
        # Legacy caches may still use opaque CGI suffixes (.pl); prefer those hits.
        legacy_opaque = (
            destination_root / f"{cache_key}{Path(parsed.path).suffix.lower()}"
        )
        if (
            not local_path.exists()
            and legacy_opaque != local_path
            and legacy_opaque.exists()
            and legacy_opaque.stat().st_size > 0
        ):
            local_path = legacy_opaque

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

        local_path = _maybe_rename_sniffed(local_path)

        staged_metadata = dict(resource.metadata)
        staged_metadata["materialization_status"] = "ready"
        staged_metadata["local_path"] = str(local_path)
        staged_metadata["cache_hit"] = cache_hit
        staged_metadata["cache_key"] = cache_key
        if target_dir is not None:
            staged_metadata["target_dir"] = str(target_dir)

        return build_resource_ref(
            uri=local_path_to_uri(local_path),
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
            with urlopen(
                req, timeout=timeout, context=ssl_context_for(uri, meta)
            ) as resp:
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
            if exc.code == 429 or exc.code >= 500:
                raise ConnectionError(
                    f"HTTP revalidate failed (transient) for {uri}: {exc}"
                ) from exc
            raise ValueError(f"HTTP revalidate failed for {uri}: {exc}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ConnectionError(
                f"HTTP revalidate failed (transient) for {uri}: {exc}"
            ) from exc

    def _download(
        self,
        uri: str,
        local_path: Path,
        *,
        extra_headers: dict[str, str],
        meta: dict[str, object],
    ) -> None:
        """带重试与断点续传的下载。

        - 写 ``<name>.part`` 半成品，成功后 ``os.replace`` 原子落盘；
        - 重试间保留 ``.part``，经 ``Range: bytes=N-`` 续传（服务器返回 206 才追加，
          否则整体重写）；
        - 瞬态故障（网络/超时/5xx/429）退避后重试，最终抛 ``ConnectionError``
          （上游 FailureClassifier 归 transient_network，可重试）；
        - 终态 4xx 与 max_bytes 超限抛 ``ValueError``（不可重试）。
        """
        timeout = _timeout_seconds(meta)
        part_path = local_path.with_name(local_path.name + ".part")
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_DOWNLOAD_ATTEMPTS + 1):
            resume_offset = part_path.stat().st_size if part_path.exists() else 0
            headers = self._merge_request_headers(extra_headers)
            if resume_offset > 0:
                headers["Range"] = f"bytes={resume_offset}-"
            req = Request(uri, headers=headers)
            ssl_ctx = ssl_context_for(uri, meta)
            try:
                with urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
                    status = int(
                        getattr(resp, "status", None)
                        or getattr(resp, "getcode", lambda: 0)()
                        or 0
                    )
                    if resume_offset > 0 and status == 206:
                        mode, start_offset = "ab", resume_offset
                    else:
                        # 服务器不支持 Range（返回 200）或全新下载：整体重写
                        mode, start_offset = "wb", 0
                    self._write_response_body(
                        resp, part_path, meta, mode=mode, start_offset=start_offset
                    )
                    os.replace(part_path, local_path)
                    self._update_sidecar_from_response(local_path, resp)
                    return
            except ValueError:
                # max_bytes 超限等业务终态：清半成品，不重试
                part_path.unlink(missing_ok=True)
                raise
            except HTTPError as exc:
                if exc.code == 416:
                    # .part 已超过远端大小（远端资源变更）：丢弃半成品整体重下
                    part_path.unlink(missing_ok=True)
                    last_exc = exc
                elif exc.code == 429 or exc.code >= 500:
                    last_exc = exc
                else:
                    part_path.unlink(missing_ok=True)
                    raise ValueError(
                        f"HTTP materialize failed for {uri}: {exc}"
                    ) from exc
            except (URLError, TimeoutError, OSError) as exc:
                # 网络向瞬态：保留 .part 供下次续传
                last_exc = exc

            if attempt >= _MAX_DOWNLOAD_ATTEMPTS:
                break
            delay = _RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "HTTP materialize 失败（第 %d/%d 次），%.1fs 后重试（续传偏移 %d）: %s",
                attempt,
                _MAX_DOWNLOAD_ATTEMPTS,
                delay,
                part_path.stat().st_size if part_path.exists() else 0,
                uri,
            )
            time.sleep(delay)

        raise ConnectionError(
            f"HTTP materialize failed (transient) for {uri}: {last_exc}"
        ) from last_exc

    def _write_response_body(
        self,
        resp,
        local_path: Path,
        meta: dict[str, object],
        *,
        mode: str = "wb",
        start_offset: int = 0,
    ) -> None:
        max_bytes = _max_download_bytes(meta)
        written = start_offset
        with local_path.open(mode) as out:
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
