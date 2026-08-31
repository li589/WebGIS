import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "Code" / "backend"))
sys.path.insert(0, str(REPO / "Code"))

from app.services.workflow_definition_service import get_definition
from app.services.workflow_graph_compiler import compile_litegraph_to_workflow_definition
from app.services.workflow_request_resolver import normalize_workflow_submit_request
from shared.contracts.api_contracts import WorkflowSubmitRequest

SEED = "analysis_vector_to_raster"
definition = get_definition(SEED)

compiled = compile_litegraph_to_workflow_definition(
    workflow_id=SEED,
    name=definition.get("name"),
    description=definition.get("description"),
    nodes=definition.get("nodes", []),
    links=definition.get("links", []),
)

DATA_ROOT = Path(r"I:\Geograph_DataSet")
ds = {}
for node in definition.get("nodes"):
    if node.get("type") != "data/source":
        continue
    props = node.get("properties") or {}
    path_s = str(props.get("path")).replace("{DATA_ROOT}", str(DATA_ROOT)).replace("\\", "/")
    ds[props.get("dataset_key")] = path_s

algo_params = {}
for node in definition.get("nodes"):
    ntype = str(node.get("type") or "")
    props = node.get("properties") or {}
    if ntype.startswith(("preprocess/", "gis/", "stats/", "fusion/", "viz/")):
        for k, v in props.items():
            if k not in ("notes", "path", "dataset_key"):
                algo_params.setdefault(k, v)

payload_dict = {
    "command_type": "analysis",
    "command_label": "smoke:analysis_vector_to_raster",
    "parameters": algo_params,
    "requested_outputs": ["json"],
    "client": {"client_id": "smoke_system_workflows", "page": "tools"},
    "algorithm_request": {
        "algorithm_params": algo_params,
        "datasource_selection": ds,
        "workflow_definition": compiled,
    },
    "time_range": {
        "start_at": "2025-01-01T00:00:00Z",
        "end_at": "2025-01-02T00:00:00Z",
        "granularity": "day",
    },
}

payload = WorkflowSubmitRequest.model_validate(payload_dict)
normalized = normalize_workflow_submit_request(payload)

from app.services.python_provider_bridge_service import PythonProviderBridgeService

bridge = PythonProviderBridgeService()


class NullEventFactory:
    def emit(self, *a, **k):
        pass


result = bridge.execute(
    run_id="debug-bridge-run",
    payload=normalized,
    requested_at=None,
    event_factory=NullEventFactory(),
)
print("status:", result.status)
print("error:", getattr(result, "error_message", None))
body = getattr(result, "result_dto", None) or getattr(result, "body", None)
print("body:", json.dumps(body, ensure_ascii=False, default=str)[:800] if body else None)
