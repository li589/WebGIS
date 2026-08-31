import json
import sqlite3

conn = sqlite3.connect(r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3")
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("tables:", tables)
rows = conn.execute(
    "SELECT run_id, status, updated_at FROM workflow_runs ORDER BY updated_at DESC LIMIT 3"
).fetchall()
for r in rows:
    print(r)
cols = [c[1] for c in conn.execute("PRAGMA table_info(workflow_runs)").fetchall()]
print("cols:", cols)

row = conn.execute(
    "SELECT status, payload_json FROM workflow_runs WHERE run_id=?", ("run-1a0f754b7f0a",)
).fetchone()
if row:
    pj = json.loads(row[1])
    algo = pj.get("algorithm_request") or {}
    print("status:", row[0])
    print("workflow_name:", algo.get("workflow_name"))
    print("module_name present:", "module_name" in algo)
    print("workflow_entry_name:", algo.get("workflow_entry_name"))
    wf = algo.get("workflow_definition")
    if isinstance(wf, dict):
        print("graph nodes:", [str(n.get("type")) for n in wf.get("nodes", [])])
    print("time_range:", pj.get("time_range"))
else:
    print("run-1a0f754b7f0a NOT in this DB")
