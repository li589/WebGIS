from tempfile import TemporaryDirectory
from threading import Event, Thread
import time

import pytest

from webgis_gee.runtime.exceptions import ResourceExhaustedError
from webgis_gee.runtime.resources import (
    InMemoryResourceQuotaCoordinator,
    RedisResourceQuotaCoordinator,
    ResourceQuotaLease,
    RuntimeResourceController,
)


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiry: dict[str, int] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.expiry[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def incr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    def decr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) - 1
        self.values[key] = str(value)
        return value

    def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        self.expiry.pop(key, None)
        return 1 if existed else 0

    def expire(self, key: str, seconds: int) -> bool:
        if key not in self.values:
            return False
        self.expiry[key] = seconds
        return True


class HeartbeatQuotaCoordinator(InMemoryResourceQuotaCoordinator):
    def __init__(self) -> None:
        super().__init__()
        self.renew_count = 0
        self.renewed_event = Event()

    def acquire(self, *, resource_name: str, owner_id: str, limit: int) -> ResourceQuotaLease:
        lease = super().acquire(resource_name=resource_name, owner_id=owner_id, limit=limit)
        return ResourceQuotaLease(
            resource_name=lease.resource_name,
            owner_id=lease.owner_id,
            token="heartbeat-token",
        )

    def renew(self, lease: ResourceQuotaLease) -> bool:
        self.renew_count += 1
        self.renewed_event.set()
        return True

    def heartbeat_interval_seconds(self) -> float | None:
        return 0.01


class FailingHeartbeatQuotaCoordinator(InMemoryResourceQuotaCoordinator):
    def __init__(self) -> None:
        super().__init__()
        self.renewed_event = Event()

    def acquire(self, *, resource_name: str, owner_id: str, limit: int) -> ResourceQuotaLease:
        lease = super().acquire(resource_name=resource_name, owner_id=owner_id, limit=limit)
        return ResourceQuotaLease(
            resource_name=lease.resource_name,
            owner_id=lease.owner_id,
            token="failing-heartbeat-token",
        )

    def renew(self, lease: ResourceQuotaLease) -> bool:
        self.renewed_event.set()
        return False

    def heartbeat_interval_seconds(self) -> float | None:
        return 0.01


class FailOnceHeartbeatQuotaCoordinator(InMemoryResourceQuotaCoordinator):
    def __init__(self) -> None:
        super().__init__()
        self.renewed_event = Event()
        self._should_fail_next_renew = True

    def acquire(self, *, resource_name: str, owner_id: str, limit: int) -> ResourceQuotaLease:
        lease = super().acquire(resource_name=resource_name, owner_id=owner_id, limit=limit)
        return ResourceQuotaLease(
            resource_name=lease.resource_name,
            owner_id=lease.owner_id,
            token=f"fail-once-token-{owner_id}",
        )

    def renew(self, lease: ResourceQuotaLease) -> bool:
        self.renewed_event.set()
        if self._should_fail_next_renew:
            self._should_fail_next_renew = False
            return False
        return True

    def heartbeat_interval_seconds(self) -> float | None:
        return 0.01


class FailOnceRenewingRedisQuotaCoordinator(RedisResourceQuotaCoordinator):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.renewed_event = Event()
        self._should_fail_next_renew = True

    def renew(self, lease: ResourceQuotaLease) -> bool:
        self.renewed_event.set()
        if self._should_fail_next_renew:
            self._should_fail_next_renew = False
            return False
        return super().renew(lease)


def test_redis_resource_quota_coordinator_acquires_and_releases_leases() -> None:
    client = FakeRedisClient()
    coordinator = RedisResourceQuotaCoordinator(
        client=client,
        key_prefix="test_quota",
        lease_ttl_seconds=120,
    )

    lease = coordinator.acquire(
        resource_name="export",
        owner_id="worker-1",
        limit=2,
    )

    assert lease.token is not None
    assert client.get("test_quota:lease:export:worker-1") == lease.token
    assert client.get("test_quota:counter:export") == "1"
    assert client.expiry["test_quota:counter:export"] == 120

    coordinator.release(lease)

    assert client.get("test_quota:lease:export:worker-1") is None
    assert client.get("test_quota:counter:export") is None


def test_redis_resource_quota_coordinator_rejects_limit_exceeded() -> None:
    client = FakeRedisClient()
    coordinator = RedisResourceQuotaCoordinator(
        client=client,
        key_prefix="test_quota",
    )

    lease = coordinator.acquire(
        resource_name="export",
        owner_id="worker-1",
        limit=1,
    )

    with pytest.raises(ResourceExhaustedError, match="shared quota reached"):
        coordinator.acquire(
            resource_name="export",
            owner_id="worker-2",
            limit=1,
        )

    assert client.get("test_quota:counter:export") == "1"
    coordinator.release(lease)


def test_redis_resource_quota_coordinator_renews_lease_ttl() -> None:
    client = FakeRedisClient()
    coordinator = RedisResourceQuotaCoordinator(
        client=client,
        key_prefix="test_quota",
        lease_ttl_seconds=120,
        renew_interval_seconds=30,
    )

    lease = coordinator.acquire(
        resource_name="export",
        owner_id="worker-1",
        limit=1,
    )
    client.expiry["test_quota:lease:export:worker-1"] = 5
    client.expiry["test_quota:counter:export"] = 5

    renewed = coordinator.renew(lease)

    assert renewed is True
    assert client.expiry["test_quota:lease:export:worker-1"] == 120
    assert client.expiry["test_quota:counter:export"] == 120


def test_redis_resource_quota_coordinator_shares_recovery_window_across_instances() -> None:
    client = FakeRedisClient()
    coordinator_a = FailOnceRenewingRedisQuotaCoordinator(
        client=client,
        key_prefix="test_quota",
        lease_ttl_seconds=120,
        renew_interval_seconds=0.01,
    )
    coordinator_b = RedisResourceQuotaCoordinator(
        client=client,
        key_prefix="test_quota",
        lease_ttl_seconds=120,
        renew_interval_seconds=0.01,
    )
    controller_a = RuntimeResourceController(
        max_parallel_exports=2,
        max_parallel_uploads=1,
        max_parallel_downloads=1,
        max_local_write_bytes=1024,
        quota_coordinator=coordinator_a,
        shared_quota_recovery_cooldown_seconds=0.08,
    )
    controller_b = RuntimeResourceController(
        max_parallel_exports=2,
        max_parallel_uploads=1,
        max_parallel_downloads=1,
        max_local_write_bytes=1024,
        quota_coordinator=coordinator_b,
        shared_quota_recovery_cooldown_seconds=0.08,
    )

    with controller_a.export_slot(run_id="worker-a"):
        assert coordinator_a.renewed_event.wait(timeout=0.2)
        time.sleep(0.02)

    with pytest.raises(ResourceExhaustedError, match="shared quota recovery in progress"):
        with controller_b.export_slot(run_id="worker-b"):
            pass

    time.sleep(0.1)

    with controller_b.export_slot(run_id="worker-c"):
        pass

    assert controller_a.snapshot()["degraded_shared_quotas"] == {}
    assert controller_b.snapshot()["degraded_shared_quotas"] == {}


def test_runtime_resource_controller_uses_redis_quota_coordinator_across_instances() -> None:
    client = FakeRedisClient()
    coordinator = RedisResourceQuotaCoordinator(
        client=client,
        key_prefix="test_quota",
    )
    controller_a = RuntimeResourceController(
        max_parallel_exports=1,
        max_parallel_uploads=1,
        max_parallel_downloads=1,
        max_local_write_bytes=1024,
        quota_coordinator=coordinator,
    )
    controller_b = RuntimeResourceController(
        max_parallel_exports=1,
        max_parallel_uploads=1,
        max_parallel_downloads=1,
        max_local_write_bytes=1024,
        quota_coordinator=coordinator,
    )

    with controller_a.export_slot(run_id="worker-a"):
        snapshot = controller_a.snapshot()
        assert snapshot["quota_coordinator"]["type"] == "RedisResourceQuotaCoordinator"
        with pytest.raises(ResourceExhaustedError, match="shared quota reached"):
            with controller_b.export_slot(run_id="worker-b"):
                pass


def test_runtime_resource_controller_heartbeats_shared_lease() -> None:
    coordinator = HeartbeatQuotaCoordinator()
    controller = RuntimeResourceController(
        max_parallel_exports=1,
        max_parallel_uploads=1,
        max_parallel_downloads=1,
        max_local_write_bytes=1024,
        quota_coordinator=coordinator,
    )

    with controller.export_slot(run_id="worker-a"):
        assert coordinator.renewed_event.wait(timeout=0.2)
        time.sleep(0.02)

    assert coordinator.renew_count >= 1


def test_runtime_resource_controller_enters_recovery_cooldown_after_heartbeat_failure() -> None:
    coordinator = FailingHeartbeatQuotaCoordinator()
    controller = RuntimeResourceController(
        max_parallel_exports=1,
        max_parallel_uploads=1,
        max_parallel_downloads=1,
        max_local_write_bytes=1024,
        quota_coordinator=coordinator,
        shared_quota_recovery_cooldown_seconds=0.05,
    )

    with controller.export_slot(run_id="worker-a"):
        assert coordinator.renewed_event.wait(timeout=0.2)
        time.sleep(0.02)

    degraded_snapshot = controller.snapshot()
    assert "export" in degraded_snapshot["degraded_shared_quotas"]

    with pytest.raises(ResourceExhaustedError, match="shared quota recovery in progress"):
        with controller.export_slot(run_id="worker-b"):
            pass

    time.sleep(0.06)

    with controller.export_slot(run_id="worker-c"):
        pass

    recovered_snapshot = controller.snapshot()
    assert recovered_snapshot["degraded_shared_quotas"] == {}


def test_runtime_resource_controller_blocks_concurrent_contention_during_recovery_window() -> None:
    coordinator = FailOnceHeartbeatQuotaCoordinator()
    controller = RuntimeResourceController(
        max_parallel_exports=2,
        max_parallel_uploads=1,
        max_parallel_downloads=1,
        max_local_write_bytes=1024,
        quota_coordinator=coordinator,
        shared_quota_recovery_cooldown_seconds=0.08,
    )

    with controller.export_slot(run_id="worker-a"):
        assert coordinator.renewed_event.wait(timeout=0.2)
        time.sleep(0.02)

    blocked_attempts: list[str] = []
    start_event = Event()

    def contender(run_id: str) -> None:
        start_event.wait(timeout=0.2)
        try:
            with controller.export_slot(run_id=run_id):
                blocked_attempts.append("acquired")
        except ResourceExhaustedError as exc:
            blocked_attempts.append(str(exc))

    contender_threads = [
        Thread(target=contender, args=(f"blocked-{index}",), daemon=True)
        for index in range(3)
    ]
    for thread in contender_threads:
        thread.start()
    start_event.set()
    for thread in contender_threads:
        thread.join(timeout=0.2)

    degraded_snapshot = controller.snapshot()
    assert len(blocked_attempts) == 3
    assert all("shared quota recovery in progress" in result for result in blocked_attempts)
    assert "export" in degraded_snapshot["degraded_shared_quotas"]
    assert degraded_snapshot["active_export_slots"] == 0

    time.sleep(0.1)

    recovered_attempts: list[str] = []
    recovered_start_event = Event()
    recovered_release_event = Event()

    def recovered_contender(run_id: str) -> None:
        recovered_start_event.wait(timeout=0.2)
        try:
            with controller.export_slot(run_id=run_id):
                recovered_attempts.append("acquired")
                recovered_release_event.wait(timeout=0.05)
        except ResourceExhaustedError as exc:
            recovered_attempts.append(str(exc))

    recovered_threads = [
        Thread(target=recovered_contender, args=(f"recovered-{index}",), daemon=True)
        for index in range(2)
    ]
    for thread in recovered_threads:
        thread.start()
    recovered_start_event.set()
    time.sleep(0.02)
    recovered_release_event.set()
    for thread in recovered_threads:
        thread.join(timeout=0.2)

    recovered_snapshot = controller.snapshot()
    assert recovered_attempts == ["acquired", "acquired"]
    assert recovered_snapshot["degraded_shared_quotas"] == {}
    assert recovered_snapshot["active_export_slots"] == 0


def test_runtime_resource_controller_scopes_temp_dirs_and_local_write_budget() -> None:
    coordinator = InMemoryResourceQuotaCoordinator()
    controller = RuntimeResourceController(
        max_parallel_exports=1,
        max_parallel_uploads=1,
        max_parallel_downloads=1,
        max_local_write_bytes=16,
        quota_coordinator=coordinator,
    )

    with TemporaryDirectory() as root:
        with controller.workflow_scope(run_id="run-1", temp_root=root) as temp_dir:
            assert temp_dir.endswith("run-1")
            with controller.local_write(run_id="run-1", byte_count=8):
                assert controller.snapshot()["active_local_write_bytes"] == 8
            with pytest.raises(ResourceExhaustedError, match="local storage write budget exceeded"):
                with controller.local_write(run_id="run-1", byte_count=9):
                    pass
            assert controller.snapshot()["active_temp_dirs"] == 1
    assert controller.snapshot()["active_temp_dirs"] == 0
    assert controller.snapshot()["active_local_write_bytes"] == 0
    assert controller.snapshot()["active_local_write_bytes"] == 0
