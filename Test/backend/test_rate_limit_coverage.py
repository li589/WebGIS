"""Write / weather-tile rate-limit prefix coverage + trust_proxy IP policy."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.api.rate_limit import (
    client_ip,
    should_rate_limit_weather_tile,
    should_rate_limit_write,
)


def test_workflow_runs_writes_are_rate_limited() -> None:
    assert should_rate_limit_write("/workflow-runs", "POST")
    assert should_rate_limit_write("/workflow-runs/abc/cancel", "POST")
    assert not should_rate_limit_write("/workflow-runs", "GET")


def test_weather_tiles_get_rate_limited() -> None:
    assert should_rate_limit_weather_tile("/weather/tiles/wind/5/1/2", "GET")
    assert not should_rate_limit_weather_tile("/weather/tiles/wind/5/1/2", "POST")
    assert not should_rate_limit_weather_tile("/weather/point", "GET")


def test_client_ip_ignores_xff_unless_trust_proxy(monkeypatch) -> None:
    from dataclasses import replace

    from app.core.config import settings

    monkeypatch.setattr(
        "app.core.config.settings",
        replace(settings, trust_proxy=False),
    )
    request = MagicMock()
    request.headers = {"x-forwarded-for": "1.2.3.4"}
    request.client.host = "9.9.9.9"
    assert client_ip(request) == "9.9.9.9"

    monkeypatch.setattr(
        "app.core.config.settings",
        replace(settings, trust_proxy=True),
    )
    assert client_ip(request) == "1.2.3.4"
