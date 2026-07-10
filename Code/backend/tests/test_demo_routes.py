from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import create_app


class DemoRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._client = TestClient(create_app())

    def test_demo_snapshot_routes_are_marked_soft_offline(self) -> None:
        response = self._client.get("/demo/layers/snapshots", params={"hour": 12})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("deprecation"), "true")
        self.assertEqual(response.headers.get("x-compat-status"), "soft-offline-demo")
        self.assertEqual(response.headers.get("x-replacement-path"), "/layers + /workflow-runs")


if __name__ == "__main__":
    unittest.main()
