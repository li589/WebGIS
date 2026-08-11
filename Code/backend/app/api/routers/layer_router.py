from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
    TimeoutError as FuturesTimeoutError,
)
import logging
import time
from threading import Lock
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.core.config import settings
from app.services.crs import crs_transformer
from app.services.crs.crs_registry import normalize_crs_code
from app.services.layer_catalog import get_layer_catalog, get_layer_category_response
from app.services.overlay_registry import (
    get_overlay_spec,
    list_overlay_ids,
    read_bounds,
)
from app.services.workflow_request_resolver import describe_layer_run_readiness
from shared.contracts.api_contracts import (
    LayerCatalogResponse,
    LayerCategoryResponse,
)

_logger = logging.getLogger(__name__)

router = APIRouter()

_READINESS_TIMEOUT = 8.0  # 单图层就绪检查最大耗时（秒）

# G1-06: 模块级共享 executor + 就绪结果短缓存，避免每请求新建线程池
_readiness_executor = ThreadPoolExecutor(max_workers=8)
_READINESS_CACHE_TTL = 30.0  # 秒
_readiness_cache: dict[str, tuple[dict, float]] = {}
_readiness_cache_lock = Lock()


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
    now = time.time()

    # G1-06: 先查缓存，只对未命中/过期的图层执行就绪检查
    items_to_check = []
    for desc in visible_items:
        cached = _readiness_cache.get(desc.layer_id)
        if cached and now - cached[1] < _READINESS_CACHE_TTL:
            layer_readiness[desc.layer_id] = cached[0]
        else:
            items_to_check.append(desc)

    if items_to_check:
        futures = {
            _readiness_executor.submit(_check_readiness, desc): desc
            for desc in items_to_check
        }
        try:
            for future in as_completed(futures, timeout=_READINESS_TIMEOUT):
                try:
                    layer_id, readiness = future.result(timeout=_READINESS_TIMEOUT)
                    layer_readiness[layer_id] = readiness
                    with _readiness_cache_lock:
                        _readiness_cache[layer_id] = (readiness, time.time())
                except FuturesTimeoutError:
                    _logger.warning("Layer readiness check timed out")
                except Exception:
                    _logger.warning("Layer readiness check failed", exc_info=True)
        except FuturesTimeoutError:
            # as_completed 整体超时：未完成的 future 直接跳过
            _logger.warning(
                "Layer readiness batch timed out after %.1fs", _READINESS_TIMEOUT
            )

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


@router.get(
    "/layers/categories", tags=["catalog"], response_model=LayerCategoryResponse
)
def list_layer_categories() -> LayerCategoryResponse:
    """X1: 后端下发图层分类定义（id / name / icon / accent_color / chip_tone）。

    前端运行时消费此端点获取分类样式，消除前后端分类定义双写。
    前端 ``LAYER_CATEGORIES`` 静态表仅在 API 不可用时作离线兜底。
    """
    return get_layer_category_response()


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


@router.get("/overlays/intersect", tags=["overlay"])
def get_overlays_in_viewport(
    west: float = Query(..., ge=-180, le=360),  # 容许 >180（跨日界线 unwrap）
    south: float = Query(..., ge=-90, le=90),
    east: float = Query(..., ge=-180, le=360),
    north: float = Query(..., ge=-90, le=90),
    zoom: int | None = Query(default=None, ge=0, le=24),
) -> dict[str, Any]:
    """返回与视口相交的 overlay layer_ids（服务端空间索引查询）。

    优先用 spatial.sqlite + R*Tree（``ST_Intersects``）；扩展不可用或表空时
    回退到逐层读 ``bounds.json`` 做 AABB 相交（与原前端 O(N) 过滤等价）。
    空间库就绪时即使零命中也信任结果，不再误扫 bounds.json。

    跨日界线约定：前端对跨日界线视口传 ``east > 180``（unwrap），与
    ``overlay_safe_wgs84_bounds`` 一致。

    回退路径无 zoom 元资料时不过滤（bounds.json / registry 目前无 min/maxzoom）。
    """
    from app.services.spatial_repository import get_spatial_repository

    repo = get_spatial_repository()
    if repo.is_spatial_ready():
        hits = repo.query_intersects(west, south, east, north, zoom=zoom)
        return {"layer_ids": [h["layer_id"] for h in hits], "source": "spatialite"}

    # 回退：扫所有 overlay 的 bounds.json 做 AABB 相交（未导入 / 扩展不可用）
    from app.services.geo_math import overlay_safe_wgs84_bounds

    matched: list[str] = []
    # 视口也按同一日界线展开约定归一化，与空间路径（BuildMBR 用展开后视口）保持同一空间
    vw, vs_, ve, vn = overlay_safe_wgs84_bounds(west, south, east, north)
    for lid in list_overlay_ids():
        try:
            b = read_bounds(lid).get("bounds")
            if not b or len(b) < 4:
                continue
            ow, os_, oe, on = b
            ow, os_, oe, on = overlay_safe_wgs84_bounds(ow, os_, oe, on)
            # AABB 相交（视口与 bounds 都已 unwrap 到同一空间）
            if vw <= oe and ve >= ow and vs_ <= on and vn >= os_:
                matched.append(lid)
        except Exception:
            _logger.debug(
                "overlay %s bounds read failed in fallback", lid, exc_info=True
            )
            continue
    return {"layer_ids": matched, "source": "fallback_bounds_json"}


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
