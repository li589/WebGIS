"""NSMC 风云卫星数据门户（新 DataPortal API）客户端。

2026-08-20 实测逆向结论（替代已废弃的旧 PortalSite asmx 直链方案）：

- 旧 ``/PortalSite/WebServ/*.asmx`` 接口已 405 重写为 ``/data/``，不可用；
  ``{base}/{SAT}/MWRID/{date}/`` 目录式直链同样 404。
- 登录链路（跨三个子域）::

    GET  https://satellite.nsmc.org.cn/DataPortal/v1/data/user/login?newurl=<home>
      → 302 http://fy4.nsmc.org.cn/center/v1/user/login?lk=<loginKey>&rd=<sourceURL>
    页面隐藏字段: keyCN（base64url RSA-2048 公钥）/ inputLoginKeyCN / inputSourceURLCN
    验证码:      http://fy4.nsmc.org.cn/center/v1/user/validateCode?data=<rand>（GIF）
    提交:        POST http://fy4.nsmc.org.cn/center/v1/user/commit
                 JSON {userName, thePassword: RSA(PKCS#1 v1.5), validateCode,
                       loginKey, sourceURL}
    令牌同步:    GET https://data.nsmc.org.cn/portalsite/sup/user/tokensync.aspx?token=…
                 （同步后 SHIRO cookie 跨 satellite/data 子域生效）

- 会话检查: ``GET /v1/data/selection/file/<任意名>/download/status`` → ``status==1``
  即有效（``resource`` 是否为直链与文件 DMZ 状态相关，可为 null）。
- 检索: ``GET /v1/data/selection/subfile``（键名与旧 asmx 近似但大小写有差：
  ``productID / txtBeginDate / east_CoordValue / beginIndex``）。
- 下载: ``POST /v1/data/selection/file/download``（form: downloadSource/fileName/
  centerFlag）直接返回文件二进制流 —— 无需购物车/订单，但受账号级频控
  （连续过快会返回非 2xx 或错误 JSON，节点层须节流）。

验证码自动化为可选依赖（``ddddocr``）；未安装或识别失败时抛
:class:`NsmcCaptchaRequired`，调用方应指引用户执行
``Tools/nsmc_online_probe.py prepare && login`` 预热共享会话文件。

依赖：仅标准库（RSA PKCS#1 v1.5 纯 Python 实现，无 pycryptodome 依赖）。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import random
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

# NSMC 站点证书链自签（实测 CERTIFICATE_VERIFY_FAILED）。安审 2026-08-21
# H-5：对齐 data_access/sources/http.py 的统一口径——域名命中
# CGDA_HTTP_INSECURE_HOSTS（默认含 NSMC 门户）才降级为不校验，env 置空
# 可恢复严格校验；降级时记 warning 便于审计。
_INSECURE_HOSTS_DEFAULT = "fy4.nsmc.org.cn,satellite.nsmc.org.cn,data.nsmc.org.cn"


def _insecure_hosts() -> set[str]:
    raw = os.getenv("CGDA_HTTP_INSECURE_HOSTS")
    if raw is None:
        raw = _INSECURE_HOSTS_DEFAULT
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _nsmc_ssl_context() -> ssl.SSLContext:
    hosts = _insecure_hosts()
    nsmc_hosts = {
        h
        for h in ("fy4.nsmc.org.cn", "satellite.nsmc.org.cn", "data.nsmc.org.cn")
        if h in hosts
    }
    if not nsmc_hosts:
        return ssl.create_default_context()  # 严格校验
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    logging.getLogger(__name__).warning(
        "NSMC portal TLS verification disabled for hosts: %s "
        "(CGDA_HTTP_INSECURE_HOSTS)",
        ",".join(sorted(nsmc_hosts)),
    )
    return ctx


_SSL_CONTEXT = _nsmc_ssl_context()

# 门户端点单点定义（ingest/endpoints.py，env 可覆盖：CGDA_NSMC_*）
from ingest.endpoints import (  # noqa: E402
    NSMC_CENTER_BASE as _CENTER_BASE,
    NSMC_HOME_URL as _HOME_URL,
    NSMC_LOGIN_ENTRY as _LOGIN_ENTRY,
    NSMC_PORTAL_BASE as _PORTAL_BASE,
    NSMC_TOKENSYNC_URL as _TOKENSYNC,
)

# 网络超时（硬编码清理 E1：env 可覆盖，默认原值）
_DOWNLOAD_TIMEOUT = float(os.getenv("CGDA_DOWNLOAD_TIMEOUT", "600"))

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CGDA-DataNode"

# 产品文件名模板真源：GET /v1/data/overview/products?seriesCode=FY3X&satelliteCode=…
# （2026-08-20 抓取；MWRI L1 为逐轨道 HDF，与 fy_preprocess 的输入契约一致）。
# 在线覆盖实测（2026-08-20）：FY3D MWRID/MWRIA 至今在线；FY3F ORBA/ORBD
# 仅 2023-12~2024 年中在线（与 NAS 3Ffinal 覆盖期一致），2025+ 检索为空——
# 属数据源现实，非客户端缺陷。
NSMC_PRODUCT_TEMPLATES: dict[tuple[str, str], str] = {
    ("FY3D", "MWRID"): "FY3D_MWRID_GBAL_L1_YYYYMMDD_HHmm_010KM_MS.HDF",
    ("FY3D", "MWRIA"): "FY3D_MWRIA_GBAL_L1_YYYYMMDD_HHmm_010KM_MS.HDF",
    # FY3F MWRI L1 实测命名带连字符（FY3F_MWRI-_ORBA_L1_*.HDF）
    ("FY3F", "ORBA"): "FY3F_MWRI-_ORBA_L1_YYYYMMDD_HHmm_010KM_Vn.HDF",
    ("FY3F", "ORBD"): "FY3F_MWRI-_ORBD_L1_YYYYMMDD_HHmm_010KM_Vn.HDF",
}


class NsmcCaptchaRequired(RuntimeError):
    """登录需要验证码但当前环境无法自动识别（无 ddddocr 或识别失败）。

    message 附带人工预热指引；上层应将其转换为可诊断的节点错误，
    并优先尝试已持久化的共享会话（见 NsmcPortalClient.load_session）。
    """


class NsmcDownloadError(RuntimeError):
    """NSMC 下载失败（频控 / 会话失效 / 网络异常）。"""


# ── RSA PKCS#1 v1.5（纯 Python，兼容 JSEncrypt） ────────────────────────────


def _der_walk(data: bytes, offset: int = 0) -> tuple[int, bytes, int]:
    """单步 DER TLV 解析：返回 (tag, value, next_offset)。"""
    tag = data[offset]
    pos = offset + 1
    length = data[pos]
    pos += 1
    if length & 0x80:
        n_bytes = length & 0x7F
        length = int.from_bytes(data[pos : pos + n_bytes], "big")
        pos += n_bytes
    value = data[pos : pos + length]
    return tag, value, pos + length


def _parse_spki_modulus_exponent(der: bytes) -> tuple[int, int]:
    """解析 X.509 SubjectPublicKeyInfo（RSA）中的 (modulus, exponent)。

    结构: SEQUENCE{ SEQUENCE{OID, NULL}, BIT STRING{ SEQUENCE{INT n, INT e} } }
    """
    _, outer, _ = _der_walk(der)
    # 第一个子元素：算法 SEQUENCE（跳过）
    _, _, pos = _der_walk(outer)
    # 第二个子元素：BIT STRING（value 首字节为未用位数，其后为 RSAPublicKey DER）
    tag, bitstring, _ = _der_walk(outer, pos)
    if tag != 0x03:
        raise ValueError("NSMC 公钥 DER 非预期结构（第二元素非 BIT STRING）")
    _, seq_body, _ = _der_walk(bitstring, 1)
    # RSAPublicKey: SEQUENCE{ INTEGER n, INTEGER e }
    _, n_raw, n_pos = _der_walk(seq_body)
    _, e_raw, _ = _der_walk(seq_body, n_pos)
    return int.from_bytes(n_raw, "big"), int.from_bytes(e_raw, "big")


def rsa_pkcs1_v15_encrypt(public_key_b64url: str, plaintext: str) -> str:
    """JSEncrypt 兼容加密：NSMC 服务端公钥为 base64url 单行。

    返回标准 base64 密文（与 jsencrypt.encrypt 输出一致）。
    """
    b64 = public_key_b64url.strip().replace("-", "+").replace("_", "/")
    der = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
    n, e = _parse_spki_modulus_exponent(der)
    k = (n.bit_length() + 7) // 8
    data = plaintext.encode("utf-8")
    if len(data) > k - 11:
        raise ValueError("RSA 明文超过密钥容量")
    # EM = 0x00 || 0x02 || PS(非零随机) || 0x00 || D
    ps_len = k - len(data) - 3
    ps = bytearray()
    while len(ps) < ps_len:
        b = random.randbytes(1)
        if b != b"\x00":
            ps += b
    em = b"\x00\x02" + bytes(ps) + b"\x00" + data
    m = int.from_bytes(em, "big")
    c = pow(m, e, n)
    return base64.b64encode(c.to_bytes(k, "big")).decode("ascii")


# ── 客户端 ───────────────────────────────────────────────────────────────────


class NsmcPortalClient:
    """NSMC 新门户会话客户端（登录 / 检索 / 单文件下载）。

    Parameters
    ----------
    session_file:
        会话持久化 JSON（cookies + username）。跨进程复用（工作流节点与
        ``Tools/nsmc_online_probe.py`` 预热共享同一文件）。
    username / password:
        登录凭据（多账号轮换由调用方管理，每账号一个 client 实例）。
    captcha_solver:
        ``callable(image_bytes) -> str``；缺省尝试 ddddocr，再缺省抛
        :class:`NsmcCaptchaRequired`。
    download_interval:
        相邻下载请求的最小间隔秒数（NSMC 账号级频控，实测连续请求会触发
        "您下载频率过于频繁"）。
    """

    def __init__(
        self,
        *,
        session_file: str | Path | None = None,
        username: str = "",
        password: str = "",
        captcha_solver=None,
        download_interval: float = 5.0,
    ) -> None:
        self.session_file = Path(session_file) if session_file else None
        self.username = username
        self.password = password
        self._captcha_solver = captcha_solver
        self.download_interval = max(0.0, float(download_interval))
        self._last_download_ts = 0.0
        self._jar = CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar),
            urllib.request.HTTPSHandler(context=_SSL_CONTEXT),
        )
        self._opener.addheaders = [
            ("User-Agent", _UA),
            ("Accept-Language", "zh-CN,zh-Hans;q=0.9"),
        ]

    # ── 底层请求 ─────────────────────────────────────────────────────────

    def _request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> tuple[int, bytes, dict[str, str]]:
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            resp = self._opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)
        return resp.status, resp.read(), dict(resp.headers)

    def _get_json(self, url: str, params: dict | None = None, **kw) -> dict:
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        status, body, _ = self._request(url, **kw)
        if status != 200:
            raise NsmcDownloadError(f"NSMC HTTP {status}: {url[:120]}")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NsmcDownloadError(
                f"NSMC 响应非 JSON（HTTP {status}）: {body[:120]!r}"
            ) from exc

    # ── 会话管理 ─────────────────────────────────────────────────────────

    def save_session(self) -> None:
        if self.session_file is None:
            return
        payload = {
            "username": self.username,
            "cookies": {c.name: c.value for c in self._jar},
            "saved_at": time.time(),
        }
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.session_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.session_file)

    def load_session(self) -> bool:
        """恢复持久化会话；仅在账号一致时采用。"""
        if self.session_file is None or not self.session_file.exists():
            return False
        try:
            payload = json.loads(self.session_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict):
            return False
        if self.username and payload.get("username") != self.username:
            return False
        for name, value in (payload.get("cookies") or {}).items():
            self._jar.set_cookie(_make_cookie(name, str(value), ".nsmc.org.cn"))
        return True

    def check_session(self) -> bool:
        """download/status 探针：status==1 即登录态有效。"""
        probe = "FY3D_MWRID_GBAL_L1_20240601_2254_010KM_MS.HDF"
        try:
            result = self._get_json(
                f"{_PORTAL_BASE}/v1/data/selection/file/{probe}/download/status",
                params={"downloadSource": "NewPortalCH"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        except NsmcDownloadError:
            return False
        return result.get("status") == 1

    # ── 登录 ─────────────────────────────────────────────────────────────

    def _solve_captcha(self, image: bytes) -> str:
        solver = self._captcha_solver
        if solver is None:
            try:
                import ddddocr  # 可选依赖，延迟导入

                _ocr = ddddocr.DdddOcr(show_ad=False)
                solver = _ocr.classification
            except Exception:  # noqa: BLE001 —— 无 OCR 能力
                raise NsmcCaptchaRequired(
                    "NSMC 登录需要验证码且本环境无 ddddocr；"
                    "请先运行 Tools/nsmc_online_probe.py prepare && "
                    "login --code <验证码> 预热共享会话后重试"
                )
        code = str(solver(image) or "").strip()
        if not code:
            raise NsmcCaptchaRequired("NSMC 验证码识别结果为空")
        return code

    def login(self) -> None:
        """完整登录链路（验证码自动识别，失败抛 NsmcCaptchaRequired）。"""
        # ① 登录页（经 satellite 入口 302 到 fy4 center，携带 lk/rd）
        status, body, _ = self._request(
            _LOGIN_ENTRY + "?newurl=" + urllib.parse.quote(_HOME_URL, safe="")
        )
        if status != 200 or b"inputPasswordCN" not in body:
            raise NsmcDownloadError(f"NSMC 登录页获取失败（HTTP {status}）")
        html = body.decode("utf-8", "replace")

        def hidden(field_id: str) -> str:
            m = re.search(
                r'<input[^>]*id="' + field_id + r'"[^>]*value="([^"]*)"', html
            ) or re.search(
                r'<input[^>]*value="([^"]*)"[^>]*id="' + field_id + r'"', html
            )
            return m.group(1) if m else ""

        rsa_key = hidden("keyCN")
        login_key = hidden("inputLoginKeyCN")
        source_url = hidden("inputSourceURLCN")
        if not (rsa_key and login_key):
            raise NsmcDownloadError("NSMC 登录页隐藏字段缺失（keyCN/loginKey）")

        # ② 验证码（与登录页同一 center 会话）
        _, image, _ = self._request(
            f"{_CENTER_BASE}/validateCode?data={random.randint(0, 1 << 20)}"
        )
        if len(image) < 100:
            raise NsmcDownloadError("NSMC 验证码获取失败")
        code = self._solve_captcha(image)

        # ③ 提交（密码 RSA 加密，JSEncrypt 兼容）
        payload = json.dumps(
            {
                "userName": self.username,
                "thePassword": rsa_pkcs1_v15_encrypt(rsa_key, self.password),
                "validateCode": code,
                "loginKey": login_key,
                "sourceURL": source_url,
            }
        ).encode("utf-8")
        result = self._get_json(
            _CENTER_BASE + "/commit",
            data=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": _CENTER_BASE + "/login",
            },
        )
        if result.get("status") != 1:
            raise NsmcDownloadError(
                f"NSMC 登录失败: status={result.get('status')} "
                f"message={result.get('message')}"
            )
        # ④ 跨域令牌同步（satellite/data 子域 SHIRO cookie 生效的关键）
        token = (result.get("resource") or {}).get("token")
        if token:
            try:
                self._request(_TOKENSYNC + "?token=" + urllib.parse.quote(str(token)))
            except (urllib.error.URLError, OSError):
                pass  # 同步失败由 check_session 兜底判定
        self.save_session()

    def ensure_session(self) -> None:
        """会话有效性保障：缓存 → 校验 → 失效则重新登录。"""
        self.load_session()
        if self.check_session():
            return
        self._jar.clear()
        if not (self.username and self.password):
            raise NsmcCaptchaRequired(
                "NSMC 会话失效且未配置账号凭据；请先运行 "
                "Tools/nsmc_online_probe.py 预热共享会话"
            )
        self.login()
        if not self.check_session():
            raise NsmcDownloadError("NSMC 登录后会话校验仍失败")

    # ── 检索与下载 ───────────────────────────────────────────────────────

    def search_daily_files(
        self,
        product_template: str,
        day: str,
        *,
        max_files: int = 100,
    ) -> list[dict]:
        """检索指定产品在某天（YYYY-MM-DD）的轨道文件列表。

        返回 subfile resource 条目（含 ARCHIVENAME / DATASIZE / CNETERFLAG 等）。
        """
        params: dict[str, object] = {
            "productID": product_template,
            "txtBeginDate": day,
            "txtBeginTime": "00:00:00",
            "txtEndDate": day,
            "txtEndTime": "23:59:59",
            "east_CoordValue": "180",
            "south_CoordValue": "-90",
            "west_CoordValue": "-180",
            "north_CoordValue": "90",
            "cbAllArea": "",
            "cbGHIArea": "",
            "converStatus": "Part",
            "rdbIsEvery": "on",
            "beginIndex": 1,
            "endIndex": min(max_files, 100),
            "where": "",
            "source": 0,
            "timeSelection": "",
            "periodTime": "",
            "daynight": "",
        }
        result = self._get_json(
            f"{_PORTAL_BASE}/v1/data/selection/subfile",
            params=params,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": _PORTAL_BASE + "/cn/data/dataset.html",
            },
        )
        if result.get("status") != 1:
            raise NsmcDownloadError(f"NSMC subfile 检索失败: {result.get('message')}")
        files = result.get("resource") or []
        return [
            item for item in files if isinstance(item, dict) and item.get("ARCHIVENAME")
        ]

    def download_file(
        self, filename: str, dest: Path, *, center_flag: str = "1"
    ) -> Path:
        """单文件下载（POST 表单直下，返回落盘路径）。

        受类级 ``download_interval`` 节流；NSMC 频控响应转 NsmcDownloadError。
        """
        wait = self.download_interval - (time.monotonic() - self._last_download_ts)
        if wait > 0:
            time.sleep(wait)
        form = urllib.parse.urlencode(
            {
                "downloadSource": "NewPortalCH",
                "fileName": filename,
                "centerFlag": center_flag,
            }
        ).encode("utf-8")
        try:
            status, body, headers = self._request(
                f"{_PORTAL_BASE}/v1/data/selection/file/download",
                data=form,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": _PORTAL_BASE + "/cn/data/dataset.html",
                },
                timeout=_DOWNLOAD_TIMEOUT,
            )
        finally:
            self._last_download_ts = time.monotonic()
        if status != 200:
            raise NsmcDownloadError(
                f"NSMC 下载 HTTP {status}（可能触发频控/会话失效）: {filename}"
            )
        ctype = headers.get("Content-Type", "")
        if "json" in ctype.lower() or body[:1] in (b"{", b"["):
            # 频控/错误以 JSON 返回（正常文件流 Content-Type 为空或 octet-stream）
            snippet = body[:200].decode("utf-8", "replace")
            raise NsmcDownloadError(f"NSMC 下载被拒绝: {filename}: {snippet}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(body)
        os.replace(tmp, dest)
        return dest


def _make_cookie(name: str, value: str, domain: str):
    from http.cookiejar import Cookie

    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=domain.startswith("."),
        path="/",
        path_specified=True,
        secure=False,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )
