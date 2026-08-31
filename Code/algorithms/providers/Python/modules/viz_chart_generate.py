"""Chart generate module — normalize upstream chart/table JSON into ChartSpec.

Reads chart_spec / table_spec / statistics products from an upstream manifest
(or a direct chart JSON path) and re-emits a canonical ChartSpec product.
Optional matplotlib PNG is written as a file product (not the primary path).
"""

from __future__ import annotations

from viz_lock import locked_plot

import json
from pathlib import Path
from typing import Any

from contracts.product import ProductManifest, ProductRef
from modules.base import BaseModule
from modules.registry import register_module_decorator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec


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


def _load_upstream_manifest(
    inputs: dict[str, object], ctx: NodeExecutionContext
) -> ProductManifest | None:
    manifest_artifact = inputs.get("manifest")
    if manifest_artifact is None:
        return None
    try:
        loaded = ctx.artifact_store.load(getattr(manifest_artifact, "artifact_id", ""))
        if isinstance(loaded, ProductManifest):
            return loaded
    except Exception:
        return None
    return None


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_chart(
    raw: dict[str, Any],
    *,
    chart_type: str,
    title: str,
    x_label: str,
    y_label: str,
) -> dict[str, Any]:
    series = raw.get("series")
    if not isinstance(series, list) or not series:
        x = list(raw.get("x") or [])
        y = list(raw.get("y") or [])
        series = [
            {
                "name": str(raw.get("series_name") or "series"),
                "x": x,
                "y": y,
            }
        ]
    out_type = str(raw.get("chart_type") or chart_type or "line")
    return {
        "schema_version": "1",
        "chart_type": out_type,
        "title": title or str(raw.get("title") or "Chart"),
        "x_label": x_label or str(raw.get("x_label") or ""),
        "y_label": y_label or str(raw.get("y_label") or ""),
        "unit": str(raw.get("unit") or ""),
        "series": series,
        "x": list(series[0].get("x") or []) if series else [],
        "y": list(series[0].get("y") or []) if series else [],
        "series_name": series[0].get("name") if series else "series",
        "bins": raw.get("bins"),
        "categories": raw.get("categories"),
    }


@locked_plot
def _maybe_write_png(
    chart: dict[str, Any],
    out_path: Path,
    *,
    width: int,
    height: int,
) -> Path | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None

    fig_w = max(width, 200) / 100.0
    fig_h = max(height, 200) / 100.0
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    try:
        ctype = str(chart.get("chart_type") or "line")
        for s in chart.get("series") or []:
            x = s.get("x") or []
            y = s.get("y") or []
            name = str(s.get("name") or "series")
            if ctype in {"bar", "histogram"}:
                ax.bar(x, y, label=name, width=0.8)
            elif ctype == "scatter":
                ax.scatter(x, y, label=name, s=12)
            else:
                ax.plot(x, y, label=name)
        ax.set_title(str(chart.get("title") or "Chart"))
        ax.set_xlabel(str(chart.get("x_label") or ""))
        ax.set_ylabel(str(chart.get("y_label") or ""))
        ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(out_path, dpi=100)
    finally:
        # E-3：close 放 finally——任何路径（含异常）figure 不泄漏
        plt.close(fig)
    return out_path


@register_module_decorator(name="viz_chart_generate", aliases=["chart_generate"])
class VizChartGenerateModule(BaseModule):
    name = "viz_chart_generate"
    description = "Normalize upstream analysis JSON into ChartSpec (+ optional PNG)."
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
        merged = {**algorithm_params, **dict(params or {})}
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        chart_type = str(merged.get("chart_type") or "line")
        title = str(merged.get("title") or "Chart")
        # Celery metadata: keep ASCII in emitted WorkflowResultReference titles
        x_label = str(merged.get("x_label") or "")
        y_label = str(merged.get("y_label") or "")
        width = int(merged.get("width") or 800)
        height = int(merged.get("height") or 600)
        write_png = bool(merged.get("write_png", True))

        output_dir = Path(
            output_spec_extra.get("output_dir", ctx.workspace / "products" / "charts")
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        raw: dict[str, Any] | None = None
        upstream = _load_upstream_manifest(inputs, ctx)
        if upstream is not None:
            for product in upstream.products:
                if product.type == "chart_spec" or str(product.uri).endswith(
                    ".chart.json"
                ):
                    raw = _read_json(Path(product.uri))
                    break
            if raw is None:
                # Build a simple bar/line from statistics_result or table_spec
                for product in upstream.products:
                    if product.type == "table_spec" or str(product.uri).endswith(
                        ".table.json"
                    ):
                        table = _read_json(Path(product.uri))
                        cols = table.get("columns") or []
                        rows = table.get("rows") or []
                        if len(cols) >= 2 and rows:
                            # Prefer center/count or zone_id/mean style
                            x_idx, y_idx = 0, 1
                            for i, c in enumerate(cols):
                                cl = str(c).lower()
                                if cl in {"center", "zone_id", "time_index", "lc_id"}:
                                    x_idx = i
                                if cl in {"count", "mean", "value"}:
                                    y_idx = i
                            raw = {
                                "chart_type": chart_type
                                if chart_type != "line"
                                else "bar",
                                "title": title,
                                "x": [
                                    r[x_idx] for r in rows if len(r) > max(x_idx, y_idx)
                                ],
                                "y": [
                                    r[y_idx] for r in rows if len(r) > max(x_idx, y_idx)
                                ],
                                "series_name": str(cols[y_idx]),
                            }
                        break

        if raw is None:
            ds = dict(inputs.get("datasource_selection", {}))
            chart_path = ds.get("chart_path") or ds.get("input_path")
            if chart_path:
                p = Path(str(chart_path))
                if p.is_file():
                    raw = _read_json(p)

        if raw is None:
            raise ValueError(
                "viz_chart_generate: need upstream chart_spec/table_spec or "
                "datasource_selection.chart_path"
            )

        chart = _normalize_chart(
            raw,
            chart_type=chart_type,
            title=title,
            x_label=x_label,
            y_label=y_label,
        )
        out_chart = output_dir / "chart.chart.json"
        out_chart.write_text(json.dumps(chart, ensure_ascii=True), encoding="utf-8")

        products = [
            ProductRef(
                name="chart_spec",
                type="chart_spec",
                uri=str(out_chart),
                tags={"kind": "chart", "chart_type": str(chart["chart_type"])},
            )
        ]
        # Pass through upstream table_spec so multi-node pipelines keep tables
        if upstream is not None:
            for product in upstream.products:
                if product.type == "table_spec" or str(product.uri).endswith(
                    ".table.json"
                ):
                    merged_tags = {
                        str(k): str(v) for k, v in dict(product.tags or {}).items()
                    }
                    merged_tags["kind"] = "table"
                    products.append(
                        ProductRef(
                            name=product.name or "table_spec",
                            type="table_spec",
                            uri=str(product.uri),
                            variable=product.variable,
                            tags=merged_tags,
                        )
                    )
        if write_png:
            png_path = output_dir / "chart.png"
            written = _maybe_write_png(chart, png_path, width=width, height=height)
            if written is not None:
                products.append(
                    ProductRef(
                        name="chart_png",
                        type="file",
                        uri=str(written),
                        tags={"kind": "file", "mime": "image/png"},
                    )
                )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_artifact(
                "viz_chart_generate", str(out_chart), "chart"
            )

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=products,
            main_layers=["chart"],
            extra={
                "module_name": self.name,
                "output_dir": str(output_dir),
                "chart_type": chart["chart_type"],
            },
        )
        return _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={"chart_type": chart["chart_type"]},
        )
