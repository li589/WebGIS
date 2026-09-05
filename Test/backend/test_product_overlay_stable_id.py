"""产物 overlay id 稳定化 + 归一化基准统一回归（2026-08-24 三联报障 A/2a）。

A：generic raster 产物 overlay id 此前恒为 imported-gis-{run_id[-8:]}-{index}
（每次运行新生成）→ 前端 syncOverlays 视为"移除旧层+添加新层"，两次网络
往返之间存在空窗（静态图层"一闪而过"根因）。修复：带 layer_id 的 run 改用
稳定 id imported-{layer_id}-{index}，overwrite 下同层重跑覆盖同一 overlay。

2a：_colorize_masked_band 的 None 兜底此前用全量 min/max，与瓦片路径
（overlay_tile_service._source_value_range 的 p2/p98）两套基准——image↔瓦片
模式切换时同数据色阶突变。修复：None 兜底统一 p2/p98（样本≥100 时）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest


def _payload(layer_id: str | None):
    from shared.contracts.api_contracts import (
        WorkflowCommandType,
        WorkflowSubmitRequest,
    )

    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        layer_id=layer_id or None,
    )


@pytest.fixture()
def raster_product(tmp_path: Path) -> dict:
    """单波段小 GeoTIFF 产物（走 generic raster map_layer 分支）。"""
    import rasterio
    from rasterio.transform import from_bounds

    tif = tmp_path / "out.tif"
    transform = from_bounds(100.0, 20.0, 110.0, 30.0, 8, 8)
    data = np.linspace(0, 1, 64, dtype="float32").reshape(8, 8)
    with rasterio.open(
        tif,
        "w",
        driver="GTiff",
        width=8,
        height=8,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    return {"type": "raster", "uri": str(tif), "name": "demo", "variable": "v"}


def test_stable_overlay_id_with_layer_id(raster_product, tmp_path, monkeypatch):
    """带 layer_id 的 run：产物 overlay id = imported-{layer_id}-{index}（稳定）。"""
    imports_root = tmp_path / "imports"
    from app.data_io.services import paths as import_paths
    from app.data_io.services import raster_commit as commit_mod
    from app.data_io.services import raster_register as register_mod

    for mod in (import_paths, register_mod, commit_mod):
        if hasattr(mod, "IMPORTS_DIR"):
            monkeypatch.setattr(mod, "IMPORTS_DIR", imports_root)
    monkeypatch.setattr(import_paths, "IMPORTS_DIR", imports_root)
    import_paths.ensure_imports_root()

    from app.services.python_provider_result_builder import PythonProviderResultBuilder

    builder = PythonProviderResultBuilder()
    now = datetime.now(timezone.utc)
    refs = builder.build_product_map_layer_refs(
        run_id="run-stable-aaa11101",
        requested_at=now,
        payload=_payload("aridity-cn"),
        result_dto={"products": [raster_product]},
    )
    assert refs, "generic raster 产物应产出 map_layer ref"
    assets = refs[0].inline_data["layer_assets"]
    assert assets["overlay_layer_id"] == "imported-aridity-cn-00"


def test_stable_id_sanitizes_illegal_chars(raster_product, tmp_path, monkeypatch):
    r"""layer_id 含 :/\ 等非法字符时 sanitize 为 _（safe_import_child 防护）。

    回归锚点：analysis:test 若不 sanitize，Windows 上 mkdir
    imports/imported-analysis:test-00 报"目录名称无效"（2026-08-24 实测）。
    """
    imports_root = tmp_path / "imports"
    from app.data_io.services import paths as import_paths
    from app.data_io.services import raster_commit as commit_mod
    from app.data_io.services import raster_register as register_mod

    for mod in (import_paths, register_mod, commit_mod):
        if hasattr(mod, "IMPORTS_DIR"):
            monkeypatch.setattr(mod, "IMPORTS_DIR", imports_root)
    monkeypatch.setattr(import_paths, "IMPORTS_DIR", imports_root)
    import_paths.ensure_imports_root()

    from app.services.python_provider_result_builder import PythonProviderResultBuilder

    builder = PythonProviderResultBuilder()
    now = datetime.now(timezone.utc)
    refs = builder.build_product_map_layer_refs(
        run_id="run-sanitize-ccc33303",
        requested_at=now,
        payload=_payload("analysis:test"),
        result_dto={"products": [raster_product]},
    )
    assert refs, "含非法字符的 layer_id 也应成功注册（sanitize 后）"
    assets = refs[0].inline_data["layer_assets"]
    assert assets["overlay_layer_id"] == "imported-analysis_test-00"


def test_product_palette_aligns_with_descriptor(raster_product, tmp_path, monkeypatch):
    """产物 palette 对齐静态层 descriptor.style.palette（用户需求 2026-08-24）。

    aridity-cn 在 layer_descriptors.json 配了 style.palette='brg'——产物注册
    的 overlay palette 与 render_hint.palette 都应取 'brg'（而非写死 viridis）。
    """
    imports_root = tmp_path / "imports"
    from app.data_io.services import paths as import_paths
    from app.data_io.services import raster_commit as commit_mod
    from app.data_io.services import raster_register as register_mod

    for mod in (import_paths, register_mod, commit_mod):
        if hasattr(mod, "IMPORTS_DIR"):
            monkeypatch.setattr(mod, "IMPORTS_DIR", imports_root)
    monkeypatch.setattr(import_paths, "IMPORTS_DIR", imports_root)
    import_paths.ensure_imports_root()

    from app.services.python_provider_result_builder import PythonProviderResultBuilder

    builder = PythonProviderResultBuilder()
    now = datetime.now(timezone.utc)
    refs = builder.build_product_map_layer_refs(
        run_id="run-palette-ddd44404",
        requested_at=now,
        payload=_payload("aridity-cn"),
        result_dto={"products": [raster_product]},
    )
    assert refs, "aridity-cn 产物应成功注册"
    hint = refs[0].inline_data["render_hint"]
    assert hint["palette"] == "brg", f"render_hint.palette 应对齐 descriptor brg，实际 {hint['palette']}"
    # 注册侧 overlay palette 也应同步（读缓存 spec）
    import json
    bounds_file = import_paths.IMPORTS_DIR / "imported-aridity-cn-00" / "bounds.json"
    assert bounds_file.exists(), "产物 overlay bounds.json 应存在"
    meta = json.loads(bounds_file.read_text(encoding="utf-8"))["meta"]
    assert meta.get("palette") == "brg", f"注册 meta.palette 应对齐 brg，实际 {meta.get('palette')}"


def test_run_derived_id_without_layer_id(raster_product, tmp_path, monkeypatch):
    """无 layer_id（画布/临时运行）：保留原 run 派生 id（不回归旧行为面）。"""
    imports_root = tmp_path / "imports"
    from app.data_io.services import paths as import_paths
    from app.data_io.services import raster_commit as commit_mod
    from app.data_io.services import raster_register as register_mod

    for mod in (import_paths, register_mod, commit_mod):
        if hasattr(mod, "IMPORTS_DIR"):
            monkeypatch.setattr(mod, "IMPORTS_DIR", imports_root)
    monkeypatch.setattr(import_paths, "IMPORTS_DIR", imports_root)
    import_paths.ensure_imports_root()

    from app.services.python_provider_result_builder import PythonProviderResultBuilder

    builder = PythonProviderResultBuilder()
    now = datetime.now(timezone.utc)
    refs = builder.build_product_map_layer_refs(
        run_id="run-freeform-bbb22202",
        requested_at=now,
        payload=_payload(None),
        result_dto={"products": [raster_product]},
    )
    assert refs
    assets = refs[0].inline_data["layer_assets"]
    assert assets["overlay_layer_id"] == "imported-gis-bbb22202-00"


def test_colorize_none_range_uses_percentile():
    """_colorize_masked_band None 兜底改 p2/p98（≥100 样本）——与瓦片基准一致。

    构造 0..99 均匀数据 + 一个 1000 的极值：全量 max 会把色阶压扁（99→近 0 色），
    p2/p98 下 99 应获得高色阶（接近 palette 末端）。
    """
    from app.services.raster_preview_service import colorize_array_to_rgba

    data = np.linspace(0, 99, 200, dtype="float32").reshape(10, 20)
    data[0, 0] = 1000.0  # 极值
    rgba = np.asarray(colorize_array_to_rgba(data, palette="viridis"))
    # 行首≈0.5（暗）vs 末行末列≈98.5（亮）
    v_lo = rgba[1, 0, :3].astype(int)
    v_hi = rgba[9, 19, :3].astype(int)
    brightness_lo = int(v_lo.sum())
    brightness_hi = int(v_hi.sum())
    assert brightness_hi > brightness_lo + 150, (
        f"p2/p98 归一化下高值应显著亮于低值：{brightness_lo} vs {brightness_hi}"
    )


def test_colorize_small_sample_keeps_minmax():
    """小样本（<100）保持全量 min/max——百分位在极小样本上退化。"""
    from app.services.raster_preview_service import _colorize_masked_band

    np_mod = np
    arr = np_mod.array([[0.0, 1.0], [2.0, 3.0]], dtype="float32")
    masked = np_mod.ma.array(arr)
    stops = np_mod.array([[0, 0, 0], [255, 255, 255]], dtype="float32")
    red, green, blue, alpha = _colorize_masked_band(
        np_mod, masked, stops, min_value=None, max_value=None
    )
    # 4 样本 < 100 → min/max 路径：min=0 → 黑，max=3 → 白
    assert red[0, 0] == 0
    assert red[1, 1] == 255


def test_mat_map_layer_product_registers_overlay(tmp_path, monkeypatch):
    """.mat map_layer 产物（static_local_read/aridity-cn 形态）注册 overlay。

    2026-08-24："工作流已完成但图层不显示"根因——generic 分支只收 GeoTIFF
    后缀，.mat 产物静默丢弃。现 .mat 走 commit_science_raster_variable 管线，
    自动推断唯一 2D 数据变量（排除 lat/lon），palette 对齐 descriptor。
    """
    imports_root = tmp_path / "imports"
    from app.data_io.services import paths as import_paths
    from app.data_io.services import raster_commit as commit_mod
    from app.data_io.services import raster_register as register_mod

    for mod in (import_paths, register_mod, commit_mod):
        if hasattr(mod, "IMPORTS_DIR"):
            monkeypatch.setattr(mod, "IMPORTS_DIR", imports_root)
    monkeypatch.setattr(import_paths, "IMPORTS_DIR", imports_root)
    import_paths.ensure_imports_root()

    import scipy.io as sio

    mat = tmp_path / "aridity_025.mat"
    sio.savemat(
        str(mat),
        {
            "aridity": np.linspace(0, 1, 176 * 256).reshape(176, 256),
            "lat": np.linspace(15, 55, 176),
            "lon": np.linspace(70, 140, 256),
        },
    )

    from app.services.python_provider_result_builder import PythonProviderResultBuilder

    builder = PythonProviderResultBuilder()
    now = datetime.now(timezone.utc)
    refs = builder.build_product_map_layer_refs(
        run_id="run-matmap-eee55505",
        requested_at=now,
        payload=_payload("aridity-cn"),
        result_dto={
            "products": [
                {
                    "name": "aridity_025.mat",
                    "type": "map_layer",
                    "uri": str(mat),
                    "tags": {"module": "output_map_layer"},
                }
            ]
        },
    )
    assert refs, ".mat map_layer 产物应注册出 map_layer ref（不再静默丢弃）"
    assets = refs[0].inline_data["layer_assets"]
    hint = refs[0].inline_data["render_hint"]
    assert assets["overlay_layer_id"], "overlay id 应非空"
    assert hint["palette"] == "brg", (
        f"palette 应对齐 aridity descriptor brg，实际 {hint['palette']}"
    )
    # overlay 目录应真实存在（注册成功）
    overlay_dir = imports_root / assets["overlay_layer_id"]
    assert overlay_dir.is_dir()
    # bounds 应精确反映 .mat 内嵌 lat/lon（15~55N / 70~140E），非默认全球网格
    import json

    bounds_meta = json.loads((overlay_dir / "bounds.json").read_text(encoding="utf-8"))
    b = bounds_meta["bounds"]
    assert abs(b[0] - 70) < 0.2, f"west 应对齐 lon.min 70，实际 {b[0]}"
    assert abs(b[2] - 140) < 0.2, f"east 应对齐 lon.max 140，实际 {b[2]}"
    assert abs(b[1] - 15) < 0.2, f"south 应对齐 lat.min 15，实际 {b[1]}"
    assert abs(b[3] - 55) < 0.2, f"north 应对齐 lat.max 55，实际 {b[3]}"
