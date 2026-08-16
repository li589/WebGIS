"""NDVI 在线种子端口契约：编译产物必须通过 provider 静态校验。

回归守卫：node_template_registry 的 ``module/ndvi_daily`` 输入端口曾漂移为
``input_dir/time_range/bbox``，而 provider 模块签名是
``datasource_selection/algorithm_params/output_spec_extra``。编译出的边
``to_port=input_dir`` 在 provider 校验被拒，导致 NDVI 在线链提交即失败。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.workflow_graph_compiler import (
    compile_litegraph_to_workflow_definition,
)
from workflow.serialization import coerce_workflow_definition
from workflow.validation import (
    WorkflowDefinitionValidationError,
    validate_workflow_definition,
)

_SEED = (
    Path(__file__).resolve().parents[2]
    / "Code"
    / "backend"
    / "workflow_seeds"
    / "system"
    / "ndvi_online_read.json"
)


def _compile_seed() -> dict:
    data = json.loads(_SEED.read_text(encoding="utf-8"))
    compiled = compile_litegraph_to_workflow_definition(
        workflow_id=data["workflow_id"],
        name=data.get("name"),
        description=data.get("description"),
        nodes=data.get("nodes"),
        links=data.get("links"),
    )
    # 与 resolver._compile_workflow_seed 一致：剔除 job_request 级端口的边
    compiled["edges"] = [
        e
        for e in (compiled.get("edges") or [])
        if e.get("to_port") not in {"time_range", "bbox", "region"}
    ]
    return compiled


def test_ndvi_online_seed_passes_provider_validation() -> None:
    definition = coerce_workflow_definition(_compile_seed())
    try:
        validate_workflow_definition(definition)
    except WorkflowDefinitionValidationError as exc:
        raise AssertionError(f"ndvi_online_read 端口漂移: {exc}") from exc


def test_ndvi_online_seed_keeps_extract_to_module_edge() -> None:
    """archive/extract → ndvi_hdf_preprocess 的数据流边不得被编译器丢弃。"""
    compiled = _compile_seed()
    pairs = {(e["from_node"], e["to_node"]) for e in compiled["edges"]}
    assert ("n3", "n6") in pairs, f"extract→preprocess 边被丢弃: {sorted(pairs)}"


def test_ndvi_online_seed_pipeline_topology() -> None:
    """CMG 产品 + HDF 预处理：VNP13C1 → 下载(带 url) → 透传 → HDF→9km TIF → ndvi_daily。"""
    compiled = _compile_seed()
    node_types = {n["node_id"]: n["params"].get("module_name") for n in compiled["nodes"]}
    assert node_types.get("n1") == "cmr_granule_search"
    assert node_types.get("n6") == "ndvi_hdf_preprocess", (
        f"缺少 HDF 预处理节点（裸 .h5 无法直入 ndvi_daily）: {node_types}"
    )
    assert node_types.get("n4") == "ndvi_daily"

    edges = {
        (e["from_node"], e["from_port"], e["to_node"], e["to_port"])
        for e in compiled["edges"]
    }
    assert ("n2", "url", "n3", "url") in edges, (
        f"缺 url 边（透传无法恢复原始文件名，YYYYDDD 解析失败）: {sorted(edges)}"
    )
    assert ("n3", "path", "n6", "input_dir") in edges
    assert ("n6", "output_dir", "n4", "data") in edges


def test_ndvi_online_seed_uses_cmg_product() -> None:
    """种子必须检索 VNP13C1（0.05° CMG）：预处理子数据集路径仅兼容 CMG 网格。"""
    data = json.loads(_SEED.read_text(encoding="utf-8"))
    cmr = next(n for n in data["nodes"] if n["type"] == "download/cmr_search")
    assert cmr["properties"]["short_name"] == "VNP13C1"
