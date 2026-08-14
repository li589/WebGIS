"""Unit tests for POST /workflow-definitions/dry-validate handler."""

from __future__ import annotations


import pytest
from fastapi import HTTPException

from app.api.routers.workflow_definition_router import dry_validate_graph


def test_empty_graph_returns_422() -> None:
    with pytest.raises(HTTPException) as ctx:
        dry_validate_graph({"workflow_id": "wf_empty", "nodes": [], "links": []})
    assert ctx.value.status_code == 422, 'ctx.exception.status_code == 422'
    detail = ctx.value.detail
    assert isinstance(detail, dict), 'isinstance(detail, dict)'
    issues = detail.get("issues") or []
    assert issues, 'issues is truthy'
    codes = {i.get("code") for i in issues if isinstance(i, dict)}
    assert codes & {"compile_error", "empty_graph"}, 'codes & {"compile_error", "empty_graph"} is truthy'


def test_valid_module_graph_returns_ok() -> None:
    body = dry_validate_graph(
        {
            "workflow_id": "wf_ok",
            "nodes": [
                {
                    "id": 1,
                    "type": "data/source",
                    "properties": {"path": "/tmp", "dataset_key": "SMAP_L3"},
                },
                {
                    "id": 2,
                    "type": "download/remote_fetch",
                    "properties": {"uri": "", "cred_profile": ""},
                },
            ],
            "links": [[1, 1, 0, 2, 1, "data:source"]],
        }
    )
    assert body.get("ok"), 'body.get("ok") is truthy'
    assert isinstance(body.get("workflow_definition"), dict), 'isinstance(body.get("workflow_definition"), dict)'
    assert body.get("issues") == [], 'body.get("issues") == []'
