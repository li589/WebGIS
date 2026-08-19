"""服务端提交链路 repro：analysis_vector_to_raster ds 是否在展平后存活。

复刻 smoke 提交体（ds=绝对路径 + workflow_definition=compile API 结果），
本地调用 normalize_workflow_submit_request，打印最终 algorithm_request。
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "Code"))
sys.path.insert(0, str(REPO / "Code" / "backend"))

from app.services.workflow_definition_service import get_definition
from app.services.workflow_graph_compiler import (
    compile_litegraph_to_workflow_definition,
)

from shared.contracts.api_contracts import (
    TimeRange,
    WorkflowCommandType,
    WorkflowSubmitRequest,
)

GEOJSON = "I:/Geograph_DataSet/_runtime/smoke_vector.geojson"


def build_compiled() -> dict:
    defn = get_definition("analysis_vector_to_raster")
    print("seed found:", bool(defn))
    if defn is None:
        raise SystemExit("seed missing")
    compiled = compile_litegraph_to_workflow_definition(
        workflow_id="analysis_vector_to_raster",
        name=defn.get("name"),
        description=defn.get("description"),
        nodes=defn.get("nodes", []),
        links=defn.get("links", []),
    )
    for node in compiled["nodes"]:
        if node.get("params", {}).get("path"):
            print(
                "compiled node path:",
                node["node_id"],
                repr(node["params"]["path"]),
            )
    return compiled


def main() -> None:
    compiled = build_compiled()
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        parameters={},
        time_range=TimeRange(
            start_at="2025-01-01T00:00:00+00:00",
            end_at="2025-01-02T00:00:00+00:00",
        ),
        algorithm_request={
            "algorithm_params": {},
            "datasource_selection": {"input_path": GEOJSON},
            "workflow_definition": compiled,
        },
    )

    from app.services.workflow_request_resolver import (
        normalize_workflow_submit_request,
    )

    out = normalize_workflow_submit_request(payload)
    ar = out.algorithm_request
    ar_dict = (
        ar.model_dump(mode="json", exclude_none=True)
        if hasattr(ar, "model_dump")
        else dict(ar)
    )
    print("=== AFTER normalize ===")
    print("module_name:", ar_dict.get("module_name"))
    print("workflow_name:", ar_dict.get("workflow_name"))
    print("has workflow_definition:", bool(ar_dict.get("workflow_definition")))
    ds = ar_dict.get("datasource_selection")
    print("datasource_selection:", json.dumps(ds, ensure_ascii=False))
    ok = isinstance(ds, dict) and str(
        ds.get("input_path") or ""
    ).lower() == GEOJSON.lower()
    print("VERDICT:", "OK — ds survives" if ok else "BROKEN — ds lost/overwritten")


if __name__ == "__main__":
    main()
