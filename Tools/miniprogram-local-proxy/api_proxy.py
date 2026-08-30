"""本机 http://127.0.0.1:PORT → HTTPS 上游（默认 api.cgdas.dpdns.org）。

用法::

    python api_proxy.py
    或 .\\start-python.ps1

环境变量：
    CGDA_PROXY_TARGET  上游根 URL（默认 https://api.cgdas.dpdns.org）
    CGDA_PROXY_PORT    本地端口（默认 8000）
"""

from __future__ import annotations

import os
import ssl
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

TARGET = os.environ.get("CGDA_PROXY_TARGET", "https://api.cgdas.dpdns.org").rstrip("/")
PORT = int(os.environ.get("CGDA_PROXY_PORT", "8000"))
_HOP_BY_HOP = frozenset(
    {
        "host",
        "content-length",
        "connection",
        "accept-encoding",
        "transfer-encoding",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "upgrade",
    }
)


class Handler(BaseHTTPRequestHandler):
    def _proxy(self) -> None:
        url = TARGET + self.path
        body: bytes | None = None
        if self.command in ("POST", "PUT", "PATCH"):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None

        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in _HOP_BY_HOP
        }
        headers["Host"] = urlparse(TARGET).hostname or "api.cgdas.dpdns.org"

        req = urllib.request.Request(url, data=body, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in {"transfer-encoding", "connection", "content-encoding"}:
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in {"transfer-encoding", "connection", "content-encoding"}:
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:  # noqa: BLE001 — surface upstream failures to the client
            self.send_response(502)
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"upstream error: {e}".encode())

    def do_GET(self) -> None:  # noqa: N802
        self._proxy()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy()

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy()

    def do_PATCH(self) -> None:  # noqa: N802
        self._proxy()

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._proxy()

    def do_HEAD(self) -> None:  # noqa: N802
        self._proxy()

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))


def main() -> None:
    if not (1 <= PORT <= 65535):
        raise SystemExit(f"Invalid CGDA_PROXY_PORT: {PORT}")
    # 部分校园网/代理环境证书链异常时仍可联调；仅用于本地开发反代。
    ssl._create_default_https_context = ssl._create_unverified_context
    print(f"proxy http://127.0.0.1:{PORT} -> {TARGET}")
    print(f"Keep this window open. Test: http://localhost:{PORT}/health")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
