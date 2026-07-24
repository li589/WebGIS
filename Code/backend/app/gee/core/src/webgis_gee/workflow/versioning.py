from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from webgis_gee.domain.models import WorkflowDefinition
from webgis_gee.nodes.registry import NodeRegistry
from webgis_gee.runtime.exceptions import WorkflowValidationError
from webgis_gee.workflow.schema import (
    AUTO_MIGRATE_FROM_SCHEMA_VERSIONS,
    CURRENT_SCHEMA_VERSION,
    LEGACY_SCHEMA_VERSION,
    SCHEMA_UPGRADE_PATHS,
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
    SUPPORTED_SCHEMA_VERSIONS,
)

LEGACY_NODE_MAPPINGS: dict[str, dict[str, Any]] = {
    "gee_band_math": {
        "replacement_node_type": "gee_raster_algebra",
        "parameter_aliases": {"variables": "band_map"},
        "parameter_migration_rules": [
            {"from": "expression_text", "to": "expression"},
            {"from": "result_band", "to": "output_band"},
        ],
    },
    "gee_threshold": {
        "replacement_node_type": "gee_threshold_classify",
        "parameter_aliases": {"classes": "class_values"},
        "parameter_migration_rules": [
            {"from": "source_band", "to": "band"},
            {"from": "threshold_values", "to": "thresholds"},
            {"from": "labels", "to": "class_values"},
            {"from": "result_band", "to": "output_band"},
        ],
    },
    "gee_remap": {
        "replacement_node_type": "gee_reclassify",
        "parameter_aliases": {"fallback_value": "default_value"},
        "parameter_migration_rules": [
            {"from": "source_band", "to": "band"},
            {"from": "remap_rules", "to": "rules"},
            {"from": "default", "to": "default_value"},
            {"from": "result_band", "to": "output_band"},
        ],
    },
}


class TerminalPlanSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_summary: str = Field(description="Receipt summary for the terminal plan")
    writeback_summary: str = Field(
        description="Writeback summary for the terminal plan"
    )
    terminal_state: str = Field(description="Terminal state after writeback")


class TerminalPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(description="Recommended API action for the terminal plan")
    reasons: list[str] = Field(
        default_factory=list, description="Risk or decision reasons"
    )
    summary: TerminalPlanSummary = Field(description="Terminal plan summary payload")


class WorkflowDefinitionMigrator:
    """Normalize workflow payloads to the current schema version."""

    def __init__(self, registry: NodeRegistry | None = None) -> None:
        self._registry = registry

    def detect_version(
        self, workflow_payload: WorkflowDefinition | dict[str, Any]
    ) -> str:
        if isinstance(workflow_payload, WorkflowDefinition):
            return workflow_payload.schema_version
        if not isinstance(workflow_payload, dict):
            raise WorkflowValidationError(
                "workflow payload must be a mapping or WorkflowDefinition"
            )
        metadata = workflow_payload.get("metadata", {})
        if isinstance(metadata, dict):
            metadata_schema_version = metadata.get("schema_version")
            if isinstance(metadata_schema_version, str) and metadata_schema_version:
                return metadata_schema_version
        schema_version = workflow_payload.get("schema_version")
        if isinstance(schema_version, str) and schema_version:
            return schema_version
        return LEGACY_SCHEMA_VERSION

    def migrate_to_latest(
        self, workflow_payload: WorkflowDefinition | dict[str, Any]
    ) -> dict[str, Any]:
        payload = (
            workflow_payload.model_dump(mode="python")
            if isinstance(workflow_payload, WorkflowDefinition)
            else deepcopy(workflow_payload)
        )
        if not isinstance(payload, dict):
            raise WorkflowValidationError(
                "workflow payload must be a mapping or WorkflowDefinition"
            )

        detected_version = self.detect_version(payload)
        payload.setdefault("metadata", {})
        auto_migrated = detected_version != CURRENT_SCHEMA_VERSION
        self._apply_schema_upgrade_path(payload, detected_version)
        self._normalize_metadata_defaults(payload, auto_migrated=auto_migrated)
        self._normalize_workflow_defaults(payload)
        self._migrate_nodes(payload)
        self._normalize_node_metadata_defaults(payload)
        self._update_normalization_summary(payload)
        self._update_compatibility_snapshot(payload)
        self._update_resave_hint(payload)
        self._update_compatibility_contract(payload)
        self._update_saveback_policy(payload)
        self._update_saveback_decision(payload)
        self._update_auto_fix_plan(payload)
        self._update_saveback_commit_plan(payload)
        self._update_saveback_audit_plan(payload)
        self._update_saveback_closure_plan(payload)
        self._update_saveback_terminal_plan(payload)
        return payload

    def validate_compatibility(self, workflow_definition: WorkflowDefinition) -> None:
        errors: list[str] = []
        if workflow_definition.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            errors.append(
                f"unsupported workflow schema_version: {workflow_definition.schema_version}"
            )

        if self._registry is not None:
            for node in workflow_definition.nodes:
                if not node.version:
                    errors.append(f"node {node.node_id} has empty version")
                    continue
                if not self._registry.has(node.node_type):
                    errors.append(f"node type not registered: {node.node_type}")
                    continue
                canonical = self._registry.get(node.node_type).build_spec()
                alias_map = canonical.parameter_aliases or {}
                alias_pairs = [
                    (alias_name, target_name)
                    for alias_name, target_name in alias_map.items()
                    if alias_name in node.params
                ]
                if alias_pairs:
                    alias_summary = ", ".join(
                        f"{alias_name}->{target_name}"
                        for alias_name, target_name in alias_pairs
                    )
                    errors.append(
                        f"node {node.node_id} uses legacy parameter aliases {alias_summary}; "
                        "normalize workflow first"
                    )
                if canonical.deprecated:
                    replacement_node_type = canonical.replacement_node_type
                    if replacement_node_type and self._registry.has(
                        replacement_node_type
                    ):
                        errors.append(
                            f"node {node.node_id} uses deprecated node type {node.node_type}; "
                            f"replacement available: {replacement_node_type}; normalize workflow first"
                        )
                    elif replacement_node_type:
                        errors.append(
                            f"node {node.node_id} uses deprecated node type {node.node_type}; "
                            f"declared replacement {replacement_node_type} is not registered"
                        )
                    else:
                        errors.append(
                            f"node {node.node_id} uses deprecated node type {node.node_type}; "
                            "no automatic replacement is available"
                        )

        if errors:
            raise WorkflowValidationError("; ".join(errors))

    def to_workflow_definition(
        self, workflow_payload: WorkflowDefinition | dict[str, Any]
    ) -> WorkflowDefinition:
        payload = self.migrate_to_latest(workflow_payload)
        workflow_definition = WorkflowDefinition.model_validate(payload)
        self.validate_compatibility(workflow_definition)
        return workflow_definition

    def describe_support(self) -> dict[str, Any]:
        deprecated_nodes: list[dict[str, Any]] = []
        canonical_parameter_alias_nodes: list[dict[str, Any]] = []
        node_type_replacements = [
            {
                "legacy_node_type": legacy_node_type,
                "replacement_node_type": config["replacement_node_type"],
                "parameter_aliases": config.get("parameter_aliases", {}),
                "parameter_migration_rules": config.get(
                    "parameter_migration_rules", []
                ),
            }
            for legacy_node_type, config in sorted(LEGACY_NODE_MAPPINGS.items())
        ]
        if self._registry is not None:
            for node_type in self._registry.supported_node_types():
                canonical = self._registry.get(node_type).build_spec()
                if canonical.deprecated:
                    deprecated_nodes.append(
                        {
                            "node_type": node_type,
                            "replacement_node_type": canonical.replacement_node_type,
                            "parameter_aliases": canonical.parameter_aliases,
                        }
                    )
                if canonical.parameter_aliases and node_type.startswith("gee_"):
                    canonical_parameter_alias_nodes.append(
                        {
                            "node_type": node_type,
                            "parameter_aliases": canonical.parameter_aliases,
                        }
                    )

        workflow_metadata_features = [
            {"schema_version": SCHEMA_VERSION_1_2, "field": "normalization_summary"},
            {"schema_version": SCHEMA_VERSION_1_3, "field": "compatibility_snapshot"},
            {"schema_version": SCHEMA_VERSION_1_4, "field": "resave_hint"},
            {"schema_version": SCHEMA_VERSION_1_5, "field": "compatibility_contract"},
            {"schema_version": SCHEMA_VERSION_1_6, "field": "saveback_policy"},
            {"schema_version": SCHEMA_VERSION_1_7, "field": "saveback_decision"},
            {"schema_version": SCHEMA_VERSION_1_8, "field": "auto_fix_plan"},
            {"schema_version": SCHEMA_VERSION_1_9, "field": "saveback_commit_plan"},
            {"schema_version": SCHEMA_VERSION_1_10, "field": "saveback_audit_plan"},
            {"schema_version": SCHEMA_VERSION_1_11, "field": "saveback_closure_plan"},
            {"schema_version": SCHEMA_VERSION_1_12, "field": "saveback_terminal_plan"},
        ]
        workflow_metadata_feature_matrix = [
            {
                "schema_version": SCHEMA_VERSION_1_2,
                "fields": ["normalization_summary", "normalization_summary_schema"],
            },
            {
                "schema_version": SCHEMA_VERSION_1_3,
                "fields": ["compatibility_snapshot", "compatibility_snapshot_schema"],
            },
            {
                "schema_version": SCHEMA_VERSION_1_4,
                "fields": ["resave_hint", "resave_hint_schema"],
            },
            {
                "schema_version": SCHEMA_VERSION_1_5,
                "fields": ["compatibility_contract", "compatibility_contract_schema"],
            },
            {
                "schema_version": SCHEMA_VERSION_1_6,
                "fields": ["saveback_policy", "saveback_policy_schema"],
            },
            {
                "schema_version": SCHEMA_VERSION_1_7,
                "fields": ["saveback_decision", "saveback_decision_schema"],
            },
            {
                "schema_version": SCHEMA_VERSION_1_8,
                "fields": ["auto_fix_plan", "auto_fix_plan_schema"],
            },
            {
                "schema_version": SCHEMA_VERSION_1_9,
                "fields": ["saveback_commit_plan", "saveback_commit_plan_schema"],
            },
            {
                "schema_version": SCHEMA_VERSION_1_10,
                "fields": ["saveback_audit_plan", "saveback_audit_plan_schema"],
            },
            {
                "schema_version": SCHEMA_VERSION_1_11,
                "fields": ["saveback_closure_plan", "saveback_closure_plan_schema"],
            },
            {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "fields": ["saveback_terminal_plan", "saveback_terminal_plan_schema"],
            },
        ]
        return {
            "status": "ok",
            "current_schema_version": CURRENT_SCHEMA_VERSION,
            "supported_schema_versions": list(SUPPORTED_SCHEMA_VERSIONS),
            "auto_migrate_from_schema_versions": list(
                AUTO_MIGRATE_FROM_SCHEMA_VERSIONS
            ),
            "schema_upgrade_paths": [
                {
                    "from": source_version,
                    "to": CURRENT_SCHEMA_VERSION,
                    "path": [source_version, *target_versions],
                }
                for source_version, target_versions in sorted(
                    SCHEMA_UPGRADE_PATHS.items()
                )
            ],
            "schema_support_summary": {
                "current_schema_version": CURRENT_SCHEMA_VERSION,
                "supported_schema_versions": list(SUPPORTED_SCHEMA_VERSIONS),
                "auto_migrate_from_schema_versions": list(
                    AUTO_MIGRATE_FROM_SCHEMA_VERSIONS
                ),
                "schema_upgrade_path_count": len(SCHEMA_UPGRADE_PATHS),
                "metadata_feature_count": len(workflow_metadata_features),
                "terminal_plan_schema_version": CURRENT_SCHEMA_VERSION,
            },
            "schema_support_notes": [
                "legacy payloads are auto-migrated to the current schema",
                "deprecated node types may be auto-replaced when a canonical replacement is registered",
                "schema_version 1.12 adds a terminal writeback plan for audit closure",
            ],
            "auto_replace_deprecated_nodes": True,
            "deprecated_nodes": deprecated_nodes,
            "node_type_replacements": node_type_replacements,
            "canonical_parameter_alias_nodes": canonical_parameter_alias_nodes,
            "workflow_metadata_features": workflow_metadata_features,
            "workflow_metadata_feature_matrix": workflow_metadata_feature_matrix,
            "workflow_metadata_feature_groups": [
                {
                    "group": "normalization_and_compatibility",
                    "schema_versions": [
                        SCHEMA_VERSION_1_2,
                        SCHEMA_VERSION_1_3,
                        SCHEMA_VERSION_1_4,
                        SCHEMA_VERSION_1_5,
                    ],
                    "fields": [
                        "normalization_summary",
                        "compatibility_snapshot",
                        "resave_hint",
                        "compatibility_contract",
                    ],
                },
                {
                    "group": "saveback_policy_and_decision",
                    "schema_versions": [SCHEMA_VERSION_1_6, SCHEMA_VERSION_1_7],
                    "fields": ["saveback_policy", "saveback_decision"],
                },
                {
                    "group": "saveback_execution_plans",
                    "schema_versions": [
                        SCHEMA_VERSION_1_8,
                        SCHEMA_VERSION_1_9,
                        SCHEMA_VERSION_1_10,
                    ],
                    "fields": [
                        "auto_fix_plan",
                        "saveback_commit_plan",
                        "saveback_audit_plan",
                    ],
                },
                {
                    "group": "saveback_terminal_closure",
                    "schema_versions": [SCHEMA_VERSION_1_11, CURRENT_SCHEMA_VERSION],
                    "fields": ["saveback_closure_plan", "saveback_terminal_plan"],
                },
            ],
            "saveback_terminal_plan_summary": {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "field": "saveback_terminal_plan",
                "description": "terminal audit writeback summary for API consumers",
                "subfields": ["action", "reasons", "summary"],
            },
            "saveback_terminal_plan_response_schema": {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "field": "saveback_terminal_plan",
                "response_fields": ["action", "reasons", "summary"],
                "response_model": TerminalPlanResponse.model_json_schema(),
            },
        }

    def _normalize_metadata_defaults(
        self, payload: dict[str, Any], *, auto_migrated: bool = False
    ) -> None:
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        now_iso = datetime.now(timezone.utc).isoformat()
        metadata.setdefault("schema_version", CURRENT_SCHEMA_VERSION)
        metadata.setdefault("created_at", now_iso)
        metadata.setdefault("updated_at", now_iso)
        metadata.setdefault(
            "source",
            "workflow_definition_migrator" if auto_migrated else "workflow_definition",
        )
        metadata.setdefault(
            "compatibility_mode", "migrated" if auto_migrated else "strict"
        )
        metadata.setdefault("migration_notes", [])

    def _apply_schema_upgrade_path(
        self, payload: dict[str, Any], detected_version: str
    ) -> None:
        if detected_version == CURRENT_SCHEMA_VERSION:
            payload["schema_version"] = CURRENT_SCHEMA_VERSION
            return
        if detected_version not in AUTO_MIGRATE_FROM_SCHEMA_VERSIONS:
            raise WorkflowValidationError(
                f"unsupported workflow schema_version: {detected_version}"
            )
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        metadata["auto_migrated_from_schema_version"] = detected_version
        migration_notes: list[dict[str, Any]] = metadata.setdefault(
            "migration_notes", []
        )
        upgrade_path = SCHEMA_UPGRADE_PATHS.get(detected_version)
        if not upgrade_path:
            raise WorkflowValidationError(
                f"unsupported workflow schema_version: {detected_version}"
            )
        metadata["schema_upgrade_path"] = [detected_version, *upgrade_path]
        current_version = detected_version
        for target_version in upgrade_path:
            self._apply_schema_upgrade_step(
                payload,
                from_version=current_version,
                to_version=target_version,
                migration_notes=migration_notes,
            )
            current_version = target_version

    @staticmethod
    def _apply_schema_upgrade_step(
        payload: dict[str, Any],
        *,
        from_version: str,
        to_version: str,
        migration_notes: list[dict[str, Any]],
    ) -> None:
        if from_version == LEGACY_SCHEMA_VERSION and to_version == SCHEMA_VERSION_1_0:
            payload["schema_version"] = to_version
            payload.setdefault("metadata", {})["schema_version"] = to_version
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_0 and to_version == CURRENT_SCHEMA_VERSION:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_0 and to_version == SCHEMA_VERSION_1_1:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_1 and to_version == SCHEMA_VERSION_1_2:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            metadata.setdefault("normalization_summary_schema", SCHEMA_VERSION_1_2)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_2 and to_version == SCHEMA_VERSION_1_3:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            metadata.setdefault("normalization_summary_schema", SCHEMA_VERSION_1_2)
            metadata.setdefault("compatibility_snapshot_schema", SCHEMA_VERSION_1_3)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_3 and to_version == SCHEMA_VERSION_1_4:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            metadata.setdefault("normalization_summary_schema", SCHEMA_VERSION_1_2)
            metadata.setdefault("compatibility_snapshot_schema", SCHEMA_VERSION_1_3)
            metadata.setdefault("resave_hint_schema", SCHEMA_VERSION_1_4)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_4 and to_version == SCHEMA_VERSION_1_5:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            metadata.setdefault("normalization_summary_schema", SCHEMA_VERSION_1_2)
            metadata.setdefault("compatibility_snapshot_schema", SCHEMA_VERSION_1_3)
            metadata.setdefault("resave_hint_schema", SCHEMA_VERSION_1_4)
            metadata.setdefault("compatibility_contract_schema", SCHEMA_VERSION_1_5)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_5 and to_version == SCHEMA_VERSION_1_6:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            metadata.setdefault("normalization_summary_schema", SCHEMA_VERSION_1_2)
            metadata.setdefault("compatibility_snapshot_schema", SCHEMA_VERSION_1_3)
            metadata.setdefault("resave_hint_schema", SCHEMA_VERSION_1_4)
            metadata.setdefault("compatibility_contract_schema", SCHEMA_VERSION_1_5)
            metadata.setdefault("saveback_policy_schema", SCHEMA_VERSION_1_6)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_6 and to_version == SCHEMA_VERSION_1_7:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            metadata.setdefault("normalization_summary_schema", SCHEMA_VERSION_1_2)
            metadata.setdefault("compatibility_snapshot_schema", SCHEMA_VERSION_1_3)
            metadata.setdefault("resave_hint_schema", SCHEMA_VERSION_1_4)
            metadata.setdefault("compatibility_contract_schema", SCHEMA_VERSION_1_5)
            metadata.setdefault("saveback_policy_schema", SCHEMA_VERSION_1_6)
            metadata.setdefault("saveback_decision_schema", SCHEMA_VERSION_1_7)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_7 and to_version == SCHEMA_VERSION_1_8:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            metadata.setdefault("normalization_summary_schema", SCHEMA_VERSION_1_2)
            metadata.setdefault("compatibility_snapshot_schema", SCHEMA_VERSION_1_3)
            metadata.setdefault("resave_hint_schema", SCHEMA_VERSION_1_4)
            metadata.setdefault("compatibility_contract_schema", SCHEMA_VERSION_1_5)
            metadata.setdefault("saveback_policy_schema", SCHEMA_VERSION_1_6)
            metadata.setdefault("saveback_decision_schema", SCHEMA_VERSION_1_7)
            metadata.setdefault("auto_fix_plan_schema", SCHEMA_VERSION_1_8)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_8 and to_version == SCHEMA_VERSION_1_9:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            metadata.setdefault("normalization_summary_schema", SCHEMA_VERSION_1_2)
            metadata.setdefault("compatibility_snapshot_schema", SCHEMA_VERSION_1_3)
            metadata.setdefault("resave_hint_schema", SCHEMA_VERSION_1_4)
            metadata.setdefault("compatibility_contract_schema", SCHEMA_VERSION_1_5)
            metadata.setdefault("saveback_policy_schema", SCHEMA_VERSION_1_6)
            metadata.setdefault("saveback_decision_schema", SCHEMA_VERSION_1_7)
            metadata.setdefault("auto_fix_plan_schema", SCHEMA_VERSION_1_8)
            metadata.setdefault("saveback_commit_plan_schema", SCHEMA_VERSION_1_9)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_9 and to_version == SCHEMA_VERSION_1_10:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            metadata.setdefault("normalization_summary_schema", SCHEMA_VERSION_1_2)
            metadata.setdefault("compatibility_snapshot_schema", SCHEMA_VERSION_1_3)
            metadata.setdefault("resave_hint_schema", SCHEMA_VERSION_1_4)
            metadata.setdefault("compatibility_contract_schema", SCHEMA_VERSION_1_5)
            metadata.setdefault("saveback_policy_schema", SCHEMA_VERSION_1_6)
            metadata.setdefault("saveback_decision_schema", SCHEMA_VERSION_1_7)
            metadata.setdefault("auto_fix_plan_schema", SCHEMA_VERSION_1_8)
            metadata.setdefault("saveback_commit_plan_schema", SCHEMA_VERSION_1_9)
            metadata.setdefault("saveback_audit_plan_schema", SCHEMA_VERSION_1_10)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_10 and to_version == SCHEMA_VERSION_1_11:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            metadata.setdefault("normalization_summary_schema", SCHEMA_VERSION_1_2)
            metadata.setdefault("compatibility_snapshot_schema", SCHEMA_VERSION_1_3)
            metadata.setdefault("resave_hint_schema", SCHEMA_VERSION_1_4)
            metadata.setdefault("compatibility_contract_schema", SCHEMA_VERSION_1_5)
            metadata.setdefault("saveback_policy_schema", SCHEMA_VERSION_1_6)
            metadata.setdefault("saveback_decision_schema", SCHEMA_VERSION_1_7)
            metadata.setdefault("auto_fix_plan_schema", SCHEMA_VERSION_1_8)
            metadata.setdefault("saveback_commit_plan_schema", SCHEMA_VERSION_1_9)
            metadata.setdefault("saveback_audit_plan_schema", SCHEMA_VERSION_1_10)
            metadata.setdefault("saveback_closure_plan_schema", SCHEMA_VERSION_1_11)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        if from_version == SCHEMA_VERSION_1_11 and to_version == CURRENT_SCHEMA_VERSION:
            payload["schema_version"] = to_version
            metadata = payload.setdefault("metadata", {})
            metadata["schema_version"] = to_version
            metadata.setdefault("node_metadata_schema", SCHEMA_VERSION_1_1)
            metadata.setdefault("normalization_summary_schema", SCHEMA_VERSION_1_2)
            metadata.setdefault("compatibility_snapshot_schema", SCHEMA_VERSION_1_3)
            metadata.setdefault("resave_hint_schema", SCHEMA_VERSION_1_4)
            metadata.setdefault("compatibility_contract_schema", SCHEMA_VERSION_1_5)
            metadata.setdefault("saveback_policy_schema", SCHEMA_VERSION_1_6)
            metadata.setdefault("saveback_decision_schema", SCHEMA_VERSION_1_7)
            metadata.setdefault("auto_fix_plan_schema", SCHEMA_VERSION_1_8)
            metadata.setdefault("saveback_commit_plan_schema", SCHEMA_VERSION_1_9)
            metadata.setdefault("saveback_audit_plan_schema", SCHEMA_VERSION_1_10)
            metadata.setdefault("saveback_closure_plan_schema", SCHEMA_VERSION_1_11)
            metadata.setdefault("saveback_terminal_plan_schema", CURRENT_SCHEMA_VERSION)
            migration_notes.append(
                {
                    "migration": "schema_version_upgraded",
                    "from": from_version,
                    "to": to_version,
                }
            )
            return
        raise WorkflowValidationError(
            f"unsupported workflow schema upgrade path: {from_version} -> {to_version}"
        )

    def _normalize_workflow_defaults(self, payload: dict[str, Any]) -> None:
        migration_notes: list[dict[str, Any]] = payload["metadata"].setdefault(
            "migration_notes", []
        )
        filled_fields: list[str] = []
        if "version" not in payload:
            payload["version"] = "1.0.0"
            filled_fields.append("version")
        if "inputs" not in payload:
            payload["inputs"] = {}
            filled_fields.append("inputs")
        if "edges" not in payload:
            payload["edges"] = []
            filled_fields.append("edges")
        if "runtime_policy" not in payload or payload["runtime_policy"] is None:
            payload["runtime_policy"] = {}
            filled_fields.append("runtime_policy")
        if "storage_policy" not in payload or payload["storage_policy"] is None:
            payload["storage_policy"] = {}
            filled_fields.append("storage_policy")
        if filled_fields:
            migration_notes.append(
                {
                    "migration": "workflow_defaults_filled",
                    "fields": filled_fields,
                }
            )

    def _normalize_node_metadata_defaults(self, payload: dict[str, Any]) -> None:
        nodes = payload.get("nodes", [])
        if not isinstance(nodes, list):
            raise WorkflowValidationError("workflow nodes must be a list")
        migration_notes: list[dict[str, Any]] = payload["metadata"].setdefault(
            "migration_notes", []
        )
        normalized_node_ids: list[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                raise WorkflowValidationError("workflow node payload must be a mapping")
            node_metadata = node.setdefault("metadata", {})
            if not isinstance(node_metadata, dict):
                raise WorkflowValidationError(
                    "workflow node metadata must be a mapping"
                )
            changed = False
            if node_metadata.get("schema_version") != CURRENT_SCHEMA_VERSION:
                node_metadata["schema_version"] = CURRENT_SCHEMA_VERSION
                changed = True
            canonical_node_type = node.get("node_type")
            if node_metadata.get("canonical_node_type") != canonical_node_type:
                node_metadata["canonical_node_type"] = canonical_node_type
                changed = True
            canonical_node_version = node.get("version")
            if (
                self._registry is not None
                and isinstance(canonical_node_type, str)
                and self._registry.has(canonical_node_type)
            ):
                canonical_node_version = (
                    self._registry.get(canonical_node_type).build_spec().version
                )
            elif (
                not isinstance(canonical_node_version, str)
                or not canonical_node_version
            ):
                canonical_node_version = "1.0.0"
            if node_metadata.get("canonical_node_version") != canonical_node_version:
                node_metadata["canonical_node_version"] = canonical_node_version
                changed = True
            if changed and isinstance(node.get("node_id"), str):
                normalized_node_ids.append(node["node_id"])
        if normalized_node_ids:
            migration_notes.append(
                {
                    "migration": "node_metadata_normalized",
                    "node_ids": normalized_node_ids,
                    "schema_version": CURRENT_SCHEMA_VERSION,
                }
            )

    def _update_normalization_summary(self, payload: dict[str, Any]) -> None:
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        nodes = payload.get("nodes", [])
        if not isinstance(nodes, list):
            raise WorkflowValidationError("workflow nodes must be a list")
        migration_notes: list[dict[str, Any]] = metadata.setdefault(
            "migration_notes", []
        )
        summary = {
            "schema_version": SCHEMA_VERSION_1_2,
            "total_nodes": len(nodes),
            "replaced_nodes": sum(
                1
                for note in migration_notes
                if note.get("migration")
                in {"node_type_replaced", "deprecated_node_replaced"}
            ),
            "aliased_parameters": sum(
                1
                for note in migration_notes
                if note.get("migration") == "parameter_aliased"
            ),
            "rule_migrated_parameters": sum(
                1
                for note in migration_notes
                if note.get("migration") == "parameter_rule_applied"
            ),
            "defaulted_nodes": len(
                {
                    note.get("node_id")
                    for note in migration_notes
                    if note.get("migration") == "default_params_filled"
                    and note.get("node_id")
                }
            ),
            "auto_migrated": "auto_migrated_from_schema_version" in metadata,
        }
        if metadata.get("normalization_summary") != summary:
            metadata["normalization_summary"] = summary
            metadata["normalization_summary_schema"] = SCHEMA_VERSION_1_2
            migration_notes.append(
                {
                    "migration": "normalization_summary_updated",
                    "schema_version": SCHEMA_VERSION_1_2,
                    "summary": summary,
                }
            )

    def _update_compatibility_snapshot(self, payload: dict[str, Any]) -> None:
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        nodes = payload.get("nodes", [])
        if not isinstance(nodes, list):
            raise WorkflowValidationError("workflow nodes must be a list")
        migration_notes: list[dict[str, Any]] = metadata.setdefault(
            "migration_notes", []
        )
        compatibility_snapshot = {
            "schema_version": SCHEMA_VERSION_1_3,
            "source_schema_version": metadata.get(
                "auto_migrated_from_schema_version", CURRENT_SCHEMA_VERSION
            ),
            "upgrade_path": metadata.get(
                "schema_upgrade_path", [CURRENT_SCHEMA_VERSION]
            ),
            "compatible": True,
            "total_nodes": len(nodes),
            "canonical_node_types": sorted(
                {
                    node.get("node_type")
                    for node in nodes
                    if isinstance(node, dict) and isinstance(node.get("node_type"), str)
                }
            ),
            "replaced_node_ids": sorted(
                {
                    note.get("node_id")
                    for note in migration_notes
                    if note.get("migration")
                    in {"node_type_replaced", "deprecated_node_replaced"}
                    and isinstance(note.get("node_id"), str)
                }
            ),
            "aliased_node_ids": sorted(
                {
                    note.get("node_id")
                    for note in migration_notes
                    if note.get("migration") == "parameter_aliased"
                    and isinstance(note.get("node_id"), str)
                }
            ),
            "rule_migrated_node_ids": sorted(
                {
                    note.get("node_id")
                    for note in migration_notes
                    if note.get("migration") == "parameter_rule_applied"
                    and isinstance(note.get("node_id"), str)
                }
            ),
            "defaulted_node_ids": sorted(
                {
                    note.get("node_id")
                    for note in migration_notes
                    if note.get("migration") == "default_params_filled"
                    and isinstance(note.get("node_id"), str)
                }
            ),
        }
        if metadata.get("compatibility_snapshot") != compatibility_snapshot:
            metadata["compatibility_snapshot"] = compatibility_snapshot
            metadata["compatibility_snapshot_schema"] = SCHEMA_VERSION_1_3
            migration_notes.append(
                {
                    "migration": "compatibility_snapshot_updated",
                    "schema_version": SCHEMA_VERSION_1_3,
                    "snapshot": compatibility_snapshot,
                }
            )

    def _update_resave_hint(self, payload: dict[str, Any]) -> None:
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        migration_notes: list[dict[str, Any]] = metadata.setdefault(
            "migration_notes", []
        )
        reason_map = {
            "schema_version_upgraded": "schema_upgraded",
            "node_type_replaced": "node_replaced",
            "deprecated_node_replaced": "deprecated_node_replaced",
            "parameter_aliased": "parameter_aliased",
            "parameter_rule_applied": "parameter_rule_applied",
            "default_params_filled": "node_defaults_filled",
            "workflow_defaults_filled": "workflow_defaults_filled",
        }
        reasons = sorted(
            {
                reason_map[note["migration"]]
                for note in migration_notes
                if note.get("migration") in reason_map
            }
        )
        affected_node_ids = sorted(
            {
                note.get("node_id")
                for note in migration_notes
                if isinstance(note.get("node_id"), str)
                and note.get("migration")
                in {
                    "node_type_replaced",
                    "deprecated_node_replaced",
                    "parameter_aliased",
                    "parameter_rule_applied",
                    "default_params_filled",
                }
            }
        )
        resave_hint = {
            "schema_version": SCHEMA_VERSION_1_4,
            "resave_recommended": bool(reasons),
            "reasons": reasons,
            "affected_node_ids": affected_node_ids,
            "auto_migrated": "auto_migrated_from_schema_version" in metadata,
        }
        if metadata.get("resave_hint") != resave_hint:
            metadata["resave_hint"] = resave_hint
            metadata["resave_hint_schema"] = SCHEMA_VERSION_1_4
            migration_notes.append(
                {
                    "migration": "resave_hint_updated",
                    "schema_version": SCHEMA_VERSION_1_4,
                    "hint": resave_hint,
                }
            )

    def _update_compatibility_contract(self, payload: dict[str, Any]) -> None:
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        nodes = payload.get("nodes", [])
        if not isinstance(nodes, list):
            raise WorkflowValidationError("workflow nodes must be a list")
        migration_notes: list[dict[str, Any]] = metadata.setdefault(
            "migration_notes", []
        )
        node_contracts: list[dict[str, Any]] = []
        node_types_with_alias_support: set[str] = set()
        nodes_requiring_resave: list[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                raise WorkflowValidationError("workflow node payload must be a mapping")
            node_contract = self._build_node_compatibility_contract(
                node, migration_notes
            )
            if node_contract is None:
                continue
            node_contracts.append(node_contract)
            if node_contract["supported_parameter_aliases"]:
                node_types_with_alias_support.add(node_contract["node_type"])
            if node_contract["resave_required"]:
                nodes_requiring_resave.append(node_contract["node_id"])
        compatibility_contract = {
            "schema_version": SCHEMA_VERSION_1_5,
            "source_schema_version": metadata.get(
                "auto_migrated_from_schema_version",
                CURRENT_SCHEMA_VERSION,
            ),
            "upgrade_path": metadata.get(
                "schema_upgrade_path", [CURRENT_SCHEMA_VERSION]
            ),
            "resave_recommended": bool(
                metadata.get("resave_hint", {}).get("resave_recommended", False)
            ),
            "nodes_requiring_resave": sorted(nodes_requiring_resave),
            "node_types_with_alias_support": sorted(node_types_with_alias_support),
            "nodes": node_contracts,
        }
        if metadata.get("compatibility_contract") != compatibility_contract:
            metadata["compatibility_contract"] = compatibility_contract
            metadata["compatibility_contract_schema"] = SCHEMA_VERSION_1_5
            migration_notes.append(
                {
                    "migration": "compatibility_contract_updated",
                    "schema_version": SCHEMA_VERSION_1_5,
                    "contract": compatibility_contract,
                }
            )

    def _update_saveback_policy(self, payload: dict[str, Any]) -> None:
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        compatibility_contract = metadata.get("compatibility_contract", {})
        if not isinstance(compatibility_contract, dict):
            raise WorkflowValidationError(
                "workflow compatibility_contract must be a mapping"
            )
        node_contracts = compatibility_contract.get("nodes", [])
        if not isinstance(node_contracts, list):
            raise WorkflowValidationError(
                "workflow compatibility contract nodes must be a list"
            )
        migration_notes: list[dict[str, Any]] = metadata.setdefault(
            "migration_notes", []
        )
        node_actions: list[dict[str, Any]] = []
        nodes_requiring_canonical_writeback: list[str] = []
        for node_contract in node_contracts:
            if not isinstance(node_contract, dict):
                raise WorkflowValidationError(
                    "workflow node compatibility contract must be a mapping"
                )
            node_action = self._build_node_saveback_action(node_contract)
            node_actions.append(node_action)
            if node_action["action"] != "keep":
                nodes_requiring_canonical_writeback.append(node_action["node_id"])
        saveback_policy = {
            "schema_version": SCHEMA_VERSION_1_6,
            "target_schema_version": CURRENT_SCHEMA_VERSION,
            "saveback_required": bool(
                metadata.get("resave_hint", {}).get("resave_recommended", False)
            ),
            "recommended_mode": (
                "canonical_writeback"
                if metadata.get("resave_hint", {}).get("resave_recommended", False)
                else "keep_current"
            ),
            "workflow_metadata_fields_to_persist": [
                "normalization_summary",
                "compatibility_snapshot",
                "resave_hint",
                "compatibility_contract",
                "saveback_policy",
            ],
            "nodes_requiring_canonical_writeback": sorted(
                nodes_requiring_canonical_writeback
            ),
            "node_actions": node_actions,
        }
        if metadata.get("saveback_policy") != saveback_policy:
            metadata["saveback_policy"] = saveback_policy
            metadata["saveback_policy_schema"] = SCHEMA_VERSION_1_6
            migration_notes.append(
                {
                    "migration": "saveback_policy_updated",
                    "schema_version": SCHEMA_VERSION_1_6,
                    "policy": saveback_policy,
                }
            )

    def _update_saveback_decision(self, payload: dict[str, Any]) -> None:
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        saveback_policy = metadata.get("saveback_policy", {})
        if not isinstance(saveback_policy, dict):
            raise WorkflowValidationError("workflow saveback_policy must be a mapping")
        node_actions = saveback_policy.get("node_actions", [])
        if not isinstance(node_actions, list):
            raise WorkflowValidationError(
                "workflow saveback policy node_actions must be a list"
            )
        migration_notes: list[dict[str, Any]] = metadata.setdefault(
            "migration_notes", []
        )
        node_decisions: list[dict[str, Any]] = []
        required_node_ids: list[str] = []
        recommended_node_ids: list[str] = []
        for node_action in node_actions:
            if not isinstance(node_action, dict):
                raise WorkflowValidationError(
                    "workflow saveback policy node action must be a mapping"
                )
            node_decision = self._build_node_saveback_decision(node_action)
            node_decisions.append(node_decision)
            if node_decision["severity"] == "required":
                required_node_ids.append(node_decision["node_id"])
            elif node_decision["severity"] == "recommended":
                recommended_node_ids.append(node_decision["node_id"])
        highest_severity = "none"
        if required_node_ids:
            highest_severity = "required"
        elif recommended_node_ids:
            highest_severity = "recommended"
        saveback_decision = {
            "schema_version": SCHEMA_VERSION_1_7,
            "target_schema_version": CURRENT_SCHEMA_VERSION,
            "highest_severity": highest_severity,
            "required_node_ids": sorted(required_node_ids),
            "recommended_node_ids": sorted(recommended_node_ids),
            "can_execute_without_saveback": True,
            "recommended_editor_mode": (
                "block_save_until_writeback"
                if highest_severity == "required"
                else "warn_before_save"
                if highest_severity == "recommended"
                else "allow_save"
            ),
            "workflow_metadata_fields_to_persist": saveback_policy.get(
                "workflow_metadata_fields_to_persist",
                [],
            ),
            "node_decisions": node_decisions,
        }
        if metadata.get("saveback_decision") != saveback_decision:
            metadata["saveback_decision"] = saveback_decision
            metadata["saveback_decision_schema"] = SCHEMA_VERSION_1_7
            migration_notes.append(
                {
                    "migration": "saveback_decision_updated",
                    "schema_version": SCHEMA_VERSION_1_7,
                    "decision": saveback_decision,
                }
            )

    def _update_auto_fix_plan(self, payload: dict[str, Any]) -> None:
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        saveback_decision = metadata.get("saveback_decision", {})
        if not isinstance(saveback_decision, dict):
            raise WorkflowValidationError(
                "workflow saveback_decision must be a mapping"
            )
        node_decisions = saveback_decision.get("node_decisions", [])
        if not isinstance(node_decisions, list):
            raise WorkflowValidationError(
                "workflow saveback decision node_decisions must be a list"
            )
        migration_notes: list[dict[str, Any]] = metadata.setdefault(
            "migration_notes", []
        )
        node_plans: list[dict[str, Any]] = []
        auto_fixable_node_ids: list[str] = []
        manual_review_node_ids: list[str] = []
        for node_decision in node_decisions:
            if not isinstance(node_decision, dict):
                raise WorkflowValidationError(
                    "workflow saveback decision node decision must be a mapping"
                )
            node_plan = self._build_node_auto_fix_plan(node_decision)
            node_plans.append(node_plan)
            if node_plan["auto_fix"]:
                auto_fixable_node_ids.append(node_plan["node_id"])
            if node_plan["manual_review"]:
                manual_review_node_ids.append(node_plan["node_id"])
        workflow_metadata_fields_to_persist = list(
            dict.fromkeys(
                [
                    *saveback_decision.get("workflow_metadata_fields_to_persist", []),
                    "saveback_decision",
                    "auto_fix_plan",
                ]
            )
        )
        auto_fix_plan = {
            "schema_version": SCHEMA_VERSION_1_8,
            "target_schema_version": CURRENT_SCHEMA_VERSION,
            "plan_mode": (
                "batch_canonical_writeback" if auto_fixable_node_ids else "no_op"
            ),
            "highest_severity": saveback_decision.get("highest_severity", "none"),
            "can_auto_fix": not manual_review_node_ids,
            "auto_fixable_node_ids": sorted(auto_fixable_node_ids),
            "manual_review_node_ids": sorted(manual_review_node_ids),
            "workflow_metadata_fields_to_persist": workflow_metadata_fields_to_persist,
            "steps": [
                {
                    "step": "persist_workflow_metadata",
                    "fields": workflow_metadata_fields_to_persist,
                },
                {
                    "step": "canonical_writeback_nodes",
                    "node_ids": sorted(auto_fixable_node_ids),
                },
            ],
            "node_plans": node_plans,
        }
        if metadata.get("auto_fix_plan") != auto_fix_plan:
            metadata["auto_fix_plan"] = auto_fix_plan
            metadata["auto_fix_plan_schema"] = SCHEMA_VERSION_1_8
            migration_notes.append(
                {
                    "migration": "auto_fix_plan_updated",
                    "schema_version": SCHEMA_VERSION_1_8,
                    "plan": auto_fix_plan,
                }
            )

    def _update_saveback_commit_plan(self, payload: dict[str, Any]) -> None:
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        auto_fix_plan = metadata.get("auto_fix_plan", {})
        if not isinstance(auto_fix_plan, dict):
            raise WorkflowValidationError("workflow auto_fix_plan must be a mapping")
        node_plans = auto_fix_plan.get("node_plans", [])
        if not isinstance(node_plans, list):
            raise WorkflowValidationError(
                "workflow auto_fix plan node_plans must be a list"
            )
        migration_notes: list[dict[str, Any]] = metadata.setdefault(
            "migration_notes", []
        )
        commit_entries: list[dict[str, Any]] = []
        confirm_before_persist_node_ids: list[str] = []
        review_before_persist_node_ids: list[str] = []
        for node_plan in node_plans:
            if not isinstance(node_plan, dict):
                raise WorkflowValidationError(
                    "workflow auto fix plan node plan must be a mapping"
                )
            commit_entry = self._build_node_saveback_commit_entry(node_plan)
            commit_entries.append(commit_entry)
            if commit_entry["commit_mode"] == "confirm_before_persist":
                confirm_before_persist_node_ids.append(commit_entry["node_id"])
            elif commit_entry["commit_mode"] == "review_before_persist":
                review_before_persist_node_ids.append(commit_entry["node_id"])
        highest_severity = auto_fix_plan.get("highest_severity", "none")
        commit_barrier = "allow_direct_persist"
        if highest_severity == "required":
            commit_barrier = "confirm_required_changes"
        elif highest_severity == "recommended":
            commit_barrier = "review_recommended_changes"
        workflow_metadata_fields_to_persist = list(
            dict.fromkeys(
                [
                    *auto_fix_plan.get("workflow_metadata_fields_to_persist", []),
                    "saveback_commit_plan",
                ]
            )
        )
        saveback_commit_plan = {
            "schema_version": SCHEMA_VERSION_1_9,
            "target_schema_version": CURRENT_SCHEMA_VERSION,
            "commit_barrier": commit_barrier,
            "requires_confirmation": bool(confirm_before_persist_node_ids),
            "requires_review": bool(
                confirm_before_persist_node_ids or review_before_persist_node_ids
            ),
            "confirm_before_persist_node_ids": sorted(confirm_before_persist_node_ids),
            "review_before_persist_node_ids": sorted(review_before_persist_node_ids),
            "workflow_metadata_fields_to_persist": workflow_metadata_fields_to_persist,
            "steps": [
                {
                    "step": "apply_auto_fixes",
                    "node_ids": sorted(auto_fix_plan.get("auto_fixable_node_ids", [])),
                },
                {
                    "step": "validate_before_persist",
                    "node_ids": sorted(
                        confirm_before_persist_node_ids + review_before_persist_node_ids
                    ),
                },
                {
                    "step": "persist_workflow_definition",
                    "fields": workflow_metadata_fields_to_persist,
                },
            ],
            "node_commits": commit_entries,
        }
        if metadata.get("saveback_commit_plan") != saveback_commit_plan:
            metadata["saveback_commit_plan"] = saveback_commit_plan
            metadata["saveback_commit_plan_schema"] = SCHEMA_VERSION_1_9
            migration_notes.append(
                {
                    "migration": "saveback_commit_plan_updated",
                    "schema_version": SCHEMA_VERSION_1_9,
                    "plan": saveback_commit_plan,
                }
            )

    def _update_saveback_audit_plan(self, payload: dict[str, Any]) -> None:
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        saveback_commit_plan = metadata.get("saveback_commit_plan", {})
        if not isinstance(saveback_commit_plan, dict):
            raise WorkflowValidationError(
                "workflow saveback_commit_plan must be a mapping"
            )
        node_commits = saveback_commit_plan.get("node_commits", [])
        if not isinstance(node_commits, list):
            raise WorkflowValidationError(
                "workflow saveback commit plan node_commits must be a list"
            )
        migration_notes: list[dict[str, Any]] = metadata.setdefault(
            "migration_notes", []
        )
        node_audits: list[dict[str, Any]] = []
        confirmation_audit_node_ids: list[str] = []
        review_audit_node_ids: list[str] = []
        for node_commit in node_commits:
            if not isinstance(node_commit, dict):
                raise WorkflowValidationError(
                    "workflow saveback commit node entry must be a mapping"
                )
            node_audit = self._build_node_saveback_audit_entry(node_commit)
            node_audits.append(node_audit)
            if node_audit["confirmation_record_required"]:
                confirmation_audit_node_ids.append(node_audit["node_id"])
            if node_audit["review_record_required"]:
                review_audit_node_ids.append(node_audit["node_id"])
        workflow_metadata_fields_to_persist = list(
            dict.fromkeys(
                [
                    *saveback_commit_plan.get(
                        "workflow_metadata_fields_to_persist", []
                    ),
                    "saveback_audit_plan",
                ]
            )
        )
        saveback_audit_plan = {
            "schema_version": SCHEMA_VERSION_1_10,
            "target_schema_version": CURRENT_SCHEMA_VERSION,
            "audit_mode": (
                "persist_saveback_audit" if node_audits else "no_audit_required"
            ),
            "requires_audit_record": bool(node_audits),
            "confirmation_audit_node_ids": sorted(confirmation_audit_node_ids),
            "review_audit_node_ids": sorted(review_audit_node_ids),
            "workflow_audit_fields": [
                "commit_barrier",
                "confirmed_node_ids",
                "reviewed_node_ids",
                "validation_results",
                "persisted_at",
            ],
            "workflow_metadata_fields_to_persist": workflow_metadata_fields_to_persist,
            "steps": [
                {
                    "step": "collect_confirmation_records",
                    "node_ids": sorted(confirmation_audit_node_ids),
                },
                {
                    "step": "collect_review_records",
                    "node_ids": sorted(review_audit_node_ids),
                },
                {
                    "step": "collect_validation_results",
                    "node_ids": sorted(
                        {
                            node_audit["node_id"]
                            for node_audit in node_audits
                            if node_audit["validation_checks"]
                        }
                    ),
                },
                {
                    "step": "persist_saveback_audit",
                    "fields": workflow_metadata_fields_to_persist,
                },
            ],
            "node_audits": node_audits,
        }
        if metadata.get("saveback_audit_plan") != saveback_audit_plan:
            metadata["saveback_audit_plan"] = saveback_audit_plan
            metadata["saveback_audit_plan_schema"] = SCHEMA_VERSION_1_10
            migration_notes.append(
                {
                    "migration": "saveback_audit_plan_updated",
                    "schema_version": SCHEMA_VERSION_1_10,
                    "plan": saveback_audit_plan,
                }
            )

    def _update_saveback_closure_plan(self, payload: dict[str, Any]) -> None:
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        saveback_audit_plan = metadata.get("saveback_audit_plan", {})
        if not isinstance(saveback_audit_plan, dict):
            raise WorkflowValidationError(
                "workflow saveback_audit_plan must be a mapping"
            )
        node_audits = saveback_audit_plan.get("node_audits", [])
        if not isinstance(node_audits, list):
            raise WorkflowValidationError(
                "workflow saveback audit plan node_audits must be a list"
            )
        migration_notes: list[dict[str, Any]] = metadata.setdefault(
            "migration_notes", []
        )
        node_closures: list[dict[str, Any]] = []
        batch_writeback_node_ids: list[str] = []
        pending_closure_node_ids: list[str] = []
        for node_audit in node_audits:
            if not isinstance(node_audit, dict):
                raise WorkflowValidationError(
                    "workflow saveback audit node entry must be a mapping"
                )
            node_closure = self._build_node_saveback_closure_entry(node_audit)
            node_closures.append(node_closure)
            if node_closure["batch_writeback_eligible"]:
                batch_writeback_node_ids.append(node_closure["node_id"])
            if node_closure["closure_required"]:
                pending_closure_node_ids.append(node_closure["node_id"])
        workflow_metadata_fields_to_persist = list(
            dict.fromkeys(
                [
                    *saveback_audit_plan.get("workflow_metadata_fields_to_persist", []),
                    "saveback_closure_plan",
                ]
            )
        )
        workflow_closure_status_fields = [
            "audit_result_status",
            "audit_persisted_at",
            "closed_node_ids",
            "pending_closure_node_ids",
            "closure_completed_at",
        ]
        saveback_closure_plan = {
            "schema_version": SCHEMA_VERSION_1_11,
            "target_schema_version": CURRENT_SCHEMA_VERSION,
            "closure_mode": (
                "batch_writeback_closure" if node_closures else "no_closure_required"
            ),
            "requires_closure_writeback": bool(node_closures),
            "batch_writeback_node_ids": sorted(batch_writeback_node_ids),
            "pending_closure_node_ids": sorted(pending_closure_node_ids),
            "workflow_closure_status_fields": workflow_closure_status_fields,
            "workflow_metadata_fields_to_persist": workflow_metadata_fields_to_persist,
            "steps": [
                {
                    "step": "collect_audit_writeback_payloads",
                    "node_ids": sorted(batch_writeback_node_ids),
                },
                {
                    "step": "writeback_node_audit_results",
                    "node_ids": sorted(batch_writeback_node_ids),
                },
                {
                    "step": "update_workflow_closure_status",
                    "fields": workflow_closure_status_fields,
                },
                {
                    "step": "persist_closed_workflow_definition",
                    "fields": workflow_metadata_fields_to_persist,
                },
            ],
            "node_closures": node_closures,
        }
        if metadata.get("saveback_closure_plan") != saveback_closure_plan:
            metadata["saveback_closure_plan"] = saveback_closure_plan
            metadata["saveback_closure_plan_schema"] = SCHEMA_VERSION_1_11
            migration_notes.append(
                {
                    "migration": "saveback_closure_plan_updated",
                    "schema_version": SCHEMA_VERSION_1_11,
                    "plan": saveback_closure_plan,
                }
            )

    def _update_saveback_terminal_plan(self, payload: dict[str, Any]) -> None:
        metadata = payload.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise WorkflowValidationError("workflow metadata must be a mapping")
        saveback_closure_plan = metadata.get("saveback_closure_plan", {})
        if not isinstance(saveback_closure_plan, dict):
            raise WorkflowValidationError(
                "workflow saveback_closure_plan must be a mapping"
            )
        node_closures = saveback_closure_plan.get("node_closures", [])
        if not isinstance(node_closures, list):
            raise WorkflowValidationError(
                "workflow saveback closure plan node_closures must be a list"
            )
        migration_notes: list[dict[str, Any]] = metadata.setdefault(
            "migration_notes", []
        )
        node_terminals: list[dict[str, Any]] = []
        terminal_writeback_node_ids: list[str] = []
        closed_terminal_node_ids: list[str] = []
        required_terminal_node_ids: list[str] = []
        recommended_terminal_node_ids: list[str] = []
        for node_closure in node_closures:
            if not isinstance(node_closure, dict):
                raise WorkflowValidationError(
                    "workflow saveback closure node entry must be a mapping"
                )
            node_terminal = self._build_node_saveback_terminal_entry(node_closure)
            node_terminals.append(node_terminal)
            if node_terminal["terminal_writeback_required"]:
                terminal_writeback_node_ids.append(node_terminal["node_id"])
            if node_terminal["closed_after_terminal_writeback"]:
                closed_terminal_node_ids.append(node_terminal["node_id"])
            if node_terminal["severity"] == "required":
                required_terminal_node_ids.append(node_terminal["node_id"])
            elif node_terminal["severity"] == "recommended":
                recommended_terminal_node_ids.append(node_terminal["node_id"])
        highest_severity = "none"
        if required_terminal_node_ids:
            highest_severity = "required"
        elif recommended_terminal_node_ids:
            highest_severity = "recommended"
        workflow_metadata_fields_to_persist = list(
            dict.fromkeys(
                [
                    *saveback_closure_plan.get(
                        "workflow_metadata_fields_to_persist", []
                    ),
                    "saveback_terminal_plan",
                ]
            )
        )
        workflow_audit_summary_fields = [
            "audit_result_summary",
            "required_terminal_node_ids",
            "recommended_terminal_node_ids",
            "terminal_state",
            "terminal_state_updated_at",
        ]
        audit_result_summary = {
            "total_terminal_nodes": len(node_terminals),
            "terminal_writeback_required_count": len(terminal_writeback_node_ids),
            "closed_terminal_count": len(closed_terminal_node_ids),
            "required_terminal_count": len(required_terminal_node_ids),
            "recommended_terminal_count": len(recommended_terminal_node_ids),
            "highest_severity": highest_severity,
        }
        pending_terminal_state = (
            "terminal_writeback_required"
            if terminal_writeback_node_ids
            else "no_terminal_writeback_required"
        )
        saveback_terminal_plan = {
            "schema_version": SCHEMA_VERSION_1_12,
            "target_schema_version": CURRENT_SCHEMA_VERSION,
            "terminal_mode": (
                "writeback_audit_terminal_state"
                if node_terminals
                else "no_terminal_writeback"
            ),
            "requires_terminal_writeback": bool(terminal_writeback_node_ids),
            "terminal_writeback_node_ids": sorted(terminal_writeback_node_ids),
            "closed_terminal_node_ids": sorted(closed_terminal_node_ids),
            "required_terminal_node_ids": sorted(required_terminal_node_ids),
            "recommended_terminal_node_ids": sorted(recommended_terminal_node_ids),
            "audit_result_summary": audit_result_summary,
            "terminal_state": pending_terminal_state,
            "terminal_state_writeback_strategy": {
                "pending_terminal_state": pending_terminal_state,
                "completed_terminal_state": (
                    "terminal_writeback_completed"
                    if terminal_writeback_node_ids
                    else "no_terminal_writeback_required"
                ),
                "terminal_state_timestamp_field": "terminal_state_updated_at",
            },
            "workflow_audit_summary_fields": workflow_audit_summary_fields,
            "workflow_metadata_fields_to_persist": workflow_metadata_fields_to_persist,
            "steps": [
                {
                    "step": "summarize_audit_results",
                    "node_ids": sorted(terminal_writeback_node_ids),
                },
                {
                    "step": "writeback_terminal_node_states",
                    "node_ids": sorted(terminal_writeback_node_ids),
                },
                {
                    "step": "writeback_workflow_audit_summary",
                    "fields": workflow_audit_summary_fields,
                },
                {
                    "step": "persist_terminal_workflow_definition",
                    "fields": workflow_metadata_fields_to_persist,
                },
            ],
            "node_terminals": node_terminals,
        }
        if metadata.get("saveback_terminal_plan") != saveback_terminal_plan:
            metadata["saveback_terminal_plan"] = saveback_terminal_plan
            metadata["saveback_terminal_plan_schema"] = SCHEMA_VERSION_1_12
            migration_notes.append(
                {
                    "migration": "saveback_terminal_plan_updated",
                    "schema_version": SCHEMA_VERSION_1_12,
                    "plan": saveback_terminal_plan,
                }
            )

    def _build_node_compatibility_contract(
        self,
        node: dict[str, Any],
        migration_notes: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        node_id = node.get("node_id")
        node_type = node.get("node_type")
        if not isinstance(node_id, str) or not isinstance(node_type, str):
            return None
        node_metadata = node.get("metadata", {})
        if not isinstance(node_metadata, dict):
            raise WorkflowValidationError("workflow node metadata must be a mapping")
        supported_parameter_aliases: dict[str, str] = {}
        if self._registry is not None and self._registry.has(node_type):
            supported_parameter_aliases = (
                self._registry.get(node_type).build_spec().parameter_aliases or {}
            )
        node_notes = [
            note
            for note in migration_notes
            if isinstance(note, dict) and note.get("node_id") == node_id
        ]
        applied_parameter_aliases = [
            {"from": note["from"], "to": note["to"]}
            for note in node_notes
            if note.get("migration") == "parameter_aliased"
            and isinstance(note.get("from"), str)
            and isinstance(note.get("to"), str)
        ]
        applied_parameter_rules = [
            {
                "from": note.get("from"),
                "to": note["to"],
                "strategy": note["strategy"],
            }
            for note in node_notes
            if note.get("migration") == "parameter_rule_applied"
            and isinstance(note.get("to"), str)
            and isinstance(note.get("strategy"), str)
        ]
        defaulted_parameters = sorted(
            {
                field_name
                for note in node_notes
                if note.get("migration") == "default_params_filled"
                for field_name in note.get("fields", [])
                if isinstance(field_name, str)
            }
        )
        replaced = any(
            note.get("migration") in {"node_type_replaced", "deprecated_node_replaced"}
            for note in node_notes
        )
        resave_required = bool(
            replaced
            or applied_parameter_aliases
            or applied_parameter_rules
            or defaulted_parameters
        )
        return {
            "node_id": node_id,
            "node_type": node_type,
            "canonical_node_version": node_metadata.get(
                "canonical_node_version", "1.0.0"
            ),
            "legacy_node_type": node_metadata.get("migrated_from_node_type"),
            "supported_parameter_aliases": supported_parameter_aliases,
            "applied_parameter_aliases": applied_parameter_aliases,
            "applied_parameter_rules": applied_parameter_rules,
            "defaulted_parameters": defaulted_parameters,
            "replaced": replaced,
            "resave_required": resave_required,
        }

    @staticmethod
    def _build_node_saveback_action(node_contract: dict[str, Any]) -> dict[str, Any]:
        node_id = node_contract["node_id"]
        reason_codes: list[str] = []
        fields_to_drop: set[str] = set()
        fields_to_write: set[str] = set()
        if node_contract.get("replaced"):
            reason_codes.append("node_type_rewritten")
        for alias_note in node_contract.get("applied_parameter_aliases", []):
            if not isinstance(alias_note, dict):
                continue
            source_name = alias_note.get("from")
            target_name = alias_note.get("to")
            if isinstance(source_name, str):
                fields_to_drop.add(source_name)
            if isinstance(target_name, str):
                fields_to_write.add(target_name)
        if node_contract.get("applied_parameter_aliases"):
            reason_codes.append("parameter_aliases_normalized")
        for rule_note in node_contract.get("applied_parameter_rules", []):
            if not isinstance(rule_note, dict):
                continue
            source_name = rule_note.get("from")
            target_name = rule_note.get("to")
            if isinstance(source_name, str):
                fields_to_drop.add(source_name)
            if isinstance(target_name, str):
                fields_to_write.add(target_name)
        if node_contract.get("applied_parameter_rules"):
            reason_codes.append("parameter_rules_applied")
        defaulted_parameters = node_contract.get("defaulted_parameters", [])
        if isinstance(defaulted_parameters, list):
            for field_name in defaulted_parameters:
                if isinstance(field_name, str):
                    fields_to_write.add(field_name)
        if defaulted_parameters:
            reason_codes.append("default_parameters_filled")
        action = "canonical_writeback" if reason_codes else "keep"
        return {
            "node_id": node_id,
            "action": action,
            "canonical_node_type": node_contract["node_type"],
            "legacy_node_type": node_contract.get("legacy_node_type"),
            "fields_to_drop": sorted(fields_to_drop),
            "fields_to_write": sorted(fields_to_write),
            "reason_codes": reason_codes,
        }

    @staticmethod
    def _build_node_saveback_decision(node_action: dict[str, Any]) -> dict[str, Any]:
        reason_codes = node_action.get("reason_codes", [])
        if not isinstance(reason_codes, list):
            reason_codes = []
        severity = "none"
        if any(
            reason_code in {"node_type_rewritten", "parameter_rules_applied"}
            for reason_code in reason_codes
        ):
            severity = "required"
        elif any(
            reason_code in {"parameter_aliases_normalized", "default_parameters_filled"}
            for reason_code in reason_codes
        ):
            severity = "recommended"
        return {
            "node_id": node_action["node_id"],
            "severity": severity,
            "action": node_action["action"],
            "canonical_node_type": node_action["canonical_node_type"],
            "legacy_node_type": node_action.get("legacy_node_type"),
            "reason_codes": reason_codes,
            "fields_to_drop": node_action.get("fields_to_drop", []),
            "fields_to_write": node_action.get("fields_to_write", []),
        }

    @staticmethod
    def _build_node_auto_fix_plan(node_decision: dict[str, Any]) -> dict[str, Any]:
        action = node_decision.get("action", "keep")
        severity = node_decision.get("severity", "none")
        auto_fix = action == "canonical_writeback"
        manual_review = False
        return {
            "node_id": node_decision["node_id"],
            "severity": severity,
            "auto_fix": auto_fix,
            "manual_review": manual_review,
            "editor_action": "apply_canonical_writeback"
            if auto_fix
            else "keep_current",
            "canonical_node_type": node_decision["canonical_node_type"],
            "legacy_node_type": node_decision.get("legacy_node_type"),
            "fields_to_drop": node_decision.get("fields_to_drop", []),
            "fields_to_write": node_decision.get("fields_to_write", []),
            "reason_codes": node_decision.get("reason_codes", []),
        }

    @staticmethod
    def _build_node_saveback_commit_entry(node_plan: dict[str, Any]) -> dict[str, Any]:
        severity = node_plan.get("severity", "none")
        commit_mode = "no_change"
        if severity == "required":
            commit_mode = "confirm_before_persist"
        elif severity == "recommended":
            commit_mode = "review_before_persist"
        validation_checks = ["canonical_payload_consistency"]
        if node_plan.get("fields_to_write"):
            validation_checks.append("fields_written_match_plan")
        if severity == "required":
            validation_checks.append("user_confirmation_recorded")
        return {
            "node_id": node_plan["node_id"],
            "severity": severity,
            "commit_mode": commit_mode,
            "persist_after_apply": bool(node_plan.get("auto_fix"))
            and not bool(node_plan.get("manual_review")),
            "review_required": severity in {"required", "recommended"},
            "canonical_node_type": node_plan["canonical_node_type"],
            "legacy_node_type": node_plan.get("legacy_node_type"),
            "fields_to_drop": node_plan.get("fields_to_drop", []),
            "fields_to_write": node_plan.get("fields_to_write", []),
            "validation_checks": validation_checks,
        }

    @staticmethod
    def _build_node_saveback_audit_entry(node_commit: dict[str, Any]) -> dict[str, Any]:
        commit_mode = node_commit.get("commit_mode", "no_change")
        confirmation_record_required = commit_mode == "confirm_before_persist"
        review_record_required = commit_mode == "review_before_persist"
        audit_fields = ["validation_results", "persisted_fields"]
        if confirmation_record_required:
            audit_fields = ["confirmed_by", "confirmed_at", *audit_fields]
        if review_record_required:
            audit_fields = ["reviewed_by", "reviewed_at", *audit_fields]
        return {
            "node_id": node_commit["node_id"],
            "severity": node_commit.get("severity", "none"),
            "audit_mode": (
                "confirmation_receipt"
                if confirmation_record_required
                else "review_receipt"
                if review_record_required
                else "no_receipt"
            ),
            "confirmation_record_required": confirmation_record_required,
            "review_record_required": review_record_required,
            "persist_audit_after_save": bool(node_commit.get("persist_after_apply")),
            "canonical_node_type": node_commit["canonical_node_type"],
            "legacy_node_type": node_commit.get("legacy_node_type"),
            "fields_to_drop": node_commit.get("fields_to_drop", []),
            "fields_to_write": node_commit.get("fields_to_write", []),
            "validation_checks": node_commit.get("validation_checks", []),
            "audit_fields": audit_fields,
        }

    @staticmethod
    def _build_node_saveback_closure_entry(
        node_audit: dict[str, Any],
    ) -> dict[str, Any]:
        audit_mode = node_audit.get("audit_mode", "no_receipt")
        closure_required = bool(node_audit.get("persist_audit_after_save"))
        closure_mode = "noop_closure"
        if audit_mode == "confirmation_receipt":
            closure_mode = "writeback_confirmation_receipt"
        elif audit_mode == "review_receipt":
            closure_mode = "writeback_review_receipt"
        closure_status_fields = [
            "audit_result_status",
            "audit_persisted_at",
            "closure_status",
        ]
        closure_checks = list(node_audit.get("validation_checks", []))
        if closure_required:
            closure_checks.append("audit_receipt_persisted")
        return {
            "node_id": node_audit["node_id"],
            "severity": node_audit.get("severity", "none"),
            "closure_mode": closure_mode,
            "closure_required": closure_required,
            "batch_writeback_eligible": closure_required,
            "close_after_writeback": closure_required,
            "canonical_node_type": node_audit["canonical_node_type"],
            "legacy_node_type": node_audit.get("legacy_node_type"),
            "fields_to_drop": node_audit.get("fields_to_drop", []),
            "fields_to_write": node_audit.get("fields_to_write", []),
            "audit_fields": node_audit.get("audit_fields", []),
            "closure_status_fields": closure_status_fields,
            "closure_checks": closure_checks,
        }

    @staticmethod
    def _build_node_saveback_terminal_entry(
        node_closure: dict[str, Any],
    ) -> dict[str, Any]:
        closure_mode = node_closure.get("closure_mode", "noop_closure")
        severity = node_closure.get("severity", "none")
        terminal_state = "no_terminal_update"
        receipt_summary = "no_receipt_recorded"
        if closure_mode == "writeback_confirmation_receipt":
            terminal_state = "closed_confirmed"
            receipt_summary = "confirmation_receipt_recorded"
        elif closure_mode == "writeback_review_receipt":
            terminal_state = "closed_reviewed"
            receipt_summary = "review_receipt_recorded"
        elif node_closure.get("closure_required"):
            terminal_state = "closed_written_back"
        writeback_summary = (
            "terminal_writeback_required"
            if node_closure.get("closure_required")
            else "no_terminal_writeback_required"
        )
        terminal_summary_fields = [
            "receipt_summary",
            "writeback_summary",
            "terminal_state",
        ]
        action = (
            "writeback_required"
            if node_closure.get("closure_required")
            else "monitor_only"
        )
        reasons = [
            reason
            for reason in [
                "requires_confirmation_receipt"
                if closure_mode == "writeback_confirmation_receipt"
                else None,
                "requires_review_receipt"
                if closure_mode == "writeback_review_receipt"
                else None,
                "terminal_writeback_pending"
                if node_closure.get("closure_required")
                else None,
                "writeback_can_be_deferred"
                if not node_closure.get("closure_required")
                else None,
            ]
            if reason is not None
        ]
        summary = TerminalPlanSummary(
            receipt_summary=receipt_summary,
            writeback_summary=writeback_summary,
            terminal_state=terminal_state,
        )
        terminal_checks = list(node_closure.get("closure_checks", []))
        if node_closure.get("closure_required"):
            terminal_checks.append("terminal_state_persisted")
        response = TerminalPlanResponse(action=action, reasons=reasons, summary=summary)
        return {
            "node_id": node_closure["node_id"],
            "severity": severity,
            "action": response.action,
            "reasons": response.reasons,
            "summary": response.summary.model_dump(),
            "suggested_action": action,
            "risk_reasons": reasons,
            "terminal_summary": response.summary.model_dump(),
            "terminal_state": terminal_state,
            "terminal_writeback_required": bool(node_closure.get("closure_required")),
            "closed_after_terminal_writeback": bool(
                node_closure.get("close_after_writeback")
            ),
            "canonical_node_type": node_closure["canonical_node_type"],
            "legacy_node_type": node_closure.get("legacy_node_type"),
            "fields_to_drop": node_closure.get("fields_to_drop", []),
            "fields_to_write": node_closure.get("fields_to_write", []),
            "audit_fields": node_closure.get("audit_fields", []),
            "closure_status_fields": node_closure.get("closure_status_fields", []),
            "receipt_summary": receipt_summary,
            "writeback_summary": writeback_summary,
            "terminal_summary_fields": terminal_summary_fields,
            "terminal_checks": terminal_checks,
        }

    def _migrate_nodes(self, payload: dict[str, Any]) -> None:
        nodes = payload.get("nodes", [])
        if not isinstance(nodes, list):
            raise WorkflowValidationError("workflow nodes must be a list")
        migration_notes: list[dict[str, Any]] = payload["metadata"].setdefault(
            "migration_notes", []
        )
        for node in nodes:
            if not isinstance(node, dict):
                raise WorkflowValidationError("workflow node payload must be a mapping")
            original_node_type = node.get("node_type")
            if not isinstance(original_node_type, str) or not original_node_type:
                raise WorkflowValidationError("workflow node payload missing node_type")
            node.setdefault("metadata", {})
            if not isinstance(node["metadata"], dict):
                raise WorkflowValidationError(
                    "workflow node metadata must be a mapping"
                )

            replaced_node_type = self._apply_legacy_node_mapping(node)
            if replaced_node_type is not None:
                migration_notes.append(
                    {
                        "node_id": node.get("node_id"),
                        "migration": "node_type_replaced",
                        "from": original_node_type,
                        "to": replaced_node_type,
                    }
                )
                legacy_mapping = LEGACY_NODE_MAPPINGS[original_node_type]
                migration_notes.extend(
                    {
                        "node_id": node.get("node_id"),
                        "migration": "parameter_rule_applied",
                        **note,
                    }
                    for note in self._apply_parameter_migration_rules(
                        node,
                        legacy_mapping.get("parameter_migration_rules", []),
                    )
                )

            alias_notes = self._apply_canonical_parameter_aliases(node)
            migration_notes.extend(
                {
                    "node_id": node.get("node_id"),
                    "migration": "parameter_aliased",
                    "from": alias_name,
                    "to": target_name,
                }
                for alias_name, target_name in alias_notes
            )

            deprecated_replacement = self._apply_deprecated_node_replacement(node)
            if deprecated_replacement is not None:
                migration_notes.append(
                    {
                        "node_id": node.get("node_id"),
                        "migration": "deprecated_node_replaced",
                        "from": deprecated_replacement[0],
                        "to": deprecated_replacement[1],
                    }
                )
                migration_notes.extend(
                    {
                        "node_id": node.get("node_id"),
                        "migration": "parameter_rule_applied",
                        **note,
                    }
                    for note in self._apply_parameter_migration_rules(
                        node,
                        self._get_deprecated_replacement_parameter_rules(
                            deprecated_replacement[0]
                        ),
                    )
                )
                alias_notes = self._apply_canonical_parameter_aliases(node)
                migration_notes.extend(
                    {
                        "node_id": node.get("node_id"),
                        "migration": "parameter_aliased",
                        "from": alias_name,
                        "to": target_name,
                    }
                    for alias_name, target_name in alias_notes
                )

            defaulted_fields = self._apply_canonical_param_defaults(node)
            if defaulted_fields:
                migration_notes.append(
                    {
                        "node_id": node.get("node_id"),
                        "migration": "default_params_filled",
                        "fields": defaulted_fields,
                    }
                )

    def _apply_legacy_node_mapping(self, node: dict[str, Any]) -> str | None:
        node_type = node["node_type"]
        mapping = LEGACY_NODE_MAPPINGS.get(node_type)
        if mapping is None:
            return None
        params = node.setdefault("params", {})
        if not isinstance(params, dict):
            raise WorkflowValidationError(
                f"node {node.get('node_id')} params must be a mapping"
            )
        self._apply_alias_map(params, mapping.get("parameter_aliases", {}))
        node["metadata"]["migrated_from_node_type"] = node_type
        node["node_type"] = mapping["replacement_node_type"]
        return mapping["replacement_node_type"]

    def _apply_deprecated_node_replacement(
        self, node: dict[str, Any]
    ) -> tuple[str, str] | None:
        if self._registry is None:
            return None
        node_type = node["node_type"]
        if not self._registry.has(node_type):
            return None
        canonical = self._registry.get(node_type).build_spec()
        replacement_node_type = canonical.replacement_node_type
        if not canonical.deprecated or not replacement_node_type:
            return None
        if not self._registry.has(replacement_node_type):
            node["metadata"]["deprecated_replacement_unavailable"] = (
                replacement_node_type
            )
            return None
        node["metadata"].setdefault("migrated_from_node_type", node_type)
        node["metadata"]["replaced_deprecated_node_type"] = node_type
        node["node_type"] = replacement_node_type
        return node_type, replacement_node_type

    def _get_deprecated_replacement_parameter_rules(
        self,
        deprecated_node_type: str,
    ) -> list[dict[str, Any]]:
        if self._registry is None or not self._registry.has(deprecated_node_type):
            return []
        canonical = self._registry.get(deprecated_node_type).build_spec()
        metadata = canonical.metadata or {}
        rules = metadata.get("replacement_parameter_rules", [])
        if not isinstance(rules, list):
            raise WorkflowValidationError(
                f"deprecated node {deprecated_node_type} replacement_parameter_rules must be a list"
            )
        return rules

    def _apply_canonical_parameter_aliases(
        self, node: dict[str, Any]
    ) -> list[tuple[str, str]]:
        if self._registry is None:
            return []
        node_type = node["node_type"]
        if not self._registry.has(node_type):
            return []
        params = node.setdefault("params", {})
        if not isinstance(params, dict):
            raise WorkflowValidationError(
                f"node {node.get('node_id')} params must be a mapping"
            )
        canonical = self._registry.get(node_type).build_spec()
        alias_map = canonical.parameter_aliases or {}
        return self._apply_alias_map(params, alias_map)

    def _apply_canonical_param_defaults(self, node: dict[str, Any]) -> list[str]:
        if self._registry is None:
            return []
        node_type = node["node_type"]
        if not self._registry.has(node_type):
            return []
        params = node.setdefault("params", {})
        if not isinstance(params, dict):
            raise WorkflowValidationError(
                f"node {node.get('node_id')} params must be a mapping"
            )
        canonical = self._registry.get(node_type).build_spec()
        applied: list[str] = []
        for field_name, default_value in canonical.params.items():
            if field_name in params:
                continue
            params[field_name] = deepcopy(default_value)
            applied.append(field_name)
        return applied

    def _apply_parameter_migration_rules(
        self,
        node: dict[str, Any],
        rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not rules:
            return []
        params = node.setdefault("params", {})
        if not isinstance(params, dict):
            raise WorkflowValidationError(
                f"node {node.get('node_id')} params must be a mapping"
            )
        applied: list[dict[str, Any]] = []
        for rule in rules:
            if not isinstance(rule, dict):
                raise WorkflowValidationError(
                    f"node {node.get('node_id')} parameter migration rule must be a mapping"
                )
            target_name = rule.get("to")
            if not isinstance(target_name, str) or not target_name:
                raise WorkflowValidationError(
                    f"node {node.get('node_id')} parameter migration rule missing target"
                )
            if target_name in params:
                continue
            source_name = rule.get("from")
            if "value" in rule:
                params[target_name] = deepcopy(rule["value"])
                applied.append(
                    {
                        "to": target_name,
                        "strategy": "literal",
                    }
                )
                continue
            if (
                not isinstance(source_name, str)
                or not source_name
                or source_name not in params
            ):
                continue
            transform = rule.get("transform", "identity")
            params[target_name] = self._transform_parameter_value(
                params.pop(source_name), transform
            )
            applied.append(
                {
                    "from": source_name,
                    "to": target_name,
                    "strategy": transform,
                }
            )
        return applied

    @staticmethod
    def _transform_parameter_value(value: Any, transform: Any) -> Any:
        if transform in (None, "identity"):
            return value
        if transform == "bool":
            return bool(value)
        if transform == "int":
            return int(value)
        if transform == "float":
            return float(value)
        if transform == "stringify":
            return str(value)
        if transform == "wrap_list":
            return [value]
        raise WorkflowValidationError(
            f"unsupported parameter migration transform: {transform}"
        )

    @staticmethod
    def _apply_alias_map(
        params: dict[str, Any], alias_map: dict[str, str]
    ) -> list[tuple[str, str]]:
        applied: list[tuple[str, str]] = []
        for alias_name, target_name in alias_map.items():
            if alias_name not in params or target_name in params:
                continue
            params[target_name] = params.pop(alias_name)
            applied.append((alias_name, target_name))
        return applied
