from __future__ import annotations

import unittest

from workflow.graph import WorkflowDefinition, WorkflowNodeSpec, WorkflowOutputSpec
from workflow.panel_schema import WorkflowInputPanelSchema, WorkflowPanelField, build_workflow_input_panel_schema
from workflow.schemas import InputSourceSpec
from workflow.ui_metadata import build_workflow_input_panel_ui_schema, enhance_panel_schema_with_ui_metadata


class WorkflowPanelSchemaTests(unittest.TestCase):
    def test_build_workflow_input_panel_schema_exposes_required_inputs_and_algorithm_fields(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-panel-omega",
            inputs={
                "optional_mask": InputSourceSpec(source_type="file", format="mat"),
            },
            nodes=[
                WorkflowNodeSpec(
                    node_id="omega_node",
                    node_type="module",
                    input_bindings={
                        "algorithm_params": "request:algorithm_params",
                        "input_mat": "input:timeseries_bundle_mat",
                        "omega_fixed_mat": "input:omega_fixed_mat",
                        "exp0_calib_mat": "input:exp0_calib_mat",
                    },
                    params={"module_name": "omega_block"},
                )
            ],
            outputs=[WorkflowOutputSpec(name="final_manifest", source="node:omega_node.manifest")],
        )

        panel = build_workflow_input_panel_schema(definition)

        datasource_fields = {field.key: field for field in panel.datasource_fields}
        algorithm_fields = {field.key: field for field in panel.algorithm_param_fields}
        request_fields = {field.key: field for field in panel.request_fields}

        self.assertEqual(panel.workflow_id, "wf-panel-omega")
        self.assertEqual(
            sorted(datasource_fields),
            ["exp0_calib_mat", "omega_fixed_mat", "optional_mask", "timeseries_bundle_mat"],
        )
        self.assertTrue(datasource_fields["timeseries_bundle_mat"].required)
        self.assertTrue(datasource_fields["omega_fixed_mat"].required)
        self.assertFalse(datasource_fields["optional_mask"].required)
        self.assertEqual(datasource_fields["optional_mask"].source_types, ("file",))
        self.assertEqual(datasource_fields["optional_mask"].format_hints, ("mat",))
        self.assertIn("exp_mode", algorithm_fields)
        self.assertIn("Exp0", algorithm_fields["exp_mode"].allowed_values)
        self.assertIn("EXP2", algorithm_fields["exp_mode"].allowed_values)
        self.assertIn("algorithm_params", request_fields)
        self.assertEqual(request_fields["algorithm_params"].consumers, ("omega_node",))

    def test_build_workflow_input_panel_schema_exposes_template_derived_optional_fields(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-panel-daily-bundle",
            nodes=[
                WorkflowNodeSpec(
                    node_id="bundle_node",
                    node_type="module",
                    input_bindings={
                        "datasource_selection": "request:datasource_selection",
                        "algorithm_params": "request:algorithm_params",
                    },
                    params={"module_name": "daily_bundle"},
                )
            ],
            outputs=[WorkflowOutputSpec(name="final_manifest", source="node:bundle_node.manifest")],
        )

        panel = build_workflow_input_panel_schema(definition)

        datasource_fields = {field.key: field for field in panel.datasource_fields}
        algorithm_fields = {field.key: field for field in panel.algorithm_param_fields}
        request_fields = {field.key: field for field in panel.request_fields}

        self.assertIn("lin_pix_mat", datasource_fields)
        self.assertFalse(datasource_fields["lin_pix_mat"].required)
        self.assertEqual(datasource_fields["lin_pix_mat"].entry_names, ("daily_bundle",))
        self.assertIn("lin_pix", algorithm_fields)
        self.assertIn("lin_pix_varname", algorithm_fields)
        self.assertIn("datasource_selection", request_fields)
        self.assertIn("algorithm_params", request_fields)

    def test_build_workflow_input_panel_ui_schema_exposes_labels_controls_and_examples(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="wf-ui-metadata",
            inputs={
                "input_dir": InputSourceSpec(source_type="directory", format="folder"),
            },
            nodes=[
                WorkflowNodeSpec(
                    node_id="fy_node",
                    node_type="module",
                    input_bindings={
                        "datasource_selection": "request:datasource_selection",
                        "algorithm_params": "request:algorithm_params",
                    },
                    params={"module_name": "fy_daily"},
                )
            ],
            outputs=[WorkflowOutputSpec(name="final_manifest", source="node:fy_node.manifest")],
        )

        ui_schema = build_workflow_input_panel_ui_schema(definition)
        sections = {section.key: section for section in ui_schema.sections}
        datasource_fields = {field.key: field for field in sections["datasource_selection"].fields}
        algorithm_fields = {field.key: field for field in sections["algorithm_params"].fields}
        request_fields = {field.key: field for field in sections["request"].fields}

        self.assertEqual(sections["datasource_selection"].title, "数据源输入")
        self.assertEqual(datasource_fields["input_dir"].label, "输入目录")
        self.assertEqual(datasource_fields["input_dir"].control_type, "directory_picker")
        self.assertTrue(datasource_fields["input_dir"].required)
        self.assertIsNotNone(datasource_fields["input_dir"].placeholder)
        self.assertEqual(algorithm_fields["orbit_mode"].control_type, "select")
        self.assertIn("Both", algorithm_fields["orbit_mode"].allowed_values)
        self.assertEqual(algorithm_fields["execute_commands"].control_type, "switch")
        self.assertEqual(request_fields["datasource_selection"].control_type, "json_editor")

    def test_enhance_panel_schema_with_ui_metadata_maps_request_specific_controls(self) -> None:
        schema = WorkflowInputPanelSchema(
            workflow_id="wf-ui-request-fields",
            workflow_name="wf-ui-request-fields",
            request_fields=(
                WorkflowPanelField(
                    key="time_range",
                    section="request",
                    required=True,
                    value_kind="structured_object",
                    consumers=("node_a",),
                ),
                WorkflowPanelField(
                    key="region",
                    section="request",
                    required=True,
                    value_kind="structured_object",
                    consumers=("node_b",),
                ),
            ),
        )

        ui_schema = enhance_panel_schema_with_ui_metadata(schema)
        request_section = {section.key: section for section in ui_schema.sections}["request"]
        request_fields = {field.key: field for field in request_section.fields}

        self.assertEqual(request_fields["time_range"].control_type, "datetime_range")
        self.assertEqual(request_fields["region"].control_type, "region_editor")


if __name__ == "__main__":
    unittest.main()
