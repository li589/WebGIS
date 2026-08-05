from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
    TimeoutError as FuturesTimeoutError,
)
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.core.config import settings
from app.services.crs import crs_transformer
from app.services.crs.crs_registry import normalize_crs_code
from app.services.layer_catalog import get_layer_catalog
from app.services.overlay_registry import (
    get_overlay_spec,
    list_overlay_ids,
    read_bounds,
)
from app.services.workflow_request_resolver import describe_layer_run_readiness
from shared.contracts.api_contracts import (
    LayerCatalogResponse,
)

_logger = logging.getLogger(__name__)

router = APIRouter()

_READINESS_TIMEOUT = 8.0  # 单图层就绪检查最大耗时（秒）


def _catalog_items_for_environment(items: list) -> list:
    """非 development/test 隐藏 status=placeholder（实验室占位层，机构包可剔除）。"""
    env = (settings.environment or "").strip().lower()
    if env in {"development", "dev", "test", "testing"}:
        return list(items)
    return [item for item in items if getattr(item, "status", None) != "placeholder"]


@router.get("/layers", tags=["catalog"], response_model=LayerCatalogResponse)
def list_layers() -> LayerCatalogResponse:
    catalog = get_layer_catalog()
    visible_items = _catalog_items_for_environment(catalog.items)

    def _check_readiness(item) -> tuple[str, dict]:
        readiness = describe_layer_run_readiness(item.layer_id) or {}
        return item.layer_id, readiness

    layer_readiness: dict[str, dict[str, Any]] = {}
    executor = ThreadPoolExecutor(max_workers=8)
    try:
        futures = {
            executor.submit(_check_readiness, desc): desc for desc in visible_items
        }
        for future in as_completed(futures, timeout=_READINESS_TIMEOUT):
            try:
                layer_id, readiness = future.result(timeout=_READINESS_TIMEOUT)
                layer_readiness[layer_id] = readiness
            except FuturesTimeoutError:
                _logger.warning("Layer readiness check timed out")
            except Exception:
                _logger.warning("Layer readiness check failed", exc_info=True)
    except FuturesTimeoutError:
        # as_completed 整体超时：未完成的 future 直接跳过
        _logger.warning(
            "Layer readiness batch timed out after %.1fs", _READINESS_TIMEOUT
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    items = []
    for descriptor in visible_items:
        readiness = layer_readiness.get(descriptor.layer_id, {})
        items.append(
            descriptor.model_copy(
                update={
                    "run_readiness": readiness.get(
                        "run_readiness", descriptor.run_readiness
                    ),
                    "run_readiness_summary": readiness.get(
                        "run_readiness_summary", descriptor.run_readiness_summary
                    ),
                    "run_readiness_notes": readiness.get(
                        "run_readiness_notes", descriptor.run_readiness_notes
                    ),
                }
            )
        )
    return LayerCatalogResponse(items=items)


@router.get("/geo/transform", tags=["geo"])
def transform_geo_point(
    lng: float, lat: float, source: str, target: str = "EPSG:3857"
) -> dict[str, float | str]:
    try:
        # 归一化旧码连字符写法（'GCJ-02' → 'GCJ02'，'BD-09' → 'BD09'），
        # 保持与旧垫片 transform_point 相同的向后兼容行为
        src = normalize_crs_code(source)
        tgt = normalize_crs_code(target)
        point = crs_transformer.transform_point(lng, lat, src, tgt)
        return {"lng": point.lng, "lat": point.lat, "source": source, "target": target}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/overlay-preview/{layer_id}", tags=["overlay"])
def get_overlay_preview(
    layer_id: str,
    time: str | None = Query(default=None),
    palette: str | None = Query(default=None),
    min_value: float | None = Query(default=None),
    max_value: float | None = Query(default=None),
    nodata_mode: str | None = Query(default=None),
    nodata_color: str | None = Query(default=None),
) -> Response:
    """返回图层的 PNG 预览图（地理配准），供前端 MapLibre image source 使用。

    对于时间序列图层，可通过 `?time=YYYYMMDD` 指定时间标签；
    未指定时使用 default_time。

    有可读源且传入 palette/min/max/nodata 时动态重着色；否则返回烘焙 PNG。
    """
    from app.services.overlay_recolor import render_overlay_preview_styled

    styled = bool(
        (palette and palette.strip())
        or min_value is not None
        or max_value is not None
        or (nodata_mode and nodata_mode.strip())
        or (nodata_color and nodata_color.strip())
    )
    content = render_overlay_preview_styled(
        layer_id,
        time=time,
        palette=palette,
        min_value=min_value,
        max_value=max_value,
        nodata_mode=nodata_mode,
        nodata_color=nodata_color,
    )
    cache = "no-cache, must-revalidate" if styled else "public, max-age=60"
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": cache, "Vary": "Accept-Encoding"},
    )


@router.get("/overlay-tiles/{layer_id}/{z}/{x}/{y}.png", tags=["overlay"])
def get_overlay_tile(
    layer_id: str,
    z: int,
    x: int,
    y: int,
    time: str | None = Query(default=None),
    palette: str | None = Query(default=None),
    min_value: float | None = Query(default=None),
    max_value: float | None = Query(default=None),
    nodata_mode: str | None = Query(default=None),
    nodata_color: str | None = Query(default=None),
) -> Response:
    """Web Mercator XYZ PNG tile for imported / geotiff-backed overlays."""
    from app.services.overlay_tile_service import render_overlay_tile

    spec = get_overlay_spec(layer_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No overlay for layer: {layer_id}")
    source = spec.resolve_source_path(time)
    if source is None or source.suffix.lower() not in {
        ".tif",
        ".tiff",
        ".geotiff",
        ".cog",
    }:
        raise HTTPException(
            status_code=404,
            detail=f"Overlay has no GeoTIFF source for XYZ tiles: {layer_id}",
        )
    try:
        png = render_overlay_tile(
            str(source),
            z,
            x,
            y,
            palette=palette or spec.palette or "viridis",
            min_value=min_value if min_value is not None else spec.vmin,
            max_value=max_value if max_value is not None else spec.vmax,
            nodata_mode=nodata_mode,
            nodata_color=nodata_color,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _logger.warning(
            "overlay tile render failed %s z=%s", layer_id, z, exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Tile render failed: {exc}"
        ) from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=120", "Vary": "Accept-Encoding"},
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
