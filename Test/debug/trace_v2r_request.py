import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "Code" / "backend"))
sys.path.insert(0, str(REPO / "Code"))

from app.services.workflow_definition_service import get_definition
from app.services.workflow_request_resolver import (
    _flatten_ui_workflow_definition,
)

SEED = "analysis_vector_to_raster"
definition = get_definition(SEED)
print("seed nodes:", [(n.get("type"), n.get("properties", {}).get("path")) for n in definition["nodes"]])

# Simulate smoke payload: compile via graph compiler
from app.services.workflow_graph_compiler import compile_litegraph_to_workflow_definition

compiled = compile_litegraph_to_workflow_definition(
    workflow_id=SEED,
    name=definition.get("name"),
    description=definition.get("description"),
    nodes=definition.get("nodes", []),
    links=definition.get("links", []),
)
compiled_nodes = compiled.get("nodes")
print("compiled nodes:", [(n.get("node_type"), {k: v for k, v in (n.get("params") or {}).items() if k in ("path", "dataset_key", "module_name")}) for n in compiled_nodes])

# Smoke-style ds extraction from seed
DATA_ROOT = Path(r"I:\Geograph_DataSet")
ds = {}
for node in definition.get("nodes"):
    if node.get("type") != "data/source":
        continue
    props = node.get("properties") or {}
    key = props.get("dataset_key")
    path = props.get("path")
    path_s = str(path).replace("{DATA_ROOT}", str(DATA_ROOT)).replace("\\", "/")
    if key:
        ds[str(key)] = path_s
    ds.setdefault("input_path", path_s)
print("smoke ds:", ds)

# Build the payload like build_payload does
algorithm_request = {
    "algorithm_params": {},
    "datasource_selection": ds,
    "workflow_definition": compiled,
}

class _Desc:
    engine = "python_provider"
    module_name = None
    workflow_name = None
    default_task_type = None
    default_data_access_sources = {}

from dataclasses import dataclass

@dataclass
class Payload:
    algorithm_request: dict
    command_type: str = "analysis"
    layer_id: str | None = None
    time_range: object = None
    spatial_filter: object = None

payload = Payload(algorithm_request=algorithm_request)
flat, tr, sp = _flatten_ui_workflow_definition(algorithm_request, descriptor=_Desc())
print("flattened ds:", flat.get("datasource_selection"))
print("flattened module_name:", flat.get("module_name"))
print("flattened has workflow_definition:", "workflow_definition" in flat)
