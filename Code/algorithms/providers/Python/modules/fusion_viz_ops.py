"""Fusion and visualization modules: interpolate, merge, stats summary, report export."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from contracts.product import ProductManifest, ProductRef
from modules.base import BaseModule
from modules.registry import register_module_decorator
from modules._raster_ops import (
    RasterOpsValidationError,
    align_rasters,
    emit_progress,
    finite_mask,
    open_raster,
    parse_bbox,
    resolve_geojson,
    resolve_raster_path,
    store_geojson_manifest,
    store_raster_manifest,
    write_cog,
)
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec


def _merged(inputs: dict[str, object], params: dict[str, object]) -> dict[str, object]:
    return {**(dict(inputs.get("algorithm_params", {}) or {})), **dict(params or {})}


def _out(ctx: NodeExecutionContext, name: str) -> Path:
    d = Path(ctx.workspace) / "products" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


@register_module_decorator(
    name="fusion_spatial_interpolate", aliases=["spatial_interpolate"]
)
class FusionSpatialInterpolateModule(BaseModule):
    name = "fusion_spatial_interpolate"
    description = (
        "Interpolate point samples to a raster (IDW / nearest; kriging experimental)."
    )
    input_ports = [
        PortSpec(name="points", kind="data", data_class="geojson", required=False),
        PortSpec(name="bbox", kind="geometry", data_class="bbox", required=False),
    ]
    output_ports = [
        PortSpec(name="raster", kind="data", data_class="raster"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {
        "method": "idw",
        "power": 2.0,
        "resolution": 1000,
        "value_field": "value",
        "max_points": 5000,
    }

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        from rasterio.transform import from_bounds
        from shapely.geometry import shape

        merged = _merged(inputs, params)
        method = str(merged.get("method") or "idw").lower()
        power = float(merged.get("power") or 2.0)
        resolution = float(merged.get("resolution") or 1000)
        value_field = str(merged.get("value_field") or "value")
        max_points = int(merged.get("max_points") or 5000)

        gj = resolve_geojson(inputs, ctx, keys=("points", "vector", "data"))
        xs, ys, vs = [], [], []
        for feat in gj.get("features") or []:
            geom = shape(feat.get("geometry"))
            if geom.is_empty:
                continue
            pt = geom if geom.geom_type == "Point" else geom.centroid
            props = feat.get("properties") or {}
            if value_field not in props:
                continue
            try:
                vs.append(float(props[value_field]))
            except (TypeError, ValueError):
                continue
            xs.append(float(pt.x))
            ys.append(float(pt.y))
        if len(vs) < 1:
            raise RasterOpsValidationError(
                f"No point values found for field {value_field!r}"
            )
        if len(vs) > max_points:
            raise RasterOpsValidationError(
                f"Point count {len(vs)} > max_points={max_points}"
            )
        xs_a = np.asarray(xs, dtype=np.float64)
        ys_a = np.asarray(ys, dtype=np.float64)
        vs_a = np.asarray(vs, dtype=np.float64)

        bbox = parse_bbox(inputs.get("bbox") or merged.get("bbox"))
        if bbox is None:
            pad = resolution
            bbox = (
                float(xs_a.min() - pad),
                float(ys_a.min() - pad),
                float(xs_a.max() + pad),
                float(ys_a.max() + pad),
            )
        west, south, east, north = bbox
        width = max(1, int(np.ceil((east - west) / resolution)))
        height = max(1, int(np.ceil((north - south) / resolution)))
        if width * height > 20_000_000:
            raise RasterOpsValidationError(f"Grid too large ({width}x{height})")
        transform = from_bounds(west, south, east, north, width, height)

        # Cell centers
        cols = np.arange(width)
        rows = np.arange(height)
        # affine: x = c + col*a, y = f + row*e
        gx = transform.c + (cols + 0.5) * transform.a
        gy = transform.f + (rows + 0.5) * transform.e
        grid_x, grid_y = np.meshgrid(gx, gy)

        emit_progress(ctx, self.name, f"{method} n={len(vs)}", 20)
        if method == "nearest":
            # For each cell, nearest sample (vectorized via chunking rows)
            out = np.empty((height, width), dtype=np.float64)
            for r in range(height):
                dx = grid_x[r : r + 1, :] - xs_a[:, None]
                dy = grid_y[r : r + 1, :] - ys_a[:, None]
                dist2 = dx * dx + dy * dy
                idx = np.argmin(dist2, axis=0)
                out[r, :] = vs_a[idx]
        elif method == "idw":
            out = np.empty((height, width), dtype=np.float64)
            eps = 1e-12
            for r in range(height):
                dx = grid_x[r : r + 1, :] - xs_a[:, None]
                dy = grid_y[r : r + 1, :] - ys_a[:, None]
                dist = np.sqrt(dx * dx + dy * dy)
                w = 1.0 / np.maximum(dist, eps) ** power
                # exact hits
                exact = dist < eps
                if np.any(exact):
                    # for columns with exact match, use that value
                    col_has = np.any(exact, axis=0)
                    out_row = np.sum(w * vs_a[:, None], axis=0) / np.sum(w, axis=0)
                    for c in np.where(col_has)[0]:
                        out_row[c] = vs_a[np.argmax(exact[:, c])]
                    out[r, :] = out_row
                else:
                    out[r, :] = np.sum(w * vs_a[:, None], axis=0) / np.sum(w, axis=0)
        elif method == "kriging":
            raise RasterOpsValidationError(
                "kriging is experimental and not enabled; use idw or nearest"
            )
        else:
            raise RasterOpsValidationError(f"Unknown method {method!r}")

        out_dir = _out(ctx, "interpolate")
        write_cog(out, out_dir, "interpolated", transform=transform, crs="EPSG:4326")
        uri = str(out_dir / "interpolated.tif")
        return store_raster_manifest(
            ctx,
            module_name=self.name,
            uri=uri,
            extra={"method": method, "point_count": int(len(vs))},
        )


@register_module_decorator(
    name="fusion_multi_source_merge", aliases=["multi_source_merge"]
)
class FusionMultiSourceMergeModule(BaseModule):
    name = "fusion_multi_source_merge"
    description = "Merge two aligned rasters (weighted; PCA/bayesian deferred)."
    input_ports = [
        PortSpec(name="primary", kind="data", data_class="raster", required=False),
        PortSpec(name="secondary", kind="data", data_class="raster", required=False),
    ]
    output_ports = [
        PortSpec(name="merged", kind="data", data_class="raster"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"method": "weighted", "weight_primary": 0.6}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        merged_p = _merged(inputs, params)
        method = str(merged_p.get("method") or "weighted").lower()
        w1 = float(
            merged_p.get("weight_primary")
            if merged_p.get("weight_primary") is not None
            else 0.6
        )
        w1 = min(max(w1, 0.0), 1.0)
        w2 = 1.0 - w1

        a_inputs = {**inputs, "raster": inputs.get("primary")}
        b_inputs = {**inputs, "raster": inputs.get("secondary")}
        a_path = resolve_raster_path(
            a_inputs, ctx, keys=("raster", "primary"), params=merged_p
        )
        b_path = resolve_raster_path(
            b_inputs, ctx, keys=("raster", "secondary"), params=merged_p
        )
        primary = open_raster(a_path)
        secondary = open_raster(b_path)
        aligned = align_rasters(primary, secondary)
        a = primary.band(0)
        b = aligned.band(0)

        if method == "weighted":
            out = w1 * a + w2 * b
            # propagate nan if either missing
            out = np.where(finite_mask(a) & finite_mask(b), out, np.nan)
        elif method in {"pca", "bayesian"}:
            raise RasterOpsValidationError(
                f"{method} merge is deferred to a later phase; use weighted"
            )
        else:
            raise RasterOpsValidationError(f"Unknown method {method!r}")

        out_dir = _out(ctx, "merge")
        write_cog(out, out_dir, "merged", transform=primary.transform, crs=primary.crs)
        uri = str(out_dir / "merged.tif")
        result = store_raster_manifest(
            ctx,
            module_name=self.name,
            uri=uri,
            extra={"method": method, "weight_primary": w1},
        )
        result["merged"] = uri
        return result


@register_module_decorator(
    name="viz_statistics_summary", aliases=["statistics_summary"]
)
class VizStatisticsSummaryModule(BaseModule):
    name = "viz_statistics_summary"
    description = "Emit mean/std/percentiles summary as GeoJSON + table JSON."
    input_ports = [
        PortSpec(name="data", kind="data", data_class="data", required=False),
        PortSpec(name="raster", kind="data", data_class="raster", required=False),
    ]
    output_ports = [
        PortSpec(name="summary", kind="data", data_class="geojson"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {
        "include_mean": True,
        "include_std": True,
        "include_percentiles": True,
        "percentile_list": "25,50,75",
    }

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        merged = _merged(inputs, params)
        include_mean = bool(merged.get("include_mean", True))
        include_std = bool(merged.get("include_std", True))
        include_pct = bool(merged.get("include_percentiles", True))
        pct_list = [
            float(x.strip())
            for x in str(merged.get("percentile_list") or "25,50,75").split(",")
            if x.strip()
        ]

        # Prefer raster
        try:
            path = resolve_raster_path(
                inputs, ctx, keys=("raster", "data"), params=merged
            )
            vals = open_raster(path).band(0)
            vals = vals[finite_mask(vals)]
        except Exception:
            # timeseries-like
            from modules._raster_ops import load_timeseries_payload

            payload = load_timeseries_payload(inputs, ctx, keys=("data", "timeseries"))
            vals = np.asarray(
                payload.get("values") or payload.get("y") or [], dtype=np.float64
            )
            vals = vals[finite_mask(vals)]

        if vals.size == 0:
            raise RasterOpsValidationError("No finite values for statistics summary")

        props: dict[str, object] = {"count": int(vals.size)}
        if include_mean:
            props["mean"] = float(np.mean(vals))
        if include_std:
            props["std"] = float(np.std(vals))
        if include_pct:
            for p in pct_list:
                props[f"p{int(p)}"] = float(np.percentile(vals, p))

        gj = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                    "properties": props,
                }
            ],
        }
        out_dir = _out(ctx, "stats_summary")
        table_path = out_dir / "summary.table.json"
        table_path.write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "title": "Statistics summary",
                    "columns": list(props.keys()),
                    "rows": [list(props.values())],
                },
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
        geo_path = out_dir / "summary.geojson"
        result = store_geojson_manifest(
            ctx,
            module_name=self.name,
            geojson=gj,
            output_path=geo_path,
            port_name="summary",
            extra=props,
        )
        # Attach table product into existing manifest
        manifest_art = result["manifest"]
        loaded = ctx.artifact_store.load(manifest_art.artifact_id)
        if isinstance(loaded, ProductManifest):
            loaded.products.append(
                ProductRef(
                    name="summary_table",
                    type="table_spec",
                    uri=str(table_path),
                    tags={"module": self.name, "kind": "table"},
                )
            )
            loaded.tables.append(str(table_path))
            ctx.artifact_store.put(manifest_art, payload=loaded)
        return result


@register_module_decorator(name="viz_report_export", aliases=["report_export"])
class VizReportExportModule(BaseModule):
    name = "viz_report_export"
    description = "Export analysis results to HTML or Markdown report (PDF/DOCX later)."
    input_ports = [
        PortSpec(name="data", kind="data", data_class="data", required=False),
        PortSpec(
            name="manifest",
            kind="artifact",
            data_class="product_manifest",
            required=False,
        ),
    ]
    output_ports = [
        PortSpec(name="filepath", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {
        "format": "html",
        "template": "default",
        "include_charts": True,
    }

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        merged = _merged(inputs, params)
        fmt = str(merged.get("format") or "html").lower()
        include_charts = bool(merged.get("include_charts", True))
        if fmt in {"pdf", "docx"}:
            raise RasterOpsValidationError(
                f"{fmt} export requires optional deps; use html or markdown in v1"
            )
        if fmt not in {"html", "markdown", "md"}:
            raise RasterOpsValidationError(f"Unsupported report format {fmt!r}")

        # Gather upstream products
        products: list[dict[str, object]] = []
        art = inputs.get("manifest") or inputs.get("data")
        if art is not None and hasattr(ctx.artifact_store, "load"):
            try:
                loaded = ctx.artifact_store.load(getattr(art, "artifact_id", ""))
                if isinstance(loaded, ProductManifest):
                    for p in loaded.products:
                        products.append(
                            {
                                "name": p.name,
                                "type": p.type,
                                "uri": p.uri,
                                "tags": p.tags,
                            }
                        )
            except Exception:
                pass
        if not products and isinstance(inputs.get("data"), dict):
            products.append(
                {"name": "data", "type": "json", "uri": "", "payload": inputs["data"]}
            )

        title = "CGDA Analysis Report"
        lines = [f"# {title}", "", f"Generated products: {len(products)}", ""]
        for p in products:
            lines.append(f"- **{p.get('name')}** (`{p.get('type')}`): `{p.get('uri')}`")
            if include_charts and str(p.get("type") or "").endswith("chart_spec"):
                lines.append("  - chart included")
        body_md = "\n".join(lines)

        out_dir = _out(ctx, "report")
        if fmt in {"markdown", "md"}:
            out_path = out_dir / "report.md"
            out_path.write_text(body_md, encoding="utf-8")
        else:
            out_path = out_dir / "report.html"
            html = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                f"<title>{title}</title></head><body>"
                f"<h1>{title}</h1><ul>"
                + "".join(
                    f"<li><b>{p.get('name')}</b> ({p.get('type')}): "
                    f"<code>{p.get('uri')}</code></li>"
                    for p in products
                )
                + "</ul></body></html>"
            )
            out_path.write_text(html, encoding="utf-8")

        filepath = str(out_path)
        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=[
                ProductRef(
                    name="report",
                    type="report",
                    uri=filepath,
                    tags={"module": self.name, "format": fmt},
                )
            ],
            extra={"module_name": self.name, "filepath": filepath, "format": fmt},
        )
        artifact = ArtifactRef(
            artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
            artifact_type="product_manifest",
            format="python_object",
            uri=None,
            producer_node_id=ctx.node_id,
            schema_name="ProductManifest",
            metadata={"module_name": self.name},
        )
        ctx.artifact_store.put(artifact, payload=manifest)
        return {"manifest": artifact, "filepath": filepath, "path": filepath}
