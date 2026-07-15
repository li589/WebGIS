"""统计分析模块 — 计算均值/中位数/标准差/分区统计。

支持输入:
  - manifest (上游模块产物)
  - datasource_selection (独立文件路径: input_path)

支持模式 (algorithm_params["mode"]):
  - global:     全局统计 (复用 ZonalStats.compute_stats)
  - zonal:      分区均值 (复用 ZonalStats.compute_zonal_mean，需 zones_source)
  - landcover:  按土地覆盖分区统计 (复用 ZonalStats.compute_landcover_stats，需 zones_source)
  - timeseries: 3D 数据逐时间片均值

可选参数:
  - variable:     待统计变量名 (默认取第一个非坐标变量)
  - zones_source: 分区数据文件路径 (zonal/landcover 模式必需)
  - output_dir:   输出目录 (默认 ctx.workspace / "products" / "statistics")
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from contracts.product import ProductManifest, ProductRef
from data_access.universal_reader import UniversalDataReader
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


def _load_input_array(
    inputs: dict[str, object],
    ctx: NodeExecutionContext,
    variable: str | None,
) -> tuple[np.ndarray, str, UniversalDataReader | None]:
    """从 manifest 或 datasource_selection 加载数据数组。返回 (values, var_name, reader)。"""
    datasource_selection = dict(inputs.get("datasource_selection", {}))
    input_path = datasource_selection.get("input_path")

    if input_path is None:
        manifest_artifact = inputs.get("manifest")
        if manifest_artifact is not None:
            try:
                loaded = ctx.artifact_store.load(getattr(manifest_artifact, "artifact_id", ""))
                if isinstance(loaded, ProductManifest) and loaded.products:
                    input_path = loaded.products[0].uri
                    if variable is None:
                        variable = loaded.products[0].variable.split(",")[0]
            except Exception:
                pass

    if input_path is None:
        raise ValueError("statistics: 需要提供 datasource_selection.input_path 或 manifest")

    reader = UniversalDataReader(Path(str(input_path)))
    available_vars = reader.list_variables()

    coord_keys = {"lat", "lon", "latitude", "longitude", "time", "count_grid"}
    if variable is None:
        for v in available_vars:
            if v.lower() not in coord_keys:
                variable = v
                break
    if variable is None or variable not in available_vars:
        raise ValueError(f"statistics: 无法确定统计变量 (available: {available_vars})")

    da = reader.read_variable(variable=variable)
    return da.values, variable, reader


def _load_zones(zones_source: str) -> np.ndarray:
    """加载分区数据数组。"""
    reader = UniversalDataReader(Path(zones_source))
    available = reader.list_variables()
    # 优先尝试常见分区变量名
    for candidate in ("landcover", "lc", "zone", "zones", "igbp"):
        if candidate in available:
            return reader.read_variable(variable=candidate).values
    # 降级: 取第一个变量
    if available:
        return reader.read_variable(variable=available[0]).values
    raise ValueError(f"statistics: 无法从 {zones_source} 加载分区数据")


@register_module_decorator(name="statistics", aliases=["statistics_pipeline"])
class StatisticsModule(BaseModule):
    name = "statistics"
    description = "Compute mean / median / std / zonal statistics on raster data."
    input_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest", required=False),
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
    ]
    output_ports = [PortSpec(name="manifest", kind="artifact", data_class="product_manifest")]

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        from scipy.io import savemat

        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        mode = str(algorithm_params.get("mode", "global")).lower()
        variable = algorithm_params.get("variable")
        if isinstance(variable, str) and not variable.strip():
            variable = None
        zones_source = algorithm_params.get("zones_source")

        output_dir = Path(output_spec_extra.get("output_dir", ctx.workspace / "products" / "statistics"))
        output_dir.mkdir(parents=True, exist_ok=True)

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start("statistics", f"Mode={mode}")

        values, var_name, _ = _load_input_array(inputs, ctx, variable if isinstance(variable, str) else None)

        from analysis.spatial_stats import ZonalStats
        zs = ZonalStats()

        result: dict[str, object] = {"mode": mode, "variable": var_name}

        if mode == "global":
            stats = zs.compute_stats(values)
            result["global"] = stats["global"]
            result["raw_stats"] = stats
        elif mode == "zonal":
            if not zones_source:
                raise ValueError("statistics: zonal 模式需要 algorithm_params.zones_source")
            zones = _load_zones(str(zones_source))
            if zones.shape != values.shape:
                # 尝试裁剪到相同形状
                min_shape = tuple(min(a, b) for a, b in zip(values.shape, zones.shape))
                values = values[tuple(slice(0, s) for s in min_shape)]
                zones = zones[tuple(slice(0, s) for s in min_shape)]
            zonal_mean = zs.compute_zonal_mean(values, zones)
            result["zonal_mean"] = {int(k): float(v) for k, v in zonal_mean.items()}
        elif mode == "landcover":
            if not zones_source:
                raise ValueError("statistics: landcover 模式需要 algorithm_params.zones_source")
            zones = _load_zones(str(zones_source))
            if zones.shape != values.shape:
                min_shape = tuple(min(a, b) for a, b in zip(values.shape, zones.shape))
                values = values[tuple(slice(0, s) for s in min_shape)]
                zones = zones[tuple(slice(0, s) for s in min_shape)]
            lc_stats = zs.compute_landcover_stats(values, zones)
            result["landcover_stats"] = {
                int(k): {kk: (float(vv) if isinstance(vv, (int, float, np.floating)) else vv)
                          for kk, vv in v.items()}
                for k, v in lc_stats.items()
            }
        elif mode == "timeseries":
            if values.ndim != 3:
                raise ValueError(f"statistics: timeseries 模式需要 3D 数据 (time, lat, lon)，实际 ndim={values.ndim}")
            n_time = values.shape[0]
            per_time_stats = []
            for t in range(n_time):
                slice_data = values[t]
                s = zs.compute_stats(slice_data)["global"]
                per_time_stats.append({
                    "time_index": t,
                    "mean": s["mean"],
                    "std": s["std"],
                    "min": s["min"],
                    "max": s["max"],
                    "median": s["median"],
                })
            result["timeseries"] = per_time_stats
            # 提取均值序列便于绘图
            result["mean_series"] = [s["mean"] for s in per_time_stats]
        else:
            raise ValueError(f"不支持的统计模式: {mode} (可选 global|zonal|landcover|timeseries)")

        # 输出 MAT + CSV
        out_name = f"stats_{mode}_{var_name}"
        mat_path = output_dir / f"{out_name}.mat"
        csv_path = output_dir / f"{out_name}.csv"

        # MAT: 结果字典 (numpy 不支持嵌套 dict，转简单结构)
        mat_payload: dict[str, object] = {"mode": mode, "variable": var_name}
        if mode == "global":
            for k, v in result["global"].items():  # type: ignore[union-attr]
                mat_payload[k] = v
        elif mode == "zonal":
            zone_ids = list(result["zonal_mean"].keys())  # type: ignore[union-attr]
            zone_vals = list(result["zonal_mean"].values())  # type: ignore[union-attr]
            mat_payload["zone_ids"] = np.array(zone_ids)
            mat_payload["zone_means"] = np.array(zone_vals)
        elif mode == "landcover":
            lc_ids = list(result["landcover_stats"].keys())  # type: ignore[union-attr]
            lc_means = [result["landcover_stats"][k]["mean"] for k in lc_ids]  # type: ignore[index]
            mat_payload["lc_ids"] = np.array(lc_ids)
            mat_payload["lc_means"] = np.array(lc_means)
        elif mode == "timeseries":
            mat_payload["mean_series"] = np.array(result["mean_series"])  # type: ignore[arg-type]
            mat_payload["std_series"] = np.array([s["std"] for s in result["timeseries"]])  # type: ignore[index]

        savemat(mat_path, mat_payload, do_compression=True)

        # CSV
        import csv
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if mode == "global":
                writer.writerow(["metric", "value"])
                for k, v in result["global"].items():  # type: ignore[union-attr]
                    writer.writerow([k, v])
            elif mode == "zonal":
                writer.writerow(["zone_id", "mean"])
                for k, v in result["zonal_mean"].items():  # type: ignore[union-attr]
                    writer.writerow([k, v])
            elif mode == "landcover":
                writer.writerow(["lc_id", "name", "mean", "std", "count", "area_pct"])
                for k, v in result["landcover_stats"].items():  # type: ignore[union-attr]
                    writer.writerow([k, v.get("name", ""), v.get("mean", ""), v.get("std", ""), v.get("count", ""), v.get("area_pct", "")])
            elif mode == "timeseries":
                writer.writerow(["time_index", "mean", "std", "min", "max", "median"])
                for s in result["timeseries"]:  # type: ignore[union-attr]
                    writer.writerow([s["time_index"], s["mean"], s["std"], s["min"], s["max"], s["median"]])

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_artifact("statistics", str(mat_path), "stats_mat")
            ctx.logger_adapter.emit_artifact("statistics", str(csv_path), "stats_csv")
            ctx.logger_adapter.emit_stage_end("statistics", f"Mode={mode}, variable={var_name}")

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=[
                ProductRef(
                    name=out_name,
                    type="statistics_result",
                    uri=str(mat_path),
                    variable=",".join(mat_payload.keys()),
                    tags={"mode": mode, "variable": var_name},
                ),
            ],
            main_layers=list(mat_payload.keys()),
            metadata_uri=None,
            extra={
                "module_name": self.name,
                "output_dir": str(output_dir),
                "mode": mode,
                "variable": var_name,
                "result_summary": {k: v for k, v in result.items() if k != "raw_stats"},
            },
        )
        return _store_manifest(ctx, module_name=self.name, manifest=manifest, metadata={
            "mode": mode,
            "variable": var_name,
        })
