from __future__ import annotations

from pathlib import Path

from algorithms.fy import (
    build_fy_daily_command_steps,
    build_fy_daily_mat_payload_from_band_tifs,
    get_fy_daily_multiband_output_path,
    get_fy_profile,
    write_fy_command_plan_json,
)
from contracts.product import ProductManifest, ProductRef
from data_access import resolve_prepared_local_directory
from ingest.fy import build_fy_daily_job_plans, write_fy_daily_plan_json
from modules.base import BaseModule
from modules.registry import register_module_decorator
from utils.fy_executor import execute_fy_command_steps
from utils.request_time import resolve_time_bounds
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


def _resolve_fy_input_dir(datasource_selection: dict[str, object]) -> Path:
    prepared_dir = resolve_prepared_local_directory(
        datasource_selection, ("FY_MWRI_HDF",)
    )
    if prepared_dir is not None:
        return prepared_dir
    input_dir = datasource_selection.get("input_dir")
    if input_dir is None:
        raise KeyError("input_dir")
    return Path(str(input_dir))


@register_module_decorator(name="fy_daily", aliases=["fy_daily_pipeline"])
class FyDailyModule(BaseModule):
    name = "fy_daily"
    description = (
        "Native module that builds FY daily plans and optional execution products."
    )
    input_ports = [
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
        # download/fy_download.path 直连（execute 内 inputs["input_dir"] 消费）；
        # 未声明会被图校验拒绝：unknown input port。
        PortSpec(name="input_dir", kind="value", data_class="string", required=False),
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
        datasource_selection = dict(inputs.get("datasource_selection", {}))
        # Canvas LiteGraph binds template port ``input_dir`` (path string or
        # data_source dict) — e.g. download/fy_download.path 直连。
        raw_input = inputs.get("input_dir")
        if raw_input is not None:
            if isinstance(raw_input, dict):
                datasource_selection = {**dict(raw_input), **datasource_selection}
                if datasource_selection.get("path") and not datasource_selection.get(
                    "input_dir"
                ):
                    datasource_selection["input_dir"] = datasource_selection["path"]
            else:
                datasource_selection.setdefault("input_dir", str(raw_input))
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        if ctx.request.algorithm_params:
            # 请求级参数作底，节点/输入覆盖其上
            algorithm_params = {**dict(ctx.request.algorithm_params), **algorithm_params}
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        input_dir = _resolve_fy_input_dir(datasource_selection)
        # 输出根目录：节点属性 output_dir（种子/画布 params）优先，便于跨 run 落盘到
        # DATA_ROOT 规范目录（如 Soil_Moisture/FY3D）供反演 fy3d_folder data/source 读取。
        output_root = Path(
            str(params.get("output_dir") or "").strip()
            or output_spec_extra.get("output_dir")
            or (ctx.workspace / "products" / "fy_daily")
        )
        orbit_mode = algorithm_params.get("orbit_mode", "MWRID")
        band_ids = tuple(algorithm_params.get("band_ids", [1, 2]))
        overlap_option = algorithm_params.get("overlap_option", "average")
        spatial_mode = algorithm_params.get("spatial_mode", "global")
        gdal_bin = algorithm_params.get("gdal_bin")
        execute_commands = bool(algorithm_params.get("execute_commands", False))

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "fy_plan", f"Build FY daily job plan from {input_dir}"
            )

        start_time, end_time = resolve_time_bounds(
            time_range=ctx.request.time_range,
            algorithm_params=algorithm_params,
            module_label="fy_daily",
        )
        plans = build_fy_daily_job_plans(
            input_dir=input_dir,
            output_root=output_root,
            start_time=start_time,
            end_time=end_time,
            orbit_mode=orbit_mode,
        )
        if not plans:
            raise FileNotFoundError(
                "No FY daily jobs found in the requested date range"
            )

        for plan in plans:
            Path(plan.output_dir).mkdir(parents=True, exist_ok=True)
            Path(plan.work_dir).mkdir(parents=True, exist_ok=True)

        plan_json_path = write_fy_daily_plan_json(
            plans, output_root / "fy_daily_plan.json"
        )
        command_plan_refs: list[ProductRef] = []
        for plan in plans:
            if plan.metadata.get("input_format") == "tif":
                # NAS 预投影逐波段 TIF：无 SDS/地理定位步骤，直接转 mat
                # （见 _build_fy_data_products），跳过 GDAL 命令链。
                continue
            command_steps = build_fy_daily_command_steps(
                plan,
                band_ids=band_ids,
                overlap_option=overlap_option,
                spatial_mode=spatial_mode,
                gdal_bin=gdal_bin,
            )
            command_plan_path = write_fy_command_plan_json(
                command_steps,
                Path(plan.work_dir) / "fy_daily_commands.json",
            )
            if execute_commands:
                execute_fy_command_steps(command_steps, logger=ctx.logger_adapter)
            command_plan_refs.append(
                ProductRef(
                    name=f"{plan.date_key}_{plan.orbit_type}_commands",
                    type="fy_daily_command_plan",
                    uri=str(command_plan_path),
                    variable="10V10H_IA",
                    tags={"date_key": plan.date_key, "orbit_type": plan.orbit_type},
                )
            )
            if ctx.logger_adapter is not None:
                ctx.logger_adapter.emit_artifact(
                    "fy_plan", str(command_plan_path), "fy_daily_command_plan"
                )

        data_product_refs = self._build_fy_data_products(
            plans, output_root, execute_commands=execute_commands
        )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_artifact(
                "fy_plan", str(plan_json_path), "fy_daily_plan_json"
            )
            for product in data_product_refs:
                ctx.logger_adapter.emit_artifact("fy_plan", product.uri, product.type)
            ctx.logger_adapter.emit_stage_end(
                "fy_plan", f"Generated {len(plans)} FY daily job plans"
            )

        product_refs = [
            ProductRef(
                name=f"{plan.date_key}_{plan.orbit_type}",
                type="fy_daily_job_plan",
                uri=str(plan_json_path),
                variable="10V10H",
                tags={"date_key": plan.date_key, "orbit_type": plan.orbit_type},
            )
            for plan in plans
        ]
        product_refs.extend(command_plan_refs)
        product_refs.extend(data_product_refs)

        main_layers = (
            ["TBv", "TBh", "IA"]
            if any(product.type == "fy_daily_mat" for product in data_product_refs)
            else []
        )
        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=product_refs,
            main_layers=main_layers,
            metadata_uri=str(plan_json_path),
            extra={
                "module_name": self.name,
                "output_root": str(output_root),
                "plan_count": len(plans),
                "orbit_mode": orbit_mode,
                "band_ids": list(band_ids),
                "execute_commands": execute_commands,
                "artifact_mode": "data_products" if main_layers else "plan_only",
            },
        )
        return _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={"product_count": len(product_refs)},
        )

    def _build_fy_data_products(
        self,
        plans: list,
        output_root: Path,
        *,
        execute_commands: bool,
    ) -> list[ProductRef]:
        tif_plans = [p for p in plans if p.metadata.get("input_format") == "tif"]
        hdf_plans = [p for p in plans if p.metadata.get("input_format") != "tif"]
        if not execute_commands and not tif_plans:
            return []

        from scipy.io import savemat

        # 计划模式下 output_root 可能尚未创建（tif 分支不走 GDAL 命令链，
        # 无 work_dir 创建副作用），savemat 前必须确保目录存在。
        output_root.mkdir(parents=True, exist_ok=True)
        data_products: list[ProductRef] = []
        # 单轨道日（orbit_mode=MWRID/MWRIA）落盘规范名 YYYYMMDD.mat 到
        # output_root，供 omega_sf_fenkuai 的 fy3d/fy3b_folder（要求 \d{8} 命名）
        # 直接读取；Both 模式同日双轨道会撞名，回落 mat/YYYYMMDD_<orbit>.mat。
        date_plan_counts: dict[str, int] = {}
        for plan in plans:
            date_plan_counts[plan.date_key] = date_plan_counts.get(plan.date_key, 0) + 1
        mat_dir = output_root / "mat"

        # NAS 预投影逐波段 TIF → 直接转 mat（无需 GDAL/execute_commands）
        for plan in tif_plans:
            payload = build_fy_daily_mat_payload_from_band_tifs(
                list(plan.input_files), plan.satellite
            )
            if date_plan_counts[plan.date_key] == 1:
                mat_path = output_root / f"{plan.date_key}.mat"
            else:
                mat_dir.mkdir(parents=True, exist_ok=True)
                mat_path = mat_dir / f"{plan.date_key}_{plan.orbit_type}.mat"
            savemat(mat_path, payload, do_compression=True)
            data_products.append(
                ProductRef(
                    name=f"{plan.date_key}_{plan.orbit_type}_fy_daily",
                    type="fy_daily_mat",
                    uri=str(mat_path),
                    variable="TBv,TBh,IA",
                    tags={
                        "date_key": plan.date_key,
                        "orbit_type": plan.orbit_type,
                        "satellite": plan.satellite,
                        "input_format": "tif",
                    },
                )
            )

        if not execute_commands:
            return data_products

        for plan in hdf_plans:
            tif_path = get_fy_daily_multiband_output_path(plan)
            if not tif_path.exists():
                continue
            data_products.append(
                ProductRef(
                    name=f"{plan.date_key}_{plan.orbit_type}_fy_daily_tif",
                    type="fy_daily_tif",
                    uri=str(tif_path),
                    variable="TBv,TBh,IA",
                    tags={
                        "date_key": plan.date_key,
                        "orbit_type": plan.orbit_type,
                        "satellite": plan.satellite,
                    },
                )
            )
            payload = _load_fy_multiband_payload(tif_path, satellite=plan.satellite)
            if date_plan_counts[plan.date_key] == 1:
                mat_path = output_root / f"{plan.date_key}.mat"
            else:
                mat_dir.mkdir(parents=True, exist_ok=True)
                mat_path = mat_dir / f"{plan.date_key}_{plan.orbit_type}.mat"
            savemat(mat_path, payload, do_compression=True)
            data_products.append(
                ProductRef(
                    name=f"{plan.date_key}_{plan.orbit_type}_fy_daily",
                    type="fy_daily_mat",
                    uri=str(mat_path),
                    variable="TBv,TBh,IA",
                    tags={
                        "date_key": plan.date_key,
                        "orbit_type": plan.orbit_type,
                        "satellite": plan.satellite,
                    },
                )
            )
        return data_products


def _load_fy_multiband_payload(tif_path: Path, *, satellite: str) -> dict[str, object]:
    import numpy as np
    import rasterio

    profile = get_fy_profile(satellite)
    with rasterio.open(tif_path) as dataset:
        if dataset.count < 3:
            raise ValueError(
                f"FY multiband output must contain at least 3 bands: {tif_path}"
            )
        tbv = dataset.read(1).astype(np.float64)
        tbh = dataset.read(2).astype(np.float64)
        ia = dataset.read(3).astype(np.float64)
        nodata = dataset.nodata
        for array in (tbv, tbh, ia):
            if nodata is not None:
                array[array == nodata] = np.nan
            array[~np.isfinite(array)] = np.nan
    tbv = tbv * profile.tb_scale + profile.tb_offset
    tbh = tbh * profile.tb_scale + profile.tb_offset
    ia = ia * profile.zen_scale + profile.zen_offset
    tbv[(tbv > 330.0) | (tbv < 0.0)] = np.nan
    tbh[(tbh > 330.0) | (tbh < 0.0)] = np.nan
    return {"TBv": tbv, "TBh": tbh, "IA": ia}
