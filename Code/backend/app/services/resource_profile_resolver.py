"""Infer WorkflowResourceProfile from seed meta and heavy module node classes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from shared.contracts.api_contracts import (
    WorkflowResourceProfile,
    WorkflowSubmitRequest,
)

# Modules that should bump the run to the heavy queue when present in the graph.
HEAVY_MODULE_NAMES: frozenset[str] = frozenset(
    {
        "preprocess_reproject",
        "preprocess_resample",
        "fusion_spatial_interpolate",
        "gis_watershed",
        "gis_contour",
        "gis_slope_aspect",
        "omega_sf_fenkuai",
        "omega_block",
        "omega_avg_daily",
        "omega_sf",
    }
)

# 本地读取源文件大小阈值（默认 1GB）：超过即自动升舱 heavy 队列。
# 2026-08-24 用户反馈#5：GEBCO_2024.nc（6.95GB）整文件读取工作流落在
# standard（仅 2 实例），长任务占满槽位 → 后续工作流排队阻塞 + 会话
# 超时登出。大文件读取属重资源任务，统一路由 heavy（独立 worker 池）。
HEAVY_SOURCE_BYTES: int = int(os.getenv("BACKEND_HEAVY_SOURCE_BYTES", str(1024**3)))


def _resolve_data_root() -> Path | None:
    """动态读 settings.data_root（frozen Settings 约定，勿模块级缓存）。"""
    from app.core.config import settings

    root = (getattr(settings, "data_root", None) or "").strip()
    return Path(root) if root else None


def local_source_max_bytes(definition: dict[str, Any] | None) -> int:
    """扫描定义中 data/source 节点的本地路径，返回最大源文件字节数。

    路径支持 ``{DATA_ROOT}`` 占位（static_local_read 种子约定）；stat 失败
    （不存在/权限）按 0 处理——嗅探是尽力而为，不阻塞提交。
    """
    if not isinstance(definition, dict):
        return 0
    root = _resolve_data_root()
    best = 0
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        props = (
            node.get("properties") if isinstance(node.get("properties"), dict) else {}
        )
        raw = props.get("path")
        if not isinstance(raw, str) or not raw.strip():
            continue
        path_text = raw.strip()
        if root is not None and "{DATA_ROOT}" in path_text:
            path_text = path_text.replace("{DATA_ROOT}", str(root))
        try:
            p = Path(path_text)
            if p.is_file():
                best = max(best, p.stat().st_size)
        except OSError:
            continue
    return best


def _parse_profile(raw: object | None) -> WorkflowResourceProfile | None:
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    try:
        return WorkflowResourceProfile(text)
    except ValueError:
        return None


def collect_module_names_from_definition(definition: dict[str, Any] | None) -> set[str]:
    """Collect node_class / module_name values from a LiteGraph or compiled graph."""
    names: set[str] = set()
    if not isinstance(definition, dict):
        return names
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        props = (
            node.get("properties") if isinstance(node.get("properties"), dict) else {}
        )
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        for candidate in (
            node.get("node_class"),
            props.get("module_name"),
            params.get("module_name"),
            node.get("node_type"),
        ):
            if candidate and str(candidate) not in {"module", "workflow"}:
                names.add(str(candidate).strip())
        # Template type → last path segment as soft hint (preprocess/reproject)
        ntype = str(node.get("type") or node.get("node_type") or "")
        if "/" in ntype:
            names.add(ntype.replace("/", "_"))
    return names


def definition_has_heavy_modules(definition: dict[str, Any] | None) -> bool:
    names = collect_module_names_from_definition(definition)
    if names & HEAVY_MODULE_NAMES:
        return True
    # Also match template-style names like preprocess_reproject from type
    return bool(names & HEAVY_MODULE_NAMES)


def infer_resource_profile(
    *,
    current: WorkflowResourceProfile | None = None,
    meta: dict[str, Any] | None = None,
    definition: dict[str, Any] | None = None,
) -> WorkflowResourceProfile:
    """Resolve effective resource profile.

    Precedence:
    1. Explicit non-default current (heavy/batch/light) wins as already chosen.
    2. Heavy module presence in the graph → heavy
       (beats seed ``_meta.resource_profile=standard``, which is a soft default).
    3. ``_meta.resource_profile`` from seed/definition.
    4. Else current or standard.
    """
    if current in (
        WorkflowResourceProfile.heavy,
        WorkflowResourceProfile.batch,
        WorkflowResourceProfile.light,
    ):
        # light/heavy/batch treated as intentional; only bump plain standard
        if current != WorkflowResourceProfile.standard:
            return current

    if definition_has_heavy_modules(definition):
        return WorkflowResourceProfile.heavy

    # 大文件本地读取自动升舱（BEFORE seed _meta：大源文件是客观资源事实，
    # 优先于种子的软默认 standard——见 HEAVY_SOURCE_BYTES 注释）
    if local_source_max_bytes(definition) > HEAVY_SOURCE_BYTES:
        return WorkflowResourceProfile.heavy

    meta_profile = _parse_profile((meta or {}).get("resource_profile"))
    if meta_profile is not None:
        return meta_profile

    return current or WorkflowResourceProfile.standard


def _workflow_seed_definition(workflow_name: str) -> dict[str, Any] | None:
    """按 workflow_name 读取种子定义（X2 变体路由场景）。

    layer_id-only 提交在受理阶段由 resolver 物化 ``algorithm_request.workflow_name``
    （无 workflow_definition / module_name 可查）；此时回读种子图判定 heavy 模块，
    保证 ω 在线/本地链路进入 heavy 队列。读取失败按无定义处理（fail-open）。
    """
    try:
        from app.services import workflow_definition_service  # 延迟导入避免环
    except Exception:  # pragma: no cover - 防御性
        return None
    try:
        return workflow_definition_service.get_definition(workflow_name)
    except Exception:
        return None


def apply_resource_profile_to_payload(
    payload: WorkflowSubmitRequest,
    *,
    meta: dict[str, Any] | None = None,
    definition: dict[str, Any] | None = None,
) -> WorkflowSubmitRequest:
    """Return payload with resource_profile possibly upgraded (mutates in place)."""
    # Prefer algorithm_request.workflow_definition when definition not passed
    graph = definition
    module_hint: str | None = None
    if graph is None and payload.algorithm_request is not None:
        algo = payload.algorithm_request
        if hasattr(algo, "workflow_definition"):
            graph = getattr(algo, "workflow_definition", None)
        elif isinstance(algo, dict):
            graph = algo.get("workflow_definition")
            module_hint = (
                str(algo.get("module_name")) if algo.get("module_name") else None
            )
        if isinstance(graph, dict) and "nodes" not in graph:
            # May be wrapped
            graph = graph if "nodes" in graph else definition

    # X2 变体路由：layer_id-only 提交在受理时物化 workflow_name（无 definition/
    # module_name 可查）；回读种子图判定 heavy，确保 ω 链路进 heavy 队列。
    if graph is None and module_hint is None and payload.algorithm_request is not None:
        algo = payload.algorithm_request
        if isinstance(algo, dict):
            wf_name = algo.get("workflow_name")
        else:
            wf_name = getattr(algo, "workflow_name", None)
        if wf_name:
            graph = _workflow_seed_definition(str(wf_name))

    if meta is None and isinstance(graph, dict):
        maybe_meta = graph.get("_meta")
        if isinstance(maybe_meta, dict):
            meta = maybe_meta

    # Flattened module-only requests drop workflow_definition; still bump heavy
    # when algorithm_request.module_name is a known heavy module.
    if (
        not definition_has_heavy_modules(graph if isinstance(graph, dict) else None)
        and module_hint
        and module_hint in HEAVY_MODULE_NAMES
        and (
            payload.resource_profile is None
            or payload.resource_profile == WorkflowResourceProfile.standard
        )
    ):
        payload.resource_profile = WorkflowResourceProfile.heavy
        return payload

    payload.resource_profile = infer_resource_profile(
        current=payload.resource_profile,
        meta=meta,
        definition=graph if isinstance(graph, dict) else definition,
    )
    return payload
