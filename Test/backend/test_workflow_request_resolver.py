from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from typing import Any
from unittest.mock import patch

from app.core import config as core_config
from app.services.workflow.submission_service import WorkflowSubmissionService
from app.services.workflow_request_resolver import (
    describe_layer_run_readiness,
    normalize_workflow_submit_request,
)
from shared.contracts.api_contracts import (
    RuntimeMapContext,
    WorkflowCommandType,
    WorkflowSubmitRequest,
)


def test_unresolved_default_datasets_remains_blocked() -> None:
    # catalog 演进：所有内置图层均已 available（无 placeholder 残留），
    # 改用「默认数据源无法解析 → blocked」路径验证 blocked 语义：
    # patch _resolve_data_access_source_uri 返回 None 使 ref-fy-tb-202512-mwri 默认数据集不可解析。
    with patch(
        "app.services.workflow_request_resolver._resolve_data_access_source_uri",
        return_value=None,
    ):
        readiness = describe_layer_run_readiness("ref-fy-tb-202512-mwri")

    assert readiness is not None, "readiness is not None"
    assert (
        readiness["run_readiness"] == "blocked"
    ), 'readiness["run_readiness"] == "blocked"'
    # 数据源未就绪时 describe_layer_run_readiness 追加 “缺少默认数据集” note
    notes_text = "\n".join(readiness["run_readiness_notes"])
    assert "缺少默认数据集" in notes_text, '"缺少默认数据集" in notes_text'


def test_normalize_fills_time_range_from_canvas_when_layer_missing() -> None:
    """编辑器提交常带 workflow_definition 但 linked_layer 可能不在 catalog。"""
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="run canvas",
        layer_id="method-smap-omega-doy-dynamic-MISSING",
        map_context=RuntimeMapContext(
            active_layer_id="method-smap-omega-doy-dynamic-MISSING"
        ),
        algorithm_request={
            "workflow_definition": {
                "nodes": [
                    {
                        "id": 1,
                        "type": "data/time_range",
                        "properties": {
                            "start_at": "2025-12-01T00:00:00",
                            "end_at": "2025-12-31T00:00:00",
                            "granularity": "day",
                        },
                    },
                    {
                        "id": 2,
                        "type": "module/omega_sf_fenkuai",
                        "properties": {
                            "module_name": "omega_sf_fenkuai",
                            "algorithm_params": {"tb_source": "SMAP"},
                        },
                    },
                ],
                "links": [],
            },
            "workflow_entry_name": "omega_sf_fenkuai_smap_single",
            "tags": {"workflow_id": "omega_sf_fenkuai_smap_single"},
        },
    )
    with patch(
        "app.services.workflow_request_resolver.get_layer_descriptor",
        return_value=None,
    ):
        normalized = normalize_workflow_submit_request(payload)

    assert normalized.time_range is not None, "normalized.time_range is not None"
    assert normalized.time_range is not None
    assert normalized.time_range.start_at == datetime(
        2025, 12, 1, 0, 0, 0
    ), "normalized.time_range.start_at == datetime(2025, 12, 1, 0, 0, 0)"
    assert normalized.time_range.end_at == datetime(
        2025, 12, 31, 0, 0, 0
    ), "normalized.time_range.end_at == datetime(2025, 12, 31, 0, 0, 0)"
    algo = normalized.algorithm_request or {}
    assert (
        algo.get("module_name") == "omega_sf_fenkuai"
    ), 'algo.get("module_name") == "omega_sf_fenkuai"'


def test_normalize_fills_time_range_from_seed_via_restored_layer() -> None:
    """关联图层重新入库后，仅 layer_id 提交也应从种子补齐 time_range。

    X2 变体路由后，无显式变体选择的 layer_id 提交翻译为默认在线变体
    （workflow_name），不再走 setdefault(module_name) 裸模块路径。
    """
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="run layer",
        layer_id="method-smap-omega-doy-dynamic",
        map_context=RuntimeMapContext(active_layer_id="method-smap-omega-doy-dynamic"),
    )
    normalized = normalize_workflow_submit_request(payload)
    assert normalized.time_range is not None, "normalized.time_range is not None"
    assert (
        normalized.time_range.start_at.year == 2025
    ), "normalized.time_range.start_at.year == 2025"
    assert (
        normalized.time_range.start_at.month == 12
    ), "normalized.time_range.start_at.month == 12"
    algo = normalized.algorithm_request or {}
    assert (
        algo.get("workflow_name") == "omega_sf_fenkuai_smap_online"
    ), 'algo.get("workflow_name") == "omega_sf_fenkuai_smap_online"'
    assert "module_name" not in algo, '"module_name" not in algo (variant seed path)'


def test_normalize_explicit_local_variant_routes_to_local_seed() -> None:
    """FE 分析框切换本地反演：workflow_entry_name（已声明变体）翻译为 workflow_name。"""
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="run FY SF local",
        layer_id="method-fy-omega-doy-dynamic",
        map_context=RuntimeMapContext(active_layer_id="method-fy-omega-doy-dynamic"),
        algorithm_request={"workflow_entry_name": "omega_sf_fenkuai_fy_single"},
    )
    normalized = normalize_workflow_submit_request(payload)
    algo = normalized.algorithm_request or {}
    assert (
        algo.get("workflow_name") == "omega_sf_fenkuai_fy_single"
    ), 'algo.get("workflow_name") == "omega_sf_fenkuai_fy_single"'
    assert (
        "module_name" not in algo
    ), '"module_name" not in algo（变体种子路径，不得 setdefault 回裸模块）'
    assert normalized.time_range is not None, "time_range 应从本地变体种子补齐"
    assert normalized.time_range.start_at.year == 2025
    assert normalized.time_range.start_at.month == 11


def test_normalize_undeclared_variant_entry_keeps_module_path() -> None:
    """workflow_entry_name 未匹配已声明变体（如 _dual 种子）→ 不路由，回落模块路径。"""
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="run FY SF dual",
        layer_id="method-fy-omega-doy-dynamic",
        map_context=RuntimeMapContext(active_layer_id="method-fy-omega-doy-dynamic"),
        algorithm_request={"workflow_entry_name": "omega_sf_fenkuai_fy_dual"},
    )
    normalized = normalize_workflow_submit_request(payload)
    algo = normalized.algorithm_request or {}
    assert (
        algo.get("module_name") == "omega_sf_fenkuai"
    ), "未声明变体应回落裸模块路径（descriptor.module_name 兜底）"
    assert "workflow_name" not in algo


def test_normalize_layer_without_variants_keeps_module_path() -> None:
    """无 workflow_variants 声明的 python_provider 图层维持既有模块路径（兼容）。"""
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="run ndvi",
        layer_id="ndvi",
        map_context=RuntimeMapContext(active_layer_id="ndvi"),
    )
    normalized = normalize_workflow_submit_request(payload)
    algo = normalized.algorithm_request or {}
    assert (
        algo.get("module_name") == "ndvi_daily"
    ), 'algo.get("module_name") == "ndvi_daily"（无变体图层不注入 workflow_name）'
    assert "workflow_name" not in algo


def test_normalize_multi_module_keeps_definition_without_module_name() -> None:
    """多模块 DAG 保留 workflow_definition，且不得同时带 module_name（bridge 互斥）。"""
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="run multi",
        algorithm_request={
            "workflow_definition": {
                "nodes": [
                    {
                        "id": 1,
                        "type": "stats/histogram",
                        "properties": {"bins": 10},
                    },
                    {
                        "id": 2,
                        "type": "viz/chart_generate",
                        "properties": {"chart_type": "bar"},
                    },
                ],
                "links": [[1, 1, 0, 2, 1]],
            }
        },
    )
    with patch(
        "app.services.workflow_request_resolver.get_layer_descriptor",
        return_value=None,
    ):
        # Synthetic descriptor path needs entry keys — workflow_definition present.
        normalized = normalize_workflow_submit_request(payload)
    algo = normalized.algorithm_request or {}
    assert isinstance(
        algo.get("workflow_definition"), dict
    ), 'isinstance(algo.get("workflow_definition"), dict)'
    assert "module_name" not in algo, '"module_name" not in algo'


def test_normalize_single_download_node_keeps_definition() -> None:
    """单 download/* 数据获取节点画布（如 ssh_sync→map_layer）不得展平。

    展平会丢弃拉取参数（server_type/remote_path/日期过滤），并把请求错配为
    层描述符默认 module（fy_tb_nas_read 直连输出场景即此形态）。
    """
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="run nas fetch",
        layer_id="ref-fy-tb-202512-mwri",
        map_context=RuntimeMapContext(active_layer_id="ref-fy-tb-202512-mwri"),
        algorithm_request={
            "workflow_definition": {
                "nodes": [
                    {
                        "id": 1,
                        "type": "download/ssh_sync",
                        "properties": {
                            "server_type": "nas_profile",
                            "remote_path": "/Chenhaojun/Data/fy3dhdf2425",
                            "start_date": "20240101",
                            "end_date": "20240101",
                            "file_filter": ".tif",
                        },
                    },
                    {
                        "id": 2,
                        "type": "output/map_layer",
                        "properties": {"layer_id": "ref-fy-tb-202512-mwri"},
                    },
                ],
                "links": [[1, 1, 0, 2, 0]],
            },
            "time_range": {
                "start": "2024-01-01T00:00:00",
                "end": "2024-01-01T23:59:59",
            },
        },
    )

    class _Descriptor:
        engine = "python_provider"
        layer_id = "ref-fy-tb-202512-mwri"
        module_name = "fy_daily"
        workflow_name = "fy_tb_local_read"
        default_task_type = "fy_daily"
        default_data_access_sources: dict[str, list[str]] = {}
        status = "available"

    with patch(
        "app.services.workflow_request_resolver.get_layer_descriptor",
        return_value=_Descriptor(),
    ):
        normalized = normalize_workflow_submit_request(payload)

    algo = normalized.algorithm_request or {}
    assert isinstance(
        algo.get("workflow_definition"), dict
    ), "single download node canvas must keep workflow_definition"
    assert (
        "module_name" not in algo
    ), "download pipeline must not be flattened into descriptor module_name"


def test_normalize_compiled_download_node_keeps_definition() -> None:
    """编译形态（node_type=module + params.module_name=node_class）的 download 节点不得展平。

    compile_litegraph_to_workflow_definition 会把 download/ssh_sync 编译为
    node_type="module" + params.module_name="ssh_sync"（node_class），原始
    "download/" 前缀丢失。检测若只认原始前缀，单 download 节点图会被错配为
    层描述符默认 module（fy_daily），拉取参数全部丢弃（run-b6906e8ed273）。
    """
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="run nas fetch compiled",
        layer_id="ref-fy-tb-202512-mwri",
        map_context=RuntimeMapContext(active_layer_id="ref-fy-tb-202512-mwri"),
        algorithm_request={
            "workflow_definition": {
                "workflow_id": "fy_tb_nas_read_live",
                "nodes": [
                    {
                        "node_id": "n1",
                        "node_type": "module",
                        "params": {
                            "server_type": "nas_profile",
                            "remote_path": "/Chenhaojun/Data/fy3dhdf2425",
                            "start_date": "20240101",
                            "end_date": "20240101",
                            "file_filter": ".tif",
                            "module_name": "ssh_sync",
                        },
                    },
                    {
                        "node_id": "n2",
                        "node_type": "module",
                        "params": {
                            "layer_id": "ref-fy-tb-202512-mwri",
                            "module_name": "output_map_layer",
                        },
                    },
                ],
                "edges": [
                    {
                        "from_node": "n1",
                        "from_port": "path",
                        "to_node": "n2",
                        "to_port": "data",
                    }
                ],
            },
            "time_range": {
                "start": "2024-01-01T00:00:00",
                "end": "2024-01-01T23:59:59",
            },
        },
    )

    class _Descriptor:
        engine = "python_provider"
        layer_id = "ref-fy-tb-202512-mwri"
        module_name = "fy_daily"
        workflow_name = "fy_tb_local_read"
        default_task_type = "fy_daily"
        default_data_access_sources: dict[str, list[str]] = {}
        status = "available"

    with patch(
        "app.services.workflow_request_resolver.get_layer_descriptor",
        return_value=_Descriptor(),
    ):
        normalized = normalize_workflow_submit_request(payload)

    algo = normalized.algorithm_request or {}
    assert isinstance(
        algo.get("workflow_definition"), dict
    ), "compiled single download node must keep workflow_definition"
    assert (
        "module_name" not in algo
    ), "compiled download pipeline must not be flattened into descriptor module_name"


def test_fy_single_descriptor_uses_accepted_fy_dataset_keys(tmp_path, request) -> None:
    """显式 module_name 提交（编辑器路径）不得注入模板不接受的 fy_folder。

    X2 变体路由后，显式 module_name 阻断变体翻译、维持裸模块路径及其
    accepted_data_access 映射尾部，此处继续守护 fy_folder 422 回归。

    数据依赖隔离：在 tmp 数据根中自建 descriptor.default_data_access_sources
    的全部候选目录，不依赖机器上的真实机构数据（BACKEND_DATA_ROOT 指向）。
    """
    from app.core.config import settings
    from app.services.workflow_request_resolver import invalidate_template_cache

    root = tmp_path / "Geograph_DataSet"
    for rel in (
        "Soil_Moisture/SMAP_Origin_Data",  # smap_folder（required）
        "Soil_Moisture/SMAP_Auxiliary_Data",  # anc_root（required）
        "Ecological_Vegetation/NDVI/climatology",  # ndvi_clim_folder
        "Soil_Moisture/FY3D",  # fy3d_folder
        "Soil_Moisture/FY3B",  # fy3b_folder
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
        (root / rel / "dummy.bin").write_bytes(b"x")

    old_root = getattr(settings, "data_root")
    object.__setattr__(settings, "data_root", str(root))
    request.addfinalizer(lambda: object.__setattr__(settings, "data_root", old_root))
    # _resolve_provider_dataset_path 为 lru_cache：先清掉其他测试遗留的解析结果，
    # 结束后再清一次，避免本测试的 tmp 路径泄漏进后续测试
    invalidate_template_cache()
    request.addfinalizer(invalidate_template_cache)

    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="run FY SF",
        layer_id="method-fy-omega-doy-dynamic",
        map_context=RuntimeMapContext(active_layer_id="method-fy-omega-doy-dynamic"),
        requested_outputs=["json", "map_layer"],
        algorithm_request={"module_name": "omega_sf_fenkuai"},
    )
    normalized = normalize_workflow_submit_request(payload)
    algo = normalized.algorithm_request or {}
    assert (
        algo.get("module_name") == "omega_sf_fenkuai"
    ), 'algo.get("module_name") == "omega_sf_fenkuai"'
    assert (
        "workflow_name" not in algo
    ), '"workflow_name" not in algo (explicit module path)'
    ds = algo.get("datasource_selection") or {}
    data_access = ds.get("_data_access_requests") or {}
    assert "fy_folder" not in data_access, '"fy_folder" not in data_access'
    assert "fy3d_folder" in data_access, '"fy3d_folder" in data_access'
    assert "fy3b_folder" in data_access, '"fy3b_folder" in data_access'
    # 提交期模板校验应通过（此前因 fy_folder 直接 422）
    WorkflowSubmissionService()._validate_request_params(normalized)


def _mk_descriptor(layer_id: str, **overrides: Any):
    from shared.contracts.api_contracts import BoundingBox, LayerDescriptor

    fields: dict[str, Any] = {
        "layer_id": layer_id,
        "dataset_key": f"dk-{layer_id}",
        "display_name": layer_id,
        "description": "test descriptor",
        "category": "research-group",
        "source_type": "algorithm_output",
        "render_type": "raster",
        "supported_map_modes": ["2d"],
        "extent": BoundingBox(west=-180.0, south=-85.0, east=180.0, north=85.0),
    }
    fields.update(overrides)
    return LayerDescriptor(**fields)


def test_merged_group_readiness_aggregates_ready_members() -> None:
    """合并组 readiness 由成员聚合：成员全 ready → 组 ready。"""
    group = _mk_descriptor(
        "grp-x",
        is_merged_group=True,
        members=["m-ready-a", "m-ready-b"],
        engine="overlay_registry",
    )
    members = {
        "grp-x": group,
        "m-ready-a": _mk_descriptor("m-ready-a"),
        "m-ready-b": _mk_descriptor("m-ready-b"),
    }
    with patch(
        "app.services.workflow_request_resolver.get_layer_descriptor",
        side_effect=lambda lid: members.get(lid),
    ):
        readiness = describe_layer_run_readiness("grp-x")

    assert readiness is not None
    assert readiness["run_readiness"] == "ready"
    assert "2/2" in (readiness["run_readiness_summary"] or "")


def test_merged_group_readiness_partial_members_still_ready() -> None:
    """任一成员 ready 即 ready，且 notes 记录未就绪成员。"""
    group = _mk_descriptor(
        "grp-y",
        is_merged_group=True,
        members=["m-ok", "m-placeholder"],
        engine="overlay_registry",
    )
    members = {
        "grp-y": group,
        "m-ok": _mk_descriptor("m-ok"),
        "m-placeholder": _mk_descriptor("m-placeholder", status="placeholder"),
    }
    with patch(
        "app.services.workflow_request_resolver.get_layer_descriptor",
        side_effect=lambda lid: members.get(lid),
    ):
        readiness = describe_layer_run_readiness("grp-y")

    assert readiness is not None
    assert readiness["run_readiness"] == "ready"
    assert "1/2" in (readiness["run_readiness_summary"] or "")
    assert any("m-placeholder" in note for note in readiness["run_readiness_notes"])


def test_merged_group_readiness_all_blocked_and_missing_member() -> None:
    """全部成员未就绪（含缺失成员）→ 组 blocked。"""
    group = _mk_descriptor(
        "grp-z",
        is_merged_group=True,
        members=["m-missing", "m-placeholder"],
        engine="overlay_registry",
    )
    members = {
        "grp-z": group,
        "m-placeholder": _mk_descriptor("m-placeholder", status="placeholder"),
    }
    with patch(
        "app.services.workflow_request_resolver.get_layer_descriptor",
        side_effect=lambda lid: members.get(lid),
    ):
        readiness = describe_layer_run_readiness("grp-z")

    assert readiness is not None
    assert readiness["run_readiness"] == "blocked"
    assert readiness["unresolved_default_datasets"] == []
    assert any("m-missing" in note for note in readiness["run_readiness_notes"])


def test_normalize_expands_data_root_placeholder_in_flattened_selection(
    tmp_path,
) -> None:
    """AD11 回归：compile 直传画布的字面 ``{DATA_ROOT}`` 须在提交边界展开。

    种子同步落盘时展开占位符，但 ``/workflow-definitions/compile`` 直传的
    画布定义保留字面 ``{DATA_ROOT}/...``；单模块展平路径的
    datasource_selection 若不展开，worker 侧算法将收到不可解析路径。
    """
    geoj = tmp_path / "smoke_vector.geojson"
    geoj.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="run canvas v2r",
        algorithm_request={
            "workflow_definition": {
                "nodes": [
                    {
                        "id": 1,
                        "type": "data/source",
                        "properties": {
                            "dataset_key": "input_path",
                            "path": "{DATA_ROOT}/smoke_vector.geojson",
                        },
                    },
                    {
                        "id": 2,
                        "type": "module/gis_vector_to_raster",
                        "properties": {
                            "module_name": "gis_vector_to_raster",
                            "algorithm_params": {"pixel_size": 0.01},
                        },
                    },
                ],
                "links": [[1, 1, 0, 2, 1]],
            },
            "workflow_entry_name": "gis_vector_to_raster",
        },
    )
    patched = dataclasses.replace(core_config.settings, data_root=str(tmp_path))
    with (
        patch(
            "app.services.workflow_request_resolver.get_layer_descriptor",
            return_value=None,
        ),
        patch(
            "app.services.workflow_request_resolver._resolve_data_access_source_uri",
            return_value=None,
        ),
        patch.object(core_config, "settings", patched),
    ):
        normalized = normalize_workflow_submit_request(payload)

    algo = normalized.algorithm_request or {}
    ds = algo.get("datasource_selection") or {}
    assert ds.get("input_path") == f"{tmp_path.as_posix()}/smoke_vector.geojson"
    assert "{DATA_ROOT" not in json.dumps(algo, default=str)


def test_normalize_expands_data_root_placeholder_in_kept_graph(tmp_path) -> None:
    """AD11 回归（保留图路径）：多模块 DAG 保留的 workflow_definition
    节点属性中的 ``{DATA_ROOT_WIN}`` 同样须展开为 data_root 绝对路径。"""
    tif = tmp_path / "smoke_input.tif"
    tif.write_bytes(b"")
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label="run canvas graph",
        algorithm_request={
            "workflow_definition": {
                "nodes": [
                    {
                        "id": 1,
                        "type": "data/source",
                        "properties": {
                            "dataset_key": "input_path",
                            "path": "{DATA_ROOT_WIN}\\smoke_input.tif",
                        },
                    },
                    {
                        "id": 2,
                        "type": "stats/histogram",
                        "properties": {"bins": 10},
                    },
                    {
                        "id": 3,
                        "type": "viz/chart_generate",
                        "properties": {"chart_type": "bar"},
                    },
                ],
                "links": [[1, 1, 0, 2, 1], [2, 2, 0, 3, 1]],
            }
        },
    )
    patched = dataclasses.replace(core_config.settings, data_root=str(tmp_path))
    with (
        patch(
            "app.services.workflow_request_resolver.get_layer_descriptor",
            return_value=None,
        ),
        patch(
            "app.services.workflow_request_resolver._resolve_data_access_source_uri",
            return_value=None,
        ),
        patch.object(core_config, "settings", patched),
    ):
        normalized = normalize_workflow_submit_request(payload)

    algo = normalized.algorithm_request or {}
    ds = algo.get("datasource_selection") or {}
    assert str(ds.get("input_path", "")).endswith("\\smoke_input.tif")
    wd = algo.get("workflow_definition")
    assert isinstance(wd, dict), "多模块 DAG 应保留 workflow_definition"
    assert "{DATA_ROOT" not in json.dumps(algo, default=str)
