"""远程下载访问控制（Phase 4：访问模式语义对齐）。

从 URI 中提取 cred_profile → 查 remote_sources 表 → 判断 access_mode：
- site_compatible：全放行（兼容模式）
- legacy + 有白名单 → 检查 path_prefix 前缀匹配
- 未管控（无条目）→ 放行

使用方式：download_remote_uri() 新增可选 policy_context 参数，
调用方在有策略上下文时传入 AccessPolicyContext。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class RemoteAccessDeniedError(Exception):
    """远程下载访问被拒绝。"""

    def __init__(self, uri: str, reason: str):
        self.uri = uri
        self.reason = reason
        super().__init__(f"Remote access denied: {uri} — {reason}")


@dataclass(frozen=True)
class AccessPolicyContext:
    """访问策略上下文：由调用方构建，传入 download_remote_uri。"""

    # remote_sources 表条目（按 cred_profile 查找）
    source_entry: dict[str, Any] | None = None
    # remote_dataset_grants 白名单条目（按 portal_id 查找）
    grants: list[dict[str, Any]] = field(default_factory=list)
    # 是否跳过校验（默认 False）
    skip_check: bool = False


def check_remote_access(uri: str, context: AccessPolicyContext) -> None:
    """校验远程 URI 是否允许访问。

    Raises:
        RemoteAccessDeniedError: 访问被拒绝时抛出
    """
    if context.skip_check:
        return

    source = context.source_entry
    if source is None:
        # 无 remote_source 条目 = 未管控 → 放行
        return

    access_mode = str(source.get("access_mode") or "legacy")

    # site_compatible：全放行
    if access_mode == "site_compatible":
        return

    # legacy 模式：检查白名单
    if not context.grants:
        # 无白名单条目 = 该 source 未被管控（migration 未覆盖）
        # → 放行（向后兼容）
        return

    # 白名单存在时检查 path_prefix 前缀匹配
    from shared.remote_sources.uri import parse_remote_uri

    parsed = parse_remote_uri(uri)
    remote_path = parsed.path.lstrip("/")  # 去掉 URI path 前导斜杠

    for grant in context.grants:
        if not grant.get("enabled", True):
            continue
        prefixes = [
            p.strip().lstrip("/")
            for p in str(grant.get("path_prefix") or "").split("\n")
            if p.strip()
        ]
        if any(remote_path.startswith(p) for p in prefixes):
            return

    # 白名单存在但未命中 → 拒绝
    raise RemoteAccessDeniedError(
        uri,
        f"remote_source '{source.get('remote_source_id')}' "
        f"is in legacy mode but no dataset grant matches path '{remote_path}'",
    )


def build_policy_context_from_uri(
    uri: str,
    *,
    source_registry=None,
    grants_registry=None,
) -> AccessPolicyContext:
    """从 URI 的 cred_profile 构建访问策略上下文。

    调用方可传入自定义 registry（测试用）；默认使用全局单例。
    """
    from shared.remote_sources.uri import parse_remote_uri

    parsed = parse_remote_uri(uri)
    profile_id = parsed.cred_profile

    if not profile_id:
        return AccessPolicyContext(skip_check=True)

    # 查 remote_sources 表
    source_entry = None
    if source_registry is not None:
        entries = source_registry.list_entries()
        source_entry = next(
            (e for e in entries if e.get("ref_id") == profile_id), None
        )

    # 查白名单（仅管控 source 才需要）
    grants = []
    if (
        source_entry
        and source_entry.get("access_mode") != "site_compatible"
        and grants_registry is not None
    ):
        grants = grants_registry.list_entries()

    return AccessPolicyContext(
        source_entry=source_entry,
        grants=grants,
    )
