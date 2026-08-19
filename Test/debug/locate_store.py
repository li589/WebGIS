import json
import sqlite3
import urllib.request

BASE = "http://127.0.0.1:8000"


def http(method: str, path: str, body=None, cookie=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data, timeout=20) as resp:
        return resp.status, resp.read().decode(), resp.headers


_, _, headers = http("POST", "/auth/login", {"username": "admin", "password": "cgda-dev-admin"})
cookie = headers.get("Set-Cookie", "").split(";")[0]

_, body, _ = http("GET", "/workflow-definitions?limit=200", cookie=cookie)
defs = json.loads(body)
items = defs if isinstance(defs, list) else defs.get("items", [])
target = None
for d in items:
    if d.get("workflow_id") == "analysis_histogram":
        target = d
        break
print("found definition:", bool(target), target.get("name") if target else "")

payload = {
    "command_type": "analysis",
    "command_label": "probe:store-locate",
    "workflow_id": "analysis_histogram",
    "algorithm_request": {
        "workflow_entry_name": "analysis_histogram",
        "datasource_selection": {
            "input_path": "I:/Geograph_DataSet/_runtime/smoke_hist.tif"
        },
        "algorithm_params": {"bins": 8},
    },
}
try:
    st, body, _ = http("POST", "/workflow-runs", payload, cookie=cookie)
    print("submit:", st, body[:200])
    rid = json.loads(body).get("run_id")
except urllib.error.HTTPError as e:
    print("submit ERR", e.code, e.read().decode()[:300])
    rid = None

if rid:
    conn = sqlite3.connect(r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3")
    row = conn.execute(
        "SELECT status FROM workflow_runs WHERE run_id=?", (rid,)
    ).fetchone()
    print("I: db has new run:", bool(row), row)
