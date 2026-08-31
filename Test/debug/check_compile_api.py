import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8000"


def login():
    body = json.dumps({"username": "admin", "password": "cgda-dev-admin"}).encode()
    req = urllib.request.Request(
        f"{BASE}/auth/login", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=60)
    return resp.headers.get_all("Set-Cookie") or []


def post(path, body, cookies):
    cookie = "; ".join(c.split(";")[0] for c in cookies)
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Cookie": cookie},
    )
    return json.load(urllib.request.urlopen(req, timeout=60))


seed_path = REPO / "Code" / "backend" / "workflow_seeds" / "system" / "analysis_vector_to_raster.json"
seed = json.loads(seed_path.read_text(encoding="utf-8"))
print("seed path prop:", seed["nodes"][0]["properties"]["path"])

cookies = login()
resp = post(
    "/workflow-definitions/compile",
    {
        "workflow_id": seed["workflow_id"],
        "name": seed["name"],
        "description": seed["description"],
        "nodes": seed["nodes"],
        "links": seed["links"],
    },
    cookies,
)
wf = resp.get("workflow_definition") or resp.get("definition") or resp
nodes = wf.get("nodes") or []
print("compiled nodes:")
for n in nodes:
    params = n.get("params") or {}
    print("  -", n.get("node_type"), {k: v for k, v in params.items() if k in ("path", "dataset_key", "module_name")})
