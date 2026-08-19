"""NSMC 风云卫星数据门户在线拉取探测工具（新 DataPortal API）。

背景（2026-08-20 实测）：
- 旧 PortalSite WebServ asmx 接口已被重写为 /data/ 服务（405），不可用。
- 新门户登录链路：
    GET https://satellite.nsmc.org.cn/DataPortal/v1/data/user/login?newurl=<home>
      → 302 http://fy4.nsmc.org.cn/center/v1/user/login?lk=<loginKey>&rd=<sourceURL>
    登录页隐藏字段：keyCN（RSA 公钥）、inputLoginKeyCN、inputSourceURLCN
    验证码：http://fy4.nsmc.org.cn/center/v1/user/validateCode?data=<rand>
    提交：POST http://fy4.nsmc.org.cn/center/v1/user/commit
          JSON {userName, thePassword: RSA(key, pwd), validateCode, loginKey, sourceURL}
- 登录成功后 resource.token 经 tokensync.aspx 同步，会话以 Cookie 保持。

分步用法（验证码需人工识别后传入）：
    python Tools/nsmc_online_probe.py prepare [--account 0]
    python Tools/nsmc_online_probe.py login --code ABCD
    python Tools/nsmc_online_probe.py quota
    python Tools/nsmc_online_probe.py search --satellite FY3D --date 2024-06-01
    python Tools/nsmc_online_probe.py order --index 0
    python Tools/nsmc_online_probe.py poll [--timeout 900]
    python Tools/nsmc_online_probe.py download [--out DIR]

账号解析：后端门户凭据（app.services.config_service.get_portal_credentials_runtime）
的 cma_nsmc/nsmc entry，accounts[account_index]。凭据不入库不入日志。

状态文件：.pytest_nsmc_probe/state.json（gitignore 已覆盖 .pytest_*）。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import warnings
from pathlib import Path

import requests
import urllib3

warnings.filterwarnings("ignore")
urllib3.disable_warnings()

REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = REPO_ROOT / ".pytest_nsmc_probe"
STATE_FILE = STATE_DIR / "state.json"
CAPTCHA_FILE = STATE_DIR / "captcha.png"

HOME_URL = "https://satellite.nsmc.org.cn/DataPortal/cn/home/index.html"
LOGIN_ENTRY = "https://satellite.nsmc.org.cn/DataPortal/v1/data/user/login"
CENTER_LOGIN = "http://fy4.nsmc.org.cn/center/v1/user/login"
CENTER_COMMIT = "http://fy4.nsmc.org.cn/center/v1/user/commit"
CENTER_CAPTCHA = "http://fy4.nsmc.org.cn/center/v1/user/validateCode"
TOKENSYNC = "https://data.nsmc.org.cn/portalsite/sup/user/tokensync.aspx"
PORTAL_API = "https://satellite.nsmc.org.cn/DataPortal"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def log(msg: str) -> None:
    print(f"[nsmc-probe] {msg}", flush=True)


def resolve_account(index: int) -> dict[str, str]:
    backend = REPO_ROOT / "Code" / "backend"
    sys.path.insert(0, str(backend))
    import os

    os.chdir(str(backend))
    from app.services.config_service import get_portal_credentials_runtime

    creds = get_portal_credentials_runtime()
    entry = creds.get("nsmc") or creds.get("cma_nsmc") or {}
    accounts = entry.get("accounts") or []
    if not accounts:
        raise SystemExit("后端门户凭据中无 NSMC accounts")
    acc = accounts[index]
    log(f"账号[{index}]: {acc['username']}")
    return acc


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh-Hans;q=0.9"})
    s.verify = False
    return s


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def session_from_state(state: dict) -> requests.Session:
    s = new_session()
    for name, value in state.get("cookies", {}).items():
        s.cookies.set(name, value)
    return s


def save_session(s: requests.Session, state: dict) -> None:
    state["cookies"] = {c.name: c.value for c in s.cookies}
    save_state(state)


# ── 步骤 1：prepare ──────────────────────────────────────────────────────────


def cmd_prepare(args: argparse.Namespace) -> None:
    account = resolve_account(args.account)
    s = new_session()
    s.get(HOME_URL, timeout=30)

    r = s.get(
        f"{LOGIN_ENTRY}?newurl={requests.utils.quote(HOME_URL, safe='')}",
        timeout=30,
        allow_redirects=True,
    )
    if r.status_code != 200 or "inputPasswordCN" not in r.text:
        raise SystemExit(f"登录页获取失败: {r.status_code} (len={len(r.text)})")
    log(f"登录页 OK: {r.url[:80]}...")

    def hidden(field_id: str) -> str:
        m = re.search(
            r'<input[^>]*id="' + field_id + r'"[^>]*value="([^"]*)"', r.text
        ) or re.search(
            r'<input[^>]*value="([^"]*)"[^>]*id="' + field_id + r'"', r.text
        )
        return m.group(1) if m else ""

    state = {
        "account": {k: account[k] for k in ("username", "password")},
        "login_key": hidden("inputLoginKeyCN"),
        "source_url": hidden("inputSourceURLCN"),
        "rsa_key": hidden("keyCN"),
        "cookies": {},
        "csrf": None,
        "order": None,
    }
    if not state["rsa_key"] or not state["login_key"]:
        raise SystemExit("登录页隐藏字段缺失（keyCN/inputLoginKeyCN）")

    resp = s.get(
        f"{CENTER_CAPTCHA}?data={random.randint(0, 1024 * 1024)}", timeout=30
    )
    if resp.status_code != 200 or len(resp.content) < 100:
        raise SystemExit(f"验证码获取失败: {resp.status_code}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CAPTCHA_FILE.write_bytes(resp.content)
    save_session(s, state)
    log(f"验证码已保存: {CAPTCHA_FILE} ({len(resp.content)}B)")
    log("请人工识别验证码后执行: python Tools/nsmc_online_probe.py login --code <识别结果>")


# ── 步骤 2：login ────────────────────────────────────────────────────────────


import base64

from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA


def rsa_encrypt(public_key_b64: str, plaintext: str) -> str:
    """JSEncrypt 兼容：PKCS#1 v1.5，输出 base64。

    NSMC 服务端公钥为 base64url 单行（392 字符 2048-bit），需转标准 base64
    并加 64 字符换行包裹成 PEM，再走 X.509 SPKI。
    """
    b64 = public_key_b64.strip().replace("-", "+").replace("_", "/")
    raw = base64.urlsafe_b64decode(b64 + "==" * (-len(b64) % 4))
    wrapped = "\n".join(
        base64.standard_b64encode(raw).decode().splitlines()
    )
    pem = f"-----BEGIN PUBLIC KEY-----\n{wrapped}\n-----END PUBLIC KEY-----\n"
    key = RSA.import_key(pem)
    cipher = PKCS1_v1_5.new(key)
    encrypted = cipher.encrypt(plaintext.encode("utf-8"))
    return base64.b64encode(encrypted).decode("ascii")


def cmd_login(args: argparse.Namespace) -> None:
    state = load_state()
    s = session_from_state(state)
    acc = state["account"]

    payload = {
        "userName": acc["username"],
        "thePassword": rsa_encrypt(state["rsa_key"], acc["password"]),
        "validateCode": args.code,
        "loginKey": state["login_key"],
        "sourceURL": state["source_url"],
    }
    r = s.post(
        CENTER_COMMIT,
        json=payload,
        headers={"Referer": CENTER_LOGIN, "X-Requested-With": "XMLHttpRequest"},
        timeout=30,
    )
    try:
        result = r.json()
    except ValueError:
        raise SystemExit(f"commit 响应非 JSON: HTTP {r.status_code} {r.text[:200]}")

    status = result.get("status")
    if status != 1:
        raise SystemExit(f"登录失败 status={status}: {result.get('message')}")

    resource = result.get("resource") or {}
    token = resource.get("token")
    if token:
        try:
            s.get(f"{TOKENSYNC}?token={token}", timeout=30)
            log("token 同步完成")
        except Exception as exc:  # noqa: BLE001
            log(f"token 同步异常（忽略）: {exc}")

    save_session(s, state)
    log(f"登录成功: {(resource.get('userInfo') or {}).get('userName', acc['username'])}")

    # 验证会话：购物车配额接口
    r2 = s.get(f"{PORTAL_API}/v1/data/cart/subsize", timeout=30)
    log(f"配额探测: HTTP {r2.status_code} {r2.text[:300]}")


# ── 步骤 3：quota / CSRF ─────────────────────────────────────────────────────


def get_csrf(s: requests.Session, state: dict) -> str | None:
    r = s.get(f"{PORTAL_API}/v1/data/selection/token", timeout=30)
    try:
        d = r.json()
        if d.get("status") == 1:
            state["csrf"] = d.get("resource")
            save_state(state)
            return state["csrf"]
    except ValueError:
        pass
    return state.get("csrf")


def cmd_quota(args: argparse.Namespace) -> None:
    state = load_state()
    s = session_from_state(state)
    r = s.get(f"{PORTAL_API}/v1/data/cart/subsize", timeout=30)
    print(json.dumps(r.json(), ensure_ascii=False, indent=2) if r.headers.get(
        "Content-Type", ""
    ).startswith("application/json") else r.text[:500])


# ── 步骤 4：search ───────────────────────────────────────────────────────────


def cmd_search(args: argparse.Namespace) -> None:
    """检索某日 FY 卫星 MWRI 文件列表（selection/subfile）。

    参数结构参考 page.data.index.search.js / page.data.file.list.js。
    """
    state = load_state()
    s = session_from_state(state)
    csrf = get_csrf(s, state)

    # 先取数据集/产品树，定位 MWRI L1 数据集 id
    r = s.get(
        f"{PORTAL_API}/v1/data/selection/file/subcount",
        params={
            "satelliteCode": args.satellite,
            "instrumentTypeCode": "MWRI",
            "productLevel": "L1",
            "beginDate": f"{args.date} 00:00:00",
            "endDate": f"{args.date} 23:59:59",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=30,
    )
    log(f"subcount: HTTP {r.status_code}")
    print(r.text[:2000])
    _ = csrf


def _shared_session_file() -> Path | None:
    """与算法包 modules/fy_download._nsmc_session_file 同一优先级逻辑。"""
    explicit = os.getenv("CGDA_NSMC_SESSION_FILE", "").strip()
    if explicit:
        return Path(explicit)
    data_root = os.getenv("BACKEND_DATA_ROOT", "").strip()
    if data_root:
        return Path(data_root) / "_runtime" / "cache" / "nsmc_session.json"
    return None


def cmd_export(args: argparse.Namespace) -> None:
    """把已登录会话导出到 CGDA 共享会话文件（fy_download 节点复用）。"""
    state = load_state()
    shared = _shared_session_file()
    if shared is None:
        raise SystemExit(
            "未配置共享会话路径：设置 CGDA_NSMC_SESSION_FILE 或 BACKEND_DATA_ROOT"
        )
    payload = {
        "username": state["account"]["username"],
        "cookies": state.get("cookies", {}),
        "saved_at": time.time(),
    }
    shared.parent.mkdir(parents=True, exist_ok=True)
    shared.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log(f"已导出会话（{state['account']['username']}）-> {shared}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--account", type=int, default=0)
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("login")
    p.add_argument("--code", required=True)
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("export")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("quota")
    p.set_defaults(func=cmd_quota)

    p = sub.add_parser("search")
    p.add_argument("--satellite", default="FY3D")
    p.add_argument("--date", default="2024-06-01")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("order")
    p.add_argument("--index", type=int, default=0)
    p.set_defaults(func=lambda a: log("not implemented yet"))

    p = sub.add_parser("poll")
    p.add_argument("--timeout", type=int, default=900)
    p.set_defaults(func=lambda a: log("not implemented yet"))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
