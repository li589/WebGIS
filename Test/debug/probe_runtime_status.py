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
cookie = headers.get("Set-Cookie", "").split(";")[0]

for path in ("/runtime/status", "/health", "/config/about"):
    try:
        status, body, _ = http("GET", path, cookie=cookie)
        print("==", path, status)
        doc = json.loads(body)
        text = json.dumps(doc)
        for needle in ("workflow_state", "data_root", "state_dir", "runtime_root"):
            idx = 0
            while True:
                idx = text.find(needle, idx)
                if idx < 0:
                    break
                print("   ", text[max(0, idx - 60) : idx + 80])
                idx += len(needle)
    except Exception as e:
        print("==", path, "ERR", e)
