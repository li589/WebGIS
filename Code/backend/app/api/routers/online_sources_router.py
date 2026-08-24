"""统一在线源凭证状态 API（图层平台子系统 P2-3）。

GET /config/online-sources —— 聚合各在线数据源的凭证就绪状态：
- GEE：加密 SQLite 账号池（账号数 / 启用数 / 最近测试结果）
- SSH HPC 隧道 / NASA Earthdata / FileBrowser：.env 环境变量凭证（只报配置布尔）

设计约束：
- 只读诊断面：不迁移凭证存储，不改写任何密钥
- 永不回显明文凭证值，仅返回「字段是否已配置」布尔
- 管理员可见（require_config_read_access，与 GEE 配置面同权限级别）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.api.deps import require_config_read_access
from app.core.config import settings
from shared.contracts.api_contracts import (
    OnlineSourceCredentialStatus,
    OnlineSourcesResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/config/online-sources",
    tags=["config"],
    dependencies=[Depends(require_config_read_access)],
)


def _gee_pool_status() -> OnlineSourceCredentialStatus:
    """GEE 账号池：账号数 / 启用数 / 最近测试结果（读取失败按未配置降级）。"""
    try:
        from app.services.config_gee_accounts import list_gee_accounts

        accounts = list_gee_accounts() or []
        enabled = [a for a in accounts if a.get("enabled")]
        last_tested = None
        last_status = None
        for account in accounts:
            tested_at = account.get("last_tested_at")
            if tested_at and (last_tested is None or tested_at > last_tested):
                last_tested = tested_at
                last_status = account.get("last_test_status")
        return OnlineSourceCredentialStatus(
            source_id="gee",
            display_name="Google Earth Engine 账号池",
            kind="account_pool",
            configured=bool(enabled),
            account_count=len(accounts),
            enabled_count=len(enabled),
            last_tested_at=last_tested,
            last_test_status=last_status,
            detail=(
                f"{len(enabled)}/{len(accounts)} 账号启用"
                if accounts
                else "账号池为空：请在设置中添加 GEE 服务账号"
            ),
        )
    except Exception as exc:  # noqa: BLE001 - 诊断面按未配置降级，不炸接口
        logger.warning("online-sources: GEE 账号池读取失败: %s", exc)
        return OnlineSourceCredentialStatus(
            source_id="gee",
            display_name="Google Earth Engine 账号池",
            kind="account_pool",
            configured=False,
            detail="账号池读取失败（GEE 模块不可用或数据库未初始化）",
        )


def _env_credential_status(
    source_id: str,
    display_name: str,
    required_fields: dict[str, bool],
    essential: set[str],
) -> OnlineSourceCredentialStatus:
    """env 凭证类：字段配置布尔 + 必需字段齐全判定。"""
    missing = [name for name in essential if not required_fields.get(name)]
    configured = not missing
    if configured:
        optional_missing = [
            name for name, ok in required_fields.items() if not ok and name not in essential
        ]
        detail = "凭证已配置" + (
            f"（可选字段未配置：{'、'.join(optional_missing)}）" if optional_missing else ""
        )
    else:
        detail = f"未配置：缺少 {'、'.join(missing)}（.env / 设置界面配置）"
    return OnlineSourceCredentialStatus(
        source_id=source_id,
        display_name=display_name,
        kind="env_credential",
        configured=configured,
        detail=detail,
        fields=required_fields,
    )


@router.get("", response_model=OnlineSourcesResponse)
async def list_online_source_credentials() -> OnlineSourcesResponse:
    """聚合各在线源凭证就绪状态（只报配置布尔，永不回显明文值）。"""
    sources = [
        _gee_pool_status(),
        _env_credential_status(
            source_id="ssh_hpc",
            display_name="SSH HPC 隧道",
            required_fields={
                "host": bool(settings.ssh_hpc_host),
                "user": bool(settings.ssh_hpc_user),
                "key_path": bool(settings.ssh_hpc_key_path),
            },
            essential={"host", "user", "key_path"},
        ),
        _env_credential_status(
            source_id="earthdata",
            display_name="NASA Earthdata",
            required_fields={
                "username": bool(settings.earthdata_username),
                "password": bool(settings.earthdata_password),
            },
            essential={"username", "password"},
        ),
        _env_credential_status(
            source_id="filebrowser",
            display_name="FileBrowser 远程文件",
            required_fields={
                "nas_url": bool(settings.filebrowser_nas_url),
                "win11_url": bool(settings.filebrowser_win11_url),
                "user": bool(settings.filebrowser_user),
                "password": bool(settings.filebrowser_password),
            },
            # 任一 URL + 账号密码即可用（NAS 与 Win11 二选一）
            essential={"user", "password"},
        ),
    ]
    return OnlineSourcesResponse(sources=sources, count=len(sources))
