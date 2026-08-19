import json
import sqlite3
import urllib.request

BASE = "http://127.0.0.1:8000"
RID = "run-c7d6aa7153d2"


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

_, body, _ = http("GET", f"/workflow-runs/{RID}/events?limit=50", cookie=cookie)
doc = json.loads(body)
print("API events count:", len(doc.get("items", [])))
for it in doc.get("items", []):
    print("  API:", it.get("created_at"), "|", str(it.get("message"))[:70])

conn = sqlite3.connect(r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3")
rows = conn.execute(
    "SELECT payload_json FROM workflow_events WHERE run_id=?", (RID,)
).fetchall()
print("DB events count:", len(rows))
for (pj,) in rows:
    ep = json.loads(pj)
    print("  DB :", ep.get("created_at"), "|", str(ep.get("message"))[:70])
