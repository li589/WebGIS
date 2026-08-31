import json
import sqlite3
import sys

conn = sqlite3.connect(r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3")
rows = conn.execute(
    "SELECT run_id, status, updated_at, payload_json FROM workflow_runs ORDER BY updated_at DESC LIMIT 12"
).fetchall()
for rid, st, ts, pj in rows:
    pj = json.loads(pj)
    label = pj.get("command_label") or ""
    print(rid, st, ts, label)
