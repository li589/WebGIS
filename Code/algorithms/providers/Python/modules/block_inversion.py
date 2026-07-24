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


def _resolve_block_datasource_selection(
    datasource_selection: dict[str, object],
) -> dict[str, object]:
    resolved = dict(datasource_selection)
    input_mat = resolve_prepared_local_path(
        resolved, ("timeseries_bundle_mat", "input_mat")
    )
    # Only overwrite input_mat if the resolved path is an actual file.
    # The DataAccessCoordinator may resolve timeseries_bundle_mat to a
    # directory; using a directory as input_mat causes load_mat_file to fail.
    if input_mat is not None and input_mat.is_file():
        resolved["input_mat"] = str(input_mat)
    dh_mat = resolve_prepared_local_path(resolved, ("dh_mat",))
    if dh_mat is not None and dh_mat.is_file():
        resolved["dh_mat"] = str(dh_mat)
    return resolved


@register_module_decorator(name="block_inversion", aliases=["block_inversion_pipeline"])
class BlockInversionModule(BaseModule):
    name = "block_inversion"
    description = "Native module that runs block-based DH or DDCA inversion over a timeseries MAT bundle."
    mode_required_inputs = {
        "ddca": ("input_mat", "dh_mat"),
        "dh": ("input_mat",),
    }
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
        PortSpec(name="input_mat", kind="scalar", data_class="path", required=False),
        PortSpec(name="dh_mat", kind="scalar", data_class="path", required=False),
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

        from algorithms.block_inversion import (
            build_block_field_config,
            execute_block_inversion,
        )

        _ = params
        datasource_selection = dict(inputs.get("datasource_selection", {}))
        if "input_mat" in inputs:
            datasource_selection["input_mat"] = inputs["input_mat"]
        if "dh_mat" in inputs and inputs["dh_mat"] is not None:
            datasource_selection["dh_mat"] = inputs["dh_mat"]
        datasource_selection = _resolve_block_datasource_selection(datasource_selection)
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        mode = str(algorithm_params.get("mode", "dh")).lower()
        missing_keys = [
            key for key in ("input_mat",) if key not in datasource_selection
        ]
        if mode == "ddca" and "dh_mat" not in datasource_selection:
            missing_keys.append("dh_mat")
        if missing_keys:
            raise ValueError(
                f"block_inversion requires datasource_selection keys for mode '{mode}': {', '.join(sorted(missing_keys))}"
            )

        input_mat = Path(datasource_selection["input_mat"])
        payload = load_mat_file(input_mat)
        freq_ghz = float(algorithm_params.get("freq_ghz", 1.4))
        pixel_chunk_size = int(algorithm_params.get("pixel_chunk_size", 2000))
        write_daily_files = bool(algorithm_params.get("write_daily_files", True))
        dh_mat_path = datasource_selection.get("dh_mat")
        field_config = build_block_field_config(algorithm_params)
        output_dir = Path(
            output_spec_extra.get(
                "output_dir", ctx.workspace / "products" / "block_inversion"
            )
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "block_inversion", f"Run {mode} block inversion for {input_mat.name}"
            )

        result = execute_block_inversion(
            payload,
            mode=mode,
            freq_ghz=freq_ghz,
            pixel_chunk_size=pixel_chunk_size,
            dh_mat_path=dh_mat_path,
            field_config=field_config,
        )

        products: list[ProductRef] = []
        start_key = result["date_keys"][0] if result["date_keys"] else input_mat.stem
        end_key = result["date_keys"][-1] if result["date_keys"] else input_mat.stem

        tau_path = output_dir / f"tau_block_{start_key}_{end_key}.mat"
        savemat(
            tau_path,
            {"Tau_ini_mat": result["Tau_ini_mat"], "date_keys": result["date_keys"]},
            do_compression=True,
        )
        products.append(
            ProductRef(
                name=f"tau_block_{start_key}_{end_key}",
                type="tau_block_mat",
                uri=str(tau_path),
                variable="Tau_ini_mat",
            )
        )

        if mode == "dh":
            block_path = output_dir / f"dh_block_{start_key}_{end_key}.mat"
            savemat(
                block_path,
                {
                    "DH_mat": result["DH_mat"],
                    "Tau_ini_mat": result["Tau_ini_mat"],
                    "date_keys": result["date_keys"],
                },
                do_compression=True,
            )
            products.append(
                ProductRef(
                    name=f"dh_block_{start_key}_{end_key}",
                    type="dh_block_mat",
                    uri=str(block_path),
                    variable="DH_mat",
                )
            )
            main_layers = ["DH_mat", "Tau_ini_mat"]
            if write_daily_files:
                daily_dir = output_dir / "daily_dh"
                daily_dir.mkdir(parents=True, exist_ok=True)
                for day_index, date_key in enumerate(result["date_keys"]):
                    day_path = daily_dir / f"{date_key}.mat"
                    savemat(
                        day_path,
                        {
                            "DH": result["DH_mat"][day_index, :],
                            "Tau_ini": result["Tau_ini_mat"][day_index, :],
                        },
                        do_compression=True,
                    )
                    products.append(
                        ProductRef(
                            name=f"{date_key}_dh",
                            type="dh_daily_mat",
                            uri=str(day_path),
                            variable="DH",
                        )
                    )
        else:
            block_path = output_dir / f"sm_vod_block_{start_key}_{end_key}.mat"
            savemat(
                block_path,
                {
                    "SM_mat": result["SM_mat"],
                    "VOD_mat": result["VOD_mat"],
                    "H_used_mat": result["H_used_mat"],
                    "Tau_ini_mat": result["Tau_ini_mat"],
                    "date_keys": result["date_keys"],
                },
                do_compression=True,
            )
            products.append(
                ProductRef(
                    name=f"sm_vod_block_{start_key}_{end_key}",
                    type="sm_vod_block_mat",
                    uri=str(block_path),
                    variable="SM_mat",
                )
            )
            main_layers = ["SM_mat", "VOD_mat", "Tau_ini_mat"]
            if write_daily_files:
                daily_dir = output_dir / "daily_sm_vod"
                daily_dir.mkdir(parents=True, exist_ok=True)
                for day_index, date_key in enumerate(result["date_keys"]):
                    day_path = daily_dir / f"{date_key}.mat"
                    savemat(
                        day_path,
                        {
                            "SM": result["SM_mat"][day_index, :],
                            "VOD": result["VOD_mat"][day_index, :],
                            "Tau_ini": result["Tau_ini_mat"][day_index, :],
                        },
                        do_compression=True,
                    )
                    products.append(
                        ProductRef(
                            name=f"{date_key}_sm",
                            type="sm_daily_mat",
                            uri=str(day_path),
                            variable="SM",
                        )
                    )
                    products.append(
                        ProductRef(
                            name=f"{date_key}_vod",
                            type="vod_daily_mat",
                            uri=str(day_path),
                            variable="VOD",
                        )
                    )

        if ctx.logger_adapter is not None:
            for product in products:
                ctx.logger_adapter.emit_artifact(
                    "block_inversion", product.uri, product.type
                )
            ctx.logger_adapter.emit_stage_end(
                "block_inversion", f"Generated {len(products)} block inversion products"
            )

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=products,
            main_layers=main_layers,
            metadata_uri=None,
            extra={
                "module_name": self.name,
                "mode": mode,
                "input_mat": str(input_mat),
                "output_dir": str(output_dir),
                "freq_ghz": freq_ghz,
                "pixel_chunk_size": pixel_chunk_size,
                "missing_dates": result.get("missing_dates", []),
            },
        )
        return _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={"product_count": len(products)},
        )
