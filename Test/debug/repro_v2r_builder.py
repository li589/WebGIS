"""本地复刻 request_builder：dump 的 payload → JobRequest，检查 ds 存活性。"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "Code"))
sys.path.insert(0, str(REPO / "Code" / "backend"))

from shared.contracts.api_contracts import WorkflowSubmitRequest

from app.services.python_provider_request_builder import (
    PythonProviderRequestBuilder,
)

payload_raw = json.loads(
    (REPO / "Test" / "debug" / "v2r_api_payload.json").read_text(encoding="utf-8")
)
payload = WorkflowSubmitRequest(**payload_raw)
print("submit model ok; ar type:", type(payload.algorithm_request).__name__)

from app.services.workflow_request_resolver import normalize_workflow_submit_request

payload = normalize_workflow_submit_request(payload)
ar = payload.algorithm_request
ar_dict = (
    ar.model_dump(mode="json", exclude_none=True)
    if hasattr(ar, "model_dump")
    else dict(ar)
)
print("post-normalize module_name:", ar_dict.get("module_name"))
print("post-normalize has workflow_definition:", bool(ar_dict.get("workflow_definition")))
print(
    "post-normalize ds:",
    json.dumps(ar_dict.get("datasource_selection"), ensure_ascii=False),
)

builder = PythonProviderRequestBuilder()
job = builder.build_job_request_payload(run_id="repro-builder", payload=payload)
ds = job.get("datasource_selection")
print("job ds keys:", sorted(ds.keys()) if isinstance(ds, dict) else ds)
print("job ds input_path:", ds.get("input_path") if isinstance(ds, dict) else None)
print("job module_name:", job.get("module_name"))
print("job workflow_name:", job.get("workflow_name"))
print("job has workflow_definition:", bool(job.get("workflow_definition")))
