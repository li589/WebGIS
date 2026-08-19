"""API 级复刻：与 smoke 完全一致的 analysis_vector_to_raster 提交。

复刻 Tools/smoke_system_workflows.py 的 prepare_overrides(无专属补丁) +
compile_litegraph + build_payload(python_provider 分支)，dump payload 后提交。
"""

import json
import sys
import time
import urllib.error
import urllib.request
import http.cookiejar
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "Tools"))

BASE = "http://127.0.0.1:8000"
WF = "analysis_vector_to_raster"

jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def http(method: str, path: str, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    try:
        with op.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def main() -> None:
    http("POST", "/auth/login", {"username": "admin", "password": "cgda-dev-admin"})

    code, definition = http("GET", f"/workflow-definitions/{WF}")
    print("GET def:", code)
    meta = definition.get("_meta") or {}
    engine = str(meta.get("engine") or "common")
    extra = definition.get("extra") or {}
    assert engine == "python_provider", engine

    # compile（与 smoke compile_litegraph 相同）
    code, cbody = http(
        "POST",
        "/workflow-definitions/compile",
        body={
            "workflow_id": definition.get("workflow_id"),
            "name": definition.get("name"),
            "description": definition.get("description"),
            "nodes": definition.get("nodes") or [],
            "links": definition.get("links") or [],
        },
    )
    compiled = (
        cbody.get("workflow_definition") or cbody.get("definition") or cbody
    ) if code == 200 else None
    print("compile:", code, "ok:", compiled is not None)
    # dump 编译图中 data_source 节点 path（关键证据）
    for n in (compiled or {}).get("nodes") or []:
        p = (n.get("params") or {}).get("path")
        if p:
            print("  compiled node path:", n.get("node_id"), repr(p))

    # build_payload python_provider 分支（无 overrides）
    parameters = dict(extra.get("default_parameters") or {})
    algo_params = dict(parameters)
    for node in definition.get("nodes") or []:
        ntype = str(node.get("type") or "")
        props = node.get("properties") or {}
        if ntype.startswith("module/"):
            nested = props.get("algorithm_params")
            if isinstance(nested, dict):
                for k, v in nested.items():
                    algo_params.setdefault(k, v)
        if ntype.startswith(("preprocess/", "gis/", "stats/", "fusion/", "viz/")):
            for k, v in props.items():
                if k not in ("notes", "path", "dataset_key"):
                    algo_params.setdefault(k, v)

    ds = None
    for node in definition.get("nodes") or []:
        if str(node.get("type") or "") != "data/source":
            continue
        props = node.get("properties") or {}
        path = props.get("path") or props.get("uri")
        if not path:
            continue
        path_s = str(path).replace("{DATA_ROOT}", r"I:\Geograph_DataSet").replace("\\", "/")
        key = props.get("dataset_key") or props.get("key")
        ds = ds or {}
        if key:
            ds[str(key)] = path_s
        ds.setdefault("input_path", path_s)
    print("extracted ds:", json.dumps(ds, ensure_ascii=False))

    tr = definition.get("_time_range_hint") or {
        "start_at": "2025-01-01T00:00:00Z",
        "end_at": "2025-01-02T00:00:00Z",
        "granularity": "day",
    }
    payload = {
        "command_type": str(extra.get("default_command") or "analysis"),
        "command_label": f"api-repro:{WF}",
        "parameters": parameters,
        "requested_outputs": ["json"],
        "client": {"client_id": "repro_v2r_api", "page": "tools"},
        "algorithm_request": {
            "algorithm_params": algo_params,
            "datasource_selection": ds or {},
            "workflow_definition": compiled,
        },
        "time_range": tr,
    }
    out = Path(REPO / "Test" / "debug" / "v2r_api_payload.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("payload dumped:", out.name, "ds in payload:", json.dumps(payload["algorithm_request"]["datasource_selection"]))

    code, accepted = http("POST", "/workflow-runs", body=payload)
    print("submit:", code, accepted.get("run_id") if isinstance(accepted, dict) else accepted)
    if code not in (200, 201, 202):
        print(json.dumps(accepted, ensure_ascii=False)[:500])
        return
    run_id = accepted["run_id"]
    for _ in range(40):
        time.sleep(2)
        c, st = http("GET", f"/workflow-runs/{run_id}")
        s = st.get("status")
        if s in ("succeeded", "failed", "cancelled"):
            print("FINAL:", s)
            if s == "failed":
                print(json.dumps(st.get("message") or st, ensure_ascii=False)[:400])
            return
        print("  polling:", s)


if __name__ == "__main__":
    main()
