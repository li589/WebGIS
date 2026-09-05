"""前端调用流程模拟与鲁棒性测试。

测试覆盖：
1. 模拟前端完整调用流程：submit → poll status → get events → get view → cancel
2. 并发测试：多个 workflow 同时提交，验证容量控制
3. 异常处理鲁棒性：
   - 429 容量超限
   - 404 不存在的 run_id
   - 取消已完成的 workflow
   - 重试不存在的 workflow
   - provider 抛出异常时 unified tile 端点的 503 响应
4. 工作流事件轮询速率限制器行为
5. TileProviderRegistry 并发注册安全性

运行方式：
    $env:BACKEND_OBJECT_STORE_BACKEND='local'
    python -m pytest tests/test_frontend_call_simulation.py -v
"""

from __future__ import annotations

import pytest
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# 确保在 conftest.py 之后执行时 sys.path 已配置
from shared.contracts.api_contracts import (
    ClientIdentity,
    EventChannel,
    ExecutionStatus,
    RuntimeMapContext,
    WorkflowAcceptedResponse,
    WorkflowCommandType,
    WorkflowEvent,
    WorkflowEventsResponse,
    WorkflowPriority,
    WorkflowResourceProfile,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
)


def _build_payload(
    *,
    layer_id: str = "ndvi",
    command_type: WorkflowCommandType = WorkflowCommandType.analysis,
) -> WorkflowSubmitRequest:
    """构造一个合法的 WorkflowSubmitRequest，模拟前端 submitWorkflow() 的负载。"""
    return WorkflowSubmitRequest(
        command_type=command_type,
        layer_id=layer_id,
        priority=WorkflowPriority.normal,
        resource_profile=WorkflowResourceProfile.standard,
        requested_outputs=["json"],
        client=ClientIdentity(client_id="test-frontend-client", session_id="sess-1"),
        map_context=RuntimeMapContext(active_layer_id=layer_id, map_mode="2d"),
        parameters={"hour": 12},
    )


def _build_run_status(
    *,
    run_id: str = "run-test-1",
    status: ExecutionStatus = ExecutionStatus.running,
    progress: int = 50,
) -> WorkflowRunStatusResponse:
    """构造一个 WorkflowRunStatusResponse，模拟后端返回的运行状态。"""
    now = datetime.now(timezone.utc)
    return WorkflowRunStatusResponse(
        run_id=run_id,
        command_type=WorkflowCommandType.analysis,
        status=status,
        progress=progress,
        message="running",
        created_at=now,
        updated_at=now,
        requested_outputs=["json"],
        client=ClientIdentity(client_id="test-frontend-client"),
        map_context=RuntimeMapContext(map_mode="2d"),
        config_overrides={},
        executor_metadata={},
        result_refs=[],
        diagnostics=[],
    )


def _admin_cred():
    """直接调用路由函数时携带的有效 admin 凭据。

    RBAC v2 后匿名调用对工作流端点 fail-closed（401）；
    单测目标是 ValueError→HTTPException 映射，故显式传入 admin 凭据
    而非绕过鉴权语义。
    """
    from app.api.deps import CredentialContext

    return CredentialContext(source="dev_bypass", role="admin")


def test_full_frontend_workflow_lifecycle() -> None:
    """端到端模拟前端调用模式，验证路由→服务委派链完整。

    前端典型调用序列：
    1. POST /workflow-runs (submitWorkflow)
    2. GET /workflow-runs/{run_id} (getWorkflowRun - 轮询)
    3. GET /workflow-runs/{run_id}/events (getWorkflowEvents)
    4. GET /workflow-runs/{run_id}/view (getWorkflowRunView)
    5. POST /workflow-runs/{run_id}/cancel (cancelWorkflowRun)
    """
    from app.api.routers.workflow_router import (
        cancel_workflow_run,
        get_workflow_run,
        list_workflow_events,
        submit_workflow,
    )

    run_id = "run-e2e-1"
    payload = _build_payload()

    # 1. Submit
    accepted = WorkflowAcceptedResponse(
        run_id=run_id,
        status=ExecutionStatus.accepted,
        status_url=f"/workflow-runs/{run_id}",
        events_url=f"/workflow-runs/{run_id}/events",
        created_at=datetime.now(timezone.utc),
        message="工作流已提交",
    )
    with patch(
        "app.api.routers.workflow_router.submission_service.submit_workflow",
        return_value=accepted,
    ):
        result = submit_workflow(payload, cred=_admin_cred())
    assert result.run_id == run_id, 'result.run_id == run_id'
    assert result.status == ExecutionStatus.accepted, 'result.status == ExecutionStatus.accepted'

    # 2. Poll status
    running_status = _build_run_status(
        run_id=run_id, status=ExecutionStatus.running, progress=50
    )
    with patch(
        "app.api.routers.workflow_router.submission_service.get_workflow_run",
        return_value=running_status,
    ):
        status_result = get_workflow_run(run_id, cred=_admin_cred())
    assert status_result is not None, 'status_result is not None'
    assert status_result.status == ExecutionStatus.running, 'status_result.status == ExecutionStatus.running'
    assert status_result.progress == 50, 'status_result.progress == 50'

    # 3. Get events
    events_response = WorkflowEventsResponse(
        run_id=run_id,
        items=[
            WorkflowEvent(
                event_id="evt-1",
                run_id=run_id,
                channel=EventChannel.status,
                message="running",
                created_at=datetime.now(timezone.utc),
            ),
        ],
    )
    request_mock = MagicMock()
    request_mock.headers = {}
    request_mock.client = MagicMock()
    request_mock.client.host = "127.0.0.1"
    with patch(
        "app.api.routers.workflow_router.submission_service.list_workflow_events",
        return_value=events_response,
    ):
        events_result = list_workflow_events(request_mock, run_id, cred=_admin_cred())
    assert events_result.run_id == run_id, 'events_result.run_id == run_id'
    assert len(events_result.items) == 1, 'len(events_result.items) == 1'

    # 4. Get view (via result_view_service)
    from app.api.routers.workflow_router import get_workflow_run_view
    from shared.contracts.api_contracts import (
        WorkflowRunViewResponse,
        WorkflowRunViewSummaryRow,
    )

    view_response = WorkflowRunViewResponse(
        run_id=run_id,
        category="analysis",
        title="Test Workflow",
        subtitle="subtitle",
        status_text="running",
        progress_text="50%",
        metric_rows=[WorkflowRunViewSummaryRow(label="metric", value="12.5")],
        can_show_link=False,
        updated_at=datetime.now(timezone.utc),
    )
    with patch(
        "app.api.routers.workflow_router.result_view_service.get_workflow_run_view",
        return_value=view_response,
    ):
        view_result = get_workflow_run_view(run_id, cred=_admin_cred())
    assert view_result.run_id == run_id, 'view_result.run_id == run_id'
    assert view_result.title == "Test Workflow", 'view_result.title == "Test Workflow"'

    # 5. Cancel
    cancelled_status = _build_run_status(
        run_id=run_id, status=ExecutionStatus.cancelled, progress=100
    )
    with patch(
        "app.api.routers.workflow_router.lifecycle_service.cancel_workflow_run",
        return_value=cancelled_status,
    ):
        cancel_result = cancel_workflow_run(run_id, cred=_admin_cred())
    assert cancel_result.status == ExecutionStatus.cancelled, 'cancel_result.status == ExecutionStatus.cancelled'


def test_submit_returns_429_when_capacity_reached() -> None:
    """容量超限时，路由层应将 ValueError 映射为 HTTPException 429。"""
    from app.api.routers.workflow_router import submit_workflow
    from fastapi import HTTPException

    payload = _build_payload()
    error_msg = "Workflow capacity reached: active_runs=4, limit=4"

    with patch(
        "app.api.routers.workflow_router.submission_service.submit_workflow",
        side_effect=ValueError(error_msg),
    ):
        with pytest.raises(HTTPException) as ctx:
            submit_workflow(payload)
        assert ctx.value.status_code == 429, 'ctx.exception.status_code == 429'
        assert "capacity" in str(ctx.value.detail).lower(), '"capacity" in str(ctx.exception.detail).lower()'


def test_get_workflow_run_returns_none_for_missing_run() -> None:
    """查询不存在的 run_id 时，服务层返回 None，路由层应返回 404。"""
    from app.api.routers.workflow_router import get_workflow_run
    from fastapi import HTTPException

    with patch(
        "app.api.routers.workflow_router.submission_service.get_workflow_run",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as ctx:
            get_workflow_run("run-nonexistent")
        assert ctx.value.status_code == 404, 'ctx.exception.status_code == 404'


def test_cancel_completed_workflow_raises_http_400() -> None:
    """取消已完成的 workflow 时，路由层应将 ValueError 映射为 HTTPException 400。"""
    from app.api.routers.workflow_router import cancel_workflow_run
    from fastapi import HTTPException

    error_msg = "Cannot cancel workflow in terminal state: succeeded"
    with patch(
        "app.api.routers.workflow_router.lifecycle_service.cancel_workflow_run",
        side_effect=ValueError(error_msg),
    ):
        with pytest.raises(HTTPException) as ctx:
            cancel_workflow_run("run-done-1", cred=_admin_cred())
        assert ctx.value.status_code == 400, 'ctx.exception.status_code == 400'
        assert "terminal state" in str(ctx.value.detail), '"terminal state" in str(ctx.exception.detail)'


def test_retry_nonexistent_workflow_raises_http_400() -> None:
    """重试不存在的 workflow 时，路由层应将 ValueError 映射为 HTTPException 400。"""
    from app.api.routers.workflow_router import retry_workflow_run
    from fastapi import HTTPException

    with patch(
        "app.api.routers.workflow_router.retry_dispatcher.retry_workflow_run",
        side_effect=ValueError("Cannot retry: no request found"),
    ):
        with pytest.raises(HTTPException) as ctx:
            retry_workflow_run("run-nonexistent", cred=_admin_cred())
        assert ctx.value.status_code == 400, 'ctx.exception.status_code == 400'
        assert "no request found" in str(ctx.value.detail), '"no request found" in str(ctx.exception.detail)'


def test_concurrent_submissions_respect_capacity_limit() -> None:
    """模拟 5 个并发提交，容量限制为 4，应至少有 1 个被拒绝。

    读侧探针仍可用于预检；正式提交走 save_run_under_capacity 原子预留。
    """
    from app.services.workflow.submission_service import WorkflowSubmissionService

    service = WorkflowSubmissionService.__new__(WorkflowSubmissionService)
    service._repository = MagicMock()
    service._persistence = MagicMock()
    service._transitions = MagicMock()
    service._follow_up = MagicMock()
    service._lifecycle = MagicMock()

    # 模拟 business 池已有 4 个活跃运行（达到上限）
    service._repository.count_active_runs = MagicMock(return_value=4)
    service._persistence.get_effective_config_int = MagicMock(return_value=4)

    # 并发提交 5 个请求
    results: list[Exception | None] = [None] * 5
    barrier = threading.Barrier(5)

    def submit_one(idx: int) -> None:
        try:
            barrier.wait(timeout=5)
            service._assert_workflow_capacity()
        except Exception as exc:
            results[idx] = exc

    threads = [threading.Thread(target=submit_one, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # 所有 5 个线程都应抛出 ValueError（因为 count_active_runs=4 >= limit=4）
    rejected_count = sum(
        1 for r in results if r is not None and "capacity" in str(r).lower()
    )
    assert rejected_count == 5, "All concurrent submissions should be rejected when at capacity"


def test_business_capacity_full_does_not_block_weather_tile_pool() -> None:
    """business 池满时，weather_tile 提交仍可过闸。"""
    from app.services.workflow.submission_service import WorkflowSubmissionService
    from app.services.workflow.run_class import (
        RUN_CLASS_BUSINESS,
        RUN_CLASS_WEATHER_TILE,
    )

    service = WorkflowSubmissionService.__new__(WorkflowSubmissionService)
    service._repository = MagicMock()
    service._persistence = MagicMock()

    def count_side_effect(run_class=None):
        if run_class == RUN_CLASS_BUSINESS:
            return 8
        if run_class == RUN_CLASS_WEATHER_TILE:
            return 0
        return 8

    def config_side_effect(scope, key, default):
        if key == "max_active_runs":
            return 8
        if key == "max_active_weather_tile_runs":
            return 16
        return default

    service._repository.count_active_runs = MagicMock(side_effect=count_side_effect)
    service._persistence.get_effective_config_int = MagicMock(
        side_effect=config_side_effect
    )

    with pytest.raises(ValueError) as biz_ctx:
        service._assert_workflow_capacity(RUN_CLASS_BUSINESS)
    assert "Workflow capacity reached" in str(biz_ctx.value), '"Workflow capacity reached" in str(biz_ctx.exception)'

    # weather_tile 池未满，不应抛错
    service._assert_workflow_capacity(RUN_CLASS_WEATHER_TILE)


def test_weather_tile_capacity_full_does_not_block_business_pool() -> None:
    """weather_tile 池满时，business 提交仍可过闸。"""
    from app.services.workflow.submission_service import WorkflowSubmissionService
    from app.services.workflow.run_class import (
        RUN_CLASS_BUSINESS,
        RUN_CLASS_WEATHER_TILE,
    )

    service = WorkflowSubmissionService.__new__(WorkflowSubmissionService)
    service._repository = MagicMock()
    service._persistence = MagicMock()

    def count_side_effect(run_class=None):
        if run_class == RUN_CLASS_WEATHER_TILE:
            return 16
        if run_class == RUN_CLASS_BUSINESS:
            return 0
        return 16

    def config_side_effect(scope, key, default):
        if key == "max_active_runs":
            return 8
        if key == "max_active_weather_tile_runs":
            return 16
        return default

    service._repository.count_active_runs = MagicMock(side_effect=count_side_effect)
    service._persistence.get_effective_config_int = MagicMock(
        side_effect=config_side_effect
    )

    with pytest.raises(ValueError) as tile_ctx:
        service._assert_workflow_capacity(RUN_CLASS_WEATHER_TILE)
    assert "Weather tile workflow capacity reached" in str(tile_ctx.value), '"Weather tile workflow capacity reached" in str(tile_ctx.exception)'

    service._assert_workflow_capacity(RUN_CLASS_BUSINESS)


def test_concurrent_tile_provider_registration_does_not_crash() -> None:
    """并发注册 provider 不应导致崩溃（list.append 在 CPython 下是原子的，但不保证线程安全）。"""
    from app.services.tile_provider_registry import TileProviderRegistry

    registry = TileProviderRegistry()
    mock_provider = MagicMock()
    mock_provider.matches = MagicMock(return_value=False)

    def register_many(count: int) -> None:
        for _ in range(count):
            registry.register(mock_provider)

    threads = [threading.Thread(target=register_many, args=(50,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # CPython 的 list.append 是原子的，所以 4×50=200 应该都注册成功
    assert len(registry._providers) == 200, 'len(registry._providers) == 200'


def test_concurrent_weather_tile_provider_lazy_init() -> None:
    """WeatherTileProvider 的 _ensure_layer_ids 并发初始化不应崩溃。"""
    from app.services.providers.weather_tile_provider import WeatherTileProvider

    provider = WeatherTileProvider()

    # Mock layer_catalog 返回空列表（避免依赖实际 catalog）
    with patch("app.services.layer_catalog.get_layer_catalog") as mock_catalog:
        mock_catalog.return_value = MagicMock(items=[])

        def call_matches(idx: int) -> bool:
            return provider.matches(f"layer-{idx}")

        threads = [
            threading.Thread(target=call_matches, args=(i,)) for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # 不应崩溃，且 _weather_layer_ids 应已初始化
        assert provider._weather_layer_ids is not None, 'provider._weather_layer_ids is not None'


def test_unified_tile_returns_503_when_provider_raises() -> None:
    """已知底图 id 且 Provider 内部异常时，端点应返回 503 而非 500。"""
    from contextlib import suppress

    from app.services.tile_provider_registry import tile_provider_registry

    # create_app 首次调用会 clear() 并重建默认 provider 注册表；
    # 必须先触发注册，再插入失败 provider，否则插入项被重建清掉
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()

    failing_provider = MagicMock()
    failing_provider.matches = MagicMock(
        side_effect=lambda layer_id: layer_id == "esri-street"
    )
    failing_provider.get_tile = AsyncMock(
        side_effect=RuntimeError("upstream service unavailable")
    )

    # 插入队首，确保先于 BaseMapTileProvider 匹配
    tile_provider_registry._providers.insert(0, failing_provider)
    try:
        client = TestClient(app)

        response = client.get("/unified-tiles/esri-street/5/25/12")
        assert response.status_code == 503, 'response.status_code == 503'
        assert "Tile unavailable" in response.json()["detail"], '"Tile unavailable" in response.json()["detail"]'
    finally:
        # 防御：若注册表在此期间被其它机制重建，remove 不应掩盖真实断言失败
        with suppress(ValueError):
            tile_provider_registry._providers.remove(failing_provider)


def test_unified_tile_returns_404_for_unknown_layer() -> None:
    """未知底图 layer_id 应返回 404（并提示天气走 /weather/tiles）。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    from app.api.deps import get_request_user
    app.dependency_overrides[get_request_user] = lambda: type("MockUser", (), {"id": "test", "role": "admin"})()
    client = TestClient(app)

    response = client.get("/unified-tiles/totally-unknown-layer-id/5/25/12")
    assert response.status_code == 404, 'response.status_code == 404'
    detail = response.json()["detail"]
    assert "Unknown basemap layer_id" in detail, '"Unknown basemap layer_id" in detail'
    assert "/weather/tiles" in detail, '"/weather/tiles" in detail'


def test_weather_tile_validates_hour_parameter() -> None:
    """天气瓦片 hour 超出 [0, 47] 应返回 422。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    from app.api.deps import get_request_user
    app.dependency_overrides[get_request_user] = lambda: type("MockUser", (), {"id": "test", "role": "admin"})()
    client = TestClient(app)

    response = client.get("/weather/tiles/wind-field/5/25/12?hour=-1")
    assert response.status_code == 422, 'response.status_code == 422'

    response = client.get("/weather/tiles/wind-field/5/25/12?hour=48")
    assert response.status_code == 422, 'response.status_code == 422'

    response = client.get("/weather/tiles/wind-field/5/25/12?hour=47")
    assert response.status_code != 422, 'response.status_code != 422'


def test_weather_tile_data_empty_returns_422_not_503() -> None:
    """上游主变量全 null（TileDataEmptyError）应透传 422，而非统一包成 503。"""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.weatherengine.tile_service import TileDataEmptyError

    empty_service = MagicMock()
    empty_service.get_tile = AsyncMock(
        side_effect=TileDataEmptyError(
            "all-null temperature_2m for model=ecmwf_ifs025"
        )
    )

    app = create_app()
    from app.api.deps import get_request_user
    app.dependency_overrides[get_request_user] = lambda: type("MockUser", (), {"id": "test", "role": "admin"})()
    client = TestClient(app)
    with patch(
        "app.api.weather_tile_routes.get_weather_tile_service",
        return_value=empty_service,
    ):
        response = client.get(
            "/weather/tiles/temperature/5/25/12?provider=open-meteo-local"
        )
    assert response.status_code == 422, 'response.status_code == 422'
    assert "no usable data" in response.json()["detail"], '"no usable data" in response.json()["detail"]'


def test_weather_tile_generic_error_still_503() -> None:
    """其它内部异常仍应包成 503（服务不可达，前端退避重试）。"""
    from fastapi.testclient import TestClient

    from app.main import create_app

    failing_service = MagicMock()
    failing_service.get_tile = AsyncMock(side_effect=RuntimeError("upstream boom"))

    app = create_app()
    from app.api.deps import get_request_user
    app.dependency_overrides[get_request_user] = lambda: type("MockUser", (), {"id": "test", "role": "admin"})()
    client = TestClient(app)
    with patch(
        "app.api.weather_tile_routes.get_weather_tile_service",
        return_value=failing_service,
    ):
        response = client.get("/weather/tiles/wind-field/5/25/12")
    assert response.status_code == 503, 'response.status_code == 503'


def test_unified_tile_returns_correct_content_type_for_basemap() -> None:
    """底图瓦片应返回正确的 content_type（image/jpeg 或 image/png）。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    from app.api.deps import get_request_user
    app.dependency_overrides[get_request_user] = lambda: type("MockUser", (), {"id": "test", "role": "admin"})()
    client = TestClient(app)

    with patch(
        "app.services.tile_proxy_service.tile_proxy_service.fetch_tile",
        new_callable=AsyncMock,
        return_value=b"fake-tile-data",
    ):
        # esri-street 含 "street" → image/png
        response = client.get("/unified-tiles/esri-street/5/25/12")
        assert response.status_code == 200, 'response.status_code == 200'
        assert "image/" in response.headers.get("content-type", ""), '"image/" in response.headers.get("content-type", "")'

        # tianditu-img 含 "img" → image/jpeg
        response = client.get("/unified-tiles/tianditu-img/5/25/12")
        assert response.status_code == 200, 'response.status_code == 200'
        assert response.headers.get("content-type") == "image/jpeg", 'response.headers.get("content-type") == "image/jpeg"'


def test_rate_limiter_allows_under_limit() -> None:
    """速率限制以内应放行。"""
    from app.api.routers.workflow_router import EventsPollRateLimiter

    limiter = EventsPollRateLimiter(limit=5, window=timedelta(minutes=1))
    for i in range(5):
        assert limiter.check("192.168.1.1"), f"Request {i+1} should be allowed"


def test_rate_limiter_blocks_over_limit() -> None:
    """超过速率限制应拒绝。"""
    from app.api.routers.workflow_router import EventsPollRateLimiter

    limiter = EventsPollRateLimiter(limit=3, window=timedelta(minutes=1))
    for i in range(3):
        assert limiter.check("10.0.0.1"), 'limiter.check("10.0.0.1") is truthy'

    # 第 4 次应被拒绝
    assert not limiter.check("10.0.0.1"), 'limiter.check("10.0.0.1") is falsy'


def test_rate_limiter_isolates_by_ip() -> None:
    """不同 IP 的限制应相互独立。"""
    from app.api.routers.workflow_router import EventsPollRateLimiter

    limiter = EventsPollRateLimiter(limit=2, window=timedelta(minutes=1))
    assert limiter.check("1.1.1.1"), 'limiter.check("1.1.1.1") is truthy'
    assert limiter.check("1.1.1.1"), 'limiter.check("1.1.1.1") is truthy'
    assert not limiter.check("1.1.1.1"), 'limiter.check("1.1.1.1") is falsy'  # 1.1.1.1 达到上限

    # 2.2.2.2 不受影响
    assert limiter.check("2.2.2.2"), 'limiter.check("2.2.2.2") is truthy'
    assert limiter.check("2.2.2.2"), 'limiter.check("2.2.2.2") is truthy'
    assert not limiter.check("2.2.2.2"), 'limiter.check("2.2.2.2") is falsy'


def test_rate_limiter_window_expiry() -> None:
    """时间窗口过后应重置限制。"""
    from app.api.routers.workflow_router import EventsPollRateLimiter

    limiter = EventsPollRateLimiter(limit=2, window=timedelta(seconds=0))
    assert limiter.check("3.3.3.3"), 'limiter.check("3.3.3.3") is truthy'
    assert limiter.check("3.3.3.3"), 'limiter.check("3.3.3.3") is truthy'

    # 窗口为 0 秒，下一次请求时所有旧时间戳都应被清除
    time.sleep(0.01)
    assert limiter.check("3.3.3.3"), 'limiter.check("3.3.3.3") is truthy'


def test_circuit_breaker_opens_after_threshold_failures() -> None:
    """连续失败达到阈值后，断路器应打开。"""
    from app.weatherengine.client import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
    assert breaker.state == "closed", 'breaker.state == "closed"'

    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == "closed", 'breaker.state == "closed"'  # 2 < 3，仍未打开

    breaker.record_failure()
    assert breaker.state == "open", 'breaker.state == "open"'


def test_circuit_breaker_blocks_requests_when_open() -> None:
    """断路器打开后应拒绝请求。"""
    from app.weatherengine.client import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    breaker.record_failure()
    assert breaker.state == "open", 'breaker.state == "open"'
    assert not breaker.can_pass(), 'breaker.can_pass() is falsy'


def test_circuit_breaker_transitions_to_half_open_after_timeout() -> None:
    """恢复超时后应转为 HALF_OPEN 状态。"""
    from app.weatherengine.client import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
    breaker.record_failure()
    assert breaker.state == "open", 'breaker.state == "open"'

    time.sleep(0.15)
    assert breaker.can_pass(), 'breaker.can_pass() is truthy'  # HALF_OPEN 放行探测
    assert breaker.state == "half_open", 'breaker.state == "half_open"'


def test_circuit_breaker_closes_on_success() -> None:
    """成功请求应关闭断路器。"""
    from app.weatherengine.client import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    breaker.record_failure()
    assert breaker.state == "open", 'breaker.state == "open"'

    # 模拟恢复超时 + HALF_OPEN 探测成功
    breaker._state = breaker._HALF_OPEN
    breaker._half_open_probes_in_flight = 1
    breaker.record_success()
    assert breaker.state == "closed", 'breaker.state == "closed"'


def test_circuit_breaker_reopens_on_half_open_failure() -> None:
    """HALF_OPEN 状态下探测失败应重新打开断路器。"""
    from app.weatherengine.client import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    breaker.record_failure()
    breaker._state = breaker._HALF_OPEN
    breaker._half_open_probes_in_flight = 1

    breaker.record_failure()
    assert breaker.state == "open", 'breaker.state == "open"'


def test_circuit_breaker_thread_safety() -> None:
    """多线程并发记录失败不应导致状态不一致。"""
    from app.weatherengine.client import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=100, recovery_timeout=60.0)

    def record_failures(count: int) -> None:
        for _ in range(count):
            breaker.record_failure()

    threads = [
        threading.Thread(target=record_failures, args=(50,)) for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # 4×50=200 次失败，应已打开
    assert breaker.state == "open", 'breaker.state == "open"'


def test_legacy_tiles_pixel_endpoint_removed() -> None:
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    from app.api.deps import get_request_user
    app.dependency_overrides[get_request_user] = lambda: type("MockUser", (), {"id": "test", "role": "admin"})()
    client = TestClient(app)
    response = client.get("/tiles/esri-street/5/25/12")
    assert response.status_code == 404, 'response.status_code == 404'


def test_unified_tiles_validates_zoom_range() -> None:
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    from app.api.deps import get_request_user
    app.dependency_overrides[get_request_user] = lambda: type("MockUser", (), {"id": "test", "role": "admin"})()
    client = TestClient(app)
    assert client.get("/unified-tiles/esri-street/-1/25/12").status_code == 400, 'client.get("/unified-tiles/esri-street/-1/25/12").status_code == 400'
    assert client.get("/unified-tiles/esri-street/19/25/12").status_code == 400, 'client.get("/unified-tiles/esri-street/19/25/12").status_code == 400'


def test_unified_tiles_rejects_weather_layer_id() -> None:
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    from app.api.deps import get_request_user
    app.dependency_overrides[get_request_user] = lambda: type("MockUser", (), {"id": "test", "role": "admin"})()
    client = TestClient(app)
    response = client.get("/unified-tiles/wind-field/5/25/12")
    assert response.status_code == 404, 'response.status_code == 404'
    assert "/weather/tiles" in response.json().get("detail", ""), '"/weather/tiles" in response.json().get("detail", "")'


def test_runtime_tile_cache_stats() -> None:
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.main import create_app

    # /runtime/tiles/cache/stats 需 config-read 鉴权（require_config_read_access），
    # test 环境无 dev bypass，须提供 service key（同 test_config_contracts.client 模式）。
    app = create_app()
    with patch(
        "app.services.effective_config.get_backend_auth_key",
        return_value="test-key",
    ):
        client = TestClient(app, headers={"X-API-Key": "test-key"})
        response = client.get("/runtime/tiles/cache/stats")
        assert response.status_code == 200, 'response.status_code == 200'
        assert "cached_tiles" in response.json(), '"cached_tiles" in response.json()'
