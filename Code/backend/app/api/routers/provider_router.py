from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.api.deps import CredentialContext, get_request_user
from app.api.routers._helpers import service_json_response
from app.core import config
from app.services.provider_workflow_service import provider_workflow_service

router = APIRouter()


def _deny_if_unauthenticated(cred: CredentialContext | None) -> None:
    """Reject anonymous access when user auth is enabled."""
    if cred is None and config.settings.user_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )


def _provider_service_response(service_call) -> JSONResponse:
    try:
        return service_json_response(service_call())
    except RuntimeError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if "disabled" in detail.lower() or "initialize" in detail.lower()
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/provider/workflows", tags=["provider"])
def list_provider_workflows(
    cred: CredentialContext | None = Depends(get_request_user),
) -> JSONResponse:
    _deny_if_unauthenticated(cred)
    return _provider_service_response(provider_workflow_service.list_workflows_response)


@router.get("/provider/workflows/diagnostics", tags=["provider"])
def get_provider_diagnostics(
    cred: CredentialContext | None = Depends(get_request_user),
) -> JSONResponse:
    _deny_if_unauthenticated(cred)
    return _provider_service_response(
        provider_workflow_service.get_diagnostics_response
    )


@router.get("/provider/workflows/{workflow_name}", tags=["provider"])
def describe_provider_workflow(
    workflow_name: str,
    cred: CredentialContext | None = Depends(get_request_user),
) -> JSONResponse:
    _deny_if_unauthenticated(cred)
    return _provider_service_response(
        lambda: provider_workflow_service.describe_workflow_response(workflow_name)
    )
