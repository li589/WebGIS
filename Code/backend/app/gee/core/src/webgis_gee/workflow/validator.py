from __future__ import annotations

import networkx as nx

from webgis_gee.domain.enums import PortKind
from webgis_gee.domain.models import NodeSpec, PortSpec, WorkflowDefinition
from webgis_gee.nodes.registry import NodeRegistry
from webgis_gee.runtime.exceptions import WorkflowValidationError
from webgis_gee.workflow.versioning import WorkflowDefinitionMigrator


class WorkflowValidator:
    """Structural validator for workflow definitions."""

    def __init__(
        self,
        registry: NodeRegistry,
        migrator: WorkflowDefinitionMigrator | None = None,
    ) -> None:
        self._registry = registry
        self._migrator = migrator

    def validate(self, workflow: WorkflowDefinition) -> None:
        if self._migrator is not None:
            self._migrator.validate_compatibility(workflow)
        node_map = {node.node_id: node for node in workflow.nodes}
        canonical_specs: dict[str, NodeSpec] = {}

        for node in workflow.nodes:
            try:
                node_cls = self._registry.get(node.node_type)
            except KeyError as exc:
                raise WorkflowValidationError(str(exc)) from exc
            canonical_specs[node.node_id] = self._get_canonical_spec(node_cls)

        graph = nx.DiGraph()
        graph.add_nodes_from(node_map.keys())
        inbound_ports: dict[str, set[str]] = {
            node.node_id: set() for node in workflow.nodes
        }

        for edge in workflow.edges:
            if edge.source_node_id not in node_map:
                raise WorkflowValidationError(
                    f"unknown source node: {edge.source_node_id}"
                )
            if edge.target_node_id not in node_map:
                raise WorkflowValidationError(
                    f"unknown target node: {edge.target_node_id}"
                )

            source_ports = self._port_map(
                node=node_map[edge.source_node_id],
                canonical=canonical_specs[edge.source_node_id],
                use_input_ports=False,
            )
            target_ports = self._port_map(
                node=node_map[edge.target_node_id],
                canonical=canonical_specs[edge.target_node_id],
                use_input_ports=True,
            )

            if edge.source_port not in source_ports:
                raise WorkflowValidationError(
                    f"unknown source port {edge.source_port!r} on node: {edge.source_node_id}"
                )
            if edge.target_port not in target_ports:
                raise WorkflowValidationError(
                    f"unknown target port {edge.target_port!r} on node: {edge.target_node_id}"
                )
            if not self._ports_compatible(
                source=source_ports[edge.source_port],
                target=target_ports[edge.target_port],
            ):
                raise WorkflowValidationError(
                    "incompatible port kinds for "
                    f"{edge.source_node_id}.{edge.source_port} -> "
                    f"{edge.target_node_id}.{edge.target_port}"
                )

            graph.add_edge(edge.source_node_id, edge.target_node_id)
            inbound_ports[edge.target_node_id].add(edge.target_port)

        if not nx.is_directed_acyclic_graph(graph):
            raise WorkflowValidationError("workflow graph must be a DAG")

        for node in workflow.nodes:
            for port in self._port_map(
                node=node,
                canonical=canonical_specs[node.node_id],
                use_input_ports=True,
            ).values():
                if not port.required:
                    continue
                if port.name in inbound_ports[node.node_id]:
                    continue
                if port.name in workflow.inputs:
                    continue
                if port.name in node.params:
                    continue
                raise WorkflowValidationError(
                    f"missing required input port {port.name!r} for node: {node.node_id}"
                )

    @staticmethod
    def _get_canonical_spec(node_cls: type) -> NodeSpec:
        spec = node_cls.build_spec()
        if not isinstance(spec, NodeSpec):
            raise WorkflowValidationError(
                f"node class {node_cls.__name__} returned invalid build_spec() payload"
            )
        return spec

    @staticmethod
    def _port_map(
        node: NodeSpec,
        canonical: NodeSpec,
        use_input_ports: bool,
    ) -> dict[str, PortSpec]:
        ports = node.input_ports if use_input_ports else node.output_ports
        if not ports:
            ports = canonical.input_ports if use_input_ports else canonical.output_ports
        return {port.name: port for port in ports}

    @staticmethod
    def _ports_compatible(source: PortSpec, target: PortSpec) -> bool:
        return (
            source.kind == target.kind
            or source.kind == PortKind.VALUE
            or target.kind == PortKind.VALUE
        )
