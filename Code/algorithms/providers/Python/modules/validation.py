"""验证指标模块 — 计算 predicted vs observed 的 r/p/rmse/bias/ubrmse + KDE 密度。

对应 Matlab Function/metrics.m + Function/scatter_kde.m。

支持输入:
  - datasource_selection.predicted_path + datasource_selection.observed_path (独立文件)
  - manifest (上游模块产物, 作为 predicted) + datasource_selection.observed_path

可选参数 (algorithm_params):
  - predicted_variable:  predicted 文件中的变量名 (默认取第一个非坐标变量;
                         若 predicted 来自 manifest, 则用 manifest.products[0].variable)
  - observed_variable:   observed 文件中的变量名 (默认取第一个非坐标变量)
  - output_dir:          输出目录 (默认 ctx.workspace / "products" / "validation")

产出:
  - validation_metrics.json: r/p/rmse/bias/ubrmse + 样本数
  - validation_kde.mat:      kde_density / predicted / observed 数组 (前端散点着色)
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


# 坐标变量名集合（加载时跳过，选取数据变量）
_COORD_VAR_KEYS = {"lat", "lon", "latitude", "longitude", "time", "count_grid"}


def _load_array_from_path(
    path: str,
    variable: str | None,
    *,
    role: str,
) -> tuple[np.ndarray, str]:
    """从文件路径加载数组。返回 (values, variable_name)。

    量纲: 输出 values 保持原文件量纲；variable_name 为实际加载的变量名。
    """
    reader = UniversalDataReader(Path(path))
    available_vars = reader.list_variables()
    if variable is not None and variable not in available_vars:
        raise ValueError(
            f"validation: {role} 变量 '{variable}' 不在 {path} "
            f"(available: {available_vars})"
        )
    if variable is None:
        for v in available_vars:
            if v.lower() not in _COORD_VAR_KEYS:
                variable = v
                break
    if variable is None:
        raise ValueError(
            f"validation: 无法确定 {role} 变量 (available: {available_vars})"
        )
    da = reader.read_variable(variable=variable)
    return da.values, variable


def _resolve_predicted_path(
    inputs: dict[str, object],
    ctx: NodeExecutionContext,
) -> tuple[str | None, str | None]:
    """从 datasource_selection.predicted_path 或 manifest 解析 predicted 路径。

    返回 (path, variable_hint)。variable_hint 来自 manifest.products[0].variable
    （逗号分隔时取第一段），供后续 _load_array_from_path 使用。
    """
    datasource_selection = dict(inputs.get("datasource_selection", {}))
    predicted_path = datasource_selection.get("predicted_path")
    variable_hint: str | None = None
    if predicted_path is None:
        manifest_artifact = inputs.get("manifest")
        if manifest_artifact is not None:
            try:
                loaded = ctx.artifact_store.load(
                    getattr(manifest_artifact, "artifact_id", "")
                )
                if isinstance(loaded, ProductManifest) and loaded.products:
                    predicted_path = loaded.products[0].uri
                    variable_hint = loaded.products[0].variable.split(",")[0]
            except Exception:
                pass
    if predicted_path is None:
        return None, None
    return str(predicted_path), variable_hint


@register_module_decorator(
    name="validation_metrics", aliases=["validation_metrics_pipeline"]
)
class ValidationMetricsModule(BaseModule):
    name = "validation_metrics"
    description = (
        "Compute validation metrics (r/p/rmse/bias/ubrmse) + KDE density "
        "between predicted and observed arrays."
    )
    mode_required_inputs = {
        "validation_metrics": ("predicted_path", "observed_path"),
    }
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
        from scipy.io import savemat

        from algorithms.validation import (
            compute_validation_metrics,
            scatter_kde_density,
        )

        _ = params
        datasource_selection = dict(inputs.get("datasource_selection", {}))
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        observed_path = datasource_selection.get("observed_path")
        if not observed_path:
            raise ValueError("validation: 需要 datasource_selection.observed_path")
        predicted_path, var_hint = _resolve_predicted_path(inputs, ctx)
        if not predicted_path:
            raise ValueError(
                "validation: 需要 datasource_selection.predicted_path 或 manifest"
            )

        predicted_variable = algorithm_params.get("predicted_variable")
        if predicted_variable is None and var_hint:
            predicted_variable = var_hint
        observed_variable = algorithm_params.get("observed_variable")

        predicted_arr, pred_var = _load_array_from_path(
            str(predicted_path),
            predicted_variable if isinstance(predicted_variable, str) else None,
            role="predicted",
        )
        observed_arr, obs_var = _load_array_from_path(
            str(observed_path),
            observed_variable if isinstance(observed_variable, str) else None,
            role="observed",
        )

        # 展平并对齐长度
        x = np.asarray(predicted_arr, dtype=float).ravel()
        y = np.asarray(observed_arr, dtype=float).ravel()
        if x.size == 0 or y.size == 0:
            raise ValueError("validation: predicted/observed 至少一侧为空")
        n = min(x.size, y.size)
        if x.size != y.size:
            # 长度不一致时截断到较短长度（容错：避免形状轻微不匹配直接失败）
            x = x[:n]
            y = y[:n]

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "validation_metrics", f"N={n}, pred={pred_var}, obs={obs_var}"
            )

        metrics = compute_validation_metrics(x, y)
        kde_density = scatter_kde_density(x, y)

        output_dir = Path(
            output_spec_extra.get(
                "output_dir", ctx.workspace / "products" / "validation"
            )
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        # metrics.json（NaN/Inf 由 json 默认写出为 NaN/Infinity，前端需容错解析）
        metrics_path = output_dir / "validation_metrics.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "predicted_variable": pred_var,
                    "observed_variable": obs_var,
                    "sample_count": int(n),
                    "metrics": metrics,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
            f.write("\n")

        # kde_density.mat（predicted/observed 一并落盘便于前端散点图）
        kde_path = output_dir / "validation_kde.mat"
        savemat(
            kde_path,
            {
                "kde_density": kde_density,
                "predicted": x,
                "observed": y,
            },
            do_compression=True,
        )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_artifact(
                "validation_metrics", str(metrics_path), "metrics_json"
            )
            ctx.logger_adapter.emit_artifact(
                "validation_metrics", str(kde_path), "kde_mat"
            )
            ctx.logger_adapter.emit_stage_end(
                "validation_metrics",
                f"r={metrics['r']:.4f}, rmse={metrics['rmse']:.4f}",
            )

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=[
                ProductRef(
                    name="validation_metrics",
                    type="validation_metrics_json",
                    uri=str(metrics_path),
                    variable=pred_var,
                    tags={
                        "observed_variable": obs_var,
                        "sample_count": str(n),
                    },
                ),
                ProductRef(
                    name="validation_kde",
                    type="validation_kde_mat",
                    uri=str(kde_path),
                    variable="kde_density",
                    tags={"sample_count": str(n)},
                ),
            ],
            main_layers=["kde_density", "predicted", "observed"],
            metadata_uri=None,
            extra={
                "module_name": self.name,
                "output_dir": str(output_dir),
                "predicted_variable": pred_var,
                "observed_variable": obs_var,
                "sample_count": int(n),
                "metrics": metrics,
            },
        )
        return _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={
                "sample_count": int(n),
                "r": metrics["r"],
                "rmse": metrics["rmse"],
            },
        )
