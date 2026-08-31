"""X2 变体路由 API 级验证。

用法:
  python verify_variant_routing.py submit     # layer_id-only 提交风云动态ω（应路由 online 种子）
  python verify_variant_routing.py poll <run_id> [--cancel]
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

BACKEND = "http://127.0.0.1:8000"
HERE = Path(__file__).resolve().parent
COOKIE: dict[str, str] = {}


def _req(method: str, path: str, payload: dict | None = None, timeout: float = 60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BACKEND + path, method=method, data=data)
    req.add_header("Content-Type", "application/json")
    for k, v in COOKIE.items():
        req.add_header("Cookie", f"{k}={v}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read()), r.headers
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read()), e.headers
        except Exception:
            return e.code, {"raw": str(e)}, e.headers


def login() -> bool:
    code, body, headers = _req(
        "POST",
        "/auth/login",
        {"username": "admin", "password": "cgda-dev-admin"},
    )
    if code != 200:
        print("login failed:", code, str(body)[:200])
        return False
    set_cookie = headers.get("Set-Cookie", "")
    for part in set_cookie.split(";"):
        if "=" in part and ("session" in part.lower() or "token" in part.lower()):
            k, v = part.split("=", 1)
            COOKIE[k.strip()] = v.strip()
    print("login ok, cookies:", list(COOKIE))
    return True


def submit() -> None:
    payload = json.loads((HERE / "payload_fy_omega_online.json").read_text("utf-8"))
    code, body, _ = _req("POST", "/workflow-runs", payload)
    print("submit:", code, json.dumps(body, ensure_ascii=False)[:300])
    if code in (200, 201, 202) and isinstance(body, dict):
        rid = body.get("run_id") or body.get("id")
        if rid:
            print("RUN_ID=" + rid)


def poll(rid: str, cancel: bool = False) -> None:
    code, body, _ = _req("GET", f"/workflow-runs/{rid}")
    if code != 200:
        print("run query failed:", code, str(body)[:200])
        return
    print("status:", body.get("status"), "| progress:", body.get("progress"))
    code2, ev, _ = _req("GET", f"/workflow-runs/{rid}/events")
    node_types: list[str] = []
    if code2 == 200 and isinstance(ev, dict):
        for e in ev.get("events", []) or []:
            t = str(e.get("message") or e.get("event") or "")
            for kw in ("fy_download", "fy_daily", "omega_sf_fenkuai", "chunk"):
                if kw in t and kw not in node_types:
                    node_types.append(kw)
    print("event keywords:", node_types)
    if cancel:
        code3, body3, _ = _req("POST", f"/workflow-runs/{rid}/cancel", {})
        print("cancel:", code3, str(body3)[:150])


if __name__ == "__main__":
    if not login():
        sys.exit(1)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "submit":
        submit()
    elif cmd == "poll":
        poll(sys.argv[2], "--cancel" in sys.argv)
    else:
        print(__doc__)
