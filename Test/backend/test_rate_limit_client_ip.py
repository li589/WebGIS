"""写限流 client_ip 与 BACKEND_TRUST_PROXY（审查 BUG-3）。"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from app.api.rate_limit import client_ip
from app.core.config import settings


def _request(*, host: str = "10.0.0.5", headers: dict[str, str] | None = None):
    return SimpleNamespace(
        headers=headers or {},
        client=SimpleNamespace(host=host),
    )


def test_client_ip_ignores_xff_when_trust_proxy_false() -> None:
    req = _request(
        host="10.0.0.5",
        headers={"x-forwarded-for": "1.2.3.4, 9.9.9.9", "x-real-ip": "8.8.8.8"},
    )
    with patch(
        "app.core.config.settings",
        replace(settings, trust_proxy=False),
    ):
        assert client_ip(req) == "10.0.0.5"


def test_client_ip_uses_xff_when_trust_proxy_true() -> None:
    req = _request(
        host="10.0.0.5",
        headers={"x-forwarded-for": "1.2.3.4, 9.9.9.9"},
    )
    with patch(
        "app.core.config.settings",
        replace(settings, trust_proxy=True),
    ):
        assert client_ip(req) == "1.2.3.4"


def test_client_ip_uses_x_real_ip_when_trust_proxy_true() -> None:
    req = _request(host="10.0.0.5", headers={"x-real-ip": "8.8.8.8"})
    with patch(
        "app.core.config.settings",
        replace(settings, trust_proxy=True),
    ):
        assert client_ip(req) == "8.8.8.8"
