"""科学栅格提交：按变量抽取 GeoTIFF、注册 overlay、可选自动确认 CRS。"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal

from app.data_io.services import paths as import_paths
from app.data_io.services.raster_register import (
    confirm_imported_raster_crs,
    register_geotiff_as_imported,
)
from app.data_io.services.raster_science import extract_variable_to_geotiff
from app.data_io.services.upload import resolve_upload_path
import contextlib

ConflictPolicy = Literal["overwrite", "rename", "error"]


def _read_layer_fingerprint(layer_dir: Path) -> dict[str, Any] | None:
    meta_path = layer_dir / "meta.json"
    if not meta_path.exists():
        bounds_path = layer_dir / "bounds.json"
        if bounds_path.exists():
            try:
                data = json.loads(bounds_path.read_text(encoding="utf-8"))
                meta = data.get("meta") if isinstance(data, dict) else None
                return meta if isinstance(meta, dict) else None
            except (OSError, json.JSONDecodeError):
                return None
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def find_existing_science_layer(
    *,
    source_name: str,
    variable_id: str,
    grid_preset: str | None,
    time_index: int,
) -> str | None:
    """按源文件名+变量+网格+时相查找已有 imported 图层（兼容旧随机 id）。"""
    import_paths.ensure_imports_root()
    want_src = Path(source_name).name
    want_stem = Path(source_name).stem
    want_var = str(variable_id)
    want_grid = str(grid_preset or "")
    want_time = int(time_index)

    stable = import_paths.stable_import_layer_id(
        want_src, want_var, want_grid, str(want_time)
    )
    if (import_paths.IMPORTS_DIR / stable).exists():
        return stable

    for child in import_paths.IMPORTS_DIR.iterdir():
        if not child.is_dir() or not child.name.startswith("imported"):
            continue
        if child.name.startswith("_"):
            continue
        meta = _read_layer_fingerprint(child)
        if not meta:
            continue
        science_source = str(meta.get("science_source") or "")
        source_filename = str(meta.get("source_filename") or "")
        src_ok = (
            Path(science_source).name == want_src
            or science_source == want_src
            or source_filename.startswith(f"{want_stem}_")
            or Path(source_filename).stem.startswith(f"{want_stem}_")
        )
        if not src_ok:
            continue
        meta_var = str(meta.get("variable_id") or "")
        if meta_var:
            if meta_var != want_var:
                continue
        elif want_var and want_var not in source_filename:
            continue
        meta_grid = str(meta.get("grid_preset") or "")
        if want_grid and meta_grid and meta_grid != want_grid:
            continue
        if int(meta.get("time_index") or 0) != want_time:
            continue
        return child.name
    return None


def _resolve_science_layer_id(
    *,
    source_name: str,
    variable_id: str,
    grid_preset: str | None,
    time_index: int,
    conflict_policy: ConflictPolicy,
) -> tuple[str, bool]:
    """返回 (layer_id, replace_existing)。"""
    base_id = import_paths.stable_import_layer_id(
        Path(source_name).name,
        variable_id,
        str(grid_preset or ""),
        str(int(time_index)),
    )
    existing = find_existing_science_layer(
        source_name=source_name,
        variable_id=variable_id,
        grid_preset=grid_preset,
        time_index=time_index,
    )
    # 覆盖时优先复用已有目录（含旧随机 id），避免配额净增
    target_id = existing or base_id
    exists = (import_paths.IMPORTS_DIR / target_id).exists()

    if conflict_policy == "overwrite":
        return target_id, exists
    if conflict_policy == "error":
        if exists:
            raise ValueError(
                f"同名导入已存在: {target_id}（源={Path(source_name).name}, "
                f"变量={variable_id}）。请选择覆盖或另存为新图层。"
            )
        return base_id, False
    # rename：已存在则新 uuid；不存在仍用稳定 id 便于下次覆盖
    if exists:
        return f"imported-{uuid.uuid4().hex[:12]}", False
    return base_id, False


def commit_science_raster_variable(
    path: Path,
    *,
    variable_id: str,
    time_index: int = 0,
    source_name: str | None = None,
    upload_id: str = "raster",
    source_crs: str | None = None,
    grid_preset: str | None = None,
    bounds: list[float] | None = None,
    invalid_values: list[float] | None = None,
    nodata: float | None = None,
    auto_confirm: bool = True,
    lng_offset: float = 0.0,
    lat_offset: float = 0.0,
    axis_order: str = "auto",
    conflict_policy: ConflictPolicy = "overwrite",
    temporal_meta: dict[str, Any] | None = None,
    palette: str | None = None,
    cell_registration: str | None = None,
) -> dict[str, Any]:
    tmp_dir = import_paths.IMPORTS_DIR / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    safe_var = "".join(c if c.isalnum() or c in "-_" else "_" for c in variable_id)[:48]
    out_tif = tmp_dir / f"{upload_id}_{safe_var}.tif"
    extract_meta = extract_variable_to_geotiff(
        path,
        variable_id=variable_id,
        output_tif=out_tif,
        time_index=time_index,
        source_crs=source_crs,
        grid_preset=grid_preset,
        bounds=bounds,
        invalid_values=invalid_values or None,
        nodata=nodata,
        axis_order=axis_order,
    )
    base_name = source_name or path.name
    layer_id, replace_existing = _resolve_science_layer_id(
        source_name=base_name,
        variable_id=variable_id,
        grid_preset=grid_preset or extract_meta.get("grid_preset"),
        time_index=time_index,
        conflict_policy=conflict_policy,
    )
    extra_meta = {
        "science_source": path.name,
        "variable_id": variable_id,
        "time_index": time_index,
        "grid_preset": extract_meta.get("grid_preset") or grid_preset,
        "source_crs_user": source_crs,
        "extract_bounds": extract_meta.get("bounds"),
        "axis_transposed": extract_meta.get("axis_transposed"),
        "invalid_values_applied": extract_meta.get("invalid_values_applied"),
        "conflict_policy": conflict_policy,
        **(temporal_meta or {}),
    }
    if cell_registration:
        # 像元配准（P1.5）：bounds 的 Area/Point 语义，供下游导出/校正参考
        extra_meta["cell_registration"] = cell_registration
    result = register_geotiff_as_imported(
        out_tif,
        source_filename=f"{Path(base_name).stem}_{safe_var}.tif",
        layer_id=layer_id,
        replace_existing=replace_existing,
        extra_meta=extra_meta,
        palette=palette or "wind-blue",
    )
    layer_dir = import_paths.IMPORTS_DIR / result["layer_id"]
    with contextlib.suppress(OSError):
        shutil.copy2(path, layer_dir / path.name)
    out_tif.unlink(missing_ok=True)

    crs_for_confirm = source_crs or extract_meta.get("crs") or result.get("source_crs")
    if (
        auto_confirm
        and crs_for_confirm
        and crs_for_confirm not in ("EPSG:4326", "EPSG:4490")
    ):
        try:
            confirmed = confirm_imported_raster_crs(
                result["layer_id"],
                source_crs=str(crs_for_confirm),
                lng_offset=lng_offset,
                lat_offset=lat_offset,
            )
            result = {**result, **confirmed, "needs_confirm": False}
        except Exception as exc:
            result["auto_confirm_error"] = str(exc)
            result["needs_confirm"] = True
    elif (
        auto_confirm
        and crs_for_confirm in ("EPSG:4326", "EPSG:4490")
        and result.get("needs_confirm")
    ):
        try:
            confirmed = confirm_imported_raster_crs(
                result["layer_id"],
                source_crs=str(crs_for_confirm),
                lng_offset=lng_offset,
                lat_offset=lat_offset,
            )
            result = {**result, **confirmed, "needs_confirm": False}
        except Exception as exc:
            result["auto_confirm_error"] = str(exc)

    result["variable_id"] = variable_id
    result["axis_transposed"] = extract_meta.get("axis_transposed")
    result["grid_preset"] = extract_meta.get("grid_preset") or grid_preset
    result["conflict_policy"] = conflict_policy
    return result


def commit_algorithm_geotiff(
    path: Path,
    *,
    layer_id: str,
    source_name: str | None = None,
    conflict_policy: ConflictPolicy = "overwrite",
    time_start: str | None = None,
    time_end: str | None = None,
    extra_meta: dict[str, Any] | None = None,
    auto_confirm: bool = True,
    palette: str | None = None,
) -> dict[str, Any]:
    """算法产物 GeoTIFF 注册：与导入 commit 共用配额/冲突/时间标签语义。

    与 ``commit_raster_upload`` 的 .tif 分支一致，但不经过 upload 目录，
    供工作流产物物化（generic raster map_layer）复用。时间标签优先取
    run 的 time_range（起止俱备→range，仅起点→point），否则按文件名猜。
    """
    from app.data_io.services.time_label import build_temporal_meta

    start = (time_start or "").strip()
    end = (time_end or "").strip()
    if start and end:
        temporal_mode = "range"
    elif start or end:
        temporal_mode = "point"
        start = start or end
    else:
        temporal_mode = "auto"

    temporal_meta = build_temporal_meta(
        temporal_mode=temporal_mode,
        time_start=start or None,
        time_end=end or None,
        source_name=source_name or path.name,
    )

    resolved_id = layer_id
    dest = import_paths.IMPORTS_DIR / resolved_id
    exists = dest.exists()
    if conflict_policy == "error" and exists:
        raise ValueError(f"同名导入已存在: {resolved_id}")
    if conflict_policy == "rename" and exists:
        resolved_id = f"imported-{uuid.uuid4().hex[:12]}"
    replace = conflict_policy == "overwrite" and exists

    result = register_geotiff_as_imported(
        path,
        source_filename=source_name or path.name,
        layer_id=resolved_id,
        replace_existing=replace,
        extra_meta={**(extra_meta or {}), **temporal_meta},
        palette=palette or "wind-blue",
    )
    result["conflict_policy"] = conflict_policy

    crs_for_confirm = str(result.get("source_crs") or "").strip()
    if (
        auto_confirm
        and crs_for_confirm
        and (
            result.get("needs_confirm")
            or crs_for_confirm not in ("EPSG:4326", "EPSG:4490")
        )
    ):
        try:
            confirmed = confirm_imported_raster_crs(
                result["layer_id"], source_crs=crs_for_confirm
            )
            result = {**result, **confirmed, "needs_confirm": False}
        except Exception as exc:
            result["auto_confirm_error"] = str(exc)
    return result


def commit_raster_upload(
    *,
    upload_id: str,
    variable_id: str | None = None,
    variable_ids: list[str] | None = None,
    time_index: int = 0,
    source_name: str | None = None,
    source_crs: str | None = None,
    grid_preset: str | None = None,
    bounds: list[float] | None = None,
    invalid_values: list[float] | None = None,
    nodata: float | None = None,
    auto_confirm: bool = True,
    lng_offset: float = 0.0,
    lat_offset: float = 0.0,
    axis_order: str = "auto",
    conflict_policy: ConflictPolicy = "overwrite",
    temporal_mode: str = "auto",
    time_label: str | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
    native_step: str | None = None,
) -> dict[str, Any]:
    from app.data_io.services.time_label import build_temporal_meta

    path = resolve_upload_path(upload_id)
    name = source_name or path.name
    temporal_meta = build_temporal_meta(
        temporal_mode=temporal_mode,
        time_label=time_label,
        time_start=time_start,
        time_end=time_end,
        native_step=native_step,
        source_name=name,
    )
    ext = path.suffix.lower()
    if ext in {".tif", ".tiff"}:
        layer_id = import_paths.stable_import_layer_id(Path(name).name, "geotiff")
        dest = import_paths.IMPORTS_DIR / layer_id
        replace = conflict_policy == "overwrite" and dest.exists()
        if conflict_policy == "error" and dest.exists():
            raise ValueError(f"同名导入已存在: {layer_id}。请选择覆盖或另存为新图层。")
        if conflict_policy == "rename" and dest.exists():
            layer_id = f"imported-{uuid.uuid4().hex[:12]}"
            replace = False
        return register_geotiff_as_imported(
            path,
            source_filename=name,
            layer_id=layer_id,
            replace_existing=replace,
            extra_meta=temporal_meta,
        )

    var_ids = [v for v in (variable_ids or []) if v]
    if not var_ids and variable_id:
        var_ids = [variable_id]
    if not var_ids:
        raise ValueError("请选择至少一个变量/数据集")

    layers: list[dict[str, Any]] = []
    for vid in var_ids:
        layers.append(
            commit_science_raster_variable(
                path,
                variable_id=vid,
                time_index=time_index,
                source_name=source_name,
                upload_id=upload_id,
                source_crs=source_crs,
                grid_preset=grid_preset,
                bounds=bounds,
                invalid_values=list(invalid_values or []),
                nodata=nodata,
                auto_confirm=auto_confirm,
                lng_offset=lng_offset,
                lat_offset=lat_offset,
                axis_order=axis_order,
                conflict_policy=conflict_policy,
                temporal_meta=temporal_meta,
            )
        )

    if len(layers) == 1:
        return layers[0]
    return {
        "layers": layers,
        "layer_id": layers[0]["layer_id"],
        "bounds": layers[0].get("bounds"),
        "source_crs": layers[0].get("source_crs"),
        "needs_confirm": any(layer.get("needs_confirm") for layer in layers),
        "count": len(layers),
        "replaced": any(layer.get("replaced") for layer in layers),
        "time_list": layers[0].get("time_list") or temporal_meta.get("time_list") or [],
        "default_time": layers[0].get("default_time")
        or temporal_meta.get("default_time"),
        "native_step": layers[0].get("native_step") or temporal_meta.get("native_step"),
        "follow_policy": layers[0].get("follow_policy")
        or temporal_meta.get("follow_policy"),
        "temporal_kind": temporal_meta.get("temporal_kind"),
        "temporal_source": temporal_meta.get("temporal_source"),
    }
