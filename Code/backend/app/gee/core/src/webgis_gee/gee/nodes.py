from __future__ import annotations

from contextlib import contextmanager
import json
import logging
from typing import Any

from webgis_gee.domain.enums import PortKind
from webgis_gee.domain.models import (
    ArtifactRecord,
    ExecutionContext,
    NodeExecutionResult,
    NodeSpec,
    PortSpec,
    RunStatus,
)
from webgis_gee.nodes.base import BaseNode
from webgis_gee.runtime.observability import (
    InMemoryMetricsCollector,
    StructuredEventSink,
    log_structured_event,
)
from webgis_gee.runtime.resources import RuntimeResourceController
from webgis_gee.storage.base import StorageBackend
from webgis_gee.storage.factory import create_storage_backend


logger = logging.getLogger(__name__)


class GeeImageNode(BaseNode):
    node_type = "gee_image"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_image",
            node_type=GeeImageNode.node_type,
            params={
                "asset_id": "COPERNICUS/S2_SR_HARMONIZED/20230101T000000_20230101T000000_T50SMJ"
            },
            output_ports=[PortSpec(name="image", kind=PortKind.VALUE)],
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        asset_id = inputs.get("asset_id") or self.spec.params.get("asset_id")
        try:
            ee = _resolve_gee_module(self.context)
            if ee is None:
                ee = __import__("ee")
            image = ee.Image(asset_id)
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                outputs={"image": image},
            )
        except Exception as e:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                outputs={},
                warnings=[f"GEE image load failed: {str(e)}"],
            )


class GeeCloudMaskNode(BaseNode):
    node_type = "gee_cloud_mask"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_cloud_mask",
            node_type=GeeCloudMaskNode.node_type,
            input_ports=[PortSpec(name="image", kind=PortKind.VALUE)],
            output_ports=[PortSpec(name="masked", kind=PortKind.VALUE)],
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        image = inputs.get("image")
        if image is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                outputs={},
                warnings=["No image input provided for cloud mask"],
            )
        try:
            # 这是Sentinel-2云掩膜的简单示例，实际可以扩展为支持更多传感器
            qa = image.select("QA60")
            mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
            masked = image.updateMask(mask)
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                outputs={"masked": masked},
            )
        except Exception as e:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                outputs={},
                warnings=[f"Cloud mask failed: {str(e)}"],
            )


class GeeClipNode(BaseNode):
    node_type = "gee_clip"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_clip",
            node_type=GeeClipNode.node_type,
            input_ports=[
                PortSpec(name="image", kind=PortKind.VALUE),
                PortSpec(name="geometry", kind=PortKind.VALUE),
            ],
            output_ports=[PortSpec(name="clipped", kind=PortKind.VALUE)],
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        image = inputs.get("image")
        geometry = inputs.get("geometry")
        if image is None or geometry is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                outputs={},
                warnings=["Missing image or geometry input for clip"],
            )
        try:
            clipped = image.clip(geometry)
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                outputs={"clipped": clipped},
            )
        except Exception as e:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                outputs={},
                warnings=[f"Clip failed: {str(e)}"],
            )


class GeeSelectBandsNode(BaseNode):
    node_type = "gee_select_bands"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_select_bands",
            node_type=GeeSelectBandsNode.node_type,
            input_ports=[PortSpec(name="image", kind=PortKind.IMAGE)],
            output_ports=[PortSpec(name="image", kind=PortKind.IMAGE)],
            params={
                "bands": [],
                "rename": None,
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        image = inputs.get("image")
        bands = inputs.get("bands", self.spec.params.get("bands", []))
        rename = inputs.get("rename", self.spec.params.get("rename"))
        if image is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing image input for band selection"],
            )
        if (
            not isinstance(bands, list)
            or not bands
            or any(not isinstance(band, str) or not band for band in bands)
        ):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["gee_select_bands bands must be a non-empty string list"],
            )
        if rename is not None:
            if not isinstance(rename, list) or len(rename) != len(bands):
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.FAILED,
                    warnings=["gee_select_bands rename must match bands length"],
                )
        try:
            selected = (
                image.select(bands, rename)
                if rename is not None
                else image.select(bands)
            )
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                outputs={"image": selected},
            )
        except Exception as e:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[f"Band selection failed: {str(e)}"],
            )


class GeeSpectralIndexNode(BaseNode):
    node_type = "gee_spectral_index"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_spectral_index",
            node_type=GeeSpectralIndexNode.node_type,
            input_ports=[PortSpec(name="image", kind=PortKind.IMAGE)],
            output_ports=[PortSpec(name="index_image", kind=PortKind.IMAGE)],
            params={
                "index": "ndvi",
                "nir_band": "B8",
                "red_band": "B4",
                "green_band": "B3",
                "swir_band": "B11",
                "output_band": None,
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        image = inputs.get("image")
        if image is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing image input for spectral index"],
            )

        index_name = str(
            inputs.get("index", self.spec.params.get("index", "ndvi"))
        ).lower()
        output_band = (
            inputs.get("output_band", self.spec.params.get("output_band")) or index_name
        )
        if not isinstance(output_band, str) or not output_band:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["gee_spectral_index output_band must be a non-empty string"],
            )

        try:
            left_band, right_band = self._resolve_index_bands(
                index_name=index_name, inputs=inputs
            )
        except ValueError as exc:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[str(exc)],
            )

        try:
            index_image = image.normalizedDifference([left_band, right_band]).rename(
                output_band
            )
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                outputs={"index_image": index_image},
            )
        except Exception as e:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[f"Spectral index failed: {str(e)}"],
            )

    def _resolve_index_bands(
        self, *, index_name: str, inputs: dict[str, Any]
    ) -> tuple[str, str]:
        if index_name == "ndvi":
            return (
                str(inputs.get("nir_band", self.spec.params.get("nir_band", "B8"))),
                str(inputs.get("red_band", self.spec.params.get("red_band", "B4"))),
            )
        if index_name == "ndwi":
            return (
                str(inputs.get("green_band", self.spec.params.get("green_band", "B3"))),
                str(inputs.get("nir_band", self.spec.params.get("nir_band", "B8"))),
            )
        if index_name == "ndmi":
            return (
                str(inputs.get("nir_band", self.spec.params.get("nir_band", "B8"))),
                str(inputs.get("swir_band", self.spec.params.get("swir_band", "B11"))),
            )
        raise ValueError(
            "gee_spectral_index index must be one of 'ndvi', 'ndwi', 'ndmi'"
        )


class GeeRasterAlgebraNode(BaseNode):
    node_type = "gee_raster_algebra"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_raster_algebra",
            node_type=GeeRasterAlgebraNode.node_type,
            input_ports=[PortSpec(name="image", kind=PortKind.IMAGE)],
            output_ports=[PortSpec(name="image", kind=PortKind.IMAGE)],
            parameter_aliases={"variables": "band_map"},
            params={
                "expression": "",
                "band_map": {},
                "output_band": None,
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        image = inputs.get("image")
        expression = inputs.get("expression", self.spec.params.get("expression", ""))
        band_map = inputs.get("band_map", self.spec.params.get("band_map", {}))
        output_band = inputs.get("output_band", self.spec.params.get("output_band"))
        if image is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing image input for raster algebra"],
            )
        if not isinstance(expression, str) or not expression.strip():
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["gee_raster_algebra expression must be a non-empty string"],
            )
        if not isinstance(band_map, dict) or not band_map:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["gee_raster_algebra band_map must be a non-empty mapping"],
            )
        if any(
            not isinstance(variable, str)
            or not variable
            or not isinstance(band_name, str)
            or not band_name
            for variable, band_name in band_map.items()
        ):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[
                    "gee_raster_algebra band_map keys and values must be non-empty strings"
                ],
            )
        if not isinstance(output_band, str) or not output_band:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["gee_raster_algebra output_band must be a non-empty string"],
            )

        try:
            variables = {
                variable: image.select([band_name])
                for variable, band_name in band_map.items()
            }
            algebra_image = image.expression(expression, variables).rename(output_band)
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                outputs={"image": algebra_image},
            )
        except Exception as e:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[f"Raster algebra failed: {str(e)}"],
            )


class GeeThresholdClassifyNode(BaseNode):
    node_type = "gee_threshold_classify"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_threshold_classify",
            node_type=GeeThresholdClassifyNode.node_type,
            input_ports=[PortSpec(name="image", kind=PortKind.IMAGE)],
            output_ports=[PortSpec(name="image", kind=PortKind.IMAGE)],
            parameter_aliases={"classes": "class_values"},
            params={
                "band": None,
                "thresholds": [],
                "class_values": [],
                "output_band": None,
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        image = inputs.get("image")
        band = inputs.get("band", self.spec.params.get("band"))
        thresholds = inputs.get("thresholds", self.spec.params.get("thresholds", []))
        class_values = inputs.get(
            "class_values", self.spec.params.get("class_values", [])
        )
        output_band = inputs.get("output_band", self.spec.params.get("output_band"))
        if image is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing image input for threshold classify"],
            )
        if not isinstance(band, str) or not band:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["gee_threshold_classify band must be a non-empty string"],
            )
        if (
            not isinstance(thresholds, list)
            or not thresholds
            or any(not isinstance(value, (int, float)) for value in thresholds)
        ):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[
                    "gee_threshold_classify thresholds must be a non-empty numeric list"
                ],
            )
        if any(
            thresholds[index] >= thresholds[index + 1]
            for index in range(len(thresholds) - 1)
        ):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[
                    "gee_threshold_classify thresholds must be strictly ascending"
                ],
            )
        if (
            not isinstance(class_values, list)
            or len(class_values) != len(thresholds) + 1
            or any(not isinstance(value, (int, float)) for value in class_values)
        ):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[
                    "gee_threshold_classify class_values must be a numeric list with len(thresholds) + 1 items"
                ],
            )
        if not isinstance(output_band, str) or not output_band:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[
                    "gee_threshold_classify output_band must be a non-empty string"
                ],
            )

        try:
            selected = image.select([band])
            classified = selected.multiply(0).add(class_values[0])
            for threshold, class_value in zip(thresholds, class_values[1:]):
                classified = classified.where(selected.gte(threshold), class_value)
            classified = classified.rename(output_band)
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                outputs={"image": classified},
            )
        except Exception as e:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[f"Threshold classify failed: {str(e)}"],
            )


class GeeReclassifyNode(BaseNode):
    node_type = "gee_reclassify"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_reclassify",
            node_type=GeeReclassifyNode.node_type,
            input_ports=[PortSpec(name="image", kind=PortKind.IMAGE)],
            output_ports=[PortSpec(name="image", kind=PortKind.IMAGE)],
            parameter_aliases={"fallback_value": "default_value"},
            params={
                "band": None,
                "rules": [],
                "default_value": 0,
                "output_band": None,
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        image = inputs.get("image")
        band = inputs.get("band", self.spec.params.get("band"))
        rules = inputs.get("rules", self.spec.params.get("rules", []))
        default_value = inputs.get(
            "default_value", self.spec.params.get("default_value", 0)
        )
        output_band = inputs.get("output_band", self.spec.params.get("output_band"))
        if image is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing image input for reclassify"],
            )
        if not isinstance(band, str) or not band:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["gee_reclassify band must be a non-empty string"],
            )
        if not isinstance(rules, list) or not rules:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["gee_reclassify rules must be a non-empty list"],
            )
        if not isinstance(default_value, (int, float)):
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["gee_reclassify default_value must be numeric"],
            )
        if not isinstance(output_band, str) or not output_band:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["gee_reclassify output_band must be a non-empty string"],
            )

        validated_rules: list[dict[str, float]] = []
        try:
            for rule in rules:
                validated_rules.append(self._validate_rule(rule))
        except ValueError as exc:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[str(exc)],
            )

        try:
            selected = image.select([band])
            classified = selected.multiply(0).add(default_value)
            for rule in validated_rules:
                if "match" in rule:
                    condition = selected.eq(rule["match"])
                else:
                    condition = selected.gte(rule["min"]).And(selected.lte(rule["max"]))
                classified = classified.where(condition, rule["value"])
            classified = classified.rename(output_band)
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                outputs={"image": classified},
            )
        except Exception as e:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[f"Reclassify failed: {str(e)}"],
            )

    @staticmethod
    def _validate_rule(rule: Any) -> dict[str, float]:
        if not isinstance(rule, dict):
            raise ValueError("gee_reclassify rules must contain mapping items")
        if not isinstance(rule.get("value"), (int, float)):
            raise ValueError("gee_reclassify each rule must include numeric value")
        if "match" in rule:
            if not isinstance(rule["match"], (int, float)):
                raise ValueError("gee_reclassify match rule must include numeric match")
            return {"match": float(rule["match"]), "value": float(rule["value"])}
        if "min" in rule and "max" in rule:
            if not isinstance(rule["min"], (int, float)) or not isinstance(
                rule["max"], (int, float)
            ):
                raise ValueError(
                    "gee_reclassify range rule must include numeric min and max"
                )
            if float(rule["min"]) > float(rule["max"]):
                raise ValueError("gee_reclassify range rule min must be <= max")
            return {
                "min": float(rule["min"]),
                "max": float(rule["max"]),
                "value": float(rule["value"]),
            }
        raise ValueError("gee_reclassify each rule must define either match or min/max")


class GeeImageCollectionCompositeNode(BaseNode):
    node_type = "gee_image_collection_composite"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_image_collection_composite",
            node_type=GeeImageCollectionCompositeNode.node_type,
            input_ports=[PortSpec(name="collection", kind=PortKind.IMAGE_COLLECTION)],
            output_ports=[PortSpec(name="image", kind=PortKind.IMAGE)],
            params={"reducer": "median"},
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        collection = inputs.get("collection")
        reducer = str(
            inputs.get("reducer", self.spec.params.get("reducer", "median"))
        ).lower()
        if collection is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing collection input for composite"],
            )
        if reducer not in {"median", "mean", "mosaic"}:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[
                    "gee_image_collection_composite reducer must be 'median', 'mean' or 'mosaic'"
                ],
            )
        try:
            composite = getattr(collection, reducer)()
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                outputs={"image": composite},
            )
        except Exception as e:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[f"Image collection composite failed: {str(e)}"],
            )


class GeeRegionStatsNode(BaseNode):
    node_type = "gee_region_stats"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_region_stats",
            node_type=GeeRegionStatsNode.node_type,
            input_ports=[
                PortSpec(name="image", kind=PortKind.IMAGE),
                PortSpec(name="geometry", kind=PortKind.GEOMETRY),
            ],
            output_ports=[PortSpec(name="stats", kind=PortKind.VALUE)],
            params={
                "reducer": "mean",
                "scale": 30,
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        image = inputs.get("image")
        geometry = inputs.get("geometry")
        reducer_name = str(
            inputs.get("reducer", self.spec.params.get("reducer", "mean"))
        ).lower()
        scale = inputs.get("scale", self.spec.params.get("scale", 30))
        if image is None or geometry is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing image or geometry input for region stats"],
            )
        if reducer_name not in {"mean", "sum", "min", "max", "median", "count"}:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[
                    "gee_region_stats reducer must be one of 'mean', 'sum', 'min', 'max', 'median', 'count'"
                ],
            )
        try:
            reducer = _resolve_reducer(self.context, reducer_name)
            stats = image.reduceRegion(
                reducer=reducer,
                geometry=geometry,
                scale=scale,
            )
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                outputs={"stats": stats},
            )
        except Exception as e:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[f"Region stats failed: {str(e)}"],
            )


class GeeTimeSeriesStatsNode(BaseNode):
    node_type = "gee_time_series_stats"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_time_series_stats",
            node_type=GeeTimeSeriesStatsNode.node_type,
            input_ports=[
                PortSpec(name="collection", kind=PortKind.IMAGE_COLLECTION),
                PortSpec(name="geometry", kind=PortKind.GEOMETRY),
            ],
            output_ports=[PortSpec(name="series", kind=PortKind.VALUE)],
            parameter_aliases={
                "date_field": "date_property",
                "value_field": "value_property",
            },
            params={
                "reducer": "mean",
                "scale": 30,
                "band": None,
                "date_property": "system:time_start",
                "value_property": "__gee_ts_value__",
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        collection = inputs.get("collection")
        geometry = inputs.get("geometry")
        reducer_name = str(
            inputs.get("reducer", self.spec.params.get("reducer", "mean"))
        ).lower()
        scale = inputs.get("scale", self.spec.params.get("scale", 30))
        band = inputs.get("band", self.spec.params.get("band"))
        date_property = str(
            inputs.get(
                "date_property",
                self.spec.params.get("date_property", "system:time_start"),
            )
        )
        value_property = str(
            inputs.get(
                "value_property",
                self.spec.params.get("value_property", "__gee_ts_value__"),
            )
        )
        if collection is None or geometry is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing collection or geometry input for time series stats"],
            )
        if reducer_name not in {"mean", "sum", "min", "max", "median", "count"}:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[
                    "gee_time_series_stats reducer must be one of 'mean', 'sum', 'min', 'max', 'median', 'count'"
                ],
            )
        if not isinstance(band, str) or not band:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["gee_time_series_stats band must be a non-empty string"],
            )
        try:
            reducer = _resolve_reducer(self.context, reducer_name)
            enriched_collection = collection.map(
                lambda image: image.set(
                    value_property,
                    image.select([band])
                    .reduceRegion(
                        reducer=reducer,
                        geometry=geometry,
                        scale=scale,
                    )
                    .get(band),
                )
            )
            series = {
                "date_property": date_property,
                "value_property": value_property,
                "band": band,
                "reducer": reducer_name,
                "dates": enriched_collection.aggregate_array(date_property),
                "values": enriched_collection.aggregate_array(value_property),
            }
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                outputs={"series": series},
            )
        except Exception as e:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=[f"Time series stats failed: {str(e)}"],
            )


class GeeExportImageNode(BaseNode):
    node_type = "gee_export_image"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_export_image",
            node_type=GeeExportImageNode.node_type,
            input_ports=[PortSpec(name="image", kind=PortKind.VALUE)],
            output_ports=[
                PortSpec(name="task_ref", kind=PortKind.VALUE),
                PortSpec(name="manifest_uri", kind=PortKind.ARTIFACT),
            ],
            parameter_aliases={
                "task_name": "description",
                "file_prefix": "file_name_prefix",
                "auto_start": "start_task",
                "bucket_name": "bucket",
            },
            params={
                "destination": "manifest",
                "description": "gee-export-image",
                "file_name_prefix": "gee_export_image",
                "scale": 10,
                "start_task": False,
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        image = inputs.get("image")
        if image is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing image input for export"],
            )

        storage_backend = _resolve_storage_backend(self.context)
        destination = inputs.get(
            "destination", self.spec.params.get("destination", "manifest")
        )
        description = inputs.get(
            "description", self.spec.params.get("description", self.spec.node_id)
        )
        file_name_prefix = inputs.get(
            "file_name_prefix",
            self.spec.params.get("file_name_prefix", self.spec.node_id),
        )
        scale = inputs.get("scale", self.spec.params.get("scale", 10))
        bucket = inputs.get("bucket", self.spec.params.get("bucket"))
        start_task = bool(
            inputs.get("start_task", self.spec.params.get("start_task", False))
        )

        task_ref: dict[str, Any] = {
            "destination": destination,
            "description": description,
            "file_name_prefix": file_name_prefix,
            "scale": scale,
            "started": False,
            "status": "manifest_created",
        }
        warnings: list[str] = []
        node_status = RunStatus.COMPLETED

        ee_module = _resolve_gee_module(self.context)
        if start_task and ee_module is not None:
            try:
                with _export_slot(self.context):
                    task = _create_image_export_task(
                        ee_module=ee_module,
                        image=image,
                        destination=destination,
                        description=description,
                        file_name_prefix=file_name_prefix,
                        scale=scale,
                        bucket=bucket,
                        region=inputs.get("region"),
                        asset_id=inputs.get("asset_id"),
                    )
                    if hasattr(task, "start"):
                        task.start()
                    task_ref["started"] = True
                    task_ref["task_id"] = getattr(task, "id", None)
                    task_ref["status"] = "submitted"
                    _metrics_increment(self.context, "export.submit.started")
                    _metrics_increment(self.context, "export.submit.completed")
                    log_structured_event(
                        logger,
                        logging.INFO,
                        "export.submit.completed",
                        sink=_resolve_event_sink(self.context),
                        run_id=self.context.run_id,
                        workflow_id=self.context.workflow_id,
                        account_id=self.context.account_id,
                        node_id=self.spec.node_id,
                        destination=destination,
                        task_id=task_ref["task_id"],
                        resource_slots=_resource_slots_snapshot(self.context),
                    )
            except Exception as exc:
                task_ref["status"] = "submit_failed"
                warnings.append(f"Image export task creation failed: {exc}")
                node_status = RunStatus.FAILED
                _metrics_increment(self.context, "export.submit.failed")
                log_structured_event(
                    logger,
                    logging.WARNING,
                    "export.submit.failed",
                    sink=_resolve_event_sink(self.context),
                    run_id=self.context.run_id,
                    workflow_id=self.context.workflow_id,
                    account_id=self.context.account_id,
                    node_id=self.spec.node_id,
                    destination=destination,
                    error=str(exc),
                    resource_slots=_resource_slots_snapshot(self.context),
                )

        payload = {
            "node_type": self.node_type,
            "workflow_id": self.context.workflow_id,
            "run_id": self.context.run_id,
            "destination": destination,
            "task_ref": task_ref,
        }
        artifact = _write_manifest_artifact(
            context=self.context,
            node_id=self.spec.node_id,
            file_name=f"{file_name_prefix}.json",
            payload=payload,
            storage_backend=storage_backend,
            artifact_type="gee_export_manifest",
        )
        task_ref["manifest_uri"] = artifact.storage_uri
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            status=node_status,
            outputs={"task_ref": task_ref, "manifest_uri": artifact.storage_uri},
            artifacts=[artifact],
            warnings=warnings,
        )


class GeeExportTableNode(BaseNode):
    node_type = "gee_export_table"

    @staticmethod
    def build_spec() -> NodeSpec:
        return NodeSpec(
            node_id="gee_export_table",
            node_type=GeeExportTableNode.node_type,
            input_ports=[PortSpec(name="collection", kind=PortKind.FEATURE_COLLECTION)],
            output_ports=[
                PortSpec(name="task_ref", kind=PortKind.VALUE),
                PortSpec(name="manifest_uri", kind=PortKind.ARTIFACT),
            ],
            parameter_aliases={
                "task_name": "description",
                "file_prefix": "file_name_prefix",
                "auto_start": "start_task",
                "bucket_name": "bucket",
            },
            params={
                "destination": "manifest",
                "description": "gee-export-table",
                "file_name_prefix": "gee_export_table",
                "start_task": False,
            },
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        collection = inputs.get("collection")
        if collection is None:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.FAILED,
                warnings=["Missing collection input for export"],
            )

        storage_backend = _resolve_storage_backend(self.context)
        destination = inputs.get(
            "destination", self.spec.params.get("destination", "manifest")
        )
        description = inputs.get(
            "description", self.spec.params.get("description", self.spec.node_id)
        )
        file_name_prefix = inputs.get(
            "file_name_prefix",
            self.spec.params.get("file_name_prefix", self.spec.node_id),
        )
        bucket = inputs.get("bucket", self.spec.params.get("bucket"))
        start_task = bool(
            inputs.get("start_task", self.spec.params.get("start_task", False))
        )

        task_ref: dict[str, Any] = {
            "destination": destination,
            "description": description,
            "file_name_prefix": file_name_prefix,
            "started": False,
            "status": "manifest_created",
        }
        warnings: list[str] = []
        node_status = RunStatus.COMPLETED

        ee_module = _resolve_gee_module(self.context)
        if start_task and ee_module is not None:
            try:
                with _export_slot(self.context):
                    task = _create_table_export_task(
                        ee_module=ee_module,
                        collection=collection,
                        destination=destination,
                        description=description,
                        file_name_prefix=file_name_prefix,
                        bucket=bucket,
                    )
                    if hasattr(task, "start"):
                        task.start()
                    task_ref["started"] = True
                    task_ref["task_id"] = getattr(task, "id", None)
                    task_ref["status"] = "submitted"
                    _metrics_increment(self.context, "export.submit.started")
                    _metrics_increment(self.context, "export.submit.completed")
                    log_structured_event(
                        logger,
                        logging.INFO,
                        "export.submit.completed",
                        sink=_resolve_event_sink(self.context),
                        run_id=self.context.run_id,
                        workflow_id=self.context.workflow_id,
                        account_id=self.context.account_id,
                        node_id=self.spec.node_id,
                        destination=destination,
                        task_id=task_ref["task_id"],
                        resource_slots=_resource_slots_snapshot(self.context),
                    )
            except Exception as exc:
                task_ref["status"] = "submit_failed"
                warnings.append(f"Table export task creation failed: {exc}")
                node_status = RunStatus.FAILED
                _metrics_increment(self.context, "export.submit.failed")
                log_structured_event(
                    logger,
                    logging.WARNING,
                    "export.submit.failed",
                    sink=_resolve_event_sink(self.context),
                    run_id=self.context.run_id,
                    workflow_id=self.context.workflow_id,
                    account_id=self.context.account_id,
                    node_id=self.spec.node_id,
                    destination=destination,
                    error=str(exc),
                    resource_slots=_resource_slots_snapshot(self.context),
                )

        payload = {
            "node_type": self.node_type,
            "workflow_id": self.context.workflow_id,
            "run_id": self.context.run_id,
            "destination": destination,
            "task_ref": task_ref,
        }
        artifact = _write_manifest_artifact(
            context=self.context,
            node_id=self.spec.node_id,
            file_name=f"{file_name_prefix}.json",
            payload=payload,
            storage_backend=storage_backend,
            artifact_type="gee_export_manifest",
        )
        task_ref["manifest_uri"] = artifact.storage_uri
        return NodeExecutionResult(
            node_id=self.spec.node_id,
            status=node_status,
            outputs={"task_ref": task_ref, "manifest_uri": artifact.storage_uri},
            artifacts=[artifact],
            warnings=warnings,
        )


def _resolve_gee_module(context: ExecutionContext) -> Any | None:
    gee_module = context.metadata.get("gee_module")
    if gee_module is not None:
        return gee_module

    gee_context = context.metadata.get("gee_context")
    if gee_context is not None:
        return gee_context.ee
    return None


def _resolve_storage_backend(context: ExecutionContext) -> StorageBackend:
    backend = context.metadata.get("storage_backend")
    if backend is not None:
        return backend
    return create_storage_backend()


def _resolve_reducer(context: ExecutionContext, reducer_name: str) -> Any:
    gee_module = _resolve_gee_module(context)
    if gee_module is not None and hasattr(gee_module, "Reducer"):
        reducer_factory = getattr(gee_module.Reducer, reducer_name, None)
        if callable(reducer_factory):
            return reducer_factory()
    return reducer_name


def _resolve_resource_controller(
    context: ExecutionContext,
) -> RuntimeResourceController | None:
    controller = context.metadata.get("resource_controller")
    if isinstance(controller, RuntimeResourceController):
        return controller
    return None


def _export_slot(context: ExecutionContext):
    controller = _resolve_resource_controller(context)
    if controller is None:
        return _noop_context_manager()
    return controller.export_slot()


def _resolve_metrics_collector(
    context: ExecutionContext,
) -> InMemoryMetricsCollector | None:
    collector = context.metadata.get("metrics_collector")
    if isinstance(collector, InMemoryMetricsCollector):
        return collector
    return None


def _resolve_event_sink(context: ExecutionContext) -> StructuredEventSink | None:
    sink = context.metadata.get("event_sink")
    if isinstance(sink, StructuredEventSink):
        return sink
    return None


def _metrics_increment(context: ExecutionContext, name: str) -> None:
    collector = _resolve_metrics_collector(context)
    if collector is not None:
        collector.increment(name)


def _resource_slots_snapshot(context: ExecutionContext) -> dict[str, int] | None:
    controller = _resolve_resource_controller(context)
    if controller is None:
        return None
    snapshot = controller.snapshot()
    return {
        "active_export_slots": int(snapshot["active_export_slots"]),
        "available_export_slots": int(snapshot["available_export_slots"]),
    }


def _write_manifest_artifact(
    context: ExecutionContext,
    node_id: str,
    file_name: str,
    payload: dict[str, Any],
    storage_backend: StorageBackend,
    artifact_type: str,
) -> ArtifactRecord:
    path = f"exports/{context.workflow_id}/{context.run_id}/{node_id}/{file_name}"
    storage_uri = storage_backend.put(
        path, json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
    )
    return ArtifactRecord(
        workflow_run_id=context.run_id,
        node_id=node_id,
        artifact_type=artifact_type,
        storage_uri=storage_uri,
        content_type="application/json",
        size=len(json.dumps(payload, ensure_ascii=True).encode("utf-8")),
        metadata={"path": path},
    )


@contextmanager
def _noop_context_manager():
    yield


def _create_image_export_task(
    ee_module: Any,
    image: Any,
    destination: str,
    description: str,
    file_name_prefix: str,
    scale: int,
    bucket: str | None,
    region: Any,
    asset_id: str | None,
) -> Any:
    export_kwargs = {
        "image": image,
        "description": description,
        "fileNamePrefix": file_name_prefix,
        "scale": scale,
    }
    if region is not None:
        export_kwargs["region"] = region

    if destination == "cloud_storage":
        if not bucket:
            raise ValueError("cloud_storage export requires bucket")
        export_kwargs["bucket"] = bucket
        return ee_module.batch.Export.image.toCloudStorage(**export_kwargs)
    if destination == "drive":
        return ee_module.batch.Export.image.toDrive(**export_kwargs)
    if destination == "asset":
        if not asset_id:
            raise ValueError("asset export requires asset_id")
        export_kwargs["assetId"] = asset_id
        return ee_module.batch.Export.image.toAsset(**export_kwargs)
    raise ValueError(f"unsupported image export destination: {destination}")


def _create_table_export_task(
    ee_module: Any,
    collection: Any,
    destination: str,
    description: str,
    file_name_prefix: str,
    bucket: str | None,
) -> Any:
    export_kwargs = {
        "collection": collection,
        "description": description,
        "fileNamePrefix": file_name_prefix,
    }
    if destination == "cloud_storage":
        if not bucket:
            raise ValueError("cloud_storage export requires bucket")
        export_kwargs["bucket"] = bucket
        return ee_module.batch.Export.table.toCloudStorage(**export_kwargs)
    if destination == "drive":
        return ee_module.batch.Export.table.toDrive(**export_kwargs)
    raise ValueError(f"unsupported table export destination: {destination}")
