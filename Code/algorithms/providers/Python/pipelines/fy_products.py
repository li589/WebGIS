from __future__ import annotations

from pathlib import Path

from algorithms.fy import (
    build_fy_daily_command_steps,
    get_fy_daily_multiband_output_path,
    get_fy_profile,
    write_fy_command_plan_json,
)
from contracts.job import JobRequest
from contracts.product import ProductManifest, ProductRef
from contracts.runtime import RuntimeContext
from data_access import resolve_prepared_local_directory
from ingest.fy import build_fy_daily_job_plans, write_fy_daily_plan_json
from pipelines.base import BasePipeline, PipelinePlan
from utils.fy_executor import execute_fy_command_steps


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


class FyDailyPipeline(BasePipeline):
    name = "fy_daily_pipeline"

    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        execute_commands = bool(request.algorithm_params.get("execute_commands", False))
        estimated_outputs = ["fy_daily_plan_json", "fy_daily_command_plan"]
        if execute_commands:
            estimated_outputs.extend(["fy_daily_tif", "fy_daily_mat"])
        return PipelinePlan(
            required_datasets=["FY_MWRI_HDF"],
            required_variables=["10V", "10H", "Latitude", "Longitude", "SensorZenith"],
            estimated_outputs=estimated_outputs,
            parallelizable=True,
            chunk_strategy="daily_orbit_group",
            cache_requirement="partial",
        )

    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        input_dir = _resolve_fy_input_dir(request.datasource_selection)
        output_root = Path(
            request.output_spec.extra.get(
                "output_dir", ctx.workspace / "products" / "fy_daily"
            )
        )
        orbit_mode = request.algorithm_params.get("orbit_mode", "MWRID")
        band_ids = tuple(request.algorithm_params.get("band_ids", [1, 2]))
        overlap_option = request.algorithm_params.get("overlap_option", "average")
        spatial_mode = request.algorithm_params.get("spatial_mode", "global")
        gdal_bin = request.algorithm_params.get("gdal_bin")
        execute_commands = bool(request.algorithm_params.get("execute_commands", False))

        if self.logger_adapter is not None:
            self.logger_adapter.emit_stage_start(
                "fy_plan", f"Build FY daily job plan from {input_dir}"
            )

        plans = build_fy_daily_job_plans(
            input_dir=input_dir,
            output_root=output_root,
            start_time=request.time_range.start,
            end_time=request.time_range.end,
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
                execute_fy_command_steps(command_steps, logger=self.logger_adapter)
            command_plan_refs.append(
                ProductRef(
                    name=f"{plan.date_key}_{plan.orbit_type}_commands",
                    type="fy_daily_command_plan",
                    uri=str(command_plan_path),
                    variable="10V10H_IA",
                    tags={"date_key": plan.date_key, "orbit_type": plan.orbit_type},
                )
            )
            if self.logger_adapter is not None:
                self.logger_adapter.emit_artifact(
                    "fy_plan", str(command_plan_path), "fy_daily_command_plan"
                )

        data_product_refs = self._build_fy_data_products(
            plans, output_root, execute_commands=execute_commands
        )

        if self.logger_adapter is not None:
            self.logger_adapter.emit_artifact(
                "fy_plan", str(plan_json_path), "fy_daily_plan_json"
            )
            for product in data_product_refs:
                self.logger_adapter.emit_artifact("fy_plan", product.uri, product.type)
            self.logger_adapter.emit_stage_end(
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

        return ProductManifest(
            job_id=request.job_id,
            run_id=ctx.run_id,
            products=product_refs,
            main_layers=main_layers,
            metadata_uri=str(plan_json_path),
            extra={
                "pipeline_name": self.name,
                "output_root": str(output_root),
                "plan_count": len(plans),
                "orbit_mode": orbit_mode,
                "band_ids": list(band_ids),
                "execute_commands": execute_commands,
                "artifact_mode": "data_products" if main_layers else "plan_only",
            },
        )

    def _build_fy_data_products(
        self,
        plans: list,
        output_root: Path,
        *,
        execute_commands: bool,
    ) -> list[ProductRef]:
        if not execute_commands:
            return []

        from scipy.io import savemat

        data_products: list[ProductRef] = []
        mat_dir = output_root / "mat"
        mat_dir.mkdir(parents=True, exist_ok=True)
        for plan in plans:
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
