from webgis_gee.accounts.pool import InMemoryAccountPool
from webgis_gee.domain.enums import AccountState
from webgis_gee.runtime.exceptions import AccountUnavailableError


def test_account_pool_acquire_release_cycle() -> None:
    pool = InMemoryAccountPool(["a1"])

    lease = pool.acquire()
    assert lease.account_id == "a1"
    assert lease.state == AccountState.LEASED

    pool.release("a1")

    assert pool.snapshot()[0].state == AccountState.AVAILABLE


def test_account_pool_raises_when_no_available_account() -> None:
    pool = InMemoryAccountPool(["a1"])
    pool.acquire()

    try:
        pool.acquire()
    except AccountUnavailableError:
        assert True
        return

    raise AssertionError("expected AccountUnavailableError")


def test_account_pool_cooldown_and_health_report() -> None:
    pool = InMemoryAccountPool(["a1"])

    lease = pool.acquire()
    assert lease.account_id == "a1"
    pool.mark_failure("a1", seconds=1, reason="quota")

    health = pool.health_report()

    assert health["total_accounts"] == 1
    assert health["cooldown_accounts"] == 1
    assert health["accounts"][0]["failure_count"] == 1
