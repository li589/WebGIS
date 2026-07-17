from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.services.coordinate_transform_service import transform_point
from app.services.layer_catalog import get_layer_catalog
from app.services.overlay_registry import (
    get_overlay_spec,
    list_overlay_ids,
    read_bounds,
    read_png_bytes,
)
from app.services.workflow_request_resolver import describe_layer_run_readiness
from shared.contracts.api_contracts import (
    LayerCatalogResponse,
)

router = APIRouter()


@router.get("/layers", tags=["catalog"], response_model=LayerCatalogResponse)
def list_layers() -> LayerCatalogResponse:
    catalog = get_layer_catalog()

    def _check_readiness(item) -> tuple[str, dict]:
        readiness = describe_layer_run_readiness(item.layer_id) or {}
        return item.layer_id, readiness

    layer_readiness: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_check_readiness, desc): desc for desc in catalog.items}
        for future in as_completed(futures):
            layer_id, readiness = future.result()
            layer_readiness[layer_id] = readiness

    items = []
    for descriptor in catalog.items:
        readiness = layer_readiness.get(descriptor.layer_id, {})
        items.append(
            descriptor.model_copy(
                update={
                    "run_readiness": readiness.get("run_readiness", descriptor.run_readiness),
                    "run_readiness_summary": readiness.get("run_readiness_summary", descriptor.run_readiness_summary),
                    "run_readiness_notes": readiness.get("run_readiness_notes", descriptor.run_readiness_notes),
                }
            )
        )
    return LayerCatalogResponse(items=items)


@router.get("/geo/transform", tags=["geo"])
def transform_geo_point(lng: float, lat: float, source: str, target: str = "EPSG:3857") -> dict[str, float | str]:
    try:
        point = transform_point(lng, lat, source=source, target=target)
        return {"lng": point.lng, "lat": point.lat, "source": source, "target": target}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/overlay-preview/{layer_id}", tags=["overlay"])
def get_overlay_preview(layer_id: str, time: str | None = Query(default=None)) -> Response:
    """返回图层的 PNG 预览图（地理配准），供前端 MapLibre image source 使用。

    对于时间序列图层，可通过 `?time=YYYYMMDD` 指定时间标签；
    未指定时使用 default_time。
    """
    return Response(
        content=read_png_bytes(layer_id, time),
        media_type="image/png",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@router.get("/overlay-bounds/{layer_id}", tags=["overlay"])
def get_overlay_bounds(
    layer_id: str,
    time: str | None = Query(default=None),
) -> dict[str, Any]:
    """返回图层的地理边界信息 + 元数据，供前端 MapLibre image source 定位与时间控制使用。"""
    return read_bounds(layer_id, time)


@router.get("/overlays", tags=["overlay"])
def list_overlays() -> dict[str, Any]:
    """列出所有已注册的叠加图层 ID（供前端发现可用 overlay 图层）。"""
    return {"overlay_layer_ids": list_overlay_ids()}


@router.get("/overlay-value/{layer_id}", tags=["overlay"])
def get_overlay_value(
    layer_id: str,
    lng: float = Query(...),
    lat: float = Query(...),
    time: str | None = Query(default=None),
) -> dict[str, Any]:
    """查询 overlay 图层在指定点 (lng, lat) 的像素值。

    对于时间序列图层，可通过 ?time=YYYYMMDD 指定时间标签。
    返回 {"value": float | null, "unit": str, "layer_id": str, ...}。
    """
    spec = get_overlay_spec(layer_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No overlay for layer: {layer_id}")
    return spec.resolve_value(lng, lat, time)
