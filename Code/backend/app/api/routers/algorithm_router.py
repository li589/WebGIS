from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.api.deps import CredentialContext, get_request_user
from app.api.routers._helpers import service_json_response
from app.core import config
from app.services.python_provider_bridge_service import python_provider_bridge_service

router = APIRouter()


def _deny_if_unauthenticated(cred: CredentialContext | None) -> None:
    """Reject anonymous access when user auth is enabled."""
    if cred is None and config.settings.user_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )


def _algorithm_service_response(service_call) -> JSONResponse:
    try:
        return service_json_response(service_call())
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/algorithm/workflows", tags=["algorithm"])
def list_algorithm_workflows(
    cred: CredentialContext | None = Depends(get_request_user),
) -> JSONResponse:
    _deny_if_unauthenticated(cred)
    return _algorithm_service_response(
        python_provider_bridge_service.list_workflows_response
    )


@router.get("/algorithm/workflows/{workflow_name}", tags=["algorithm"])
def describe_algorithm_workflow(
    workflow_name: str,
    cred: CredentialContext | None = Depends(get_request_user),
) -> JSONResponse:
    _deny_if_unauthenticated(cred)
    return _algorithm_service_response(
        lambda: python_provider_bridge_service.describe_workflow_response(workflow_name)
    )


@router.get("/algorithm/workflows/{workflow_name}/panel-schema", tags=["algorithm"])
def get_algorithm_workflow_panel_schema(
    workflow_name: str,
    cred: CredentialContext | None = Depends(get_request_user),
) -> JSONResponse:
    _deny_if_unauthenticated(cred)
    return _algorithm_service_response(
        lambda: python_provider_bridge_service.get_workflow_panel_schema_response(
            workflow_name
        )
    )


@router.get("/algorithm/workflows/{workflow_name}/ui-schema", tags=["algorithm"])
def get_algorithm_workflow_ui_schema(
    workflow_name: str,
    cred: CredentialContext | None = Depends(get_request_user),
) -> JSONResponse:
    _deny_if_unauthenticated(cred)
    return _algorithm_service_response(
        lambda: python_provider_bridge_service.get_workflow_ui_schema_response(
            workflow_name
        )
    )


@router.get("/algorithm/diagnostics", tags=["algorithm"])
def get_algorithm_diagnostics(
    cred: CredentialContext | None = Depends(get_request_user),
) -> JSONResponse:
    _deny_if_unauthenticated(cred)
    return _algorithm_service_response(
        python_provider_bridge_service.get_diagnostics_response
    )
