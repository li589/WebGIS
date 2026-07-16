from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import importlib
import logging
from pathlib import Path
import sys
import threading
from typing import Any
from typing import Iterator

from app.core.config import settings
from app.services.engine_request_registry import (
    EngineRequestPopulator,
    get_engine_populator,
    register_engine_populator,
)
from app.services.layer_catalog import get_layer_descriptor
from shared.contracts.api_contracts import WorkflowCommandType, WorkflowSubmitRequest

_ALGORITHM_ENTRY_KEYS: tuple[str, ...] = ("module_name", "workflow_name", "workflow_definition")
_GEE_ENTRY_KEYS: tuple[str, ...] = ("workflow", "manifest_uri")
_WEATHER_ENTRY_KEYS: tuple[str, ...] = ("workflow",)


def normalize_workflow_submit_request(payload: WorkflowSubmitRequest) -> WorkflowSubmitRequest:
    """按 layer catalog 元数据补齐 bridge 所需请求字段。

    当前前端只提交 `layer_id + parameters + map_context`，而 Python provider bridge
    需要 `algorithm_request.module_name/workflow_name/workflow_definition` 才会接管。
    这里优先使用后端 `layer_catalog` 作为执行事实源，避免前端维护第二份 workflow 元数据。

    引擎分发通过 engine_request_registry 注册表完成，新增引擎只需注册 populator。
    """

    if payload.command_type != WorkflowCommandType.analysis:
        return payload

    layer_id = payload.layer_id or payload.map_context.active_layer_id
    if not layer_id:
        return payload

    descriptor = get_layer_descriptor(layer_id)
    if descriptor is None or not descriptor.engine:
        return payload

    populator = get_engine_populator(descriptor.engine)
    if populator is None:
        return payload

    return populator.populate(payload=payload, layer_id=layer_id, descriptor=descriptor)


def describe_python_provider_resolution(payload: WorkflowSubmitRequest) -> dict[str, Any] | None:
    """公开 API：委托给 python_provider populator。"""
    populator = get_engine_populator("python_provider")
    if populator is None:
        return None
    return populator.describe_resolution(payload)


def _describe_python_provider_resolution_impl(payload: WorkflowSubmitRequest) -> dict[str, Any] | None:
    layer_id = payload.layer_id or payload.map_context.active_layer_id
    if not layer_id:
        return None

    descriptor = get_layer_descriptor(layer_id)
    if descriptor is None or descriptor.engine != "python_provider" or not descriptor.module_name:
        return None

    algorithm_request = _normalize_algorithm_request(payload.algorithm_request)
    datasource_selection = _normalize_request(algorithm_request.get("datasource_selection"))
    explicit_data_access_requests = _normalize_request(datasource_selection.get("_data_access_requests"))
    default_datasets: list[dict[str, Any]] = []
    unresolved_default_datasets: list[dict[str, Any]] = []

    for dataset_name, candidates in descriptor.default_data_access_sources.items():
        resolution = _resolve_data_access_candidates(candidates)
        dataset_summary = {
            "dataset_name": dataset_name,
            "resolved_uri": resolution["resolved_uri"],
            "candidate_sources": [item["source"] for item in resolution["candidates"]],
            "candidates": resolution["candidates"],
        }
        default_datasets.append(dataset_summary)
        if resolution["resolved_uri"] is None:
            unresolved_default_datasets.append(dataset_summary)

    return {
        "layer_id": layer_id,
        "layer_status": descriptor.status,
        "module_name": descriptor.module_name,
        "workflow_entry_name": descriptor.workflow_name or descriptor.module_name,
        "task_type": algorithm_request.get("task_type") or descriptor.default_task_type or descriptor.module_name,
        "explicit_data_access_datasets": sorted(explicit_data_access_requests.keys()),
        "default_datasets": default_datasets,
        "unresolved_default_datasets": unresolved_default_datasets,
    }


def describe_layer_run_readiness(layer_id: str) -> dict[str, Any] | None:
    descriptor = get_layer_descriptor(layer_id)
    if descriptor is None:
        return None

    readiness = "ready"
    notes: list[str] = list(descriptor.run_readiness_notes)
    summary: str | None = descriptor.run_readiness_summary

    if descriptor.status == "sample":
        notes.append("当前图层为样板 provider 链路，可运行但结果仅用于联调/演示。")
        summary = summary or "样板 provider 可运行，但不代表正式生产数据。"
    elif descriptor.status == "placeholder":
        readiness = "blocked"
        notes.append("图层仍处于占位状态，真实数据源尚未接入。")

    # 引擎特定就绪检查通过注册表分发
    unresolved_default_datasets: list[dict[str, Any]] = []
    if descriptor.engine:
        populator = get_engine_populator(descriptor.engine)
        if populator is not None:
            engine_result = populator.describe_readiness(descriptor)
            if engine_result:
                unresolved_default_datasets = engine_result.get("unresolved_default_datasets", [])

    if unresolved_default_datasets:
        readiness = "blocked"
        for item in unresolved_default_datasets:
            candidate_text = ", ".join(item["candidate_sources"]) or "未提供候选源"
            notes.append(f"缺少默认数据集 {item['dataset_name']}；已检查：{candidate_text}")

    if unresolved_default_datasets:
        dataset_names = "、".join(item["dataset_name"] for item in unresolved_default_datasets)
        summary = f"默认数据源未就绪：{dataset_names}"
    elif summary is None and readiness == "blocked" and notes:
        summary = notes[0]

    return {
        "run_readiness": readiness,
        "run_readiness_summary": summary,
        "run_readiness_notes": notes,
        "unresolved_default_datasets": unresolved_default_datasets,
    }


@lru_cache(maxsize=1)
def _load_module_template_map():
    """加载 Python provider 的 module request templates（含手工表 + 自动推导）。

    返回 {module_name: RequestTemplateSpec} 字典。若 provider root 不存在或导入失败返回空 dict。
    """
    provider_root = Path(settings.python_provider_root)
    if not provider_root.exists():
        return {}
    try:
        with _python_provider_import_path(provider_root):
            deriver = importlib.import_module("contracts.template_deriver")
            return deriver.list_module_templates()
    except Exception:
        logger.debug("Failed to load module templates from python provider", exc_info=True)
        return {}


def _get_module_request_template(module_name: str):
    """获取指定 module 的 RequestTemplateSpec，未找到返回 None。"""
    templates = _load_module_template_map()
    return templates.get(module_name)


def _populate_python_provider_request(*, payload: WorkflowSubmitRequest, descriptor) -> WorkflowSubmitRequest:
    if not descriptor.module_name:
        return payload

    algorithm_request = _normalize_algorithm_request(payload.algorithm_request)
    if algorithm_request.get("workflow_definition") or algorithm_request.get("workflow_name"):
        return payload
    explicit_module_name = algorithm_request.get("module_name")
    if explicit_module_name and explicit_module_name != descriptor.module_name:
        return payload

    algorithm_request.setdefault("module_name", descriptor.module_name)
    algorithm_request.setdefault(
        "workflow_entry_name",
        descriptor.workflow_name or descriptor.module_name,
    )
    algorithm_request.setdefault("task_type", descriptor.default_task_type or descriptor.module_name)

    datasource_selection = _normalize_request(algorithm_request.get("datasource_selection"))
    data_access_requests = _normalize_request(datasource_selection.get("_data_access_requests"))
    default_data_access = _build_default_data_access_requests(descriptor.default_data_access_sources)
    for dataset_name, request_payload in default_data_access.items():
        data_access_requests.setdefault(dataset_name, request_payload)
    if data_access_requests:
        datasource_selection["_data_access_requests"] = data_access_requests

    # 根据模板的 accepted_data_access_by_required_key 把 dataset URI 映射到 required_key
    # 修复：模板验证检查 datasource_selection 中有 input_dir 等键，
    # 但 _data_access_requests 中用的是 dataset_name（如 NDVI_16DAY_RASTER）。
    # 需要把解析到的 URI 也设置到 datasource_selection[required_key] 中。
    template = _get_module_request_template(descriptor.module_name)
    if template is not None and template.accepted_data_access_by_required_key:
        for required_key, accepted_datasets in template.accepted_data_access_by_required_key.items():
            if datasource_selection.get(required_key) is not None:
                continue  # 用户已显式提供
            for dataset_name in accepted_datasets:
                da_request = data_access_requests.get(dataset_name)
                if da_request and isinstance(da_request, dict):
                    selector = da_request.get("selector") or {}
                    uris = selector.get("uris") or []
                    if uris:
                        datasource_selection[required_key] = uris[0]
                        break

    if datasource_selection:
        algorithm_request["datasource_selection"] = datasource_selection

    return payload.model_copy(update={"algorithm_request": algorithm_request})


def _populate_gee_request(*, payload: WorkflowSubmitRequest, layer_id: str, descriptor) -> WorkflowSubmitRequest:
    if not descriptor.workflow_definition:
        return payload

    gee_request = _normalize_request(payload.gee_request)
    if any(gee_request.get(key) for key in _GEE_ENTRY_KEYS):
        return payload

    gee_request.setdefault("workflow", descriptor.workflow_definition)
    gee_request.setdefault("workflow_id", descriptor.workflow_id or descriptor.workflow_name or layer_id)
    return payload.model_copy(update={"gee_request": gee_request})


def _populate_weather_request(*, payload: WorkflowSubmitRequest, layer_id: str, descriptor) -> WorkflowSubmitRequest:
    if not descriptor.workflow_definition:
        return payload

    weather_request = _normalize_request(payload.weather_request)
    if any(weather_request.get(key) for key in _WEATHER_ENTRY_KEYS):
        return payload

    weather_request.setdefault("workflow", descriptor.workflow_definition)
    weather_request.setdefault("workflow_id", descriptor.workflow_id or descriptor.workflow_name or layer_id)
    weather_request.setdefault("layer_id", layer_id)
    return payload.model_copy(update={"weather_request": weather_request})


def _normalize_algorithm_request(value: Any) -> dict[str, Any]:
    return _normalize_request(value)


def _normalize_request(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return dict(value)
    return {}


def _build_default_data_access_requests(source_map: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    requests: dict[str, dict[str, Any]] = {}
    for dataset_name, candidates in source_map.items():
        uri = _resolve_data_access_candidates(candidates)["resolved_uri"]
        if uri:
            requests[dataset_name] = {"selector": {"uris": [uri]}}
    return requests


def _resolve_data_access_candidates(candidates: list[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    resolved_uri: str | None = None
    for candidate in candidates:
        uri = _resolve_data_access_source_uri(candidate)
        results.append(
            {
                "source": candidate,
                "resolved_uri": uri,
                "available": bool(uri),
            }
        )
        if resolved_uri is None and uri:
            resolved_uri = uri
    return {"resolved_uri": resolved_uri, "candidates": results}


def _resolve_first_existing_data_access_uri(candidates: list[str]) -> str | None:
    for candidate in candidates:
        uri = _resolve_data_access_source_uri(candidate)
        if uri:
            return uri
    return None


def _resolve_data_access_source_uri(source: str) -> str | None:
    candidate = str(source).strip()
    if not candidate:
        return None
    if "://" in candidate:
        return _resolve_scheme_uri(candidate)
    if Path(candidate).is_absolute():
        absolute_path = Path(candidate)
        return str(absolute_path) if absolute_path.exists() else None

    resolved_path = _resolve_provider_dataset_path(candidate)
    if resolved_path is not None:
        return str(resolved_path)

    fallback_path = Path(settings.data_root) / Path(candidate)
    return str(fallback_path) if fallback_path.exists() else None


def _resolve_scheme_uri(uri: str) -> str | None:
    """Pass through http/minio/file; remote schemes require resolvable credentials."""
    from urllib.parse import urlparse

    from shared.remote_sources.uri import REMOTE_SCHEMES, parse_remote_uri

    scheme = (urlparse(uri).scheme or "").lower()
    if scheme == "gcs":
        scheme = "gs"
    if scheme not in REMOTE_SCHEMES:
        return uri

    try:
        parse_remote_uri(uri)
    except ValueError:
        return None

    try:
        from app.services.remote_auth_resolver import resolve_remote_auth

        auth = resolve_remote_auth(uri)
    except Exception:
        return None

    if settings.remote_readiness_probe:
        try:
            from shared.remote_sources.download import probe_remote_connectivity

            # Connectivity only — missing object must not block workflow readiness
            probe_remote_connectivity(uri, auth)
        except Exception:
            return None
    return uri


@lru_cache(maxsize=128)
def _resolve_provider_dataset_path(logical_name: str) -> Path | None:
    dataset_helpers = _load_provider_dataset_helpers()
    if dataset_helpers is None:
        return None

    resolve_dataset_path, get_dataset_info = dataset_helpers
    if callable(resolve_dataset_path):
        resolved = resolve_dataset_path(logical_name)
        if resolved is not None:
            return Path(str(resolved))

    if callable(get_dataset_info):
        info = get_dataset_info(logical_name)
        relative_path = getattr(info, "relative_path", None) if info is not None else None
        if relative_path:
            candidate = Path(settings.data_root) / Path(str(relative_path))
            if candidate.exists():
                return candidate

    return None


_provider_helpers_cache_lock = threading.Lock()

# 内部实现（无缓存）
def _load_provider_dataset_helpers_uncached() -> tuple[Any, Any] | None:
    import time
    start = time.time()
    logger = logging.getLogger(__name__)
    provider_root = Path(settings.python_provider_root)
    logger.info(f"[workflow_request_resolver] _load_provider_dataset_helpers start, root={provider_root}")
    if not provider_root.exists():
        logger.info(f"[workflow_request_resolver] _load_provider_dataset_helpers: root doesn't exist, returning None")
        return None

    try:
        import concurrent.futures

        def _import_dataset_config() -> Any:
            with _python_provider_import_path(provider_root):
                return importlib.import_module("dataset_config")

        # 添加超时保护，避免 dataset_config 导入挂起导致 /layers 端点响应缓慢
        logger.info(f"[workflow_request_resolver] _load_provider_dataset_helpers: starting import with timeout")
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_import_dataset_config)
            try:
                dataset_config = future.result(timeout=5.0)  # 5秒超时
                logger.info(f"[workflow_request_resolver] _load_provider_dataset_helpers: import succeeded after {time.time() - start:.1f}s")
            except concurrent.futures.TimeoutError:
                logger.warning("[workflow_request_resolver] _load_provider_dataset_helpers timed out after 5s")
                return None
    except Exception as e:
        logger.warning(f"[workflow_request_resolver] _load_provider_dataset_helpers exception: {e}")
        return None

    result = (
        getattr(dataset_config, "resolve_dataset_path", None),
        getattr(dataset_config, "get_dataset_info", None),
    )
    logger.info(f"[workflow_request_resolver] _load_provider_dataset_helpers done in {time.time() - start:.1f}s")
    return result


# 线程安全的缓存包装器
@lru_cache(maxsize=1)
def _load_provider_dataset_helpers() -> tuple[Any, Any] | None:
    with _provider_helpers_cache_lock:
        return _load_provider_dataset_helpers_uncached()


def warm_provider_helpers() -> bool:
    """在应用启动时预热 provider dataset helpers 缓存 + 各图层 readiness 检查。

    避免首次 /layers 请求时阻塞在 dataset_config 导入 + 数据源路径解析上。
    返回 True 表示成功加载，False 表示失败或跳过。
    """
    helpers = _load_provider_dataset_helpers()
    if helpers is None:
        return False

    # 预解析所有图层的 readiness，填充 _resolve_provider_dataset_path 的 lru_cache
    # 避免首次 /layers 的 8 并发 readiness 检查串行等待
    try:
        from app.services.layer_catalog import get_layer_catalog
        catalog = get_layer_catalog()
        for descriptor in catalog.items:
            try:
                describe_layer_run_readiness(descriptor.layer_id)
            except Exception:
                pass  # 个别图层 readiness 失败不影响整体预热
    except Exception:
        pass  # catalog 加载失败不影响 helpers 预热

    return True


@contextmanager
def _python_provider_import_path(provider_root: Path) -> Iterator[None]:
    provider_path = str(provider_root)
    inserted = False
    if provider_path not in sys.path:
        sys.path.insert(0, provider_path)
        inserted = True
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(provider_path)
            except ValueError:
                pass


# ── Engine Request Populator 实现 ──────────────────────────────────────────


class _PythonProviderPopulator:
    """python_provider 引擎的请求填充器。"""

    @property
    def engine_name(self) -> str:
        return "python_provider"

    def populate(
        self,
        *,
        payload: WorkflowSubmitRequest,
        layer_id: str,
        descriptor: Any,
    ) -> WorkflowSubmitRequest:
        return _populate_python_provider_request(payload=payload, descriptor=descriptor)

    def describe_resolution(self, payload: WorkflowSubmitRequest) -> dict[str, Any] | None:
        return _describe_python_provider_resolution_impl(payload)

    def describe_readiness(self, descriptor: Any) -> dict[str, Any] | None:
        if not descriptor.default_data_access_sources:
            return None
        unresolved: list[dict[str, Any]] = []
        for dataset_name, candidates in descriptor.default_data_access_sources.items():
            resolution = _resolve_data_access_candidates(candidates)
            if resolution["resolved_uri"] is not None:
                continue
            unresolved.append(
                {
                    "dataset_name": dataset_name,
                    "candidate_sources": [item["source"] for item in resolution["candidates"]],
                }
            )
        return {"unresolved_default_datasets": unresolved} if unresolved else None


class _GeePopulator:
    """gee 引擎的请求填充器。"""

    @property
    def engine_name(self) -> str:
        return "gee"

    def populate(
        self,
        *,
        payload: WorkflowSubmitRequest,
        layer_id: str,
        descriptor: Any,
    ) -> WorkflowSubmitRequest:
        return _populate_gee_request(payload=payload, layer_id=layer_id, descriptor=descriptor)

    def describe_resolution(self, payload: WorkflowSubmitRequest) -> dict[str, Any] | None:
        return None

    def describe_readiness(self, descriptor: Any) -> dict[str, Any] | None:
        return None


class _WeatherPopulator:
    """weather_workflow 引擎的请求填充器。"""

    @property
    def engine_name(self) -> str:
        return "weather_workflow"

    def populate(
        self,
        *,
        payload: WorkflowSubmitRequest,
        layer_id: str,
        descriptor: Any,
    ) -> WorkflowSubmitRequest:
        return _populate_weather_request(payload=payload, layer_id=layer_id, descriptor=descriptor)

    def describe_resolution(self, payload: WorkflowSubmitRequest) -> dict[str, Any] | None:
        return None

    def describe_readiness(self, descriptor: Any) -> dict[str, Any] | None:
        return None


# 模块加载时注册所有 populator
register_engine_populator(_PythonProviderPopulator())
register_engine_populator(_GeePopulator())
register_engine_populator(_WeatherPopulator())
