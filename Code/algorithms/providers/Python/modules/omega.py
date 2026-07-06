from __future__ import annotations

from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from data_access import resolve_prepared_local_path
from ingest.mat_bundle import load_mat_file
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


def _resolve_omega_datasource_selection(datasource_selection: dict[str, object]) -> dict[str, object]:
    resolved = dict(datasource_selection)
    input_mat = resolve_prepared_local_path(resolved, ("timeseries_bundle_mat", "input_mat"))
    if input_mat is not None:
        resolved["input_mat"] = str(input_mat)
    for key in ("omega_fixed_mat", "exp0_calib_mat"):
        local_path = resolve_prepared_local_path(resolved, (key,))
        if local_path is not None:
            resolved[key] = str(local_path)
    return resolved


@register_module_decorator(name="omega_block", aliases=["omega_block_pipeline"])
class OmegaBlockModule(BaseModule):
    name = "omega_block"
    description = "Native module that runs OMEGA block retrieval over a timeseries MAT bundle."
    mode_required_inputs = {
        "omega": ("input_mat", "omega_fixed_mat", "exp0_calib_mat"),
    }
    input_ports = [
        PortSpec(name="datasource_selection", kind="config", data_class="dict", required=False),
        PortSpec(name="algorithm_params", kind="config", data_class="dict", required=False),
        PortSpec(name="output_spec_extra", kind="config", data_class="dict", required=False),
        PortSpec(name="input_mat", kind="scalar", data_class="path", required=False),
        PortSpec(name="omega_fixed_mat", kind="scalar", data_class="path", required=False),
        PortSpec(name="exp0_calib_mat", kind="scalar", data_class="path", required=False),
    ]
    output_ports = [PortSpec(name="manifest", kind="artifact", data_class="product_manifest")]

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        from scipy.io import savemat

        from algorithms.omega import build_omega_config, build_omega_field_config, execute_omega_retrieval

        _ = params
        datasource_selection = dict(inputs.get("datasource_selection", {}))
        for key in ("input_mat", "omega_fixed_mat", "exp0_calib_mat"):
            if key in inputs and inputs[key] is not None:
                datasource_selection[key] = inputs[key]
        datasource_selection = _resolve_omega_datasource_selection(datasource_selection)
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        mode = str(algorithm_params.get("mode", "dh")).lower()
        missing_keys = [key for key in ("input_mat",) if key not in datasource_selection]
        if mode == "omega":
            missing_keys.extend(
                key
                for key in ("omega_fixed_mat", "exp0_calib_mat")
                if key not in datasource_selection or datasource_selection.get(key) is None
            )
        if missing_keys:
            raise ValueError(f"omega_block requires datasource_selection keys for mode '{mode}': {', '.join(sorted(missing_keys))}")

        input_mat = Path(datasource_selection["input_mat"])
        payload = load_mat_file(input_mat)
        for key in ("omega_fixed_mat", "exp0_calib_mat"):
            extra_path = datasource_selection.get(key)
            if extra_path is not None:
                payload.update(load_mat_file(extra_path))

        config = build_omega_config(algorithm_params)
        field_config = build_omega_field_config(algorithm_params)
        write_daily_files = bool(algorithm_params.get("write_daily_files", True))
        output_dir = Path(output_spec_extra.get("output_dir", ctx.workspace / "products" / "omega_block"))
        output_dir.mkdir(parents=True, exist_ok=True)

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start("omega_block", f"Run omega block retrieval for {input_mat.name}")

        result = execute_omega_retrieval(payload, config=config, field_config=field_config)
        start_key = result["date_keys"][0] if result["date_keys"] else input_mat.stem
        end_key = result["date_keys"][-1] if result["date_keys"] else input_mat.stem

        block_path = output_dir / f"omega_block_{start_key}_{end_key}.mat"
        block_payload = {key: value for key, value in result.items() if value is not None}
        savemat(block_path, block_payload, do_compression=True)

        products = [
            ProductRef(
                name=f"omega_block_{start_key}_{end_key}",
                type="omega_block_mat",
                uri=str(block_path),
                variable="OMEGA_mat",
            )
        ]

        if write_daily_files:
            daily_dir = output_dir / "daily_omega"
            daily_dir.mkdir(parents=True, exist_ok=True)
            for day_index, date_key in enumerate(result["date_keys"]):
                day_path = daily_dir / f"{date_key}.mat"
                savemat(
                    day_path,
                    {
                        "OMEGA": result["OMEGA_mat"][day_index, :],
                        "SM": result["SM_RET_mat"][day_index, :],
                        "VOD": result["VOD_RET_mat"][day_index, :],
                        "Tau_star": result["Tau_star_mat"][day_index, :],
                    },
                    do_compression=True,
                )
                products.append(
                    ProductRef(name=f"{date_key}_omega", type="omega_daily_mat", uri=str(day_path), variable="OMEGA")
                )

        if ctx.logger_adapter is not None:
            for product in products:
                ctx.logger_adapter.emit_artifact("omega_block", product.uri, product.type)
            ctx.logger_adapter.emit_stage_end("omega_block", f"Generated {len(products)} omega products")

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=products,
            main_layers=["OMEGA_mat", "SM_RET_mat", "VOD_RET_mat", "Tau_star_mat"],
            qc_layers=["qc_flag_mat", "qc_condk_mat", "qc_sratio_mat"],
            metadata_uri=None,
            extra={
                "module_name": self.name,
                "output_dir": str(output_dir),
                "freq_ghz": config.freq_ghz,
                "temp_scheme": config.temp_scheme,
                "exp_mode": config.exp_mode,
                "block_days": config.block_days,
                "pixel_chunk_size": config.pixel_chunk_size,
            },
        )
        return _store_manifest(ctx, module_name=self.name, manifest=manifest, metadata={"product_count": len(products)})
