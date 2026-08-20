"""Domain router package.

Split from routes.py (534 lines) into 8 focused router modules:
- health_router: /health
- layer_router: /layers, /geo/transform
- workflow_router: /workflow-runs/*
- runtime_router: /runtime/*, /frontend/commands
- algorithm_router: /algorithm/*
- weather_router: /weather/point, /weather/workflows/*
- provider_router: /provider/workflows/*
- artifact_router: /artifacts/*
"""

from app.api.routers.health_router import router as health_router
from app.api.routers.layer_router import router as layer_router
from app.api.routers.workflow_router import router as workflow_router
from app.api.routers.runtime_router import router as runtime_router
from app.api.routers.algorithm_router import router as algorithm_router
from app.api.routers.weather_router import router as weather_router
from app.api.routers.provider_router import router as provider_router
from app.api.routers.artifact_router import router as artifact_router
from app.api.routers.import_router import router as import_router
from app.api.routers.feedback_router import router as feedback_router
from app.data_io.api.router import router as data_io_router
from app.api.routers.analysis_router import router as analysis_router
from app.api.routers.zonal_stats_router import router as zonal_stats_router
from app.api.routers.workspace_router import router as workspace_router

__all__ = [
    "health_router",
    "layer_router",
    "workflow_router",
    "runtime_router",
    "algorithm_router",
    "weather_router",
    "provider_router",
    "artifact_router",
    "import_router",
    "feedback_router",
    "data_io_router",
    "analysis_router",
    "zonal_stats_router",
    "workspace_router",
]
