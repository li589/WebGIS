"""DuXin 时序土壤水分估算 module（Python import provider 包装层）。

把 ``algorithms.duxin_sme`` 的时序 SAR 土壤水分反演注册为 workflow 可用节点
（module_name: ``duxin_time_series_sme``）。读取本地 .mat 输入（变量
``obsv_data`` / ``inc_ang``，支持常用别名），按配置执行三段反演
（时序 alpha → 查表介电常数 → Topp 水分），产出每期 GeoTIFF(COG) +
MAT + manifest。

输入 .mat 约定（与 MATLAB 原版主程序一致）：
- ``obsv_data``：(rows, cols, N) 时序 SAR 后向散射（线性单位，非 dB）
- ``inc_ang``：(rows, cols) 入射角（rad，约 0.3~1.2）
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from algorithms.duxin_sme import (
    DuxinSmeConfig,
    run_time_series_sme,
)
from contracts.product import ProductManifest, ProductRef
from ingest.mat_bundle import get_first_available, load_mat_file
from modules.base import BaseModule
from modules.registry import register_module_decorator
from output import OutputCoordinator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec

logger = logging.getLogger(__name__)

# 输入 .mat 变量别名（MATLAB 原版变量名优先）
_OBSV_ALIASES = ["obsv_data", "obs_data", "observed_data", "backscatter", "sigma0"]
_INC_ANG_ALIASES = ["inc_ang", "incidence_angle", "inc_angle", "theta"]


def _coerce_edge_dir(value: object) -> str | None:
    """从上游边输入提取数据目录/文件（字符串或含路径键的 dict）。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("path", "file", "local_path", "input_dir", "input_file"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None


def _resolve_input_file(datasource_selection: dict[str, object]) -> Path:
    """解析输入 .mat 文件路径（input_file 优先，input_dir 下找首个 .mat）。"""
    for key in ("input_file", "mat_file", "file"):
        raw = datasource_selection.get(key)
        if isinstance(raw, str) and raw.strip():
            return Path(raw.strip())
    input_dir = datasource_selection.get("input_dir")
    if isinstance(input_dir, str) and input_dir.strip():
        directory = Path(input_dir.strip())
        if directory.is_dir():
            candidates = sorted(directory.glob("*.mat"))
            if candidates:
                return candidates[0]
            raise FileNotFoundError(f"no .mat files under input_dir: {directory}")
        if directory.is_file():
            return directory
    raise KeyError(
        "duxin_time_series_sme requires datasource_selection.input_file or input_dir"
    )


def _extract_observation_stack(payload: dict[str, object]) -> tuple[np.ndarray, np.ndarray]:
    """从 .mat 载荷提取观测时序与入射角。"""
    obsv = get_first_available(payload, list(_OBSV_ALIASES))
    inc_ang = get_first_available(payload, list(_INC_ANG_ALIASES))
    if obsv is None:
        raise KeyError(f"input .mat missing observation variable (tried {_OBSV_ALIASES})")
    if inc_ang is None:
        raise KeyError(f"input .mat missing incidence angle variable (tried {_INC_ANG_ALIASES})")
    obsv_arr = np.asarray(obsv, dtype=np.float64)
    ang_arr = np.asarray(inc_ang, dtype=np.float64)
    if obsv_arr.ndim != 3:
        raise ValueError(
            f"obsv_data must be 3-D (rows, cols, N), got shape {obsv_arr.shape}"
        )
    if ang_arr.shape != obsv_arr.shape[:2]:
        raise ValueError(
            f"inc_ang shape {ang_arr.shape} must match obsv_data spatial "
            f"shape {obsv_arr.shape[:2]}"
        )
    return obsv_arr, ang_arr


def _as_dict(value: object) -> dict[str, object]:
    """把上游输入值收窄为 dict（非 dict 时回退空 dict）。"""
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return {}


def _as_float(value: object, default: float) -> float:
    """把上游参数值收窄为 float（数字/数字字符串，其余回退默认值）。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _as_int_or_none(value: object) -> int | None:
    """把上游参数值收窄为 int（数字/数字字符串，其余 None）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _extract_region_bounds(region) -> tuple[float, float, float, float] | None:
    """从 RegionSpec 提取地理边界；无 region 时返回中国区域默认值。"""
    if region is None:
        return (73.0, 18.0, 135.0, 53.0)
    kind = getattr(region, "kind", None)
    value = getattr(region, "value", None)
    if kind == "bbox" and value:
        bbox = value.get("bbox") if value else None
        if bbox is None and value:
            bbox = (
                value.get("west"),
                value.get("south"),
                value.get("east"),
                value.get("north"),
            )
        if bbox and len(bbox) == 4:
            west, south, east, north = (float(c) for c in bbox)
            return (west, south, east, north)
    return (73.0, 18.0, 135.0, 53.0)


@register_module_decorator(
    name="duxin_time_series_sme",
    aliases=["duxin_sme", "time_series_soil_moisture_estimation"],
    template_overrides={
        "phase": "inversion",
        "notes": (
            "DuXin 时序 SAR 土壤水分反演：滑窗约束最小二乘估计 Fresnel alpha，"
            "查表反演介电常数，Topp 模型换算体积含水量（HH/VV 双极化）。"
            "输入 .mat 需含 obsv_data(rows,cols,N, 线性单位) 与 inc_ang(rows,cols, rad)。"
        ),
    },
)
class DuxinTimeSeriesSmeModule(BaseModule):
    name = "duxin_time_series_sme"
    description = (
        "Time-series SAR soil moisture estimation (DuXin): sliding-window "
        "bounded least-squares alpha retrieval, LUT dielectric inversion, "
        "Topp model conversion."
    )
    input_ports = [
        PortSpec(name="data", kind="data", data_class="source", required=False),
        PortSpec(
            name="datasource_selection", kind="config", data_class="dict", required=False
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

        datasource_selection = _as_dict(inputs.get("datasource_selection"))
        raw_params = inputs.get("algorithm_params") or params or {}
        algorithm_params = _as_dict(raw_params)
        output_spec_extra = _as_dict(inputs.get("output_spec_extra"))

        edge_value = _coerce_edge_dir(inputs.get("data"))
        if edge_value:
            edge_path = Path(edge_value)
            if edge_path.is_dir():
                datasource_selection.setdefault("input_dir", str(edge_path))
            else:
                datasource_selection.setdefault("input_file", str(edge_path))
        input_file = _resolve_input_file(datasource_selection)

        output_dir_value = output_spec_extra.get("output_dir") or (
            ctx.workspace / "products" / "duxin_time_series_sme"
        )
        output_dir = Path(str(output_dir_value))
        output_dir.mkdir(parents=True, exist_ok=True)

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                self.name, f"Run time-series SME from {input_file}"
            )

        payload = load_mat_file(input_file)
        obsv_arr, ang_arr = _extract_observation_stack(payload)

        raw_num_step = algorithm_params.get("num_step")
        config = DuxinSmeConfig(
            polarization=str(algorithm_params.get("polarization", "hh")),
            num_step=_as_int_or_none(raw_num_step),
            epsilon_min=_as_float(algorithm_params.get("epsilon_min"), 4.0),
            epsilon_max=_as_float(algorithm_params.get("epsilon_max"), 35.0),
        )
        results = run_time_series_sme(obsv_arr, ang_arr, config)
        moisture = results["soil_moisture"]
        _, _, num_image = moisture.shape

        region_bounds = _extract_region_bounds(ctx.request.region)
        transform, crs = _build_transform(region_bounds, moisture.shape)
        pixel_resolution = abs(transform.a) if transform else 0.01

        coordinator = OutputCoordinator(
            job_id=ctx.request.job_id,
            output_dir=output_dir,
            module_name=self.name,
            workflow_name=ctx.request.workflow_name or "",
            time_range={
                "start": ctx.request.time_range.start.isoformat(),
                "end": ctx.request.time_range.end.isoformat(),
            },
            region={"bounds": region_bounds} if region_bounds else None,
            crs="EPSG:4326",
            pixel_resolution=pixel_resolution,
            preview_cmap="BrBG",
            preview_size=(512, 512),
            compress="deflate",
            overwrite=True,
            storage_backend=ctx.runtime_context.storage_backend,
        )

        # 每期产物：MAT（保留原格式通道）+ COG GeoTIFF + preview
        for k in range(num_image):
            mat_path = output_dir / f"soil_moisture_{k + 1:03d}.mat"
            savemat(
                mat_path,
                {
                    "soil_moisture": moisture[:, :, k],
                    "soil_epsilon": results["soil_epsilon"][:, :, k],
                    "soil_alpha": results["soil_alpha"][:, :, k],
                },
                do_compression=True,
            )
            coordinator.write_raster(
                name=f"soil_moisture_{k + 1:03d}",
                data=moisture[:, :, k],
                transform=transform,
                nodata=0.0,
                unit="%",
                description=f"DuXin 时序土壤水分（第 {k + 1}/{num_image} 期，体积含水量 %）",
                var_name="soil_moisture",
                generate_preview=True,
            )
            coordinator.add_mat(
                name=mat_path.stem,
                path=mat_path,
                variable="soil_moisture,soil_epsilon,soil_alpha",
                description=f"DuXin 时序土壤水分 MATLAB 产物（第 {k + 1} 期）",
                type="duxin_sme_mat",
            )
            if ctx.logger_adapter is not None:
                ctx.logger_adapter.emit_artifact(
                    self.name, str(mat_path), "duxin_sme_mat"
                )

        coordinator.add_diagnostic("stack_shape", list(obsv_arr.shape))
        coordinator.add_diagnostic("polarization", config.polarization)
        coordinator.add_diagnostic("num_step", config.num_step or obsv_arr.shape[2])
        coordinator.add_diagnostic("input_file", str(input_file))
        coordinator.add_diagnostic("algorithm_params", algorithm_params)

        manifest_dict = coordinator.build_manifest(
            extra={
                "module_name": self.name,
                "output_dir": str(output_dir),
                "region_bounds": region_bounds,
            }
        )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_end(
                self.name,
                f"Generated {num_image} soil moisture products"
                f" → {manifest_dict.get('manifest_path', output_dir / 'manifest.json')}",
            )

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=[
                ProductRef(
                    name=str(p.get("name", "")),
                    type=str(p.get("type", "mat")),
                    uri=str(p.get("uri", "")),
                    variable=p.get("variable"),
                )
                for p in manifest_dict.get("products", [])
            ],
            main_layers=["soil_moisture"],
            metadata_uri=manifest_dict.get("manifest_uri"),
            extra={
                "module_name": self.name,
                "output_dir": str(output_dir),
                "count": num_image,
                "manifest_path": manifest_dict.get("manifest_path", ""),
                "product_count": num_image,
            },
        )

        artifact = ArtifactRef(
            artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
            artifact_type="product_manifest",
            format="python_object",
            uri=None,
            producer_node_id=ctx.node_id,
            schema_name="ProductManifest",
            metadata={"module_name": self.name, "product_count": num_image},
        )
        ctx.artifact_store.put(artifact, payload=manifest)
        return {"manifest": artifact}


def _build_transform(region_bounds, stack_shape):
    """按边界与数组 shape 构建 rasterio Affine（rasterio 不可用时返回 None）。"""
    try:
        from rasterio.transform import from_bounds
    except ImportError:
        return (None, None)
    height, width = stack_shape[:2]
    west, south, east, north = region_bounds or (73.0, 18.0, 135.0, 53.0)
    transform = from_bounds(west, south, east, north, width, height)
    try:
        import rasterio

        crs = rasterio.crs.CRS.from_epsg(4326)
    except ImportError:
        crs = None
    return (transform, crs)
