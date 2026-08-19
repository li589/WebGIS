"""诊断：对比 API 视角与两个候选 workflow_state 数据库。"""

import json
import sqlite3
import urllib.request

BASE = "http://127.0.0.1:8000"
DBS = {
    "repo_old": r"Code\backend\.data\workflow_state\workflow_state.sqlite3",
    "repo_runtime": r"Code\backend\.data\_runtime\workflow_state\workflow_state.sqlite3",
    "i_drive": r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3",
}
PROBE_IDS = ("run-3e3a4a01b1bb", "run-probe0001", "run-19e73c905550", "run-cb99870d887c")

req = urllib.request.Request(BASE + "/auth/login", method="POST")
req.add_header("Content-Type", "application/json")
with urllib.request.urlopen(req, timeout=10, data=json.dumps(
    {"username": "admin", "password": "cgda-dev-admin"}
).encode()) as resp:
    cookie = resp.headers.get("Set-Cookie", "").split(";")[0]

req = urllib.request.Request(BASE + "/workflow-runs?active_only=false&limit=200")
req.add_header("Cookie", cookie)
with urllib.request.urlopen(req, timeout=20) as resp:
    items = json.loads(resp.read())
print("API page count:", len(items))
print("API latest 3:")
for it in items[:3]:
    print("  ", it.get("run_id"), it.get("status"), it.get("updated_at"))

for name, path in DBS.items():
    try:
        conn = sqlite3.connect(path)
        total = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
        latest = conn.execute(
            "SELECT run_id, status, updated_at FROM workflow_runs"
            " ORDER BY updated_at DESC LIMIT 3"
        ).fetchall()
        probe_rows = {}
        for rid in PROBE_IDS:
            row = conn.execute(
                "SELECT status, updated_at FROM workflow_runs WHERE run_id=?",
                (rid,),
            ).fetchone()
            probe_rows[rid] = row
        print(f"\n[{name}] {path}")
        print("  total:", total)
        print("  latest:", latest)
        for rid, row in probe_rows.items():
            print(f"  probe {rid}: {row}")
        conn.close()
    except Exception as exc:
        print(f"\n[{name}] {path} ERROR: {exc}")
