"""标量场网格渲染节点参数化基类（N1 收敛）。

露点 / 湿度 / 降水 / 气压 / 能见度 / 云量六个标量图层的网格渲染节点
共享同一 execute 骨架：输入校验 → grid_data 优先 → 单点数据回退 →
artifact 落存 → 统一错误处理。差异仅是图层标识、指标键、单位与
artifact 命名，由本基类参数化；子类薄壳只声明差异字段，必要时覆写
``_build_point_fallback`` 挂接专用单点模拟 builder。

temperature 与 wind_field 不纳入收敛：前者的 grid builder 需按
layer_id 动态解析高度层后缀（2m/80m/120m/180m），后者为矢量粒子流
渲染，均属实质渲染差异，保留独立实现（见各模块 docstring）。

service 层入口 ``build_scalar_geojson_from_grid`` /
``build_scalar_geojson_from_point`` 由 P1-4 统一，本基类收敛节点层样板。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.workflow_engine.base import BaseNode
from app.workflow_engine.enums import RunStatus
from app.workflow_engine.models import (
    ArtifactRecord,
    NodeExecutionResult,
)
from app.weatherengine.nodes._utils import (
    coerce_float,
    get_weather_engine_service,
    resolve_bbox,
)
from shared.contracts.api_contracts import ResultKind, WeatherPointResponse

logger = logging.getLogger(__name__)


def _get_result_storage_service():
    from app.services.result_storage import result_storage_service

    return result_storage_service


class ScalarGridRenderNode(BaseNode):
    """标量场网格渲染基类：统一 grid/point 双路径渲染骨架。

    子类须声明 ``node_type`` 与全部 ``_`` 前缀差异字段；point 回退走
    参数化路径（``_point_unit`` + ``_base_field``）或覆写
    ``_build_point_fallback`` 挂接专用 builder，二选一。
    """

    node_type: str = ""

    _layer_id: str = ""
    _metric_key: str = ""
    _unit: str = ""
    _skip_none: bool = False
    _min_value: float | None = None
    # 声明二者时 point 回退走 build_scalar_geojson_from_point 参数化路径。
    _point_unit: str | None = None
    _base_field: str | None = None
    # artifact 命名。
    _artifact_type: str = ""
    _result_prefix: str = ""
    _display_title: str = ""
    _node_label: str = ""

    def _build_grid_geojson(self, service: Any, grid_data: Any) -> dict[str, object]:
        return service.build_scalar_geojson_from_grid(
            grid_data,
            metric_key=self._metric_key,
            unit=self._unit,
            skip_none=self._skip_none,
            min_value=self._min_value,
        )

    def _build_point_fallback(
        self, service: Any, weather: WeatherPointResponse, bbox: Any
    ) -> dict[str, object]:
        if self._point_unit and self._base_field:
            base = float(getattr(weather.current, self._base_field, None) or 0.0)
            return service.build_scalar_geojson_from_point(
                weather,
                bbox,
                metric_key=self._metric_key,
                unit=self._point_unit,
                base_value=base,
            )
        raise NotImplementedError(
            f"{type(self).__name__} 须声明 _point_unit/_base_field 或覆写 _build_point_fallback"
        )

    def execute(self, inputs: dict[str, Any]) -> NodeExecutionResult:
        try:
            latitude = coerce_float(inputs.get("latitude"))
            longitude = coerce_float(inputs.get("longitude"))
            if latitude is None or longitude is None:
                return NodeExecutionResult(
                    node_id=self.spec.node_id,
                    status=RunStatus.failed,
                    warnings=[f"{self._node_label} 缺少必需输入: latitude/longitude"],
                )

            layer_id = inputs.get("layer_id") or self._layer_id
            weather_engine_service = get_weather_engine_service()
            grid_data = inputs.get("grid_data")
            if grid_data:
                geojson = self._build_grid_geojson(weather_engine_service, grid_data)
                logger.info(
                    "[%s] Built from grid data: layer=%s features=%d",
                    self._node_label,
                    layer_id,
                    len(geojson.get("features", [])),
                )
            else:
                bbox = resolve_bbox(inputs, latitude, longitude)
                weather_point = inputs.get("weather_point")
                if isinstance(weather_point, dict):
                    weather = WeatherPointResponse.model_validate(weather_point)
                else:
                    weather = weather_engine_service.get_point_weather(
                        layer_id=layer_id,
                        latitude=latitude,
                        longitude=longitude,
                    )
                geojson = self._build_point_fallback(
                    weather_engine_service, weather, bbox
                )
                logger.info(
                    "[%s] Built from point data (fallback): layer=%s features=%d",
                    self._node_label,
                    layer_id,
                    len(geojson.get("features", [])),
                )

            storage = _get_result_storage_service()
            run_id = self.context.metadata.get("workflow_run_id", self.context.run_id)
            artifact = None
            try:
                artifact_ref = storage.create_artifact_result_ref(
                    run_id=run_id,
                    result_id=f"{self._result_prefix}-geojson-{self.spec.node_id}",
                    result_kind=ResultKind.file,
                    title=self._display_title,
                    mime_type="application/geo+json",
                    updated_at=datetime.now(UTC),
                    payload=geojson,
                )
                artifact = ArtifactRecord(
                    artifact_id=artifact_ref.resource_key or "",
                    workflow_run_id=run_id,
                    node_id=self.spec.node_id,
                    artifact_type=self._artifact_type,
                    storage_uri=artifact_ref.resource_url or "",
                    content_type="application/geo+json",
                )
            except Exception as exc:
                logger.warning(
                    "Failed to store %s GeoJSON artifact: %s", self._result_prefix, exc
                )

            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.completed,
                outputs={"geojson": geojson},
                artifacts=[artifact] if artifact else [],
            )
        except Exception as exc:
            return NodeExecutionResult(
                node_id=self.spec.node_id,
                status=RunStatus.failed,
                warnings=[f"{self._node_label} failed: {exc}"],
            )
