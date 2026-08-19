import json
import sqlite3
import sys

run_id = sys.argv[1] if len(sys.argv) > 1 else "run-10060b8de27b"
conn = sqlite3.connect(r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3")
conn.row_factory = sqlite3.Row
row = conn.execute(
    "SELECT request_json, status FROM workflow_runs WHERE run_id=?", (run_id,)
).fetchone()
if row is None:
    print("run not found")
else:
    print("status:", row["status"])
    d = json.loads(row["request_json"])
    ar = d.get("algorithm_request") or {}
    print("algorithm_request keys:", list(ar.keys()))
    print("datasource_selection:", json.dumps(ar.get("datasource_selection"), ensure_ascii=False))
    print("module_name:", ar.get("module_name"))
    print("workflow_name:", ar.get("workflow_name"))
    print("has workflow_definition:", "workflow_definition" in ar)
    print("command_type:", d.get("command_type"))
    print("parameters:", json.dumps(d.get("parameters"), ensure_ascii=False)[:300])
    wf = ar.get("workflow_definition")
    if isinstance(wf, dict):
        for n in wf.get("nodes") or []:
            params = n.get("params") or {}
            print("wf node:", n.get("node_type"), {k: v for k, v in params.items() if k in ("path", "dataset_key", "module_name")})
