from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
import logging
from math import ceil
from pathlib import Path
from shutil import rmtree
from threading import BoundedSemaphore, Event, Lock, Thread
from time import monotonic, time as wall_time
from typing import Iterator
from uuid import uuid4

from webgis_gee.runtime.exceptions import ResourceExhaustedError
from webgis_gee.storage.base import StorageBackend
from webgis_gee.storage.local import LocalStorageBackend


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResourceQuotaLease:
    resource_name: str
    owner_id: str
    token: str | None = None


class ResourceQuotaCoordinator(ABC):
    """Coordinates optional shared quotas across workers or processes."""

    @abstractmethod
    def acquire(self, *, resource_name: str, owner_id: str, limit: int) -> ResourceQuotaLease:
        raise NotImplementedError

    @abstractmethod
    def release(self, lease: ResourceQuotaLease) -> None:
        raise NotImplementedError

    def renew(self, lease: ResourceQuotaLease) -> bool:
        return True

    def heartbeat_interval_seconds(self) -> float | None:
        return None

    def mark_resource_degraded(
        self,
        *,
        resource_name: str,
        owner_id: str,
        cooldown_seconds: float,
    ) -> None:
        return None

    def get_retry_after_seconds(self, resource_name: str) -> float | None:
        return None

    def describe(self) -> dict[str, str]:
        return {
            "type": self.__class__.__name__,
        }


class NoopResourceQuotaCoordinator(ResourceQuotaCoordinator):
    def acquire(self, *, resource_name: str, owner_id: str, limit: int) -> ResourceQuotaLease:
        return ResourceQuotaLease(resource_name=resource_name, owner_id=owner_id)

    def release(self, lease: ResourceQuotaLease) -> None:
        return None


class InMemoryResourceQuotaCoordinator(ResourceQuotaCoordinator):
    """Shared in-memory quota coordinator for tests or single-host integration."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._active_leases_by_resource: dict[str, set[str]] = {}

    def acquire(self, *, resource_name: str, owner_id: str, limit: int) -> ResourceQuotaLease:
        with self._lock:
            active_owners = self._active_leases_by_resource.setdefault(resource_name, set())
            if len(active_owners) >= limit:
                raise ResourceExhaustedError(
                    f"shared quota reached: resource={resource_name} active={len(active_owners)} limit={limit}"
                )
            active_owners.add(owner_id)
        return ResourceQuotaLease(resource_name=resource_name, owner_id=owner_id)

    def release(self, lease: ResourceQuotaLease) -> None:
        with self._lock:
            active_owners = self._active_leases_by_resource.get(lease.resource_name)
            if active_owners is None:
                return
            active_owners.discard(lease.owner_id)
            if not active_owners:
                self._active_leases_by_resource.pop(lease.resource_name, None)

    def describe(self) -> dict[str, str | dict[str, int]]:
        with self._lock:
            active_counts = {
                resource_name: len(owners)
                for resource_name, owners in self._active_leases_by_resource.items()
            }
        return {
            "type": self.__class__.__name__,
            "active_shared_quotas": active_counts,
        }


class RedisResourceQuotaCoordinator(ResourceQuotaCoordinator):
    """Redis-backed shared quota coordinator for multi-worker deployments."""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        key_prefix: str = "webgis_gee:quota",
        lease_ttl_seconds: int = 300,
        renew_interval_seconds: float | None = None,
        client: object | None = None,
    ) -> None:
        self._key_prefix = key_prefix.rstrip(":")
        self._lease_ttl_seconds = lease_ttl_seconds
        self._renew_interval_seconds = renew_interval_seconds or max(1.0, lease_ttl_seconds / 3)
        self._client = client or self._create_client(redis_url)

    def acquire(self, *, resource_name: str, owner_id: str, limit: int) -> ResourceQuotaLease:
        lease_key = self._lease_key(resource_name, owner_id)
        counter_key = self._counter_key(resource_name)
        token = str(uuid4())
        acquired = bool(
            self._client.set(
                lease_key,
                token,
                nx=True,
                ex=self._lease_ttl_seconds,
            )
        )
        if not acquired:
            raise ResourceExhaustedError(
                f"shared quota lease already held: resource={resource_name} owner_id={owner_id}"
            )
        current_count = int(self._client.incr(counter_key))
        self._client.expire(counter_key, self._lease_ttl_seconds)
        if current_count > limit:
            self._client.decr(counter_key)
            current_token = self._decode(self._client.get(lease_key))
            if current_token == token:
                self._client.delete(lease_key)
            raise ResourceExhaustedError(
                f"shared quota reached: resource={resource_name} active={current_count - 1} limit={limit}"
            )
        return ResourceQuotaLease(
            resource_name=resource_name,
            owner_id=owner_id,
            token=token,
        )

    def release(self, lease: ResourceQuotaLease) -> None:
        lease_key = self._lease_key(lease.resource_name, lease.owner_id)
        counter_key = self._counter_key(lease.resource_name)
        current_token = self._decode(self._client.get(lease_key))
        if current_token is None:
            return
        if lease.token is not None and current_token != lease.token:
            return
        self._client.delete(lease_key)
        remaining = int(self._client.decr(counter_key))
        if remaining <= 0:
            self._client.delete(counter_key)

    def renew(self, lease: ResourceQuotaLease) -> bool:
        if lease.token is None:
            return False
        lease_key = self._lease_key(lease.resource_name, lease.owner_id)
        counter_key = self._counter_key(lease.resource_name)
        current_token = self._decode(self._client.get(lease_key))
        if current_token != lease.token:
            return False
        self._client.expire(lease_key, self._lease_ttl_seconds)
        self._client.expire(counter_key, self._lease_ttl_seconds)
        return True

    def heartbeat_interval_seconds(self) -> float | None:
        return self._renew_interval_seconds

    def describe(self) -> dict[str, str | int]:
        return {
            "type": self.__class__.__name__,
            "key_prefix": self._key_prefix,
            "lease_ttl_seconds": self._lease_ttl_seconds,
            "renew_interval_seconds": round(self._renew_interval_seconds, 3),
        }

    def _lease_key(self, resource_name: str, owner_id: str) -> str:
        return f"{self._key_prefix}:lease:{resource_name}:{owner_id}"

    def _counter_key(self, resource_name: str) -> str:
        return f"{self._key_prefix}:counter:{resource_name}"

    def _degraded_key(self, resource_name: str) -> str:
        return f"{self._key_prefix}:degraded:{resource_name}"

    def mark_resource_degraded(
        self,
        *,
        resource_name: str,
        owner_id: str,
        cooldown_seconds: float,
    ) -> None:
        if cooldown_seconds <= 0:
            return
        degraded_key = self._degraded_key(resource_name)
        deadline = wall_time() + cooldown_seconds
        self._client.set(
            degraded_key,
            str(deadline),
            ex=max(1, ceil(cooldown_seconds)),
        )

    def get_retry_after_seconds(self, resource_name: str) -> float | None:
        degraded_key = self._degraded_key(resource_name)
        deadline_value = self._decode(self._client.get(degraded_key))
        if deadline_value is None:
            return None
        try:
            remaining_seconds = float(deadline_value) - wall_time()
        except ValueError:
            self._client.delete(degraded_key)
            return None
        if remaining_seconds <= 0:
            self._client.delete(degraded_key)
            return None
        return remaining_seconds

    @staticmethod
    def _decode(value: object | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    @staticmethod
    def _create_client(redis_url: str | None) -> object:
        if not redis_url:
            raise ValueError("redis_url is required when Redis client is not provided")
        try:
            import redis
        except ImportError as exc:
            raise ImportError("redis package is required for RedisResourceQuotaCoordinator") from exc
        return redis.Redis.from_url(redis_url)


class ResourceManagedStorageBackend(StorageBackend):
    """Wraps storage operations with lightweight runtime resource checks."""

    def __init__(
        self,
        backend: StorageBackend,
        *,
        resource_controller: "RuntimeResourceController",
        run_id: str,
    ) -> None:
        self._backend = backend
        self._resource_controller = resource_controller
        self._run_id = run_id

    def put(self, path: str, content: bytes) -> str:
        with self._resource_controller.upload_slot(run_id=self._run_id):
            if isinstance(self._backend, LocalStorageBackend):
                with self._resource_controller.local_write(run_id=self._run_id, byte_count=len(content)):
                    return self._backend.put(path, content)
            return self._backend.put(path, content)

    def get(self, path: str) -> bytes:
        with self._resource_controller.download_slot(run_id=self._run_id):
            return self._backend.get(path)

    def exists(self, path: str) -> bool:
        return self._backend.exists(path)

    def delete(self, path: str) -> None:
        self._backend.delete(path)

    def list(self, prefix: str = "") -> list[str]:
        return self._backend.list(prefix)

    def stat(self, path: str) -> dict[str, int | float]:
        return self._backend.stat(path)

    def build_uri(self, path: str) -> str:
        return self._backend.build_uri(path)


class RuntimeResourceController:
    """Coordinates lightweight in-process resource limits."""

    def __init__(
        self,
        max_parallel_exports: int,
        *,
        max_parallel_uploads: int,
        max_parallel_downloads: int,
        max_local_write_bytes: int,
        quota_coordinator: ResourceQuotaCoordinator | None = None,
        shared_quota_recovery_cooldown_seconds: float = 30.0,
    ) -> None:
        self._max_parallel_exports = max_parallel_exports
        self._max_parallel_uploads = max_parallel_uploads
        self._max_parallel_downloads = max_parallel_downloads
        self._max_local_write_bytes = max_local_write_bytes
        self._quota_coordinator = quota_coordinator or NoopResourceQuotaCoordinator()
        self._shared_quota_recovery_cooldown_seconds = max(0.0, shared_quota_recovery_cooldown_seconds)
        self._export_slots = BoundedSemaphore(max_parallel_exports)
        self._upload_slots = BoundedSemaphore(max_parallel_uploads)
        self._download_slots = BoundedSemaphore(max_parallel_downloads)
        self._lock = Lock()
        self._active_export_slots = 0
        self._active_upload_slots = 0
        self._active_download_slots = 0
        self._active_temp_dirs = 0
        self._active_local_write_bytes = 0
        self._local_write_bytes_by_run: dict[str, int] = {}
        self._shared_quota_degraded_until_by_resource: dict[str, float] = {}

    @contextmanager
    def export_slot(self, *, run_id: str = "shared") -> Iterator[None]:
        with self._operation_slot(
            semaphore=self._export_slots,
            active_attr="_active_export_slots",
            limit=self._max_parallel_exports,
            resource_name="export",
            owner_id=run_id,
            error_message=f"export concurrency limit reached: max_parallel_exports={self._max_parallel_exports}",
        ):
            yield

    @contextmanager
    def upload_slot(self, *, run_id: str = "shared") -> Iterator[None]:
        with self._operation_slot(
            semaphore=self._upload_slots,
            active_attr="_active_upload_slots",
            limit=self._max_parallel_uploads,
            resource_name="upload",
            owner_id=run_id,
            error_message=f"upload concurrency limit reached: max_parallel_uploads={self._max_parallel_uploads}",
        ):
            yield

    @contextmanager
    def download_slot(self, *, run_id: str = "shared") -> Iterator[None]:
        with self._operation_slot(
            semaphore=self._download_slots,
            active_attr="_active_download_slots",
            limit=self._max_parallel_downloads,
            resource_name="download",
            owner_id=run_id,
            error_message=f"download concurrency limit reached: max_parallel_downloads={self._max_parallel_downloads}",
        ):
            yield

    @contextmanager
    def workflow_scope(self, *, run_id: str, temp_root: str) -> Iterator[str]:
        temp_root_path = Path(temp_root).resolve()
        temp_root_path.mkdir(parents=True, exist_ok=True)
        workflow_temp_dir = temp_root_path / run_id
        if workflow_temp_dir.exists():
            rmtree(workflow_temp_dir, ignore_errors=True)
        workflow_temp_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._active_temp_dirs += 1
            self._local_write_bytes_by_run.setdefault(run_id, 0)
        try:
            yield str(workflow_temp_dir)
        finally:
            rmtree(workflow_temp_dir, ignore_errors=True)
            with self._lock:
                self._active_temp_dirs = max(0, self._active_temp_dirs - 1)
                released_bytes = self._local_write_bytes_by_run.pop(run_id, 0)
                self._active_local_write_bytes = max(0, self._active_local_write_bytes - released_bytes)

    @contextmanager
    def local_write(self, *, run_id: str, byte_count: int) -> Iterator[None]:
        if byte_count < 0:
            raise ValueError("byte_count must be non-negative")
        with self._lock:
            written_bytes = self._local_write_bytes_by_run.get(run_id, 0)
            projected_bytes = written_bytes + byte_count
            if projected_bytes > self._max_local_write_bytes:
                raise ResourceExhaustedError(
                    "local storage write budget exceeded: "
                    f"run_id={run_id} requested_bytes={byte_count} "
                    f"written_bytes={written_bytes} max_local_write_bytes={self._max_local_write_bytes}"
                )
            self._local_write_bytes_by_run[run_id] = projected_bytes
            self._active_local_write_bytes += byte_count
        committed = False
        try:
            yield
            committed = True
        finally:
            if not committed:
                with self._lock:
                    current_run_bytes = self._local_write_bytes_by_run.get(run_id, 0)
                    self._local_write_bytes_by_run[run_id] = max(0, current_run_bytes - byte_count)
                    self._active_local_write_bytes = max(0, self._active_local_write_bytes - byte_count)

    @contextmanager
    def transient_local_write(self, *, byte_count: int) -> Iterator[None]:
        if byte_count < 0:
            raise ValueError("byte_count must be non-negative")
        with self._lock:
            projected_bytes = self._active_local_write_bytes + byte_count
            if projected_bytes > self._max_local_write_bytes:
                raise ResourceExhaustedError(
                    "local storage write budget exceeded: "
                    f"requested_bytes={byte_count} "
                    f"active_local_write_bytes={self._active_local_write_bytes} "
                    f"max_local_write_bytes={self._max_local_write_bytes}"
                )
            self._active_local_write_bytes += byte_count
        try:
            yield
        finally:
            with self._lock:
                self._active_local_write_bytes = max(0, self._active_local_write_bytes - byte_count)

    def wrap_storage_backend(self, backend: StorageBackend, *, run_id: str) -> StorageBackend:
        if isinstance(backend, ResourceManagedStorageBackend):
            return backend
        return ResourceManagedStorageBackend(
            backend,
            resource_controller=self,
            run_id=run_id,
        )

    def snapshot(self) -> dict[str, int | float | str | dict[str, str] | dict[str, int] | dict[str, float]]:
        with self._lock:
            active_export_slots = self._active_export_slots
            active_upload_slots = self._active_upload_slots
            active_download_slots = self._active_download_slots
            active_temp_dirs = self._active_temp_dirs
            active_local_write_bytes = self._active_local_write_bytes
            degraded_shared_quotas = self._active_shared_quota_degradations()
        return {
            "status": "ok",
            "gee_runtime_mode": "serialized",
            "max_parallel_exports": self._max_parallel_exports,
            "active_export_slots": active_export_slots,
            "available_export_slots": self._max_parallel_exports - active_export_slots,
            "max_parallel_uploads": self._max_parallel_uploads,
            "active_upload_slots": active_upload_slots,
            "available_upload_slots": self._max_parallel_uploads - active_upload_slots,
            "max_parallel_downloads": self._max_parallel_downloads,
            "active_download_slots": active_download_slots,
            "available_download_slots": self._max_parallel_downloads - active_download_slots,
            "max_local_write_bytes": self._max_local_write_bytes,
            "active_local_write_bytes": active_local_write_bytes,
            "active_temp_dirs": active_temp_dirs,
            "shared_quota_recovery_cooldown_seconds": round(
                self._shared_quota_recovery_cooldown_seconds,
                3,
            ),
            "degraded_shared_quotas": degraded_shared_quotas,
            "quota_coordinator": self._quota_coordinator.describe(),
        }

    @contextmanager
    def _operation_slot(
        self,
        *,
        semaphore: BoundedSemaphore,
        active_attr: str,
        limit: int,
        resource_name: str,
        owner_id: str,
        error_message: str,
    ) -> Iterator[None]:
        self._ensure_shared_quota_available(resource_name)
        acquired = semaphore.acquire(blocking=False)
        if not acquired:
            raise ResourceExhaustedError(error_message)
        shared_lease: ResourceQuotaLease | None = None
        heartbeat_stop: Event | None = None
        heartbeat_thread: Thread | None = None
        with self._lock:
            setattr(self, active_attr, getattr(self, active_attr) + 1)
        try:
            shared_lease = self._quota_coordinator.acquire(
                resource_name=resource_name,
                owner_id=owner_id,
                limit=limit,
            )
            heartbeat_interval = self._quota_coordinator.heartbeat_interval_seconds()
            if shared_lease.token is not None and heartbeat_interval is not None and heartbeat_interval > 0:
                heartbeat_stop = Event()
                heartbeat_thread = Thread(
                    target=self._heartbeat_shared_lease,
                    args=(shared_lease, heartbeat_interval, heartbeat_stop),
                    daemon=True,
                )
                heartbeat_thread.start()
            yield
        finally:
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=heartbeat_interval * 2 if heartbeat_interval is not None else 1.0)
            if shared_lease is not None:
                self._quota_coordinator.release(shared_lease)
            with self._lock:
                setattr(self, active_attr, max(0, getattr(self, active_attr) - 1))
            semaphore.release()

    def _heartbeat_shared_lease(
        self,
        lease: ResourceQuotaLease,
        interval_seconds: float,
        stop_event: Event,
    ) -> None:
        next_deadline = monotonic() + interval_seconds
        while not stop_event.wait(max(0.0, next_deadline - monotonic())):
            try:
                renewed = self._quota_coordinator.renew(lease)
                if not renewed:
                    self._record_shared_quota_failure(
                        resource_name=lease.resource_name,
                        owner_id=lease.owner_id,
                    )
                    logger.warning(
                        "shared quota lease renewal skipped or failed: resource=%s owner_id=%s",
                        lease.resource_name,
                        lease.owner_id,
                    )
                    return
            except Exception as exc:
                self._record_shared_quota_failure(
                    resource_name=lease.resource_name,
                    owner_id=lease.owner_id,
                )
                logger.warning(
                    "shared quota lease renewal failed: resource=%s owner_id=%s error=%s",
                    lease.resource_name,
                    lease.owner_id,
                    exc,
                )
                return
            next_deadline = monotonic() + interval_seconds

    def _ensure_shared_quota_available(self, resource_name: str) -> None:
        shared_retry_after = self._quota_coordinator.get_retry_after_seconds(resource_name)
        with self._lock:
            degraded_until = self._shared_quota_degraded_until_by_resource.get(resource_name)
            remaining_seconds = 0.0
            if degraded_until is not None:
                remaining_seconds = degraded_until - monotonic()
            if remaining_seconds <= 0:
                self._shared_quota_degraded_until_by_resource.pop(resource_name, None)
                remaining_seconds = 0.0
        effective_retry_after = max(remaining_seconds, shared_retry_after or 0.0)
        if effective_retry_after <= 0:
            return
        raise ResourceExhaustedError(
            "shared quota recovery in progress: "
            f"resource={resource_name} retry_after_seconds={effective_retry_after:.3f}"
        )

    def _record_shared_quota_failure(self, *, resource_name: str, owner_id: str) -> None:
        if self._shared_quota_recovery_cooldown_seconds <= 0:
            return
        degraded_until = monotonic() + self._shared_quota_recovery_cooldown_seconds
        with self._lock:
            current_deadline = self._shared_quota_degraded_until_by_resource.get(resource_name, 0.0)
            self._shared_quota_degraded_until_by_resource[resource_name] = max(
                current_deadline,
                degraded_until,
            )
        try:
            self._quota_coordinator.mark_resource_degraded(
                resource_name=resource_name,
                owner_id=owner_id,
                cooldown_seconds=self._shared_quota_recovery_cooldown_seconds,
            )
        except Exception as exc:
            logger.warning(
                "shared quota degraded marker update failed: resource=%s owner_id=%s error=%s",
                resource_name,
                owner_id,
                exc,
            )
        logger.warning(
            "shared quota marked degraded after renewal failure: resource=%s owner_id=%s cooldown_seconds=%.3f",
            resource_name,
            owner_id,
            self._shared_quota_recovery_cooldown_seconds,
        )

    def _active_shared_quota_degradations(self) -> dict[str, float]:
        now = monotonic()
        expired_resources = [
            resource_name
            for resource_name, degraded_until in self._shared_quota_degraded_until_by_resource.items()
            if degraded_until <= now
        ]
        for resource_name in expired_resources:
            self._shared_quota_degraded_until_by_resource.pop(resource_name, None)
        return {
            resource_name: round(degraded_until - now, 3)
            for resource_name, degraded_until in self._shared_quota_degraded_until_by_resource.items()
            if degraded_until > now
        }
