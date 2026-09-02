"""materialize_map_layers 扫描 run-* 子目录 block dir 回归。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_materialize_map_layers_finds_mat_in_run_subdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import config as cfg_mod
    from app.services.python_provider_result_builder import PythonProviderResultBuilder
    from shared.contracts.api_contracts import WorkflowCommandType

    run_id = "run-materialize-subdir"
    block_root = (
        tmp_path
        / "_runtime"
        / "python_provider"
        / "products"
        / "omega_sf_fenkuai"
    )
    run_subdir = block_root / "run-other-legacy"
    run_subdir.mkdir(parents=True)
    (run_subdir / "20240101_20240108.mat").write_bytes(b"mat")

    patched = replace(
        cfg_mod.settings,
        data_root=str(tmp_path),
        python_provider_workspace="",
    )
    monkeypatch.setattr(cfg_mod, "settings", patched)

    upsert_calls: list[tuple[str, str]] = []

    def fake_upsert(block_dir: Path, *, variable_id: str, label: str, **kwargs):
        upsert_calls.append((str(block_dir), variable_id))
        return {
            "layer_id": f"ovl-{variable_id.lower()}",
            "title": label,
            "product_tag": label,
            "bounds": [100.0, 28.0, 101.0, 29.0],
            "source_crs": "EPSG:4326",
            "cog_preview_url": None,
            "time_list": ["20240101"],
            "default_time": "20240101",
            "native_step": "8d",
        }

    monkeypatch.setattr(
        "app.data_io.services.raster_timeseries.upsert_block_dir_timeseries",
        fake_upsert,
    )

    run_status = SimpleNamespace(
        status="succeeded",
        command_type=WorkflowCommandType.analysis,
        layer_id="omega_sf_fenkuai_smap_online",
        result_dto=None,
        result_refs=[],
        time_range=None,
    )

    out = PythonProviderResultBuilder().materialize_map_layers(run_id, run_status)

    assert out["count"] == 3
    tags = {layer["product_tag"] for layer in out["layers"]}
    assert tags == {"SM", "VOD", "OMEGA"}
    assert upsert_calls
    assert all(str(run_subdir) in path for path, _ in upsert_calls)
    assert {var for _, var in upsert_calls} == {"SM", "VOD", "OMEGA"}
