"""统一远程 profile 浏览/搜索分发（双路径回退感知）。

按 profile 协议分发到具体传输实现：
- filebrowser → FileBrowser REST（原生搜索）
- sftp/ssh    → paramiko（支持私钥字符串）
- smb         → smbclient（scandir/listdir）
- ftp/ftps    → ftplib（MLSD/NLST）
- gs          → google-cloud-storage（前缀列举）
- lan/nfs     → UNC/挂载点本地路径直访
- http/https  → HTML 目录索引解析（开放数据目录）

双路径语义（extra.alt + fallback_mode）：
- auto   主路径网络异常时自动切备用（隧道），成功后落 failover_state
- manual 仅按 failover_state.active 钉死使用主/备路径
- off    禁用备用
认证类错误不触发回退（凭据问题换路径无意义）。
"""

from __future__ import annotations

import io
import json
import logging
import posixpath
import re
import stat as stat_module
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from app.core.ssrf import safe_urlopen
from app.services.remote_access.filebrowser_client import (
    FileBrowserAuthError,
    FileBrowserClient,
    FileBrowserError,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20.0
SEARCH_MAX_DEPTH = 3
SEARCH_MAX_RESULTS_DEFAULT = 200
_MAX_PATH_LENGTH = 1024

PROTOCOLS_BROWSABLE = frozenset(
    {
        "sftp",
        "ssh",
        "smb",
        "ftp",
        "ftps",
        "gs",
        "filebrowser",
        "lan",
        "nfs",
        "http",
        "https",
    }
)
PROTOCOLS_SEARCHABLE = frozenset(
    {"sftp", "ssh", "smb", "ftp", "ftps", "gs", "filebrowser", "lan", "nfs"}
)
# http/https 搜索走门户目录（portal_catalog）能力，不在本模块


class RemoteAccessError(RuntimeError):
    """远程访问失败（消息已脱敏）。"""


class RemoteAccessAuthError(RemoteAccessError):
    """认证失败（不触发双路径回退）。"""


class RemoteAccessNetworkError(RemoteAccessError):
    """网络类失败（连接拒绝/超时/DNS 等，触发双路径回退）。"""


def normalize_remote_path(path: str) -> str:
    """校验并规范化远程路径（拒绝空字节/控制字符/遍历/超长）。"""
    if not path:
        return "/"
    if "\x00" in path:
        raise RemoteAccessError("路径不允许包含空字节")
    if len(path) > _MAX_PATH_LENGTH:
        raise RemoteAccessError("路径长度超限")
    if any(ord(ch) < 32 for ch in path):
        raise RemoteAccessError("路径不允许包含控制字符")
    normalized = posixpath.normpath(path.replace("\\", "/"))
    if normalized.startswith("..") or "/.." in normalized or normalized == "..":
        raise RemoteAccessError("路径不允许包含目录遍历")
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized


def _get_repository():
    from app.services.config_remote_storage import get_remote_storage_repository

    return get_remote_storage_repository()


def _get_bundle(profile_id: str) -> dict[str, Any]:
    repo = _get_repository()
    info = repo.get_profile_info(profile_id)
    if info is None:
        raise RemoteAccessError(f"数据源不存在: {profile_id}")
    if not info.get("enabled"):
        raise RemoteAccessError(f"数据源已禁用: {profile_id}")
    bundle = repo.get_secret_bundle(profile_id)
    if bundle is None:
        raise RemoteAccessError(f"数据源凭据不可用: {profile_id}")
    return bundle


# ── 双路径 ────────────────────────────────────────────────────────────────────


def _effective_target(
    bundle: dict[str, Any], which: str, alt: dict[str, Any] | None
) -> dict[str, Any]:
    """返回当次尝试的 effective host/port/url。"""
    extra = bundle.get("extra") or {}
    host = bundle.get("host") or ""
    port = bundle.get("port")
    url = extra.get("base_url") or ""
    if which == "alt" and alt:
        host = alt.get("host") or host
        if alt.get("port") is not None:
            port = alt.get("port")
        url = alt.get("url") or url
    return {"host": host, "port": port, "url": url}


def _record_path_state(bundle: dict[str, Any], which: str) -> None:
    extra = bundle.get("extra") or {}
    state = extra.get("failover_state") or {}
    if state.get("active") == which:
        return
    from datetime import UTC, datetime

    update: dict[str, Any] = {"active": which}
    if which == "alt":
        update["last_failover_at"] = datetime.now(UTC).isoformat()
        update["last_error"] = "primary path unreachable, switched to alt"
    try:
        _get_repository().set_failover_state(bundle["profile_id"], update)
    except Exception:  # noqa: BLE001 — 状态记录失败不影响浏览结果
        logger.warning("记录 failover 状态失败: %s", bundle.get("profile_id"))


def _with_failover(
    bundle: dict[str, Any],
    attempt,
) -> tuple[list[dict[str, Any]], str]:
    """执行 attempt(which, alt) 并按 fallback_mode 处理双路径回退。"""
    extra = bundle.get("extra") or {}
    mode = extra.get("fallback_mode", "auto")
    alt_raw = extra.get("alt")
    alt = alt_raw if isinstance(alt_raw, dict) else None
    alt_valid = bool(alt and any(alt.get(k) for k in ("host", "url", "share")))
    state = extra.get("failover_state") or {}
    pinned_alt = mode == "manual" and state.get("active") == "alt" and alt_valid

    order: list[tuple[str, dict[str, Any] | None]] = []
    if pinned_alt:
        order.append(("alt", alt))
    else:
        order.append(("primary", None))
        if alt_valid and mode == "auto":
            order.append(("alt", alt))

    last_exc: RemoteAccessError | None = None
    for which, alt_view in order:
        try:
            items = attempt(which, alt_view)
            _record_path_state(bundle, which)
            return items, which
        except RemoteAccessAuthError:
            raise
        except RemoteAccessNetworkError as exc:
            last_exc = exc
            continue
    raise last_exc if last_exc else RemoteAccessError("无可用访问路径")


# ── 协议实现：浏览 ────────────────────────────────────────────────────────────


def _load_paramiko_pkey(pem: str):
    import paramiko

    errors: list[Exception] = []
    for key_cls in (
        paramiko.RSAKey,
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
    ):
        try:
            return key_cls.from_private_key(io.StringIO(pem))
        except Exception as exc:  # noqa: BLE001 — 逐类型尝试加载
            errors.append(exc)
    raise RemoteAccessError("私钥格式不受支持（支持 RSA/Ed25519/ECDSA PEM）") from (
        errors[-1] if errors else None
    )


def _entries_sftp(bundle: dict[str, Any], target: dict[str, Any], path: str):
    import paramiko

    host = target["host"]
    if not host:
        raise RemoteAccessError("缺少主机地址")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict[str, Any] = {
        "hostname": host,
        "port": int(target["port"] or 22),
        "username": bundle.get("username") or "",
        "timeout": DEFAULT_TIMEOUT,
        "look_for_keys": False,
        "allow_agent": False,
    }
    pem = bundle.get("private_key_pem")
    if pem:
        kwargs["pkey"] = _load_paramiko_pkey(pem)
    elif bundle.get("secret"):
        kwargs["password"] = bundle["secret"]
    try:
        client.connect(**kwargs)
        sftp = client.open_sftp()
        try:
            entries = sftp.listdir_attr(path)
        finally:
            sftp.close()
    except paramiko.AuthenticationException as exc:
        raise RemoteAccessAuthError("SSH/SFTP 认证失败") from exc
    except Exception as exc:  # noqa: BLE001 — 网络/超时类
        raise RemoteAccessNetworkError(f"SSH/SFTP 连接失败（{host}）") from exc
    finally:
        client.close()

    items: list[dict[str, Any]] = []
    for entry in entries:
        mode = entry.st_mode or 0
        is_dir = stat_module.S_ISDIR(mode)
        items.append(
            {
                "name": entry.filename,
                "is_dir": is_dir,
                "size": 0 if is_dir else int(entry.st_size or 0),
                "mtime": float(entry.st_mtime) if entry.st_mtime else None,
            }
        )
    return items


def _smb_unc(host: str, share: str, path: str) -> str:
    rel = (path or "/").strip("/").replace("/", "\\")
    unc = f"\\\\{host}\\{share}"
    return f"{unc}\\{rel}".rstrip("\\") if rel else unc


def _entries_smb(bundle: dict[str, Any], target: dict[str, Any], path: str):
    share = (bundle.get("extra") or {}).get("default_share") or (
        target.get("url") or ""
    )
    if target.get("url") and not (bundle.get("extra") or {}).get("default_share"):
        share = target["url"]
    if not share:
        raise RemoteAccessError("SMB 数据源缺少 extra.default_share")
    host = target["host"]
    if not host:
        raise RemoteAccessError("SMB 数据源缺少主机地址")
    username = bundle.get("username") or ""
    password = bundle.get("secret") or ""
    domain = bundle.get("domain") or ""
    port = int(target["port"] or 445)
    unc_dir = _smb_unc(host, share, path)
    conn = {
        "username": username or None,
        "password": password or None,
        "port": port,
        "connection_timeout": DEFAULT_TIMEOUT,
        "domain": domain or None,
    }
    try:
        import smbclient

        try:
            from smbprotocol.exceptions import SMBAuthenticationError
        except ImportError:  # pragma: no cover — 版本差异兜底
            SMBAuthenticationError = ()  # type: ignore[assignment,misc]
        try:
            items: list[dict[str, Any]] = []
            scanned = False
            if hasattr(smbclient, "scandir"):
                for entry in smbclient.scandir(unc_dir, **conn):
                    try:
                        st = entry.stat()
                    except OSError:
                        continue
                    is_dir = entry.is_dir()
                    items.append(
                        {
                            "name": entry.name,
                            "is_dir": is_dir,
                            "size": 0
                            if is_dir
                            else int(getattr(st, "st_size", 0) or 0),
                            "mtime": float(getattr(st, "st_mtime", 0) or 0) or None,
                        }
                    )
                scanned = True
            if not scanned:
                for name in smbclient.listdir(unc_dir, **conn):
                    st = smbclient.stat(f"{unc_dir}\\{name}", **conn)
                    is_dir = bool(
                        getattr(st, "st_mode", None) and stat_module.S_ISDIR(st.st_mode)
                    )
                    items.append(
                        {
                            "name": name,
                            "is_dir": is_dir,
                            "size": 0
                            if is_dir
                            else int(getattr(st, "st_size", 0) or 0),
                            "mtime": float(getattr(st, "st_mtime", 0) or 0) or None,
                        }
                    )
            return items
        except SMBAuthenticationError as exc:  # type: ignore[misc]
            raise RemoteAccessAuthError("SMB 认证失败") from exc
    except RemoteAccessError:
        raise
    except ImportError as exc:
        raise RemoteAccessError("未安装 smbclient（smbprotocol）依赖") from exc
    except Exception as exc:  # noqa: BLE001 — 网络/超时类
        raise RemoteAccessNetworkError(f"SMB 连接失败（{host}）") from exc


def _ftp_connect(bundle: dict[str, Any], target: dict[str, Any], scheme: str):
    import ftplib

    host = target["host"]
    if not host:
        raise RemoteAccessError("FTP 数据源缺少主机地址")
    port = int(target["port"] or (990 if scheme == "ftps" else 21))
    extra = bundle.get("extra") or {}
    username = bundle.get("username") or "anonymous"
    password = bundle.get("secret") or "anonymous@"
    try:
        if scheme == "ftps":
            ftp: ftplib.FTP = ftplib.FTP_TLS()
            ftp.connect(host, port, timeout=DEFAULT_TIMEOUT)
            ftp.login(username, password)
            ftp.prot_p()
        else:
            allow_plain = extra.get("allow_plain_ftp")
            if not (allow_plain is True or str(allow_plain).lower() == "true"):
                raise RemoteAccessError(
                    "明文 ftp 默认禁用；在凭据 extra 中设置 allow_plain_ftp=true 或改用 ftps"
                )
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=DEFAULT_TIMEOUT)
            ftp.login(username, password)
        return ftp
    except ftplib.error_perm as exc:
        if "530" in str(exc):
            raise RemoteAccessAuthError("FTP 登录被拒绝") from exc
        raise RemoteAccessError(f"FTP 操作失败: {exc}") from exc
    except RemoteAccessError:
        raise
    except Exception as exc:  # noqa: BLE001 — 网络/超时类
        raise RemoteAccessNetworkError(f"FTP 连接失败（{host}）") from exc


def _entries_ftp(
    bundle: dict[str, Any], target: dict[str, Any], path: str, scheme: str
):
    ftp = _ftp_connect(bundle, target, scheme)
    try:
        try:
            mlsd = list(ftp.mlsd(path))
        except ftplib_error_perm() as exc:  # type: ignore[misc]
            raise RemoteAccessError(f"FTP 目录不可访问: {exc}") from exc
        items: list[dict[str, Any]] = []
        for name, facts in mlsd:
            if name in {".", ".."}:
                continue
            is_dir = facts.get("type") == "dir"
            size_raw = facts.get("size")
            items.append(
                {
                    "name": name,
                    "is_dir": is_dir,
                    "size": 0 if is_dir else int(size_raw or 0),
                    "mtime": None,
                }
            )
        return items
    finally:
        try:
            ftp.quit()
        except Exception:  # noqa: BLE001
            ftp.close()


def ftplib_error_perm():
    import ftplib

    return ftplib.error_perm


def _entries_gs(bundle: dict[str, Any], target: dict[str, Any], path: str):
    sa_json = bundle.get("secret") or ""
    bucket_name = target["host"]
    if not bucket_name:
        raise RemoteAccessError("GS 数据源缺少 bucket（host 字段）")
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RemoteAccessError("未安装 google-cloud-storage 依赖") from exc
    try:
        info = json.loads(sa_json) if sa_json else {}
    except json.JSONDecodeError as exc:
        raise RemoteAccessError("GS service account JSON 无效") from exc
    try:
        client = storage.Client.from_service_account_info(
            info, project=info.get("project_id")
        )
        bucket = client.bucket(bucket_name)
        prefix = (path or "/").strip("/")
        iterator = bucket.list_blobs(prefix=prefix, delimiter="/")
        items: list[dict[str, Any]] = []
        for blob in iterator:
            name = blob.name[len(prefix) :].strip("/") if prefix else blob.name
            if not name or "/" in name:
                continue
            items.append(
                {
                    "name": name,
                    "is_dir": False,
                    "size": int(blob.size or 0),
                    "mtime": None,
                }
            )
        for dir_prefix in iterator.prefixes:
            name = dir_prefix[len(prefix) :].strip("/")
            if name:
                items.append({"name": name, "is_dir": True, "size": 0, "mtime": None})
        return items
    except RemoteAccessError:
        raise
    except Exception as exc:  # noqa: BLE001
        name_type = type(exc).__name__
        if "Auth" in name_type or "Unauthorized" in str(exc):
            raise RemoteAccessAuthError("GCS 认证失败") from exc
        raise RemoteAccessNetworkError(f"GCS 访问失败（bucket={bucket_name}）") from exc


def _entries_filebrowser(bundle: dict[str, Any], target: dict[str, Any], path: str):
    url = target["url"] or target["host"]
    if not url:
        raise RemoteAccessError("FileBrowser 数据源缺少 base URL")
    try:
        client = FileBrowserClient(
            url, bundle.get("username") or "", bundle.get("secret") or ""
        )
        return client.list_dir(path)
    except FileBrowserAuthError as exc:
        raise RemoteAccessAuthError(str(exc)) from exc
    except FileBrowserError as exc:
        raise RemoteAccessNetworkError(str(exc)) from exc


def _local_base(bundle: dict[str, Any], target: dict[str, Any]) -> Path:
    extra = bundle.get("extra") or {}
    base = extra.get("base_path") or target["host"] or target["url"]
    if not base:
        raise RemoteAccessError("缺少 UNC/挂载点路径（host 或 extra.base_path）")
    return Path(base)


def _entries_local(bundle: dict[str, Any], target: dict[str, Any], path: str):
    base = _local_base(bundle, target)
    full = (base / (path or "/").strip("/")).resolve()
    base_resolved = base.resolve()
    if base_resolved != full and base_resolved not in full.parents:
        raise RemoteAccessError("路径越出挂载根目录")
    if not full.exists():
        raise RemoteAccessError(f"路径不存在: {path}")
    if not full.is_dir():
        raise RemoteAccessError(f"不是目录: {path}")
    try:
        items: list[dict[str, Any]] = []
        for child in full.iterdir():
            try:
                st = child.stat()
            except OSError:
                continue
            items.append(
                {
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": 0 if child.is_dir() else int(st.st_size),
                    "mtime": st.st_mtime,
                }
            )
        return items
    except OSError as exc:
        raise RemoteAccessNetworkError(f"挂载点访问失败（{base}）") from exc


_HTML_LINK_RE = re.compile(r'<a\s[^>]*href=["\']([^"\'#?]+)["\']', re.IGNORECASE)


def _entries_http(bundle: dict[str, Any], target: dict[str, Any], path: str):
    base_url = (target["url"] or target["host"]).rstrip("/")
    if not base_url:
        raise RemoteAccessError("HTTP 数据源缺少 base URL")
    rel = quote((path or "/").strip("/"))
    url = f"{base_url}/{rel}" if rel else f"{base_url}/"
    try:
        with safe_urlopen(
            url,
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": "CGDA-Backend/1.0"},
            allow_private=True,
        ) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read(2 * 1024 * 1024)
    except Exception as exc:  # noqa: BLE001 — 网络/超时类
        raise RemoteAccessNetworkError("HTTP 目录访问失败（无法连接）") from exc
    if "text/html" not in content_type.lower():
        raise RemoteAccessError("目标不是 HTML 目录索引（仅支持目录型 http 源浏览）")
    html = body.decode("utf-8", errors="replace")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _HTML_LINK_RE.finditer(html):
        href = match.group(1)
        if href.startswith(("/", "http:", "https:", "mailto:", "javascript:")):
            if href.startswith("/"):
                continue
            continue
        name = unquote(href.rstrip("/").split("/")[-1])
        if not name or name in {".", ".."} or name in seen:
            continue
        seen.add(name)
        items.append(
            {"name": name, "is_dir": href.endswith("/"), "size": 0, "mtime": None}
        )
    if not items:
        raise RemoteAccessError("目录索引解析不到条目（页面可能不是目录列表）")
    return items


# ── 协议实现：搜索 ────────────────────────────────────────────────────────────


def _recursive_search(
    list_fn, root: str, query: str, max_results: int
) -> list[dict[str, Any]]:
    """受限深度递归名称匹配搜索（文件系统类源）。"""
    pattern = query.lower()
    results: list[dict[str, Any]] = []
    stack: list[tuple[str, int]] = [(root, 0)]
    visited = 0
    while stack and len(results) < max_results:
        current, depth = stack.pop()
        if depth > SEARCH_MAX_DEPTH:
            continue
        try:
            entries = list_fn(current)
        except RemoteAccessError:
            continue
        visited += 1
        for item in entries:
            if pattern in item["name"].lower():
                results.append(item)
                if len(results) >= max_results:
                    break
            if item["is_dir"]:
                stack.append(
                    (
                        posixpath.join(current, item["name"]).replace("\\", "/"),
                        depth + 1,
                    )
                )
    logger.debug("recursive search visited %d dirs for %r", visited, query)
    return results


def _sftp_items(entries: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in entries:
        mode = entry.st_mode or 0
        is_dir = stat_module.S_ISDIR(mode)
        items.append(
            {
                "name": entry.filename,
                "is_dir": is_dir,
                "size": 0 if is_dir else int(entry.st_size or 0),
                "mtime": float(entry.st_mtime) if entry.st_mtime else None,
            }
        )
    return items


def _search_sftp(
    bundle: dict[str, Any], target: dict[str, Any], query: str, max_results: int
) -> list[dict[str, Any]]:
    """单连接递归搜索：整个搜索复用一次 SSH/SFTP 会话（避免每目录重握手）。"""
    import paramiko

    host = target["host"]
    if not host:
        raise RemoteAccessError("缺少主机地址")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict[str, Any] = {
        "hostname": host,
        "port": int(target["port"] or 22),
        "username": bundle.get("username") or "",
        "timeout": DEFAULT_TIMEOUT,
        "look_for_keys": False,
        "allow_agent": False,
    }
    pem = bundle.get("private_key_pem")
    if pem:
        kwargs["pkey"] = _load_paramiko_pkey(pem)
    elif bundle.get("secret"):
        kwargs["password"] = bundle["secret"]
    try:
        client.connect(**kwargs)
        sftp = client.open_sftp()
        try:
            return _recursive_search(
                lambda p: _sftp_items(sftp.listdir_attr(p)), "/", query, max_results
            )
        finally:
            sftp.close()
    except paramiko.AuthenticationException as exc:
        raise RemoteAccessAuthError("SSH/SFTP 认证失败") from exc
    except RemoteAccessError:
        raise
    except Exception as exc:  # noqa: BLE001 — 网络/超时类
        raise RemoteAccessNetworkError(f"SSH/SFTP 连接失败（{host}）") from exc
    finally:
        client.close()


def _search_ftp(
    bundle: dict[str, Any],
    target: dict[str, Any],
    query: str,
    max_results: int,
    scheme: str,
) -> list[dict[str, Any]]:
    """单连接递归搜索：整个搜索复用一次 FTP 会话。"""

    def list_fn(path: str) -> list[dict[str, Any]]:
        try:
            mlsd = list(ftp.mlsd(path))
        except ftplib_error_perm() as exc:
            raise RemoteAccessError(f"FTP 目录不可访问: {exc}") from exc
        items: list[dict[str, Any]] = []
        for name, facts in mlsd:
            if name in {".", ".."}:
                continue
            is_dir = facts.get("type") == "dir"
            items.append(
                {
                    "name": name,
                    "is_dir": is_dir,
                    "size": 0 if is_dir else int(facts.get("size") or 0),
                    "mtime": None,
                }
            )
        return items

    ftp = _ftp_connect(bundle, target, scheme)
    try:
        return _recursive_search(list_fn, "/", query, max_results)
    finally:
        try:
            ftp.quit()
        except Exception:  # noqa: BLE001
            ftp.close()


def _search_filebrowser(
    bundle: dict[str, Any], target: dict[str, Any], query: str, max_results: int
):
    url = target["url"] or target["host"]
    if not url:
        raise RemoteAccessError("FileBrowser 数据源缺少 base URL")
    try:
        client = FileBrowserClient(
            url, bundle.get("username") or "", bundle.get("secret") or ""
        )
        return client.search(query, max_results=max_results)
    except FileBrowserAuthError as exc:
        raise RemoteAccessAuthError(str(exc)) from exc
    except FileBrowserError as exc:
        raise RemoteAccessNetworkError(str(exc)) from exc


def _search_gs(
    bundle: dict[str, Any], target: dict[str, Any], query: str, max_results: int
):
    sa_json = bundle.get("secret") or ""
    bucket_name = target["host"]
    if not bucket_name:
        raise RemoteAccessError("GS 数据源缺少 bucket（host 字段）")
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RemoteAccessError("未安装 google-cloud-storage 依赖") from exc
    try:
        info = json.loads(sa_json) if sa_json else {}
        client = storage.Client.from_service_account_info(
            info, project=info.get("project_id")
        )
        bucket = client.bucket(bucket_name)
        pattern = query.lower()
        results: list[dict[str, Any]] = []
        for blob in bucket.list_blobs():
            if pattern in blob.name.lower():
                results.append(
                    {
                        "name": blob.name,
                        "is_dir": False,
                        "size": int(blob.size or 0),
                        "mtime": None,
                        "path": blob.name,
                    }
                )
                if len(results) >= max_results:
                    break
        return results
    except Exception as exc:  # noqa: BLE001
        if "Auth" in type(exc).__name__:
            raise RemoteAccessAuthError("GCS 认证失败") from exc
        raise RemoteAccessNetworkError(f"GCS 访问失败（bucket={bucket_name}）") from exc


def _search_local(
    bundle: dict[str, Any], target: dict[str, Any], query: str, max_results: int
):
    base = _local_base(bundle, target)
    base_resolved = base.resolve()
    pattern = query.lower()
    results: list[dict[str, Any]] = []
    stack: list[tuple[Path, int]] = [(base, 0)]
    while stack and len(results) < max_results:
        current, depth = stack.pop()
        if depth > SEARCH_MAX_DEPTH:
            continue
        try:
            # resolve 防符号链接逃逸：每层目录必须仍位于挂载根内
            current_resolved = current.resolve()
            if base_resolved != current_resolved and (
                base_resolved not in current_resolved.parents
            ):
                continue
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            try:
                # 不跟随符号链接判定目录；符号链接目录不入栈（防越根）
                st = child.stat(follow_symlinks=False)
            except OSError:
                continue
            if pattern in child.name.lower():
                results.append(
                    {
                        "name": child.name,
                        # lstat 判定目录（Path.is_dir(follow_symlinks=) 需 3.13）
                        "is_dir": stat_module.S_ISDIR(st.st_mode),
                        "size": int(st.st_size),
                        "mtime": st.st_mtime,
                        "path": str(child.relative_to(base)).replace("\\", "/"),
                    }
                )
                if len(results) >= max_results:
                    break
            if stat_module.S_ISDIR(st.st_mode):
                stack.append((child, depth + 1))
    return results


# ── 公共入口 ──────────────────────────────────────────────────────────────────


def browse_profile(profile_id: str, path: str = "/") -> dict[str, Any]:
    """浏览一个存储 profile 的目录，返回 {profile_id, protocol, path, via, items}。"""
    bundle = _get_bundle(profile_id)
    protocol = str(bundle.get("protocol") or "").lower()
    if protocol not in PROTOCOLS_BROWSABLE:
        raise RemoteAccessError(f"该协议不支持目录浏览: {protocol}")
    safe_path = normalize_remote_path(path)

    def attempt(which: str, alt: dict[str, Any] | None):
        target = _effective_target(bundle, which, alt)
        if protocol in {"sftp", "ssh"}:
            return _entries_sftp(bundle, target, safe_path)
        if protocol == "smb":
            return _entries_smb(bundle, target, safe_path)
        if protocol in {"ftp", "ftps"}:
            return _entries_ftp(bundle, target, safe_path, protocol)
        if protocol == "gs":
            return _entries_gs(bundle, target, safe_path)
        if protocol == "filebrowser":
            return _entries_filebrowser(bundle, target, safe_path)
        if protocol in {"lan", "nfs"}:
            return _entries_local(bundle, target, safe_path)
        if protocol in {"http", "https"}:
            return _entries_http(bundle, target, safe_path)
        raise RemoteAccessError(f"协议未实现浏览: {protocol}")

    items, via = _with_failover(bundle, attempt)
    return {
        "profile_id": profile_id,
        "protocol": protocol,
        "path": safe_path,
        "via": via,
        "items": items,
    }


def search_profile(
    profile_id: str, query: str, *, max_results: int = SEARCH_MAX_RESULTS_DEFAULT
) -> dict[str, Any]:
    """在存储 profile 内按名称搜索，返回 {profile_id, protocol, query, via, items}。"""
    query = (query or "").strip()
    if not query:
        raise RemoteAccessError("搜索关键词不能为空")
    if len(query) > 256:
        raise RemoteAccessError("搜索关键词过长")
    bundle = _get_bundle(profile_id)
    protocol = str(bundle.get("protocol") or "").lower()
    if protocol not in PROTOCOLS_SEARCHABLE:
        raise RemoteAccessError(f"该协议不支持名称搜索: {protocol}")
    limit = max(1, min(int(max_results), 500))

    def attempt(which: str, alt: dict[str, Any] | None):
        target = _effective_target(bundle, which, alt)
        if protocol == "filebrowser":
            return _search_filebrowser(bundle, target, query, limit)
        if protocol in {"sftp", "ssh"}:
            return _search_sftp(bundle, target, query, limit)
        if protocol == "smb":
            share = (bundle.get("extra") or {}).get("default_share") or ""
            if not share:
                raise RemoteAccessError("SMB 数据源缺少 extra.default_share")
            return _recursive_search(
                lambda p: _entries_smb(bundle, target, p), "/", query, limit
            )
        if protocol in {"ftp", "ftps"}:
            return _search_ftp(bundle, target, query, limit, protocol)
        if protocol == "gs":
            return _search_gs(bundle, target, query, limit)
        if protocol in {"lan", "nfs"}:
            return _search_local(bundle, target, query, limit)
        raise RemoteAccessError(f"协议未实现搜索: {protocol}")

    items, via = _with_failover(bundle, attempt)
    return {
        "profile_id": profile_id,
        "protocol": protocol,
        "query": query,
        "via": via,
        "items": items,
    }
