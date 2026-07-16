from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse, unquote


REMOTE_SCHEMES = frozenset({"sftp", "smb", "ftp", "ftps", "gs", "gcs"})


@dataclass(frozen=True, slots=True)
class ParsedRemoteUri:
    scheme: str
    host: str
    port: int | None
    username: str | None
    path: str
    # SMB: first path segment is share
    share: str | None
    cred_profile: str | None
    raw: str

    @property
    def path_without_share(self) -> str:
        """SMB path after share name; other schemes return ``path``."""
        if self.scheme != "smb" or not self.share:
            return self.path
        remainder = self.path.lstrip("/")
        prefix = f"{self.share}/"
        if remainder.startswith(prefix):
            return remainder[len(prefix) :]
        if remainder == self.share:
            return ""
        return remainder

    def with_port(self, port: int | None) -> ParsedRemoteUri:
        if port == self.port:
            return self
        return ParsedRemoteUri(
            scheme=self.scheme,
            host=self.host,
            port=port,
            username=self.username,
            path=self.path,
            share=self.share,
            cred_profile=self.cred_profile,
            raw=self.raw,
        )


def redact_uri(uri: str) -> str:
    """Strip userinfo/password and credential ids from URI for safe logging."""
    try:
        parsed = urlparse(uri)
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        netloc = f"{host}{port}"
        pairs: list[tuple[str, str]] = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower() in {"cred", "profile"}:
                pairs.append((key, "***"))
            else:
                pairs.append((key, value))
        query = urlencode(pairs)
        return urlunparse((parsed.scheme, netloc, parsed.path, "", query, ""))
    except Exception:
        return "<redacted-uri>"


def parse_remote_uri(uri: str) -> ParsedRemoteUri:
    if not uri or "://" not in uri:
        raise ValueError(f"Invalid remote URI (missing scheme): {uri!r}")
    parsed = urlparse(uri)
    scheme = (parsed.scheme or "").lower()
    if scheme == "gcs":
        scheme = "gs"
    if scheme not in REMOTE_SCHEMES:
        raise ValueError(f"Unsupported remote scheme '{scheme}' in {uri!r}")

    if parsed.password:
        raise ValueError(
            "Passwords embedded in remote URIs are not allowed; "
            "store secrets in a credential profile and use ?cred=profile_id"
        )

    host = parsed.hostname or ""
    if scheme == "gs":
        # gs://bucket/object — bucket is netloc; strip userinfo if present
        host = (parsed.hostname or parsed.netloc or "").split("@")[-1]
        if ":" in host and not host.startswith("["):
            host = host.split(":")[0]
    if not host:
        raise ValueError(f"Remote URI missing host/bucket: {uri!r}")

    from urllib.parse import parse_qs

    query = parse_qs(parsed.query)
    cred_values = query.get("cred") or query.get("profile") or []
    cred_profile = cred_values[0] if cred_values else None

    path = unquote(parsed.path or "")
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"Path traversal not allowed in remote URI: {uri!r}")
    normalized = "/" + "/".join(parts) if parts else "/"

    share: str | None = None
    if scheme == "smb":
        segs = [p for p in normalized.split("/") if p]
        if not segs:
            raise ValueError(f"SMB URI requires share: {uri!r}")
        share = segs[0]

    return ParsedRemoteUri(
        scheme=scheme,
        host=host,
        port=parsed.port,
        username=unquote(parsed.username) if parsed.username else None,
        path=normalized,
        share=share,
        cred_profile=cred_profile,
        raw=uri,
    )


def build_connectivity_probe_uri(uri: str, *, default_port: int | None = None) -> str:
    """Build a root/share URI for connectivity checks (not object existence)."""
    parsed = parse_remote_uri(uri)
    port = parsed.port if parsed.port is not None else default_port
    host_part = f"{parsed.host}:{port}" if port is not None and parsed.scheme != "gs" else parsed.host
    if parsed.scheme == "smb":
        share = parsed.share or "share"
        base = f"smb://{host_part}/{share}/"
    elif parsed.scheme == "gs":
        base = f"gs://{parsed.host}/"
    else:
        base = f"{parsed.scheme}://{host_part}/"
    if parsed.cred_profile:
        return f"{base}?cred={parsed.cred_profile}"
    return base
