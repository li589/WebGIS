"""Statistical analysis modules: spatial mean, trend, anomaly, correlation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from contracts.product import ProductManifest, ProductRef
from modules.base import BaseModule
from modules.registry import register_module_decorator
from modules._raster_ops import (
    RasterOpsValidationError,
    emit_progress,
    finite_mask,
    load_timeseries_payload,
    open_raster,
    resolve_raster_path,
    store_geojson_manifest,
)
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec


def _merged(inputs: dict[str, object], params: dict[str, object]) -> dict[str, object]:
    return {**(dict(inputs.get("algorithm_params", {}) or {})), **dict(params or {})}


def _out(ctx: NodeExecutionContext, name: str) -> Path:
    d = Path(ctx.workspace) / "products" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _store_value_manifest(
    ctx: NodeExecutionContext,
    *,
    module_name: str,
    value: float,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    out_dir = _out(ctx, module_name)
    stats_path = out_dir / "result.json"
    payload = {"value": value, "module_name": module_name, **(extra or {})}
    stats_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    manifest = ProductManifest(
        job_id=ctx.request.job_id,
        run_id=ctx.runtime_context.run_id,
        products=[
            ProductRef(
                name="statistics_result",
                type="statistics_result",
                uri=str(stats_path),
                tags={"module": module_name},
            )
        ],
        tables=[str(stats_path)],
        extra={"module_name": module_name, "value": value, **(extra or {})},
    )
    artifact = ArtifactRef(
        artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
        artifact_type="product_manifest",
        format="python_object",
        uri=None,
        producer_node_id=ctx.node_id,
        schema_name="ProductManifest",
        metadata={"module_name": module_name},
    )
    ctx.artifact_store.put(artifact, payload=manifest)
    return {"manifest": artifact, "value": value, "coefficient": value}


def _extract_series(payload: dict) -> tuple[np.ndarray, np.ndarray]:
    times = payload.get("times") or payload.get("time") or payload.get("x") or []
    values = payload.get("values") or payload.get("y") or []
    y = np.asarray(values, dtype=np.float64).reshape(-1)
    if len(times) == 0:
        x = np.arange(y.size, dtype=np.float64)
    else:
        # ordinal days if ISO strings
        x_list = []
        for t in times:
            if isinstance(t, (int, float)):
                x_list.append(float(t))
            else:
                try:
                    from datetime import datetime

                    dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
                    x_list.append(dt.toordinal())
                except Exception:
                    x_list.append(float(len(x_list)))
        x = np.asarray(x_list, dtype=np.float64)
        n = min(x.size, y.size)
        x, y = x[:n], y[:n]
    mask = finite_mask(y) & finite_mask(x)
    if mask.sum() < 2:
        raise RasterOpsValidationError("Timeseries needs at least 2 finite samples")
    return x[mask], y[mask]


@register_module_decorator(name="stats_spatial_mean", aliases=["spatial_mean"])
class StatsSpatialMeanModule(BaseModule):
    name = "stats_spatial_mean"
    description = "Spatial statistic over a raster band (float64, nodata-aware)."
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
        PortSpec(name="value", kind="value", data_class="number"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"statistic": "mean", "band": 0}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        import rasterio

        from modules._raster_ops import (
            estimate_full_read_ok,
            reduce_raster_blocks,
        )

        merged = _merged(inputs, params)
        statistic = str(merged.get("statistic") or "mean").lower()
        band = int(merged.get("band") or 0)
        allowed = {"mean", "median", "min", "max", "std"}
        if statistic not in allowed:
            raise RasterOpsValidationError(
                f"statistic must be one of {sorted(allowed)}"
            )
        path = resolve_raster_path(inputs, ctx, params=merged)

        with rasterio.open(path) as ds:
            full_ok = estimate_full_read_ok(ds.height, ds.width, bands=1)

        if not full_ok:
            if statistic == "median":
                raise RasterOpsValidationError(
                    "Raster exceeds memory budget for median; clip or resample first"
                )
            value, count = reduce_raster_blocks(path, statistic=statistic, band=band)
            emit_progress(ctx, self.name, f"{statistic}={value} (windowed)", 100)
            return _store_value_manifest(
                ctx,
                module_name=self.name,
                value=value,
                extra={
                    "statistic": statistic,
                    "count": count,
                    "windowed": True,
                },
            )

        bundle = open_raster(path, band=band)
        vals = bundle.band(0)
        vals = vals[finite_mask(vals)]
        if vals.size == 0:
            raise RasterOpsValidationError("No finite pixels for spatial statistic")
        if statistic == "mean":
            value = float(np.mean(vals))
        elif statistic == "median":
            value = float(np.median(vals))
        elif statistic == "min":
            value = float(np.min(vals))
        elif statistic == "max":
            value = float(np.max(vals))
        else:
            value = float(np.std(vals))
        emit_progress(ctx, self.name, f"{statistic}={value}", 100)
        return _store_value_manifest(
            ctx,
            module_name=self.name,
            value=value,
            extra={"statistic": statistic, "count": int(vals.size), "windowed": False},
        )


@register_module_decorator(name="stats_temporal_trend", aliases=["temporal_trend"])
class StatsTemporalTrendModule(BaseModule):
    name = "stats_temporal_trend"
    description = "Linear / Theil-Sen / Mann-Kendall trend on a timeseries."
    input_ports = [
        PortSpec(
            name="timeseries", kind="data", data_class="timeseries", required=False
        ),
    ]
    output_ports = [
        PortSpec(name="result", kind="data", data_class="geojson"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"trend_method": "linear", "confidence_level": 0.95}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        from scipy import stats as scipy_stats

        merged = _merged(inputs, params)
        method = str(merged.get("trend_method") or "linear").lower()
        conf = float(merged.get("confidence_level") or 0.95)
        payload = load_timeseries_payload(inputs, ctx)
        x, y = _extract_series(payload)

        props: dict[str, object] = {
            "method": method,
            "confidence_level": conf,
            "n": int(x.size),
        }
        if method == "linear":
            slope, intercept, r, p, se = scipy_stats.linregress(x, y)
            props.update(
                {
                    "slope": float(slope),
                    "intercept": float(intercept),
                    "r_value": float(r),
                    "p_value": float(p),
                    "stderr": float(se),
                }
            )
        elif method == "theil_sen":
            slope, intercept, low, high = scipy_stats.theilslopes(y, x, alpha=1 - conf)
            props.update(
                {
                    "slope": float(slope),
                    "intercept": float(intercept),
                    "slope_low": float(low),
                    "slope_high": float(high),
                }
            )
        elif method == "mann_kendall":
            # SciPy 1.11+ has mannwhitney; implement classic MK
            n = y.size
            s = 0
            for i in range(n - 1):
                s += int(np.sum(np.sign(y[i + 1 :] - y[i])))
            unique, counts = np.unique(y, return_counts=True)
            tie_term = np.sum(counts * (counts - 1) * (2 * counts + 5))
            var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
            if s > 0:
                z = (s - 1) / np.sqrt(var_s) if var_s > 0 else 0.0
            elif s < 0:
                z = (s + 1) / np.sqrt(var_s) if var_s > 0 else 0.0
            else:
                z = 0.0
            p = float(2 * (1 - scipy_stats.norm.cdf(abs(z))))
            props.update(
                {
                    "s": int(s),
                    "z": float(z),
                    "p_value": p,
                    "trend": "up" if s > 0 else ("down" if s < 0 else "none"),
                }
            )
        else:
            raise RasterOpsValidationError(f"Unknown trend_method {method!r}")

        # Point geometry at origin as placeholder GeoJSON carrier
        lon = float(payload.get("lon") or payload.get("longitude") or 0)
        lat = float(payload.get("lat") or payload.get("latitude") or 0)
        gj = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": props,
                }
            ],
        }
        out_path = _out(ctx, "trend") / "trend.geojson"
        return store_geojson_manifest(
            ctx,
            module_name=self.name,
            geojson=gj,
            output_path=out_path,
            port_name="result",
            extra=props,
        )


@register_module_decorator(name="stats_anomaly_detect", aliases=["anomaly_detect"])
class StatsAnomalyDetectModule(BaseModule):
    name = "stats_anomaly_detect"
    description = "Detect anomalies in a timeseries (zscore / IQR / DBSCAN)."
    input_ports = [
        PortSpec(
            name="timeseries", kind="data", data_class="timeseries", required=False
        ),
    ]
    output_ports = [
        PortSpec(name="anomalies", kind="data", data_class="geojson"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"method": "zscore", "threshold": 2.0}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        merged = _merged(inputs, params)
        method = str(merged.get("method") or "zscore").lower()
        threshold = float(merged.get("threshold") or 2.0)
        payload = load_timeseries_payload(inputs, ctx)
        x, y = _extract_series(payload)
        times = payload.get("times") or list(range(len(y)))

        flags = np.zeros(y.size, dtype=bool)
        if method == "zscore":
            mu = float(np.mean(y))
            sigma = float(np.std(y))
            if sigma < 1e-15:
                raise RasterOpsValidationError(
                    "Z-score undefined for zero-variance series"
                )
            z = np.abs((y - mu) / sigma)
            flags = z > threshold
        elif method == "iqr":
            q1, q3 = np.percentile(y, [25, 75])
            iqr = float(q3 - q1)
            lo, hi = q1 - threshold * iqr, q3 + threshold * iqr
            flags = (y < lo) | (y > hi)
        elif method == "dbscan":
            try:
                from sklearn.cluster import DBSCAN
            except ImportError as exc:
                raise RasterOpsValidationError(
                    "dbscan requires scikit-learn; use zscore or iqr"
                ) from exc
            pts = np.column_stack([x, y])
            # scale
            pts = (pts - pts.mean(0)) / (pts.std(0) + 1e-9)
            labels = DBSCAN(eps=0.5, min_samples=3).fit_predict(pts)
            flags = labels == -1
        else:
            raise RasterOpsValidationError(f"Unknown method {method!r}")

        lon = float(payload.get("lon") or 0)
        lat = float(payload.get("lat") or 0)
        feats = []
        for i, is_anom in enumerate(flags):
            if not is_anom:
                continue
            t = times[i] if i < len(times) else i
            feats.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "index": int(i),
                        "time": t,
                        "value": float(y[i]),
                        "method": method,
                    },
                }
            )
        gj = {"type": "FeatureCollection", "features": feats}
        out_path = _out(ctx, "anomaly") / "anomalies.geojson"
        return store_geojson_manifest(
            ctx,
            module_name=self.name,
            geojson=gj,
            output_path=out_path,
            port_name="anomalies",
            extra={"anomaly_count": len(feats), "method": method},
        )


@register_module_decorator(name="stats_correlation", aliases=["correlation"])
class StatsCorrelationModule(BaseModule):
    name = "stats_correlation"
    description = "Pearson / Spearman / Kendall correlation with optional lag."
    input_ports = [
        PortSpec(name="x", kind="data", data_class="timeseries", required=False),
        PortSpec(name="y", kind="data", data_class="timeseries", required=False),
    ]
    output_ports = [
        PortSpec(name="coefficient", kind="value", data_class="number"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"method": "pearson", "lag_days": 0}

    def execute(self, inputs, params, ctx: NodeExecutionContext) -> dict[str, object]:
        from scipy import stats as scipy_stats

        merged = _merged(inputs, params)
        method = str(merged.get("method") or "pearson").lower()
        lag = int(merged.get("lag_days") or 0)
        x_payload = load_timeseries_payload(inputs, ctx, keys=("x", "timeseries"))
        # For y, prefer dedicated port
        y_inputs = dict(inputs)
        if inputs.get("y") is not None:
            y_inputs = {"timeseries": inputs["y"]}
        y_payload = load_timeseries_payload(
            y_inputs, ctx, keys=("timeseries", "y", "data")
        )
        _, xv = _extract_series(x_payload)
        _, yv = _extract_series(y_payload)
        n = min(xv.size, yv.size)
        xv, yv = xv[:n], yv[:n]
        if lag > 0:
            if lag >= n - 1:
                raise RasterOpsValidationError("lag_days too large for series length")
            xv = xv[: n - lag]
            yv = yv[lag:]
        elif lag < 0:
            lag_a = -lag
            if lag_a >= n - 1:
                raise RasterOpsValidationError("lag_days too large for series length")
            xv = xv[lag_a:]
            yv = yv[: n - lag_a]

        if method == "pearson":
            coef, p = scipy_stats.pearsonr(xv, yv)
        elif method == "spearman":
            coef, p = scipy_stats.spearmanr(xv, yv)
        elif method == "kendall":
            coef, p = scipy_stats.kendalltau(xv, yv)
        else:
            raise RasterOpsValidationError(f"Unknown method {method!r}")
        if not np.isfinite(coef):
            raise RasterOpsValidationError("Correlation coefficient is not finite")
        return _store_value_manifest(
            ctx,
            module_name=self.name,
            value=float(coef),
            extra={
                "method": method,
                "p_value": float(p),
                "lag_days": lag,
                "n": int(xv.size),
            },
        )
