from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.service_name,
        "environment": settings.environment,
    }
