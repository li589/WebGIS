"""GIS tool modules: buffer, zonal stats, calculator, conversions, terrain, watershed."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from contracts.product import ProductRef
from modules.base import BaseModule
from modules.registry import register_module_decorator
from modules._raster_ops import (
    RasterOpsValidationError,
    apply_remap,
    emit_progress,
    finite_mask,
    open_raster,
    parse_bbox,
    parse_remap_table,
    resolve_geojson,
    resolve_raster_path,
    safe_raster_expression,
    store_geojson_manifest,
    store_raster_manifest,
    write_cog,
)
from workflow.schemas import NodeExecutionContext, PortSpec


def _merged(inputs: dict[str, object], params: dict[str, object]) -> dict[str, object]:
    return {**(dict(inputs.get("algorithm_params", {}) or {})), **dict(params or {})}


def _out(ctx: NodeExecutionContext, name: str) -> Path:
    d = Path(ctx.workspace) / "products" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


@register_module_decorator(name="gis_buffer_analysis", aliases=["buffer_analysis"])
class GisBufferModule(BaseModule):
    name = "gis_buffer_analysis"
    description = "Create geodesic/projected buffers around vector features."
    input_ports = [
        PortSpec(name="points", kind="data", data_class="geojson", required=False),
        PortSpec(name="distance", kind="value", data_class="number", required=False),
    ]
    output_ports = [
        PortSpec(name="buffer", kind="data", data_class="geojson"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"distance_unit": "meters", "segments": 16}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        from shapely.geometry import mapping, shape
        from shapely.ops import transform as shp_transform
        import pyproj

        merged = _merged(inputs, params)
        gj = resolve_geojson(inputs, ctx, keys=("points", "vector", "data"))
        distance = float(
            inputs.get("distance")
            if inputs.get("distance") is not None
            else merged.get("distance", 1000)
        )
        unit = str(merged.get("distance_unit") or "meters").lower()
        segments = int(merged.get("segments") or 16)
        if distance <= 0:
            raise RasterOpsValidationError("distance must be > 0")

        if unit == "kilometers":
            distance_m = distance * 1000.0
        elif unit == "degrees":
            distance_m = None
            distance_deg = distance
        else:
            distance_m = distance
            distance_deg = None

        features_out = []
        for feat in gj.get("features") or []:
            geom = shape(feat.get("geometry"))
            if geom.is_empty:
                continue
            if distance_m is not None:
                # Project to local Azimuthal Equidistant around centroid
                lon, lat = geom.centroid.x, geom.centroid.y
                proj = pyproj.Proj(proj="aeqd", lat_0=lat, lon_0=lon, datum="WGS84")
                wgs84 = pyproj.Proj("EPSG:4326")
                project = pyproj.Transformer.from_proj(
                    wgs84, proj, always_xy=True
                ).transform
                project_back = pyproj.Transformer.from_proj(
                    proj, wgs84, always_xy=True
                ).transform
                local = shp_transform(project, geom)
                buffered = local.buffer(distance_m, quad_segs=segments)
                out_geom = shp_transform(project_back, buffered)
            else:
                out_geom = geom.buffer(distance_deg, quad_segs=segments)
            props = dict(feat.get("properties") or {})
            props["buffer_distance"] = distance
            props["buffer_unit"] = unit
            features_out.append(
                {"type": "Feature", "geometry": mapping(out_geom), "properties": props}
            )

        out_gj = {"type": "FeatureCollection", "features": features_out}
        path = _out(ctx, "buffer") / "buffer.geojson"
        return store_geojson_manifest(
            ctx,
            module_name=self.name,
            geojson=out_gj,
            output_path=path,
            port_name="buffer",
            extra={"feature_count": len(features_out)},
        )


@register_module_decorator(name="gis_zonal_statistics", aliases=["zonal_statistics"])
class GisZonalStatisticsModule(BaseModule):
    name = "gis_zonal_statistics"
    description = "Compute per-polygon raster statistics."
    input_ports = [
        PortSpec(name="raster", kind="data", data_class="raster", required=False),
        PortSpec(name="zones", kind="data", data_class="geojson", required=False),
    ]
    output_ports = [
        PortSpec(name="stats", kind="data", data_class="geojson"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"statistic": "mean", "band": 0, "all_touched": False}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        from rasterio.features import geometry_mask
        from shapely.geometry import mapping, shape

        merged = _merged(inputs, params)
        statistic = str(merged.get("statistic") or "mean").lower()
        band = int(merged.get("band") or 0)
        all_touched = bool(merged.get("all_touched", False))
        allowed = {"mean", "median", "sum", "min", "max", "count"}
        if statistic not in allowed:
            raise RasterOpsValidationError(
                f"statistic must be one of {sorted(allowed)}"
            )

        raster_path = resolve_raster_path(inputs, ctx, params=merged)
        zones = resolve_geojson(inputs, ctx, keys=("zones", "vector", "points"))
        bundle = open_raster(raster_path, band=band)
        data = bundle.band(0)
        emit_progress(ctx, self.name, f"zonal {statistic}", 10)

        features_out = []
        for idx, feat in enumerate(zones.get("features") or []):
            geom = shape(feat.get("geometry"))
            if geom.is_empty:
                continue
            mask = geometry_mask(
                [mapping(geom)],
                out_shape=data.shape,
                transform=bundle.transform,
                invert=True,
                all_touched=all_touched,
            )
            vals = data[mask]
            vals = vals[finite_mask(vals)]
            props = dict(feat.get("properties") or {})
            if vals.size == 0:
                props["stat_value"] = None
                props["stat_count"] = 0
            else:
                if statistic == "mean":
                    props["stat_value"] = float(np.mean(vals))
                elif statistic == "median":
                    props["stat_value"] = float(np.median(vals))
                elif statistic == "sum":
                    props["stat_value"] = float(np.sum(vals))
                elif statistic == "min":
                    props["stat_value"] = float(np.min(vals))
                elif statistic == "max":
                    props["stat_value"] = float(np.max(vals))
                else:
                    props["stat_value"] = float(vals.size)
                props["stat_count"] = int(vals.size)
            props["statistic"] = statistic
            props["zone_index"] = idx
            features_out.append(
                {"type": "Feature", "geometry": mapping(geom), "properties": props}
            )

        out_gj = {"type": "FeatureCollection", "features": features_out}
        out_dir = _out(ctx, "zonal")
        path = out_dir / "zonal_stats.geojson"

        # Analysis panel: structured table (+ optional bar chart) for InfoPanel.
        columns = ["zone_index", "stat_value", "stat_count", "statistic"]
        rows: list[list[object]] = []
        for feat in features_out:
            props = dict(feat.get("properties") or {})
            rows.append(
                [
                    props.get("zone_index"),
                    props.get("stat_value"),
                    props.get("stat_count"),
                    props.get("statistic") or statistic,
                ]
            )
        table = {
            "schema_version": "1",
            "title": f"Zonal {statistic}",
            "columns": columns,
            "rows": rows,
            "units": {},
            "dtypes": {
                "zone_index": "int64",
                "stat_value": "float64",
                "stat_count": "int64",
                "statistic": "string",
            },
        }
        table_path = out_dir / "zonal_stats.table.json"
        table_path.write_text(json.dumps(table, ensure_ascii=True), encoding="utf-8")
        chart = {
            "schema_version": "1",
            "chart_type": "bar",
            "title": f"Zonal {statistic}",
            "x_label": "zone",
            "y_label": statistic,
            "unit": "",
            "series": [
                {
                    "name": statistic,
                    "x": [str(r[0]) for r in rows],
                    "y": [
                        float(r[1]) if isinstance(r[1], (int, float)) else None
                        for r in rows
                    ],
                }
            ],
            "x": [str(r[0]) for r in rows],
            "y": [
                float(r[1]) if isinstance(r[1], (int, float)) else None for r in rows
            ],
            "series_name": statistic,
        }
        chart_path = out_dir / "zonal_stats.chart.json"
        chart_path.write_text(json.dumps(chart, ensure_ascii=True), encoding="utf-8")
        extra_products = [
            ProductRef(
                name="zonal_stats_table",
                type="table_spec",
                uri=str(table_path),
                variable=statistic,
                tags={"kind": "table", "module": self.name},
            ),
            ProductRef(
                name="zonal_stats_chart",
                type="chart_spec",
                uri=str(chart_path),
                variable=statistic,
                tags={
                    "kind": "chart",
                    "chart_type": "bar",
                    "module": self.name,
                },
            ),
        ]
        return store_geojson_manifest(
            ctx,
            module_name=self.name,
            geojson=out_gj,
            output_path=path,
            port_name="stats",
            extra={"statistic": statistic, "zone_count": len(features_out)},
            extra_products=extra_products,
            table_uris=[str(table_path)],
        )


@register_module_decorator(name="gis_raster_calculator", aliases=["raster_calculator"])
class GisRasterCalculatorModule(BaseModule):
    name = "gis_raster_calculator"
    description = "Evaluate a whitelist AST expression over rasters A/B."
    input_ports = [
        PortSpec(name="a", kind="data", data_class="raster", required=False),
        PortSpec(name="b", kind="data", data_class="raster", required=False),
        PortSpec(name="raster", kind="data", data_class="raster", required=False),
    ]
    output_ports = [
        PortSpec(name="result", kind="data", data_class="raster"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"expression": "A", "nodata_handling": "propagate"}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        from modules._raster_ops import align_rasters

        merged = _merged(inputs, params)
        expression = str(merged.get("expression") or "A")
        nodata_handling = str(merged.get("nodata_handling") or "propagate").lower()

        # Resolve A
        a_inputs = dict(inputs)
        if inputs.get("a") is not None:
            a_inputs["raster"] = inputs["a"]
        a_path = resolve_raster_path(a_inputs, ctx, keys=("raster", "a"), params=merged)
        primary = open_raster(a_path)
        variables = {"A": primary.band(0), "a": primary.band(0)}

        if inputs.get("b") is not None or merged.get("b"):
            b_inputs = {**inputs, "raster": inputs.get("b")}
            b_path = resolve_raster_path(
                b_inputs, ctx, keys=("raster", "b"), params=merged
            )
            secondary = open_raster(b_path)
            aligned = align_rasters(primary, secondary)
            variables["B"] = aligned.band(0)
            variables["b"] = aligned.band(0)

        result = safe_raster_expression(expression, variables)
        if nodata_handling == "propagate":
            # already NaN-aware for many ops; ensure A nan propagates when referenced
            pass
        elif nodata_handling == "zero":
            result = np.nan_to_num(result, nan=0.0)
        elif nodata_handling == "ignore":
            result = np.where(np.isfinite(result), result, 0.0)
        else:
            raise RasterOpsValidationError(
                f"Unknown nodata_handling {nodata_handling!r}"
            )

        out_dir = _out(ctx, "raster_calc")
        write_cog(
            result,
            out_dir,
            "calc_result",
            transform=primary.transform,
            crs=primary.crs,
        )
        uri = str(out_dir / "calc_result.tif")
        result_ports = store_raster_manifest(
            ctx,
            module_name=self.name,
            uri=uri,
            extra={"expression": expression, "nodata_handling": nodata_handling},
        )
        result_ports["result"] = uri
        return result_ports


@register_module_decorator(name="gis_vector_to_raster", aliases=["vector_to_raster"])
class GisVectorToRasterModule(BaseModule):
    name = "gis_vector_to_raster"
    description = "Rasterize vector attributes into a GeoTIFF."
    input_ports = [
        PortSpec(name="vector", kind="data", data_class="geojson", required=False),
        PortSpec(name="bbox", kind="geometry", data_class="bbox", required=False),
    ]
    output_ports = [
        PortSpec(name="raster", kind="data", data_class="raster"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {
        "attribute_field": "",
        "resolution": 1000,
        "dtype": "float32",
        "fill_value": 0,
    }

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        from rasterio import features, transform as rio_transform

        merged = _merged(inputs, params)
        gj = resolve_geojson(inputs, ctx, keys=("vector", "points", "zones"))
        field = str(merged.get("attribute_field") or "").strip()
        resolution = float(merged.get("resolution") or 1000)
        fill_value = float(merged.get("fill_value") or 0)
        dtype = str(merged.get("dtype") or "float32")
        bbox = parse_bbox(inputs.get("bbox") or merged.get("bbox"))
        if bbox is None:
            # derive from features
            from shapely.geometry import shape as sh_shape
            from shapely.ops import unary_union

            geoms = [
                sh_shape(f["geometry"])
                for f in (gj.get("features") or [])
                if f.get("geometry")
            ]
            if not geoms:
                raise RasterOpsValidationError(
                    "vector_to_raster needs features or bbox"
                )
            minx, miny, maxx, maxy = unary_union(geoms).bounds
            bbox = (minx, miny, maxx, maxy)
        west, south, east, north = bbox
        if resolution <= 0:
            raise RasterOpsValidationError("resolution must be > 0")
        # Treat resolution as degrees if span looks geographic and res large
        width = max(1, int(np.ceil((east - west) / resolution)))
        height = max(1, int(np.ceil((north - south) / resolution)))
        if width * height > 50_000_000:
            raise RasterOpsValidationError(f"Output too large ({width}x{height})")
        transform = rio_transform.from_bounds(west, south, east, north, width, height)

        shapes = []
        for feat in gj.get("features") or []:
            geom = feat.get("geometry")
            if not geom:
                continue
            props = feat.get("properties") or {}
            if field:
                val = props.get(field, fill_value)
            else:
                val = 1
            try:
                val_f = float(val)
            except (TypeError, ValueError):
                val_f = fill_value
            shapes.append((geom, val_f))

        if not shapes:
            raise RasterOpsValidationError("No burnable geometries")

        arr = features.rasterize(
            shapes,
            out_shape=(height, width),
            transform=transform,
            fill=fill_value,
            dtype=np.float64,
        )
        out_dir = _out(ctx, "vector_raster")
        write_cog(
            arr,
            out_dir,
            "rasterized",
            transform=transform,
            crs="EPSG:4326",
            dtype=dtype,
        )
        uri = str(out_dir / "rasterized.tif")
        return store_raster_manifest(
            ctx, module_name=self.name, uri=uri, extra={"attribute_field": field}
        )


@register_module_decorator(name="gis_raster_to_vector", aliases=["raster_to_vector"])
class GisRasterToVectorModule(BaseModule):
    name = "gis_raster_to_vector"
    description = "Polygonize raster cells above a threshold."
    input_ports = [
        PortSpec(name="raster", kind="data", data_class="raster", required=False),
    ]
    output_ports = [
        PortSpec(name="vector", kind="data", data_class="geojson"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"band": 0, "threshold": 0, "simplify_tolerance": 0}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        from rasterio import features
        from shapely.geometry import mapping, shape

        merged = _merged(inputs, params)
        band = int(merged.get("band") or 0)
        threshold = float(merged.get("threshold") or 0)
        simplify = float(merged.get("simplify_tolerance") or 0)
        path = resolve_raster_path(inputs, ctx, params=merged)
        bundle = open_raster(path, band=band)
        data = bundle.band(0)
        mask = finite_mask(data) & (data > threshold)
        labeled = mask.astype(np.uint8)

        feats = []
        for geom, val in features.shapes(
            labeled, mask=mask, transform=bundle.transform
        ):
            if int(val) == 0:
                continue
            g = shape(geom)
            if simplify > 0:
                g = g.simplify(simplify, preserve_topology=True)
            feats.append(
                {
                    "type": "Feature",
                    "geometry": mapping(g),
                    "properties": {"value": 1, "threshold": threshold},
                }
            )
        out_gj = {"type": "FeatureCollection", "features": feats}
        out_path = _out(ctx, "raster_vector") / "polygons.geojson"
        return store_geojson_manifest(
            ctx,
            module_name=self.name,
            geojson=out_gj,
            output_path=out_path,
            port_name="vector",
            extra={"feature_count": len(feats)},
        )


@register_module_decorator(name="gis_reclassify", aliases=["reclassify"])
class GisReclassifyModule(BaseModule):
    name = "gis_reclassify"
    description = "Reclassify raster values using a remap table."
    input_ports = [
        PortSpec(name="raster", kind="data", data_class="raster", required=False),
    ]
    output_ports = [
        PortSpec(name="raster", kind="data", data_class="raster"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"remap_table": "0-30:1,30-60:2,60-100:3", "nodata_value": -9999}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        merged = _merged(inputs, params)
        table = str(merged.get("remap_table") or "")
        nodata_value = float(
            merged.get("nodata_value")
            if merged.get("nodata_value") is not None
            else -9999
        )
        rules = parse_remap_table(table)
        path = resolve_raster_path(inputs, ctx, params=merged)
        bundle = open_raster(path)
        out = apply_remap(bundle.band(0), rules, nodata_value=nodata_value)
        out_dir = _out(ctx, "reclassify")
        write_cog(
            out,
            out_dir,
            f"{path.stem}_reclass",
            transform=bundle.transform,
            crs=bundle.crs,
            nodata=nodata_value,
        )
        uri = str(out_dir / f"{path.stem}_reclass.tif")
        return store_raster_manifest(
            ctx, module_name=self.name, uri=uri, extra={"rules": len(rules)}
        )


@register_module_decorator(name="gis_contour", aliases=["contour"])
class GisContourModule(BaseModule):
    name = "gis_contour"
    description = "Extract contour lines from a raster surface."
    input_ports = [
        PortSpec(name="raster", kind="data", data_class="raster", required=False),
    ]
    output_ports = [
        PortSpec(name="contours", kind="data", data_class="geojson"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"interval": 100, "band": 0, "smoothing": True}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from shapely.geometry import LineString, mapping

        merged = _merged(inputs, params)
        interval = float(merged.get("interval") or 100)
        band = int(merged.get("band") or 0)
        if interval <= 0:
            raise RasterOpsValidationError("interval must be > 0")
        path = resolve_raster_path(inputs, ctx, params=merged)
        bundle = open_raster(path, band=band)
        data = bundle.band(0)
        valid = data[finite_mask(data)]
        if valid.size == 0:
            raise RasterOpsValidationError("Raster has no finite values for contours")
        vmin, vmax = float(np.nanmin(valid)), float(np.nanmax(valid))
        if vmax <= vmin:
            levels = [vmin]
        else:
            start = np.floor(vmin / interval) * interval
            levels = list(np.arange(start, vmax + interval, interval))

        # Pixel coordinates → geographic via affine
        transform = bundle.transform
        ys = np.arange(bundle.height)
        xs = np.arange(bundle.width)
        # contour in array index space
        fig, ax = plt.subplots()
        cs = ax.contour(xs, ys, data, levels=levels)
        features = []
        for level, segs in zip(cs.levels, cs.allsegs, strict=False):
            for seg in segs:
                if len(seg) < 2:
                    continue
                coords = []
                for x, y in seg:
                    # rasterio affine: col,row
                    gx = transform.c + x * transform.a + y * transform.b
                    gy = transform.f + x * transform.d + y * transform.e
                    coords.append((float(gx), float(gy)))
                line = LineString(coords)
                if bool(merged.get("smoothing", True)) and line.length > 0:
                    line = line.simplify(
                        abs(transform.a) * 0.25, preserve_topology=True
                    )
                features.append(
                    {
                        "type": "Feature",
                        "geometry": mapping(line),
                        "properties": {"elevation": float(level)},
                    }
                )
        plt.close(fig)
        out_gj = {"type": "FeatureCollection", "features": features}
        out_path = _out(ctx, "contour") / "contours.geojson"
        return store_geojson_manifest(
            ctx,
            module_name=self.name,
            geojson=out_gj,
            output_path=out_path,
            port_name="contours",
            extra={"levels": len(levels), "feature_count": len(features)},
        )


@register_module_decorator(name="gis_slope_aspect", aliases=["slope_aspect"])
class GisSlopeAspectModule(BaseModule):
    name = "gis_slope_aspect"
    description = "Compute slope (deg) and aspect (deg) from DEM (Horn / Zevenbergen)."
    input_ports = [
        PortSpec(name="dem", kind="data", data_class="raster", required=False),
        PortSpec(name="raster", kind="data", data_class="raster", required=False),
    ]
    output_ports = [
        PortSpec(name="slope", kind="data", data_class="raster"),
        PortSpec(name="aspect", kind="data", data_class="raster"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"z_unit": "meters", "algorithm": "horn"}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        merged = _merged(inputs, params)
        algorithm = str(merged.get("algorithm") or "horn").lower()
        z_unit = str(merged.get("z_unit") or "meters").lower()
        path = resolve_raster_path(inputs, ctx, keys=("dem", "raster"), params=merged)
        bundle = open_raster(path)
        dem = bundle.band(0).astype(np.float64)
        if z_unit == "feet":
            dem = dem * 0.3048

        # Pixel size
        px = abs(bundle.transform.a)
        py = abs(bundle.transform.e)
        # Geographic: convert degree cell size to meters (approx)
        if "4326" in bundle.crs or "EPSG:4326" in bundle.crs.upper():
            mid = bundle.transform.f + bundle.transform.e * bundle.height / 2
            m_lat = 111_320.0
            m_lon = 111_320.0 * max(np.cos(np.deg2rad(mid)), 1e-6)
            dx = px * m_lon
            dy = py * m_lat
        else:
            dx = px if px > 0 else 1.0
            dy = py if py > 0 else 1.0

        # Pad for gradients
        z = np.pad(dem, 1, mode="edge")
        if algorithm == "zevenbergen":
            # Zevenbergen & Thorne
            dzdx = (z[1:-1, 2:] - z[1:-1, :-2]) / (2 * dx)
            dzdy = (z[:-2, 1:-1] - z[2:, 1:-1]) / (2 * dy)
        else:
            # Horn (3x3)
            dzdx = (
                (z[:-2, 2:] + 2 * z[1:-1, 2:] + z[2:, 2:])
                - (z[:-2, :-2] + 2 * z[1:-1, :-2] + z[2:, :-2])
            ) / (8 * dx)
            dzdy = (
                (z[:-2, :-2] + 2 * z[:-2, 1:-1] + z[:-2, 2:])
                - (z[2:, :-2] + 2 * z[2:, 1:-1] + z[2:, 2:])
            ) / (8 * dy)

        slope_rad = np.arctan(np.hypot(dzdx, dzdy))
        slope = np.degrees(slope_rad)
        # Aspect: 0=N, 90=E
        aspect = np.degrees(np.arctan2(dzdx, -dzdy))
        aspect = np.mod(aspect, 360.0)
        invalid = ~finite_mask(dem)
        slope[invalid] = np.nan
        aspect[invalid] = np.nan
        # Flat cells: aspect undefined
        flat = slope < 1e-6
        aspect[flat] = -1.0

        out_dir = _out(ctx, "slope_aspect")
        write_cog(slope, out_dir, "slope", transform=bundle.transform, crs=bundle.crs)
        write_cog(aspect, out_dir, "aspect", transform=bundle.transform, crs=bundle.crs)
        slope_uri = str(out_dir / "slope.tif")
        aspect_uri = str(out_dir / "aspect.tif")
        from contracts.product import ProductRef

        result = store_raster_manifest(
            ctx,
            module_name=self.name,
            uri=slope_uri,
            variable="slope",
            product_name="slope",
            extra_products=[
                ProductRef(
                    name="aspect",
                    type="raster",
                    uri=aspect_uri,
                    variable="aspect",
                    tags={"module": self.name, "kind": "raster"},
                )
            ],
            extra={"algorithm": algorithm},
        )
        result["slope"] = slope_uri
        result["aspect"] = aspect_uri
        return result


@register_module_decorator(name="gis_watershed", aliases=["watershed"])
class GisWatershedModule(BaseModule):
    name = "gis_watershed"
    description = "D8 watershed delineation from DEM and pour points (pixel guard)."
    input_ports = [
        PortSpec(name="dem", kind="data", data_class="raster", required=False),
        PortSpec(name="pour_points", kind="data", data_class="geojson", required=False),
    ]
    output_ports = [
        PortSpec(name="watershed", kind="data", data_class="geojson"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {
        "fill_threshold": 0.01,
        "flow_direction": "d8",
        "max_dem_pixels": 4_000_000,
    }

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        from rasterio.transform import rowcol
        from shapely.geometry import shape
        from rasterio import features as rio_features

        merged = _merged(inputs, params)
        flow_dir = str(merged.get("flow_direction") or "d8").lower()
        if flow_dir != "d8":
            raise RasterOpsValidationError("Only D8 flow_direction is supported in v1")
        max_pixels = int(merged.get("max_dem_pixels") or 4_000_000)
        fill_threshold = float(merged.get("fill_threshold") or 0.01)

        dem_path = resolve_raster_path(
            inputs, ctx, keys=("dem", "raster"), params=merged
        )
        pour = resolve_geojson(inputs, ctx, keys=("pour_points", "points", "vector"))
        bundle = open_raster(dem_path)
        dem = bundle.band(0).astype(np.float64)
        if dem.size > max_pixels:
            raise RasterOpsValidationError(
                f"DEM has {dem.size} pixels > max_dem_pixels={max_pixels}; resample or clip first"
            )

        # Simple depression fill (iterative local minima raise)
        filled = dem.copy()
        for _ in range(5):
            padded = np.pad(filled, 1, mode="edge")
            neigh_min = np.min(
                np.stack(
                    [
                        padded[:-2, :-2],
                        padded[:-2, 1:-1],
                        padded[:-2, 2:],
                        padded[1:-1, :-2],
                        padded[1:-1, 2:],
                        padded[2:, :-2],
                        padded[2:, 1:-1],
                        padded[2:, 2:],
                    ]
                ),
                axis=0,
            )
            pits = finite_mask(filled) & (filled + fill_threshold < neigh_min)
            if not np.any(pits):
                break
            filled[pits] = neigh_min[pits]

        # D8 flow direction codes (ESRI): 1 E, 2 SE, 4 S, 8 SW, 16 W, 32 NW, 64 N, 128 NE
        offsets = [
            (0, 1, 1),
            (1, 1, 2),
            (1, 0, 4),
            (1, -1, 8),
            (0, -1, 16),
            (-1, -1, 32),
            (-1, 0, 64),
            (-1, 1, 128),
        ]
        h, w = filled.shape
        fdir = np.zeros((h, w), dtype=np.uint8)
        for r in range(1, h - 1):
            for c in range(1, w - 1):
                z0 = filled[r, c]
                if not np.isfinite(z0):
                    continue
                best_drop = 0.0
                best_code = 0
                for dr, dc, code in offsets:
                    zn = filled[r + dr, c + dc]
                    if not np.isfinite(zn):
                        continue
                    dist = 1.41421356237 if dr and dc else 1.0
                    drop = (z0 - zn) / dist
                    if drop > best_drop:
                        best_drop = drop
                        best_code = code
                fdir[r, c] = best_code

        # Build reverse flow graph: for each cell, who drains into it
        receivers: dict[tuple[int, int], list[tuple[int, int]]] = {}
        code_to_offset = {code: (dr, dc) for dr, dc, code in offsets}
        for r in range(h):
            for c in range(w):
                code = int(fdir[r, c])
                if code not in code_to_offset:
                    continue
                dr, dc = code_to_offset[code]
                nr, nc = r + dr, c + dc
                if 0 <= nr < h and 0 <= nc < w:
                    receivers.setdefault((nr, nc), []).append((r, c))

        # Delineate upstream for each pour point
        from collections import deque

        basin = np.zeros((h, w), dtype=np.uint8)
        for feat in pour.get("features") or []:
            geom = shape(feat.get("geometry"))
            if geom.geom_type != "Point":
                geom = geom.centroid
            row, col = rowcol(bundle.transform, geom.x, geom.y)
            if not (0 <= row < h and 0 <= col < w):
                continue
            q = deque([(int(row), int(col))])
            seen = {(int(row), int(col))}
            while q:
                rr, cc = q.popleft()
                basin[rr, cc] = 1
                for pr, pc in receivers.get((rr, cc), []):
                    if (pr, pc) not in seen:
                        seen.add((pr, pc))
                        q.append((pr, pc))

        feats = []
        for geom, val in rio_features.shapes(
            basin, mask=basin.astype(bool), transform=bundle.transform
        ):
            if int(val) == 0:
                continue
            feats.append(
                {
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {"watershed_id": 1},
                }
            )
        out_gj = {"type": "FeatureCollection", "features": feats}
        out_path = _out(ctx, "watershed") / "watershed.geojson"
        return store_geojson_manifest(
            ctx,
            module_name=self.name,
            geojson=out_gj,
            output_path=out_path,
            port_name="watershed",
            extra={"feature_count": len(feats), "dem_pixels": int(dem.size)},
        )
