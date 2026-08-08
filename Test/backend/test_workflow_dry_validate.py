"""Unit tests for POST /workflow-definitions/dry-validate handler."""

from __future__ import annotations

import unittest

from fastapi import HTTPException

from app.api.routers.workflow_definition_router import dry_validate_graph


class DryValidateGraphTests(unittest.TestCase):
    def test_empty_graph_returns_422(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            dry_validate_graph({"workflow_id": "wf_empty", "nodes": [], "links": []})
        self.assertEqual(ctx.exception.status_code, 422)
        detail = ctx.exception.detail
        self.assertIsInstance(detail, dict)
        issues = detail.get("issues") or []
        self.assertTrue(issues)
        codes = {i.get("code") for i in issues if isinstance(i, dict)}
        self.assertTrue(codes & {"compile_error", "empty_graph"})

    def test_valid_module_graph_returns_ok(self) -> None:
        body = dry_validate_graph(
            {
                "workflow_id": "wf_ok",
                "nodes": [
                    {
                        "id": 1,
                        "type": "data/source",
                        "properties": {"path": "/tmp", "dataset_key": "SMAP_L3"},
                    },
                    {
                        "id": 2,
                        "type": "download/remote_fetch",
                        "properties": {"uri": "", "cred_profile": ""},
                    },
                ],
                "links": [[1, 1, 0, 2, 1, "data:source"]],
            }
        )
        self.assertTrue(body.get("ok"))
        self.assertIsInstance(body.get("workflow_definition"), dict)
        self.assertEqual(body.get("issues"), [])


if __name__ == "__main__":
    unittest.main()
