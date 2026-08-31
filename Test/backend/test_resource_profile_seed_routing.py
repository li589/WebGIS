"""resource_profile 按 workflow_name 种子图升级测试（X2 A5 修复）。

背景：layer_id-only 提交（ω 图层默认在线路径）在受理阶段由 resolver 物化
``algorithm_request.workflow_name``，但无 ``workflow_definition`` / ``module_name``
可查，导致 ``apply_resource_profile_to_payload`` 无法识别 heavy 模块，
run 停留 standard 队列。修复后按 workflow_name 回读种子图判定。

运行方式（仓库根执行）::

    Env/Python312/python.exe -m pytest Test/backend/test_resource_profile_seed_routing.py -q
"""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/15")

from shared.contracts.api_contracts import (  # noqa: E402
    AlgorithmWorkflowRequest,
    WorkflowResourceProfile,
    WorkflowSubmitRequest,
)
from app.services import resource_profile_resolver as rpr  # noqa: E402
from app.services import workflow_definition_service as wds  # noqa: E402

OMEGA_ONLINE_SEEDS = [
    "omega_sf_fenkuai_fy_online",
    "omega_sf_fenkuai_smap_online",
    "omega_avg_daily_fy_online",
    "omega_avg_daily_smap_online",
]
OMEGA_LOCAL_SEEDS = ["omega_sf_fenkuai_fy_single", "omega_sf_fenkuai_smap_single"]

OMEGA_GRAPH = {"nodes": [{"properties": {"module_name": "omega_sf_fenkuai"}}]}
LIGHT_GRAPH = {"nodes": [{"properties": {"module_name": "ndvi_climatology"}}]}


def _payload(algorithm_request: object) -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type="analysis",
        layer_id="method-fy-omega-doy-dynamic",
        resource_profile=WorkflowResourceProfile.standard,
        algorithm_request=algorithm_request,  # type: ignore[arg-type]
    )


def test_dict_workflow_name_with_heavy_seed_upgrades() -> None:
    """dict 形式 algorithm_request.workflow_name + heavy 种子图 → 升级 heavy。"""
    payload = _payload({"workflow_name": "omega_sf_fenkuai_fy_online"})
    with patch.object(rpr, "_workflow_seed_definition", return_value=OMEGA_GRAPH):
        rpr.apply_resource_profile_to_payload(payload)
    assert payload.resource_profile == WorkflowResourceProfile.heavy


def test_model_workflow_name_with_heavy_seed_upgrades() -> None:
    """模型形式 AlgorithmWorkflowRequest（无 definition/module_name）→ 升级 heavy。"""
    payload = _payload(
        AlgorithmWorkflowRequest(workflow_name="omega_sf_fenkuai_fy_online")
    )
    with patch.object(rpr, "_workflow_seed_definition", return_value=OMEGA_GRAPH):
        rpr.apply_resource_profile_to_payload(payload)
    assert payload.resource_profile == WorkflowResourceProfile.heavy


def test_seed_not_found_stays_standard() -> None:
    """种子不存在（fail-open）→ 维持 standard。"""
    payload = _payload({"workflow_name": "definitely-missing-seed"})
    with patch.object(rpr, "_workflow_seed_definition", return_value=None):
        rpr.apply_resource_profile_to_payload(payload)
    assert payload.resource_profile == WorkflowResourceProfile.standard


def test_light_seed_stays_standard() -> None:
    """种子图无 heavy 模块 → 维持 standard。"""
    payload = _payload({"workflow_name": "some_light_seed"})
    with patch.object(rpr, "_workflow_seed_definition", return_value=LIGHT_GRAPH):
        rpr.apply_resource_profile_to_payload(payload)
    assert payload.resource_profile == WorkflowResourceProfile.standard


def test_real_omega_seeds_upgrade_to_heavy() -> None:
    """真实种子图（同步后）：ω 在线/本地链均升级 heavy。"""
    wds._ensure_dirs()
    wds._sync_system_seeds()
    for seed in OMEGA_ONLINE_SEEDS + OMEGA_LOCAL_SEEDS:
        payload = _payload({"workflow_name": seed})
        rpr.apply_resource_profile_to_payload(payload)
        assert payload.resource_profile == WorkflowResourceProfile.heavy, seed


def test_explicit_heavy_not_downgraded() -> None:
    """显式 heavy 不被降级（infer 语义：非 standard 的显式选择优先）。"""
    payload = WorkflowSubmitRequest(
        command_type="analysis",
        resource_profile=WorkflowResourceProfile.heavy,
        algorithm_request={"workflow_name": "omega_sf_fenkuai_fy_online"},
    )
    with patch.object(rpr, "_workflow_seed_definition", return_value=LIGHT_GRAPH):
        rpr.apply_resource_profile_to_payload(payload)
    assert payload.resource_profile == WorkflowResourceProfile.heavy
