"""Shared helpers for domain routers."""
from fastapi.responses import JSONResponse


def service_json_response(service_response) -> JSONResponse:
    """Support both dict and object return formats from bridge services.

    Some bridge services return {"status_code": int, "body": dict} dict format.
    Others return objects with status_code and body attributes.
    """
    if isinstance(service_response, dict):
        return JSONResponse(
            status_code=service_response.get("status_code", 200),
            content=service_response.get("body", {}),
        )
    return JSONResponse(status_code=service_response.status_code, content=service_response.body)
