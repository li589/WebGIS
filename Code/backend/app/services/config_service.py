from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.config_api_keys import (  # noqa: F401
    _annotate_key_entry,
    _env_api_key_value,
    _get_api_keys_repository,
    _get_effective_api_key_cached,
    _sync_api_config_manager_key,
    clear_api_key_history,
    delete_api_key,
    delete_api_key_history_entry,
    get_effective_api_key,
    has_api_key_db_row,
    is_basemap_key_available,
    list_api_key_history,
    list_api_keys,
    restore_api_key_history,
    test_api_key,
    toggle_api_key,
    upsert_api_key,
)
from app.services.config_gee_accounts import (  # noqa: F401
    _get_gee_credentials_repository,
    add_gee_account,
    delete_gee_account,
    list_gee_accounts,
    reload_gee_account_pool,
    test_gee_account,
    toggle_gee_account,
)
from app.services.config_remote_storage import (  # noqa: F401
    _get_remote_storage_repository,
    clear_remote_storage_history,
    delete_remote_storage_history_entry,
    delete_remote_storage_profile,
    get_remote_storage_profile,
    list_remote_storage_history,
    list_remote_storage_profiles,
    probe_failover,
    restore_remote_storage_history,
    test_remote_storage_profile,
    toggle_remote_storage_profile,
    upsert_remote_storage_profile,
)
from app.services.config_weather_providers import (  # noqa: F401
    _ensure_weather_providers_registered,
    _get_weather_providers_repository,
    apply_persisted_provider_overrides,
    delete_weather_provider,
    get_weather_provider,
    list_weather_providers,
    set_weather_provider_priority,
    test_weather_provider,
    toggle_weather_provider,
    update_weather_provider,
)

logger = logging.getLogger(__name__)


# ── 常规配置 ──────────────────────────────────────────────────────────────────


def _parse_map_aoi_presets(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    presets: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        try:
            west = float(item["west"])
            south = float(item["south"])
            east = float(item["east"])
            north = float(item["north"])
        except (KeyError, TypeError, ValueError):
            continue
        if not isinstance(label, str) or not label.strip():
            continue
        presets.append(
            {
                "label": label.strip(),
                "west": west,
                "south": south,
                "east": east,
                "north": north,
            }
        )
    return presets


def _redact_redis_url(url: str) -> str:
    """Mask the password embedded in a Redis connection URL.

    Handles ``redis://:password@host`` and ``redis://user:password@host``;
    leaves scheme/host/db intact. Non-credential URLs are returned unchanged.
    """
    if not url:
        return url
    import re

    match = re.match(
        r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)(?P<auth>[^@/]+@)?(?P<rest>.+)$",
        url,
    )
    if not match:
        return url
    auth = match.group("auth")
    if not auth or ":" not in auth:
        return url  # no password (e.g. ``redis://host`` or ``user@host``)
    user, _, _pwd = auth.partition(":")
    return f"{match.group('scheme')}{user}:***@{match.group('rest')}"


def get_general_config() -> dict[str, Any]:
    """获取常规配置（脱敏）。"""
    return {
        "environment": settings.environment,
        "host": settings.host,
        "port": settings.port,
        "service_name": settings.service_name,
        "data_root": settings.data_root,
        "output_root": settings.output_root,
        "cache_dir": settings.cache_dir,
        "log_dir": settings.log_dir,
        "log_level": settings.log_level,
        "max_active_runs": settings.max_active_runs,
        "max_requested_outputs": settings.max_requested_outputs,
        "max_active_weather_tile_runs": settings.max_active_weather_tile_runs,
        "weather_cache_ttl_seconds": settings.weather_cache_ttl_seconds,
        "weather_refresh_forecast_hours": settings.weather_refresh_forecast_hours,
        "cache_default_ttl_seconds": settings.cache_default_ttl_seconds,
        "provider_max_hotspots": settings.provider_max_hotspots,
        "provider_max_series_points": settings.provider_max_series_points,
        "provider_table_chunk_size": settings.provider_table_chunk_size,
        "provider_series_chunk_size": settings.provider_series_chunk_size,
        "result_inline_max_bytes": settings.result_inline_max_bytes,
        "celery_task_soft_time_limit": settings.celery_task_soft_time_limit,
        "celery_task_time_limit": settings.celery_task_time_limit,
        "celery_task_always_eager": settings.celery_task_always_eager,
        "celery_worker_concurrency": settings.celery_worker_concurrency,
        "celery_worker_prefetch_multiplier": settings.celery_worker_prefetch_multiplier,
        "celery_worker_max_tasks_per_child": settings.celery_worker_max_tasks_per_child,
        "workflow_node_parallelism": settings.workflow_node_parallelism,
        "algorithm_max_parallel_workers": settings.algorithm_max_parallel_workers,
        "task_memory_budget_mb": settings.task_memory_budget_mb,
        "task_cpu_budget_cores": settings.task_cpu_budget_cores,
        "cors_origins": settings.cors_origins,
        "object_store_backend": settings.object_store_backend,
        "object_store_public_base": settings.object_store_public_base,
        "result_artifact_dir": settings.result_artifact_dir,
        "workflow_state_dir": settings.workflow_state_dir,
        "python_provider_root": settings.python_provider_root,
        "python_provider_workspace": settings.python_provider_workspace,
        "redis_url": _redact_redis_url(settings.redis_url),
        "storage_backend": settings.storage_backend,
        "reload": settings.reload,
        "map_default_longitude": settings.map_default_longitude,
        "map_default_latitude": settings.map_default_latitude,
        "map_default_zoom": settings.map_default_zoom,
        "map_default_tile_source": settings.map_default_tile_source,
        "map_aoi_presets": _parse_map_aoi_presets(settings.map_aoi_presets_json),
    }


# ── GEE 运行时配置 ────────────────────────────────────────────────────────────


def get_gee_runtime_config() -> dict[str, Any]:
    """获取 GEE 运行时配置。"""
    return {
        "gee_enabled": settings.gee_enabled,
        "max_parallel_exports": settings.gee_max_parallel_exports,
        "max_parallel_uploads": settings.gee_max_parallel_uploads,
        "max_parallel_downloads": settings.gee_max_parallel_downloads,
        "account_cooldown_seconds": settings.gee_account_cooldown_seconds,
        "storage_backend": settings.gee_storage_backend,
        "local_storage_root": settings.gee_local_storage_root,
        "api_account_management_enabled": settings.gee_api_account_management_enabled,
        "credentials_encryption_enabled": bool(settings.gee_credentials_encryption_key),
    }


# ── 天气 API 配置 ─────────────────────────────────────────────────────────────


def get_weather_config() -> dict[str, Any]:
    """获取天气 API 配置（含 runtime effective 覆盖 + 模型/同步真源）。"""
    from app.services.effective_config import (
        get_runtime_snapshot,
        get_weather_cache_ttl_seconds,
    )
    from app.services.weather_engine_settings import get_weather_engine_public_config

    snap = get_runtime_snapshot()
    engine = get_weather_engine_public_config()
    return {
        **engine,
        "cache_ttl_seconds": get_weather_cache_ttl_seconds(),
        "refresh_forecast_hours": settings.weather_refresh_forecast_hours,
        "schedule_enabled": settings.weather_schedule_enabled,
        "default_latitude": settings.weather_default_latitude,
        "default_longitude": settings.weather_default_longitude,
        "default_place_name": settings.weather_default_place_name,
        "max_active_weather_tile_runs": snap.max_active_weather_tile_runs,
    }


def set_weather_default_model(model: str) -> dict[str, Any]:
    """持久化全局默认天气模型（P1 DB）。"""
    from app.services.weather_engine_settings import set_weather_default_model as _set

    return _set(model)


def get_effective_weather_default_model() -> str:
    from app.services.weather_engine_settings import (
        get_effective_weather_default_model as _get,
    )

    return _get()


def get_weather_sync_overview() -> dict[str, Any]:
    from app.services.weather_engine_settings import (
        get_weather_sync_overview as _overview,
    )

    return _overview()


# ── 数据源配置 ────────────────────────────────────────────────────────────────


def _research_data_repo():
    from functools import lru_cache
    from pathlib import Path

    @lru_cache(maxsize=1)
    def _inner():
        from app.services.research_data_settings_repository import (
            ResearchDataSettingsRepository,
        )

        db_path = (
            Path(settings.gee_credentials_db_path).parent
            / "research_data_settings.sqlite3"
        )
        return ResearchDataSettingsRepository(db_path=db_path)

    return _inner()


def get_data_source_config() -> dict[str, Any]:
    """获取数据源配置（含数据根扫描、开放数据预设、静态缓存概览）。"""
    from app.services.data_cache_service import (
        DEFAULT_OPEN_DATA_PRESETS,
        OPEN_DATA_PRESET_LABELS,
        get_data_cache_overview,
        scan_data_root_datasets,
    )
    from app.services.portal_credentials import public_portal_credentials

    repo = _research_data_repo()
    # presets = 目录默认（内置+自定义门户）+ open_data_presets KV 覆盖
    from app.services.portal_catalog import (
        effective_base_urls,
        preset_labels_from_catalog,
    )

    presets = effective_base_urls(repo=repo)
    if not isinstance(presets, dict) or not presets:
        presets = dict(DEFAULT_OPEN_DATA_PRESETS)
    labels = preset_labels_from_catalog(repo=repo)
    for legacy_key, legacy_label in OPEN_DATA_PRESET_LABELS.items():
        if legacy_key in presets:
            labels[legacy_key] = legacy_label
    layer_uris = repo.get_json("remote_layer_data_uris", {})
    if not isinstance(layer_uris, dict):
        layer_uris = {}

    overview = get_data_cache_overview()
    portal_creds = public_portal_credentials(
        repo=repo,
        encryption_key=settings.gee_credentials_encryption_key,
    )
    from app.services.env_file_upsert import read_env_file_values

    env_vals = read_env_file_values()
    env_data_root = (env_vals.get("BACKEND_DATA_ROOT") or "").strip()
    env_output_root = (env_vals.get("BACKEND_OUTPUT_ROOT") or "").strip()
    effective_data = (settings.data_root or "").strip()
    effective_output = (settings.output_root or "").strip()
    pending_restart = bool(
        (env_data_root and env_data_root != effective_data)
        or (env_output_root and env_output_root != effective_output)
    )
    return {
        "storage_backend": settings.storage_backend,
        "data_root": settings.data_root,
        "output_root": settings.output_root,
        "env_data_root": env_data_root,
        "env_output_root": env_output_root,
        "pending_restart": pending_restart,
        "ui_restart_enabled": bool(getattr(settings, "ui_restart_enabled", False)),
        "download_source_root": settings.download_source_root,
        "download_real_fetch_enabled": settings.download_real_fetch_enabled,
        "tile_proxy_enabled": settings.tile_proxy_enabled,
        "tile_proxy_cache_ttl_seconds": settings.tile_proxy_cache_ttl_seconds,
        "static_cache_root": str(_resolve_static_cache_root_effective()),
        "cache_dir": str(settings.cache_dir or ""),
        "minio": {
            "endpoint": settings.minio_endpoint,
            "bucket": settings.minio_bucket,
            "secure": settings.minio_secure,
        }
        if settings.storage_backend == "minio"
        else None,
        "discovered_datasets": scan_data_root_datasets(),
        "available_datasets": _available_datasets_safe(),
        "open_data_presets": presets,
        "open_data_preset_labels": labels,
        "portal_credentials": portal_creds,
        "remote_layer_data_uris": layer_uris,
        "static_cache": {
            "cache_root": overview["cache_root"],
            "ttl_seconds": overview["ttl_seconds"],
            "ttl_unlimited": overview["ttl_unlimited"],
            "entry_count": overview["entry_count"],
            "total_bytes": overview["total_bytes"],
        },
        "workflow_hint": (
            "开放门户请用工作流「门户数据下载」(http_open_data) + cred_profile；"
            "NAS/任意 URI 用「远程拉取」并引用「远程存储」凭证 profile。"
            "数据根目录可在本页修改；保存后需重启 FastAPI+Worker+Beat 生效。"
        ),
    }


def _validate_absolute_existing_dir(path_str: str, *, label: str) -> Path:
    raw = str(path_str or "").strip()
    if not raw:
        raise ValueError(f"{label} must not be empty")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    if not path.exists():
        raise ValueError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"{label} is not a directory: {path}")
    try:
        next(path.iterdir(), None)
    except OSError as exc:
        raise ValueError(f"{label} is not listable: {path}") from exc
    return path.resolve()


def _validate_or_create_absolute_dir(path_str: str, *, label: str) -> Path:
    """缓存类路径：允许不存在但必须可创建（创建失败抛 ValueError）。"""
    raw = str(path_str or "").strip()
    if not raw:
        raise ValueError(f"{label} must not be empty")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    if not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"cannot create {label}: {path}") from exc
    if not path.is_dir():
        raise ValueError(f"{label} is not a directory: {path}")
    return path.resolve()


def update_data_source_paths(
    data_root: str,
    output_root: str | None = None,
    static_cache_root: str | None = None,
    cache_dir: str | None = None,
    download_source_root: str | None = None,
) -> dict[str, Any]:
    """校验并写入数据根/产物根/缓存类路径到 .env（需重启后端生效）。"""
    from app.services.env_file_upsert import backend_env_path, upsert_env_keys

    root = _validate_absolute_existing_dir(data_root, label="data_root")
    out_raw = (output_root or "").strip()
    if out_raw:
        out = _validate_absolute_existing_dir(out_raw, label="output_root")
    else:
        out = root / "ProjectOutput"
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"cannot create output_root: {out}") from exc
        out = _validate_absolute_existing_dir(str(out), label="output_root")

    env_updates: dict[str, str] = {
        "BACKEND_DATA_ROOT": str(root),
        "BACKEND_OUTPUT_ROOT": str(out),
    }
    effective_map: dict[str, str] = {}
    optional_paths: list[tuple[str, str | None, str, str]] = [
        (
            "static_cache_root",
            static_cache_root,
            "BACKEND_STATIC_CACHE_ROOT",
            str(_resolve_static_cache_root_effective()),
        ),
        (
            "cache_dir",
            cache_dir,
            "BACKEND_CACHE_DIR",
            str(settings.cache_dir or ""),
        ),
        (
            "download_source_root",
            download_source_root,
            "BACKEND_DOWNLOAD_SOURCE_ROOT",
            str(settings.download_source_root or ""),
        ),
    ]
    for label, raw_value, env_key, effective_value in optional_paths:
        value = str(raw_value or "").strip()
        if not value:
            continue
        resolved = _validate_or_create_absolute_dir(value, label=label)
        env_updates[env_key] = str(resolved)
        effective_map[label] = str(resolved)

    env_path = upsert_env_keys(env_updates)
    effective_data = (settings.data_root or "").strip()
    effective_output = (settings.output_root or "").strip()
    pending = str(root) != effective_data or str(out) != effective_output
    for label, resolved in effective_map.items():
        env_key = next(k for _l, _v, k, _e in optional_paths if _l == label)
        env_effective = next(e for _l, _v, k, e in optional_paths if k == env_key)
        if resolved != env_effective:
            pending = True
    return {
        "data_root": str(root),
        "output_root": str(out),
        "effective_data_root": effective_data,
        "effective_output_root": effective_output,
        "static_cache_root": effective_map.get("static_cache_root"),
        "cache_dir": effective_map.get("cache_dir"),
        "download_source_root": effective_map.get("download_source_root"),
        "pending_restart": pending,
        "env_path": str(env_path if env_path else backend_env_path()),
        "message": (
            "Paths saved to .env. Restart FastAPI + Worker + Beat to apply."
            if pending
            else "Paths saved; already match the running process."
        ),
    }


def _resolve_static_cache_root_effective() -> Path:
    from app.services.data_cache_service import resolve_static_cache_root

    return resolve_static_cache_root()


def _available_datasets_safe() -> list[dict[str, Any]]:
    try:
        from app.services.dataset_registry_service import get_dataset_registry

        return get_dataset_registry().list_entries()
    except Exception as exc:  # noqa: BLE001 — 注册表不可用不应阻断配置读取
        logger.warning("dataset registry unavailable: %s", exc)
        return []


def list_available_datasets(*, include_disabled: bool = True) -> list[dict[str, Any]]:
    from app.services.dataset_registry_service import get_dataset_registry

    return get_dataset_registry().list_entries(include_disabled=include_disabled)


def upsert_available_dataset(
    dataset_id: str | None, payload: dict[str, Any]
) -> dict[str, Any]:
    """可用数据集创建/更新；写后失效 readiness 路径缓存。"""
    from app.services.dataset_registry_service import (
        DatasetRegistryError,
        get_dataset_registry,
        invalidate_dataset_caches,
    )

    try:
        entry = get_dataset_registry().upsert(
            dataset_id=None
            if not dataset_id or dataset_id in {"new", "-"}
            else dataset_id,
            logical_name=str(payload.get("logical_name") or "").strip(),
            path=str(payload.get("path") or "").strip(),
            file_format=str(payload.get("file_format") or ""),
            variables=payload.get("variables"),
            time_range=str(payload.get("time_range") or ""),
            resolution=str(payload.get("resolution") or ""),
            tags=payload.get("tags"),
            description=str(payload.get("description") or ""),
            enabled=bool(payload.get("enabled", True)),
        )
    except DatasetRegistryError as exc:
        raise ValueError(str(exc)) from exc
    invalidate_dataset_caches()
    return entry


def delete_available_dataset(dataset_id: str) -> bool:
    from app.services.dataset_registry_service import (
        DatasetRegistryError,
        get_dataset_registry,
        invalidate_dataset_caches,
    )

    try:
        deleted = get_dataset_registry().delete(dataset_id)
    except DatasetRegistryError as exc:
        raise ValueError(str(exc)) from exc
    if deleted:
        invalidate_dataset_caches()
    return deleted


def rescan_available_datasets() -> dict[str, Any]:
    from app.services.dataset_registry_service import (
        invalidate_dataset_caches,
        rescan_data_root,
    )

    result = rescan_data_root()
    invalidate_dataset_caches()
    return result


def list_remote_sources() -> list[dict[str, Any]]:
    from app.services.remote_source_registry import (
        list_remote_sources_with_capabilities,
    )

    return list_remote_sources_with_capabilities()


def upsert_remote_source_entry(
    remote_source_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    from app.services.remote_source_registry import (
        RemoteSourceRegistryError,
        get_remote_source_registry,
    )

    try:
        return get_remote_source_registry().upsert(
            remote_source_id=remote_source_id,
            kind=str(payload.get("kind") or ""),
            ref_id=str(payload.get("ref_id") or ""),
            remote_path=str(payload.get("remote_path") or ""),
            display_name=str(payload.get("display_name") or ""),
            cache_policy=str(payload.get("cache_policy") or "standard"),
        )
    except RemoteSourceRegistryError as exc:
        raise ValueError(str(exc)) from exc


def delete_remote_source_entry(remote_source_id: str) -> bool:
    from app.services.remote_source_registry import get_remote_source_registry

    return get_remote_source_registry().delete(remote_source_id)


def schedule_ui_backend_restart(
    components: list[str] | None = None,
) -> dict[str, Any]:
    from app.services.service_restart import (
        schedule_backend_restart,
        ui_restart_allowed,
    )

    result = schedule_backend_restart(components)
    result["ui_restart_enabled"] = ui_restart_allowed()
    return result


def update_open_data_presets(presets: dict[str, Any]) -> dict[str, Any]:
    from app.core.ssrf import validate_url_for_storage

    cleaned: dict[str, str] = {}
    for k, v in presets.items():
        key = str(k).strip()
        val = str(v).strip()
        if not key or not val:
            continue
        # 安全：存储时校验 URL 格式，防止非 HTTP(S) 协议入库
        validate_url_for_storage(val)
        cleaned[key] = val
    _research_data_repo().set_json("open_data_presets", cleaned)
    return {"open_data_presets": cleaned}


def get_portal_credentials_public() -> dict[str, Any]:
    from app.services.portal_credentials import public_portal_credentials

    return {
        "portal_credentials": public_portal_credentials(
            repo=_research_data_repo(),
            encryption_key=settings.gee_credentials_encryption_key,
        )
    }


def upsert_portal_credential(portal_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.portal_credentials import upsert_portal_credential as _upsert

    return {
        "portal_credentials": _upsert(
            repo=_research_data_repo(),
            encryption_key=settings.gee_credentials_encryption_key,
            portal_id=portal_id,
            payload=payload,
        )
    }


def delete_portal_credential(portal_id: str) -> dict[str, Any]:
    from app.services.portal_credentials import delete_portal_credential as _delete

    return {
        "portal_credentials": _delete(
            repo=_research_data_repo(),
            encryption_key=settings.gee_credentials_encryption_key,
            portal_id=portal_id,
        )
    }


def get_portal_credentials_runtime() -> dict[str, Any]:
    """Decrypted portal credentials for job injection (never expose via public API)."""
    from app.services.portal_credentials import load_portal_credentials_secret

    return load_portal_credentials_secret(
        repo=_research_data_repo(),
        encryption_key=settings.gee_credentials_encryption_key,
    )


# ── 开放门户目录 ─────────────────────────────────────────────────────────────


def get_portal_catalog() -> dict[str, Any]:
    from app.services.portal_catalog import get_portal_catalog as _list

    return {"portals": _list()}


def upsert_portal(portal_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.node_template_registry import invalidate_portal_options_cache
    from app.services.portal_catalog import upsert_portal as _upsert

    try:
        return _upsert(portal_id, payload)
    finally:
        invalidate_portal_options_cache()


def delete_portal(portal_id: str) -> bool:
    from app.services.node_template_registry import invalidate_portal_options_cache
    from app.services.portal_catalog import delete_portal as _delete

    try:
        return _delete(portal_id)
    finally:
        invalidate_portal_options_cache()


def test_portal(portal_id: str) -> dict[str, Any]:
    from app.services.portal_catalog import test_portal as _test

    return _test(portal_id)


def search_portal(portal_id: str, *, query: str, page_size: int = 20) -> dict[str, Any]:
    from app.services.portal_catalog import search_portal as _search

    return _search(portal_id, query=query, page_size=page_size)


def update_remote_layer_data_uris(uris: dict[str, Any]) -> dict[str, Any]:
    """Persist nested overlay: {layer_id: {dataset: uri|[uri...]}}."""
    from app.core.ssrf import validate_data_source_uri_for_storage

    cleaned: dict[str, dict[str, list[str]]] = {}
    for layer_id, datasets in uris.items():
        if not str(layer_id).strip() or not isinstance(datasets, dict):
            continue
        ds_map: dict[str, list[str]] = {}
        for dataset_name, raw_uris in datasets.items():
            if isinstance(raw_uris, str) and raw_uris.strip():
                # 安全：允许 smb/file/minio 等取数 scheme，拒绝 javascript: 等
                validated = validate_data_source_uri_for_storage(raw_uris.strip())
                ds_map[str(dataset_name)] = [validated]
            elif isinstance(raw_uris, list):
                vals = []
                for u in raw_uris:
                    val = str(u).strip()
                    if val:
                        vals.append(validate_data_source_uri_for_storage(val))
                if vals:
                    ds_map[str(dataset_name)] = vals
        if ds_map:
            cleaned[str(layer_id)] = ds_map
    _research_data_repo().set_json("remote_layer_data_uris", cleaned)
    return {"remote_layer_data_uris": cleaned}


def get_data_cache_overview_api() -> dict[str, Any]:
    from app.services.data_cache_service import get_data_cache_overview

    return get_data_cache_overview()


def evict_data_cache_api(
    *, uri_or_name: str | None = None, older_than_seconds: int | None = None
) -> dict[str, Any]:
    from app.services.data_cache_service import evict_data_cache

    return evict_data_cache(
        uri_or_name=uri_or_name, older_than_seconds=older_than_seconds
    )


# ── 关于信息 ──────────────────────────────────────────────────────────────────


def get_about_info() -> dict[str, Any]:
    """获取项目信息。"""
    return {
        "project_name": settings.service_name,
        "version": "0.1.0",
        # 旧描述（CGDA 时代）："综合地理态势数据分析与可视化系统"
        "description": "星地融合土壤水分监测与干旱预警数据分析与可视化系统",
        "tech_stack": [
            "Vue 3",
            "TypeScript",
            "Pinia",
            "MapLibre GL",
            "Cesium",
            "ECharts",
            "Vite",
            "FastAPI",
            "Python 3.12",
            "Celery",
            "Redis",
            "SQLite",
            "MinIO",
            "Google Earth Engine",
            "Open-Meteo",
            "Nginx",
            "Docker",
        ],
        "modules": [
            {"name": "图层管理", "description": "多源图层目录、工作流驱动、实时瓦片"},
            {
                "name": "天气引擎",
                "description": "Open-Meteo 实时气象数据、风场粒子流渲染",
            },
            {
                "name": "GEE 引擎",
                "description": "Google Earth Engine 多账户并行、遥感分析",
            },
            {"name": "算法引擎", "description": "Python Provider 算法集成、双通道接口"},
            {
                "name": "工作流调度",
                "description": "Celery 分布式任务、队列路由、重试策略",
            },
            {
                "name": "数据管理",
                "description": "本地/远程数据源、导入导出、MinIO 持久化",
            },
        ],
        "architecture_summary": (
            "系统采用前后端分离架构：前端 Vue 3 + MapLibre GL 负责地图渲染与交互，"
            "后端 FastAPI 提供 RESTful API，Celery + Redis 处理异步工作流。"
            "支持 GEE、天气、算法三大引擎模块化接入，通过统一工作流端点调度。"
            "数据层支持本地文件系统、MinIO 对象存储和远程 FileBrowser 服务器。"
        ),
    }
