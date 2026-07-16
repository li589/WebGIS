from __future__ import annotations

import logging
from pathlib import Path

from shared.remote_sources.limits import DEFAULT_MAX_REMOTE_BYTES
from shared.remote_sources.protocol import RemoteAuth, RemoteStat, effective_port
from shared.remote_sources.uri import ParsedRemoteUri, redact_uri

logger = logging.getLogger(__name__)


class SmbTransport:
    name = "smb"
    supported_schemes = ("smb",)

    def supports(self, parsed: ParsedRemoteUri) -> bool:
        return parsed.scheme == "smb"

    def _auth_fields(self, parsed: ParsedRemoteUri, auth: RemoteAuth) -> tuple[str, str, str, int]:
        username = auth.username or parsed.username
        if not username or not auth.password:
            raise ValueError("SMB requires username and password in credential profile")
        if not parsed.share:
            raise ValueError("SMB URI requires share name: smb://host/share/path")
        domain = auth.domain or (auth.extra or {}).get("domain") or ""
        port = effective_port(parsed, auth, 445)
        return username, auth.password, domain, port

    def stat(self, parsed: ParsedRemoteUri, auth: RemoteAuth) -> RemoteStat:
        try:
            from smbclient import listdir as smb_listdir  # type: ignore
            from smbclient import stat as smb_stat  # type: ignore
            import stat as stat_mod
        except ImportError as exc:
            raise ValueError("smbprotocol/smbclient is required for smb:// URIs") from exc

        username, password, domain, port = self._auth_fields(parsed, auth)
        relative = parsed.path_without_share.replace("/", "\\")
        unc_root = f"\\\\{parsed.host}\\{parsed.share}"
        unc = f"{unc_root}\\{relative}".rstrip("\\") if relative else unc_root

        # Share root = connectivity probe
        if not relative:
            smb_listdir(
                unc_root,
                username=username,
                password=password,
                port=port,
                connection_timeout=30,
                domain=domain or None,
            )
            return RemoteStat(path=parsed.path, size=None, is_dir=True)

        st = smb_stat(
            unc,
            username=username,
            password=password,
            port=port,
            connection_timeout=30,
            domain=domain or None,
        )
        is_dir = bool(getattr(st, "st_mode", None) and stat_mod.S_ISDIR(st.st_mode))
        return RemoteStat(
            path=parsed.path,
            size=int(st.st_size) if getattr(st, "st_size", None) is not None else None,
            is_dir=is_dir,
            mtime=float(st.st_mtime) if getattr(st, "st_mtime", None) is not None else None,
        )

    def download_to(
        self,
        parsed: ParsedRemoteUri,
        auth: RemoteAuth,
        local_path: Path,
        *,
        max_bytes: int = DEFAULT_MAX_REMOTE_BYTES,
    ) -> RemoteStat:
        try:
            from smbclient import open_file  # type: ignore
        except ImportError as exc:
            raise ValueError("smbprotocol/smbclient is required for smb:// URIs") from exc

        username, password, domain, port = self._auth_fields(parsed, auth)
        relative = parsed.path_without_share.replace("/", "\\")
        unc = f"\\\\{parsed.host}\\{parsed.share}\\{relative}".rstrip("\\")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with open_file(
            unc,
            mode="rb",
            username=username,
            password=password,
            port=port,
            connection_timeout=30,
            domain=domain or None,
        ) as remote:
            with local_path.open("wb") as out:
                while True:
                    chunk = remote.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        local_path.unlink(missing_ok=True)
                        raise ValueError(f"SMB download exceeded max_bytes={max_bytes}")
                    out.write(chunk)
        logger.info("SMB downloaded %s -> %s (%s bytes)", redact_uri(parsed.raw), local_path, written)
        return RemoteStat(path=parsed.path, size=written, is_dir=False)
