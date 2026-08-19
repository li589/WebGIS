import json
import sqlite3

conn = sqlite3.connect(r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3")
row = conn.execute(
    "SELECT payload_json FROM workflow_runs WHERE run_id='run-ba1d5ac94d10'"
).fetchone()
p = json.loads(row[0])
print("top keys:", sorted(p.keys())[:20])
for key in ("workflow_id", "definition_id", "status"):
    print(key, "=", p.get(key))
result = p.get("result") or p.get("result_dto") or {}
if isinstance(result, dict):
    print("result keys:", sorted(result.keys())[:20])
    print("result.status:", result.get("status"))

print("command_label:", p.get("command_label"))
rd = p.get("result_dto") or {}
print("workflow_entry_name:", rd.get("workflow_entry_name"))
print("job_status:", rd.get("job_status"))

rows = conn.execute(
    "SELECT run_id, status, updated_at, payload_json FROM workflow_runs ORDER BY updated_at DESC LIMIT 40"
).fetchall()
for rid, st, ts, pj in rows:
    pj = json.loads(pj)
    label = pj.get("command_label") or (pj.get("result_dto") or {}).get("workflow_entry_name") or ""
    if "vector" in str(label).lower() or "analysis" in str(label).lower():
        print(rid, st, ts, label)
