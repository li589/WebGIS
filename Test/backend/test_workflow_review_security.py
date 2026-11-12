"""Regression locks for Standard workflow isolation and review.

These tests deliberately exercise server-side helpers, not browser visibility:
knowing another workflow ID must not grant an API mutation path.
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def isolated_definitions(tmp_path, monkeypatch):
    from app.core import config
    from app.services import workflow_definition_service as wds

    monkeypatch.setattr(config.settings, "data_root", str(tmp_path))
    monkeypatch.setattr(wds, "_SEED_SYNC_DONE", True)
    return wds


def _payload(workflow_id: str) -> dict:
    return {
        "workflow_id": workflow_id,
        "name": workflow_id,
        "nodes": [],
        "links": [],
    }


def test_private_workflows_are_isolated_and_guest_cannot_discover(isolated_definitions):
    from app.api.error_codes import ApiError
    from app.api.routers.workflow_definition_router import _deny_if_cannot_mutate_definition
    from app.services.credential_resolver import CredentialContext

    wds = isolated_definitions
    definition = wds.create_definition(_payload("standard_a_private"), owner_user_id=101)
    meta = definition["_meta"]
    assert wds.can_view_definition(meta, role="standard", user_id=101)
    assert not wds.can_view_definition(meta, role="standard", user_id=202)
    assert not wds.can_view_definition(meta, role="demo", user_id=303)

    owner = CredentialContext(source="session", role="standard", user_id=101)
    peer = CredentialContext(source="session", role="standard", user_id=202)
    admin = CredentialContext(source="session", role="admin", user_id=1)
    _deny_if_cannot_mutate_definition("standard_a_private", owner)
    _deny_if_cannot_mutate_definition("standard_a_private", admin)
    with pytest.raises(ApiError) as exc_info:
        _deny_if_cannot_mutate_definition("standard_a_private", peer)
    assert exc_info.value.status_code == 403


def test_submission_freezes_definition_until_admin_decision(isolated_definitions):
    wds = isolated_definitions
    wds.create_definition(_payload("client_flow"), owner_user_id=101)

    submitted = wds.submit_for_review("client_flow", owner_user_id=101, note="please review")
    assert submitted["_meta"]["review_status"] == "submitted"
    assert [x["workflow_id"] for x in wds.list_review_submissions()] == ["client_flow"]
    with pytest.raises(ValueError, match="Submitted"):
        wds.update_definition("client_flow", {"name": "changed"})

    approved = wds.decide_review("client_flow", approved=True, reviewer_user_id=1)
    assert approved["_meta"]["review_status"] == "approved"
    assert approved["_meta"]["published"] is False
    with pytest.raises(ValueError, match="Approved"):
        wds.update_definition("client_flow", {"name": "changed"})


def test_rejected_workflow_returns_to_draft_only_after_owner_edits(isolated_definitions):
    wds = isolated_definitions
    wds.create_definition(_payload("client_revise"), owner_user_id=101)
    wds.submit_for_review("client_revise", owner_user_id=101)
    rejected = wds.decide_review("client_revise", approved=False, reviewer_user_id=1, note="fix inputs")
    assert rejected["_meta"]["review_status"] == "rejected"

    revised = wds.update_definition("client_revise", {"name": "revised"})
    assert revised["_meta"]["review_status"] == "draft"
    assert revised["_meta"]["published"] is False


def test_standard_node_catalogue_rejects_unknown_executor():
    from fastapi import HTTPException
    from app.api.routers.workflow_definition_router import _validate_standard_workflow_nodes

    _validate_standard_workflow_nodes({"nodes": [{"type": "data/source"}]})
    with pytest.raises(HTTPException) as exc_info:
        _validate_standard_workflow_nodes({"nodes": [{"type": "python/arbitrary_script"}]})
    assert exc_info.value.status_code == 422
