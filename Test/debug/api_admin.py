"""带服务密钥的后端 API 调试客户端。

用法:
  python api_admin.py layers                 # 列出 omega 图层变体配置
  python api_admin.py cancel <run_id>        # 取消工作流
  python api_admin.py run <run_id>           # 查看 run 状态
  python api_admin.py submit <json_file>     # 提交工作流
  python api_admin.py submit-omega-fy        # 提交风云动态ω在线反演
"""
import json
import sys
import urllib.request
from pathlib import Path

BACKEND = "http://127.0.0.1:8000"
ENV_PATH = Path(__file__).resolve().parents[2] / "Code" / "backend" / ".env"


def service_key() -> str:
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("BACKEND_API_KEY=") and not line.startswith("BACKEND_API_KEY_ROLE"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def call(method: str, path: str, payload: dict | None = None) -> object:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BACKEND + path,
        method=method,
        data=data,
        headers={"Content-Type": "application/json", "X-API-Key": service_key()},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode()[:400])
        return None
    except Exception as e:
        print("ERR", e)
        return None


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "layers":
        data = call("GET", "/layers")
        if data is None:
            return
        layers = data if isinstance(data, list) else data.get("layers", [])
        for l in layers:
            if "omega" in str(l.get("layer_id", "")):
                print(
                    l.get("layer_id"),
                    "| wf:", l.get("workflow_id"),
                    "| variants:", json.dumps(l.get("workflow_variants"), ensure_ascii=False),
                )
    elif cmd == "cancel":
        rid = sys.argv[2]
        body = call("POST", f"/workflow-runs/{rid}/cancel", {})
        if body:
            print("cancel:", body.get("status"), "|", body.get("message"))
    elif cmd == "run":
        rid = sys.argv[2]
        body = call("GET", f"/workflow-runs/{rid}")
        if body:
            print("status:", body.get("status"), "| progress:", body.get("progress"))
            print("message:", str(body.get("message"))[:200])
    elif cmd == "submit":
        payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        body = call("POST", "/workflow-runs", payload)
        if body:
            print(json.dumps(body, ensure_ascii=False)[:400])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
