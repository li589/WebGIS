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
    with urllib.request.urlopen(req, data, timeout=15) as resp:
        return resp.status, resp.read().decode(), resp.headers


_, _, headers = http("POST", "/auth/login", {"username": "admin", "password": "cgda-dev-admin"})
cookie = headers.get("Set-Cookie", "").split(";")[0]

RID = "run-19e73c905550"
st, body, _ = http("GET", f"/workflow-runs/{RID}", cookie=cookie)
print("api:", st, json.loads(body).get("status") if st == 200 else body[:120])

conn = sqlite3.connect(r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3")
row = conn.execute("SELECT status, updated_at FROM workflow_runs WHERE run_id=?", (RID,)).fetchone()
print("I: db:", row)

st, body, _ = http("GET", "/workflow-runs?limit=8", cookie=cookie)
doc = json.loads(body)
items = doc if isinstance(doc, list) else doc.get("items", [])
print("api list (top):")
for it in items[:8]:
    print("  ", it.get("run_id"), it.get("status"), str(it.get("command_label"))[:36])
