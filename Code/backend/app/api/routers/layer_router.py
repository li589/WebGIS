from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status

from app.services.coordinate_transform_service import transform_point
from app.services.demo_snapshots import get_demo_layer_snapshot, list_demo_layer_snapshots
from app.services.layer_catalog import get_layer_catalog
from app.services.workflow_request_resolver import describe_layer_run_readiness
from shared.contracts.api_contracts import (
    DemoLayerSnapshot,
    DemoLayerSnapshotsResponse,
    LayerCatalogResponse,
)

router = APIRouter()


def _mark_compat_response(response: Response, *, replacement: str, status_label: str) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["X-Compat-Status"] = status_label
    response.headers["X-Replacement-Path"] = replacement
    response.headers["Warning"] = f'299 - "Deprecated compatibility endpoint. Prefer {replacement}."'


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


@router.get("/demo/layers/snapshots", tags=["demo"], response_model=DemoLayerSnapshotsResponse)
def list_demo_snapshots(response: Response, hour: float = 12) -> DemoLayerSnapshotsResponse:
    _mark_compat_response(response, replacement="/layers + /workflow-runs", status_label="soft-offline-demo")
    return list_demo_layer_snapshots(hour)


@router.get("/demo/layers/{layer_id}/snapshot", tags=["demo"], response_model=DemoLayerSnapshot)
def get_demo_snapshot(response: Response, layer_id: str, hour: float = 12) -> DemoLayerSnapshot:
    _mark_compat_response(response, replacement="/layers + /workflow-runs/{run_id}/view", status_label="soft-offline-demo")
    snapshot = get_demo_layer_snapshot(layer_id, hour)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Demo layer not found: {layer_id}")
    return snapshot


@router.get("/geo/transform", tags=["geo"])
def transform_geo_point(lng: float, lat: float, source: str, target: str = "EPSG:3857") -> dict[str, float | str]:
    try:
        point = transform_point(lng, lat, source=source, target=target)
        return {"lng": point.lng, "lat": point.lat, "source": source, "target": target}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
