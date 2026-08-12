"""Analysis tools API: catalog listing + submit thin wrapper over workflow-runs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_write_access
from app.services.analysis_run_service import AnalysisRunError, submit_analysis_run
from app.services.analysis_tool_catalog import get_tool, list_tools_for_layer
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
    dependencies=[Depends(require_write_access)],
)
def create_analysis_run(payload: AnalysisRunRequest) -> WorkflowAcceptedResponse:
    try:
        return submit_analysis_run(payload)
    except AnalysisRunError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
