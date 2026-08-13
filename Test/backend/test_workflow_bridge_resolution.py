from __future__ import annotations


import pytest
from app.tasks.workflow_tasks import _explain_no_bridge, resolve_workflow_channel
from shared.contracts.api_contracts import (
    ClientIdentity,
    RuntimeMapContext,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowSubmitRequest,
)


def _bare_analysis_payload(layer_id: str) -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label=f"test {layer_id}",
        layer_id=layer_id,
        priority=WorkflowPriority.normal,
        requested_outputs=["json"],
        client=ClientIdentity(client_id="test-client"),
        map_context=RuntimeMapContext(active_layer_id=layer_id),
    )


def test_overlay_without_engine_explains_static_layer() -> None:
    # catalog 演进：dem-etopo 已绑定 engine=overlay_registry。
    # 校验 engine 已配置但未命中 bridge 的可读说明。
    message = _explain_no_bridge(_bare_analysis_payload("dem-etopo"))
    assert "ETOPO" in message, '"ETOPO" in message'  # display_name（用户提交 4587c70 改为「ETOPO 地形高程」）
    assert "overlay_registry" in message, '"overlay_registry" in message'
    assert "did not match" in message, '"did not match" in message'


def test_resolve_channel_raises_readable_error_for_overlay() -> None:
    # dem-etopo 现有 engine，但仍无 bridge 匹配 → 可读错误说明 engine 未命中。
    with pytest.raises(ValueError) as ctx:
        resolve_workflow_channel(_bare_analysis_payload("dem-etopo"))
    assert "ETOPO" in str(ctx.value), '"ETOPO" in str(ctx.exception)'
    assert "did not match" in str(ctx.value), '"did not match" in str(ctx.exception)'
