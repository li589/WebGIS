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


_, _, headers = http("POST", "/auth/login", {"username": "admin", "password": "cgda-dev-admin"})
cookie = headers.get("Set-Cookie", "").split(";")[0]

for path in ("/config/deployment",):
    try:
        st, body, _ = http("GET", path, cookie=cookie)
        doc = json.loads(body)
        for k in doc.get("keys", []):
            if k.get("key") in ("runtime_root", "data_root", "output_root"):
                print(k.get("key"), "| runtime:", k.get("runtime_value"), "| env:", k.get("env_value"), "| source:", k.get("source"))
    except Exception as e:
        print("==", path, "ERR", e)
