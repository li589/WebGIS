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

conn = sqlite3.connect(r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3")
for rid in ("run-c7d6aa7153d2", "run-ba1d5ac94d10", "run-cb99870d887c"):
    st, body, _ = http("GET", f"/workflow-runs/{rid}", cookie=cookie)
    api_st = json.loads(body).get("status") if st == 200 else f"HTTP{st}"
    row = conn.execute(
        "SELECT status, updated_at FROM workflow_runs WHERE run_id=?", (rid,)
    ).fetchone()
    db_st = (row[0], row[1]) if row else ("<absent>",)
    print(f"{rid}: api={api_st} | db={db_st}")

st, body, _ = http("GET", "/health", cookie=cookie)
print("health:", st, body[:100])
