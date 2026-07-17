"""工作流定义管理 API 路由

提供 ComfyUI 风格工作流编辑器所需的后端接口：
- GET    /workflow-definitions           列出全部（system + user）
- GET    /workflow-definitions/{id}       获取单个定义
- POST   /workflow-definitions            创建用户工作流
- PUT    /workflow-definitions/{id}       更新用户工作流
- DELETE /workflow-definitions/{id}       删除用户工作流
- POST   /workflow-definitions/{id}/duplicate  复制工作流
- GET    /workflow-node-templates         获取所有可用节点模板
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_write_access
from app.services import workflow_definition_service as wds
from app.services.workflow_definition_service import (
    WorkflowExistsError,
    WorkflowNotFoundError,
)
from app.services.node_template_registry import get_all_node_templates

router = APIRouter(prefix="/workflow-definitions", tags=["workflow-definition"])


# ─── 节点模板 ────────────────────────────────────────────────────────────────
@router.get("/node-templates", tags=["workflow-definition"])
def list_node_templates() -> dict[str, Any]:
    """获取所有可用的节点模板，供前端节点面板展示。"""
    templates = get_all_node_templates()
    return {"templates": templates, "count": len(templates)}


# ─── 工作流定义 CRUD ──────────────────────────────────────────────────────────
@router.get("", tags=["workflow-definition"])
def list_definitions() -> dict[str, Any]:
    """列出所有工作流定义（system + user）。"""
    items = wds.list_definitions()
    return {"items": items, "count": len(items)}


@router.get("/{workflow_id}", tags=["workflow-definition"])
def get_definition(workflow_id: str) -> dict[str, Any]:
    """获取单个工作流定义的完整内容。"""
    definition = wds.get_definition(workflow_id)
    if definition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow definition not found: {workflow_id}")
    return definition


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_write_access)],
    tags=["workflow-definition"],
)
def create_definition(payload: dict[str, Any]) -> dict[str, Any]:
    """创建用户工作流定义。"""
    try:
        return wds.create_definition(payload)
    except WorkflowExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put(
    "/{workflow_id}",
    dependencies=[Depends(require_write_access)],
    tags=["workflow-definition"],
)
def update_definition(workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """更新用户工作流定义。system 定义不可更新。"""
    try:
        return wds.update_definition(workflow_id, payload)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_write_access)],
    tags=["workflow-definition"],
)
def delete_definition(workflow_id: str) -> dict[str, Any]:
    """删除用户工作流定义。system 定义不可删除。"""
    try:
        wds.delete_definition(workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"deleted": workflow_id}


@router.post(
    "/{workflow_id}/duplicate",
    dependencies=[Depends(require_write_access)],
    tags=["workflow-definition"],
)
def duplicate_definition(workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """复制现有工作流定义为新的用户工作流。"""
    new_id = payload.get("new_id")
    new_name = payload.get("new_name")
    if not new_id or not isinstance(new_id, str):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="new_id is required and must be a string")
    # new_name 可选，但若提供则必须是字符串（防止数字等类型污染数据）
    if new_name is not None and not isinstance(new_name, str):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="new_name must be a string if provided")
    try:
        return wds.duplicate_definition(workflow_id, new_id, new_name)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WorkflowExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
