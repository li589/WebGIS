from __future__ import annotations

from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from data_access import resolve_prepared_local_path
from ingest.mat_bundle import (
    extract_ddca_inputs,
    extract_inversion_inputs,
    load_mat_file,
)
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


def _resolve_inversion_input_mat(datasource_selection: dict[str, object]) -> Path:
    prepared_path = resolve_prepared_local_path(
        datasource_selection, ("daily_bundle_mat", "input_mat")
    )
    # Only use the prepared path if it's an actual file (not a directory).
    # The DataAccessCoordinator may resolve daily_bundle_mat to a directory.
    if prepared_path is not None and prepared_path.is_file():
        return prepared_path
    input_mat = datasource_selection.get("input_mat")
    if input_mat is None:
        raise KeyError("input_mat")
    return Path(str(input_mat))


@register_module_decorator(name="inversion_daily", aliases=["inversion_daily_pipeline"])
class InversionDailyModule(BaseModule):
    name = "inversion_daily"
    description = "Native module that runs DDCA or dynamic-h daily inversion from a prepared MAT bundle."
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

        from algorithms.inversion import ddca_retrieve_grid, retrieve_dynamic_h_grid

        _ = params
        datasource_selection = dict(inputs.get("datasource_selection", {}))
        algorithm_params = dict(inputs.get("algorithm_params", {}))
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        input_mat = _resolve_inversion_input_mat(datasource_selection)
        payload = load_mat_file(input_mat)
        mode = str(algorithm_params.get("mode", "ddca")).lower()
        freq_ghz = float(algorithm_params.get("freq_ghz", 1.4))
        output_dir = Path(
            output_spec_extra.get(
                "output_dir", ctx.workspace / "products" / "inversion_daily"
            )
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "inversion_daily", f"Run {mode} inversion for {input_mat.name}"
            )

        if mode == "dh":
            inputs_payload = extract_inversion_inputs(payload)
            dh = retrieve_dynamic_h_grid(
                inputs_payload["tbv"],
                inputs_payload["tbh"],
                inputs_payload["ts"],
                inputs_payload["tau_ini"],
                inputs_payload["clay_fraction"],
                inputs_payload["albedo"],
                inputs_payload["porosity"],
                freq_ghz,
                inputs_payload["theta_deg"],
            )
            output_path = output_dir / f"{input_mat.stem}_dh.mat"
            savemat(output_path, {"DH": dh}, do_compression=True)
            products = [
                ProductRef(
                    name=f"{input_mat.stem}_dh",
                    type="dh_mat",
                    uri=str(output_path),
                    variable="DH",
                )
            ]
            main_layers = ["DH"]
        else:
            inputs_payload = extract_ddca_inputs(payload)
            sm, vod = ddca_retrieve_grid(
                inputs_payload["tbv"],
                inputs_payload["tbh"],
                inputs_payload["ts"],
                inputs_payload["tau_ini"],
                inputs_payload["h_value"],
                inputs_payload["clay_fraction"],
                inputs_payload["albedo"],
                inputs_payload["porosity"],
                freq_ghz,
                inputs_payload["theta_deg"],
            )
            output_path = output_dir / f"{input_mat.stem}_sm_vod.mat"
            savemat(output_path, {"SM": sm, "VOD": vod}, do_compression=True)
            products = [
                ProductRef(
                    name=f"{input_mat.stem}_sm",
                    type="sm_mat",
                    uri=str(output_path),
                    variable="SM",
                ),
                ProductRef(
                    name=f"{input_mat.stem}_vod",
                    type="vod_mat",
                    uri=str(output_path),
                    variable="VOD",
                ),
            ]
            main_layers = ["SM", "VOD"]

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_artifact(
                "inversion_daily", str(output_path), "inversion_mat"
            )
            ctx.logger_adapter.emit_stage_end(
                "inversion_daily", f"Generated {output_path.name}"
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
                "output_path": str(output_path),
                "freq_ghz": freq_ghz,
            },
        )
        return _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={"product_count": len(products)},
        )
