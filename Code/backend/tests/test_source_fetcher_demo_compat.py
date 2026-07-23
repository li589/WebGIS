from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.source_fetcher import DemoSourceFetcher


class DemoSourceFetcherCompatTests(unittest.TestCase):
    def test_demo_fetcher_writes_legacy_demo_compat_artifact(self) -> None:
        fetcher = DemoSourceFetcher()

        with patch(
            "app.services.source_fetcher.object_store.put_bytes",
            return_value=SimpleNamespace(
                content_length=128, file_path=Path("demo-artifact.json")
            ),
        ) as put_bytes_mock:
            result = fetcher.fetch(
                ref_id="demo-ref",
                source_uri="demo://snapshots/wind-field",
                artifact_key_prefix="artifacts/test",
            )

        self.assertTrue(result.success)
        self.assertEqual(result.artifact_key, "artifacts/test/demo-ref")
        payload = json.loads(put_bytes_mock.call_args.kwargs["data"].decode("utf-8"))
        metadata = put_bytes_mock.call_args.kwargs["metadata"]
        self.assertEqual(payload["compatibility_mode"], "legacy-demo")
        self.assertIn("compatibility artifact", payload["note"])
        self.assertEqual(metadata["compatibility_mode"], "legacy-demo")
        self.assertEqual(metadata["artifact_role"], "compat-placeholder")


if __name__ == "__main__":
    unittest.main()
