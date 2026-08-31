"""全链 worker 复刻：normalize → builder → job_api.submit_job（进程内执行）。

等价于 Celery worker 进程内 python_provider_bridge_service.execute 的调用序列。
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "Code"))
sys.path.insert(0, str(REPO / "Code" / "backend"))

from shared.contracts.api_contracts import WorkflowSubmitRequest

from app.services.workflow_request_resolver import normalize_workflow_submit_request
from app.services.python_provider_request_builder import (
    PythonProviderRequestBuilder,
)
from app.services.python_provider_bridge_service import _load_python_job_service

payload_raw = json.loads(
    (REPO / "Test" / "debug" / "v2r_api_payload.json").read_text(encoding="utf-8")
)
payload = WorkflowSubmitRequest(**payload_raw)
payload = normalize_workflow_submit_request(payload)

builder = PythonProviderRequestBuilder()
job = builder.build_job_request_payload(run_id="repro-full-chain", payload=payload)
ds = job.get("datasource_selection") or {}
print("job ds input_path:", ds.get("input_path"))

service = _load_python_job_service()
resp = service.submit_job(job)
body = resp.body if hasattr(resp, "body") else resp
print("status_code:", getattr(resp, "status_code", None))
print("body:", json.dumps(body, ensure_ascii=False, default=str)[:800])
