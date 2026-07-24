"""Native module: Matlab A1/A2 NDVI HDF preprocess → 9 km GeoTIFF for ndvi_daily."""

from __future__ import annotations

from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from data_access import resolve_prepared_local_directory
from ingest.ndvi_hdf_preprocess import convert_ndvi_hdf_directory_to_9km
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


def _resolve_input_dir(datasource_selection: dict[str, object]) -> Path:
    prepared = resolve_prepared_local_directory(
        datasource_selection,
        ("NDVI_VIIRS", "NDVI_MODIS", "NDVI_16DAY_HDF"),
    )
    if prepared is not None:
        return prepared
    input_dir = datasource_selection.get("input_dir")
    if input_dir is None:
        raise KeyError("input_dir")
    return Path(str(input_dir))


@register_module_decorator(
    name="ndvi_hdf_preprocess",
    aliases=["ndvi_hdf_preprocess_pipeline", "a1_a2_ndvi_preprocess"],
)
class NdviHdfPreprocessModule(BaseModule):
    name = "ndvi_hdf_preprocess"
    description = (
        "Matlab A1/A2: VNP13C1/MOYD13C1 HDF → QA-masked 9 km GeoTIFF "
        "({YYYYMMDD}.tif) for ndvi_daily."
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
        PortSpec(
            name="input_dir",
            kind="value",
            data_class="string",
            required=False,
            description="VIIRS/MODIS NDVI HDF directory.",
        ),
    ]
    output_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
        PortSpec(
            name="output_dir",
            kind="value",
            data_class="string",
            required=False,
            description="9 km GeoTIFF output directory.",
        ),
    ]

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = params
        datasource_selection = dict(inputs.get("datasource_selection", {}))
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
        output_spec_extra = dict(inputs.get("output_spec_extra", {}))

        input_dir = _resolve_input_dir(datasource_selection)
        output_dir = Path(
            output_spec_extra.get(
                "output_dir",
                ctx.workspace / "products" / "ndvi_9km_tif",
            )
        )
        work_dir = Path(
            output_spec_extra.get("work_dir", output_dir / "_tmp_ndvi_hdf")
        )

        if ctx.logger_adapter is not None:
            ctx.logger_adapter.emit_stage_start(
                "ndvi_hdf_preprocess", f"Preprocess NDVI HDF from {input_dir}"
            )

        results = convert_ndvi_hdf_directory_to_9km(
            input_dir=input_dir,
            output_dir=output_dir,
            work_dir=work_dir,
        )
        product_refs = [
            ProductRef(
                name=item.output_path.stem,
                type="ndvi_9km_tif",
                uri=str(item.output_path),
                variable="NDVI",
                tags={
                    "date_key": item.output_path.stem,
                    "source_kind": item.source_kind,
                },
            )
            for item in results
        ]
        if ctx.logger_adapter is not None:
            for item in results:
                ctx.logger_adapter.emit_artifact(
                    "ndvi_hdf_preprocess",
                    str(item.output_path),
                    "ndvi_9km_tif",
                )
            ctx.logger_adapter.emit_stage_end(
                "ndvi_hdf_preprocess", f"Wrote {len(results)} 9 km GeoTIFF(s)"
            )

        manifest = ProductManifest(
            job_id=ctx.request.job_id,
            run_id=ctx.runtime_context.run_id,
            products=product_refs,
            main_layers=["NDVI"],
            metadata_uri=None,
            extra={
                "module_name": self.name,
                "input_dir": str(input_dir),
                "output_dir": str(output_dir),
                "product_count": len(product_refs),
            },
        )
        stored = _store_manifest(
            ctx,
            module_name=self.name,
            manifest=manifest,
            metadata={"output_dir": str(output_dir)},
        )
        stored["output_dir"] = str(output_dir)
        return stored
