from urllib.error import HTTPError, URLError

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.api.routers._helpers import service_json_response
from app.services.weather_bridge_service import weather_bridge_service
from app.weatherengine.service import weather_engine_service
from shared.contracts.api_contracts import WeatherPointResponse

router = APIRouter()


def _weather_service_response(service_call) -> JSONResponse:
    try:
        return service_json_response(service_call())
    except RuntimeError as exc:
        detail = str(exc)
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE if "disabled" in detail.lower() or "initialize" in detail.lower() else status.HTTP_500_INTERNAL_SERVER_ERROR
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/weather/point", tags=["weather"], response_model=WeatherPointResponse)
def get_weather_point(
    layer_id: str,
    latitude: float,
    longitude: float,
    model: str | None = None,
    forecast_hours: int = 6,
    place_name: str | None = None,
    provider: str | None = None,
) -> WeatherPointResponse:
    try:
        return weather_engine_service.get_point_weather(
            layer_id=layer_id,
            latitude=latitude,
            longitude=longitude,
            model=model,
            forecast_hours=forecast_hours,
            place_name=place_name,
            provider_id=provider,
        )
    except ValueError as exc:
        detail = str(exc)
        lower = detail.lower()
        if any(
            token in lower
            for token in (
                "no enabled weather provider",
                "is disabled",
                "is not registered",
                "does not support layer",
            )
        ):
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
    except (HTTPError, URLError) as exc:
        detail = "Weather point forecast is temporarily unavailable."
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc


@router.get("/weather/providers-for-layer/{layer_id}", tags=["weather"])
def get_providers_for_layer(layer_id: str, include_disabled: bool = False):
    """List weather providers that declare support for ``layer_id`` (for layer source dropdown)."""
    from app.weatherengine.constants import WEATHER_LAYER_SPECS
    from app.weatherengine.fetch_gateway import list_providers_for_layer
    from app.services.config_service import _ensure_weather_providers_registered

    if layer_id not in WEATHER_LAYER_SPECS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown weather layer: {layer_id}")
    _ensure_weather_providers_registered()
    return {"layer_id": layer_id, "providers": list_providers_for_layer(layer_id, include_disabled=include_disabled)}


@router.get("/weather/workflows", tags=["weather"])
def list_weather_workflows() -> JSONResponse:
    return _weather_service_response(weather_bridge_service.list_workflows_response)


@router.get("/weather/workflows/diagnostics", tags=["weather"])
def get_weather_diagnostics() -> JSONResponse:
    return _weather_service_response(weather_bridge_service.get_diagnostics_response)


@router.get("/weather/workflows/{workflow_name}", tags=["weather"])
def describe_weather_workflow(workflow_name: str) -> JSONResponse:
    return _weather_service_response(lambda: weather_bridge_service.describe_workflow_response(workflow_name))
