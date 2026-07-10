"""
底图代理 API 路由

提供以下端点：
- GET /tiles/providers - 获取所有可用的底图提供商
- GET /tiles/{provider}/{z}/{x}/{y} - 获取 tile 图像
"""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.services.tile_proxy_service import tile_proxy_service, TILE_URL_TEMPLATES


router = APIRouter(prefix="/tiles", tags=["tiles"])


class TileProviderInfo(BaseModel):
    """底图提供商信息"""
    id: str
    provider: str
    requires_transform: bool
    coord_system: str


class TileProvidersResponse(BaseModel):
    """底图提供商列表响应"""
    providers: list[TileProviderInfo]


@router.get("/providers", response_model=TileProvidersResponse)
async def get_tile_providers():
    """
    获取所有可用的底图提供商列表

    Returns:
        底图提供商列表，包含每个提供商是否需要坐标转换等信息
    """
    providers = tile_proxy_service.get_available_providers()
    return TileProvidersResponse(
        providers=[TileProviderInfo(**p) for p in providers]
    )


@router.get("/{provider}/{z}/{x}/{y}")
async def get_tile(
    provider: str,
    z: int,
    x: int,
    y: int,
    use_cache: bool = True,
):
    """
    获取底图 tile 图像

    Args:
        provider: 底图提供商 ID（如 'gaode-street', 'esri-street', 'tianditu-img' 等）
        z: zoom 级别
        x: tile x 坐标
        y: tile y 坐标
        use_cache: 是否使用缓存（默认 True）

    Returns:
        tile 图像数据（PNG/JPEG）
    """
    if z < 0 or z > 18:
        raise HTTPException(status_code=400, detail="Zoom level must be between 0 and 18")

    if x < 0 or y < 0:
        raise HTTPException(status_code=400, detail="Invalid tile coordinates")

    try:
        data = await tile_proxy_service.fetch_tile(
            tile_id=provider,
            x=x,
            y=y,
            z=z,
            use_cache=use_cache,
        )

        # 根据 provider 推断 content-type
        if "baidu" in provider or "gaode" in provider:
            # 高德和百度通常返回 PNG
            content_type = "image/png"
        elif "satellite" in provider or "img" in provider:
            # 影像底图通常是 JPEG
            content_type = "image/jpeg"
        else:
            content_type = "image/png"

        return Response(
            content=data,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-Tile-Provider": provider,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch tile: {str(e)}")


@router.post("/cache/clear")
async def clear_tile_cache():
    """清空 tile 缓存"""
    tile_proxy_service.clear_cache()
    return {"message": "Tile cache cleared"}


@router.get("/cache/stats")
async def get_cache_stats():
    """获取缓存统计信息"""
    return {
        "cached_tiles": len(tile_proxy_service._cache),
        "cache_ttl_seconds": tile_proxy_service._cache_ttl,
    }
