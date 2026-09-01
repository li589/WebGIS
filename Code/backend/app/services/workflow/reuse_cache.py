"""Resolve block-cache reuse paths when retrying workflow runs."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.services.workflow_repository import (
    _TERMINAL_STATUSES,
    SQLiteWorkflowRepository,
)

logger = logging.getLogger(__name__)

# Modules that support reuse_block_cache / reuse_output_dir on retry.
_OMEGA_BLOCK_MODULES = frozenset(
    {
        "omega_avg_daily",
        "omega_sf_fenkuai",
        "omega_sf",
        "omega_block",
        "block_inversion",
    }
)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _module_supports_block_reuse(module_name: str | None) -> bool:
    if not module_name:
        return False
    normalized = module_name.strip().lower()
    return normalized in _OMEGA_BLOCK_MODULES or normalized.startswith("omega_")


def _output_dir_from_products(products: list[Any]) -> str | None:
    for product in products:
        if not isinstance(product, dict):
            continue
        uri = product.get("uri") or product.get("path") or product.get("local_path")
        if not isinstance(uri, str) or not uri.strip():
            continue
        path = Path(uri)
        name_lower = path.name.lower()
        tags = product.get("tags") if isinstance(product.get("tags"), dict) else {}
        layer = str(tags.get("layer", "")).upper()
        product_type = str(product.get("type") or product.get("name") or "").lower()
        if "block_dir" in product_type or layer == "BLOCK" or "block" in name_lower:
            if path.is_dir():
                return str(path)
            parent = path.parent
            if parent.is_dir():
                return str(parent)
        if path.suffix.lower() in {".mat", ".tif", ".tiff"} and path.parent.is_dir():
            return str(path.parent)
    return None


def _output_dir_from_request(request_json: str | None) -> str | None:
    if not request_json:
        return None
    try:
        payload = json.loads(request_json)
    except json.JSONDecodeError:
        return None
    algo = payload.get("algorithm_request")
    if not isinstance(algo, dict):
        return None
    params = algo.get("algorithm_params")
    if not isinstance(params, dict):
        return None
    output_spec = algo.get("output_spec")
    extra = output_spec.get("extra") if isinstance(output_spec, dict) else None
    for source in (params, extra if isinstance(extra, dict) else {}):
        for key in ("reuse_output_dir", "output_dir"):
            raw = source.get(key)
            if isinstance(raw, str) and raw.strip():
                path = Path(raw.strip())
                if path.exists():
                    return str(path)
    module_name = algo.get("module_name")
    if _module_supports_block_reuse(str(module_name) if module_name else None):
        default = (
            Path(settings.python_provider_workspace) / "products" / str(module_name)
        )
        if default.is_dir():
            return str(default)
    return None


def resolve_reuse_output_dir(
    repository: SQLiteWorkflowRepository,
    run_id: str,
) -> tuple[str | None, str | None]:
    """Return ``(reuse_output_dir, module_name)`` for a prior workflow run.

    Priority:
    1. ``executor_metadata.reuse_output_dir``
    2. ``result_dto.products`` block/mat paths
    3. Original request ``algorithm_params.output_dir`` / ``output_spec.extra``
    4. Default ``products/{module_name}`` when module is omega-block capable
    """
    run = repository.get_run(run_id)
    if run is None:
        return None, None

    meta = _as_dict(run.executor_metadata)
    cached = meta.get("reuse_output_dir")
    if isinstance(cached, str) and cached.strip() and Path(cached).exists():
        module = meta.get("module_name")
        return cached.strip(), str(module) if module else None

    raw_payload = repository.get_run_payload(run_id)
    raw_result_dto = (
        raw_payload.get("result_dto") if isinstance(raw_payload, dict) else None
    )
    if isinstance(raw_result_dto, dict):
        products = raw_result_dto.get("products")
        if isinstance(products, list):
            from_products = _output_dir_from_products(products)
            if from_products:
                module = raw_result_dto.get("module_name") or meta.get("module_name")
                return from_products, str(module) if module else None

    result_dto = _as_dict(run.result_dto)
    products = result_dto.get("products")
    if isinstance(products, list):
        from_products = _output_dir_from_products(products)
        if from_products:
            module = result_dto.get("module_name") or meta.get("module_name")
            return from_products, str(module) if module else None

    request_json = repository.get_run_request_json(run_id)
    from_request = _output_dir_from_request(request_json)
    if from_request:
        module = None
        if request_json:
            try:
                algo = json.loads(request_json).get("algorithm_request") or {}
                if isinstance(algo, dict) and algo.get("module_name"):
                    module = str(algo["module_name"])
            except json.JSONDecodeError:
                pass
        return from_request, module

    return None, None


def inject_retry_reuse_params(
    payload_dict: dict[str, Any],
    *,
    reuse_output_dir: str | None,
) -> dict[str, Any]:
    """Merge reuse flags into ``algorithm_request.algorithm_params``."""
    if not reuse_output_dir:
        return payload_dict
    algo = payload_dict.get("algorithm_request")
    if not isinstance(algo, dict):
        return payload_dict
    params = dict(algo.get("algorithm_params") or {})
    if params.get("reuse_block_cache", True) is False:
        return payload_dict
    if "reuse_output_dir" not in params:
        params["reuse_block_cache"] = True
        params["reuse_output_dir"] = reuse_output_dir
        algo = {**algo, "algorithm_params": params}
        return {**payload_dict, "algorithm_request": algo}
    return payload_dict


# ─── B-N2：retry 复用目录 claim（写互斥）─────────────────────────────────────
# 并发双 retry 解析出同一 reuse_output_dir 后，两个新 run 会同时向该目录写
# chunk checkpoint（``_append_chunk_checkpoint(output_dir, ...)``，2026-08-23
# 起为增量目录 ``.omega_sf_chunks/``）/ 块缓存。
# 生命周期：提交前 acquire（pending，TTL 短）→ 新 run 落库后 upgrade 为
# ``{run_id}:{token}``（TTL 长）→ 持有者 run 终态/被清理后由下一次 acquire
# 懒抢占（compare-and-delete）→ 提交失败/未落库则立即 release。
# Redis 不可用时退化为进程内 dict 兜底（仅单进程互斥，与 sync 锁 B-N3 同定位）。

RETRY_REUSE_PENDING_TTL_SECONDS = 300
RETRY_REUSE_RUNNING_TTL_SECONDS = 6 * 3600

_CAS_DELETE_SCRIPT = """
-- cas-delete: value matches expected then DEL
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_CAS_UPGRADE_SCRIPT = """
-- cas-upgrade: value matches expected then SET new value with new TTL
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
    return 1
end
return 0
"""

_retry_reuse_local_lock = threading.Lock()
_retry_reuse_local_holders: dict[str, str] = {}


def _retry_reuse_claim_key(reuse_output_dir: str) -> str:
    normalized = os.path.abspath(reuse_output_dir.strip())
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
    return f"workflow:retry-reuse:{digest}"


def _holder_run_id(claim_value: str) -> str:
    return claim_value.split(":", 1)[0]


def _holder_finished(repository: SQLiteWorkflowRepository, claim_value: str) -> bool:
    """持有者是否已可抢占：run 已终态或已被清理。pending（提交中）不可抢占。"""
    holder = _holder_run_id(claim_value)
    if holder == "pending":
        return False
    run = repository.get_run(holder)
    if run is None:
        return True
    return getattr(run, "status", None) in _TERMINAL_STATUSES


def acquire_retry_reuse_claim(
    repository: SQLiteWorkflowRepository,
    reuse_output_dir: str,
) -> str | None:
    """获取复用目录写互斥 claim；被持有时返回 None。

    持有者 run 已终态/被清理时懒抢占（CAS 删除后重取一次）。
    """
    key = _retry_reuse_claim_key(reuse_output_dir)
    client = get_redis_client()
    if client is not None:
        token = f"pending:{uuid.uuid4().hex[:12]}"
        if client.set(key, token, nx=True, ex=RETRY_REUSE_PENDING_TTL_SECONDS):
            return token
        current = client.get(key)
        if current is None or not _holder_finished(repository, current):
            return None
        if client.eval(_CAS_DELETE_SCRIPT, 1, key, current) == 1:
            retry_token = f"pending:{uuid.uuid4().hex[:12]}"
            if client.set(
                key, retry_token, nx=True, ex=RETRY_REUSE_PENDING_TTL_SECONDS
            ):
                return retry_token
        return None
    with _retry_reuse_local_lock:
        current = _retry_reuse_local_holders.get(key)
        if current is None:
            token = f"pending:{uuid.uuid4().hex[:12]}"
            _retry_reuse_local_holders[key] = token
            return token
        if not _holder_finished(repository, current):
            return None
        del _retry_reuse_local_holders[key]
        token = f"pending:{uuid.uuid4().hex[:12]}"
        _retry_reuse_local_holders[key] = token
        return token


def upgrade_retry_reuse_claim(
    reuse_output_dir: str,
    claim: str,
    holder_run_id: str,
) -> bool:
    """提交成功后将 pending claim 升级为持有者 run（TTL 拉长到运行时长档）。"""
    key = _retry_reuse_claim_key(reuse_output_dir)
    new_value = f"{holder_run_id}:{claim.split(':', 1)[1]}"
    client = get_redis_client()
    if client is not None:
        try:
            return (
                client.eval(
                    _CAS_UPGRADE_SCRIPT,
                    1,
                    key,
                    claim,
                    new_value,
                    RETRY_REUSE_RUNNING_TTL_SECONDS,
                )
                == 1
            )
        except Exception:  # noqa: BLE001 - Redis 抖动不应毁掉已提交的 run
            logger.warning(
                "retry reuse claim upgrade failed for %s", key, exc_info=True
            )
            return False
    with _retry_reuse_local_lock:
        if _retry_reuse_local_holders.get(key) != claim:
            return False
        _retry_reuse_local_holders[key] = new_value
        return True


def release_retry_reuse_claim(reuse_output_dir: str, claim: str) -> None:
    """提交失败/新 run 未落库时释放 claim（token 不匹配则不动他人锁）。"""
    key = _retry_reuse_claim_key(reuse_output_dir)
    client = get_redis_client()
    if client is not None:
        try:
            client.eval(_CAS_DELETE_SCRIPT, 1, key, claim)
        except Exception:  # noqa: BLE001
            logger.warning(
                "retry reuse claim release failed for %s", key, exc_info=True
            )
        return
    with _retry_reuse_local_lock:
        if _retry_reuse_local_holders.get(key) == claim:
            del _retry_reuse_local_holders[key]
