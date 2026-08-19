"""决定性测试：通过 API 提交一个 run，然后直查各候选库定位落盘位置。"""

import json
import sqlite3
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
DB = r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3"


def http(method: str, path: str, body=None, cookie=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data, timeout=30) as resp:
        return resp.status, json.loads(resp.read())


_, _ = http("POST", "/auth/login", {"username": "admin", "password": "cgda-dev-admin"})
req = urllib.request.Request(BASE + "/auth/login", method="POST")
req.add_header("Content-Type", "application/json")
with urllib.request.urlopen(req, timeout=10, data=json.dumps(
    {"username": "admin", "password": "cgda-dev-admin"}
).encode()) as resp:
    cookie = resp.headers.get("Set-Cookie", "").split(";")[0]

payload = {
    "workflow_id": "analysis_histogram",
    "command_type": "analysis",
    "command_label": "probe:state-db-locate",
    "inputs": {},
    "nodes": [
        {
            "node_id": "n1",
            "node_type": "module",
            "label": "数据源",
            "params": {
                "path": "I:/Geograph_DataSet/_runtime/smoke_hist.tif",
                "dataset_key": "input_path",
                "module_name": "data_source",
            },
        },
        {
            "node_id": "n2",
            "node_type": "module",
            "label": "直方图统计",
            "params": {"bins": 10, "band": 0, "module_name": "stats_histogram"},
        },
    ],
    "edges": [{"from_node": "n1", "from_port": "manifest", "to_node": "n2", "to_port": "manifest"}],
    "client": {"client_id": "probe_state_db", "page": "tools"},
}
status, accepted = http("POST", "/workflow-runs", payload, cookie=cookie)
run_id = accepted.get("run_id")
print("submitted:", status, "run_id:", run_id)

for i in range(30):
    time.sleep(2)
    _, doc = http("GET", f"/workflow-runs/{run_id}", cookie=cookie)
    st = doc.get("status")
    print(f"  poll {i}: {st}")
    if st in {"succeeded", "failed", "cancelled"}:
        break

conn = sqlite3.connect(DB)
row = conn.execute(
    "SELECT status, updated_at FROM workflow_runs WHERE run_id=?", (run_id,)
).fetchone()
print("I-drive DB direct query:", row)
total = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
print("I-drive DB total now:", total)
conn.close()
