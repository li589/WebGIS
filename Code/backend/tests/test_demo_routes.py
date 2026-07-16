from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app


class DemoRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._client = TestClient(create_app())

    def test_demo_routes_disabled_by_default(self) -> None:
        disabled_settings = replace(settings, demo_routes_enabled=False)
        with patch("app.api.routers.layer_router.settings", disabled_settings):
            response = self._client.get("/demo/layers/snapshots", params={"hour": 12})
        self.assertEqual(response.status_code, 404)

    def test_demo_snapshot_routes_are_marked_soft_offline_when_enabled(self) -> None:
        enabled_settings = replace(settings, demo_routes_enabled=True)
        with patch("app.api.routers.layer_router.settings", enabled_settings):
            response = self._client.get("/demo/layers/snapshots", params={"hour": 12})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("deprecation"), "true")
        self.assertEqual(response.headers.get("x-compat-status"), "soft-offline-demo")
        self.assertEqual(response.headers.get("x-replacement-path"), "/layers + /workflow-runs")


if __name__ == "__main__":
    unittest.main()
