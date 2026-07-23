"""画布参数与输出节点：data_source / 常量 / map_layer / file output。"""

from __future__ import annotations

import json
from pathlib import Path

from contracts.product import ProductManifest, ProductRef
from modules.base import BaseModule
from modules.registry import register_module_decorator
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec


def _path_manifest(
    ctx: NodeExecutionContext,
    *,
    module_name: str,
    path: str,
    product_type: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    manifest = ProductManifest(
        job_id=ctx.request.job_id,
        run_id=ctx.runtime_context.run_id,
        products=[
            ProductRef(
                name=Path(path).name or module_name,
                type=product_type,
                uri=path,
                tags={"module": module_name},
            )
        ],
        extra={"module_name": module_name, "path": path, **(extra or {})},
    )
    artifact = ArtifactRef(
        artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
        artifact_type="product_manifest",
        format="python_object",
        uri=None,
        producer_node_id=ctx.node_id,
        schema_name="ProductManifest",
        metadata={"module_name": module_name},
    )
    ctx.artifact_store.put(artifact, payload=manifest)
    return {"manifest": artifact, "path": path}


@register_module_decorator(name="data_source")
class DataSourceModule(BaseModule):
    name = "data_source"
    description = (
        "Package dataset path/URI into a datasource reference for downstream modules."
    )
    input_ports = [
        PortSpec(
            name="time_range", kind="value", data_class="time_range", required=False
        ),
        PortSpec(name="bbox", kind="geometry", data_class="bbox", required=False),
    ]
    output_ports = [
        PortSpec(name="data", kind="data", data_class="source"),
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {
        "dataset_key": "",
        "path": "",
        "pattern": "*",
        "format": "auto",
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        path = str(params.get("path") or "").strip()
        dataset_key = str(params.get("dataset_key") or "").strip()
        payload: dict[str, object] = {
            "dataset_key": dataset_key,
            "path": path,
            "input_dir": path,
            "pattern": str(params.get("pattern") or "*"),
            "format": str(params.get("format") or "auto"),
        }
        if inputs.get("time_range") is not None:
            payload["time_range"] = inputs["time_range"]
        if inputs.get("bbox") is not None:
            payload["bbox"] = inputs["bbox"]
        if dataset_key and not path:
            # Logical dataset name — leave resolution to downstream / data_access
            payload["input_dir"] = dataset_key
            path = dataset_key

        result = _path_manifest(
            ctx,
            module_name=self.name,
            path=path or dataset_key or "(empty)",
            product_type="data_source_ref",
            extra={"dataset_key": dataset_key},
        )
        result["data"] = payload
        return result


@register_module_decorator(name="time_range")
class TimeRangeModule(BaseModule):
    name = "time_range"
    description = "Emit a time_range value object."
    input_ports = []
    output_ports = [PortSpec(name="time_range", kind="value", data_class="time_range")]
    default_params = {
        "start_at": "",
        "end_at": "",
        "resolution_unit": "day",
        "resolution_step": 1,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = inputs, ctx
        return {
            "time_range": {
                "start_at": params.get("start_at"),
                "end_at": params.get("end_at"),
                "resolution_unit": params.get("resolution_unit", "day"),
                "resolution_step": params.get("resolution_step", 1),
            }
        }


@register_module_decorator(name="bbox")
class BBoxModule(BaseModule):
    name = "bbox"
    description = "Emit a bbox geometry object."
    input_ports = []
    output_ports = [PortSpec(name="bbox", kind="geometry", data_class="bbox")]
    default_params = {
        "west": 73.0,
        "south": 15.0,
        "east": 137.0,
        "north": 59.0,
        "crs": "EPSG:4326",
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = inputs, ctx
        return {
            "bbox": {
                "west": float(params.get("west", 73.0)),
                "south": float(params.get("south", 15.0)),
                "east": float(params.get("east", 137.0)),
                "north": float(params.get("north", 59.0)),
                "crs": str(params.get("crs") or "EPSG:4326"),
            }
        }


@register_module_decorator(name="number_const")
class NumberConstModule(BaseModule):
    name = "number_const"
    input_ports = []
    output_ports = [PortSpec(name="value", kind="value", data_class="number")]
    default_params = {"value": 0}

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = inputs, ctx
        return {"value": float(params.get("value", 0))}


@register_module_decorator(name="string_const")
class StringConstModule(BaseModule):
    name = "string_const"
    input_ports = []
    output_ports = [PortSpec(name="value", kind="value", data_class="string")]
    default_params = {"value": ""}

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = inputs, ctx
        return {"value": str(params.get("value") or "")}


@register_module_decorator(name="boolean_const")
class BooleanConstModule(BaseModule):
    name = "boolean_const"
    input_ports = []
    output_ports = [PortSpec(name="value", kind="value", data_class="boolean")]
    default_params = {"value": False}

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = inputs, ctx
        return {"value": bool(params.get("value", False))}


@register_module_decorator(name="latlng")
class LatLngModule(BaseModule):
    name = "latlng"
    input_ports = []
    output_ports = [PortSpec(name="point", kind="geometry", data_class="point")]
    default_params = {"latitude": 23.1, "longitude": 113.3}

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = inputs, ctx
        return {
            "point": {
                "latitude": float(params.get("latitude", 23.1)),
                "longitude": float(params.get("longitude", 113.3)),
            }
        }


@register_module_decorator(name="map_viewport")
class MapViewportModule(BaseModule):
    name = "map_viewport"
    input_ports = []
    output_ports = [PortSpec(name="bbox", kind="geometry", data_class="bbox")]
    default_params = {}

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        _ = inputs, params
        region = ctx.request.region
        if region is not None and getattr(region, "value", None):
            value = region.value if isinstance(region.value, dict) else {}
            return {"bbox": dict(value)}
        return {
            "bbox": {
                "west": -180,
                "south": -90,
                "east": 180,
                "north": 90,
                "crs": "EPSG:4326",
            }
        }


@register_module_decorator(name="output_map_layer")
class OutputMapLayerModule(BaseModule):
    name = "output_map_layer"
    description = "Register upstream path/data as a map_layer product manifest."
    input_ports = [
        PortSpec(name="data", kind="data", data_class="any", required=False),
        PortSpec(name="path", kind="value", data_class="string", required=False),
        PortSpec(
            name="manifest",
            kind="artifact",
            data_class="product_manifest",
            required=False,
        ),
    ]
    output_ports = [
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
        PortSpec(name="map_layer", kind="data", data_class="layer"),
    ]
    default_params = {"layer_id": "", "display_name": ""}

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        if inputs.get("manifest") is not None:
            artifact = inputs["manifest"]
            map_layer = {
                "layer_id": str(params.get("layer_id") or ""),
                "display_name": str(params.get("display_name") or ""),
                "source": "upstream_manifest",
            }
            return {"manifest": artifact, "map_layer": map_layer}

        path = None
        data = inputs.get("data")
        if isinstance(data, dict):
            path = data.get("path") or data.get("input_dir") or data.get("uri")
        path = path or inputs.get("path")
        if not path:
            raise ValueError("output_map_layer requires data/path or upstream manifest")

        layer_id = str(params.get("layer_id") or Path(str(path)).stem)
        display_name = str(params.get("display_name") or layer_id)
        map_layer = {
            "layer_id": layer_id,
            "display_name": display_name,
            "uri": str(path),
            "path": str(path),
        }
        result = _path_manifest(
            ctx,
            module_name=self.name,
            path=str(path),
            product_type="map_layer",
            extra={"layer_id": layer_id, "display_name": display_name},
        )
        result["map_layer"] = map_layer
        return result


@register_module_decorator(name="output_file")
class OutputFileModule(BaseModule):
    name = "output_file"
    description = "Copy or serialize upstream data to a named output file."
    input_ports = [
        PortSpec(name="data", kind="data", data_class="any", required=False),
        PortSpec(name="path", kind="value", data_class="string", required=False),
        PortSpec(
            name="manifest",
            kind="artifact",
            data_class="product_manifest",
            required=False,
        ),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"format": "json", "filename": "output"}

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        fmt = str(params.get("format") or "json")
        filename = str(params.get("filename") or "output")
        out_dir = Path(ctx.workspace) / "products" / "files"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{filename}.{fmt}"

        src = inputs.get("path")
        data = inputs.get("data")
        if src and Path(str(src)).exists():
            import shutil

            shutil.copy2(str(src), out_path)
        elif isinstance(data, dict):
            out_path = out_path.with_suffix(".json")
            out_path.write_text(
                json.dumps(data, default=str, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif inputs.get("manifest") is not None:
            out_path.write_text(
                json.dumps({"manifest_ref": str(inputs["manifest"])}, default=str),
                encoding="utf-8",
            )
        else:
            raise ValueError("output_file requires data/path/manifest input")

        return _path_manifest(
            ctx, module_name=self.name, path=str(out_path), product_type="output_file"
        )
