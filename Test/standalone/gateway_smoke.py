#!/usr/bin/env python3
"""CGDA Nginx Gateway 冒烟巡检（独立脚本，仅标准库）。

为什么独立于 pytest：本脚本需要**网关正在运行**（打真实 HTTP），
若命名 test_*.py 会被 pytest 误收集并在无网关环境下判失败，故不挂 test_ 前缀。

用途
----
- 交接/换机后确认网关与反馈页可用；
- 改动 ``Code/infra/gateway/{nginx.conf,nginx.prod.conf,nginx.hmr.conf,maintenance/}``
  后的回归自检；
- 交付态起栈后用 ``--base http://<host>:5175`` 复检同一套契约。

覆盖的契约（任何一条 FAIL 即退出码 1）
------------------------------------
1. 反馈页与 SPA **正确隔离**：``/feedback/`` 是独立静态站，不引用 SPA 的 ``/assets/index-*``。
2. 缺失的 hashed 资源返回**真 404**，而不是 SPA 回退成 index.html
   （回退会让浏览器把 HTML 当 JS → "Failed to fetch dynamically imported module"）。
3. SPA 深链接回退 200；入口 HTML 带 ``no-store``。
4. 反代 ``/health`` 通（FastAPI 可达）。
5. 反馈页安全头：CSP **比基线更严**（无 ``unsafe-inline`` / ``unsafe-eval``）。
6. 反馈 API 鉴权分层：admin 端点期望 401/403；匿名 ``POST /reports`` 期望 4xx 校验类
   （**不是** 401/403，否则匿名用户无法提交）。

用法
----
    Env/Python312/python.exe Test/standalone/gateway_smoke.py
    Env/Python312/python.exe Test/standalone/gateway_smoke.py --base http://192.168.1.10:5175
    Env/Python312/python.exe Test/standalone/gateway_smoke.py --no-post-probe   # 跳过写探测
    Env/Python312/python.exe Test/standalone/gateway_smoke.py --json           # 机器可读

注意：``--no-post-probe`` 之外的默认行为会发一次**故意非法**的 POST（缺 multipart
字段），后端返回 422 且**不落库**；这不是写操作，但若目标环境对匿名请求有额外 WAF
规则，可用该开关跳过。

退出码：0=全通过；1=有断言失败；2=网关不可达（未启动 / 端口不通）。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:5175"
UA = "cgda-gateway-smoke/1.0"

# 反馈页判别标记（来自 maintenance/html/feedback/index.html 的 <title>）
FB_TITLE = "问题反馈中心".encode("utf-8")
FB_CONSOLE_TITLE = "反馈处理台".encode("utf-8")
SPA_MARKER = b'<div id="app"'
SPA_ASSET_REF = b"/assets/index-"

# path, want_status, ctype_prefix(None=不校验), csp(bool|None), xcto(bool|None),
# no_store(bool), marker(must-contain bytes|None), absent(must-not-contain bytes|None), label
CHECKS: list[dict] = [
    {
        "path": "/",
        "want": 200,
        "ctype": "text/html",
        "csp": True,
        "xcto": True,
        "no_store": True,
        "marker": SPA_MARKER,
        "label": "SPA 入口",
    },
    {
        "path": "/index.html",
        "want": 200,
        "ctype": "text/html",
        "csp": True,
        "xcto": True,
        "no_store": True,
        "label": "入口 HTML",
    },
    {
        "path": "/feedback/",
        "want": 200,
        "ctype": "text/html",
        "csp": True,
        "xcto": True,
        "no_store": True,
        "marker": FB_TITLE,
        "absent": SPA_ASSET_REF,
        "label": "反馈页(目录 index)",
    },
    {
        "path": "/feedback/index.html",
        "want": 200,
        "ctype": "text/html",
        "csp": True,
        "xcto": True,
        "no_store": True,
        "marker": FB_TITLE,
        "label": "反馈页(直连)",
    },
    {
        "path": "/feedback/console.html",
        "want": 200,
        "ctype": "text/html",
        "csp": True,
        "xcto": True,
        "no_store": True,
        "marker": FB_CONSOLE_TITLE,
        "label": "工程师处理台",
    },
    {
        "path": "/feedback/assets/feedback.js",
        "want": 200,
        "ctype": "application/javascript",
        "csp": True,
        "xcto": True,
        "no_store": True,
        "label": "反馈页 JS",
    },
    {
        "path": "/feedback/assets/feedback.css",
        "want": 200,
        "ctype": "text/css",
        "csp": True,
        "xcto": True,
        "no_store": True,
        "label": "反馈页 CSS",
    },
    {
        "path": "/feedback/assets/console.js",
        "want": 200,
        "ctype": "application/javascript",
        "csp": True,
        "xcto": True,
        "no_store": True,
        "label": "处理台 JS",
    },
    {
        "path": "/feedback/data/announcements.json",
        "want": 200,
        "ctype": "application/json",
        "csp": True,
        "xcto": True,
        "no_store": True,
        "label": "公告数据",
    },
    {
        "path": "/maintenance.html",
        "want": 200,
        "ctype": "text/html",
        "csp": True,
        "xcto": True,
        "no_store": True,
        "label": "维护页",
    },
    {
        "path": "/health",
        "want": 200,
        "ctype": "application/json",
        "csp": None,
        "xcto": None,
        "no_store": False,
        "label": "反代 -> FastAPI",
    },
    {
        "path": "/assets/_missing_probe_.js",
        "want": 404,
        "ctype": None,
        "csp": None,
        "xcto": None,
        "no_store": False,
        "label": "缺失 hashed 资源须真 404",
    },
    {
        "path": "/_spa_deep_link_probe_",
        "want": 200,
        "ctype": "text/html",
        "csp": True,
        "xcto": True,
        "no_store": True,
        "marker": SPA_MARKER,
        "label": "SPA 深链接回退",
    },
    {
        "path": "/feedback/api/session",
        "want": (401, 403),
        "ctype": "application/json",
        "csp": None,
        "xcto": None,
        "no_store": False,
        "label": "反馈 admin 端点须鉴权",
    },
    {
        "path": "/feedback/api/reports",
        "want": (401, 403),
        "ctype": "application/json",
        "csp": None,
        "xcto": None,
        "no_store": False,
        "label": "反馈列表须鉴权",
    },
]


def request(
    base: str,
    path: str,
    timeout: float,
    method: str = "GET",
    body: bytes | None = None,
    ctype: str | None = None,
):
    """返回 (status|None, headers(lower), body)。网络层失败时 status=None。"""
    req = urllib.request.Request(
        base.rstrip("/") + path,
        method=method,
        data=body,
        headers={"User-Agent": UA, **({"Content-Type": ctype} if ctype else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(65536)
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read(65536)
    except Exception as e:  # noqa: BLE001 — 网络层任何异常都视为不可达
        return None, {"_err": repr(e)}, b""


def check_one(base: str, spec: dict, timeout: float) -> tuple[bool, str, dict]:
    st, h, body = request(base, spec["path"], timeout)
    problems: list[str] = []
    if st is None:
        return False, f"不可达: {h.get('_err')}", {"status": None}

    want = spec["want"]
    if isinstance(want, tuple):
        if st not in want:
            problems.append(f"status={st} 期望 {want}")
    elif st != want:
        problems.append(f"status={st} 期望 {want}")

    if spec.get("ctype") and not h.get("content-type", "").startswith(spec["ctype"]):
        problems.append(f"content-type={h.get('content-type')!r} 期望 {spec['ctype']}*")

    if spec.get("csp") and "content-security-policy" not in h:
        problems.append("缺 CSP")
    if spec.get("xcto") and "x-content-type-options" not in h:
        problems.append("缺 X-Content-Type-Options")
    if spec.get("no_store") and "no-store" not in h.get("cache-control", ""):
        problems.append("缺 Cache-Control: no-store")

    if spec.get("marker") and spec["marker"] not in body:
        problems.append(f"正文缺标记 {spec['marker']!r}")
    if spec.get("absent") and spec["absent"] in body:
        problems.append(f"正文不应含 {spec['absent']!r}（疑似串到 SPA）")

    flags = "".join(
        [
            "csp " if "content-security-policy" in h else "",
            "xcto " if "x-content-type-options" in h else "",
            "no-store" if "no-store" in h.get("cache-control", "") else "",
        ]
    ).strip()
    return (
        not problems,
        "; ".join(problems),
        {
            "status": st,
            "ctype": h.get("content-type", ""),
            "flags": flags,
            "len": len(body),
        },
    )


def check_csp_hardened(base: str, timeout: float) -> tuple[bool, str, dict]:
    """反馈页 CSP 必须比基线更严：不得含 unsafe-inline / unsafe-eval。"""
    st, h, _ = request(base, "/feedback/", timeout)
    if st != 200:
        return False, f"/feedback/ status={st}", {"status": st}
    csp = h.get("content-security-policy", "")
    bad = [tok for tok in ("unsafe-inline", "unsafe-eval") if tok in csp]
    if bad:
        return False, f"反馈页 CSP 含 {bad}（应比基线更严）", {"status": st}
    if "script-src 'self'" not in csp:
        return False, "反馈页 CSP 缺 script-src 'self'", {"status": st}
    return True, "", {"status": st, "flags": "csp(hardened)"}


def check_anonymous_post(base: str, timeout: float) -> tuple[bool, str, dict]:
    """匿名提交路径：POST 缺 file 字段应 422（证明代理通+路由挂载+无鉴权墙+未落库）。

    绝不接受 401/403（那会挡住匿名反馈），也不接受 404（路由未挂载）。
    """
    st, h, body = request(
        base,
        "/feedback/api/reports",
        timeout,
        method="POST",
        body=b"{}",
        ctype="application/json",
    )
    if st is None:
        return False, f"不可达: {h.get('_err')}", {"status": None}
    if st in (401, 403):
        return False, f"status={st} 匿名提交被鉴权挡住（应可匿名）", {"status": st}
    if st == 404:
        return False, "status=404 路由未挂载", {"status": st}
    if not (400 <= st < 500):
        return False, f"status={st} 期望 4xx 校验类", {"status": st}
    rid = ""
    try:
        rid = json.loads(body).get("request_id", "")
    except Exception:  # noqa: BLE001
        pass
    return True, "", {"status": st, "flags": f"request_id={rid[:12]}…" if rid else ""}


def main() -> int:
    ap = argparse.ArgumentParser(description="CGDA Nginx Gateway 冒烟巡检")
    ap.add_argument(
        "--base", default=DEFAULT_BASE, help=f"网关基址（默认 {DEFAULT_BASE}）"
    )
    ap.add_argument("--timeout", type=float, default=8.0, help="单请求超时秒（默认 8）")
    ap.add_argument(
        "--no-post-probe",
        action="store_true",
        help="跳过匿名 POST 探测（默认执行；该探测发非法体、不落库）",
    )
    ap.add_argument("--json", action="store_true", help="输出 JSON 结果")
    args = ap.parse_args()

    base = args.base.rstrip("/")

    # 预检可达性：区分「网关没起」与「断言失败」
    st, h, _ = request(base, "/", args.timeout)
    if st is None:
        print(f"[FATAL] 网关不可达 {base} -> {h.get('_err')}", file=sys.stderr)
        print(
            "        请先启动：launch.py start gateway（或 start --mode prod）",
            file=sys.stderr,
        )
        return 2

    rows: list[dict] = []
    results: list[tuple[bool, str, str, str]] = []

    for spec in CHECKS:
        ok, why, info = check_one(base, spec, args.timeout)
        results.append((ok, spec["path"], spec["label"], why))
        rows.append(
            {"path": spec["path"], "label": spec["label"], "ok": ok, "why": why, **info}
        )

    ok, why, info = check_csp_hardened(base, args.timeout)
    results.append((ok, "/feedback/ [CSP 更严]", "反馈页 CSP 硬化", why))
    rows.append(
        {
            "path": "/feedback/ [CSP 更严]",
            "label": "反馈页 CSP 硬化",
            "ok": ok,
            "why": why,
            **info,
        }
    )

    if not args.no_post_probe:
        ok, why, info = check_anonymous_post(base, args.timeout)
        results.append((ok, "POST /feedback/api/reports", "匿名提交链路", why))
        rows.append(
            {
                "path": "POST /feedback/api/reports",
                "label": "匿名提交链路",
                "ok": ok,
                "why": why,
                **info,
            }
        )

    failed = [r for r in results if not r[0]]

    if args.json:
        print(
            json.dumps(
                {
                    "base": base,
                    "passed": len(results) - len(failed),
                    "failed": len(failed),
                    "results": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if failed else 0

    print(f"CGDA gateway smoke check   base={base}")
    print("-" * 98)
    for ok, path, label, why in results:
        tag = "PASS" if ok else "FAIL"
        line = f"[{tag}] {path:36} {label}"
        print(line + (f"  <- {why}" if why else ""))
    print("-" * 98)
    print(
        f"{len(results)} checks: {len(results) - len(failed)} passed, {len(failed)} failed"
    )
    print("RESULT: " + ("OK" if not failed else "FAILED"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
