from __future__ import annotations

import io
import logging
from pathlib import Path

from shared.remote_sources.limits import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_MAX_REMOTE_BYTES,
)
from shared.remote_sources.protocol import RemoteAuth, RemoteStat, effective_port
from shared.remote_sources.uri import ParsedRemoteUri, redact_uri

logger = logging.getLogger(__name__)


class SftpTransport:
    name = "sftp"
    supported_schemes = ("sftp",)

    def supports(self, parsed: ParsedRemoteUri) -> bool:
        return parsed.scheme == "sftp"

    def _connect(self, parsed: ParsedRemoteUri, auth: RemoteAuth):
        try:
            import paramiko  # type: ignore
        except ImportError as exc:
            raise ValueError("paramiko package is required for sftp:// URIs") from exc

        username = auth.username or parsed.username
        if not username:
            raise ValueError("SFTP requires username (URI or credential profile)")

        client = paramiko.SSHClient()
        policy = (auth.extra or {}).get("host_key_policy", "reject").lower()
        client.load_system_host_keys()
        if policy == "auto_add":
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())

        connect_kwargs: dict = {
            "hostname": parsed.host,
            "port": effective_port(parsed, auth, 22),
            "username": username,
            "timeout": DEFAULT_CONNECT_TIMEOUT,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if auth.private_key_pem:
            key_file = io.StringIO(auth.private_key_pem)
            try:
                pkey = paramiko.Ed25519Key.from_private_key(key_file)
            except Exception:
                key_file.seek(0)
                try:
                    pkey = paramiko.RSAKey.from_private_key(key_file)
                except Exception:
                    key_file.seek(0)
                    pkey = paramiko.ECDSAKey.from_private_key(key_file)
            connect_kwargs["pkey"] = pkey
        elif auth.password:
            connect_kwargs["password"] = auth.password
        else:
            raise ValueError(
                "SFTP credential profile requires password or private_key_pem"
            )

        client.connect(**connect_kwargs)
        return client

    def stat(self, parsed: ParsedRemoteUri, auth: RemoteAuth) -> RemoteStat:
        client = self._connect(parsed, auth)
        try:
            sftp = client.open_sftp()
            try:
                path = parsed.path or "/"
                if path == "/":
                    # Connectivity probe: connection success is enough
                    return RemoteStat(path="/", size=None, is_dir=True)
                st = sftp.stat(path)
                is_dir = False
                try:
                    import stat as stat_mod

                    is_dir = bool(st.st_mode and stat_mod.S_ISDIR(st.st_mode))
                except Exception:
                    is_dir = False
                return RemoteStat(
                    path=path,
                    size=int(st.st_size) if st.st_size is not None else None,
                    is_dir=is_dir,
                    mtime=float(st.st_mtime) if st.st_mtime is not None else None,
                )
            finally:
                sftp.close()
        finally:
            client.close()

    def download_to(
        self,
        parsed: ParsedRemoteUri,
        auth: RemoteAuth,
        local_path: Path,
        *,
        max_bytes: int = DEFAULT_MAX_REMOTE_BYTES,
    ) -> RemoteStat:
        client = self._connect(parsed, auth)
        try:
            sftp = client.open_sftp()
            try:
                st = sftp.stat(parsed.path)
                size = int(st.st_size) if st.st_size is not None else None
                if size is not None and size > max_bytes:
                    raise ValueError(
                        f"SFTP file exceeds max_bytes={max_bytes}: {redact_uri(parsed.raw)}"
                    )
                local_path.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with (
                    sftp.open(parsed.path, "rb") as remote,
                    local_path.open("wb") as out,
                ):
                    while True:
                        chunk = remote.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > max_bytes:
                            local_path.unlink(missing_ok=True)
                            raise ValueError(
                                f"SFTP download exceeded max_bytes={max_bytes}"
                            )
                        out.write(chunk)
                logger.info(
                    "SFTP downloaded %s -> %s (%s bytes)",
                    redact_uri(parsed.raw),
                    local_path,
                    written,
                )
                return RemoteStat(path=parsed.path, size=written, is_dir=False)
            finally:
                sftp.close()
        finally:
            client.close()
