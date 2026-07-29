"""远程文件浏览 API

提供前端 SSH/SFTP/FileBrowser 远程目录浏览能力，供下载节点参数 UI 使用。

端点：
- GET /api/remote/servers    列出可用服务器配置（不含密码/密钥）
- GET /api/remote/list       列出远程目录内容
- GET /api/remote/test       测试远程服务器连接
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/remote", tags=["remote-browser"])

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
        return {
            "server_type": "filebrowser",
            "url": settings.filebrowser_win11_url,
            "username": settings.filebrowser_user,
            "password": settings.filebrowser_password,
        }
    if server == "nas":
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
                items = _sftp_list_dir(sftp, path)
            finally:
                sftp.close()
                ssh_client.close()
            return {
                "server": server,
                "path": path,
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
            items = _filebrowser_list_dir(cfg["url"], token, path)
            return {
                "server": server,
                "path": path,
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
            "Remote list failed: server=%s path=%s err=%s", server, path, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Remote directory listing failed: {exc}",
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
        return {
            "ok": False,
            "server": server,
            "error": str(exc),
            "latency_ms": latency_ms,
        }
