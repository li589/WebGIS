import pytest

from webgis_gee.api.contracts import WorkflowContractAdapter
from webgis_gee.application.services import WorkflowService
from webgis_gee.config.settings import Settings
from webgis_gee.domain.enums import PortKind, RunStatus
from webgis_gee.domain.models import ExecutionContext, NodeExecutionResult, NodeSpec, WorkflowDefinition
from webgis_gee.nodes.base import BaseNode
from webgis_gee.nodes.registry import NodeRegistry
from webgis_gee.nodes.sample_nodes import IdentityNode
from webgis_gee.runtime.exceptions import WorkflowValidationError
from webgis_gee.workflow.schema import (
    CURRENT_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
    SCHEMA_VERSION_1_0,
    SCHEMA_VERSION_1_1,
    SCHEMA_VERSION_1_2,
    SCHEMA_VERSION_1_3,
    SCHEMA_VERSION_1_4,
    SCHEMA_VERSION_1_5,
    SCHEMA_VERSION_1_6,
    SCHEMA_VERSION_1_7,
    SCHEMA_VERSION_1_8,
    SCHEMA_VERSION_1_9,
    SCHEMA_VERSION_1_10,
    SCHEMA_VERSION_1_11,
    SCHEMA_VERSION_1_12,
)
from webgis_gee.workflow.versioning import WorkflowDefinitionMigrator


class DeprecatedTestNode(BaseNode):
    node_type = "deprecated_test_node"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="deprecated_test_node",
            node_type=DeprecatedTestNode.node_type,
            input_ports=[],
            output_ports=[{"name": "value", "kind": PortKind.VALUE}],
            deprecated=True,
            replacement_node_type="identity",
        )

    def execute(self, inputs):
        return NodeExecutionResult(node_id=self.spec.node_id, outputs={"value": "deprecated"})


class ConfiguredReplacementNode(BaseNode):
    node_type = "configured_replacement_node"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="configured_replacement_node",
            node_type=ConfiguredReplacementNode.node_type,
            input_ports=[],
            output_ports=[{"name": "value", "kind": PortKind.VALUE}],
            params={
                "value": "",
                "enabled": False,
                "tags": [],
                "mode": "canonical",
            },
        )

    def execute(self, inputs):
        return NodeExecutionResult(node_id=self.spec.node_id, outputs={"value": inputs.get("value")})


class DeprecatedConfiguredNode(BaseNode):
    node_type = "deprecated_configured_node"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="deprecated_configured_node",
            node_type=DeprecatedConfiguredNode.node_type,
            input_ports=[],
            output_ports=[{"name": "value", "kind": PortKind.VALUE}],
            params={
                "legacy_value": "",
                "legacy_enabled": 0,
                "legacy_tag": "",
            },
            deprecated=True,
            replacement_node_type="configured_replacement_node",
            metadata={
                "replacement_parameter_rules": [
                    {"from": "legacy_value", "to": "value"},
                    {"from": "legacy_enabled", "to": "enabled", "transform": "bool"},
                    {"from": "legacy_tag", "to": "tags", "transform": "wrap_list"},
                    {"to": "mode", "value": "compat"},
                ]
            },
        )

    def execute(self, inputs):
        return NodeExecutionResult(node_id=self.spec.node_id, outputs={"value": "deprecated-configured"})


SCHEMA_VERSION_SEQUENCE = [
    LEGACY_SCHEMA_VERSION,
    SCHEMA_VERSION_1_0,
    SCHEMA_VERSION_1_1,
    SCHEMA_VERSION_1_2,
    SCHEMA_VERSION_1_3,
    SCHEMA_VERSION_1_4,
    SCHEMA_VERSION_1_5,
    SCHEMA_VERSION_1_6,
    SCHEMA_VERSION_1_7,
    SCHEMA_VERSION_1_8,
    SCHEMA_VERSION_1_9,
    SCHEMA_VERSION_1_10,
    SCHEMA_VERSION_1_11,
    CURRENT_SCHEMA_VERSION,
]


def expected_upgrade_path(from_version: str) -> list[str]:
    start_index = SCHEMA_VERSION_SEQUENCE.index(from_version)
    return SCHEMA_VERSION_SEQUENCE[start_index:]


def assert_schema_upgrade_notes(migration_notes: list[dict[str, object]], from_version: str) -> None:
    for source_version, target_version in zip(
        expected_upgrade_path(from_version),
        expected_upgrade_path(from_version)[1:],
    ):
        assert any(
            note["migration"] == "schema_version_upgraded"
            and note["from"] == source_version
            and note["to"] == target_version
            for note in migration_notes
        )


def test_normalize_workflow_definition_auto_migrates_legacy_payload(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "legacy-demo",
            "nodes": [
                {"node_id": "n1", "node_type": "literal", "params": {"value": "gee"}},
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == LEGACY_SCHEMA_VERSION
    assert normalized.metadata["schema_version"] == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(LEGACY_SCHEMA_VERSION)
    assert normalized.metadata["compatibility_mode"] == "migrated"
    assert normalized.metadata["source"] == "workflow_definition_migrator"
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], LEGACY_SCHEMA_VERSION)
    assert normalized.nodes[0].metadata["schema_version"] == CURRENT_SCHEMA_VERSION
    assert normalized.nodes[0].metadata["canonical_node_type"] == "literal"
    assert normalized.nodes[0].metadata["canonical_node_version"] == "1.0.0"
    assert normalized.metadata["normalization_summary_schema"] == SCHEMA_VERSION_1_2
    assert normalized.metadata["normalization_summary"]["total_nodes"] == 1
    assert normalized.metadata["compatibility_snapshot_schema"] == SCHEMA_VERSION_1_3
    assert normalized.metadata["compatibility_snapshot"]["canonical_node_types"] == ["literal"]
    assert normalized.metadata["resave_hint_schema"] == SCHEMA_VERSION_1_4
    assert normalized.metadata["resave_hint"]["resave_recommended"] is True
    assert normalized.metadata["resave_hint"]["auto_migrated"] is True
    assert "schema_upgraded" in normalized.metadata["resave_hint"]["reasons"]
    assert normalized.metadata["compatibility_contract_schema"] == SCHEMA_VERSION_1_5
    assert normalized.metadata["compatibility_contract"]["upgrade_path"] == expected_upgrade_path(
        LEGACY_SCHEMA_VERSION
    )
    assert normalized.metadata["saveback_policy_schema"] == SCHEMA_VERSION_1_6
    assert normalized.metadata["saveback_policy"]["recommended_mode"] == "canonical_writeback"
    assert normalized.metadata["saveback_decision_schema"] == SCHEMA_VERSION_1_7
    assert normalized.metadata["saveback_decision"]["highest_severity"] == "none"
    assert normalized.metadata["auto_fix_plan_schema"] == SCHEMA_VERSION_1_8
    assert normalized.metadata["auto_fix_plan"]["schema_version"] == SCHEMA_VERSION_1_8
    assert normalized.metadata["auto_fix_plan"]["plan_mode"] == "no_op"
    assert normalized.metadata["saveback_commit_plan_schema"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["saveback_commit_plan"]["schema_version"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["saveback_audit_plan_schema"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_audit_plan"]["schema_version"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_closure_plan"]["schema_version"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12
    assert normalized.metadata["saveback_terminal_plan"]["schema_version"] == SCHEMA_VERSION_1_12


def test_submit_workflow_rejects_unsupported_schema_version(tmp_path) -> None:
    adapter = WorkflowContractAdapter(
        WorkflowService(settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)))
    )

    with pytest.raises(WorkflowValidationError, match="unsupported workflow schema_version: 9.9"):
        adapter.submit_workflow(
            workflow={
                "workflow_id": "unsupported-schema-demo",
                "schema_version": "9.9",
                "nodes": [
                    {"node_id": "n1", "node_type": "literal", "params": {"value": 1}},
                ],
            }
        )


def test_normalize_workflow_definition_auto_migrates_1_0_payload_to_current_schema(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "schema-1-0-demo",
            "schema_version": SCHEMA_VERSION_1_0,
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "literal",
                    "params": {"value": "gee"},
                    "metadata": {"schema_version": SCHEMA_VERSION_1_0},
                },
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == SCHEMA_VERSION_1_0
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(SCHEMA_VERSION_1_0)
    assert normalized.metadata["node_metadata_schema"] == SCHEMA_VERSION_1_1
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], SCHEMA_VERSION_1_0)
    assert any(
        note["migration"] == "node_metadata_normalized"
        and note["schema_version"] == CURRENT_SCHEMA_VERSION
        and "n1" in note["node_ids"]
        for note in normalized.metadata["migration_notes"]
    )
    assert normalized.nodes[0].metadata["schema_version"] == CURRENT_SCHEMA_VERSION
    assert normalized.nodes[0].metadata["canonical_node_type"] == "literal"
    assert normalized.nodes[0].metadata["canonical_node_version"] == "1.0.0"
    assert normalized.metadata["normalization_summary_schema"] == SCHEMA_VERSION_1_2
    assert normalized.metadata["normalization_summary"]["auto_migrated"] is True
    assert normalized.metadata["compatibility_snapshot_schema"] == SCHEMA_VERSION_1_3
    assert normalized.metadata["resave_hint_schema"] == SCHEMA_VERSION_1_4
    assert {"schema_upgraded", "workflow_defaults_filled"} <= set(
        normalized.metadata["resave_hint"]["reasons"]
    )
    assert normalized.metadata["compatibility_contract_schema"] == SCHEMA_VERSION_1_5
    assert normalized.metadata["saveback_policy_schema"] == SCHEMA_VERSION_1_6
    assert normalized.metadata["saveback_decision_schema"] == SCHEMA_VERSION_1_7
    assert normalized.metadata["auto_fix_plan_schema"] == SCHEMA_VERSION_1_8
    assert normalized.metadata["saveback_commit_plan_schema"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["saveback_audit_plan_schema"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12


def test_normalize_workflow_definition_auto_migrates_1_1_payload_to_current_schema(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "schema-1-1-demo",
            "schema_version": SCHEMA_VERSION_1_1,
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "identity",
                    "metadata": {
                        "schema_version": SCHEMA_VERSION_1_1,
                        "canonical_node_type": "identity",
                    },
                },
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == SCHEMA_VERSION_1_1
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(SCHEMA_VERSION_1_1)
    assert normalized.metadata["normalization_summary_schema"] == SCHEMA_VERSION_1_2
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], SCHEMA_VERSION_1_1)
    assert normalized.nodes[0].metadata["schema_version"] == CURRENT_SCHEMA_VERSION
    assert normalized.nodes[0].metadata["canonical_node_type"] == "identity"
    assert normalized.nodes[0].metadata["canonical_node_version"] == "1.0.0"
    assert normalized.metadata["normalization_summary"]["total_nodes"] == 1
    assert normalized.metadata["normalization_summary"]["defaulted_nodes"] == 0
    assert normalized.metadata["compatibility_snapshot_schema"] == SCHEMA_VERSION_1_3
    assert normalized.metadata["compatibility_snapshot"]["canonical_node_types"] == ["identity"]
    assert normalized.metadata["resave_hint_schema"] == SCHEMA_VERSION_1_4
    assert {"schema_upgraded", "workflow_defaults_filled"} <= set(
        normalized.metadata["resave_hint"]["reasons"]
    )
    assert normalized.metadata["compatibility_contract_schema"] == SCHEMA_VERSION_1_5
    assert normalized.metadata["saveback_policy_schema"] == SCHEMA_VERSION_1_6
    assert normalized.metadata["saveback_decision_schema"] == SCHEMA_VERSION_1_7
    assert normalized.metadata["auto_fix_plan_schema"] == SCHEMA_VERSION_1_8
    assert normalized.metadata["saveback_commit_plan_schema"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["saveback_audit_plan_schema"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12


def test_normalize_workflow_definition_auto_migrates_1_2_payload_to_current_schema(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "schema-1-2-demo",
            "schema_version": SCHEMA_VERSION_1_2,
            "metadata": {
                "schema_version": SCHEMA_VERSION_1_2,
                "normalization_summary_schema": SCHEMA_VERSION_1_2,
            },
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_export_image",
                    "params": {"destination": "manifest"},
                    "metadata": {
                        "schema_version": SCHEMA_VERSION_1_2,
                        "canonical_node_type": "gee_export_image",
                        "canonical_node_version": "1.0.0",
                    },
                },
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == SCHEMA_VERSION_1_2
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(SCHEMA_VERSION_1_2)
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], SCHEMA_VERSION_1_2)
    assert normalized.metadata["normalization_summary_schema"] == SCHEMA_VERSION_1_2
    assert normalized.metadata["compatibility_snapshot_schema"] == SCHEMA_VERSION_1_3
    assert normalized.metadata["compatibility_snapshot"]["canonical_node_types"] == ["gee_export_image"]
    assert normalized.metadata["compatibility_snapshot"]["defaulted_node_ids"] == ["n1"]
    assert normalized.metadata["resave_hint_schema"] == SCHEMA_VERSION_1_4
    assert {
        "node_defaults_filled",
        "schema_upgraded",
        "workflow_defaults_filled",
    } <= set(normalized.metadata["resave_hint"]["reasons"])
    assert normalized.metadata["compatibility_contract_schema"] == SCHEMA_VERSION_1_5
    assert normalized.metadata["saveback_policy_schema"] == SCHEMA_VERSION_1_6
    assert normalized.metadata["saveback_decision_schema"] == SCHEMA_VERSION_1_7
    assert normalized.metadata["auto_fix_plan_schema"] == SCHEMA_VERSION_1_8
    assert normalized.metadata["saveback_commit_plan_schema"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["saveback_audit_plan_schema"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12


def test_normalize_workflow_definition_auto_migrates_1_3_payload_to_current_schema(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "schema-1-3-demo",
            "schema_version": SCHEMA_VERSION_1_3,
            "metadata": {
                "schema_version": SCHEMA_VERSION_1_3,
                "normalization_summary_schema": SCHEMA_VERSION_1_2,
                "compatibility_snapshot_schema": SCHEMA_VERSION_1_3,
            },
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_export_table",
                    "params": {"destination": "manifest"},
                    "metadata": {
                        "schema_version": SCHEMA_VERSION_1_3,
                        "canonical_node_type": "gee_export_table",
                        "canonical_node_version": "1.0.0",
                    },
                },
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == SCHEMA_VERSION_1_3
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(SCHEMA_VERSION_1_3)
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], SCHEMA_VERSION_1_3)
    assert normalized.metadata["compatibility_snapshot_schema"] == SCHEMA_VERSION_1_3
    assert normalized.metadata["resave_hint_schema"] == SCHEMA_VERSION_1_4
    assert normalized.metadata["resave_hint"]["resave_recommended"] is True
    assert {
        "node_defaults_filled",
        "schema_upgraded",
        "workflow_defaults_filled",
    } <= set(normalized.metadata["resave_hint"]["reasons"])
    assert normalized.metadata["resave_hint"]["affected_node_ids"] == ["n1"]
    assert normalized.metadata["resave_hint"]["auto_migrated"] is True
    assert normalized.metadata["compatibility_contract_schema"] == SCHEMA_VERSION_1_5
    assert normalized.metadata["compatibility_contract"]["nodes_requiring_resave"] == ["n1"]
    assert normalized.metadata["saveback_policy_schema"] == SCHEMA_VERSION_1_6
    assert normalized.metadata["saveback_decision_schema"] == SCHEMA_VERSION_1_7
    assert normalized.metadata["auto_fix_plan_schema"] == SCHEMA_VERSION_1_8
    assert normalized.metadata["saveback_commit_plan_schema"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["saveback_audit_plan_schema"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12


def test_normalize_workflow_definition_auto_migrates_1_4_payload_to_current_schema(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "schema-1-4-demo",
            "schema_version": SCHEMA_VERSION_1_4,
            "metadata": {
                "schema_version": SCHEMA_VERSION_1_4,
                "normalization_summary_schema": SCHEMA_VERSION_1_2,
                "compatibility_snapshot_schema": SCHEMA_VERSION_1_3,
                "resave_hint_schema": SCHEMA_VERSION_1_4,
            },
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_raster_algebra",
                    "params": {
                        "expression": "nir / red",
                        "variables": {"nir": "B8", "red": "B4"},
                    },
                    "metadata": {
                        "schema_version": SCHEMA_VERSION_1_4,
                        "canonical_node_type": "gee_raster_algebra",
                        "canonical_node_version": "1.0.0",
                    },
                },
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == SCHEMA_VERSION_1_4
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(SCHEMA_VERSION_1_4)
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], SCHEMA_VERSION_1_4)
    assert normalized.metadata["resave_hint_schema"] == SCHEMA_VERSION_1_4
    assert normalized.metadata["compatibility_contract_schema"] == SCHEMA_VERSION_1_5
    assert normalized.metadata["saveback_policy_schema"] == SCHEMA_VERSION_1_6
    assert normalized.metadata["saveback_decision_schema"] == SCHEMA_VERSION_1_7
    assert normalized.metadata["auto_fix_plan_schema"] == SCHEMA_VERSION_1_8
    assert normalized.metadata["saveback_commit_plan_schema"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["saveback_audit_plan_schema"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12
    assert normalized.nodes[0].params["band_map"] == {"nir": "B8", "red": "B4"}
    assert normalized.metadata["compatibility_contract"]["node_types_with_alias_support"] == [
        "gee_raster_algebra"
    ]
    assert normalized.metadata["compatibility_contract"]["nodes_requiring_resave"] == ["n1"]
    assert normalized.metadata["saveback_policy"]["nodes_requiring_canonical_writeback"] == ["n1"]
    assert normalized.metadata["saveback_decision"]["recommended_node_ids"] == ["n1"]


def test_normalize_workflow_definition_auto_migrates_1_5_payload_to_current_schema(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "schema-1-5-demo",
            "schema_version": SCHEMA_VERSION_1_5,
            "metadata": {
                "schema_version": SCHEMA_VERSION_1_5,
                "normalization_summary_schema": SCHEMA_VERSION_1_2,
                "compatibility_snapshot_schema": SCHEMA_VERSION_1_3,
                "resave_hint_schema": SCHEMA_VERSION_1_4,
                "compatibility_contract_schema": SCHEMA_VERSION_1_5,
            },
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_export_table",
                    "params": {
                        "destination": "drive",
                        "task_name": "legacy-table-export",
                    },
                    "metadata": {
                        "schema_version": SCHEMA_VERSION_1_5,
                        "canonical_node_type": "gee_export_table",
                        "canonical_node_version": "1.0.0",
                    },
                },
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == SCHEMA_VERSION_1_5
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(SCHEMA_VERSION_1_5)
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], SCHEMA_VERSION_1_5)
    assert normalized.metadata["compatibility_contract_schema"] == SCHEMA_VERSION_1_5
    assert normalized.metadata["saveback_policy_schema"] == SCHEMA_VERSION_1_6
    assert normalized.metadata["saveback_decision_schema"] == SCHEMA_VERSION_1_7
    assert normalized.metadata["auto_fix_plan_schema"] == SCHEMA_VERSION_1_8
    assert normalized.metadata["saveback_commit_plan_schema"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["saveback_audit_plan_schema"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12
    assert normalized.metadata["saveback_policy"]["recommended_mode"] == "canonical_writeback"
    assert normalized.metadata["saveback_policy"]["nodes_requiring_canonical_writeback"] == ["n1"]


def test_normalize_workflow_definition_auto_migrates_1_6_payload_to_current_schema(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "schema-1-6-demo",
            "schema_version": SCHEMA_VERSION_1_6,
            "metadata": {
                "schema_version": SCHEMA_VERSION_1_6,
                "normalization_summary_schema": SCHEMA_VERSION_1_2,
                "compatibility_snapshot_schema": SCHEMA_VERSION_1_3,
                "resave_hint_schema": SCHEMA_VERSION_1_4,
                "compatibility_contract_schema": SCHEMA_VERSION_1_5,
                "saveback_policy_schema": SCHEMA_VERSION_1_6,
            },
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_time_series_stats",
                    "params": {
                        "band": "B8",
                        "date_field": "acquired_at",
                        "value_field": "series_value",
                    },
                    "metadata": {
                        "schema_version": SCHEMA_VERSION_1_6,
                        "canonical_node_type": "gee_time_series_stats",
                        "canonical_node_version": "1.0.0",
                    },
                },
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == SCHEMA_VERSION_1_6
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(SCHEMA_VERSION_1_6)
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], SCHEMA_VERSION_1_6)
    assert normalized.metadata["saveback_policy_schema"] == SCHEMA_VERSION_1_6
    assert normalized.metadata["saveback_decision_schema"] == SCHEMA_VERSION_1_7
    assert normalized.metadata["auto_fix_plan_schema"] == SCHEMA_VERSION_1_8
    assert normalized.metadata["saveback_commit_plan_schema"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["saveback_audit_plan_schema"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12
    assert normalized.metadata["saveback_decision"]["highest_severity"] == "recommended"
    assert normalized.metadata["saveback_decision"]["recommended_node_ids"] == ["n1"]
    assert normalized.metadata["saveback_decision"]["required_node_ids"] == []


def test_normalize_workflow_definition_auto_migrates_1_7_payload_to_current_schema(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "schema-1-7-demo",
            "schema_version": SCHEMA_VERSION_1_7,
            "metadata": {
                "schema_version": SCHEMA_VERSION_1_7,
                "normalization_summary_schema": SCHEMA_VERSION_1_2,
                "compatibility_snapshot_schema": SCHEMA_VERSION_1_3,
                "resave_hint_schema": SCHEMA_VERSION_1_4,
                "compatibility_contract_schema": SCHEMA_VERSION_1_5,
                "saveback_policy_schema": SCHEMA_VERSION_1_6,
                "saveback_decision_schema": SCHEMA_VERSION_1_7,
            },
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_export_image",
                    "params": {
                        "destination": "drive",
                        "task_name": "legacy-export",
                    },
                    "metadata": {
                        "schema_version": SCHEMA_VERSION_1_7,
                        "canonical_node_type": "gee_export_image",
                        "canonical_node_version": "1.0.0",
                    },
                },
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == SCHEMA_VERSION_1_7
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(SCHEMA_VERSION_1_7)
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], SCHEMA_VERSION_1_7)
    assert normalized.metadata["saveback_decision_schema"] == SCHEMA_VERSION_1_7
    assert normalized.metadata["auto_fix_plan_schema"] == SCHEMA_VERSION_1_8
    assert normalized.metadata["saveback_commit_plan_schema"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["saveback_audit_plan_schema"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12
    assert normalized.metadata["auto_fix_plan"]["plan_mode"] == "batch_canonical_writeback"
    assert normalized.metadata["auto_fix_plan"]["auto_fixable_node_ids"] == ["n1"]


def test_normalize_workflow_definition_auto_migrates_1_8_payload_to_current_schema(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "schema-1-8-demo",
            "schema_version": SCHEMA_VERSION_1_8,
            "metadata": {
                "schema_version": SCHEMA_VERSION_1_8,
                "normalization_summary_schema": SCHEMA_VERSION_1_2,
                "compatibility_snapshot_schema": SCHEMA_VERSION_1_3,
                "resave_hint_schema": SCHEMA_VERSION_1_4,
                "compatibility_contract_schema": SCHEMA_VERSION_1_5,
                "saveback_policy_schema": SCHEMA_VERSION_1_6,
                "saveback_decision_schema": SCHEMA_VERSION_1_7,
                "auto_fix_plan_schema": SCHEMA_VERSION_1_8,
            },
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_export_table",
                    "params": {
                        "destination": "drive",
                        "task_name": "legacy-table-export",
                    },
                    "metadata": {
                        "schema_version": SCHEMA_VERSION_1_8,
                        "canonical_node_type": "gee_export_table",
                        "canonical_node_version": "1.0.0",
                    },
                },
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == SCHEMA_VERSION_1_8
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(SCHEMA_VERSION_1_8)
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], SCHEMA_VERSION_1_8)
    assert normalized.metadata["auto_fix_plan_schema"] == SCHEMA_VERSION_1_8
    assert normalized.metadata["saveback_commit_plan_schema"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["saveback_audit_plan_schema"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12


def test_normalize_workflow_definition_auto_migrates_1_9_payload_to_current_schema(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "schema-1-9-demo",
            "schema_version": SCHEMA_VERSION_1_9,
            "metadata": {
                "schema_version": SCHEMA_VERSION_1_9,
                "normalization_summary_schema": SCHEMA_VERSION_1_2,
                "compatibility_snapshot_schema": SCHEMA_VERSION_1_3,
                "resave_hint_schema": SCHEMA_VERSION_1_4,
                "compatibility_contract_schema": SCHEMA_VERSION_1_5,
                "saveback_policy_schema": SCHEMA_VERSION_1_6,
                "saveback_decision_schema": SCHEMA_VERSION_1_7,
                "auto_fix_plan_schema": SCHEMA_VERSION_1_8,
                "saveback_commit_plan_schema": SCHEMA_VERSION_1_9,
            },
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_export_table",
                    "params": {
                        "destination": "drive",
                        "description": "canonical-table-export",
                    },
                    "metadata": {
                        "schema_version": SCHEMA_VERSION_1_9,
                        "canonical_node_type": "gee_export_table",
                        "canonical_node_version": "1.0.0",
                    },
                },
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(SCHEMA_VERSION_1_9)
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], SCHEMA_VERSION_1_9)
    assert normalized.metadata["saveback_commit_plan_schema"] == SCHEMA_VERSION_1_9
    assert normalized.metadata["saveback_audit_plan_schema"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12


def test_normalize_workflow_definition_auto_migrates_1_10_payload_to_current_schema(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "schema-1-10-demo",
            "schema_version": SCHEMA_VERSION_1_10,
            "metadata": {
                "schema_version": SCHEMA_VERSION_1_10,
                "normalization_summary_schema": SCHEMA_VERSION_1_2,
                "compatibility_snapshot_schema": SCHEMA_VERSION_1_3,
                "resave_hint_schema": SCHEMA_VERSION_1_4,
                "compatibility_contract_schema": SCHEMA_VERSION_1_5,
                "saveback_policy_schema": SCHEMA_VERSION_1_6,
                "saveback_decision_schema": SCHEMA_VERSION_1_7,
                "auto_fix_plan_schema": SCHEMA_VERSION_1_8,
                "saveback_commit_plan_schema": SCHEMA_VERSION_1_9,
                "saveback_audit_plan_schema": SCHEMA_VERSION_1_10,
            },
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_export_table",
                    "params": {
                        "destination": "drive",
                        "description": "canonical-table-export",
                    },
                    "metadata": {
                        "schema_version": SCHEMA_VERSION_1_10,
                        "canonical_node_type": "gee_export_table",
                        "canonical_node_version": "1.0.0",
                    },
                },
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(SCHEMA_VERSION_1_10)
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], SCHEMA_VERSION_1_10)
    assert normalized.metadata["saveback_audit_plan_schema"] == SCHEMA_VERSION_1_10
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12


def test_normalize_workflow_definition_auto_migrates_1_11_payload_to_current_schema(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "schema-1-11-demo",
            "schema_version": SCHEMA_VERSION_1_11,
            "metadata": {
                "schema_version": SCHEMA_VERSION_1_11,
                "normalization_summary_schema": SCHEMA_VERSION_1_2,
                "compatibility_snapshot_schema": SCHEMA_VERSION_1_3,
                "resave_hint_schema": SCHEMA_VERSION_1_4,
                "compatibility_contract_schema": SCHEMA_VERSION_1_5,
                "saveback_policy_schema": SCHEMA_VERSION_1_6,
                "saveback_decision_schema": SCHEMA_VERSION_1_7,
                "auto_fix_plan_schema": SCHEMA_VERSION_1_8,
                "saveback_commit_plan_schema": SCHEMA_VERSION_1_9,
                "saveback_audit_plan_schema": SCHEMA_VERSION_1_10,
                "saveback_closure_plan_schema": SCHEMA_VERSION_1_11,
            },
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_export_table",
                    "params": {
                        "destination": "drive",
                        "description": "canonical-table-export",
                    },
                    "metadata": {
                        "schema_version": SCHEMA_VERSION_1_11,
                        "canonical_node_type": "gee_export_table",
                        "canonical_node_version": "1.0.0",
                    },
                },
            ],
        }
    )

    assert normalized.schema_version == CURRENT_SCHEMA_VERSION
    assert normalized.metadata["auto_migrated_from_schema_version"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["schema_upgrade_path"] == expected_upgrade_path(SCHEMA_VERSION_1_11)
    assert_schema_upgrade_notes(normalized.metadata["migration_notes"], SCHEMA_VERSION_1_11)
    assert normalized.metadata["saveback_closure_plan_schema"] == SCHEMA_VERSION_1_11
    assert normalized.metadata["saveback_terminal_plan_schema"] == SCHEMA_VERSION_1_12


def test_workflow_migrator_rejects_deprecated_node_type_in_compatibility_check() -> None:
    registry = NodeRegistry()
    registry.register(DeprecatedTestNode)
    registry.register(IdentityNode)
    migrator = WorkflowDefinitionMigrator(registry)
    workflow = WorkflowDefinition(
        workflow_id="deprecated-node-demo",
        nodes=[NodeSpec(node_id="n1", node_type="deprecated_test_node")],
    )

    with pytest.raises(
        WorkflowValidationError,
        match=(
            "node n1 uses deprecated node type deprecated_test_node; "
            "replacement available: identity; normalize workflow first"
        ),
    ):
        migrator.validate_compatibility(workflow)


def test_normalize_workflow_definition_replaces_deprecated_node_type(tmp_path) -> None:
    registry = NodeRegistry()
    registry.register(DeprecatedTestNode)
    service = WorkflowService(
        registry=registry,
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "deprecated-normalize-demo",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "deprecated_test_node",
                }
            ],
        }
    )

    node = normalized.nodes[0]
    assert node.node_type == "identity"
    assert any(
        note.get("node_id") == "n1"
        and note["migration"] == "deprecated_node_replaced"
        and note["from"] == "deprecated_test_node"
        and note["to"] == "identity"
        for note in normalized.metadata["migration_notes"]
    )


def test_diagnostics_exposes_workflow_schema_support(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    report = service.diagnose()

    assert report.checks["workflow_schema"]["status"] == "ok"
    assert report.checks["workflow_schema"]["current_schema_version"] == CURRENT_SCHEMA_VERSION
    assert report.checks["workflow_schema"]["auto_replace_deprecated_nodes"] is True
    assert CURRENT_SCHEMA_VERSION in report.checks["workflow_schema"]["supported_schema_versions"]
    for source_version in [
        LEGACY_SCHEMA_VERSION,
        SCHEMA_VERSION_1_0,
        SCHEMA_VERSION_1_1,
        SCHEMA_VERSION_1_2,
        SCHEMA_VERSION_1_3,
        SCHEMA_VERSION_1_4,
        SCHEMA_VERSION_1_5,
        SCHEMA_VERSION_1_6,
        SCHEMA_VERSION_1_7,
        SCHEMA_VERSION_1_8,
        SCHEMA_VERSION_1_9,
        SCHEMA_VERSION_1_10,
        SCHEMA_VERSION_1_11,
    ]:
        assert any(
            item["from"] == source_version
            and item["to"] == CURRENT_SCHEMA_VERSION
            and item["path"] == expected_upgrade_path(source_version)
            for item in report.checks["workflow_schema"]["schema_upgrade_paths"]
        )
    assert any(
        item["legacy_node_type"] == "gee_band_math"
        and item["replacement_node_type"] == "gee_raster_algebra"
        and item["parameter_migration_rules"]
        for item in report.checks["workflow_schema"]["node_type_replacements"]
    )
    assert any(
        item["node_type"] == "gee_export_image"
        and item["parameter_aliases"]["task_name"] == "description"
        for item in report.checks["workflow_schema"]["canonical_parameter_alias_nodes"]
    )
    assert any(
        item["node_type"] == "gee_time_series_stats"
        and item["parameter_aliases"]["date_field"] == "date_property"
        for item in report.checks["workflow_schema"]["canonical_parameter_alias_nodes"]
    )
    assert report.checks["workflow_schema"]["schema_support_summary"] == {
        "current_schema_version": CURRENT_SCHEMA_VERSION,
        "supported_schema_versions": [CURRENT_SCHEMA_VERSION],
        "auto_migrate_from_schema_versions": [
            LEGACY_SCHEMA_VERSION,
            SCHEMA_VERSION_1_0,
            SCHEMA_VERSION_1_1,
            SCHEMA_VERSION_1_2,
            SCHEMA_VERSION_1_3,
            SCHEMA_VERSION_1_4,
            SCHEMA_VERSION_1_5,
            SCHEMA_VERSION_1_6,
            SCHEMA_VERSION_1_7,
            SCHEMA_VERSION_1_8,
            SCHEMA_VERSION_1_9,
            SCHEMA_VERSION_1_10,
            SCHEMA_VERSION_1_11,
        ],
        "schema_upgrade_path_count": 13,
        "metadata_feature_count": 11,
        "terminal_plan_schema_version": CURRENT_SCHEMA_VERSION,
    }
    assert report.checks["workflow_schema"]["schema_support_notes"] == [
        "legacy payloads are auto-migrated to the current schema",
        "deprecated node types may be auto-replaced when a canonical replacement is registered",
        "schema_version 1.12 adds a terminal writeback plan for audit closure",
    ]
    assert {"schema_version": SCHEMA_VERSION_1_2, "field": "normalization_summary"} in report.checks[
        "workflow_schema"
    ]["workflow_metadata_features"]
    assert {
        "group": "saveback_terminal_closure",
        "schema_versions": [SCHEMA_VERSION_1_11, CURRENT_SCHEMA_VERSION],
        "fields": ["saveback_closure_plan", "saveback_terminal_plan"],
    } in report.checks["workflow_schema"]["workflow_metadata_feature_groups"]
    assert report.checks["workflow_schema"]["saveback_terminal_plan_summary"] == {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "field": "saveback_terminal_plan",
        "description": "terminal audit writeback summary for API consumers",
        "subfields": ["action", "reasons", "summary"],
    }
    response_schema = report.checks["workflow_schema"]["saveback_terminal_plan_response_schema"]
    assert response_schema["schema_version"] == CURRENT_SCHEMA_VERSION
    assert response_schema["field"] == "saveback_terminal_plan"
    assert response_schema["response_fields"] == ["action", "reasons", "summary"]
    assert response_schema["response_model"]["title"] == "TerminalPlanResponse"
    assert response_schema["response_model"]["properties"]["summary"]["$ref"] == "#/$defs/TerminalPlanSummary"
    assert response_schema["response_model"]["$defs"]["TerminalPlanSummary"]["title"] == "TerminalPlanSummary"
    assert {"schema_version": SCHEMA_VERSION_1_3, "field": "compatibility_snapshot"} in report.checks[
        "workflow_schema"
    ]["workflow_metadata_features"]
    assert {"schema_version": SCHEMA_VERSION_1_4, "field": "resave_hint"} in report.checks[
        "workflow_schema"
    ]["workflow_metadata_features"]
    assert {"schema_version": SCHEMA_VERSION_1_5, "field": "compatibility_contract"} in report.checks[
        "workflow_schema"
    ]["workflow_metadata_features"]
    assert {"schema_version": SCHEMA_VERSION_1_6, "field": "saveback_policy"} in report.checks[
        "workflow_schema"
    ]["workflow_metadata_features"]
    assert {"schema_version": SCHEMA_VERSION_1_7, "field": "saveback_decision"} in report.checks[
        "workflow_schema"
    ]["workflow_metadata_features"]
    assert {"schema_version": SCHEMA_VERSION_1_8, "field": "auto_fix_plan"} in report.checks[
        "workflow_schema"
    ]["workflow_metadata_features"]
    assert {"schema_version": SCHEMA_VERSION_1_9, "field": "saveback_commit_plan"} in report.checks[
        "workflow_schema"
    ]["workflow_metadata_features"]
    assert {"schema_version": SCHEMA_VERSION_1_10, "field": "saveback_audit_plan"} in report.checks[
        "workflow_schema"
    ]["workflow_metadata_features"]
    assert {"schema_version": SCHEMA_VERSION_1_11, "field": "saveback_closure_plan"} in report.checks[
        "workflow_schema"
    ]["workflow_metadata_features"]
    assert {"schema_version": SCHEMA_VERSION_1_12, "field": "saveback_terminal_plan"} in report.checks[
        "workflow_schema"
    ]["workflow_metadata_features"]
    assert any(
        item["schema_version"] == CURRENT_SCHEMA_VERSION
        and item["fields"] == ["saveback_terminal_plan", "saveback_terminal_plan_schema"]
        for item in report.checks["workflow_schema"]["workflow_metadata_feature_matrix"]
    )


def test_submit_workflow_accepts_legacy_payload_and_executes(tmp_path) -> None:
    adapter = WorkflowContractAdapter(
        WorkflowService(settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)))
    )

    result = adapter.submit_workflow(
        workflow={
            "workflow_id": "legacy-submit-demo",
            "nodes": [
                {"node_id": "n1", "node_type": "literal", "params": {"value": "ok"}},
                {"node_id": "n2", "node_type": "identity"},
            ],
            "edges": [
                {
                    "source_node_id": "n1",
                    "source_port": "value",
                    "target_node_id": "n2",
                    "target_port": "value",
                }
            ],
        },
        context=ExecutionContext(workflow_id="legacy-submit-demo"),
    )

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.value"] == "ok"


def test_migrator_rewrites_legacy_node_type_and_alias_params(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "legacy-band-math-demo",
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_band_math",
                    "params": {
                        "expression": "(nir - red) / (nir + red)",
                        "variables": {"nir": "B8", "red": "B4"},
                        "output_band": "ndvi_like",
                    },
                }
            ],
        }
    )

    node = normalized.nodes[0]
    assert node.node_type == "gee_raster_algebra"
    assert node.params["band_map"] == {"nir": "B8", "red": "B4"}
    assert "variables" not in node.params
    assert any(
        note.get("node_id") == "n1" and note["migration"] == "node_type_replaced"
        for note in normalized.metadata["migration_notes"]
    )


def test_migrator_applies_second_batch_replacement_rules_for_real_legacy_nodes(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "legacy-real-node-rules-demo",
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_band_math",
                    "params": {
                        "expression_text": "(nir - red) / (nir + red)",
                        "variables": {"nir": "B8", "red": "B4"},
                        "result_band": "ndvi_like",
                    },
                },
                {
                    "node_id": "n2",
                    "node_type": "gee_threshold",
                    "params": {
                        "source_band": "ndvi",
                        "threshold_values": [0.2, 0.4],
                        "labels": [1, 2, 3],
                        "result_band": "ndvi_class",
                    },
                },
                {
                    "node_id": "n3",
                    "node_type": "gee_remap",
                    "params": {
                        "source_band": "landcover",
                        "remap_rules": [{"match": 10, "value": 1}],
                        "default": 99,
                        "result_band": "landcover_class",
                    },
                },
            ],
        }
    )

    raster_node = normalized.nodes[0]
    threshold_node = normalized.nodes[1]
    remap_node = normalized.nodes[2]

    assert raster_node.node_type == "gee_raster_algebra"
    assert raster_node.params["expression"] == "(nir - red) / (nir + red)"
    assert raster_node.params["band_map"] == {"nir": "B8", "red": "B4"}
    assert raster_node.params["output_band"] == "ndvi_like"
    assert "expression_text" not in raster_node.params
    assert "result_band" not in raster_node.params

    assert threshold_node.node_type == "gee_threshold_classify"
    assert threshold_node.params["band"] == "ndvi"
    assert threshold_node.params["thresholds"] == [0.2, 0.4]
    assert threshold_node.params["class_values"] == [1, 2, 3]
    assert threshold_node.params["output_band"] == "ndvi_class"
    assert "source_band" not in threshold_node.params
    assert "threshold_values" not in threshold_node.params
    assert "labels" not in threshold_node.params

    assert remap_node.node_type == "gee_reclassify"
    assert remap_node.params["band"] == "landcover"
    assert remap_node.params["rules"] == [{"match": 10, "value": 1}]
    assert remap_node.params["default_value"] == 99
    assert remap_node.params["output_band"] == "landcover_class"
    assert "source_band" not in remap_node.params
    assert "remap_rules" not in remap_node.params
    assert "default" not in remap_node.params

    assert any(
        note.get("node_id") == "n1"
        and note["migration"] == "parameter_rule_applied"
        and note["from"] == "expression_text"
        and note["to"] == "expression"
        for note in normalized.metadata["migration_notes"]
    )
    assert any(
        note.get("node_id") == "n2"
        and note["migration"] == "parameter_rule_applied"
        and note["from"] == "threshold_values"
        and note["to"] == "thresholds"
        for note in normalized.metadata["migration_notes"]
    )
    assert any(
        note.get("node_id") == "n3"
        and note["migration"] == "parameter_rule_applied"
        and note["from"] == "default"
        and note["to"] == "default_value"
        for note in normalized.metadata["migration_notes"]
    )


def test_migrator_rewrites_current_node_parameter_aliases(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "current-alias-demo",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_threshold_classify",
                    "params": {
                        "band": "ndvi",
                        "thresholds": [0.2, 0.4],
                        "classes": [1, 2, 3],
                        "output_band": "ndvi_class",
                    },
                }
            ],
        }
    )

    node = normalized.nodes[0]
    assert node.params["class_values"] == [1, 2, 3]
    assert "classes" not in node.params
    assert any(
        note["migration"] == "parameter_aliased"
        and note["from"] == "classes"
        and note["to"] == "class_values"
        for note in normalized.metadata["migration_notes"]
    )


def test_workflow_migrator_reports_legacy_parameter_aliases_in_compatibility_check(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )
    migrator = WorkflowDefinitionMigrator(service._registry)
    workflow = WorkflowDefinition(
        workflow_id="compatibility-alias-demo",
        schema_version=CURRENT_SCHEMA_VERSION,
        nodes=[
            NodeSpec(
                node_id="n1",
                node_type="gee_export_image",
                params={"destination": "drive", "task_name": "legacy-name"},
            )
        ],
    )

    with pytest.raises(
        WorkflowValidationError,
        match=(
            "node n1 uses legacy parameter aliases "
            "task_name->description; normalize workflow first"
        ),
    ):
        migrator.validate_compatibility(workflow)


def test_normalize_workflow_definition_applies_deprecated_replacement_parameter_rules(tmp_path) -> None:
    registry = NodeRegistry()
    registry.register(ConfiguredReplacementNode)
    registry.register(DeprecatedConfiguredNode)
    service = WorkflowService(
        registry=registry,
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "deprecated-configured-demo",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "deprecated_configured_node",
                    "params": {
                        "legacy_value": "abc",
                        "legacy_enabled": 1,
                        "legacy_tag": "primary",
                    },
                }
            ],
        }
    )

    node = normalized.nodes[0]
    assert node.node_type == "configured_replacement_node"
    assert node.params["value"] == "abc"
    assert node.params["enabled"] is True
    assert node.params["tags"] == ["primary"]
    assert node.params["mode"] == "compat"
    assert "legacy_value" not in node.params
    assert "legacy_enabled" not in node.params
    assert "legacy_tag" not in node.params
    assert any(
        note.get("node_id") == "n1"
        and note["migration"] == "deprecated_node_replaced"
        and note["from"] == "deprecated_configured_node"
        and note["to"] == "configured_replacement_node"
        for note in normalized.metadata["migration_notes"]
    )
    assert any(
        note.get("node_id") == "n1"
        and note["migration"] == "parameter_rule_applied"
        and note["from"] == "legacy_enabled"
        and note["to"] == "enabled"
        and note["strategy"] == "bool"
        for note in normalized.metadata["migration_notes"]
    )
    assert any(
        note.get("node_id") == "n1"
        and note["migration"] == "parameter_rule_applied"
        and note["to"] == "mode"
        and note["strategy"] == "literal"
        for note in normalized.metadata["migration_notes"]
    )


def test_migrator_fills_workflow_and_node_defaults_from_canonical_specs(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "default-fill-demo",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "sample_input",
                    "params": {},
                },
                {
                    "node_id": "n2",
                    "node_type": "gee_export_image",
                    "params": {"destination": "manifest"},
                },
            ],
        }
    )

    assert normalized.version == "1.0.0"
    assert normalized.inputs == {}
    assert normalized.edges == []
    assert normalized.runtime_policy.max_retries_per_node == 0
    assert normalized.storage_policy.backend is None

    sample_node = normalized.nodes[0]
    export_node = normalized.nodes[1]
    assert sample_node.params["default"] == 0
    assert export_node.params["description"] == "gee-export-image"
    assert export_node.params["file_name_prefix"] == "gee_export_image"
    assert export_node.params["scale"] == 10
    assert export_node.params["start_task"] is False
    assert any(
        note["migration"] == "workflow_defaults_filled"
        and set(note["fields"]) == {"version", "inputs", "edges", "runtime_policy", "storage_policy"}
        for note in normalized.metadata["migration_notes"]
    )
    assert any(
        note.get("node_id") == "n1"
        and note["migration"] == "default_params_filled"
        and note["fields"] == ["default"]
        for note in normalized.metadata["migration_notes"]
    )
    assert any(
        note.get("node_id") == "n2"
        and note["migration"] == "default_params_filled"
        and set(note["fields"]) == {"description", "file_name_prefix", "scale", "start_task"}
        for note in normalized.metadata["migration_notes"]
    )


def test_migrator_rewrites_second_batch_aliases_for_batch_and_export_nodes(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "second-batch-alias-demo",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "batch_map",
                    "params": {
                        "map_key": "tile_id",
                    },
                },
                {
                    "node_id": "n2",
                    "node_type": "gee_time_series_stats",
                    "params": {
                        "band": "B8",
                        "date_field": "acquired_at",
                        "value_field": "series_value",
                    },
                },
                {
                    "node_id": "n3",
                    "node_type": "gee_export_image",
                    "params": {
                        "destination": "drive",
                        "task_name": "legacy-export",
                        "file_prefix": "legacy_export",
                        "auto_start": True,
                        "bucket_name": "legacy-bucket",
                    },
                },
            ],
        }
    )

    batch_map_node = normalized.nodes[0]
    series_node = normalized.nodes[1]
    export_node = normalized.nodes[2]

    assert batch_map_node.params["item_key"] == "tile_id"
    assert "map_key" not in batch_map_node.params
    assert series_node.params["date_property"] == "acquired_at"
    assert series_node.params["value_property"] == "series_value"
    assert "date_field" not in series_node.params
    assert "value_field" not in series_node.params
    assert export_node.params["description"] == "legacy-export"
    assert export_node.params["file_name_prefix"] == "legacy_export"
    assert export_node.params["start_task"] is True
    assert export_node.params["bucket"] == "legacy-bucket"
    assert "task_name" not in export_node.params
    assert "file_prefix" not in export_node.params
    assert "auto_start" not in export_node.params
    assert "bucket_name" not in export_node.params
    assert any(
        note.get("node_id") == "n1"
        and note["migration"] == "parameter_aliased"
        and note["from"] == "map_key"
        and note["to"] == "item_key"
        for note in normalized.metadata["migration_notes"]
    )
    assert any(
        note.get("node_id") == "n2"
        and note["migration"] == "parameter_aliased"
        and note["from"] == "date_field"
        and note["to"] == "date_property"
        for note in normalized.metadata["migration_notes"]
    )
    assert any(
        note.get("node_id") == "n3"
        and note["migration"] == "parameter_aliased"
        and note["from"] == "task_name"
        and note["to"] == "description"
        for note in normalized.metadata["migration_notes"]
    )


def test_compatibility_contract_exposes_real_node_alias_surface(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "compatibility-contract-demo",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_raster_algebra",
                    "params": {
                        "expression": "nir / red",
                        "variables": {"nir": "B8", "red": "B4"},
                    },
                },
                {
                    "node_id": "n2",
                    "node_type": "gee_reclassify",
                    "params": {
                        "band": "landcover",
                        "rules": [{"match": 10, "value": 1}],
                        "fallback_value": 99,
                        "output_band": "landcover_class",
                    },
                },
                {
                    "node_id": "n3",
                    "node_type": "gee_export_table",
                    "params": {
                        "destination": "drive",
                        "task_name": "legacy-table-export",
                        "file_prefix": "legacy_table_export",
                        "auto_start": True,
                        "bucket_name": "legacy-table-bucket",
                    },
                },
            ],
        }
    )

    compatibility_contract = normalized.metadata["compatibility_contract"]
    assert compatibility_contract["schema_version"] == SCHEMA_VERSION_1_5
    assert compatibility_contract["resave_recommended"] is True
    assert compatibility_contract["node_types_with_alias_support"] == [
        "gee_export_table",
        "gee_raster_algebra",
        "gee_reclassify",
    ]
    assert compatibility_contract["nodes_requiring_resave"] == ["n1", "n2", "n3"]

    node_contracts = {item["node_id"]: item for item in compatibility_contract["nodes"]}
    assert node_contracts["n1"]["supported_parameter_aliases"] == {"variables": "band_map"}
    assert node_contracts["n1"]["applied_parameter_aliases"] == [{"from": "variables", "to": "band_map"}]
    assert node_contracts["n2"]["supported_parameter_aliases"] == {"fallback_value": "default_value"}
    assert node_contracts["n2"]["applied_parameter_aliases"] == [
        {"from": "fallback_value", "to": "default_value"}
    ]
    assert node_contracts["n3"]["supported_parameter_aliases"] == {
        "task_name": "description",
        "file_prefix": "file_name_prefix",
        "auto_start": "start_task",
        "bucket_name": "bucket",
    }
    assert node_contracts["n3"]["applied_parameter_aliases"] == [
        {"from": "task_name", "to": "description"},
        {"from": "file_prefix", "to": "file_name_prefix"},
        {"from": "auto_start", "to": "start_task"},
        {"from": "bucket_name", "to": "bucket"},
    ]


def test_saveback_policy_exposes_canonical_writeback_actions(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "saveback-policy-demo",
            "schema_version": CURRENT_SCHEMA_VERSION,
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_raster_algebra",
                    "params": {
                        "expression": "nir / red",
                        "variables": {"nir": "B8", "red": "B4"},
                    },
                },
                {
                    "node_id": "n2",
                    "node_type": "gee_export_image",
                    "params": {
                        "destination": "drive",
                        "task_name": "legacy-export",
                        "file_prefix": "legacy_export",
                    },
                },
            ],
        }
    )

    saveback_policy = normalized.metadata["saveback_policy"]
    assert saveback_policy["schema_version"] == SCHEMA_VERSION_1_6
    assert saveback_policy["saveback_required"] is True
    assert saveback_policy["recommended_mode"] == "canonical_writeback"
    assert saveback_policy["workflow_metadata_fields_to_persist"] == [
        "normalization_summary",
        "compatibility_snapshot",
        "resave_hint",
        "compatibility_contract",
        "saveback_policy",
    ]
    assert saveback_policy["nodes_requiring_canonical_writeback"] == ["n1", "n2"]

    node_actions = {item["node_id"]: item for item in saveback_policy["node_actions"]}
    assert node_actions["n1"] == {
        "node_id": "n1",
        "action": "canonical_writeback",
        "canonical_node_type": "gee_raster_algebra",
        "legacy_node_type": None,
        "fields_to_drop": ["variables"],
        "fields_to_write": ["band_map", "output_band"],
        "reason_codes": ["parameter_aliases_normalized", "default_parameters_filled"],
    }
    assert node_actions["n2"] == {
        "node_id": "n2",
        "action": "canonical_writeback",
        "canonical_node_type": "gee_export_image",
        "legacy_node_type": None,
        "fields_to_drop": ["file_prefix", "task_name"],
        "fields_to_write": ["description", "file_name_prefix", "scale", "start_task"],
        "reason_codes": ["parameter_aliases_normalized", "default_parameters_filled"],
    }


def test_saveback_decision_distinguishes_required_and_recommended_nodes(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "saveback-decision-demo",
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_band_math",
                    "params": {
                        "expression_text": "(nir - red) / (nir + red)",
                        "variables": {"nir": "B8", "red": "B4"},
                    },
                },
                {
                    "node_id": "n2",
                    "node_type": "gee_time_series_stats",
                    "params": {
                        "band": "B8",
                        "date_field": "acquired_at",
                        "value_field": "series_value",
                    },
                },
                {
                    "node_id": "n3",
                    "node_type": "gee_threshold_classify",
                    "params": {
                        "band": "ndvi",
                        "thresholds": [0.2, 0.4],
                        "classes": [1, 2, 3],
                    },
                },
            ],
        }
    )

    saveback_decision = normalized.metadata["saveback_decision"]
    assert saveback_decision["schema_version"] == SCHEMA_VERSION_1_7
    assert saveback_decision["highest_severity"] == "required"
    assert saveback_decision["required_node_ids"] == ["n1"]
    assert saveback_decision["recommended_node_ids"] == ["n2", "n3"]
    assert saveback_decision["recommended_editor_mode"] == "block_save_until_writeback"
    assert saveback_decision["can_execute_without_saveback"] is True

    node_decisions = {item["node_id"]: item for item in saveback_decision["node_decisions"]}
    assert node_decisions["n1"]["severity"] == "required"
    assert node_decisions["n1"]["reason_codes"] == [
        "node_type_rewritten",
        "parameter_rules_applied",
        "default_parameters_filled",
    ]
    assert node_decisions["n2"]["severity"] == "recommended"
    assert node_decisions["n2"]["reason_codes"] == [
        "parameter_aliases_normalized",
        "default_parameters_filled",
    ]
    assert node_decisions["n3"]["severity"] == "recommended"
    assert node_decisions["n3"]["reason_codes"] == [
        "parameter_aliases_normalized",
        "default_parameters_filled",
    ]


def test_auto_fix_plan_exposes_batch_canonical_writeback_steps(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "auto-fix-plan-demo",
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_band_math",
                    "params": {
                        "expression_text": "(nir - red) / (nir + red)",
                        "variables": {"nir": "B8", "red": "B4"},
                    },
                },
                {
                    "node_id": "n2",
                    "node_type": "gee_export_table",
                    "params": {
                        "destination": "drive",
                        "task_name": "legacy-table-export",
                    },
                },
            ],
        }
    )

    auto_fix_plan = normalized.metadata["auto_fix_plan"]
    assert auto_fix_plan["schema_version"] == SCHEMA_VERSION_1_8
    assert auto_fix_plan["plan_mode"] == "batch_canonical_writeback"
    assert auto_fix_plan["highest_severity"] == "required"
    assert auto_fix_plan["can_auto_fix"] is True
    assert auto_fix_plan["auto_fixable_node_ids"] == ["n1", "n2"]
    assert auto_fix_plan["manual_review_node_ids"] == []
    assert auto_fix_plan["workflow_metadata_fields_to_persist"] == [
        "normalization_summary",
        "compatibility_snapshot",
        "resave_hint",
        "compatibility_contract",
        "saveback_policy",
        "saveback_decision",
        "auto_fix_plan",
    ]
    assert auto_fix_plan["steps"] == [
        {
            "step": "persist_workflow_metadata",
            "fields": [
                "normalization_summary",
                "compatibility_snapshot",
                "resave_hint",
                "compatibility_contract",
                "saveback_policy",
                "saveback_decision",
                "auto_fix_plan",
            ],
        },
        {
            "step": "canonical_writeback_nodes",
            "node_ids": ["n1", "n2"],
        },
    ]

    node_plans = {item["node_id"]: item for item in auto_fix_plan["node_plans"]}
    assert node_plans["n1"] == {
        "node_id": "n1",
        "severity": "required",
        "auto_fix": True,
        "manual_review": False,
        "editor_action": "apply_canonical_writeback",
        "canonical_node_type": "gee_raster_algebra",
        "legacy_node_type": "gee_band_math",
        "fields_to_drop": ["expression_text"],
        "fields_to_write": ["expression", "output_band"],
        "reason_codes": [
            "node_type_rewritten",
            "parameter_rules_applied",
            "default_parameters_filled",
        ],
    }
    assert node_plans["n2"] == {
        "node_id": "n2",
        "severity": "recommended",
        "auto_fix": True,
        "manual_review": False,
        "editor_action": "apply_canonical_writeback",
        "canonical_node_type": "gee_export_table",
        "legacy_node_type": None,
        "fields_to_drop": ["task_name"],
        "fields_to_write": ["description", "file_name_prefix", "start_task"],
        "reason_codes": ["parameter_aliases_normalized", "default_parameters_filled"],
    }


def test_saveback_commit_plan_exposes_confirmation_and_review_barriers(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "saveback-commit-plan-demo",
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_band_math",
                    "params": {
                        "expression_text": "(nir - red) / (nir + red)",
                        "variables": {"nir": "B8", "red": "B4"},
                    },
                },
                {
                    "node_id": "n2",
                    "node_type": "gee_export_table",
                    "params": {
                        "destination": "drive",
                        "task_name": "legacy-table-export",
                    },
                },
            ],
        }
    )

    saveback_commit_plan = normalized.metadata["saveback_commit_plan"]
    assert saveback_commit_plan["schema_version"] == SCHEMA_VERSION_1_9
    assert saveback_commit_plan["commit_barrier"] == "confirm_required_changes"
    assert saveback_commit_plan["requires_confirmation"] is True
    assert saveback_commit_plan["requires_review"] is True
    assert saveback_commit_plan["confirm_before_persist_node_ids"] == ["n1"]
    assert saveback_commit_plan["review_before_persist_node_ids"] == ["n2"]
    assert saveback_commit_plan["workflow_metadata_fields_to_persist"] == [
        "normalization_summary",
        "compatibility_snapshot",
        "resave_hint",
        "compatibility_contract",
        "saveback_policy",
        "saveback_decision",
        "auto_fix_plan",
        "saveback_commit_plan",
    ]
    assert saveback_commit_plan["steps"] == [
        {
            "step": "apply_auto_fixes",
            "node_ids": ["n1", "n2"],
        },
        {
            "step": "validate_before_persist",
            "node_ids": ["n1", "n2"],
        },
        {
            "step": "persist_workflow_definition",
            "fields": [
                "normalization_summary",
                "compatibility_snapshot",
                "resave_hint",
                "compatibility_contract",
                "saveback_policy",
                "saveback_decision",
                "auto_fix_plan",
                "saveback_commit_plan",
            ],
        },
    ]

    node_commits = {item["node_id"]: item for item in saveback_commit_plan["node_commits"]}
    assert node_commits["n1"] == {
        "node_id": "n1",
        "severity": "required",
        "commit_mode": "confirm_before_persist",
        "persist_after_apply": True,
        "review_required": True,
        "canonical_node_type": "gee_raster_algebra",
        "legacy_node_type": "gee_band_math",
        "fields_to_drop": ["expression_text"],
        "fields_to_write": ["expression", "output_band"],
        "validation_checks": [
            "canonical_payload_consistency",
            "fields_written_match_plan",
            "user_confirmation_recorded",
        ],
    }
    assert node_commits["n2"] == {
        "node_id": "n2",
        "severity": "recommended",
        "commit_mode": "review_before_persist",
        "persist_after_apply": True,
        "review_required": True,
        "canonical_node_type": "gee_export_table",
        "legacy_node_type": None,
        "fields_to_drop": ["task_name"],
        "fields_to_write": ["description", "file_name_prefix", "start_task"],
        "validation_checks": [
            "canonical_payload_consistency",
            "fields_written_match_plan",
        ],
    }


def test_saveback_audit_plan_exposes_audit_receipts_and_fields(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "saveback-audit-plan-demo",
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_band_math",
                    "params": {
                        "expression_text": "(nir - red) / (nir + red)",
                        "variables": {"nir": "B8", "red": "B4"},
                    },
                },
                {
                    "node_id": "n2",
                    "node_type": "gee_export_table",
                    "params": {
                        "destination": "drive",
                        "task_name": "legacy-table-export",
                    },
                },
            ],
        }
    )

    saveback_audit_plan = normalized.metadata["saveback_audit_plan"]
    assert saveback_audit_plan["schema_version"] == SCHEMA_VERSION_1_10
    assert saveback_audit_plan["target_schema_version"] == CURRENT_SCHEMA_VERSION
    assert saveback_audit_plan["audit_mode"] == "persist_saveback_audit"
    assert saveback_audit_plan["requires_audit_record"] is True
    assert saveback_audit_plan["confirmation_audit_node_ids"] == ["n1"]
    assert saveback_audit_plan["review_audit_node_ids"] == ["n2"]
    assert saveback_audit_plan["workflow_audit_fields"] == [
        "commit_barrier",
        "confirmed_node_ids",
        "reviewed_node_ids",
        "validation_results",
        "persisted_at",
    ]
    assert saveback_audit_plan["workflow_metadata_fields_to_persist"] == [
        "normalization_summary",
        "compatibility_snapshot",
        "resave_hint",
        "compatibility_contract",
        "saveback_policy",
        "saveback_decision",
        "auto_fix_plan",
        "saveback_commit_plan",
        "saveback_audit_plan",
    ]
    assert saveback_audit_plan["steps"] == [
        {
            "step": "collect_confirmation_records",
            "node_ids": ["n1"],
        },
        {
            "step": "collect_review_records",
            "node_ids": ["n2"],
        },
        {
            "step": "collect_validation_results",
            "node_ids": ["n1", "n2"],
        },
        {
            "step": "persist_saveback_audit",
            "fields": [
                "normalization_summary",
                "compatibility_snapshot",
                "resave_hint",
                "compatibility_contract",
                "saveback_policy",
                "saveback_decision",
                "auto_fix_plan",
                "saveback_commit_plan",
                "saveback_audit_plan",
            ],
        },
    ]

    node_audits = {item["node_id"]: item for item in saveback_audit_plan["node_audits"]}
    assert node_audits["n1"] == {
        "node_id": "n1",
        "severity": "required",
        "audit_mode": "confirmation_receipt",
        "confirmation_record_required": True,
        "review_record_required": False,
        "persist_audit_after_save": True,
        "canonical_node_type": "gee_raster_algebra",
        "legacy_node_type": "gee_band_math",
        "fields_to_drop": ["expression_text"],
        "fields_to_write": ["expression", "output_band"],
        "validation_checks": [
            "canonical_payload_consistency",
            "fields_written_match_plan",
            "user_confirmation_recorded",
        ],
        "audit_fields": [
            "confirmed_by",
            "confirmed_at",
            "validation_results",
            "persisted_fields",
        ],
    }
    assert node_audits["n2"] == {
        "node_id": "n2",
        "severity": "recommended",
        "audit_mode": "review_receipt",
        "confirmation_record_required": False,
        "review_record_required": True,
        "persist_audit_after_save": True,
        "canonical_node_type": "gee_export_table",
        "legacy_node_type": None,
        "fields_to_drop": ["task_name"],
        "fields_to_write": ["description", "file_name_prefix", "start_task"],
        "validation_checks": [
            "canonical_payload_consistency",
            "fields_written_match_plan",
        ],
        "audit_fields": [
            "reviewed_by",
            "reviewed_at",
            "validation_results",
            "persisted_fields",
        ],
    }


def test_saveback_closure_plan_exposes_batch_writeback_and_closure_status(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "saveback-closure-plan-demo",
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_band_math",
                    "params": {
                        "expression_text": "(nir - red) / (nir + red)",
                        "variables": {"nir": "B8", "red": "B4"},
                    },
                },
                {
                    "node_id": "n2",
                    "node_type": "gee_export_table",
                    "params": {
                        "destination": "drive",
                        "task_name": "legacy-table-export",
                    },
                },
            ],
        }
    )

    saveback_closure_plan = normalized.metadata["saveback_closure_plan"]
    assert saveback_closure_plan["schema_version"] == SCHEMA_VERSION_1_11
    assert saveback_closure_plan["target_schema_version"] == CURRENT_SCHEMA_VERSION
    assert saveback_closure_plan["closure_mode"] == "batch_writeback_closure"
    assert saveback_closure_plan["requires_closure_writeback"] is True
    assert saveback_closure_plan["batch_writeback_node_ids"] == ["n1", "n2"]
    assert saveback_closure_plan["pending_closure_node_ids"] == ["n1", "n2"]
    assert saveback_closure_plan["workflow_closure_status_fields"] == [
        "audit_result_status",
        "audit_persisted_at",
        "closed_node_ids",
        "pending_closure_node_ids",
        "closure_completed_at",
    ]
    assert saveback_closure_plan["workflow_metadata_fields_to_persist"] == [
        "normalization_summary",
        "compatibility_snapshot",
        "resave_hint",
        "compatibility_contract",
        "saveback_policy",
        "saveback_decision",
        "auto_fix_plan",
        "saveback_commit_plan",
        "saveback_audit_plan",
        "saveback_closure_plan",
    ]
    assert saveback_closure_plan["steps"] == [
        {
            "step": "collect_audit_writeback_payloads",
            "node_ids": ["n1", "n2"],
        },
        {
            "step": "writeback_node_audit_results",
            "node_ids": ["n1", "n2"],
        },
        {
            "step": "update_workflow_closure_status",
            "fields": [
                "audit_result_status",
                "audit_persisted_at",
                "closed_node_ids",
                "pending_closure_node_ids",
                "closure_completed_at",
            ],
        },
        {
            "step": "persist_closed_workflow_definition",
            "fields": [
                "normalization_summary",
                "compatibility_snapshot",
                "resave_hint",
                "compatibility_contract",
                "saveback_policy",
                "saveback_decision",
                "auto_fix_plan",
                "saveback_commit_plan",
                "saveback_audit_plan",
                "saveback_closure_plan",
            ],
        },
    ]

    node_closures = {item["node_id"]: item for item in saveback_closure_plan["node_closures"]}
    assert node_closures["n1"] == {
        "node_id": "n1",
        "severity": "required",
        "closure_mode": "writeback_confirmation_receipt",
        "closure_required": True,
        "batch_writeback_eligible": True,
        "close_after_writeback": True,
        "canonical_node_type": "gee_raster_algebra",
        "legacy_node_type": "gee_band_math",
        "fields_to_drop": ["expression_text"],
        "fields_to_write": ["expression", "output_band"],
        "audit_fields": [
            "confirmed_by",
            "confirmed_at",
            "validation_results",
            "persisted_fields",
        ],
        "closure_status_fields": [
            "audit_result_status",
            "audit_persisted_at",
            "closure_status",
        ],
        "closure_checks": [
            "canonical_payload_consistency",
            "fields_written_match_plan",
            "user_confirmation_recorded",
            "audit_receipt_persisted",
        ],
    }
    assert node_closures["n2"] == {
        "node_id": "n2",
        "severity": "recommended",
        "closure_mode": "writeback_review_receipt",
        "closure_required": True,
        "batch_writeback_eligible": True,
        "close_after_writeback": True,
        "canonical_node_type": "gee_export_table",
        "legacy_node_type": None,
        "fields_to_drop": ["task_name"],
        "fields_to_write": ["description", "file_name_prefix", "start_task"],
        "audit_fields": [
            "reviewed_by",
            "reviewed_at",
            "validation_results",
            "persisted_fields",
        ],
        "closure_status_fields": [
            "audit_result_status",
            "audit_persisted_at",
            "closure_status",
        ],
        "closure_checks": [
            "canonical_payload_consistency",
            "fields_written_match_plan",
            "audit_receipt_persisted",
        ],
    }


def test_saveback_terminal_plan_exposes_audit_summary_and_terminal_writeback_strategy(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "saveback-terminal-plan-demo",
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "gee_band_math",
                    "params": {
                        "expression_text": "(nir - red) / (nir + red)",
                        "variables": {"nir": "B8", "red": "B4"},
                    },
                },
                {
                    "node_id": "n2",
                    "node_type": "gee_export_table",
                    "params": {
                        "destination": "drive",
                        "task_name": "legacy-table-export",
                    },
                },
            ],
        }
    )

    saveback_terminal_plan = normalized.metadata["saveback_terminal_plan"]
    assert saveback_terminal_plan["schema_version"] == SCHEMA_VERSION_1_12
    assert saveback_terminal_plan["target_schema_version"] == CURRENT_SCHEMA_VERSION
    assert saveback_terminal_plan["terminal_mode"] == "writeback_audit_terminal_state"
    assert saveback_terminal_plan["requires_terminal_writeback"] is True
    assert saveback_terminal_plan["terminal_writeback_node_ids"] == ["n1", "n2"]
    assert saveback_terminal_plan["closed_terminal_node_ids"] == ["n1", "n2"]
    assert saveback_terminal_plan["required_terminal_node_ids"] == ["n1"]
    assert saveback_terminal_plan["recommended_terminal_node_ids"] == ["n2"]
    assert saveback_terminal_plan["audit_result_summary"] == {
        "total_terminal_nodes": 2,
        "terminal_writeback_required_count": 2,
        "closed_terminal_count": 2,
        "required_terminal_count": 1,
        "recommended_terminal_count": 1,
        "highest_severity": "required",
    }
    assert saveback_terminal_plan["terminal_state"] == "terminal_writeback_required"
    assert saveback_terminal_plan["terminal_state_writeback_strategy"] == {
        "pending_terminal_state": "terminal_writeback_required",
        "completed_terminal_state": "terminal_writeback_completed",
        "terminal_state_timestamp_field": "terminal_state_updated_at",
    }
    assert saveback_terminal_plan["workflow_audit_summary_fields"] == [
        "audit_result_summary",
        "required_terminal_node_ids",
        "recommended_terminal_node_ids",
        "terminal_state",
        "terminal_state_updated_at",
    ]
    assert saveback_terminal_plan["workflow_metadata_fields_to_persist"] == [
        "normalization_summary",
        "compatibility_snapshot",
        "resave_hint",
        "compatibility_contract",
        "saveback_policy",
        "saveback_decision",
        "auto_fix_plan",
        "saveback_commit_plan",
        "saveback_audit_plan",
        "saveback_closure_plan",
        "saveback_terminal_plan",
    ]
    assert saveback_terminal_plan["steps"] == [
        {
            "step": "summarize_audit_results",
            "node_ids": ["n1", "n2"],
        },
        {
            "step": "writeback_terminal_node_states",
            "node_ids": ["n1", "n2"],
        },
        {
            "step": "writeback_workflow_audit_summary",
            "fields": [
                "audit_result_summary",
                "required_terminal_node_ids",
                "recommended_terminal_node_ids",
                "terminal_state",
                "terminal_state_updated_at",
            ],
        },
        {
            "step": "persist_terminal_workflow_definition",
            "fields": [
                "normalization_summary",
                "compatibility_snapshot",
                "resave_hint",
                "compatibility_contract",
                "saveback_policy",
                "saveback_decision",
                "auto_fix_plan",
                "saveback_commit_plan",
                "saveback_audit_plan",
                "saveback_closure_plan",
                "saveback_terminal_plan",
            ],
        },
    ]

    node_terminals = {item["node_id"]: item for item in saveback_terminal_plan["node_terminals"]}
    assert node_terminals["n1"] == {
        "node_id": "n1",
        "severity": "required",
        "action": "writeback_required",
        "reasons": [
            "requires_confirmation_receipt",
            "terminal_writeback_pending",
        ],
        "summary": {
            "receipt_summary": "confirmation_receipt_recorded",
            "writeback_summary": "terminal_writeback_required",
            "terminal_state": "closed_confirmed",
        },
        "suggested_action": "writeback_required",
        "risk_reasons": [
            "requires_confirmation_receipt",
            "terminal_writeback_pending",
        ],
        "terminal_summary": {
            "receipt_summary": "confirmation_receipt_recorded",
            "writeback_summary": "terminal_writeback_required",
            "terminal_state": "closed_confirmed",
        },
        "terminal_state": "closed_confirmed",
        "terminal_writeback_required": True,
        "closed_after_terminal_writeback": True,
        "canonical_node_type": "gee_raster_algebra",
        "legacy_node_type": "gee_band_math",
        "fields_to_drop": ["expression_text"],
        "fields_to_write": ["expression", "output_band"],
        "audit_fields": [
            "confirmed_by",
            "confirmed_at",
            "validation_results",
            "persisted_fields",
        ],
        "closure_status_fields": [
            "audit_result_status",
            "audit_persisted_at",
            "closure_status",
        ],
        "receipt_summary": "confirmation_receipt_recorded",
        "writeback_summary": "terminal_writeback_required",
        "terminal_summary_fields": ["receipt_summary", "writeback_summary", "terminal_state"],
        "terminal_checks": [
            "canonical_payload_consistency",
            "fields_written_match_plan",
            "user_confirmation_recorded",
            "audit_receipt_persisted",
            "terminal_state_persisted",
        ],
    }
    assert node_terminals["n2"] == {
        "node_id": "n2",
        "severity": "recommended",
        "action": "writeback_required",
        "reasons": [
            "requires_review_receipt",
            "terminal_writeback_pending",
        ],
        "summary": {
            "receipt_summary": "review_receipt_recorded",
            "writeback_summary": "terminal_writeback_required",
            "terminal_state": "closed_reviewed",
        },
        "suggested_action": "writeback_required",
        "risk_reasons": [
            "requires_review_receipt",
            "terminal_writeback_pending",
        ],
        "terminal_summary": {
            "receipt_summary": "review_receipt_recorded",
            "writeback_summary": "terminal_writeback_required",
            "terminal_state": "closed_reviewed",
        },
        "terminal_state": "closed_reviewed",
        "terminal_writeback_required": True,
        "closed_after_terminal_writeback": True,
        "canonical_node_type": "gee_export_table",
        "legacy_node_type": None,
        "fields_to_drop": ["task_name"],
        "fields_to_write": ["description", "file_name_prefix", "start_task"],
        "audit_fields": [
            "reviewed_by",
            "reviewed_at",
            "validation_results",
            "persisted_fields",
        ],
        "closure_status_fields": [
            "audit_result_status",
            "audit_persisted_at",
            "closure_status",
        ],
        "receipt_summary": "review_receipt_recorded",
        "writeback_summary": "terminal_writeback_required",
        "terminal_summary_fields": ["receipt_summary", "writeback_summary", "terminal_state"],
        "terminal_checks": [
            "canonical_payload_consistency",
            "fields_written_match_plan",
            "audit_receipt_persisted",
            "terminal_state_persisted",
        ],
    }


def test_saveback_terminal_plan_does_not_require_writeback_for_monitor_only_nodes(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
    )

    normalized = service.normalize_workflow_definition(
        {
            "workflow_id": "saveback-terminal-monitor-only-demo",
            "nodes": [
                {
                    "node_id": "n1",
                    "node_type": "literal",
                    "params": {"value": "ok"},
                },
            ],
        }
    )

    saveback_terminal_plan = normalized.metadata["saveback_terminal_plan"]

    assert saveback_terminal_plan["terminal_mode"] == "writeback_audit_terminal_state"
    assert saveback_terminal_plan["requires_terminal_writeback"] is False
    assert saveback_terminal_plan["terminal_writeback_node_ids"] == []
    assert saveback_terminal_plan["terminal_state"] == "no_terminal_writeback_required"
    assert saveback_terminal_plan["terminal_state_writeback_strategy"]["completed_terminal_state"] == (
        "no_terminal_writeback_required"
    )
    assert saveback_terminal_plan["audit_result_summary"]["terminal_writeback_required_count"] == 0
    node_terminals = {item["node_id"]: item for item in saveback_terminal_plan["node_terminals"]}
    assert node_terminals["n1"] == {
        "node_id": "n1",
        "severity": "none",
        "action": "monitor_only",
        "reasons": [
            "writeback_can_be_deferred",
        ],
        "summary": {
            "receipt_summary": "no_receipt_recorded",
            "writeback_summary": "no_terminal_writeback_required",
            "terminal_state": "no_terminal_update",
        },
        "suggested_action": "monitor_only",
        "risk_reasons": [
            "writeback_can_be_deferred",
        ],
        "terminal_summary": {
            "receipt_summary": "no_receipt_recorded",
            "writeback_summary": "no_terminal_writeback_required",
            "terminal_state": "no_terminal_update",
        },
        "terminal_state": "no_terminal_update",
        "terminal_writeback_required": False,
        "closed_after_terminal_writeback": False,
        "canonical_node_type": "literal",
        "legacy_node_type": None,
        "fields_to_drop": [],
        "fields_to_write": [],
        "audit_fields": [
            "validation_results",
            "persisted_fields",
        ],
        "closure_status_fields": [
            "audit_result_status",
            "audit_persisted_at",
            "closure_status",
        ],
        "receipt_summary": "no_receipt_recorded",
        "writeback_summary": "no_terminal_writeback_required",
        "terminal_summary_fields": ["receipt_summary", "writeback_summary", "terminal_state"],
        "terminal_checks": [
            "canonical_payload_consistency",
        ],
    }
