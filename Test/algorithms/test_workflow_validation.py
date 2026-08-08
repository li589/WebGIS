from __future__ import annotations

import unittest

from contracts.job import JobRequest
from contracts.product import ProductManifest
from contracts.runtime import RuntimeContext
from modules.base import BaseModule
from modules.registry import MODULE_ALIASES, MODULE_REGISTRY, register_module
from pipelines.base import BasePipeline, PipelinePlan
from runner.registry import PIPELINE_REGISTRY, register_pipeline
from workflow.graph import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNodeSpec,
    WorkflowOutputSpec,
)
from workflow.schemas import PortSpec
from workflow.template_inference import infer_workflow_request_template
from workflow.validation import (
    WorkflowDefinitionValidationError,
    validate_workflow_definition,
)


class _ValidationModule(BaseModule):
    name = "validation_module"
    input_ports = [
        PortSpec(
            name="input_value",
            kind="scalar",
            data_class="python_object",
            required=False,
        )
    ]
    output_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
        PortSpec(name="output_value", kind="scalar", data_class="python_object"),
    ]

    def execute(self, inputs, params, ctx):
        _ = (inputs, params, ctx)
        return {}


class _ValidationBridgePipeline(BasePipeline):
    name = "validation_bridge_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        _ = (request, ctx)
        return PipelinePlan(required_datasets=[], required_variables=[])

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        _ = (request, ctx)
        return ProductManifest(job_id="job", run_id="run", products=[], main_layers=[])


class WorkflowValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_module = MODULE_REGISTRY.get(_ValidationModule.name)
        self._original_aliases = dict(MODULE_ALIASES)
        self._original_pipeline = PIPELINE_REGISTRY.get(_ValidationBridgePipeline.name)
        register_module(_ValidationModule())
        register_pipeline(_ValidationBridgePipeline.name, _ValidationBridgePipeline)

    def tearDown(self) -> None:
        if self._original_module is None:
            MODULE_REGISTRY.pop(_ValidationModule.name, None)
        else:
            MODULE_REGISTRY[_ValidationModule.name] = self._original_module
        if self._original_pipeline is None:
            PIPELINE_REGISTRY.pop(_ValidationBridgePipeline.name, None)
        else:
            PIPELINE_REGISTRY[_ValidationBridgePipeline.name] = self._original_pipeline
        MODULE_ALIASES.clear()
        MODULE_ALIASES.update(self._original_aliases)

    def test_validate_workflow_definition_rejects_unknown_node_type(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-invalid-node-type",
            nodes=[WorkflowNodeSpec(node_id="bad_node", node_type="test.missing")],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:bad_node.manifest"
                )
            ],
        )

        with self.assertRaises(WorkflowDefinitionValidationError) as ctx:
            validate_workflow_definition(definition)

        self.assertIn("Node executor not registered", str(ctx.exception))

    def test_validate_workflow_definition_rejects_unsupported_request_binding(
        self,
    ) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-invalid-request-binding",
            nodes=[
                WorkflowNodeSpec(
                    node_id="module_node",
                    node_type="module",
                    input_bindings={"input_value": "request:not_supported"},
                    params={"module_name": "validation_module"},
                )
            ],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:module_node.manifest"
                )
            ],
        )

        with self.assertRaises(WorkflowDefinitionValidationError) as ctx:
            validate_workflow_definition(definition)

        self.assertIn("unsupported request binding", str(ctx.exception))

    def test_validate_workflow_definition_rejects_unknown_edge_target_port(
        self,
    ) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-invalid-edge-port",
            nodes=[
                WorkflowNodeSpec(
                    node_id="source_node",
                    node_type="module",
                    params={"module_name": "validation_module"},
                ),
                WorkflowNodeSpec(
                    node_id="target_node",
                    node_type="module",
                    params={"module_name": "validation_module"},
                ),
            ],
            edges=[
                WorkflowEdge(
                    from_node="source_node",
                    from_port="output_value",
                    to_node="target_node",
                    to_port="missing_input",
                )
            ],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:target_node.manifest"
                )
            ],
        )

        with self.assertRaises(WorkflowDefinitionValidationError) as ctx:
            validate_workflow_definition(definition)

        self.assertIn("unknown input port", str(ctx.exception))

    def test_validate_workflow_definition_rejects_unknown_output_source_port(
        self,
    ) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-invalid-output-source",
            nodes=[
                WorkflowNodeSpec(
                    node_id="module_node",
                    node_type="module",
                    params={"module_name": "validation_module"},
                )
            ],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:module_node.missing_output"
                )
            ],
        )

        with self.assertRaises(WorkflowDefinitionValidationError) as ctx:
            validate_workflow_definition(definition)

        self.assertIn("unknown node output port", str(ctx.exception))

    def test_validate_workflow_definition_rejects_cycle(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-cycle",
            nodes=[
                WorkflowNodeSpec(
                    node_id="node_a",
                    node_type="module",
                    params={"module_name": "validation_module"},
                ),
                WorkflowNodeSpec(
                    node_id="node_b",
                    node_type="module",
                    params={"module_name": "validation_module"},
                ),
            ],
            edges=[
                WorkflowEdge(
                    from_node="node_a",
                    from_port="output_value",
                    to_node="node_b",
                    to_port="input_value",
                ),
                WorkflowEdge(
                    from_node="node_b",
                    from_port="output_value",
                    to_node="node_a",
                    to_port="input_value",
                ),
            ],
            outputs=[
                WorkflowOutputSpec(name="final_manifest", source="node:node_a.manifest")
            ],
        )

        with self.assertRaises(WorkflowDefinitionValidationError) as ctx:
            validate_workflow_definition(definition)

        self.assertIn("cycle", str(ctx.exception).lower())

    def test_validate_workflow_definition_rejects_missing_bridge_param_binding_input(
        self,
    ) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-bridge-missing-binding",
            nodes=[
                WorkflowNodeSpec(
                    node_id="bridge_node",
                    node_type="bridge.pipeline",
                    params={
                        "pipeline_name": "validation_bridge_pipeline",
                        "datasource_bindings": {"source_value": "dynamic_source"},
                    },
                )
            ],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:bridge_node.manifest"
                )
            ],
        )

        with self.assertRaises(WorkflowDefinitionValidationError) as ctx:
            validate_workflow_definition(definition)

        self.assertIn("dynamic_source", str(ctx.exception))
        self.assertIn("required input port not bound", str(ctx.exception).lower())

    def test_validate_workflow_definition_accepts_bridge_param_binding_input(
        self,
    ) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-bridge-bound-input",
            nodes=[
                WorkflowNodeSpec(
                    node_id="bridge_node",
                    node_type="bridge.pipeline",
                    input_bindings={"dynamic_source": "input:source_value"},
                    params={
                        "pipeline_name": "validation_bridge_pipeline",
                        "datasource_bindings": {"source_value": "dynamic_source"},
                    },
                )
            ],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:bridge_node.manifest"
                )
            ],
        )

        validated = validate_workflow_definition(definition)

        self.assertIs(validated, definition)

    def test_infer_workflow_request_template_collects_input_and_request_bindings(
        self,
    ) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-template",
            name="wf-template",
            nodes=[
                WorkflowNodeSpec(
                    node_id="module_node",
                    node_type="module",
                    input_bindings={
                        "input_value": "input:source_value",
                    },
                    params={"module_name": "validation_module"},
                ),
                WorkflowNodeSpec(
                    node_id="module_node_2",
                    node_type="module",
                    input_bindings={
                        "input_value": "request:tags",
                    },
                    params={"module_name": "validation_module"},
                ),
            ],
            outputs=[
                WorkflowOutputSpec(
                    name="final_manifest", source="node:module_node.manifest"
                )
            ],
        )

        template = infer_workflow_request_template(definition)

        self.assertEqual(template.workflow_id, "wf-template")
        self.assertEqual(template.required_datasource_keys, ("source_value",))
        self.assertEqual(template.referenced_request_keys, ("tags",))
        self.assertEqual(len(template.nodes), 2)
        self.assertEqual(template.nodes[0].entry_name, "validation_module")


if __name__ == "__main__":
    unittest.main()
