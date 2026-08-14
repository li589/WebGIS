"""远程文件浏览 API

提供前端 SSH/SFTP/FileBrowser 远程目录浏览能力，供下载节点参数 UI 使用。

端点：
- GET /api/remote/servers    列出可用服务器配置（不含密码/密钥）
- GET /api/remote/list       列出远程目录内容
- GET /api/remote/test       测试远程服务器连接
"""

from __future__ import annotations

import logging
import posixpath
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_write_access
from app.core.config import settings

logger = logging.getLogger(__name__)

# 安全：远程路径校验
# - 禁止空字节 / 控制字符
# - 禁止 .. 路径遍历
# - 限制路径长度
# - 允许 Unicode 目录名（中文 NAS 路径）；不强制 ASCII 白名单
_MAX_PATH_LENGTH = 1024


def _validate_remote_path(path: str) -> str:
    """校验并规范化远程目录路径。

    Returns:
        规范化后的安全路径（统一为 ``/`` 分隔）

    Raises:
        HTTPException: 路径不合法时返回 400
    """
    if not path:
        return "/"

    if "\x00" in path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid path: null bytes are not allowed.",
        )

    if len(path) > _MAX_PATH_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid path: path too long.",
        )

    # 拒绝 C0 控制字符（保留普通空白）；允许 Unicode 文件名
    if any(ord(ch) < 32 for ch in path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid path: control characters are not allowed.",
        )

    # Windows 分隔符统一为 /，再做 posix 规范化与遍历检查
    normalized = posixpath.normpath(path.replace("\\", "/"))
    if normalized.startswith("..") or "/.." in normalized or normalized == "..":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid path: directory traversal is not allowed.",
        )

    if not normalized.startswith("/"):
        normalized = "/" + normalized

    return normalized


# 发布就绪修复（P0-2/P1-7）：远程浏览全部端点强制写权限鉴权。
# 这些端点会携带已存凭据向内/外部服务器发起真实出站连接，未鉴权可被利用做 SSRF/凭据外带。
router = APIRouter(
    prefix="/api/remote",
    tags=["remote-browser"],
    dependencies=[Depends(require_write_access)],
)

# ── 将 algorithms/providers/Python 加入 sys.path 以复用 ingest 模块 ──
_PROVIDER_ROOT = Path(settings.python_provider_root)
if str(_PROVIDER_ROOT) not in sys.path:
    sys.path.append(str(_PROVIDER_ROOT))


def _resolve_server(server: str) -> dict[str, Any]:
    """根据 server 名称解析连接参数（不含敏感凭据之外的字段）。

    Returns:
        含 server_type / url / host / port / username / password 的 dict
    """
    if server == "hpc":
        return {
            "server_type": "sftp",
            "host": settings.ssh_hpc_host,
            "port": settings.ssh_hpc_port,
            "username": settings.ssh_hpc_user,
            "key_filename": settings.ssh_hpc_key_path,
        }
    if server == "win11":
        if not settings.filebrowser_win11_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="win11 filebrowser 未配置（BACKEND_FILEBROWSER_WIN11_URL 为空）",
            )
        return {
            "server_type": "filebrowser",
            "url": settings.filebrowser_win11_url,
            "username": settings.filebrowser_user,
            "password": settings.filebrowser_password,
        }
    if server == "nas":
        if not settings.filebrowser_nas_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="nas filebrowser 未配置（BACKEND_FILEBROWSER_NAS_URL 为空）",
            )
        return {
            "server_type": "filebrowser",
            "url": settings.filebrowser_nas_url,
            "username": settings.filebrowser_user,
            "password": settings.filebrowser_password,
        }
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unknown server: {server!r} (expected: hpc, win11, nas)",
    )


@router.get("/servers")
def list_servers() -> dict[str, Any]:
    """列出可用远程服务器配置（不含敏感凭据）。"""
    servers = []
    for name in ("hpc", "win11", "nas"):
        try:
            cfg = _resolve_server(name)
        except Exception:  # noqa: BLE001
            continue
        servers.append(
            {
                "name": name,
                "server_type": cfg["server_type"],
                "host": cfg.get("host", ""),
                "port": cfg.get("port", 0),
                "username": cfg.get("username", ""),
                "url": cfg.get("url", ""),
            }
        )
    return {"servers": servers}


@router.get("/list")
def list_remote_dir(
    server: str = Query(..., description="服务器名称: hpc / win11 / nas"),
    path: str = Query("/", description="远程目录路径"),
) -> dict[str, Any]:
    """列出远程目录内容。"""
    cfg = _resolve_server(server)
    # 安全：校验路径，防止路径遍历和注入攻击
    safe_path = _validate_remote_path(path)

    try:
        if cfg["server_type"] == "sftp":
            from ingest.remote_sync import ServerConfig, _sftp_connect, _sftp_list_dir

            sc = ServerConfig(
                server_type="hpc",
                host=cfg["host"],
                port=cfg["port"],
                username=cfg["username"],
                key_filename=cfg.get("key_filename", ""),
            )
            ssh_client, sftp = _sftp_connect(sc)
            try:
                items = _sftp_list_dir(sftp, safe_path)
            finally:
                sftp.close()
                ssh_client.close()
            return {
                "server": server,
                "path": safe_path,
                "items": [
                    {"name": f.name, "isDir": f.is_dir, "size": f.size} for f in items
                ],
            }

        elif cfg["server_type"] == "filebrowser":
            from ingest.remote_sync import (
                _filebrowser_list_dir,
                filebrowser_login,
            )

            token = filebrowser_login(cfg["url"], cfg["username"], cfg["password"])
            items = _filebrowser_list_dir(cfg["url"], token, safe_path)
            return {
                "server": server,
                "path": safe_path,
                "items": [
                    {"name": f.name, "isDir": f.is_dir, "size": f.size} for f in items
                ],
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported server_type: {cfg['server_type']}",
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Remote list failed: server=%s path=%s err=%s", server, safe_path, exc
        )
        # 安全：不向客户端泄露原始异常细节，仅返回通用错误信息
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Remote directory listing failed. Check server logs for details.",
        ) from exc


@router.get("/test")
def test_remote_connection(
    server: str = Query(..., description="服务器名称: hpc / win11 / nas"),
) -> dict[str, Any]:
    """测试远程服务器连接是否可用。"""
    cfg = _resolve_server(server)
    t0 = time.monotonic()

    try:
        if cfg["server_type"] == "sftp":
            from ingest.remote_sync import ServerConfig, _sftp_connect

            sc = ServerConfig(
                server_type="hpc",
                host=cfg["host"],
                port=cfg["port"],
                username=cfg["username"],
                key_filename=cfg.get("key_filename", ""),
            )
            ssh_client, sftp = _sftp_connect(sc)
            try:
                sftp.listdir(".")
            finally:
                sftp.close()
                ssh_client.close()
            latency_ms = int((time.monotonic() - t0) * 1000)
            return {
                "ok": True,
                "server": server,
                "server_type": cfg["server_type"],
                "latency_ms": latency_ms,
            }

        elif cfg["server_type"] == "filebrowser":
            from ingest.remote_sync import filebrowser_login

            filebrowser_login(cfg["url"], cfg["username"], cfg["password"])
            latency_ms = int((time.monotonic() - t0) * 1000)
            return {
                "ok": True,
                "server": server,
                "server_type": cfg["server_type"],
                "latency_ms": latency_ms,
            }
        else:
            return {
                "ok": False,
                "server": server,
                "error": f"Unsupported server_type: {cfg['server_type']}",
            }
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.warning("Remote test failed: server=%s err=%s", server, exc)
        # 安全：不向客户端泄露原始异常细节
        return {
            "ok": False,
            "server": server,
            "error": "Connection failed. Check server logs for details.",
            "latency_ms": latency_ms,
        }
