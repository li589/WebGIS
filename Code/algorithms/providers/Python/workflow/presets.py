from __future__ import annotations

from contracts.job import JobRequest
from contracts.modes import RetrievalMode
from workflow.graph import WorkflowDefinition, WorkflowEdge, WorkflowNodeSpec, WorkflowOutputSpec


def build_retrieval_workflow_definition(request: JobRequest) -> WorkflowDefinition:
    mode = str(request.algorithm_params.get("mode", RetrievalMode.DH.value)).lower()
    if mode == RetrievalMode.OMEGA.value:
        retrieval_node = WorkflowNodeSpec(
            node_id="omega_block",
            node_type="module",
            input_bindings={
                "algorithm_params": "request:algorithm_params",
                "output_spec_extra": "request:output_spec_extra",
                "omega_fixed_mat": "input:omega_fixed_mat",
                "exp0_calib_mat": "input:exp0_calib_mat",
            },
            params={"module_name": "omega_block", "mode": mode},
        )
    else:
        retrieval_bindings = {
            "algorithm_params": "request:algorithm_params",
            "output_spec_extra": "request:output_spec_extra",
        }
        if "dh_mat" in request.datasource_selection:
            retrieval_bindings["dh_mat"] = "input:dh_mat"
        retrieval_node = WorkflowNodeSpec(
            node_id="block_inversion",
            node_type="module",
            input_bindings=retrieval_bindings,
            params={"module_name": "block_inversion", "mode": mode},
        )

    return WorkflowDefinition(
        workflow_id="retrieval_workflow",
        name="retrieval_workflow",
        description="Preset workflow that builds a time-series bundle and runs block retrieval.",
        nodes=[
            WorkflowNodeSpec(
                node_id="timeseries_bundle",
                node_type="module",
                input_bindings={
                    "datasource_selection": "request:datasource_selection",
                    "algorithm_params": "request:algorithm_params",
                    "output_spec_extra": "request:output_spec_extra",
                },
                params={"module_name": "timeseries_bundle"},
            ),
            retrieval_node,
        ],
        edges=[WorkflowEdge(from_node="timeseries_bundle", from_port="output_path", to_node=retrieval_node.node_id, to_port="input_mat")],
        outputs=[WorkflowOutputSpec(name="final_manifest", source=f"node:{retrieval_node.node_id}.manifest")],
        metadata={"generated_from": "workflow.presets", "mode": mode},
    )


NAMED_WORKFLOW_BUILDERS = {
    "retrieval_workflow": build_retrieval_workflow_definition,
}


def has_named_workflow(name: str) -> bool:
    return name in NAMED_WORKFLOW_BUILDERS


def list_named_workflows() -> list[str]:
    return sorted(NAMED_WORKFLOW_BUILDERS)


def build_named_workflow(name: str, request: JobRequest) -> WorkflowDefinition:
    if name not in NAMED_WORKFLOW_BUILDERS:
        raise KeyError(f"Unknown workflow preset: {name}")
    return NAMED_WORKFLOW_BUILDERS[name](request)
