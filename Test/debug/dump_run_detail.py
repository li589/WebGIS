import json
import sys
import urllib.request

BACKEND = "http://127.0.0.1:8000"
COOKIE: dict[str, str] = {}


def _req(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BACKEND + path, method=method, data=data)
    req.add_header("Content-Type", "application/json")
    for k, v in COOKIE.items():
        req.add_header("Cookie", f"{k}={v}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read()), r.headers
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read()), e.headers
        except Exception:
            return e.code, {"raw": str(e)}, e.headers


def main() -> None:
    rid = sys.argv[1]
    _req("POST", "/auth/login", {"username": "admin", "password": "cgda-dev-admin"})
    code, body, headers = _req("POST", "/auth/login", {"username": "admin", "password": "cgda-dev-admin"})
    set_cookie = headers.get("Set-Cookie", "")
    for part in set_cookie.split(";"):
        if "=" in part and ("session" in part.lower() or "token" in part.lower()):
            k, v = part.split("=", 1)
            COOKIE[k.strip()] = v.strip()

    code, body, _ = _req("GET", f"/workflow-runs/{rid}")
    print("== run ==")
    print(json.dumps(body, ensure_ascii=False, indent=1)[:2000])

    code, ev, _ = _req("GET", f"/workflow-runs/{rid}/events")
    print("== events ==")
    events = ev.get("events", []) if isinstance(ev, dict) else []
    print(json.dumps(events[-15:], ensure_ascii=False, indent=1)[:3000])


if __name__ == "__main__":
    main()
