"""门户 → 下载/处理工作流映射（2026-08-25 数据源管理改版 P2/Wave 2）。

「注册并添加到图层」能力的数据源真源：
- 前端 ``components/settings/data-source/portal-workflow-map.ts`` 与本文件
  **同源同步**（前端用于按钮可见性，后端用于编排提示/自动链）。
- Wave 2：提供 ``workflow_hint``（模块名/节点类型/建议参数）——前端展示
  引导用户到工作流编辑器；Wave 3 接全自动「下载→预处理→产物入图层库」链
  （需动态 layer 注册 + 产物 map_layer 物化，见 .workbuddy 记忆 2026-08-25）。

映射键 = portal_id（portal_catalog 门户标识）。
"""

from __future__ import annotations

from typing import Any


def _dates_last_days(days: int) -> dict[str, str]:
    """建议时间范围：最近 N 天（ISO 日期，供下载节点 start/end_date）。"""
    from datetime import UTC, datetime, timedelta

    today = datetime.now(UTC).date()
    return {
        "start_date": (today - timedelta(days=days)).isoformat(),
        "end_date": today.isoformat(),
    }


PORTAL_WORKFLOW_MAP: dict[str, dict[str, Any]] = {
    # NASA NSIDC — SMAP L3 土壤水分（SPL3SMP_E）
    # layer_id 复用现有种子层（engine=python_provider，render_strategy=
    # workflow_map_layer）——提交即触发「下载→预处理→烘焙→入图层库」全链。
    "nsidc_data": {
        "workflow": "nsidc_smap_download",
        "node_type": "download/nsidc_smap_download",
        "layer_id": "ref-smap-sm-202512-l3",
        "default_dataset_keys": ["SPL3SMP_E"],
        "default_params": {"short_name": "SPL3SMP_E", "version": "6"},
    },
    # NASA GES DISC — GLDAS Noah 陆面同化（暂无种子层——hint 引导手动编排）
    "nasa_gldas": {
        "workflow": "gldas_download",
        "node_type": "download/gldas_download",
        "default_dataset_keys": ["GLDAS_NOAH025_3H"],
        "default_params": {"short_name": "GLDAS_NOAH025_3H", "version": "2.1"},
    },
    "nasa_ges_disc": {
        "workflow": "gldas_download",
        "node_type": "download/gldas_download",
        "default_dataset_keys": ["GLDAS_NOAH025_3H"],
        "default_params": {"short_name": "GLDAS_NOAH025_3H", "version": "2.1"},
    },
    # CDS — ERA5 再分析（暂无种子层）
    "ecmwf_cds": {
        "workflow": "cds_download",
        "node_type": "download/cds_download",
        "default_dataset_keys": ["reanalysis-era5-land"],
        "default_params": {"dataset": "reanalysis-era5-land"},
    },
    # ESA Copernicus Data Space — S1/S2（暂无种子层）
    "esa_copernicus": {
        "workflow": "cdse_download",
        "node_type": "download/cdse_download",
        "default_dataset_keys": [],
        "default_params": {},
    },
    "esa_download": {
        "workflow": "cdse_download",
        "node_type": "download/cdse_download",
        "default_dataset_keys": [],
        "default_params": {},
    },
    # NOAA NOMADS — GFS/GEFS（暂无种子层）
    "noaa_nomads": {
        "workflow": "nomads_download",
        "node_type": "download/nomads_download",
        "default_dataset_keys": ["gfs"],
        "default_params": {"model": "gfs"},
    },
    # 国家卫星气象中心 NSMC — FY3 MWRI（有种子层 ref-fy-tb-202512-mwri）
    "cma_nsmc": {
        "workflow": "fy_preprocess",
        "node_type": "download/ssh_sync",
        "layer_id": "ref-fy-tb-202512-mwri",
        "default_dataset_keys": [],
        "default_params": {},
    },
    "cma_data": {
        "workflow": "fy_preprocess",
        "node_type": "download/ssh_sync",
        "layer_id": "ref-fy-tb-202512-mwri",
        "default_dataset_keys": [],
        "default_params": {},
    },
}


def get_portal_workflow_mapping(portal_id: str) -> dict[str, Any] | None:
    """返回门户的工作流映射；无映射返回 None。"""
    return PORTAL_WORKFLOW_MAP.get(portal_id)


def build_workflow_hint(
    portal_id: str, dataset_keys: list[str] | None = None
) -> dict[str, Any] | None:
    """构造「注册并添加到图层」的工作流编排提示。

    - dataset_keys 为空 → 用映射默认数据集；
    - 无映射门户 → None（前端不显示一键上图按钮）。
    - ``layer_id`` 存在 = 已有种子层（engine=python_provider）→
      ``auto_chain_ready=True``：register-and-add 端点将自动提交该层的
      工作流（「下载→预处理→烘焙→入图层库」全链由现有管线完成）；
      无 layer_id 的门户走 hint 引导手动编排（Wave 3+ 逐门户补种子层）。
    建议参数模板自动附最近 30 天时间范围（下载类节点的 start/end_date）。
    """
    mapping = get_portal_workflow_mapping(portal_id)
    if mapping is None:
        return None
    keys = [k for k in (dataset_keys or []) if k] or list(
        mapping["default_dataset_keys"]
    )
    params = {**mapping["default_params"]}
    if mapping["workflow"].endswith("_download"):
        params.update(_dates_last_days(30))
    return {
        "workflow": mapping["workflow"],
        "node_type": mapping["node_type"],
        "layer_id": mapping.get("layer_id") or None,
        "dataset_keys": keys,
        "params": params,
        "auto_chain_ready": bool(mapping.get("layer_id")),
    }
