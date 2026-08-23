"""Remote scheme adapter (sftp/smb/ftp/ftps/gs) backed by shared.remote_sources."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from data_access.contracts import DataRequestV2, ResourceRef, build_resource_ref
from path_utils import local_path_to_uri
from shared.remote_sources.download import download_remote_uri
from shared.remote_sources.limits import get_max_remote_bytes
from shared.remote_sources.protocol import RemoteAuth
from shared.remote_sources.uri import parse_remote_uri

_REMOTE_SCHEMES = frozenset({"sftp", "smb", "ftp", "ftps", "gs", "gcs"})


def _rebuild_uri_with_alt(uri: str, alt: dict) -> str | None:
    """用备用 host/port 重建 URI（保留 scheme/path/query；无 host 则返回 None）。"""
    alt_host = str(alt.get("host") or "").strip()
    if not alt_host:
        return None
    try:
        alt_port = int(alt["port"]) if alt.get("port") is not None else None
    except (TypeError, ValueError):
        alt_port = None
    parts = urlparse(uri)
    userinfo = ""
    if parts.username:
        userinfo = (
            parts.username + (f":{parts.password}" if parts.password else "") + "@"
        )
    netloc = f"{userinfo}{alt_host}" + (f":{alt_port}" if alt_port else "")
    return urlunparse(
        (parts.scheme, netloc, parts.path, parts.params, parts.query, parts.fragment)
    )


def _alt_descriptor(auth: RemoteAuth) -> dict | None:
    """从 auth.extra 提取备用路径描述（fallback_mode=auto 时才回退）。"""
    extra = auth.extra or {}
    if str(extra.get("fallback_mode", "auto")) != "auto":
        return None
    raw = extra.get("alt_json")
    if not raw:
        return None
    try:
        loaded = json.loads(str(raw))
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _resolve_auth(uri: str, metadata: dict[str, object] | None) -> RemoteAuth:
    meta = dict(metadata or {})
    # Context-first: if a pre-resolved RemoteAuth is injected, use it directly.
    pre_resolved = meta.get("auth")
    if isinstance(pre_resolved, RemoteAuth):
        return pre_resolved
    if meta.get("username") or meta.get("password") or meta.get("private_key_pem"):
        extra = meta.get("extra") if isinstance(meta.get("extra"), dict) else {}
        port_raw = meta.get("port")
        try:
            port = int(port_raw) if port_raw is not None else None
        except (TypeError, ValueError):
            port = None
        return RemoteAuth(
            username=str(meta["username"]) if meta.get("username") else None,
            password=str(meta["password"]) if meta.get("password") else None,
            private_key_pem=str(meta["private_key_pem"])
            if meta.get("private_key_pem")
            else None,
            domain=str(meta["domain"]) if meta.get("domain") else None,
            port=port,
            extra={str(k): str(v) for k, v in extra.items()},
        )
    # P3 分层收口（2026-08-23）：后端凭据解析经 _backend_bridge 边界桥
    # （算法包唯一的 app.services 借用点）
    from _backend_bridge import resolve_remote_credentials

    resolved = resolve_remote_credentials(uri)
    if resolved is not None:
        return resolved
    raise ValueError(
        f"Unable to resolve remote credentials for {uri}. "
        "Provide metadata auth fields or backend credential profile (?cred=)."
    )


class RemoteSource:
    name = "remote"
    supported_schemes = ("sftp", "smb", "ftp", "ftps", "gs", "gcs")

    def can_handle(self, uri: str) -> bool:
        scheme = urlparse(uri).scheme.lower()
        return scheme in _REMOTE_SCHEMES

    def locate(
        self,
        uri: str,
        *,
        request: DataRequestV2 | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ResourceRef:
        _ = request
        parsed = parse_remote_uri(uri)
        staged = dict(metadata or {})
        staged["remote_scheme"] = parsed.scheme
        staged["remote_host"] = parsed.host
        if parsed.cred_profile:
            staged["cred_profile"] = parsed.cred_profile
        return build_resource_ref(
            uri=uri,
            source_kind="remote",
            storage_backend=parsed.scheme,
            metadata=staged,
        )

    def materialize(
        self,
        resource: ResourceRef,
        *,
        target_dir: Path | None = None,
    ) -> ResourceRef:
        destination = (
            Path(target_dir)
            if target_dir is not None
            else Path.cwd() / ".data" / "remote_cache"
        )
        auth = _resolve_auth(resource.uri, resource.metadata)
        try:
            local_path, stat = download_remote_uri(
                resource.uri,
                auth,
                target_dir=destination,
                max_bytes=get_max_remote_bytes(),
            )
        except OSError:
            # 网络类失败（连接拒绝/超时/DNS）——auto 模式且有备用路径时经备用重试一次；
            # 认证类错误不在此列（换路径无意义），原样抛出
            alt = _alt_descriptor(auth)
            alt_uri = _rebuild_uri_with_alt(resource.uri, alt) if alt else None
            if not alt_uri:
                raise
            local_path, stat = download_remote_uri(
                alt_uri,
                auth,
                target_dir=destination,
                max_bytes=get_max_remote_bytes(),
            )
        staged = dict(resource.metadata)
        staged["materialization_status"] = "ready"
        staged["local_path"] = str(local_path)
        staged["remote_size"] = stat.size
        if target_dir is not None:
            staged["target_dir"] = str(target_dir)
        return build_resource_ref(
            uri=local_path_to_uri(local_path),
            source_kind=resource.source_kind,
            format=resource.format,
            logical_type=resource.logical_type,
            storage_backend="local",
            metadata=staged,
        )
