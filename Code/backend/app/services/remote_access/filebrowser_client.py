"""FileBrowser REST 客户端（SSRF 防护 + JWT 缓存）。

FileBrowser API 约定（Cloudflare 隧道要求 User-Agent）：
- POST /api/login          body {"username","password"} → JWT 字符串
- GET  /api/resources/{p}  X-Auth: <token> → 目录条目（根目录 dict / 子目录 list）
- GET  /api/search?q=      X-Auth: <token> → 搜索结果条目
- GET  /api/raw/{p}        下载（本期 browser 不实现，下载走算法包 remote_sync）

所有出站请求经 ``app.core.ssrf.safe_urlopen``（允许内网目标：profile 由管理员
配置，属于可信内部数据源场景；环回/链路本地等仍被阻断）。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote

from app.core.ssrf import safe_urlopen

logger = logging.getLogger(__name__)

_USER_AGENT = "CGDA-Backend/1.0"
_TOKEN_TTL_SECONDS = 45 * 60
_DEFAULT_TIMEOUT = 30.0

# (base_url, username) -> (token, expires_at_monotonic)
_token_cache: dict[tuple[str, str], tuple[str, float]] = {}


class FileBrowserError(RuntimeError):
    """FileBrowser 交互失败（消息已脱敏，不含 token/密码）。"""


class FileBrowserAuthError(FileBrowserError):
    """登录或鉴权失败（不触发双路径回退）。"""


def clear_filebrowser_token_cache() -> None:
    _token_cache.clear()


def _login(base_url: str, username: str, password: str) -> str:
    login_url = f"{base_url.rstrip('/')}/api/login"
    body = json.dumps({"username": username, "password": password}).encode("utf-8")
    try:
        with safe_urlopen(
            login_url,
            timeout=_DEFAULT_TIMEOUT,
            headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
            data=body,
            allow_private=True,
        ) as resp:
            token = resp.read().decode("utf-8").strip().strip('"')
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise FileBrowserAuthError("FileBrowser 登录被拒绝（用户名或密码错误）")
        raise FileBrowserError(f"FileBrowser 登录失败（HTTP {exc.code}）") from exc
    except Exception as exc:  # noqa: BLE001 — 网络类错误统一转译，避免泄露内网细节
        raise FileBrowserError("FileBrowser 登录失败（无法连接服务器）") from exc
    if not token:
        raise FileBrowserAuthError("FileBrowser 登录响应为空")
    return token


class FileBrowserClient:
    """面向单个 FileBrowser 服务的客户端（token 自动缓存与续期）。"""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        if not base_url or not username or not password:
            raise FileBrowserError("FileBrowser 需要 base_url、username 与 password")
        self._base = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout = timeout

    def _token(self, *, force: bool = False) -> str:
        key = (self._base, self._username)
        cached = _token_cache.get(key)
        now = time.monotonic()
        if not force and cached and cached[1] > now:
            return cached[0]
        token = _login(self._base, self._username, self._password)
        _token_cache[key] = (token, now + _TOKEN_TTL_SECONDS)
        return token

    def _get(self, api_path: str, *, params: dict[str, str] | None = None) -> Any:
        from urllib.parse import urlencode

        url = f"{self._base}{api_path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        token = self._token()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with safe_urlopen(
                    url,
                    timeout=self._timeout,
                    headers={"X-Auth": token, "User-Agent": _USER_AGENT},
                    allow_private=True,
                ) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code in {401, 403} and attempt == 0:
                    # token 过期：强制重新登录一次
                    token = self._token(force=True)
                    continue
                if exc.code in {401, 403}:
                    raise FileBrowserAuthError("FileBrowser 鉴权失败（token 已失效）")
                raise FileBrowserError(
                    f"FileBrowser 请求失败（HTTP {exc.code}）"
                ) from exc
            except FileBrowserError:
                raise
            except Exception as exc:  # noqa: BLE001 — 网络类错误统一转译
                last_error = exc
                break
        raise FileBrowserError("FileBrowser 请求失败（无法连接服务器）") from last_error

    @staticmethod
    def _parse_items(data: Any) -> list[dict[str, Any]]:
        items = data.get("items", data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        entries: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            if not name:
                continue
            is_dir = bool(item.get("isDir", False))
            entries.append(
                {
                    "name": name,
                    "is_dir": is_dir,
                    "size": int(item.get("size", 0) or 0) if not is_dir else 0,
                    "path": str(item.get("path", name)),
                }
            )
        return entries

    def list_dir(self, path: str) -> list[dict[str, Any]]:
        encoded = quote(path.lstrip("/"), safe="/") or ""
        data = self._get(f"/api/resources/{encoded}")
        return self._parse_items(data)

    def search(self, query: str, *, max_results: int = 200) -> list[dict[str, Any]]:
        data = self._get("/api/search", params={"q": query})
        return self._parse_items(data)[: max(0, int(max_results))]

    def test(self) -> float:
        """探活：登录一次，返回耗时（毫秒）。"""
        start = time.monotonic()
        self._token(force=True)
        return (time.monotonic() - start) * 1000
