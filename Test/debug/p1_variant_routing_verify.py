"""P1 X2 变体路由 API 级验证（在线默认 + 本地切换 + resource_profile 核查）。

断言（对应用户需求「默认在线反演，可在分析框切换本地反演」）：
  A1 layer_id-only 提交 → request_json.algorithm_request.workflow_name == omega_sf_fenkuai_fy_online
  A2 同上 → module_name is None（不走裸模块路径）
  A3 事件流进入种子图（Execute workflow omega_sf_fenkuai_fy_online + fy_download 节点）
  A4 占位符已展开（request_json / 事件无 {YYYYMMDD} 字面量，含具体日期）
  A5 resource_profile 有效值（记录实测；期望 heavy —— layer_id-only 提交时
     apply_resource_profile_to_payload 目前无 workflow_name 线索，可能为 standard）
  B1 提交 algorithm_request.workflow_entry_name=omega_sf_fenkuai_fy_single →
     request_json.algorithm_request.workflow_name == omega_sf_fenkuai_fy_single

用法（仓库根执行）:
  Env/Python312/python.exe Test/debug/p1_variant_routing_verify.py
"""
import json
import sqlite3
import sys
import time
import urllib.request

BACKEND = "http://127.0.0.1:8000"
STATE_DB = r"I:\Geograph_DataSet\_runtime\workflow_state\workflow_state.sqlite3"
COOKIE: dict[str, str] = {}

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, cond, detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  -> {detail}" if detail else ""))


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
        "POST", "/auth/login", {"username": "admin", "password": "cgda-dev-admin"}
    )
    if code != 200:
        print("login failed:", code, str(body)[:200])
        return False
    for part in headers.get("Set-Cookie", "").split(";"):
        if "=" in part and ("session" in part.lower() or "token" in part.lower()):
            k, v = part.split("=", 1)
            COOKIE[k.strip()] = v.strip()
    return True


def submit(payload: dict) -> str | None:
    code, body, _ = _req("POST", "/workflow-runs", payload)
    if code not in (200, 201, 202) or not isinstance(body, dict):
        print("submit failed:", code, str(body)[:300])
        return None
    rid = body.get("run_id") or body.get("id")
    print("submitted:", rid, "| status:", body.get("status"))
    return rid


def api_status(rid: str) -> dict:
    code, body, _ = _req("GET", f"/workflow-runs/{rid}")
    return body if code == 200 and isinstance(body, dict) else {}


def wait_terminal(rid: str, timeout: float = 150.0) -> str:
    deadline = time.time() + timeout
    last = "?"
    while time.time() < deadline:
        st = api_status(rid)
        last = str(st.get("status"))
        if last in ("succeeded", "failed", "cancelled"):
            return last
        time.sleep(3)
    return last


def db_row(rid: str) -> dict | None:
    conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT request_json, status FROM workflow_runs WHERE run_id=?", (rid,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def db_events(rid: str) -> list[str]:
    conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT payload_json FROM workflow_events WHERE run_id=? ORDER BY created_at",
            (rid,),
        ).fetchall()
        return [str(r[0]) for r in rows]
    finally:
        conn.close()


BASE_PAYLOAD = {
    "command_type": "analysis",
    "command_label": "P1 变体路由验证 · 在线默认",
    "layer_id": "method-fy-omega-doy-dynamic",
    "priority": "normal",
    "resource_profile": "standard",
    "realtime_preferred": False,
    "requested_outputs": ["json", "text", "table", "map_layer"],
    "parameters": {"hour": 0, "latitude": 35.0, "longitude": 105.0},
    "client": {"page": "dashboard", "view_id": "map-2d"},
    "map_context": {"active_layer_id": "method-fy-omega-doy-dynamic", "map_mode": "2d"},
}

LOCAL_PAYLOAD = {
    **BASE_PAYLOAD,
    "command_label": "P1 变体路由验证 · 本地切换",
    "algorithm_request": {"workflow_entry_name": "omega_sf_fenkuai_fy_single"},
}


def verify_online() -> None:
    print("\n=== A. layer_id-only（默认 online）===")
    rid = submit(BASE_PAYLOAD)
    if not rid:
        check("A0 提交成功", False)
        return
    terminal = wait_terminal(rid)
    print("terminal status:", terminal)
    row = db_row(rid)
    if row is None:
        check("A0 run 落库", False)
        return
    req = json.loads(row["request_json"])
    ar = req.get("algorithm_request") or {}
    check(
        "A1 workflow_name==omega_sf_fenkuai_fy_online",
        ar.get("workflow_name") == "omega_sf_fenkuai_fy_online",
        f"实际 {ar.get('workflow_name')}",
    )
    check("A2 module_name is None", ar.get("module_name") is None, f"实际 {ar.get('module_name')}")
    events = db_events(rid)
    joined = "\n".join(events)
    check(
        "A3 事件进入种子图（Execute workflow + fy_download）",
        "omega_sf_fenkuai_fy_online" in joined and "fy_download" in joined,
    )
    check(
        "A4 占位符展开（无 {YYYYMMDD} 字面量）",
        "{YYYYMMDD}" not in row["request_json"] and "{YYYYMMDD}" not in joined,
        "URL 含具体日期" if "2025" in joined or "2026" in joined else "",
    )
    check(
        "A5 resource_profile（期望 heavy）",
        req.get("resource_profile") == "heavy",
        f"实际 {req.get('resource_profile')}（提交请求 standard）",
    )
    # 失败原因分类（预期 nsmc/nas 环境性失败，非路由问题）
    diag = api_status(rid).get("diagnostics") or []
    print("diagnostics 尾部:", str(diag[-1])[:160] if diag else "(空)")


def verify_local() -> None:
    print("\n=== B. workflow_entry_name=本地变体 ===")
    rid = submit(LOCAL_PAYLOAD)
    if not rid:
        check("B0 提交成功", False)
        return
    time.sleep(6)  # 受理后 request_json 即落库，无需等执行
    row = db_row(rid)
    if row is None:
        check("B0 run 落库", False)
        return
    req = json.loads(row["request_json"])
    ar = req.get("algorithm_request") or {}
    check(
        "B1 workflow_name==omega_sf_fenkuai_fy_single",
        ar.get("workflow_name") == "omega_sf_fenkuai_fy_single",
        f"实际 {ar.get('workflow_name')}",
    )
    check(
        "B2 module_name is None",
        ar.get("module_name") is None,
        f"实际 {ar.get('module_name')}",
    )
    st = api_status(rid).get("status")
    print("run status before cancel:", st)
    code, body, _ = _req("POST", f"/workflow-runs/{rid}/cancel", {})
    print("cancel:", code, str(body)[:120])


def main() -> int:
    if not login():
        return 1
    verify_online()
    verify_local()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n==== P1 断言汇总: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed ====")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL {name} {detail}")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
