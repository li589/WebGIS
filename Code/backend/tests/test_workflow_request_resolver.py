from __future__ import annotations

import unittest

from app.services.workflow_request_resolver import describe_layer_run_readiness


class WorkflowRequestResolverTests(unittest.TestCase):
    def test_lab_output_is_exposed_as_runnable_sample_provider(self) -> None:
        readiness = describe_layer_run_readiness("lab-output")

        self.assertIsNotNone(readiness)
        self.assertEqual(readiness["run_readiness"], "ready")
        self.assertIn("样板 provider", readiness["run_readiness_summary"])
        self.assertTrue(any("样板 provider" in note for note in readiness["run_readiness_notes"]))

    def test_placeholder_python_provider_remains_blocked(self) -> None:
        readiness = describe_layer_run_readiness("smap-soil")

        self.assertIsNotNone(readiness)
        self.assertEqual(readiness["run_readiness"], "blocked")
        self.assertIn("默认数据源未就绪", readiness["run_readiness_summary"])


if __name__ == "__main__":
    unittest.main()
