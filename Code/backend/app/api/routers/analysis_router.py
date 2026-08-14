"""Analysis tools API: catalog listing + submit thin wrapper over workflow-runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    CredentialContext,
    check_resource_access,
    get_request_user,
    require_workflow_run_access,
)
from app.services.analysis_run_service import AnalysisRunError, submit_analysis_run
from app.services.analysis_tool_catalog import get_tool, list_tools_for_layer
from app.services.workflow.submission_service import WorkflowValidationError
from shared.contracts.api_contracts import (
    AnalysisRunRequest,
    AnalysisToolDescriptor,
    AnalysisToolListResponse,
    WorkflowAcceptedResponse,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/tools", response_model=AnalysisToolListResponse)
def get_analysis_tools(
    layer_id: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    overlay_layer_id: str | None = Query(default=None),
    has_vector: bool = Query(default=False),
    has_raster: bool = Query(default=False),
    is_weather: bool = Query(default=False),
    is_point_only: bool = Query(default=False),
) -> AnalysisToolListResponse:
    return list_tools_for_layer(
        layer_id=layer_id,
        source_type=source_type,
        overlay_layer_id=overlay_layer_id,
        has_vector=has_vector,
        has_raster=has_raster,
        is_weather=is_weather,
        is_point_only=is_point_only,
    )


@router.get("/tools/{tool_id}", response_model=AnalysisToolDescriptor)
def get_analysis_tool(tool_id: str) -> AnalysisToolDescriptor:
    tool = get_tool(tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Unknown analysis tool: {tool_id}")
    return tool


@router.post(
    "/runs",
    response_model=WorkflowAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_analysis_run(
    payload: AnalysisRunRequest,
    _run_ok: None = Depends(require_workflow_run_access),
    cred: CredentialContext | None = Depends(get_request_user),
) -> WorkflowAcceptedResponse:
    _cred = cred if isinstance(cred, CredentialContext) else None
    # require_workflow_run_access already gates auth; ACL when cred resolved.
    if _cred is not None:
        if payload.layer_id:
            check_resource_access(_cred, "layer", payload.layer_id)
        if payload.overlay_layer_id:
            check_resource_access(_cred, "layer", payload.overlay_layer_id)
        if payload.zones_overlay_layer_id:
            check_resource_access(_cred, "layer", payload.zones_overlay_layer_id)
    try:
        return submit_analysis_run(
            payload,
            user_id=_cred.user_id if _cred else None,
            role=_cred.role if _cred else None,
        )
    except AnalysisRunError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WorkflowValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_type": "validation",
                "user_message": "分析请求未通过业务校验。",
                "issues": exc.issues,
            },
        ) from exc
    except ValueError as exc:
        detail = str(exc)
        if "capacity" in detail.lower():
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=detail,
            ) from exc
        raise HTTPException(status_code=422, detail=detail) from exc
