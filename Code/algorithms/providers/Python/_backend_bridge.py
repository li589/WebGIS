"""算法包 ↔ 后端 app.services 的可选边界桥（P3 分层收口，2026-08-23）。

设计意图（审查报告"algorithms 4 处 lazy 导入 app.services 灰区"的收口）：
算法包原则上零依赖后端 ``app.*``（可独立打包部署到算力集群）；但当其运行
在后端进程内时，可复用后端的凭据解析与远程存储仓库。此前这类"可选后端
能力"以 lazy import 散落在 4 处业务代码中，灰区不可见、降级语义不一致。

本模块是**唯一的**算法包→后端边界：
- 集中声明全部可选后端能力（remote auth / portal credentials / remote storage）
- 统一"后端不可用"降级语义（返回 None/空 dict 或抛带指引的 ValueError）
- 运行于后端外（如独立算力集群）时，这些函数返回缺省值，算法包其余功能不受影响

新增后端能力借用必须加在本模块，禁止业务代码直接 ``from app.services...``。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _backend_available() -> bool:
    """探测后端 app 包是否可导入（独立部署时为 False）。"""
    try:
        import app  # noqa: F401

        return True
    except ImportError:
        return False


def resolve_remote_credentials(uri: str) -> dict[str, Any] | None:
    """经后端 remote_auth_resolver 解析远程数据源凭据。

    Returns:
        解析出的认证元数据 dict；后端不可用或解析失败时返回 None
        （调用方回退到 datasource metadata 显式 auth 字段或 ?cred= profile）。
    """
    try:
        from app.services.remote_auth_resolver import resolve_remote_auth

        return resolve_remote_auth(uri)
    except ImportError:
        return None
    except Exception:
        # 保留根因可见（凭据 profile 配置错误/解密失败等）——
        # 回顾审查 2026-08-23：静默吞异常会让故障排查只看到通用错误
        logger.warning(
            "backend_bridge: remote auth resolve failed for %s", uri, exc_info=True
        )
        return None


def get_portal_credentials() -> dict[str, Any] | None:
    """经后端 config_service 解析门户凭据（NSMC 等）。

    Returns:
        门户凭据 dict；后端不可用/未配置/解析失败时返回 None（调用方回退
        到请求上下文已内联的 portal_credentials）。
    """
    try:
        from app.services.config_service import get_portal_credentials_runtime

        resolved = get_portal_credentials_runtime()
        return resolved if isinstance(resolved, dict) else None
    except ImportError:
        return None
    except Exception:
        logger.warning(
            "backend_bridge: portal credentials resolve failed", exc_info=True
        )
        return None


def get_remote_storage_repository() -> Any:
    """获取后端远程存储 profile 仓库（凭据懒加载，不入作业负载）。

    Raises:
        ValueError: 后端不可用（独立部署环境无此能力）。
    """
    try:
        from app.services.config_remote_storage import get_remote_storage_repository

        return get_remote_storage_repository()
    except ImportError as exc:
        raise ValueError(
            "远程存储 profile 解析需要后端运行环境（app.services 不可用）。"
            "独立部署场景请在 datasource metadata 中显式提供凭据。"
        ) from exc
