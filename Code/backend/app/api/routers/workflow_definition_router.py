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
from app.services.workflow_graph_compiler import (
    WorkflowGraphCompileError,
    compile_litegraph_to_workflow_definition,
)

router = APIRouter(prefix="/workflow-definitions", tags=["workflow-definition"])


# ─── 节点模板 ────────────────────────────────────────────────────────────────
@router.get("/node-templates", tags=["workflow-definition"])
def list_node_templates() -> dict[str, Any]:
    """获取所有可用的节点模板，供前端节点面板展示。

    P0-10：未实现执行器的占位节点（executable=False 的 stub）在 production 默认
    从面板隐藏（避免面板承诺未实现功能），development 或显式设
    BACKEND_NODE_STUBS_VISIBLE=true 时可见（供开发中联调）。
    """
    from app.core.config import settings

    templates = get_all_node_templates()
    stubs_hidden = False
    if settings.environment != "development" and not settings.node_stubs_visible:
        templates = [t for t in templates if t.get("executable") is not False]
        stubs_hidden = True
    return {
        "templates": templates,
        "count": len(templates),
        "stubs_hidden": stubs_hidden,
    }


@router.post(
    "/compile",
    dependencies=[Depends(require_write_access)],
    tags=["workflow-definition"],
)
def compile_graph(payload: dict[str, Any]) -> dict[str, Any]:
    """将 LiteGraph 画布编译为 Python provider 可执行的 workflow_definition。"""
    try:
        definition = compile_litegraph_to_workflow_definition(
            workflow_id=str(payload.get("workflow_id") or "canvas_workflow"),
            name=payload.get("name"),
            description=payload.get("description"),
            nodes=payload.get("nodes")
            if isinstance(payload.get("nodes"), list)
            else [],
            links=payload.get("links")
            if isinstance(payload.get("links"), list)
            else [],
        )
    except WorkflowGraphCompileError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"编译失败: {exc}",
        ) from exc
    return {"workflow_definition": definition, "ok": True}


@router.post(
    "/dry-validate",
    dependencies=[Depends(require_write_access)],
    tags=["workflow-definition"],
)
def dry_validate_graph(payload: dict[str, Any]) -> dict[str, Any]:
    """图模式提交前干跑校验：编译 + 静态结构检查，不入队。

    成功返回 ``{ ok: true, workflow_definition, issues: [] }``；
    编译失败返回 422 + 字段级 issues（与提交期校验风格一致）。
    """
    issues: list[dict[str, str]] = []
    try:
        definition = compile_litegraph_to_workflow_definition(
            workflow_id=str(payload.get("workflow_id") or "canvas_workflow"),
            name=payload.get("name"),
            description=payload.get("description"),
            nodes=payload.get("nodes")
            if isinstance(payload.get("nodes"), list)
            else [],
            links=payload.get("links")
            if isinstance(payload.get("links"), list)
            else [],
        )
    except WorkflowGraphCompileError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_type": "validation",
                "user_message": "工作流图未通过预检，请检查节点与连线。",
                "issues": [
                    {
                        "field": "graph",
                        "code": "compile_error",
                        "message": str(exc),
                    }
                ],
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_type": "validation",
                "user_message": "工作流图预检失败。",
                "issues": [
                    {
                        "field": "graph",
                        "code": "compile_error",
                        "message": f"编译失败: {exc}",
                    }
                ],
            },
        ) from exc

    nodes = definition.get("nodes") if isinstance(definition, dict) else None
    if not isinstance(nodes, list) or not nodes:
        issues.append(
            {
                "field": "nodes",
                "code": "empty_graph",
                "message": "工作流图没有可执行节点。",
            }
        )
    else:
        # Compiled nodes use node_type=module + params.module_name; LiteGraph
        # seeds (if ever passed through) use type=module/*.
        _HELPER_MODULES = frozenset(
            {
                "data_source",
                "source",
                "time_range",
                "bbox",
                "number_const",
                "string_const",
                "boolean_const",
                "latlng",
                "map_viewport",
                "output_map_layer",
                "output_file",
            }
        )

        def _compiled_module_name(node: dict[str, Any]) -> str:
            props = (
                node.get("properties")
                if isinstance(node.get("properties"), dict)
                else {}
            )
            params = node.get("params") if isinstance(node.get("params"), dict) else {}
            raw = (
                props.get("module_name")
                or params.get("module_name")
                or node.get("node_class")
                or ""
            )
            name = str(raw).strip()
            if name:
                return name
            ntype = str(node.get("type") or node.get("node_type") or "")
            if "/" in ntype:
                return ntype.split("/", 1)[-1]
            return ntype

        module_nodes = []
        for n in nodes:
            if not isinstance(n, dict):
                continue
            ntype = str(n.get("type") or "")
            node_type = str(n.get("node_type") or "")
            module_name = _compiled_module_name(n)
            if module_name in _HELPER_MODULES:
                continue
            if ntype.startswith("module/") or (
                node_type == "module" and module_name not in {"", "module"}
            ):
                module_nodes.append(n)

        if not module_nodes:
            issues.append(
                {
                    "field": "nodes",
                    "code": "no_module",
                    "message": "图中缺少算法模块节点（module/*）。",
                }
            )
        for node in module_nodes:
            module_name = _compiled_module_name(node)
            if not module_name:
                issues.append(
                    {
                        "field": f"node:{node.get('node_id') or node.get('id')}",
                        "code": "module_name_missing",
                        "message": "模块节点缺少 module_name。",
                    }
                )

    if issues:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_type": "validation",
                "user_message": "工作流图未通过预检，请检查节点配置。",
                "issues": issues,
            },
        )
    return {"ok": True, "workflow_definition": definition, "issues": []}


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow definition not found: {workflow_id}",
        )
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="new_id is required and must be a string",
        )
    # new_name 可选，但若提供则必须是字符串（防止数字等类型污染数据）
    if new_name is not None and not isinstance(new_name, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="new_name must be a string if provided",
        )
    try:
        return wds.duplicate_definition(workflow_id, new_id, new_name)
    except WorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except WorkflowExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
