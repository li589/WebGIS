from __future__ import annotations

from contextlib import contextmanager, suppress
from datetime import date, datetime
from functools import lru_cache
import importlib
import logging
from pathlib import Path
import re
import sys
import threading
from typing import Any
from collections.abc import Iterator

from app.core import config
from app.services.engine_request_registry import (
    get_engine_populator,
    register_engine_populator,
)
from app.services.layer_catalog import get_layer_descriptor
from shared.contracts.api_contracts import WorkflowCommandType, WorkflowSubmitRequest

logger = logging.getLogger(__name__)

# 平台常量（模块级以便测试 monkeypatch；硬编码清理 A3）
_IS_WINDOWS = sys.platform == "win32"

_ALGORITHM_ENTRY_KEYS: tuple[str, ...] = (
    "module_name",
    "workflow_name",
    "workflow_definition",
)
_GEE_ENTRY_KEYS: tuple[str, ...] = ("workflow", "manifest_uri")
_WEATHER_ENTRY_KEYS: tuple[str, ...] = ("workflow",)

_DATE_PLACEHOLDER_RE = re.compile(r"\{((?:YYYY|yyyy|MM|mm|DD|dd)[^{}]*?)\}")


def _format_date_token(fmt: str, ref_date: date) -> str:
    result = fmt
    result = result.replace("YYYY", f"{ref_date.year:04d}")
    result = result.replace("yyyy", f"{ref_date.year:04d}")
    result = result.replace("MM", f"{ref_date.month:02d}")
    result = result.replace("mm", f"{ref_date.month:02d}")
    result = result.replace("DD", f"{ref_date.day:02d}")
    result = result.replace("dd", f"{ref_date.day:02d}")
    return result


def _expand_date_placeholders(value: Any, ref_date: date) -> Any:
    if isinstance(value, str):
        if "{" not in value:
            return value
        return _DATE_PLACEHOLDER_RE.sub(
            lambda m: _format_date_token(m.group(1), ref_date), value
        )
    if isinstance(value, dict):
        return {k: _expand_date_placeholders(v, ref_date) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_date_placeholders(v, ref_date) for v in value]
    return value


def _expand_data_root_placeholders(value: Any) -> Any:
    """展开 ``{DATA_ROOT}`` / ``{DATA_ROOT_WIN}`` 种子占位符。

    种子同步（workflow_definition_service）在落盘时展开，但经
    ``/workflow-definitions/compile`` 直传的画布定义保留字面占位符；
    提交边界须展开为 settings.data_root 绝对路径，否则 worker 侧
    算法收到不可解析的 ``{DATA_ROOT}/...`` 路径。
    """
    if isinstance(value, str):
        if "{DATA_ROOT" not in value:
            return value
        root = (getattr(config.settings, "data_root", None) or "").strip()
        if not root:
            return value
        root_posix = root.replace("\\", "/")
        # 跨平台（硬编码清理 A3）：非 Windows 下 {DATA_ROOT_WIN} 退化为
        # posix root（占位符名保留兼容旧种子/画布定义）——原
        # root.replace("/", "\\") 在 Linux data_root 下生成含反斜杠的非法路径。
        root_win = root_posix.replace("/", "\\") if _IS_WINDOWS else root_posix
        return value.replace("{DATA_ROOT_WIN}", root_win).replace(
            "{DATA_ROOT}", root_posix
        )
    if isinstance(value, dict):
        return {k: _expand_data_root_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_data_root_placeholders(v) for v in value]
    return value


def _get_ref_date_from_payload(payload: WorkflowSubmitRequest) -> date:
    tr = payload.time_range
    if tr and getattr(tr, "start_at", None):
        return tr.start_at.date()
    if tr and getattr(tr, "start", None):
        try:
            return datetime.fromisoformat(str(tr.start)).date()
        except (ValueError, TypeError):
            pass
    return date.today()


def normalize_workflow_submit_request(
    payload: WorkflowSubmitRequest,
) -> WorkflowSubmitRequest:
    """按 layer catalog 元数据补齐 bridge 所需请求字段。

    当前前端只提交 `layer_id + parameters + map_context`，而 Python provider bridge
    需要 `algorithm_request.module_name/workflow_name/workflow_definition` 才会接管。
    这里优先使用后端 `layer_catalog` 作为执行事实源，避免前端维护第二份 workflow 元数据。

    引擎分发通过 engine_request_registry 注册表完成，新增引擎只需注册 populator。

    若 ``layer_id`` 不在 catalog（例如种子 ``linked_layer_id`` 尚未入库、或仅带
    画布 ``workflow_definition`` 的编辑器提交），仍须从 algorithm_request /
    种子补齐 ``time_range``，否则 Python provider 会在 validate_job 处以
    ``Missing required field: job_request.time_range`` 失败。
    """

    if payload.command_type != WorkflowCommandType.analysis:
        return payload

    layer_id = payload.layer_id or payload.map_context.active_layer_id
    algorithm_request = _normalize_algorithm_request(payload.algorithm_request)
    has_algorithm_entry = any(
        algorithm_request.get(key) for key in _ALGORITHM_ENTRY_KEYS
    )

    descriptor = get_layer_descriptor(layer_id) if layer_id else None
    if descriptor is None or not descriptor.engine:
        if has_algorithm_entry:
            return _populate_python_provider_request(
                payload=payload,
                descriptor=_synthetic_descriptor_from_algorithm_request(
                    algorithm_request
                ),
            )
        return payload

    populator = get_engine_populator(descriptor.engine)
    if populator is None:
        return payload

    return populator.populate(payload=payload, layer_id=layer_id, descriptor=descriptor)


def describe_python_provider_resolution(
    payload: WorkflowSubmitRequest,
) -> dict[str, Any] | None:
    """公开 API：委托给 python_provider populator。"""
    populator = get_engine_populator("python_provider")
    if populator is None:
        return None
    return populator.describe_resolution(payload)


def _describe_python_provider_resolution_impl(
    payload: WorkflowSubmitRequest,
) -> dict[str, Any] | None:
    layer_id = payload.layer_id or payload.map_context.active_layer_id
    if not layer_id:
        return None

    descriptor = get_layer_descriptor(layer_id)
    if (
        descriptor is None
        or descriptor.engine != "python_provider"
        or not descriptor.module_name
    ):
        return None

    algorithm_request = _normalize_algorithm_request(payload.algorithm_request)
    datasource_selection = _normalize_request(
        algorithm_request.get("datasource_selection")
    )
    explicit_data_access_requests = _normalize_request(
        datasource_selection.get("_data_access_requests")
    )
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
        "task_type": algorithm_request.get("task_type")
        or descriptor.default_task_type
        or descriptor.module_name,
        "explicit_data_access_datasets": sorted(explicit_data_access_requests.keys()),
        "default_datasets": default_datasets,
        "unresolved_default_datasets": unresolved_default_datasets,
    }


def _portal_credential_profile_ready(profile: str) -> bool:
    """门户凭据 profile 就绪检查。

    语义对齐 ``Tools/smoke_system_workflows.py`` 的 ``portal_creds_ready``：
    门户 store 条目 enabled=false 忽略；token/access_token 或 username+password
    任一可用即就绪；支持多账号轮换条目（accounts[]）。
    """
    try:
        from app.services.config_service import get_portal_credentials_runtime

        store = get_portal_credentials_runtime() or {}
    except Exception:  # noqa: BLE001 — 凭据存储不可用时按未就绪处理
        return False
    entry = store.get(profile)
    if not isinstance(entry, dict) or entry.get("enabled") is False:
        return False
    if str(entry.get("token") or entry.get("access_token") or "").strip():
        return True
    user = str(entry.get("username") or "").strip()
    password = str(entry.get("password") or entry.get("secret") or "").strip()
    if user and password:
        return True
    for account in entry.get("accounts") or []:
        if not isinstance(account, dict):
            continue
        if str(account.get("token") or "").strip():
            return True
        account_user = str(account.get("username") or "").strip()
        account_password = str(account.get("password") or "").strip()
        if account_user and account_password:
            return True
    return False


def _variant_field(variant: Any, key: str, default: Any = None) -> Any:
    """读取变体字段，兼容 pydantic 对象与 dict 两种形态。"""
    if isinstance(variant, dict):
        return variant.get(key, default)
    return getattr(variant, key, default)


def _resolve_variant_workflow_entry(
    algorithm_request: dict[str, Any], descriptor: Any
) -> str | None:
    """X2 变体路由：解析本次提交应执行的变体种子 id。

    - FE 分析框切换注入 ``workflow_entry_name``（变体种子 id）：仅当与
      ``descriptor.workflow_variants`` 中声明的变体匹配时生效，未声明的
      entry 不路由（维持旧语义，交给后续兜底）；
    - 无显式选择：回落默认变体（``workflow_variants.online.workflow_id``，
      即 ω 反演图层默认在线执行）；
    - descriptor 未声明变体 → None（维持既有单变体/裸模块语义）。
    """
    variants = getattr(descriptor, "workflow_variants", None)
    if not isinstance(variants, dict) or not variants:
        return None
    entry = algorithm_request.get("workflow_entry_name")
    if entry:
        entry = str(entry)
        for variant in variants.values():
            if _variant_field(variant, "workflow_id") == entry:
                return entry
        return None
    online = variants.get("online")
    default_workflow = _variant_field(online, "workflow_id") if online else None
    return str(default_workflow) if default_workflow else None


def _describe_workflow_variant_readiness(
    descriptor: Any, unresolved_default_datasets: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """工作流变体二元就绪语义（X2）：在线凭据就绪 OR 本地数据可解析 → ready。

    仅对声明了 ``workflow_variants`` 的 descriptor 生效；返回 None 表示无变体
    （维持既有单变体语义）。返回体含 online_ready / local_ready / notes / summary。
    """
    variants = getattr(descriptor, "workflow_variants", None)
    if not variants:
        return None
    online = variants.get("online")
    local = variants.get("local")

    notes: list[str] = []
    online_ready = False
    if online is not None:
        profile = _variant_field(online, "credential_profile")
        if profile:
            online_ready = _portal_credential_profile_ready(profile)
            label = _variant_field(online, "label") or "在线反演"
            if online_ready:
                notes.append(f"{label}就绪（门户凭据 {profile} 可用，默认执行路径）。")
            else:
                notes.append(
                    f"{label}未就绪：缺少门户凭据 {profile}（可在设置中配置）。"
                )
        else:
            notes.append("在线变体未声明凭据 profile，按未就绪处理。")

    # 仅当声明了 local 变体时才评估本地就绪；单变体（仅 online）descriptor
    # 本地数据可解析也不得误报「本地反演可用」。
    local_ready = local is not None and not unresolved_default_datasets
    if local is not None:
        label = _variant_field(local, "label") or "本地反演"
        if local_ready:
            notes.append(f"{label}就绪（本地数据源可解析）。")
        else:
            missing = "、".join(
                item["dataset_name"] for item in unresolved_default_datasets
            )
            notes.append(f"{label}未就绪：本地数据源缺失（{missing}）。")

    if online_ready or local_ready:
        available = []
        if online_ready:
            available.append(_variant_field(online, "label") or "在线反演")
        if local_ready:
            available.append(_variant_field(local, "label") or "本地反演")
        summary = f"变体可用：{'、'.join(available)}（默认 {descriptor.workflow_id}）。"
        readiness = "ready"
    else:
        summary = "在线凭据与本地数据源均未就绪，无法执行反演。"
        readiness = "blocked"

    return {
        "readiness": readiness,
        "online_ready": online_ready,
        "local_ready": local_ready,
        "summary": summary,
        "notes": notes,
    }


def _describe_merged_group_readiness(descriptor: Any) -> dict[str, Any]:
    """合并组虚拟条目的就绪聚合：任一成员 ready 即 ready。

    合并组自身不对应实际数据资产（overlay_registry 中无对应 spec），
    就绪状态应由成员图层的 readiness 聚合得出。
    """
    notes = list(descriptor.run_readiness_notes)
    ready_members: list[str] = []
    blocked_members: list[str] = []
    for member_id in descriptor.members:
        member = get_layer_descriptor(member_id)
        if member is None or member.is_merged_group:
            blocked_members.append(member_id)
            continue
        member_result = describe_layer_run_readiness(member_id)
        member_status = (member_result or {}).get("run_readiness", "blocked")
        if member_status == "ready":
            ready_members.append(member_id)
        else:
            blocked_members.append(member_id)

    total = len(descriptor.members)
    readiness = "ready" if ready_members else "blocked"
    if ready_members:
        summary = f"合并组虚拟条目：{len(ready_members)}/{total} 个成员源就绪"
    else:
        summary = f"合并组虚拟条目：全部 {total} 个成员源未就绪"
    if blocked_members:
        notes.append(f"未就绪成员：{', '.join(blocked_members)}")
    return {
        "run_readiness": readiness,
        "run_readiness_summary": summary,
        "run_readiness_notes": notes,
        "unresolved_default_datasets": [],
    }


def describe_layer_run_readiness(layer_id: str) -> dict[str, Any] | None:
    descriptor = get_layer_descriptor(layer_id)
    if descriptor is None:
        return None

    if descriptor.is_merged_group and descriptor.members:
        return _describe_merged_group_readiness(descriptor)

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
                unresolved_default_datasets = engine_result.get(
                    "unresolved_default_datasets", []
                )

    # X2 变体二元语义：在线凭据就绪 OR 本地数据可解析 → ready（本地缺失不 block）
    variant_result = _describe_workflow_variant_readiness(
        descriptor, unresolved_default_datasets
    )

    if unresolved_default_datasets:
        if variant_result is not None and variant_result["online_ready"]:
            # 本地数据缺失但在线变体可用：保持 ready，说明走在线执行路径
            notes.extend(variant_result["notes"])
            summary = variant_result["summary"]
        else:
            readiness = "blocked"
            for item in unresolved_default_datasets:
                candidate_text = ", ".join(item["candidate_sources"]) or "未提供候选源"
                notes.append(
                    f"缺少默认数据集 {item['dataset_name']}；已检查：{candidate_text}"
                )
    elif variant_result is not None:
        notes.extend(variant_result["notes"])
        if variant_result["readiness"] == "blocked":
            readiness = "blocked"
        summary = variant_result["summary"]

    if unresolved_default_datasets and (
        variant_result is None or not variant_result["online_ready"]
    ):
        dataset_names = "、".join(
            item["dataset_name"] for item in unresolved_default_datasets
        )
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
    provider_root = Path(config.settings.python_provider_root)
    if not provider_root.exists():
        return {}
    try:
        with _python_provider_import_path(provider_root):
            deriver = importlib.import_module("contracts.template_deriver")
            return deriver.list_module_templates()
    except Exception:
        logger.debug(
            "Failed to load module templates from python provider", exc_info=True
        )
        return {}


def _get_module_request_template(module_name: str):
    """获取指定 module 的 RequestTemplateSpec，未找到返回 None。"""
    templates = _load_module_template_map()
    return templates.get(module_name)


def _node_props(node: dict[str, Any]) -> dict[str, Any]:
    """统一读取种子节点 properties 或编译节点 params。"""
    props = node.get("properties")
    if isinstance(props, dict) and props:
        return props
    params = node.get("params")
    if isinstance(params, dict) and params:
        return params
    return {}


def _node_module_name(node: dict[str, Any]) -> str:
    """识别节点逻辑类型：data/source、time_range、bbox、omega_sf_fenkuai 等。"""
    node_type = str(node.get("type") or "")
    if node_type.startswith("data/"):
        return node_type.split("/", 1)[-1]
    if node_type.startswith("module/"):
        return node_type.split("/", 1)[-1]
    if node_type.startswith("output/"):
        return node_type.split("/", 1)[-1]
    props = _node_props(node)
    module_name = props.get("module_name")
    if module_name:
        return str(module_name)
    return str(node.get("node_type") or "")


def _expand_seed_date_placeholder(value: str, ref: Any) -> str:
    """展开种子 time_range 节点的日期占位符（无 ref 时用当天）。

    在线种子的 start/end 常为 ``{YYYY-MM-DD}T00:00:00`` 字面占位符
    （默认=提交当天）。此前 ``_extract_time_range_from_nodes`` 直接
    ``fromisoformat`` 解析占位符抛 ValueError → time_range 静默 None →
    layer_id-only 提交缺 time_range → 下游参数校验报一堆无效
    （用户报障 2026-08-22「流水线配置时间范围后运行直接出错」根因）。
    """
    from datetime import date as _date

    if "{YYYY-MM-DD}" in value:
        base = ref if isinstance(ref, _date) else _date.today()
        return value.replace("{YYYY-MM-DD}", base.isoformat())
    if "{YYYYMMDD}" in value:
        base = ref if isinstance(ref, _date) else _date.today()
        return value.replace("{YYYYMMDD}", base.strftime("%Y%m%d"))
    return value


def _extract_time_range_from_nodes(nodes: list[Any] | None, ref_date: Any = None):
    """从 data/time_range（或编译后的 time_range 模块）节点提取 TimeRange。"""
    if not nodes:
        return None
    try:
        from datetime import datetime

        from shared.contracts.api_contracts import TimeGranularity, TimeRange

        for node in nodes:
            if not isinstance(node, dict):
                continue
            if _node_module_name(node) != "time_range":
                continue
            props = _node_props(node)
            start_str = props.get("start_at")
            end_str = props.get("end_at")
            if not start_str or not end_str:
                continue
            start_dt = datetime.fromisoformat(
                _expand_seed_date_placeholder(str(start_str), ref_date)
            )
            end_dt = datetime.fromisoformat(
                _expand_seed_date_placeholder(str(end_str), ref_date)
            )
            granularity_str = str(props.get("granularity") or "day")
            try:
                granularity = TimeGranularity(granularity_str)
            except ValueError:
                granularity = TimeGranularity.day
            return TimeRange(start_at=start_dt, end_at=end_dt, granularity=granularity)
    except Exception:
        logger.debug("Failed to extract time_range from nodes", exc_info=True)
    return None


def _extract_time_range_from_seed(workflow_name: str):
    """从工作流种子的 data/time_range 节点提取 TimeRange。

    前端 UI 提交工作流时不带 time_range，Python provider 的 validate_job
    要求 job_request.time_range 必填。这里从种子中读取默认值填充。
    """
    try:
        from app.services.workflow_definition_service import get_definition

        definition = get_definition(workflow_name)
        if not definition:
            return None
        return _extract_time_range_from_nodes(definition.get("nodes"))
    except Exception:
        logger.debug("Failed to extract time_range from seed", exc_info=True)
    return None


def _resolve_missing_time_range(
    *,
    payload: WorkflowSubmitRequest,
    algorithm_request: dict[str, Any],
    descriptor: Any,
):
    """UI 提交常缺 time_range：从画布定义 / entry 名 / 图层种子补齐。"""
    if payload.time_range is not None:
        return None

    workflow_definition = algorithm_request.get("workflow_definition")
    if isinstance(workflow_definition, dict):
        from_nodes = _extract_time_range_from_nodes(workflow_definition.get("nodes"))
        if from_nodes is not None:
            return from_nodes

    tags = algorithm_request.get("tags")
    tag_workflow_id = tags.get("workflow_id") if isinstance(tags, dict) else None
    candidates = (
        algorithm_request.get("workflow_entry_name"),
        algorithm_request.get("workflow_name"),
        tag_workflow_id,
        getattr(descriptor, "workflow_name", None),
    )
    for name in candidates:
        if not name:
            continue
        from_seed = _extract_time_range_from_seed(str(name))
        if from_seed is not None:
            return from_seed
    return None


def _extract_bbox_from_nodes(nodes: list[Any] | None):
    """从 data/bbox（或编译后的 bbox 模块）节点提取 SpatialFilter。"""
    if not nodes:
        return None
    try:
        from shared.contracts.api_contracts import BoundingBox, SpatialFilter

        for node in nodes:
            if not isinstance(node, dict):
                continue
            if _node_module_name(node) != "bbox":
                continue
            props = _node_props(node)
            required = ("west", "south", "east", "north")
            if any(props.get(k) is None for k in required):
                continue
            bbox = BoundingBox(
                west=float(props["west"]),
                south=float(props["south"]),
                east=float(props["east"]),
                north=float(props["north"]),
                crs=str(props.get("crs") or "EPSG:4326"),
            )
            return SpatialFilter(filter_type="bbox", bbox=bbox)
    except Exception:
        logger.debug("Failed to extract bbox from nodes", exc_info=True)
    return None


def _extract_algorithm_params_from_nodes(
    nodes: list[Any] | None,
) -> dict[str, Any] | None:
    """从画布算法模块节点读取 algorithm_params。"""
    if not nodes:
        return None
    skip = {"data_source", "time_range", "bbox", "output_map_layer", "module"}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        module_name = _node_module_name(node)
        node_type = str(node.get("type") or "")
        # 种子：module/*；编译：params.module_name=算法名
        if node_type.startswith("module/") or (
            module_name and module_name not in skip and module_name != "module"
        ):
            props = _node_props(node)
            params = props.get("algorithm_params")
            if isinstance(params, dict) and params:
                return dict(params)
    return None


def _extract_datasource_selection_from_nodes(
    nodes: list[Any] | None,
) -> dict[str, Any]:
    """从 data/source（或编译后的 data_source 模块）提取 datasource_selection。"""
    selection: dict[str, Any] = {}
    if not nodes:
        return selection
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if _node_module_name(node) not in {"source", "data_source"}:
            continue
        props = _node_props(node)
        key = props.get("dataset_key") or props.get("key")
        path = props.get("path") or props.get("uri") or props.get("value")
        if path:
            # Generic analysis modules read datasource_selection.input_path
            selection.setdefault("input_path", str(path))
        if key and path:
            selection[str(key)] = str(path)
    return selection


@lru_cache(maxsize=1)
def _registry_type_by_node_class() -> dict[str, str]:
    """node_class → 注册表规范 type 映射（如 ssh_sync → download/ssh_sync）。

    compile_litegraph_to_workflow_definition 将 download/* 编译为
    node_type="module" + params.module_name=<node_class>，原始前缀丢失；
    借注册表反查以恢复 download/stats/viz 类别判断。
    """
    from app.services.node_template_registry import get_all_node_templates

    mapping: dict[str, str] = {}
    for template in get_all_node_templates():
        node_class = str(template.get("node_class") or "")
        node_type = str(template.get("type") or "")
        if node_class and node_type:
            mapping.setdefault(node_class, node_type)
    return mapping


def _executable_node_types(nodes: list[Any] | None) -> list[str]:
    """List raw node types of executable nodes, excluding canvas metadata helpers."""
    scrape_only = {
        "data_source",
        "source",
        "time_range",
        "bbox",
        "number_const",
        "string_const",
        "boolean_const",
        "latlng",
        "map_viewport",
        "output_map_layer",
        "output_file",
    }
    types: list[str] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        module_name = _node_module_name(node).strip()
        if module_name in scrape_only:
            continue
        ntype = str(node.get("type") or node.get("node_type") or "")
        if (
            ntype.startswith("module/")
            or ntype.startswith("download/")
            or ntype.startswith("stats/")
            or ntype.startswith("viz/")
        ):
            types.append(ntype)
            continue
        # Compiled form: node_type=module + params.module_name=<node_class>.
        # 反查注册表恢复规范 type（download/* 判定依赖前缀），查不到退化为 module/*。
        if str(node.get("node_type") or "") == "module" and module_name not in {
            "",
            "module",
        }:
            types.append(
                _registry_type_by_node_class().get(module_name, f"module/{module_name}")
            )
    return types


def _count_executable_module_nodes(nodes: list[Any] | None) -> int:
    """Count algorithm/module nodes, excluding canvas metadata helpers."""
    return len(_executable_node_types(nodes))


def _flatten_ui_workflow_definition(
    algorithm_request: dict[str, Any],
    *,
    descriptor: Any,
) -> tuple[dict[str, Any], Any, Any]:
    """将 UI 画布 workflow_definition 展平为种子式 algorithm_request。

    单模块画布：展平为 module_name + algorithm_params + datasource_selection。
    多模块 DAG（如 timeseries_bundle → omega_block）：保留 workflow_definition，
    仅合并 data/source 到 datasource_selection，避免丢掉模块间边。
    """
    workflow_definition = algorithm_request.get("workflow_definition")
    if not isinstance(workflow_definition, dict):
        return algorithm_request, None, None

    nodes = workflow_definition.get("nodes")
    canvas_params = _extract_algorithm_params_from_nodes(nodes)
    time_range = _extract_time_range_from_nodes(nodes)
    spatial = _extract_bbox_from_nodes(nodes)

    ref_date = date.today()
    if time_range and getattr(time_range, "start_at", None):
        ref_date = time_range.start_at.date()

    existing_ds = algorithm_request.get("datasource_selection")
    if not isinstance(existing_ds, dict):
        existing_ds = {}
    canvas_ds = _extract_datasource_selection_from_nodes(nodes)
    for key, value in canvas_ds.items():
        existing_ds.setdefault(key, value)
    for key, value in list(existing_ds.items()):
        if key.startswith("_") or not isinstance(value, str) or not value.strip():
            continue
        expanded = _expand_data_root_placeholders(
            _expand_date_placeholders(value, ref_date)
        )
        if expanded != value:
            existing_ds[key] = expanded
            value = expanded
    for key, value in list(existing_ds.items()):
        if key.startswith("_") or not isinstance(value, str) or not value.strip():
            continue
        if Path(value).is_absolute() and Path(value).exists():
            continue
        resolved = _resolve_data_access_source_uri(value)
        if resolved:
            existing_ds[key] = resolved

    existing_params = algorithm_request.get("algorithm_params")
    if not isinstance(existing_params, dict):
        existing_params = {}

    # Multi-module graph: keep executable definition; only enrich request fields.
    # 数据获取节点（download/*）承载拉取参数（server_type/remote_path/日期过滤），
    # 展平会丢弃这些参数并把请求错配为层描述符默认 module（如 fy_tb_nas_read
    # 跳过预处理直连 map_layer 的单 ssh_sync 形态）；含任一即保留整图执行。
    executable_types = _executable_node_types(nodes)
    keep_graph = len(executable_types) >= 2 or any(
        t.startswith("download/") for t in executable_types
    )

    if canvas_params and not keep_graph:
        merged = dict(canvas_params)
        merged.update(existing_params)
        existing_params = merged
    if spatial is not None and getattr(spatial, "bbox", None) is not None:
        bbox = spatial.bbox
        existing_params.setdefault("bbox_west", float(bbox.west))
        existing_params.setdefault("bbox_south", float(bbox.south))
        existing_params.setdefault("bbox_east", float(bbox.east))
        existing_params.setdefault("bbox_north", float(bbox.north))
        existing_params.setdefault(
            "bbox", [bbox.west, bbox.south, bbox.east, bbox.north]
        )

    # 图执行路径：请求级 algorithm_params 仅保留用户覆盖（首模块提取已在上方
    # 剥离），节点级 properties.algorithm_params 由算法侧 executor 以节点基底
    # 合并，避免首模块参数（如 fy_daily 的 orbit_mode）泄漏进其余模块。
    if keep_graph:
        enriched = dict(algorithm_request)
        enriched["datasource_selection"] = existing_ds
        enriched["algorithm_params"] = existing_params
        enriched.setdefault("output_spec", {})
        if "workflow_definition" in enriched:
            enriched["workflow_definition"] = _expand_data_root_placeholders(
                _expand_date_placeholders(enriched["workflow_definition"], ref_date)
            )
        # Bridge rejects workflow_definition + module_name together; keep graph only.
        enriched.pop("module_name", None)
        # Bridge builds job_request from algorithm_request; keep time_range there too
        # so worker validate_job still sees it if top-level payload.time_range is dropped.
        if time_range is not None and "time_range" not in enriched:
            enriched["time_range"] = {
                "start": time_range.start_at.isoformat(),
                "end": time_range.end_at.isoformat(),
            }
        return enriched, time_range, spatial

    flat = {
        key: value
        for key, value in algorithm_request.items()
        if key not in {"workflow_definition", "workflow_name"}
    }
    inferred_module = _infer_primary_module_name(
        nodes if isinstance(nodes, list) else None
    )
    flat.setdefault(
        "module_name",
        getattr(descriptor, "module_name", None) or inferred_module,
    )
    flat.setdefault(
        "task_type",
        getattr(descriptor, "default_task_type", None)
        or getattr(descriptor, "module_name", None)
        or inferred_module,
    )
    flat.setdefault(
        "workflow_entry_name",
        algorithm_request.get("workflow_entry_name")
        or getattr(descriptor, "workflow_name", None)
        or getattr(descriptor, "module_name", None)
        or inferred_module,
    )
    flat["algorithm_params"] = existing_params
    flat["datasource_selection"] = existing_ds
    flat.setdefault("output_spec", {})
    return flat, time_range, spatial


def _compile_workflow_seed(workflow_name: str) -> dict[str, Any] | None:
    """编译工作流种子，返回 compiled workflow_definition。

    用于将种子的 algorithm_params（如 tb_source）传递到模块执行。

    编译后过滤无效 edge：node_template_registry 会为模块节点添加 time_range/bbox
    等"元输入端口"，但 Python provider 的模块签名不包含它们。这些值通过
    job_request.time_range / job_request.region 在请求级别传递，不走 workflow edge。
    同时合并重复的 datasource_selection edge（多个 data/source → 同一端口）为
    input_bindings，只保留第一条 edge。
    """
    try:
        from app.services.workflow_definition_service import get_definition
        from app.services.workflow_graph_compiler import (
            compile_litegraph_to_workflow_definition,
        )

        definition = get_definition(workflow_name)
        if not definition:
            return None
        compiled = compile_litegraph_to_workflow_definition(
            workflow_id=workflow_name,
            name=definition.get("name"),
            description=definition.get("description"),
            nodes=definition.get("nodes", []),
            links=definition.get("links", []),
        )

        _filter_invalid_edges(compiled)

        # 透传种子 extra（outputs/group_title/output_labels 等）到 compiled
        # workflow_definition——前端建组命名（extra.group_title/output_labels
        # 中文配置，2026-08-22 需求2）与产出标签推导依赖该字段；此前编译器
        # 丢弃 extra，配置静默失效。
        seed_extra = definition.get("extra")
        if isinstance(seed_extra, dict) and seed_extra:
            compiled["extra"] = dict(seed_extra)

        return compiled
    except Exception:
        logger.debug("Failed to compile workflow seed", exc_info=True)
        return None


def _seed_uses_graph_execution(workflow_name: str) -> bool:
    """判断种子是否按图执行（多模块或含 download/* 节点）。

    图执行种子的节点级 properties.algorithm_params 由算法侧 executor 以节点
    基底合并；请求级不应再注入首模块提取，否则首模块参数泄漏进其余模块。
    """
    try:
        from app.services.workflow_definition_service import get_definition

        definition = get_definition(workflow_name)
        if not definition:
            return False
        executable_types = _executable_node_types(definition.get("nodes"))
        return len(executable_types) >= 2 or any(
            t.startswith("download/") for t in executable_types
        )
    except Exception:
        logger.debug("Failed to inspect seed graph shape", exc_info=True)
        return False


def _extract_algorithm_params_from_seed(workflow_name: str) -> dict[str, Any] | None:
    """从工作流种子的模块节点 properties 中提取 algorithm_params。

    比 _compile_workflow_seed 更轻量：不编译完整 graph，只读取种子的节点属性。
    用于将 algorithm_params（如 tb_source=SMAP）直接合并到 algorithm_request，
    避免设置 workflow_definition 导致 executor 处理 graph 时出现 datasource_selection
    多重绑定问题。
    """
    try:
        from app.services.workflow_definition_service import get_definition

        definition = get_definition(workflow_name)
        if not definition:
            return None
        for node in definition.get("nodes", []):
            node_type = node.get("type") or node.get("node_type") or ""
            if not node_type.startswith("module/"):
                continue
            props = node.get("properties") or {}
            params = props.get("algorithm_params")
            if isinstance(params, dict) and params:
                return dict(params)
        return None
    except Exception:
        logger.debug("Failed to extract algorithm_params from seed", exc_info=True)
        return None


# 这些端口由 job_request 级别处理，不应出现在 workflow edge 中
_NON_EDGE_PORTS = frozenset({"time_range", "bbox", "region"})


def _filter_invalid_edges(compiled: dict[str, Any]) -> None:
    """从编译后的 workflow_definition 中移除引用不存在输入端口的 edge。

    仅过滤 time_range/bbox/region 等由 job_request 级别处理的端口。
    保留所有其他 edge（包括重复连接到同一端口的多条 edge，
    因为多个 data/source 节点可能都连接到 datasource_selection）。
    """
    raw_edges = compiled.get("edges") or []
    if not raw_edges:
        return

    filtered: list[dict[str, str]] = []
    for edge in raw_edges:
        to_port = edge.get("to_port", "")

        # 跳过由 job_request 级别处理的端口
        if to_port in _NON_EDGE_PORTS:
            continue

        filtered.append(edge)

    compiled["edges"] = filtered


def _infer_primary_module_name(nodes: list[Any] | None) -> str | None:
    """从画布节点推断主算法 module_name（跳过 data/output 辅助节点）。"""
    skip = {
        "",
        "source",
        "data_source",
        "time_range",
        "bbox",
        "map_layer",
        "output_map_layer",
        "module",
        "workflow",
    }
    if not nodes:
        return None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = _node_module_name(node)
        if name and name not in skip:
            return name
    return None


def _synthetic_descriptor_from_algorithm_request(algorithm_request: dict[str, Any]):
    """catalog 缺失时，用 algorithm_request / 画布节点拼最小 descriptor。"""

    class _SyntheticDescriptor:
        engine = "python_provider"
        module_name: str | None = None
        workflow_name: str | None = None
        default_task_type: str | None = None
        default_data_access_sources: dict[str, list[str]] = {}
        status = "available"

    stub = _SyntheticDescriptor()
    stub.module_name = (
        str(algorithm_request["module_name"])
        if algorithm_request.get("module_name")
        else None
    )
    tags = algorithm_request.get("tags")
    tag_workflow_id = tags.get("workflow_id") if isinstance(tags, dict) else None
    stub.workflow_name = (
        (
            str(algorithm_request["workflow_name"])
            if algorithm_request.get("workflow_name")
            else None
        )
        or (
            str(algorithm_request["workflow_entry_name"])
            if algorithm_request.get("workflow_entry_name")
            else None
        )
        or (str(tag_workflow_id) if tag_workflow_id else None)
    )
    wf_def = algorithm_request.get("workflow_definition")
    if not stub.module_name and isinstance(wf_def, dict):
        stub.module_name = _infer_primary_module_name(wf_def.get("nodes"))
    stub.default_task_type = stub.module_name
    stub.default_data_access_sources = {}
    return stub


def _populate_python_provider_request(
    *, payload: WorkflowSubmitRequest, descriptor
) -> WorkflowSubmitRequest:
    algorithm_request = _normalize_algorithm_request(payload.algorithm_request)
    # X2 变体路由：变体选择（FE 注入 workflow_entry_name）或默认在线变体翻译为
    # workflow_name 入口键，由下方种子分支补齐 time_range、bridge 的种子编译接管
    # 图执行。否则后续 setdefault(module_name) 会遮蔽变体选择，退化为裸模块
    # 路径（变体切换失效根因）。显式 module_name/workflow_definition 提交
    # （画布/编辑器）不参与翻译，保持原优先级。
    if not any(
        algorithm_request.get(key)
        for key in ("module_name", "workflow_name", "workflow_definition")
    ):
        variant_entry = _resolve_variant_workflow_entry(algorithm_request, descriptor)
        if variant_entry:
            algorithm_request["workflow_name"] = variant_entry
    has_algorithm_entry = any(
        algorithm_request.get(key) for key in _ALGORITHM_ENTRY_KEYS
    )
    if not getattr(descriptor, "module_name", None) and not has_algorithm_entry:
        return payload

    canvas_time_range = None
    canvas_spatial = None
    if algorithm_request.get("workflow_definition"):
        # UI 画布提交：展平为种子式请求，避免多 datasource edge / 元端口校验失败
        algorithm_request, canvas_time_range, canvas_spatial = (
            _flatten_ui_workflow_definition(algorithm_request, descriptor=descriptor)
        )
        updates: dict[str, Any] = {"algorithm_request": algorithm_request}
        if payload.time_range is None and canvas_time_range is not None:
            updates["time_range"] = canvas_time_range
        if payload.spatial_filter is None and canvas_spatial is not None:
            updates["spatial_filter"] = canvas_spatial
        payload = payload.model_copy(update=updates)
        # 多模块 DAG 保留 workflow_definition：此处必须返回，否则下方会用
        # descriptor.module_name 再 setdefault 回 module_name，触发 bridge 互斥校验。
        if isinstance(algorithm_request.get("workflow_definition"), dict):
            resolved_tr = _resolve_missing_time_range(
                payload=payload,
                algorithm_request=algorithm_request,
                descriptor=descriptor,
            )
            if resolved_tr is not None and payload.time_range is None:
                payload = payload.model_copy(update={"time_range": resolved_tr})
            return payload
    elif algorithm_request.get("workflow_name"):
        # 仅声明 workflow_name、无 definition：仍补齐 time_range 后交由种子路径
        resolved_tr = _resolve_missing_time_range(
            payload=payload,
            algorithm_request=algorithm_request,
            descriptor=descriptor,
        )
        if resolved_tr is not None:
            payload = payload.model_copy(update={"time_range": resolved_tr})
        ref_date = _get_ref_date_from_payload(payload)
        algorithm_request = _expand_date_placeholders(algorithm_request, ref_date)
        payload = payload.model_copy(update={"algorithm_request": algorithm_request})
        return payload

    descriptor_module = getattr(descriptor, "module_name", None)
    explicit_module_name = algorithm_request.get("module_name")
    if (
        explicit_module_name
        and descriptor_module
        and explicit_module_name != descriptor_module
    ):
        updates = {}
        resolved_tr = _resolve_missing_time_range(
            payload=payload,
            algorithm_request=algorithm_request,
            descriptor=descriptor,
        )
        if resolved_tr is not None:
            updates["time_range"] = resolved_tr
        return payload.model_copy(update=updates) if updates else payload

    if not descriptor_module and not algorithm_request.get("module_name"):
        # 画布已展平但仍无 module：至少补齐 time_range，避免 validate_job 直接炸
        updates = {}
        resolved_tr = _resolve_missing_time_range(
            payload=payload,
            algorithm_request=algorithm_request,
            descriptor=descriptor,
        )
        if resolved_tr is not None:
            updates["time_range"] = resolved_tr
        if algorithm_request:
            updates["algorithm_request"] = algorithm_request
        return payload.model_copy(update=updates) if updates else payload

    algorithm_request.setdefault(
        "task_type",
        getattr(descriptor, "default_task_type", None)
        or descriptor_module
        or algorithm_request.get("module_name"),
    )

    # 如果图层有 workflow_name，从种子中提取 algorithm_params（如 tb_source=SMAP）
    # 直接合并到 algorithm_request，避免设置 workflow_definition 导致 executor
    # 处理 graph 时出现 datasource_selection 多重绑定问题。
    # 图执行种子（多模块/含下载节点）例外：节点级 params 由算法侧 executor 以
    # 节点基底合并，请求级注入首模块提取会造成跨模块参数泄漏。
    descriptor_workflow = getattr(descriptor, "workflow_name", None)
    effective_module = descriptor_module or algorithm_request.get("module_name")
    if descriptor_workflow:
        seed_graph_execution = _seed_uses_graph_execution(str(descriptor_workflow))
        if not seed_graph_execution:
            seed_params = _extract_algorithm_params_from_seed(str(descriptor_workflow))
            if seed_params is not None:
                existing_params = algorithm_request.get("algorithm_params")
                if not isinstance(existing_params, dict):
                    existing_params = {}
                    algorithm_request["algorithm_params"] = existing_params
                for k, v in seed_params.items():
                    existing_params.setdefault(k, v)
        if effective_module:
            algorithm_request.setdefault("module_name", effective_module)
        algorithm_request.setdefault(
            "workflow_entry_name",
            descriptor_workflow or effective_module,
        )
    else:
        if effective_module:
            algorithm_request.setdefault("module_name", effective_module)
            algorithm_request.setdefault("workflow_entry_name", effective_module)

    # 展开种子 algorithm_params 中的日期占位符
    _ref_date = _get_ref_date_from_payload(payload)
    if isinstance(algorithm_request.get("algorithm_params"), dict):
        algorithm_request["algorithm_params"] = _expand_date_placeholders(
            algorithm_request["algorithm_params"], _ref_date
        )

    datasource_selection = _normalize_request(
        algorithm_request.get("datasource_selection")
    )
    data_access_requests = _normalize_request(
        datasource_selection.get("_data_access_requests")
    )
    default_data_access = _build_default_data_access_requests(
        getattr(descriptor, "default_data_access_sources", None) or {}
    )
    for dataset_name, request_payload in default_data_access.items():
        data_access_requests.setdefault(dataset_name, request_payload)
    if data_access_requests:
        datasource_selection["_data_access_requests"] = data_access_requests

    # 根据模板的 accepted_data_access_by_required_key 把 dataset URI 映射到 required_key
    # 修复：模板验证检查 datasource_selection 中有 input_dir 等键，
    # 但 _data_access_requests 中用的是 dataset_name（如 NDVI_16DAY_RASTER）。
    # 需要把解析到的 URI 也设置到 datasource_selection[required_key] 中。
    template_module = str(
        algorithm_request.get("module_name") or descriptor_module or ""
    )
    template = (
        _get_module_request_template(template_module) if template_module else None
    )
    if template is not None and template.accepted_data_access_by_required_key:
        for (
            required_key,
            accepted_datasets,
        ) in template.accepted_data_access_by_required_key.items():
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

    # 展开日期占位符 {YYYY.MM.DD} 等（种子 uri/relative_path 中的模板）
    ref_date = _ref_date
    for key, value in list(datasource_selection.items()):
        if isinstance(value, str) and "{" in value:
            expanded = _expand_data_root_placeholders(
                _expand_date_placeholders(value, ref_date)
            )
            if expanded != value:
                datasource_selection[key] = expanded
    if isinstance(algorithm_request.get("workflow_definition"), dict):
        algorithm_request["workflow_definition"] = _expand_data_root_placeholders(
            _expand_date_placeholders(
                algorithm_request["workflow_definition"], ref_date
            )
        )

    # 显式相对路径（画布/种子）→ 绝对本地 URI，供 omega_sf 读 IGPB 等
    for key, value in list(datasource_selection.items()):
        if key.startswith("_") or not isinstance(value, str) or not value.strip():
            continue
        if Path(value).is_absolute() and Path(value).exists():
            continue
        resolved = _resolve_data_access_source_uri(value)
        if resolved:
            datasource_selection[key] = resolved

    if datasource_selection:
        algorithm_request["datasource_selection"] = datasource_selection

    # 从画布/种子补齐 time_range（前端 UI 提交时常缺该字段）
    updates: dict[str, Any] = {"algorithm_request": algorithm_request}
    resolved_tr = _resolve_missing_time_range(
        payload=payload,
        algorithm_request=algorithm_request,
        descriptor=descriptor,
    )
    if resolved_tr is not None:
        updates["time_range"] = resolved_tr

    return payload.model_copy(update=updates)


def _populate_gee_request(
    *, payload: WorkflowSubmitRequest, layer_id: str, descriptor
) -> WorkflowSubmitRequest:
    if not descriptor.workflow_definition:
        return payload

    gee_request = _normalize_request(payload.gee_request)
    if any(gee_request.get(key) for key in _GEE_ENTRY_KEYS):
        return payload

    gee_request.setdefault("workflow", descriptor.workflow_definition)
    gee_request.setdefault(
        "workflow_id", descriptor.workflow_id or descriptor.workflow_name or layer_id
    )
    return payload.model_copy(update={"gee_request": gee_request})


def _populate_weather_request(
    *, payload: WorkflowSubmitRequest, layer_id: str, descriptor
) -> WorkflowSubmitRequest:
    if not descriptor.workflow_definition:
        return payload

    weather_request = _normalize_request(payload.weather_request)
    if any(weather_request.get(key) for key in _WEATHER_ENTRY_KEYS):
        return payload

    weather_request.setdefault("workflow", descriptor.workflow_definition)
    weather_request.setdefault(
        "workflow_id", descriptor.workflow_id or descriptor.workflow_name or layer_id
    )
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


def _build_default_data_access_requests(
    source_map: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
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

    # 路径别名：FY3D_TB / SMAP_ancillary 等 → 本地 catalog 目录
    normalized = _normalize_provider_relative_path(candidate)
    if normalized != candidate:
        alias_resolved = _resolve_provider_dataset_path(normalized)
        if alias_resolved is not None:
            return str(alias_resolved)
        alias_fallback = Path(config.settings.data_root) / Path(normalized)
        if alias_fallback.exists():
            return str(alias_fallback)

    fallback_path = Path(config.settings.data_root) / Path(candidate)
    return str(fallback_path) if fallback_path.exists() else None


def _normalize_provider_relative_path(path: str) -> str:
    """Normalize historical seed paths via provider dataset_config aliases."""
    try:
        import importlib

        # Ensure provider root is importable (helpers load already does this)
        _load_provider_dataset_helpers()
        mod = importlib.import_module("dataset_config")
        normalize = getattr(mod, "normalize_dataset_relative_path", None)
        if callable(normalize):
            return str(normalize(path))
    except Exception:
        return path
    return path


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

    if config.settings.remote_readiness_probe:
        try:
            from shared.remote_sources.download import probe_remote_connectivity

            # Connectivity only — missing object must not block workflow readiness
            probe_remote_connectivity(uri, auth)
        except Exception:
            return None
    return uri


@lru_cache(maxsize=128)
def _resolve_provider_dataset_path(logical_name: str) -> Path | None:
    # 可用数据集注册表优先（运行时可编辑；写操作经 invalidate_template_cache 失效本缓存）
    try:
        from app.services.dataset_registry_service import (
            resolve_dataset_path as _registry_resolve,
        )

        registry_path = _registry_resolve(logical_name)
        if registry_path is not None:
            return registry_path
    except Exception:  # noqa: BLE001 — 注册表不可用不应阻断既有解析链路
        pass

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
        relative_path = (
            getattr(info, "relative_path", None) if info is not None else None
        )
        if relative_path:
            candidate = Path(config.settings.data_root) / Path(str(relative_path))
            if candidate.exists():
                return candidate

    return None


_provider_helpers_cache_lock = threading.Lock()


# 内部实现（无缓存）
def _load_provider_dataset_helpers_uncached() -> tuple[Any, Any] | None:
    import time

    start = time.time()
    logger = logging.getLogger(__name__)
    provider_root = Path(config.settings.python_provider_root)
    logger.info(
        f"[workflow_request_resolver] _load_provider_dataset_helpers start, root={provider_root}"
    )
    if not provider_root.exists():
        logger.info(
            "[workflow_request_resolver] _load_provider_dataset_helpers: root doesn't exist, returning None"
        )
        return None

    try:
        import concurrent.futures

        def _import_dataset_config() -> Any:
            with _python_provider_import_path(provider_root):
                return importlib.import_module("dataset_config")

        # 添加超时保护，避免 dataset_config 导入挂起导致 /layers 端点响应缓慢
        logger.info(
            "[workflow_request_resolver] _load_provider_dataset_helpers: starting import with timeout"
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_import_dataset_config)
            try:
                dataset_config = future.result(timeout=5.0)  # 5秒超时
                logger.info(
                    f"[workflow_request_resolver] _load_provider_dataset_helpers: import succeeded after {time.time() - start:.1f}s"
                )
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "[workflow_request_resolver] _load_provider_dataset_helpers timed out after 5s"
                )
                return None
    except Exception as e:
        logger.warning(
            f"[workflow_request_resolver] _load_provider_dataset_helpers exception: {e}"
        )
        return None

    result = (
        getattr(dataset_config, "resolve_dataset_path", None),
        getattr(dataset_config, "get_dataset_info", None),
    )
    logger.info(
        f"[workflow_request_resolver] _load_provider_dataset_helpers done in {time.time() - start:.1f}s"
    )
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
            with suppress(Exception):
                describe_layer_run_readiness(
                    descriptor.layer_id
                )  # 个别图层 readiness 失败不影响整体预热
    except Exception:
        pass  # catalog 加载失败不影响 helpers 预热

    return True


def invalidate_template_cache() -> None:
    """P1-3：清除所有 lru_cache 缓存，使后续调用重新从磁盘加载。

    在以下场景需手动调用：
    - 修改了 MODULE_REQUEST_TEMPLATES 后（需 FastAPI 进程重启才能生效，此函数用于不重启时强制刷新）
    - 修改了 provider dataset 配置后
    - 修改了 provider dataset helpers 后
    - admin 通过 API 端点主动刷新
    """
    _load_module_template_map.cache_clear()
    _resolve_provider_dataset_path.cache_clear()
    _load_provider_dataset_helpers.cache_clear()
    logger = logging.getLogger(__name__)
    logger.info("workflow_request_resolver caches invalidated")


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
            with suppress(ValueError):
                sys.path.remove(provider_path)


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

    def describe_resolution(
        self, payload: WorkflowSubmitRequest
    ) -> dict[str, Any] | None:
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
                    "candidate_sources": [
                        item["source"] for item in resolution["candidates"]
                    ],
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
        return _populate_gee_request(
            payload=payload, layer_id=layer_id, descriptor=descriptor
        )

    def describe_resolution(
        self, payload: WorkflowSubmitRequest
    ) -> dict[str, Any] | None:
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
        return _populate_weather_request(
            payload=payload, layer_id=layer_id, descriptor=descriptor
        )

    def describe_resolution(
        self, payload: WorkflowSubmitRequest
    ) -> dict[str, Any] | None:
        return None

    def describe_readiness(self, descriptor: Any) -> dict[str, Any] | None:
        return None


class _OverlayRegistryPopulator:
    """overlay_registry 引擎的就绪检查器。

    检查 overlay 图层的 PNG 预览文件、bounds JSON 文件和源数据文件是否实际存在。
    文件缺失时将图层标记为 "blocked"，避免用户添加图层后看到空白显示。
    """

    @property
    def engine_name(self) -> str:
        return "overlay_registry"

    def populate(
        self,
        *,
        payload: WorkflowSubmitRequest,
        layer_id: str,
        descriptor: Any,
    ) -> WorkflowSubmitRequest:
        # overlay_registry 图层不走工作流提交
        return payload

    def describe_resolution(
        self, payload: WorkflowSubmitRequest
    ) -> dict[str, Any] | None:
        return None

    def describe_readiness(self, descriptor: Any) -> dict[str, Any] | None:
        # 延迟导入避免模块加载顺序问题
        from app.services.overlay_registry import get_overlay_spec

        layer_id = getattr(descriptor, "layer_id", None)
        if not layer_id:
            return None

        spec = get_overlay_spec(layer_id)
        if spec is None:
            return {
                "unresolved_default_datasets": [
                    {
                        "dataset_name": "overlay 注册",
                        "candidate_sources": [
                            f"overlay_registry 中未找到 layer_id={layer_id}"
                        ],
                    }
                ]
            }

        unresolved: list[dict[str, Any]] = []

        # 检查 PNG 预览文件
        try:
            png_path = spec.resolve_png(None)
            if not png_path.exists():
                unresolved.append(
                    {
                        "dataset_name": "PNG 预览文件",
                        "candidate_sources": [str(png_path)],
                    }
                )
        except Exception:
            pass  # 配置错误由其他检查覆盖

        # 检查 bounds JSON 文件
        try:
            bounds_path = spec.resolve_bounds(None)
            if not bounds_path.exists():
                unresolved.append(
                    {
                        "dataset_name": "bounds 边界文件",
                        "candidate_sources": [str(bounds_path)],
                    }
                )
        except Exception:
            pass

        # 检查源数据文件（用于点查询；缺失不阻止显示但影响点选）
        try:
            source_path = spec.resolve_source_path(None)
            if source_path is None and spec.source_path is not None:
                unresolved.append(
                    {
                        "dataset_name": "源数据文件（点查询）",
                        "candidate_sources": [str(spec.source_path)],
                    }
                )
        except Exception:
            pass

        return {"unresolved_default_datasets": unresolved} if unresolved else None


# 模块加载时注册所有 populator
register_engine_populator(_PythonProviderPopulator())
register_engine_populator(_GeePopulator())
register_engine_populator(_WeatherPopulator())
register_engine_populator(_OverlayRegistryPopulator())
