"""NAS 只读客户端 —— 全项目唯一允许连 NAS 的地方。

═══════════════════════════════════════════════════════════════════════════
安全设计（改动前请读完）
═══════════════════════════════════════════════════════════════════════════
* 唯一出口 ``_http()``：非 GET 请求只有一处被允许 —— ``POST /api/login``
  换 token。任何其它非 GET 请求会直接抛 ``NasWriteForbidden``，不会到达网络。
* 路径白名单 ``assert_nas_path_readable()`` 在**发请求之前**校验；对不上
  config.ALLOWED_NAS_PREFIXES 的前缀直接抛 ``NasPathDenied``。
* 不引用本地 ``Z:`` 盘符；所有路径走 HTTPS。
* 只下载 ``YYYYMMDD.mat``（``assert_mat_filename()`` 强校验后缀）。
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from app.services.nas_ondemand import config

logger = logging.getLogger(__name__)

_MAT_RE = re.compile(r"^\d{8}\.mat$")
_DATE_RE = re.compile(r"^\d{8}$")

# 允许下载的文件名（白名单，逐个精确匹配；其余一律拒绝）
# 1) YYYYMMDD.mat                                       —— smvod 目录逐日
# 2) doy_DDD.mat                                        —— *_avg_ω 按年内日序
# 3) YYYYMMDD_YYYYMMDD_exp0_global_ismn_all_shard01of01_roundrobin.mat
#                                                       —— *_raw_ω 8 天块
_NAMED_MAT_PATTERNS = (
    _MAT_RE,
    re.compile(r"^doy_\d{3}\.mat$"),
    re.compile(r"^\d{8}_\d{8}_exp0_global_ismn_all_shard01of01_roundrobin\.mat$"),
)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

# 自签证书 / 隧道证书链不完整，按已有只读脚本的做法跳过校验（仅只读用途）
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, object] = {"token": None, "expires_at": 0.0}
_TOKEN_TTL = 6 * 3600.0

# OMEGA 目录名探测结果缓存（product → 真正可用的目录）
_DIR_CACHE: dict[str, str] = {}
_DIR_LOCK = threading.Lock()


class NasError(RuntimeError):
    """NAS 访问失败的基类。"""


class NasPathDenied(NasError):
    """路径不在白名单内 —— 请求根本不会发出去。"""


class NasWriteForbidden(NasError):
    """试图发出非 GET 请求 —— 红线，直接拦截。"""


class NasUnavailable(NasError):
    """网络/登录/服务端故障。"""


class NasFileMissing(NasError):
    """白名单目录内，但该日期的 .mat 不存在（正常业务情况，非故障）。"""


# ── 白名单校验 ────────────────────────────────────────────────────────────────
def assert_nas_path_readable(remote_path: str) -> str:
    """校验远程路径是否落在白名单目录内，返回规范化后的路径。

    Raises:
        NasPathDenied: 不在白名单内，或含 ``..`` 等穿越成分。
    """
    raw = str(remote_path or "").strip()
    if not raw.startswith("/"):
        raw = "/" + raw
    parts = [p for p in raw.split("/") if p != ""]
    if not parts:
        raise NasPathDenied("空路径，拒绝")
    # 拒绝穿越与当前目录段（防 ``/…/fy_avg_smvod/../../xxx`` 逃逸）
    if any(p in (".", "..") for p in parts):
        raise NasPathDenied(f"路径含穿越成分，拒绝：{raw}")
    normalized = "/" + "/".join(parts)
    # 末段含 "." → 视为文件，取所在目录；否则视为目录
    if "." in parts[-1]:
        target_dir = "/" + "/".join(parts[:-1]) + "/"
    else:
        target_dir = normalized + "/"
    for prefix in config.ALLOWED_NAS_PREFIXES:
        if target_dir.startswith(prefix):
            return normalized
    raise NasPathDenied(
        f"路径不在 NAS 只读白名单内，已拦截（未发出请求）：{normalized}"
    )


def assert_mat_filename(remote_path: str) -> str:
    """文件名必须命中 3 种白名单命名之一，其它一律拒绝。"""
    name = remote_path.rsplit("/", 1)[-1]
    if not any(p.match(name) for p in _NAMED_MAT_PATTERNS):
        raise NasPathDenied(
            "只允许下载已核对的三种 .mat 命名，拒绝："
            f"{name!r}（允许 YYYYMMDD.mat / doy_DDD.mat / "
            "YYYYMMDD_YYYYMMDD_exp0_*.mat）"
        )
    return name


def assert_date_tag(date_tag: str) -> str:
    """日期必须是 8 位数字。"""
    tag = str(date_tag or "").strip()
    if not _DATE_RE.match(tag):
        raise ValueError(f"日期必须是 YYYYMMDD 八位数字，收到：{date_tag!r}")
    return tag


# ── 唯一出口 ──────────────────────────────────────────────────────────────────
def _http(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 60.0,
) -> Any:
    """所有 NAS 请求的唯一出口。

    红线：``method != "GET"`` 时，只放行登录接口，其它一律抛异常。
    """
    upper = method.upper()
    if upper != "GET":
        if upper != "POST" or not url.endswith("/api/login"):
            raise NasWriteForbidden(
                f"红线拦截：只允许 GET（登录除外），收到 {upper} {url}"
            )
    req = urllib.request.Request(
        url, data=data, headers={**_UA, **(headers or {})}, method=upper
    )
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise
        raise NasUnavailable(f"NAS 返回 HTTP {exc.code}：{url}") from exc
    except urllib.error.URLError as exc:
        raise NasUnavailable(
            f"连不上 NAS（隧道可能已断）：{exc.reason}｜{config._load_nas_config()[0]}"
        ) from exc


def _login() -> str:
    """取 token（缓存 6 小时）。整个模块唯一的非 GET 调用。"""
    now = time.time()
    with _TOKEN_LOCK:
        token = _TOKEN_CACHE.get("token")
        if token and float(_TOKEN_CACHE.get("expires_at") or 0) > now:
            return str(token)
        base, user, pwd = config._load_nas_config()
        body = json.dumps({"username": user, "password": pwd}).encode()
        with _http(
            base + "/api/login",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=body,
            timeout=config.LIST_TIMEOUT,
        ) as resp:
            token = resp.read().decode().strip().strip('"')
        if not token:
            raise NasUnavailable("NAS 登录返回空 token")
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["expires_at"] = now + _TOKEN_TTL
        return token


def _auth_headers() -> dict[str, str]:
    return {"X-Auth": _login()}


def _quote(remote_path: str) -> str:
    return urllib.parse.quote(remote_path.strip("/"), safe="/")


# ── 只读操作：列目录 / 探测 / 下载 ────────────────────────────────────────────
def list_dir(remote_dir: str) -> list[dict]:
    """列白名单目录内容。返回 FileBrowser 的 ``items`` 列表。"""
    path = assert_nas_path_readable(remote_dir)
    base, _, _ = config._load_nas_config()
    url = f"{base}/api/resources/{_quote(path)}"
    try:
        with _http(url, headers=_auth_headers(), timeout=config.LIST_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except NasUnavailable:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise NasUnavailable(f"列目录失败 HTTP {exc.code}：{path}") from exc
    items = payload.get("items") if isinstance(payload, dict) else None
    return items if isinstance(items, list) else []


def resolve_nas_dir(product: str, variable: str) -> str:
    """确定该产品/变量真正可用的 NAS 目录（OMEGA 有拉丁/希腊两种写法）。"""
    candidates = config.nas_dir_candidates(product, variable)
    if len(candidates) == 1:
        return assert_nas_path_readable(candidates[0])
    key = f"{product}:{variable.upper()}"
    with _DIR_LOCK:
        cached = _DIR_CACHE.get(key)
    if cached:
        return cached
    tried: list[str] = []
    for cand in candidates:
        tried.append(cand)
        items = list_dir(cand)
        if items:
            with _DIR_LOCK:
                _DIR_CACHE[key] = cand
            return cand
    raise NasFileMissing(
        "OMEGA 目录两种写法都读不到内容，请核对 NAS 上的实际目录名。已尝试："
        + "、".join(tried)
    )


def has_date_file(remote_dir: str, date_tag: str) -> bool:
    """白名单目录里是否存在该日的 .mat（只看文件名，不下载）。"""
    tag = assert_date_tag(date_tag)
    want = f"{tag}{config.MAT_SUFFIX}"
    return any(
        isinstance(it, dict) and str(it.get("name")) == want
        for it in list_dir(remote_dir)
    )


def download_file(remote_dir: str, filename: str, dest: Path) -> int:
    """把白名单目录里指定的 ``.mat`` 文件流式下载到 ``dest``，返回字节数。

    网络抖动（``IncompleteRead`` / 连接被重置）会自动重试，最多
    ``config.DOWNLOAD_RETRIES`` 次；``NasFileMissing`` 不重试。

    Raises:
        NasFileMissing: NAS 上没有该文件（正常业务情况）。
    """
    last_exc: BaseException | None = None
    for attempt in range(1, config.DOWNLOAD_RETRIES + 1):
        try:
            return _download_once(remote_dir, filename, dest)
        except NasFileMissing:
            raise
        except Exception as exc:  # noqa: BLE001 - 区分可重试/不可重试
            retryable = isinstance(exc, (NasUnavailable, OSError)) or (
                type(exc).__name__
                in ("IncompleteRead", "RemoteDisconnected", "timeout")
            )
            if not retryable:
                raise
            last_exc = exc
            if attempt >= config.DOWNLOAD_RETRIES:
                break
            logger.warning(
                "下载 %s/%s 第 %d 次失败（%s），重试中",
                remote_dir,
                filename,
                attempt,
                type(exc).__name__,
            )
            time.sleep(1.0 * attempt)
    raise NasUnavailable(
        f"下载 {filename} 连续 {config.DOWNLOAD_RETRIES} 次失败：{last_exc}"
    ) from last_exc


def download_mat(remote_dir: str, date_tag: str, dest: Path) -> int:
    """逐日产品（smvod 目录）：下载 ``YYYYMMDD.mat``。"""
    tag = assert_date_tag(date_tag)
    return download_file(remote_dir, f"{tag}{config.MAT_SUFFIX}", dest)


def _download_once(remote_dir: str, filename: str, dest: Path) -> int:
    remote = f"{remote_dir.rstrip('/')}/{filename}"
    assert_nas_path_readable(remote)
    assert_mat_filename(remote)

    base, _, _ = config._load_nas_config()
    url = f"{base}/api/raw/{_quote(remote)}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    total = 0
    try:
        with _http(
            url, headers=_auth_headers(), timeout=config.DOWNLOAD_TIMEOUT
        ) as resp:
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
                    total += len(chunk)
    except urllib.error.HTTPError as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        if exc.code == 404:
            raise NasFileMissing(f"NAS 上不存在 {filename}（{remote_dir}）") from exc
        raise NasUnavailable(f"下载失败 HTTP {exc.code}：{remote}") from exc
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
    tmp.replace(dest)
    return total


def reset_token_cache() -> None:
    """测试/排障用：清掉内存里的 token 与目录探测结果。"""
    with _TOKEN_LOCK:
        _TOKEN_CACHE["token"] = None
        _TOKEN_CACHE["expires_at"] = 0.0
    with _DIR_LOCK:
        _DIR_CACHE.clear()
