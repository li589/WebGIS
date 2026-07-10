from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.services.analysis_workflow_service import analysis_workflow_service
from app.services.demo_workflow_service import demo_workflow_service
from app.services.download_workflow_service import download_workflow_service
from shared.contracts.api_contracts import ClientIdentity, ResultKind, RuntimeMapContext, WorkflowCommandType, WorkflowPriority, WorkflowResultReference, WorkflowSubmitRequest


class CompatResultDtoShapeTests(unittest.TestCase):
    def _build_payload(self, *, outputs: list[ResultKind | str]) -> WorkflowSubmitRequest:
        return WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            layer_id="wind-field",
            priority=WorkflowPriority.normal,
            requested_outputs=outputs,
            client=ClientIdentity(client_id="test-client"),
            map_context=RuntimeMapContext(active_layer_id="wind-field"),
            parameters={"hour": 12},
        )

    def _assert_common_compat_fields(self, result_dto: dict, *, expected_category: str) -> None:
        self.assertEqual(result_dto["compatibility_mode"], "legacy-demo")
        self.assertEqual(result_dto["result_category"], expected_category)
        self.assertEqual(result_dto["layer_id"], "wind-field")
        self.assertEqual(result_dto["requested_hour"], 12.0)
        self.assertIn("summary", result_dto)
        self.assertIn("status_label", result_dto)
        self.assertIn("availability_state", result_dto)
        self.assertIn("data_state_mode", result_dto)
        self.assertIsInstance(result_dto.get("results"), dict)
        self.assertIn("json_result_id", result_dto["results"])

    def test_analysis_compat_result_dto_exposes_common_shape(self) -> None:
        payload = self._build_payload(outputs=[ResultKind.table, ResultKind.chart, ResultKind.text])

        result = analysis_workflow_service.execute(
            run_id="run-analysis-compat",
            payload=payload,
            requested_at=datetime.now(timezone.utc),
            event_factory=lambda **kwargs: kwargs,
        )

        assert result.result_dto is not None
        self._assert_common_compat_fields(result.result_dto, expected_category="analysis")
        self.assertEqual(result.result_dto["workflow_entry_name"], "analysis_workflow")
        self.assertIn("metric_label", result.result_dto)
        self.assertIn("metric_value", result.result_dto)
        self.assertIn("table_result_id", result.result_dto["results"])
        self.assertIn("chart_result_id", result.result_dto["results"])
        self.assertIn("text_result_id", result.result_dto["results"])

    def test_download_compat_result_dto_exposes_common_shape(self) -> None:
        payload = self._build_payload(outputs=[ResultKind.text])

        with patch(
            "app.services.download_service.result_storage_service.create_artifact_result_ref",
            return_value=WorkflowResultReference(
                result_id="manifest-test-result",
                result_kind=ResultKind.json,
                title="download-manifest",
                mime_type="application/json",
                resource_key="artifacts/test/manifest.json",
                resource_url="/artifacts/test/manifest.json",
                updated_at=datetime.now(timezone.utc),
            ),
        ):
            result = download_workflow_service.execute(
                run_id="run-download-compat",
                payload=payload,
                requested_at=datetime.now(timezone.utc),
                event_factory=lambda **kwargs: kwargs,
            )

        assert result.result_dto is not None
        self._assert_common_compat_fields(result.result_dto, expected_category="download")
        self.assertEqual(result.result_dto["workflow_entry_name"], "download_workflow")
        self.assertIn("download_ticket_id", result.result_dto)
        self.assertIn("manifest_result_id", result.result_dto)
        self.assertIn("text_result_id", result.result_dto["results"])
        self.assertIn("manifest_result_id", result.result_dto["results"])

    def test_demo_compat_result_dto_reuses_analysis_like_shape(self) -> None:
        payload = self._build_payload(outputs=[ResultKind.table, ResultKind.text])

        result = demo_workflow_service.execute(
            run_id="run-demo-compat-shape",
            payload=payload,
            requested_at=datetime.now(timezone.utc),
            event_factory=lambda **kwargs: kwargs,
        )

        assert result.result_dto is not None
        self._assert_common_compat_fields(result.result_dto, expected_category="analysis")
        self.assertEqual(result.result_dto["workflow_entry_name"], "demo_workflow")
        self.assertIn("metric_label", result.result_dto)
        self.assertIn("metric_value", result.result_dto)
        self.assertIn("table_result_id", result.result_dto["results"])
        self.assertIn("text_result_id", result.result_dto["results"])


if __name__ == "__main__":
    unittest.main()
