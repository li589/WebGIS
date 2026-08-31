import json
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


status, body, headers = http("POST", "/auth/login", {"username": "admin", "password": "cgda-dev-admin"})
print("login:", status)
cookie = headers.get("Set-Cookie", "").split(";")[0]

status, body, _ = http("GET", "/workflow-runs/run-c7d6aa7153d2", cookie=cookie)
print("run status:", status, "| api status:", json.loads(body).get("status"))

status, body, _ = http("GET", "/workflow-runs/run-c7d6aa7153d2/events?limit=5", cookie=cookie)
print("events:", status)
if status == 200:
    doc = json.loads(body)
    for item in doc.get("items", [])[-5:]:
        print("  ev:", item.get("created_at"), str(item.get("message"))[:80])

status, body, _ = http("GET", "/workflow-runs?limit=5", cookie=cookie)
print("list:", status)
if status == 200:
    doc = json.loads(body)
    items = doc if isinstance(doc, list) else doc.get("items", [])
    for it in items[:5]:
        print("  ls:", it.get("run_id"), it.get("status"), str(it.get("command_label"))[:40])
