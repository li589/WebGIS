import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"


def login():
    body = json.dumps({"username": "admin", "password": "cgda-dev-admin"}).encode()
    req = urllib.request.Request(
        f"{BASE}/auth/login", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return resp.headers.get_all("Set-Cookie") or []


def get(path, cookies):
    cookie = "; ".join(c.split(";")[0] for c in cookies)
    req = urllib.request.Request(f"{BASE}{path}", headers={"Cookie": cookie})
    try:
        return json.load(urllib.request.urlopen(req, timeout=15))
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode(errors="replace")[:2000]}


run_id = sys.argv[1] if len(sys.argv) > 1 else "run-f28826f3c652"
cookies = login()
d = get(f"/workflow-runs/{run_id}", cookies)
out = json.dumps(d, ensure_ascii=False, indent=2)
print(out[:6000])
