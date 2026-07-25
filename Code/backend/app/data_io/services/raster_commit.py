"""科学栅格提交：按变量抽取 GeoTIFF、注册 overlay、可选自动确认 CRS。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.data_io.services import paths as import_paths
from app.data_io.services.raster_register import (
    confirm_imported_raster_crs,
    register_geotiff_as_imported,
)
from app.data_io.services.raster_science import extract_variable_to_geotiff
from app.data_io.services.upload import resolve_upload_path


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
    )
    base_name = source_name or path.name
    result = register_geotiff_as_imported(
        out_tif,
        source_filename=f"{Path(base_name).stem}_{safe_var}.tif",
        extra_meta={
            "science_source": path.name,
            "variable_id": variable_id,
            "time_index": time_index,
            "grid_preset": grid_preset,
            "source_crs_user": source_crs,
            "extract_bounds": extract_meta.get("bounds"),
        },
    )
    layer_dir = import_paths.IMPORTS_DIR / result["layer_id"]
    try:
        shutil.copy2(path, layer_dir / path.name)
    except OSError:
        pass
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
) -> dict[str, Any]:
    path = resolve_upload_path(upload_id)
    ext = path.suffix.lower()
    if ext in {".tif", ".tiff"}:
        return register_geotiff_as_imported(
            path, source_filename=source_name or path.name
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
    }
