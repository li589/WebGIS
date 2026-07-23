from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Iterable, Optional

from webgis_gee.domain.enums import AccountState
from webgis_gee.domain.models import AccountLease
from webgis_gee.runtime.exceptions import AccountUnavailableError


@dataclass
class AccountConfig:
    """账号配置：用于向账号池注入凭证化的账号。

    向后兼容：InMemoryAccountPool 也接受 Iterable[str]（只有 account_id，credentials=None）。
    """

    account_id: str
    credentials: Any | None = None
    project_id: Optional[str] = None
    account_type: str = "service_account"
    display_name: Optional[str] = None


def _normalize_accounts(
    accounts: "Iterable[AccountConfig | str] | None",
) -> list[AccountConfig]:
    """把 Iterable[str] / Iterable[AccountConfig] 统一成 list[AccountConfig]。"""
    if accounts is None:
        return []
    result: list[AccountConfig] = []
    for item in accounts:
        if isinstance(item, AccountConfig):
            result.append(item)
        elif isinstance(item, str):
            result.append(AccountConfig(account_id=item))
        else:
            raise TypeError(
                f"Unsupported account entry type: {type(item).__name__}; "
                "expected AccountConfig or str"
            )
    return result


class InMemoryAccountPool:
    """Account pool implementation supporting credential-backed accounts.

    向后兼容：构造函数接受 ``Iterable[str]``（旧用法，credentials=None）或
    ``Iterable[AccountConfig]``（新用法，携带凭证）。
    """

    def __init__(self, accounts: "Iterable[AccountConfig | str] | None" = None) -> None:
        # 兼容旧签名 InMemoryAccountPool(account_ids: Iterable[str]) —— 位置参数即可
        self._configs: dict[str, AccountConfig] = {}
        self._leases: dict[str, AccountLease] = {}
        for cfg in _normalize_accounts(accounts):
            self._configs[cfg.account_id] = cfg
            self._leases[cfg.account_id] = self._build_lease(cfg)
        self._lock = RLock()

    def _build_lease(self, cfg: AccountConfig) -> AccountLease:
        return AccountLease(
            account_id=cfg.account_id,
            credentials=cfg.credentials,
            project_id=cfg.project_id,
            account_type=cfg.account_type,
            display_name=cfg.display_name,
        )

    def acquire(self) -> AccountLease:
        with self._lock:
            for lease in self._leases.values():
                if lease.is_available():
                    lease.mark_leased()
                    return lease
        raise AccountUnavailableError("no available gee account")

    def release(self, account_id: str) -> None:
        with self._lock:
            self._leases[account_id].mark_success()

    def cooldown(self, account_id: str, seconds: int, reason: str) -> None:
        with self._lock:
            self._leases[account_id].mark_cooldown(seconds=seconds, reason=reason)

    def mark_failure(self, account_id: str, seconds: int, reason: str) -> None:
        self.cooldown(account_id=account_id, seconds=seconds, reason=reason)

    def get(self, account_id: str) -> AccountLease:
        with self._lock:
            return self._leases[account_id]

    def snapshot(self) -> list[AccountLease]:
        with self._lock:
            return [lease.model_copy(deep=True) for lease in self._leases.values()]

    def add_account(self, account_config: AccountConfig) -> None:
        """新增账号到池中。若 account_id 已存在则覆盖（凭证更新）。"""
        with self._lock:
            self._configs[account_config.account_id] = account_config
            self._leases[account_config.account_id] = self._build_lease(account_config)

    def remove_account(self, account_id: str) -> bool:
        """从池中移除账号，返回是否曾存在。"""
        with self._lock:
            existed = self._configs.pop(account_id, None) is not None
            self._leases.pop(account_id, None)
            return existed

    def reload_accounts(self, accounts: "Iterable[AccountConfig | str]") -> None:
        """重建账号池（清空后重新加载）。保留已存在账号的 lease 状态？不保留——重建即重置。"""
        with self._lock:
            self._configs.clear()
            self._leases.clear()
            for cfg in _normalize_accounts(accounts):
                self._configs[cfg.account_id] = cfg
                self._leases[cfg.account_id] = self._build_lease(cfg)

    def health_report(self) -> dict[str, object]:
        leases = self.snapshot()
        return {
            "total_accounts": len(leases),
            "available_accounts": len(
                [lease for lease in leases if lease.is_available()]
            ),
            "cooldown_accounts": len(
                [lease for lease in leases if lease.state == AccountState.COOLDOWN]
            ),
            "disabled_accounts": len(
                [lease for lease in leases if lease.state == AccountState.DISABLED]
            ),
            "accounts": [
                {
                    "account_id": lease.account_id,
                    "state": lease.state.value,
                    "health_score": lease.health_score,
                    "success_count": lease.success_count,
                    "failure_count": lease.failure_count,
                    "last_error": lease.last_error,
                    "account_type": lease.account_type,
                    "display_name": lease.display_name,
                    "has_credentials": lease.credentials is not None,
                    "project_id": lease.project_id,
                }
                for lease in leases
            ],
        }


# 保持别名向后兼容
MemoryAccountPool = InMemoryAccountPool
