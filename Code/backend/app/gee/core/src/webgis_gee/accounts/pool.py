from __future__ import annotations

from threading import RLock
from typing import Iterable

from webgis_gee.domain.enums import AccountState
from webgis_gee.domain.models import AccountLease
from webgis_gee.runtime.exceptions import AccountUnavailableError


class InMemoryAccountPool:
    """Minimal account pool implementation for early-stage runtime integration."""

    def __init__(self, account_ids: Iterable[str]) -> None:
        self._leases = {account_id: AccountLease(account_id=account_id) for account_id in account_ids}
        self._lock = RLock()

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

    def health_report(self) -> dict[str, object]:
        leases = self.snapshot()
        return {
            "total_accounts": len(leases),
            "available_accounts": len([lease for lease in leases if lease.is_available()]),
            "cooldown_accounts": len([lease for lease in leases if lease.state == AccountState.COOLDOWN]),
            "disabled_accounts": len([lease for lease in leases if lease.state == AccountState.DISABLED]),
            "accounts": [
                {
                    "account_id": lease.account_id,
                    "state": lease.state.value,
                    "health_score": lease.health_score,
                    "success_count": lease.success_count,
                    "failure_count": lease.failure_count,
                    "last_error": lease.last_error,
                }
                for lease in leases
            ],
        }


# 保持别名向后兼容
MemoryAccountPool = InMemoryAccountPool
