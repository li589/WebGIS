"""画布 scrape 的 datasource alias 须提升为 omega_avg / daily-bundle required 键。"""

from __future__ import annotations

from pathlib import Path

from modules.bundles import _resolve_bundle_datasource_selection
from modules.omega_avg_daily import _resolve_omega_avg_datasource_selection


def test_bundle_resolve_promotes_flat_aliases() -> None:
    resolved = _resolve_bundle_datasource_selection(
        {
            "smap_daily_mat": "I:/data/SMAP_Origin_Data",
            "ancillary_mat": "I:/data/SMAP_Auxiliary_Data",
            "ndvi_daily_mat": "I:/data/NDVIday",
        }
    )
    assert resolved["smap_folder"] == "I:/data/SMAP_Origin_Data"
    assert resolved["anc_root"] == "I:/data/SMAP_Auxiliary_Data"
    assert resolved["ndvi_folder"] == "I:/data/NDVIday"


def test_bundle_resolve_promotes_data_source_payload() -> None:
    resolved = _resolve_bundle_datasource_selection(
        {
            "smap_daily_mat": {
                "dataset_key": "smap_daily_mat",
                "path": "Soil_Moisture/SMAP_Origin_Data",
                "input_dir": "Soil_Moisture/SMAP_Origin_Data",
            }
        }
    )
    assert resolved["smap_folder"] == "Soil_Moisture/SMAP_Origin_Data"


def test_omega_avg_resolve_promotes_omega_block_output_alias() -> None:
    resolved = _resolve_omega_avg_datasource_selection(
        {
            "omega_block_output": "I:/data/Inversion_Results/omega_block",
            "smap_daily_mat": "I:/data/SMAP_Origin_Data",
            "ancillary_mat": "I:/data/SMAP_Auxiliary_Data",
            "ndvi_daily_mat": "I:/data/NDVIday",
        }
    )
    assert resolved["omega_block_dir"] == "I:/data/Inversion_Results/omega_block"
    assert resolved["smap_folder"] == "I:/data/SMAP_Origin_Data"
    assert resolved["anc_root"] == "I:/data/SMAP_Auxiliary_Data"
    assert resolved["ndvi_folder"] == "I:/data/NDVIday"
    missing = [
        key
        for key in ("omega_block_dir", "anc_root", "smap_folder", "ndvi_folder")
        if not resolved.get(key)
    ]
    assert missing == []


def test_keep_graph_flatten_promotes_aliases(tmp_path: Path, request) -> None:
    """流水线/画布多节点图：scrape alias 后须提升，避免运行期缺键。"""
    from app.core.config import settings
    from app.services.workflow_request_resolver import (
        _flatten_ui_workflow_definition,
        invalidate_template_cache,
    )
    from shared.contracts.api_contracts import BoundingBox, LayerDescriptor

    root = tmp_path / "Geograph_DataSet"
    for rel in (
        "Inversion_Results/omega_block",
        "Soil_Moisture/SMAP_Origin_Data",
        "Soil_Moisture/SMAP_Auxiliary_Data",
        "Ecological_Vegetation/NDVI/NDVIday",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
        (root / rel / "dummy.bin").write_bytes(b"x")

    old_root = getattr(settings, "data_root")
    object.__setattr__(settings, "data_root", str(root))
    request.addfinalizer(lambda: object.__setattr__(settings, "data_root", old_root))
    invalidate_template_cache()
    request.addfinalizer(invalidate_template_cache)

    descriptor = LayerDescriptor(
        layer_id="method-smap-omega-doy-avg",
        dataset_key="omega_avg_daily_smap",
        display_name="SMAP avg",
        description="test",
        category="research-group",
        source_type="algorithm_output",
        render_type="raster",
        supported_map_modes=["2d"],
        extent=BoundingBox(west=-180, south=-85, east=180, north=85),
        module_name="omega_avg_daily",
        engine="python_provider",
        default_data_access_sources={
            "omega_block_dir": ["Inversion_Results/omega_block"],
            "smap_folder": ["Soil_Moisture/SMAP_Origin_Data"],
            "anc_root": ["Soil_Moisture/SMAP_Auxiliary_Data"],
            "ndvi_folder": ["Ecological_Vegetation/NDVI/NDVIday"],
        },
    )
    algo = {
        "workflow_definition": {
            "nodes": [
                {
                    "id": 1,
                    "type": "download/nsidc_smap_download",
                    "properties": {"start_date": "20240101", "end_date": "20240102"},
                },
                {
                    "id": 2,
                    "type": "data/source",
                    "properties": {
                        "path": "Soil_Moisture/SMAP_Origin_Data",
                        "dataset_key": "smap_daily_mat",
                    },
                },
                {
                    "id": 3,
                    "type": "data/source",
                    "properties": {
                        "path": "Soil_Moisture/SMAP_Auxiliary_Data",
                        "dataset_key": "ancillary_mat",
                    },
                },
                {
                    "id": 4,
                    "type": "data/source",
                    "properties": {
                        "path": "Ecological_Vegetation/NDVI/NDVIday",
                        "dataset_key": "ndvi_daily_mat",
                    },
                },
                {
                    "id": 5,
                    "type": "data/source",
                    "properties": {
                        "path": "Inversion_Results/omega_block",
                        "dataset_key": "omega_block_output",
                    },
                },
                {
                    "id": 6,
                    "type": "module/omega_avg_daily",
                    "properties": {"module_name": "omega_avg_daily"},
                },
            ],
            "links": [],
        }
    }
    enriched, _, _ = _flatten_ui_workflow_definition(algo, descriptor=descriptor)
    assert "workflow_definition" in enriched
    ds = enriched.get("datasource_selection") or {}
    assert ds.get("smap_folder")
    assert ds.get("anc_root")
    assert ds.get("ndvi_folder")
    assert ds.get("omega_block_dir")
