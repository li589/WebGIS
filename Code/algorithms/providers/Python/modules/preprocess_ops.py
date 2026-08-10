"""Preprocess modules: reproject / resample / clip / mask."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from modules.base import BaseModule
from modules.registry import register_module_decorator
from modules._raster_ops import (
    RasterOpsValidationError,
    align_rasters,
    emit_progress,
    open_raster,
    parse_bbox,
    resampling_enum,
    resolve_raster_path,
    store_raster_manifest,
    write_cog,
)
from workflow.schemas import NodeExecutionContext, PortSpec


def _out_dir(ctx: NodeExecutionContext, name: str) -> Path:
    d = Path(ctx.workspace) / "products" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _merged_params(
    inputs: dict[str, object], params: dict[str, object]
) -> dict[str, object]:
    algorithm_params = dict(inputs.get("algorithm_params", {}) or {})
    return {**algorithm_params, **dict(params or {})}


@register_module_decorator(name="preprocess_reproject", aliases=["reproject"])
class PreprocessReprojectModule(BaseModule):
    name = "preprocess_reproject"
    description = "Reproject a raster to a target CRS (float64 compute, float32 COG)."
    input_ports = [
        PortSpec(name="raster", kind="data", data_class="raster", required=False),
        PortSpec(name="bbox", kind="geometry", data_class="bbox", required=False),
        PortSpec(
            name="manifest",
            kind="artifact",
            data_class="product_manifest",
            required=False,
        ),
    ]
    output_ports = [
        PortSpec(name="raster", kind="data", data_class="raster"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"target_crs": "EPSG:4326", "resampling": "nearest"}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        import rasterio
        from rasterio.warp import calculate_default_transform, reproject

        merged = _merged_params(inputs, params)
        target_crs = str(merged.get("target_crs") or "EPSG:4326")
        resampling = str(merged.get("resampling") or "nearest")
        src_path = resolve_raster_path(inputs, ctx, params=merged)
        emit_progress(ctx, self.name, f"reproject {src_path.name} -> {target_crs}", 5)

        with rasterio.open(src_path) as src:
            if src.crs is None:
                raise RasterOpsValidationError("Source raster has no CRS")
            transform, width, height = calculate_default_transform(
                src.crs, target_crs, src.width, src.height, *src.bounds
            )
            bbox = parse_bbox(inputs.get("bbox") or merged.get("bbox"))
            if bbox is not None:
                # Optional spatial window after warp via destination window clip
                pass
            count = src.count
            dst = np.full((count, height, width), np.nan, dtype=np.float64)
            for i in range(1, count + 1):
                band = src.read(i).astype(np.float64)
                if src.nodata is not None:
                    band = np.where(band == src.nodata, np.nan, band)
                reproject(
                    source=band,
                    destination=dst[i - 1],
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    resampling=resampling_enum(resampling),
                    src_nodata=np.nan,
                    dst_nodata=np.nan,
                )
            out_data = dst[0] if count == 1 else dst

        out_dir = _out_dir(ctx, "reproject")
        meta = write_cog(
            out_data,
            out_dir,
            f"{src_path.stem}_reproj",
            transform=transform,
            crs=target_crs,
            dtype="float32",
        )
        uri = str(out_dir / f"{src_path.stem}_reproj.tif")
        emit_progress(ctx, self.name, "done", 100)
        return store_raster_manifest(
            ctx,
            module_name=self.name,
            uri=uri,
            extra={"target_crs": target_crs, "resampling": resampling, **meta},
        )


@register_module_decorator(name="preprocess_resample", aliases=["resample"])
class PreprocessResampleModule(BaseModule):
    name = "preprocess_resample"
    description = "Resample a raster to a target resolution."
    input_ports = [
        PortSpec(name="raster", kind="data", data_class="raster", required=False),
        PortSpec(
            name="manifest",
            kind="artifact",
            data_class="product_manifest",
            required=False,
        ),
    ]
    output_ports = [
        PortSpec(name="raster", kind="data", data_class="raster"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {
        "target_resolution": 1000,
        "resampling": "nearest",
        "unit": "meters",
    }

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        import rasterio
        from rasterio.transform import from_bounds
        from rasterio.warp import reproject

        merged = _merged_params(inputs, params)
        target_res = float(merged.get("target_resolution") or 1000)
        unit = str(merged.get("unit") or "meters").lower()
        resampling = str(merged.get("resampling") or "nearest")
        if target_res <= 0:
            raise RasterOpsValidationError("target_resolution must be > 0")

        src_path = resolve_raster_path(inputs, ctx, params=merged)
        bundle = open_raster(src_path)
        emit_progress(ctx, self.name, f"resample {src_path.name}", 5)

        with rasterio.open(src_path) as src:
            west, south, east, north = src.bounds
            if unit == "degrees":
                res_x = target_res
                res_y = target_res
            else:
                # Approximate meters→degrees when geographic; else use linear units
                crs = src.crs
                if crs and crs.is_geographic:
                    # crude mid-latitude conversion
                    mid_lat = (south + north) / 2.0
                    m_per_deg_lat = 111_320.0
                    m_per_deg_lon = 111_320.0 * max(np.cos(np.deg2rad(mid_lat)), 1e-6)
                    res_x = target_res / m_per_deg_lon
                    res_y = target_res / m_per_deg_lat
                else:
                    res_x = target_res
                    res_y = target_res

            width = max(1, int(np.ceil((east - west) / res_x)))
            height = max(1, int(np.ceil((north - south) / res_y)))
            if width * height > 50_000_000:
                raise RasterOpsValidationError(
                    f"Resample output too large ({width}x{height}); raise resolution or clip first"
                )
            transform = from_bounds(west, south, east, north, width, height)
            count = src.count
            dst = np.full((count, height, width), np.nan, dtype=np.float64)
            for i in range(1, count + 1):
                band = src.read(i).astype(np.float64)
                if src.nodata is not None:
                    band = np.where(band == src.nodata, np.nan, band)
                reproject(
                    source=band,
                    destination=dst[i - 1],
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=src.crs,
                    resampling=resampling_enum(resampling),
                    src_nodata=np.nan,
                    dst_nodata=np.nan,
                )
            out_data = dst[0] if count == 1 else dst
            crs = src.crs.to_string() if src.crs else bundle.crs

        out_dir = _out_dir(ctx, "resample")
        write_cog(
            out_data,
            out_dir,
            f"{src_path.stem}_resample",
            transform=transform,
            crs=crs,
            dtype="float32",
        )
        uri = str(out_dir / f"{src_path.stem}_resample.tif")
        return store_raster_manifest(
            ctx,
            module_name=self.name,
            uri=uri,
            extra={
                "target_resolution": target_res,
                "unit": unit,
                "resampling": resampling,
            },
        )


@register_module_decorator(name="preprocess_clip", aliases=["clip_raster"])
class PreprocessClipModule(BaseModule):
    name = "preprocess_clip"
    description = "Clip a raster by bbox with optional meter buffer."
    input_ports = [
        PortSpec(name="raster", kind="data", data_class="raster", required=False),
        # Optional at graph-bind time: bbox edges are scraped to job_request /
        # algorithm_params (same pattern as fusion_spatial_interpolate).
        PortSpec(name="bbox", kind="geometry", data_class="bbox", required=False),
        PortSpec(
            name="manifest",
            kind="artifact",
            data_class="product_manifest",
            required=False,
        ),
    ]
    output_ports = [
        PortSpec(name="raster", kind="data", data_class="raster"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"buffer_meters": 0}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        import rasterio
        from rasterio.windows import from_bounds, transform as window_transform

        merged = _merged_params(inputs, params)
        bbox = parse_bbox(inputs.get("bbox") or merged.get("bbox"))
        if bbox is None and all(
            k in merged for k in ("bbox_west", "bbox_south", "bbox_east", "bbox_north")
        ):
            bbox = (
                float(merged["bbox_west"]),
                float(merged["bbox_south"]),
                float(merged["bbox_east"]),
                float(merged["bbox_north"]),
            )
        if bbox is None:
            region = getattr(ctx.request, "region", None)
            if region is not None:
                bbox = parse_bbox(getattr(region, "bbox", None) or region)
        if bbox is None:
            raise RasterOpsValidationError("clip requires bbox (west,south,east,north)")
        west, south, east, north = bbox
        buffer_m = float(merged.get("buffer_meters") or 0)

        src_path = resolve_raster_path(inputs, ctx, params=merged)
        with rasterio.open(src_path) as src:
            if buffer_m > 0:
                if src.crs and src.crs.is_geographic:
                    mid_lat = (south + north) / 2.0
                    dlat = buffer_m / 111_320.0
                    dlon = buffer_m / (
                        111_320.0 * max(np.cos(np.deg2rad(mid_lat)), 1e-6)
                    )
                    west -= dlon
                    east += dlon
                    south -= dlat
                    north += dlat
                else:
                    west -= buffer_m
                    east += buffer_m
                    south -= buffer_m
                    north += buffer_m

            window = from_bounds(west, south, east, north, transform=src.transform)
            window = window.round_lengths().round_offsets()
            if window.width <= 0 or window.height <= 0:
                raise RasterOpsValidationError(
                    "Clip window is empty; check bbox vs raster extent"
                )
            data = src.read(window=window).astype(np.float64)
            if src.nodata is not None:
                data = np.where(data == src.nodata, np.nan, data)
            if data.shape[0] == 1:
                data = data[0]
            transform = window_transform(window, src.transform)
            crs = src.crs.to_string() if src.crs else "EPSG:4326"

        out_dir = _out_dir(ctx, "clip")
        write_cog(data, out_dir, f"{src_path.stem}_clip", transform=transform, crs=crs)
        uri = str(out_dir / f"{src_path.stem}_clip.tif")
        return store_raster_manifest(
            ctx,
            module_name=self.name,
            uri=uri,
            extra={"bbox": [west, south, east, north], "buffer_meters": buffer_m},
        )


@register_module_decorator(name="preprocess_mask", aliases=["mask_raster"])
class PreprocessMaskModule(BaseModule):
    name = "preprocess_mask"
    description = "Mask a raster using another raster (aligned to primary grid)."
    input_ports = [
        PortSpec(name="raster", kind="data", data_class="raster", required=False),
        PortSpec(name="mask", kind="data", data_class="raster", required=False),
        PortSpec(
            name="manifest",
            kind="artifact",
            data_class="product_manifest",
            required=False,
        ),
    ]
    output_ports = [
        PortSpec(name="raster", kind="data", data_class="raster"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"mask_value": 0, "invert": False}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        merged = _merged_params(inputs, params)
        mask_value = float(
            merged.get("mask_value") if merged.get("mask_value") is not None else 0
        )
        invert = bool(merged.get("invert", False))

        raster_path = resolve_raster_path(inputs, ctx, keys=("raster",), params=merged)
        # Mask may be under key "mask"
        mask_inputs = dict(inputs)
        if "mask" in inputs:
            mask_inputs = {**inputs, "raster": inputs.get("mask")}
        try:
            mask_path = resolve_raster_path(
                mask_inputs, ctx, keys=("raster", "mask"), params=merged
            )
        except Exception as exc:
            raise RasterOpsValidationError(f"mask raster required: {exc}") from exc

        primary = open_raster(raster_path)
        secondary = open_raster(mask_path)
        aligned = align_rasters(primary, secondary, resampling="nearest")
        data = primary.band(0).copy()
        mask_arr = aligned.band(0)
        keep = mask_arr != mask_value
        if invert:
            keep = ~keep
        data = np.where(keep, data, np.nan)

        out_dir = _out_dir(ctx, "mask")
        write_cog(
            data,
            out_dir,
            f"{raster_path.stem}_masked",
            transform=primary.transform,
            crs=primary.crs,
        )
        uri = str(out_dir / f"{raster_path.stem}_masked.tif")
        return store_raster_manifest(
            ctx,
            module_name=self.name,
            uri=uri,
            extra={"mask_value": mask_value, "invert": invert},
        )
