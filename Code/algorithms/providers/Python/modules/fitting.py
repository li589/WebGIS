"""曲线拟合模块 — 对时间序列数据执行线性/多项式/指数拟合。

支持输入:
  - manifest (上游模块产物)
  - datasource_selection (独立文件路径: input_path)

支持方法 (algorithm_params["method"]):
  - linear:       线性回归 (复用 TrendAnalysis.linear_trend)
  - polynomial:   多项式拟合 (numpy.polyfit)
  - exponential:  指数拟合 y = a*exp(b*x) (scipy.optimize.curve_fit)

可选参数:
  - degree:   多项式阶数 (默认 2)
  - variable: 待拟合变量名 (默认取第一个非坐标变量)
  - output_dir: 输出目录 (默认 ctx.workspace / "products" / "fitting")
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import numpy as np
from numpy.exceptions import RankWarning

from contracts.product import ProductManifest, ProductRef
from data_access.universal_reader import UniversalDataReader
from modules.base import BaseModule
from modules.registry import register_module_decorator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec

logger = logging.getLogger(__name__)

# 数值专项 W2：高阶多项式在有限样本上条件数爆炸（Vandermonde 病态），
# 拟合曲线在端点大幅振荡甚至溢出；6 阶为科研时序拟合的经验上限
_MAX_POLY_DEGREE = 6


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
    inputs: dict[str, object], ctx: NodeExecutionContext, variable: str | None
) -> tuple[np.ndarray, str]:
    """从 manifest 或 datasource_selection 加载待拟合的一维时间序列。"""
    # 从 datasource_selection 加载
    datasource_selection = dict(inputs.get("datasource_selection", {}))
    input_path = datasource_selection.get("input_path")

    # 也从 manifest artifact 提取
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
                        variable = loaded.products[0].variable.split(",")[0]
            except Exception:
                pass

    if input_path is None:
        raise ValueError(
            "curve_fitting: 需要提供 datasource_selection.input_path 或 manifest"
        )

    reader = UniversalDataReader(Path(str(input_path)))
    available_vars = reader.list_variables()

    # 选择变量
    coord_keys = {"lat", "lon", "latitude", "longitude", "time", "count_grid"}
    if variable is None:
        for v in available_vars:
            if v.lower() not in coord_keys:
                variable = v
                break
    if variable is None or variable not in available_vars:
        raise ValueError(
            f"curve_fitting: 无法确定拟合变量 (available: {available_vars})"
        )

    da = reader.read_variable(variable=variable)
    values = da.values

    # 降维为一维时间序列
    if values.ndim == 3:
        # (time, lat, lon) -> 取空间均值作为时间序列
        values = np.nanmean(values.reshape(values.shape[0], -1), axis=1)
    elif values.ndim == 2:
        values = values.ravel()
    elif values.ndim == 1:
        pass
    else:
        values = values.ravel()

    return values, variable


def _fit_linear(values: np.ndarray) -> dict[str, object]:
    from analysis.timeseries_analysis import TrendAnalysis

    ta = TrendAnalysis()
    result = ta.linear_trend(values)
    # 生成拟合曲线
    time = np.arange(values.size, dtype=np.float64)
    fitted = result["slope"] * time + result["intercept"]
    return {
        "params": result,
        "fitted_curve": fitted,
        "method": "linear",
        "equation": f"y = {result['slope']:.6f} * x + {result['intercept']:.6f}",
    }


def _fit_polynomial(values: np.ndarray, degree: int) -> dict[str, object]:
    time = np.arange(values.size, dtype=np.float64)
    if not 1 <= degree <= _MAX_POLY_DEGREE:
        raise ValueError(
            f"curve_fitting: degree 必须在 1..{_MAX_POLY_DEGREE}"
            f"（收到 {degree}），高阶拟合病态且易溢出"
        )
    valid = np.isfinite(values) & np.isfinite(time)
    if valid.sum() < degree + 1:
        raise ValueError(
            f"curve_fitting: 有效样本不足 ({valid.sum()}) 进行 {degree} 阶多项式拟合"
        )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RankWarning)
        coeffs = np.polyfit(time[valid], values[valid], degree)
    for entry in caught:
        logger.warning("polyfit 条件数差/秩亏 (degree=%d): %s", degree, entry.message)
    poly = np.poly1d(coeffs)
    fitted = poly(time)
    coeff_terms = [f"{c:.6f} * x^{degree - i}" for i, c in enumerate(coeffs)]
    return {
        "params": {"coefficients": coeffs.tolist(), "degree": degree},
        "fitted_curve": fitted,
        "method": "polynomial",
        "equation": "y = " + " + ".join(coeff_terms),
    }


def _fit_exponential(values: np.ndarray) -> dict[str, object]:
    from scipy.optimize import curve_fit

    time = np.arange(values.size, dtype=np.float64)
    valid = np.isfinite(values) & (values > 0)  # 指数拟合要求正值
    if valid.sum() < 3:
        raise ValueError("curve_fitting: 正值样本不足进行指数拟合")

    def _exp_func(x, a, b):
        # 优化器试参可能使 exp 上溢——非有限结果由下游统一截 NaN，抑制告警噪音
        with np.errstate(over="ignore"):
            return a * np.exp(b * x)

    try:
        # 数值专项 W2：初值量纲感知——固定 a0=1.0 对亮温(~300K)等大量纲
        # 数据梯度悬殊，curve_fit 收敛差甚至发散；以数据峰值作 a0
        a0 = float(np.nanmax(values[valid]))
        if not np.isfinite(a0) or a0 <= 0:
            a0 = 1.0
        popt, _ = curve_fit(
            _exp_func, time[valid], values[valid], p0=(a0, 0.01), maxfev=5000
        )
        fitted = _exp_func(time, *popt)
        # b>0 时对全时间轴求值可能在末端溢出 inf——落盘前截为 NaN
        fitted = np.asarray(fitted, dtype=np.float64)
        fitted[~np.isfinite(fitted)] = np.nan
        return {
            "params": {"a": float(popt[0]), "b": float(popt[1])},
            "fitted_curve": fitted,
            "method": "exponential",
            "equation": f"y = {popt[0]:.6f} * exp({popt[1]:.6f} * x)",
        }
    except Exception as e:
        raise ValueError(f"curve_fitting: 指数拟合失败: {e}")


@register_module_decorator(name="curve_fitting", aliases=["curve_fitting_pipeline"])
class CurveFittingModule(BaseModule):
    name = "curve_fitting"
    description = (
        "Curve fitting (linear / polynomial / exponential) on time-series data."
    )
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

        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        method = str(algorithm_params.get("method", "linear")).lower()
        degree = int(algorithm_params.get("degree", 2))
        variable = algorithm_params.get("variable")
        if isinstance(variable, str) and not variable.strip():
            variable = None

        output_dir = Path(
            output_spec_extra.get("output_dir", ctx.workspace / "products" / "fitting")
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "curve_fitting", f"Fit {method} (degree={degree})"
            )

        values, var_name = _load_input_array(
            inputs, ctx, variable if isinstance(variable, str) else None
        )

        if method == "linear":
            result = _fit_linear(values)
        elif method == "polynomial":
            result = _fit_polynomial(values, degree)
        elif method == "exponential":
            result = _fit_exponential(values)
        else:
            raise ValueError(
                f"不支持的拟合方法: {method} (可选 linear|polynomial|exponential)"
            )

        # 数值专项 W2：任何方法拟合曲线的溢出值（inf）不得落盘污染下游
        fitted_curve = np.asarray(result["fitted_curve"], dtype=np.float64)
        fitted_curve[~np.isfinite(fitted_curve)] = np.nan
        result["fitted_curve"] = fitted_curve

        # 输出 MAT + CSV
        out_name = f"fitting_{method}_{var_name}"
        mat_path = output_dir / f"{out_name}.mat"
        csv_path = output_dir / f"{out_name}.csv"

        savemat(
            mat_path,
            {
                "original": values,
                "fitted": result["fitted_curve"],
                "params": result["params"],
                "method": method,
                "equation": result["equation"],
            },
            do_compression=True,
        )

        # CSV: 原始值 + 拟合值
        import csv

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["index", "original", "fitted"])
            for i, (orig, fit) in enumerate(zip(values, result["fitted_curve"])):
                writer.writerow(
                    [
                        i,
                        float(orig) if np.isfinite(orig) else "",
                        float(fit) if np.isfinite(fit) else "",
                    ]
                )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_artifact(
                "curve_fitting", str(mat_path), "fitting_mat"
            )
            ctx.logger_adapter.emit_artifact(
                "curve_fitting", str(csv_path), "fitting_csv"
            )
            ctx.logger_adapter.emit_stage_end(
                "curve_fitting", f"Method={method}, equation={result['equation']}"
            )

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=[
                ProductRef(
                    name=out_name,
                    type="fitting_result",
                    uri=str(mat_path),
                    variable="original,fitted,params",
                    tags={"method": method, "variable": var_name},
                ),
            ],
            main_layers=["original", "fitted"],
            metadata_uri=None,
            extra={
                "module_name": self.name,
                "output_dir": str(output_dir),
                "method": method,
                "equation": result["equation"],
                "variable": var_name,
                "params": result["params"],
            },
        )
        return _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={
                "method": method,
                "variable": var_name,
                "equation": result["equation"],
            },
        )
