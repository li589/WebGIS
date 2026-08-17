"""Raster histogram module — generic numeric raster → ChartSpec + TableSpec.

Registered as ``stats_histogram`` so workflow templates with
``node_class=stats_histogram`` resolve via the Python provider bridge.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from contracts.product import ProductManifest, ProductRef
from data_access.universal_reader import UniversalDataReader
from modules.base import BaseModule
from modules.registry import register_module_decorator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec


def _json_safe(value):
    """递归将非有限 float（NaN/±inf）转为 None（数值专项 W1）。

    全 NaN 栅格的直方图统计量是 NaN，``json.dumps`` 默认 ``allow_nan=True``
    会写出非法 JSON 的 ``NaN`` 字面量，前端 ``JSON.parse`` 抛错。
    """
    import math
    from collections.abc import Mapping

    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    return value


def _store_manifest(
    ctx: NodeExecutionContext,
    *,
    module_name: str,
    manifest: ProductManifest,
    metadata: dict[str, object],
) -> dict[str, object]:
    artifact = ArtifactRef(
        artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
        artifact_type="product_manifest",
        format="python_object",
        uri=None,
        producer_node_id=ctx.node_id,
        schema_name="ProductManifest",
        metadata={"module_name": module_name, **metadata},
    )
    ctx.artifact_store.put(artifact, payload=manifest)
    return {"manifest": artifact}


def _load_array(
    inputs: dict[str, object],
    ctx: NodeExecutionContext,
    variable: str | None,
    band: int,
) -> tuple[np.ndarray, str]:
    datasource_selection = dict(inputs.get("datasource_selection", {}))
    input_path = datasource_selection.get("input_path")
    if input_path is None:
        manifest_artifact = inputs.get("manifest")
        if manifest_artifact is not None:
            try:
                loaded = ctx.artifact_store.load(
                    getattr(manifest_artifact, "artifact_id", "")
                )
                if isinstance(loaded, ProductManifest) and loaded.products:
                    input_path = loaded.products[0].uri
                    if variable is None:
                        variable = loaded.products[0].variable
                        if variable:
                            variable = str(variable).split(",")[0]
            except Exception:
                pass
    if input_path is None:
        raise ValueError(
            "stats_histogram: need datasource_selection.input_path or upstream manifest"
        )

    reader = UniversalDataReader(Path(str(input_path)))
    available = reader.list_variables()
    coord_keys = {"lat", "lon", "latitude", "longitude", "time", "count_grid", "x", "y"}
    if variable is None:
        for v in available:
            if v.lower() not in coord_keys:
                variable = v
                break
    if variable is None or variable not in available:
        # GeoTIFF / single-band: first variable
        if available:
            variable = available[min(max(band, 0), len(available) - 1)]
        else:
            raise ValueError(f"stats_histogram: no variables in {input_path}")

    values = reader.read_variable(variable=variable).values
    return np.asarray(values, dtype=np.float64), str(variable)


@register_module_decorator(
    name="stats_histogram", aliases=["histogram", "raster_histogram"]
)
class StatsHistogramModule(BaseModule):
    name = "stats_histogram"
    description = "Compute a generic float64 histogram for any numeric raster."
    input_ports = [
        PortSpec(
            name="manifest",
            kind="artifact",
            data_class="product_manifest",
            required=False,
        ),
        PortSpec(
            name="datasource_selection",
            kind="config",
            data_class="dict",
            required=False,
        ),
        PortSpec(
            name="algorithm_params", kind="config", data_class="dict", required=False
        ),
        PortSpec(
            name="output_spec_extra", kind="config", data_class="dict", required=False
        ),
    ]
    output_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest")
    ]

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        # Template params may also land in top-level params / properties
        merged = {**algorithm_params, **dict(params or {})}
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        bins = int(merged.get("bins", 50) or 50)
        band = int(merged.get("band", 0) or 0)
        density = bool(merged.get("density", False))
        nodata_raw = merged.get("nodata")
        nodata = (
            float(nodata_raw) if nodata_raw is not None and nodata_raw != "" else None
        )
        variable = merged.get("variable")
        if isinstance(variable, str) and not variable.strip():
            variable = None
        vmin = merged.get("min")
        vmax = merged.get("max")
        value_range = None
        if vmin is not None and vmax is not None and vmin != "" and vmax != "":
            value_range = (float(vmin), float(vmax))

        output_dir = Path(
            output_spec_extra.get(
                "output_dir", ctx.workspace / "products" / "histogram"
            )
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start("stats_histogram", f"bins={bins}")

        values, var_name = _load_array(
            inputs, ctx, variable if isinstance(variable, str) else None, band
        )
        # Multi-band: pick band index along first axis when 3D and band set
        if values.ndim == 3 and 0 <= band < values.shape[0]:
            values = values[band]

        # Ensure provider root is importable inside Celery worker children
        import sys

        _provider_root = str(Path(__file__).resolve().parents[1])
        if _provider_root not in sys.path:
            sys.path.insert(0, _provider_root)
        from analysis.histogram import compute_histogram, histogram_to_chart_spec

        hist = compute_histogram(
            values,
            bins=bins,
            value_range=value_range,
            nodata=nodata,
            density=density,
        )
        chart = histogram_to_chart_spec(
            hist,
            title=f"Histogram ({var_name})",
            series_name="density" if density else "count",
            use_density=density,
        )
        table = {
            "schema_version": "1",
            "title": f"Histogram bins ({var_name})",
            "columns": ["bin_left", "bin_right", "center", "count"],
            "rows": [
                [
                    hist["edges"][i],
                    hist["edges"][i + 1],
                    hist["centers"][i],
                    hist["counts"][i],
                ]
                for i in range(len(hist["counts"]))
            ],
            "units": {},
            "dtypes": {
                "bin_left": "float64",
                "bin_right": "float64",
                "center": "float64",
                "count": "float64",
            },
        }

        chart_path = output_dir / f"histogram_{var_name}.chart.json"
        table_path = output_dir / f"histogram_{var_name}.table.json"
        stats_path = output_dir / f"histogram_{var_name}.stats.json"
        chart_path.write_text(
            json.dumps(_json_safe(chart), ensure_ascii=True, allow_nan=False),
            encoding="utf-8",
        )
        table_path.write_text(
            json.dumps(_json_safe(table), ensure_ascii=True, allow_nan=False),
            encoding="utf-8",
        )
        stats_path.write_text(
            json.dumps(
                _json_safe({"variable": var_name, **hist["stats"]}),
                ensure_ascii=True,
                allow_nan=False,
            ),
            encoding="utf-8",
        )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_artifact(
                "stats_histogram", str(chart_path), "chart"
            )
            ctx.logger_adapter.emit_stage_end(
                "stats_histogram",
                f"variable={var_name}, count={hist['stats']['count']}",
            )

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=[
                ProductRef(
                    name=f"histogram_chart_{var_name}",
                    type="chart_spec",
                    uri=str(chart_path),
                    variable=var_name,
                    tags={"kind": "chart", "chart_type": "histogram"},
                ),
                ProductRef(
                    name=f"histogram_table_{var_name}",
                    type="table_spec",
                    uri=str(table_path),
                    variable=var_name,
                    tags={"kind": "table"},
                ),
                ProductRef(
                    name=f"histogram_stats_{var_name}",
                    type="statistics_result",
                    uri=str(stats_path),
                    variable=var_name,
                    tags={"kind": "stats"},
                ),
            ],
            main_layers=[var_name],
            tables=[str(table_path)],
            extra={
                "module_name": self.name,
                "output_dir": str(output_dir),
                "variable": var_name,
                "result_summary": hist["stats"],
            },
        )
        return _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={"variable": var_name, "bins": bins},
        )
