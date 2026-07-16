from __future__ import annotations

import ftplib
import logging
from pathlib import Path

from shared.remote_sources.limits import DEFAULT_CONNECT_TIMEOUT, DEFAULT_MAX_REMOTE_BYTES
from shared.remote_sources.protocol import RemoteAuth, RemoteStat, effective_port
from shared.remote_sources.uri import ParsedRemoteUri, redact_uri

logger = logging.getLogger(__name__)


class FtpTransport:
    name = "ftp"
    supported_schemes = ("ftp", "ftps")

    def supports(self, parsed: ParsedRemoteUri) -> bool:
        return parsed.scheme in {"ftp", "ftps"}

    def _connect(self, parsed: ParsedRemoteUri, auth: RemoteAuth):
        username = auth.username or parsed.username or "anonymous"
        password = auth.password or "anonymous@"
        default_port = 990 if parsed.scheme == "ftps" else 21
        port = effective_port(parsed, auth, default_port)
        if parsed.scheme == "ftps":
            ftp: ftplib.FTP = ftplib.FTP_TLS()
            ftp.connect(parsed.host, port, timeout=DEFAULT_CONNECT_TIMEOUT)
            ftp.login(username, password)
            ftp.prot_p()
        else:
            allow_plain = (auth.extra or {}).get("allow_plain_ftp", "false").lower() == "true"
            if not allow_plain:
                raise ValueError(
                    "Plain ftp:// is disabled by default; set credential extra.allow_plain_ftp=true "
                    "or use ftps://"
                )
            ftp = ftplib.FTP()
            ftp.connect(parsed.host, port, timeout=DEFAULT_CONNECT_TIMEOUT)
            ftp.login(username, password)
        return ftp

    def stat(self, parsed: ParsedRemoteUri, auth: RemoteAuth) -> RemoteStat:
        ftp = self._connect(parsed, auth)
        try:
            path = parsed.path or "/"
            if path == "/":
                ftp.voidcmd("NOOP")
                return RemoteStat(path="/", size=None, is_dir=True)

            size: int | None = None
            try:
                raw_size = ftp.size(path)
                if raw_size is not None:
                    size = int(raw_size)
            except Exception:
                size = None

            if size is not None:
                return RemoteStat(path=path, size=size, is_dir=False)

            # SIZE unsupported/failed — confirm existence via NLST (do not treat as OK blindly)
            try:
                ftp.nlst(path)
            except Exception as exc:
                raise FileNotFoundError(f"FTP path not found or inaccessible: {path}") from exc
            return RemoteStat(path=path, size=None, is_dir=False)
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()

    def download_to(
        self,
        parsed: ParsedRemoteUri,
        auth: RemoteAuth,
        local_path: Path,
        *,
        max_bytes: int = DEFAULT_MAX_REMOTE_BYTES,
    ) -> RemoteStat:
        ftp = self._connect(parsed, auth)
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            written = 0

            def _write(chunk: bytes) -> None:
                nonlocal written
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError(f"FTP download exceeded max_bytes={max_bytes}")
                out.write(chunk)

            with local_path.open("wb") as out:
                ftp.retrbinary(f"RETR {parsed.path}", _write, blocksize=1024 * 1024)
            logger.info("FTP downloaded %s -> %s (%s bytes)", redact_uri(parsed.raw), local_path, written)
            return RemoteStat(path=parsed.path, size=written, is_dir=False)
        except Exception:
            local_path.unlink(missing_ok=True)
            raise
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()
