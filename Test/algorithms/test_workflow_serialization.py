from __future__ import annotations

import json
import unittest

from workflow.graph import WorkflowDefinition
from workflow.serialization import (
    WorkflowDefinitionDecodeError,
    coerce_workflow_definition,
    get_workflow_definition_json_schema,
)


class WorkflowSerializationTests(unittest.TestCase):
    def test_coerce_workflow_definition_accepts_json_string_payload(self) -> None:
        payload = json.dumps(
            {
                "workflow_id": "wf-json-string",
                "nodes": [
                    {
                        "node_id": "module_node",
                        "node_type": "module",
                        "input_bindings": {"input_value": "input:source_value"},
                        "params": {"module_name": "acceptance_module"},
                    }
                ],
                "outputs": [
                    {"name": "final_manifest", "source": "node:module_node.manifest"},
                ],
            }
        )

        definition = coerce_workflow_definition(payload)

        self.assertIsInstance(definition, WorkflowDefinition)
        self.assertEqual(definition.workflow_id, "wf-json-string")
        self.assertEqual(
            definition.nodes[0].input_bindings["input_value"], "input:source_value"
        )

    def test_coerce_workflow_definition_rejects_non_string_binding_payload(
        self,
    ) -> None:
        payload = {
            "workflow_id": "wf-invalid-binding",
            "nodes": [
                {
                    "node_id": "module_node",
                    "node_type": "module",
                    "input_bindings": {"input_value": {"source": "input:source_value"}},
                    "params": {"module_name": "acceptance_module"},
                }
            ],
            "outputs": [
                {"name": "final_manifest", "source": "node:module_node.manifest"},
            ],
        }

        with self.assertRaises(WorkflowDefinitionDecodeError) as ctx:
            coerce_workflow_definition(payload)

        self.assertIn(
            "workflow_definition.nodes[0].input_bindings.input_value",
            str(ctx.exception),
        )

    def test_coerce_workflow_definition_rejects_unknown_top_level_field(self) -> None:
        payload = {
            "workflow_id": "wf-unknown-top",
            "nodes": [
                {
                    "node_id": "module_node",
                    "node_type": "module",
                    "params": {"module_name": "acceptance_module"},
                }
            ],
            "outputs": [
                {"name": "final_manifest", "source": "node:module_node.manifest"},
            ],
            "unexpected": "ignored-before",
        }

        with self.assertRaises(WorkflowDefinitionDecodeError) as ctx:
            coerce_workflow_definition(payload)

        self.assertIn("workflow_definition", str(ctx.exception))
        self.assertIn("unexpected", str(ctx.exception))

    def test_coerce_workflow_definition_rejects_unknown_node_field(self) -> None:
        payload = {
            "workflow_id": "wf-unknown-node-field",
            "nodes": [
                {
                    "node_id": "module_node",
                    "node_type": "module",
                    "params": {"module_name": "acceptance_module"},
                    "surprise": 1,
                }
            ],
            "outputs": [
                {"name": "final_manifest", "source": "node:module_node.manifest"},
            ],
        }

        with self.assertRaises(WorkflowDefinitionDecodeError) as ctx:
            coerce_workflow_definition(payload)

        self.assertIn("workflow_definition.nodes[0]", str(ctx.exception))
        self.assertIn("surprise", str(ctx.exception))

    def test_workflow_definition_json_schema_exposes_runtime_fields(self) -> None:
        schema = get_workflow_definition_json_schema()

        self.assertEqual(schema["title"], "WorkflowDefinition")
        self.assertIn("workflow_id", schema["properties"])
        self.assertIn("nodes", schema["properties"])
        self.assertIn("outputs", schema["properties"])


if __name__ == "__main__":
    unittest.main()
